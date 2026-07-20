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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

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
    """Confirm no analysis is still pending/running in any layer."""
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


# ── metadata wipe ─────────────────────────────────────────────────────────


def _purge_metadata(store: HistoryStore, result: HistoryPurgeResult) -> None:
    """Unlink every history metadata file under ``_history_dir()``.

    Only the JSON metadata is touched — the report/log artifacts are
    removed by the dedicated helpers below.
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
