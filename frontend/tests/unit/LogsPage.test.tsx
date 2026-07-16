import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  listTickersImpl: vi.fn(),
  listTasksImpl: vi.fn(),
  getChunksImpl: vi.fn(),
}));

const MOCK_TICKERS = [
  {
    ticker: '600595',
    task_count: 82,
    latest_signal: 'Buy',
    latest_status: 'completed',
    latest_trade_date: '2026-07-16',
  },
  {
    ticker: '603313',
    task_count: 1,
    latest_signal: 'Underweight',
    latest_status: 'completed',
    latest_trade_date: '2026-07-09',
  },
];

const MOCK_TASKS = [
  {
    analysis_id: '600595_2026-07-16_aaaaaaaa',
    ticker: '600595',
    trade_date: '2026-07-16',
    task_dir_name: '2026-07-16_run01',
    status: 'completed',
    signal: 'Buy',
    elapsed_sec: 12.34,
    started_at: '1784166305.0',
    finished_at: '1784166317.0',
    chunk_counts: { llm: 4, tool: 0, agent_output: 8 },
    is_legacy: false,
  },
  {
    analysis_id: '600595_2026-07-15_bbbbbbbb',
    ticker: '600595',
    trade_date: '2026-07-15',
    task_dir_name: '2026-07-15_run01',
    status: 'completed',
    signal: 'Hold',
    elapsed_sec: 715.2,
    started_at: '1784074549.0',
    finished_at: '1784075264.0',
    chunk_counts: { llm: 12, tool: 0, agent_output: 198 },
    is_legacy: false,
  },
];

const MOCK_CHUNKS_LLM = [
  {
    ts: 1784075105.6,
    type: 'llm',
    agent: 'research_manager',
    role: 'assistant',
    content: '<think>Bull case looks solid…</think>',
    tokens_in: 1200,
    tokens_out: 320,
  },
];

vi.mock('@/api/logs', async () => {
  const actual = await vi.importActual<typeof import('@/api/logs')>('@/api/logs');
  return {
    ...actual,
    listTickers: (...args: Parameters<typeof actual.listTickers>) => mocks.listTickersImpl(...args),
    listTasks: (...args: Parameters<typeof actual.listTasks>) => mocks.listTasksImpl(...args),
    getChunks: (...args: Parameters<typeof actual.getChunks>) => mocks.getChunksImpl(...args),
    getTask: () =>
      Promise.resolve({
        meta: MOCK_TASKS[0],
        chunk_counts: MOCK_TASKS[0].chunk_counts,
        ticker: '600595',
        task: '2026-07-16_run01',
      }),
    getCounts: () => Promise.resolve({}),
  };
});

// We mock useQuery with a stub that returns data based on the queryKey, so
// each panel receives the right shape.
vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>(
    '@tanstack/react-query'
  );
  return {
    ...actual,
    useQuery: ({ queryKey }: { queryKey: unknown[] }) => {
      const key = queryKey[0] as string;
      if (key === 'logs-tickers') {
        return {
          data: { tickers: MOCK_TICKERS, total: MOCK_TICKERS.length },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (key === 'logs-tasks') {
        // Per-ticker view: 603313 has no tasks in the mock fixture (so we
        // can assert the empty state on click). The first selected ticker
        // (600595) sees the full task list.
        const ticker = queryKey[1] as string | undefined;
        const tasks = ticker === '603313' ? [] : MOCK_TASKS;
        return {
          data: { ticker: ticker ?? '600595', tasks, total: tasks.length },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (key === 'logs-chunks') {
        const tab = queryKey[3] as string;
        const chunks = tab === 'llm' ? MOCK_CHUNKS_LLM : [];
        return {
          data: {
            ticker: '600595',
            task: '2026-07-16_run01',
            type: tab,
            chunks,
            total: chunks.length,
            counts: { llm: MOCK_CHUNKS_LLM.length, tool: 0, agent_output: 0 },
          },
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
    useMutation: () => ({ isPending: false, mutate: vi.fn(), variables: undefined }),
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  };
});

import { LogsPage } from '@/pages/LogsPage';

describe('LogsPage', () => {
  beforeEach(() => {
    mocks.listTickersImpl.mockClear();
    mocks.listTasksImpl.mockClear();
    mocks.getChunksImpl.mockClear();
    mocks.listTickersImpl.mockResolvedValue({
      tickers: MOCK_TICKERS,
      total: MOCK_TICKERS.length,
    });
    mocks.listTasksImpl.mockResolvedValue({
      ticker: '600595',
      tasks: MOCK_TASKS,
      total: MOCK_TASKS.length,
    });
  });

  function renderPage() {
    return render(<LogsPage />);
  }

  it('renders ticker list, task list, chunk viewer with 3 tabs', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByTestId('logs-page')).toBeInTheDocument());
    // Tickers
    expect(screen.getByTestId('ticker-list')).toBeInTheDocument();
    expect(screen.getByTestId('ticker-card-600595')).toBeInTheDocument();
    expect(screen.getByTestId('ticker-card-603313')).toBeInTheDocument();

    // Default-select happens; task list visible.
    await waitFor(() => expect(screen.getByTestId('task-list')).toBeInTheDocument());
    expect(screen.getByTestId('task-card-2026-07-16_run01')).toBeInTheDocument();
    expect(screen.getByTestId('task-card-2026-07-15_run01')).toBeInTheDocument();

    // Chunk viewer mounted with 3 tabs.
    await waitFor(() => expect(screen.getByTestId('chunk-viewer')).toBeInTheDocument());
    expect(screen.getByTestId('chunk-tab-agent_output')).toBeInTheDocument();
    expect(screen.getByTestId('chunk-tab-llm')).toBeInTheDocument();
    expect(screen.getByTestId('chunk-tab-tool')).toBeInTheDocument();

    // Total counter
    expect(screen.getByTestId('logs-ticker-total')).toHaveTextContent('2');
  });

  it('clicking a ticker switches the task list', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('logs-page')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('ticker-card-603313'));

    // The right column should now be empty (no tasks for 603313 in the
    // mock) — confirm the prompt text appears.
    await waitFor(() =>
      expect(screen.getByTestId('task-list-empty')).toBeInTheDocument()
    );
  });

  it('clicking a task card mounts the chunk viewer with the selected task', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('logs-page')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('task-card-2026-07-15_run01'));
    await waitFor(() => expect(screen.getByTestId('chunk-viewer')).toBeInTheDocument());

    // Default tab is agent_output → empty (mock has no agent_output chunks)
    expect(screen.getByTestId('chunk-tab-agent_output')).toHaveAttribute(
      'aria-selected',
      'true'
    );

    // Switch to LLM tab → mock has 1 chunk → chunk card renders.
    fireEvent.click(screen.getByTestId('chunk-tab-llm'));
    await waitFor(() =>
      expect(screen.getByTestId('chunk-tab-llm')).toHaveAttribute('aria-selected', 'true')
    );
    expect(screen.getAllByTestId('chunk-card-llm')).toHaveLength(1);
  });
});