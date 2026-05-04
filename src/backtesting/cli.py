from __future__ import annotations

import argparse
import sys
from argparse import Namespace
from datetime import datetime
from dateutil.relativedelta import relativedelta

from colorama import Fore, Style, init
import questionary

from .engine import BacktestEngine
from src.cli.input import resolve_use_ollama_and_instance
from src.llm.models import LLM_ORDER, OLLAMA_LLM_ORDER, get_model_info, ModelProvider
from src.utils.analysts import ANALYST_ORDER
from src.main import run_hedge_fund
from src.utils.ollama import ensure_ollama_and_model, warn_suboptimal_quant_for_amd_vulkan


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="Run backtesting engine (modular)")
    parser.add_argument("--tickers", type=str, required=False, help="Comma-separated tickers")
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=(datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d"),
        help="Start date YYYY-MM-DD",
    )
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--margin-requirement", type=float, default=0.0)
    parser.add_argument("--analysts", type=str, required=False)
    parser.add_argument("--analysts-all", action="store_true")
    parser.add_argument("--ollama", action="store_true")

    args = parser.parse_args()
    init(autoreset=True)

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else []

    # Analysts selection is simplified; no interactive prompts here
    if args.analysts_all:
        selected_analysts = [a[1] for a in ANALYST_ORDER]
    elif args.analysts:
        selected_analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
    else:
        # Interactive analyst selection (same as legacy backtester)
        choices = questionary.checkbox(
            "Use the Space bar to select/unselect analysts.",
            choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
            instruction="\n\nPress 'a' to toggle all.\n\nPress Enter when done to run the hedge fund.",
            validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
            style=questionary.Style(
                [
                    ("checkbox-selected", "fg:green"),
                    ("selected", "fg:green noinherit"),
                    ("highlighted", "noinherit"),
                    ("pointer", "noinherit"),
                ]
            ),
        ).ask()
        if not choices:
            print("\n\nInterrupt received. Exiting...")
            return 1
        selected_analysts = choices
        print(
            f"\nSelected analysts: "
            f"{', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}\n"
        )

    # Model selection: same Ollama discovery / prompts as src/cli/input.py
    use_ollama = resolve_use_ollama_and_instance(Namespace(ollama=args.ollama, model=None))
    if use_ollama:
        print(f"{Fore.CYAN}Using Ollama for local LLM inference.{Style.RESET_ALL}")
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            model_name = OLLAMA_LLM_ORDER[0][1]
            print(f"{Fore.CYAN}Non-interactive:{Style.RESET_ALL} default Ollama model {model_name}")
        else:
            model_name = questionary.select(
                "Select your Ollama model:",
                choices=[questionary.Choice(display, value=value) for display, value, _ in OLLAMA_LLM_ORDER],
                style=questionary.Style(
                    [
                        ("selected", "fg:green bold"),
                        ("pointer", "fg:green bold"),
                        ("highlighted", "fg:green"),
                        ("answer", "fg:green bold"),
                    ]
                ),
            ).ask()
            if not model_name:
                print("\n\nInterrupt received. Exiting...")
                return 1
            if model_name == "-":
                model_name = questionary.text("Enter the custom model name:").ask()
                if not model_name:
                    print("\n\nInterrupt received. Exiting...")
                    return 1
        if not ensure_ollama_and_model(model_name):
            print(f"{Fore.RED}Cannot proceed without Ollama and the selected model.{Style.RESET_ALL}")
            return 1
        warn_suboptimal_quant_for_amd_vulkan(model_name)
        model_provider = ModelProvider.OLLAMA.value
        print(
            f"\nSelected {Fore.CYAN}Ollama{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n"
        )
    else:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            model_name, model_provider = LLM_ORDER[0][1], LLM_ORDER[0][2]
            print(f"{Fore.CYAN}Non-interactive mode:{Style.RESET_ALL} using {model_provider} / {model_name}")
        else:
            model_choice = questionary.select(
                "Select your LLM model:",
                choices=[questionary.Choice(display, value=(name, provider)) for display, name, provider in LLM_ORDER],
                style=questionary.Style(
                    [
                        ("selected", "fg:green bold"),
                        ("pointer", "fg:green bold"),
                        ("highlighted", "fg:green"),
                        ("answer", "fg:green bold"),
                    ]
                ),
            ).ask()
            if not model_choice:
                print("\n\nInterrupt received. Exiting...")
                return 1
            model_name, model_provider = model_choice
            model_info = get_model_info(model_name, model_provider)
            if model_info and model_info.is_custom():
                model_name = questionary.text("Enter the custom model name:").ask()
                if not model_name:
                    print("\n\nInterrupt received. Exiting...")
                    return 1
            print(
                f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n"
            )

    engine = BacktestEngine(
        agent=run_hedge_fund,
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        model_name=model_name,
        model_provider=model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=args.margin_requirement,
    )

    metrics = engine.run_backtest()
    values = engine.get_portfolio_values()

    # Minimal terminal output (no plots)
    if values:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}ENGINE RUN COMPLETE{Style.RESET_ALL}")
        last_value = values[-1]["Portfolio Value"]
        start_value = values[0]["Portfolio Value"]
        total_return = (last_value / start_value - 1.0) * 100.0 if start_value else 0.0
        print(f"Total Return: {Fore.GREEN if total_return >= 0 else Fore.RED}{total_return:.2f}%{Style.RESET_ALL}")
    if metrics.get("sharpe_ratio") is not None:
        print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    if metrics.get("sortino_ratio") is not None:
        print(f"Sortino: {metrics['sortino_ratio']:.2f}")
    if metrics.get("max_drawdown") is not None:
        md = abs(metrics["max_drawdown"]) if metrics["max_drawdown"] is not None else 0.0
        if metrics.get("max_drawdown_date"):
            print(f"Max DD: {md:.2f}% on {metrics['max_drawdown_date']}")
        else:
            print(f"Max DD: {md:.2f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())




