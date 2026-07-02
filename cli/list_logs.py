"""CLI: 列出所有任务的日志摘要. 用法: python -m cli.list_logs [ticker]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.core.log_store import get_log_store


def main():
    parser = argparse.ArgumentParser(description="List all analysis task logs")
    parser.add_argument("ticker", nargs="?", help="Filter to one ticker")
    parser.add_argument("--legacy", action="store_true", help="Include legacy full_states_log_*.json tasks")
    args = parser.parse_args()

    store = get_log_store()

    if args.ticker:
        tasks = store.list_tasks(args.ticker)
        if not tasks:
            print(f"No tasks for ticker {args.ticker}")
            return
        print(f"\n{args.ticker} ({len(tasks)} tasks):")
        for t in tasks:
            legacy_marker = " [LEGACY]" if t.is_legacy else ""
            print(f"  {t.trade_date}  {t.task_dir_name}  {t.status:10}  {t.signal:12}  {t.elapsed_sec:6.1f}s{legacy_marker}")
    else:
        tickers = store.list_tickers()
        if not tickers:
            print("No tickers have logs yet")
            return
        for ticker in tickers:
            tasks = store.list_tasks(ticker)
            print(f"\n{ticker} ({len(tasks)} tasks):")
            for t in tasks:
                legacy_marker = " [LEGACY]" if t.is_legacy else ""
                print(f"  {t.trade_date}  {t.task_dir_name}  {t.status:10}  {t.signal:12}  {t.elapsed_sec:6.1f}s{legacy_marker}")


if __name__ == "__main__":
    main()