/**
 * AnalysisReport — render the analyze-page report tab.
 *
 * P2.28 — extended from 7 cards to all 12 pipeline stages. Mirrors the
 * backend stage_map so the report matches what /progress shows.
 *
 * P2.29 — visual overhaul. The P2.28 layout dumped every report body into
 * a `<pre>` tag inside a Card — it was technically all 12 stages but the
 * user called it "ugly and unreadable". This rewrite:
 *
 *   * Big hero block with signal-coloured pill, ticker, trade date, and two
 *     download buttons (📥 Markdown always-on; 📄 PDF fallback to a
 *     disabled grey button when the host has no CJK font).
 *   * 7 analyst sections collapse into a single Radix Accordion so the
 *     report doesn't sprawl across two screens of full-height cards.
 *   * Bull/bear/research-manager debate + aggressive/conservative/neutral/
 *     risk-judge debate each get their own Radix Tabs.
 *   * Markdown rendering via react-markdown + remark-gfm + rehype-sanitize
 *     replaces the raw-text `<pre>` so headings, lists, tables actually
 *     render with hierarchy.
 *
 * The 12 ``analysis-report-card-{key}`` testids the prior implementation
 * locked in (and the E2E suite ``tests/e2e/report-tab-p228.spec.ts``
 * asserts on) are still produced verbatim — each accordion item, tabs
 * block, and standalone card carries one.
 */
import * as React from 'react';
import { Card, CardContent } from '@/components/ui/card';
import {
  Accordion,
  AccordionItem,
  AccordionTrigger,
  AccordionContent,
} from '@/components/ui/accordion';
import type { AnalyzeReport } from '@/api/analyze';
import { ReportHeader } from './report-header';
import { ReportDebateTabs } from './report-debate-tabs';
import { ReportRiskTabs } from './report-risk-tabs';
import { ReportMarkdown } from './report-markdown';

interface AnalysisReportProps {
  report: AnalyzeReport | null;
  isLoading?: boolean;
  error?: string | null;
}

// 12 stages in pipeline order so the report reads top-to-bottom like the
// progress bar. ``extractMarkdown`` maps both the new ``report`` payload
// (full_states_log_*.json shape with canonical keys) and the legacy
// ``stage_reports`` shape (from ProgressResponse) into a uniform string.
const TRADER_REPORTS: { key: string; title: string; icon: string }[] = [
  { key: 'market_report', title: '技术分析', icon: '📊' },
  { key: 'sentiment_report', title: '情绪分析', icon: '💬' },
  { key: 'news_report', title: '新闻舆情', icon: '📰' },
  { key: 'fundamentals_report', title: '基本面', icon: '📋' },
  { key: 'policy_report', title: '政策分析', icon: '🏛️' },
  { key: 'hot_money_report', title: '游资追踪', icon: '🔥' },
  { key: 'lockup_report', title: '解禁监控', icon: '🔒' },
  { key: 'quality_gate_report', title: '质量门禁', icon: '✅' },
  { key: 'investment_debate_state', title: '多空辩论', icon: '⚔️' },
  { key: 'risk_debate_state', title: '风控讨论', icon: '🛡️' },
  { key: 'trader_investment_plan', title: '交易员决策', icon: '💹' },
  { key: 'final_trade_decision', title: '组合经理决策', icon: '👔' },
];

// The seven analyst sections that collapse into the analyst Accordion.
// ``debate / risk / trader / pm / quality_gate`` render as their own
// Card or Tabs block (see layout below) — only these 7 use the Accordion.
const ANALYST_KEYS = new Set([
  'market_report',
  'sentiment_report',
  'news_report',
  'fundamentals_report',
  'policy_report',
  'hot_money_report',
  'lockup_report',
]);

type StringMap = Record<string, string>;

function extractMarkdown(
  report: Record<string, unknown> | null | undefined,
): StringMap {
  if (!report || typeof report !== 'object') return {};
  const out: StringMap = {};

  // 1) flat stage_reports dict (from ProgressResponse)
  const stageReports = report.stage_reports;
  if (stageReports && typeof stageReports === 'object') {
    for (const [k, v] of Object.entries(stageReports as Record<string, unknown>)) {
      if (typeof v === 'string' && v.trim()) out[k] = v;
    }
  }

  // 2) full_states_log_*.json shape: reports nested under canonical keys
  //    — walk the dict and pull out the first string per key, but skip
  //    dict-shaped stages here (rendered separately).
  for (const def of TRADER_REPORTS) {
    if (out[def.key]) continue;
    const top = report[def.key];
    if (def.key === 'investment_debate_state' || def.key === 'risk_debate_state') {
      // Dict-shaped — handled by report-debate-tabs / report-risk-tabs.
      // We still produce a placeholder so the empty-state contract works.
      if (top && typeof top === 'object') out[def.key] = '__HAS_DICT__';
      continue;
    }
    if (typeof top === 'string' && top.trim()) {
      out[def.key] = top;
    } else if (top && typeof top === 'object') {
      // drill one level for any nested string fields
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

function extractDebate(report: Record<string, unknown>): Record<string, unknown> | null {
  const d = report.investment_debate_state;
  return d && typeof d === 'object' ? (d as Record<string, unknown>) : null;
}
function extractRisk(report: Record<string, unknown>): Record<string, unknown> | null {
  const d = report.risk_debate_state;
  return d && typeof d === 'object' ? (d as Record<string, unknown>) : null;
}

function pickStr(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

export function AnalysisReport({ report, isLoading, error }: AnalysisReportProps) {
  if (isLoading) {
    return (
      <div
        className="text-sm text-text-secondary"
        data-testid="analysis-report-loading"
      >
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
        暂无报告。完成一次分析后, 报告会按 12 个阶段逐张卡片渲染。
      </div>
    );
  }

  const reportBody = (report.report ?? {}) as Record<string, unknown>;
  const stageMarkdown = extractMarkdown(reportBody);
  const debate = extractDebate(reportBody);
  const risk = extractRisk(reportBody);

  // ── Card / Tabs blocks (one per non-analyst stage) ───────────────────────
  const standalone: { def: (typeof TRADER_REPORTS)[number]; body: string }[] = [];
  for (const def of TRADER_REPORTS) {
    if (ANALYST_KEYS.has(def.key)) continue; // handled by Accordion below
    if (def.key === 'investment_debate_state' || def.key === 'risk_debate_state') continue;
    const body = stageMarkdown[def.key] ?? '';
    standalone.push({ def, body });
  }
  const analystDefs = TRADER_REPORTS.filter((d) => ANALYST_KEYS.has(d.key));

  return (
    <div className="space-y-5" data-testid="analysis-report">
      <ReportHeader report={report} pdfAvailable={report.pdf_available} />

      {/* Analyst Accordion: opens the first analyst by default so the user
          sees one fully-rendered card on first load (the rest stay collapsed
          to avoid a scroll-wall). Each AccordionItem carries the locked-in
          card testid so existing E2E selectors still match. */}
      <section data-testid="analysis-report-analysts">
        <Accordion
          type="multiple"
          defaultValue={['market_report']}
          className="w-full"
        >
          {analystDefs.map((def) => {
            const body = stageMarkdown[def.key] ?? '';
            return (
              <AccordionItem
                key={def.key}
                value={def.key}
                data-testid={`analysis-report-card-${def.key}`}
              >
                <AccordionTrigger>
                  <span className="flex items-center gap-2">
                    <span aria-hidden className="text-base leading-none">{def.icon}</span>
                    <span>{def.title}</span>
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <ReportMarkdown source={body} />
                </AccordionContent>
              </AccordionItem>
            );
          })}
        </Accordion>
      </section>

      {/* Debate & Risk Tabs: dict-shape payloads rendered as multi-tab blocks.
          Cards keep the locked testids; the TabsList/TabsContent blocks have
          their own finer-grained testids for the new unit tests. */}
      {debate && (
        <ReportDebateTabs
          debate={{
            bull_history: pickStr(debate.bull_history),
            bear_history: pickStr(debate.bear_history),
            judge_decision: pickStr(debate.judge_decision),
          }}
        />
      )}
      {risk && (
        <ReportRiskTabs
          risk={{
            aggressive_history: pickStr(risk.aggressive_history),
            conservative_history: pickStr(risk.conservative_history),
            neutral_history: pickStr(risk.neutral_history),
            judge_decision: pickStr(risk.judge_decision),
          }}
        />
      )}

      {/* Standalone cards: quality gate + trader + PM decision. */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {standalone.map(({ def, body }) => (
          <Card key={def.key} data-testid={`analysis-report-card-${def.key}`}>
            <CardContent className="space-y-2 p-4">
              <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                <span aria-hidden className="text-lg leading-none">{def.icon}</span>
                <span>{def.title}</span>
              </div>
              <ReportMarkdown source={body} />
            </CardContent>
          </Card>
        ))}
      </div>

      <p className="text-xs text-text-tertiary">
        报告源: <code className="font-mono">{report.results_path}</code> · 7 分析师 +
        1 质量门禁 + 1 多空辩论 + 1 风控评估 + 1 交易员决策 + 1 组合经理决策
      </p>
    </div>
  );
}

export default AnalysisReport;
