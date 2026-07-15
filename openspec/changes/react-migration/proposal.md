# React SPA Migration — Proposal

> **change_id**: `react-migration`
> **version**: v0.7.0
> **kind**: breaking
> **created**: 2026-07-15
> **status**: proposed

---

## Why

### 现状:Streamlit 作为前端渲染层的 7 个真实痛点

1. **重渲染失控** — Streamlit 每次 `st.session_state` 变化都触发整页 rerun。批量分析页 (📊) 跑 50 只票, ticker 列表状态变更会触发整个 panel 重建, 实测 30+ ticker 时肉眼可见卡顿 (1.2s+ rerun 延迟)。

2. **残留状态泄漏** — Streamlit `session_state` 没有 TTL, 切页面 (`render_*_panel`) 时旧 panel 的 session_state key 永久驻留, 经常出现"切到日志页后回分析页, ticker 还是上一次的值"的诡异 bug。

3. **实时 K 线 push 卡顿** — `chart_panel` 用 Lightweight Charts CDN + SSE 直接连 push2his, 这条路在 Streamlit 之外更直接; Streamlit 的 iframe + WebSocket 桥接反而引入额外序列化开销。

4. **复杂 dialog/form 表达受限** — 仓位面板 6 tabs × 4 dialogs (新增/编辑/交易/预警) 全靠 streamlit dialog + form, 代码量 ~3000 行 (`portfolio_panel.py` + 5 个子 panel + `portfolio_dialogs.py` 704 行), 改一个 form 字段要全文搜 `st.form_*`。

5. **测试困难** — Streamlit 组件测试必须 monkeypatch `streamlit.*` 全局 namespace (`tests/test_portfolio_panel.py` 842 行, 几乎全是 mock); 真正的 UI 行为没有验证, 只能验证函数返回值。

6. **样式散落** — `web/styles/elements.css` 1393 行, 改一个按钮 hover 要全局搜索 `.bb-btn` / `.bb-button` / `.bb-button-primary` 等十几个变体, 没有 token 化设计系统。

7. **现代前端生态脱节** — Tailwind / shadcn/ui / Radix / TanStack / Vite 全部用不上; React 18 并发渲染、Suspense、server components 等现代能力全部无法享受。

### 目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                  Browser (React SPA — 新)                        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ 📝分析 │ │ 📊批量  │ │ 📈板块  │ │ 💼仓位  │ │ 📋历史  │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│  shadcn/ui + Tailwind + Lightweight Charts + ECharts             │
│  Zustand + TanStack Query + React Router 6                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP / SSE
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│              FastAPI (扩展现有 backend/api/)                      │
│  /api/analyze  /api/batch  /api/batch/{id}/stream (SSE)          │
│  /api/portfolio/*  /api/schedule/*  /api/kb/*  /api/sector/*     │
│  /api/logs/*  /api/history  /api/settings  /api/health           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Python 业务层 (零修改)                                            │
│  tradingagents/  cli/  backend/core/  backend/api/               │
└─────────────────────────────────────────────────────────────────┘
```

### 关键收益 (Why Now)

- **零业务代码改动**: Python 业务层 100% 保留, 渲染层完全替换 → 风险可控
- **可复用**: 现有 FastAPI (`backend/api/batch.py` + `sse.py`) 已经跑通生产级 SSE 实时推送, 不需要重写后端
- **可参考**: 用户已有 `youfu-known` (FastAPI + React 18 + Chakra UI + Vite) 项目经验, 栈对齐
- **测试零回归**: Phase 3 触发条件之一就是 pytest 757 必须 0 失败, 业务代码不动就不可能回归

### 为什么必须 Phase 3 删 Streamlit

用户原话: *"重构完成后我要你删除现在所有 python 渲染的所有代码"*

理由:
1. **避免双前端长期并存** — React + Streamlit 并行 7 天验证通过后, Streamlit 不再被访问, 留着是死代码 + 维护负担
2. **依赖清理** — `streamlit>=1.45.0` 从 pyproject.toml 移除, `web/styles/elements.css` 1393 行不再加载
3. **测试清理** — 8 个 `tests/test_web_*.py` + `test_streamlit_*.py` + `test_chart_panel*.py` 等 ~1900 行 mock 测试删除
4. **不删的硬约束** — Phase 3 触发条件**必须**全部满足, 用户**必须**明确下令, 不到点不删

---

## What Changes

### 新增 (additions)

| 类别 | 内容 | 行数估计 |
|---|---|---|
| 前端框架 | `frontend/` (Vite + React 18 + TS + Tailwind + shadcn/ui) | ~5000 行 (含 9 页) |
| K 线组件 | `frontend/src/components/charts/LightweightKline.tsx` | ~300 |
| 图表组件 | `frontend/src/components/charts/EChart.tsx` | ~200 |
| 设计 token | `frontend/src/styles/tokens.css` (从 `web/styles/tokens.css` 移植) | ~150 |
| API client | `frontend/src/api/{analyze,batch,portfolio,schedule,kb,sector,log,history,settings}.ts` | ~800 |
| 状态管理 | `frontend/src/stores/{portfolioStore,scheduleStore,analysisStore}.ts` | ~400 |
| Hooks | `frontend/src/hooks/{useAnalysis,useBatchJob,usePortfolio,useSchedule}.ts` | ~300 |
| 后端扩展 | `backend/api/{portfolio,schedule,sector,kb,settings,log}.py` | ~1500 |
| 后端 app | `backend/main.py` (已有, 扩展 router 注册 + 静态挂载) | +50 |
| 测试 | `frontend/tests/unit/*.test.ts` (Vitest) | ~600 |
| 测试 | `frontend/tests/e2e/*.spec.ts` (Playwright) | ~500 |
| 文档 | `docs/architecture/react-spa.md` | ~200 |
| 文档 | `openspec/changes/react-migration/*` (本文件) | ~3000 |

### 修改 (modifications — Phase 3 才做, Phase 1-2 不动)

| 文件 | 修改内容 |
|---|---|
| `pyproject.toml` | 删除 `streamlit>=1.45.0` 依赖 (Phase 3) |
| `backend/main.py` | 增加 `app.mount("/", StaticFiles(...))` 挂载 Vite build |
| `README.md` | 改启动命令 (Phase 3 后) |
| `CLAUDE.md` | 更新架构图 (Phase 3 后) |

### 删除 (deletions — 仅 Phase 3, 触发后)

详见 `design.md` 第 5 节"Phase 3 删除清单", 这里只列摘要:

- `web/app.py` (447 行) — Streamlit 入口
- `web/components/*.py` 全部 (21 个文件, 5665 行) — 所有 panel / dialog / sidebar
- `web/styles/elements.css` (1393 行) — Streamlit-specific CSS
- `web/styles/components.css` — 推测 streamlit-only, 删前确认
- `web/styles.py` (797 行) — Streamlit 样式加载
- `web/progress.py` (97 行) — Streamlit ProgressTracker
- `web/nav.py` (130 行) — Streamlit 导航
- `web/launch.py` (25 行) — Streamlit 启动器
- `tests/test_web_app_dispatch.py` (244 行)
- `tests/test_running_view_refresh.py` (122 行)
- `tests/test_chart_panel.py` (271 行)
- `tests/test_chart_panel_quote.py` (97 行)
- `tests/test_logs_panel.py` (103 行)
- `tests/test_portfolio_panel.py` (842 行)
- `tests/test_web_runner.py` — 删前确认是否含非 UI 测试

**保留**:
- `web/runner.py` (301 行) — 业务层分析运行器, 但需脱 streamlit 依赖 (用 `backend/core/runner.py` 替换或重写)
- `web/pdf_export.py` (410 行) — PDF 导出, 可改为 backend 工具或保留
- `web/history.py` (69 行) — 可能复用

### 保留 (zero-change)

- `tradingagents/` — 7 analyst + Bull/Bear + 数据层, 一行不动
- `cli/` — CLI 入口, 一行不动
- `backend/core/` — job_queue / scheduler / portfolio_store / log_store / history_store / portfolio_calc / portfolio_alerts / portfolio_import / notifier / tracker / watchlist / runner, 一行不动
- `backend/api/batch.py + batch_helpers.py + analyze.py + sse.py + progress.py + result.py + history.py` — 已有 FastAPI, Phase 1-2 一行不动, Phase 1 扩展, Phase 3 不动

---

## Capabilities

### New Capabilities

| Capability | 说明 | 落到哪 |
|---|---|---|
| `react-spa-shell` | Vite + React 18 + TS 骨架 + 路由 + 主题 + 9 sidebar 入口 | `frontend/` |
| `react-shadcn-ui` | shadcn/ui 组件库 (button / dialog / tabs / form / table / toast 等) | `frontend/src/components/ui/` |
| `react-charts` | Lightweight Charts (K线) + ECharts (饼图/柱图/折线) 封装 | `frontend/src/components/charts/` |
| `react-state` | Zustand 全局状态 (portfolio / schedule / analysis) | `frontend/src/stores/` |
| `react-data-fetch` | TanStack Query 缓存 + 重试 + 失效 | `frontend/src/api/` |
| `fastapi-extension` | 扩展 FastAPI: portfolio / schedule / sector / kb / settings / log | `backend/api/*.py` |
| `fastapi-static-mount` | Vite build 挂载到 FastAPI `/` | `backend/main.py` |
| `react-e2e` | Playwright 9 sidebar e2e 覆盖 | `frontend/tests/e2e/` |

### Modified Capabilities
- `web-rendering` → **deprecated** (Phase 3 删除)
- `streamlit-ui` → **deprecated** (Phase 3 删除)
- `pdf-export` → **保留** 或迁移到 backend/core/pdf_export.py

---

## Parity 原则 (Parity Principles)

> 详见 [`parity-check.md`](./parity-check.md)。本节是总览, 让 reviewer 一眼看到核心约束。

### 核心原则

**React 新页 ≠ "复制 Streamlit UI"; React 新页 = "功能完全等价于 Streamlit 老页"。** 迁移的真正质量不在于"按钮长得像不像", 而在于"用户切到 React 页能不能完成跟 Streamlit 一样的操作, 拿到一样的结果"。

### 5 维度等价

| 维度 | 要求 | 容忍度 | 校验工具 |
|---|---|---|---|
| **功能** | 老页每个 button / form / select / dialog, 新页必须有等价控件 | **0 缺失** (100% 覆盖) | Playwright e2e (~106 必执行操作) |
| **数据** | React 读到 / 写到的数据 md5sum == Streamlit 读到 / 写到 | **0 偏差** (100% 一致) | `scripts/parity_check.py` hash 对比 |
| **UI / 视觉** | 同 ticker + 同日期截图 diff < 1% 像素, 暗色 Bloomberg 风 1:1, 中文文案 1:1, sidebar 9 入口 1:1 | ≤ 0.5% 像素 | Playwright 截图 + ImageMagick + OpenCV |
| **性能** | 首屏 ≤ 2× Streamlit, 切页 < 200ms, SSE < 1s, bundle gzip < 500 KB | ≤ 100% 慢可接受 | Lighthouse + 手量 |
| **错误** | API key 无效 / ticker 不存在 / 网络超时 / 数据源 404, React 报错信息跟 Streamlit 同等 | **0 偏差** (100% 等价) | `scripts/parity_fault_inject.py` |

### 不可妥协项 (Hard NO)

- ❌ "React 实现不了 X, 删 X" (除非用户明确接受)
- ❌ "数据字段多/少几个, 没问题" (字段顺序 / 字段值 1:1)
- ❌ "Streamlit 旧, React 用现代风更好" (暗色 Bloomberg 风 1:1)
- ❌ "性能差一点, 感知不到" (≤ 2× Streamlit 实际值可接受, 超不接受)
- ❌ "报错文案改一下更友好" (错误信息 100% 1:1, 文案不改)

### Phase 2 每页流程 (5 步)

1. **Patch** — 写代码 + 写 e2e + commit
2. **Verify** — 跑 5 维度校验 (e2e / hash / 截图 / Lighthouse / fault injection)
3. **用户确认** — 用户切 React / Streamlit 对比, 文字回复 "✅ parity 通过"
4. **记录** — 写 `parity-results/{page}-diff.md` (失败 / 例外 diff 全部记录)
5. **进下一页** — 5 步全绿 + 用户确认 → 该页计入完成

任一 ❌ → 该页任务**不算完成**, 不进 Phase 2 下一项, 不进 Phase 3。

### Phase 2 收尾 (整体)

9 页全部 ✅ 后, 跑一次整体 parity check (跨页一致性 + 7 天 fallback + 用户全 9 页手动确认), 全绿才进 Phase 3 触发条件检查。

---

## Phase 划分

> **核心原则**: Phase 1-2 React SPA + Streamlit **并行运行** (双端口), 端到端验证后才进下一步。**Phase 3 触发条件**详见 `design.md` 第 5 节。

### Phase 1 — 骨架 + 设置页 (预计 3-5 天)

**目标**: 搭出 React SPA 骨架, 第一个 page (⚙️ 设置) 端到端跑通, 跟现有 FastAPI 串通, 跟 Streamlit 并行不冲突。

**范围**:
- `frontend/` 完整 Vite 项目
- 路由 + 9 个 sidebar 占位
- 设计 token 移植 (`tokens.css`)
- Tailwind + shadcn/ui init
- ⚙️ 设置页 (LLM provider / API key / Deep/Quick think model) — **第一个真实页**
- FastAPI 新增 `/api/settings` (GET / POST) — 读写 `~/.tradingagents/settings.json` 或 env

**不做的**:
- 不删任何代码
- 不改现有 pytest
- 不改 pyproject.toml deps

**验收**:
- `cd frontend && npm run dev` 启动 Vite dev server (默认 :5173)
- `python -m backend.main` 启动 FastAPI (默认 :8000)
- `python -m streamlit run web/app.py` 启动 Streamlit (默认 :8501)
- 三端并行不冲突
- React SPA 能保存 LLM 配置 → FastAPI 落盘 → 再次 GET 返回新值
- Streamlit 仍能正常使用 (无回归)
- pytest 757 全绿

### Phase 2 — 逐页迁移 (预计 2-3 周)

**目标**: 按"易 → 难"顺序迁移 9 个 sidebar 页, 每页 e2e 通过后才进下一页。

**顺序** (易 → 难, 跟 streamlit 现有 panel 映射):

| # | sidebar | streamlit panel | React 页 | 估计工期 | 关键依赖 |
|---|---|---|---|---|---|
| 2.1 | ⚙️ 设置 | `settings_panel.py` | `SettingsPage` | 已做 | Phase 1 |
| 2.2 | 📋 历史 | `history_panel.py` | `HistoryPage` | 1d | `/api/history` 已存在 |
| 2.3 | 📋 日志 | `logs_panel.py` | `LogsPage` | 1d | `log_store` + `/api/logs/*` 新增 |
| 2.4 | 📈 走势图 | `chart_panel.py` | `ChartPage` | 2d | Lightweight Charts + SSE |
| 2.5 | 📈 板块轮动 | `sector_panel.py` | `SectorPage` | 1d | `/api/sector/digest` 新增 |
| 2.6 | 📊 批量分析 | `batch_panel.py` | `BatchPage` | 3d | `/api/batch/*` 已存在 |
| 2.7 | 💼 我的仓位 | `portfolio_panel.py` + 5 子 + dialogs | `PortfolioPage` (6 tabs) | 4d | `/api/portfolio/*` 新增 |
| 2.8 | ⏰ 定时分析 | `schedule_panel.py` + dialogs | `SchedulePage` | 3d | `/api/schedule/*` 新增 |
| 2.9 | 📝 分析 | `app.py` main flow + `runner.py` | `AnalysisPage` | 3d | `/api/analyze` + SSE |

**每页流程**:
1. 在 `frontend/src/pages/{Page}/` 新增 `{Page}Page.tsx`
2. 在 `backend/api/` 新增对应 endpoints
3. 写 Vitest 单测 (`frontend/tests/unit/{page}.test.tsx`)
4. 写 Playwright e2e (`frontend/tests/e2e/{page}.spec.ts`)
5. 本地端到端跑通 (React ↔ FastAPI ↔ Python 业务层)
6. Streamlit 仍在同功能, 用户切换对比无差异
7. git commit (per-page commit, 方便回滚)

**不做的**:
- 不删任何 streamlit 代码
- 不改现有 pytest (757 必须 0 回归)
- 不改 pyproject.toml deps

**验收** (每页):
- React 页 e2e 通过
- Streamlit 对应 panel 仍可用 (无回归)
- pytest 757 全绿

### Phase 3 — 删 Streamlit 渲染代码 (预计 1 天, **触发后才执行**)

**触发条件** (必须**全部**满足, 缺一不可):

1. ✅ Phase 2 全部 9 页跑通
2. ✅ Playwright e2e **0 失败** (全部 9 页有 e2e, 全部通过)
3. ✅ pytest **757 passed** (0 回归)
4. ✅ 用户手动跑一遍全部 9 个页 (用户截图 / 录屏 / 文字确认)
5. ✅ React SPA 切到默认前端 8501 → 5173 (或 8000 看部署)
6. ✅ Streamlit fallback 端口运行 ≥ 7 天**无关键问题**
7. ✅ 用户**明确**下令: "现在可以删 streamlit 代码"

**未满足任一条件 → 不删**。任何时候用户没明确下令前, 都并行运行 streamlit + React。

**执行清单** (满足触发条件后):
- 详见 `design.md` 第 5 节"Phase 3 删除清单"
- 详见 `tasks.md` Phase 3 checkbox (共 10 个)

**验收**:
- `web/` 目录清空
- `pyproject.toml` 移除 `streamlit` 依赖
- `pytest tests/` 全绿 (业务测试, 应 ≈ 600-650, 因 8 个 UI 测试删了)
- `python -m streamlit` 找不到模块 (验证依赖清理)
- `tradingagents-web` console_script 报错或重定向到 React 启动
- React SPA 全功能, 无 streamlit 残留

---

## 影响 (Impact)

### 团队影响

| 角色 | 影响 |
|---|---|
| 用户 (1 人) | 短期 (Phase 1-2): 切换 React / Streamlit 两个端口对比, 反馈差异; 中期 (Phase 3+): 只用 React |
| 维护者 (1 人 = 用户) | 短期: 双前端维护 (React 新 + Streamlit 旧), 文档要明示; 长期: React 单前端, 测试更现代, 改 UI 不用全文搜 `st.` |

### 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 双端口运维混乱 | 中 | Phase 1 README 明示端口, Phase 2 加 "默认 React" 横幅, Phase 3 删 streamlit |
| React ↔ FastAPI CORS / SSE 兼容 | 低 | 现有 `backend/main.py` CORS `allow_origins=["*"]` 已经够, SSE `sse_starlette` 已经验证 |
| 数据格式不兼容 | 低 | 复用 `~/.tradingagents/` 目录, 不改 JSON schema |
| 用户中途弃用 React 想回 Streamlit | 低 | Phase 1-2 双端口并行, 回退成本 = 0 |
| 测试 0 回归失败 | 中 | 每页 commit, Phase 2 任何回归立刻 revert, 不进 Phase 3 |
| 实时 K 线 SSE 在 React 表现差 | 低 | Phase 2.4 单独做 e2e, 不行就 WebSocket fallback |
| Lightweight Charts bundle 体积 | 低 | 懒加载 + code splitting (路由级别) |
| shadcn/ui copy-paste 哲学不一致 | 低 | 一次性 init, 后续新增组件按需 copy |

### 不影响的

- Python 业务层 (tradingagents / cli / backend/core) 0 行修改
- 现有 pytest 757 必须 0 回归
- 数据存储 `~/.tradingagents/` 格式不变
- 部署流程 (Phase 3 之前不动, Phase 3 之后单 FastAPI + 静态)

---

## 迁移路径 (Migration Path)

```
2026-07-15  Phase 1 开始: 搭骨架 + 设置页
              ├─ 前端: Vite + React 18 + TS + Tailwind + shadcn/ui
              ├─ 后端: /api/settings (新增)
              ├─ 测试: Vitest + Playwright init
              └─ 验收: 三端口并行 OK, 设置页 e2e 通过

2026-07-20  Phase 1 完成 (预计)
              └─ commit: "feat(react): phase 1 — skeleton + settings page"

2026-07-21  Phase 2 开始: 逐页迁移
              ├─ 2.1 ⚙️ 设置 (Phase 1 已做)
              ├─ 2.2 📋 历史 (1d)
              ├─ 2.3 📋 日志 (1d)
              ├─ 2.4 📈 走势图 (2d, 含 Lightweight Charts 集成)
              ├─ 2.5 📈 板块轮动 (1d)
              ├─ 2.6 📊 批量分析 (3d)
              ├─ 2.7 💼 我的仓位 (4d, 最复杂 6 tabs)
              ├─ 2.8 ⏰ 定时分析 (3d, 含 scheduler 对接)
              └─ 2.9 📝 分析 (3d, 含 SSE 实时推送)

2026-08-21  Phase 2 完成 (预计, 视实际情况浮动)
              └─ commit: "feat(react): phase 2 — all 9 sidebar pages migrated"

2026-08-22  Phase 2 等待期 (7 天)
              ├─ React 默认前端, Streamlit fallback 8502
              └─ 用户每天手动验证至少 1 页, 反馈问题

2026-08-29  Phase 3 触发条件检查
              ├─ 9 页 e2e 全过?
              ├─ pytest 757 全绿?
              ├─ 用户明确下令?
              └─ ALL YES → Phase 3 执行

2026-08-30  Phase 3 执行 (1 天)
              ├─ 删 web/app.py + components + styles
              ├─ 删 tests/test_web_* / test_streamlit_*
              ├─ pyproject.toml 移除 streamlit
              └─ commit: "refactor: phase 3 — delete streamlit rendering"

2026-08-31  Phase 3 完成, v0.7.0 发布
              ├─ tag v0.7.0
              ├─ CHANGELOG 更新
              ├─ CLAUDE.md 更新架构图
              └─ README 更新启动命令
```

### 回滚路径 (Rollback)

任何 Phase 出问题, 立即回滚:

- **Phase 1 回滚**: `git revert <phase-1-commit>` → React 目录删除, Streamlit 仍是唯一前端
- **Phase 2.X 回滚**: `git revert <phase-2.x-commit>` → 该页 React 实现删除, Streamlit 对应 panel 仍是默认前端
- **Phase 3 回滚**: `git revert <phase-3-commit>` + `pip install streamlit>=1.45.0` → Streamlit 恢复

**回滚不删数据**: `~/.tradingagents/` 任何文件 Phase 1-3 全程不删, 回滚即恢复访问。