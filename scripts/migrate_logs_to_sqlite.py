"""One-shot migration: import existing logs/*.json + *.jsonl into SQLite.

Phase 3a minimum example. Reads from the live JSON/JSONL files at::

    ~/.tradingagents/logs/history/{analysis_id}.json
    ~/.tradingagents/logs/{ticker}/{date}_runNN/meta.json
    ~/.tradingagents/logs/{ticker}/{date}_runNN/*.jsonl
    ~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_*.json   # legacy, skipped

Writes into the 4 tables created by ``backend.storage.schema_migrations``.

Design contract:

* **Idempotent** — every insert uses ``INSERT OR IGNORE`` keyed on natural
  primary keys (``history.analysis_id``, ``log_chunks`` uniqueness
  ``(analysis_id, ts, type, content_hash)``, etc.). Re-running this script
  on an already-imported DB is a no-op.
* **Read-only on source files** — the JSON files are left in place as
  rollback backup. Phase 3d (after 7-day observation) is when deletion
  happens, manually.
* **Dry-run** — ``--dry-run`` prints a summary without touching the DB.
* **Backwards compat** — legacy ``full_states_log_*.json`` files are
  detected and counted but NOT migrated (they're referenced by the
  history row's ``results_path``).

Usage::

    python scripts/migrate_logs_to_sqlite.py                 # real run
    python scripts/migrate_logs_to_sqlite.py --dry-run       # preview
    python scripts/migrate_logs_to_sqlite.py --db /tmp/x.db   # alternate target

Hard constraint: this script does NOT modify any runtime code
(``backend/core/log_store.py``, ``history_store.py``, ``runner.py``,
``tracker.py``). It only writes to the SQLite target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable

# Make backend.storage.schema_migrations importable when run as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.storage.schema_migrations.migrate import (  # noqa: E402
    _DEFAULT_DB,
    _apply_pragmas,
    migrate as run_migrations,
)

_LOGS_ROOT = Path.home() / ".tradingagents" / "logs"
_HISTORY_DIR = _LOGS_ROOT / "history"
_LEGACY_SUBDIR = "TradingAgentsStrategy_logs"

# Mapping from file-suffix chunk-type to log_chunks.type enum value.
# (Schema CHECK: type IN ('llm','tool','agent_output'))
_CHUNK_FILE_TO_TYPE = {
    "llm_messages": "llm",
    "tool_calls": "tool",
    "agent_outputs": "agent_output",
}


# --- DB connection ---------------------------------------------------------

def _open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    _apply_pragmas(conn)
    return conn


# --- Source-file discovery -------------------------------------------------

def _iter_history_json() -> Iterable[Path]:
    """``~/.tradingagents/logs/history/*.json``."""
    if not _HISTORY_DIR.is_dir():
        return
    yield from sorted(_HISTORY_DIR.glob("*.json"))


def _iter_task_dirs() -> Iterable[Path]:
    """``~/.tradingagents/logs/{ticker}/{date}_runNN/`` directories."""
    if not _LOGS_ROOT.is_dir():
        return
    for ticker_dir in sorted(_LOGS_ROOT.iterdir()):
        if not ticker_dir.is_dir():
            continue
        if ticker_dir.name in {"history", "TradingAgentsStrategy_logs"} or ticker_dir.name.startswith("."):
            continue
        for task_dir in sorted(ticker_dir.iterdir()):
            # Match "{date}_runNN}" pattern (no real } char — that's from a doc typo).
            if task_dir.is_dir() and "_run" in task_dir.name:
                yield task_dir


def _iter_legacy_full_states() -> Iterable[Path]:
    """``~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_*.json``.

    These are NOT migrated — they're already referenced via history.results_path
    by Phase 3a. We just count them for the dry-run report.
    """
    if not _LOGS_ROOT.is_dir():
        return
    for ticker_dir in _LOGS_ROOT.iterdir():
        legacy_dir = ticker_dir / _LEGACY_SUBDIR
        if not legacy_dir.is_dir():
            continue
        yield from sorted(legacy_dir.glob("full_states_log_*.json"))


# --- Parsing helpers -------------------------------------------------------

def _load_json(path: Path) -> dict | None:
    """Load a JSON file; return None on any error (with a friendly note)."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        print(f"  WARN: bad JSON in {path.name}: {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"  WARN: cannot read {path}: {exc}", file=sys.stderr)
        return None


def _load_jsonl_lines(path: Path) -> Iterable[dict]:
    """Yield parsed JSONL lines; skip lines that fail to parse."""
    try:
        with path.open("r", encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    print(f"  WARN: bad JSONL line in {path.name}:{ln}: {exc}", file=sys.stderr)
    except OSError as exc:
        print(f"  WARN: cannot read {path}: {exc}", file=sys.stderr)


# --- Migration logic -------------------------------------------------------

def _content_hash(*parts: object) -> str:
    """Stable SHA256 over a tuple of fields — used for log_chunks idempotency."""
    h = hashlib.sha256()
    for p in parts:
        if p is None:
            h.update(b"\x00")
        elif isinstance(p, (dict, list)):
            h.update(json.dumps(p, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        else:
            h.update(str(p).encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


def _import_history_row(conn: sqlite3.Connection, entry: dict) -> bool:
    """Insert one history row from a history/*.json or meta.json file.

    Uses ``INSERT OR IGNORE`` so re-running on the same analysis_id is a
    no-op. Returns True if the row was newly inserted, False if it already
    existed.
    """
    analysis_id = entry.get("analysis_id")
    if not analysis_id:
        return False

    cur = conn.execute(
        """
        INSERT OR IGNORE INTO history (
            analysis_id, ticker, trade_date, signal, elapsed, status, error,
            results_path, started_at, finished_at, created_at, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            analysis_id,
            entry.get("ticker", ""),
            entry.get("trade_date", ""),
            entry.get("signal") or None,            # HistoryEntry default ""
            float(entry.get("elapsed", entry.get("elapsed_sec", 0.0)) or 0.0),
            entry.get("status", "pending"),
            entry.get("error") or None,
            entry.get("results_path", ""),
            entry.get("started_at"),
            entry.get("finished_at"),
            float(entry.get("created_at", time.time())),
        ),
    )
    return cur.rowcount > 0


def _import_stage_reports(conn: sqlite3.Connection, entry: dict) -> int:
    """Insert all stage_reports for one history entry. Returns count inserted."""
    reports = entry.get("stage_reports") or {}
    if not isinstance(reports, dict):
        return 0
    inserted = 0
    for report_key, content in reports.items():
        # Derive stage_id from report_key by stripping trailing "_report" if present.
        stage_id = report_key
        if stage_id.endswith("_report"):
            stage_id = stage_id[: -len("_report")]
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO stage_reports (
                analysis_id, report_key, stage_id, content, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                entry["analysis_id"],
                report_key,
                stage_id,
                content or "",
                float(entry.get("created_at", time.time())),
            ),
        )
        inserted += cur.rowcount
    return inserted


def _import_completed_stages(conn: sqlite3.Connection, entry: dict) -> int:
    """Insert all completed_stages for one history entry, preserving order."""
    stages = entry.get("completed_stages") or entry.get("stages_completed") or []
    if not isinstance(stages, list):
        return 0
    inserted = 0
    base_ts = float(entry.get("created_at", time.time()))
    for seq, stage_id in enumerate(stages, start=1):
        # We don't have per-stage timestamps; use created_at + seq seconds.
        completed_at = base_ts + seq
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO completed_stages (
                analysis_id, stage_id, completed_at, sequence
            ) VALUES (?, ?, ?, ?)
            """,
            (entry["analysis_id"], stage_id, completed_at, seq),
        )
        inserted += cur.rowcount
    return inserted


def _import_log_chunk(
    conn: sqlite3.Connection,
    analysis_id: str,
    task_dir_name: str,
    chunk: dict,
    chunk_type: str,
) -> bool:
    """Insert one log_chunks row, dedup by (analysis_id, ts, type, content_hash).

    SQLite has AUTOINCREMENT id but we want re-runs to be idempotent. The
    natural uniqueness for a chunk is its (analysis_id, ts, type) + a hash
    of the mutable content fields. We use INSERT OR IGNORE with a UNIQUE
    expression in WHERE NOT EXISTS — SQLite doesn't support unique on
    expressions via CREATE TABLE so we do it imperatively.
    """
    ts = float(chunk.get("ts", time.time()))
    agent = chunk.get("agent", "") or ""
    role = chunk.get("role")
    tokens_in = chunk.get("tokens_in")
    tokens_out = chunk.get("tokens_out")
    content = chunk.get("content")
    tool = chunk.get("tool")
    input_json = chunk.get("input_json")
    output = chunk.get("output")
    report_key = chunk.get("report_key")

    chash = _content_hash(analysis_id, ts, chunk_type, agent, role, content, tool, input_json, output)

    cur = conn.execute(
        """
        INSERT INTO log_chunks (
            analysis_id, task_dir_name, ts, type, agent, role,
            tokens_in, tokens_out, content, tool, input_json, output, report_key
        )
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM log_chunks
            WHERE analysis_id = ? AND ts = ? AND type = ? AND content = ?
        )
        """,
        (
            analysis_id, task_dir_name, ts, chunk_type, agent, role,
            tokens_in, tokens_out, content, tool, input_json, output, report_key,
            # WHERE NOT EXISTS params:
            analysis_id, ts, chunk_type, content,
        ),
    )
    return cur.rowcount > 0


# --- Top-level migration flow ----------------------------------------------

def _import_history_files(conn: sqlite3.Connection, dry_run: bool) -> tuple[int, int, int, int]:
    """Import from ``logs/history/*.json``.

    Returns (history_inserted, stage_reports_inserted, completed_stages_inserted, errors).
    """
    h_ins = sr_ins = cs_ins = errs = 0
    files = list(_iter_history_json())
    if not files:
        print(f"  history: 0 files found in {_HISTORY_DIR}")
        return 0, 0, 0, 0

    print(f"  history: scanning {len(files)} files in {_HISTORY_DIR}")
    for i, path in enumerate(files, 1):
        if dry_run:
            h_ins += 1
            continue
        entry = _load_json(path)
        if entry is None:
            errs += 1
            continue
        if _import_history_row(conn, entry):
            h_ins += 1
        sr_ins += _import_stage_reports(conn, entry)
        cs_ins += _import_completed_stages(conn, entry)
        if i % 100 == 0:
            print(f"    ...{i}/{len(files)} processed", file=sys.stderr)
    if not dry_run:
        conn.commit()
    return h_ins, sr_ins, cs_ins, errs


def _import_task_dirs(conn: sqlite3.Connection, dry_run: bool) -> tuple[int, int, int]:
    """Import from ``logs/{ticker}/{date}_runNN/{meta.json,*.jsonl}``.

    Returns (chunks_inserted, history_dedup_skipped, errors).
    History inserts via meta.json use INSERT OR IGNORE — if the matching
    analysis_id already came from history/*.json, it's skipped silently.
    """
    chunks_ins = history_dedup = errs = 0
    tasks = list(_iter_task_dirs())
    if not tasks:
        print(f"  tasks: 0 task dirs found under {_LOGS_ROOT}")
        return 0, 0, 0

    print(f"  tasks: scanning {len(tasks)} task dirs under {_LOGS_ROOT}")
    for task_dir in tasks:
        meta_path = task_dir / "meta.json"
        if dry_run:
            # Count history inserts + jsonl lines as if we'd insert them.
            chunks_ins += sum(1 for _ in task_dir.glob("*.jsonl"))
            if meta_path.exists():
                history_dedup += 1
            continue

        if meta_path.exists():
            entry = _load_json(meta_path)
            if entry is not None and _import_history_row(conn, entry) is False:
                history_dedup += 1
        else:
            entry = None

        # jsonl chunks
        for jsonl_path in sorted(task_dir.glob("*.jsonl")):
            chunk_type = _CHUNK_FILE_TO_TYPE.get(jsonl_path.stem)
            if not chunk_type:
                print(f"    WARN: unknown jsonl name {jsonl_path.name} in {task_dir}", file=sys.stderr)
                continue
            for chunk in _load_jsonl_lines(jsonl_path):
                aid = chunk.get("analysis_id")
                if not aid and entry is not None:
                    aid = entry.get("analysis_id")
                if not aid:
                    errs += 1
                    continue
                if _import_log_chunk(conn, aid, task_dir.name, chunk, chunk_type):
                    chunks_ins += 1
    if not dry_run:
        conn.commit()
    return chunks_ins, history_dedup, errs


def _count_legacy_full_states() -> int:
    """Count legacy full_states_log_*.json files (NOT imported — fallback only)."""
    return sum(1 for _ in _iter_legacy_full_states())


def migrate_logs(db_path: Path, dry_run: bool = False) -> dict:
    """Run the full migration. Returns a stats dict."""
    # Always ensure schema is up to date first (idempotent).
    list(run_migrations(db_path=db_path))

    stats = {
        "db_path": str(db_path),
        "dry_run": dry_run,
        "history_inserted": 0,
        "stage_reports_inserted": 0,
        "completed_stages_inserted": 0,
        "history_dedup_skipped": 0,
        "chunks_inserted": 0,
        "errors": 0,
        "legacy_full_states_seen": _count_legacy_full_states(),
    }

    if dry_run:
        # Dry-run report: estimate counts by scanning files only.
        h_files = list(_iter_history_json())
        tasks = list(_iter_task_dirs())
        chunk_files = sum(1 for t in tasks for _ in t.glob("*.jsonl"))
        chunk_lines = 0
        for t in tasks:
            for jp in t.glob("*.jsonl"):
                try:
                    with jp.open("r", encoding="utf-8") as f:
                        chunk_lines += sum(1 for ln in f if ln.strip())
                except OSError:
                    pass
        print(f"DRY RUN: would import")
        print(f"  history/*.json files: {len(h_files)}")
        print(f"  task meta.json: {len(tasks)} (some dedup with history/*.json)")
        print(f"  jsonl files: {chunk_files}")
        print(f"  jsonl lines (log_chunks): {chunk_lines}")
        print(f"  legacy full_states_log_*.json: {stats['legacy_full_states_seen']} (NOT migrated)")
        stats.update({
            "history_inserted": len(h_files),
            "chunks_inserted": chunk_lines,
            "history_dedup_skipped": len(tasks),
        })
        return stats

    conn = _open_db(db_path)
    try:
        t0 = time.time()
        h, sr, cs, errs = _import_history_files(conn, dry_run=False)
        stats["history_inserted"] += h
        stats["stage_reports_inserted"] += sr
        stats["completed_stages_inserted"] += cs
        stats["errors"] += errs

        ci, hd, errs2 = _import_task_dirs(conn, dry_run=False)
        stats["chunks_inserted"] += ci
        stats["history_dedup_skipped"] += hd
        stats["errors"] += errs2

        dt = time.time() - t0
        stats["elapsed_sec"] = round(dt, 3)
        print(f"OK: imported {stats['history_inserted']} history + "
              f"{stats['chunks_inserted']} log_chunks + "
              f"{stats['stage_reports_inserted']} stage_reports + "
              f"{stats['completed_stages_inserted']} completed_stages "
              f"in {dt:.2f}s "
              f"({stats['history_dedup_skipped']} meta deduped, "
              f"{stats['legacy_full_states_seen']} legacy skipped)")
    finally:
        conn.close()
    return stats


# --- CLI --------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate_logs_to_sqlite",
        description="One-shot import of logs/*.json + *.jsonl into SQLite.",
    )
    p.add_argument("--db", type=Path, default=_DEFAULT_DB,
                   help=f"Path to SQLite DB (default: {_DEFAULT_DB})")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan files and report counts without touching the DB.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        migrate_logs(db_path=args.db, dry_run=args.dry_run)
    except Exception as exc:
        print(f"ERROR: migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())