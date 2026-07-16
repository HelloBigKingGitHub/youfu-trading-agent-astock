/**
 * AnalysisForm — single-stock analysis submission form.
 *
 * Mirrors web/components/analyze_panel.py::render_analyze_panel form block.
 * Fields: ticker (6-digit OR Chinese) + trade_date + llm_provider +
 * quick_think_llm + deep_think_llm. Submits to POST /api/analyze.
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { TickerInput } from './ticker-input';
import type { AnalyzeRequest } from '@/api/analyze';

interface AnalysisFormProps {
  onSubmit: (payload: AnalyzeRequest) => Promise<void>;
  isSubmitting?: boolean;
  errorMessage?: string | null;
  initialTicker?: string;
  initialDate?: string;
}

const PROVIDERS = ['minimax', 'openai', 'deepseek', 'qwen', 'anthropic'];
const QUICK_MODELS = ['MiniMax-M2.7-highspeed', 'MiniMax-M3', 'gpt-4o-mini', 'deepseek-chat'];
const DEEP_MODELS = ['MiniMax-M2.7', 'MiniMax-M3', 'gpt-4o', 'deepseek-reasoner', 'claude-sonnet-4'];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function AnalysisForm({
  onSubmit, isSubmitting, errorMessage, initialTicker, initialDate,
}: AnalysisFormProps) {
  const [ticker, setTicker] = React.useState(initialTicker ?? '');
  const [tradeDate, setTradeDate] = React.useState(initialDate ?? todayIso());
  const [provider, setProvider] = React.useState('minimax');
  const [quickModel, setQuickModel] = React.useState('MiniMax-M2.7-highspeed');
  const [deepModel, setDeepModel] = React.useState('MiniMax-M2.7');
  const [localError, setLocalError] = React.useState<string | null>(null);

  function validate(): string | null {
    if (!ticker.trim()) return '股票代码不能为空';
    if (!/^\d{6}$/.test(ticker.trim()) && !/[一-龥]/.test(ticker)) {
      return '股票代码必须是 6 位数字或中文名';
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(tradeDate)) return '交易日期必须是 YYYY-MM-DD 格式';
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const err = validate();
    if (err) {
      setLocalError(err);
      return;
    }
    setLocalError(null);
    await onSubmit({
      ticker: ticker.trim(),
      trade_date: tradeDate.trim(),
      llm_provider: provider,
      quick_think_llm: quickModel,
      deep_think_llm: deepModel,
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      data-testid="analysis-form"
      className="space-y-4 rounded-md border border-border-1 bg-bg-elevated/40 p-4"
    >
      <TickerInput
        value={ticker}
        onChange={(v) => { setTicker(v); setLocalError(null); }}
        error={localError}
        disabled={isSubmitting}
      />

      <div className="space-y-1">
        <Label htmlFor="analyze-date">交易日期</Label>
        <Input
          id="analyze-date"
          type="date"
          data-testid="analysis-form-date"
          value={tradeDate}
          onChange={(e) => setTradeDate(e.target.value)}
          disabled={isSubmitting}
          required
        />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="analyze-provider">LLM 供应商</Label>
          <select
            id="analyze-provider"
            data-testid="analysis-form-provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={isSubmitting}
            className="w-full rounded-md border border-border-1 bg-bg-elevated px-3 py-2 text-sm"
          >
            {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="analyze-quick">快速思考模型</Label>
          <select
            id="analyze-quick"
            data-testid="analysis-form-quick"
            value={quickModel}
            onChange={(e) => setQuickModel(e.target.value)}
            disabled={isSubmitting}
            className="w-full rounded-md border border-border-1 bg-bg-elevated px-3 py-2 text-sm"
          >
            {QUICK_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="analyze-deep">深度思考模型</Label>
          <select
            id="analyze-deep"
            data-testid="analysis-form-deep"
            value={deepModel}
            onChange={(e) => setDeepModel(e.target.value)}
            disabled={isSubmitting}
            className="w-full rounded-md border border-border-1 bg-bg-elevated px-3 py-2 text-sm"
          >
            {DEEP_MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      </div>

      {(errorMessage || localError) && (
        <div
          className="rounded-md border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-300"
          data-testid="analysis-form-error"
        >
          {localError ?? errorMessage}
        </div>
      )}

      <div className="flex justify-end">
        <Button
          type="submit"
          size="sm"
          disabled={isSubmitting}
          data-testid="analysis-form-submit"
        >
          {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : '🚀'}
          开始分析
        </Button>
      </div>
    </form>
  );
}

export default AnalysisForm;