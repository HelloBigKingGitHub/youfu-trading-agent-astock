# Portfolio Module — Implementation Tasks

> 工作目录：/home/youfu/projects/youfu-trading-agent-astock
> 依赖：现有 `backend/core/history_store.py` 风格 + `tradingagents.dataflows.a_stock._tencent_quote`
> 参考：openspec/changes/sector-rotation/tasks.md（同样 spec-first 流程）

---

## Phase 1 — 数据层（无 UI，纯函数 + 文件 IO）

### 1.1 `backend/core/portfolio_store.py` 骨架

- [ ] 1.1.1 创建 `Position` dataclass
  - 字段：`position_id`, `ticker`, `name`, `cost_basis`, `quantity`, `first_buy_date`, `last_trade_date`, `account`, `asset_class`, `notes`
  - `to_dict()` / `from_dict()` 方法
- [ ] 1.1.2 创建 `Transaction` dataclass
  - 字段：`tx_id`, `position_id`, `ticker`, `date`, `action`, `price`, `quantity`, `fees`, `notes`
  - `action` 取值：`buy` | `sell` | `dividend` | `split` | `merge` | `rights`
- [ ] 1.1.3 创建 `AlertRule` dataclass
  - 字段：`rule_id`, `ticker`, `rule_type`, `threshold`, `enabled`, `note`, `created_at`, `last_triggered_at`, `last_triggered_price`, `trigger_count`
  - `rule_type` 取值：`price_above` | `price_below` | `pct_change` | `pnl_pct` | `take_profit` | `stop_loss` | `trailing_stop`
- [ ] 1.1.4 创建 `Account` dataclass（v0.5.0 增量）
  - 字段：`account_id`, `name`, `broker`, `account_number_tail`, `asset_class`, `notes`, `is_default`, `created_at`
  - `to_dict()` / `from_dict()` 方法
  - `asset_class` 默认 `"stock"`，可选 `"bond"` | `"overseas"` | `"cash"` | `"fund"`
- [ ] 1.1.5 创建 `PortfolioStore` 单例类
  - `_instance` + `_lock` 模式（参考 history_store.py line 88-100）
  - 路径常量：`PORTFOLIO_DIR = ~/.tradingagents/portfolio/`
- [ ] 1.1.6 实现 Position CRUD 方法
  - `add_position()` 支持 `account` 参数（默认 "default"）+ `asset_class=None` 自动从 Account 继承
  - `update_position()`, `delete_position()`, `get_position()`, `list_positions(account=None, asset_class=None)`
  - 校验：`add_position` 时如果 `account` 不在 `list_accounts()` → 提示用户先建账户（或 fallback 到默认账户 + warning）
- [ ] 1.1.7 实现 Transaction CRUD 方法
  - `add_transaction()`, `list_transactions(ticker=None, since=None)`
- [ ] 1.1.8 实现 AlertRule CRUD 方法
  - `add_alert()`, `update_alert()`, `delete_alert()`, `list_alerts(ticker=None, enabled_only=False)`, `record_trigger(rule_id, price)`
- [ ] 1.1.9 实现 Account CRUD 方法（v0.5.0 增量）
  - `add_account(name, ...)`：**name 唯一性校验**（已存在 → `ValueError("账户名已存在")`）；is_default=True 自动把其它账户置为 False
  - `update_account(account_id, **fields)`：name 改了不影响持仓引用（因为是字符串引用）
  - `delete_account(account_id)`：检查 `list_positions(account=name)`，非空 → `ValueError("该账户下还有 N 只持仓")`
  - `get_account(account_id)` / `get_account_by_name(name)` / `list_accounts()` / `set_default_account(account_id)`
  - `ensure_default_account()`：**幂等启动逻辑**（accounts.json 不存在 / 为空 / 无 default → 建一个 `{name:"default", asset_class:"stock", is_default:True}`；已存在 default → noop）
- [ ] 1.1.10 实现内部 IO 方法
  - `_path(filename)` / `_read(filename)` / `_write(filename, data)` / `_audit(msg)`
  - 5 个文件：`positions.json`, `transactions.json`, `alerts.json`, `accounts.json`（v0.5.0 新增）, `audit.log`
- [ ] 1.1.11 添加 `_normalize_ticker()` 调用
  - 复用 `tradingagents.dataflows.a_stock._normalize_ticker()`（line 44 附近）

### 1.2 `backend/core/portfolio_calc.py` 计算层

- [ ] 1.2.1 创建 `PositionMetrics` dataclass
  - 字段：`current_value`, `cost_value`, `pnl_abs`, `pnl_pct`, `today_pnl`, `today_pnl_pct`, `holding_days`, `cost_basis`, `current_price`, `prev_close`
- [ ] 1.2.2 创建 `PortfolioSummary` dataclass
  - 字段：`total_value`, `total_cost`, `total_pnl_abs`, `total_pnl_pct`, `today_pnl`, `positions_count`, `by_industry`, `by_sector`, `by_asset_class`, `concentration_top5_pct`
- [ ] 1.2.3 实现 `compute_position_metrics(position, current_price, transactions) -> PositionMetrics`
  - 移动加权平均成本计算
  - 持仓天数 = (today - first_buy_date).days
- [ ] 1.2.4 实现 `compute_portfolio_summary(positions, current_prices) -> PortfolioSummary`
  - 调 `get_concept_blocks(ticker)` 拿板块分类
  - 集中度 = 前 5 大持仓金额 / 总金额
- [ ] 1.2.5 实现 `compute_xirr(transactions, current_value, as_of) -> float`
  - 用 `scipy.optimize.brentq` 求 IRR=0 的根
  - 初始猜测 0.08（年化 8%）
  - 容差 1e-6，max 1000 iter
- [ ] 1.2.6 实现 `compute_max_drawdown(equity_curve) -> float`
  - equity_curve: `list[tuple[date, float]]`
  - 滚动 max + 当前值的最大跌幅
- [ ] 1.2.7 实现 `compute_sharpe(daily_returns, risk_free_rate=0.025) -> float`
  - 年化：(mean - rf_daily) / std * sqrt(252)
- [ ] 1.2.8 实现 `compute_brinson_attribution(positions, benchmark_returns) -> dict`
  - MVP：选股贡献 + 行业贡献两部分
  - 返回 `{"selection": float, "allocation": float, "total": float}`
- [ ] 1.2.9 实现 `compute_equity_curve(positions, transactions, current_prices, days=30) -> list[tuple[date, float]]`
  - 给 Sharpe / MaxDrawdown 喂数据

### 1.3 `backend/core/portfolio_alerts.py` 预警引擎

- [ ] 1.3.1 创建 `AlertTrigger` dataclass
  - 字段：`rule_id`, `ticker`, `rule_type`, `threshold`, `current_value`, `triggered_at`, `message`
- [ ] 1.3.2 实现 `evaluate_alerts(store, current_prices: dict[str, float]) -> list[AlertTrigger]`
  - 遍历 `store.list_alerts(enabled_only=True)`
  - 按 rule_type 分发比较逻辑（price_above 用 >=, price_below 用 <=, pct_change 用 abs diff, etc.）
  - 防重复：`last_triggered_at` 距今 < 300s 跳过
  - 触发后调 `store.record_trigger(rule_id, current_value)`
- [ ] 1.3.3 实现 `format_trigger_message(trigger: AlertTrigger) -> str`
  - 返回人类可读字符串："价格突破 7.00，当前 7.05 (+0.71%)"

### 1.4 `backend/core/portfolio_import.py` 导入导出

- [ ] 1.4.1 定义 `CSV_FORMATS` 字典
  - 4 种格式：eastmoney / ths (同花顺) / xueqiu / generic
  - 每种格式定义列名映射
- [ ] 1.4.2 实现 `detect_format(csv_path: Path) -> str | None`
  - 读前 5 行 header，匹配 format 置信度
- [ ] 1.4.3 实现 `parse_csv(csv_path: Path, format: str) -> list[dict]`
  - 输出标准格式：`[{ticker, name, cost, quantity, date}, ...]`
- [ ] 1.4.4 实现 `preview_import(parsed, existing_positions) -> dict`
  - 返回：`{"new": [...], "conflicts": [{parsed, existing}], "invalid": [...]}`
- [ ] 1.4.5 实现 `apply_import(preview, resolution_strategy) -> list[Position]`
  - `resolution_strategy`: `"overwrite"` | `"skip"` | `"merge"`
  - 写 `store._audit()` 记录 file_path + row_count + conflicts
- [ ] 1.4.6 实现 `export_csv(positions, transactions) -> Path`
  - 输出 UTF-8 BOM CSV（Excel 兼容）
  - 列：`代码, 名称, 成本价, 持仓数量, 持仓金额, 浮动盈亏, 盈亏比例, 首次买入日期, 备注`
- [ ] 1.4.7 实现 `export_transactions_csv(transactions) -> Path`

---

## Phase 2 — Web UI 层

### 2.1 `web/components/portfolio_panel.py` 入口

- [ ] 2.1.1 创建 `render_portfolio_panel() -> None` 函数
  - **入口第一行调 `store.ensure_default_account()`**（v0.5.0 增量）—— 保证下拉框永远有默认账户
  - 顶部调仓推送横幅（如果有信号变化）
  - `st.tabs(["📊 总览", "📜 流水", "🎯 配置", "🔔 预警", "📥 导入/导出", "📈 收益风险", "🏦 账户管理"])` —— **v0.5.0 新增 Tab 7**
  - 默认选中"总览" tab
- [ ] 2.1.2 实现 `_show_rebalance_banner(positions)`
  - 调 `get_rebalance_signals(lookback_days=7)`
  - 有信号变化时 `st.info()` 横幅："📊 模型信号变化：600595 HOLD → BUY (2026-07-07)"

### 2.2 7 个 Tab 实现（v0.5.0 +1）

- [ ] 2.2.1 Tab 1 — 总览
  - 顶部 4 个 metric 卡片（总市值 / 总成本 / 总盈亏 / 今日盈亏）
  - 表格：**v0.5.0 新增"账户"列** —— 列顺序：代码 / **账户** / 名称 / 持仓数量 / 成本价 / 现价 / 浮动盈亏 / 盈亏比例 / 持仓天数 / 操作
  - "录入新持仓" 按钮（调 `_add_position_dialog`）—— **账户字段改成 `st.selectbox` 下拉框**，选项 = `store.list_accounts()` 按 name 排序，默认账户排第一
  - 行操作：编辑 / 删除 / 录入交易
- [ ] 2.2.2 Tab 2 — 交易流水
  - 表格：**v0.5.0 新增"账户"列** —— 列顺序：日期 / 代码 / **账户** / 动作 / 价格 / 数量 / 手续费 / 备注
  - 按 ticker / **账户** / 时间筛选（v0.5.0 增量）
  - "录入新交易" 按钮（按 position_id 选）—— 账户字段也用 selectbox
- [ ] 2.2.3 Tab 3 — 资产配置
  - 行业分布饼图（用 altair 或 plotly）
  - 板块分布（按 `get_concept_blocks`）
  - 大类资产分布（按 `asset_class`）
  - **v0.5.0 新增"账户分布"饼图**（按账户聚合持仓金额）
  - 集中度（前 5 / 单股最大）
- [ ] 2.2.4 Tab 4 — 价格预警
  - 表格：ticker / 规则类型 / 阈值 / 启用 / 最后触发 / 触发次数 / 操作
  - "新增预警" 按钮（调 `_add_alert_dialog`）
  - "检查预警" 按钮（调 `evaluate_alerts` + `st.toast`）
- [ ] 2.2.5 Tab 5 — 导入 / 导出
  - 上传 CSV 文件 → 检测格式 → 预览 → 选 resolution → 导入
  - 下载 CSV 按钮（持仓 / 流水 两种）
  - 显示最近 5 条 audit log
- [ ] 2.2.6 Tab 6 — 收益与风险
  - 4 个 metric：总收益率 / 年化（XIRR） / 最大回撤 / 夏普比率
  - 与沪深 300 基准对比曲线（拉 `get_index_data("000300")`）
  - Brinson 归因 3 个数字（选股 / 行业 / 总）
- [ ] 2.2.7 Tab 7 — 账户管理（v0.5.0 新增）
  - 表格列：账户名 / 券商 / 账号后 4 位 / 大类资产 / 默认 ⭐ / 持仓数 / 创建时间 / 操作
  - "新增账户" 按钮（调 `_add_account_dialog`）
  - 行操作：编辑 / 删除 / 设为默认
  - **删除前检查持仓引用**：`list_positions(account=name)` 非空 → `st.warning` 阻断 + 提示"该账户下还有 N 只持仓，请先迁移或删除"
  - **同名拒绝**：`_add_account_dialog` 提交时如果 name 已存在 → `st.error("账户名已存在")` + 不调 store

### 2.3 `st.dialog` 模态表单

- [ ] 2.3.1 `_add_position_dialog()`（v0.5.0 改：账户字段用 selectbox）
  - 字段：ticker / name / cost_basis / quantity / first_buy_date / **account (selectbox，下拉，选项=store.list_accounts() 按 name 排序)** / asset_class / notes
  - 验证：ticker 6 位 / cost > 0 / quantity > 0 / account 必须在 list_accounts() 里
  - **asset_class 处理**：默认 "stock"（或从 `Account.asset_class` 继承）—— 选 selectbox 时给个 "继承账户默认" 选项
  - 提交后 `st.rerun()`
- [ ] 2.3.2 `_edit_position_dialog(position_id)`
  - 复用 add 表单，预填值
  - 提交后 update_position + st.rerun()
- [ ] 2.3.3 `_add_transaction_dialog(position_id)`（v0.5.0 改：账户字段用 selectbox）
  - 字段：date / action / price / quantity / fees / notes
  - **account 字段也用 selectbox**（v0.5.0 增量，可选；默认从 position.account 预填）
  - 验证：sell 时 quantity <= 持仓数量
- [ ] 2.3.4 `_add_alert_dialog()`
  - 字段：ticker / rule_type（selectbox）/ threshold / note / enabled（checkbox）
  - 提交后 add_alert + st.rerun()
- [ ] 2.3.5 `_add_account_dialog()`（v0.5.0 新增）
  - 字段：name（text_input）/ broker（text_input）/ account_number_tail（text_input，4 位）/ asset_class（selectbox: stock/bond/overseas/cash/fund）/ notes / is_default（checkbox）
  - 验证：name 非空 + 4-32 字符 + 不与现有账户同名
  - 提交后 add_account + st.rerun()

### 2.4 `web/app.py` 入口集成

- [ ] 2.4.1 在 `_NAV_ITEMS` 列表插入 "💼 我的仓位"
  - 位置：第 4 个，在 ("📈", "板块轮动", "sector") 之后
- [ ] 2.4.2 在主路由 `view == "portfolio"` elif 分支
  - `from web.components.portfolio_panel import render_portfolio_panel`
  - `render_portfolio_panel()`
- [ ] 2.4.3 在 `web/nav.py` 的 `plan_nav_click()` 加 portfolio 状态清理（如果需要）
  - 参考现有 history 的 viewing_history 清理逻辑

---

## Phase 3 — 测试

### 3.1 `tests/test_portfolio_store.py`

- [ ] 3.1.1 TestPortfolioStoreInit：单例模式 + 锁
- [ ] 3.1.2 TestPositionCRUD：增 / 改 / 删 / 查 / 列表
- [ ] 3.1.3 TestTransactionCRUD：增 / 列表（按 ticker 筛 / 按 since 筛）
- [ ] 3.1.4 TestAlertRuleCRUD：增 / 改 / 删 / 查 / 列表（按 enabled 筛）
- [ ] 3.1.5 TestThreadSafety：多线程并发 CRUD 验证
- [ ] 3.1.6 TestAuditLog：导入操作写 audit.log
- [ ] 3.1.7 TestAccountCRUD（v0.5.0 增量）
  - 增 / 改 / 删 / 查 / 列表
  - **name 唯一性**：同名 add → ValueError
  - **删除引用阻断**：账户下有持仓 → delete_account → ValueError
  - **set_default_account**：设置 A 为 default → B 自动让位
  - **get_account_by_name**：通过 name 查找
- [ ] 3.1.8 TestEnsureDefaultAccount（v0.5.0 增量）
  - 首次调用：accounts.json 不存在 → 创建 default 账户
  - 已有 default：no-op
  - 已有非 default 账户（删光了 default）：自动重建 default
  - 幂等性：连续调用 10 次只产生 1 个 default 账户

### 3.2 `tests/test_portfolio_calc.py`

- [ ] 3.2.1 TestPositionMetrics：单只持仓盈亏 + 当日盈亏 + 持仓天数
- [ ] 3.2.2 TestPortfolioSummary：组合汇总 + 行业 / 板块分布
- [ ] 3.2.3 TestXIRR：已知样本回归（单笔买入 + 持有 1 年，IRR ≈ (current - cost) / cost）
- [ ] 3.2.4 TestMaxDrawdown：滚动 max 算法边界
- [ ] 3.2.5 TestSharpe：年化算法边界（全部正收益 / 全部负收益 / 混合）
- [ ] 3.2.6 TestBrinson：选股贡献 + 行业贡献拆解

### 3.3 `tests/test_portfolio_alerts.py`

- [ ] 3.3.1 TestPriceAbove：当前价 > threshold 触发
- [ ] 3.3.2 TestPriceBelow：当前价 < threshold 触发
- [ ] 3.3.3 TestPctChange：当日涨跌幅超阈值触发
- [ ] 3.3.4 TestPnlPct：盈亏比例超阈值触发
- [ ] 3.3.5 TestAntiRepeat：触发后 5 分钟内不重复触发
- [ ] 3.3.6 TestDisabledAlert：disabled 不触发

### 3.4 `tests/test_portfolio_import.py`

- [ ] 3.4.1 TestDetectFormat：4 种格式自动检测（mock CSV 头）
- [ ] 3.4.2 TestParseCSV：4 种格式 sample data 解析
- [ ] 3.4.3 TestPreviewImport：冲突检测
- [ ] 3.4.4 TestApplyImport：3 种 resolution 策略
- [ ] 3.4.5 TestExportCSV：UTF-8 BOM 验证 + 列完整性

### 3.5 `tests/test_portfolio_panel.py`

- [ ] 3.5.1 TestPanelRender：mock streamlit snapshot 7 个 tab 都渲染（v0.5.0 +1）
- [ ] 3.5.2 TestAddPositionDialog：表单验证（**v0.5.0 改：账户字段是 selectbox 而非 text_input**）
- [ ] 3.5.3 TestRebalanceBanner：有 / 无信号变化两种状态
- [ ] 3.5.4 TestAccountSelectbox（v0.5.0 增量）
  - 验证 `_add_position_dialog` 账户字段是 `st.selectbox`
  - 选项 = `store.list_accounts()` 按 name 排序
  - 默认选项 = `is_default=True` 的账户
- [ ] 3.5.5 TestEnsureDefaultCalledOnPanelEnter（v0.5.0 增量）
  - 调用 `render_portfolio_panel()` 第一次 → `accounts.json` 存在一个 default 账户
  - 已存在 default → 不增加新账户
- [ ] 3.5.6 TestDeleteAccountBlocked（v0.5.0 增量）
  - 账户下有持仓 → 触发 `st.warning` 阻断
  - 账户下无持仓 → 实际删除
- [ ] 3.5.7 TestAddAccountDialogNameValidation（v0.5.0 增量）
  - 同名 → `st.error` 阻断
  - 不同名 → add_account 成功

### 3.6 集成 / 回归

- [ ] 3.6.1 跑 `python -m pytest tests/ -v` 确认 0 回归
- [ ] 3.6.2 跑 `python -m pytest tests/test_portfolio_*.py --cov=backend.core.portfolio_store --cov-fail-under=80`
  - 目标：新增代码覆盖率 ≥ 80%

---

## Phase 4 — Bull/Bear 联动 (P1)

### 4.1 `tradingagents/agents/utils/portfolio_tools.py`

- [ ] 4.1.1 实现 `get_my_position(ticker: str) -> dict`
  - 返回：`{position_id, ticker, name, cost_basis, quantity, current_value, pnl_abs, pnl_pct}`
  - LLM 工具：返回简化 dict
- [ ] 4.1.2 实现 `get_my_portfolio_summary() -> dict`
  - 返回：`{total_value, total_cost, total_pnl, today_pnl, positions_count, top5_concentration}`
- [ ] 4.1.3 实现 `get_my_rebalance_signals(lookback_days: int = 7) -> list[dict]`
  - 调 `history_store.list_all()` + diff signal 字段
  - 返回：`[{ticker, old_signal, new_signal, detected_at}, ...]`
- [ ] 4.1.4 实现 `register_tools() -> None`
  - 挂到 7 个 Analyst 的工具列表（参考 sector_rotation 的 signal_data_tools 挂法）
  - 在 `agent_utils.py` 加 import block

### 4.2 自动事件

- [ ] 4.2.1 在 Bull/Bear 报告生成后，调 `create_alert_from_signal()`
  - 如果 signal 是 BUY/SELL，自动创建对应方向的 take_profit / stop_loss 预警
  - 默认关闭，需用户在 settings 启用
- [ ] 4.2.2 实现 `create_alert_from_signal(position, signal) -> AlertRule`
  - take_profit：threshold = current_price * 1.10
  - stop_loss：threshold = current_price * 0.90
  - 默认 enabled=False

---

## Phase 5 — 文档与发布

### 5.1 `CLAUDE.md`

- [ ] 5.1.1 版本号升到 v0.5.0
- [ ] 5.1.2 在"Agent 角色"加"个人仓位模块（v0.5.0 新增）"
- [ ] 5.1.3 在"关键路径"加 `backend/core/portfolio_store.py` / `portfolio_calc.py` / `web/components/portfolio_panel.py`

### 5.2 `README.md`

- [ ] 5.2.1 功能列表新增"个人仓位跟踪"
- [ ] 5.2.2 截图（如果方便）

### 5.3 `CHANGELOG.md`

- [ ] 5.3.1 v0.5.0 entry
  - Added: 个人仓位模块（持仓 / 流水 / 配置 / 预警 / 导入导出 / 收益风险 6 tab）
  - Added: 调仓推送（与 Bull/Bear 信号变化联动）
  - Added: 资产配置分析（行业 / 板块 / 大类）
  - Added: XIRR / Sharpe / 最大回撤 / Brinson 归因
  - Known Limitations: 复权处理放 P2（成本价按用户录入计算）

### 5.4 Pre-merge Verification

- [ ] 5.4.1 `python -m pytest tests/ -v` 全套通过
- [ ] 5.4.2 `python -m pytest tests/test_portfolio_*.py --cov-fail-under=80` 新增代码 ≥ 80% 覆盖
- [ ] 5.4.3 live test：手动录入 2 只持仓，验证 Tab 1 表格 + 4 个 metric 卡片
- [ ] 5.4.4 live test：创建 3 条预警规则，点"检查预警"按钮，验证 `st.toast` 弹提示
- [ ] 5.4.5 live test：上传一份 mock CSV（东财格式），验证预览 + 导入
- [ ] 5.4.6 live test：等 Bull/Bear 分析完成后，进 Tab 1 验证调仓推送横幅
- [ ] 5.4.7 live test：Tab 6 收益风险页，验证 XIRR / Sharpe / 最大回撤数字合理
- [ ] 5.4.8 `git log` 规范：`feat: v0.5.0 — 个人仓位跟踪模块（持仓 + 预警 + 调仓推送）`
- [ ] 5.4.9 Code review：用 code-reviewer agent 检查 hardcoded secrets / SQL injection / error handling

---

## Phase 6 — (可选) Out-of-Scope Follow-ups

这些不在本 change 范围，留作后续 TODO：

- [ ] 6.1 P2: 复权处理（成本价按复权因子调整）
- [ ] 6.2 P2: Excel 多 sheet 导入（用户截图）
- [ ] 6.3 P2: Excel 多 sheet 导出
- [ ] 6.4 P3: 持仓脱敏分享
- [ ] 6.5 P3: 实时推送（cron / systemd 守护进程）
- [ ] 6.6 P3: 移动止损（trailing stop）
- [ ] 6.7 P3: 用户覆盖成本价的批量调整
- [ ] 6.8 P3: 持仓再平衡建议（按目标配置）