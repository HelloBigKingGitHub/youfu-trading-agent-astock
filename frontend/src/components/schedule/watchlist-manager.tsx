/**
 * WatchlistManager — view watchlist entries by tag (read-only mirror).
 *
 * The Streamlit watchlist component writes through backend.core.watchlist;
 * the React mirror here is read-only because the schedule-panel consumer
 * only needs to *select* from the watchlist. Editing watchlist itself is
 * out of scope for Phase 2.8 — that lives in a future page.
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { WatchlistEntry } from '@/api/schedule';

interface WatchlistManagerProps {
  entries: WatchlistEntry[];
  validTags: string[];
  isLoading?: boolean;
  error?: string | null;
}

export function WatchlistManager({ entries, validTags, isLoading, error }: WatchlistManagerProps) {
  const [tagFilter, setTagFilter] = React.useState<string>('');
  const filtered = React.useMemo(() => {
    if (!tagFilter) return entries;
    return entries.filter((e) => e.tag === tagFilter);
  }, [entries, tagFilter]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="watchlist-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载自选股…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="watchlist-error"
      >
        加载自选股失败: {error}
      </div>
    );
  }

  return (
    <div data-testid="watchlist-manager" className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-sm text-text-secondary">tag 过滤:</span>
        <select
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          data-testid="watchlist-tag-filter"
          className="rounded-md border border-border-1 bg-bg-elevated px-2 py-1 text-sm"
        >
          <option value="">(全部)</option>
          {validTags.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <span className="text-xs text-text-tertiary">
          共 {entries.length} 条 · 过滤后 {filtered.length} 条
        </span>
      </div>
      {filtered.length === 0 ? (
        <div
          className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
          data-testid="watchlist-empty"
        >
          {entries.length === 0 ? '暂无自选股 (Streamlit 端录入).' : '当前 tag 下无 ticker.'}
        </div>
      ) : (
        <Table data-testid="watchlist-table">
          <TableHeader>
            <TableRow>
              <TableHead>ticker</TableHead>
              <TableHead>tag</TableHead>
              <TableHead>备注</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((e) => (
              <TableRow key={e.entry_id} data-testid={`watchlist-row-${e.entry_id}`}>
                <TableCell className="font-mono">{e.ticker}</TableCell>
                <TableCell className="text-xs">{e.tag}</TableCell>
                <TableCell className="text-xs text-text-secondary">{e.note || '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}