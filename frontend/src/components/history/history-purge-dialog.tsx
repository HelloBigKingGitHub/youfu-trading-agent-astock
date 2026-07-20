/**
 * P2.30 — Shared "清空所有历史" dialog.
 *
 * Mounted by both HistoryPage and AnalyzePage so the destructive action
 * has a single source of truth:
 *   * Trigger button + confirmation Dialog are identical across surfaces.
 *   * The user must type the literal sentinel 清空 before the
 *     destructive button is enabled (defense against fat-finger).
 *   * On success, React Query cache is invalidated for both history
 *     surfaces (`['history']`, `['analyze-recent']`) and per-id caches
 *     (`['history-detail']`, `['analyze-progress']`, `['analyze-report']`)
 *     are removed so a stale detail view doesn't render post-purge.
 *   * ``onPurged`` lets each page reset its own local state
 *     (HistoryPage closes the detail modal + jumps to page 0;
 *     AnalyzePage clears ``activeAnalysisId`` and stays on the history tab).
 *
 * 409 responses surface the active-analyses count and keep the dialog
 * open so the user can retry once the running analyses complete.
 */

import * as React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useToast } from '@/components/ui/toast';
import {
  purgeHistory,
  type PurgeHistoryBody,
  type PurgeHistoryResponse,
} from '@/api/history';

interface HistoryPurgeDialogProps {
  /**
   * Page-local callback fired after a successful purge. Each consumer
   * resets its own state here (e.g. clearing selected ids).
   */
  onPurged?: () => void;
}

const CONFIRM_SENTINEL = '清空';
const REQUEST_BODY: PurgeHistoryBody = {
  confirmation: 'CLEAR_ALL_HISTORY',
  include_cache: true,
};

interface ActiveAnalysesErrorPayload {
  reason: 'active_analyses';
  active_ids: string[];
  active_count: number;
}

/**
 * Runtime guard for the 409 detail payload — narrows `unknown` to the
 * expected `active_analyses` shape before we trust it for the toast.
 * ``JSON.parse(tail) as { ... }`` alone is unsafe: a non-conforming body
 * could pass the `reason === 'active_analyses'` test while missing
 * `active_count`/`active_ids`.
 */
function isActiveAnalysesPayload(value: unknown): value is ActiveAnalysesErrorPayload {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  if (v.reason !== 'active_analyses') return false;
  if (!Array.isArray(v.active_ids)) return false;
  if (typeof v.active_count !== 'number') return false;
  return true;
}

/**
 * Parse a 409 detail payload out of an Error message produced by
 * ``purgeHistory``'s ``Error(`POST /api/history/purge ${status}: ${body}`)``.
 * Returns null if the payload isn't the expected active-analyses shape.
 */
function parseActiveAnalysesError(message: string): ActiveAnalysesErrorPayload | null {
  const idx = message.indexOf('{"detail"');
  if (idx < 0) return null;
  const tail = message.slice(idx);
  try {
    const parsed: unknown = JSON.parse(tail);
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'detail' in parsed &&
      isActiveAnalysesPayload((parsed as { detail: unknown }).detail)
    ) {
      return (parsed as { detail: ActiveAnalysesErrorPayload }).detail;
    }
  } catch {
    return null;
  }
  return null;
}

export function HistoryPurgeDialog({ onPurged }: HistoryPurgeDialogProps) {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [open, setOpen] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState('');

  const mutation = useMutation<PurgeHistoryResponse, Error, void>({
    mutationFn: () => purgeHistory(REQUEST_BODY),
    onSuccess: (data) => {
      // Refresh every list that may have grown stale.
      void queryClient.invalidateQueries({ queryKey: ['history'] });
      void queryClient.invalidateQueries({ queryKey: ['analyze-recent'] });
      // Wipe per-id caches so a stale detail/progress/report doesn't
      // render in any open tab after the purge.
      queryClient.removeQueries({ queryKey: ['history-detail'] });
      queryClient.removeQueries({ queryKey: ['analyze-progress'] });
      queryClient.removeQueries({ queryKey: ['analyze-report'] });

      toast({
        title: '已清空所有历史',
        description:
          data.failed_items > 0
            ? `删除 ${data.history_deleted} 条历史 · 释放 ${formatBytes(
                data.bytes_freed
              )} · ${data.failed_items} 项失败`
            : `删除 ${data.history_deleted} 条历史 · ${data.reports_deleted} 份报告 · ${data.log_runs_deleted} 份日志 · 释放 ${formatBytes(
                data.bytes_freed
              )}`,
        variant: data.failed_items > 0 ? 'warning' : 'success',
      });

      // Page-local cleanup then close the dialog.
      onPurged?.();
      setOpen(false);
      setConfirmText('');
    },
    onError: (err: Error) => {
      const active = parseActiveAnalysesError(err.message);
      if (active) {
        toast({
          title: '仍有分析在运行',
          description: `当前 ${active.active_count} 个分析处于 pending / running 状态，请等待完成或取消后再试。`,
          variant: 'error',
        });
      } else {
        toast({
          title: '清空失败',
          description: err.message,
          variant: 'error',
        });
      }
      // Dialog stays open so the user can retry.
    },
  });

  const confirmEnabled = confirmText === CONFIRM_SENTINEL && !mutation.isPending;

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        data-testid="history-purge-trigger"
        className="border-bb-up/40 text-bb-up hover:bg-bb-up/10"
      >
        <Trash2 className="h-4 w-4" />
        清空所有历史
      </Button>
      <Dialog
        open={open}
        onClose={() => {
          if (mutation.isPending) return;
          setOpen(false);
          setConfirmText('');
        }}
        title="清空所有历史"
        description="该操作不可撤销，请仔细阅读下方影响范围。"
        testId="history-purge-dialog"
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                if (mutation.isPending) return;
                setOpen(false);
                setConfirmText('');
              }}
              disabled={mutation.isPending}
              data-testid="history-purge-cancel"
            >
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => mutation.mutate()}
              disabled={!confirmEnabled}
              data-testid="history-purge-confirm"
            >
              {mutation.isPending ? '正在清空…' : '确认清空'}
            </Button>
          </>
        }
      >
        <div className="space-y-4 text-sm">
          <section>
            <h3 className="font-semibold text-text-primary mb-2">将删除</h3>
            <ul className="space-y-1.5 text-text-secondary list-disc pl-5">
              <li>所有分析历史元数据（已完成 / 已失败）</li>
              <li>对应的生成报告与逐次 Agent 运行日志</li>
              <li>所有行情缓存（K线 / 资金流 / 选股热度等）</li>
            </ul>
          </section>

          <section>
            <h3 className="font-semibold text-text-primary mb-2">不会删除</h3>
            <ul className="space-y-1.5 text-text-secondary list-disc pl-5">
              <li>定时任务配置与运行历史</li>
              <li>持仓、交易流水与预警</li>
              <li>自选股、系统设置、Agent memory</li>
            </ul>
          </section>

          <section>
            <label
              htmlFor="history-purge-input"
              className="block font-semibold text-text-primary mb-2"
            >
              请输入 <span className="font-mono text-bb-up">{CONFIRM_SENTINEL}</span> 以确认
            </label>
            <Input
              id="history-purge-input"
              data-testid="history-purge-input"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={CONFIRM_SENTINEL}
              disabled={mutation.isPending}
              autoComplete="off"
              autoFocus
            />
          </section>
        </div>
      </Dialog>
    </>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}