/**
 * AnalysisReport — render the 7 analyst reports + final decision from a
 * full_states_log_*.json blob.
 *
 * Mirrors web/components/analyze_panel.py::render_report_block. The backend
 * normalises all report keys to ``stage_reports`` (a dict[stage_id, markdown])
 * for live progress, but the full report carries the same content nested under
 * the canonical ``report_key`` names (market_report / sentiment_report / etc.).
 * We render whichever shape the API returns.
 */
import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AnalyzeReport } from '@/api/analyze';

interface AnalysisReportProps {
  report: AnalyzeReport | null;
  isLoading?: boolean;
  error?: string | null;
}

interface TraderReportDef {
  key: string;
  title: string;
  icon: string;
}

const TRADER_REPORTS: TraderReportDef[] = [
  { key: 'market_report', title: '技术分析', icon: '📊' },
  { key: 'sentiment_report', title: '情绪分析', icon: '💬' },
  { key: 'news_report', title: '新闻舆情', icon: '📰' },
  { key: 'fundamentals_report', title: '基本面', icon: '📋' },
  { key: 'policy_report', title: '政策分析', icon: '🏛️' },
  { key: 'hot_money_report', title: '游资追踪', icon: '🔥' },
  { key: 'lockup_report', title: '解禁监控', icon: '🔒' },
];

function extractMarkdown(report: Record<string, unknown> | null | undefined): Record<string, string> {
  if (!report || typeof report !== 'object') return {};
  const out: Record<string, string> = {};
  // 1) flat stage_reports dict (from ProgressResponse)
  const stageReports = report.stage_reports;
  if (stageReports && typeof stageReports === 'object') {
    for (const [k, v] of Object.entries(stageReports as Record<string, unknown>)) {
      if (typeof v === 'string' && v.trim()) out[k] = v;
    }
  }
  // 2) full_states_log_*.json shape: reports nested under canonical keys.
  //    Walk one level deep to find the first string per key.
  for (const def of TRADER_REPORTS) {
    if (out[def.key]) continue;
    const top = report[def.key];
    if (typeof top === 'string' && top.trim()) {
      out[def.key] = top;
    } else if (top && typeof top === 'object') {
      // drill one level
      for (const v of Object.values(top as Record<string, unknown>)) {
        if (typeof v === 'string' && v.trim()) {
          out[def.key] = v;
          break;
        }
      }
    }
  }
  return out;
}

function extractSignal(report: Record<string, unknown> | null | undefined): string | null {
  if (!report || typeof report !== 'object') return null;
  const direct = report.final_signal ?? report.signal;
  if (typeof direct === 'string') return direct;
  const decision = report.final_trade_decision;
  if (decision && typeof decision === 'object') {
    const inner = (decision as Record<string, unknown>).signal;
    if (typeof inner === 'string') return inner;
  }
  return null;
}

export function AnalysisReport({ report, isLoading, error }: AnalysisReportProps) {
  if (isLoading) {
    return (
      <div className="text-sm text-text-secondary" data-testid="analysis-report-loading">
        加载报告中…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="analysis-report-error"
      >
        加载分析失败: {error}
      </div>
    );
  }
  if (!report) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="analysis-report-empty"
      >
        暂无报告。完成一次分析后, 报告会按 7 位分析师逐张卡片渲染。
      </div>
    );
  }

  const reportBody = (report.report ?? {}) as Record<string, unknown>;
  const stageMarkdown = extractMarkdown(reportBody);
  const signal = extractSignal(reportBody);

  return (
    <div className="space-y-4" data-testid="analysis-report">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm">
            <span className="font-mono font-semibold">{report.ticker}</span>{' '}
            <span className="text-text-tertiary">· {report.trade_date}</span>
          </div>
          <div className="text-xs text-text-tertiary font-mono">{report.analysis_id}</div>
        </div>
        {signal && (
          <span
            className="rounded bg-bb-accent/20 px-2 py-1 font-mono text-xs text-bb-accent-bright"
            data-testid="analysis-report-signal"
          >
            信号: {signal}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {TRADER_REPORTS.map((def) => {
          const body = stageMarkdown[def.key];
          return (
            <Card key={def.key} data-testid={`analysis-report-card-${def.key}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <span className="text-lg leading-none">{def.icon}</span>
                  {def.title}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {body ? (
                  <pre
                    className="whitespace-pre-wrap break-words text-xs leading-relaxed text-text-primary font-mono"
                    data-testid={`analysis-report-body-${def.key}`}
                  >
                    {body.slice(0, 4000)}
                    {body.length > 4000 ? '\n…' : ''}
                  </pre>
                ) : (
                  <div
                    className="text-xs text-text-tertiary"
                    data-testid={`analysis-report-empty-${def.key}`}
                  >
                    (本报告无内容)
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="text-xs text-text-tertiary">
        报告源: <code>{report.results_path}</code> · 7 analyst + 1 最终决策 (trader_investment_plan)
      </p>
    </div>
  );
}

export default AnalysisReport;