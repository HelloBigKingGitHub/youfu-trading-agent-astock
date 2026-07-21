"""Read-routing compatibility wrapper for the Phase 4 read cutover.

This is the Phase 4 counterpart to ``history_store_dualwrite``.  Where the
Phase 3b wrapper kept JSON as the read source of truth (writes hit both JSON
and SQLite) the Phase 4 wrapper flips the read direction: every read goes to
SQLite, while writes keep using whatever writer Phase 3b installed (a
``DualWriteHistoryStore`` when ``DUAL_WRITE_HISTORY=1`` or the raw JSON
``HistoryStore`` when dual-write is off).

The wrapper is installed through ``enable_read_routing`` at FastAPI
startup.  No existing caller of ``HistoryStore`` is modified.

This file MUST NOT modify ``backend/core/history_store.py``.  The
``HistoryStore._instance`` class attribute is patched at runtime to point at
this wrapper so ``get_history_store()`` returns a SQLite-read shim without
any source change.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator

from backend.core.history_store import HistoryEntry

logger = logging.getLogger(__name__)


class DualReadHistoryStore:
    """Route reads to SQLite; writes to whatever writer was passed in.

    The ``writer`` parameter is either the raw ``HistoryStore`` (default
    configuration) or a ``DualWriteHistoryStore`` (when ``DUAL_WRITE_HISTORY=1``
    is also set).  Either way write operations land on the JSON file *and* the
    SQLite sidecar.  Reads, however, come exclusively from the SQLite
    sidecar.  This keeps the Phase 3b invariants intact while giving the UI a
    measurement of how reads behave under ``READ_FROM_SQLITE=1``.
    """

    def __init__(self, writer, sqlite_store) -> None:
        self._writer = writer
        self._sqlite = sqlite_store

    # ── writes: defer to the underlying writer (JSON+SQLite dual-write in
    #    the Phase 3b case, raw JSON in the default case) ────────────────

    def create(
        self,
        ticker: str,
        trade_date: str,
        status: str = "running",
        analysis_id: str | None = None,
    ) -> HistoryEntry:
        return self._writer.create(ticker, trade_date, status, analysis_id)

    def update(self, entry: HistoryEntry) -> None:
        self._writer.update(entry)

    def mark_running(self, analysis_id: str) -> HistoryEntry | None:
        return self._writer.mark_running(analysis_id)

    def mark_stage_done(
        self,
        analysis_id: str,
        stage_id: str,
        report: str = "",
        report_key: str | None = None,
    ) -> None:
        self._writer.mark_stage_done(analysis_id, stage_id, report, report_key)

    def mark_complete(
        self,
        analysis_id: str,
        signal: str,
        elapsed: float,
        completed_stages: list[str],
    ) -> None:
        self._writer.mark_complete(
            analysis_id, signal, elapsed, completed_stages
        )

    def mark_error(self, analysis_id: str, error: str, elapsed: float = 0.0) -> None:
        self._writer.mark_error(analysis_id, error, elapsed)

    def set_results_path(self, analysis_id: str, path: str) -> None:
        self._writer.set_results_path(analysis_id, path)

    def delete(self, analysis_id: str) -> None:
        self._writer.delete(analysis_id)

    # ── reads: SQLite sidecar is the source of truth (Phase 4) ──────────

    def get(self, analysis_id: str) -> HistoryEntry | None:
        return self._sqlite.get(analysis_id)

    def list_all(
        self,
        ticker: str | None = None,
        signal: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[HistoryEntry], int]:
        return self._sqlite.list_all(ticker, signal, status, limit, offset)

    def find_by_ticker_date(self, ticker: str, trade_date: str) -> HistoryEntry | None:
        return self._sqlite.find_by_ticker_date(ticker, trade_date)

    # ── zombie compatibility: SQLite implementation as in Phase 3b ──────

    @staticmethod
    def is_zombie(entry: HistoryEntry, now: float | None = None) -> bool:
        # Delegate to the same static method that Phase 3b picked: the SQLite
        # implementation is identical to the JSON implementation, but inlining
        # the JSON logic would couple us to its private constants.
        from backend.core.history_store_sqlite import SQLiteHistoryStore

        return SQLiteHistoryStore.is_zombie(entry, now)

    def cleanup_zombies(self, now: float | None = None) -> list[str]:
        # Clean both the SQLite sidecar (which we now read from) and the
        # underlying writer (which Phase 3b keeps as its own source of truth).
        # Returning the union avoids dropping an analysis_id cleared on one
        # sidecar but not the other.
        cleaned_sqlite = self._sqlite.cleanup_zombies(now)

        cleanup = getattr(self._writer, "cleanup_zombies", None)
        if cleanup is None:
            return list(cleaned_sqlite)
        try:
            cleaned_writer = cleanup(now)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "DualReadHistoryStore: writer cleanup_zombies failed: %s", exc
            )
            return list(cleaned_sqlite)
        return list({*cleaned_sqlite, *cleaned_writer})

    # ── lock compatibility: pass through to the underlying writer. ───────
    # The purge service uses ``exclusive_access`` to lock both ``list_all``
    # and write paths.  When ``READ_FROM_SQLITE=1`` is enabled the SQLite
    # sidecar takes the read traffic but the writer still holds its own
    # write lock, so we must hold both to keep the contract observable.
    # We delegate to the writer's lock first (it owns JSON writes), then
    # the SQLite lock (it owns the sidecar).

    @contextlib.contextmanager
    def exclusive_access(self) -> Iterator[None]:
        writer_lock = getattr(self._writer, "exclusive_access", None)
        sqlite_lock = getattr(self._sqlite, "exclusive_access", None)
        if writer_lock is None and sqlite_lock is None:
            yield
            return
        if writer_lock is None:
            with sqlite_lock():
                yield
            return
        if sqlite_lock is None:
            with writer_lock():
                yield
            return
        with writer_lock():
            with sqlite_lock():
                yield

    def close(self) -> None:
        """Close only the sidecar; writer is owned by the singleton."""
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


__all__ = ["DualReadHistoryStore"]
