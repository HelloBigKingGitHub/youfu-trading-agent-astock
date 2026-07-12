"""CLI schedule command tests (v0.6.0)."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner

import pytest

from backend.core.scheduler import Schedule, SourceType, Scheduler
from cli.schedule import app


@pytest.fixture
def tmp_schedules(monkeypatch, tmp_path):
    fake_dir = tmp_path / "schedules"
    fake_dir.mkdir()
    fake_runs = fake_dir / "runs"
    fake_runs.mkdir()
    monkeypatch.setattr("backend.core.scheduler.SCHEDULES_DIR", fake_dir)
    monkeypatch.setattr("backend.core.scheduler.SCHEDULES_FILE", fake_dir / "schedules.json")
    monkeypatch.setattr("backend.core.scheduler.RUNS_DIR", fake_runs)
    Scheduler._reset_singleton()
    # CLI 测试期望从空开始（不加 presets），所以 init 后清空再 reset
    s = Scheduler.get_instance()
    with s._rlock:
        s._schedules.clear()
        s._save()
    Scheduler._reset_singleton()
    yield fake_dir


@pytest.fixture
def sample_schedule():
    return Schedule(
        schedule_id="sched-cli-1",
        name="CLI测试",
        cron_expr="0 18 * * 1-5",
        source_type=SourceType.PORTFOLIO,
        source_config={},
        enabled=True,
        notify_channels=["log"],
    )


runner = CliRunner()


class TestListCommand:
    def test_list_empty(self, tmp_schedules):
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0

    def test_list_with_one(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "CLI测试" in result.stdout or "sched-cli-1" in result.stdout


class TestAddCommand:
    def test_add_portfolio(self, tmp_schedules):
        result = runner.invoke(app, ["add", "--name", "新调度", "--cron", "0 18 * * 1-5", "--source", "portfolio"])
        assert result.exit_code == 0
        s = Scheduler.get_instance()
        assert len(s.list_schedules()) == 1
        sched = s.list_schedules()[0]
        assert sched.name == "新调度"
        assert sched.source_type == SourceType.PORTFOLIO

    def test_add_manual(self, tmp_schedules):
        result = runner.invoke(app, [
            "add", "--name", "手动测试", "--cron", "0 9 * * *",
            "--source", "manual", "--tickers", "600595,688017",
        ])
        assert result.exit_code == 0
        s = Scheduler.get_instance()
        sched = s.list_schedules()[0]
        assert sched.source_type == SourceType.MANUAL
        assert sched.source_config["tickers"] == ["600595", "688017"]

    def test_add_watchlist_with_tag(self, tmp_schedules):
        result = runner.invoke(app, [
            "add", "--name", "长线股", "--cron", "0 9 * * *",
            "--source", "watchlist", "--tag", "长线",
        ])
        assert result.exit_code == 0
        s = Scheduler.get_instance()
        sched = s.list_schedules()[0]
        assert sched.source_type == SourceType.WATCHLIST
        assert sched.source_config["tag"] == "长线"

    def test_add_invalid_cron_fails(self, tmp_schedules):
        result = runner.invoke(app, ["add", "--name", "x", "--cron", "garbage", "--source", "portfolio"])
        assert result.exit_code != 0
        s = Scheduler.get_instance()
        assert len(s.list_schedules()) == 0


class TestRunNowCommand:
    def test_run_now(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        # mock _run_schedule 直接跳过 executor 跑的 real pipeline
        with patch.object(s, "_run_schedule"):
            result = runner.invoke(app, ["run-now", sample_schedule.schedule_id])
        assert result.exit_code == 0

    def test_run_now_not_found(self, tmp_schedules):
        result = runner.invoke(app, ["run-now", "nonexistent"])
        assert result.exit_code != 0


class TestPauseResumeCommand:
    def test_pause(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        result = runner.invoke(app, ["pause", sample_schedule.schedule_id])
        assert result.exit_code == 0
        assert s.get_schedule(sample_schedule.schedule_id).enabled is False

    def test_resume(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        s.pause_schedule(sample_schedule.schedule_id)
        result = runner.invoke(app, ["resume", sample_schedule.schedule_id])
        assert result.exit_code == 0
        assert s.get_schedule(sample_schedule.schedule_id).enabled is True


class TestDeleteCommand:
    def test_delete(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        result = runner.invoke(app, ["delete", sample_schedule.schedule_id, "--yes"])
        assert result.exit_code == 0
        assert s.get_schedule(sample_schedule.schedule_id) is None


class TestRunsCommand:
    def test_runs_empty(self, tmp_schedules):
        result = runner.invoke(app, ["runs"])
        assert result.exit_code == 0

    def test_runs_with_history(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        from backend.core.scheduler import ScheduleRun
        import time
        run = ScheduleRun(
            run_id="run-cli-1", schedule_id=sample_schedule.schedule_id,
            started_at=time.time()-10, finished_at=time.time(),
            status="ok", batch_id="b-1", ticker_count=3, duration=10.0, summary="3 BUY",
        )
        s._append_run(run)
        result = runner.invoke(app, ["runs", "--limit", "10"])
        assert result.exit_code == 0

    def test_runs_filter_by_schedule(self, tmp_schedules, sample_schedule):
        s = Scheduler.get_instance()
        s.add_schedule(sample_schedule)
        result = runner.invoke(app, ["runs", sample_schedule.schedule_id])
        assert result.exit_code == 0