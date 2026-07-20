"""Dual-write compatibility wrapper for the Phase 3b history migration.

Reads intentionally remain on the JSON store for the whole dual-write period.
SQLite failures are logged and swallowed so the legacy analysis path remains
available while the sidecar is observed.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator

from backend.core.history_store import HistoryEntry

logger = logging.getLogger(__name__)


class DualWriteHistoryStore:
    """Write JSON and SQLite, but keep JSON as the read source of truth."""

    def __init__(self, json_store, sqlite_store) -> None:
        self._json = json_store
        self._sqlite = sqlite_store

    # ── writes ──────────────────────────────────────────────────────────────

    def create(
        self,
        ticker: str,
        trade_date: str,
        status: str = "running",
        analysis_id: str | None = None,
    ) -> HistoryEntry:
        entry = self._json.create(ticker, trade_date, status, analysis_id)
        try:
            # Use the JSON-generated id and then copy the complete entry.  The
            # second step preserves created_at exactly, avoiding timestamp
            # drift between the two stores during reconciliation.
            self._sqlite.create(
                ticker,
                trade_date,
                status,
                analysis_id=entry.analysis_id,
            )
            self._sqlite.update(entry)
        except Exception as exc:  # pragma: no cover - exercised by fault tests
            logger.warning("SQLite dual-write failed (non-fatal): %s", exc)
        return entry

    def update(self, entry: HistoryEntry) -> None:
        self._json.update(entry)
        self._try_sqlite("update", lambda: self._sqlite.update(entry))

    def mark_running(self, analysis_id: str) -> HistoryEntry | None:
        entry = self._json.mark_running(analysis_id)
        if entry is not None:
            self._sync_json_entry(analysis_id, entry)
        return entry

    def mark_stage_done(
        self,
        analysis_id: str,
        stage_id: str,
        report: str = "",
        report_key: str | None = None,
    ) -> None:
        self._json.mark_stage_done(analysis_id, stage_id, report, report_key)
        self._sync_from_json(analysis_id)

    def mark_complete(
        self,
        analysis_id: str,
        signal: str,
        elapsed: float,
        completed_stages: list[str],
    ) -> None:
        self._json.mark_complete(analysis_id, signal, elapsed, completed_stages)
        self._sync_from_json(analysis_id)

    def mark_error(self, analysis_id: str, error: str, elapsed: float = 0.0) -> None:
        self._json.mark_error(analysis_id, error, elapsed)
        self._sync_from_json(analysis_id)

    def set_results_path(self, analysis_id: str, path: str) -> None:
        self._json.set_results_path(analysis_id, path)
        self._sync_from_json(analysis_id)

    def delete(self, analysis_id: str) -> None:
        self._json.delete(analysis_id)
        self._try_sqlite("delete", lambda: self._sqlite.delete(analysis_id))

    # ── reads: JSON only during Phase 3b ───────────────────────────────────

    def get(self, analysis_id: str) -> HistoryEntry | None:
        return self._json.get(analysis_id)

    def list_all(
        self,
        ticker: str | None = None,
        signal: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[HistoryEntry], int]:
        return self._json.list_all(ticker, signal, status, limit, offset)

    def find_by_ticker_date(self, ticker: str, trade_date: str) -> HistoryEntry | None:
        return self._json.find_by_ticker_date(ticker, trade_date)

    # Zombie detection uses the new implementation, as requested by Phase 3b.
    def is_zombie(self, entry: HistoryEntry, now: float | None = None) -> bool:
        return self._sqlite.is_zombie(entry, now)

    def cleanup_zombies(self, now: float | None = None) -> list[str]:
        cleaned_json = self._json.cleanup_zombies(now)
        cleaned_sqlite = self._sqlite.cleanup_zombies(now)

        # JSON cleanup and SQLite cleanup execute at different instants.  Copy
        # the canonical JSON result back after both sweeps so common entries
        # remain byte-for-byte equivalent, including finished_at.
        for analysis_id in cleaned_json:
            entry = self._json.get(analysis_id)
            if entry is not None:
                self._sync_json_entry(analysis_id, entry)
        return list(set(cleaned_json + cleaned_sqlite))

    @contextlib.contextmanager
    def exclusive_access(self) -> Iterator[None]:
        """Preserve the extra method used by the existing purge service."""
        with self._json.exclusive_access():
            with self._sqlite.exclusive_access():
                yield

    def close(self) -> None:
        self._sqlite.close()

    def _sync_from_json(self, analysis_id: str) -> None:
        entry = self._json.get(analysis_id)
        if entry is not None:
            self._sync_json_entry(analysis_id, entry)

    def _sync_json_entry(self, _analysis_id: str, entry: HistoryEntry) -> None:
        self._try_sqlite(
            "sync",
            lambda: self._sqlite.update(entry),
        )

    def _try_sqlite(self, operation: str, action) -> None:
        try:
            action()
        except Exception as exc:  # pragma: no cover - exercised by fault tests
            logger.warning(
                "SQLite dual-write failed (non-fatal) during %s: %s",
                operation,
                exc,
            )


__all__ = ["DualWriteHistoryStore"]
