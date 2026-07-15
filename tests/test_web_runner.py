"""Tests for the canonical single-analysis entry point.

Verifies that ``run_one_analysis`` writes H1 history.json through
HistoryStore and delegates the H2 stream loop to ``_run``. Also covers the
backward-compatible ``run_analysis_in_thread`` wrapper and the
``JobQueue._run_pipeline`` routing through ``run_one_analysis``.
"""

from __future__ import annotations

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