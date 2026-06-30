"use client";

import { useState, FormEvent } from "react";

interface AnalyzeFormProps {
  onSubmit: (data: { ticker: string; trade_date: string }) => void;
  isLoading?: boolean;
  error?: string;
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function AnalyzeForm({ onSubmit, isLoading, error }: AnalyzeFormProps) {
  const [ticker, setTicker] = useState("");
  const [tradeDate, setTradeDate] = useState(today);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!ticker.trim() || !tradeDate.trim()) return;
    onSubmit({ ticker: ticker.trim().toUpperCase(), trade_date: tradeDate.trim() });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium" style={{ color: "#888" }}>股票代码</label>
        <input
          type="text"
          inputMode="numeric"
          placeholder="例如: 000001"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.replace(/\D/g, "").slice(0, 6))}
          maxLength={6}
          className="w-full px-4 py-3 rounded-xl text-base text-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-orange-500 transition-colors duration-200"
          style={{ backgroundColor: "#161616", border: "1px solid #222" }}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-sm font-medium" style={{ color: "#888" }}>交易日期</label>
        <input
          type="text"
          placeholder="格式: 2026-06-01"
          value={tradeDate}
          onChange={(e) => setTradeDate(e.target.value)}
          className="w-full px-4 py-3 rounded-xl text-base text-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-orange-500 transition-colors duration-200"
          style={{ backgroundColor: "#161616", border: "1px solid #222" }}
        />
      </div>
      {error && (
        <p className="text-xs text-red-500">{error}</p>
      )}
      <button
        type="submit"
        disabled={isLoading || !ticker || !tradeDate}
        className="w-full py-3 rounded-xl text-white text-base font-medium shadow-lg transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.97]"
        style={{ backgroundColor: "#ff5a1f" }}
      >
        {isLoading ? "分析中..." : "开始分析"}
      </button>
    </form>
  );
}