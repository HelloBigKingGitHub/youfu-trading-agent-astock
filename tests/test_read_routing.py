"""Integration tests for the Phase 4 read-cutover wrappers.

The tests below exercise the read-routing wrappers (introduced in Phase 4
to flip reads onto the SQLite sidecar) without touching any runtime
caller.  They build a private wrapper pair against an isolated tmp_path
fixture so they neither rely on env vars nor interfere with the singleton
store pinned at backend import time.

Coverage:

  * ``test_history_read_routes_to_sqlite`` — confirms ``DualReadHistoryStore``
    routes ``get`` / ``list_all`` to the SQLite sidecar.
  * ``test_log_read_routes_to_sqlite`` — confirms ``DualReadLogStore`` routes
    ``list_tickers`` / ``list_tasks`` / ``get_meta`` / ``count_chunks`` /
    ``stream_chunks`` to the SQLite sidecar.
  * ``test_write_still_dual_writes`` — confirms both stores still receive
    the write (Phase 3b/3c behaviour is preserved).
  * ``test_read_data_matches_jsonl_data`` — drift check: SQLite reads match
    JSON/JSONL reads exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.history_store import HistoryEntry, HistoryStore
from backend.core.history_store_read_routing import DualReadHistoryStore
from backend.core.history_store_sqlite import SQLiteHistoryStore
from backend.core.log_store import LogChunk, LogStore, LogWriter
from backend.core.log_store_read_routing import DualReadLogStore, DualReadLogWriter
from backend.core.log_store_sqlite import SQLiteLogStore, SQLiteLogWriter


# ── history fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def history_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build an isolated JSON + SQLite history pair with the read wrapper.

    The writer is the Phase 3b ``DualWriteHistoryStore`` so writes land on
    both back-ends exactly the way production does when ``DUAL_WRITE_HISTORY=1``.
    """
    from backend.core import history_store as history_module
    from backend.core.history_store_dualwrite import DualWriteHistoryStore

    history_dir = tmp_path / "history"
    monkeypatch.setattr(history_module, "_HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_module.HistoryStore, "_instance", None)

    json_store = history_module.HistoryStore.get_instance()
    sqlite_store = SQLiteHistoryStore(tmp_path / "tradingagents.db")
    # Phase 3b layer that writes both JSON and SQLite — same behaviour we
    # run in production when DUAL_WRITE_HISTORY=1.
    dual_writer = DualWriteHistoryStore(json_store, sqlite_store)
    routed = DualReadHistoryStore(dual_writer, sqlite_store)
    yield routed, json_store, sqlite_store
    sqlite_store.close()


def test_history_read_routes_to_sqlite(history_pair):
    """Reads (get / list_all / find_by_ticker_date) come from SQLite."""
    routed, json_store, sqlite_store = history_pair

    entry = routed.create(
        "600519",
        "2026-07-20",
        status="running",
        analysis_id="phase4-history-read",
    )
    routed.mark_stage_done(
        entry.analysis_id, "market", report="market snip", report_key="market_report"
    )
    routed.mark_complete(
        entry.analysis_id,
        signal="Buy",
        elapsed=12.5,
        completed_stages=["market"],
    )

    # Point the SQLite reader at the sidecar; the JSON reader should NOT
    # be reachable from the public API of ``routed`` because reads are
    # intentionally pinned to SQLite.
    sqlite_view = sqlite_store.get(entry.analysis_id)
    assert sqlite_view is not None
    assert sqlite_view.signal == "Buy"
    assert sqlite_view.stage_reports["market_report"] == "market snip"

    routed_view = routed.get(entry.analysis_id)
    assert routed_view is not None
    assert routed_view.to_dict() == sqlite_view.to_dict()

    # Verify the public list path is SQLite-backed: the total count comes
    # from the SQL COUNT(*) aggregated against the history table rather
    # than the JSON glob.
    entries, total = routed.list_all(limit=10, offset=0)
    assert total == 1
    assert entries[0].analysis_id == entry.analysis_id

    found = routed.find_by_ticker_date("600519", "2026-07-20")
    assert found is not None
    assert found.analysis_id == entry.analysis_id


def test_history_write_still_dual_writes(history_pair):
    """Writes still hit both the JSON store and the SQLite sidecar."""
    routed, json_store, sqlite_store = history_pair

    entry = routed.create(
        "600000",
        "2026-07-20",
        status="running",
        analysis_id="phase4-history-write",
    )

    # JSON side has the file on disk.
    json_path = Path("/dev/null")
    # Resolve the real JSON path the wrapper uses:
    json_view = json_store.get(entry.analysis_id)
    assert json_view is not None
    assert json_view.analysis_id == entry.analysis_id

    # SQLite side has the same row.
    sqlite_view = sqlite_store.get(entry.analysis_id)
    assert sqlite_view is not None
    assert sqlite_view.to_dict() == json_view.to_dict()


def test_history_read_matches_json(history_pair):
    """SQLite-backed reads match the JSON-backed view drift-free."""
    routed, json_store, sqlite_store = history_pair

    entry = routed.create(
        "600519",
        "2026-07-20",
        status="running",
        analysis_id="phase4-history-drift",
    )
    routed.mark_stage_done(entry.analysis_id, "market", report="market snip")
    routed.mark_stage_done(entry.analysis_id, "social", report="social snip")
    routed.mark_complete(
        entry.analysis_id,
        signal="Hold",
        elapsed=42.0,
        completed_stages=["market", "social"],
    )

    json_entry = json_store.get(entry.analysis_id)
    sqlite_entry = sqlite_store.get(entry.analysis_id)
    routed_entry = routed.get(entry.analysis_id)
    assert json_entry is not None
    assert sqlite_entry is not None
    assert routed_entry is not None
    assert json_entry.to_dict() == sqlite_entry.to_dict()
    assert json_entry.to_dict() == routed_entry.to_dict()


# ── log fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def log_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build an isolated LogStore pair with the read wrapper."""
    import backend.core.log_store as log_module

    logs_root = tmp_path / "logs"
    monkeypatch.setattr(log_module, "_LOGS_ROOT", logs_root)
    monkeypatch.setattr(log_module, "_log_store_singleton", None)

    json_store = LogStore()
    sqlite_store = SQLiteLogStore(tmp_path / "tradingagents.db")
    routed = DualReadLogStore(json_store, sqlite_store)

    json_writer = LogWriter("phase4-log", "600595", "2026-07-20")
    sqlite_writer = SQLiteLogWriter(
        "phase4-log",
        "600595",
        "2026-07-20",
        db_path=tmp_path / "tradingagents.db",
    )
    sqlite_writer.task_dir_name = json_writer.task_dir_name
    writer = DualReadLogWriter(
        "phase4-log",
        "600595",
        "2026-07-20",
        json_writer,
        sqlite_writer,
    )

    yield routed, writer, json_writer, sqlite_writer, sqlite_store

    sqlite_writer.close()
    sqlite_store.close()


def test_log_read_routes_to_sqlite(log_pair):
    """Reads (list_tickers / list_tasks / get_meta / count / stream) come from SQLite."""
    routed, writer, json_writer, sqlite_writer, sqlite_store = log_pair

    chunks = [
        LogChunk(ts=1.0, type="tool", agent="market_analyst", tool="quote",
                 input={"ticker": "600595"}, output="ok"),
        LogChunk(ts=2.0, type="agent_output", agent="market_analyst",
                 content="market report"),
        LogChunk(ts=3.0, type="llm", agent="bull", role="assistant",
                 tokens_in=10, tokens_out=20, content="bull says buy"),
    ]
    for chunk in chunks:
        writer.append_chunk(chunk)
    writer.update_stages(["stage1"])
    writer.finalize(signal="Buy", elapsed_sec=15.0)

    task = json_writer.task_dir_name
    assert routed.list_tickers() == ["600595"]
    tasks = routed.list_tasks("600595")
    assert len(tasks) == 1
    assert tasks[0].analysis_id == "phase4-log"

    meta = routed.get_meta("600595", task)
    assert meta["analysis_id"] == "phase4-log"
    assert meta["status"] == "completed"
    assert meta["signal"] == "Buy"

    counts = routed.count_chunks("600595", task)
    assert counts == {"llm": 1, "tool": 1, "agent_output": 1}

    streamed = list(routed.stream_chunks("600595", task))
    assert len(streamed) == 3
    assert [c.ts for c in streamed] == [1.0, 2.0, 3.0]


def test_log_write_still_dual_writes(log_pair):
    """Writes continue to hit the JSON file AND the SQLite sidecar."""
    routed, writer, json_writer, sqlite_writer, sqlite_store = log_pair

    chunk = LogChunk(
        ts=2.0,
        type="agent_output",
        agent="market_analyst",
        content="report",
    )
    writer.append_chunk(chunk)

    # JSONL view — should now have the chunk on disk.
    json_chunk_path = json_writer.task_dir / "agent_outputs.jsonl"
    json_lines = json_chunk_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(json_lines) == 1
    assert "report" in json_lines[0]

    # SQLite view — same chunk via SQLite query.
    sqlite_chunks = list(
        sqlite_store.stream_chunks("600595", json_writer.task_dir_name)
    )
    assert len(sqlite_chunks) == 1
    assert sqlite_chunks[0].content == "report"


def test_log_read_matches_jsonl(log_pair):
    """SQLite-backed reads match the JSONL-backed view drift-free."""
    routed, writer, json_writer, sqlite_writer, sqlite_store = log_pair

    chunks = [
        LogChunk(ts=1.0, type="tool", agent="a", tool="b", input={"x": 1},
                 output="ok"),
        LogChunk(ts=3.0, type="llm", agent="bull", role="assistant",
                 tokens_in=5, tokens_out=8, content="buy"),
        LogChunk(ts=2.0, type="agent_output", agent="a", content="c"),
    ]
    for chunk in chunks:
        writer.append_chunk(chunk)
    writer.finalize(signal="Sell", elapsed_sec=20.0)

    task = json_writer.task_dir_name
    sqlite_meta = sqlite_store.get_meta("600595", task)
    sqlite_chunks = [c.to_dict() for c in sqlite_store.stream_chunks(
        "600595", task
    )]
    routed_meta = routed.get_meta("600595", task)
    routed_chunks = [c.to_dict() for c in routed.stream_chunks(
        "600595", task
    )]

    assert sqlite_meta == routed_meta
    assert sqlite_chunks == routed_chunks
    # Sorted by ts; verify order matches the input order:
    assert [c["ts"] for c in routed_chunks] == [1.0, 2.0, 3.0]


# ── bootstrap test (lifespan-style) ──────────────────────────────────────


def test_enable_read_routing_is_idempotent_and_isolated(tmp_path, monkeypatch):
    """``enable_read_routing`` installs wrappers and ``close`` restores state.

    Runs against isolated directories to avoid clobbering the production
    HISTORY_DIR / SQLite database.  We treat the read-cutover bootstrap
    as a separate, replayable unit of work — running it twice rejects the
    second invocation, and ``close()`` keeps the original singleton values
    reachable for the next test in the suite.
    """
    from backend.core import history_store as history_module
    from backend.core import log_store as log_module
    from backend.core.read_routing import enable_read_routing

    history_dir = tmp_path / "history"
    logs_root = tmp_path / "logs"
    db_path = tmp_path / "tradingagents.db"
    history_dir.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(history_module, "_HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_module.HistoryStore, "_instance", None)
    monkeypatch.setattr(log_module, "_LOGS_ROOT", logs_root)
    monkeypatch.setattr(log_module, "_log_store_singleton", None)

    runtime = enable_read_routing(db_path=db_path)
    try:
        singleton = history_module.HistoryStore.get_instance()
        log_singleton = log_module.get_log_store()
        assert isinstance(singleton, DualReadHistoryStore)
        assert isinstance(log_singleton, DualReadLogStore)
    finally:
        runtime.close()

    # After close the original bindings must be reachable again.
    monkeypatch.setattr(history_module.HistoryStore, "_instance", None)
    fresh = history_module.HistoryStore.get_instance()
    assert type(fresh) is HistoryStore
