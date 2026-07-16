import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { MOCK_STRATEGIES, MOCK_CONCEPTS, MOCK_STOCKS, MOCK_DIGEST } = vi.hoisted(() => ({
  MOCK_STRATEGIES: [
    { rank: '1', heatValue: 18127, chg: '+4.78%', question: '量比大于1.2;总市值 60-180 亿', code: '600000', name: '浦发银行' },
    { rank: '2', heatValue: 17131, chg: '+1.87%', question: '当日大单净流入>10M', code: '600519', name: '贵州茅台' },
  ],
  MOCK_CONCEPTS: [
    { name: '国企改革', stock_count: 8, avg_ratio: 1.23, codes: ['600000', '600519'] },
    { name: '创投', stock_count: 5, avg_ratio: -0.5, codes: ['600635'] },
  ],
  MOCK_STOCKS: [
    { code: '600519', name: '贵州茅台', ratio: '+10.01%', zhangfu: '+10.01', huanshou: '1.2%', reason: '白酒+国企改革+高分红' },
    { code: '600635', name: '大众公用', ratio: '-2.34%', zhangfu: '-2.34', huanshou: '0.8%', reason: '创投+天然气' },
  ],
  MOCK_DIGEST: {
    date: 'today',
    top_n: 20,
    markdown: '# 板块轮动日报 | 2026-07-16\n\n## 一、机构视角\n\n> np-ipick 选股热度 Top 5\n\n## 二、涨停归因\n\n> 同花顺 涨停 5 只\n',
    sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
    hot_strategies_count: 5,
    hot_stocks_count: 3,
    concept_blocks_count: 12,
    digest_hash: 'abc123def456',
  },
}));

vi.mock('@/api/sector', async () => {
  const actual = await vi.importActual<typeof import('@/api/sector')>('@/api/sector');
  return {
    ...actual,
    getHeatmap: vi.fn().mockResolvedValue({
      date: 'today',
      top_n: 20,
      concept_blocks: {
        '国企改革': [{ code: '600519', name: '贵州茅台', ratio: '+10.01%' }],
        '创投': [{ code: '600635', name: '大众公用', ratio: '-2.34%' }],
      },
      sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
      count: 2,
    }),
    getTopStocks: vi.fn().mockResolvedValue({
      date: 'today',
      limit: 20,
      strategies: MOCK_STRATEGIES,
      sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
      count: MOCK_STRATEGIES.length,
    }),
    getConcepts: vi.fn().mockResolvedValue({
      date: 'today',
      top_n: 20,
      concepts: MOCK_CONCEPTS,
      sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
      count: MOCK_CONCEPTS.length,
    }),
    getLimitUp: vi.fn().mockResolvedValue({
      date: 'today',
      top_n: 20,
      stocks: MOCK_STOCKS,
      sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
      count: MOCK_STOCKS.length,
    }),
    getDigest: vi.fn().mockResolvedValue(MOCK_DIGEST),
  };
});

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query',
  );
  return {
    ...actual,
    useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
      const k = queryKey[0];
      if (k === 'sector-heatmap') {
        return {
          data: {
            date: 'today',
            top_n: 20,
            concept_blocks: {
              '国企改革': [{ code: '600519', name: '贵州茅台', ratio: '+10.01%' }],
              '创投': [{ code: '600635', name: '大众公用', ratio: '-2.34%' }],
            },
            sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
            count: 2,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'sector-top-stocks') {
        return {
          data: {
            date: 'today',
            limit: 20,
            strategies: MOCK_STRATEGIES,
            sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
            count: MOCK_STRATEGIES.length,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'sector-concepts') {
        return {
          data: {
            date: 'today',
            top_n: 20,
            concepts: MOCK_CONCEPTS,
            sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
            count: MOCK_CONCEPTS.length,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'sector-limit-up') {
        return {
          data: {
            date: 'today',
            top_n: 20,
            stocks: MOCK_STOCKS,
            sources_ok: { np_ipick: true, ths_limitup: true, baidu_pae: false },
            count: MOCK_STOCKS.length,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'sector-digest') {
        return {
          data: MOCK_DIGEST,
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      return {
        data: undefined,
        isLoading: false,
        isFetching: false,
        error: null,
        refetch: vi.fn(),
      };
    },
  };
});

import SectorPage from '@/pages/SectorPage';

describe('SectorPage', () => {
  it('renders the heatmap tab by default with block grid', async () => {
    render(<SectorPage />);

    expect(screen.getByTestId('sector-page')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /板块轮动/ })).toBeInTheDocument();
    // 5 tab buttons
    expect(screen.getByTestId('sector-tab-heatmap')).toBeInTheDocument();
    expect(screen.getByTestId('sector-tab-top-stocks')).toBeInTheDocument();
    expect(screen.getByTestId('sector-tab-concepts')).toBeInTheDocument();
    expect(screen.getByTestId('sector-tab-limit-up')).toBeInTheDocument();
    expect(screen.getByTestId('sector-tab-digest')).toBeInTheDocument();
    // Default heatmap panel
    expect(screen.getByTestId('sector-panel-heatmap')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('heatmap-grid')).toBeInTheDocument());
    expect(screen.getByTestId('heatmap-block-国企改革')).toBeInTheDocument();
    expect(screen.getByTestId('heatmap-block-创投')).toBeInTheDocument();
  });

  it('switches to the top_stocks tab and renders the strategies table', async () => {
    render(<SectorPage />);
    screen.getByTestId('sector-tab-top-stocks').click();
    await waitFor(() => expect(screen.getByTestId('top-stocks-table')).toBeInTheDocument());
    expect(screen.getByTestId('top-stock-row-1')).toBeInTheDocument();
    expect(screen.getByTestId('top-stock-row-2')).toBeInTheDocument();
  });

  it('switches to the concepts tab and renders concept cards', async () => {
    render(<SectorPage />);
    screen.getByTestId('sector-tab-concepts').click();
    await waitFor(() => expect(screen.getByTestId('concepts-list')).toBeInTheDocument());
    expect(screen.getByTestId('concept-card-国企改革')).toBeInTheDocument();
    expect(screen.getByTestId('concept-card-创投')).toBeInTheDocument();
  });

  it('switches to the limit_up tab and renders the limit-up rows', async () => {
    render(<SectorPage />);
    screen.getByTestId('sector-tab-limit-up').click();
    await waitFor(() => expect(screen.getByTestId('limit-up-table')).toBeInTheDocument());
    expect(screen.getByTestId('limit-up-row-600519')).toBeInTheDocument();
    expect(screen.getByTestId('limit-up-row-600635')).toBeInTheDocument();
  });

  it('switches to the digest tab and renders the markdown viewer with sources', async () => {
    render(<SectorPage />);
    screen.getByTestId('sector-tab-digest').click();
    await waitFor(() => expect(screen.getByTestId('digest-viewer')).toBeInTheDocument());
    expect(screen.getByTestId('digest-markdown')).toHaveTextContent('板块轮动日报');
    expect(screen.getByTestId('digest-sources')).toBeInTheDocument();
    expect(screen.getByTestId('digest-hash')).toHaveTextContent('abc123de');
  });
});