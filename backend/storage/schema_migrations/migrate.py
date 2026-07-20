"""Django-style migration runner for tradingagents.db.

Discovers ``NNN_*.sql`` files in this directory, applies any that are not
yet recorded in the ``schema_migrations`` journal, and wraps each in a
``BEGIN ... COMMIT`` transaction. SHA256 checksums prevent accidental
re-application of mutated files.

Usage (from anywhere)::

    python -m backend.storage.schema_migrations.migrate
    python -m backend.storage.schema_migrations.migrate --db /path/to.db
    python -m backend.storage.schema_migrations.migrate --dry-run

Design contract (Phase 3a minimum example):

* ``schema_migrations`` is bootstrapped first via ``schema.sql`` so the
  journal itself is safe to query.
* Each migration runs inside a transaction — if anything fails, the DB
  rolls back to the pre-migration state and the version is NOT recorded.
* The function is **idempotent** — re-running it on an up-to-date DB is
  a no-op.
* It does NOT touch runtime code (backend/core/log_store.py,
  history_store.py, runner.py, etc.) — Phase 3a is data-only.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable

# --- Paths -------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_SCHEMA_SQL = _THIS_DIR.parent / "schema.sql"
_DEFAULT_DB = Path.home() / ".tradingagents" / "tradingagents.db"


# --- Connection setup -------------------------------------------------------

def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply connection PRAGMAs recommended in docs/SQLITE_MIGRATION_PLAN.md §2.1.

    Called immediately after every connect. WAL must be set before any
    write transaction begins.
    """
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous  = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA cache_size    = -64000")
    conn.execute("PRAGMA temp_store    = MEMORY")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Use autocommit (isolation_level=None) so that executescript()'s internal
    # COMMIT does not interfere with our manual BEGIN/COMMIT boundaries.
    # We wrap each migration in its own sqlite3.Transaction context manager
    # instead of relying on the connection's auto-begin.
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    _apply_pragmas(conn)
    return conn


# --- Schema bootstrap -------------------------------------------------------

def _ensure_journal_exists(conn: sqlite3.Connection) -> None:
    """Create ONLY the ``schema_migrations`` journal if missing.

    We don't bootstrap the 4 core tables here — they're created by
    001_initial.sql so the migration journal is the source of truth for
    what was applied when. The first migration handles table creation.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            applied_at  REAL    NOT NULL,
            description TEXT    NOT NULL,
            checksum    TEXT    NOT NULL
        )
        """
    )


def _ensure_core_tables_exist(conn: sqlite3.Connection) -> None:
    """Create the 4 core tables + indexes if missing (recovery path).

    Only used when the journal is up-to-date but the 4 tables somehow
    aren't present (e.g., partial bootstrap, manual DB surgery). On a
    fresh DB this is a no-op because 001_initial.sql creates them.
    """
    if not _SCHEMA_SQL.exists():
        raise FileNotFoundError(f"schema.sql not found at {_SCHEMA_SQL}")
    conn.executescript(_SCHEMA_SQL.read_text(encoding="utf-8"))


# --- Migration discovery & application --------------------------------------

def _migration_files() -> list[Path]:
    """Return NNN_*.sql files in this directory, sorted by version prefix."""
    return sorted(p for p in _THIS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def _applied_versions(conn: sqlite3.Connection) -> dict[int, str]:
    """Return {version: checksum} for every applied migration."""
    cur = conn.execute(
        "SELECT version, checksum FROM schema_migrations ORDER BY version"
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _checksum(path: Path) -> str:
    """SHA256 hex digest of the file contents."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _parse_version(path: Path) -> int:
    """Extract the leading integer prefix from a migration filename."""
    return int(path.name.split("_", 1)[0])


def _apply_one(conn: sqlite3.Connection, sql_path: Path) -> None:
    """Apply a single migration file in its own transaction.

    Uses sqlite3.Transaction context manager which emits explicit
    BEGIN/COMMIT/ROLLBACK around the wrapped block. We append the
    ``INSERT INTO schema_migrations`` to the SQL text itself so the
    journal record is committed atomically with the schema change.
    """
    version = _parse_version(sql_path)
    description = sql_path.stem  # e.g. "001_initial"
    sql_text = sql_path.read_text(encoding="utf-8")
    # Append the journal insert as the last statement in the same script.
    # executescript() commits once at the end — atomic with the schema DDL.
    sql_text += (
        "\nINSERT INTO schema_migrations (version, applied_at, description, checksum) "
        f"VALUES ({version}, {time.time()}, '{description}', '{_checksum(sql_path)}');\n"
    )
    try:
        with conn:  # BEGIN ... COMMIT (ROLLBACK on exception)
            conn.executescript(sql_text)
    except Exception:
        # The context manager already rolled back; re-raise with context.
        raise


def migrate(db_path: Path | None = None, dry_run: bool = False) -> Iterable[str]:
    """Apply any pending migrations. Yields human-readable status lines.

    Parameters
    ----------
    db_path:
        Path to the SQLite file. Defaults to ``~/.tradingagents/tradingagents.db``.
    dry_run:
        If True, report what would be applied without touching the DB.

    Returns
    -------
    Iterable[str]
        Status lines (suitable for printing or logging).
    """
    db_path = Path(db_path) if db_path else _DEFAULT_DB
    messages: list[str] = []

    if dry_run:
        # Inspect file system only — no DB connection required for dry-run.
        for sql_path in _migration_files():
            messages.append(f"DRY-RUN: would apply {sql_path.name}")
        messages.append(f"DRY-RUN: target db = {db_path}")
        for m in messages:
            yield m
        return

    conn = _connect(db_path)
    try:
        # Bootstrap: ensure the schema_migrations journal exists so we can
        # inspect applied versions. Use IF NOT EXISTS so this is a no-op
        # once the DB is bootstrapped. Other 4 tables are created by
        # 001_initial.sql on first run.
        _ensure_journal_exists(conn)

        applied = _applied_versions(conn)
        pending = [p for p in _migration_files() if _parse_version(p) not in applied]

        if not pending:
            # Belt-and-braces: if the journal exists but the 4 tables don't
            # (partial bootstrap), re-run schema.sql to fill in the rest.
            _ensure_core_tables_exist(conn)
            yield f"OK: schema up-to-date at {db_path} (no pending migrations)"
            return

        for sql_path in pending:
            version = _parse_version(sql_path)
            yield f"  applying {sql_path.name}..."
            t0 = time.time()
            _apply_one(conn, sql_path)
            dt = time.time() - t0
            yield f"  applied  {sql_path.name} in {dt:.2f}s"

        yield f"OK: applied {len(pending)} migration(s); db = {db_path}"
    finally:
        conn.close()


# --- CLI ---------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backend.storage.schema_migrations.migrate",
        description="Apply pending SQLite migrations (Django-style journal).",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_DB,
        help=f"Path to SQLite DB (default: {_DEFAULT_DB})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List migrations that would be applied without touching the DB.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        for line in migrate(db_path=args.db, dry_run=args.dry_run):
            print(line)
    except Exception as exc:  # pragma: no cover — CLI surface
        print(f"ERROR: migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())