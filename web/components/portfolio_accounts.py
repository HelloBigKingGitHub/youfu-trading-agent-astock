"""Tab 7 — 账户管理 (v0.5.0 新增).

多券商账户管理 UI：
  - 表格列：账户名 / 券商 / 账号后 4 位 / 大类资产 / 默认 ⭐ / 持仓数 / 创建时间 / 操作
  - 行操作：编辑 / 删除 / 设为默认
  - "新增账户" 按钮（调 ``open_add_account_dialog``，对应 ``portfolio_dialogs`` 里
    的 ``_add_account_dialog``）
  - 删除前检查持仓引用：``list_positions(account=name)`` 非空 → ``st.warning`` 阻断 +
    提示"该账户下还有 N 只持仓，请先迁移或删除"
  - 同名拒绝：``_add_account_dialog`` 提交时如果 name 已存在 → ``st.error`` + 不调 store

设计:
  - 复用 ``portfolio_dialogs.format_currency`` 显示持仓金额（虽然这里显示的是 count）
  - 时间戳走 ``datetime.fromtimestamp(a.created_at).strftime("%Y-%m-%d")``
  - 删除走 ``st.dialog`` 弹框确认（``open_delete_account_dialog``），不再用
    ``st.session_state[confirm_key]`` 二次确认 trick：原方案 click → rerun →
    按钮立即被替换为"✓"，用户看不到反馈，而且 rerun 期间 playwright 会报
    "subtree intercepts pointer events"。
  - 所有按钮文字带 emoji + 中文（如 "🗑️ 删除"），不再用 emoji-only 标签。
"""

from __future__ import annotations

import logging
from datetime import datetime

import streamlit as st

from backend.core.portfolio_store import Account, get_portfolio_store
from web.components.portfolio_dialogs import open_delete_account_dialog

logger = logging.getLogger(__name__)


# ── Pure helpers (unit-testable) ────────────────────────────────────────


def count_positions_for_account(account_name: str) -> int:
    """持仓表里归属于此账户的条目数。封装方便测试和复用。"""
    try:
        store = get_portfolio_store()
        return len(store.list_positions(account=account_name))
    except Exception as exc:  # noqa: BLE001
        logger.debug("count_positions_for_account(%s) failed: %s", account_name, exc)
        return 0


def format_created_at(epoch_seconds: float | int) -> str:
    """epoch → 'YYYY-MM-DD'。测试隔离 time zone 用。"""
    try:
        return datetime.fromtimestamp(float(epoch_seconds)).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return "—"


def default_account_or_none(accounts: list[Account]) -> Account | None:
    """返回 ``is_default=True`` 的账户；若没有，返回 ``accounts[0]``（兜底）。"""
    for a in accounts:
        if a.is_default:
            return a
    return accounts[0] if accounts else None


# ── Streamlit renderers ────────────────────────────────────────────────


def _render_accounts_table(accounts: list[Account]) -> None:
    """多账户表格：账户名 / 券商 / 账号后 4 位 / 大类资产 / 默认 ⭐ / 持仓数 / 创建时间 / 操作。

    每个账户一行 + 4 个操作按钮（编辑 / 删除 / 设为默认 / 取消默认）。
    """
    if not accounts:
        st.info("📭 暂无账户。点击下方 '新增账户' 创建第一个账户（首次进入会自动建一个 default）。")
        return

    # Header
    header_cols = st.columns([1.4, 1.2, 0.8, 1, 0.6, 0.8, 1, 2.2])
    headers = ["账户名", "券商", "账号后 4 位", "大类资产", "默认", "持仓数", "创建时间", "操作"]
    for col, h in zip(header_cols, headers):
        col.markdown(f'<div class="bb-portfolio-th">{h}</div>', unsafe_allow_html=True)

    store = get_portfolio_store()
    for acc in accounts:
        held_count = len(store.list_positions(account=acc.name))
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1.4, 1.2, 0.8, 1, 0.6, 0.8, 1, 2.2])
        with c1:
            st.html(f'<div class="bb-portfolio-td"><b>{acc.name}</b></div>')
        with c2:
            st.html(f'<div class="bb-portfolio-td">{acc.broker or "—"}</div>')
        with c3:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">'
                f'{acc.account_number_tail or "—"}</div>'
            )
        with c4:
            st.html(f'<div class="bb-portfolio-td">{acc.asset_class}</div>')
        with c5:
            star = "⭐" if acc.is_default else ""
            st.html(f'<div class="bb-portfolio-td">{star}</div>')
        with c6:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{held_count}</div>'
            )
        with c7:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">'
                f'{format_created_at(acc.created_at)}</div>'
            )
        with c8:
            btn_row = st.columns([1, 1, 1, 1])
            # 设为默认 / 取消默认
            with btn_row[0]:
                if acc.is_default:
                    if st.button(
                        "🚫 取消默认", key=f"unset_default_{acc.account_id}",
                        help="取消默认账户",
                    ):
                        # 取消：把当前 default 设 False（其它账户保持非 default）
                        try:
                            store.update_account(acc.account_id, is_default=False)
                            st.rerun()
                        except (ValueError, KeyError) as exc:
                            st.error(f"操作失败: {exc}")
                else:
                    if st.button(
                        "⭐ 设默认", key=f"set_default_{acc.account_id}",
                        help="设为默认账户",
                    ):
                        try:
                            store.set_default_account(acc.account_id)
                            st.rerun()
                        except (ValueError, KeyError) as exc:
                            st.error(f"操作失败: {exc}")
            # 编辑
            with btn_row[1]:
                if st.button(
                    "✏️ 编辑", key=f"edit_acc_{acc.account_id}",
                    help="编辑账户",
                ):
                    _edit_account_dialog(acc)
            # 删除（st.dialog 弹框二次确认，取代旧的 session_state trick）
            with btn_row[2]:
                if st.button(
                    "🗑️ 删除", key=f"del_acc_{acc.account_id}",
                    help="删除账户（弹框二次确认）",
                ):
                    # 弹框本身已展示持仓数并阻断持仓非空账户，
                    # 但提前给个即时提示可避免无谓的 dialog 重绘。
                    if held_count > 0:
                        st.warning(
                            f"账户 '{acc.name}' 下还有 {held_count} 只持仓，"
                            "请先迁移或删除持仓"
                        )
                    open_delete_account_dialog(acc.account_id)
            # 第 4 个槽位留空（视觉对齐）
            with btn_row[3]:
                st.html('<div class="bb-portfolio-td">&nbsp;</div>')


@st.dialog("🏦 编辑账户", width="medium")
def _edit_account_dialog(acc: Account) -> None:
    """编辑已有账户的元数据。name 不能改（避免重名风险，留作 v0.5.1 增强）。"""
    st.caption(f"账户 ID: {acc.account_id[:8]}...（name 不可改）")
    name = st.text_input("账户名", value=acc.name, disabled=True)
    broker = st.text_input("券商", value=acc.broker, key=f"edit_acc_broker_{acc.account_id}")
    tail = st.text_input(
        "账号后 4 位", value=acc.account_number_tail, max_chars=4,
        key=f"edit_acc_tail_{acc.account_id}",
    )
    asset_class = st.selectbox(
        "大类资产",
        options=["stock", "bond", "overseas", "cash", "fund"],
        index=["stock", "bond", "overseas", "cash", "fund"].index(acc.asset_class)
        if acc.asset_class in ["stock", "bond", "overseas", "cash", "fund"] else 0,
        key=f"edit_acc_asset_{acc.account_id}",
    )
    notes = st.text_area("备注", value=acc.notes, key=f"edit_acc_notes_{acc.account_id}")
    is_default = st.checkbox(
        "设为默认账户", value=acc.is_default,
        key=f"edit_acc_default_{acc.account_id}",
    )

    col1, col2 = st.columns(2)
    if col1.button("✅ 保存", type="primary", key=f"edit_acc_submit_{acc.account_id}"):
        try:
            get_portfolio_store().update_account(
                acc.account_id,
                broker=broker.strip(),
                account_number_tail=tail.strip(),
                asset_class=asset_class,
                notes=notes.strip(),
                is_default=bool(is_default),
            )
        except ValueError as exc:
            st.error(f"保存失败: {exc}")
            return
        st.success("已更新")
        st.rerun()
    if col2.button("取消", key=f"edit_acc_cancel_{acc.account_id}"):
        st.rerun()


def render_accounts_tab() -> None:
    """Public entry: render Tab 7 — 账户管理。"""
    # 兜底：如果磁盘上没有任何账户，建一个 default
    store = get_portfolio_store()
    store.ensure_default_account()

    accounts = store.list_accounts()

    st.markdown(
        '<div class="bb-section-label">账户列表 (v0.5.0)</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"共 {len(accounts)} 个账户。"
        f"持仓按账户聚合分析（'华泰账户今天盈亏多少'）。"
        f"删除前自动检查引用。"
    )

    _render_accounts_table(accounts)

    if st.button(
        "➕ 新增账户", type="primary", key="accounts_add_button",
        use_container_width=False,
    ):
        from web.components.portfolio_dialogs import open_add_account_dialog
        open_add_account_dialog()


__all__ = [
    "count_positions_for_account",
    "format_created_at",
    "default_account_or_none",
    "render_accounts_tab",
]