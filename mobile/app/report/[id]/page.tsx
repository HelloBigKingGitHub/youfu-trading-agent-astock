"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { ReportTabs } from "@/components/report/ReportTabs";
import { DebateView } from "@/components/report/DebateView";
import { RiskView } from "@/components/report/RiskView";
import { StatsBar } from "@/components/report/StatsBar";
import { SignalCard } from "@/components/analyze/SignalCard";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { getResult } from "@/lib/api";
import type { AnalysisResult } from "@/lib/types";

export default function ReportPage({ params }: { params: { id: string } }) {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"report" | "debate" | "risk">("report");

  useEffect(() => {
    getResult(params.id)
      .then(setResult)
      .catch((e) => setError(e instanceof Error ? e.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [params.id]);

  if (loading) {
    return (
      <main className="max-w-lg mx-auto px-4 pt-6">
        <div className="flex items-center justify-center h-64">
          <div className="text-[var(--text-muted)]">加载中...</div>
        </div>
      </main>
    );
  }

  if (error || !result) {
    return (
      <main className="max-w-lg mx-auto px-4 pt-6">
        <Card>
          <p className="text-sm text-red-400">{error || "报告不存在"}</p>
          <Button variant="ghost" onClick={() => history.back()} className="mt-3">
            返回
          </Button>
        </Card>
      </main>
    );
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-6 space-y-4 pb-8">
      <SignalCard
        signal={result.signal}
        ticker={result.ticker}
        tradeDate={result.trade_date}
        elapsed={result.elapsed}
      />
      <StatsBar stats={result.stats} elapsed={result.elapsed} />

      <div className="flex gap-2">
        {[
          { key: "report", label: "分析报告" },
          { key: "debate", label: "多空辩论" },
          { key: "risk", label: "风控评估" },
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as typeof activeTab)}
            className={`
              flex-1 py-2 rounded-xl text-sm font-medium transition-all
              ${activeTab === tab.key
                ? "bg-[var(--accent)] text-white"
                : "bg-[var(--bg-card)] text-[var(--text-muted)]"}
            `}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "report" && <ReportTabs result={result} />}
      {activeTab === "debate" && <DebateView result={result} />}
      {activeTab === "risk" && <RiskView result={result} />}
    </main>
  );
}