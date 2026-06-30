"use client";

import type { AnalysisResult } from "@/lib/types";
import { Card } from "../ui/Card";

interface DebateViewProps {
  result: AnalysisResult;
}

export function DebateView({ result }: DebateViewProps) {
  const debate = result.investment_debate_state;
  if (!debate) return null;

  const bull = debate.bull_history || "";
  const bear = debate.bear_history || "";
  const verdict = debate.judge_decision || "";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <Card variant="bordered" className="border-green-500/20">
          <div className="text-xs text-green-400 font-medium mb-2">多头 🐂</div>
          <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
            {bull}
          </pre>
        </Card>
        <Card variant="bordered" className="border-red-500/20">
          <div className="text-xs text-red-400 font-medium mb-2">空头 🐻</div>
          <pre className="text-xs text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">
            {bear}
          </pre>
        </Card>
      </div>

      <Card variant="bordered" className="border-[var(--accent)]/30">
        <div className="text-xs text-[var(--accent)] font-medium mb-2">裁判裁决 ⚖️</div>
        <pre className="text-sm text-[var(--text-secondary)] whitespace-pre-wrap leading-relaxed">
          {verdict}
        </pre>
      </Card>
    </div>
  );
}