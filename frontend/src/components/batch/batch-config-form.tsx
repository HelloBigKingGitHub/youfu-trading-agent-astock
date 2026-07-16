import * as React from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

// Date + worker count + advanced LLM options form.
//
// Mirrors `web/components/batch_panel.py` lines 220-241:
//   trade_date   = st.date_input(...)
//   max_workers  = st.number_input(..., max_value=20, value=BATCH_MAX_WORKERS)
//   with st.expander("⚙️  高级(LLM 配置)", expanded=False): _render_llm_config()
//
// The Streamlit page reuses ``_render_llm_config`` from sidebar so the
// React equivalent should match the same fields: provider / deep / quick /
// base URL. We expose only lightweight text inputs here — actual persistence
// lives in ⚙️ Settings, but the batch API accepts per-job LLM overrides so
// the user can paste a different provider inline without leaving the page.

export interface LLMSettings {
  provider: string;
  deepModel: string;
  quickModel: string;
  baseUrl: string;
}

export interface BatchConfig {
  tradeDate: string;        // YYYY-MM-DD
  maxWorkers: number;       // 1..20
  llm: LLMSettings;
}

export interface BatchConfigFormProps {
  value: BatchConfig;
  onChange: (next: BatchConfig) => void;
}

const todayIso = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export function BatchConfigForm({ value, onChange }: BatchConfigFormProps) {
  function patch(p: Partial<BatchConfig>) {
    onChange({ ...value, ...p });
  }
  function patchLlm(p: Partial<LLMSettings>) {
    onChange({ ...value, llm: { ...value.llm, ...p } });
  }

  return (
    <div className="space-y-4" data-testid="batch-config-form">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="batch-trade-date">分析日期</Label>
          <Input
            id="batch-trade-date"
            type="date"
            value={value.tradeDate || todayIso()}
            onChange={(e) => patch({ tradeDate: e.target.value })}
            data-testid="batch-trade-date"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="batch-max-workers">并发 worker 数</Label>
          <Input
            id="batch-max-workers"
            type="number"
            min={1}
            max={20}
            step={1}
            value={value.maxWorkers}
            onChange={(e) => {
              const n = parseInt(e.target.value, 10);
              if (!Number.isNaN(n)) {
                patch({ maxWorkers: Math.min(20, Math.max(1, n)) });
              }
            }}
            data-testid="batch-max-workers"
          />
          <p className="text-xs text-text-tertiary">
            同一时间最多跑几个 job (后端 ThreadPoolExecutor 大小)。
          </p>
        </div>
      </div>

      <details className="rounded-md border border-border-1 bg-bg-elevated/40" data-testid="batch-llm-advanced">
        <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-text-primary">
          ⚙️ 高级(LLM 配置) — 留空则走 ⚙️ 设置
        </summary>
        <div className="grid grid-cols-1 gap-4 p-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="batch-llm-provider">LLM 供应商</Label>
            <Input
              id="batch-llm-provider"
              type="text"
              placeholder="minimax"
              value={value.llm.provider}
              onChange={(e) => patchLlm({ provider: e.target.value })}
              data-testid="batch-llm-provider"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batch-llm-base-url">Base URL</Label>
            <Input
              id="batch-llm-base-url"
              type="text"
              placeholder="https://..."
              value={value.llm.baseUrl}
              onChange={(e) => patchLlm({ baseUrl: e.target.value })}
              data-testid="batch-llm-base-url"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batch-llm-deep">深度模型</Label>
            <Input
              id="batch-llm-deep"
              type="text"
              placeholder="MiniMax-M3"
              value={value.llm.deepModel}
              onChange={(e) => patchLlm({ deepModel: e.target.value })}
              data-testid="batch-llm-deep"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="batch-llm-quick">快速模型</Label>
            <Input
              id="batch-llm-quick"
              type="text"
              placeholder="MiniMax-M2.7-highspeed"
              value={value.llm.quickModel}
              onChange={(e) => patchLlm({ quickModel: e.target.value })}
              data-testid="batch-llm-quick"
            />
          </div>
        </div>
      </details>
    </div>
  );
}