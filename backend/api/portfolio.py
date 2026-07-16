"""Portfolio FastAPI router — read-only + write endpoints for the personal
portfolio module (v0.5.0), surfaced to the React frontend (P2.7).

Mirrors ``web/components/portfolio_panel.py`` 1:1 by exposing the same data
slices the Streamlit panel renders:

  - GET  /portfolio/positions                          → list positions
  - GET  /portfolio/transactions                       → list transactions
  - GET  /portfolio/positions/group_by_sector          → 3 pie data
  - GET  /portfolio/allocation                         → asset class + concentration
  - GET  /portfolio/alerts                             → 7 rules + audit
  - GET  /portfolio/alerts/rules                       → list 7 rule defs
  - POST /portfolio/alerts/ack/{alert_id}              → ack an alert
  - GET  /portfolio/risk                               → XIRR / Sharpe / MaxDD / Brinson
  - GET  /portfolio/import/detect?file_path=           → CSV detect (4 formats)
  - POST /portfolio/import/preview                     → preview CSV (multipart)
  - POST /portfolio/import/commit                      → commit import
  - GET  /portfolio/export?format=                     → export CSV (UTF-8 BOM)

This API does NOT modify the business layer: it reuses the existing
``backend.core.portfolio_store``, ``backend.core.portfolio_calc``,
``backend.core.portfolio_alerts`` and ``backend.core.portfolio_import`` modules.
The Streamlit panel keeps running in parallel (硬约束 0 改).

Phase 2.7 of v0.7.0 — the 7th page to come online after Settings, History,
Logs, Chart, Sector, Batch.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────────────


def _position_to_dict(p: Any) -> dict[str, Any]:
    """Convert Position dataclass → JSON-safe dict."""
    if hasattr(p, "to_dict"):
        return p.to_dict()
    return {
        "position_id": getattr(p, "position_id", ""),
        "ticker": getattr(p, "ticker", ""),
        "name": getattr(p, "name", ""),
        "cost_basis": float(getattr(p, "cost_basis", 0.0)),
        "quantity": int(getattr(p, "quantity", 0)),
        "first_buy_date": getattr(p, "first_buy_date", ""),
        "last_trade_date": getattr(p, "last_trade_date", ""),
        "account": getattr(p, "account", "default"),
        "asset_class": getattr(p, "asset_class", "stock"),
        "notes": getattr(p, "notes", ""),
        "created_at": getattr(p, "created_at", 0.0),
    }


def _transaction_to_dict(t: Any) -> dict[str, Any]:
    """Convert Transaction dataclass → JSON-safe dict."""
    if hasattr(t, "to_dict"):
        return t.to_dict()
    return {
        "tx_id": getattr(t, "tx_id", ""),
        "position_id": getattr(t, "position_id", ""),
        "ticker": getattr(t, "ticker", ""),
        "date": getattr(t, "date", ""),
        "action": getattr(t, "action", ""),
        "price": float(getattr(t, "price", 0.0)),
        "quantity": int(getattr(t, "quantity", 0)),
        "fees": float(getattr(t, "fees", 0.0)),
        "notes": getattr(t, "notes", ""),
        "created_at": getattr(t, "created_at", 0.0),
    }


def _alert_to_dict(a: Any) -> dict[str, Any]:
    """Convert AlertRule dataclass → JSON-safe dict."""
    if hasattr(a, "to_dict"):
        return a.to_dict()
    return {
        "rule_id": getattr(a, "rule_id", ""),
        "ticker": getattr(a, "ticker", ""),
        "rule_type": getattr(a, "rule_type", ""),
        "threshold": float(getattr(a, "threshold", 0.0)),
        "enabled": bool(getattr(a, "enabled", True)),
        "note": getattr(a, "note", ""),
        "created_at": getattr(a, "created_at", 0.0),
        "last_triggered_at": getattr(a, "last_triggered_at", None),
        "last_triggered_price": getattr(a, "last_triggered_price", None),
        "trigger_count": int(getattr(a, "trigger_count", 0)),
    }


def _safe_quote(ticker: str) -> Optional[float]:
    """Best-effort current price lookup; returns None on any error.

    Mirrors ``web/components/portfolio_overview.py::safe_quote``.  Tries
    ``tradingagents.dataflows.a_stock._tencent_quote`` first (the same source
    Streamlit uses), falls back to None so the API can still respond when the
    upstream quote vendor is offline.
    """
    try:
        from tradingagents.dataflows.a_stock import _tencent_quote
        quotes = _tencent_quote([ticker])
        q = quotes.get(ticker) if isinstance(quotes, dict) else None
        if not q or not q.get("price"):
            return None
        return float(q["price"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("safe_quote(%s) failed: %s", ticker, exc)
        return None


def _fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """Batch-fetch current prices for all tickers; skip tickers where the
    quote failed (callers fall back to cost_basis)."""
    out: dict[str, float] = {}
    for t in tickers:
        q = _safe_quote(t)
        if q is not None:
            out[t] = q
    return out


def _store():
    """Lazy import to avoid side-effects at module import time."""
    from backend.core.portfolio_store import get_portfolio_store
    return get_portfolio_store()


# ── 1. positions ─────────────────────────────────────────────────────────────


@router.get("/portfolio/positions")
def list_positions(
    account: str = Query("", description="Optional account name filter"),
    asset_class: str = Query("", description="Optional asset_class filter"),
) -> dict[str, Any]:
    """List all positions in the singleton store.

    Mirrors ``PortfolioStore.list_positions()`` and the Streamlit
    ``render_overview_tab`` table on Tab 1.
    """
    store = _store()
    positions = store.list_positions(
        account=account or None,
        asset_class=asset_class or None,
    )
    rows = [_position_to_dict(p) for p in positions]

    # Attach current-price snapshot so the React table can render PnL
    # without an extra round-trip.  Mirrors the ``prices_cache`` flow in
    # ``portfolio_panel.py`` (best-effort; falls back to cost basis).
    tickers = sorted({r["ticker"] for r in rows})
    prices = _fetch_current_prices(tickers)
    for r in rows:
        r["current_price"] = prices.get(r["ticker"], float(r["cost_basis"]))

    return {
        "positions": rows,
        "count": len(rows),
        "prices_source": "tencent" if prices else "fallback-cost",
        "fetched_at": time.time(),
    }


@router.get("/portfolio/transactions")
def list_transactions(
    ticker: str = Query("", description="Optional ticker filter"),
    since: str = Query("", description="Optional YYYY-MM-DD since filter"),
) -> dict[str, Any]:
    """List all transactions, newest first.

    Mirrors ``PortfolioStore.list_transactions()`` and the Streamlit
    ``render_transactions_tab`` table on Tab 2.
    """
    store = _store()
    txs = store.list_transactions(
        ticker=ticker or None,
        since=since or None,
    )
    rows = [_transaction_to_dict(t) for t in txs]
    return {
        "transactions": rows,
        "count": len(rows),
        "fetched_at": time.time(),
    }


# ── 3. group_by_sector (3 pie data) ─────────────────────────────────────────


@router.get("/portfolio/positions/group_by_sector")
def group_by_sector() -> dict[str, Any]:
    """Group positions by industry / sector / asset_class for 3 pie charts.

    Mirrors Tab 3 (配置) in the Streamlit panel — the page renders 3 pies:
    industry, sector, asset_class.  Uses ``portfolio_calc.group_by_sector``
    for the network-fetched sector split, and computes industry / asset_class
    from the positions directly (cheap local aggregation).
    """
    from backend.core.portfolio_calc import group_by_sector as calc_group_by_sector

    store = _store()
    positions = store.list_positions()
    tickers = sorted({p.ticker for p in positions})
    prices = _fetch_current_prices(tickers)

    # by_asset_class — local aggregation, no IO
    by_asset_class: dict[str, float] = {}
    for p in positions:
        price = prices.get(p.ticker, p.cost_basis)
        value = float(price) * int(p.quantity)
        key = p.asset_class or "stock"
        by_asset_class[key] = by_asset_class.get(key, 0.0) + value

    # by_industry — local aggregation keyed by ``name`` prefix until we wire
    # an industry vendor.  The Streamlit panel leaves by_industry empty for
    # the MVP (no cheap industry-classification source).  We mirror that by
    # returning an empty mapping.
    by_industry: dict[str, float] = {}

    # by_sector — delegates to ``portfolio_calc.group_by_sector`` (network
    # IO via a_stock.get_concept_blocks with graceful fallback).
    try:
        by_sector = calc_group_by_sector(positions, prices)
    except Exception as exc:  # noqa: BLE001
        logger.debug("group_by_sector failed: %s", exc)
        by_sector = {}

    # Concentration: top-5 by value.
    values = sorted(
        (
            (p.ticker, prices.get(p.ticker, p.cost_basis) * p.quantity)
            for p in positions
        ),
        key=lambda kv: -kv[1],
    )
    total_value = sum(v for _, v in values)
    top5 = values[:5]
    concentration_top5_pct = (
        sum(v for _, v in top5) / total_value if total_value > 0 else 0.0
    )

    return {
        "by_industry": {k: round(v, 2) for k, v in by_industry.items()},
        "by_sector": {k: round(v, 2) for k, v in by_sector.items()},
        "by_asset_class": {k: round(v, 2) for k, v in by_asset_class.items()},
        "concentration_top5_pct": round(concentration_top5_pct, 4),
        "total_value": round(total_value, 2),
        "positions_count": len(positions),
        "fetched_at": time.time(),
    }


# ── 4. allocation ───────────────────────────────────────────────────────────


@router.get("/portfolio/allocation")
def get_allocation() -> dict[str, Any]:
    """Asset class + concentration summary.

    Mirrors the inner numbers behind Tab 3 (配置), but as a single
    read-only call — the React page can hit this once and render the
    concentration banner + asset class pie without re-running the
    sector computation.
    """
    store = _store()
    positions = store.list_positions()
    tickers = sorted({p.ticker for p in positions})
    prices = _fetch_current_prices(tickers)

    by_asset_class: dict[str, float] = {}
    by_account: dict[str, float] = {}
    values: list[tuple[str, float]] = []
    total_value = 0.0
    total_cost = 0.0
    for p in positions:
        price = prices.get(p.ticker, p.cost_basis)
        value = float(price) * int(p.quantity)
        cost = float(p.cost_basis) * int(p.quantity)
        total_value += value
        total_cost += cost
        key = p.asset_class or "stock"
        by_asset_class[key] = by_asset_class.get(key, 0.0) + value
        by_account[p.account] = by_account.get(p.account, 0.0) + value
        values.append((p.ticker, value))

    values.sort(key=lambda kv: -kv[1])
    top5 = values[:5]
    concentration_top5_pct = (
        sum(v for _, v in top5) / total_value if total_value > 0 else 0.0
    )
    total_pnl_abs = total_value - total_cost
    total_pnl_pct = total_pnl_abs / total_cost if total_cost > 0 else 0.0

    return {
        "by_asset_class": {k: round(v, 2) for k, v in by_asset_class.items()},
        "by_account": {k: round(v, 2) for k, v in by_account.items()},
        "concentration_top5_pct": round(concentration_top5_pct, 4),
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl_abs": round(total_pnl_abs, 2),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "positions_count": len(positions),
        "fetched_at": time.time(),
    }


# ── 5/6. alerts ─────────────────────────────────────────────────────────────


@router.get("/portfolio/alerts")
def list_alerts(
    ticker: str = Query("", description="Optional ticker filter"),
    enabled_only: bool = Query(False, description="Only return enabled rules"),
) -> dict[str, Any]:
    """List alert rules.

    Mirrors ``PortfolioStore.list_alerts()`` and the Streamlit
    ``render_alerts_tab`` table on Tab 4.
    """
    store = _store()
    rules = store.list_alerts(
        ticker=ticker or None,
        enabled_only=enabled_only,
    )
    rows = [_alert_to_dict(r) for r in rules]
    return {
        "alerts": rows,
        "count": len(rows),
        "fetched_at": time.time(),
    }


@router.get("/portfolio/alerts/rules")
def list_alert_rules() -> dict[str, Any]:
    """Enumerate the 7 supported alert rule types (catalog).

    Mirrors the static list in ``portfolio_alerts_view.py`` + the
    ``VALID_ALERT_RULE_TYPES`` frozenset in ``portfolio_store.py``.
    """
    rule_types = [
        {
            "type": "price_above",
            "label": "现价突破",
            "description": "现价 ≥ 阈值时触发（看多突破）",
            "example": "现价突破 10.00",
        },
        {
            "type": "price_below",
            "label": "现价跌破",
            "description": "现价 ≤ 阈值时触发（看空跌破）",
            "example": "现价跌破 8.00",
        },
        {
            "type": "pct_change",
            "label": "日涨跌幅",
            "description": "当日涨跌幅绝对值 ≥ 阈值时触发（异动提醒）",
            "example": "日涨跌幅 ≥ 5%",
        },
        {
            "type": "pnl_pct",
            "label": "盈亏比例",
            "description": "当前盈亏 % ≥ 阈值时触发（盈/亏通知）",
            "example": "盈亏 % ≥ 20%（可为负）",
        },
        {
            "type": "take_profit",
            "label": "止盈",
            "description": "现价 ≥ 成本 × (1 + 阈值/100) 时触发",
            "example": "盈利 30% 时止盈",
        },
        {
            "type": "stop_loss",
            "label": "止损",
            "description": "现价 ≤ 成本 × (1 - 阈值/100) 时触发",
            "example": "亏损 10% 时止损",
        },
        {
            "type": "trailing_stop",
            "label": "移动止损",
            "description": "P2 stub —— 语义同 stop_loss，移动止损失留 P2 实现",
            "example": "回撤 5% 触发",
        },
    ]
    return {
        "rules": rule_types,
        "count": len(rule_types),
        "anti_repeat_window_sec": 300,
    }


@router.post("/portfolio/alerts/ack/{alert_id}")
def ack_alert(alert_id: str) -> dict[str, Any]:
    """Acknowledge an alert — disable the rule and stamp audit log.

    Mirrors the Streamlit 「确认预警」 action in Tab 4.  Idempotent: if the
    rule has already been disabled (enabled=False), we return success
    without re-writing.
    """
    store = _store()
    try:
        # Look up by rule_id first (so we can mark disabled + audit).
        all_rules = store.list_alerts()
        target = next((r for r in all_rules if r.rule_id == alert_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id!r} not found")
        if target.enabled:
            updated = store.update_alert(alert_id, enabled=False)
        else:
            updated = target
        return {
            "ok": True,
            "alert": _alert_to_dict(updated),
            "acked_at": time.time(),
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("ack_alert failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── 7. risk (XIRR / Sharpe / MaxDD / Brinson / 板块归因) ────────────────────


@router.get("/portfolio/risk")
def get_risk() -> dict[str, Any]:
    """XIRR / Sharpe / MaxDD / Brinson + 板块归因 composite.

    Mirrors Tab 6 (收益风险) in the Streamlit panel.  We expose the 4
    headline numbers + 板块归因 map so the React page can render the
    KPI cards + 归因饼图 in a single round-trip.
    """
    store = _store()
    positions = store.list_positions()
    transactions = store.list_transactions()
    tickers = sorted({p.ticker for p in positions})
    prices = _fetch_current_prices(tickers)

    # ── XIRR ─────────────────────────────────────────────────────────────
    xirr_value: float | None = None
    xirr_status: str = "no_data"
    try:
        from backend.core.portfolio_calc import compute_xirr
        current_value = sum(
            prices.get(p.ticker, p.cost_basis) * p.quantity for p in positions
        )
        if transactions and current_value > 0:
            result = compute_xirr(transactions, current_value=current_value)
            if result is not None and -0.99 < result < 10.0:
                xirr_value = round(float(result), 4)
                xirr_status = "ok"
            else:
                xirr_status = "no_convergence"
    except Exception as exc:  # noqa: BLE001
        logger.debug("compute_xirr failed: %s", exc)
        xirr_status = f"error: {exc}"

    # ── MaxDD ────────────────────────────────────────────────────────────
    max_drawdown: float | None = None
    max_drawdown_status: str = "no_data"
    try:
        from backend.core.portfolio_calc import compute_max_drawdown
        # Approximate equity curve via cost_value vs current_value
        cost_series = [float(p.cost_basis) * int(p.quantity) for p in positions]
        value_series = [
            prices.get(p.ticker, p.cost_basis) * p.quantity for p in positions
        ]
        if value_series:
            result = compute_max_drawdown(value_series)
            if result is not None:
                max_drawdown = round(float(result), 4)
                max_drawdown_status = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.debug("compute_max_drawdown failed: %s", exc)
        max_drawdown_status = f"error: {exc}"

    # ── Sharpe ───────────────────────────────────────────────────────────
    sharpe: float | None = None
    sharpe_status: str = "no_data"
    try:
        from backend.core.portfolio_calc import compute_sharpe
        returns = []
        for p in positions:
            cost = float(p.cost_basis)
            price = prices.get(p.ticker, cost)
            if cost > 0:
                returns.append((price - cost) / cost)
        if returns:
            result = compute_sharpe(returns, risk_free_rate=0.025)
            if result is not None:
                sharpe = round(float(result), 4)
                sharpe_status = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.debug("compute_sharpe failed: %s", exc)
        sharpe_status = f"error: {exc}"

    # ── Brinson ──────────────────────────────────────────────────────────
    brinson: dict[str, float] = {}
    brinson_status: str = "no_data"
    try:
        from backend.core.portfolio_calc import compute_brinson_attribution
        # Build a benchmark_returns dict from price-vs-cost for each ticker.
        # MVP: bench_returns default to 0 when no quote, so Brinson returns
        # 0 by design (positions × 0 weight). Still exercised so React page
        # can render the 5-row table.
        benchmark_returns: dict[str, float] = {}
        for p in positions:
            cost = float(p.cost_basis)
            price = prices.get(p.ticker, cost)
            benchmark_returns[p.ticker] = (price - cost) / cost if cost > 0 else 0.0
        if positions:
            result = compute_brinson_attribution(positions, benchmark_returns)
            if isinstance(result, dict):
                brinson = {k: round(float(v), 4) for k, v in result.items()}
                brinson_status = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.debug("compute_brinson_attribution failed: %s", exc)
        brinson_status = f"error: {exc}"

    # ── 板块归因 (group_by_sector) ───────────────────────────────────────
    sector_attribution: dict[str, float] = {}
    try:
        from backend.core.portfolio_calc import group_by_sector
        sector_attribution = group_by_sector(positions, prices) or {}
        sector_attribution = {k: round(float(v), 2) for k, v in sector_attribution.items()}
    except Exception as exc:  # noqa: BLE001
        logger.debug("group_by_sector (risk) failed: %s", exc)

    return {
        "xirr": xirr_value,
        "xirr_status": xirr_status,
        "sharpe": sharpe,
        "sharpe_status": sharpe_status,
        "max_drawdown": max_drawdown,
        "max_drawdown_status": max_drawdown_status,
        "brinson": brinson,
        "brinson_status": brinson_status,
        "sector_attribution": sector_attribution,
        "positions_count": len(positions),
        "transactions_count": len(transactions),
        "fetched_at": time.time(),
    }


# ── 8/9/10. import (4 CSV 格式 detect + UTF-8 BOM Excel) ───────────────────


@router.get("/portfolio/import/detect")
def detect_import_format(file_path: str = Query(..., description="Absolute path to CSV")) -> dict[str, Any]:
    """Detect which of the 4 supported CSV formats the file matches.

    Mirrors ``portfolio_import.detect_format()``.  Returns the format name
    (``eastmoney`` / ``ths`` / ``xueqiu`` / ``generic`` / ``unknown``).
    """
    from backend.core.portfolio_import import detect_format

    path = Path(file_path)
    # Path-traversal guard: refuse path with NUL bytes or shell-meta chars.
    if any(ch in file_path for ch in ("\x00", "\n", "\r")):
        raise HTTPException(status_code=400, detail="invalid file_path")
    if not path.is_absolute():
        raise HTTPException(status_code=400, detail="file_path must be absolute")

    try:
        fmt = detect_format(path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("detect_format failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "file_path": str(path),
        "format": fmt,
        "detected_at": time.time(),
    }


@router.post("/portfolio/import/preview")
async def preview_import(file: UploadFile = File(...)) -> dict[str, Any]:
    """Parse a multipart-uploaded CSV and return a preview (first 10 rows).

    Mirrors ``portfolio_import.preview_import()``.  The actual commit step
    is separate (``/portfolio/import/commit``) so users can review before
    persisting.
    """
    from backend.core.portfolio_import import detect_format, parse_csv

    # Persist the upload to a temp file because ``parse_csv`` expects a path.
    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".csv",
        delete=False,
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        fmt = detect_format(tmp_path)
        if fmt is None:
            raise HTTPException(status_code=400, detail="unknown CSV format")
        rows = parse_csv(tmp_path, fmt)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("preview_import failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    preview_rows = rows[:10]
    preview_hash = hashlib.md5(
        json.dumps(preview_rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "format": fmt,
        "total_rows": len(rows),
        "preview": preview_rows,
        "preview_hash": preview_hash,
        "detected_at": time.time(),
    }


@router.post("/portfolio/import/commit")
async def commit_import(
    file: UploadFile = File(...),
    format: str = Form(...),
) -> dict[str, Any]:
    """Commit a previously-previewed CSV import to the portfolio store.

    Mirrors ``portfolio_import.apply_import()``.  The CSV is parsed and
    applied; counts (inserted/skipped/errors) are returned for the React UI
    to show a confirmation banner.
    """
    from backend.core.portfolio_import import apply_import, parse_csv

    if format not in ("eastmoney", "ths", "xueqiu", "generic"):
        raise HTTPException(
            status_code=400,
            detail=f"invalid format {format!r}; expected one of eastmoney/ths/xueqiu/generic",
        )

    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".csv",
        delete=False,
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        rows = parse_csv(tmp_path, format)
        result = apply_import(rows)
    except Exception as exc:  # noqa: BLE001
        logger.exception("commit_import failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    # ``apply_import`` returns either a dict or a number; normalize.
    if isinstance(result, dict):
        inserted = int(result.get("inserted", 0))
        skipped = int(result.get("skipped", 0))
        errors = result.get("errors", [])
    else:
        inserted = int(result or 0)
        skipped = 0
        errors = []

    return {
        "ok": True,
        "format": format,
        "inserted": inserted,
        "skipped": skipped,
        "errors": errors,
        "committed_at": time.time(),
    }


# ── 11. export ──────────────────────────────────────────────────────────────


@router.get("/portfolio/export")
def export_portfolio(
    format: str = Query("positions", description="positions | transactions"),
) -> Response:
    """Export positions or transactions as CSV with UTF-8 BOM (Excel-friendly).

    Mirrors ``portfolio_import.export_csv()`` and ``export_transactions_csv()``.
    """
    store = _store()
    if format == "positions":
        positions = store.list_positions()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ticker", "name", "cost_basis", "quantity",
            "first_buy_date", "last_trade_date", "account",
            "asset_class", "notes", "created_at",
        ])
        for p in positions:
            writer.writerow([
                p.ticker, p.name, p.cost_basis, p.quantity,
                p.first_buy_date, p.last_trade_date, p.account,
                p.asset_class, p.notes, p.created_at,
            ])
        body = output.getvalue()
        filename = "portfolio_positions.csv"
    elif format == "transactions":
        transactions = store.list_transactions()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "tx_id", "position_id", "ticker", "date", "action",
            "price", "quantity", "fees", "notes", "created_at",
        ])
        for t in transactions:
            writer.writerow([
                t.tx_id, t.position_id, t.ticker, t.date, t.action,
                t.price, t.quantity, t.fees, t.notes, t.created_at,
            ])
        body = output.getvalue()
        filename = "portfolio_transactions.csv"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"invalid format {format!r}; expected 'positions' or 'transactions'",
        )

    # UTF-8 BOM + body.  Excel needs the BOM to detect UTF-8 properly.
    csv_bytes = b"\xef\xbb\xbf" + body.encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Portfolio-Export-Format": format,
        },
    )


__all__ = ["router"]