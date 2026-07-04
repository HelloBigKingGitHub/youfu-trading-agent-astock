"""Regression test: web/app.py module-level code must run without NameError.

Bug context (2026-07-04):
    A refactor accidentally renamed the local ``nav`` binding on line 360 to
    ``view`` (reading the wrong session_state key), but the very next line
    still called ``resolve_main_view(nav, ...)``. Result: streamlit main
    page crashed on first load with::

        NameError: name 'nav' is not defined
        File "web/app.py", line 362, in <module>
            view = resolve_main_view(nav, tracker, viewing_history)

    The fix is one-line: read the ``"nav"`` key (matching what every sidebar
    button writes via ``st.session_state["nav"] = plan.nav`` — see line 312).
    The same key is also read by the sidebar nav-button loop on line 303, so
    the binding is the canonical source of truth for "which page is active".

This single test exercises three layers of regression coverage so the bug
can never silently come back:

1. **Static AST check** — parse ``web/app.py``, locate the call to
   ``resolve_main_view(...)``, and confirm that a module-scope assignment
   to a target named ``nav`` precedes it. If the assignment target is ever
   renamed again, this assertion fires first.
2. **Source-line check** — confirm the offending binding line reads
   ``st.session_state.get("nav", ...)`` (not ``"view"``), so a regression
   surfaces with a clear message rather than via downstream symptoms.
3. **importlib reload** — actually execute the module-level code path
   under a fully-mocked ``streamlit`` so we hit the real ``NameError`` if
   the binding goes missing again. The mock covers every streamlit API
   the module touches at import time, so we reproduce the exact failure
   mode a real streamlit run would produce (the bind / dispatch block on
   lines 358-362) without spawning a streamlit server.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_streamlit_mock() -> MagicMock:
    """Build a MagicMock that quacks like the streamlit module surface used
    by ``web/app.py`` at import / module-execution time."""
    st_mock = MagicMock()
    # session_state must behave like a dict so .get() / []= work.
    st_mock.session_state = {}
    # Common API callables become MagicMocks; default return values are
    # fine because app.py only uses them for side effects (rendering).
    st_mock.set_page_config = MagicMock()
    st_mock.html = MagicMock()
    st_mock.markdown = MagicMock()
    st_mock.button = MagicMock(return_value=False)
    st_mock.error = MagicMock()
    st_mock.warning = MagicMock()
    st_mock.info = MagicMock()
    st_mock.success = MagicMock()
    st_mock.rerun = MagicMock()
    st_mock.fragment = lambda **_kw: (lambda f: f)
    st_mock.cache_data = lambda *_a, **_kw: (lambda f: f)
    st_mock.cache_resource = lambda *_a, **_kw: (lambda f: f)
    st_mock.columns = (
        lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
    )
    st_mock.tabs = lambda labels: [MagicMock() for _ in labels]
    st_mock.expander.return_value.__enter__ = lambda s: s
    st_mock.expander.return_value.__exit__ = lambda s, *_a: None
    st_mock.spinner.return_value.__enter__ = lambda s: s
    st_mock.spinner.return_value.__exit__ = lambda s, *_a: None
    st_mock.progress = MagicMock()
    st_mock.empty = MagicMock()
    st_mock.container = MagicMock()
    st_mock.stop = MagicMock()
    st_mock.sidebar = MagicMock()
    st_mock.subheader = MagicMock()
    st_mock.text_input = MagicMock(return_value="")
    st_mock.number_input = MagicMock(return_value=0)
    st_mock.selectbox = MagicMock(return_value="")
    st_mock.checkbox = MagicMock(return_value=False)
    st_mock.radio = MagicMock(return_value="")
    st_mock.slider = MagicMock(return_value=0)
    st_mock.text_area = MagicMock(return_value="")
    st_mock.form = MagicMock()
    st_mock.form_submit_button = MagicMock(return_value=False)
    st_mock.file_uploader = MagicMock()
    st_mock.date_input = MagicMock()
    st_mock.toast = MagicMock()
    st_mock.divider = MagicMock()
    st_mock.code = MagicMock()
    st_mock.json = MagicMock()
    st_mock.dataframe = MagicMock()
    st_mock.table = MagicMock()
    st_mock.metric = MagicMock()
    st_mock.line_chart = MagicMock()
    st_mock.bar_chart = MagicMock()
    st_mock.caption = MagicMock()
    st_mock.title = MagicMock()
    st_mock.header = MagicMock()
    st_mock.write = MagicMock()
    st_mock.image = MagicMock()
    st_mock.audio = MagicMock()
    st_mock.video = MagicMock()
    return st_mock


def _neutralise_web_dependencies() -> None:
    """Replace the render-side helpers web/app.py calls at module scope with
    MagicMocks so loading the module doesn't depend on real LLM / data
    vendor state."""
    targets = (
        "web.components.history_panel",
        "web.components.progress_panel",
        "web.components.report_viewer",
        "web.components.sector_panel",
        "web.components.settings_panel",
        "web.components.sidebar",
        "web.styles",
        "web.history",
        "web.runner",
        "web._signal_helpers",
    )
    for mod_name in targets:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr in dir(mod):
            if attr.startswith("_"):
                continue
            val = getattr(mod, attr)
            if callable(val) and not isinstance(val, type):
                setattr(mod, attr, MagicMock())


# ── The regression test ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_web_app_dispatch_resolves_nav_without_nameerror(monkeypatch) -> None:
    """``web/app.py`` must load and dispatch ``resolve_main_view`` without
    raising ``NameError``.

    Three layered assertions in one test (matching the original 312+1=313
    pytest budget):

    (a) Static AST — find ``resolve_main_view(...)`` and assert a prior
        module-scope assignment to ``nav`` exists.
    (b) Source line — the binding line must read from session_state key
        ``"nav"`` (not ``"view"``), matching the sidebar nav-button writes
        at ``web/app.py:312``.
    (c) Live reload — actually import ``web.app`` under a mocked streamlit
        and confirm no ``NameError`` is raised.
    """
    app_path = Path(__file__).resolve().parent.parent / "web" / "app.py"

    # ── (a) Static AST check ─────────────────────────────────────────────
    tree = ast.parse(app_path.read_text(encoding="utf-8"))

    assignments: list[tuple[int, str]] = []  # (lineno, target)
    for node in tree.body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for tgt in sub.targets:
                    if isinstance(tgt, ast.Name):
                        assignments.append((sub.lineno, tgt.id))
            elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                assignments.append((sub.lineno, sub.target.id))

    call_linenos = sorted({
        sub.lineno
        for node in tree.body
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Name)
        and sub.func.id == "resolve_main_view"
    })
    assert call_linenos, "resolve_main_view call site not found in web/app.py"

    for call_line in call_linenos:
        nav_assignments_before = [
            ln for ln, tgt in assignments if tgt == "nav" and ln < call_line
        ]
        assert nav_assignments_before, (
            f"web/app.py calls resolve_main_view(...) on line {call_line} "
            f"but never assigns a module-level variable named `nav` before "
            f"it. This is the regression that produced the 2026-07-04 "
            f"NameError."
        )

    # ── (b) Source-line check ────────────────────────────────────────────
    # Match an *annotated* binding to either ``nav`` (correct) or ``view``
    # (the historical bug target) that sits in the dispatch block. We
    # deliberately ignore other session_state lookups (viewing_history,
    # tracker, etc.) by requiring the LHS name to be exactly ``nav`` /
    # ``view`` AND the LHS to carry a type annotation.
    lines = app_path.read_text(encoding="utf-8").splitlines()
    binding_line = None
    for idx, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        # Pattern: ``<name>: <type> = st.session_state.get(...)``
        for candidate in ("nav", "view"):
            if stripped.startswith(f"{candidate}:") and "st.session_state.get" in line:
                binding_line = (idx, line)
                break
        if binding_line is not None:
            break
    assert binding_line is not None, (
        "Could not find the nav/view binding near resolve_main_view in web/app.py"
    )
    bind_idx, bind_text = binding_line
    assert '"nav"' in bind_text, (
        f"Line {bind_idx} of web/app.py must read "
        f'st.session_state.get("nav", ...). Got: {bind_text!r}'
    )

    # ── (c) Live reload ──────────────────────────────────────────────────
    monkeypatch.delitem(sys.modules, "web.app", raising=False)

    st_mock = _make_streamlit_mock()
    monkeypatch.setitem(sys.modules, "streamlit", st_mock)

    # Neutralise dotenv so the test doesn't touch the developer's real .env.
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *_a, **_kw: None)

    # Pre-load web.nav (no streamlit dependency) so the import order is stable.
    from web.nav import plan_nav_click, resolve_main_view  # noqa: F401

    _neutralise_web_dependencies()

    try:
        importlib.import_module("web.app")
    except NameError as exc:
        pytest.fail(
            f"web/app.py raised NameError during module-load: {exc}. "
            "Likely regression of the 2026-07-04 'nav is not defined' bug."
        )