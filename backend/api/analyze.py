"""POST /api/analyze — start a new analysis.
GET  /api/analyze/recent — list most-recent N analyses (canonical for React recent tab).
GET  /api/analyze/{analysis_id}/report — read the full_states_log_*.json report.

Mirrors ``web/components/history_panel.py`` for list/report parity.  All
business code lives in ``backend.core.start_analysis`` / ``tracker`` /
``history_store`` — this module is the FastAPI surface only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Literal

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.core import start_analysis
from backend.core.history_store import get_history_store
from backend.core.report_adapter import adapt_report_for_export, strip_think_blocks
from backend.models.request import AnalyzeRequest, AnalyzeResponse

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

router = APIRouter(prefix="/api")


# ── shared response models for new endpoints ─────────────────────────────────

class RecentAnalyzeItem(BaseModel):
    """One recent analysis row — mirrors the Streamlit history_panel.py list
    shape so React can consume it 1:1 with /api/history."""
    analysis_id: str
    ticker: str
    trade_date: str
    signal: str | None = None
    elapsed: float = 0.0
    created_at: str = ""
    status: str | None = None
    error: str | None = None
    completed_stages: list[str] = []


class AnalyzeReport(BaseModel):
    """Full report payload — mirrors history.py ``get_history_report``.

    P2.29 — added ``pdf_available`` so the React report tab's 📄 PDF button
    can show its disabled state without a separate preflight request.
    The value is computed once at module import (``_pdf_export_available``)
    because ``_find_cjk_font`` recursively scans system font directories and
    we don't want to repeat that work on every report fetch.
    """
    analysis_id: str
    ticker: str
    trade_date: str
    results_path: str
    report: dict | None = None
    pdf_available: bool = False


# P2.29 — CJK-font probe, lazily memoized. ``web/pdf_export._find_cjk_font``
# recursively walks /usr/share/fonts etc. so we don't want to pay that cost
# on every /report fetch. Re-probed lazily via ``invalidate_caches`` if the
# user installs a font mid-session.
def _pdf_export_available() -> bool:
    """True iff the host has at least one CJK font readable by fpdf2.

    Imported lazily so test environments that don't have fpdf2 still work.
    """
    try:
        from web import pdf_export as _pdf_mod
    except Exception:
        return False
    try:
        return _pdf_mod._find_cjk_font() is not None
    except Exception:
        return False


def _entry_to_item(entry) -> RecentAnalyzeItem:
    return RecentAnalyzeItem(
        analysis_id=entry.analysis_id,
        ticker=entry.ticker,
        trade_date=entry.trade_date,
        signal=entry.signal or None,
        elapsed=entry.elapsed,
        created_at=str(entry.created_at),
        status=entry.status or None,
        error=entry.error,
        completed_stages=entry.completed_stages,
    )


# ── POST /api/analyze ────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalyzeResponse, status_code=202)
def create_analysis(request: AnalyzeRequest) -> AnalyzeResponse:
    """Start a new stock analysis. Returns immediately with analysis_id."""
    try:
        analysis_id, tracker = start_analysis(request)
        return AnalyzeResponse(
            analysis_id=analysis_id,
            status="started",
            ticker=request.ticker,
            trade_date=request.trade_date,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── GET /api/analyze/recent ──────────────────────────────────────────────────

@router.get("/analyze/recent", response_model=List[RecentAnalyzeItem])
def list_recent_analyzes(
    limit: int = Query(20, ge=1, le=100),
) -> List[RecentAnalyzeItem]:
    """List most-recent N analyses (newest first) from the history store.

    Mirrors ``history.py::list_history`` but is the dedicated analyze-page
    recent-list endpoint — the React ``AnalyzePage`` uses it as its default
    tab data source so the list refreshes as soon as ``POST /api/analyze``
    writes a new entry to ``backend.core.history_store``.
    """
    store = get_history_store()
    entries, _total = store.list_all(limit=limit, offset=0)
    return [_entry_to_item(e) for e in entries]


# ── P2.14 hotfix: POST /api/analyze/{analysis_id}/mark_error ─────────────────

@router.post("/analyze/{analysis_id}/mark_error", status_code=200)
def mark_analysis_error(
    analysis_id: str,
    reason: str = Query("manual cleanup"),
) -> dict:
    """Force-mark a stuck analysis as errored (manual cleanup tool).

    P2.14 hotfix — for cases where the user sees a permanently-running
    analysis (zombie: status=running, elapsed=0, no thread progressing),
    this endpoint lets the React UI offer a one-click cleanup. The
    backend startup hook does the same sweep automatically on restart;
    this is for the live case where a new zombie appears mid-session.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"分析 {analysis_id!r} 不存在",
        )
    store.mark_error(analysis_id, reason, elapsed=entry.elapsed or 0.0)
    return {
        "analysis_id": analysis_id,
        "status": "error",
        "reason": reason,
    }


# ── P2.21 hotfix: POST /api/analyze/{analysis_id}/cancel ──────────────────────

@router.post("/analyze/{analysis_id}/cancel", status_code=200)
def cancel_analysis(analysis_id: str) -> dict:
    """Mark a running analysis as error-cancelled (user-initiated cleanup).

    P2.21 hotfix — the user reported ``600595_2026-07-16_1589cdfd`` was stuck
    for 8.2 hours with no way to stop it from the React UI. This endpoint
    gives the React AnalyzePage a one-click "取消" button that flips the
    history entry to ``error`` so the polling loop stops and the recent list
    no longer shows it as ``running``.

    Important — Python has no safe way to kill a background thread, so this
    does NOT terminate the worker. The thread will eventually finish or
    error out naturally and write its own completion/error status. The
    important effect is on the UI: the entry's status flips to ``error``
    immediately, so the polling interval stops and the recent-list tab
    treats it as done.

    P2.21 hotfix — also accepts an ID from the POST response, even though
    ``tracker_id != history_id`` due to a separate UUID generation in
    TrackerStore.create() vs HistoryStore.create(). If the direct lookup
    misses, we fall back to ``find_by_ticker_date`` for analyses that
    started today and are still running.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        # Fallback: POST /api/analyze returns the TrackerStore analysis_id
        # but the history file uses a freshly generated one from
        # HistoryStore.create() — they don't match. Try to recover by
        # ticker+date for recent running entries.
        if "_" in analysis_id and analysis_id.count("_") >= 2:
            parts = analysis_id.rsplit("_", 2)
            if len(parts) == 3:
                ticker, trade_date, _uid = parts
                recent = store.find_by_ticker_date(ticker, trade_date)
                if recent and recent.status in ("running", "pending"):
                    entry = recent
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"分析 {analysis_id!r} 不存在",
        )
    if entry.status not in ("running", "pending"):
        # 409 — only running/pending can be cancelled. Already-finished
        # entries are immutable from the user's perspective.
        raise HTTPException(
            status_code=409,
            detail=f"分析状态是 {entry.status}, 不可取消",
        )

    reason = "用户手动取消"
    store.mark_error(entry.analysis_id, reason, elapsed=entry.elapsed or 0.0)

    logger.warning(
        f"Analysis {entry.analysis_id} cancelled by user (thread still running, "
        f"elapsed={entry.elapsed:.1f}s)"
    )
    return {
        "analysis_id": entry.analysis_id,
        "status": "error",
        "reason": reason,
    }


# ── GET /api/analyze/{analysis_id}/report ────────────────────────────────────

@router.get("/analyze/{analysis_id}/report", response_model=AnalyzeReport)
def get_analyze_report(analysis_id: str) -> AnalyzeReport:
    """Return the full report for a past analysis.

    Reads ``history.entry.results_path`` (full_states_log_*.json) and returns
    it as JSON. Falls back to the legacy ticker/date path if results_path is
    empty — same fallback ``history.py::get_history_report`` uses.

    P2.29 — also reports ``pdf_available`` so the React report tab can decide
    whether the 📄 PDF button should be enabled without a separate preflight.
    """
    content, entry, path = _load_report_json(analysis_id)

    return AnalyzeReport(
        analysis_id=entry.analysis_id,
        ticker=entry.ticker,
        trade_date=entry.trade_date,
        results_path=str(path),
        report=content if isinstance(content, dict) else {"raw": content},
        pdf_available=_pdf_export_available(),
    )


def _load_report_json(analysis_id: str) -> tuple[dict, object, Path]:
    """Shared loader for the /report and /export endpoints.

    Returns ``(report_dict, history_entry, resolved_path)``. Raises
    ``HTTPException(404)`` when the analysis is missing or the report
    file is gone — same payload shape both callers surface.
    """
    store = get_history_store()
    entry = store.get(analysis_id)
    if entry is None:
        # P2.10 hotfix — friendlier 404 (Chinese) shared by /report + /export.
        raise HTTPException(
            status_code=404,
            detail=(
                f"分析 {analysis_id!r} 不存在或已过期, "
                "请从历史列表选择新分析"
            ),
        )

    results_path = entry.results_path or ""
    path = Path(results_path) if results_path else None

    if not path or not path.exists():
        legacy = (
            Path.home()
            / ".tradingagents"
            / "logs"
            / entry.ticker
            / "TradingAgentsStrategy_logs"
            / f"full_states_log_{entry.trade_date}.json"
        )
        if legacy.exists():
            path = legacy
        else:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"分析 {analysis_id!r} 的报告文件丢失 "
                    f"(results_path={results_path!r}), 请重跑该分析"
                ),
            )

    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"failed to read report: {exc}"
        ) from exc

    # P2.31 — drop the LLM's chain-of-thought (``<think>...</think>``) at the
    # API boundary. Applies to /report + /export, so the PDF exporter and
    # the React report tab both see the cleaned payload.
    content = strip_think_blocks(content)

    if not isinstance(content, dict):
        content = {"raw": content}

    return content, entry, path


# ── P2.29: GET /api/analyze/{analysis_id}/export?format=md|pdf ────────────────

@router.get("/analyze/{analysis_id}/export")
def export_analyze_report(
    analysis_id: str,
    format: Literal["md", "pdf"] = Query(..., description="markdown or pdf"),
) -> StreamingResponse:
    """Download the report as Markdown or PDF.

    Mirrors the Streamlit download buttons in
    ``web/components/report_viewer.py:66-94``. The browser gets the file
    via ``Content-Disposition: attachment`` so it triggers a native save
    dialog instead of inlining.

    Errors:
      * 404 — unknown analysis_id or report file missing
      * 422 — ``format`` missing or not in {md, pdf}
      * 503 — PDF requested but host has no CJK font
      * 500 — Markdown serialization or PDF generation crashed
    """
    content, entry, _path = _load_report_json(analysis_id)
    adapted, signal = adapt_report_for_export(content)

    filename = f"TradingAgents-Astock_{entry.ticker}_{entry.trade_date}.{format}"

    if format == "md":
        try:
            from web import pdf_export as _pdf_mod
            md_text = _pdf_mod.generate_markdown(
                adapted, entry.ticker, entry.trade_date, signal or "BUY",
            )
        except Exception as exc:  # noqa: BLE001 — propagate as 500
            logger.exception("Markdown export failed for %s", analysis_id)
            raise HTTPException(
                status_code=500,
                detail=f"markdown export failed: {exc}",
            ) from exc
        return StreamingResponse(
            iter([md_text.encode("utf-8")]),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    # format == "pdf"
    if not _pdf_export_available():
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "no_cjk_font",
                "message": (
                    "PDF 导出需要系统装有中文字体（Windows 自带微软雅黑/黑体，"
                    "macOS 自带苹方，Linux 可 apt install fonts-noto-cjk）。"
                    "请改用 Markdown 导出。"
                ),
            },
        )
    try:
        from web import pdf_export as _pdf_mod
        pdf_bytes = _pdf_mod.generate_pdf(
            adapted, entry.ticker, entry.trade_date, signal or "BUY",
        )
    except RuntimeError as exc:
        # Font / fpdf2 runtime issues — surface as 503 with the message so
        # the user knows why their PDF doesn't render.
        logger.warning("PDF export unavailable for %s: %s", analysis_id, exc)
        raise HTTPException(
            status_code=503,
            detail={"reason": "pdf_runtime", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("PDF export crashed for %s", analysis_id)
        raise HTTPException(
            status_code=500,
            detail=f"pdf export failed: {exc}",
        ) from exc

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )