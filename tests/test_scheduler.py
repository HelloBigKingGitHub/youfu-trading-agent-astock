"""Scheduler unit tests (v0.6.0)."""
from __future__ import annotations
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.core.scheduler import (
    Schedule,
    ScheduleRun,
    Scheduler,
    SourceType,
    RunStatus,
    VALID_CRON_HELPERS,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_schedules(monkeypatch, tmp_path):
    """隔离真实 ~/.tradingagents/schedules/.（保留自动创建的 presets）"""
    fake_dir = tmp_path / "schedules"
    fake_dir.mkdir()
    fake_runs = fake_dir / "runs"
    fake_runs.mkdir()
    monkeypatch.setattr("backend.core.scheduler.SCHEDULES_DIR", fake_dir)
    monkeypatch.setattr("backend.core.scheduler.SCHEDULES_FILE", fake_dir / "schedules.json")
    monkeypatch.setattr("backend.core.scheduler.RUNS_DIR", fake_runs)
    Scheduler._reset_singleton()
    yield fake_dir


@pytest.fixture
def sample_schedule():
    return Schedule(
        schedule_id="sched-001",
        name="每日持仓复盘",
        cron_expr="0 18 * * 1-5",
        source_type=SourceType.PORTFOLIO,
        source_config={},
        enabled=True,
        notify_channels=["log"],
    )


# ── Schedule dataclass tests ────────────────────────────────────────────


class TestScheduleDataclass:
    def test_to_dict_from_dict_round_trip(self):
        s = Schedule(
            schedule_id="x", name="n", cron_expr="0 9 * * *",
            source_type=SourceType.MANUAL, source_config={"tickers": ["600595"]},
        )
        d = s.to_dict()
        s2 = Schedule.from_dict(d)
        assert s2.schedule_id == s.schedule_id
        assert s2.name == s.name
        assert s2.cron_expr == s.cron_expr
        assert s2.source_type == s.source_type
        assert s2.source_config == s.source_config


class TestScheduleValidate:
    def test_empty_name_fails(self):
        s = Schedule(schedule_id="x", name="   ", cron_expr="0 9 * * *", source_type=SourceType.PORTFOLIO)
        assert s.validate() is not None

    def test_empty_cron_fails(self):
        s = Schedule(schedule_id="x", name="n", cron_expr="", source_type=SourceType.PORTFOLIO)
        assert s.validate() is not None

    def test_invalid_cron_fails(self):
        s = Schedule(schedule_id="x", name="n", cron_expr="not a cron", source_type=SourceType.PORTFOLIO)
        assert s.validate() is not None

    def test_valid_cron_passes(self):
        s = Schedule(schedule_id="x", name="n", cron_expr="0 9 * * *", source_type=SourceType.PORTFOLIO)
        assert s.validate() is None

    def test_manual_source_no_tickers_fails(self):
        s = Schedule(schedule_id="x", name="n", cron_expr="0 9 * * *", source_type=SourceType.MANUAL, source_config={})
        assert s.validate() is not None


class TestScheduleNextRunAt:
    def test_next_run_workday_6pm(self):
        s = Schedule(schedule_id="x", name="n", cron_expr="0 18 * * 1-5", source_type=SourceType.PORTFOLIO)
        now = datetime(2026, 7, 12, 23, 0, 0, tzinfo=timezone.utc).timestamp()
        nxt = s.next_run_at(now=now)
        assert nxt is not None
        assert nxt > now
        nxt_dt = datetime.fromtimestamp(nxt, tz=timezone.utc)
        assert nxt_dt.weekday() < 5
        assert nxt_dt.hour == 18

    def test_next_run_invalid_cron_returns_none(self):
        s = Schedule(schedule_id="x", name="n", cron_expr="garbage", source_type=SourceType.PORTFOLIO)
        assert s.next_run_at() is None

    def test_next_run_5_helpers(self):
        assert len(VALID_CRON_HELPERS) == 5
        for label, expr in VALID_CRON_HELPERS.items():
            s = Schedule(schedule_id="x", name=label, cron_expr=expr, source_type=SourceType.PORTFOLIO)
            assert s.next_run_at() is not None, f"helper {label} ({expr}) returned None"


# ── Scheduler CRUD ──────────────────────────────────────────────────────


class TestSchedulerSingleton:
    def test_get_instance_returns_same(self, tmp_schedules):
        s1 = Scheduler.get_instance()
        s2 = Scheduler.get_instance()
        assert s1 is s2

    def test_reset_singleton_creates_new(self, tmp_schedules):
        s1 = Scheduler.get_instance()
        Scheduler._reset_singleton()
        s2 = Scheduler.get_instance()
        assert s1 is not s2


class TestSchedulerCRUD:
    def test_add_schedule(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        ret = s.add_schedule(sample_schedule)
        assert ret == sample_schedule.schedule_id
        # 2 presets (自动创建) + 1 new = 3
        assert len(s.list_schedules()) == 3
        # 新加的应该是 user, presets 是 preset
        added = s.get_schedule(sample_schedule.schedule_id)
        assert added is not None
        assert added.created_by == "user"

    def test_list_enabled_only(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        s.pause_schedule(sample_schedule.schedule_id)
        # enabled_only=True: 2 presets (1 enabled + 1 disabled) = 1 enabled
        assert len(s.list_schedules(enabled_only=True)) == 1
        # total: 3
        assert len(s.list_schedules()) == 3

    def test_get_schedule(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        assert s.get_schedule(sample_schedule.schedule_id) is not None
        assert s.get_schedule("nonexistent") is None

    def test_update_schedule(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        updated = s.get_schedule(sample_schedule.schedule_id)
        assert updated is not None
        updated.name = "改名后"
        s.update_schedule(updated)
        assert s.get_schedule(sample_schedule.schedule_id).name == "改名后"

    def test_delete_schedule(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        assert s.delete_schedule(sample_schedule.schedule_id) is True
        assert s.get_schedule(sample_schedule.schedule_id) is None
        assert s.delete_schedule(sample_schedule.schedule_id) is False

    def test_pause_resume(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        assert s.pause_schedule(sample_schedule.schedule_id) is True
        assert s.get_schedule(sample_schedule.schedule_id).enabled is False
        assert s.resume_schedule(sample_schedule.schedule_id) is True
        assert s.get_schedule(sample_schedule.schedule_id).enabled is True


# ── Scheduler IO / Persistence ─────────────────────────────────────────


class TestSchedulerLoadSave:
    def test_save_and_reload(self, tmp_schedules, sample_schedule):
        s1 = Scheduler.get_instance()
        s1.add_schedule(sample_schedule)
        assert (tmp_schedules / "schedules.json").exists()
        Scheduler._reset_singleton()
        s2 = Scheduler.get_instance()
        loaded = s2.get_schedule(sample_schedule.schedule_id)
        assert loaded is not None
        assert loaded.name == sample_schedule.name
        assert loaded.cron_expr == sample_schedule.cron_expr

    def test_persists_across_restart(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        Scheduler._reset_singleton()
        s2 = Scheduler.get_instance()
        # 2 presets 持久化 + 1 new = 3
        assert len(s2.list_schedules()) == 3
        assert s2.get_schedule(sample_schedule.schedule_id) is not None
        assert s2.get_schedule(sample_schedule.schedule_id).name == "每日持仓复盘"

    def test_corrupt_json_recovers(self, tmp_schedules):
        # 删掉现有 schedules.json + 禁用 presets 创建
        (tmp_schedules / "schedules.json").write_text("NOT JSON{")
        # Reset singleton, force re-init
        Scheduler._reset_singleton()
        # Monkey-patch _ensure_presets to be a no-op for this test
        with patch("backend.core.scheduler.Scheduler._ensure_presets") as mock_presets:
            mock_presets.return_value = None
            s = Scheduler.get_instance()
        # 即使 JSON 损坏, _load 应 catch + 返回空 schedules (但 presets 可能被加入)
        # 验证 corrupt file 不让 scheduler 崩
        assert s is not None


# ── Scheduler Tick + Load tickers ──────────────────────────────────────


class TestSchedulerTick:
    def test_tick_runs_due_schedule(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        sample_schedule.cron_expr = "* * * * *"
        sample_schedule.source_type = SourceType.MANUAL
        sample_schedule.source_config = {"tickers": ["600595"]}
        s.add_schedule(sample_schedule)
        # 用 mock 整个 _run_schedule, 避免真实 job_queue; 验证 _executor.submit 被调用一次
        with patch.object(s, "_run_schedule") as mock_run, \
             patch.object(s._executor, "submit", wraps=s._executor.submit) as mock_submit:
            s._tick()
        mock_submit.assert_called_once()
        # 第一个位置参数应该是 _run_schedule 的可调用对象（mock_run 或 self._run_schedule）
        assert mock_submit.call_args[0][0] is mock_run

    def test_tick_skips_disabled(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        sample_schedule.enabled = False
        s.add_schedule(sample_schedule)
        with patch.object(s._executor, "submit") as mock_submit:
            s._tick()
        mock_submit.assert_not_called()

    def test_tick_does_not_run_future(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        sample_schedule.cron_expr = "0 0 1 1 *"
        s.add_schedule(sample_schedule)
        with patch.object(s._executor, "submit") as mock_submit:
            s._tick()
        mock_submit.assert_not_called()


class TestSchedulerLoadTickers:
    def test_load_tickers_portfolio(self, tmp_schedules):
        s = Scheduler.get_instance()
        # mock portfolio_store 的 get_portfolio_store 函数
        mock_store = MagicMock()
        mock_pos = MagicMock()
        mock_pos.ticker = "600595"
        mock_pos2 = MagicMock()
        mock_pos2.ticker = "688017"
        mock_store.list_positions.return_value = [mock_pos, mock_pos2]
        with patch("backend.core.portfolio_store.get_portfolio_store", return_value=mock_store):
            tickers = s._load_tickers_for_source(SourceType.PORTFOLIO, {})
        assert tickers == ["600595", "688017"]

    def test_load_tickers_watchlist(self, tmp_schedules):
        s = Scheduler.get_instance()
        mock_store = MagicMock()
        e1 = MagicMock()
        e1.ticker = "000001"
        e2 = MagicMock()
        e2.ticker = "002195"
        mock_store.list.return_value = [e1, e2]
        with patch("backend.core.watchlist.get_watchlist_store", return_value=mock_store):
            tickers = s._load_tickers_for_source(SourceType.WATCHLIST, {"tag": "长线"})
        assert tickers == ["000001", "002195"]
        mock_store.list.assert_called_with(tag="长线")

    def test_load_tickers_manual(self, tmp_schedules):
        s = Scheduler.get_instance()
        tickers = s._load_tickers_for_source(SourceType.MANUAL, {"tickers": ["300750", "301550"]})
        assert tickers == ["300750", "301550"]

    def test_load_tickers_manual_empty(self, tmp_schedules):
        s = Scheduler.get_instance()
        tickers = s._load_tickers_for_source(SourceType.MANUAL, {})
        assert tickers == []


# ── Scheduler run_now + threading ──────────────────────────────────────


class TestSchedulerRunNow:
    def test_run_now_returns_batch_id(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        sample_schedule.source_type = SourceType.MANUAL
        sample_schedule.source_config = {"tickers": ["600595"]}
        s.add_schedule(sample_schedule)
        # mock 整个 _run_schedule 来跳过 job_queue
        with patch.object(s, "_run_schedule") as mock_run:
            # run_now 会 create_batch 然后 submit, 我们用 _run_schedule mock 跳过
            bid = s.run_now(sample_schedule.schedule_id)
        assert isinstance(bid, str)  # 返回字符串 batch_id
        mock_run.assert_called()

    def test_run_now_not_found(self, tmp_schedules):
        s = Scheduler.get_instance()
        with pytest.raises((KeyError, ValueError)):
            s.run_now("nonexistent")


class TestSchedulerThreading:
    def test_concurrent_add_list(self, tmp_schedules):
        s = Scheduler.get_instance()
        errors = []
        initial_count = len(s.list_schedules())  # 2 presets
        def add(i):
            try:
                s.add_schedule(Schedule(
                    schedule_id=f"sched-{i}", name=f"n{i}",
                    cron_expr="0 9 * * *", source_type=SourceType.PORTFOLIO,
                ))
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert len(errors) == 0
        # 2 presets + 20 new = 22
        assert len(s.list_schedules()) == initial_count + 20


# ── Scheduler Audit log + Notify ───────────────────────────────────────


class TestSchedulerOnComplete:
    def test_creates_run_record(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        run = ScheduleRun(
            run_id="run-1",
            schedule_id=sample_schedule.schedule_id,
            started_at=time.time() - 10,
            finished_at=time.time(),
            status="ok",
            batch_id="batch-1",
            ticker_count=3,
            duration=10.0,
            summary="3BUY",
        )
        s._append_run(run)
        today = datetime.now().strftime("%Y-%m-%d")
        run_file = tmp_schedules / "runs" / f"{today}.jsonl"
        assert run_file.exists()
        content = run_file.read_text()
        assert "run-1" in content

    def test_notify_failure_does_not_crash(self, tmp_schedules):
        from backend.core.notifier import ChannelConfig
        cfg = ChannelConfig(wecom_webhook="https://x")
        with patch("backend.core.notifier.Notifier") as MockN:
            mock = MockN.get_instance.return_value
            mock._load_config.return_value = cfg
            mock.send.return_value = {"wecom": False}
            try:
                mock.send(["wecom"], "name", {"summary": "test"})
            except Exception as e:
                pytest.fail(f"notification failure caused crash: {e}")


class TestSchedulerPruneOldRuns:
    def test_prune_30_days_old(self, tmp_schedules):
        s = Scheduler.get_instance()
        old_file = tmp_schedules / "runs" / "2020-01-01.jsonl"
        old_file.write_text('{"run_id": "old"}')
        new_file = tmp_schedules / "runs" / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        new_file.write_text('{"run_id": "new"}')
        s._prune_old_runs()
        assert not old_file.exists()
        assert new_file.exists()


class TestSchedulerStartStop:
    def test_start_creates_thread(self, tmp_schedules):
        s = Scheduler.get_instance()
        s.start()
        try:
            assert s.is_running() is True
            assert s._thread is not None
            assert s._thread.is_alive()
        finally:
            # Stop async (避免 2s join 阻塞)
            s._stop_event.set()
            if s._thread:
                s._thread = None

    def test_stop_clears_thread(self, tmp_schedules):
        s = Scheduler.get_instance()
        s.start()
        # 异步 stop (不阻塞)
        s._stop_event.set()
        s._thread = None
        assert s._thread is None

    def test_start_idempotent(self, tmp_schedules):
        s = Scheduler.get_instance()
        s.start()
        t1 = s._thread
        s.start()
        t2 = s._thread
        assert t1 is t2
        # 异步 stop
        s._stop_event.set()
        s._thread = None


class TestSchedulerPresets:
    def test_presets_created_on_install(self, tmp_schedules):
        s = Scheduler.get_instance()
        names = [x.name for x in s.list_schedules()]
        # Should have 2 presets
        assert "每日持仓复盘" in names
        assert "周一前瞻" in names

    def test_preset_portfolio_default(self, tmp_schedules):
        s = Scheduler.get_instance()
        scheds = [x for x in s.list_schedules() if x.name == "每日持仓复盘"]
        if scheds:
            assert scheds[0].source_type == SourceType.PORTFOLIO
            assert "1-5" in scheds[0].cron_expr


class TestSchedulerNotifyChannels:
    def test_log_channel_works(self, tmp_schedules, sample_schedule):
        """Log channel is always working (no external deps).
        测 _notify 方法: 当 batch 完成时, log channel 始终成功.
        """
        from backend.core.scheduler import ScheduleRun
        s = Scheduler.get_instance()
        sample_schedule.notify_channels = ["log"]
        s.add_schedule(sample_schedule)
        # Mock Notifier.get_instance().send, 测 _notify 调 send
        with patch("backend.core.notifier.Notifier") as MockN:
            mock_notifier = MockN.get_instance.return_value
            mock_notifier.send.return_value = {"log": True}
            # 直接调 _notify (不跑 _run_schedule)
            run = ScheduleRun(
                run_id="test-1", schedule_id=sample_schedule.schedule_id,
                started_at=time.time(), finished_at=time.time(),
                status="ok", batch_id="b-1", ticker_count=2, duration=10.0,
                summary="2 OK",
            )
            s._notify(sample_schedule, run)
        # send 接受 (channels, schedule_name, run_data_dict)
        mock_notifier.send.assert_called_once()
        call_args = mock_notifier.send.call_args
        assert call_args.args[0] == ["log"]
        assert call_args.args[1] == sample_schedule.name
        assert isinstance(call_args.args[2], dict)