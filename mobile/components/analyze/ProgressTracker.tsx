"use client";

import { PIPELINE_STAGES } from "@/lib/constants";
import type { ProgressResponse } from "@/lib/types";

interface ProgressTrackerProps {
  progress: ProgressResponse;
}

export function ProgressTracker({ progress }: ProgressTrackerProps) {
  const { current_stage, completed_stages = [], stats } = progress;
  const currentIndex = PIPELINE_STAGES.findIndex((s) => s.id === current_stage);

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex justify-between text-xs text-[var(--text-muted)]">
          <span>{PIPELINE_STAGES[currentIndex]?.name || current_stage}</span>
          <span>{currentIndex + 1} / {PIPELINE_STAGES.length}</span>
        </div>
        <div className="h-1.5 bg-[var(--bg-elevated)] rounded-full overflow-hidden">
          <div
            className="h-full bg-[var(--accent)] transition-all duration-500 rounded-full"
            style={{ width: `${((currentIndex + 1) / PIPELINE_STAGES.length) * 100}%` }}
          />
        </div>
      </div>

      <div className="flex gap-1.5 overflow-x-auto pb-1 no-scrollbar">
        {PIPELINE_STAGES.map((stage, i) => {
          const isDone = completed_stages.includes(stage.id);
          const isCurrent = stage.id === current_stage;
          const isPending = !isDone && !isCurrent;

          return (
            <div
              key={stage.id}
              className={`
                flex-shrink-0 flex flex-col items-center gap-1
                transition-all duration-300
              `}
            >
              <div
                className={`
                  w-8 h-8 rounded-full flex items-center justify-center text-sm
                  transition-all duration-300
                  ${isDone ? "bg-[var(--signal-buy)] text-white" : ""}
                  ${isCurrent ? "bg-[var(--accent)] text-white scale-110" : ""}
                  ${isPending ? "bg-[var(--bg-elevated)] text-[var(--text-muted)]" : ""}
                `}
              >
                {isDone ? "✓" : stage.icon}
              </div>
              <span className={`
                text-[10px] whitespace-nowrap
                ${isCurrent ? "text-[var(--accent)] font-medium" : "text-[var(--text-muted)]"}
                ${isDone ? "text-[var(--signal-buy)]" : ""}
              `}>
                {stage.name}
              </span>
            </div>
          );
        })}
      </div>

      {stats && (
        <div className="flex justify-around text-xs text-[var(--text-muted)] border-t border-[var(--border-subtle)] pt-3">
          <div className="flex flex-col items-center">
            <span className="text-[var(--text-secondary)] font-medium">{stats.llm_calls ?? 0}</span>
            <span>LLM调用</span>
          </div>
          <div className="flex flex-col items-center">
            <span className="text-[var(--text-secondary)] font-medium">{stats.tool_calls ?? 0}</span>
            <span>工具调用</span>
          </div>
          <div className="flex flex-col items-center">
            <span className="text-[var(--text-secondary)] font-medium">{stats.tokens_in ?? 0}</span>
            <span>输入Token</span>
          </div>
          <div className="flex flex-col items-center">
            <span className="text-[var(--text-secondary)] font-medium">{stats.tokens_out ?? 0}</span>
            <span>输出Token</span>
          </div>
        </div>
      )}
    </div>
  );
}