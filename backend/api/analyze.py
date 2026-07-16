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

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.core import start_analysis
from backend.core.history_store import get_history_store
from backend.models.request import AnalyzeRequest, AnalyzeResponse

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter(prefix="/api")


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

@router.post("/analyze", response_model=AnalyzeResponse, status_code=202)
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

@router.get("/analyze/recent", response_model=List[RecentAnalyzeItem])
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


# ── P2.14 hotfix: POST /api/analyze/{analysis_id}/mark_error ─────────────────

@router.post("/analyze/{analysis_id}/mark_error", status_code=200)
def mark_analysis_error(
    analysis_id: str,
    reason: str = Query("manual cleanup"),
) -> dict:
    """Force-mark a stuck analysis as errored (manual cleanup tool).

    P2.14 hotfix — for cases where the user sees a permanently-running
    analysis (zombie: status=running, elapsed=0, no thread progressing),
    this endpoint lets the React UI offer a one-click cleanup. The
    backend startup hook does the same sweep automatically on restart;
    this is for the live case where a new zombie appears mid-session.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"分析 {analysis_id!r} 不存在",
        )
    store.mark_error(analysis_id, reason, elapsed=entry.elapsed or 0.0)
    return {
        "analysis_id": analysis_id,
        "status": "error",
        "reason": reason,
    }


# ── P2.21 hotfix: POST /api/analyze/{analysis_id}/cancel ──────────────────────

@router.post("/analyze/{analysis_id}/cancel", status_code=200)
def cancel_analysis(analysis_id: str) -> dict:
    """Mark a running analysis as error-cancelled (user-initiated cleanup).

    P2.21 hotfix — the user reported ``600595_2026-07-16_1589cdfd`` was stuck
    for 8.2 hours with no way to stop it from the React UI. This endpoint
    gives the React AnalyzePage a one-click "取消" button that flips the
    history entry to ``error`` so the polling loop stops and the recent list
    no longer shows it as ``running``.

    Important — Python has no safe way to kill a background thread, so this
    does NOT terminate the worker. The thread will eventually finish or
    error out naturally and write its own completion/error status. The
    important effect is on the UI: the entry's status flips to ``error``
    immediately, so the polling interval stops and the recent-list tab
    treats it as done.

    P2.21 hotfix — also accepts an ID from the POST response, even though
    ``tracker_id != history_id`` due to a separate UUID generation in
    TrackerStore.create() vs HistoryStore.create(). If the direct lookup
    misses, we fall back to ``find_by_ticker_date`` for analyses that
    started today and are still running.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        # Fallback: POST /api/analyze returns the TrackerStore analysis_id
        # but the history file uses a freshly generated one from
        # HistoryStore.create() — they don't match. Try to recover by
        # ticker+date for recent running entries.
        if "_" in analysis_id and analysis_id.count("_") >= 2:
            parts = analysis_id.rsplit("_", 2)
            if len(parts) == 3:
                ticker, trade_date, _uid = parts
                recent = store.find_by_ticker_date(ticker, trade_date)
                if recent and recent.status in ("running", "pending"):
                    entry = recent
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"分析 {analysis_id!r} 不存在",
        )
    if entry.status not in ("running", "pending"):
        # 409 — only running/pending can be cancelled. Already-finished
        # entries are immutable from the user's perspective.
        raise HTTPException(
            status_code=409,
            detail=f"分析状态是 {entry.status}, 不可取消",
        )

    reason = "用户手动取消"
    store.mark_error(entry.analysis_id, reason, elapsed=entry.elapsed or 0.0)

    logger.warning(
        f"Analysis {entry.analysis_id} cancelled by user (thread still running, "
        f"elapsed={entry.elapsed:.1f}s)"
    )
    return {
        "analysis_id": entry.analysis_id,
        "status": "error",
        "reason": reason,
    }


# ── GET /api/analyze/{analysis_id}/report ────────────────────────────────────

@router.get("/analyze/{analysis_id}/report", response_model=AnalyzeReport)
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