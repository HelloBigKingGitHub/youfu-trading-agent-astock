/**
 * ScheduleForm — new/edit schedule dialog. Posts to /api/schedule/create or PUT.
 *
 * Mirrors web/components/schedule_panel.py::render_schedule_dialog.
 * Source types: portfolio (持仓) / watchlist (自选股 + tag) / manual (tickers csv).
 */
import * as React from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type {
  CreateSchedulePayload, Schedule, WatchlistEntry,
} from '@/api/schedule';

interface ScheduleFormProps {
  initial?: Schedule | null;
  watchlist: WatchlistEntry[];
  onSubmit: (payload: CreateSchedulePayload) => Promise<void>;
  onCancel: () => void;
  isSubmitting?: boolean;
  errorMessage?: string | null;
}

const NOTIFY_CHOICES = ['wecom', 'email', 'desktop', 'log'];

export function ScheduleForm({
  initial, watchlist, onSubmit, onCancel, isSubmitting, errorMessage,
}: ScheduleFormProps) {
  const [name, setName] = React.useState(initial?.name ?? '');
  const [cronExpr, setCronExpr] = React.useState(initial?.cron_expr ?? '0 18 * * 1-5');
  const [sourceType, setSourceType] = React.useState<'portfolio' | 'watchlist' | 'manual'>(
    (initial?.source_type as 'portfolio' | 'watchlist' | 'manual') ?? 'manual',
  );
  const [watchlistTag, setWatchlistTag] = React.useState<string>('');
  const [manualTickers, setManualTickers] = React.useState<string>('');
  const [notifyChannels, setNotifyChannels] = React.useState<string[]>(
    initial?.notify_channels ?? ['log'],
  );
  const [enabled, setEnabled] = React.useState<boolean>(initial?.enabled ?? true);

  const watchlistTags = React.useMemo(() => {
    const set = new Set<string>();
    for (const e of watchlist) set.add(e.tag);
    return Array.from(set).sort();
  }, [watchlist]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const sourceConfig: Record<string, unknown> = {};
    if (sourceType === 'watchlist') {
      if (watchlistTag) sourceConfig.tag = watchlistTag;
    } else if (sourceType === 'manual') {
      const tickers = manualTickers
        .split(/[,\s]+/)
        .map((t) => t.trim())
        .filter(Boolean);
      sourceConfig.tickers = tickers;
    }
    const payload: CreateSchedulePayload = {
      name: name.trim(),
      cron_expr: cronExpr.trim(),
      source_type: sourceType,
      source_config: sourceConfig,
      notify_channels: notifyChannels,
      notify_template: initial?.notify_template ?? 'v0.6.0 default',
      enabled,
      config: initial?.config ?? {},
    };
    await onSubmit(payload);
  }

  function toggleChannel(ch: string) {
    setNotifyChannels((cur) =>
      cur.includes(ch) ? cur.filter((x) => x !== ch) : [...cur, ch],
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      data-testid="schedule-form"
      className="space-y-4 rounded-md border border-border-1 bg-bg-elevated/40 p-4"
    >
      <div className="space-y-1">
        <Label htmlFor="sched-name">名称</Label>
        <Input
          id="sched-name"
          data-testid="schedule-form-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="每日持仓复盘"
          required
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="sched-cron">Cron 表达式 (5-field)</Label>
        <Input
          id="sched-cron"
          data-testid="schedule-form-cron"
          value={cronExpr}
          onChange={(e) => setCronExpr(e.target.value)}
          placeholder="0 18 * * 1-5"
          required
          className="font-mono"
        />
        <p className="text-xs text-text-tertiary">
          分 时 日 月 周 · 例: <code>0 18 * * 1-5</code> = 工作日 18:00
        </p>
      </div>

      <div className="space-y-1">
        <Label>来源类型</Label>
        <div className="flex flex-wrap gap-2">
          {(['portfolio', 'watchlist', 'manual'] as const).map((opt) => (
            <Button
              key={opt}
              type="button"
              variant={sourceType === opt ? 'default' : 'outline'}
              size="sm"
              onClick={() => setSourceType(opt)}
              data-testid={`schedule-form-source-${opt}`}
            >
              {opt === 'portfolio' && '持仓'}
              {opt === 'watchlist' && '自选股'}
              {opt === 'manual' && '手动'}
            </Button>
          ))}
        </div>
      </div>

      {sourceType === 'watchlist' && (
        <div className="space-y-1">
          <Label htmlFor="sched-tag">自选股 tag (可选)</Label>
          <select
            id="sched-tag"
            data-testid="schedule-form-watchlist-tag"
            value={watchlistTag}
            onChange={(e) => setWatchlistTag(e.target.value)}
            className="w-full rounded-md border border-border-1 bg-bg-elevated px-3 py-2 text-sm"
          >
            <option value="">(全部)</option>
            {watchlistTags.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      )}

      {sourceType === 'manual' && (
        <div className="space-y-1">
          <Label htmlFor="sched-tickers">手动 ticker 列表 (逗号或空格分隔)</Label>
          <Input
            id="sched-tickers"
            data-testid="schedule-form-tickers"
            value={manualTickers}
            onChange={(e) => setManualTickers(e.target.value)}
            placeholder="600519, 000858, 300750"
            className="font-mono"
          />
        </div>
      )}

      <div className="space-y-1">
        <Label>通知渠道 (可多选)</Label>
        <div className="flex flex-wrap gap-2">
          {NOTIFY_CHOICES.map((ch) => {
            const checked = notifyChannels.includes(ch);
            return (
              <Button
                key={ch}
                type="button"
                variant={checked ? 'default' : 'outline'}
                size="sm"
                onClick={() => toggleChannel(ch)}
                data-testid={`schedule-form-channel-${ch}`}
              >
                {ch}
              </Button>
            );
          })}
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
          data-testid="schedule-form-enabled"
        />
        创建后立即启用
      </label>

      {errorMessage && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-2 text-xs text-red-300">
          {errorMessage}
        </div>
      )}

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onCancel}
          data-testid="schedule-form-cancel"
        >
          取消
        </Button>
        <Button
          type="submit"
          size="sm"
          disabled={isSubmitting}
          data-testid="schedule-form-submit"
        >
          {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {initial ? '保存修改' : '创建定时任务'}
        </Button>
      </div>
    </form>
  );
}