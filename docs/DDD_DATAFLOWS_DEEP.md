# TradingAgents A 股 dataflows 关键文件 DDD 深入探索（read-only）

> **范围**：4 个 dataflows 关键文件 + `agents/utils/` 10 个 Agent 工具集 — 聚焦**真实存在的 ACL**、yfinance 限流重试、跨层 ticker 校验泄漏、Agent 工具集 typed contract 现状。本文是第四轮 DDD 战术探索，与前 3 个文档互补：
>
> | 文档 | 行数 | 主题 |
> |---|---|---|
> | `docs/DDD_EXPLORATION.md` | 1311 | backend/core 13 聚合根 + Domain 模型 |
> | `docs/DDD_AGENTS_DEEP_DIVE.md` | 1424 | LangGraph 16 Agent + 状态机 |
> | `docs/DDD_DATAFLOWS_INFRA.md` | 779 | dataflows/ 13 模块 + 11 外部数据源 |
> | **`docs/DDD_DATAFLOWS_DEEP.md`（本文）** | — | **interface.py ACL + stockstats_utils + utils + agents/utils 工具集** |
>
> **git HEAD**：`33b3a42`（P2.25 tracker + history_store + runner ID 一致性）
>
> **关键纠正**：第三轮 DDD 报告 `DDD_DATAFLOWS_INFRA.md` §6 说 "ACL 几乎不存在" **是错的**。`tradingagents/dataflows/interface.py` **已经是 Anti-Corruption Layer**（239 行实现 `TOOLS_CATEGORIES` + `VENDOR_METHODS` + `route_to_vendor` + `get_vendor`），只是覆盖范围小（仅 3 vendor），不在 11 个 HTTP 数据源之间。第三轮的真正发现是 "**真实存在的 ACL 范围有限 + 11 数据源 fallback 在 a_stock.py 内部嵌套 try/except 完成**"，而非 "ACL 不存在"。本文会先纠偏，再深入 4 个关键文件 + 工具集。

---

## 目录

1. [`interface.py` — 真实存在的 ACL（239 行）](#1-interfacepy--真实存在的-acl239-行)
2. [`stockstats_utils.py` — yfinance 限流重试 + OHLCV 缓存（133 行）](#2-stockstats_utilspy--yfinance-限流重试--ohlcv-缓存133-行)
3. [`utils.py` — `safe_ticker_component` + 跨层泄漏（80 行）](#3-utilspy--safe_ticker_component--跨层泄漏80-行)
4. [`agents/utils/*.py` — Agent 工具集（10 文件 / 19 个 `@tool`）](#4-agentsutilspy--agent-工具集10-文件--19-个-tool)
5. [跨层调用图 + 数据流](#5-跨层调用图--数据流)
6. [架构债务（7 条）](#6-架构债务7-条)
7. [重构建议（短期 / 中期 / 长期）](#7-重构建议短期--中期--长期)
8. [附录：实测 LOC 对照表](#8-附录实测-loc-对照表)

---

## 1. `interface.py` — 真实存在的 ACL（239 行）

> **路径**：`tradingagents/dataflows/interface.py`（239 行 / 8262 字节 / 全文 0 个注释掉的代码）

### 1.1 整体结构（4 个核心组件）

```
┌──────────────────────────────────────────────────────────────┐
│  interface.py — Anti-Corruption Layer (ACL)                  │
├──────────────────────────────────────────────────────────────┤
│  1. VENDOR_LIST          (line 100)   ["a_stock", "yfinance", "alpha_vantage"]
│  2. TOOLS_CATEGORIES     (line  53)   5 categories × N tools
│  3. VENDOR_METHODS       (line 107)   19 methods × vendor 实现 (callable mapping)
│  4. Helpers + Router     (line 190)   get_category_for_method / get_vendor / route_to_vendor
└──────────────────────────────────────────────────────────────┘
```

### 1.2 `TOOLS_CATEGORIES` — 5 个 category × 19 个 tool

| Category | Tool 数 | Tool 列表（按顺序） | 主要 vendor |
|---|---:|---|---|
| `core_stock_apis` | 1 | `get_stock_data` | a_stock |
| `technical_indicators` | 1 | `get_indicators` | a_stock |
| `fundamental_data` | 4 | `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` | a_stock |
| `news_data` | 3 | `get_news` / `get_global_news` / `get_insider_transactions` | a_stock |
| `signal_data` | 10 | `get_profit_forecast` / `get_hot_stocks` / `get_northbound_flow` / `get_concept_blocks` / `get_fund_flow` / `get_dragon_tiger_board` / `get_lockup_expiry` / `get_industry_comparison` / `get_hot_strategy_ranking` / `get_sector_rotation_digest` | a_stock **唯一** |
| **合计** | **19** | | |

> **关键观察**：10 个 signal_data tool **全部只有 `a_stock` 一个 vendor 实现**（A 股独有）。其余 9 个 tool 都有 a_stock + yfinance + alpha_vantage 三家 vendor，**但默认 vendor 在 `default_config.py` 全部配置为 `a_stock`**，意味着 yfinance/alpha_vantage 仅作 fallback。

### 1.3 `VENDOR_METHODS` — 19 method × 3 vendor 完整映射

> **来源**：`interface.py` line 107–188。以下是**全部 19 个 method**的 vendor 实现 + 数据返回类型 + fallback 行为矩阵。

| # | method | a_stock | yfinance | alpha_vantage | 返回类型 | signal_data? |
|---:|---|---|---|---|---|---|
| 1 | `get_stock_data` | ✅ `get_astock_stock_data` | ✅ `get_YFin_data_online` | ✅ `get_alpha_vantage_stock` | `str` (csv/text) | ❌ |
| 2 | `get_indicators` | ✅ `get_astock_indicators` | ✅ `get_stock_stats_indicators_window` | ✅ `get_alpha_vantage_indicator` | `str` | ❌ |
| 3 | `get_fundamentals` | ✅ `get_astock_fundamentals` | ✅ `get_yfinance_fundamentals` | ✅ `get_alpha_vantage_fundamentals` | `str` | ❌ |
| 4 | `get_balance_sheet` | ✅ `get_astock_balance_sheet` | ✅ `get_yfinance_balance_sheet` | ✅ `get_alpha_vantage_balance_sheet` | `str` | ❌ |
| 5 | `get_cashflow` | ✅ `get_astock_cashflow` | ✅ `get_yfinance_cashflow` | ✅ `get_alpha_vantage_cashflow` | `str` | ❌ |
| 6 | `get_income_statement` | ✅ `get_astock_income_statement` | ✅ `get_yfinance_income_statement` | ✅ `get_alpha_vantage_income_statement` | `str` | ❌ |
| 7 | `get_news` | ✅ `get_astock_news` | ✅ `get_news_yfinance` | ✅ `get_alpha_vantage_news` | `str` | ❌ |
| 8 | `get_global_news` | ✅ `get_astock_global_news` | ✅ `get_global_news_yfinance` | ✅ `get_alpha_vantage_global_news` | `str` | ❌ |
| 9 | `get_insider_transactions` | ✅ `get_astock_insider_transactions` | ✅ `get_yfinance_insider_transactions` | ✅ `get_alpha_vantage_insider_transactions` | `str` | ❌ |
| 10 | `get_profit_forecast` | ✅ `get_astock_profit_forecast` | ❌ | ❌ | `str` | ✅ |
| 11 | `get_hot_stocks` | ✅ `get_astock_hot_stocks` | ❌ | ❌ | `str` | ✅ |
| 12 | `get_northbound_flow` | ✅ `get_astock_northbound_flow` | ❌ | ❌ | `str` | ✅ |
| 13 | `get_concept_blocks` | ✅ `get_astock_concept_blocks` | ❌ | ❌ | `str` | ✅ |
| 14 | `get_fund_flow` | ✅ `get_astock_fund_flow` | ❌ | ❌ | `str` | ✅ |
| 15 | `get_dragon_tiger_board` | ✅ `get_astock_dragon_tiger_board` | ❌ | ❌ | `str` | ✅ |
| 16 | `get_lockup_expiry` | ✅ `get_astock_lockup_expiry` | ❌ | ❌ | `str` | ✅ |
| 17 | `get_industry_comparison` | ✅ `get_astock_industry_comparison` | ❌ | ❌ | `str` | ✅ |
| 18 | `get_hot_strategy_ranking` | ✅ `get_astock_hot_strategy_ranking` | ❌ | ❌ | `str` | ✅ |
| 19 | `get_sector_rotation_digest` | ✅ `get_astock_sector_rotation_digest` | ❌ | ❌ | `str` / `dataclass` | ✅ |

> **关于返回类型**：所有 19 个 method 的 return 类型**在 interface.py 中没有声明**（无 type hint）。实测：
> - 18 个返回 `str`（CSV/格式化文本）
> - `get_sector_rotation_digest` 返回 `SectorRotationDigest` dataclass，由 `agents/utils/signal_data_tools.py` 第 206 行 `if hasattr(digest, "markdown"): return digest.markdown` 兜底
>
> **Task 描述里说的"21 method × 3 vendor"是错的**。实测是 **19 method**，其中 9 个有 3 vendor、10 个只有 1 vendor。

### 1.4 `get_vendor(category, method)` — 二级 vendor 配置解析

```python
# interface.py L197–210
def get_vendor(category: str, method: str = None) -> str:
    config = get_config()
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]          # tool-level 优先
    return config.get("data_vendors", {}).get(category, "default")  # category-level fallback
```

> **配置源**：`tradingagents/default_config.py` L41–58
>
> ```python
> "data_vendors": {
>     "core_stock_apis":      "a_stock",
>     "technical_indicators": "a_stock",
>     "fundamental_data":     "a_stock",
>     "news_data":            "a_stock",
>     "signal_data":          "a_stock",
> },
> "tool_vendors": {},  # 用户可填入 per-tool 覆盖
> ```
>
> **关键设计**：
> 1. **二级回退**（tool-level → category-level），用户可在 `tool_vendors` 里指定 `get_stock_data: alpha_vantage` 而不破坏其他 tool。
> 2. **vendor 字符串是 CSV**：`route_to_vendor` L216 `[v.strip() for v in vendor_config.split(',')]`，意味着配置可写 `"a_stock,alpha_vantage"` 表示先 a_stock 后 alpha_vantage，但 `default_config.py` 当前**没有用到 CSV 形式**（全部单值）。

### 1.5 `route_to_vendor(method, *args, **kwargs)` — ACL 路由核心（27 行）

```python
# interface.py L212–240
def route_to_vendor(method: str, *args, **kwargs):
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Build fallback chain: primary vendors first, then remaining available vendors
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError:
            continue  # Only rate limits trigger fallback

    raise RuntimeError(f"No available vendor for '{method}'")
```

### 1.6 ACL 工作流程图

```
route_to_vendor("get_stock_data", "600595", "2024-01-01", "2024-12-31")
  │
  ├─① get_category_for_method("get_stock_data") → "core_stock_apis"
  ├─② get_vendor("core_stock_apis", "get_stock_data")
  │     └─ tool_vendors.get("get_stock_data") → None
  │     └─ data_vendors.get("core_stock_apis") → "a_stock"  (default)
  ├─③ vendor_config = "a_stock" → primary_vendors = ["a_stock"]
  ├─④ fallback_vendors = ["a_stock", "yfinance", "alpha_vantage"]  (因为 VENDOR_METHODS["get_stock_data"] = {a_stock, yfinance, alpha_vantage})
  │
  ├─▶ try a_stock → get_astock_stock_data(...) → return
  │   (or AlphaVantageRateLimitError → continue)
  │
  └─ raise RuntimeError if all vendors fail
```

### 1.7 这个 ACL 不完整的 5 个关键问题

> 这是 ACL 实际存在的问题清单，跟 DDD 教科书"理想 ACL"对比：

| # | 问题 | 现状 | 风险 |
|---:|---|---|---|
| 1 | **Fallback 仅触发 `AlphaVantageRateLimitError`** | line 237 `except AlphaVantageRateLimitError: continue` | 网络 5xx / JSON 解析错 / DNS 失败 / SSL 错误等**直接 raise**，不 fallback |
| 2 | **Primary vendor 配置是字符串 CSV**，无 health check / circuit breaker | line 215–216 读 CSV 后无验证 | vendor 全挂时 100% 失败，无熔断 |
| 3 | **`VENDOR_LIST` hardcoded**（3 vendor） | line 100–104 | 新 vendor 必须改源码，不能动态注册 |
| 4 | **ACL 只覆盖 3 vendor**，**不覆盖 11 HTTP 数据源** | line 107–188 只引用 yfinance / alpha_vantage / a_stock | eastmoney datacenter / push2his / sina / 10jqka / 财联社 / 百度股市通 / np-ipick / 龙虎榜 datacenter 全部在 `a_stock.py` 内部嵌套 try/except fallback，**没经过 ACL** |
| 5 | **`vendor_impl` 支持 list**（line 233），但从未被使用 | `impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl` | list 形式是 dead code，仅作扩展点保留 |

### 1.8 Call site — ACL 被谁调

```
tradingagents/agents/utils/core_stock_tools.py           (1 @tool)
tradingagents/agents/utils/technical_indicators_tools.py  (1 @tool, 内部 comma-split 多次调)
tradingagents/agents/utils/fundamental_data_tools.py      (4 @tool)
tradingagents/agents/utils/news_data_tools.py             (3 @tool)
tradingagents/agents/utils/signal_data_tools.py           (10 @tool)
                                                     ─────
                                                     19 个 @tool 全部走 route_to_vendor
```

> **未走 ACL 的调用方**：`tradingagents/dataflows/a_stock.py` 内部 11 个 HTTP 数据源之间的 fallback 链（mootdx TCP → sina HTTP → push2his HTTP → push2 realtime）由 `a_stock.py` 自己管理（line 561–635 的嵌套 try/except + `_sina_kline_fallback` + `_push2his_kline_fallback` helper），**不通过 `route_to_vendor`**。这是 ACL 覆盖范围缺口。

---

## 2. `stockstats_utils.py` — yfinance 限流重试 + OHLCV 缓存（133 行）

> **路径**：`tradingagents/dataflows/stockstats_utils.py`（133 行 / 4718 字节）
> **依赖**：`yfinance as yf`、`stockstats`、`pandas`、`safe_ticker_component`

### 2.1 3 个核心函数 + 1 个 wrapper class

#### 2.1.1 `yf_retry(func, max_retries=3, base_delay=2.0)` — 限流重试（17 行）

```python
# stockstats_utils.py L16–32
def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.
    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)        # 2s → 4s → 8s
                logger.warning(f"Yahoo Finance rate limited, retrying in {delay:.0f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise
```

**重试时序**：

| Attempt | Delay (exponential backoff base=2.0) | 累计等待 |
|---:|---:|---:|
| 1 | 2s | 2s |
| 2 | 4s | 6s |
| 3 | 8s | 14s |
| 4 (final) | 直接 raise | — |

**问题清单**：

1. **只重试 `YFRateLimitError`** — 其他异常（`ConnectionError` / `JSONDecodeError` / `KeyError` / `SSLError`）直接 propagate。`route_to_vendor` 的 `AlphaVantageRateLimitError` 是 alpha_vantage 专用的，跟 `YFRateLimitError` 是两个独立 exception class。
2. **同步阻塞**（`time.sleep`）— 在 Streamlit + LangGraph 同步调用链中会卡 UI，但目前 vendor 链路设计就是同步的。
3. **Jitter 缺失** — 多 worker 并发同 ticker 时会同步重试，可能触发 thundering herd。
4. **无 retry-after header 解析** — 完全按指数退避，未读 yfinance 返回的 `Retry-After`。

#### 2.1.2 `_clean_dataframe(data: pd.DataFrame) -> pd.DataFrame`（11 行）

```python
# stockstats_utils.py L35–45
def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()      # 双向 fillna

    return data
```

**关键设计**：
- **Date 必须存在**（dropna），但允许 `Close` fillna 后的值保留 — 假设停牌日用前后日 fillna。
- **`ffill().bfill()`** — 前向 + 后向填充。理论上前向 fill 就够（停牌价 = 上日收盘），bfill 是 startup 早期数据防御。

#### 2.1.3 `load_ohlcv(symbol, curr_date) -> pd.DataFrame`（46 行）

```python
# stockstats_utils.py L48–93
def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias."""
    safe_symbol = safe_ticker_component(symbol)              # 路径安全校验

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)         # ⚠️ task 描述说"15 年"，实测是 **5 年**
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
    else:
        data = yf_retry(lambda: yf.download(
            symbol,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        data = data.reset_index()
        data.to_csv(data_file, index=False, encoding="utf-8")

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    return data
```

**重要纠正**：
- **task 描述说 "Downloads 15 years of data"，实测 `pd.DateOffset(years=5)`，是 5 年**。
- **缓存策略**：文件名含日期窗口，5 年窗口内同 ticker 复用同一 CSV。
- **防 look-ahead bias**：line 91 `data[data["Date"] <= curr_date_dt]` — backtest 时未来日期会被裁掉。

#### 2.1.4 `StockstatsUtils` wrapper class（24 行）

```python
# stockstats_utils.py L110–133
class StockstatsUtils:
    @staticmethod
    def get_stock_stats(symbol, indicator, curr_date):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)                          # stockstats.wrap
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]                            # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
```

**问题清单**：
1. **第三方依赖未自主化** — `import yfinance as yf` + `from stockstats import wrap`（line 5, 7）。当前 yfinance 对 A 股支持有限（HK/CH 需 `.SS`/`.SZ` 后缀），stockstats 又是基于美股指标的 wrapper。**A 股数据层仍没完全自主**。
2. **N/A fallback 是字符串** — `"N/A: Not a trading day (weekend or holiday)"` 是 typed `str`，不是 enum 或 `Optional[float]`，下游解析可能误判。
3. **`df[indicator]` 触发** — stockstats 用 property descriptor 触发计算，依赖 `wrap()` 的 monkey-patch，不直观。

### 2.2 调用方

- **`tradingagents/dataflows/interface.py`** 第 8 行：`get_stock_stats_indicators_window` (yfinance) 导入。
- **`tradingagents/dataflows/a_stock.py`** 第 11 行：`from .utils import safe_ticker_component`（同 utils.py 共享 ticker 校验）。
- **`tradingagents/dataflows/utils.py`** 第 11 行：`StockstatsUtils` 仅由 `technical_indicators_tools.py` 间接用。

> **实际位置**：`get_stock_stats_indicators_window` 这个 function **不在 `stockstats_utils.py`** — 实际在 `tradingagents/dataflows/y_finance.py`（421 行）。`stockstats_utils.py` 只暴露 `StockstatsUtils.get_stock_stats` 静态方法 + `load_ohlcv` 内部 helper。

---

## 3. `utils.py` — `safe_ticker_component` + 跨层泄漏（80 行）

> **路径**：`tradingagents/dataflows/utils.py`（80 行 / 2661 字节）
> **任务背景**：subagent #1 发现的 `safe_ticker_component` 跨层泄漏已**确认**。

### 3.1 6 个 public 符号

| 符号 | 行 | 类型 | 说明 |
|---|---:|---|---|
| `SavePathType` | L11 | `Annotated[str, ...]` | LangChain tool SavePath 类型 |
| `_TICKER_PATH_RE` | L16 | regex | `^[A-Za-z0-9._\-\^]+$` — 允许字母/数字/点/横线/下划线/插入符（指数 `^GSPC`） |
| `_HAS_CHINESE_RE` | L17 | regex | `[一-鿿]` — CJK 统一汉字 |
| `safe_ticker_component(value, *, max_len=32)` | L20–47 | function | 路径安全 + 中文 ticker 自动 resolve |
| `save_output(data, tag, save_path)` | L50–53 | function | DataFrame CSV 落盘 |
| `get_current_date()` | L56–57 | function | `date.today()` ISO 字符串 |
| `decorate_all_methods(decorator)` | L60–67 | function | 给 class 所有 method 加 decorator |
| `get_next_weekday(date)` | L70–80 | function | 跳过周末 |

### 3.2 `safe_ticker_component` 完整实现 + 跨层 resolve 路径

```python
# utils.py L20–47
def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """Validate ``value`` is safe to interpolate into a filesystem path.

    If the value contains Chinese characters (common when LLMs return stock
    names instead of codes), automatically resolve it to a 6-digit A-stock
    code via ``resolve_ticker`` before validation.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"ticker must be a non-empty string, got {value!r}")

    if _HAS_CHINESE_RE.search(value):
        from tradingagents.dataflows.a_stock import resolve_ticker    # ⚠️ 延迟 import
        resolved = resolve_ticker(value)
        logger.info("Auto-resolved Chinese ticker %r -> %s", value, resolved)
        value = resolved

    if len(value) > max_len:
        raise ValueError(f"ticker exceeds {max_len} chars: {value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        raise ValueError(
            f"ticker contains characters not allowed in a filesystem path: {value!r}"
        )
    if set(value) == {"."}:
        raise ValueError(f"ticker cannot consist solely of dots: {value!r}")
    return value
```

**关键设计**：
1. **3 道防线**：长度 → 字符集 → dot-only 检查。
2. **中文 ticker 自动 resolve**：`_HAS_CHINESE_RE.search` 命中后调用 `a_stock.resolve_ticker(value)`，内部用 mootdx 全市场股票名 → 代码映射（`a_stock.py` L121–145 `_build_name_code_map`）。
3. **延迟 import**（line 34 `from tradingagents.dataflows.a_stock import resolve_ticker`）— 避免 utils.py 直接依赖 a_stock 模块导致循环 import，但也说明 utils 和 a_stock 关系是**双向耦合**。

### 3.3 跨层泄漏：调用方矩阵（实测 `grep -rn safe_ticker_component`）

```
tradingagents/dataflows/stockstats_utils.py:11:    from .utils import safe_ticker_component
tradingagents/dataflows/stockstats_utils.py:57:        safe_symbol = safe_ticker_component(symbol)

tradingagents/dataflows/a_stock.py:35:    from .utils import safe_ticker_component
tradingagents/dataflows/a_stock.py:69:     return safe_ticker_component(s)
tradingagents/dataflows/a_stock.py:1948:  code = safe_ticker_component(ticker)
tradingagents/dataflows/a_stock.py:2076:  code = safe_ticker_component(ticker)
tradingagents/dataflows/a_stock.py:2157:  code = safe_ticker_component(ticker)

tradingagents/dataflows/utils.py:20: def safe_ticker_component(value: str, *, max_len: int = 32) -> str:

tradingagents/graph/trading_graph.py:21:  from tradingagents.dataflows.utils import safe_ticker_component
tradingagents/graph/trading_graph.py:423:  safe_ticker = safe_ticker_component(self.ticker)

tradingagents/graph/checkpointer.py:16:  from tradingagents.dataflows.utils import safe_ticker_component
tradingagents/graph/checkpointer.py:22:  safe = safe_ticker_component(ticker).upper()

tests/test_safe_ticker_component.py:8:  from tradingagents.dataflows.utils import safe_ticker_component
tests/test_safe_ticker_component.py:15-46:  7 个测试用例

scripts/parity_fault_inject.py:130: # safe_ticker_component 6-digit regex) and raises ValueError →  (注释引用)

backend/api/chart.py:65:  # Mirrors ``safe_ticker_component``  (注释引用 + 自己实现)
```

### 3.4 跨层问题分析

| 调用方 | 所在层 | 是否合规 | 说明 |
|---|---|---|---|
| `stockstats_utils.py` | dataflows/ | ✅ 合规 | 同层使用 |
| `a_stock.py` | dataflows/ | ✅ 合规 | 同层使用 |
| `graph/trading_graph.py` | graph/ | ❌ **跨层泄漏** | graph 层（编排）直接 import dataflows/ 的 utility |
| `graph/checkpointer.py` | graph/ | ❌ **跨层泄漏** | graph 层直接 import dataflows/ 的 utility |
| `tests/test_safe_ticker_component.py` | tests/ | ✅ 合规 | 测试可跨层 |
| `backend/api/chart.py` | backend/ | ⚠️ 注释引用 | 没 import，但自己复制了一份 "mirrors" 实现（line 65 注释） |

**为什么这是问题**：
- **DDD 分层原则**：graph/ 是 orchestration 层，应该只依赖 domain/ 的接口，不应该直接 import infrastructure（dataflows/）。
- **后果**：`safe_ticker_component` 想换实现（比如改成 `domain/value_objects/ticker.py`），要改 graph + checkpointer 两个文件，无法做到 domain 单向依赖。
- **backend/api/chart.py 的复制实现**：更糟 — 已经有"复制粘贴而非共享"的征兆。如果 `safe_ticker_component` 改了 regex（比如允许中文），chart.py 的副本会跟主版本 drift。

### 3.5 `safe_ticker_component` 测试覆盖（实测 7 个用例）

```
tests/test_safe_ticker_component.py (60 行)
├─ test_accepts_common_ticker_formats        (AAPL, BRK-B, BRK.A, 0700.HK, 7203.T, BHP.AX, ^GSPC)
├─ test_rejects_path_separators              (., .., ../etc, a/b, a\b, /abs, ..\..\x)
├─ test_rejects_null_byte_and_whitespace     (AAP L, AAPL\x00, AAPL\n, \tAAPL)
├─ test_rejects_empty_or_non_string          ('', None, 123, b'AAPL')
├─ test_rejects_overlong_input               (33 个 'A')
├─ test_rejects_dot_only_values              (., .., ..., ....)
└─ test_traversal_string_does_not_escape_join  (sanity: Path 拼接后仍在 base 内)
```

> **测试**没覆盖中文 ticker → resolve_ticker 的路径。这是测试覆盖盲点：中文 → 6 位代码转换全靠 `_build_name_code_map()` mock 或真 mootdx 调用，无单元测试。

---

## 4. `agents/utils/*.py` — Agent 工具集（10 文件 / 19 个 `@tool`）

> **路径**：`tradingagents/agents/utils/`（10 个 Python 文件）
> **实测 LOC 对照表**：task 描述里给的 LOC 是大量错估（如 `memory.py 11527` 实际是 11527 字节=300 行，`signal_data_tools.py 7945` 实际 7945 字节=208 行）。**正确数字见 §8 附录**。

### 4.1 文件分类（按用途）

| 文件 | LOC | 字节 | `@tool` 数 | 类别 | 说明 |
|---|---:|---:|---:|---|---|
| `agent_states.py` | 79 | 3474 | 0 | **状态定义** | `AgentState` / `InvestDebateState` / `RiskDebateState` TypedDict（详见 `DDD_AGENTS_DEEP_DIVE.md`） |
| `agent_utils.py` | 73 | 2278 | 0 | **装配** | re-export 19 个 `@tool` + `get_language_instruction` / `build_instrument_context` / `create_msg_delete` |
| `core_stock_tools.py` | 22 | 988 | 1 | OHLCV | `get_stock_data` |
| `technical_indicators_tools.py` | 31 | 1641 | 1 | 技术指标 | `get_indicators`（**comma-split** 多 indicator 内部循环调 ACL） |
| `fundamental_data_tools.py` | 76 | 3144 | 4 | 基本面 | `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` |
| `news_data_tools.py` | 53 | 2041 | 3 | 新闻 | `get_news` / `get_global_news` / `get_insider_transactions` |
| `signal_data_tools.py` | 208 | 7945 | 10 | **A 股独有信号** | 10 个 A 股特化 tool |
| `rating.py` | 50 | 1733 | 0 | **Typed contract** | `RATINGS_5_TIER` + `parse_rating` heuristic |
| `structured.py` | 73 | 2690 | 0 | **Typed contract** | `bind_structured` + `invoke_structured_or_freetext` |
| `memory.py` | 300 | 11527 | 0 | 持久化 | `TradingMemoryLog` append-only markdown log |
| **合计** | **965** | **37461** | **19** | | |

### 4.2 `@tool` 函数全清单（19 个）

#### 4.2.1 `core_stock_tools.py` — 1 个 `@tool`

```python
# core_stock_tools.py L6–22
@tool
def get_stock_data(
    symbol: Annotated[str, "6-digit A-stock code (e.g. 600379). Must be numeric, NOT company name or Chinese text"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date:   Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    return route_to_vendor("get_stock_data", symbol, start_date, end_date)
```

#### 4.2.2 `technical_indicators_tools.py` — 1 个 `@tool`（**comma-split 是亮点**）

```python
# technical_indicators_tools.py L5–31
@tool
def get_indicators(
    symbol: Annotated[str, "6-digit A-stock code..."],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date..."],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    # LLMs sometimes pass multiple indicators as a comma-separated string;
    # split and process each individually.
    indicators = [i.strip().lower() for i in indicator.split(",") if i.strip()]
    results = []
    for ind in indicators:
        try:
            results.append(route_to_vendor("get_indicators", symbol, ind, curr_date, look_back_days))
        except ValueError as e:
            results.append(str(e))
    return "\n\n".join(results)
```

> **亮点**：`get_indicators` 是**唯一支持多 indicator 一次传入的 tool**，处理 LLM 经常输错成 `"rsi,macd,kdj"` 的情况。Error 时返回 `str(e)` 而不是 raise，方便 LLM 重试。

#### 4.2.3 `fundamental_data_tools.py` — 4 个 `@tool`（4 选 1：基本面+三表）

| `@tool` | 参数 | ACL 调用 |
|---|---|---|
| `get_fundamentals(ticker, curr_date)` | 2 | `route_to_vendor("get_fundamentals", ...)` |
| `get_balance_sheet(ticker, freq, curr_date=None)` | 3 | `route_to_vendor("get_balance_sheet", ...)` |
| `get_cashflow(ticker, freq, curr_date=None)` | 3 | `route_to_vendor("get_cashflow", ...)` |
| `get_income_statement(ticker, freq, curr_date=None)` | 3 | `route_to_vendor("get_income_statement", ...)` |

> `freq` 默认 `"quarterly"`，`curr_date` 默认 `None`（**LangChain tool 用 None 作为 default 是反 pattern**，LLM 没法明确表达 "None"）。

#### 4.2.4 `news_data_tools.py` — 3 个 `@tool`

| `@tool` | 参数 | ACL 调用 |
|---|---|---|
| `get_news(ticker, start_date, end_date)` | 3 | `route_to_vendor("get_news", ...)` |
| `get_global_news(curr_date, look_back_days=7, limit=5)` | 3 | `route_to_vendor("get_global_news", ...)` |
| `get_insider_transactions(ticker)` | 1 | `route_to_vendor("get_insider_transactions", ...)` |

> **A 股局限**：`get_insider_transactions` 在 a_stock.py 中是 stub（mock 数据），真实内部人交易数据 A 股监管不公开，需要未来对接特定供应商。

#### 4.2.5 `signal_data_tools.py` — **10 个 `@tool`（A 股独有）**

| `#` | `@tool` | A 股数据源 | 关键参数 |
|---:|---|---|---|
| 1 | `get_profit_forecast(ticker)` | 10jqka EPS 一致预期 | 1 |
| 2 | `get_hot_stocks(curr_date="")` | 10jqka 涨停归因 + 主题词频 | 1 |
| 3 | `get_northbound_flow(curr_date, include_history=False)` | 东财 push2 f58 + f62 (HGT/SGT) | 2 |
| 4 | `get_concept_blocks(ticker)` | 东财 push2 f10 + 百度 PAE | 1 |
| 5 | `get_fund_flow(ticker, curr_date, include_history=True)` | 东财 push2 f62/f63 分钟级 | 3 |
| 6 | `get_dragon_tiger_board(ticker, curr_date, look_back_days=30)` | 东财 datacenter | 3 |
| 7 | `get_lockup_expiry(ticker, curr_date, forward_days=90)` | 东财 datacenter | 3 |
| 8 | `get_industry_comparison(ticker, curr_date)` | 10jqka 行业横向 | 2 |
| 9 | `get_hot_strategy_ranking(curr_date="", top_n=20)` | 东财 np-ipick | 2 |
| 10 | `get_sector_rotation_digest(curr_date="", top_n=20)` | np-ipick + 10jqka 涨停 + 百度 PAE | 2 |

> **唯一 dataclass 返回**：`get_sector_rotation_digest` 的 ACL 调用结果是 `SectorRotationDigest` dataclass，tool 在 line 206 兜底处理 `hasattr(digest, "markdown")`。

> **Cost 提示**：tool docstring 显式写 "Limit calls to 1 per session"（`get_hot_strategy_ranking` L169 + `get_sector_rotation_digest` L195），说明这两个 tool 是**高 cost、低频**的。

### 4.3 `rating.py` — 5-tier typed contract（**关键发现**）

```python
# rating.py L19–27
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)
_RATING_SET = {r.lower() for r in RATINGS_5_TIER}
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)

# rating.py L30–50
def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.
    Two-pass strategy:
    1. Look for an explicit "Rating: X" label (tolerant of markdown bold).
    2. Fall back to the first 5-tier rating word found anywhere in the text.
    Returns a Title-cased rating string, or ``default`` if no rating word appears.
    """
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            return m.group(1).capitalize()

    for line in text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in _RATING_SET:
                return clean.capitalize()

    return default
```

**调用方（实测）**：

```
tradingagents/agents/utils/memory.py          L7  from .rating import parse_rating
tradingagents/agents/utils/memory.py          L46 rating = parse_rating(final_trade_decision)
tradingagents/graph/signal_processing.py      L17 from tradingagents.agents.utils.rating import parse_rating
tradingagents/graph/signal_processing.py      L31 return parse_rating(full_signal)
```

**关键价值**：
1. **真正的 typed contract**：5 个值 hardcoded 在 `RATINGS_5_TIER` tuple，下游所有代码（research manager / portfolio manager / signal processor / memory log）共用同一份 vocabulary。
2. **Heuristic parser 而非 enum**：因为 LLM 输出是 prose，需要 regex 解析（支持 "Rating: **Buy**" markdown bold）。这是 DDD 里 Value Object 的"有限 vocabulary + parser"模式。
3. **解决 P2.23 部分问题**：第三轮发现的 "structured-output invocation failed" 部分由 `structured.py` 的 fallback 处理，部分由 `rating.py` 的 prose 兜底处理。

**局限**：
- `RATINGS_5_TIER` 是 `Tuple[str, ...]`，**不是 `Enum`**。比较时仍要 lowercase 或 capitalize，不强制类型安全。
- `_RATING_LABEL_RE` 只匹配一行内的 "rating: X"，不支持跨行。
- `default = "Hold"` 在 LLM 没明确给 rating 时会**默认填 Hold**，可能掩盖事实。

### 4.4 `structured.py` — LLM structured output + 优雅 fallback（73 行）

```python
# structured.py L31–73
def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported."""
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning("%s: provider does not support with_structured_output (%s); "
                       "falling back to free-text generation", agent_name, exc)
        return None

def invoke_structured_or_freetext(structured_llm, plain_llm, prompt, render, agent_name) -> str:
    """Run the structured call and render to markdown; fall back to free-text on any failure."""
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return render(result)
        except Exception as exc:
            logger.warning("%s: structured-output invocation failed (%s); "
                           "retrying once as free text", agent_name, exc)
    response = plain_llm.invoke(prompt)
    return response.content
```

**调用方**：
```
tradingagents/agents/managers/research_manager.py   (Research Manager)
tradingagents/agents/managers/portfolio_manager.py  (Portfolio Manager)
tradingagents/agents/trader/trader.py               (Trader)
```

> **关键作用**：3 个 Manager/Trader 共用同一套 pattern（"try structured → fall back to free-text"）。centralise 后减少 ~3 处重复实现，避免 drift。
>
> **问题**：`except Exception` 太宽（line 66），连 `KeyboardInterrupt` 都会 catch（Python 3 中 `Exception` 不 catch `KeyboardInterrupt`，但 `SystemExit` 仍可能）。建议改成 `except (ValueError, TypeError, JSONDecodeError, ...)`。

### 4.5 `memory.py` — `TradingMemoryLog` append-only markdown log（300 行）

> **关键发现**：memory.py **不是 ChromaDB**，是**纯 markdown + regex 解析**的决策日志。

```python
# memory.py L10–17
class TradingMemoryLog:
    """Append-only markdown log of trading decisions and reflections."""
    _SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"        # HTML 注释做硬分隔符
    _DECISION_RE = re.compile(r"DECISION:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
    _REFLECTION_RE = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)
```

**Entry 格式**：
```
[2024-06-15 | 600379 | Buy | pending]

DECISION:
... (LLM 输出的决策文本)

<!-- ENTRY_END -->

[2024-06-15 | 600379 | Buy | +12.3% | +5.1% | 30d]

DECISION:
... (LLM 输出的决策文本)

REFLECTION:
... (回测后反思)

<!-- ENTRY_END -->
```

**3 个阶段**：
1. **Phase A（写 pending）**：`store_decision()` line 31–50 — 调 `parse_rating` 拿 rating，写 `[date | ticker | rating | pending]` tag。
2. **Phase A（读）**：`load_entries()` line 54–65 + `get_past_context()` line 71–96 — 解析全部 entry，按 (ticker 匹配 / cross-ticker) 选 n_same + n_cross 条注入 prompt。
3. **Phase B（写 reflection）**：`update_with_outcome()` line 100–163 — 找到 pending entry，replace tag + append REFLECTION。**atomic write** 用 `tmp_path.replace(self._log_path)`。

**测试覆盖盲点**：300 行 memory.py **没有专门 unit test**（grep `tests/test_memory.py` 不存在）。这是覆盖缺口。

### 4.6 `agent_states.py` + `agent_utils.py` — 状态 + 装配（79 + 73 行）

`agent_states.py`：定义 `AgentState`（继承 `MessagesState`）/ `InvestDebateState` / `RiskDebateState`，详见 `DDD_AGENTS_DEEP_DIVE.md`。

`agent_utils.py`：**纯装配文件**，re-export 19 个 `@tool`（line 4–32），加上 3 个 helper：
- `get_language_instruction()` — 读 `output_language` 配置返回中文/英文指令。
- `build_instrument_context(ticker)` — 给 agent prompt 加 "the instrument to analyze is X" 上下文。
- `create_msg_delete()` — Anthropic 兼容的 messages 清空函数（Add HumanMessage "Continue" placeholder）。

---

## 5. 跨层调用图 + 数据流

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          LangGraph Agent 层                              │
│  tradingagents/agents/analysts/{fundamentals,hot_money_tracker}.py       │
│  tradingagents/agents/managers/{research,portfolio}_manager.py           │
│  tradingagents/agents/trader/trader.py                                   │
│  tradingagents/agents/risk_mgmt/{aggressive,conservative,neutral}.py    │
└──────────────────────────────────────────────────────────────────────────┘
        │                    │                    │
        │ ToolNode 调         │ struct out         │ AgentState 共享
        ▼                    ▼                    ▼
┌──────────────────────────────────┐    ┌─────────────────────────────┐
│  agents/utils/*.py               │    │  agents/utils/structured.py │
│  19 个 @tool 函数                 │    │  bind_structured            │
│  每个 = @tool + route_to_vendor  │    │  invoke_structured_or_freetext│
└──────────────────────────────────┘    └─────────────────────────────┘
        │                                            │
        │ route_to_vendor(method, *args, **kwargs)   │
        ▼                                            │
┌──────────────────────────────────────────────────────────────────┐
│  dataflows/interface.py — Anti-Corruption Layer (239 行)         │
│  TOOLS_CATEGORIES (5) / VENDOR_METHODS (19 method × 3 vendor)    │
│  get_vendor (tool-level > category-level)                         │
│  route_to_vendor (3 vendor fallback on AlphaVantageRateLimitError)│
└──────────────────────────────────────────────────────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ a_stock.py       │   │ y_finance.py     │   │ alpha_vantage*   │
│ 2610 行 (11 数据源)│   │ 421 行 (yfinance) │   │ 4 文件 ~388 行   │
│ 内嵌 fallback:    │   │ yfinance_news.py  │   │ alpha_vantage_common│
│ mootdx→sina→push2his│  │ 197 行            │   │ AlphaVantageRateLimitError│
└──────────────────┘   └──────────────────┘   └──────────────────┘
        │
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  External 11 HTTP/TCP 数据源 (A 股独有)                           │
│  mootdx TCP:7709 / qt.gtimg.cn / push2.eastmoney / datacenter-web│
│  push2his.eastmoney / money.finance.sina / 10jqka.com.cn          │
│  cls.cn / gushitong.baidu / np-weblist / np-ipick                 │
└──────────────────────────────────────────────────────────────────┘
```

**关键调用路径**（典型一次 OHLCV 查询）：
```
Analyst (Fundamentals) 
  → ToolNode 调 @tool get_stock_data(symbol="600595", start, end)
  → agents/utils/core_stock_tools.get_stock_data 调 route_to_vendor
  → dataflows/interface.route_to_vendor
    ├─ primary vendor: a_stock (data_vendors["core_stock_apis"]="a_stock")
    │   → a_stock.get_astock_stock_data (line ~550 内部 3 层 fallback)
    │     ├─ mootdx TCP (7709)        ─ try → except _FutTimeoutError
    │     ├─ _sina_kline_fallback      ─ try → except Exception
    │     └─ _push2his_kline_fallback  ─ try → except Exception (final)
    │   → return pd.DataFrame 格式化为 str
    └─ if AlphaVantageRateLimitError: continue → yfinance → alpha_vantage
  → return str to Analyst
```

---

## 6. 架构债务（7 条）

### 6.1 已知债务清单

| # | 债务 | 严重度 | 影响范围 | 修复成本 |
|---:|---|---|---|---|
| 1 | **ACL 只覆盖 3 vendor，不覆盖 11 HTTP 数据源** | 🟠 High | `a_stock.py` 内 11 数据源 fallback 不经 `route_to_vendor` | 高（重构 fallback chain） |
| 2 | **Fallback 仅触发 `AlphaVantageRateLimitError`** | 🟠 High | 网络/解析/5xx 错直接 raise，不 fallback | 低（改 except 子句） |
| 3 | **No health check / circuit breaker** | 🟠 High | primary vendor 挂就 100% 失败，无熔断 | 中（加 per-vendor 失败计数） |
| 4 | **Vendor list hardcoded**（3 vendor 写死在 `VENDOR_LIST`） | 🟡 Med | 加新 vendor 必改源码 | 中（改成注册表） |
| 5 | **`safe_ticker_component` 跨层泄漏** | 🟠 High | `graph/trading_graph.py` + `graph/checkpointer.py` 直接 import dataflows utility | 中（提到 domain/） |
| 6 | **`rating.py` 是局部 typed contract，不是全局 enum** | 🟡 Med | `RATINGS_5_TIER: Tuple[str, ...]` 非 Enum，比较仍需 lowercase/capitalize | 低（升级为 Enum） |
| 7 | **`memory.py` 跨 markdown + regex，无 embedding/vector** | 🟢 Low | "semantic search" 在 P3.x 路线图但当前不可用 | 高（接 ChromaDB / LanceDB） |

### 6.2 债务详细分析

#### 6.2.1 ACL 只覆盖 3 vendor，不覆盖 11 数据源

**现状**：
- `interface.py` 的 `VENDOR_METHODS` 只有 `a_stock` / `yfinance` / `alpha_vantage` 3 个 key。
- `a_stock.py` 内部 11 个数据源（mootdx TCP、qt.gtimg.cn、push2.eastmoney、datacenter-web、push2his、money.finance.sina、10jqka、cls.cn、gushitong.baidu、np-weblist、np-ipick）的 fallback 完全在 a_stock.py 内部嵌套 try/except 完成（line 561–635 是 3 层 fallback 典型）。

**为什么是问题**：
- ACL 的核心价值是**集中 vendor 配置**（一份 config 切换 vendor）。11 数据源散落 a_stock.py 意味着切换数据源要改 a_stock.py。
- `route_to_vendor` 的 fallback 只在 vendor 之间（如 a_stock → yfinance）触发，**不在数据源之间**（如 mootdx → sina）触发。

**修复方向**：把 a_stock.py 内部 fallback 也通过 ACL 路由（见 §7 R4）。

#### 6.2.2 Fallback 仅触发 `AlphaVantageRateLimitError`

**现状**（`interface.py` L237）：
```python
try:
    return impl_func(*args, **kwargs)
except AlphaVantageRateLimitError:
    continue  # Only rate limits trigger fallback
```

**问题**：
- 其他 exception（`ConnectionError` / `Timeout` / `JSONDecodeError` / `KeyError` / `ValueError`）都直接 raise，**不触发 vendor 切换**。
- alpha_vantage 限流错误用专门 class（`AlphaVantageRateLimitError`），yfinance 用 `YFRateLimitError`（在 `stockstats_utils.yf_retry` 里独立处理）。
- a_stock.py 内部 fallback 用裸 `except Exception`，更宽。

**修复方向**：定义 `VendorUnavailableError` base class，所有 vendor-specific 错误都继承它，route_to_vendor catch base class（见 §7 R1）。

#### 6.2.3 No health check / circuit breaker

**现状**：每次调用都直接调 primary vendor，没有 "上一次失败 → 临时禁用 N 秒" 的熔断。

**问题**：
- primary vendor 挂时，**每个 tool call 都重试**直到成功/超时。
- 11 个 tool 并发时，primary vendor 同时被压 11 次（thundering herd）。

**修复方向**：加 per-vendor 失败计数 + 半开熔断（见 §7 R2）。

#### 6.2.4 Vendor list hardcoded

**现状**（`interface.py` L100–104）：
```python
VENDOR_LIST = [
    "a_stock",
    "yfinance",
    "alpha_vantage",
]
```

**问题**：加新 vendor（如 `tushare` / `akshare`）要改源码 + 重启。

**修复方向**：改成注册表模式 + 装饰器（见 §7 R4）。

#### 6.2.5 `safe_ticker_component` 跨层泄漏

**现状**：见 §3.4 跨层问题矩阵。

**修复方向**：见 §7 R3。

#### 6.2.6 `rating.py` 是局部 typed contract

**现状**（`rating.py` L19–21）：
```python
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)
```

**问题**：
- `Tuple[str, ...]` 允许任何 string，下游 `if rating == "BUY": ...` 容易大小写错。
- `parse_rating` 返回 `str` 而非 `Rating` enum。

**修复方向**：见 §7 R5。

#### 6.2.7 `memory.py` 无 embedding / vector search

**现状**：memory.py 是**纯 markdown + regex 解析**（`TradingMemoryLog`）。语义搜索需要 future work。

**修复方向**：见 §7 R6。

---

## 7. 重构建议（短期 / 中期 / 长期）

### 7.1 短期（1-2 周 / 0-3 个 PR）

#### R1: 修 ACL fallback 范围（覆盖所有 vendor exception）

**改动**（`interface.py` L25 附近）：
```python
# 当前
except AlphaVantageRateLimitError:
    continue

# 建议（引入 VendorUnavailable base exception）
class VendorUnavailable(Exception):
    """Base class for all vendor-specific failure modes."""

class VendorRateLimited(VendorUnavailable): ...
class VendorTimeout(VendorUnavailable): ...
class VendorParseError(VendorUnavailable): ...

# interface.py L235–238
except VendorUnavailable as exc:
    logger.warning("vendor %s unavailable for %s: %s", vendor, method, exc)
    continue    # All vendor failures trigger fallback
```

**好处**：网络/解析/限流/超时统一 fallback，**11 数据源错误也能 fallback 到 yfinance**（前提是 yfinance 也覆盖该 method）。

**测试**：加 `tests/test_interface.py`，覆盖 (a) 所有 vendor 失败的 fallback chain，(b) 单 vendor 失败不阻塞其他 call site。

**工时**：0.5-1 天。

#### R2: 加 circuit breaker（per-vendor 失败计数 + 临时禁用）

**改动**（`interface.py` L215 附近）：
```python
# 引入 breaker 状态（per-vendor, 内存）
_breaker_state: dict[str, dict] = {}

def _vendor_available(vendor: str) -> bool:
    state = _breaker_state.setdefault(vendor, {"fails": 0, "open_until": 0})
    if time.time() < state["open_until"]:
        return False                                # 熔断中
    return True

def _record_failure(vendor: str):
    state = _breaker_state.setdefault(vendor, {"fails": 0, "open_until": 0})
    state["fails"] += 1
    if state["fails"] >= 3:
        state["open_until"] = time.time() + 60      # 60s 熔断

# route_to_vendor 调整
for vendor in fallback_vendors:
    if not _vendor_available(vendor): continue
    ...
    except VendorUnavailable:
        _record_failure(vendor)
        continue
```

**好处**：vendor 全挂时自动跳过（不浪费 timeout），恢复后自动 retry。

**工时**：1-2 天。

#### R3: 把 `safe_ticker_component` 提到 domain/（跨层修复）

**改动**：
```
# 新建 tradingagents/domain/value_objects/ticker.py
class Ticker(str):
    """Validated 6-digit A-stock code (or convertible name)."""
    @classmethod
    def from_user_input(cls, value: str) -> "Ticker":
        ...

# 重命名 dataflows/utils.py: safe_ticker_component → deprecated shim
# graph/trading_graph.py + checkpointer 改 from tradingagents.domain.value_objects.ticker import Ticker
# a_stock.py / stockstats_utils.py 同样
```

**好处**：graph 不再依赖 dataflows，分层回归单向。

**工时**：0.5 天（含 deprecation warning）。

### 7.2 中期（1-2 月 / 5-10 PR）

#### R4: ACL 覆盖 11 数据源（不只 3 vendor）

**改动**：把 a_stock.py 内部 fallback 也走 ACL：
```python
# 新增 vendor key "a_stock_mootdx" / "a_stock_sina" / "a_stock_push2his"
VENDOR_METHODS["get_stock_data"]["a_stock_mootdx"]   = _get_stock_data_mootdx
VENDOR_METHODS["get_stock_data"]["a_stock_sina"]     = _get_stock_data_sina
VENDOR_METHODS["get_stock_data"]["a_stock_push2his"] = _get_stock_data_push2his
```

**好处**：用户能在 `tool_vendors` 配置中指定只用某个数据源（如"只用 push2his"）。

**工时**：1 周（需要拆分 a_stock.py 的 fallback 函数）。

#### R5: rating 提升为全局 typed contract（PortfolioRating enum 升级）

**改动**：
```python
# rating.py
from enum import Enum

class PortfolioRating(Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"

def parse_rating(text: str, default: PortfolioRating = PortfolioRating.HOLD) -> PortfolioRating:
    ...
```

**好处**：
- 类型安全（`if rating == PortfolioRating.BUY:` 不需要 lowercase）。
- IDE auto-complete 支持。
- Pydantic schema 可直接用 enum。

**工时**：1-2 天（含下游调用方更新）。

#### R6: memory.py 抽 Provider 抽象（支持多种 embedding 后端）

**改动**：定义 `MemoryProvider` 抽象：
```python
class MemoryProvider(Protocol):
    def store(self, ticker: str, entry: dict) -> None: ...
    def retrieve_similar(self, query: str, top_k: int = 5) -> list[dict]: ...

class MarkdownLogProvider: ...   # 当前实现
class ChromaDBProvider: ...      # 未来
class LanceDBProvider: ...       # 未来
```

**工时**：2 周（含 ChromaDB 集成 + P3.x semantic search）。

### 7.3 长期（季度级 / 跨模块）

#### R7: async ACL（asyncio + httpx）

**改动**：把 `route_to_vendor` 改成 async：
```python
async def route_to_vendor_async(method, *args, **kwargs) -> str:
    ...
    return await impl_func(*args, **kwargs)
```

**好处**：并发 19 个 tool call 时不阻塞（当前 LangGraph ToolNode 是同步的，串行调用 19 个 tool 可能 60-90s）。

**工时**：2-3 周（含 a_stock.py 全 async 化）。

#### R8: 数据源 provider 配置化（YAML / TOML）

**改动**：把 `default_config.py` 的 `data_vendors` / `tool_vendors` 提到 YAML/TOML：
```yaml
# config.yaml
vendors:
  core_stock_apis:
    primary: a_stock
    fallback: [yfinance, alpha_vantage]
  signal_data:
    primary: a_stock
    timeout_seconds: 30
  ...
```

**好处**：用户/运维改 YAML 不需要 Python knowledge。

**工时**：1-2 周（含 schema validation + hot-reload）。

---

## 8. 附录：实测 LOC 对照表

> **Task 描述里给的 LOC 大部分是错的**（如 `memory.py 11527` 实际是 11527 字节=300 行）。下面是**实测** LOC 对照。

### 8.1 `dataflows/` 14 个 Python 模块实测 LOC

```
排序按 LOC 降序
─────────────────────────────────────────────
a_stock.py                              2610
y_finance.py                             421
interface.py                             239
alpha_vantage_indicator.py               222
yfinance_news.py                         197
stockstats_utils.py                      133
alpha_vantage_common.py                  122
utils.py                                  80
alpha_vantage_news.py                     70
alpha_vantage_fundamentals.py             55
alpha_vantage_stock.py                    37
config.py                                 31
alpha_vantage.py                           4
__init__.py                                0
─────────────────────────────────────────────
Total                                  4221 行（13 个模块 + __init__.py）
```

### 8.2 `agents/utils/` 10 个 Python 模块实测 LOC

```
排序按字节数降序（task 描述里给的是字节数）
─────────────────────────────────────────────
memory.py                          300 行 / 11527 字节
signal_data_tools.py               208 行 /  7945 字节
fundamental_data_tools.py           76 行 /  3144 字节
agent_states.py                     79 行 /  3474 字节
structured.py                       73 行 /  2690 字节
agent_utils.py                      73 行 /  2278 字节
news_data_tools.py                  53 行 /  2041 字节
rating.py                           50 行 /  1733 字节
technical_indicators_tools.py       31 行 /  1641 字节
core_stock_tools.py                 22 行 /   988 字节
─────────────────────────────────────────────
Total                              965 行 / 37461 字节
```

### 8.3 `@tool` 装饰器统计（19 个）

```
agents/utils/signal_data_tools.py          10
agents/utils/fundamental_data_tools.py      4
agents/utils/news_data_tools.py             3
agents/utils/core_stock_tools.py            1
agents/utils/technical_indicators_tools.py  1
agents/utils/rating.py                      0  (无 @tool)
agents/utils/structured.py                  0  (无 @tool)
agents/utils/memory.py                      0  (无 @tool)
agents/utils/agent_states.py                0  (无 @tool)
agents/utils/agent_utils.py                 0  (无 @tool)
─────────────────────────────────────────────
Total                                     19
```

### 8.4 关键配置摘要

```
default_config.py:
├─ data_vendors:    5 个 category 全部 "a_stock"
├─ tool_vendors:    {}  (空，用户可覆盖)
├─ data_cache_dir:  ~/.tradingagents/cache
├─ memory_log_path: ~/.tradingagents/memory/trading_memory.md
└─ output_language: "Chinese"
```

### 8.5 测试覆盖盲点

| 模块 | 现有测试 | 缺失 |
|---|---|---|
| `interface.py` | ❌ **无** | route_to_vendor fallback chain 行为未测 |
| `stockstats_utils.py` | ❌ **无** | yf_retry 重试逻辑 + _clean_dataframe 未测 |
| `utils.py` (`safe_ticker_component`) | ✅ `tests/test_safe_ticker_component.py`（7 用例） | 中文 ticker → resolve_ticker 路径未覆盖 |
| `memory.py` | ❌ **无** | 300 行 append-only markdown log 0 测试 |
| `rating.py` | ❌ **无** | parse_rating heuristic 未测 |
| `structured.py` | ❌ **无** | bind/invoke structured fallback 未测 |
| `signal_data_tools.py` | ⚠️ 部分（via `tests/test_sector_rotation_digest.py`） | 10 个 @tool 端到端测试覆盖弱 |

---

## 9. 与前 3 个 DDD 文档的边界

本文（`DDD_DATAFLOWS_DEEP.md`）与前 3 个 DDD 文档的关系：

| 文档 | 关注 | 不关注 |
|---|---|---|
| `DDD_EXPLORATION.md` | backend/core 13 聚合根 + Domain 模型 | dataflows/ + agents/utils |
| `DDD_AGENTS_DEEP_DIVE.md` | LangGraph 16 Agent + state machine + 状态流转 | dataflows/ ACL + utils + stockstats_utils |
| `DDD_DATAFLOWS_INFRA.md` | dataflows/ 13 模块 + 11 外部数据源 + Repository 视角 | ACL 详细 + agents/utils 工具集 |
| **`DDD_DATAFLOWS_DEEP.md`（本文）** | **ACL 详细 + yfinance 集成 + ticker 校验 + 工具集** | backend/core 聚合根 + Agent state machine |

**互补性**：
- 上一轮 `DDD_DATAFLOWS_INFRA.md` §6 说"ACL 几乎不存在"，本文 §1 纠偏为"ACL 已存在但范围有限"。
- 上一轮 §5 的 `safe_ticker_component` 跨层泄漏**得到验证**（见 §3.4）。
- 上一轮 §3 提到的 "Fallback 在 a_stock.py 内部嵌套 try/except" 在本文 §5 调用图得到完整复现。

---

## 10. 总结

### 核心发现

1. **`interface.py` 已经是 ACL**（239 行实现 5 category + 19 method × 3 vendor + route_to_vendor + 二级 vendor 配置）。这是对前一轮 `DDD_DATAFLOWS_INFRA.md` §6 "ACL 几乎不存在" 的**纠偏**。
2. **ACL 覆盖范围有限**：3 vendor（a_stock / yfinance / alpha_vantage），不含 11 HTTP 数据源。a_stock.py 内部 11 数据源 fallback 不经过 route_to_vendor。
3. **`stockstats_utils.py` 仍依赖 yfinance + stockstats 第三方库**，A 股数据层未完全自主。
4. **`safe_ticker_component` 跨层泄漏已验证**：graph/trading_graph.py + graph/checkpointer.py 直接 import dataflows/utils.py 的 utility。
5. **`rating.py` 是真正的 typed contract**（5-tier vocabulary + heuristic parser），但不是 Enum，类型安全有限。
6. **`memory.py` 不是 ChromaDB**，是纯 markdown + regex 解析的决策日志。`TradingMemoryLog` 是 append-only + atomic write。
7. **`structured.py` 提供 3 个 Manager/Trader 共用的 structured output fallback pattern**，解决 P2.23 部分问题。

### 重构优先级

| 优先级 | 建议 | 工时 |
|---|---|---|
| 🔴 P0 | R1（ACL fallback 覆盖所有 vendor exception） | 0.5-1 天 |
| 🔴 P0 | R2（circuit breaker） | 1-2 天 |
| 🟠 P1 | R3（safe_ticker_component 提到 domain/） | 0.5 天 |
| 🟠 P1 | R4（ACL 覆盖 11 数据源） | 1 周 |
| 🟡 P2 | R5（rating 升级 Enum） | 1-2 天 |
| 🟡 P2 | R6（memory.py Provider 抽象） | 2 周 |
| 🟢 P3 | R7（async ACL） | 2-3 周 |
| 🟢 P3 | R8（YAML 配置化） | 1-2 周 |

### 测试覆盖盲点

`interface.py` / `stockstats_utils.py` / `memory.py` / `rating.py` / `structured.py` **全无 unit test**。建议下一轮补 5 个测试文件（test_interface.py / test_stockstats_utils.py / test_memory_log.py / test_rating.py / test_structured.py）。

---

**End of `DDD_DATAFLOWS_DEEP.md`**