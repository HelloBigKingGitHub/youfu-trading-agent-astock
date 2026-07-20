"""Tests for the new ``GET /api/analyze/{analysis_id}/export?format=…`` endpoint.

P2.29 — added so the React `/analyze` report tab can offer a download button
(📥 Markdown / 📄 PDF) the same way the legacy Streamlit report did
(``web/components/report_viewer.py:66-94`` via ``web/pdf_export.py``).

The endpoint reuses the same ``entry.results_path`` + legacy-fallback path
that ``get_analyze_report`` uses, reads the JSON file, then delegates to
``web.pdf_export.generate_markdown`` / ``generate_pdf`` after applying the
field-name adapter so the old ``_collect_sections`` still works (see
``backend/core/report_adapter.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ── shared fixtures ──────────────────────────────────────────────────────────


REPORT_PAYLOAD = {
    "company_of_interest": "600595",
    "trade_date": "2026-07-18",
    "market_report": "# 技术分析\nMock body",
    "sentiment_report": "# 情绪分析\nMock body",
    "news_report": "# 新闻舆情\nMock body",
    "fundamentals_report": "# 基本面\nMock body",
    "policy_report": "# 政策分析\nMock body",
    "hot_money_report": "# 游资追踪\nMock body",
    "lockup_report": "# 解禁\nMock body",
    "quality_gate_report": "# 质量门禁\nMock body",
    "investment_debate_state": {"judge_decision": "买入", "bull_history": "bull", "bear_history": "bear"},
    "risk_debate_state": {"judge_decision": "持有", "aggressive_history": "agg"},
    "trader_investment_plan": "执行买入 5% 仓位",
    "final_trade_decision": "BUY",
}

ANALYSIS_ID = "600595_2026-07-18_test"


@pytest.fixture()
def export_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a fake history store + full_states_log_*.json file under tmp_path.

    Mirrors the ``tracker_env`` fixture from test_tracker_stage_reports.py —
    monkeypatch ``_HISTORY_DIR`` so the real ``~/.tradingagents/logs/history``
    isn't touched, then write one analysis entry pointing at a fake results
    file we control.
    """
    # 1. Redirect HistoryStore (used by the /export endpoint to find entries).
    from backend.core import history_store as history_mod

    monkeypatch.setattr(history_mod, "_HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history_mod.HistoryStore, "_instance", None)

    # 2. Write the fake full_states_log file + register a history entry
    #    pointing at it. Tweak results_path to an absolute tmp_path so we
    #    don't rely on the legacy fallback in tests.
    logs_dir = tmp_path / "logs" / "600595" / "TradingAgentsStrategy_logs"
    logs_dir.mkdir(parents=True)
    report_file = logs_dir / "full_states_log_2026-07-18.json"
    report_file.write_text(json.dumps(REPORT_PAYLOAD, ensure_ascii=False), encoding="utf-8")

    history_dir = tmp_path / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    (history_dir / f"{ANALYSIS_ID}.json").write_text(
        json.dumps(
            {
                "analysis_id": ANALYSIS_ID,
                "ticker": "600595",
                "trade_date": "2026-07-18",
                "signal": "BUY",
                "elapsed": 87.42,
                "created_at": "2026-07-18T10:00:00",
                "status": "completed",
                "error": None,
                "results_path": str(report_file),
                "completed_stages": [
                    "market", "social", "news", "fundamentals", "policy",
                    "hot_money", "lockup", "quality_gate", "debate",
                    "risk", "trader", "pm",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    yield {"report_file": report_file, "history_dir": history_dir}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient — same pattern as tests/test_batch.py:309-317.

    Only GET routes are exercised here so we don't need to stub ``start_analysis``
    or the executor — POST /api/analyze is not in scope for export tests.
    """
    from fastapi.testclient import TestClient
    from backend.main import app

    return TestClient(app)


# ── tests ────────────────────────────────────────────────────────────────────


class TestAnalyzeExportMarkdown:
    """Markdown export — always works (no font dependency)."""

    def test_returns_200_with_disposition_header(
        self, client, export_env, monkeypatch
    ):
        from backend.core import history_store as history_mod

        # Force pdf_available computation to use a fast deterministic value
        # so we don't depend on the actual host having a CJK font for the
        # markdown test (pdf_available is computed lazily by the endpoint).
        from web import pdf_export as pdf_mod

        monkeypatch.setattr(pdf_mod, "_find_cjk_font", lambda: None)

        # Re-bind the module-level cache after monkeypatch.
        monkeypatch.setattr(
            "backend.api.analyze._pdf_export_available",
            lambda: False,
            raising=False,
        )

        r = client.get(f"/api/analyze/{ANALYSIS_ID}/export?format=md")

        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/markdown")
        assert "attachment" in r.headers.get("content-disposition", "")
        assert (
            "TradingAgents-Astock_600595_2026-07-18.md"
            in r.headers["content-disposition"]
        )

        body = r.text
        # Hero metadata
        assert "# A股多Agent投研分析报告" in body
        assert "**股票代码**：600595" in body
        assert "**交易信号**：**BUY**" in body
        # At least one section header present
        assert "## 技术分析报告" in body


class TestAnalyzeExportPdf:
    """PDF export — depends on a CJK font on the host."""

    def test_returns_503_with_reason_when_no_cjk_font(
        self, client, export_env, monkeypatch
    ):
        from web import pdf_export as pdf_mod

        monkeypatch.setattr(pdf_mod, "_find_cjk_font", lambda: None)

        # Reset module-level cache so the endpoint re-probes the (mocked)
        # _find_cjk_font. Different code-path from the markdown test.
        import backend.api.analyze as analyze_api

        monkeypatch.setattr(analyze_api, "_pdf_export_available", lambda: False)

        r = client.get(f"/api/analyze/{ANALYSIS_ID}/export?format=pdf")

        assert r.status_code == 503
        # FastAPI wraps HTTPException(detail=dict) → JSON body is {"detail": {...}}.
        assert r.json()["detail"]["reason"] == "no_cjk_font"

    def test_returns_200_pdf_bytes_when_font_available(
        self, client, export_env, monkeypatch
    ):
        # Don't actually run fpdf2 here — that would require a real TTF
        # file on disk and adds flakiness to the endpoint contract. Stub
        # generate_pdf so we verify the endpoint's plumbing (Content-Type,
        # Content-Disposition, status code) without coupling to fpdf2.
        from web import pdf_export as pdf_mod

        monkeypatch.setattr(pdf_mod, "_find_cjk_font", lambda: "/fake/font.ttf")
        monkeypatch.setattr(
            pdf_mod,
            "generate_pdf",
            lambda *_a, **_k: b"%PDF-1.4\n%mock\n",
        )

        import backend.api.analyze as analyze_api

        monkeypatch.setattr(analyze_api, "_pdf_export_available", lambda: True)

        r = client.get(f"/api/analyze/{ANALYSIS_ID}/export?format=pdf")

        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert "TradingAgents-Astock_600595_2026-07-18.pdf" in r.headers["content-disposition"]
        assert r.content.startswith(b"%PDF-")


class TestAnalyzeExportErrors:
    """Edge cases — invalid format string, unknown analysis_id."""

    def test_404_when_entry_missing(self, client, export_env):
        r = client.get("/api/analyze/does_not_exist/export?format=md")
        assert r.status_code == 404

    def test_400_when_format_missing(self, client, export_env):
        # ``format`` has no default — absent or empty string both fail Pydantic validation.
        r = client.get(f"/api/analyze/{ANALYSIS_ID}/export")
        assert r.status_code in (400, 422)

    def test_400_when_format_unsupported(self, client, export_env):
        r = client.get(f"/api/analyze/{ANALYSIS_ID}/export?format=docx")
        assert r.status_code in (400, 422)
