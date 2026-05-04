"""Utilities for working with Ollama models"""

import os
import platform
import subprocess
import sys
import time
from typing import List
from urllib.parse import urlparse

import questionary
import requests
from colorama import Fore, Style
from . import docker

# Constants
DEFAULT_OLLAMA_SERVER_URL = "http://localhost:11434"

# After stalls/timeouts on localhost, restart Ollama and ensure this tag exists (`ollama pull`).
DEFAULT_RECOVERY_OLLAMA_MODEL = "qwen3.5:9b"


def _get_ollama_base_url() -> str:
    """Return the configured Ollama base URL, trimming any trailing slash."""
    url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_SERVER_URL)
    if not url:
        url = DEFAULT_OLLAMA_SERVER_URL
    return url.rstrip("/")


def _get_ollama_endpoint(path: str) -> str:
    """Build a full Ollama API endpoint from the configured base URL."""
    base = _get_ollama_base_url()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _candidate_ollama_base_urls() -> list[tuple[str, str]]:
    """Return (label, base_url) pairs to probe for a running Ollama API (deduplicated)."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(label: str, raw: str) -> None:
        raw = (raw or "").strip()
        if not raw:
            return
        if not raw.startswith("http"):
            raw = f"http://{raw}"
        url = raw.rstrip("/")
        if url not in seen:
            seen.add(url)
            out.append((label, url))

    env_base = os.environ.get("OLLAMA_BASE_URL", "").strip()
    if env_base:
        add("OLLAMA_BASE_URL (current environment)", env_base)
    host = os.environ.get("OLLAMA_HOST", "").strip()
    if host and not env_base:
        if "://" in host:
            add("OLLAMA_HOST (current environment)", host)
        elif ":" in host and not host.startswith("http"):
            add("OLLAMA_HOST (current environment)", f"http://{host}")
        else:
            add("OLLAMA_HOST (current environment)", f"http://{host}:11434")

    add("Local machine (localhost)", "http://localhost:11434")
    add("Local machine (127.0.0.1)", "http://127.0.0.1:11434")
    add("Docker Desktop host (host.docker.internal)", "http://host.docker.internal:11434")
    add("Docker Compose service name 'ollama'", "http://ollama:11434")
    return out


def ollama_base_url_is_local() -> bool:
    """True when OLLAMA_BASE_URL points at this machine (safe to taskkill / restart)."""
    raw = _get_ollama_base_url()
    try:
        u = urlparse(raw)
    except Exception:
        return False
    host = (u.hostname or "").lower().strip()
    return host in ("localhost", "127.0.0.1", "::1")


def auto_restart_on_stall_enabled() -> bool:
    """Allow automatic local restart after stall detection (CLI). Disable with OLLAMA_AUTO_RESTART_ON_STALL=0."""
    return os.environ.get("OLLAMA_AUTO_RESTART_ON_STALL", "1").strip().lower() not in ("0", "false", "no", "off")


def _stop_local_ollama_processes() -> None:
    """Best-effort: terminate local Ollama so `ollama serve` can be started cleanly."""
    system = platform.system().lower()
    if system == "windows":
        subprocess.run(
            ["taskkill", "/F", "/IM", "ollama.exe"],
            capture_output=True,
            text=True,
            timeout=90,
        )
    elif system in ("darwin", "linux"):
        subprocess.run(
            ["pkill", "-f", "ollama serve"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        subprocess.run(
            ["pkill", "-f", "ollama runner"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    time.sleep(2)


def restart_local_ollama_and_ensure_model(
    model_name: str | None = None,
    *,
    pull_if_missing: bool = True,
) -> tuple[bool, str]:
    """
    Stop local Ollama, start `ollama serve`, optionally pull the recovery model.
    Skips non-local OLLAMA_BASE_URL hosts (Docker/remote).
    """
    tag = (model_name or DEFAULT_RECOVERY_OLLAMA_MODEL).strip()
    if not tag:
        return False, "No model tag specified."
    if not ollama_base_url_is_local():
        return False, "OLLAMA_BASE_URL is not localhost; automatic restart skipped."
    if not is_ollama_installed():
        return False, "Ollama CLI not found on PATH."

    _stop_local_ollama_processes()
    if not start_ollama_server():
        return False, "Failed to start Ollama after stop."

    if pull_if_missing:
        available = get_locally_available_models()
        if tag not in available:
            if not download_model(tag):
                return False, f"Ollama is up but failed to pull {tag}."

    return True, f"Ollama restarted; {tag} is available."


def probe_ollama_at_base(base_url: str, timeout: float = 2.5) -> tuple[bool, list[str]]:
    """Return (ok, model_names) for GET /api/tags on the given Ollama base URL."""
    base = base_url.rstrip("/")
    try:
        response = requests.get(f"{base}/api/tags", timeout=timeout)
        if response.status_code != 200:
            return False, []
        data = response.json()
        models = data.get("models") or []
        names = [str(m.get("name", "")) for m in models if m.get("name")]
        return True, names
    except requests.RequestException:
        return False, []


def discover_ollama_instances(timeout_per_host: float = 2.5) -> list[tuple[str, str, list[str]]]:
    """Return (label, base_url, local_model_names) for each reachable Ollama server."""
    found: list[tuple[str, str, list[str]]] = []
    for label, url in _candidate_ollama_base_urls():
        ok, names = probe_ollama_at_base(url, timeout=timeout_per_host)
        if ok:
            found.append((label, url, names))
    return found


def _preset_models_installed(server_models: list[str]) -> list[str]:
    """Which preset names from ollama_models.json exist on this server (exact tag match)."""
    try:
        from src.llm.models import OLLAMA_MODELS
    except Exception:
        return []
    presets = [m.model_name for m in OLLAMA_MODELS]
    server_set = set(server_models)
    return [p for p in presets if p in server_set]


def print_discovered_ollama_instances(instances: list[tuple[str, str, list[str]]]) -> None:
    """Print reachable Ollama instances and how they line up with this repo's preset models."""
    from src.llm.models import OLLAMA_MODELS

    catalog_n = len(OLLAMA_MODELS)
    print(f"\n{Fore.CYAN}Ollama servers reachable from this script{Style.RESET_ALL}")
    if not instances:
        print(
            f"  {Fore.YELLOW}None detected.{Style.RESET_ALL} Tried: "
            + ", ".join(url for _, url in _candidate_ollama_base_urls())
        )
        print(f"  Install from https://ollama.com/download then start the Ollama app or run `ollama serve`.")
        return
    for label, url, models in instances:
        presets_here = _preset_models_installed(models)
        if models:
            preset_note = f"{Fore.GREEN}{len(presets_here)}/{catalog_n}{Style.RESET_ALL} catalog presets pulled (see src/llm/ollama_models.json)"
        else:
            preset_note = "no models pulled yet on this server"
        print(f"  {Fore.GREEN}OK{Style.RESET_ALL}  {label}")
        print(f"       URL: {url}")
        print(f"       Local tags: {len(models)}  ({preset_note})")
        if presets_here:
            print(f"       Presets ready: {', '.join(presets_here)}")
    print(
        f"\n  {Fore.CYAN}Tip:{Style.RESET_ALL} Preset model names match `src/llm/ollama_models.json`. "
        f"Run `ollama pull <name>` for any missing tag.\n"
    )


def prompt_select_ollama_instance(
    instances: list[tuple[str, str, list[str]]] | None = None,
) -> str | None:
    """
    Let the user pick which Ollama base URL to use and set OLLAMA_BASE_URL for this process.
    Returns the chosen base URL, or None if cancelled / skipped.
    """
    if instances is None:
        instances = discover_ollama_instances()

    if not instances:
        print(f"{Fore.YELLOW}No Ollama API responded on the usual addresses.{Style.RESET_ALL}")
        if not questionary.confirm("Enter a custom Ollama base URL?", default=True).ask():
            return None
        url = questionary.text("Base URL (example: http://192.168.1.10:11434):").ask()
        if not url or not str(url).strip():
            return None
        url = str(url).strip().rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        os.environ["OLLAMA_BASE_URL"] = url
        print(f"{Fore.GREEN}OLLAMA_BASE_URL set to {url}{Style.RESET_ALL}\n")
        return url

    choices = [
        questionary.Choice(f"{lbl}  |  {url}  ({len(mdl)} tags)", value=url) for lbl, url, mdl in instances
    ]
    choices.append(questionary.Choice("Other (type base URL)", value="__custom__"))

    picked = questionary.select(
        "Select the Ollama instance to use for this run:",
        choices=choices,
        style=questionary.Style(
            [
                ("selected", "fg:green bold"),
                ("pointer", "fg:green bold"),
                ("highlighted", "fg:green"),
                ("answer", "fg:green bold"),
            ]
        ),
    ).ask()

    if picked is None:
        return None
    if picked == "__custom__":
        url = questionary.text("Ollama base URL:").ask()
        if not url or not str(url).strip():
            return None
        url = str(url).strip().rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
    else:
        url = str(picked).strip().rstrip("/")

    os.environ["OLLAMA_BASE_URL"] = url
    print(f"{Fore.GREEN}Using Ollama at {url}{Style.RESET_ALL}\n")
    return url


def ensure_ollama_ready_for_run() -> None:
    """
    Sanity check: the Ollama HTTP API must respond at the configured base URL before the app continues.
    Call this after OLLAMA_BASE_URL is set (or when relying on the default localhost:11434).
    Exits with code 1 if GET /api/tags does not succeed.
    """
    base = _get_ollama_base_url()
    ok, _ = probe_ollama_at_base(base, timeout=4.0)
    if ok:
        return
    print(f"\n{Fore.RED}Ollama sanity check failed.{Style.RESET_ALL}")
    print(f"  Expected a running Ollama server at: {base}")
    print(f"  Tried: GET {base}/api/tags (no HTTP 200 response).")
    print("  Install: https://ollama.com/download")
    print("  Start: launch the Ollama app, or run `ollama serve` in a terminal.")
    print("  Remote host: set OLLAMA_BASE_URL, e.g. http://192.168.1.10:11434\n")
    sys.exit(1)


def _env_truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def apply_amd_radeon_vulkan_effective_env() -> None:
    """
    When OLLAMA_AMD_RADEON_VULKAN=1, enable Ollama's experimental Vulkan path and pin the first Vulkan GPU
    by default (GGML_VK_VISIBLE_DEVICES=0). Values only apply to this process and children (e.g. `ollama serve`
    started from here). A separately installed Ollama tray app must set the same variables on its service.
    See https://docs.ollama.com/gpu (Vulkan GPU Support).
    """
    if not _env_truthy(os.environ.get("OLLAMA_AMD_RADEON_VULKAN")):
        return
    os.environ.setdefault("OLLAMA_VULKAN", "1")
    os.environ.setdefault("GGML_VK_VISIBLE_DEVICES", "0")
    vk_dev = os.environ.get("GGML_VK_VISIBLE_DEVICES", "0")
    print(
        f"{Fore.CYAN}OLLAMA_AMD_RADEON_VULKAN=1:{Style.RESET_ALL} set "
        f"{Fore.GREEN}OLLAMA_VULKAN=1{Style.RESET_ALL} and "
        f"{Fore.GREEN}GGML_VK_VISIBLE_DEVICES={vk_dev}{Style.RESET_ALL} for this process "
        f"(first Vulkan-visible GPU). Override GGML_VK_VISIBLE_DEVICES if you use multiple GPUs.\n"
    )


def print_amd_radeon_vulkan_service_reminder() -> None:
    """After a successful /api/tags check, remind users that a standalone Ollama app needs the same env on its process."""
    if not _env_truthy(os.environ.get("OLLAMA_AMD_RADEON_VULKAN")):
        return
    print(
        f"{Fore.CYAN}AMD Radeon + Vulkan:{Style.RESET_ALL} if Ollama was started as a separate app/service, "
        "set OLLAMA_VULKAN=1 (and GGML_VK_VISIBLE_DEVICES as needed) on that process and restart it so "
        "inference uses Vulkan on your Radeon GPU. Details: https://docs.ollama.com/gpu\n"
    )


def ensure_ollama_ready_for_run_with_amd_hint() -> None:
    ensure_ollama_ready_for_run()
    print_amd_radeon_vulkan_service_reminder()


_QUANT_MARKERS = (
    "q2_", "q3_", "q4_", "q5_", "q6_", "q8_", "q4_k", "q5_k", "q6_k", "q8_k",
    "iq2", "iq3", "iq4", "f16", "fp16", "bf16",
)


def model_tag_has_explicit_quant(model_name: str) -> bool:
    low = model_name.lower()
    return any(m in low for m in _QUANT_MARKERS)


def warn_suboptimal_quant_for_amd_vulkan(model_name: str) -> None:
    """
    With OLLAMA_AMD_RADEON_VULKAN=1, nudge users toward explicit GGUF quants on the Ollama tag for predictable VRAM use.
    """
    if not _env_truthy(os.environ.get("OLLAMA_AMD_RADEON_VULKAN")):
        return
    if model_tag_has_explicit_quant(model_name):
        return
    print(
        f"{Fore.YELLOW}Quantization hint (AMD Radeon + Vulkan):{Style.RESET_ALL} model tag {model_name!r} "
        "does not show an explicit GGUF quant level."
    )
    print(
        "  Typical sweet spots: q4_K_M or q4_0 (speed/VRAM), q5_K_M (quality if VRAM allows). "
        "Avoid full fp16 on consumer Radeon unless you have headroom."
    )
    print("  Example: ollama pull llama3.1:8b-instruct-q4_K_M\n")


OLLAMA_DOWNLOAD_URL = {"darwin": "https://ollama.com/download/darwin", "windows": "https://ollama.com/download/windows", "linux": "https://ollama.com/download/linux"}  # macOS  # Windows  # Linux
INSTALLATION_INSTRUCTIONS = {"darwin": "curl -fsSL https://ollama.com/install.sh | sh", "windows": "# Download from https://ollama.com/download/windows and run the installer", "linux": "curl -fsSL https://ollama.com/install.sh | sh"}


def is_ollama_installed() -> bool:
    """Check if Ollama is installed on the system."""
    system = platform.system().lower()

    if system == "darwin" or system == "linux":  # macOS or Linux
        try:
            result = subprocess.run(["which", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return result.returncode == 0
        except Exception:
            return False
    elif system == "windows":  # Windows
        try:
            result = subprocess.run(["where", "ollama"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
            return result.returncode == 0
        except Exception:
            return False
    else:
        return False  # Unsupported OS


def is_ollama_server_running() -> bool:
    """Check if the Ollama server is running."""
    endpoint = _get_ollama_endpoint("/api/tags")
    try:
        response = requests.get(endpoint, timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


def get_locally_available_models() -> List[str]:
    """Get a list of models that are already downloaded locally."""
    if not is_ollama_server_running():
        return []

    try:
        endpoint = _get_ollama_endpoint("/api/tags")
        response = requests.get(endpoint, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data["models"]] if "models" in data else []
        return []
    except requests.RequestException:
        return []


def start_ollama_server() -> bool:
    """Start the Ollama server if it's not already running."""
    if is_ollama_server_running():
        print(f"{Fore.GREEN}Ollama server is already running.{Style.RESET_ALL}")
        return True

    system = platform.system().lower()

    try:
        if system == "darwin" or system == "linux":  # macOS or Linux
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        elif system == "windows":  # Windows
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        else:
            print(f"{Fore.RED}Unsupported operating system: {system}{Style.RESET_ALL}")
            return False

        # Wait for server to start
        for _ in range(10):  # Try for 10 seconds
            if is_ollama_server_running():
                print(f"{Fore.GREEN}Ollama server started successfully.{Style.RESET_ALL}")
                return True
            time.sleep(1)

        print(f"{Fore.RED}Failed to start Ollama server. Timed out waiting for server to become available.{Style.RESET_ALL}")
        return False
    except Exception as e:
        print(f"{Fore.RED}Error starting Ollama server: {e}{Style.RESET_ALL}")
        return False


def install_ollama() -> bool:
    """Install Ollama on the system."""
    system = platform.system().lower()
    if system not in OLLAMA_DOWNLOAD_URL:
        print(f"{Fore.RED}Unsupported operating system for automatic installation: {system}{Style.RESET_ALL}")
        print(f"Please visit https://ollama.com/download to install Ollama manually.")
        return False

    if system == "darwin":  # macOS
        print(f"{Fore.YELLOW}Ollama for Mac is available as an application download.{Style.RESET_ALL}")

        # Default to offering the app download first for macOS users
        if questionary.confirm("Would you like to download the Ollama application?", default=True).ask():
            try:
                import webbrowser

                webbrowser.open(OLLAMA_DOWNLOAD_URL["darwin"])
                print(f"{Fore.YELLOW}Please download and install the application, then restart this program.{Style.RESET_ALL}")
                print(f"{Fore.CYAN}After installation, you may need to open the Ollama app once before continuing.{Style.RESET_ALL}")

                # Ask if they want to try continuing after installation
                if questionary.confirm("Have you installed the Ollama app and opened it at least once?", default=False).ask():
                    # Check if it's now installed
                    if is_ollama_installed() and start_ollama_server():
                        print(f"{Fore.GREEN}Ollama is now properly installed and running!{Style.RESET_ALL}")
                        return True
                    else:
                        print(f"{Fore.RED}Ollama installation not detected. Please restart this application after installing Ollama.{Style.RESET_ALL}")
                        return False
                return False
            except Exception as e:
                print(f"{Fore.RED}Failed to open browser: {e}{Style.RESET_ALL}")
                return False
        else:
            # Only offer command-line installation as a fallback for advanced users
            if questionary.confirm("Would you like to try the command-line installation instead? (For advanced users)", default=False).ask():
                print(f"{Fore.YELLOW}Attempting command-line installation...{Style.RESET_ALL}")
                try:
                    install_process = subprocess.run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                    if install_process.returncode == 0:
                        print(f"{Fore.GREEN}Ollama installed successfully via command line.{Style.RESET_ALL}")
                        return True
                    else:
                        print(f"{Fore.RED}Command-line installation failed. Please use the app download method instead.{Style.RESET_ALL}")
                        return False
                except Exception as e:
                    print(f"{Fore.RED}Error during command-line installation: {e}{Style.RESET_ALL}")
                    return False
            return False
    elif system == "linux":  # Linux
        print(f"{Fore.YELLOW}Installing Ollama...{Style.RESET_ALL}")
        try:
            # Run the installation command as a single command
            install_process = subprocess.run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            if install_process.returncode == 0:
                print(f"{Fore.GREEN}Ollama installed successfully.{Style.RESET_ALL}")
                return True
            else:
                print(f"{Fore.RED}Failed to install Ollama. Error: {install_process.stderr}{Style.RESET_ALL}")
                return False
        except Exception as e:
            print(f"{Fore.RED}Error during Ollama installation: {e}{Style.RESET_ALL}")
            return False
    elif system == "windows":  # Windows
        print(f"{Fore.YELLOW}Automatic installation on Windows is not supported.{Style.RESET_ALL}")
        print(f"Please download and install Ollama from: {OLLAMA_DOWNLOAD_URL['windows']}")

        # Ask if they want to open the download page
        if questionary.confirm("Do you want to open the Ollama download page in your browser?").ask():
            try:
                import webbrowser

                webbrowser.open(OLLAMA_DOWNLOAD_URL["windows"])
                print(f"{Fore.YELLOW}After installation, please restart this application.{Style.RESET_ALL}")

                # Ask if they want to try continuing after installation
                if questionary.confirm("Have you installed Ollama?", default=False).ask():
                    # Check if it's now installed
                    if is_ollama_installed() and start_ollama_server():
                        print(f"{Fore.GREEN}Ollama is now properly installed and running!{Style.RESET_ALL}")
                        return True
                    else:
                        print(f"{Fore.RED}Ollama installation not detected. Please restart this application after installing Ollama.{Style.RESET_ALL}")
                        return False
            except Exception as e:
                print(f"{Fore.RED}Failed to open browser: {e}{Style.RESET_ALL}")
        return False

    return False


def download_model(model_name: str) -> bool:
    """Download an Ollama model."""
    if not is_ollama_server_running():
        if not start_ollama_server():
            return False

    print(f"{Fore.YELLOW}Downloading model {model_name}...{Style.RESET_ALL}")
    print(f"{Fore.CYAN}This may take a while depending on your internet speed and the model size.{Style.RESET_ALL}")
    print(f"{Fore.CYAN}The download is happening in the background. Please be patient...{Style.RESET_ALL}")

    try:
        # Use the Ollama CLI to download the model
        process = subprocess.Popen(
            ["ollama", "pull", model_name],
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout to capture all output
            text=True,
            bufsize=1,  # Line buffered
            encoding='utf-8',  # Explicitly use UTF-8 encoding
            errors='replace'   # Replace any characters that cannot be decoded
        )
        
        # Show some progress to the user
        print(f"{Fore.CYAN}Download progress:{Style.RESET_ALL}")

        # For tracking progress
        last_percentage = 0
        last_phase = ""
        bar_length = 40

        while True:
            output = process.stdout.readline()
            if output == "" and process.poll() is not None:
                break
            if output:
                output = output.strip()
                # Try to extract percentage information using a more lenient approach
                percentage = None
                current_phase = None

                # Example patterns in Ollama output:
                # "downloading: 23.45 MB / 42.19 MB [================>-------------] 55.59%"
                # "downloading model: 76%"
                # "pulling manifest: 100%"

                # Check for percentage in the output
                import re

                percentage_match = re.search(r"(\d+(\.\d+)?)%", output)
                if percentage_match:
                    try:
                        percentage = float(percentage_match.group(1))
                    except ValueError:
                        percentage = None

                # Try to determine the current phase (downloading, extracting, etc.)
                phase_match = re.search(r"^([a-zA-Z\s]+):", output)
                if phase_match:
                    current_phase = phase_match.group(1).strip()

                # If we found a percentage, display a progress bar
                if percentage is not None:
                    # Only update if there's a significant change (avoid flickering)
                    if abs(percentage - last_percentage) >= 1 or (current_phase and current_phase != last_phase):
                        last_percentage = percentage
                        if current_phase:
                            last_phase = current_phase

                        # Create a progress bar
                        filled_length = int(bar_length * percentage / 100)
                        bar = "█" * filled_length + "░" * (bar_length - filled_length)

                        # Build the status line with the phase if available
                        phase_display = f"{Fore.CYAN}{last_phase.capitalize()}{Style.RESET_ALL}: " if last_phase else ""
                        status_line = f"\r{phase_display}{Fore.GREEN}{bar}{Style.RESET_ALL} {Fore.YELLOW}{percentage:.1f}%{Style.RESET_ALL}"

                        # Print the status line without a newline to update in place
                        print(status_line, end="", flush=True)
                else:
                    # If we couldn't extract a percentage but have identifiable output
                    if "download" in output.lower() or "extract" in output.lower() or "pulling" in output.lower():
                        # Don't print a newline for percentage updates
                        if "%" in output:
                            print(f"\r{Fore.GREEN}{output}{Style.RESET_ALL}", end="", flush=True)
                        else:
                            print(f"{Fore.GREEN}{output}{Style.RESET_ALL}")

        # Wait for the process to finish
        return_code = process.wait()

        # Ensure we print a newline after the progress bar
        print()

        if return_code == 0:
            print(f"{Fore.GREEN}Model {model_name} downloaded successfully!{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}Failed to download model {model_name}. Check your internet connection and try again.{Style.RESET_ALL}")
            return False
    except Exception as e:
        print(f"\n{Fore.RED}Error downloading model {model_name}: {e}{Style.RESET_ALL}")
        return False


def ensure_ollama_and_model(model_name: str) -> bool:
    """Ensure Ollama is installed, running, and the requested model is available."""
    ollama_url = _get_ollama_base_url()
    env_override = os.environ.get("OLLAMA_BASE_URL")

    # If an explicit base URL is provided (including Docker defaults), use the remote workflow
    if env_override or ollama_url.startswith("http://ollama:") or ollama_url.startswith("http://host.docker.internal:"):
        return docker.ensure_ollama_and_model(model_name, ollama_url)

    # Regular flow for environments that rely on the local Ollama install
    # Check if Ollama is installed
    if not is_ollama_installed():
        print(f"{Fore.YELLOW}Ollama is not installed on your system.{Style.RESET_ALL}")
        
        # Ask if they want to install it
        if questionary.confirm("Do you want to install Ollama?").ask():
            if not install_ollama():
                return False
        else:
            print(f"{Fore.RED}Ollama is required to use local models.{Style.RESET_ALL}")
            return False
    
    # Make sure the server is running
    if not is_ollama_server_running():
        print(f"{Fore.YELLOW}Starting Ollama server...{Style.RESET_ALL}")
        if not start_ollama_server():
            return False
    
    # Check if the model is already downloaded
    available_models = get_locally_available_models()
    if model_name not in available_models:
        print(f"{Fore.YELLOW}Model {model_name} is not available locally.{Style.RESET_ALL}")
        
        # Ask if they want to download it
        model_size_info = ""
        if "70b" in model_name:
            model_size_info = " This is a large model (up to several GB) and may take a while to download."
        elif "34b" in model_name or "8x7b" in model_name:
            model_size_info = " This is a medium-sized model (1-2 GB) and may take a few minutes to download."
        
        if questionary.confirm(f"Do you want to download the {model_name} model?{model_size_info} The download will happen in the background.").ask():
            return download_model(model_name)
        else:
            print(f"{Fore.RED}The model is required to proceed.{Style.RESET_ALL}")
            return False
    
    return True


def delete_model(model_name: str) -> bool:
    """Delete a locally downloaded Ollama model."""
    # Check if we're running in Docker
    in_docker = os.environ.get("OLLAMA_BASE_URL", "").startswith("http://ollama:") or os.environ.get("OLLAMA_BASE_URL", "").startswith("http://host.docker.internal:")
    
    # In Docker environment, delegate to docker module
    if in_docker:
        ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
        return docker.delete_model(model_name, ollama_url)
        
    # Non-Docker environment
    if not is_ollama_server_running():
        if not start_ollama_server():
            return False
    
    print(f"{Fore.YELLOW}Deleting model {model_name}...{Style.RESET_ALL}")
    
    try:
        # Use the Ollama CLI to delete the model
        process = subprocess.run(["ollama", "rm", model_name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if process.returncode == 0:
            print(f"{Fore.GREEN}Model {model_name} deleted successfully.{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.RED}Failed to delete model {model_name}. Error: {process.stderr}{Style.RESET_ALL}")
            return False
    except Exception as e:
        print(f"{Fore.RED}Error deleting model {model_name}: {e}{Style.RESET_ALL}")
        return False


# Add this at the end of the file for command-line usage
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Ollama model manager")
    parser.add_argument("--check-model", help="Check if model exists and download if needed")
    args = parser.parse_args()

    if args.check_model:
        print(f"Ensuring Ollama is installed and model {args.check_model} is available...")
        result = ensure_ollama_and_model(args.check_model)
        sys.exit(0 if result else 1)
    else:
        print("No action specified. Use --check-model to check if a model exists.")
        sys.exit(1)
