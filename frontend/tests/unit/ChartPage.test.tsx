import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const { MOCK_KLINES } = vi.hoisted(() => ({
  MOCK_KLINES: [
    { date: '2026-07-14', open: 10, high: 11, low: 9.5, close: 10.5, volume: 120000 },
    { date: '2026-07-15', open: 10.5, high: 11.4, low: 10.2, close: 11.1, volume: 180000 },
    { date: '2026-07-16', open: 11.1, high: 11.6, low: 10.8, close: 11.3, volume: 160000 },
  ],
}));

vi.mock('@/api/chart', async () => {
  const actual = await vi.importActual<typeof import('@/api/chart')>('@/api/chart');
  return {
    ...actual,
    getKline: vi.fn().mockResolvedValue({
      ticker: '600595',
      range: '6m',
      klines: MOCK_KLINES,
      source: 'cache',
      cached: true,
      count: MOCK_KLINES.length,
    }),
    getQuote: vi.fn().mockResolvedValue({
      ticker: '600595',
      name: '贵州轮胎',
      price: 11.3,
      open: 11.1,
      high: 11.6,
      low: 10.8,
      last_close: 11.0,
      change_amount: 0.3,
      change_pct: 2.73,
      volume: 160000,
      timestamp: 1784160000,
      source: 'tencent_qt_gtimg',
    }),
  };
});

vi.mock('@/components/chart/kline-chart', () => ({
  KlineChart: ({ klines }: { klines: unknown[] }) => (
    <div data-testid="chart-canvas" role="img" aria-label="K线图">
      {klines.length} candles
    </div>
  ),
}));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query',
  );
  return {
    ...actual,
    useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
      const isKline = queryKey[0] === 'chart-kline';
      const ticker = (queryKey[1] as string) ?? '600595';
      if (isKline) {
        // For the empty-state test, the second ticker (000000) resolves to an
        // empty kline list, mirroring what the real backend returns.
        if (ticker === '000000') {
          return {
            data: {
              ticker,
              range: '6m',
              klines: [],
              source: 'empty',
              cached: false,
              count: 0,
              message: '未找到数据',
            },
            isLoading: false,
            isFetching: false,
            error: null,
            refetch: vi.fn(),
          };
        }
        return {
          data: {
            ticker,
            range: '6m',
            klines: MOCK_KLINES,
            source: 'cache',
            cached: true,
            count: MOCK_KLINES.length,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      return {
        data: {
          ticker,
          name: '贵州轮胎',
          price: 11.3,
          open: 11.1,
          high: 11.6,
          low: 10.8,
          last_close: 11.0,
          change_amount: 0.3,
          change_pct: 2.73,
          volume: 160000,
          timestamp: 1784160000,
          source: 'tencent_qt_gtimg',
        },
        isLoading: false,
        isFetching: false,
        error: null,
        refetch: vi.fn(),
      };
    },
  };
});

import ChartPage from '@/pages/ChartPage';

describe('ChartPage', () => {
  it('renders the ticker controls, quote banner, source status, and chart canvas', async () => {
    render(
      <MemoryRouter initialEntries={['/chart?ticker=600595&range=6m']}>
        <ChartPage />
      </MemoryRouter>,
    );

    expect(screen.getByTestId('chart-page')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '📈 走势图' })).toBeInTheDocument();
    expect(screen.getByLabelText('股票代码')).toHaveValue('600595');
    expect(screen.getByTestId('chart-ticker-input')).toBeInTheDocument();
    expect(screen.getByTestId('quote-banner')).toHaveTextContent('贵州轮胎');
    expect(screen.getByTestId('data-source-status')).toHaveTextContent('cache');

    await waitFor(() => expect(screen.getByTestId('chart-canvas')).toBeInTheDocument());
    expect(screen.getByTestId('chart-canvas')).toHaveTextContent('3 candles');
  });

  it('shows an empty state when the API returns no klines', async () => {
    render(
      <MemoryRouter initialEntries={['/chart?ticker=000000&range=6m']}>
        <ChartPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId('chart-empty')).toBeInTheDocument());
    expect(screen.getByTestId('chart-empty')).toHaveTextContent('暂无 K 线数据');
  });
});
