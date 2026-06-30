"""Settings panel — LLM provider and model configuration."""

from __future__ import annotations

import os

import streamlit as st

from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS

_PROVIDERS = [
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


def render_settings_panel() -> None:
    """Render the LLM settings panel."""

    st.html(
        """
        <div class="bb-h1">
            <div class="bb-h1-title">⚙️ 设置</div>
            <div class="bb-h1-subtitle">配置模型供应商与 API Key</div>
        </div>
        """
    )

    # Current provider
    current_provider = st.session_state.get("llm_provider", "minimax")
    try:
        current_idx = _PROVIDER_KEYS.index(current_provider)
    except ValueError:
        current_idx = 0

    st.markdown("#### 🔑 API Keys")

    # Show current API key status
    col1, col2 = st.columns(2)
    with col1:
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        st.text_input(
            "ANTHROPIC_API_KEY",
            value=anthropic_key[:10] + "..." if anthropic_key else "",
            disabled=True,
            help="从 .env 读取",
        )
    with col2:
        openai_key = os.getenv("OPENAI_API_KEY", "")
        st.text_input(
            "OPENAI_API_KEY",
            value=openai_key[:10] + "..." if openai_key else "",
            disabled=True,
            help="从 .env 读取",
        )

    st.html(
        '<div class="bb-api-key-hint">'
        'API Key 请在项目根目录 <code>.env</code> 文件中配置后重启应用生效</div>'
    )

    st.markdown("####🤖 模型配置")

    provider_idx = st.selectbox(
        "LLM 供应商",
        range(len(_PROVIDERS)),
        index=current_idx,
        format_func=lambda i: _PROVIDER_DISPLAY[i],
        key="settings_llm_provider_idx",
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

        current_quick = st.session_state.get("quick_think_llm", "")
        try:
            quick_idx = quick_values.index(current_quick)
        except ValueError:
            quick_idx = 0
        current_deep = st.session_state.get("deep_think_llm", "")
        try:
            deep_idx = deep_values.index(current_deep)
        except ValueError:
            deep_idx = 0

        quick_idx = st.selectbox(
            "⚡ 快速思考模型",
            range(len(quick_options)),
            index=quick_idx,
            format_func=lambda i: quick_labels[i],
            key="settings_quick_model_idx",
            help="用于常规分析任务，速度优先",
        )
        st.session_state["quick_think_llm"] = quick_values[quick_idx]

        deep_idx = st.selectbox(
            "🧠 深度思考模型",
            range(len(deep_options)),
            index=deep_idx,
            format_func=lambda i: deep_labels[i],
            key="settings_deep_model_idx",
            help="用于辩论/决策等需要深度推理的任务",
        )
        st.session_state["deep_think_llm"] = deep_values[deep_idx]
    else:
        custom_quick = st.text_input(
            "快速思考模型 ID",
            value=st.session_state.get("quick_think_llm", ""),
            key="settings_custom_quick",
        )
        custom_deep = st.text_input(
            "深度思考模型 ID",
            value=st.session_state.get("deep_think_llm", ""),
            key="settings_custom_deep",
        )
        st.session_state["quick_think_llm"] = custom_quick
        st.session_state["deep_think_llm"] = custom_deep

    st.markdown("#### 🌐 网络代理（可选）")

    backend_url = st.text_input(
        "API Base URL（第三方/代理）",
        value=st.session_state.get("llm_base_url", os.getenv("BACKEND_URL", "")),
        placeholder="例: https://your-proxy.com/v1",
        key="settings_llm_base_url",
        help="通过第三方中转访问 Claude、OpenAI 时填写网关地址",
    )
    st.session_state["llm_base_url"] = backend_url

    st.markdown("---")

    # Save confirmation
    st.success("✅ 配置已保存，下次分析时生效")