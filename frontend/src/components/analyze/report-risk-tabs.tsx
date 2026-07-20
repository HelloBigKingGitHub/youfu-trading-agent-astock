/**
 * ReportRiskTabs — render the risk-debate dictionary as four persona tabs
 * (激进 / 保守 / 中性 / 风控决策).
 *
 * P2.29 — replaces the old JSON-as-text rendering of the risk debate dict.
 *
 * Outer wrapper preserves the existing
 * ``analysis-report-card-risk_debate_state`` testid for E2E parity.
 */
import * as React from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { ReportMarkdown } from './report-markdown';

interface RiskDebateState {
  aggressive_history?: string;
  conservative_history?: string;
  neutral_history?: string;
  judge_decision?: string;
}

interface ReportRiskTabsProps {
  risk: RiskDebateState;
  cardTestId?: string;
}

export function ReportRiskTabs({ risk, cardTestId }: ReportRiskTabsProps) {
  const aggressive = risk.aggressive_history ?? '';
  const conservative = risk.conservative_history ?? '';
  const neutral = risk.neutral_history ?? '';
  const judge = risk.judge_decision ?? '';

  return (
    <div data-testid={cardTestId ?? 'analysis-report-card-risk_debate_state'}>
      <Tabs defaultValue="aggressive" className="w-full">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-text-primary">
          <span aria-hidden>🛡️</span>
          风控评估
        </div>
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="aggressive" data-testid="report-risk-aggressive">
            激进
          </TabsTrigger>
          <TabsTrigger value="conservative" data-testid="report-risk-conservative">
            保守
          </TabsTrigger>
          <TabsTrigger value="neutral" data-testid="report-risk-neutral">
            中性
          </TabsTrigger>
          <TabsTrigger value="judge" data-testid="report-risk-judge">
            风控决策
          </TabsTrigger>
        </TabsList>
        <TabsContent value="aggressive">
          <ReportMarkdown source={aggressive || '无数据'} />
        </TabsContent>
        <TabsContent value="conservative">
          <ReportMarkdown source={conservative || '无数据'} />
        </TabsContent>
        <TabsContent value="neutral">
          <ReportMarkdown source={neutral || '无数据'} />
        </TabsContent>
        <TabsContent value="judge">
          <ReportMarkdown source={judge || '无数据'} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default ReportRiskTabs;
