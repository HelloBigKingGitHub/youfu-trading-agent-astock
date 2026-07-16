import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Clock, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  createSchedule,
  deleteSchedule,
  listNotifierChannels,
  listSchedules,
  listWatchlist,
  pauseSchedule,
  resumeSchedule,
  runNow,
  updateSchedule,
} from '@/api/schedule';
import type { CreateSchedulePayload, Schedule } from '@/api/schedule';
import { ScheduleList } from '@/components/schedule/schedule-list';
import { ScheduleDetail } from '@/components/schedule/schedule-detail';
import { ScheduleForm } from '@/components/schedule/schedule-form';
import { WatchlistManager } from '@/components/schedule/watchlist-manager';
import { NotifierConfig } from '@/components/schedule/notifier-config';
import { ScheduleRuns } from '@/components/schedule/schedule-runs';

// SchedulePage — mirrors `web/components/schedule_panel.py::render_schedule_panel()`.
//
// Five tabs driven by 4 GET endpoints (list/detail/watchlist/notifier-channels):
//   1. 总览       → /api/schedule/list + /api/schedule/{id}
//   2. 历史       → /api/schedule/{id} (run history aggregated across first 5 scheds)
//   3. 自选股    → /api/schedule/watchlist
//   4. 通知       → /api/schedule/notifier/channels (+ test_notify fire)
//   5. 创建       → POST /api/schedule/create form
//
// Same React Query + 5-tab pattern as SectorPage; all 4 base queries run in
// parallel so the first paint shows whichever finishes first.

type TabKey = 'overview' | 'runs' | 'watchlist' | 'notifier' | 'create';

interface TabDef {
  key: TabKey;
  label: string;
  testid: string;
}

const TABS: TabDef[] = [
  { key: 'overview', label: '总览', testid: 'schedule-tab-overview' },
  { key: 'runs', label: '历史', testid: 'schedule-tab-runs' },
  { key: 'watchlist', label: '自选股', testid: 'schedule-tab-watchlist' },
  { key: 'notifier', label: '通知', testid: 'schedule-tab-notifier' },
  { key: 'create', label: '创建', testid: 'schedule-tab-create' },
];

const DEFAULT_TAB: TabKey = 'overview';

function readTab(value: string | null): TabKey {
  if (
    value === 'overview' || value === 'runs' || value === 'watchlist'
    || value === 'notifier' || value === 'create'
  ) {
    return value;
  }
  return DEFAULT_TAB;
}

function scheduleById(schedules: Schedule[], id: string | null): Schedule | null {
  if (!id) return null;
  return schedules.find((s) => s.schedule_id === id) ?? null;
}

export function SchedulePage() {
  const [activeTab, setActiveTab] = React.useState<TabKey>(DEFAULT_TAB);
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [createError, setCreateError] = React.useState<string | null>(null);
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ['schedule-list'],
    queryFn: () => listSchedules(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
  const watchlistQuery = useQuery({
    queryKey: ['schedule-watchlist'],
    queryFn: () => listWatchlist(),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const channelsQuery = useQuery({
    queryKey: ['schedule-notifier-channels'],
    queryFn: () => listNotifierChannels(),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  // detail query (depends on selectedId)
  const detailQuery = useQuery({
    queryKey: ['schedule-detail', selectedId],
    queryFn: () => import('@/api/schedule').then((m) => m.getSchedule(selectedId!)),
    enabled: Boolean(selectedId),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  const invalidate = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['schedule-list'] });
    void queryClient.invalidateQueries({ queryKey: ['schedule-detail'] });
  }, [queryClient]);

  const runMut = useMutation({
    mutationFn: (id: string) => runNow(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => {
      setBusyId(null);
      invalidate();
    },
  });
  const pauseMut = useMutation({
    mutationFn: (id: string) => pauseSchedule(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => {
      setBusyId(null);
      invalidate();
    },
  });
  const resumeMut = useMutation({
    mutationFn: (id: string) => resumeSchedule(id),
    onMutate: (id) => setBusyId(id),
    onSettled: () => {
      setBusyId(null);
      invalidate();
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteSchedule(id),
    onMutate: (id) => setBusyId(id),
    onSettled: (_, __, id) => {
      setBusyId(null);
      if (selectedId === id) setSelectedId(null);
      invalidate();
    },
  });

  const createMut = useMutation({
    mutationFn: (payload: CreateSchedulePayload) => createSchedule(payload),
    onSuccess: () => {
      setCreateError(null);
      setActiveTab('overview');
      invalidate();
    },
    onError: (e) => setCreateError(e instanceof Error ? e.message : String(e)),
  });

  function handleRefresh() {
    void listQuery.refetch();
    void watchlistQuery.refetch();
    void channelsQuery.refetch();
    void detailQuery.refetch();
  }

  function errStr(q: { error: unknown }): string | null {
    return q.error instanceof Error ? q.error.message : null;
  }
  const listError = errStr(listQuery);
  const watchlistError = errStr(watchlistQuery);
  const channelsError = errStr(channelsQuery);
  const detailError = errStr(detailQuery);

  const listData = listQuery.data;
  const schedules = listData?.schedules ?? [];
  const schedulerRunning = listData?.scheduler_running ?? false;

  async function handleAction(action: 'run' | 'pause' | 'resume' | 'delete', id: string) {
    if (action === 'run') await runMut.mutateAsync(id);
    if (action === 'pause') await pauseMut.mutateAsync(id);
    if (action === 'resume') await resumeMut.mutateAsync(id);
    if (action === 'delete') await deleteMut.mutateAsync(id);
  }

  async function handleCreate(payload: CreateSchedulePayload) {
    await createMut.mutateAsync(payload);
  }

  // auto-pick first schedule when schedules arrive and nothing selected
  React.useEffect(() => {
    if (!selectedId && schedules.length > 0) {
      setSelectedId(schedules[0].schedule_id);
    }
  }, [schedules, selectedId]);

  const isFetching =
    listQuery.isFetching || watchlistQuery.isFetching || channelsQuery.isFetching;

  return (
    <div
      data-testid="schedule-page"
      className="mx-auto w-full max-w-7xl space-y-6"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-6 w-6" />
            <h1 className="text-inherit font-inherit">⏰ 定时分析</h1>
          </CardTitle>
          <CardDescription>
            Cron 调度 + ticker 源 (持仓 / 自选股 / 手动) + 4 渠道通知
            (WeCom / Email / Desktop / Log) · 引擎 backend.core.scheduler
            (单例 + 60s polling) · 共享 batch_job_queue + portfolio_store
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm text-text-secondary">
              {listData
                ? `共 ${listData.count} 个定时任务 · scheduler ${schedulerRunning ? '运行中' : '已停止'}`
                : '加载中…'}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={isFetching}
              data-testid="schedule-refresh"
            >
              <RefreshCw className={isFetching ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
              刷新
            </Button>
          </div>

          {/* Tab strip */}
          <div
            role="tablist"
            aria-label="定时分析视图"
            className="flex flex-wrap gap-2 border-b border-border-1 pb-2"
          >
            {TABS.map((tab) => {
              const isActive = activeTab === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`schedule-tabpanel-${tab.key}`}
                  data-testid={tab.testid}
                  onClick={() => setActiveTab(tab.key)}
                  className={cn(
                    'px-3 py-1.5 text-sm rounded-t-md transition-colors',
                    isActive
                      ? 'bg-bb-accent-glow text-bb-accent font-semibold ring-1 ring-bb-accent/40 ' +
                        'shadow-[inset_0_-3px_0_0_var(--bb-accent-bright)]'
                      : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated',
                  )}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab panel */}
          <div
            role="tabpanel"
            id={`schedule-tabpanel-${activeTab}`}
            aria-labelledby={`schedule-tab-${activeTab}`}
            data-testid={`schedule-panel-${activeTab}`}
            className="pt-2 space-y-4"
          >
            {activeTab === 'overview' && (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div>
                  <h2 className="text-sm font-semibold mb-2">任务列表</h2>
                  {listError ? (
                    <Alert variant="destructive" data-testid="schedule-list-error">
                      <AlertTitle>加载任务列表失败</AlertTitle>
                      <AlertDescription className="flex items-center gap-3">
                        <span>{listError}</span>
                        <Button type="button" variant="outline" size="sm" onClick={() => void listQuery.refetch()}>
                          重试
                        </Button>
                      </AlertDescription>
                    </Alert>
                  ) : (
                    <ScheduleList
                      schedules={schedules}
                      isLoading={listQuery.isLoading}
                      onSelect={setSelectedId}
                      selectedId={selectedId}
                      onAction={handleAction}
                      busyId={busyId}
                    />
                  )}
                </div>
                <div>
                  <h2 className="text-sm font-semibold mb-2">任务详情</h2>
                  {detailError ? (
                    <Alert variant="destructive" data-testid="schedule-detail-error">
                      <AlertTitle>加载详情失败</AlertTitle>
                      <AlertDescription>{detailError}</AlertDescription>
                    </Alert>
                  ) : (
                    <ScheduleDetail
                      schedule={
                        detailQuery.data?.schedule
                          ?? scheduleById(schedules, selectedId)
                      }
                      runs={detailQuery.data?.runs ?? []}
                      isLoading={detailQuery.isLoading}
                    />
                  )}
                </div>
              </div>
            )}

            {activeTab === 'runs' && (
              <ScheduleRuns
                schedules={schedules}
                isLoading={listQuery.isLoading}
                error={listError}
              />
            )}

            {activeTab === 'watchlist' && (
              watchlistError ? (
                <Alert variant="destructive" data-testid="schedule-watchlist-error">
                  <AlertTitle>加载自选股失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{watchlistError}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => void watchlistQuery.refetch()}>
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <WatchlistManager
                  entries={watchlistQuery.data?.entries ?? []}
                  validTags={watchlistQuery.data?.valid_tags ?? []}
                  isLoading={watchlistQuery.isLoading}
                />
              )
            )}

            {activeTab === 'notifier' && (
              channelsError ? (
                <Alert variant="destructive" data-testid="schedule-notifier-error">
                  <AlertTitle>加载通知渠道失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{channelsError}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => void channelsQuery.refetch()}>
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <NotifierConfig
                  channels={channelsQuery.data?.channels ?? []}
                  enabledChannels={channelsQuery.data?.enabled_channels ?? []}
                  isLoading={channelsQuery.isLoading}
                />
              )
            )}

            {activeTab === 'create' && (
              <div>
                <h2 className="text-sm font-semibold mb-2">新建定时任务</h2>
                <ScheduleForm
                  watchlist={watchlistQuery.data?.entries ?? []}
                  onSubmit={handleCreate}
                  onCancel={() => setActiveTab('overview')}
                  isSubmitting={createMut.isPending}
                  errorMessage={createError}
                />
              </div>
            )}
          </div>

          <p className="text-xs text-text-tertiary">
            定时分析模块基于 Schedule + ScheduleRun 单例 + croniter, 与 Streamlit
            <code>web/components/schedule_panel.py</code> 共用同一业务函数
            <code>backend.core.scheduler</code>, 0 改业务层。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default SchedulePage;