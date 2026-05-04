"""Rolling run-duration history for adaptive report timeouts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean


def load_recent_completed_durations(history_path: Path, *, limit: int = 10) -> list[float]:
    """Return durations (seconds) for the most recent completed runs only."""
    if not history_path.is_file():
        return []
    rows: list[tuple[float, bool]] = []
    try:
        text = history_path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        dur = obj.get("duration_sec")
        completed = obj.get("completed", False)
        if isinstance(dur, (int, float)) and completed:
            rows.append((float(dur), True))
    tail = rows[-limit:] if limit else rows
    return [d for d, _ in tail]


def compute_adaptive_report_timeout(
    history_path: Path,
    *,
    ratio: float,
    floor_seconds: float,
    fallback_seconds: float,
    sample_size: int = 8,
) -> float:
    """
    Next-run ceiling ≈ max(floor, avg(last N completed runs) * ratio).
    Example: avg 45s, ratio 1.67 → ~75s ceiling.
    """
    durations = load_recent_completed_durations(history_path, limit=sample_size)
    if not durations:
        return max(floor_seconds, fallback_seconds)
    avg = mean(durations)
    return max(floor_seconds, avg * ratio)


def append_run_timing_record(
    history_path: Path,
    *,
    duration_sec: float,
    tickers: list[str],
    completed: bool,
) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "duration_sec": round(duration_sec, 3),
        "tickers": tickers,
        "completed": completed,
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
