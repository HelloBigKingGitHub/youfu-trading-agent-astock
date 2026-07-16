import * as React from 'react';
import { parseTickerList } from '@/api/batch';

// Multi-line ticker textarea.
//
// Mirrors `web/components/batch_panel.py` lines 212-218:
//   st.text_area("股票列表(逗号或换行分隔)", value=..., height=120, help=...)
//
// Live-previews parsed count + invalid list so the user can fix typos before
// hitting "开始批量分析" — matches the Streamlit post-submit error message
// but surfaces it inline.

export interface TickerInputProps {
  value: string;
  onChange: (next: string) => void;
}

export function TickerInput({ value, onChange }: TickerInputProps) {
  const { clean, invalid } = React.useMemo(() => parseTickerList(value), [value]);
  const helpId = 'ticker-input-help';

  return (
    <div className="space-y-2" data-testid="ticker-input">
      <label
        htmlFor="batch-tickers-textarea"
        className="text-sm font-medium text-text-primary"
      >
        股票列表(逗号或换行分隔)
      </label>
      <textarea
        id="batch-tickers-textarea"
        rows={6}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={'688017\n600519\n000001'}
        data-testid="batch-tickers-textarea"
        aria-describedby={helpId}
        className="flex w-full rounded-md border border-border-1 bg-bg-elevated px-3 py-2 text-sm font-mono text-text-primary placeholder:text-text-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bb-accent focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50"
      />
      <div id={helpId} className="flex flex-wrap gap-3 text-xs text-text-secondary">
        <span data-testid="ticker-count">
          ✓ 已识别 <strong className="text-text-primary">{clean.length}</strong> 个
        </span>
        {invalid.length > 0 && (
          <span className="text-bb-down" data-testid="ticker-invalid">
            ⚠️ 非法 {invalid.length} 个: {invalid.slice(0, 5).join(', ')}
            {invalid.length > 5 ? ' …' : ''}
          </span>
        )}
        <span className="text-text-tertiary">
          6 位 A 股代码,沪市 60x/688,深市 000/001/002/003,创业板 300/301,北交所 430。
        </span>
      </div>
    </div>
  );
}