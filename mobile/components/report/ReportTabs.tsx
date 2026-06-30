"use client";

import { useState } from "react";
import { PIPELINE_STAGES } from "@/lib/constants";
import type { AnalysisResult } from "@/lib/types";
import { cleanContent } from "@/lib/content";
import { MarkdownRenderer } from "../ui/MarkdownRenderer";

interface ReportTabsProps {
  result: AnalysisResult;
}

const reportStages = PIPELINE_STAGES.filter(
  (s) => s.id !== "quality_gate" && s.id !== "debate" && s.id !== "trader" && s.id !== "risk" && s.id !== "pm"
);

export function ReportTabs({ result }: ReportTabsProps) {
  const [activeTab, setActiveTab] = useState(reportStages[0]?.id ?? "market");

  const activeStage = reportStages.find((s) => s.id === activeTab);
  const reportKey = activeStage?.reportKey ?? "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const rawContent = result.reports ? (result.reports as any)[reportKey] : null;
  const reportContent = cleanContent(rawContent);

  return (
    <div className="space-y-4">
      <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
        {reportStages.map((stage) => {
          const rk = stage.reportKey ?? "";
          const hasContent = result.reports ? !!(result.reports as any)[rk] : false;
          return (
            <button
              key={stage.id}
              onClick={() => setActiveTab(stage.id)}
              className={`
                flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium
                transition-all duration-200
                ${activeTab === stage.id
                  ? "bg-[var(--accent)] text-white shadow-lg shadow-[var(--accent)]/20"
                  : hasContent
                    ? "bg-[var(--bg-card)] text-[var(--text-secondary)]"
                    : "bg-[var(--bg-elevated)] text-[var(--text-muted)] opacity-50"}
              `}
            >
              <span>{stage.icon}</span>
              <span>{stage.name}</span>
            </button>
          );
        })}
      </div>

      <div className="rounded-2xl bg-[var(--bg-card)] border border-[var(--border-subtle)] p-4">
        {reportContent ? (
          <MarkdownRenderer content={reportContent} />
        ) : (
          <div className="flex items-center justify-center h-40 text-[var(--text-muted)] text-sm">
            暂无报告内容
          </div>
        )}
      </div>
    </div>
  );
}