"""Tests for web.components.chart_panel (v0.4.0).

All Streamlit API calls are mocked via unittest.mock.patch so tests run without
a live Streamlit context. Cache directory is redirected to tmp_path via
monkeypatch so tests never touch real ``~/.tradingagents/cache/kline/``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """Redirect chart_panel._CACHE_DIR to tmp so tests don't touch real cache."""
    monkeypatch.setattr("web.components.chart_panel._CACHE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def sample_kline_df() -> pd.DataFrame:
    """30-day sample OHLCV DataFrame for MA + chart tests."""
    dates = pd.date_range("2026-06-01", periods=30, freq="D")
    prices = [5.0 + i * 0.1 + (i % 5) * 0.05 for i in range(30)]
    return pd.DataFrame({
        "Date": dates,
        "Open": prices,
        "High": [p + 0.1 for p in prices],
        "Low": [p - 0.1 for p in prices],
        "Close": [p + 0.05 for p in prices],
        "Volume": [1000000 + i * 10000 for i in range(30)],
    })


# ── helpers ─────────────────────────────────────────────────────────


def _patched_streamlit_columns():
    """Returns a (patch, mock_cols) — mock_cols.return_value = (3 MagicMock cols)."""
    mock_cols = MagicMock()
    mock_cols.return_value = (MagicMock(), MagicMock(), MagicMock())
    return patch("streamlit.columns", mock_cols), mock_cols


# ── tests (7 必需, 1:1 对应设计文档 §5 V2) ──────────────────────────


def test_render_chart_panel_empty_ticker_shows_info():
    """Empty ticker → st.info shows '请输入 6 位股票代码'."""
    cols_patch, _ = _patched_streamlit_columns()
    with cols_patch, \
         patch("streamlit.markdown"), \
         patch("streamlit.session_state", {}), \
         patch("streamlit.text_input", return_value=""), \
         patch("streamlit.selectbox", return_value="1m"), \
         patch("streamlit.button", return_value=False), \
         patch("streamlit.info") as mock_info:
        from web.components.chart_panel import render_chart_panel
        render_chart_panel()

        mock_info.assert_called_once()
        msg = mock_info.call_args[0][0]
        assert "6 位" in msg


def test_render_chart_panel_invalid_ticker_shows_info():
    """Non-6-char ticker → st.info shows '请输入 6 位股票代码'."""
    cols_patch, _ = _patched_streamlit_columns()
    with cols_patch, \
         patch("streamlit.markdown"), \
         patch("streamlit.session_state", {}), \
         patch("streamlit.text_input", return_value="12345"), \
         patch("streamlit.selectbox", return_value="1m"), \
         patch("streamlit.button", return_value=False), \
         patch("streamlit.info") as mock_info:
        from web.components.chart_panel import render_chart_panel
        render_chart_panel()

        mock_info.assert_called_once()
        assert "6 位" in mock_info.call_args[0][0]


def test_render_chart_panel_calls_get_historical_kline(tmp_cache_dir, sample_kline_df):
    """Valid ticker → _get_historical_kline is called + chart rendered via
    streamlit-lightweight-charts (PyPI wrapper)."""
    cols_patch, _ = _patched_streamlit_columns()
    with cols_patch, \
         patch("streamlit.markdown"), \
         patch("streamlit.session_state", {}), \
         patch("streamlit.text_input", return_value="600595"), \
         patch("streamlit.selectbox", return_value="1m"), \
         patch("streamlit.button", return_value=False), \
         patch("streamlit.html"), \
         patch("streamlit.warning"), \
         patch(
             "tradingagents.dataflows.a_stock._tencent_quote",
         ) as mock_tencent, \
         patch(
             "web.components.chart_panel.renderLightweightCharts",
         ) as mock_render_lwc:
        mock_tencent.return_value = {
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

        csv_header = (
            "# Stock data for 600595 (A-stock) from 2026-06-01 to 2026-07-10\n"
            "# Total records: 30\n"
            "# Data source: mootdx (TCP)\n"
            "# Data retrieved on: 2026-07-10 09:00:00\n\n"
        )
        csv_body = "Date,Open,High,Low,Close,Volume\n"
        for _, row in sample_kline_df.iterrows():
            csv_body += f"{row['Date'].strftime('%Y-%m-%d')},{row['Open']},{row['High']},{row['Low']},{row['Close']},{row['Volume']}\n"
        with patch(
            "tradingagents.dataflows.a_stock.get_stock_data",
            return_value=csv_header + csv_body,
        ) as mock_get_stock:
            from web.components.chart_panel import render_chart_panel
            render_chart_panel()

            mock_get_stock.assert_called_once()
            args = mock_get_stock.call_args.args
            assert args[0] == "600595"

            # renderLightweightCharts called with a list of panes
            assert mock_render_lwc.call_count == 1
            charts_arg = mock_render_lwc.call_args[0][0]
            assert len(charts_arg) == 2  # main (candle+MA) + volume pane

            main_chart = charts_arg[0]
            assert main_chart["chart"]["layout"]["background"]["color"] == "#0e131b"
            # candle + MA5 + MA10 + MA20 = 4 series in main pane
            assert len(main_chart["series"]) == 4
            assert main_chart["series"][0]["type"] == "Candlestick"
            assert main_chart["series"][1]["type"] == "Line"
            assert main_chart["series"][1]["options"]["title"] == "MA5"
            vol_chart = charts_arg[1]
            assert vol_chart["series"][0]["type"] == "Histogram"


def test_render_quote_banner_renders_correct_colors():
    """Up day → green (#00d68f); Down day → red (#ff4d6d). Arrow + sign correct."""
    from web.components.chart_panel import _render_quote_banner

    # Up: positive change_pct → green ▲ + sign
    with patch("streamlit.html") as mock_html:
        _render_quote_banner({
            "ticker": "600595",
            "price": 5.96,
            "change_pct": 3.30,
            "change_amount": 0.19,
            "timestamp": 1718000000.0,
        })
        call_str = str(mock_html.call_args)
        # bb-quote-up class is applied (color comes from --bb-up via CSS var)
        assert "bb-quote-up" in call_str
        assert "▲" in call_str
        assert "+3.30%" in call_str or "3.30%" in call_str

    # Down: negative change_pct → red ▼
    with patch("streamlit.html") as mock_html:
        _render_quote_banner({
            "ticker": "000001",
            "price": 10.50,
            "change_pct": -2.10,
            "change_amount": -0.22,
            "timestamp": 1718000000.0,
        })
        call_str = str(mock_html.call_args)
        # bb-quote-down class is applied (color comes from --bb-down via CSS var)
        assert "bb-quote-down" in call_str
        assert "▼" in call_str
        assert "-2.10%" in call_str


def test_render_lwc_chart_contains_required_elements(sample_kline_df):
    """Chart call must include: candle series, MA lines, volume histogram,
    correct background color, and A-share color convention (red up / green
    down)."""
    with patch(
        "web.components.chart_panel.renderLightweightCharts",
    ) as mock_render_lwc:
        from web.components.chart_panel import _render_lwc_chart
        _render_lwc_chart(sample_kline_df, "600595", "1m")

        charts_arg = mock_render_lwc.call_args[0][0]
        assert len(charts_arg) == 2

        # Main pane: Candlestick + MA5 + MA10 + MA20
        main_series = charts_arg[0]["series"]
        assert main_series[0]["type"] == "Candlestick"
        # Red up / green down for A-share
        assert main_series[0]["options"]["upColor"] == "#ff4d6d"
        assert main_series[0]["options"]["downColor"] == "#00d68f"
        # MA lines
        assert main_series[1]["options"]["title"] == "MA5"
        assert main_series[2]["options"]["title"] == "MA10"
        assert main_series[3]["options"]["title"] == "MA20"
        # Background color = dark Bloomberg style
        assert charts_arg[0]["chart"]["layout"]["background"]["color"] == "#0e131b"

        # Volume pane
        vol_series = charts_arg[1]["series"]
        assert vol_series[0]["type"] == "Histogram"
        # Volume has per-bar colors (one per row)
        assert len(vol_series[0]["data"]) == len(sample_kline_df)
        # First row color is either red or green (not a single value)
        first_color = vol_series[0]["data"][0]["color"]
        assert first_color in ("#ff4d6d", "#00d68f")


def test_get_ma_computes_correct_moving_averages(sample_kline_df):
    """_get_ma with [5, 10, 20] returns MA5/MA10/MA20 with correct rolling
    values, skipping leading NaN values (returned as list of {time, value}
    dicts ready for lightweight-charts).
    """
    from web.components.chart_panel import _get_ma

    mas = _get_ma(sample_kline_df, [5, 10, 20])
    assert set(mas.keys()) == {"MA5", "MA10", "MA20"}

    # Each MA is a list of {time, value} dicts
    assert isinstance(mas["MA5"], list)
    assert all("time" in p and "value" in p for p in mas["MA5"])

    # MA5 at row index 4 = mean of first 5 closes (first 4 are NaN, skipped)
    expected_ma5_at_4 = round(sample_kline_df["Close"].iloc[:5].mean(), 3)
    assert mas["MA5"][0]["value"] == pytest.approx(expected_ma5_at_4)

    # MA20: skip first 19 NaN, first value is mean of first 20 closes
    expected_ma20_at_19 = round(sample_kline_df["Close"].iloc[:20].mean(), 3)
    assert mas["MA20"][0]["value"] == pytest.approx(expected_ma20_at_19)

    # Number of valid points: total rows - (window - 1)
    assert len(mas["MA5"]) == len(sample_kline_df) - 4  # 30 - (5-1)
    assert len(mas["MA20"]) == len(sample_kline_df) - 19  # 30 - (20-1)


def test_get_historical_kline_uses_cache(tmp_cache_dir, sample_kline_df):
    """Fresh cache file present → get_stock_data is NOT called."""
    # Write a fresh CSV to cache
    cache = tmp_cache_dir / "600595_1m.csv"
    sample_kline_df.to_csv(cache, index=False, encoding="utf-8")

    with patch(
        "tradingagents.dataflows.a_stock.get_stock_data",
    ) as mock_get_stock:
        # If cache is correctly used, get_stock_data should NOT be called
        # and even if called, would raise
        mock_get_stock.side_effect = AssertionError("get_stock_data should not be called when cache is fresh")

        from web.components.chart_panel import _get_historical_kline
        df = _get_historical_kline("600595", "1m")

        # Cache file content returned
        assert len(df) == len(sample_kline_df)
        assert "Date" in df.columns
        assert "Close" in df.columns