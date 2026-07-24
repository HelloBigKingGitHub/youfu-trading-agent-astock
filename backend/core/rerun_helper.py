"""P2.34 hotfix: atomic rerun + debounce for ``POST /api/history/{id}/rerun``.

Background (DDD_OPERATIONS.md §6.9)
-----------------------------------
The previous ``rerun_history`` endpoint (backend/api/history.py) did::

    entry = store.get(analysis_id)
    payload = {"ticker": entry.ticker, "trade_date": entry.trade_date}
    store.delete(analysis_id)            # ← 删了！
    return {"ok": True, "start_analysis": payload, "analysis_id": analysis_id}

Three concrete failure modes:

1. **Race condition** — two concurrent clicks on "重新跑" both saw
   ``status in (completed, error)``, both deleted the old entry, then
   each created a brand-new analysis. The user ended up with two
   concurrent runs of the same ticker/date.
2. **State inconsistency** — between the ``delete`` and the follow-up
   ``POST /api/analyze``, a stale TrackerStore entry (still holding
   the old ``analysis_id``) could still serve `/api/analyze/progress`
   queries with garbage data.
3. **No debounce** — a user holding down the button (or a frontend
   retry loop) could spam the endpoint and pile up pending analyses.

What this module does
---------------------
- Provides ``rerun_analysis(analysis_id, ...)`` that performs the
  delete + create pair **inside** ``HistoryStore.exclusive_access()``
  so the two cannot interleave with another rerun, a worker
  ``mark_*`` write, or a purge sweep.
- Generates a **new** ``analysis_id`` for the new entry (the
  ``start_analysis`` runtime that follows this helper in P2.35 will
  pick it up unchanged — P2.34 only fixes the race / atomicity
  half).
- Enforces a 60-second debounce per ``analysis_id`` so a spammy
  client can not pile up identical reruns.
- Rejects rerunning an entry whose ``status`` is ``pending`` or
  ``running`` (those are live analyses; rerunning them would create
  two concurrent runs anyway).

Design notes (mirrors Phase 3d dual-write period style)
------------------------------------------------------
- **0 改** to ``history_store.py`` / ``log_store.py`` / ``runner.py``
  / ``web/runner.py``. This module is a pure consumer of the
  store's public API.
- The ``_recent_reruns`` dict is intentionally **process-local** —
  in a single-process uvicorn deploy (the only deploy we ship),
  the dict is the source of truth. A multi-worker deploy would
  need a Redis/SQLite-backed debounce, which is out of scope for
  P2.34.
- A failing ``store.delete()`` is logged and swallowed: the new
  entry is already on disk, the user already has a valid response,
  and a leftover old entry is much less harmful than a rollback
  that would re-orphan a freshly-created entry.
"""
from __future__ import annotations

import logging
import time
from uuid import uuid4

from backend.core.history_store import get_history_store

logger = logging.getLogger(__name__)

# Debounce window: same analysis_id cannot be rerun more than once
# within this many seconds. Default = 60s — short enough to allow a
# real user retry, long enough to absorb a double-click or a
# React Query retry loop.
RERUN_DEBOUNCE_SEC = 60.0

# Module-level debounce ledger. process-local, see docstring.
_recent_reruns: dict[str, float] = {}

# Terminal statuses that are eligible for rerun. P2.34 narrows this
# to the two states that mean "the analysis is done" — completed
# (full report) and error (worker gave up). pending/running are
# rejected so we never create a parallel live analysis.
_RERUNNABLE_STATUSES = frozenset({"completed", "error"})


def _clear_debounce(analysis_id: str) -> None:
    """Drop the debounce ledger entry — call on failure so the
    user is not punished with a 60s wait if the actual rerun did
    not happen.
    """
    _recent_reruns.pop(analysis_id, None)


def rerun_analysis(
    analysis_id: str,
    *,
    debounce_sec: float = RERUN_DEBOUNCE_SEC,
    now: float | None = None,
) -> str:
    """Atomically rerun a completed/errored analysis. Returns new ``analysis_id``.

    Parameters
    ----------
    analysis_id
        The analysis_id of the existing history entry to rerun.
    debounce_sec
        Override the per-process debounce window. Tests use a
        small value (e.g. ``0.05``) to keep the suite fast.
    now
        Override the wall clock for tests. ``None`` means
        ``time.time()``.

    Returns
    -------
    str
        The ``analysis_id`` of the newly-created entry. P2.34 only
        creates the entry; the actual analysis run is the
        follow-up work tracked as P2.35.

    Raises
    ------
    ValueError
        - The old entry does not exist (404 in the HTTP layer).
        - The old entry's ``status`` is not in
          ``_RERUNNABLE_STATUSES`` (409 in the HTTP layer).
        - The debounce window has not yet elapsed since the
          previous rerun attempt (409 in the HTTP layer).
    RuntimeError
        - The new entry could not be created (e.g. disk full).
          In this case the old entry is **not** deleted.
    """
    if now is None:
        now = time.time()

    # 1. Debounce — module-level ledger, process-local.
    last_rerun = _recent_reruns.get(analysis_id, 0.0)
    if now - last_rerun < debounce_sec:
        raise ValueError(
            f"rerun debounced for {analysis_id!r}: last attempt "
            f"{now - last_rerun:.1f}s ago (< {debounce_sec:.1f}s debounce window)"
        )
    _recent_reruns[analysis_id] = now

    store = get_history_store()

    # 2-5. Atomic operation — held inside the store's reentrant
    # lock so no other thread can sneak a ``create()``, ``delete()``,
    # or ``mark_*`` write in between our check and our delete.
    with store.exclusive_access():
        old_entry = store.get(analysis_id)
        if old_entry is None:
            _clear_debounce(analysis_id)
            raise ValueError(f"history entry {analysis_id!r} not found")

        if old_entry.status not in _RERUNNABLE_STATUSES:
            _clear_debounce(analysis_id)
            raise ValueError(
                f"cannot rerun {analysis_id!r}: status is {old_entry.status!r}, "
                f"only {'/'.join(sorted(_RERUNNABLE_STATUSES))} allowed"
            )

        # Build the new analysis_id.  Format mirrors the rest of the
        # codebase (ticker_date_<6 hex>) but with an ``_r<unix>`` tag
        # so a re-reader of the history list can tell the entry was
        # born from a rerun and not a fresh user request.
        new_id = (
            f"{old_entry.ticker}_{old_entry.trade_date}"
            f"_r{int(now)}_{uuid4().hex[:6]}"
        )

        # Create the new entry first; only delete the old one after
        # the new one is on disk. This is the "no orphan" guarantee:
        # if create() raises, the old entry is left intact.
        try:
            new_entry = store.create(
                ticker=old_entry.ticker,
                trade_date=old_entry.trade_date,
                status="pending",
                analysis_id=new_id,
            )
        except Exception as exc:
            _clear_debounce(analysis_id)
            logger.error(
                "rerun: failed to create new entry for %s: %s",
                analysis_id, exc,
            )
            raise RuntimeError(
                f"create new entry for {analysis_id!r} failed: {exc}"
            ) from exc

        # New entry is on disk — try to delete the old one. If this
        # fails we log and continue: the user already has a valid
        # analysis_id in the response, and a leftover old entry is
        # less harmful than a rollback that would orphan the new one.
        try:
            store.delete(analysis_id)
        except Exception as exc:
            logger.warning(
                "rerun: failed to delete old entry %s (new entry %s created): %s",
                analysis_id, new_id, exc,
            )

        logger.warning(
            "rerun: %s -> %s (ticker=%s, trade_date=%s, status=%s)",
            analysis_id, new_entry.analysis_id,
            old_entry.ticker, old_entry.trade_date, old_entry.status,
        )
        return new_entry.analysis_id


def reset_debounce() -> None:
    """Clear the in-process debounce ledger. Tests call this between
    cases so one test cannot leak a 60s wait into the next.
    """
    _recent_reruns.clear()
