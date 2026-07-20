"""Auto-cleanup for the tradingagents SQLite DB + history JSON + log JSONL.

Phase 3d — TTL policy (configurable via env vars, see ``env_config`` below):

| Table         | TTL      | Condition                                                    |
|---------------|----------|--------------------------------------------------------------|
| history       | 30 days  | status IN ('completed','error') AND finished_at < cutoff     |
| log_chunks    | 7 days   | ts < cutoff                                                  |

After the SQL deletes pass, the corresponding on-disk artifacts that are
NOT referenced by any surviving row are also deleted to keep the legacy
JSONL/JSON layout from growing unbounded:

* ``~/.tradingagents/logs/history/{analysis_id}.json`` — history metadata
* ``~/.tradingagents/logs/{ticker}/{date}_runNN/``    — task directory
  containing ``meta.json`` + ``*.jsonl`` (and ``full_states_log_*.json``
  legacy artifacts preserved by results_path)

The class is **idempotent** — calling it twice in a row yields ``deleted = 0``
on the second call.  All deletes are transactional.  ``dry_run=True``
computes the same diff without touching the filesystem or DB.

Hard constraints:

* Never modifies ``backend/core/log_store.py`` /
  ``backend/core/history_store.py`` / ``backend/core/runner.py``.
* Treats ``logs_BACKUP_*`` sibling directories as untouchable (same
  convention as :mod:`backend.core.history_cleanup`).
* Does not delete ``portfolio/`` / ``schedules/`` / ``cache/`` / ``memory/``.
* Does not change the schema — uses only queries from 001_initial.sql and
  any indexes added by 002_index_optimization.sql.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from backend.storage.schema_migrations.migrate import _apply_pragmas

logger = logging.getLogger(__name__)


# ── defaults (overridable per-instance / per-env) ────────────────────────────

_DEFAULT_DB = Path.home() / ".tradingagents" / "tradingagents.db"
_DEFAULT_HISTORY_DIR = Path.home() / ".tradingagents" / "logs" / "history"
_DEFAULT_LOGS_ROOT = Path.home() / ".tradingagents" / "logs"

# Source-of-truth TTLs come from docs/SQLITE_MIGRATION_PLAN.md §5.1
# Phase 3d introduces env-var override for ops who want a different window.
DEFAULT_HISTORY_TTL_DAYS = 30
DEFAULT_LOG_TTL_DAYS = 7


def _env_int(name: str, default: int) -> int:
    """Read an int from env, falling back to ``default`` on absent / invalid.

    Negative values are clamped to 0 (no historical rows survive) — useful
    for tests that want to wipe everything.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an int, falling back to %d", name, raw, default)
        return default
    return max(0, v)


# ── stats dataclass ──────────────────────────────────────────────────────────


@dataclass
class CleanupStats:
    """Counters produced by a single cleanup pass.

    Returned by every public method on :class:`SQLiteCleaner` so callers can
    log ``cleanup_x_deleted: N, bytes_freed: M`` exactly as the lifespan
    bridge expects.
    """

    history_deleted: int = 0
    log_chunks_deleted: int = 0
    json_files_deleted: int = 0
    jsonl_files_deleted: int = 0
    task_dirs_deleted: int = 0
    bytes_freed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "history_deleted": self.history_deleted,
            "log_chunks_deleted": self.log_chunks_deleted,
            "json_files_deleted": self.json_files_deleted,
            "jsonl_files_deleted": self.jsonl_files_deleted,
            "task_dirs_deleted": self.task_dirs_deleted,
            "bytes_freed": self.bytes_freed,
        }

    def is_no_op(self) -> bool:
        return (
            self.history_deleted == 0
            and self.log_chunks_deleted == 0
            and self.json_files_deleted == 0
            and self.jsonl_files_deleted == 0
            and self.task_dirs_deleted == 0
        )


# ── core cleaner ────────────────────────────────────────────────────────────


class SQLiteCleaner:
    """Idempotent TTL cleanup for the tradingagents SQLite DB + legacy paths.

    Parameters
    ----------
    db_path:
        SQLite database to clean. Defaults to
        ``~/.tradingagents/tradingagents.db``.
    history_dir:
        Directory holding ``*.json`` history metadata files (legacy
        history.json-style store). Defaults to
        ``~/.tradingagents/logs/history``.
    logs_root:
        Directory holding ``{ticker}/{date}_runNN/`` task directories
        (legacy JSONL logs). Defaults to ``~/.tradingagents/logs``.
    history_ttl_days:
        Age in days after which *terminal* history rows (completed / error)
        become eligible for deletion. Default 30.
    log_ttl_days:
        Age in days after which log_chunks rows + their jsonl files
        become eligible. Default 7.
    backup_dirname:
        Name of the sibling of ``logs_root`` we MUST NOT delete when
        pruning task directories. Defaults to ``logs_BACKUP_*`` (any
        variant, matched by prefix).
    """

    def __init__(
        self,
        *,
        db_path: Path | None = None,
        history_dir: Path | None = None,
        logs_root: Path | None = None,
        history_ttl_days: int = DEFAULT_HISTORY_TTL_DAYS,
        log_ttl_days: int = DEFAULT_LOG_TTL_DAYS,
        backup_dirname_prefix: str = "logs_BACKUP_",
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else _DEFAULT_DB
        self.history_dir = Path(history_dir) if history_dir is not None else _DEFAULT_HISTORY_DIR
        self.logs_root = Path(logs_root) if logs_root is not None else _DEFAULT_LOGS_ROOT
        self.history_ttl_days = max(0, int(history_ttl_days))
        self.log_ttl_days = max(0, int(log_ttl_days))
        self.backup_dirname_prefix = backup_dirname_prefix

        # Lazy connection — only opened when a method that needs it runs.
        self._conn: sqlite3.Connection | None = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if not self.db_path.exists():
            # Empty DB -> nothing to clean. Caller treats this as no-op.
            self._conn = _open_noop_conn()
            return self._conn
        conn = sqlite3.connect(str(self.db_path))
        _apply_pragmas(conn)
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None

    def __enter__(self) -> "SQLiteCleaner":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ── helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _now_epoch() -> float:
        return time.time()

    def _history_cutoff(self) -> float:
        return self._now_epoch() - self.history_ttl_days * 86400

    def _log_cutoff(self) -> float:
        return self._now_epoch() - self.log_ttl_days * 86400

    def _safe_rmtree(self, path: Path, stats: CleanupStats) -> None:
        """Remove ``path`` recursively and add freed bytes to stats."""
        if not path.exists():
            return
        try:
            size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        except OSError:
            size = 0
        try:
            import shutil

            shutil.rmtree(path)
            stats.task_dirs_deleted += 1
            stats.bytes_freed += size
        except OSError as exc:
            logger.warning("failed to remove %s: %s", path, exc)

    def _safe_unlink(self, path: Path, stats: CleanupStats, *, kind: str) -> None:
        """Unlink a single file; record on stats. ``kind`` is 'json' or 'jsonl'."""
        if not path.is_file():
            return
        try:
            size = path.stat().st_size
            path.unlink()
            stats.bytes_freed += size
            if kind == "json":
                stats.json_files_deleted += 1
            elif kind == "jsonl":
                stats.jsonl_files_deleted += 1
        except OSError as exc:
            logger.warning("failed to unlink %s: %s", path, exc)

    # ── core cleanup passes ───────────────────────────────────────────────

    def cleanup_history(self, dry_run: bool = False) -> CleanupStats:
        """Delete terminal history rows + matching JSON metadata files.

        Policy:
          * DELETE FROM history WHERE status IN ('completed','error')
            AND finished_at < cutoff
          * DELETE history/*.json whose analysis_id is in the deleted set
            (or whose ``finished_at`` field is older than cutoff)
        """
        stats = CleanupStats()
        cutoff = self._history_cutoff()

        # Skip silently if DB doesn't exist yet — Phase 3a has no DB on
        # first install; nothing to clean.
        if not self.db_path.exists():
            return stats

        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT analysis_id FROM history "
                "WHERE status IN ('completed','error') AND finished_at IS NOT NULL "
                "AND finished_at < ?",
                (cutoff,),
            )
            deleted_ids = {row[0] for row in cur.fetchall()}
            stats.history_deleted = len(deleted_ids)

            if not dry_run and deleted_ids:
                with conn:  # transaction
                    conn.execute(
                        "DELETE FROM history "
                        "WHERE status IN ('completed','error') "
                        "AND finished_at IS NOT NULL "
                        "AND finished_at < ?",
                        (cutoff,),
                    )
                # Cleanup cascading rows explicitly (FK is ON DELETE CASCADE
                # in schema.sql, but we are defensive in case a DB lacks the
                # pragma for the connection that ran the DELETE, or the
                # tables simply don't exist — e.g. the synthetic in-memory
                # slice used by verify_migration._cleanup_timing).
                for table in ("stage_reports", "completed_stages"):
                    cur = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    )
                    if cur.fetchone() is None:
                        continue
                    conn.execute(
                        f"DELETE FROM {table} WHERE analysis_id NOT IN "
                        "(SELECT analysis_id FROM history)"
                    )
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("cleanup_history: SQL failed: %s", exc)
            return stats

        # Legacy history/*.json files — delete if older than cutoff OR if
        # the analysis_id matches one we just deleted from SQLite.
        if self.history_dir.is_dir():
            for json_path in self.history_dir.glob("*.json"):
                if not deleted_ids or json_path.stem in deleted_ids:
                    # When deleted_ids is empty (dry-run with no SQL
                    # deletes yet), still scan by mtime-based heuristic so
                    # the report is informative.
                    if not deleted_ids:
                        try:
                            payload = json.loads(json_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            continue
                        ts = payload.get("finished_at") or payload.get("started_at")
                        if not isinstance(ts, (int, float)) or ts >= cutoff:
                            continue
                    if not dry_run:
                        self._safe_unlink(json_path, stats, kind="json")

        return stats

    def cleanup_log_chunks(self, dry_run: bool = False) -> CleanupStats:
        """Delete log_chunks rows + matching JSONL files / task directories.

        Policy:
          * DELETE FROM log_chunks WHERE ts < cutoff
          * For every task directory whose meta.json finished_at < cutoff:
            remove the entire directory (meta.json + *.jsonl +
            full_states_log_*.json).
        """
        stats = CleanupStats()
        cutoff = self._log_cutoff()

        if not self.db_path.exists():
            return stats

        conn = self._connect()
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM log_chunks WHERE ts < ?",
                (cutoff,),
            )
            stats.log_chunks_deleted = int(cur.fetchone()[0])
            if not dry_run and stats.log_chunks_deleted:
                with conn:
                    conn.execute(
                        "DELETE FROM log_chunks WHERE ts < ?",
                        (cutoff,),
                    )
                conn.commit()
        except sqlite3.Error as exc:
            logger.warning("cleanup_log_chunks: SQL failed: %s", exc)
            return stats

        # On-disk task directories.
        if self.logs_root.is_dir():
            for ticker_dir in self.logs_root.iterdir():
                if not ticker_dir.is_dir():
                    continue
                # Never touch the legacy history/ dir or any backup root.
                if ticker_dir.name == "history":
                    continue
                if ticker_dir.name.startswith(self.backup_dirname_prefix):
                    continue
                if ticker_dir.name.startswith("."):
                    continue
                for task_dir in sorted(ticker_dir.iterdir()):
                    if not task_dir.is_dir() or "_run" not in task_dir.name:
                        continue
                    meta_path = task_dir / "meta.json"
                    task_finished_at: float | None = None
                    if meta_path.is_file():
                        try:
                            payload = json.loads(meta_path.read_text(encoding="utf-8"))
                        except (OSError, json.JSONDecodeError):
                            payload = None
                        ts = None
                        if isinstance(payload, dict):
                            ts = payload.get("finished_at") or payload.get("started_at")
                        if isinstance(ts, (int, float)):
                            task_finished_at = float(ts)

                    # If meta.json says the task is older than the cutoff,
                    # we can safely wipe the directory (no surviving chunks).
                    eligible = (
                        task_finished_at is not None and task_finished_at < cutoff
                    )
                    # Fallback: no meta.json at all → use directory mtime.
                    if task_finished_at is None:
                        try:
                            eligible = task_dir.stat().st_mtime < cutoff
                        except OSError:
                            eligible = False

                    if not eligible:
                        continue

                    if dry_run:
                        # Count files that *would* be freed without removing.
                        try:
                            for p in task_dir.rglob("*"):
                                if p.is_file():
                                    if p.suffix == ".jsonl":
                                        stats.jsonl_files_deleted += 1
                                    elif p.suffix == ".json":
                                        stats.json_files_deleted += 1
                                    stats.bytes_freed += p.stat().st_size
                            stats.task_dirs_deleted += 1
                        except OSError:
                            pass
                    else:
                        # Record individual file counts then rmtree.
                        for p in task_dir.rglob("*"):
                            if p.is_file():
                                if p.suffix == ".jsonl":
                                    stats.jsonl_files_deleted += 1
                                elif p.suffix == ".json":
                                    stats.json_files_deleted += 1
                        self._safe_rmtree(task_dir, stats)

        return stats

    def cleanup_all(self, dry_run: bool = False) -> CleanupStats:
        """Run both passes and merge stats."""
        history_stats = self.cleanup_history(dry_run=dry_run)
        log_stats = self.cleanup_log_chunks(dry_run=dry_run)
        merged = CleanupStats(
            history_deleted=history_stats.history_deleted,
            log_chunks_deleted=log_stats.log_chunks_deleted,
            json_files_deleted=history_stats.json_files_deleted
            + log_stats.json_files_deleted,
            jsonl_files_deleted=log_stats.jsonl_files_deleted,
            task_dirs_deleted=log_stats.task_dirs_deleted,
            bytes_freed=history_stats.bytes_freed + log_stats.bytes_freed,
        )
        return merged


# ── internal helpers ────────────────────────────────────────────────────────


def _open_noop_conn() -> sqlite3.Connection:
    """Return an in-memory connection that does NOT touch disk.

    Used when ``db_path`` doesn't exist yet — we want all methods to be
    callable without crashing so dry-run reports stay informative even on
    a freshly-installed machine.
    """
    return sqlite3.connect(":memory:")


# ── factory ─────────────────────────────────────────────────────────────────


def cleaner_from_env(
    *,
    db_path: Path | None = None,
    history_dir: Path | None = None,
    logs_root: Path | None = None,
) -> SQLiteCleaner:
    """Build a :class:`SQLiteCleaner` from env-var overrides.

    Env vars:
      * ``SQLITE_HISTORY_TTL_DAYS`` (default 30)
      * ``SQLITE_LOG_TTL_DAYS``     (default 7)
    """
    return SQLiteCleaner(
        db_path=db_path,
        history_dir=history_dir,
        logs_root=logs_root,
        history_ttl_days=_env_int("SQLITE_HISTORY_TTL_DAYS", DEFAULT_HISTORY_TTL_DAYS),
        log_ttl_days=_env_int("SQLITE_LOG_TTL_DAYS", DEFAULT_LOG_TTL_DAYS),
    )


# ── module export ───────────────────────────────────────────────────────────

__all__ = [
    "CleanupStats",
    "DEFAULT_HISTORY_TTL_DAYS",
    "DEFAULT_LOG_TTL_DAYS",
    "SQLiteCleaner",
    "cleaner_from_env",
]