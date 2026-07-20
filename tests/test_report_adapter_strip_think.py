"""P2.31 — tests for ``report_adapter.strip_think_blocks``.

The LLM's chain-of-thought reaches the report as ``<think>...</think>``,
``<THINK>...</THINK>``, or ``<think>...</think>`` (LangGraph deepseek/
thinking models emit plain-text `` with no angle brackets). All three
leak to the report tab and to the PDF export unless we strip them at
the adapter boundary so Streamlit + React + the PDF exporter all see
the cleaned payload.

The function is recursive over dicts and lists so the entire report
tree — including nested ``investment_debate_state`` / ``risk_debate_state``
debate history fields — gets sanitized in one pass.
"""

from __future__ import annotations

from backend.core.report_adapter import (
    adapt_report_for_export,
    extract_signal,
    strip_think_blocks,
)


# ── 1) each of the 3 think-tag variants ──────────────────────────────────
def test_strips_lowercase_xml_think_block():
    src = "<think>secret reasoning</think>\n# Heading\n\nreal report"
    assert strip_think_blocks(src) == "# Heading\n\nreal report"


def test_strips_uppercase_think_block():
    # P2.30 screenshot evidence: ``rehype-sanitize`` escapes unknown inline
    # HTML so the user actually sees ``<THINK>...</THINK>`` rendered.
    src = "<THINK>THE USER IS ASKING ME TO WRITE...</THINK>\n## 结论"
    assert strip_think_blocks(src) == "## 结论"


def test_strips_no_angle_bracket_think_block():
    # The real data shape — LangGraph thinking models emit ``
    # without angle brackets. This is the variant the prior
    # ``STRIP_THINK`` regex missed and which caused the report tab to
    # show a giant yellow block.
    src = "<think>\n现在我有了所有需要的数据...让我计算关键数据：\n</think>\n# 报告"
    assert strip_think_blocks(src) == "# 报告"


def test_strips_multiple_think_blocks_in_same_string():
    src = "<think>first</think>A<think>second</think>B<think>third</think>C"
    assert strip_think_blocks(src) == "ABC"


# ── 2) variants and edge cases ────────────────────────────────────────────
def test_strips_think_with_attributes():
    src = '<think lang="en">x</think>keep'
    assert strip_think_blocks(src) == "keep"


def test_strips_think_with_surrounding_whitespace():
    src = "<think>reasoning</think>\n\n\n# Real\n\ncontent"
    assert strip_think_blocks(src) == "# Real\n\ncontent"


def test_preserves_think_like_text_inside_legitimate_content():
    # Only the chain-of-thought block is stripped; ordinary occurrences of
    # the word "think" mid-sentence must survive.
    src = "I think this stock is undervalued. Let me explain why..."
    assert strip_think_blocks(src) == src


def test_returns_input_unchanged_when_no_think_block():
    src = "# 标题\n\n正文内容没有任何 think 块。"
    assert strip_think_blocks(src) == src


def test_empty_string_returns_empty_string():
    assert strip_think_blocks("") == ""


def test_handles_unclosed_think_gracefully():
    # An unclosed ``<think>`` (LLM ran out of tokens) must NOT eat the
    # entire report. Strip what we can and keep the rest.
    src = "<think>truncated reasoning with no closing tag\n# Heading\n\ncontent"
    out = strip_think_blocks(src)
    # The trailing report content must be preserved.
    assert "# Heading" in out
    assert "content" in out


# ── 3) recursive walk over dicts / lists ──────────────────────────────────
def test_strips_inside_nested_dict():
    report = {
        "market_report": "<think>secret</think># Market\n\nAnalysis",
        "investment_debate_state": {
            "bull_history": "<think>bull reasoning</think>\n# Bull case",
            "judge_decision": "<THINK>PM reasoning</THINK>最终决定",
        },
    }
    out = strip_think_blocks(report)
    assert out["market_report"] == "# Market\n\nAnalysis"
    # Leading ``\n`` after the stripped think block is normalized away so the
    # markdown renderer doesn't open with a blank line.
    assert out["investment_debate_state"]["bull_history"] == "# Bull case"
    assert out["investment_debate_state"]["judge_decision"] == "最终决定"


def test_strips_inside_list_of_strings():
    report = {"history": ["<think>turn 1</think>A", "<think>turn 2</think>B", "C"]}
    out = strip_think_blocks(report)
    assert out["history"] == ["A", "B", "C"]


def test_does_not_mutate_input():
    report = {"market_report": "<think>x</think># Real"}
    snapshot = {"market_report": "<think>x</think># Real"}
    strip_think_blocks(report)
    assert report == snapshot


def test_non_string_scalar_values_preserved():
    report = {
        "trade_date": "2026-07-19",
        "completed": True,
        "score": 0.85,
        "items": None,
    }
    out = strip_think_blocks(report)
    assert out == report


# ── 4) integration: API-layer composition (strip → extract_signal) ────────
def test_api_layer_composition_strip_then_extract_signal():
    # The real production flow: analyze.py / history.py run
    # ``strip_think_blocks(report)`` BEFORE handing the payload to anything
    # else. ``extract_signal`` does NOT strip on its own; the contract is
    # that the API layer has already cleaned the payload. Both helpers are
    # composable: the strip is recursive over dicts / lists, and the signal
    # is pulled from the (now-clean) dict's ``final_trade_decision.signal``.
    raw = {
        "final_trade_decision": {
            "signal": "HOLD",
            "reasoning": "<think>long reasoning chain</think>\n# 投资决策\n\n综合判断...",
        }
    }
    cleaned = strip_think_blocks(raw)
    # extract_signal reads the dict's signal key directly — no parsing.
    assert extract_signal(cleaned) == "HOLD"
    # The think text inside the dict's reasoning field is gone after strip.
    assert "<think>" not in cleaned["final_trade_decision"]["reasoning"]


def test_adapt_report_for_export_is_dumb_about_think():
    # ``adapt_report_for_export`` is the key-rename helper; the strip step
    # belongs to the API layer (analyze.py / history.py). This test pins
    # the layering so a future refactor that pushes stripping into the
    # adapter has to consciously decide where it goes.
    raw = {
        "trader_investment_plan": "<think>reasoning</think># Trader\n\nBuy partial",
        "final_trade_decision": {"signal": "SELL", "decision": "Exit now"},
    }
    adapted, signal = adapt_report_for_export(raw)
    # adapt does not strip — that's the caller's job.
    assert "<think>" in adapted["trader_investment_plan"]
    # …but the dict-shaped final decision cleanly surfaces its signal.
    assert signal == "SELL"
    # …and the legacy ``investment_plan`` key was added. The implementation
    # prefers the signal over the decision string when both exist (a SELL
    # signal is more informative for the PDF section header than a free-form
    # "decision" string).
    assert adapted["investment_plan"] == "SELL"
