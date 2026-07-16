"""FastAPI backend for TradingAgents-Astock mobile API."""

import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env so LLM client factories (tradingagents.*) see provider API keys
# at import / first-call time. web/app.py does the same for streamlit.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
load_dotenv(_PROJECT_ROOT / ".env")

from backend.api import analyze_router, progress_router, result_router, history_router, sse_router, batch_router  # noqa: E402
from backend.api.settings import router as settings_router  # noqa: E402
from backend.api.logs import router as logs_router  # noqa: E402
from backend.api.chart import router as chart_router  # noqa: E402
from backend.api.sector import router as sector_router  # noqa: E402
from backend.api.portfolio import router as portfolio_router  # noqa: E402

app = FastAPI(
    title="TradingAgents-Astock API",
    description="移动端 API — A股多Agent投研框架",
    version="0.1.0",
)

# CORS: allow mobile SPA to call this API. Phase 1 also whitelists the React
# dev server (5173) and the Streamlit UI (8501) so the new frontend can call
# /api/settings during parity validation. Phase 3 will go same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # React dev server
        "http://127.0.0.1:5173",   # React dev server (alt)
        "http://localhost:8501",   # Streamlit UI
        "http://127.0.0.1:8501",   # Streamlit UI (alt)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(analyze_router)
app.include_router(progress_router)
app.include_router(result_router)
app.include_router(history_router)
app.include_router(sse_router)
app.include_router(batch_router)
app.include_router(settings_router, prefix="/api")
app.include_router(logs_router, prefix="/api")
app.include_router(chart_router, prefix="/api")
app.include_router(sector_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "TradingAgents-Astock API", "docs": "/docs"}