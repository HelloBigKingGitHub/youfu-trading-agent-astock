"""Tests for the Web UI layer of the portfolio module (Phase 2).

Streamlit API calls are mocked with ``unittest.mock.patch`` so the tests
run without a live Streamlit context. The portfolio store is redirected
to ``tmp_path`` via ``monkeypatch.setattr`` so tests never touch the
real ``~/.tradingagents/portfolio/`` directory.

Coverage matrix (25+ tests):
  - portfolio_dialogs:  validators + format helpers
  - portfolio_overview: holding_days, compute_metric_row, safe_quote
  - portfolio_transactions: filter_transactions, transaction_amount
  - portfolio_allocation: group_by_asset_class, concentration_topn
  - portfolio_alerts_view: alert_status_label
  - portfolio_import_view: list_audit_lines, preview_summary_counts
  - portfolio_risk: total_return_pct
  - portfolio_panel: get_rebalance_signals
"""

from __future__ import annotations

import os
from datetime import date as _date
from pathlib import Path
from unittest.mock import patch

import pytest


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_portfolio(tmp_path, monkeypatch):
    """Redirect PORTFOLIO_DIR + reset singleton (matches test_portfolio_store)."""
    monkeypatch.setattr("backend.core.portfolio_store.PORTFOLIO_DIR", tmp_path)
    monkeypatch.setattr("backend.core.portfolio_store.PortfolioStore._instance", None)
    return tmp_path


@pytest.fixture
def store(tmp_portfolio):
    from backend.core.portfolio_store import PortfolioStore
    return PortfolioStore()


def _add_basic_position(store, ticker="600595", name="贵州茅台",
                         cost=10.0, qty=100, date="2026-01-01"):
    return store.add_position(
        ticker=ticker, name=name, cost_basis=cost,
        quantity=qty, first_buy_date=date,
    )


# ── portfolio_dialogs: validators ───────────────────────────────────────


class TestValidateTicker:
    @pytest.mark.unit
    @pytest.mark.parametrize("ticker", ["600595", "000001", "300750"])
    def test_valid_6_digit_tickers(self, ticker):
        from web.components.portfolio_dialogs import validate_ticker
        assert validate_ticker(ticker) is None

    @pytest.mark.unit
    @pytest.mark.parametrize("ticker", ["", "12345", "1234567", "abc123", "60 05 95"])
    def test_invalid_tickers(self, ticker):
        from web.components.portfolio_dialogs import validate_ticker
        assert validate_ticker(ticker) is not None


class TestValidatePositionFields:
    @pytest.mark.unit
    def test_valid_fields(self):
        from web.components.portfolio_dialogs import validate_position_fields
        assert validate_position_fields("600595", 10.0, 100) is None

    @pytest.mark.unit
    def test_invalid_ticker(self):
        from web.components.portfolio_dialogs import validate_position_fields
        assert validate_position_fields("12345", 10.0, 100) is not None

    @pytest.mark.unit
    def test_zero_cost_rejected(self):
        from web.components.portfolio_dialogs import validate_position_fields
        assert validate_position_fields("600595", 0.0, 100) is not None

    @pytest.mark.unit
    def test_negative_cost_rejected(self):
        from web.components.portfolio_dialogs import validate_position_fields
        assert validate_position_fields("600595", -1.0, 100) is not None

    @pytest.mark.unit
    def test_zero_quantity_rejected(self):
        from web.components.portfolio_dialogs import validate_position_fields
        assert validate_position_fields("600595", 10.0, 0) is not None

    @pytest.mark.unit
    def test_invalid_asset_class_rejected(self):
        from web.components.portfolio_dialogs import validate_position_fields
        assert validate_position_fields("600595", 10.0, 100, asset_class="crypto") is not None


class TestValidateTransactionFields:
    @pytest.mark.unit
    def test_valid_buy(self):
        from web.components.portfolio_dialogs import validate_transaction_fields
        assert validate_transaction_fields(10.0, 100, "buy") is None

    @pytest.mark.unit
    def test_valid_sell_within_holdings(self):
        from web.components.portfolio_dialogs import validate_transaction_fields
        assert validate_transaction_fields(10.0, 50, "sell", held_quantity=100) is None

    @pytest.mark.unit
    def test_sell_exceeding_holdings_rejected(self):
        from web.components.portfolio_dialogs import validate_transaction_fields
        assert validate_transaction_fields(10.0, 200, "sell", held_quantity=100) is not None

    @pytest.mark.unit
    def test_zero_price_rejected(self):
        from web.components.portfolio_dialogs import validate_transaction_fields
        assert validate_transaction_fields(0.0, 100, "buy") is not None

    @pytest.mark.unit
    def test_zero_quantity_rejected(self):
        from web.components.portfolio_dialogs import validate_transaction_fields
        assert validate_transaction_fields(10.0, 0, "buy") is not None

    @pytest.mark.unit
    def test_invalid_action_rejected(self):
        from web.components.portfolio_dialogs import validate_transaction_fields
        assert validate_transaction_fields(10.0, 100, "wash") is not None


class TestValidateAlertFields:
    @pytest.mark.unit
    def test_valid_price_above(self):
        from web.components.portfolio_dialogs import validate_alert_fields
        assert validate_alert_fields("600595", "price_above", 7.0) is None

    @pytest.mark.unit
    def test_invalid_rule_type(self):
        from web.components.portfolio_dialogs import validate_alert_fields
        assert validate_alert_fields("600595", "unknown", 5.0) is not None

    @pytest.mark.unit
    def test_invalid_ticker(self):
        from web.components.portfolio_dialogs import validate_alert_fields
        assert validate_alert_fields("abc", "price_above", 5.0) is not None

    @pytest.mark.unit
    def test_trailing_stop_zero_threshold_rejected(self):
        from web.components.portfolio_dialogs import validate_alert_fields
        assert validate_alert_fields("600595", "trailing_stop", 0.0) is not None

    @pytest.mark.unit
    def test_all_seven_rule_types_accepted(self):
        from backend.core.portfolio_store import VALID_ALERT_RULE_TYPES
        from web.components.portfolio_dialogs import validate_alert_fields
        for rt in VALID_ALERT_RULE_TYPES:
            assert validate_alert_fields("600595", rt, 1.0) is None, rt


# ── portfolio_dialogs: format helpers ──────────────────────────────────


class TestParsePct:
    @pytest.mark.unit
    @pytest.mark.parametrize("raw,expected", [
        ("+10.01%", 10.01),
        ("-3.5%", -3.5),
        ("2.5", 2.5),
        ("0%", 0.0),
        (None, 0.0),
        ("", 0.0),
        ("abc", 0.0),
        (5.0, 5.0),
    ])
    def test_parse_pct_variants(self, raw, expected):
        from web.components.portfolio_dialogs import parse_pct
        assert parse_pct(raw) == pytest.approx(expected)


class TestFormatHelpers:
    @pytest.mark.unit
    def test_format_pct_signed_positive(self):
        from web.components.portfolio_dialogs import format_pct
        assert format_pct(1.23) == "+1.23%"

    @pytest.mark.unit
    def test_format_pct_signed_negative(self):
        from web.components.portfolio_dialogs import format_pct
        assert format_pct(-0.45) == "-0.45%"

    @pytest.mark.unit
    def test_format_pct_unsigned(self):
        from web.components.portfolio_dialogs import format_pct
        assert format_pct(1.23, signed=False) == "1.23%"

    @pytest.mark.unit
    def test_format_pct_handles_none(self):
        from web.components.portfolio_dialogs import format_pct
        assert format_pct(None) == "+0.00%"

    @pytest.mark.unit
    def test_format_currency_positive(self):
        from web.components.portfolio_dialogs import format_currency
        assert format_currency(1234.5) == "¥1,234.50"

    @pytest.mark.unit
    def test_format_currency_negative(self):
        from web.components.portfolio_dialogs import format_currency
        assert format_currency(-123.45) == "-¥123.45"

    @pytest.mark.unit
    def test_format_currency_handles_none(self):
        from web.components.portfolio_dialogs import format_currency
        assert format_currency(None) == "¥0.00"

    @pytest.mark.unit
    @pytest.mark.parametrize("value,expected", [
        (1.0, "bb-portfolio-pnl-up"),
        (-1.0, "bb-portfolio-pnl-down"),
        (0.0, "bb-portfolio-pnl-neutral"),
    ])
    def test_pnl_color_class(self, value, expected):
        from web.components.portfolio_dialogs import pnl_color_class
        assert pnl_color_class(value) == expected


class TestLabelDicts:
    @pytest.mark.unit
    def test_alert_rule_labels_seven_entries(self):
        from backend.core.portfolio_store import VALID_ALERT_RULE_TYPES
        from web.components.portfolio_dialogs import ALERT_RULE_LABELS
        assert set(ALERT_RULE_LABELS.keys()) == set(VALID_ALERT_RULE_TYPES)

    @pytest.mark.unit
    def test_asset_class_labels_five_entries(self):
        from backend.core.portfolio_store import VALID_ASSET_CLASSES
        from web.components.portfolio_dialogs import ASSET_CLASS_LABELS
        assert set(ASSET_CLASS_LABELS.keys()) == set(VALID_ASSET_CLASSES)
        # v0.5.0: stock/bond/overseas/cash/fund (5 个)
        assert len(VALID_ASSET_CLASSES) == 5

    @pytest.mark.unit
    def test_tx_action_labels_six_entries(self):
        from backend.core.portfolio_store import VALID_TRANSACTION_ACTIONS
        from web.components.portfolio_dialogs import TX_ACTION_LABELS
        assert set(TX_ACTION_LABELS.keys()) == set(VALID_TRANSACTION_ACTIONS)


# ── portfolio_overview ─────────────────────────────────────────────────


class TestHoldingDays:
    @pytest.mark.unit
    def test_basic(self):
        from web.components.portfolio_overview import holding_days
        assert holding_days("2026-01-01", today="2026-07-01") == 181

    @pytest.mark.unit
    def test_zero_when_future_date(self):
        from web.components.portfolio_overview import holding_days
        # Negative deltas should clamp to 0.
        assert holding_days("2099-01-01", today="2026-01-01") == 0

    @pytest.mark.unit
    def test_invalid_date_returns_zero(self):
        from web.components.portfolio_overview import holding_days
        assert holding_days("not-a-date", today="2026-07-01") == 0


class TestComputeMetricRow:
    @pytest.mark.unit
    def test_empty_positions(self):
        from web.components.portfolio_overview import compute_metric_row
        m = compute_metric_row([], {})
        assert m["total_value"] == 0
        assert m["total_cost"] == 0
        assert m["positions_count"] == 0
        assert m["total_pnl_abs"] == 0

    @pytest.mark.unit
    def test_basic_two_positions(self, store):
        from web.components.portfolio_overview import compute_metric_row
        _add_basic_position(store, ticker="600595", cost=10.0, qty=100)
        _add_basic_position(store, ticker="000001", cost=20.0, qty=50)
        positions = store.list_positions()
        # No current prices → fall back to cost_basis
        m = compute_metric_row(positions, {})
        assert m["total_cost"] == 10.0 * 100 + 20.0 * 50  # 2000
        assert m["total_value"] == 2000.0  # same as cost
        assert m["total_pnl_abs"] == 0.0
        assert m["positions_count"] == 2

    @pytest.mark.unit
    def test_with_current_prices(self, store):
        from web.components.portfolio_overview import compute_metric_row
        _add_basic_position(store, ticker="600595", cost=10.0, qty=100)
        positions = store.list_positions()
        m = compute_metric_row(positions, {"600595": 12.0})
        assert m["total_value"] == 1200.0
        assert m["total_pnl_abs"] == 200.0
        assert m["total_pnl_pct"] == pytest.approx(0.2, abs=1e-4)


class TestSafeQuote:
    @pytest.mark.unit
    def test_returns_none_when_import_fails(self):
        from web.components.portfolio_overview import safe_quote
        with patch(
            "tradingagents.dataflows.a_stock._tencent_quote",
            side_effect=RuntimeError("network down"),
        ):
            assert safe_quote("600595") is None

    @pytest.mark.unit
    def test_returns_price_on_success(self):
        from web.components.portfolio_overview import safe_quote
        with patch(
            "tradingagents.dataflows.a_stock._tencent_quote",
            return_value={"600595": {"price": 12.34, "last_close": 12.0}},
        ):
            assert safe_quote("600595") == 12.34

    @pytest.mark.unit
    def test_returns_none_on_empty_quote(self):
        from web.components.portfolio_overview import safe_quote
        with patch(
            "tradingagents.dataflows.a_stock._tencent_quote",
            return_value={},
        ):
            assert safe_quote("600595") is None


# ── portfolio_transactions ─────────────────────────────────────────────


class TestFilterTransactions:
    @pytest.mark.unit
    def test_no_filter(self, store):
        from backend.core.portfolio_store import Transaction
        from web.components.portfolio_transactions import filter_transactions
        p1 = _add_basic_position(store, ticker="600595")
        p2 = _add_basic_position(store, ticker="000001")
        store.add_transaction(p1.position_id, "2026-01-15", "buy", 10.0, 100)
        store.add_transaction(p2.position_id, "2026-02-20", "buy", 20.0, 50)
        store.add_transaction(p1.position_id, "2026-03-10", "sell", 12.0, 50)
        txs = store.list_transactions()
        result = filter_transactions(txs)
        assert len(result) == 3
        # Default sort: most recent first
        assert result[0].date == "2026-03-10"

    @pytest.mark.unit
    def test_filter_by_ticker(self, store):
        from web.components.portfolio_transactions import filter_transactions
        p1 = _add_basic_position(store, ticker="600595")
        p2 = _add_basic_position(store, ticker="000001")
        store.add_transaction(p1.position_id, "2026-01-15", "buy", 10.0, 100)
        store.add_transaction(p2.position_id, "2026-02-20", "buy", 20.0, 50)
        txs = store.list_transactions()
        result = filter_transactions(txs, ticker="600595")
        assert len(result) == 1
        assert result[0].ticker == "600595"

    @pytest.mark.unit
    def test_filter_by_since(self, store):
        from web.components.portfolio_transactions import filter_transactions
        p1 = _add_basic_position(store)
        store.add_transaction(p1.position_id, "2026-01-15", "buy", 10.0, 100)
        store.add_transaction(p1.position_id, "2026-04-15", "buy", 12.0, 50)
        txs = store.list_transactions()
        result = filter_transactions(txs, since="2026-03-01")
        assert len(result) == 1
        assert result[0].date == "2026-04-15"


class TestTransactionAmount:
    @pytest.mark.unit
    def test_buy_is_negative(self):
        from backend.core.portfolio_store import Transaction
        from web.components.portfolio_transactions import transaction_amount
        tx = Transaction(
            tx_id="t1", position_id="p1", ticker="600595",
            date="2026-01-01", action="buy", price=10.0, quantity=100, fees=5.0,
        )
        assert transaction_amount(tx) == -(10.0 * 100 + 5.0)

    @pytest.mark.unit
    def test_sell_is_positive(self):
        from backend.core.portfolio_store import Transaction
        from web.components.portfolio_transactions import transaction_amount
        tx = Transaction(
            tx_id="t1", position_id="p1", ticker="600595",
            date="2026-01-01", action="sell", price=12.0, quantity=50, fees=5.0,
        )
        assert transaction_amount(tx) == 12.0 * 50 - 5.0

    @pytest.mark.unit
    def test_dividend_is_positive(self):
        from backend.core.portfolio_store import Transaction
        from web.components.portfolio_transactions import transaction_amount
        tx = Transaction(
            tx_id="t1", position_id="p1", ticker="600595",
            date="2026-01-01", action="dividend", price=0.5, quantity=100,
        )
        assert transaction_amount(tx) == 50.0

    @pytest.mark.unit
    def test_split_is_zero(self):
        from backend.core.portfolio_store import Transaction
        from web.components.portfolio_transactions import transaction_amount
        tx = Transaction(
            tx_id="t1", position_id="p1", ticker="600595",
            date="2026-01-01", action="split", price=0.0, quantity=100,
        )
        assert transaction_amount(tx) == 0.0


# ── portfolio_allocation ──────────────────────────────────────────────


class TestGroupByAssetClass:
    @pytest.mark.unit
    def test_empty(self):
        from web.components.portfolio_allocation import group_by_asset_class
        assert group_by_asset_class([], {}) == {}

    @pytest.mark.unit
    def test_basic(self, store):
        from web.components.portfolio_allocation import group_by_asset_class
        p1 = _add_basic_position(store, ticker="600595", cost=10.0, qty=100)
        # Override asset_class for diversification
        store.update_position(p1.position_id, asset_class="bond")
        _add_basic_position(store, ticker="000001", cost=20.0, qty=50)
        positions = store.list_positions()
        result = group_by_asset_class(positions, {})
        assert "bond" in result
        assert "stock" in result
        assert result["bond"] == 10.0 * 100


class TestConcentration:
    @pytest.mark.unit
    def test_topn_ordered_by_value(self, store):
        from web.components.portfolio_allocation import concentration_topn
        _add_basic_position(store, ticker="600595", cost=10.0, qty=100)  # 1000
        _add_basic_position(store, ticker="000001", cost=20.0, qty=200)  # 4000
        _add_basic_position(store, ticker="300750", cost=5.0, qty=50)   # 250
        positions = store.list_positions()
        top = concentration_topn(positions, {}, n=5)
        assert len(top) == 3
        # 000001 is largest (4000)
        assert top[0][0] == "000001"
        # weights sum to 1.0
        assert sum(w for _, _, w in top) == pytest.approx(1.0, abs=1e-4)

    @pytest.mark.unit
    def test_max_single_holding(self, store):
        from web.components.portfolio_allocation import max_single_holding_pct
        _add_basic_position(store, ticker="600595", cost=10.0, qty=100)
        _add_basic_position(store, ticker="000001", cost=20.0, qty=200)
        positions = store.list_positions()
        # 4000 / 5000 = 0.8
        assert max_single_holding_pct(positions, {}) == pytest.approx(0.8, abs=1e-4)

    @pytest.mark.unit
    def test_empty_returns_empty(self):
        from web.components.portfolio_allocation import (
            concentration_topn, max_single_holding_pct,
        )
        assert concentration_topn([], {}, n=5) == []
        assert max_single_holding_pct([], {}) == 0.0


# ── portfolio_alerts_view ─────────────────────────────────────────────


class TestAlertStatusLabel:
    @pytest.mark.unit
    def test_untriggered(self):
        from backend.core.portfolio_store import AlertRule
        from web.components.portfolio_alerts_view import alert_status_label
        rule = AlertRule(rule_id="r1", ticker="600595", rule_type="price_above", threshold=10.0)
        assert alert_status_label(rule) == "(未触发)"

    @pytest.mark.unit
    def test_triggered_format(self):
        from backend.core.portfolio_store import AlertRule
        from web.components.portfolio_alerts_view import alert_status_label
        rule = AlertRule(
            rule_id="r1", ticker="600595", rule_type="price_above",
            threshold=10.0, last_triggered_at=1747353600.0,
        )
        # Should be a non-empty timestamp string
        assert alert_status_label(rule) != "(未触发)"
        assert "20" in alert_status_label(rule)


# ── portfolio_import_view ─────────────────────────────────────────────


class TestListAuditLines:
    @pytest.mark.unit
    def test_missing_file_returns_empty(self, tmp_path):
        from web.components.portfolio_import_view import list_audit_lines
        assert list_audit_lines(tmp_path / "audit.log") == []

    @pytest.mark.unit
    def test_reads_last_n(self, tmp_path):
        from web.components.portfolio_import_view import list_audit_lines
        f = tmp_path / "audit.log"
        f.write_text("\n".join(f"line {i}" for i in range(10)) + "\n", encoding="utf-8")
        result = list_audit_lines(f, limit=3)
        assert len(result) == 3
        assert result[-1] == "line 9"

    @pytest.mark.unit
    def test_handles_empty_file(self, tmp_path):
        from web.components.portfolio_import_view import list_audit_lines
        f = tmp_path / "audit.log"
        f.write_text("", encoding="utf-8")
        assert list_audit_lines(f) == []


class TestPreviewSummaryCounts:
    @pytest.mark.unit
    def test_basic(self):
        from web.components.portfolio_import_view import preview_summary_counts
        result = preview_summary_counts(
            {"new": [1, 2, 3], "conflicts": [1, 2], "invalid": [1]}
        )
        assert result == {"new": 3, "conflicts": 2, "invalid": 1}

    @pytest.mark.unit
    def test_empty(self):
        from web.components.portfolio_import_view import preview_summary_counts
        assert preview_summary_counts({}) == {"new": 0, "conflicts": 0, "invalid": 0}


# ── portfolio_risk ────────────────────────────────────────────────────


class TestTotalReturnPct:
    @pytest.mark.unit
    def test_no_positions(self):
        from web.components.portfolio_risk import total_return_pct
        assert total_return_pct([], {}) == 0.0

    @pytest.mark.unit
    def test_positive_return(self, store):
        from web.components.portfolio_risk import total_return_pct
        _add_basic_position(store, cost=10.0, qty=100)
        positions = store.list_positions()
        # Current price 12 → gain 200 / cost 1000 = 0.2
        assert total_return_pct(positions, {"600595": 12.0}) == pytest.approx(0.2)

    @pytest.mark.unit
    def test_negative_return(self, store):
        from web.components.portfolio_risk import total_return_pct
        _add_basic_position(store, cost=10.0, qty=100)
        positions = store.list_positions()
        # Current price 8 → loss 200 / cost 1000 = -0.2
        assert total_return_pct(positions, {"600595": 8.0}) == pytest.approx(-0.2)


# ── portfolio_panel ──────────────────────────────────────────────────


class TestGetRebalanceSignals:
    @pytest.mark.unit
    def test_returns_empty_by_default(self, store):
        from web.components.portfolio_panel import get_rebalance_signals
        _add_basic_position(store)
        positions = store.list_positions()
        # MVP stub: empty list.
        assert get_rebalance_signals(positions, lookback_days=7) == []

    @pytest.mark.unit
    def test_empty_positions_returns_empty(self):
        from web.components.portfolio_panel import get_rebalance_signals
        assert get_rebalance_signals([], lookback_days=7) == []


# ── Spec 3.5: rebalance banner behavior ──────────────────────────────


class TestShowRebalanceBanner:
    """``_show_rebalance_banner`` reads signals and emits ``st.info`` per signal."""

    @pytest.mark.unit
    def test_no_positions_skips_silently(self):
        from web.components.portfolio_panel import _show_rebalance_banner
        with patch("streamlit.info") as mock_info:
            _show_rebalance_banner([])
            assert not mock_info.called

    @pytest.mark.unit
    def test_empty_signals_skips_silently(self, store):
        from web.components.portfolio_panel import _show_rebalance_banner
        _add_basic_position(store)
        with patch("streamlit.info") as mock_info:
            _show_rebalance_banner(store.list_positions())
            # MVP stub returns [] → no banner.
            assert not mock_info.called

    @pytest.mark.unit
    def test_signals_emit_st_info(self, store):
        from web.components.portfolio_panel import _show_rebalance_banner
        _add_basic_position(store)
        fake_signals = [
            {
                "ticker": "600595",
                "old_signal": "bullish",
                "new_signal": "bearish",
                "detected_at": "2026-06-01",
            }
        ]
        with patch(
            "web.components.portfolio_panel.get_rebalance_signals",
            return_value=fake_signals,
        ), patch("streamlit.info") as mock_info:
            _show_rebalance_banner(store.list_positions())
            assert mock_info.called
            msg = mock_info.call_args[0][0]
            assert "600595" in msg
            assert "bullish" in msg
            assert "bearish" in msg

    @pytest.mark.unit
    def test_signals_capped_at_five(self, store):
        """Banner surfaces at most 5 signals to keep the UI tidy."""
        from web.components.portfolio_panel import _show_rebalance_banner
        _add_basic_position(store)
        fake_signals = [
            {
                "ticker": "60000" + str(i),
                "old_signal": "bullish",
                "new_signal": "bearish",
                "detected_at": "2026-06-01",
            }
            for i in range(8)
        ]
        with patch(
            "web.components.portfolio_panel.get_rebalance_signals",
            return_value=fake_signals,
        ), patch("streamlit.info") as mock_info:
            _show_rebalance_banner(store.list_positions())
            # 8 signals supplied, banner renders 5.
            assert mock_info.call_count == 5


# ── Spec 3.5: fetch_current_prices fallback behavior ─────────────────


class TestFetchCurrentPrices:
    """``_fetch_current_prices`` calls ``safe_quote`` per ticker and drops None."""

    @pytest.mark.unit
    def test_empty_tickers_returns_empty_dict(self):
        from web.components.portfolio_panel import _fetch_current_prices
        assert _fetch_current_prices([]) == {}

    @pytest.mark.unit
    def test_skips_none_quotes(self):
        """If safe_quote returns None for a ticker, that ticker is excluded."""
        from web.components.portfolio_panel import _fetch_current_prices

        def fake_safe_quote(t):
            return 12.5 if t == "600595" else None

        with patch(
            "web.components.portfolio_panel.safe_quote", side_effect=fake_safe_quote,
        ):
            out = _fetch_current_prices(["600595", "000001"])
        assert out == {"600595": 12.5}
        assert "000001" not in out

    @pytest.mark.unit
    def test_all_quotes_succeed(self):
        from web.components.portfolio_panel import _fetch_current_prices

        with patch(
            "web.components.portfolio_panel.safe_quote",
            return_value=11.0,
        ):
            out = _fetch_current_prices(["600595", "000001"])
        assert out == {"600595": 11.0, "000001": 11.0}

    @pytest.mark.unit
    def test_safe_quote_exception_propagates(self):
        """``_fetch_current_prices`` does not swallow safe_quote exceptions;
        the caller (panel entry) wraps in try/except. We just confirm the
        current contract: an exception bubbles up untouched."""
        from web.components.portfolio_panel import _fetch_current_prices

        def boom(t):
            raise RuntimeError("network")

        with patch("web.components.portfolio_panel.safe_quote", side_effect=boom):
            with pytest.raises(RuntimeError, match="network"):
                _fetch_current_prices(["600595"])


# ── Spec 3.5: load_data and render_header fallbacks ─────────────────


class TestLoadDataIntegration:

    @pytest.mark.unit
    def test_loads_three_lists_from_store(self, store):
        from web.components.portfolio_panel import _load_data
        _add_basic_position(store)
        pos, txs, alerts = _load_data()
        assert len(pos) == 1
        assert txs == []
        assert alerts == []

    @pytest.mark.unit
    def test_loads_with_transactions_and_alerts(self, store):
        from web.components.portfolio_panel import _load_data
        pos = _add_basic_position(store)
        store.add_transaction(pos.position_id, "2026-02-01", "buy", 11.0, 50)
        store.add_alert("600595", "price_above", 12.0)
        positions, transactions, alerts = _load_data()
        assert len(positions) == 1
        assert len(transactions) == 1
        assert len(alerts) == 1

    @pytest.mark.unit
    def test_empty_store_returns_empty_lists(self, store):
        from web.components.portfolio_panel import _load_data
        assert _load_data() == ([], [], [])


class TestRenderHeaderFallbacks:

    @pytest.mark.unit
    def test_render_header_emits_title_and_caption(self):
        from web.components.portfolio_panel import _render_header
        with patch("streamlit.markdown") as mock_md, \
             patch("streamlit.caption") as mock_caption, \
             patch("streamlit.button", return_value=False):
            _render_header()
            assert mock_md.called
            assert mock_caption.called
            # Title should reference "我的仓位"
            title = mock_md.call_args[0][0]
            assert "我的仓位" in title

    @pytest.mark.unit
    def test_render_header_reload_button_clears_cache_and_reruns(self):
        import streamlit as st

        from web.components.portfolio_panel import _render_header
        with patch.dict(
            "streamlit.session_state",
            {"portfolio_prices_cache": {"600595": 12.0}},
            clear=False,
        ), patch("streamlit.markdown"), \
             patch("streamlit.caption"), \
             patch("streamlit.button", return_value=True), \
             patch("streamlit.rerun") as mock_rerun:
            _render_header()
            assert mock_rerun.called
            assert "portfolio_prices_cache" not in st.session_state


# ── panel entry: render smoke test ────────────────────────────────────


class TestRenderPortfolioPanel:
    """Verify the main entry doesn't crash when all 6 tab modules are mocked."""

    @pytest.mark.unit
    def test_renders_all_seven_tabs(self, store):
        from contextlib import ExitStack
        from unittest.mock import MagicMock, patch
        from web.components.portfolio_panel import render_portfolio_panel

        _add_basic_position(store)

        mock_tabs = MagicMock(return_value=[MagicMock() for _ in range(7)])
        mock_expander = MagicMock()
        mock_expander.return_value.__enter__ = MagicMock()
        mock_expander.return_value.__exit__ = MagicMock(return_value=False)

        def _columns_factory(*args, **kwargs):
            """Return exactly N MagicMock column objects, matching the call shape.

            Streamlit's ``st.columns(N)`` or ``st.columns([1, 2, 3])`` returns
            N columns. We return the exact count so positional unpacking on
            the caller side (e.g. ``c1, c2, c3, ... = st.columns([...])``)
            works.
            """
            n = 1
            if args:
                first = args[0]
                if isinstance(first, int):
                    n = first
                elif isinstance(first, (list, tuple)):
                    n = len(first)
            return tuple(MagicMock() for _ in range(n))

        def _selectbox_factory(*args, **kwargs):
            """Return the first option (or a sane default) from each selectbox call."""
            options = kwargs.get("options") or (args[1] if len(args) > 1 else None) or []
            if not options:
                return ""
            return options[0]

        streamlit_patches = [
            patch("streamlit.tabs", mock_tabs),
            patch("streamlit.markdown", MagicMock()),
            patch("streamlit.caption", MagicMock()),
            patch("streamlit.button", MagicMock(return_value=False)),
            patch("streamlit.html", MagicMock()),
            patch("streamlit.rerun", MagicMock()),
            patch("streamlit.info", MagicMock()),
            patch("streamlit.error", MagicMock()),
            patch("streamlit.warning", MagicMock()),
            patch("streamlit.success", MagicMock()),
            patch("streamlit.toast", MagicMock()),
            patch("streamlit.altair_chart", MagicMock()),
            patch("streamlit.plotly_chart", MagicMock()),
            patch("streamlit.selectbox", side_effect=_selectbox_factory),
            patch("streamlit.text_input", MagicMock(return_value="")),
            patch("streamlit.file_uploader", MagicMock(return_value=None)),
            patch("streamlit.date_input", MagicMock(return_value=None)),
            patch("streamlit.radio", MagicMock(return_value="skip")),
            patch("streamlit.expander", mock_expander),
            patch("streamlit.columns", side_effect=_columns_factory),
            patch("streamlit.toggle", MagicMock(return_value=True)),
        ]
        with ExitStack() as stack:
            for p in streamlit_patches:
                stack.enter_context(p)
            with patch.dict("streamlit.session_state", {}, clear=False):
                render_portfolio_panel()
            assert mock_tabs.called
