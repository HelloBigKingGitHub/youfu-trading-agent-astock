# React SPA Migration — Design

> **change_id**: `react-migration`
> **version**: v0.7.0
> **kind**: breaking
> **status**: proposed (Phase 1 — skeleton)

---

## Context

### 背景

`youfu-trading-agent-astock` 是基于 TauricResearch/TradingAgents (65K ⭐) 的 A 股深度特化 fork。v0.6.0 (最新) 已有完整业务:

- **7 个 Analyst** (市场/情绪/新闻/基本面/政策/游资/解禁)
- **Bull/Bear 辩论 + 三方风险辩论**
- **9 个 sidebar 页** (📝分析 / 📊批量 / 📈板块 / 💼仓位 / 📋历史 / 📋日志 / 📈走势 / ⏰定时 / ⚙️设置)
- **板块轮动日报** (v0.2.12)
- **个人仓位跟踪 + Brinson 业绩归因** (v0.5.0)
- **定时分析 + 多渠道通知** (v0.6.0)
- **757 pytest passed** (零回归底线)

**问题**: 整个 UI 跑在 Streamlit 上, 见 `proposal.md` 第 1 节 7 个痛点。

**决策**: v0.7.0 把前端从 Streamlit 迁到 React SPA, Python 只做后端 (FastAPI)。

### 目标读者

- 实施者 (本次: 用户自己)
- 未来维护者 (同上)
- 任何 reviewer / AI agent

### 不在范围

- 不重写 Python 业务代码
- 不改 pytest 757 任何用例
- 不引入 SSR / Next.js (纯 SPA 即可, 个人工具)
- 不引入 RBAC / OAuth / 多用户 (个人工具)

---

## 关键决策 (Decisions)

### Decision 1: 前端框架 = Vite + React 18 + TypeScript

**问题**: 用什么前端框架? 选项: Next.js / Remix / Vite + React / Astro / SvelteKit / 纯 HTML+JS

**决策**: **Vite + React 18 + TypeScript**

**理由**:
1. **Vite dev server 秒级 HMR** — Streamlit 痛点之一就是 rerun 卡顿, Vite HMR < 100ms
2. **React 18 并发渲染** — `useTransition` / `useDeferredValue` 解批量分析 50 只票重渲染
3. **TypeScript 必备** — 9 个 sidebar × 多 tab × 多 dialog, JS 撑不住
4. **Vite bundle 体积小** — Production build 默认 code splitting, 首屏 < 200KB
5. **不需要 SSR** — 个人工具, 内网部署, SEO 无关

**替代方案**:
- ❌ Next.js: 过度工程, 个人工具不需要 SSR / RSC / image optimization
- ❌ Remix: 同上, 而且生态比 Next.js 小
- ❌ SvelteKit: 学习曲线 + 用户已知 React 生态
- ❌ Astro: 内容站框架, 不是 SPA 框架
- ✅ Vite + React 18 + TS: 事实标准, 生态最大, 用户已有 `youfu-known` 经验

**Trade-off**: 没有 SSR, 首屏需要 JS bundle 才能渲染 (但有 skeleton), 接受。

**实现细节**:
- `frontend/package.json` 锁版本: `react@18.3.x`, `react-dom@18.3.x`, `vite@5.x`, `typescript@5.4+`
- `frontend/vite.config.ts` 配置 proxy: `/api` → `http://localhost:8000`
- `frontend/tsconfig.json` strict 模式

---

### Decision 2: UI 组件库 = shadcn/ui

**问题**: UI 组件怎么来? 选项: MUI / Ant Design / Chakra UI / Material-UI / Radix UI / shadcn/ui / Headless UI

**决策**: **shadcn/ui** (Tailwind + Radix + copy-paste 哲学)

**理由**:
1. **零运行时开销** — 组件代码 copy 到自己的 repo, 不引第三方 runtime
2. **完全可控** — 改样式直接改 `frontend/src/components/ui/button.tsx`, 不等上游
3. **Tailwind 集成** — 暗色 Bloomberg 风 token 直接走 Tailwind theme
4. **Radix 底层** — 无障碍 (a11y) 默认通过, 不需自己写 ARIA
5. **不需要 i18n** — shadcn/ui 默认英文标签, 中文 hard-code 即可
6. **用户已有 youfu-known Chakra 经验** — Chakra 也行, 但 shadcn/ui 更轻

**替代方案**:
- ❌ MUI / Ant Design: bundle 重 (200KB+), 主题定制复杂
- ❌ Chakra UI: 用户已知, 但运行时大, 主题 layer 抽象
- ✅ shadcn/ui: 60KB 级 Tailwind + Radix 组件, 100% 可控

**Trade-off**: copy-paste 哲学 = 升级时需手动同步, 但 shadcn 升级频繁度低。

**实现细节**:
- `npx shadcn-ui@latest init` → 生成 `components.json` + `tailwind.config.ts` + `lib/utils.ts`
- 首批组件: `button / dialog / tabs / form / input / select / table / toast / dropdown-menu / card / badge / separator / sheet / skeleton`
- 主题 token 沿用 `web/styles/tokens.css` 的 `--bb-*` 变量, 移植到 `frontend/src/styles/tokens.css`

---

### Decision 3: K 线库 = TradingView Lightweight Charts v5

**问题**: K 线图用什么? 选项: Lightweight Charts / ECharts / Highcharts / Plotly.js / Recharts / d3.js / 自己写 canvas

**决策**: **TradingView Lightweight Charts v5** (Apache-2.0, 61 KB gzip)

**理由**:
1. **事实标准** — 业界 K 线方案头部选, 同花顺 / 雪球 / 老虎都用
2. **体积小** — 61 KB gzip, 比 ECharts K 线方案 (~250 KB) 小 4 倍
3. **性能强** — Canvas 渲染, 10000+ 蜡烛无压力
4. **已有 streamlit 集成经验** — v0.4.0 chart_panel 已经用 CDN v4.1.3 跑通 SSE, 直接升 v5
5. **Apache-2.0** — 商用 OK, 无水印

**替代方案**:
- ❌ ECharts K 线 (candlestick): 自带够用, 但性能 + 美观不如 Lightweight Charts
- ❌ Highcharts: 非开源 (商用 license 费)
- ❌ Plotly.js: bundle 重 (~3MB), 学术风
- ❌ Recharts / d3: SVG 渲染, K 线性能差
- ✅ Lightweight Charts: 体积 / 性能 / 美观 / 商业 都最优

**Trade-off**: v5 API 与 v4 不完全兼容, chart_panel 旧代码不能直接复用, 但 React 重写本来就用新 API。

**实现细节**:
- `npm install lightweight-charts@^5.0.0`
- 封装 `<LightweightKline data={ohlcv[]} onCrosshairMove={...} />` 在 `frontend/src/components/charts/LightweightKline.tsx`
- MA5/10/20 用 `lineSeries` overlay
- 成交量副图用 `histogramSeries`
- 实时推送用 SSE (WebSocket 见 Decision 7)

---

### Decision 4: 通用图表 = Apache ECharts 6

**问题**: 非 K 线图 (饼图/柱图/折线/雷达) 用什么? 选项: ECharts / Chart.js / Recharts / Nivo / Plotly

**决策**: **Apache ECharts 6** (Apache-2.0)

**理由**:
1. **覆盖面最广** — 饼/柱/折线/雷达/桑基/热力/地图, 全场景
2. **中文文档最好** — 国产项目, 中文文档详尽
3. **主题丰富** — `dark` 主题匹配 Bloomberg 暗色风
4. **性能好** — Canvas + 增量渲染, 1w+ 数据点流畅
5. **暗色适配** — 直接用 `dark` theme, 跟 `--bb-*` token 兼容

**替代方案**:
- ❌ Chart.js: 功能弱, 不支持复杂可视化
- ❌ Recharts: 仅 React 生态, 自定义差
- ❌ Plotly: bundle 重 (3MB+)
- ✅ ECharts: 国产之光, 中文文档, 暗色好

**Trade-off**: bundle 偏大 (~300 KB min), 用 dynamic import 懒加载。

**实现细节**:
- `npm install echarts@^6.0.0 echarts-for-react@^3.0.2`
- 封装 `<EChart option={...} />` 在 `frontend/src/components/charts/EChart.tsx`
- 暗色主题: `import 'echarts/theme/dark'`
- 用于: 板块轮动饼图 / 仓位行业归因 / Brinson 业绩归因 / 流水趋势

---

### Decision 5: 状态管理 = Zustand

**问题**: 客户端状态怎么管? 选项: Redux Toolkit / Zustand / Jotai / Recoil / MobX / React Context

**决策**: **Zustand** (4KB)

**理由**:
1. **轻量** — 4 KB, Redux Toolkit 50 KB
2. **API 简单** — `const useStore = create(set => ({ count: 0, inc: () => set(s => ({count: s.count+1})) }))`
3. **无 boilerplate** — Redux Toolkit 还要写 slice / reducer / action / dispatch
4. **TS 友好** — `create<State>()(...)` 推断完整
5. **持久化中间件** — `zustand/middleware` `persist` 直接接 localStorage

**替代方案**:
- ❌ Redux Toolkit: 个人工具过度, 4 个页用不上 RTK Query
- ❌ Jotai: atomic 思路好但 Zustand store 思路更直观
- ❌ React Context: 频繁更新会触发整树 rerender
- ✅ Zustand: 4KB, API 简单, 适合个人工具

**Trade-off**: 生态比 Redux 小, 但本项目不需要 time-travel debug / middleware 链。

**实现细节**:
- `npm install zustand@^4.5.0`
- 三大 store: `usePortfolioStore` (positions / transactions / alerts), `useScheduleStore` (schedules / runs), `useAnalysisStore` (current ticker / stage / progress)
- 持久化中间件: portfolioStore (持久到 localStorage, key `yt-portfolio-cache`, TTL 1h)

---

### Decision 6: HTTP 客户端 = TanStack Query v5

**问题**: 服务端状态 (server state) 怎么管? 选项: TanStack Query / SWR / axios + 自写 / fetch + 自写

**决策**: **TanStack Query v5** (前身 React Query)

**理由**:
1. **缓存 + 失效** — `useQuery` 自带 staleTime / cacheTime / invalidation, 不用自己写
2. **乐观更新** — `useMutation` 的 `onMutate` / `onError` / `onSettled` 三段式, 适合 portfolio CRUD
3. **重试 + 错误边界** — 默认 3 次指数退避重试
4. **devtools** — `@tanstack/react-query-devtools` 一行接入
5. **跟 Zustand 互补** — Zustand 管客户端状态, TanStack Query 管服务端状态, 边界清晰

**替代方案**:
- ❌ SWR: 比 TanStack Query 功能少, 社区小
- ❌ axios + 自写: 自己实现缓存 / 失效 / 重试, 重复造轮子
- ✅ TanStack Query: 业界事实标准

**Trade-off**: 学习曲线略高, 但有完整 TS 推断 + devtools。

**实现细节**:
- `npm install @tanstack/react-query@^5.0.0 @tanstack/react-query-devtools@^5.0.0`
- 单实例 `<QueryClientProvider>` 包裹 App
- 关键 query keys 工厂: `queryKeys.analyze.detail(id)`, `queryKeys.batch.list()`, `queryKeys.portfolio.positions()`
- 失效策略: `mutation` 成功后 `queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.all })`

---

### Decision 7: 路由 = React Router 6

**问题**: 客户端路由用什么? 选项: React Router 6 / TanStack Router / Next.js router / 自写 hash router

**决策**: **React Router 6** (`createBrowserRouter` + 数据路由)

**理由**:
1. **成熟稳定** — 9.x 历史悠久, 文档全
2. **数据路由** — `loader` / `action` 一体化, 跟 TanStack Query 配合好
3. **懒加载友好** — `lazy: () => import('./pages/PortfolioPage')`
4. **嵌套路由** — sidebar layout + 9 child routes 自然

**替代方案**:
- ❌ TanStack Router: 强类型路由是新, 但生态比 React Router 小, 学习成本高
- ❌ Next.js router: 需引入 Next.js, 跟 Vite 冲突
- ❌ 自写 hash router: 重复造轮子
- ✅ React Router 6: 平衡成熟度 + 现代 API

**Trade-off**: TanStack Router 类型更强, 但本项目 9 个页类型推断 React Router 已够。

**实现细节**:
- `npm install react-router-dom@^6.26.0`
- `frontend/src/router.tsx` 声明 9 个 sidebar 路由
- sidebar 入口 `NavLink`, active state 用 `aria-current="page"`

---

### Decision 8: 实时数据通信 = SSE (Server-Sent Events)

**问题**: 实时 K 线 / 分析进度 / 批量状态 推送协议? 选项: WebSocket / SSE / 轮询

**决策**: **SSE** (`text/event-stream`)

**理由**:
1. **已有现成实现** — `backend/api/sse.py` + `sse_starlette` 已经生产可用
2. **HTTP 兼容** — SSE 是单向 HTTP, 无需独立端口, 无需 ws upgrade
3. **自动重连** — 浏览器原生 `EventSource` 自动重连
4. **Nginx / 反代友好** — SSE 是 HTTP, 不需要 WebSocket 单独配
5. **够用** — 客户端只需要收 (进度推送 / K 线推送), 不需要主动发 (发走 POST)
6. **CORS 已验证** — v0.4.0 chart_panel SSE 集成已实测 `Access-Control-Allow-Origin` OK

**替代方案**:
- ❌ WebSocket: 双向, 但本项目不需要客户端主动发 (发的走 POST), 杀鸡用牛刀
- ❌ 轮询: 30s 轮询分析进度 = 浪费, SSE 推送秒到
- ✅ SSE: 单向 + HTTP + 自动重连 + 反代友好 + 已有现成后端

**Trade-off**: 单向限制 (如果以后要"客户端 push 命令"需升级到 WebSocket, 但本项目无此需求)。

**实现细节**:
- 后端: `backend/api/sse.py` 已有 `/api/analyze/{id}/stream`, 沿用
- 前端: `new EventSource('/api/analyze/{id}/stream')`, 封装 `useAnalysisStream(id)` hook
- K 线实时: `new EventSource('https://push2his.eastmoney.com/api/qt/stock/trends2/sse?secid=...')` (浏览器直连, v0.4.0 已验证)
- 批量进度: SSE `/api/batch/{id}/stream` (backend/api/batch.py 已有)

---

### Decision 9: 测试 = Vitest + React Testing Library + Playwright

**问题**: React 测试栈? 选项: Jest + RTL / Vitest + RTL / Vitest + Playwright / Cypress

**决策**: **Vitest + React Testing Library + Playwright**

**理由**:
1. **Vitest** — Vite 原生, HMR 同款, 比 Jest 快 5-10x, TS 支持开箱
2. **React Testing Library** — 测试用户视角 (按钮 / 表单), 不测实现细节
3. **Playwright** — e2e 业界事实标准, 比 Cypress 多浏览器 + 多语言, TS 推断好

**替代方案**:
- ❌ Jest: 慢, 配置烦, Vite 用户没必要
- ❌ Cypress: 单浏览器 (Chromium) 起家, 现在支持多但 Playwright 仍胜
- ❌ Storybook + Chromatic: 视觉回归好, 但本项目不需要视觉回归 (样式测试不抓像素)
- ✅ Vitest + RTL + Playwright: 现代 + 快 + 业界标准

**Trade-off**: Playwright 调试比 Cypress 略复杂, 但多浏览器值得。

**实现细节**:
- `npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom`
- `npm install -D @playwright/test playwright`
- `frontend/vitest.config.ts` 配置 jsdom + setup
- `frontend/playwright.config.ts` 配置 baseURL = http://localhost:5173
- CI: `vitest run && playwright test`

---

### Decision 10: 暗色主题 = 沿用 `--bb-*` CSS 变量

**问题**: 暗色 Bloomberg 风怎么实现? 选项: CSS variables / Tailwind theme / CSS-in-JS / 全 CSS module

**决策**: **CSS variables + Tailwind theme 桥接**

**理由**:
1. **复用现有 token** — `web/styles/tokens.css` 已经定义 `--bb-accent / --bb-up / --bb-down / --bg-elevated / --bg-surface`, 直接移植
2. **Tailwind 兼容** — `tailwind.config.ts` 用 `colors: { bb: { accent: 'var(--bb-accent)', up: 'var(--bb-up)', ... } }` 桥接
3. **运行时切换** — 未来想加 light mode, 只改 CSS variables 不改组件
4. **shadcn/ui 兼容** — shadcn/ui 默认就是 CSS variables, 完美对齐

**替代方案**:
- ❌ Tailwind theme only: 不能运行时切换
- ❌ CSS-in-JS: bundle 重 + 跟 shadcn/ui 哲学冲突
- ❌ CSS modules: 不能跨组件共享 token
- ✅ CSS variables + Tailwind theme bridge: 业界最佳实践

**Trade-off**: CSS variables 在 IE 不支持, 但本项目目标浏览器 Chrome 90+, 无影响。

**实现细节**:
- `frontend/src/styles/tokens.css` (从 `web/styles/tokens.css` 移植 + 删除 streamlit-specific selector)
- `frontend/tailwind.config.ts` `colors.bb.{accent, up, down, ...}` 桥接
- shadcn/ui 默认变量 (`--background / --foreground / --primary`) 也指向 `--bb-*`

---

### Decision 11: 部署 = FastAPI static mount

**问题**: 怎么部署? 选项: 静态服务器 (nginx) + FastAPI 反代 / FastAPI 静态挂载 / Vercel / Docker

**决策**: **Vite build → FastAPI static mount**

**理由**:
1. **单进程** — 一个 `uvicorn backend.main:app` 跑全部 (API + 静态文件), 部署简单
2. **无 nginx** — 个人工具, 不需要反代
3. **CORS 同源** — `/api/*` 和 `/` 同源, 无 CORS 问题
4. **回退 SPA 路由** — `app.mount("/", StaticFiles(...))` + catch-all 路由到 `index.html`

**替代方案**:
- ❌ nginx + FastAPI: 个人工具过度, 2 个进程
- ❌ Vercel: 内部工具, 不上云
- ❌ Docker: Phase 3 后考虑, Phase 1-2 简单跑即可
- ✅ FastAPI static mount: 单进程, 简单

**Trade-off**: FastAPI 静态文件服务比 nginx 慢, 但 9 个页 bundle < 1MB, 无影响。

**实现细节**:
- `vite build` 输出到 `frontend/dist/`
- `backend/main.py` 增加:
  ```python
  from fastapi.staticfiles import StaticFiles
  app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")
  
  @app.get("/{full_path:path}")
  async def spa_fallback(full_path: str):
      return FileResponse("frontend/dist/index.html")
  ```
- 开发模式: `vite dev` (5173) + `uvicorn backend.main:app --reload` (8000), Vite proxy `/api` → 8000
- 生产模式: `vite build` + `uvicorn backend.main:app` (8000) 单端口

---

### Decision 12: 9 页迁移顺序 (Phase 2)

**问题**: 9 个 sidebar 按什么顺序迁? 选项: 按现有 sidebar 顺序 / 按难度易→难 / 按用户使用频率

**决策**: **按"易→难"**, 见 `proposal.md` Phase 2 表:

1. ⚙️ 设置 (Phase 1 已做) — 最简单, 表单 + 持久化
2. 📋 历史 — 列表 + 详情, 已有 `/api/history`
3. 📋 日志 — 列表 + 详情, 需新增 `/api/logs/*`
4. 📈 走势图 — K 线 + 实时, 已有 `/api/analyze` SSE 经验
5. 📈 板块轮动 — 单页 Markdown 渲染, 简单
6. 📊 批量分析 — 进度 + 状态, 已有 `/api/batch`
7. 💼 我的仓位 — 6 tabs, 最复杂
8. ⏰ 定时分析 — 3 个 sub-panel + cron 编辑
9. 📝 分析 — 主流程 + SSE 实时, 收尾

**理由**: 早迁简单的早暴露问题 (CORS / 数据格式 / SSE 兼容), 难的后迁有把握。

---

## 架构图 (Architecture)

### 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Browser (用户本机)                              │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  React SPA (Vite dev :5173 / built :8000 same-origin)            │   │
│  │                                                                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Sidebar  │  │  Router  │  │  Pages   │  │  Stores  │          │   │
│  │  │ 9 入口   │→ │ R-Router │→ │ 9 pages  │← │ Zustand  │          │   │
│  │  └──────────┘  └──────────┘  └────┬─────┘  └──────────┘          │   │
│  │                                    │                              │   │
│  │  ┌─────────────────────────────────┴────────────────────────┐   │   │
│  │  │         TanStack Query (server state cache)               │   │   │
│  │  └───────┬─────────────────────┬─────────────────────────────┘   │   │
│  │          │                     │                                  │   │
│  │  ┌───────▼──────┐    ┌────────▼─────────┐                       │   │
│  │  │ Lightweight   │    │  ECharts 6        │                       │   │
│  │  │ Charts v5     │    │  (饼/柱/折线)      │                       │   │
│  │  └───────────────┘    └──────────────────┘                       │   │
│  │                                                                   │   │
│  │  shadcn/ui (button/dialog/tabs/form/table/toast/...)              │   │
│  │  Tailwind + --bb-* CSS variables                                  │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │ HTTP (same-origin)
                               │ SSE  (text/event-stream)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             FastAPI :8000 (backend/main.py)                              │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  Existing routers (零修改)                                       │    │
│  │  /api/analyze  /api/batch  /api/batch/{id}/stream              │    │
│  │  /api/history  /api/sse  /api/progress  /api/result            │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  Phase 1-2 新增 routers                                           │    │
│  │  /api/settings (Phase 1)                                        │    │
│  │  /api/logs/*  /api/sector/*  /api/portfolio/*  /api/schedule/* │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  Phase 3 新增 (挂载静态)                                          │    │
│  │  app.mount("/assets", StaticFiles(...))                          │    │
│  │  @app.get("/{full_path:path}") → FileResponse("index.html")     │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  CORS: allow_origins=["*"] (开发); same-origin (生产)                   │
└──────────────────────────────┬───────────────────────────────────────────┘
                               │ Python call
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  Python 业务层 (零修改, Phase 1-3 全程)                  │
│                                                                          │
│  tradingagents/                                                          │
│    ├─ dataflows/a_stock.py  (10+ vendor: mootdx/腾讯/东财/...)          │
│    ├─ agents/  (7 analyst + Bull/Bear debate)                            │
│    └─ graph/  (LangGraph state machine)                                 │
│                                                                          │
│  cli/                                                                    │
│    └─ analyze / list_logs / portfolio / schedule / ...                   │
│                                                                          │
│  backend/core/                                                           │
│    ├─ job_queue.py  (423 行, 批量任务调度)                                │
│    ├─ scheduler.py  (889 行, cron + 多渠道通知)                          │
│    ├─ portfolio_store.py  (923 行, 单例 + RLock + JSON)                  │
│    ├─ portfolio_calc.py  (743 行, XIRR/Sharpe/MaxDD/Brinson)            │
│    ├─ log_store.py  (458 行, LogStore + LogWriter)                       │
│    ├─ history_store.py  (266 行, 分析历史)                               │
│    ├─ notifier.py  (396 行, 4 渠道通知)                                  │
│    └─ watchlist.py / tracker.py / portfolio_alerts.py / ...             │
│                                                                          │
│  持久化: ~/.tradingagents/                                                │
│    ├─ logs/{ticker}/{date}_run{NN}/ (stream chunks)                     │
│    ├─ history/  (分析历史)                                                │
│    ├─ portfolio/  (positions/transactions/alerts/audit)                  │
│    ├─ schedules/  (cron + runs)                                          │
│    ├─ watchlist/  (自选股)                                                │
│    └─ cache/  (kline / northbound)                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phase 1 数据流 (设置页)

```
User opens http://localhost:5173/settings
    ↓ React Router matches /settings → SettingsPage
    ↓ SettingsPage useQuery(['settings'], () => api.get('/api/settings'))
    ↓
GET http://localhost:8000/api/settings
    ↓ Vite dev proxy → http://localhost:8000/api/settings
    ↓
backend/api/settings.py (Phase 1 新增)
    ↓ 读 ~/.tradingagents/settings.json (新建)
    ↓ 或读环境变量 (LLM_PROVIDER / DEEP_THINK_LLM / ...)
    ↓ 返回 {provider, deepModel, quickModel, apiKey, baseUrl}
    ↓
React 渲染 Form (shadcn/ui Input/Select/Switch)
    ↓ User 修改 → onChange → useState
    ↓ User 点击 "保存" → useMutation
    ↓
POST http://localhost:8000/api/settings
    ↓ body: {provider: "minimax", deepModel: "MiniMax-M2.7", ...}
    ↓
backend/api/settings.py 写 ~/.tradingagents/settings.json + reload dotenv
    ↓ 返回 {ok: true, saved: {...}}
    ↓
React: queryClient.invalidateQueries(['settings']) + toast.success("设置已保存")
```

### Phase 2.4 数据流 (走势图)

```
User 打开 http://localhost:5173/chart?ticker=600519
    ↓ ChartPage useQuery(['kline', '600519', '1d'], () => api.get('/api/analyze/kline?symbol=600519&range=1d'))
    ↓
GET http://localhost:8000/api/analyze/kline?...
    ↓
backend/api/chart.py (Phase 2.4 新增, 或扩 analyze.py)
    ↓ tradingagents.dataflows.a_stock.get_stock_data('600519', '2024-01-01', '2024-12-31')
    ↓ 3-fallback: mootdx → sina → push2his
    ↓ 返回 [{date, open, high, low, close, volume}, ...]
    ↓
React: <LightweightKline data={ohlcv} /> 渲染
    ↓ 同时: new EventSource('https://push2his.eastmoney.com/api/qt/stock/trends2/sse?secid=1.600519')
    ↓ 浏览器直连 (CORS 已验证 v0.4.0), 实时推送最新 K 线
    ↓ LightweightKline.update(latestCandle)
```

### 并行运行 (Phase 1-2)

```
http://localhost:5173 (React SPA dev)       ← 用户主要使用
http://localhost:8000 (FastAPI)             ← React ↔ 后端
http://localhost:8501 (Streamlit)           ← fallback, 用户对比
http://localhost:8502 (Streamlit venv2)      ← 测试用 (可选)

三个端口都跑, 用户任选, 数据共享 ~/.tradingagents/
```

---

## 文件结构 (File Layout)

### 新增 `frontend/` 目录

```
frontend/
├── .gitignore                       # node_modules / dist / .env.local
├── .nvmrc                           # node 20.x
├── package.json                     # deps + scripts
├── package-lock.json
├── tsconfig.json                    # TS strict
├── tsconfig.node.json               # for vite.config.ts
├── vite.config.ts                   # Vite + plugin-react + proxy /api
├── tailwind.config.ts               # tailwind + shadcn theme + --bb-* bridge
├── postcss.config.js                # tailwind + autoprefixer
├── components.json                  # shadcn config
├── index.html                       # SPA 入口
├── env.d.ts                         # import.meta.env types
│
├── public/                          # 静态资源 (favicon 等)
│
├── src/
│   ├── main.tsx                     # React 18 createRoot + Providers
│   ├── App.tsx                      # Router + Sidebar layout
│   │
│   ├── styles/
│   │   ├── tokens.css               # 从 web/styles/tokens.css 移植
│   │   └── globals.css              # tailwind base + tokens import
│   │
│   ├── router.tsx                   # 9 sidebar routes
│   │
│   ├── components/
│   │   ├── ui/                      # shadcn copy-paste
│   │   │   ├── button.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── tabs.tsx
│   │   │   ├── form.tsx
│   │   │   ├── input.tsx
│   │   │   ├── select.tsx
│   │   │   ├── table.tsx
│   │   │   ├── toast.tsx
│   │   │   ├── dropdown-menu.tsx
│   │   │   ├── card.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── separator.tsx
│   │   │   ├── sheet.tsx
│   │   │   └── skeleton.tsx
│   │   │
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx          # 9 入口
│   │   │   ├── Header.tsx           # 顶部 logo + 版本
│   │   │   └── PageContainer.tsx    # 内容区
│   │   │
│   │   └── charts/
│   │       ├── LightweightKline.tsx # K 线封装
│   │       └── EChart.tsx           # ECharts 封装
│   │
│   ├── pages/
│   │   ├── Settings/                # ⚙️ 设置
│   │   │   ├── SettingsPage.tsx
│   │   │   ├── LLMConfigForm.tsx
│   │   │   └── index.ts
│   │   │
│   │   ├── History/                 # 📋 历史 (Phase 2.2)
│   │   ├── Logs/                    # 📋 日志 (Phase 2.3)
│   │   ├── Chart/                   # 📈 走势图 (Phase 2.4)
│   │   ├── Sector/                  # 📈 板块轮动 (Phase 2.5)
│   │   ├── Batch/                   # 📊 批量 (Phase 2.6)
│   │   ├── Portfolio/               # 💼 仓位 (Phase 2.7, 6 tabs)
│   │   │   ├── PortfolioPage.tsx
│   │   │   ├── OverviewTab.tsx
│   │   │   ├── TransactionsTab.tsx
│   │   │   ├── AllocationTab.tsx
│   │   │   ├── AlertsTab.tsx
│   │   │   ├── ImportExportTab.tsx
│   │   │   └── RiskReturnTab.tsx
│   │   ├── Schedule/                # ⏰ 定时 (Phase 2.8)
│   │   └── Analysis/                # 📝 分析 (Phase 2.9)
│   │
│   ├── api/
│   │   ├── client.ts                # fetch wrapper + TanStack Query keys
│   │   ├── settings.ts              # getSettings / saveSettings
│   │   ├── analyze.ts               # startAnalysis / getResult / stream
│   │   ├── batch.ts                 # createBatch / getBatch / stream
│   │   ├── history.ts               # listHistory / deleteHistory
│   │   ├── logs.ts                  # listLogs / getLogDetail
│   │   ├── sector.ts                # getSectorDigest
│   │   ├── portfolio.ts             # listPositions / addPosition / ...
│   │   ├── schedule.ts              # listSchedules / createSchedule / ...
│   │   └── chart.ts                 # getKline / getQuote
│   │
│   ├── stores/                      # Zustand
│   │   ├── usePortfolioStore.ts
│   │   ├── useScheduleStore.ts
│   │   ├── useAnalysisStore.ts
│   │   └── useUIStore.ts            # sidebar collapsed / theme
│   │
│   ├── hooks/
│   │   ├── useAnalysisStream.ts     # SSE 订阅分析进度
│   │   ├── useBatchJobStream.ts     # SSE 订阅批量任务
│   │   ├── useLogStream.ts          # SSE 订阅日志
│   │   └── useKlineRealtime.ts      # SSE 订阅 K 线实时
│   │
│   ├── lib/
│   │   ├── queryClient.ts           # TanStack Query client 配置
│   │   ├── format.ts                # 数字 / 日期 / 百分比格式化
│   │   ├── cn.ts                    # clsx + tailwind-merge
│   │   └── eventSource.ts           # EventSource wrapper (重连 + 错误处理)
│   │
│   └── types/
│       ├── api.ts                   # request/response 类型
│       ├── domain.ts                # Position / Transaction / Schedule / ...
│       └── env.d.ts
│
├── tests/
│   ├── setup.ts                     # vitest + RTL setup
│   ├── unit/
│   │   ├── SettingsPage.test.tsx
│   │   ├── HistoryPage.test.tsx
│   │   ├── ...
│   │   └── stores/*.test.ts
│   │
│   └── e2e/
│       ├── settings.spec.ts
│       ├── history.spec.ts
│       ├── chart.spec.ts
│       ├── ...
│       └── fixtures/
│           └── auth.ts              # (no-op, 个人工具无 auth)
│
└── README.md                        # 开发命令 + Phase 进度
```

### 后端扩展 `backend/api/` 新增文件

```
backend/api/
├── __init__.py                      # 注册新 router (Phase 1 改)
├── analyze.py                       # 已有, 可能扩 chart 端点
├── batch.py                         # 已有, 不动
├── batch_helpers.py                 # 已有, 不动
├── history.py                       # 已有, 不动
├── sse.py                           # 已有, 不动
├── progress.py                      # 已有, 不动
├── result.py                        # 已有, 不动
├── settings.py                      # Phase 1 新增: GET / POST /api/settings
├── logs.py                          # Phase 2.3 新增: GET /api/logs/* 
├── sector.py                        # Phase 2.5 新增: GET /api/sector/digest
├── portfolio.py                     # Phase 2.7 新增: ~12 endpoints
├── schedule.py                      # Phase 2.8 新增: ~8 endpoints
└── chart.py                         # Phase 2.4 新增: GET /api/analyze/kline
```

### `docs/architecture/` 新增

```
docs/architecture/
├── react-spa.md                     # 总体架构 + 迁移进度
├── frontend-layout.md               # 9 sidebar + 路由 + 状态
├── backend-api.md                   # FastAPI endpoints 列表
├── realtime-sse.md                  # SSE 协议 + K 线实时
└── phase3-deletion-checklist.md     # Phase 3 删除清单 (从本 spec 提)
```

---

## API 设计 (FastAPI Endpoints)

### 现有 (Phase 1-2 一行不动)

| Method | Path | 用途 | 模块 |
|---|---|---|---|
| GET | `/api/health` | 健康检查 | `backend/main.py` |
| POST | `/api/analyze` | 启动单笔分析 | `backend/api/analyze.py` |
| GET | `/api/analyze/{id}` | 获取分析结果 | `backend/api/result.py` |
| GET | `/api/analyze/{id}/progress` | 获取进度 (polling) | `backend/api/progress.py` |
| GET | `/api/analyze/{id}/stream` | SSE 实时进度推送 | `backend/api/sse.py` |
| POST | `/api/batch` | 创建批量任务 | `backend/api/batch.py` |
| GET | `/api/batch/{id}` | 获取批量状态 | `backend/api/batch.py` |
| GET | `/api/batch/{id}/summary` | 批量汇总 | `backend/api/batch.py` |
| GET | `/api/batch/{id}/stream` | SSE 批量进度推送 | `backend/api/batch.py` |
| POST | `/api/batch/{id}/cancel` | 取消批量 | `backend/api/batch.py` |
| GET | `/api/jobs` | 列出所有 jobs | `backend/api/batch.py` |
| POST | `/api/jobs/{id}/retry` | 重试失败 job | `backend/api/batch.py` |
| GET | `/api/history` | 列出历史 | `backend/api/history.py` |
| DELETE | `/api/history/{id}` | 删除历史 | `backend/api/history.py` |

### Phase 1 新增 (Settings)

| Method | Path | Payload | Response | 说明 |
|---|---|---|---|---|
| GET | `/api/settings` | — | `{provider, deepModel, quickModel, apiKey, baseUrl}` | 读 ~/.tradingagents/settings.json + 环境变量 fallback |
| POST | `/api/settings` | `{provider?, deepModel?, quickModel?, apiKey?, baseUrl?}` | `{ok: true, saved: {...}}` | 写 settings.json + 重新 load .env |

### Phase 2 新增 (按页)

#### Phase 2.3 Logs (3 endpoints)

| Method | Path | Payload | Response |
|---|---|---|---|
| GET | `/api/logs` | query: `?ticker=&date=&page=&size=` | `[{ticker, date, runId, summary, ...}]` |
| GET | `/api/logs/{ticker}/{date}/{runId}` | — | `{meta, chunks: [...]}` |
| GET | `/api/logs/{ticker}/{date}/{runId}/stream` | — | SSE 实时日志推送 |

#### Phase 2.4 Chart (2 endpoints)

| Method | Path | Payload | Response |
|---|---|---|---|
| GET | `/api/analyze/kline` | query: `?symbol=&range=&start=&end=` | `[{date, open, high, low, close, volume}, ...]` |
| GET | `/api/analyze/quote` | query: `?symbol=` | `{symbol, name, price, change, changePct, ...}` |

> K 线实时推送: 浏览器直连 push2his (CORS 已验证), 不走后端

#### Phase 2.5 Sector (1 endpoint)

| Method | Path | Payload | Response |
|---|---|---|---|
| GET | `/api/sector/digest` | query: `?date=&topN=` | `{digest: "Markdown text", topStocks: [...], hotConcepts: [...]}` |

#### Phase 2.6 Batch (沿用现有, Phase 2 加 GET 列表)

#### Phase 2.7 Portfolio (~15 endpoints)

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/portfolio/positions` | 列出持仓 |
| POST | `/api/portfolio/positions` | 新增持仓 |
| PUT | `/api/portfolio/positions/{id}` | 修改持仓 |
| DELETE | `/api/portfolio/positions/{id}` | 删除持仓 |
| GET | `/api/portfolio/transactions` | 列出流水 |
| POST | `/api/portfolio/transactions` | 新增流水 |
| PUT | `/api/portfolio/transactions/{id}` | 修改流水 |
| DELETE | `/api/portfolio/transactions/{id}` | 删除流水 |
| GET | `/api/portfolio/alerts` | 列出预警 |
| POST | `/api/portfolio/alerts` | 新增预警 |
| PUT | `/api/portfolio/alerts/{id}` | 修改预警 |
| DELETE | `/api/portfolio/alerts/{id}` | 删除预警 |
| GET | `/api/portfolio/summary` | 汇总指标 (XIRR / Sharpe / MaxDD) |
| GET | `/api/portfolio/allocation` | 配置分析 (行业/板块/大类) |
| POST | `/api/portfolio/import` | CSV 导入 |
| GET | `/api/portfolio/export` | CSV 导出 |
| GET | `/api/portfolio/brinson` | Brinson 业绩归因 |

#### Phase 2.8 Schedule (~8 endpoints)

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/schedule/list` | 列出所有 schedule |
| POST | `/api/schedule/create` | 新建 schedule |
| PUT | `/api/schedule/{id}` | 修改 schedule |
| DELETE | `/api/schedule/{id}` | 删除 schedule |
| POST | `/api/schedule/{id}/toggle` | 启用/暂停 |
| GET | `/api/schedule/{id}/runs` | 运行历史 |
| POST | `/api/schedule/{id}/run-now` | 立即运行 |
| GET | `/api/schedule/tickers` | 可用 ticker 源 (portfolio / watchlist / manual) |

### 总计 endpoints (Phase 3 完成)

- 现有: 13
- Phase 1 新增: 2
- Phase 2 新增: ~30
- **总计**: ~45 endpoints

---

## 实时通信协议 (SSE)

### 为什么 SSE 不是 WebSocket

| 维度 | SSE | WebSocket |
|---|---|---|
| 协议 | HTTP (单向) | ws upgrade (双向) |
| 反代 | nginx 默认 OK | 需特殊配置 |
| 自动重连 | 浏览器原生 | 需自己实现 |
| 浏览器 API | `EventSource` | `WebSocket` |
| 客户端发 | 走 POST | 原生 send |
| 本项目需求 | ✅ 只需收 | ❌ 客户端不需发 |

### SSE 端点列表

```
GET /api/analyze/{id}/stream       # 分析进度 (已有)
GET /api/batch/{id}/stream         # 批量任务进度 (已有)
GET /api/logs/{ticker}/{date}/{runId}/stream  # 日志实时 (Phase 2.3 新增)
```

### SSE EventSource 封装 (前端)

```typescript
// frontend/src/lib/eventSource.ts
export function createAnalysisStream(id: string, onEvent: (data: any) => void): () => void {
  const es = new EventSource(`/api/analyze/${id}/stream`);
  es.addEventListener('progress', (e) => onEvent(JSON.parse(e.data)));
  es.addEventListener('complete', (e) => { onEvent({type: 'complete', ...JSON.parse(e.data)}); es.close(); });
  es.addEventListener('error', (e) => { onEvent({type: 'error', error: e}); });
  return () => es.close();
}
```

### K 线实时 (不走后端)

```typescript
// 浏览器直连 push2his (CORS 已验证)
const es = new EventSource(
  `https://push2his.eastmoney.com/api/qt/stock/trends2/sse?secid=1.${ticker}`
);
es.addEventListener('data', (e) => {
  const candle = parsePush2hisData(e.data);
  chart.update(candle); // Lightweight Charts update
});
```

---

## Phase 拆分详细策略

### Parity Check Strategy (跨章节总结, 详见 `parity-check.md`)

> 本节是 parity-check.md 的精简版, 让 reviewer 在 design.md 里就能看到核心思路。完整 per-page 校验清单 (~1500 行) 见 [`parity-check.md`](./parity-check.md)。

#### 为什么需要 Parity Check

Phase 2 迁移 9 个 sidebar 页, 默认假设"React 重写能跑就行"。但**真正的质量门槛**是"用户切到 React 后, 能不能完成跟 Streamlit 一样的操作, 拿到一样的结果"。这需要 5 维度系统校验:

1. **功能等价** — 每个 button / form / dialog 都覆盖 (100%)
2. **数据等价** — React 拉到的 md5sum == Streamlit 拉到的 md5sum (100%)
3. **视觉等价** — 同 ticker + 同日期截图 diff < 1% (≤ 0.5% 容忍)
4. **性能等价** — React ≤ 2× Streamlit 实际值 (不能慢一倍以上)
5. **错误等价** — API key 无效 / ticker 不存在等, React 报错信息 100% 跟 Streamlit 等价

#### Parity 维度与工具映射

| 维度 | 工具 | 触发时机 | 通过标准 |
|---|---|---|---|
| 功能 | Playwright e2e (`frontend/tests/e2e/{page}.spec.ts`) | 每页 Phase 2.X 完 | 0 失败 + 用户手动确认 |
| 数据 | `scripts/parity_check.py` (hash md5sum 对比) | 每页 + Phase 2.10 整体 | hash 全等 |
| UI | `scripts/parity_visual.py` (Playwright 截图 + ImageMagick compare) | 每页 + Phase 2.10 整体 | AE < 1% 像素 |
| 性能 | `scripts/parity_perf.py` (Lighthouse) + 手量 | 每页 + Phase 2.10 整体 | Lighthouse ≥ 80, React ≤ 2× Streamlit |
| 错误 | `scripts/parity_fault_inject.py` (10 错误场景 fault injection) | 每页 + Phase 2.10 整体 | 错误文案 100% 1:1 |

#### Phase 2 每页流程 (5 步, parity-check.md § 5.1)

```
1. Patch    写代码 (frontend + backend) + 写 e2e + commit
2. Verify   跑 5 维度校验
              ├─ npx playwright test <page>.spec.ts
              ├─ python scripts/parity_check.py --page <page>
              ├─ python scripts/parity_visual.py --page <page>
              ├─ python scripts/parity_perf.py --page <page>
              └─ python scripts/parity_fault_inject.py --page <page>
3. User     用户切 React / Streamlit 对比, 文字回复 "✅ parity 通过"
4. Record   写 parity-results/{page}-diff.md (失败 / 例外 diff 全部记录)
5. Next     5 步全绿 → 该页计入完成 → 进下一页
```

任一 ❌ → 该页任务**不算完成**, 不进 Phase 2 下一项, 不进 Phase 3。

#### Phase 2.10 整体 Parity Check (parity-check.md § 5.2)

9 页全部 ✅ 后, 跑一次跨页一致性校验:

```bash
# 跨页串行
npx playwright test                                            # 全部 9 spec 通过
python scripts/parity_check.py                                  # 全 9 页 hash 对比
python scripts/parity_visual.py                                 # 全 9 页截图 diff
python scripts/parity_perf.py                                   # 全 9 页 Lighthouse
python scripts/parity_fault_inject.py                           # 10 错误场景
pytest tests/ -q                                                # 757 passed
# 7 天 Streamlit fallback 无关键问题
# 用户全 9 页手动验证 (用户截图 / 录屏 / 文字确认)
```

#### 失败处理 (parity-check.md § 6)

- **任一 parity 维度 fail** → 不能进 Phase 3
- **个别 parity 维度可允许 0.5% 容忍**, 但功能 / 数据 / 错误**必须 100% 一致**
- **若功能无法 1:1** (因 React/state 架构不同), spec 需明确:
  - "diff 原因 + 用户确认接受" 写到 `parity-results/{page}-diff.md`
  - 用户明确回复 "✅ 接受此 diff" → 该 diff 例外, 其他维度仍要求 1:1

#### 硬约束 (跟 `.openspec.yaml` 一致)

- ❌ "React 实现不了 X, 删 X" (除非用户明确接受)
- ❌ "数据字段多/少几个, 没问题"
- ❌ "Streamlit 旧, React 用现代风更好"
- ❌ "性能差一点, 感知不到"
- ❌ "报错文案改一下更友好"

#### Parity Check Tooling 实现位置

| 脚本 | 行数估计 | 实现时机 |
|---|---|---|
| `scripts/parity_check.py` | ~200 | Phase 1 末尾 (基础 hash 工具) |
| `scripts/parity_visual.py` | ~150 | Phase 1.5 (需 Playwright + ImageMagick) |
| `scripts/parity_perf.py` | ~50 | Phase 1.5 (需 lighthouse CLI) |
| `scripts/parity_fault_inject.py` | ~100 | Phase 2.2 (需要至少 1 页迁移完才能对照) |
| `parity-results/{page}-diff.md` | per page | Phase 2.X 同步生成 |

详见 [`parity-check.md`](./parity-check.md)。

---

### Phase 1: 骨架 + 设置页 (3-5 天)

#### 目标

- `frontend/` 完整 Vite 项目
- 9 个 sidebar 占位 + 路由 + 主题
- 设计 token 移植
- Tailwind + shadcn/ui init
- ⚙️ 设置页端到端跑通
- `/api/settings` GET/POST
- 三端口并行不冲突
- Streamlit 无回归 (757 passed)

#### 详细步骤

1. **Vite init**: `npm create vite@latest frontend -- --template react-ts`
2. **依赖安装**: react 18.3 / vite 5 / tailwind 3 / shadcn-ui / zustand / @tanstack/react-query / react-router-dom 6
3. **shadcn init**: `npx shadcn-ui@latest init`, 选 TypeScript + Tailwind + CSS variables
4. **首批组件**: button / dialog / tabs / form / input / select / toast / card
5. **路由**: `frontend/src/router.tsx` 9 个 sidebar route, 全部 lazy + placeholder
6. **Sidebar**: 9 入口 + shadcn `Button` + React Router `NavLink`
7. **Design tokens**: 从 `web/styles/tokens.css` 移植 (去掉 streamlit-specific selector), 桥接到 Tailwind theme
8. **backend/api/settings.py**: 读 `~/.tradingagents/settings.json` (新建) + 环境变量 fallback
9. **frontend/src/pages/Settings/SettingsPage.tsx**: shadcn `Form` + `Input` + `Select`, useQuery + useMutation
10. **Vitest init**: `npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom`
11. **Playwright init**: `npm install -D @playwright/test && npx playwright install chromium`
12. **第一个 e2e**: settings.spec.ts — 打开 /settings, 修改 LLM provider, 保存, 刷新, 验证持久化
13. **README**: 三端口启动命令
14. **commit**: `feat(react): phase 1 — skeleton + settings page (React SPA 脚手架)`

#### 验收 (Phase 1 Done)

```bash
# Terminal 1: Vite dev
cd frontend && npm run dev
# → http://localhost:5173 (React SPA)

# Terminal 2: FastAPI
python -m backend.main
# → http://localhost:8000/docs (FastAPI)

# Terminal 3: Streamlit (验证无回归)
python -m streamlit run web/app.py
# → http://localhost:8501 (Streamlit fallback)

# Terminal 4: pytest (验证 757 passed)
pytest tests/ -q
# → 757 passed
```

- [ ] 三端口并行 OK
- [ ] React 设置页能保存 LLM 配置 → FastAPI 落盘 → 刷新后 GET 返回新值
- [ ] Streamlit 设置仍能用 (无回归)
- [ ] Vitest 至少 3 测试 (SettingsPage + formatters + cn)
- [ ] Playwright settings.spec.ts 通过
- [ ] pytest 757 全绿

---

### Phase 2: 逐页迁移 (2-3 周)

详见 `tasks.md` Phase 2 (30 checkbox, 每页 3-5 个)。

#### Parity Gate (每页强制 5 步, parity-check.md § 5.1)

> **每页完成 ≠ 代码 commit 完成, 而是 parity 5 步全绿完成。**

```
Step 1: Patch        写代码 + 写 e2e + commit
Step 2: Verify       跑 5 维度校验 (e2e + hash + 截图 + Lighthouse + fault injection)
Step 3: User         用户手动切 React / Streamlit 对比, 文字回复 "✅ parity 通过"
Step 4: Record       写 parity-results/{page}-diff.md
Step 5: Next         全绿 → 进下一页
```

任一 ❌ → 该页任务**不算完成**, 不进 Phase 2 下一项, 不进 Phase 3。详见 [`parity-check.md`](./parity-check.md) § 4-6。

#### 每页标准流程

```
1. Backend: backend/api/{page}.py 新增 endpoints (估算行数 + 参考 tests/)
2. Frontend: frontend/src/pages/{Page}/{Page}Page.tsx 新增页
3. Components: 按需新增 shadcn 组件 (例如 Portfolio 需要 Table + Sheet + Calendar)
4. State: 必要时新增 Zustand store
5. Hooks: 必要时新增 SSE subscription hook
6. Unit: frontend/tests/unit/{Page}Page.test.tsx (3-5 测试)
7. E2E: frontend/tests/e2e/{page}.spec.ts (3-5 场景)
8. Verify: 三端口并行, React 端到端跑通, Streamlit 对应 panel 无回归
9. **Parity Gate (新增):** 跑 parity-check.md § 5.1 的 5 步 (patch + verify + 用户确认), 全绿才计入完成
10. Commit: feat(react): phase 2.X — {Page} page (单页 commit)
```

#### Phase 2.7 Portfolio 特殊说明

最复杂的页 (6 tabs + 4 dialogs + 业绩归因), 必须拆 sub-tasks:

- 2.7.1: 总览 Tab (OverviewTab.tsx + 汇总指标 endpoint)
- 2.7.2: 流水 Tab (TransactionsTab.tsx + CRUD endpoints)
- 2.7.3: 配置 Tab (AllocationTab.tsx + 行业/板块/大类 endpoint)
- 2.7.4: 预警 Tab (AlertsTab.tsx + 7 规则 endpoint)
- 2.7.5: 导入导出 Tab (ImportExportTab.tsx + 4 CSV 格式 endpoint)
- 2.7.6: 收益风险 Tab (RiskReturnTab.tsx + XIRR/Sharpe/MaxDD/Brinson endpoint)

每个 sub-task 单独 commit。

---

### Phase 3: 删 Streamlit 渲染代码 (1 天, **触发后才执行**)

#### Phase 3 触发条件 (硬约束, 必须全部满足)

> 详见 `proposal.md` 第 4 节。这里再列一次, 写明"未满足任一条件 → 不删":

| # | 条件 | 验证方式 | 满足? |
|---|---|---|---|
| 1 | React SPA 全部 9 个 sidebar 页跑通 | `cd frontend && npm run build` 成功 + 9 个 e2e 全绿 | ☐ |
| 2 | **每页 parity-check.md § 4 详细 checklist 全部通过 (5 维度)** | `parity-results/{page}-diff.md` 全绿 + 用户文字确认 | ☐ |
| 3 | **Phase 2.10 整体 parity check 9 页串行通过** (parity-check.md § 5.2) | 全 9 页 parity_check.py + parity_visual.py + parity_perf.py + parity_fault_inject.py 全绿 | ☐ |
| 4 | Playwright e2e 0 失败 | `cd frontend && npx playwright test` 退出码 0 | ☐ |
| 5 | 用户手动跑一遍全部 9 个页 (用户截图/录屏/文字确认) | 用户回复 "✅ 全部 9 页跑过, OK" | ☐ |
| 6 | pytest 757 passed (0 回归) | `pytest tests/ -q` 输出 "757 passed" | ☐ |
| 7 | Streamlit fallback 端口运行 ≥ 7 天**无关键问题** | 日志监控 + 用户反馈 | ☐ |
| 8 | 用户明确下令: "现在可以删 streamlit 代码" | 用户消息 | ☐ |

**未满足任一条件 → 不进入 Phase 3**。任何时候用户没明确下令前, 都并行运行 streamlit + React。

#### Phase 3 删除清单 (详细 checklist)

> 用户原话: *"重构完成后我要你删除现在所有 python 渲染的所有代码"*

**A. 必须删除 — Streamlit 渲染代码**

| 文件 | 行数 | 类型 | 验证 |
|---|---|---|---|
| `web/app.py` | 447 | Streamlit 主入口 | Phase 3 后 `streamlit run` 报 "no such file" |
| `web/components/batch_panel.py` | 447 | 批量分析 | — |
| `web/components/chart_panel.py` | 356 | 走势图 | — |
| `web/components/history_panel.py` | 245 | 历史 | — |
| `web/components/logs_panel.py` | 178 | 日志 | — |
| `web/components/portfolio_accounts.py` | 235 | 仓位账户 | — |
| `web/components/portfolio_alerts_view.py` | 173 | 仓位预警 | — |
| `web/components/portfolio_allocation.py` | 219 | 仓位配置 | — |
| `web/components/portfolio_dialogs.py` | 704 | 仓位 dialog | — |
| `web/components/portfolio_import_view.py` | 243 | 仓位导入 | — |
| `web/components/portfolio_overview.py` | 256 | 仓位总览 | — |
| `web/components/portfolio_panel.py` | 184 | 仓位主入口 | — |
| `web/components/portfolio_risk.py` | 250 | 仓位风险 | — |
| `web/components/portfolio_transactions.py` | 157 | 仓位流水 | — |
| `web/components/progress_panel.py` | 97 | 进度 | — |
| `web/components/report_viewer.py` | 145 | 报告查看 | — |
| `web/components/schedule_dialogs.py` | 369 | 定时 dialog | — |
| `web/components/schedule_panel.py` | 355 | 定时 | — |
| `web/components/sector_panel.py` | 384 | 板块轮动 | — |
| `web/components/settings_panel.py` | 151 | 设置 | — |
| `web/components/sidebar.py` | 213 | 侧边栏 | — |
| `web/components/__init__.py` | 0 | (空文件) | — |
| `web/styles.py` | 797 | Streamlit 样式加载 | — |
| `web/styles/elements.css` | 1393 | Streamlit-specific CSS | — |
| `web/styles/components.css` | TBD | 推测 streamlit-only | Phase 3 前确认 |
| `web/styles/base.css` | TBD | 推测 streamlit-only | Phase 3 前确认 |
| `web/progress.py` | 97 | Streamlit ProgressTracker | — |
| `web/nav.py` | 130 | Streamlit 导航 | — |
| `web/launch.py` | 25 | Streamlit 启动器 | — |
| **小计 (29 文件)** | **~7949 行** | | |

**B. 必须删除 — Streamlit 相关测试**

| 文件 | 行数 | 类型 |
|---|---|---|
| `tests/test_web_app_dispatch.py` | 244 | Streamlit 调度 |
| `tests/test_running_view_refresh.py` | 122 | Streamlit rerun 测试 |
| `tests/test_chart_panel.py` | 271 | chart_panel mock |
| `tests/test_chart_panel_quote.py` | 97 | chart_panel quote mock |
| `tests/test_logs_panel.py` | 103 | logs_panel mock |
| `tests/test_portfolio_panel.py` | 842 | portfolio_panel mock |
| `tests/test_web_runner.py` | TBD | 验证后删除 (可能含非 UI 测试) |
| **小计 (~7-8 文件)** | **~1679+ 行** | |

**C. 必须删除 — Streamlit 依赖**

`pyproject.toml` 移除:
```diff
- "streamlit>=1.45.0",
```

**D. 必须验证 — 数据 0 影响**

```bash
# Phase 3 前
ls ~/.tradingagents/
# logs/  history/  portfolio/  schedules/  watchlist/  cache/

# Phase 3 后 (不能动)
ls ~/.tradingagents/
# (同上, 一字不动)
```

**E. 保留 (Phase 3 不删, 后续评估)**

| 文件 | 行数 | 处理 |
|---|---|---|
| `web/runner.py` | 301 | 含业务逻辑, Phase 3 后评估: 可保留作 backend wrapper 或删除 |
| `web/pdf_export.py` | 410 | PDF 导出, Phase 3 后评估: 迁移到 backend/core/pdf_export.py 或删除 |
| `web/history.py` | 69 | 历史辅助, Phase 3 后评估 |
| `web/_signal_helpers.py` | 27 | 信号辅助, Phase 3 后评估 |
| `web/static/` | (dir) | 静态资源, Phase 3 后清理 |

> 这 5 个文件不是删除清单**必须**项, 但 Phase 3 触发后建议清理。详见 `tasks.md` Phase 3.5。

#### Phase 3 执行流程

```bash
# 1. 备份 (git branch)
git checkout -b phase-3-streamlit-removal
git tag v0.7.0-pre-phase3

# 2. 删 web/
git rm -r web/

# 3. 删 streamlit 测试
git rm tests/test_web_app_dispatch.py \
       tests/test_running_view_refresh.py \
       tests/test_chart_panel.py \
       tests/test_chart_panel_quote.py \
       tests/test_logs_panel.py \
       tests/test_portfolio_panel.py \
       tests/test_web_runner.py

# 4. 改 pyproject.toml
# 手动: 删除 "streamlit>=1.45.0",

# 5. 跑 pytest (验证业务测试 0 回归, 应 ≈ 600-650)
pytest tests/ -q

# 6. 跑前端 build
cd frontend && npm run build && cd ..

# 7. 跑 Playwright e2e (验证 React 端到端 OK)
cd frontend && npx playwright test && cd ..

# 8. 验证 streamlit 找不到
python -m streamlit run web/app.py
# 应报错: "No module named streamlit" 或 "web/app.py not found"

# 9. commit
git add -A
git commit -m "refactor: phase 3 — delete streamlit rendering code"

# 10. tag
git tag v0.7.0

# 11. CHANGELOG / CLAUDE.md / README 更新 (单 commit)
git commit -m "docs: v0.7.0 release notes"
```

#### Phase 3 验收

- [ ] `web/` 目录不存在 (`ls web/` → No such file or directory)
- [ ] `pytest tests/` 全绿 (业务测试, 数量 ≈ 600-650, 因 ~1679 行 UI mock 测试删了)
- [ ] `python -m streamlit run` 报 "No module named streamlit"
- [ ] `pyproject.toml` 无 streamlit
- [ ] React SPA `npm run build` 成功
- [ ] React SPA `npm run preview` 全 9 页 e2e 通过
- [ ] `tradingagents-web` console_script 报错 (因依赖 streamlit)
- [ ] `~/.tradingagents/` 数据完整, 一字不动
- [ ] `git tag v0.7.0` 标记发布

---

## 测试策略 (Testing)

### Python 测试 (零回归底线)

```bash
pytest tests/ -q
# 当前 v0.6.2: 757 passed

# Phase 1-2 期间: 必须保持 757 passed
# Phase 3 后: 应 ≈ 600-650 passed (Streamlit mock 测试 ~1579 行删了)
```

- 不删任何 pytest 用例 (Phase 3 触发条件之一就是 757 passed)
- Phase 3 才删 Streamlit 相关测试

### React 单元测试 (Vitest + RTL)

```bash
cd frontend && npx vitest run
```

覆盖:
- `SettingsPage.test.tsx` — form 渲染 / 提交 / 错误处理
- `HistoryPage.test.tsx` — 列表渲染 / 详情切换
- `LightweightKline.test.tsx` — 数据更新 / crosshair 事件
- `EChart.test.tsx` — option 变化重渲染
- `usePortfolioStore.test.ts` — Zustand store 行为
- `eventSource.test.ts` — EventSource wrapper 重连逻辑
- `format.test.ts` — 数字 / 日期 / 百分比格式化

### E2E (Playwright)

```bash
cd frontend && npx playwright test
```

9 个 spec (每页一个):

| Spec | 场景 |
|---|---|
| `settings.spec.ts` | 改 LLM 配置 → 保存 → 刷新 → 持久化验证 |
| `history.spec.ts` | 列出历史 → 打开详情 → 删除 |
| `logs.spec.ts` | 列 ticker → 选 date → 展开 chunk |
| `chart.spec.ts` | 输入 ticker → 切换 range → K 线渲染 |
| `sector.spec.ts` | 加载日报 → 切日期 → 显示 Top N |
| `batch.spec.ts` | 上传 ticker 列表 → 启动 → 看进度 → 看汇总 |
| `portfolio.spec.ts` | 加持仓 → 加流水 → 看汇总 → 设预警 → 看导入 |
| `schedule.spec.ts` | 建 schedule → 启停 → 跑历史 → 立即跑 |
| `analysis.spec.ts` | 输 ticker + date → 启动 → 看 SSE 进度 → 看报告 |

### 测试覆盖目标

- 业务逻辑 (Python): ≥ 80% (现有)
- React 单元: ≥ 60% (适度, 不强求 80%)
- E2E: 9 页各 3-5 场景 = 30-45 场景

---

## 部署策略 (Deployment)

### 开发模式 (Phase 1-2)

```bash
# 3 个 terminal
cd frontend && npm run dev               # Vite :5173
python -m backend.main                   # FastAPI :8000
python -m streamlit run web/app.py       # Streamlit :8501 (fallback)
```

或一键脚本 `scripts/dev.sh`:
```bash
#!/bin/bash
cd "$(dirname "$0")/.."
trap 'kill 0' SIGINT
(cd frontend && npm run dev) &
python -m backend.main &
python -m streamlit run web/app.py &
wait
```

### 生产模式 (Phase 3+)

```bash
# 1. 构建前端
cd frontend && npm run build
# → frontend/dist/

# 2. 启动 FastAPI (单端口 :8000 同时 serve API + SPA)
python -m backend.main
# → http://localhost:8000 (React SPA + API)
```

#### backend/main.py 静态挂载 (Phase 3)

```python
# backend/main.py (Phase 3 改动)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _DIST.exists():
    # 静态资源 (JS / CSS / assets)
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")
    
    # favicon
    @app.get("/favicon.ico")
    async def favicon():
        return FileResponse(_DIST / "favicon.ico")
    
    # SPA fallback (所有非 /api 路由 → index.html)
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(_DIST / "index.html")
```

### Phase 1-2 期间部署

Phase 1-2 不部署, 仅本地开发。Phase 3 才考虑部署。

---

## 不修改的硬约束 (Hard Constraints)

### 1. Python 业务代码 0 行修改

| 目录 | 行数估计 | 处理 |
|---|---|---|
| `tradingagents/` | ~8000 | **0 修改** |
| `cli/` | ~500 | **0 修改** |
| `backend/core/` | ~6100 | **0 修改** |
| `backend/api/batch.py + batch_helpers.py + analyze.py + sse.py + progress.py + result.py + history.py` | ~1060 | **0 修改** |

### 2. Streamlit 渲染代码 Phase 3 才删

| 目录 | 行数估计 | 处理 |
|---|---|---|
| `web/app.py` | 447 | Phase 1-2 保留, Phase 3 删 |
| `web/components/*.py` (21 文件) | ~5665 | Phase 1-2 保留, Phase 3 删 |
| `web/styles/elements.css` | 1393 | Phase 1-2 保留, Phase 3 删 |
| `web/progress.py` | 97 | Phase 1-2 保留, Phase 3 删 |

### 3. 现有 Python 测试 0 回归

```bash
pytest tests/ -q
# v0.6.2: 757 passed
# Phase 1-2: 必须 757 passed
# Phase 3 触发条件之一: 必须 757 passed
# Phase 3 后: ≈ 600-650 passed (Streamlit mock 测试 ~1679 行删了)
```

### 4. pyproject.toml Phase 3 才改

```diff
# Phase 1-2: 不动
# Phase 3: 删除 "streamlit>=1.45.0",
```

### 5. 数据格式 0 改变

```bash
~/.tradingagents/
├─ logs/         # 不动
├─ history/      # 不动
├─ portfolio/    # 不动 (positions.json / transactions.json / alerts.json / audit.log)
├─ schedules/    # 不动
├─ watchlist/    # 不动
└─ cache/        # 不动
```

### 6. pytest 757 必须保持

- Phase 1: 757 passed
- Phase 2 (每页): 757 passed
- Phase 3 触发条件: 757 passed
- Phase 3 后: ~600-650 passed (Streamlit mock 测试删除后)

---

## 风险与缓解 (Risks & Mitigations)

| 风险 | 等级 | 缓解 |
|---|---|---|
| CORS 配置错误 | 低 | `backend/main.py` 已有 `allow_origins=["*"]` (dev), 生产同源 |
| SSE 反代 (nginx) 切断 | 低 | 开发无 nginx, 生产 FastAPI 单进程无 nginx |
| Lightweight Charts v5 API 变更 | 低 | v0.4.0 已用 v4.1.3, v5 升级官方 migration guide |
| shadcn/ui 升级频繁 | 低 | copy-paste 哲学, 手动同步成本低 |
| 用户中途想回 Streamlit | 低 | Phase 1-2 双端口, 回退 `git revert` 即可 |
| React bundle 体积膨胀 | 低 | Vite code splitting (路由级), dynamic import (ECharts) |
| pytest 757 回归 | 中 | 每页单独 commit, 任何回归立刻 revert |
| 实时 K 线 SSE 在 React 表现差 | 低 | Phase 2.4 单独 e2e, 不行就 WebSocket fallback |
| Phase 3 触发条件用户不满足 | 中 | 触发清单 6 条全部 ✅ 才进, 任一不满足不删 |
| Streamlit 7 天 fallback 期发现 bug | 中 | 修复优先级 = React 实现优先, Streamlit 仅作对照 |
| PDF export 迁移 | 低 | `web/pdf_export.py` 410 行, Phase 3 后评估迁移或删除 |

---

## 验收总结 (Acceptance Summary)

### Phase 1 Done ✓

- [ ] `frontend/` 完整 Vite + React 18 + TS
- [ ] 9 个 sidebar 占位 + 路由
- [ ] 设计 token 移植 + Tailwind + shadcn/ui
- [ ] ⚙️ 设置页端到端跑通 (GET/POST /api/settings)
- [ ] Vitest + Playwright init
- [ ] 三端口并行不冲突
- [ ] pytest 757 passed
- [ ] Streamlit 无回归

### Phase 2 Done ✓

- [ ] 全部 9 个 sidebar 页 React 实现
- [ ] **每页 parity-check.md § 4 详细 checklist 全部通过 (5 维度) + 用户文字确认 "✅ parity 通过"**
- [ ] **Phase 2.10 整体 parity check 9 页串行通过 (parity-check.md § 5.2)**
- [ ] 全部 9 个 e2e spec 通过
- [ ] pytest 757 passed (整个 Phase 2 期间)
- [ ] Streamlit 对应 panel 无回归
- [ ] **每页 `parity-results/{page}-diff.md` 记录在案**

### Phase 3 Done ✓ (触发后才执行)

- [ ] Phase 3 触发条件 8 条全部 ✅ (含 2 条 parity 条件)
- [ ] `web/` 目录清空 (29 文件 ~7949 行)
- [ ] Streamlit 相关测试清空 (7-8 文件 ~1679 行)
- [ ] `pyproject.toml` 移除 streamlit
- [ ] `python -m streamlit run` 报 "No module named streamlit"
- [ ] pytest ~600-650 passed (业务测试)
- [ ] React SPA 全功能, 9 页 e2e 通过
- [ ] `git tag v0.7.0` 发布

---

## 附录: 与 youfu-known 的差异

| 维度 | youfu-known (参考) | youfu-trading-agent-astock (本项目) |
|---|---|---|
| 后端 | FastAPI | FastAPI (沿用) |
| 前端框架 | React 18 + Vite | 同 |
| UI 库 | Chakra UI 2.10 | **shadcn/ui** (不同) |
| 状态管理 | Redux Toolkit | **Zustand** (不同, 更轻) |
| 数据获取 | RTK Query | **TanStack Query** (不同, 独立于 store) |
| 实时 | WebSocket | **SSE** (不同, 已有现成后端) |
| 主题 | Chakra theme | **CSS variables + Tailwind** (沿用 --bb-* token) |
| 测试 | Jest + RTL + Playwright | **Vitest + RTL + Playwright** (Vite 原生) |

> 用户已知 youfu-known 结构, 但本项目栈选择更轻 (Zustand 替 Redux Toolkit, shadcn/ui 替 Chakra, SSE 替 WebSocket)。理由详见 Decision 2/5/8。

---

## 附录: 文件统计 (估算)

| 类别 | 文件数 | 行数估计 |
|---|---|---|
| frontend/ (Vite + React + 9 页 + 测试) | ~80 | ~7000 |
| backend/api/ (新增 settings + logs + sector + portfolio + schedule + chart) | 6 | ~1500 |
| backend/main.py (扩静态挂载) | 1 | +30 |
| openspec/changes/react-migration/ (5 文件) | 5 | ~3500 |
| docs/architecture/ | 5 | ~1000 |
| **总计新增** | **~97** | **~13030** |
| **总计删除 (Phase 3)** | **~36-37** | **~9628+** |
| **净值** | +60 | +3402 |

---

*文档结束。Phase 3 触发条件清单见 `tasks.md` Phase 3。*