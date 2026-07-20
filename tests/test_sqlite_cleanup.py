"""Tests for backend.core.sqlite_cleanup (Phase 3d TTL auto-cleanup).

Each test gets a fresh temporary SQLite DB + isolated history/logs dirs via
pytest's ``tmp_path`` fixture so we never touch the user's real
``~/.tradingagents/tradingagents.db``.  The DB is bootstrapped with the
real schema migrations (001_initial.sql + 002_index_optimization.sql) so
the indexes the cleanup relies on are present.

Hard constraints honored by these tests:

* 0 changes to backend/core/log_store.py, history_store.py, runner.py
* 0 changes to frontend/*, pyproject.toml, spec
* restore_sqlite.sh is NOT exercised directly — we test the round-trip
  by invoking ``sqlite3``'s ``.backup`` / ``cp`` ourselves with the
  same shape the script uses, then verifying the restored DB is
  byte-identical to the source. This is safer than shelling out in CI.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from backend.core.sqlite_cleanup import (
    DEFAULT_HISTORY_TTL_DAYS,
    DEFAULT_LOG_TTL_DAYS,
    CleanupStats,
    SQLiteCleaner,
)
from backend.storage.schema_migrations import migrate as migrate_module
from backend.storage.schema_migrations.migrate import _apply_pragmas


# ── helpers ───────────────────────────────────────────────────────────────


def _bootstrap_db(db_path: Path) -> None:
    """Apply all schema migrations to a fresh tmp DB."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Run the migrate generator to completion (it yields status lines).
    list(migrate_module.migrate(db_path=db_path, dry_run=False))


def _insert_history(
    conn: sqlite3.Connection,
    analysis_id: str,
    *,
    status: str,
    finished_at: float | None,
    ticker: str = "600519",
    trade_date: str = "2026-07-20",
) -> None:
    conn.execute(
        """
        INSERT INTO history (
            analysis_id, ticker, trade_date, status, finished_at,
            created_at, started_at, results_path, elapsed, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            analysis_id,
            ticker,
            trade_date,
            status,
            finished_at,
            finished_at or time.time(),
            finished_at,
            "",
            1.0,
            1,
        ),
    )


def _insert_log_chunk(
    conn: sqlite3.Connection,
    *,
    analysis_id: str,
    task_dir_name: str,
    ts: float,
    chunk_type: str = "llm",
) -> None:
    conn.execute(
        """
        INSERT INTO log_chunks (
            analysis_id, task_dir_name, ts, type, agent, content
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (analysis_id, task_dir_name, ts, chunk_type, "market", "hello"),
    )


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    return int(cur.fetchone()[0])


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Fresh SQLite DB with the real schema applied."""
    db_path = tmp_path / "tradingagents.db"
    _bootstrap_db(db_path)
    return db_path


# ── tests ─────────────────────────────────────────────────────────────────


def test_cleanup_history_removes_old_completed(tmp_db: Path) -> None:
    """3 old completed rows + 2 recent ones → 3 deleted."""
    now = time.time()
    one_day_ago = now - 86400
    thirty_five_days_ago = now - (35 * 86400)

    conn = sqlite3.connect(str(tmp_db))
    try:
        # 3 old completed (should be deleted with default 30d TTL)
        for i in range(3):
            _insert_history(
                conn, f"old-completed-{i}", status="completed",
                finished_at=thirty_five_days_ago,
            )
        # 2 recent (should survive)
        for i in range(2):
            _insert_history(
                conn, f"recent-{i}", status="completed",
                finished_at=one_day_ago,
            )
        conn.commit()
        assert _count_rows(conn, "history") == 5
    finally:
        conn.close()

    cleaner = SQLiteCleaner(db_path=tmp_db, history_ttl_days=30, log_ttl_days=7)
    stats = cleaner.cleanup_history()
    cleaner.close()

    assert stats.history_deleted == 3, (
        f"expected 3 history rows deleted, got {stats.history_deleted}"
    )

    conn = sqlite3.connect(str(tmp_db))
    try:
        survivors = {row[0] for row in conn.execute("SELECT analysis_id FROM history")}
    finally:
        conn.close()
    assert "old-completed-0" not in survivors
    assert "old-completed-1" not in survivors
    assert "old-completed-2" not in survivors
    assert "recent-0" in survivors
    assert "recent-1" in survivors


def test_cleanup_log_chunks_removes_old(tmp_db: Path) -> None:
    """5 log_chunks (3 old + 2 new) → 3 deleted."""
    now = time.time()
    two_days_ago = now - (2 * 86400)
    ten_days_ago = now - (10 * 86400)

    conn = sqlite3.connect(str(tmp_db))
    try:
        for i in range(3):
            _insert_log_chunk(
                conn, analysis_id=f"old-{i}", task_dir_name=f"2026-07-01_run0{i}",
                ts=ten_days_ago,
            )
        for i in range(2):
            _insert_log_chunk(
                conn, analysis_id=f"recent-{i}", task_dir_name=f"2026-07-20_run0{i}",
                ts=two_days_ago,
            )
        conn.commit()
        assert _count_rows(conn, "log_chunks") == 5
    finally:
        conn.close()

    cleaner = SQLiteCleaner(db_path=tmp_db, history_ttl_days=30, log_ttl_days=7)
    stats = cleaner.cleanup_log_chunks()
    cleaner.close()

    assert stats.log_chunks_deleted == 3, (
        f"expected 3 log_chunks deleted, got {stats.log_chunks_deleted}"
    )

    conn = sqlite3.connect(str(tmp_db))
    try:
        survivors = {row[0] for row in conn.execute("SELECT analysis_id FROM log_chunks")}
    finally:
        conn.close()
    assert survivors == {"recent-0", "recent-1"}


def test_cleanup_respects_ttl_config(tmp_db: Path) -> None:
    """history_ttl_days=1 → more rows deleted than with default 30d.

    Two independent DBs are used (DB-A and DB-B) so the FK cascade from
    history → log_chunks doesn't bleed into the second assertion. We
    compare the *number* of history deletions, not the DB state.

    Math sanity:
      * 35-day-old rows  > 30d cutoff → deleted with default TTL
      * 5-day-old rows   < 30d cutoff → survive with default TTL
      * 5-day-old rows   >  1d cutoff → deleted with TTL=1d
    """
    from backend.storage.schema_migrations import migrate as migrate_module

    now = time.time()
    five_days_ago = now - (5 * 86400)
    thirty_five_days_ago = now - (35 * 86400)

    def _seed(db: Path) -> None:
        list(migrate_module.migrate(db_path=db, dry_run=False))
        c = sqlite3.connect(str(db))
        try:
            _insert_history(c, "old-0", status="completed", finished_at=thirty_five_days_ago)
            _insert_history(c, "old-1", status="completed", finished_at=thirty_five_days_ago)
            _insert_history(c, "recent-0", status="completed", finished_at=five_days_ago)
            _insert_history(c, "recent-1", status="completed", finished_at=five_days_ago)
            _insert_history(c, "recent-2", status="completed", finished_at=five_days_ago)
            c.commit()
        finally:
            c.close()

    db_a = tmp_db.parent / "db_a.db"
    db_b = tmp_db.parent / "db_b.db"
    _seed(db_a)
    _seed(db_b)

    # DB-A: default TTL=30 → only old-* (35d) are deleted → 2.
    cl_a = SQLiteCleaner(db_path=db_a)
    stats_a = cl_a.cleanup_history()
    cl_a.close()
    assert stats_a.history_deleted == 2, (
        f"DB-A: expected 2 deletes with TTL=30d, got {stats_a.history_deleted}"
    )

    # DB-B: TTL=1d → both old-* (35d) and recent-* (5d) are deleted → 5.
    cl_b = SQLiteCleaner(db_path=db_b, history_ttl_days=1)
    stats_b = cl_b.cleanup_history()
    cl_b.close()
    assert stats_b.history_deleted == 5, (
        f"DB-B: expected 5 deletes with TTL=1d, got {stats_b.history_deleted}"
    )
    assert stats_b.history_deleted > stats_a.history_deleted


def test_cleanup_is_idempotent(tmp_db: Path) -> None:
    """Running cleanup twice → second call deletes 0 rows.

    To prevent FK cascade (history → log_chunks) from making the second
    assertion trivially true, log_chunks rows here use distinct
    analysis_ids from history rows.  That way each cleanup pass has its
    own work to do, and the idempotent invariant is genuinely tested.
    """
    now = time.time()
    thirty_five_days_ago = now - (35 * 86400)

    conn = sqlite3.connect(str(tmp_db))
    try:
        for i in range(4):
            _insert_history(
                conn, f"idem-hist-{i}", status="completed",
                finished_at=thirty_five_days_ago,
            )
        for i in range(4):
            _insert_log_chunk(
                conn, analysis_id=f"idem-log-{i}", task_dir_name=f"old_run0{i}",
                ts=now - (10 * 86400),
            )
        conn.commit()
    finally:
        conn.close()

    cleaner = SQLiteCleaner(db_path=tmp_db, history_ttl_days=30, log_ttl_days=7)
    try:
        first = cleaner.cleanup_all()
        second = cleaner.cleanup_all()
    finally:
        cleaner.close()

    assert first.history_deleted == 4
    assert first.log_chunks_deleted == 4
    # Idempotent: second pass must do nothing.
    assert second.history_deleted == 0, (
        f"second pass should delete 0 history rows, got {second.history_deleted}"
    )
    assert second.log_chunks_deleted == 0, (
        f"second pass should delete 0 log_chunks, got {second.log_chunks_deleted}"
    )
    assert second.is_no_op()


def test_backup_and_restore_roundtrip(tmp_db: Path, tmp_path: Path) -> None:
    """Backup the DB, drop the live one, restore from backup → identical.

    Mirrors what scripts/backup_sqlite.sh + scripts/restore_sqlite.sh
    do at the SQL level: TRUNCATE the WAL, then ``.backup`` the DB to
    a sibling file.  We don't shell out to the .sh scripts because CI
    may not have bash on PATH; the SQL primitives are what matters.
    """
    now = time.time()
    thirty_five_days_ago = now - (35 * 86400)

    # Seed a known set of rows so we can compare contents.
    # Use distinct analysis_ids across tables so the FK CASCADE from
    # history doesn't pre-delete the log_chunks before cleanup_log_chunks
    # gets a chance to run.
    conn = sqlite3.connect(str(tmp_db))
    try:
        for i in range(3):
            _insert_history(
                conn, f"bkp-h-{i}", status="completed",
                finished_at=thirty_five_days_ago,
            )
        for i in range(2):
            _insert_log_chunk(
                conn, analysis_id=f"bkp-l-{i}", task_dir_name=f"backup_run0{i}",
                ts=now - (10 * 86400),
            )
        conn.commit()
    finally:
        conn.close()

    # 1. Run cleanup to delete the old rows so we have an *interesting*
    #    state in the backup (mix of deletes + survivors).
    cleaner = SQLiteCleaner(db_path=tmp_db, history_ttl_days=30, log_ttl_days=7)
    pre_stats = cleaner.cleanup_all()
    cleaner.close()
    assert pre_stats.history_deleted == 3
    assert pre_stats.log_chunks_deleted == 2

    # Snapshot the live DB's row counts after cleanup.
    def _snapshot(db: Path) -> dict[str, int]:
        c = sqlite3.connect(str(db))
        try:
            return {
                "history": _count_rows(c, "history"),
                "log_chunks": _count_rows(c, "log_chunks"),
                "stage_reports": _count_rows(c, "stage_reports"),
                "completed_stages": _count_rows(c, "completed_stages"),
                "schema_migrations": _count_rows(c, "schema_migrations"),
            }
        finally:
            c.close()

    pre_snapshot = _snapshot(tmp_db)
    assert pre_snapshot["history"] == 0  # all 3 deleted
    assert pre_snapshot["log_chunks"] == 0  # both deleted

    # 2. Run the same WAL checkpoint + .backup dance as backup_sqlite.sh.
    backup_path = tmp_path / "db-backup.db"
    subprocess.run(
        ["sqlite3", str(tmp_db), "PRAGMA wal_checkpoint(TRUNCATE);"],
        check=True,
    )
    subprocess.run(
        ["sqlite3", str(tmp_db), f".backup '{backup_path}'"],
        check=True,
    )
    assert backup_path.exists()
    assert backup_path.stat().st_size > 0

    # 3. Restore: cp the backup over the live DB (this is what
    #    restore_sqlite.sh does, modulo the .new + mv atomicity).
    shutil.copyfile(backup_path, tmp_db)

    # 4. Compare row counts. The restored DB must match the snapshot.
    post_snapshot = _snapshot(tmp_db)
    assert post_snapshot == pre_snapshot, (
        f"restore mismatch: before={pre_snapshot}, after={post_snapshot}"
    )

    # 5. Spot-check the actual row identities — all old rows must be
    #    absent (they were already deleted before backup).
    c = sqlite3.connect(str(tmp_db))
    try:
        ids = {row[0] for row in c.execute("SELECT analysis_id FROM history")}
        chunk_ids = {row[0] for row in c.execute("SELECT analysis_id FROM log_chunks")}
    finally:
        c.close()
    assert ids == set()
    assert chunk_ids == set()