"""Tests for backend.core.portfolio_alerts (v0.5.0 MVP).

MVP 只实现 price_above / price_below；其它 5 种 type 抛 NotImplementedError。
"""

from __future__ import annotations

import time

import pytest

from backend.core.portfolio_alerts import (
    ANTI_REPEAT_WINDOW_SEC,
    AlertTrigger,
    evaluate_alert,
    evaluate_alerts,
    format_trigger_message,
)
from backend.core.portfolio_store import PortfolioStore


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path, monkeypatch):
    """隔离 PortfolioStore 到 tmp_path，每个测试独立。"""
    monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)
    monkeypatch.setattr("backend.core.portfolio_store.PortfolioStore._instance", None)
    return PortfolioStore()


# ── 单条评估 evaluate_alert ────────────────────────────────────────


class TestEvaluateAlert:
    """MVP 单条规则评估。"""

    def test_price_above_triggers_when_above(self, store):
        """price > threshold 触发 price_above."""
        rule = store.add_alert("600595", "price_above", 12.0)
        trigger = evaluate_alert(rule, current_price=12.5)
        assert trigger is not None
        assert trigger.rule_type == "price_above"
        assert trigger.threshold == 12.0
        assert trigger.current_value == 12.5
        assert "突破" in trigger.message

    def test_price_above_does_not_trigger_at_threshold(self, store):
        """price == threshold → 不触发（MVP 用严格 >）。"""
        rule = store.add_alert("600595", "price_above", 12.0)
        assert evaluate_alert(rule, current_price=12.0) is None

    def test_price_above_does_not_trigger_below(self, store):
        """price < threshold → 不触发。"""
        rule = store.add_alert("600595", "price_above", 12.0)
        assert evaluate_alert(rule, current_price=11.99) is None

    def test_price_below_triggers_when_below(self, store):
        """price < threshold 触发 price_below."""
        rule = store.add_alert("600595", "price_below", 10.0)
        trigger = evaluate_alert(rule, current_price=9.5)
        assert trigger is not None
        assert trigger.rule_type == "price_below"
        assert trigger.current_value == 9.5
        assert "跌破" in trigger.message

    def test_price_below_does_not_trigger_at_threshold(self, store):
        """price == threshold → 不触发（MVP 用严格 <）。"""
        rule = store.add_alert("600595", "price_below", 10.0)
        assert evaluate_alert(rule, current_price=10.0) is None

    def test_price_below_does_not_trigger_above(self, store):
        """price > threshold → 不触发。"""
        rule = store.add_alert("600595", "price_below", 10.0)
        assert evaluate_alert(rule, current_price=10.5) is None

    def test_pct_change_raises_not_implemented(self, store):
        """pct_change 在 MVP 抛 NotImplementedError。"""
        rule = store.add_alert("600595", "pct_change", 3.0)
        with pytest.raises(NotImplementedError):
            evaluate_alert(rule, current_price=10.0)

    def test_pnl_pct_raises_not_implemented(self, store):
        """pnl_pct 在 MVP 抛 NotImplementedError。"""
        rule = store.add_alert("600595", "pnl_pct", -10.0)
        with pytest.raises(NotImplementedError):
            evaluate_alert(rule, current_price=10.0)

    def test_take_profit_raises_not_implemented(self, store):
        """take_profit 在 MVP 抛 NotImplementedError。"""
        rule = store.add_alert("600595", "take_profit", 10.0)
        with pytest.raises(NotImplementedError):
            evaluate_alert(rule, current_price=10.0)

    def test_stop_loss_raises_not_implemented(self, store):
        """stop_loss 在 MVP 抛 NotImplementedError。"""
        rule = store.add_alert("600595", "stop_loss", 10.0)
        with pytest.raises(NotImplementedError):
            evaluate_alert(rule, current_price=10.0)

    def test_trailing_stop_raises_not_implemented(self, store):
        """trailing_stop 在 MVP 抛 NotImplementedError。"""
        rule = store.add_alert("600595", "trailing_stop", 10.0)
        with pytest.raises(NotImplementedError):
            evaluate_alert(rule, current_price=10.0)

    def test_trigger_message_format(self, store):
        """trigger.message 包含 ticker、threshold、current price 的中文描述。"""
        rule = store.add_alert("600595", "price_above", 12.0)
        trigger = evaluate_alert(rule, current_price=12.5)
        assert "12.00" in trigger.message  # threshold
        assert "12.50" in trigger.message  # current price
        # pct 变化：(12.5 - 12.0) / 12.0 ≈ 4.17%
        assert "4.17%" in trigger.message

    def test_trigger_message_threshold_zero_no_pct_suffix(self):
        """threshold=0 时不附加 pct 变化（避免除零）。

        直接构造 AlertRule（绕过 add_alert 的 threshold!=0 校验）。
        """
        from backend.core.portfolio_store import AlertRule
        rule = AlertRule(
            rule_id="r0", ticker="600595", rule_type="price_above",
            threshold=0.0,
        )
        trigger = evaluate_alert(rule, current_price=5.0)
        assert trigger is not None
        # message 没有括号包裹的百分比
        assert "(+" not in trigger.message  # 无 +X.XX% 后缀


# ── 批量评估 evaluate_alerts ───────────────────────────────────────


class TestEvaluateAlertsBatch:
    """批量评估 + anti-repeat + record_trigger。"""

    def test_empty_alerts_returns_empty(self, store):
        """无任何预警规则 → 空 list."""
        assert evaluate_alerts(store, {"600595": 10.0}) == []

    def test_all_rules_trigger_when_conditions_met(self, store):
        """3 条规则全部满足条件 → 返回 3 个 trigger."""
        store.add_alert("600595", "price_above", 12.0)
        store.add_alert("000001", "price_below", 5.0)
        store.add_alert("300001", "price_above", 8.0)
        triggers = evaluate_alerts(
            store,
            current_prices={"600595": 13.0, "000001": 4.5, "300001": 9.0},
        )
        assert len(triggers) == 3
        tickers = {t.ticker for t in triggers}
        assert tickers == {"600595", "000001", "300001"}

    def test_anti_repeat_within_300s(self, store):
        """300 秒内同一规则不重复触发。"""
        rule = store.add_alert("600595", "price_above", 12.0)
        now = 1_000_000.0
        # 第一次触发
        triggers1 = evaluate_alerts(
            store, {"600595": 13.0}, now=now,
        )
        assert len(triggers1) == 1
        # 200 秒后再次评估 → 仍在 300s 窗口内 → 跳过
        triggers2 = evaluate_alerts(
            store, {"600595": 14.0}, now=now + 200,
        )
        assert len(triggers2) == 0
        # trigger_count 仍为 1
        assert store.list_alerts(ticker="600595")[0].trigger_count == 1

    def test_anti_repeat_expires_after_300s(self, store):
        """300 秒后 anti-repeat 窗口过期 → 重新触发。"""
        rule = store.add_alert("600595", "price_above", 12.0)
        now = 1_000_000.0
        # 第一次
        triggers1 = evaluate_alerts(store, {"600595": 13.0}, now=now)
        assert len(triggers1) == 1
        # 350 秒后（> 300s）→ 重新触发
        triggers2 = evaluate_alerts(store, {"600595": 14.0}, now=now + 350)
        assert len(triggers2) == 1
        assert triggers2[0].current_value == 14.0
        # trigger_count = 2
        assert store.list_alerts(ticker="600595")[0].trigger_count == 2

    def test_disabled_alerts_skipped(self, store):
        """enabled=False 的规则不被评估。"""
        store.add_alert("600595", "price_above", 12.0, enabled=False)
        assert evaluate_alerts(store, {"600595": 13.0}) == []

    def test_missing_price_skipped(self, store):
        """current_prices 缺 ticker → 跳过该规则（不抛错）。"""
        store.add_alert("600595", "price_above", 12.0)
        store.add_alert("000001", "price_below", 5.0)
        # 只提供 600595 的报价
        triggers = evaluate_alerts(store, {"600595": 13.0})
        assert len(triggers) == 1
        assert triggers[0].ticker == "600595"

    def test_record_trigger_called_on_trigger(self, store):
        """成功触发的规则会被 store.record_trigger 写回 last_triggered_at/price/count."""
        rule = store.add_alert("600595", "price_above", 12.0)
        assert rule.trigger_count == 0
        assert rule.last_triggered_at is None

        evaluate_alerts(store, {"600595": 13.0}, now=1_000_000.0)

        refreshed = store.list_alerts(ticker="600595")[0]
        assert refreshed.trigger_count == 1
        assert refreshed.last_triggered_at == 1_000_000.0
        assert refreshed.last_triggered_price == 13.0

    def test_not_implemented_type_silently_skipped_in_batch(self, store):
        """pct_change 在批量评估中静默跳过，不影响其它规则。"""
        store.add_alert("600595", "pct_change", 3.0)
        store.add_alert("000001", "price_above", 5.0)
        triggers = evaluate_alerts(
            store, {"600595": 10.0, "000001": 6.0},
        )
        # pct_change 跳过，price_above 触发
        assert len(triggers) == 1
        assert triggers[0].ticker == "000001"


# ── 消息格式化 format_trigger_message ──────────────────────────────


class TestFormatTriggerMessage:
    """format_trigger_message 直接透传 trigger.message。"""

    def test_returns_trigger_message_unchanged(self):
        """直接返回构造时的 message，不二次格式化。"""
        trigger = AlertTrigger(
            rule_id="r1",
            ticker="600595",
            rule_type="price_above",
            threshold=12.0,
            current_value=12.5,
            triggered_at=time.time(),
            message="价格突破 12.00，当前 12.50 (+4.17%)",
        )
        assert format_trigger_message(trigger) == "价格突破 12.00，当前 12.50 (+4.17%)"

    def test_constant_anti_repeat_window_is_300(self):
        """ANTI_REPEAT_WINDOW_SEC = 300。"""
        assert ANTI_REPEAT_WINDOW_SEC == 300