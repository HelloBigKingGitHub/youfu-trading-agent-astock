/**
 * AnalysisWorkspace — render the 7 analyst intermediate reports from a
 * ProgressResponse's ``stage_reports`` dict.
 *
 * Mirrors the working-tabs layout in web/components/analyze_panel.py that
 * shows each analyst's markdown as it lands. While the analysis is running
 * the parent polls /api/analyze/{id} and re-renders this component; when the
 * run finishes the user can switch to the report tab to see the consolidated
 * 7-card layout.
 */
import * as React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Loader2 } from 'lucide-react';

interface AnalysisWorkspaceProps {
  stageReports: Record<string, string> | null | undefined;
  currentStage?: string | null;
  isLoading?: boolean;
  error?: string | null;
}

interface WorkspaceCard {
  id: string;
  title: string;
  icon: string;
}

const WORKSPACE_CARDS: WorkspaceCard[] = [
  { id: 'market_report', title: '市场分析', icon: '📊' },
  { id: 'sentiment_report', title: '情绪分析', icon: '💬' },
  { id: 'news_report', title: '新闻舆情', icon: '📰' },
  { id: 'fundamentals_report', title: '基本面', icon: '📋' },
  { id: 'policy_report', title: '政策分析', icon: '🏛️' },
  { id: 'hot_money_report', title: '游资追踪', icon: '🔥' },
  { id: 'lockup_report', title: '解禁监控', icon: '🔒' },
];

export function AnalysisWorkspace({
  stageReports, currentStage, isLoading, error,
}: AnalysisWorkspaceProps) {
  if (isLoading) {
    return (
      <div className="text-sm text-text-secondary" data-testid="analysis-workspace-loading">
        <Loader2 className="inline-block h-4 w-4 animate-spin mr-2" />
        加载分析师工作区…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="analysis-workspace-error"
      >
        加载工作区失败: {error}
      </div>
    );
  }
  const reports = stageReports ?? {};
  const hasAny = WORKSPACE_CARDS.some((c) => Boolean(reports[c.id]));

  if (!hasAny) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="analysis-workspace-empty"
      >
        7 位分析师 (市场/情绪/新闻/基本面/政策/游资/解禁) 的中间结果会在这里按阶段陆续出现 ·
        提交一次分析后, 每完成一个 stage 就会渲染对应卡片
      </div>
    );
  }

  return (
    <div
      className="grid grid-cols-1 gap-3 lg:grid-cols-2"
      data-testid="analysis-workspace"
    >
      {WORKSPACE_CARDS.map((c) => {
        const body = reports[c.id];
        const isCurrent = currentStage && currentStage.startsWith(c.id.replace('_report', ''));
        return (
          <Card
            key={c.id}
            data-testid={`analysis-workspace-card-${c.id}`}
            className={isCurrent ? 'ring-1 ring-bb-accent/60' : undefined}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <span className="text-lg leading-none">{c.icon}</span>
                {c.title}
                {isCurrent && <Loader2 className="h-3 w-3 animate-spin text-bb-accent-bright" />}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {body ? (
                <pre
                  className="whitespace-pre-wrap break-words text-xs leading-relaxed text-text-primary font-mono"
                  data-testid={`analysis-workspace-body-${c.id}`}
                >
                  {body.slice(0, 4000)}
                  {body.length > 4000 ? '\n…' : ''}
                </pre>
              ) : (
                <div
                  className="text-xs text-text-tertiary"
                  data-testid={`analysis-workspace-pending-${c.id}`}
                >
                  (等待该阶段完成)
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

export default AnalysisWorkspace;