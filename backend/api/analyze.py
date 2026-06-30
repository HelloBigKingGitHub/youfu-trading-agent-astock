"""POST /api/analyze — start a new analysis."""

from fastapi import APIRouter, HTTPException

from backend.core import start_analysis
from backend.models.request import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


@router.post("/api/analyze", response_model=AnalyzeResponse, status_code=202)
def create_analysis(request: AnalyzeRequest) -> AnalyzeResponse:
    """Start a new stock analysis. Returns immediately with analysis_id."""
    try:
        analysis_id, tracker = start_analysis(request)
        return AnalyzeResponse(
            analysis_id=analysis_id,
            status="started",
            ticker=request.ticker,
            trade_date=request.trade_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc