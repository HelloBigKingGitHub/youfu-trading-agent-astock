"""GET /api/chart — read-only access to historical K-line + realtime quote.

Mirrors web/components/chart_panel.py 1:1:
- 7 time-range buttons (1d / 1w / 1m / 3m / 6m / 1y / all) — default 6m
- top ticker input (6-digit A-share code) — default 600595
- real-time quote banner (Tencent qt.gtimg.cn)
- K-line + MA5/10/20 + volume chart (Lightweight Charts in React frontend)
- 3-tier fallback via tradingagents.dataflows.a_stock.get_stock_data
  (mootdx → sina → push2his)

This API does NOT modify the business layer: it only reads. The same
``get_stock_data`` function is reused (0 changes), and the same 24h CSV
cache (~/.tradingagents/cache/kline/{ticker}_{range}.csv) is honored.

Phase 2.4 of P2.4.P1 — the 4th page to come online after Settings, History
and Logs.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Ranges (mirrors chart_panel._RANGES + sidebar order) ────────────────────
_VALID_RANGES: tuple[str, ...] = ("1d", "1w", "1m", "3m", "6m", "1y", "all")
_RANGE_DEFAULT = "6m"
_RANGE_START_DAYS: dict[str, int | None] = {
    # `None` means "use a wide window" (== "all" → 3y back, plenty for any
    # A-share IPO since the longest history is ~30y).
    "1d": 2,
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
    "all": 365 * 3,
}

_CACHE_DIR = Path.home() / ".tradingagents" / "cache" / "kline"
_CACHE_TTL = 24 * 3600


# ── helpers ────────────────────────────────────────────────────────────────


def _validate_ticker(ticker: str) -> str:
    """Strict 6-digit A-share code validation. Mirrors ``safe_ticker_component``.

    The Streamlit panel uses a free-text input and only checks ``len == 6``;
    the API tightens this to digits-only to avoid path-traversal-style inputs
    reaching the on-disk cache key.
    """
    if not ticker or not isinstance(ticker, str):
        raise HTTPException(status_code=400, detail="ticker is required")
    ticker = ticker.strip()
    if not ticker.isdigit() or len(ticker) != 6:
        raise HTTPException(
            status_code=400,
            detail=f"invalid ticker {ticker!r}: must be 6 digits (e.g. 600595)",
        )
    return ticker


def _validate_range(rng: str) -> str:
    if rng not in _VALID_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid range {rng!r}: must be one of {list(_VALID_RANGES)}",
        )
    return rng


def _parse_kline_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse ``get_stock_data``'s annotated CSV → list[dict] for the frontend.

    The store returns ``# …`` comment headers + a bare CSV body. We strip
    comments, parse Date/Open/High/Low/Close/Volume and round-trip floats to
    JSON-friendly values.
    """
    rows: list[dict[str, Any]] = []
    for ln in csv_text.split("\n"):
        if not ln or ln.startswith("#") or not ln.strip():
            continue
        parts = ln.split(",")
        if len(parts) < 6:
            continue
        try:
            rows.append(
                {
                    "date": parts[0],
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                    "volume": int(float(parts[5])),
                }
            )
        except (ValueError, IndexError):
            continue
    return rows


def _detect_source(csv_text: str) -> str:
    """Read the '# Data source:' comment line written by ``get_stock_data``."""
    for ln in csv_text.split("\n"):
        if ln.startswith("# Data source:"):
            src = ln.split(":", 1)[1].strip()
            if "mootdx" in src:
                return "mootdx"
            if "sina" in src:
                return "sina"
            if "push2his" in src:
                return "push2his"
            return "empty"
    return "empty"


def _read_cache(ticker: str, rng: str) -> list[dict[str, Any]] | None:
    """Read 24h CSV cache; return None on miss/stale/malformed.

    Mirrors ``_get_historical_kline``'s cache layer in chart_panel.py exactly.
    """
    cache = _CACHE_DIR / f"{ticker}_{rng}.csv"
    if not cache.exists():
        return None
    if (time.time() - cache.stat().st_mtime) >= _CACHE_TTL:
        return None
    try:
        import csv as _csv

        with cache.open("r", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            rows: list[dict[str, Any]] = []
            for r in reader:
                try:
                    rows.append(
                        {
                            "date": r.get("Date") or r.get("date") or "",
                            "open": float(r.get("Open") or r.get("open") or 0),
                            "high": float(r.get("High") or r.get("high") or 0),
                            "low": float(r.get("Low") or r.get("low") or 0),
                            "close": float(r.get("Close") or r.get("close") or 0),
                            "volume": int(
                                float(r.get("Volume") or r.get("volume") or 0)
                            ),
                        }
                    )
                except (ValueError, TypeError):
                    continue
            return rows or None
    except Exception:
        return None


def _write_cache(ticker: str, rng: str, rows: list[dict[str, Any]]) -> None:
    """Write 24h CSV cache (Date/Open/High/Low/Close/Volume header)."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = _CACHE_DIR / f"{ticker}_{rng}.csv"
        import csv as _csv

        with cache.open("w", encoding="utf-8", newline="") as f:
            writer = _csv.DictWriter(
                f, fieldnames=["Date", "Open", "High", "Low", "Close", "Volume"]
            )
            writer.writeheader()
            for r in rows:
                writer.writerow(
                    {
                        "Date": r["date"],
                        "Open": r["open"],
                        "High": r["high"],
                        "Low": r["low"],
                        "Close": r["close"],
                        "Volume": r["volume"],
                    }
                )
    except Exception as exc:
        logger.warning("cache write failed for %s/%s: %s", ticker, rng, exc)


# ── endpoints ──────────────────────────────────────────────────────────────


@router.get("/chart/kline")
def get_kline(
    ticker: str = Query(..., description="6-digit A-share code (e.g. 600595)"),
    rng: str = Query(_RANGE_DEFAULT, alias="range", description="1d|1w|1m|3m|6m|1y|all"),
) -> dict[str, Any]:
    """Historical K-line with 3-tier fallback (mootdx → sina → push2his).

    Reuses tradingagents.dataflows.a_stock.get_stock_data() 1:1; we do NOT
    reimplement the fallback chain here. The same 24h CSV cache used by the
    Streamlit panel is honored so a cold React page + warm Streamlit page
    hash the same bytes.
    """
    ticker = _validate_ticker(ticker)
    rng = _validate_range(rng)

    # 1. Try cache first (24h TTL).
    cached = _read_cache(ticker, rng)
    if cached is not None:
        return {
            "ticker": ticker,
            "range": rng,
            "klines": cached,
            "source": "cache",
            "cached": True,
            "count": len(cached),
        }

    # 2. Compute date window.
    days = _RANGE_START_DAYS[rng]
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat() if days else "1990-01-01"

    # 3. Call the business-layer function (3-tier fallback already inside).
    try:
        from tradingagents.dataflows.a_stock import get_stock_data

        csv_text = get_stock_data(ticker, start, end)
    except Exception as exc:
        logger.exception("get_stock_data raised for %s/%s: %s", ticker, rng, exc)
        # Fall back to cache if it became available mid-call.
        cached = _read_cache(ticker, rng)
        if cached is not None:
            return {
                "ticker": ticker,
                "range": rng,
                "klines": cached,
                "source": "cache",
                "cached": True,
                "count": len(cached),
            }
        raise HTTPException(
            status_code=502,
            detail=f"K-line fetch failed for {ticker}: {exc}",
        ) from exc

    # 4. Empty-result strings from get_stock_data are surfaced as-is.
    if csv_text.startswith("K线数据获取失败") or csv_text.startswith("No data found"):
        return {
            "ticker": ticker,
            "range": rng,
            "klines": [],
            "source": "empty",
            "cached": False,
            "count": 0,
            "message": csv_text.strip().split("\n")[0],
        }

    rows = _parse_kline_csv(csv_text)
    source = _detect_source(csv_text)

    # 5. Warm cache for the next 24h.
    if rows:
        _write_cache(ticker, rng, rows)

    return {
        "ticker": ticker,
        "range": rng,
        "klines": rows,
        "source": source,
        "cached": False,
        "count": len(rows),
    }


@router.get("/chart/quote")
def get_quote(
    ticker: str = Query(..., description="6-digit A-share code (e.g. 600595)"),
) -> dict[str, Any]:
    """Real-time quote from Tencent qt.gtimg.cn (mirrors _tencent_quote)."""
    ticker = _validate_ticker(ticker)
    try:
        from tradingagents.dataflows.a_stock import _tencent_quote

        quotes = _tencent_quote([ticker])
        q = quotes.get(ticker)
        if not q or not q.get("price"):
            raise HTTPException(
                status_code=502,
                detail=f"tencent qt.gtimg.cn returned empty quote for {ticker}",
            )
        price = float(q["price"])
        last_close = float(q.get("last_close") or price)
        change_amount = round(price - last_close, 3)
        change_pct = (
            round((price - last_close) / last_close * 100, 2) if last_close else 0.0
        )
        return {
            "ticker": ticker,
            "name": q.get("name", ""),
            "price": price,
            "open": float(q.get("open") or 0),
            "high": float(q.get("high") or 0),
            "low": float(q.get("low") or 0),
            "last_close": last_close,
            "change_amount": change_amount,
            "change_pct": change_pct,
            "volume": 0,  # qt.gtimg.cn minimal — placeholder
            "timestamp": time.time(),
            "source": "tencent_qt_gtimg",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("get_quote raised for %s: %s", ticker, exc)
        raise HTTPException(
            status_code=502,
            detail=f"quote fetch failed for {ticker}: {exc}",
        ) from exc


# ── SSE (long-poll style, mirrors streamlit's planned EventSource) ─────────


async def _sse_kline_stream(
    ticker: str, rng: str
) -> AsyncIterator[str]:
    """Server-Sent Events: emit one kline update per minute.

    Per spec P2.4 § 4: "POST /api/chart/quote/sse?ticker=X&range=Y → 每 1 分钟
    push K 线 update". We implement GET (the spec mentions POST in the brief
    but EventSource only supports GET; POST here would break the browser
    EventSource API). First event is the current snapshot; subsequent events
    are refreshed snapshots every 60s until the client disconnects.

    Each SSE frame follows the standard ``data: <json>\\n\\n`` wire format.
    """
    yield f"event: open\ndata: {json.dumps({'ticker': ticker, 'range': rng})}\n\n"
    while True:
        try:
            payload = get_kline(ticker=ticker, rng=rng)
            payload["ts"] = time.time()
            yield f"event: kline\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except HTTPException as exc:
            yield f"event: error\ndata: {json.dumps({'detail': exc.detail})}\n\n"
        except Exception as exc:  # pragma: no cover
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
        await asyncio.sleep(60)


@router.get("/chart/quote/sse")
async def get_quote_sse(
    ticker: str = Query(..., description="6-digit A-share code (e.g. 600595)"),
    rng: str = Query(_RANGE_DEFAULT, alias="range"),
):
    """SSE stream of kline updates (1 per minute).

    The brief mentions POST but browsers' native ``EventSource`` only supports
    GET, and the Streamlit mirror also uses HTTP polling, so GET is the
    canonical transport here.
    """
    ticker = _validate_ticker(ticker)
    rng = _validate_range(rng)
    return StreamingResponse(
        _sse_kline_stream(ticker, rng),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )