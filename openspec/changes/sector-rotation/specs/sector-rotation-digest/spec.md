# Sector Rotation Digest — Spec

## ADDED Requirements

### Requirement: Vendor routing for eastmoney hot strategy ranking

The system MUST provide a vendor function `get_hot_strategy_ranking(curr_date)` that retrieves top-N hot stock-picking strategies from `np-ipick.eastmoney.com/recommend/stock/heat/ranking`. The function MUST be registered in `tradingagents/dataflows/interface.py` under `VENDOR_METHODS` with key `get_hot_strategy_ranking` and a single `a_stock` vendor implementation.

The function MUST be invocable through the existing `route_to_vendor` mechanism (same pattern as `get_hot_stocks`, `get_concept_blocks`).

#### Scenario: Successful fetch with valid date
- **WHEN** `route_to_vendor("get_hot_strategy_ranking", "2026-06-17")` is called
- **THEN** the system returns a Markdown-formatted text containing each strategy's rank, heat value, change percentage, and the full question text of the picking condition
- **AND** the strategies MUST be sorted by `heatValue` descending

#### Scenario: Empty date defaults to today
- **WHEN** `route_to_vendor("get_hot_strategy_ranking", "")` or `route_to_vendor("get_hot_strategy_ranking")` is called with no/empty date
- **THEN** the system MUST treat the call as a "today" query and return the most recent data

#### Scenario: Eastmoney HTTP failure
- **WHEN** the upstream endpoint returns non-200 or invalid JSON
- **THEN** the function MUST return a string starting with `"Error fetching hot strategy ranking: "` containing the exception message
- **AND** MUST NOT raise an unhandled exception

#### Scenario: All requests must use the unified eastmoney throttler
- **WHEN** the function makes any HTTP request to `*.eastmoney.com`
- **THEN** it MUST route through `_em_get()` to honor the v0.2.11 anti-ban throttling policy

### Requirement: Sector rotation digest aggregation

The system MUST provide a vendor function `get_sector_rotation_digest(curr_date, top_n=20)` that produces a daily sector rotation Markdown digest by combining three data sources in a single pass:

1. `get_hot_strategy_ranking(curr_date)` — institutional/editor view of hot strategies
2. `get_hot_stocks(curr_date)` — same-day limit-up stocks with reason tags
3. Reverse-lookup of limit-up stocks' concept blocks via `get_concept_blocks(ticker)` — to aggregate "most limit-up-dense concept blocks"

The function MUST output a `SectorRotationDigest` dataclass (or equivalent structured form) with these fields:
- `hot_strategies: list[dict]` — top-N from np-ipick
- `hot_stocks: list[dict]` — top-N limit-up stocks
- `concept_blocks: dict[str, list[dict]]` — keyed by concept name, value is the list of limit-up stocks in that concept
- `markdown: str` — pre-rendered Markdown digest for direct consumption

The function MUST be registered in `interface.py` and exposed to LangGraph agents via `tradingagents/agents/utils/signal_data_tools.py` wrapper.

#### Scenario: Normal day with limit-up data
- **WHEN** `route_to_vendor("get_sector_rotation_digest", "2026-06-17")` is called on a trading day with at least 10 limit-up stocks
- **THEN** the returned `markdown` field MUST contain these sections in order:
  - "# 板块轮动日报 | <date>"
  - "## 一、机构/编辑视角 — 选股热度 Top N" (from np-ipick)
  - "## 二、强势概念板块 (按涨停密集度)" (from reverse-lookup aggregation)
  - "## 三、龙头候选池" (top stocks by concept block, deduped)
  - "## 四、个股涨停理由归因" (from THS reason tags)

#### Scenario: Limit-up reverse lookup is batched
- **WHEN** the function performs concept block reverse-lookup for N limit-up stocks
- **THEN** it MUST batch the requests (e.g. up to 10 codes per Baidu PAE call) to minimize HTTP round-trips
- **AND** it MUST throttle each batch with at least 0.5s sleep between requests (Baidu PAE has no documented limit but defensive throttling is required by v0.2.5+ policy)

#### Scenario: Partial data source failure is non-fatal
- **WHEN** any one of the three data sources fails (e.g. np-ipick 5xx, or Baidu PAE rate-limited)
- **THEN** the function MUST return a digest that includes the available sources and clearly marks the failed source as `[数据缺失: <source_name>]` in the markdown output
- **AND** the function MUST NOT raise an exception

#### Scenario: Trading day with no limit-up stocks
- **WHEN** `get_hot_stocks` returns 0 limit-up stocks for the given date (e.g. market closed, holiday, or pre-market)
- **THEN** the function MUST still return a digest with the strategy ranking section and an explicit note "## 二、强势概念板块: 当日无涨停股,跳过涨停归因"

### Requirement: Test coverage and integration tests

The system MUST provide a unit test file `tests/dataflows/test_sector_rotation.py` with at least these test cases:

1. `test_hot_strategy_ranking_parses_top_n` — verify the function returns sorted-by-heatValue Markdown when given a mocked successful response
2. `test_hot_strategy_ranking_handles_empty_date` — verify today-default behavior
3. `test_hot_strategy_ranking_handles_5xx` — verify graceful failure on HTTP error
4. `test_sector_rotation_digest_aggregates_three_sources` — verify all 4 sections of the Markdown are present and the dataclass fields are populated
5. `test_sector_rotation_digest_batches_pae_requests` — verify N stocks ≤ 10 trigger 1 PAE call, N=20 trigger 2 PAE calls
6. `test_sector_rotation_digest_handles_missing_limit_up` — verify graceful handling of zero limit-up stocks
7. `test_sector_rotation_digest_handles_partial_failure` — verify a single source failing does not abort the whole digest

The test file MUST use `pytest` with `pytest-mock` (or equivalent) to mock HTTP calls — no real network calls in unit tests. Integration tests using real endpoints belong in `tests/integration/`.

The system MUST achieve ≥ 80% line coverage for the new code in `tradingagents/dataflows/a_stock.py` (functions `get_hot_strategy_ranking` and `get_sector_rotation_digest` only).

#### Scenario: Coverage threshold met
- **WHEN** `pytest --cov=tradingagents.dataflows.a_stock --cov-fail-under=80` runs against `tests/dataflows/test_sector_rotation.py`
- **THEN** the coverage report MUST show ≥ 80% line coverage for lines added by this change
- **AND** the pytest run MUST exit with status code 0

#### Scenario: Unit tests are isolated from network
- **WHEN** `pytest tests/dataflows/test_sector_rotation.py` runs in an offline environment
- **THEN** all unit tests MUST pass without making any real HTTP requests
- **AND** the test file MUST NOT be skipped or marked as `xfail` due to network unavailability
