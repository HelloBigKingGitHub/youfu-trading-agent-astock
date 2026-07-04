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
    """Valid ticker → _get_historical_kline is called + chart rendered via st.html."""
    cols_patch, _ = _patched_streamlit_columns()
    with cols_patch, \
         patch("streamlit.markdown"), \
         patch("streamlit.session_state", {}), \
         patch("streamlit.text_input", return_value="600595"), \
         patch("streamlit.selectbox", return_value="1m"), \
         patch("streamlit.button", return_value=False), \
         patch("streamlit.html") as mock_html, \
         patch("streamlit.warning"), \
         patch(
             "tradingagents.dataflows.a_stock._em_get",
         ) as mock_em_get:
        # Quote response: push2his trends2/sse format (last row close = current price)
        mock_quote = MagicMock()
        mock_quote.json.return_value = {
            "data": {
                "preClose": 5.75,
                "trends": [
                    "2026-07-03 09:30,5.75,5.80,5.82,5.74,5000,2880000.0,5.78",
                    "2026-07-03 14:55,5.94,5.94,5.95,5.94,3922,2316678.00,5.922",
                ],
            }
        }
        mock_em_get.return_value = mock_quote

        # get_stock_data returns CSV with header
        csv_header = (
            "# Stock data for 600595 (A-stock) from 2026-06-01 to 2026-07-10\n"
            "# Total records: 30\n"
            "# Data source: mootdx (TCP)\n"
            "# Data retrieved on: 2026-07-10 09:00:00\n\n"
        )
        csv_body = "Date,Open,High,Low,Close,Volume\n"
        for i, row in sample_kline_df.iterrows():
            csv_body += f"{row['Date'].strftime('%Y-%m-%d')},{row['Open']},{row['High']},{row['Low']},{row['Close']},{row['Volume']}\n"
        with patch(
            "tradingagents.dataflows.a_stock.get_stock_data",
            return_value=csv_header + csv_body,
        ) as mock_get_stock:
            from web.components.chart_panel import render_chart_panel
            render_chart_panel()

            # get_stock_data called with ticker + start + end
            mock_get_stock.assert_called_once()
            args = mock_get_stock.call_args.args
            assert args[0] == "600595"

            # st.html called at least twice (quote banner + chart)
            assert mock_html.call_count >= 2

            # Chart HTML contains LightweightCharts CDN
            chart_html = " ".join(str(c) for c in mock_html.call_args_list)
            assert "lightweight-charts" in chart_html
            assert "push2his.eastmoney.com" in chart_html


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
        assert "#00d68f" in call_str  # green
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
        assert "#ff4d6d" in call_str  # red
        assert "▼" in call_str
        assert "-2.10%" in call_str


def test_render_lightweight_chart_contains_required_elements(sample_kline_df):
    """Chart HTML must include: CDN script, candleSeries, MA series, EventSource SSE."""
    mas = {"MA5": sample_kline_df["Close"].rolling(5).mean()}

    with patch("streamlit.html") as mock_html:
        from web.components.chart_panel import _render_lightweight_chart_with_sse
        _render_lightweight_chart_with_sse(sample_kline_df, mas, "600595", "1m")

        call_str = str(mock_html.call_args)
        # CDN
        assert "lightweight-charts@4.1.3" in call_str
        assert "unpkg.com" in call_str
        # Chart container + candle series
        assert '<div id="chart"' in call_str
        assert "addCandlestickSeries" in call_str
        # MA series
        assert "addLineSeries" in call_str
        assert "MA5" in call_str
        # SSE realtime connection
        assert "EventSource" in call_str
        assert "push2his.eastmoney.com" in call_str
        assert "/api/qt/stock/trends2/sse" in call_str
        # secid for Shanghai
        assert "secid=1.600595" in call_str


def test_get_ma_computes_correct_moving_averages(sample_kline_df):
    """_get_ma with [5, 10, 20] returns MA5/MA10/MA20 with correct rolling values."""
    from web.components.chart_panel import _get_ma

    mas = _get_ma(sample_kline_df, [5, 10, 20])
    assert set(mas.keys()) == {"MA5", "MA10", "MA20"}

    # MA5 at row index 4 = mean of first 5 closes
    expected_ma5_at_4 = sample_kline_df["Close"].iloc[:5].mean()
    assert mas["MA5"].iloc[4] == pytest.approx(expected_ma5_at_4)

    # MA5 at row index 0-3 = NaN (not enough data)
    assert pd.isna(mas["MA5"].iloc[0])
    assert pd.isna(mas["MA5"].iloc[3])
    assert not pd.isna(mas["MA5"].iloc[4])

    # MA20 at row 19 = mean of first 20 closes
    expected_ma20_at_19 = sample_kline_df["Close"].iloc[:20].mean()
    assert mas["MA20"].iloc[19] == pytest.approx(expected_ma20_at_19)


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