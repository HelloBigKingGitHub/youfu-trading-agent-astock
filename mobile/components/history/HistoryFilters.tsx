"use client";

import { useState } from "react";
import { Button } from "../ui/Button";

interface HistoryFiltersProps {
  onSearch: (filters: { ticker: string; signal: string; status: string }) => void;
  isLoading?: boolean;
}

const SIGNAL_OPTIONS = ["", "Buy", "Sell", "Hold", "Overweight", "Underweight"];
const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "completed", label: "已完成" },
  { value: "error", label: "失败" },
  { value: "running", label: "进行中" },
];

export function HistoryFilters({ onSearch, isLoading }: HistoryFiltersProps) {
  const [ticker, setTicker] = useState("");
  const [signal, setSignal] = useState("");
  const [status, setStatus] = useState("");

  const handleSearch = () => {
    onSearch({ ticker, signal, status });
  };

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="搜索股票代码..."
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase().slice(0, 6))}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          className="flex-1 px-4 py-2.5 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)] text-white placeholder:text-[var(--text-muted)] text-sm focus:outline-none focus:border-[var(--accent)]"
        />
        <Button
          variant="primary"
          size="sm"
          onClick={handleSearch}
          disabled={isLoading}
        >
          搜索
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
       <span className="text-xs text-[var(--text-muted)] self-center mr-1">信号:</span>
        {SIGNAL_OPTIONS.map((s) => (
          <button
            key={s || "all"}
            onClick={() => { setSignal(s); }}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
              signal === s
                ? s === "Buy" ? "bg-green-500/20 text-green-400 border border-green-500/40"
                  : s === "Sell" ? "bg-red-500/20 text-red-400 border border-red-500/40"
                  : s === "Hold" ? "bg-yellow-500/20 text-yellow-400 border border-yellow-500/40"
                  : "bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40"
                : "bg-[var(--bg-elevated)] text-[var(--text-muted)] border border-transparent"
            }`}
          >
            {s || "全部"}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <span className="text-xs text-[var(--text-muted)] self-center mr-1">状态:</span>
        {STATUS_OPTIONS.map((opt) => (
          <button
            key={opt.value || "all"}
            onClick={() => setStatus(opt.value)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
              status === opt.value
                ? "bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40"
                : "bg-[var(--bg-elevated)] text-[var(--text-muted)] border border-transparent"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}