/**
 * ScheduleList — 总览 tab. Renders all schedules with status + action buttons.
 *
 * Mirrors web/components/schedule_panel.py::render_schedule_list. Columns:
 *   name / cron / source / enabled / last_run / next_run / 操作 (run/pause/resume/delete)
 *
 * The detail click is delegated to the parent (SchedulePage) so this component
 * stays a pure presentational list. Action buttons fire the API directly and
 * invalidate the parent query via the onMutated callback.
 */
import * as React from 'react';
import { Loader2, Play, Pause, PlayCircle, Trash2, ChevronRight } from 'lucide-react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import type { Schedule } from '@/api/schedule';

interface ScheduleListProps {
  schedules: Schedule[];
  isLoading?: boolean;
  error?: string | null;
  onSelect?: (scheduleId: string) => void;
  selectedId?: string | null;
  onAction?: (action: 'run' | 'pause' | 'resume' | 'delete', scheduleId: string) => void;
  busyId?: string | null;
}

function fmtTs(ts: number | null): string {
  if (!ts || !Number.isFinite(ts)) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', { hour12: false });
}

function statusColor(s: string): string {
  switch (s) {
    case 'ok': return 'text-emerald-400';
    case 'error': return 'text-red-400';
    case 'running': return 'text-amber-400';
    case 'never': return 'text-text-tertiary';
    default: return 'text-text-secondary';
  }
}

export function ScheduleList({
  schedules, isLoading, error, onSelect, selectedId, onAction, busyId,
}: ScheduleListProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="schedule-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载定时任务…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="schedule-error"
      >
        加载定时任务失败: {error}
      </div>
    );
  }
  if (!schedules.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="schedule-empty"
      >
        暂无定时任务。切到「创建」 tab 新建一个。
      </div>
    );
  }
  return (
    <div data-testid="schedule-table-wrap">
      <Table data-testid="schedule-table">
        <TableHeader>
          <TableRow>
            <TableHead>名称</TableHead>
            <TableHead>Cron</TableHead>
            <TableHead>来源</TableHead>
            <TableHead>通知</TableHead>
            <TableHead className="text-center">启用</TableHead>
            <TableHead>上次</TableHead>
            <TableHead>下次</TableHead>
            <TableHead className="text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {schedules.map((s) => {
            const isBusy = busyId === s.schedule_id;
            return (
              <TableRow
                key={s.schedule_id}
                data-testid={`schedule-row-${s.schedule_id}`}
                onClick={() => onSelect?.(s.schedule_id)}
                className={selectedId === s.schedule_id ? 'bg-bg-elevated' : 'cursor-pointer hover:bg-bg-elevated/60'}
              >
                <TableCell>
                  <div className="flex items-center gap-2">
                    {selectedId === s.schedule_id && <ChevronRight className="h-3 w-3 text-bb-accent" />}
                    <span className="font-medium">{s.name}</span>
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs">{s.cron_expr || '—'}</TableCell>
                <TableCell className="text-xs">{s.source_summary || s.source_type}</TableCell>
                <TableCell className="text-xs text-text-secondary">
                  {(s.notify_channels || []).join(', ') || '—'}
                </TableCell>
                <TableCell className="text-center">
                  <span className={s.enabled ? 'text-emerald-400' : 'text-text-tertiary'}>
                    {s.enabled ? '●' : '○'}
                  </span>
                </TableCell>
                <TableCell className="text-xs">
                  <div>{fmtTs(s.last_run_at)}</div>
                  <div className={`text-[10px] ${statusColor(s.last_run_status)}`}>
                    {s.last_run_status}
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs">{fmtTs(s.next_run_at)}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={(e) => { e.stopPropagation(); onAction?.('run', s.schedule_id); }}
                      disabled={isBusy}
                      data-testid={`schedule-run-${s.schedule_id}`}
                      title="立即执行"
                    >
                      <Play className="h-3 w-3" />
                    </Button>
                    {s.enabled ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); onAction?.('pause', s.schedule_id); }}
                        disabled={isBusy}
                        data-testid={`schedule-pause-${s.schedule_id}`}
                        title="暂停"
                      >
                        <Pause className="h-3 w-3" />
                      </Button>
                    ) : (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={(e) => { e.stopPropagation(); onAction?.('resume', s.schedule_id); }}
                        disabled={isBusy}
                        data-testid={`schedule-resume-${s.schedule_id}`}
                        title="恢复"
                      >
                        <PlayCircle className="h-3 w-3" />
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`删除定时任务「${s.name}」?`)) {
                          onAction?.('delete', s.schedule_id);
                        }
                      }}
                      disabled={isBusy}
                      data-testid={`schedule-delete-${s.schedule_id}`}
                      title="删除"
                    >
                      <Trash2 className="h-3 w-3 text-red-400" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}