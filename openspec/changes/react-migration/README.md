# React Migration (v0.7.0)

> **Status**: 🚧 proposed — Phase 0 (spec v2.1)
> **Target**: Replace Streamlit frontend with React SPA + shadcn/ui, keep Python as FastAPI backend only.
> **v2.1 增**: [`parity-check.md`](./parity-check.md) (Phase 2 守门人, ~1500 行) + 15 个 P*.P1 Parity Gate + README 8 触发条件 (原 6 + parity 2)

This directory contains the spec-first artifacts for migrating the UI from Streamlit to a React SPA.

---

## 📚 文档结构

| 文件 | 用途 |
|---|---|
| [`.openspec.yaml`](./.openspec.yaml) | Spec 元数据 + **硬约束** (phase 触发 + 不动代码清单) |
| [`proposal.md`](./proposal.md) | Why / What / Capabilities / Impact / Migration path (~700 行) |
| [`design.md`](./design.md) | 主要 spec — 12 个决策 / 架构图 / API / Phase 拆分 / 删除清单 (~900 行) |
| [`tasks.md`](./tasks.md) | ~156 checkboxes — Phase 1 / 2 / 3 详细任务 (含 15 个 Parity Gate) |
| [`parity-check.md`](./parity-check.md) | **Phase 2 守门人** — 5 维度 / 9 页 checklist / § 5 执行流程 (~1500 行) |
| [`README.md`](./README.md) | 本文件 — 快速开始 + 进度跟踪 + Phase 2 完成条件 |

---

## 🚀 快速开始

### Phase 0 (当前): 仅 spec, 无 frontend/ 目录

```bash
ls openspec/changes/react-migration/
# .openspec.yaml  proposal.md  design.md  tasks.md  parity-check.md  README.md
```

### Phase 1 (即将开始): 三端口并行

**前置**:
- Node.js ≥ 20
- Python ≥ 3.10
- 现有 pytest 757 passed

**启动**:

```bash
# Terminal 1: Vite dev server (React SPA)
cd frontend && npm install && npm run dev
# → http://localhost:5173

# Terminal 2: FastAPI
python -m backend.main
# → http://localhost:8000 (API + /docs)

# Terminal 3: Streamlit (fallback, Phase 1-2 期间)
python -m streamlit run web/app.py
# → http://localhost:8501
```

或一键脚本:

```bash
./scripts/dev.sh
# 一次性启 Vite + FastAPI + Streamlit
```

### Phase 3 后: 单端口

```bash
# 1. 构建前端
cd frontend && npm run build

# 2. 启动 FastAPI (单端口同时 serve API + SPA)
python -m backend.main
# → http://localhost:8000 (API + React SPA)
```

---

## 📊 Phase 进度

| Phase | 任务数 | 完成 | 状态 |
|---|---|---|---|
| Phase 1 (骨架 + 设置) | 26 | 0/26 | ⬜ 待开始 (含 P1.6.P1) |
| Phase 2 (9 页迁移) | ~93 | 0/93 | ⬜ 待开始 |
| Phase 2 Parity (15 gate) | 15 | 0/15 | ⬜ 待开始 (每页 5 步: Patch → Verify → 用户确认 → 记录 → 进下一步) |
| Phase 3 (删除 streamlit) | ~30 | 0/30 | ⛔ 等待触发 (8 条触发条件) |
| **总计** | **~164** | **0/164** | **0%** |

详细 checkbox 见 [`tasks.md`](./tasks.md)。Parity 守门逻辑见 [`parity-check.md`](./parity-check.md)。

---

## ✅ Phase 2 完成条件 (Parity Check)

**Phase 2 不算完成 → Phase 3 不能进**。Phase 2 完成 = 9 个 sidebar 页全部迁移 + 15 个 Parity Gate 全绿 + 跨页一致性 OK + pytest 0 回归。

### 每页 Parity Gate: 5 步 (硬约束)

每完成一页 React 迁移, 跑一次以下 5 步, **全绿才计为完成**:

```
Step 1: Patch   — 前端代码 + 后端 API + Playwright e2e 写完
Step 2: Verify  — 5 维度自动化校验
   ├─ npx playwright test <page>.spec.ts        0 失败
   ├─ python scripts/parity_check.py --page X  hash 全等 (数据 1:1)
   ├─ python scripts/parity_visual.py --page X AE < 1% 像素 (UI 1:1)
   ├─ python scripts/parity_perf.py --page X   Lighthouse ≥ 80 (性能 1:1)
   └─ python scripts/parity_fault_inject.py --page X 错误文案 1:1
Step 3: 用户确认 — 用户文字回复 "✅ {page} parity 通过"
Step 4: 记录     — 写 parity-results/{page}-diff.md
Step 5: 进下一步 — 任一 ❌ → 该页任务不算完成 → 不进 Phase 2 下一项
```

**15 个 Parity Gate 清单** ([`tasks.md`](./tasks.md) 全部 checkbox 化):

| Gate | 范围 | 主要校验点 |
|---|---|---|
| `P1.6.P1` | ⚙️ 设置 (Phase 1 回顾) | settings.json 读写 / 表单 / provider 切换 |
| `P2.2.P1` | 📋 历史 | history 列表 md5sum + 删除 + 详情 Markdown |
| `P2.3.P1` | 📋 日志 | SSE 实时流 + 9 类 chunk 着色 + GitHub PR 布局 |
| `P2.4.P1` | 📈 走势图 (~12 操作) | K 线 OHLCV/MA/Volume hash + SSE 推送 + 中文 ticker 解析 |
| `P2.5.P1` | 📈 板块轮动 | digest md5sum + 5 列表格 + EChart 暗色 |
| `P2.6.P1` | 📊 批量分析 (~14 操作) | job dict / status 转换 + 50 ticker 实时 SSE |
| `P2.7.P1.1` | 💼 总览 | 汇总卡片 + 持仓表格 + 集中度 |
| `P2.7.P1.2` | 💼 流水 | CRUD + ticker/类型/日期筛选 |
| `P2.7.P1.3` | 💼 配置 | 行业/板块/大类 3 饼图 + 集中度精度 |
| `P2.7.P1.4` | 💼 预警 (7 规则) | 7 规则 + 300s anti-repeat + LogStore |
| `P2.7.P1.5` | 💼 导入导出 (4 CSV) | detect/parse/import/export + UTF-8 BOM |
| `P2.7.P1.6` | 💼 收益风险 | XIRR/Sharpe/MaxDD/Brinson 数值精度 + 板块归因 |
| `P2.7.P2` | 💼 跨 6 tab 全局 | Zustand 共享 + 切 tab 无重渲染 |
| `P2.8.P1` | ⏰ 定时分析 | scheduler/croniter + 4 渠道通知 + watchlist |
| `P2.9.P1` | 📝 单笔分析 | run_one_analysis + H1/H2 + 7 trader reports + SSE |
| `P2.10.0` | 🛠️ tooling 脚本 | 编写 4 个 `scripts/parity_*.py` + 单测 |
| `P2.10.7` | 🌐 跨页串行 | 9 sidebar nav 切换 + 7 天 fallback |

(注: P2.10.0 是工具脚本编写, 不是页面 gate; 总共 15 页级 gate 上表 17 行含 P2.10.0/P2.10.7)

### 通过标准 (硬要求)

- ✅ **功能 / 数据 / 错误维度 0 容忍** (100% 一致)
- ✅ **UI 容忍 0.5% 像素差** (≥ 99.5% 一致)
- ✅ **性能容忍 ≤ 2× Streamlit 实际值** (Lighthouse ≥ 80)
- ✅ 每页用户必须文字回复 "✅ {page} parity 通过"
- ✅ 任一 ❌ → 该页任务**不算完成** → Phase 2 不算完成 → **不删 streamlit**

详见 [`parity-check.md` § 5.1 (页面阶段) + § 5.2 (整体)](./parity-check.md#5-parity-check-执行流程-execution-flow)。每个 gate 的详细 Verify 命令见 [`tasks.md`](./tasks.md) 中 `**P*.P1**` 行。

---

## ⛔ Phase 3 触发条件 (硬约束)

**8 条全部 ✅ 才进入 Phase 3**, 任一 ❌ → 不删 streamlit, 继续并行运行:

### 原 6 条 (v2.0)

1. ✅ React SPA 全部 9 个 sidebar 页跑通且 e2e 通过
2. ✅ Playwright e2e 0 失败
3. ✅ 用户手动跑一遍全部 9 个页 (用户截图/录屏/文字确认)
4. ✅ pytest 757 passed (0 回归)
5. ✅ Streamlit fallback 端口运行 ≥ 7 天**无关键问题**
6. ✅ 用户明确下令: "现在可以删 streamlit 代码"

### v2.1 新增 2 条 (parity 硬约束)

7. ✅ **每页 Parity Gate 5 步全绿** ([`parity-check.md` § 5.1](./parity-check.md#51-page-阶段-每页迁移完))
   - 每页 e2e 0 失败 + 数据 hash 全等 + 视觉 AE < 1% + Lighthouse ≥ 80 + 错误文案 1:1
   - 9 页 × `P*.P1` parity 任务 (`tasks.md` 中 P2.2.P1 - P2.9.P1 + P2.7.P1.1~.6) 共 15 个 gate 全 ✅
   - 用户文字回复 "✅ parity 通过" 每页一份

8. ✅ **跨页串行 Parity 全绿 + 7 天 fallback 通过** ([`parity-check.md` § 5.2](./parity-check.md#52-整体-phase-2-收尾-所有-9-页迁完))
   - `scripts/parity_check.py` + `parity_visual.py` + `parity_perf.py` + `parity_fault_inject.py` 跨页一致性 OK
   - Playwright 9 spec 串行跑无状态污染
   - Streamlit fallback 端口 7 天无 ERROR 日志
   - 用户手动跑过 9 页 (录屏/截图/文字确认)

**任何时候用户没明确下令前, 都并行运行 streamlit + React。**

详见 [`design.md` 第 5 节](./design.md#phase-3-删-streamlit-渲染代码-1-天-触发后才执行), 完整触发清单见 [`tasks.md` § 3 顶部](./tasks.md#phase-3-删-streamlit-渲染代码-1-天-触发后才执行)。

---

## 🗑️ Phase 3 删除清单摘要

详见 [`design.md` Phase 3 详细清单](./design.md#phase-3-删除清单-详细-checklist), 这里只列摘要:

### A. Streamlit 渲染代码 (29 文件, ~7949 行)

- `web/app.py` (447)
- `web/components/*.py` (21 文件, 5665) — 所有 panel / dialog / sidebar
- `web/styles/elements.css` (1393) + `web/styles.py` (797)
- `web/progress.py` (97) + `web/nav.py` (130) + `web/launch.py` (25)

### B. Streamlit 相关测试 (7-8 文件, ~1679 行)

- `tests/test_web_app_dispatch.py` (244)
- `tests/test_running_view_refresh.py` (122)
- `tests/test_chart_panel.py` (271) + `test_chart_panel_quote.py` (97)
- `tests/test_logs_panel.py` (103)
- `tests/test_portfolio_panel.py` (842)
- `tests/test_web_runner.py` (评估后决定)

### C. pyproject.toml

```diff
- "streamlit>=1.45.0",
```

### D. 数据 0 影响

```bash
~/.tradingagents/
├─ logs/  history/  portfolio/  schedules/  watchlist/  cache/
# Phase 3 前后一字不动
```

---

## 🔒 不修改的硬约束

| 类别 | 处理 |
|---|---|
| `tradingagents/` | **0 修改** (7 analyst + 数据层) |
| `cli/` | **0 修改** |
| `backend/core/` | **0 修改** (业务层) |
| `backend/api/{batch,batch_helpers,analyze,sse,progress,result,history}.py` | **0 修改** (已有) |
| `web/` | **Phase 1-2 保留, Phase 3 才删** |
| `pyproject.toml` deps | **Phase 1-2 不改, Phase 3 移除 streamlit** |
| `~/.tradingagents/` | **0 改动** (复用现有 JSON 格式) |
| pytest 757 | **必须 0 回归** (Phase 3 触发条件之一) |

---

## 🛠️ 技术栈

| 维度 | 选型 | 理由 |
|---|---|---|
| 前端框架 | **Vite + React 18 + TS** | dev HMR < 100ms, 生态最大 |
| UI 库 | **shadcn/ui** | Tailwind + Radix + copy-paste, 100% 可控 |
| K 线 | **Lightweight Charts v5** | Apache-2.0, 61 KB, 业界事实标准 |
| 图表 | **ECharts 6** | 中文文档, 暗色主题, 覆盖面广 |
| 状态 | **Zustand** | 4 KB, 简单 API, TS 友好 |
| 数据获取 | **TanStack Query v5** | 缓存 + 失效 + 重试, devtools |
| 路由 | **React Router 6** | 成熟稳定, 数据路由 |
| 实时 | **SSE** (EventSource) | HTTP 兼容, 已有后端, 自动重连 |
| 测试 | **Vitest + RTL + Playwright** | Vite 原生, 快, 业界标准 |
| 主题 | **CSS variables + Tailwind bridge** | 沿用 `--bb-*` token |
| 部署 | **FastAPI static mount** | 单进程, 单端口 |

详见 [`design.md` Decisions](./design.md#关键决策-decisions) (12 个决策)。

---

## 📁 关键文件链接

### 现有 (不修改)

- [`backend/main.py`](../../backend/main.py) — FastAPI 入口 (Phase 3 加静态挂载)
- [`backend/api/batch.py`](../../backend/api/batch.py) — 批量任务 (Phase 1-2 不动)
- [`backend/api/analyze.py`](../../backend/api/analyze.py) — 单笔分析 (Phase 1-2 不动)
- [`backend/api/sse.py`](../../backend/api/sse.py) — SSE 实时推送 (Phase 1-2 不动)
- [`backend/core/`](../../backend/core/) — 业务层 (0 修改)
- [`tradingagents/`](../../tradingagents/) — Analyst + 数据层 (0 修改)
- [`web/`](../../web/) — Streamlit 渲染 (Phase 1-2 保留, Phase 3 删)

### 新增 (Phase 1+)

- `frontend/` — React SPA (Phase 1 新建)
- `backend/api/settings.py` — Settings API (Phase 1 新建)
- `backend/api/{logs,sector,portfolio,schedule,chart}.py` — Phase 2 新建
- `docs/architecture/react-spa.md` — 架构文档 (Phase 1 新建)

### Spec

- [`.openspec.yaml`](./.openspec.yaml) — 元数据 + 硬约束 (Phase 1-3 不动代码清单)
- [`proposal.md`](./proposal.md) — Why / What / Migration (~700 行)
- [`design.md`](./design.md) — 主要 spec, 12 个决策 + 架构图 (~900 行)
- [`tasks.md`](./tasks.md) — ~156 checkboxes (含 15 个 Parity Gate P*.P1 行)
- [`parity-check.md`](./parity-check.md) — Phase 2 守门人, 5 维度 / 9 页 checklist / § 5 执行流程 (~1500 行)

---

## 🔄 回滚路径

任何 Phase 出问题, 立即回滚:

```bash
# Phase 1 回滚
git revert <phase-1-commit> && rm -rf frontend/

# Phase 2.X 回滚 (单页回滚)
git revert <phase-2.X-commit>

# Phase 3 回滚
git revert <phase-3-commit> && pip install streamlit>=1.45.0
```

**回滚不删数据**: `~/.tradingagents/` 全程不删。

---

## 📞 与用户约定

- **Phase 1-2 期间**: Streamlit 是 fallback, 用户主要用 React, 反馈差异
- **Phase 3 触发条件**: 用户主动评估 + 主动下令
- **不在触发条件满足前删 streamlit**: 即使用户说"差不多了"也**不删**, 必须 8 条全 ✅ (原 6 条 + v2.1 新增 2 条 parity 校验)
- **per-page commit**: 每个 page 一个 commit, 方便回滚单页
- **三端口并行**: Phase 1-2 全程保持 Streamlit 可用

---

## 🔗 相关文档

- [`CLAUDE.md`](../../CLAUDE.md) — 项目总览 (Phase 3 后更新架构图)
- [`README.md`](../../README.md) — 用户文档 (Phase 3 后更新启动命令)
- [`CHANGELOG.md`](../../CHANGELOG.md) — 变更日志 (v0.7.0 发布时更新)
- [`openspec/changes/portfolio-module/`](../../portfolio-module/) — 上一版 spec-first 范例

---

*Spec v2.1 完成 (v2.0 + parity-check.md + 15 P*.P1 gates + README 8 触发条件)。下一步: 用户确认后开始 Phase 1 实施。*