"""Tab 5 — 导入/导出.

上传 CSV → 自动 detect format → 预览 (new / conflicts / invalid) → 选
resolution → 导入;下载 (positions / transactions);最近 5 条 audit log。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import streamlit as st

from backend.core.portfolio_import import (
    CSV_FORMATS,
    apply_import,
    detect_format,
    export_csv,
    export_transactions_csv,
    parse_csv,
    preview_import,
)
from backend.core.portfolio_store import AUDIT_FILE, PORTFOLIO_DIR, Position, Transaction
from web.components.portfolio_dialogs import format_currency, format_pct


# ── Pure helpers (unit-testable) ────────────────────────────────────────


def list_audit_lines(audit_file: Path, limit: int = 5) -> list[str]:
    """Read last N lines from audit.log, falling back to [] on missing file."""
    if not audit_file.exists():
        return []
    try:
        text = audit_file.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-limit:]


def preview_summary_counts(preview: dict[str, Any]) -> dict[str, int]:
    """Compact {new, conflicts, invalid} counts for the preview header."""
    return {
        "new": len(preview.get("new", [])),
        "conflicts": len(preview.get("conflicts", [])),
        "invalid": len(preview.get("invalid", [])),
    }


# ── Streamlit renderers ────────────────────────────────────────────────


def _render_import_section(existing_positions: list[Position]) -> None:
    """Upload → detect → preview → apply flow."""
    st.markdown(
        '<div class="bb-section-label">📥 导入 CSV</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"支持 4 种格式: {', '.join(CSV_FORMATS.keys())}。"
        "上传后自动检测,可在预览后选 overwrite / skip / merge 解决冲突。"
    )

    uploaded = st.file_uploader(
        "选择 CSV 文件",
        type=["csv"],
        key="import_csv_uploader",
        help="支持 东方财富 / 同花顺 / 雪球 / 通用 4 种列名映射",
    )

    if uploaded is None:
        st.session_state.pop("import_preview", None)
        return

    # Persist upload to a temp path so backend functions can read it.
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".csv", delete=False
    ) as tmp:
        tmp.write(uploaded.read())
        tmp_path = Path(tmp.name)

    detected = detect_format(tmp_path)
    if detected is None:
        st.error(
            f"⚠️ 无法识别格式。表头与已知 4 种格式都不匹配。"
            f"已知格式: {', '.join(CSV_FORMATS.keys())}"
        )
        return
    st.info(f"✅ 检测到格式: **{detected}**")

    # Manual override option
    format_choice = st.selectbox(
        "格式 (可手动覆盖)",
        options=list(CSV_FORMATS.keys()),
        index=list(CSV_FORMATS.keys()).index(detected),
        key="import_format_override",
    )

    try:
        parsed = parse_csv(tmp_path, format_choice)
    except Exception as exc:  # noqa: BLE001
        st.error(f"解析失败: {exc}")
        return
    if not parsed:
        st.warning("⚠️ 文件解析为空 (无有效行)。")
        return

    preview = preview_import(parsed, existing_positions)
    counts = preview_summary_counts(preview)

    # Preview table
    st.html(
        f'<div class="bb-portfolio-preview-summary">'
        f'📊 解析: <b>{len(parsed)}</b> 行 · '
        f'新持仓 <b>{counts["new"]}</b> · '
        f'冲突 <b>{counts["conflicts"]}</b> · '
        f'无效 <b>{counts["invalid"]}</b>'
        f'</div>'
    )

    # Show the new rows
    new_rows = preview.get("new", [])
    if new_rows:
        with st.expander(f"🆕 新增 ({counts['new']})", expanded=True):
            for row in new_rows:
                st.html(
                    f'<div class="bb-portfolio-td">'
                    f'· {row.ticker} {row.name or "(无名称)"} · '
                    f'成本 {row.cost:.4f} · 数量 {row.quantity:,} · '
                    f'日期 {row.date}'
                    f'</div>'
                )
    conflicts = preview.get("conflicts", [])
    if conflicts:
        with st.expander(f"⚠️ 冲突 ({counts['conflicts']})", expanded=True):
            for c in conflicts:
                p = c["parsed"]
                e = c["existing"]
                st.html(
                    f'<div class="bb-portfolio-td">'
                    f'· {p.ticker} (CSV 成本 {p.cost:.4f} / 数量 {p.quantity:,} / {p.date} '
                    f'<b>vs</b> 现有 成本 {e.cost_basis:.4f} / 数量 {e.quantity:,})'
                    f'</div>'
                )

    # Resolution + apply
    st.session_state.setdefault("import_preview", preview)
    st.session_state["import_preview"] = preview
    st.session_state["import_format"] = format_choice

    resolution = st.radio(
        "冲突解决策略",
        options=["overwrite", "skip", "merge"],
        index=1,  # default: skip
        format_func=lambda x: {
            "overwrite": "覆盖 (overwrite)",
            "skip": "跳过 (skip)",
            "merge": "合并 (merge - 加权平均)",
        }[x],
        key="import_resolution",
        horizontal=True,
    )

    if st.button("✅ 应用导入", type="primary", key="import_apply"):
        from backend.core.portfolio_store import get_portfolio_store
        store = get_portfolio_store()
        try:
            created = apply_import(
                preview, resolution, store,
                file_path=str(tmp_path), row_count=len(parsed),
            )
        except (ValueError, KeyError) as exc:
            st.error(f"导入失败: {exc}")
            return
        st.success(f"✅ 已导入 {len(created)} 条持仓 (策略: {resolution})")
        st.session_state.pop("import_preview", None)
        st.rerun()


def _render_export_section(
    positions: list[Position],
    transactions: list[Transaction],
) -> None:
    """Download buttons for positions and transactions CSVs."""
    st.markdown(
        '<div class="bb-section-label">📤 导出 CSV</div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📤 导出持仓 CSV", key="export_positions_btn",
                     use_container_width=True):
            try:
                path = export_csv(positions, transactions)
                st.success(f"✅ 已导出: {path}")
            except OSError as exc:
                st.error(f"导出失败: {exc}")
    with c2:
        if st.button("📤 导出流水 CSV", key="export_transactions_btn",
                     use_container_width=True):
            if not transactions:
                st.warning("⚠️ 暂无交易记录可导出。")
            else:
                try:
                    path = export_transactions_csv(transactions)
                    st.success(f"✅ 已导出: {path}")
                except OSError as exc:
                    st.error(f"导出失败: {exc}")


def _render_audit_log() -> None:
    """Last 5 audit log lines."""
    st.markdown(
        '<div class="bb-section-label">📜 最近操作 (audit.log)</div>',
        unsafe_allow_html=True,
    )
    lines = list_audit_lines(PORTFOLIO_DIR / AUDIT_FILE, limit=5)
    if not lines:
        st.caption("(暂无记录)")
        return
    for ln in lines:
        st.html(f'<div class="bb-portfolio-audit-line">{ln}</div>')


def render_import_tab(
    positions: list[Position],
    transactions: list[Transaction],
) -> None:
    """Public entry: render the import/export tab inside the portfolio panel."""
    _render_import_section(positions)
    st.markdown("---")
    _render_export_section(positions, transactions)
    st.markdown("---")
    _render_audit_log()


__all__ = [
    "list_audit_lines",
    "preview_summary_counts",
    "render_import_tab",
]
