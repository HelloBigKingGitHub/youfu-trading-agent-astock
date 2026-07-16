import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import {
  Badge,
  signalLabel,
  signalVariant,
  statusLabel,
  statusVariant,
} from '@/components/ui/badge';
import { getHistory, type HistoryDetail as HistoryDetailData } from '@/api/history';

// HistoryDetail — shadcn-Dialog-style modal showing the full entry. Loads
// the full detail via GET /api/history/{id} (not the slim list item) so the
// user sees stage_reports / started_at / finished_at / results_path — same
// payload streamlit gets when it does entry = json.loads(file).
//
// The "完整报告" link opens /api/history/{id}/report in a new tab — the same
// raw full_states_log_*.json streamlit reads via Path(results_path).read_text().

interface HistoryDetailModalProps {
  analysisId: string | null;
  open: boolean;
  onClose: () => void;
}

function fmtTs(ts: number | null): string {
  if (!ts) return '-';
  const date = new Date(ts * 1000);
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function HistoryDetailModal({ analysisId, open, onClose }: HistoryDetailModalProps) {
  const { data, isLoading, error } = useQuery<HistoryDetailData>({
    queryKey: ['history-detail', analysisId],
    queryFn: () => getHistory(analysisId as string),
    enabled: Boolean(analysisId) && open,
    staleTime: 0,
    retry: 0,
  });

  const apiBase = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';
  const reportUrl = analysisId ? `${apiBase}/api/history/${encodeURIComponent(analysisId)}/report` : null;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={data ? `📊 ${data.ticker} · ${data.trade_date}` : '历史详情'}
      description={analysisId ? `analysis_id = ${analysisId}` : undefined}
      testId="history-detail-dialog"
      footer={
        reportUrl ? (
          <>
            <Button type="button" variant="outline" onClick={onClose} data-testid="history-detail-close">
              关闭
            </Button>
            <a href={reportUrl} target="_blank" rel="noreferrer">
              <Button type="button" variant="default" data-testid="history-detail-report-link">
                <ExternalLink className="h-4 w-4" />
                完整报告 JSON
              </Button>
            </a>
          </>
        ) : (
          <Button type="button" variant="outline" onClick={onClose} data-testid="history-detail-close">
            关闭
          </Button>
        )
      }
    >
      {!analysisId ? null : isLoading ? (
        <div className="flex items-center gap-2 text-text-secondary" data-testid="history-detail-loading">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载详情中…
        </div>
      ) : error ? (
        <div className="rounded-md border border-bb-up/40 bg-bb-up/10 p-4 text-bb-up text-sm" data-testid="history-detail-error">
          {(error as Error).message}
        </div>
      ) : data ? (
        <div className="space-y-4 text-sm">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="分析 ID" value={data.analysis_id} mono />
            <Field label="状态" value={
              <Badge variant={statusVariant(data.status)}>
                {statusLabel(data.status)}
              </Badge>
            } />
            <Field label="股票代码" value={data.ticker} mono />
            <Field label="信号" value={
              <Badge variant={signalVariant(data.signal)}>
                {signalLabel(data.signal)}
              </Badge>
            } />
            <Field label="交易日期" value={data.trade_date} />
            <Field
              label="耗时 (s)"
              value={typeof data.elapsed === 'number' ? data.elapsed.toFixed(2) : '-'}
              mono
            />
            <Field label="创建时间" value={fmtTs(typeof data.created_at === 'string' ? Number(data.created_at) : (data.created_at as unknown as number | null))} />
            <Field label="开始时间" value={fmtTs(data.started_at ?? null)} />
            <Field label="完成时间" value={fmtTs(data.finished_at ?? null)} />
          </div>

          <Section title="已完成阶段">
            {data.completed_stages?.length ? (
              <div className="flex flex-wrap gap-1.5">
                {data.completed_stages.map((s) => (
                  <span
                    key={s}
                    className="rounded bg-bg-elevated px-2 py-0.5 font-mono text-xs text-text-secondary"
                  >
                    {s}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-text-tertiary text-sm">-</span>
            )}
          </Section>

          {data.error && (
            <Section title="错误信息">
              <pre className="whitespace-pre-wrap break-words rounded-md bg-bb-up/5 p-3 font-mono text-xs text-bb-up">
                {data.error}
              </pre>
            </Section>
          )}

          <Section title="原始报告路径">
            <code className="block break-all rounded-md bg-bg-elevated px-3 py-2 font-mono text-xs text-text-secondary">
              {data.results_path || '(results_path 为空，使用 ticker/date legacy 兜底)'}
            </code>
          </Section>

          {data.stage_reports && Object.keys(data.stage_reports).length > 0 && (
            <Section title={`阶段报告片段 (${Object.keys(data.stage_reports).length})`}>
              <details className="rounded-md border border-border-1 bg-bg-elevated p-3">
                <summary className="cursor-pointer text-text-primary text-sm">
                  查看所有 stage_reports
                </summary>
                <div className="mt-3 space-y-2">
                  {Object.entries(data.stage_reports).map(([stage, snip]) => (
                    <div key={stage} className="text-xs">
                      <div className="font-mono text-text-secondary">{stage}</div>
                      <div className="mt-1 whitespace-pre-wrap break-words text-text-primary">
                        {snip}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            </Section>
          )}
        </div>
      ) : null}
    </Dialog>
  );
}

function Field({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs uppercase tracking-wider text-text-tertiary">{label}</span>
      <span className={mono ? 'font-mono text-sm text-text-primary' : 'text-sm text-text-primary'}>{value}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-text-tertiary mb-1.5">{title}</div>
      {children}
    </div>
  );
}
