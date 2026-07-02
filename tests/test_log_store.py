"""Tests for backend.core.log_store."""

from __future__ import annotations

import json

import pytest

from backend.core.log_store import (
    LogChunk,
    LogStore,
    LogWriter,
    _LOGS_ROOT,
    get_log_store,
)


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_logs_root(tmp_path, monkeypatch):
    """Redirect _LOGS_ROOT to a tmp dir so tests don't touch real ~/.tradingagents/."""
    monkeypatch.setattr("backend.core.log_store._LOGS_ROOT", tmp_path)
    # Also reset module-level singleton so subsequent get_log_store() picks
    # up the new _LOGS_ROOT via LogStore (it stores no state, but stay tidy).
    monkeypatch.setattr("backend.core.log_store._log_store_singleton", None)
    return tmp_path


# ── LogWriter tests ────────────────────────────────────────────────


def test_log_writer_creates_task_dir(tmp_logs_root):
    """LogWriter(analysis_id, ticker, date) creates {ticker}/{date}_run01/."""
    w = LogWriter("test_001", "600595", "2026-06-30")
    assert w.task_dir == tmp_logs_root / "600595" / "2026-06-30_run01"
    assert w.task_dir.exists()
    assert w.task_dir_name == "2026-06-30_run01"


def test_log_writer_writes_initial_meta(tmp_logs_root):
    """Initial meta.json: status='running', started_at, chunk_counts={0,0,0}."""
    w = LogWriter("test_001", "600595", "2026-06-30")
    meta = json.loads((w.task_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "running"
    assert meta["ticker"] == "600595"
    assert meta["trade_date"] == "2026-06-30"
    assert meta["analysis_id"] == "test_001"
    assert meta["chunk_counts"] == {"llm": 0, "tool": 0, "agent_output": 0}
    assert meta["signal"] == ""
    assert meta["finished_at"] is None


def test_log_writer_picks_run01_for_first(tmp_logs_root):
    """First task for {ticker, date} → run01."""
    w1 = LogWriter("test_001", "600595", "2026-06-30")
    assert w1.task_dir_name == "2026-06-30_run01"


def test_log_writer_picks_run02_for_second(tmp_logs_root):
    """Second task same day → run02."""
    LogWriter("test_001", "600595", "2026-06-30")
    w2 = LogWriter("test_002", "600595", "2026-06-30")
    assert w2.task_dir_name == "2026-06-30_run02"


def test_log_writer_picks_run01_for_new_date(tmp_logs_root):
    """Different date → run01 even if other dates exist."""
    LogWriter("test_001", "600595", "2026-06-30")
    w2 = LogWriter("test_002", "600595", "2026-06-31")
    assert w2.task_dir_name == "2026-06-31_run01"


def test_log_writer_append_chunk_creates_correct_file(tmp_logs_root):
    """append_chunk('llm') → writes to llm_messages.jsonl."""
    w = LogWriter("test_001", "600595", "2026-06-30")
    chunk = LogChunk(
        ts=1.0, type="llm", agent="market_analyst", role="assistant", content="hi"
    )
    w.append_chunk(chunk)
    assert (w.task_dir / "llm_messages.jsonl").exists()
    content = (w.task_dir / "llm_messages.jsonl").read_text(encoding="utf-8")
    assert "market_analyst" in content
    assert "hi" in content
    assert (w.task_dir / "tool_calls.jsonl").exists() is False


def test_log_writer_append_chunk_increments_count(tmp_logs_root):
    """After 5 LLM + 3 tool + 2 agent_output, chunk_counts reflects."""
    w = LogWriter("test_001", "600595", "2026-06-30")
    for _ in range(5):
        w.append_chunk(LogChunk(ts=1.0, type="llm", agent="x", content=""))
    for _ in range(3):
        w.append_chunk(LogChunk(ts=1.0, type="tool", agent="x", tool="y"))
    for _ in range(2):
        w.append_chunk(LogChunk(ts=1.0, type="agent_output", agent="x", report_key="z"))
    assert w.chunk_counts == {"llm": 5, "tool": 3, "agent_output": 2}


def test_log_writer_finalize_completed(tmp_logs_root):
    """finalize(signal='Buy', elapsed=10) → status='completed', signal, finished_at."""
    w = LogWriter("test_001", "600595", "2026-06-30")
    w.append_chunk(LogChunk(ts=1.0, type="llm", agent="x", content=""))
    w.finalize(
        signal="Buy", elapsed_sec=10.5, completed_stages=["market", "social"]
    )
    meta = json.loads((w.task_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "completed"
    assert meta["signal"] == "Buy"
    assert meta["elapsed_sec"] == 10.5
    assert meta["finished_at"] is not None
    assert meta["stages_completed"] == ["market", "social"]
    assert meta["chunk_counts"]["llm"] == 1


def test_log_writer_finalize_error(tmp_logs_root):
    """finalize(error='xxx') → status='error', error=xxx."""
    w = LogWriter("test_001", "600595", "2026-06-30")
    w.finalize(signal="", elapsed_sec=2.0, error="OOM")
    meta = json.loads((w.task_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "error"
    assert meta["error"] == "OOM"


# ── LogStore read tests ────────────────────────────────────────────


def test_list_tickers_empty(tmp_logs_root):
    """No log dir → empty list."""
    store = LogStore()
    assert store.list_tickers() == []


def test_list_tickers_returns_tickers_with_new_structure(tmp_logs_root):
    """2 tickers with new logs → both listed."""
    LogWriter("a_001", "600595", "2026-06-30")
    LogWriter("b_001", "000001", "2026-06-30")
    store = LogStore()
    assert set(store.list_tickers()) == {"600595", "000001"}


def test_list_tasks_returns_new_tasks_only(tmp_logs_root):
    """list_tasks for ticker with 2 new tasks."""
    LogWriter("a_001", "600595", "2026-06-30")
    LogWriter("a_002", "600595", "2026-06-31")
    tasks = LogStore().list_tasks("600595")
    assert len(tasks) == 2
    # Sorted by started_at desc
    assert tasks[0].trade_date == "2026-06-31"
    assert tasks[1].trade_date == "2026-06-30"


def test_count_chunks_returns_correct_counts(tmp_logs_root):
    """count_chunks reflects 3 jsonl file line counts."""
    w = LogWriter("a_001", "600595", "2026-06-30")
    w.append_chunk(LogChunk(ts=1.0, type="llm", agent="x", content=""))
    w.append_chunk(LogChunk(ts=2.0, type="llm", agent="x", content=""))
    w.append_chunk(LogChunk(ts=3.0, type="tool", agent="x", tool="y"))
    counts = LogStore().count_chunks("600595", w.task_dir_name)
    assert counts == {"llm": 2, "tool": 1, "agent_output": 0}


def test_stream_chunks_yields_in_chronological_order(tmp_logs_root):
    """stream_chunks yields chunks sorted by ts."""
    w = LogWriter("a_001", "600595", "2026-06-30")
    w.append_chunk(LogChunk(ts=3.0, type="tool", agent="x", tool="y"))
    w.append_chunk(LogChunk(ts=1.0, type="llm", agent="x", content="a"))
    w.append_chunk(LogChunk(ts=2.0, type="llm", agent="x", content="b"))
    chunks = list(LogStore().stream_chunks("600595", w.task_dir_name))
    assert [c.ts for c in chunks] == [1.0, 2.0, 3.0]
    assert [c.type for c in chunks] == ["llm", "llm", "tool"]


def test_stream_chunks_with_type_filter(tmp_logs_root):
    """type_filter='llm' only yields llm chunks."""
    w = LogWriter("a_001", "600595", "2026-06-30")
    w.append_chunk(LogChunk(ts=1.0, type="llm", agent="x", content=""))
    w.append_chunk(LogChunk(ts=2.0, type="tool", agent="x", tool="y"))
    llm_only = list(
        LogStore().stream_chunks("600595", w.task_dir_name, type_filter="llm")
    )
    assert len(llm_only) == 1
    assert llm_only[0].type == "llm"


def test_compat_read_legacy_full_states_log(tmp_logs_root):
    """Legacy task (only full_states_log_*.json) → get_meta returns converted dict."""
    legacy_dir = tmp_logs_root / "000001" / "TradingAgentsStrategy_logs"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "full_states_log_2026-06-10.json").write_text(
        json.dumps({
            "company_of_interest": "000001",
            "trade_date": "2026-06-10",
            "market_report": "test report",
            "final_trade_decision": "BUY",
        }),
        encoding="utf-8",
    )

    store = LogStore()
    meta = store.get_meta("000001", "2026-06-10_run01")
    assert meta["is_legacy"] is True
    assert meta["ticker"] == "000001"
    assert meta["trade_date"] == "2026-06-10"
    assert meta["legacy_state"]["market_report"] == "test report"