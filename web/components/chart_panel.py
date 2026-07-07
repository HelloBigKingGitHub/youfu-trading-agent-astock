"""K线 + MA + 成交量 + 实时报价 面板 (v0.4.0).

Entry point: :func:`render_chart_panel`. Sidebar nav (in ``web/app.py``) calls
this when ``nav == "chart"``.

Data flow
---------
1. Python side (``_get_historical_kline``): 3-tier fallback via
   ``get_stock_data`` (mootdx → sina → push2his) → 24h CSV cache
   (``~/.tradingagents/cache/kline/{ticker}_{rng}.csv``).
2. Real-time quote (``_get_realtime_quote``): ``qt.gtimg.cn`` (tencent) HTTP
   (走 ``_tencent_quote`` 批量化入口; 之前试过 ``push2his/trends2/sse`` 但它
   是 SSE 长连接端点, 普通 HTTP GET 不带 ``Accept: text/event-stream`` 会被
   服务端先保持连接再超时断开 → ``RemoteDisconnected``), rendered as
   ``bb-quote-banner`` HTML.
3. K-line + MA + volume chart via ``streamlit-lightweight-charts`` (PyPI
   package, MIT, TradingView's Lightweight Charts v5 wrapped as a proper
   streamlit custom component). This bypasses the DOMPurify limitations of
   ``st.html(unsafe_allow_javascript=True)`` because custom components are
   served via streamlit's internal ``_stcore/bidi-components/`` endpoint and
   do not pass through the sanitize pass.

v0.4.0 migration note
---------------------
Earlier 0.4.0 versions tried to embed Lightweight Charts via ``st.html``
inline scripts + ``<script src=...>`` for the LWC bundle, but streamlit
1.58's DOMPurify 3.4.5 keeps the ``<script>`` element but strips the
inline body (per the streamlit client ``Html.oJkhUkEr.js``'s
``Ye`` React component: ``useEffect`` clones each script via
``createElement + replaceChild`` but the inline body is a text node that
gets escaped during DOMPurify's HTML-to-DOM round-trip). The 3-script
split (data / src / IIFE) workaround also failed for the same reason.

Switching to ``streamlit-lightweight-charts==0.7.20`` (a proper streamlit
custom component shipped as a prebuilt React bundle) bypasses the sanitize
pass entirely and renders K-line + MA + volume correctly.

SSE realtime
------------
Note: the earlier D2 direct EventSource realtime push to
``push2his.eastmoney.com/api/qt/stock/trends2/sse`` is NOT yet wired into
the new wrapper. ``renderLightweightCharts`` is a black-box component, so
we cannot inject an EventSource into its iframe. Real-time updates would
require either: (a) polling every 5-10s + re-render, or (b) upgrading
``streamlit-lightweight-charts`` to expose an update hook. We ship the
historical view first; realtime is a follow-up.
"""

from __future__ import annotations

import io
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_lightweight_charts import renderLightweightCharts


logger = logging.getLogger(__name__)


# Tokens (red up / green down for A-share convention; can be flipped by
# editing web/styles/tokens.css's --bb-up / --bb-down to match Chinese
# market convention).
_BB_UP = "#ff4d6d"        # red (涨)
_BB_DOWN = "#00d68f"      # green (跌)

_CACHE_DIR = Path.home() / ".tradingagents" / "cache" / "kline"
_CACHE_TTL = 24 * 3600

_RANGES = ["1d", "1w", "1m", "3m", "6m", "1y", "all"]


def render_chart_panel() -> None:
    """Entry point, called from app.py when nav == 'chart'."""
    st.markdown("## 📈 股价走势图")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        ticker = st.text_input(
            "股票代码",
            value=st.session_state.get("chart_ticker", "600595"),
            key="chart_ticker_input",
        ).strip()
    with col2:
        rng = st.selectbox(
            "时间范围",
            options=_RANGES,
            index=2,  # default "1m"
            key="chart_range_select",
        )
    with col3:
        if st.button("🔄 刷新", use_container_width=True):
            st.session_state["chart_force_refresh"] = True
            st.rerun()

    if not ticker or len(ticker) != 6:
        st.info("请输入 6 位股票代码 (例: 600595)")
        return

    # 2. Real-time quote banner
    try:
        quote = _get_realtime_quote(ticker)
        _render_quote_banner(quote)
    except Exception as exc:
        logger.warning("_get_realtime_quote failed for %s: %s", ticker, exc, exc_info=True)
        st.warning(f"实时报价拉取失败: {exc}")

    # 3. K-line + MA + volume chart
    try:
        df = _get_historical_kline(ticker, rng)
        if df.empty:
            st.warning(f"{ticker} 在 {rng} 范围内无 K 线数据")
            return
        _render_lwc_chart(df, ticker, rng)
    except Exception as exc:
        st.error(f"K 线数据加载失败: {exc}")


# ── Real-time quote ────────────────────────────────────────────


def _get_realtime_quote(ticker: str) -> dict:
    """Fetch realtime quote from Tencent Finance (qt.gtimg.cn)."""
    from tradingagents.dataflows.a_stock import _tencent_quote

    quotes = _tencent_quote([ticker])
    q = quotes.get(ticker)
    if not q or not q.get("price"):
        raise ValueError(f"tencent qt.gtimg.cn returned empty quote for {ticker}")

    price = q["price"]
    pre_close = q.get("last_close") or price
    change_amount = round(price - pre_close, 3)
    change_pct = round((price - pre_close) / pre_close * 100, 2) if pre_close else 0

    return {
        "ticker": ticker,
        "price": price,
        "change_pct": change_pct,
        "change_amount": change_amount,
        "timestamp": time.time(),
    }


def _render_quote_banner(quote: dict) -> None:
    cls = "bb-quote-up" if quote["change_pct"] >= 0 else "bb-quote-down"
    arrow = "▲" if quote["change_pct"] >= 0 else "▼"
    sign = "+" if quote["change_pct"] >= 0 else ""
    pct_str = f"{sign}{quote['change_pct']:.2f}%" if quote["change_pct"] >= 0 else f"{quote['change_pct']:.2f}%"
    amt_str = f"{sign}{quote['change_amount']:.2f}" if quote["change_amount"] >= 0 else f"{quote['change_amount']:.2f}"
    ts_str = datetime.fromtimestamp(quote["timestamp"]).strftime("%H:%M:%S")
    st.html(
        f"""
        <style>
            .bb-quote-banner .bb-quote-up {{ color: var(--bb-up); }}
            .bb-quote-banner .bb-quote-down {{ color: var(--bb-down); }}
        </style>
        <div class="bb-quote-banner">
            <div class="bb-quote-ticker">{quote['ticker']}</div>
            <div class="bb-quote-price {cls}">{quote['price']:.2f}</div>
            <div class="bb-quote-change {cls}">{arrow} {pct_str}</div>
            <div class="bb-quote-amount {cls}">{amt_str}</div>
            <div class="bb-quote-time">{ts_str}</div>
        </div>
        """
    )


# ── Historical K-line (3-fallback via get_stock_data + 24h cache) ──────────


def _get_historical_kline(ticker: str, rng: str) -> pd.DataFrame:
    """Fetch historical K-line with 24h CSV cache, parsing get_stock_data CSV."""
    from tradingagents.dataflows.a_stock import get_stock_data

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _CACHE_DIR / f"{ticker}_{rng}.csv"

    if cache.exists() and (time.time() - cache.stat().st_mtime) < _CACHE_TTL:
        try:
            return pd.read_csv(cache, parse_dates=["Date"])
        except Exception:
            pass

    end = date.today().isoformat()
    start = {
        "1d": (date.today() - timedelta(days=2)).isoformat(),
        "1w": (date.today() - timedelta(days=7)).isoformat(),
        "1m": (date.today() - timedelta(days=30)).isoformat(),
        "3m": (date.today() - timedelta(days=90)).isoformat(),
        "6m": (date.today() - timedelta(days=180)).isoformat(),
        "1y": (date.today() - timedelta(days=365)).isoformat(),
        "all": (date.today() - timedelta(days=365 * 3)).isoformat(),
    }[rng]

    try:
        csv_text = get_stock_data(ticker, start, end)
        if csv_text.startswith("K线数据获取失败") or csv_text.startswith("No data found"):
            raise ValueError(csv_text.strip().split("\n")[0])
        lines = [ln for ln in csv_text.split("\n") if not ln.startswith("#") and ln.strip()]
        if not lines:
            raise ValueError(f"Empty CSV from get_stock_data for {ticker}")
        df = pd.read_csv(io.StringIO("\n".join(lines)), parse_dates=["Date"])
        if df.empty:
            raise ValueError(f"Empty DataFrame after parsing for {ticker}")
        df.to_csv(cache, index=False, encoding="utf-8")
        return df
    except Exception as exc:
        if cache.exists():
            try:
                return pd.read_csv(cache, parse_dates=["Date"])
            except Exception:
                pass
        raise


def _get_ma(df: pd.DataFrame, windows: list[int]) -> dict[str, list[dict]]:
    """Return MA line series for the chart, skipping leading NaN values."""
    out: dict[str, list[dict]] = {}
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    for w in windows:
        ma = df["Close"].rolling(window=w).mean()
        points = []
        for d, v in zip(dates, ma):
            if pd.notna(v):
                points.append({"time": d, "value": round(float(v), 3)})
        out[f"MA{w}"] = points
    return out


# ── Lightweight Charts via streamlit-lightweight-charts ──────────


def _render_lwc_chart(df: pd.DataFrame, ticker: str, rng: str) -> None:
    """Render the candlestick + volume + MA chart via the PyPI wrapper.

    Wraps the official ``streamlit-lightweight-charts`` package
    (which itself wraps TradingView's ``lightweight-charts`` v5 as a
    prebuilt React bundle distributed as a streamlit custom component).
    """
    candles = [
        {
            "time": d.strftime("%Y-%m-%d"),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
        }
        for d, o, h, l, c in zip(df["Date"], df["Open"], df["High"], df["Low"], df["Close"])
    ]
    # Volume histogram: per-bar color (red up / green down) handled by
    # LWC's "color" property which can be a list (one color per bar).
    vol_colors = [
        _BB_UP if float(c) >= float(o) else _BB_DOWN
        for o, c in zip(df["Open"], df["Close"])
    ]
    volumes = [
        {"time": d.strftime("%Y-%m-%d"), "value": int(v), "color": col}
        for d, v, col in zip(df["Date"], df["Volume"], vol_colors)
    ]
    ma_series = _get_ma(df, [5, 10, 20])

    candle_series = [
        {
            "type": "Candlestick",
            "data": candles,
            "options": {
                "upColor": _BB_UP,
                "downColor": _BB_DOWN,
                "borderUpColor": _BB_UP,
                "borderDownColor": _BB_DOWN,
                "wickUpColor": _BB_UP,
                "wickDownColor": _BB_DOWN,
            },
        }
    ]

    volume_series = [
        {
            "type": "Histogram",
            "data": volumes,
            "options": {
                "priceFormat": {"type": "volume"},
                "priceScaleId": "vol",
                "color": _BB_UP,
            },
            "priceScale": {
                "scaleMargins": {"top": 0.8, "bottom": 0},
                "alignLabels": False,
            },
        }
    ]

    ma_colors = {"MA5": "#4d9aff", "MA10": "#fbbf24", "MA20": "#7ab4ff"}
    line_series = [
        {
            "type": "Line",
            "data": points,
            "options": {
                "color": ma_colors.get(name, "#8a96a8"),
                "lineWidth": 1,
                "priceLineVisible": False,
                "lastValueVisible": False,
                "title": name,
            },
        }
        for name, points in ma_series.items()
    ]

    chart_options = {
        "height": 480,
        "layout": {
            "background": {"type": "solid", "color": "#0e131b"},
            "textColor": "#8a96a8",
        },
        "grid": {
            "vertLines": {"color": "#1c2532"},
            "horzLines": {"color": "#1c2532"},
        },
        "timeScale": {
            "timeVisible": True,
            "secondsVisible": False,
            "borderColor": "#1c2532",
        },
        "rightPriceScale": {"borderColor": "#1c2532"},
        "crosshair": {"mode": 0},
        "watermark": {
            "visible": True,
            "text": f"{ticker}  {rng}",
            "fontSize": 32,
            "horzAlign": "left",
            "vertAlign": "top",
            "color": "rgba(74, 154, 255, 0.08)",
        },
    }

    renderLightweightCharts(
        [
            {"chart": chart_options, "series": candle_series + line_series},
            {
                "chart": {**chart_options, "height": 120, "watermark": {"visible": False}},
                "series": volume_series,
            },
        ],
        key=f"lwc_{ticker}_{rng}",
    )

    st.caption(
        "蜡烛颜色遵循 A 股惯例（红涨绿跌），MA5/10/20 + 成交量副图。"
        "历史 K 线数据来自 mootdx → sina → push2his 3 层 fallback。"
    )
