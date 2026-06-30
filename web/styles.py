"""Single CSS injection point for the entire web app.

Reads web/styles/{tokens,base,components,elements}.css in order and injects
them as one <style> block. This is the only place in the codebase that uses
st.markdown(..., unsafe_allow_html=True). Business code should use st.html()
or semantic .bb-* class names.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

_STYLES_DIR = Path(__file__).parent / "styles"
_CSS_FILES = ("tokens.css", "base.css", "components.css", "elements.css")


def inject_css() -> None:
    """Read all CSS files and inject as a single <style> block."""
    parts = [
        (_STYLES_DIR / name).read_text(encoding="utf-8") for name in _CSS_FILES
    ]
    st.markdown(f"<style>{''.join(parts)}</style>", unsafe_allow_html=True)