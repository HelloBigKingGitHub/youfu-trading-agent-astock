-- ============================================================================
-- Migration 002: index optimization for Phase 3d cleanup queries.
-- ============================================================================
-- Phase 3d adds TTL cleanup queries that scan on (status, finished_at) and
-- (ts). 001_initial.sql's indexes do not cover those access paths:
--
--   - idx_history_ticker_created  : ticker + created_at   (UI list)
--   - idx_history_status_running  : status partial WHERE status IN running
--   - idx_history_created         : created_at DESC        (UI list)
--   - idx_chunks_analysis_ts      : (analysis_id, ts)      (per-task fetch)
--   - idx_chunks_analysis_type    : (analysis_id, type)    (per-task fetch)
--   - idx_chunks_task_dir         : task_dir_name          (legacy compat)
--
-- The TTL queries are NOT covered by any of the above:
--
--   DELETE FROM history
--     WHERE status IN ('completed','error') AND finished_at < :cutoff
--
--   DELETE FROM log_chunks WHERE ts < :cutoff
--
-- This migration adds two indexes tailored for those scans. Both are
-- non-covering (i.e., the planner still reads the row for the DELETE);
-- their purpose is to keep the scan from doing a full table scan as the
-- DB grows past ~10k rows.
-- ============================================================================

-- 1. history cleanup scan: (status, finished_at) range.
--    Using a partial index restricted to terminal statuses keeps it small
--    (~30-day window * completed rows only). The planner can use it for
--    both `WHERE status IN (...) AND finished_at < ?` and any ad-hoc
--    reports on completed-history timing.
CREATE INDEX IF NOT EXISTS idx_history_finished_at
    ON history (finished_at)
    WHERE status IN ('completed', 'error') AND finished_at IS NOT NULL;

-- 2. log_chunks TTL scan: range on ts alone.
--    The chunks table grows ~50–100x faster than history; a global index on
--    ts lets the cleanup pass use a simple range scan. Without this, a 7-day
--    cleanup over 1M rows is O(N); with it, it's O(N * 7 / retention_days).
CREATE INDEX IF NOT EXISTS idx_log_chunks_ts
    ON log_chunks (ts);