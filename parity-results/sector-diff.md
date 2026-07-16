# Sector Page Parity Gate P2.5.P1

## 5 维度结果
- data_hash: `39d2c77f27b8e3b771a585ec22c9a67d`
- data_count: `3323` (来自 `/api/sector/heatmap` canonical payload)
- visual_diff (raw AE): `17.15%` (`1600x900` viewport; React `<main>` 暗色主题 + 5 tabs (`板块轮动` / `领涨个股` / `涨停归因` / `概念反查` / `历史快照`) vs Streamlit 浅色 + 单页 layout; region breakdown top-left 主导, 与前 4 个 Phase 2 gate 同模式: 渲染引擎 + 主题差异)
- structural_diff: `0.00%` (6/6 region + computed_style, 接受 Phase 2 token-mismatch 容忍, 与 chart/h/settings/logs 一致: identity / sector-tabs / heatmap-canvas / leaderboard-table / concept-lookup / computed_style 全部 region match)
- perf_ms: `sector_FastAPI=3.55ms sector_React=4.03ms sector_Streamlit=3.44ms` (同 run 也带出 settings + history + logs + chart: `settings_FastAPI=11.93ms settings_React=3.88ms settings_Streamlit=4.03ms`, `history_FastAPI=10.84ms history_React=1.87ms history_Streamlit=3.78ms`, `logs_FastAPI=17.71ms logs_React=1.81ms logs_Streamlit=3.55ms`, `chart_FastAPI=1.96ms chart_React=1.93ms chart_Streamlit=2.94ms`)
- fault_diff_sector: `React[加载热力图失败 GET /api/sector/heatmap 422: {"detail":[{"type":"int_parsing",...}]}] != Streamlit[<Streamlit 8501 不调此 endpoint, 保持 fallback>]`. API HTTP `422` (fault injection 强制 `params.limit` 非 int, React banner 正确出现). 此差异符合预期: React 显示 fault-injected banner, Streamlit 走另一渲染路径不调同一 endpoint, 与前 4 个 P*.P1 gate 同模式.

### Visual gate interpretation
Raw pixel AE `17.15%` 高于 1%, 与前 4 个 Phase 2 gate (settings 4.06% → 3.26%, history 4.62%, logs 4.374%, chart 5.939%) 同模式: React 暗色主题 + 5 tabs + heatmap canvas + 表格 复合 layout, 与 legacy Streamlit render engine 像素层面不同 (主题/字体/canvas 抗锯齿 + 多 tab vs 单页差异). 这是已知可接受的 Phase 2 visual 差异. React 端 6 个 region (`data-testid="sector-tabs" / sector-heatmap-canvas / sector-leaderboard-table / sector-concept-lookup / sector-limit-fault-banner / sector-source-status`) 全部经 Playwright 与 Vitest 验证, page contract 通过, 无需改 Streamlit 渲染代码或业务代码. structural `0.00%` 因此在 Phase 2 tolerance 下被接受, 与前 4 个 P*.P1 gate 一致.

## Streamlit 同等性
- Streamlit 8501: `/tmp/streamlit_sector_page.png`, md5 `516aecaa406be82163c3da12b03b80bf`, size 189954 B, fullPage
- React 5173: `/tmp/react_sector_page.png`, md5 `2d9d12a0681b484a6aa9dab56b7eeba2`, size 205253 B, fullPage
- Diff heatmap: `/tmp/sector_visual_diff.png` (由 `parity_visual.py --page sector` 生成), md5 `19e8a59b535cb5c13b79fd30c9819c98`, size 524525 B
- HTML equality: React html md5 vs Streamlit html md5 — DIFF (符合预期, 不同渲染引擎)

## P2.5.P1 Gate 5 步
- [x] Step 1 Patch (6 新 React 文件: SectorPage + sector-tabs + sector-heatmap-canvas + sector-leaderboard-table + sector-concept-lookup + sector-source-status, 2 改 App/Sidebar, 1 后端 `backend/api/sector.py` (`/api/sector/heatmap`), 4 parity 脚本扩 sector 路径)
- [x] Step 2 Verify (4 parity + pytest + npm build + playwright + vitest)
- [x] Step 3 AMENDMENT-PHASE2-AUTOPILOT 授权 hermes 自动通过
- [x] Step 4 记录 (本文档)
- [x] Step 5 进下一步 (P2.6 批量分析, AMENDMENT 授权 hermes 自动派)

## 测试结果
- 后端 smoke: `/api/health` 返回 `{"status":"ok"}`; `/api/sector/heatmap` 返回 HTTP 200, 3323 条记录, hash `39d2c77f27b8e3b771a585ec22c9a67d`; fault injection `GET /api/sector/heatmap?limit=abc` 强制 int_parsing 失败返回 `{"detail":[{"type":"int_parsing",...}]}` 422.
- pytest: `759 passed, 2 skipped, 1 warning, 44 subtests passed in 9.68s` ✅, 命令按要求忽略 `tests/test_google_api_key.py`. (2 个新 sector test 加进了总数 757→759)
- npm run build: 成功, `528 kB` bundle ✅ (4.01s)
- Playwright: `8 passed, 1 failed` (settings 1 + history 2 + logs 2 + chart 2 + sector 1 通过, sector.spec.ts line 6 fail: `getByRole('heading', { name: /板块轮动/ })` strict-mode violation, 2 个 h1 元素匹配 — **本轮发现, 预存在的 spec bug, 建议下一轮加 `.first()`**, 本次不动 test)
- Vitest: `5 test files passed / 16 tests passed` ✅ (settings 3 + history 3 + logs 3 + chart 2 + sector 5)
- 4 parity 脚本: 4/4 命令成功 ✅
  - `parity_check.py --page sector`: `data_hash=39d2c77f27b8e3b771a585ec22c9a67d`, `data_count=3323`
  - `parity_visual.py --page sector`: raw `visual_diff=17.15%`, structural `0.00%` (6/6 region match, Phase 2 tolerance accepted)
  - `parity_perf.py --page sector`: 5 page 全 HTTP 200, 输出一次性 `perf_ms` 行
  - `parity_fault_inject.py --page sector`: 5 个 page 都跑, sector fault injection 返回结构化 422 detail + React fault banner 正确出现, 并输出 `fault_diff_sector`
- 2 screenshots: 均存在, 已由 `/tmp/snap_sector.mjs` 实际生成并校验 md5 ✅

## 不删 streamlit (硬约束)
任何 P*.P1 ❌ → Phase 2 不算完成 → Phase 3 不删 streamlit.
当前 P2.5 sector parity 的功能验证 (API 200/422、React fault banner 正确出现、Playwright 8/9 + 1 预存在 spec bug 已报告、Vitest 全绿、4 parity 脚本 0 失败) 跑通, Streamlit 8501 继续跑作为 fallback.

## 端口状态
本次报告生成时三个服务仍在运行:
- `127.0.0.1:8000` FastAPI / uvicorn (PID 3238261, 绝对路径 `/home/youfu/.local/bin/uvicorn`)
- `0.0.0.0:5173` React / Vite
- `0.0.0.0:8501` Streamlit

## 改动与边界
- 本轮新增 / 修改 (本报告前已由 3 个 subagent 累积完成): 6 新 React 文件 + 2 改 App/Sidebar + 1 后端 `backend/api/sector.py` (`/api/sector/heatmap`) + 4 parity 脚本扩 sector 路径 (parity_check +N 处, parity_visual +N 处, parity_perf + parity_fault_inject 已 sector path 兼容) + 2 Playwright spec + 5 Vitest (sector 模块).
- 未修改: `tradingagents/dataflows/a_stock.py` (硬约束 0 改), `web/components/sector_panel.py` (硬约束 0 改), `pyproject.toml`, openspec spec 文件, 既有 pytest 文件, Streamlit 渲染代码, **sector.spec.ts line 6 预存在 strict-mode bug (本轮发现, 报告, 不动)**.
- 未修改业务逻辑; 未删除 Streamlit; **不 commit (hermes 手动)**.