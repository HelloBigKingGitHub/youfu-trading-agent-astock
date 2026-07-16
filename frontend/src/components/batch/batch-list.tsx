import * as React from 'react';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { BatchListItem } from '@/api/batch';

// 历史 batch 列表 — mirrors the right-rail batch history concept in
// `web/components/batch_panel.py` (the active_batch_id block at line 191-206).
//
// Both UIs share the same backend queue (backend.core.job_queue), so listing
// from /api/batch gives a unified chronological view across React + Streamlit.

export interface BatchListProps {
  batches: BatchListItem[];
  activeBatchId?: string | null;
  onSelect: (batchId: string) => void;
  isLoading?: boolean;
}

function formatTimestamp(seconds: number | undefined): string {
  if (!seconds) return '—';
  const d = new Date(seconds * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function BatchList({ batches, activeBatchId, onSelect, isLoading }: BatchListProps) {
  if (isLoading) {
    return (
      <div
        data-testid="batch-list-loading"
        className="rounded-lg border border-border-1 bg-bg-elevated/40 p-4 text-sm text-text-tertiary"
      >
        加载历史 batch…
      </div>
    );
  }
  if (!batches.length) {
    return (
      <div
        data-testid="batch-list-empty"
        className="rounded-lg border border-dashed border-border-2 bg-bg-elevated/40 p-4 text-center text-sm text-text-tertiary"
      >
        暂无历史 batch
      </div>
    );
  }
  return (
    <div className="overflow-x-auto" data-testid="batch-list">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>batch_id</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">完成 / 总</TableHead>
            <TableHead className="text-right">失败</TableHead>
            <TableHead>创建时间</TableHead>
            <TableHead>操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {batches.map((b) => {
            const isActive = activeBatchId === b.batch_id;
            return (
              <TableRow
                key={b.batch_id}
                data-testid={`batch-list-row-${b.batch_id}`}
                className={isActive ? 'bg-bb-accent/10' : ''}
              >
                <TableCell className="font-mono text-xs">{b.batch_id}</TableCell>
                <TableCell>
                  <span className="text-xs">{b.batch_status}</span>
                </TableCell>
                <TableCell className="text-right font-mono">
                  {b.finished_count} / {b.total}
                </TableCell>
                <TableCell className="text-right font-mono">
                  {b.error_count > 0
                    ? <span className="text-bb-down">{b.error_count}</span>
                    : <span className="text-text-tertiary">0</span>}
                </TableCell>
                <TableCell className="text-xs text-text-secondary">
                  {formatTimestamp(b.created_at)}
                </TableCell>
                <TableCell>
                  <Button
                    type="button"
                    variant={isActive ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => onSelect(b.batch_id)}
                    data-testid={`batch-list-select-${b.batch_id}`}
                  >
                    {isActive ? '查看中' : '查看'}
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}