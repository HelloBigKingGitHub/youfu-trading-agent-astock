"""Tests for web/components/logs_panel.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_render_logs_panel_shows_empty_state_when_no_tickers(tmp_path, monkeypatch):
    """No log files → '暂无日志' info."""
    monkeypatch.setattr("backend.core.log_store._LOGS_ROOT", tmp_path)
    from web.components.logs_panel import render_logs_panel

    with patch("streamlit.info") as mock_info:
        render_logs_panel()
        mock_info.assert_called_once()
        assert "暂无日志" in mock_info.call_args[0][0]


def test_render_logs_panel_lists_tickers(tmp_path, monkeypatch):
    """2 tickers → render_logs_panel doesn't raise on basic streamlit mock."""
    monkeypatch.setattr("backend.core.log_store._LOGS_ROOT", tmp_path)
    from backend.core.log_store import LogWriter

    LogWriter("a", "600595", "2026-06-30")
    LogWriter("b", "000001", "2026-06-30")

    from web.components.logs_panel import render_logs_panel

    with patch("streamlit.columns") as mock_cols:
        col_a = MagicMock()
        col_b = MagicMock()
        mock_cols.return_value = (col_a, col_b)
        # Should not raise
        render_logs_panel()


def test_render_running_tasks_shows_when_tracker_running():
    """st.session_state.tracker.is_running=True → running card rendered."""
    mock_tracker = MagicMock()
    mock_tracker.is_running = True
    mock_tracker.ticker = "688596"
    mock_tracker.trade_date = "2026-06-30"
    mock_tracker.completed_stages = ["market", "social"]
    mock_tracker.llm_calls = 3
    mock_tracker.tool_calls = 1
    mock_tracker.tokens_in = 500
    mock_tracker.tokens_out = 200

    from web.components.logs_panel import _render_running_tasks

    with patch("streamlit.session_state", {"tracker": mock_tracker}):
        with patch("streamlit.html") as mock_html:
            _render_running_tasks()
            assert mock_html.called
            call_args = str(mock_html.call_args_list)
            assert "688596" in call_args
            assert "运行中" in call_args or "🔥" in call_args


def test_render_running_tasks_skipped_when_no_tracker():
    """No tracker in session → no render."""
    from web.components.logs_panel import _render_running_tasks

    with patch("streamlit.session_state", {}):
        with patch("streamlit.html") as mock_html:
            _render_running_tasks()
            assert not mock_html.called


def test_signal_to_badge_class_buy_is_bull():
    from web.components.logs_panel import _signal_to_badge_class

    assert _signal_to_badge_class("Buy") == "bull"
    assert _signal_to_badge_class("Overweight") == "bull"
    assert _signal_to_badge_class("Underweight") == "bear"
    assert _signal_to_badge_class("Hold") == "hold"
    assert _signal_to_badge_class("") == "neutral"


def test_chunk_card_renders_correctly_for_llm():
    """LLM chunk → icon 🧠 + tokens info, content shown via st.code."""
    from backend.core.log_store import LogChunk
    from web.components.logs_panel import _render_chunk_card

    chunk = LogChunk(
        ts=1.0,
        type="llm",
        agent="market_analyst",
        role="assistant",
        tokens_in=100,
        tokens_out=50,
        content="hi",
    )

    with patch("streamlit.container") as mock_container, \
         patch("streamlit.html") as mock_html, \
         patch("streamlit.code") as mock_code:
        mock_container.return_value.__enter__ = MagicMock()
        mock_container.return_value.__exit__ = MagicMock()
        _render_chunk_card(chunk)
        assert mock_code.called
        assert mock_code.call_args[0][0] == "hi"