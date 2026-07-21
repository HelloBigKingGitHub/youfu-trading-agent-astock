"""Phase 4 read-cutover bootstrap helpers.

This module is installed by ``backend.main`` only when ``READ_FROM_SQLITE=1``
is set, mirroring the ``DUAL_WRITE_HISTORY=1`` and ``DUAL_WRITE_LOGS=1``
bootstraps introduced in Phase 3b and Phase 3c.  The bootstrap patches the
already-imported call-site bindings; no runtime source file is modified.

Behaviour matrix:

  * Reads (``list_all`` / ``list_tickers`` / ``get_meta`` / ``stream_chunks``
    / ``count_chunks``) — served by the SQLite sidecar.
  * Writes — go through whatever writer Phase 3b / 3c installed:
      - ``DUAL_WRITE_HISTORY=1``: write hits both JSON and SQLite, the
        consistent Phase 3b behaviour.
      - ``DUAL_WRITE_LOGS=1``: every chunk is appended independently to
        JSONL and SQLite, plus the Phase 3d §6.1 cross-process ``meta.lock``
        on the JSONL side.
      - Neither flag: writes fall back to plain JSON / JSONL exactly as
        the legacy runtime does.

The point of the Phase 4 cutover is to keep all current writers running and
let the read path land on the SQLite sidecar so the team can measure
behaviour without a write-traffic regression.  Once a one-week observation
window is complete the next phase may flip the writers too.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from backend.core.history_store_read_routing import DualReadHistoryStore
from backend.core.log_store_read_routing import DualReadLogStore, DualReadLogWriter
from backend.core.log_store_sqlite import SQLiteLogStore, SQLiteLogWriter

logger = logging.getLogger(__name__)


class ReadRoutingRuntime:
    """Own installed wrapper objects and undo patches on close."""

    def __init__(
        self,
        *,
        history_module,
        log_module,
        web_runner_module,
        original_history_singleton,
        original_log_singleton,
        original_web_writer,
        original_log_writer,
        history_dual_store,
        log_dual_store,
    ) -> None:
        self._history_module = history_module
        self._log_module = log_module
        self._web_runner_module = web_runner_module
        self._original_history_singleton = original_history_singleton
        self._original_log_singleton = original_log_singleton
        self._original_web_writer = original_web_writer
        self._original_log_writer = original_log_writer
        self._history_dual_store = history_dual_store
        self._log_dual_store = log_dual_store

    def close(self) -> None:
        """Undo bootstrap patches and close the sidecar connections."""
        self._history_module.HistoryStore._instance = self._original_history_singleton
        self._log_module._log_store_singleton = self._original_log_singleton
        self._log_module.LogWriter = self._original_log_writer
        if self._web_runner_module is not None:
            self._web_runner_module.LogWriter = self._original_web_writer
        self._history_dual_store.close()
        self._log_dual_store.close()


def enable_read_routing(db_path: Path | None = None) -> ReadRoutingRuntime:
    """Install the Phase 4 read cutover without changing runtime code.

    Idempotency guard: if either sidecar is already wired through one of
    these wrappers the bootstrap is rejected.  ``DUAL_WRITE_HISTORY=1`` /
    ``DUAL_WRITE_LOGS=1`` are expected to be set first (a typical user
    runs ``DUAL_WRITE_HISTORY=1 DUAL_WRITE_LOGS=1 READ_FROM_SQLITE=1`` to
    get a full SQLite read + dual-write validation environment).
    """
    from backend.core import history_store as history_module
    from backend.core import log_store as log_module
    from backend.core.history_store import get_history_store

    current_history = get_history_store()
    if isinstance(current_history, DualReadHistoryStore):
        raise RuntimeError("HistoryStore read routing is already enabled")

    current_log = log_module.get_log_store()
    if isinstance(current_log, DualReadLogStore):
        raise RuntimeError("LogStore read routing is already enabled")

    # Build a fresh SQLiteHistoryStore with the same db path the sidecar uses.
    from backend.core.history_store_sqlite import SQLiteHistoryStore

    sqlite_history = SQLiteHistoryStore(db_path)
    history_dual = DualReadHistoryStore(current_history, sqlite_history)
    history_module.HistoryStore._instance = history_dual

    sqlite_log = SQLiteLogStore(db_path)
    log_dual = DualReadLogStore(current_log, sqlite_log)
    log_module._log_store_singleton = log_dual

    # ── LogWriter factory ────────────────────────────────────────────────
    # ``web.runner`` imports ``LogWriter`` directly so we must patch that
    # binding explicitly to ensure every new chunk is appended to JSONL
    # *and* SQLite even after reads are routed to the sidecar.  This
    # matches the Phase 3c bootstrap pattern.
    web_runner_module = importlib.import_module("web.runner")
    original_web_writer = web_runner_module.LogWriter

    def dual_read_writer_factory(
        analysis_id: str, ticker: str, trade_date: str
    ):
        json_writer_type = original_web_writer or log_module.LogWriter
        json_writer = json_writer_type(analysis_id, ticker, trade_date)
        sqlite_writer = SQLiteLogWriter(
            analysis_id,
            ticker,
            trade_date,
            db_path=db_path,
        )
        # JSON writer chose the canonical ``task_dir_name``; mirror it so
        # downstream reads (now SQLite-routed) align row-by-row.
        sqlite_writer.task_dir_name = json_writer.task_dir_name
        return DualReadLogWriter(
            analysis_id,
            ticker,
            trade_date,
            json_writer,
            sqlite_writer,
        )

    log_module.LogWriter = dual_read_writer_factory
    if web_runner_module is not None:
        web_runner_module.LogWriter = dual_read_writer_factory

    logger.warning(
        "Read routing: SQLite reads + JSON/JSONL writes (Phase 4 cutover active)"
    )
    return ReadRoutingRuntime(
        history_module=history_module,
        log_module=log_module,
        web_runner_module=web_runner_module,
        original_history_singleton=current_history,
        original_log_singleton=current_log,
        original_web_writer=original_web_writer,
        original_log_writer=log_module.LogWriter,
        history_dual_store=history_dual,
        log_dual_store=log_dual,
    )


__all__ = ["ReadRoutingRuntime", "enable_read_routing"]
