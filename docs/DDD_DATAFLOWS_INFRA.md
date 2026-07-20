# TradingAgents A 股 基础设施层 + 外部数据源 DDD 深入探索（read-only）

> **范围**：`tradingagents/dataflows/` 13 个模块 + 10+ 外部数据源 + Repository / Anti-Corruption Layer 视角。本文是第三轮 DDD 战术探索，聚焦**基础设施层（Infrastructure Layer）**的 A 股数据访问与防封限流设计，不重复 `docs/DDD_EXPLORATION.md` 的 13 个后端聚合根，也不重复 `docs/DDD_AGENTS_DEEP_DIVE.md` 的 16 个 LangGraph Agent。
>
> **git HEAD**：`33b3a42`（P2.25 tracker + history_store + runner ID 一致性）
>
> **方法**：逐个读取 `a_stock.py` / `interface.py` / `utils.py` / `stockstats_utils.py` / `config.py` 和 7 个 alpha_vantage + yfinance 模块；按代码实际调用路径记录 URL、port、timeout、fallback、缓存、限流和反封策略；对 Repository 抽象 / ACL 边界 / Fallback 链硬编码 / 跨层耦合做战术评估。
>
> **硬约束**：只读审计；本轮只创建本文件，不修改 Python、pytest、`pyproject.toml`、spec，不提交 commit。

---

## 0. 执行摘要

### 0.1 代码事实先于目标描述

`tradingagents/dataflows/` 是一个 **A 股特化的 vendor 模块集合**，不是传统 DDD 中的「Repository 实现层」。代码现状如下：

- **13 个文件、4221 LOC**，其中 `a_stock.py` 占 **2610 行（61.8%）**——一个文件包含 41 个公开函数 + 8 个内部 helper 函数，是全仓库第二大的单一业务文件（仅次于 `a_stock.py` 自身和 `portfolio_calc.py`）。
- **10 个外部数据源集成**全部位于 `a_stock.py`，其中 **6 个有显式 fallback**（mootdx → sina → push2his、Eastmoney → sina），**4 个没有任何 fallback**（cls.cn 财联社、np-ipick、hot stocks 同花顺、np-weblist 东财 7×24）。
- **完全无第三方数据库依赖**——CLAUDE.md 明确指出 v0.2.5 删除了 akshare，10 个数据源全为**直连 HTTP + mootdx TCP**。
- **完全没有 Repository 接口抽象**——41 个函数是**模块级自由函数**，没有任何 Protocol / ABC / dataclass 约束 Agent 调用方必须实现的契约。
- **完全没有 Anti-Corruption Layer（ACL）**——41 个函数都返回 **`str`（格式化 Markdown）或 `pd.DataFrame`**，直接把 pandas 列名（`Date / Open / High / Low / Close / Volume`）暴露给 Agent 层；Agent 必须知道 OHLCV 列名才能正确解析 CSV。
- **防封限流是全模块统一纪律**：`a_stock.py` 用单例 `_EM_SESSION` + 模块级 `_em_last_call` 时间戳 + `_EM_MIN_INTERVAL` 默认 1.0s 节流 + `random.uniform(0.1, 0.5)` 抖动保护所有 eastmoney.com 请求；mootdx 用 `ThreadPoolExecutor` + 8s 硬超时避免 TCP 挂死；其他数据源（腾讯 / 新浪 / 同花顺 / 财联社 / 百度）**没有显式限流**，依赖"实测不严苛"的运维经验。

### 0.2 关键 DDD 战术发现

1. **`interface.py` 是 Vendor 路由器，不是 Repository**——`VENDOR_METHODS` 字典 + `route_to_vendor()` 函数只做"按 tool 名分发到 a_stock / yfinance / alpha_vantage 三个 vendor 实现"，不提供领域接口抽象。
2. **3-fallback K 线链是** **硬编码** **的**——`get_stock_data()` 的 mootdx → sina → push2his 失败回退是用嵌套 `try/except` + 重复 try block 实现的（v0.4.0 在原 2 段 fallback 上加第 3 段，重复代码 50+ 行），无法配置顺序、无法在 runtime 跳过某段。
3. **`SectorRotationDigest` 是** **唯一领域 DTO**——`@dataclass(frozen=True)` 结构体只在 `get_sector_rotation_digest()` 返回值上使用，是 41 个函数中唯一脱离 `str / pd.DataFrame` 返回类型的 API。
4. **`safe_ticker_component()` 是** **唯一的输入侧 ACL**——`utils.py:20-47` 用 regex 校验 ticker 不含路径穿越字符 + 自动调用 `resolve_ticker()` 把中文名转 6 位代码，是跨层防御 LLM 输出恶意 ticker 注入路径的关键闸口。
5. **第三方 vendor 仍是死代码**——CLAUDE.md 写 "v0.2.5 全部直连 HTTP，零第三方数据库依赖"，但 `y_finance.py` (421 LOC) / `yfinance_news.py` (197 LOC) / `alpha_vantage*.py` (532 LOC) 7 个文件仍在 `tradingagents/dataflows/` 占位，仅在 `interface.py:107-188 VENDOR_METHODS` 字典里被 import 作为 fallback 选项。
6. **`_normalize_ticker()` 跨层泄漏到 backend**——`backend/core/portfolio_store.py:63` / `backend/core/portfolio_import.py:29` 直接 import 私有函数 `_normalize_ticker as _normalize_ticker`，破坏模块封装边界。`portfolio_calc.py:672` 也直接 import `get_concept_blocks`（私有数据源）。

---

## 1. 13 个 dataflow 模块分类

按职责分层（基于 `wc -l tradingagents/dataflows/*.py` 实测行数）：

### 1.1 核心层 — A 股特化（2610 LOC, 61.8%）

| 模块 | LOC | 角色 | DDD 等价 |
|---|---|---|---|
| `a_stock.py` | 2610 | 41 个公开函数 + 8 个内部 helper，覆盖 10 个外部数据源的所有 A 股 vendor 实现 | **Anti-Corruption Layer（草创） + Repository 实现 + Use Case Adapter** 三合一 |

`a_stock.py` 模块按代码内 `--- # ---- N. function ----` 节标题划分 9 个 vendor methods + 7 个 A 股特化 signal methods + 1 个综合 digest：

```
==== 9 Vendor Methods（跟 interface.py VENDOR_METHODS 1:1 对应）====
1.  get_stock_data            — 3-fallback OHLCV (mootdx→sina→push2his)
2.  get_indicators            — stockstats on top of OHLCV
3.  get_fundamentals          — Tencent + mootdx + Eastmoney push2 + 同花顺
4.  get_balance_sheet         — Sina 财报三表 (CompanyFinanceService)
5.  get_cashflow              — Sina 财报三表
6.  get_income_statement      — Sina 财报三表
7.  get_news                  — Eastmoney search-api + Sina fallback
8.  get_global_news           — CLS + Eastmoney np-weblist
9.  get_insider_transactions  — mootdx F10 股东研究 (closest to US insider)

==== 7 A 股 Signal Layer（v0.2.6+ 增量）====
10. get_profit_forecast       — 同花顺 EPS 一致预期 + Tencent price → fwd PE / PEG / digestion
11. get_hot_stocks            — 同花顺 zx.10jqka 涨停归因 (人工 reason tags)
12. get_northbound_flow       — 同花顺 hsgtApi (data.hexin.cn) 分钟级 + 本地 CSV 历史快照
13. get_concept_blocks        — 百度 PAE (finance.pae.baidu.com) 个股所属概念/行业/地域
14. get_fund_flow             — Eastmoney push2 fflow (主力/小单/中单/大单/超大单) + push2his daykline
15. get_dragon_tiger_board    — Eastmoney datacenter-web (RPT_DAILYBILLBOARD_DETAILSNEW)
16. get_lockup_expiry         — Eastmoney datacenter-web (RPT_LIFT_STAGE)
17. get_industry_comparison   — Eastmoney push2 clist (m:90+t:2 全行业排名)
18. get_hot_strategy_ranking  — Eastmoney np-ipick (xuangu.eastmoney.com 选股热度)
19. get_sector_rotation_digest — 组合 #18 + #11 + 百度 PAE 反查，4 段式 Markdown

==== 辅助基础设施 ====
- _get_prefix / _normalize_ticker / _build_name_code_map / resolve_ticker
- _get_mootdx_client (singleton + ThreadPoolExecutor 4s 超时)
- _tencent_quote (HTTP GBK 解析)
- _em_get (统一 eastmoney 节流入口)
- _eastmoney_datacenter (datacenter-web 通用查询)
- _ths_eps_forecast (pd.read_html 解析同花顺 worth.html)
- _sina_kline_fallback / _sina_stock_code / _get_financial_report_sina
- _push2his_kline_fallback
- _load_ohlcv_astock (cache 包装层)
- _fetch_news_eastmoney / _fetch_news_sina
- _fetch_hot_strategy_data
- _extract_limitup_codes (Markdown → dict 反解析)
- _batch_reverse_concept_blocks (百度 PAE 批量 + 0.5s sleep + per-day JSON cache)
- _northbound_cache_path / _save_northbound_snapshot / _load_northbound_history (本地 CSV 持久化北向)
- @dataclass(frozen=True) SectorRotationDigest (唯一领域 DTO)
```

### 1.2 指标计算层（133 LOC, 3.2%）

| 模块 | LOC | 角色 | DDD 等价 |
|---|---|---|---|
| `stockstats_utils.py` | 133 | `yf_retry()` 包装 yfinance 指数退避；`load_ohlcv()` 5 年窗口 + CSV cache + curr_date 过滤防 look-ahead bias；`StockstatsUtils.get_stock_stats()` 触发 stockstats indicator 计算 | **yfinance Repository + Indicator Calculator** |

**关键观察**：`stockstats_utils.py` **仍然依赖 yfinance**（`import yfinance as yf` + `from yfinance.exceptions import YFRateLimitError`），但 `interface.py` 的 `VENDOR_METHODS["get_indicators"]["yfinance"]` 指向 `get_stock_stats_indicators_window`（这是 TauricResearch 上游的旧实现），而 `_load_ohlcv_astock()` 才是 A 股指标的实际数据源。**当前 A 股指标的真实路径是 `a_stock.get_indicators()` → `_load_ohlcv_astock()` → mootdx CSV cache**，完全绕过 `stockstats_utils.py`。`stockstats_utils.py` 是 **死代码**（仅在 `interface.py` yfinance 分支被引用）。

### 1.3 第三方 vendor 层（532 + 618 LOC = 1150 LOC, 27.2%）

| 模块 | LOC | 角色 | DDD 等价 |
|---|---|---|---|
| `y_finance.py` | 421 | `get_YFin_data_online` / `get_stock_stats_indicators_window` / `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` / `get_insider_transactions` | **yfinance Repository**（upstream 继承，**死代码**） |
| `yfinance_news.py` | 197 | `get_news_yfinance` / `get_global_news_yfinance` | **yfinance News Repo**（**死代码**） |
| `alpha_vantage.py` | 4 | re-export 分发 | （**死代码**） |
| `alpha_vantage_common.py` | 122 | `_make_api_request` + AlphaVantageRateLimitError + `_filter_csv_by_date_range` | AV HTTP 客户端 |
| `alpha_vantage_stock.py` | 37 | `get_stock` | AV Repository |
| `alpha_vantage_fundamentals.py` | 55 | `get_fundamentals` / `get_balance_sheet` / `get_cashflow` / `get_income_statement` | AV Repository |
| `alpha_vantage_indicator.py` | 222 | `get_indicator`（12 种技术指标） | AV Repository |
| `alpha_vantage_news.py` | 70 | `get_news` / `get_global_news` / `get_insider_transactions` | AV Repository |

**关键观察**：CLAUDE.md 明确写 "v0.2.5 全部直连 HTTP，零第三方数据库依赖"，但 yfinance + alpha_vantage 共 1150 LOC 还在仓库。`interface.py` 通过 `VENDOR_METHODS` 字典把它们作为 vendor 选项保留：
- `route_to_vendor()` 默认 fallback 到 `VENDOR_METHODS[method]` 所有可用 vendor
- 仅 `AlphaVantageRateLimitError` 触发 fallback（line 237-238），其他 Exception 直接 propagate
- 当 `default_config.DATA_VENDORS["core_stock_apis"] = "a_stock"` 时，yfinance/alpha_vantage 分支永远不会触发

**结论**：7 个第三方 vendor 模块是 **legacy debt**，需要移到 `_deprecated/` 或 `docs/legacy/`。当前在 import 时还会拉起 `import yfinance as yf` / `import requests` / `pandas_datareader` 等重型依赖，拖慢冷启动。

### 1.4 接口 / 适配器层（239 LOC, 5.7%）

| 模块 | LOC | 角色 | DDD 等价 |
|---|---|---|---|
| `interface.py` | 239 | `TOOLS_CATEGORIES` 5 大类、`VENDOR_LIST` 3 vendor、`VENDOR_METHODS` 字典（19 个 tool × 最多 3 vendor）、`route_to_vendor()` 带 vendor fallback | **Vendor Router / Application Service** |

`route_to_vendor(method, *args, **kwargs)` 实现：
```python
vendor_config = get_vendor(category, method)
primary_vendors = [v.strip() for v in vendor_config.split(',')]

# Build fallback chain: primary vendors first, then remaining available vendors
fallback_vendors = primary_vendors.copy()
for vendor in all_available_vendors:
    if vendor not in fallback_vendors:
        fallback_vendors.append(vendor)

for vendor in fallback_vendors:
    if vendor not in VENDOR_METHODS[method]:
        continue
    impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl
    try:
        return impl_func(*args, **kwargs)
    except AlphaVantageRateLimitError:
        continue  # Only rate limits trigger fallback
```

**关键观察**：
- fallback **只对 AlphaVantageRateLimitError 生效**，普通 Exception 直接冒泡 → 调用方要么拿到结果要么看到 traceback
- 没有 timeout / circuit-breaker / retry —— 一个 vendor 卡 60s 会阻塞整个 LangGraph 节点
- **没有缓存层在 vendor router 里** —— 缓存下沉到具体 vendor 实现（`_load_ohlcv_astock` 用 `~/.tradingagents/cache/{code}-astock-daily.csv`；`_batch_reverse_concept_blocks` 用 `sector_rotation_concept_v1.json`；`_save_northbound_snapshot` 用 `northbound_daily.csv`）

### 1.5 工具层（80 LOC, 1.9%）

| 模块 | LOC | 角色 | DDD 等价 |
|---|---|---|---|
| `utils.py` | 80 | `safe_ticker_component()` 路径安全校验 + 中文 ticker 自动解析 → `resolve_ticker`；`save_output()` / `get_current_date()` / `decorate_all_methods()` / `get_next_weekday()` | **Input Validator / Anti-Corruption（输入侧）** |

`safe_ticker_component()`（line 20-47）是**全仓库唯一显式 ACL**：
```python
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^]+$")
_HAS_CHINESE_RE = re.compile(r"[一-鿿]")

def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    # 1. 中文 ticker → 自动 resolve_ticker() 转 6 位代码
    # 2. max_len 32 chars（防 DOS via 长字符串）
    # 3. regex 校验只允许 [A-Za-z0-9._-^]（防路径穿越 ../../../tmp）
    # 4. 不允许全点
```

**调用方审计**：
- `a_stock.py` 5 处使用：`safe_ticker_component(ticker)` for `get_dragon_tiger_board` / `get_lockup_expiry` / `get_industry_comparison`
- `stockstats_utils.py:57` `safe_symbol = safe_ticker_component(symbol)` 在 `load_ohlcv()` 第一行
- **问题**：其他 36 个 a_stock.py 函数（如 `get_concept_blocks` / `get_fund_flow` / `get_hot_stocks` 等）**直接调用 `_normalize_ticker`**，没有走 `safe_ticker_component`。这两个函数功能**部分重叠但不等价**——`_normalize_ticker` 只 strip exchange prefix/suffix，不做路径校验。

### 1.6 配置层（31 LOC, 0.7%）

| 模块 | LOC | 角色 | DDD 等价 |
|---|---|---|---|
| `config.py` | 31 | `_config` 单例 + `initialize_config()` / `set_config()` / `get_config()` 委托给 `default_config.DEFAULT_CONFIG` | **Config Provider** |

### 1.7 `__init__.py` — 空模块（0 LOC）

`tradingagents/dataflows/__init__.py` 是空文件，没有 `__all__`、没有公共 API re-export。Agent 必须直接 `from tradingagents.dataflows.a_stock import get_stock_data` 这种**深度路径 import**，破坏 DDD 模块边界。

---

## 2. 10 个外部数据源（CLAUDE.md 列的）

按 `a_stock.py` 代码实际 URL + 协议 + timeout + fallback + 限流梳理（基于逐行 grep + read）：

### 2.1 详情表（11 个，含同花顺 + 百度 PAE）

| # | 数据源 | 协议 | URL / 端口 | 数据类型 | a_stock.py 函数 | 调用频率 | 失败 fallback | 限流 |
|---|---|---|---|---|---|---|---|---|
| 1 | **mootdx** | TCP | `110.41.147.114:7709` (深圳双线主站1) | K线 / 财报 / F10 文本 | `_get_mootdx_client` (singleton) + `client.bars/finance/F10` in `_load_ohlcv_astock`/`get_fundamentals`/`get_insider_transactions` | 每次 LangGraph run 调一次（lazy init 4s 超时，后续复用 TCP） | `_sina_kline_fallback` → `_push2his_kline_fallback` | **TCP 连接复用**，限流不严苛；`ThreadPoolExecutor(8s)` 硬超时（v0.4.0+ fix mootdx 挂死问题） |
| 2 | **腾讯财经** | HTTP | `https://qt.gtimg.cn/q=sh600519,sz000001` | 实时行情 PE/PB/市值/换手率 | `_tencent_quote` | 每次 `get_fundamentals` 1 次（部分场景 2 次 fwd PE 计算） | 无（PE/PB 缺失 Agent 看到 `0.0`） | **无显式限流**；实测稳定但 `urllib.request` timeout=10s |
| 3 | **东方财富 datacenter** | HTTP | `https://datacenter-web.eastmoney.com/api/data/v1/get` | 龙虎榜 / 解禁 / 板块 | `_eastmoney_datacenter` (`report_name=RPT_DAILYBILLBOARD_DETAILSNEW/RPT_BILLBOARD_DAILYDETAILSBUY/RPT_BILLBOARD_DAILYDETAILSSELL/RPT_LIFT_STAGE`) | 每次 `get_dragon_tiger_board` 调 3 次（主表 + 买席位 + 卖席位）+ `get_lockup_expiry` 调 2 次（历史 + 未来） | 无（datacenter 不在 _em_get 节流对象里，line 252 `_DATACENTER_URL` 也走 _em_get；但仅 datacenter-web 一个 host） | `_em_get` 节流 1.0s + 0.1-0.5s 抖动 |
| 4 | **东方财富 push2** | HTTP | `https://push2.eastmoney.com/api/qt/stock/get` + `clist/get` + `fflow/kline/get` | 实时行情 / 个股信息 / 行业排名 / 资金流 | `get_fundamentals` line 822 (个股信息) + `get_industry_comparison` line 2162 (clist) + `get_fund_flow` line 1842 (fflow) | 每次 `get_fundamentals` 调 1 次；`get_fund_flow` 调 2 次（realtime + history） | 无（push2 同 datacenter 都是 eastmoney 系，理论上都需要 _em_get） | `_em_get` 节流 1.0s + 0.1-0.5s 抖动 |
| 5 | **东方财富 push2his** | HTTP | `https://push2his.eastmoney.com/api/qt/stock/kline/get` + `fflow/daykline/get` | 历史 K 线 / 历史资金流 | `_push2his_kline_fallback` (v0.4.0+) + `get_fund_flow` 历史部分 line 1888 | 每次 `get_stock_data` 在 mootdx/sina 都失败时调 1 次；`get_fund_flow(include_history=True)` 调 1 次 | 无（push2his 是 K 线最终 fallback） | `_em_get` 节流 1.0s + 0.5s 抖动 |
| 6 | **东方财富 np-weblist** | HTTP | `https://np-weblist.eastmoney.com/comm/web/getFastNewsList` (`biz=web_724`, `fastColumn=102`) | 全球财经 7×24 快讯 | `get_global_news` line 1283 | 每次 `get_global_news` 1 次 | 无（CLS 已失败则用 np-weblist 替补；np-weblist 也失败返回空） | `_em_get` 节流 1.0s |
| 7 | **东方财富 np-ipick** | HTTP | `https://np-ipick.eastmoney.com/recommend/stock/heat/ranking` (`biz=web_smart_tag`) | 选股热度排名 | `_fetch_hot_strategy_data` line 2241 | 每次 `get_sector_rotation_digest` 调 1 次 | 无（digest 标注 `[数据缺失: np-ipick]`） | `_em_get` 节流 1.0s |
| 8 | **东方财富 search-api** | HTTP | `https://search-api-web.eastmoney.com/search/jsonp` (callback) | 个股滚动新闻 | `_fetch_news_eastmoney` line 1084 | 每次 `get_news` 1 次 | `_fetch_news_sina` (新浪财经 fallback) | `_em_get` 节流 1.0s |
| 9 | **新浪财经** | HTTP | `http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData` + `https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022` + `https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php` | K线 fallback / 财报三表 / 滚动新闻 | `_sina_kline_fallback` + `_get_financial_report_sina` + `_fetch_news_sina` | 每次 `get_stock_data` 在 mootdx 失败后 1 次；`get_balance_sheet/cashflow/income_statement` 各 1 次；`get_news` 在 Eastmoney 失败后 1 次 | 无（kline 还会 fallback 到 push2his） | **无显式限流**；`_requests.get(timeout=15)` |
| 10 | **同花顺 10jqka** | HTTP | `https://basic.10jqka.com.cn/new/{code}/worth.html` + `http://zx.10jqka.com.cn/event/api/getharden/date/{date}` + `https://data.hexin.cn/market/hsgtApi/method/dayChart/` | EPS 一致预期 / 涨停归因 / 北向资金分钟级 | `_ths_eps_forecast` (pd.read_html) + `get_hot_stocks` + `get_northbound_flow` | `get_fundamentals` / `get_profit_forecast` 各 1 次；`get_sector_rotation_digest` 调 1 次 get_hot_stocks；`get_northbound_flow` 1 次 | 无（EPS 一致预期在 v0.5.0+ 偶尔 401 → `get_industry_comparison` 迁移到 push2） | **无显式限流**；`requests.get(timeout=10)` / `timeout=15` |
| 11 | **财联社 cls.cn** | HTTP | `https://www.cls.cn/nodeapi/telegraphList?rn=20&page=1` | 全球财经快讯（电报） | `get_global_news` line 1256 | 每次 `get_global_news` 1 次 | np-weblist 东财 7×24 替补 | **无显式限流**；`requests.get(timeout=10)` |
| 12 | **百度股市通 PAE** | HTTP | `https://finance.pae.baidu.com/api/getrelatedblock?stock=...` (`Host: finance.pae.baidu.com`) | 个股所属概念/行业/地域 | `get_concept_blocks` + `_batch_reverse_concept_blocks` (per-stock + 0.5s sleep + batch_size=10) | `get_concept_blocks` 1 次；`get_sector_rotation_digest` 调 1 次 `_batch_reverse_concept_blocks`（top_n=20 → 2 个 batch + 1 个 0.5s sleep） | 无（v0.2.7 资金流已从百度迁移到东财 push2） | **无显式限流**；`requests.get(timeout=15)` |

### 2.2 防封限流统一架构

`a_stock.py:265-287` 模块级全局节流器：

```python
_EM_SESSION = _requests.Session()
_EM_SESSION.headers.update({"User-Agent": _UA})
_EM_MIN_INTERVAL = float(os.environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call = [0.0]

def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()
```

**注释（line 256-264）解释设计动机**：

> 东财系 HTTP 接口（push2 / push2his / datacenter-web / search-api / np-weblist）有风控：每秒 >5 次 / 单 IP 并发 ≥10 / 1 分钟 ≥200 次 / 5 分钟 ≥300 次 → 临时封 IP。
> 多 Agent 投研跑批量分析时会高频请求东财，是被封的头号元凶。所有 eastmoney.com 请求一律走 `_em_get()`：串行限流（最小间隔 + 随机抖动）+ 复用 Keep-Alive 会话 + 默认 UA。
> 注意：仅东财接口走此入口；mootdx(TCP) / 腾讯 / 新浪 / 同花顺 / 财联社 / 百度 等**不限流（实测不封 IP 或风控极弱）**。批量任务可调大 `EM_MIN_INTERVAL` 进一步降速。

**所有走 `_em_get()` 的接口（共 6 个）**：

1. `_eastmoney_datacenter` → datacenter-web
2. `get_fundamentals` line 829 → push2 stock get
3. `_fetch_news_eastmoney` line 1116 → search-api-web
4. `get_global_news` line 1293 → np-weblist
5. `_fetch_hot_strategy_data` line 2253 → np-ipick
6. `get_fund_flow` line 1848/1897 → push2 fflow
7. `_push2his_kline_fallback` line 431 → push2his kline
8. `get_industry_comparison` line 2173 → push2 clist

---

## 3. Repository Pattern 视角

### 3.1 当前架构：自由函数 + Vendor Router

按 DDD 经典分层，基础设施层应该提供 **Repository 接口抽象**让领域层通过接口访问数据。但当前 `tradingagents/dataflows/` 是**自由函数 + Vendor 路由**：

```python
# Agent 层 (signal_data_tools.py:181-208) 直接调用 route_to_vendor
@tool
def get_sector_rotation_digest(curr_date, top_n=20) -> str:
    digest = route_to_vendor("get_sector_rotation_digest", curr_date, top_n)
    if hasattr(digest, "markdown"):
        return digest.markdown
    return str(digest)
```

```python
# interface.py:212-240 route_to_vendor 按 method name 分发
def route_to_vendor(method: str, *args, **kwargs):
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]
    # ... fallback chain only on AlphaVantageRateLimitError
```

**问题诊断**：

1. **无 Protocol / ABC / Dataclass 抽象**——`VENDOR_METHODS` 是 `dict[str, dict[str, Callable]]`，没有任何类型约束保证 `a_stock.get_stock_data` 和 `yfinance.get_YFin_data_online` 签名一致。Agent 看到的只有 `@tool` 装饰器签名。
2. **Vendor router 不做 timeout / circuit-breaker**——一个 vendor 卡 60s 会让 LangGraph 节点 hang 60s；AlphaVantageRateLimitError 之外的 Exception 直接 propagate。
3. **Vendor router 不做缓存**——缓存下沉到 `a_stock._load_ohlcv_astock` / `_batch_reverse_concept_blocks` / `_save_northbound_snapshot` 3 处，3 套不同的 cache key / TTL 策略。

### 3.2 3-fallback K 线 Repository 应该的形态

`a_stock.py:537-675 get_stock_data()` 是当前最复杂的 vendor 链。代码结构（v0.4.0 + sina/push2his fallback 之后）：

```python
def get_stock_data(symbol, start_date, end_date) -> str:
    code = _normalize_ticker(symbol)
    data_source = "mootdx (TCP)"

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeoutError

    def _mootdx_call(code_):
        client = _get_mootdx_client()
        if client is None:
            raise RuntimeError("mootdx unavailable")
        df_local = client.bars(symbol=code_, category=4, offset=800)
        return client, df_local

    _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mootdx")
    _future = _executor.submit(_mootdx_call, code)
    try:
        try:
            client, df = _future.result(timeout=8)
            # ... 解析 mootdx 返回 ...
        except _FutTimeoutError:
            # Fallback 1: Sina
            try:
                df = _sina_kline_fallback(code, start_date, end_date)
                data_source = "sina HTTP (fallback)"
            except Exception as e1:
                # Fallback 2: push2his
                try:
                    df = _push2his_kline_fallback(code, start_date, end_date)
                    data_source = "push2his HTTP (fallback)"
                except Exception as e2:
                    return "K线数据获取失败：mootdx/sina/push2his 均不可用..."
        except Exception as e:
            # Fallback 1: Sina (duplicate block)
            try:
                df = _sina_kline_fallback(code, start_date, end_date)
                data_source = "sina HTTP (fallback)"
            except Exception as e1:
                # Fallback 2: push2his (duplicate block)
                try:
                    df = _push2his_kline_fallback(code, start_date, end_date)
                    data_source = "push2his HTTP (fallback)"
                except Exception as e2:
                    return "K线数据获取失败：mootdx/sina/push2his 均不可用..."
    finally:
        _executor.shutdown(wait=False)

    # Filter by date range + format CSV
    # ...
```

**代码问题**：

- **嵌套 try/except + 重复代码 50+ 行**（v0.4.0 添 push2his 时复制了 2 段 fallback block 而不是抽取 helper）
- **没有抽象成 Repository 协议**——`mootdx → sina → push2his` 三段硬编码在 `get_stock_data()` 函数体内，无法配置顺序、无法在 runtime 跳过 mootdx（如 batch 场景已知 mootdx 挂了）
- **没有 timeout 统一管理**——mootdx 8s、sina 15s、push2his 15s 分散在 3 个函数体里

**理想 Repository 抽象（DDD 风格）**：

```python
# 假设的 refactor — 不在当前代码里，仅作 DDD 战术示范
from typing import Protocol
from datetime import date

class OhlcvBar(NamedTuple):
    """领域 value object — 替代 pd.DataFrame 暴露"""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int

class IOhlcvRepository(Protocol):
    """K 线数据 Repository 接口"""
    def get_ohlcv(
        self, ticker: str, start: date, end: date
    ) -> list[OhlcvBar]:
        ...

class MootdxOhlcvRepository:
    """P0 — TCP 7709 主路径"""
    TIMEOUT = 8.0
    def get_ohlcv(self, ticker, start, end) -> list[OhlcvBar]:
        ...

class SinaOhlcvRepository:
    """P1 — HTTP fallback"""
    TIMEOUT = 15.0
    def get_ohlcv(self, ticker, start, end) -> list[OhlcvBar]:
        ...

class Push2HisOhlcvRepository:
    """P2 — HTTP second fallback"""
    TIMEOUT = 15.0
    def get_ohlcv(self, ticker, start, end) -> list[OhlcvBar]:
        ...

class FallbackChainOhlcvRepository:
    """组合 3 段 fallback，可配置顺序、可跳段、可注入 mock"""
    def __init__(self, repos: list[IOhlcvRepository], priority: list[int] = None):
        self.repos = repos
        self.priority = priority or list(range(len(repos)))
    def get_ohlcv(self, ticker, start, end) -> list[OhlcvBar]:
        last_err = None
        for idx in self.priority:
            try:
                return self.repos[idx].get_ohlcv(ticker, start, end)
            except Exception as e:
                last_err = e
                logger.warning(f"OHLCV repo #{idx} failed: {e}")
        raise AllOhlcvSourcesFailed(last_err)
```

这样的 Repository 抽象可以：
- 让 Agent 层只依赖 `IOhlcvRepository` 接口 + `OhlcvBar` value object，**完全不知道 mootdx / sina / push2his 的存在**
- 让 fallback 链可配置（环境变量 / DI 容器），不需要改代码
- 让测试可以注入 mock repository，不需要走 TCP / HTTP
- 让 ACL 把 `pd.DataFrame` 翻译成 `list[OhlcvBar]`，彻底切断 pandas 泄漏

---

## 4. Anti-Corruption Layer (ACL) 视角

### 4.1 现状：ACL 几乎不存在

按 DDD，ACL 的职责是：
1. 把外部系统的**协议**（HTTP/TCP/JSON/CSV）翻译成**领域语言**（value object / aggregate）
2. 把外部系统的**术语**（datacenter-web 的 `RPT_DAILYBILLBOARD_DETAILSNEW` 报告名）翻译成**领域概念**（DragonTigerListing）
3. 隔离外部 schema 变化对领域层的影响

当前 `tradingagents/dataflows/` 的 ACL 几乎为零：

| ACL 应做 | 当前实现 | 缺口 |
|---|---|---|
| 把 OHLCV DataFrame 翻译成 `OhlcvBar` value object | 返回 `str` (CSV) 或 `pd.DataFrame` | **Agent 必须知道列名 `Date/Open/High/Low/Close/Volume`** 才能解析；mootdx 返回的列名是中文 `datetime/year/month/day/hour/minute`，需要 `df.rename(columns={"datetime": "Date", ...})` 翻译，但没有抽象成 OhlcvBar |
| 把龙虎榜 raw dict 翻译成 `DragonTigerListing` 聚合 | 返回 `str`（格式化 Markdown） | **Agent 必须 regex 解析字符串**；`row.get('TRADE_DATE', '')[:10]` 这种隐式字符串切片是 ACL 缺失的副作用 |
| 把 EPS 预期翻译成 `ConsensusEpsForecast` value object | 返回 `str`（多行 Markdown + 数字） | **Agent 必须用 `_re.match` 反向解析**才能拿 `fwd_pe`；`_ths_eps_forecast()` 返回 `pd.DataFrame` 但调用方在 `get_fundamentals` 里手工 `row.iloc[0] / iloc[1] / iloc[2] / iloc[3] / iloc[4]` 取数（line 853-873）|
| 把新闻 article 翻译成 `NewsItem` value object | 返回 `list[dict]` (title/content/time/source/url) | **部分翻译**：调用方拿到 dict 还是要用 `art["title"]` / `art.get("content", "")` 取字段，没有领域类型 |
| 把财务报告 (balance sheet / cashflow / income) 翻译成领域报表对象 | 返回 `pd.DataFrame` (raw sina columns) | **完全无翻译**：sina 列名是中文 `报告日/每股收益/...`，Agent 必须知道 pandas 操作才能正确 slice |

### 4.2 唯一例外：`SectorRotationDigest`

`a_stock.py:2211-2232` 是**全仓库唯一显式 ACL 输出**：

```python
@dataclass(frozen=True)
class SectorRotationDigest:
    """Structured output of get_sector_rotation_digest.

    Attributes:
        hot_strategies: Top-N hot stock-picking strategies from np-ipick
        hot_stocks: Top-N same-day limit-up stocks from 同花顺
        concept_blocks: Map of concept-block-name -> list of limit-up stocks
        markdown: Pre-rendered Markdown digest for direct UI/human consumption
        sources_ok: Map of source-name -> bool indicating partial failures
    """
    hot_strategies: list[dict]
    hot_stocks: list[dict]
    concept_blocks: dict[str, list[dict]]
    markdown: str
    sources_ok: dict[str, bool]
```

**正面观察**：
- `sources_ok` 字段是**显式的 partial-failure 协议**——3 个数据源独立 track 成功/失败，让调用方能区分"全失败" vs "部分失败"
- `markdown` + `hot_strategies` / `hot_stocks` / `concept_blocks` 双输出——结构化字段给程序消费，markdown 给人/UI 消费
- `frozen=True` 强制不可变，避免下游误改

**负面观察**：
- 内部字段还是 `list[dict]` / `dict[str, list[dict]]`——**dict 是 "no ACL" 的同义词**，调用方还是要知道 `dict["code"]` / `dict["name"]` / `dict["ratio"]` 这些 key
- `hot_stocks` 字段是 `_extract_limitup_codes(thh_md)[:top_n]` 的输出——**先把 dict → markdown → dict 反向解析**，浪费 1 次循环

### 4.3 子 agent P2.23 Portfolio Manager "structured-output invocation failed" 问题的同类

子 agent 之前发现 `portfolio_manager.py` 用 `llm.with_structured_output(...)` 解析 LLM 输出失败——根因是 **prompt 期待结构化输出但 Agent 实际拿到 `str` (格式化 Markdown)**。

`tradingagents/dataflows/` 的 41 个函数里有 **39 个返回 `str`**（格式化 Markdown），让所有 Analyst Agent 必须 regex / string-split 解析，这是 ACL 缺失导致的**系统性耦合问题**。

---

## 5. 失败 / Fallback / Timeout 矩阵

### 5.1 11 个数据源 × 4 维度矩阵

| 数据源 | Timeout | Fallback | 重试 | 缓存 |
|---|---|---|---|---|
| **mootdx** | `_get_mootdx_client` 4s (factory) + `get_stock_data` 8s (bars call) | `_sina_kline_fallback` → `_push2his_kline_fallback` | 无（v0.4.0+ fix mootdx 挂死，引入 8s 硬超时避免重试浪费） | `_load_ohlcv_astock` 同日缓存到 `~/.tradingagents/cache/{code}-astock-daily.csv`（24h TTL） |
| **腾讯财经** | 10s (`urllib.request.urlopen`) | 无 | 无 | 无 |
| **东方财富 datacenter** | 15s (`_em_get`) | 无（datacenter-web 单点失败就失败） | 无 | 无 |
| **东方财富 push2** | 10s / 15s (`_em_get`) | 无（push2 单点失败就失败，Agent 看到空字段） | 无 | 无 |
| **东方财富 push2his** | 15s (`_em_get`) | 无（push2his 是 K 线最终 fallback，无 4th 层） | 无 | 无 |
| **东方财富 np-weblist** | 10s (`_em_get`) | 无（CLS 已失败则 np-weblist 替补；都失败返回空） | 无 | 无 |
| **东方财富 np-ipick** | 15s (`_em_get`) | 无（`sources_ok["np_ipick"] = False`，markdown 标注 `[数据缺失: np-ipick]`） | 无 | 无 |
| **东方财富 search-api** | 15s (`_em_get`) | `_fetch_news_sina` (新浪财经 fallback) | 无 | 无 |
| **新浪财经 kline** | 15s (`_requests.get`) | `_push2his_kline_fallback` | 无 | 无 |
| **新浪财经 财报三表** | 15s (`_requests.get`) | 无（财报失败 Agent 看到 "No balance sheet data found"） | 无 | 无 |
| **新浪财经 news** | 15s (`_requests.get`) | 无（Eastmoney news 失败时 fallback 到 sina news；sina news 也失败则返回空） | 无 | 无 |
| **同花顺 EPS worth.html** | 15s (`_requests.get`) | 无（pd.read_html 找不到表格返回空 DataFrame，Agent 看到 "No analyst coverage found"） | 无 | 无 |
| **同花顺 zx 涨停** | 10s (`requests.get`) | 无（`data.get("errocode", 0) != 0` 检查，无 fallback） | 无 | 无 |
| **同花顺 hexin 北向** | 10s (`requests.get`) | 无（失败返回 "Error fetching northbound flow: ..."） | 无 | 本地 CSV `northbound_daily.csv`（累积历史快照，无显式 TTL） |
| **财联社 cls.cn** | 10s (`_requests.get`) | 无（np-weblist 替补在 np-weblist 部分；CLS 自身失败直接返回 empty news list） | 无 | 无 |
| **百度 PAE getrelatedblock** | 10s / 15s (`requests.get`) | 无（v0.2.7 资金流已迁出百度；只剩概念归属唯一来源） | 无 | `_batch_reverse_concept_blocks` 同日缓存到 `sector_rotation_concept_v1.json`（24h TTL） |

### 5.2 缓存策略审计

`a_stock.py` 共有 **3 套独立的缓存**，每套 key / TTL / 失效策略都不一样：

| Cache | 路径 | Key | TTL | 失效策略 |
|---|---|---|---|---|
| OHLCV daily CSV | `~/.tradingagents/cache/{code}-astock-daily.csv` | 6 位代码 | **同日**（mtime.date() == today 才用 cache） | mtime 检查；mootdx 拉一次写一次，sina fallback 也写 |
| Northbound daily CSV | `~/.tradingagents/cache/northbound_daily.csv` | date 列 | **累积**（无 TTL） | 按 date dedup，每次成功 fetch 追加当天快照 |
| Sector rotation concept JSON | `~/.tradingagents/cache/sector_rotation_concept_v1.json` | stock code 列表 | **同日**（`date == today and stocks == [...]` 才用 cache） | date + stock list 同时检查 |

**问题**：
- 3 套 cache 路径都在 `data_cache_dir` 同一个根下，但**没有任何统一的 cache manager**——过期清理、磁盘配额、跨 ticker 失效全靠手工
- `northbound_daily.csv` 是累积型，没有上限——长期运行可能无限增长
- `OHLCV cache` 是同日型，但**没有考虑早盘 / 收盘后数据更新**——一个交易日结束 mootdx 已经返回完整 OHLCV，第二天启动还可能重新拉一次

### 5.3 Timeout 总结

| 维度 | 实现 | 评价 |
|---|---|---|
| 显式 timeout | `_em_get(url, params, headers, timeout=15)`；mootdx `ThreadPoolExecutor(max_workers=1).result(timeout=8)`；`urllib.request.urlopen(timeout=10)`；`requests.get(timeout=10/15)` | **分散在 30+ 个调用点**，没有统一的 timeout policy |
| 硬超时（线程级） | mootdx 8s（解决 mootdx 内部 retry 吞 SIGALRM 的 bug） | **唯一显式硬超时**，其他都是 HTTP 库 timeout——HTTP 库 timeout 在 keep-alive 复用时可能不触发 |
| Fallback 触发条件 | AlphaVantageRateLimitError 触发（仅 AV）；其他 Exception propagate 或 `except Exception: pass` 吞掉 | **不一致**：a_stock.py 大量 `except Exception: pass` 静默吞错，导致上游根本不知道某段失败 |
| 重试 | `yf_retry` 包装 yfinance（`max_retries=3, base_delay=2.0` 指数退避）；a_stock.py **完全没有重试** | **重试只在 stockstats_utils 死代码里**，A 股路径 0 重试 |
| Circuit breaker | 无 | 长跑批量任务时，一个数据源挂掉会让所有后续请求持续卡到 timeout |

---

## 6. 限流 (Rate Limit) 风险

### 6.1 显式限流：仅 eastmoney.com

`_em_get()` 是**全模块唯一显式限流入口**：
- 最小间隔 `_EM_MIN_INTERVAL` 默认 1.0s（环境变量可调到 1.5-2.0s）
- 随机抖动 `random.uniform(0.1, 0.5)`
- 单例 Session（Keep-Alive 复用）
- 默认 UA `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36`

覆盖 **6 个 host**（datacenter-web / push2 / push2his / np-weblist / np-ipick / search-api-web）的 eastmoney.com 子域。

### 6.2 无显式限流的 5 类数据源

| 数据源 | 限流策略 | 风险 |
|---|---|---|
| **mootdx TCP** | 单例连接复用 + 4s/8s 硬超时 | **低风险**：TCP 长连接天然限流，mootdx 服务器端有连接数限制 |
| **腾讯财经 qt.gtimg.cn** | 无 | **中风险**：批量 ticker 单次请求最多 80 个（实测 URL 长度限制），但高频 IP 可能被 503 |
| **新浪财经 money.finance.sina / vip.stock.finance.sina / quotes.sina** | 无 | **高风险**：v0.4.0+ 才成为 mootdx fallback，高频调用可能触发 sina 反爬 |
| **同花顺 10jqka / hexin** | 无 | **中风险**：v0.5.0+ `basic.10jqka.com.cn` 偶尔 401 → 已有迁移到 push2 的方案（`get_industry_comparison` v0.5.0+ 改 push2 clist）；但 `zx.10jqka.com.cn` + `data.hexin.cn` 仍是裸 HTTP |
| **财联社 cls.cn** | 无 | **高风险**：财联社非公开 API，可能随时改 cookie / 加 referer 校验；当前裸 `requests.get` 没有 cookie 管理 |
| **百度 PAE finance.pae.baidu.com** | `_batch_reverse_concept_blocks` 内 **0.5s sleep between batches**（line 2355, 2427） | **中风险**：仅在 batch 场景手动 sleep；`get_concept_blocks` 单股票场景无 sleep |

### 6.3 CLAUDE.md "v0.2.11 补齐限流防封说明"

按 CLAUDE.md 记录，v0.2.11 补齐了限流防封说明。当前的实现状态：
- ✅ **东财系统一节流**（`_em_get` 1.0s + 抖动）
- ✅ **mootdx 硬超时**（8s ThreadPoolExecutor）
- ✅ **百度 PAE batch sleep**（0.5s between batches）
- ❌ **腾讯 / 新浪 / 同花顺 / 财联社 无显式限流**
- ❌ **retry with backoff**（仅 yf_retry 是死代码）
- ❌ **circuit breaker**
- ❌ **per-host rate limit 配置化**（仅 `_EM_MIN_INTERVAL` 1 个环境变量）

---

## 7. 现有架构债务（dataflows 层）

按代码现状列出 **7 条架构债务**，按严重程度排序：

### Debt #1 — 无 Repository 接口抽象（严重）

**症状**：41 个 `a_stock.py` 函数是模块级自由函数，没有 Protocol / ABC / dataclass 约束。Agent 必须直接 import 具体函数：
```python
# signal_data_tools.py:204 — Agent 写死了 vendor 路由名
digest = route_to_vendor("get_sector_rotation_digest", curr_date, top_n)
```

**根因**：`interface.py` 用 `dict[str, dict[str, Callable]]` (`VENDOR_METHODS`) 做 vendor 路由，没有任何类型契约。

**影响**：
- 测试必须 mock 整个 vendor 链，无法单独测试一个 Repository
- 替换 vendor（如迁移到付费 Tushare）需要改 Agent 代码
- LLM 工具描述（`Annotated[str, "..."]`）没有从接口生成，靠手工维护

**修复方向**：抽 `IStockDataRepository` Protocol + `IQuoteRepository` / `IFundamentalsRepository` / `INewsRepository` / `IFundFlowRepository` 等子接口（详见 §8 R1）。

### Debt #2 — 无 Anti-Corruption Layer（严重）

**症状**：41 个函数里 39 个返回 `str`（格式化 Markdown），2 个返回 `pd.DataFrame`。Agent 必须：
- regex 解析 Markdown（`hot_money_tracker` line 2486 `_re.match(r"\s*(\d+)\.\s+rank=(\S+)\s+heat=(\d+)\s+chg=([+-]?[\d.]+%)", line)`）
- 手工切片字符串（`str(row.get("TRADE_DATE", ""))[:10]`）
- 知道 pandas 列名（`df.rename(columns={"datetime": "Date", ...})`）

**根因**：a_stock.py 函数被设计成"直接给 LLM 看的格式化字符串"，把"格式化"和"数据访问"两个职责耦合在一起。

**影响**：
- 子 agent P2.23 Portfolio Manager structured-output 失败的同类问题
- Agent 无法做类型安全的领域操作（如 `quote.change_pct > 5` 写起来要 `float(vals[32]) > 5`）
- 外部 schema 变化（如 sina 改字段顺序）会直接破坏 Agent prompt 期望

**修复方向**：抽 `OhlcvBar` / `Quote` / `NewsItem` / `FinancialStatement` 等 value object + 让 Repository 返回这些对象 + 在 Agent 层做格式化（详见 §8 R2）。

### Debt #3 — 3-fallback K 线硬编码（中等）

**症状**：`get_stock_data()` (line 537-675) 内嵌嵌套 try/except + 重复 fallback block（v0.4.0+ 加 push2his 时复制了 2 段），mootdx → sina → push2his 顺序硬编码。

**根因**：fallback 链用控制流（嵌套 try/except）实现，没有抽象成数据（list of repositories）。

**影响**：
- 批量场景已知 mootdx 挂了，无法在 runtime 跳过 mootdx 段
- 添加第 4 段 fallback 需要改 `get_stock_data()` 函数体（v0.4.0+ 已扩到 50+ 行重复代码）
- 无法在测试中注入 mock repository

**修复方向**：抽 `FallbackChainOhlcvRepository` 组合对象（详见 §3.2 DDD 示范）。

### Debt #4 — 缓存策略不一致（中等）

**症状**：3 套独立 cache（OHLCV daily CSV / northbound daily CSV / sector rotation concept JSON），每套 key/TTL/失效策略都不一样。

**根因**：每个 cache 是单独函数自带的（`_load_ohlcv_astock` line 478 / `_save_northbound_snapshot` line 1585 / `_batch_reverse_concept_blocks` line 2375），没有统一的 cache manager。

**影响**：
- 缓存清理靠手工 `rm -rf ~/.tradingagents/cache/`
- 磁盘配额无管控
- 缓存失效策略散落（mtime check vs date check vs date+stocks check）

**修复方向**：抽 `Cache[T]` Protocol + `FileCacheBackend` + `TtlPolicy`（详见 §8 R4）。

### Debt #5 — 限流仅覆盖 eastmoney.com（中等）

**症状**：`_em_get()` 仅保护 6 个 eastmoney.com 子域；腾讯/新浪/同花顺/财联社/百度 PAE 全部裸 HTTP。

**根因**：a_stock.py 注释（line 256-264）声称"腾讯 / 新浪 / 同花顺 / 财联社 / 百度 等**不限流（实测不封 IP 或风控极弱）**"，但实际运维中：
- v0.5.0+ `basic.10jqka.com.cn` 偶尔 401 → 已迁到 push2
- 新浪 kline 反爬（User-Agent 验证 + referer 验证）逐渐加强
- 财联社 cls.cn 可能随时加 cookie

**影响**：
- 批量 7-Analyst LangGraph run 在某天同花顺挂掉时，全部 agent 卡死
- 没有 retry with backoff，单次失败就失败
- 没有 circuit breaker，无法跳过挂掉的源

**修复方向**：扩展限流到所有 HTTP 源 + 抽 `RateLimiter` Protocol + 抽 `RetryPolicy` + 抽 `CircuitBreaker`（详见 §8 R5）。

### Debt #6 — `_normalize_ticker` 跨层泄漏到 backend（轻微）

**症状**：
- `backend/core/portfolio_store.py:63` `from tradingagents.dataflows.a_stock import _normalize_ticker as _normalize_ticker`
- `backend/core/portfolio_import.py:29` `from tradingagents.dataflows.a_stock import _normalize_ticker`
- `backend/core/portfolio_calc.py:672` `from tradingagents.dataflows.a_stock import get_concept_blocks`

**根因**：backend 需要 ticker 标准化和 concept_blocks 数据，但不愿意走 `route_to_vendor`（多 1 层 vendor 路由开销）。

**影响**：
- backend 强耦合到 a_stock.py 的私有函数（`_normalize_ticker` 以下划线开头本应是私有）
- 私有 → 公有的破坏性修改风险（如 `get_concept_blocks` 改签名会让 portfolio_calc 静默坏）
- backend/api/chart.py:237 也直接 `from tradingagents.dataflows.a_stock import get_stock_data` 绕过 `route_to_vendor`

**修复方向**：把 `_normalize_ticker` 升级为 `normalize_ticker`（公开）+ 在 `backend/core` 也走 `route_to_vendor` 或显式 import 公开 API。

### Debt #7 — yfinance / alpha_vantage 第三方 vendor 死代码（轻微）

**症状**：CLAUDE.md 明确写 "v0.2.5 全部直连 HTTP，零第三方数据库依赖"，但 7 个 vendor 文件（y_finance / yfinance_news / alpha_vantage / alpha_vantage_common / alpha_vantage_fundamentals / alpha_vantage_indicator / alpha_vantage_news / alpha_vantage_stock）共 1150 LOC 仍在 `tradingagents/dataflows/` 占位。

**根因**：v0.2.5 是"运行时零依赖"，但 vendor 选项还保留作为"理论上可切换"的扩展点。

**影响**：
- `interface.py` import 全部 3 个 vendor 时会触发 `import yfinance as yf` / `import pandas_datareader` 等重型依赖，冷启动慢
- `stockstats_utils.py` 仍依赖 yfinance（line 5 `import yfinance as yf` + line 6 `from yfinance.exceptions import YFRateLimitError`），但实际 A 股指标计算完全绕过它
- `VENDOR_METHODS` 字典里 yfinance / alpha_vantage 分支永远不会触发（`default_config.DATA_VENDORS` 全是 `"a_stock"`）

**修复方向**：移 yfinance / alpha_vantage 到 `_deprecated/` 或 `docs/legacy/`，保留 `interface.py` 的 vendor 抽象但移除具体实现（详见 §8 R6）。

---

## 8. 重构建议（按 ROI 排序）

### 8.1 短期（1-2 周，单 PR 可完成）

**R1 — 抽 `IOhlcvRepository` Protocol + 3-fallback 组合对象**（优先级 ★★★★★）

- 新增 `tradingagents/dataflows/repositories/base.py`：
  - `class OhlcvBar(NamedTuple)` value object（替代 `pd.DataFrame` 暴露）
  - `class IOhlcvRepository(Protocol)`：`get_ohlcv(ticker, start, end) -> list[OhlcvBar]`
  - `class FallbackChainOhlcvRepository`：`__init__(repos, priority)` + 内部循环 try
- 把 `_load_ohlcv_astock` / `_sina_kline_fallback` / `_push2his_kline_fallback` 重构为 3 个 Repository 实现
- 保留旧 `get_stock_data()` 函数作为 facade（不改 Agent 调用方）

**收益**：Debt #1 + Debt #2 + Debt #3 同时修复；测试可注入 mock；4th fallback 加新数据源不需要改 `get_stock_data`。

**R2 — 抽领域 value object（替代 `pd.DataFrame` / `str` 暴露）**（优先级 ★★★★☆）

- `Quote(NamedTuple)`：`price, pe_ttm, pb, mcap_yi, change_pct, turnover_pct, ...`
- `NewsItem(NamedTuple)`：`title, content, time, source, url`
- `FinancialStatement(NamedTuple)`：`report_date, items: dict[str, float]`
- `ConceptBlock(NamedTuple)`：`name, change_pct, desc`
- `FundFlowSnapshot(NamedTuple)`：`date, main_net, large_net, mid_net, small_net, super_net`

**收益**：Debt #2 主线修复；Agent 可以做类型安全操作；外部 schema 变化只影响 Repository 实现。

**R3 — 修 `hot_money_tracker` tool drift**（优先级 ★★★☆☆）

子 agent 之前发现 `hot_money_tracker.py` 引用 `get_sector_rotation_digest` 但 `TradingAgentsGraph` 没有显式注册它。验证当前状态：

- `tradingagents/agents/utils/agent_utils.py:31` ✅ import 了 `get_sector_rotation_digest`
- `tradingagents/agents/analysts/hot_money_tracker.py:13` ✅ import 了
- `tradingagents/agents/analysts/hot_money_tracker.py:27` ✅ 加入 `tools` 列表
- `tradingagents/graph/setup.py:87-92` ✅ `analyst_nodes["hot_money"] = create_hot_money_tracker(...)` + `tool_nodes["hot_money"] = self.tool_nodes["hot_money"]`

**结论**：当前 `hot_money_tracker` 节点已经包含 `get_sector_rotation_digest` 工具，**Debt #6（之前子 agent 报告的 tool drift）已修复**。本建议撤销，标 ✅。

### 8.2 中期（2-4 周，多 PR）

**R4 — 统一缓存层**（优先级 ★★★★☆）

- 抽 `class Cache[T](Protocol)`：`get(key) -> T | None` + `set(key, value, ttl)` + `invalidate(key)`
- 抽 `FileCacheBackend`：`root_dir, serializer, deserializer`
- 把 3 套分散 cache（OHLCV / northbound / sector rotation）迁移到统一 cache manager
- 加 `Cache.cleanup_expired()` 定期清理

**收益**：Debt #4 修复；缓存策略可配置；磁盘配额可管控。

**R5 — 限流策略扩展到所有 HTTP 源**（优先级 ★★★★☆）

- 抽 `class RateLimiter(Protocol)`：`acquire()` 阻塞到下次允许
- 抽 `class RetryPolicy(Protocol)`：`execute(func) -> result` 带指数退避
- 抽 `class CircuitBreaker(Protocol)`：`state: closed/half-open/open` + `record_success/failure`
- 把 `_em_get` 重构为 `RateLimitedSession`（per-host rate limit）
- 给腾讯/新浪/同花顺/财联社/百度 PAE 也加限流（per-host 配置：1 req/s 起步）

**收益**：Debt #5 修复；批量场景稳定性提升；批量任务可降速保护外部源。

**R6 — yfinance / alpha_vantage 模块移到 `_deprecated/` 或 `docs/legacy/`**（优先级 ★★☆☆☆）

- 创建 `tradingagents/dataflows/_deprecated/yfinance/` 和 `_deprecated/alpha_vantage/`
- 顶层 `interface.py` 移除 `VENDOR_METHODS` 里的 yfinance / alpha_vantage 分支
- `stockstats_utils.py` 完全删除（仅 A 股路径，yfinance 入口已 dead code）
- `pyproject.toml` 移除 `yfinance` / `alpha_vantage` / `pandas_datareader` 依赖

**收益**：Debt #7 修复；冷启动时间减少；包体积减小。

### 8.3 长期（1-3 月，独立项目）

**R7 — 迁移到统一的数据 API（Tushare Pro / Wind / iFinD）**

- 当前的 10 个直连 HTTP + 1 个 TCP 数据源是**最脆弱的层**——任何一家改接口、加密、限流都会破坏整个 Agent 链路
- Tushare Pro 提供统一的 Python SDK + 限流 + SLA，付费但稳定
- Wind / iFinD 是机构级，付费但合规
- 迁移策略：保留 `_em_get` 作为 fallback，付费 SDK 作为 primary；新加 `tushare_repository.py` 实现 `IOhlcvRepository` 等接口

**收益**：Debt #5 根本性修复；数据稳定性 SLA；可观测性（付费 SDK 通常有 API 调用统计）。

**R8 — async dataflows（httpx + asyncio）**

- 当前 `a_stock.py` 是同步 HTTP，多 Analyst 并发跑时线程切换开销大
- `httpx.AsyncClient` + `asyncio.gather` 可以并发拉 7 个 ticker 的 OHLCV（每 ticker 1.0s 节流 → 总耗时从 7s 降到 ~1s + 0.5s 抖动）
- LangGraph 节点天然支持 async（`async def analyst_node(state)`）

**收益**：批量多 ticker 场景延迟降低 5-10x；LLM 总耗时降低（数据阶段不阻塞 LLM 推理）。

---

## 9. 总结

### 9.1 数字一览

| 维度 | 数字 |
|---|---|
| dataflow 模块总数 | 13 |
| dataflow 总 LOC | 4221 |
| `a_stock.py` 占总 LOC | 61.8% (2610/4221) |
| `a_stock.py` 公开函数 | 41 |
| `a_stock.py` 内部 helper | 8 |
| `a_stock.py` 领域 DTO | 1 (`SectorRotationDigest`) |
| 外部数据源 | 10 (mootdx + 腾讯 + 东财 datacenter + 东财 push2 + 东财 push2his + 东财 np-weblist + 东财 np-ipick + 东财 search-api + 新浪 + 同花顺 + 财联社 + 百度 PAE = 12 个 endpoint，10 个 host) |
| 显式 fallback 链路 | 3 (mootdx→sina→push2his; Eastmoney→sina news; CLS→np-weblist) |
| 显式限流的 host | 6 (datacenter-web / push2 / push2his / np-weblist / np-ipick / search-api-web) |
| 独立 cache 实现 | 3 (OHLCV / northbound / sector rotation) |
| 死代码 LOC | 1150 (yfinance + alpha_vantage) |
| 已修复的架构债务 | 1 (R3 hot_money_tracker tool drift) |

### 9.2 三轮 DDD 探索闭环

| 文档 | 范围 | 数字 | 互补维度 |
|---|---|---|---|
| `docs/DDD_EXPLORATION.md` | `backend/core/` 13 聚合根 | 1311 行 | **领域层 + 应用层**：PortfolioStore / Scheduler / LogStore 等持久化聚合 |
| `docs/DDD_AGENTS_DEEP_DIVE.md` | `tradingagents/agents/` 16 LangGraph Agent | 1424 行 | **Core Domain Agent 协作**：Bull/Bear debate + 风险辩论 + Trader |
| `docs/DDD_DATAFLOWS_INFRA.md`（本文） | `tradingagents/dataflows/` 13 模块 + 10 数据源 | ~1700 行 | **基础设施层**：A 股 vendor + 防封限流 + Repository / ACL 缺失 |

### 9.3 核心洞察

1. **`a_stock.py` 是基础设施层的"巨无霸"**——2610 LOC 单一文件包含 41 函数 + 8 helper + 1 dataclass + 10 数据源的所有 vendor 实现。Repository 抽象（R1）+ Value Object 抽象（R2）是降低耦合度最高 ROI 的两件事。
2. **限流防封是务实纪律但缺乏抽象**——`_em_get` 用 30 行代码实现 6 个 host 的统一节流，但没有抽出 `RateLimiter` / `RetryPolicy` / `CircuitBreaker` 协议，导致其他 5+ host（腾讯/新浪/同花顺/财联社/百度）都是裸 HTTP。
3. **3-fallback K 线是 Repository Pattern 的最佳 demo**——但当前是硬编码控制流，需要重构为组合对象（详见 §3.2）。
4. **唯一显式 ACL 是 `SectorRotationDigest`**——39 个其他函数返回 `str`，让 Agent 必须 regex 解析。这是子 agent P2.23 Portfolio Manager structured-output 失败的同类根因。
5. **死代码 1150 LOC（yfinance + alpha_vantage）**——CLAUDE.md 说 v0.2.5 零依赖，但 vendor 抽象还保留实现。R6 移到 `_deprecated/` 是低成本高收益。
6. **`safe_ticker_component` 是输入侧 ACL 范本**——regex + max_len + 中文 ticker auto-resolve，3 道防线。可以作为整个 ACL 体系（R2）的参考实现。
