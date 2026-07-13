"""⏰ 定时分析 主页面 — 4 段布局 (列表 / 编辑 dialog / 历史 / 全局状态).

Sidebar 第 9 按钮的落点。整个页面是「随时可配置」的定时任务中心，而不是
一次性 dialog：用户在这里新增 / 编辑 / 启停 / 删除 schedule，查看运行历史，
以及控制后台调度器的启停。

设计对齐 v0.5.0 portfolio_panel:
  - 4 段布局
  - Bloomberg 暗色主题 (.bb-schedule-* class)
  - ``st.session_state`` 传 schedule_id (不用 query_params)

复用:
  - ``backend.core.scheduler.Scheduler`` 单例 (CRUD / run_now / list_runs / start / stop)
  - ``web.components.schedule_dialogs`` (新增/编辑 modal)

自动刷新 (10s) 用 ``time.sleep + st.rerun`` (MVP，不引 streamlit-autorefresh)，
抽成 ``_auto_refresh()`` 以便单测 patch 掉、避免阻塞。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import streamlit as st

from backend.core.scheduler import RunStatus, Schedule, Scheduler, ScheduleRun, SourceType

logger = logging.getLogger(__name__)

_AUTO_REFRESH_SECONDS = 10
_RUNS_HISTORY_LIMIT = 20

_STATUS_EMOJI: dict[str, str] = {
    RunStatus.OK.value: "🟢",
    RunStatus.PARTIAL.value: "🟡",
    RunStatus.ERROR.value: "🔴",
    RunStatus.SKIPPED.value: "⚪",
    RunStatus.NEVER.value: "—",
    "running": "🔵",
}

_SOURCE_LABELS: dict[str, str] = {
    SourceType.PORTFOLIO.value: "持仓",
    SourceType.WATCHLIST.value: "自选股",
    SourceType.MANUAL.value: "手动",
}


# ── Pure helpers (no streamlit, unit-testable) ───────────────────────────


def format_ts(ts: float | None) -> str:
    """Format a unix ts as ``YYYY-MM-DD HH:MM:SS``; ``—`` when None/0."""
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "—"


def source_summary(sched: Schedule) -> str:
    """Human-readable one-liner for a schedule's ticker source."""
    src = (
        sched.source_type.value
        if isinstance(sched.source_type, SourceType)
        else sched.source_type
    )
    label = _SOURCE_LABELS.get(src, src)
    if src == SourceType.WATCHLIST.value:
        tag = sched.source_config.get("tag")
        return f"{label} · {tag}" if tag else label
    if src == SourceType.MANUAL.value:
        tickers = sched.source_config.get("tickers", [])
        return f"{label} · {len(tickers)} 只"
    return label


def status_emoji(status: str) -> str:
    """Map a RunStatus value to its status emoji."""
    return _STATUS_EMOJI.get(status, "—")


def status_dot_class(enabled: bool) -> str:
    """CSS modifier class for the enabled/paused status dot."""
    return "bb-schedule-status-dot--on" if enabled else "bb-schedule-status-dot--off"


# ── Section 1: toolbar ────────────────────────────────────────────────────


def _render_toolbar(mgr: Scheduler) -> None:
    cols = st.columns([2, 1, 1, 1])
    with cols[0]:
        st.markdown("## ⏰ 定时分析")
    with cols[1]:
        if st.button("➕ 新增", key="sched_tb_add", use_container_width=True):
            st.session_state["schedule_dialog_open"] = True
            st.session_state["schedule_edit_id"] = None
            st.rerun()
    with cols[2]:
        if st.button("▶ 立即跑全部", key="sched_tb_run_all", use_container_width=True):
            _run_all(mgr)
    with cols[3]:
        if st.button("⟳ 刷新", key="sched_tb_reload", use_container_width=True):
            st.rerun()


def _run_all(mgr: Scheduler) -> None:
    enabled = mgr.list_schedules(enabled_only=True)
    if not enabled:
        st.warning("没有启用中的定时任务")
        return
    n = 0
    for s in enabled:
        try:
            mgr.run_now(s.schedule_id)
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("run_now 失败 %s: %s", s.schedule_id, exc)
            st.error(f"{s.name} 触发失败: {exc}")
    if n:
        st.success(f"已触发 {n} 个任务")


# ── Section 2: schedule list ──────────────────────────────────────────────


def _render_schedule_list(mgr: Scheduler) -> None:
    schedules = mgr.list_schedules()
    if not schedules:
        st.markdown(
            '<div class="bb-schedule-empty">👋 暂无定时任务，点 ➕新增 创建第一个</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown('<div class="bb-schedule-card">', unsafe_allow_html=True)
    header = st.columns([2, 2, 2, 1, 2, 2])
    for col, label in zip(
        header, ["名称", "cron", "源", "启用", "上次", "操作"]
    ):
        col.markdown(f'<div class="bb-schedule-th">{label}</div>',
                     unsafe_allow_html=True)

    for s in schedules:
        _render_schedule_row(mgr, s)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_schedule_row(mgr: Scheduler, s: Schedule) -> None:
    c = st.columns([2, 2, 2, 1, 2, 2])
    c[0].markdown(f'<div class="bb-schedule-td">{s.name}</div>',
                  unsafe_allow_html=True)
    c[1].markdown(
        f'<span class="bb-schedule-cron-pill">{s.cron_expr}</span>',
        unsafe_allow_html=True,
    )
    c[2].markdown(f'<div class="bb-schedule-td">{source_summary(s)}</div>',
                  unsafe_allow_html=True)
    dot = status_dot_class(s.enabled)
    c[3].markdown(
        f'<span class="bb-schedule-status-dot {dot}"></span>',
        unsafe_allow_html=True,
    )
    c[4].markdown(
        f'<div class="bb-schedule-td">{status_emoji(s.last_run_status)} '
        f'{format_ts(s.last_run_at)}</div>',
        unsafe_allow_html=True,
    )
    with c[5]:
        op = st.columns(4)
        if op[0].button("✎", key=f"sched_edit_{s.schedule_id}",
                        help="编辑"):
            st.session_state["schedule_dialog_open"] = True
            st.session_state["schedule_edit_id"] = s.schedule_id
            st.rerun()
        toggle_icon = "⏸" if s.enabled else "▶"
        if op[1].button(toggle_icon, key=f"sched_toggle_{s.schedule_id}",
                        help="启用/暂停"):
            if s.enabled:
                mgr.pause_schedule(s.schedule_id)
            else:
                mgr.resume_schedule(s.schedule_id)
            st.rerun()
        if op[2].button("▷", key=f"sched_runnow_{s.schedule_id}",
                        help="立即跑"):
            try:
                bid = mgr.run_now(s.schedule_id)
                st.success(f"已触发: {bid}")
            except KeyError as exc:
                st.error(f"触发失败: {exc}")
        if op[3].button("🗑", key=f"sched_del_{s.schedule_id}",
                        help="删除"):
            st.session_state["schedule_delete_id"] = s.schedule_id
            st.rerun()


# ── delete confirmation dialog ─────────────────────────────────────────────


@st.dialog("🗑️ 确认删除定时任务")
def _delete_dialog(mgr: Scheduler, schedule_id: str) -> None:
    s = mgr.get_schedule(schedule_id)
    if s is None:
        st.error("任务不存在（可能已被删除）")
        if st.button("关闭", key=f"sched_del_missing_{schedule_id}",
                     use_container_width=True):
            st.session_state.pop("schedule_delete_id", None)
            st.rerun()
        return
    st.warning(
        f"**{s.name}**\n\n"
        f"cron: {s.cron_expr}\n\n"
        f"源: {source_summary(s)}"
    )
    st.error("⚠️ 删除后无法恢复！")
    col1, col2 = st.columns(2)
    if col1.button("确认删除", type="primary",
                   key=f"sched_del_confirm_{schedule_id}",
                   use_container_width=True):
        mgr.delete_schedule(schedule_id)
        st.session_state.pop("schedule_delete_id", None)
        st.success(f"已删除 {s.name}")
        st.rerun()
    if col2.button("取消", key=f"sched_del_cancel_{schedule_id}",
                   use_container_width=True):
        st.session_state.pop("schedule_delete_id", None)
        st.rerun()


# ── Section 3: runs history ─────────────────────────────────────────────────


def _render_runs_history(mgr: Scheduler) -> None:
    st.markdown("### 📜 运行历史")
    try:
        runs = mgr.list_runs(limit=_RUNS_HISTORY_LIMIT)
    except Exception as exc:  # noqa: BLE001
        st.error(f"读取运行历史失败: {exc}")
        return
    if not runs:
        st.markdown(
            '<div class="bb-schedule-empty">暂无运行记录</div>',
            unsafe_allow_html=True,
        )
        return
    name_by_id = {s.schedule_id: s.name for s in mgr.list_schedules()}
    for r in runs:
        name = name_by_id.get(r.schedule_id, r.schedule_id)
        st.markdown(
            f'<div class="bb-schedule-history-row">'
            f'{status_emoji(r.status)} <b>{name}</b> · '
            f'{format_ts(r.started_at)} · {r.ticker_count} 只 · '
            f'{r.duration:.1f}s · {r.summary or r.error or ""}'
            f'</div>',
            unsafe_allow_html=True,
        )


# ── Section 4: global status ─────────────────────────────────────────────────


def _render_global_status(mgr: Scheduler) -> None:
    st.markdown("### 🖥️ 调度器状态")
    running = mgr.is_running()
    schedules = mgr.list_schedules(enabled_only=True)
    next_runs = [
        s.next_run_at() for s in schedules if s.next_run_at() is not None
    ]
    next_run = min(next_runs) if next_runs else None

    dot = "🟢 运行中" if running else "🔴 已停止"
    st.markdown(
        f'<div class="bb-schedule-card">'
        f'<div class="bb-schedule-td">调度器: <b>{dot}</b></div>'
        f'<div class="bb-schedule-td">上次 tick: {format_ts(mgr.last_tick_at())}</div>'
        f'<div class="bb-schedule-td">下次执行: {format_ts(next_run)}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    if col1.button("⏸ 停止调度器", key="sched_stop", use_container_width=True,
                   disabled=not running):
        mgr.stop()
        st.rerun()
    if col2.button("▶ 启动调度器", key="sched_start", use_container_width=True,
                   disabled=running):
        mgr.start()
        st.rerun()


# ── auto refresh (extracted so tests can stub it) ───────────────────────────


def _auto_refresh() -> None:
    """MVP 10s auto-refresh via sleep+rerun (no streamlit-autorefresh dep)."""
    time.sleep(_AUTO_REFRESH_SECONDS)
    st.rerun()


# ── Main entry ──────────────────────────────────────────────────────────────


def render_schedule_panel() -> None:
    """Top-level entry — called from ``web/app.py`` when ``view == "schedule"``."""
    mgr = Scheduler.get_instance()

    _render_toolbar(mgr)
    st.caption(
        "随时配置定时分析任务：cron 触发 → 拉取 ticker (持仓/自选股/手动) → "
        "批量分析 → 多渠道通知。调度器后台运行，无需常开本页。"
    )

    _render_schedule_list(mgr)

    # Section 2: add/edit dialog (opened via session_state flag)
    if st.session_state.get("schedule_dialog_open"):
        try:
            from web.components.schedule_dialogs import open_schedule_dialog
            open_schedule_dialog(st.session_state.get("schedule_edit_id"))
        except Exception as exc:  # noqa: BLE001
            # Bare mode (testing/no ScriptRunContext): dialog open() raises;
            # log + skip instead of crashing the whole panel.
            import logging
            logging.getLogger(__name__).debug("dialog skipped: %s", exc)

    # delete confirmation dialog
    if st.session_state.get("schedule_delete_id"):
        try:
            _delete_dialog(mgr, st.session_state["schedule_delete_id"])
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).debug(
                "delete_dialog skipped (no ScriptRunContext?): %s", exc
            )

    st.markdown("<div class='bb-sidebar-sep'></div>", unsafe_allow_html=True)
    _render_runs_history(mgr)

    st.markdown("<div class='bb-sidebar-sep'></div>", unsafe_allow_html=True)
    _render_global_status(mgr)

    _auto_refresh()


__all__ = [
    "render_schedule_panel",
    "format_ts",
    "source_summary",
    "status_emoji",
    "status_dot_class",
]
