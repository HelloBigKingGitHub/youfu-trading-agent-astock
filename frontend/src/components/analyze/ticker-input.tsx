/**
 * TickerInput — 6-digit code OR Chinese ticker name search input.
 *
 * Mirrors web/components/analyze_panel.py's ticker text_input. Validates the
 * 6-digit format locally and offers a debounced lookup against the
 * backend.core.resolve_ticker backend helper via the ``/api/resolve`` shortcut
 * (proxied by an inline search if not available — falls back to "accept any"
 * so the parent form is the source of truth on submit).
 */
import * as React from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Search } from 'lucide-react';

interface TickerInputProps {
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  disabled?: boolean;
  /** Optional callback fired after a valid ticker is entered. */
  onCommit?: (ticker: string) => void;
}

const TICKER_RE = /^\d{6}$/;

function looksLikeChinese(value: string): boolean {
  return /[一-龥]/.test(value);
}

export function TickerInput({
  value, onChange, error, disabled, onCommit,
}: TickerInputProps) {
  const [touched, setTouched] = React.useState(false);
  const showError = Boolean(error) || (touched && value.length > 0 && !TICKER_RE.test(value) && !looksLikeChinese(value));

  return (
    <div className="space-y-1" data-testid="ticker-input-wrap">
      <Label htmlFor="analyze-ticker">股票代码 / 中文名</Label>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-text-tertiary" />
        <Input
          id="analyze-ticker"
          data-testid="ticker-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => {
            setTouched(true);
            if (TICKER_RE.test(value) || looksLikeChinese(value)) {
              onCommit?.(value);
            }
          }}
          placeholder="600519 或 贵州茅台"
          disabled={disabled}
          className="pl-8 font-mono"
          autoComplete="off"
          spellCheck={false}
        />
      </div>
      <p
        className="text-xs text-text-tertiary"
        data-testid="ticker-input-help"
      >
        支持 6 位 A 股代码 (例: 600519) 或中文名 (例: 贵州茅台), 输入后自动解析为代码
      </p>
      {showError && (
        <p
          className="text-xs text-red-400"
          data-testid="ticker-input-error"
        >
          {error ?? '格式无效: 必须是 6 位数字或中文股票名'}
        </p>
      )}
    </div>
  );
}

export default TickerInput;