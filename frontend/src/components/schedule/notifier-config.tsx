/**
 * NotifierConfig — 4 notify channels status grid + per-channel test fire.
 *
 * Mirrors web/components/schedule_panel.py::render_notifier_panel. Each
 * channel shows: configured flag, enabled-in-config flag, support-test flag,
 * and a 「测试」 button that fires /api/schedule/0/test_notify?channel=<ch>.
 */
import * as React from 'react';
import { Loader2, CheckCircle2, XCircle, Circle, Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { NotifierChannel } from '@/api/schedule';
import { testNotify } from '@/api/schedule';

interface NotifierConfigProps {
  channels: NotifierChannel[];
  enabledChannels: string[];
  isLoading?: boolean;
  error?: string | null;
}

interface TestState {
  status: 'idle' | 'running' | 'ok' | 'error';
  message?: string;
}

export function NotifierConfig({ channels, enabledChannels, isLoading, error }: NotifierConfigProps) {
  const [tests, setTests] = React.useState<Record<string, TestState>>({});

  async function fireTest(ch: string) {
    setTests((s) => ({ ...s, [ch]: { status: 'running' } }));
    try {
      const r = await testNotify('0', ch);
      setTests((s) => ({
        ...s,
        [ch]: { status: 'ok', message: `run_id=${r.run_id} · status=${String(r.status)}` },
      }));
    } catch (e) {
      setTests((s) => ({
        ...s,
        [ch]: { status: 'error', message: e instanceof Error ? e.message : String(e) },
      }));
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="notifier-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> 加载通知配置…
      </div>
    );
  }
  if (error) {
    return (
      <div
        className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
        data-testid="notifier-error"
      >
        加载通知配置失败: {error}
      </div>
    );
  }

  return (
    <div data-testid="notifier-config" className="space-y-3">
      <div className="text-sm text-text-secondary">
        4 渠道 · 当前启用 {enabledChannels.length} 个 · 共 {channels.length}
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {channels.map((ch) => {
          const t = tests[ch.channel] || { status: 'idle' };
          const StatusIcon =
            ch.configured && ch.enabled_in_config
              ? CheckCircle2
              : ch.configured
                ? Circle
                : XCircle;
          const statusColor =
            ch.configured && ch.enabled_in_config
              ? 'text-emerald-400'
              : ch.configured
                ? 'text-amber-400'
                : 'text-text-tertiary';
          return (
            <div
              key={ch.channel}
              data-testid={`notifier-channel-${ch.channel}`}
              className="rounded-md border border-border-1 bg-bg-elevated/40 p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <StatusIcon className={`h-4 w-4 ${statusColor}`} />
                  <span className="font-medium">{ch.label}</span>
                  <span className="font-mono text-xs text-text-tertiary">{ch.channel}</span>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void fireTest(ch.channel)}
                  disabled={t.status === 'running'}
                  data-testid={`notifier-test-${ch.channel}`}
                >
                  {t.status === 'running' ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Zap className="h-3 w-3" />
                  )}
                  测试
                </Button>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="text-text-tertiary">已配置</div>
                  <div className={ch.configured ? 'text-emerald-400' : 'text-text-tertiary'}>
                    {ch.configured ? '是' : '否'}
                  </div>
                </div>
                <div>
                  <div className="text-text-tertiary">已启用</div>
                  <div className={ch.enabled_in_config ? 'text-emerald-400' : 'text-text-tertiary'}>
                    {ch.enabled_in_config ? '是' : '否'}
                  </div>
                </div>
                <div>
                  <div className="text-text-tertiary">支持测试</div>
                  <div>{ch.supports_test ? '是' : '否'}</div>
                </div>
              </div>
              {t.status !== 'idle' && (
                <div
                  className={`text-xs ${t.status === 'ok' ? 'text-emerald-400' : t.status === 'error' ? 'text-red-300' : 'text-text-secondary'}`}
                  data-testid={`notifier-test-result-${ch.channel}`}
                >
                  {t.status === 'running' ? '发送中…' : t.message}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}