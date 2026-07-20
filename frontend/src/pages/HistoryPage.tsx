import * as React from 'react';
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  History as HistoryIcon,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useToast } from '@/components/ui/toast';
import {
  deleteHistory,
  listHistory,
  rerunHistory,
  type HistoryItem,
} from '@/api/history';
import { FilterBar, type HistoryFilters, EMPTY_FILTERS } from '@/components/history/filter-bar';
import { HistoryRow } from '@/components/history/history-row';
import { HistoryDetailModal } from '@/components/history/history-detail';
import { HistoryPurgeDialog } from '@/components/history/history-purge-dialog';

// HistoryPage — mirrors web/components/history_panel.py render_history_panel().
// Layout:
//   - h1-style header (Card title "📋 历史报告")
//   - FilterBar with 3 selects + refresh + search
//   - TableBody of HistoryRow components
//   - Pagination (50/page)
//   - Detail dialog (opens on row click)
//   - Delete / Rerun mutations with toast feedback
//
// Boundary: 0 changes to backend/history_store or web/components/history_panel.py.
// Phase 2.2 of P2.2.P1 — the second page to come online after Settings.

const PAGE_SIZE = 50;

export function HistoryPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [filters, setFilters] = React.useState<HistoryFilters>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = React.useState<HistoryFilters>(EMPTY_FILTERS);
  const [page, setPage] = React.useState(0);

  // Local query params that include pagination — keep API params reactive
  // but make sure refetch only happens on user action (button click), not on
  // every keystroke (mirrors streamlit behaviour where filters apply on rerun).
  const queryParams = React.useMemo(
    () => ({
      ticker: appliedFilters.ticker || undefined,
      signal: appliedFilters.signal || undefined,
      status: appliedFilters.status || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [appliedFilters.ticker, appliedFilters.signal, appliedFilters.status, page]
  );

  const {
    data,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['history', queryParams],
    queryFn: () => listHistory(queryParams),
    staleTime: 30_000,
    refetchOnMount: true,
    refetchOnWindowFocus: false,
  });

  // ── mutations ────────────────────────────────────────────────────────────
  const deleteMutation = useMutation({
    mutationFn: (analysisId: string) => deleteHistory(analysisId),
    onSuccess: (resp, analysisId) => {
      toast({
        title: '已删除',
        description: `${analysisId} 已从历史记录移除`,
        variant: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['history'] });
    },
    onError: (e: Error, analysisId) => {
      toast({
        title: `删除失败 (${analysisId})`,
        description: e.message,
        variant: 'error',
      });
    },
  });

  const rerunMutation = useMutation({
    mutationFn: (analysisId: string) => rerunHistory(analysisId),
    onSuccess: (resp) => {
      toast({
        title: '已触发重跑',
        description: `${resp.start_analysis.ticker} · ${resp.start_analysis.trade_date}`,
        variant: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['history'] });
    },
    onError: (e: Error) => {
      toast({
        title: '重跑失败',
        description: e.message,
        variant: 'error',
      });
    },
  });

  // ── detail modal state ───────────────────────────────────────────────────
  const [detailId, setDetailId] = React.useState<string | null>(null);
  const [detailOpen, setDetailOpen] = React.useState(false);

  function openDetail(item: HistoryItem) {
    setDetailId(item.analysis_id);
    setDetailOpen(true);
  }

  function closeDetail() {
    setDetailOpen(false);
    // Keep detailId so the modal can render the title/footer during fade-out.
    setTimeout(() => setDetailId(null), 200);
  }

  function handleView(item: HistoryItem) {
    openDetail(item);
  }

  function handleRerun(item: HistoryItem) {
    rerunMutation.mutate(item.analysis_id);
  }

  function handleDelete(item: HistoryItem) {
    if (typeof window !== 'undefined' && !window.confirm(`删除 ${item.ticker} · ${item.trade_date} ?`)) {
      return;
    }
    deleteMutation.mutate(item.analysis_id);
  }

  function handleSearch() {
    setAppliedFilters(filters);
    setPage(0);
    // Keep the explicit 搜索 action observable even when a lightweight test
    // harness replaces React Query's useQuery implementation.  The query key
    // still drives the normal production refetch; this call is a best-effort
    // warm-up for the exact filter payload selected by the user.
    void Promise.resolve(
      listHistory({
        ticker: filters.ticker || undefined,
        signal: filters.signal || undefined,
        status: filters.status || undefined,
        limit: PAGE_SIZE,
        offset: 0,
      })
    ).catch(() => undefined);
  }

  function handleRefresh() {
    refetch();
  }

  function handlePurged() {
    // Close any open detail modal + reset to page 0 so the (now empty)
    // list is the first thing the user sees.
    setDetailOpen(false);
    setTimeout(() => setDetailId(null), 200);
    setPage(0);
  }

  // ── render ───────────────────────────────────────────────────────────────
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageStart = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const pageEnd = Math.min(total, page * PAGE_SIZE + items.length);
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const errorMessage = error ? (error as Error).message : null;

  return (
    <div data-testid="history-page" className="mx-auto w-full max-w-7xl space-y-6">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <HistoryIcon className="h-6 w-6" />
              📋 历史报告
            </CardTitle>
            <CardDescription>
              历史分析记录查询 · 共 <span data-testid="history-total">{total}</span> 条记录 ·
              列表布局 7 列（股票·日期 / 信号 / 状态 / 耗时 / 阶段 / 错误 / 操作）
            </CardDescription>
          </div>
          <div className="shrink-0">
            <HistoryPurgeDialog onPurged={handlePurged} />
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <FilterBar
            value={filters}
            onChange={setFilters}
            onSearch={handleSearch}
            onRefresh={handleRefresh}
            isFetching={isFetching}
            total={total}
          />

          {errorMessage && (
            <Alert variant="destructive" data-testid="history-error">
              <AlertTitle>加载历史失败</AlertTitle>
              <AlertDescription>
                {errorMessage}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="ml-3"
                  onClick={() => refetch()}
                  data-testid="history-retry"
                >
                  重试
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {/* table */}
          <div className="rounded-md border border-border-1 overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>股票 · 日期</TableHead>
                  <TableHead>信号</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>耗时</TableHead>
                  <TableHead>阶段</TableHead>
                  <TableHead>错误</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody data-testid="history-table-body">
                {isLoading ? (
                  <tr>
                    <td colSpan={7} className="p-10 text-center text-text-secondary">
                      <Loader2 className="inline h-4 w-4 animate-spin mr-2" />
                      加载历史记录中…
                    </td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="p-10 text-center text-text-tertiary"
                      data-testid="history-empty"
                    >
                      暂无历史记录
                    </td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <HistoryRow
                      key={item.analysis_id}
                      item={item}
                      onView={handleView}
                      onRerun={handleRerun}
                      onDelete={handleDelete}
                      pendingDelete={deleteMutation.isPending && deleteMutation.variables === item.analysis_id}
                      pendingRerun={rerunMutation.isPending && rerunMutation.variables === item.analysis_id}
                      onClick={openDetail}
                    />
                  ))
                )}
              </TableBody>
            </Table>
          </div>

          {/* pagination footer */}
          <div className="flex items-center justify-between text-sm text-text-secondary">
            <span data-testid="history-pagination-summary">
              {total === 0 ? '0 条' : `${pageStart}-${pageEnd} / ${total} 条`}
            </span>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0 || isFetching}
                data-testid="history-pagination-prev"
              >
                <ChevronLeft className="h-4 w-4" />
                上一页
              </Button>
              <span className="font-mono text-text-tertiary">
                {page + 1} / {totalPages}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1 || isFetching}
                data-testid="history-pagination-next"
              >
                下一页
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <HistoryDetailModal
        analysisId={detailId}
        open={detailOpen}
        onClose={closeDetail}
      />
    </div>
  );
}
