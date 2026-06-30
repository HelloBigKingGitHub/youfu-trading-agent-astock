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
from web.components.sidebar import render_sidebar, render_sidebar_logo  # noqa: E402
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
    """Render the new-analysis form + welcome hero + 4 recent analysis cards + disclaimer."""

    _render_analysis_form()

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
# Modal states (viewing a report, analysis running/complete/errored) ALWAYS
# win over the nav page so the user sees what they actually triggered. The
# nav button is forced back to "analyze" in those branches so the sidebar
# indicator stays consistent with what's on screen.

tracker: ProgressTracker | None = st.session_state.get("tracker")
viewing_history: str | None = st.session_state.get("viewing_history")
nav: str = st.session_state.get("nav", "analyze")

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
    _render_idle_screen()
