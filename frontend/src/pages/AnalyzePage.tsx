/**
 * AnalyzePage — mirrors web/components/analyze_panel.py::render_analyze_panel().
 *
 * Five tabs driven by 4 GET endpoints + 1 POST endpoint:
 *   1. 新建     → form (POST /api/analyze on submit)
 *   2. 进度     → polling progress bar (GET /api/analyze/{id} every 2s while running)
 *   3. 报告     → 7-card analyst report (GET /api/analyze/{id}/report)
 *   4. 历史     → recent list (GET /api/analyze/recent?limit=20)
 *   5. 工作区   → live 7-stage intermediate reports from /api/analyze/{id}
 *
 * Same React Query + 5-tab inline dispatcher pattern as SchedulePage and
 * SectorPage; queries run in parallel so the first paint shows whichever
 * finishes first.
 */
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
import { Sparkles, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  getAnalysis,
  getAnalysisReport,
  getRecentAnalyzes,
  startAnalysis,
} from '@/api/analyze';
import type { AnalyzeRequest, RecentAnalyzeItem } from '@/api/analyze';
import { AnalysisForm } from '@/components/analyze/analysis-form';
import { AnalysisProgress } from '@/components/analyze/analysis-progress';
import { AnalysisReport } from '@/components/analyze/analysis-report';
import { AnalysisRecentList } from '@/components/analyze/analysis-recent-list';
import { AnalysisWorkspace } from '@/components/analyze/analysis-workspace';

type TabKey = 'new' | 'progress' | 'report' | 'history' | 'workspace';

interface TabDef {
  key: TabKey;
  label: string;
  testid: string;
}

const TABS: TabDef[] = [
  { key: 'new', label: '新建', testid: 'analyze-tab-new' },
  { key: 'progress', label: '进度', testid: 'analyze-tab-progress' },
  { key: 'report', label: '报告', testid: 'analyze-tab-report' },
  { key: 'history', label: '历史', testid: 'analyze-tab-history' },
  { key: 'workspace', label: '工作区', testid: 'analyze-tab-workspace' },
];

const DEFAULT_TAB: TabKey = 'new';
const POLL_INTERVAL_MS = 2000;

export function AnalyzePage() {
  const [activeTab, setActiveTab] = React.useState<TabKey>(DEFAULT_TAB);
  const [activeAnalysisId, setActiveAnalysisId] = React.useState<string | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);
  const queryClient = useQueryClient();

  // Recent list — always live so the history tab can show latest.
  const recentQuery = useQuery({
    queryKey: ['analyze-recent', 20],
    queryFn: () => getRecentAnalyzes(20),
    staleTime: 10_000,
    refetchOnWindowFocus: false,
  });

  // Live progress (only when we have an active analysis).
  const progressQuery = useQuery({
    queryKey: ['analyze-progress', activeAnalysisId],
    queryFn: () => getAnalysis(activeAnalysisId!),
    enabled: Boolean(activeAnalysisId),
    refetchInterval: (q) => {
      const status = (q.state.data as { status?: string } | undefined)?.status;
      if (status === 'ok' || status === 'error' || status === 'complete') {
        return false;
      }
      return POLL_INTERVAL_MS;
    },
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  // Full report (lazy — only when user clicks 报告 tab).
  const reportQuery = useQuery({
    queryKey: ['analyze-report', activeAnalysisId],
    queryFn: () => getAnalysisReport(activeAnalysisId!),
    enabled: Boolean(activeAnalysisId) && activeTab === 'report',
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const startMut = useMutation({
    mutationFn: (payload: AnalyzeRequest) => startAnalysis(payload),
    onSuccess: (result) => {
      setFormError(null);
      setActiveAnalysisId(result.analysis_id);
      setActiveTab('progress');
      void queryClient.invalidateQueries({ queryKey: ['analyze-recent'] });
    },
    onError: (e) => setFormError(e instanceof Error ? e.message : String(e)),
  });

  function handleRefresh() {
    void recentQuery.refetch();
    void progressQuery.refetch();
    void reportQuery.refetch();
  }

  function handleSelectRecent(analysisId: string) {
    setActiveAnalysisId(analysisId);
    setActiveTab('report');
  }

  async function handleSubmit(payload: AnalyzeRequest) {
    await startMut.mutateAsync(payload);
  }

  function errStr(q: { error: unknown }): string | null {
    return q.error instanceof Error ? q.error.message : null;
  }
  const recentError = errStr(recentQuery);
  const progressError = errStr(progressQuery);
  const reportError = errStr(reportQuery);

  const recentItems = recentQuery.data ?? [];
  const progress = progressQuery.data ?? null;
  const isComplete = progress?.status === 'ok' || progress?.status === 'complete';

  // Auto-advance from 进度 to 报告 when run finishes.
  React.useEffect(() => {
    if (isComplete && activeTab === 'progress') {
      setActiveTab('report');
    }
  }, [isComplete, activeTab]);

  const isFetching =
    recentQuery.isFetching || progressQuery.isFetching || reportQuery.isFetching;

  return (
    <div
      data-testid="analyze-page"
      className="mx-auto w-full max-w-7xl space-y-6"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-6 w-6" />
            <h1 className="text-inherit font-inherit">📝 单股分析</h1>
          </CardTitle>
          <CardDescription>
            7 位分析师 (市场/情绪/新闻/基本面/政策/游资/解禁) + 多空辩论 + 风险管理 ·
            引擎 backend.core.start_analysis (复用 web.runner.run_one_analysis) ·
            与 Streamlit <code>web/components/analyze_panel.py</code> 共用同一业务函数, 0 改业务层
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm text-text-secondary">
              {recentQuery.data
                ? `共 ${recentItems.length} 条历史分析`
                : '加载中…'}
              {activeAnalysisId && (
                <span className="ml-3 font-mono text-xs text-text-tertiary">
                  当前: {activeAnalysisId}
                </span>
              )}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={isFetching}
              data-testid="analyze-refresh"
            >
              <RefreshCw className={isFetching ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
              刷新
            </Button>
          </div>

          {/* Tab strip */}
          <div
            role="tablist"
            aria-label="单股分析视图"
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
                  aria-controls={`analyze-tabpanel-${tab.key}`}
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
            id={`analyze-tabpanel-${activeTab}`}
            aria-labelledby={`analyze-tab-${activeTab}`}
            data-testid={`analyze-panel-${activeTab}`}
            className="pt-2 space-y-4"
          >
            {activeTab === 'new' && (
              <div>
                <h2 className="text-sm font-semibold mb-2">新建单股分析</h2>
                <AnalysisForm
                  onSubmit={handleSubmit}
                  isSubmitting={startMut.isPending}
                  errorMessage={formError}
                />
              </div>
            )}

            {activeTab === 'progress' && (
              progressError ? (
                <Alert variant="destructive" data-testid="analyze-progress-error">
                  <AlertTitle>加载进度失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{progressError}</span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void progressQuery.refetch()}
                    >
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <AnalysisProgress
                  progress={progress}
                  isPolling={Boolean(progressQuery.isFetching)}
                />
              )
            )}

            {activeTab === 'report' && (
              <AnalysisReport
                report={reportQuery.data ?? null}
                isLoading={reportQuery.isLoading}
                error={reportError}
              />
            )}

            {activeTab === 'history' && (
              recentError ? (
                <Alert variant="destructive" data-testid="analyze-recent-error">
                  <AlertTitle>加载历史分析失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{recentError}</span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void recentQuery.refetch()}
                    >
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <AnalysisRecentList
                  items={recentItems}
                  isLoading={recentQuery.isLoading}
                  error={null}
                  selectedId={activeAnalysisId}
                  onSelect={handleSelectRecent}
                />
              )
            )}

            {activeTab === 'workspace' && (
              progressError ? (
                <Alert variant="destructive" data-testid="analyze-workspace-error">
                  <AlertTitle>加载工作区失败</AlertTitle>
                  <AlertDescription>{progressError}</AlertDescription>
                </Alert>
              ) : (
                <AnalysisWorkspace
                  stageReports={progress?.stage_reports ?? null}
                  currentStage={progress?.current_stage ?? null}
                  isLoading={progressQuery.isLoading}
                  error={null}
                />
              )
            )}
          </div>

          <p className="text-xs text-text-tertiary">
            单股分析模块基于 web.runner.run_one_analysis + backend.core.start_analysis
            + history_store 单例, 与 Streamlit <code>web/components/analyze_panel.py</code>
            共用同一业务函数, 0 改业务层
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default AnalyzePage;