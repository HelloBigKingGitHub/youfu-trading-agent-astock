# React SPA Migration — Tasks

> **change_id**: `react-migration`
> **version**: v0.7.0
> **status**: proposed
> **target**: v0.7.0 release
>
> **硬约束**: Phase 1-2 期间, React SPA + Streamlit **并行运行**。Phase 3 触发条件**全部**满足前, **不删任何 streamlit 代码**。详见 `design.md` 第 5 节。

---

## Phase 1: 骨架 + 设置页 (3-5 天)

**目标**: 搭出 React SPA 完整骨架, 第一个 page (⚙️ 设置) 端到端跑通, 跟 FastAPI 串通, 三端口并行不冲突。

### 1.1 Vite + React 项目初始化

- [ ] **P1.1.1** 在仓库根新建 `frontend/` 目录, `npm create vite@latest frontend -- --template react-ts` 初始化
  - 验收: `frontend/package.json` 存在, `cd frontend && npm install` 成功
  - 谁: 用户 / Claude
- [ ] **P1.1.2** 锁版本: `package.json` 写明 `react@18.3.x`, `react-dom@18.3.x`, `vite@5.x`, `typescript@5.4+`
  - 验收: `npm ls react react-dom vite typescript` 输出符合
- [ ] **P1.1.3** `frontend/.gitignore` 写明 `node_modules/`, `dist/`, `.env.local`, `coverage/`
  - 验收: `git status` 不出现 `node_modules/`
- [ ] **P1.1.4** `frontend/.nvmrc` 写 `20`, 同步 `frontend/package.json` `engines.node = ">=20"`
  - 验收: `node --version` ≥ 20

### 1.2 Tailwind + shadcn/ui 集成

- [ ] **P1.2.1** 安装 Tailwind: `npm install -D tailwindcss@^3.4 postcss autoprefixer && npx tailwindcss init -p`
  - 验收: `tailwind.config.ts` + `postcss.config.js` 存在
- [ ] **P1.2.2** 配置 Tailwind content paths + dark mode class
  - 验收: `frontend/tailwind.config.ts` content 包含 `./index.html`, `./src/**/*.{ts,tsx}`
- [ ] **P1.2.3** shadcn init: `npx shadcn-ui@latest init`, 选 TypeScript + Tailwind + CSS variables
  - 验收: `frontend/components.json` 存在, `lib/utils.ts` 生成
- [ ] **P1.2.4** 首批组件: `npx shadcn-ui@latest add button dialog tabs form input select toast card dropdown-menu table sheet skeleton separator badge`
  - 验收: `frontend/src/components/ui/*.tsx` 16 个文件存在
- [ ] **P1.2.5** 移植 `web/styles/tokens.css` → `frontend/src/styles/tokens.css` (删除 streamlit-specific selector)
  - 验收: `frontend/src/styles/tokens.css` 包含 `--bb-accent / --bb-up / --bb-down / --bg-elevated / --bg-surface`
- [ ] **P1.2.6** `tailwind.config.ts` 桥接 CSS variables: `colors.bb.{accent,up,down,...}` → `var(--bb-*)`
  - 验收: `<div className="bg-bb-elevated text-bb-accent" />` 渲染正确
- [ ] **P1.2.7** `frontend/src/styles/globals.css` import `tailwind base/components/utilities` + `tokens.css`
  - 验收: 全局背景色 = `--bg-base`

### 1.3 状态管理 + 数据获取 + 路由

- [ ] **P1.3.1** 安装 Zustand: `npm install zustand@^4.5.0`
  - 验收: `useUIStore` (sidebar collapsed) 简单 store 跑通
- [ ] **P1.3.2** 安装 TanStack Query: `npm install @tanstack/react-query@^5 @tanstack/react-query-devtools@^5`
  - 验收: `<QueryClientProvider>` 包裹 App, devtools 可见
- [ ] **P1.3.3** 安装 React Router: `npm install react-router-dom@^6.26`
  - 验收: `frontend/src/router.tsx` 用 `createBrowserRouter`
- [ ] **P1.3.4** 安装工具库: `clsx` `tailwind-merge` `date-fns` `echarts@^6` `echarts-for-react@^3` `lightweight-charts@^5`
  - 验收: `frontend/src/lib/cn.ts` (clsx + twMerge) 跑通

### 1.4 Vite 配置 + 路由 + Sidebar

- [ ] **P1.4.1** `frontend/vite.config.ts` 配置 proxy: `/api` → `http://localhost:8000`
  - 验收: dev 模式 fetch `/api/health` 走 proxy 到 8000
- [ ] **P1.4.2** `frontend/src/router.tsx` 声明 9 个 sidebar route (全部 lazy + 占位 placeholder)
  - 验收: 9 个 route 注册, `<NavLink>` 跳转 OK
- [ ] **P1.4.3** `frontend/src/components/layout/Sidebar.tsx` 9 入口 (📝分析/📊批量/📈板块/💼仓位/📋历史/📋日志/📈走势/⏰定时/⚙️设置), 用 shadcn `Button` + `NavLink`
  - 验收: sidebar 9 按钮点击切换页面, active state 高亮
- [ ] **P1.4.4** `frontend/src/components/layout/Header.tsx` logo + 版本号 (从 `pyproject.toml` 读)
  - 验收: 顶部显示 `v0.7.0-dev`

### 1.5 后端扩展 — Settings API

- [ ] **P1.5.1** 新建 `backend/api/settings.py`, 实现 `GET /api/settings` (读 `~/.tradingagents/settings.json` + 环境变量 fallback)
  - 验收: `curl http://localhost:8000/api/settings` 返回 `{provider, deepModel, quickModel, apiKey: "***", baseUrl}`
- [ ] **P1.5.2** 实现 `POST /api/settings` (写 settings.json, 重新 load .env)
  - 验收: `curl -X POST -H 'Content-Type: application/json' -d '{"provider":"minimax"}' http://localhost:8000/api/settings` 返回 `{ok:true}`
- [ ] **P1.5.3** `backend/api/__init__.py` 注册 `settings_router`
  - 验收: `python -m backend.main` 启动后 `/api/settings` 路由可访问
- [ ] **P1.5.4** `backend/main.py` `CORSMiddleware` 保持 `allow_origins=["*"]` (开发), 加 comment "Phase 3 同源"
  - 验收: CORS 不影响前端调用

### 1.6 前端 — Settings Page

- [ ] **P1.6.1** `frontend/src/api/settings.ts` 实现 `getSettings()` `saveSettings(payload)`
  - 验收: TS 类型从 `types/api.ts` 推断
- [ ] **P1.6.2** `frontend/src/pages/Settings/SettingsPage.tsx` 用 shadcn `Form` + `Input` + `Select`
  - 验收: 页面渲染 4 个字段 (provider / deepModel / quickModel / baseUrl)
- [ ] **P1.6.3** `useQuery(['settings'], getSettings)` + `useMutation(saveSettings)`
  - 验收: 加载状态 / 错误 / 成功 toast 都正确
- [ ] **P1.6.4** 保存按钮 mutation 成功后 `queryClient.invalidateQueries(['settings'])`
  - 验收: 保存 → 立即看到新值

### 1.7 测试 setup

- [ ] **P1.7.1** 安装 Vitest: `npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom`
  - 验收: `npx vitest --version` 输出 ≥ 1.x
- [ ] **P1.7.2** `frontend/vitest.config.ts` 配置 jsdom + setup + alias
  - 验收: `npx vitest run` 找到 `tests/unit/` 测试
- [ ] **P1.7.3** `frontend/tests/setup.ts` import `@testing-library/jest-dom`
  - 验收: `expect(el).toBeInTheDocument()` 编译通过
- [ ] **P1.7.4** 安装 Playwright: `npm install -D @playwright/test && npx playwright install chromium`
  - 验收: `npx playwright --version` 输出 ≥ 1.x
- [ ] **P1.7.5** `frontend/playwright.config.ts` 配置 baseURL `http://localhost:5173` + webServer 启动 Vite
  - 验收: `npx playwright test` 自动启 dev server

### 1.6.5 Phase 1 Settings — Parity Gate (回顾, parity-check.md § 5.1)

- [ ] **P1.6.P1** **Parity Gate (设置页 Phase 1 retrospective, parity-check.md § 5.1)**
  - **Patch:** Phase 1 已完成 (P1.6.1-1.6.4 + P1.5.1-1.5.4 + P1.1.1-1.4.4 全部 ✅), 补回顾校验
  - **Verify:**
    - `npx playwright test settings.spec.ts` 0 失败 (打开 /settings → 改 LLM provider → 保存 → 刷新 → 验证, 5 步流程)
    - `python scripts/parity_check.py --page settings` hash 全等 (settings.json 字段顺序 1:1, `~/.tradingagents/settings.json` 读写一致)
    - `python scripts/parity_visual.py --page settings` AE < 1% 像素 (4 字段表单 + dark theme + shadcn 组件样式 1:1)
    - `python scripts/parity_perf.py --page settings` Lighthouse ≥ 80 (首次加载 LCP < 2.5s)
    - `python scripts/parity_fault_inject.py --page settings` settings.json 损坏 / API 401 / provider 不支持 错误 1:1
  - **用户确认:** 用户文字回复 "✅ settings parity 通过"
  - **记录:** 写 `parity-results/settings-diff.md`
  - **验收:** 5 步全绿 → Phase 1 真正完成 → 进 Phase 2 任意页面

### 1.8 Phase 1 单元测试 + E2E

- [ ] **P1.8.1** `frontend/tests/unit/SettingsPage.test.tsx` 至少 3 测试: 渲染 / 修改 / 保存
  - 验收: `npx vitest run SettingsPage` 全绿
- [ ] **P1.8.2** `frontend/tests/unit/format.test.ts` 测试日期 / 数字 / 百分比格式化
  - 验收: `npx vitest run format` 全绿
- [ ] **P1.8.3** `frontend/tests/unit/cn.test.ts` 测试 clsx + tailwind-merge
  - 验收: `npx vitest run cn` 全绿
- [ ] **P1.8.4** `frontend/tests/e2e/settings.spec.ts` 完整流程: 打开 /settings → 改 LLM provider → 保存 → 刷新 → 验证
  - 验收: `npx playwright test settings` 全绿

### 1.9 Phase 1 文档 + 验收

- [ ] **P1.9.1** `frontend/README.md` 写明三端口启动命令 (Vite 5173 / FastAPI 8000 / Streamlit 8501)
  - 验收: 新人按 README 能启动
- [ ] **P1.9.2** `frontend/scripts/dev.sh` 一键启动三个服务
  - 验收: `./scripts/dev.sh` 启 Vite + FastAPI + Streamlit
- [ ] **P1.9.3** `pytest tests/ -q` 全绿
  - 验收: `757 passed`
- [ ] **P1.9.4** commit: `feat(react): phase 1 — skeleton + settings page`
  - 验收: `git log --oneline` 出现 commit

---

## Phase 2: 逐页迁移 (2-3 周)

**目标**: 按"易 → 难"顺序迁移 9 个 sidebar 页, 每页 e2e 通过后才进下一页。

### 2.1 ⚙️ 设置 (Phase 1 已做)

- [x] **P2.1.1** Settings Page 端到端 (见 Phase 1)
  - 验收: Phase 1 验收清单

### 2.2 📋 历史 (1 天)

- [ ] **P2.2.1** 后端: 扩展 `backend/api/history.py` (已有) — 必要时加分页 / 过滤
  - 验收: `GET /api/history?page=1&size=20&ticker=` 工作
- [ ] **P2.2.2** 前端: `frontend/src/api/history.ts` (listHistory + deleteHistory)
  - 验收: TS 类型对齐
- [ ] **P2.2.3** 前端: `frontend/src/pages/History/HistoryPage.tsx` (列表 + 详情 dialog)
  - 验收: 用 shadcn `Table` + `Dialog` 渲染
- [ ] **P2.2.4** 前端: 详情 dialog 显示历史 report (markdown 渲染, 用 react-markdown)
  - 验收: 点开历史看到完整报告
- [ ] **P2.2.5** 测试: `HistoryPage.test.tsx` (3 测试) + `history.spec.ts` (3 场景)
  - 验收: vitest + playwright 全绿
- [ ] **P2.2.P1** **Parity Gate (硬约束, parity-check.md § 5.1)**
  - **Patch:** 上述 5 项完成后
  - **Verify:**
    - `npx playwright test history.spec.ts` 0 失败
    - `python scripts/parity_check.py --page history` hash 全等
    - `python scripts/parity_visual.py --page history` AE < 1% 像素
    - `python scripts/parity_perf.py --page history` Lighthouse ≥ 80
    - `python scripts/parity_fault_inject.py --page history` 错误文案 1:1
  - **用户确认:** 用户切 React / Streamlit 对比, 文字回复 "✅ history parity 通过"
  - **记录:** 写 `parity-results/history-diff.md`
  - **验收:** 5 步全绿 → 该页计入完成 → 进 2.3; 任一 ❌ → 该页任务**不算完成**
- [ ] **P2.2.6** commit: `feat(react): phase 2.2 — history page`

### 2.3 📋 日志 (1 天)

- [ ] **P2.3.1** 后端: 新建 `backend/api/logs.py` — `GET /api/logs` (list) + `GET /api/logs/{ticker}/{date}/{runId}` (detail)
  - 验收: 复用 `backend/core/log_store.py`, 接口能跑
- [ ] **P2.3.2** 后端: `GET /api/logs/{ticker}/{date}/{runId}/stream` (SSE 实时推送)
  - 验收: 类似 `sse.py` 模式
- [ ] **P2.3.3** 前端: `frontend/src/api/logs.ts` + `frontend/src/hooks/useLogStream.ts`
  - 验收: SSE EventSource 封装
- [ ] **P2.3.4** 前端: `frontend/src/pages/Logs/LogsPage.tsx` (GitHub PR 风格 1:3 双列)
  - 验收: 左 ticker 列表, 右 task + chunks
- [ ] **P2.3.5** 前端: chunks 按 type 着色 (llm / tool / agent_output), 折叠/展开
  - 验收: 用 shadcn `Collapsible`
- [ ] **P2.3.6** 测试: `LogsPage.test.tsx` + `logs.spec.ts`
  - 验收: 全绿
- [ ] **P2.3.P1** **Parity Gate (硬约束, parity-check.md § 5.1)**
  - **Patch:** 上述 6 项完成后
  - **Verify:**
    - `npx playwright test logs.spec.ts` 0 失败
    - `python scripts/parity_check.py --page logs` hash 全等
    - `python scripts/parity_visual.py --page logs` AE < 1% 像素
    - `python scripts/parity_perf.py --page logs` Lighthouse ≥ 80
    - `python scripts/parity_fault_inject.py --page logs` 错误文案 1:1
  - **用户确认:** 用户文字回复 "✅ logs parity 通过"
  - **记录:** 写 `parity-results/logs-diff.md`
  - **验收:** 5 步全绿 → 进 2.4
- [ ] **P2.3.7** commit: `feat(react): phase 2.3 — logs page`

### 2.4 📈 走势图 (2 天, 含 Lightweight Charts)

- [ ] **P2.4.1** 后端: 新建 `backend/api/chart.py` — `GET /api/analyze/kline` (历史 K 线, 3-fallback) + `GET /api/analyze/quote` (实时报价)
  - 验收: 复用 `tradingagents.dataflows.a_stock.get_stock_data`
- [ ] **P2.4.2** 前端: `frontend/src/components/charts/LightweightKline.tsx` 封装 Lightweight Charts v5
  - 验收: candlestick + MA5/10/20 line + volume histogram 副图
- [ ] **P2.4.3** 前端: `frontend/src/hooks/useKlineRealtime.ts` 浏览器直连 push2his SSE
  - 验收: 实时推送蜡烛图更新
- [ ] **P2.4.4** 前端: `frontend/src/pages/Chart/ChartPage.tsx` (ticker input + 7 range tabs + K 线 + quote banner)
  - 验收: 切 range 重新加载, K 线实时更新
- [ ] **P2.4.5** 前端: 中文 ticker 自动解析 (复用 `safe_ticker_component` 思路, 后端解析)
  - 验收: 输入 "贵州茅台" → 解析为 "600519"
- [ ] **P2.4.6** 测试: `LightweightKline.test.tsx` (3 测试) + `chart.spec.ts` (4 场景)
  - 验收: 全绿
- [ ] **P2.4.P1** **Parity Gate (硬约束, parity-check.md § 5.1, 最复杂页 ~12 操作)**
  - **Patch:** 上述 6 项完成后
  - **Verify:**
    - `npx playwright test chart.spec.ts` 0 失败 (含 SSE 推送验证)
    - `python scripts/parity_check.py --page chart --ticker 600519 --range 6m` hash 全等 (OHLCV / MA / Volume)
    - `python scripts/parity_visual.py --page chart` AE < 1% 像素 (K 线 + MA 颜色 1:1)
    - `python scripts/parity_perf.py --page chart` Lighthouse ≥ 80 (Lightweight Charts bundle 验证)
    - `python scripts/parity_fault_inject.py --page chart` ticker 不存在 / 数据源全 fail 错误 1:1
  - **用户确认:** 用户文字回复 "✅ chart parity 通过"
  - **记录:** 写 `parity-results/chart-diff.md` (重点: SSE 实时推送延迟 ≤ 1s)
  - **验收:** 5 步全绿 → 进 2.5
- [ ] **P2.4.7** commit: `feat(react): phase 2.4 — chart page (Lightweight Charts)`

### 2.5 📈 板块轮动 (1 天)

- [ ] **P2.5.1** 后端: 新建 `backend/api/sector.py` — `GET /api/sector/digest?date=&topN=`
  - 验收: 复用 `tradingagents.dataflows.a_stock.get_sector_rotation_digest`
- [ ] **P2.5.2** 前端: `frontend/src/api/sector.ts`
  - 验收: TS 类型对齐
- [ ] **P2.5.3** 前端: `frontend/src/components/charts/EChart.tsx` 封装 ECharts (饼图/柱图)
  - 验收: ECharts dark theme 渲染
- [ ] **P2.5.4** 前端: `frontend/src/pages/Sector/SectorPage.tsx` (Markdown 日报 + Top N 柱图 + 概念板块饼图)
  - 验收: react-markdown + EChart 双视图
- [ ] **P2.5.5** 测试: `SectorPage.test.tsx` + `sector.spec.ts`
  - 验收: 全绿
- [ ] **P2.5.P1** **Parity Gate (硬约束, parity-check.md § 5.1)**
  - **Patch:** 上述 5 项完成后
  - **Verify:**
    - `npx playwright test sector.spec.ts` 0 失败
    - `python scripts/parity_check.py --page sector` hash 全等 (digest Markdown md5sum 1:1)
    - `python scripts/parity_visual.py --page sector` AE < 1% 像素 (5 列表格布局 1:1)
    - `python scripts/parity_perf.py --page sector` Lighthouse ≥ 80
    - `python scripts/parity_fault_inject.py --page sector` 数据源 fail / date 错 错误 1:1
  - **用户确认:** 用户文字回复 "✅ sector parity 通过"
  - **记录:** 写 `parity-results/sector-diff.md`
  - **验收:** 5 步全绿 → 进 2.6
- [ ] **P2.5.6** commit: `feat(react): phase 2.5 — sector rotation page`

### 2.6 📊 批量分析 (3 天)

- [ ] **P2.6.1** 后端: 沿用现有 `backend/api/batch.py` (POST /api/batch, GET /api/batch/{id}, SSE stream)
  - 验收: 现有 6 个 endpoints 零修改
- [ ] **P2.6.2** 前端: `frontend/src/api/batch.ts` (createBatch / getBatch / cancel / retry)
  - 验收: TS 类型对齐
- [ ] **P2.6.3** 前端: `frontend/src/hooks/useBatchJobStream.ts` SSE 订阅批量进度
  - 验收: EventSource + 重连
- [ ] **P2.6.4** 前端: `frontend/src/pages/Batch/BatchPage.tsx` (3 sections: 提交 / 进行中 / 完成)
  - 验收: 上传 ticker 列表 → 启动 → 看进度 (实时 SSE) → 看汇总
- [ ] **P2.6.5** 前端: 进度条 (shadcn `Progress`) + 实时 ticker 完成列表 (shadcn `Table`)
  - 验收: 50 ticker 实时更新
- [ ] **P2.6.6** 前端: 汇总 dialog (Markdown 报告 + 重试/取消按钮)
  - 验收: 用 shadcn `Dialog` + `Sheet`
- [ ] **P2.6.7** 前端: ticker 校验 (6 位 A 股代码) — 复用后端 `_validate_ticker`
  - 验收: 非法 ticker 显示错误
- [ ] **P2.6.8** 测试: `BatchPage.test.tsx` + `batch.spec.ts` (5 场景)
  - 验收: 全绿
- [ ] **P2.6.P1** **Parity Gate (硬约束, parity-check.md § 5.1, 复杂操作流 ~14 操作)**
  - **Patch:** 上述 8 项完成后
  - **Verify:**
    - `npx playwright test batch.spec.ts` 0 失败 (含 SSE 批量进度 + 50 ticker 实时更新)
    - `python scripts/parity_check.py --page batch` hash 全等 (job dict / status 转换 1:1)
    - `python scripts/parity_visual.py --page batch` AE < 1% 像素 (3 sections 布局 + 状态图标 1:1)
    - `python scripts/parity_perf.py --page batch` Lighthouse ≥ 80 (50 ticker 实时不卡顿验证)
    - `python scripts/parity_fault_inject.py --page batch` ticker 空 / 全非法 / LLM 未配置 错误 1:1
  - **用户确认:** 用户文字回复 "✅ batch parity 通过"
  - **记录:** 写 `parity-results/batch-diff.md`
  - **验收:** 5 步全绿 → 进 2.7
- [ ] **P2.6.9** commit: `feat(react): phase 2.6 — batch analysis page`

### 2.7 💼 我的仓位 (4 天, 最复杂 6 tabs)

#### 2.7.1 基础 + 总览 Tab

- [ ] **P2.7.1** 后端: 新建 `backend/api/portfolio.py` — GET /api/portfolio/positions, /transactions, /alerts, /summary
  - 验收: 复用 `backend/core/portfolio_store.py` + `portfolio_calc.py`
- [ ] **P2.7.2** 前端: `frontend/src/api/portfolio.ts` (CRUD + summary)
  - 验收: TS 类型 = Position / Transaction / Alert
- [ ] **P2.7.3** 前端: `frontend/src/stores/usePortfolioStore.ts` (Zustand, persist 到 localStorage)
  - 验收: positions / transactions / alerts 状态管理
- [ ] **P2.7.4** 前端: `frontend/src/pages/Portfolio/PortfolioPage.tsx` (6 tabs layout)
  - 验收: shadcn `Tabs` 渲染 6 个 tab
- [ ] **P2.7.5** 前端: `OverviewTab.tsx` (汇总卡片 + 持仓表格)
  - 验收: 显示总盈亏 / 持仓数 / 集中度
- [ ] **P2.7.P1.1** **Parity Gate (仅总览 tab, parity-check.md § 5.1)**
  - **Patch:** 上述 5 项完成后
  - **Verify:** 跑总览 tab 的 parity 校验 (4 操作), 5 步全绿
  - **用户确认:** 用户文字回复 "✅ portfolio overview parity 通过"
  - **记录:** 写 `parity-results/portfolio-overview-diff.md`
- [ ] **P2.7.6** commit: `feat(react): phase 2.7.1 — portfolio overview tab`

#### 2.7.2 流水 Tab

- [ ] **P2.7.7** 前端: `TransactionsTab.tsx` (流水表格 + CRUD dialog)
  - 验收: 新增 / 编辑 / 删除 (shadcn `Dialog` + `Form`)
- [ ] **P2.7.8** 前端: 流水筛选 (按 ticker / 类型 / 日期)
  - 验收: shadcn `Select` + `Calendar` 过滤
- [ ] **P2.7.9** 测试: `TransactionsTab.test.tsx` + 集成到 portfolio.spec.ts
  - 验收: 全绿
- [ ] **P2.7.P1.2** **Parity Gate (流水 tab, parity-check.md § 5.1)**
  - **Patch:** 上述 9 项完成后
  - **Verify:** 跑流水 tab 的 parity 校验 (5 操作 + 3 错误场景), 5 步全绿
  - **用户确认:** 用户文字回复 "✅ portfolio transactions parity 通过"
  - **记录:** 写 `parity-results/portfolio-transactions-diff.md`
- [ ] **P2.7.10** commit: `feat(react): phase 2.7.2 — portfolio transactions tab`

#### 2.7.3 配置 Tab

- [ ] **P2.7.11** 后端: GET /api/portfolio/allocation (行业 / 板块 / 大类)
  - 验收: 复用 `portfolio_calc.group_by_sector` 等
- [ ] **P2.7.12** 前端: `AllocationTab.tsx` (3 饼图 + 集中度卡片)
  - 验收: EChart 饼图 + 数字
- [ ] **P2.7.P1.3** **Parity Gate (配置 tab, parity-check.md § 5.1)**
  - **Patch:** 上述 2 项完成后
  - **Verify:**
    - `npx playwright test portfolio.spec.ts -g "allocation"` 0 失败 (3 饼图渲染 + 集中度数字正确)
    - `python scripts/parity_check.py --page portfolio --tab allocation` hash 全等 (group_by_sector 行业 / 板块 / 大类 1:1, 集中度百分比精度 1:1)
    - `python scripts/parity_visual.py --page portfolio --tab allocation` AE < 1% 像素 (EChart dark theme + 卡片布局 1:1)
    - `python scripts/parity_perf.py --page portfolio --tab allocation` Lighthouse ≥ 80 (ECharts 渲染 3 饼图不卡顿)
    - `python scripts/parity_fault_inject.py --page portfolio --tab allocation` 行业映射缺失 / 集中度超 100% 错误 1:1
  - **用户确认:** 用户文字回复 "✅ portfolio allocation parity 通过"
  - **记录:** 写 `parity-results/portfolio-allocation-diff.md`
  - **验收:** 5 步全绿 → 进 2.7.4
- [ ] **P2.7.13** commit: `feat(react): phase 2.7.3 — portfolio allocation tab`

#### 2.7.4 预警 Tab

- [ ] **P2.7.14** 后端: POST/PUT/DELETE /api/portfolio/alerts (CRUD) + 评估接口
  - 验收: 7 种规则类型支持
- [ ] **P2.7.15** 前端: `AlertsTab.tsx` (预警列表 + 启停 + 编辑 dialog)
  - 验收: shadcn `Switch` + `Dialog`
- [ ] **P2.7.P1.4** **Parity Gate (预警 tab, parity-check.md § 5.1, 7 规则 + 300s anti-repeat 验证)**
  - **Patch:** 上述 2 项完成后
  - **Verify:**
    - `npx playwright test portfolio.spec.ts -g "alerts"` 0 失败 (7 规则启停 dialog + 列表 CRUD 全通过)
    - `python scripts/parity_check.py --page portfolio --tab alerts` hash 全等 (alerts.json 1:1, 7 规则 payload 字段顺序 1:1, audit log 1:1)
    - `python scripts/parity_visual.py --page portfolio --tab alerts` AE < 1% 像素 (Switch 状态色 + 列表布局 1:1)
    - `python scripts/parity_perf.py --page portfolio --tab alerts` Lighthouse ≥ 80 (后台 60s 评估轮询不阻塞 UI)
    - `python scripts/parity_fault_inject.py --page portfolio --tab alerts` 规则阈值非法 (price_above 负数 / pct_change 超 100) / 300s anti-repeat 触发 错误 1:1
  - **用户确认:** 用户文字回复 "✅ portfolio alerts parity 通过"
  - **记录:** 写 `parity-results/portfolio-alerts-diff.md` (重点: 300s anti-repeat LogStore 验证)
  - **验收:** 5 步全绿 → 进 2.7.5
- [ ] **P2.7.16** commit: `feat(react): phase 2.7.4 — portfolio alerts tab`

#### 2.7.5 导入导出 Tab

- [ ] **P2.7.17** 后端: POST /api/portfolio/import (4 种 CSV 格式) + GET /api/portfolio/export
  - 验收: 复用 `portfolio_import.py`
- [ ] **P2.7.18** 前端: `ImportExportTab.tsx` (上传 + 预览 + 确认导入)
  - 验收: shadcn `Tabs` + 表格预览
- [ ] **P2.7.P1.5** **Parity Gate (导入导出 tab, parity-check.md § 5.1, 4 种 CSV 格式 + UTF-8 BOM 验证)**
  - **Patch:** 上述 2 项完成后
  - **Verify:**
    - `npx playwright test portfolio.spec.ts -g "import-export"` 0 失败 (东财/同花顺/雪球/generic 4 格式上传 + 预览 + 确认导入流程)
    - `python scripts/parity_check.py --page portfolio --tab import` hash 全等 (detect_format 输出 1:1, parse 字段 1:1, preview rows 1:1, exported CSV md5sum 1:1)
    - `python scripts/parity_visual.py --page portfolio --tab import` AE < 1% 像素 (上传区 + 预览 table + 4 格式识别标签 1:1)
    - `python scripts/parity_perf.py --page portfolio --tab import` Lighthouse ≥ 80 (上传 10MB CSV 不卡)
    - `python scripts/parity_fault_inject.py --page portfolio --tab import` CSV 编码错 (非 UTF-8 / 非 GBK) / 列名不全 / 空文件 错误 1:1
  - **用户确认:** 用户文字回复 "✅ portfolio import parity 通过"
  - **记录:** 写 `parity-results/portfolio-import-diff.md` (重点: UTF-8 BOM Excel 友好验证)
  - **验收:** 5 步全绿 → 进 2.7.6
- [ ] **P2.7.19** commit: `feat(react): phase 2.7.5 — portfolio import/export tab`

#### 2.7.6 收益风险 Tab

- [ ] **P2.7.20** 后端: GET /api/portfolio/brinson + 已有 summary (XIRR/Sharpe/MaxDD)
  - 验收: 复用 `portfolio_calc`
- [ ] **P2.7.21** 前端: `RiskReturnTab.tsx` (4 卡片 + Brinson 柱图)
  - 验收: EChart 柱图 + 数字卡片
- [ ] **P2.7.22** 前端: Bull/Bear 信号 banner (空状态, MVP stub)
  - 验收: 显示空 banner 占位
- [ ] **P2.7.P1.6** **Parity Gate (收益风险 tab, parity-check.md § 5.1, XIRR/Sharpe/MaxDD/Brinson 数值精度验证)**
  - **Patch:** 上述 3 项完成后
  - **Verify:**
    - `npx playwright test portfolio.spec.ts -g "risk-return"` 0 失败 (4 卡片 + Brinson 柱图 + 空 banner 全通过)
    - `python scripts/parity_check.py --page portfolio --tab risk` hash 全等 (XIRR / Sharpe / MaxDD / Brinson 数值 1:1, 板块归因 1:1, 小数精度不丢)
    - `python scripts/parity_visual.py --page portfolio --tab risk` AE < 1% 像素 (4 卡片 + 柱图 + 空 banner 1:1)
    - `python scripts/parity_perf.py --page portfolio --tab risk` Lighthouse ≥ 80 (Brinson 大数据量计算不阻塞)
    - `python scripts/parity_fault_inject.py --page portfolio --tab risk` 数据不足 (XIRR 现金流 < 2 / Sharpe 单点) / Brinson 缺基准 错误 1:1
  - **用户确认:** 用户文字回复 "✅ portfolio risk-return parity 通过"
  - **记录:** 写 `parity-results/portfolio-risk-diff.md` (重点: 业绩归因数值精度验证)
  - **验收:** 5 步全绿 → 进 2.7 cross-tab
- [ ] **P2.7.23** 测试: 全 6 tabs + portfolio.spec.ts (8 场景)
  - 验收: 全绿
- [ ] **P2.7.24** commit: `feat(react): phase 2.7.6 — portfolio risk/return tab (6 tabs complete)`
- [ ] **P2.7.P2** **Parity Gate (portfolio 跨 6 tab 全局, parity-check.md § 5.2, Zustand 状态共享 + 切 tab 无重渲染验证)**
  - **Patch:** 上述 6 tab + 跨 tab 数据依赖 (overview 引用 transactions / allocation 引用 positions)
  - **Verify:**
    - `npx playwright test portfolio.spec.ts` 0 失败 (8 场景, 含 6 tab 串行切换 + Zustand 状态持久化 + localStorage reload)
    - `python scripts/parity_check.py --page portfolio` hash 全等 (6 tab 并行拉取同一 snapshot 数据 1:1, transactions 改动 → overview/concentration 自动联动)
    - `python scripts/parity_visual.py --page portfolio` AE < 1% 像素 (切 tab 时 skeleton + 数字骨架稳定, 无白屏闪烁)
    - `python scripts/parity_perf.py --page portfolio` Lighthouse ≥ 80 (6 tab 切回首页无重渲染, memo + useMemo 验证)
    - `python scripts/parity_fault_inject.py --page portfolio` 切 tab 时拉数据 fail / state 错乱 错误 1:1
  - **用户确认:** 用户文字回复 "✅ portfolio cross-tab parity 通过"
  - **记录:** 写 `parity-results/portfolio-cross-tab-diff.md`
  - **验收:** 5 步全绿 → 进 2.8

### 2.8 ⏰ 定时分析 (3 天)

- [ ] **P2.8.1** 后端: 新建 `backend/api/schedule.py` — CRUD + toggle + run-now + list-runs + tickers
  - 验收: 复用 `backend/core/scheduler.py`, 8 endpoints
- [ ] **P2.8.2** 前端: `frontend/src/api/schedule.ts`
  - 验收: TS 类型对齐
- [ ] **P2.8.3** 前端: `frontend/src/stores/useScheduleStore.ts`
  - 验收: schedules + runs 状态
- [ ] **P2.8.4** 前端: `frontend/src/pages/Schedule/SchedulePage.tsx` (3 sub-panel: 列表 / 编辑 / 历史)
  - 验收: shadcn `Tabs` 渲染
- [ ] **P2.8.5** 前端: cron 编辑器 (用 react-cron-generator 或自写)
  - 验收: 5-field cron 输入
- [ ] **P2.8.6** 前端: ticker 源选择 (portfolio / watchlist / manual)
  - 验收: shadcn `RadioGroup` 或 `Select`
- [ ] **P2.8.7** 前端: 通知渠道配置 (WeCom / Email / Desktop / Log) — 4 个 `Switch`
  - 验收: shadcn `Switch` 多选
- [ ] **P2.8.8** 前端: 运行历史表格 (ticker / 时间 / 状态 / 通知状态)
  - 验收: shadcn `Table`
- [ ] **P2.8.9** 前端: 立即运行按钮 (POST /api/schedule/{id}/run-now)
  - 验收: 触发后 30s 内看到新 run
- [ ] **P2.8.10** 测试: `SchedulePage.test.tsx` + `schedule.spec.ts` (5 场景)
  - 验收: 全绿
- [ ] **P2.8.P1** **Parity Gate (定时分析页, parity-check.md § 5.1, scheduler + notifier + watchlist + dialogs 验证)**
  - **Patch:** 上述 10 项完成后
  - **Verify:**
    - `npx playwright test schedule.spec.ts` 0 失败 (5 场景, 含 cron 编辑器 / 4 渠道通知 / run-now 触发后 30s 内 SSE 推送)
    - `python scripts/parity_check.py --page schedule` hash 全等 (Schedule / ScheduleRun JSON 1:1, croniter 下次触发时间 1:1, ticker 源 portfolio/watchlist/manual 解析 1:1)
    - `python scripts/parity_visual.py --page schedule` AE < 1% 像素 (3 sub-panel + cron 5-field + 4 Switch 1:1)
    - `python scripts/parity_perf.py --page schedule` Lighthouse ≥ 80 (60s 轮询后台不阻塞, schedule 列表 100 条不卡)
    - `python scripts/parity_fault_inject.py --page schedule` cron 表达式非法 / ticker 源为空 / 通知全关 / scheduler 单例锁冲突 错误 1:1
  - **用户确认:** 用户文字回复 "✅ schedule parity 通过"
  - **记录:** 写 `parity-results/schedule-diff.md` (重点: cron 下次触发时间 + 4 渠道通知验证)
  - **验收:** 5 步全绿 → 进 2.9
- [ ] **P2.8.11** commit: `feat(react): phase 2.8 — schedule page`

### 2.9 📝 分析 (3 天, 收尾)

- [ ] **P2.9.1** 后端: 沿用 `backend/api/analyze.py` (POST /api/analyze) + `result.py` (GET /api/analyze/{id}) + `sse.py` (SSE)
  - 验收: 现有 0 修改
- [ ] **P2.9.2** 前端: `frontend/src/api/analyze.ts` (startAnalysis / getResult / stream)
  - 验收: TS 类型 = AnalysisRequest / AnalysisResult / ProgressEvent
- [ ] **P2.9.3** 前端: `frontend/src/hooks/useAnalysisStream.ts` SSE 订阅进度
  - 验收: EventSource + 重连 + 错误处理
- [ ] **P2.9.4** 前端: `frontend/src/stores/useAnalysisStore.ts` (current ticker / stage / progress)
  - 验收: Zustand 持久化当前状态
- [ ] **P2.9.5** 前端: `frontend/src/pages/Analysis/AnalysisPage.tsx` (输入表单 + 进度 + 报告)
  - 验收: 三 section layout
- [ ] **P2.9.6** 前端: 表单 (ticker + trade_date + LLM 配置) — 复用 settings 的 LLM 配置
  - 验收: shadcn `Form` + `Input` + `Calendar`
- [ ] **P2.9.7** 前端: 进度展示 (PIPELINE_STAGES: 7 analyst + debate + risk + trader)
  - 验收: shadcn `Progress` + 阶段列表
- [ ] **P2.9.8** 前端: 报告查看 (Markdown 渲染 + 各 analyst 报告 tab)
  - 验收: react-markdown + shadcn `Tabs`
- [ ] **P2.9.9** 前端: 历史跳转 (报告底部 "查看历史" 按钮 → /history)
  - 验收: NavLink 跳转
- [ ] **P2.9.10** 测试: `AnalysisPage.test.tsx` + `analysis.spec.ts` (5 场景, 含 SSE)
  - 验收: 全绿
- [ ] **P2.9.P1** **Parity Gate (分析页, parity-check.md § 5.1, run_one_analysis + H1/H2 + 7 trader reports + workspace 验证)**
  - **Patch:** 上述 10 项完成后
  - **Verify:**
    - `npx playwright test analysis.spec.ts` 0 失败 (5 场景, 含表单校验 + SSE 进度流 + 7 analyst report tab + 报告 Markdown 渲染 + 历史跳转)
    - `python scripts/parity_check.py --page analysis --ticker 600519` hash 全等 (AnalysisRequest / AnalysisResult / ProgressEvent JSON 1:1, H1/H2 markdown md5sum 1:1, 7 trader reports 1:1, workspace log_stream 引用路径 1:1)
    - `python scripts/parity_visual.py --page analysis` AE < 1% 像素 (3 section layout + progress 阶段列表 + report tabs 1:1)
    - `python scripts/parity_perf.py --page analysis` Lighthouse ≥ 80 (SSE 长连接不阻塞 + 大 Markdown 报告懒加载)
    - `python scripts/parity_fault_inject.py --page analysis` ticker 非法 / LLM 未配置 / SSE 中断重连 / trade_date > today 错误 1:1
  - **用户确认:** 用户文字回复 "✅ analysis parity 通过"
  - **记录:** 写 `parity-results/analysis-diff.md` (重点: SSE 进度流 + 7 analyst 报告 1:1)
  - **验收:** 5 步全绿 → 进 2.10
- [ ] **P2.9.11** commit: `feat(react): phase 2.9 — analysis page (all 9 sidebar pages complete)`

### 2.10 Phase 2 整体验收

- [ ] **P2.10.0** 编写 4 个 parity tooling 脚本 (parity-check.md § 3 + § 5.1/5.2 依赖)
  - **P2.10.0.1** `scripts/parity_check.py` — 数据 hash 对比 (md5sum + recursive dict/list 比较)
    - 验收: `--page <page>` 支持 9 个 + `--tab <tab>` 支持 portfolio 6 个; 输出 hash 对比表 + 差异位置
  - **P2.10.0.2** `scripts/parity_visual.py` — 视觉 pixel diff (Playwright 截图 + PIL ImageChops, AE 算法)
    - 验收: 输出 AE% 像素差 + 红色高亮 diff 区域, 阈值 < 1%
  - **P2.10.0.3** `scripts/parity_perf.py` — Lighthouse Performance 校验
    - 验收: `--page <page>` 启 dev server, 跑 lighthouse CLI, 输出 Performance / FCP / LCP / TTI 指标
  - **P2.10.0.4** `scripts/parity_fault_inject.py` — 错误文案 1:1 对比 (mock 10 个异常场景)
    - 验收: 每个 page 输出错误文案表格 (React / Streamlit / Match/❌), 任一不匹配则 exit 1
  - **验证:** `python scripts/parity_check.py --help` 等 4 命令输出符合, `pytest tests/test_parity_tooling.py` (3 测试) 全绿
  - **验收:** 4 脚本就绪 → Phase 2 每页 parity gate 才有工具可用
- [ ] **P2.10.1** 全部 9 个 e2e spec 通过: `npx playwright test`
  - 验收: 0 失败
- [ ] **P2.10.2** pytest 757 全绿: `pytest tests/ -q`
  - 验收: `757 passed`
- [ ] **P2.10.3** Streamlit 9 个 panel 无回归 (对比测试)
  - 验收: 手动验证每个 panel 仍能用
- [ ] **P2.10.4** 三端口并行 7 天无关键问题
  - 验收: 用户观察 + 日志无 ERROR
- [ ] **P2.10.5** `git log --oneline` 出现至少 9 个 phase 2.x commit
  - 验收: per-page commits
- [ ] **P2.10.6** commit: `feat(react): phase 2 complete — all 9 sidebar pages migrated`
- [ ] **P2.10.7** **跨页串行 Parity Gate (parity-check.md § 5.2, 9 sidebar nav 切换 + 7 天 fallback 监控)**
  - **Patch:** 全部 9 页 e2e + 每页单独 P*.P1 完成后
  - **Verify:**
    - 跨页串行: `npx playwright test` 9 spec 顺序跑 (settings → history → logs → chart → sector → batch → portfolio → schedule → analysis) 全绿, 无串行状态污染
    - 跨页一致性: `python scripts/parity_check.py` 全 9 页 hash 对比, 任意页 hash 异常 → exit 1
    - 跨页视觉: `python scripts/parity_visual.py` 全 9 页截图 batch diff, AE < 1%
    - 跨页性能: `python scripts/parity_perf.py` 全 9 页 Lighthouse batch, 任一 < 80 → exit 1
    - 跨页错误: `python scripts/parity_fault_inject.py` 全 9 页 ×10 个错误场景 = 90 场景, 任一不匹配 → exit 1
    - 9 sidebar nav 切换: 手动 + e2e 验证切页无状态丢失, 不重渲染卡顿, queryClient cache 复用
    - 7 天 fallback 监控: Streamlit 8501 端口运行 ≥ 7 天, 日志无 ERROR, 用户无 bug 反馈
  - **用户确认:** 用户手动跑完 9 页 → 截图/录屏/文字 "✅ 全部 9 页跑过, OK"
  - **记录:** 写 `parity-results/phase2-cross-page-diff.md` + `parity-results/7day-fallback-log.md`
  - **验收:** 5 步全绿 + 7 天 fallback 通过 → Phase 2 整体完成 → Phase 3 触发检查启动

---

## Phase 3: 删 Streamlit 渲染代码 (1 天, **触发后才执行**)

### ⛔ 硬约束: 触发条件 (6 条全部 ✅ 才进)

> 未满足任一条件 → **不进入 Phase 3**。任何时候用户没明确下令前, 都并行运行 streamlit + React。

- [ ] **T1** React SPA 全部 9 个 sidebar 页跑通且 e2e 通过
  - 验证: `cd frontend && npm run build` 成功 + `npx playwright test` 退出码 0
- [ ] **T2** Playwright e2e 0 失败
  - 验证: `npx playwright test` 全部 9 spec 通过
- [ ] **T3** pytest 757 passed (0 回归)
  - 验证: `pytest tests/ -q` 输出 `757 passed`
- [ ] **T4** 用户手动跑一遍全部 9 个页 (用户截图/录屏/文字确认)
  - 验证: 用户回复 "✅ 全部 9 页跑过, OK"
- [ ] **T5** Streamlit fallback 端口运行 ≥ 7 天**无关键问题**
  - 验证: 7 天内无 ERROR 日志 + 用户无 bug 反馈
- [ ] **T6** 用户明确下令: "现在可以删 streamlit 代码"
  - 验证: 用户消息包含此原话或近似指令

**6 条全部 ✅ 才继续, 任一 ❌ → STOP, 等条件满足**。

### 3.1 备份 + 准备

- [ ] **P3.1.1** `git checkout -b phase-3-streamlit-removal`
  - 验收: 新分支存在
- [ ] **P3.1.2** `git tag v0.7.0-pre-phase3` (回滚点)
  - 验收: tag 存在

### 3.2 删除 Streamlit 渲染代码 (29 文件)

- [ ] **P3.2.1** `git rm web/app.py` (447 行)
  - 验收: 文件已删
- [ ] **P3.2.2** `git rm web/components/*.py` (21 文件, 5665 行) — 一次性:
  ```bash
  git rm web/components/batch_panel.py \
         web/components/chart_panel.py \
         web/components/history_panel.py \
         web/components/logs_panel.py \
         web/components/portfolio_accounts.py \
         web/components/portfolio_alerts_view.py \
         web/components/portfolio_allocation.py \
         web/components/portfolio_dialogs.py \
         web/components/portfolio_import_view.py \
         web/components/portfolio_overview.py \
         web/components/portfolio_panel.py \
         web/components/portfolio_risk.py \
         web/components/portfolio_transactions.py \
         web/components/progress_panel.py \
         web/components/report_viewer.py \
         web/components/schedule_dialogs.py \
         web/components/schedule_panel.py \
         web/components/sector_panel.py \
         web/components/settings_panel.py \
         web/components/sidebar.py \
         web/components/__init__.py
  ```
  - 验收: `web/components/` 目录不存在 (除 git 历史)
- [ ] **P3.2.3** `git rm web/styles/elements.css` (1393 行)
  - 验收: 文件已删
- [ ] **P3.2.4** `git rm web/styles.py` (797 行)
  - 验收: 文件已删
- [ ] **P3.2.5** `git rm web/progress.py` (97 行)
  - 验收: 文件已删
- [ ] **P3.2.6** `git rm web/nav.py` (130 行)
  - 验收: 文件已删
- [ ] **P3.2.7** `git rm web/launch.py` (25 行)
  - 验收: 文件已删
- [ ] **P3.2.8** 评估 `web/styles/base.css` + `web/styles/components.css` 是否仅 streamlit 用 — 如是, 删
  - 验收: 检查后决定

### 3.3 删 Streamlit 测试 (7-8 文件)

- [ ] **P3.3.1** `git rm tests/test_web_app_dispatch.py` (244 行)
- [ ] **P3.3.2** `git rm tests/test_running_view_refresh.py` (122 行)
- [ ] **P3.3.3** `git rm tests/test_chart_panel.py` (271 行)
- [ ] **P3.3.4** `git rm tests/test_chart_panel_quote.py` (97 行)
- [ ] **P3.3.5** `git rm tests/test_logs_panel.py` (103 行)
- [ ] **P3.3.6** `git rm tests/test_portfolio_panel.py` (842 行)
- [ ] **P3.3.7** 检查 `tests/test_web_runner.py` 是否含非 UI 测试 — 如全 UI, 删; 如有业务测试, 保留
  - 验收: 决定后执行

### 3.4 清理 pyproject.toml 依赖

- [ ] **P3.4.1** 编辑 `pyproject.toml`, 删除 `"streamlit>=1.45.0"` 那一行
  - 验收: `grep streamlit pyproject.toml` 无输出
- [ ] **P3.4.2** 检查 `pyproject.toml` 是否还有 streamlit 间接依赖 (`fpdf2` 是 PDF 导出, 保留)
  - 验收: 仅 streamlit 移除

### 3.5 评估剩余 web/ 文件 (非必须, 建议)

- [ ] **P3.5.1** `web/runner.py` (301 行) — 含业务逻辑, 评估: 保留作 backend wrapper 或迁移到 `backend/core/runner.py`
  - 验收: 决策记录在 commit message
- [ ] **P3.5.2** `web/pdf_export.py` (410 行) — 评估: 迁移到 `backend/core/pdf_export.py` 或删除 (前端不需要 PDF)
  - 验收: 决策记录
- [ ] **P3.5.3** `web/history.py` (69 行) — 评估: 是否被任何代码引用
  - 验收: `grep -r "from web.history" --include="*.py"` 无输出则删
- [ ] **P3.5.4** `web/_signal_helpers.py` (27 行) — 同上
- [ ] **P3.5.5** `web/static/` 目录 — 清空或保留
  - 验收: 决策记录

### 3.6 后端 — 静态挂载 SPA

- [ ] **P3.6.1** `backend/main.py` 增加 StaticFiles 挂载 + SPA fallback (见 `design.md` 第 11 节)
  - 验收: `python -m backend.main` 启动后 `http://localhost:8000/` 返回 React index.html
- [ ] **P3.6.2** `backend/main.py` CORSMiddleware 改同源 (可保留 `["*"]` 兼容 Phase 3 之前的混合部署)
  - 验收: 评论说明

### 3.7 验证脚本

- [ ] **P3.7.1** 跑 pytest: `pytest tests/ -q`
  - 验收: ~600-650 passed (业务测试, 不含 Streamlit mock)
- [ ] **P3.7.2** 跑前端 build: `cd frontend && npm run build`
  - 验收: 0 error
- [ ] **P3.7.3** 跑前端 e2e: `cd frontend && npx playwright test`
  - 验收: 0 失败 (全部 9 spec)
- [ ] **P3.7.4** 验证 streamlit 找不到: `python -m streamlit run web/app.py`
  - 验收: 报错 `No module named 'streamlit'` 或 `web/app.py not found`
- [ ] **P3.7.5** 验证数据完整: `ls ~/.tradingagents/`
  - 验收: logs/ history/ portfolio/ schedules/ watchlist/ cache/ 全部存在, 内容不变
- [ ] **P3.7.6** 验证 tradingagents-web 报错: `tradingagents-web`
  - 验收: 报错 (因 streamlit 找不到) 或重定向到 React 启动
- [ ] **P3.7.7** 验证 web/ 不存在: `ls web/`
  - 验收: `No such file or directory`

### 3.8 commit + tag

- [ ] **P3.8.1** commit: `refactor: phase 3 — delete streamlit rendering code (~9.6k lines)`
  - 验收: commit 存在
- [ ] **P3.8.2** `git tag v0.7.0`
  - 验收: tag 存在

### 3.9 文档更新

- [ ] **P3.9.1** `CHANGELOG.md` 增加 v0.7.0 条目
  - 验收: changelog 包含 phase 1-3 摘要
- [ ] **P3.9.2** `CLAUDE.md` 更新架构图 (删 streamlit, 加 React)
  - 验收: 架构图反映新栈
- [ ] **P3.9.3** `README.md` 更新启动命令 (从 3 端口 → 1 端口)
  - 验收: README 显示 `python -m backend.main` 单命令启动
- [ ] **P3.9.4** commit: `docs: v0.7.0 release notes`
  - 验收: commit 存在

### 3.10 最终验收清单

- [ ] **P3.10.1** `web/` 目录不存在
  - 验证: `ls web/` → No such file or directory
- [ ] **P3.10.2** Streamlit 不可用: `python -c "import streamlit"` 报错
- [ ] **P3.10.3** pytest 业务测试全绿 (~600-650 passed)
- [ ] **P3.10.4** React SPA build 成功 + 9 页 e2e 通过
- [ ] **P3.10.5** 单端口启动: `python -m backend.main` → http://localhost:8000 全部 OK
- [ ] **P3.10.6** `~/.tradingagents/` 数据 0 改动
- [ ] **P3.10.7** `git tag v0.7.0` 发布
- [ ] **P3.10.8** 用户接受 v0.7.0 (用户消息确认)

---

## 进度跟踪 (Progress Tracking)

| Phase | 任务数 | 完成 | 状态 |
|---|---|---|---|
| Phase 1 (骨架 + 设置) | 26 | 0/26 | ⬜ 待开始 (含 P1.6.P1) |
| Phase 2.1 (设置) | 1 | 0/1 | ⬜ (Phase 1 已做) |
| Phase 2.2 (历史) | 7 | 0/7 | ⬜ 待开始 (含 P2.2.P1) |
| Phase 2.3 (日志) | 8 | 0/8 | ⬜ 待开始 (含 P2.3.P1) |
| Phase 2.4 (走势图) | 8 | 0/8 | ⬜ 待开始 (含 P2.4.P1) |
| Phase 2.5 (板块) | 7 | 0/7 | ⬜ 待开始 (含 P2.5.P1) |
| Phase 2.6 (批量) | 10 | 0/10 | ⬜ 待开始 (含 P2.6.P1) |
| Phase 2.7 (仓位) | 27 | 0/27 | ⬜ 待开始 (含 P2.7.P1.1~.6 + P2.7.P2) |
| Phase 2.8 (定时) | 12 | 0/12 | ⬜ 待开始 (含 P2.8.P1) |
| Phase 2.9 (分析) | 12 | 0/12 | ⬜ 待开始 (含 P2.9.P1) |
| Phase 2.10 (整体) | 8 | 0/8 | ⬜ 待开始 (含 P2.10.0 + P2.10.7) |
| Phase 3 (删除) | ~30 | 0/30 | ⛔ 等待触发 (8 条触发条件) |
| **总计** | **~156** | **0/156** | **0%** |

---

## 紧急回滚 (Rollback)

任何 Phase 出问题, 立即回滚:

```bash
# Phase 1 回滚
git revert <phase-1-commit>
# 删 frontend/
rm -rf frontend/

# Phase 2.X 回滚 (单页回滚)
git revert <phase-2.X-commit>
# 该页 React 实现删除, Streamlit 对应 panel 仍是默认前端

# Phase 3 回滚
git revert <phase-3-commit>
pip install streamlit>=1.45.0
# Streamlit 恢复, web/ 目录恢复
```

**回滚不删数据**: `~/.tradingagents/` 全程不删, 回滚即恢复访问。

---

*任务清单结束。Phase 3 触发条件 8 条详见清单顶部 (含 2 条 parity 校验: 每页 § 5.1 + 跨页 § 5.2)。*