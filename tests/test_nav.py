"""Tests for web/nav.py — the main-area navigation state machine.

Covers the reported bug: after an analysis completes and the report shows,
selecting a different sidebar nav page must switch the main area (previously
the completed tracker pinned the view to the report forever).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from web.nav import (
    VIEW_COMPLETE,
    VIEW_ERROR,
    VIEW_HISTORY,
    VIEW_IDLE,
    VIEW_RUNNING,
    NavPlan,
    plan_nav_click,
    resolve_main_view,
)


@dataclass
class FakeTracker:
    """Minimal stand-in for ProgressTracker (structural match)."""

    is_running: bool = False
    is_complete: bool = False
    error: Any = None


# ── resolve_main_view: running always wins ──────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize("nav", ["analyze", "sector", "batch", "history", "logs", "settings"])
def test_running_tracker_always_shows_progress(nav):
    """A running analysis pins the main area to progress regardless of nav."""
    tracker = FakeTracker(is_running=True)
    assert resolve_main_view(nav, tracker, None) == VIEW_RUNNING


# ── resolve_main_view: terminal states only on the analyze tab ──────────────


@pytest.mark.unit
def test_completed_tracker_shows_report_on_analyze_tab():
    tracker = FakeTracker(is_complete=True)
    assert resolve_main_view("analyze", tracker, None) == VIEW_COMPLETE


@pytest.mark.unit
@pytest.mark.parametrize("nav", ["sector", "batch", "history", "logs", "settings"])
def test_completed_tracker_yields_to_other_nav_pages(nav):
    """THE BUG: with a completed tracker, clicking another nav page must
    switch the main area to that page instead of re-showing the report."""
    tracker = FakeTracker(is_complete=True)
    assert resolve_main_view(nav, tracker, None) == nav


@pytest.mark.unit
def test_errored_tracker_shows_error_on_analyze_tab():
    tracker = FakeTracker(error="boom")
    assert resolve_main_view("analyze", tracker, None) == VIEW_ERROR


@pytest.mark.unit
@pytest.mark.parametrize("nav", ["sector", "history", "settings"])
def test_errored_tracker_yields_to_other_nav_pages(nav):
    tracker = FakeTracker(error="boom")
    assert resolve_main_view(nav, tracker, None) == nav


@pytest.mark.unit
def test_viewing_history_shows_report_on_analyze_tab():
    assert resolve_main_view("analyze", None, "/path/to/report.json") == VIEW_HISTORY


@pytest.mark.unit
@pytest.mark.parametrize("nav", ["sector", "history", "logs"])
def test_viewing_history_yields_to_other_nav_pages(nav):
    """A historical-report overlay must also not trap the nav."""
    assert resolve_main_view(nav, None, "/path/to/report.json") == nav


# ── resolve_main_view: idle / plain nav ─────────────────────────────────────


@pytest.mark.unit
def test_analyze_tab_with_nothing_is_idle():
    assert resolve_main_view("analyze", None, None) == VIEW_IDLE


@pytest.mark.unit
@pytest.mark.parametrize("nav", ["sector", "batch", "history", "logs", "settings"])
def test_plain_nav_pages_pass_through(nav):
    assert resolve_main_view(nav, None, None) == nav


@pytest.mark.unit
def test_running_beats_viewing_history():
    """Defensive: a live run wins even if a history overlay is somehow set."""
    tracker = FakeTracker(is_running=True)
    assert resolve_main_view("analyze", tracker, "/x.json") == VIEW_RUNNING


# ── plan_nav_click: dismiss sticky terminal state, preserve running run ──────


@pytest.mark.unit
def test_nav_click_clears_completed_tracker_and_history():
    plan = plan_nav_click("sector", FakeTracker(is_complete=True))
    assert plan == NavPlan(nav="sector", clear_viewing_history=True, clear_tracker=True)


@pytest.mark.unit
def test_nav_click_clears_errored_tracker():
    plan = plan_nav_click("history", FakeTracker(error="boom"))
    assert plan.clear_tracker is True
    assert plan.nav == "history"


@pytest.mark.unit
def test_nav_click_preserves_running_tracker():
    """A running run must not be discarded by a nav click."""
    plan = plan_nav_click("settings", FakeTracker(is_running=True))
    assert plan.clear_tracker is False
    assert plan.clear_viewing_history is True


@pytest.mark.unit
def test_nav_click_with_no_tracker():
    plan = plan_nav_click("analyze", None)
    assert plan == NavPlan(nav="analyze", clear_viewing_history=True, clear_tracker=False)


@pytest.mark.unit
def test_nav_click_to_analyze_clears_completed_report():
    """Clicking 分析 after a completed run resets to a fresh form
    (clear_tracker=True) rather than re-showing the stale report."""
    plan = plan_nav_click("analyze", FakeTracker(is_complete=True))
    assert plan.nav == "analyze"
    assert plan.clear_tracker is True
