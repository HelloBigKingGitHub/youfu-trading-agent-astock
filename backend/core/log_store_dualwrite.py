"""Dual-write compatibility wrappers for the Phase 3c log migration.

JSONL remains the read source of truth.  Each write is attempted against the
legacy writer and the SQLite sidecar independently; either side may fail
without aborting the analysis.

Phase 3d additionally grabs a cross-process fcntl.flock on the
``meta.json`` sibling when ``DUAL_WRITE_LOGS=1`` — fixes DDD_OPERATIONS §6.1
where two writers could race the read-modify-write of meta.json.  The
helper lives in :mod:`backend.core.log_store_lock_helper` so we never
modify :mod:`backend.core.log_store`.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path

from backend.core.log_store_lock_helper import (
    MetaJsonLockError,
    is_dual_write_active,
    meta_json_lock,
)

logger = logging.getLogger(__name__)


class DualWriteLogStore:
    """Expose the LogStore API while routing every read to JSONL."""

    def __init__(self, json_store, sqlite_store) -> None:
        self._json = json_store
        self._sqlite = sqlite_store

    def list_tickers(self):
        return self._json.list_tickers()

    def list_tasks(self, ticker: str):
        return self._json.list_tasks(ticker)

    def get_meta(self, ticker: str, task: str):
        return self._json.get_meta(ticker, task)

    def count_chunks(self, ticker: str, task: str):
        return self._json.count_chunks(ticker, task)

    def stream_chunks(self, ticker: str, task: str, type_filter: str | None = None):
        return self._json.stream_chunks(ticker, task, type_filter)

    def close(self) -> None:
        """Close only the sidecar connection; JSON LogStore has no close API."""
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


class DualWriteLogWriter:
    """Expose LogWriter's write API with independent JSON/SQLite attempts."""

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
        self.task_dir_name = getattr(json_writer, "task_dir_name", "")

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _meta_path_for(json_writer) -> Path | None:
        """Resolve the legacy ``meta.json`` path, if available."""
        if json_writer is None:
            return None
        getter = getattr(json_writer, "_meta_path", None)
        if getter is None:
            return None
        try:
            return Path(getter())
        except Exception:
            return None

    def _with_meta_lock(self, fn, *args, **kwargs):
        """Run ``fn`` while holding the meta.json fcntl lock (dual-write only).

        Phase 3d fix for DDD_OPERATIONS §6.1 — the legacy
        ``_write_meta_field`` is a non-atomic read-modify-write.  Under
        ``DUAL_WRITE_LOGS=1`` we serialize every call to ``update_stages``
        and ``finalize`` through a sibling ``meta.lock`` so two processes
        can't clobber each other's fields.
        """
        if not is_dual_write_active():
            return fn(*args, **kwargs)
        meta_path = self._meta_path_for(self._json)
        if meta_path is None:
            # No path resolved → fall back to the legacy writer's own
            # internal locking, which is what the JSON writer has always
            # done for append_chunk.
            return fn(*args, **kwargs)
        try:
            with meta_json_lock(meta_path, timeout_sec=5.0, blocking=True):
                return fn(*args, **kwargs)
        except MetaJsonLockError as exc:
            # Lock not acquired — log and continue.  The legacy writer is
            # already in use elsewhere; falling through here just means
            # the second writer's update may race.  That's no worse than
            # the pre-Phase 3d behaviour.
            logger.warning(
                "Phase 3d §6.1 meta.json lock unavailable for %s — proceeding unlocked: %s",
                meta_path, exc,
            )
            return fn(*args, **kwargs)

    # ── write API ────────────────────────────────────────────────────────

    def append_chunk(self, chunk) -> None:
        # append_chunk writes a JSONL append (already flock-protected inside
        # the legacy writer) plus a periodic meta update.  We only need to
        # gate the meta update path; the append itself is safe.
        try:
            self._json.append_chunk(chunk)
        except Exception as exc:
            logger.warning("JSON append_chunk failed: %s", exc)
        try:
            self._sqlite.append_chunk(chunk)
        except Exception as exc:
            logger.warning("SQLite append_chunk failed (non-fatal): %s", exc)

    def update_stages(self, stages: list[str]) -> None:
        def _do() -> None:
            self._json.update_stages(stages)
        with suppress(Exception):
            self._with_meta_lock(_do)
        try:
            self._sqlite.update_stages(stages)
        except Exception as exc:
            logger.warning("SQLite update_stages failed (non-fatal): %s", exc)

    def finalize(self, **kwargs) -> None:
        def _do() -> None:
            self._json.finalize(**kwargs)
        with suppress(Exception):
            self._with_meta_lock(_do)
        try:
            self._sqlite.finalize(**kwargs)
        except Exception as exc:
            logger.warning("SQLite finalize failed (non-fatal): %s", exc)

    def close(self) -> None:
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


__all__ = ["DualWriteLogStore", "DualWriteLogWriter"]
