"""GET /api/analyze/{analysis_id} — get full analysis result."""

from fastapi import APIRouter, HTTPException

from backend.core import get_store
from backend.models.response import (
    AnalysisResult,
    InvestmentDebateState,
    ReportResult,
    RiskDebateState,
)

router = APIRouter()


@router.get("/api/analyze/{analysis_id}", response_model=AnalysisResult)
def get_result(analysis_id: str) -> AnalysisResult:
    """Get the full analysis result after completion."""
    store = get_store()
    tracker = store.get(analysis_id)

    if tracker is None:
        raise HTTPException(status_code=404, detail=f"Analysis '{analysis_id}' not found")

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

    status = "error" if tracker.error else ("complete" if tracker.is_complete else "running")

    return AnalysisResult(
        analysis_id=analysis_id,
        status=status,
        ticker=tracker.ticker,
        trade_date=tracker.trade_date,
        signal=tracker.signal,
        reports=reports,
        investment_debate_state=inv_debate,
        trader_investment_decision=state.get("trader_investment_plan") if state else None,
        risk_debate_state=risk_debate,
        final_trade_decision=state.get("final_trade_decision") if state else None,
        data_quality_summary=state.get("data_quality_summary") if state else None,
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