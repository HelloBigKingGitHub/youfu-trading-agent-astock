/**
 * DigestViewer — renders the 4-section Markdown digest from
 * ``backend/api/sector.py::get_digest``.
 *
 * The backend returns ``{ markdown, sources_ok, hot_strategies_count,
 * hot_stocks_count, concept_blocks_count, digest_hash }``.  We render the
 * Markdown as a monospace block (Streamlit's ``st.markdown(md)`` does the
 * same); a future polish can swap in a markdown renderer like
 * ``react-markdown`` if we want syntax-highlighted tables.  For the parity
 * gate, byte-identical Markdown content is what matters — see
 * ``scripts/parity_check.py --page sector``.
 *
 * Sources banner at the top shows which upstream data sources responded OK
 * (np-ipick, 同花顺, 百度 PAE).
 */
import * as React from 'react';
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { SourcesOk } from '@/api/sector';

interface DigestViewerProps {
  markdown: string;
  sources_ok: SourcesOk;
  hot_strategies_count: number;
  hot_stocks_count: number;
  concept_blocks_count: number;
  digest_hash: string;
  isLoading?: boolean;
  error?: string | null;
}

function SourcePill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-[11px] font-mono px-2 py-0.5 rounded-full border',
        ok
          ? 'border-bb-down/40 bg-bb-down/10 text-bb-down'
          : 'border-bb-up/40 bg-bb-up/10 text-bb-up',
      )}
      title={ok ? `${label} OK` : `${label} unavailable`}
    >
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      {label}
    </span>
  );
}

export const DigestViewer = React.memo(function DigestViewer({
  markdown,
  sources_ok,
  hot_strategies_count,
  hot_stocks_count,
  concept_blocks_count,
  digest_hash,
  isLoading,
  error,
}: DigestViewerProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="digest-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载 4 段式报告…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="digest-error"
      >
        加载 4 段式报告失败: {error}
      </div>
    );
  }

  if (!markdown) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
        data-testid="digest-empty"
      >
        暂无 4 段式报告
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="digest-viewer">
      {/* Sources banner */}
      <div
        className="rounded-md border border-border-1 bg-bg-elevated p-3 flex flex-wrap items-center gap-2"
        data-testid="digest-sources"
      >
        <span className="text-[11px] uppercase tracking-wider text-text-tertiary mr-1">
          数据源
        </span>
        <SourcePill ok={Boolean(sources_ok.np_ipick)} label="东财 np-ipick" />
        <SourcePill ok={Boolean(sources_ok.ths_limitup)} label="同花顺 涨停" />
        <SourcePill ok={Boolean(sources_ok.baidu_pae)} label="百度 PAE 概念" />
        <span className="ml-auto text-[11px] font-mono text-text-tertiary">
          热度 {hot_strategies_count} · 涨停 {hot_stocks_count} · 概念 {concept_blocks_count}
        </span>
        <span
          className="font-mono text-[10px] text-text-tertiary"
          data-testid="digest-hash"
          title="md5(canonical-payload) — same as parity_check.py"
        >
          md5: {digest_hash.slice(0, 8)}…
        </span>
      </div>

      {/* Markdown body — monospace block, identical to streamlit's st.markdown */}
      <pre
        className="rounded-md border border-border-1 bg-bg-elevated p-4
                   font-mono text-[12.5px] leading-relaxed text-text-primary
                   whitespace-pre-wrap break-words max-h-[70vh] overflow-y-auto"
        data-testid="digest-markdown"
      >
        {markdown}
      </pre>
    </div>
  );
});