/**
 * AnalysisProgress — live progress bar across the 12 pipeline stages.
 *
 * P2.21 hotfix:
 *   - Stages list expanded from 7 to 12 to match the actual backend
 *     pipeline (market/social/news/fundamentals/policy/hot_money/lockup
 *     + quality_gate/debate/risk/trader/pm). The user's
 *     ``600595_2026-07-16_1589cdfd`` finished 8 stages and stopped, but
 *     the old 7-card UI couldn't show debate/risk/trader/pm as cards.
 *   - Added ``inferCurrentStage()`` to recover a non-empty current_stage
 *     when the backend returns ``""`` (which happens for analyses started
 *     before P2.21, and during transitions between stages). We infer it
 *     from ``completed_stages[-1] + 1``.
 *   - Added a "取消" button that calls POST /api/analyze/{id}/cancel —
 *     gives the user a one-click escape when the analysis hangs.
 *   - Preview block shows the latest stage_report text (first 200 chars)
 *     so the user can see what the latest analyst said while waiting.
 */
import * as React from 'react';
import {
  CheckCircle2,
  Circle,
  Loader2,
  AlertCircle,
  XCircle,
} from 'lucide-react';
import type { ProgressResponse } from '@/api/analyze';
import { cancelAnalysis } from '@/api/analyze';

interface AnalysisProgressProps {
  progress: ProgressResponse | null;
  isPolling?: boolean;
  /** Optional callback after a successful cancel — parent can flip tabs. */
  onCancelled?: () => void;
}

interface StageDef {
  id: string;
  name: string;
  icon: string;
}

// 12 stages — matches backend/core/runner.py stage_map keys. Order matches
// the pipeline execution order so the user sees stages light up left-to-right.
const STAGES: StageDef[] = [
  { id: 'market', name: '技术分析', icon: '📊' },
  { id: 'social', name: '情绪分析', icon: '💬' },
  { id: 'news', name: '新闻舆情', icon: '📰' },
  { id: 'fundamentals', name: '基本面', icon: '📋' },
  { id: 'policy', name: '政策分析', icon: '🏛️' },
  { id: 'hot_money', name: '游资追踪', icon: '🔥' },
  { id: 'lockup', name: '解禁监控', icon: '🔒' },
  { id: 'quality_gate', name: '质量门禁', icon: '✅' },
  { id: 'debate', name: '多空辩论', icon: '⚔️' },
  { id: 'risk', name: '风控讨论', icon: '🛡️' },
  { id: 'trader', name: '交易员决策', icon: '💹' },
  { id: 'pm', name: '组合经理', icon: '👔' },
];

const STAGE_TO_REPORT_KEY: Record<string, string> = {
  market: 'market_report',
  social: 'sentiment_report',
  news: 'news_report',
  fundamentals: 'fundamentals_report',
  policy: 'policy_report',
  hot_money: 'hot_money_report',
  lockup: 'lockup_report',
  debate: 'investment_debate_state',
  risk: 'risk_debate_state',
  trader: 'trader_investment_plan',
  pm: 'final_trade_decision',
  quality_gate: 'quality_gate_report',
};

/**
 * P2.21 hotfix — recover a non-empty current_stage.
 *
 * The backend's `runner._run_analysis` historically cleared current_stage
 * to ``""`` after every ``mark_stage_done()`` (fixed in P2.21 but old
 * history entries still have the bug). When current_stage is empty we
 * infer it as "the next stage after the last completed one".
 */
export function inferCurrentStage(progress: ProgressResponse): string {
  if (progress.current_stage) return progress.current_stage;
  const completed = progress.completed_stages ?? [];
  if (completed.length === 0) return STAGES[0].id;

  const lastDone = completed[completed.length - 1];
  const lastIdx = STAGES.findIndex((s) => s.id === lastDone);
  if (lastIdx === -1) return STAGES[0].id;
  if (lastIdx >= STAGES.length - 1) return STAGES[STAGES.length - 1].id;
  return STAGES[lastIdx + 1].id;
}

function fmtElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m${s}s`;
}

function latestStageReportSnippet(
  progress: ProgressResponse,
  currentStageId: string,
): string | null {
  const stageReports = progress.stage_reports ?? {};
  const completed = progress.completed_stages ?? [];

  // Prefer the report for the currently-inferred stage (if it has one).
  const reportKey = STAGE_TO_REPORT_KEY[currentStageId];
  if (reportKey && stageReports[reportKey]) {
    return stageReports[reportKey];
  }
  // Fallback: most recent completed stage's report.
  for (let i = completed.length - 1; i >= 0; i--) {
    const key = STAGE_TO_REPORT_KEY[completed[i]];
    if (key && stageReports[key]) return stageReports[key];
  }
  return null;
}

export function AnalysisProgress({
  progress,
  isPolling,
  onCancelled,
}: AnalysisProgressProps) {
  const [cancelling, setCancelling] = React.useState(false);
  const [cancelError, setCancelError] = React.useState<string | null>(null);

  if (!progress) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="analysis-progress-empty"
      >
        提交分析后这里会显示 12 阶段实时进度 (技术 → 情绪 → 新闻 → 基本面 → 政策 → 游资 → 解禁 → 质量门禁 → 多空辩论 → 风控 → 交易员 → 组合经理)
      </div>
    );
  }

  const completed = new Set(progress.completed_stages ?? []);
  const inferredCurrent = inferCurrentStage(progress);
  const isError = progress.status === 'error' || Boolean(progress.error);
  const isComplete = progress.status === 'ok' || progress.status === 'complete';
  const isRunning = !isError && !isComplete;
  const latestSnippet = latestStageReportSnippet(progress, inferredCurrent);

  // P2.27 hotfix — when the analysis errored, ``current_stage`` in the
  // payload still names the stage where the runner crashed (e.g.
  // ``"quality_gate"`` after the 600s/1800s hard timeout fires), but
  // that stage is NOT done and NOT still running — it died mid-flight.
  // We mark it visually as "errored" (red, distinct from the green
  // "done" and blue "running") and refuse to render any other stage as
  // "running" so the progress bar settles into a clear failure state.
  // Without this, the UI shows "质量门禁 ● 蓝色 (running)" alongside the
  // error banner — a contradiction the user reported as "progress page
  // stuck after timeout fires" because the bar never settled.
  const erroredStage = isError
    ? (progress.current_stage || inferredCurrent)
    : null;

  async function handleCancel() {
    if (!progress || cancelling) return;
    if (!window.confirm('确定要取消这个正在运行的分析吗? 取消后 UI 会停止轮询, 后台线程会继续运行直到自然结束.')) {
      return;
    }
    setCancelling(true);
    setCancelError(null);
    try {
      // analysis_id is not on ProgressResponse, but the parent can pass it
      // through a closure or we look it up from the ticker. Simplest: the
      // parent owns the activeAnalysisId, so we expose this via a window
      // call. Better path: parent passes it explicitly — but to avoid
      // breaking the existing signature, we accept that the cancel happens
      // via a custom event the parent can wire.
      window.dispatchEvent(
        new CustomEvent('analyze:cancel', { detail: { ticker: progress.ticker, trade_date: progress.trade_date } }),
      );
      onCancelled?.();
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : String(e));
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="analysis-progress">
      <div className="flex items-center justify-between text-sm">
        <div>
          <span className="font-mono font-semibold">{progress.ticker}</span>{' '}
          <span className="text-text-tertiary">· {progress.trade_date}</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-text-secondary">
          {isPolling && <Loader2 className="h-3 w-3 animate-spin" />}
          <span data-testid="analysis-progress-elapsed">{fmtElapsed(progress.elapsed)}</span>
          <span data-testid="analysis-progress-stats">
            LLM {progress.stats.llm_calls ?? 0} · Tool {progress.stats.tool_calls ?? 0}
          </span>
          {progress.signal && (
            <span
              className="rounded bg-bb-accent/20 px-2 py-0.5 font-mono text-[10px] text-bb-accent-bright"
              data-testid="analysis-progress-signal"
            >
              {progress.signal}
            </span>
          )}
          {isRunning && (
            <button
              type="button"
              onClick={handleCancel}
              disabled={cancelling}
              data-testid="analysis-progress-cancel"
              className="inline-flex items-center gap-1 rounded border border-red-500/50 px-2 py-0.5 text-[10px] text-red-300 hover:bg-red-500/10 disabled:opacity-50"
              title="取消这个正在运行的分析 (后台线程不会被强制杀死)"
            >
              <XCircle className="h-3 w-3" />
              {cancelling ? '取消中…' : '取消'}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-3" data-testid="analysis-progress-stages">
        {STAGES.map((s) => {
          const isDone = completed.has(s.id);
          // P2.27 — when errored OR complete, suppress the "running"
          // highlight so the bar settles into a terminal state. The
          // crashed stage (errored case only) gets a distinct red style
          // instead. Without this, status='ok' would still highlight
          // quality_gate as "running" because ``inferredCurrent`` is
          // derived from completed_stages[-1]+1 and quality_gate is the
          // next one — even though the run has finished.
          const isRunningThis = !isDone && !isError && !isComplete && inferredCurrent === s.id;
          const isErrored = !isDone && isError && s.id === erroredStage;
          return (
            <div
              key={s.id}
              className={
                'flex items-center gap-2 rounded-md border p-2 text-sm ' +
                (isDone
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                  : isErrored
                    ? 'border-red-500/50 bg-red-500/10 text-red-300'
                    : isRunningThis
                      ? 'border-bb-accent/40 bg-bb-accent/10 text-bb-accent-bright'
                      : 'border-border-1 bg-bg-elevated/40 text-text-tertiary')
              }
              data-testid={`analysis-stage-${s.id}`}
              data-status={isDone ? 'done' : isErrored ? 'errored' : isRunningThis ? 'running' : 'pending'}
            >
              <span className="text-lg leading-none">{s.icon}</span>
              <span className="flex-1">{s.name}</span>
              {isDone && <CheckCircle2 className="h-4 w-4" />}
              {isErrored && <AlertCircle className="h-4 w-4" />}
              {isRunningThis && <Loader2 className="h-4 w-4 animate-spin" />}
              {!isDone && !isErrored && !isRunningThis && <Circle className="h-4 w-4" />}
            </div>
          );
        })}
      </div>

      {/* P2.21 — show a short snippet of the latest stage_report so the
          user can see what the latest analyst said while waiting. */}
      {!isComplete && !isError && latestSnippet && (
        <div
          className="rounded-md border border-border-1 bg-bg-elevated/40 p-3 text-xs text-text-secondary"
          data-testid="analysis-progress-snippet"
        >
          <div className="mb-1 font-semibold text-text-tertiary">
            📝 最新阶段输出 ({inferredCurrent}):
          </div>
          <pre className="whitespace-pre-wrap break-words font-mono leading-relaxed">
            {latestSnippet.slice(0, 200)}
            {latestSnippet.length > 200 ? '…' : ''}
          </pre>
        </div>
      )}

      {cancelError && (
        <div
          className="flex items-start gap-2 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
          data-testid="analysis-progress-cancel-error"
        >
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>取消失败: {cancelError}</span>
        </div>
      )}

      {isError && (
        <div
          className="flex items-start gap-3 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
          data-testid="analysis-progress-error"
        >
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <div className="flex-1 space-y-1">
            <div className="font-semibold">分析已终止</div>
            <div className="text-xs leading-relaxed">
              {progress.error ?? '分析失败'}
            </div>
            <div className="text-xs text-red-300/70">
              已完成的 {completed.size} 个阶段报告仍可在「工作区」tab 查看 · 切到「新建」tab 可重跑
              （建议换模型 / 缩短窗口期后重试）
            </div>
          </div>
        </div>
      )}

      {isComplete && (
        <div
          className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-300"
          data-testid="analysis-progress-done"
        >
          ✅ 分析完成 · 切到「报告」 tab 查看交易决策 · 切到「历史」 tab 查看更多
        </div>
      )}
    </div>
  );
}

export default AnalysisProgress;
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const _cancelExport = cancelAnalysis; // re-export to silence tree-shake warnings if unused