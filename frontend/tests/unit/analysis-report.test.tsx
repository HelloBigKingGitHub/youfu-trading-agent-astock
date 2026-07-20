/**
 * Vitest unit tests for AnalysisReport (P2.29).
 *
 * Coverage:
 *   * All 12 analyst report cards render with their locked-in testids
 *     (matches ``tests/e2e/report-tab-p228.spec.ts`` selectors).
 *   * Hero block reflects the BUY signal coloured pill.
 *   * Null signal renders an em-dash fallback without crashing.
 *   * 📥 Markdown download link href targets /api/analyze/{id}/export?format=md.
 *   * 📄 PDF button is disabled and labeled "PDF 不可用" when ``pdf_available``
 *     is False.
 *   * When ``pdf_available`` is True the PDF button becomes an <a download>.
 *   * Markdown inside an analyst card is actually rendered (not <pre>):
 *     a ``#`` heading produces an ``<h1>`` element.
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AnalysisReport } from '@/components/analyze/analysis-report';
import type { AnalyzeReport } from '@/api/analyze';

const BASE_REPORT: AnalyzeReport = {
  analysis_id: '600595_2026-07-18_test',
  ticker: '600595',
  trade_date: '2026-07-18',
  results_path: '/tmp/full_states_log_2026-07-18.json',
  pdf_available: true,
  report: {
    market_report: '# 技术分析\nK 线多头排列',
    sentiment_report: '# 情绪\n看多占优',
    news_report: '# 新闻\n公司公告利好',
    fundamentals_report: '# 基本面\nROE 15%',
    policy_report: '# 政策\n行业扶持',
    hot_money_report: '# 游资\n主力净流入',
    lockup_report: '# 解禁\n未来 30 天无解禁',
    quality_gate_report: '# 质量门禁\n数据完整',
    investment_debate_state: {
      bull_history: '多方观点：业绩稳定',
      bear_history: '空方观点：估值偏高',
      judge_decision: '研究经理：买入',
    },
    risk_debate_state: {
      aggressive_history: '激进：满仓',
      conservative_history: '保守：半仓',
      neutral_history: '中性：六成',
      judge_decision: '风控决策：六成仓',
    },
    trader_investment_plan: '# 交易员\n执行买入 5%',
    final_trade_decision: 'BUY',
  },
};

describe('AnalysisReport — P2.29 layout', () => {
  it('renders 12 stage cards with locked testids', () => {
    render(<AnalysisReport report={BASE_REPORT} />);

    const expected = [
      'market_report',
      'sentiment_report',
      'news_report',
      'fundamentals_report',
      'policy_report',
      'hot_money_report',
      'lockup_report',
      'quality_gate_report',
      'investment_debate_state',
      'risk_debate_state',
      'trader_investment_plan',
      'final_trade_decision',
    ];
    for (const key of expected) {
      expect(
        screen.getByTestId(`analysis-report-card-${key}`),
        `missing analysis-report-card-${key}`,
      ).toBeInTheDocument();
    }
  });

  it('renders the hero block with BUY signal value', () => {
    render(<AnalysisReport report={BASE_REPORT} />);

    const hero = screen.getByTestId('analysis-report-hero');
    expect(hero).toBeInTheDocument();
    expect(hero.dataset.signal).toBe('BUY');
    expect(screen.getByTestId('analysis-report-signal-value')).toHaveTextContent('BUY');
  });

  it('falls back to em-dash when signal is null', () => {
    const noSignal: AnalyzeReport = {
      ...BASE_REPORT,
      report: {
        ...BASE_REPORT.report,
        final_trade_decision: { foo: 'bar' }, // no signal key
      },
    };
    render(<AnalysisReport report={noSignal} />);

    expect(screen.getByTestId('analysis-report-signal-value')).toHaveTextContent('—');
  });

  it('links the Markdown download to the /export?format=md endpoint', () => {
    render(<AnalysisReport report={BASE_REPORT} />);

    const mdLink = screen.getByTestId('analysis-report-download-md');
    expect(mdLink).toBeInTheDocument();
    expect(mdLink.tagName).toBe('A');
    expect((mdLink as HTMLAnchorElement).href).toContain(
      '/api/analyze/600595_2026-07-18_test/export?format=md',
    );
    expect((mdLink as HTMLAnchorElement).download).toBe(
      'TradingAgents-Astock_600595_2026-07-18.md',
    );
  });

  it('renders the PDF button as disabled when pdf_available=false', () => {
    const disabled: AnalyzeReport = { ...BASE_REPORT, pdf_available: false };
    render(<AnalysisReport report={disabled} />);

    const pdfDisabled = screen.getByTestId('analysis-report-download-pdf-disabled');
    expect(pdfDisabled).toBeInTheDocument();
    expect((pdfDisabled as HTMLButtonElement).disabled).toBe(true);
    // No enabled <a> download link should be present when PDF is unavailable.
    expect(screen.queryByTestId('analysis-report-download-pdf')).toBeNull();
  });

  it('renders the PDF button as <a download> when pdf_available=true', () => {
    render(<AnalysisReport report={BASE_REPORT} />);

    const pdfLink = screen.getByTestId('analysis-report-download-pdf');
    expect(pdfLink).toBeInTheDocument();
    expect(pdfLink.tagName).toBe('A');
    expect((pdfLink as HTMLAnchorElement).href).toContain(
      '/api/analyze/600595_2026-07-18_test/export?format=pdf',
    );
    expect((pdfLink as HTMLAnchorElement).download).toBe(
      'TradingAgents-Astock_600595_2026-07-18.pdf',
    );
  });

  it('renders the open (defaultValue=market_report) analyst markdown as headings', async () => {
    render(<AnalysisReport report={BASE_REPORT} />);

    // The first analyst accordion item is open by default; verify the
    // rendered <h1> inside it. We pass { hidden: true } because radix
    // marks the (initially closed) sibling panels with the `hidden`
    // attribute and testing-library's getByRole filters those by default.
    const marketCard = await screen.findByTestId('analysis-report-card-market_report');
    const heading = within(marketCard).getByRole('heading', {
      name: '技术分析',
      level: 1,
      hidden: true,
    });
    expect(heading).toBeInTheDocument();
    expect(heading.tagName).toBe('H1');
  });

  it('renders risk-debate tabs with persona triggers', async () => {
    render(<AnalysisReport report={BASE_REPORT} />);

    // Risk tabs render radix triggers; clicking flips the data-state attribute.
    const riskCard = screen.getByTestId('analysis-report-card-risk_debate_state');
    expect(riskCard).toBeInTheDocument();
    expect(within(riskCard).getByTestId('report-risk-aggressive')).toHaveTextContent('激进');
    expect(within(riskCard).getByTestId('report-risk-conservative')).toHaveTextContent('保守');
    expect(within(riskCard).getByTestId('report-risk-neutral')).toHaveTextContent('中性');
    expect(within(riskCard).getByTestId('report-risk-judge')).toHaveTextContent('风控决策');
  });
});
