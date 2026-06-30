"""Sidebar: logo header, stock input, LLM config, and history list."""

from __future__ import annotations

import html
from datetime import date

import streamlit as st

from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS
from web._signal_helpers import signal_badge
from web.history import get_history

# Provider display names in recommended order
_PROVIDERS: list[tuple[str, str]] = [
    ("MiniMax（推荐·国内直连）", "minimax"),
    ("DeepSeek", "deepseek"),
    ("通义千问 Qwen", "qwen"),
    ("智谱 GLM", "glm"),
    ("OpenAI", "openai"),
    ("Anthropic", "anthropic"),
    ("Google Gemini", "google"),
    ("xAI Grok", "xai"),
    ("Ollama（本地）", "ollama"),
]

_PROVIDER_DISPLAY = [name for name, _ in _PROVIDERS]
_PROVIDER_KEYS = [key for _, key in _PROVIDERS]


def _resolve_user_input(raw: str) -> tuple[str, str | None]:
    """Resolve raw user input to (ticker_code, error_msg).

    Accepts 6-digit codes or Chinese stock names (e.g. '宝光股份').
    Returns (code, None) on success or ("", error_msg) on failure.
    """
    from tradingagents.dataflows.a_stock import resolve_ticker

    try:
        code = resolve_ticker(raw)
        return code, None
    except ValueError as e:
        return "", str(e)


def _current_model_label() -> str:
    """Return a short label for the currently selected (provider, model).

    Falls back to provider + llm_base_url hint if model is not in the catalog.
    Used in the expander title to surface the active model at a glance.
    """
    provider_idx = st.session_state.get("llm_provider_idx", 0)
    quick_idx = st.session_state.get("quick_model_idx", 0)
    if 0 <= provider_idx < len(_PROVIDERS):
        provider_name = _PROVIDER_DISPLAY[provider_idx].split("（")[0]
    else:
        provider_name = "LLM"
    # Prefer the short model id (e.g. "MiniMax-M2.7-highspeed") over the long
    # display label so the expander title fits on one line in the narrow sidebar.
    quick = "—"
    if 0 <= provider_idx < len(_PROVIDERS) and _PROVIDER_KEYS[provider_idx] in MODEL_OPTIONS:
        quick_options = MODEL_OPTIONS[_PROVIDER_KEYS[provider_idx]]["quick"]
        if 0 <= quick_idx < len(quick_options):
            quick = quick_options[quick_idx][1]
    return f"{provider_name} · {quick}"


def _render_llm_config() -> None:
    """Render LLM provider and model selection controls."""

    provider_idx = st.selectbox(
        "LLM 供应商",
        range(len(_PROVIDERS)),
        format_func=lambda i: _PROVIDER_DISPLAY[i],
        key="llm_provider_idx",
        help="选择你配置了 API Key 的供应商",
    )
    provider_key = _PROVIDER_KEYS[provider_idx]
    st.session_state["llm_provider"] = provider_key

    if provider_key in MODEL_OPTIONS:
        quick_options = MODEL_OPTIONS[provider_key]["quick"]
        deep_options = MODEL_OPTIONS[provider_key]["deep"]

        quick_labels = [label for label, _ in quick_options]
        quick_values = [value for _, value in quick_options]
        deep_labels = [label for label, _ in deep_options]
        deep_values = [value for _, value in deep_options]

        quick_idx = st.selectbox(
            "快速思考模型",
            range(len(quick_options)),
            format_func=lambda i: quick_labels[i],
            key="quick_model_idx",
            help="用于常规分析任务，速度优先",
        )
        st.session_state["quick_think_llm"] = quick_values[quick_idx]

        deep_idx = st.selectbox(
            "深度思考模型",
            range(len(deep_options)),
            format_func=lambda i: deep_labels[i],
            key="deep_model_idx",
            help="用于辩论/决策等需要深度推理的任务",
        )
        st.session_state["deep_think_llm"] = deep_values[deep_idx]
    else:
        custom_quick = st.text_input("快速思考模型 ID", key="custom_quick_model")
        custom_deep = st.text_input("深度思考模型 ID", key="custom_deep_model")
        st.session_state["quick_think_llm"] = custom_quick
        st.session_state["deep_think_llm"] = custom_deep

    st.text_input(
        "API Base URL（第三方/代理，可选）",
        key="llm_base_url",
        placeholder="例: https://your-proxy.com/v1",
        help=(
            "通过第三方中转/代理访问 Claude、OpenAI 等模型时填写网关地址；"
            "留空则用所选供应商的官方地址。API Key 仍从 .env 读取"
            "（如 ANTHROPIC_API_KEY / OPENAI_API_KEY）。"
            "也可在 .env 里设 BACKEND_URL 代替此处。"
        ),
    )


def render_sidebar_logo() -> None:
    """Render the sidebar's top logo block (glacier-blue Bloomberg style)."""

    st.html(
        """
        <div class="bb-sidebar-block bb-sidebar-logo">
            <div class="bb-logo-text">
                <span class="bb-logo-text--accent">TRADING</span><span class="bb-logo-text--primary">AGENTS</span><span class="bb-logo-text--primary">-</span><span class="bb-logo-text--accent">ASTOCK</span>
            </div>
            <div class="bb-logo-subtitle">A股多 Agent 投研系统</div>
            <div class="bb-logo-author">
                by <a class="bb-logo-link" href="https://github.com/simonlin1212" target="_blank">simonlin1212</a>
            </div>
        </div>
        """
    )


def _render_history_entry(entry: dict) -> None:
    """Render one sidebar history row as a ticker + date + signal badge.

    Streamlit buttons don't allow custom inner HTML, so we render the visual
    row with st.html and put a real button underneath for the click target.
    The button keeps a unique key per analysis_id (see b17eb0f).
    """
    ticker_raw = entry.get("ticker", "")
    ticker = html.escape(ticker_raw)
    trade_date = html.escape(entry.get("date", ""))
    signal = entry.get("signal", "") or ""
    status = entry.get("status", "") or ""
    aid = entry.get("analysis_id") or f"{ticker_raw}_{entry.get('date', '')}"
    badge_kind, badge_label = signal_badge(signal, status)
    badge_label_esc = html.escape(badge_label)
    active_path = st.session_state.get("viewing_history")
    is_active = bool(active_path) and active_path == entry.get("path")

    st.html(
        f"""
        <div class="bb-sidebar-history-item{' bb-sidebar-history-item--active' if is_active else ''}">
            <div class="bb-sidebar-history-left">
                <div class="bb-sidebar-history-ticker">{ticker}</div>
                <div class="bb-sidebar-history-date">{trade_date}</div>
            </div>
            <div class="bb-card-badge bb-card-badge--{badge_kind}">
                <span class="bb-card-badge-dot"></span>
                <span>{badge_label_esc}</span>
            </div>
        </div>
        """
    )
    if st.button(
        "查看报告",
        key=f"hist_{aid}",
        use_container_width=True,
    ):
        st.session_state["viewing_history"] = entry.get("path") or None
        st.session_state["start_analysis"] = None
        st.rerun()


def render_sidebar() -> None:
    """Render the new-analysis form, history list, and disclaimer."""

    st.html(
        """
        <div class="bb-sidebar-form-box">
            <div class="bb-sidebar-section-label">新建分析</div>
        </div>
        """
    )

    ticker = st.text_input(
        "股票代码",
        placeholder="例: 300750 或 宁德时代",
        key="input_ticker",
        label_visibility="collapsed",
        help="输入6位A股代码或中文股票全称",
    )

    trade_date = st.date_input(
        "分析日期",
        value=date.today(),
        key="input_date",
    )

    with st.expander(f"⚙️  模型配置  ·  {_current_model_label()}", expanded=False):
        _render_llm_config()

    tracker = st.session_state.get("tracker")
    is_busy = tracker is not None and tracker.is_running

    if st.button(
        "开始分析" if not is_busy else "分析进行中...",
        use_container_width=True,
        disabled=is_busy or not ticker,
        type="primary",
        key="sidebar_start_analysis",
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

    history = get_history()
    count = len(history)
    st.html(
        f"""
        <div class="bb-sidebar-section-header">
            <span class="bb-sidebar-section-label">历史记录</span>
            <span class="bb-sidebar-count">{count}</span>
        </div>
        """
    )

    if not history:
        st.html(
            """
            <div class="bb-sidebar-empty">暂无历史记录</div>
            """
        )
    else:
        for entry in history[:20]:
            _render_history_entry(entry)

    st.html(
        """
        <div class="bb-sidebar-disclaimer">
            ⚠️ 仅供学习研究，不构成投资建议
        </div>
        """
    )
