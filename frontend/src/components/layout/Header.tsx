import * as React from 'react';

interface HeaderProps {
  title: string;
  subtitle?: string;
}

// Top header bar — mirrors web/components/settings_panel.py's bb-h1 block
// (icon + title + subtitle) on a darker elevated background.
export function Header({ title, subtitle }: HeaderProps) {
  return (
    <header className="flex items-center justify-between border-b border-border-1 bg-bg-surface px-6 py-4">
      <div>
        <h1 className="text-2xl font-semibold text-text-primary" data-testid="page-title">
          {title}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-text-secondary">{subtitle}</p>}
      </div>
      <div className="text-xs text-text-tertiary font-mono">React SPA · Phase 1</div>
    </header>
  );
}