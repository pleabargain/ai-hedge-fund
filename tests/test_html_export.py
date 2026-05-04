"""Tests for CLI HTML research report export (Phase 1)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.reporting.html_export import (
    default_export_html_path,
    render_research_report_html,
    write_research_report_html,
)


def _sample_result() -> dict:
    return {
        "decisions": {
            "TEST": {
                "action": "hold",
                "quantity": 0,
                "confidence": 50.0,
                "reasoning": "Synthetic fixture.",
            }
        },
        "analyst_signals": {
            "fundamentals_analyst_agent": {
                "TEST": {
                    "signal": "neutral",
                    "confidence": 40,
                    "reasoning": "Fixture reasoning.",
                }
            }
        },
    }


class TestRenderResearchReportHtml:
    def test_includes_core_sections(self):
        html_text = render_research_report_html(
            result=_sample_result(),
            tickers=["TEST"],
            start_date="2026-01-01",
            end_date="2026-03-01",
            model_name="test-model",
            model_provider="TestProvider",
        )
        assert "<h1>AI Hedge Fund Research Report</h1>" in html_text
        assert "<h2>Portfolio Decisions</h2>" in html_text
        assert "<h2>Analyst Signals</h2>" in html_text
        assert ">Elapsed</th>" in html_text
        assert "<h2>Data Sources (Manifest)</h2>" in html_text
        assert "Financial Datasets" in html_text
        assert "/prices/" in html_text
        assert "Raw Result JSON" in html_text

    def test_agent_timing_table_from_snapshot(self):
        snap = {
            "warren_buffett_agent": {
                "ticker": "TEST",
                "status": "Done",
                "duration_sec": 12.345,
            }
        }
        html_text = render_research_report_html(
            result=_sample_result(),
            tickers=["TEST"],
            start_date="2026-01-01",
            end_date="2026-03-01",
            model_name="m",
            model_provider="Ollama",
            progress_snapshot=snap,
        )
        assert "<h2>Agent run timing</h2>" in html_text
        assert "12.3s" in html_text
        assert "Warren Buffett" in html_text

    def test_infra_alert_renders_banner(self):
        html_text = render_research_report_html(
            result=_sample_result(),
            tickers=["TEST"],
            start_date="2026-01-01",
            end_date="2026-03-01",
            model_name="m",
            model_provider="Ollama",
            infra_alert="Ollama stopped responding — restarting.",
        )
        assert "banner-infra" in html_text
        assert "Ollama / runtime:" in html_text
        assert "restarting" in html_text

    def test_wall_clock_meta_line(self):
        html_text = render_research_report_html(
            result=_sample_result(),
            tickers=["TEST"],
            start_date="2026-01-01",
            end_date="2026-03-01",
            model_name="qwen3.5:9b",
            model_provider="Ollama",
            wall_clock_seconds=123.456,
        )
        assert "Wall-clock run:" in html_text
        assert "123.5s" in html_text
        assert "qwen3.5:9b" in html_text

    def test_escapes_angle_brackets_in_reasoning(self):
        payload = _sample_result()
        payload["decisions"]["TEST"]["reasoning"] = "<script>bad</script>"
        html_text = render_research_report_html(
            result=payload,
            tickers=["TEST"],
            start_date="2026-01-01",
            end_date="2026-03-01",
            model_name="m",
            model_provider="p",
        )
        assert "<script>" not in html_text
        assert "&lt;script&gt;" in html_text


class TestDefaultExportHtmlPath:
    def test_single_ticker_outputs_folder_and_timestamp_suffix(self):
        p = default_export_html_path(["bcda"])
        assert p.parent == Path("outputs")
        assert re.match(r"^BCDA-\d{8}_\d{6}\.html$", p.name)

    def test_multiple_tickers_joined_before_timestamp(self):
        p = default_export_html_path(["AAPL", "GOOGL"])
        assert p.parent == Path("outputs")
        assert re.match(r"^AAPL_GOOGL-\d{8}_\d{6}\.html$", p.name)

    def test_empty_tickers_uses_research_stem(self):
        p = default_export_html_path([])
        assert p.parent == Path("outputs")
        assert re.match(r"^research-\d{8}_\d{6}\.html$", p.name)


class TestWriteResearchReportHtml:
    def test_writes_file_at_given_path(self, tmp_path: Path):
        out = tmp_path / "subdir" / "report.html"
        path = write_research_report_html(
            result=_sample_result(),
            tickers=["TEST"],
            start_date="2026-01-01",
            end_date="2026-03-01",
            model_name="m",
            model_provider="p",
            output_path=str(out),
        )
        assert path == out.resolve()
        assert out.is_file()
        body = out.read_text(encoding="utf-8")
        assert "Portfolio Decisions" in body

    def test_writes_default_path_under_outputs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        path = write_research_report_html(
            result=_sample_result(),
            tickers=["BCDA"],
            start_date="2026-01-01",
            end_date="2026-03-01",
            model_name="m",
            model_provider="p",
            output_path=None,
        )
        assert path.parent == tmp_path / "outputs"
        assert re.match(r"^BCDA-\d{8}_\d{6}\.html$", path.name)
        assert path.is_file()
