"""GET /api/logs — read-only access to the per-task LangGraph log store.

Mirrors web/components/logs_panel.py 1:1:
- list tickers that have any log (new or legacy)
- list tasks for a ticker
- read a single task's meta + chunk counts
- stream raw chunks from the per-task jsonl files
- count chunks per ticker / per task

The store is the single source of truth — all reads go through
backend/core/log_store.get_log_store(). This API does NOT modify the
business layer (no writes — those still come from web/runner.py via
LogWriter). Phase 2.3 of P2.3.P1 — the third page to come online after
Settings and History.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.core.log_store import get_log_store

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter()


def _safe_segment(value: str, *, label: str) -> str:
    """Reject path traversal and any character that could escape the logs dir.

    Mirrors the Streamlit panel's `st.session_state["logs_selected_ticker"]`
    contract: the ticker is a 6-digit code, but `task` is a `date_runNN` folder
    name. Both are passed as URL query params on this API; we reject anything
    that contains '/', '\\', '..' or a NUL byte.
    """
    if not value:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    if "/" in value or "\\" in value or ".." in value or "\x00" in value:
        raise HTTPException(
            status_code=400,
            detail=f"invalid {label}: must not contain '/', '\\\\', '..', or NUL",
        )
    return value


# ── list tickers ────────────────────────────────────────────────────────────
@router.get("/logs/tickers")
def list_tickers() -> dict[str, Any]:
    """Return the tickers that have at least one log (new or legacy).

    Mirrors `LogStore.list_tickers()` but exposes the count of tasks per
    ticker so the React ticker-card can show "N runs" without a second
    round-trip.  The store's internal sort is by most-recent mtime desc.
    """
    store = get_log_store()
    tickers = store.list_tickers()
    payload = []
    for ticker in tickers:
        tasks = store.list_tasks(ticker)
        latest = tasks[0] if tasks else None
        payload.append({
            "ticker": ticker,
            "task_count": len(tasks),
            "latest_signal": latest.signal if latest else "",
            "latest_status": latest.status if latest else "",
            "latest_trade_date": latest.trade_date if latest else "",
        })
    return {"tickers": payload, "total": len(payload)}


# ── list tasks ──────────────────────────────────────────────────────────────
@router.get("/logs/tasks")
def list_tasks(ticker: str) -> dict[str, Any]:
    """Return the tasks for one ticker (sorted by started_at desc)."""
    ticker = _safe_segment(ticker, label="ticker")
    store = get_log_store()
    tasks = store.list_tasks(ticker)
    if not tasks:
        # Distinguish "ticker doesn't exist" (404) from "ticker exists but
        # has no tasks" (200 with empty list).  Streamlit's panel does the
        # same implicit check via `if not tickers: return st.info(...)`.
        if ticker not in store.list_tickers():
            raise HTTPException(status_code=404, detail=f"no logs for ticker {ticker!r}")
    payload = [
        {
            "analysis_id": t.analysis_id,
            "ticker": t.ticker,
            "trade_date": t.trade_date,
            "task_dir_name": t.task_dir_name,
            "status": t.status,
            "signal": t.signal,
            "elapsed_sec": t.elapsed_sec,
            "started_at": t.started_at,
            "finished_at": t.finished_at,
            "chunk_counts": t.chunk_counts,
            "is_legacy": t.is_legacy,
        }
        for t in tasks
    ]
    return {"ticker": ticker, "tasks": payload, "total": len(payload)}


# ── single task meta ────────────────────────────────────────────────────────
@router.get("/logs/task")
def get_task(ticker: str, task: str) -> dict[str, Any]:
    """Return the meta.json for a single task (or legacy fallback)."""
    ticker = _safe_segment(ticker, label="ticker")
    task = _safe_segment(task, label="task")
    store = get_log_store()
    try:
        meta = store.get_meta(ticker, task)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    counts = store.count_chunks(ticker, task)
    return {"meta": meta, "chunk_counts": counts, "ticker": ticker, "task": task}


# ── chunks ──────────────────────────────────────────────────────────────────
@router.get("/logs/chunks")
def get_chunks(
    ticker: str,
    task: str,
    type: str | None = None,
) -> dict[str, Any]:
    """Return the raw chunks for a task, optionally filtered by type.

    type: None=全部, 'llm'/'tool'/'agent_output'=只返回该类型.
    """
    ticker = _safe_segment(ticker, label="ticker")
    task = _safe_segment(task, label="task")
    if type is not None and type not in ("llm", "tool", "agent_output"):
        raise HTTPException(
            status_code=400,
            detail=f"invalid type {type!r} (expected llm/tool/agent_output)",
        )
    store = get_log_store()
    chunks = [c.to_dict() for c in store.stream_chunks(ticker, task, type_filter=type)]
    counts: dict[str, int] = {}
    for c in chunks:
        counts[c.get("type", "unknown")] = counts.get(c.get("type", "unknown"), 0) + 1
    return {
        "ticker": ticker,
        "task": task,
        "type": type,
        "chunks": chunks,
        "total": len(chunks),
        "counts": counts,
    }


# ── counts (lightweight, per-ticker or per-task) ─────────────────────────────
@router.get("/logs/counts")
def get_counts(ticker: str | None = None, task: str | None = None) -> dict[str, Any]:
    """Return chunk counts. With only `ticker`, sum across all its tasks.

    Used by the React ticker-card to show "LLM X · Tool Y · Output Z" without
    loading every task's jsonl.
    """
    store = get_log_store()
    if ticker is not None:
        ticker = _safe_segment(ticker, label="ticker")
        tasks = store.list_tasks(ticker)
        if task is not None:
            task = _safe_segment(task, label="task")
            return {
                "ticker": ticker,
                "task": task,
                "counts": store.count_chunks(ticker, task),
            }
        total = {"llm": 0, "tool": 0, "agent_output": 0}
        for t in tasks:
            cc = t.chunk_counts or {"llm": 0, "tool": 0, "agent_output": 0}
            for k in total:
                total[k] += cc.get(k, 0)
        return {"ticker": ticker, "counts": total}
    # No ticker → counts per ticker across the whole store
    tickers = store.list_tickers()
    out: dict[str, dict[str, int]] = {}
    grand = {"llm": 0, "tool": 0, "agent_output": 0}
    for tk in tickers:
        tasks = store.list_tasks(tk)
        per = {"llm": 0, "tool": 0, "agent_output": 0}
        for t in tasks:
            cc = t.chunk_counts or {"llm": 0, "tool": 0, "agent_output": 0}
            for k in per:
                per[k] += cc.get(k, 0)
        out[tk] = per
        for k in grand:
            grand[k] += per[k]
    return {"tickers": out, "grand_total": grand, "total_tickers": len(out)}