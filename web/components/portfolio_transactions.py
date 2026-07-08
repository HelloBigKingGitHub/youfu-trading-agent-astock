"""Tab 2 — 交易流水.

按 ticker / 时间筛选的交易表 + 「录入新交易」 按钮 (按 position_id 选)。

设计:
  - 排序: 默认按 date desc (跟 store.list_transactions 一致)。
  - 筛选: ticker (下拉) + since (date_input) 两个独立 filter。
  - 「录入新交易」 按钮用 session_state 中的 dialog entry,复用 ``portfolio_dialogs``。
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

import streamlit as st

from backend.core.portfolio_store import Position, Transaction
from web.components.portfolio_dialogs import (
    TX_ACTION_LABELS,
    format_currency,
    open_add_transaction_dialog,
)


# ── Pure helpers (unit-testable) ────────────────────────────────────────


def filter_transactions(
    transactions: list[Transaction],
    ticker: str | None = None,
    since: str | None = None,
) -> list[Transaction]:
    """Pure in-memory filter — same semantics as store.list_transactions
    but operates on a pre-loaded list (the panel keeps the full list in
    memory anyway to avoid re-reading the file on every widget change)."""
    out = list(transactions)
    if ticker:
        out = [t for t in out if t.ticker == ticker]
    if since:
        out = [t for t in out if t.date >= since]
    out.sort(key=lambda t: t.date, reverse=True)
    return out


def transaction_amount(tx: Transaction) -> float:
    """Signed amount for display: buy 负, sell 正, dividend 正, split 0."""
    if tx.action == "buy":
        return -(tx.price * tx.quantity + tx.fees)
    if tx.action == "sell":
        return tx.price * tx.quantity - tx.fees
    if tx.action == "dividend":
        return tx.price * tx.quantity
    return 0.0


def _tx_pnl_class(amount: float) -> str:
    if amount > 0:
        return "bb-portfolio-pnl-up"
    if amount < 0:
        return "bb-portfolio-pnl-down"
    return "bb-portfolio-pnl-neutral"


# ── Streamlit renderers ────────────────────────────────────────────────


def render_transactions_tab(
    transactions: list[Transaction],
    positions: list[Position],
) -> None:
    """Public entry: render the transactions tab inside the portfolio panel."""
    if not positions:
        st.info("📭 暂无持仓,无法录入交易。请先在 '总览' 页录入持仓。")
        return

    # Toolbar
    tickers = sorted({p.ticker for p in positions})
    tc1, tc2, tc3 = st.columns([1, 1, 2])
    with tc1:
        ticker_choice = st.selectbox(
            "按 ticker 筛选",
            options=["(全部)"] + tickers,
            index=0,
            key="tx_filter_ticker",
        )
    with tc2:
        since = st.date_input(
            "起始日期",
            value=None,
            key="tx_filter_since",
        )
    with tc3:
        if st.button("💸 录入新交易", type="primary", key="tx_add_btn",
                     use_container_width=False):
            # Pop a chooser dialog for the position; for simplicity we open the
            # first matching position's dialog via a temp selectbox.
            pass

    # Position chooser for new-tx dialog
    pos_choices = {f"{p.ticker} {p.name}".strip(): p for p in positions}
    chosen_label = st.selectbox(
        "为哪只持仓录入交易?",
        options=list(pos_choices.keys()),
        index=0,
        key="tx_target_position",
    )
    target_position = pos_choices[chosen_label]
    if st.button("📝 打开录入表单", key="tx_open_dialog"):
        open_add_transaction_dialog(target_position.position_id)

    # Apply filters
    since_str = since.strftime("%Y-%m-%d") if since else None
    ticker_filter = None if ticker_choice == "(全部)" else ticker_choice.split()[0]
    rows = filter_transactions(transactions, ticker=ticker_filter, since=since_str)

    if not rows:
        st.info("📭 没有匹配的交易记录。")
        return

    # Header
    cols = st.columns([1.2, 1, 0.8, 1, 1, 1, 1.2, 1.5])
    headers = ["日期", "代码", "动作", "价格", "数量", "手续费", "金额", "备注"]
    for col, h in zip(cols, headers):
        col.markdown(f'<div class="bb-portfolio-th">{h}</div>', unsafe_allow_html=True)

    for tx in rows:
        amount = transaction_amount(tx)
        action_label = TX_ACTION_LABELS.get(tx.action, tx.action)
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.2, 1, 0.8, 1, 1, 1, 1.2, 1.5])
        with c1:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{tx.date}</div>')
        with c2:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{tx.ticker}</div>')
        with c3:
            st.html(f'<div class="bb-portfolio-td">{action_label}</div>')
        with c4:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{tx.price:.4f}</div>')
        with c5:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{tx.quantity:,}</div>')
        with c6:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{tx.fees:.2f}</div>')
        with c7:
            cls = _tx_pnl_class(amount)
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono {cls}">'
                f'{amount:+.2f}</div>'
            )
        with c8:
            st.html(f'<div class="bb-portfolio-td">{tx.notes or "—"}</div>')


__all__ = [
    "filter_transactions",
    "transaction_amount",
    "render_transactions_tab",
]
