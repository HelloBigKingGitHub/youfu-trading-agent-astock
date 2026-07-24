"""P5b: HistoryStore wrapper that routes writes to SQLite-only.

跟 Phase 3b ``DualWriteHistoryStore`` / Phase 4 ``DualReadHistoryStore``
同款旁路 wrapper, 但是 SINGLE-WRITE 版本 (不写 JSON).

**核心不变量**:
- 写方法 (``create`` / ``update`` / ``mark_running`` / ``mark_stage_done`` /
  ``mark_complete`` / ``mark_error`` / ``set_results_path`` / ``delete``)
  只调 ``sqlite_store`` — 不再调 ``json_store``.
- 读方法 (``get`` / ``list_all`` / ``find_by_ticker_date``) delegate 给
  ``sqlite_store`` — 跟 Phase 4 DualRead 一致 (Phase 5b 不切读路径).
- ``cleanup_zombies`` 仍 delegate 给 ``sqlite_store`` (Phase 3b/4 同款
  行为).
- ``exclusive_access`` 穿透到 ``sqlite_store`` (purge service 仍要拿锁).

**为何不 0 改 history_store.py**: 跟 Phase 3b/4 一样, 我们用
``HistoryStore._instance`` 替换成这个 wrapper, 所有 ``get_history_store()``
调用方拿到的就是这个 wrapper, 不需要改 ``runner.py`` / ``web/runner.py``
任何 runtime code.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator

from backend.core.history_store import HistoryEntry, HistoryStore
from backend.core.history_store_sqlite import SQLiteHistoryStore

logger = logging.getLogger(__name__)


class SingleWriteHistoryStore:
    """Write-only-to-SQLite wrapper.  Reads still come from SQLite.

    Constructed at FastAPI lifespan with::

        SingleWriteHistoryStore(json_store, sqlite_store)

    where ``json_store`` is the legacy JSON ``HistoryStore`` (kept only
    as a reference for fall-through tests) and ``sqlite_store`` is the
    SQLite sidecar.  Every write operation calls ``sqlite_store`` and
    never ``json_store`` — Phase 5b drops the dual-write invariant from
    Phase 3b and stops creating JSON history files.  Old JSON files
    remain on disk for the observation window (and the
    ``scripts/cleanup_old_jsonl.py`` tool can purge them in Phase 5c).
    """

    def __init__(self, json_store: HistoryStore, sqlite_store: SQLiteHistoryStore) -> None:
        self._json = json_store  # kept for symmetry / debug, never written
        self._sqlite = sqlite_store

    # ── writes: SQLite only (Phase 5b cutover) ──────────────────────────

    def create(
        self,
        ticker: str,
        trade_date: str,
        status: str = "running",
        analysis_id: str | None = None,
    ) -> HistoryEntry:
        return self._sqlite.create(ticker, trade_date, status, analysis_id)

    def update(self, entry: HistoryEntry) -> None:
        self._sqlite.update(entry)

    def mark_running(self, analysis_id: str) -> HistoryEntry | None:
        return self._sqlite.mark_running(analysis_id)

    def mark_stage_done(
        self,
        analysis_id: str,
        stage_id: str,
        report: str = "",
        report_key: str | None = None,
    ) -> None:
        self._sqlite.mark_stage_done(analysis_id, stage_id, report, report_key)

    def mark_complete(
        self,
        analysis_id: str,
        signal: str,
        elapsed: float,
        completed_stages: list[str],
    ) -> None:
        self._sqlite.mark_complete(analysis_id, signal, elapsed, completed_stages)

    def mark_error(self, analysis_id: str, error: str, elapsed: float = 0.0) -> None:
        self._sqlite.mark_error(analysis_id, error, elapsed)

    def set_results_path(self, analysis_id: str, path: str) -> None:
        self._sqlite.set_results_path(analysis_id, path)

    def delete(self, analysis_id: str) -> None:
        self._sqlite.delete(analysis_id)

    # ── reads: SQLite is the source of truth (Phase 4 preserved) ───────

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

    # ── zombie compatibility ────────────────────────────────────────────

    @staticmethod
    def is_zombie(entry: HistoryEntry, now: float | None = None) -> bool:
        # Delegate to the SQLite implementation (identical math to JSON).
        return SQLiteHistoryStore.is_zombie(entry, now)

    def cleanup_zombies(self, now: float | None = None) -> list[str]:
        """Mark zombies as error via SQLite only — no JSON writes."""
        return self._sqlite.cleanup_zombies(now)

    # ── lock compatibility ──────────────────────────────────────────────

    @contextlib.contextmanager
    def exclusive_access(self) -> Iterator[None]:
        """Delegate to ``sqlite_store`` only — JSON sidecar is read-only
        during Phase 5b so its lock is unused."""
        sqlite_lock = getattr(self._sqlite, "exclusive_access", None)
        if sqlite_lock is None:
            yield
            return
        with sqlite_lock():
            yield

    def close(self) -> None:
        """Close only the SQLite sidecar; JSON store is owned by the
        legacy singleton."""
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


__all__ = ["SingleWriteHistoryStore"]