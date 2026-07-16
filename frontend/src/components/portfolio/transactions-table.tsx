/**
 * TransactionsTable — 流水 tab. Renders date / action / ticker / quantity / price / fees.
 *
 * Mirrors web/components/portfolio_transactions.py.  Both UIs read the same
 * ``PortfolioStore.list_transactions()`` singleton (newest first) so the rows
 * are 1:1 between React and Streamlit.
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { Transaction } from '@/api/portfolio';

interface TransactionsTableProps {
  transactions: Transaction[];
  isLoading?: boolean;
  error?: string | null;
}

function fmtMoney(n: number): string {
  if (!Number.isFinite(n)) return '—';
  return `¥${n.toFixed(2)}`;
}

function actionBadge(action: string): { label: string; cls: string } {
  const a = action.toLowerCase();
  if (a === 'buy') {
    return { label: '买入', cls: 'bg-red-500/20 text-red-300 border-red-500/40' };
  }
  if (a === 'sell') {
    return { label: '卖出', cls: 'bg-green-500/20 text-green-300 border-green-500/40' };
  }
  return { label: action || '—', cls: 'bg-bg-elevated text-text-secondary border-border-1' };
}

export function TransactionsTable({ transactions, isLoading, error }: TransactionsTableProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="transactions-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载流水…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="transactions-error"
      >
        加载流水失败: {error}
      </div>
    );
  }
  if (!transactions.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="transactions-empty"
      >
        暂无交易流水。
      </div>
    );
  }
  return (
    <div data-testid="transactions-table-wrap">
      <Table data-testid="transactions-table">
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>代码</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead className="text-right">价格</TableHead>
            <TableHead className="text-right">费用</TableHead>
            <TableHead>备注</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {transactions.map((t) => {
            const badge = actionBadge(t.action);
            return (
              <TableRow key={t.tx_id} data-testid={`transactions-row-${t.tx_id}`}>
                <TableCell className="font-mono text-text-secondary">{t.date || '—'}</TableCell>
                <TableCell>
                  <span className={`inline-block rounded border px-1.5 py-0.5 text-xs ${badge.cls}`}>
                    {badge.label}
                  </span>
                </TableCell>
                <TableCell className="font-mono">{t.ticker}</TableCell>
                <TableCell className="text-right font-mono">{t.quantity.toLocaleString('zh-CN')}</TableCell>
                <TableCell className="text-right font-mono">{fmtMoney(t.price)}</TableCell>
                <TableCell className="text-right font-mono text-text-secondary">{fmtMoney(t.fees)}</TableCell>
                <TableCell className="text-text-secondary">{t.notes || '—'}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export default TransactionsTable;