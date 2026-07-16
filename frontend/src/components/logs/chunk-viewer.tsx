import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Loader2, Brain, Wrench, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getChunks, type ChunkType, type LogChunk } from '@/api/logs';

// ChunkViewer — renders the jsonl chunks for a selected (ticker, task) pair
// with three tabs matching `web/components/logs_panel.py::_render_chunk_card`:
//   - 🧠 LLM Messages        → type=llm
//   - 🔧 Tool Calls          → type=tool
//   - 📄 Agent Outputs       → type=agent_output
//
// The 3 tabs are implemented as a lightweight switcher (no Radix Tabs
// dependency) — same visual semantics, simpler code, and matches the
// streamlit `st.tabs(["Agent Outputs", "LLM Messages", "Tool Calls"])` UX.
//
// Tool chunks get collapsible input/output panes (mirrors streamlit's
// `st.expander("input", expanded=False)` / `st.expander("output")`).

type TabKey = 'llm' | 'tool' | 'agent_output';

const TAB_DEFS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
  { key: 'agent_output', label: 'Agent Outputs', icon: <FileText className="h-3.5 w-3.5" /> },
  { key: 'llm', label: 'LLM Messages', icon: <Brain className="h-3.5 w-3.5" /> },
  { key: 'tool', label: 'Tool Calls', icon: <Wrench className="h-3.5 w-3.5" /> },
];

interface ChunkViewerProps {
  ticker: string | null;
  task: string | null;
}

export function ChunkViewer({ ticker, task }: ChunkViewerProps) {
  const [tab, setTab] = React.useState<TabKey>('agent_output');

  const enabled = Boolean(ticker && task);

  const { data, isLoading, error } = useQuery({
    queryKey: ['logs-chunks', ticker, task, tab],
    queryFn: () => getChunks(ticker as string, task as string, tab),
    enabled,
    staleTime: 30_000,
    retry: 0,
  });

  if (!ticker || !task) {
    return (
      <div
        className="flex h-full items-center justify-center text-text-tertiary text-sm py-12"
        data-testid="chunk-viewer-prompt"
      >
        ← 选择 ticker + task 查看 chunks
      </div>
    );
  }

  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-text-secondary text-sm py-6"
        data-testid="chunk-viewer-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载 chunks…
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="rounded-md border border-bb-up/40 bg-bb-up/10 p-3 text-bb-up text-sm"
        data-testid="chunk-viewer-error"
      >
        加载 chunks 失败: {(error as Error).message}
      </div>
    );
  }

  const chunks = data?.chunks ?? [];
  const counts = data?.counts ?? {};

  return (
    <div
      className="flex flex-col gap-3"
      data-testid="chunk-viewer"
      aria-label={`${ticker} / ${task} chunks`}
    >
      <div
        className="inline-flex items-center gap-1 rounded-md border border-border-1 bg-bg-elevated p-1 self-start"
        role="tablist"
      >
        {TAB_DEFS.map((t) => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              data-testid={`chunk-tab-${t.key}`}
              onClick={() => setTab(t.key)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-sm px-3 py-1.5 text-xs font-medium transition-colors',
                active
                  ? 'bg-bb-accent text-white shadow'
                  : 'text-text-secondary hover:bg-bg-surface hover:text-text-primary'
              )}
            >
              {t.icon}
              <span>{t.label}</span>
              <span className="font-mono text-[10px] opacity-70">
                {counts[t.key] ?? 0}
              </span>
            </button>
          );
        })}
      </div>

      <div
        className="font-mono text-[11px] text-text-tertiary"
        data-testid="chunk-viewer-summary"
      >
        {ticker} · {task} · {chunks.length} {tab} chunks
      </div>

      {chunks.length === 0 ? (
        <div
          className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center text-text-tertiary text-sm"
          data-testid="chunk-viewer-empty"
        >
          此任务暂无 {tab} 类型 chunk
        </div>
      ) : (
        <div
          className="flex flex-col gap-3 max-h-[60vh] overflow-y-auto pr-1"
          data-testid="chunk-list"
        >
          {chunks.map((chunk, idx) => (
            <ChunkCard key={`${chunk.ts ?? idx}-${idx}`} chunk={chunk} />
          ))}
        </div>
      )}
    </div>
  );
}

function ChunkCard({ chunk }: { chunk: LogChunk }) {
  const type = (chunk.type ?? 'agent_output') as ChunkType;

  const header = (() => {
    if (type === 'llm') {
      const tk = chunk.tokens_in || chunk.tokens_out
        ? ` · tokens ${chunk.tokens_in ?? 0}/${chunk.tokens_out ?? 0}`
        : '';
      return `LLM · ${chunk.agent ?? ''}${tk}`;
    }
    if (type === 'tool') {
      return `Tool · ${chunk.agent ?? ''} · ${chunk.tool ?? ''}`;
    }
    return `Output · ${chunk.agent ?? ''} · ${chunk.report_key ?? ''}`;
  })();

  const icon = type === 'llm' ? '🧠' : type === 'tool' ? '🔧' : '📄';

  return (
    <article
      className="rounded-md border border-border-1 bg-bg-elevated overflow-hidden"
      data-testid={`chunk-card-${type}`}
    >
      <header className="flex items-center gap-2 px-3 py-2 border-b border-border-1 bg-bg-surface text-xs text-text-primary">
        <span aria-hidden>{icon}</span>
        <span className="font-mono truncate">{header}</span>
      </header>

      {type === 'tool' ? (
        <div className="px-3 py-3 space-y-2 text-xs">
          <details className="rounded-md border border-border-1 bg-bg-base">
            <summary className="cursor-pointer px-3 py-2 text-text-secondary select-none">
              input
            </summary>
            <pre className="px-3 py-2 whitespace-pre-wrap break-words text-text-primary">
              {chunk.input ? JSON.stringify(chunk.input, null, 2) : ''}
            </pre>
          </details>
          <details className="rounded-md border border-border-1 bg-bg-base">
            <summary className="cursor-pointer px-3 py-2 text-text-secondary select-none">
              output
            </summary>
            <pre className="px-3 py-2 whitespace-pre-wrap break-words text-text-primary">
              {chunk.output ?? ''}
            </pre>
          </details>
        </div>
      ) : (
        <pre className="px-3 py-3 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-text-primary">
          {chunk.content ?? ''}
        </pre>
      )}
    </article>
  );
}