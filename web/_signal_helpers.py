"""Shared UI helpers for signal badges.

Single source of truth for the (signal, status) → (kind, label) mapping used
by both the main area recent-analysis cards and the sidebar history list.
"""

from __future__ import annotations


def signal_badge(signal: str, status: str) -> tuple[str, str]:
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
