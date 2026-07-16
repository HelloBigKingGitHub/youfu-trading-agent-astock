import * as React from 'react';
import { Search, RefreshCw, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Label } from '@/components/ui/label';

// Mirrors web/components/history_panel.py render_filters() — 3 cols
// (ticker / signal / status) + 搜索 + 刷新. The 全部/Buy/Sell/Hold/...
// options map exactly to streamlit's signal_filter selectbox; the status
// map mirrors status_map = {"全部":"","已完成":"completed",...}.

export interface HistoryFilters {
  ticker: string;
  signal: string;
  status: string;
}

export const EMPTY_FILTERS: HistoryFilters = {
  ticker: '',
  signal: '',
  status: '',
};

interface FilterBarProps {
  value: HistoryFilters;
  onChange: (next: HistoryFilters) => void;
  onRefresh: () => void;
  onSearch: () => void;
  isFetching?: boolean;
  total: number;
}

const SIGNAL_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'Buy', label: 'Buy · 买入' },
  { value: 'Sell', label: 'Sell · 卖出' },
  { value: 'Hold', label: 'Hold · 持有' },
  { value: 'Overweight', label: 'Overweight · 超配' },
  { value: 'Underweight', label: 'Underweight · 低配' },
];

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'completed', label: '已完成' },
  { value: 'error', label: '失败' },
  { value: 'running', label: '进行中' },
  { value: 'pending', label: '等待' },
];

export function FilterBar({
  value,
  onChange,
  onRefresh,
  onSearch,
  isFetching,
  total,
}: FilterBarProps) {
  function update<K extends keyof HistoryFilters>(key: K, next: HistoryFilters[K]) {
    onChange({ ...value, [key]: next });
  }

  return (
    <div
      data-testid="history-filter-bar"
      className="grid grid-cols-1 gap-4 sm:grid-cols-[2fr_1fr_1fr_auto_auto] items-end"
    >
      <div className="flex flex-col gap-2">
        <Label htmlFor="filter-ticker">股票代码</Label>
        <Input
          id="filter-ticker"
          data-testid="filter-ticker"
          placeholder="搜索 ticker…"
          value={value.ticker}
          onChange={(e) => update('ticker', e.target.value.toUpperCase())}
        />
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="filter-signal">信号</Label>
        <Select
          id="filter-signal"
          data-testid="filter-signal"
          value={value.signal}
          onChange={(e) => update('signal', e.target.value)}
        >
          {SIGNAL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="filter-status">状态</Label>
        <Select
          id="filter-status"
          data-testid="filter-status"
          value={value.status}
          onChange={(e) => update('status', e.target.value)}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>

      <Button
        type="button"
        variant="default"
        data-testid="filter-search"
        onClick={onSearch}
        disabled={isFetching}
      >
        <Search className="h-4 w-4" />
        搜索
      </Button>

      <Button
        type="button"
        variant="outline"
        data-testid="filter-refresh"
        onClick={onRefresh}
        disabled={isFetching}
        title={`当前 ${total} 条记录（刷新即时生效）`}
      >
        {isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        刷新
      </Button>
    </div>
  );
}
