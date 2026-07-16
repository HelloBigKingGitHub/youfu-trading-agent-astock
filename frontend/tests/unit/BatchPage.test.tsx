import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// ── Mock data ───────────────────────────────────────────────────────────────
const { MOCK_BATCH_LIST, MOCK_PROGRESS, MOCK_SUMMARY } = vi.hoisted(() => ({
  MOCK_BATCH_LIST: {
    batches: [
      {
        batch_id: 'batch_test_001',
        batch_status: 'completed' as const,
        total: 3,
        finished_count: 3,
        error_count: 0,
        created_at: 1700000000,
        jobs: [
          { job_id: 'j1', ticker: '600519', trade_date: '2026-07-16', status: 'completed' as const, completed_stages: ['s1', 's2'], signal: 'BUY' },
        ],
      },
    ],
    total: 1,
  },
  MOCK_PROGRESS: {
    batch_id: 'batch_test_001',
    batch_status: 'completed' as const,
    total: 3,
    finished_count: 3,
    error_count: 0,
    running_count: 0,
    pending_count: 0,
    jobs: [
      { job_id: 'j1', ticker: '600519', trade_date: '2026-07-16', status: 'completed' as const, completed_stages: ['s1', 's2'], signal: 'BUY', error: null, elapsed: 12.5 },
    ],
  },
  MOCK_SUMMARY: {
    batch_id: 'batch_test_001',
    batch_status: 'completed' as const,
    rows: [
      { ticker: '600519', trade_date: '2026-07-16', status: 'completed', signal: 'BUY', completed_stages_count: 2, elapsed_seconds: 12.5, error: '' },
    ],
  },
}));

// ── Mock the batch API client ───────────────────────────────────────────────
// The hooks inside React Query depend on the result of createBatch / listBatches
// / getBatchProgress / getBatchSummary. We keep parseTickerList real (it's a
// pure function used by the component for the TickerInput live count).
vi.mock('@/api/batch', async () => {
  const actual = await vi.importActual<typeof import('@/api/batch')>('@/api/batch');
  return {
    ...actual,
    createBatch: vi.fn().mockResolvedValue({
      batch_id: 'batch_test_001',
      total: 3,
      jobs: [],
    }),
    listBatches: vi.fn().mockResolvedValue(MOCK_BATCH_LIST),
    getBatchProgress: vi.fn().mockResolvedValue(MOCK_PROGRESS),
    getBatchSummary: vi.fn().mockResolvedValue(MOCK_SUMMARY),
    cancelBatch: vi.fn().mockResolvedValue({ batch_id: 'batch_test_001', cancelled_count: 0 }),
    retryJob: vi.fn().mockResolvedValue({ job_id: 'j1', status: 'pending' }),
  };
});

// ── Mock React Query hooks so we control state without a real QueryClient ──
// The component uses useQuery for batch-list / batch-progress / batch-summary,
// useMutation for create / cancel / retry, and useQueryClient for cache
// invalidation after a successful submission.  Replacing all three mirrors
// the pattern from HistoryPage / LogsPage / SettingsPage tests so the
// component renders without a real QueryClientProvider.
vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query',
  );
  return {
    ...actual,
    useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
      const k = queryKey[0];
      if (k === 'batch-list') {
        return { data: MOCK_BATCH_LIST, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'batch-progress') {
        return { data: MOCK_PROGRESS, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      if (k === 'batch-summary') {
        return { data: MOCK_SUMMARY, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
      }
      return { data: undefined, isLoading: false, isFetching: false, error: null, refetch: vi.fn() };
    },
    useMutation: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
      reset: vi.fn(),
    }),
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
      getQueryData: vi.fn(),
      cancelQueries: vi.fn(),
    }),
  };
});

import BatchPage from '@/pages/BatchPage';

describe('BatchPage', () => {
  it('renders 3 tabs + default submit panel (ticker input + config form + start CTA)', async () => {
    render(<BatchPage />);

    // outer page wrapper + title
    expect(screen.getByTestId('batch-page')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /批量分析/ })).toBeInTheDocument();

    // 3 tab buttons (mirrors Streamlit batch_panel.py 3-tab layout)
    expect(screen.getByTestId('batch-tab-submit')).toBeInTheDocument();
    expect(screen.getByTestId('batch-tab-progress')).toBeInTheDocument();
    expect(screen.getByTestId('batch-tab-history')).toBeInTheDocument();

    // Default tab is submit → panel + form fields visible
    expect(screen.getByTestId('batch-panel-submit')).toBeInTheDocument();
    expect(screen.getByTestId('ticker-input')).toBeInTheDocument();
    expect(screen.getByTestId('batch-config-form')).toBeInTheDocument();
    expect(screen.getByTestId('batch-submit')).toBeInTheDocument();
    // Tickers textarea prefilled with the 3 default tickers (688017 / 600519 / 000001)
    expect(screen.getByTestId('batch-tickers-textarea')).toHaveValue('688017\n600519\n000001');
  });

  it('switches to history tab and renders the BatchList (with mocked batches)', async () => {
    render(<BatchPage />);

    // Switch to history tab — this should reveal the BatchList backed by the
    // mocked listBatches payload.
    screen.getByTestId('batch-tab-history').click();
    await waitFor(() =>
      expect(screen.getByTestId('batch-panel-history')).toBeVisible(),
    );
    expect(screen.getByTestId('batch-list')).toBeInTheDocument();
    // The mocked batch_id should appear as a selectable row.
    expect(screen.getByTestId('batch-list-row-batch_test_001')).toBeInTheDocument();
  });
});
