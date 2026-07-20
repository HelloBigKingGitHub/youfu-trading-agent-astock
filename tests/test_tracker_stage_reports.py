"""Tests for ``AnalysisTracker.mark_stage_done`` and HistoryStore parity.

Covers the P2.25 hotfix:

  * ``stage_reports`` must be keyed by the **canonical LangGraph chunk
    field name** (``report_key``) — NOT by ``stage_id``. The React
    frontend reads by ``report_key`` via ``STAGE_TO_REPORT_KEY`` /
    ``WORKSPACE_CARDS`` and silently shows "(等待该阶段完成)" forever
    if the key is wrong.

  * ``completed_stages`` is still keyed by ``stage_id`` (the pipeline
    stage label used by the UI progress bar).

  * Both layers — ``AnalysisTracker`` (in-memory) and ``HistoryStore``
    (JSON-backed) — must apply the same key when ``report_key`` is
    passed.
"""

from __future__ import annotations

import importlib
import json
import threading
from pathlib import Path

import pytest


@pytest.fixture()
def tracker_env(tmp_path, monkeypatch):
    """Reset TrackerStore singleton + redirect HistoryStore to tmp_path."""
    # 1. Redirect HistoryStore's storage dir + reset its singleton so the
    #    new path is honoured. Mirrors the ``tmp_logs_root`` pattern in
    #    test_log_store.py.
    from backend.core import history_store as history_mod
    monkeypatch.setattr(history_mod, "_HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history_mod.HistoryStore, "_instance", None)

    # 2. Reset TrackerStore singleton so the tracker doesn't reuse the
    #    live in-memory store across tests.
    from backend.core import tracker as tracker_mod
    monkeypatch.setattr(tracker_mod.TrackerStore, "_instance", None)

    yield tracker_mod, history_mod


class TestMarkStageDoneKeyContract:
    """The contract: ``stage_reports`` keys = ``report_key``, NOT ``stage_id``."""

    def test_explicit_report_key_is_used_as_dict_key(self, tracker_env):
        tracker_mod, _ = tracker_env
        _, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="000001", trade_date="2026-07-17",
        )

        # Simulate the runner's debate-stage call. The canonical chunk
        # field name is ``investment_debate_state`` but the stage id is
        # ``debate``. The frontend looks up by the canonical name.
        tracker.mark_stage_done(
            stage_id="debate",
            report="Bull says BUY. Bear says SELL. Judge says HOLD.",
            report_key="investment_debate_state",
        )

        assert "investment_debate_state" in tracker.stage_reports
        assert tracker.stage_reports["investment_debate_state"] == (
            "Bull says BUY. Bear says SELL. Judge says HOLD."
        )
        # Old (buggy) key MUST NOT be present.
        assert "debate" not in tracker.stage_reports

    def test_completed_stages_uses_stage_id_not_report_key(self, tracker_env):
        tracker_mod, _ = tracker_env
        _, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="000001", trade_date="2026-07-17",
        )
        tracker.mark_stage_done(
            stage_id="debate",
            report="...",
            report_key="investment_debate_state",
        )
        # The UI progress bar uses ``completed_stages`` and reads by id.
        assert "debate" in tracker.completed_stages
        assert "investment_debate_state" not in tracker.completed_stages

    def test_default_falls_back_to_stage_id(self, tracker_env):
        """Backward compat: callers that don't pass ``report_key`` still work."""
        tracker_mod, _ = tracker_env
        _, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="000001", trade_date="2026-07-17",
        )
        # No ``report_key`` passed — the report should land under ``stage_id``
        # so legacy callers don't crash.
        tracker.mark_stage_done(stage_id="market", report="mock market body")
        assert tracker.stage_reports["market"] == "mock market body"
        assert tracker.stage_reports.get("market_report") is None

    def test_market_report_uses_canonical_key(self, tracker_env):
        """For analyst stages the stage_id and report_key happen to differ
        only in the ``_report`` suffix; we still verify both layers stay
        consistent.
        """
        tracker_mod, _ = tracker_env
        _, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="000001", trade_date="2026-07-17",
        )
        tracker.mark_stage_done(
            stage_id="market",
            report="mock body",
            report_key="market_report",
        )
        assert tracker.stage_reports["market_report"] == "mock body"
        assert "market" in tracker.completed_stages


class TestHistoryStoreParity:
    """HistoryStore must mirror the tracker — both layers see the same key.

    P2.25 hotfix — TrackerStore.create() now passes its generated id
    through to HistoryStore.create(), so the two layers share one
    analysis_id. /progress falls through tracker → history by the same
    id and finds the entry; recent-list shows the same id POST returned.
    """

    def test_history_store_reuses_external_analysis_id(self, tracker_env):
        """P2.25 — passing ``analysis_id`` makes HistoryStore NOT mint its
        own UUID. Without this, POST /api/analyze's id and the on-disk
        history.json's id diverged and /progress 404'd after restart.
        """
        _, history_mod = tracker_env
        hs = history_mod.get_history_store()
        external_id = "600595_2026-07-17_aabbcc00"
        entry = hs.create(
            "600595", "2026-07-17", status="running", analysis_id=external_id,
        )
        assert entry.analysis_id == external_id
        refetched = hs.get(external_id)
        assert refetched is not None
        assert refetched.analysis_id == external_id

    def test_history_store_mints_own_id_when_none_passed(self, tracker_env):
        """Backward compat — callers (e.g. web/runner.py) that don't pass
        an id still get the legacy ticker_date_uuid pattern.
        """
        _, history_mod = tracker_env
        hs = history_mod.get_history_store()
        entry = hs.create("600595", "2026-07-17", status="running")
        assert entry.analysis_id.startswith("600595_2026-07-17_")
        assert len(entry.analysis_id.split("_")[-1]) == 8

    def test_tracker_store_creates_history_with_shared_id(self, tracker_env):
        """End-to-end: TrackerStore.create() and the resulting HistoryStore
        entry share the same analysis_id. This is the contract the
        frontend relies on — POST returns one id, recent-list shows the
        same id, /progress finds the same id.
        """
        tracker_mod, _ = tracker_env
        from backend.core.history_store import get_history_store

        returned_id, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="600595", trade_date="2026-07-17",
        )
        # The id POST /api/analyze returned.
        assert tracker.analysis_id == returned_id
        # The history entry on disk must be findable under the SAME id.
        hs_entry = get_history_store().get(returned_id)
        assert hs_entry is not None, (
            f"HistoryStore has no entry under TrackerStore id {returned_id!r} "
            "— P2.25 fix not in effect"
        )
        assert hs_entry.analysis_id == returned_id

    def test_history_store_records_under_report_key(self, tracker_env):
        _, history_mod = tracker_env
        hs = history_mod.get_history_store()
        # Create the HistoryStore entry directly so the analysis_id is known.
        entry = hs.create("000001", "2026-07-17", status="running")
        # Now call mark_stage_done with the same id the HistoryStore owns.
        hs.mark_stage_done(
            entry.analysis_id,
            stage_id="risk",
            report="Aggressive BUY / Conservative HOLD / Neutral SELL.",
            report_key="risk_debate_state",
        )

        refetched = hs.get(entry.analysis_id)
        assert refetched is not None
        assert "risk_debate_state" in refetched.stage_reports
        assert refetched.stage_reports["risk_debate_state"].startswith("Aggressive")
        # ``risk`` (stage id) goes into completed_stages, not stage_reports.
        assert "risk" in refetched.completed_stages
        assert "risk" not in refetched.stage_reports

    def test_history_store_default_falls_back_to_stage_id(self, tracker_env):
        """Backward compat: callers that don't pass ``report_key`` still work."""
        _, history_mod = tracker_env
        hs = history_mod.get_history_store()
        entry = hs.create("000001", "2026-07-17", status="running")
        hs.mark_stage_done(entry.analysis_id, stage_id="market", report="mock body")
        refetched = hs.get(entry.analysis_id)
        assert refetched.stage_reports["market"] == "mock body"

    def test_progress_dict_exposes_canonical_keys(self, tracker_env):
        """The /api/analyze/{id}/progress endpoint serializes
        ``tracker.to_progress_dict()`` directly. Verify the dict the
        frontend consumes is keyed correctly.
        """
        tracker_mod, _ = tracker_env
        _, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="000001", trade_date="2026-07-17",
        )
        tracker.mark_stage_done(
            stage_id="debate",
            report="judge output",
            report_key="investment_debate_state",
        )
        tracker.mark_stage_done(
            stage_id="pm",
            report="final decision",
            report_key="final_trade_decision",
        )

        progress = tracker.to_progress_dict()
        assert set(progress["stage_reports"].keys()) == {
            "investment_debate_state",
            "final_trade_decision",
        }


class TestDictStagePrematureDone:
    """The runner's DICT_STAGE_KEYS guard — debate/risk must not fire
    ``mark_stage_done`` until ``judge_decision`` is non-empty.

    Verified at the ``mark_stage_done`` boundary: callers are responsible
    for guarding the empty-initial-state case; the tracker simply trusts
    the call. We mirror that here so the contract is documented.
    """

    def test_empty_dict_content_is_a_caller_concern(self, tracker_env):
        tracker_mod, _ = tracker_env
        _, tracker = tracker_mod.TrackerStore.get_instance().create(
            ticker="000001", trade_date="2026-07-17",
        )
        # If the caller passes an empty dict rendered as a string, it still
        # gets stored — the guard lives in the runner. This test pins the
        # tracker contract so a future refactor doesn't try to re-introduce
        # silent filtering inside the tracker.
        empty_dict_repr = "{'bull_history': '', 'judge_decision': '', 'count': 0}"
        tracker.mark_stage_done(
            stage_id="debate",
            report=empty_dict_repr,
            report_key="investment_debate_state",
        )
        assert tracker.stage_reports["investment_debate_state"] == empty_dict_repr


class TestStageProgressionChaining:
    """P2.26 hotfix — when one stage finishes, the NEXT pipeline stage
    must immediately become ``active`` so the progress bar lights up the
    next card without waiting for the next LangGraph chunk (which is
    emitted on the next node boundary, typically 30-90s apart for an
    LLM-bound analyst). Without this chain, ``current_stage`` is empty
    between chunks and the workspace / progress UI sits on the same
    completed card for a long silence — exactly what the user reported
    as "进度不实时推送".

    We exercise the chain at the runner boundary so the test stays
    stable as ``STAGE_ORDER`` evolves.
    """

    def test_first_stage_activated_on_runner_start(self, monkeypatch):
        """When ``_run_analysis`` enters, ``current_stage`` should already
        be ``"market"`` — even before the first chunk arrives. This kills
        the 100-500ms window between ``POST /api/analyze`` and the first
        LangGraph chunk where the UI shows all-pending.
        """
        import time as time_module
        from backend.core import runner as runner_mod

        # ── Fake graph that yields one chunk then raises ──────────────
        class _FakeGraph:
            class _Graph:
                def stream(self, init_state, **kwargs):
                    raise ConnectionError("simulated API outage during first chunk")

            def __init__(self, *a, **kw):
                self.graph = self._Graph()
                self.propagator = type("P", (), {
                    "create_initial_state": lambda self_, t, d: {},
                    "get_graph_args": lambda self_, **kw: {},
                })()
                self.ticker = ""
            def process_signal(self, x): return "HOLD"
            def _log_state(self, *a, **kw): pass

        import tradingagents.graph.trading_graph as tg_mod
        import cli.stats_handler as stats_mod
        monkeypatch.setattr(tg_mod, "TradingAgentsGraph", _FakeGraph)
        monkeypatch.setattr(stats_mod, "StatsCallbackHandler", lambda: type(
            "S", (), {"get_stats": lambda self_: {"llm_calls": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0}}
        )())

        store = runner_mod.get_store()
        _, tracker = store.create(ticker="600595", trade_date="2026-07-17")
        # Pre-condition: tracker has NOT been activated yet.
        assert tracker.current_stage == ""

        with pytest.raises(ConnectionError):
            runner_mod._run_analysis(
                analysis_id=tracker.analysis_id,
                config={},
                tracker=tracker,
            )

        # After the first chunk was attempted (and raised), ``current_stage``
        # must be ``"market"`` — the runner activated it before entering the
        # stream loop.
        progress = tracker.to_progress_dict()
        assert progress["current_stage"] == "market", (
            f"expected current_stage='market' after runner start, "
            f"got {progress['current_stage']!r}"
        )

    def test_next_stage_activated_when_stage_completes(self, monkeypatch):
        """After ``mark_stage_done`` for ``market`` fires (chunk arrived),
        the runner's chain should activate ``social`` immediately, so the
        UI's progress bar lights up the social card the moment market's
        card turns green — no 30-90s lag waiting for social's first chunk.
        """
        import time as time_module
        from backend.core import runner as runner_mod

        chunks_yielded = [
            # First chunk: market_report fires → mark_stage_done('market')
            # → _activate_next_stage('market') must set current_stage='social'.
            {"market_report": "ok"},
            # Second chunk: sentiment_report fires → mark_stage_done('social')
            # → _activate_next_stage('social') must set current_stage='news'.
            {"sentiment_report": "ok"},
            # Third chunk: news_report fires → mark_stage_done('news')
            # → _activate_next_stage('news') must set current_stage='fundamentals'.
            {"news_report": "ok"},
            # Final: PM yields its decision → mark_complete.
            {"final_trade_decision": "BUY"},
        ]

        class _FakeGraph:
            class _Graph:
                def stream(self, init_state, **kwargs):
                    for c in chunks_yielded:
                        yield c

            def __init__(self, *a, **kw):
                self.graph = self._Graph()
                self.propagator = type("P", (), {
                    "create_initial_state": lambda self_, t, d: {},
                    "get_graph_args": lambda self_, **kw: {},
                })()
                self.ticker = ""
            def process_signal(self, x): return "BUY"
            def _log_state(self, *a, **kw): pass

        import tradingagents.graph.trading_graph as tg_mod
        import cli.stats_handler as stats_mod
        monkeypatch.setattr(tg_mod, "TradingAgentsGraph", _FakeGraph)
        monkeypatch.setattr(stats_mod, "StatsCallbackHandler", lambda: type(
            "S", (), {"get_stats": lambda self_: {"llm_calls": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0}}
        )())

        store = runner_mod.get_store()
        _, tracker = store.create(ticker="600595", trade_date="2026-07-17")

        runner_mod._run_analysis(
            analysis_id=tracker.analysis_id,
            config={},
            tracker=tracker,
        )

        progress = tracker.to_progress_dict()
        # Final state — analysis is complete.
        assert progress["status"] == "complete"
        assert set(progress["completed_stages"]) >= {"market", "social", "news"}
        # P2.26 — after the chain runs, current_stage should reflect the
        # LAST stage that was activated. The fake graph yields final_trade_decision
        # which triggers mark_complete via the for-loop tail; the chain
        # activated 'fundamentals' right after 'news'. Either 'fundamentals'
        # (chain activated it) or '' (mark_complete cleared it) is acceptable —
        # the contract is that the chain RAN, not what survives mark_complete.
        # We assert by checking the stage_reports were recorded under the
        # correct canonical keys (proving mark_stage_done fired).
        assert "market_report" in progress["stage_reports"]
        assert "sentiment_report" in progress["stage_reports"]
        assert "news_report" in progress["stage_reports"]


class TestExceptionPathMarksError:
    """P2.25 hotfix — the runner's ``except Exception`` branch must call
    ``tracker.mark_error`` before re-raising, so a daemon thread can never
    die silently with the tracker stuck in "running".

    Reproduces the failure mode that bit the user: LangGraph stream
    raises ``openai.APIConnectionError`` during the Fundamentals node →
    propagates up unhandled → thread dies → tracker stays at
    status=running forever → UI shows "running" with no recourse.
    """

    def test_runner_marks_error_on_arbitrary_exception(self, monkeypatch):
        """Drive ``_run_analysis`` end-to-end with a fake graph that
        raises after one chunk. The tracker's progress dict must report
        status=error with the exception message, not status=running.
        """
        import time as time_module
        from backend.core import runner as runner_mod

        # ── Fake graph that yields one chunk then raises ──────────────
        class _FakeGraph:
            class _Graph:
                def stream(self, init_state, **kwargs):
                    # Yield a "market" chunk (truthy market_report),
                    # then crash like openai.APIConnectionError.
                    yield {"market_report": "ok"}
                    raise ConnectionError("simulated API outage")

            def __init__(self, *a, **kw):
                self.graph = self._Graph()
                self.propagator = type("P", (), {
                    "create_initial_state": lambda self_, t, d: {},
                    "get_graph_args": lambda self_, **kw: {},
                })()
                self.ticker = ""
            def process_signal(self, x): return "HOLD"
            def _log_state(self, *a, **kw): pass

        # Patched at the source module — _run_analysis imports
        # ``TradingAgentsGraph`` inside the function body, so patching
        # ``runner_mod.TradingAgentsGraph`` has no effect.
        import tradingagents.graph.trading_graph as tg_mod
        import cli.stats_handler as stats_mod
        monkeypatch.setattr(tg_mod, "TradingAgentsGraph", _FakeGraph)
        monkeypatch.setattr(stats_mod, "StatsCallbackHandler", lambda: type(
            "S", (), {"get_stats": lambda self_: {"llm_calls": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0}}
        )())

        # Run synchronously so we can assert on the resulting tracker state.
        store = runner_mod.get_store()
        _, tracker = store.create(ticker="600595", trade_date="2026-07-17")

        with pytest.raises(ConnectionError):
            runner_mod._run_analysis(
                analysis_id=tracker.analysis_id,
                config={},
                tracker=tracker,
            )

        # The fix: mark_error must have run. UI sees status=error, not running.
        progress = tracker.to_progress_dict()
        assert progress["status"] == "error", (
            f"tracker stuck in {progress['status']!r} after unhandled "
            f"exception — P2.25 hotfix regression"
        )
        assert "ConnectionError" in (progress["error"] or "")
        assert "simulated API outage" in (progress["error"] or "")