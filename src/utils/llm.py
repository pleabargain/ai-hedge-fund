"""Helper functions for LLM"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pydantic import BaseModel
from src.llm.models import get_model, get_model_info
from src.utils.progress import progress
from src.graph.state import AgentState

_ollama_stall_recovery_lock = threading.Lock()
_ollama_stall_recovery_done = False


def reset_ollama_stall_recovery_flag() -> None:
    """Reset once-per-run guard (call at start of `run_hedge_fund`)."""
    global _ollama_stall_recovery_done
    _ollama_stall_recovery_done = False


def _stall_like_llm_exception(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    msg = str(exc).lower()
    needles = (
        "timeout",
        "timed out",
        "connection refused",
        "connection error",
        "econnrefused",
        "10061",
        "broken pipe",
        "reset by peer",
        "failed to establish",
        "read timed out",
    )
    return any(n in msg for n in needles)


def _try_recover_local_ollama_after_stall(
    state: AgentState | None,
    model_provider: str,
    agent_name: str | None,
    exc: BaseException,
) -> None:
    global _ollama_stall_recovery_done
    if state is None:
        return
    if str(model_provider).strip().lower() != "ollama":
        return
    if not _stall_like_llm_exception(exc):
        return

    from src.utils import ollama as ollama_util

    if not ollama_util.auto_restart_on_stall_enabled():
        progress.set_infra_alert(
            "Ollama request stalled or failed. Set OLLAMA_AUTO_RESTART_ON_STALL=1 for automatic local restart."
        )
        return
    if not ollama_util.ollama_base_url_is_local():
        progress.set_infra_alert(
            "Ollama stalled (remote OLLAMA_BASE_URL). Restart Ollama on that machine manually."
        )
        return

    with _ollama_stall_recovery_lock:
        if _ollama_stall_recovery_done:
            return
        _ollama_stall_recovery_done = True

    progress.set_infra_alert(
        "Ollama stopped responding — restarting local server and ensuring qwen3.5:9b."
    )
    print(
        f"\nOllama stall detected ({type(exc).__name__}); restarting local Ollama + pull "
        f"{ollama_util.DEFAULT_RECOVERY_OLLAMA_MODEL} if missing."
    )
    ok, detail = ollama_util.restart_local_ollama_and_ensure_model()
    progress.set_infra_alert(detail if ok else f"Recover failed: {detail}")
    print(("OK — " if ok else "FAILED — ") + detail)


def call_llm(
    prompt: any,
    pydantic_model: type[BaseModel],
    agent_name: str | None = None,
    state: AgentState | None = None,
    max_retries: int = 3,
    default_factory=None,
) -> BaseModel:
    """
    Makes an LLM call with retry logic, handling both JSON supported and non-JSON supported models.

    Args:
        prompt: The prompt to send to the LLM
        pydantic_model: The Pydantic model class to structure the output
        agent_name: Optional name of the agent for progress updates and model config extraction
        state: Optional state object to extract agent-specific model configuration
        max_retries: Maximum number of retries (default: 3)
        default_factory: Optional factory function to create default response on failure

    Returns:
        An instance of the specified Pydantic model
    """
    
    # Extract model configuration if state is provided and agent_name is available
    if state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        # Use system defaults when no state or agent_name is provided
        model_name = "gpt-4.1"
        model_provider = "OPENAI"

    # Extract API keys from state if available
    api_keys = None
    if state:
        request = state.get("metadata", {}).get("request")
        if request and hasattr(request, 'api_keys'):
            api_keys = request.api_keys

    model_info = get_model_info(model_name, model_provider)
    llm = get_model(model_name, model_provider, api_keys)

    # For non-JSON support models, we can use structured output
    if not (model_info and not model_info.has_json_mode()):
        llm = llm.with_structured_output(
            pydantic_model,
            method="json_mode",
        )

    invoke_timeout: float | None = None
    if state:
        raw_timeout = state.get("metadata", {}).get("llm_call_timeout_seconds")
        if isinstance(raw_timeout, (int, float)) and float(raw_timeout) > 0:
            invoke_timeout = float(raw_timeout)

    # Call the LLM with retries
    for attempt in range(max_retries):
        try:
            # Call the LLM (optional wall-clock timeout per attempt — helps when a provider hangs)
            if invoke_timeout is not None:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(llm.invoke, prompt)
                    try:
                        result = future.result(timeout=invoke_timeout)
                    except FuturesTimeoutError:
                        raise TimeoutError(f"LLM invoke exceeded {invoke_timeout}s") from None
            else:
                result = llm.invoke(prompt)

            # For non-JSON support models, we need to extract and parse the JSON manually
            if model_info and not model_info.has_json_mode():
                parsed_result = extract_json_from_response(result.content)
                if parsed_result:
                    return pydantic_model(**parsed_result)
            else:
                return result

        except Exception as e:
            _try_recover_local_ollama_after_stall(state, model_provider, agent_name, e)
            if agent_name:
                msg = str(e)
                if "exceeded" in msg.lower() or isinstance(e, TimeoutError):
                    progress.update_status(agent_name, None, f"Timeout — retry {attempt + 1}/{max_retries}")
                else:
                    progress.update_status(agent_name, None, f"Error - retry {attempt + 1}/{max_retries}")

            if attempt == max_retries - 1:
                print(f"Error in LLM call after {max_retries} attempts: {e}")
                # Use default_factory if provided, otherwise create a basic default
                if default_factory:
                    return default_factory()
                return create_default_response(pydantic_model)

    # This should never be reached due to the retry logic above
    return create_default_response(pydantic_model)


def create_default_response(model_class: type[BaseModel]) -> BaseModel:
    """Creates a safe default response based on the model's fields."""
    default_values = {}
    for field_name, field in model_class.model_fields.items():
        if field.annotation == str:
            default_values[field_name] = "Error in analysis, using default"
        elif field.annotation == float:
            default_values[field_name] = 0.0
        elif field.annotation == int:
            default_values[field_name] = 0
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ == dict:
            default_values[field_name] = {}
        else:
            # For other types (like Literal), try to use the first allowed value
            if hasattr(field.annotation, "__args__"):
                default_values[field_name] = field.annotation.__args__[0]
            else:
                default_values[field_name] = None

    return model_class(**default_values)


def extract_json_from_response(content: str) -> dict | None:
    """Extracts JSON from a response, handling markdown-wrapped and raw JSON formats."""
    try:
        # 1. Try markdown code block with ```json
        json_start = content.find("```json")
        if json_start != -1:
            json_text = content[json_start + 7:]  # Skip past ```json
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    pass

        # 2. Try markdown code block without json specifier
        json_start = content.find("```")
        if json_start != -1:
            json_text = content[json_start + 3:]
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    pass

        # 3. Try to parse the entire content as JSON
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            pass

        # 4. Find the first top-level JSON object by matching braces
        brace_start = content.find("{")
        if brace_start != -1:
            depth = 0
            for i, char in enumerate(content[brace_start:], brace_start):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(content[brace_start:i + 1])
                        except json.JSONDecodeError:
                            break

    except Exception as e:
        print(f"Error extracting JSON from response: {e}")
    return None


def get_agent_model_config(state, agent_name):
    """
    Get model configuration for a specific agent from the state.
    Falls back to global model configuration if agent-specific config is not available.
    Always returns valid model_name and model_provider values.
    """
    request = state.get("metadata", {}).get("request")
    
    if request and hasattr(request, 'get_agent_model_config'):
        # Get agent-specific model configuration
        model_name, model_provider = request.get_agent_model_config(agent_name)
        # Ensure we have valid values
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, 'value') else str(model_provider)
    
    # Fall back to global configuration (system defaults)
    model_name = state.get("metadata", {}).get("model_name") or "gpt-4.1"
    model_provider = state.get("metadata", {}).get("model_provider") or "OPENAI"
    
    # Convert enum to string if necessary
    if hasattr(model_provider, 'value'):
        model_provider = model_provider.value
    
    return model_name, model_provider
