"""GET /api/analyze/{analysis_id} — get full analysis result.

P2.11 hotfix: fall back to ``HistoryStore`` when ``TrackerStore`` (in-memory)
loses the analysis on backend restart. Without this, the React AnalyzePage
"result" tab returns 404 for any analysis_id that was created before the
last uvicorn restart.
"""

from fastapi import APIRouter, HTTPException

from backend.core import get_store
from backend.core.history_store import get_history_store
from backend.models.response import (
    AnalysisResult,
    InvestmentDebateState,
    ReportResult,
    RiskDebateState,
)

router = APIRouter()


@router.get("/api/analyze/{analysis_id}", response_model=AnalysisResult)
def get_result(analysis_id: str) -> AnalysisResult:
    """Get the full analysis result after completion.

    Looks up the live ``AnalysisTracker`` first (carries the full LangGraph
    ``final_state`` for in-flight or just-completed analyses), then falls
    back to the persistent ``HistoryEntry`` for analyses that completed
    before the last backend restart.
    """
    store = get_store()
    tracker = store.get(analysis_id)

    if tracker is not None:
        state = tracker.final_state

        reports = None
        if state:
            reports = ReportResult(
                market_report=state.get("market_report"),
                sentiment_report=state.get("sentiment_report"),
                news_report=state.get("news_report"),
                fundamentals_report=state.get("fundamentals_report"),
                policy_report=state.get("policy_report"),
                hot_money_report=state.get("hot_money_report"),
                lockup_report=state.get("lockup_report"),
            )

        inv_debate = None
        if state and state.get("investment_debate_state"):
            ds = state["investment_debate_state"]
            inv_debate = InvestmentDebateState(
                bull_history=ds.get("bull_history"),
                bear_history=ds.get("bear_history"),
                judge_decision=ds.get("judge_decision"),
            )

        risk_debate = None
        if state and state.get("risk_debate_state"):
            rs = state["risk_debate_state"]
            risk_debate = RiskDebateState(
                aggressive_history=rs.get("aggressive_history"),
                conservative_history=rs.get("conservative_history"),
                neutral_history=rs.get("neutral_history"),
                judge_decision=rs.get("judge_decision"),
            )

        status = (
            "error" if tracker.error
            else "complete" if tracker.is_complete
            else "running"
        )

        return AnalysisResult(
            analysis_id=analysis_id,
            status=status,
            ticker=tracker.ticker,
            trade_date=tracker.trade_date,
            signal=tracker.signal,
            reports=reports,
            investment_debate_state=inv_debate,
            trader_investment_decision=(
                state.get("trader_investment_plan") if state else None
            ),
            risk_debate_state=risk_debate,
            final_trade_decision=(
                state.get("final_trade_decision") if state else None
            ),
            data_quality_summary=(
                state.get("data_quality_summary") if state else None
            ),
            stats={
                "llm_calls": tracker.llm_calls,
                "tool_calls": tracker.tool_calls,
                "tokens_in": tracker.tokens_in,
                "tokens_out": tracker.tokens_out,
            },
            elapsed=tracker.elapsed,
            completed_stages=list(tracker.completed_stages),
            error=tracker.error,
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

    return AnalysisResult(
        analysis_id=analysis_id,
        status=entry.status or "complete",
        ticker=entry.ticker,
        trade_date=entry.trade_date,
        signal=entry.signal or None,
        reports=None,
        investment_debate_state=None,
        trader_investment_decision=None,
        risk_debate_state=None,
        final_trade_decision=None,
        data_quality_summary=None,
        stats={
            "llm_calls": 0,
            "tool_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        },
        elapsed=float(entry.elapsed or 0.0),
        completed_stages=entry.completed_stages or [],
        error=entry.error,
    )