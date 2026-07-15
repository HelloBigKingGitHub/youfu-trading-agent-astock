#!/usr/bin/env python3
"""Fault-injection parity probe for the settings page.

A deliberately malformed settings PUT is sent to FastAPI.  The two UI roots
are then fetched with ``requests`` and scanned for the short error-message
markers that are visible in their HTML responses.  This is intentionally a
best-effort probe: React and Streamlit may render an error only after a user
interaction, in which case the result records ``无可见错误文案`` instead of
inventing one.

Usage:
    python scripts/parity_fault_inject.py

Machine-readable summary (STDERR):
    fault_diff: ...
"""

from __future__ import annotations

import html
import re
import sys
from typing import Any

try:
    import requests
except ImportError as exc:  # pragma: no cover - environment diagnostic
    print(f"fault_diff: requests unavailable ({exc})", file=sys.stderr)
    raise SystemExit(1)


API_URL = "http://localhost:8000/api/settings"
REACT_URL = "http://localhost:5173/settings"
STREAMLIT_URL = "http://localhost:8501/settings"
TIMEOUT_SECONDS = 10

# Keep the regex intentionally small and UI-oriented.  The fallback marker is
# useful because the initial HTML of an SPA often contains no rendered error.
ERROR_MARKERS = re.compile(
    r"(?:保存失败|加载设置失败|请求失败|错误|Error|error|Invalid|invalid|"
    r"Validation|validation|Exception|exception|Traceback|traceback)",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

# provider=<script> is part of the requested injection.  deepModel is also an
# object, which violates the Pydantic string contract and makes the PUT fail
# deterministically without modifying any business code or persisted settings.
INVALID_PAYLOAD: dict[str, Any] = {
    "provider": "<script>alert(1)</script>",
    "deepModel": {"not": "a string"},
    "quickModel": "fault-injection",
    "baseUrl": "",
}


def _visible_error_text(document: str) -> str:
    """Extract a compact, de-duplicated error snippet from response HTML."""
    text = html.unescape(TAG_RE.sub(" ", document))
    text = WHITESPACE_RE.sub(" ", text).strip()
    matches = ERROR_MARKERS.finditer(text)
    snippets: list[str] = []
    for match in matches:
        start = max(0, match.start() - 45)
        end = min(len(text), match.end() + 95)
        snippet = text[start:end].strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= 3:
            break
    if not snippets:
        return "无可见错误文案"
    return " / ".join(snippets)


def _get_html(url: str) -> tuple[int | None, str, str | None]:
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": "parity-fault-inject/1"},
        )
        return response.status_code, response.text, None
    except requests.RequestException as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


def main() -> int:
    api_status: int | None = None
    api_detail = ""
    try:
        response = requests.put(
            API_URL,
            json=INVALID_PAYLOAD,
            timeout=TIMEOUT_SECONDS,
            headers={"User-Agent": "parity-fault-inject/1"},
        )
        api_status = response.status_code
        api_detail = response.text[:240].replace("\n", " ")
    except requests.RequestException as exc:
        api_detail = f"{type(exc).__name__}: {exc}"

    ui_results: dict[str, str] = {}
    ui_errors: list[str] = []
    for label, url in (("React", REACT_URL), ("Streamlit", STREAMLIT_URL)):
        status, document, error = _get_html(url)
        if error:
            ui_results[label] = f"不可达 ({error})"
            ui_errors.append(label)
        else:
            ui_results[label] = _visible_error_text(document)
            if status is None or status >= 500:
                ui_errors.append(label)

    if api_status is None:
        api_summary = f"API不可达: {api_detail}"
    else:
        api_summary = f"API HTTP {api_status}: {api_detail}"

    react_text = ui_results["React"]
    streamlit_text = ui_results["Streamlit"]
    if react_text == streamlit_text:
        difference = "文案一致"
    else:
        difference = f"React[{react_text}] != Streamlit[{streamlit_text}]"

    print(f"fault payload: {INVALID_PAYLOAD}")
    print(f"{api_summary}")
    print(f"React: {react_text}")
    print(f"Streamlit: {streamlit_text}")
    print(f"fault_diff: {difference}", file=sys.stderr)

    # UI reachability is useful evidence, but a non-2xx response is the
    # expected result of this fault injection and therefore is not a failure.
    # Fail only when a target cannot be contacted at all.
    return 1 if ui_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
