import * as React from 'react';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { BatchJob, JobStatus } from '@/api/batch';

// Per-ticker progress table — mirrors `web/components/batch_panel.py`
// `_render_jobs_table` lines 374-448:
//
//   h1-h6 st.columns -> header row "Ticker / Status / Current stage /
//                                 Elapsed / Signal / Action"
//   for j in jobs:
//     st.columns -> per-job cells with retry / view-report buttons
//
// The React equivalent renders a real <table> via shadcn Table. We add a
// status pill (matches `_STATUS_ICON` emoji mapping in batch_panel.py) and
// an inline "重试" button for errored rows + "查看报告" button for completed
// rows (matches the Streamlit popover / button behaviour).

export interface BatchProgressProps {
  jobs: BatchJob[];
  onRetry: (job: BatchJob) => void;
  onViewReport: (job: BatchJob) => void;
  isRetrying?: (jobId: string) => boolean;
}

const STATUS_ICON: Record<JobStatus, string> = {
  completed: '✅',
  error: '❌',
  running: '🔄',
  pending: '⏳',
  cancelled: '⊘',
};

const STATUS_COLOR: Record<JobStatus, string> = {
  completed: 'text-bb-up',
  error: 'text-bb-down',
  running: 'text-bb-accent',
  pending: 'text-text-tertiary',
  cancelled: 'text-text-tertiary',
};

function formatElapsed(seconds: number | undefined): string {
  if (!seconds) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function signalKind(signal: string): 'buy' | 'sell' | 'hold' | 'neutral' {
  const s = (signal || '').toUpperCase();
  if (s.includes('BUY')) return 'buy';
  if (s.includes('SELL')) return 'sell';
  if (s.includes('HOLD')) return 'hold';
  return 'neutral';
}

export function BatchProgress({
  jobs, onRetry, onViewReport, isRetrying,
}: BatchProgressProps) {
  if (!jobs.length) {
    return (
      <div
        data-testid="batch-progress-empty"
        className="rounded-lg border border-dashed border-border-2 bg-bg-elevated/50 p-6 text-center text-sm text-text-tertiary"
      >
        batch 中暂无 job。
      </div>
    );
  }
  return (
    <div className="overflow-x-auto" data-testid="batch-progress">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[120px]">Ticker</TableHead>
            <TableHead className="w-[140px]">Status</TableHead>
            <TableHead className="w-[160px]">Current stage</TableHead>
            <TableHead className="w-[80px]">Elapsed</TableHead>
            <TableHead className="w-[100px]">Signal</TableHead>
            <TableHead>Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => {
            const status: JobStatus = (job.status || 'pending') as JobStatus;
            const retrying = isRetrying?.(job.job_id) ?? false;
            return (
              <TableRow key={job.job_id} data-testid={`batch-job-row-${job.ticker}`}>
                <TableCell className="font-mono font-semibold">{job.ticker}</TableCell>
                <TableCell>
                  <span className={STATUS_COLOR[status]} data-testid={`batch-job-status-${job.ticker}`}>
                    {STATUS_ICON[status]} {status}
                  </span>
                </TableCell>
                <TableCell className="text-text-secondary">
                  {job.current_stage || '—'}
                </TableCell>
                <TableCell className="font-mono text-text-secondary">
                  {formatElapsed(job.elapsed)}
                </TableCell>
                <TableCell>
                  {job.signal ? (
                    <span
                      className={`bb-signal bb-signal--${signalKind(job.signal)}`}
                      data-testid={`batch-job-signal-${job.ticker}`}
                    >
                      {job.signal}
                    </span>
                  ) : (
                    <span className="text-text-tertiary">—</span>
                  )}
                </TableCell>
                <TableCell>
                  {status === 'error' && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={retrying}
                      onClick={() => onRetry(job)}
                      data-testid={`batch-retry-${job.ticker}`}
                    >
                      {retrying ? '重试中…' : `🔄 重试 ${job.ticker}`}
                    </Button>
                  )}
                  {status === 'completed' && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => onViewReport(job)}
                      data-testid={`batch-view-${job.ticker}`}
                    >
                      📄 查看报告
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}