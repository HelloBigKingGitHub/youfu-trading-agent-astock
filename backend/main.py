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
from backend.core.history_store_read_routing import DualReadHistoryStore  # noqa: E402
from backend.core.log_store_read_routing import DualReadLogStore  # noqa: E402
from backend.core.write_routing import is_single_write_sqlite  # noqa: E402
from backend.core.history_store_singlewrite import SingleWriteHistoryStore  # noqa: E402
from backend.core.log_store_singlewrite import (  # noqa: E402
    SingleWriteLogStore,
    SingleWriteLogWriter,
)
from backend.core import log_store as log_module  # noqa: E402

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
    """Install the Phase 3c JSONL + SQLite log wrapper (idempotent).

    The underlying ``enable_log_dual_write()`` raises ``RuntimeError`` when
    a ``DualWriteLogStore`` is already installed — that guard exists to
    catch accidental double-bootstrap.  But the lifespan legitimately
    reaches ``_enable_log_dual_write()`` twice in the same run whenever
    ``DUAL_WRITE_LOGS=1`` and ``READ_FROM_SQLITE=1`` (or
    ``SINGLE_WRITE_SQLITE=1``) are all set: Phase 3c installs first, then
    the Phase 4 / Phase 5b branches re-enter the helper.  The runtime
    raise would abort lifespan startup before ``cleanup_zombies`` /
    Phase 5b can run.  We short-circuit in main.py (Phase 5b P5b hotfix)
    rather than touch the protected ``log_store_dualwrite_runtime``
    module — keeps the bootstrap-order invariant intact while making the
    lifespan call idempotent.
    """
    from backend.core.log_store_dualwrite import DualWriteLogStore

    current = log_module.get_log_store()
    if isinstance(current, DualWriteLogStore):
        logger.warning(
            "LogStore dual-write already enabled — idempotent reuse (P5b hotfix)"
        )
        return _noop_dual_write_runtime(current)
    return enable_log_dual_write()


def _noop_dual_write_runtime(current):
    """Stand-in ``DualWriteLogRuntime`` for the idempotent short-circuit.

    Holds the existing ``DualWriteLogStore`` instance so the lifespan
    ``close()`` path can call ``.close()`` on it without re-patching any
    bindings.  Closing the already-running dual-write singleton is a
    no-op for Phase 3c (its ``close()`` only tears down its own
    sidecar, not the JSON store), so this is safe across the lifespan
    yield.
    """
    from backend.core.log_store_dualwrite_runtime import DualWriteLogRuntime

    class _IdempotentRuntime(DualWriteLogRuntime):
        def __init__(self, dual_store):
            # Pass the existing DualWriteLogStore as the dual_store; record
            # the original singletons it already replaced so close() can
            # restore them — but close() is never expected to fire on the
            # lifespan shutdown path in P5b.
            self._log_module = log_module
            self._runner_module = None
            self._web_runner_module = None
            self._original_singleton = log_module._log_store_singleton
            self._original_log_writer = log_module.LogWriter
            self._original_web_writer = None
            self._dual_store = dual_store

        def close(self):
            # Idempotent: the bootstrap already finished — leave the
            # singleton alone so subsequent Phase 4/5b logic can see the
            # wrapped DualWriteLogStore on yield.
            return None

    return _IdempotentRuntime(current)


def _enable_read_routing() -> ReadRoutingRuntime:
    """Phase 4: route reads to the SQLite sidecar; writes stay JSON/JSONL."""
    return enable_read_routing()


def _enable_single_write() -> None:
    """Phase 5b: route writes to SQLite-only; JSON/JSONL is observe-only.

    Requires Phase 4 ``READ_FROM_SQLITE=1`` to be set first (or we
    force it on) so the SQLite sidecar is populated by the same
    wrappers Phase 4 already installs.  Layering pattern:

      Phase 3b/3c (DualWrite)            ─┐
                                          ├── Phase 4 DualRead wraps these
      Phase 5b SingleWrite ───────────────┘
        (replaces Phase 4 DualRead wrappers in-place so writes stop
        hitting JSON/JSONL but reads still come from SQLite)

    The P5b layer mutates the singletons installed by
    ``enable_read_routing()`` rather than building fresh sidecars —
    this keeps the SQLite connection shared and matches the lifecycle
    pattern in Phase 3c/4 bootstrap seams.
    """
    import importlib

    from backend.core import history_store as history_module
    from backend.core import log_store as log_module
    from backend.core.history_store import get_history_store
    from backend.core.history_store_sqlite import SQLiteHistoryStore

    current_history = get_history_store()
    # Find the SQLite sidecar (Phase 4 wraps it as _sqlite on DualRead).
    sqlite_history: SQLiteHistoryStore | None = None
    if hasattr(current_history, "_sqlite") and isinstance(
        current_history._sqlite, SQLiteHistoryStore  # type: ignore[attr-defined]
    ):
        sqlite_history = current_history._sqlite  # type: ignore[attr-defined]
    if sqlite_history is None:
        # No SQLite sidecar — create one.  This makes ``SINGLE_WRITE_SQLITE=1``
        # independently usable without requiring ``READ_FROM_SQLITE=1`` first.
        sqlite_history = SQLiteHistoryStore()

    # Phase 5b never touches the JSON writer; keep a reference for symmetry.
    json_history = current_history
    if hasattr(json_history, "_writer"):
        json_history = json_history._writer  # type: ignore[attr-defined]
    single_history = SingleWriteHistoryStore(json_history, sqlite_history)
    history_module.HistoryStore._instance = single_history

    # ── LogStore side ─────────────────────────────────────────────────
    current_log = log_module.get_log_store()
    from backend.core.log_store_sqlite import SQLiteLogStore, SQLiteLogWriter

    sqlite_log: SQLiteLogStore | None = None
    if hasattr(current_log, "_sqlite") and isinstance(
        current_log._sqlite, SQLiteLogStore  # type: ignore[attr-defined]
    ):
        sqlite_log = current_log._sqlite  # type: ignore[attr-defined]
    if sqlite_log is None:
        sqlite_log = SQLiteLogStore()

    single_log = SingleWriteLogStore(current_log, sqlite_log)
    log_module._log_store_singleton = single_log

    # Capture the db_path for the LogWriter factory so each new writer
    # opens against the same database the singleton reads from.
    sqlite_log_db_path = sqlite_log.db

    # ── LogWriter factory ─────────────────────────────────────────────
    # ``web.runner`` imports ``LogWriter`` directly at module import time,
    # so we must patch that binding explicitly.  The factory delegates to
    # SQLiteLogWriter only — no JSONL write sidecar.  Same patching
    # pattern as Phase 3c/4 bootstraps.
    web_runner_module = importlib.import_module("web.runner")

    def single_write_log_writer_factory(
        analysis_id: str, ticker: str, trade_date: str
    ):
        sqlite_log_writer = SQLiteLogWriter(
            analysis_id,
            ticker,
            trade_date,
            db_path=sqlite_log_db_path,
        )
        return SingleWriteLogWriter(
            analysis_id,
            ticker,
            trade_date,
            json_writer=None,
            sqlite_writer=sqlite_log_writer,
        )

    log_module.LogWriter = single_write_log_writer_factory
    if web_runner_module is not None:
        web_runner_module.LogWriter = single_write_log_writer_factory

    logger.warning(
        "Phase 5b SINGLE WRITE: writes go to SQLite only; JSON/JSONL is observe-only"
    )


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
        # Phase 5b — single-write cutover.  Defaults to off; the user
        # must explicitly opt in once the 1-week observation window
        # (Phase 4 cutover) completes.  Forces READ_FROM_SQLITE=1 +
        # dual-write so the SQLite sidecar stays consistent with the
        # bootstrap order, then layers SingleWrite on top so JSON /
        # JSONL writes are dropped.
        if is_single_write_sqlite():
            os.environ.setdefault("READ_FROM_SQLITE", "1")
            os.environ.setdefault("DUAL_WRITE_HISTORY", "1")
            os.environ.setdefault("DUAL_WRITE_LOGS", "1")
            if not isinstance(get_history_store(), DualReadHistoryStore):
                _enable_history_dual_write()
            if not isinstance(log_module.get_log_store(), DualReadLogStore):
                log_runtime = _enable_log_dual_write()
                read_runtime = _enable_read_routing()
            _enable_single_write()
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