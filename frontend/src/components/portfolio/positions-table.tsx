/**
 * PositionsTable — overview tab. Renders ticker / name / quantity / cost / current / PnL.
 *
 * Mirrors web/components/portfolio_overview.py::render_overview_table.  Both UIs
 * render the same singleton data (backend.core.portfolio_store.list_positions),
 * so the columns are 1:1.  Color follows A-share convention: red = up (PnL > 0),
 * green = down (PnL < 0).
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { Position } from '@/api/portfolio';

interface PositionsTableProps {
  positions: Position[];
  isLoading?: boolean;
  error?: string | null;
}

function fmtPct(n: number): string {
  if (!Number.isFinite(n)) return '—';
  return `${(n * 100).toFixed(2)}%`;
}

function fmtMoney(n: number): string {
  if (!Number.isFinite(n)) return '—';
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pnlColor(abs: number): string {
  if (abs > 0) return 'text-red-400';   // A-share: red = up
  if (abs < 0) return 'text-green-400'; // green = down
  return 'text-text-secondary';
}

export function PositionsTable({ positions, isLoading, error }: PositionsTableProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="positions-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载持仓…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="positions-error"
      >
        加载持仓失败: {error}
      </div>
    );
  }
  if (!positions.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="positions-empty"
      >
        暂无持仓。先到「导入导出」或「流水」录入。
      </div>
    );
  }
  return (
    <div data-testid="positions-table-wrap">
      <Table data-testid="positions-table">
        <TableHeader>
          <TableRow>
            <TableHead>代码</TableHead>
            <TableHead>名称</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead className="text-right">成本价</TableHead>
            <TableHead className="text-right">现价</TableHead>
            <TableHead className="text-right">盈亏额</TableHead>
            <TableHead className="text-right">盈亏 %</TableHead>
            <TableHead>首买日</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p) => {
            const marketValue = p.current_price * p.quantity;
            const costTotal = p.cost_basis * p.quantity;
            const pnlAbs = marketValue - costTotal;
            const pnlPct = costTotal > 0 ? pnlAbs / costTotal : 0;
            return (
              <TableRow key={p.position_id} data-testid={`positions-row-${p.ticker}`}>
                <TableCell className="font-mono">{p.ticker}</TableCell>
                <TableCell>{p.name || '—'}</TableCell>
                <TableCell className="text-right font-mono">{p.quantity.toLocaleString('zh-CN')}</TableCell>
                <TableCell className="text-right font-mono">{p.cost_basis.toFixed(2)}</TableCell>
                <TableCell className="text-right font-mono">{p.current_price.toFixed(2)}</TableCell>
                <TableCell className={`text-right font-mono ${pnlColor(pnlAbs)}`}>
                  {pnlAbs >= 0 ? '+' : ''}{fmtMoney(pnlAbs).replace('¥', '¥')}
                </TableCell>
                <TableCell className={`text-right font-mono ${pnlColor(pnlAbs)}`}>
                  {pnlAbs >= 0 ? '+' : ''}{fmtPct(pnlPct)}
                </TableCell>
                <TableCell className="font-mono text-text-secondary">{p.first_buy_date || '—'}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export default PositionsTable;