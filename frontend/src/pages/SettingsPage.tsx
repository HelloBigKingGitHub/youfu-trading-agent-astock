import * as React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Save, RefreshCw, Loader2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Separator } from '@/components/ui/separator';
import { useToast } from '@/components/ui/toast';
import { getSettings, saveSettings } from '@/api/settings';
import type { ProviderOption, SettingsPayload, SettingsSavePayload } from '@/types/api';

// Mirrors web/components/settings_panel.py — 4 fields (provider / deepModel /
// quickModel / baseUrl) + API key status banner. The Streamlit page reads
// st.session_state + os.getenv() live; React reads /api/settings which is
// served by backend/api/settings.py from the same data sources.

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const {
    data,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
    staleTime: 30_000,
  });

  // Local form state — initialised from server once data arrives.
  const [provider, setProvider] = React.useState<string>('');
  const [deepModel, setDeepModel] = React.useState<string>('');
  const [quickModel, setQuickModel] = React.useState<string>('');
  const [baseUrl, setBaseUrl] = React.useState<string>('');

  React.useEffect(() => {
    if (data?.settings) {
      setProvider(data.settings.provider);
      setDeepModel(data.settings.deepModel);
      setQuickModel(data.settings.quickModel);
      setBaseUrl(data.settings.baseUrl);
    }
  }, [data?.settings]);

  const saveMutation = useMutation({
    mutationFn: (payload: SettingsSavePayload) => saveSettings(payload),
    onSuccess: (resp) => {
      toast({
        title: '设置已保存',
        description: `provider=${resp.settings.provider}, deep=${resp.settings.deepModel}`,
        variant: 'success',
      });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: (e: Error) => {
      toast({
        title: '保存失败',
        description: e.message,
        variant: 'error',
      });
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-text-secondary" data-testid="settings-loading">
        <Loader2 className="h-4 w-4 animate-spin" />
        加载设置中…
      </div>
    );
  }

  if (error) {
    return (
      <Alert variant="destructive" data-testid="settings-error">
        <AlertTitle>加载设置失败</AlertTitle>
        <AlertDescription>
          {(error as Error).message}
          <Button onClick={() => refetch()} variant="outline" size="sm" className="ml-3">
            <RefreshCw className="h-3 w-3" /> 重试
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (!data) return null;

  const providers = data.providers;
  const currentProvider = providers.find((p) => p.key === provider) ?? providers[0];

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    saveMutation.mutate({ provider, deepModel, quickModel, baseUrl });
  }

  function handleReset() {
    setProvider(data!.settings.provider);
    setDeepModel(data!.settings.deepModel);
    setQuickModel(data!.settings.quickModel);
    setBaseUrl(data!.settings.baseUrl);
  }

  return (
    <form
      onSubmit={handleSubmit}
      data-testid="settings-form"
      className="mx-auto w-full max-w-3xl space-y-8"
    >
      <ApiKeyBanner settings={data.settings} />
      <Card>
        <CardHeader>
          <CardTitle>🤖 模型配置</CardTitle>
          <CardDescription>选择 LLM 供应商和模型组合</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div>
            <Label htmlFor="provider">LLM 供应商</Label>
            <Select
              id="provider"
              data-testid="settings-provider"
              value={provider}
              onChange={(e) => {
                const next = e.target.value;
                setProvider(next);
                const p = providers.find((x) => x.key === next);
                if (p) {
                  setDeepModel(p.deep[0]?.value ?? '');
                  setQuickModel(p.quick[0]?.value ?? '');
                }
              }}
            >
              {providers.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </Select>
          </div>

          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
            <div>
              <Label htmlFor="deep">深度模型</Label>
              <Select
                id="deep"
                data-testid="settings-deep"
                value={deepModel}
                onChange={(e) => setDeepModel(e.target.value)}
              >
                {(currentProvider?.deep ?? []).map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="quick">快速模型</Label>
              <Select
                id="quick"
                data-testid="settings-quick"
                value={quickModel}
                onChange={(e) => setQuickModel(e.target.value)}
              >
                {(currentProvider?.quick ?? []).map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <Separator />

          <div>
            <Label htmlFor="baseUrl">Base URL (可选, 走自定义网关时填)</Label>
            <Input
              id="baseUrl"
              data-testid="settings-baseurl"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </div>
        </CardContent>
        <CardFooter className="flex justify-between gap-4">
          <Button type="button" variant="outline" onClick={handleReset} disabled={saveMutation.isPending}>
            重置
          </Button>
          <Button
            type="submit"
            data-testid="settings-save"
            disabled={saveMutation.isPending || isFetching}
          >
            {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}

function ApiKeyBanner({ settings }: { settings: SettingsPayload }) {
  if (settings.apiKeySet) {
    return (
      <Alert variant="success" data-testid="apikey-banner-set">
        <AlertTitle>✅ API Key 已配置</AlertTitle>
        <AlertDescription>
          {settings.apiKey}
          <span className="ml-2 text-text-tertiary">({settings.provider})</span>
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert variant="warning" data-testid="apikey-banner-missing">
      <AlertTitle>⚠️ 未检测到 API Key</AlertTitle>
      <AlertDescription>
        请在项目根目录 <code className="px-1 rounded bg-bg-elevated">.env</code> 文件中配置{' '}
        <code className="px-1 rounded bg-bg-elevated">{providerEnvVar(settings.provider)}</code> 后重启后端生效。
      </AlertDescription>
    </Alert>
  );
}

function providerEnvVar(provider: string): string {
  return `${provider.toUpperCase()}_API_KEY`;
}