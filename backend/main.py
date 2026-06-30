"""FastAPI backend for TradingAgents-Astock mobile API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import analyze_router, progress_router, result_router, history_router, sse_router, batch_router

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