/**
 * ScheduleDetail — single schedule metadata + recent 20 runs.
 *
 * Mirrors web/components/schedule_panel.py::render_schedule_detail. Shows
 * the Schedule dict fields on top and the recent ScheduleRun list below.
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { Schedule, ScheduleRun } from '@/api/schedule';

interface ScheduleDetailProps {
  schedule: Schedule | null;
  runs: ScheduleRun[];
  isLoading?: boolean;
  error?: string | null;
}

function fmtTs(ts: number | null | undefined): string {
  if (!ts || !Number.isFinite(ts)) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN', { hour12: false });
}

function statusColor(s: string): string {
  switch (s) {
    case 'ok': return 'text-emerald-400';
    case 'error': return 'text-red-400';
    case 'running': return 'text-amber-400';
    default: return 'text-text-secondary';
  }
}

export function ScheduleDetail({ schedule, runs, isLoading, error }: ScheduleDetailProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="schedule-detail-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载详情…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="schedule-detail-error"
      >
        加载详情失败: {error}
      </div>
    );
  }
  if (!schedule) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="schedule-detail-empty"
      >
        请从左侧列表选择一个定时任务查看详情。
      </div>
    );
  }
  return (
    <div data-testid="schedule-detail" className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-3">
        <div>
          <div className="text-text-tertiary text-xs">ID</div>
          <div className="font-mono">{schedule.schedule_id}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">名称</div>
          <div>{schedule.name}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">Cron</div>
          <div className="font-mono text-xs">{schedule.cron_expr || '—'}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">来源</div>
          <div>{schedule.source_summary}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">通知</div>
          <div className="text-xs">{(schedule.notify_channels || []).join(', ') || '—'}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">状态</div>
          <div>{schedule.enabled ? '● 启用' : '○ 禁用'}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">上次</div>
          <div className="text-xs">{fmtTs(schedule.last_run_at)}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">下次</div>
          <div className="text-xs">{fmtTs(schedule.next_run_at)}</div>
        </div>
        <div>
          <div className="text-text-tertiary text-xs">创建时间</div>
          <div className="text-xs">{fmtTs(schedule.created_at)}</div>
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold mb-2">最近运行 ({(runs || []).length})</h3>
        {(runs || []).length === 0 ? (
          <div className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-4 text-center text-sm text-text-tertiary">
            暂无运行记录。
          </div>
        ) : (
          <Table data-testid="schedule-detail-runs">
            <TableHeader>
              <TableRow>
                <TableHead>run_id</TableHead>
                <TableHead>开始</TableHead>
                <TableHead className="text-right">耗时 (s)</TableHead>
                <TableHead className="text-right">ticker</TableHead>
                <TableHead>状态</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((r) => (
                <TableRow key={r.run_id} data-testid={`schedule-detail-run-${r.run_id}`}>
                  <TableCell className="font-mono text-xs">{r.run_id}</TableCell>
                  <TableCell className="text-xs">{fmtTs(r.started_at)}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{r.duration?.toFixed(2) ?? '—'}</TableCell>
                  <TableCell className="text-right font-mono text-xs">{r.ticker_count}</TableCell>
                  <TableCell className={`text-xs ${statusColor(r.status)}`}>
                    {r.status}
                    {r.error && <span className="ml-2 text-red-300">· {r.error.slice(0, 60)}</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}