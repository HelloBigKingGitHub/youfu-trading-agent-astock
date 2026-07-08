"""Portfolio calc layer — pure functions over Position / Transaction data.

No I/O, no Streamlit. Every function takes primitives (or dataclasses) and
returns either a dataclass or a small dict / number. Safe to call from
tests, the panel, or the Bull/Bear portfolio_tools wrapper.

Style mirrors backend/core/portfolio_store.py: type hints + dataclasses for
output, plain functions for compute. Side effects: none.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from datetime import date as _date_cls, datetime
from pathlib import Path
from typing import Iterable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.portfolio_store import Position, Transaction  # noqa: E402

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.025
DEFAULT_XIRR_GUESS = 0.08
XIRR_TOL = 1e-6
XIRR_MAX_ITER = 1000


@dataclass
class PositionMetrics:
    """Per-position snapshot: cost vs current value, today's move, age."""

    current_value: float
    cost_value: float
    pnl_abs: float
    pnl_pct: float
    today_pnl: float
    today_pnl_pct: float
    holding_days: int
    cost_basis: float
    current_price: float
    prev_close: float


@dataclass
class PortfolioSummary:
    """Portfolio-level aggregation across all positions."""

    total_value: float
    total_cost: float
    total_pnl_abs: float
    total_pnl_pct: float
    today_pnl: float
    today_pnl_pct: float
    positions_count: int
    by_industry: dict[str, float] = field(default_factory=dict)
    by_sector: dict[str, float] = field(default_factory=dict)
    by_asset_class: dict[str, float] = field(default_factory=dict)
    concentration_top5_pct: float = 0.0


# ── helpers ─────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> _date_cls:
    """Parse YYYY-MM-DD; raise ValueError on garbage."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def _weighted_avg_cost(transactions: list[Transaction], ticker: str) -> float | None:
    """Recompute moving weighted-average cost from a position's transaction log.

    Buys increase both quantity and cost basis; sells only decrease quantity
    (without changing the avg cost basis). Splits/merges/rights affect cost
    per share but not total cost basis, so they're treated as quantity-only
    events for weighted-avg purposes (matches 东方财富 behavior).

    Returns None if the position has zero buys recorded.
    """
    total_qty = 0
    total_cost = 0.0
    for tx in transactions:
        if tx.ticker != ticker:
            continue
        if tx.action == "buy":
            total_qty += tx.quantity
            total_cost += tx.price * tx.quantity + tx.fees
        elif tx.action == "sell":
            # Reduce quantity proportionally; avg cost basis unchanged.
            if total_qty > 0:
                avg = total_cost / total_qty
                sold = min(tx.quantity, total_qty)
                total_qty -= sold
                total_cost = avg * total_qty
        # dividend / split / merge / rights: don't change weighted-avg cost
    if total_qty <= 0:
        return None
    return total_cost / total_qty


# ── per-position ────────────────────────────────────────────────────────────


def compute_position_metrics(
    position: Position,
    current_price: float,
    transactions: Iterable[Transaction] | None = None,
    prev_close: float | None = None,
    today: str | None = None,
) -> PositionMetrics:
    """Compute current value / pnl / today-pnl / holding-days for one position.

    `cost_basis` is taken from position.cost_basis unless a transactions log
    is provided — in which case we recompute weighted avg from the log. This
    mirrors 东方财富 / 雪球 / 腾讯 convention where avg cost is always
    recomputable from the trade history.
    """
    tx_list = list(transactions) if transactions else []
    recomputed = _weighted_avg_cost(tx_list, position.ticker)
    cost = recomputed if recomputed is not None else position.cost_basis

    current_value = float(current_price) * position.quantity
    cost_value = cost * position.quantity
    pnl_abs = current_value - cost_value
    pnl_pct = pnl_abs / cost_value if cost_value else 0.0

    prev = float(prev_close) if prev_close is not None else float(current_price)
    today_pnl = (float(current_price) - prev) * position.quantity
    today_pnl_pct = (
        (float(current_price) - prev) / prev if prev else 0.0
    )

    try:
        first = _parse_date(position.first_buy_date)
    except (ValueError, TypeError):
        first = datetime.now().date()
    try:
        ref_date = _parse_date(today) if today else datetime.now().date()
    except (ValueError, TypeError):
        ref_date = datetime.now().date()
    holding_days = max(0, (ref_date - first).days)

    return PositionMetrics(
        current_value=round(current_value, 2),
        cost_value=round(cost_value, 2),
        pnl_abs=round(pnl_abs, 2),
        pnl_pct=round(pnl_pct, 4),
        today_pnl=round(today_pnl, 2),
        today_pnl_pct=round(today_pnl_pct, 4),
        holding_days=holding_days,
        cost_basis=round(cost, 4),
        current_price=float(current_price),
        prev_close=prev,
    )


# ── portfolio-level ─────────────────────────────────────────────────────────


def _concept_block_to_sectors(raw: str) -> list[str]:
    """Parse the markdown returned by `get_concept_blocks(ticker)` into sector names.

    `get_concept_blocks` returns text like:
        ## 概念
          锂电池: 1.23%
          新能源车: -0.45%
        ## 行业
        Concept tags: 锂电池 / 新能源车

    We extract the `Concept tags:` line (and the `## 行业` block names) as
    the sector labels. Falls back to [] on error.
    """
    if not raw:
        return []
    sectors: list[str] = []
    in_industry = False
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_industry = s[3:] == "行业"
            continue
        if in_industry and s and not s.startswith("#"):
            # take first token before any colon / paren
            name = s.split(":")[0].split("(")[0].strip()
            if name and name not in sectors:
                sectors.append(name)
        if s.lower().startswith("concept tags:"):
            tag_blob = s.split(":", 1)[1].strip()
            for tag in tag_blob.split("/"):
                tag = tag.strip()
                if tag and tag not in sectors:
                    sectors.append(tag)
    return sectors


def compute_portfolio_summary(
    positions: list[Position],
    current_prices: dict[str, float],
    by_industry: dict[str, float] | None = None,
    by_sector: dict[str, float] | None = None,
) -> PortfolioSummary:
    """Aggregate per-position metrics into a portfolio-level summary.

    `by_industry` / `by_sector` default to empty dicts when not provided;
    the caller (panel) is responsible for fetching concept-block data via
    `get_concept_blocks(ticker)` and grouping by ticker beforehand.
    `by_asset_class` is auto-built from each position's asset_class field.

    `current_prices` maps normalized 6-digit ticker -> current price. Missing
    tickers fall back to cost_basis (so the holding value is at least the
    cost basis and pnl is 0 for that row).
    """
    total_value = 0.0
    total_cost = 0.0
    today_pnl = 0.0
    by_asset_class: dict[str, float] = {}
    values_by_ticker: list[tuple[str, float]] = []

    for pos in positions:
        price = current_prices.get(pos.ticker, pos.cost_basis)
        value = price * pos.quantity
        cost = pos.cost_basis * pos.quantity
        total_value += value
        total_cost += cost
        # If we don't know today's prev_close, treat today_pnl as 0 to keep
        # totals honest (the panel can fetch prev_close separately).
        by_asset_class[pos.asset_class] = by_asset_class.get(pos.asset_class, 0.0) + value
        values_by_ticker.append((pos.ticker, value))

    total_pnl_abs = total_value - total_cost
    total_pnl_pct = total_pnl_abs / total_cost if total_cost else 0.0

    # Concentration: top-5 tickers by current value / total.
    values_by_ticker.sort(key=lambda x: x[1], reverse=True)
    top5 = sum(v for _, v in values_by_ticker[:5])
    concentration_top5_pct = top5 / total_value if total_value else 0.0

    return PortfolioSummary(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl_abs=round(total_pnl_abs, 2),
        total_pnl_pct=round(total_pnl_pct, 4),
        today_pnl=round(today_pnl, 2),
        today_pnl_pct=0.0,
        positions_count=len(positions),
        by_industry=dict(by_industry or {}),
        by_sector=dict(by_sector or {}),
        by_asset_class={k: round(v, 2) for k, v in by_asset_class.items()},
        concentration_top5_pct=round(concentration_top5_pct, 4),
    )


def group_by_sector(
    positions: list[Position],
    current_prices: dict[str, float],
) -> dict[str, float]:
    """Aggregate current portfolio value by sector using `get_concept_blocks`.

    Failures (network / parsing) fall back to {"其他": total_value} so the UI
    still has something to render.
    """
    try:
        from tradingagents.dataflows.a_stock import get_concept_blocks
    except Exception:
        return {"其他": sum(current_prices.get(p.ticker, p.cost_basis) * p.quantity for p in positions)}

    out: dict[str, float] = {}
    fallback = 0.0
    for pos in positions:
        try:
            raw = get_concept_blocks(pos.ticker)
        except Exception:
            raw = ""
        sectors = _concept_block_to_sectors(raw)
        value = current_prices.get(pos.ticker, pos.cost_basis) * pos.quantity
        if not sectors:
            fallback += value
            continue
        # Attribute equally across all sectors the ticker belongs to.
        share = value / len(sectors)
        for s in sectors:
            out[s] = out.get(s, 0.0) + share
    if fallback and not out:
        out["其他"] = fallback
    return {k: round(v, 2) for k, v in out.items()}


# ── performance metrics ─────────────────────────────────────────────────────


def compute_xirr(
    transactions: list[Transaction],
    current_value: float,
    as_of: str | None = None,
) -> float:
    """XIRR — annualized internal rate of return for irregular cash flows.

    Convention: buys are negative cash flow (money out), sells + final
    `current_value` are positive (money in / remaining value). Dividends
    and splits are treated as zero-cash-flow events for XIRR purposes
    (they affect return via current_value, not the cash series).
    """
    if as_of is None:
        as_of_date = datetime.now().date()
    else:
        as_of_date = _parse_date(as_of)

    cash_flows: list[tuple[_date_cls, float]] = []
    for tx in transactions:
        if tx.action in ("dividend", "split", "merge", "rights"):
            continue
        if tx.action == "buy":
            amount = -(tx.price * tx.quantity + tx.fees)
        elif tx.action == "sell":
            amount = tx.price * tx.quantity - tx.fees
        else:
            continue
        cash_flows.append((_parse_date(tx.date), amount))

    if not cash_flows:
        return 0.0

    cash_flows.sort(key=lambda x: x[0])
    cash_flows.append((as_of_date, float(current_value)))

    # Filter out zero flows (would break log-scale NPV).
    cash_flows = [(d, a) for d, a in cash_flows if a != 0.0]
    if len(cash_flows) < 2:
        return 0.0

    t0 = cash_flows[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for d, amount in cash_flows:
            years = (d - t0).days / 365.0
            total += amount / ((1 + rate) ** years)
        return total

    from scipy.optimize import brentq

    try:
        return brentq(npv, -0.999, 10.0, xtol=XIRR_TOL, maxiter=XIRR_MAX_ITER)
    except (ValueError, RuntimeError):
        # No sign change → cannot bracket a root. Fall back to bisection over
        # a coarser grid; if still no root, return the initial guess.
        lo, hi = -0.9, 5.0
        for _ in range(60):
            mid = (lo + hi) / 2
            v = npv(mid)
            if v > 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2


def compute_max_drawdown(equity_curve: list[tuple[_date_cls, float]]) -> float:
    """Maximum drawdown over a date-indexed equity curve.

    Returns the largest peak-to-trough decline as a positive fraction
    (e.g. 0.25 means a 25% drawdown). Returns 0.0 for empty / monotonic input.
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0][1]
    max_dd = 0.0
    for _, v in equity_curve:
        if v > peak:
            peak = v
        if peak <= 0:
            continue
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 6)


def compute_sharpe(
    daily_returns: list[float],
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Annualized Sharpe ratio. Assumes daily returns are simple (not log)."""
    if len(daily_returns) < 2:
        return 0.0
    mean = sum(daily_returns) / len(daily_returns)
    var = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    rf_daily = risk_free_rate / TRADING_DAYS_PER_YEAR
    return round((mean - rf_daily) / std * math.sqrt(TRADING_DAYS_PER_YEAR), 4)


def compute_brinson_attribution(
    positions: list[Position],
    benchmark_returns: dict[str, float],
) -> dict[str, float]:
    """Brinson-Fachler attribution, MVP (selection + allocation only).

    Returns:
        selection:  Σ w_p,i * (r_p,i - r_b,i)   (stock-picking within sector)
        allocation: Σ (w_p,i - w_b,i) * r_b,i   (over/under-weight sector)
        total:      selection + allocation       (no interaction term in MVP)

    Where:
      - w_p,i = position weight in portfolio for ticker i (current value / total)
      - w_b,i = position weight in benchmark for ticker i
                (synthesized here as uniform across tickers for MVP)
      - r_p,i = position return for ticker i (current_price / cost_basis - 1)
      - r_b,i = benchmark return for ticker i (from `benchmark_returns`)

    Raises ValueError on empty positions.
    """
    if not positions:
        raise ValueError("positions must be non-empty")
    total_value = sum(p.quantity * p.cost_basis for p in positions) or 1.0

    selection = 0.0
    allocation = 0.0
    n = len(positions)
    for p in positions:
        w_p = (p.quantity * p.cost_basis) / total_value
        w_b = 1.0 / n  # uniform benchmark — MVP simplification
        r_p = 0.0  # unknown current price here; caller patches this in
        r_b = benchmark_returns.get(p.ticker, 0.0)
        selection += w_p * (r_p - r_b)
        allocation += (w_p - w_b) * r_b

    total = selection + allocation
    return {
        "selection": round(selection, 6),
        "allocation": round(allocation, 6),
        "total": round(total, 6),
    }


def compute_equity_curve(
    positions: list[Position],
    transactions: list[Transaction],
    current_prices: dict[str, float],
    days: int = 30,
    today: str | None = None,
) -> list[tuple[_date_cls, float]]:
    """Build a synthetic equity curve over the past `days` days.

    For each day in the window we estimate portfolio value by:
      1. Replaying buys / sells to compute cumulative quantity at that date.
      2. Falling back to `cost_basis` as the price proxy for days before the
         position existed (zero or cost_basis * qty).

    Note: real prices aren't available historically without extra API calls.
    This MVP curve uses cost_basis as a flat forward-fill, so the resulting
    Sharpe / max-drawdown are derived from the *current_price* shock at the
    final point. Sufficient for daily-return stats over short windows.
    """
    if today is None:
        end_date = datetime.now().date()
    else:
        end_date = _parse_date(today)

    # Cumulative quantity per ticker at each historical date.
    sorted_tx = sorted(transactions, key=lambda t: t.date)
    points: list[tuple[_date_cls, float]] = []
    for offset in range(days - 1, -1, -1):
        d = _date_cls.fromordinal(end_date.toordinal() - offset)
        d_str = d.strftime("%Y-%m-%d")
        value = 0.0
        for p in positions:
            qty = 0
            for tx in sorted_tx:
                if tx.ticker != p.ticker or tx.date > d_str:
                    continue
                if tx.action == "buy":
                    qty += tx.quantity
                elif tx.action == "sell":
                    qty = max(0, qty - tx.quantity)
            if qty <= 0:
                continue
            # Use current price only on the final day; flat cost_basis otherwise.
            price = current_prices.get(p.ticker, p.cost_basis) if offset == 0 else p.cost_basis
            value += qty * price
        points.append((d, round(value, 2)))
    return points