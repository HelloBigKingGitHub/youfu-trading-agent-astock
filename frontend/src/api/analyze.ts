/**
 * Analyze API client — mirrors backend/api/analyze.py 1:1.
 *
 * Endpoints:
 *   POST /api/analyze                       → start a new analysis (returns 202 + analysis_id)
 *   GET  /api/analyze/recent?limit=N        → list most-recent N analyses (newest first)
 *   GET  /api/analyze/{id}                  → live progress (poll while running)
 *   GET  /api/analyze/{id}/report           → full report (full_states_log_*.json)
 *   GET  /api/analyze/{id}/export?format=X  → download as md|pdf (P2.29)
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

/** Pydantic mirror: AnalyzeReport (GET /api/analyze/{id}/report).
 *
 *  P2.29 — added ``pdf_available`` so the report tab can decide whether the
 *  📄 PDF button is enabled without a separate preflight request. Computed
 *  once at module import by probing the host for a CJK font (see
 *  backend/api/analyze.py::_pdf_export_available).
 */
export interface AnalyzeReport {
  analysis_id: string;
  ticker: string;
  trade_date: string;
  results_path: string;
  report: Record<string, unknown> | null;
  pdf_available: boolean;
}

export type ExportFormat = 'md' | 'pdf';

export function analyzeExportUrl(analysisId: string, format: ExportFormat): string {
  return _url(`/api/analyze/${safeAnalysisId(analysisId)}/export?format=${format}`);
}

export function analyzeExportFilename(
  ticker: string,
  trade_date: string,
  format: ExportFormat,
): string {
  return `TradingAgents-Astock_${ticker}_${trade_date}.${format}`;
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

// ── GET /api/analyze/{id}/progress ───────────────────────────────────────────
//
// P2.24 hotfix — /api/analyze/{id} returns the FULL AnalysisResult
// (market_report / sentiment_report / ... / debate_state / final_trade_decision)
// and intentionally OMITS the per-stage ``current_stage`` / ``stage_reports`` /
// ``signal`` fields that the React ``AnalysisProgress`` and ``AnalysisWorkspace``
// components rely on. The dedicated ``/api/analyze/{id}/progress`` endpoint
// (backend/api/progress.py) returns a slim ``ProgressResponse`` carrying those
// fields, plus a HistoryStore fallback for analyses that have already been
// evicted from the in-memory TrackerStore.
//
// Both Streamlit (analyze_panel.py) and React (AnalyzePage.tsx) now call
// /progress for the live poll, while /report and /{id} (AnalysisResult) stay
// reserved for the consolidated report view.
export async function getProgress(analysisId: string): Promise<ProgressResponse> {
  // P2.12 hotfix — refuse to build the URL with an invalid id so we never
  // hit `/api/analyze/null/progress` even if a React Query queryFn runs while
  // enabled=false (HMR / refetchInterval race).
  const safeId = safeAnalysisId(analysisId);
  const res = await fetch(
    _url(`/api/analyze/${encodeURIComponent(safeId)}/progress`),
    { credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`GET /api/analyze/${safeId}/progress ${res.status}: ${await res.text()}`);
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

// ── POST /api/analyze/{id}/cancel ────────────────────────────────────────────

/** P2.21 hotfix — user can cancel a stuck/slow analysis from the UI. */
export interface CancelAnalysisResult {
  analysis_id: string;
  status: 'error';
  reason: string;
}

export async function cancelAnalysis(analysisId: string): Promise<CancelAnalysisResult> {
  const safeId = safeAnalysisId(analysisId);
  const res = await fetch(
    _url(`/api/analyze/${encodeURIComponent(safeId)}/cancel`),
    { method: 'POST', credentials: 'omit' },
  );
  if (!res.ok) {
    throw new Error(`POST /api/analyze/${safeId}/cancel ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as CancelAnalysisResult;
}