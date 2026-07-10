"""Streamlit panel for batch analysis.

Renders the multi-ticker input form, submits via the backend `/api/batch`
endpoint, polls `/api/batch/{id}` until all jobs reach a terminal state,
and exposes per-row retry / view-report buttons. The CSV download button
sits at the top of the panel for quick export.

Reuses:
- ``web.components.sidebar._render_llm_config`` for the model selector so the
  panel looks identical to the analyze form's advanced settings.
- ``web.components.report_viewer.render_report`` to show a completed job's
  full report when the user clicks "查看报告".
- ``web.styles.inject_css`` is called once from ``web.app``, no need to
  re-inject here.
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests
import streamlit as st

# Project root on sys.path so ``backend.*`` imports resolve when Streamlit
# imports this module directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.job_queue import TICKER_WHITELIST_RE  # noqa: E402

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")

# Terminal statuses for a job (no further changes expected).
_TERMINAL = {"completed", "error", "cancelled"}

# Status icons reused in the table.
_STATUS_ICON = {
    "completed": "✅",
    "error": "❌",
    "running": "🔄",
    "pending": "⏳",
    "cancelled": "⊘",
}


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_tickers(text: str) -> tuple[list[str], list[str]]:
    """Split user input on comma/newline/whitespace. Returns (clean, invalid)."""
    if not text:
        return [], []
    parts = re.split(r"[,\n\r\s]+", text)
    clean: list[str] = []
    invalid: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if TICKER_WHITELIST_RE.match(p):
            clean.append(p)
        else:
            invalid.append(p)
    # Dedupe while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for t in clean:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped, invalid


def _format_elapsed(seconds: float) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _signal_kind(signal: str) -> str:
    """Map signal text to a CSS class suffix used in elements.css."""
    s = (signal or "").upper()
    if "BUY" in s:
        return "buy"
    if "SELL" in s:
        return "sell"
    if "HOLD" in s:
        return "hold"
    return "neutral"


def _fetch_batch(batch_id: str) -> dict[str, Any] | None:
    """GET /api/batch/{id} with a short timeout. None on network error."""
    try:
        r = requests.get(f"{BACKEND_URL}/api/batch/{batch_id}", timeout=5)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def _fetch_summary(batch_id: str) -> dict[str, Any] | None:
    try:
        r = requests.get(f"{BACKEND_URL}/api/batch/{batch_id}/summary", timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def _summary_to_csv(summary: dict[str, Any]) -> str:
    """Convert the /summary payload to a CSV string (UTF-8 BOM for Excel)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "ticker", "trade_date", "status", "signal",
        "completed_stages_count", "elapsed_seconds", "error",
    ])
    for row in summary.get("rows", []):
        writer.writerow([
            row.get("ticker", ""),
            row.get("trade_date", ""),
            row.get("status", ""),
            row.get("signal", ""),
            row.get("completed_stages_count", 0),
            row.get("elapsed_seconds", 0.0),
            (row.get("error") or "").replace("\n", " ")[:200],
        ])
    return buf.getvalue()


def _results_path_for_job(job: dict[str, Any]) -> str | None:
    """Resolve the full_states_log path for a completed job.

    Tries (in order):
      1. ``stage_reports`` key on the job dict (if backend exposes it).
      2. Conventional path under ``~/.tradingagents/logs/<ticker>/...`` keyed
         by ``trade_date``.
    Returns None if nothing usable is found.
    """
    ticker = job.get("ticker", "")
    trade_date = job.get("trade_date", "")
    if not ticker or not trade_date:
        return None
    candidate = (
        Path.home() / ".tradingagents" / "logs" / ticker
        / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json"
    )
    if candidate.exists():
        return str(candidate)
    return None


def _has_active_jobs(payload: dict[str, Any] | None) -> bool:
    """True if any job in the batch is still pending or running."""
    if not payload:
        return True  # unknown → assume still active so we keep polling
    for j in payload.get("jobs", []):
        if j.get("status") not in _TERMINAL:
            return True
    return False


# ── main panel ───────────────────────────────────────────────────────────────


def render_batch_panel() -> None:
    """Render the batch analysis page."""
    st.html(
        """
        <div class="bb-section-label">批量分析</div>
        <div class="bb-section-help">
            一次跑多个 ticker + 同一日期,共享同一份 LLM 配置。任务在后台线程池并行,
            失败/取消的 job 可以单独重试。
        </div>
        """
    )

    active_batch_id: str | None = st.session_state.get("active_batch_id")

    # ── 1. CSV export button (visible only when a batch has been started) ──
    if active_batch_id:
        summary = _fetch_summary(active_batch_id)
        if summary and summary.get("rows"):
            csv_text = _summary_to_csv(summary)
            st.download_button(
                "📥 导出汇总",
                data=csv_text,
                file_name=f"batch_{active_batch_id}.csv",
                mime="text/csv",
                key="batch_export_csv",
                use_container_width=False,
            )
        st.caption(f"batch_id: `{active_batch_id}`")

    # ── 2. Input form (wrapped in the same visual class as the analyze form) ──
    with st.container(key="main_batch_form_container"):
        st.html('<div class="bb-section-label">新建批量任务</div>')

        tickers_text = st.text_area(
            "股票列表(逗号或换行分隔)",
            value=st.session_state.get("batch_tickers_input", "688017\n600519\n000001"),
            height=120,
            key="batch_tickers_input",
            help="6 位 A 股代码,沪市 60x/688,深市 000/001/002/003,创业板 300/301,北交所 430。",
        )

        col_a, col_b = st.columns([1, 1])
        with col_a:
            trade_date = st.date_input(
                "分析日期",
                value=st.session_state.get("batch_date_input", date.today()),
                key="batch_date_input",
            )
        with col_b:
            max_workers = st.number_input(
                "并发 worker 数",
                min_value=1,
                max_value=20,
                value=int(os.environ.get("BATCH_MAX_WORKERS", "5")),
                step=1,
                key="batch_workers_input",
                help="同一时间最多跑几个 job (后端 ThreadPoolExecutor 大小)。",
            )

        with st.expander("⚙️  高级(LLM 配置)", expanded=False):
            from web.components.sidebar import _render_llm_config  # noqa: PLC0415

            _render_llm_config()

        submit = st.button(
            "🚀 开始批量分析",
            type="primary",
            use_container_width=True,
            key="batch_submit",
        )

    if submit:
        tickers, invalid = _parse_tickers(tickers_text or "")
        if invalid:
            st.error(f"非法 ticker: {', '.join(invalid)}")
        if not tickers and not invalid:
            st.error("请至少输入一个 ticker")
        if not tickers:
            st.stop()

        # 关键改动:把当前 session_state 里的 LLM 配置塞到每个 item 的 body 里
        # 传给 /api/batch,而不是写 os.environ(env 不会跨进程边界从 Streamlit
        # 传到 uvicorn,所以以前那种"前端设 env"的写法是无效的)。
        payload = []
        for t in tickers:
            payload.append({
                "ticker": t,
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "llm_provider": st.session_state.get("llm_provider") or None,
                "deep_think_llm": st.session_state.get("deep_think_llm") or None,
                "quick_think_llm": st.session_state.get("quick_think_llm") or None,
                "backend_url": st.session_state.get("llm_base_url") or None,
            })
        try:
            r = requests.post(
                f"{BACKEND_URL}/api/batch",
                json=payload,
                timeout=10,
            )
        except requests.RequestException as exc:
            st.error(f"无法连接后端 {BACKEND_URL}: {exc}")
            st.stop()

        if r.status_code != 200:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            st.error(f"提交失败 ({r.status_code}): {detail}")
            st.stop()

        data = r.json()
        batch_id = data.get("batch_id")
        if not batch_id:
            st.error(f"后端未返回 batch_id: {data}")
            st.stop()
        st.session_state["active_batch_id"] = batch_id
        st.success(f"✓ batch 已提交: {batch_id} ({data.get('total', len(tickers))} jobs)")

        # 把后端确认的实际 LLM 配置回显给用户,验证它与「⚙️ 设置」一致。
        llm_summaries = data.get("llm_summary") or []
        if llm_summaries:
            with st.expander("🔍 实际使用的 LLM 配置", expanded=False):
                for s in llm_summaries:
                    st.markdown(
                        f"- `{s.get('ticker', '?')}` → provider=`{s.get('llm_provider', '?')}` "
                        f"deep=`{s.get('deep_think_llm', '?')}` "
                        f"quick=`{s.get('quick_think_llm', '?')}`"
                    )
        st.rerun()

    # ── 3. Live progress + per-job actions ──
    if not active_batch_id:
        return

    payload = _fetch_batch(active_batch_id)
    if payload is None:
        st.warning(
            f"无法拉取 batch `{active_batch_id}` 状态。"
            f"确认后端 {BACKEND_URL} 已启动 (uvicorn backend.main:app --port 8000)。"
        )
        return

    finished = payload.get("finished_count", 0)
    error_count = payload.get("error_count", 0)
    total = payload.get("total", 0)

    st.markdown("---")
    st.html('<div class="bb-section-label">任务进度</div>')
    st.markdown(
        f"**Batch 状态**: `{payload.get('batch_status', '?')}`  ·  "
        f"完成 **{finished}**/{total}  ·  失败 **{error_count}**"
    )
    if total:
        st.progress(min(1.0, finished / total))

    st.html('<div class="bb-section-label">JOB 列表</div>')

    jobs = payload.get("jobs", [])
    if not jobs:
        st.info("batch 中暂无 job。")
    else:
        _render_jobs_table(jobs)

    # ── 4. Modal: view report ──
    viewing_report = st.session_state.get("batch_viewing_report")
    if viewing_report:
        st.markdown("---")
        try:
            with open(viewing_report, encoding="utf-8") as f:
                import json as _json

                state = _json.load(f)
            from web.components.report_viewer import render_report  # noqa: PLC0415
            from web.history import extract_signal  # noqa: PLC0415

            ticker = state.get("ticker") or Path(viewing_report).parent.parent.name
            trade_date = (
                state.get("trade_date")
                or Path(viewing_report).stem.replace("full_states_log_", "")
            )
            signal = extract_signal(state)
            render_report(state, ticker, trade_date, signal)
        except Exception as exc:
            st.error(f"加载报告失败: {exc}")
        if st.button("← 回到 batch", key="batch_back"):
            st.session_state["batch_viewing_report"] = None
            st.rerun()

    # ── 5. Auto-refresh while batch has non-terminal jobs ──
    if _has_active_jobs(payload):
        time.sleep(2)
        st.rerun()


def _render_jobs_table(jobs: list[dict[str, Any]]) -> None:
    """Render the per-job status table with retry / view-report buttons."""
    # Header row.
    h1, h2, h3, h4, h5, h6 = st.columns([1.2, 0.8, 1.4, 0.8, 1.0, 2.0])
    h1.markdown("**Ticker**")
    h2.markdown("**Status**")
    h3.markdown("**Current stage**")
    h4.markdown("**Elapsed**")
    h5.markdown("**Signal**")
    h6.markdown("**Action**")

    for j in jobs:
        job_id = j.get("job_id", "")
        ticker = j.get("ticker", "")
        status = j.get("status", "pending")
        icon = _STATUS_ICON.get(status, status)
        stage = j.get("current_stage") or "—"
        elapsed_str = _format_elapsed(j.get("elapsed") or 0.0)
        signal = j.get("signal") or ""

        c1, c2, c3, c4, c5, c6 = st.columns([1.2, 0.8, 1.4, 0.8, 1.0, 2.0])
        c1.markdown(f"`{ticker}`")
        c2.markdown(f"{icon} {status}")
        c3.markdown(stage)
        c4.markdown(elapsed_str)
        if signal:
            kind = _signal_kind(signal)
            c5.html(
                f'<span class="bb-signal bb-signal--{kind}">{signal}</span>'
            )
        else:
            c5.markdown("—")

        # Action cell: retry for errors, view for completed.
        with c6:
            if status == "error":
                err_msg = j.get("error") or "未知错误"
                with st.popover(f"🔄 重试 {ticker}", use_container_width=True):
                    st.markdown(f"**错误信息**\n\n```\n{err_msg[:500]}\n```")
                    if st.button(
                        "确认重试",
                        key=f"retry_{job_id}",
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            r = requests.post(
                                f"{BACKEND_URL}/api/jobs/{job_id}/retry",
                                timeout=5,
                            )
                            if r.status_code == 200:
                                st.success(f"已重新入队: {ticker}")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(f"重试失败 ({r.status_code}): {r.text}")
                        except requests.RequestException as exc:
                            st.error(f"网络错误: {exc}")
            elif status == "completed":
                if st.button(
                    f"📄 查看报告 {ticker}",
                    key=f"view_{job_id}",
                    use_container_width=True,
                ):
                    results_path = _results_path_for_job(j)
                    if results_path:
                        st.session_state["batch_viewing_report"] = results_path
                        st.rerun()
                    else:
                        st.warning(
                            f"找不到 {ticker}/{j.get('trade_date')} 的报告文件,"
                            "请到「历史」页查看。"
                        )
            else:
                st.markdown("&nbsp;", unsafe_allow_html=True)