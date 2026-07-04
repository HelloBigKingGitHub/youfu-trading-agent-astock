"""K线 + MA + 成交量 + 实时报价 + 实时 SSE 推送 面板 (v0.4.0).

Entry point: :func:`render_chart_panel`. Sidebar nav (in ``web/app.py``) calls
this when ``nav == "chart"``.

Data flow
---------
1. Python side (``_get_historical_kline``): 3-tier fallback via
   ``get_stock_data`` (mootdx → sina → push2his) → 24h CSV cache
   (``~/.tradingagents/cache/kline/{ticker}_{rng}.csv``).
2. Real-time quote (``_get_realtime_quote``): single ``push2/stock/get`` call,
   rendered as ``bb-quote-banner`` HTML.
3. Browser side (``_render_lightweight_chart_with_sse``): Lightweight Charts v4
   embeds historical K-line + MA5/10/20 + volume, then opens an ``EventSource``
   to ``push2his.eastmoney.com/api/qt/stock/trends2/sse`` for live updates
   (CORS-verified, no backend proxy needed).
"""

from __future__ import annotations

import io
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st


_LIGHTWEIGHT_CDN = (
    "https://unpkg.com/lightweight-charts@4.1.3/dist/"
    "lightweight-charts.standalone.production.js"
)

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

    # 2. Real-time quote banner (走 push2/get 一次性)
    try:
        quote = _get_realtime_quote(ticker)
        _render_quote_banner(quote)
    except Exception as exc:
        st.warning(f"实时报价拉取失败: {exc}")

    # 3. K-line + MA + volume + SSE realtime
    try:
        df = _get_historical_kline(ticker, rng)
        if df.empty:
            st.warning(f"{ticker} 在 {rng} 范围内无 K 线数据")
            return
        mas = _get_ma(df, [5, 10, 20])
        _render_lightweight_chart_with_sse(df, mas, ticker, rng)
    except Exception as exc:
        st.error(f"K 线数据加载失败: {exc}")


# ── Real-time quote (Python 端一次性, 给 banner 用) ──────────


def _get_realtime_quote(ticker: str) -> dict:
    """Fetch realtime quote from 东财 push2 (走 _em_get 节流)."""
    from tradingagents.dataflows.a_stock import _em_get

    secid_prefix = "1." if ticker.startswith("6") else "0."
    secid = f"{secid_prefix}{ticker}"

    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386a173a0153c803ac01",
        "fields": "f43,f44,f45,f46,f60,f169,f170",
    }
    r = _em_get(url, params=params, timeout=10)
    d = r.json().get("data", {})

    return {
        "ticker": ticker,
        "price": d.get("f43", 0) / 100,         # f43 单位是分
        "change_pct": d.get("f170", 0) / 100,
        "change_amount": d.get("f169", 0) / 100,
        "timestamp": time.time(),
    }


def _render_quote_banner(quote: dict) -> None:
    color = "#00d68f" if quote["change_pct"] >= 0 else "#ff4d6d"
    arrow = "▲" if quote["change_pct"] >= 0 else "▼"
    sign = "+" if quote["change_pct"] >= 0 else ""
    pct_str = f"{sign}{quote['change_pct']:.2f}%" if quote["change_pct"] >= 0 else f"{quote['change_pct']:.2f}%"
    amt_str = f"{sign}{quote['change_amount']:.2f}" if quote["change_amount"] >= 0 else f"{quote['change_amount']:.2f}"
    ts_str = datetime.fromtimestamp(quote["timestamp"]).strftime("%H:%M:%S")
    st.html(
        f"""
        <div class="bb-quote-banner">
            <div class="bb-quote-ticker">{quote['ticker']}</div>
            <div class="bb-quote-price" style="color: {color}">{quote['price']:.2f}</div>
            <div class="bb-quote-change" style="color: {color}">{arrow} {pct_str}</div>
            <div class="bb-quote-amount" style="color: {color}">{amt_str}</div>
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

    # Try cache
    if cache.exists() and (time.time() - cache.stat().st_mtime) < _CACHE_TTL:
        try:
            return pd.read_csv(cache, parse_dates=["Date"])
        except Exception:
            pass

    # Compute fetch window (request more than needed; trim after parse)
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
        # Parse CSV (skip header lines starting with #)
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
        if cache.exists():  # stale cache fallback
            try:
                return pd.read_csv(cache, parse_dates=["Date"])
            except Exception:
                pass
        raise


def _get_ma(df: pd.DataFrame, windows: list[int]) -> dict[str, pd.Series]:
    return {f"MA{w}": df["Close"].rolling(window=w).mean() for w in windows}


# ── Lightweight Charts + SSE realtime (D2 直连) ────────────────


def _render_lightweight_chart_with_sse(
    df: pd.DataFrame, mas: dict, ticker: str, rng: str,
) -> None:
    """Embed Lightweight Charts + EventSource realtime update via st.html()."""
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
    volumes = [
        {
            "time": d.strftime("%Y-%m-%d"),
            "value": int(v),
            "color": "#00d68f80" if float(c) >= float(o) else "#ff4d6d80",
        }
        for d, o, c, v in zip(df["Date"], df["Open"], df["Close"], df["Volume"])
    ]
    ma_series = {
        name: [
            {"time": d.strftime("%Y-%m-%d"), "value": (None if pd.isna(v) else float(v))}
            for d, v in zip(df["Date"], ser)
        ]
        for name, ser in mas.items()
    }

    data_json = json.dumps(
        {"candles": candles, "volumes": volumes, "ma": ma_series},
        ensure_ascii=False,
    )

    # 东财 SSE URL (browser 直连)
    secid_prefix = "1." if ticker.startswith("6") else "0."
    secid = f"{secid_prefix}{ticker}"
    sse_url = (
        "https://push2his.eastmoney.com/api/qt/stock/trends2/sse"
        f"?secid={secid}"
        "&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        "&iscr=0&ndays=1"
    )

    html = f"""
    <div id="chart" style="width:100%;height:600px"></div>
    <script src="{_LIGHTWEIGHT_CDN}"></script>
    <script>
    const data = {data_json};
    const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
        width: document.getElementById('chart').clientWidth,
        height: 600,
        layout: {{
            background: {{ type: 'solid', color: '#0e131b' }},
            textColor: '#8a96a8',
        }},
        grid: {{ vertLines: {{ color: '#1c2532' }}, horzLines: {{ color: '#1c2532' }} }},
        timeScale: {{ timeVisible: true, secondsVisible: false, borderColor: '#1c2532' }},
        rightPriceScale: {{ borderColor: '#1c2532' }},
    }});
    const candleSeries = chart.addCandlestickSeries({{
        upColor: '#00d68f', downColor: '#ff4d6d',
        borderUpColor: '#00d68f', borderDownColor: '#ff4d6d',
        wickUpColor: '#00d68f', wickDownColor: '#ff4d6d',
    }});
    candleSeries.setData(data.candles);
    const volumeSeries = chart.addHistogramSeries({{
        priceFormat: {{ type: 'volume' }},
        priceScaleId: '',
        scaleMargins: {{ top: 0.8, bottom: 0 }},
    }});
    volumeSeries.setData(data.volumes);
    chart.priceScale('').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});

    const maColors = {{ 'MA5': '#4d9aff', 'MA10': '#fbbf24', 'MA20': '#7ab4ff' }};
    Object.entries(data.ma).forEach(([name, points]) => {{
        const s = chart.addLineSeries({{
            color: maColors[name] || '#8a96a8',
            lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
        }});
        s.setData(points.filter(p => p.value !== null));
    }});
    chart.timeScale().fitContent();

    // === D2: 浏览器直连东财 SSE 实时推送 ===
    const sseUrl = "{sse_url}";
    const es = new EventSource(sseUrl);
    es.onmessage = (e) => {{
        try {{
            const payload = JSON.parse(e.data);
            const d = payload.data;
            if (!d || !d.trends || d.trends.length === 0) return;

            const lastLine = d.trends[d.trends.length - 1];
            const parts = lastLine.split(",");
            // 格式: "2026-07-03 14:30,5.94,5.94,5.94,5.93,3847,..."
            const time = parts[0].substring(0, 10);
            const open = parseFloat(parts[1]);
            const close = parseFloat(parts[2]);
            const high = parseFloat(parts[3]);
            const low = parseFloat(parts[4]);
            const volume = parseInt(parts[5]);

            candleSeries.update({{ time: time, open: open, high: high, low: low, close: close }});
            const isUp = close >= open;
            volumeSeries.update({{
                time: time, value: volume,
                color: isUp ? "#00d68f80" : "#ff4d6d80",
            }});
        }} catch (err) {{
            console.error("SSE parse error", err);
        }}
    }};
    es.onerror = (e) => {{
        console.warn("SSE connection error, will auto-reconnect", e);
    }};
    </script>
    """
    st.html(html)