"""Background thread runner for TradingAgentsGraph pipeline."""

from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.history_store import get_history_store
from web.progress import PIPELINE_STAGES, ProgressTracker

_history_store = get_history_store()
_RESULTS_DIR = Path.home() / ".tradingagents" / "logs"


_REPORT_KEY_TO_STAGE = {s["report_key"]: s["id"] for s in PIPELINE_STAGES}

_ANALYST_REPORT_KEYS = [
    "market_report", "sentiment_report", "news_report",
    "fundamentals_report", "policy_report", "hot_money_report", "lockup_report",
]


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _detect_completed_stages(
    chunk: dict[str, Any],
    tracker: ProgressTracker,
) -> None:
    """Check the streamed chunk for newly completed stages."""
    for report_key in _ANALYST_REPORT_KEYS:
        stage_id = _REPORT_KEY_TO_STAGE[report_key]
        content = chunk.get(report_key, "")
        if content and tracker.stage_status(stage_id) != "done":
            tracker.mark_stage_done(stage_id, _strip_think_tags(str(content)))

    dqs = chunk.get("data_quality_summary", "")
    if dqs and tracker.stage_status("quality_gate") != "done":
        tracker.mark_stage_done("quality_gate", str(dqs))

    debate = chunk.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        judge = debate.get("judge_decision", "")
        if judge and tracker.stage_status("debate") != "done":
            tracker.mark_stage_done("debate", str(judge))

    trader_plan = chunk.get("trader_investment_plan", "")
    if trader_plan and tracker.stage_status("trader") != "done":
        tracker.mark_stage_done("trader", _strip_think_tags(str(trader_plan)))

    risk = chunk.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        risk_judge = risk.get("judge_decision", "")
        if risk_judge and tracker.stage_status("risk") != "done":
            tracker.mark_stage_done("risk", str(risk_judge))

    final = chunk.get("final_trade_decision", "")
    if final and tracker.stage_status("pm") != "done":
        tracker.mark_stage_done("pm", _strip_think_tags(str(final)))


def _infer_active_stage(tracker: ProgressTracker) -> None:
    """Set the current_stage to the first non-completed stage."""
    from web.progress import STAGE_IDS
    for sid in STAGE_IDS:
        if tracker.stage_status(sid) == "pending":
            tracker.mark_stage_active(sid)
            return


def _run(ticker: str, trade_date: str, config: dict, tracker: ProgressTracker, analysis_id: str) -> None:
    """Execute the full pipeline in the current thread."""
    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    stats = StatsCallbackHandler()

    graph = TradingAgentsGraph(
        debug=True,
        config=config,
        callbacks=[stats],
    )

    init_state = graph.propagator.create_initial_state(ticker, trade_date)
    args = graph.propagator.get_graph_args(callbacks=[stats])

    last_chunk: dict[str, Any] = {}

    for chunk in graph.graph.stream(init_state, **args):
        last_chunk = chunk
        _detect_completed_stages(chunk, tracker)
        _infer_active_stage(tracker)

        s = stats.get_stats()
        tracker.update_stats(s["llm_calls"], s["tool_calls"], s["tokens_in"], s["tokens_out"])

    signal = graph.process_signal(last_chunk.get("final_trade_decision", ""))

    graph.ticker = ticker
    graph._log_state(trade_date, last_chunk)

    tracker.mark_complete(last_chunk, signal)

    # Save "completed" history entry via unified store
    elapsed = time.time() - tracker.start_time
    _history_store.mark_complete(
        analysis_id,
        signal=signal,
        elapsed=elapsed,
        completed_stages=list(tracker.completed_stages),
    )
    # Set the results path so report viewer can find the full log
    results_path = str(_RESULTS_DIR / ticker / "TradingAgentsStrategy_logs" / f"full_states_log_{trade_date}.json")
    _history_store.set_results_path(analysis_id, results_path)


def run_analysis_in_thread(
    ticker: str,
    trade_date: str,
    config: dict,
    tracker: ProgressTracker,
) -> threading.Thread:
    """Launch the pipeline in a daemon thread. Returns the thread handle."""
    tracker.ticker = ticker
    tracker.trade_date = trade_date
    tracker.is_running = True
    tracker.mark_stage_active("market")

    # Create history entry via unified store
    entry = _history_store.create(ticker, trade_date, status="running")
    analysis_id = entry.analysis_id
    tracker.analysis_id = analysis_id

    def _target() -> None:
        start = time.time()
        try:
            _run(ticker, trade_date, config, tracker, analysis_id)
        except Exception as exc:
            tracker.mark_error(str(exc))
            elapsed = time.time() - start
            _history_store.mark_error(analysis_id, str(exc), elapsed=elapsed)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t
