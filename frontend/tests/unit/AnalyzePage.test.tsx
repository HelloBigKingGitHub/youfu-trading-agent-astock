import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { MOCK_RECENT, MOCK_PROGRESS, MOCK_REPORT } = vi.hoisted(() => ({
  MOCK_RECENT: [
    {
      analysis_id: 'a-001',
      ticker: '600595',
      trade_date: '2026-07-16',
      signal: null,
      elapsed: 12.86,
      created_at: '1784193771.06289',
      status: 'error',
      error: 'cannot schedule new futures after interpreter shutdown',
      completed_stages: [],
    },
    {
      analysis_id: 'a-002',
      ticker: '000858',
      trade_date: '2026-07-15',
      signal: 'BUY',
      elapsed: 87.42,
      created_at: '1784107371.06289',
      status: 'ok',
      error: null,
      completed_stages: ['market', 'social', 'news', 'fundamentals', 'policy', 'hot_money', 'lockup'],
    },
  ],
  MOCK_PROGRESS: {
    status: 'running',
    ticker: '600595',
    trade_date: '2026-07-16',
    current_stage: 'fundamentals',
    completed_stages: ['market', 'social', 'news'],
    stage_reports: {
      market_report: '# 技术分析\nMock market body',
      sentiment_report: '# 情绪分析\nMock sentiment body',
    },
    stats: { llm_calls: 12, tool_calls: 7, tokens_in: 4321, tokens_out: 2103 },
    elapsed: 27.4,
    signal: null,
    error: null,
  },
  MOCK_REPORT: {
    analysis_id: 'a-002',
    ticker: '000858',
    trade_date: '2026-07-15',
    results_path: '/home/youfu/.tradingagents/logs/000858/2026-07-15_run01/full_states_log_2026-07-15.json',
    report: {
      market_report: '# 技术分析\nMock body 2',
      sentiment_report: '# 情绪分析\nMock body 2',
      final_signal: 'BUY',
    },
  },
}));

vi.mock('@/api/analyze', async () => {
  const actual = await vi.importActual<typeof import('@/api/analyze')>('@/api/analyze');
  return {
    ...actual,
    getRecentAnalyzes: vi.fn().mockResolvedValue(MOCK_RECENT),
    getAnalysis: vi.fn().mockImplementation((id: string) => {
      if (id === 'a-002') {
        return Promise.resolve({
          ...MOCK_PROGRESS,
          status: 'ok',
          current_stage: null,
          completed_stages: ['market', 'social', 'news', 'fundamentals', 'policy', 'hot_money', 'lockup'],
          elapsed: 87.42,
          signal: 'BUY',
        });
      }
      return Promise.resolve(MOCK_PROGRESS);
    }),
    getAnalysisReport: vi.fn().mockResolvedValue(MOCK_REPORT),
    startAnalysis: vi.fn().mockResolvedValue({
      analysis_id: 'a-new',
      status: 'started',
      ticker: '600519',
      trade_date: '2026-07-16',
    }),
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
      if (k === 'analyze-recent') {
        return {
          data: MOCK_RECENT,
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'analyze-progress') {
        return {
          data: MOCK_PROGRESS,
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'analyze-report') {
        return {
          data: MOCK_REPORT,
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
    useMutation: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(async () => undefined),
      data: undefined,
      error: null,
      isPending: false,
      isError: false,
      isSuccess: false,
      reset: vi.fn(),
    }),
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
      getQueryData: vi.fn(),
      removeQueries: vi.fn(),
      cancelQueries: vi.fn(),
      refetchQueries: vi.fn(),
      prefetchQuery: vi.fn(),
    }),
  };
});

import AnalyzePage from '@/pages/AnalyzePage';

describe('AnalyzePage', () => {
  it('renders the new tab by default with the analysis form', async () => {
    render(<AnalyzePage />);

    expect(screen.getByTestId('analyze-page')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '📝 单股分析', level: 1 })).toBeInTheDocument();

    // 5 tab buttons
    expect(screen.getByTestId('analyze-tab-new')).toBeInTheDocument();
    expect(screen.getByTestId('analyze-tab-progress')).toBeInTheDocument();
    expect(screen.getByTestId('analyze-tab-report')).toBeInTheDocument();
    expect(screen.getByTestId('analyze-tab-history')).toBeInTheDocument();
    expect(screen.getByTestId('analyze-tab-workspace')).toBeInTheDocument();

    // Default panel is new + form
    await waitFor(() => expect(screen.getByTestId('analysis-form')).toBeInTheDocument());
    expect(screen.getByTestId('ticker-input')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-form-submit')).toBeInTheDocument();
  });

  it('switches to the progress tab and renders the 7 stage cards', async () => {
    render(<AnalyzePage />);
    screen.getByTestId('analyze-tab-progress').click();
    await waitFor(() => expect(screen.getByTestId('analysis-progress')).toBeInTheDocument());
    expect(screen.getByTestId('analysis-stage-market')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-stage-lockup')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-progress-elapsed')).toBeInTheDocument();
  });

  it('switches to the history tab and renders the recent analysis table', async () => {
    render(<AnalyzePage />);
    screen.getByTestId('analyze-tab-history').click();
    await waitFor(() => expect(screen.getByTestId('analysis-recent-table')).toBeInTheDocument());
    expect(screen.getByTestId('analysis-recent-row-a-001')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-recent-row-a-002')).toBeInTheDocument();
  });

  it('switches to the workspace tab and renders 7 analyst cards', async () => {
    render(<AnalyzePage />);
    screen.getByTestId('analyze-tab-workspace').click();
    await waitFor(() => expect(screen.getByTestId('analysis-workspace')).toBeInTheDocument());
    expect(screen.getByTestId('analysis-workspace-card-market_report')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-workspace-card-lockup_report')).toBeInTheDocument();
  });

  it('switches to the report tab and renders the 7 trader report cards', async () => {
    render(<AnalyzePage />);
    screen.getByTestId('analyze-tab-report').click();
    await waitFor(() => expect(screen.getByTestId('analysis-report')).toBeInTheDocument());
    expect(screen.getByTestId('analysis-report-card-market_report')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-report-card-lockup_report')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-report-signal')).toBeInTheDocument();
  });
});