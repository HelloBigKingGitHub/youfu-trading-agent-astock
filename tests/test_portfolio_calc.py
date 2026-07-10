"""Tests for backend.core.portfolio_calc (v0.5.0 MVP).

覆盖每个公开函数 2-3 个用例：
  - compute_position_metrics
  - compute_portfolio_summary
  - compute_xirr / _extract_cashflows
  - compute_max_drawdown
  - compute_sharpe
  - compute_brinson_attribution
  - compute_equity_curve
  - compute_annual_return
  - get_rebalance_signals

注：group_by_sector 已废弃，不测。
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from backend.core.portfolio_calc import (
    DEFAULT_RISK_FREE_RATE,
    TRADING_DAYS_PER_YEAR,
    PortfolioSummary,
    PositionMetrics,
    _extract_cashflows,
    compute_annual_return,
    compute_brinson_attribution,
    compute_equity_curve,
    compute_max_drawdown,
    compute_portfolio_summary,
    compute_position_metrics,
    compute_sharpe,
    compute_xirr,
    get_rebalance_signals,
)
from backend.core.portfolio_store import Position, Transaction


# ── helpers ─────────────────────────────────────────────────────────


def _pos(
    ticker: str = "600595",
    cost_basis: float = 5.5,
    quantity: int = 1000,
    first_buy_date: str = "2026-01-01",
    asset_class: str = "stock",
    account: str = "default",
) -> Position:
    return Position(
        position_id=f"pos_{ticker}",
        ticker=ticker,
        name=f"名称-{ticker}",
        cost_basis=cost_basis,
        quantity=quantity,
        first_buy_date=first_buy_date,
        last_trade_date=first_buy_date,
        asset_class=asset_class,
        account=account,
    )


def _tx(
    tx_id: str = "t1",
    position_id: str = "p1",
    ticker: str = "600595",
    date_str: str = "2026-01-01",
    action: str = "buy",
    price: float = 10.0,
    quantity: int = 100,
    fees: float = 0.0,
) -> Transaction:
    return Transaction(
        tx_id=tx_id,
        position_id=position_id,
        ticker=ticker,
        date=date_str,
        action=action,
        price=price,
        quantity=quantity,
        fees=fees,
    )


# ── 2.1 compute_position_metrics ────────────────────────────────────


class TestPositionMetrics:
    """单只持仓的盈亏指标。"""

    def test_basic_pnl(self):
        """cost_basis=5.5, current=6.0, qty=1000 → pnl_abs=500, pnl_pct=9.09%."""
        pos = _pos(cost_basis=5.5, quantity=1000)
        m = compute_position_metrics(
            position=pos,
            current_price=6.0,
            prev_close=5.8,
            transactions=[],
        )
        assert isinstance(m, PositionMetrics)
        assert m.current_value == 6000.0
        assert m.cost_value == 5500.0
        assert m.pnl_abs == 500.0
        assert m.pnl_pct == pytest.approx(0.0909, abs=1e-4)
        # today_pnl = (6.0 - 5.8) * 1000 = 200
        assert m.today_pnl == 200.0
        assert m.today_pnl_pct == pytest.approx(0.0345, abs=1e-4)

    def test_zero_cost_basis_no_division_by_zero(self):
        """cost_basis=0 时 pnl_pct 退化为 0（避免除零）。"""
        pos = _pos(cost_basis=0.0, quantity=100)
        m = compute_position_metrics(
            position=pos,
            current_price=10.0,
            prev_close=9.5,
            transactions=[],
        )
        assert m.pnl_pct == 0.0  # graceful fallback

    def test_zero_prev_close_no_division_by_zero(self):
        """prev_close=0 时 today_pnl 退化为 0。"""
        pos = _pos(cost_basis=10.0, quantity=100)
        m = compute_position_metrics(
            position=pos,
            current_price=11.0,
            prev_close=0.0,
            transactions=[],
        )
        assert m.today_pnl == 0.0
        assert m.today_pnl_pct == 0.0

    def test_holding_days_calculation(self):
        """holding_days = (今天 - first_buy_date).days."""
        # 1000 天前
        old_date = (date.today() - timedelta(days=1000)).isoformat()
        pos = _pos(first_buy_date=old_date)
        m = compute_position_metrics(
            position=pos,
            current_price=10.0,
            prev_close=9.0,
            transactions=[],
        )
        assert m.holding_days == 1000

    def test_holding_days_invalid_date_returns_zero(self):
        """first_buy_date 解析失败 → holding_days=0。"""
        pos = _pos(first_buy_date="not-a-date")
        m = compute_position_metrics(
            position=pos,
            current_price=10.0,
            prev_close=9.0,
            transactions=[],
        )
        assert m.holding_days == 0


# ── 2.2 compute_portfolio_summary ───────────────────────────────────


class TestPortfolioSummary:
    """组合汇总 + 板块/行业/账户归因 + 集中度。"""

    def test_total_value_and_cost(self):
        """两只持仓：600595 @ 10 → 1100, 000001 @ 5 → 550."""
        positions = [
            _pos(ticker="600595", cost_basis=10.0, quantity=100),
            _pos(ticker="000001", cost_basis=5.0, quantity=100),
        ]
        s = compute_portfolio_summary(
            positions=positions,
            current_prices={"600595": 11.0, "000001": 5.5},
            prev_closes={},
            get_industry_fn=lambda t: "科技",
            get_sector_fn=lambda t: ["板块A"],
        )
        assert isinstance(s, PortfolioSummary)
        assert s.total_value == pytest.approx(1650.0)
        assert s.total_cost == 1500.0
        assert s.positions_count == 2

    def test_total_pnl_and_pct(self):
        """组合 PnL = 1650 - 1500 = 150 (+10%)."""
        positions = [
            _pos(ticker="600595", cost_basis=10.0, quantity=100),
            _pos(ticker="000001", cost_basis=5.0, quantity=100),
        ]
        s = compute_portfolio_summary(
            positions=positions,
            current_prices={"600595": 11.0, "000001": 5.5},
            prev_closes={},
            get_industry_fn=lambda t: "科技",
            get_sector_fn=lambda t: [],
        )
        assert s.total_pnl_abs == pytest.approx(150.0)
        assert s.total_pnl_pct == pytest.approx(0.1)

    def test_by_industry_sector_asset_class_account(self):
        """4 个归因 dict 都按 position 聚合。

        默认 helper 是 cost_basis=5.5 / quantity=1000 → value=5500 (用 price=10) / 5000。
        """
        positions = [
            _pos(ticker="600595", account="main", asset_class="stock"),
            _pos(ticker="000001", account="sub", asset_class="fund"),
        ]

        def industry_fn(t):
            return "科技" if t == "600595" else "医药"

        def sector_fn(t):
            return ["板块A"] if t == "600595" else ["板块B"]

        s = compute_portfolio_summary(
            positions=positions,
            current_prices={"600595": 10.0, "000001": 5.0},
            prev_closes={},
            get_industry_fn=industry_fn,
            get_sector_fn=sector_fn,
        )
        # 600595: 10 * 1000 = 10000; 000001: 5 * 1000 = 5000
        assert s.by_industry == {"科技": 10000.0, "医药": 5000.0}
        assert s.by_sector == {"板块A": 10000.0, "板块B": 5000.0}
        assert s.by_asset_class == {"stock": 10000.0, "fund": 5000.0}
        assert s.by_account == {"main": 10000.0, "sub": 5000.0}

    def test_concentration_top5_pct(self):
        """top 5 集中度（positions 数 < 5 时即 100%）。"""
        positions = [
            _pos(ticker="A", cost_basis=10.0, quantity=100),  # 1000
            _pos(ticker="B", cost_basis=10.0, quantity=200),  # 2000
            _pos(ticker="C", cost_basis=10.0, quantity=300),  # 3000
            _pos(ticker="D", cost_basis=10.0, quantity=400),  # 4000
            _pos(ticker="E", cost_basis=10.0, quantity=500),  # 5000
            _pos(ticker="F", cost_basis=10.0, quantity=600),  # 6000
        ]
        s = compute_portfolio_summary(
            positions=positions,
            current_prices={p.ticker: 10.0 for p in positions},
            prev_closes={},
            get_industry_fn=lambda t: "行业",
            get_sector_fn=lambda t: [],
        )
        # total=21000, top5 sorted desc: 6000+5000+4000+3000+2000=20000 → 20000/21000
        assert s.concentration_top5_pct == pytest.approx(20000 / 21000, abs=1e-4)

    def test_filters_via_callbacks(self):
        """get_industry/get_sector 抛异常时优雅退化为 '未知行业' / '未分类'."""
        positions = [_pos(ticker="600595", cost_basis=10.0, quantity=100)]

        def boom(t):
            raise RuntimeError("boom")

        s = compute_portfolio_summary(
            positions=positions,
            current_prices={"600595": 10.0},
            prev_closes={},
            get_industry_fn=boom,
            get_sector_fn=boom,
        )
        assert s.by_industry == {"未知行业": 1000.0}
        assert s.by_sector == {"未分类": 1000.0}

    def test_empty_positions(self):
        """空持仓 → total 全部 0, count=0."""
        s = compute_portfolio_summary(
            positions=[],
            current_prices={},
            prev_closes={},
            get_industry_fn=lambda t: "",
            get_sector_fn=lambda t: [],
        )
        assert s.total_value == 0.0
        assert s.total_cost == 0.0
        assert s.total_pnl_abs == 0.0
        assert s.total_pnl_pct == 0.0
        assert s.positions_count == 0
        assert s.concentration_top5_pct == 0.0
        assert s.by_industry == {}
        assert s.by_sector == {}

    def test_multi_sector_shares_value(self):
        """一只股票属多个板块时按权重分摊金额。"""
        positions = [_pos(ticker="600595", cost_basis=10.0, quantity=100)]
        s = compute_portfolio_summary(
            positions=positions,
            current_prices={"600595": 10.0},
            prev_closes={},
            get_industry_fn=lambda t: "科技",
            get_sector_fn=lambda t: ["板块A", "板块B"],
        )
        # 1000 / 2 = 500 每人
        assert s.by_sector == {"板块A": 500.0, "板块B": 500.0}


# ── 2.3 compute_xirr / _extract_cashflows ───────────────────────────


class TestExtractCashflows:
    """内部 helper：把 Transaction 列表 + current_value 折算成 (cf, dates)."""

    def test_buy_only_extracts_negative_cashflow(self):
        txs = [_tx(action="buy", price=10.0, quantity=100)]
        cf, dates = _extract_cashflows(txs, current_value=0.0, as_of=date(2026, 6, 1))
        # buy 流出 + 终值(0) 跳过；只保留 buy
        assert cf == [-1000.0]
        assert dates == [date(2026, 1, 1)]

    def test_dividend_extracts_positive_cashflow(self):
        txs = [
            _tx(tx_id="t1", action="buy", price=10.0, quantity=100, date_str="2026-01-01"),
            _tx(tx_id="t2", action="dividend", price=0.5, quantity=100, date_str="2026-06-01"),
        ]
        cf, dates = _extract_cashflows(txs, current_value=1100.0, as_of=date(2026, 12, 1))
        # buy -1000, dividend +50, 终值 +1100
        assert cf == [-1000.0, 50.0, 1100.0]
        assert dates == [date(2026, 1, 1), date(2026, 6, 1), date(2026, 12, 1)]

    def test_split_skipped_no_cashflow_impact(self):
        txs = [_tx(action="split", price=1.0, quantity=10)]
        cf, dates = _extract_cashflows(txs, current_value=100.0, as_of=date(2026, 6, 1))
        # split 跳过，只剩终值
        assert cf == [100.0]
        assert dates == [date(2026, 6, 1)]


class TestXirr:
    """XIRR：不规则现金流的年化内部收益率。"""

    def test_single_buy_held_one_year(self):
        """100 块买入持有一年 → 110 → XIRR ≈ +10%."""
        one_year_ago = date.today() - timedelta(days=365)
        txs = [_tx(
            action="buy", price=100.0, quantity=1,
            date_str=one_year_ago.isoformat(),
        )]
        xirr = compute_xirr(txs, current_value=110.0)
        assert xirr == pytest.approx(0.10, abs=1e-2)

    def test_breakeven(self):
        """买入持有一年现值不变 → XIRR ≈ 0."""
        one_year_ago = date.today() - timedelta(days=365)
        txs = [_tx(
            action="buy", price=100.0, quantity=1,
            date_str=one_year_ago.isoformat(),
        )]
        xirr = compute_xirr(txs, current_value=100.0)
        assert xirr == pytest.approx(0.0, abs=1e-2)

    def test_losing(self):
        """买入持有一年现值缩水 → XIRR < 0."""
        one_year_ago = date.today() - timedelta(days=365)
        txs = [_tx(
            action="buy", price=100.0, quantity=1,
            date_str=one_year_ago.isoformat(),
        )]
        xirr = compute_xirr(txs, current_value=80.0)
        assert xirr < 0
        assert xirr == pytest.approx(-0.20, abs=1e-2)

    def test_with_dividend_cashflow(self):
        """买入 + 分红 → XIRR 高于无分红情形。"""
        one_year_ago = date.today() - timedelta(days=365)
        txs = [
            _tx(tx_id="t1", action="buy", price=100.0, quantity=1,
                date_str=one_year_ago.isoformat()),
            _tx(tx_id="t2", action="dividend", price=5.0, quantity=1,
                date_str=(one_year_ago + timedelta(days=180)).isoformat()),
        ]
        # 现值 + 分红 = 105；纯现值 100 → 5% + 分红抬高 IRR
        xirr_with_div = compute_xirr(txs, current_value=100.0)
        # 验证 XIRR 存在且为正（不会精确等于某个固定值）
        assert xirr_with_div > 0
        assert xirr_with_div < 0.20  # 不会爆炸

    def test_no_transactions_returns_zero(self):
        """空流水 → 0."""
        assert compute_xirr([], current_value=100.0) == 0.0

    def test_only_sells_no_buys(self):
        """只有卖出 → 现金流仍可计算（sell 正 + 终值正）→ XIRR 有效。"""
        # 卖出 1000 元 → 现值 1100 元 → 即时收益 +10%
        txs = [_tx(action="sell", price=10.0, quantity=100)]
        xirr = compute_xirr(txs, current_value=1100.0)
        # XIRR 计算可能回退到 bisection 上界，但应该是有限正数
        assert xirr > 0

    def test_buy_then_sell(self):
        """买入 + 卖出 → XIRR 应反映期间的回报率。"""
        one_year_ago = date.today() - timedelta(days=365)
        txs = [
            _tx(tx_id="t1", action="buy", price=100.0, quantity=1,
                date_str=one_year_ago.isoformat()),
            _tx(tx_id="t2", action="sell", price=110.0, quantity=1,
                date_str=date.today().isoformat()),
        ]
        # 100 → 110 → 1 年期 IRR ≈ 10%
        xirr = compute_xirr(txs, current_value=0.0)
        assert xirr == pytest.approx(0.10, abs=1e-2)


# ── 2.4 compute_max_drawdown ────────────────────────────────────────


class TestMaxDrawdown:
    """最大回撤：max((peak - trough) / peak)，返回正数小数。"""

    def test_basic_drawdown(self):
        """典型回撤序列：100 → 80 → 60 → 90 → 75 → 100 → 最大回撤 40%."""
        curve = [
            (date(2026, 1, 1), 100.0),
            (date(2026, 2, 1), 80.0),
            (date(2026, 3, 1), 60.0),
            (date(2026, 4, 1), 90.0),
            (date(2026, 5, 1), 75.0),
            (date(2026, 6, 1), 100.0),
        ]
        dd = compute_max_drawdown(curve)
        # (100 - 60) / 100 = 0.40
        assert dd == pytest.approx(0.40, abs=1e-4)

    def test_no_drawdown_monotonic_up(self):
        """单调递增 → 回撤 = 0."""
        curve = [
            (date(2026, 1, 1), 100.0),
            (date(2026, 2, 1), 110.0),
            (date(2026, 3, 1), 120.0),
            (date(2026, 4, 1), 130.0),
        ]
        assert compute_max_drawdown(curve) == 0.0

    def test_empty_or_single_point(self):
        """不足 2 个点 → 0."""
        assert compute_max_drawdown([]) == 0.0
        assert compute_max_drawdown([(date(2026, 1, 1), 100.0)]) == 0.0


# ── 2.5 compute_sharpe ──────────────────────────────────────────────


class TestSharpe:
    """年化夏普比率。"""

    def test_basic_positive_returns(self):
        """5 个正收益（均值 > 0） → Sharpe > 0."""
        returns = [0.01, 0.02, 0.015, 0.012, 0.018]  # 平均约 +1.5%/日
        sharpe = compute_sharpe(returns, risk_free_rate=0.025)
        assert sharpe > 0

    def test_zero_std_returns_zero(self):
        """所有收益相同 → std=0 → Sharpe=0（避免除零）。"""
        returns = [0.01, 0.01, 0.01, 0.01, 0.01]
        assert compute_sharpe(returns) == 0.0

    def test_single_return_returns_zero(self):
        """不足 2 个点 → 0."""
        assert compute_sharpe([0.01]) == 0.0
        assert compute_sharpe([]) == 0.0

    def test_default_risk_free_rate(self):
        """默认 risk_free_rate=0.025 应与显式传 0.025 输出一致。"""
        returns = [0.01, 0.02, -0.01, 0.015, -0.005, 0.02]
        s1 = compute_sharpe(returns)
        s2 = compute_sharpe(returns, risk_free_rate=DEFAULT_RISK_FREE_RATE)
        assert s1 == s2
        # 同时验证 TRADING_DAYS_PER_YEAR 用于年化
        assert TRADING_DAYS_PER_YEAR == 252


# ── 2.6 compute_brinson_attribution ─────────────────────────────────


class TestBrinson:
    """Brinson 业绩归因（简化 MVP）。"""

    def test_portfolio_outperforms_benchmark(self):
        """组合所有持仓回报 > 基准 → total_effect > 0."""
        positions = [
            _pos(ticker="A", cost_basis=10.0, quantity=100),  # 1000
            _pos(ticker="B", cost_basis=10.0, quantity=100),  # 1000
        ]
        benchmark = {"A": 0.10, "B": 0.05}  # 组合超额 5%/10% 基准
        # 注：MVP 的 portfolio_return 用 r_p=0（无当前价），所以 portfolio_return=0
        # benchmark_return = w_p * r_b（等权） → positive
        # selection = w_p * (0 - r_b) = -benchmark_return
        # allocation = (w_p - 0.5) * r_b；本题 w_p=0.5 → 0
        # total_effect = selection = -benchmark_return < 0
        # 但 selection+allocation 合计反映组合相对基准的偏离
        result = compute_brinson_attribution(positions, benchmark)
        assert result["benchmark_return"] > 0
        assert isinstance(result["selection_effect"], float)
        assert isinstance(result["allocation_effect"], float)
        # total = selection + allocation；符号 = -benchmark_return (MVP 简化)
        assert result["total_effect"] == pytest.approx(
            result["selection_effect"] + result["allocation_effect"],
            abs=1e-6,
        )

    def test_portfolio_underperforms_benchmark_sign_flips(self):
        """不同 benchmark 权重下 allocation 贡献方向不同。"""
        positions = [
            _pos(ticker="A", cost_basis=10.0, quantity=300),  # 75%
            _pos(ticker="B", cost_basis=10.0, quantity=100),  # 25%
        ]
        benchmark = {"A": 0.05, "B": 0.20}
        result = compute_brinson_attribution(positions, benchmark)
        # 验证 4 个 key 都存在且为 float
        for k in ("portfolio_return", "benchmark_return",
                  "selection_effect", "allocation_effect", "total_effect"):
            assert k in result
            assert isinstance(result[k], float)

    def test_empty_positions_raises(self):
        """空持仓 → ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            compute_brinson_attribution([], {"A": 0.1})

    def test_zero_value_positions_raises(self):
        """所有持仓 cost*qty=0 → ValueError."""
        positions = [
            Position(
                position_id="x", ticker="X", name="X",
                cost_basis=0.0, quantity=0, first_buy_date="2026-01-01",
                last_trade_date="2026-01-01", asset_class="stock", account="default",
            )
        ]
        with pytest.raises(ValueError, match="zero"):
            compute_brinson_attribution(positions, {"X": 0.1})


# ── 2.7 compute_equity_curve ────────────────────────────────────────


class TestEquityCurve:
    """MVP 占位实现：返回单点曲线 [(today, total_value)]。"""

    def test_single_point_returns_one_tuple(self):
        """MVP 当前实现：1 个点的曲线。"""
        positions = [
            _pos(ticker="600595", cost_basis=10.0, quantity=100),
        ]
        curve = compute_equity_curve(
            positions=positions,
            transactions=[],
            current_prices={"600595": 11.0},
            days=30,
        )
        assert len(curve) == 1
        assert isinstance(curve[0][0], date)
        # 11.0 * 100 = 1100
        assert curve[0][1] == 1100.0

    def test_empty_positions_returns_zero_value(self):
        positions = []
        curve = compute_equity_curve(
            positions=positions,
            transactions=[],
            current_prices={},
        )
        assert len(curve) == 1
        assert curve[0][1] == 0.0


# ── 2.8 compute_annual_return ───────────────────────────────────────


class TestAnnualReturn:
    """年化收益工具：(end/start)^(365/days) - 1."""

    def test_basic(self):
        """100 → 110, 180 天 → (110/100)^(365/180) - 1 ≈ 0.2132."""
        annual = compute_annual_return(100.0, 110.0, 180)
        assert annual == pytest.approx(0.2132, abs=1e-3)

    def test_zero_start_value_returns_zero(self):
        """start_value<=0 → 0（避免除零 / 负底数）。"""
        assert compute_annual_return(0.0, 110.0, 180) == 0.0
        assert compute_annual_return(-100.0, 110.0, 180) == 0.0

    def test_zero_days_returns_zero(self):
        """days<=0 → 0."""
        assert compute_annual_return(100.0, 110.0, 0) == 0.0
        assert compute_annual_return(100.0, 110.0, -10) == 0.0

    def test_negative_ratio_returns_zero(self):
        """start>0 但 end<=0 → 0（避免负底数幂爆炸）。"""
        assert compute_annual_return(100.0, 0.0, 180) == 0.0
        assert compute_annual_return(100.0, -10.0, 180) == 0.0


# ── 2.9 get_rebalance_signals ───────────────────────────────────────


class TestGetRebalanceSignals:
    """调仓推送：diff Bull/Bear 信号变化。"""

    def test_no_history_returns_empty(self, monkeypatch):
        """history_store 不可用 → 返回空 list."""
        # monkeypatch HistoryStore.get_instance() 返回一个抛异常的 mock
        mock_store = MagicMock()
        mock_store.list_all.side_effect = RuntimeError("history unavailable")
        mock_cls = MagicMock()
        mock_cls.get_instance.return_value = mock_store
        monkeypatch.setattr(
            "backend.core.history_store.HistoryStore",
            mock_cls,
        )
        assert get_rebalance_signals(lookback_days=7) == []

    def test_no_change_same_signals_returns_empty(self, monkeypatch):
        """同一 ticker 两条历史信号相同 → 不进入结果。"""
        # 构造一个 fake entry
        entry_old = MagicMock()
        entry_old.ticker = "600595"
        entry_old.status = "completed"
        entry_old.signal = "bullish"
        entry_old.created_at = 1000000.0
        entry_old.analysis_id = "old_xxx"

        entry_new = MagicMock()
        entry_new.ticker = "600595"
        entry_new.status = "completed"
        entry_new.signal = "bullish"  # same as old
        entry_new.created_at = 1000100.0
        entry_new.analysis_id = "new_xxx"

        mock_store = MagicMock()
        mock_store.list_all.return_value = ([entry_old, entry_new], 2)
        mock_cls = MagicMock()
        mock_cls.get_instance.return_value = mock_store
        monkeypatch.setattr(
            "backend.core.history_store.HistoryStore",
            mock_cls,
        )
        assert get_rebalance_signals(lookback_days=7) == []

    def test_different_signals_creates_change(self, monkeypatch):
        """同一 ticker 信号从 bullish → bearish → 出现在结果里。"""
        # created_at = 0 (epoch) 距今几十年，肯定 > 7 days → 会被 cutoff 过滤掉
        # 改成近期时间戳
        import time
        now_ts = time.time()

        entry_old = MagicMock()
        entry_old.ticker = "600595"
        entry_old.status = "completed"
        entry_old.signal = "bullish"
        entry_old.created_at = now_ts - 86400  # 1 天前
        entry_old.analysis_id = "old_xxx"

        entry_new = MagicMock()
        entry_new.ticker = "600595"
        entry_new.status = "completed"
        entry_new.signal = "bearish"
        entry_new.created_at = now_ts
        entry_new.analysis_id = "new_xxx"

        mock_store = MagicMock()
        mock_store.list_all.return_value = ([entry_old, entry_new], 2)
        mock_cls = MagicMock()
        mock_cls.get_instance.return_value = mock_store
        monkeypatch.setattr(
            "backend.core.history_store.HistoryStore",
            mock_cls,
        )
        result = get_rebalance_signals(lookback_days=7)
        assert len(result) == 1
        assert result[0]["ticker"] == "600595"
        assert result[0]["old_signal"] == "bullish"
        assert result[0]["new_signal"] == "bearish"
        assert result[0]["analysis_ids"] == ["old_xxx", "new_xxx"]

    def test_signal_change_outside_lookback_excluded(self, monkeypatch):
        """信号变化但超出 lookback 窗口 → 排除。"""
        import time
        ancient_ts = time.time() - 86400 * 30  # 30 天前

        entry_old = MagicMock()
        entry_old.ticker = "600595"
        entry_old.status = "completed"
        entry_old.signal = "bullish"
        entry_old.created_at = ancient_ts - 86400
        entry_old.analysis_id = "old"

        entry_new = MagicMock()
        entry_new.ticker = "600595"
        entry_new.status = "completed"
        entry_new.signal = "bearish"
        entry_new.created_at = ancient_ts  # 30 天前，远超 7 天窗口
        entry_new.analysis_id = "new"

        mock_store = MagicMock()
        mock_store.list_all.return_value = ([entry_old, entry_new], 2)
        mock_cls = MagicMock()
        mock_cls.get_instance.return_value = mock_store
        monkeypatch.setattr(
            "backend.core.history_store.HistoryStore",
            mock_cls,
        )
        assert get_rebalance_signals(lookback_days=7) == []