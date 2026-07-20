"""Field-name adapter between new analyze report payload and old pdf_export.

P2.29 — the React ``/analyze`` report tab now exposes a download button
(📥 Markdown / 📄 PDF) backed by ``GET /api/analyze/{id}/export``. The
export handler delegates to ``web/pdf_export.generate_markdown`` and
``generate_pdf``, both of which were written for the legacy Streamlit
report shape:

  * ``trader_investment_decision`` (string) — what the trader node emits
  * ``investment_plan`` (string) — the PM's final recommendation
  * ``final_signal`` (string) — top-level BUY/SELL/HOLD

The new analyze pipeline persists slightly different field names:

  * ``trader_investment_plan`` (string) — same content, renamed
  * ``final_trade_decision`` (string OR dict) — same content, renamed,
    sometimes nested with ``{"signal": "BUY", ...}``
  * No top-level ``final_signal``; the signal lives inside
    ``final_trade_decision`` if the dict shape was used.

This module rewrites the new payload into the shape ``_collect_sections()``
(and ``generate_*``) expects, plus extracts the trading signal so it can
be passed as a separate argument.
"""

from __future__ import annotations

import re
from typing import Any, Tuple


# P2.31 — strip the LLM's chain-of-thought before it leaks to the report
# tab, the PDF export, and the Streamlit history view. The LangGraph
# deepseek/thinking models emit three variants we have to handle:
#
#   1. ``<think>...</think>``  — plain text, no angle brackets (the dominant
#                                variant in the real ``full_states_log_*.json``)
#   2. ``<THINK>...</THINK>``   — uppercase XML (what the user saw in the
#                                screenshot after ``rehype-sanitize`` escaped
#                                the `` variant as unknown inline HTML)
#   3. ``<think...>...</think>`` — properly-cased XML, with optional attrs
#
# The regex below matches all three with a single alternation, non-greedy
# so a payload with multiple think blocks only loses the blocks themselves.
# Unclosed ``<think>`` (LLM ran out of tokens) is tolerated via the
# ``?`` on the closing half — see tests/test_report_adapter_strip_think.py
# for the exact contract.
_STRIP_THINK_RE = re.compile(
    r"<think>[\s\S]*?</think>"            # plain-text variant
    r"|<think\b[^>]*>[\s\S]*?</think\s*>",  # XML variants (any case, attrs OK)
    re.IGNORECASE,
)


def strip_think_blocks(value: Any) -> Any:
    """Recursively drop ``<think>...</think>`` blocks from an analyze report.

    Walks dicts, lists, and tuples; passes scalars through unchanged. A
    non-string value that can't be recursed into (e.g. ``int``, ``bool``,
    ``None``) is returned as-is so the output dict stays schema-compatible
    with the original payload.

    The function is pure — the input is never mutated.
    """
    if isinstance(value, str):
        cleaned = _STRIP_THINK_RE.sub("", value).strip()
        return cleaned
    if isinstance(value, dict):
        return {k: strip_think_blocks(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_think_blocks(v) for v in value]
    if isinstance(value, tuple):
        return tuple(strip_think_blocks(v) for v in value)
    return value


def extract_signal(report: dict[str, Any] | None) -> str:
    """Pull the trading signal out of an analyze report payload.

    Mirrors the TS logic in ``frontend/src/components/analyze/analysis-report.tsx::extractSignal``
    so frontend and backend agree on where the signal lives.

    Priority:
      1. ``report.final_signal`` if it's a string (some old payloads have it)
      2. ``report.final_trade_decision.signal`` if dict shape with ``signal`` key
      3. ``report.final_trade_decision`` if it's a string itself
      4. ``""`` (caller decides what to do with empty signal)
    """
    if not report or not isinstance(report, dict):
        return ""

    direct = report.get("final_signal")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    decision = report.get("final_trade_decision")
    if isinstance(decision, dict):
        inner = decision.get("signal")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()
    elif isinstance(decision, str) and decision.strip():
        return decision.strip()

    return ""


def adapt_report_for_export(report: dict[str, Any] | None) -> Tuple[dict[str, Any], str]:
    """Rewrite a new-shape report dict into the legacy pdf_export shape.

    Returns ``(adapted, signal)`` where ``adapted`` is a shallow copy of
    ``report`` with the renamed keys (``trader_investment_decision``,
    ``investment_plan``) added, and ``signal`` is the trading signal
    suitable for passing as the ``signal=`` argument to ``generate_*``.

    The original keys are kept on the returned dict as well — pdf_export
    only reads the legacy keys so any extras are inert. Keeping the new
    keys around makes debugging easier (e.g. ``json.dumps(adapted, indent=2)``
    shows the full original payload).
    """
    if not isinstance(report, dict):
        return {}, ""

    adapted = dict(report)
    signal = extract_signal(report)

    # Map the new trader key into the legacy key pdf_export._collect_sections
    # reads (line ~338 in web/pdf_export.py).
    trader = report.get("trader_investment_plan")
    if trader and "trader_investment_decision" not in adapted:
        adapted["trader_investment_decision"] = str(trader)

    # Map the new final-decision key into ``investment_plan``. pdf_export
    # treats this as the PM's final recommendation (it sits between the
    # trader decision and the risk discussion in the section list).
    final_decision = report.get("final_trade_decision")
    if final_decision and "investment_plan" not in adapted:
        if isinstance(final_decision, dict):
            # dict shape — there's no clean string to render for the
            # "投资建议" section. Fall back to the signal so the section
            # has at least one line of content.
            adapted["investment_plan"] = signal or str(final_decision.get("decision", ""))
        else:
            adapted["investment_plan"] = str(final_decision)

    return adapted, signal
