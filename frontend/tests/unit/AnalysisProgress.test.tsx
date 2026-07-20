/**
 * P2.27 hotfix — AnalysisProgress must render the crashed stage as
 * "errored" (red, AlertCircle icon) when status='error', NOT as
 * "running" (blue, Loader2 spinner). Without this guarantee the user
 * sees the contradiction "质量门禁 ● 蓝色 (running)" alongside the
 * error banner — exactly what the user reported as "progress page
 * stuck after timeout fires" after the 600s/1800s hard timeout fires.
 *
 * We render AnalysisProgress in isolation (no router/query mocks needed)
 * so the test stays stable as the parent page wiring evolves.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AnalysisProgress } from '@/components/analyze/analysis-progress';
import type { ProgressResponse } from '@/api/analyze';

const baseProgress: ProgressResponse = {
  status: 'running',
  ticker: '600595',
  trade_date: '2026-07-17',
  current_stage: 'quality_gate',
  completed_stages: [
    'market', 'social', 'news', 'fundamentals',
    'policy', 'hot_money', 'lockup',
  ],
  stage_reports: {
    market_report: '# 技术分析\nMock body',
    sentiment_report: '# 情绪分析\nMock body',
  },
  stats: { llm_calls: 23, tool_calls: 37, tokens_in: 182248, tokens_out: 29913 },
  elapsed: 791.5,
  signal: null,
  error: null,
};

describe('AnalysisProgress — P2.27 errored stage visual contract', () => {
  it('shows the error banner and renders quality_gate as errored (not running)', () => {
    render(
      <AnalysisProgress
        progress={{
          ...baseProgress,
          status: 'error',
          error: '分析超过 1800s 硬上限, 强制终止 (P2.27 hotfix, 最后阶段: quality_gate)',
        }}
        isPolling={false}
      />,
    );

    // 1. Error banner with the failure reason.
    const banner = screen.getByTestId('analysis-progress-error');
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain('分析已终止');
    expect(banner.textContent).toContain('分析超过 1800s 硬上限');

    // 2. The 7 stages that finished before quality_gate must be "done".
    for (const id of [
      'market', 'social', 'news', 'fundamentals',
      'policy', 'hot_money', 'lockup',
    ]) {
      const card = screen.getByTestId(`analysis-stage-${id}`);
      expect(card.dataset.status).toBe('done');
    }

    // 3. The crashed stage MUST be "errored" — NOT "running".
    const crashed = screen.getByTestId('analysis-stage-quality_gate');
    expect(crashed.dataset.status).toBe('errored');

    // 4. No card may render as "running" — the bar must settle.
    const allStages = document.querySelectorAll('[data-testid^="analysis-stage-"]');
    for (const el of Array.from(allStages)) {
      expect(el.getAttribute('data-status')).not.toBe('running');
    }

    // 5. Stages after the crash remain "pending" (only the crashed stage
    //    gets the errored badge).
    for (const id of ['debate', 'risk', 'trader', 'pm']) {
      expect(screen.getByTestId(`analysis-stage-${id}`).dataset.status).toBe('pending');
    }
  });

  it('still shows the running spinner for in-flight analyses (no regression)', () => {
    render(<AnalysisProgress progress={baseProgress} isPolling={true} />);

    // quality_gate is the current stage in MOCK_PROGRESS.
    const qg = screen.getByTestId('analysis-stage-quality_gate');
    expect(qg.dataset.status).toBe('running');

    // No error banner for in-flight runs.
    expect(screen.queryByTestId('analysis-progress-error')).not.toBeInTheDocument();
  });

  it('shows the completion banner and no running spinner for ok analyses', () => {
    render(
      <AnalysisProgress
        progress={{
          ...baseProgress,
          status: 'ok',
          current_stage: null,
          signal: 'BUY',
        }}
        isPolling={false}
      />,
    );

    // Done banner shows.
    expect(screen.getByTestId('analysis-progress-done')).toBeInTheDocument();

    // All 7 finished stages must be "done".
    for (const id of [
      'market', 'social', 'news', 'fundamentals',
      'policy', 'hot_money', 'lockup',
    ]) {
      expect(screen.getByTestId(`analysis-stage-${id}`).dataset.status).toBe('done');
    }

    // No card runs as "running".
    const allStages = document.querySelectorAll('[data-testid^="analysis-stage-"]');
    for (const el of Array.from(allStages)) {
      expect(el.getAttribute('data-status')).not.toBe('running');
    }
  });
});