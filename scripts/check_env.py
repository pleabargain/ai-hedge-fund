#!/usr/bin/env python3
"""Print which API-related env vars are set (masked) and ping Financial Datasets (AAPL)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KEY_NAMES: list[tuple[str, str]] = [
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
    ("GROQ_API_KEY", "Groq"),
    ("DEEPSEEK_API_KEY", "DeepSeek"),
    ("GOOGLE_API_KEY", "Google Gemini (GOOGLE_API_KEY)"),
    ("GEMINI_API_KEY", "Google Gemini (GEMINI_API_KEY)"),
    ("XAI_API_KEY", "xAI"),
    ("MOONSHOT_API_KEY", "Moonshot / Kimi"),
    ("OPENROUTER_API_KEY", "OpenRouter"),
    ("FINANCIAL_DATASETS_API_KEY", "Financial Datasets (market data)"),
    ("GIGACHAT_API_KEY", "GigaChat"),
    ("GIGACHAT_USER", "GigaChat (user+password flow)"),
    ("AZURE_OPENAI_API_KEY", "Azure OpenAI"),
    ("OLLAMA_BASE_URL", "Ollama HTTP API base URL"),
    ("OLLAMA_AMD_RADEON_VULKAN", "Ollama preset: AMD Radeon + Vulkan (see README)"),
    ("OLLAMA_VULKAN", "Ollama experimental Vulkan GPU backend (1=on)"),
    ("GGML_VK_VISIBLE_DEVICES", "Vulkan-visible GPU index for llama.cpp (e.g. 0)"),
]


def load_dotenv_optional() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def mask(val: str, head: int = 4, tail: int = 4) -> str:
    if not val or not val.strip():
        return "(empty)"
    s = val.strip()
    if len(s) <= head + tail + 3:
        return "***"
    return f"{s[:head]}...{s[-tail:]}"


def print_key_status() -> None:
    print("=== API-related environment variables ===\n")
    for env_name, label in KEY_NAMES:
        v = os.environ.get(env_name)
        if v and str(v).strip():
            print(f"  [set] {label:<42} {env_name} = {mask(str(v))}")
        else:
            print(f"  [---] {label:<42} {env_name}")
    print()


def ping_financial_datasets() -> int:
    ticker = "AAPL"
    end = date.today()
    start = end - timedelta(days=7)
    query = (
        f"ticker={ticker}&interval=day&interval_multiplier=1"
        f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
    )
    url = f"https://api.financialdatasets.ai/prices/?{query}"
    key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    key_stripped = str(key).strip() if key else ""
    headers: dict[str, str] = {
        # Cloudflare often blocks Python-urllib; match a typical requests client.
        "User-Agent": "python-requests/2.32.3",
        "Accept": "application/json",
    }
    if key_stripped:
        headers["X-API-KEY"] = key_stripped

    print("=== Financial Datasets API (same endpoint as src/tools/api.py) ===\n")
    print(f"  Ticker: {ticker} (free-tier ticker; works with or without API key)\n")
    sent_key = bool(key_stripped)
    print(
        f"  X-API-KEY: {'sent' if sent_key else 'omitted (anonymous free tier: AAPL, GOOGL, NVDA, TSLA per financialdatasets.ai)'}\n"
    )

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} {e.reason}")
        snippet = e.read().decode(errors="replace")[:400]
        if snippet.strip():
            print(f"  Body (truncated): {snippet!r}")
        if e.code in (401, 403):
            print("\n  Get a key: https://financialdatasets.ai/ (sign up, dashboard, copy API key)")
            if e.code == 403 and "1010" in snippet:
                print(
                    "  If you see error 1010, Cloudflare may be blocking this client; "
                    "retry on your machine or set FINANCIAL_DATASETS_API_KEY and run again."
                )
        return 1
    except urllib.error.URLError as e:
        print(f"  Network / URL error: {e}")
        return 1

    print(f"  HTTP {code} OK\n")
    try:
        data = json.loads(body)
        prices = data.get("prices") or []
        print(f"  Parsed: {len(prices)} daily row(s) for {ticker}")
        if prices:
            last = prices[-1]
            close = last.get("close")
            d = last.get("time") or last.get("date")
            print(f"  Latest sample: date={d!r} close={close!r}")
    except json.JSONDecodeError:
        print(f"  (Could not parse JSON; first 200 chars): {body[:200]!r}")
    return 0


def print_ollama_sanity_status() -> None:
    """Advisory GET /api/tags (same probe as when the main CLI selects Ollama); does not change exit code."""
    base = (os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").strip().rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    url = f"{base}/api/tags"
    print("=== Ollama (local LLM / --ollama) ===\n")
    print(f"  Target: {url}\n")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "python-requests/2.32.3", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status != 200:
                print(f"  Status: HTTP {resp.status} (main app will exit if you choose Ollama without fixing this.)")
                return
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: Ollama not usable at this URL for local runs.")
        return
    except urllib.error.URLError as e:
        print(f"  Not reachable: {e}")
        print("  (Ignore if you only use cloud LLMs. The main script runs an API tags sanity check when Ollama is selected.)")
        return
    try:
        data = json.loads(body)
        n = len(data.get("models") or [])
    except json.JSONDecodeError:
        n = 0
    print(f"  OK: Ollama responded ({n} local model tag(s) reported).")
    amd = (os.environ.get("OLLAMA_AMD_RADEON_VULKAN") or "").strip().lower()
    if amd in ("1", "true", "yes", "on"):
        vk = os.environ.get("OLLAMA_VULKAN", "")
        dev = os.environ.get("GGML_VK_VISIBLE_DEVICES", "")
        print(
            f"  AMD Radeon + Vulkan preset active for this Python process: "
            f"OLLAMA_VULKAN={vk!r} GGML_VK_VISIBLE_DEVICES={dev!r}. "
            "The Ollama desktop/service process must set the same if it was started separately."
        )


def apply_amd_vulkan_preset_if_configured() -> None:
    """Match main CLI: OLLAMA_AMD_RADEON_VULKAN=1 sets OLLAMA_VULKAN and GGML_VK_VISIBLE_DEVICES for this process."""
    root_s = str(ROOT)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    try:
        from src.utils.ollama import apply_amd_radeon_vulkan_effective_env

        apply_amd_radeon_vulkan_effective_env()
    except ImportError:
        pass


def main() -> int:
    load_dotenv_optional()
    apply_amd_vulkan_preset_if_configured()
    print_key_status()
    print_ollama_sanity_status()
    print()
    return ping_financial_datasets()


if __name__ == "__main__":
    sys.exit(main())
