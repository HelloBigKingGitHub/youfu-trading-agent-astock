import * as React from 'react';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { BatchSummaryResponse } from '@/api/batch';

// CSV-ready summary view — mirrors `web/components/batch_panel.py`
// `_summary_to_csv` lines 123-141 plus the `📥 导出汇总` button at line 199.
//
// React renders the same row shape + a "导出汇总" download button that
// builds the CSV in-browser (same column order as Streamlit).

export interface BatchSummaryProps {
  summary: BatchSummaryResponse;
  onDownloadCsv: () => void;
}

const STATUS_BADGE: Record<string, string> = {
  completed: 'bg-bb-up/20 text-bb-up',
  error: 'bg-bb-down/20 text-bb-down',
  running: 'bg-bb-accent/20 text-bb-accent',
  pending: 'bg-text-tertiary/20 text-text-tertiary',
  cancelled: 'bg-text-tertiary/20 text-text-tertiary',
};

export function BatchSummary({ summary, onDownloadCsv }: BatchSummaryProps) {
  const { batch_id, batch_status, rows } = summary;
  return (
    <div className="space-y-3" data-testid="batch-summary">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-text-secondary">
          Batch <code className="font-mono text-text-primary">{batch_id}</code>
          {' · '}
          状态 <span className="font-mono">{batch_status}</span>
          {' · '}
          共 {rows.length} 条
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onDownloadCsv}
          data-testid="batch-export-csv"
        >
          📥 导出汇总
        </Button>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ticker</TableHead>
              <TableHead>trade_date</TableHead>
              <TableHead>status</TableHead>
              <TableHead>signal</TableHead>
              <TableHead className="text-right">stages</TableHead>
              <TableHead className="text-right">elapsed</TableHead>
              <TableHead>error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={`${row.ticker}-${row.trade_date}`}>
                <TableCell className="font-mono">{row.ticker}</TableCell>
                <TableCell className="font-mono">{row.trade_date}</TableCell>
                <TableCell>
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${STATUS_BADGE[row.status] || STATUS_BADGE.pending}`}
                  >
                    {row.status}
                  </span>
                </TableCell>
                <TableCell className="font-mono">{row.signal || '—'}</TableCell>
                <TableCell className="text-right font-mono">{row.completed_stages_count}</TableCell>
                <TableCell className="text-right font-mono">{row.elapsed_seconds}s</TableCell>
                <TableCell className="max-w-[280px] truncate text-xs text-text-secondary">
                  {row.error || '—'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}