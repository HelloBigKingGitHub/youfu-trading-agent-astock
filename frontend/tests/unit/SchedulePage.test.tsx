import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { MOCK_SCHEDULES, MOCK_WATCHLIST, MOCK_CHANNELS } = vi.hoisted(() => ({
  MOCK_SCHEDULES: [
    {
      schedule_id: 'sched-001',
      name: '每日持仓复盘',
      cron_expr: '0 18 * * 1-5',
      source_type: 'portfolio',
      source_config: {},
      enabled: true,
      notify_channels: ['log', 'desktop'],
      notify_template: 'v0.6.0 default',
      config: {},
      last_run_at: 1784190800,
      last_run_batch_id: 'batch_abc',
      last_run_status: 'ok',
      last_error: null,
      created_at: 1784180000,
      created_by: 'preset',
      next_run_at: 1784224800,
      source_summary: '持仓',
    },
    {
      schedule_id: 'sched-002',
      name: '周一前瞻',
      cron_expr: '0 9 * * 1',
      source_type: 'watchlist',
      source_config: { tag: '长线' },
      enabled: false,
      notify_channels: ['email'],
      notify_template: 'v0.6.0 weekly',
      config: {},
      last_run_at: null,
      last_run_batch_id: null,
      last_run_status: 'never',
      last_error: null,
      created_at: 1784180000,
      created_by: 'preset',
      next_run_at: null,
      source_summary: '自选股 · 长线',
    },
  ],
  MOCK_WATCHLIST: [
    { entry_id: 'w-1', ticker: '600519', tag: '长线', note: 'core', created_at: 1784000000 },
    { entry_id: 'w-2', ticker: '000858', tag: '长线', note: 'liquor', created_at: 1784000100 },
    { entry_id: 'w-3', ticker: '300750', tag: '短线', note: 'battery', created_at: 1784000200 },
  ],
  MOCK_CHANNELS: [
    { channel: 'wecom', label: 'WeCom', enabled_in_config: false, configured: false, supports_test: true, test_endpoint: '/api/schedule/0/test_notify?channel=wecom' },
    { channel: 'email', label: 'Email', enabled_in_config: true, configured: true, supports_test: true, test_endpoint: '/api/schedule/0/test_notify?channel=email' },
    { channel: 'desktop', label: 'Desktop', enabled_in_config: false, configured: false, supports_test: true, test_endpoint: '/api/schedule/0/test_notify?channel=desktop' },
    { channel: 'log', label: 'Log', enabled_in_config: true, configured: true, supports_test: true, test_endpoint: '/api/schedule/0/test_notify?channel=log' },
  ],
}));

vi.mock('@/api/schedule', async () => {
  const actual = await vi.importActual<typeof import('@/api/schedule')>('@/api/schedule');
  const sched = MOCK_SCHEDULES[0];
  return {
    ...actual,
    listSchedules: vi.fn().mockResolvedValue({
      schedules: MOCK_SCHEDULES,
      count: MOCK_SCHEDULES.length,
      scheduler_running: true,
      last_tick_at: 1784190900,
      fetched_at: 1784190900,
    }),
    listWatchlist: vi.fn().mockResolvedValue({
      entries: MOCK_WATCHLIST,
      count: MOCK_WATCHLIST.length,
      valid_tags: ['T0', 'T1', 'T2', '短线', '观察', '长线'],
      fetched_at: 1784190900,
    }),
    listNotifierChannels: vi.fn().mockResolvedValue({
      channels: MOCK_CHANNELS,
      count: MOCK_CHANNELS.length,
      enabled_channels: ['email', 'log'],
      fetched_at: 1784190900,
    }),
    getSchedule: vi.fn().mockImplementation((sid: string) => {
      console.log('mock getSchedule called with', sid);
      return Promise.resolve({
        schedule: sched,
        runs: [
          { run_id: 'run-1', schedule_id: sched.schedule_id, started_at: 1784190700, finished_at: 1784190800, status: 'ok', batch_id: 'batch_abc', job_ids: ['j-1'], duration: 100.5, summary: 'ok', error: null, ticker_count: 3 },
        ],
        fetched_at: 1784190900,
      });
    }),
    createSchedule: vi.fn().mockResolvedValue({ schedule: sched, runs: [], fetched_at: 1784190900 }),
    updateSchedule: vi.fn().mockResolvedValue({ schedule_id: sched.schedule_id, updated_at: 1784190900 }),
    deleteSchedule: vi.fn().mockResolvedValue({ deleted: true, schedule_id: sched.schedule_id }),
    pauseSchedule: vi.fn().mockResolvedValue({ paused: true, schedule_id: sched.schedule_id, paused_at: 1784190900 }),
    resumeSchedule: vi.fn().mockResolvedValue({ resumed: true, schedule_id: sched.schedule_id, resumed_at: 1784190900 }),
    runNow: vi.fn().mockResolvedValue({ triggered: true, schedule_id: sched.schedule_id, triggered_at: 1784190900 }),
    testNotify: vi.fn().mockResolvedValue({ run_id: 'tn-1', channel: 'log', status: 'running', schedule_id: '0' }),
    getRun: vi.fn().mockResolvedValue({ run: { run_id: 'run-1', schedule_id: sched.schedule_id, started_at: 0, finished_at: 0, status: 'ok', batch_id: '', job_ids: [], duration: 0, summary: '', error: null, ticker_count: 0 }, fetched_at: 0 }),
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
      if (k === 'schedule-list') {
        return {
          data: {
            schedules: MOCK_SCHEDULES,
            count: MOCK_SCHEDULES.length,
            scheduler_running: true,
            last_tick_at: 1784190900,
            fetched_at: 1784190900,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'schedule-watchlist') {
        return {
          data: {
            entries: MOCK_WATCHLIST,
            count: MOCK_WATCHLIST.length,
            valid_tags: ['T0', 'T1', 'T2', '短线', '观察', '长线'],
            fetched_at: 1784190900,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'schedule-notifier-channels') {
        return {
          data: {
            channels: MOCK_CHANNELS,
            count: MOCK_CHANNELS.length,
            enabled_channels: ['email', 'log'],
            fetched_at: 1784190900,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      if (k === 'schedule-detail') {
        const sched = MOCK_SCHEDULES[0];
        return {
          data: {
            schedule: sched,
            runs: [
              { run_id: 'run-1', schedule_id: sched.schedule_id, started_at: 1784190700, finished_at: 1784190800, status: 'ok', batch_id: 'batch_abc', job_ids: ['j-1'], duration: 100.5, summary: 'ok', error: null, ticker_count: 3 },
            ],
            fetched_at: 1784190900,
          },
          isLoading: false,
          isFetching: false,
          error: null,
          refetch: vi.fn(),
        };
      }
      // ScheduleRuns aggregation query — runs across the first MAX_SCHEDULES (5)
      // schedule ids. Mocked as a single object so the table renders without
      // requiring real getSchedule calls + Promise.all timing in jsdom.
      if (k === 'schedule-runs') {
        const sched = MOCK_SCHEDULES[0];
        return {
          data: [
            {
              run_id: 'run-1',
              schedule_id: sched.schedule_id,
              started_at: 1784190700,
              finished_at: 1784190800,
              status: 'ok',
              batch_id: 'batch_abc',
              job_ids: ['j-1'],
              duration: 100.5,
              summary: 'ok',
              error: null,
              ticker_count: 3,
              schedule_name: sched.name,
            },
          ],
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

import SchedulePage from '@/pages/SchedulePage';

describe('SchedulePage', () => {
  it('renders the overview tab by default with schedule table', async () => {
    render(<SchedulePage />);

    expect(screen.getByTestId('schedule-page')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /定时分析/ })).toBeInTheDocument();

    // 5 tab buttons
    expect(screen.getByTestId('schedule-tab-overview')).toBeInTheDocument();
    expect(screen.getByTestId('schedule-tab-runs')).toBeInTheDocument();
    expect(screen.getByTestId('schedule-tab-watchlist')).toBeInTheDocument();
    expect(screen.getByTestId('schedule-tab-notifier')).toBeInTheDocument();
    expect(screen.getByTestId('schedule-tab-create')).toBeInTheDocument();

    // Default overview panel renders the schedule list
    await waitFor(() => expect(screen.getByTestId('schedule-table')).toBeInTheDocument());
    expect(screen.getByTestId('schedule-row-sched-001')).toBeInTheDocument();
    expect(screen.getByTestId('schedule-row-sched-002')).toBeInTheDocument();
  });

  it('switches to the watchlist tab and renders the watchlist table', async () => {
    render(<SchedulePage />);
    screen.getByTestId('schedule-tab-watchlist').click();
    await waitFor(() => expect(screen.getByTestId('watchlist-table')).toBeInTheDocument());
    expect(screen.getByTestId('watchlist-row-w-1')).toBeInTheDocument();
    expect(screen.getByTestId('watchlist-row-w-3')).toBeInTheDocument();
  });

  it('switches to the notifier tab and renders 4 channel cards', async () => {
    render(<SchedulePage />);
    screen.getByTestId('schedule-tab-notifier').click();
    await waitFor(() => expect(screen.getByTestId('notifier-config')).toBeInTheDocument());
    expect(screen.getByTestId('notifier-channel-wecom')).toBeInTheDocument();
    expect(screen.getByTestId('notifier-channel-email')).toBeInTheDocument();
    expect(screen.getByTestId('notifier-channel-desktop')).toBeInTheDocument();
    expect(screen.getByTestId('notifier-channel-log')).toBeInTheDocument();
  });

  it('switches to the create tab and renders the schedule form', async () => {
    render(<SchedulePage />);
    screen.getByTestId('schedule-tab-create').click();
    await waitFor(() => expect(screen.getByTestId('schedule-form')).toBeInTheDocument());
    expect(screen.getByTestId('schedule-form-name')).toBeInTheDocument();
    expect(screen.getByTestId('schedule-form-cron')).toBeInTheDocument();
    expect(screen.getByTestId('schedule-form-submit')).toBeInTheDocument();
  });

  it('switches to the runs tab and renders the history table', async () => {
    render(<SchedulePage />);
    screen.getByTestId('schedule-tab-runs').click();
    // Wait for ScheduleRuns.useEffect → fetchRuns → getSchedule (mocked) → setRuns
    // to populate the table. ScheduleRuns renders schedule-runs-empty on first
    // render (loadingRuns=false, runs=[] defaults), then useEffect kicks off the
    // Promise.all over schedules, and the resolved runs land in state — at
    // which point the table replaces the empty placeholder.
    await new Promise((r) => setTimeout(r, 500));
    const apiModule = await import('@/api/schedule');
    console.log('api.getSchedule is', typeof apiModule.getSchedule, apiModule.getSchedule?.toString?.()?.slice(0, 100));
    await waitFor(() => expect(screen.getByTestId('schedule-runs-table')).toBeInTheDocument(), { timeout: 8000 });
    const rows = screen.getAllByTestId('schedule-runs-row-run-1');
    expect(rows.length).toBeGreaterThanOrEqual(1);
  }, 15000);
});