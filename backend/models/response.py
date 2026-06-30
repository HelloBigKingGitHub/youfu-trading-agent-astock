from pydantic import BaseModel


class ReportResult(BaseModel):
    market_report: str | None = None
    sentiment_report: str | None = None
    news_report: str | None = None
    fundamentals_report: str | None = None
    policy_report: str | None = None
    hot_money_report: str | None = None
    lockup_report: str | None = None


class InvestmentDebateState(BaseModel):
    bull_history: str | None = None
    bear_history: str | None = None
    judge_decision: str | None = None


class RiskDebateState(BaseModel):
    aggressive_history: str | None = None
    conservative_history: str | None = None
    neutral_history: str | None = None
    judge_decision: str | None = None


class AnalysisResult(BaseModel):
    analysis_id: str
    status: str
    ticker: str
    trade_date: str
    signal: str | None = None
    reports: ReportResult | None = None
    investment_debate_state: InvestmentDebateState | None = None
    trader_investment_decision: str | None = None
    risk_debate_state: RiskDebateState | None = None
    final_trade_decision: str | None = None
    data_quality_summary: str | None = None
    stats: dict | None = None
    elapsed: float = 0.0
    completed_stages: list[str] = []
    error: str | None = None