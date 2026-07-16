/**
 * ScheduleRuns — history tab. Aggregates runs across all schedules.
 *
 * Mirrors web/components/schedule_panel.py::render_schedule_runs. The
 * backend exposes runs via /api/schedule/{schedule_id} (last 20 per sched),
 * so this component fetches the list endpoint and then loads the detail
 * for each schedule. To avoid N+1 calls, we cap the aggregation at the
 * first 5 schedules (sufficient for the recent-history pane).
 *
 * Uses React Query (useQuery per schedule_id) so vitest can stub the data
 * via `vi.mock('@tanstack/react-query', ...)` — matching the pattern used
 * by PortfolioPage / BatchPage / HistoryPage tests.
 */
import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { Schedule, ScheduleRun } from '@/api/schedule';
import { getSchedule } from '@/api/schedule';

interface ScheduleRunsProps {
  schedules: Schedule[];
  isLoading?: boolean;
  error?: string | null;
}

interface RunRow extends ScheduleRun {
  schedule_name: string;
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

const MAX_SCHEDULES = 5;

export function ScheduleRuns({ schedules, isLoading, error }: ScheduleRunsProps) {
  const targets = React.useMemo(
    () => schedules.slice(0, MAX_SCHEDULES),
    [schedules],
  );
  const scheduleIdsKey = targets.map((s) => s.schedule_id).join('|');

  // One useQuery per schedule_id (max 5). Each call uses the same queryKey
  // prefix `'schedule-runs'` + id so the mock can pattern-match on prefix.
  const ids = targets.map((s) => s.schedule_id);

  return (
    <ScheduleRunsInner
      scheduleIds={ids}
      scheduleNames={Object.fromEntries(targets.map((s) => [s.schedule_id, s.name]))}
      isLoading={isLoading}
      error={error}
      resetKey={scheduleIdsKey}
    />
  );
}

interface ScheduleRunsInnerProps {
  scheduleIds: string[];
  scheduleNames: Record<string, string>;
  isLoading?: boolean;
  error?: string | null;
  resetKey: string;
}

function ScheduleRunsInner({
  scheduleIds, scheduleNames, isLoading, error, resetKey,
}: ScheduleRunsInnerProps) {
  // Single useQuery keyed on the joined list of schedule_ids so React Query
  // re-fetches whenever the selection changes. queryFn fans out the per-id
  // getSchedule calls (Promise.all with per-call try/catch, matching the
  // previous useEffect behavior) and returns the aggregated rows.
  const runsQuery = useQuery({
    queryKey: ['schedule-runs', resetKey],
    queryFn: async (): Promise<RunRow[]> => {
      if (!scheduleIds.length) return [];
      const allRows: RunRow[] = [];
      await Promise.all(
        scheduleIds.map(async (sid) => {
          try {
            const detail = await getSchedule(sid);
            for (const r of detail.runs) {
              allRows.push({ ...r, schedule_name: scheduleNames[sid] ?? sid });
            }
          } catch {
            // skip failed schedule; do not abort the whole list
          }
        }),
      );
      allRows.sort((a, b) => b.started_at - a.started_at);
      return allRows;
    },
    enabled: scheduleIds.length > 0,
    refetchInterval: 3000,
  });

  const runs = runsQuery.data ?? [];
  const loadingRuns = runsQuery.isLoading || runsQuery.isFetching;
  const loadError =
    runsQuery.error instanceof Error ? runsQuery.error.message : null;

  if (isLoading || loadingRuns) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="schedule-runs-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载运行历史…
      </div>
    );
  }
  if (error || loadError) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="schedule-runs-error"
      >
        加载运行历史失败: {error || loadError}
      </div>
    );
  }
  if (!runs.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="schedule-runs-empty"
      >
        暂无运行历史。
      </div>
    );
  }

  return (
    <div data-testid="schedule-runs">
      <Table data-testid="schedule-runs-table">
        <TableHeader>
          <TableRow>
            <TableHead>任务</TableHead>
            <TableHead>run_id</TableHead>
            <TableHead>开始</TableHead>
            <TableHead className="text-right">耗时 (s)</TableHead>
            <TableHead className="text-right">ticker</TableHead>
            <TableHead>状态</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.slice(0, 50).map((r) => (
            <TableRow key={`${r.schedule_id}-${r.run_id}`} data-testid={`schedule-runs-row-${r.run_id}`}>
              <TableCell className="text-xs">{r.schedule_name}</TableCell>
              <TableCell className="font-mono text-xs">{r.run_id}</TableCell>
              <TableCell className="text-xs">{fmtTs(r.started_at)}</TableCell>
              <TableCell className="text-right font-mono text-xs">{r.duration?.toFixed(2) ?? '—'}</TableCell>
              <TableCell className="text-right font-mono text-xs">{r.ticker_count}</TableCell>
              <TableCell className={`text-xs ${statusColor(r.status)}`}>
                {r.status}
                {r.error && <span className="ml-2 text-red-300">· {r.error.slice(0, 50)}</span>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default ScheduleRuns;