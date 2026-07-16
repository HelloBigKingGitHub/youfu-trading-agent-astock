/**
 * Sector API client — mirrors backend/api/sector.py 1:1.
 *
 * Endpoints:
 *   GET /api/sector/heatmap?date=&top_n=      concept_blocks (block-name → stocks)
 *   GET /api/sector/top_stocks?date=&limit=   np-ipick hot strategies (heatValue desc)
 *   GET /api/sector/concepts?date=&top_n=     block-name → {stock_count, avg_ratio, codes}
 *   GET /api/sector/limit_up?date=&top_n=     同花顺 limit-up list with reason tags
 *   GET /api/sector/digest?date=&top_n=       pre-rendered 4-section Markdown digest
 *
 * Both UIs (Streamlit sector_panel.py + this React SectorPage) ultimately
 * call the same business-layer function: ``get_sector_rotation_digest``.
 * No LLM is involved — the digest is built from np-ipick + 同花顺 + 百度 PAE
 * HTTP data only. The React page can safely re-fetch on demand without
 * burning tokens.
 *
 * Mirrors the style of frontend/src/api/chart.ts.
 */

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

function _url(path: string): string {
  return `${API_BASE}${path}`;
}

export const DEFAULT_TOP_N = 20;

// ── shared types ────────────────────────────────────────────────────────────

export interface SourcesOk {
  np_ipick: boolean;
  ths_limitup: boolean;
  baidu_pae: boolean;
  [key: string]: boolean;
}

export interface HotStrategy {
  rank: string;
  heatValue: number;
  chg: string;
  question: string;
  [key: string]: unknown;
}

export interface LimitUpStock {
  code: string;
  name: string;
  reason: string;
  ratio?: string;
  zhangfu?: string;
  huanshou?: string;
  chengjiaoe?: string;
  ddejingliang?: string;
  [key: string]: unknown;
}

export interface ConceptStock extends LimitUpStock {}

export interface ConceptSummary {
  name: string;
  stock_count: number;
  avg_ratio: number;
  codes: string[];
}

// ── /api/sector/heatmap ─────────────────────────────────────────────────────

export interface HeatmapResponse {
  date: string;
  top_n: number;
  concept_blocks: Record<string, ConceptStock[]>;
  sources_ok: SourcesOk;
  count: number;
}

export async function getHeatmap(topN: number = DEFAULT_TOP_N): Promise<HeatmapResponse> {
  const qs = new URLSearchParams({ top_n: String(topN) });
  const res = await fetch(_url(`/api/sector/heatmap?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/sector/heatmap ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as HeatmapResponse;
}

// ── /api/sector/top_stocks ──────────────────────────────────────────────────

export interface TopStocksResponse {
  date: string;
  limit: number;
  strategies: HotStrategy[];
  sources_ok: SourcesOk;
  count: number;
}

export async function getTopStocks(limit: number = DEFAULT_TOP_N): Promise<TopStocksResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(_url(`/api/sector/top_stocks?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/sector/top_stocks ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as TopStocksResponse;
}

// ── /api/sector/concepts ────────────────────────────────────────────────────

export interface ConceptsResponse {
  date: string;
  top_n: number;
  concepts: ConceptSummary[];
  sources_ok: SourcesOk;
  count: number;
}

export async function getConcepts(topN: number = DEFAULT_TOP_N): Promise<ConceptsResponse> {
  const qs = new URLSearchParams({ top_n: String(topN) });
  const res = await fetch(_url(`/api/sector/concepts?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/sector/concepts ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as ConceptsResponse;
}

// ── /api/sector/limit_up ────────────────────────────────────────────────────

export interface LimitUpResponse {
  date: string;
  top_n: number;
  stocks: LimitUpStock[];
  sources_ok: SourcesOk;
  count: number;
}

export async function getLimitUp(topN: number = DEFAULT_TOP_N): Promise<LimitUpResponse> {
  const qs = new URLSearchParams({ top_n: String(topN) });
  const res = await fetch(_url(`/api/sector/limit_up?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/sector/limit_up ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as LimitUpResponse;
}

// ── /api/sector/digest ──────────────────────────────────────────────────────

export interface DigestResponse {
  date: string;
  top_n: number;
  markdown: string;
  sources_ok: SourcesOk;
  hot_strategies_count: number;
  hot_stocks_count: number;
  concept_blocks_count: number;
  digest_hash: string;
}

export async function getDigest(topN: number = DEFAULT_TOP_N): Promise<DigestResponse> {
  const qs = new URLSearchParams({ top_n: String(topN) });
  const res = await fetch(_url(`/api/sector/digest?${qs.toString()}`), {
    credentials: 'omit',
  });
  if (!res.ok) {
    throw new Error(`GET /api/sector/digest ${res.status}: ${await res.text()}`);
  }
  return (await res.json()) as DigestResponse;
}