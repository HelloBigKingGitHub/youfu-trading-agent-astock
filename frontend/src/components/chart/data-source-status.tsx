import * as React from 'react';
import type { DataSource } from '@/api/chart';

interface DataSourceStatusProps {
  source: DataSource | string;
  cached?: boolean;
  cacheTimestamp?: number | string | null;
}

function formatTimestamp(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === '') return '—';
  const date = typeof value === 'number' ? new Date(value) : new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN');
}

/** Displays which historical-data fallback/cache supplied the current chart. */
export function DataSourceStatus({ source, cached = false, cacheTimestamp }: DataSourceStatusProps) {
  const sourceLabel = source || 'empty';
  const isEmpty = sourceLabel === 'empty';
  return (
    <div
      data-testid="data-source-status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-secondary"
      aria-label="数据来源"
    >
      <span className="inline-flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${isEmpty ? 'bg-bb-up' : 'bg-bb-down'}`} aria-hidden />
        数据来源：<strong className="font-mono font-medium text-text-primary">{sourceLabel}</strong>
      </span>
      {cached && <span>缓存：是</span>}
      <span>缓存时间：{formatTimestamp(cacheTimestamp)}</span>
    </div>
  );
}

export default DataSourceStatus;
