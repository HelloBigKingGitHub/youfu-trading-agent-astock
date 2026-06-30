"""History panel — full list with search/filter and delete."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import streamlit as st

_HISTORY_DIR = Path.home() / ".tradingagents" / "logs" / "history"

_SIGNAL_LABELS = {
    "Buy": "🟢 买入",
    "Sell": "🔴 卖出",
    "Hold": "🟡 持有",
    "Overweight": "🟢 超配",
    "Underweight": "🔴 低配",
}


def _load_entries() -> list[dict]:
    """Load all history entries from disk."""
    if not _HISTORY_DIR.exists():
        return []
    entries = []
    for f in _HISTORY_DIR.glob("*.json"):
        try:
            entries.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    entries.sort(key=lambda e: e.get("created_at", 0), reverse=True)
    return entries


def _signal_class(signal: str) -> str:
    s = signal.upper() if signal else ""
    if "BUY" in s or "OVERWEIGHT" in s:
        return "bb-signal bb-signal--buy"
    if "SELL" in s or "UNDERWEIGHT" in s:
        return "bb-signal bb-signal--sell"
    if "HOLD" in s:
        return "bb-signal bb-signal--hold"
    return "bb-signal bb-signal--neutral"


def _status_class(status: str) -> str:
    if status == "completed":
        return "bb-status bb-status--completed"
    if status == "error":
        return "bb-status bb-status--error"
    return "bb-status bb-status--running"


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def render_history_panel() -> None:
    """Render the full history management panel."""

    st.html(
        """
        <div class="bb-h1">
            <div class="bb-h1-title">📋 历史记录</div>
            <div class="bb-h1-subtitle">管理所有历史分析记录</div>
        </div>
        """
    )

    # Load entries
    entries = _load_entries()

    # Filters
    col_ticker, col_signal, col_status = st.columns([1, 1, 1])
    with col_ticker:
        ticker_filter = st.text_input(
            "股票代码",
            placeholder="搜索...",
            key="hist_ticker_filter",
        ).strip().upper()
    with col_signal:
        signal_filter = st.selectbox(
            "信号",
            ["全部", "Buy", "Sell", "Hold", "Overweight", "Underweight"],
            key="hist_signal_filter",
        )
        if signal_filter == "全部":
            signal_filter = ""
    with col_status:
        status_filter = st.selectbox(
            "状态",
            ["全部", "已完成", "失败", "进行中"],
            key="hist_status_filter",
        )
        status_map = {"全部": "", "已完成": "completed", "失败": "error", "进行中": "running"}
        status_filter = status_map.get(status_filter, "")

    # Apply filters
    filtered = []
    for e in entries:
        ticker = e.get("ticker", "")
        signal = e.get("signal", "")
        status = e.get("status", "")

        if ticker_filter and ticker_filter not in ticker.upper():
            continue
        if signal_filter and signal_filter != signal:
            continue
        if status_filter and status_filter != status:
            continue
        filtered.append(e)

    # Debug info
    with st.expander("🔧 调试信息", expanded=False):
        st.write(f"文件数: {len(list(_HISTORY_DIR.glob('*.json')))}")
        st.write(f"entries: {len(entries)}, filtered: {len(filtered)}")
        for e in entries:
            status = e.get("status", "")
            stages = e.get("completed_stages", [])
            can_retry = status in ("error", "pending") or (status == "running" and not stages)
            st.write(f"  {e.get('ticker')} {e.get('trade_date')} | status={status} | stages={len(stages)} | can_retry={can_retry}")

    st.markdown(f"**共 {len(filtered)} 条记录**")

    if not filtered:
        st.info("暂无历史记录")
        return

    # Table header
    header_cols = st.columns([2, 1, 1, 1, 1, 1, 1, 1])
    header_labels = ["股票 · 日期", "信号", "状态", "耗时", "阶段", "错误", "重试", "操作"]
    for col, label in zip(header_cols, header_labels):
        col.markdown(f"**{label}**")

    st.markdown("---")

    for entry in filtered:
        aid = entry.get("analysis_id", "")
        ticker = entry.get("ticker", "")
        trade_date = entry.get("trade_date", "")
        signal = entry.get("signal", "")
        status = entry.get("status", "")
        elapsed = entry.get("elapsed", 0)
        completed_stages = entry.get("completed_stages", [])
        error = entry.get("error", "")

        cols = st.columns([2, 1, 1, 1, 1, 1, 1, 1])

        # Ticker + date
        with cols[0]:
            st.html(
                f"""
                <div class="bb-table-cell">{ticker}</div>
                <div class="bb-table-cell bb-table-cell--date">{trade_date}</div>
                <div class="bb-table-cell bb-table-cell--id">{aid[-8:]}</div>
                """
            )

        # Signal
        with cols[1]:
            cls = _signal_class(signal)
            label = _SIGNAL_LABELS.get(signal, signal or "-")
            st.html(f'<div class="{cls}">{label}</div>')

        # Status
        with cols[2]:
            cls = _status_class(status)
            label = {"completed": "✅ 已完成", "error": "❌ 失败", "running": "🔄 进行中"}.get(status, "-")
            st.html(f'<div class="{cls}">{label}</div>')

        # Elapsed
        with cols[3]:
            st.markdown(f"`{_format_time(elapsed)}`")

        # Stages
        with cols[4]:
            count = len(completed_stages)
            st.markdown(f"`{count}`")

        # Error
        with cols[5]:
            if error:
                st.html(
                    f'<div class="bb-table-error" title="{error}">🔴 {error[:30]}</div>'
                )
            else:
                st.markdown("-")

        # Retry button (rightmost column)
        with cols[6]:
            can_retry = status in ("error", "pending") or (status == "running" and not completed_stages)
            if can_retry:
                if st.button("🔄", key=f"retry_{aid}", help="重新分析"):
                    # Delete the old history entry (new analysis will create a fresh one)
                    old_path = _HISTORY_DIR / f"{aid}.json"
                    if old_path.exists():
                        old_path.unlink()
                    # Trigger the analyze tab to start a fresh analysis
                    st.session_state["start_analysis"] = {
                        "ticker": ticker,
                        "trade_date": trade_date,
                    }
                    st.session_state["viewing_history"] = None
                    st.session_state["nav"] = "analyze"
                    st.rerun()
            else:
                st.markdown("")

        # Actions: view + delete
        with cols[7]:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📄", key=f"v_{aid}", help="查看报告"):
                    # Prefer results_path from entry; fall back to ticker-specific search
                    results_path = entry.get("results_path", "")
                    if not results_path or not Path(results_path).exists():
                        log_root = Path.home() / ".tradingagents" / "logs"
                        candidate = log_root / ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json"
                        results_path = str(candidate) if candidate.exists() else ""
                    if results_path and Path(results_path).exists():
                        st.session_state["viewing_history"] = results_path
                        st.session_state["nav"] = "analyze"
                        st.rerun()
                    else:
                        st.warning("找不到原始报告文件")
            with c2:
                if st.button("🗑️", key=f"d_{aid}", help="删除"):
                    path = _HISTORY_DIR / f"{aid}.json"
                    if path.exists():
                        path.unlink()
                    st.rerun()

        # Stage progress bar (for running jobs)
        if status == "running" and completed_stages:
            stage_count = len(completed_stages)
            total_stages = 11
            pct = stage_count / total_stages
            st.progress(pct, text=f"🔄 {stage_count}/{total_stages} 阶段完成")
            current = entry.get("current_stage", "")
            if current:
                st.caption(f"📍 当前: {current}")

        st.markdown("---")