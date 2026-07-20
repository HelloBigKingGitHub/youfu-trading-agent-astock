-- ============================================================================
-- SQLite schema for tradingagents.db
-- ============================================================================
-- Source of truth: docs/SQLITE_MIGRATION_PLAN.md §2
-- Phase 3a minimum example — 4 tables + indexes + schema_migrations journal.
--
-- This file is the "idempotent" full DDL. To create a fresh database, run
-- `python backend/storage/schema_migrations/migrate.py` (which executes the
-- 001_initial.sql migration through the journal).
--
-- Direct usage:
--     sqlite3 ~/.tradingagents/tradingagents.db < backend/storage/schema.sql
--
-- All table definitions are wrapped in `CREATE TABLE IF NOT EXISTS` so this
-- file is safely re-runnable against an existing database (used by tests).
-- ============================================================================

-- -----------------------------------------------------------------------
-- Connection PRAGMAs (call after every connect, NOT stored in schema)
-- -----------------------------------------------------------------------
-- PRAGMA journal_mode = WAL;
-- PRAGMA synchronous  = NORMAL;
-- PRAGMA busy_timeout = 5000;
-- PRAGMA foreign_keys = ON;
-- PRAGMA cache_size    = -64000;
-- PRAGMA temp_store    = MEMORY;
-- (Applied in code; see backend/storage/schema_migrations/migrate.py)

-- -----------------------------------------------------------------------
-- Migration journal (must come first — migrate.py reads from it)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  REAL    NOT NULL,
    description TEXT    NOT NULL,
    checksum    TEXT    NOT NULL                  -- SHA256 of file contents (anti-tamper)
);

-- -----------------------------------------------------------------------
-- 1. history — aggregate root for analysis metadata
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS history (
    analysis_id     TEXT    PRIMARY KEY,          -- 16-char ulid (existing convention)
    ticker          TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,             -- "YYYY-MM-DD"
    signal          TEXT,                         -- "Buy"/"Sell"/"Hold"/NULL
    elapsed         REAL    NOT NULL DEFAULT 0,   -- seconds
    status          TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','running','completed','error')),
    error           TEXT,                         -- error message or NULL
    results_path    TEXT    NOT NULL DEFAULT '',  -- legacy full_states_log_*.json path
    started_at      REAL,
    finished_at     REAL,
    created_at      REAL    NOT NULL,
    schema_version  INTEGER NOT NULL DEFAULT 1    -- row-level schema version
);

CREATE INDEX IF NOT EXISTS idx_history_ticker_created
    ON history (ticker, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_history_status_running
    ON history (status) WHERE status IN ('running', 'pending');

CREATE INDEX IF NOT EXISTS idx_history_created
    ON history (created_at DESC);

-- -----------------------------------------------------------------------
-- 2. stage_reports — replaces HistoryEntry.stage_reports (dict[str, str])
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stage_reports (
    analysis_id TEXT    NOT NULL,
    report_key  TEXT    NOT NULL,                 -- canonical LangGraph chunk field key
    stage_id    TEXT    NOT NULL,                 -- pipeline stage label
    content     TEXT    NOT NULL,                 -- markdown report body
    created_at  REAL    NOT NULL,
    PRIMARY KEY (analysis_id, report_key),
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stage_reports_stage
    ON stage_reports (stage_id);

-- -----------------------------------------------------------------------
-- 3. completed_stages — replaces HistoryEntry.completed_stages (list[str])
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS completed_stages (
    analysis_id  TEXT    NOT NULL,
    stage_id     TEXT    NOT NULL,
    completed_at REAL    NOT NULL,
    sequence     INTEGER NOT NULL,                -- completion order (1, 2, 3, ...)
    PRIMARY KEY (analysis_id, stage_id),
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_completed_stages_analysis_seq
    ON completed_stages (analysis_id, sequence);

-- -----------------------------------------------------------------------
-- 4. log_chunks — stream events (replaces llm/tool/agent_output .jsonl)
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS log_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id   TEXT    NOT NULL,
    task_dir_name TEXT    NOT NULL,               -- "{date}_runNN}" — preserved for legacy API compat
    ts            REAL    NOT NULL,
    type          TEXT    NOT NULL
                            CHECK (type IN ('llm','tool','agent_output')),
    agent         TEXT    NOT NULL DEFAULT '',
    role          TEXT,
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    content       TEXT,
    tool          TEXT,
    input_json    TEXT,                           -- JSON-stringified input dict
    output        TEXT,
    report_key    TEXT,
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_analysis_ts
    ON log_chunks (analysis_id, ts);

CREATE INDEX IF NOT EXISTS idx_chunks_analysis_type
    ON log_chunks (analysis_id, type);

CREATE INDEX IF NOT EXISTS idx_chunks_task_dir
    ON log_chunks (task_dir_name);