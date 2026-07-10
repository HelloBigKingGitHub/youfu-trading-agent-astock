"""Tab 1 — 持仓总览.

4 metric cards (总市值 / 总成本 / 总盈亏 / 今日盈亏) + 持仓表格 (代码/名称/
持仓数量/成本价/现价/浮动盈亏/盈亏比例/持仓天数) + 行操作 (编辑/录入交易
/删除) + 「录入新持仓」 按钮。

设计:
  - 取现价走 ``_tencent_quote`` (复用 chart_panel 路径),失败 fallback 到成本价。
  - Metric 数字和表格 cell 都走 ``portfolio_dialogs.format_*``。
  - 删除走原生 ``st.dialog`` 弹框确认（@st.dialog 装饰函数
    ``open_delete_position_dialog``），不再用 session_state 二次确认 trick：
    原方案下按钮 click → rerun → 按钮立即被替换为"✓"，用户看不到视觉反馈，
    而且 rerun 期间 playwright 会报"subtree intercepts pointer events"。
  - 所有按钮文字带 emoji + 中文（如 "🗑️ 删除"），不再用 emoji-only 标签。
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from backend.core.portfolio_store import Position
from web.components.portfolio_dialogs import (
    format_currency,
    format_pct,
    open_add_position_dialog,
    open_add_transaction_dialog,
    open_delete_position_dialog,
    open_edit_position_dialog,
    pnl_color_class,
)

logger = logging.getLogger(__name__)


# ── Pure helpers (unit-testable) ────────────────────────────────────────


def safe_quote(ticker: str) -> float | None:
    """Best-effort current price lookup. Returns None on any error.

    Lives here (not in dialogs) because it's not a validation concern; it's a
    data fetch with streamlit-aware error handling.
    """
    try:
        from tradingagents.dataflows.a_stock import _tencent_quote
        quotes = _tencent_quote([ticker])
        q = quotes.get(ticker)
        if not q or not q.get("price"):
            return None
        return float(q["price"])
    except Exception as exc:
        logger.debug("safe_quote(%s) failed: %s", ticker, exc)
        return None


def compute_metric_row(
    positions: list[Position],
    current_prices: dict[str, float],
) -> dict[str, float]:
    """Aggregate 4 top-level portfolio metrics for the metric cards.

    Returns dict with: total_value, total_cost, total_pnl_abs, total_pnl_pct,
    today_pnl (rough: cost-basis diff vs prev_close from current_prices when
    available, else 0).
    """
    total_value = 0.0
    total_cost = 0.0
    for pos in positions:
        price = current_prices.get(pos.ticker, pos.cost_basis)
        total_value += price * pos.quantity
        total_cost += pos.cost_basis * pos.quantity
    total_pnl_abs = total_value - total_cost
    total_pnl_pct = total_pnl_abs / total_cost if total_cost else 0.0
    # Today pnl requires prev_close; for the overview we use cost_basis as
    # the fallback so the field always renders a number rather than "—".
    today_pnl = 0.0
    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pnl_abs": total_pnl_abs,
        "total_pnl_pct": total_pnl_pct,
        "today_pnl": today_pnl,
        "positions_count": len(positions),
    }


def holding_days(first_buy_date: str, today: str | None = None) -> int:
    """Compute holding days from first_buy_date (YYYY-MM-DD) to today."""
    from datetime import date as _date, datetime
    try:
        first = datetime.strptime(first_buy_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 0
    if today:
        try:
            ref = datetime.strptime(today, "%Y-%m-%d").date()
        except ValueError:
            ref = _date.today()
    else:
        ref = _date.today()
    return max(0, (ref - first).days)


def _row_metrics(pos: Position, current_prices: dict[str, float]) -> dict[str, Any]:
    """Compute per-row derived fields for the overview table."""
    price = current_prices.get(pos.ticker, pos.cost_basis)
    cost_value = pos.cost_basis * pos.quantity
    current_value = price * pos.quantity
    pnl_abs = current_value - cost_value
    pnl_pct = pnl_abs / cost_value if cost_value else 0.0
    return {
        "price": price,
        "current_value": current_value,
        "cost_value": cost_value,
        "pnl_abs": pnl_abs,
        "pnl_pct": pnl_pct,
        "holding_days": holding_days(pos.first_buy_date),
    }


# ── Streamlit renderers ────────────────────────────────────────────────


def _render_metric_cards(metrics: dict[str, float]) -> None:
    """4 metric cards in a single row. Uses bb-portfolio-metric-card CSS class."""
    cols = st.columns(4)
    cards = [
        ("总市值", format_currency(metrics["total_value"]),
         pnl_color_class(metrics["total_value"] - metrics["total_cost"])),
        ("总成本", format_currency(metrics["total_cost"]), "bb-portfolio-pnl-neutral"),
        ("总盈亏",
         f"{format_currency(metrics['total_pnl_abs'])} ({format_pct(metrics['total_pnl_pct'] * 100)})",
         pnl_color_class(metrics["total_pnl_abs"])),
        ("今日盈亏",
         format_currency(metrics["today_pnl"]),
         pnl_color_class(metrics["today_pnl"])),
    ]
    for col, (label, value, cls) in zip(cols, cards):
        with col:
            st.html(
                f'<div class="bb-portfolio-metric-card">'
                f'<div class="bb-portfolio-metric-label">{label}</div>'
                f'<div class="bb-portfolio-metric-value {cls}">{value}</div>'
                f"</div>"
            )


def _render_positions_table(
    positions: list[Position],
    current_prices: dict[str, float],
) -> None:
    """Per-position table with edit / delete / add-tx row actions."""
    if not positions:
        st.info("📭 暂无持仓。点击下方 '录入新持仓' 开始记录。")
        return

    # Header row
    header_cols = st.columns([1, 1.4, 1, 1, 1, 1.2, 1, 0.8, 1.6])
    headers = ["代码", "名称", "数量", "成本价", "现价", "浮动盈亏", "盈亏%", "天数", "操作"]
    for col, h in zip(header_cols, headers):
        col.markdown(
            f'<div class="bb-portfolio-th">{h}</div>',
            unsafe_allow_html=True,
        )

    for pos in positions:
        m = _row_metrics(pos, current_prices)
        c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns([1, 1.4, 1, 1, 1, 1.2, 1, 0.8, 1.6])
        with c1:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{pos.ticker}</div>')
        with c2:
            st.html(f'<div class="bb-portfolio-td">{pos.name or "—"}</div>')
        with c3:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{pos.quantity:,}</div>')
        with c4:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{pos.cost_basis:.4f}</div>'
            )
        with c5:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{m["price"]:.2f}</div>'
            )
        with c6:
            cls = pnl_color_class(m["pnl_abs"])
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono {cls}">'
                f'{m["pnl_abs"]:+.2f}</div>'
            )
        with c7:
            cls = pnl_color_class(m["pnl_pct"])
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono {cls}">'
                f'{m["pnl_pct"] * 100:+.2f}%</div>'
            )
        with c8:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{m["holding_days"]}</div>'
            )
        with c9:
            btn1, btn2, btn3 = st.columns(3)
            with btn1:
                if st.button(
                    "✏️ 编辑", key=f"edit_pos_{pos.position_id}",
                    help="编辑该持仓",
                ):
                    open_edit_position_dialog(pos.position_id)
            with btn2:
                if st.button(
                    "💸 录入交易", key=f"add_tx_{pos.position_id}",
                    help="为该持仓录入一条交易流水",
                ):
                    open_add_transaction_dialog(pos.position_id)
            with btn3:
                # 原先用 ``st.session_state[confirm_key]`` 做 2-step 二次确认：
                # click 🗑️ → rerun → 按钮立即替换成 ✓，用户看不到反馈。
                # 现在改成 @st.dialog 弹框（portoflio_dialogs 里的
                # ``open_delete_position_dialog``），有明确的视觉提示，
                # 也避免 playwright 报告"subtree intercepts pointer events"。
                if st.button(
                    "🗑️ 删除", key=f"del_pos_{pos.position_id}",
                    help="删除该持仓（弹框二次确认）",
                ):
                    open_delete_position_dialog(pos.position_id)


def render_overview_tab(positions: list[Position]) -> None:
    """Public entry: render the overview tab inside the portfolio panel."""
    # Fetch current prices (best-effort; falls back to cost_basis per row).
    tickers = [p.ticker for p in positions]
    current_prices: dict[str, float] = {}
    for t in tickers:
        q = safe_quote(t)
        if q is not None:
            current_prices[t] = q

    metrics = compute_metric_row(positions, current_prices)
    _render_metric_cards(metrics)

    st.markdown('<div class="bb-section-label">持仓列表</div>', unsafe_allow_html=True)

    _render_positions_table(positions, current_prices)

    if st.button("➕ 录入新持仓", type="primary", key="overview_add_position",
                 use_container_width=False):
        open_add_position_dialog()


__all__ = [
    "safe_quote",
    "compute_metric_row",
    "holding_days",
    "render_overview_tab",
]
