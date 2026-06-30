# Sector Rotation — Design

## Context

### 背景

A 股板块轮动 (sector rotation) 是短线交易的核心信号。当前 `tradingagents-astock` 框架的 `hot_money_tracker` Analyst 工具列表里有 9 个 vendor 函数,但都是**单股视角**:

| 现有工具 | 视角 | 限制 |
|----------|------|------|
| `get_industry_comparison` | 全行业涨跌幅 | 缺成分股,只能看"哪些行业强",不能说"哪些股票是该行业龙头候选" |
| `get_concept_blocks(ticker)` | 个股→所属概念 | 已知概念名后,无法反向问"X 概念下有哪些股票" |
| `get_hot_stocks(curr_date)` | 涨停股+reason tags | 只有涨停后才有,且 reason 是 free text,LLM 自己聚类 |
| `get_fund_flow(ticker)` | 个股资金流 | 看不到板块级资金 |
| `get_dragon_tiger_board(ticker)` | 个股龙虎榜 | 同上 |

LLM 想产出"今天 AI 算力板块最热,候选池是 002230/300308/688041"这种洞察时,**必须在脑子里串 3-4 个 tool call + 反向 join**,既慢又脆。

### 当前状态(endpoints 实测,2026-06-17,5 次重试)

| 端点 | 实测 | 状态 |
|------|------|------|
| `np-ipick.eastmoney.com/recommend/stock/heat/ranking` | ✅ 5/5 | **🆕 新增** |
| `np-anotice-stock.eastmoney.com/api/security/ann` | ✅ 5/5 | 备用(公告事件) |
| `zx.10jqka.com.cn/event/api/getharden/` | ✅ 5/5 | **复用**(已有) |
| `finance.pae.baidu.com/api/getrelatedblock` (批量 10) | ✅ 200 / 0.48s | **复用**(已有) |
| `datacenter-web.eastmoney.com` (RPT_DAILYBILLBOARD) | ✅ 5/5 | 复用(龙虎榜) |
| `push2.eastmoney.com` (行业/概念/成分股) | ❌ 0/5 | 不可用,本机网络问题 |
| `push2his.eastmoney.com` (类似) | ❌ 0/5 | 不可用,本机网络问题 |
| `stock.xueqiu.com/v5/stock/hot_stock/list.json` | ❌ HTTP 400 | 需 cookie |
| `np-tjxg-b.eastmoney.com/.../pw/search-code` | ❌ 200/55B | 需 `qgqp_b_id` |

### 约束

- v0.2.5 起立的"零第三方数据库依赖 + 全直连 HTTP"原则
- v0.2.11 立的"东财接口统一走 `_em_get()` 节流防封"原则
- 项目零 cookie 接入、零 API key、零 chromedp

## Goals / Non-Goals

### Goals

1. **独立可消费**:产出独立 Markdown 日报,不依赖完整 Analyst 链路
2. **零外部依赖**:不引入 API key、cookie、chromedp、selenium
3. **零新增第三方包**:只用 `requests` + 项目内置工具
4. **可被 hot_money_tracker 复用**:作为 LLM 工具的输入增强
5. **延迟可接受**:单次日报生成 < 30s(单线程,带节流)
6. **可测试**:单元测试覆盖率 ≥ 80%

### Non-Goals

- 不做"散户情绪"通道(雪球需 cookie)
- 不做"板块涨跌幅 Top N"面板(push2 不可用,需备用源)
- 不做"板块→成分股"反查接口(push2 不可用,本 change 用涨停股反查 PAE 替代)
- 不做实时分钟级刷新(单次拉取即缓存)
- 不引入新数据库(全部走 `_TRADINGAGENTS_HOME/cache` 现有缓存)

## Decisions

### Decision 1: 板块识别走"涨停股→反查"路径,不走"行业→成分股"路径

**问题**:行业/概念涨跌幅和成分股都需要 push2/push2his,但本机 0/5 不可用。

**决策**:把"板块涨跌幅"信号换成**"涨停密集度"**信号——把同花顺涨停 Top N 反查百度 PAE,统计哪些概念板块下涨停股最多。这个概念板块的"涨停密度"就是它的"机构+游资热度"代理变量。

**替代方案**:
- ❌ 走 push2 行业排名 + push2 行业成分股:实测 0/5 失败
- ❌ 走 push2 概念排名 + push2 概念成分股:同上
- ❌ 引入第三方数据源(akshare):违背 v0.2.5 原则

**Why it works**:A 股市场"涨停归因"高度集中(95 只涨停股分布在 ~30 个概念),Top 5 概念板块就能代表 80%+ 资金关注度。

### Decision 2: 引入"机构/编辑视角"作为补充信号(np-ipick)

**问题**:百度 PAE 反查涨停股是**事后**信号(涨停已经发生)。需要**事前/同步**的"机构最关注什么"信号。

**决策**:新增 `get_hot_strategy_ranking` 调 `np-ipick.eastmoney.com/recommend/stock/heat/ranking`,返回东财选股策略热度 Top N。`heatValue` 反映"选股策略被多少用户使用",`question` 是选股条件描述(如"近 3 日涨停+创业板+量比 1.2-3+MACD 金叉")。

**信号拼接**:
- 涨停密集 = 事后,揭示"已发生热点"
- 选股热度 = 同步,揭示"机构关注方向"
- 两路叠加 = 更稳健的板块轮动识别

**Why np-ipick 是最佳源**(对比 go-stock 的 4 个备选):

| go-stock 数据源 | 本项目可行性 | 结论 |
|-----------------|--------------|------|
| `np-ipick.eastmoney.com/recommend/stock/heat/ranking` | ✅ 5/5,无 cookie | **采纳** |
| `np-ipick.eastmoney.com` 是否要 API key | ❌ 无 | 满足"零 API key" |
| 雪球 hot_stock | ❌ HTTP 400,需 cookie/chromedp | 否决 |
| 东财 np-tjxg 关键词搜板块 | ❌ 需 `qgqp_b_id` | 否决 |
| 东财 `HotStrategy` (np-ipick 同源) | ✅ 实际就是 np-ipick | 合并 |

### Decision 3: 报告生成 = 单一 vendor 函数,不走新 Analyst

**问题**:要不要新增独立 `sector_rotation_analyst` 走 Bull/Bear 辩论?

**决策**:**v0.1 只加 1 个 vendor 函数 + 1 个组合函数**,LLM 工具形式可被 hot_money_tracker 复用,但**不**新增独立 Analyst 节点。原因:

1. 板块轮动是**描述性**任务(今天什么强),不是**决策性**任务(买不买),不需要 Bull/Bear 辩论
2. LangGraph 加新节点会改 state schema,影响所有现有 Analyst
3. v0.1 先验证"组合函数输出是否真有效",再决定要不要走独立 Analyst(v0.2 候选)

**v0.2 候选**:`sector_rotation_analyst` 独立节点 + Web UI tab,从 state 读板块轮动日报,与 hot_money_tracker 并行运行。

### Decision 4: 节流策略 = `_em_get()` + 0.5s/req 自定义节流

**问题**:新引入 np-ipick 端点,需不需要节流?

**决策**:
- **np-ipick 调用**:走项目内 `_em_get()`(默认 1.0s 间隔),因为它属于 `eastmoney.com` 子域,理论上有风控
- **百度 PAE 批量反查**:0.5s/req 自定义节流(PAE 实际不限流,但 v0.2.5 起所有 HTTP 都建议加节流,减少被风控风险)
- **同花顺 `zx.10jqka.com.cn`**:不加节流(v0.2.5 已确认不限流)

**实现**:复用 `a_stock.py` 的 `_em_get()`,不新增节流器。

### Decision 5: Web UI 入口 = 独立 tab + 不启动完整链路

**问题**:用户怎么消费板块轮动日报?

**决策**:
- v0.1:在 `web/app.py` 加 "板块轮动日报" 按钮(不是 tab),点击后**直接**调 `get_sector_rotation_digest`,渲染 Markdown,**不**走 LangGraph
- v0.2(候选):独立 tab,可配置刷新频率

**Why 不强制走 LangGraph**:板块轮动是高频低价值任务(每天可能看 3-5 次),走 LangGraph 启动开销太大,延迟不可接受。

## Risks / Trade-offs

| 风险 | 等级 | 缓解 |
|------|------|------|
| `np-ipick` 端点未来被东财风控封禁 | 中 | 走 `_em_get()` 节流;失败时 `get_sector_rotation_digest` 自动降级到"只有涨停+反查"模式 |
| 百度 PAE 批量接口被风控 | 低 | 0.5s 节流 + 失败时返回部分结果 + 标注 [数据缺失] |
| 同花顺涨停数据偶发 5xx | 中 | v0.2.5 起已确认稳定,失败时 `get_hot_stocks` 已有降级处理 |
| 报告延迟 16-20s(单线程)用户不耐烦 | 低 | v0.1 文档说明"首次加载需 ~20s",加 progress bar |
| LLM 在 hot_money_tracker 里滥用 `get_sector_rotation_digest` 拖慢 | 中 | 工具描述里明确"每个 session 最多调用 1 次" |
| push2 端点本机 0/5 失败 | **高** | 已在文档明确标注;**生产部署前必须先验证 push2/push2his 端点的可用性**,失败需切换到备用数据中心(已有 `EM_MIN_INTERVAL` 但不限断连重试);**本次 change 不涉及修复此问题**(独立 issue) |

## Migration Plan

1. 部署前在生产环境验证 np-ipick 端点(本机已 5/5 OK,生产因 IP 段不同需重测)
2. 部署时 `pip install -e .`(无新依赖)
3. 默认启用(Web UI 默认 tab 列表追加"板块轮动")
4. 监控:看 `_em_get()` 日志里 np-ipick 调用频率(预期 < 1 次/会话,因 v0.1 工具描述里限制)
5. 回滚:`git revert` 即可,无数据迁移

## Open Questions

- **Q1**:Web UI 的"板块轮动"按钮放 `web/app.py` 还是新开 `web/sector_rotation.py`?
  - 倾向 `web/app.py` 同文件加 section(v0.1 阶段),代码量 < 100 行
- **Q2**:`get_sector_rotation_digest` 的输出格式是纯 Markdown 还是结构化 dict(便于 LLM 二次加工)?
  - 倾向**双格式**:函数返回 `SectorRotationDigest` dataclass(包含 `hot_stocks: list`, `concept_blocks: dict`, `strategy_ranking: list`, `markdown: str`),`markdown` 字段是给 Web UI 和人类看的,`hot_stocks`/`concept_blocks` 是给 LLM 二次加工的
- **Q3**:`np-ipick` 返回的 `question` 是长 free text,需不需要做关键词提取?
  - **不在 v0.1 范围**——留给 LLM 自己处理(LLM 擅长 free text 解析)
- **Q4**:`get_sector_rotation_digest` 是否要支持历史日期查询?
  - **v0.1 不支持**(同花顺涨停也只支持当日),v0.2 候选(用 `np-anotice-stock` 拉历史公告)
