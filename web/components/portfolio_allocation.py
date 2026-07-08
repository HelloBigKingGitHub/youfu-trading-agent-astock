"""Tab 3 — 资产配置.

3 个饼图:行业 / 板块 / 大类资产 + 集中度 (top 5 + 单股最大)。

设计:
  - 行业归类:从 ``get_concept_blocks`` 拿原始 markdown,parse 后取「行业」段
    (走 ``portfolio_calc._concept_block_to_sectors`` 已有逻辑)。失败时回退
    到「其他」bucket,不阻塞 UI。
  - 板块分布: 复用 ``portfolio_calc.group_by_sector``。
  - 大类资产: 直接从 ``Position.asset_class`` 字段聚合。
  - 集中度: top 5 + max single holding。值用 ``portfolio_summary`` 已有字段。
  - 饼图:用 ``altair`` (项目已有,无需新增依赖) 走 ``st.altair_chart``。
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from backend.core.portfolio_store import (
    VALID_ASSET_CLASSES,
    Position,
)
from web.components.portfolio_dialogs import (
    ASSET_CLASS_LABELS,
    format_currency,
    format_pct,
)


# ── Pure helpers (unit-testable) ────────────────────────────────────────


def group_by_asset_class(
    positions: list[Position],
    current_prices: dict[str, float],
) -> dict[str, float]:
    """Aggregate current value by Position.asset_class. Asset class label
    falls back to the raw enum string when not in ASSET_CLASS_LABELS."""
    out: dict[str, float] = {}
    for pos in positions:
        price = current_prices.get(pos.ticker, pos.cost_basis)
        value = price * pos.quantity
        out[pos.asset_class] = out.get(pos.asset_class, 0.0) + value
    return {k: round(v, 2) for k, v in out.items()}


def concentration_topn(
    positions: list[Position],
    current_prices: dict[str, float],
    n: int = 5,
) -> list[tuple[str, float, float]]:
    """Return top-N (ticker, value, weight) by current value.

    weight = value / total_value (0..1). Sorted desc.
    """
    if not positions:
        return []
    values: list[tuple[str, float]] = []
    total = 0.0
    for pos in positions:
        price = current_prices.get(pos.ticker, pos.cost_basis)
        v = price * pos.quantity
        values.append((pos.ticker, v))
        total += v
    values.sort(key=lambda x: x[1], reverse=True)
    out: list[tuple[str, float, float]] = []
    for t, v in values[:n]:
        w = v / total if total else 0.0
        out.append((t, round(v, 2), round(w, 4)))
    return out


def max_single_holding_pct(
    positions: list[Position],
    current_prices: dict[str, float],
) -> float:
    """Largest single holding as fraction of total value (0..1)."""
    top = concentration_topn(positions, current_prices, n=1)
    if not top:
        return 0.0
    return top[0][2]


def _df_from_dict(d: dict[str, float], label: str) -> pd.DataFrame:
    """Build a DataFrame [{label, value}] for altair pie, sorted desc."""
    if not d:
        return pd.DataFrame(columns=[label, "value"])
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return pd.DataFrame({label: [k for k, _ in items], "value": [v for _, v in items]})


def _pie_chart(df: pd.DataFrame, label: str, title: str) -> alt.Chart:
    """Donut chart via altair.mark_arc."""
    if df.empty:
        return alt.Chart(pd.DataFrame({label: [], "value": []})).mark_text().encode(
            text=alt.value("(空)"),
        )
    base = alt.Chart(df).encode(
        theta=alt.Theta("value:Q", title=None),
        color=alt.Color(f"{label}:N", legend=alt.Legend(title=title)),
        tooltip=[label, alt.Tooltip("value:Q", format=",.2f")],
    )
    pie = base.mark_arc(innerRadius=50, outerRadius=110)
    text = base.mark_text(radius=130, size=11).encode(
        text=alt.Text(f"{label}:N"),
    )
    return pie + text


# ── Streamlit renderers ────────────────────────────────────────────────


def _render_pies(
    by_industry: dict[str, float],
    by_sector: dict[str, float],
    by_asset: dict[str, float],
) -> None:
    """3 altair pie charts in a row, fallback to info if empty."""
    df_ind = _df_from_dict(by_industry, "行业")
    df_sec = _df_from_dict(by_sector, "板块")
    df_ast = _df_from_dict(by_asset, "资产")

    cols = st.columns(3)
    titles = [
        ("🏭 行业分布", df_ind, "行业"),
        ("🏷️ 板块分布", df_sec, "板块"),
        ("💰 大类资产", df_ast, "资产"),
    ]
    for col, (title, df, label) in zip(cols, titles):
        with col:
            st.markdown(
                f'<div class="bb-portfolio-pie-title">{title}</div>',
                unsafe_allow_html=True,
            )
            if df.empty:
                st.html(
                    '<div class="bb-portfolio-pie-empty">'
                    "(无数据 / 概念板块拉取失败)</div>"
                )
            else:
                st.altair_chart(_pie_chart(df, label, title), use_container_width=True)


def _render_concentration(
    positions: list[Position],
    current_prices: dict[str, float],
) -> None:
    """Top-5 concentration table + max single holding metric."""
    top5 = concentration_topn(positions, current_prices, n=5)
    max_pct = max_single_holding_pct(positions, current_prices)
    total = sum(v for _, v, _ in top5)

    st.markdown(
        '<div class="bb-section-label">🎯 持仓集中度</div>',
        unsafe_allow_html=True,
    )

    if not top5:
        st.info("📭 暂无持仓,集中度为 0。")
        return

    cols = st.columns([1, 1, 1, 1])
    headers = ["排名", "代码", "持仓金额", "占比"]
    for col, h in zip(cols, headers):
        col.markdown(f'<div class="bb-portfolio-th">{h}</div>', unsafe_allow_html=True)
    for i, (ticker, value, weight) in enumerate(top5, 1):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">#{i}</div>')
        with c2:
            st.html(f'<div class="bb-portfolio-td bb-portfolio-td-mono">{ticker}</div>')
        with c3:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{format_currency(value)}</div>'
            )
        with c4:
            st.html(
                f'<div class="bb-portfolio-td bb-portfolio-td-mono">{format_pct(weight * 100, signed=False)}</div>'
            )

    st.html(
        f'<div class="bb-portfolio-concentration-summary">'
        f'📊 前 5 大占比 <b>{format_pct(sum(w for _, _, w in top5) * 100, signed=False)}</b>'
        f' · 单股最大 <b>{format_pct(max_pct * 100, signed=False)}</b>'
        f' · 持仓总额 <b>{format_currency(total)}</b>'
        f'</div>'
    )


def render_allocation_tab(
    positions: list[Position],
    current_prices: dict[str, float],
    by_industry: dict[str, float] | None = None,
    by_sector: dict[str, float] | None = None,
) -> None:
    """Public entry: render the allocation tab inside the portfolio panel."""
    if not positions:
        st.info("📭 暂无持仓。请先在 '总览' 页录入持仓,再回来看资产配置。")
        return

    by_asset = group_by_asset_class(positions, current_prices)
    by_industry = by_industry or {}
    by_sector = by_sector or {}

    _render_pies(by_industry, by_sector, by_asset)
    st.markdown("---")
    _render_concentration(positions, current_prices)


__all__ = [
    "group_by_asset_class",
    "concentration_topn",
    "max_single_holding_pct",
    "render_allocation_tab",
]
