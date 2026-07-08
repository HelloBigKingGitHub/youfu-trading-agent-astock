"""Portfolio CRUD dialogs — 4 modal forms for positions, transactions, alerts.

Streamlit ``st.dialog`` (1.58+) wraps the underlying modal. Each dialog
exposes a pure validation helper (``validate_*``) that the unit tests can
call without a Streamlit context, and a ``render_*_dialog`` that consumes
``st.session_state`` and writes back via the store.

Design constraints (v0.5.0):
  - ticker must be 6 digits
  - cost_basis > 0 for positions
  - quantity > 0 for positions, != 0 for transactions
  - sell transaction: quantity must not exceed held position quantity
  - rule_type must be in VALID_ALERT_RULE_TYPES
  - All errors render inline via ``st.error`` and short-circuit submit.
"""

from __future__ import annotations

import re
from datetime import date as _date
from typing import Any

import streamlit as st

from backend.core.portfolio_store import (
    VALID_ALERT_RULE_TYPES,
    VALID_ASSET_CLASSES,
    VALID_TRANSACTION_ACTIONS,
    Position,
)

# ── Constants (exported for tests) ────────────────────────────────────────

TICKER_RE = re.compile(r"^\d{6}$")

ALERT_RULE_LABELS: dict[str, str] = {
    "price_above": "价格突破 (>=)",
    "price_below": "价格跌破 (<=)",
    "pct_change": "当日涨跌幅 (|%|)",
    "pnl_pct": "盈亏比例 (>=%)",
    "take_profit": "止盈 (成本+%)",
    "stop_loss": "止损 (成本-%)",
    "trailing_stop": "移动止损 (成本-%)",
}

ASSET_CLASS_LABELS: dict[str, str] = {
    "stock": "股票",
    "bond": "债券",
    "overseas": "海外",
    "cash": "现金",
}

TX_ACTION_LABELS: dict[str, str] = {
    "buy": "买入",
    "sell": "卖出",
    "dividend": "分红",
    "split": "送股",
    "merge": "并股",
    "rights": "配股",
}


# ── Pure validation helpers (no streamlit, unit-testable) ───────────────


def validate_ticker(ticker: str) -> str | None:
    """Return None if valid 6-digit, else error message."""
    if not ticker:
        return "请输入股票代码"
    if not TICKER_RE.match(ticker.strip()):
        return "股票代码必须为 6 位数字"
    return None


def validate_position_fields(
    ticker: str,
    cost_basis: float,
    quantity: int,
    asset_class: str = "stock",
) -> str | None:
    """Combined validator for the position dialog. Returns first error or None."""
    err = validate_ticker(ticker)
    if err:
        return err
    if cost_basis <= 0:
        return "成本价必须大于 0"
    if quantity <= 0:
        return "持仓数量必须大于 0"
    if asset_class not in VALID_ASSET_CLASSES:
        return f"资产类别必须为 {VALID_ASSET_CLASSES} 之一"
    return None


def validate_transaction_fields(
    price: float,
    quantity: int,
    action: str,
    held_quantity: int = 0,
) -> str | None:
    """Combined validator for the transaction dialog."""
    if action not in VALID_TRANSACTION_ACTIONS:
        return f"动作必须为 {VALID_TRANSACTION_ACTIONS} 之一"
    if price <= 0:
        return "价格必须大于 0"
    if quantity <= 0:
        return "数量必须大于 0"
    if action == "sell" and quantity > held_quantity:
        return f"卖出数量 {quantity} 超过当前持仓 {held_quantity}"
    return None


def validate_alert_fields(
    ticker: str,
    rule_type: str,
    threshold: float,
) -> str | None:
    """Combined validator for the alert dialog."""
    err = validate_ticker(ticker)
    if err:
        return err
    if rule_type not in VALID_ALERT_RULE_TYPES:
        return f"规则类型必须为 {VALID_ALERT_RULE_TYPES} 之一"
    if rule_type == "trailing_stop" and threshold <= 0:
        return "移动止损阈值必须大于 0"
    return None


# ── Formatting helpers (pure, exported for tests) ────────────────────────


def parse_pct(s: Any) -> float:
    """Parse a percentage string ('+10.01%', '-3.5%', '2.5') to float.

    Returns 0.0 for unparseable / None values. Mirrors the helper in
    sector_panel but lives here too so the panel doesn't depend on a
    sibling module.
    """
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"([+-]?[\d.]+)\s*%?", str(s))
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def format_pct(value: float, signed: bool = True) -> str:
    """Format a float as a signed % string ('+1.23%' / '-0.45%' / '0.00%')."""
    if value is None:
        value = 0.0
    if signed:
        return f"{value:+.2f}%"
    return f"{value:.2f}%"


def format_currency(value: float, prefix: str = "¥") -> str:
    """Format a float as currency ('¥1,234.56' / '¥-123.45')."""
    if value is None:
        value = 0.0
    if value < 0:
        return f"-{prefix}{abs(value):,.2f}"
    return f"{prefix}{value:,.2f}"


def pnl_color_class(value: float) -> str:
    """Return CSS class for a pnl/value: positive=up, negative=down, 0=neutral."""
    if value > 0:
        return "bb-portfolio-pnl-up"
    if value < 0:
        return "bb-portfolio-pnl-down"
    return "bb-portfolio-pnl-neutral"


# ── Store singleton accessor (kept here for clean import sites) ──────────


def _get_store():
    """Lazy import + singleton accessor for the portfolio store."""
    from backend.core.portfolio_store import get_portfolio_store

    return get_portfolio_store()


# ── Dialogs ─────────────────────────────────────────────────────────────


@st.dialog("➕ 录入新持仓", width="medium")
def _add_position_dialog() -> None:
    """Modal form to add a new Position. State stored in session_state."""
    st.caption("录入后立即写入本地 JSON,并触发 'st.rerun()' 刷新总览页。")

    ticker = st.text_input(
        "股票代码 *",
        key="dlg_pos_ticker",
        placeholder="6 位数字 (例: 600595)",
        help="6 位 A 股代码",
    ).strip()
    name = st.text_input("股票名称", key="dlg_pos_name", placeholder="(可选) 例: 贵州茅台")
    col1, col2 = st.columns(2)
    with col1:
        cost_basis = st.number_input(
            "成本价 *", min_value=0.0, value=0.0, step=0.01,
            format="%.4f", key="dlg_pos_cost",
        )
    with col2:
        quantity = st.number_input(
            "持仓数量 *", min_value=0, value=0, step=100,
            key="dlg_pos_qty",
        )
    first_buy_date = st.date_input(
        "首次买入日期 *", value=_date.today(), key="dlg_pos_date",
    )
    col3, col4 = st.columns(2)
    with col3:
        account = st.text_input("账户", value="default", key="dlg_pos_account")
    with col4:
        asset_class = st.selectbox(
            "资产类别",
            options=list(VALID_ASSET_CLASSES),
            index=list(VALID_ASSET_CLASSES).index("stock"),
            format_func=lambda x: ASSET_CLASS_LABELS.get(x, x),
            key="dlg_pos_asset",
        )
    notes = st.text_area("备注", key="dlg_pos_notes", placeholder="(可选)")

    if st.button("✅ 提交", type="primary", key="dlg_pos_submit", use_container_width=True):
        err = validate_position_fields(ticker, cost_basis, int(quantity), asset_class)
        if err:
            st.error(err)
            return
        store = _get_store()
        try:
            store.add_position(
                ticker=ticker,
                name=name.strip(),
                cost_basis=float(cost_basis),
                quantity=int(quantity),
                first_buy_date=first_buy_date.strftime("%Y-%m-%d"),
                account=account.strip() or "default",
                asset_class=asset_class,
                notes=notes.strip(),
            )
        except ValueError as exc:
            st.error(f"保存失败: {exc}")
            return
        st.success("已录入")
        st.rerun()


@st.dialog("✏️ 编辑持仓", width="medium")
def _edit_position_dialog(position_id: str) -> None:
    """Modal form to update an existing Position. Pre-fills from store."""
    store = _get_store()
    pos = store.get_position(position_id)
    if pos is None:
        st.error(f"持仓 {position_id} 不存在 (可能已删除)")
        return

    st.caption(f"编辑: {pos.ticker} {pos.name}".strip())

    ticker = st.text_input(
        "股票代码 *", value=pos.ticker, key=f"dlg_edit_pos_ticker_{position_id}",
    ).strip()
    name = st.text_input(
        "股票名称", value=pos.name, key=f"dlg_edit_pos_name_{position_id}",
    )
    col1, col2 = st.columns(2)
    with col1:
        cost_basis = st.number_input(
            "成本价 *", min_value=0.0, value=float(pos.cost_basis),
            step=0.01, format="%.4f", key=f"dlg_edit_pos_cost_{position_id}",
        )
    with col2:
        quantity = st.number_input(
            "持仓数量 *", min_value=0, value=int(pos.quantity),
            step=100, key=f"dlg_edit_pos_qty_{position_id}",
        )
    first_buy_date = st.date_input(
        "首次买入日期 *",
        value=_date.fromisoformat(pos.first_buy_date) if pos.first_buy_date else _date.today(),
        key=f"dlg_edit_pos_date_{position_id}",
    )
    asset_class = st.selectbox(
        "资产类别",
        options=list(VALID_ASSET_CLASSES),
        index=list(VALID_ASSET_CLASSES).index(pos.asset_class)
        if pos.asset_class in VALID_ASSET_CLASSES else 0,
        format_func=lambda x: ASSET_CLASS_LABELS.get(x, x),
        key=f"dlg_edit_pos_asset_{position_id}",
    )
    notes = st.text_area("备注", value=pos.notes, key=f"dlg_edit_pos_notes_{position_id}")

    if st.button("✅ 保存", type="primary", key=f"dlg_edit_pos_submit_{position_id}", use_container_width=True):
        err = validate_position_fields(ticker, cost_basis, int(quantity), asset_class)
        if err:
            st.error(err)
            return
        try:
            store.update_position(
                position_id,
                ticker=ticker,
                name=name.strip(),
                cost_basis=float(cost_basis),
                quantity=int(quantity),
                first_buy_date=first_buy_date.strftime("%Y-%m-%d"),
                asset_class=asset_class,
                notes=notes.strip(),
            )
        except (ValueError, KeyError) as exc:
            st.error(f"保存失败: {exc}")
            return
        st.success("已更新")
        st.rerun()


@st.dialog("💸 录入交易", width="medium")
def _add_transaction_dialog(position_id: str) -> None:
    """Modal form to add a Transaction against a given position."""
    store = _get_store()
    pos = store.get_position(position_id)
    if pos is None:
        st.error(f"持仓 {position_id} 不存在")
        return

    st.caption(f"{pos.ticker} {pos.name} · 当前持仓 {pos.quantity}")

    col1, col2 = st.columns(2)
    with col1:
        action = st.selectbox(
            "动作 *",
            options=list(VALID_TRANSACTION_ACTIONS),
            index=0,
            format_func=lambda x: TX_ACTION_LABELS.get(x, x),
            key=f"dlg_tx_action_{position_id}",
        )
    with col2:
        tx_date = st.date_input(
            "交易日期 *", value=_date.today(),
            key=f"dlg_tx_date_{position_id}",
        )
    col3, col4, col5 = st.columns(3)
    with col3:
        price = st.number_input(
            "价格 *", min_value=0.0, value=float(pos.cost_basis),
            step=0.01, format="%.4f",
            key=f"dlg_tx_price_{position_id}",
        )
    with col4:
        quantity = st.number_input(
            "数量 *", min_value=0, value=int(pos.quantity) or 100,
            step=100,
            key=f"dlg_tx_qty_{position_id}",
        )
    with col5:
        fees = st.number_input(
            "手续费", min_value=0.0, value=0.0,
            step=0.01, format="%.2f",
            key=f"dlg_tx_fees_{position_id}",
        )
    notes = st.text_area("备注", key=f"dlg_tx_notes_{position_id}", placeholder="(可选)")

    if st.button(
        "✅ 提交", type="primary",
        key=f"dlg_tx_submit_{position_id}", use_container_width=True,
    ):
        held = pos.quantity if action == "sell" else 0
        err = validate_transaction_fields(
            float(price), int(quantity), action, held_quantity=held,
        )
        if err:
            st.error(err)
            return
        try:
            store.add_transaction(
                position_id=position_id,
                date=tx_date.strftime("%Y-%m-%d"),
                action=action,
                price=float(price),
                quantity=int(quantity),
                fees=float(fees),
                notes=notes.strip(),
            )
        except (ValueError, KeyError) as exc:
            st.error(f"保存失败: {exc}")
            return
        st.success("已录入")
        st.rerun()


@st.dialog("🔔 新增预警", width="medium")
def _add_alert_dialog() -> None:
    """Modal form to add an AlertRule."""
    st.caption("基于现价 / 成本价的阈值预警。达到条件后 Tab 4 '检查预警' 触发 toast。")

    ticker = st.text_input(
        "股票代码 *", key="dlg_alert_ticker",
        placeholder="6 位数字 (例: 600595)",
    ).strip()
    rule_type = st.selectbox(
        "规则类型 *",
        options=list(VALID_ALERT_RULE_TYPES),
        index=0,
        format_func=lambda x: ALERT_RULE_LABELS.get(x, x),
        key="dlg_alert_rule_type",
    )
    threshold = st.number_input(
        "阈值 *", value=0.0, step=0.01, format="%.2f",
        key="dlg_alert_threshold",
        help="price_above/below 直接填价格;pct_change/pnl_pct 填 %;take_profit/stop_loss 填 %",
    )
    note = st.text_area("备注", key="dlg_alert_note", placeholder="(可选)")
    enabled = st.checkbox("启用", value=True, key="dlg_alert_enabled")

    if st.button("✅ 提交", type="primary", key="dlg_alert_submit", use_container_width=True):
        err = validate_alert_fields(ticker, rule_type, float(threshold))
        if err:
            st.error(err)
            return
        store = _get_store()
        try:
            store.add_alert(
                ticker=ticker,
                rule_type=rule_type,
                threshold=float(threshold),
                note=note.strip(),
                enabled=bool(enabled),
            )
        except ValueError as exc:
            st.error(f"保存失败: {exc}")
            return
        st.success("已添加")
        st.rerun()


# ── Public entry wrappers (called from tabs) ───────────────────────────


def open_add_position_dialog() -> None:
    """Tab 1 button → open the add-position dialog."""
    _add_position_dialog()


def open_edit_position_dialog(position_id: str) -> None:
    """Tab 1 row button → open the edit dialog pre-filled for position_id."""
    _edit_position_dialog(position_id)


def open_add_transaction_dialog(position_id: str) -> None:
    """Tab 1 row button → open the transaction dialog for the given position."""
    _add_transaction_dialog(position_id)


def open_add_alert_dialog() -> None:
    """Tab 4 button → open the alert dialog."""
    _add_alert_dialog()


__all__ = [
    "TICKER_RE",
    "ALERT_RULE_LABELS",
    "ASSET_CLASS_LABELS",
    "TX_ACTION_LABELS",
    "validate_ticker",
    "validate_position_fields",
    "validate_transaction_fields",
    "validate_alert_fields",
    "parse_pct",
    "format_pct",
    "format_currency",
    "pnl_color_class",
    "open_add_position_dialog",
    "open_edit_position_dialog",
    "open_add_transaction_dialog",
    "open_add_alert_dialog",
]
