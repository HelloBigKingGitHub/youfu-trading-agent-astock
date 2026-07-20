/**
 * ReportHeader — hero block at the top of the analyze report tab.
 *
 * P2.29 — replaces the old flat ticker+signal pill layout (rooted in
 * ``web/components/report_viewer.py``'s "TRADING SIGNAL" big block). Renders:
 *
 *   * Eyebrow "TRADING SIGNAL" small caps
 *   * Big signal pill colored by BUY/SELL/HOLD
 *   * Ticker + trade date prominent
 *   * Two download buttons (📥 Markdown / 📄 PDF) wired to the new
 *     GET /api/analyze/{id}/export?format=… endpoint.
 *   * Disclaimer caption underneath
 *
 * Downloads rely on the browser's native <a download> behaviour triggered by
 * Content-Disposition, so no Blob / URL.createObjectURL faff.
 */
import * as React from 'react';
import { Download, FileText, Loader2 } from 'lucide-react';
import {
  analyzeExportFilename,
  analyzeExportUrl,
  type AnalyzeReport,
} from '@/api/analyze';

interface ReportHeaderProps {
  report: AnalyzeReport;
  pdfAvailable: boolean;
}

interface SignalStyle {
  label: string;
  cls: string;
  ring: string;
}

function styleSignal(signal: string | null): SignalStyle {
  const upper = (signal ?? '').toUpperCase();
  if (upper.includes('BUY')) {
    return {
      label: 'BUY',
      cls: 'bg-emerald-500/15 text-emerald-300',
      ring: 'ring-emerald-500/30',
    };
  }
  if (upper.includes('SELL')) {
    return {
      label: 'SELL',
      cls: 'bg-red-500/15 text-red-300',
      ring: 'ring-red-500/30',
    };
  }
  return {
    label: upper || '—',
    cls: 'bg-amber-500/15 text-amber-300',
    ring: 'ring-amber-500/30',
  };
}

export function ReportHeader({ report, pdfAvailable }: ReportHeaderProps) {
  const signalValue = readSignal(report);
  const sig = styleSignal(signalValue);
  const mdUrl = analyzeExportUrl(report.analysis_id, 'md');
  const pdfUrl = analyzeExportUrl(report.analysis_id, 'pdf');
  const mdName = analyzeExportFilename(report.ticker, report.trade_date, 'md');
  const pdfName = analyzeExportFilename(report.ticker, report.trade_date, 'pdf');

  return (
    <section
      className="rounded-lg border border-border-2 bg-bg-surface px-4 py-3 shadow-sm"
      data-testid="analysis-report-hero"
      data-signal={sig.label}
    >
      <div className="flex flex-wrap items-center gap-3">
        {/* Signal block — the inner span carries the new ``analysis-report-signal-value``
            testid while the outer wrapper keeps the legacy ``analysis-report-signal``
            testid alive so the AnalyzePage unit test (and any external
            selectors) continue to find the signal pill. */}
        <div
          className={`flex flex-col items-center justify-center rounded-md px-3 py-1.5 ring-1 ${sig.cls} ${sig.ring}`}
          data-testid="analysis-report-signal-block"
        >
          <span className="text-[9px] uppercase tracking-widest text-text-tertiary leading-none">
            Trading Signal
          </span>
          <span data-testid="analysis-report-signal" className="contents">
            <span
              className="font-mono text-base font-semibold leading-tight"
              data-testid="analysis-report-signal-value"
            >
              {sig.label}
            </span>
          </span>
        </div>

        {/* Ticker / date meta */}
        <div className="flex-1 space-y-0 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-base font-semibold text-text-primary">
              {report.ticker}
            </span>
            <span className="text-xs text-text-tertiary">
              分析日期 <span className="font-mono">{report.trade_date}</span>
            </span>
          </div>
          <div className="font-mono text-[10px] text-text-tertiary truncate">
            {report.analysis_id}
          </div>
        </div>

        {/* Download buttons */}
        <div className="flex flex-col gap-2" data-testid="analysis-report-actions">
          <a
            href={mdUrl}
            download={mdName}
            data-testid="analysis-report-download-md"
            className="inline-flex items-center justify-center gap-2 rounded-md border border-border-2 bg-bg-elevated px-4 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-surface hover:border-bb-accent/60"
          >
            <FileText className="h-4 w-4" />
            下载 Markdown
          </a>
          {pdfAvailable ? (
            <a
              href={pdfUrl}
              download={pdfName}
              data-testid="analysis-report-download-pdf"
              className="inline-flex items-center justify-center gap-2 rounded-md border border-border-2 bg-bg-elevated px-4 py-2 text-sm font-medium text-text-primary transition-colors hover:bg-bg-surface hover:border-bb-accent/60"
            >
              <Download className="h-4 w-4" />
              下载 PDF
            </a>
          ) : (
            <button
              type="button"
              disabled
              data-testid="analysis-report-download-pdf-disabled"
              title="PDF 导出需要系统装有中文字体（Windows 自带微软雅黑/黑体，macOS 自带苹方，Linux 可 apt install fonts-noto-cjk）。请改用 Markdown 下载。"
              className="inline-flex cursor-not-allowed items-center justify-center gap-2 rounded-md border border-border-2 bg-bg-elevated/40 px-4 py-2 text-sm font-medium text-text-tertiary opacity-50"
            >
              <Download className="h-4 w-4" />
              PDF 不可用
            </button>
          )}
        </div>
      </div>

      {/* Disclaimer caption */}
      <p className="mt-3 border-t border-border-2 pt-2 text-[11px] text-text-tertiary">
        ⚠️ 本报告由 AI 多 Agent 系统自动生成，仅供学习研究与技术演示，不构成投资建议。投资决策请咨询持牌专业机构。
      </p>
    </section>
  );
}

/** Pulls the trading signal out of the new analyze payload. */
function readSignal(report: AnalyzeReport): string | null {
  if (!report.report) return null;
  const r = report.report as Record<string, unknown>;
  const direct = r.final_signal;
  if (typeof direct === 'string' && direct.trim()) return direct;
  const decision = r.final_trade_decision;
  if (typeof decision === 'string' && decision.trim()) return decision;
  if (decision && typeof decision === 'object') {
    const inner = (decision as Record<string, unknown>).signal;
    if (typeof inner === 'string' && inner.trim()) return inner;
  }
  return null;
}

/** Returns a spinner if a download is pending — currently unused (downloads
 *  go straight through native <a download>) but exported so future wrappers
 *  (e.g. a Blob-fallback for the PDF button) can show progress without
 *  inventing their own loading state. */
export const _DownloadSpinner = Loader2;

export default ReportHeader;
