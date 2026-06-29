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

from web.components.progress_panel import render_progress  # noqa: E402
from web.components.report_viewer import render_report  # noqa: E402
from web.components.sidebar import render_sidebar  # noqa: E402
from web.history import extract_signal, get_history, load_analysis  # noqa: E402
from web.progress import ProgressTracker  # noqa: E402
from web.runner import run_analysis_in_thread  # noqa: E402
from web.styles import inject_css  # noqa: E402

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TradingAgents-Astock A股分析",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject design-system CSS (tokens, base, components, elements).
inject_css()

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');

    /* Hide Streamlit chrome for clean video recording.
       IMPORTANT: do NOT `display:none` the whole header OR the whole toolbar.
       In Streamlit >= 1.36 the "expand sidebar" button lives *inside* the
       toolbar (header > stToolbar > stExpandSidebarButton), so hiding either
       one makes a collapsed sidebar impossible to reopen (issue #36). Instead
       keep the header/toolbar in the DOM, make the header transparent, and
       hide only the individual chrome widgets we don't want on camera. */
    #MainMenu,
    footer,
    div[data-testid="stDecoration"],
    div[data-testid="stStatusWidget"],
    div[data-testid="stToolbarActions"],
    div[data-testid="stAppDeployButton"],
    span[data-testid="stMainMenu"] { display: none !important; }
    header[data-testid="stHeader"] {
        background: transparent !important;
        box-shadow: none !important;
    }
    /* Keep the sidebar collapse / expand controls always visible & clickable.
       Selector list spans multiple Streamlit versions. */
    button[data-testid="stExpandSidebarButton"],
    button[data-testid="stSidebarCollapseButton"],
    button[data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, sans-serif;
    }
    .stApp {
        background: #0a0a0a;
    }
    section[data-testid="stSidebar"] {
        background: #0f0f0f;
        border-right: 1px solid #1a1a1a;
    }
    .stMetric label { color: #888 !important; font-size: 0.8rem !important; }
    .stMetric [data-testid="stMetricValue"] {
        color: #ff5a1f !important;
        font-weight: 700 !important;
    }
    .stProgress > div > div > div {
        background: linear-gradient(90deg, #ff5a1f, #ff8c42) !important;
    }
    button[kind="primary"] {
        background: linear-gradient(135deg, #ff5a1f, #ff8c42) !important;
        border: none !important;
        font-weight: 700 !important;
        letter-spacing: 0.05em !important;
        box-shadow: 0 4px 15px rgba(255,90,31,0.3) !important;
        transition: all 0.2s ease !important;
    }
    button[kind="primary"]:hover {
        background: linear-gradient(135deg, #e04d15, #ff5a1f) !important;
        box-shadow: 0 6px 20px rgba(255,90,31,0.4) !important;
        transform: translateY(-1px) !important;
    }
    /* Secondary buttons (history items) */
    button[kind="secondary"] {
        background: #161616 !important;
        border: 1px solid #2a2a2a !important;
        color: #ccc !important;
        transition: all 0.2s ease !important;
    }
    button[kind="secondary"]:hover {
        background: #1e1e1e !important;
        border-color: #ff5a1f !important;
        color: #ff5a1f !important;
    }
    .stExpander {
        border: 1px solid #222 !important;
        border-radius: 8px !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: #888 !important;
    }
    .stTabs [aria-selected="true"] {
        color: #ff5a1f !important;
        border-bottom-color: #ff5a1f !important;
    }
    div[data-testid="stDownloadButton"] button {
        background: #1a1a2e !important;
        border: 1px solid #ff5a1f !important;
        color: #ff5a1f !important;
    }
    /* Text input styling */
    input[data-testid="stTextInputRootElement"] input,
    .stTextInput input {
        background: #161616 !important;
        border-color: #2a2a2a !important;
        color: #f5f1eb !important;
    }
    .stTextInput input:focus {
        border-color: #ff5a1f !important;
        box-shadow: 0 0 0 1px #ff5a1f !important;
    }
    /* Date input styling */
    .stDateInput input {
        background: #161616 !important;
        border-color: #2a2a2a !important;
        color: #f5f1eb !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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

def _signal_badge(signal: str, status: str) -> tuple[str, str]:
    """Map (signal, status) to (badge_kind, badge_label).

    badge_kind ∈ {bull, bear, hold, neutral, running, error}.
    Falls back to status-driven colour when signal is empty.
    """
    s = (signal or "").upper()
    if status == "running":
        return "running", "RUNNING"
    if status == "error":
        return "error", "ERROR"
    if "BUY" in s or "OVERWEIGHT" in s or "LONG" in s:
        return "bull", signal.upper()
    if "SELL" in s or "UNDERWEIGHT" in s or "SHORT" in s:
        return "bear", signal.upper()
    if "HOLD" in s:
        return "hold", "HOLD"
    return "neutral", "—"


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


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    render_sidebar()


# ── Handle "Start Analysis" trigger ──────────────────────────────────────────

start_req = st.session_state.pop("start_analysis", None)
if start_req:
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


# ── Main area state machine ─────────────────────────────────────────────────

tracker: ProgressTracker | None = st.session_state.get("tracker")
viewing_history: str | None = st.session_state.get("viewing_history")

# State 1: Viewing a historical analysis
if viewing_history:
    try:
        state = load_analysis(viewing_history)
        signal = extract_signal(state)
        ticker = Path(viewing_history).parent.parent.name
        trade_date = Path(viewing_history).stem.replace("full_states_log_", "")
        render_report(state, ticker, trade_date, signal)
    except Exception as exc:
        st.error(f"加载失败: {exc}")

# State 2: Analysis running
elif tracker and tracker.is_running:
    render_progress(tracker)
    time.sleep(2)
    st.rerun()

# State 3: Analysis complete
elif tracker and tracker.is_complete:
    render_report(
        tracker.final_state,
        tracker.ticker,
        tracker.trade_date,
        tracker.signal,
        elapsed=tracker.elapsed,
    )

# State 4: Analysis errored
elif tracker and tracker.error:
    st.error(f"分析失败: {tracker.error}")
    if st.button("重试"):
        st.session_state.pop("tracker", None)
        st.rerun()

# State 0: Idle — welcome screen
else:
    _render_idle_screen()
