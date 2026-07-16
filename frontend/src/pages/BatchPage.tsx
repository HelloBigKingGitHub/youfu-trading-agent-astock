import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  BarChart3, FileSpreadsheet, History, ListOrdered,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  cancelBatch,
  createBatch,
  getBatchProgress,
  getBatchSummary,
  listBatches,
  parseTickerList,
  retryJob,
  type BatchItemInput,
  type BatchJob,
  type BatchProgressResponse,
} from '@/api/batch';
import { TickerInput } from '@/components/batch/ticker-input';
import { BatchConfigForm, type BatchConfig } from '@/components/batch/batch-config-form';
import { BatchProgress } from '@/components/batch/batch-progress';
import { BatchSummary } from '@/components/batch/batch-summary';
import { BatchList } from '@/components/batch/batch-list';
import { StartButton } from '@/components/batch/start-button';

const TICKERS_DEFAULT = '688017\n600519\n000001';
const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATUSES = new Set(['completed', 'error', 'cancelled']);

type TabKey = 'submit' | 'progress' | 'history';

interface TabDef {
  key: TabKey;
  label: string;
  testid: string;
  icon: React.ComponentType<{ className?: string }>;
}

const TABS: TabDef[] = [
  { key: 'submit',   label: '新建批量任务', testid: 'batch-tab-submit',   icon: FileSpreadsheet },
  { key: 'progress', label: '任务进度',     testid: 'batch-tab-progress', icon: ListOrdered    },
  { key: 'history',  label: '历史 batch',    testid: 'batch-tab-history',  icon: History        },
];

const DEFAULT_TAB: TabKey = 'submit';

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function defaultConfig(): BatchConfig {
  return {
    tradeDate: todayIso(),
    maxWorkers: 5,
    llm: { provider: '', deepModel: '', quickModel: '', baseUrl: '' },
  };
}

function isBatchTerminal(batch: BatchProgressResponse | undefined): boolean {
  if (!batch) return false;
  return TERMINAL_STATUSES.has(batch.batch_status);
}

function summaryToCsv(s: { batch_id: string; rows: Array<Record<string, unknown>> }): string {
  const headers = ['ticker', 'trade_date', 'status', 'signal', 'completed_stages_count', 'elapsed_seconds', 'error'];
  const lines = [headers.join(',')];
  for (const row of s.rows) {
    const cells = headers.map((h) => {
      const v = row[h];
      const sv = v === null || v === undefined ? '' : String(v).replace(/\n/g, ' ');
      // RFC 4180 quoting
      return /[",\n]/.test(sv) ? `"${sv.replace(/"/g, '""')}"` : sv;
    });
    lines.push(cells.join(','));
  }
  return '\ufeff' + lines.join('\n'); // UTF-8 BOM for Excel friendliness
}

function downloadCsv(batchId: string, csv: string) {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `batch_${batchId}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// BatchPage — React counterpart of web/components/batch_panel.py.
//
// Layout (single Card, three sections mirroring Streamlit):
//   1. Submit form: TickerInput + BatchConfigForm + StartButton + post-submit LLM summary
//   2. Live progress: progress bar + per-job table (with retry / view-report buttons)
//   3. History: BatchList + summary + CSV export (Tabs split "列表" / "汇总")
//
// Both UIs hit the same backend queue; polling /api/batch/{id}/progress every
// 2s while jobs are non-terminal (mirrors Streamlit's time.sleep + st.rerun).

export function BatchPage() {
  const queryClient = useQueryClient();

  const [tickerText, setTickerText] = React.useState<string>(TICKERS_DEFAULT);
  const [config, setConfig] = React.useState<BatchConfig>(defaultConfig());
  const [activeBatchId, setActiveBatchId] = React.useState<string | null>(null);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [submitInfo, setSubmitInfo] = React.useState<string | null>(null);
  const [retiringJobIds, setRetiringJobIds] = React.useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = React.useState<TabKey>(DEFAULT_TAB);

  const { clean, invalid } = React.useMemo(() => parseTickerList(tickerText), [tickerText]);

  // ── create batch mutation ─────────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (items: BatchItemInput[]) => createBatch(items, false),
    onSuccess: (data) => {
      setActiveBatchId(data.batch_id);
      setSubmitInfo(`✓ batch 已提交: ${data.batch_id} (${data.total} jobs)`);
      setSubmitError(null);
      setActiveTab('progress');
      // Refresh list/history queries immediately.
      void queryClient.invalidateQueries({ queryKey: ['batch-list'] });
      void queryClient.invalidateQueries({ queryKey: ['batch-progress', data.batch_id] });
      void queryClient.invalidateQueries({ queryKey: ['batch-summary', data.batch_id] });
    },
    onError: (err: unknown) => {
      setSubmitError(err instanceof Error ? err.message : String(err));
      setSubmitInfo(null);
    },
  });

  // ── polling progress for active batch ─────────────────────────────────────
  const progressQuery = useQuery({
    queryKey: ['batch-progress', activeBatchId],
    queryFn: () => getBatchProgress(activeBatchId!),
    enabled: !!activeBatchId,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return POLL_INTERVAL_MS;
      return isBatchTerminal(data) ? false : POLL_INTERVAL_MS;
    },
    refetchOnWindowFocus: false,
    staleTime: 0,
  });

  // ── summary query (only when terminal) ────────────────────────────────────
  const summaryQuery = useQuery({
    queryKey: ['batch-summary', activeBatchId],
    queryFn: () => getBatchSummary(activeBatchId!),
    enabled: !!activeBatchId && isBatchTerminal(progressQuery.data),
    refetchOnWindowFocus: false,
  });

  // ── historical batch list ────────────────────────────────────────────────
  const listQuery = useQuery({
    queryKey: ['batch-list', 20],
    queryFn: () => listBatches(20),
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnWindowFocus: false,
  });

  // ── cancel mutation ──────────────────────────────────────────────────────
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelBatch(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['batch-progress'] });
      void queryClient.invalidateQueries({ queryKey: ['batch-list'] });
    },
  });

  // ── retry mutation ───────────────────────────────────────────────────────
  const retryMutation = useMutation({
    mutationFn: (jobId: string) => retryJob(jobId),
    onSuccess: (_data, jobId) => {
      setRetiringJobIds((prev) => {
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: ['batch-progress'] });
    },
    onError: (_err, jobId) => {
      setRetiringJobIds((prev) => {
        const next = new Set(prev);
        next.delete(jobId);
        return next;
      });
    },
  });

  function handleSubmit() {
    setSubmitError(null);
    setSubmitInfo(null);
    if (invalid.length > 0) {
      setSubmitError(`非法 ticker: ${invalid.join(', ')}`);
      return;
    }
    if (clean.length === 0) {
      setSubmitError('请至少输入一个 ticker');
      return;
    }
    const items: BatchItemInput[] = clean.map((t) => ({
      ticker: t,
      trade_date: config.tradeDate,
      llm_provider: config.llm.provider || null,
      deep_think_llm: config.llm.deepModel || null,
      quick_think_llm: config.llm.quickModel || null,
      backend_url: config.llm.baseUrl || null,
    }));
    createMutation.mutate(items);
  }

  function handleRetry(job: BatchJob) {
    setRetiringJobIds((prev) => new Set(prev).add(job.job_id));
    retryMutation.mutate(job.job_id);
  }

  function handleViewReport(job: BatchJob) {
    // The full report is rendered by the existing History page (history panel
    // reads from full_states_log_<date>.json). We jump there with hash.
    const path = `/history?focus=${encodeURIComponent(job.ticker)}&date=${encodeURIComponent(job.trade_date)}`;
    window.location.assign(path);
  }

  function handleDownloadCsv() {
    if (summaryQuery.data) {
      downloadCsv(summaryQuery.data.batch_id, summaryToCsv(summaryQuery.data as never));
    }
  }

  function setTab(key: TabKey) {
    setActiveTab(key);
  }

  const progress = progressQuery.data;
  const isTerminal = isBatchTerminal(progress);
  const finishedCount = progress?.finished_count ?? 0;
  const errorCount = progress?.error_count ?? 0;
  const total = progress?.total ?? 0;
  const progressPct = total > 0 ? Math.min(100, Math.round((finishedCount / total) * 100)) : 0;

  return (
    <div
      data-testid="batch-page"
      className="mx-auto w-full max-w-7xl space-y-6"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-6 w-6" />
            <h1 className="text-inherit font-inherit" data-testid="batch-title">📊 批量分析</h1>
          </CardTitle>
          <CardDescription>
            一次跑多个 ticker + 同一日期,共享同一份 LLM 配置。任务在后台线程池并行,
            失败/取消的 job 可以单独重试。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Tab strip — mirrors sector page inline <button role="tab"> pattern */}
          <div
            role="tablist"
            aria-label="批量分析视图"
            className="flex flex-wrap gap-2 border-b border-border-1 pb-2"
            data-testid="batch-tabs"
          >
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.key;
              // Disable the progress tab until a batch has been submitted (or
              // selected from history), matching Streamlit's tab2 disabled
              // until st.session_state.batch_id is set.
              const disabled = tab.key === 'progress' && !activeBatchId;
              return (
                <button
                  key={tab.key}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls={`batch-tabpanel-${tab.key}`}
                  data-testid={tab.testid}
                  disabled={disabled}
                  onClick={() => !disabled && setTab(tab.key)}
                  className={cn(
                    'flex items-center px-3 py-1.5 text-sm rounded-t-md transition-colors',
                    disabled
                      ? 'text-text-tertiary opacity-60 cursor-not-allowed'
                      : isActive
                        ? 'bg-bb-accent-glow text-bb-accent font-semibold ring-1 ring-bb-accent/40 ' +
                          'shadow-[inset_0_-3px_0_0_var(--bb-accent-bright)]'
                        : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated',
                  )}
                >
                  <Icon className="mr-2 h-4 w-4" />
                  {tab.label}
                  {tab.key === 'progress' && activeBatchId && progress && !isTerminal && (
                    <span
                      className="ml-2 inline-flex h-2 w-2 animate-pulse rounded-full bg-bb-accent"
                      data-testid="batch-tab-progress-pulse"
                    />
                  )}
                </button>
              );
            })}
          </div>

          {/* ── Submit tab ─────────────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="batch-tabpanel-submit"
            aria-labelledby="batch-tab-submit"
            data-testid="batch-panel-submit"
            className={cn('space-y-4 pt-2', activeTab !== 'submit' && 'hidden')}
          >
            <TickerInput value={tickerText} onChange={setTickerText} />
            <BatchConfigForm value={config} onChange={setConfig} />
            <StartButton
              onClick={handleSubmit}
              disabled={createMutation.isPending}
              isSubmitting={createMutation.isPending}
              totalJobs={clean.length}
            />
            {submitError && (
              <Alert variant="destructive" data-testid="batch-submit-error">
                <AlertTitle>提交失败</AlertTitle>
                <AlertDescription>{submitError}</AlertDescription>
              </Alert>
            )}
            {submitInfo && (
              <Alert data-testid="batch-submit-info">
                <AlertTitle>已提交</AlertTitle>
                <AlertDescription>{submitInfo}</AlertDescription>
              </Alert>
            )}
            <p className="text-xs text-text-tertiary">
              任务在 <code>backend.core.job_queue</code> ThreadPoolExecutor 跑,
              默认 5 worker。LLM 配置留空 → 走 ⚙️ 设置 / env 兜底。
              与 Streamlit <code>web/components/batch_panel.py</code> 1:1。
            </p>
          </div>

          {/* ── Progress tab ───────────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="batch-tabpanel-progress"
            aria-labelledby="batch-tab-progress"
            data-testid="batch-panel-progress"
            className={cn('space-y-4 pt-2', activeTab !== 'progress' && 'hidden')}
          >
            {!activeBatchId && (
              <div
                data-testid="batch-progress-empty-state"
                className="rounded-lg border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
              >
                还没有进行中的 batch。先到「新建批量任务」提交一个。
              </div>
            )}
            {activeBatchId && (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border-1 bg-bg-elevated/40 px-4 py-3">
                  <div className="space-y-1 text-sm" data-testid="batch-progress-meta">
                    <div>
                      Batch ID:{' '}
                      <code className="font-mono text-text-primary">
                        {activeBatchId}
                      </code>
                    </div>
                    <div className="text-text-secondary">
                      状态 <span className="font-mono">{progress?.batch_status ?? '加载中…'}</span>
                      {' · '}
                      完成 <strong data-testid="batch-progress-finished">{finishedCount}</strong>
                      {' / '}
                      {total}
                      {' · '}
                      失败 <strong data-testid="batch-progress-error">{errorCount}</strong>
                    </div>
                  </div>
                  {!isTerminal && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={cancelMutation.isPending}
                      onClick={() => cancelMutation.mutate(activeBatchId)}
                      data-testid="batch-cancel"
                    >
                      {cancelMutation.isPending ? '取消中…' : '⊘ 取消 batch'}
                    </Button>
                  )}
                </div>

                <div data-testid="batch-progress-bar-wrap">
                  <div className="h-2 w-full overflow-hidden rounded-full bg-bg-elevated">
                    <div
                      className="h-full rounded-full bg-bb-accent transition-all duration-500"
                      style={{ width: `${progressPct}%` }}
                      data-testid="batch-progress-bar"
                    />
                  </div>
                  <div className="mt-1 text-right text-xs text-text-tertiary">
                    {progressPct}%
                  </div>
                </div>

                <BatchProgress
                  jobs={progress?.jobs ?? []}
                  onRetry={handleRetry}
                  onViewReport={handleViewReport}
                  isRetrying={(jobId) => retiringJobIds.has(jobId)}
                />

                {isTerminal && summaryQuery.data && (
                  <BatchSummary
                    summary={summaryQuery.data}
                    onDownloadCsv={handleDownloadCsv}
                  />
                )}
                {isTerminal && !summaryQuery.data && summaryQuery.isLoading && (
                  <div
                    data-testid="batch-summary-loading"
                    className="rounded-md border border-border-1 bg-bg-elevated/40 p-4 text-sm text-text-tertiary"
                  >
                    正在加载汇总…
                  </div>
                )}
              </>
            )}
          </div>

          {/* ── History tab ────────────────────────────────────────────── */}
          <div
            role="tabpanel"
            id="batch-tabpanel-history"
            aria-labelledby="batch-tab-history"
            data-testid="batch-panel-history"
            className={cn('space-y-4 pt-2', activeTab !== 'history' && 'hidden')}
          >
            <BatchList
              batches={listQuery.data?.batches ?? []}
              activeBatchId={activeBatchId}
              onSelect={(id) => {
                setActiveBatchId(id);
                setActiveTab('progress');
              }}
              isLoading={listQuery.isLoading}
            />
            <p className="text-xs text-text-tertiary">
              最近 20 个 batch · 与 Streamlit <code>web/components/batch_panel.py</code>{' '}
              共享 <code>backend.core.job_queue.JobQueue</code> 单例。
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export default BatchPage;
