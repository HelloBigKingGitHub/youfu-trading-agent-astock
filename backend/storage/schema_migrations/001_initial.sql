-- ============================================================================
-- Migration 001: initial schema
-- ============================================================================
-- Creates the 4 core tables (history, stage_reports, completed_stages,
-- log_chunks) + all indexes. See backend/storage/schema.sql for the full DDL.
--
-- This migration is applied once via migrate.py and recorded in
-- schema_migrations with its SHA256 checksum (anti-tamper).
-- ============================================================================

CREATE TABLE history (
    analysis_id     TEXT    PRIMARY KEY,
    ticker          TEXT    NOT NULL,
    trade_date      TEXT    NOT NULL,
    signal          TEXT,
    elapsed         REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','running','completed','error')),
    error           TEXT,
    results_path    TEXT    NOT NULL DEFAULT '',
    started_at      REAL,
    finished_at     REAL,
    created_at      REAL    NOT NULL,
    schema_version  INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_history_ticker_created
    ON history (ticker, created_at DESC);

CREATE INDEX idx_history_status_running
    ON history (status) WHERE status IN ('running', 'pending');

CREATE INDEX idx_history_created
    ON history (created_at DESC);

CREATE TABLE stage_reports (
    analysis_id TEXT    NOT NULL,
    report_key  TEXT    NOT NULL,
    stage_id    TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  REAL    NOT NULL,
    PRIMARY KEY (analysis_id, report_key),
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX idx_stage_reports_stage
    ON stage_reports (stage_id);

CREATE TABLE completed_stages (
    analysis_id  TEXT    NOT NULL,
    stage_id     TEXT    NOT NULL,
    completed_at REAL    NOT NULL,
    sequence     INTEGER NOT NULL,
    PRIMARY KEY (analysis_id, stage_id),
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX idx_completed_stages_analysis_seq
    ON completed_stages (analysis_id, sequence);

CREATE TABLE log_chunks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id   TEXT    NOT NULL,
    task_dir_name TEXT    NOT NULL,
    ts            REAL    NOT NULL,
    type          TEXT    NOT NULL
                            CHECK (type IN ('llm','tool','agent_output')),
    agent         TEXT    NOT NULL DEFAULT '',
    role          TEXT,
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    content       TEXT,
    tool          TEXT,
    input_json    TEXT,
    output        TEXT,
    report_key    TEXT,
    FOREIGN KEY (analysis_id) REFERENCES history (analysis_id) ON DELETE CASCADE
);

CREATE INDEX idx_chunks_analysis_ts
    ON log_chunks (analysis_id, ts);

CREATE INDEX idx_chunks_analysis_type
    ON log_chunks (analysis_id, type);

CREATE INDEX idx_chunks_task_dir
    ON log_chunks (task_dir_name);