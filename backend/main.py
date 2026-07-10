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

app = FastAPI(
    title="TradingAgents-Astock API",
    description="移动端 API — A股多Agent投研框架",
    version="0.1.0",
)

# CORS: allow mobile SPA to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "TradingAgents-Astock API", "docs": "/docs"}