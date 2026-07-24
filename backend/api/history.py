"""GET /api/history — unified history API using history_store.

Mirrors web/components/history_panel.py 1:1:
- list with filters (ticker / signal / status / min_elapsed / max_elapsed)
- single entry detail
- delete entry
- re-run entry (delete old + record new analysis intent for the analyze page)
- report (read full_states_log_*.json from results_path)

The store is the single source of truth — all reads/writes go through
backend/core/history_store.get_history_store(). This API does NOT modify
business code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.history_store import get_history_store
from backend.core.report_adapter import strip_think_blocks
from backend.models.request import HistoryItem, HistoryResponse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter()

# P2.30 — confirmation token for the destructive ``POST /api/history/purge``
# endpoint. Kept module-level so tests can monkeypatch it without reaching
# into the Pydantic ``Literal`` baked into the request model.
REQUIRED_CONFIRMATION = "CLEAR_ALL_HISTORY"


def _entry_to_item(entry) -> HistoryItem:
    """Convert a HistoryStore entry into the public HistoryItem shape."""
    return HistoryItem(
        analysis_id=entry.analysis_id,
        ticker=entry.ticker,
        trade_date=entry.trade_date,
        signal=entry.signal or None,
        elapsed=entry.elapsed,
        created_at=str(entry.created_at),
        status=entry.status or None,
        error=entry.error,
        completed_stages=entry.completed_stages,
    )


# ── list ────────────────────────────────────────────────────────────────────
@router.get("/api/history", response_model=HistoryResponse)
def list_history(
    limit: int = 20,
    offset: int = 0,
    ticker: str | None = None,
    signal: str | None = None,
    status: str | None = None,
    min_elapsed: float | None = None,
    max_elapsed: float | None = None,
) -> HistoryResponse:
    """List past analyses from the unified history store."""
    store = get_history_store()
    entries, total = store.list_all(
        ticker=ticker,
        signal=signal,
        status=status,
        limit=limit,
        offset=offset,
    )

    # Apply min/max elapsed filter (not supported natively by store yet)
    filtered = entries
    if min_elapsed is not None or max_elapsed is not None:
        filtered = [
            e for e in entries
            if (min_elapsed is None or e.elapsed >= min_elapsed)
            and (max_elapsed is None or e.elapsed <= max_elapsed)
        ]
        total = len(filtered)

    items = [_entry_to_item(e) for e in filtered]

    return HistoryResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ── purge (P2.30) ──────────────────────────────────────────────────────────
#
# Declared BEFORE the dynamic ``/{analysis_id}`` routes below. Starlette
# iterates routes in declaration order, and a literal path under a
# dynamic prefix must be matched as a literal — not as
# ``analysis_id="purge"`` — to avoid the 405 the user hit when the route
# was declared after ``GET /api/history/{analysis_id}``.
class PurgeHistoryRequest(BaseModel):
    """Destructive bulk-cleanup payload.

    ``confirmation`` is a Literal sentinel so a malformed/missing field
    returns the standard Pydantic 422 before the route body ever runs.
    ``include_cache`` defaults to ``False`` — opt-in to also wipe
    ``DEFAULT_CONFIG["data_cache_dir"]``.
    """

    confirmation: Literal["CLEAR_ALL_HISTORY"]
    include_cache: bool = Field(default=False, strict=True)


class PurgeHistoryResponse(BaseModel):
    """Tally returned by ``POST /api/history/purge``.

    No field holds a host filesystem path; the response must not leak
    user home / ``~/.tradingagents/...`` to the client.
    """

    ok: bool
    history_deleted: int
    reports_deleted: int
    log_runs_deleted: int
    cache_files_deleted: int
    bytes_freed: int
    failed_items: int


@router.post(
    "/api/history/purge",
    response_model=PurgeHistoryResponse,
)
def purge_history_endpoint(req: PurgeHistoryRequest) -> PurgeHistoryResponse:
    """Wipe terminal history, per-ticker reports, per-run logs and (opt-in) cache.

    - 422 on missing/wrong confirmation or wrong include_cache type — emitted
      by Pydantic before this body runs.
    - 409 with ``detail.reason == "active_analyses"`` (plus ``active_ids``)
      when any ``pending``/``running`` analysis is still alive in either the
      HistoryStore metadata or the in-memory ``TrackerStore``. Disk is
      untouched on this path.
    - 200 with the per-domain delete tally otherwise.
    """
    # Lazy import — keeps ``backend.api.history`` importable in lightweight
    # tests that never hit the purge endpoint.
    from backend.core.history_cleanup import (
        ActiveAnalysesError,
        purge_history,
    )

    try:
        result = purge_history(include_cache=req.include_cache)
    except ActiveAnalysesError as exc:
        # ``detail`` is a dict so the React Query client can branch on
        # ``reason`` without parsing a free-form string.
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "active_analyses",
                "active_ids": exc.active_ids,
                "active_count": len(exc.active_ids),
            },
        ) from exc

    return PurgeHistoryResponse(
        ok=result.ok,
        history_deleted=result.history_deleted,
        reports_deleted=result.reports_deleted,
        log_runs_deleted=result.log_runs_deleted,
        cache_files_deleted=result.cache_files_deleted,
        bytes_freed=result.bytes_freed,
        failed_items=result.failed_items,
    )


# ── detail ──────────────────────────────────────────────────────────────────
@router.get("/api/history/{analysis_id}")
def get_history(analysis_id: str) -> dict:
    """Return a single history entry (full dict, includes results_path).

    Mirrors streamlit: entry from ~/.tradingagents/logs/history/{id}.json
    read via history_store.get(). 404 if the id is not on disk.
    """
    entry = get_history_store().get(analysis_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"history entry {analysis_id!r} not found")
    payload = entry.to_dict()
    # Surface results_path as a top-level field too for the React detail view.
    return payload


# ── delete ──────────────────────────────────────────────────────────────────
@router.delete("/api/history/{analysis_id}")
def delete_history(analysis_id: str) -> dict:
    """Delete a history entry.

    Idempotent: returns 200 even if the entry did not exist (Streamlit
    behaviour when the user clicks "🗑️" on a stale entry).
    """
    get_history_store().delete(analysis_id)
    return {"ok": True, "analysis_id": analysis_id}


# ── re-run (P2.34 + P2.35) ──────────────────────────────────────────────────
#
# P2.34 hotfix — atomic rerun (§6.9 of DDD_OPERATIONS.md).
#
# The previous implementation did ``store.get()`` → ``store.delete()`` with
# no lock, no status check, and no debounce. Two concurrent clicks could
# race past the check and both create a new analysis; a spam client could
# pile up pending analyses; an in-flight worker could write to the
# deleted entry's analysis_id.
#
# P2.35 hotfix — actually start the analysis. P2.34 only created the new
# history entry; the worker thread was never spawned, so the user saw
# ``status=pending`` forever. The chain now lives in
# :func:`backend.core.rerun_helper.rerun_and_start` which:
#   * delegates the atomic delete + create to ``rerun_analysis`` (P2.34
#     invariant — status guard, debounce, lock-held critical section)
#   * calls ``backend.core.start_analysis`` so a worker thread actually
#     picks up the new analysis and the frontend's progress polls have
#     something to render
#   * cleans up the helper-created stub to avoid a duplicate history
#     entry (``start_analysis`` writes its own keyed by the uuid id)
#
# This endpoint:
#   * maps ``ValueError`` to HTTP 409 — debounce rejection, wrong status,
#     or 404 case
#   * maps ``RuntimeError`` to HTTP 500 — atomic create failure (the
#     helper left the old entry intact, so a retry will succeed once
#     the underlying problem is fixed)
#   * propagates any exception raised by ``start_analysis`` as HTTP 500
#     (the helper stub is left in pending state so the user can retry)
@router.post("/api/history/{analysis_id}/rerun")
def rerun_history(analysis_id: str) -> dict:
    """Atomically rerun a completed/errored analysis AND start it (P2.34+P2.35).

    Returns ``{ok, analysis_id, ticker, trade_date, start_analysis}``
    where ``analysis_id`` is the live id returned by ``start_analysis``
    (a fresh uuid-based id, not the helper-created ``_r<ts>_<hex>``
    stub). The frontend uses ``start_analysis.ticker`` /
    ``start_analysis.trade_date`` for the success toast and polls
    ``/api/analyze/{analysis_id}/progress`` to follow the run.
    """
    from backend.core.rerun_helper import rerun_and_start

    try:
        result = rerun_and_start(analysis_id)
    except ValueError as exc:
        # 409 covers both the debounce window and the "status is
        # pending/running" rejection. The detail string carries the
        # specific reason so the React Query client can branch on
        # the message text.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        # 500: the helper stub could not be created (disk full /
        # permissions / etc). The old entry is left intact by the
        # helper so a retry from the user will succeed once the
        # underlying problem is fixed.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        # 500: start_analysis raised (e.g. ticker format check
        # failed, OpenAI key missing). The helper stub is still
        # in pending state on disk so the user can retry once the
        # underlying problem is fixed. The 60s debounce stays in
        # effect to avoid piling up identical reruns.
        raise HTTPException(
            status_code=500,
            detail=f"start_analysis raised: {exc}",
        ) from exc

    return result


# ── report ──────────────────────────────────────────────────────────────────
@router.get("/api/history/{analysis_id}/report")
def get_history_report(analysis_id: str) -> dict:
    """Return the full report associated with a history entry.

    Reads ``history.entry.results_path`` (full_states_log_*.json) and
    returns it as JSON. Falls back to the legacy ticker/date path if
    results_path is empty — same fallback streamlit uses.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"history entry {analysis_id!r} not found")

    results_path = entry.results_path or ""
    path = Path(results_path) if results_path else None

    if not path or not path.exists():
        # Legacy fallback — streamlit history_panel.py uses the same lookup.
        legacy = (
            Path.home()
            / ".tradingagents"
            / "logs"
            / entry.ticker
            / "TradingAgentsStrategy_logs"
            / f"full_states_log_{entry.trade_date}.json"
        )
        if legacy.exists():
            path = legacy
        else:
            raise HTTPException(
                status_code=404,
                detail=f"report not found for {analysis_id!r} (results_path={results_path!r})",
            )

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to read report: {exc}") from exc

    # P2.31 — drop the LLM's chain-of-thought (<think>...</think>) at the API
    # boundary so the React tab, the PDF exporter, and the Streamlit history
    # view all see the cleaned payload. Pure / non-mutating on `content`.
    content = strip_think_blocks(content)

    return {
        "analysis_id": entry.analysis_id,
        "ticker": entry.ticker,
        "trade_date": entry.trade_date,
        "results_path": str(path),
        "report": content,
    }