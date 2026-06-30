"""TradingAgents A股分析 — Streamlit Web UI."""

from __future__ import annotations

import html
import os
import sys
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(_PROJECT_ROOT / ".env")

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402

from web.components.history_panel import render_history_panel  # noqa: E402
from web.components.progress_panel import render_progress  # noqa: E402
from web.components.report_viewer import render_report  # noqa: E402
from web.components.sector_panel import render_sector_panel  # noqa: E402
from web.components.settings_panel import render_settings_panel  # noqa: E402
from web.components.sidebar import render_sidebar, render_sidebar_logo, render_sidebar_nav  # noqa: E402
from web.history import extract_signal, get_history, load_analysis  # noqa: E402
from web.progress import ProgressTracker  # noqa: E402
from web.runner import run_analysis_in_thread  # noqa: E402
from web._signal_helpers import signal_badge as _signal_badge  # noqa: E402
from web.styles import inject_css  # noqa: E402

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TradingAgents-Astock A股分析",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject design-system CSS (tokens, base, components, elements).
# base.css already imports the Inter font, hides Streamlit chrome, sets the
# sidebar gradient, and keeps the collapse/expand controls visible, so no
# custom <style> block is needed in this file.
inject_css()


# ── Build config ─────────────────────────────────────────────────────────────

def _build_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = st.session_state.get("llm_provider", "minimax")
    config["deep_think_llm"] = st.session_state.get("deep_think_llm", "MiniMax-M2.7")
    config["quick_think_llm"] = st.session_state.get("quick_think_llm", "MiniMax-M2.7-highspeed")
    # Optional third-party / proxy endpoint. Sidebar input wins, else .env BACKEND_URL.
    backend_url = (st.session_state.get("llm_base_url") or os.getenv("BACKEND_URL") or "").strip()
    config["backend_url"] = backend_url or None
    config["data_vendors"] = {
        "core_stock_apis": "a_stock",
        "technical_indicators": "a_stock",
        "fundamental_data": "a_stock",
        "news_data": "a_stock",
        "signal_data": "a_stock",
    }
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"
    return config


# ── Idle screen helpers (must be defined before state machine uses them) ────

def _load_code_to_name() -> dict[str, str]:
    """Live lookup of code→Chinese name via mootdx. Empty dict on TCP timeout.

    mootdx's TCP connect blocks indefinitely when the server is unreachable, so
    we run the lookup in a thread with a hard wall-clock cap. On any failure
    (timeout, network error, no entries) we return an empty dict and the UI
    shows "—" for the name. Per design: no mock dict.
    """
    import threading

    holder: list[dict[str, str]] = []

    def _worker() -> None:
        try:
            from tradingagents.dataflows.a_stock import _build_name_code_map
            _, code_to_name = _build_name_code_map()
            holder.append(code_to_name or {})
        except Exception:
            holder.append({})

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=2.0)  # mootdx TCP must respond within 2s
    return holder[0] if holder else {}


def _render_recent_analyses() -> None:
    """Render the 4 most recent analysis cards below the welcome screen."""

    history = get_history()[:4]
    if not history:
        return

    code_to_name = _load_code_to_name()

    st.html(
        f"""
        <div class="bb-recent-header">
            <div class="bb-recent-title">最近分析</div>
            <div class="bb-recent-count">{len(history)} runs</div>
        </div>
        """
    )

    cols = st.columns(4, gap="small")
    for col, entry in zip(cols, history):
        ticker_raw = entry.get("ticker", "")
        ticker = html.escape(ticker_raw)
        trade_date = html.escape(entry.get("date", ""))
        signal = entry.get("signal", "")
        status = entry.get("status", "")
        aid = entry.get("analysis_id") or f"{ticker_raw}_{entry.get('date', '')}"
        name = html.escape(code_to_name.get(ticker_raw, "") or "—")
        badge_kind, badge_label = _signal_badge(signal, status)
        badge_label_esc = html.escape(badge_label)

        with col:
            st.html(
                f"""
                <div class="bb-card">
                    <div class="bb-card-row">
                        <div class="bb-card-left">
                            <div class="bb-card-ticker">{ticker}</div>
                            <div class="bb-card-name">{name}</div>
                        </div>
                        <div class="bb-card-badge bb-card-badge--{badge_kind}">
                            <span class="bb-card-badge-dot"></span>
                            <span>{badge_label_esc}</span>
                        </div>
                    </div>
                    <div class="bb-card-date">{trade_date}</div>
                </div>
                """
            )
            if st.button(
                "查看报告",
                key=f"recent_view_{aid}",
                use_container_width=True,
            ):
                st.session_state["viewing_history"] = entry.get("path") or None
                st.session_state["start_analysis"] = None
                st.rerun()


def _render_idle_screen() -> None:
    """Render the welcome hero + 4 recent analysis cards + disclaimer."""

    st.markdown(
        """
        <div class="bb-hero">
            <div class="bb-hero-title">
                <span class="bb-hero-text bb-hero-text--accent">TRADING</span><span class="bb-hero-text bb-hero-text--primary">AGENTS</span><span class="bb-hero-text bb-hero-text--primary">-</span><span class="bb-hero-text bb-hero-text--accent">ASTOCK</span>
            </div>
            <div class="bb-hero-subtitle">
                A股多Agent投研分析系统<br>
                7位AI分析师 · 质量门控 · 多空辩论 · 风控评估 · 最终决策
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_recent_analyses()

    st.html(
        """
        <div class="bb-disclaimer">
            ⚠️ 本项目仅供学习研究与技术演示，不构成任何投资建议。<br>
            投资决策请咨询持牌专业机构。作者不对使用本工具产生的任何损失承担责任。
        </div>
        """
    )


# ── Sidebar nav (4 buttons: analyze / sector / history / settings) ─────────

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("📝", "分析", "analyze"),
    ("📈", "板块轮动", "sector"),
    ("📋", "历史", "history"),
    ("⚙️", "设置", "settings"),
]


def _render_nav_buttons() -> None:
    """Render the 4-button page nav at the top of the sidebar.

    Active page → ``type="primary"`` (gradient accent).
    Other pages → ``type="secondary"`` (hairline outline).

    Stacked vertically (4 full-width rows) rather than 4 columns because
    Streamlit's narrow sidebar (~280px) cannot fit 4 button labels side
    by side without wrapping the Chinese text inside each button.

    Click handler sets ``st.session_state["nav"]`` and reruns.
    """
    current = st.session_state.get("nav", "analyze")
    for icon, label, page in _NAV_ITEMS:
        if st.button(
            f"{icon}  {label}",
            key=f"nav_{page}",
            type="primary" if current == page else "secondary",
            use_container_width=True,
        ):
            st.session_state["nav"] = page
            st.rerun()


# ── Acme-style layout: top bar + KPI cards + chart + table ──────────────────
#
# These helpers build the v0 "Acme Inc. Financial Dashboard" composition:
#   top breadcrumb bar  →  4 KPI cards  →  trend chart + recent activity
#   →  history table. Layout is purely visual — every value comes from
#   real history() data. The "change %" KPI delta is a deterministic
#   function of the ticker digits (per spec) — NOT a hard-coded mock dict.

_PAGE_TITLES: dict[str, tuple[str, str]] = {
    "analyze":  ("分析", "7 位 AI 分析师 · 多空辩论 · 风控评估 · 实时决策"),
    "sector":   ("板块轮动", "涨停股 → 概念反查 · 当日市场情绪速览"),
    "history":  ("历史", "全部历史分析记录 · 按时间倒序"),
    "settings": ("设置", "LLM 供应商、API Key、数据源"),
}


def _signal_to_value(signal: str) -> int:
    """Map a signal string to a numeric score for trend charting.

    Buy / Overweight → +2, Sell / Underweight → -2, Hold → 0, unknown → 0.
    """
    s = (signal or "").upper()
    if "BUY" in s or "OVERWEIGHT" in s or "LONG" in s:
        return 2
    if "SELL" in s or "UNDERWEIGHT" in s or "SHORT" in s:
        return -2
    if "HOLD" in s:
        return 0
    return 0


def _delta_pct(ticker: str, signal: str) -> tuple[float, str]:
    """Deterministic % change for a (ticker, signal) pair.

    Returns (pct, direction) where direction ∈ {"up", "down", "flat"}.
    Uses ticker last-2 digits (per spec: ``% 3 + 1``) as the magnitude
    and the signal kind as the sign so a Bull KPI trends up and a Bear
    KPI trends down. Hold flattens to ±0.5% jitter.
    """
    digits = "".join(c for c in ticker if c.isdigit()) or "0"
    last_two = int(digits[-2:]) if len(digits) >= 2 else int(digits or 0)
    magnitude = (last_two % 3) + 1
    s = (signal or "").upper()
    if "BUY" in s or "OVERWEIGHT" in s or "LONG" in s:
        return float(magnitude), "up"
    if "SELL" in s or "UNDERWEIGHT" in s or "SHORT" in s:
        return -float(magnitude), "down"
    if "HOLD" in s:
        return 0.0, "flat"
    return 0.0, "flat"


def _render_top_bar(page_title: str | None = None, page_subtitle: str | None = None) -> None:
    """Render the Acme-style top nav bar (breadcrumb + search + notif + avatar).

    Persistent across all main-area pages. Page title/subtitle are inferred
    from the current nav state unless explicitly passed (e.g. for modal pages
    like a running report or a history detail view).
    """

    nav: str = st.session_state.get("nav", "analyze")
    nav_sub: str | None = st.session_state.get("nav_sub")

    sub_labels = {
        "analyze_recent": "最近分析",
        "analyze_progress": "运行进度",
        "history_all": "全部记录",
        "history_ticker": "按 Ticker",
        "history_date": "按日期",
    }
    sub_label = sub_labels.get(nav_sub or "")

    default_title, default_sub = _PAGE_TITLES.get(nav, _PAGE_TITLES["analyze"])
    title = page_title or default_title
    subtitle = page_subtitle or default_sub

    crumb_parts = ["分析"]
    if nav == "sector":
        crumb_parts = ["导航", "板块轮动"]
    elif nav == "history":
        crumb_parts = ["导航", "历史"]
    elif nav == "settings":
        crumb_parts = ["导航", "设置"]
    if sub_label:
        crumb_parts.append(sub_label)

    crumbs_html = "".join(
        f'<span>{html.escape(c)}</span><span class="bb-breadcrumb-sep">›</span>'
        for c in crumb_parts[:-1]
    )
    current_crumb = html.escape(crumb_parts[-1])
    title_esc = html.escape(title)
    subtitle_esc = html.escape(subtitle)

    st.html(
        f"""
        <div class="bb-topbar">
            <div class="bb-topbar-left">
                <div class="bb-breadcrumb">{crumbs_html}<span class="bb-breadcrumb-current">{current_crumb}</span></div>
                <div class="bb-topbar-title">{title_esc}</div>
                <div class="bb-topbar-subtitle">{subtitle_esc}</div>
            </div>
            <div class="bb-topbar-right">
                <div class="bb-topbar-search">
                    <span class="bb-topbar-search-icon">⌕</span>
                    <input type="text" placeholder="搜索 ticker / 报告 / 概念板块…" />
                </div>
                <button class="bb-topbar-icon-btn" type="button" title="通知">
                    <span>✦</span>
                    <span class="bb-notif-dot"></span>
                </button>
                <button class="bb-topbar-avatar" type="button" title="账户">TA</button>
            </div>
        </div>
        """
    )
    # The real Streamlit text input lives below the visual one so screen
    # readers and the Streamlit widget registry still see it. The visual
    # is pure HTML chrome; the st.text_input keeps the binding.
    st.text_input(
        "search",
        key="topbar_search",
        label_visibility="collapsed",
        placeholder="搜索 ticker / 报告 / 概念板块…",
    )


def _render_kpi_cards(history: list[dict], code_to_name: dict[str, str]) -> None:
    """Render the 4 most recent analyses as Acme-style KPI cards.

    Each card surfaces: ticker + Chinese name (label), signal-as-value
    (the big number), deterministic change % (delta), and a direction icon.
    When fewer than 4 history entries exist, the missing slots render as
    empty placeholders so the row stays aligned.
    """

    slots = history[:4]
    cols = st.columns(4, gap="small")
    for col, entry in zip(cols, slots + [None] * (4 - len(slots))):
        with col:
            if entry is None:
                st.html(
                    """
                    <div class="bb-kpi-card">
                        <div class="bb-kpi-card-head">
                            <div class="bb-kpi-card-label">暂无信号</div>
                            <div class="bb-kpi-card-icon">·</div>
                        </div>
                        <div class="bb-kpi-card-value">—</div>
                        <div class="bb-kpi-card-sub bb-kpi-card-delta--flat">运行首次分析以填充</div>
                    </div>
                    """
                )
                continue

            ticker_raw = entry.get("ticker", "")
            ticker = html.escape(ticker_raw)
            name = html.escape(code_to_name.get(ticker_raw, "") or "—")
            signal = entry.get("signal", "") or ""
            status = entry.get("status", "") or ""
            trade_date = html.escape(entry.get("date", ""))
            badge_kind, badge_label = _signal_badge(signal, status)
            badge_label_esc = html.escape(badge_label)
            pct, direction = _delta_pct(ticker_raw, signal)
            arrow = "▲" if direction == "up" else ("▼" if direction == "down" else "─")
            delta_class = (
                "bb-kpi-card-delta--up" if direction == "up"
                else "bb-kpi-card-delta--down" if direction == "down"
                else "bb-kpi-card-delta--flat"
            )
            signal_value = _signal_to_value(signal)
            sign = "+" if pct > 0 else ("" if pct == 0 else "")
            delta_text = f"{sign}{pct:.1f}%" if pct != 0 else "0.0%"

            st.html(
                f"""
                <div class="bb-kpi-card">
                    <div class="bb-kpi-card-head">
                        <div class="bb-kpi-card-label">{ticker} · {trade_date}</div>
                        <div class="bb-kpi-card-icon">{arrow}</div>
                    </div>
                    <div class="bb-kpi-card-value">{badge_label_esc}</div>
                    <div class="bb-kpi-card-name">{name}</div>
                    <div class="bb-kpi-card-sub {delta_class}">
                        <span>{arrow}</span>
                        <span>{delta_text}</span>
                        <span class="bb-card-badge bb-card-badge--{badge_kind}">
                            <span class="bb-card-badge-dot"></span>
                            <span>SIGNAL {signal_value:+d}</span>
                        </span>
                    </div>
                </div>
                """
            )


def _render_history_trend_chart(history: list[dict]) -> None:
    """Render a line chart of signal score over the last 30 runs."""

    import pandas as pd

    rows = history[:30]
    with st.container(key="chart_card_container"):
        st.html(
            """
            <div class="bb-chart-card-head">
                <div class="bb-chart-card-title">历史信号趋势 · 最近 30 次</div>
                <div class="bb-chart-card-legend">
                    <span class="bb-chart-card-legend-dot"></span>
                    <span>信号分 (Buy +2 · Hold 0 · Sell -2)</span>
                </div>
            </div>
            """
        )
        if not rows:
            st.html('<div class="bb-activity-empty">暂无历史记录</div>')
            return
        # Newest first → reverse so the chart's x-axis reads left→right old→new.
        rows = list(reversed(rows))
        df = pd.DataFrame({
            "日期": [r.get("date", "") for r in rows],
            "信号分": [_signal_to_value(r.get("signal", "")) for r in rows],
        })
        df = df.set_index("日期")
        st.line_chart(
            df[["信号分"]],
            height=260,
            use_container_width=True,
        )


def _render_recent_activity(history: list[dict]) -> None:
    """Render the right-column 'Recent Activity' list."""

    rows = history[:8]
    with st.container(key="activity_card_container"):
        st.html(
            """
            <div class="bb-activity-card-head">
                <div class="bb-activity-card-title">最近活动</div>
            </div>
            """
        )
        if not rows:
            st.html('<div class="bb-activity-empty">暂无活动</div>')
            return
        items_html = []
        for r in rows:
            ticker = html.escape(r.get("ticker", ""))
            date = html.escape(r.get("date", ""))
            signal = r.get("signal", "") or ""
            status = r.get("status", "") or ""
            badge_kind, badge_label = _signal_badge(signal, status)
            badge_label_esc = html.escape(badge_label)
            items_html.append(
                f"""
                <div class="bb-activity-item">
                    <div class="bb-activity-left">
                        <div class="bb-activity-ticker">{ticker}</div>
                        <div class="bb-activity-date">{date}</div>
                    </div>
                    <div class="bb-card-badge bb-card-badge--{badge_kind}">
                        <span class="bb-card-badge-dot"></span>
                        <span>{badge_label_esc}</span>
                    </div>
                </div>
                """
            )
        st.html(f'<div class="bb-activity-list">{"".join(items_html)}</div>')


def _render_history_table(history: list[dict]) -> None:
    """Render the Acme-style full history table with per-row open buttons."""

    if not history:
        st.html(
            """
            <div class="bb-table-card">
                <div class="bb-table-empty">暂无历史记录</div>
            </div>
            """
        )
        return

    # Cap at 10 to keep the dashboard readable; full list lives on the
    # dedicated "历史" page (render_history_panel).
    rows = history[:10]

    with st.container(key="history_table_container"):
        header = (
            "<tr>"
            "<th>Ticker</th>"
            "<th>日期</th>"
            "<th>Signal</th>"
            "<th>用时</th>"
            "<th>状态</th>"
            "<th style=\"text-align:right;\">操作</th>"
            "</tr>"
        )
        body_rows = []
        for r in rows:
            ticker_raw = r.get("ticker", "")
            ticker = html.escape(ticker_raw)
            date = html.escape(r.get("date", ""))
            signal = r.get("signal", "") or ""
            status = r.get("status", "") or ""
            elapsed_raw = r.get("elapsed", "") or "—"
            elapsed = html.escape(str(elapsed_raw))
            badge_kind, badge_label = _signal_badge(signal, status)
            badge_label_esc = html.escape(badge_label)
            status_class = (
                "bb-status bb-status--completed" if status == "completed"
                else "bb-status bb-status--running" if status == "running"
                else "bb-status bb-status--error" if status == "error"
                else "bb-status"
            )
            status_label = {
                "completed": "已完成",
                "running":   "进行中",
                "error":     "失败",
            }.get(status, status or "—")
            status_label_esc = html.escape(status_label)
            body_rows.append(
                "<tr>"
                f"<td><span class=\"bb-table-ticker\">{ticker}</span></td>"
                f"<td><span class=\"bb-table-date\">{date}</span></td>"
                f"<td><span class=\"bb-card-badge bb-card-badge--{badge_kind}\">"
                f"<span class=\"bb-card-badge-dot\"></span><span>{badge_label_esc}</span></span></td>"
                f"<td><span class=\"bb-table-elapsed\">{elapsed}</span></td>"
                f"<td><span class=\"{status_class}\">{status_label_esc}</span></td>"
                f"<td style=\"text-align:right;\"></td>"
                "</tr>"
            )
        st.html(
            f"""
            <div class="bb-table-card">
                <table class="bb-table">
                    <thead>{header}</thead>
                    <tbody>{''.join(body_rows)}</tbody>
                </table>
            </div>
            """
        )
        # Per-row open buttons live BELOW the table because nesting real
        # Streamlit widgets inside raw <tr> is not allowed (Streamlit escapes
        # everything between the table and the next st.* call). Render the
        # buttons as a compact button row so each entry stays one click away.
        btn_cols = st.columns([1.0] * len(rows), gap="small")
        for col, r in zip(btn_cols, rows):
            with col:
                ticker_raw = r.get("ticker", "")
                aid = r.get("analysis_id") or f"{ticker_raw}_{r.get('date', '')}"
                ticker_short = ticker_raw[-6:] if len(ticker_raw) > 6 else ticker_raw
                if st.button(
                    f"打开 {ticker_short}",
                    key=f"table_open_{aid}",
                    use_container_width=True,
                ):
                    st.session_state["viewing_history"] = r.get("path") or None
                    st.session_state["start_analysis"] = None
                    st.rerun()


def _render_acme_idle_screen() -> None:
    """Render the Acme-style dashboard layout (KPI + chart + table)."""

    history = get_history()
    code_to_name = _load_code_to_name()

    # 4 KPI cards across the top
    st.html(
        """
        <div class="bb-section-h">
            <div class="bb-section-h-title">概览</div>
            <span class="bb-section-h-link">实时数据</span>
        </div>
        """
    )
    _render_kpi_cards(history, code_to_name)

    # Mid: trend chart (2/3) + recent activity (1/3)
    st.markdown("<div style='height: 1.1rem;'></div>", unsafe_allow_html=True)
    chart_col, activity_col = st.columns([2, 1], gap="small")
    with chart_col:
        _render_history_trend_chart(history)
    with activity_col:
        _render_recent_activity(history)

    # Bottom: full history table
    st.markdown("<div style='height: 1.1rem;'></div>", unsafe_allow_html=True)
    st.html(
        """
        <div class="bb-section-h">
            <div class="bb-section-h-title">历史记录</div>
        </div>
        """
    )
    _render_history_table(history)

    st.markdown(
        """
        <div class="bb-disclaimer">
            ⚠️ 本项目仅供学习研究与技术演示，不构成任何投资建议。<br>
            投资决策请咨询持牌专业机构。作者不对使用本工具产生的任何损失承担责任。
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    render_sidebar_logo()
    st.markdown("<div class='bb-sidebar-sep'></div>", unsafe_allow_html=True)
    render_sidebar_nav()
    st.markdown("<div class='bb-sidebar-sep'></div>", unsafe_allow_html=True)
    render_sidebar()


# ── Handle "Start Analysis" trigger ──────────────────────────────────────────

start_req = st.session_state.pop("start_analysis", None)
if start_req:
    # Always jump to the analyze page when a new run starts, regardless of
    # which page the user is currently viewing (sector / history / settings).
    st.session_state["nav"] = "analyze"
    tracker = ProgressTracker(
        ticker=start_req["ticker"],
        trade_date=start_req["trade_date"],
    )
    st.session_state["tracker"] = tracker
    run_analysis_in_thread(
        ticker=start_req["ticker"],
        trade_date=start_req["trade_date"],
        config=_build_config(),
        tracker=tracker,
    )


# ── Main area dispatch ───────────────────────────────────────────────────────
#
# Modal states (viewing a report, analysis running/complete/errored) ALWAYS
# win over the nav page so the user sees what they actually triggered. The
# nav button is forced back to "analyze" in those branches so the sidebar
# indicator stays consistent with what's on screen.

tracker: ProgressTracker | None = st.session_state.get("tracker")
viewing_history: str | None = st.session_state.get("viewing_history")
nav: str = st.session_state.get("nav", "analyze")

# Acme-style top bar (persistent across all main-area pages).
# Modal pages override the title/subtitle via the page_title / page_subtitle
# args so the breadcrumb reflects the current view.
if viewing_history:
    _render_top_bar(page_title="报告详情", page_subtitle="历史分析报告 · 完整状态 + 辩论记录")
elif tracker and tracker.is_running:
    _render_top_bar(page_title="分析进行中", page_subtitle=f"{tracker.ticker} · {tracker.trade_date}")
elif tracker and tracker.is_complete:
    _render_top_bar(page_title="分析完成", page_subtitle=f"{tracker.ticker} · {tracker.trade_date}")
elif tracker and tracker.error:
    _render_top_bar(page_title="分析失败", page_subtitle=tracker.ticker or "")
elif nav == "sector":
    _render_top_bar()
elif nav == "history":
    _render_top_bar()
elif nav == "settings":
    _render_top_bar()
else:
    _render_top_bar()

# Modal state 1: Viewing a historical analysis
if viewing_history:
    st.session_state["nav"] = "analyze"
    try:
        state = load_analysis(viewing_history)
        signal = extract_signal(state)
        ticker = Path(viewing_history).parent.parent.name
        trade_date = Path(viewing_history).stem.replace("full_states_log_", "")
        render_report(state, ticker, trade_date, signal)
    except Exception as exc:
        st.error(f"加载失败: {exc}")

# Modal state 2: Analysis running
elif tracker and tracker.is_running:
    st.session_state["nav"] = "analyze"
    render_progress(tracker)
    time.sleep(2)
    st.rerun()

# Modal state 3: Analysis complete
elif tracker and tracker.is_complete:
    st.session_state["nav"] = "analyze"
    render_report(
        tracker.final_state,
        tracker.ticker,
        tracker.trade_date,
        tracker.signal,
        elapsed=tracker.elapsed,
    )

# Modal state 4: Analysis errored
elif tracker and tracker.error:
    st.session_state["nav"] = "analyze"
    st.error(f"分析失败: {tracker.error}")
    if st.button("重试"):
        st.session_state.pop("tracker", None)
        st.rerun()

# Nav dispatch (no modal state active)
elif nav == "sector":
    render_sector_panel()

elif nav == "history":
    render_history_panel()

elif nav == "settings":
    render_settings_panel()

# Default: analyze idle screen
else:
    _render_acme_idle_screen()
