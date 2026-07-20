import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/ui/toast';
import type { HistoryItem } from '@/api/history';

const mocks = vi.hoisted(() => ({
  invalidateQueries: vi.fn(),
  deleteMutate: vi.fn(),
  rerunMutate: vi.fn(),
  listHistoryImpl: vi.fn(),
}));

// Two completed entries — mirrors the production fixture. We don't read
// `selected` until the test clicks a row, so coverage of the list+filter
// path is the priority.
const MOCK_ITEMS: HistoryItem[] = [
  {
    analysis_id: '600595_2026-07-10_aaaaaaaa',
    ticker: '600595',
    trade_date: '2026-07-10',
    signal: 'Buy',
    elapsed: 12.34,
    created_at: '1784000000.0',
    status: 'completed',
    error: null,
    completed_stages: ['news', 'fundamentals', 'bull', 'bear', 'judge'],
  },
  {
    analysis_id: '600490_2026-07-09_bbbbbbbb',
    ticker: '600490',
    trade_date: '2026-07-09',
    signal: 'Sell',
    elapsed: 5.67,
    created_at: '1783900000.0',
    status: 'error',
    error: 'something blew up: Traceback (most recent call last)…',
    completed_stages: ['news'],
  },
];

vi.mock('@/api/history', async () => {
  const actual = await vi.importActual<typeof import('@/api/history')>('@/api/history');
  return {
    ...actual,
    listHistory: (...args: Parameters<typeof actual.listHistory>) => mocks.listHistoryImpl(...args),
    deleteHistory: (aid: string) => {
      mocks.deleteMutate(aid);
      return Promise.resolve({ ok: true, analysis_id: aid });
    },
    rerunHistory: (aid: string) => {
      mocks.rerunMutate(aid);
      return Promise.resolve({
        ok: true,
        start_analysis: { ticker: '600595', trade_date: '2026-07-10' },
        analysis_id: aid,
      });
    },
    getHistory: (aid: string) =>
      Promise.resolve({
        ...MOCK_ITEMS[0],
        stage_reports: {},
        started_at: 1784000001,
        finished_at: 1784000013,
        results_path: '/tmp/dummy.json',
      }),
    getReport: () =>
      Promise.resolve({
        analysis_id: 'x',
        ticker: 'x',
        trade_date: 'x',
        results_path: 'x',
        report: {},
      }),
  };
});

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query'
  );
  return {
    ...actual,
    useQuery: () => ({
      data: { items: MOCK_ITEMS, total: 2, limit: 50, offset: 0 },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    }),
    useMutation: () => ({ isPending: false, mutate: vi.fn(), variables: undefined }),
    useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
  };
});

import { HistoryPage } from '@/pages/HistoryPage';

describe('HistoryPage', () => {
  beforeEach(() => {
    mocks.invalidateQueries.mockClear();
    mocks.deleteMutate.mockClear();
    mocks.rerunMutate.mockClear();
    mocks.listHistoryImpl.mockClear();
  });

  function renderPage() {
    return render(
      <ToastProvider>
        <HistoryPage />
      </ToastProvider>
    );
  }

  it('renders the filter bar, table, and pagination summary', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId('history-page')).toBeInTheDocument());
    expect(screen.getByTestId('history-filter-bar')).toBeInTheDocument();
    expect(screen.getByTestId('history-table-body')).toBeInTheDocument();
    expect(screen.getByTestId('history-pagination-summary')).toHaveTextContent('1-2 / 2');
    // 2 rows visible in the table for our 2 mock items
    const rows = screen.getAllByTestId(/^history-row-/);
    expect(rows).toHaveLength(2);
    // One of the rows has signal badge = Buy → label "🟢 买入"
    expect(screen.getByText('🟢 买入')).toBeInTheDocument();
    // Error row shows the error snippet (capped at 30 chars)
    expect(screen.getByText(/🔴 something blew up/)).toBeInTheDocument();
  });

  it('clicking the filter 搜索 button calls listHistory with the new signal filter', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId('history-page')).toBeInTheDocument());

    fireEvent.change(screen.getByTestId('filter-signal'), { target: { value: 'Buy' } });
    fireEvent.click(screen.getByTestId('filter-search'));

    await waitFor(() => {
      const calledWithBuy = mocks.listHistoryImpl.mock.calls.some(
        (call) => (call[0] as { signal?: string }).signal === 'Buy'
      );
      expect(calledWithBuy).toBe(true);
    });
  });

  it('clicking a row opens the detail dialog', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId('history-page')).toBeInTheDocument());

    const firstRow = screen.getAllByTestId(/^history-row-/)[0];
    fireEvent.click(firstRow);

    await waitFor(() =>
      expect(screen.getByTestId('history-detail-dialog')).toBeInTheDocument()
    );
    expect(screen.getByTestId('history-detail-close')).toBeInTheDocument();
  });

  // P2.30 — the shared purge button must be visible in the page header so
  // the user can wipe all terminal history in one action.
  it('renders the shared 清空所有历史 trigger button in the page header', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId('history-page')).toBeInTheDocument());

    const trigger = screen.getByTestId('history-purge-trigger');
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveTextContent(/清空所有历史/);
  });
});
