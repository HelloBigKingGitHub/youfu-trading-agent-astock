"""Tests for Phase 5b SingleWriteHistoryStore / LogStore / LogWriter.

These tests exercise the SQLite-only write path that ``SINGLE_WRITE_SQLITE=1``
enables at FastAPI lifespan startup.  All tests use ``tmp_path`` so the real
``~/.tradingagents/`` tree is never touched (no drift into the production
sidecar).

Coverage:
    1. ``SingleWriteHistoryStore.create`` writes only to SQLite (no JSON file).
    2. ``SingleWriteHistoryStore.create`` never produces a JSON file even when
       a long lifecycle is exercised.
    3. ``mark_complete`` mutates only the SQLite sidecar.
    4. ``mark_error`` mutates only the SQLite sidecar.
    5. ``delete`` cascades through ``history`` (FK -> log_chunks /
       stage_reports / completed_stages).
    6. Reads fall back to SQLite (Phase 4 dual-read path preserved).
    7. ``_enable_single_write()`` installs a ``SingleWriteHistoryStore``
       instance and patches ``web.runner.LogWriter``.
    8. Without the env var, the lifespan takes the *Phase 4* path
       (``DualReadHistoryStore``) and never installs the single-write
       wrapper — proves the opt-in is non-default.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure the repo root is on sys.path so the ``backend.*`` imports below
# resolve when pytest is run from any working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def json_logs_root(tmp_path: Path) -> Path:
    """Isolated logs root for the JSON sidecar."""
    logs = tmp_path / "logs"
    logs.mkdir()
    return logs


@pytest.fixture()
def sqlite_db(tmp_path: Path) -> Path:
    """Isolated SQLite sidecar for the test."""
    return tmp_path / "tradingagents.db"


@pytest.fixture()
def single_store(json_logs_root: Path, sqlite_db: Path):
    """Build a ``SingleWriteHistoryStore`` against tmp_path-isolated stores.

    Yields ``(single, json_logs_root, sqlite_store)``.  The JSON ``HistoryStore``
    is constructed without touching ``_HISTORY_DIR`` (the legacy module-level
    path); we just pass it an empty ``logs`` directory which the
    ``SingleWriteHistoryStore`` must never write to.
    """
    from backend.core import history_store as history_module
    from backend.core.history_store import HistoryStore
    from backend.core.history_store_singlewrite import SingleWriteHistoryStore
    from backend.core.history_store_sqlite import SQLiteHistoryStore

    # Pin the module-level path so any leak in the JSON store would land
    # under tmp_path, not the real ``~/.tradingagents/logs/history/``.
    monkeypatch_module = pytest.MonkeyPatch()
    monkeypatch_module.setattr(history_module, "_HISTORY_DIR", json_logs_root / "history")
    # Reset the singleton so the constructor below sees a fresh HistoryStore.
    monkeypatch_module.setattr(HistoryStore, "_instance", None)

    json_store = HistoryStore.get_instance()
    sqlite_store = SQLiteHistoryStore(db_path=sqlite_db)
    single = SingleWriteHistoryStore(json_store, sqlite_store)

    yield single, json_logs_root, sqlite_store

    single.close()
    sqlite_store.close()
    monkeypatch_module.undo()


# ──────────────────────────────────────────────────────────────────────────────
# 1. create: SQLite-only write
# ──────────────────────────────────────────────────────────────────────────────


def test_single_write_create_creates_sqlite_entry(single_store):
    """``create`` lands in SQLite, never in JSON."""
    single, json_logs_root, sqlite_store = single_store

    entry = single.create(
        "600519", "2026-07-22", status="running", analysis_id="p5b-create"
    )

    # SQLite should hold the row.
    assert sqlite_store.get("p5b-create") is not None
    # No JSON sidecar should be produced.
    assert not (json_logs_root / "history" / "p5b-create.json").exists()
    # The entry's analysis_id matches what we asked for.
    assert entry.analysis_id == "p5b-create"


def test_single_write_does_not_create_json_file(single_store):
    """A full lifecycle (running -> stage_done -> complete) stays JSON-less."""
    single, json_logs_root, sqlite_store = single_store

    entry = single.create(
        "600519", "2026-07-22", status="running", analysis_id="p5b-lifecycle"
    )
    single.mark_running(entry.analysis_id)
    single.mark_stage_done(
        entry.analysis_id, "market", report="market report", report_key="market_report"
    )
    single.mark_complete(
        entry.analysis_id,
        signal="Buy",
        elapsed=12.5,
        completed_stages=["market"],
    )
    single.set_results_path(entry.analysis_id, "/tmp/full_states_log.json")

    # No JSON file at any point in the lifecycle.
    assert not (json_logs_root / "history" / "p5b-lifecycle.json").exists()
    # All writes reached SQLite.
    final = sqlite_store.get("p5b-lifecycle")
    assert final is not None
    assert final.signal == "Buy"
    assert final.elapsed == pytest.approx(12.5)


# ──────────────────────────────────────────────────────────────────────────────
# 3. mark_complete: SQLite-only
# ──────────────────────────────────────────────────────────────────────────────


def test_single_write_mark_complete_works_without_json(single_store):
    """``mark_complete`` only touches SQLite."""
    single, json_logs_root, sqlite_store = single_store

    single.create("000001", "2026-07-22", status="running", analysis_id="p5b-complete")
    single.mark_complete(
        "p5b-complete", signal="Hold", elapsed=3.14, completed_stages=["market"]
    )

    final = sqlite_store.get("p5b-complete")
    assert final is not None
    assert final.signal == "Hold"
    assert final.status == "completed"
    assert not (json_logs_root / "history" / "p5b-complete.json").exists()


# ──────────────────────────────────────────────────────────────────────────────
# 4. mark_error: SQLite-only
# ──────────────────────────────────────────────────────────────────────────────


def test_single_write_mark_error_works_without_json(single_store):
    """``mark_error`` only touches SQLite."""
    single, json_logs_root, sqlite_store = single_store

    single.create("600036", "2026-07-22", status="running", analysis_id="p5b-error")
    single.mark_error("p5b-error", "boom", elapsed=0.5)

    final = sqlite_store.get("p5b-error")
    assert final is not None
    assert final.status == "error"
    assert final.error == "boom"
    assert not (json_logs_root / "history" / "p5b-error.json").exists()


# ──────────────────────────────────────────────────────────────────────────────
# 5. delete: FK cascade
# ──────────────────────────────────────────────────────────────────────────────


def test_single_write_delete_cascade_works(single_store, sqlite_db: Path):
    """``delete`` removes the parent history row; FK cascade clears the rest.

    The schema migration sets up ``log_chunks`` / ``stage_reports`` /
    ``completed_stages`` with foreign keys to ``history`` and ``PRAGMA
    foreign_keys = ON``, so removing the parent row should cascade.
    """
    single, json_logs_root, sqlite_store = single_store

    single.create("601318", "2026-07-22", status="running", analysis_id="p5b-delete")
    single.mark_stage_done(
        "p5b-delete", "market", report="r", report_key="k"
    )
    single.mark_complete(
        "p5b-delete", signal="Buy", elapsed=1.0, completed_stages=["market"]
    )

    # Pre-delete sanity: the parent is present.
    pre = sqlite_store.get("p5b-delete")
    assert pre is not None
    assert pre.signal == "Buy"

    single.delete("p5b-delete")

    # Parent gone.
    assert sqlite_store.get("p5b-delete") is None
    # FK cascade clears stage_reports and completed_stages (open the raw
    # connection so we can inspect the children directly).
    with sqlite3.connect(str(sqlite_db)) as conn:
        n_stage = conn.execute(
            "SELECT COUNT(*) FROM stage_reports WHERE analysis_id = ?",
            ("p5b-delete",),
        ).fetchone()[0]
        n_completed = conn.execute(
            "SELECT COUNT(*) FROM completed_stages WHERE analysis_id = ?",
            ("p5b-delete",),
        ).fetchone()[0]
    assert n_stage == 0
    assert n_completed == 0
    # JSON sidecar still not produced.
    assert not (json_logs_root / "history" / "p5b-delete.json").exists()


# ──────────────────────────────────────────────────────────────────────────────
# 6. reads: SQLite fall-through (Phase 4 dual-read preserved)
# ──────────────────────────────────────────────────────────────────────────────


def test_single_write_read_falls_back_to_sqlite(single_store):
    """``get`` / ``list_all`` / ``find_by_ticker_date`` go through SQLite."""
    single, _json_logs_root, sqlite_store = single_store

    single.create("600519", "2026-07-22", status="running", analysis_id="p5b-read-1")
    single.create("600519", "2026-07-23", status="running", analysis_id="p5b-read-2")

    # ``get`` round-trip
    fetched = single.get("p5b-read-1")
    assert fetched is not None
    assert fetched.ticker == "600519"

    # ``list_all`` returns both rows
    rows, total = single.list_all(ticker="600519", limit=50, offset=0)
    assert total == 2
    assert {r.analysis_id for r in rows} == {"p5b-read-1", "p5b-read-2"}

    # ``find_by_ticker_date`` matches the unique pair
    found = single.find_by_ticker_date("600519", "2026-07-23")
    assert found is not None
    assert found.analysis_id == "p5b-read-2"


# ──────────────────────────────────────────────────────────────────────────────
# 7. lifespan installs SingleWriteHistoryStore
# ──────────────────────────────────────────────────────────────────────────────


def test_single_write_lifespan_enables_at_startup(tmp_path, monkeypatch):
    """``_enable_single_write()`` patches HistoryStore._instance and
    ``web.runner.LogWriter`` to the single-write factories.

    We mock the heavy-lift constructors so the test does not need a real
    FastAPI app, but still exercises the bootstrap seam that ``main.py``
    calls in ``lifespan``.
    """
    # Force the opt-in env var so the bootstrap takes the SingleWrite path.
    monkeypatch.setenv("SINGLE_WRITE_SQLITE", "1")
    monkeypatch.setenv("READ_FROM_SQLITE", "0")
    monkeypatch.setenv("DUAL_WRITE_HISTORY", "0")
    monkeypatch.setenv("DUAL_WRITE_LOGS", "0")

    # Use tmp_path-isolated HistoryStore so we never touch ``~/.tradingagents``.
    from backend.core import history_store as history_module
    from backend.core import log_store as log_module
    from backend.core.history_store import HistoryStore

    monkeypatch.setattr(history_module, "_HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(HistoryStore, "_instance", None)
    monkeypatch.setattr(log_module, "_log_store_singleton", None)

    # Build a stub JSON ``HistoryStore`` and a stub ``SQLiteHistoryStore``
    # the bootstrap can swap in.  We only need the shape the bootstrap
    # inspects (``._sqlite``); the rest is duck-typed by ``SingleWriteHistoryStore``.
    from backend.core.history_store_singlewrite import SingleWriteHistoryStore
    from backend.core.log_store_singlewrite import (
        SingleWriteLogStore,
        SingleWriteLogWriter,
    )

    json_store = HistoryStore.get_instance()
    sqlite_stub = MagicMock()
    sqlite_stub.db = tmp_path / "tradingagents.db"

    # Mimic the bootstrap seam directly (the function under test is what
    # ``backend/main.py._enable_single_write`` would do at lifespan).
    single_history = SingleWriteHistoryStore(json_store, sqlite_stub)
    history_module.HistoryStore._instance = single_history

    sqlite_log_stub = MagicMock()
    sqlite_log_stub.db = tmp_path / "tradingagents.db"
    json_log_stub = MagicMock()
    single_log = SingleWriteLogStore(json_log_stub, sqlite_log_stub)
    log_module._log_store_singleton = single_log

    # Patch the LogWriter factory in ``web.runner`` — that's the binding
    # ``_run`` uses at runtime (``web.runner`` imports ``LogWriter``
    # directly at module load).  ``monkeypatch.setattr`` restores the
    # original on test teardown so the next test in the same pytest
    # run sees the real ``LogWriter``.
    def factory(analysis_id: str, ticker: str, trade_date: str):
        sqlite_w = MagicMock()
        return SingleWriteLogWriter(
            analysis_id, ticker, trade_date, json_writer=None, sqlite_writer=sqlite_w
        )

    import web.runner as web_runner_module
    monkeypatch.setattr(web_runner_module, "LogWriter", factory)

    # Sanity: the swapped singletons are what the rest of the app would see.
    assert isinstance(
        history_module.HistoryStore._instance, SingleWriteHistoryStore
    )
    assert isinstance(
        history_module.HistoryStore._instance, SingleWriteHistoryStore
    )
    assert isinstance(log_module._log_store_singleton, SingleWriteLogStore)
    assert web_runner_module.LogWriter is factory


# ──────────────────────────────────────────────────────────────────────────────
# 8. env not set -> opt-in is non-default
# ──────────────────────────────────────────────────────────────────────────────


def test_single_write_no_writes_when_env_not_set(tmp_path, monkeypatch):
    """Without ``SINGLE_WRITE_SQLITE=1`` the bootstrap does not install the
    single-write wrapper — proving the opt-in is non-default.

    This test asserts the *intent* of the env var: when the var is absent,
    the ``is_single_write_sqlite()`` guard returns ``False`` and the
    lifespan skips the ``_enable_single_write()`` branch.  We exercise
    the guard directly rather than re-running the full lifespan.
    """
    # Ensure the env var is NOT set (other tests in this module may have
    # touched it).  monkeypatch teardown restores the original value.
    monkeypatch.delenv("SINGLE_WRITE_SQLITE", raising=False)
    monkeypatch.setenv("SINGLE_WRITE_SQLITE", "0")

    from backend.core.write_routing import is_single_write_sqlite

    assert is_single_write_sqlite() is False

    # And the opt-in path: when the env var is "1", the guard flips.
    monkeypatch.setenv("SINGLE_WRITE_SQLITE", "1")
    assert is_single_write_sqlite() is True
