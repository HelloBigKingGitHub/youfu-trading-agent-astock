"""Tests for ``web.components.chart_panel._get_realtime_quote`` (v0.4.0 fix).

Original code hit ``push2.eastmoney.com`` which FlClash blocks. Fix routes
quote through ``push2his.eastmoney.com`` ``trends2/sse`` — same endpoint as
the browser SSE. ``_em_get`` is mocked so tests run without network access.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# trends2/sse 1-day response: preClose + 2 trend rows.
# Format: "datetime,open,close,high,low,volume,amount,avg"
_RESPONSE = {
    "data": {
        "preClose": 5.75,
        "trends": [
            "2026-07-03 09:30,5.75,5.80,5.82,5.74,5000,2880000.0,5.78",
            "2026-07-03 14:55,5.94,5.94,5.95,5.94,3922,2316678.00,5.922",
        ],
    }
}


@pytest.fixture
def mock_em_get():
    with patch("tradingagents.dataflows.a_stock._em_get") as m:
        m.return_value = MagicMock(json=MagicMock(return_value=_RESPONSE))
        yield m


# ── 5 tests ─────────────────────────────────────────────────────────


def test_quote_returns_dict_with_required_fields(mock_em_get):
    from web.components.chart_panel import _get_realtime_quote
    r = _get_realtime_quote("600595")
    assert set(r.keys()) >= {"ticker", "price", "change_pct", "change_amount", "timestamp"}
    assert r["ticker"] == "600595"
    assert isinstance(r["price"], float)
    assert isinstance(r["change_pct"], (int, float))


def test_quote_calculates_change_pct_correctly(mock_em_get):
    """change = (last_close − preClose) / preClose × 100."""
    from web.components.chart_panel import _get_realtime_quote
    r = _get_realtime_quote("600595")
    # last close = 5.94, preClose = 5.75 → amount = +0.19, pct ≈ +3.30
    assert r["price"] == pytest.approx(5.94)
    assert r["change_amount"] == pytest.approx(0.19)
    assert r["change_pct"] == pytest.approx(round(0.19 / 5.75 * 100, 2))


def test_quote_handles_trends2_sse_response(mock_em_get):
    """Verifies URL is push2his (not push2) + secid parsing."""
    from web.components.chart_panel import _get_realtime_quote
    _get_realtime_quote("600595")

    called_url = mock_em_get.call_args.args[0]
    assert called_url == "https://push2his.eastmoney.com/api/qt/stock/trends2/sse"
    assert mock_em_get.call_args.kwargs["params"]["secid"] == "1.600595"


def test_quote_handles_shanghai_vs_shenzhen_secid(mock_em_get):
    """secid prefix: 1. for 6xxxxx (沪市), 0. for 0xxxxx/3xxxxx (深市)."""
    from web.components.chart_panel import _get_realtime_quote

    _get_realtime_quote("600595")
    assert mock_em_get.call_args.kwargs["params"]["secid"] == "1.600595"

    _get_realtime_quote("000001")
    assert mock_em_get.call_args.kwargs["params"]["secid"] == "0.000001"

    _get_realtime_quote("300750")
    assert mock_em_get.call_args.kwargs["params"]["secid"] == "0.300750"


def test_quote_falls_back_to_first_line_if_preclose_missing():
    """If preClose=0, fallback uses first row's open as pre_close."""
    payload = {
        "data": {
            "preClose": 0,  # missing
            "trends": [
                "2026-07-03 09:30,7.50,7.52,7.53,7.49,1000,7520.0,7.51",
                "2026-07-03 14:55,7.55,7.60,7.62,7.54,2000,15200.0,7.58",
            ],
        }
    }
    with patch("tradingagents.dataflows.a_stock._em_get") as m:
        m.return_value = MagicMock(json=MagicMock(return_value=payload))
        from web.components.chart_panel import _get_realtime_quote
        r = _get_realtime_quote("600595")

    # last close = 7.60, fallback pre_close = first row open = 7.50
    assert r["price"] == pytest.approx(7.60)
    assert r["change_amount"] == pytest.approx(0.10)
    assert r["change_pct"] == pytest.approx(round(0.10 / 7.50 * 100, 2))