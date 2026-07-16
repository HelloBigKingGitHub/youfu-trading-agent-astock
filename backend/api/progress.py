"""GET /api/analyze/{analysis_id}/progress — poll analysis progress.

P2.11 hotfix: fall back to ``HistoryStore`` when ``TrackerStore`` (in-memory)
loses the analysis on backend restart. Without this, the React AnalyzePage
"progress" tab returns 404 for any analysis_id that was created before the
last uvicorn restart — even though ``/api/analyze/recent`` still lists it from
the persistent JSON history.
"""

from fastapi import APIRouter, HTTPException

from backend.core import get_store
from backend.core.history_store import get_history_store
from backend.models.request import ProgressResponse

router = APIRouter()


@router.get("/api/analyze/{analysis_id}/progress", response_model=ProgressResponse)
def get_progress(analysis_id: str) -> ProgressResponse:
    """Poll the current progress of an analysis.

    Looks up the live ``AnalysisTracker`` first (most up-to-date for
    in-flight analyses), then falls back to the persistent ``HistoryEntry``
    for analyses that completed before the last backend restart.
    """
    store = get_store()
    tracker = store.get(analysis_id)

    if tracker is not None:
        data = tracker.to_progress_dict()
        return ProgressResponse(
            status=data["status"],
            ticker=data["ticker"],
            trade_date=data["trade_date"],
            current_stage=data.get("current_stage"),
            completed_stages=data.get("completed_stages", []),
            stage_reports=data.get("stage_reports", {}),
            stats=data.get("stats"),
            elapsed=data.get("elapsed", 0.0),
            signal=data.get("signal"),
            error=data.get("error"),
        )

    # P2.11 fallback: TrackerStore is in-memory and loses data on restart.
    # HistoryStore is JSON-backed and survives restarts.
    history = get_history_store()
    entry = history.get(analysis_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"分析 {analysis_id!r} 不存在或已过期, "
                "请从历史列表选择新分析"
            ),
        )

    stats = {
        "llm_calls": 0,
        "tool_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
    }

    return ProgressResponse(
        status=entry.status or "complete",
        ticker=entry.ticker,
        trade_date=entry.trade_date,
        current_stage=None,
        completed_stages=entry.completed_stages or [],
        stage_reports=entry.stage_reports or {},
        stats=stats,
        elapsed=float(entry.elapsed or 0.0),
        signal=entry.signal or None,
        error=entry.error,
    )