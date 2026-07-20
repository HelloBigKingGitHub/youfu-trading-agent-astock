"""Background runner that wraps web/runner.run_analysis_in_thread for FastAPI use."""

from __future__ import annotations

import threading
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.tracker import AnalysisTracker, get_store
from backend.core.history_store import get_history_store
from backend.models.request import AnalyzeRequest

# P2.28 — mirror web/runner.py's results_path layout. The full report
# file is written by ``graph._log_state()`` under
# ``~/.tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json``;
# the history entry's ``results_path`` field has to point at that exact
# path or ``GET /api/analyze/{id}/report`` 404s with "报告文件丢失"
# even though the file exists on disk.
_RESULTS_DIR = Path.home() / ".tradingagents" / "logs"


def _run_analysis(
    analysis_id: str,
    config: dict,
    tracker: AnalysisTracker,
) -> None:
    """Run the full TradingAgents pipeline in a background thread."""
    from web.progress import ProgressTracker
    from web.runner import run_analysis_in_thread

    # Map our tracker to the web ProgressTracker interface
    web_tracker = ProgressTracker(
        ticker=tracker.ticker,
        trade_date=tracker.trade_date,
    )
    web_tracker.is_running = True
    web_tracker.start_time = tracker.start_time

    # Map tracker callbacks to our store
    def on_stats(llm: int, tool: int, tok_in: int, tok_out: int) -> None:
        tracker.update_stats(llm, tool, tok_in, tok_out)
        web_tracker.update_stats(llm, tool, tok_in, tok_out)

    # We can't easily intercept the runner's internal stats handler,
    # so we poll tracker.elapsed and copy stats
    import time as time_module

    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    stats = StatsCallbackHandler()

    graph = TradingAgentsGraph(
        debug=True,
        config=config,
        callbacks=[stats],
    )

    init_state = graph.propagator.create_initial_state(
        tracker.ticker, tracker.trade_date
    )
    args = graph.propagator.get_graph_args(callbacks=[stats])

    last_chunk: dict = {}

    # Map LangGraph chunk keys to (stage_id, canonical report_key). The
    # chunk key is what the underlying node emits in the stream; the
    # canonical key is what we persist under ``stage_reports`` and what
    # the frontend reads via ``STAGE_TO_REPORT_KEY``. They differ for
    # stages where the LangGraph field name doesn't match the canonical
    # name (e.g. quality_gate's ``data_quality_summary`` chunk is
    # exposed as ``quality_gate_report``).
    stage_map = {
        "market_report": ("market", "market_report"),
        "sentiment_report": ("social", "sentiment_report"),
        "news_report": ("news", "news_report"),
        "fundamentals_report": ("fundamentals", "fundamentals_report"),
        "policy_report": ("policy", "policy_report"),
        "hot_money_report": ("hot_money", "hot_money_report"),
        "lockup_report": ("lockup", "lockup_report"),
        # P2.28 — quality_gate node emits ``data_quality_summary``; expose
        # it under the canonical ``quality_gate_report`` key the frontend
        # expects. Without this mapping quality_gate never landed in
        # ``completed_stages`` and the report summary stopped at 11.
        "data_quality_summary": ("quality_gate", "quality_gate_report"),
        "investment_debate_state": ("debate", "investment_debate_state"),
        "trader_investment_plan": ("trader", "trader_investment_plan"),
        "risk_debate_state": ("risk", "risk_debate_state"),
        "final_trade_decision": ("pm", "final_trade_decision"),
    }

    stage_order = [
        # P2.26 hotfix — explicit pipeline order. Derived from stage_map
        # values it lost ``quality_gate`` (no chunk field for it — the gate
        # fires between lockup and debate), so the auto-chain was skipping
        # over quality_gate when lockup finished. Mirrors the order in
        # ``STAGES`` in frontend/src/components/analyze/analysis-progress.tsx.
        "market", "social", "news", "fundamentals", "policy", "hot_money",
        "lockup", "quality_gate", "debate", "risk", "trader", "pm",
    ]

    def _activate_next_stage(completed_stage: str) -> None:
        """Activate the next pipeline stage as soon as one completes."""
        try:
            next_index = stage_order.index(completed_stage) + 1
        except ValueError:
            return
        for next_stage in stage_order[next_index:]:
            if tracker.stage_status(next_stage) != "done":
                tracker.mark_stage_active(next_stage)
                return

    # Publish the first stage before entering LangGraph. This closes the
    # short all-pending window between POST /api/analyze and the first chunk.
    tracker.mark_stage_active("market")

    # P2.23 hotfix — hard timeout guard.
    #
    # The user reported analysis 600595_2026-07-17_df9be2bf where the LLM
    # structured-output retry path in the Portfolio Manager stage wedged
    # for 10+ minutes (retry-as-free-text hangs), the for-loop over
    # graph.graph.stream() never yielded a final chunk that completed the
    # stream, and tracker.mark_complete() never ran. Without this guard,
    # the thread runs forever, the UI shows "running" with no signal, and
    # users have no recourse. We now enforce a hard 10-minute ceiling:
    # any chunk that arrives after the ceiling triggers a TimeoutError
    # that we catch and convert to tracker.mark_error(), so the user
    # always sees a definitive error/complete state.
    MAX_RUN_SEC = 1800  # 30 minutes — user feedback: real analyses
                       # typically take ~20 min (12 stages × LLM calls).
                       # 10 min was too aggressive and aborted legitimate
                       # long runs (P2.23 hotfix was a stop-gap at 600s).
                       # Must match STUCK_THRESHOLD_SEC in history_store.py.

    try:
        for chunk in graph.graph.stream(init_state, **args):
            last_chunk = chunk

            # Hard timeout check — checked once per chunk, which is
            # bounded by the graph's own yield rate (every node boundary).
            if time_module.time() - tracker.start_time > MAX_RUN_SEC:
                raise TimeoutError(
                    f"分析超过 {MAX_RUN_SEC}s 硬上限, 强制终止 (P2.23 hotfix, "
                    f"最后阶段: {tracker.current_stage or 'unknown'})"
                )

            # Update current stage based on chunk keys
            for chunk_key, (stage_id, canonical_key) in stage_map.items():
                content = chunk.get(chunk_key, "")
                if not content or tracker.stage_status(stage_id) == "done":
                    continue
                # Dict stages (debate / risk) — only count as done once the
                # judge node has produced a non-empty decision. The empty
                # initial state ``{'count': 0, ..., 'judge_decision': ''}``
                # is otherwise truthy and would fire mark_stage_done on the
                # first chunk. P2.26 hotfix — re-added after a refactor
                # dropped the guard, which caused empty-dict stage_reports
                # to land in the workspace tab.
                if chunk_key in {"investment_debate_state", "risk_debate_state"}:
                    if not isinstance(content, dict):
                        continue
                    if not content.get("judge_decision"):
                        continue
                if tracker.current_stage != stage_id:
                    tracker.mark_stage_active(stage_id)
                tracker.mark_stage_done(
                    stage_id,
                    str(content)[:500],
                    report_key=canonical_key,
                )
                _activate_next_stage(stage_id)

            # Update stats
            s = stats.get_stats()
            tracker.update_stats(s["llm_calls"], s["tool_calls"], s["tokens_in"], s["tokens_out"])

            time_module.sleep(0.5)

        signal = graph.process_signal(last_chunk.get("final_trade_decision", ""))
        tracker.mark_complete(last_chunk, signal)

        graph.ticker = tracker.ticker
        graph._log_state(tracker.trade_date, last_chunk)

        # P2.28 hotfix — point the history entry at the file
        # ``graph._log_state()`` just wrote. Without this the report
        # endpoint reads ``entry.results_path`` (empty string) and
        # 404s with "报告文件丢失 (results_path='')" even though the
        # file exists on disk. Mirrors web/runner.py:285-289.
        results_path = str(
            _RESULTS_DIR / tracker.ticker / "TradingAgentsStrategy_logs"
            / f"full_states_log_{tracker.trade_date}.json"
        )
        get_history_store().set_results_path(tracker.analysis_id, results_path)
    except TimeoutError as e:
        # P2.23 hotfix — hard timeout, mark error so the user sees a
        # definitive failure rather than "running" forever.
        tracker.mark_error(str(e))
    except Exception as exc:
        # Never leave a daemon-thread analysis stuck in ``running`` when the
        # graph fails before it can produce a completion signal. Keep the
        # exception class in the persisted message for actionable diagnostics.
        tracker.mark_error(f"{type(exc).__name__}: {exc}")
        raise


def start_analysis(
    request: AnalyzeRequest,
) -> tuple[str, AnalysisTracker]:
    """Start a new analysis in a background thread. Returns (analysis_id, tracker)."""
    store = get_store()
    analysis_id, tracker = store.create(request.ticker, request.trade_date)

    # P2.26 hotfix — flip the first stage to "active" synchronously so the
    # progress bar lights up before the worker thread is even scheduled.
    # Without this the very first /progress poll (which can fire ~50ms
    # after POST returns) would see ``current_stage=""`` and show the
    # all-pending empty state for the 100-500ms between submit and the
    # first chunk.
    tracker.mark_stage_active("market")

    from tradingagents.default_config import DEFAULT_CONFIG

    config = {**DEFAULT_CONFIG, **{
        "llm_provider": request.llm_provider,
        "deep_think_llm": request.deep_think_llm,
        "quick_think_llm": request.quick_think_llm,
        "max_debate_rounds": 1,
        "output_language": "Chinese",
        "data_vendors": {
            "core_stock_apis": "a_stock",
            "technical_indicators": "a_stock",
            "fundamental_data": "a_stock",
            "news_data": "a_stock",
            "signal_data": "a_stock",
        },
    }}
    if request.backend_url:
        config["backend_url"] = request.backend_url

    # Load .env for API keys
    from dotenv import load_dotenv
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    thread = threading.Thread(
        target=_run_analysis,
        args=(analysis_id, config, tracker),
        daemon=True,
    )
    thread.start()

    return analysis_id, tracker