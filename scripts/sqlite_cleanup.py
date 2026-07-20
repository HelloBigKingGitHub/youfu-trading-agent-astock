"""CLI entry point for :mod:`backend.core.sqlite_cleanup`.

Mirrors ``scripts/migrate_logs_to_sqlite.py``'s style: ``--dry-run`` for
preview, ``--db`` for an alternate target, JSON summary on stdout, exit
code 0 on success (0 or more deletes) and 1 on hard errors.

Usage::

    .venv/bin/python scripts/sqlite_cleanup.py --dry-run
    .venv/bin/python scripts/sqlite_cleanup.py
    .venv/bin/python scripts/sqlite_cleanup.py --history-ttl 7 --log-ttl 1
    .venv/bin/python scripts/sqlite_cleanup.py --db /tmp/x.db --dry-run

Idempotent — safe to run from cron.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.sqlite_cleanup import (  # noqa: E402
    DEFAULT_HISTORY_TTL_DAYS,
    DEFAULT_LOG_TTL_DAYS,
    CleanupStats,
    SQLiteCleaner,
    cleaner_from_env,
)


def _print_human(stats: CleanupStats, *, dry_run: bool) -> None:
    label = "DRY RUN" if dry_run else "OK"
    print(f"{label}: history_deleted={stats.history_deleted}, "
          f"log_chunks_deleted={stats.log_chunks_deleted}, "
          f"json_files_deleted={stats.json_files_deleted}, "
          f"jsonl_files_deleted={stats.jsonl_files_deleted}, "
          f"task_dirs_deleted={stats.task_dirs_deleted}, "
          f"bytes_freed={stats.bytes_freed}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="sqlite_cleanup",
        description=(
            "Auto-cleanup for tradingagents.db + history JSON + log JSONL. "
            "Idempotent; safe to run repeatedly from cron."
        ),
    )
    p.add_argument(
        "--db", type=Path, default=None,
        help="Path to SQLite DB (default: ~/.tradingagents/tradingagents.db)",
    )
    p.add_argument(
        "--history-dir", type=Path, default=None,
        help="Path to history/*.json dir (default: ~/.tradingagents/logs/history)",
    )
    p.add_argument(
        "--logs-root", type=Path, default=None,
        help="Path to logs root (default: ~/.tradingagents/logs)",
    )
    p.add_argument(
        "--history-ttl", type=int, default=None,
        help=f"history TTL in days (default {DEFAULT_HISTORY_TTL_DAYS}, "
             "overrides SQLITE_HISTORY_TTL_DAYS)",
    )
    p.add_argument(
        "--log-ttl", type=int, default=None,
        help=f"log_chunks TTL in days (default {DEFAULT_LOG_TTL_DAYS}, "
             "overrides SQLITE_LOG_TTL_DAYS)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Compute the cleanup diff without deleting anything.",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of the human-readable line.",
    )

    args = p.parse_args(argv)

    # Build the cleaner — env wins unless an explicit CLI override was given.
    env_cleaner = cleaner_from_env(
        db_path=args.db,
        history_dir=args.history_dir,
        logs_root=args.logs_root,
    )
    history_ttl = args.history_ttl if args.history_ttl is not None else env_cleaner.history_ttl_days
    log_ttl = args.log_ttl if args.log_ttl is not None else env_cleaner.log_ttl_days

    cleaner = SQLiteCleaner(
        db_path=env_cleaner.db_path,
        history_dir=env_cleaner.history_dir,
        logs_root=env_cleaner.logs_root,
        history_ttl_days=history_ttl,
        log_ttl_days=log_ttl,
    )

    try:
        stats = cleaner.cleanup_all(dry_run=args.dry_run)
    finally:
        cleaner.close()

    if args.json:
        payload = {
            "dry_run": args.dry_run,
            "db": str(cleaner.db_path),
            "history_ttl_days": cleaner.history_ttl_days,
            "log_ttl_days": cleaner.log_ttl_days,
            **stats.as_dict(),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(stats, dry_run=args.dry_run)
        if stats.is_no_op():
            print("(no-op — nothing to clean)")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())