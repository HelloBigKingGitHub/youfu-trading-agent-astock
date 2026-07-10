"""Tests for ``web.components.chart_panel._get_realtime_quote`` (v0.4.0 fix).

v0.4.0 早期: 走 push2his ``trends2/sse`` (与浏览器 SSE 实时推送共用域).
问题: 该端点是 SSE 长连接, Python ``requests.get`` 不带
``Accept: text/event-stream`` 头时, 服务端先保持连接等事件再超时断开 →
``RemoteDisconnected('Remote end closed connection without response')``.

修复: 改走腾讯 ``qt.gtimg.cn`` (普通 HTTP 短连接, 字段更全). ``_tencent_quote``
被 mock, 测试无需联网.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


# _tencent_quote 返回结构 (a_stock.py:174)
_QUOTE_RESPONSE = {
    "600595": {
        "name": "中孚实业",
        "price": 5.94,
        "last_close": 5.75,
        "open": 5.80,
        "change_pct": 3.30,
        "high": 5.95,
        "low": 5.74,
    },
}


@pytest.fixture
def mock_tencent_quote():
    with patch(
        "tradingagents.dataflows.a_stock._tencent_quote",
        return_value=_QUOTE_RESPONSE,
    ) as m:
        yield m


# ── 4 tests ─────────────────────────────────────────────────────────


def test_quote_returns_dict_with_required_fields(mock_tencent_quote):
    from web.components.chart_panel import _get_realtime_quote

    r = _get_realtime_quote("600595")
    assert set(r.keys()) >= {"ticker", "price", "change_pct", "change_amount", "timestamp"}
    assert r["ticker"] == "600595"
    assert isinstance(r["price"], float)
    assert isinstance(r["change_pct"], (int, float))


def test_quote_calculates_change_pct_correctly(mock_tencent_quote):
    """change = (price − last_close) / last_close × 100.

    price=5.94, last_close=5.75 → amount=+0.19, pct ≈ +3.30.
    """
    from web.components.chart_panel import _get_realtime_quote

    r = _get_realtime_quote("600595")
    assert r["price"] == pytest.approx(5.94)
    assert r["change_amount"] == pytest.approx(0.19)
    assert r["change_pct"] == pytest.approx(round(0.19 / 5.75 * 100, 2))


def test_quote_calls_tencent_with_ticker(mock_tencent_quote):
    """_tencent_quote must be called with the user-supplied ticker."""
    from web.components.chart_panel import _get_realtime_quote

    _get_realtime_quote("600595")
    assert mock_tencent_quote.call_args.args[0] == ["600595"]


def test_quote_raises_when_tencent_returns_empty():
    """Empty/invalid response → ValueError (banner shows '拉取失败' warning)."""
    with patch(
        "tradingagents.dataflows.a_stock._tencent_quote",
        return_value={},
    ):
        from web.components.chart_panel import _get_realtime_quote

        with pytest.raises(ValueError, match="empty quote"):
            _get_realtime_quote("600595")


def test_quote_raises_when_price_is_zero():
    """price=0 (停牌) → ValueError."""
    with patch(
        "tradingagents.dataflows.a_stock._tencent_quote",
        return_value={"600595": {"price": 0, "last_close": 0, "change_pct": 0}},
    ):
        from web.components.chart_panel import _get_realtime_quote

        with pytest.raises(ValueError, match="empty quote"):
            _get_realtime_quote("600595")
