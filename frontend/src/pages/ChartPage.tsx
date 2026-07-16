import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  DEFAULT_RANGE,
  DEFAULT_TICKER,
  getKline,
  getQuote,
  type ChartRange,
} from '@/api/chart';
import { DataSourceStatus } from '@/components/chart/data-source-status';
import { KlineChart } from '@/components/chart/kline-chart';
import { QuoteBanner } from '@/components/chart/quote-banner';
import { TickerInput } from '@/components/chart/ticker-input';

function readRange(value: string | null): ChartRange {
  return value === '1d' || value === '1w' || value === '1m' || value === '3m'
    || value === '6m' || value === '1y' || value === 'all' ? value : DEFAULT_RANGE;
}

/** React counterpart of web/components/chart_panel.py::render_chart_panel. */
export function ChartPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const ticker = searchParams.get('ticker') || DEFAULT_TICKER;
  const range = readRange(searchParams.get('range'));
  const validTicker = /^\d{6}$/.test(ticker);

  const klineQuery = useQuery({
    queryKey: ['chart-kline', ticker, range],
    queryFn: () => getKline(ticker, range),
    enabled: validTicker,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const quoteQuery = useQuery({
    queryKey: ['chart-quote', ticker],
    queryFn: () => getQuote(ticker),
    enabled: validTicker,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
  });

  const handleChange = React.useCallback((nextTicker: string, nextRange: ChartRange) => {
    setSearchParams({ ticker: nextTicker, range: nextRange }, { replace: true });
  }, [setSearchParams]);

  const klines = klineQuery.data?.klines ?? [];
  const klineError = klineQuery.error instanceof Error ? klineQuery.error.message : null;
  const quoteError = quoteQuery.error instanceof Error ? quoteQuery.error.message : null;
  const tickerError = validTicker ? klineError : '股票代码必须是 6 位数字';
  const hasData = klines.length > 0;

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6" data-testid="chart-page">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <h1 className="text-inherit font-inherit">📈 走势图</h1>
          </CardTitle>
          <CardDescription>
            A 股 K 线图 + MA5/10/20 + 成交量副图 · 实时报价 (每 60s 刷新) ·
            数据源 mootdx → sina → push2his 3 层 fallback (24h CSV cache)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <TickerInput
            ticker={ticker}
            range={range}
            error={tickerError}
            onChange={handleChange}
          />

          <QuoteBanner
            quote={quoteQuery.data ?? null}
            ticker={ticker}
            isFetching={quoteQuery.isFetching}
            error={quoteError}
          />

          <DataSourceStatus
            source={klineQuery.data?.source ?? 'empty'}
            cached={klineQuery.data?.cached ?? false}
            cacheTimestamp={klineQuery.dataUpdatedAt ? new Date(klineQuery.dataUpdatedAt).toISOString() : null}
          />

          {klineQuery.isLoading && (
            <div className="rounded-lg border border-border-1 bg-bg-elevated p-12 text-center text-text-secondary" data-testid="chart-loading">
              正在加载 {ticker} 的 {range} K 线数据…
            </div>
          )}

          {klineError && !klineQuery.isLoading && (
            <Alert variant="destructive" data-testid="chart-error">
              <AlertTitle>加载走势图失败</AlertTitle>
              <AlertDescription className="flex items-center gap-3">
                <span>{klineError}</span>
                <Button type="button" variant="outline" size="sm" onClick={() => void klineQuery.refetch()}>
                  重试
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {!klineQuery.isLoading && !klineError && !hasData && (
            <div className="rounded-lg border border-dashed border-border-2 bg-bg-elevated p-10 text-center text-sm text-text-tertiary" data-testid="chart-empty">
              <p className="text-base text-text-primary">暂无 K 线数据</p>
              <p className="mt-2">{validTicker
                ? (klineQuery.data?.message || `${ticker} 在 ${range} 范围内无 K 线数据。`)
                : '请输入 6 位数字的 A 股代码。'}
              </p>
            </div>
          )}

          {hasData && (
            <KlineChart klines={klines} range={range} />
          )}

          <p className="text-xs text-text-tertiary">
            蜡烛颜色遵循 A 股惯例（红涨绿跌），MA5/10/20 + 成交量副图。
            {quoteError && ` 实时报价暂不可用：${quoteError}`}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default ChartPage;
