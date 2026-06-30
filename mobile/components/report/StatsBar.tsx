"use client";

import type { ProgressResponse } from "@/lib/types";

interface StatsBarProps {
  stats: ProgressResponse["stats"];
  elapsed?: number;
}

export function StatsBar({ stats, elapsed }: StatsBarProps) {
  if (!stats && elapsed === undefined) return null;

  return (
    <div className="flex justify-around text-xs text-[var(--text-muted)] bg-[var(--bg-card)] rounded-xl p-3 border border-[var(--border-subtle)]">
      {stats?.llm_calls != null && (
        <div className="flex flex-col items-center">
          <span className="text-[var(--text-secondary)] font-semibold text-sm">{stats.llm_calls}</span>
          <span>LLM</span>
        </div>
      )}
      {stats?.tool_calls != null && (
        <div className="flex flex-col items-center">
          <span className="text-[var(--text-secondary)] font-semibold text-sm">{stats.tool_calls}</span>
          <span>工具</span>
        </div>
      )}
      {stats?.tokens_in != null && (
        <div className="flex flex-col items-center">
          <span className="text-[var(--text-secondary)] font-semibold text-sm">
            {stats.tokens_in >= 1000 ? `${(stats.tokens_in / 1000).toFixed(1)}k` : stats.tokens_in}
          </span>
          <span>输入</span>
        </div>
      )}
      {stats?.tokens_out != null && (
        <div className="flex flex-col items-center">
          <span className="text-[var(--text-secondary)] font-semibold text-sm">
            {stats.tokens_out >= 1000 ? `${(stats.tokens_out / 1000).toFixed(1)}k` : stats.tokens_out}
          </span>
          <span>输出</span>
        </div>
      )}
      {elapsed !== undefined && (
        <div className="flex flex-col items-center">
          <span className="text-[var(--text-secondary)] font-semibold text-sm">{elapsed.toFixed(1)}s</span>
          <span>耗时</span>
        </div>
      )}
    </div>
  );
}