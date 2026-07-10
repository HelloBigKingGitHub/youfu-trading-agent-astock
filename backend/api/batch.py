"""Batch analysis endpoints — submit, monitor, cancel, retry, summary."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from backend.core.job_queue import (
    BatchStatus,
    TICKER_WHITELIST_RE,
    get_job_queue,
)

router = APIRouter()

_MAX_BATCH = 50


# ── helpers ─────────────────────────────────────────────────────────────────


def _validate_ticker(t: str) -> str:
    """严格 6 位 A 股代码白名单校验。"""
    if not isinstance(t, str):
        raise HTTPException(status_code=400, detail=f"ticker 必须是字符串: {t!r}")
    t = t.strip()
    if not TICKER_WHITELIST_RE.match(t):
        raise HTTPException(
            status_code=400,
            detail=(
                f"非法 ticker: {t!r}。"
                "必须是 6 位 A 股代码(沪市 60x/601/603/605/688,深市 000/001/002/003,"
                "创业板 300/301,北交所 430)。"
            ),
        )
    return t


def _validate_date(d: str) -> str:
    """基础日期校验:YYYY-MM-DD。"""
    if not isinstance(d, str) or len(d) != 10:
        raise HTTPException(status_code=400, detail=f"trade_date 格式错误: {d!r}")
    try:
        year, month, day = d.split("-")
        int(year), int(month), int(day)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"trade_date 不是有效日期: {d!r}") from None
    return d


def _dedupe(
    items: list[dict],
    item_overrides: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    """根据 ticker+trade_date 去重,跳过已 completed 的组合。

    Returns ``(kept_items, kept_overrides)``. ``item_overrides`` is filtered
    in lockstep with ``items`` so the per-job LLM config stays aligned with
    the jobs that survived dedupe. If ``item_overrides`` is None, an empty
    list is returned for the second element (CLI path that doesn't pass any).
    """
    from backend.core.history_store import get_history_store

    store = get_history_store()
    kept: list[dict] = []
    kept_ov: list[dict] = []
    overrides = item_overrides or []
    for idx, it in enumerate(items):
        entries, _ = store.list_all(ticker=it["ticker"], status="completed", limit=50)
        already = any(
            e.ticker == it["ticker"] and e.trade_date == it["trade_date"]
            for e in entries
        )
        if not already:
            kept.append(it)
            kept_ov.append(overrides[idx] if idx < len(overrides) else {})
    return kept, kept_ov


# POST /api/batch 每条 item 允许的 LLM 字段(都是可选)。这些字段在 body 里
# 按 job 传递 — 避免依赖 env 变量,因为前端(Streamlit)和后端(uvicorn)是
# 两个独立进程,env 不会跨边界传递。
_OPTIONAL_LLM_FIELDS = (
    "llm_provider",
    "deep_think_llm",
    "quick_think_llm",
    "backend_url",
)


def _extract_item_llm(raw: dict) -> dict:
    """Pull LLM override fields from a raw item; drop any non-string / empty.

    Returns a dict with at most the four _OPTIONAL_LLM_FIELDS keys, all values
    being non-empty strings. Any field that wasn't provided (or was an empty
    string / non-string) is omitted — the helpers then fall back to env /
    hardcoded defaults.
    """
    out: dict = {}
    for key in _OPTIONAL_LLM_FIELDS:
        v = raw.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


# ── POST /api/batch ──────────────────────────────────────────────────────────


@router.post("/api/batch")
def create_batch(
    items: list[dict],
    dedupe: bool = Query(default=False, description="true 时跳过已 completed 的 ticker+date"),
) -> dict:
    """提交批量分析任务。"""
    if not items:
        raise HTTPException(status_code=400, detail="Empty batch")
    if len(items) > _MAX_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Max {_MAX_BATCH} jobs per batch (got {len(items)})",
        )

    # 校验 + dedup
    seen: set[tuple[str, str]] = set()
    normalized: list[dict] = []
    item_overrides: list[dict] = []
    for raw in items:
        ticker = _validate_ticker(raw.get("ticker", ""))
        date = _validate_date(raw.get("trade_date", ""))
        key = (ticker, date)
        if key in seen:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate ticker+date in batch: {ticker}/{date}",
            )
        seen.add(key)
        normalized.append({"ticker": ticker, "trade_date": date})
        # 收集该 item 的 LLM override;空 dict 表示"走 env / 硬编码兜底"
        item_overrides.append(_extract_item_llm(raw))

    if dedupe:
        normalized, item_overrides = _dedupe(normalized, item_overrides)
        if not normalized:
            raise HTTPException(
                status_code=400,
                detail="All items already completed (dedupe filtered everything)",
            )

    q = get_job_queue()
    batch_id, batch = q.create_batch(normalized)

    # 构造 per-job config:每个 job 用各自的 LLM override(若 body 里给了),
    # 否则读 env(BATCH_LLM_*),再否则硬编码 minimax。
    #
    # `build_default_configs` 内部以 ``dict(DEFAULT_CONFIG)`` 为种子 — 这样
    # ``data_cache_dir`` 等上游必需键都保留,避免 TradingAgentsGraph.__init__
    # 抛 KeyError。然后 LLM / debate / language / data_vendors 字段被显式
    # 覆盖,这样即使 ``DEFAULT_CONFIG.llm_provider == "openai"``,最终生效的
    # 也不会是 openai(没有 OPENAI_API_KEY 也会 OK)。
    from backend.api.batch_helpers import build_default_configs, resolve_llm_summary

    configs = build_default_configs(batch.jobs, item_overrides=item_overrides)
    q.submit(batch_id, batch.jobs, configs=configs)

    # 把"该 job 实际用的 LLM"回给前端,方便用户核对配置是否生效。
    # 用 build_default_configs 解析之后的 config(经过 env 兜底),而不是 raw item —
    # 这样前端显示的就是真正会跑的那个 LLM。
    job_summaries = [
        {
            **resolve_llm_summary(cfg),
            "ticker": j.ticker,
            "trade_date": j.trade_date,
        }
        for j, cfg in zip(batch.jobs, configs)
    ]

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
        "llm_summary": job_summaries,
    }


# ── GET /api/batch/{batch_id} ────────────────────────────────────────────────


@router.get("/api/batch/{batch_id}")
def get_batch(batch_id: str) -> dict:
    q = get_job_queue()
    batch = q.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {
        "batch_id": batch.batch_id,
        "batch_status": batch.batch_status,
        "total": len(batch.jobs),
        "finished_count": sum(1 for j in batch.jobs if j.status == "completed"),
        "error_count": sum(1 for j in batch.jobs if j.status == "error"),
        "jobs": [j.to_dict() for j in batch.jobs],
    }


# ── GET /api/batch/{batch_id}/summary ────────────────────────────────────────


@router.get("/api/batch/{batch_id}/summary")
def get_batch_summary(batch_id: str) -> dict:
    """聚合 CSV-ready 行,供前端导出按钮使用。"""
    q = get_job_queue()
    batch = q.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    rows = []
    for j in batch.jobs:
        rows.append({
            "ticker": j.ticker,
            "trade_date": j.trade_date,
            "status": j.status,
            "signal": j.signal,
            "completed_stages_count": len(j.completed_stages),
            "elapsed_seconds": round(j.elapsed, 1),
            "error": j.error or "",
        })
    return {
        "batch_id": batch_id,
        "batch_status": batch.batch_status,
        "rows": rows,
    }


# ── SSE stream ───────────────────────────────────────────────────────────────


@router.get("/api/batch/{batch_id}/stream")
async def stream_batch(batch_id: str):
    """SSE:逐 job 推送 stage_done,直到 batch 全部完成。

    Event types:
      - stage: 某个 job 完成一个 stage
      - job_done: 某个 job 进入终态(completed/error/cancelled)
      - complete: 整批完成
    """
    q = get_job_queue()
    batch = q.get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    terminal = {"completed", "error", "cancelled"}
    seen_stages: dict[str, set[str]] = {j.job_id: set() for j in batch.jobs}
    seen_done: set[str] = set()

    async def gen():
        last_keepalive = time.time()
        while True:
            now = time.time()
            # 心跳
            if now - last_keepalive > 15:
                yield {"event": "ping", "data": json.dumps({"ts": now})}
                last_keepalive = now

            # 扫描所有 job
            for j in batch.jobs:
                d = j.to_dict()
                # stage 事件
                for s in d["completed_stages"]:
                    if s not in seen_stages[j.job_id]:
                        seen_stages[j.job_id].add(s)
                        yield {
                            "event": "stage",
                            "data": json.dumps({
                                "job_id": j.job_id,
                                "ticker": j.ticker,
                                "stage_id": s,
                                "status": "done",
                            }),
                        }
                # job_done 事件
                if d["status"] in terminal and j.job_id not in seen_done:
                    seen_done.add(j.job_id)
                    yield {
                        "event": "job_done",
                        "data": json.dumps({
                            "job_id": j.job_id,
                            "ticker": j.ticker,
                            "status": d["status"],
                            "signal": d["signal"],
                            "error": d["error"],
                        }),
                    }
            # batch 完成
            if all(j.status in terminal for j in batch.jobs):
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "batch_id": batch_id,
                        "batch_status": batch.batch_status,
                        "total": len(batch.jobs),
                    }),
                }
                return

            # 短暂 sleep
            import asyncio
            await asyncio.sleep(0.5)

    return EventSourceResponse(gen())


# ── Job list / retry ─────────────────────────────────────────────────────────


@router.get("/api/jobs")
def list_jobs(
    batch_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    q = get_job_queue()
    if batch_id:
        batch = q.get_batch(batch_id)
        jobs = batch.jobs if batch else []
    else:
        jobs = q.list_all_jobs()

    if status:
        jobs = [j for j in jobs if j.status == status]
    if ticker:
        jobs = [j for j in jobs if ticker.upper() in j.ticker.upper()]
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    jobs = jobs[:limit]
    return {"jobs": [j.to_dict() for j in jobs], "total": len(jobs)}


@router.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    q = get_job_queue()
    job = q.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "running":
        raise HTTPException(status_code=400, detail="Job already running")
    ok = q.retry(job_id, config={})
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot retry this job")
    return {"job_id": job_id, "status": "retrying"}


# ── Batch cancel ─────────────────────────────────────────────────────────────


@router.post("/api/batch/{batch_id}/cancel")
def cancel_batch(batch_id: str) -> dict:
    q = get_job_queue()
    n = q.cancel_batch(batch_id)
    if q.get_batch(batch_id) is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"batch_id": batch_id, "cancelled_count": n}