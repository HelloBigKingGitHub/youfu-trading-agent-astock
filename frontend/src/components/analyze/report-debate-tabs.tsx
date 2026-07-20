/**
 * ReportDebateTabs — render the bull / bear / judge-debate sections of a
 * completed investment-debate-state payload as 3 tabs.
 *
 * P2.29 — replaces the old full-text <pre> render for the entire debate
 * dictionary (which dumped the JSON of the dict into a card). The three
 * states are now first-class tabs: 多方 / 空方 / 研究经理.
 *
 * Outer wrapper preserves the existing ``analysis-report-card-investment_debate_state``
 * testid so the E2E suite (`tests/e2e/report-tab-p228.spec.ts`) continues
 * to find all 12 cards.
 */
import * as React from 'react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { ReportMarkdown } from './report-markdown';

interface DebateState {
  bull_history?: string;
  bear_history?: string;
  judge_decision?: string;
}

interface ReportDebateTabsProps {
  debate: DebateState;
  /** Required so the test ids stay stable even when the debate dict is null. */
  cardTestId?: string;
}

export function ReportDebateTabs({ debate, cardTestId }: ReportDebateTabsProps) {
  const bull = debate.bull_history ?? '';
  const bear = debate.bear_history ?? '';
  const judge = debate.judge_decision ?? '';

  return (
    <div data-testid={cardTestId ?? 'analysis-report-card-investment_debate_state'}>
      <Tabs defaultValue="bull" className="w-full">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-text-primary">
          <span aria-hidden>⚔️</span>
          多空辩论
        </div>
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="bull" data-testid="report-debate-bull">
            多方
          </TabsTrigger>
          <TabsTrigger value="bear" data-testid="report-debate-bear">
            空方
          </TabsTrigger>
          <TabsTrigger value="judge" data-testid="report-debate-judge">
            研究经理
          </TabsTrigger>
        </TabsList>
        <TabsContent value="bull" data-testid="report-debate-content-bull">
          <ReportMarkdown source={bull || '无数据'} />
        </TabsContent>
        <TabsContent value="bear" data-testid="report-debate-content-bear">
          <ReportMarkdown source={bear || '无数据'} />
        </TabsContent>
        <TabsContent value="judge" data-testid="report-debate-content-judge">
          <ReportMarkdown source={judge || '无数据'} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default ReportDebateTabs;
