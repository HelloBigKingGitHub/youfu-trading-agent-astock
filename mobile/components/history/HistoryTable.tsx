"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "../ui/Badge";
import type { HistoryItem } from "@/lib/types";

interface HistoryTableProps {
  items: HistoryItem[];
  onDelete: (analysisId: string) => void;
  isDeleting?: string | null;
}

const SIGNAL_VARIANTS: Record<string, "buy" | "sell" | "hold" | "overweight" | "underweight" | "default"> = {
  Buy: "buy",
  Sell: "sell",
  Hold: "hold",
  Overweight: "overweight",
  Underweight: "underweight",
};

const STATUS_LABELS: Record<string, string> = {
  completed: "已完成",
  error: "失败",
  running: "进行中",
};

export function HistoryTable({ items, onDelete, isDeleting }: HistoryTableProps) {
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-[var(--text-muted)]">
        <span className="text-4xl mb-3">📋</span>
        <p className="text-sm">暂无历史记录</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div
          key={item.analysis_id}
          className="bg-[var(--bg-card)] rounded-xl p-4 border border-[var(--border-subtle)] hover:border-[var(--accent)]/30 transition-colors"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className="font-semibold text-[var(--text-primary)] text-base">
                  {item.ticker}
                </span>
                {item.signal && (
                  <Badge variant={SIGNAL_VARIANTS[item.signal] ?? "default"}>
                    {item.signal}
                  </Badge>
                )}
                {item.status && (
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    item.status === "completed" ? "bg-green-500/10 text-green-400"
                    : item.status === "error" ? "bg-red-500/10 text-red-400"
                    : "bg-blue-500/10 text-blue-400"
                  }`}>
                    {STATUS_LABELS[item.status] ?? item.status}
                  </span>
                )}
              </div>
              <div className="text-xs text-[var(--text-muted)] space-y-0.5">
                <div>{item.trade_date}</div>
                <div className="flex gap-3">
                  <span>耗时 {item.elapsed.toFixed(1)}s</span>
                  {item.completed_stages && item.completed_stages.length > 0 && (
                    <span>{item.completed_stages.length} 个阶段</span>
                  )}
                </div>
                {item.error && (
                  <div className="text-red-400 truncate max-w-[200px]">{item.error}</div>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              {confirmDelete === item.analysis_id ? (
                <>
                  <button
                    onClick={() => { onDelete(item.analysis_id); setConfirmDelete(null); }}
                    disabled={isDeleting === item.analysis_id}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/40 transition-colors disabled:opacity-50"
                  >
                    {isDeleting === item.analysis_id ? "删除中..." : "确认"}
                  </button>
                  <button
                    onClick={() => setConfirmDelete(null)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--bg-elevated)] text-[var(--text-muted)] transition-colors"
                  >
                    取消
                  </button>
                </>
              ) : (
                <>
                  <Link
                    href={`/report/${item.analysis_id}`}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30 hover:bg-[var(--accent)]/20 transition-colors"
                  >
                    查看
                  </Link>
                  <button
                    onClick={() => setConfirmDelete(item.analysis_id)}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-red-400 transition-colors"
                  >
                    删除
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}