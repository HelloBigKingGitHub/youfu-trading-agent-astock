import * as React from 'react';
import { Loader2, TrendingDown, TrendingUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { QuoteResponse } from '@/api/chart';

// QuoteBanner — live ticker quote row.
//
// Mirrors web/components/chart_panel.py::_render_quote_banner:
//   - ticker · 中文名 · 当前价 · 涨跌额 · 涨跌幅 · 成交量 (best-effort)
//   - 涨绿 / 跌红 (A-share convention via tokens.css --bb-down / --bb-up)
//   - 60s refresh (the SSE backend emits 1 update/minute per spec P2.4 § 4)
//
// The component is presentational: it accepts a `quote` (or null) and an
// `isFetching` flag. Parent (ChartPage) drives the polling cadence.

export interface QuoteBannerProps {
  quote: QuoteResponse | null;
  ticker: string;
  isFetching?: boolean;
  error?: string | null;
}

function _formatPrice(value: number): string {
  return value.toFixed(2);
}

function _formatChange(value: number, isUp: boolean): string {
  const sign = isUp ? '+' : '';
  return `${sign}${value.toFixed(3)}`;
}

function _formatPct(value: number, isUp: boolean): string {
  const sign = isUp ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function _formatTime(ts: number | undefined): string {
  if (!ts) return '--:--:--';
  try {
    return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false });
  } catch {
    return '--:--:--';
  }
}

export const QuoteBanner = React.memo(function QuoteBanner({
  quote,
  ticker,
  isFetching,
  error,
}: QuoteBannerProps) {
  if (error) {
    return (
      <div
        data-testid="quote-banner-error"
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-sm text-bb-up"
        role="alert"
      >
        实时报价拉取失败: {error}
      </div>
    );
  }

  if (!quote) {
    return (
      <div
        data-testid="quote-banner-loading"
        className="flex items-center gap-2 rounded-md border border-border-1 bg-bg-elevated p-3 text-sm text-text-secondary"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        正在拉取 {ticker} 的实时报价…
      </div>
    );
  }

  const isUp = (quote.change_pct ?? 0) >= 0;
  const accentColor = isUp ? 'text-bb-down' : 'text-bb-up';
  const Arrow = isUp ? TrendingUp : TrendingDown;
  const arrow = isUp ? '▲' : '▼';

  return (
    <div
      data-testid="quote-banner"
      className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-md border border-border-1 bg-bg-elevated p-3 font-mono text-sm"
      aria-label="实时报价"
    >
      <div className="flex items-baseline gap-2">
        <span
          data-testid="quote-banner-ticker"
          className="text-base font-semibold text-text-primary"
        >
          {quote.ticker}
        </span>
        <span
          data-testid="quote-banner-name"
          className="text-xs text-text-secondary"
        >
          {quote.name || '—'}
        </span>
      </div>

      <div className="flex items-baseline gap-1.5">
        <span className="text-xs text-text-tertiary">现价</span>
        <span
          data-testid="quote-banner-price"
          className={cn('text-xl font-bold tabular-nums', accentColor)}
        >
          {_formatPrice(quote.price)}
        </span>
      </div>

      <div className={cn('flex items-center gap-1', accentColor)}>
        <Arrow className="h-4 w-4" aria-hidden />
        <span data-testid="quote-banner-pct" className="font-semibold tabular-nums">
          {_formatPct(quote.change_pct ?? 0, isUp)}
        </span>
      </div>

      <div className={cn('text-xs tabular-nums', accentColor)}>
        <span className="text-text-tertiary">涨跌</span>{' '}
        <span data-testid="quote-banner-change">{_formatChange(quote.change_amount ?? 0, isUp)}</span>
      </div>

      <div className="text-xs tabular-nums text-text-secondary">
        <span className="text-text-tertiary">开盘</span>{' '}
        <span data-testid="quote-banner-open">{_formatPrice(quote.open ?? 0)}</span>
      </div>

      <div className="text-xs tabular-nums text-text-secondary">
        <span className="text-text-tertiary">昨收</span>{' '}
        <span data-testid="quote-banner-last-close">
          {_formatPrice(quote.last_close ?? 0)}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2 text-xs text-text-tertiary">
        <span data-testid="quote-banner-source">{quote.source || 'tencent_qt_gtimg'}</span>
        <span aria-hidden>{arrow}</span>
        <span data-testid="quote-banner-time">{_formatTime(quote.timestamp)}</span>
        {isFetching && <Loader2 className="h-3 w-3 animate-spin" />}
      </div>
    </div>
  );
});