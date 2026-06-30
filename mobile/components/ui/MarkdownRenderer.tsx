"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export function MarkdownRenderer({ content, className = "" }: MarkdownRendererProps) {
  if (!content.trim()) {
    return (
      <p className="text-sm text-[var(--text-muted)]">暂无内容</p>
    );
  }

  return (
    <div className={`prose prose-sm prose-invert max-w-none text-[var(--text-secondary)] ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}