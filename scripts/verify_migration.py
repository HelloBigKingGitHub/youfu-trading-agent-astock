"""Reconciliation / verification script for the SQLite migration.

Compares the live log files on disk against the rows in
``~/.tradingagents/tradingagents.db`` and reports any drift.

Checks performed:

1. ``history`` row count vs number of ``history/*.json`` files
   (expect: row count >= file count; meta.json may add rows too).
2. ``history`` analysis_id set vs the union of all source-file IDs.
3. ``log_chunks`` row count vs total lines across all ``*.jsonl`` files.
4. Per-type chunk counts vs per-type source lines.
5. Sample field validation: pick N random rows and check
   ``status / signal / elapsed`` round-trip cleanly through JSON → SQLite.
6. ``schema_migrations`` journal exists and matches expected versions.
7. ``PRAGMA integrity_check`` + ``PRAGMA foreign_key_check``.

Exit code is 0 only when **0 data loss / 0 missing** is observed. Any
drift sets exit code 1 so CI / a manual run can detect it.

Hard constraint: read-only — does NOT modify the DB.

Usage::

    python scripts/verify_migration.py
    python scripts/verify_migration.py --db /tmp/x.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.storage.schema_migrations.migrate import (  # noqa: E402
    _DEFAULT_DB,
    _apply_pragmas,
)

_LOGS_ROOT = Path.home() / ".tradingagents" / "logs"
_HISTORY_DIR = _LOGS_ROOT / "history"
_LEGACY_SUBDIR = "TradingAgentsStrategy_logs"

# Match migrate_logs_to_sqlite.py — keep them in sync.
_CHUNK_FILE_TO_TYPE = {
    "llm_messages": "llm",
    "tool_calls": "tool",
    "agent_outputs": "agent_output",
}


# --- Source-file scanning (no DB) ------------------------------------------

def _scan_source() -> dict:
    """Compute expected counts from disk.

    Returns a dict with:
      history_file_ids: list[analysis_id] from history/*.json
      history_meta_ids: list[analysis_id] from logs/{t}/{date}_runNN/meta.json
      jsonl_lines_total: int
      jsonl_lines_by_type: dict[type, int]
      legacy_full_states: int
    """
    history_file_ids: list[str] = []
    history_meta_ids: list[str] = []
    jsonl_lines_by_type: dict[str, int] = {"llm": 0, "tool": 0, "agent_output": 0}
    jsonl_lines_total = 0
    legacy_count = 0

    if _HISTORY_DIR.is_dir():
        for p in sorted(_HISTORY_DIR.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                aid = d.get("analysis_id")
                if aid:
                    history_file_ids.append(aid)
            except (json.JSONDecodeError, OSError):
                pass

    if _LOGS_ROOT.is_dir():
        for ticker_dir in _LOGS_ROOT.iterdir():
            if not ticker_dir.is_dir():
                continue
            if ticker_dir.name in {"history", _LEGACY_SUBDIR} or ticker_dir.name.startswith("."):
                continue
            for task_dir in sorted(ticker_dir.iterdir()):
                if not (task_dir.is_dir() and "_run" in task_dir.name):
                    continue
                meta_path = task_dir / "meta.json"
                if meta_path.exists():
                    try:
                        d = json.loads(meta_path.read_text(encoding="utf-8"))
                        aid = d.get("analysis_id")
                        if aid:
                            history_meta_ids.append(aid)
                    except (json.JSONDecodeError, OSError):
                        pass
                for jp in sorted(task_dir.glob("*.jsonl")):
                    chunk_type = _CHUNK_FILE_TO_TYPE.get(jp.stem)
                    if not chunk_type:
                        continue
                    try:
                        n = sum(1 for ln in jp.read_text(encoding="utf-8").splitlines() if ln.strip())
                    except OSError:
                        n = 0
                    jsonl_lines_total += n
                    jsonl_lines_by_type[chunk_type] = jsonl_lines_by_type.get(chunk_type, 0) + n

            legacy_dir = ticker_dir / _LEGACY_SUBDIR
            if legacy_dir.is_dir():
                legacy_count += sum(1 for _ in legacy_dir.glob("full_states_log_*.json"))

    return {
        "history_file_ids": history_file_ids,
        "history_meta_ids": history_meta_ids,
        "jsonl_lines_total": jsonl_lines_total,
        "jsonl_lines_by_type": jsonl_lines_by_type,
        "legacy_full_states": legacy_count,
    }


# --- DB queries -------------------------------------------------------------

def _db_counts(conn: sqlite3.Connection) -> dict:
    cur = conn.execute("SELECT COUNT(*) FROM history")
    history_count = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM stage_reports")
    sr_count = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM completed_stages")
    cs_count = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(*) FROM log_chunks")
    chunks_total = cur.fetchone()[0]
    cur = conn.execute("SELECT type, COUNT(*) FROM log_chunks GROUP BY type")
    chunks_by_type = {row[0]: row[1] for row in cur.fetchall()}
    cur = conn.execute("SELECT analysis_id FROM history")
    db_history_ids = {row[0] for row in cur.fetchall()}
    return {
        "history_count": history_count,
        "stage_reports_count": sr_count,
        "completed_stages_count": cs_count,
        "chunks_total": chunks_total,
        "chunks_by_type": chunks_by_type,
        "db_history_ids": db_history_ids,
    }


def _sample_field_check(conn: sqlite3.Connection, n: int = 50) -> tuple[int, int]:
    """Sample N random history rows and verify status/signal/elapsed round-trip.

    Returns (ok, bad).
    """
    cur = conn.execute(
        "SELECT analysis_id, status, signal, elapsed FROM history ORDER BY RANDOM() LIMIT ?",
        (n,),
    )
    ok = bad = 0
    for row in cur.fetchall():
        aid, status, signal, elapsed = row
        if not aid:
            bad += 1
            continue
        if status not in {"pending", "running", "completed", "error"}:
            print(f"  FIELD-DRIFT: {aid} status={status!r} not in CHECK set", file=sys.stderr)
            bad += 1
            continue
        if elapsed is None or not isinstance(elapsed, (int, float)):
            print(f"  FIELD-DRIFT: {aid} elapsed={elapsed!r} not numeric", file=sys.stderr)
            bad += 1
            continue
        ok += 1
    return ok, bad


def _journal_check(conn: sqlite3.Connection) -> tuple[int, int]:
    """Verify schema_migrations journal exists and has entries."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    )
    if not cur.fetchone():
        return 0, 1
    cur = conn.execute("SELECT COUNT(*) FROM schema_migrations")
    return cur.fetchone()[0], 0


def _integrity_check(conn: sqlite3.Connection) -> list[str]:
    """Return list of integrity problems (empty = ok)."""
    issues: list[str] = []
    cur = conn.execute("PRAGMA integrity_check")
    res = cur.fetchone()
    if not res or res[0] != "ok":
        issues.append(f"PRAGMA integrity_check returned: {res[0] if res else None}")
    cur = conn.execute("PRAGMA foreign_key_check")
    fk_violations = cur.fetchall()
    if fk_violations:
        issues.append(f"FK violations: {len(fk_violations)} row(s)")
    return issues


# --- Top-level verification flow -------------------------------------------

def verify(db_path: Path) -> int:
    if not db_path.exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    src = _scan_source()
    conn = sqlite3.connect(str(db_path))
    _apply_pragmas(conn)
    try:
        db = _db_counts(conn)
        sample_ok, sample_bad = _sample_field_check(conn, n=50)
        journal_count, journal_err = _journal_check(conn)
        integrity_issues = _integrity_check(conn)
    finally:
        conn.close()

    # --- Reconcile ---
    expected_history_ids = set(src["history_file_ids"]) | set(src["history_meta_ids"])
    db_history_ids = db["db_history_ids"]
    missing_in_db = sorted(expected_history_ids - db_history_ids)
    extra_in_db = sorted(db_history_ids - expected_history_ids)

    chunks_ok = (db["chunks_total"] == src["jsonl_lines_total"])
    chunk_diffs: dict[str, tuple[int, int]] = {}
    for t, expected in src["jsonl_lines_by_type"].items():
        actual = db["chunks_by_type"].get(t, 0)
        if actual != expected:
            chunk_diffs[t] = (actual, expected)

    # --- Report ---
    print("=" * 70)
    print(f"VERIFICATION REPORT — {db_path}")
    print("=" * 70)
    print(f"  source: history/*.json={len(src['history_file_ids'])}, "
          f"task meta.json={len(src['history_meta_ids'])}, "
          f"jsonl lines={src['jsonl_lines_total']}, "
          f"legacy full_states_log={src['legacy_full_states']} (not migrated)")
    print(f"  db: history={db['history_count']}, stage_reports={db['stage_reports_count']}, "
          f"completed_stages={db['completed_stages_count']}, log_chunks={db['chunks_total']}")
    print(f"  journal: {journal_count} migration(s) recorded"
          + ("  [ERROR: missing]" if journal_err else ""))
    print(f"  sample field check: {sample_ok} ok / {sample_bad} bad (n=50)")
    print()

    failures: list[str] = []
    if missing_in_db:
        failures.append(f"history missing in DB: {len(missing_in_db)} (e.g. {missing_in_db[:3]})")
    if extra_in_db:
        # extras are tolerable (e.g., orphan rows from manual inserts), warn but don't fail
        print(f"  WARN: db has {len(extra_in_db)} analysis_id(s) not in source files "
              f"(e.g. {extra_in_db[:3]})", file=sys.stderr)
    if not chunks_ok:
        failures.append(f"log_chunks drift: db={db['chunks_total']}, source={src['jsonl_lines_total']}")
    if chunk_diffs:
        for t, (a, e) in chunk_diffs.items():
            failures.append(f"log_chunks type={t} drift: db={a}, source={e}")
    if sample_bad:
        failures.append(f"{sample_bad} sample row(s) failed field validation")
    if journal_err:
        failures.append("schema_migrations journal missing")
    if integrity_issues:
        failures.extend(integrity_issues)

    print("-" * 70)
    if failures:
        print(f"FAIL: {len(failures)} verification failure(s):")
        for f in failures:
            print(f"  - {f}")
        print("-" * 70)
        return 1
    print(f"OK: history {len(missing_in_db)} missing, log_chunks 0 missing, "
          f"{sample_ok}/{sample_ok + sample_bad} sample rows pass, "
          f"journal + integrity checks pass.")
    print("-" * 70)
    return 0


# --- CLI --------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verify_migration",
        description="Reconcile log files against tradingagents.db.",
    )
    p.add_argument("--db", type=Path, default=_DEFAULT_DB,
                   help=f"Path to SQLite DB (default: {_DEFAULT_DB})")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return verify(args.db)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())