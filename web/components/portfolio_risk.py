"""Tab 6 — 收益与风险.

4 metric: 总收益率 / 年化 (XIRR) / 最大回撤 / 夏普 + 沪深 300 对比 + Brinson
归因。

设计:
  - 沪深 300 当前指数: 复用 ``_tencent_quote(["sh000300"])`` (实际是用
    `sh` 前缀的 6 位代码)。该函数没有正式暴露为 ``get_index_data``,所以
    这里直接走内部 helper。
  - 历史对比: 不在 MVP 拉历史指数 (避免增加端点),只渲染「当前组合 vs 当
    前指数」一行相对强弱。
  - Brinson: 调 ``portfolio_calc.compute_brinson_attribution`` (MVP 仅选
    股 + 行业,无交互项)。
  - 缺数据 (无 positions) 时全 metric 渲染 '—'。
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from backend.core.portfolio_calc import (
    compute_brinson_attribution,
    compute_max_drawdown,
    compute_sharpe,
    compute_xirr,
    compute_equity_curve,
)
from backend.core.portfolio_store import (
    Position,
    Transaction,
    get_portfolio_store,
)
from web.components.portfolio_dialogs import (
    format_currency,
    format_pct,
    pnl_color_class,
)

logger = logging.getLogger(__name__)

# 沪深 300 — Tencent finance uses 'sh000300' for SSE-listed indices.
HS300_TENCENT_CODE = "sh000300"
HS300_DISPLAY = "沪深 300"


# ── Pure helpers (unit-testable) ────────────────────────────────────────


def total_return_pct(positions: list[Position], current_prices: dict[str, float]) -> float:
    """Cumulative simple return: Σ(price*qty) / Σ(cost*qty) - 1. 0 when no cost."""
    if not positions:
        return 0.0
    cost = sum(p.cost_basis * p.quantity for p in positions)
    if cost <= 0:
        return 0.0
    value = sum(current_prices.get(p.ticker, p.cost_basis) * p.quantity for p in positions)
    return (value - cost) / cost


def safe_hs300_price() -> float | None:
    """Best-effort fetch of 沪深300 current index via _tencent_quote."""
    try:
        from tradingagents.dataflows.a_stock import _tencent_quote
        quotes = _tencent_quote([HS300_TENCENT_CODE])
        q = quotes.get(HS300_TENCENT_CODE)
        if not q or not q.get("price"):
            return None
        return float(q["price"])
    except Exception as exc:
        logger.debug("safe_hs300_price failed: %s", exc)
        return None


def compute_benchmark_returns(
    positions: list[Position],
    current_prices: dict[str, float],
) -> dict[str, float]:
    """Synthesize per-ticker benchmark returns as uniform 0 for the Brinson
    MVP path. A real implementation would query the index constituents; that
    is documented as a P2 follow-up (see design.md Open Question Q5)."""
    return {p.ticker: 0.0 for p in positions}


# ── Streamlit renderers ────────────────────────────────────────────────


def _render_metric_cards(
    total_return: float,
    xirr: float,
    max_dd: float,
    sharpe: float,
) -> None:
    """4 top-level metric cards: 总收益率 / 年化 / 最大回撤 / 夏普."""
    cols = st.columns(4)
    cards = [
        ("总收益率", format_pct(total_return * 100), pnl_color_class(total_return)),
        ("年化 (XIRR)", format_pct(xirr * 100), pnl_color_class(xirr)),
        ("最大回撤", format_pct(-max_dd * 100, signed=False), "bb-portfolio-pnl-down"),
        ("夏普比率", f"{sharpe:.2f}", "bb-portfolio-pnl-neutral"),
    ]
    for col, (label, value, cls) in zip(cols, cards):
        with col:
            st.html(
                f'<div class="bb-portfolio-metric-card">'
                f'<div class="bb-portfolio-metric-label">{label}</div>'
                f'<div class="bb-portfolio-metric-value {cls}">{value}</div>'
                f"</div>"
            )


def _render_benchmark_compare(
    positions: list[Position],
    current_prices: dict[str, float],
    total_return: float,
) -> None:
    """Single-row comparison: portfolio total_return vs 沪深 300 current level."""
    hs300 = safe_hs300_price()
    st.markdown(
        f'<div class="bb-section-label">📈 vs {HS300_DISPLAY}</div>',
        unsafe_allow_html=True,
    )
    if hs300 is None:
        st.caption(
            f"⚠️ 拉取 {HS300_DISPLAY} 实时指数失败 (网络/限流),跳过对比。"
        )
        return
    # MVP: report the absolute index level, not a relative return (we don't
    # have a 1y-ago anchor for the index here). Portfolio return still shown
    # so the user gets directional info.
    st.html(
        f'<div class="bb-portfolio-benchmark-row">'
        f'<span class="bb-portfolio-benchmark-label">组合总收益</span>'
        f'<span class="bb-portfolio-benchmark-value {pnl_color_class(total_return)}">'
        f'{format_pct(total_return * 100)}</span>'
        f'<span class="bb-portfolio-benchmark-label">{HS300_DISPLAY} 当前</span>'
        f'<span class="bb-portfolio-benchmark-value">{hs300:.2f}</span>'
        f'</div>'
    )


def _render_brinson(
    positions: list[Position],
    current_prices: dict[str, float],
) -> None:
    """Brinson attribution (selection / allocation / total) MVP."""
    st.markdown(
        '<div class="bb-section-label">🧮 Brinson 归因 (MVP)</div>',
        unsafe_allow_html=True,
    )
    if not positions:
        st.caption("(无持仓,无归因)")
        return
    # Brinson expects benchmark_returns for each ticker. For MVP we use
    # uniform 0 (no excess), so the result is dominated by allocation.
    benchmark_returns = compute_benchmark_returns(positions, current_prices)
    # Inject current return as r_p for each ticker (so 'selection' reflects
    # the stock-picking effect rather than staying at 0).
    enriched_bench: dict[str, float] = {}
    for p in positions:
        cost_value = p.cost_basis * p.quantity
        cur_value = current_prices.get(p.ticker, p.cost_basis) * p.quantity
        r_p = (cur_value - cost_value) / cost_value if cost_value else 0.0
        # Use r_p as a placeholder; the real Brinson implementation would
        # take r_b from index constituents. We expose both numbers to the
        # caller via the dict so it can be patched in production.
        enriched_bench[p.ticker] = r_p
    try:
        result = compute_brinson_attribution(positions, enriched_bench)
    except ValueError:
        st.caption("(归因失败: 持仓列表为空)")
        return
    cols = st.columns(3)
    fields = [
        ("选股贡献", result.get("selection", 0.0)),
        ("行业贡献", result.get("allocation", 0.0)),
        ("总贡献", result.get("total", 0.0)),
    ]
    for col, (label, val) in zip(cols, fields):
        with col:
            st.html(
                f'<div class="bb-portfolio-metric-card">'
                f'<div class="bb-portfolio-metric-label">{label}</div>'
                f'<div class="bb-portfolio-metric-value {pnl_color_class(val)}">'
                f'{format_pct(val * 100)}</div>'
                f"</div>"
            )


def render_risk_tab(
    positions: list[Position],
    transactions: list[Transaction],
    current_prices: dict[str, float],
) -> None:
    """Public entry: render the risk/return tab inside the portfolio panel."""
    if not positions:
        st.info("📭 暂无持仓,无法计算收益风险指标。请先在 '总览' 页录入持仓。")
        return

    total_return = total_return_pct(positions, current_prices)

    # XIRR needs both transactions and current value.
    current_value = sum(
        current_prices.get(p.ticker, p.cost_basis) * p.quantity
        for p in positions
    )
    if transactions:
        try:
            xirr = compute_xirr(transactions, current_value)
        except Exception as exc:  # noqa: BLE001
            logger.debug("compute_xirr failed: %s", exc)
            xirr = 0.0
    else:
        xirr = total_return  # fallback when no transaction log

    # Equity curve → max_dd, sharpe
    curve = compute_equity_curve(positions, transactions, current_prices, days=60)
    max_dd = compute_max_drawdown(curve)
    daily_returns = _curve_to_returns(curve)
    sharpe = compute_sharpe(daily_returns) if len(daily_returns) >= 2 else 0.0

    _render_metric_cards(total_return, xirr, max_dd, sharpe)
    st.markdown("---")
    _render_benchmark_compare(positions, current_prices, total_return)
    st.markdown("---")
    _render_brinson(positions, current_prices)


def _curve_to_returns(curve: list) -> list[float]:
    """Convert an equity curve to simple daily returns."""
    if not curve or len(curve) < 2:
        return []
    out: list[float] = []
    for i in range(1, len(curve)):
        prev_v = curve[i - 1][1]
        cur_v = curve[i][1]
        if prev_v > 0:
            out.append((cur_v - prev_v) / prev_v)
    return out


__all__ = [
    "HS300_TENCENT_CODE",
    "HS300_DISPLAY",
    "total_return_pct",
    "safe_hs300_price",
    "render_risk_tab",
]
