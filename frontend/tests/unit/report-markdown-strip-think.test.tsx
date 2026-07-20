/**
 * P2.31 — Tests for the think-block stripper in ReportMarkdown.
 *
 * P2.30 shipped a regex that only matched ``<think...>...</think>`` (XML).
 * The LangGraph deepseek/thinking model actually emits ``<think>...</think>``
 * (plain text, no angle brackets), so the report tab rendered a giant
 * yellow block of chain-of-thought. The fix widens the regex to handle
 * all three variants we have seen in the wild:
 *
 *   1. ``<think>...</think>``  — plain text, no angle brackets (dominant)
 *   2. ``<THINK>...</THINK>``   — uppercase XML
 *   3. ``<think...>...</think>`` — properly-cased XML, optional attrs
 *
 * We exercise the regex directly via the source text we feed to
 * ``ReportMarkdown``. Since ``ReportMarkdown`` is a React component,
 * we render it with a stripped string and assert the produced text.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ReportMarkdown } from '@/components/analyze/report-markdown';

function renderMarkdown(source: string) {
  return render(<ReportMarkdown source={source} />);
}

describe('ReportMarkdown strips LLM chain-of-thought', () => {
  it('strips the no-angle-bracket variant (the dominant shape in real data)', () => {
    const src = '<think>现在我有了所有需要的数据...让我计算关键数据：</think>\n# 报告\n\n正文';
    renderMarkdown(src);
    // The think block must be gone…
    expect(screen.queryByText(/现在我有了所有需要的数据/)).toBeNull();
    // …and the heading + body must render normally.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('报告');
  });

  it('strips the uppercase <THINK> variant (what the P2.30 screenshot showed)', () => {
    const src = '<THINK>THE USER IS ASKING ME TO WRITE A COMPREHENSIVE ANALYSIS</THINK>\n## 结论';
    renderMarkdown(src);
    expect(screen.queryByText(/THE USER IS ASKING/)).toBeNull();
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('结论');
  });

  it('strips the lowercase XML variant <think...>...</think>', () => {
    const src = '<think lang="en">secret</think>\n# Real';
    renderMarkdown(src);
    expect(screen.queryByText('secret')).toBeNull();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Real');
  });

  it('strips multiple think blocks in the same string', () => {
    const src = '<think>first</think>A<think>second</think>B<think>third</think>C';
    const { container } = renderMarkdown(src);
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/first|second|third/);
    expect(text).toBe('ABC');
  });

  it('preserves the word "think" when it appears in normal prose', () => {
    const src = 'I think this stock is undervalued. Let me explain why...';
    const { container } = renderMarkdown(src);
    expect(container.textContent).toContain('I think this stock is undervalued');
  });

  it('renders the empty-state when stripping leaves nothing', () => {
    renderMarkdown('<think>only think content here</think>');
    expect(screen.getByTestId('report-markdown-empty')).toBeInTheDocument();
    expect(screen.getByText('(本报告无内容)')).toBeInTheDocument();
  });

  it('does not crash on unclosed <think> and keeps the trailing content', () => {
    const src = '<think>truncated with no closing tag\n# Heading\n\nreal body';
    renderMarkdown(src);
    // The truncated think body is gone but the trailing content survives.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Heading');
    expect(screen.getByText('real body')).toBeInTheDocument();
  });
});
