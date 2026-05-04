"""Parse portfolio manager LLM output (expected JSON) into a decisions dict."""

from __future__ import annotations

import json

from colorama import Fore, Style


def parse_hedge_fund_response(response: object) -> dict | None:
    """Parse a JSON string from the portfolio manager; return None on failure."""
    if response is None:
        print(f"{Fore.YELLOW}Portfolio manager: empty response (no message content).{Style.RESET_ALL}")
        return None
    if not isinstance(response, str):
        print(
            f"{Fore.YELLOW}Portfolio manager: expected a string (JSON), got "
            f"{type(response).__name__}.{Style.RESET_ALL}"
        )
        return None
    stripped = response.strip()
    if not stripped:
        print(f"{Fore.YELLOW}Portfolio manager: blank message — cannot parse decisions.{Style.RESET_ALL}")
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as e:
        preview = stripped if len(stripped) <= 600 else stripped[:597] + "..."
        echo = stripped.startswith("Make trading decisions based on the provided data")
        print(
            f"{Fore.RED}Portfolio manager output was not valid JSON ({e}).{Style.RESET_ALL}\n"
            f"{Fore.CYAN}Hint:{Style.RESET_ALL} The model must return a single JSON object mapping tickers to "
            f"decisions (action, quantity, confidence, reasoning). "
            + (
                "It looks like the model echoed the initial user prompt instead of JSON.\n"
                if echo
                else ""
            )
            + f"{Fore.CYAN}First ~600 chars:{Style.RESET_ALL}\n{preview!r}"
        )
        return None
    except TypeError as e:
        print(f"{Fore.RED}Invalid response type while parsing JSON: {e}{Style.RESET_ALL}")
        return None
    except Exception as e:
        print(f"{Fore.RED}Unexpected error while parsing portfolio manager response: {e}{Style.RESET_ALL}")
        return None
