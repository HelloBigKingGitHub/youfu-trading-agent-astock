/**
 * ReportMarkdown — react-markdown wrapper for rendering LLM-generated analyst
 * reports inside the analyze report tab.
 *
 * P2.29 — replaces the old `<pre>{body}</pre>` rendering that treated markdown
 * as plain text (which the user reported as ugly and unreadable). Now real
 * GFM-flavoured markdown gets rendered with headings, bullet lists, tables,
 * and inline code with project-aligned spacing.
 *
 * Safety: wraps `rehype-sanitize` with the default schema which already
 * strips `<script>` / event handlers / `<iframe>` etc. We use LLM-generated
 * content so XSS surface is small but we never trust the markdown source.
 *
 * `_strip_think` removes the model's `  …  ` chain — the user reported earlier
 * that this leaked reasoning onto the report tab.
 */
import * as React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';

interface ReportMarkdownProps {
  source: string;
  /** Drop empty paragraphs that contain only whitespace, common in LLM output. */
  trim?: boolean;
}

const STRIP_THINK = /<think[^>]*>[\s\S]*?<\/think>\s*/gi;

function preprocess(source: string): string {
  // Drop the model's chain-of-thought block before sanitizing/rendering.
  return source.replace(STRIP_THINK, '').trim();
}

export const ReportMarkdown = React.forwardRef<HTMLDivElement, ReportMarkdownProps>(
  ({ source, trim = true }, ref) => {
    const cleaned = React.useMemo(() => preprocess(source), [source]);
    if (!cleaned) {
      return (
        <div ref={ref} data-testid="report-markdown-empty" className="text-xs text-text-tertiary">
          (本报告无内容)
        </div>
      );
    }
    return (
      <div ref={ref} data-testid="report-markdown" className="report-md text-sm leading-relaxed">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSanitize]}
          skipHtml
          components={{
            // Tighten list spacing — Tailwind reset gives too much vertical air.
            ul: ({ children }) => <ul className="my-2 ml-4 list-disc space-y-1">{children}</ul>,
            ol: ({ children }) => <ol className="my-2 ml-4 list-decimal space-y-1">{children}</ol>,
            li: ({ children }) => <li className="text-text-primary">{children}</li>,
            p: ({ children }) => <p className="my-2 text-text-primary">{trim ? compact(children) : children}</p>,
            h1: ({ children }) => (
              <h1 className="mb-2 mt-3 text-lg font-semibold text-text-primary">{children}</h1>
            ),
            h2: ({ children }) => (
              <h2 className="mb-2 mt-3 text-base font-semibold text-text-primary">{children}</h2>
            ),
            h3: ({ children }) => (
              <h3 className="mb-1 mt-2 text-sm font-semibold text-text-secondary">{children}</h3>
            ),
            h4: ({ children }) => (
              <h4 className="mb-1 mt-2 text-sm font-medium text-text-secondary">{children}</h4>
            ),
            code: ({ children, className }) => {
              const isBlock = typeof className === 'string' && className.includes('language-');
              if (isBlock) {
                return (
                  <code className="block whitespace-pre-wrap rounded bg-bg-base/60 p-2 font-mono text-xs text-text-secondary">
                    {children}
                  </code>
                );
              }
              return <code className="rounded bg-bg-base/60 px-1 py-0.5 font-mono text-xs">{children}</code>;
            },
            pre: ({ children }) => (
              <pre className="my-2 overflow-x-auto rounded bg-bg-base/60 p-3 font-mono text-xs leading-relaxed">
                {children}
              </pre>
            ),
            table: ({ children }) => (
              <table className="my-2 w-full border-collapse text-xs">{children}</table>
            ),
            th: ({ children }) => (
              <th className="border border-border-2 bg-bg-elevated/60 px-2 py-1 text-left font-medium">
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td className="border border-border-2 px-2 py-1 align-top">{children}</td>
            ),
            blockquote: ({ children }) => (
              <blockquote className="my-2 border-l-2 border-bb-accent/60 bg-bg-elevated/40 px-3 py-1 text-text-secondary">
                {children}
              </blockquote>
            ),
            hr: () => <hr className="my-3 border-border-2" />,
            a: ({ children, href }) => (
              <a
                href={href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-bb-accent-bright underline-offset-4 hover:underline"
              >
                {children}
              </a>
            ),
          }}
        >
          {cleaned}
        </ReactMarkdown>
      </div>
    );
  },
);
ReportMarkdown.displayName = 'ReportMarkdown';

/**
 * Strip whitespace-only text nodes inside a paragraph — gfm `remark` plugins
 * sometimes insert empty whitespace between sibling elements which renders as
 * extra blank lines in our compact card grid.
 */
function compact(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === 'string') return child.replace(/\s+/g, ' ');
    return child;
  });
}

export default ReportMarkdown;
