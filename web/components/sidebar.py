"""Sidebar: logo header, 4-button page nav, and bottom disclaimer.

The new-analysis form and history list have been moved out of the sidebar —
they now live in the main area of the analyze / history pages respectively.
This module keeps the shared helpers (_resolve_user_input, _render_llm_config)
and the logo block; _render_llm_config is imported by app.py for the main-area
form.
"""

from __future__ import annotations

import streamlit as st

from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

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
    """Render the sidebar's top logo block (glacier-blue Bloomberg style).

    Composition: a contained box with version badge (top-right), two-tone
    TRADINGAGENTS-ASTOCK title, subtitle, live indicator with pulsing dot,
    hairline divider, and GitHub-icon author link at the bottom.
    """
    # GitHub Octocat path (inline SVG, no emoji).
    github_icon = (
        '<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor" '
        'aria-hidden="true" focusable="false">'
        '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38'
        ' 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01'
        ' 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95'
        ' 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27'
        ' 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95'
        ' .29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>'
        '</svg>'
    )

    st.html(
        f"""
        <div class="bb-sidebar-block bb-logo-box">
            <div class="bb-logo-version">v0.2.13</div>
            <div class="bb-logo-text">
                <span class="bb-logo-text--accent">TRADING</span><span class="bb-logo-text--primary">AGENTS</span><span class="bb-logo-text--primary">-</span><span class="bb-logo-text--accent">ASTOCK</span>
            </div>
            <div class="bb-logo-subtitle">A股多 Agent 投研系统</div>
            <div class="bb-logo-live">
                <span class="bb-logo-live-dot"></span>
                <span>实时数据 · 7 位 AI 分析师</span>
            </div>
            <div class="bb-logo-divider"></div>
            <div class="bb-logo-author">
                by <a class="bb-logo-author-link" href="https://github.com/simonlin1212" target="_blank" rel="noopener">{github_icon}<span>simonlin1212</span></a>
            </div>
        </div>
        """
    )


def render_sidebar() -> None:
    """Render only the bottom disclaimer in the sidebar.

    The new-analysis form has been moved to the analyze page (main area) and
    the history list has been moved to the history page. The sidebar now
    only contains the logo, nav buttons, and this disclaimer.
    """
    st.html(
        """
        <div class="bb-sidebar-disclaimer">
            ⚠️ 仅供学习研究，不构成投资建议
        </div>
        """
    )
