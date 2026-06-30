"""GET /api/history — unified history API using history_store."""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.history_store import get_history_store
from backend.models.request import HistoryItem, HistoryResponse

router = APIRouter()


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

    items = [
        HistoryItem(
            analysis_id=e.analysis_id,
            ticker=e.ticker,
            trade_date=e.trade_date,
            signal=e.signal or None,
            elapsed=e.elapsed,
            created_at=str(e.created_at),
            status=e.status or None,
            error=e.error,
            completed_stages=e.completed_stages,
        )
        for e in filtered
    ]

    return HistoryResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/api/history/{analysis_id}")
def delete_history(analysis_id: str) -> dict:
    """Delete a history entry."""
    get_history_store().delete(analysis_id)
    return {"ok": True}