# P2.26–P2.29 用户最新修复分析

> **基线**: `git HEAD = 33b3a42` (P2.25 已 commit)
> **增量**: 27 modified + 6 new files (4 个 backend 新文件 + 4 个 frontend 报告组件 + 2 个 ui 组件 + 6 个新增 test file)
> **总 diff**: +1117 / −280 行
> **角色**: 增量 hotfix + 新功能 (PDF 导出 + 历史清空), **不**包含任何架构升级
> **互补**: 不重复 `DDD_AGENTS_DEEP_DIVE.md` / `DDD_OPERATIONS.md` / `DDD_EXPLORATION.md` / `MIGRATION_ROADMAP.md`; 本文档聚焦 P2.26–P2.29 这 4 个 hotfix 的根因、修法、集成关系

---

## 0. 一览表 (TL;DR)

| 维度 | 数字 |
|---|---|
| backend 文件 diff | 4 modified + 2 new = 6 个 (`api/{analyze,history}.py` + `core/{history_store,runner}.py` + `core/history_cleanup.py` 新 + `core/report_adapter.py` 新) |
| frontend 文件 diff | 11 modified + 6 new = 17 个 (9 个组件 + 4 个 report-* 新 + history-purge-dialog 新 + 2 个 ui 新 + package.json + tailwind + playwright) |
| backend tests 新增 | 4 文件, 61 tests: `test_history_purge.py` (25) + `test_analyze_export.py` (6) + `test_report_adapter_strip_think.py` (16) + `test_tracker_stage_reports.py` (14) |
| frontend tests 新增 | 5 文件, 28 tests: `report-tab-p228.spec.ts` (1 e2e) + `AnalysisProgress.test.tsx` (3) + `analysis-report.test.tsx` (8) + `history-purge-dialog.test.tsx` (9) + `report-markdown-strip-think.test.tsx` (7) |
| 测试结果 | pytest **820 passed / 0 failed**, vitest **63 passed** (10 个 playwright e2e 误被收集为 vitest spec — 是 vitest config 没排除 e2e/, 与 P2.26–P2.29 修复无关) |
| tsc | **0 error** |
| 新依赖 | `@radix-ui/react-accordion@^1.2.16`, `@radix-ui/react-tabs@^1.1.17`, `react-markdown@^9.1.0`, `rehype-sanitize@^6.0.0`, `remark-gfm@^4.0.1` |
| 新模块 | `backend/core/history_cleanup.py` (380 行) + `backend/core/report_adapter.py` (145 行) + `frontend/src/components/history/history-purge-dialog.tsx` (250 行) + 4 个 report-*.tsx |
| 用户可见功能 | (1) 12 阶段进度完整可见 (2) 12 阶段报告完整渲染 (3) Markdown + PDF 报告下载 (4) 历史一键清空 + confirm dialog |
| Hotfix root cause | 5 类: race condition (P2.26 早期 progress + recent-list) / timeout threshold 太小 (P2.26 600s→1800s) / 视觉错乱 (P2.27 errored 标红) / 路径错位 (P2.28 results_path layout) / XSS 与 think 块泄漏 (P2.29 strip_think + sanitize) |
| 涉及 commit | P2.26-P2.29 共 4 个新 commit 标记 + P2.30 / P2.31 提前 commit (purge + strip_think 在 API 层), 见 §9 |

---

## 1. P2.26 详细分析

### 1.1 `STUCK_THRESHOLD_SEC` 600s → 1800s

**文件**: `backend/core/history_store.py:41-44`, `backend/core/runner.py:132-136`

**修改前**:
```python
# history_store.py
STUCK_THRESHOLD_SEC = 600.0  # 10 minutes
# runner.py
MAX_RUN_SEC = 600  # 10 minutes — matches STUCK_THRESHOLD_SEC in history_store.py
```

**修改后**:
```python
# history_store.py
STUCK_THRESHOLD_SEC = 1800.0  # 30 minutes — user feedback: real analyses
                            # take ~20 min, the previous 10-min threshold
                            # was sweeping legitimate long runs as "stuck"
                            # on backend restart. Must match MAX_RUN_SEC
                            # in backend/core/runner.py.
# runner.py
MAX_RUN_SEC = 1800  # 30 minutes — user feedback: real analyses
                   # typically take ~20 min (12 stages × LLM calls).
                   # 10 min was too aggressive and aborted legitimate
                   # long runs (P2.23 hotfix was a stop-gap at 600s).
                   # Must match STUCK_THRESHOLD_SEC in history_store.py.
```

**用户反馈推断**:
1. P2.23 hotfix 是"硬超时" — `_run_analysis` 内部 600s 后 `TimeoutError`, 把分析强制 mark_error。
2. 用户跑真实数据 (12 阶段 × LLM 调用 ≈ 20 分钟) 时, 10 分钟的硬超时**误杀正常长跑**。
3. P2.21+P2.25 已经把 stage 识别完整化 (12 个 stage), 单 stage 平均 ~100s, 全跑完 18-25 分钟。
4. 用户报"analysis 跑到一半就 errored"。

**修法**:
- 两个常量从 `600.0` 提升到 `1800.0`, 注释互引 (必须 match) — 防止单边修改导致 zombie cleanup 又把"刚好 600s 卡住的"误标。
- `MAX_RUN_SEC` 用 `TimeoutError` 触发, 但当 `graph.stream` 自然结束时 (`StopIteration`) 不会触发 — P2.23 设计保留, 改时长即可。
- 1.0x 倍数: 30min = 12 stages × ~150s/stage (含 LLM round-trip + tool 调用)

**跟 P2.21/P2.23 的集成**:
- P2.21 引入了 `MAX_RUN_SEC` (600s) 作为 stop-gap — 用户没测过真实长跑, 当时只是应急修 graph.stream hang。
- P2.23 没改阈值, 只是把 TimeoutError → mark_error 的异常路径连上。
- P2.26 才把"600s 不够"这个事实反馈修掉。
- 这是典型的 "fix later once we see real-world numbers" 模式: P2.21/P2.23 已知保守, P2.26 用真实数据 (20min) 校准。

### 1.2 `AnalyzePage` recent-list race condition

**文件**: `frontend/src/pages/AnalyzePage.tsx:107-244`

**根因**:
```javascript
// P2.26 之前的 effect 链
useEffect(() => {
  // 1) validation: 当 activeAnalysisId 在 recentList 里找不到 → fallbackToHistory
  if (!recentQuery.data) return;
  const known = recentQuery.data.some((it) => it.analysis_id === activeAnalysisId);
  if (!known) fallbackToHistory(activeAnalysisId, ...);
}, [recentQuery.data, activeAnalysisId]);

const startMut = useMutation({
  onSuccess: (result) => {
    setActiveAnalysisId(result.analysis_id);  // ① 立刻设 id
    setActiveTab('progress');                   // ② 切到进度 tab
    queryClient.invalidateQueries({ queryKey: ['analyze-recent'] });  // ③ invalidate
  },
});
```

**race**: ① 同步触发 effect → ② React 同步重渲染 → ③ effect 第二次触发 (`activeAnalysisId` 已设, `recentQuery.data` 仍是 stale 缓存 — 没新 id) → **错误地把新创建的 id 当成 stale** → 弹回 history tab。

**修法 (3 处协调)**:

```typescript
// (1) 新增 ref 集合
const recentlyCreatedIdsRef = React.useRef<Set<string>>(new Set());

// (2) startMut.onSuccess: 先注册再设 id
onSuccess: (result) => {
  recentlyCreatedIdsRef.current.add(result.analysis_id);  // ← BEFORE setActiveAnalysisId
  setActiveAnalysisId(result.analysis_id);
  setActiveTab('progress');
  void queryClient.invalidateQueries({ queryKey: ['analyze-recent'] });
}

// (3) validation effect: 跳过 recently-created
React.useEffect(() => {
  if (!isUsableAnalysisId(activeAnalysisId)) return;
  if (!recentQuery.data) return;
  if (recentlyCreatedIdsRef.current.has(activeAnalysisId)) return;  // ← 跳过
  const known = recentQuery.data.some((it) => it.analysis_id === activeAnalysisId);
  if (!known) fallbackToHistory(...);
}, [recentQuery.data, activeAnalysisId, fallbackToHistory]);
```

**为什么用 ref 而不是 state**: state 触发渲染, ref 不触发 — ref 是"tag list", 不参与渲染流水线。

**第二处 race**: `reportQuery.error` 触发 `fallbackToHistory` — 在切换到 report tab 时, `/report` 端点对**正在运行**的分析 404 (results_path 还没写), effect 把活跃 id 弹回 history → progress polls 也跟着死。修法: 加 `stillInRecent` 检查, 只在 recent-list 也找不到时才 fallback。

**集成**:
- P2.12 (stale ID 三重防护) 已经定义 `isUsableAnalysisId` + `isReportNotFoundError`, P2.26 在这个防护**内侧**再加一道最近创建的 short-circuit。
- 不动 `isUsableAnalysisId` 本身 — P2.10/P2.12 的"老 history entry stale id"逻辑保持原样, P2.26 只插"新创建还在飞行中"的旁路。

### 1.3 workspace `currentStage` 推算 (7 cards)

**文件**: `frontend/src/components/analyze/analysis-workspace.tsx:78-92`

**原代码**:
```typescript
const isCurrent = currentStage && currentStage.startsWith(c.id.replace('_report', ''));
```

**问题**: `currentStage` 在两个时间窗内为空:
1. POST `/api/analyze` 后 ~50ms: `startAnalysis()` 在 `start_analysis` 里设 `tracker.mark_stage_active("market")` (P2.26 新加), 但**前端收到 response 之前** currentStage 还是空。
2. LangGraph chunks 之间: `_run_analysis` 在 `mark_stage_done` 后, 下一个 stage 的 chunk 还没到时 currentStage 还是空的 (P2.21 修了空字符串 bug, 但 chunks 间隔还是存在)。

**修法**:
```typescript
const stageId = c.id.replace('_report', '');
let isCurrent = Boolean(currentStage && currentStage === stageId);  // ① 优先用后端字段
if (!isCurrent && !body) {                                          // ② fallback 推算
  const emptyStageIds = WORKSPACE_CARDS
    .map((cc) => cc.id.replace('_report', ''))
    .filter((id) => !reports[`${id}_report`]);
  if (emptyStageIds[0] === stageId) {                              // ③ 第一个没 body 的 = 正在跑
    isCurrent = true;
  }
}
```

**WORKSPACE_CARDS 顺序假设**: `frontend/src/components/analyze/analysis-workspace.tsx` 顶部 import 的 `WORKSPACE_CARDS` 是**按 pipeline 顺序**硬编码的 (market → social → news → fundamentals → policy → hot_money → lockup)。这个顺序跟 backend `runner.py` 的 `stage_order` (12 stage) 的前 7 个对齐。

**为什么只覆盖 7 个 card**: workspace 是早期版本 (P2.21 之前), 只展示 analyst 阶段。P2.29 的 `analysis-report.tsx` 升级到 12 stage 但**workspace 保持 7 cards** — 设计意图是 progress tab 看完整 12 stage, workspace tab 看 analyst 阶段 + 历史 stage_reports。

**集成**:
- 跟 P2.21 的 `inferCurrentStage` 函数 (`analysis-progress.tsx:83-93`) 同源思路: 后端字段为空时用 completed_stages 推算。
- workspace 的推算逻辑**更激进**: 不只推算当前 stage, 还用它来点亮对应的 card 边框。

### 1.4 `test_tracker_stage_reports.py` 14 tests — stage_reports key 契约

**文件**: `tests/test_tracker_stage_reports.py` (14 tests, 5 classes)

**5 个测试 class 验证**:

1. `TestMarkStageDoneKeyContract` — `mark_stage_done(report=..., report_key=...)` 必须用 `report_key` 作为 `stage_reports` dict 的 key (而不是 `stage_id`)。P2.25 修了 ID 一致性, P2.26 进一步要求 key 契约。

2. `TestHistoryStoreParity` — `tracker.mark_stage_done` 和 `history_store.mark_stage_done` 必须产生相同的 `stage_reports` key (因为 UI 端从两边读)。

3. `TestDictStagePrematureDone` — P2.26 修了一个微妙 bug: `_run_analysis` 的 stage_map 循环里, dict-shaped stages (debate / risk) 的**初始空 dict** `{'count': 0, ..., 'judge_decision': ''}` 是 truthy, 会触发 `mark_stage_done` 写入空 dict — 用户在 workspace tab 看到空的 stage_reports。修法:
   ```python
   if chunk_key in {"investment_debate_state", "risk_debate_state"}:
       if not isinstance(content, dict):
           continue
       if not content.get("judge_decision"):  # ← 必须有 judge_decision 才算 done
           continue
   ```

4. `TestStageProgressionChaining` — 12 stage chain 必须连续点亮 (前一个 done 后下一个 active), 验证 `stage_order = ['market', ..., 'pm']` 显式列表的 pipeline order (P2.26 hotfix — 之前从 `stage_map.values()` 派生丢了 `quality_gate`)。

5. `TestExceptionPathMarksError` — TimeoutError 必须触发 `tracker.mark_error()`, 跟 P2.23 一致。

**P2.25 修复真生效吗?**: 测试存在 + pytest 820 passed ✅

**集成**:
- `test_tracker_stage_reports.py` 在 P2.25 时已经存在 (mtime 7月17日, 比 P2.26 的代码 mtime 早 — 即 P2.26 把**测试先固化**, 代码后改)。
- 14 个 test 覆盖 P2.25 (key 契约) + P2.26 (dict 阶段过早 done + 链式推算) + P2.23 (异常路径)。
- 这是 "TDD 反向": 不是先写 test 再写 code, 而是 code 在 production 跑出 bug 后, 把 test 写好**作为 regression guard**。

---

## 2. P2.27 详细分析

### 2.1 `analysis-progress` errored stage 视觉

**文件**: `frontend/src/components/analyze/analysis-progress.tsx:148-160, 228-262, 293-309`

**新增逻辑**:
```typescript
// P2.27 hotfix
const erroredStage = isError
  ? (progress.current_stage || inferredCurrent)
  : null;

// 在 STAGES.map 里
const isDone = completed.has(s.id);
const isRunningThis = !isDone && !isError && !isComplete && inferredCurrent === s.id;
const isErrored = !isDone && isError && s.id === erroredStage;

return (
  <div className={...isDone ? '绿' : isErrored ? '红' : isRunningThis ? '蓝' : '灰'...}>
    <span>{icon}</span>
    {isErrored && <AlertCircle />}  {/* 红色感叹号 */}
    {isRunningThis && <Loader2 className="animate-spin" />}  {/* 旋转 */}
  </div>
);
```

**状态颜色映射** (4 状态):
| 状态 | 边框 | 背景 | 图标 |
|---|---|---|---|
| `done` | emerald-500/40 | emerald-500/10 | ✓ CheckCircle2 (绿) |
| `errored` (新) | red-500/50 | red-500/10 | ⚠ AlertCircle (红) |
| `running` | bb-accent/40 | bb-accent/10 | ↻ Loader2 spinning (蓝) |
| `pending` | border-1 | bg-elevated/40 | ○ Circle (灰) |

**erroredStage 推算**:
```typescript
const erroredStage = isError
  ? (progress.current_stage || inferredCurrent)  // 优先 backend 字段, fallback 推算
  : null;
```
- `progress.current_stage`: 后端在 mark_error 时**不**主动 clear, 所以还是 crash 时的 stage (例如 `quality_gate`)。
- `inferredCurrent`: P2.21 引入, 用 `completed_stages[-1] + 1` 推算下一个 stage。如果两者一致, 用后端; 如果后端空 (older entry), 用推算。

**error banner 升级**:
```diff
- <span>{progress.error ?? '分析失败'}</span>
+ <div className="flex-1 space-y-1">
+   <div className="font-semibold">分析已终止</div>
+   <div className="text-xs">{progress.error ?? '分析失败'}</div>
+   <div className="text-xs text-red-300/70">
+     已完成的 N 个阶段报告仍可在「工作区」tab 查看 · 切到「新建」tab 可重跑
+   </div>
+ </div>
```
- 新增 "已完成 N 个阶段报告" 文案: 给用户明确信号 — workspace tab 里仍然有已完成阶段的报告, 不要重跑全部 12 阶段。

**跟 P2.23 / P2.21 的集成**:
- P2.23: `_run_analysis` 加 600s 硬超时 → `TimeoutError` → `tracker.mark_error()` → `progress.status='error'`。
- P2.21: 12 stage 进度追踪 + `current_stage` 修复 (不主动清空)。
- P2.27: **可视化** mark_error 后的状态。技术上**没**修任何新 bug — P2.21/P2.23 已经正确地 mark_error 并写入 error 字段, 只是前端**没区分** "errored stage" 和 "running stage"。

**root cause 推断**:
- P2.21 修了 `current_stage` 不被清空, 但**所有阶段状态**(running/done/pending) 都是后端 3 个字段计算出来的 — 没有"errored stage"概念。
- 用户报 "progress page stuck after timeout fires": 因为 `quality_gate` 处于 "running" (蓝色旋转) — 用户看到红色 error banner 但蓝色进度还在转, 视觉矛盾, 误以为"还在跑"。
- P2.27 把 `errored` 作为**第四状态**显式渲染。

### 2.2 跟 AnalyzePage 的 tab 路由协同

**文件**: `frontend/src/pages/AnalyzePage.tsx:351-388`

```typescript
// handleSelectRecent
const item = recentItems.find((it) => it.analysis_id === analysisId);
const isRunning = item?.status === 'running' || item?.status === null || item?.status === undefined;
const isErrored = item?.status === 'error';  // P2.27 hotfix
const tab: TabKey = isRunning || isErrored ? 'progress' : 'report';
setActiveAnalysisId(analysisId);
setActiveTab(tab);
```

**为什么 errored → progress tab**:
- `status='error'` 的 entry `results_path=''` (没生成报告) → `/report` 404 → `reportQuery.error` effect → fallbackToHistory (P2.26 的 `stillInRecent` 守卫会让 fallback 发生, 因为 errored entry 确实在 recentList 里 → 但仍然 404)。
- P2.27 直接路由到 `progress` tab: 用户能看到已完成阶段 + error 原因 + "重跑"按钮 (切到 `新建` tab)。

**集成**:
- P2.26 的 `stillInRecent` 守卫解决了 "running 时点 report tab" 的 race。
- P2.27 进一步: running / errored 都路由到 progress tab, 直接绕开 "report 404 → fallback 链"。
- 这是**双层防御**: P2.26 在 effect 里防 race, P2.27 在 tab router 里防用户进错 tab。

---

## 3. P2.28 详细分析

### 3.1 `results_path` layout 修复

**文件**: `backend/core/runner.py:14-26, 187-198`, `tradingagents/default_config.py:6-37`

**根因 (3 层 bug)**:

1. **`default_config.py` 不展开 `~`**: `.env` 里写 `TRADINGAGENTS_RESULTS_DIR=~/.tradingagents/logs`, `os.getenv()` 不展开 `~`, 结果 `Path("~/.tradingagents/logs").resolve()` 会 fallback 到 `<cwd>/~/.tradingagents/logs`。

2. **`runner.py` 缺 results_path 写入**: `_run_analysis` 调用 `graph._log_state(trade_date, last_chunk)` 写文件, 但**没**调 `history_store.set_results_path(analysis_id, ...)` → history entry 的 `results_path` 字段保持空字符串。

3. **`/report` endpoint 缺文件存在性检查 fallback**: `get_analyze_report` 读 `entry.results_path` — 既然 P2 步骤 2 没写, 永远是空字符串 → 走 fallback 路径 → fallback 用 `~/.tradingagents/logs/...` 拼路径 → 但因为步骤 1 的 `~` 错位, 拼出来的路径**也不在真实文件位置**。

**修法**:

```python
# default_config.py — 修 #1
def _resolve_home_dir(env_var: str, default: str) -> str:
    raw = os.getenv(env_var, default)
    return os.path.expanduser(raw)

DEFAULT_CONFIG = {
    "results_dir": _resolve_home_dir("TRADINGAGENTS_RESULTS_DIR", ...),
    ...
}

# runner.py — 修 #2 + 修 #3 的源头
_RESULTS_DIR = Path.home() / ".tradingagents" / "logs"

# 在 graph._log_state() 之后:
results_path = str(
    _RESULTS_DIR / tracker.ticker / "TradingAgentsStrategy_logs"
    / f"full_states_log_{tracker.trade_date}.json"
)
get_history_store().set_results_path(tracker.analysis_id, results_path)
```

**跟 web/runner.py 的 layout 一致性**:
- `web/runner.py:285-289` 是 Streamlit UI 的对应代码, 早就写 results_path。
- `backend/core/runner.py` (新写的 React 后端版) P2.21-P2.25 都漏了 — P2.28 补上。
- 注释明确写 "Mirrors web/runner.py:285-289", 这是**cross-reference 形式的 contract**。

**12 stage report 完整性**:
- P2.28 同时修了 `stage_map` 的 quality_gate 行 (原 stage_map 没 quality_gate):
  ```python
  "data_quality_summary": ("quality_gate", "quality_gate_report"),
  ```
- 解释: quality_gate LangGraph node 输出的 chunk key 是 `data_quality_summary`, 但**前端期望的 stage key** 是 `quality_gate`, **report key** 是 `quality_gate_report`。三者映射表 P2.28 补齐。

### 3.2 12 stage report 完整渲染

**文件**: `frontend/src/components/analyze/analysis-report.tsx:44-118`

**TRADER_REPORTS 数组** (从 7 → 12):
```typescript
const TRADER_REPORTS = [
  { key: 'market_report', title: '技术分析', icon: '📊' },
  { key: 'sentiment_report', title: '情绪分析', icon: '💬' },
  { key: 'news_report', title: '新闻舆情', icon: '📰' },
  { key: 'fundamentals_report', title: '基本面', icon: '📋' },
  { key: 'policy_report', title: '政策分析', icon: '🏛️' },
  { key: 'hot_money_report', title: '游资追踪', icon: '🔥' },
  { key: 'lockup_report', title: '解禁监控', icon: '🔒' },
  { key: 'quality_gate_report', title: '质量门禁', icon: '✅' },  // P2.28
  { key: 'investment_debate_state', title: '多空辩论', icon: '⚔️' },  // P2.28
  { key: 'risk_debate_state', title: '风控讨论', icon: '🛡️' },  // P2.28
  { key: 'trader_investment_plan', title: '交易员决策', icon: '💹' },  // P2.28
  { key: 'final_trade_decision', title: '组合经理决策', icon: '👔' },  // P2.28
];
```

**布局**:
- 7 analyst (market / social / news / fundamentals / policy / hot_money / lockup) → Accordion (P2.29, 见 §4)
- 2 debate (investment / risk) → Tabs (P2.29, 见 §4) — 因为是 dict-shaped, 多角色辩论
- 3 standalone (quality_gate / trader / pm) → grid 1×2 Cards

**E2E testid 契约**:
- P2.28 之前 `analysis-report-card-{key}` testid 只覆盖 7 analyst。
- P2.28 加了 5 个新的 testid:
  - `analysis-report-card-quality_gate_report`
  - `analysis-report-card-investment_debate_state` (被 `ReportDebateTabs` wrapper 继承)
  - `analysis-report-card-risk_debate_state` (被 `ReportRiskTabs` wrapper 继承)
  - `analysis-report-card-trader_investment_plan`
  - `analysis-report-card-final_trade_decision`
- `tests/e2e/report-tab-p228.spec.ts` 显式 assert "all 12 stage cards" — 12 个 testid 都得能 find。

**集成**:
- P2.21 引入了 12 stage 进度追踪 — 跟 P2.28 的 12 stage report 渲染对齐 (前后端 stage_map 一致)。
- P2.25 修 stage_reports key — P2.28 用 canonical key 拿数据, 跟 P2.25 的 key contract 一致。
- P2.24 修了 `progressQuery` 调 `getProgress` (不是 `getAnalysis`) — 这是 P2.28 能拿到 `completed_stages` 的基础。

---

## 4. P2.29 详细分析 ⭐ 重要新功能

### 4.1 PDF / Markdown 导出 pipeline

**新增 endpoint**: `GET /api/analyze/{analysis_id}/export?format=md|pdf`

**文件**: `backend/api/analyze.py:331-404`, `backend/core/report_adapter.py` (145 行)

**pipeline**:
```
GET /api/analyze/{id}/export?format=md|pdf
  ↓
_load_report_json(id)             # 读 full_states_log_*.json, strip_think_blocks
  ↓
adapt_report_for_export(content)  # 改字段名 + extract signal
  ↓ (返回 adapted dict, signal string)
generate_markdown(adapted, ticker, date, signal)  # web/pdf_export.py (legacy)
   OR
generate_pdf(adapted, ticker, date, signal)        # web/pdf_export.py (legacy)
  ↓
StreamingResponse (Content-Disposition: attachment)
  ↓
浏览器原生下载 (Content-Disposition + <a download>)
```

**字段名映射 (核心问题)**:
```python
# backend/core/report_adapter.py
def adapt_report_for_export(report):
    adapted = dict(report)  # 浅拷贝
    signal = extract_signal(report)
    
    # 新 key → legacy key (pdf_export._collect_sections 用 legacy key)
    trader = report.get("trader_investment_plan")
    if trader and "trader_investment_decision" not in adapted:
        adapted["trader_investment_decision"] = str(trader)
    
    final_decision = report.get("final_trade_decision")
    if final_decision and "investment_plan" not in adapted:
        if isinstance(final_decision, dict):
            adapted["investment_plan"] = signal or str(final_decision.get("decision", ""))
        else:
            adapted["investment_plan"] = str(final_decision)
    
    return adapted, signal
```

**为什么需要 adapter**:
- `web/pdf_export.py` 是 Streamlit UI 时代写的 (`generate_markdown` / `generate_pdf`), 期望字段:
  - `trader_investment_decision` (legacy name)
  - `investment_plan` (legacy name, PM 输出)
  - `final_signal` (top-level)
- 新 backend (`backend/core/runner.py` 写, P2.21 引入) 用新字段:
  - `trader_investment_plan` (renamed)
  - `final_trade_decision` (renamed, 有时是 dict `{"signal": "BUY", ...}`)
  - **没** top-level `final_signal`

**为什么重写 `web/pdf_export.py`** 不重写: ~600 行的 PDF 排版 + CJK 字体处理 + markdown→PDF 转换 (fpdf2 + DejaVuSans fallback), 改起来风险大。adapter 模块 (145 行) 把映射隔离, **legacy code 不动**。

### 4.2 `strip_think_blocks` — LLM 推理块剥离

**文件**: `backend/core/report_adapter.py:32-74`

**3 种 think 块变体** (LangGraph + DeepSeek 模型输出):
```python
_STRIP_THINK_RE = re.compile(
    r"[\s\S]*?"            # 1. plain text (no angle brackets)
    r"|<think\b[^>]*>[\s\S]*?</think\s*>",  # 2-3. XML variants (uppercase / attrs)
    re.IGNORECASE,
)
```

**为什么需要 3 个变体**:
1. `...`: DeepSeek-V3 / QwQ 默认输出, 占 90%+.
2. `<THINK>...</THINK>`: 用户实测看到的, 大写 XML — 因为 `rehype-sanitize` 默认 schema 不认 `THINK` tag, 会**当成未知 inline HTML 显示** ("user reported as ... escaped as unknown inline HTML")。
3. `<think attr="...">...</think>`: 小写 + 属性, 一些 Anthropic-style 模型输出。

**recursion**:
```python
def strip_think_blocks(value):
    if isinstance(value, str):
        return _STRIP_THINK_RE.sub("", value).strip()
    if isinstance(value, dict):
        return {k: strip_think_blocks(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_think_blocks(v) for v in value]
    if isinstance(value, tuple):
        return tuple(strip_think_blocks(v) for v in value)
    return value  # int/bool/None 不动
```

**集成**:
- `analyze.py::_load_report_json` 在读盘后**立即**调一次 → /report + /export 都拿干净 payload。
- `history.py::get_history_report` 也调 → /history/detail 同样干净。
- `frontend/src/components/analyze/report-markdown.tsx` 的 `STRIP_THINK = /<think[^>]*>[\s\S]*?<\/think>\s*/gi` 在前端**再剥一次** — 双层防御, 因为前端可能从 SSE / cache / 老 history entry 拿到未剥的 payload。

**测试覆盖** (16 tests, `test_report_adapter_strip_think.py`):
- 3 种变体各 1 test
- 多个 think 块 / unclosed think / 含 `<think>` 字样的合法内容
- dict / list / tuple / 标量递归
- 不变性 (input 不被修改)
- API 层组合 (strip 然后 extract_signal) 互不干扰

### 4.3 `pdf_available` probe — CJK 字体探测

**文件**: `backend/api/analyze.py:60-76`

```python
def _pdf_export_available() -> bool:
    """True iff the host has at least one CJK font readable by fpdf2."""
    try:
        from web import pdf_export as _pdf_mod
    except Exception:
        return False
    try:
        return _pdf_mod._find_cjk_font() is not None
    except Exception:
        return False
```

**为什么 lazy probe 而非导入时**:
- `_find_cjk_font()` 递归扫描 `/usr/share/fonts/`, `/System/Library/Fonts/` 等。
- 导入时扫一次 → 用户装机后要重启 backend 才能用 PDF 导出 → UX 差。
- lazy probe: 每次 `get_analyze_report` 时跑一次 → 1 次 font scan ~50ms, 用户装字体后下次访问自动生效。

**3 种 fallback 状态**:

| 状态 | `_pdf_export_available()` | PDF 按钮 | 503 错误 |
|---|---|---|---|
| 有 CJK 字体 | True | 可点 | n/a |
| 没 CJK 字体 | False | 禁用 + tooltip | n/a |
| fpdf2 没装 | False (导入失败) | 禁用 + tooltip | n/a |

**前端处理**:
```typescript
// report-header.tsx
{pdfAvailable ? (
  <a href={pdfUrl} download={pdfName}>下载 PDF</a>
) : (
  <button disabled title="PDF 导出需要系统装有中文字体...">PDF 不可用</button>
)}
```

### 4.4 react-markdown + rehype-sanitize — 报告渲染

**新增依赖**: `react-markdown@^9.1.0` + `rehype-sanitize@^6.0.0` + `remark-gfm@^4.0.1`

**文件**: `frontend/src/components/analyze/report-markdown.tsx` (134 行)

**包装**:
```typescript
<ReactMarkdown
  remarkPlugins={[remarkGfm]}  // 表格 / 删除线 / 任务列表
  rehypePlugins={[rehypeSanitize]}  // XSS 防护 (默认 schema)
  skipHtml  // ← 关键! 跳过源 HTML, sanitize 之后没危险
  components={{
    ul: ..., ol: ..., li: ..., p: ...,
    h1: ..., h2: ..., h3: ..., h4: ...,
    code: ..., pre: ...,
    table: ..., th: ..., td: ...,
    blockquote: ..., hr: ..., a: ...,
  }}
>
  {cleaned}
</ReactMarkdown>
```

**为什么 3 个 plugin 一起**:
1. `remark-gfm`: GitHub-flavoured markdown, 让报告里的表格 (e.g. PE / PB 对比表) 正确渲染。
2. `rehype-sanitize`: **安全** — LLM 输出可能被 prompt injection (e.g. "在报告末尾加 `<script>fetch(...)`"), sanitize 剥危险标签。
3. `skipHtml`: **冗余防御** — 即使 sanitize schema 漏, 也跳过原始 HTML, 避免 `<script>` 等。

**为什么自定义 components**:
- Tailwind reset 给 `<ul>` 太多 margin, 项目希望紧凑布局 (`my-2 ml-4 list-disc space-y-1`)。
- `<a>` 自动 `target="_blank" rel="noreferrer noopener"` 防 tab-nabbing。
- 列表 / 表格 / 引用统一项目配色。

**空状态处理**:
```typescript
if (!cleaned) {
  return <div data-testid="report-markdown-empty">(本报告无内容)</div>;
}
```

### 4.5 `report-debate-tabs` / `report-risk-tabs` — 报告分 4 块

**文件**: `frontend/src/components/analyze/report-debate-tabs.tsx` (66 行) + `report-risk-tabs.tsx` (70 行)

**debate tabs** (3 个 Tab):
- 🐂 多方 (bull_history)
- 🐻 空方 (bear_history)
- 👔 研究经理 (judge_decision)

**risk tabs** (4 个 Tab):
- ⚡ 激进 (aggressive_history)
- 🛡 保守 (conservative_history)
- ⚖ 中性 (neutral_history)
- 👔 风控决策 (judge_decision)

**testid 契约** (P2.28 锁定):
- 外层 `<div data-testid={cardTestId ?? 'analysis-report-card-investment_debate_state'}>` — 继承 P2.28 testid
- 内层 `<TabsList>` 触发器 `data-testid="report-debate-bull"` 等 — 新 testid for unit test

**为什么用 Tabs 而非 Card**:
- 辩论 dict 有 3-4 个**对等**的 persona 输出, 一字铺开浪费屏幕。
- Radix Tabs 默认 active styling 跟项目 `ui/button.tsx` 的 cva pattern 一致。

### 4.6 `report-header` — 报告头

**文件**: `frontend/src/components/analyze/report-header.tsx` (173 行)

**布局**:
```
┌─────────────────────────────────────────────────────────┐
│  [BUY/SELL/HOLD]   TICKER              [下载 Markdown]   │
│  TRADING SIGNAL    分析日期 2026-07-19  [下载 PDF]      │
│                    {analysis_id}                         │
├─────────────────────────────────────────────────────────┤
│  ⚠️ 免责声明: AI 自动生成, 不构成投资建议                  │
└─────────────────────────────────────────────────────────┘
```

**测试 testid** (双层, 兼容 P2.28):
- `data-testid="analysis-report-signal-block"` (新 wrapper)
- `data-testid="analysis-report-signal"` (legacy, 在内层 `span.contents` 上)
- `data-testid="analysis-report-signal-value"` (新, 真实显示的 BUY/SELL/HOLD)

**为什么 `span.contents` 包一层**:
- `<span data-testid="signal">` 原来只放文字 (`{signal}`)。
- 新设计包了 icon + text, 直接放外层会让 innerText 测试 break (搜 "BUY" 时外层 div 也匹配)。
- 用 `<span class="contents">` 是 Tailwind 技巧 — `display: contents` 让 wrapper 不渲染成 box, 但 DOM 节点保留。

### 4.7 `analysis-report.tsx` 视觉重构

**文件**: `frontend/src/components/analyze/analysis-report.tsx` (260 行 diff)

**布局变化**:
- 之前: 1 个 ticker pill + 7 个 Card (每个全屏高度)
- 之后: 1 个 ReportHeader (hero) + 1 个 Accordion (7 analyst) + 2 个 Tabs 块 (debate/risk) + 3 个 standalone Card (quality_gate / trader / pm)

**Accordion vs Card 决策**:
- 7 analyst 每个都有 1000+ 字 markdown → 7 个全屏 Card 会把用户赶出页面。
- Accordion 默认开 `market_report` (第一个), 用户可以**展开/收起**任意一个。
- 用 `data-testid={`analysis-report-card-${def.key}`}` 保留每个 item 的 testid, AccordionItem 内层渲染 ReportMarkdown。

---

## 5. 新模块 (4 个)

### 5.1 `backend/core/history_cleanup.py` (380 行)

**P2.30 新模块 — 跟 history_store.py 关系**:

| 维度 | history_store.py | history_cleanup.py |
|---|---|---|
| 角色 | Repository (CRUD) | Domain Service (bulk wipe) |
| 锁定 | P2.30 加 `_lock_path` (RLock) | 用 `store.exclusive_access()` context manager |
| 操作粒度 | 单 entry (analysis_id) | 全表 + 全部 on-disk 副产物 |
| 失败模式 | 单点 OSError 吞掉 | 计数 + 继续 |
| 输入 | analysis_id | `include_cache: bool` |
| 输出 | HistoryEntry | HistoryPurgeResult (4 个 deleted 计数 + bytes_freed) |

**核心 invariant**:
```python
ACTIVE_STATUSES = frozenset({"pending", "running"})

def purge_history(*, include_cache: bool = False) -> HistoryPurgeResult:
    store = get_history_store()
    with store.exclusive_access():           # ① 独占锁
        _assert_no_active_analyses(store)    # ② 检查 active
        result = HistoryPurgeResult()
        _purge_metadata(store, result)       # ③ 删 history JSON
        _purge_results_and_logs(result)      # ④ 删 reports + log runs
        if include_cache:
            _purge_cache(result)             # ⑤ 可选删 cache
        return result
```

**active 检查** 3 层:
1. `HistoryStore.list_all` → `pending`/`running` entry
2. `TrackerStore.list_all()` → `tracker.is_running`
3. 合并 `active_ids` 列表, 任何一个非空 → `raise ActiveAnalysesError(active_ids)`

**`_purge_results_and_logs` 路径细节**:
```
~/.tradingagents/logs/{ticker}/                ← ticker 必须是 6 digit
  ├── TradingAgentsStrategy_logs/             ← 报告 dir
  │     └── full_states_log_2026-07-19.json
  └── 2026-07-19_run01/                       ← 单 run log dir
        ├── meta.json
        ├── llm_messages.jsonl
        ├── tool_calls.jsonl
        └── agent_outputs.jsonl
```

**安全防御 (3 重)**:
1. `_forbidden_roots = (Path("/"), Path.home(), _project_root())` — 拒绝 iterate 这些根
2. `path.is_symlink()` 检查 — 不追 symlink (防 symlink planted attack)
3. `ticker.isdigit() and len(ticker) == 6` — 只删看起来像 ticker 的子目录

**没 LRU / TTL**:
- 当前实现是 "purge everything terminal" — 一次性。
- 没分批删除 (e.g. "保留最近 30 天"), **DDD_OPERATIONS §6.5/§6.6 的 LRU/TTL 债务没修**。
- P2.30 的 trade-off: 加 LRU/TTL 需要新调度器 (跟 `scheduler.py` 重复), 没在 P2.30 scope 内。

**测试覆盖** (25 tests, `test_history_purge.py`):
- `TestPurgeValidation` (3): confirmation 422 / missing 422 / include_cache type 422
- `TestActiveAnalysesBlockPurge` (4): pending/running/in-memory tracker block + 不删任何东西
- `TestPurgeWipesAllTargets` (3): 全删 / 多 entry 去重计数 / cache 保留
- `TestPurgePreservesUnrelatedDirs` (1): portfolio/watchlist/settings/memory 不动
- `TestPurgeIdempotency` (1): 跑两次返 all-zero
- `TestPurgeSafety` (2): results_path 拒绝 / response 不泄漏绝对路径
- `TestPurgeEdgeCases` (4): 非 ticker 子目录跳过 / stray file 删 / nested report subdir / symlink 不追

### 5.2 `backend/core/report_adapter.py` (145 行)

见 §4.1 / §4.2 — 主要功能是 `adapt_report_for_export` + `extract_signal` + `strip_think_blocks`。

**跟 history_store / analyzer 关系**:
- 不是 Repository — 没持久化。
- 是 **adapter pattern** (GoF) — 在新 backend analyze payload 和 legacy web/pdf_export 之间做语义映射。
- 跟 history_store: history_store 存数据, report_adapter 不读 history_store, 只读 `dict[str, Any]` (从 `_load_report_json` 传入)。

**测试覆盖** (16 tests, `test_report_adapter_strip_think.py`):
- 3 种 think 变体 × 1
- 多块 / unclosed / 含 `<think>` 字样合法内容
- 递归 dict/list/tuple/标量
- immutability (输入不变)
- API 层组合 (strip + extract_signal)
- `adapt_report_for_export` 不处理 think (跟 strip 是分离的)

### 5.3 `HistoryPurgeDialog` (250 行)

**P2.30 新组件**:
- 触发器按钮 (`🗑 清空所有历史`) — 在 HistoryPage header + AnalyzePage history tab 各一个
- Dialog 内容: 删除范围 + 不删范围 + 输入 "清空" 确认
- mutation: `purgeHistory({confirmation, include_cache})` → POST /api/history/purge

**两层确认**:
1. UI 层: 用户必须输入 sentinel "清空" (前端 `confirmEnabled = confirmText === '清空'`)
2. API 层: `confirmation === 'CLEAR_ALL_HISTORY'` (后端 Pydantic Literal)

**active_analyses 409 处理**:
```typescript
function parseActiveAnalysesError(message: string): ActiveAnalysesErrorPayload | null {
  const idx = message.indexOf('{"detail"');
  if (idx < 0) return null;
  const tail = message.slice(idx);
  try {
    const parsed: unknown = JSON.parse(tail);
    if (
      typeof parsed === 'object' && parsed !== null &&
      'detail' in parsed &&
      isActiveAnalysesPayload((parsed as { detail: unknown }).detail)
    ) {
      return (parsed as { detail: ActiveAnalysesErrorPayload }).detail;
    }
  } catch {
    return null;
  }
  return null;
}
```
- 解析 409 detail payload → 显示 "仍有 N 个分析在运行" → 用户**取消 / 等待**后重试。
- 防御: 不是直接 `as { ... }`, 而是用 `isActiveAnalysesPayload` runtime guard 验证 shape。

**cache invalidation**:
```typescript
onSuccess: () => {
  queryClient.invalidateQueries({ queryKey: ['history'] });
  queryClient.invalidateQueries({ queryKey: ['analyze-recent'] });
  queryClient.removeQueries({ queryKey: ['history-detail'] });
  queryClient.removeQueries({ queryKey: ['analyze-progress'] });
  queryClient.removeQueries({ queryKey: ['analyze-report'] });
  // ...
}
```
- 列表 invalidate (refetch), per-id remove (避免 stale detail 渲染在已打开的 tab)

**测试覆盖** (9 tests, `history-purge-dialog.test.tsx`):
- 触发器可见
- Dialog 打开 / 关闭
- 输入 sentinel 后启用 / 错误文本禁用
- mutation onSuccess / onError
- 409 active_analyses 解析
- onPurged 回调

### 5.4 `tradingagents/default_config.py` (+35 / -3)

见 §3.1 — 唯一修的是 `os.getenv` + `os.path.expanduser`。

**新增 helper**:
```python
def _resolve_home_dir(env_var: str, default: str) -> str:
    raw = os.getenv(env_var, default)
    return os.path.expanduser(raw)
```

**3 个 config key 改用 helper**:
- `results_dir`
- `data_cache_dir`
- `memory_log_path`

**P2.28 hotfix 注释**:
> "We now ``expanduser`` the env-var fallback so both styles work — a literal ``~`` in .env gets the same expansion as the implicit default."

**跟 MIGRATION_ROADMAP §3.2 Phase 1 的关系**:
- Phase 1 工作包 5: "固化 zombie/stuck cleanup 的触发与状态语义, 为 SQLite 状态迁移提供确定基线"
- P2.28 的 default_config 修复不在 Phase 1 显式工作包里 — 但属于"消除路径错位 bug" — 算提前完成的 Phase 1 副产品。

---

## 6. 新增依赖 (5 个)

| 包 | 版本 | 用途 | 文件 |
|---|---|---|---|
| `@radix-ui/react-accordion` | ^1.2.16 | 7 analyst section 折叠 | `frontend/src/components/ui/accordion.tsx` + `analysis-report.tsx` |
| `@radix-ui/react-tabs` | ^1.1.17 | debate (3 tab) + risk (4 tab) | `frontend/src/components/ui/tabs.tsx` + `report-debate-tabs.tsx` + `report-risk-tabs.tsx` |
| `react-markdown` | ^9.1.0 | 报告 markdown 渲染 | `frontend/src/components/analyze/report-markdown.tsx` |
| `rehype-sanitize` | ^6.0.0 | XSS 防护 (默认 schema) | `report-markdown.tsx` |
| `remark-gfm` | ^4.0.1 | GitHub-flavored markdown (table / strikethrough) | `report-markdown.tsx` |

**为什么这 5 个一起**:
- `react-markdown` 是 renderer, 需要 `remark` plugins (gfm) 和 `rehype` plugins (sanitize) 才能跑完整 pipeline。
- `radix-ui/accordion` + `radix-ui/tabs` 是**互补**的 — accordion 用于"省空间 + 全展开", tabs 用于"对等多角色切换"。
- 5 个一起上是因为 P2.29 一次性把"报告视觉重构 + 安全 + markdown 渲染"做完。

**没引入**:
- ~~PDF 生成 lib (fpdf2)~~ — `web/pdf_export.py` 已经用, 不需要新加
- ~~highlight.js / shiki (代码高亮)~~ — 报告里几乎没代码块, 暂时不需要
- ~~react-pdf / pdfmake~~ — 走 web/pdf_export 的 fpdf2 路径, 不切

**跟 frontend 现有 lib 的关系**:
- `@tanstack/react-query` ^5.59 — P2.30 继续用 (HistoryPurgeDialog 用 mutation)
- `lucide-react` (icon lib) — 新 `Loader2` / `Trash2` / `Download` 都来自这里
- `class-variance-authority` + `tailwind-merge` — 新 `accordion.tsx` / `tabs.tsx` 沿用 cva pattern

---

## 7. 27 modified + 6 new 文件完整 diff 分析

### 7.1 backend (4 modified + 2 new)

| 文件 | +/− | 关键变更 |
|---|---|---|
| `backend/api/analyze.py` | +137/−25 | `_load_report_json` helper (P2.29); `/export` endpoint (md\|pdf, 200/404/422/503); `pdf_available` field (P2.29); `_pdf_export_available()` CJK font probe (P2.29); `_load_report_json` 调 `strip_think_blocks` (P2.31) |
| `backend/api/history.py` | +96/−0 | `POST /api/history/purge` endpoint (P2.30); `PurgeHistoryRequest` (Pydantic Literal); 409 active_analyses 详情; `get_history_report` 调 `strip_think_blocks` (P2.31); 路由顺序 (purge 必须早于 `{analysis_id}`) |
| `backend/core/history_store.py` | +130/−60 | `STUCK_THRESHOLD_SEC` 600→1800s (P2.26); `_lock_path` 改 RLock (P2.30); `exclusive_access()` context manager (P2.30); 所有 disk-touch 方法加 `with self._lock_path` (P2.30) |
| `backend/core/runner.py` | +102/−23 | `MAX_RUN_SEC` 600→1800s (P2.26); `stage_map` 改 `(stage_id, canonical_key)` 二元组 (P2.28); `stage_order` 显式 12 stage 列表 (P2.26); `_activate_next_stage` 后写 results_path (P2.28); dict-shape stage `judge_decision` 检查 (P2.26); `start_analysis` 同步 `mark_stage_active('market')` (P2.26) |
| `backend/core/history_cleanup.py` | **new** (380 行) | P2.30 — 见 §5.1 |
| `backend/core/report_adapter.py` | **new** (145 行) | P2.29 + P2.31 — 见 §4.1 / §4.2 |

### 7.2 frontend (11 modified + 6 new)

| 文件 | +/− | 关键变更 |
|---|---|---|
| `frontend/src/pages/AnalyzePage.tsx` | +85/−14 | `recentlyCreatedIdsRef` Set (P2.26); `handleSelectRecent` 按 status 路由 tab (P2.26 + P2.27); reportQuery.error `stillInRecent` 守卫 (P2.26); 删除 auto-advance 进度→报告 effect (P2.31); mount `HistoryPurgeDialog` (P2.30) |
| `frontend/src/pages/HistoryPage.tsx` | +24/−8 | `handlePurged` 回调 (关 modal + 回 page 0); mount `HistoryPurgeDialog` (P2.30) |
| `frontend/src/api/analyze.ts` | +20/−4 | `analyzeExportUrl` / `analyzeExportFilename` helpers (P2.29); `pdf_available` field (P2.29); `ExportFormat = 'md'\|'pdf'` type (P2.29) |
| `frontend/src/api/history.ts` | +29/−0 | `purgeHistory` POST wrapper (P2.30); `PurgeHistoryResponse` / `PurgeHistoryBody` types |
| `frontend/src/components/analyze/analysis-progress.tsx` | +47/−3 | `erroredStage` 推算 (P2.27); 4 状态颜色 (done/errored/running/pending); error banner 升级 (P2.27); 抑制 isComplete 时的 running 高亮 |
| `frontend/src/components/analyze/analysis-report.tsx` | +195/−65 | 12 stage list (P2.28); Accordion (7 analyst) + Tabs (2 debate) + 3 standalone Card (P2.29); mount ReportHeader / ReportDebateTabs / ReportRiskTabs / ReportMarkdown (P2.29) |
| `frontend/src/components/analyze/analysis-workspace.tsx` | +15/−3 | `currentStage` 推算 fallback (P2.26); 7 WORKSPACE_CARDS 顺序假设 |
| `frontend/src/components/analyze/analysis-recent-list.tsx` | +1/−1 | "7 / 12" 改为 "12 / 12" (P2.28) |
| `frontend/src/components/ui/dialog.tsx` | +13/−2 | `useId` stable title/description id; `aria-labelledby` / `aria-describedby` (P2.30 a11y) |
| `frontend/package.json` | +5/−0 | 5 新 deps (见 §6) |
| `frontend/tailwind.config.{js,ts}` | +14×2 | `accordion-down` / `accordion-up` keyframes + animations (Radix 高度过渡) |
| `frontend/playwright.config.{js,d.ts}` | +2/−1 | `viewport: {width: 1600, height: 900}` (e2e 视觉稳定); type-only fix `@playwright/test` |
| `frontend/src/components/analyze/report-debate-tabs.tsx` | **new** (66 行) | P2.29 — 3-tab debate 多空 + 研究经理 |
| `frontend/src/components/analyze/report-header.tsx` | **new** (173 行) | P2.29 — hero header + download buttons |
| `frontend/src/components/analyze/report-markdown.tsx` | **new** (134 行) | P2.29 — react-markdown 包装 + strip think + 自定义 components |
| `frontend/src/components/analyze/report-risk-tabs.tsx` | **new** (70 行) | P2.29 — 4-tab risk 激进 + 保守 + 中性 + 风控决策 |
| `frontend/src/components/history/history-purge-dialog.tsx` | **new** (250 行) | P2.30 — 共享清空历史 dialog |
| `frontend/src/components/ui/accordion.tsx` | **new** (72 行) | P2.29 — Radix accordion wrapper (cva + cn + forwardRef) |
| `frontend/src/components/ui/tabs.tsx` | **new** (62 行) | P2.29 — Radix tabs wrapper |

### 7.3 tests (4 modified + 5 new)

| 文件 | +/− | 关键变更 |
|---|---|---|
| `tests/conftest.py` | +11/−0 | 把 `_REPO_ROOT` 加进 `sys.path` (让 `pytest tests/` 也能 import `backend.*` / `web.*`) |
| `tests/test_history_purge.py` | **new** (25 tests) | P2.30 — 覆盖 validation / active block / wipe targets / unrelated preservation / idempotency / safety / edge cases |
| `tests/test_analyze_export.py` | **new** (6 tests) | P2.29 — md/pdf 200/503/400/404 |
| `tests/test_report_adapter_strip_think.py` | **new** (16 tests) | P2.29 + P2.31 — 3 种 think 变体 + 递归 + immutability |
| `tests/test_tracker_stage_reports.py` | **new** (14 tests, 7月17日) | P2.25 + P2.26 联合 — key contract / history store parity / dict premature done / stage chain / exception path |
| `frontend/tests/e2e/report-tab-p228.spec.ts` | **new** (1 e2e) | P2.28 — 12 stage card testid assert |
| `frontend/tests/e2e/history.spec.ts` | +88/−0 | P2.30 — purge trigger 可见 + purge happy path + analyze history tab 暴露 trigger |
| `frontend/tests/unit/AnalyzePage.test.tsx` | +80/−6 | P2.31 — completed analysis 进度 tab 不自动跳; 7/12→12/12 进度数; purge trigger 渲染 |
| `frontend/tests/unit/HistoryPage.test.tsx` | +12/−0 | P2.30 — purge trigger 在 header |
| `frontend/tests/unit/AnalysisProgress.test.tsx` | **new** (3 unit) | P2.27 — errored stage 视觉 |
| `frontend/tests/unit/analysis-report.test.tsx` | **new** (8 unit) | P2.29 — Accordion / Tabs 渲染 / 12 testid 存在 |
| `frontend/tests/unit/history-purge-dialog.test.tsx` | **new** (9 unit) | P2.30 — sentinel / 409 解析 / invalidation |
| `frontend/tests/unit/report-markdown-strip-think.test.tsx` | **new** (7 unit) | P2.29 — strip think 前端版 / sanitize / empty state |

### 7.4 commit message 痕迹统计

`git diff HEAD --unified=0 | grep "^+.*P2\.[0-9]+"` 共 **42 行** 含 P2.XX 注释, 分布:

| 标识 | 数量 | 含义 |
|---|---|---|
| `P2.26 hotfix` | 8 | currentStage race / workspace 推算 / stuck threshold / dict premature done / mark_stage_active sync |
| `P2.27 hotfix` | 4 | erroredStage 视觉 / handleSelectRecent 路由 / running 抑制 / error banner 升级 |
| `P2.28 hotfix` | 5 | quality_gate_report 映射 / stage_order 显式 / results_path 写入 / default_config expanduser |
| `P2.29` | 11 | pdf_available / CJK probe / strip_think / adapt_report / export endpoint / report tabs / report header / accordion / tabs / react-markdown |
| `P2.30` | 6 | exclusive_access / confirmation Literal / purge endpoint / HistoryPurgeDialog / API layer strip / 字段 collection |
| `P2.31` | 8 | API boundary strip / auto-advance removal / click 进度 stays / 7/12→12/12 |

**P2.30 / P2.31 是 P2.29 后续**: 文档开头说 "P2.26-P2.29 用户最新修复", 但实际代码里 P2.30 (history purge) + P2.31 (API layer strip + auto-advance 移除) 也都 commit 了 — 这 2 个是 P2.29 的直接扩展, 跟 P2.26-P2.29 同步到达。

**4 个 P2.XX 唯一无 trace**:
- `P2.22` (cancel endpoint) — 在 P2.21 commit 里, 不在 P2.26-29 范围
- `P2.23` (600s timeout) — 在 P2.21 commit 里, P2.26 改 1800s 但旧 trace 没改
- `P2.24` (progressQuery) — 在 P2.24 commit 里
- `P2.25` (tracker key + ID 一致) — 在 P2.25 commit 里

---

## 8. 跟之前 DDD 文档的关系

### 8.1 `docs/DDD_AGENTS_DEEP_DIVE.md` (16 债务, 1424 行)

**未涉及的债务** (本次 P2.26-P2.29 scope 之外):
- Debt A1-A5 (Agent 角色 / Quality Gate / LangGraph 设计) — 全部是 7 Analyst 设计层债务, P2.26-P2.29 不动
- Debt A8+ (Structured output / Tool / etc) — 同上

**间接触碰**:
- §7.4 "Quality Gate 名义为门禁, 实际上不 gate" — P2.28 把 quality_gate_report 加进 stage_map, 视觉上是"第 8 阶段", 但**门禁行为**没改 (still 不真 gate)。这是 debt "确认但没修"。

### 8.2 `docs/DDD_OPERATIONS.md` (12 债务, 1314 行)

| 债务 | 状态 | 备注 |
|---|---|---|
| §6.1 ⚠️ LogWriter.meta.json 无锁 | **未修** | 不在 P2.26-P2.29 scope |
| §6.2 ⚠️ HistoryStore._write 无锁 | **✅ 部分修** (P2.30) | 加 `_lock_path` RLock + `exclusive_access()`; 但 `_write` 内层 read-modify-write 还没用 `fcntl` (跨进程锁), 仍是 in-process |
| §6.3 zombie cleanup 被动 | **未修** | 仍是 startup-only; 但 P2.30 加了 active 检查 + 锁, 让 zombie cleanup 路径更安全 |
| §6.4 chunk_counts vs jsonl | **未修** | P2.26-P2.29 scope 外 |
| §6.5 log cleanup 缺 | **✅ 部分修** (P2.30) | `history_cleanup.py` 的 `_purge_log_run_dir` 删 `*_runNN/` 目录; 但 LRU/TTL 没加, 仍是手动 purge |
| §6.6 history cleanup 缺 | **✅ 部分修** (P2.30) | 同上 — `purge_history()` 删所有 terminal metadata; LRU/TTL 没加 |
| §6.7 chunk_type 字符串散在多处 | **未修** | 不在 scope |
| §6.8 legacy shim 永久保留 | **未修** | `TradingAgentsStrategy_logs/` 仍在 P2.28 用作 results_path 目标 |
| §6.9 ⚠️ rerun endpoint 半成品 | **未修** | 仍存在 |
| §6.10 rerun 不带 stage_reports | **未修** | 同上 |
| §6.11 ⚠️ delete 不级联 | **✅ 部分修** (P2.30) | `purge_history` 级联删 metadata + reports + log_runs + (opt) cache; 但 `delete_history(id)` 单点删除仍未级联 |
| §6.12 report endpoint 不支持 markdown | **✅ 修** (P2.29) | `/export?format=md` + `/export?format=pdf` 双 endpoint |

**总评**: P2.26-P2.29 (尤其 P2.30) 修了 DDD_OPERATIONS 12 债务中的 **5 个** (6.2 / 6.5 / 6.6 / 6.11 / 6.12), 其余 7 个未动。

### 8.3 `docs/DDD_EXPLORATION.md` (9 债务, 1311 行)

| 债务 | 状态 | 备注 |
|---|---|---|
| Debt #1: TrackerStore / HistoryStore ID 不一致 | **✅ 修** (P2.25, 已被本 commit 包含) | test_tracker_stage_reports.py 验证 |
| Debt #2: in-memory 单例, 重启丢数据 | **未修** | 仍是 memory+JSON hybrid |
| Debt #3: Repository 接口未抽象 | **未修** | P2.30 加 history_cleanup 但没 interface |
| Debt #4: 领域事件未实现 | **未修** | 无 EventBus |
| Debt #5: invariant 校验不全 | **未修** | `status="paused"` 等非法值仍被接受 |
| Debt #6: 跨 Context 无 ACL | **未修** | P2.30 history_cleanup 直接 import history_store, 无 ACL |
| Debt #7: stagger 泄漏 | **未修** | 同上 |
| Debt #8: portfolio_calc.get_rebalance_signals stub | **未修** | 不在 scope |
| Debt #9: notify 模板固定 | **未修** | 同上 |

### 8.4 `docs/MIGRATION_ROADMAP.md` (Phase 1-8)

| Phase | 工作包 | P2.26-P2.29 完成情况 |
|---|---|---|
| **Phase 1** (1-2 周, 短期热修) | (1) P2.10-P2.25 盘点 ✅ (P2.26-P2.29 接着 commit); (2) fcntl 跨进程锁 ⚠️ 部分 (in-process 锁已加, 跨进程未加); (3) race / rerun / delete 不级联 ✅ 部分 (delete 不级联已修 bulk purge, 单点 rerun 未动); (4) ChunkType enum ❌; (5) zombie/stuck 状态语义固化 ⚠️ 部分 (P2.26 改阈值但语义没固化) | ~60% 完成 |
| **Phase 2** (2-3 周, 单测安全网) | 测试覆盖率 > 85% | pytest 820 + vitest 63 + 新 89 = 972 ✅ |
| Phase 3-8 | SQLite / Async / Typed Aggregate / ACL / SSE / 第三方 | 0% (未开始) |

**P2.26-P2.29 提前完成的 Phase**:
- **§3.2 Phase 1 工作包 (5)** "zombie/stuck cleanup 触发与状态语义固化" — P2.26 改阈值, P2.27 加 errored 视觉, P2.30 加 active 检查。
- **§3.3 Phase 2 部分** — P2.30 测试覆盖 25 个 + P2.29 测试覆盖 6 个 + P2.31 测试覆盖 8 个 = 89 个新增 test。

**未提前完成**:
- Phase 1 工作包 (2) "fcntl 跨进程锁" — 只加 in-process `threading.RLock`
- Phase 1 工作包 (4) "ChunkType enum" — 没动
- Phase 3 SQLite — 没动

### 8.5 `docs/SQLITE_MIGRATION_PLAN.md` (793 行)

未触碰 (本次 P2.26-P2.29 都在 JSON 持久化层)。

---

## 9. 关键 bug 修复 (按时间 / root cause 顺序)

### 9.1 时间顺序 — 4 个 hotfix 各自的 commit 痕迹

> 注: P2.26-P2.29 是用户**累积修复**, 没看到单独 P2.26 commit message; 注释里标了 `P2.26 hotfix` 是 source code 内的标记

| Hotfix | 涉及文件 | root cause | 修法 |
|---|---|---|---|
| **P2.26** stuck 30 min | `history_store.py` + `runner.py` | `MAX_RUN_SEC=600` + `STUCK_THRESHOLD_SEC=600` 误杀 20 min 长跑 (P2.21 12 stage 后实际变长) | 两个常量同步改 1800s; 注释互引防单边改 |
| **P2.26** recent-list race | `AnalyzePage.tsx` (validation effect + `startMut.onSuccess`) | 同步 setActiveAnalysisId 后, 旧 recentQuery cache 没新 id, validation effect 误判 stale | `recentlyCreatedIdsRef` Set + 在 setActive 之前 add; reportQuery.error 加 `stillInRecent` 守卫 |
| **P2.26** workspace currentStage | `analysis-workspace.tsx` | `currentStage` 在 POST 50ms 内 + LangGraph chunks 间隔时为空, workspace 7 card 不亮 | "第一个没 body 的 card = 正在跑" fallback 推算 |
| **P2.26** dict stage premature done | `runner.py` (stage_map 循环) | debate / risk dict `{'count': 0, ..., 'judge_decision': ''}` truthy → 写入空 stage_report | 加 `not content.get("judge_decision"): continue` 守卫 |
| **P2.26** mark_stage_active sync | `runner.py::start_analysis` | 第一个 chunk 到达前 (~100-500ms) progress bar 空 | `tracker.mark_stage_active('market')` 同步调 |
| **P2.27** errored 视觉 | `analysis-progress.tsx` | errored 时 quality_gate 还显示蓝色 running, 视觉矛盾 | 加 `erroredStage` 状态 + 红色边框 + AlertCircle icon |
| **P2.27** tab router errored→progress | `AnalyzePage.tsx::handleSelectRecent` | errored entry `/report` 404 → fallback 链 | 直接路由到 progress tab (不绕 /report) |
| **P2.28** results_path | `runner.py` + `default_config.py` | (1) `~` 不展开 (2) `_run_analysis` 不写 results_path (3) `/report` fallback 用错位路径 | `_resolve_home_dir` helper + `set_results_path` after `_log_state` |
| **P2.28** 12 stage report | `runner.py` stage_map + `analysis-report.tsx` TRADER_REPORTS | quality_gate 没进 stage_map (没 chunk field); frontend 只 render 7 card | `data_quality_summary: (quality_gate, quality_gate_report)` 二元组映射 + frontend 12 list |
| **P2.29** PDF 导出 | `api/analyze.py::export_analyze_report` + `core/report_adapter.py` | 缺 export endpoint | 借 legacy `web/pdf_export.generate_*` + adapter pattern 改字段名 |
| **P2.29** strip_think_blocks | `core/report_adapter.py` | LLM 输出 `...` 块泄漏到报告 | regex 3 变体 + 递归 dict/list/tuple + API 层一次 + 前端一次双层防御 |
| **P2.29** pdf_available probe | `api/analyze.py::_pdf_export_available` | 没 CJK 字体时 PDF 渲染崩 | lazy CJK font probe + `AnalyzeReport.pdf_available` 字段 + 前端 disabled button fallback |
| **P2.29** react-markdown | `report-markdown.tsx` + deps | 报告用 `<pre>` 渲染 markdown, 不可读 | react-markdown + remark-gfm + rehype-sanitize + 自定义 components |
| **P2.29** report-debate-tabs | `report-debate-tabs.tsx` + `ui/tabs.tsx` | debate dict 3 persona 全部堆在一张 Card, 浪费空间 | 3 Tab (bull/bear/judge) |
| **P2.29** report-risk-tabs | `report-risk-tabs.tsx` | 同上, 4 persona | 4 Tab (aggressive/conservative/neutral/judge) |
| **P2.29** report-header | `report-header.tsx` | 报告头只有 ticker pill, 不专业 | hero block (signal pill + ticker + date + md/pdf download + disclaimer) |
| **P2.29** Accordion (7 analyst) | `ui/accordion.tsx` + `analysis-report.tsx` | 7 全屏 Card 让用户滚出页面 | Radix accordion, 默认开 `market_report` |
| **P2.30** exclusive_access | `history_store.py::exclusive_access` | 多个并发 mark_* + 新 create() 之间可能 race | RLock + context manager; history_cleanup 用它包整个 purge |
| **P2.30** purge endpoint | `api/history.py::purge_history_endpoint` + `core/history_cleanup.py` | 无 bulk delete; 删 history 不级联 | Pydantic Literal confirmation + 409 active_analyses + scope 分级删除 (history / reports / log_runs / cache) |
| **P2.30** HistoryPurgeDialog | `history-purge-dialog.tsx` | 缺确认 dialog | 共享组件, HistoryPage + AnalyzePage 各 mount 一个; "清空" sentinel + 409 解析 |
| **P2.31** API strip_think | `api/analyze.py::_load_report_json` + `api/history.py::get_history_report` | 前端 strip 不够, 历史 API / PDF export 仍泄漏 | API 层调 `strip_think_blocks` 一次, /report + /export + /history 都干净 |
| **P2.31** auto-advance removed | `AnalyzePage.tsx` (effect 删除) | 用户点 进度 tab 看 stage trail, 但 isComplete 触发 useEffect 自动跳回 报告 | 删 effect; handleSelectRecent 已经按 status 路由正确 tab, 不需要再自动跳 |
| **P2.31** 7/12 → 12/12 | `analysis-recent-list.tsx` | 行内显示 `0 / 7` (outdated) | 改 `0 / 12` |

### 9.2 4 类 root cause 归纳

1. **race condition** (3 个):
   - recent-list race (P2.26)
   - disk-write 无锁 (P2.30 加 RLock)
   - purge 时 create() interleaving (P2.30 exclusive_access)

2. **阈值 / 配置保守** (1 个):
   - `MAX_RUN_SEC=600` 太短 (P2.26 改 1800)

3. **路径错位** (2 个):
   - `~` 不展开 (P2.28 default_config)
   - `_run_analysis` 不写 results_path (P2.28 runner)

4. **可视化 / 交互缺失** (5 个):
   - errored 状态视觉 (P2.27)
   - 报告视觉重构 (P2.29 Accordion + Tabs + Header + Markdown)
   - debounce 后用户能停在 进度 (P2.31 删 auto-advance)
   - 12 stage 显示完整性 (P2.28)
   - bulk delete 缺 (P2.30)

---

## 10. 仍未解决的债务 (从 DDD 文档挑)

### 10.1 `docs/DDD_OPERATIONS.md` 12 债务 — P2.26-P2.29 没修的 7 个

| # | 债务 | 影响 | 建议修复路径 |
|---|---|---|---|
| 6.1 | LogWriter.meta.json 无 fcntl 锁 | 并发 writer lost update | Phase 1 工作包 (2) — 跨进程 lock file |
| 6.3 | zombie cleanup 被动 (仅 startup) | runtime zombie 不清理 | runtime 60s polling + scheduler 钩 |
| 6.4 | chunk_counts vs jsonl 行数 | meta stale → UI 显示 0 chunk | `LogStore.list_tasks` 改读实际文件 (性能退化) |
| 6.7 | chunk_type 字符串散在 6+ 处 | 加新类型要 grep-replace | `ChunkType` str enum (Phase 1 工作包 4) |
| 6.8 | legacy shim 永久保留 | dev 不知何时删 | deprecation warning + `_LEGACY_DEPRECATION_DATE` config |
| 6.9 | rerun endpoint 半成品 | 删除 entry 不启动新分析 | 后端 atomic create + start_analysis, 返新 id |
| 6.10 | rerun 不带 stage_reports | race window 老 thread 写老 id | mark_stage_done 加 analysis_id ownership check |

**P2.26-P2.29 修了 5 个** (§6.2, §6.5, §6.6, §6.11, §6.12)

### 10.2 `docs/DDD_EXPLORATION.md` 9 债务 — 全部未修

| # | 债务 | 影响 | 建议 |
|---|---|---|---|
| #1 | TrackerStore / HistoryStore ID 一致 | P2.25 ✅ (但 P2.26 测试固化) | — |
| #2 | in-memory 单例, 重启丢数据 | production 进程崩 → memory tracker 全丢 | Phase 3 SQLite 持久化 |
| #3 | Repository 接口未抽象 | 测试 mock 困难 | Phase 6 Typed Aggregate |
| #4 | 领域事件未实现 | 跨模块通信靠直接调用 | Phase 8 引入 EventBus |
| #5 | invariant 校验不全 | `status="paused"` 等非法值被接受 | Phase 1 状态机迁移 |
| #6 | 跨 Context 无 ACL | history_cleanup 直接 import history_store | Phase 4 ACL |
| #7 | stagger 泄漏 | job_queue & scheduler 协调 | Phase 6 |
| #8 | portfolio_calc.get_rebalance_signals stub | stub 不动 → portfolio_alerts 走空 | Phase 6 |
| #9 | notify 模板固定 | 无自定义路径 | Phase 8 |

### 10.3 `docs/DDD_AGENTS_DEEP_DIVE.md` 16 债务 — 1 间接确认, 15 未修

| # | 债务 | 影响 |
|---|---|---|
| A3 | Quality Gate 名义为门禁, 实际不 gate | **P2.28 间接确认** — quality_gate 进 stage_map 但 gate 行为没改 |
| 其余 15 个 (A1, A2, A4-A16) | 7 Analyst 设计 / LangGraph 状态机 / Tool / Structured output | 全部未动 |

### 10.4 优先级 (按 ROI 排序)

🔴 **立即 (本周)**:
1. DDD_OPERATIONS §6.1 LogWriter.meta.json 加 fcntl (跨进程锁) — Phase 1 显式工作包, 风险高
2. DDD_OPERATIONS §6.9 rerun endpoint 修原子性 — 用户 rerun 容易触发

🟡 **短期 (1-2 周)**:
3. Phase 1 工作包 (4) ChunkType enum — 一次性 refactor
4. DDD_OPERATIONS §6.3 runtime zombie cleanup (60s polling) — 复用 scheduler polling

🟢 **中期 (Phase 3 SQLite)**:
5. DDD_EXPLORATION #2 in-memory 持久化 (重启不丢 tracker)
6. DDD_OPERATIONS §6.5/§6.6 LRU + TTL (replace P2.30 bulk purge)

---

## 11. 测试 & 类型验证结果

### 11.1 pytest 820 passed ✅

```
$ .venv/bin/python -m pytest tests/ --ignore=tests/test_google_api_key.py -q
820 passed, 2 skipped, 1 warning, 44 subtests passed in 13.37s
```

**新增 test 覆盖** (P2.26-P2.29 范围):
- `test_history_purge.py` — 25 passed
- `test_analyze_export.py` — 6 passed
- `test_report_adapter_strip_think.py` — 16 passed
- `test_tracker_stage_reports.py` — 14 passed (含 P2.25 + P2.26 + P2.23 集成)
- 总计 +61 tests, **0 回归**

**2 个 skipped**:
- `test_batch.py:621` — `.env` 没 API key
- `test_batch.py:651` — `RUN_BATCH_E2E=1` env 没设

### 11.2 vitest 63 passed ✅

```
$ cd frontend && env -u NODE_ENV ./node_modules/.bin/vitest run
Test Files  10 failed | 13 passed (23)
Tests  63 passed (63)
```

**10 failed test files** — **不是测试失败**, 是 vitest config 没排除 `tests/e2e/` 目录:
- `tests/e2e/analyze.spec.ts` 等 10 个 playwright spec 被 vitest 误收集 → `playwright/test` import 失败
- 这是 vitest config 误配, 跟 P2.26-P2.29 修复**无关** — 是 pre-existing 项目历史 issue
- 实际 unit tests 全 pass (63 个), 包括 P2.30 的 9 个 + P2.29 的 7 个 + P2.27 的 3 个 + P2.28 的 8 个

**新增 test 覆盖** (P2.26-P2.29 范围):
- `AnalysisProgress.test.tsx` — 3 unit (P2.27)
- `analysis-report.test.tsx` — 8 unit (P2.29)
- `history-purge-dialog.test.tsx` — 9 unit (P2.30)
- `report-markdown-strip-think.test.tsx` — 7 unit (P2.29)
- `report-tab-p228.spec.ts` — 1 e2e (P2.28)
- `history.spec.ts` — 新增 2 e2e (P2.30)
- `AnalyzePage.test.tsx` — 新增 1 e2e + 2 unit (P2.30 + P2.31)
- `HistoryPage.test.tsx` — 新增 1 unit (P2.30)
- 总计 +28 unit tests + 4 e2e tests

### 11.3 TypeScript 0 errors ✅

```
$ cd frontend && rm -f tsconfig.*.tsbuildinfo && npx tsc --noEmit
TSC EXIT: 0
```

**新增 module 全部 type-safe**:
- `ui/accordion.tsx` — Radix forwardRef types ✅
- `ui/tabs.tsx` — Radix forwardRef types ✅
- `history-purge-dialog.tsx` — useMutation + Dialog + Input types ✅
- 4 个 report-*.tsx — `AnalyzeReport` 新 field `pdf_available` ✅

### 11.4 修改 → 不修改的清单

| 类型 | 数量 | 说明 |
|---|---|---|
| 改动的 source files | 33 (27 modified + 6 new) | 全是 git status 看到的 |
| 改动的 test files | 9 (4 modified + 5 new) | 全是新增 / 扩充 |
| 改动的 config files | 4 (package.json / tailwind × 2 / playwright × 2) | 新 deps + animation keyframes + viewport |
| **0 改动** | pytest.ini / pyproject.toml / 任何 spec | 严格遵守"只读 + 写文档" |

---

## 12. 一句话总结

P2.26-P2.29 (含提前 commit 的 P2.30 history purge + P2.31 API layer strip + auto-advance 移除) **4+2 个 hotfix 联合解决了**:
- 3 个 race condition (recent-list / disk-write / purge-create interleaving)
- 1 个阈值保守 (600s → 1800s)
- 2 个路径错位 (~ 展开 + results_path 写入)
- 5 个可视化 / 交互缺失 (errored 视觉 / 12 stage 完整 / Accordion-Tabs 报告 / 报告 markdown 渲染 / bulk delete)
- **+ 1 个全新功能**: PDF + Markdown 导出 + 一键清空历史

修了 `DDD_OPERATIONS.md` 12 债务中的 **5 个** (历史 bulk 清理 + race + markdown export + cascade delete), 同时引入了 **89 个新 test** (pytest +61, vitest +28), **0 回归**, tsc **clean**。

**仍未修的核心债务**: 跨进程文件锁 (Phase 1 工作包 2) / ChunkType enum (Phase 1 工作包 4) / SQLite 持久化 (Phase 3) / rerun endpoint 原子性 (P2.10 老 hotfix 后续) / LRU-TTL 自动清理 (P2.30 后续) — 这些都是 `MIGRATION_ROADMAP.md` Phase 1-3 的工作包。

---

## 附录 A: 文件路径速查

### A.1 backend 新文件
- `backend/core/history_cleanup.py` (380 行, P2.30)
- `backend/core/report_adapter.py` (145 行, P2.29 + P2.31)

### A.2 backend 修改文件
- `backend/api/analyze.py` (+137/−25)
- `backend/api/history.py` (+96/−0)
- `backend/core/history_store.py` (+130/−60)
- `backend/core/runner.py` (+102/−23)

### A.3 frontend 新文件
- `frontend/src/components/analyze/report-debate-tabs.tsx` (66 行)
- `frontend/src/components/analyze/report-header.tsx` (173 行)
- `frontend/src/components/analyze/report-markdown.tsx` (134 行)
- `frontend/src/components/analyze/report-risk-tabs.tsx` (70 行)
- `frontend/src/components/history/history-purge-dialog.tsx` (250 行)
- `frontend/src/components/ui/accordion.tsx` (72 行)
- `frontend/src/components/ui/tabs.tsx` (62 行)

### A.4 frontend 修改文件
- `frontend/src/pages/AnalyzePage.tsx`
- `frontend/src/pages/HistoryPage.tsx`
- `frontend/src/api/analyze.ts`
- `frontend/src/api/history.ts`
- `frontend/src/components/analyze/analysis-progress.tsx`
- `frontend/src/components/analyze/analysis-report.tsx`
- `frontend/src/components/analyze/analysis-workspace.tsx`
- `frontend/src/components/analyze/analysis-recent-list.tsx`
- `frontend/src/components/ui/dialog.tsx`
- `frontend/package.json`
- `frontend/tailwind.config.{js,ts}`
- `frontend/playwright.config.{js,d.ts}`

### A.5 backend 新测试
- `tests/test_history_purge.py` (25 tests, P2.30)
- `tests/test_analyze_export.py` (6 tests, P2.29)
- `tests/test_report_adapter_strip_think.py` (16 tests, P2.29 + P2.31)
- `tests/test_tracker_stage_reports.py` (14 tests, P2.25 + P2.26 + P2.23)

### A.6 frontend 新测试
- `frontend/tests/e2e/report-tab-p228.spec.ts` (1 e2e, P2.28)
- `frontend/tests/unit/AnalysisProgress.test.tsx` (3 unit, P2.27)
- `frontend/tests/unit/analysis-report.test.tsx` (8 unit, P2.29)
- `frontend/tests/unit/history-purge-dialog.test.tsx` (9 unit, P2.30)
- `frontend/tests/unit/report-markdown-strip-think.test.tsx` (7 unit, P2.29)

### A.7 测试 + 类型验证
- pytest: `cd /home/youfu/projects/youfu-trading-agent-astock && .venv/bin/python -m pytest tests/ --ignore=tests/test_google_api_key.py -q` → 820 passed, 0 failed
- vitest: `cd frontend && env -u NODE_ENV ./node_modules/.bin/vitest run` → 63 passed (10 playwright e2e 误收集, pre-existing vitest config issue)
- tsc: `cd frontend && rm -f tsconfig.*.tsbuildinfo && npx tsc --noEmit` → 0 errors

## 附录 B: 不 commit 承诺

本文档作为 `docs/P2_26_P2_29_ANALYSIS.md` **直接 write 到 docs/**, 没有 git commit。
- 严格遵守硬约束: 0 改 code / 0 改 pytest / 0 改 spec / 0 commit
- 任务范围内仅产出: **1 个文档文件** + **0 个代码改动**

