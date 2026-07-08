"""Portfolio panel — main entry, dispatches 6 tabs.

Top-level layout:
  1. Page header + reload button
  2. Rebalance banner (signals changed since last analysis — P0 hook)
  3. ``st.tabs([总览, 流水, 配置, 预警, 导入/导出, 收益风险])``

Each tab is a separate module (sibling files) to keep this dispatcher
under 200 lines. Dialogs (add / edit / tx / alert) live in
``portfolio_dialogs`` and are invoked by the tabs themselves.

Phase 2 deliverable. Depends on the data layer (Round 1):
  - ``backend.core.portfolio_store.PortfolioStore``
  - ``backend.core.portfolio_calc``
  - ``backend.core.portfolio_alerts.evaluate_alerts``
  - ``backend.core.portfolio_import.{detect,parse,preview,apply}_*``
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from backend.core.portfolio_store import (
    AlertRule,
    Position,
    Transaction,
    get_portfolio_store,
)
from web.components.portfolio_alerts_view import render_alerts_tab
from web.components.portfolio_allocation import render_allocation_tab
from web.components.portfolio_import_view import render_import_tab
from web.components.portfolio_overview import safe_quote
from web.components.portfolio_risk import render_risk_tab
from web.components.portfolio_transactions import render_transactions_tab

logger = logging.getLogger(__name__)

_TAB_LABELS = [
    "📊 总览",
    "📜 流水",
    "🎯 配置",
    "🔔 预警",
    "📥 导入/导出",
    "📈 收益风险",
]


# ── Pure helpers (unit-testable, no streamlit dep) ──────────────────────


def get_rebalance_signals(
    positions: list[Position],
    lookback_days: int = 7,
) -> list[dict[str, Any]]:
    """Diff Bull/Bear signal changes per ticker over the last `lookback_days`.

    MVP stub: returns []. The full implementation lives in Phase 4 (P1) once
    the Bull/Bear signal_history table is in place. Returning [] means
    ``_show_rebalance_banner`` renders nothing — the rest of the panel
    works normally.

    Tests assert the empty-list default and the no-Position-id-keyerror
    behavior; Phase 4 will swap the body without breaking the signature.
    """
    return []


def _load_data() -> tuple[list[Position], list[Transaction], list[AlertRule]]:
    """Read the 3 lists from the singleton store. Tolerant of missing files."""
    store = get_portfolio_store()
    return store.list_positions(), store.list_transactions(), store.list_alerts()


def _fetch_current_prices(tickers: list[str]) -> dict[str, float]:
    """Batch-fetch current prices for all tickers. Skips tickers where the
    quote failed (callers fall back to cost_basis)."""
    out: dict[str, float] = {}
    for t in tickers:
        q = safe_quote(t)
        if q is not None:
            out[t] = q
    return out


# ── Banner ──────────────────────────────────────────────────────────────


def _show_rebalance_banner(positions: list[Position]) -> None:
    """Show rebalance signals (model signal changes) if any.

    No positions → skip (nothing to compare against). No signals → skip
    silently (per design.md Decision 5, we don't show a noisy "all good"
    banner).
    """
    if not positions:
        return
    try:
        signals = get_rebalance_signals(positions, lookback_days=7)
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_rebalance_signals failed: %s", exc)
        return
    if not signals:
        return
    for sig in signals[:5]:
        ticker = sig.get("ticker", "?")
        old = sig.get("old_signal", "?")
        new = sig.get("new_signal", "?")
        date = sig.get("detected_at", "")
        st.info(f"📊 模型信号变化: {ticker} {old} → {new} ({date})")


# ── Main entry ──────────────────────────────────────────────────────────


def _render_header() -> None:
    """Title + caption + reload button (clear cached prices)."""
    st.markdown("## 💼 我的仓位")
    st.caption(
        "手动录入持仓 + 交易流水,实时计算盈亏 / 集中度 / 收益风险。"
        "支持 4 种 CSV 格式导入导出 + 7 种预警规则 + 调仓推送。"
    )
    if st.button("🔄 刷新数据", key="portfolio_reload", type="secondary"):
        st.session_state.pop("portfolio_prices_cache", None)
        st.rerun()


def render_portfolio_panel() -> None:
    """Top-level entry — called from ``web/app.py`` when ``view == "portfolio"``."""
    _render_header()

    positions, transactions, alerts = _load_data()
    _show_rebalance_banner(positions)

    tickers = sorted({p.ticker for p in positions})
    prices_cache = st.session_state.setdefault("portfolio_prices_cache", {})
    if not prices_cache and tickers:
        prices_cache.update(_fetch_current_prices(tickers))
        st.session_state["portfolio_prices_cache"] = prices_cache
    prices: dict[str, float] = prices_cache

    tabs = st.tabs(_TAB_LABELS)
    with tabs[0]:
        from web.components.portfolio_overview import render_overview_tab
        render_overview_tab(positions)
    with tabs[1]:
        render_transactions_tab(transactions, positions)
    with tabs[2]:
        # Allocation tab needs by_industry/by_sector. Compute by_sector via
        # the calc layer (network-fetched); by_industry is left empty for
        # the MVP since we don't have a cheap industry-classification source.
        from backend.core.portfolio_calc import group_by_sector
        try:
            by_sector = group_by_sector(positions, prices)
        except Exception:
            by_sector = {}
        render_allocation_tab(positions, prices, by_industry={}, by_sector=by_sector)
    with tabs[3]:
        render_alerts_tab(alerts, positions)
    with tabs[4]:
        render_import_tab(positions, transactions)
    with tabs[5]:
        render_risk_tab(positions, transactions, prices)


__all__ = [
    "get_rebalance_signals",
    "render_portfolio_panel",
]
