/**
 * LimitUpTable — 同花顺 limit-up list with reason tags.
 *
 * Mirrors `web/components/sector_panel.py::_render_hot_stocks_table`:
 *   code | name | ratio | reason
 *
 * The `reason` is a `+`-delimited tag list (e.g. "中成药集采+中药全产业链")
 * — we render each segment as a small tag for visual scannability. Up / down
 * coloring follows A-share convention.
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
import type { LimitUpStock } from '@/api/sector';

interface LimitUpTableProps {
  stocks: LimitUpStock[];
  isLoading?: boolean;
  error?: string | null;
}

function parseRatio(stock: LimitUpStock): number | null {
  // Backend provides both `ratio` (string) and `zhangfu`; prefer `zhangfu` as
  // it's already a clean percentage.
  const raw = stock.zhangfu ?? stock.ratio;
  if (raw === null || raw === undefined) return null;
  if (typeof raw === 'number') return raw;
  const m = String(raw).match(/([+-]?[\d.]+)/);
  if (!m) return null;
  const v = parseFloat(m[1]);
  return Number.isFinite(v) ? v : null;
}

function ratioColor(r: number | null): string {
  if (r === null) return 'text-text-secondary';
  if (r > 0) return 'text-bb-up font-semibold';
  if (r < 0) return 'text-bb-down font-semibold';
  return 'text-text-secondary';
}

function splitReasonTags(reason: string): string[] {
  if (!reason) return [];
  return reason
    .split('+')
    .map((s) => s.trim())
    .filter(Boolean);
}

export const LimitUpTable = React.memo(function LimitUpTable({
  stocks,
  isLoading,
  error,
}: LimitUpTableProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="limit-up-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载涨停归因…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="limit-up-error"
      >
        加载涨停归因失败: {error}
      </div>
    );
  }

  if (!stocks.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
        data-testid="limit-up-empty"
      >
        暂无涨停归因数据
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border-1 bg-bg-surface" data-testid="limit-up-table">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-24">股票代码</TableHead>
            <TableHead>中文名</TableHead>
            <TableHead className="text-right">涨跌幅</TableHead>
            <TableHead className="w-24">换手率</TableHead>
            <TableHead>归因标签</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {stocks.map((s) => {
            const ratio = parseRatio(s);
            const tags = splitReasonTags(s.reason);
            return (
              <TableRow
                key={`${s.code}-${s.name}`}
                data-testid={`limit-up-row-${s.code}`}
              >
                <TableCell className="font-mono">{s.code || '—'}</TableCell>
                <TableCell className="font-medium">{s.name || '—'}</TableCell>
                <TableCell className={cn('text-right font-mono tabular-nums', ratioColor(ratio))}>
                  {ratio === null ? (s.ratio ?? '—') : (
                    <Badge variant={ratio > 0 ? 'destructive' : ratio < 0 ? 'success' : 'outline'}>
                      {`${ratio >= 0 ? '+' : ''}${ratio.toFixed(2)}%`}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs text-text-secondary">
                  {s.huanshou ?? '—'}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1 max-w-md">
                    {tags.length === 0 && (
                      <span className="text-text-tertiary text-xs">—</span>
                    )}
                    {tags.map((tag, idx) => (
                      <span
                        key={`${s.code}-${idx}`}
                        className="text-[10px] font-mono px-1.5 py-0.5 rounded
                                   bg-bg-elevated border border-border-1
                                   text-text-secondary"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
});