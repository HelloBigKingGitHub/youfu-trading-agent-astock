"""Logs panel — GitHub PR style: ticker list on left, task list on right."""

from __future__ import annotations

import streamlit as st

from backend.core.log_store import TaskSummary, get_log_store


def render_logs_panel() -> None:
    """Entry point called from app.py when nav == "logs"."""
    store = get_log_store()
    tickers = store.list_tickers()
    if not tickers:
        st.info("暂无日志. 完成一次分析后, 日志会自动出现.")
        return

    col1, col2 = st.columns([1, 3], gap="small")
    with col1:
        _render_ticker_list(tickers, store)
    with col2:
        _render_selected_ticker(st.session_state.get("logs_selected_ticker"), store)

    _render_running_tasks()


def _render_ticker_list(tickers: list[str], store) -> None:
    """Left column: vertical list of ticker cards."""
    st.html('<div class="bb-section-label">Tickers</div>')
    for ticker in tickers:
        tasks = store.list_tasks(ticker)
        n = len(tasks)
        latest = tasks[0] if tasks else None
        if latest and latest.signal:
            cls = _signal_to_badge_class(latest.signal)
            signal_badge = f'<span class="bb-card-badge bb-card-badge--{cls}">{latest.signal}</span>'
        else:
            signal_badge = '<span class="bb-card-badge bb-card-badge--neutral">—</span>'

        is_active = st.session_state.get("logs_selected_ticker") == ticker
        css_class = (
            "bb-log-ticker-card bb-log-ticker-card--active"
            if is_active
            else "bb-log-ticker-card"
        )

        st.html(f"""
            <div class="{css_class}">
                <div class="bb-log-ticker-card-row">
                    <div class="bb-log-ticker-name">{ticker}</div>
                    {signal_badge}
                </div>
                <div class="bb-log-ticker-count">{n} runs</div>
            </div>
        """)
        if st.button(
            f"查看 {ticker}",
            key=f"logs_pick_{ticker}",
            use_container_width=True,
        ):
            st.session_state["logs_selected_ticker"] = ticker
            st.rerun()


def _render_selected_ticker(ticker: str | None, store) -> None:
    """Right column: tasks for selected ticker, expandable to show chunks."""
    if not ticker:
        st.caption("← 选择左侧 ticker 查看任务")
        return

    st.html(f'<div class="bb-section-label">Tasks for {ticker}</div>')
    tasks = store.list_tasks(ticker)
    if not tasks:
        st.caption("此 ticker 暂无任务")
        return

    for task in tasks:
        _render_task_card(task, ticker, store)


def _render_task_card(task: TaskSummary, ticker: str, store) -> None:
    """Single task: status + signal + expandable chunks."""
    if task.signal:
        cls = _signal_to_badge_class(task.signal)
        signal_badge = f'<span class="bb-card-badge bb-card-badge--{cls}">{task.signal}</span>'
    else:
        signal_badge = '<span class="bb-card-badge bb-card-badge--neutral">—</span>'

    status_badge = {
        "running": '<span class="bb-status bb-status--running">运行中</span>',
        "completed": '<span class="bb-status bb-status--completed">完成</span>',
        "error": '<span class="bb-status bb-status--error">失败</span>',
    }.get(task.status, '<span class="bb-status">—</span>')

    counts = task.chunk_counts
    counts_text = (
        f"LLM {counts.get('llm', 0)} · Tool {counts.get('tool', 0)}"
        f" · Output {counts.get('agent_output', 0)}"
    )

    title = f"{task.trade_date}  {status_badge}  {signal_badge}  {counts_text}"

    with st.expander(title, expanded=(task.status == "running")):
        st.html(f"""
            <div class="bb-log-meta">
                <div><b>Status</b>: {task.status}</div>
                <div><b>Signal</b>: {task.signal or "—"}</div>
                <div><b>Elapsed</b>: {task.elapsed_sec:.1f}s</div>
                <div><b>Started</b>: {task.started_at}</div>
                <div><b>Chunks</b>: {counts_text}</div>
            </div>
        """)

        if task.is_legacy:
            st.caption(
                "⚠️ Legacy task (pre-v0.3.0). 完整 state 在 "
                ".tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_*.json"
            )
        else:
            for chunk in store.stream_chunks(ticker, task.task_dir_name):
                _render_chunk_card(chunk)


def _render_chunk_card(chunk) -> None:
    """Single chunk card: header + content."""
    if chunk.type == "llm":
        icon = "🧠"
        title = f"LLM  ·  {chunk.agent}"
        if chunk.tokens_in or chunk.tokens_out:
            title += f"  ·  tokens {chunk.tokens_in}/{chunk.tokens_out}"
    elif chunk.type == "tool":
        icon = "🔧"
        title = f"Tool  ·  {chunk.agent}  ·  {chunk.tool}"
    else:
        icon = "📄"
        title = f"Output  ·  {chunk.agent}  ·  {chunk.report_key}"

    with st.container(border=False):
        st.html(f'<div class="bb-log-chunk-header">{icon}  {title}</div>')
        if chunk.type == "tool":
            with st.expander("input", expanded=False):
                st.json(chunk.input or {})
            with st.expander("output", expanded=False):
                st.code(chunk.output or "", language="text")
        else:
            st.code(chunk.content or "", language="markdown")
        st.html('<div class="bb-log-chunk-sep"></div>')


def _render_running_tasks() -> None:
    """Top section: tasks currently running in-memory (from web.progress.tracker)."""
    tracker = st.session_state.get("tracker")
    if not tracker or not tracker.is_running:
        return
    st.html('<div class="bb-section-label">🔥 运行中</div>')
    st.html(f"""
        <div class="bb-log-running-card">
            <div><b>{tracker.ticker}</b> · {tracker.trade_date}</div>
            <div class="bb-log-running-stages">
                Completed: {len(tracker.completed_stages)} / 12 stages
            </div>
            <div class="bb-log-running-stats">
                LLM: {tracker.llm_calls}  ·  Tool: {tracker.tool_calls}
                 ·  Tokens: {tracker.tokens_in}/{tracker.tokens_out}
            </div>
        </div>
    """)
    st.caption("运行中任务的实时 chunk 会在完成后落到磁盘, 届时刷新页面查看完整日志.")


def _signal_to_badge_class(signal: str) -> str:
    s = (signal or "").strip().lower()
    if s in ("buy", "bull", "long", "overweight"):
        return "bull"
    if s in ("sell", "bear", "short", "underweight"):
        return "bear"
    if s == "hold":
        return "hold"
    return "neutral"