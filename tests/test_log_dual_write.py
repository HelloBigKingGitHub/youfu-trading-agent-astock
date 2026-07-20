"""Integration tests for the Phase 3c LogStore dual-write period."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.core.log_store import LogChunk, LogStore, LogWriter
from backend.core.log_store_dualwrite import DualWriteLogStore, DualWriteLogWriter
from backend.core.log_store_sqlite import SQLiteLogStore, SQLiteLogWriter


def _json_snapshot(task_dir: Path) -> dict:
    meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
    chunks = []
    for name in ("llm_messages.jsonl", "tool_calls.jsonl", "agent_outputs.jsonl"):
        path = task_dir / name
        if path.exists():
            chunks.extend(
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
    return {
        "meta": meta,
        "chunks": sorted(chunks, key=lambda item: item["ts"]),
    }


def _sqlite_snapshot(store: SQLiteLogStore, ticker: str, task: str) -> dict:
    meta = store.get_meta(ticker, task)
    chunks = [chunk.to_dict() for chunk in store.stream_chunks(ticker, task)]
    return {"meta": meta, "chunks": chunks}


@pytest.fixture()
def dual_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build isolated legacy JSON + SQLite writers."""
    import backend.core.log_store as log_module

    logs_root = tmp_path / "logs"
    monkeypatch.setattr(log_module, "_LOGS_ROOT", logs_root)
    monkeypatch.setattr(log_module, "_log_store_singleton", None)

    json_writer = LogWriter("phase3c-analysis", "600595", "2026-07-20")
    sqlite_writer = SQLiteLogWriter(
        "phase3c-analysis",
        "600595",
        "2026-07-20",
        db_path=tmp_path / "tradingagents.db",
    )
    # The JSON writer is authoritative for the task directory name.
    sqlite_writer.task_dir_name = json_writer.task_dir_name
    writer = DualWriteLogWriter(
        "phase3c-analysis",
        "600595",
        "2026-07-20",
        json_writer,
        sqlite_writer,
    )
    yield writer, json_writer, sqlite_writer, logs_root
    sqlite_writer.close()


def test_dual_write_lifecycle_has_zero_drift(dual_writer):
    writer, json_writer, sqlite_writer, logs_root = dual_writer
    chunks = [
        LogChunk(
            ts=3.0,
            type="tool",
            agent="market_analyst",
            tool="quote",
            input={"ticker": "600595"},
            output="ok",
        ),
        LogChunk(
            ts=1.0,
            type="llm",
            agent="market_analyst",
            role="assistant",
            tokens_in=10,
            tokens_out=4,
            content="market report",
        ),
        LogChunk(
            ts=2.0,
            type="agent_output",
            agent="market_analyst",
            report_key="market_report",
            content="agent report",
        ),
    ]
    for chunk in chunks:
        writer.append_chunk(chunk)
    writer.update_stages(["market", "social"])
    writer.finalize(
        signal="Buy",
        elapsed_sec=12.5,
        completed_stages=["market", "social"],
    )

    task_dir = logs_root / "600595" / json_writer.task_dir_name
    sqlite_reader = SQLiteLogStore(logs_root.parent / "tradingagents.db")
    try:
        json_view = _json_snapshot(task_dir)
        sqlite_view = _sqlite_snapshot(
            sqlite_reader,
            "600595",
            json_writer.task_dir_name,
        )
        # JSON and SQLite use different representation names for elapsed and
        # input_json internally, so compare their canonical public shapes.
        assert json_view["chunks"] == sqlite_view["chunks"]
        assert json_view["meta"]["analysis_id"] == sqlite_view["meta"]["analysis_id"]
        assert json_view["meta"]["ticker"] == sqlite_view["meta"]["ticker"]
        assert json_view["meta"]["trade_date"] == sqlite_view["meta"]["trade_date"]
        assert json_view["meta"]["status"] == sqlite_view["meta"]["status"] == "completed"
        assert json_view["meta"]["signal"] == sqlite_view["meta"]["signal"] == "Buy"
        assert json_view["meta"]["chunk_counts"] == sqlite_view["meta"]["chunk_counts"]
        assert sqlite_writer.chunk_counts == {
            "llm": 1,
            "tool": 1,
            "agent_output": 1,
        }
    finally:
        sqlite_reader.close()


def test_sqlite_read_api_matches_json_read_api(dual_writer):
    writer, json_writer, sqlite_writer, _logs_root = dual_writer
    writer.append_chunk(LogChunk(ts=2.0, type="llm", agent="a", content="b"))
    writer.append_chunk(LogChunk(ts=1.0, type="tool", agent="a", tool="t"))
    writer.finalize(signal="Hold", elapsed_sec=2.0)

    json_store = LogStore()
    sqlite_store = SQLiteLogStore(sqlite_writer.db)
    try:
        assert sqlite_store.list_tickers() == json_store.list_tickers()
        assert [task.task_dir_name for task in sqlite_store.list_tasks("600595")] == [
            task.task_dir_name for task in json_store.list_tasks("600595")
        ]
        assert sqlite_store.count_chunks("600595", json_writer.task_dir_name) == (
            json_store.count_chunks("600595", json_writer.task_dir_name)
        )
        assert [chunk.to_dict() for chunk in sqlite_store.stream_chunks(
            "600595", json_writer.task_dir_name, type_filter="llm"
        )] == [chunk.to_dict() for chunk in json_store.stream_chunks(
            "600595", json_writer.task_dir_name, type_filter="llm"
        )]
        assert sqlite_store.get_meta("600595", json_writer.task_dir_name)["status"] == (
            json_store.get_meta("600595", json_writer.task_dir_name)["status"]
        )
    finally:
        sqlite_store.close()


def test_dual_store_reads_are_json_only(dual_writer):
    writer, json_writer, _sqlite_writer, _logs_root = dual_writer
    writer.append_chunk(LogChunk(ts=1.0, type="llm", agent="a", content="json"))

    class ExplodingSQLite:
        def list_tickers(self):
            raise AssertionError("SQLite read should not be used")

        def list_tasks(self, _ticker):
            raise AssertionError("SQLite read should not be used")

        def get_meta(self, _ticker, _task):
            raise AssertionError("SQLite read should not be used")

        def count_chunks(self, _ticker, _task):
            raise AssertionError("SQLite read should not be used")

        def stream_chunks(self, _ticker, _task, _type_filter=None):
            raise AssertionError("SQLite read should not be used")

    store = DualWriteLogStore(LogStore(), ExplodingSQLite())
    assert store.list_tickers() == ["600595"]
    assert store.count_chunks("600595", json_writer.task_dir_name)["llm"] == 1
    assert [c.content for c in store.stream_chunks("600595", json_writer.task_dir_name)] == [
        "json"
    ]


def test_sqlite_pragmas_and_foreign_keys(dual_writer):
    _writer, _json_writer, sqlite_writer, _logs_root = dual_writer
    conn = sqlite_writer._conn
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO log_chunks "
            "(analysis_id, task_dir_name, ts, type, agent) "
            "VALUES ('missing', 'x', 0, 'llm', '')"
        )


def test_dual_write_failures_are_non_fatal():
    calls = []

    class FailingWriter:
        def append_chunk(self, _chunk):
            calls.append("json")
            raise OSError("json down")

        def update_stages(self, _stages):
            raise OSError("json down")

        def finalize(self, **_kwargs):
            raise OSError("json down")

    class WorkingWriter:
        def append_chunk(self, _chunk):
            calls.append("sqlite")

        def update_stages(self, _stages):
            calls.append("sqlite-stages")

        def finalize(self, **_kwargs):
            calls.append("sqlite-finalize")

    writer = DualWriteLogWriter(
        "a",
        "600595",
        "2026-07-20",
        FailingWriter(),
        WorkingWriter(),
    )
    writer.append_chunk(LogChunk(ts=1, type="llm", agent="a"))
    writer.update_stages(["market"])
    writer.finalize(signal="")
    assert calls == ["json", "sqlite", "sqlite-stages", "sqlite-finalize"]
