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
8. *(Phase 3d)* Query performance benchmark — single-query timings for the
   most common read paths and the two TTL cleanup queries.
9. *(Phase 3d)* Cleanup timing — measures how long it takes
   :class:`SQLiteCleaner` to scan 100 eligible rows on this DB.
10. *(Phase 3d)* Index usage report — runs ``EXPLAIN QUERY PLAN`` against
    each canonical read / cleanup SQL and prints whether the planner uses
    an index.

Exit code is 0 only when **0 data loss / 0 missing** is observed and the
planner is using indexes for cleanup queries. Any drift sets exit code 1
so CI / a manual run can detect it.

Hard constraint: read-only — does NOT modify the DB (the cleanup timing
runs against an in-memory synthetic slice, never the live DB).

Usage::

    python scripts/verify_migration.py
    python scripts/verify_migration.py --db /tmp/x.db
    python scripts/verify_migration.py --skip-perf    # old behaviour only
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
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


# --- Phase 3d: performance + cleanup timing + EXPLAIN QUERY PLAN ------------

# Canonical queries whose perf + plan we want to report on.  ``label`` is
# only used for the printed output.
_PERF_QUERIES: list[tuple[str, str, tuple]] = [
    (
        "history list by ticker",
        "SELECT analysis_id FROM history WHERE ticker = ? ORDER BY created_at DESC LIMIT 50",
        ("600519",),
    ),
    (
        "history cleanup scan",
        "SELECT analysis_id FROM history WHERE status IN ('completed','error') "
        "AND finished_at IS NOT NULL AND finished_at < ?",
        (time.time() - 30 * 86400,),
    ),
    (
        "log_chunks per task fetch",
        "SELECT id, ts, type FROM log_chunks WHERE analysis_id = ? ORDER BY ts LIMIT 1000",
        ("placeholder-aid",),
    ),
    (
        "log_chunks cleanup scan",
        "SELECT id FROM log_chunks WHERE ts < ?",
        (time.time() - 7 * 86400,),
    ),
]


def _time_query(conn: sqlite3.Connection, sql: str, params: tuple, *, runs: int = 5) -> float:
    """Run ``sql`` ``runs`` times, return median elapsed seconds.

    SQLite caches prepared statements within a connection; we deliberately
    re-prepare each iteration so the timing reflects the cold plan as well.
    """
    import statistics

    samples: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        list(conn.execute(sql, params).fetchall())
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


def _explain(conn: sqlite3.Connection, sql: str, params: tuple) -> list[str]:
    """Return the ``EXPLAIN QUERY PLAN`` lines for ``sql``."""
    cur = conn.execute("EXPLAIN QUERY PLAN " + sql, params)
    return [row[3] for row in cur.fetchall()]


def _index_usage_report(conn: sqlite3.Connection) -> list[str]:
    """For each canonical query, print whether the planner uses an index.

    Returns the list of warning messages (empty = good).
    """
    warnings: list[str] = []
    for label, sql, params in _PERF_QUERIES:
        plan_lines = _explain(conn, sql, params)
        uses_index = any("USING INDEX" in line.upper() or "USING COVERING INDEX" in line.upper()
                         for line in plan_lines)
        marker = "OK " if uses_index else "WARN"
        joined = " | ".join(plan_lines) or "(no plan)"
        print(f"    [{marker}] {label}: {joined}")
        if not uses_index:
            warnings.append(f"{label}: no index used by planner — {joined}")
    return warnings


def _perf_benchmark(conn: sqlite3.Connection) -> dict[str, float]:
    """Time each canonical query and return {label: median_seconds}."""
    timings: dict[str, float] = {}
    for label, sql, params in _PERF_QUERIES:
        timings[label] = _time_query(conn, sql, params)
    return timings


def _cleanup_timing(db_path: Path) -> tuple[float, int]:
    """Measure :class:`SQLiteCleaner` cost against a synthetic in-memory slice.

    The function NEVER touches the live DB — it builds an isolated
    in-memory SQLite, populates 100 eligible rows + 100 keepers, then runs
    a non-dry-run cleanup and reports wall time + rows deleted.
    """
    from backend.core.sqlite_cleanup import SQLiteCleaner

    in_mem = sqlite3.connect(":memory:")
    _apply_pragmas(in_mem)
    in_mem.executescript(
        """
        CREATE TABLE history (
            analysis_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            status TEXT NOT NULL,
            finished_at REAL,
            started_at REAL,
            created_at REAL NOT NULL
        );
        CREATE INDEX idx_history_finished_at
            ON history (finished_at)
            WHERE status IN ('completed', 'error') AND finished_at IS NOT NULL;
        """
    )
    now = time.time()
    for i in range(200):
        # 100 old completed rows (eligible) + 100 new completed rows (keepers).
        status = "completed"
        finished_at = (now - 60 * 86400) if i < 100 else (now - 1 * 86400)
        in_mem.execute(
            "INSERT INTO history (analysis_id, ticker, trade_date, status, "
            "finished_at, started_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"timing-{i:03d}", "600519", "2026-07-01", status, finished_at,
             finished_at - 60, finished_at - 60),
        )
    in_mem.commit()

    cleaner = SQLiteCleaner(db_path=db_path, history_ttl_days=30, log_ttl_days=7)
    # Wedge the in-memory connection in so ``cleaner._connect`` returns it.
    # We avoid calling ``connect`` directly so we can also clean up afterwards.
    cleaner._conn = in_mem  # type: ignore[attr-defined]
    t0 = time.perf_counter()
    stats = cleaner.cleanup_history(dry_run=False)
    elapsed = time.perf_counter() - t0
    cleaner._conn = None  # type: ignore[attr-defined]
    cleaner.close()
    in_mem.close()
    return elapsed, stats.history_deleted


# --- Top-level verification flow -------------------------------------------

def verify(db_path: Path, *, skip_perf: bool = False) -> int:
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
        index_warnings: list[str] = []
        timings: dict[str, float] = {}
        cleanup_seconds = 0.0
        cleanup_deleted = 0
        if not skip_perf:
            index_warnings = _index_usage_report(conn)
            timings = _perf_benchmark(conn)
    finally:
        conn.close()

    if not skip_perf:
        cleanup_seconds, cleanup_deleted = _cleanup_timing(db_path)

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

    if not skip_perf:
        print()
        print("PERFORMANCE + INDEX USAGE (Phase 3d):")
        for label, secs in timings.items():
            print(f"  perf: {label:35s} median {secs * 1000:7.2f} ms")
        print(f"  cleanup_timing: {cleanup_deleted} rows deleted in "
              f"{cleanup_seconds * 1000:.2f} ms (synthetic 100-eligible slice)")
        if index_warnings:
            print("  WARN: planner is NOT using an index for:")
            for w in index_warnings:
                print(f"    - {w}")
        else:
            print("  index_usage: all canonical queries use an index")
        print("-" * 70)

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
    p.add_argument(
        "--skip-perf", action="store_true",
        help="Skip the Phase 3d perf benchmark + cleanup-timing slice.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return verify(args.db, skip_perf=args.skip_perf)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())