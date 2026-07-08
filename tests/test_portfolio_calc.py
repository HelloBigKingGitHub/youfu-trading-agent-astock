"""Tests for backend.core.portfolio_calc."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.core.portfolio_calc import (
    DEFAULT_RISK_FREE_RATE,
    PositionMetrics,
    PortfolioSummary,
    compute_brinson_attribution,
    compute_equity_curve,
    compute_max_drawdown,
    compute_portfolio_summary,
    compute_position_metrics,
    compute_sharpe,
    compute_xirr,
    group_by_sector,
)
from backend.core.portfolio_store import Position, Transaction


# ── helpers ─────────────────────────────────────────────────────────


def _tx(
    ticker="600595",
    date_str="2026-01-01",
    action="buy",
    price=10.0,
    quantity=100,
    fees=0.0,
    position_id="p1",
) -> Transaction:
    return Transaction(
        tx_id="t1",
        position_id=position_id,
        ticker=ticker,
        date=date_str,
        action=action,
        price=price,
        quantity=quantity,
        fees=fees,
    )


def _pos(
    ticker="600595",
    name="X",
    cost_basis=10.0,
    quantity=100,
    first_buy_date="2026-01-01",
    last_trade_date="2026-01-01",
    asset_class="stock",
) -> Position:
    return Position(
        position_id="p1",
        ticker=ticker,
        name=name,
        cost_basis=cost_basis,
        quantity=quantity,
        first_buy_date=first_buy_date,
        last_trade_date=last_trade_date,
        asset_class=asset_class,
    )


# ── PositionMetrics ─────────────────────────────────────────────────


class TestPositionMetrics:

    def test_basic_profit(self):
        pos = _pos(cost_basis=10.0, quantity=100)
        m = compute_position_metrics(pos, current_price=12.0, prev_close=11.5)
        assert m.current_value == 1200.0
        assert m.cost_value == 1000.0
        assert m.pnl_abs == 200.0
        assert m.pnl_pct == pytest.approx(0.2)
        assert m.today_pnl == pytest.approx(50.0)  # (12.0 - 11.5) * 100
        assert m.cost_basis == 10.0

    def test_loss_position(self):
        pos = _pos(cost_basis=10.0, quantity=100)
        m = compute_position_metrics(pos, current_price=8.0, prev_close=8.0)
        assert m.pnl_abs == -200.0
        assert m.pnl_pct == pytest.approx(-0.2)
        assert m.today_pnl == 0.0

    def test_holding_days_simple(self):
        pos = _pos(first_buy_date="2026-01-01")
        m = compute_position_metrics(
            pos, current_price=10.0, today="2026-06-01"
        )
        assert m.holding_days == 151  # Jan 1 → Jun 1

    def test_holding_days_garbage_date_falls_back_to_zero(self):
        pos = _pos(first_buy_date="not-a-date")
        m = compute_position_metrics(pos, current_price=10.0, today="2026-06-01")
        assert m.holding_days >= 0  # falls back to today

    def test_holding_days_garbage_today_falls_back(self):
        pos = _pos(first_buy_date="2026-01-01")
        m = compute_position_metrics(pos, current_price=10.0, today="garbage")
        assert m.holding_days >= 0

    def test_prev_close_defaults_to_current(self):
        """When prev_close is None, today_pnl is 0 (no phantom P&L)."""
        pos = _pos(cost_basis=10.0, quantity=100)
        m = compute_position_metrics(pos, current_price=12.0, prev_close=None)
        assert m.today_pnl == 0.0
        assert m.today_pnl_pct == 0.0

    def test_recomputes_weighted_avg_from_buys(self):
        """Two buys at different prices → weighted avg cost basis."""
        pos = _pos(cost_basis=999.0, quantity=200, first_buy_date="2026-01-01")
        txs = [
            _tx(action="buy", price=10.0, quantity=100, date_str="2026-01-01"),
            _tx(action="buy", price=20.0, quantity=100, date_str="2026-02-01"),
        ]
        m = compute_position_metrics(pos, current_price=15.0, transactions=txs)
        # (10*100 + 20*100) / 200 = 15
        assert m.cost_basis == pytest.approx(15.0)
        assert m.pnl_abs == 0.0
        assert m.pnl_pct == 0.0

    def test_recomputes_with_sell(self):
        """Sell does not change avg cost basis (still 15.0 across 100 shares post-sell)."""
        pos = _pos(cost_basis=999.0, quantity=200, first_buy_date="2026-01-01")
        txs = [
            _tx(action="buy", price=10.0, quantity=100, date_str="2026-01-01"),
            _tx(action="buy", price=20.0, quantity=100, date_str="2026-02-01"),
            _tx(action="sell", price=25.0, quantity=50, date_str="2026-03-01"),
        ]
        m = compute_position_metrics(pos, current_price=15.0, transactions=txs)
        # Weighted avg = (10*100 + 20*100) / 200 = 15.0 (sell doesn't change it).
        assert m.cost_basis == pytest.approx(15.0)
        # current_value uses position.quantity (200) — caller is responsible for
        # updating position.quantity after a sell (store.add_transaction does this).
        assert m.current_value == 15.0 * 200

    def test_no_buys_falls_back_to_position_cost(self):
        """If the tx log has no buys, fall back to position.cost_basis."""
        pos = _pos(cost_basis=8.0, quantity=100)
        m = compute_position_metrics(pos, current_price=10.0, transactions=[])
        assert m.cost_basis == 8.0

    def test_dividend_does_not_change_avg(self):
        pos = _pos(cost_basis=999.0, quantity=100)
        txs = [
            _tx(action="buy", price=10.0, quantity=100),
            _tx(action="dividend", price=0.5, quantity=100),
        ]
        m = compute_position_metrics(pos, current_price=10.0, transactions=txs)
        assert m.cost_basis == 10.0


# ── PortfolioSummary ────────────────────────────────────────────────


class TestPortfolioSummary:

    def test_basic_aggregation(self):
        positions = [
            _pos(ticker="600595", cost_basis=10.0, quantity=100),
            _pos(ticker="000001", cost_basis=5.0, quantity=200),
        ]
        prices = {"600595": 12.0, "000001": 4.0}
        s = compute_portfolio_summary(positions, prices)
        # total_value = 12*100 + 4*200 = 2000
        # total_cost = 10*100 + 5*200 = 2000
        # total_pnl = 0
        assert s.total_value == 2000.0
        assert s.total_cost == 2000.0
        assert s.total_pnl_abs == 0.0
        assert s.total_pnl_pct == 0.0
        assert s.positions_count == 2

    def test_concentration_top5(self):
        positions = [
            _pos(ticker="A", cost_basis=10.0, quantity=100),  # value depends on price
            _pos(ticker="B", cost_basis=10.0, quantity=100),
            _pos(ticker="C", cost_basis=10.0, quantity=100),
            _pos(ticker="D", cost_basis=10.0, quantity=100),
            _pos(ticker="E", cost_basis=10.0, quantity=100),
            _pos(ticker="F", cost_basis=10.0, quantity=100),
        ]
        prices = {p.ticker: 10.0 for p in positions}
        s = compute_portfolio_summary(positions, prices)
        # Top 5 of 6 equal positions = 5/6
        assert s.concentration_top5_pct == pytest.approx(5 / 6, rel=1e-3)

    def test_concentration_when_only_two_positions(self):
        positions = [
            _pos(ticker="A", cost_basis=10.0, quantity=100),
            _pos(ticker="B", cost_basis=10.0, quantity=100),
        ]
        prices = {"A": 10.0, "B": 10.0}
        s = compute_portfolio_summary(positions, prices)
        assert s.concentration_top5_pct == pytest.approx(1.0)

    def test_by_asset_class_breakdown(self):
        positions = [
            _pos(ticker="A", asset_class="stock"),
            _pos(ticker="B", asset_class="bond"),
            _pos(ticker="C", asset_class="cash"),
        ]
        prices = {p.ticker: 10.0 for p in positions}
        s = compute_portfolio_summary(positions, prices)
        assert s.by_asset_class == {"stock": 1000.0, "bond": 1000.0, "cash": 1000.0}

    def test_by_industry_passed_through(self):
        positions = [_pos(ticker="600595")]
        by_industry = {"科技": 1000.0}
        s = compute_portfolio_summary(positions, {"600595": 10.0}, by_industry=by_industry)
        assert s.by_industry == by_industry

    def test_by_sector_passed_through(self):
        positions = [_pos(ticker="600595")]
        by_sector = {"锂电池": 1000.0}
        s = compute_portfolio_summary(positions, {"600595": 10.0}, by_sector=by_sector)
        assert s.by_sector == by_sector

    def test_missing_price_falls_back_to_cost_basis(self):
        """If a ticker has no current price, treat it as flat (no phantom pnl)."""
        positions = [_pos(ticker="600595", cost_basis=10.0, quantity=100)]
        s = compute_portfolio_summary(positions, current_prices={})
        assert s.total_value == 1000.0
        assert s.total_pnl_abs == 0.0

    def test_empty_positions(self):
        s = compute_portfolio_summary([], {})
        assert s.total_value == 0.0
        assert s.positions_count == 0
        assert s.concentration_top5_pct == 0.0


# ── XIRR ────────────────────────────────────────────────────────────


class TestXIRR:

    def test_simple_buy_and_hold_one_year_doubles(self):
        """Buy 10 @ $100 ($1000 out), 1y later value $2000 → IRR ≈ 1.0 (100%)."""
        txs = [_tx(action="buy", price=100.0, quantity=10, date_str="2025-01-01")]
        irr = compute_xirr(txs, current_value=2000.0, as_of="2026-01-01")
        assert irr == pytest.approx(1.0, rel=0.01)

    def test_no_change_returns_zero(self):
        """Buy 10 @ $100 ($1000 out), value stays $1000 → IRR ≈ 0."""
        txs = [_tx(action="buy", price=100.0, quantity=10, date_str="2025-01-01")]
        irr = compute_xirr(txs, current_value=1000.0, as_of="2026-01-01")
        assert irr == pytest.approx(0.0, abs=1e-3)

    def test_loss(self):
        """Buy 10 @ $100 ($1000 out), value $500 after 1y → IRR ≈ -0.5."""
        txs = [_tx(action="buy", price=100.0, quantity=10, date_str="2025-01-01")]
        irr = compute_xirr(txs, current_value=500.0, as_of="2026-01-01")
        assert irr == pytest.approx(-0.5, rel=0.01)

    def test_sell_event_cash_flow(self):
        """Buy 10 @ $10 ($100 out), sell 5 @ $15 (1y later), remaining 5 worth $10 each → IRR > 0."""
        txs = [
            _tx(action="buy", price=10.0, quantity=10, date_str="2025-01-01"),
            _tx(action="sell", price=15.0, quantity=5, date_str="2026-01-01"),
        ]
        # Cash in from sale = $75, remaining 5 shares @ $10 = $50 → $125 total.
        irr = compute_xirr(txs, current_value=50.0, as_of="2026-06-01")
        assert irr > 0

    def test_dividend_ignored_in_cash_flow(self):
        """Dividends are zero-cash-flow; should not break XIRR."""
        txs = [
            _tx(action="buy", price=100.0, quantity=1, date_str="2025-01-01"),
            _tx(action="dividend", price=5.0, quantity=1, date_str="2025-06-01"),
        ]
        irr = compute_xirr(txs, current_value=100.0, as_of="2026-01-01")
        assert irr == pytest.approx(0.0, abs=1e-3)

    def test_no_transactions_returns_zero(self):
        assert compute_xirr([], current_value=100.0, as_of="2026-01-01") == 0.0

    def test_fallback_when_no_bracket(self):
        """All-zero flows fall back gracefully without raising."""
        txs = [_tx(action="buy", price=0.0, quantity=1, date_str="2025-01-01")]
        # Zero buy amount is filtered out → only one entry, no root → fallback.
        irr = compute_xirr(txs, current_value=0.0, as_of="2026-01-01")
        assert irr == 0.0


# ── Max drawdown ────────────────────────────────────────────────────


class TestMaxDrawdown:

    def test_empty_returns_zero(self):
        assert compute_max_drawdown([]) == 0.0

    def test_monotonic_up_returns_zero(self):
        curve = [(date(2026, 1, i + 1), float(i + 1)) for i in range(5)]
        assert compute_max_drawdown(curve) == 0.0

    def test_basic_peak_then_drop(self):
        # peak 100, drop to 50 → dd = 0.5
        curve = [
            (date(2026, 1, 1), 100.0),
            (date(2026, 1, 2), 50.0),
        ]
        assert compute_max_drawdown(curve) == pytest.approx(0.5)

    def test_multiple_peaks_takes_largest(self):
        curve = [
            (date(2026, 1, 1), 100.0),
            (date(2026, 1, 2), 50.0),    # dd 0.5
            (date(2026, 1, 3), 80.0),
            (date(2026, 1, 4), 40.0),    # dd from peak 80 = 0.5 (tie)
            (date(2026, 1, 5), 100.0),
            (date(2026, 1, 6), 25.0),    # dd from peak 100 = 0.75 (largest)
        ]
        assert compute_max_drawdown(curve) == pytest.approx(0.75)

    def test_drawdown_with_zero_value_is_safe(self):
        """A peak at 0 shouldn't divide-by-zero."""
        curve = [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 5.0)]
        assert compute_max_drawdown(curve) == 0.0


# ── Sharpe ──────────────────────────────────────────────────────────


class TestSharpe:

    def test_too_few_returns_zero(self):
        assert compute_sharpe([0.01]) == 0.0
        assert compute_sharpe([]) == 0.0

    def test_zero_std_returns_zero(self):
        """All-zero returns → std=0 → return 0 (don't divide)."""
        assert compute_sharpe([0.0, 0.0, 0.0]) == 0.0

    def test_all_positive_returns_positive_sharpe(self):
        # Use varied positive returns — constant series has std=0 → Sharpe=0.
        ret = [0.005 + 0.001 * (i % 5) for i in range(252)]
        s = compute_sharpe(ret)
        assert s > 0

    def test_all_negative_returns_negative_sharpe(self):
        ret = [-0.005 - 0.001 * (i % 5) for i in range(252)]
        s = compute_sharpe(ret)
        assert s < 0

    def test_mixed_returns_finite(self):
        ret = [0.02, -0.01, 0.005, -0.015, 0.01]
        s = compute_sharpe(ret)
        # Just verify the function runs without raising and produces a finite number.
        assert -100 < s < 100

    def test_risk_free_rate_default(self):
        """Default rf is 2.5% annualized (i.e. 0.025)."""
        ret = [DEFAULT_RISK_FREE_RATE / 252] * 252
        # When mean == rf_daily, Sharpe should be ~0.
        s = compute_sharpe(ret)
        assert s == pytest.approx(0.0, abs=1e-3)


# ── Brinson ─────────────────────────────────────────────────────────


class TestBrinson:

    def test_returns_selection_and_allocation_keys(self):
        positions = [_pos(ticker="600595", cost_basis=10.0, quantity=100)]
        out = compute_brinson_attribution(positions, {"600595": 0.05})
        assert "selection" in out
        assert "allocation" in out
        assert "total" in out
        # r_p is 0 (no current_price supplied) → selection = -w_p * r_b
        # w_p = 1.0 (single position), r_b = 0.05 → selection = -0.05
        assert out["selection"] == pytest.approx(-0.05, abs=1e-6)
        # allocation: (w_p - w_b) * r_b = (1 - 1) * 0.05 = 0
        assert out["allocation"] == 0.0
        assert out["total"] == pytest.approx(-0.05, abs=1e-6)

    def test_empty_positions_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            compute_brinson_attribution([], {})

    def test_two_positions_uniform_benchmark(self):
        positions = [
            _pos(ticker="600595", cost_basis=10.0, quantity=100),
            _pos(ticker="000001", cost_basis=5.0, quantity=200),
        ]
        out = compute_brinson_attribution(positions, {"600595": 0.1, "000001": 0.05})
        # Both r_p = 0; selection sums to -(w_p1 * 0.1 + w_p2 * 0.05)
        # w_p1 = 1000/2000 = 0.5, w_p2 = 1000/2000 = 0.5
        # selection = -(0.5 * 0.1 + 0.5 * 0.05) = -0.075
        assert out["selection"] == pytest.approx(-0.075, abs=1e-6)
        # allocation: (0.5 - 0.5) * 0.1 + (0.5 - 0.5) * 0.05 = 0
        assert out["allocation"] == 0.0


# ── Equity curve ────────────────────────────────────────────────────


class TestEquityCurve:

    def test_default_returns_n_points(self):
        positions = [_pos(cost_basis=10.0, quantity=100)]
        txs = [_tx(action="buy", price=10.0, quantity=100, date_str="2026-01-01")]
        curve = compute_equity_curve(
            positions, txs, {"600595": 12.0}, days=30,
            today="2026-06-01",
        )
        assert len(curve) == 30
        # Final day uses current price
        assert curve[-1][1] == 1200.0
        # All dates are valid date objects
        assert all(isinstance(d, date) for d, _ in curve)

    def test_no_buys_yields_zero_value(self):
        positions = [_pos()]
        txs: list[Transaction] = []
        curve = compute_equity_curve(positions, txs, {}, days=5, today="2026-01-05")
        assert all(v == 0.0 for _, v in curve)

    def test_buy_partway_through_window(self):
        """A position bought mid-window has value 0 before that date."""
        positions = [_pos(cost_basis=10.0, quantity=100, first_buy_date="2026-01-15")]
        txs = [_tx(action="buy", price=10.0, quantity=100, date_str="2026-01-15")]
        curve = compute_equity_curve(
            positions, txs, {"600595": 10.0}, days=20, today="2026-01-20"
        )
        # First 14 days (Jan 1-14): qty=0 → value 0
        # Day 15+: qty=100 → value 1000
        assert curve[0][1] == 0.0
        assert curve[-1][1] == 1000.0

    def test_sell_zeroes_out_after(self):
        positions = [_pos(cost_basis=10.0, quantity=100)]
        txs = [
            _tx(action="buy", price=10.0, quantity=100, date_str="2026-01-01"),
            _tx(action="sell", price=10.0, quantity=100, date_str="2026-01-10"),
        ]
        curve = compute_equity_curve(
            positions, txs, {"600595": 10.0}, days=15, today="2026-01-15"
        )
        # Days 1-9: qty=100 → value=1000
        # Days 10+: qty=0 → value=0
        assert curve[5][1] == 1000.0
        assert curve[-1][1] == 0.0


# ── group_by_sector (graceful failure) ──────────────────────────────


class TestGroupBySector:

    def test_fallback_when_a_stock_unavailable(self, monkeypatch):
        """Network failure on get_concept_blocks → fall back to 其他 bucket."""
        # Patch where it's looked up — group_by_sector imports lazily inside the fn.
        import tradingagents.dataflows.a_stock as a_stock

        def boom(ticker):
            raise RuntimeError("network down")

        monkeypatch.setattr(a_stock, "get_concept_blocks", boom)
        positions = [_pos(cost_basis=10.0, quantity=100)]
        out = group_by_sector(positions, {"600595": 10.0})
        # Single fallback bucket with total value
        assert out.get("其他") == 1000.0

    def test_parse_sector_text(self):
        from backend.core.portfolio_calc import _concept_block_to_sectors
        sample = (
            "# Concept & Sector Blocks for 600595 (A-stock)\n"
            "## 概念\n"
            "  锂电池: 1.23%\n"
            "## 行业\n"
            "  电子设备\n"
            "Concept tags: 锂电池 / 新能源车\n"
        )
        out = _concept_block_to_sectors(sample)
        assert "电子设备" in out
        assert "锂电池" in out
        assert "新能源车" in out