from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sanitize_ticker_filename_segment(ticker: str) -> str:
    """Allow only safe filename characters for ticker-derived path segments."""
    s = "".join(c for c in (ticker or "").strip().upper() if c.isalnum() or c in "-_")
    return s or "TICKER"


def default_export_html_path(tickers: list[str]) -> Path:
    """
    Default report path: outputs/{TICKER}-{YYYYMMDD_HHMMSS}.html
    Multiple tickers: outputs/{TICK1_TICK2_...}-{YYYYMMDD_HHMMSS}.html
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not tickers:
        stem = f"research-{ts}"
    elif len(tickers) == 1:
        stem = f"{_sanitize_ticker_filename_segment(tickers[0])}-{ts}"
    else:
        joined = "_".join(_sanitize_ticker_filename_segment(t) for t in tickers)
        stem = f"{joined}-{ts}"
    return Path("outputs") / f"{stem}.html"


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _json_block(data: Any) -> str:
    return _escape(json.dumps(data, indent=2, default=str))


def _reasoning_text(reasoning: Any) -> str:
    if reasoning is None:
        return ""
    if isinstance(reasoning, str):
        return reasoning
    return json.dumps(reasoning, indent=2, default=str)


def _agent_display_name(agent_id: str) -> str:
    return agent_id.replace("_agent", "").replace("_", " ").title()


def _timing_sort_key_html(agent_name: str) -> tuple:
    if "risk_management" in agent_name:
        return (2, agent_name)
    if "portfolio_management" in agent_name:
        return (3, agent_name)
    return (1, agent_name)


def _durations_from_progress_snapshot(snapshot: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for agent_name, info in (snapshot or {}).items():
        if not isinstance(info, dict):
            continue
        raw = info.get("duration_sec")
        if raw is None:
            continue
        try:
            out[str(agent_name)] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def _duration_cell_html(agent_name: str, agent_durations: dict[str, float]) -> str:
    v = agent_durations.get(agent_name)
    if v is None:
        return "—"
    try:
        return _escape(f"{float(v):.1f}s")
    except (TypeError, ValueError):
        return "—"


def _sources_manifest() -> list[dict[str, str]]:
    return [
        {
            "provider": "Financial Datasets",
            "endpoint": "GET /prices/",
            "base_url": "https://api.financialdatasets.ai",
            "notes": "Used for historical price series.",
        },
        {
            "provider": "Financial Datasets",
            "endpoint": "GET /financial-metrics/",
            "base_url": "https://api.financialdatasets.ai",
            "notes": "Used for profitability, growth, and valuation metrics.",
        },
        {
            "provider": "Financial Datasets",
            "endpoint": "POST /financials/search/line-items",
            "base_url": "https://api.financialdatasets.ai",
            "notes": "Used for normalized financial statement line items.",
        },
        {
            "provider": "Financial Datasets",
            "endpoint": "GET /insider-trades/",
            "base_url": "https://api.financialdatasets.ai",
            "notes": "Used in sentiment and insider activity analysis.",
        },
        {
            "provider": "Financial Datasets",
            "endpoint": "GET /news/",
            "base_url": "https://api.financialdatasets.ai",
            "notes": "Used for company news sentiment.",
        },
        {
            "provider": "Financial Datasets",
            "endpoint": "GET /company/facts/",
            "base_url": "https://api.financialdatasets.ai",
            "notes": "Used for company metadata and market cap fallback.",
        },
    ]


def _render_decisions_table(decisions: dict[str, Any]) -> str:
    rows: list[str] = []
    for ticker, decision in (decisions or {}).items():
        action = _escape((decision or {}).get("action", ""))
        quantity = _escape((decision or {}).get("quantity", ""))
        confidence = _escape((decision or {}).get("confidence", ""))
        reasoning = _escape(_reasoning_text((decision or {}).get("reasoning", "")))
        rows.append(
            "<tr>"
            f"<td>{_escape(ticker)}</td>"
            f"<td>{action}</td>"
            f"<td>{quantity}</td>"
            f"<td>{confidence}</td>"
            f"<td><pre>{reasoning}</pre></td>"
            "</tr>"
        )
    if not rows:
        return "<p>No decisions returned.</p>"
    return (
        "<table><thead><tr><th>Ticker</th><th>Action</th><th>Quantity</th>"
        "<th>Confidence</th><th>Reasoning</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_analyst_rows(analyst_signals: dict[str, Any], agent_durations: dict[str, float] | None) -> str:
    dur_map = agent_durations or {}
    rows: list[str] = []
    for agent_name, per_ticker in (analyst_signals or {}).items():
        for ticker, signal in (per_ticker or {}).items():
            elapsed = _duration_cell_html(agent_name, dur_map)
            rows.append(
                "<tr>"
                f"<td>{_escape(agent_name)}</td>"
                f"<td>{_escape(ticker)}</td>"
                f"<td>{_escape((signal or {}).get('signal', ''))}</td>"
                f"<td>{_escape((signal or {}).get('confidence', ''))}</td>"
                f'<td style="text-align:right">{elapsed}</td>'
                f"<td><pre>{_escape(_reasoning_text((signal or {}).get('reasoning', '')))}</pre></td>"
                "</tr>"
            )
    if not rows:
        return "<p>No analyst signals returned.</p>"
    return (
        "<table><thead><tr><th>Agent</th><th>Ticker</th><th>Signal</th>"
        '<th>Confidence</th><th style="text-align:right">Elapsed</th><th>Reasoning</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_agent_timing_table(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    rows: list[str] = []
    for agent_name, info in sorted(snapshot.items(), key=lambda x: _timing_sort_key_html(x[0])):
        if not isinstance(info, dict):
            continue
        dur_raw = info.get("duration_sec")
        dur_cell = "—"
        if dur_raw is not None:
            try:
                dur_cell = _escape(f"{float(dur_raw):.1f}s")
            except (TypeError, ValueError):
                dur_cell = "—"
        ticker = info.get("ticker") or ""
        status = _escape((info.get("status") or "")[:80])
        rows.append(
            "<tr>"
            f"<td>{_escape(_agent_display_name(agent_name))}</td>"
            f"<td>{_escape(ticker)}</td>"
            f"<td>{status}</td>"
            f'<td style="text-align:right">{dur_cell}</td>'
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<h2>Agent run timing</h2>"
        "<p>Seconds from first activity to terminal status (Done / Error) for each LangGraph node.</p>"
        "<table><thead><tr><th>Agent</th><th>Ticker</th><th>Last status</th>"
        '<th style="text-align:right">Elapsed</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_sources_rows(sources: list[dict[str, str]]) -> str:
    rows = []
    for src in sources:
        rows.append(
            "<tr>"
            f"<td>{_escape(src.get('provider', ''))}</td>"
            f"<td>{_escape(src.get('endpoint', ''))}</td>"
            f"<td>{_escape(src.get('base_url', ''))}</td>"
            f"<td>{_escape(src.get('notes', ''))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Provider</th><th>Endpoint</th><th>Base URL</th><th>Notes</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_research_report_html(
    *,
    result: dict[str, Any],
    tickers: list[str],
    start_date: str,
    end_date: str,
    model_name: str,
    model_provider: str,
    status_banner: str | None = None,
    progress_snapshot: dict[str, Any] | None = None,
    infra_alert: str | None = None,
    wall_clock_seconds: float | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    decisions = result.get("decisions") or {}
    analyst_signals = result.get("analyst_signals") or {}
    agent_durations = _durations_from_progress_snapshot(progress_snapshot)
    sources = _sources_manifest()
    banner_html = ""
    if status_banner:
        banner_html = f'<div class="banner"><strong>Run status:</strong> {_escape(status_banner)}</div>'
    infra_html = ""
    if infra_alert:
        infra_html = (
            '<div class="banner-infra"><strong>Ollama / runtime:</strong> '
            f"{_escape(infra_alert)}</div>"
        )

    wall_line = ""
    if wall_clock_seconds is not None:
        wall_line = (
            f"<div><strong>Wall-clock run:</strong> {_escape(f'{float(wall_clock_seconds):.1f}s')} "
            f"(model {_escape(model_provider)} / {_escape(model_name)})</div>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Hedge Fund Research Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.4; color: #222; }}
    h1, h2 {{ margin-bottom: 8px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f5f5f5; }}
    pre {{ white-space: pre-wrap; margin: 0; font-family: Consolas, monospace; font-size: 12px; }}
    .meta {{ background: #fafafa; border: 1px solid #eee; padding: 10px; border-radius: 6px; }}
    .banner {{ background: #fff3cd; border: 1px solid #ffc107; padding: 10px; border-radius: 6px; margin-bottom: 12px; }}
    .banner-infra {{ background: #fdecea; border: 1px solid #f5c2c0; padding: 10px; border-radius: 6px; margin-bottom: 12px; color: #842029; }}
    details {{ margin-top: 12px; }}
  </style>
</head>
<body>
  <h1>AI Hedge Fund Research Report</h1>
  {banner_html}
  {infra_html}
  <div class="meta">
    <div><strong>Generated (UTC):</strong> {_escape(generated_at)}</div>
    <div><strong>Tickers:</strong> {_escape(", ".join(tickers))}</div>
    <div><strong>Date range:</strong> {_escape(start_date)} to {_escape(end_date)}</div>
    <div><strong>Model:</strong> {_escape(model_provider)} / {_escape(model_name)}</div>
    {wall_line}
  </div>

  <h2>Portfolio Decisions</h2>
  {_render_decisions_table(decisions)}

  {_render_agent_timing_table(progress_snapshot)}

  <h2>Analyst Signals</h2>
  {_render_analyst_rows(analyst_signals, agent_durations)}

  {_render_progress_snapshot(progress_snapshot)}

  <h2>Data Sources (Manifest)</h2>
  {_render_sources_rows(sources)}

  <details>
    <summary><strong>Raw Result JSON</strong></summary>
    <pre>{_json_block(result)}</pre>
  </details>
</body>
</html>
"""


def _render_progress_snapshot(snapshot: dict[str, Any] | None) -> str:
    if not snapshot:
        return ""
    return (
        "<h2>Agent progress snapshot</h2>"
        "<p>Captured between LangGraph steps or on a heartbeat timer; useful when the run is still busy inside one analyst.</p>"
        f"<pre>{_json_block(snapshot)}</pre>"
    )


def write_research_report_html(
    *,
    result: dict[str, Any],
    tickers: list[str],
    start_date: str,
    end_date: str,
    model_name: str,
    model_provider: str,
    output_path: str | None = None,
    status_banner: str | None = None,
    progress_snapshot: dict[str, Any] | None = None,
    infra_alert: str | None = None,
    wall_clock_seconds: float | None = None,
) -> Path:
    if output_path:
        target = Path(output_path)
    else:
        target = default_export_html_path(tickers)

    target.parent.mkdir(parents=True, exist_ok=True)
    html_text = render_research_report_html(
        result=result,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        model_name=model_name,
        model_provider=model_provider,
        status_banner=status_banner,
        progress_snapshot=progress_snapshot,
        infra_alert=infra_alert,
        wall_clock_seconds=wall_clock_seconds,
    )
    target.write_text(html_text, encoding="utf-8")
    return target.resolve()
