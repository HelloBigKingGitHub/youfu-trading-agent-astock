"""Phase 5b: 切写路径到 SQLite (单写, jsonl 仅 observe).

1 周观察期后 (Phase 3a-4 dual-write + READ_FROM_SQLITE=1), Phase 5b
**切写**: 把 HistoryStore / LogStore / LogWriter 写方法改为只写 SQLite,
JSON/JSONL 写操作变 no-op (但 JSON/JSONL 仍可读做 fallback / troubleshoot).

**关键不变量**:
- ``SINGLE_WRITE_SQLITE=1`` 默认 OFF. 用户**显式** opt-in (跟 Phase 3b/3c/4
  同款环境变量).
- 0 改 ``history_store.py`` / ``log_store.py`` / ``runner.py`` /
  ``web/runner.py``. 通过 ``HistoryStore._instance`` patch +
  ``web/runner.LogWriter`` factory patch + ``log_store._log_store_singleton``
  patch (跟 Phase 3b/3c/4 同款 bootstrap seam).
- 读路径不动: Phase 4 ``READ_FROM_SQLITE=1`` 仍生效 (SingleWrite wrapper
  的 read 方法直接 delegate 给 SQLite store, 跟 Phase 4 DualRead 一致).
- 清 JSON/JSONL 不是 Phase 5b 范围 — 那是 Phase 5c (观察期+清理).
  ``scripts/cleanup_old_jsonl.py`` 提供 dry-run / --force 工具, 不强删.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

SINGLE_WRITE_SQLITE_ENV = "SINGLE_WRITE_SQLITE"
DEFAULT_SINGLE_WRITE = False


def is_single_write_sqlite() -> bool:
    """User opt-in to single-write to SQLite (skip JSON/JSONL writes).

    Returns True only when ``SINGLE_WRITE_SQLITE=1`` is set in the
    environment.  Defaults to False — the user has to explicitly opt in
    because flipping this on stops JSON/JSONL from receiving new writes,
    which is a deliberate trade-off (less disk IO, no drift risk) the
    team only wants after the 1-week observation period completes.
    """
    return os.environ.get(SINGLE_WRITE_SQLITE_ENV, "0") == "1"


def read_with_fallback(sidecar_path: str, sqlite_row: dict | None) -> dict | None:
    """If single-write and sidecar read fails, fall back to SQLite.

    Phase 5b doesn't actually use this — reads still come through the
    Phase 4 DualRead path which is already SQLite-first.  But we keep
    the helper for ``scripts/cleanup_old_jsonl.py`` and any future
    troubleshoot path that needs to gracefully degrade when a JSON
    sidecar is gone.

    Priority:
      1. SQLite row (always preferred — it's the new source of truth).
      2. JSON sidecar at ``sidecar_path`` — used during the dual-write
         window so legacy reads still work, and as a one-time rescue
         during the cleanup transition.
    """
    if sqlite_row is not None:
        return sqlite_row
    try:
        with open(sidecar_path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


__all__ = [
    "SINGLE_WRITE_SQLITE_ENV",
    "DEFAULT_SINGLE_WRITE",
    "is_single_write_sqlite",
    "read_with_fallback",
]