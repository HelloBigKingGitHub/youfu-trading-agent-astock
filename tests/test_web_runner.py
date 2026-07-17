"""Tests for the canonical single-analysis entry point.

Verifies that ``run_one_analysis`` writes H1 history.json through
HistoryStore and delegates the H2 stream loop to ``_run``. Also covers the
backward-compatible ``run_analysis_in_thread`` wrapper and the
``JobQueue._run_pipeline`` routing through ``run_one_analysis``.
"""

from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ─── run_one_analysis ────────────────────────────────────────────────────────


@pytest.fixture()
def runner_harness(monkeypatch):
    """Isolate run_one_analysis from disk and the real graph.

    ``_run`` is replaced with a MagicMock so the test exercises only the
    wrapper's bookkeeping (H1 create/mark, log_writer creation lives in
    ``_run`` and is verified separately in test_log_streaming).
    """
    import importlib
    import web.runner as runner

    # Self-heal from test_web_app_dispatch._neutralise_web_dependencies,
    # which replaces every callable attribute of ``web.runner`` (including
    # ``run_one_analysis``) with ``MagicMock()`` instances in the module
    # namespace. Without this reload, tests in this module would receive a
    # MagicMock when calling ``runner.run_one_analysis(...)`` instead of the
    # real function, breaking the assertion contract.
    importlib.reload(runner)

    history_store = MagicMock()
    history_store.create.return_value = SimpleNamespace(analysis_id="analysis-123")
    monkeypatch.setattr(runner, "_history_store", history_store)
    monkeypatch.setattr(runner, "_run", MagicMock())
    return runner, history_store


class TestRunOneAnalysis:
    def test_creates_h1_entry(self, runner_harness):
        runner, history_store = runner_harness

        runner.run_one_analysis("600519", "2026-07-15", {"mode": "test"})

        history_store.create.assert_called_once_with(
            "600519", "2026-07-15", status="running"
        )

    def test_delegates_to_run(self, runner_harness):
        """run_one_analysis delegates the pipeline to _run."""
        runner, _ = runner_harness

        runner.run_one_analysis("600519", "2026-07-15", {"mode": "test"})

        runner._run.assert_called_once()
        # _run signature: _run(ticker, trade_date, config, tracker, analysis_id)
        args = runner._run.call_args.args
        assert args[0] == "600519"
        assert args[1] == "2026-07-15"
        assert args[2] == {"mode": "test"}
        assert args[4] == "analysis-123"

    def test_returns_analysis_id(self, runner_harness):
        runner, _ = runner_harness

        analysis_id = runner.run_one_analysis("600519", "2026-07-15", {})

        assert analysis_id == "analysis-123"

    def test_marks_complete_on_success(self, runner_harness):
        runner, history_store = runner_harness

        def complete_run(ticker, trade_date, config, tracker, analysis_id):
            tracker.completed_stages.append("market")
            tracker.signal = "Buy"

        runner._run.side_effect = complete_run

        runner.run_one_analysis("600519", "2026-07-15", {})

        assert history_store.mark_complete.call_args.args == ("analysis-123",)
        assert history_store.mark_complete.call_args.kwargs["signal"] == "Buy"
        assert history_store.mark_complete.call_args.kwargs["completed_stages"] == [
            "market",
        ]
        assert history_store.mark_complete.call_args.kwargs["elapsed"] >= 0
        history_store.set_results_path.assert_called_once()

    def test_marks_error_on_failure(self, runner_harness):
        runner, history_store = runner_harness
        runner._run.side_effect = RuntimeError("pipeline failed")

        with pytest.raises(RuntimeError, match="pipeline failed"):
            runner.run_one_analysis("600519", "2026-07-15", {})

        history_store.mark_error.assert_called_once()
        assert history_store.mark_error.call_args.args[:2] == (
            "analysis-123",
            "pipeline failed",
        )

    def test_existing_run_analysis_in_thread_uses_run_one_analysis(self, monkeypatch):
        """run_analysis_in_thread backward-compat wraps run_one_analysis."""
        import web.runner as runner

        called = threading.Event()
        run_one = MagicMock(side_effect=lambda *args: called.set())
        monkeypatch.setattr(runner, "run_one_analysis", run_one)

        thread = runner.run_analysis_in_thread(
            "600519", "2026-07-15", {"mode": "test"}
        )

        assert called.wait(timeout=2)
        thread.join(timeout=2)
        # run_one_analysis called once with the same args
        assert run_one.call_count == 1
        assert run_one.call_args.args == (
            "600519", "2026-07-15", {"mode": "test"},
        )


# ─── Streamlit interpreter-shutdown trap 防护 ─────────────────────────────────


class TestInterpreterShutdownGuard:
    """Regression guard for v0.7.0.P0 single-analysis 死锁 fix.

    当 CPython ``concurrent.futures.thread`` 模块的 ``_shutdown`` 全局 flag
    被 streamlit 源文件热更新触发置为 True 时, ``_run`` 入口检测并自动
    reset (worker threads 还在, flag 只是 submit 守卫) + logger.warning
    一行 hint。这样用户无需手动重启 streamlit 就能跑分析, 同时 meta.json
    的 chunk_counts/stages_completed 不再全部为 0。
    """

    def test_run_resets_shutdown_flag_and_runs_pipeline(
        self, runner_harness, monkeypatch, tmp_path
    ):
        """验证 _shutdown=True 时 _run 自动重置 + 跑通 pipeline。

        不依赖真 LangGraph (mock TradingAgentsGraph + StatsCallbackHandler),
        直接调真 _run 验证 guard 在第一行就 reset。LogWriter 落盘用 tmp_path
        重定向, 与已有 ``test_run_creates_log_writer_when_calling_directly``
        模式一致。
        """
        import concurrent.futures.thread as _cf_thread
        import web.runner as runner

        runner, history_store = runner_harness

        # reload 拿回真 _run 函数 (harness 默认 mock 掉了)
        importlib.reload(runner)
        # reload 后 _history_store 又是真实 store, 需要再次 mock 防止落盘
        history_store = MagicMock()
        history_store.create.return_value = SimpleNamespace(
            analysis_id="analysis-123"
        )
        monkeypatch.setattr(runner, "_history_store", history_store)

        # 把 LogWriter 落盘路径重定向到 tmp_path, 避免污染 ~/.tradingagents/logs
        monkeypatch.setattr(
            "backend.core.log_store._LOGS_ROOT", tmp_path, raising=False
        )

        # 模拟 _python_exit 已经触发
        monkeypatch.setattr(_cf_thread, "_shutdown", True)

        # 拦截 TradingAgentsGraph + StatsCallbackHandler (LangGraph 真模块太重)
        with patch(
            "tradingagents.graph.trading_graph.TradingAgentsGraph"
        ) as mock_graph_cls, patch(
            "cli.stats_handler.StatsCallbackHandler",
            return_value=MagicMock(),
        ):
            mock_graph = MagicMock()
            mock_graph.graph.stream.return_value = iter([
                {"final_trade_decision": "Hold"},
            ])
            mock_graph.propagator.create_initial_state.return_value = {}
            mock_graph.propagator.get_graph_args.return_value = {}
            mock_graph.process_signal.return_value = "Hold"
            mock_graph.ticker = "600595"
            mock_graph_cls.return_value = mock_graph

            mock_tracker = MagicMock()
            mock_tracker.completed_stages = []
            mock_tracker.start_time = __import__("time").time()

            # 真 _run — guard 应自动重置 _shutdown, 然后正常往下跑
            runner._run("600595", "2026-07-16", {}, mock_tracker, "analysis-123")

        # 关键断言 1: _shutdown 已重置回 False
        assert _cf_thread._shutdown is False, (
            "Guard 应该自动重置 _shutdown=False 而不是抛错"
        )

        # 关键断言 2: 真 _run 跑完 stream loop, mock_tracker.mark_complete 应被调
        assert mock_tracker.mark_complete.called, (
            "_run 应该走完 stream loop 调用 mark_complete"
        )

        # 关键断言 3: LogWriter 落盘到 tmp_path 证明 pipeline 实际跑完
        log_dir = tmp_path / "600595"
        assert log_dir.exists() and any(log_dir.iterdir()), (
            f"LogWriter 应该在 {tmp_path}/600595/ 落盘, 但目录不存在或为空"
        )

    def test_run_no_warning_when_shutdown_already_false(
        self, runner_harness, monkeypatch, caplog
    ):
        """验证 _shutdown=False 时 _run 不打 warning (无副作用)。"""
        import concurrent.futures.thread as _cf_thread
        import logging
        import web.runner as runner

        runner, _ = runner_harness

        # 确保 _shutdown=False
        monkeypatch.setattr(_cf_thread, "_shutdown", False)

        mock_tracker = MagicMock()
        mock_tracker.completed_stages = []
        mock_tracker.start_time = __import__("time").time()

        with patch(
            "tradingagents.graph.trading_graph.TradingAgentsGraph"
        ) as mock_graph_cls, patch(
            "cli.stats_handler.StatsCallbackHandler",
            return_value=MagicMock(),
        ):
            mock_graph = MagicMock()
            mock_graph.graph.stream.return_value = iter([
                {"final_trade_decision": "Hold"},
            ])
            mock_graph.propagator.create_initial_state.return_value = {}
            mock_graph.propagator.get_graph_args.return_value = {}
            mock_graph.process_signal.return_value = "Hold"
            mock_graph.ticker = "600519"
            mock_graph_cls.return_value = mock_graph

            with caplog.at_level(logging.WARNING, logger="web.runner"):
                runner._run(
                    "600519", "2026-07-15", {}, mock_tracker, "analysis-123"
                )

            # 没有 _shutdown reset warning
            warnings = [
                r for r in caplog.records
                if "_shutdown=False" in r.getMessage()
            ]
            assert not warnings, (
                f"Guard 不应在 _shutdown=False 时触发 warning, got: {warnings}"
            )

        # _shutdown 仍是 False (没动)
        assert _cf_thread._shutdown is False


# ─── _run still owns LogWriter ───────────────────────────────────────────────


class TestRunStillOwnsLogWriter:
    """Regression guard: removing the LogWriter creation from ``_run`` would
    silently break all 4 entry points. ``_run`` MUST create the LogWriter
    itself, even when called directly (e.g. from ``test_log_streaming``).
    """

    def test_run_creates_log_writer_when_calling_directly(self, tmp_path, monkeypatch):
        from web.runner import _run
        from backend.core.log_store import LogWriter

        monkeypatch.setattr(
            "backend.core.log_store._LOGS_ROOT", tmp_path, raising=False
        )

        # Use the real LogWriter — verify _run creates it
        mock_graph = MagicMock()
        mock_graph.graph.stream.return_value = iter([{
            "final_trade_decision": "Hold",
        }])
        mock_graph.propagator.create_initial_state.return_value = {}
        mock_graph.propagator.get_graph_args.return_value = {}
        mock_graph.process_signal.return_value = "Hold"
        mock_graph.ticker = "600519"

        mock_tracker = MagicMock()
        mock_tracker.completed_stages = []
        mock_tracker.start_time = __import__("time").time()

        with patch("tradingagents.graph.trading_graph.TradingAgentsGraph", return_value=mock_graph), \
             patch("cli.stats_handler.StatsCallbackHandler", return_value=MagicMock()), \
             patch("web.runner._history_store"):
            _run("600519", "2026-07-15", {}, mock_tracker, "test-id")

        # meta.json must exist (proves _run created LogWriter)
        log_dir = tmp_path / "600519" / "2026-07-15_run01"
        assert (log_dir / "meta.json").exists()


# ─── JobQueue routes through run_one_analysis ────────────────────────────────


class TestJobQueueRoutesThroughRunOneAnalysis:
    """JobQueue._run_pipeline must delegate to run_one_analysis so that
    scheduler / batch API / CLI all write H1 history entries.
    """

    def test_run_pipeline_calls_run_one_analysis(self, monkeypatch):
        from backend.core.job_queue import JobQueue, Job

        run_one = MagicMock(return_value="analysis-from-run-one")
        monkeypatch.setattr("web.runner.run_one_analysis", run_one)

        # Reset singleton for a fresh job queue
        JobQueue._reset_singleton()

        job = Job(
            job_id="j-1",
            analysis_id="a-1",
            ticker="600519",
            trade_date="2026-07-15",
        )
        q = JobQueue.get_instance()
        q._run_pipeline(job, {"mode": "test"})

        run_one.assert_called_once_with("600519", "2026-07-15", {"mode": "test"})