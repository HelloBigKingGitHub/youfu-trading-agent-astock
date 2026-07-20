"""SQLite-backed HistoryStore compatibility implementation.

This module is deliberately separate from :mod:`history_store`.  During the
Phase 3b dual-write period the existing JSON ``HistoryStore`` remains the read
source of truth; this class is the SQLite sidecar used for migration and
reconciliation.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Iterator

from backend.core.history_store import (
    STUCK_THRESHOLD_SEC,
    ZOMBIE_THRESHOLD_SEC,
    HistoryEntry,
)
from backend.storage.schema_migrations.migrate import migrate

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path.home() / ".tradingagents" / "tradingagents.db"


class SQLiteHistoryStore:
    """SQLite implementation with the same public API as ``HistoryStore``.

    The connection is opened in autocommit mode, but every mutation is still
    wrapped in an explicit ``BEGIN IMMEDIATE`` / ``COMMIT`` transaction.  The
    connection is shared by the worker threads used by the backend and guarded
    by an RLock, so SQLite's default same-thread restriction is disabled
    safely at the store boundary.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db = Path(db_path) if db_path is not None else _DEFAULT_DB
        self.db.parent.mkdir(parents=True, exist_ok=True)

        # Phase 3a owns schema creation.  Running the idempotent migration
        # runner here makes a fresh sidecar usable without a separate startup
        # command, while leaving the migration files themselves untouched.
        list(migrate(db_path=self.db))

        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db),
            isolation_level=None,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()

    def _apply_pragmas(self) -> None:
        """Apply connection-local PRAGMAs once, immediately after connect."""
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA cache_size = -64000")
        self._conn.execute("PRAGMA temp_store = MEMORY")

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[None]:
        """Serialize a write and make its transaction boundary explicit."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    @contextlib.contextmanager
    def exclusive_access(self) -> Iterator[None]:
        """Compatibility lock used by the existing history purge service."""
        with self._lock:
            yield

    def close(self) -> None:
        """Close the sidecar connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SQLiteHistoryStore":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    # ── write API ──────────────────────────────────────────────────────────

    def create(
        self,
        ticker: str,
        trade_date: str,
        status: str = "running",
        analysis_id: str | None = None,
    ) -> HistoryEntry:
        entry = HistoryEntry(
            analysis_id=analysis_id or f"{ticker}_{trade_date}_{uuid.uuid4().hex[:8]}",
            ticker=ticker,
            trade_date=trade_date,
            status=status,
            created_at=time.time(),
        )
        with self._transaction():
            self._upsert_history(entry)
            self._delete_children(entry.analysis_id)
        return entry

    def update(self, entry: HistoryEntry) -> None:
        with self._transaction():
            self._upsert_history(entry)
            self._delete_children(entry.analysis_id)
            self._insert_children(entry)

    def mark_running(self, analysis_id: str) -> HistoryEntry | None:
        with self._transaction():
            row = self._history_row(analysis_id)
            if row is None:
                return None
            started_at = time.time()
            self._conn.execute(
                "UPDATE history SET status = 'running', started_at = ? "
                "WHERE analysis_id = ?",
                (started_at, analysis_id),
            )
            return self._read_entry_unlocked(analysis_id)

    def mark_stage_done(
        self,
        analysis_id: str,
        stage_id: str,
        report: str = "",
        report_key: str | None = None,
    ) -> None:
        with self._transaction():
            if self._history_row(analysis_id) is None:
                return

            existing = self._conn.execute(
                "SELECT 1 FROM completed_stages WHERE analysis_id = ? AND stage_id = ?",
                (analysis_id, stage_id),
            ).fetchone()
            if existing is None:
                sequence_row = self._conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                    "FROM completed_stages WHERE analysis_id = ?",
                    (analysis_id,),
                ).fetchone()
                self._conn.execute(
                    "INSERT INTO completed_stages "
                    "(analysis_id, stage_id, completed_at, sequence) VALUES (?, ?, ?, ?)",
                    (analysis_id, stage_id, time.time(), sequence_row["next_sequence"]),
                )

            if report:
                key = report_key or stage_id
                self._conn.execute(
                    "INSERT INTO stage_reports "
                    "(analysis_id, report_key, stage_id, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(analysis_id, report_key) DO UPDATE SET "
                    "stage_id = excluded.stage_id, content = excluded.content, "
                    "created_at = excluded.created_at",
                    (analysis_id, key, stage_id, report[:500], time.time()),
                )

    def mark_complete(
        self,
        analysis_id: str,
        signal: str,
        elapsed: float,
        completed_stages: list[str],
    ) -> None:
        with self._transaction():
            if self._history_row(analysis_id) is None:
                return
            self._conn.execute(
                "UPDATE history SET status = 'completed', signal = ?, elapsed = ?, "
                "finished_at = ? WHERE analysis_id = ?",
                (signal, elapsed, time.time(), analysis_id),
            )
            self._conn.execute(
                "DELETE FROM completed_stages WHERE analysis_id = ?", (analysis_id,)
            )
            for sequence, stage_id in enumerate(completed_stages, start=1):
                self._conn.execute(
                    "INSERT INTO completed_stages "
                    "(analysis_id, stage_id, completed_at, sequence) VALUES (?, ?, ?, ?)",
                    (analysis_id, stage_id, time.time(), sequence),
                )

    def mark_error(self, analysis_id: str, error: str, elapsed: float = 0.0) -> None:
        with self._transaction():
            if self._history_row(analysis_id) is None:
                return
            self._conn.execute(
                "UPDATE history SET status = 'error', error = ?, elapsed = ?, "
                "finished_at = ? WHERE analysis_id = ?",
                (error, elapsed, time.time(), analysis_id),
            )

    def set_results_path(self, analysis_id: str, path: str) -> None:
        with self._transaction():
            if self._history_row(analysis_id) is None:
                return
            self._conn.execute(
                "UPDATE history SET results_path = ? WHERE analysis_id = ?",
                (path, analysis_id),
            )

    def delete(self, analysis_id: str) -> None:
        with self._transaction():
            self._conn.execute(
                "DELETE FROM history WHERE analysis_id = ?", (analysis_id,)
            )

    # ── read API ───────────────────────────────────────────────────────────

    def get(self, analysis_id: str) -> HistoryEntry | None:
        with self._lock:
            return self._read_entry_unlocked(analysis_id)

    def list_all(
        self,
        ticker: str | None = None,
        signal: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[HistoryEntry], int]:
        conditions: list[str] = []
        params: list[object] = []
        if ticker:
            conditions.append("UPPER(ticker) LIKE ?")
            params.append(f"%{ticker.upper()}%")
        if signal:
            conditions.append("signal = ?")
            params.append(signal)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM history{where}", params
            ).fetchone()[0]
            rows = self._conn.execute(
                "SELECT analysis_id FROM history"
                f"{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return [
                self._read_entry_unlocked(row["analysis_id"])
                for row in rows
                if self._read_entry_unlocked(row["analysis_id"]) is not None
            ], total

    def find_by_ticker_date(self, ticker: str, trade_date: str) -> HistoryEntry | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT analysis_id FROM history WHERE ticker = ? AND trade_date = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (ticker, trade_date),
            ).fetchone()
            return self._read_entry_unlocked(row["analysis_id"]) if row else None

    # ── zombie compatibility ──────────────────────────────────────────────

    @staticmethod
    def is_zombie(entry: HistoryEntry, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        if entry.status != "running":
            return False
        if entry.elapsed == 0.0 and not entry.completed_stages:
            return (now - entry.created_at) > ZOMBIE_THRESHOLD_SEC
        if entry.elapsed > 0:
            return entry.elapsed > STUCK_THRESHOLD_SEC
        return False

    def cleanup_zombies(self, now: float | None = None) -> list[str]:
        if now is None:
            now = time.time()
        cleaned: list[str] = []
        entries, _ = self.list_all(limit=1000, offset=0)
        for entry in entries:
            if not self.is_zombie(entry, now=now):
                continue
            if entry.elapsed == 0.0 and not entry.completed_stages:
                reason = "分析被中断 (server restart, thread was SIGKILL'd)"
            else:
                reason = (
                    f"分析超时被清理 (elapsed={entry.elapsed:.1f}s > "
                    f"{STUCK_THRESHOLD_SEC:.0f}s, 可能卡在 "
                    f"{entry.completed_stages[-1] if entry.completed_stages else '未知'} 阶段)"
                )
            self.mark_error(entry.analysis_id, reason, entry.elapsed or 0.0)
            cleaned.append(entry.analysis_id)
        return cleaned

    # ── SQL mapping helpers ────────────────────────────────────────────────

    def _history_row(self, analysis_id: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM history WHERE analysis_id = ?", (analysis_id,)
        ).fetchone()

    def _upsert_history(self, entry: HistoryEntry) -> None:
        self._conn.execute(
            "INSERT INTO history "
            "(analysis_id, ticker, trade_date, signal, elapsed, status, error, "
            "results_path, started_at, finished_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(analysis_id) DO UPDATE SET "
            "ticker = excluded.ticker, trade_date = excluded.trade_date, "
            "signal = excluded.signal, elapsed = excluded.elapsed, "
            "status = excluded.status, error = excluded.error, "
            "results_path = excluded.results_path, started_at = excluded.started_at, "
            "finished_at = excluded.finished_at, created_at = excluded.created_at",
            (
                entry.analysis_id,
                entry.ticker,
                entry.trade_date,
                entry.signal,
                entry.elapsed,
                entry.status,
                entry.error,
                entry.results_path,
                entry.started_at,
                entry.finished_at,
                entry.created_at,
            ),
        )

    def _delete_children(self, analysis_id: str) -> None:
        self._conn.execute(
            "DELETE FROM stage_reports WHERE analysis_id = ?", (analysis_id,)
        )
        self._conn.execute(
            "DELETE FROM completed_stages WHERE analysis_id = ?", (analysis_id,)
        )

    def _insert_children(self, entry: HistoryEntry) -> None:
        now = time.time()
        for sequence, stage_id in enumerate(entry.completed_stages, start=1):
            self._conn.execute(
                "INSERT INTO completed_stages "
                "(analysis_id, stage_id, completed_at, sequence) VALUES (?, ?, ?, ?)",
                (entry.analysis_id, stage_id, now, sequence),
            )
        for report_key, content in entry.stage_reports.items():
            self._conn.execute(
                "INSERT INTO stage_reports "
                "(analysis_id, report_key, stage_id, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry.analysis_id, report_key, report_key, content, now),
            )

    def _read_entry_unlocked(self, analysis_id: str) -> HistoryEntry | None:
        row = self._history_row(analysis_id)
        if row is None:
            return None
        completed_rows = self._conn.execute(
            "SELECT stage_id FROM completed_stages "
            "WHERE analysis_id = ? ORDER BY sequence ASC",
            (analysis_id,),
        ).fetchall()
        report_rows = self._conn.execute(
            "SELECT report_key, content FROM stage_reports "
            "WHERE analysis_id = ? ORDER BY created_at ASC, report_key ASC",
            (analysis_id,),
        ).fetchall()
        return HistoryEntry(
            analysis_id=row["analysis_id"],
            ticker=row["ticker"],
            trade_date=row["trade_date"],
            signal=row["signal"] or "",
            elapsed=float(row["elapsed"] or 0.0),
            status=row["status"],
            error=row["error"],
            completed_stages=[r["stage_id"] for r in completed_rows],
            stage_reports={r["report_key"]: r["content"] for r in report_rows},
            created_at=float(row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            results_path=row["results_path"] or "",
        )


__all__ = ["SQLiteHistoryStore"]
