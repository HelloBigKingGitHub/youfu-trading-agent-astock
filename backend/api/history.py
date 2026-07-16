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

from fastapi import APIRouter, HTTPException

from backend.core.history_store import get_history_store
from backend.models.request import HistoryItem, HistoryResponse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter()


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


# ── re-run ──────────────────────────────────────────────────────────────────
@router.post("/api/history/{analysis_id}/rerun")
def rerun_history(analysis_id: str) -> dict:
    """Mark an entry for re-analysis.

    Mirrors streamlit: deletes the old entry and returns a payload the
    frontend (or the legacy analyze page) can use to start a fresh run.
    The actual analysis is initiated by the existing analyze endpoint;
    this route is the "delete + intent" half, kept tiny on purpose so the
    store stays the single source of truth.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"history entry {analysis_id!r} not found")
    payload = {
        "ticker": entry.ticker,
        "trade_date": entry.trade_date,
    }
    store.delete(analysis_id)
    return {"ok": True, "start_analysis": payload, "analysis_id": analysis_id}


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

    return {
        "analysis_id": entry.analysis_id,
        "ticker": entry.ticker,
        "trade_date": entry.trade_date,
        "results_path": str(path),
        "report": content,
    }