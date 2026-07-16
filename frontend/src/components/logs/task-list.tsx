import * as React from 'react';
import { Loader2, Clock } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge, signalLabel, signalVariant, statusLabel, statusVariant } from '@/components/ui/badge';
import type { LogTaskSummary } from '@/api/logs';

// TaskList — right column's task list for the currently-selected ticker.
// Mirrors `web/components/logs_panel.py::_render_selected_ticker` +
// `_render_task_card` (the collapsed row part — chunk rendering lives in
// ChunkViewer):
//   - Sorted by trade_date desc, then task_dir_name asc (stable).
//   - Each task card shows date · status · signal · chunk counts.
//   - Clicking a row fires onSelect(task) → ChunkViewer mounts.
//
// is_legacy tasks are tagged so the user knows the chunk stream isn't
// available (same UX as streamlit's caption warning).

interface TaskListProps {
  ticker: string | null;
  tasks: LogTaskSummary[];
  selectedTask: string | null;
  onSelect: (task: LogTaskSummary) => void;
  isLoading?: boolean;
  error?: string | null;
}

function formatElapsed(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return '—';
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m${String(s).padStart(2, '0')}s`;
}

function compareTasks(a: LogTaskSummary, b: LogTaskSummary): number {
  const ad = a.trade_date ?? '';
  const bd = b.trade_date ?? '';
  if (ad !== bd) return bd.localeCompare(ad);
  return (a.task_dir_name ?? '').localeCompare(b.task_dir_name ?? '');
}

export const TaskList = React.memo(function TaskList({
  ticker,
  tasks,
  selectedTask,
  onSelect,
  isLoading,
  error,
}: TaskListProps) {
  if (!ticker) {
    return (
      <div
        className="flex h-full items-center justify-center text-text-tertiary text-sm py-12"
        data-testid="task-list-prompt"
      >
        ← 选择左侧 ticker 查看任务
      </div>
    );
  }

  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="task-list-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载 tasks…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="task-list-error"
      >
        加载任务列表失败: {error}
      </div>
    );
  }

  if (!tasks.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
        data-testid="task-list-empty"
      >
        此 ticker 暂无任务
      </div>
    );
  }

  const sorted = [...tasks].sort(compareTasks);

  return (
    <div
      className="flex flex-col gap-2"
      data-testid="task-list"
      aria-label={`${ticker} 的任务列表`}
    >
      <div className="text-[10px] uppercase tracking-wider text-text-tertiary px-1">
        Tasks for {ticker} ({sorted.length})
      </div>
      <div className="flex flex-col gap-2 max-h-[40vh] overflow-y-auto pr-1">
        {sorted.map((task) => {
          const isActive = selectedTask === task.task_dir_name;
          const cc = task.chunk_counts || { llm: 0, tool: 0, agent_output: 0 };
          return (
            <button
              key={task.task_dir_name}
              type="button"
              onClick={() => onSelect(task)}
              data-testid={`task-card-${task.task_dir_name}`}
              aria-pressed={isActive}
              className={cn(
                'flex flex-col gap-1.5 rounded-md border p-3 text-left transition-colors',
                isActive
                  ? 'border-bb-accent/60 bg-bb-accent-glow text-text-primary shadow-[inset_3px_0_0_0_var(--bb-accent-bright)]'
                  : 'border-border-1 bg-bg-elevated hover:bg-bg-surface text-text-primary'
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-semibold text-sm">
                  {task.trade_date} · {task.task_dir_name}
                </span>
                <Badge
                  variant={statusVariant(task.status)}
                  className={cn(
                    'shrink-0',
                    (task.status ?? '').toLowerCase() === 'running' && 'animate-pulse'
                  )}
                >
                  {statusLabel(task.status)}
                </Badge>
              </div>

              <div className="flex items-center justify-between gap-2 text-[11px] text-text-secondary">
                <div className="flex items-center gap-1.5">
                  <Badge variant={signalVariant(task.signal)}>
                    {signalLabel(task.signal)}
                  </Badge>
                  {task.is_legacy && (
                    <span
                      className="text-yellow-500 text-[10px] uppercase tracking-wider"
                      title="Legacy task (pre-v0.3.0). 完整 state 在 .tradingagents/logs/{ticker}/TradingAgentsStrategy_logs/full_states_log_*.json"
                    >
                      legacy
                    </span>
                  )}
                </div>
                <span className="flex items-center gap-1 font-mono text-text-tertiary">
                  <Clock className="h-3 w-3" />
                  {formatElapsed(task.elapsed_sec)}
                </span>
              </div>

              <div
                className="flex items-center gap-3 text-[11px] font-mono text-text-tertiary"
                data-testid={`task-counts-${task.task_dir_name}`}
              >
                <span>LLM {cc.llm ?? 0}</span>
                <span>·</span>
                <span>Tool {cc.tool ?? 0}</span>
                <span>·</span>
                <span>Output {cc.agent_output ?? 0}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
});