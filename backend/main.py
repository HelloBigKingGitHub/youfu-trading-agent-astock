"""FastAPI backend for TradingAgents-Astock mobile API."""

import logging
import os
import sys
from contextlib import asynccontextmanager
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
from backend.api.schedule import router as schedule_router  # noqa: E402

from backend.core.history_store import HistoryStore, get_history_store  # noqa: E402
from backend.core.history_store_dualwrite import DualWriteHistoryStore  # noqa: E402
from backend.core.history_store_sqlite import SQLiteHistoryStore  # noqa: E402
from backend.core.log_store_dualwrite_runtime import (  # noqa: E402
    DualWriteLogRuntime,
    enable_log_dual_write,
)
from backend.core.read_routing import (  # noqa: E402
    ReadRoutingRuntime,
    enable_read_routing,
)

logger = logging.getLogger("backend.main")
# Uvicorn's default logging config leaves application loggers at WARNING.
# Keep this lifecycle notice visible at startup without changing root logging.
logger.setLevel(logging.INFO)


def _enable_history_dual_write() -> DualWriteHistoryStore:
    """Install the Phase 3b wrapper without changing JSON callers."""
    current = get_history_store()
    if isinstance(current, DualWriteHistoryStore):
        return current

    dual_store = DualWriteHistoryStore(current, SQLiteHistoryStore())
    # ``get_history_store`` delegates to HistoryStore.get_instance(), so the
    # class singleton—not a module-level attribute—must be replaced here.
    HistoryStore._instance = dual_store
    logger.warning("HistoryStore dual-write enabled (JSON + SQLite)")
    return dual_store


def _enable_log_dual_write() -> DualWriteLogRuntime:
    """Install the Phase 3c JSONL + SQLite log wrapper."""
    return enable_log_dual_write()


def _enable_read_routing() -> ReadRoutingRuntime:
    """Phase 4: route reads to the SQLite sidecar; writes stay JSON/JSONL."""
    return enable_read_routing()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI lifespan: cleanup zombie analyses on startup.

    P2.14 hotfix — when uvicorn is restarted (SIGKILL of the old PID),
    any worker thread that was mid-analysis dies, but the history.json
    file persists with status=running / elapsed=0 / stages=[]. No thread
    ever picks it back up, so the recent-list UI shows a permanently-
    stuck entry. On every startup we sweep these and mark them error so
    the UI stays clean. Idempotent — a fresh store has no zombies.
    """
    log_runtime: DualWriteLogRuntime | None = None
    read_runtime: ReadRoutingRuntime | None = None
    try:
        if os.environ.get("DUAL_WRITE_LOGS", "0") == "1":
            log_runtime = _enable_log_dual_write()
        if os.environ.get("DUAL_WRITE_HISTORY", "0") == "1":
            _enable_history_dual_write()
        # Phase 4 — flip reads to SQLite.  Defaults to off so a uvicorn
        # restart does not silently change behaviour.  Dual-write flags
        # P2.32 hotfix — READ_FROM_SQLITE=1 must also enable writes to SQLite,
        # otherwise new analyses only land in JSON/JSONL and the read-side
        # SQLite-sidecar returns [] — the user sees an empty history while
        # the JSON files still exist. Force dual-write flags on when reads
        # are routed, so the SQLite sidecar stays consistent with disk.
        if os.environ.get("READ_FROM_SQLITE", "0") == "1":
            os.environ.setdefault("DUAL_WRITE_HISTORY", "1")
            os.environ.setdefault("DUAL_WRITE_LOGS", "1")
            _enable_history_dual_write()
            log_runtime = _enable_log_dual_write()
            read_runtime = _enable_read_routing()
        store = get_history_store()
        cleaned = store.cleanup_zombies()
        if cleaned:
            logger.warning(
                "P2.14 startup: marked %d zombie analyses as error: %s",
                len(cleaned),
                ", ".join(cleaned[:10]) + ("…" if len(cleaned) > 10 else ""),
            )
        else:
            logger.info("P2.14 startup: no zombie analyses to clean")
        # Phase 3d — TTL auto-cleanup. Opt-in via SQLITE_AUTO_CLEANUP=1 so
        # cron-less prod deploys can still bound the DB.  Always
        # non-fatal: a failure here must never block uvicorn startup.
        if os.environ.get("SQLITE_AUTO_CLEANUP", "0") == "1":
            try:
                from backend.core.sqlite_cleanup import cleaner_from_env

                _auto_cleaner = cleaner_from_env()
                _auto_stats = _auto_cleaner.cleanup_all()
                _auto_cleaner.close()
                logger.warning(
                    "SQLite auto-cleanup: deleted %d history + %d log_chunks, freed %d bytes",
                    _auto_stats.history_deleted,
                    _auto_stats.log_chunks_deleted,
                    _auto_stats.bytes_freed,
                )
            except Exception as _auto_exc:  # pragma: no cover — never block startup
                logger.warning("SQLite auto-cleanup failed (non-fatal): %s", _auto_exc)
    except Exception as exc:  # pragma: no cover — never block startup
        logger.exception("P2.14 zombie cleanup failed (non-fatal): %s", exc)
    yield
    if log_runtime is not None:
        log_runtime.close()
    if read_runtime is not None:
        read_runtime.close()


app = FastAPI(
    title="TradingAgents-Astock API",
    description="移动端 API — A股多Agent投研框架",
    version="0.1.0",
    lifespan=lifespan,
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
app.include_router(schedule_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "TradingAgents-Astock API", "docs": "/docs"}