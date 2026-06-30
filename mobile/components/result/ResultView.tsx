"use client";

import { useState } from "react";
import { SignalCard } from "../analyze/SignalCard";
import { StatsBar } from "../report/StatsBar";
import { ReportTabs } from "../report/ReportTabs";
import { DebateView } from "../report/DebateView";
import { RiskView } from "../report/RiskView";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { MarkdownRenderer } from "../ui/MarkdownRenderer";
import { cleanContent } from "@/lib/content";
import { downloadReportPdf } from "@/lib/pdf";
import type { AnalysisResult, ProgressResponse } from "@/lib/types";

interface ResultViewProps {
  result: AnalysisResult;
  progress: ProgressResponse | null;
  onReset: () => void;
}

type Tab = "report" | "debate" | "risk";

export function ResultView({ result, progress, onReset }: ResultViewProps) {
  const [tab, setTab] = useState<Tab>("report");
  const [downloading, setDownloading] = useState(false);

  const finalDecision = cleanContent(
    typeof result.final_trade_decision === "string"
      ? result.final_trade_decision
      : JSON.stringify(result.final_trade_decision, null, 2)
  );

  const traderDecision = cleanContent(
    typeof result.trader_investment_decision === "string"
      ? result.trader_investment_decision
      : JSON.stringify(result.trader_investment_decision, null, 2)
  );

  const handleDownloadPdf = async () => {
    setDownloading(true);
    try {
      await downloadReportPdf(result);
    } catch (e) {
      console.error("PDF download failed:", e);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-4">
      <SignalCard
        signal={result.signal}
        ticker={result.ticker}
        tradeDate={result.trade_date}
        elapsed={result.elapsed}
      />

      <StatsBar stats={result.stats} elapsed={result.elapsed} />

      {finalDecision && (
        <Card
          variant="bordered"
          className="border-l-4"
          style={{ borderLeftColor: "var(--accent)" }}
        >
          <div className="text-xs font-semibold mb-2" style={{ color: "var(--accent)" }}>
            最终决策
          </div>
          <MarkdownRenderer content={finalDecision} />
        </Card>
      )}

      {traderDecision && (
        <Card>
          <div className="text-xs font-semibold mb-2 text-[var(--text-secondary)]">
            交易计划
          </div>
          <MarkdownRenderer content={traderDecision.length > 500 ? traderDecision.slice(0, 500) + "..." : traderDecision} />
        </Card>
      )}

      <div className="flex gap-2">
        {(["report", "debate", "risk"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all ${
              tab === t
                ? "bg-[var(--accent)] text-white shadow-lg shadow-[var(--accent)]/20"
                : "bg-[var(--bg-card)] text-[var(--text-secondary)]"
            }`}
          >
            {t === "report" ? "分析报告" : t === "debate" ? "多空辩论" : "风控评估"}
          </button>
        ))}
      </div>

      {tab === "report" && <ReportTabs result={result} />}
      {tab === "debate" && <DebateView result={result} />}
      {tab === "risk" && <RiskView result={result} />}

      <div className="flex gap-2 pt-2">
        <Button variant="secondary" onClick={onReset} className="flex-1">
          新分析
        </Button>
        <Button
          variant="primary"
          onClick={handleDownloadPdf}
          disabled={downloading}
          className="flex-1"
        >
          {downloading ? "生成中..." : "下载 PDF"}
        </Button>
      </div>
    </div>
  );
}