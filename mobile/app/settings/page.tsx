"use client";

import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { API_BASE } from "@/lib/constants";
import { checkHealth } from "@/lib/api";
import { useState, useEffect } from "react";

export default function SettingsPage() {
  const [apiStatus, setApiStatus] = useState<"checking" | "ok" | "error">("checking");

  useEffect(() => {
    checkHealth()
      .then(() => setApiStatus("ok"))
      .catch(() => setApiStatus("error"));
  }, []);

  return (
    <main className="max-w-lg mx-auto px-4 pt-6 space-y-6 pb-8">
      <h1 className="text-xl font-semibold">设置</h1>

      <Card>
        <div className="text-sm font-medium text-[var(--text-secondary)] mb-3">API 状态</div>
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              apiStatus === "ok"
                ? "bg-green-500"
                : apiStatus === "error"
                  ? "bg-red-500"
                  : "bg-yellow-500"
            }`}
          />
          <span className="text-sm text-[var(--text-muted)]">
            {apiStatus === "ok"
              ? "后端服务正常"
              : apiStatus === "error"
                ? "后端服务不可用"
                : "检查中..."}
          </span>
        </div>
        <div className="mt-2 text-xs text-[var(--text-muted)]">
          API 地址: {API_BASE}
        </div>
      </Card>

      <Card>
        <div className="text-sm font-medium text-[var(--text-secondary)] mb-3">关于</div>
        <div className="space-y-2 text-xs text-[var(--text-muted)]">
          <p>基于 TradingAgents 多 Agent 框架的 A 股深度投研分析</p>
          <p>版本 0.2.11</p>
        </div>
      </Card>
    </main>
  );
}