"""Schedule FastAPI router — read + write endpoints for the scheduled
analysis module (v0.6.0), surfaced to the React frontend (P2.8).

Mirrors ``web/components/schedule_panel.py`` 1:1 by exposing the same data
slices the Streamlit panel renders:

  - GET    /api/schedule/list                       → list all schedules
  - GET    /api/schedule/{id}                      → single schedule + recent runs
  - POST   /api/schedule/create                    → create (cron + source + notify)
  - PUT    /api/schedule/{id}                      → update
  - DELETE /api/schedule/{id}                      → delete
  - POST   /api/schedule/{id}/run_now              → trigger immediately
  - POST   /api/schedule/{id}/pause                → pause
  - POST   /api/schedule/{id}/resume               → resume
  - GET    /api/schedule/watchlist                 → list watchlist entries
  - GET    /api/schedule/notifier/channels         → list 4 notify channels + status
  - POST   /api/schedule/{id}/test_notify          → fire a test notify
  - GET    /api/schedule/runs/{run_id}             → run detail + ticker status

This API does NOT modify the business layer: it reuses the existing
``backend.core.scheduler.Scheduler``, ``backend.core.watchlist.WatchlistStore``
and ``backend.core.notifier.Notifier`` modules. The Streamlit panel keeps
running in parallel (硬约束 0 改).

Phase 2.8 of v0.7.0 — the 8th page to come online after Settings, History,
Logs, Chart, Sector, Batch, Portfolio.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory cache of test_notify jobs (run_id → Future/result) so the
# React UI can poll status without forcing the user to wait synchronously.
# Mirrors the same loose pattern used by ``batch.py`` for batch progress —
# we accept that this cache is process-local and ephemeral; persistent
# audit still lives in the scheduler's runs/*.jsonl files.
_TEST_NOTIFY_THREADS: dict[str, dict[str, Any]] = {}
_TEST_NOTIFY_LOCK = threading.Lock()


# ── helpers ──────────────────────────────────────────────────────────────────


def _schedule_to_dict(s: Any) -> dict[str, Any]:
    """Convert ``Schedule`` dataclass → JSON-safe dict (incl. computed fields).

    Adds two computed fields the Streamlit panel computes on the fly:
      - ``next_run_at`` (unix ts; ``None`` when cron invalid)
      - ``source_summary`` (e.g. ``持仓`` / ``自选股 · 长线`` / ``手动 · 3 只``)
    """
    if hasattr(s, "to_dict"):
        base = s.to_dict()
    else:  # pragma: no cover - defensive
        base = {
            "schedule_id": getattr(s, "schedule_id", ""),
            "name": getattr(s, "name", ""),
            "cron_expr": getattr(s, "cron_expr", ""),
            "source_type": getattr(s, "source_type", "portfolio"),
            "source_config": dict(getattr(s, "source_config", {})),
            "enabled": bool(getattr(s, "enabled", True)),
            "notify_channels": list(getattr(s, "notify_channels", ["log"])),
            "notify_template": getattr(s, "notify_template", ""),
            "config": dict(getattr(s, "config", {})),
            "last_run_at": getattr(s, "last_run_at", None),
            "last_run_batch_id": getattr(s, "last_run_batch_id", None),
            "last_run_status": getattr(s, "last_run_status", "never"),
            "last_error": getattr(s, "last_error", None),
            "created_at": getattr(s, "created_at", 0.0),
            "created_by": getattr(s, "created_by", "user"),
        }
    next_at = None
    try:
        next_at = s.next_run_at()
    except Exception:  # noqa: BLE001
        next_at = None
    base["next_run_at"] = next_at
    base["source_summary"] = _source_summary(s)
    return base


def _source_summary(s: Any) -> str:
    """Human-readable one-liner for a schedule's ticker source.

    Mirrors ``web/components/schedule_panel.py::source_summary`` so the React
    page can render the same wording without re-implementing the heuristic.
    """
    src = (
        s.source_type.value
        if hasattr(s.source_type, "value")
        else s.source_type
    )
    cfg = s.source_config or {}
    if src == "portfolio":
        return "持仓"
    if src == "watchlist":
        tag = cfg.get("tag") if cfg else None
        return f"自选股 · {tag}" if tag else "自选股"
    if src == "manual":
        tickers = cfg.get("tickers", []) if cfg else []
        return f"手动 · {len(tickers)} 只"
    return src


def _run_to_dict(r: Any) -> dict[str, Any]:
    """Convert ``ScheduleRun`` dataclass → JSON-safe dict."""
    if hasattr(r, "to_dict"):
        return r.to_dict()
    return {
        "run_id": getattr(r, "run_id", ""),
        "schedule_id": getattr(r, "schedule_id", ""),
        "started_at": getattr(r, "started_at", 0.0),
        "finished_at": getattr(r, "finished_at", None),
        "status": getattr(r, "status", "running"),
        "batch_id": getattr(r, "batch_id", None),
        "job_ids": list(getattr(r, "job_ids", [])),
        "duration": float(getattr(r, "duration", 0.0)),
        "summary": getattr(r, "summary", ""),
        "error": getattr(r, "error", None),
        "ticker_count": int(getattr(r, "ticker_count", 0)),
    }


def _scheduler():
    """Lazy import to avoid side-effects at module import time."""
    from backend.core.scheduler import Scheduler

    return Scheduler.get_instance()


# ── 1. list ──────────────────────────────────────────────────────────────────


@router.get("/schedule/list")
def list_schedules() -> dict[str, Any]:
    """List all schedules (enabled + disabled), sorted by name then id.

    Mirrors ``Scheduler.list_schedules()`` and the Streamlit ``render_schedule_panel``
    toolbar/list layout.
    """
    sched = _scheduler()
    items = sched.list_schedules()
    rows = [_schedule_to_dict(s) for s in items]
    # Sort: enabled first, then by name (so the preset 每日持仓复盘 is first).
    rows.sort(key=lambda r: (not r["enabled"], r["name"], r["schedule_id"]))
    return {
        "schedules": rows,
        "count": len(rows),
        "scheduler_running": sched.is_running(),
        "last_tick_at": sched.last_tick_at(),
        "fetched_at": time.time(),
    }


# ── 1.5 watchlist (MUST come before /{schedule_id} — 'watchlist' is a valid id) ─


@router.get("/schedule/watchlist")
def list_watchlist(tag: str = "") -> dict[str, Any]:
    """List all watchlist entries (optional tag filter).

    Mirrors ``WatchlistStore.list`` and the Streamlit self-stock dropdown
    used inside the schedule add/edit dialog when source=watchlist.
    """
    from backend.core.watchlist import VALID_TAGS, get_watchlist_store

    store = get_watchlist_store()
    entries = store.list(tag=tag or None)
    rows = [
        {
            "entry_id": e.entry_id,
            "ticker": e.ticker,
            "tag": e.tag,
            "note": e.note,
            "created_at": e.created_at,
        }
        for e in entries
    ]
    return {
        "entries": rows,
        "count": len(rows),
        "valid_tags": sorted(VALID_TAGS),
        "fetched_at": time.time(),
    }


# ── 1.6 notifier channels (also before /{schedule_id}) ──────────────────────


@router.get("/schedule/notifier/channels")
def list_notifier_channels() -> dict[str, Any]:
    """Enumerate the 4 supported notify channels + per-channel config status.

    Mirrors ``Notifier.config()`` + the static ``Channel`` enum. Returns a
    declarative catalog so the React notifier-config panel can render a
    status grid without re-implementing the heuristic.
    """
    from backend.core.notifier import Channel, get_notifier

    notifier = get_notifier()
    cfg = notifier.config()
    catalog: list[dict[str, Any]] = []
    for ch in (Channel.WECOM, Channel.EMAIL, Channel.DESKTOP, Channel.LOG):
        ch_value = ch.value
        configured = cfg.is_configured(ch_value)
        catalog.append({
            "channel": ch_value,
            "label": {
                "wecom": "WeCom",
                "email": "Email",
                "desktop": "Desktop",
                "log": "Log",
            }.get(ch_value, ch_value),
            "enabled_in_config": ch_value in cfg.enabled_channels,
            "configured": configured,
            "supports_test": True,
            "test_endpoint": f"/api/schedule/0/test_notify?channel={ch_value}",
        })
    return {
        "channels": catalog,
        "count": len(catalog),
        "enabled_channels": list(cfg.enabled_channels),
        "fetched_at": time.time(),
    }


# ── 2. detail ────────────────────────────────────────────────────────────────


@router.get("/schedule/{schedule_id}")
def get_schedule(schedule_id: str) -> dict[str, Any]:
    """Single schedule + recent runs (last 20).

    Mirrors the Streamlit ``render_schedule_list`` row click → detail panel.
    """
    sched = _scheduler()
    s = sched.get_schedule(schedule_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
    runs = sched.list_runs(schedule_id=schedule_id, limit=20)
    return {
        "schedule": _schedule_to_dict(s),
        "runs": [_run_to_dict(r) for r in runs],
        "fetched_at": time.time(),
    }


# ── 3. create ────────────────────────────────────────────────────────────────


@router.post("/schedule/create")
def create_schedule(payload: dict = Body(...)) -> dict[str, Any]:
    """Create a new schedule.

    Body fields (all required unless noted):
      - ``name`` (str)
      - ``cron_expr`` (str, 5-field cron)
      - ``source_type`` (str: 'portfolio' | 'watchlist' | 'manual')
      - ``source_config`` (dict: ``{tag: ...}`` for watchlist, ``{tickers: [...]}`` for manual)
      - ``enabled`` (bool, optional, default True)
      - ``notify_channels`` (list[str], optional, default ['log'])
      - ``notify_template`` (str, optional)
      - ``config`` (dict, optional — LLM override / stagger / wait_timeout)
    """
    from backend.core.scheduler import Schedule, SourceType

    sched = _scheduler()
    name = (payload.get("name") or "").strip()
    cron_expr = (payload.get("cron_expr") or "").strip()
    source_type_raw = payload.get("source_type") or "portfolio"
    try:
        source_type = SourceType(source_type_raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"未知 source_type: {source_type_raw!r}",
        ) from exc
    source_config = dict(payload.get("source_config") or {})
    enabled = bool(payload.get("enabled", True))
    notify_channels = list(payload.get("notify_channels") or ["log"])
    notify_template = payload.get("notify_template") or "v0.6.0 default"
    config = dict(payload.get("config") or {})

    s = Schedule(
        schedule_id="",
        name=name,
        cron_expr=cron_expr,
        source_type=source_type,
        source_config=source_config,
        enabled=enabled,
        notify_channels=notify_channels,
        notify_template=notify_template,
        config=config,
    )
    try:
        sid = sched.add_schedule(s)
    except ValueError as exc:
        # Pydantic-422-style validation failure for the user-facing message.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = sched.get_schedule(sid)
    return {"schedule": _schedule_to_dict(saved) if saved else {}, "created_at": time.time()}


# ── 4. update ────────────────────────────────────────────────────────────────


@router.put("/schedule/{schedule_id}")
def update_schedule(schedule_id: str, payload: dict = Body(...)) -> dict[str, Any]:
    """Update an existing schedule (schedule_id in URL is authoritative).

    Same body contract as ``create_schedule`` — the schedule_id in the body
    is ignored; the URL path wins. Mirrors the Streamlit edit dialog
    (which preserves schedule_id and only mutates the other fields).
    """
    from backend.core.scheduler import Schedule, SourceType

    sched = _scheduler()
    existing = sched.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")

    try:
        source_type = SourceType(payload.get("source_type") or existing.source_type.value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"未知 source_type: {payload.get('source_type')!r}",
        ) from exc

    updated = Schedule(
        schedule_id=schedule_id,
        name=(payload.get("name") or existing.name).strip(),
        cron_expr=(payload.get("cron_expr") or existing.cron_expr).strip(),
        source_type=source_type,
        source_config=dict(payload.get("source_config") or existing.source_config),
        enabled=bool(payload.get("enabled", existing.enabled)),
        notify_channels=list(payload.get("notify_channels") or existing.notify_channels),
        notify_template=payload.get("notify_template") or existing.notify_template,
        config=dict(payload.get("config") or existing.config),
        last_run_at=existing.last_run_at,
        last_run_batch_id=existing.last_run_batch_id,
        last_run_status=existing.last_run_status,
        last_error=existing.last_error,
        created_at=existing.created_at,
        created_by=existing.created_by,
    )
    try:
        sched.update_schedule(updated)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = sched.get_schedule(schedule_id)
    return {"schedule": _schedule_to_dict(saved) if saved else {}, "updated_at": time.time()}


# ── 5. delete ────────────────────────────────────────────────────────────────


@router.delete("/schedule/{schedule_id}")
def delete_schedule(schedule_id: str) -> dict[str, Any]:
    """Delete a schedule (idempotent: 404 if not present)."""
    sched = _scheduler()
    ok = sched.delete_schedule(schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
    return {"deleted": True, "schedule_id": schedule_id, "deleted_at": time.time()}


# ── 6. run_now ──────────────────────────────────────────────────────────────


@router.post("/schedule/{schedule_id}/run_now")
def run_schedule_now(schedule_id: str) -> dict[str, Any]:
    """Trigger the schedule immediately (async).

    Mirrors the Streamlit ▶ button — calls ``Scheduler.run_now`` and returns
    a placeholder batch_id; the actual JobQueue batch is created inside
    ``Scheduler._run_schedule`` running in the executor thread.
    """
    sched = _scheduler()
    try:
        bid = sched.run_now(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"batch_id": bid, "schedule_id": schedule_id, "triggered_at": time.time()}


# ── 7. pause ─────────────────────────────────────────────────────────────────


@router.post("/schedule/{schedule_id}/pause")
def pause_schedule(schedule_id: str) -> dict[str, Any]:
    sched = _scheduler()
    ok = sched.pause_schedule(schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
    return {"paused": True, "schedule_id": schedule_id, "paused_at": time.time()}


# ── 8. resume ────────────────────────────────────────────────────────────────


@router.post("/schedule/{schedule_id}/resume")
def resume_schedule(schedule_id: str) -> dict[str, Any]:
    sched = _scheduler()
    ok = sched.resume_schedule(schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
    return {"resumed": True, "schedule_id": schedule_id, "resumed_at": time.time()}


# ── 9. test_notify ────────────────────────────────────────────────────────────


@router.post("/schedule/{schedule_id}/test_notify")
def test_notify(schedule_id: str, channel: str = "log") -> dict[str, Any]:
    """Fire a one-shot test notification through the named channel.

    Mirrors the Streamlit 「测试通知」 button. The channel can be ``log`` /
    ``desktop`` / ``wecom`` / ``email`` — non-``log`` channels require the
    corresponding channels.yaml section to be configured (the Notifier
    surfaces that as ``configured=True`` on the channels endpoint).
    """
    import uuid as _uuid

    from backend.core.notifier import Channel, get_notifier
    from backend.core.scheduler import Scheduler

    valid = {c.value for c in Channel}
    if channel not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"未知 channel: {channel!r} (valid: {sorted(valid)})",
        )

    sched = Scheduler.get_instance()
    if schedule_id != "0":
        s = sched.get_schedule(schedule_id)
        if s is None:
            raise HTTPException(
                status_code=404,
                detail=f"schedule {schedule_id!r} not found",
            )
        sched_name = s.name
    else:
        sched_name = "Test Notify (schedule 0)"

    run_id = _uuid.uuid4().hex[:12]
    notifier = get_notifier()

    def _fire() -> None:
        """Background fire — never raise out of the executor."""
        try:
            results = notifier.send(
                [channel],
                sched_name,
                {
                    "status": "ok",
                    "started_at": time.time(),
                    "duration": 0.0,
                    "summary": f"test_notify via {channel} (run_id={run_id})",
                    "batch_id": "",
                    "run_id": run_id,
                    "ticker_count": 0,
                },
            )
            with _TEST_NOTIFY_LOCK:
                _TEST_NOTIFY_THREADS[run_id] = {
                    "status": "done",
                    "results": results,
                    "finished_at": time.time(),
                }
        except Exception as exc:  # noqa: BLE001
            with _TEST_NOTIFY_LOCK:
                _TEST_NOTIFY_THREADS[run_id] = {
                    "status": "error",
                    "error": str(exc),
                    "finished_at": time.time(),
                }

    with _TEST_NOTIFY_LOCK:
        _TEST_NOTIFY_THREADS[run_id] = {
            "status": "running",
            "started_at": time.time(),
        }
    threading.Thread(target=_fire, name=f"test-notify-{run_id}", daemon=True).start()
    return {"run_id": run_id, "channel": channel, "status": "running", "schedule_id": schedule_id}


# ── 12. run detail ───────────────────────────────────────────────────────────


@router.get("/schedule/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Single run detail (with all fields).

    Used by the React schedule-runs panel when the user clicks a history
    row — surfaces the full ScheduleRun payload so the panel can render
    the ticker-processing breakdown (batch_id + job_ids + ticker_count).
    """
    sched = _scheduler()
    # Search all runs (lightweight: only last 4 × limit; mirror CLI helper).
    candidates = sched.list_runs(limit=200)
    for r in candidates:
        if r.run_id == run_id:
            return {
                "run": _run_to_dict(r),
                "fetched_at": time.time(),
            }
    raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")


# ── test_notify polling helper (internal; not part of PAGE_REGISTRY) ────────


@router.get("/schedule/test_notify/status/{run_id}")
def test_notify_status(run_id: str) -> dict[str, Any]:
    """Poll the status of a test_notify fire. Returns the cached result."""
    with _TEST_NOTIFY_LOCK:
        rec = dict(_TEST_NOTIFY_THREADS.get(run_id) or {})
    if not rec:
        raise HTTPException(status_code=404, detail=f"test_notify run {run_id!r} not found")
    return {"run_id": run_id, **rec, "fetched_at": time.time()}
