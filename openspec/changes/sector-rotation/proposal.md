# Sector Rotation Report

## Why

A 股市场的板块轮动 (sector rotation) 是短线择时与行业配置的核心信号——同一时段内不同板块的涨跌分化揭示资金流向、北向态度、机构调仓。但当前框架 (`hot_money_tracker` Analyst) 只能在单只股票的视角下串联 `get_concept_blocks` / `get_industry_comparison` / `get_fund_flow`，缺一条**板块级、独立可消费**的证据链：哪些板块今天最热、谁是龙头候选池、机构与编辑视角怎么看、是否值得追踪。

`v0.2.5` 立的"零第三方数据库依赖 + 全直连 HTTP"原则下,新增板块轮动能力**不能引入 API key、cookie、chromedp 等额外基础设施**。本 change 走"用现有数据源 + 反向 join 拼装"路径,新增 1 个 vendor 函数 + 1 个组合函数,产出独立可消费的"板块轮动日报"。

## What Changes

- **新增 vendor 函数** `get_hot_strategy_ranking(curr_date)`：调 `np-ipick.eastmoney.com/recommend/stock/heat/ranking`(东财选股热度,实测 5/5 稳定,无需 cookie),走 `_em_get()` 节流,返回 Top N 选股策略 + heatValue + 选股条件 question。
- **新增组合函数** `get_sector_rotation_digest(curr_date, top_n=20)`:
  1. 调 `get_hot_strategy_ranking` 拿机构/编辑视角热度
  2. 调 `get_hot_stocks` 拿同花顺涨停股(已有)
  3. 对涨停股 Top N 反查 `get_concept_blocks`(百度 PAE,批量接口,实测 0.48s/10 只)聚合"涨停密集概念板块"
  4. 输出 LLM 友好的 Markdown 日报
- **修改 `hot_money_tracker` Analyst**：在工具列表里加 `get_sector_rotation_digest`,prompt 注入"先看板块轮动大盘再聚焦个股"的工作流,避免 LLM 上来就钻个股细节。
- **Web UI 入口**：在 `web/app.py` 加"板块轮动"独立 tab,允许用户不启动完整 Analyst 链路就拿日报。

### Non-goals (明确不做的)

- ❌ 不引入雪球(`xueqiu.com` 实测 HTTP 400,需 cookie/chromedp)
- ❌ 不引入 `qgqp_b_id` cookie 机制(本项目零 cookie 接入)
- ❌ 不调用 push2/push2his 行业/概念接口(本机实测 0/5 不可用,生产环境需另行验证)
- ❌ 不新增独立"散户情绪"通道(数据源未找到零依赖方案)
- ❌ 不替换现有 `get_industry_comparison` / `get_concept_blocks`(它们仍是核心数据源,本 change 只**叠加**不替代)

## Capabilities

### New Capabilities
- `sector-rotation-digest`: 板块轮动日报 vendor 路由(数据获取 + 聚合 + Markdown 输出)
- `sector-rotation-analyst`: 板块轮动独立工作流(可选,作为 hot_money_tracker 的输入增强)

### Modified Capabilities
<!-- 现有 spec 没有 machine-readable 形式,CLAUDE.md 列出的"7 个 Analyst"是 ad-hoc 列表,不算 spec 级契约。本次 change 不修改 spec 级契约,只新增 -->
- (无)

## Impact

### 新增文件
- `tradingagents/dataflows/a_stock.py`: 新增 `get_hot_strategy_ranking()` + `get_sector_rotation_digest()`
- `tradingagents/agents/utils/signal_data_tools.py`: 新增 `get_sector_rotation_digest` 工具 wrapper
- `tradingagents/agents/analysts/hot_money_tracker.py`: 工具列表 + prompt 增强
- `tests/dataflows/test_sector_rotation.py`: 单元测试

### 修改文件
- `tradingagents/dataflows/interface.py`: 多 vendor 注册 `get_hot_strategy_ranking`
- `web/app.py`: Web UI tab 入口
- `CLAUDE.md`: 文档更新(v0.2.12)
- `README.md`: 文档更新
- `CHANGELOG.md`: 版本号

### 依赖
- **零新增依赖** —— 全部使用现有 `requests` + 项目内置 `_em_get()` 节流
- **零 API key** —— 所有端点实测 5/5 稳定可用
- **零 cookie** —— 不引入任何 cookie 机制

### 风险
- `np-ipick.eastmoney.com` 是东财子域名,理论上有被风控的可能(v0.2.11 防封原则适用),**必须走 `_em_get()` 节流**,默认 1s 间隔
- 百度 PAE 批量接口:实测 0.48s/10 只,30 只反查约 1.4s,本项目无并发,加 0.5s/req 节流到 ~16s,可用但偏慢
- 涨停股反查依赖 `zx.10jqka.com.cn` 同花顺稳定性(v0.2.5 起已确认)
