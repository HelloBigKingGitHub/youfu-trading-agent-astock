import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")


# P2.28 hotfix — ``TRADINGAGENTS_RESULTS_DIR`` and friends are typically
# written into ``.env`` with a literal ``~/.tradingagents/...`` value
# (the project's ``.env.example`` uses that style). ``os.getenv`` does NOT
# expand ``~``, so the unexpanded string flowed into ``config["results_dir"]``
# and ``Path()`` resolved it relative to CWD — producing files at
# ``<cwd>/~/.tradingagents/logs/...`` instead of ``~/.tradingagents/logs/...``.
# The analysis runner happily wrote the log file to the wrong path, the
# history entry's ``results_path`` field (which mirrors this layout) ended
# up pointing at the wrong path, and ``/api/analyze/{id}/report`` 404'd
# even though the file existed on disk.
#
# We now ``expanduser`` the env-var fallback so both styles work — a
# literal ``~`` in .env gets the same expansion as the implicit default.
def _resolve_home_dir(env_var: str, default: str) -> str:
    """Read env_var, expanding ``~`` so .env-style values land in $HOME."""
    raw = os.getenv(env_var, default)
    return os.path.expanduser(raw)


DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": _resolve_home_dir(
        "TRADINGAGENTS_RESULTS_DIR",
        os.path.join(_TRADINGAGENTS_HOME, "logs"),
    ),
    "data_cache_dir": _resolve_home_dir(
        "TRADINGAGENTS_CACHE_DIR",
        os.path.join(_TRADINGAGENTS_HOME, "cache"),
    ),
    "memory_log_path": _resolve_home_dir(
        "TRADINGAGENTS_MEMORY_LOG_PATH",
        os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md"),
    ),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "Chinese",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "a_stock",        # Options: a_stock, alpha_vantage, yfinance
        "technical_indicators": "a_stock",   # Options: a_stock, alpha_vantage, yfinance
        "fundamental_data": "a_stock",       # Options: a_stock, alpha_vantage, yfinance
        "news_data": "a_stock",              # Options: a_stock, alpha_vantage, yfinance
        "signal_data": "a_stock",            # A-stock only: topic attribution, capital flow, consensus
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
}
