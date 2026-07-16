/**
 * Logs API client — mirrors backend/api/logs.py 1:1.
 *
 * Endpoints:
 *   GET /api/logs/tickers                              list of tickers + counts
 *   GET /api/logs/tasks?ticker=                       list of tasks per ticker
 *   GET /api/logs/task?ticker=&task=                   single task meta + counts
 *   GET /api/logs/chunks?ticker=&task=&type=           chunks (optionally typed)
 *   GET /api/logs/counts?ticker=&task=                 lightweight counts
 *
 * Both UIs (Streamlit logs_panel.py + this React LogsPage) ultimately read
 * from the SAME store (backend/core/log_store.py via LogStore), so payloads
 * are the canonical Pydantic mirror and do NOT need massaging in React.
 *
 * React Query is used at the call site; this module is the *transport* layer
 * — keep it dumb (no caching, no transformation). Mirrors the style of
 * frontend/src/api/history.ts.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

// ── shared types ────────────────────────────────────────────────────────────
export type ChunkType = 'llm' | 'tool' | 'agent_output';
export type TaskStatus = 'running' | 'completed' | 'error' | 'pending' | string;

export interface ChunkCounts {
  llm: number;
  tool: number;
  agent_output: number;
}

// ── list tickers ────────────────────────────────────────────────────────────
export interface TickerSummary {
  ticker: string;
  task_count: number;
  latest_signal: string;
  latest_status: string;
  latest_trade_date: string;
}

export interface TickersResponse {
  tickers: TickerSummary[];
  total: number;
}

export async function listTickers(): Promise<TickersResponse> {
  const res = await fetch(_url('/api/logs/tickers'), { credentials: 'omit' });
  if (!res.ok) {
    throw new Error(`GET /api/logs/tickers ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as TickersResponse;
}

// ── list tasks ──────────────────────────────────────────────────────────────
export interface LogTaskSummary {
  analysis_id: string;
  ticker: string;
  trade_date: string;
  task_dir_name: string;
  status: TaskStatus;
  signal: string;
  elapsed_sec: number;
  started_at: string | null;
  finished_at: string | null;
  chunk_counts: ChunkCounts;
  is_legacy: boolean;
}

export interface TasksResponse {
  ticker: string;
  tasks: LogTaskSummary[];
  total: number;
}

export async function listTasks(ticker: string): Promise<TasksResponse> {
  const res = await fetch(
    _url(`/api/logs/tasks?ticker=${encodeURIComponent(ticker)}`),
    { credentials: 'omit' }
  );
  if (!res.ok) {
    throw new Error(`GET /api/logs/tasks ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as TasksResponse;
}

// ── single task meta ────────────────────────────────────────────────────────
export interface TaskMeta {
  analysis_id?: string;
  ticker?: string;
  trade_date?: string;
  task_dir_name?: string;
  status?: TaskStatus;
  signal?: string | null;
  elapsed_sec?: number;
  started_at?: string | number | null;
  finished_at?: string | number | null;
  error?: string | null;
  stages_completed?: string[];
  chunk_counts?: ChunkCounts;
  created_at?: string | number | null;
  is_legacy?: boolean;
  [key: string]: unknown;
}

export interface TaskResponse {
  meta: TaskMeta;
  chunk_counts: ChunkCounts;
  ticker: string;
  task: string;
}

export async function getTask(ticker: string, task: string): Promise<TaskResponse> {
  const res = await fetch(
    _url(
      `/api/logs/task?ticker=${encodeURIComponent(ticker)}&task=${encodeURIComponent(task)}`
    ),
    { credentials: 'omit' }
  );
  if (!res.ok) {
    throw new Error(`GET /api/logs/task ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as TaskResponse;
}

// ── chunks ──────────────────────────────────────────────────────────────────
export interface LogChunk {
  ts: number | null;
  type: ChunkType | string;
  agent?: string;
  role?: string;
  tool?: string;
  tokens_in?: number | null;
  tokens_out?: number | null;
  report_key?: string;
  content?: string | null;
  input?: Record<string, unknown> | null;
  output?: string | null;
  // Allow backend to add other fields without breaking the UI.
  [key: string]: unknown;
}

export interface ChunksResponse {
  ticker: string;
  task: string;
  type: ChunkType | null;
  chunks: LogChunk[];
  total: number;
  counts: Record<string, number>;
}

export async function getChunks(
  ticker: string,
  task: string,
  type?: ChunkType | null
): Promise<ChunksResponse> {
  const qs = new URLSearchParams({ ticker, task });
  if (type) qs.set('type', type);
  const res = await fetch(_url(`/api/logs/chunks?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/logs/chunks ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as ChunksResponse;
}

// ── counts ──────────────────────────────────────────────────────────────────
export interface CountsResponse {
  ticker?: string;
  task?: string;
  counts?: ChunkCounts;
  tickers?: Record<string, ChunkCounts>;
  grand_total?: ChunkCounts;
  total_tickers?: number;
}

export async function getCounts(
  ticker?: string | null,
  task?: string | null
): Promise<CountsResponse> {
  const qs = new URLSearchParams();
  if (ticker) qs.set('ticker', ticker);
  if (task) qs.set('task', task);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  const res = await fetch(_url(`/api/logs/counts${suffix}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/logs/counts ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as CountsResponse;
}