# TradingAgents A 股 LangGraph 多 Agent DDD 深入探索（read-only）

> **范围**：`tradingagents/agents/` 及其 LangGraph 编排、工具适配和 A 股数据源。本文是第二轮 DDD 战术探索，聚焦 Core Domain 的 Agent 协作，不重复 `docs/DDD_EXPLORATION.md` 的 13 个后端聚合根，也不重复 `docs/DDD_ANALYSIS.md` 的战略分层。
>
> **git HEAD**：`33b3a42`（P2.25 tracker + history_store + runner ID 一致性）
>
> **方法**：逐个读取 agents、schemas、AgentState、quality gate、graph setup/conditional logic/propagation、工具适配器和 `a_stock.py`；按代码实际调用路径记录输入、输出、LLM 调用和状态转换。
>
> **硬约束**：只读审计；本轮只创建本文件，不修改 Python、pytest、`pyproject.toml`、spec，不提交 commit。

---

## 0. 执行摘要

### 0.1 代码事实先于目标描述

仓库的 Core Domain 是一个**单一 LangGraph 图**，不是 17 个互相独立、可注册的 Agent 服务。当前可实例化的业务节点正好是：

- 7 个 Analyst
- 2 个投资研究辩论角色（Bull / Bear）
- 3 个风险辩论角色（Aggressive / Conservative / Neutral）
- 1 个 Trader
- 2 个 Manager（Research / Portfolio）
- 1 个 Quality Gate

合计 **16 个业务 Agent 节点**；如果将图中每个 Analyst 后的 `Msg Clear <Analyst>` 视为消息生命周期辅助节点，再加上 7 个 `ToolNode`，图的运行节点数会更多，但它们不是新的业务 Agent。用户需求中的“17 个 Agent”与当前实现存在一个重要口径差异：**代码中没有第 17 个独立业务 Agent**。`Quality Gate` 是第 16 个业务节点；`create_msg_delete()` 产生的是 7 个清理节点，不应误报为业务角色。另一个容易混淆的角色是 `SignalProcessor`，它只是确定性地从 Portfolio Manager Markdown 中解析评级，不在 `tradingagents/agents/` 业务图内，也不调用 LLM。

### 0.2 图并非“7 analyst 并行”

目标描述中的“7 analyst 并行”不符合当前 `tradingagents/graph/setup.py`：

```text
START
  → 第一个 selected analyst
  → tools_<analyst> ↔ 同一 analyst（工具循环）
  → Msg Clear <analyst>
  → 下一个 analyst
  → ...
  → Quality Gate
```

默认 `selected_analysts` 虽然包含 7 个角色，但它们是**按列表顺序串行执行**。只有同一 Analyst 与其工具节点形成循环；没有 `START → analyst_1, analyst_2, ...` 的 fan-out/fan-in 并行边。

### 0.3 Quality Gate 的代码行为与任务假设也不完全相同

`quality_gate.py` 的 docstring 写的是“Layer 1 hard checks + Layer 2 LLM review”，且确实在图中位于最后一个 Analyst 后、Bull Researcher 前。但它：

- 读取 7 个报告（空字符串也可读）；**不读取投资辩论状态或风险辩论状态**，因为这时两种辩论尚未发生；
- 不是纯规则、非 LLM 节点：硬检查是规则，但当少于 4 个报告为 D/F 时，会额外调用一次 `llm.invoke(review_prompt)`；
- 输出 `data_quality_summary` 为拼接 Markdown 字符串，不是 `pass/warn/fail` 枚举或结构化对象；
- `fail_count >= 4` 时跳过 LLM 复审，仅生成“多数报告未通过硬检查”的规则摘要。

### 0.4 DDD 结论

`AgentState` 是本流程事实上的**分析决策聚合根 / workflow aggregate**：所有 Agent 通过它读写报告、辩论历史和决策产物；但它当前继承 LangGraph `MessagesState`，并用 `TypedDict` 子状态 + `Annotated[str, description]` 表达字段，缺乏明确的生命周期、版本、状态转换契约和跨节点 schema 校验。Agent 的接口也不是 Protocol，而是工厂函数返回的闭包（Trader 还是 `functools.partial`），使图编排、工具循环、LLM 调用和业务输出紧密耦合。

---

## 1. 当前模块与角色清单

### 1.1 文件清单（实测行数）

| 区域 | 文件 | 行数 | 主要职责 |
|---|---|---:|---|
| State | `agents/utils/agent_states.py` | 79 | `AgentState`、`InvestDebateState`、`RiskDebateState` |
| Schema | `agents/schemas.py` | 228 | Pydantic 输出 schema + Markdown render |
| Quality | `agents/quality_gate.py` | 168 | 硬检查 + 可选 LLM 复审 |
| Analysts | `agents/analysts/*.py` | 634 | 7 个报告生产者 |
| Researchers | `agents/researchers/*.py` | 133 | Bull / Bear 投资辩论 |
| Risk | `agents/risk_mgmt/*.py` | 211 | 三方风险辩论 |
| Managers | `agents/managers/*.py` | 168 | Research / Portfolio 决策管理 |
| Trader | `agents/trader/trader.py` | 85 | 交易提案 |
| Helpers | `agents/utils/*.py` | 965 | 工具 facade、结构化输出、评分、memory 等辅助模块 |
| Graph | `graph/setup.py` | 212 | 节点 + 边 + 工具循环 |
| Graph | `graph/conditional_logic.py` | 91 | 辩论轮次与工具调用路由 |
| Graph | `graph/propagation.py` | 73 | 初始状态与 graph invoke 参数 |

### 1.2 业务角色总览

| 编号 | 类别 | 代码工厂 / 图节点 | 业务产物 | LLM 类型 | 当前执行位置 |
|---:|---|---|---|---|---|
| A1 | Analyst | `create_market_analyst` / `Market Analyst` | `market_report` | quick + tool loop | 7 个 analyst 中按顺序 |
| A2 | Analyst | `create_social_media_analyst` / `Social Analyst` | `sentiment_report` | quick + tool loop | 同上 |
| A3 | Analyst | `create_news_analyst` / `News Analyst` | `news_report` | quick + tool loop | 同上 |
| A4 | Analyst | `create_fundamentals_analyst` / `Fundamentals Analyst` | `fundamentals_report` | quick + tool loop | 同上 |
| A5 | Analyst | `create_policy_analyst` / `Policy Analyst` | `policy_report` | quick + tool loop | 同上 |
| A6 | Analyst | `create_hot_money_tracker` / `Hot_money Analyst` | `hot_money_report` | quick + tool loop | 同上 |
| A7 | Analyst | `create_lockup_watcher` / `Lockup Analyst` | `lockup_report` | quick + tool loop | 同上 |
| R1 | Researcher | `create_bull_researcher` / `Bull Researcher` | `investment_debate_state.bull_history` | quick | 投资辩论循环 |
| R2 | Researcher | `create_bear_researcher` / `Bear Researcher` | `investment_debate_state.bear_history` | quick | 投资辩论循环 |
| D1 | Risk Debator | `create_aggressive_debator` / `Aggressive Analyst` | `risk_debate_state.aggressive_history` | quick | 风险辩论循环 |
| D2 | Risk Debator | `create_conservative_debator` / `Conservative Analyst` | `risk_debate_state.conservative_history` | quick | 风险辩论循环 |
| D3 | Risk Debator | `create_neutral_debator` / `Neutral Analyst` | `risk_debate_state.neutral_history` | quick | 风险辩论循环 |
| T1 | Trader | `create_trader` / `Trader` | `trader_investment_plan` | quick + structured attempt | 风险辩论前 |
| M1 | Manager | `create_research_manager` / `Research Manager` | `investment_plan`、投资 judge | deep + structured attempt | 投资辩论结束后 |
| M2 | Manager | `create_portfolio_manager` / `Portfolio Manager` | `final_trade_decision`、风险 judge | deep + structured attempt | 风险辩论结束后 |
| Q1 | Quality | `create_quality_gate` / `Quality Gate` | `data_quality_summary` | 规则 + **可选一次 quick LLM** | Analyst 结束后 |
| — | 辅助，不计业务 Agent | `create_msg_delete`、`ToolNode`、`SignalProcessor` | 清理消息、执行工具、解析评级 | 无 / 工具内部由 Analyst 触发 | 图基础设施 |

> **角色计数结论**：当前业务节点是 16 个，而不是 17 个。若产品/架构文档坚持 17，需要明确第 17 个是业务角色还是将辅助节点错误地纳入计数；建议不要把 `Msg Clear`、`ToolNode` 或 `SignalProcessor` 命名为 Agent。

---

## 2. 16 个业务 Agent 详细画像

### 2.1 输入/输出字段约定

后文用以下缩写避免重复：

- **基础输入**：`company_of_interest`、`trade_date`、`messages`、`past_context`。
- **7 报告**：`market_report`（MKT）、`sentiment_report`（SENT）、`news_report`（NEWS）、`fundamentals_report`（FUND）、`policy_report`（POL）、`hot_money_report`（HOT）、`lockup_report`（LOCK）。
- **投资辩论**：`investment_debate_state`（INV），字段见 §3。
- **风险辩论**：`risk_debate_state`（RISK），字段见 §3。
- **输出规则**：Analyst 返回 `messages` 增量 + 一个报告字段；辩论 Agent 返回完整替换的嵌套 state；Manager 返回完整替换的嵌套 state + 决策字段。

### 2.2 7 个 Analyst

#### A1 技术 / 市场分析师（Market Analyst）

- **实现**：`analysts/market_analyst.py:create_market_analyst`。
- **职责**：在 A 股涨跌停、T+1、北向资金、换手率和量价关系背景下，选择最多 8 个技术指标，生成带具体数值和 Markdown 汇总表的技术研究报告。
- **读取 state**：`trade_date`、`company_of_interest`、`messages`。
- **写入 state**：`messages` 追加 LLM 消息；`market_report` 在没有 tool call 的最终消息上写入 `result.content`，如果结果仍有工具调用则报告保持空字符串。
- **工具 / 数据源**：`get_stock_data`、`get_indicators`。由 `agent_utils` facade 转到 `a_stock.get_stock_data` / `a_stock.get_indicators`；K 线主源为 mootdx TCP，失败依次 Sina HTTP、push2his HTTP。
- **LLM 调用**：每轮 `chain.invoke(state["messages"])` 一次；如果 LLM 返回 tool calls，则进入 ToolNode，再回到 Analyst，形成“至少一次、按工具循环次数增加”的调用次数，不是固定的单次 system+user+JSON 调用。输出是自然语言 Markdown，不是 Pydantic JSON。
- **不变量**：工具调用必须先获取 K 线再取指标；指标名须是 `a_stock.py` 支持白名单；报告最终应包含最新收盘价、近 30 日涨跌、5/20 日均量比较、至少 3 个指标、支撑阻力，并尽量用 `[数据缺失: ...]` 标记缺失。

#### A2 情绪 / 社交媒体分析师（Social Media Analyst）

- **实现**：`analysts/social_media_analyst.py:create_social_media_analyst`。
- **职责**：从个股新闻和市场讨论推断 A 股散户情绪、方向、强度和短中期趋势。
- **读取 state**：`trade_date`、`company_of_interest`、`messages`。
- **写入 state**：`messages`、`sentiment_report`。
- **工具 / 数据源**：`get_news` → `a_stock.get_news`（东方财富个股新闻，失败时新浪财经）。代码注释提及股吧/雪球/同花顺讨论，但当前工具并没有独立的这些论坛 API，属于提示词推断范围而非已接入数据源。
- **LLM 调用**：每一轮 `chain.invoke` 一次；工具调用后循环。最终自然语言报告，不是 JSON。
- **不变量**：报告应包含检索条数与时间范围、正/负/中性比例、Top 3 舆情主题、五档情绪评级和趋势方向；无法取数时标注数据缺失。

#### A3 新闻分析师（News Analyst）

- **实现**：`analysts/news_analyst.py:create_news_analyst`。
- **职责**：分析个股新闻、宏观/全球新闻、政策市和事件驱动，区分利好/利空/中性及影响持续时间。
- **读取 state**：`trade_date`、`company_of_interest`、`messages`。
- **写入 state**：`messages`、`news_report`。
- **工具 / 数据源**：`get_news`、`get_global_news` → `a_stock.get_news`、`a_stock.get_global_news`。后者组合财联社 CLS Wire 与东方财富 7×24 快讯。
- **LLM 调用**：每次工具循环一次 `chain.invoke`；最终自然语言 Markdown。
- **不变量**：报告应有个股/宏观新闻条数与时间范围、至少 3 个关键事件时间线、利好/利空/中性统计、风险事件清单。

#### A4 基本面分析师（Fundamentals Analyst）

- **实现**：`analysts/fundamentals_analyst.py:create_fundamentals_analyst`。
- **职责**：在中国会计准则、A 股估值参照和财报披露周期下，输出估值、盈利、资产负债和现金流研究。
- **读取 state**：`trade_date`、`company_of_interest`、`messages`。
- **写入 state**：`messages`、`fundamentals_report`。
- **工具 / 数据源**：`get_fundamentals`（腾讯报价 + mootdx finance + 东财 push2 + 同花顺 EPS 预测）、`get_balance_sheet`、`get_cashflow`、`get_income_statement`（Sina 财报 HTTP）、`get_profit_forecast`（同花顺一致预期）、`get_industry_comparison`（东财 push2 行业板块）。均通过 `route_to_vendor` 进入 A 股 vendor。
- **LLM 调用**：每次 Analyst/Tool 循环调用一次；最终自然语言 Markdown。
- **不变量**：至少覆盖 PE(TTM)、PB、市值、营收增速、归母净利及增速、ROE、资产负债率、经营现金流/净利、机构一致预期 EPS；数据必须受 `trade_date` 截止，避免 look-ahead bias。

#### A5 政策分析师（Policy Analyst）

- **实现**：`analysts/policy_analyst.py:create_policy_analyst`。
- **职责**：识别宏观、监管、产业、地方和国际政策，建立“政策 → 行业 → 公司业务 → 财务/股价”的影响链。
- **读取 state**：`trade_date`、`company_of_interest`、`messages`。
- **写入 state**：`messages`、`policy_report`。
- **工具 / 数据源**：`get_news`、`get_global_news` → 个股新闻 + CLS/东财全球快讯；没有专门的政策 API。
- **LLM 调用**：每个 tool loop 一次 `chain.invoke`；自然语言报告。
- **不变量**：报告应列出事件、发布日期/机构、行业方向、影响强弱、时间窗口和总体政策评级；官方政策与传闻应区分。

#### A6 游资 / 资金流追踪师（Hot Money Tracker）

- **实现**：`analysts/hot_money_tracker.py:create_hot_money_tracker`。
- **职责**：综合量价异动、板块轮动、龙虎榜、北向资金、个股资金流和题材标签，判断主力吸筹、出货、游资接力或散户主导。
- **读取 state**：`trade_date`、`company_of_interest`、`messages`。
- **写入 state**：`messages`、`hot_money_report`。
- **工具 / 数据源**：`get_sector_rotation_digest`（东财 np-ipick + 同花顺涨停归因 + 百度 PAE 概念反查）、`get_stock_data`（mootdx/Sina/push2his）、`get_news`、`get_insider_transactions`（mootdx F10 股东研究）、`get_hot_stocks`（同花顺）、`get_northbound_flow`（同花顺 hsgtApi + 本地日缓存）、`get_concept_blocks`（百度 PAE）、`get_fund_flow`（东财 push2/push2his）、`get_dragon_tiger_board`（东财 datacenter）、`get_industry_comparison`（东财 push2）。
- **实现注意**：Hot Money 工厂在本地 `tools` 列表绑定了 `get_sector_rotation_digest`，但 `TradingAgentsGraph._create_tool_nodes()` 的 `hot_money` ToolNode 列表没有注册该工具；因此实际图运行时可能出现“模型要求调用但 ToolNode 不认识”的配置漂移。这是 §8 的单独架构债务，不把提示词声明误当作已验证的运行能力。
- **LLM 调用**：每个 tool loop 一次；提示词要求 `get_sector_rotation_digest` 每 session 最多一次，但这是提示词约束而非运行时 registry/计数器。
- **不变量**：报告应至少包含 5 日成交量趋势、当日北向净流入、个股主力净流入、概念板块及涨幅、热门股/题材归因和总体判断；外部来源部分失败应显式反映数据缺失。

#### A7 解禁 / 减持监控师（Lockup Watcher）

- **实现**：`analysts/lockup_watcher.py:create_lockup_watcher`。
- **职责**：追踪限售解禁、股东减持和股权结构变化，评估供给端压力和未来 1–3 个月风险。
- **读取 state**：`trade_date`、`company_of_interest`、`messages`。
- **写入 state**：`messages`、`lockup_report`。
- **工具 / 数据源**：`get_insider_transactions`（mootdx F10）、`get_news`（东财/Sina）、`get_fundamentals`（腾讯 + mootdx + 东财 + 同花顺）、`get_lockup_expiry`（东财 datacenter `RPT_LIFT_STAGE`）。
- **LLM 调用**：每个 tool loop 一次；自然语言报告。
- **不变量**：报告应包含近 6 个月内部人/大股东活动、前十大股东变化、解禁公告、压力评级和未来 3 个月风险；解禁日历必须按 `trade_date` + `forward_days=90` 过滤。

### 2.3 投资研究辩论（2 个 Researcher）

#### R1 Bull Researcher

- **实现**：`researchers/bull_researcher.py:create_bull_researcher`。
- **职责**：依据 7 份报告和质量摘要构造看多论点，强调成长、政策顺风、北向流入、游资动量、估值增长故事、解禁压力消除，并回应上一轮 Bear 论点。
- **读取 state**：7 个报告字段、`data_quality_summary`、`investment_debate_state.history`、`current_response`、`bull_history`、`bear_history`、`count`。
- **写入 state**：仅返回 `investment_debate_state`；追加 `history` 和 `bull_history`，更新 `current_response`、`count`，保留 `bear_history`。`judge_decision` 不在本节点写入。
- **数据源**：**不直接调用 `a_stock.py`**，只消费 Analyst 已产生的文本报告。
- **LLM 调用**：固定一次 `llm.invoke(prompt)`；无工具、无 structured output、自然语言论证。
- **不变量**：`count` 单调递增；`history` 必须包含标记为 `Bull Analyst:` 的论点；低质量报告应降低权重并披露限制；没有 AgentState schema validator 阻止丢字段，因此完整保留嵌套字段是靠手工构造。

#### R2 Bear Researcher

- **实现**：`researchers/bear_researcher.py:create_bear_researcher`。
- **职责**：构造看空论点，强调政策反转、解禁/减持、游资撤退、估值泡沫、T+1、北向撤退和竞争/财务风险。
- **读取 state**：与 Bull 相同的 7 报告、质量摘要及 INV 历史/当前响应。
- **写入 state**：`investment_debate_state.history`、`bear_history`、`current_response`、`count`，保留 `bull_history`。
- **数据源**：无直接 `a_stock.py` 调用。
- **LLM 调用**：固定一次 `llm.invoke(prompt)`。
- **不变量**：输出必须带 `Bear Analyst:`，count 单调，必须与当前 Bull 论点交锋；没有代码级辩论消息类型或角色枚举。

> **关于“bull 直接 import bear”**：实际读取的两个 researcher 文件没有互相 import；二者通过 `AgentState` 和 `ConditionalLogic.should_continue_debate` 间接耦合。`graph/setup.py` 通过 `from tradingagents.agents import *` 统一导入工厂。债务应准确描述为**共享状态 + 图路由强耦合**，而不是不存在的直接 import。

### 2.4 Trader

#### T1 Trader

- **实现**：`trader/trader.py:create_trader`，返回 `functools.partial(trader_node, name="Trader")`。
- **职责**：把 Research Manager 的投资计划转成可执行的 Buy/Hold/Sell 交易提案，同时给出 entry、stop loss、仓位建议，遵守 A 股 T+1、涨跌停、最小手数和交易时段约束。
- **读取 state**：`company_of_interest`、`investment_plan`、可选 `policy_report`、`hot_money_report`、`lockup_report`。
- **写入 state**：`messages` 追加一个 `AIMessage`；`trader_investment_plan`；`sender="Trader"`。
- **数据源**：无直接工具调用，消费报告；报告背后的来源由 7 Analyst 负责。
- **LLM 调用**：优先一次 `structured_llm.invoke`（`TraderProposal`）；失败后同一个 prompt 再调用一次普通 `llm.invoke`。若 provider 在创建时不支持 structured output，则直接一次普通调用。因此通常 1 次，结构化失败时最多 2 次；不再额外用 JSON extraction LLM。
- **不变量**：最终文本由 `render_trader_proposal` 生成，并保留 `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**` 兼容行；`action` 必须是三档 `TraderAction`（结构化路径）；entry/stop 可空。

### 2.5 三方风险辩论（3 个 Debator）

#### D1 Aggressive Risk Analyst

- **实现**：`risk_mgmt/aggressive_debator.py:create_aggressive_debator`。
- **职责**：从高收益、动量、政策主题、北向验证和游资接力角度支持激进仓位，反驳保守/中性观点。
- **读取 state**：全部 7 报告、`trader_investment_plan`、RISK 的 `history`、`current_conservative_response`、`current_neutral_response`、`aggressive_history`、`count`。
- **写入 state**：完整 `risk_debate_state`，追加 `history` / `aggressive_history`，更新 `latest_speaker="Aggressive"`、`current_aggressive_response`、`count`，保留其他历史。
- **数据源**：不直接调用 `a_stock.py`。
- **LLM 调用**：一次普通 `llm.invoke(prompt)`。
- **不变量**：输出前缀 `Aggressive Analyst:`；风险辩论 count 单调；完整保留三方历史。

#### D2 Conservative Risk Analyst

- **实现**：`risk_mgmt/conservative_debator.py:create_conservative_debator`。
- **职责**：强调 T+1 锁损、跌停无法退出、解禁、政策反转、游资退出、高估值和 ST/退市风险，保护资产。
- **读取 state**：与 Aggressive 相同，特别依赖 trader plan 与当前 Aggressive/Neutral 响应。
- **写入 state**：`history` / `conservative_history`，`latest_speaker="Conservative"`、`current_conservative_response`、`count`，保留其它状态。
- **数据源**：无直接 `a_stock.py` 调用。
- **LLM 调用**：一次普通 `llm.invoke(prompt)`。
- **不变量**：输出前缀 `Conservative Analyst:`；三方交锋顺序由 `ConditionalLogic` 控制而非 Agent 自己决定。

#### D3 Neutral Risk Analyst

- **实现**：`risk_mgmt/neutral_debator.py:create_neutral_debator`。
- **职责**：平衡 T+1 双面性、政策证据等级、北向资金确认作用、估值带、解禁时点和仓位大小，提出可承受的中间方案。
- **读取 state**：全部 7 报告、Trader 计划、RISK 全部历史和两个当前对手论点。
- **写入 state**：`history` / `neutral_history`，`latest_speaker="Neutral"`、`current_neutral_response`、`count`，保留其它状态。
- **数据源**：无直接 `a_stock.py` 调用。
- **LLM 调用**：一次普通 `llm.invoke(prompt)`。
- **不变量**：输出前缀 `Neutral Analyst:`；风险辩论在 count 达阈值后交给 Portfolio Manager。

### 2.6 两个 Manager

#### M1 Research Manager

- **实现**：`managers/research_manager.py:create_research_manager`。
- **职责**：作为投资辩论 judge/计划编排者，把 Bull/Bear 历史综合为五档 `Buy / Overweight / Hold / Underweight / Sell` 的投资计划，供 Trader 执行。
- **读取 state**：`company_of_interest`、`investment_debate_state.history`（并保留完整 INV state）、`trade_date`（通过 instrument context 间接使用）；它**不直接重新拼接 7 份 Analyst 报告**，那些内容已经在辩论历史中。
- **写入 state**：`investment_debate_state`（写 `judge_decision=investment_plan`、`current_response=investment_plan`，保留 bull/bear/history/count）；`investment_plan`。
- **数据源**：无直接 `a_stock.py` 调用。
- **LLM 调用**：优先一次 `structured_llm.invoke`（`ResearchPlan`），成功后 render；结构化失败最多再普通调用一次。通常 1 次，失败最多 2 次。
- **不变量**：研究计划必须包含 recommendation、rationale、strategic actions；`judge_decision` 与 `investment_plan` 应表示同一决策文本。当前代码没有 validator 强制两者一致。
- **图语义**：它是在投资辩论 count 达阈值后的 judge，不是“先 judge 再 bull/bear”；Bull/Bear 结束后才第一次执行。

#### M2 Portfolio Manager

- **实现**：`managers/portfolio_manager.py:create_portfolio_manager`。
- **职责**：综合风险辩论、Research Manager 计划和 Trader 提案，在 A 股执行约束和历史教训下输出最终五档组合评级与行动方案。
- **读取 state**：`company_of_interest`、`risk_debate_state.history`、`investment_plan`、`trader_investment_plan`、可选 `past_context`。
- **写入 state**：`risk_debate_state`（写 `judge_decision=final_trade_decision`、`latest_speaker="Judge"`，保留三方历史/count）；`final_trade_decision`。
- **数据源**：无直接 `a_stock.py` 调用；风险辩论已消费报告。
- **LLM 调用**：优先一次 `structured_llm.invoke`（`PortfolioDecision`）；失败后最多一次普通 `llm.invoke`。通常 1 次，失败最多 2 次。当前 `structured.py` 的 warning 文案为“structured-output invocation failed; retrying once as free text”，这正是 P2.23 类失败路径的证据。
- **不变量**：最终输出应能由 `parse_rating` 解析；结构化成功时 `rating` 必为五档 enum；Markdown 中要保留 `**Rating**`、`**Executive Summary**`、`**Investment Thesis**`，可选目标价和时间周期。

### 2.7 Quality Gate（Q1）

详细分析见 §6。这里先给角色画像：

- **实现**：`quality_gate.py:create_quality_gate(llm)`。
- **职责**：在进入投资辩论前对 7 份 Analyst 报告进行硬质量检查，并在总体未严重失败时调用一次 LLM 做逐报告复审。
- **读取 state**：`trade_date`、`company_of_interest`、7 个报告字段。**不读取** `investment_debate_state` 或 `risk_debate_state`。
- **写入 state**：只写 `data_quality_summary`。
- **数据源**：不调用 `a_stock.py`；仅检查报告文本。
- **LLM 调用**：硬检查后，若 D/F 报告数 `<4`，调用 quick LLM 一次；否则 0 次。此处没有 structured schema。
- **不变量**：每个报告至少能获得 A/B/C/D/F grade 和 detail；报告为空 → F，短于 200 字符 → D，失败信息占主导 → D；但输出 summary 不是程序可直接比较的 pass/warn/fail 值。

---

## 3. AgentState 聚合根分析

### 3.1 实际定义

`tradingagents/agents/utils/agent_states.py`（用户任务中写成 `agents/agent_states.py`，实际路径是 `agents/utils/agent_states.py`）定义：

```python
class InvestDebateState(TypedDict):
    bull_history: Annotated[str, "Bullish Conversation history"]
    bear_history: Annotated[str, "Bearish Conversation history"]
    history: Annotated[str, "Conversation history"]
    current_response: Annotated[str, "Latest response"]
    judge_decision: Annotated[str, "Final judge decision"]
    count: Annotated[int, "Length of the current conversation"]

class RiskDebateState(TypedDict):
    aggressive_history: Annotated[str, "Aggressive Agent's Conversation history"]
    conservative_history: Annotated[str, "Conservative Agent's Conversation history"]
    neutral_history: Annotated[str, "Neutral Agent's Conversation history"]
    history: Annotated[str, "Conversation history"]
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[str, "Latest response by the aggressive analyst"]
    current_conservative_response: Annotated[str, "Latest response by the conservative analyst"]
    current_neutral_response: Annotated[str, "Latest response by the neutral analyst"]
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]

class AgentState(MessagesState):
    company_of_interest: Annotated[str, ...]
    trade_date: Annotated[str, ...]
    sender: Annotated[str, ...]
    market_report: Annotated[str, ...]
    sentiment_report: Annotated[str, ...]
    news_report: Annotated[str, ...]
    fundamentals_report: Annotated[str, ...]
    policy_report: Annotated[str, ...]
    hot_money_report: Annotated[str, ...]
    lockup_report: Annotated[str, ...]
    data_quality_summary: Annotated[str, ...]
    investment_debate_state: Annotated[InvestDebateState, ...]
    investment_plan: Annotated[str, ...]
    trader_investment_plan: Annotated[str, ...]
    risk_debate_state: Annotated[RiskDebateState, ...]
    final_trade_decision: Annotated[str, ...]
    past_context: Annotated[str, ...]
```

注意：`MessagesState` 还隐含 `messages` 字段，`AgentState` 本身没有显式的 `prices`、`news`、`fundamentals` 字段；这些输入由工具在 Analyst 执行期获取，并以文本形式进入 `messages`，最后被压缩为报告字段。也没有显式 `ticker` 字段，实际字段名是 `company_of_interest`，初始值由 `Propagator.create_initial_state` 接收 `company_name`。

### 3.2 字段分类、来源、消费者、不变量

| 分类 | 字段 / 类型 | 来源 Agent / 初始化 | 消费者 | 代码可观察不变量 |
|---|---|---|---|---|
| 输入标识 | `company_of_interest: str` | `Propagator` 初始化；图入口传入 `company_name` | 所有需要 instrument context 的 Agent、工具 prompt、日志 | 应是可被工具解析的 A 股代码；工具 facade 的描述要求 6 位数字，但图自身未做 Pydantic/regex 校验 |
| 输入时间 | `trade_date: str` | `Propagator` 强制 `str(trade_date)` | Analyst 工具、质量 gate、辩论上下文、日志 | 应为 `YYYY-MM-DD`；AgentState 无日期 validator |
| 消息总线 | `messages`（`MessagesState` 管理） | 初始 `[("human", company_name)]`；Analyst/Trader 追加；清理节点移除 | Analyst prompt、ConditionalLogic、日志/调试 | Analyst 有 tool calls 就回 ToolNode；最终无 tool calls 才写报告；消息清理是手工 RemoveMessage |
| 发件人 | `sender: str` | Trader 写 `"Trader"`；Analyst 没有稳定写入 | UI/调试可能读取 | 不是 Enum；多数节点不维护，值可能为空或旧值 |
| Analyst 产物 | `market_report: str` | Market Analyst | Bull/Bear、三方风险 Agent、Quality Gate、Trader（间接只读 A 股额外字段） | 只有没有 tool call 的最终消息才赋值；空字符串代表未完成/缺失/模型未结束，语义混合 |
| Analyst 产物 | `sentiment_report: str` | Social Analyst | Bull/Bear、三方风险 Agent、Quality Gate | 同上；报告文本非结构化 |
| Analyst 产物 | `news_report: str` | News Analyst | Bull/Bear、三方风险 Agent、Quality Gate | 同上 |
| Analyst 产物 | `fundamentals_report: str` | Fundamentals Analyst | Bull/Bear、三方风险 Agent、Quality Gate | 同上 |
| Analyst 产物 | `policy_report: str` | Policy Analyst | Bull/Bear、三方风险 Agent、Quality Gate、Trader | 同上；运行时可选 `.get` |
| Analyst 产物 | `hot_money_report: str` | Hot Money Tracker | Bull/Bear、三方风险 Agent、Quality Gate、Trader | 同上；工具可能部分失败并在文本中报告 |
| Analyst 产物 | `lockup_report: str` | Lockup Watcher | Bull/Bear、三方风险 Agent、Quality Gate、Trader | 同上 |
| 质量产物 | `data_quality_summary: str` | Quality Gate | Bull/Bear；Portfolio Manager 不直接读取 | gate 输出完整 Markdown；没有机器可判定 enum；失败标志依赖文字 |
| 投资辩论 | `investment_debate_state: InvestDebateState` | `Propagator` 初始化空 state；Bull/Bear 增量重建；Research Manager 写 judge | ConditionalLogic、Research Manager、日志 | `count` 从 0 单调增加；达到 `2 * max_debate_rounds` 转 Research Manager；`current_response` 前缀决定下一个 Bull/Bear；嵌套字段不由 Pydantic 校验 |
| 投资计划 | `investment_plan: str` | Research Manager | Trader、Portfolio Manager | 与 INV `judge_decision` 逻辑上应相同，但代码不做 equality 校验；Markdown 结构依赖 render helper |
| 交易提案 | `trader_investment_plan: str` | Trader | 三方风险 Agent、Portfolio Manager、日志 | 结构化成功时为 TraderProposal render；fallback 时为任意 LLM 文本，仍被下游消费 |
| 风险辩论 | `risk_debate_state: RiskDebateState` | `Propagator` 初始化空 state；三方 Debator 增量重建；PM 写 judge | ConditionalLogic、Portfolio Manager、日志 | `count` 达到 `3 * max_risk_discuss_rounds` 转 PM；`latest_speaker` 前缀路由 Aggressive → Conservative → Neutral；PM 写 `Judge` 但 conditional edge 已不再继续 |
| 最终决策 | `final_trade_decision: str` | Portfolio Manager | `SignalProcessor`、日志、memory、外部 UI | 结构化路径 render 的 `PortfolioDecision`；fallback 可为任意 free text；下游解析依赖 `**Rating**` 或 rating heuristic |
| 历史上下文 | `past_context: str` | `TradingMemoryLog.get_past_context` 注入 | Portfolio Manager（决策 prompt） | 可为空；文本由外部 memory log 提供，没有长度/schema 约束 |
| 隐含决策输入 | `messages` 中的 tool results | ToolNode 根据 LLM tool calls 生成 | 当前 Analyst 下一轮 | tool call 的参数和返回格式由 LLM + 工具 docstring 决定；无 Agent-level tool invocation schema |

### 3.3 聚合边界与生命周期

```text
┌───────────────────────────────────────────────────────────────────────┐
│ AgentState：一次 ticker + trade_date 分析的 workflow aggregate        │
│                                                                       │
│  identity: company_of_interest, trade_date                            │
│  evidence: messages + 7 analyst reports + data_quality_summary        │
│  investment sub-state: InvestDebateState + investment_plan            │
│  execution sub-state: trader_investment_plan                          │
│  risk sub-state: RiskDebateState + final_trade_decision               │
│  context: past_context, sender                                         │
└───────────────────────────────────────────────────────────────────────┘
```

生命周期由图节点隐式定义，而不是显式状态机：

```text
created
  │ Propagator.create_initial_state()
  ▼
analyst-evidence-building
  │ 7 analyst + ToolNode loops
  ▼
quality-reviewed
  │ Quality Gate
  ▼
investment-debating
  │ Bull ↔ Bear until count threshold
  ▼
research-plan-ready
  │ Research Manager
  ▼
trade-proposal-ready
  │ Trader
  ▼
risk-debating
  │ Aggressive → Conservative → Neutral cycles
  ▼
final-decision-ready
  │ Portfolio Manager
  ▼
completed
```

**聚合根缺陷**：

1. 任意节点都能返回一个 `dict` 更新任意字段；没有 command/event 形式的合法 transition。
2. 子 state 全是可变 `TypedDict`，没有 `frozen`、版本号或 schema migration。
3. 字符串同时承担“缺失”“未运行”“失败返回”“模型空响应”四种语义。
4. 报告没有来源、抓取时间、vendor、数据新鲜度、工具失败明细等值对象。
5. `judge_decision` 在两个嵌套 state 中存在，但投资 judge 与风险 judge 的完成态没有 enum 标识。
6. `AgentState` 的类型注解并不等于运行时校验；LangGraph 的 state merge 不会按业务不变量阻止错误写入。

---

## 4. LangGraph 状态机

### 4.1 真实图（默认 7 Analyst 是串行，不是并行）

```text
                                  ┌──────────────────────┐
                                  │  selected_analysts   │
                                  │ 默认 7 个，按列表顺序 │
                                  └──────────┬───────────┘
                                             │
START ──▶ Market Analyst ──tool_calls?──▶ tools_market ──┐
              │ no tool calls                             │
              ▼                                           └──▶ Market Analyst
        Msg Clear Market
              │
              ▼
        Social Analyst ──tool_calls?──▶ tools_social ──────┐
              │ no tool calls                               └──▶ Social Analyst
              ▼
        Msg Clear Social
              │
              ▼
        News Analyst ──tool_calls?──▶ tools_news ───────────┐
              │ no tool calls                                └──▶ News Analyst
              ▼
        Msg Clear News
              │
              ▼
        Fundamentals Analyst ──tool_calls?──▶ tools_fundamentals ─┐
              │ no tool calls                                       └──▶ Fundamentals Analyst
              ▼
        Msg Clear Fundamentals
              │
              ▼
        Policy Analyst ──tool_calls?──▶ tools_policy ──────┐
              │ no tool calls                               └──▶ Policy Analyst
              ▼
        Msg Clear Policy
              │
              ▼
        Hot_money Analyst ──tool_calls?──▶ tools_hot_money ─┐
              │ no tool calls                                 └──▶ Hot_money Analyst
              ▼
        Msg Clear Hot_money
              │
              ▼
        Lockup Analyst ──tool_calls?──▶ tools_lockup ───────┐
              │ no tool calls                                 └──▶ Lockup Analyst
              ▼
        Msg Clear Lockup
              │
              ▼
        Quality Gate
              │
              ▼
        Bull Researcher ── count < 2R and last != Bull? ──▶ Bear Researcher
              │                                           ▲
              │ count < 2R and last starts Bull            │
              └───────────────────────────────────────────┘
              │ count ≥ 2R
              ▼
        Research Manager (investment judge / plan)
              │
              ▼
        Trader
              │
              ▼
        Aggressive Analyst ── count < 3K ──▶ Conservative Analyst
              │                                  │
              │ count ≥ 3K                         │ count < 3K
              ▼                                  ▼
        Portfolio Manager ◀────────────────── Neutral Analyst
              │                                  │
              │ count < 3K from Neutral          └──▶ Aggressive Analyst
              ▼
             END
```

其中 `R = max_debate_rounds`，`K = max_risk_discuss_rounds`，默认配置中二者均为 1。图中投资辩论默认最多 2 次 Agent 发言（Bull/Bear 各一次）；风险辩论默认最多 3 次发言（Aggressive/Conservative/Neutral 各一次）。

### 4.2 每条边的触发条件

#### Analyst 与 ToolNode

每个 Analyst 的 conditional edge 都调用 `ConditionalLogic.should_continue_<analyst>`：

```text
last_message.tool_calls 非空 → tools_<analyst>
last_message.tool_calls 为空 → Msg Clear <Analyst>
```

- `tools_<analyst>` 执行工具调用结果，然后无条件回到同一个 Analyst。
- Analyst 最终无 tool calls 后，`Msg Clear` 使用 `RemoveMessage` 删除当前 `messages`，再加一个 `HumanMessage("Continue")`，避免后一个 Agent 继承前一 Agent 的上下文。
- 当前实现对 7 个 Analyst 使用 `workflow.add_edge` 链接，因此上一个清理节点完成后才进入下一个 Analyst。
- `selected_analysts` 可裁剪或重排；最后一个 selected Analyst 的 clear 节点进入 Quality Gate。

#### Quality Gate → Bull

```text
Quality Gate 完成 → Bull Researcher
```

无 conditional edge。Quality Gate 不会以 pass/warn/fail 决定是否阻断；即便报告质量很差，也仍进入 Bull Researcher。`fail_count >=4` 只影响是否调用 gate 内的 LLM 复审，不改变图边。

#### Bull / Bear 投资辩论

`should_continue_debate`：

```python
if investment_debate_state["count"] >= 2 * max_debate_rounds:
    return "Research Manager"
if current_response.startswith("Bull"):
    return "Bear Researcher"
return "Bull Researcher"
```

- 初始 `current_response=""`、count=0 → Bull。
- Bull 写入前缀 `Bull Analyst:` → 下一条 Bear。
- Bear 写入前缀 `Bear Analyst:` → 下一条 Bull。
- count 达阈值 → Research Manager。
- 这是“基于字符串前缀的路由”，不是 `Speaker` enum。

#### Research Manager → Trader

```text
Research Manager 完成 → Trader
```

无 conditional edge。它执行一次研究 judge，写 `investment_plan` 后进入 Trader。

#### Trader → Aggressive

```text
Trader 完成 → Aggressive Analyst
```

无 conditional edge。Trader 不判断 action 是否 Hold，也不提前短路风险辩论。

#### 三方风险辩论

`should_continue_risk_analysis`：

```python
if risk_debate_state["count"] >= 3 * max_risk_discuss_rounds:
    return "Portfolio Manager"
if latest_speaker.startswith("Aggressive"):
    return "Conservative Analyst"
if latest_speaker.startswith("Conservative"):
    return "Neutral Analyst"
return "Aggressive Analyst"
```

- 初始 latest_speaker 为空，进入 Aggressive。
- Aggressive → Conservative → Neutral → Aggressive，直到 count 达阈值。
- 达阈值后进入 Portfolio Manager。
- PM 虽然写入 `latest_speaker="Judge"`，但图在 PM 后直接 END，不会再经过 risk conditional。

#### Portfolio Manager → END

```text
Portfolio Manager 完成 → END
```

没有图内 quality gate 后置边；Quality Gate 实际位于 Analyst 之后、Bull 之前，而不是 PM 之后。

### 4.3 目标图与实现图的差异清单

| 目标描述 | 实际代码 |
|---|---|
| 7 Analyst 并行 | 7 Analyst 串行，只有 Analyst ↔ ToolNode 循环 |
| research_manager 先 judge，再 bull/bear | 先 Quality Gate → Bull/Bear 循环 → Research Manager judge |
| 研究 manager final plan 再 trader | Research Manager 一次执行；同一节点是投资辩论结束后的 judge/plan |
| trader → 3 debator | 正确，但三方按 Aggressive → Conservative → Neutral 顺序循环，不是并行 |
| research_manager judge risk | 实际由 Portfolio Manager 写 `risk_debate_state.judge_decision`；Research Manager 不参与风险 judge |
| portfolio_manager → quality_gate → END | 实际 Portfolio Manager → END；Quality Gate 在前 |
| Quality Gate 纯规则 | 硬检查是规则，但 fail_count<4 时有一次 LLM review |
| 17 业务 Agent | 当前代码 16 个业务节点，另有辅助节点 |

---

## 5. 数据流：从 A 股数据源到决策

### 5.1 真实端到端数据流

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ A 股 vendor / external APIs                                                   │
│                                                                               │
│ mootdx TCP: bars / finance / F10                                               │
│ 新浪 HTTP: K 线 fallback / 三张财报 / 个股新闻 fallback                        │
│ 东财 push2/push2his/datacenter/np-weblist/np-ipick                            │
│ 同花顺: EPS forecast / hot stocks / hsgt northbound                           │
│ 财联社 CLS: global wire                                                        │
│ 百度 PAE: concept blocks                                                       │
└───────────────┬───────────────────────────────────────────────────────────────┘
                │ route_to_vendor() → tool facade
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 7 Analyst（当前串行；每个 Analyst 内部可多轮 tool loop）                       │
│                                                                             │
│ Market       → get_stock_data + get_indicators → market_report               │
│ Social       → get_news → sentiment_report                                   │
│ News         → get_news + get_global_news → news_report                      │
│ Fundamentals → fundamentals/financials/forecast/industry → fundamentals_report│
│ Policy       → get_news + get_global_news → policy_report                     │
│ Hot Money    → sector digest + flow + LHB + northbound + concepts → hot_money │
│ Lockup       → insider + fundamentals + news + lockup calendar → lockup_report│
└───────────────┬───────────────────────────────────────────────────────────────┘
                │ 7 text reports in AgentState
                ▼
        Quality Gate: hard grade A/B/C/D/F + optional LLM review
                │ data_quality_summary（不阻断）
                ▼
        Bull Researcher ↔ Bear Researcher
                │ investment_debate_state.history / bull_history / bear_history
                ▼
        Research Manager
                │ investment_plan + investment judge
                ▼
        Trader
                │ trader_investment_plan（Buy/Hold/Sell proposal）
                ▼
        Aggressive ↔ Conservative ↔ Neutral
                │ risk_debate_state histories / latest_speaker
                ▼
        Portfolio Manager
                │ final_trade_decision + risk judge
                ▼
        SignalProcessor.parse_rating + memory/log/UI
```

### 5.2 数据源到工具的映射

| 工具 facade | `a_stock.py` 函数 | 主要外部来源 / 结果 | 使用 Agent |
|---|---|---|---|
| `get_stock_data` | `get_stock_data` | mootdx bars；Sina、push2his fallback；OHLCV | Market、Hot Money |
| `get_indicators` | `get_indicators` | 上述 OHLCV + stockstats；白名单指标 | Market |
| `get_fundamentals` | `get_fundamentals` | 腾讯报价、mootdx finance、东财 push2、同花顺 EPS | Fundamentals、Lockup |
| `get_balance_sheet` | `get_balance_sheet` | 新浪财报 API | Fundamentals |
| `get_cashflow` | `get_cashflow` | 新浪财报 API | Fundamentals |
| `get_income_statement` | `get_income_statement` | 新浪财报 API | Fundamentals |
| `get_news` | `get_news` | 东财个股搜索；新浪个股新闻 fallback | Social、News、Policy、Hot Money、Lockup |
| `get_global_news` | `get_global_news` | CLS Wire + 东财 7×24 | News、Policy |
| `get_insider_transactions` | `get_insider_transactions` | mootdx F10 股东研究 | News tool set、Hot Money、Lockup |
| `get_profit_forecast` | `get_profit_forecast` | 同花顺一致预期 EPS / forward PE / PEG | Fundamentals |
| `get_hot_stocks` | `get_hot_stocks` | 同花顺涨停股与题材标签 | Hot Money；sector digest 内部调用 |
| `get_northbound_flow` | `get_northbound_flow` | 同花顺 hsgtApi；本地 20 日 CSV 缓存 | Hot Money |
| `get_concept_blocks` | `get_concept_blocks` | 百度股市通 PAE | Hot Money |
| `get_fund_flow` | `get_fund_flow` | 东财 push2 实时 + push2his 20 日 | Hot Money |
| `get_dragon_tiger_board` | `get_dragon_tiger_board` | 东财 datacenter 龙虎榜/席位 | Hot Money |
| `get_lockup_expiry` | `get_lockup_expiry` | 东财 datacenter `RPT_LIFT_STAGE` | Lockup |
| `get_industry_comparison` | `get_industry_comparison` | 东财 push2 90/100 行业板块 | Fundamentals、Hot Money |
| `get_sector_rotation_digest` | `get_sector_rotation_digest` | np-ipick + 同花顺 + 百度 PAE；结果有 `sources_ok` | Hot Money |

### 5.3 Vendor 路由与数据契约

工具并不直接 import 并调用某个 vendor；`agents/utils/*_tools.py` 的 `@tool` 包装器统一调用 `route_to_vendor(method, ...)`。`dataflows/interface.py` 维护：

- category → tool 列表；
- method → vendor 实现映射；
- config 的 category-level / tool-level vendor override；
- vendor fallback chain。

默认配置 `data_vendors` 将 core stock、technical、fundamental、news、signal 全部指向 `a_stock`。这为数据接入提供了一个较好的 adapter seam，但 Agent 侧看到的返回类型依旧是 `str`（`get_sector_rotation_digest` facade 把 dataclass 转成 Markdown），数据来源、采集时间和失败状态没有进入 AgentState 的 typed evidence。

### 5.4 数据流不变量

1. **时间一致性**：工具 prompt 应使用 `trade_date`，`a_stock` 内部有截止日期过滤；但最终报告是字符串，无法证明所有工具都遵守同一 as-of 约束。
2. **来源可追溯性**：很多工具在 Markdown header 写 `Data source`，但没有统一 `Evidence` schema，不能程序化关联报告与来源。
3. **部分失败可传播**：工具常把异常转成 `Error ...` 或 `No data ...` 字符串，Analyst 再写成报告；Quality Gate 只能通过文本 marker 近似识别。
4. **报告完整性**：Quality Gate 的最小检查只认长度、表格和 `[数据缺失`，不验证具体必采字段是否真的出现。
5. **消息隔离**：每个 Analyst 完成后 clear messages，后续 Analyst 只看到初始 `Continue`，其跨角色知识传递主要依赖共享报告字段，而非消息。

---

## 6. Pydantic Schemas：结构化决策接口

`tradingagents/agents/schemas.py` 共 228 行。它只覆盖 3 个决策 Agent，不覆盖 7 Analyst、辩论 Agent 或 Quality Gate。

### 6.1 `PortfolioRating` enum

```python
class PortfolioRating(str, Enum):
    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"
```

- **用途**：Research Manager 的投资推荐和 Portfolio Manager 的最终评级共用五档值。
- **输出者**：`ResearchPlan.recommendation`、`PortfolioDecision.rating`。
- **DDD 意义**：这是当前最明确的决策值对象；但 render 后又变回文本，进入 state 的字段类型仍是 `str`。

### 6.2 `TraderAction` enum

```python
class TraderAction(str, Enum):
    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"
```

- **用途**：交易方向只有 Buy/Hold/Sell；与五档投资评级区分，Overweight/Underweight 在 Trader 层被压缩。
- **输出者**：`TraderProposal.action`。
- **DDD 意义**：把“观点评级”和“执行方向”分成两个概念是正确的；但 state 中仍只存 render 后 Markdown。

### 6.3 `ResearchPlan`（Research Manager 输出）

| 字段 | 类型 / 默认 | 用途 |
|---|---|---|
| `recommendation` | `PortfolioRating`，必填 | 五档投资推荐 |
| `rationale` | `str`，必填 | 总结 Bull/Bear 关键论点，并说明哪一侧胜出 |
| `strategic_actions` | `str`，必填 | 给 Trader 的具体战略动作和仓位指导 |

- Render 函数：`render_research_plan`。
- 输出 Markdown headers：`**Recommendation**`、`**Rationale**`、`**Strategic Actions**`。
- 调用方式：`bind_structured(llm, ResearchPlan, ...)` + `invoke_structured_or_freetext`。
- fallback：结构化调用失败时直接普通 `llm.invoke`，返回未经 schema 校验的 `response.content`。

### 6.4 `TraderProposal`（Trader 输出）

| 字段 | 类型 / 默认 | 用途 |
|---|---|---|
| `action` | `TraderAction`，必填 | Buy/Hold/Sell 交易方向 |
| `reasoning` | `str`，必填 | 2–4 句、基于 Analyst 与 Research Plan 的理由 |
| `entry_price` | `Optional[float] = None` | 目标入场价 |
| `stop_loss` | `Optional[float] = None` | 止损价 |
| `position_sizing` | `Optional[str] = None` | 仓位建议，如 5% |

- Render 函数：`render_trader_proposal`。
- 固定保留 `FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**` 行，兼容旧解析器。
- 输出者：Trader。
- 可选字段允许模型不提供价格/仓位，不存在代码级约束（例如 stop loss 必须与 entry 合理关系）。

### 6.5 `PortfolioDecision`（Portfolio Manager 输出）

| 字段 | 类型 / 默认 | 用途 |
|---|---|---|
| `rating` | `PortfolioRating`，必填 | 最终 Buy/Overweight/Hold/Underweight/Sell |
| `executive_summary` | `str`，必填 | 入场、仓位、风险位、时间周期的 2–4 句行动摘要 |
| `investment_thesis` | `str`，必填 | 引用具体证据的详细投资逻辑 |
| `price_target` | `Optional[float] = None` | 目标价 |
| `time_horizon` | `Optional[str] = None` | 建议持有周期 |

- Render 函数：`render_pm_decision`。
- 输出 headers：`**Rating**`、`**Executive Summary**`、`**Investment Thesis**`，可选 `**Price Target**`、`**Time Horizon**`。
- 输出者：Portfolio Manager。
- 下游 `SignalProcessor` 不再调用 LLM，只用 `parse_rating` 从 Markdown 提取评级。

### 6.6 结构化输出 helper 的实际策略

`agents/utils/structured.py`：

```text
create agent
  └─ bind_structured(llm, schema)
       ├─ with_structured_output 成功 → structured_llm
       └─ NotImplementedError/AttributeError → None，永久走 free text

invoke
  ├─ structured_llm.invoke(prompt) 成功 → Pydantic instance → render Markdown
  ├─ structured invoke 任意异常 → warning → plain_llm.invoke(prompt)
  └─ plain response.content
```

因此当前架构已经不是“所有 LLM 输出都靠 JSON parsing”：3 个决策 Agent 首选 Pydantic structured output，且有 free-text fallback。但 fallback 的代价是：

- 同一个决策字段可能是 typed render 或任意自然语言；
- provider 不支持 structured output 时，每次都退化，没有 capability registry；
- 失败路径不重试 structured invocation，也不做二次 JSON repair；
- fallback 文本可缺失关键 section，质量错误直到 `parse_rating` 或 UI 才暴露；
- Analyst 与辩论 Agent 仍全部是自由文本。

---

## 7. Quality Gate：特殊的混合节点

### 7.1 位置与真实职责

`GraphSetup.setup_graph` 将 Quality Gate 放在最后一个 Analyst 的 `Msg Clear` 后：

```text
last selected Analyst
  → Msg Clear last Analyst
  → Quality Gate
  → Bull Researcher
```

它不是 PM 后的最终安全门，也不阻止下游图运行。它是一个**研究证据进入辩论前的质量摘要器**。

### 7.2 Layer 1：规则硬检查

`REPORT_FIELDS` 固定 7 个报告与 analyst type 映射；`_hard_check_report` 对每个报告返回 `(grade, detail)`：

| 条件 | Grade | 说明 |
|---|---|---|
| 空或全 whitespace | F | 报告为空 |
| 长度 `< MIN_REPORT_LENGTH`，其中 `MIN_REPORT_LENGTH=200` | D | 报告过短 |
| 包含失败 marker，移除 marker 后仍 `<200` | D | 主要由失败信息组成 |
| 无 `|` 且无 `---` | B | 缺少 Markdown 汇总表格 |
| 含 `[数据缺失` 但少于 3 处 | B | 有缺失但整体可用 |
| 缺失数 `>=3` | C | 需谨慎使用 |
| 长度足够、有表格、无 marker/缺失 | A | `完整 (length chars)` |

`FAILURE_MARKERS`：`无法获取`、`I cannot retrieve`、`I don't have access`、`unable to fetch`、`工具调用失败`。

硬检查结果被拼成 7 行摘要，`fail_count` 统计 Grade D/F。

### 7.3 Layer 2：可选 LLM review

当 `fail_count < 4`：

```python
review_prompt = _build_review_prompt(reports, trade_date, ticker)
response = llm.invoke(review_prompt)  # 一次 quick LLM 调用
llm_review = response.content
```

LLM 被要求逐一审核 7 份报告，并输出 A/B/C/D/F、时效、缺失项、备注和整体可信度。每个报告在 review prompt 中最多截断到 3000 字符。

当 `fail_count >= 4`：

- 跳过 LLM review；
- summary 写入“跳过 — 多数报告未通过硬检查”。

LLM 异常不会抛出阻断图，而是写入 `（LLM 复审失败: ExceptionType: message）`。

### 7.4 输出与“pass/warn/fail”差异

代码实际输出：

```text
## 数据质量门控结果

**标的**: <ticker> | **交易日**: <date>

### 硬检查结果
- 技术分析师: [A/B/C/D/F] ...
...

### LLM 复审
<review markdown 或跳过/失败文本>
```

因此 `data_quality_summary` 是一段 Markdown `str`，不是：

```python
QualityStatus.PASS | QualityStatus.WARN | QualityStatus.FAIL
```

也没有单独字段承载每个 Analyst 的 grade、缺失字段列表、freshness、source health。下游 Bull/Bear 只能把整段文本放入 prompt，依赖 LLM 自己理解“C/D/F”。

### 7.5 与任务假设的核对

| 任务假设 | 代码事实 |
|---|---|
| 非 LLM Agent | 不准确：规则层之外有可选一次 LLM review |
| 输入 7 Analyst reports | 正确 |
| 输入投资辩论 + 风控辩论 | 不成立：Quality Gate 位于二者之前，state 中尚无辩论产物 |
| 输出 pass/warn/fail | 不成立：输出 Markdown 字符串，内部 grade 是 A/B/C/D/F |
| 数据缺失或异常触发 | 正确，但触发只改变 grade 和是否跳过 LLM，不阻断 graph |
| PM 后执行 | 不成立：Analyst 后、Bull 前执行 |

### 7.6 DDD 视角

Quality Gate 更像一个**EvidenceQualityPolicy / Domain Service**，被包装成 LangGraph node，而不是拥有独立生命周期的聚合根。它同时包含确定性规则与可变 LLM reviewer，导致两个职责混在一起：

1. `HardQualityChecker`：纯函数，输入报告文本，输出结构化 grade；
2. `QualityReviewer`：LLM adapter，输入规范化证据，输出可解释 review；
3. `QualityGate`：合并两者并决定继续策略（当前没有真正 gate）。

推荐将这三个概念分开，同时保留 graph node 作为编排 adapter。

---

## 8. Agents 层现有架构债务

以下债务均针对 `tradingagents/agents/` 与 `tradingagents/graph/`，不重复第一轮 backend/core 的 store 债务。

### Debt A1：业务 Agent 计数和目录边界不清

**证据**：`agents/__init__.py` 导出 16 个 `create_*` 业务工厂；`graph/setup.py` 添加 16 个业务节点，另有 `Msg Clear` 和 `ToolNode` 辅助节点。产品/CLAUDE 口径写 7 Analyst + Bull/Bear + 三风险 + Trader + 两 Manager + quality gate，但相加是 16。

**后果**：架构图、监控 stage_map、验收指标会把辅助节点误算业务角色；新增“第 17 个”时缺少明确 bounded responsibility。

**严重度**：🟡 中。

### Debt A2：7 Analyst 声称并行，代码实际串行

**证据**：`setup.py:139-162` 通过 `START → first_analyst` 和每个 `current_clear → next_analyst` 建立线性边，没有 LangGraph fan-out/fan-in。

**后果**：总延迟近似 7 个 Analyst tool loop 串联；一个 Analyst 卡住会阻塞全部研究；“并行独立证据”没有真正的并发语义。

**严重度**：🟠 高。

### Debt A3：Quality Gate 名义为门禁，实际上不 gate

**证据**：`Quality Gate → Bull Researcher` 是无条件边；`data_quality_summary` 只注入 Bull/Bear prompt；不存在 fail 分支、降级分支或终止边。

**后果**：即使 7 份报告全部 F/D，流程仍继续产生 Buy/Sell 决策；数据质量没有成为 domain policy，只是 prompt 提示。

**严重度**：🔴 高。

### Debt A4：Quality Gate “规则/LLM”边界和输出协议不稳定

**证据**：`quality_gate.py` 明确调用 `llm.invoke`，但任务/注释容易把它当纯非 LLM Agent；输出 `str`，内部 grade A/B/C/D/F，外部预期却是 pass/warn/fail。

**后果**：测试必须解析 Markdown；无法稳定决定是否允许辩论；LLM 复审失败也变成字符串，不易观测。

**严重度**：🟡 中高。

### Debt A5：Agent 接口是闭包工厂，不是可发现/可替换的 registry

**证据**：`agents/__init__.py` 导出 16 个 `create_*` 业务工厂；`graph/setup.py` 手工写 7 个 if、手工写所有 `add_node` 和 conditional edge；没有 `AgentSpec`、registry、capability 或 role Protocol。Trader 返回 `functools.partial`。另外，`hot_money_tracker.py` 的工具绑定声明了 `get_sector_rotation_digest`，但 `TradingAgentsGraph._create_tool_nodes()` 的 `hot_money` ToolNode 列表未注册该工具，提示词/节点能力存在漂移。

**后果**：新增角色需要同时改 import、setup、tool nodes、边和 conditional logic；无法按角色发现、单独实例化、替换 fake 或生成拓扑检查；模型可能请求未注册工具，运行期才失败。

**严重度**：🟡 中高。

### Debt A6：统一状态类型与运行时 schema 校验缺失

**证据**：`AgentState` 是 `MessagesState` 子类，字段用 `Annotated` 描述；子状态是 `TypedDict`；各 Agent 返回裸 `dict`，手工重建嵌套 state。没有 Pydantic `model_validate`、transition validator、字段必需性检查。

**后果**：拼写错误、遗漏嵌套字段、空字符串、错误 speaker、count 回退都可能进入下一节点；错误常在很晚的 prompt 或 KeyError 才暴露。

**严重度**：🔴 高。

### Debt A7：字符串承担报告、决策、失败和缺失四种语义

**证据**：所有报告是 `str`；工具异常返回 `Error...` 字符串；空报告也可能是 Analyst 尚未结束；structured fallback 又把任意 free text 写入 `investment_plan`、`trader_investment_plan`、`final_trade_decision`。

**后果**：下游只能靠关键词、Markdown header、前缀和 LLM 解释；无法做可靠的 completeness/freshness/source validation。

**严重度**：🔴 高。

### Debt A8：LLM 调用不可预测，tool loop 和 fallback 没有统一预算

**证据**：Analyst 每次 tool call 都重新 `chain.invoke`；structured decision failure 会再次普通 invoke；Quality Gate 还可能额外一次 LLM；没有 per-agent call budget、timeout、retry policy 或 cost envelope。

**后果**：一轮 run 的 LLM 次数和 token 成本依赖模型行为；工具循环可能触及 LangGraph recursion limit；监控只能通过 callback 事后统计。

**严重度**：🟠 高。

### Debt A9：结构化输出只覆盖 3 个决策 Agent，fallback 消除了类型边界

**证据**：`schemas.py` 只有 ResearchPlan、TraderProposal、PortfolioDecision；`structured.py` 在任何结构化异常后直接 `plain_llm.invoke` 返回 `response.content`。

**后果**：同一 state 字段两种形状；Portfolio Manager 的 P2.23 类 structured-output failure 会静默变成 free text（仅 warning），直到后续 parser/用户看到异常。

**严重度**：🟠 高。

### Debt A10：辩论通过字符串前缀和手工 count 路由

**证据**：`should_continue_debate` 判断 `current_response.startswith("Bull")`；风险判断 `latest_speaker.startswith("Aggressive")` 等；count 由各节点 `+1`。

**后果**：模型内容/代码改动导致路由错误；没有显式 `Speaker`、`Round`、`DebatePhase` value object；并发/重试时 count 幂等性不清楚。

**严重度**：🟡 中高。

### Debt A11：跨 Agent 耦合通过全量共享 State 和超长 prompt

**证据**：Bull/Bear 和三风险 Agent 都手工读取全部 7 个报告 + 多个历史字段；Portfolio Manager 读取风险历史、研究计划、Trader 计划和 past context。没有最小输入 DTO 或 ACL。

**后果**：任何字段改名会影响大量 Agent；prompt 体积随历史追加增长；角色职责与 context assembly 混在一个闭包内。

**严重度**：🟠 高。

### Debt A12：Agent 不可脱离 LangGraph runtime 做自然单测

**证据**：Analyst 依赖 `state["messages"]`、LangChain message 对象、`llm.bind_tools`、ToolNode；Manager 依赖 structured wrapper；GraphSetup 才能串起真实输入。虽然工厂可以注入 fake LLM，但没有显式 input/output Protocol 和最小 DTO。

**后果**：单测需要构造 LangGraph 风格 state/message，难以独立验证“报告生成”“辩论转移”“决策渲染”；图级集成测试成为主要防线。

**严重度**：🟡 中高。

### Debt A13：数据来源追溯和证据质量没有 typed provenance

**证据**：`a_stock.py` 工具输出带不同格式的 source header；`AgentState` 只有 7 个文本报告，没有 `source/vendor/retrieved_at/as_of/partial_failure` 字段。

**后果**：无法回答某个投资结论依赖哪条数据、数据是否过期或 vendor 是否 fallback；Quality Gate 只能做文本启发式。

**严重度**：🟡 中高。

### Debt A14：图编排把业务顺序、工具执行、消息清理写在同一 setup 中

**证据**：`GraphSetup.setup_graph` 同时创建工厂、注册 ToolNode、添加业务节点、定义 Analyst conditional、清理边、辩论边、风险边和 END。

**后果**：拓扑变更风险大；无法分别测试 graph policy、role implementation、tool policy；并行化会触及大量手工边。

**严重度**：🟡 中高。

### Debt A15：文档/实现中的风险 judge 归属不一致

**证据**：任务描述写“research_manager judge risk”，但代码 `Portfolio Manager` 将 `final_trade_decision` 写入 `risk_debate_state.judge_decision`；Research Manager 只写投资辩论 state。

**后果**：监控、阶段报告、领域语言把“研究计划”“风险 judge”“组合决策”混为一谈。

**严重度**：🟡 中。

### Debt A16：没有真正的 fail-fast / retry / timeout 语义

**证据**：Analyst 工具错误常被转成文本继续；Quality Gate LLM 异常转文本；structured output 失败只 fallback 一次；普通辩论 LLM 直接 invoke，没有统一 try/except 或 per-node timeout。

**后果**：失败被“成功的文本”掩盖；图可能产出看似完整但证据为空的最终评级。

**严重度**：🟠 高。

---

## 9. DDD 重构建议（按优先级）

### R1（最高 ROI）：定义 Agent Protocol 与最小输入/输出 DTO

建立明确的应用层接口，而不是让所有节点都接收全量 `AgentState`：

```python
class IAnalyst(Protocol):
    role: AnalystRole
    def analyze(self, request: AnalystRequest) -> AnalystReport: ...

class IDebator(Protocol):
    role: DebateRole
    def argue(self, request: DebateRequest) -> DebateArgument: ...

class IManager(Protocol):
    role: ManagerRole
    def decide(self, request: ManagerRequest) -> DecisionArtifact: ...
```

- `AnalystRequest`：ticker、as_of、instrument context、工具 gateway、language；
- `AnalystReport`：role、content、grade candidate、evidence refs、source health、retrieved_at；
- `DebateArgument`：speaker enum、round、content、claims；
- `DecisionArtifact`：typed schema + rendered Markdown。

LangGraph node 只做 DTO ↔ AgentState adapter。收益：独立单测、角色替换、调用预算和 registry 都有 seam。

### R2：将 AgentState 重构为“typed aggregate + transition commands”

保留 LangGraph 需要的 dict 兼容层，但领域核心使用 Pydantic model（或 frozen dataclass + Pydantic validation）：

```python
class AnalysisAggregate(BaseModel):
    analysis_id: AnalysisId
    instrument: Instrument
    as_of: TradeDate
    evidence: EvidenceBundle
    quality: QualitySummary
    investment_debate: InvestmentDebate
    research_plan: ResearchPlan | None
    trader_proposal: TraderProposal | None
    risk_debate: RiskDebate
    final_decision: PortfolioDecision | None
```

每个 transition 使用显式方法：`record_report`、`complete_quality_review`、`append_investment_argument`、`publish_research_plan`、`publish_trader_proposal`、`append_risk_argument`、`publish_final_decision`。方法中校验 phase、speaker、count 单调和 required fields。

### R3：把报告从 `str` 提升为 Evidence / Report value object

建议至少包含：

```python
class AnalystReport(BaseModel):
    role: AnalystRole
    text: str
    as_of: date
    retrieved_at: datetime
    sources: list[SourceRef]
    missing_items: list[str]
    failed_sources: list[str]
    completeness: float | None
```

这会将 `Error...`、`No data...`、`[数据缺失: ...]` 从 prompt 文本解析升级为可验证数据。Quality Gate 可以同时支持规则与 LLM，并能用 source health 做阻断策略。

### R4：将 Quality Gate 拆成可插拔规则策略 + LLM reviewer + policy decision

```text
HardQualityChecker (纯函数) → QualityFinding[]
LLMQualityReviewer (可选 adapter) → QualityReview
QualityPolicy (可配置) → PASS / WARN / FAIL + next transition
QualityGateNode (LangGraph adapter) → state update / route
```

- 规则结果用 `QualityGrade` 和 `QualityStatus` enum；
- LLM review 是可选策略，不改变 gate interface；
- `FAIL` 明确进入 `END`/`degraded_research`/`retry_analysts` 分支，而不是无条件 Bull；
- policy 可按报告数量、交易日、数据源健康、模型配置切换；
- Quality Gate 若要放到 PM 后，应另建 `FinalDecisionGate`，不要复用同一概念。

### R5：真正实现 analyst fan-out / fan-in，或诚实命名为串行

若目标是降低延迟：

```text
START → [Market, Social, News, Fundamentals, Policy, HotMoney, Lockup] 并行
      → AnalystReport fan-in / merge
      → Quality Gate
```

需要配套：

- 独立 message context，不再共享单一 `MessagesState`；
- merge reducer 只允许每个 role 写自己的 report key；
- tool/LLM timeout 与 per-agent failure result；
- fan-in barrier 检查 selected roles 是否都返回（或显式 degraded）；
- 基于 node id 的追踪，不依赖 `stage_map` 字符串猜测。

若出于 vendor rate-limit 或成本原因暂不并行，应把产品/CLAUDE 文档改为“serial analyst pipeline”，避免错误的领域语言。

### R6：建立 Agent Registry 与声明式 graph spec

```python
@dataclass(frozen=True)
class AgentSpec:
    role: str
    factory: Callable
    phase: Phase
    input_fields: frozenset[str]
    output_fields: frozenset[str]
    tools: tuple[str, ...]
    llm_policy: LLMPolicy
```

Registry 负责：

- role → factory / capabilities；
- selected analyst 校验；
- 工具白名单和预算；
- graph topology 生成；
- 监控/日志统一 role 名；
- 防止 `GraphSetup` 的手工 if/边复制。

### R7：统一 LLM Gateway、调用预算和失败策略

建立 `ILLMInvoker`：

```python
result = invoker.invoke(
    prompt=prompt,
    schema=ResearchPlan,
    role="research_manager",
    max_calls=2,
    timeout_s=60,
    retry_policy=RetryPolicy(...),
)
```

明确区分：

- tool call loop 的单次模型 call；
- structured output retry；
- provider capability fallback；
- transient error retry；
- permanent schema error；
- budget exhausted。

所有调用都返回 `LLMResult[T]`（success / failure / fallback_used / attempts / tokens / provider），不把异常压成普通报告文本。

### R8：保持 typed schema 到 state，不要立即 render 再丢类型

当前 render helper 对 UI 兼容有价值，但应同时保存：

```python
research_plan: ResearchPlan
investment_plan_markdown: str
trader_proposal: TraderProposal
trader_plan_markdown: str
portfolio_decision: PortfolioDecision
final_trade_decision_markdown: str
```

下游 Agent 消费 typed object 或专用 DTO；Markdown 只作为显示、日志和向后兼容出口。`SignalProcessor` 可直接消费 `PortfolioDecision.rating`，旧文本解析作为 adapter。

### R9：用 Enum / round object 替换字符串前缀路由

```python
class InvestmentSpeaker(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    JUDGE = "judge"

class RiskSpeaker(str, Enum):
    AGGRESSIVE = "aggressive"
    CONSERVATIVE = "conservative"
    NEUTRAL = "neutral"
    JUDGE = "judge"
```

`ConditionalLogic` 应读取 `last_speaker` 和 `round_no`，不读取 LLM 文本的前缀。转移规则放在纯函数 `next_investment_turn` / `next_risk_turn` 中，可表格化测试。

### R10：拆分 context assembly 与 Agent reasoning

当前每个 closure 同时做：读取 state、拼接长 prompt、绑定 tools、调用 LLM、包装输出。可拆为：

```text
ContextAssembler → Prompt / ToolRequest DTO
LLM Adapter       → RawModelResult
OutputParser      → typed AgentArtifact
StateAdapter      → LangGraph update dict
```

收益：提示词变更不会改变状态转换；同一研究报告 context 可复用；对 prompt 注入、token 长度和截断策略可单测。

### R11：为工具建立强类型 `DataGateway` 与 provenance

工具 facade 已通过 `route_to_vendor` 有 adapter 雏形，下一步应从统一 `str` 返回升级：

```python
class MarketDataGateway(Protocol):
    def ohlcv(self, ticker: Ticker, as_of: TradeDate) -> DataResult[OHLCV]: ...
    def fundamentals(...) -> DataResult[Fundamentals]: ...
    def news(...) -> DataResult[list[NewsItem]]: ...
```

每次 `DataResult` 带 primary vendor、fallback vendor、retrieved_at、partial flag、error code。Agent 工具 wrapper 再将其转换成模型上下文。

### R12：为每个 Agent 建立不依赖图的 contract tests

最低测试层次：

1. **Pure tests**：quality hard check、debate transition、render/parse、schema invariants；
2. **Agent contract tests**：fake LLM + fake gateway，输入最小 DTO，验证输出 artifact；
3. **Graph topology tests**：节点集合、边、selected analyst、fan-in、fail branch；
4. **Integration tests**：少量真实 LangGraph invoke；
5. **Failure tests**：tool empty/error、structured output malformed、LLM timeout、partial reports、count corruption。

这样无需每次启动完整 graph 才能发现一个 Agent 漏写 `neutral_history` 或错误返回 `sender`。

### R13：明确“风险 judge”归属和语言

建议采用以下 Ubiquitous Language：

- `Research Manager`：投资辩论 judge，发布 `ResearchPlan`；
- `Trader`：执行提案，发布 `TraderProposal`；
- `Risk Debate Facilitator`（可作为 manager 或 graph policy）：只负责风险辩论转移；
- `Portfolio Manager`：风险辩论 judge + 最终组合决策，发布 `PortfolioDecision`；
- `Final Decision Gate`：可选的 PM 后质量/合规门禁。

不要把 Portfolio Manager 通过嵌套字段写入 `risk_debate_state.judge_decision` 叫作“Research Manager judge risk”。

### R14：为 observability 设计稳定的 AgentRun / TransitionEvent

每个节点/工具调用记录：

- analysis id、ticker、trade_date、role、phase、round；
- input field names（不记录敏感 prompt 全文）；
- output artifact type、quality、attempts、fallback；
- tool/vendor、latency、error code；
- state transition before/after version。

这样可以直接回答“本次最终 Sell 是哪份报告、哪家 vendor、哪轮辩论影响的”，并替代目前通过日志 chunk 猜测 agent stage 的方式。

---

## 10. DDD 建模建议：核心聚合与上下文

### 10.1 建议的 Core Domain 聚合

```text
AnalysisDecision (aggregate root)
├── AnalysisIdentity (Ticker + TradeDate + AnalysisId)
├── EvidenceBundle
│   ├── AnalystReport[market/social/news/fundamentals/policy/hot_money/lockup]
│   └── QualitySummary
├── InvestmentDebate
│   ├── DebateArgument[Bull/Bear]
│   └── ResearchPlan
├── ExecutionProposal
│   └── TraderProposal
├── RiskDebate
│   ├── DebateArgument[Aggressive/Conservative/Neutral]
│   └── RiskAssessment
└── PortfolioDecision
```

### 10.2 可能的 bounded context / adapter

```text
Market Evidence Context
  └─ DataGateway adapters (mootdx / Sina / Eastmoney / THS / CLS / Baidu)

Research Debate Context
  └─ Bull, Bear, Research Manager

Execution & Risk Context
  └─ Trader, three risk roles, Portfolio Manager

Quality & Policy Context
  └─ hard checks, LLM review, quality policy

Workflow / Delivery Context
  └─ LangGraph nodes, reducers, checkpoints, streaming, log adapters
```

当前实现把这些 context 的实现全部放进 graph state 和闭包中；建议先用 Protocol/DTO 建 seam，再逐步物理拆目录，避免一次性重写。

### 10.3 不应过度建模的部分

- Analyst 报告不是 7 个独立持久化聚合；它们更像同一分析 aggregate 下的 evidence entities/value objects。
- Bull/Bear/Aggressive 等角色本身不是长期有身份的实体，而是一次 run 中的 strategy/agent role。
- `ToolNode`、`Msg Clear`、`SignalProcessor` 是 workflow/application infrastructure，不是领域 Agent。
- Markdown report 是 read model / delivery representation，不应成为 domain truth。

---

## 11. 验证矩阵与结论

### 11.1 需求条目完成情况

| 要求 | 本文结论 |
|---|---|
| 17 Agent 分类 | 已列出全部 16 业务 Agent，并明确第 17 个不存在的代码证据与辅助节点口径 |
| 每 Agent 职责、输入、输出、LLM、数据源 | §2 完成；数据源追溯到 `a_stock.py` |
| AgentState 聚合根 | §3 完成，按字段列出类型、来源、消费者、不变量 |
| LangGraph 状态机 ASCII | §4 完成，按实际图绘制，并解释所有条件边 |
| 数据流 | §5 完成，包含 vendor、tool facade 和决策路径 |
| Pydantic schemas | §6 完成，覆盖 enum、字段、用途、输出 Agent、fallback |
| Quality Gate | §7 完成，纠正“纯 LLM / 纯规则 / pass-warn-fail / PM 后”的不准确假设 |
| 5+ 架构债务 | §8 列出 16 项，均给证据与严重度 |
| 5+ 重构建议 | §9 列出 14 项，含 Protocol、typed state、显式 transitions、typed LLM、pluggable gate |
| 不改 code / 不 commit | 本轮只创建本文档；验证见 §12 |

### 11.2 核心判断

1. **真正的 Core Domain 不在单个 prompt，而在 AgentState 的证据—辩论—执行—风险—组合决策转移**。
2. **当前图是串行多 Agent workflow，不是并行多 Agent workflow**；这既影响性能，也影响领域语言的准确性。
3. **Quality Gate 是前置证据质量摘要器，不是终态门禁**；它含可选 LLM，输出文本且不阻断流程。
4. **Pydantic 已用于 3 个决策 schema，但 render/fallback 把类型边界重新降为字符串**。
5. **辩论路由依赖字符串前缀和 count，状态聚合根缺少显式 transition/invariant enforcement**。
6. **A 股数据接入已经有 `route_to_vendor` adapter seam，但 provenance 没进入 State，导致质量检查只能做文本启发式**。
7. **最先值得做的不是增加 Agent 数量，而是纠正角色计数、明确 State contract、拆 Quality Policy、统一 LLM/Data Gateway，并为 Agent 建立可脱离 LangGraph 的测试接口**。

---

## 12. 变更与可复现性记录

### 12.1 本轮创建/修改

- **创建**：`docs/DDD_AGENTS_DEEP_DIVE.md`
- **未修改**：`tradingagents/`、`backend/`、`web/`、`tests/`、`pyproject.toml`、spec、`docs/DDD_EXPLORATION.md`、`docs/DDD_ANALYSIS.md`
- **未提交**：没有执行 `git commit`。

### 12.2 读取的关键实现锚点

- `tradingagents/agents/utils/agent_states.py`：79 行，AgentState 与两个 TypedDict 子状态。
- `tradingagents/agents/schemas.py`：228 行，3 个 Pydantic 决策 schema。
- `tradingagents/agents/quality_gate.py`：168 行，硬检查 + 可选 LLM review。
- `tradingagents/graph/setup.py`：212 行，实际节点和边。
- `tradingagents/graph/conditional_logic.py`：91 行，tool/debate/risk 路由。
- `tradingagents/graph/propagation.py`：73 行，初始状态。
- `tradingagents/dataflows/interface.py`：vendor routing/fallback。
- `tradingagents/dataflows/a_stock.py`：A 股工具实际实现（OHLCV、财报、新闻、资金、解禁等）。

---

## 附录 A：Agent → State 读写速查

| Agent | 读取 | 写入 |
|---|---|---|
| Market | `company_of_interest`, `trade_date`, `messages` | `messages`, `market_report` |
| Social | `company_of_interest`, `trade_date`, `messages` | `messages`, `sentiment_report` |
| News | `company_of_interest`, `trade_date`, `messages` | `messages`, `news_report` |
| Fundamentals | `company_of_interest`, `trade_date`, `messages` | `messages`, `fundamentals_report` |
| Policy | `company_of_interest`, `trade_date`, `messages` | `messages`, `policy_report` |
| Hot Money | `company_of_interest`, `trade_date`, `messages` | `messages`, `hot_money_report` |
| Lockup | `company_of_interest`, `trade_date`, `messages` | `messages`, `lockup_report` |
| Quality Gate | `company_of_interest`, `trade_date`, 7 reports | `data_quality_summary` |
| Bull | 7 reports, quality, INV | `investment_debate_state` |
| Bear | 7 reports, quality, INV | `investment_debate_state` |
| Research Manager | `company_of_interest`, INV history | `investment_debate_state`, `investment_plan` |
| Trader | instrument, `investment_plan`, POL/HOT/LOCK | `messages`, `trader_investment_plan`, `sender` |
| Aggressive | 7 reports, trader, RISK | `risk_debate_state` |
| Conservative | 7 reports, trader, RISK | `risk_debate_state` |
| Neutral | 7 reports, trader, RISK | `risk_debate_state` |
| Portfolio Manager | instrument, RISK history, research plan, trader plan, past context | `risk_debate_state`, `final_trade_decision` |

## 附录 B：LLM 调用模式速查

| 类别 | 模式 | 固定/可变 |
|---|---|---|
| 7 Analyst | `ChatPromptTemplate` + `llm.bind_tools` + `chain.invoke` | 每个 tool loop 一次，可变；最终是自由文本 |
| Bull/Bear | `llm.invoke(prompt)` | 每个节点固定一次 |
| 3 Risk | `llm.invoke(prompt)` | 每个节点固定一次 |
| Research Manager | `with_structured_output(ResearchPlan)`，失败普通 invoke | 通常 1，失败最多 2 |
| Trader | `with_structured_output(TraderProposal)`，失败普通 invoke | 通常 1，失败最多 2 |
| Portfolio Manager | `with_structured_output(PortfolioDecision)`，失败普通 invoke | 通常 1，失败最多 2 |
| Quality Gate | hard checks；`fail_count < 4` 时普通 `llm.invoke(review_prompt)` | 0 或 1 |
| SignalProcessor | `parse_rating` | 0，确定性 |

## 附录 C：推荐的最小改造顺序（不代表本轮已实施）

```text
1. 纠正角色/阶段命名与文档口径
2. 为 Quality hard check 写纯函数测试并引入 QualityFinding schema
3. 为 Debate/Risk 路由引入 enum + round transition function
4. 为三种 decision schema 保留 typed object，不只存 render string
5. 定义 IAnalyst / IDebator / IManager / DataGateway Protocol
6. 建 Agent Registry + graph topology tests
7. 将 Analyst reports 改为 Evidence/Report DTO（含 provenance）
8. 再决定 fan-out/fan-in 并行化与 Quality Gate fail branches
```
