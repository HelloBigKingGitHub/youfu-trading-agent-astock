"""Bulk history / report / log / cache purge service.

P2.30 — backs the ``POST /api/history/purge`` endpoint. Wipes every
terminal analysis (status ∈ {completed, error}) and its on-disk
artifacts in one atomic, locked sweep. Refuses to start if any
analysis is ``pending`` or ``running`` anywhere in the system.

The service NEVER touches:
  * schedules (config + run history) under ``~/.tradingagents/schedules/``
  * portfolio (positions / transactions / alerts) under
    ``~/.tradingagents/portfolio/``
  * watchlist.json, settings.json
  * agent memory directory
  * any ``logs_BACKUP_*`` sibling of the logs root

The user must opt in via the JSON body. The endpoint is the only
caller, so a missing ``include_cache`` is a programming error and we
default to ``False`` to be safe.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core import history_store as _history_store_mod  # noqa: E402
from backend.core.history_store import (  # noqa: E402
    HistoryEntry,
    HistoryStore,
    get_history_store,
)

logger = logging.getLogger(__name__)

# ``DEFAULT_CONFIG.data_cache_dir`` is the canonical cache root. The
# constant is module-level so tests can monkeypatch it. We resolve
# ``~`` the same way ``default_config._resolve_home_dir`` does.
try:
    from tradingagents.default_config import DEFAULT_CONFIG as _DEFAULT_CONFIG  # noqa: E402
    _DEFAULT_CACHE_DIR = Path(os.path.expanduser(_DEFAULT_CONFIG["data_cache_dir"]))
except Exception:  # pragma: no cover — default_config is always importable
    _DEFAULT_CACHE_DIR = Path.home() / ".tradingagents" / "cache"

_CACHE_DIR = _DEFAULT_CACHE_DIR
_RESULTS_DIR = Path(_history_store_mod._RESULTS_DIR)


def _history_dir() -> Path:
    """Resolve the history metadata dir at call time.

    ``history_store._HISTORY_DIR`` is monkeypatched by tests (and could
    theoretically be reconfigured at runtime); the cleanup helpers must
    pick up the current value, not the one captured at import.
    """
    return _history_store_mod._HISTORY_DIR


def _results_dir() -> Path:
    """Resolve the results (logs) dir at call time.

    ``_RESULTS_DIR`` is also exposed as a module-level attribute (for
    tests that monkeypatch it), but the helpers below always re-read
    through this accessor so a runtime monkeypatch on either
    ``history_store._RESULTS_DIR`` or ``cleanup_mod._RESULTS_DIR``
    takes effect.
    """
    return _RESULTS_DIR

# Active statuses — any entry in this set blocks ``purge_history``.
ACTIVE_STATUSES = frozenset({"pending", "running"})

# Directories we never descend into even if a buggy caller ever wired
# them up as a purge root. The compare is path-anchored.
def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _forbidden_roots() -> tuple[Path, ...]:
    """Resolve forbidden roots at call time.

    ``Path.home()`` is captured here (not at import) so a ``monkeypatch``
    of ``$HOME`` — or a runtime change in production — takes effect.
    """
    return (Path("/"), Path.home(), _project_root())


@dataclass
class HistoryPurgeResult:
    """Tally returned by ``purge_history``.

    No field holds a host filesystem path — the response must not leak
    user home / ``~/.tradingagents/...`` to the client.
    """

    ok: bool = True
    history_deleted: int = 0
    reports_deleted: int = 0
    log_runs_deleted: int = 0
    cache_files_deleted: int = 0
    bytes_freed: int = 0
    failed_items: int = 0


class ActiveAnalysesError(Exception):
    """Raised when at least one analysis is still ``pending`` or ``running``."""

    def __init__(self, active_ids: list[str]) -> None:
        self.active_ids = active_ids
        super().__init__(
            f"{len(active_ids)} analysis/analyses are still active: "
            + ", ".join(active_ids[:10])
        )


# ── public entry point ────────────────────────────────────────────────────


def purge_history(*, include_cache: bool = False) -> HistoryPurgeResult:
    """Wipe all terminal history, results, log runs and (optionally) cache.

    Raises ``ActiveAnalysesError`` without touching disk if any
    ``pending``/``running`` analysis is found.
    """
    store = get_history_store()

    # 1) Block on any active analysis while holding the store's exclusive
    #    lock so a new ``create()`` can not interleave between the check
    #    and the unlink loop.
    with store.exclusive_access():
        _assert_no_active_analyses(store)
        result = HistoryPurgeResult()
        _purge_metadata(store, result)
        _purge_results_and_logs(result)
        if include_cache:
            _purge_cache(result)
        return result


# ── checks ────────────────────────────────────────────────────────────────


def _assert_no_active_analyses(store: HistoryStore) -> None:
    """Confirm no analysis is still pending/running in any layer.

    P2.32 hotfix — before checking the active set, sweep any zombie
    tracker whose persisted history metadata is already terminal (or
    missing entirely). The previous behavior blocked purge whenever the
    in-memory ``AnalysisTracker.is_running`` flag was True, even if the
    backing worker thread had crashed and the metadata was already
    ``completed``/``error``. Users who hit this were stuck: every restart
    re-spawned the stale tracker on import (via ``TrackerStore.get_instance()``
    in lifespan), the active-check raised ``ActiveAnalysesError``, and the
    destructive action was permanently denied.

    Sweep strategy:
      * For every ``tracker.is_running=True`` entry, look up the
        matching history metadata.
      * If metadata is missing → orphan tracker (race between
        ``TrackerStore.create`` and the history write that lost to a
        crash). Drop the tracker so the recent list stops showing a
        phantom entry.
      * If metadata exists but is terminal (``completed`` / ``error``)
        → the worker finalised before the crash; the tracker is stale.
        Drop ``is_running`` (preserve the rest of the tracker for any
        post-mortem read).
    """
    # 1) Sweep stale tracker entries first so the active-check below
    #    doesn't trip on zombies.
    _sweep_stale_trackers(store)

    # 1b) P2.31 hotfix — sweep JSON-history zombies too (status=running +
    #     elapsed=0 + older than ``ZOMBIE_TTL_SEC``). Phase 3d added a
    #     startup-time sweep that catches zombies that survive a restart;
    #     this runtime pass catches ones that appear *after* the most
    #     recent worker died mid-flight. The user-reported
    #     ``bbca7f78`` case is exactly this: JSON metadata still says
    #     ``running`` but the tracker is gone and no thread is alive.
    scan_and_mark_zombies()

    # 2) Re-read the active set with up-to-date tracker state.
    active: list[str] = []

    # HistoryStore metadata
    entries, _ = store.list_all(limit=10_000, offset=0)
    for e in entries:
        if e.status in ACTIVE_STATUSES:
            active.append(e.analysis_id)

    # In-memory TrackerStore — covers the brief window where the worker
    # has not yet written its first ``mark_stage_done`` but the tracker
    # is alive.
    try:
        from backend.core.tracker import get_store as _get_tracker_store

        for tracker in _get_tracker_store().list_all():
            if tracker.is_running and tracker.analysis_id not in active:
                active.append(tracker.analysis_id)
    except Exception:  # pragma: no cover — defensive only
        pass

    if active:
        raise ActiveAnalysesError(active)


def _sweep_stale_trackers(store: HistoryStore) -> None:
    """Flip ``is_running`` on trackers whose metadata is already terminal.

    P2.32 hotfix — see ``_assert_no_active_analyses`` docstring. Operates
    on the in-memory ``TrackerStore`` singleton and never deletes the
    tracker itself; only the ``is_running`` flag is cleared so any
    subsequent post-mortem read still surfaces the entry.

    Orphan trackers (no metadata at all) are removed outright because
    there is nothing to keep around for.
    """
    try:
        from backend.core.tracker import get_store as _get_tracker_store
    except Exception:  # pragma: no cover — defensive only
        return

    tracker_store = _get_tracker_store()
    for tracker in list(tracker_store.list_all()):
        if not tracker.is_running:
            continue
        meta = store.get(tracker.analysis_id)
        if meta is None:
            # Orphan: tracker was created in memory but the metadata write
            # never landed. Drop the in-memory entry so it stops tripping
            # future active-checks.
            tracker_store.delete(tracker.analysis_id)
            logger.info(
                "purge: swept orphan tracker %s (no history metadata)",
                tracker.analysis_id,
            )
            continue
        if meta.status not in ACTIVE_STATUSES:
            # Stale: the worker finalised the metadata before a crash
            # left the tracker flag stuck. Clear ``is_running`` so a
            # subsequent ``_assert_no_active_analyses`` no longer flags
            # this id.
            tracker.is_running = False
            logger.info(
                "purge: swept stale tracker %s (metadata status=%s)",
                tracker.analysis_id,
                meta.status,
            )


# P2.31 hotfix — TTL for the runtime zombie sweep. Mirrors
# ``history_store.ZOMBIE_THRESHOLD_SEC``; we keep our own copy so a future
# refactor that retunes the threshold in one place doesn't accidentally
# re-introduce the runtime gap.
ZOMBIE_TTL_SEC = 600.0


def scan_and_mark_zombies(
    *, now: Optional[float] = None, ttl_sec: float = ZOMBIE_TTL_SEC,
) -> list[str]:
    """Mark JSON-history zombies ``error`` so ``purge_history`` can proceed.

    P2.31 hotfix — Phase 3d added a *startup-time* sweep that reaps any
    ``status=running + elapsed=0`` entry left over from a previous
    process.  That handles the "server crashed before the worker
    finalised" case *if the user restarts*, but does not catch the more
    common pattern: the worker thread dies *after* startup, the JSON
    metadata still says ``running``, the in-memory ``TrackerStore``
    forgets the entry on its next refresh, and the user is left with a
    permanent 409 on ``/api/history/purge``. The user-reported
    ``600595_2026-07-21_bbca7f78`` zombie is exactly this shape — 8
    ``completed_stages`` but ``status=running`` and no live thread.

    Sweep policy:
      * ``status == 'running'`` AND ``elapsed == 0`` AND the
        ``started_at`` (or, as fallback, ``created_at``) is older than
        ``ttl_sec`` → call ``store.mark_error(analysis_id, ...)``.  The
        next ``_assert_no_active_analyses`` then sees the entry as
        terminal and allows the purge to proceed.
      * ``status == 'running'`` with ``elapsed > 0`` → leave alone.
        That's a long-running analysis that the user *intends* to keep
        running; killing it would be data loss.
      * Anything else → untouched.

    Returns the list of analysis_ids that were marked ``error`` (in the
    order they were processed).  The function never raises — it logs
    and skips on per-entry errors so one bad row doesn't block the
    sweep.
    """
    cleaned: list[str] = []
    store = get_history_store()
    if now is None:
        now = time.time()
    try:
        entries, _ = store.list_all(limit=10_000, offset=0)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("scan_and_mark_zombies: list_all failed: %s", exc)
        return cleaned

    for entry in entries:
        if entry.status != "running":
            continue
        if entry.elapsed != 0:
            # Long-running analysis with real progress — not a zombie.
            continue
        anchor = entry.started_at or entry.created_at
        if anchor is None:
            continue
        if (now - anchor) < ttl_sec:
            # Still inside the TTL grace window — don't reap yet.
            continue
        try:
            elapsed = max(0.0, now - anchor)
            store.mark_error(
                entry.analysis_id,
                error="manually marked zombie (purge-time sweep)",
                elapsed=elapsed,
            )
            cleaned.append(entry.analysis_id)
            logger.warning(
                "scan_and_mark_zombies: marked %s as error (running %ss, elapsed=0)",
                entry.analysis_id,
                int(elapsed),
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "scan_and_mark_zombies: failed to mark %s: %s",
                entry.analysis_id,
                exc,
            )
    return cleaned


# ── metadata wipe ─────────────────────────────────────────────────────────


def _purge_metadata(store: HistoryStore, result: HistoryPurgeResult) -> None:
    """Unlink every history metadata file + bulk-DELETE SQLite history rows.

    Phase 4 cut the read path over to the SQLite sidecar
    (``READ_FROM_SQLITE=1``) so ``DualReadHistoryStore.list_all()``
    serves rows straight from the sidecar.  The pre-Phase-4 purge
    cleared only the JSON layer, which left 17 stale rows visible via
    ``/api/history`` because the SQLite sidecar still held the
    canonical copy.  Mirror the JSON wipe against SQLite so the
    post-purge state is consistent.

    P2.31 hotfix — the SQLite sidecar lives behind
    ``backend.core.history_store_sqlite.SQLiteHistoryStore``.  We never
    import the module at module top so a Python build without
    ``sqlite3`` (rare but possible in slim containers) degrades
    gracefully: the JSON wipe still completes, the SQLite wipe logs a
    warning and skips.  The store is opened via the ``sqlite_helper``
    shim and closed after the bulk delete via ``with`` semantics
    (handled inside the helper's transaction).
    """
    history_dir = _history_dir()
    if not history_dir.exists():
        return
    for path in history_dir.glob("*.json"):
        if path.is_symlink():
            # Never follow a symlink planted under the history dir.
            try:
                size = path.lstat().st_size
                path.unlink()
                result.bytes_freed += size
                result.failed_items += 1
            except OSError:
                continue
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            result.history_deleted += 1
            result.bytes_freed += size
        except OSError as exc:
            logger.warning("purge: failed to unlink history %s: %s", path, exc)
            result.failed_items += 1

    # P2.31 hotfix — mirror the JSON wipe against the SQLite sidecar.
    # Failure here is *non-fatal*: the JSON layer is already clean, and
    # the user's primary complaint ("history list still shows N rows")
    # is a read-path symptom — leaving a few rows in SQLite would
    # partially regress to the pre-fix behaviour, so we *do* abort the
    # rest of the wipe (already done at this point) but never raise.
    try:
        from backend.core.sqlite_helper import (  # noqa: WPS433 — lazy
            bulk_delete_all_history,
            get_sqlite_history_store_or_none,
        )

        sqlite_store = get_sqlite_history_store_or_none()
        if sqlite_store is not None:
            sqlite_deleted = bulk_delete_all_history(sqlite_store)
            if sqlite_deleted > 0:
                result.history_deleted += sqlite_deleted
                logger.warning(
                    "purge: cleared %d SQLite history rows",
                    sqlite_deleted,
                )
            try:
                sqlite_store.close()
            except Exception:  # pragma: no cover — defensive
                pass
    except Exception as exc:
        logger.warning("purge: SQLite history cleanup failed (non-fatal): %s", exc)


# ── reports + per-run log dirs ────────────────────────────────────────────


def _purge_results_and_logs(result: HistoryPurgeResult) -> None:
    """Unlink every per-ticker results file + per-run log directory.

    Iterates ``_results_dir()`` (=``~/.tradingagents/logs``) and, for each
    ticker subdir, removes:
      * ``TradingAgentsStrategy_logs/full_states_log_*.json`` (reports)
      * ``{date}_run{NN}/`` (per-task log chunks)

    Skips non-numeric / non-ticker subdirs (e.g. the ``history`` dir
    the metadata wipe already handled, or any ``logs_BACKUP_*``
    sibling that lives one level above this root).

    P2.31 hotfix — Phase 4 routes ``stream_chunks`` reads through the
    SQLite sidecar (``log_chunks`` table).  ``LogWriter.append_chunk``
    still dual-writes to the JSONL files under ``{date}_runNN/``, so
    a Phase-4 purge must clear **both** layers; otherwise a
    post-purge ``/api/logs`` request would return rows from SQLite
    while the on-disk JSONL files are gone (or vice versa).  Mirrors
    the dual-write symmetry from Phase 3c.
    """
    results_dir = _results_dir()
    if not results_dir.exists():
        return
    results_root = results_dir.resolve()
    for child in _safe_iterdir(results_root):
        if not child.is_dir():
            continue
        ticker = child.name
        if ticker == "history" or ticker.startswith("logs_BACKUP_"):
            continue
        # Tickers are 6-digit codes per project convention; anything
        # else here is likely an unrelated folder (the ``tradingagents``
        # code base itself lives at the project root, never here).
        if not ticker.isdigit() or len(ticker) != 6:
            continue
        _purge_ticker_dir(child, result)

    # P2.31 hotfix — mirror the JSONL wipe against the SQLite sidecar.
    # Non-fatal: a SQLite unavailable (slim Python) or schema-not-yet
    # migrated environment logs a warning and skips.  We close the
    # store inside the helper's transaction, so a leak is impossible
    # even if the bulk delete raises.
    try:
        from backend.core.sqlite_helper import (  # noqa: WPS433 — lazy
            bulk_delete_all_log_chunks,
            get_sqlite_history_store_or_none,
        )

        sqlite_store = get_sqlite_history_store_or_none()
        if sqlite_store is not None:
            sqlite_log_deleted = bulk_delete_all_log_chunks(sqlite_store)
            if sqlite_log_deleted > 0:
                result.log_runs_deleted += sqlite_log_deleted
                logger.warning(
                    "purge: cleared %d SQLite log_chunks rows",
                    sqlite_log_deleted,
                )
            try:
                sqlite_store.close()
            except Exception:  # pragma: no cover — defensive
                pass
    except Exception as exc:
        logger.warning("purge: SQLite log_chunks cleanup failed: %s", exc)


def _purge_ticker_dir(ticker_dir: Path, result: HistoryPurgeResult) -> None:
    """Remove a single ticker's reports + log-run dirs without following symlinks."""
    for child in _safe_iterdir(ticker_dir):
        if child.is_symlink():
            # Never chase a symlink under a purge root.
            try:
                size = child.lstat().st_size
                child.unlink()
                result.bytes_freed += size
                result.failed_items += 1  # symlink → counted as a guard event
            except OSError:
                continue
            continue
        if child.is_dir():
            name = child.name
            if name == "TradingAgentsStrategy_logs":
                _purge_reports_dir(child, result)
            elif "_run" in name:
                _purge_log_run_dir(child, result)
            # Any other dir under a ticker is project-internal — skip.
        elif child.is_file():
            # Stray files at the ticker root are rare; drop them so
            # the purge produces a clean slate.
            _unlink_file(child, result)


def _purge_reports_dir(reports_dir: Path, result: HistoryPurgeResult) -> None:
    for f in _safe_iterdir(reports_dir):
        if f.is_file() and f.suffix == ".json":
            _unlink_file(f, result)
            result.reports_deleted += 1
        elif f.is_dir():
            # Legacy nested dirs (e.g. ``by_date/``) — drop recursively.
            _rmtree(f, result, label="report_subdir")


def _purge_log_run_dir(run_dir: Path, result: HistoryPurgeResult) -> None:
    # A run dir contains meta.json + 3 jsonl files; we use rmtree to
    # keep the code simple, but count it as a single ``log_runs_deleted``
    # regardless of internal file count.
    _rmtree(run_dir, result, label="log_run_dir", count_as="log_runs_deleted")


# ── cache wipe ───────────────────────────────────────────────────────────


def _purge_cache(result: HistoryPurgeResult) -> None:
    """Recursively unlink every regular file under ``_CACHE_DIR``."""
    if not _CACHE_DIR.exists():
        return
    cache_root = _CACHE_DIR.resolve()
    # Mirror the ``_results`` / ``_history`` paths' safety net: refuse to
    # descend if the cache root was somehow re-pointed at a forbidden
    # location (defense in depth for future refactors that parametrise it).
    for forbidden in _forbidden_roots():
        if cache_root == forbidden.resolve():
            logger.warning("purge: refused to iterate forbidden cache root %s", cache_root)
            return
    for path in cache_root.rglob("*"):
        if path.is_symlink():
            try:
                size = path.lstat().st_size
                path.unlink()
                result.bytes_freed += size
                result.failed_items += 1
            except OSError:
                continue
            continue
        if path.is_file():
            _unlink_file(path, result)
            result.cache_files_deleted += 1


# ── helpers ──────────────────────────────────────────────────────────────


def _safe_iterdir(root: Path) -> Iterable[Path]:
    """``iterdir`` that never yields anything for forbidden roots."""
    try:
        resolved = root.resolve()
    except OSError:
        return iter(())
    for forbidden in _forbidden_roots():
        if resolved == forbidden.resolve():
            logger.warning("purge: refused to iterate forbidden root %s", root)
            return iter(())
    if not root.exists():
        return iter(())
    try:
        return list(root.iterdir())
    except OSError as exc:
        logger.warning("purge: failed to iterdir %s: %s", root, exc)
        return iter(())


def _unlink_file(path: Path, result: HistoryPurgeResult) -> None:
    try:
        size = path.stat().st_size
        path.unlink()
        result.bytes_freed += size
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("purge: failed to unlink %s: %s", path, exc)
        result.failed_items += 1


def _rmtree(
    path: Path,
    result: HistoryPurgeResult,
    *,
    label: str,
    count_as: str | None = None,
) -> None:
    """Recursively remove a directory, counting once per call.

    The size delta is the sum of regular-file sizes within (best-effort).
    """
    bytes_before = 0
    try:
        for sub in path.rglob("*"):
            if sub.is_file() and not sub.is_symlink():
                try:
                    bytes_before += sub.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    try:
        shutil.rmtree(path)
        result.bytes_freed += bytes_before
        if count_as == "log_runs_deleted":
            result.log_runs_deleted += 1
    except OSError as exc:
        logger.warning("purge: failed to rmtree %s (%s): %s", path, label, exc)
        result.failed_items += 1
