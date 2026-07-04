"""Regression tests for the running-view refresh pattern in web/app.py.

Bug history
-----------
Originally the running branch in web/app.py used
``render_progress(tracker); time.sleep(2); st.rerun()`` to poll for
progress updates. ``time.sleep`` blocked the Streamlit script runner for
the full 2 s on every cycle; during long analyses (15-25 s, longer for
batch) the script thread held on long enough that the WebSocket ping
(~10 s default) was missed and the browser showed "Connection failed".

The user reported this from the sector panel flow specifically: clicking
分析 on a stock row successfully set ``start_analysis`` and triggered a
rerun, but the browser then dropped the connection before the analyze
page could render — perceived as "the link from sector panel to analyze
page broke".

Fix
---
The running branch now renders inside an ``st.fragment(run_every=2)``
that re-executes itself on a separate scheduler tick. The main script
thread no longer blocks on a sleep, so heartbeats keep flowing. When the
tracker flips to a terminal state, the fragment triggers an
``st.rerun(scope="app")`` so ``resolve_main_view`` re-renders the
completed report or error.

These tests guard against regressions to the blocking-poll pattern.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_APP_PY = Path(__file__).resolve().parent.parent / "web" / "app.py"


def _read_app() -> str:
    return _APP_PY.read_text(encoding="utf-8")


def _running_branch(text: str) -> str:
    """Extract the running-view region from web/app.py — from the
    ``@st.fragment(...)`` decorator down to the closing line of the
    ``if view == VIEW_RUNNING:`` block. The fragment lives above the
    ``if`` block but is logically part of the running branch."""
    frag = re.search(
        r"@st\.fragment\(run_every=[^\n]*\)\s*\n"
        r"def _running_view[^\n]*:\s*\n"
        r"(?P<decorator>.*?)"
        r"(?=\n\s*\n\s*\nif view == VIEW_RUNNING)",
        text,
        flags=re.DOTALL,
    )
    if_block = re.search(
        r"if view == VIEW_RUNNING:\n(?P<body>(?:\n|.)*?)(?=\n# |\n# ─|\nelif view == )",
        text,
    )
    assert if_block is not None, "could not locate ``if view == VIEW_RUNNING:`` in web/app.py"
    body = if_block.group("body")
    if frag is not None:
        body = "@st.fragment(run_every=...)\n" + frag.group("decorator") + "\n" + body
    return body


@pytest.mark.unit
def test_running_branch_does_not_block_with_time_sleep():
    """The original bug: ``time.sleep(2)`` in the running branch blocked the
    Streamlit script runner and starved the WebSocket ping. Guard against
    any future regression by asserting the running branch contains no
    time.sleep call."""
    body = _running_branch(_read_app())
    assert "time.sleep" not in body, (
        "running branch must not call time.sleep — it blocks the Streamlit "
        "script runner and causes WebSocket ping timeouts. Use "
        "st.fragment(run_every=...) instead."
    )


@pytest.mark.unit
def test_running_branch_uses_fragment_with_run_every():
    """The running branch must render inside a fragment that auto-refreshes
    so progress updates without blocking the main script."""
    body = _running_branch(_read_app())
    assert "st.fragment(run_every=" in body, (
        "running branch must wrap render_progress in st.fragment(run_every=...) "
        "for non-blocking progress refresh."
    )
    assert "render_progress" in body, (
        "running branch should still call render_progress(tracker)."
    )


@pytest.mark.unit
def test_running_branch_reruns_parent_on_terminal_transition():
    """When the background thread flips the tracker to complete/errored, the
    fragment must rerun the parent app so resolve_main_view transitions to
    VIEW_COMPLETE / VIEW_ERROR — otherwise the user is stuck on the
    progress view forever."""
    body = _running_branch(_read_app())
    assert "st.rerun(scope=\"app\")" in body or "st.rerun(scope='app')" in body, (
        "fragment must trigger a parent rerun when tracker leaves the "
        "running state, otherwise the completed report never appears."
    )


@pytest.mark.unit
def test_running_branch_does_not_call_unconditional_st_rerun():
    """The OLD pattern was ``render_progress(...); st.rerun()`` — a parent
    rerun on every fragment tick. With the new fragment-based pattern, only
    the terminal transition should trigger an app-scope rerun; bare
    ``st.rerun()`` in the running branch would defeat the fragment."""
    body = _running_branch(_read_app())
    assert "st.rerun()" not in body.replace("st.rerun(scope=\"app\")", "").replace(
        "st.rerun(scope='app')", ""
    ), (
        "running branch should not call bare st.rerun() — use "
        "st.rerun(scope=\"app\") only on terminal transition, or rely on "
        "the fragment's own run_every tick."
    )