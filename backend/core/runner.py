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

    for chunk in graph.graph.stream(init_state, **args):
        last_chunk = chunk

        # Update current stage based on chunk keys
        for report_key, stage_id in stage_map.items():
            content = chunk.get(report_key, "")
            if content and tracker.stage_status(stage_id) != "done":
                if tracker.current_stage != stage_id:
                    tracker.mark_stage_active(stage_id)
                tracker.mark_stage_done(stage_id, str(content)[:500])
                tracker.mark_stage_active("")  # Clear active after marking done

        # Update stats
        s = stats.get_stats()
        tracker.update_stats(s["llm_calls"], s["tool_calls"], s["tokens_in"], s["tokens_out"])

        time_module.sleep(0.5)

    signal = graph.process_signal(last_chunk.get("final_trade_decision", ""))
    tracker.mark_complete(last_chunk, signal)

    graph.ticker = tracker.ticker
    graph._log_state(tracker.trade_date, last_chunk)


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