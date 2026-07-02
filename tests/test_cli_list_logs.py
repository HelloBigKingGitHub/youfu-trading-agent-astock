"""Tests for cli/list_logs.py."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.core.log_store import LogWriter


@pytest.fixture
def isolated_logs_root(tmp_path, monkeypatch):
    """Redirect LOGS_ROOT to a tmp dir so tests don't touch real ~/.tradingagents/."""
    monkeypatch.setattr("backend.core.log_store._LOGS_ROOT", tmp_path)
    return tmp_path


def test_list_logs_with_no_tickers_prints_message(capsys, isolated_logs_root):
    """Empty log dir → prints 'No tickers have logs yet' message."""
    from cli.list_logs import main

    with patch("sys.argv", ["list_logs"]):
        main()

    captured = capsys.readouterr()
    assert "No tickers" in captured.out


def test_list_logs_for_specific_ticker_prints_table(capsys, isolated_logs_root):
    """Filter by ticker → prints task row with date + status + signal."""
    LogWriter("a", "600595", "2026-06-30")

    from cli.list_logs import main

    with patch("sys.argv", ["list_logs", "600595"]):
        main()

    captured = capsys.readouterr()
    assert "600595" in captured.out
    assert "2026-06-30" in captured.out
    assert "running" in captured.out


def test_list_logs_includes_legacy(capsys, isolated_logs_root):
    """Legacy full_states_log_*.json also shows up with [LEGACY] marker."""
    legacy = isolated_logs_root / "000001" / "TradingAgentsStrategy_logs"
    legacy.mkdir(parents=True)
    (legacy / "full_states_log_2026-06-10.json").write_text(json.dumps({
        "company_of_interest": "000001",
        "trade_date": "2026-06-10",
        "market_report": "x",
        "final_trade_decision": "BUY",
    }))

    from cli.list_logs import main

    with patch("sys.argv", ["list_logs"]):
        main()

    captured = capsys.readouterr()
    assert "000001" in captured.out
    assert "LEGACY" in captured.out