"""Sector rotation panel — concept-block grouped table with [分析] entry.

Renders the data from ``SectorRotationDigest`` (provided by
``tradingagents.dataflows.a_stock.get_sector_rotation_digest``) as a
Bloomberg-terminal-style grouped table.

Layout (top → bottom):
    1. Toolbar — search box, min-count filter, data source status, refresh
    2. 机构选股策略 expander (Top 3 from np-ipick)
    3. Concept blocks (sorted by stock count desc, Top 3 expanded)
        Per block: 5-column table (代码/名称/题材/板块涨幅/操作) + [分析] button
    4. Empty-state fallback when no data

The [分析] button is a 2-step flow (jump to analyze tab + pre-fill, not
1-click direct) so users can confirm ticker + change date before consuming
LLM tokens.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date as _date
from typing import Any

import streamlit as st


# ── Pure helpers (unit-testable, no streamlit dependency) ─────────────────


def parse_pct(s: Any) -> float:
    """Parse a percentage string like '+10.01%' or '-3.5%' to float.

    Returns 0.0 for unparseable values (no exception, no warning).
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


def block_avg_ratio(stocks: list[dict]) -> float:
    """Compute the simple-average block ratio (板块涨幅).

    Uses each stock's ``ratio`` field (百度 PAE block daily change %).
    Returns 0.0 for an empty list.
    """
    if not stocks:
        return 0.0
    return sum(parse_pct(s.get("ratio", 0)) for s in stocks) / len(stocks)


def block_key(name: str) -> str:
    """Stable short hash of block name (for streamlit widget keys)."""
    return hashlib.md5(name.encode("utf-8")).hexdigest()[:8]


def sort_blocks(blocks: dict[str, list[dict]]) -> list[tuple[str, list[dict]]]:
    """Sort concept blocks by stock count desc, then by avg ratio desc.

    Tie-breaker: alphabetical by block name (stable for tests).
    """
    return sorted(
        blocks.items(),
        key=lambda kv: (-len(kv[1]), -block_avg_ratio(kv[1]), kv[0]),
    )


def filter_blocks(
    blocks: list[tuple[str, list[dict]]],
    min_count: int,
    search: str,
) -> list[tuple[str, list[dict]]]:
    """Apply min-count + search filter (in-memory, no I/O).

    Search matches block name OR any stock's code/name (case-insensitive
    on code, substring on name).
    """
    needle = search.strip().upper()
    out: list[tuple[str, list[dict]]] = []
    for name, stocks in blocks:
        if len(stocks) < min_count:
            continue
        if needle:
            name_hit = needle in name.upper()
            stock_hit = any(
                needle in s.get("code", "").upper()
                or needle in s.get("name", "")
                for s in stocks
            )
            if not (name_hit or stock_hit):
                continue
        out.append((name, stocks))
    return out


def zhangfu_signal_cls(value: str) -> str:
    """Return bb-signal CSS class for a % value string.

    ≥+9.5% → buy (limit-up), ≤-0.5% → sell, ≥+2% → hold, else neutral.
    """
    v = parse_pct(value)
    if v >= 9.5:
        return "bb-signal bb-signal--buy"
    if v <= -0.5:
        return "bb-signal bb-signal--sell"
    if v >= 2.0:
        return "bb-signal bb-signal--hold"
    return "bb-signal bb-signal--neutral"


# ── Sub-renderers ────────────────────────────────────────────────────────


def _render_meta(sources_ok: dict[str, bool]) -> None:
    """3-source status row: ✓/✗ np-ipick · ths · baidu + 重试 button."""
    labels = [
        ("np_ipick", "东财 np-ipick"),
        ("ths_limitup", "同花顺 涨停"),
        ("baidu_pae", "百度 PAE"),
    ]
    parts: list[str] = []
    for key, label in labels:
        ok = sources_ok.get(key, False)
        cls = "bb-sector-meta-ok" if ok else "bb-sector-meta-fail"
        glyph = "✓" if ok else "✗"
        parts.append(f'<span class="{cls}">{glyph} {label}</span>')
    st.html(
        f'<div class="bb-sector-meta">{"&nbsp;·&nbsp;".join(parts)}</div>'
    )


def _render_strategies(strategies: list[dict]) -> None:
    """Top-N institution strategies as collapsed expander."""
    with st.expander(
        f"📌 机构选股策略 Top {len(strategies)} (np-ipick 热度)",
        expanded=False,
    ):
        if not strategies:
            st.html(
                '<div class="bb-sector-meta bb-sector-meta-fail">'
                "数据源 np-ipick 不可用</div>"
            )
            return
        for s in strategies[:3]:
            q = s.get("question", "")[:80]
            heat = s.get("heatValue", 0)
            rank = s.get("rank", "-")
            st.html(
                f'<div class="bb-section-label">'
                f'<span style="color:var(--bb-accent)">#{rank}</span> '
                f"heat={heat}</div>"
                f'<div style="font-size:0.85rem;color:var(--text-primary);'
                f'margin-bottom:0.4rem">{q}</div>'
            )


def _render_block_table(stocks: list[dict], block_key_hash: str) -> None:
    """Single block's stock table with [分析] buttons."""
    # Header
    cols = st.columns([1, 1, 3, 1.2, 0.8])
    headers = ["代码", "名称", "题材", "板块涨幅", "操作"]
    for col, h in zip(cols, headers):
        col.markdown(
            f'<div class="bb-section-label">{h}</div>',
            unsafe_allow_html=True,
        )

    for stock in stocks:
        code = stock.get("code", "")
        name = stock.get("name", "")
        reason = stock.get("reason", "-") or "-"
        ratio = stock.get("ratio", "-")

        c1, c2, c3, c4, c5 = st.columns([1, 1, 3, 1.2, 0.8])
        with c1:
            st.html(f'<div class="bb-table-cell">{code}</div>')
        with c2:
            st.html(f'<div class="bb-table-cell">{name}</div>')
        with c3:
            st.markdown(
                f'<div style="font-size:0.78rem;color:var(--text-secondary)">{reason}</div>',
                unsafe_allow_html=True,
            )
        with c4:
            st.html(f'<div class="{zhangfu_signal_cls(ratio)}">{ratio}</div>')
        with c5:
            _render_analyze_button(code, block_key_hash)


def _render_analyze_button(code: str, block_key_hash: str) -> None:
    """[分析] button → 2-step jump to analyze tab + pre-fill."""
    btn_key = f"analyze_{code}_{block_key_hash}"
    if not st.button("分析", key=btn_key, type="secondary"):
        return

    tracker = st.session_state.get("tracker")
    if tracker is not None and getattr(tracker, "is_running", False):
        st.warning("已有进行中的分析, 请等待完成")
        return

    st.session_state["start_analysis"] = {
        "ticker": code,
        "trade_date": _date.today().strftime("%Y-%m-%d"),
    }
    st.session_state["nav"] = "analyze"
    st.session_state["viewing_history"] = None
    st.rerun()


def _render_block(
    name: str,
    stocks: list[dict],
    expanded: bool,
    idx: int,
) -> None:
    """One concept block as expander with table inside."""
    n = len(stocks)
    avg = block_avg_ratio(stocks)
    avg_str = f"{avg:+.2f}%"
    # First 3 blocks expand by default; user toggle overrides via session_state
    expand_key = f"sector_block_expand_{block_key(name)}"
    if expand_key not in st.session_state:
        st.session_state[expand_key] = expanded

    label = f"📊 {name} · {n} 只涨停 · 板块涨幅 {avg_str}"
    with st.expander(label, expanded=bool(st.session_state[expand_key])):
        _render_block_table(stocks, block_key(name))


def _render_blocks(blocks: dict[str, list[dict]]) -> None:
    """Top toolbar (search + min) + all concept blocks."""
    # Toolbar
    tc1, tc2 = st.columns([3, 1])
    with tc1:
        st.text_input(
            "搜索",
            placeholder="代码 / 名称 / 板块名 (例: 300, 宁德, 电池)",
            key="sector_search",
        )
    with tc2:
        st.selectbox(
            "仅看 ≥",
            [1, 2, 3, 5, 10],
            index=2,  # default 3
            key="sector_min",
        )

    search = st.session_state.get("sector_search", "")
    min_count = int(st.session_state.get("sector_min", 3))

    sorted_blocks = sort_blocks(blocks)
    filtered = filter_blocks(sorted_blocks, min_count, search)

    if not filtered:
        st.html(
            '<div class="bb-sector-empty">'
            "没有匹配的板块 (尝试调低'仅看 ≥'或清空搜索)"
            "</div>"
        )
        return

    total_stocks = sum(len(s) for _, s in filtered)
    n_blocks = len(filtered)
    st.html(
        f'<div class="bb-section-label">'
        f"{total_stocks} 只涨停 · {n_blocks} 个概念板块 · 按股票数降序"
        "</div>"
    )

    for i, (name, stocks) in enumerate(filtered):
        _render_block(name, stocks, expanded=(i < 3), idx=i)


def _render_flat_hot_stocks(hot_stocks: list[dict]) -> None:
    """Fallback: concept_blocks empty but hot_stocks has data → flat table."""
    st.html(
        '<div class="bb-section-label">'
        f"📈 涨停热点股 Top {len(hot_stocks)} (无概念板块聚类数据)"
        "</div>"
    )
    _render_block_table(hot_stocks, block_key("__flat__"))


def _render_empty_state() -> None:
    """All-empty fallback."""
    st.html(
        '<div class="bb-sector-empty">'
        "📭 今日无涨停股, 可能非交易日或数据源全部失败<br>"
        "<span style='font-size:0.8rem;color:var(--text-tertiary)'>"
        "可点击上方「重试」重新拉取</span></div>"
    )


# ── Public entry ────────────────────────────────────────────────────────


def _fetch_digest() -> tuple[Any | None, str | None]:
    """Load cached digest or fetch a fresh one. Returns (digest, error_msg)."""
    digest = st.session_state.get("sector_digest_cache")
    if digest is not None:
        return digest, None

    first_load = "sector_digest_cache" not in st.session_state
    with st.spinner("正在拉取板块轮动数据,预计 15-25 秒..."):
        try:
            from tradingagents.dataflows.interface import route_to_vendor
            digest = route_to_vendor("get_sector_rotation_digest", "", 20)
            st.session_state["sector_digest_cache"] = digest
            return digest, None
        except Exception as exc:  # noqa: BLE001 — surface to UI
            err = f"加载失败: {exc}"
            if first_load:
                err += "\n\n提示:可在 '设置' 页配置数据源代理,或稍后重试。"
            return None, err


def _render_header() -> None:
    """Page title + caption + refresh button."""
    st.markdown("## 🔄 板块轮动日报")
    st.caption(
        "当日 A 股板块轮动快照:东财选股热度(机构/编辑视角) + 同花顺涨停归因"
        " + 百度 PAE 概念反查。无需 LLM,直接展示数据。预期 15-25 秒。"
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button(
            "🔄  拉取最新",
            key="sector_refresh",
            type="primary",
            use_container_width=True,
        ):
            st.session_state["sector_digest_cache"] = None
            st.rerun()
    with col2:
        st.caption("提示:交易日 9:30-15:00 数据最完整。")


def render_sector_panel() -> None:
    """Main entry — replaces the inline sector tab in app.py.

    Fetches (or reuses cached) ``SectorRotationDigest`` and renders the
    toolbar / strategy expander / concept-block tables.
    """
    _render_header()

    digest, err = _fetch_digest()
    if err:
        st.error(err)
        if st.button("🔄 重试", key="sector_retry_after_error", type="primary"):
            st.session_state["sector_digest_cache"] = None
            st.rerun()
        return

    if digest is None:
        st.info("点击 '🔄  拉取最新' 获取板块轮动日报。")
        return

    sources_ok = getattr(digest, "sources_ok", {}) or {}
    _render_meta(sources_ok)

    strategies = getattr(digest, "hot_strategies", []) or []
    _render_strategies(strategies)

    st.markdown("---")

    concept_blocks = getattr(digest, "concept_blocks", {}) or {}
    hot_stocks = getattr(digest, "hot_stocks", []) or []

    if concept_blocks:
        _render_blocks(concept_blocks)
    elif hot_stocks:
        _render_flat_hot_stocks(hot_stocks)
    else:
        _render_empty_state()
