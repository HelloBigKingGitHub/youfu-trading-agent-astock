"""Tests for tradingagents.dataflows.a_stock._push2his_kline_fallback (v0.4.0).

All tests use monkeypatch + MagicMock to simulate _em_get responses, so the
test suite never makes real HTTP calls to push2his.eastmoney.com.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.dataflows.a_stock import _push2his_kline_fallback


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def sample_kline_response():
    """Sample push2his /api/qt/stock/kline/get response with 3 daily bars."""
    return {
        "rc": 0,
        "data": {
            "code": "600595",
            "name": "中孚实业",
            "klines": [
                "2026-06-30,5.80,5.85,5.92,5.78,1000000,5750000.00,2.5,5.85,1.2,1.5",
                "2026-07-01,5.85,5.90,5.95,5.82,1200000,7080000.00,2.5,5.90,1.3,1.6",
                "2026-07-02,5.90,5.95,6.00,5.88,1500000,8925000.00,2.5,5.95,1.4,1.7",
            ],
        },
    }


# ── tests (6 必需, 1:1 对应设计文档 §5 V1) ──────────────────────────


def test_push2his_kline_returns_correct_columns(sample_kline_response):
    """Mocked response with 3 bars → DataFrame with Date/Open/Close/High/Low/Volume.

    Verify column order, dtypes, parsed float/int values, and parsed Date.
    """
    mock_r = MagicMock()
    mock_r.json.return_value = sample_kline_response
    with patch("tradingagents.dataflows.a_stock._em_get", return_value=mock_r):
        df = _push2his_kline_fallback("600595")

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["Date", "Open", "Close", "High", "Low", "Volume"]
    assert len(df) == 3
    assert df.iloc[0]["Open"] == 5.80
    assert df.iloc[0]["High"] == 5.92
    assert df.iloc[0]["Low"] == 5.78
    assert df.iloc[0]["Close"] == 5.85
    assert df.iloc[0]["Volume"] == 1000000
    assert pd.api.types.is_datetime64_any_dtype(df["Date"])


def test_push2his_kline_handles_empty_response():
    """Empty klines → empty DataFrame (不抛异常)."""
    mock_r = MagicMock()
    mock_r.json.return_value = {"rc": 0, "data": {"code": "600595", "klines": []}}
    with patch("tradingagents.dataflows.a_stock._em_get", return_value=mock_r):
        df = _push2his_kline_fallback("600595")

    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_push2his_kline_datelen_calculation(sample_kline_response):
    """start+end passed → lmt = clamp(days+30, 60, 800). Malformed rows skipped."""
    mock_r = MagicMock()
    # Mix well-formed and malformed rows to verify resilience
    mock_r.json.return_value = {
        "rc": 0,
        "data": {
            "klines": [
                "2026-07-01,5.85,5.90,5.95,5.82,1200000,7080000.00,2.5,5.90,1.3,1.6",
                "malformed_row",  # skip
                "2026-07-03,5.95,6.00,6.05,5.90,1500000,8925000.00,2.5,5.95,1.4,1.7",
            ],
        },
    }
    with patch(
        "tradingagents.dataflows.a_stock._em_get", return_value=mock_r,
    ) as mock_get:
        # 100 days range → 100+30=130, fits [60, 800] → lmt=130
        df = _push2his_kline_fallback("600595", "2026-04-01", "2026-07-10")

        params = mock_get.call_args.kwargs["params"]
        assert params["lmt"] == 130
        assert params["beg"] == "20260401"
        assert params["end"] == "20260710"

        # Default klt=101 (日 K) + fqt=1 (前复权)
        assert params["klt"] == 101
        assert params["fqt"] == 1

        # Malformed row skipped; only 2 well-formed rows remain
        assert len(df) == 2


def test_push2his_kline_uses_em_get_throttle(sample_kline_response):
    """All requests must go through _em_get (东财节流); NOT naked requests.get."""
    mock_r = MagicMock()
    mock_r.json.return_value = sample_kline_response
    with patch(
        "tradingagents.dataflows.a_stock._em_get", return_value=mock_r,
    ) as mock_get:
        _push2his_kline_fallback("600595", "2026-07-01", "2026-07-10")
        # Verify URL is push2his (NOT naked requests.get)
        called_url = mock_get.call_args.args[0]
        assert "push2his.eastmoney.com" in called_url
        assert "/api/qt/stock/kline/get" in called_url
        # Timeout is at least 10s
        assert mock_get.call_args.kwargs.get("timeout", 0) >= 10


def test_push2his_kline_secid_prefix_shanghai(sample_kline_response):
    """6xxxxx (Shanghai) → secid='1.600595'."""
    mock_r = MagicMock()
    mock_r.json.return_value = sample_kline_response
    with patch(
        "tradingagents.dataflows.a_stock._em_get", return_value=mock_r,
    ) as mock_get:
        _push2his_kline_fallback("600595")
        params = mock_get.call_args.kwargs["params"]
        assert params["secid"] == "1.600595"


def test_push2his_kline_secid_prefix_shenzhen(sample_kline_response):
    """0xxxxx / 3xxxxx (Shenzhen) → secid starts with '0.'."""
    mock_r = MagicMock()
    mock_r.json.return_value = sample_kline_response
    with patch(
        "tradingagents.dataflows.a_stock._em_get", return_value=mock_r,
    ) as mock_get:
        _push2his_kline_fallback("000001")
        params = mock_get.call_args.kwargs["params"]
        assert params["secid"] == "0.000001"

        _push2his_kline_fallback("300750")
        params = mock_get.call_args.kwargs["params"]
        assert params["secid"] == "0.300750"