# Portfolio Module (个人仓位跟踪)

## Why

现有框架定位是"投研引擎"——7 个 Analyst 角色（市场/情绪/新闻/基本面/政策/游资/解禁）通过 Bull/Bear 辩论 + 三方风险辩论生成投资报告。但**研报与"我的持仓"完全脱节**：

- 用户跑完一份分析，结论是 BUY，但**仓位模块不知道他持有多少、成本多少、是否需要补仓/减仓**。
- 没有"我持有的股票 vs 实时行情 vs 我之前的研究"对比。
- 没有"今天我盈亏多少"、"组合风险敞口多大"等个人化指标。

调研了 4 个国内主流 App（东方财富 / 雪球 / 腾讯自选股 / 有知有行）后，**Full scope** 包含：

| 维度 | 东方财富 | 雪球 | 腾讯自选股 | 有知有行 |
|---|---|---|---|---|
| 手动录入持仓 | ✓ | ✓ | ✓ | ✓（主线） |
| 交易事件类型 | 10+ (买/卖/分红/送股/配股/打新/期权/融资融券) | 8 (买/卖/补仓/卖空/股息/红股/合股/拆股) | 4 (买/卖/分红/扣税) | 8+ (买/卖/分红/再投/定投/可转债) |
| 移动平均成本 | ✓ 默认 | ✓ 默认 | ✓ | ✓ |
| 真实/摊薄成本 | ✓ 切换 | ✗ (用户一直要求) | ✗ | ✗ |
| 盈亏统计（当日/累计） | ✓ | ✓ | ✓ | ✓ |
| IRR / XIRR / TWR | ✗ | ✗ | ✗ | ✓ **核心** |
| 行业/板块分布 | ✓ | ✓ (饼图特色) | 基础 | 基础 |
| 大类资产配置 (股/债/海外) | ✗ | ✗ | ✗ | ✓ **核心** |
| 组合 Beta / 夏普 / 最大回撤 | 仅 Choice 付费版 | ✗ | ✗ | ✓ |
| Brinson 业绩归因 | ✗ | ✗ | ✗ | ✓ |
| 调仓推送 / 大 V 跟随 | ✗ | ✓ **核心特色** | ✗ | ✗ |
| 持仓脱敏分享 | ✓ | ✓ | ✓ (微信) | ✗ |

本 change 走 **Full scope**：覆盖手动持仓录入 + 完整盈亏/统计 + 资产配置 + 风险指标（IRR/夏普）+ 与已有 Bull/Bear 报告联动。**不做**：券商实盘同步（零 cookie 原则）、社交化大 V 跟随（不是投研引擎定位）、融资融券/期权（复杂度超出 MVP）。

数据存储复用现有 `~/.tradingagents/` 数据系统，文件风格对齐 `backend/core/history_store.py`。

## What Changes

### 数据层（`backend/core/portfolio_store.py`，新增）

仿 `history_store.py` 风格：JSON 文件 + dataclass + 单例 + 线程锁。

- **存储路径**：
  - `~/.tradingagents/portfolio/positions.json`（持仓）
  - `~/.tradingagents/portfolio/transactions.json`（交易流水）
  - `~/.tradingagents/portfolio/alerts.json`（预警规则）
  - `~/.tradingagents/portfolio/accounts.json`（**账户管理，v0.5.0 增量**）
  - `~/.tradingagents/portfolio/audit.log`（追加日志）
- **数据模型**：
  ```python
  @dataclass
  class Position:
      position_id: str            # uuid4 前 12 位
      ticker: str                 # 6 位代码，关联 tradingagents.a_stock._normalize_ticker
      name: str                   # 中文名（冗余存，UI 显示用）
      cost_basis: float           # 加权平均成本
      quantity: int               # 当前持仓数量
      first_buy_date: str        # 首次买入 ISO date
      last_trade_date: str
      account: str                # 引用 Account.name（如"华泰证券"、"现金账户"）
      asset_class: str = "stock"  # 单只持仓级别可覆盖 Account 默认值
      notes: str = ""

  @dataclass
  class Transaction:
      tx_id: str
      position_id: str
      ticker: str
      date: str                   # ISO date
      action: str                 # buy | sell | dividend | split | merge
      price: float
      quantity: int
      fees: float = 0.0           # 佣金 + 印花税
      notes: str = ""

  @dataclass
  class Account:
      """账户管理 — 存 ~/.tradingagents/portfolio/accounts.json

      设计意图：用户可能管理多个券商账户（A 股 / 港股 / 场外基金 / 现金），每只持仓必须属于一个账户。
      Position.account 字段引用 Account.name（不是 account_id），方便用户在 UI 下拉框里直接选中文账户名。
      """
      account_id: str             # uuid4 前 12 位（内部使用）
      name: str                   # 显示名（用户取的中文名，如"华泰证券"、"招商证券"、"现金账户"），Position.account 引用此字段
      broker: str = ""            # 券商名（华泰 / 招商 / 国泰君安 等）
      account_number_tail: str = ""  # 账号后 4 位（脱敏，便于用户区分同名账户）
      asset_class: str = "stock"  # 默认 "stock"，可选 "bond" / "overseas" / "cash" / "fund"——这个是账户级别的默认 asset_class，Position 仍可单独覆盖
      notes: str = ""
      is_default: bool = False    # 是否为默认账户（新增持仓时预选）
      created_at: float = field(default_factory=time.time)

  @dataclass
  class AlertRule:
      """价格预警规则 — 存在 ~/.tradingagents/portfolio/alerts.json"""
      rule_id: str                # uuid4 前 12 位
      ticker: str
      rule_type: str              # price_above | price_below | pct_change | pnl_pct | take_profit | stop_loss | trailing_stop
      threshold: float            # 阈值（按 rule_type 不同含义不同：价格 / 百分比 / 比例）
      enabled: bool = True
      note: str = ""
      created_at: float = field(default_factory=time.time)
      last_triggered_at: float | None = None
      last_triggered_price: float | None = None
      trigger_count: int = 0
  ```

- **API**：
  ```python
  class PortfolioStore:
      add_position(ticker, name, cost_basis, quantity, first_buy_date, account="default", asset_class=None) -> Position
      update_position(position_id, **fields) -> Position
      delete_position(position_id) -> None
      get_position(position_id) -> Position | None
      list_positions(account=None, asset_class=None) -> list[Position]

      add_transaction(...) -> Transaction
      list_transactions(ticker=None, since=None) -> list[Transaction]

      # 账户管理（v0.5.0 增量）
      add_account(name, broker="", account_number_tail="", asset_class="stock", notes="", is_default=False) -> Account
      update_account(account_id, **fields) -> Account
      delete_account(account_id) -> None  # 仅当无持仓引用时允许
      get_account(account_id) -> Account | None
      get_account_by_name(name) -> Account | None  # Position.account → Account.name 查找
      list_accounts() -> list[Account]
      set_default_account(account_id) -> None  # 把所有 is_default=False 然后该账户设 True
      # 默认账户：首次启动时自动创建一个默认账户 {"default", broker="", asset_class="stock", is_default=True}
      ensure_default_account() -> Account  # 启动时调用

      add_alert(ticker, rule_type, threshold, note="") -> AlertRule
      update_alert(rule_id, **fields) -> AlertRule
      delete_alert(rule_id) -> None
      list_alerts(ticker=None, enabled_only=False) -> list[AlertRule]
      record_trigger(rule_id, price) -> None

      get_snapshot(ticker, as_of=None) -> dict    # 触发数据层实时价查询
  ```

- **Account + Position 引用约束**：
  - `Position.account` 字段值必须是 `Account.name` 之一（初次启动时 `ensure_default_account()` 会自动建一个名为 "default" 的账户，保证不空）
  - 删除账户前检查无持仓引用，提示用户"该账户下还有 N 只持仓，请先迁移或删除"
- **`add_position()` 自动填充 asset_class**：如果调用方不传 `asset_class`，从 `Account.asset_class` 继承（账户级别的默认值）

### 实时计算层（`backend/core/portfolio_calc.py`，新增）

```python
def compute_position_metrics(position, current_price, transactions) -> dict:
    """返回 {current_value, cost_value, pnl_abs, pnl_pct, today_pnl, holding_days, ...}"""

def compute_portfolio_summary(positions, current_prices) -> dict:
    """返回 {total_value, total_cost, total_pnl, today_pnl, by_sector, by_industry, by_asset_class, by_account, ...}"""
    # by_account: dict[account_name -> value]  # v0.5.0 增量

def compute_xirr(transactions, current_value, as_of) -> float:
    """XIRR: 现金流时序 + 当前净值，用 scipy.optimize 或 numpy 实现"""

def compute_max_drawdown(equity_curve) -> float:
    """最大回撤"""

def compute_sharpe(daily_returns, risk_free_rate=0.025) -> float:
    """年化 Sharpe"""
```

价格获取复用现有 `tradingagents.dataflows.a_stock._tencent_quote()`（已在用，已有节流）。

### Web UI（`web/components/portfolio_panel.py`，新增）

参照现有 `sector_panel.py` / `history_panel.py` 风格：

**主面板分 7 个 Tab**（用 st.tabs）——**v0.5.0 增量加了"账户" tab**：

  - **Tab 1 — 持仓总览**：表格 + 关键指标卡片
    - 顶部 4 个 metric 卡片：总市值 / 总成本 / 总盈亏 / 今日盈亏（红绿按 A 股习惯）
    - 表格列：代码 / 名称 / **账户**（新增列）/ 持仓数量 / 成本价 / 现价 / 浮动盈亏 / 盈亏比例 / 持仓天数 / 操作
    - 表格底部"录入新持仓"按钮 → 弹 `st.dialog` 表单
      - **账户字段**用 `st.selectbox` 下拉框，选项来自 `store.list_accounts()`（按 name 排序，默认账户排第一）
      - **如果 list_accounts() 为空**（理论不会，因为 ensure_default_account 启动时建好；但兜底），自动 fallback 到 "default" 文本输入
    - 编辑持仓 / 录入交易用 `st.dialog` 模态
  - **Tab 2 — 交易流水**：表格 + 时间线视图
    - 表格列：日期 / 代码 / **账户** / 动作 / 价格 / 数量 / 手续费 / 备注
    - 支持按 ticker / 账户 / 时间筛选
    - "录入新交易" 按钮
  - **Tab 3 — 资产配置**：图表
    - 行业分布饼图（用 `st.plotly_chart` 或 altair，复用你项目已有风格）
    - 板块分布（按同花顺概念板块）
    - 大类资产分布
    - **账户分布**（v0.5.0 增量）：按账户聚合持仓金额，饼图
    - 持仓集中度（前 5 大持仓占比 / 单股最大占比）
  - **Tab 4 — 价格预警**
    - 同前（v0.5.0 不变）
  - **Tab 5 — 导入导出**
    - 同前（v0.5.0 不变）
  - **Tab 6 — 收益与风险**
    - 同前（v0.5.0 不变）
  - **Tab 7 — 账户管理**（v0.5.0 新增）
    - 表格：账户名 / 券商 / 账号后 4 位 / 大类资产 / 默认 / 持仓数 / 创建时间 / 操作
    - "新增账户" 按钮 → `st.dialog` 表单（账户名 / 券商 / 账号后 4 位 / 大类资产下拉 / 备注 / 是否默认）
    - 编辑 / 删除 / 设为默认操作
    - 删除前检查持仓引用（如有 → `st.warning` 阻断）

### 入口集成（`web/app.py`，修改）

  - 在 `_NAV_ITEMS` 列表插入新按钮（位置 A：**第 4 个，在"📋 历史"前面**）
    ```python
    _NAV_ITEMS: list[tuple[str, str, str]] = [
        ("📝", "分析", "analyze"),
        ("📊", "批量分析", "batch"),
        ("📈", "板块轮动", "sector"),
        ("💼", "我的仓位", "portfolio"),     # 新增
        ("📋", "历史", "history"),
        ("📋", "日志", "logs"),
        ("📈", "走势图", "chart"),
        ("⚙️", "设置", "settings"),
    ]
    ```
  - 在主路由 `view == "portfolio"` elif 分支调 `render_portfolio_panel()`
  - **`render_portfolio_panel()` 入口先调 `store.ensure_default_account()`** —— 首次启动自动建默认账户，无需用户手动操作

### 与已有 Bull/Bear 报告联动（`tradingagents/agents/utils/portfolio_tools.py`，新增，可选 P1）

  - 新增工具 `get_my_position(ticker)` 和 `get_my_portfolio_summary()`，挂载到所有 7 个 Analyst 的工具列表（参考 `sector_rotation` 怎么挂）
  - 这样 LLM 在生成报告时会知道"我已经持有 600595 共 5000 股，成本 5.80"，结论 BUY/HOLD/SELL 会更精准
  - **P1 优先级**——P0 先把模块本身跑通

### 测试（`tests/`）

  - `tests/test_portfolio_store.py`：CRUD + 线程安全 + Account 引用约束
  - `tests/test_portfolio_calc.py`：XIRR/Sharpe/MaxDrawdown 的边界 + 已知样本回归
  - `tests/test_portfolio_alerts.py`：trigger logic + 防重复
  - `tests/test_portfolio_import.py`：4 种格式 sample data + 冲突处理
  - `tests/test_portfolio_panel.py`：UI 渲染快照 + 关键交互（mock streamlit）+ **账户下拉框**测试
  - 目标 30+ 测试，零回归

### Non-goals (明确不做的)

- ❌ **券商实盘同步**：本项目"零 cookie"原则（参照 `sector_rotation` change 的 non-goals），接券商 API 需要 cookie / 二次验证
- ❌ **融资融券 / 期权 / 港美股 / 可转债**：超出 MVP 复杂度；可转债、ETF、个股三层交易事件类型已经支持
- ❌ **社交化 / 大 V 跟随 / 实盘组合公开**：不是投研引擎定位
- ❌ **OCR 截图识别**：复杂且无可靠开源库

## Capabilities

### New Capabilities

- `portfolio-store`: JSON 文件持久化的持仓 + 交易流水 + 账户 + 预警规则（CRUD + 查询 + 线程安全）
- `portfolio-calc`: 盈亏指标计算（XIRR、Sharpe、最大回撤、按账户聚合、Brinson）
- `portfolio-panel`: Streamlit 面板（7 tab：总览 / 流水 / 配置 / 预警 / 导入导出 / 收益风险 / 账户管理）
- `portfolio-alerts`: 价格预警规则（CRUD + 触发引擎 + 触发历史）
- `portfolio-import-export`: 多格式 CSV 导入（东财/同花顺/雪球/通用）+ UTF-8 BOM CSV 导出 + 审计日志
- `portfolio-rebalance-signal`: 调仓推送（diff Bull/Bear 信号变化，Tab 1 顶部横幅展示）
- `portfolio-account-management`: 账户 CRUD（新增/编辑/删除/设默认）+ Position.account 引用约束

### Modified Capabilities

<!-- 同 sector_rotation：现有 spec 不存在 machine-readable 形式，本 change 不修改 spec 级契约 -->
- (无)

## Impact

### 新增文件

- `backend/core/portfolio_store.py`：~400 行（含 Position/Transaction/AlertRule/Account 4 个 dataclass + PortfolioStore 单例 + 线程安全 + Account CRUD + 引用约束检查）
- `backend/core/portfolio_calc.py`：~380 行（纯计算 + 数据类，含按账户聚合）
- `backend/core/portfolio_alerts.py`：~150 行（预警规则 CRUD + 触发引擎 + 触发历史）
- `backend/core/portfolio_import.py`：~250 行（多格式 CSV 解析 + 4 种列名映射 + 审计日志）
- `web/components/portfolio_panel.py`：~620 行（7 tab + 4 个 st.dialog 表单 + 调仓推送横幅）
- `tradingagents/agents/utils/portfolio_tools.py`：~100 行（P1 可选）
- `tests/test_portfolio_store.py`：~180 行（含 Account 引用约束测试）
- `tests/test_portfolio_calc.py`：~180 行
- `tests/test_portfolio_alerts.py`：~120 行
- `tests/test_portfolio_import.py`：~150 行
- `tests/test_portfolio_panel.py`：~180 行（含账户下拉框测试）
- `openspec/changes/portfolio-module/design.md`：技术细节
- `openspec/changes/portfolio-module/tasks.md`：任务分解
- `docs/research/portfolio-module-competitor-analysis.md`：4 个竞品调研汇总

### 修改文件

- `web/app.py`：`_NAV_ITEMS` 插入新按钮（1 行） + 主路由加 elif（5 行）
- `web/nav.py`：可能需要在 `plan_nav_click` 加 portfolio 状态清理
- `web/styles/elements.css`：可能加 .bb-portfolio-* 类（红色涨绿色跌等 token 复用现有）
- `CLAUDE.md`：架构清单新增"个人仓位模块"
- `CHANGELOG.md`：版本号 v0.5.0
- `README.md`：功能列表更新

### 依赖

- **零新增第三方依赖** —— 全部使用现有 `pandas` / `numpy` / `streamlit`
- XIRR 用 `numpy` + 自实现（不引入 `pyirr`）
- 价格查询复用 `tradingagents.dataflows.a_stock._tencent_quote`

### 风险

- **账户删除时的引用约束**：用户已有持仓引用某账户时，删除要阻断并提示
- **首次启动账户为空**：`ensure_default_account()` 在 `render_portfolio_panel()` 入口调，保证一定有默认账户，下拉框不会空
- **同名账户**：禁止两个账户 name 相同（`add_account` 抛 `ValueError`）
- **持仓价格快照频率**：每次刷新面板调 `_tencent_quote`，可能触发东财节流（已有 `_em_get` 节流）；本模块走 `_tencent_quote` 而非 `_em_get`（腾讯节流更宽松）
- **成本价精度**：用户手动录入 vs 多次买入摊薄，建议采用移动加权平均（与东方财富 / 雪球 / 腾讯一致），但提供"用户覆盖成本价"按钮（与东方财富一致）
- **复权处理**：当前 `_tencent_quote` 返回不复权价；如果用户买入后发生过除权除息，成本价计算可能不准——P2 阶段加复权支持

## 参考调研

- `docs/research/portfolio-module-competitor-analysis.md`（由 4 个 subagent 调研汇总）
- 原始调研文件：
  - `/tmp/research_eastmoney.md`（14979 bytes, 125 行, 52 引用源）
  - `/tmp/research_xueqiu.md`（8763 bytes, 107 行, 38 引用源）
  - `/tmp/research_tencent_quote.md`（9249 bytes, 91 行, 42 引用源）
  - `/tmp/research_youzhiyouxing.md`（29402 bytes, 218 行, 80 引用源）
- 模板：`openspec/changes/sector-rotation/proposal.md`
- 数据存储参考：`backend/core/history_store.py`（同名 dataclass + 单例 + 线程锁风格）
- UI 组件参考：`web/components/sector_panel.py`（4 tab 结构 + st.tabs）

## v0.5.0 增量日志

- v0.5.0 在 v0.5.0 基础规格上**新增账户管理模块**：
  - 新增 `Account` dataclass（account_id / name / broker / account_number_tail / asset_class / is_default / created_at）
  - `Position` dataclass 字段保持原样（`account: str` 引用 Account.name）
  - 新增 8 个 PortfolioStore API 方法（add/update/delete/get/get_by_name/list/set_default/ensure_default）
  - 新增 1 个 Capability：`portfolio-account-management`
  - 新增 1 个 Tab（Tab 7 — 账户管理）
  - 新增 1 列到 Tab 1（账户列）+ Tab 2（账户列）+ Tab 3（账户分布饼图）
  - `add_position()` 自动从 Account 继承 asset_class
  - 首次启动时自动创建默认账户（`ensure_default_account()`）