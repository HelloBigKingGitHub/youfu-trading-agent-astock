# Portfolio Module — Design

## Context

### 背景

现有框架定位是"投研引擎"——7 个 Analyst 通过 Bull/Bear 辩论生成 BUY/HOLD/SELL 报告。但**报告与"我持有什么"完全脱节**：

- LLM 在生成报告时**不知道**用户已经持仓多少、成本多少；
- 用户跑完 BUY 报告，**没有机制提醒**"是否要加仓 / 减仓 / 设止盈"；
- "今日盈亏 / 总盈亏 / 持仓集中度 / 大类资产配置"等个人化指标**全无**。

调研了 4 个国内主流 App（东方财富 / 雪球 / 腾讯自选股 / 有知有行）后，确认本模块的核心差异点是 **"投研 × 实盘闭环"**：

| 维度 | 4 个 App 共同点 | 本项目差异点 |
|---|---|---|
| 持仓录入 | 手动为主，券商同步为辅 | **手动为主**（用户用例已确认）；同步券商不在 v1 范围（零 cookie 原则） |
| 盈亏统计 | 当日 / 累计 / 年化 | **+ XIRR / 最大回撤 / 夏普 / Brinson**（有知有行深度，不学东方财富的"净值相减"伪收益率） |
| 资产配置 | 行业 / 板块 | **+ 大类资产（股/债/海外/现金）**（有知有行深度） |
| 预警 | 价格预警（基础） | **+ 模型信号变化 → 调仓推送**（本项目独有） |
| 数据来源 | 行情 + 公告 + 研报 | **+ 已有的 Bull/Bear 报告** |

### 当前状态（端点实测，2026-07）

| 端点 | 实测 | 状态 |
|---|---|---|
| `qt.gtimg.cn` (腾讯财经) | ✅ | **复用**（chart_panel / sector_panel 已在用，走 `_tencent_quote`） |
| `push2his.eastmoney.com` | ⚠️ 本机 SSL 问题 | 备用 |
| `zx.10jqka.com.cn` (同花顺概念板块) | ✅ | **复用** |
| `finance.pae.baidu.com` (百度 PAE) | ✅ | **复用** |
| `datacenter-web.eastmoney.com` (龙虎榜 / 板块) | ✅ | **复用** |
| `push2.eastmoney.com` (沪深 300 指数) | ⚠️ | 备用，需节流 |

### 约束

- v0.2.5"零第三方数据库依赖 + 全直连 HTTP"
- v0.2.11"东财接口统一走 `_em_get()` 节流防封"
- v0.4.0"走势图走 CDN + Lightweight Charts"
- 项目零 cookie、零 API key、零 chromedp
- 数据存储复用 `~/.tradingagents/`，对齐 `backend/core/history_store.py` 风格（dataclass + 单例 + 线程锁 + JSON 文件）

## Goals / Non-Goals

### Goals

1. **手动录入持仓 + 交易流水**：支持买入 / 卖出 / 分红 / 再投 / 打新 5 类事件
2. **完整盈亏统计**：当日 / 累计 / XIRR / 年化 / 最大回撤 / 夏普
3. **资产配置可视化**：行业 + 板块 + 大类资产（手动标记现金 / 海外 / 债券）+ 集中度
4. **价格预警**：7 种规则类型 + 按需触发 + 触发历史
5. **CSV 导入导出**：支持东财 / 同花顺 / 雪球 / 通用 4 种列名映射
6. **调仓推送**：diff Bull/Bear 报告信号变化，Tab 1 顶部横幅
7. **可测试**：单元测试覆盖率 ≥ 80%
8. **零新增第三方依赖**

### Non-Goals

- ❌ 券商实盘同步（接券商 API 需要 cookie / 二次验证）
- ❌ 融资融券 / 期权 / 港美股 / 可转债（超出 MVP 复杂度）
- ❌ 社交化大 V 跟随 / 实盘组合公开（不是投研引擎定位）
- ❌ OCR 截图识别（无可靠开源库）
- ❌ 持仓脱敏分享（P3 候选）
- ❌ 价格预警的"持久化通知 / 推送服务 / 邮件"（只做 `st.toast`，刷新即消）

## Decisions

### Decision 1: 数据存储走"单文件 JSON"而非 SQLite

**问题**：项目现有数据全是文件 + dataclass（history_store / log_store / job_queue），但 portfolio 涉及 3 个表（持仓 / 交易流水 / 预警）+ 频繁 CRUD + 频繁查询，是否应该升级到 SQLite？

**决策**：**保持单文件 JSON**，仿 `history_store.py` 风格。理由：

1. **数据规模小**：个人用户持仓 < 100 只，交易流水 < 1000 条，预警 < 50 条，全部 JSON 文件 < 100KB
2. **零依赖**：SQLite 需要 `sqlite3`（Python 内置但需要 schema 迁移 / 索引 / 连接池管理），增加复杂度
3. **一致性**：跟 history_store / log_store / job_queue 风格统一，将来要做"全 SQLite 化"可以一次性大改
4. **简单 backup**：JSON 文件直接 `cp` 就备份

**替代方案**：
- ❌ SQLite：over-engineering for 个人用例
- ❌ 单文件 per ticker（`~/.tradingagents/portfolio/{ticker}.json`）：CRUD 复杂度上升（拆 / 合 / merge 时文件操作复杂）
- ✅ 单文件多 ticker（`positions.json`）+ 单文件流水 + 单文件预警：3 个文件，简单清晰

### Decision 2: 持仓成本计算走"移动加权平均"，用户可手动覆盖

**问题**：移动加权 vs 摊薄 vs 真实成本 3 种算法，4 个 App 都不一致：
- 东方财富：移动加权 + 摊薄双显示
- 雪球：移动加权（用户一直要求切换）
- 腾讯自选股：移动加权
- 有知有行：移动加权 + 复权处理

**决策**：默认**移动加权平均**（行业惯例），但**提供"覆盖成本价"按钮**（与东方财富一致），理由：

1. 个人用户手动录入时，**第一次录入的成本价 = 真实成本**（含佣金），后续多次买入由代码自动算加权平均
2. 如果用户发现自己录入有错（比如漏了某笔交易），"覆盖"比"重新算"更可控
3. 复权处理放到 P2（`_tencent_quote` 当前返回不复权价，需要等后端补）

**复权策略 P2 候选**：调 `finance.pae.baidu.com` 或 `datacenter-web.eastmoney.com` 拿复权因子，在 portfolio_calc.py 里加 `def adjust_price_for_split(price, date, splits) -> float`。

### Decision 3: 价格预警按需触发，不做实时调度

**问题**：传统 App 的预警是"服务端实时监控 + 推送通知"。本项目 Streamlit 单进程，按需渲染，**不可能做实时调度**。

**决策**：预警触发 = **用户进入 Tab 1 时 + 手动点"检查预警"按钮**。理由：

1. 符合项目架构（Streamlit + 单进程）
2. 用户每天打开 1-3 次仓位面板足够日常使用
3. 不引入 systemd / cron / apscheduler 等额外基础设施
4. **不持久化通知**（`st.toast` 刷新即消）—— 与竞品的"通知中心"对比简化

**触发引擎**：
```python
def check_alerts(store, alerts, current_prices) -> list[AlertTrigger]:
    """遍历所有 enabled 规则，与 current_prices 对比，返回触发的列表"""
```

**P3 候选**：用 cron 守护进程做实时推送（脱离本 change 范围）。

### Decision 4: CSV 导入支持 4 种列名映射，前置解析 + 预览 + 确认

**问题**：不同券商 / App 的 CSV 列名千差万别（东方财富"成本价" / 同花顺"成本" / 雪球"cost_price"），导入不能简单映射。

**决策**：**4 种格式 mapping + 2 步交互（预览 → 确认）**。理由：

1. 用户**可能录错文件**（选错格式），预览给一次机会纠正
2. 导入冲突（ticker 已存在）需要用户决定（覆盖 / 跳过 / 合并）
3. 审计日志（`audit.log`）记录每次导入的 file_path / row_count / conflicts，方便追溯

**4 种格式定义**（在 `portfolio_import.py` 里维护）：
```python
CSV_FORMATS = {
    "eastmoney": {
        "code": "证券代码",
        "name": "证券名称",
        "cost": "成本价",
        "quantity": "持有数量",
        "date": "建仓日期",
    },
    "ths": {  # 同花顺
        "code": "股票代码",
        "name": "股票名称",
        "cost": "成本价",
        "quantity": "持仓数量",
        "date": "买入日期",
    },
    "xueqiu": {
        "code": "symbol",
        "name": "name",
        "cost": "cost_price",
        "quantity": "quantity",
        "date": "created_at",
    },
    "generic": {  # 通用
        "code": ["ticker", "code", "代码"],
        "name": ["name", "名称"],
        "cost": ["cost", "成本价", "cost_basis"],
        "quantity": ["quantity", "数量", "qty"],
        "date": ["date", "日期", "buy_date"],
    },
}
```

**P1.5 候选**：Excel 多 sheet 导入（用户截图里有提到）。

### Decision 5: 调仓推送按需检查，不做实时调度

**问题**：Bull/Bear 报告信号变化时，要不要立即通知用户？

**决策**：**按需检查**——用户进 Tab 1 时，调 `list_analyses(ticker=...)` 拿最近两次报告的 `signal` 字段，diff 出变化，用 `st.info()` 横幅展示。

**Why 按需**：
1. 跟预警决策 3 一致——单进程 Streamlit 不适合实时
2. 用户进 Tab 1 是**主动行为**，看到推送后能立即响应（进分析 / 调仓）
3. 实现简单：1 次数据库查询 + 1 次内存 diff

**数据流**：
```python
def get_rebalance_signals(ticker, lookback_days=7) -> list[RebalanceSignal]:
    """对比 ticker 最近 7 天的所有分析，找出 signal 从 X → Y 的变化"""
    entries = history_store.list_all(ticker=ticker, limit=20)
    # entries 按时间排序，pairwise diff signal
    ...
```

### Decision 6: 行业 / 板块归类复用现有 PAE + 同花顺

**问题**：要支持"行业分布饼图"和"板块分布"，需要 ticker → 行业 / 板块的映射。

**决策**：**复用现有 `tradingagents.dataflows.a_stock`**：
- 行业：调 `get_industry_comparison` 或 `_get_industry_for_ticker`（查现有）
- 板块：调 `get_concept_blocks(ticker)`（已存在，PAE 反查）

**缓存**：第一次调时缓存到 `st.session_state`（避免每次刷新都打接口）。缓存 key = ticker，TTL = 24h。

### Decision 7: 大类资产（股/债/海外/现金）走"手动标记"而非自动识别

**问题**：4 个 App 都不做"大类资产配置"（除了有知有行），国内 App 用户持仓基本是 A 股，没"债券" / "海外" 等分类需求。

**决策**：**手动标记 + 占位资产**：
- `Position.asset_class` 字段：`"stock"` (默认) / `"bond"` / `"overseas"` / `"cash"`
- 用户在录入或编辑持仓时手动选择
- "现金"是特殊类型（`quantity=0, cost_basis=0`），仅显示在汇总，不出现在股票列表

**Why 不自动识别**：
- 没有可靠的"持仓 ticker → 资产类别"映射数据源
- 个人用户规模小，手动标记比自动分类更可控

### Decision 8: 与 Bull/Bear 报告联动 = 工具 + 自动事件

**联动点**：
1. **LLM 工具**（P1）：`portfolio_tools.py` 加 `get_my_position(ticker)` 和 `get_my_portfolio_summary()`，挂到 7 个 Analyst 工具列表
2. **自动事件**（P0）：当某 ticker 报告 signal 变化（HOLD → BUY），Tab 1 顶部调仓推送横幅
3. **自动预警**（P0，默认关闭）：当某 ticker 报告 BUY/SELL 信号，自动创建止盈/止损预警

**实现**：
- `portfolio_tools.py`（P1）：参考 `signal_data_tools.py`（sector_rotation 的工具 wrapper）
- 调仓推送：参考 Decision 5
- 自动预警：`signal_extractor.py` 加 hook（参考 `tradingagents/agents/utils/` 现有结构）

### Decision 9: 账户管理 = Account dataclass + Position.account 引用 name（v0.5.0 增量）

**问题**：用户可能管理多个券商账户（华泰 A 股 / 招商港股 / 场外基金账户 / 现金账户）。持仓必须归属于某个账户，否则无法按账户聚合分析（"我华泰账户今天盈亏多少？"）。但如果 `Position.account` 引用 `account_id`（uuid），UI 下拉框就要展示 UUID —— 用户看不懂；存引用 `name` 又有重名风险。

**决策**：
- 新增 `Account` dataclass，存 `~/.tradingagents/portfolio/accounts.json`
- `Position.account` 字段值 = **`Account.name`**（不是 account_id）
- UI 下拉框直接显示中文名（如"华泰证券"、"现金账户"）
- `add_account()` 时**强制 name 唯一**（查重后抛 `ValueError("账户名已存在")`），避免下拉框出现重复项
- 删除账户前**检查引用**：`list_positions(account=name)` 不为空 → 阻断 + 提示"该账户下还有 N 只持仓，请先迁移或删除"

**为什么 name 而不是 account_id**：
1. UI 下拉框天然需要可读名（参考东方财富/雪球的账户切换器）
2. name 是用户视角的"业务标识"，account_id 是内部技术标识
3. 重名问题靠强制唯一解决（比强制 account_id 简单）
4. 用户改名（"华泰证券" → "华泰A"）时，所有 `Position.account` 自动跟过去（因为是引用 name 字符串）

**Position.asset_class vs Account.asset_class**：
- `Account.asset_class`：账户级默认（"我这个账户主要买股票 / 还是买海外 / 还是基金"）
- `Position.asset_class`：单只持仓级覆盖（"这个账户虽然默认股票，但我买了点港股 ETF"）
- `add_position()` 流程：如果调用方不传 `asset_class` → 从 `Account.asset_class` 继承

**默认账户**：第一次启动时 `ensure_default_account()` 自动创建一个 `name="default"` 的账户，保证下拉框永远不空。这是兜底逻辑，即使 `accounts.json` 文件不存在 / 为空 / 被用户删光。

### Decision 10: ensure_default_account() 启动时调，避免下拉框空

**问题**：用户第一次进入"我的仓位"模块时，`accounts.json` 不存在。Tab 1 录入持仓的"账户"下拉框 `st.selectbox(options=store.list_accounts())` 会渲染**空列表**，体验糟糕。

**决策**：在 `render_portfolio_panel()` 入口第一行调 `store.ensure_default_account()`，幂等（已经存在默认账户就 skip），保证：
1. 首次启动 → 自动建一个 `{name: "default", asset_class: "stock", is_default: True}`
2. 用户删除全部账户 → 下次进入 Tab 1 自动重建（兜底）
3. 已有账户 → noop，不影响

**为什么不用 `try/except` + fallback string**：
- 兜底用 string `"default"` 会让"账户管理"Tab 7 和"录入持仓"Tab 1 的下拉框不一致
- 走 `ensure_default_account()` 让所有 UI 都依赖单一数据源（store）

**set_default_account() 的副作用**：把所有账户 `is_default=False`，再把指定账户 `is_default=True`。保证**最多 1 个默认账户**（避免 set_default 之后有 2 个 default 的情况）。

**is_default 在 UI 的作用**：Tab 1 录入新持仓的账户下拉框**默认选中** `is_default=True` 的账户（无需 user 每次手动选）。Tab 7 账户管理表格的"默认"列显示 ⭐ 标记。

## Risks / Trade-offs

| 风险 | 等级 | 缓解 |
|---|---|---|
| 用户录入错误（手抖填错成本价） | 中 | "覆盖成本价"按钮 + 交易流水可追溯 + 导入审计日志 |
| 价格快照延迟（`_tencent_quote` 偶发慢响应） | 中 | `tencent_quote` 已有节流，本模块增加 timeout=10s；snapshot 不阻塞主面板 |
| 复权不准确（分红 / 拆股后成本价偏差） | 中 | P1 复权处理；MVP 阶段文档明确"成本价按用户录入计算，不自动复权" |
| CSV 格式变更（券商升级导出格式） | 低 | 4 种映射在代码里维护，用户可手动选"通用格式" |
| 账户重名 | 低 | `add_account()` 强制 name 唯一，抛 `ValueError`；UI 表单层面校验 |
| 删除有持仓的账户 | 中 | 删除前 `list_positions(account=name)` 检查，非空则 `st.warning` 阻断 + 提示用户迁移 |
| 删除全部账户后下拉框空 | 低 | `render_portfolio_panel()` 入口调 `ensure_default_account()`，幂等重建 |
| 改名后持仓引用断裂（用户把"华泰证券"改名为"华泰"） | 低 | `Position.account` 是字符串引用，自动跟过去；但**没有任何**位置自动同步——这是设计选择（用户主动改 = 全部跟过去） |
| XIRR 计算发散（现金流边界） | 中 | numpy + scipy optimize，给合理初始值（年化 8%）+ 容差 1e-6 + max 1000 iter |
| 预警误触（手动覆盖成本价后立即触发） | 低 | `last_triggered_at` 至少 5 分钟内不重复触发 |
| 调仓推送误报（同 ticker 1 天内多次跑分析） | 低 | 仅 diff "前后两次不同 report id 的 signal 字段"，run 多次同 signal 不算变化 |
| Bull/Bear 报告历史数据缺失（旧 ticker 没历史） | 低 | "首次出现 ticker 时创建首次持仓提示" |
| 7 个 Analyst 都挂 portfolio tools 增加 LLM 上下文 | 低 | 工具描述精简，LLM 智能调用（不会每个 ticker 都查） |

## Migration Plan

1. **部署顺序**：先 `portfolio_store.py` + `portfolio_calc.py` + 基础测试，再 `portfolio_panel.py` + nav 按钮接入，再 3 个 P0（alerts / import / rebalance），最后 P1（Bull/Bear 工具挂载）
2. **数据迁移**：无（新模块，`~/.tradingagents/portfolio/` 目录新建）
3. **配置迁移**：无（无需新增 streamlit config）
4. **回滚**：`git revert` 即可
5. **监控**：
   - `~/.tradingagents/portfolio/audit.log` 看导入操作
   - `~/.tradingagents/logs/` 看 streamlit session 日志里的 panel 渲染错误

## Open Questions

- **Q1**:Brinson 模型实现复杂度（拆"选股贡献"vs"行业贡献"vs"交互贡献"），MVP 是否只做"选股贡献 + 行业贡献"两部分？
  - 倾向 **MVP 只做这两部分**，交互贡献（residual）放 P2
- **Q2**:XIRR vs IRR 的选择？
  - **XIRR**（任意日期现金流）—— 个人用户现金流入出不规则，XIRR 更准确；IRR 假设等间隔流入不适合
- **Q3**:预警类型"移动止损"（trailing stop）的实现：需要每天拿历史价格算最高点
  - **v1 暂不支持**——只支持静态阈值（止盈/止损）；移动止损需要保存"自创建以来的最高价"，增加复杂度
  - 数据模型预留字段（`AlertRule` 注释标注），P3 实现
- **Q4**:CSV 导出格式选择？
  - **CSV 优先**（轻量、Excel 兼容 UTF-8 BOM）；Excel 多 sheet 放 P1.5
- **Q5**:Brinson 归因的行业基准用什么？
  - **沪深 300**（业界惯例）；用户可配置（`"benchmark": "000300"` 在 settings）
  - 复权价格用 `np-anotice-stock` 或 `datacenter-web` 拉历史，复权因子在 `_em_get` 缓存
- **Q6**:Tab 1 调仓推送横幅的"7 天"窗口是配置项还是硬编码？
  - **硬编码常量 `REBALANCE_LOOKBACK_DAYS = 7`**；P3 加到 settings panel 可配置

## Architecture Diagram

```
                  ┌─────────────────────────────────────┐
                  │       web/components/                │
                  │       portfolio_panel.py             │
                  │                                       │
                  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐      │
                  │  │Tab1 │ │Tab2 │ │Tab3 │ │Tab4-6│     │
                  │  │总览 │ │流水 │ │配置 │ │预警/IO/收益│
                  │  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘      │
                  └─────┼──────┼──────┼──────┼────────────┘
                        │      │      │      │
       ┌────────────────┘      │      │      └──────────────┐
       │                       │      │                      │
       ▼                       ▼      ▼                      ▼
┌──────────────────┐  ┌─────────────────┐  ┌────────────────────┐
│ PortfolioStore   │  │ PortfolioCalc   │  │ AlertEngine         │
│ (JSON + lock)    │  │ (XIRR/Sharpe)   │  │ (rule eval)         │
│                  │  │                 │  │                     │
│ - positions.json │  │ - compute_      │  │ - load_alerts       │
│ - transactions.  │  │   position_     │  │ - check vs current  │
│   json           │  │   metrics       │  │ - return triggered  │
│ - alerts.json    │  │ - compute_      │  │                     │
│ - audit.log      │  │   portfolio_    │  │                     │
│                  │  │   summary       │  │                     │
└────────┬─────────┘  │ - compute_xirr  │  └──────────┬──────────┘
         │            │ - compute_      │             │
         │            │   max_drawdown  │             │
         │            │ - compute_      │             │
         │            │   sharpe        │             │
         │            │ - compute_      │             │
         │            │   brinson       │             │
         │            └────────┬────────┘             │
         │                     │                      │
         └─────────────────────┼──────────────────────┘
                               │
                               ▼
            ┌──────────────────────────────────┐
            │  tradingagents/dataflows/        │
            │  - _tencent_quote (price)         │
            │  - get_concept_blocks (sector)   │
            │  - interface.list_analyses        │
            │    (Bull/Bear report history)    │
            └──────────────────────────────────┘
```

## File-by-File Spec

### `backend/core/portfolio_store.py` (~400 行，v0.5.0 含账户)

```python
@dataclass
class Position: ...
@dataclass
class Transaction: ...
@dataclass
class AlertRule: ...
@dataclass
class Account:        # v0.5.0 新增
    account_id: str
    name: str            # 唯一，UI 显示名（中文）
    broker: str = ""
    account_number_tail: str = ""
    asset_class: str = "stock"   # 账户级默认
    notes: str = ""
    is_default: bool = False     # 全局最多 1 个 True
    created_at: float = field(default_factory=time.time)

class PortfolioStore:
    _instance: PortfolioStore | None = None
    _lock: threading.Lock

    # --- Position CRUD ---
    add_position(ticker, name, cost_basis, quantity, first_buy_date, account="default", asset_class=None) -> Position
        # account: 引用 Account.name，不存在则 ValueError
        # asset_class=None → 从 Account.asset_class 继承
    update_position(position_id, **fields) -> Position
    delete_position(position_id) -> None
    get_position(position_id) -> Position | None
    list_positions(account=None, asset_class=None) -> list[Position]

    # --- Transaction CRUD ---
    add_transaction(position_id, date, action, price, quantity, fees=0, notes="") -> Transaction
    list_transactions(ticker=None, since=None) -> list[Transaction]

    # --- AlertRule CRUD ---
    add_alert(ticker, rule_type, threshold, note="") -> AlertRule
    update_alert(rule_id, **fields) -> AlertRule
    delete_alert(rule_id) -> None
    list_alerts(ticker=None, enabled_only=False) -> list[AlertRule]
    record_trigger(rule_id, price) -> None

    # --- Account CRUD (v0.5.0 新增) ---
    add_account(name, broker="", account_number_tail="", asset_class="stock", notes="", is_default=False) -> Account
        # name 唯一性校验：list_accounts() 中已有同名 → ValueError
        # is_default=True → 自动把其它账户的 is_default=False
    update_account(account_id, **fields) -> Account
        # name 改了不影响持仓（因为是字符串引用）
    delete_account(account_id) -> None
        # 检查引用：list_positions(account=name) 非空 → ValueError
    get_account(account_id) -> Account | None
    get_account_by_name(name) -> Account | None
    list_accounts() -> list[Account]
    set_default_account(account_id) -> None
        # 所有账户 is_default=False → 该账户 is_default=True
        # 至少保留 1 个 default：如果 set 一个非 default 为 default，旧 default 自动让位
    ensure_default_account() -> Account
        # 幂等：如果 accounts.json 不存在/为空/无 default → 创建 {name:"default", asset_class:"stock", is_default:True}
        # 已存在 default → noop

    # --- Internal ---
    _path(filename) -> Path
    _read(filename) -> list
    _write(filename, data) -> None
    _audit(msg: str) -> None  # 写 audit.log
```

**存储路径**：
- `~/.tradingagents/portfolio/positions.json`
- `~/.tradingagents/portfolio/transactions.json`
- `~/.tradingagents/portfolio/alerts.json`
- `~/.tradingagents/portfolio/accounts.json`（v0.5.0 新增）
- `~/.tradingagents/portfolio/audit.log`（追加）

### `backend/core/portfolio_calc.py` (~350 行)

```python
@dataclass
class PositionMetrics:
    current_value: float      # 现价 × 持仓
    cost_value: float         # 成本价 × 持仓
    pnl_abs: float            # 浮动盈亏金额
    pnl_pct: float            # 浮动盈亏比例
    today_pnl: float          # 当日盈亏（基于现价 - 昨收）
    today_pnl_pct: float
    holding_days: int         # 持仓天数
    cost_basis: float
    current_price: float

@dataclass
class PortfolioSummary:
    total_value: float
    total_cost: float
    total_pnl_abs: float
    total_pnl_pct: float
    today_pnl: float
    positions_count: int
    by_industry: dict[str, float]
    by_sector: dict[str, float]
    by_asset_class: dict[str, float]
    concentration_top5_pct: float

def compute_position_metrics(position, current_price, transactions) -> PositionMetrics: ...
def compute_portfolio_summary(positions, current_prices) -> PortfolioSummary: ...
def compute_xirr(transactions, current_value, as_of) -> float: ...
def compute_max_drawdown(equity_curve: list[tuple[date, float]]) -> float: ...
def compute_sharpe(daily_returns: list[float], risk_free_rate: float = 0.025) -> float: ...
def compute_brinson_attribution(positions, benchmark_returns) -> dict: ...
```

**算法**：
- XIRR: `scipy.optimize.brentq` 求 IRR=0 的根
- 最大回撤: 滚动 max + 当前值的最大跌幅
- Sharpe: `(mean(daily_returns) - rf_daily) / std(daily_returns) * sqrt(252)`
- Brinson: 拆"组合收益 = Σ(权重 × 收益) vs 基准组合收益"，差值归因到选股 / 行业 / 交互

### `backend/core/portfolio_alerts.py` (~150 行)

```python
@dataclass
class AlertTrigger:
    rule_id: str
    ticker: str
    rule_type: str
    threshold: float
    current_value: float
    triggered_at: float
    message: str  # "价格突破 7.00，当前 7.05"

def evaluate_alerts(store, current_prices: dict[str, float]) -> list[AlertTrigger]:
    """遍历 enabled 规则，对比 current_prices，返回触发的列表
    触发后调 store.record_trigger(rule_id, current_value) 记录
    防重复：last_triggered_at 距今 < 300s 跳过
    """
```

### `backend/core/portfolio_import.py` (~250 行)

```python
CSV_FORMATS: dict[str, dict[str, str | list[str]]]

def detect_format(csv_path: Path) -> str | None:
    """读前 5 行，匹配置信度最高的格式"""

def parse_csv(csv_path: Path, format: str) -> list[dict]:
    """解析为标准格式 [{ticker, name, cost, quantity, date}, ...]"""

def preview_import(parsed: list[dict], existing_positions: list[Position]) -> dict:
    """返回 {new: [...], conflicts: [{parsed, existing, resolution}], invalid: [...]}"""

def apply_import(preview: dict, resolution_strategy: str) -> list[Position]:
    """resolution_strategy: 'overwrite' | 'skip' | 'merge'
    写 store._audit() 记录导入操作
    """

def export_csv(positions: list[Position], transactions: list[Transaction]) -> Path:
    """生成 UTF-8 BOM CSV 文件，返回路径"""
```

### `web/components/portfolio_panel.py` (~550 行)

```python
def render_portfolio_panel() -> None:
    """Streamlit 入口
    6 tab: 总览 / 流水 / 配置 / 预警 / 导入导出 / 收益风险
    顶部调仓推送横幅（如果有信号变化）
    """

def _render_overview_tab(positions, summary): ...
def _render_transactions_tab(transactions, positions): ...
def _render_allocation_tab(positions, summary): ...
def _render_alerts_tab(alerts, positions): ...
def _render_io_tab(store): ...
def _render_metrics_tab(positions, summary, metrics): ...

def _show_rebalance_banner(positions): ...
def _add_position_dialog(): ...  # st.dialog
def _edit_position_dialog(position_id): ...  # st.dialog
def _add_transaction_dialog(position_id): ...  # st.dialog
def _add_alert_dialog(): ...  # st.dialog
```

### `tradingagents/agents/utils/portfolio_tools.py` (~100 行, P1)

```python
def get_my_position(ticker: str) -> dict:
    """LLM 工具：返回当前持仓摘要"""

def get_my_portfolio_summary() -> dict:
    """LLM 工具：返回组合汇总"""

def get_my_rebalance_signals(lookback_days: int = 7) -> list[dict]:
    """LLM 工具：返回近期信号变化列表"""

def register_tools() -> None:
    """注册到 7 个 Analyst 的工具列表"""
```

### 测试

- `tests/test_portfolio_store.py` (~150 行)：CRUD + 线程安全 + audit log
- `tests/test_portfolio_calc.py` (~180 行)：XIRR/Sharpe/MaxDrawdown/Brinson 边界 + 已知样本
- `tests/test_portfolio_alerts.py` (~120 行)：trigger logic + 防重复
- `tests/test_portfolio_import.py` (~150 行)：4 种格式 sample data + 冲突处理
- `tests/test_portfolio_panel.py` (~150 行)：mock streamlit snapshot
- 总计 25+ 测试，零回归