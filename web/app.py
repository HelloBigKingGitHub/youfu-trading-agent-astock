"""TradingAgents A股分析 — Streamlit Web UI."""

from __future__ import annotations

import html
import os
import sys
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
from web.components.sidebar import render_sidebar, render_sidebar_logo  # noqa: E402
from web.history import extract_signal, get_history, load_analysis  # noqa: E402
from web.nav import (  # noqa: E402
    VIEW_COMPLETE,
    VIEW_ERROR,
    VIEW_HISTORY,
    VIEW_RUNNING,
    plan_nav_click,
    resolve_main_view,
)
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
    a pre-fetched ``st.session_state['_code_name_map']`` (populated at app
    start by a fire-and-forget thread) is returned. If the thread hasn't
    finished yet, an empty dict is returned and the UI shows "—" for the
    name. The thread itself never blocks the Streamlit render path.

    NOTE: the import happens inside the worker thread. Streamlit's script
    runner and Python's import lock can interact badly when ``a_stock`` is
    imported for the *first* time from inside a daemon thread; in that
    situation the lookup hangs. We keep the worker so the first successful
    pre-fetch seeds the cache, but the render path treats an empty result as
    acceptable.
    """
    return st.session_state.get("_code_name_map") or {}


# Note: the original _kick_off_code_name_loader() (which spawns a daemon
# thread to warm the mootdx code→name cache) is intentionally NOT called at
# module top level. In practice the import inside the worker thread deadlocks
# the Streamlit script runner when mootdx's TCP server is unreachable
# (TimeoutError but the import itself blocks). Leaving the helper defined
# for reference but unused; the render path tolerates an empty cache by
# showing "—" for the Chinese name.


def _render_recent_analyses() -> None:
    """Render the 4 most recent analysis cards below the welcome screen."""
    try:
        history = get_history()[:4]
        if not history:
            return

        try:
            code_to_name = _load_code_to_name()
        except Exception:
            code_to_name = {}

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
    except Exception as exc:
        st.warning(f"最近分析加载异常: {exc}")


def _render_analysis_form() -> None:
    """Render the 'new analysis' form at the top of the analyze page.

    Moved from sidebar to main area in v0.2.14 so the form sits with the
    analysis content rather than competing for sidebar real estate with
    the nav buttons and history list.
    """
    from datetime import date

    from web.components.sidebar import _render_llm_config, _resolve_user_input

    with st.container(key="main_analysis_form_container"):
        st.html('<div class="bb-section-label">新建分析</div>')

        col1, col2 = st.columns([1, 1])
        with col1:
            ticker = st.text_input(
                "股票代码",
                placeholder="例: 300750 或 宁德时代",
                key="input_ticker_main",
                help="输入6位A股代码或中文股票全称",
            )
        with col2:
            trade_date = st.date_input(
                "分析日期",
                value=date.today(),
                key="input_date_main",
            )

        with st.expander("⚙️  模型配置", expanded=False):
            _render_llm_config()

        tracker = st.session_state.get("tracker")
        is_busy = tracker is not None and tracker.is_running
        button_label = "⏳ 分析进行中..." if is_busy else "🚀 开始分析"

        if st.button(
            button_label,
            use_container_width=True,
            disabled=is_busy or not ticker,
            type="primary",
            key="main_start_analysis",
        ):
            resolved_code, err = _resolve_user_input(ticker)
            if err:
                st.error(f"❌ {err}")
            else:
                if resolved_code != ticker.strip():
                    st.success(f"✅ {ticker.strip()} → {resolved_code}")
                st.session_state["start_analysis"] = {
                    "ticker": resolved_code,
                    "trade_date": trade_date.strftime("%Y-%m-%d"),
                }
                st.session_state["viewing_history"] = None
                st.rerun()


def _render_idle_screen() -> None:
    """Render the welcome hero + new-analysis form + 4 recent analysis cards + disclaimer.

    Layout (top → bottom):
      1. Welcome hero (TRADINGAGENTS-ASTOCK title acts as the page heading)
      2. New-analysis form (the primary CTA — start here)
      3. 4 recent-analysis cards
      4. Bottom disclaimer
    """
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

    _render_analysis_form()

    try:
        _render_recent_analyses()
    except Exception as exc:
        st.warning(f"最近分析加载异常: {exc}")

    try:
        st.html(
            """
            <div class="bb-disclaimer">
                ⚠️ 本项目仅供学习研究与技术演示，不构成任何投资建议。<br>
                投资决策请咨询持牌专业机构。作者不对使用本工具产生的任何损失承担责任。
            </div>
            """
        )
    except Exception:
        pass


# ── Sidebar nav (4 buttons: analyze / sector / history / settings) ─────────

_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("📝", "分析", "analyze"),
    ("📊", "批量分析", "batch"),
    ("📈", "板块轮动", "sector"),
    ("💼", "我的仓位", "portfolio"),
    ("📋", "历史", "history"),
    ("📋", "日志", "logs"),
    ("📈", "走势图", "chart"),
    ("⏰", "定时分析", "schedule"),
    ("⚙️", "设置", "settings"),
]


def _render_nav_buttons() -> None:
    """Render the 4-button page nav at the top of the sidebar.

    Active page → ``type="primary"`` (gradient accent).
    Other pages → ``type="secondary"`` (hairline outline).

    Stacked vertically (4 full-width rows) rather than 4 columns because
    Streamlit's narrow sidebar (~280px) cannot fit 4 button labels side
    by side without wrapping the Chinese text inside each button.

    Click handler routes through ``plan_nav_click`` so navigating away from a
    completed / errored report (or a historical-report overlay) dismisses that
    sticky state — otherwise a lingering completed tracker would pin the main
    area to the report and the nav could never switch (see web/nav.py). A
    *running* analysis is preserved so its background thread stays tracked.
    """
    current = st.session_state.get("nav", "analyze")
    for icon, label, page in _NAV_ITEMS:
        if st.button(
            f"{icon}  {label}",
            key=f"nav_{page}",
            type="primary" if current == page else "secondary",
            use_container_width=True,
        ):
            plan = plan_nav_click(page, st.session_state.get("tracker"))
            st.session_state["nav"] = plan.nav
            if plan.clear_viewing_history:
                st.session_state["viewing_history"] = None
            if plan.clear_tracker:
                st.session_state.pop("tracker", None)
            st.rerun()


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    render_sidebar_logo()
    st.markdown("<div class='bb-sidebar-sep'></div>", unsafe_allow_html=True)
    _render_nav_buttons()
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
# The view is decided by web.nav.resolve_main_view (a pure, unit-tested state
# machine). A *running* analysis always wins. Terminal report states
# (historical report / completed / errored) render ONLY on the analyze tab, so
# selecting another nav page switches the main area instead of being trapped on
# a sticky report.

tracker: ProgressTracker | None = st.session_state.get("tracker")
viewing_history: str | None = st.session_state.get("viewing_history")
nav: str = st.session_state.get("nav", "analyze")

view = resolve_main_view(nav, tracker, viewing_history)

# Running: show live progress in a self-refreshing fragment.
#
# We render the progress panel inside an ``st.fragment(run_every=2)`` instead
# of the older ``time.sleep(2) + st.rerun()`` loop. The sleep blocked the
# Streamlit script runner for the full 2 s on every poll; during long
# analyses (15-25 s per CLAUDE.md, batch even longer) the script thread held
# on long enough that the WebSocket ping (~10 s default) was missed and the
# browser showed "Connection failed" — which users perceived as "the link
# from the sector panel to the analyze page broke". A fragment re-executes
# itself on a separate scheduler tick without blocking the main script, so
# heartbeat traffic and other tabs keep flowing while progress refreshes.
#
# When the tracker flips to a terminal state inside the fragment (the
# background thread just called ``mark_complete`` / ``mark_error``), we
# explicitly rerun the parent so ``resolve_main_view`` re-renders the
# completed report / error page instead of leaving the user stuck on the
# progress view. ``run_every`` only refreshes the fragment itself.
@st.fragment(run_every=2)
def _running_view(tracker: ProgressTracker) -> None:
    render_progress(tracker)
    if not tracker.is_running:
        st.rerun(scope="app")


if view == VIEW_RUNNING:
    st.session_state["nav"] = "analyze"
    _running_view(tracker)

# Viewing a historical analysis (overlay on the analyze tab).
elif view == VIEW_HISTORY:
    try:
        state = load_analysis(viewing_history)
        signal = extract_signal(state)
        ticker = Path(viewing_history).parent.parent.name
        trade_date = Path(viewing_history).stem.replace("full_states_log_", "")
        render_report(state, ticker, trade_date, signal)
    except Exception as exc:
        st.error(f"加载失败: {exc}")

# Completed analysis report.
elif view == VIEW_COMPLETE:
    render_report(
        tracker.final_state,
        tracker.ticker,
        tracker.trade_date,
        tracker.signal,
        elapsed=tracker.elapsed,
    )

# Errored analysis.
elif view == VIEW_ERROR:
    st.error(f"分析失败: {tracker.error}")
    if st.button("重试"):
        st.session_state.pop("tracker", None)
        st.rerun()

# Nav pages.
elif view == "sector":
    render_sector_panel()

elif view == "batch":
    from web.components.batch_panel import render_batch_panel
    render_batch_panel()

elif view == "history":
    render_history_panel()

elif view == "logs":
    from web.components.logs_panel import render_logs_panel

    render_logs_panel()

elif view == "chart":
    from web.components.chart_panel import render_chart_panel

    render_chart_panel()

elif view == "portfolio":
    from web.components.portfolio_panel import render_portfolio_panel

    render_portfolio_panel()

elif view == "schedule":
    from web.components.schedule_panel import render_schedule_panel

    render_schedule_panel()

elif view == "settings":
    render_settings_panel()

# Default: analyze idle screen (VIEW_IDLE).
else:
    try:
        _render_idle_screen()
    except Exception as e:
        st.error(f"渲染失败: {e}")
