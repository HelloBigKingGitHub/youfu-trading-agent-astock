import * as React from 'react';
import { CHART_RANGES, DEFAULT_RANGE, DEFAULT_TICKER, type ChartRange } from '@/api/chart';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface TickerInputProps {
  ticker?: string;
  range?: ChartRange;
  error?: string | null;
  onChange: (ticker: string, range: ChartRange) => void;
}

/** Ticker + time-range controls shared by the chart page and parity probes. */
export function TickerInput({
  ticker = DEFAULT_TICKER,
  range = DEFAULT_RANGE,
  error,
  onChange,
}: TickerInputProps) {
  const [draftTicker, setDraftTicker] = React.useState(ticker);
  const [draftRange, setDraftRange] = React.useState<ChartRange>(range);

  React.useEffect(() => setDraftTicker(ticker), [ticker]);
  React.useEffect(() => setDraftRange(range), [range]);

  function handleTickerChange(event: React.ChangeEvent<HTMLInputElement>) {
    const next = event.target.value.replace(/\D/g, '').slice(0, 6);
    setDraftTicker(next);
    if (next.length === 6) onChange(next, draftRange);
  }

  function handleRangeChange(nextRange: ChartRange) {
    setDraftRange(nextRange);
    onChange(draftTicker, nextRange);
  }

  const localError = draftTicker.length > 0 && draftTicker.length < 6
    ? '请输入 6 位股票代码'
    : error;

  return (
    <div data-testid="chart-ticker-input" className="space-y-2">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <label className="block w-full max-w-xs space-y-1.5 text-sm text-text-secondary">
          <span>股票代码</span>
          <Input
            aria-label="股票代码"
            type="text"
            inputMode="numeric"
            maxLength={6}
            value={draftTicker}
            onChange={handleTickerChange}
            placeholder="600595"
            autoComplete="off"
          />
        </label>
        <div className="flex flex-wrap gap-2" aria-label="时间范围">
          {CHART_RANGES.map((item) => (
            <Button
              key={item}
              type="button"
              size="sm"
              variant={draftRange === item ? 'default' : 'outline'}
              aria-pressed={draftRange === item}
              data-testid={`chart-range-${item}`}
              onClick={() => handleRangeChange(item)}
            >
              {item}
            </Button>
          ))}
        </div>
      </div>
      {localError && (
        <p className="text-sm text-bb-up" role="alert" data-testid="chart-ticker-error">
          {localError}
        </p>
      )}
    </div>
  );
}

export default TickerInput;
