/**
 * AlertsList — 预警 tab. Renders 7-rule catalog + live alert rules + ack button.
 *
 * Mirrors web/components/portfolio_alerts_view.py.  Both UIs share the same
 * ``PortfolioStore.list_alerts()`` singleton, so the rule rows are 1:1.
 *
 * Color badge convention:
 *   - enabled + recently triggered → yellow (active watch)
 *   - enabled, never triggered    → green (armed)
 *   - disabled (acked)            → grey (silenced)
 */
import * as React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, Loader2, ShieldAlert } from 'lucide-react';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  ackAlert,
  type AlertRule,
  type AlertRuleCatalogEntry,
} from '@/api/portfolio';

interface AlertsListProps {
  rules: AlertRule[];
  catalog: AlertRuleCatalogEntry[];
  isLoading?: boolean;
  error?: string | null;
}

function statusBadge(r: AlertRule): { label: string; cls: string } {
  if (!r.enabled) return { label: '已确认', cls: 'bg-bg-elevated text-text-tertiary border-border-1' };
  if (r.trigger_count > 0) return { label: '已触发', cls: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40' };
  return { label: '启用中', cls: 'bg-green-500/20 text-green-300 border-green-500/40' };
}

function labelForType(t: string, catalog: AlertRuleCatalogEntry[]): string {
  const entry = catalog.find((c) => c.type === t);
  return entry?.label ?? t;
}

export function AlertsList({ rules, catalog, isLoading, error }: AlertsListProps) {
  const queryClient = useQueryClient();
  const ackMutation = useMutation({
    mutationFn: (alertId: string) => ackAlert(alertId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['portfolio-alerts'] });
    },
  });

  return (
    <div className="space-y-4" data-testid="alerts-list">
      {/* rule type catalog (always 7 rules) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-4 w-4" /> 7 种预警规则
          </CardTitle>
          <CardDescription>
            后端 300s anti-repeat 去重 — 同一规则同 ticker 5 分钟内只触发一次
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
            {catalog.map((c) => (
              <li
                key={c.type}
                className="rounded-md border border-border-1 bg-bg-elevated/40 p-2"
                data-testid={`alert-catalog-${c.type}`}
              >
                <div className="font-semibold">{c.label}</div>
                <div className="text-xs text-text-secondary">{c.description}</div>
                <div className="mt-1 font-mono text-[11px] text-text-tertiary">{c.example}</div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">当前预警规则</CardTitle>
          <CardDescription>
            共 {rules.length} 条规则 — 点击「确认」禁用对应规则并写入 audit log
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="alerts-loading">
              <Loader2 className="h-4 w-4 animate-spin" /> 加载预警规则…
            </div>
          )}
          {error && (
            <div
              className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
              data-testid="alerts-error"
            >
              加载预警规则失败: {error}
            </div>
          )}
          {!isLoading && !error && rules.length === 0 && (
            <div
              className="rounded-md border border-dashed border-border-2 bg-bg-elevated/40 p-6 text-center text-sm text-text-tertiary"
              data-testid="alerts-empty"
            >
              暂无预警规则。可通过后端 <code className="font-mono">portfolio_alerts</code> 模块添加。
            </div>
          )}
          {!isLoading && !error && rules.length > 0 && (
            <Table data-testid="alerts-table">
              <TableHeader>
                <TableRow>
                  <TableHead>代码</TableHead>
                  <TableHead>规则</TableHead>
                  <TableHead className="text-right">阈值</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">触发次数</TableHead>
                  <TableHead>备注</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.map((r) => {
                  const badge = statusBadge(r);
                  return (
                    <TableRow key={r.rule_id} data-testid={`alert-row-${r.rule_id}`}>
                      <TableCell className="font-mono">{r.ticker}</TableCell>
                      <TableCell>{labelForType(r.rule_type, catalog)}</TableCell>
                      <TableCell className="text-right font-mono">{r.threshold}</TableCell>
                      <TableCell>
                        <span className={`inline-block rounded border px-1.5 py-0.5 text-xs ${badge.cls}`}>
                          {badge.label}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono">{r.trigger_count}</TableCell>
                      <TableCell className="text-text-secondary">{r.note || '—'}</TableCell>
                      <TableCell className="text-right">
                        {r.enabled && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={ackMutation.isPending && ackMutation.variables === r.rule_id}
                            onClick={() => ackMutation.mutate(r.rule_id)}
                            data-testid={`alert-ack-${r.rule_id}`}
                          >
                            {ackMutation.isPending && ackMutation.variables === r.rule_id
                              ? '确认中…'
                              : (<><Check className="mr-1 h-3 w-3" />确认</>)}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default AlertsList;