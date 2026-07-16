import * as React from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge, signalLabel, signalVariant } from '@/components/ui/badge';
import type { TickerSummary } from '@/api/logs';

// TickerList — left column of the GitHub-PR-style LogsPage. Mirrors
// `web/components/logs_panel.py::_render_ticker_list`:
//   - Sort by latest activity desc (server side, but we also defensively
//     re-sort by latest_trade_date desc + ticker asc for stability).
//   - Each ticker shows a card with the latest signal + run count.
//   - Active ticker is highlighted with a left blue bar.
//
// On click → onSelect(ticker) is fired upward; the parent owns the
// session-equivalent "selected ticker" so the two panels stay in sync.

interface TickerListProps {
  tickers: TickerSummary[];
  selectedTicker: string | null;
  onSelect: (ticker: string) => void;
  isLoading?: boolean;
  error?: string | null;
}

function compareTickers(a: TickerSummary, b: TickerSummary): number {
  // Sort by latest_trade_date desc, then ticker asc (deterministic).
  const ad = a.latest_trade_date ?? '';
  const bd = b.latest_trade_date ?? '';
  if (ad !== bd) return bd.localeCompare(ad);
  return a.ticker.localeCompare(b.ticker);
}

export const TickerList = React.memo(function TickerList({
  tickers,
  selectedTicker,
  onSelect,
  isLoading,
  error,
}: TickerListProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="ticker-list-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载 tickers…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="ticker-list-error"
      >
        加载 ticker 列表失败: {error}
      </div>
    );
  }

  if (!tickers.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
        data-testid="ticker-list-empty"
      >
        暂无日志. 完成一次分析后, 日志会自动出现.
      </div>
    );
  }

  const sorted = [...tickers].sort(compareTickers);

  return (
    <div
      className="flex flex-col gap-2"
      data-testid="ticker-list"
      aria-label="ticker 列表"
    >
      <div className="text-[10px] uppercase tracking-wider text-text-tertiary px-1">
        Tickers ({sorted.length})
      </div>
      <div className="flex flex-col gap-2 max-h-[70vh] overflow-y-auto pr-1">
        {sorted.map((t) => {
          const isActive = selectedTicker === t.ticker;
          return (
            <button
              key={t.ticker}
              type="button"
              onClick={() => onSelect(t.ticker)}
              data-testid={`ticker-card-${t.ticker}`}
              aria-pressed={isActive}
              className={cn(
                'group flex flex-col gap-1.5 rounded-md border p-3 text-left transition-colors',
                isActive
                  ? 'border-bb-accent/60 bg-bb-accent-glow text-text-primary shadow-[inset_3px_0_0_0_var(--bb-accent-bright)]'
                  : 'border-border-1 bg-bg-elevated hover:bg-bg-surface text-text-primary'
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-semibold text-sm truncate">
                  {t.ticker}
                </span>
                <Badge
                  variant={signalVariant(t.latest_signal)}
                  className="shrink-0"
                  data-testid={`ticker-signal-${t.ticker}`}
                >
                  {signalLabel(t.latest_signal)}
                </Badge>
              </div>
              <div className="flex items-center justify-between text-[11px] text-text-secondary">
                <span className="font-mono">{t.task_count} runs</span>
                <span className="font-mono">
                  {t.latest_trade_date || '—'}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
});