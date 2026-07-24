"""P5b: LogStore + LogWriter wrapper that routes writes to SQLite-only.

跟 ``backend.core.history_store_singlewrite`` 同款旁路 wrapper, 但是
针对 LogStore / LogWriter (Phase 3c ``DualWriteLogStore`` /
``DualWriteLogWriter`` / Phase 4 ``DualReadLogStore`` / ``DualReadLogWriter``
的 SINGLE-WRITE 版本).

**核心不变量**:
- ``SingleWriteLogStore``: 读方法 (``list_tickers`` / ``list_tasks`` /
  ``get_meta`` / ``count_chunks`` / ``stream_chunks``) delegate 给
  ``sqlite_store``. ``json_store`` 完全不调 — Phase 5b 不切读路径,
  但 JSONL 已是 legacy 兼容, 读已经走 SQLite (Phase 4 切的).
- ``SingleWriteLogWriter``: 写方法 (``append_chunk`` / ``update_stages`` /
  ``finalize``) **只调** ``sqlite_writer``. 不再调 ``json_writer``,
  不再写 JSONL 文件, 不再维护 ``meta.json``.

**为何不 0 改 log_store.py / runner.py / web/runner.py**: 跟 Phase 3c/4
一样, 通过替换 ``log_store._log_store_singleton`` (read 单例) 和
``log_store.LogWriter`` (write factory) + ``web.runner.LogWriter``
(``web.runner`` 直接 import 的 binding), 所有调用方拿到的就是这个 wrapper.

注意 ``web.runner`` 在 import 时直接 ``from backend.core.log_store import
LogWriter``, 所以模块对象 binding 必须 patch (Phase 3c 已经发现这个坑).
Phase 5b 沿用相同做法 (跟 ``enable_read_routing`` 一致).
"""

from __future__ import annotations

import logging
from typing import Iterator

from backend.core.log_store import LogChunk, LogStore, TaskSummary
from backend.core.log_store_sqlite import SQLiteLogStore, SQLiteLogWriter

logger = logging.getLogger(__name__)


class SingleWriteLogStore:
    """Read-only API mirror that always pulls from SQLite.

    ``json_store`` is retained for symmetry but every method
    bypasses it.  In Phase 5b the JSONL sidecar is **legacy**: it may
    still contain historic rows (Phase 3a-3d wrote to it), but new
    analyses only land in SQLite.  The ``scripts/cleanup_old_jsonl.py``
    helper provides a one-time purge after the observation window.
    """

    def __init__(self, json_store: LogStore, sqlite_store: SQLiteLogStore) -> None:
        self._json = json_store  # kept for symmetry / debug
        self._sqlite = sqlite_store

    # ── reads: SQLite is the source of truth (Phase 4 preserved) ───────

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
        """Close only the SQLite sidecar; JSON store has no close API."""
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


class SingleWriteLogWriter:
    """SQLite-only writer with the same public API as ``LogWriter``.

    The constructor accepts ``json_writer`` for symmetry with the
    Phase 3c/4 wrappers but never invokes it.  ``task_dir_name`` is
    sourced from the SQLite writer (``SQLiteLogWriter._next_task_dir_name``
    picks the canonical runNN the same way the JSON writer would have).

    Phase 3d §6.1 cross-process ``meta.lock`` semantics are dropped —
    with single-write we don't touch the legacy ``meta.json`` file at
    all, so there is nothing to flock.  SQLite handles its own
    cross-process serialization through ``BEGIN IMMEDIATE``.
    """

    def __init__(
        self,
        analysis_id: str,
        ticker: str,
        trade_date: str,
        json_writer,
        sqlite_writer: SQLiteLogWriter,
    ) -> None:
        self._json = json_writer  # never invoked; kept for symmetry
        self._sqlite = sqlite_writer
        self.analysis_id = analysis_id
        self.ticker = ticker
        self.trade_date = trade_date
        # SQLite writer picks the canonical task directory; mirror it so
        # downstream reads (now SQLite-routed) align row-by-row with any
        # legacy JSONL directory naming that callers depend on.
        self.task_dir_name = sqlite_writer.task_dir_name

    # ── writes: SQLite only (Phase 5b cutover) ──────────────────────────

    def append_chunk(self, chunk: LogChunk) -> None:
        self._sqlite.append_chunk(chunk)

    def update_stages(self, completed_stages: list[str]) -> None:
        self._sqlite.update_stages(completed_stages)

    def finalize(self, **kwargs) -> None:
        self._sqlite.finalize(**kwargs)

    def close(self) -> None:
        close = getattr(self._sqlite, "close", None)
        if close is not None:
            close()


__all__ = ["SingleWriteLogStore", "SingleWriteLogWriter"]