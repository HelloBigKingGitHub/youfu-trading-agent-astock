/**
 * Chart API client — mirrors backend/api/chart.py 1:1.
 *
 * Endpoints:
 *   GET /api/chart/kline?ticker=&range=      historical OHLCV + MA-ready
 *   GET /api/chart/quote?ticker=             real-time quote banner
 *   GET /api/chart/quote/sse?ticker=&range=  SSE stream (1 per minute)
 *
 * Both UIs (Streamlit chart_panel.py + this React ChartPage) ultimately
 * read from the SAME data source: tradingagents.dataflows.a_stock.get_stock_data
 * (3-tier fallback: mootdx → sina → push2his). The 24h CSV cache under
 * ~/.tradingagents/cache/kline/{ticker}_{range}.csv is shared.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

export type ChartRange = '1d' | '1w' | '1m' | '3m' | '6m' | '1y' | 'all';

export const CHART_RANGES: ChartRange[] = ['1d', '1w', '1m', '3m', '6m', '1y', 'all'];
export const DEFAULT_RANGE: ChartRange = '6m';
export const DEFAULT_TICKER = '600595';

export type DataSource = 'mootdx' | 'sina' | 'push2his' | 'cache' | 'empty';

export interface Kline {
  date: string;     // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface KlineResponse {
  ticker: string;
  range: ChartRange;
  klines: Kline[];
  source: DataSource;
  cached: boolean;
  count: number;
  message?: string;
}

export interface QuoteResponse {
  ticker: string;
  name: string;
  price: number;
  open: number;
  high: number;
  low: number;
  last_close: number;
  change_amount: number;
  change_pct: number;
  volume: number;
  timestamp: number;
  source: 'tencent_qt_gtimg' | string;
}

// ── historical kline ───────────────────────────────────────────────────────
export async function getKline(
  ticker: string,
  range: ChartRange = DEFAULT_RANGE,
): Promise<KlineResponse> {
  const qs = new URLSearchParams({ ticker, range });
  const res = await fetch(_url(`/api/chart/kline?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/chart/kline ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as KlineResponse;
}

// ── real-time quote ────────────────────────────────────────────────────────
export async function getQuote(ticker: string): Promise<QuoteResponse> {
  const res = await fetch(
    _url(`/api/chart/quote?ticker=${encodeURIComponent(ticker)}`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`GET /api/chart/quote ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as QuoteResponse;
}