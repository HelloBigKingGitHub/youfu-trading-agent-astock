# Sector Rotation Analyst Integration — Spec

## ADDED Requirements

### Requirement: hot_money_tracker analyst tool set extension

The `hot_money_tracker` Analyst MUST include `get_sector_rotation_digest` in its tool list (in `tradingagents/agents/analysts/hot_money_tracker.py`). The system prompt MUST be updated to instruct the LLM to call `get_sector_rotation_digest(curr_date)` **first** (before any individual stock lookups) to establish a "sector rotation baseline" before drilling into specific stocks.

The tool description (in `signal_data_tools.py` wrapper) MUST explicitly state: "Limit calls to 1 per session — the digest covers all sectors at once, repeated calls waste tokens and add latency."

#### Scenario: Analyst prompt includes new tool
- **WHEN** the LLM is bound with the updated tool list
- **THEN** `get_sector_rotation_digest` MUST be one of the available tool names
- **AND** the system prompt MUST contain a directive instructing the LLM to call this tool first

#### Scenario: LLM overuses the digest tool
- **WHEN** the LLM attempts to call `get_sector_rotation_digest` more than once in the same session
- **THEN** the system SHOULD rely on the LLM's own judgment to follow the "1 call per session" guideline (the system prompt enforces this; the wrapper does not hard-block repeated calls in v0.1)
- **AND** this is documented as a v0.2 candidate (hard block via LangGraph state inspection)

### Requirement: Web UI entry point for digest

The web UI (`web/app.py`) MUST provide a user-facing entry point for the sector rotation digest that does NOT require running the full LangGraph pipeline. The entry point MUST be a button labeled "板块轮动日报" (or equivalent) in the main page, that on click:

1. Invokes `get_sector_rotation_digest` synchronously
2. Renders the returned `markdown` field via Streamlit's `st.markdown()`
3. Shows a progress indicator while waiting (Streamlit spinner) — the digest takes 15-25s in normal conditions

The entry point MUST NOT require any LLM call (pure data → Markdown, no AI cost).

#### Scenario: User clicks digest button on a trading day
- **WHEN** user is on the main page and clicks "板块轮动日报"
- **THEN** the system shows a spinner with text "正在拉取板块轮动数据,预计 15-25 秒..."
- **AND** upon completion renders the full digest Markdown in the main area
- **AND** does NOT call any LLM (no token cost)

#### Scenario: User clicks digest button on a non-trading day
- **WHEN** user clicks "板块轮动日报" and the date is a holiday/weekend
- **THEN** the system still returns a digest with the available data
- **AND** the digest Markdown explicitly notes "## 二、强势概念板块: 当日无涨停股,跳过涨停归因" or equivalent
- **AND** no error is raised to the user

#### Scenario: User clicks digest button while another agent run is in progress
- **WHEN** user clicks "板块轮动日报" while a LangGraph run is in progress
- **THEN** the system MUST handle concurrent access gracefully (Streamlit session state, no race conditions)
- **AND** the digest call MUST NOT block or interfere with the in-progress LangGraph run
