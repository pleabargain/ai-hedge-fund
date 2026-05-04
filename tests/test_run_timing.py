"""Tests for adaptive report timeout helpers."""

from __future__ import annotations

import json
from pathlib import Path

from src.reporting.run_timing import (
    append_run_timing_record,
    compute_adaptive_report_timeout,
    load_recent_completed_durations,
)


def test_compute_adaptive_fallback_when_empty(tmp_path: Path) -> None:
    hist = tmp_path / "h.jsonl"
    ceiling = compute_adaptive_report_timeout(
        hist,
        ratio=1.67,
        floor_seconds=30.0,
        fallback_seconds=120.0,
    )
    assert ceiling == 120.0


def test_compute_adaptive_from_history(tmp_path: Path) -> None:
    hist = tmp_path / "h.jsonl"
    rec_completed = {"duration_sec": 45.0, "completed": True, "tickers": ["X"], "ts_utc": "t"}
    rec_partial = {"duration_sec": 999.0, "completed": False, "tickers": ["Y"], "ts_utc": "t"}
    hist.write_text(json.dumps(rec_completed) + "\n" + json.dumps(rec_partial) + "\n", encoding="utf-8")
    ceiling = compute_adaptive_report_timeout(
        hist,
        ratio=1.67,
        floor_seconds=30.0,
        fallback_seconds=120.0,
        sample_size=8,
    )
    assert ceiling == 45.0 * 1.67


def test_append_and_load_roundtrip(tmp_path: Path) -> None:
    hist = tmp_path / "h.jsonl"
    append_run_timing_record(hist, duration_sec=12.5, tickers=["A"], completed=True)
    append_run_timing_record(hist, duration_sec=50.0, tickers=["B"], completed=False)
    loaded = load_recent_completed_durations(hist, limit=10)
    assert loaded == [12.5]
