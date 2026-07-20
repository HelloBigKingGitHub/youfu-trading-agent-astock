#!/usr/bin/env bash
# ============================================================================
# Restore tradingagents.db from a hot backup (Phase 3d, §5.2)
# ============================================================================
# By DEFAULT this script is dry-run: it prints the exact ``cp`` / ``sqlite3``
# commands it would run but does NOT touch the live DB.  Pass ``--confirm``
# to actually restore.
#
# Safety:
#   * Always backs up the current db to ``db-pre-restore-TIMESTAMP.db``
#     before clobbering it (so the restore itself is reversible).
#   * Verifies the chosen backup passes ``PRAGMA integrity_check`` before
#     swapping it in.
#
# Usage:
#   bash scripts/restore_sqlite.sh latest                      # dry-run
#   bash scripts/restore_sqlite.sh latest --confirm            # real restore
#   bash scripts/restore_sqlite.sh db-20260720-030000.db --confirm
#   bash scripts/restore_sqlite.sh --list                      # list backups
# ============================================================================

set -euo pipefail

DB_PATH="${TRADINGAGENTS_DB:-${HOME}/.tradingagents/tradingagents.db}"
BACKUP_DIR="${TRADINGAGENTS_BACKUP_DIR:-${HOME}/.tradingagents/backups}"

CONFIRM=0
LIST_ONLY=0
TARGET=""

# --- arg parsing ------------------------------------------------------------

while (( $# > 0 )); do
    case "$1" in
        --confirm)
            CONFIRM=1
            shift
            ;;
        --list)
            LIST_ONLY=1
            shift
            ;;
        --help|-h)
            sed -n '2,25p' "$0"
            exit 0
            ;;
        -*)
            echo "ERROR: unknown flag $1" >&2
            exit 1
            ;;
        *)
            TARGET="$1"
            shift
            ;;
    esac
done

# --- --list -----------------------------------------------------------------

if (( LIST_ONLY )); then
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        echo "(no backup dir at ${BACKUP_DIR})"
        exit 0
    fi
    echo "Available backups in ${BACKUP_DIR}:"
    ls -lt "${BACKUP_DIR}"/db-*.db 2>/dev/null || echo "  (none)"
    exit 0
fi

# --- pre-flight -------------------------------------------------------------

if [[ -z "${TARGET}" ]]; then
    echo "ERROR: no backup target specified (use 'latest' or a db-*.db filename)" >&2
    exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "ERROR: sqlite3 CLI not found in PATH" >&2
    exit 1
fi

# --- resolve backup path ----------------------------------------------------

if [[ "${TARGET}" == "latest" ]]; then
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        echo "ERROR: backup dir ${BACKUP_DIR} does not exist" >&2
        exit 1
    fi
    backup_path="$(ls -1t "${BACKUP_DIR}"/db-*.db 2>/dev/null | head -n 1 || true)"
    if [[ -z "${backup_path}" ]]; then
        echo "ERROR: no backups found in ${BACKUP_DIR}" >&2
        exit 1
    fi
elif [[ "${TARGET}" == /* ]]; then
    backup_path="${TARGET}"
else
    backup_path="${BACKUP_DIR}/${TARGET}"
fi

if [[ ! -f "${backup_path}" ]]; then
    echo "ERROR: backup not found at ${backup_path}" >&2
    exit 1
fi

# --- integrity check on the backup ------------------------------------------

integrity="$(sqlite3 "${backup_path}" "PRAGMA integrity_check;")"
if [[ "${integrity}" != "ok" ]]; then
    echo "ERROR: backup failed integrity_check: ${integrity}" >&2
    exit 2
fi

# --- dry-run by default -----------------------------------------------------

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
safety_backup="${BACKUP_DIR}/db-pre-restore-${TIMESTAMP}.db"

echo "[dry-run] would:"
echo "  1) integrity-check backup:       ${backup_path} -> ok"
echo "  2) snapshot current live db:     ${DB_PATH}"
echo "       -> ${safety_backup} (only if live db exists)"
echo "  3) replace live db with backup:  cp '${backup_path}' '${DB_PATH}'"
echo "  4) re-run integrity on live db:  sqlite3 '${DB_PATH}' \"PRAGMA integrity_check;\""

if (( CONFIRM == 0 )); then
    echo
    echo "(dry-run only — pass --confirm to actually run the restore)"
    exit 0
fi

# --- real restore -----------------------------------------------------------

echo "[$(date -Iseconds)] restoring ${backup_path} -> ${DB_PATH}"

# Snapshot the current live db first, if it exists.  Skip if live db is
# missing (fresh install).
if [[ -f "${DB_PATH}" ]]; then
    cp -p "${DB_PATH}" "${safety_backup}"
    echo "[$(date -Iseconds)] safety snapshot at ${safety_backup}"
fi

# Atomic-ish swap: write to a sibling .new then mv into place.  This avoids
# leaving the live db half-written if the restore is interrupted.
tmp_path="${DB_PATH}.new"
cp "${backup_path}" "${tmp_path}"
chmod 0644 "${tmp_path}"
mv -f "${tmp_path}" "${DB_PATH}"

post_integrity="$(sqlite3 "${DB_PATH}" "PRAGMA integrity_check;")"
if [[ "${post_integrity}" != "ok" ]]; then
    echo "ERROR: restored db failed integrity_check: ${post_integrity}" >&2
    echo "       safety snapshot still at ${safety_backup}" >&2
    exit 3
fi

echo "[$(date -Iseconds)] OK: restored from ${backup_path}"
echo "[$(date -Iseconds)] safety snapshot: ${safety_backup}"