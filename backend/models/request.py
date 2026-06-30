from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    ticker: str
    trade_date: str
    llm_provider: str = "minimax"
    quick_think_llm: str = "MiniMax-M2.7-highspeed"
    deep_think_llm: str = "MiniMax-M2.7"
    backend_url: str | None = None


class AnalyzeResponse(BaseModel):
    analysis_id: str
    status: str
    ticker: str
    trade_date: str


class ProgressStats(BaseModel):
    llm_calls: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class ProgressResponse(BaseModel):
    status: str
    ticker: str
    trade_date: str
    current_stage: str | None = None
    completed_stages: list[str] = []
    stage_reports: dict[str, str] = {}
    stats: ProgressStats = ProgressStats()
    elapsed: float = 0.0
    signal: str | None = None
    error: str | None = None


class HistoryItem(BaseModel):
    analysis_id: str
    ticker: str
    trade_date: str
    signal: str | None = None
    elapsed: float = 0.0
    created_at: str = ""
    status: str | None = None
    error: str | None = None
    completed_stages: list[str] = []


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int
    limit: int
    offset: int