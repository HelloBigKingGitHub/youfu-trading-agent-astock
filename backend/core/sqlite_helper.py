"""P2.31 hotfix: history_cleanup 用的 SQLite 旁路 helper.

提供跟 JSON layer 同 shape 的 bulk delete 接口, 不引入循环依赖.

Phase 3b 把 ``history_store_sqlite.SQLiteHistoryStore`` 做成 JSON
``HistoryStore`` 的旁路 sidecar, 但 ``history_cleanup.purge_history`` 在
Phase 4 切读路径之后只清 JSON layer — SQLite 表里还留着 17 条
``history`` 行, ``DualReadHistoryStore.list_all()`` 一查就又冒出来.

这里给 ``history_cleanup`` 提供两个 bulk delete 函数, 让 purge 同时清
两侧, 跟 Phase 3b / 3c 双写语义对称.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_sqlite_history_store_or_none(db_path: Optional[Path] = None):
    """懒加载 SQLiteHistoryStore (跟 history_cleanup lazy import 一致).

    Returns ``None`` when ``backend.core.history_store_sqlite`` is
    unavailable (e.g. Python 构建 without ``sqlite3``).  Callers must
    handle the ``None`` path — purge never aborts on SQLite cleanup
    failure; the JSON wipe already succeeded.

    The helper does **not** cache the returned store: the cleanup service
    only uses it once per call and we want a fresh connection each time
    so a long-running server can reload the schema without stale
    connections.  ``SQLiteHistoryStore`` already opens a private
    connection guarded by an ``RLock``, so callers don't need extra
    locking on top.
    """
    try:
        from backend.core.history_store_sqlite import SQLiteHistoryStore

        return SQLiteHistoryStore(db_path)
    except ImportError as exc:
        logger.warning("sqlite_helper: SQLiteHistoryStore unavailable: %s", exc)
        return None


def bulk_delete_all_history(sqlite_store) -> int:
    """Bulk ``DELETE FROM history`` (children cascade via FK).

    FK declarations on ``stage_reports`` / ``completed_stages`` /
    ``log_chunks`` reference ``history(analysis_id)`` with
    ``ON DELETE CASCADE``.  The parent delete therefore propagates
    automatically — we don't need (and don't want) to issue explicit
    child-table deletes here, because that would *also* zero the
    ``log_runs_deleted`` tally that
    :func:`bulk_delete_all_log_chunks` is responsible for.

    Returns the number of ``history`` rows deleted.  The store uses
    ``isolation_level=None`` + explicit ``BEGIN IMMEDIATE``, so the
    single transaction is safe under ``READ_FROM_SQLITE=1`` even when
    the FastAPI handler is concurrently serving reads.
    """
    if sqlite_store is None:
        return 0
    conn = sqlite_store._conn
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    try:
        cur.execute("DELETE FROM history")
        total = cur.rowcount
        conn.execute("COMMIT")
        logger.warning("sqlite_helper: bulk_delete_all_history removed %d rows", total)
        return total
    except Exception:
        conn.execute("ROLLBACK")
        raise


def bulk_delete_all_log_chunks(sqlite_store) -> int:
    """Bulk ``DELETE FROM log_chunks`` + ``stage_reports`` + ``completed_stages``.

    Keeps ``history`` rows intact (those are wiped by
    :func:`bulk_delete_all_history`).  Mirrors the JSON side's
    per-run-dir wipe — both sides of the dual-write layer get the
    same destructive treatment so a post-purge ``/api/history`` /
    ``/api/logs`` response is empty.

    Returns total child-row count deleted.
    """
    if sqlite_store is None:
        return 0
    conn = sqlite_store._conn
    cur = conn.cursor()
    cur.execute("BEGIN IMMEDIATE")
    try:
        cur.execute("DELETE FROM log_chunks")
        total = cur.rowcount
        cur.execute("DELETE FROM stage_reports")
        cur.execute("DELETE FROM completed_stages")
        conn.execute("COMMIT")
        return total
    except Exception:
        conn.execute("ROLLBACK")
        raise