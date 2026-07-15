# React ↔ Streamlit Parity Check Spec (v0.7.0)

> **change_id**: `react-migration` (增量 spec v2)
> **version**: v0.7.0
> **status**: proposed
> **created**: 2026-07-15
> **purpose**: 定义 React 新页 vs Streamlit 老页**功能完全等价**的校验逻辑与验收清单, 保证 Phase 2 迁移质量, 为 Phase 3 删 streamlit 守门。

---

## 0. 适用范围 (Scope)

本文档是 `openspec/changes/react-migration/` 目录下的**增量 spec**, 与 `proposal.md` / `design.md` / `tasks.md` 互为补充:

- **本文件负责**: Phase 2 每页迁移完后, 怎么**验证**新老页面"功能完全一致"。
- **不负责**: 迁移本身的设计决策 (见 `design.md`)、为什么迁移 (见 `proposal.md`)、逐步任务 (见 `tasks.md`)。

### 与现有 spec 的关系

| 现有 spec | 本 spec 增量 |
|---|---|
| `proposal.md` § Phase 2 验收: "React 页 e2e 通过 + Streamlit 对应 panel 仍可用 (无回归)" | **明确**: "e2e 通过" 包含 5 维度 (功能/数据/UI/性能/错误), 任一不达标则该页不算完成 |
| `design.md` § 测试策略: Vitest + Playwright e2e (9 spec, 每页 3-5 场景) | **明确**: 每页除 e2e 外, 还需 hash 对比 + 截图 diff + fault injection |
| `tasks.md` Phase 2.10 整体验收: "全部 9 个 e2e spec 通过 + pytest 757 全绿" | **新增**: Phase 2 收尾跑一次**整体 parity check** (9 页串行切换 + 跨页一致性) |
| `.openspec.yaml` `phase_3_delete_streamlit` 触发条件 | **新增**: 任一页 parity check ❌ → 该页任务**不算完成** → Phase 2 不算完成 → Phase 3 触发条件**不满足** |

---

## 1. 目标 (Goal)

### 1.1 一句话

> **React 新页 ≠ "复制 Streamlit UI"; React 新页 = "功能完全等价于 Streamlit 老页"。**

迁移的真正质量, 不在于"按钮长得像不像", 而在于"用户切到 React 页能不能完成跟 Streamlit 一样的操作, 拿到一样的结果"。

### 1.2 6 项等价维度

| 维度 | 说明 | 容忍度 |
|---|---|---|
| **数据展示字段 1:1** | 老页显示哪些字段, 新页**必须**显示同样字段, 同样顺序, 同样精度 | **0 偏差** (不一致 = 缺失信息) |
| **表单 / 按钮 / 操作 1:1** | 老页所有 `button` / `form` / `select` / `dialog`, 新页**必须**有等价控件 | **0 缺失** (缺失 = 用户做不到) |
| **错误处理 / 验证信息 1:1** | 老页弹什么错、显示什么 inline error, 新页**必须**等价呈现 | **0 偏差** (用户依赖错误做判断) |
| **状态持久化 1:1** | 老页 `st.session_state` 存的 key / 值, 新页**必须**等价持久化 (localStorage / Zustand persist / 后端) | **0 偏差** (持久化丢失 = 用户配置漂移) |
| **视觉/交互 1:1 优先** | 暗色 Bloomberg 风必须对齐, 文案必须中文一致, 不一味"现代化"。可微调 spacing/字体, 但**不能改色板/语义/层级** | **≤ 0.5% 偏差** (UI token 严格 1:1) |
| **性能 不显著变慢** | 首屏 / 切页 / SSE 推送延迟不能比 Streamlit 慢 100%+ | **+100% 内可接受** (不能变慢一倍以上) |

### 1.3 不可妥协 (Non-Negotiable)

- **功能等价**: 100%。Streamlit 能做的事, React 全部能做, 反之亦然。
- **数据等价**: 100%。同一 ticker + 同一日期 + 同一参数, React 拉到的数据跟 Streamlit 拉到的 md5sum 一致。
- **错误等价**: 100%。同一个错误场景 (API key 错 / ticker 不存在 / 网络超时), React 跟 Streamlit 报同样的错。
- **UI 文案**: 100%。"📈 走势图" 不能变成 "📈 K线图表"; "📋 历史" 不能变成 "📋 分析历史"。
- **侧边栏 9 入口**: 100%。顺序/图标/中文文案全部 1:1。

### 1.4 可妥协 (Tolerable Up To 0.5%)

- 视觉微调: padding/margin/字体大小可微调 ±2px (响应式布局差异)。
- 颜色 token: 必须 1:1, 但边框/阴影可微调。
- 切页动画: React 可加 `framer-motion` 微动画, Streamlit 没有 → 不影响功能等价。
- 加载 skeleton: React 可加, Streamlit 显示 "Running..." → 等价 (都告知用户"在加载")。

---

## 2. Parity 5 维度详解 (Five Dimensions)

### A. 功能维度 (Functional Parity)

#### 定义

老 Streamlit `web/components/{panel}.py` 中的每一个 user-facing 操作 (button click / form submit / select choice / dialog open), React 新页**必须**有等价控件能触发等价行为。

#### 量化指标: 每页"必执行操作" 清单

| 页 | 必执行操作数 (估算) | 说明 |
|---|---|---|
| ⚙️ 设置 (P2.1) | 8 | 选 provider / 改 deep model / 改 quick model / 改 base URL / 保存 / 加载默认 / 重置 / 复制 API key |
| 📋 历史 (P2.2) | 6 | 列表加载 / 搜索过滤 / 点开详情 / 关闭详情 / 删除一条 / 删除全部 |
| 📋 日志 (P2.3) | 7 | 列出 ticker / 选 ticker / 选 date / 选 run / 展开 chunk / 折叠 chunk / 关闭 |
| 📈 走势图 (P2.4) | 12 | 输入 ticker / 中文名解析 / 选 range / 切 range / K线渲染 / MA 显示 / 成交量显示 / 实时 quote / SSE 推送 / 错误 ticker / fallback 数据源 / 暗色 |
| 📈 板块轮动 (P2.5) | 5 | 加载日报 / 选日期 / 显示 Top N / 显示概念板块饼图 / 点 [分析] 跳到分析页 |
| 📊 批量分析 (P2.6) | 14 | 输入 ticker 列表 / 校验 ticker / 选 LLM / 启动 / 看进度 (实时 SSE) / 取消 / 重试失败 / 看报告 / 下载 CSV / ticker 完成列表 / 失败行高亮 / 汇总 dialog / 跳历史 / 失败重试 |
| 💼 我的仓位 (P2.7) | 30+ | 6 tabs × 5 操作 ≈ 30: 总览 (4: 刷新/汇总卡/持仓表格/跳交易) + 流水 (5: 新增/编辑/删除/筛选/排序) + 配置 (3: 选维度/饼图/集中度卡) + 预警 (5: 列表/新增/启停/编辑/删除) + 导入导出 (6: 上传/格式检测/预览/确认/导出/模板下载) + 收益风险 (4: 4 卡/Brinson 柱图/Bull-Bear banner/空状态) + 账户管理 (3) |
| ⏰ 定时分析 (P2.8) | 13 | 列表 / 新建 / 编辑 / 删除 / 启停 / 立即跑 / cron 编辑 / ticker 源选 / 通知渠道选 / 看历史 run / 启停调度器 / 跳历史 / 全局状态 |
| 📝 分析 (P2.9) | 11 | 输入 ticker / 选 trade_date / 选 LLM / 启动 / SSE 进度 / 阶段展开 / 报告 tab / Bull/Bear 信号 / 跳历史 / 导出 PDF / 错误重试 |
| **总计** | **~106 个必执行操作** | 每页 React 必须全部跑通 |

#### 验证方法

- **Playwright e2e**: 每页一个 `frontend/tests/e2e/{page}.spec.ts`, 至少 3-5 场景, 覆盖上表的关键操作
- **手动验证**: 用户每天切换 React / Streamlit 对比 1-2 页, 反馈差异

#### 通过标准

- 该页所有必执行操作在 React e2e 中**全部跑通**
- 与 Streamlit 同操作结果**完全一致** (e.g. 点 "保存" → Streamlit 写入 `~/.tradingagents/settings.json` + 重新 load dotenv; React 必须做同样的事)

---

### B. 数据维度 (Data Parity)

#### 定义

React 页拉到 / 写到的数据, 必须**字节级一致**于 Streamlit 老页。

#### 数据源清单 (复用现有 schema)

```
~/.tradingagents/
├─ logs/{ticker}/{date}_run{NN}/
│   ├─ meta.json              # task metadata
│   ├─ llm_messages.jsonl     # stream chunks
│   ├─ tool_calls.jsonl       # stream chunks
│   └─ agent_outputs.jsonl    # stream chunks
├─ logs/history/*.json       # 分析历史
├─ portfolio/
│   ├─ positions.json
│   ├─ transactions.json
│   ├─ alerts.json
│   ├─ accounts.json          # v0.5.0
│   └─ audit.log
├─ schedules/scheduler.json  # 定时任务 + runs
├─ watchlist/watchlist.json
└─ cache/
    ├─ kline/{ticker}_{range}.csv
    └─ northbound_daily.csv
```

#### 验证方法 (hash 对比)

对每个 React 页 + Streamlit 页都要拉的数据, 写 `scripts/parity_check.py` (新增, 见 §3 B):

```python
# scripts/parity_check.py (伪代码示意)
def check_data_parity(page: str, ticker: str = None, date: str = None):
    streamlit_data = read_via_streamlit(page, ticker, date)
    react_data = read_via_react_api(page, ticker, date)
    
    s_hash = md5(json.dumps(streamlit_data, sort_keys=True).encode())
    r_hash = md5(json.dumps(react_data, sort_keys=True).encode())
    
    if s_hash != r_hash:
        diff = deep_diff(streamlit_data, react_data)
        return ParityResult(FAIL, f"data hash mismatch: streamlit={s_hash} react={r_hash}\n diff={diff}")
    return ParityResult(PASS, f"hash={s_hash}")
```

#### 通过标准

- 同一 ticker + 同一参数, React 端读到的 JSON / CSV 的 md5sum **必须 ==** Streamlit 端读到的 md5sum
- 字段顺序、空字段 (`null` vs 缺失) 也要 1:1 (e.g. positions.json 中没有的字段不能多出来也不能少)

#### 量化指标

| 页 | 关键数据 | hash 对比 |
|---|---|---|
| ⚙️ 设置 | `~/.tradingagents/settings.json` 或 env vars | 字段 1:1, 值 1:1 |
| 📋 历史 | `~/.tradingagents/logs/history/*.json` | N/A (Streamlit 直接读文件系统, React 走后端 API; 验证 API 返回 == 直接读文件) |
| 📋 日志 | `~/.tradingagents/logs/{ticker}/{date}_run{NN}/*.jsonl` | 同上 |
| 📈 走势图 | `~/.tradingagents/cache/kline/{ticker}_{range}.csv` (服务端拉) + realtime quote | OHLCV md5sum 1:1, MA5/10/20 数值 1:1 |
| 📈 板块轮动 | 实时拉 `tradingagents.dataflows.a_stock.get_sector_rotation_digest` | 返回 Markdown + Top N dict 必须 1:1 |
| 📊 批量分析 | 任务状态从 `backend/core/job_queue.py` 读 | job dict md5sum 1:1 |
| 💼 我的仓位 | `~/.tradingagents/portfolio/*.json` | positions/transactions/alerts/accounts 全部 md5sum 1:1 |
| ⏰ 定时分析 | `~/.tradingagents/schedules/scheduler.json` | schedule dict + runs list md5sum 1:1 |
| 📝 分析 | `~/.tradingagents/logs/{ticker}/{date}_run{NN}/*` | 同日志 |

---

### C. UI 维度 (Visual Parity)

#### 定义

同 ticker + 同日期 + 同窗口大小, Streamlit 截图 vs React 截图的**像素差异 < 1%**。

#### 视觉 1:1 强制项

| 类别 | 要求 |
|---|---|
| **暗色主题** | `--bb-accent` (冰蓝) / `--bb-up` (绿) / `--bb-down` (红) / `--bg-elevated` (深灰) / `--bg-surface` (更深灰) — 颜色 token 1:1, 不能"现代化" |
| **侧边栏** | 9 按钮顺序/图标/中文文案 1:1, 不可重排不可改名 |
| **字号** | h1 / h2 / h3 / body / small 5 级, 跟 Streamlit 同 |
| **间距** | padding / margin 可微调 ±2px (响应式差异), 不能超过 |
| **文案** | 中文文案 1:1, 标点符号 1:1 |
| **图标** | Emoji 1:1 (📈 📊 💼 ⏰ ⚙️ 📋 等) |

#### 验证方法

- **Playwright 自动截图**: 截 Streamlit (8501) + React (5173 / 8000) 同窗口大小的截图
- **ImageMagick compare**: `compare -metric AE streamlit.png react.png diff.png`, AE (absolute error count) < 1% 像素
- **OpenCV ORB feature match**: 特征点匹配 ≥ 95% (对齐 token 一致性)
- **手动肉眼对比**: 用户切换端口, 肉眼 review (兜底)

#### 通过标准

| 维度 | 阈值 | 工具 |
|---|---|---|
| 像素差 (AE) | < 1% | ImageMagick compare |
| 特征点匹配 | ≥ 95% | OpenCV ORB |
| 颜色 token | 100% 1:1 | CSS variable diff |
| 文案 | 100% 1:1 | 字符串 diff |
| 图标 | 100% 1:1 | Emoji diff |

#### 容忍范围 (0.5%)

- 字体抗锯齿差异 (不同浏览器)
- 1-2 px 间距漂移
- 阴影/边框微调 (如: React `border-radius: 4px`, Streamlit `border-radius: 6px` → 差异可接受)

---

### D. 性能维度 (Performance Parity, 不能显著变慢)

#### 定义

React 新页**不能比 Streamlit 老页慢 100% 以上**。

#### 关键指标

| 指标 | Streamlit 基准 (实测) | React 必须 | 工具 |
|---|---|---|---|
| **首屏 (FCP)** | ~2.5s (Streamlit 全量 JS) | < 5.0s (相似或更快) | Lighthouse / WebPageTest |
| **可交互 (TTI)** | ~4.0s (Streamlit WS 握手) | < 8.0s | Lighthouse |
| **切页时间** | ~1.2s (Streamlit rerun) | < 200ms (React Router) | Performance API |
| **SSE 推送延迟** | ~800ms (Streamlit iframe 序列化) | < 1s (浏览器直连) | EventSource readyState + data timestamp |
| **Bundle size (gzip)** | ~3 MB (Streamlit 全包) | < 500 KB (核心 + chart lib) | `vite build --report` |
| **冷启动后端** | ~3s (Streamlit 启动) | < 2s (uvicorn) | `time uvicorn backend.main:app` |

#### 验证方法

- **Lighthouse**: 跑 9 页 Lighthouse, 取 Performance 分数 ≥ 80
- **Chrome DevTools Performance tab**: 录制用户操作, 看 Frame rate / Long tasks
- **手量**: 用户切页, 感觉 ≤ Streamlit 即可
- **Bundle analyzer**: `vite-plugin-visualizer` 输出 HTML report, 确认 < 500 KB gzip

#### 通过标准

- 首屏/切页/SSE: React ≤ 2× Streamlit 实际值 (不能变慢一倍)
- Bundle size: gzip < 500 KB (含 react + router + tanstack-query + lightweight-charts + echarts + zustand)
- Lighthouse Performance ≥ 80

#### 容忍范围

- 首屏 +100% 可接受 (Streamlit 优化后 ~1.5s, React 3s 内可接受)
- Bundle +20% 可接受 (e.g. 引入 react-markdown 多 50 KB)

---

### E. 错误处理维度 (Error Parity)

#### 定义

同一错误状态 (API key 无效 / ticker 不存在 / 数据源 404 / 网络超时), React 跟 Streamlit 报同样的错、同样的位置、同样的样式。

#### 错误场景清单

| 错误类型 | Streamlit 行为 | React 必须行为 |
|---|---|---|
| **API key 无效 (LLM 401)** | `st.error("❌ API key 无效, 请检查 .env")` 顶部红条 | toast.error / inline error, 文案 1:1 |
| **ticker 不存在** | `st.warning(f"⚠️ {ticker} 不存在或已退市")` | toast.warning, 文案 1:1 |
| **网络超时** | `st.error("⏱️ 网络超时, 请重试")` + retry 按钮 | toast.error + retry 按钮 |
| **数据源 404 (mootdx/sina/push2his 全 fail)** | 自动 fallback 到下一个数据源, 全失败时 `st.error("📡 所有数据源均不可用")` | 同 fallback 链路, 同错误 |
| **CSV 解析失败** | `st.error("📄 CSV 格式错误, 请检查")` + 错误行高亮 | toast.error + 错误行表格高亮 |
| **Portfolio 校验失败 (负数 quantity)** | `st.error("❌ 持仓数量必须为正")` inline 表单 | 表单字段 red border + 错误文案 1:1 |
| **SSE 断连** | 静默重连 (Streamlit 内部) | toast.info("🔄 重新连接...") + EventSource 自动重连 |
| **LLM token 超出** | `st.warning("⚠️ 输入过长, 已截断")` | toast.warning, 文案 1:1 |
| **Schedule cron 格式错** | `st.error("❌ cron 表达式无效")` | toast.error + 字段 red border |
| **历史/日志不存在** | `st.info("ℹ️ 暂无日志. 完成一次分析后, 日志会自动出现.")` | 同样 info 文案 |

#### 验证方法 (Fault Injection)

写 `scripts/parity_fault_inject.py`, 故意制造错误场景, 跑两边, 对比错误信息:

```python
# scripts/parity_fault_inject.py (伪代码示意)
SCENARIOS = [
    "拔 API key",
    "ticker 不存在 (000000)",
    "网络超时 (mock)",
    "数据源 404",
    "CSV 格式错误",
    "负数 quantity",
    "cron 格式错",
]

for scenario in SCENARIOS:
    streamlit_msg = run_streamlit_scenario(scenario)
    react_msg = run_react_scenario(scenario)
    
    if not error_messages_match(streamlit_msg, react_msg):
        log(f"❌ {scenario}: \n  Streamlit: {streamlit_msg}\n  React: {react_msg}")
```

#### 通过标准

- 10 个错误场景下, React 报错信息**必须**等价 Streamlit (文案 / 位置 / 样式)
- 错误可恢复性 (retry / fallback) 链路等价
- 错误恢复时间 (用户感知) < 1s

---

## 3. Parity Check Tooling (实测工具)

### A. Functional: Playwright + Vitest

#### Playwright (e2e, 跑全 9 页)

**配置**: `frontend/playwright.config.ts`

```typescript
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  expect: { timeout: 5000 },
  fullyParallel: false,  // 顺序跑 9 页, 便于报告
  retries: 0,
  reporter: [
    ['list'],
    ['json', { outputFile: 'parity-results/functional.json' }],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:5173',
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
  },
});
```

**每页 1 个 spec, 覆盖关键操作**:

```
frontend/tests/e2e/
├── settings.spec.ts      # 8 场景
├── history.spec.ts       # 6 场景
├── logs.spec.ts          # 7 场景
├── chart.spec.ts         # 12 场景 (含 SSE)
├── sector.spec.ts        # 5 场景
├── batch.spec.ts         # 14 场景 (含 SSE)
├── portfolio.spec.ts     # 30 场景 (6 tabs × 5)
├── schedule.spec.ts      # 13 场景
├── analysis.spec.ts      # 11 场景
└── fixtures/
    ├── streamlit-url.ts  # http://localhost:8501 (对比用)
    └── react-url.ts      # http://localhost:5173
```

#### Vitest (unit, 跑组件逻辑)

**配置**: `frontend/vitest.config.ts` (Phase 1 已建)

```typescript
export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/unit/**/*.{test,spec}.{ts,tsx}'],
    coverage: { thresholds: { lines: 60, branches: 60 } },
  },
});
```

---

### B. Data: `scripts/parity_check.py` (hash 对比)

**新增脚本** `scripts/parity_check.py` (~200 行), 调用 Streamlit 和 React 两边, 拉同一数据, md5sum 对比。

```python
#!/usr/bin/env python3
"""React vs Streamlit data parity check.

对每个 React 页要读的数据, 同时通过 Streamlit 端 (直接读文件系统) 和 React 端
(走 FastAPI API) 读取, 对比 md5sum 是否一致。

Usage:
    python scripts/parity_check.py              # 全 9 页
    python scripts/parity_check.py --page chart # 单页
    python scripts/parity_check.py --page portfolio --ticker 600519  # 仓位页 + 指定 ticker
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Streamlit 端直接读文件系统
STREAMLIT_BASE = Path.home() / ".tradingagents"
# React 端走 FastAPI
REACT_API = "http://localhost:8000"


def md5(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.md5(data).hexdigest()


def check_settings() -> tuple[bool, str]:
    """⚙️ 设置: 对比 settings.json (Streamlit 读 env, React 走 API)."""
    # Streamlit: 直接读 env
    import os
    streamlit_settings = {
        "provider": os.getenv("LLM_PROVIDER", "minimax"),
        "deepModel": os.getenv("DEEP_THINK_LLM", "MiniMax-M2.7"),
        "quickModel": os.getenv("QUICK_THINK_LLM", "MiniMax-M2.7"),
    }
    
    # React: 走 API
    import requests
    react_resp = requests.get(f"{REACT_API}/api/settings")
    react_settings = react_resp.json()
    
    s_hash = md5(json.dumps(streamlit_settings, sort_keys=True))
    r_hash = md5(react_resp.content)
    
    return s_hash == r_hash, f"streamlit={s_hash} react={r_hash}"


def check_chart(ticker: str = "600519", range: str = "6m") -> tuple[bool, str]:
    """📈 走势图: 对比 OHLCV 数据 md5sum."""
    from tradingagents.dataflows.a_stock import get_stock_data
    
    # Streamlit 端: 直接调 Python
    df = get_stock_data(ticker, "2024-01-01", "2025-12-31")
    streamlit_ohlcv = df.to_dict(orient="records")
    
    # React 端: 走 API
    import requests
    react_resp = requests.get(
        f"{REACT_API}/api/analyze/kline",
        params={"symbol": ticker, "range": range},
    )
    react_ohlcv = react_resp.json()
    
    s_hash = md5(json.dumps(streamlit_ohlcv, sort_keys=True, default=str))
    r_hash = md5(json.dumps(react_ohlcv, sort_keys=True, default=str))
    
    return s_hash == r_hash, f"ticker={ticker} range={range} streamlit={s_hash} react={r_hash}"


def check_portfolio() -> tuple[bool, str]:
    """💼 仓位: 对比 positions/transactions/alerts/accounts 全部."""
    from backend.core.portfolio_store import get_portfolio_store
    
    store = get_portfolio_store()
    streamlit_positions = [p.to_dict() for p in store.list_positions()]
    streamlit_tx = [t.to_dict() for t in store.list_transactions()]
    streamlit_alerts = [a.to_dict() for a in store.list_alerts()]
    
    import requests
    react_positions = requests.get(f"{REACT_API}/api/portfolio/positions").json()
    react_tx = requests.get(f"{REACT_API}/api/portfolio/transactions").json()
    react_alerts = requests.get(f"{REACT_API}/api/portfolio/alerts").json()
    
    s_hash = md5(json.dumps(
        {"p": streamlit_positions, "t": streamlit_tx, "a": streamlit_alerts},
        sort_keys=True,
    ))
    r_hash = md5(json.dumps(
        {"p": react_positions, "t": react_tx, "a": react_alerts},
        sort_keys=True,
    ))
    
    return s_hash == r_hash, f"streamlit={s_hash} react={r_hash}"


# ... 其他 6 页类似 ...

CHECKS = {
    "settings": check_settings,
    "history": check_history,
    "logs": check_logs,
    "chart": check_chart,
    "sector": check_sector,
    "batch": check_batch,
    "portfolio": check_portfolio,
    "schedule": check_schedule,
    "analysis": check_analysis,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", choices=list(CHECKS.keys()))
    parser.add_argument("--ticker", default="600519")
    args = parser.parse_args()
    
    pages = [args.page] if args.page else list(CHECKS.keys())
    
    failures = []
    for page in pages:
        ok, msg = CHECKS[page](ticker=args.ticker) if page == "chart" else CHECKS[page]()
        status = "✅" if ok else "❌"
        print(f"{status} {page}: {msg}")
        if not ok:
            failures.append(page)
    
    if failures:
        print(f"\n❌ {len(failures)} 页 parity 失败: {failures}")
        sys.exit(1)
    else:
        print(f"\n✅ 全部 {len(pages)} 页数据 parity 通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

#### 运行

```bash
# 前置: 三端都跑
cd frontend && npm run dev          # React :5173
python -m backend.main              # FastAPI :8000
python -m streamlit run web/app.py  # Streamlit :8501

# 跑 parity check
python scripts/parity_check.py                  # 全 9 页
python scripts/parity_check.py --page chart     # 单页
python scripts/parity_check.py --page portfolio # 仓位

# 输出
# ✅ settings: streamlit=a1b2... react=a1b2...
# ✅ history: streamlit=c3d4... react=c3d4...
# ✅ chart: ticker=600519 range=6m streamlit=e5f6... react=e5f6...
# ✅ portfolio: streamlit=g7h8... react=g7h8...
# ...
# ✅ 全部 9 页数据 parity 通过
```

---

### C. Visual: 截图 diff (ImageMagick + OpenCV)

#### 自动化截图脚本

`scripts/parity_visual.py` (~150 行, 新增):

```python
#!/usr/bin/env python3
"""React vs Streamlit visual parity check (screenshot diff).

对每个页面, 用 Playwright 截同窗口大小的 Streamlit 和 React 截图, 用 ImageMagick compare
计算像素差, 阈值 < 1%。

Usage:
    python scripts/parity_visual.py
    python scripts/parity_visual.py --page chart --ticker 600519
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PAGES = [
    ("settings", "/settings", "⚙️ 设置"),
    ("history", "/history", "📋 历史"),
    ("logs", "/logs", "📋 日志"),
    ("chart", "/chart?ticker=600519&range=6m", "📈 走势图"),
    ("sector", "/sector", "📈 板块轮动"),
    ("batch", "/batch", "📊 批量分析"),
    ("portfolio", "/portfolio", "💼 我的仓位"),
    ("schedule", "/schedule", "⏰ 定时分析"),
    ("analysis", "/analysis?ticker=600519", "📝 分析"),
]


def screenshot_with_playwright(url: str, output: Path, port: int):
    """Use Playwright to screenshot a URL."""
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(f"http://localhost:{port}{url}")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(output), full_page=True)
        browser.close()


def diff_images(streamlit_png: Path, react_png: Path) -> tuple[int, int]:
    """ImageMagick compare. Returns (AE_count, total_pixels)."""
    result = subprocess.run(
        ["compare", "-metric", "AE", "-fuzz", "0.5%",
         str(streamlit_png), str(react_png), "/dev/null"],
        capture_output=True, text=True,
    )
    # AE = number of pixels different
    ae_count = int(result.stderr.strip().split()[-1]) if result.stderr.strip() else 0
    
    # Get total pixels from image dimensions
    from PIL import Image
    img = Image.open(react_png)
    total = img.width * img.height
    
    return ae_count, total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page")
    parser.add_argument("--threshold", type=float, default=0.01)  # 1%
    args = parser.parse_args()
    
    pages = [p for p in PAGES if not args.page or p[0] == args.page]
    
    out_dir = Path("parity-results/visual")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    failures = []
    for slug, path, label in pages:
        streamlit_png = out_dir / f"{slug}-streamlit.png"
        react_png = out_dir / f"{slug}-react.png"
        
        screenshot_with_playwright(path, streamlit_png, port=8501)
        screenshot_with_playwright(path, react_png, port=5173)
        
        ae, total = diff_images(streamlit_png, react_png)
        pct = ae / total
        
        threshold_pct = args.threshold
        status = "✅" if pct < threshold_pct else "❌"
        print(f"{status} {slug} ({label}): AE={ae}/{total} = {pct*100:.2f}% (阈值 {threshold_pct*100:.2f}%)")
        if pct >= threshold_pct:
            failures.append(slug)
    
    if failures:
        print(f"\n❌ {len(failures)} 页视觉 parity 失败: {failures}")
        sys.exit(1)
    else:
        print(f"\n✅ 全部 {len(pages)} 页视觉 parity 通过")


if __name__ == "__main__":
    main()
```

#### 运行

```bash
python scripts/parity_visual.py
# ✅ settings (⚙️ 设置): AE=12453/1296000 = 0.96% (阈值 1.00%)
# ✅ history (📋 历史): AE=8732/1296000 = 0.67% (阈值 1.00%)
# ✅ chart (📈 走势图): AE=5234/1296000 = 0.40% (阈值 1.00%)
# ...
# ✅ 全部 9 页视觉 parity 通过
```

---

### D. Performance: Lighthouse + 手量

#### Lighthouse

`scripts/parity_perf.py` (~50 行, 新增):

```python
#!/usr/bin/env python3
"""Run Lighthouse on all 9 React pages, output JSON report."""

from pathlib import Path
import subprocess

PAGES = ["settings", "history", "logs", "chart", "sector", "batch", "portfolio", "schedule", "analysis"]
BASE = "http://localhost:5173"

for page in PAGES:
    out = Path(f"parity-results/perf/{page}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "npx", "lighthouse", f"{BASE}/{page}",
        "--output=json",
        f"--output-path={out}",
        "--chrome-flags=--headless --no-sandbox",
        "--quiet",
    ])
    print(f"✅ {page} Lighthouse 跑完, 见 {out}")
```

#### 手量

用户每天切换 React / Streamlit, 感觉 ≤ Streamlit 即可, 记录到 `parity-results/perf/user-notes.md`。

---

### E. Error: Fault Injection

`scripts/parity_fault_inject.py` (~100 行, 新增):

```python
#!/usr/bin/env python3
"""React vs Streamlit error parity via fault injection.

对每个错误场景, 故意制造, 看两边报什么错, 对比是否一致。
"""

SCENARIOS = [
    ("拔 API key", "unset LLM_API_KEY; run analyze; check error"),
    ("ticker 不存在", "analyze ticker=000000; check error"),
    ("网络超时 (mock)", "monkeypatch requests.get to timeout"),
    ("数据源 404 (mootdx fail)", "monkeypatch mootdx to raise"),
    ("CSV 格式错误", "upload invalid.csv; check error"),
    ("负数 quantity", "POST portfolio position with qty=-100"),
    ("cron 格式错", "POST schedule with cron='invalid'"),
    ("LLM token 超出", "submit 100k token input"),
    ("SSE 断连", "kill backend mid-stream; check reconnect msg"),
    ("历史/日志不存在", "GET /api/logs/<unknown-ticker>"),
]

def run_scenario(name: str, setup_fn, action_fn) -> tuple[str, str]:
    """Returns (streamlit_error, react_error)."""
    # Streamlit
    setup_fn()
    sl_err = action_fn(streamlit_client)
    
    # React
    setup_fn()
    re_err = action_fn(react_client)
    
    return sl_err, re_err


# 对每个 scenario, 跑两边, 对比错误文案
```

---

## 4. Per-Page 详细校验清单 (9 页面)

> 每页 4 类 checklist: **功能** (Playwright e2e) / **数据** (hash 对比) / **UI** (截图 diff) / **错误** (fault injection)。
> 每页 checklist 总计 ~50-80 行, 9 页合计 ~500+ 行。

---

### Page 1. ⚙️ 设置 (`settings_panel.py` → `SettingsPage.tsx`)

#### 数据来源

- `web/components/settings_panel.py` (151 行, v0.6.x 稳定)
- `tradingagents/llm_clients/model_catalog.py` (`MODEL_OPTIONS`)
- env vars: `LLM_PROVIDER` / `DEEP_THINK_LLM` / `QUICK_THINK_LLM` / `*_API_KEY`
- Phase 1 新增 `~/.tradingagents/settings.json` (可选持久化)

#### 功能 checklist (Playwright e2e, **8 个必执行操作**)

- [ ] **F1** 页面打开后 GET `/api/settings`, 显示当前 provider (默认 minimax)
- [ ] **F2** provider 下拉框包含 9 个选项: minimax / deepseek / qwen / glm / openai / anthropic / google / xai / ollama
- [ ] **F3** 选 `openai`, deep model 自动切到 `gpt-4o`, quick model 自动切到 `gpt-4o-mini`
- [ ] **F4** 改 deep model 输入框接受任意字符串 (custom model name)
- [ ] **F5** 改 base URL 输入框接受 URL 格式
- [ ] **F6** 点 "保存" 按钮 → POST `/api/settings` → toast.success "设置已保存"
- [ ] **F7** 保存后刷新页面, GET `/api/settings` 返回新值 (持久化验证)
- [ ] **F8** 暗色主题所有元素可见 (无白色残影)

#### 数据 checklist (hash 对比)

- [ ] **D1** React 端 GET `/api/settings` 返回的字段 md5sum == Streamlit 端读 env vars 的 md5sum
- [ ] **D2** React 保存新 provider 后, `~/.tradingagents/settings.json` 内容跟 POST body 一致
- [ ] **D3** 字段顺序: `{provider, deepModel, quickModel, apiKey, baseUrl}` (固定顺序, 不变)

#### UI checklist (截图 diff)

- [ ] **U1** 顶部 "⚙️ 设置" 标题 + 副标题 "配置模型供应商与 API Key" 1:1
- [ ] **U2** provider 下拉框位置 / 宽度匹配 Streamlit
- [ ] **U3** 保存按钮 hover 颜色匹配 (`--bb-accent` 冰蓝)
- [ ] **U4** 暗色背景 (`--bg-elevated`) 1:1, 文字 (`--text-primary`) 1:1
- [ ] **U5** 中文文案 1:1 (e.g. "API Keys" 不变 "API 密钥")

#### 错误 checklist (fault injection)

- [ ] **E1** API key 为空时保存 → toast.error "❌ API key 不能为空"
- [ ] **E2** provider 选 `ollama` 但 base URL 没填 → toast.error "❌ Ollama 需要 base URL"
- [ ] **E3** 后端 `/api/settings` 500 → toast.error "❌ 保存失败, 请重试" + retry 按钮

---

### Page 2. 📋 历史 (`history_panel.py` → `HistoryPage.tsx`)

#### 数据来源

- `web/components/history_panel.py` (245 行)
- `~/.tradingagents/logs/history/*.json`
- 后端: 已有 `backend/api/history.py` (GET /api/history + DELETE /api/history/{id})

#### 功能 checklist (Playwright e2e, **6 个必执行操作**)

- [ ] **F1** 页面打开后 GET `/api/history`, 按 created_at 倒序列出全部历史
- [ ] **F2** 搜索框输入 ticker (e.g. "600519") → 实时过滤列表
- [ ] **F3** 信号徽章显示: 🟢 买入 / 🔴 卖出 / 🟡 持有 / 🟢 超配 / 🔴 低配 (跟 Streamlit 同)
- [ ] **F4** 状态徽章显示: ✅ completed / ❌ error / 🔄 running
- [ ] **F5** 点击某条历史 → 详情 dialog 打开, 显示完整 Markdown 报告
- [ ] **F6** 关闭 dialog → 返回列表 (状态保持, 搜索词不清空)

#### 数据 checklist (hash 对比)

- [ ] **D1** React 端 GET `/api/history` 返回的 list md5sum == Streamlit 端直接读 `~/.tradingagents/logs/history/*.json` 的 md5sum
- [ ] **D2** 字段顺序: `{id, ticker, trade_date, signal, status, created_at, duration_sec, summary}` (Streamlit 当前顺序)
- [ ] **D3** 删除某条后, GET 返回的 list md5sum == Streamlit 删除后的 list md5sum

#### UI checklist (截图 diff)

- [ ] **U1** 列表布局: ticker / trade_date / signal badge / status badge / duration
- [ ] **U2** 信号徽章颜色: Buy=绿, Sell=红, Hold=黄, Neutral=灰 (1:1)
- [ ] **U3** 状态徽章颜色: completed=绿, error=红, running=冰蓝
- [ ] **U4** 详情 dialog 居中, 暗色背景, Markdown 渲染

#### 错误 checklist

- [ ] **E1** `~/.tradingagents/logs/history/` 不存在 → 空状态 "ℹ️ 暂无历史"
- [ ] **E2** 后端 500 → toast.error + retry
- [ ] **E3** 删除失败 → toast.error "❌ 删除失败" + 不刷新列表

---

### Page 3. 📋 日志 (`logs_panel.py` → `LogsPage.tsx`)

#### 数据来源

- `web/components/logs_panel.py` (178 行, GitHub PR 风格 1:3 双列)
- `backend/core/log_store.py` (LogStore + LogWriter)
- `~/.tradingagents/logs/{ticker}/{date}_run{NN}/*.jsonl`

#### 功能 checklist (Playwright e2e, **7 个必执行操作**)

- [ ] **F1** 页面打开 → 列出所有 ticker (左列 ticker cards)
- [ ] **F2** ticker card 显示: ticker name + runs count + signal badge
- [ ] **F3** 点击 ticker card → 右列显示该 ticker 的所有 task (按 date + runId)
- [ ] **F4** 点击 task → 展开 chunks (按 type 着色: llm=紫, tool=绿, agent_output=蓝)
- [ ] **F5** chunk 折叠/展开 (shadcn Collapsible)
- [ ] **F6** 底部 "Running Tasks" 区域显示当前正在跑的任务 (实时更新)
- [ ] **F7** 暗色主题 GitHub PR 风格 1:1 (左列窄 / 右列宽)

#### 数据 checklist (hash 对比)

- [ ] **D1** React 端 GET `/api/logs` 返回 ticker list md5sum == Streamlit 端 `log_store.list_tickers()` md5sum
- [ ] **D2** React 端 GET `/api/logs/{ticker}/{date}/{runId}` 返回 chunks md5sum == Streamlit 端 `log_store.read_chunks()` md5sum
- [ ] **D3** chunk 字段: `{type, content, ts, agent?, tool?, ...}` 顺序 1:1

#### UI checklist (截图 diff)

- [ ] **U1** 1:3 双列布局 (左 ticker 列表窄, 右 task + chunks 宽)
- [ ] **U2** ticker card 暗色背景, hover 高亮 `--bb-accent` 边框
- [ ] **U3** chunk type 着色: llm=紫 (`#a371f7`), tool=绿 (`#3fb950`), agent_output=蓝 (`#58a6ff`)
- [ ] **U4** 折叠箭头旋转动画 1:1

#### 错误 checklist

- [ ] **E1** 无日志 → "ℹ️ 暂无日志. 完成一次分析后, 日志会自动出现."
- [ ] **E2** ticker 不存在 → 列表为空, 不报错
- [ ] **E3** SSE 断连 → "🔄 重新连接..." toast, 自动重连

---

### Page 4. 📈 走势图 (`chart_panel.py` → `ChartPage.tsx`)

> **最复杂的页**, 包含 K 线 + MA + 成交量 + 实时 quote + SSE 实时推送 + 中文 ticker 解析

#### 数据来源

- `web/components/chart_panel.py` (356 行, v0.4.0)
- `tradingagents/dataflows/a_stock.py` (`get_stock_data` 3-tier fallback + `get_realtime_quote`)
- `~/.tradingagents/cache/kline/{ticker}_{range}.csv` (24h CSV cache)
- 实时: `qt.gtimg.cn` (tencent) HTTP quote + 浏览器直连 push2his SSE

#### 功能 checklist (Playwright e2e, **12 个必执行操作**)

- [ ] **F1** 顶部 ticker 输入框接受 6 位代码 (e.g. `600519`)
- [ ] **F2** 时间范围按钮 7 个: `1d / 1w / 1m / 3m / 6m / 1y / all`, 默认 `6m`
- [ ] **F3** 点击 range 按钮立即重新加载 K 线
- [ ] **F4** 实时报价 banner 显示: 现价 / 涨跌 / 涨跌幅 / 成交量 / 最高 / 最低 / 今开 / 昨收
- [ ] **F5** K 线 + MA5/10/20 + 成交量副图 显示 (Lightweight Charts v5)
- [ ] **F6** SSE 推送每分钟至少 1 次 frame 更新 (验证 1 分钟内至少 1 次实时数据点)
- [ ] **F7** ticker 输入错误 (e.g. `000000`) 显示 inline error "⚠️ 股票代码不存在"
- [ ] **F8** 数据源切换 fallback 链路: mootdx → sina → push2his (全失败显示错误)
- [ ] **F9** 暗色主题所有元素可见 (无白色残影, 边框/网格线用 `--bb-grid` token)
- [ ] **F10** 中文 ticker 输入 "贵州茅台" → 自动解析为 `600519`
- [ ] **F11** ticker 输入框回车触发加载
- [ ] **F12** 鼠标 hover K 线显示十字光标 + OHLCV tooltip

#### 数据 checklist (hash 对比)

- [ ] **D1** 同一 ticker (`600519`) + 同一 range (`6m`), React 拉到 OHLCV md5sum == Streamlit 拉到 md5sum
- [ ] **D2** MA5/10/20 计算结果 1:1 (Streamlit `_compute_ma()` vs React `ma5 = ohlcv.close.rolling(5).mean()`)
- [ ] **D3** 成交量副图 md5sum 1:1
- [ ] **D4** 实时 quote 字段顺序: `{symbol, name, price, change, changePct, volume, high, low, open, prevClose}` (跟 Streamlit `_format_quote()` 一致)

#### UI checklist (截图 diff)

- [ ] **U1** 顶部 ticker 输入框 + 7 range buttons 横向排列 1:1
- [ ] **U2** 实时报价 banner 颜色: ups=绿 (`--bb-up`), downs=红 (`--bb-down`)
- [ ] **U3** chart canvas 位置 / 比例 (主图 70% + 副图 30%) 匹配
- [ ] **U4** 蜡烛颜色: ups=绿, downs=红, wicks 同色 1:1
- [ ] **U5** MA 线颜色: MA5=黄, MA10=橙, MA20=紫 (跟 Streamlit `_MA_COLORS` 1:1)
- [ ] **U6** 成交量柱子: ups=半透明绿, downs=半透明红

#### 错误 checklist (fault injection)

- [ ] **E1** 拔 API key → Streamlit 显示 "❌ 获取实时报价失败" vs React 显示 "❌ 获取实时报价失败" (文案 1:1)
- [ ] **E2** ticker `000000` 不存在 → Streamlit "⚠️ 股票代码不存在" vs React 同
- [ ] **E3** 数据源全部 fail → Streamlit "📡 所有数据源均不可用" vs React 同 (含 fallback 链路日志)
- [ ] **E4** SSE 断连 → "🔄 重新连接..." toast + 自动重连 (≤ 5s)
- [ ] **E5** ticker 输入超长 (20 字符) → inline error "❌ ticker 长度超出"

---

### Page 5. 📈 板块轮动 (`sector_panel.py` → `SectorPage.tsx`)

#### 数据来源

- `web/components/sector_panel.py` (384 行)
- `tradingagents/dataflows/a_stock.py` (`get_sector_rotation_digest`)
- 实时数据: 东财 np-ipick + 同花顺涨停归因 + 百度 PAE 概念反查

#### 功能 checklist (Playwright e2e, **5 个必执行操作**)

- [ ] **F1** 页面打开 → GET `/api/sector/digest?date=&topN=`, 默认 `date=today`, `topN=20`
- [ ] **F2** 顶部 toolbar: 搜索框 + min-count filter + 数据源状态 + 刷新按钮
- [ ] **F3** "机构选股策略" expander 显示 Top 3 (从 np-ipick)
- [ ] **F4** 概念板块 grouped table: 5 列表格 (代码/名称/题材/板块涨幅/操作), Top 3 默认展开
- [ ] **F5** 每行 `[分析]` 按钮 → 跳到 `📝 分析` 页 + 预填 ticker (2-step flow, 不直接 1-click 消耗 LLM token)

#### 数据 checklist (hash 对比)

- [ ] **D1** React 端 GET `/api/sector/digest` 返回的 digest Markdown md5sum == Streamlit 端 `get_sector_rotation_digest()` 输出 md5sum
- [ ] **D2** Top stocks list 字段 1:1: `{code, name, theme, ratio, ...}`
- [ ] **D3** 概念板块 group by theme 1:1 (Streamlit 用 `groupby(theme)` vs React 用 `Object.groupBy`)

#### UI checklist (截图 diff)

- [ ] **U1** 顶部 toolbar 布局: 搜索框左 / filter 中 / 状态右 / 刷新最右
- [ ] **U2** "机构选股策略" expander 折叠箭头 1:1
- [ ] **U3** 概念板块 grouped table 5 列宽度比例 1:1
- [ ] **U4** 板块涨幅正负色: ups=绿, downs=红
- [ ] **U5** `[分析]` 按钮 hover 颜色匹配 `--bb-accent`

#### 错误 checklist

- [ ] **E1** 数据源全 fail → "📡 板块数据获取失败" + retry
- [ ] **E2** date 格式错 → inline error "❌ 日期格式应为 YYYY-MM-DD"
- [ ] **E3** min-count 超出范围 → inline error "❌ min-count 必须在 1-100"

---

### Page 6. 📊 批量分析 (`batch_panel.py` → `BatchPage.tsx`)

> **最复杂的操作流**, 包含 ticker 校验 / SSE 实时进度 / 重试 / 取消 / 汇总 dialog / 跳历史

#### 数据来源

- `web/components/batch_panel.py` (447 行)
- `backend/core/job_queue.py` (423 行, TICKER_WHITELIST_RE + 任务调度)
- 已有 API: `POST /api/batch`, `GET /api/batch/{id}`, `GET /api/batch/{id}/stream`

#### 功能 checklist (Playwright e2e, **14 个必执行操作**)

- [ ] **F1** 页面打开 → 3 sections: 提交 (top) / 进行中 (middle) / 完成 (bottom)
- [ ] **F2** ticker 输入框接受多行 / 逗号分隔 (e.g. `600519\n000001\n002415`)
- [ ] **F3** ticker 校验: 6 位代码正则 `TICKER_WHITELIST_RE = re.compile(r"^\d{6}$")`, 非法 ticker 显示 ❌
- [ ] **F4** LLM 配置复用 settings 页 (`_render_llm_config`)
- [ ] **F5** 启动按钮 → POST `/api/batch` → 跳到 "进行中" section
- [ ] **F6** SSE 实时进度: 每个 ticker 完成时, 该行从 ⏳ → 🔄 → ✅/❌
- [ ] **F7** 进度条 (shadcn Progress) 显示总进度 (已完成 / 总数)
- [ ] **F8** 取消按钮 → POST `/api/batch/{id}/cancel` → 剩余 ticker 变 ⊘
- [ ] **F9** 失败 ticker 重试按钮 → POST `/api/jobs/{id}/retry`
- [ ] **F10** 看报告按钮 → dialog 显示 Markdown 报告 (`report_viewer.render_report`)
- [ ] **F11** 汇总 dialog: 总耗时 / 完成数 / 失败数 / 失败原因分类
- [ ] **F12** CSV 下载按钮 (顶部) → 下载汇总 CSV
- [ ] **F13** 失败行高亮 (红色背景) + 失败原因 hover 显示
- [ ] **F14** 50 ticker 实时更新无卡顿 (验证 React 解决 Streamlit 重渲染痛点)

#### 数据 checklist (hash 对比)

- [ ] **D1** React 端 POST `/api/batch` 创建的 job dict md5sum == Streamlit 端 `job_queue.create_batch()` md5sum
- [ ] **D2** 任务状态从 ⏳ → 🔄 → ✅/❌ 转换时, React 端 GET `/api/batch/{id}` 返回的 status md5sum 1:1
- [ ] **D3** ticker 校验错误列表 1:1 (跟 Streamlit `_parse_tickers(text)` 返回的 `(clean, invalid)` 一致)

#### UI checklist (截图 diff)

- [ ] **U1** 3 sections 布局: 提交 (top, sticky) / 进行中 (middle, scroll) / 完成 (bottom)
- [ ] **U2** ticker 输入框 textarea + "启动" 按钮右对齐
- [ ] **U3** 状态图标: pending=⏳, running=🔄, completed=✅, error=❌, cancelled=⊘
- [ ] **U4** 进度条颜色: 0-50%=黄, 50-99%=冰蓝, 100%=绿
- [ ] **U5** 失败行背景红色 + 失败原因 tooltip 1:1

#### 错误 checklist

- [ ] **E1** ticker 列表为空 → toast.error "❌ 请输入至少 1 个 ticker"
- [ ] **E2** ticker 全非法 → toast.error "❌ 没有合法的 ticker"
- [ ] **E3** 启动时 LLM 未配置 → toast.error "❌ 请先配置 LLM (去设置页)"
- [ ] **E4** 后端 500 → toast.error + retry
- [ ] **E5** SSE 断连 → "🔄 重新连接..." + 自动重连
- [ ] **E6** 取消时已完成 ticker 不变状态

---

### Page 7. 💼 我的仓位 (`portfolio_panel.py` + 7 子 → `PortfolioPage.tsx`)

> **最复杂的页** (6-7 tabs × 多个 dialogs), 拆 7 个子 checklist。

#### 数据来源

- `web/components/portfolio_panel.py` (184 行, dispatcher)
- 7 子: `portfolio_overview.py` / `portfolio_transactions.py` / `portfolio_allocation.py` / `portfolio_alerts_view.py` / `portfolio_import_view.py` / `portfolio_risk.py` / `portfolio_accounts.py` / `portfolio_dialogs.py` (704 行)
- `backend/core/portfolio_store.py` (positions/transactions/alerts/accounts/audit)
- `backend/core/portfolio_calc.py` (XIRR/Sharpe/MaxDD/Brinson)
- `backend/core/portfolio_alerts.py` (7 规则)
- `backend/core/portfolio_import.py` (4 CSV 格式)

#### 7.1 总览 Tab (OverviewTab)

**功能 checklist (4 个必执行操作)**:

- [ ] **F1** 顶部 reload 按钮 → 重新拉所有数据
- [ ] **F2** Rebalance banner (信号变化提示, MVP stub 显示空)
- [ ] **F3** 汇总卡片: 总市值 / 总盈亏 / 持仓数 / 集中度
- [ ] **F4** 持仓表格: 代码 / 名称 / 数量 / 成本 / 现价 / 盈亏 / 盈亏% / 行业 / 板块

**数据 checklist**:

- [ ] **D1** React GET `/api/portfolio/positions` md5sum == Streamlit `portfolio_store.list_positions()` md5sum
- [ ] **D2** React GET `/api/portfolio/summary` 计算结果 == Streamlit `portfolio_calc.compute_portfolio_summary()` 结果

**UI checklist**:

- [ ] **U1** 4 汇总卡片网格布局 (2x2 或 4x1) 1:1
- [ ] **U2** 持仓表格斑马纹 + hover 高亮
- [ ] **U3** 盈亏正负色: 盈=绿, 亏=红
- [ ] **U4** 暗色 Bloomberg 风 1:1

#### 7.2 流水 Tab (TransactionsTab)

**功能 checklist (5 个必执行操作)**:

- [ ] **F1** 流水表格: 日期 / 代码 / 类型 (买/卖) / 数量 / 价格 / 金额 / 手续费
- [ ] **F2** 新增流水 dialog (shadcn Dialog + Form)
- [ ] **F3** 编辑流水 dialog (回填 + 提交)
- [ ] **F4** 删除流水 (确认 dialog → 删除)
- [ ] **F5** 筛选: ticker 下拉 / 类型下拉 / 日期范围

**数据 checklist**:

- [ ] **D1** CRUD 操作后, React GET `/api/portfolio/transactions` md5sum == Streamlit md5sum
- [ ] **D2** 筛选条件应用后, 列表 md5sum 1:1

**UI checklist**:

- [ ] **U1** 表格列顺序 1:1
- [ ] **U2** 类型徽章: 买=绿, 卖=红
- [ ] **U3** Dialog 居中 + 暗色背景

**错误 checklist**:

- [ ] **E1** 数量为负 → toast.error "❌ 数量必须为正"
- [ ] **E2** 日期格式错 → inline error
- [ ] **E3** ticker 校验失败 (6 位正则) → inline error

#### 7.3 配置 Tab (AllocationTab)

**功能 checklist (3 个必执行操作)**:

- [ ] **F1** 3 饼图: 行业 / 板块 / 大类 (ECharts)
- [ ] **F2** 集中度卡片: Top 1 / Top 3 / Top 5 占比
- [ ] **F3** 暗色 Bloomberg 风格饼图配色

**数据 checklist**:

- [ ] **D1** React GET `/api/portfolio/allocation` 返回的 3 个分组 md5sum == Streamlit `portfolio_calc.group_by_sector()` 等 md5sum
- [ ] **D2** 集中度百分比 1:1 (跟 `compute_concentration()` 一致)

#### 7.4 预警 Tab (AlertsTab)

**功能 checklist (5 个必执行操作)**:

- [ ] **F1** 预警列表: 类型 / ticker / 阈值 / 启用状态 / 创建时间
- [ ] **F2** 新增预警 dialog (7 种规则: price_above / price_below / pct_change / pnl_pct / take_profit / stop_loss / trailing_stop)
- [ ] **F3** 编辑预警 dialog
- [ ] **F4** 删除预警
- [ ] **F5** 启停 Switch (shadcn Switch)

**数据 checklist**:

- [ ] **D1** CRUD 操作后, React GET `/api/portfolio/alerts` md5sum == Streamlit md5sum
- [ ] **D2** 7 种规则字段 1:1 (跟 `AlertRule` dataclass 一致)

**错误 checklist**:

- [ ] **E1** 规则字段缺失 → inline error
- [ ] **E2** 同一 ticker + 同一规则重复 → toast.error "❌ 重复预警"

#### 7.5 导入导出 Tab (ImportExportTab)

**功能 checklist (6 个必执行操作)**:

- [ ] **F1** 上传 CSV (drag-drop 或 button)
- [ ] **F2** 格式检测 (东财 / 同花顺 / 雪球 / generic)
- [ ] **F3** 预览表格 (前 10 行 + 总数)
- [ ] **F4** 确认导入 (POST `/api/portfolio/import`)
- [ ] **F5** 导出 CSV (GET `/api/portfolio/export`)
- [ ] **F6** 模板下载 (4 种格式 sample)

**数据 checklist**:

- [ ] **D1** 导入成功后, 流水 / 持仓 md5sum 1:1
- [ ] **D2** 导出 CSV 内容 1:1 (UTF-8 BOM, Excel 友好)

**错误 checklist**:

- [ ] **E1** 文件过大 → toast.error "❌ 文件超过 10MB"
- [ ] **E2** 格式识别失败 → toast.error "❌ 无法识别 CSV 格式"
- [ ] **E3** 字段映射失败 → inline error + 行号定位

#### 7.6 收益风险 Tab (RiskReturnTab)

**功能 checklist (4 个必执行操作)**:

- [ ] **F1** 4 卡片: XIRR / Sharpe / MaxDD / Brinson
- [ ] **F2** Brinson 柱图 (ECharts)
- [ ] **F3** Bull/Bear 信号 banner (MVP stub 空)
- [ ] **F4** 空状态处理 (无流水时显示 "ℹ️ 添加交易流水后, 业绩归因才可用")

**数据 checklist**:

- [ ] **D1** React GET `/api/portfolio/brinson` md5sum == Streamlit `portfolio_calc.compute_brinson_attribution()` md5sum
- [ ] **D2** XIRR/Sharpe/MaxDD 数值 1:1

#### 7.7 账户管理 Tab (AccountsTab, v0.5.0 新增)

**功能 checklist (3 个必执行操作)**:

- [ ] **F1** 账户列表 (多账户: 默认账户 + 自定义)
- [ ] **F2** 新增账户 / 编辑账户 / 删除账户
- [ ] **F3** 切换当前账户 (持仓 / 流水按账户过滤)

**数据 checklist**:

- [ ] **D1** React GET `/api/portfolio/accounts` md5sum == Streamlit md5sum

#### 全局功能 checklist (跨 7 tabs)

- [ ] **G1** Tab 切换不丢失状态 (Streamlit 痛点: 切回 tab 状态丢失; React 用 TanStack Query cache 持久化)
- [ ] **G2** 7 个 tab 顺序 1:1: 总览 / 流水 / 配置 / 预警 / 导入导出 / 收益风险 / 账户管理
- [ ] **G3** tab 图标 1:1: 📊 / 📜 / 🎯 / 🔔 / 📥 / 📈 / 🏦

---

### Page 8. ⏰ 定时分析 (`schedule_panel.py` → `SchedulePage.tsx`)

#### 数据来源

- `web/components/schedule_panel.py` (355 行, v0.6.0)
- `web/components/schedule_dialogs.py` (369 行, 新增/编辑 modal)
- `backend/core/scheduler.py` (889 行, cron + 多渠道通知)
- `~/.tradingagents/schedules/scheduler.json`

#### 功能 checklist (Playwright e2e, **13 个必执行操作**)

- [ ] **F1** 页面打开 → GET `/api/schedule/list`, 列出所有 schedule
- [ ] **F2** 新建 schedule dialog: cron + ticker 源 + 通知渠道
- [ ] **F3** 编辑 schedule dialog (回填当前值)
- [ ] **F4** 删除 schedule (确认 dialog)
- [ ] **F5** 启停 Switch (POST `/api/schedule/{id}/toggle`)
- [ ] **F6** 立即运行按钮 (POST `/api/schedule/{id}/run-now`)
- [ ] **F7** cron 编辑器 (5-field: 分/时/日/月/周) 接受任意 cron 表达式
- [ ] **F8** ticker 源选择 (持仓 / 自选股 / 手动, RadioGroup)
- [ ] **F9** 通知渠道 4 Switch (WeCom / Email / Desktop / Log)
- [ ] **F10** 运行历史表格 (ticker / 时间 / 状态 / 通知状态, 最近 20 runs)
- [ ] **F11** 调度器启停 (全局开关, 后台 60s polling)
- [ ] **F12** 全局状态卡: 调度器状态 / 启用 schedule 数 / 今日 runs 数
- [ ] **F13** 10s 自动刷新 (后台 polling, 实时显示新 run)

#### 数据 checklist (hash 对比)

- [ ] **D1** React GET `/api/schedule/list` md5sum == Streamlit `scheduler.list_schedules()` md5sum
- [ ] **D2** CRUD 操作后 md5sum 1:1
- [ ] **D3** runs list md5sum 1:1 (跟 `scheduler.list_runs(schedule_id)` 一致)
- [ ] **D4** cron 字段顺序: `{minute, hour, day, month, weekday}` (5-field)

#### UI checklist (截图 diff)

- [ ] **U1** 4 段布局: 列表 / 编辑 dialog / 历史 / 全局状态 (跟 Streamlit 同)
- [ ] **U2** schedule 卡片: 名称 / cron / ticker 源 / 通知渠道 / 启停 / 操作
- [ ] **U3** 状态 emoji: OK=🟢, PARTIAL=🟡, ERROR=🔴, SKIPPED=⚪, NEVER=—, running=🔵
- [ ] **U4** cron 输入框 5 列网格布局
- [ ] **U5** ticker 源单选按钮组
- [ ] **U6** 通知渠道 Switch 横向排列 4 个

#### 错误 checklist

- [ ] **E1** cron 格式错 → inline error "❌ cron 表达式无效" + 字段红边
- [ ] **E2** ticker 源 = 手动 但没填 ticker → inline error "❌ 请至少填 1 个 ticker"
- [ ] **E3** 通知渠道全关 → toast.warning "⚠️ 至少启用 1 个通知渠道"
- [ ] **E4** 调度器未启动时立即运行 → toast.error "❌ 调度器未启动"

---

### Page 9. 📝 分析 (`app.py` main + `runner.py` → `AnalysisPage.tsx`)

> **主流程页**, 收尾页, 包含 SSE 实时进度 + 7 analyst 报告 tab

#### 数据来源

- `web/app.py` (447 行, main flow: ticker input → run_analysis_in_thread → progress → report)
- `web/runner.py` (301 行, 业务层分析运行器)
- `backend/api/analyze.py` (POST /api/analyze) + `result.py` (GET) + `sse.py` (SSE)

#### 功能 checklist (Playwright e2e, **11 个必执行操作**)

- [ ] **F1** 顶部表单: ticker 输入 + trade_date 选择 + LLM 配置 (复用 settings)
- [ ] **F2** 中文 ticker 自动解析 (复用 settings 页的 resolve_ticker)
- [ ] **F3** 启动按钮 → POST `/api/analyze` → 跳到进度 section
- [ ] **F4** SSE 实时进度: PIPELINE_STAGES 7 analyst + debate + risk + trader 阶段展开
- [ ] **F5** 进度条 (shadcn Progress) 显示整体进度 0-100%
- [ ] **F6** 每个阶段状态: pending / running / done / error (4 种图标)
- [ ] **F7** 完成后跳到报告 section, 显示完整 Markdown 报告
- [ ] **F8** 报告 tab: 7 analyst 报告 + 辩论总结 + 风险辩论 + trader 决策
- [ ] **F9** Bull/Bear 信号徽章: 🟢 买入 / 🔴 卖出 / 🟡 持有 / 🟢 超配 / 🔴 低配
- [ ] **F10** "查看历史" 按钮 → 跳到 `📋 历史` 页 (`NavLink`)
- [ ] **F11** 错误重试按钮 (失败时显示)

#### 数据 checklist (hash 对比)

- [ ] **D1** React POST `/api/analyze` 创建的 task dict md5sum == Streamlit `run_analysis_in_thread()` 内部 task md5sum
- [ ] **D2** 进度 SSE event 顺序: `market_analyst → sentiment_analyst → ... → trader` md5sum 1:1
- [ ] **D3** 报告 Markdown 内容 md5sum == Streamlit 落盘的 `~/.tradingagents/logs/history/{id}.json` 的 `report` 字段 md5sum

#### UI checklist (截图 diff)

- [ ] **U1** 3 section 布局: 输入表单 (top) / 进度 (middle) / 报告 (bottom)
- [ ] **U2** ticker 输入框 + date picker + LLM select 横向排列
- [ ] **U3** 7 阶段列表垂直展开, 每个阶段 icon + 名称 + 耗时
- [ ] **U4** 报告 Markdown 渲染 + 代码块语法高亮
- [ ] **U5** tab 切换动画 1:1

#### 错误 checklist

- [ ] **E1** ticker 不存在 → inline error "⚠️ 股票代码不存在"
- [ ] **E2** LLM 未配置 → toast.error "❌ 请先配置 LLM (去设置页)"
- [ ] **E3** 分析中 SSE 断连 → "🔄 重新连接..." + 自动重连, 不丢失进度
- [ ] **E4** 分析失败 → 阶段状态变 ❌ + 错误原因显示 + 重试按钮
- [ ] **E5** trade_date > today → inline error "❌ 日期超出范围"

---

## 5. Parity Check 执行流程 (Execution Flow)

### 5.1 Page 阶段 (每页迁移完)

每页 Phase 2.X 完成时, 跑以下 5 步 parity check, 全绿才计入"完成":

```bash
# Step 1: Patch 修复
# (前端代码 + 后端 API + Playwright e2e 写完, commit 前)

# Step 2: Verify 自动化验证
cd frontend
npm run build                          # 验证 build OK
npx vitest run                         # 单元测试全绿
npx playwright test <page>.spec.ts     # 该页 e2e 全绿

# 数据 parity
cd ..
python scripts/parity_check.py --page <page>   # 数据 hash 对比 OK

# 视觉 parity
python scripts/parity_visual.py --page <page>  # 截图 diff < 1% OK

# 性能 parity
python scripts/parity_perf.py --page <page>    # Lighthouse Performance ≥ 80 OK

# Step 3: 用户手动验证 (硬要求)
# 用户打开 React 页 + Streamlit 页, 对比:
#   - 按钮位置/图标/文案
#   - 表单字段/校验
#   - 错误信息/位置
#   - 数据值/精度
# 反馈 OK 或具体 diff → 用户明确回复 "✅ parity 通过" 或 "❌ 有差异, 见: ..."

# Step 4: 全部绿 + 用户确认 → 计入完成 → 进下一页
```

#### 通过标准 (Page 阶段)

- ✅ e2e 0 失败
- ✅ 数据 hash md5sum 1:1
- ✅ 截图 diff < 1% 像素
- ✅ Lighthouse Performance ≥ 80
- ✅ 用户明确文字回复 "✅ parity 通过"

任一 ❌ → 该页任务**不算完成**, 不进 Phase 2 下一项。

---

### 5.2 整体 Phase 2 收尾 (所有 9 页迁完)

9 页全部 ✅ 后, 跑一次**整体 parity check** (跨页一致性):

```bash
# 跨页一致性
python scripts/parity_check.py                      # 全 9 页 hash 对比
python scripts/parity_visual.py                     # 全 9 页截图 diff
python scripts/parity_perf.py                       # 全 9 页 Lighthouse
python scripts/parity_fault_inject.py               # 10 个错误场景 fault injection

# Playwright e2e 跨页串行
cd frontend
npx playwright test                                  # 全部 9 spec 通过

# pytest 业务测试
cd ..
pytest tests/ -q                                    # 757 passed (0 回归)

# Streamlit 三端并行 7 天无关键问题
# (从 Phase 2 完 → Phase 3 触发检查期间)
```

#### 通过标准 (整体)

- ✅ 全部 9 页 parity check 全绿
- ✅ 跨页一致性 (sidebar 9 入口切换无状态丢失 / 无重渲染卡顿)
- ✅ pytest 757 passed
- ✅ Streamlit fallback 端口 7 天无关键问题
- ✅ 用户手动跑过 9 页 (用户截图 / 录屏 / 文字确认)

任一 ❌ → Phase 2 收尾**不算完成**, 不进 Phase 3 触发检查。

---

### 5.3 时序图

```
Phase 2.1 设置 (Phase 1 已做)
   └─ parity ✅ (用户确认)

Phase 2.2 历史
   ├─ 写代码 (frontend + backend)
   ├─ Playwright e2e 写
   ├─ parity check 5 步全绿
   └─ 用户确认 → ✅ → 进 2.3

Phase 2.3 日志
   └─ 同上流程

...

Phase 2.9 分析
   └─ 同上流程

Phase 2.10 整体 parity check
   ├─ 9 页串行 parity
   ├─ pytest 757
   ├─ 7 天 fallback
   └─ 用户全 9 页手动验证

Phase 3 触发条件检查
   ├─ 9 页 ✅
   ├─ Playwright e2e ✅
   ├─ pytest 757 ✅
   ├─ 用户确认 ✅
   ├─ 7 天无关键问题 ✅
   └─ 用户明确下令 → 进 Phase 3
```

---

## 6. 失败时怎么办 (Failure Handling)

### 6.1 一般原则

- **parity check fail → 不能进 Phase 3 删除 streamlit** (硬约束)
- **个别 parity 维度可允许 0.5% 容忍**, 但功能/数据**必须 100% 一致**
- **若功能无法 1:1** (因 React/state 架构不同), spec 需明确:
  - "diff 原因 + 用户确认接受" 写到 `parity-results/{page}-diff.md`
  - 用户明确回复 "✅ 接受此 diff" → 该 diff 例外, 其他维度仍要求 1:1

### 6.2 失败分类处理

#### 类别 A: 功能差异 (Functional Diff)

- **症状**: Streamlit 能做的操作, React 缺失 / 行为不同
- **处理**:
  1. 立即修复 React 代码 (补功能)
  2. 跑 e2e 验证
  3. 用户确认 → parity 通过
- **不允许**: 跳过功能 / 标记 "暂不支持" (除非用户明确接受)

#### 类别 B: 数据差异 (Data Diff)

- **症状**: hash md5sum 不匹配, React 拉到的数据字段 / 值跟 Streamlit 不一致
- **处理**:
  1. 立即修复 (通常是 API endpoint 没透传所有字段, 或字段顺序错)
  2. 重跑 parity_check.py
  3. hash 全等 → parity 通过
- **不允许**: 数据字段缺失 / 顺序错 / 精度丢 (e.g. `1.5` → `1`)

#### 类别 C: 视觉差异 (Visual Diff)

- **症状**: 截图 diff ≥ 1% 像素
- **处理**:
  1. 找出差异区域 (e.g. 按钮 hover 色不对)
  2. 修复 CSS token / 颜色
  3. 重跑 parity_visual.py
  4. 像素差 < 1% → parity 通过
- **容忍范围**: padding/margin ±2px 可接受; 颜色 / 字体 / 图标 不可妥协

#### 类别 D: 性能差异 (Performance Diff)

- **症状**: React 比 Streamlit 慢 100%+ (e.g. 首屏 8s vs Streamlit 3s)
- **处理**:
  1. Profile 找瓶颈 (e.g. bundle 大 / chart lib 重 / 不必要的 re-render)
  2. 优化 (code splitting / lazy load / memo)
  3. 重跑 parity_perf.py
  4. React ≤ 2× Streamlit → parity 通过
- **不允许**: 慢 200%+ (Streamlit 3s → React 9s)

#### 类别 E: 错误差异 (Error Diff)

- **症状**: 同错误场景, React 报错文案 / 位置 / 样式跟 Streamlit 不一致
- **处理**:
  1. 修复错误处理代码 (toast 文案 / 位置 / retry 按钮)
  2. 重跑 parity_fault_inject.py
  3. 错误信息 1:1 → parity 通过
- **不允许**: 错误信息丢失 / 改文案 / 不显示错误

### 6.3 不可接受的妥协 (Hard NO)

- ❌ "React 实现不了 X 功能, 删 X" (除非用户明确同意删功能)
- ❌ "数据字段 React 多返回 Y, Streamlit 没 Y, 没问题" (字段顺序 / 字段值必须 1:1)
- ❌ "Streamlit 旧, React 用现代风更好看" (暗色 Bloomberg 风 1:1, 不一味"现代化")
- ❌ "性能差一点, 用户感知不到" (≤ 100% 慢可接受, 超过不接受)

### 6.4 失败文档化

每页 parity check 失败时, 必须写 `parity-results/{page}-diff.md`:

```markdown
# {Page} Parity Diff Log

## Diff 1: {日期}
- 维度: 功能 / 数据 / UI / 性能 / 错误
- 差异: Streamlit 显示 X, React 显示 Y
- 根因: ...
- 处理: ...
- 状态: ✅ 已修复 / ⏳ 用户接受 / ❌ 待修复

## Diff 2: ...
```

---

## 7. 总结: Parity 是 Phase 3 的守门人

> **没有 parity-check 全绿 = 没有 Phase 3 删除 streamlit 的资格。**

```
Phase 1 完成
  ↓
Phase 2 每页 parity 全绿 (Patch + Verify + 用户确认)
  ↓
Phase 2 整体 parity (9 页 + 7 天 fallback)
  ↓
Phase 3 触发条件 6 条全部 ✅
  ↓
Phase 3 执行 (删 streamlit)
  ↓
v0.7.0 发布
```

**parity 是连接 Phase 2 迁移质量 和 Phase 3 删除动作 的关键守门环节**。本 spec 通过明确 5 维度 / 3 工具 / 9 页 checklist / 执行流程 / 失败处理, 保证迁移不是"复制 UI"而是"功能完全等价"。

---

*本文档是 spec v2 增量, 跟 proposal.md / design.md / tasks.md 互为补充。详细执行脚本见 `scripts/parity_check.py` / `parity_visual.py` / `parity_perf.py` / `parity_fault_inject.py` (Phase 1 后由用户 / Claude 实现)。*

*Spec v2 结束。下一步: 用户确认后, Phase 1 实施 + parity tooling 脚本编写。*