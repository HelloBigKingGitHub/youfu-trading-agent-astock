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


# ── P2.35 hotfix: rerun + actually start ─────────────────────────────────────
#
# P2.34 closed the atomicity half (delete + create race) but the endpoint
# only created a new history entry — it never spawned the worker, so the
# user saw ``status=pending`` forever. P2.35 completes §6.9 by chaining
# ``start_analysis`` onto the helper so a rerun behaves like a fresh
# POST /api/analyze for the same ticker/date.
#
# Design contract (preserved from P2.34):
#
# * ``rerun_analysis`` stays as-is. It owns the atomicity, status guard,
#   and debounce. This function layers the actual start on top.
# * ``start_analysis`` is **not** modified. We import it lazily inside
#   ``rerun_and_start`` so a test environment that never hits the
#   endpoint does not pay the cost of ``web/runner.py`` /
#   ``tradingagents.default_config`` loading.
# * The returned ``analysis_id`` is the one ``start_analysis`` produces —
#   a fresh uuid-based id of the form ``{ticker}_{date}_{hex}``. The
#   helper-created ``_r<ts>_<hex>`` stub is deleted after
#   ``start_analysis`` succeeds because it would otherwise be a
#   duplicate orphan (start_analysis writes its own history entry).
#
# Failure mode contract:
#
# * If ``rerun_analysis`` raises (debounce / 404 / 409 / 500),
#   ``rerun_and_start`` propagates without calling ``start_analysis``.
# * If ``start_analysis`` raises after ``rerun_analysis`` succeeded,
#   the ``_r<ts>_<hex>`` stub is left in ``pending`` state so the user
#   can retry; the 60s debounce remains in effect to avoid piling up
#   identical reruns while the underlying problem is fixed.
def rerun_and_start(
    analysis_id: str,
    config: dict | None = None,
    *,
    debounce_sec: float = RERUN_DEBOUNCE_SEC,
    now: float | None = None,
) -> dict:
    """P2.35 hotfix — atomic rerun + actually start the new analysis.

    Parameters
    ----------
    analysis_id
        Existing history entry to rerun.
    config
        Optional ``DEFAULT_CONFIG`` overrides forwarded to
        ``start_analysis``. Tests pass a stub; production typically
        passes ``None`` so ``start_analysis`` reads
        ``tradingagents.default_config.DEFAULT_CONFIG``.
    debounce_sec
        Forwarded to :func:`rerun_analysis`. Tests use a small value
        to keep the suite fast.
    now
        Forwarded to :func:`rerun_analysis` for wall-clock injection.

    Returns
    -------
    dict
        ``{ok, analysis_id, ticker, trade_date, start_analysis}``
        where ``analysis_id`` is the live id returned by
        ``start_analysis`` and ``start_analysis`` echoes the
        ticker/trade_date pair so the React Query client can show
        a toast without an extra history fetch.

    Raises
    ------
    ValueError
        404 / 409 from :func:`rerun_analysis` (not found, wrong
        status, debounce window). Caller maps to HTTPException.
    RuntimeError
        500 — atomic create of the helper stub failed.
    Exception
        Anything raised by :func:`start_analysis` (e.g. ticker
        format validation, OpenAI key missing, …). The helper
        stub remains in ``pending`` for retry.
    """
    # Step 1 — P2.34 atomic delete-old + create-stub + debounce.
    stub_id = rerun_analysis(
        analysis_id,
        debounce_sec=debounce_sec,
        now=now,
    )

    # Step 2 — read the helper-created stub for its ticker/trade_date.
    store = get_history_store()
    stub_entry = store.get(stub_id)
    if stub_entry is None:
        # Defensive: should not happen because rerun_analysis just
        # created it. If it did, the old entry is gone and there is
        # no new one either — surface as 500.
        raise RuntimeError(
            f"rerun_and_start: helper-created stub {stub_id!r} vanished "
            f"immediately after rerun_analysis()"
        )

    # Step 3 — actually start the analysis. start_analysis(request)
    # creates its own history entry (uuid-based) and a tracker,
    # then spawns the worker thread. We pass the ticker/date from
    # the helper-created stub because it inherits those from the
    # old entry. Config overrides flow through if provided.
    from backend.core import start_analysis as _start_analysis
    from backend.models.request import AnalyzeRequest

    llm_overrides = (config or {}).get("llm_overrides") or {}

    request = AnalyzeRequest(
        ticker=stub_entry.ticker,
        trade_date=stub_entry.trade_date,
        llm_provider=llm_overrides.get("llm_provider", "minimax"),
        quick_think_llm=llm_overrides.get(
            "quick_think_llm", "MiniMax-M2.7-highspeed",
        ),
        deep_think_llm=llm_overrides.get("deep_think_llm", "MiniMax-M2.7"),
        backend_url=llm_overrides.get("backend_url"),
    )

    try:
        live_id, _tracker = _start_analysis(request)
    except Exception:
        # start_analysis raised before/after creating its entry.
        # Either way, the helper stub is still in pending state and
        # the user gets a retryable error. We log so an operator
        # can correlate the two halves.
        logger.warning(
            "rerun_and_start: start_analysis raised for %s "
            "(stub %s left in pending for retry)",
            analysis_id, stub_id,
            exc_info=True,
        )
        raise

    # Step 4 — clean up the helper-created stub. start_analysis
    # wrote its own history entry keyed by ``live_id``; the stub
    # is now redundant and would show up as an orphan in the
    # history list. Best-effort delete — a leftover stub is much
    # less harmful than a rollback that could orphan the live one.
    try:
        store.delete(stub_id)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "rerun_and_start: failed to delete helper stub %s "
            "(live entry %s already running): %s",
            stub_id, live_id, exc,
        )

    logger.warning(
        "rerun_and_start: %s -> %s (ticker=%s, trade_date=%s) "
        "[stub=%s, debounce_sec=%.1f]",
        analysis_id, live_id,
        stub_entry.ticker, stub_entry.trade_date,
        stub_id, debounce_sec,
    )

    payload = {
        "ticker": stub_entry.ticker,
        "trade_date": stub_entry.trade_date,
    }
    return {
        "ok": True,
        "analysis_id": live_id,
        "ticker": stub_entry.ticker,
        "trade_date": stub_entry.trade_date,
        "start_analysis": payload,
    }
