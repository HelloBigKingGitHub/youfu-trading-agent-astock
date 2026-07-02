"""Background thread runner for TradingAgentsGraph pipeline."""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

import sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.history_store import get_history_store
from backend.core.log_store import LogChunk, LogWriter
from web.progress import PIPELINE_STAGES, ProgressTracker

logger = logging.getLogger(__name__)

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

    # Init log writer (creates task dir + meta.json)
    log_writer = LogWriter(analysis_id, ticker, trade_date)
    last_chunk: dict[str, Any] = {}
    last_stats: dict = {"llm_calls": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0}
    completed_stages: list[str] = []

    try:
        for chunk in graph.graph.stream(init_state, **args):
            last_chunk = chunk

            # === 现有逻辑 (不动) ===
            _detect_completed_stages(chunk, tracker)
            _infer_active_stage(tracker)
            s = stats.get_stats()
            tracker.update_stats(s["llm_calls"], s["tool_calls"], s["tokens_in"], s["tokens_out"])
            last_stats = s

            # === 新增: 写 log chunks (try/except 不 raise) ===
            try:
                for log_chunk in _classify_chunk(chunk, last_stats):
                    log_writer.append_chunk(log_chunk)
            except Exception as e:
                logger.warning("LogWriter.append_chunk failed: %s", e)

            # 阶段完成时更新 meta
            for stage in tracker.completed_stages:
                if stage not in completed_stages:
                    completed_stages.append(stage)
            log_writer.update_stages(completed_stages)

        signal = graph.process_signal(last_chunk.get("final_trade_decision", ""))

        # 现有 final state 写盘 (保持)
        graph.ticker = ticker
        graph._log_state(trade_date, last_chunk)

        tracker.mark_complete(last_chunk, signal)
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

        # === 新增: finalize log writer ===
        log_writer.finalize(signal=signal, elapsed_sec=elapsed,
                            completed_stages=completed_stages)

    except Exception as exc:
        tracker.mark_error(str(exc))
        elapsed = time.time() - tracker.start_time
        _history_store.mark_error(analysis_id, str(exc), elapsed=elapsed)
        # === 新增: error finalize ===
        try:
            log_writer.finalize(signal="", elapsed_sec=elapsed, error=str(exc))
        except Exception:
            pass
        raise


_KEY_TO_AGENT_NAME = {
    "market_report": "market_analyst",
    "sentiment_report": "social_analyst",
    "news_report": "news_analyst",
    "fundamentals_report": "fundamentals_analyst",
    "policy_report": "policy_analyst",
    "hot_money_report": "hot_money_tracker",
    "lockup_report": "lockup_monitor",
    "investment_plan": "research_manager",
    "final_trade_decision": "risk_manager",
}


def _classify_chunk(chunk: dict[str, Any], stats: dict) -> Iterator[LogChunk]:
    """Yield LogChunks for a single LangGraph state snapshot.

    Heuristic:
    - agent_output fields (9 keys): → 1 agent_output chunk each
    - investment_debate_state / risk_debate_state with judge_decision: → 1 llm chunk
    - trader_investment_plan: → 1 llm chunk
    """
    now = time.time()

    AGENT_OUTPUT_KEYS = (
        "market_report", "sentiment_report", "news_report",
        "fundamentals_report", "policy_report", "hot_money_report", "lockup_report",
        "investment_plan", "final_trade_decision",
    )
    for key in AGENT_OUTPUT_KEYS:
        if key in chunk and chunk[key]:
            agent_name = _KEY_TO_AGENT_NAME.get(key, key)
            yield LogChunk(
                ts=now,
                type="agent_output",
                agent=agent_name,
                report_key=key,
                content=str(chunk[key])[:50000],
            )

    debate = chunk.get("investment_debate_state", {})
    if isinstance(debate, dict) and debate.get("judge_decision"):
        yield LogChunk(
            ts=now,
            type="llm",
            agent="research_manager",
            role="assistant",
            content=str(debate["judge_decision"])[:50000],
        )

    risk = chunk.get("risk_debate_state", {})
    if isinstance(risk, dict) and risk.get("judge_decision"):
        yield LogChunk(
            ts=now,
            type="llm",
            agent="risk_manager",
            role="assistant",
            content=str(risk["judge_decision"])[:50000],
        )

    trader_plan = chunk.get("trader_investment_plan", "")
    if trader_plan:
        yield LogChunk(
            ts=now,
            type="llm",
            agent="trader",
            role="assistant",
            content=str(trader_plan)[:50000],
        )


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
