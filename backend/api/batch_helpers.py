"""Helpers shared between the batch API endpoints and the CLI.

Centralises the "default LLM config" so the web API and CLI agree.

Per-job LLM config resolution order (highest → lowest priority):

1. ``item_overrides[i]`` — the dict embedded in the POST /api/batch body for
   that specific job (provider / deep / quick / backend_url).
2. Process env (``BATCH_LLM_PROVIDER`` / ``BATCH_DEEP_MODEL`` /
   ``BATCH_QUICK_MODEL`` / ``BACKEND_URL``) — the CLI uses this layer.
3. Hard-coded fallback ``"minimax"`` / ``"MiniMax-M2.7"`` /
   ``"MiniMax-M2.7-highspeed"``.

We never fall back to ``DEFAULT_CONFIG.llm_provider`` because that key is
hard-coded to ``"openai"`` in upstream code, which would break local
development for users without an ``OPENAI_API_KEY`` set.

**Important:** We still seed the per-job config from ``DEFAULT_CONFIG.copy()``
— the upstream ``TradingAgentsGraph.__init__`` hard-requires keys like
``data_cache_dir``, ``results_dir``, ``memory_log_path`` and many more that
live in ``DEFAULT_CONFIG``. Building a config from scratch (only the ~7 keys
we override) would surface a ``KeyError: 'data_cache_dir'`` the moment the
graph is constructed. This mirrors ``web/app.py._build_config`` which also
copies ``DEFAULT_CONFIG`` first and then overrides only the user-facing
fields.

The LLM override is applied *after* the copy, so the upstream ``"openai"``
provider never leaks through.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 从上游导入 DEFAULT_CONFIG — 我们把它当作"上游所有必需字段的种子",
# 然后只覆盖 LLM / debate / language / data_vendors 几项。
# 见模块 docstring 的根因说明。
from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402


# 硬编码兜底 — 绝不再从 DEFAULT_CONFIG.llm_provider 读(那是 "openai")
_FALLBACK_PROVIDER = "minimax"
_FALLBACK_DEEP = "MiniMax-M2.7"
_FALLBACK_QUICK = "MiniMax-M2.7-highspeed"


def _env_or_hardcoded(env_key: str, hardcoded: str) -> str:
    """Read an env var, falling back to the hard-coded default if missing."""
    val = os.environ.get(env_key)
    if val is not None and str(val).strip():
        return str(val).strip()
    return hardcoded


def _resolve_provider(item_override: dict | None) -> str:
    """Pick the llm_provider for one job."""
    if item_override:
        v = item_override.get("llm_provider")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return _env_or_hardcoded("BATCH_LLM_PROVIDER", _FALLBACK_PROVIDER)


def _resolve_deep(item_override: dict | None) -> str:
    if item_override:
        v = item_override.get("deep_think_llm")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return _env_or_hardcoded("BATCH_DEEP_MODEL", _FALLBACK_DEEP)


def _resolve_quick(item_override: dict | None) -> str:
    if item_override:
        v = item_override.get("quick_think_llm")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return _env_or_hardcoded("BATCH_QUICK_MODEL", _FALLBACK_QUICK)


def _resolve_backend_url(item_override: dict | None) -> str | None:
    """Pick the backend_url (or None to use provider default)."""
    if item_override:
        v = item_override.get("backend_url")
        if isinstance(v, str) and v.strip():
            return v.strip()
    env = os.environ.get("BACKEND_URL", "").strip()
    return env or None


def _base_config(provider: str, deep: str, quick: str, backend_url: str | None) -> dict:
    """构造 per-job config dict,供 JobQueue + runner 使用。

    必须以 ``dict(DEFAULT_CONFIG)`` 作为种子,否则上游
    ``TradingAgentsGraph.__init__`` 会因为缺 ``data_cache_dir`` / ``results_dir``
    / ``memory_log_path`` 等必需键而 KeyError。

    然后只覆盖我们关心的几项(LLM / debate / language / data_vendors)。
    覆盖顺序刻意放在 copy 之后,所以即使 ``DEFAULT_CONFIG.llm_provider``
    是 ``"openai"``,最终的值也是我们解析出来的 ``"minimax"`` — OPENAI_API_KEY
    的报错不会回来。
    """
    cfg = dict(DEFAULT_CONFIG)
    # LLM 三件套 + 可选 backend_url
    cfg["llm_provider"] = provider
    cfg["deep_think_llm"] = deep
    cfg["quick_think_llm"] = quick
    if backend_url:
        cfg["backend_url"] = backend_url
    else:
        # DEFAULT_CONFIG 默认是 None;如果 upstream 改成了字符串,强制清回 None,
        # 否则会泄露成上游的 endpoint(历史上曾把 OpenAI URL 转发给 Gemini)。
        cfg["backend_url"] = None
    # 辩论 / 语言 / 数据源 — 显式设置,不依赖 DEFAULT_CONFIG(它已经默认这些值,
    # 但我们显式声明以便改动可追踪)。
    cfg["max_debate_rounds"] = 1
    cfg["max_risk_discuss_rounds"] = 1
    cfg["output_language"] = "Chinese"
    cfg["data_vendors"] = {
        "core_stock_apis": "a_stock",
        "technical_indicators": "a_stock",
        "fundamental_data": "a_stock",
        "news_data": "a_stock",
        "signal_data": "a_stock",
    }
    return cfg


def build_default_configs(
    jobs: list,
    item_overrides: list[dict | None] | None = None,
) -> list[dict]:
    """为每个 job 构造一个 config dict。

    Args:
        jobs: list of Job objects (only ``len(jobs)`` is used).
        item_overrides: optional per-job override dicts (one entry per job;
            ``None`` or empty dict means "use env / hardcoded fallback").
            - When ``None``, every job falls back to the same env-level config
              (CLI use case).
            - When shorter than ``jobs``, the tail uses env fallback.

    Returns:
        List of config dicts, length == len(jobs). Each is a fresh dict so
        downstream mutations don't leak across jobs.

    每个 config 都以 ``dict(DEFAULT_CONFIG)`` 作为种子(携带 ``data_cache_dir``
    等所有上游必需键),然后只覆盖 LLM / debate / language / data_vendors 字段。
    """
    n = len(jobs)
    if n == 0:
        return []

    if item_overrides is None:
        # CLI / 无 body 的情况:全部 job 共享同一份从 env 解析出来的 config。
        cfg = _base_config(
            provider=_env_or_hardcoded("BATCH_LLM_PROVIDER", _FALLBACK_PROVIDER),
            deep=_env_or_hardcoded("BATCH_DEEP_MODEL", _FALLBACK_DEEP),
            quick=_env_or_hardcoded("BATCH_QUICK_MODEL", _FALLBACK_QUICK),
            backend_url=_resolve_backend_url(None),
        )
        return [dict(cfg) for _ in range(n)]

    # item_overrides 提供,但长度可能短于 jobs — 尾部走 env 兜底。
    out: list[dict] = []
    for i in range(n):
        ov = item_overrides[i] if i < len(item_overrides) else None
        ov = ov or None  # 规范化:空 dict 也走 env 兜底
        out.append(
            _base_config(
                provider=_resolve_provider(ov),
                deep=_resolve_deep(ov),
                quick=_resolve_quick(ov),
                backend_url=_resolve_backend_url(ov),
            )
        )
    return out


def resolve_llm_summary(config: dict) -> dict:
    """Tiny helper for the API response: report what LLM a job will use.

    Returns ``{"llm_provider": ..., "deep_think_llm": ...,
    "quick_think_llm": ...}`` — useful for the batch panel UI to show the
    model next to each ticker.

    输入是 ``build_default_configs`` 已经解析好的 config(per-item 兜底之后),
    这样 UI 显示的就是"实际会跑"的 LLM,而不是用户原始 body 里写的字符串。
    """
    return {
        "llm_provider": config.get("llm_provider"),
        "deep_think_llm": config.get("deep_think_llm"),
        "quick_think_llm": config.get("quick_think_llm"),
    }