/**
 * Analyze API client — mirrors backend/api/analyze.py 1:1.
 *
 * Endpoints:
 *   POST /api/analyze                       → start a new analysis (returns 202 + analysis_id)
 *   GET  /api/analyze/recent?limit=N        → list most-recent N analyses (newest first)
 *   GET  /api/analyze/{id}                  → live progress (poll while running)
 *   GET  /api/analyze/{id}/report           → full report (full_states_log_*.json)
 *
 * Both UIs (Streamlit analyze_panel.py + this React AnalyzePage) call the
 * same backend.core.start_analysis / tracker / history_store singletons. No
 * business logic here — pure HTTP mirror of the FastAPI surface.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

/**
 * P2.12 hotfix — guard against /api/analyze/null/... 404 storms.
 *
 * Root cause: the React Query `queryFn` closures sometimes fire even when
 * `enabled` is false (React Query v5 HMR edge case, refetchInterval race
 * where activeAnalysisId flips to null mid-flight, etc.). When that happens
 * the fetch URL becomes `/api/analyze/null` or `/api/analyze/null/report`
 * — both 404. We throw here BEFORE constructing the URL, so the network
 * layer never sees a malformed request and the recent list / toast /
 * fallback effect can drive the actual recovery.
 *
 * Treats as invalid: null, undefined, empty string, the literal strings
 * "null" / "undefined" (which the JS URL API happily forwards when a
 * caller forgot to JSON.parse).
 */
export function safeAnalysisId(id: string | null | undefined): string {
  if (!id || id === 'null' || id === 'undefined' || id.trim() === '') {
    throw new Error(`invalid analysis_id: ${String(id)}`);
  }
  return id;
}

// ── request / response shapes ────────────────────────────────────────────────

/** Pydantic mirror: AnalyzeRequest (backend/models/request.py). */
export interface AnalyzeRequest {
  ticker: string;
  trade_date: string;
  llm_provider?: string;
  quick_think_llm?: string;
  deep_think_llm?: string;
  backend_url?: string | null;
}

/** Pydantic mirror: AnalyzeResponse (POST /api/analyze). */
export interface AnalyzeResult {
  analysis_id: string;
  status: string;
  ticker: string;
  trade_date: string;
}

/** Pydantic mirror: ProgressResponse (GET /api/analyze/{id}). */
export interface ProgressStats {
  llm_calls: number;
  tool_calls: number;
  tokens_in: number;
  tokens_out: number;
}

export interface ProgressResponse {
  status: string;
  ticker: string;
  trade_date: string;
  current_stage: string | null;
  completed_stages: string[];
  stage_reports: Record<string, string>;
  stats: ProgressStats;
  elapsed: number;
  signal: string | null;
  error: string | null;
}

/** Pydantic mirror: AnalyzeReport (GET /api/analyze/{id}/report). */
export interface AnalyzeReport {
  analysis_id: string;
  ticker: string;
  trade_date: string;
  results_path: string;
  report: Record<string, unknown> | null;
}

/** Pydantic mirror: RecentAnalyzeItem (GET /api/analyze/recent). */
export interface RecentAnalyzeItem {
  analysis_id: string;
  ticker: string;
  trade_date: string;
  signal: string | null;
  elapsed: number;
  created_at: string;
  status: string | null;
  error: string | null;
  completed_stages: string[];
}

// ── POST /api/analyze ────────────────────────────────────────────────────────

export async function startAnalysis(payload: AnalyzeRequest): Promise<AnalyzeResult> {
  const res = await fetch(_url('/api/analyze'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'omit',
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`POST /api/analyze ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as AnalyzeResult;
}

// ── GET /api/analyze/{id} ────────────────────────────────────────────────────

export async function getAnalysis(analysisId: string): Promise<ProgressResponse> {
  // P2.12 hotfix — refuse to build the URL with an invalid id so we never
  // hit `/api/analyze/null` even if a React Query queryFn runs while
  // enabled=false (HMR / refetchInterval race).
  const safeId = safeAnalysisId(analysisId);
  const res = await fetch(
    _url(`/api/analyze/${encodeURIComponent(safeId)}`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`GET /api/analyze/${safeId} ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as ProgressResponse;
}

// ── GET /api/analyze/{id}/report ─────────────────────────────────────────────

export async function getAnalysisReport(analysisId: string): Promise<AnalyzeReport> {
  // P2.12 hotfix — see getAnalysis().
  const safeId = safeAnalysisId(analysisId);
  const res = await fetch(
    _url(`/api/analyze/${encodeURIComponent(safeId)}/report`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`GET /api/analyze/${safeId}/report ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as AnalyzeReport;
}

// ── GET /api/analyze/recent ──────────────────────────────────────────────────

export async function getRecentAnalyzes(limit: number = 20): Promise<RecentAnalyzeItem[]> {
  const qs = `?limit=${encodeURIComponent(String(limit))}`;
  const res = await fetch(_url(`/api/analyze/recent${qs}`), { credentials: 'omit' });
  if (!res.ok) {
    throw new Error(`GET /api/analyze/recent ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as RecentAnalyzeItem[];
}