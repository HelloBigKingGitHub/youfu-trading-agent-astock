"""Dual-write compatibility wrappers for the Phase 3c log migration.

JSONL remains the read source of truth.  Each write is attempted against the
legacy writer and the SQLite sidecar independently; either side may fail
without aborting the analysis.
"""

from __future__ import annotations

import logging

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

    def append_chunk(self, chunk) -> None:
        try:
            self._json.append_chunk(chunk)
        except Exception as exc:
            logger.warning("JSON append_chunk failed: %s", exc)
        try:
            self._sqlite.append_chunk(chunk)
        except Exception as exc:
            logger.warning("SQLite append_chunk failed (non-fatal): %s", exc)

    def update_stages(self, stages: list[str]) -> None:
        try:
            self._json.update_stages(stages)
        except Exception as exc:
            logger.warning("JSON update_stages failed: %s", exc)
        try:
            self._sqlite.update_stages(stages)
        except Exception as exc:
            logger.warning("SQLite update_stages failed (non-fatal): %s", exc)

    def finalize(self, **kwargs) -> None:
        try:
            self._json.finalize(**kwargs)
        except Exception as exc:
            logger.warning("JSON finalize failed: %s", exc)
        try:
            self._sqlite.finalize(**kwargs)
        except Exception as exc:
            logger.warning("SQLite finalize failed (non-fatal): %s", exc)

    def close(self) -> None:
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


__all__ = ["DualWriteLogStore", "DualWriteLogWriter"]
