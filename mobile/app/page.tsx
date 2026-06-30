"use client";

import { useState, useCallback } from "react";
import { AnalyzeForm } from "@/components/analyze/AnalyzeForm";
import { ProgressTracker } from "@/components/analyze/ProgressTracker";
import { Card } from "@/components/ui/Card";
import { ResultView } from "@/components/result/ResultView";
import { startAnalysis, pollProgress, getResult } from "@/lib/api";
import type { ProgressResponse, AnalysisResult, AnalyzeResponse } from "@/lib/types";

export default function AnalyzePage() {
  const [phase, setPhase] = useState<"idle" | "running" | "done" | "error">("idle");
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = useCallback(async (data: { ticker: string; trade_date: string }) => {
    setFormError(null);
    setError(null);
    setResult(null);
    setProgress(null);

    try {
      const resp: AnalyzeResponse = await startAnalysis(data);
      setAnalysisId(resp.analysis_id);
      setPhase("running");

      const poll = async () => {
        const p: ProgressResponse = await pollProgress(resp.analysis_id);
        setProgress(p);
        if (p.status === "complete" || p.status === "error") {
          clearInterval(timer);
          if (p.status === "complete") {
            try {
              const r: AnalysisResult = await getResult(resp.analysis_id);
              setResult(r);
              setPhase("done");
            } catch {
              setPhase("error");
              setError("获取结果失败");
            }
          } else {
            setPhase("error");
            setError(p.error || "分析失败");
          }
        }
      };

      await poll();
      const timer = setInterval(poll, 2000);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "启动分析失败");
    }
  }, []);

  if (phase === "done" && result) {
    return (
      <main className="max-w-lg mx-auto px-4 pt-6 pb-8 space-y-4">
        <ResultView
          result={result}
          progress={progress}
          onReset={() => {
            setPhase("idle");
            setResult(null);
            setProgress(null);
          }}
        />
      </main>
    );
  }

  if (phase === "running" && progress) {
    return (
      <main className="max-w-lg mx-auto px-4 pt-6 space-y-4">
        <div className="text-center mb-2">
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">分析中</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">股票 {progress.ticker || "..."}</p>
        </div>
        <ProgressTracker progress={progress} />
        {progress.status === "error" && (
          <Card>
            <p className="text-sm text-red-400">{progress.error || "分析出错"}</p>
          </Card>
        )}
      </main>
    );
  }

  if (phase === "error") {
    return (
      <main className="max-w-lg mx-auto px-4 pt-6 space-y-4">
        <Card>
          <p className="text-sm text-red-400">{error || "分析出错"}</p>
        </Card>
        <button
          onClick={() => { setPhase("idle"); setError(null); }}
          className="w-full py-3 text-sm text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
        >
          重试
        </button>
      </main>
    );
  }

  return (
    <main className="max-w-lg mx-auto px-4 pt-8">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold tracking-tight mb-2">
          <span style={{ color: "var(--accent)" }}>A股</span>分析
        </h1>
        <p className="text-sm text-[var(--text-muted)]">多 Agent 深度投研分析</p>
      </div>
      <Card variant="elevated" className="mb-6">
        <AnalyzeForm onSubmit={handleSubmit} isLoading={phase === "running"} error={formError || undefined} />
      </Card>
      <div className="grid grid-cols-3 gap-3 text-center">
        {[
          { icon: "📊", label: "技术分析" },
          { icon: "💬", label: "情绪分析" },
          { icon: "📰", label: "新闻舆情" },
        ].map((f) => (
          <div key={f.label} className="bg-[var(--bg-card)] rounded-xl p-3">
            <div className="text-xl mb-1">{f.icon}</div>
            <div className="text-xs text-[var(--text-muted)]">{f.label}</div>
          </div>
        ))}
      </div>
    </main>
  );
}