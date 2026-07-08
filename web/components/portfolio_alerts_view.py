"""Tab 4 — 价格预警.

预警表格 (ticker / 规则类型 / 阈值 / 启用 / 最后触发 / 触发次数) + 「新增
预警」+「检查预警」 按钮。检查预警调 ``evaluate_alerts``,每条 trigger 弹
``st.toast``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from backend.core.portfolio_alerts import evaluate_alerts, format_trigger_message
from backend.core.portfolio_store import (
    AlertRule,
    VALID_ALERT_RULE_TYPES,
    Position,
    get_portfolio_store,
)
from web.components.portfolio_dialogs import (
    ALERT_RULE_LABELS,
    open_add_alert_dialog,
)


# ── Pure helpers (unit-testable) ────────────────────────────────────────


def alert_status_label(rule: AlertRule) -> str:
    """Human-readable status string for the '最后触发' column."""
    if rule.last_triggered_at is None:
        return "(未触发)"
    try:
        ts = datetime.fromtimestamp(rule.last_triggered_at)
        return ts.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return "(无效时间戳)"


def _is_valid_rule_type(rule_type: str) -> bool:
    """Defensive check for the 'rule_type' selectbox choices."""
    return rule_type in VALID_ALERT_RULE_TYPES


def _row_key(rule: AlertRule) -> str:
    """Stable per-row widget key."""
    return f"alert_row_{rule.rule_id}"


# ── Streamlit renderers ────────────────────────────────────────────────


def _render_alert_table(rules: list[AlertRule]) -> None:
    """One row per enabled or disabled rule with delete / toggle actions."""
    if not rules:
        st.info("📭 暂无预警规则。点击下方 '新增预警' 创建第一条规则。")
        return

    cols = st.columns([1, 1.2, 1.4, 1, 0.8, 1.5, 0.8, 1])
    headers = ["代码", "规则类型", "阈值", "启用", "触发次数", "最后触发", "价格", "操作"]
    for col, h in zip(cols, headers):
        col.markdown(f'<div class="bb-portfolio-th">{h}</div>', unsafe_allow_html=True)

    store = get_portfolio_store()
    for rule in rules:
        rt_label = ALERT_RULE_LABELS.get(rule.rule_type, rule.rule_type)
        last_ts = alert_status_label(rule)
        c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1, 1.2, 1.4, 1, 0.8, 1.5, 0.8, 1])
        with c1:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{rule.ticker}</div>')
        with c2:
            st.html(f'<div class="bb-portfolio-td">{rt_label}</div>')
        with c3:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{rule.threshold:.2f}</div>'
            )
        with c4:
            enabled_now = st.toggle(
                "启用",
                value=bool(rule.enabled),
                key=f"alert_toggle_{rule.rule_id}",
                label_visibility="collapsed",
            )
            if enabled_now != rule.enabled:
                store.update_alert(rule.rule_id, enabled=bool(enabled_now))
                st.rerun()
        with c5:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{rule.trigger_count}</div>'
            )
        with c6:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{last_ts}</div>')
        with c7:
            lp = rule.last_triggered_price
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">'
                f'{(f"{lp:.2f}" if lp is not None else "—")}'
                f'</div>'
            )
        with c8:
            if st.button("🗑️", key=f"alert_del_{rule.rule_id}", help="删除"):
                store.delete_alert(rule.rule_id)
                st.rerun()


def _render_check_button(
    rules: list[AlertRule],
    positions: list[Position],
) -> None:
    """One-click evaluator: fetch prices, run evaluate_alerts, render toasts."""
    enabled_count = sum(1 for r in rules if r.enabled)
    if enabled_count == 0:
        st.caption("⚠️ 当前没有启用的预警规则,'检查预警' 无效果。")
    if st.button(
        f"🔍 检查预警 ({enabled_count} 条启用)",
        key="alerts_check_btn",
        type="primary",
        use_container_width=False,
    ):
        # Fetch current prices for all rule tickers (deduplicated)
        from web.components.portfolio_overview import safe_quote

        cost_map: dict[str, float] = {p.ticker: p.cost_basis for p in positions}
        prev_closes: dict[str, float] = {}
        prices: dict[str, float] = {}
        for rule in rules:
            if rule.ticker in prices:
                continue
            q = safe_quote(rule.ticker)
            if q is not None:
                prices[rule.ticker] = q
                # Tencent qt.gtimg.cn payload also includes last_close; we don't
                # have a clean accessor here, so we leave prev_close empty —
                # pct_change rules will skip (returns False when prev_close None).
        if not prices:
            st.warning("⚠️ 拉取实时行情失败,请稍后重试。")
            return
        store = get_portfolio_store()
        triggers = evaluate_alerts(
            store=store,
            current_prices=prices,
            prev_closes=prev_closes,
            cost_bases=cost_map,
        )
        if not triggers:
            st.toast("✅ 没有预警触发", icon="✅")
        else:
            for t in triggers:
                msg = format_trigger_message(t)
                st.toast(f"🔔 {t.ticker}: {msg}", icon="🔔")


def render_alerts_tab(
    rules: list[AlertRule],
    positions: list[Position],
) -> None:
    """Public entry: render the alerts tab inside the portfolio panel."""
    _render_alert_table(rules)
    st.markdown("---")
    btn1, btn2 = st.columns([1, 4])
    with btn1:
        if st.button("➕ 新增预警", key="alerts_add_btn", type="secondary"):
            open_add_alert_dialog()
    with btn2:
        _render_check_button(rules, positions)


__all__ = [
    "alert_status_label",
    "render_alerts_tab",
]
