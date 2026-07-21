"""Read-routing compatibility wrappers for the Phase 4 read cutover.

This is the Phase 4 counterpart to ``log_store_dualwrite_runtime``.  Where
the Phase 3c wrapper kept JSONL as the read source of truth, the Phase 4
wrapper flips the read direction to the SQLite sidecar.

Constraints:

  * Zero modifications to ``backend/core/log_store.py``.  The existing
    module-level ``_log_store_singleton`` is replaced at runtime.
  * Writes continue to use the Phase 3c dual-write path: each chunk is
    appended independently to the JSONL sidecar and the SQLite sidecar,
    with the ``meta.json`` cross-process flock patch from Phase 3d still
    in force.
  * Readers (``list_tickers`` / ``list_tasks`` / ``get_meta`` /
    ``count_chunks`` / ``stream_chunks``) go through the SQLite
    sidecar.  The legacy JSONL path is bypassed entirely.

The wrapper is installed by ``backend.core.read_routing.enable_read_routing``
when ``READ_FROM_SQLITE=1``; default runtime behaviour is unchanged.
"""

from __future__ import annotations

import logging
from typing import Iterator

from backend.core.log_store import LogChunk, TaskSummary
from backend.core.log_store_lock_helper import (
    MetaJsonLockError,
    is_dual_write_active,
    meta_json_lock,
)

logger = logging.getLogger(__name__)


class DualReadLogStore:
    """Route reads to the SQLite sidecar; JSONL writes are untouched.

    The constructor accepts the ``writer`` argument for symmetry with the
    history wrapper, even though ``LogStore`` itself is read-only at runtime;
    the underlying JSONL ``LogStore`` is left in place to honour any
    fall-through test path.  Reads always go through ``sqlite_store``.
    """

    def __init__(self, writer, sqlite_store) -> None:
        self._writer = writer
        self._sqlite = sqlite_store

    # ── reads: SQLite sidecar is the source of truth (Phase 4) ──────────

    def list_tickers(self) -> list[str]:
        return self._sqlite.list_tickers()

    def list_tasks(self, ticker: str) -> list[TaskSummary]:
        return self._sqlite.list_tasks(ticker)

    def get_meta(self, ticker: str, task_dir_name: str) -> dict:
        return self._sqlite.get_meta(ticker, task_dir_name)

    def count_chunks(self, ticker: str, task_dir_name: str) -> dict[str, int]:
        return self._sqlite.count_chunks(ticker, task_dir_name)

    def stream_chunks(
        self,
        ticker: str,
        task_dir_name: str,
        type_filter: str | None = None,
    ) -> Iterator[LogChunk]:
        return self._sqlite.stream_chunks(ticker, task_dir_name, type_filter)

    def close(self) -> None:
        """Close only the SQLite sidecar connection."""
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


class DualReadLogWriter:
    """Write API mirroring ``LogWriter`` while dual-writing JSONL+SQLite.

    The constructor accepts the explicit ``json_writer`` and ``sqlite_writer``
    rather than re-deriving them from module-level factories, because
    ``web.runner`` patches ``LogWriter`` directly and a runtime factory
    lookup could miss that.  ``backend.core.read_routing`` pre-instantiates
    both writers from the original factory captured at bootstrap.

    Phase 3d §6.1 cross-process flock semantics are inherited from
    ``DualWriteLogWriter``: ``update_stages`` and ``finalize`` hold a
    ``meta.lock`` file lock around the legacy ``_write_meta_field`` call
    when ``DUAL_WRITE_LOGS=1`` is set, regardless of whether reads are
    also routed to SQLite.
    """

    def __init__(
        self,
        analysis_id: str,
        ticker: str,
        trade_date: str,
        json_writer,
        sqlite_writer,
    ) -> None:
        self._json = json_writer
        self._sqlite = sqlite_writer
        self.analysis_id = analysis_id
        self.ticker = ticker
        self.trade_date = trade_date
        # The JSON writer picks the canonical task directory; preserve it.
        self.task_dir_name = getattr(json_writer, "task_dir_name", "")

    # ── helpers (lifted verbatim from DualWriteLogWriter) ────────────────

    @staticmethod
    def _meta_path_for(json_writer) -> "object | None":
        if json_writer is None:
            return None
        getter = getattr(json_writer, "_meta_path", None)
        if getter is None:
            return None
        try:
            from pathlib import Path
            return Path(getter())
        except Exception:
            return None

    def _with_meta_lock(self, fn, *args, **kwargs):
        """Run ``fn`` while holding the meta.json fcntl lock (dual-write only)."""
        if not is_dual_write_active():
            return fn(*args, **kwargs)
        meta_path = self._meta_path_for(self._json)
        if meta_path is None:
            return fn(*args, **kwargs)
        try:
            with meta_json_lock(meta_path, timeout_sec=5.0, blocking=True):
                return fn(*args, **kwargs)
        except MetaJsonLockError as exc:
            logger.warning(
                "Phase 3d §6.1 meta.json lock unavailable for %s — "
                "proceeding unlocked: %s",
                meta_path, exc,
            )
            return fn(*args, **kwargs)

    # ── write API (mirrors LogWriter; delegates to dual sidecar pair) ────

    def append_chunk(self, chunk: LogChunk) -> None:
        try:
            self._json.append_chunk(chunk)
        except Exception as exc:
            logger.warning("DualReadLogWriter: JSON append_chunk failed: %s", exc)
        try:
            self._sqlite.append_chunk(chunk)
        except Exception as exc:
            logger.warning(
                "DualReadLogWriter: SQLite append_chunk failed (non-fatal): %s",
                exc,
            )

    def update_stages(self, stages: list[str]) -> None:
        from contextlib import suppress

        def _do() -> None:
            self._json.update_stages(stages)
        with suppress(Exception):
            self._with_meta_lock(_do)
        try:
            self._sqlite.update_stages(stages)
        except Exception as exc:
            logger.warning(
                "DualReadLogWriter: SQLite update_stages failed (non-fatal): %s",
                exc,
            )

    def finalize(self, **kwargs) -> None:
        from contextlib import suppress

        def _do() -> None:
            self._json.finalize(**kwargs)
        with suppress(Exception):
            self._with_meta_lock(_do)
        try:
            self._sqlite.finalize(**kwargs)
        except Exception as exc:
            logger.warning(
                "DualReadLogWriter: SQLite finalize failed (non-fatal): %s",
                exc,
            )

    def close(self) -> None:
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


__all__ = ["DualReadLogStore", "DualReadLogWriter"]
