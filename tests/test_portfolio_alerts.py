"""Tests for backend.core.portfolio_alerts."""

from __future__ import annotations

import time

import pytest

from backend.core.portfolio_alerts import (
    ANTI_REPEAT_WINDOW_SEC,
    AlertTrigger,
    evaluate_alerts,
    format_trigger_message,
)
from backend.core.portfolio_store import PortfolioStore


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)
    monkeypatch.setattr("backend.core.portfolio_store.PortfolioStore._instance", None)
    return PortfolioStore()


# ── trigger per rule_type ───────────────────────────────────────────


class TestPriceAbove:

    def test_triggers_when_price_above_threshold(self, store):
        store.add_alert("600595", "price_above", 12.0)
        triggers = evaluate_alerts(store, {"600595": 12.5})
        assert len(triggers) == 1
        assert triggers[0].rule_type == "price_above"
        assert triggers[0].current_value == 12.5

    def test_triggers_at_exact_threshold(self, store):
        """Boundary: price == threshold → still triggers (>=)."""
        store.add_alert("600595", "price_above", 12.0)
        triggers = evaluate_alerts(store, {"600595": 12.0})
        assert len(triggers) == 1

    def test_does_not_trigger_below_threshold(self, store):
        store.add_alert("600595", "price_above", 12.0)
        assert evaluate_alerts(store, {"600595": 11.99}) == []


class TestPriceBelow:

    def test_triggers_when_price_below_threshold(self, store):
        store.add_alert("600595", "price_below", 10.0)
        triggers = evaluate_alerts(store, {"600595": 9.5})
        assert len(triggers) == 1

    def test_does_not_trigger_above_threshold(self, store):
        store.add_alert("600595", "price_below", 10.0)
        assert evaluate_alerts(store, {"600595": 10.5}) == []


class TestPctChange:

    def test_triggers_on_large_up_move(self, store):
        store.add_alert("600595", "pct_change", 3.0)
        triggers = evaluate_alerts(store, {"600595": 11.0}, prev_closes={"600595": 10.0})
        # +10% change vs threshold 3% → triggers
        assert len(triggers) == 1

    def test_triggers_on_large_down_move(self, store):
        store.add_alert("600595", "pct_change", 3.0)
        triggers = evaluate_alerts(store, {"600595": 9.0}, prev_closes={"600595": 10.0})
        # -10% change vs threshold 3% → triggers (abs)
        assert len(triggers) == 1

    def test_no_trigger_for_small_move(self, store):
        store.add_alert("600595", "pct_change", 5.0)
        triggers = evaluate_alerts(store, {"600595": 10.2}, prev_closes={"600595": 10.0})
        assert triggers == []


class TestPnlPct:

    def test_triggers_when_gain_exceeds_threshold(self, store):
        store.add_alert("600595", "pnl_pct", 5.0)
        # current 11, cost 10 → +10% pnl vs threshold 5%
        triggers = evaluate_alerts(store, {"600595": 11.0}, cost_bases={"600595": 10.0})
        assert len(triggers) == 1

    def test_does_not_trigger_below_threshold(self, store):
        store.add_alert("600595", "pnl_pct", 20.0)
        triggers = evaluate_alerts(store, {"600595": 10.5}, cost_bases={"600595": 10.0})
        # +5% < 20% threshold
        assert triggers == []


class TestTakeProfitStopLoss:

    def test_take_profit_triggers(self, store):
        """Take profit @ +10%: current 11, cost 10 → triggers."""
        store.add_alert("600595", "take_profit", 10.0)
        triggers = evaluate_alerts(store, {"600595": 11.0}, cost_bases={"600595": 10.0})
        assert len(triggers) == 1

    def test_stop_loss_triggers(self, store):
        """Stop loss @ -5%: current 9, cost 10 → triggers."""
        store.add_alert("600595", "stop_loss", 5.0)
        triggers = evaluate_alerts(store, {"600595": 9.0}, cost_bases={"600595": 10.0})
        assert len(triggers) == 1

    def test_trailing_stop_same_as_stop_loss_in_v1(self, store):
        store.add_alert("600595", "trailing_stop", 5.0)
        triggers = evaluate_alerts(store, {"600595": 9.0}, cost_bases={"600595": 10.0})
        assert len(triggers) == 1


# ── anti-repeat / disabled ──────────────────────────────────────────


class TestAntiRepeat:

    def test_does_not_re_trigger_within_window(self, store):
        store.add_alert("600595", "price_above", 12.0)
        now = 1_000_000.0
        # First trigger succeeds.
        first = evaluate_alerts(store, {"600595": 12.5}, now=now)
        assert len(first) == 1
        # Second call 60s later should NOT fire (anti-repeat).
        second = evaluate_alerts(store, {"600595": 12.5}, now=now + 60)
        assert second == []

    def test_triggers_again_after_window_expires(self, store):
        store.add_alert("600595", "price_above", 12.0)
        now = 1_000_000.0
        evaluate_alerts(store, {"600595": 12.5}, now=now)
        # Way after the cooldown window
        later = evaluate_alerts(store, {"600595": 12.5}, now=now + ANTI_REPEAT_WINDOW_SEC + 1)
        assert len(later) == 1

    def test_record_trigger_increments_count(self, store):
        store.add_alert("600595", "price_above", 12.0)
        now = 1_000_000.0
        evaluate_alerts(store, {"600595": 12.5}, now=now)
        # After window expires, trigger again → count == 2
        evaluate_alerts(store, {"600595": 12.5}, now=now + ANTI_REPEAT_WINDOW_SEC + 1)
        rule = store.list_alerts(ticker="600595")[0]
        assert rule.trigger_count == 2


class TestDisabledAndMissing:

    def test_disabled_alert_does_not_trigger(self, store):
        store.add_alert("600595", "price_above", 12.0, enabled=False)
        triggers = evaluate_alerts(store, {"600595": 12.5})
        assert triggers == []

    def test_missing_price_skips_rule(self, store):
        store.add_alert("600595", "price_above", 12.0)
        # No price for 600595 in the snapshot
        assert evaluate_alerts(store, {"000001": 12.5}) == []

    def test_only_enabled_rules_are_evaluated(self, store):
        store.add_alert("600595", "price_above", 12.0, enabled=True)
        store.add_alert("000001", "price_above", 12.0, enabled=False)
        triggers = evaluate_alerts(store, {"600595": 12.5, "000001": 12.5})
        assert len(triggers) == 1
        assert triggers[0].ticker == "600595"


# ── message formatting ──────────────────────────────────────────────


class TestFormatTriggerMessage:

    def test_explicit_message_passed_through(self):
        t = AlertTrigger(
            rule_id="r1", ticker="600595", rule_type="price_above",
            threshold=12.0, current_value=12.5,
            triggered_at=time.time(), message="custom msg",
        )
        assert format_trigger_message(t) == "custom msg"

    def test_fallback_format_when_no_message(self):
        t = AlertTrigger(
            rule_id="r1", ticker="600595", rule_type="price_above",
            threshold=12.0, current_value=12.5, triggered_at=time.time(),
        )
        out = format_trigger_message(t)
        assert "600595" in out
        assert "12.50" in out


# ── integration with store ──────────────────────────────────────────


class TestEvaluateAlertsIntegration:

    def test_returns_trigger_per_fired_rule(self, store):
        store.add_alert("600595", "price_above", 12.0)
        store.add_alert("000001", "price_below", 5.0)
        store.add_alert("300750", "price_above", 100.0, enabled=False)  # disabled
        triggers = evaluate_alerts(
            store,
            {"600595": 13.0, "000001": 4.5, "300750": 200.0},
        )
        tickers = sorted(t.rule_id for t in triggers)  # sort for stability
        assert len(triggers) == 2
        # Each fired trigger has a unique rule_id and a positive message.
        for t in triggers:
            assert t.rule_id
            assert t.message
            assert t.triggered_at > 0

    def test_mixed_triggers_recorded_once(self, store):
        store.add_alert("600595", "price_above", 12.0)
        before = store.list_alerts(ticker="600595")[0].trigger_count
        evaluate_alerts(store, {"600595": 13.0})
        after = store.list_alerts(ticker="600595")[0].trigger_count
        assert after == before + 1