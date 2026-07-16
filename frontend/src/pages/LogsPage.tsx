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
import { ScrollText, RefreshCw } from 'lucide-react';
import {
  listTickers,
  listTasks,
  type LogTaskSummary,
  type TickerSummary,
} from '@/api/logs';
import { TickerList } from '@/components/logs/ticker-list';
import { TaskList } from '@/components/logs/task-list';
import { ChunkViewer } from '@/components/logs/chunk-viewer';

// LogsPage — mirrors `web/components/logs_panel.py::render_logs_panel()`
// 1:3 layout:
//   ┌────────────┬──────────────────────────────────┐
//   │ Tickers    │ Tasks for {ticker}                │
//   │ (1/4)      ├──────────────────────────────────┤
//   │            │ Chunk viewer (3 tabs)             │
//   │            │ (3/4 total)                       │
//   └────────────┴──────────────────────────────────┘
//
// State: ticker + selectedTask live in component state (parent owns the
// "two-column" coordination). React Query handles ticker list + per-ticker
// task list; ChunkViewer manages its own per-task chunks query.

export function LogsPage() {
  const [selectedTicker, setSelectedTicker] = React.useState<string | null>(null);
  const [selectedTask, setSelectedTask] = React.useState<string | null>(null);

  // Tickers — server-sorted, defensive re-sort lives in TickerList itself.
  const tickersQuery = useQuery({
    queryKey: ['logs-tickers'],
    queryFn: () => listTickers(),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  // Per-ticker tasks.
  const tasksQuery = useQuery({
    queryKey: ['logs-tasks', selectedTicker],
    queryFn: () => listTasks(selectedTicker as string),
    enabled: Boolean(selectedTicker),
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  // Default-select first ticker when the list first arrives so the user
  // sees immediate content (mirrors streamlit's `st.session_state` default).
  React.useEffect(() => {
    if (selectedTicker) return;
    const tickers: TickerSummary[] = tickersQuery.data?.tickers ?? [];
    if (tickers.length > 0) {
      setSelectedTicker(tickers[0].ticker);
    }
  }, [tickersQuery.data, selectedTicker]);

  // Reset selected task when ticker changes (or when the underlying list
  // shows no tasks for the current selection).
  React.useEffect(() => {
    setSelectedTask(null);
  }, [selectedTicker]);

  React.useEffect(() => {
    if (!tasksQuery.data) return;
    const tasks = tasksQuery.data.tasks;
    if (!tasks.length) {
      setSelectedTask(null);
      return;
    }
    // If the previously-selected task no longer exists, snap to the latest.
    if (!selectedTask || !tasks.some((t) => t.task_dir_name === selectedTask)) {
      setSelectedTask(tasks[0].task_dir_name);
    }
  }, [tasksQuery.data, selectedTask]);

  const tickers = tickersQuery.data?.tickers ?? [];
  const tasks = tasksQuery.data?.tasks ?? [];
  const tickersError = tickersQuery.error
    ? (tickersQuery.error as Error).message
    : null;
  const tasksError = tasksQuery.error
    ? (tasksQuery.error as Error).message
    : null;

  function handleRefresh() {
    void tickersQuery.refetch();
    if (selectedTicker) void tasksQuery.refetch();
  }

  function handleTickerSelect(ticker: string) {
    setSelectedTicker(ticker);
  }

  function handleTaskSelect(task: LogTaskSummary) {
    setSelectedTask(task.task_dir_name);
  }

  return (
    <div
      data-testid="logs-page"
      className="mx-auto w-full max-w-7xl space-y-6"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScrollText className="h-6 w-6" />
            📋 日志
          </CardTitle>
          <CardDescription>
            LangGraph stream chunks 实时 + 历史 · 共{' '}
            <span data-testid="logs-ticker-total">{tickers.length}</span> 个 ticker
            · 布局 1:3 双列 (左 ticker 列表, 右 task 列表 + chunks 三 tab)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm text-text-secondary">
              {selectedTicker
                ? `当前 ticker: ${selectedTicker} · ${tasks.length} 个任务`
                : '选择一个 ticker 查看历史日志'}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={tickersQuery.isFetching || tasksQuery.isFetching}
              data-testid="logs-refresh"
            >
              <RefreshCw
                className={
                  tickersQuery.isFetching || tasksQuery.isFetching
                    ? 'h-4 w-4 animate-spin'
                    : 'h-4 w-4'
                }
              />
              刷新
            </Button>
          </div>

          {tickersError && (
            <Alert variant="destructive" data-testid="logs-tickers-error">
              <AlertTitle>加载 ticker 列表失败</AlertTitle>
              <AlertDescription>
                {tickersError}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="ml-3"
                  onClick={() => tickersQuery.refetch()}
                  data-testid="logs-tickers-retry"
                >
                  重试
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
            {/* left column — ticker list (1/4) */}
            <aside
              className="lg:col-span-1"
              data-testid="logs-ticker-column"
            >
              <TickerList
                tickers={tickers}
                selectedTicker={selectedTicker}
                onSelect={handleTickerSelect}
                isLoading={tickersQuery.isLoading}
                error={tickersError}
              />
            </aside>

            {/* right column — task list (3/4) + chunk viewer */}
            <section
              className="lg:col-span-3 space-y-4"
              data-testid="logs-task-column"
            >
              {tasksError ? (
                <Alert variant="destructive" data-testid="logs-tasks-error">
                  <AlertTitle>加载任务列表失败</AlertTitle>
                  <AlertDescription>
                    {tasksError}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="ml-3"
                      onClick={() => tasksQuery.refetch()}
                      data-testid="logs-tasks-retry"
                    >
                      重试
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : (
                <TaskList
                  ticker={selectedTicker}
                  tasks={tasks}
                  selectedTask={selectedTask}
                  onSelect={handleTaskSelect}
                  isLoading={tasksQuery.isLoading}
                />
              )}

              <div className="border-t border-border-1 pt-4">
                <ChunkViewer ticker={selectedTicker} task={selectedTask} />
              </div>
            </section>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}