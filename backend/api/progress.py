"""GET /api/analyze/{analysis_id}/progress — poll analysis progress."""

from fastapi import APIRouter, HTTPException

from backend.core import get_store
from backend.models.request import ProgressResponse

router = APIRouter()


@router.get("/api/analyze/{analysis_id}/progress", response_model=ProgressResponse)
def get_progress(analysis_id: str) -> ProgressResponse:
    """Poll the current progress of an analysis."""
    store = get_store()
    tracker = store.get(analysis_id)

    if tracker is None:
        raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found")

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