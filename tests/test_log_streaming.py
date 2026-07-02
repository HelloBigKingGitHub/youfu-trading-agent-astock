"""Tests for web/runner.py LogWriter integration.

Phase 1 / Commit 2 of log-monitor module. Verifies that the runner hooks
every LangGraph stream chunk through _classify_chunk and persists them via
LogWriter, both on success and on exception.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── _classify_chunk unit tests ─────────────────────────────────────────


def test_classify_chunk_yields_agent_output_for_12_keys():
    """_classify_chunk yields 1 agent_output per known report key."""
    from web.runner import _classify_chunk

    chunk = {
        "market_report": "X",
        "news_report": "Y",
        "fundamentals_report": "Z",
    }
    chunks = list(_classify_chunk(chunk, {}))
    keys = [c.report_key for c in chunks if c.type == "agent_output"]
    assert set(keys) >= {"market_report", "news_report", "fundamentals_report"}


def test_classify_chunk_yields_llm_for_debate_judge():
    """_classify_chunk yields llm for investment_debate_state.judge_decision."""
    from web.runner import _classify_chunk

    chunk = {"investment_debate_state": {"judge_decision": "We buy."}}
    chunks = list(_classify_chunk(chunk, {}))
    assert any(
        c.type == "llm" and c.agent == "research_manager" for c in chunks
    )


def test_classify_chunk_yields_llm_for_risk_judge():
    """_classify_chunk yields llm for risk_debate_state.judge_decision."""
    from web.runner import _classify_chunk

    chunk = {"risk_debate_state": {"judge_decision": "Risk acceptable."}}
    chunks = list(_classify_chunk(chunk, {}))
    assert any(
        c.type == "llm" and c.agent == "risk_manager" for c in chunks
    )


def test_classify_chunk_skips_empty_chunks():
    """Empty chunk (no known fields) → no LogChunks."""
    from web.runner import _classify_chunk

    chunk = {"random_field": "x", "company_of_interest": "600595"}
    chunks = list(_classify_chunk(chunk, {}))
    assert chunks == []


def test_classify_chunk_caps_content_at_50k():
    """Content > 50K chars is truncated to 50K."""
    from web.runner import _classify_chunk

    huge = "X" * 100_000
    chunk = {"market_report": huge}
    chunks = list(_classify_chunk(chunk, {}))
    assert len(chunks) == 1
    assert len(chunks[0].content) == 50_000


# ── _run integration tests (MagicMock TradingAgentsGraph) ───────────────


def test_run_analysis_writes_log_chunks_during_stream(tmp_path, monkeypatch):
    """Full _run: chunk → log chunk → file."""
    monkeypatch.setattr("backend.core.log_store._LOGS_ROOT", tmp_path)

    # Mock TradingAgentsGraph
    mock_graph = MagicMock()
    mock_graph.graph.stream.return_value = iter([
        {"market_report": "A"},
        {"investment_debate_state": {"judge_decision": "B"}},
        {"final_trade_decision": "BUY"},
    ])
    mock_graph.process_signal.return_value = "Buy"
    mock_graph.propagator.create_initial_state.return_value = {}
    mock_graph.propagator.get_graph_args.return_value = {}
    mock_graph.ticker = "600595"
    mock_graph._log_state = MagicMock()

    # Mock stats
    mock_stats = MagicMock()
    mock_stats.get_stats.return_value = {
        "llm_calls": 1,
        "tool_calls": 0,
        "tokens_in": 100,
        "tokens_out": 50,
    }

    mock_tracker = MagicMock()
    mock_tracker.completed_stages = ["market"]
    mock_tracker.start_time = time.time()

    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph", return_value=mock_graph), \
         patch("cli.stats_handler.StatsCallbackHandler", return_value=mock_stats), \
         patch("web.runner._history_store") as mock_hs:
        from web.runner import _run
        _run("600595", "2026-06-30", {}, mock_tracker, "test_id")

    # Check log files written
    log_dir = tmp_path / "600595" / "2026-06-30_run01"
    assert (log_dir / "llm_messages.jsonl").exists()
    assert (log_dir / "agent_outputs.jsonl").exists()
    # Check meta
    meta = json.loads((log_dir / "meta.json").read_text())
    assert meta["status"] == "completed"
    assert meta["signal"] == "Buy"


def test_run_analysis_finalize_error_on_exception(tmp_path, monkeypatch):
    """If stream raises, log_writer.finalize(error=...) is called."""
    monkeypatch.setattr("backend.core.log_store._LOGS_ROOT", tmp_path)

    mock_graph = MagicMock()
    mock_graph.graph.stream.side_effect = RuntimeError("API timeout")
    mock_graph.propagator.create_initial_state.return_value = {}
    mock_graph.propagator.get_graph_args.return_value = {}
    mock_graph.ticker = "600595"

    mock_tracker = MagicMock()
    mock_tracker.completed_stages = []
    mock_tracker.start_time = time.time()

    with patch("tradingagents.graph.trading_graph.TradingAgentsGraph", return_value=mock_graph), \
         patch("cli.stats_handler.StatsCallbackHandler", return_value=MagicMock()), \
         patch("web.runner._history_store") as mock_hs:
        from web.runner import _run
        with pytest.raises(RuntimeError, match="API timeout"):
            _run("600595", "2026-06-30", {}, mock_tracker, "test_id")

    log_dir = tmp_path / "600595" / "2026-06-30_run01"
    meta = json.loads((log_dir / "meta.json").read_text())
    assert meta["status"] == "error"
    assert "API timeout" in meta["error"]