/**
 * TopStocksTable — top-N hot stock-picking strategies from np-ipick.
 *
 * Mirrors `web/components/sector_panel.py::_render_hot_strategies_table`:
 *   rank | heatValue | chg | question (the strategy description)
 *
 * The backend's `hot_strategies` list is already sorted by heatValue desc;
 * we re-sort defensively in case the backend changes ordering in the future.
 * Up (red) / down (green) follows A-share convention.
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import type { HotStrategy } from '@/api/sector';

interface TopStocksTableProps {
  strategies: HotStrategy[];
  isLoading?: boolean;
  error?: string | null;
}

function parseChg(chg: string): number | null {
  if (!chg) return null;
  const m = String(chg).match(/([+-]?[\d.]+)/);
  if (!m) return null;
  const v = parseFloat(m[1]);
  return Number.isFinite(v) ? v : null;
}

function chgColor(chg: number | null): string {
  if (chg === null || chg === 0) return 'text-text-secondary';
  return chg > 0 ? 'text-bb-up font-semibold' : 'text-bb-down font-semibold';
}

function chgBadgeVariant(chg: number | null): 'destructive' | 'success' | 'outline' {
  if (chg === null || chg === 0) return 'outline';
  return chg > 0 ? 'destructive' : 'success';
}

export const TopStocksTable = React.memo(function TopStocksTable({
  strategies,
  isLoading,
  error,
}: TopStocksTableProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="top-stocks-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载选股热度…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="top-stocks-error"
      >
        加载选股热度失败: {error}
      </div>
    );
  }

  if (!strategies.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
        data-testid="top-stocks-empty"
      >
        暂无选股热度数据
      </div>
    );
  }

  // Stable sort by rank asc (rank is the backend's natural order: heatValue desc).
  const sorted = [...strategies].sort((a, b) => {
    const ar = parseInt(String(a.rank ?? '999'), 10);
    const br = parseInt(String(b.rank ?? '999'), 10);
    return (ar || 999) - (br || 999);
  });

  return (
    <div className="rounded-md border border-border-1 bg-bg-surface" data-testid="top-stocks-table">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-14">排名</TableHead>
            <TableHead>股票代码</TableHead>
            <TableHead>中文名</TableHead>
            <TableHead className="text-right">热度</TableHead>
            <TableHead className="text-right">涨跌幅</TableHead>
            <TableHead>策略描述</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((s) => {
            const code = String(s.code ?? '');
            const name = String(s.name ?? '');
            const heat = s.heatValue ?? 0;
            const chg = parseChg(String(s.chg ?? ''));
            const question = String(s.question ?? '');
            return (
              <TableRow
                key={`${s.rank}-${code}-${name}`}
                data-testid={`top-stock-row-${s.rank}`}
              >
                <TableCell className="font-mono font-semibold text-text-secondary">
                  #{s.rank}
                </TableCell>
                <TableCell className="font-mono">{code || '—'}</TableCell>
                <TableCell>{name || '—'}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">
                  {heat.toLocaleString()}
                </TableCell>
                <TableCell className={cn('text-right font-mono tabular-nums', chgColor(chg))}>
                  <Badge variant={chgBadgeVariant(chg)}>
                    {chg === null
                      ? (s.chg ?? '—')
                      : `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-text-secondary max-w-md truncate" title={question}>
                  {question || '—'}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
});