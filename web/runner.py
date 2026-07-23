"""Background thread runner for TradingAgentsGraph pipeline."""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import sys
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.history_store import get_history_store
from backend.core.log_store import LogChunk, LogWriter
from web.progress import PIPELINE_STAGES, ProgressTracker

logger = logging.getLogger(__name__)

# P2.32 hotfix — call get_history_store() lazily on every access.
# Previously the module captured a reference at import time, which
# locked in the *initial* HistoryStore singleton before lifespan
# could swap it for DualWriteHistoryStore (Phase 3b) — new analyses
# only wrote JSON, the SQLite sidecar stayed empty, and READ_FROM_SQLITE=1
# read 0 rows.
def _history_store():
    return get_history_store()
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
    """Execute the full pipeline in the current thread.

    Owns the LogWriter (H2 meta.json + agent_outputs.jsonl + tool_calls.jsonl
    + llm_messages.jsonl). ``run_one_analysis`` wraps this with H1 history
    management so all 4 entry points (Web UI / batch API / CLI / scheduler)
    share the same H1+H2 path.
    """
    # Streamlit 架构性 trap 防护 (v0.7.0.P0):
    # CPython ``concurrent.futures.thread`` 在 import 时通过
    # ``threading._register_atexit(_python_exit)`` 注册模块全局
    # ``_shutdown=True``。一旦 streamlit 的 file watcher 检测到 web/ 下源文件
    # 变更触发 script rerun, 进程 interpreter 进入 shutdown 阶段, 这个
    # 全局 flag 会被永久置 True, 进程虽不退出但后续所有
    # ThreadPoolExecutor.submit 都抛 "cannot schedule new futures after
    # interpreter shutdown"。
    #
    # 关键洞察 (本地验证): ``_shutdown`` 只是 submit() 的 bool 守卫, worker
    # threads 还在, 把 flag 重置回 False 后 ThreadPoolExecutor 就能继续
    # 工作。所以防护策略 = 检测 + 重置, 而不是只抛错。
    import concurrent.futures.thread as _cf_thread
    if _cf_thread._shutdown:
        _cf_thread._shutdown = False
        logger.warning(
            "Reset concurrent.futures.thread._shutdown=False (streamlit "
            "hot-reload 触发的 _python_exit 钩子锁死了 thread pool; "
            "已绕过, 但建议重启 streamlit 避免其他模块残留异常)."
        )

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
        log_writer.finalize(signal=signal, elapsed_sec=elapsed,
                            completed_stages=completed_stages)

    except Exception as exc:
        tracker.mark_error(str(exc))
        elapsed = time.time() - tracker.start_time
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


def run_one_analysis(ticker: str, trade_date: str, config: dict) -> str:
    """Run one analysis synchronously through the canonical entry point.

    This is the only high-level single-analysis API. It owns creation and
    finalization of the **H1** history entry (history.json), and delegates
    the **H2** stream chunks / meta.json to ``_run``.

    Behaviour identical to the Web UI's per-button flow (which previously
    called ``run_analysis_in_thread``); batch API, CLI batch and the
    scheduler route through here so they also write a history entry.
    """
    started_at = time.time()
    hs = _history_store()
    entry = hs.create(ticker, trade_date, status="running")
    analysis_id = entry.analysis_id
    tracker = ProgressTracker(
        analysis_id=analysis_id,
        ticker=ticker,
        trade_date=trade_date,
    )
    tracker.is_running = True
    tracker.mark_stage_active("market")

    try:
        _run(ticker, trade_date, config, tracker, analysis_id)
    except Exception as exc:
        tracker.mark_error(str(exc))
        hs = _history_store()
        hs.mark_error(analysis_id, str(exc),
                      elapsed=time.time() - started_at)
        raise

    elapsed = time.time() - started_at
    hs = _history_store()
    hs.mark_complete(
        analysis_id,
        signal=tracker.signal or "",
        elapsed=elapsed,
        completed_stages=list(tracker.completed_stages),
    )
    results_path = str(
        _RESULTS_DIR / ticker / "TradingAgentsStrategy_logs"
        / f"full_states_log_{trade_date}.json"
    )
    hs.set_results_path(analysis_id, results_path)
    return analysis_id


def run_analysis_in_thread(
    ticker: str,
    trade_date: str,
    config: dict,
    tracker: ProgressTracker | None = None,
) -> threading.Thread:
    """Backward-compat wrapper - 内部调 run_one_analysis + 自己开 thread.

    Web UI 还在用这个. run_one_analysis 创建自己的 tracker (canonical).
    Legacy tracker 收到 error 时会 mark_error (best-effort), 别的 live
    updates 由 canonical tracker 负责. 调 run_one_analysis 不返回
    analysis_id 给 legacy tracker 是可接受的, 这是 web UI legacy tracker,
    不影响后续 console 业务.
    """
    if tracker is not None:
        tracker.ticker = ticker
        tracker.trade_date = trade_date
        tracker.is_running = True
        tracker.mark_stage_active("market")

    def _target() -> None:
        try:
            run_one_analysis(ticker, trade_date, config)
        except Exception as exc:
            if tracker is not None:
                tracker.mark_error(str(exc))

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t
