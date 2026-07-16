/**
 * AnalysisProgress — live progress bar across the 7 pipeline stages.
 *
 * Mirrors web/components/analyze_panel.py::render_progress_block. Reads the
 * ``current_stage`` + ``completed_stages`` from the ProgressResponse and
 * renders one progress card per stage with running/done/pending markers.
 */
import * as React from 'react';
import { CheckCircle2, Circle, Loader2, AlertCircle } from 'lucide-react';
import type { ProgressResponse } from '@/api/analyze';

interface AnalysisProgressProps {
  progress: ProgressResponse | null;
  isPolling?: boolean;
}

interface StageDef {
  id: string;
  name: string;
  icon: string;
}

const STAGES: StageDef[] = [
  { id: 'market', name: '技术分析', icon: '📊' },
  { id: 'social', name: '情绪分析', icon: '💬' },
  { id: 'news', name: '新闻舆情', icon: '📰' },
  { id: 'fundamentals', name: '基本面', icon: '📋' },
  { id: 'policy', name: '政策分析', icon: '🏛️' },
  { id: 'hot_money', name: '游资追踪', icon: '🔥' },
  { id: 'lockup', name: '解禁监控', icon: '🔒' },
];

function fmtElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m${s}s`;
}

export function AnalysisProgress({ progress, isPolling }: AnalysisProgressProps) {
  if (!progress) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="analysis-progress-empty"
      >
        提交分析后这里会显示 7 阶段实时进度 (技术 → 情绪 → 新闻 → 基本面 → 政策 → 游资 → 解禁)
      </div>
    );
  }

  const completed = new Set(progress.completed_stages ?? []);
  const current = progress.current_stage ?? '';
  const isError = progress.status === 'error' || Boolean(progress.error);
  const isComplete = progress.status === 'ok' || progress.status === 'complete';

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
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-2" data-testid="analysis-progress-stages">
        {STAGES.map((s) => {
          const isDone = completed.has(s.id);
          const isRunning = !isDone && current === s.id;
          return (
            <div
              key={s.id}
              className={
                'flex items-center gap-2 rounded-md border p-2 text-sm ' +
                (isDone
                  ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                  : isRunning
                    ? 'border-bb-accent/40 bg-bb-accent/10 text-bb-accent-bright'
                    : 'border-border-1 bg-bg-elevated/40 text-text-tertiary')
              }
              data-testid={`analysis-stage-${s.id}`}
              data-status={isDone ? 'done' : isRunning ? 'running' : 'pending'}
            >
              <span className="text-lg leading-none">{s.icon}</span>
              <span className="flex-1">{s.name}</span>
              {isDone && <CheckCircle2 className="h-4 w-4" />}
              {isRunning && <Loader2 className="h-4 w-4 animate-spin" />}
              {!isDone && !isRunning && <Circle className="h-4 w-4" />}
            </div>
          );
        })}
      </div>

      {isError && (
        <div
          className="flex items-start gap-2 rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
          data-testid="analysis-progress-error"
        >
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{progress.error ?? '分析失败'}</span>
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