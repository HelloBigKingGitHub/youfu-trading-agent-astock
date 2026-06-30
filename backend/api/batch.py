"""Batch analysis endpoints — submit, monitor, and retry batch jobs."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import APIRouter, HTTPException

from backend.core.job_queue import BatchJob, Job, JobQueue, get_job_queue
from backend.core.tracker import get_store
from backend.models.request import AnalyzeRequest
from tradingagents.default_config import DEFAULT_CONFIG

router = APIRouter()

# ── helpers ─────────────────────────────────────────────────────────────────

_STAGE_MAP = {
    "market_report": "market",
    "sentiment_report": "social",
    "news_report": "news",
    "fundamentals_report": "fundamentals",
    "policy_report": "policy",
    "hot_money_report": "hot_money",
    "lockup_report": "lockup",
    "investment_debate_state": "debate",
    "trader_investment_plan": "trader",
    "risk_debate_state": "risk",
    "final_trade_decision": "pm",
}


def _build_config(request: AnalyzeRequest) -> dict[str, Any]:
    config = {**DEFAULT_CONFIG, **{
        "llm_provider": request.llm_provider,
        "deep_think_llm": request.deep_think_llm,
        "quick_think_llm": request.quick_think_llm,
        "max_debate_rounds": 1,
        "output_language": "Chinese",
        "data_vendors": {
            "core_stock_apis": "a_stock",
            "technical_indicators": "a_stock",
            "fundamental_data": "a_stock",
            "news_data": "a_stock",
            "signal_data": "a_stock",
        },
    }}
    if request.backend_url:
        config["backend_url"] = request.backend_url
    return config


def _run_single_job(job: Job, config: dict) -> None:
    """Run a single analysis job in a background thread."""
    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    q = get_job_queue()
    q.start_job(job.job_id)

    try:
        from dotenv import load_dotenv
        env_path = _PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        stats = StatsCallbackHandler()
        graph = TradingAgentsGraph(debug=True, config=config, callbacks=[stats])

        init_state = graph.propagator.create_initial_state(job.ticker, job.trade_date)
        args = graph.propagator.get_graph_args(callbacks=[stats])

        last_chunk: dict = {}

        for chunk in graph.graph.stream(init_state, **args):
            last_chunk = chunk

            for report_key, stage_id in _STAGE_MAP.items():
                content = chunk.get(report_key, "")
                if content:
                    q.update_job_stage(job.job_id, stage_id, str(content)[:500])
                    if job.stage_status(stage_id) != "done":
                        q.update_job_stage(job.job_id, stage_id, str(content)[:500], is_done=True)

            time.sleep(0.5)

        signal = graph.process_signal(last_chunk.get("final_trade_decision", ""))
        q.complete_job(job.job_id, signal, last_chunk)

        graph.ticker = job.ticker
        graph._log_state(job.trade_date, last_chunk)

    except Exception as exc:
        q.error_job(job.job_id, str(exc))


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/api/batch")
def create_batch(items: list[AnalyzeRequest]) -> dict:
    """Submit a batch of analysis jobs."""
    if not items:
        raise HTTPException(status_code=400, detail="Empty batch")
    if len(items) > 50:
        raise HTTPException(status_code=400, detail="Max 50 jobs per batch")

    q = get_job_queue()
    batch_id, batch = q.create_batch([
        {"ticker": req.ticker, "trade_date": req.trade_date} for req in items
    ])

    # Start all jobs in background threads
    for job in batch.jobs:
        req = next(r for r in items if r.ticker == job.ticker and r.trade_date == job.trade_date)
        config = _build_config(req)
        t = threading.Thread(target=_run_single_job, args=(job, config), daemon=True)
        t.start()

    return {
        "batch_id": batch_id,
        "total": len(batch.jobs),
        "jobs": [
            {
                "job_id": j.job_id,
                "ticker": j.ticker,
                "trade_date": j.trade_date,
                "status": j.status,
            }
            for j in batch.jobs
        ],
    }


@router.get("/api/batch/{batch_id}")
def get_batch(batch_id: str) -> dict:
    """Get status of all jobs in a batch."""
    q = get_job_queue()
    batch = q.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {
        "batch_id": batch.batch_id,
        "total": len(batch.jobs),
        "finished_count": batch.finished_count,
        "error_count": batch.error_count,
        "jobs": [j.to_dict() for j in batch.jobs],
    }


@router.get("/api/jobs")
def list_jobs(
    status: str | None = None,
    ticker: str | None = None,
    limit: int = 50,
) -> dict:
    """List all jobs, optionally filtered."""
    q = get_job_queue()
    jobs = q.list_all_jobs()

    if status:
        jobs = [j for j in jobs if j.status == status]
    if ticker:
        jobs = [j for j in jobs if ticker.upper() in j.ticker.upper()]

    jobs.sort(key=lambda j: j.created_at, reverse=True)
    jobs = jobs[:limit]

    return {
        "jobs": [j.to_dict() for j in jobs],
        "total": len(jobs),
    }


@router.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    """Retry a failed or pending job."""
    q = get_job_queue()
    job = q.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "running":
        raise HTTPException(status_code=400, detail="Job already running")

    # Reset job state
    with job._lock:
        job.status = "pending"
        job.error = None
        job.signal = ""
        job.completed_stages = []
        job.stage_reports = {}
        job.current_stage = ""
        job.started_at = None
        job.finished_at = None
        job.created_at = time.time()

    # Get config from session (use default for now)
    req = AnalyzeRequest(ticker=job.ticker, trade_date=job.trade_date)
    config = _build_config(req)

    q._save_job_history(job, "pending")
    t = threading.Thread(target=_run_single_job, args=(job, config), daemon=True)
    t.start()

    return {"job_id": job.job_id, "status": "retrying"}