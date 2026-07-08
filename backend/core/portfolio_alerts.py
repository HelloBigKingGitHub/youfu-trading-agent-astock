"""Portfolio alert engine — evaluate rules against current prices.

Trigger model: on-demand. The Streamlit panel calls `evaluate_alerts(store,
current_prices)` whenever the user enters Tab 1 or hits the
"检查预警" button. There is no background scheduler — matches the project's
single-process Streamlit architecture (see design.md Decision 3).

Each AlertRule is matched against `current_prices` keyed by 6-digit ticker.
Rules whose `last_triggered_at` is within ANTI_REPEAT_WINDOW seconds are
skipped so a single re-render doesn't fire the same alert 60 times.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

if TYPE_CHECKING:
    from backend.core.portfolio_store import AlertRule, PortfolioStore

ANTI_REPEAT_WINDOW_SEC = 300  # 5 minutes


@dataclass
class AlertTrigger:
    """One fired alert, returned by `evaluate_alerts` for the UI to render."""

    rule_id: str
    ticker: str
    rule_type: str
    threshold: float
    current_value: float
    triggered_at: float
    message: str = ""


def _price_change_pct(current_price: float, prev_close: float) -> float:
    """Today's pct move. Returns 0 when prev_close is missing/zero."""
    if not prev_close:
        return 0.0
    return (current_price - prev_close) / prev_close * 100.0


def _pnl_pct(current_price: float, cost_basis: float) -> float:
    """Realized-vs-cost return as percentage. 0 when cost_basis missing."""
    if not cost_basis:
        return 0.0
    return (current_price - cost_basis) / cost_basis * 100.0


def _should_trigger(
    rule: "AlertRule",
    current_price: float,
    prev_close: float | None = None,
    cost_basis: float | None = None,
) -> bool:
    """Pure rule logic. No side effects, no IO."""
    rt = rule.rule_type
    threshold = rule.threshold

    if rt == "price_above":
        return current_price >= threshold
    if rt == "price_below":
        return current_price <= threshold
    if rt == "pct_change":
        # threshold in %; trigger on |today_pct| >= threshold.
        pct = _price_change_pct(current_price, prev_close or current_price)
        return abs(pct) >= abs(threshold)
    if rt == "pnl_pct":
        # threshold in %; trigger when pnl_pct >= threshold (signed).
        pct = _pnl_pct(current_price, cost_basis or 0.0)
        return pct >= threshold
    if rt == "take_profit":
        # threshold is a multiplier on cost_basis in pct (e.g. 10 means +10%).
        if not cost_basis:
            return False
        target = cost_basis * (1 + threshold / 100.0)
        return current_price >= target
    if rt == "stop_loss":
        if not cost_basis:
            return False
        target = cost_basis * (1 - threshold / 100.0)
        return current_price <= target
    if rt == "trailing_stop":
        # v1 fallback: behave like stop_loss until P3 implements trailing high.
        if not cost_basis:
            return False
        target = cost_basis * (1 - threshold / 100.0)
        return current_price <= target
    return False


def _build_message(
    rule: "AlertRule",
    current_price: float,
    prev_close: float | None,
    cost_basis: float | None,
) -> str:
    """Compose a human-readable Chinese message. Falls back gracefully."""
    threshold = rule.threshold
    if rule.rule_type == "price_above":
        return f"价格突破 {threshold:.2f}，当前 {current_price:.2f}"
    if rule.rule_type == "price_below":
        return f"价格跌破 {threshold:.2f}，当前 {current_price:.2f}"
    if rule.rule_type == "pct_change":
        pct = _price_change_pct(current_price, prev_close or current_price)
        return f"当日涨跌幅 {pct:+.2f}%，触发阈值 {threshold:.2f}%"
    if rule.rule_type == "pnl_pct":
        pct = _pnl_pct(current_price, cost_basis or 0.0)
        return f"持仓盈亏 {pct:+.2f}%，触发阈值 {threshold:+.2f}%"
    if rule.rule_type == "take_profit":
        pct = _pnl_pct(current_price, cost_basis or 0.0)
        return f"止盈触发：当前 {current_price:.2f}，盈亏 {pct:+.2f}%"
    if rule.rule_type in ("stop_loss", "trailing_stop"):
        pct = _pnl_pct(current_price, cost_basis or 0.0)
        return f"止损触发：当前 {current_price:.2f}，盈亏 {pct:+.2f}%"
    return f"规则 {rule.rule_type} 触发：当前 {current_price:.2f}"


def evaluate_alerts(
    store: "PortfolioStore",
    current_prices: dict[str, float],
    prev_closes: dict[str, float] | None = None,
    cost_bases: dict[str, float] | None = None,
    now: float | None = None,
) -> list[AlertTrigger]:
    """Walk all enabled rules, fire those whose condition is met.

    Anti-repeat: rules triggered within ANTI_REPEAT_WINDOW_SEC are skipped,
    and successfully fired rules are stamped via `store.record_trigger` so
    the next call respects the cooldown.

    `prev_closes` and `cost_bases` are optional; missing entries fall back
    to current_price (so pct_change / pnl_pct become 0 and won't fire).
    """
    if now is None:
        now = time.time()
    prev_closes = prev_closes or {}
    cost_bases = cost_bases or {}

    enabled = store.list_alerts(enabled_only=True)
    out: list[AlertTrigger] = []
    for rule in enabled:
        price = current_prices.get(rule.ticker)
        if price is None:
            continue
        # Anti-repeat guard
        if (
            rule.last_triggered_at is not None
            and now - rule.last_triggered_at < ANTI_REPEAT_WINDOW_SEC
        ):
            continue

        if not _should_trigger(
            rule,
            price,
            prev_close=prev_closes.get(rule.ticker),
            cost_basis=cost_bases.get(rule.ticker),
        ):
            continue

        message = _build_message(
            rule,
            price,
            prev_closes.get(rule.ticker),
            cost_bases.get(rule.ticker),
        )
        trigger = AlertTrigger(
            rule_id=rule.rule_id,
            ticker=rule.ticker,
            rule_type=rule.rule_type,
            threshold=rule.threshold,
            current_value=price,
            triggered_at=now,
            message=message,
        )
        out.append(trigger)
        try:
            store.record_trigger(rule.rule_id, price, now=now)
        except KeyError:
            # Rule vanished between list and record — skip silently.
            pass
    return out


def format_trigger_message(trigger: AlertTrigger) -> str:
    """Format an AlertTrigger for display (e.g. toast / banner)."""
    if trigger.message:
        return trigger.message
    return f"{trigger.ticker} 规则 {trigger.rule_type} 触发，当前 {trigger.current_value:.2f}"