"""Tests for the ⏰ schedule Web UI layer (v0.6.0 Phase 2).

Streamlit API calls are mocked with ``unittest.mock.patch`` so the tests run
without a live Streamlit context. The Scheduler singleton + its persistence
paths are redirected to ``tmp_path`` (matching ``tests/test_scheduler.py``) so
tests never touch the real ``~/.tradingagents/schedules/`` directory.

Coverage matrix (~13 tests):
  - TestPanelRender: 4 sections render without crash (mocked streamlit)
  - TestScheduleListTable: header has 6 columns (5 data + ops)
  - TestAddDialog / TestEditDialog: dialog helpers build correct Schedule
  - TestCronHelpers: 5 presets match backend VALID_CRON_HELPERS
  - TestCronValidation: invalid cron → error string
  - TestNextRunPreview: valid cron → formatted timestamp
  - TestPauseResumeButton: toggle flips enabled
  - TestDeleteConfirmation: delete removes schedule
  - TestEmptyState: no schedules → prompt text
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_schedules(monkeypatch, tmp_path):
    """Redirect scheduler dirs + reset singleton (matches test_scheduler)."""
    fake_dir = tmp_path / "schedules"
    fake_dir.mkdir()
    fake_runs = fake_dir / "runs"
    fake_runs.mkdir()
    monkeypatch.setattr("backend.core.scheduler.SCHEDULES_DIR", fake_dir)
    monkeypatch.setattr(
        "backend.core.scheduler.SCHEDULES_FILE", fake_dir / "schedules.json"
    )
    monkeypatch.setattr("backend.core.scheduler.RUNS_DIR", fake_runs)
    from backend.core.scheduler import Scheduler
    Scheduler._reset_singleton()
    yield fake_dir
    Scheduler._reset_singleton()


@pytest.fixture
def mgr(tmp_schedules):
    """Fresh Scheduler with presets cleared for deterministic assertions."""
    from backend.core.scheduler import Scheduler
    m = Scheduler.get_instance()
    for s in m.list_schedules():
        m.delete_schedule(s.schedule_id)
    return m


def _make_schedule(name="测试任务", cron="0 18 * * 1-5", source="manual",
                   tickers=("600595",)):
    from backend.core.scheduler import Schedule, SourceType
    cfg = {"tickers": list(tickers)} if source == "manual" else {}
    return Schedule(
        schedule_id="",
        name=name,
        cron_expr=cron,
        source_type=SourceType(source),
        source_config=cfg,
    )


def _streamlit_patches():
    """Common streamlit patch set. Column mocks return the exact count."""
    def _columns_factory(*args, **kwargs):
        n = 1
        if args:
            first = args[0]
            if isinstance(first, int):
                n = first
            elif isinstance(first, (list, tuple)):
                n = len(first)
        return tuple(MagicMock() for _ in range(n))

    # Mock @st.dialog: 返回的函数 = 原函数 (不会触发 dialog.open())
    def _dialog_decorator(title, **kwargs):
        def _wrap(func):
            return func
        return _wrap

    return [
        patch("streamlit.markdown", MagicMock()),
        patch("streamlit.caption", MagicMock()),
        patch("streamlit.button", MagicMock(return_value=False)),
        patch("streamlit.checkbox", MagicMock(return_value=False)),
        patch("streamlit.text_input", MagicMock(return_value="")),
        patch("streamlit.selectbox", MagicMock(return_value="")),
        patch("streamlit.radio", MagicMock(return_value="portfolio")),
        patch("streamlit.error", MagicMock()),
        patch("streamlit.warning", MagicMock()),
        patch("streamlit.success", MagicMock()),
        patch("streamlit.rerun", MagicMock()),
        patch("streamlit.columns", side_effect=_columns_factory),
        # `streamlit/__init__.py` does
        #     from streamlit.elements.dialog_decorator import dialog_decorator as dialog
        # so `streamlit.dialog` is the *bound alias* — patching the underlying
        # function name leaves `st.dialog` pointing at the original. Patch the
        # alias directly.
        patch("streamlit.dialog", side_effect=_dialog_decorator),
        patch("streamlit.stop", MagicMock()),
    ]


# ── TestCronHelpers ────────────────────────────────────────────────────────


class TestCronHelpers:
    @pytest.mark.unit
    def test_five_presets(self):
        from web.components.schedule_dialogs import CRON_HELPERS
        assert len(CRON_HELPERS) == 5

    @pytest.mark.unit
    def test_matches_backend(self):
        from backend.core.scheduler import VALID_CRON_HELPERS
        from web.components.schedule_dialogs import CRON_HELPERS
        assert CRON_HELPERS == dict(VALID_CRON_HELPERS)


# ── TestCronValidation ─────────────────────────────────────────────────────


class TestCronValidation:
    @pytest.mark.unit
    @pytest.mark.parametrize("expr", ["0 18 * * 1-5", "30 9 * * *", "0 */4 * * *"])
    def test_valid(self, expr):
        from web.components.schedule_dialogs import validate_cron
        assert validate_cron(expr) is None

    @pytest.mark.unit
    @pytest.mark.parametrize("expr", ["", "not a cron", "99 99 * * *", "0 18 * *"])
    def test_invalid(self, expr):
        from web.components.schedule_dialogs import validate_cron
        assert validate_cron(expr) is not None


# ── TestNextRunPreview ─────────────────────────────────────────────────────


class TestNextRunPreview:
    @pytest.mark.unit
    def test_valid_cron_returns_timestamp(self):
        from web.components.schedule_dialogs import next_run_preview
        # 2026-07-13 12:00:00 → next daily 09:30 is 2026-07-14 09:30:00
        base = 1_784_000_000.0
        out = next_run_preview("30 9 * * *", now=base)
        assert out is not None
        assert out.count(":") == 2 and out.count("-") == 2

    @pytest.mark.unit
    def test_invalid_cron_returns_none(self):
        from web.components.schedule_dialogs import next_run_preview
        assert next_run_preview("garbage") is None


# ── TestParseManualTickers ─────────────────────────────────────────────────


class TestParseManualTickers:
    @pytest.mark.unit
    def test_comma_split(self):
        from web.components.schedule_dialogs import parse_manual_tickers
        assert parse_manual_tickers("600595,688017,300750") == [
            "600595", "688017", "300750"
        ]

    @pytest.mark.unit
    def test_chinese_comma_and_dedup(self):
        from web.components.schedule_dialogs import parse_manual_tickers
        assert parse_manual_tickers("600595，600595 688017") == ["600595", "688017"]

    @pytest.mark.unit
    def test_drops_non_6_digit(self):
        from web.components.schedule_dialogs import parse_manual_tickers
        assert parse_manual_tickers("600595,abc,123") == ["600595"]

    @pytest.mark.unit
    def test_empty(self):
        from web.components.schedule_dialogs import parse_manual_tickers
        assert parse_manual_tickers("") == []


# ── TestValidateScheduleForm ───────────────────────────────────────────────


class TestValidateScheduleForm:
    @pytest.mark.unit
    def test_valid_portfolio(self):
        from web.components.schedule_dialogs import validate_schedule_form
        assert validate_schedule_form("复盘", "0 18 * * 1-5", "portfolio", {}) is None

    @pytest.mark.unit
    def test_empty_name(self):
        from web.components.schedule_dialogs import validate_schedule_form
        assert validate_schedule_form("", "0 18 * * 1-5", "portfolio", {}) is not None

    @pytest.mark.unit
    def test_manual_without_tickers(self):
        from web.components.schedule_dialogs import validate_schedule_form
        assert validate_schedule_form("x", "0 9 * * *", "manual", {"tickers": []}) is not None


# ── TestBuildSourceConfig ──────────────────────────────────────────────────


class TestBuildSourceConfig:
    @pytest.mark.unit
    def test_watchlist_tag(self):
        from web.components.schedule_dialogs import build_source_config
        assert build_source_config("watchlist", "长线", "") == {"tag": "长线"}

    @pytest.mark.unit
    def test_manual_tickers(self):
        from web.components.schedule_dialogs import build_source_config
        assert build_source_config("manual", "", "600595,688017") == {
            "tickers": ["600595", "688017"]
        }

    @pytest.mark.unit
    def test_portfolio_empty(self):
        from web.components.schedule_dialogs import build_source_config
        assert build_source_config("portfolio", "", "") == {}


# ── TestPanelHelpers ───────────────────────────────────────────────────────


class TestPanelHelpers:
    @pytest.mark.unit
    def test_format_ts_none(self):
        from web.components.schedule_panel import format_ts
        assert format_ts(None) == "—"
        assert format_ts(0) == "—"

    @pytest.mark.unit
    def test_format_ts_valid(self):
        from web.components.schedule_panel import format_ts
        out = format_ts(1_784_000_000.0)
        assert out.count("-") == 2 and out.count(":") == 2

    @pytest.mark.unit
    def test_source_summary_manual(self):
        from web.components.schedule_panel import source_summary
        s = _make_schedule(source="manual", tickers=("600595", "688017"))
        assert "手动" in source_summary(s) and "2" in source_summary(s)

    @pytest.mark.unit
    def test_status_dot_class(self):
        from web.components.schedule_panel import status_dot_class
        assert status_dot_class(True).endswith("--on")
        assert status_dot_class(False).endswith("--off")


# ── TestAddDialog / TestEditDialog (build_schedule helper) ─────────────────


class TestBuildSchedule:
    @pytest.mark.unit
    def test_new_schedule_has_no_id(self):
        from web.components.schedule_dialogs import _build_schedule
        s = _build_schedule(None, "n", "0 9 * * *", "portfolio", {}, ["log"], True)
        assert s.schedule_id == ""
        assert s.name == "n"
        assert s.enabled is True

    @pytest.mark.unit
    def test_edit_preserves_id(self, mgr):
        from web.components.schedule_dialogs import _build_schedule
        sid = mgr.add_schedule(_make_schedule(name="原始"))
        existing = mgr.get_schedule(sid)
        s = _build_schedule(existing, "改名", "30 9 * * *", "portfolio", {},
                            ["log", "wecom"], False)
        assert s.schedule_id == sid
        assert s.name == "改名"
        assert s.enabled is False
        assert set(s.notify_channels) == {"log", "wecom"}


# ── TestScheduleListTable ──────────────────────────────────────────────────


class TestScheduleListTable:
    @pytest.mark.unit
    def test_header_six_columns(self, mgr):
        from web.components import schedule_panel
        mgr.add_schedule(_make_schedule())
        captured = {}

        def _cols(spec, *a, **k):
            n = spec if isinstance(spec, int) else len(spec)
            captured.setdefault("specs", []).append(n)
            return tuple(MagicMock() for _ in range(n))

        with ExitStack() as stack:
            for p in _streamlit_patches():
                stack.enter_context(p)
            stack.enter_context(patch("streamlit.columns", side_effect=_cols))
            schedule_panel._render_schedule_list(mgr)
        # The header + each row uses a 6-slot column layout.
        assert 6 in captured["specs"]


# ── TestEmptyState ─────────────────────────────────────────────────────────


class TestEmptyState:
    @pytest.mark.unit
    def test_empty_prompt_rendered(self, mgr):
        from web.components import schedule_panel
        with patch("streamlit.markdown") as mock_md, \
             patch("streamlit.columns", side_effect=lambda *a, **k: (MagicMock(),)):
            schedule_panel._render_schedule_list(mgr)
        joined = " ".join(str(c.args[0]) for c in mock_md.call_args_list if c.args)
        assert "暂无定时任务" in joined


# ── TestPauseResumeButton ──────────────────────────────────────────────────


class TestPauseResumeButton:
    @pytest.mark.unit
    def test_pause_flips_enabled(self, mgr):
        sid = mgr.add_schedule(_make_schedule(name="启停测试"))
        assert mgr.get_schedule(sid).enabled is True
        mgr.pause_schedule(sid)
        assert mgr.get_schedule(sid).enabled is False
        mgr.resume_schedule(sid)
        assert mgr.get_schedule(sid).enabled is True


# ── TestDeleteConfirmation ─────────────────────────────────────────────────


class TestDeleteConfirmation:
    @pytest.mark.unit
    def test_confirm_delete_removes_schedule(self, mgr):
        from web.components import schedule_panel
        sid = mgr.add_schedule(_make_schedule(name="待删"))
        assert mgr.get_schedule(sid) is not None

        # First column button ("确认删除") returns True, others False.
        call_state = {"n": 0}

        def _button(*a, **k):
            call_state["n"] += 1
            return call_state["n"] == 1  # only the first button click fires

        col = MagicMock()
        col.button = MagicMock(side_effect=_button)
        with patch("streamlit.markdown"), patch("streamlit.warning"), \
             patch("streamlit.error"), patch("streamlit.success"), \
             patch("streamlit.rerun"), \
             patch("streamlit.columns", side_effect=lambda *a, **k: (col, col)), \
             patch.dict("streamlit.session_state", {"schedule_delete_id": sid},
                        clear=False):
            # call the underlying function (unwrap st.dialog decorator)
            schedule_panel._delete_dialog.__wrapped__(mgr, sid)
        assert mgr.get_schedule(sid) is None


# ── TestPanelRender (smoke) ────────────────────────────────────────────────


class TestPanelRender:
    @pytest.mark.unit
    def test_render_panel_all_sections(self, mgr):
        """render_schedule_panel runs without crashing (all 4 sections)."""
        from web.components import schedule_panel
        mgr.add_schedule(_make_schedule())

        with ExitStack() as stack:
            for p in _streamlit_patches():
                stack.enter_context(p)
            # Prevent the 10s sleep+rerun auto-refresh from blocking.
            stack.enter_context(
                patch("web.components.schedule_panel._auto_refresh", MagicMock())
            )
            # ✅ 关键 patch: streamlit @st.dialog 在 bare mode + 测试环境
            # 调 .open() 会 raise StreamlitAPIException (open() is not a valid
            # Streamlit command). 我们 patch open_schedule_dialog 跳过 dialog
            # 渲染 (close等价), 让 test 验证 4 段渲染不依赖 dialog 装饰器.
            # 注: schedule_panel.py 每次 import + call, 所以 patch source module.
            stack.enter_context(
                patch(
                    "web.components.schedule_dialogs.open_schedule_dialog",
                    MagicMock(),
                )
            )
            # Ensure no dialog is opened — clear=True wipes any leaked session_state
            # from earlier tests in the same process.
            with patch.dict(
                "streamlit.session_state",
                {"schedule_dialog_open": False, "schedule_delete_id": None},
                clear=True,
            ):
                schedule_panel.render_schedule_panel()
        # No exception == pass; assert the store still has our schedule.
        assert len(mgr.list_schedules()) == 1
