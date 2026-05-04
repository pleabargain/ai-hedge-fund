import sys
import time
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from colorama import Fore, Style, init
import questionary
from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.graph.state import AgentState
from src.utils.display import print_trading_output
from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes
from src.utils.progress import progress
from src.utils.visualize import save_graph_as_png
from src.cli.input import (
    parse_cli_inputs,
)
from src.reporting.html_export import default_export_html_path, write_research_report_html
from src.reporting.run_timing import append_run_timing_record, compute_adaptive_report_timeout
from src.utils.llm import reset_ollama_stall_recovery_flag
from src.tools.api import reset_financial_datasets_error_report_dedupe
from src.utils.portfolio_json import parse_hedge_fund_response

import json

# Load environment variables from .env file
load_dotenv()

init(autoreset=True)


def derive_checkpoint_html_path(output_path: str | None) -> Path:
    """Sidecar partial checkpoint next to the final HTML path."""
    if output_path:
        p = Path(output_path)
        return p.with_name(p.stem + ".partial" + p.suffix)
    return Path("outputs") / "research_report.partial.html"


def build_run_result_dict(final_state: dict | None, *, run_meta: dict) -> dict:
    """Turn LangGraph channel state into print/export payload."""
    if not final_state:
        return {"decisions": {}, "analyst_signals": {}, "_run_meta": run_meta}
    messages = final_state.get("messages") or []
    content = messages[-1].content if messages else None
    decisions = parse_hedge_fund_response(content) if content else None
    if not isinstance(decisions, dict):
        decisions = {}
    analyst_signals = (final_state.get("data") or {}).get("analyst_signals") or {}
    return {"decisions": decisions, "analyst_signals": analyst_signals, "_run_meta": run_meta}


##### Run the Hedge Fund #####
def run_hedge_fund(
    tickers: list[str],
    start_date: str,
    end_date: str,
    portfolio: dict,
    show_reasoning: bool = False,
    selected_analysts: list[str] = [],
    model_name: str = "gpt-4.1",
    model_provider: str = "OpenAI",
    *,
    report_timeout_seconds: float | None = None,
    llm_call_timeout_seconds: float | None = None,
    export_html_checkpoint_path: Path | str | None = None,
    checkpoint_interval_seconds: float = 15.0,
    checkpoint_context: dict | None = None,
    emit_timing_footer: bool = True,
):
    """
    Stream LangGraph execution so we can checkpoint HTML between nodes, enforce coarse wall-clock
    limits between steps, and surface hung LLM calls via llm_call_timeout_seconds on metadata.
    """
    reset_ollama_stall_recovery_flag()
    reset_financial_datasets_error_report_dedupe()
    progress.set_infra_alert(None)
    progress.reset_for_new_run()
    # Start progress tracking
    progress.start()
    run_wall_started = time.monotonic()

    checkpoint_path: Path | None = Path(export_html_checkpoint_path) if export_html_checkpoint_path else None
    ctx = checkpoint_context or {}

    def write_checkpoint(last_state: dict | None, banner: str) -> None:
        if not checkpoint_path or not last_state:
            return
        rm = {
            "partial": True,
            "reason": "checkpoint",
            "elapsed_sec": round(time.monotonic() - t0, 3),
        }
        payload = build_run_result_dict(last_state, run_meta=rm)
        snapshot = {k: deepcopy(v) for k, v in progress.agent_status.items()}
        write_research_report_html(
            result=payload,
            tickers=ctx.get("tickers", tickers),
            start_date=ctx.get("start_date", start_date),
            end_date=ctx.get("end_date", end_date),
            model_name=ctx.get("model_name", model_name),
            model_provider=ctx.get("model_provider", model_provider),
            output_path=str(checkpoint_path),
            status_banner=banner,
            progress_snapshot=snapshot,
            infra_alert=progress.infra_alert,
            wall_clock_seconds=float(rm["elapsed_sec"]),
        )

    try:
        workflow = create_workflow(selected_analysts if selected_analysts else None)
        compiled = workflow.compile()

        meta: dict = {
            "show_reasoning": show_reasoning,
            "model_name": model_name,
            "model_provider": model_provider,
        }
        if llm_call_timeout_seconds is not None and llm_call_timeout_seconds > 0:
            meta["llm_call_timeout_seconds"] = llm_call_timeout_seconds

        initial_state = {
            "messages": [
                HumanMessage(
                    content="Make trading decisions based on the provided data.",
                )
            ],
            "data": {
                "tickers": tickers,
                "portfolio": portfolio,
                "start_date": start_date,
                "end_date": end_date,
                "analyst_signals": {},
            },
            "metadata": meta,
        }

        last_state: dict | None = None
        t0 = time.monotonic()
        interrupted = False
        timed_out = False
        last_ckpt_mono = float("-inf")
        min_gap = float(checkpoint_interval_seconds) if checkpoint_interval_seconds and checkpoint_interval_seconds > 0 else 0.0

        try:
            for state in compiled.stream(initial_state, stream_mode="values"):
                last_state = state
                now_mono = time.monotonic()
                if checkpoint_path and (now_mono - last_ckpt_mono) >= min_gap:
                    write_checkpoint(
                        state,
                        "Graph checkpoint — latest analyst outputs merged into analyst_signals.",
                    )
                    last_ckpt_mono = now_mono
                if report_timeout_seconds is not None and (now_mono - t0) > float(report_timeout_seconds):
                    timed_out = True
                    break
        except KeyboardInterrupt:
            interrupted = True

        if timed_out and checkpoint_path and last_state:
            write_checkpoint(
                last_state,
                f"Run stopped: wall-clock limit (~{report_timeout_seconds}s from start). "
                "Partial data below; tune timeouts if this fires too early.",
            )
        if interrupted and checkpoint_path and last_state:
            write_checkpoint(last_state, "Interrupted (Ctrl+C); partial checkpoint refreshed.")

        elapsed = round(time.monotonic() - t0, 3)
        completed = bool(last_state is not None and not interrupted and not timed_out)
        reason: str | None = None
        if timed_out:
            reason = (
                f"Stopped after report wall-clock limit (~{report_timeout_seconds}s between LangGraph yields). "
                "Increase --report-timeout-seconds or tune --report-timeout-adaptive."
            )
        elif interrupted:
            reason = "Interrupted by user (Ctrl+C); exporting last merged LangGraph state."
        elif last_state is None:
            reason = "Run produced no LangGraph state before exit."
            completed = False

        run_meta = {
            "partial": not completed,
            "reason": reason,
            "elapsed_sec": elapsed,
            "timed_out": timed_out,
            "interrupted": interrupted,
        }
        return build_run_result_dict(last_state, run_meta=run_meta)
    finally:
        wall_total = round(time.monotonic() - run_wall_started, 3)
        progress.stop()
        if emit_timing_footer:
            progress.print_run_timing_footer(
                wall_seconds=wall_total,
                model_name=model_name,
                model_provider=model_provider,
            )


def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None):
    """Create the workflow with selected analysts."""
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)

    # Get analyst nodes from the configuration
    analyst_nodes = get_analyst_nodes()

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = list(analyst_nodes.keys())
    # Add selected analyst nodes
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)
        workflow.add_edge("start_node", node_name)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_manager", portfolio_management_agent)

    # Connect selected analysts to risk management
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_manager")
    workflow.add_edge("portfolio_manager", END)

    workflow.set_entry_point("start_node")
    return workflow


if __name__ == "__main__":
    inputs = parse_cli_inputs(
        description="Run the hedge fund trading system",
        require_tickers=True,
        default_months_back=None,
        include_graph_flag=True,
        include_reasoning_flag=True,
    )

    tickers = inputs.tickers
    selected_analysts = inputs.selected_analysts

    report_timeout_val: float | None = None
    if inputs.report_timeout_adaptive:
        report_timeout_val = compute_adaptive_report_timeout(
            Path(inputs.report_timing_history_path),
            ratio=float(inputs.report_timeout_ratio),
            floor_seconds=float(inputs.report_timeout_floor_seconds),
            fallback_seconds=float(inputs.report_timeout_fallback_seconds),
        )
        print(
            f"{Fore.CYAN}Adaptive report timeout:{Style.RESET_ALL} "
            f"{Fore.GREEN}{report_timeout_val:.1f}s{Style.RESET_ALL} "
            f"(ratio={inputs.report_timeout_ratio}, history={inputs.report_timing_history_path})\n"
        )
    elif inputs.report_timeout_seconds is not None:
        report_timeout_val = float(inputs.report_timeout_seconds)

    export_final_path: str | None = None
    checkpoint_path: Path | None = None
    if inputs.export_html:
        export_final_path = inputs.export_html_path or str(default_export_html_path(tickers))
        checkpoint_path = derive_checkpoint_html_path(export_final_path)
        interval = float(inputs.checkpoint_html_interval_seconds or 0.0)
        print(
            f"{Fore.CYAN}HTML export:{Style.RESET_ALL} final "
            f"{Fore.GREEN}{Path(export_final_path).resolve()}{Style.RESET_ALL} "
            f"(checkpoints: {Fore.GREEN}{checkpoint_path.resolve()}{Style.RESET_ALL}, "
            f"every ~{interval}s between analysts).\n"
        )

    # Construct portfolio here
    portfolio = {
        "cash": inputs.initial_cash,
        "margin_requirement": inputs.margin_requirement,
        "margin_used": 0.0,
        "positions": {
            ticker: {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0.0,
                "short_cost_basis": 0.0,
                "short_margin_used": 0.0,
            }
            for ticker in tickers
        },
        "realized_gains": {
            ticker: {
                "long": 0.0,
                "short": 0.0,
            }
            for ticker in tickers
        },
    }

    wall_t0 = time.monotonic()
    result = run_hedge_fund(
        tickers=tickers,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
        portfolio=portfolio,
        show_reasoning=inputs.show_reasoning,
        selected_analysts=inputs.selected_analysts,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
        report_timeout_seconds=report_timeout_val,
        llm_call_timeout_seconds=inputs.llm_call_timeout_seconds,
        export_html_checkpoint_path=checkpoint_path,
        checkpoint_interval_seconds=float(inputs.checkpoint_html_interval_seconds or 0.0)
        if inputs.export_html
        else 0.0,
        checkpoint_context={
            "tickers": tickers,
            "start_date": inputs.start_date,
            "end_date": inputs.end_date,
            "model_name": inputs.model_name,
            "model_provider": inputs.model_provider,
        },
        emit_timing_footer=False,
    )
    wall_elapsed = time.monotonic() - wall_t0
    run_meta = result.get("_run_meta") or {}
    if isinstance(run_meta, dict):
        run_meta["wall_clock_sec"] = round(wall_elapsed, 3)
    completed_flag = not bool(run_meta.get("partial"))

    append_run_timing_record(
        Path(inputs.report_timing_history_path),
        duration_sec=wall_elapsed,
        tickers=tickers,
        completed=completed_flag,
    )

    print_trading_output(
        {
            "decisions": result.get("decisions") or {},
            "analyst_signals": result.get("analyst_signals") or {},
        },
        agent_run_timing=dict(progress.agent_status),
        wall_seconds=wall_elapsed,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
    )

    if run_meta.get("partial"):
        reason = run_meta.get("reason") or "Partial/incomplete run."
        print(f"\n{Fore.YELLOW}Run finished with partial results:{Style.RESET_ALL} {reason}")

    if inputs.export_html:
        banner = run_meta.get("reason") if run_meta.get("partial") else None
        snap = {k: deepcopy(v) for k, v in progress.agent_status.items()}
        report_path = write_research_report_html(
            result=result,
            tickers=tickers,
            start_date=inputs.start_date,
            end_date=inputs.end_date,
            model_name=inputs.model_name,
            model_provider=inputs.model_provider,
            output_path=export_final_path,
            status_banner=banner,
            progress_snapshot=snap if snap else None,
            infra_alert=progress.infra_alert,
            wall_clock_seconds=float(wall_elapsed),
        )
        print(
            f"\n{Fore.GREEN}Saved HTML research report:{Style.RESET_ALL} "
            f"{Fore.CYAN}{report_path}{Style.RESET_ALL}"
        )
