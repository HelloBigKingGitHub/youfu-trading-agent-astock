import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { BarChart3, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  DEFAULT_TOP_N,
  getConcepts,
  getDigest,
  getHeatmap,
  getLimitUp,
  getTopStocks,
} from '@/api/sector';
import { Heatmap } from '@/components/sector/heatmap';
import { TopStocksTable } from '@/components/sector/top-stocks-table';
import { ConceptsList } from '@/components/sector/concepts-list';
import { LimitUpTable } from '@/components/sector/limit-up-table';
import { DigestViewer } from '@/components/sector/digest-viewer';

// SectorPage — mirrors `web/components/sector_panel.py::render_sector_panel()`.
//
// Five tabs driven by 4 GET endpoints (heatmap and concepts share the same
// backend digest fetch, so they're bundled into one query key via getConcepts):
//   1. 热力图    → /api/sector/heatmap
//   2. 选股热度  → /api/sector/top_stocks
//   3. 概念板块  → /api/sector/concepts
//   4. 涨停归因  → /api/sector/limit_up
//   5. 4 段式报告 → /api/sector/digest
//
// Same React Query + 5-tab pattern as LogsPage; all 4 queries run in parallel
// so the first paint shows whichever finishes first.

type TabKey = 'heatmap' | 'top_stocks' | 'concepts' | 'limit_up' | 'digest';

interface TabDef {
  key: TabKey;
  label: string;
  testid: string;
}

const TABS: TabDef[] = [
  { key: 'heatmap', label: '热力图', testid: 'sector-tab-heatmap' },
  { key: 'top_stocks', label: '选股热度', testid: 'sector-tab-top-stocks' },
  { key: 'concepts', label: '概念板块', testid: 'sector-tab-concepts' },
  { key: 'limit_up', label: '涨停归因', testid: 'sector-tab-limit-up' },
  { key: 'digest', label: '4 段式报告', testid: 'sector-tab-digest' },
];

const DEFAULT_TAB: TabKey = 'heatmap';

function readTab(value: string | null): TabKey {
  if (
    value === 'heatmap' || value === 'top_stocks' || value === 'concepts'
    || value === 'limit_up' || value === 'digest'
  ) {
    return value;
  }
  return DEFAULT_TAB;
}

export function SectorPage() {
  const [activeTab, setActiveTab] = React.useState<TabKey>(DEFAULT_TAB);

  const heatmapQuery = useQuery({
    queryKey: ['sector-heatmap', DEFAULT_TOP_N],
    queryFn: () => getHeatmap(DEFAULT_TOP_N),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
  const topStocksQuery = useQuery({
    queryKey: ['sector-top-stocks', DEFAULT_TOP_N],
    queryFn: () => getTopStocks(DEFAULT_TOP_N),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
  const conceptsQuery = useQuery({
    queryKey: ['sector-concepts', DEFAULT_TOP_N],
    queryFn: () => getConcepts(DEFAULT_TOP_N),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
  const limitUpQuery = useQuery({
    queryKey: ['sector-limit-up', DEFAULT_TOP_N],
    queryFn: () => getLimitUp(DEFAULT_TOP_N),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
  const digestQuery = useQuery({
    queryKey: ['sector-digest', DEFAULT_TOP_N],
    queryFn: () => getDigest(DEFAULT_TOP_N),
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });

  function handleRefresh() {
    void heatmapQuery.refetch();
    void topStocksQuery.refetch();
    void conceptsQuery.refetch();
    void limitUpQuery.refetch();
    void digestQuery.refetch();
  }

  const isFetching =
    heatmapQuery.isFetching || topStocksQuery.isFetching
    || conceptsQuery.isFetching || limitUpQuery.isFetching
    || digestQuery.isFetching;

  const heatmapData = heatmapQuery.data;
  const topStocksData = topStocksQuery.data;
  const conceptsData = conceptsQuery.data;
  const limitUpData = limitUpQuery.data;
  const digestData = digestQuery.data;

  // Per-tab error string (so each tab can render its own destructive Alert).
  function errStr(q: { error: unknown }): string | null {
    return q.error instanceof Error ? q.error.message : null;
  }
  const heatmapError = errStr(heatmapQuery);
  const topStocksError = errStr(topStocksQuery);
  const conceptsError = errStr(conceptsQuery);
  const limitUpError = errStr(limitUpQuery);
  const digestError = errStr(digestQuery);

  return (
    <div
      data-testid="sector-page"
      className="mx-auto w-full max-w-7xl space-y-6"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-6 w-6" />
            <h1 className="text-inherit font-inherit">📈 板块轮动</h1>
          </CardTitle>
          <CardDescription>
            每日板块行情 + 选股热度 + 涨停归因 + 概念反查 · 数据源 东财 np-ipick
            + 同花顺 + 百度 PAE · 24h digest cache (与 Streamlit 共享)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm text-text-secondary">
              {heatmapData
                ? `日期 ${heatmapData.date} · top_n ${heatmapData.top_n} · ${heatmapData.count} 个概念板块`
                : '加载中…'}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={isFetching}
              data-testid="sector-refresh"
            >
              <RefreshCw className={isFetching ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
              刷新
            </Button>
          </div>

          {/* Tab strip */}
          <div
            role="tablist"
            aria-label="板块轮动视图"
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
                  aria-controls={`sector-tabpanel-${tab.key}`}
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
            id={`sector-tabpanel-${activeTab}`}
            aria-labelledby={`sector-tab-${activeTab}`}
            data-testid={`sector-panel-${activeTab}`}
            className="pt-2"
          >
            {activeTab === 'heatmap' && (
              heatmapError ? (
                <Alert variant="destructive" data-testid="sector-heatmap-error">
                  <AlertTitle>加载热力图失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{heatmapError}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => void heatmapQuery.refetch()}>
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <Heatmap
                  blocks={heatmapData?.concept_blocks ?? {}}
                  isLoading={heatmapQuery.isLoading}
                />
              )
            )}

            {activeTab === 'top_stocks' && (
              topStocksError ? (
                <Alert variant="destructive" data-testid="sector-top-stocks-error">
                  <AlertTitle>加载选股热度失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{topStocksError}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => void topStocksQuery.refetch()}>
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <TopStocksTable
                  strategies={topStocksData?.strategies ?? []}
                  isLoading={topStocksQuery.isLoading}
                />
              )
            )}

            {activeTab === 'concepts' && (
              conceptsError ? (
                <Alert variant="destructive" data-testid="sector-concepts-error">
                  <AlertTitle>加载概念板块失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{conceptsError}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => void conceptsQuery.refetch()}>
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <ConceptsList
                  concepts={conceptsData?.concepts ?? []}
                  isLoading={conceptsQuery.isLoading}
                />
              )
            )}

            {activeTab === 'limit_up' && (
              limitUpError ? (
                <Alert variant="destructive" data-testid="sector-limit-up-error">
                  <AlertTitle>加载涨停归因失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{limitUpError}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => void limitUpQuery.refetch()}>
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <LimitUpTable
                  stocks={limitUpData?.stocks ?? []}
                  isLoading={limitUpQuery.isLoading}
                />
              )
            )}

            {activeTab === 'digest' && (
              digestError ? (
                <Alert variant="destructive" data-testid="sector-digest-error">
                  <AlertTitle>加载 4 段式报告失败</AlertTitle>
                  <AlertDescription className="flex items-center gap-3">
                    <span>{digestError}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => void digestQuery.refetch()}>
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <DigestViewer
                  markdown={digestData?.markdown ?? ''}
                  sources_ok={digestData?.sources_ok ?? { np_ipick: false, ths_limitup: false, baidu_pae: false }}
                  hot_strategies_count={digestData?.hot_strategies_count ?? 0}
                  hot_stocks_count={digestData?.hot_stocks_count ?? 0}
                  concept_blocks_count={digestData?.concept_blocks_count ?? 0}
                  digest_hash={digestData?.digest_hash ?? ''}
                  isLoading={digestQuery.isLoading}
                />
              )
            )}
          </div>

          <p className="text-xs text-text-tertiary">
            板块轮动日报基于东财 np-ipick 选股热度 + 同花顺涨停归因 + 百度 PAE 概念反查,
            与 Streamlit <code>web/components/sector_panel.py</code> 共用同一业务函数
            <code>get_sector_rotation_digest</code>, 不消耗 LLM token.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default SectorPage;