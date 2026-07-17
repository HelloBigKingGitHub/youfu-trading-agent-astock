"""Background runner that wraps web/runner.run_analysis_in_thread for FastAPI use."""

from __future__ import annotations

import threading
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.tracker import AnalysisTracker, get_store
from backend.models.request import AnalyzeRequest


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

    # Map report keys to stage IDs
    stage_map = {
        "market_report": "market",
        "sentiment_report": "social",
        "news_report": "news",
        "fundamentals_report": "fundamentals",
        "policy_report": "policy",
        "hot_money_report": "hot_money",
        "lockup_report": "lockup",
        "investment_debate_state": "debate",
        "trader_investment_plan": "trader",
        "risk_debate_state": "risk",
        "final_trade_decision": "pm",
    }

    stage_order = list(stage_map.values())

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
    MAX_RUN_SEC = 600  # 10 minutes — matches STUCK_THRESHOLD_SEC in history_store.py

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
            for report_key, stage_id in stage_map.items():
                content = chunk.get(report_key, "")
                if content and tracker.stage_status(stage_id) != "done":
                    if tracker.current_stage != stage_id:
                        tracker.mark_stage_active(stage_id)
                    tracker.mark_stage_done(
                        stage_id,
                        str(content)[:500],
                        report_key=report_key,
                    )
                    _activate_next_stage(stage_id)
                    # P2.21 hotfix — previously this cleared current_stage to ""
                    # after every mark_stage_done, which made the React progress
                    # UI show no current stage during stage transitions (the
                    # user reported the progress tab was blank for 8+ hours).
                    # We now KEEP current_stage pointing at the just-finished
                    # stage until the next stage's chunk arrives and overwrites
                    # it via the `if tracker.current_stage != stage_id` branch
                    # above. The frontend (修 4) additionally infers current_stage
                    # from completed_stages when this is empty for older history
                    # entries, so we don't need to write "" anymore.
                    # tracker.mark_stage_active("")  # ← removed in P2.21

            # Update stats
            s = stats.get_stats()
            tracker.update_stats(s["llm_calls"], s["tool_calls"], s["tokens_in"], s["tokens_out"])

            time_module.sleep(0.5)

        signal = graph.process_signal(last_chunk.get("final_trade_decision", ""))
        tracker.mark_complete(last_chunk, signal)

        graph.ticker = tracker.ticker
        graph._log_state(tracker.trade_date, last_chunk)
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