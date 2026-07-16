"""POST /api/analyze — start a new analysis.
GET  /api/analyze/recent — list most-recent N analyses (canonical for React recent tab).
GET  /api/analyze/{analysis_id}/report — read the full_states_log_*.json report.

Mirrors ``web/components/history_panel.py`` for list/report parity.  All
business code lives in ``backend.core.start_analysis`` / ``tracker`` /
``history_store`` — this module is the FastAPI surface only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.core import start_analysis
from backend.core.history_store import get_history_store
from backend.models.request import AnalyzeRequest, AnalyzeResponse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter()


# ── shared response models for new endpoints ─────────────────────────────────

class RecentAnalyzeItem(BaseModel):
    """One recent analysis row — mirrors the Streamlit history_panel.py list
    shape so React can consume it 1:1 with /api/history."""
    analysis_id: str
    ticker: str
    trade_date: str
    signal: str | None = None
    elapsed: float = 0.0
    created_at: str = ""
    status: str | None = None
    error: str | None = None
    completed_stages: list[str] = []


class AnalyzeReport(BaseModel):
    """Full report payload — mirrors history.py ``get_history_report``."""
    analysis_id: str
    ticker: str
    trade_date: str
    results_path: str
    report: dict | None = None


def _entry_to_item(entry) -> RecentAnalyzeItem:
    return RecentAnalyzeItem(
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


# ── POST /api/analyze ────────────────────────────────────────────────────────

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


# ── GET /api/analyze/recent ──────────────────────────────────────────────────

@router.get("/api/analyze/recent", response_model=List[RecentAnalyzeItem])
def list_recent_analyzes(
    limit: int = Query(20, ge=1, le=100),
) -> List[RecentAnalyzeItem]:
    """List most-recent N analyses (newest first) from the history store.

    Mirrors ``history.py::list_history`` but is the dedicated analyze-page
    recent-list endpoint — the React ``AnalyzePage`` uses it as its default
    tab data source so the list refreshes as soon as ``POST /api/analyze``
    writes a new entry to ``backend.core.history_store``.
    """
    store = get_history_store()
    entries, _total = store.list_all(limit=limit, offset=0)
    return [_entry_to_item(e) for e in entries]


# ── GET /api/analyze/{analysis_id}/report ────────────────────────────────────

@router.get("/api/analyze/{analysis_id}/report", response_model=AnalyzeReport)
def get_analyze_report(analysis_id: str) -> AnalyzeReport:
    """Return the full report for a past analysis.

    Reads ``history.entry.results_path`` (full_states_log_*.json) and returns
    it as JSON. Falls back to the legacy ticker/date path if results_path is
    empty — same fallback ``history.py::get_history_report`` uses.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        # P2.10 hotfix: friendlier 404 — React Query may hold a stale
        # analysis_id from an old session; explain in user-facing Chinese so
        # the AnalyzePage can render a banner + offer "go back to history".
        raise HTTPException(
            status_code=404,
            detail=(
                f"分析 {analysis_id!r} 不存在或已过期, "
                "请从历史列表选择新分析"
            ),
        )

    results_path = entry.results_path or ""
    path = Path(results_path) if results_path else None

    if not path or not path.exists():
        # Legacy fallback — mirrors history.py.
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
                detail=(
                    f"分析 {analysis_id!r} 的报告文件丢失 "
                    f"(results_path={results_path!r}), 请重跑该分析"
                ),
            )

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"failed to read report: {exc}"
        ) from exc

    return AnalyzeReport(
        analysis_id=entry.analysis_id,
        ticker=entry.ticker,
        trade_date=entry.trade_date,
        results_path=str(path),
        report=content if isinstance(content, dict) else {"raw": content},
    )