"""Phase 5b: cleanup JSON/JSONL logs after switching to SQLite-only writes.

After the 1-week observation period (Phase 4 + Phase 5b SINGLE_WRITE_SQLITE=1),
the user can manually delete:

  * ``~/.tradingagents/logs/history/*.json``           (history sidecars)
  * ``~/.tradingagents/logs/{ticker}/{date}_runNN/*.jsonl`` (run chunks)

We **keep** the legacy ``full_states_log_*.json`` reports under
``~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/`` because the
report-generation pipeline still reads them.

By default the tool runs in ``--dry-run`` mode and only counts how many files
**would** be deleted.  Pass ``--force`` to actually unlink them.

Examples::

    # Count what would be removed (default = dry-run)
    python scripts/cleanup_old_jsonl.py

    # Preview the list of files
    python scripts/cleanup_old_jsonl.py --dry-run

    # Actually delete
    python scripts/cleanup_old_jsonl.py --force

    # Use a different logs root (e.g. for testing)
    python scripts/cleanup_old_jsonl.py --logs-root /tmp/ta_logs --dry-run
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LOGS_ROOT = Path.home() / ".tradingagents" / "logs"

# Ticker directory names are 6-digit codes (e.g. "600519").  Anything else
# in ``logs_root`` is a sibling namespace (e.g. ``history/`` or
# ``TradingAgentsStrategy_logs/``) and must be skipped.
_TICKER_DIR_RE = lambda name: name.isdigit() and len(name) == 6


def find_old_files(logs_root: Path) -> tuple[list[Path], list[Path]]:
    """Find old JSON history + JSONL run files to delete.

    Returns ``(history_json_files, jsonl_run_files)``.

    History JSON files live in ``{logs_root}/history/*.json`` and are the
    sidecar of each ``HistoryStore`` analysis entry.  JSONL run files
    live in ``{logs_root}/{ticker}/{date}_runNN/*.jsonl`` and are the
    sidecar of each ``LogWriter`` task.

    Both are safe to remove once the SQLite sidecar
    (``~/.tradingagents/tradingagents.db``) has been the source of truth
    for >= 1 week (Phase 5b observation window).
    """
    history_dir = logs_root / "history"
    history_jsons: list[Path] = (
        sorted(history_dir.glob("*.json")) if history_dir.exists() else []
    )

    jsonl_runs: list[Path] = []
    if logs_root.exists():
        for ticker_dir in sorted(logs_root.iterdir()):
            if not ticker_dir.is_dir() or not _TICKER_DIR_RE(ticker_dir.name):
                continue
            # New run-dirs follow ``{date}_runNN`` naming; JSONL chunks
            # inside are sidecars that we are about to drop.
            for run_dir in ticker_dir.glob("*_run*"):
                if run_dir.is_dir():
                    jsonl_runs.extend(sorted(run_dir.glob("*.jsonl")))

    return history_jsons, jsonl_runs


def cleanup(logs_root: Path, dry_run: bool = True) -> dict[str, int]:
    """Delete the legacy JSON / JSONL sidecars.

    Returns a small dict with three counters::

        {
            "history_files": <int>,   # how many history/*.json would be / were touched
            "jsonl_files":   <int>,   # how many {ticker}/{date}_runNN/*.jsonl touched
            "deleted":       <int>,   # actually unlinked (0 in dry-run)
        }
    """
    history, jsonl = find_old_files(logs_root)
    if dry_run:
        return {
            "history_files": len(history),
            "jsonl_files": len(jsonl),
            "deleted": 0,
        }

    deleted = 0
    for f in history:
        try:
            f.unlink()
            deleted += 1
        except OSError as e:
            logger.warning("failed to delete %s: %s", f, e)
    for f in jsonl:
        try:
            f.unlink()
            deleted += 1
        except OSError as e:
            logger.warning("failed to delete %s: %s", f, e)
    return {
        "history_files": len(history),
        "jsonl_files": len(jsonl),
        "deleted": deleted,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Phase 5b cleanup: delete old JSON history + JSONL run files "
            "after the SQLite-only migration is stable."
        )
    )
    p.add_argument(
        "--logs-root",
        type=Path,
        default=DEFAULT_LOGS_ROOT,
        help="Root of the tradingagents logs tree (default: %(default)s)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count files; do not delete (default if --force is missing)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Actually delete the files (otherwise dry-run)",
    )
    args = p.parse_args()

    # Default to dry-run unless the user explicitly opts into --force.
    if not args.force:
        args.dry_run = True

    if not args.logs_root.exists():
        print(
            f"[DRY-RUN] logs_root does not exist: {args.logs_root} "
            "(nothing to clean)"
        )
        return

    result = cleanup(args.logs_root, dry_run=args.dry_run)
    mode = "DRY-RUN" if args.dry_run else "DELETED"
    print(
        f"[{mode}] history_files={result['history_files']}, "
        f"jsonl_files={result['jsonl_files']}, "
        f"deleted={result['deleted']}"
    )


if __name__ == "__main__":
    main()
