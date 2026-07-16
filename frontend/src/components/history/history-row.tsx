import * as React from 'react';
import { FileText, RotateCw, Trash2, Loader2 } from 'lucide-react';
import {
  Badge,
  signalLabel,
  signalVariant,
  statusLabel,
  statusVariant,
} from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  TableRow,
  TableCell,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import type { HistoryItem } from '@/api/history';

// Single history row in the HistoryPage table. Mirrors streamlit's
// 8-column row layout ([ticker·date, signal, status, elapsed, stages,
// error, retry, actions]) but consolidated into 6 React cells (signal/status
// use Badge components; stages shown via running badge detail; retry is
// implicit in the "rerun" action; the "view report" + "delete" + "rerun"
// buttons live in the actions cell).
//
// All three actions emit upward through callbacks — the page wires them to
// the appropriate React Query mutations.

interface HistoryRowProps {
  item: HistoryItem;
  onView: (item: HistoryItem) => void;
  onRerun: (item: HistoryItem) => void;
  onDelete: (item: HistoryItem) => void;
  pendingRerun?: boolean;
  pendingDelete?: boolean;
  onClick?: (item: HistoryItem) => void;
}

function formatElapsed(elapsed: number): string {
  if (!elapsed || elapsed < 0) return '-';
  const total = Math.floor(elapsed);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function canRerun(item: HistoryItem): boolean {
  const status = (item.status ?? '').toLowerCase();
  if (status === 'error' || status === 'pending') return true;
  if (status === 'running' && (!item.completed_stages || item.completed_stages.length === 0))
    return true;
  return false;
}

export const HistoryRow = React.memo(function HistoryRow({
  item,
  onView,
  onRerun,
  onDelete,
  pendingRerun,
  pendingDelete,
  onClick,
}: HistoryRowProps) {
  const aid = item.analysis_id || '-';
  const stageCount = item.completed_stages?.length ?? 0;
  const status = (item.status ?? '').toLowerCase();
  const hasError = !!item.error && status === 'error';

  return (
    <TableRow
      data-testid={`history-row-${aid}`}
      className={cn(onClick && 'cursor-pointer')}
      onClick={onClick ? () => onClick(item) : undefined}
    >
      {/* ticker · date · aid */}
      <TableCell>
        <div className="flex flex-col gap-1 leading-tight">
          <span className="font-mono font-semibold text-text-primary">
            {item.ticker || '-'}
          </span>
          <span className="text-xs text-text-secondary">
            {item.trade_date || '-'}
          </span>
          <span className="font-mono text-[10px] text-text-tertiary">
            …{aid.slice(-8)}
          </span>
        </div>
      </TableCell>

      {/* signal */}
      <TableCell>
        <Badge variant={signalVariant(item.signal)} data-testid={`history-signal-${aid}`}>
          {signalLabel(item.signal)}
        </Badge>
      </TableCell>

      {/* status (with pulse on running) */}
      <TableCell>
        <Badge
          variant={statusVariant(item.status)}
          data-testid={`history-status-${aid}`}
          className={cn(status === 'running' && 'animate-pulse')}
        >
          {statusLabel(item.status)}
        </Badge>
      </TableCell>

      {/* elapsed */}
      <TableCell>
        <span className="font-mono text-sm">{formatElapsed(item.elapsed)}</span>
      </TableCell>

      {/* stages */}
      <TableCell>
        <span
          className="font-mono text-sm"
          title={item.completed_stages?.join(', ') || 'no stages yet'}
        >
          {stageCount}/11
        </span>
      </TableCell>

      {/* error snippet (cap 30 chars to match streamlit) */}
      <TableCell>
        {hasError ? (
          <span
            className="text-xs text-bb-up"
            title={item.error ?? ''}
            data-testid={`history-error-${aid}`}
          >
            🔴 {(item.error ?? '').slice(0, 30)}
            {(item.error ?? '').length > 30 ? '…' : ''}
          </span>
        ) : (
          <span className="text-text-tertiary text-xs">-</span>
        )}
      </TableCell>

      {/* actions */}
      <TableCell>
        <div className="flex items-center gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid={`history-view-${aid}`}
            onClick={(e) => {
              e.stopPropagation();
              onView(item);
            }}
            title="查看报告"
          >
            <FileText className="h-3.5 w-3.5" />
          </Button>
          {canRerun(item) && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid={`history-rerun-${aid}`}
              onClick={(e) => {
                e.stopPropagation();
                onRerun(item);
              }}
              disabled={pendingRerun}
              title="重新分析"
            >
              {pendingRerun ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCw className="h-3.5 w-3.5" />
              )}
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid={`history-delete-${aid}`}
            onClick={(e) => {
              e.stopPropagation();
              onDelete(item);
            }}
            disabled={pendingDelete}
            title="删除"
            className="hover:!bg-bb-up/10 hover:!text-bb-up hover:!border-bb-up/40"
          >
            {pendingDelete ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
});
