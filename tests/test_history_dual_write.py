"""Integration tests for the Phase 3b HistoryStore dual-write period.

The tests use temporary JSON and SQLite roots and exercise only the public
store APIs.  The JSON store remains the read source of truth while every
mutation is reconciled against the SQLite sidecar.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from backend.core.history_store_dualwrite import DualWriteHistoryStore
from backend.core.history_store_sqlite import SQLiteHistoryStore


def _json_snapshot(history_dir: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for path in sorted(history_dir.glob("*.json")):
        result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return result


def _sqlite_snapshot(store: SQLiteHistoryStore) -> dict[str, dict]:
    entries, _ = store.list_all(limit=10_000, offset=0)
    return {entry.analysis_id: entry.to_dict() for entry in entries}


@pytest.fixture()
def dual_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Construct a completely isolated JSON + SQLite dual-write pair."""
    from backend.core import history_store as history_module

    history_dir = tmp_path / "history"
    monkeypatch.setattr(history_module, "_HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_module.HistoryStore, "_instance", None)

    json_store = history_module.HistoryStore.get_instance()
    sqlite_store = SQLiteHistoryStore(tmp_path / "tradingagents.db")
    store = DualWriteHistoryStore(json_store, sqlite_store)
    yield store, history_dir, sqlite_store
    store.close()


def test_dual_write_lifecycle_has_no_drift(dual_store):
    store, history_dir, sqlite_store = dual_store

    entry = store.create(
        "600519",
        "2026-07-20",
        status="running",
        analysis_id="dual-lifecycle",
    )
    store.mark_running(entry.analysis_id)
    store.mark_stage_done(
        entry.analysis_id,
        "market",
        report="market report",
        report_key="market_report",
    )
    store.mark_stage_done(entry.analysis_id, "social", report="social report")
    store.mark_complete(
        entry.analysis_id,
        signal="Buy",
        elapsed=12.5,
        completed_stages=["market", "social"],
    )
    store.set_results_path(entry.analysis_id, "/tmp/full_states_log.json")

    json_entry = store.get(entry.analysis_id)
    sqlite_entry = sqlite_store.get(entry.analysis_id)
    assert json_entry is not None
    assert sqlite_entry is not None
    assert json_entry.to_dict() == sqlite_entry.to_dict()
    assert _json_snapshot(history_dir) == _sqlite_snapshot(sqlite_store)

    # The wrapper's reads are intentionally still served by JSON in Phase 3b.
    assert store.list_all(limit=10)[0][0].to_dict() == json_entry.to_dict()


def test_delete_and_zombie_cleanup_reconcile_both_stores(dual_store):
    store, history_dir, sqlite_store = dual_store

    deleted = store.create(
        "000001",
        "2026-07-20",
        status="running",
        analysis_id="delete-me",
    )
    store.delete(deleted.analysis_id)
    assert store.get(deleted.analysis_id) is None
    assert sqlite_store.get(deleted.analysis_id) is None
    assert not (history_dir / f"{deleted.analysis_id}.json").exists()

    created_at = time.time() - 120
    zombie = store.create(
        "000002",
        "2026-07-20",
        status="running",
        analysis_id="zombie-me",
    )
    zombie.created_at = created_at
    store.update(zombie)

    cleaned = store.cleanup_zombies(now=time.time())
    assert cleaned == ["zombie-me"]
    json_entry = store.get("zombie-me")
    sqlite_entry = sqlite_store.get("zombie-me")
    assert json_entry is not None and sqlite_entry is not None
    assert json_entry.to_dict() == sqlite_entry.to_dict()
    assert json_entry.status == "error"
    assert _json_snapshot(history_dir) == _sqlite_snapshot(sqlite_store)


def test_sqlite_foreign_keys_and_schema_are_enabled(dual_store):
    _store, _history_dir, sqlite_store = dual_store

    tables = {
        row[0]
        for row in sqlite_store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"history", "stage_reports", "completed_stages", "log_chunks"} <= tables
    assert sqlite_store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert sqlite_store._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    with pytest.raises(sqlite3.IntegrityError):
        sqlite_store._conn.execute(
            "INSERT INTO stage_reports "
            "(analysis_id, report_key, stage_id, content, created_at) "
            "VALUES ('missing', 'r', 's', 'x', 0)"
        )
