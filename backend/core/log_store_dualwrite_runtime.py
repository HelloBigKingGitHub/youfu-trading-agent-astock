"""Runtime bootstrap helpers for Phase 3c LogStore dual-write.

This module is intentionally separate from ``backend.core.log_store`` and all
existing callers.  ``backend.main`` imports it only when
``DUAL_WRITE_LOGS=1``.  The bootstrap patches the already-imported call-site
bindings and swaps the module-level read singleton for a JSON-routing wrapper;
default runtime behaviour is therefore unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.core.log_store_dualwrite import DualWriteLogStore, DualWriteLogWriter
from backend.core.log_store_sqlite import SQLiteLogStore, SQLiteLogWriter

logger = logging.getLogger(__name__)


class DualWriteLogRuntime:
    """Own installed wrapper objects and restore their original bindings."""

    def __init__(
        self,
        *,
        log_module,
        runner_module,
        web_runner_module,
        original_singleton,
        original_log_writer,
        original_web_writer,
        dual_store,
    ) -> None:
        self._log_module = log_module
        self._runner_module = runner_module
        self._web_runner_module = web_runner_module
        self._original_singleton = log_module._log_store_singleton
        self._original_log_writer = original_log_writer
        self._original_web_writer = original_web_writer
        self._dual_store = dual_store

    def close(self) -> None:
        """Undo bootstrap patches and close the store sidecar connection."""
        self._log_module._log_store_singleton = self._original_singleton
        self._log_module.LogWriter = self._original_log_writer
        if self._web_runner_module is not None:
            self._web_runner_module.LogWriter = self._original_web_writer
        self._dual_store.close()


def enable_log_dual_write(db_path: Path | None = None) -> DualWriteLogRuntime:
    """Install dual-write wrappers without modifying any existing caller.

    ``web.runner`` imports ``LogWriter`` directly at module import time, so
    assigning ``backend.core.log_store.LogWriter`` later would not affect that
    call site.  If it is already loaded, patch that binding explicitly.

    ``backend.core.runner`` currently performs its own pipeline and does not
    instantiate ``LogWriter``.  Its module object is still retained in this
    runtime handle so future factory bindings can be patched at the same
    bootstrap seam without touching protected runtime source.
    """
    import importlib

    from backend.core import log_store as log_module
    from backend.core import runner as runner_module

    current = log_module.get_log_store()
    if isinstance(current, DualWriteLogStore):
        raise RuntimeError("LogStore dual-write is already enabled")

    sqlite_store = SQLiteLogStore(db_path)
    dual_store = DualWriteLogStore(current, sqlite_store)

    # ``web.runner`` imports LogWriter directly.  Import it once at the
    # bootstrap seam so the existing binding can be replaced before any
    # analysis worker is created.  This changes no source file and is the same
    # effect as a lifespan-level factory patch.
    web_runner_module = importlib.import_module("web.runner")
    original_web_writer = web_runner_module.LogWriter

    def dual_writer_factory(analysis_id: str, ticker: str, trade_date: str):
        # Resolve the legacy class at call time.  This avoids importing
        # web.runner during startup merely to install the feature flag.
        json_writer_type = original_web_writer or log_module.LogWriter
        json_writer = json_writer_type(analysis_id, ticker, trade_date)
        sqlite_writer = SQLiteLogWriter(
            analysis_id,
            ticker,
            trade_date,
            db_path=db_path,
        )
        # JSON selected the canonical task directory.  Use it on the sidecar
        # too, even if older SQLite rows have a gap from a prior partial write.
        sqlite_writer.task_dir_name = json_writer.task_dir_name
        return DualWriteLogWriter(
            analysis_id,
            ticker,
            trade_date,
            json_writer,
            sqlite_writer,
        )

    log_module._log_store_singleton = dual_store
    if web_runner_module is not None:
        web_runner_module.LogWriter = dual_writer_factory

    logger.warning("LogStore dual-write enabled (jsonl + SQLite)")
    return DualWriteLogRuntime(
        log_module=log_module,
        runner_module=runner_module,
        web_runner_module=web_runner_module,
        original_singleton=current,
        original_web_writer=original_web_writer,
        original_log_writer=log_module.LogWriter,
        dual_store=dual_store,
    )


__all__ = ["DualWriteLogRuntime", "enable_log_dual_write"]
