from datetime import datetime, timezone
import time
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.style import Style
from rich.text import Text
from typing import Dict, Optional, Callable, List

console = Console()


class AgentProgress:
    """Manages progress tracking for multiple agents."""

    def __init__(self):
        self.agent_status: Dict[str, Dict[str, str]] = {}
        self._agent_started_mono: Dict[str, float] = {}
        self.table = Table(show_header=False, box=None, padding=(0, 1))
        self.live = Live(self.table, console=console, refresh_per_second=4)
        self.started = False
        self.infra_alert: Optional[str] = None
        self.update_handlers: List[Callable[[str, Optional[str], str], None]] = []

    def register_handler(self, handler: Callable[[str, Optional[str], str], None]):
        """Register a handler to be called when agent status updates."""
        self.update_handlers.append(handler)
        return handler  # Return handler to support use as decorator

    def unregister_handler(self, handler: Callable[[str, Optional[str], str], None]):
        """Unregister a previously registered handler."""
        if handler in self.update_handlers:
            self.update_handlers.remove(handler)

    def reset_for_new_run(self):
        """Clear agent rows and timers so a new hedge-fund run starts fresh."""
        self.agent_status.clear()
        self._agent_started_mono.clear()

    def start(self):
        """Start the progress display."""
        if not self.started:
            self.live.start()
            self.started = True

    def stop(self):
        """Stop the progress display."""
        if self.started:
            self.live.stop()
            self.started = False

    def set_infra_alert(self, message: Optional[str]):
        """Shown at top of the Rich progress table and can be mirrored into HTML export."""
        self.infra_alert = message
        self._refresh_display()

    @staticmethod
    def _is_terminal_agent_status(status: str) -> bool:
        s = (status or "").strip().lower()
        return s == "done" or s == "error"

    def _elapsed_column_text(self, agent_name: str, info: Dict[str, str]) -> Text:
        dur = info.get("duration_sec")
        if dur is not None:
            try:
                sec = float(dur)
            except (TypeError, ValueError):
                sec = None
            if sec is not None:
                return Text(f"{sec:.1f}s", style=Style(color="green", bold=True))

        start_mono = self._agent_started_mono.get(agent_name)
        if start_mono is not None:
            live = time.monotonic() - start_mono
            return Text(f"{live:.1f}s …", style=Style(color="yellow"))
        return Text("—", style=Style(dim=True))

    def update_status(self, agent_name: str, ticker: Optional[str] = None, status: str = "", analysis: Optional[str] = None):
        """Update the status of an agent."""
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {"status": "", "ticker": None}

        info = self.agent_status[agent_name]

        if agent_name not in self._agent_started_mono:
            self._agent_started_mono[agent_name] = time.monotonic()

        if ticker:
            info["ticker"] = ticker
        if status:
            info["status"] = status
            if self._is_terminal_agent_status(status):
                if info.get("duration_sec") is None and agent_name in self._agent_started_mono:
                    info["duration_sec"] = round(time.monotonic() - self._agent_started_mono[agent_name], 3)
        if analysis:
            info["analysis"] = analysis

        # Set the timestamp as UTC datetime
        timestamp = datetime.now(timezone.utc).isoformat()
        info["timestamp"] = timestamp

        # Notify all registered handlers
        for handler in self.update_handlers:
            handler(agent_name, ticker, status, analysis, timestamp)

        self._refresh_display()

    def get_all_status(self):
        """Get the current status of all agents as a dictionary."""
        return {
            agent_name: {"ticker": info["ticker"], "status": info["status"], "display_name": self._get_display_name(agent_name)}
            for agent_name, info in self.agent_status.items()
        }

    def _get_display_name(self, agent_name: str) -> str:
        """Convert agent_name to a display-friendly format."""
        return agent_name.replace("_agent", "").replace("_", " ").title()

    def _sort_key(self, agent_name: str):
        if "risk_management" in agent_name:
            return (2, agent_name)
        if "portfolio_management" in agent_name:
            return (3, agent_name)
        return (1, agent_name)

    def _refresh_display(self):
        """Refresh the progress display."""
        self.table.columns.clear()
        self.table.add_column(width=78)
        self.table.add_column(width=14, justify="right", overflow="ellipsis")

        if self.infra_alert:
            warn = Text()
            warn.append("⚠ ", style=Style(color="red", bold=True))
            warn.append(self.infra_alert, style=Style(color="red", bold=False))
            self.table.add_row(warn, Text("", justify="right"))

        for agent_name, info in sorted(self.agent_status.items(), key=lambda item: self._sort_key(item[0])):
            status = info.get("status") or ""
            ticker = info["ticker"]
            if status.lower() == "done":
                style = Style(color="green", bold=True)
                symbol = "✓"
            elif status.lower() == "error":
                style = Style(color="red", bold=True)
                symbol = "✗"
            else:
                style = Style(color="yellow")
                symbol = "⋯"

            agent_display = self._get_display_name(agent_name)
            status_text = Text()
            status_text.append(f"{symbol} ", style=style)
            status_text.append(f"{agent_display:<20}", style=Style(bold=True))

            if ticker:
                status_text.append(f"[{ticker}] ", style=Style(color="cyan"))
            status_text.append(status, style=style)

            self.table.add_row(status_text, self._elapsed_column_text(agent_name, info))

    def print_run_timing_footer(self, *, wall_seconds: float, model_name: str, model_provider: str) -> None:
        """After Live stops: table of per-agent durations plus total wall clock and model."""
        footer = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
        footer.add_column("Agent", width=36)
        footer.add_column("Elapsed", justify="right", width=12)

        for agent_name, info in sorted(self.agent_status.items(), key=lambda item: self._sort_key(item[0])):
            disp = self._get_display_name(agent_name)
            dur = info.get("duration_sec")
            if dur is not None:
                try:
                    cell = f"{float(dur):.1f}s"
                except (TypeError, ValueError):
                    cell = "—"
            elif agent_name in self._agent_started_mono:
                cell = f"{time.monotonic() - self._agent_started_mono[agent_name]:.1f}s (no Done)"
            else:
                cell = "—"
            footer.add_row(disp, cell)

        console.print()
        console.print(footer)
        console.print(
            Text(
                f"Total wall-clock: {wall_seconds:.1f}s   ·   Model: {model_provider} / {model_name}",
                style="bold",
            )
        )


# Create a global instance
progress = AgentProgress()
