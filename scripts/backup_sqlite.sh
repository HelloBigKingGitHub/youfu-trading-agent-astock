#!/usr/bin/env bash
# ============================================================================
# Hot backup for tradingagents.db (Phase 3d, §5.2)
# ============================================================================
# Uses sqlite3's `.backup` command which is safe to run while uvicorn is
# serving traffic — it checkpoints the WAL internally and produces a
# consistent snapshot regardless of concurrent writers.
#
# Backup path:    ~/.tradingagents/backups/db-YYYYmmdd-HHMMSS.db
# Retention:      last 30 backups (configurable via BACKUP_KEEP env)
# Idempotent:     always creates a new timestamped file; never overwrites.
#
# Usage:
#   bash scripts/backup_sqlite.sh                    # default paths
#   BACKUP_KEEP=10 bash scripts/backup_sqlite.sh     # keep fewer
#   TRADINGAGENTS_DB=/tmp/x.db bash scripts/backup_sqlite.sh
#
# Cron suggestion (every Sunday 03:00):
#   0 3 * * 0  /home/youfu/projects/youfu-trading-agent-astock/scripts/backup_sqlite.sh >> /home/youfu/.tradingagents/backups/backup.log 2>&1
# ============================================================================

set -euo pipefail

# --- Paths / config ---------------------------------------------------------

DB_PATH="${TRADINGAGENTS_DB:-${HOME}/.tradingagents/tradingagents.db}"
BACKUP_DIR="${TRADINGAGENTS_BACKUP_DIR:-${HOME}/.tradingagents/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-30}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/db-${TIMESTAMP}.db"

# --- Pre-flight checks ------------------------------------------------------

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "ERROR: sqlite3 CLI not found in PATH" >&2
    exit 1
fi

if [[ ! -f "${DB_PATH}" ]]; then
    echo "ERROR: database not found at ${DB_PATH}" >&2
    exit 1
fi

mkdir -p "${BACKUP_DIR}"

# --- Hot backup -------------------------------------------------------------
#
# Strategy: run a TRUNCATE WAL checkpoint first so the .backup doesn't have
# to read from the -wal file (the backup is a single self-contained .db).
# Then `.backup` produces a transactionally-consistent copy.

echo "[$(date -Iseconds)] checkpoint WAL before backup..."
sqlite3 "${DB_PATH}" "PRAGMA wal_checkpoint(TRUNCATE);"

echo "[$(date -Iseconds)] backing up ${DB_PATH} -> ${BACKUP_FILE}"
sqlite3 "${DB_PATH}" ".backup '${BACKUP_FILE}'"

# --- Integrity check on the backup ------------------------------------------

integrity="$(sqlite3 "${BACKUP_FILE}" "PRAGMA integrity_check;")"
if [[ "${integrity}" != "ok" ]]; then
    echo "ERROR: backup failed integrity_check: ${integrity}" >&2
    rm -f "${BACKUP_FILE}"
    exit 2
fi

# --- Retention --------------------------------------------------------------
#
# Delete backups beyond the most-recent BACKUP_KEEP. We keep this last so a
# failed backup never accidentally prunes older good copies.

backup_count=$(ls -1 "${BACKUP_DIR}"/db-*.db 2>/dev/null | wc -l | tr -d ' ')
if (( backup_count > BACKUP_KEEP )); then
    # ``ls -t`` = newest-first; drop the head BACKUP_KEEP lines, delete the rest.
    ls -1t "${BACKUP_DIR}"/db-*.db | tail -n +$((BACKUP_KEEP + 1)) | while read -r old; do
        echo "[$(date -Iseconds)] pruning old backup ${old}"
        rm -f "${old}"
    done
fi

size=$(stat -c '%s' "${BACKUP_FILE}" 2>/dev/null || stat -f '%z' "${BACKUP_FILE}")
echo "[$(date -Iseconds)] OK: backup created ${BACKUP_FILE} (${size} bytes)"
echo "[$(date -Iseconds)] retained backups: $(ls -1 "${BACKUP_DIR}"/db-*.db 2>/dev/null | wc -l | tr -d ' ') / ${BACKUP_KEEP}"