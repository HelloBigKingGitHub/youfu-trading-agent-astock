"""Main-area navigation state machine — pure, side-effect-free helpers.

Kept separate from :mod:`web.app` (whose module-level body runs Streamlit page
setup, CSS injection, and sidebar rendering on import) so the dispatch decision
can be unit-tested in isolation without a live Streamlit context.

Bug this module fixes
---------------------
Previously the main-area dispatch in ``web/app.py`` checked "modal" states
(viewing a historical report, an analysis that had completed, or an errored
run) *before* the nav-page dispatch, and each such branch unconditionally
forced ``nav = "analyze"``. A completed ``ProgressTracker`` is never cleared,
so once a report appeared, every rerun re-entered the completed branch and the
sidebar nav could never switch pages.

Fix
---
Terminal report states (history / complete / error) only take over the main
area while the analyze tab is selected (``nav == "analyze"``). Selecting any
other nav page yields to that page. A *running* analysis still always wins so
the user cannot navigate away from live progress. Navigating away also clears
the sticky terminal state (see :func:`plan_nav_click`) so returning to the
analyze tab shows a fresh new-analysis form rather than the stale report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# ── View identifiers returned by resolve_main_view ──────────────────────────
#
# The four terminal / running views use names that DO NOT collide with the nav
# page ids (analyze / batch / sector / history / logs / settings), so a caller
# can branch on the returned string unambiguously. Note VIEW_HISTORY is
# "history_report" (a report overlay), distinct from the "history" nav page.
VIEW_RUNNING = "running"
VIEW_HISTORY = "history_report"
VIEW_COMPLETE = "complete"
VIEW_ERROR = "error"
VIEW_IDLE = "idle"

ANALYZE = "analyze"


class TrackerLike(Protocol):
    """Structural type for the bits of ProgressTracker this module reads."""

    is_running: bool
    is_complete: bool
    error: Any


def resolve_main_view(
    nav: str,
    tracker: TrackerLike | None,
    viewing_history: str | None,
) -> str:
    """Decide what the main content area should render.

    Precedence:

    1. A *running* analysis always wins — the user must see live progress and
       cannot navigate away mid-run.
    2. Terminal report states (viewing a historical report, a completed run, or
       an errored run) render **only while the analyze tab is selected**. This
       is what makes the sidebar nav work again after a report is shown: on any
       other nav page those states are ignored.
    3. Otherwise the selected nav page renders; the analyze tab with no tracker
       and no history overlay falls back to the idle welcome screen.

    Args:
        nav: The currently selected nav page id.
        tracker: The active ProgressTracker, or ``None``.
        viewing_history: Path of a historical report being viewed, or falsy.

    Returns:
        One of the ``VIEW_*`` constants, or a nav page id
        (``"sector"``/``"batch"``/``"history"``/``"logs"``/``"settings"``).
    """
    if tracker is not None and tracker.is_running:
        return VIEW_RUNNING

    if nav == ANALYZE:
        if viewing_history:
            return VIEW_HISTORY
        if tracker is not None and tracker.is_complete:
            return VIEW_COMPLETE
        if tracker is not None and tracker.error:
            return VIEW_ERROR
        return VIEW_IDLE

    # A non-analyze page is selected and nothing is running → show that page.
    return nav


@dataclass(frozen=True)
class NavPlan:
    """Immutable description of the session-state changes for a nav click.

    Applied by the caller against ``st.session_state`` — this module never
    touches Streamlit state itself, which keeps it unit-testable.
    """

    nav: str
    clear_viewing_history: bool
    clear_tracker: bool


def plan_nav_click(page: str, tracker: TrackerLike | None) -> NavPlan:
    """Compute the state changes for clicking a sidebar nav button.

    Navigating dismisses any sticky *terminal* report so it is not trapped on
    screen and so returning to the analyze tab shows a fresh form. A *running*
    tracker is preserved — its background thread must stay tracked and the user
    should not be able to abandon a live run by clicking a nav button.

    Args:
        page: The nav page id the user clicked.
        tracker: The active ProgressTracker, or ``None``.

    Returns:
        A :class:`NavPlan` describing which session-state keys to update/clear.
    """
    is_running = tracker is not None and getattr(tracker, "is_running", False)
    return NavPlan(
        nav=page,
        clear_viewing_history=True,
        clear_tracker=tracker is not None and not is_running,
    )
