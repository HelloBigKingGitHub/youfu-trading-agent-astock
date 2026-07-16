/**
 * ImportExport — 导入导出 tab. File picker → detect format → preview → commit.
 *
 * Mirrors web/components/portfolio_import_view.py.  Both UIs hit the same
 * portfolio_import backend (4 CSV formats: eastmoney / ths / xueqiu / generic),
 * so the visible state machine is identical:
 *
 *   file chosen → POST /import/preview (multipart) → preview table
 *      ↓
 *   user clicks 提交导入 → POST /import/commit (multipart + format) → result banner
 *
 * Export is a plain GET /export?format=positions|transactions download with
 * UTF-8 BOM for Excel friendliness (mirrors backend).
 */
import * as React from 'react';
import { useMutation } from '@tanstack/react-query';
import {
  Download, FileSpreadsheet, Loader2, Upload,
} from 'lucide-react';
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  commitImport, previewImport,
  type CommitImportResponse, type PreviewImportResponse,
  exportUrl,
} from '@/api/portfolio';

interface ImportExportProps {
  isLoading?: boolean;
}

function fmtDate(ts: number): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('zh-CN');
}

export function ImportExport({ isLoading }: ImportExportProps) {
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<PreviewImportResponse | null>(null);
  const [commitResult, setCommitResult] = React.useState<CommitImportResponse | null>(null);
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null);

  const previewMutation = useMutation({
    mutationFn: (f: File) => previewImport(f),
    onSuccess: (data) => {
      setPreview(data);
      setErrorMsg(null);
      setCommitResult(null);
    },
    onError: (err: unknown) => {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setPreview(null);
    },
  });

  const commitMutation = useMutation({
    mutationFn: ({ f, fmt }: { f: File; fmt: string }) => commitImport(f, fmt as 'eastmoney' | 'ths' | 'xueqiu' | 'generic'),
    onSuccess: (data) => {
      setCommitResult(data);
      setErrorMsg(null);
    },
    onError: (err: unknown) => {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    },
  });

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setPreview(null);
    setCommitResult(null);
    setErrorMsg(null);
    if (f) previewMutation.mutate(f);
  }

  function handleCommit() {
    if (!file || !preview) return;
    commitMutation.mutate({ f: file, fmt: preview.format });
  }

  return (
    <div className="space-y-4" data-testid="import-export">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Upload className="h-4 w-4" /> 导入持仓 CSV
          </CardTitle>
          <CardDescription>
            支持 4 种格式 — 东财 / 同花顺 / 雪球 / generic。自动 detect + 预览前 10 行。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={handleFile}
              disabled={previewMutation.isPending}
              data-testid="import-file-input"
              className="text-sm file:mr-3 file:rounded-md file:border file:border-border-1 file:bg-bg-elevated file:px-3 file:py-1.5 file:text-sm file:text-text-primary hover:file:bg-bg-surface"
            />
            {file && (
              <span className="text-xs text-text-secondary font-mono">
                {file.name} ({(file.size / 1024).toFixed(1)} KB)
              </span>
            )}
          </div>

          {(previewMutation.isPending || isLoading) && (
            <div className="flex items-center gap-2 text-sm text-text-secondary" data-testid="import-loading">
              <Loader2 className="h-4 w-4 animate-spin" /> 解析中…
            </div>
          )}

          {errorMsg && (
            <div
              className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300"
              data-testid="import-error"
            >
              {errorMsg}
            </div>
          )}

          {preview && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border-1 bg-bg-elevated/40 px-4 py-2 text-sm">
                <div>
                  检测格式:{' '}
                  <code className="rounded bg-bg-surface px-1.5 py-0.5 font-mono" data-testid="import-format">
                    {preview.format}
                  </code>
                  {' · '}
                  共 <strong data-testid="import-total-rows">{preview.total_rows}</strong> 行
                </div>
                <Button
                  type="button"
                  size="sm"
                  disabled={commitMutation.isPending || !file}
                  onClick={handleCommit}
                  data-testid="import-commit"
                >
                  {commitMutation.isPending ? '导入中…' : '✓ 提交导入'}
                </Button>
              </div>

              <div className="rounded-md border border-border-1">
                <Table data-testid="import-preview-table">
                  <TableHeader>
                    <TableRow>
                      {Object.keys(preview.preview[0] ?? {}).map((k) => (
                        <TableHead key={k}>{k}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.preview.map((row, i) => (
                      <TableRow key={i}>
                        {Object.values(row).map((v, j) => (
                          <TableCell key={j} className="font-mono text-xs">
                            {v === null || v === undefined ? '' : String(v)}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <p className="text-xs text-text-tertiary">
                preview 仅展示前 10 行 · preview_hash ={' '}
                <code className="font-mono">{preview.preview_hash}</code>
              </p>
            </>
          )}

          {commitResult && (
            <div
              className="rounded-md border border-green-500/40 bg-green-500/10 p-3 text-sm text-green-300"
              data-testid="import-commit-result"
            >
              ✓ 导入完成 — 新增 {commitResult.inserted} 条 · 跳过 {commitResult.skipped} 条 · 错误{' '}
              {Array.isArray(commitResult.errors) ? commitResult.errors.length : commitResult.errors}
              {' · '}
              <span className="font-mono text-xs">{fmtDate(commitResult.committed_at)}</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Download className="h-4 w-4" /> 导出持仓 CSV
          </CardTitle>
          <CardDescription>
            UTF-8 BOM 格式 — Excel 直接打开不乱码
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <a
            href={exportUrl('positions')}
            data-testid="export-positions"
            className="inline-flex items-center gap-2 rounded-md border border-border-1 bg-bg-elevated px-3 py-2 text-sm hover:bg-bg-surface"
          >
            <FileSpreadsheet className="h-4 w-4" /> 导出持仓 (positions)
          </a>
          <a
            href={exportUrl('transactions')}
            data-testid="export-transactions"
            className="inline-flex items-center gap-2 rounded-md border border-border-1 bg-bg-elevated px-3 py-2 text-sm hover:bg-bg-surface"
          >
            <FileSpreadsheet className="h-4 w-4" /> 导出流水 (transactions)
          </a>
        </CardContent>
      </Card>
    </div>
  );
}

export default ImportExport;