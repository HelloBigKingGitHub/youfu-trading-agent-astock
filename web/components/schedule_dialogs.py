"""Schedule add/edit dialog — cron picker + source config + notify channels.

Streamlit ``st.dialog`` (1.58+) wraps the underlying modal. As with
``portfolio_dialogs``, every non-trivial bit of logic lives in a pure helper
(``validate_cron`` / ``next_run_preview`` / ``parse_manual_tickers`` / …) so
the unit tests can exercise it without a live Streamlit context. The dialog
body itself only wires those helpers to widgets and the ``Scheduler`` singleton.

Design constraints (v0.6.0 Phase 2):
  - name required
  - cron validated live → invalid disables the save buttons + red error
  - live "下次执行" preview via ``croniter.get_next()``
  - source radio: 持仓 / 自选股 / 手动
      * 持仓  → no extra config
      * 自选股 → tag selectbox from ``VALID_TAGS``
      * 手动  → comma-separated tickers text input
  - 4 notify checkboxes: WeCom / Email / Desktop / Log
  - enabled checkbox (default True)
  - footer: [取消] [保存] [保存并立即跑]
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import streamlit as st

from backend.core.scheduler import (
    VALID_CRON_HELPERS,
    Schedule,
    Scheduler,
    SourceType,
)
from backend.core.watchlist import VALID_TAGS

# ── Constants (exported for tests) ────────────────────────────────────────

# 5 one-click cron presets. Kept identical to scheduler.VALID_CRON_HELPERS so
# a drift between UI and backend is impossible (tested).
CRON_HELPERS: dict[str, str] = dict(VALID_CRON_HELPERS)

SOURCE_LABELS: dict[str, str] = {
    SourceType.PORTFOLIO.value: "持仓",
    SourceType.WATCHLIST.value: "自选股",
    SourceType.MANUAL.value: "手动",
}

# Notify channel id → display label. Order is stable for a deterministic UI.
NOTIFY_CHANNELS: list[tuple[str, str]] = [
    ("wecom", "WeCom"),
    ("email", "Email"),
    ("desktop", "Desktop"),
    ("log", "Log"),
]

# Sorted for a deterministic selectbox order.
WATCHLIST_TAGS: list[str] = sorted(VALID_TAGS)


# ── Pure helpers (no streamlit, unit-testable) ───────────────────────────


def validate_cron(cron_expr: str) -> str | None:
    """Return None if the cron expression is valid, else an error message."""
    if not cron_expr or not cron_expr.strip():
        return "cron 表达式不能为空"
    try:
        from croniter import croniter

        if not croniter.is_valid(cron_expr.strip()):
            return f"cron 表达式无效: {cron_expr!r}"
    except Exception:  # noqa: BLE001 — croniter raises assorted validation errors
        return f"cron 表达式无效: {cron_expr!r}"
    return None


def next_run_preview(cron_expr: str, now: float | None = None) -> str | None:
    """Return the next fire time as ``YYYY-MM-DD HH:MM:SS`` or None if invalid."""
    if validate_cron(cron_expr) is not None:
        return None
    try:
        from croniter import croniter

        base = time.time() if now is None else now
        nxt = float(croniter(cron_expr.strip(), base).get_next())
        return datetime.fromtimestamp(nxt).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return None


def parse_manual_tickers(raw: str) -> list[str]:
    """Split a comma-separated ticker string into a clean 6-digit list.

    Accepts Chinese / ASCII commas and whitespace; keeps only 6-digit codes,
    de-duplicated while preserving order.
    """
    if not raw:
        return []
    parts = raw.replace("，", ",").replace(" ", ",").replace("\n", ",").split(",")
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        t = p.strip()
        if len(t) == 6 and t.isdigit() and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_source_config(source_type: str, tag: str, manual_raw: str) -> dict:
    """Assemble the ``source_config`` dict for the given source type."""
    if source_type == SourceType.WATCHLIST.value:
        return {"tag": tag} if tag else {}
    if source_type == SourceType.MANUAL.value:
        return {"tickers": parse_manual_tickers(manual_raw)}
    return {}


def validate_schedule_form(
    name: str,
    cron_expr: str,
    source_type: str,
    source_config: dict,
) -> str | None:
    """Full form validator mirroring ``Schedule.validate`` for pre-submit UX."""
    if not name or not name.strip():
        return "名称不能为空"
    cron_err = validate_cron(cron_expr)
    if cron_err:
        return cron_err
    if source_type == SourceType.MANUAL.value and not source_config.get("tickers"):
        return "手动源必须指定至少 1 个 6 位 ticker"
    return None


# ── Dialog ────────────────────────────────────────────────────────────────


@st.dialog("⏰ 新增 / 编辑 定时任务", width="large")
def _add_edit_dialog(schedule_id: str | None = None) -> None:
    """Modal form to create or edit a :class:`Schedule`.

    ``schedule_id=None`` → create; otherwise pre-fill from the store and update.
    """
    sched_mgr = Scheduler.get_instance()
    existing: Schedule | None = (
        sched_mgr.get_schedule(schedule_id) if schedule_id else None
    )
    kp = schedule_id or "new"  # key prefix so create + edit don't collide

    st.markdown('<div class="bb-schedule-dialog">配置一个 cron 定时分析任务</div>',
                unsafe_allow_html=True)

    name = st.text_input(
        "任务名称 *",
        value=existing.name if existing else "",
        key=f"sched_name_{kp}",
        placeholder="例: 每日持仓复盘",
    ).strip()

    # ── cron + 5 helper buttons ──────────────────────────────────────────
    cron_state_key = f"sched_cron_val_{kp}"
    if cron_state_key not in st.session_state:
        st.session_state[cron_state_key] = existing.cron_expr if existing else "0 18 * * 1-5"

    st.caption("cron 表达式 (分 时 日 月 周) — 点下方按钮一键填入")
    helper_cols = st.columns(len(CRON_HELPERS))
    for col, (label, expr) in zip(helper_cols, CRON_HELPERS.items()):
        with col:
            if st.button(label, key=f"sched_cron_help_{kp}_{expr}",
                         use_container_width=True):
                st.session_state[cron_state_key] = expr
                st.rerun()

    cron_expr = st.text_input(
        "cron *",
        key=cron_state_key,
        placeholder="0 18 * * 1-5",
    ).strip()

    cron_err = validate_cron(cron_expr)
    if cron_err:
        st.error(f"❌ {cron_err}")
    else:
        preview = next_run_preview(cron_expr)
        st.caption(f"⏰ 下次执行: {preview}")

    # ── source ────────────────────────────────────────────────────────────
    source_values = [
        SourceType.PORTFOLIO.value,
        SourceType.WATCHLIST.value,
        SourceType.MANUAL.value,
    ]
    default_source_idx = 0
    if existing:
        src_val = (
            existing.source_type.value
            if isinstance(existing.source_type, SourceType)
            else existing.source_type
        )
        if src_val in source_values:
            default_source_idx = source_values.index(src_val)

    source_type = st.radio(
        "ticker 来源 *",
        options=source_values,
        index=default_source_idx,
        format_func=lambda v: SOURCE_LABELS.get(v, v),
        horizontal=True,
        key=f"sched_source_{kp}",
    )

    tag = ""
    manual_raw = ""
    if source_type == SourceType.WATCHLIST.value:
        existing_tag = (existing.source_config.get("tag") if existing else None) or WATCHLIST_TAGS[0]
        tag = st.selectbox(
            "自选股标签",
            options=WATCHLIST_TAGS,
            index=WATCHLIST_TAGS.index(existing_tag) if existing_tag in WATCHLIST_TAGS else 0,
            key=f"sched_tag_{kp}",
        )
    elif source_type == SourceType.MANUAL.value:
        existing_tickers = existing.source_config.get("tickers", []) if existing else []
        manual_raw = st.text_input(
            "tickers (逗号分隔)",
            value=",".join(existing_tickers),
            key=f"sched_manual_{kp}",
            placeholder="600595,688017,300750",
        )
    else:  # portfolio
        st.caption("将分析当前所有持仓 ticker (无需额外配置)")

    source_config = build_source_config(source_type, tag, manual_raw)

    # ── notify channels ─────────────────────────────────────────────────────
    st.caption("完成后通知渠道")
    existing_channels = set(existing.notify_channels) if existing else {"log"}
    notify_cols = st.columns(len(NOTIFY_CHANNELS))
    selected_channels: list[str] = []
    for col, (cid, clabel) in zip(notify_cols, NOTIFY_CHANNELS):
        with col:
            if st.checkbox(
                clabel,
                value=cid in existing_channels,
                key=f"sched_notify_{kp}_{cid}",
            ):
                selected_channels.append(cid)

    enabled = st.checkbox(
        "启用",
        value=existing.enabled if existing else True,
        key=f"sched_enabled_{kp}",
    )

    # ── footer: 取消 / 保存 / 保存并立即跑 ─────────────────────────────────
    form_err = validate_schedule_form(name, cron_expr, source_type, source_config)
    can_save = form_err is None

    c1, c2, c3 = st.columns(3)
    if c1.button("取消", key=f"sched_cancel_{kp}", use_container_width=True):
        _close_dialog(kp)
        st.rerun()

    save_clicked = c2.button(
        "保存", type="primary", key=f"sched_save_{kp}",
        use_container_width=True, disabled=not can_save,
    )
    run_clicked = c3.button(
        "保存并立即跑", key=f"sched_save_run_{kp}",
        use_container_width=True, disabled=not can_save,
    )

    if not (save_clicked or run_clicked):
        return

    if form_err:
        st.error(form_err)
        return

    sched = _build_schedule(existing, name, cron_expr, source_type,
                            source_config, selected_channels, enabled)
    try:
        if existing:
            sched_mgr.update_schedule(sched)
        else:
            sched_mgr.add_schedule(sched)
    except (ValueError, KeyError) as exc:
        st.error(f"保存失败: {exc}")
        return

    if run_clicked:
        try:
            batch_id = sched_mgr.run_now(sched.schedule_id)
            st.success(f"已保存并触发运行: {batch_id}")
        except KeyError as exc:
            st.error(f"立即运行失败: {exc}")
            return
    else:
        st.success("已保存")

    _close_dialog(kp)
    st.rerun()


# ── Internal helpers ──────────────────────────────────────────────────────


def _build_schedule(
    existing: Schedule | None,
    name: str,
    cron_expr: str,
    source_type: str,
    source_config: dict,
    channels: list[str],
    enabled: bool,
) -> Schedule:
    """Assemble a Schedule from form values (preserving id/created_at on edit)."""
    return Schedule(
        schedule_id=existing.schedule_id if existing else "",
        name=name,
        cron_expr=cron_expr,
        source_type=SourceType(source_type),
        source_config=source_config,
        enabled=enabled,
        notify_channels=channels or ["log"],
        notify_template=existing.notify_template if existing else "v0.6.0 default",
        config=existing.config if existing else {},
        created_at=existing.created_at if existing else time.time(),
        created_by=existing.created_by if existing else "user",
    )


def _close_dialog(kp: str) -> None:
    """Clear the "which schedule is open" flag + this form's cron state."""
    st.session_state.pop("schedule_dialog_open", None)
    st.session_state.pop("schedule_edit_id", None)
    st.session_state.pop(f"sched_cron_val_{kp}", None)


def open_schedule_dialog(schedule_id: str | None = None) -> None:
    """Public entry — panel buttons call this to open the modal."""
    try:
        _add_edit_dialog(schedule_id)
    except Exception as exc:  # noqa: BLE001
        # Bare-mode / no-ScriptRunContext: @st.dialog .open() raises here.
        # We swallow so the test environment (and accidental headless runs)
        # get a no-op instead of a crash. UI code itself never hits this
        # branch in production because script_run is always present.
        import logging
        logging.getLogger(__name__).debug(
            "schedule_dialog open skipped (no ScriptRunContext?): %s", exc
        )


__all__ = [
    "CRON_HELPERS",
    "SOURCE_LABELS",
    "NOTIFY_CHANNELS",
    "WATCHLIST_TAGS",
    "validate_cron",
    "next_run_preview",
    "parse_manual_tickers",
    "build_source_config",
    "validate_schedule_form",
    "open_schedule_dialog",
]
