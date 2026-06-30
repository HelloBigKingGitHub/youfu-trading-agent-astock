"""Real-time progress display for the analysis pipeline."""

from __future__ import annotations

import streamlit as st

from web.progress import PIPELINE_STAGES, ProgressTracker


def _status_badge(status: str) -> str:
    if status == "done":
        return '<span class="bb-stage-badge bb-stage-badge--done">●</span>'
    if status == "active":
        return '<span class="bb-stage-badge bb-stage-badge--active">◉</span>'
    return '<span class="bb-stage-badge bb-stage-badge--pending">○</span>'


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def render_progress(tracker: ProgressTracker) -> None:
    """Render the pipeline progress panel."""

    st.html(
        f"""
        <div class="bb-progress-title">
            <span class="bb-progress-title-text">分析进行中</span>
            <span class="bb-progress-ticker">{tracker.ticker}</span>
        </div>
        """
    )

    completed = len(tracker.completed_stages)
    total = len(PIPELINE_STAGES)
    pct = completed / total if total else 0
    st.progress(pct, text=f"{completed}/{total} 阶段完成  ·  {_format_time(tracker.elapsed)}")

    analyst_stages = PIPELINE_STAGES[:7]
    post_stages = PIPELINE_STAGES[7:]

    st.html('<div class="bb-section-label">ANALYSTS</div>')

    cols = st.columns(len(analyst_stages))
    for col, stage in zip(cols, analyst_stages):
        status = tracker.stage_status(stage["id"])
        badge = _status_badge(status)
        label_cls = "bb-stage-label bb-stage-label--active" if status == "active" else "bb-stage-label bb-stage-label--pending" if status == "pending" else "bb-stage-label bb-stage-label--done"
        col.html(
            f"""
            <div class="bb-stage-cell">
                {badge}<br>
                <span class="{label_cls}">{stage['name']}</span>
            </div>
            """
        )

    st.html('<div class="bb-section-label">PIPELINE</div>')

    cols2 = st.columns(len(post_stages))
    for col, stage in zip(cols2, post_stages):
        status = tracker.stage_status(stage["id"])
        badge = _status_badge(status)
        label_cls = "bb-stage-label bb-stage-label--lg bb-stage-label--active" if status == "active" else "bb-stage-label bb-stage-label--lg bb-stage-label--pending" if status == "pending" else "bb-stage-label bb-stage-label--lg bb-stage-label--done"
        col.html(
            f"""
            <div class="bb-stage-cell">
                {badge}<br>
                <span class="{label_cls}">{stage['name']}</span>
            </div>
            """
        )

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("LLM 调用", tracker.llm_calls)
    c2.metric("工具调用", tracker.tool_calls)
    c3.metric("输入 Tokens", f"{tracker.tokens_in:,}")
    c4.metric("输出 Tokens", f"{tracker.tokens_out:,}")

    if tracker.error:
        st.error(f"错误: {tracker.error}")

    completed_reports = [
        (stage["name"], stage["icon"], tracker.stage_reports[stage["id"]])
        for stage in PIPELINE_STAGES
        if stage["id"] in tracker.stage_reports
    ]

    if completed_reports:
        st.html(f'<div class="bb-section-label">REPORTS ({len(completed_reports)})</div>')
        for name, icon, report in reversed(completed_reports):
            is_latest = (name == completed_reports[-1][0])
            with st.expander(f"{icon} {name}", expanded=is_latest):
                st.markdown(report[:3000])
