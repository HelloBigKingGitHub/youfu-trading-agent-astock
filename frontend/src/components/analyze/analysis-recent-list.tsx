/**
 * AnalysisRecentList — 最近分析列表 tab. Mirrors history_panel.py list view.
 *
 * Renders the recent analyses from GET /api/analyze/recent?limit=20, plus a
 * selectable highlight that the parent AnalyzePage uses to drive the
 * report tab drill-down.
 */
import * as React from 'react';
import { Loader2, ChevronRight } from 'lucide-react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import type { RecentAnalyzeItem } from '@/api/analyze';

interface AnalysisRecentListProps {
  items: RecentAnalyzeItem[];
  isLoading?: boolean;
  error?: string | null;
  selectedId?: string | null;
  onSelect?: (analysisId: string) => void;
}

function statusColor(s: string | null): string {
  switch (s) {
    case 'ok':
    case 'complete':
      return 'text-emerald-400';
    case 'error': return 'text-red-400';
    case 'running': return 'text-amber-400';
    default: return 'text-text-secondary';
  }
}

function fmtTs(createdAt: string): string {
  const num = Number(createdAt);
  if (!Number.isFinite(num) || num <= 0) return createdAt;
  const d = new Date(num * (num < 1e12 ? 1000 : 1));
  return d.toLocaleString('zh-CN', { hour12: false });
}

function fmtElapsed(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m${s}s`;
}

export function AnalysisRecentList({
  items, isLoading, error, selectedId, onSelect,
}: AnalysisRecentListProps) {
  if (isLoading) {
    return (
      <div
        className="flex items-center gap-2 text-sm text-text-secondary"
        data-testid="analysis-recent-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" /> 加载最近分析…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="analysis-recent-error"
      >
        加载分析失败: {error}
      </div>
    );
  }
  if (!items.length) {
    return (
      <div
        className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
        data-testid="analysis-recent-empty"
      >
        暂无分析记录。切到「新建」 tab 跑一次分析。
      </div>
    );
  }
  return (
    <div data-testid="analysis-recent-table-wrap">
      <Table data-testid="analysis-recent-table">
        <TableHeader>
          <TableRow>
            <TableHead>股票 · 日期</TableHead>
            <TableHead>信号</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>已完成阶段</TableHead>
            <TableHead>耗时</TableHead>
            <TableHead>创建时间</TableHead>
            <TableHead className="text-right">查看</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((it) => (
            <TableRow
              key={it.analysis_id}
              data-testid={`analysis-recent-row-${it.analysis_id}`}
              onClick={() => onSelect?.(it.analysis_id)}
              className={selectedId === it.analysis_id
                ? 'bg-bg-elevated cursor-pointer'
                : 'cursor-pointer hover:bg-bg-elevated/60'}
            >
              <TableCell>
                <div className="flex items-center gap-2">
                  {selectedId === it.analysis_id && <ChevronRight className="h-3 w-3 text-bb-accent" />}
                  <span className="font-mono font-medium">{it.ticker}</span>
                  <span className="text-xs text-text-tertiary">{it.trade_date}</span>
                </div>
              </TableCell>
              <TableCell>
                {it.signal
                  ? (
                    <span className="rounded bg-bb-accent/20 px-2 py-0.5 font-mono text-[10px] text-bb-accent-bright">
                      {it.signal}
                    </span>
                  )
                  : <span className="text-xs text-text-tertiary">—</span>}
              </TableCell>
              <TableCell>
                <span className={`text-xs ${statusColor(it.status)}`}>{it.status ?? '—'}</span>
              </TableCell>
              <TableCell className="text-xs text-text-secondary">
                {it.completed_stages?.length ?? 0} / 7
              </TableCell>
              <TableCell className="font-mono text-xs">{fmtElapsed(it.elapsed)}</TableCell>
              <TableCell className="text-xs text-text-tertiary">{fmtTs(it.created_at)}</TableCell>
              <TableCell className="text-right text-xs text-text-tertiary">
                {selectedId === it.analysis_id ? '●' : '点击查看'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default AnalysisRecentList;