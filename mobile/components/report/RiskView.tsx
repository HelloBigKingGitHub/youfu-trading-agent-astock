"use client";

import type { AnalysisResult } from "@/lib/types";
import { Card } from "../ui/Card";

interface RiskViewProps {
  result: AnalysisResult;
}

export function RiskView({ result }: RiskViewProps) {
  const risk = result.risk_debate_state;
  if (!risk) return null;

  const aggressive = risk.aggressive_history || "";
  const conservative = risk.conservative_history || "";
  const neutral = risk.neutral_history || "";
  const verdict = risk.judge_decision || "";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3">
        <Card variant="bordered" className="border-green-500/20">
          <div className="text-xs text-green-400 font-medium mb-2">风险偏好 🛡️</div>
          <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">
            {aggressive}
          </pre>
        </Card>
        <Card variant="bordered" className="border-yellow-500/20">
          <div className="text-xs text-yellow-400 font-medium mb-2">风险规避 ⚠️</div>
          <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">
            {conservative}
          </pre>
        </Card>
        <Card variant="bordered" className="border-blue-500/20">
          <div className="text-xs text-blue-400 font-medium mb-2">中性观点</div>
          <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">
            {neutral}
          </pre>
        </Card>
      </div>

      <Card variant="bordered" className="border-[var(--accent)]/30">
        <div className="text-xs text-[var(--accent)] font-medium mb-2">风险裁决</div>
        <pre className="text-sm text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed">
          {verdict}
        </pre>
      </Card>
    </div>
  );
}