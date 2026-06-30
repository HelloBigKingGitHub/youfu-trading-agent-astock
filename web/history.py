"""Manage analysis history using the unified history_store."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.history_store import get_history_store


def get_history() -> list[dict[str, str]]:
    """Return history entries as dicts compatible with the Streamlit sidebar.

    Each entry: {"ticker": "300750", "date": "2026-05-12", "path": "/abs/path/...json"}
    The 'path' points to the full_states_log_*.json for report viewing,
    or to the history entry itself if no full results file exists.
    """
    store = get_history_store()
    entries, _ = store.list_all(limit=100, offset=0)
    results: list[dict[str, str]] = []
    for e in entries:
        path = e.results_path
        if not path or not Path(path).exists():
            # Fallback: try to find the full_states_log file
            log_root = Path.home() / ".tradingagents" / "logs"
            ticker_dir = log_root / e.ticker
            fallback = ticker_dir / "TradingAgentsStrategy_logs" / f"full_states_log_{e.trade_date}.json"
            path = str(fallback) if fallback.exists() else ""
        results.append({
            "ticker": e.ticker,
            "date": e.trade_date,
            "path": path,
            "status": e.status,
            "signal": e.signal,
            "elapsed": e.elapsed,
            "analysis_id": e.analysis_id,
        })
    return results


def load_analysis(path: str) -> dict[str, Any]:
    """Load a saved analysis JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_signal(state: dict[str, Any]) -> str:
    """Extract the short signal (Buy/Sell/Hold) from a final state dict."""
    import re

    for field in (
        "investment_plan",
        "trader_investment_decision",
        "final_trade_decision",
    ):
        text = state.get(field, "")
        if not text:
            continue
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        for keyword in ("BUY", "SELL", "HOLD"):
            if keyword in cleaned.upper():
                return keyword.capitalize()
    return "N/A"
