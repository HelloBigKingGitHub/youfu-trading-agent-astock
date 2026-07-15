import * as React from 'react';
import { NavLink } from 'react-router-dom';
import { cn } from '@/lib/utils';

// 9 sidebar entries — order MUST match existing streamlit web/components/* pages.
// (web/app.py sidebar order: 分析 / 批量 / 板块 / 仓位 / 历史 / 日志 / 走势 / 定时 / 设置)
// Phase 1: only ⚙️ enabled (renders SettingsPage); other 8 are placeholders.
export interface NavEntry {
  to: string;
  icon: string;        // emoji — keeps visual parity with streamlit sidebar
  label: string;
  phase: string;       // TODO marker
  enabled: boolean;
}

export const NAV_ENTRIES: NavEntry[] = [
  { to: '/analyze',  icon: '📝', label: '分析',   phase: 'Phase 2.1', enabled: false },
  { to: '/batch',    icon: '📊', label: '批量',   phase: 'Phase 2.4', enabled: false },
  { to: '/sector',   icon: '📈', label: '板块',   phase: 'Phase 2.5', enabled: false },
  { to: '/portfolio',icon: '💼', label: '仓位',   phase: 'Phase 2.6', enabled: false },
  { to: '/history',  icon: '📋', label: '历史',   phase: 'Phase 2.2', enabled: false },
  { to: '/logs',     icon: '📋', label: '日志',   phase: 'Phase 2.3', enabled: false },
  { to: '/chart',    icon: '📈', label: '走势',   phase: 'Phase 2.7', enabled: false },
  { to: '/schedule', icon: '⏰', label: '定时',   phase: 'Phase 2.8', enabled: false },
  { to: '/settings', icon: '⚙️', label: '设置',   phase: 'Phase 1 ✅', enabled: true  },
];

export function Sidebar() {
  return (
    <aside
      className="flex flex-col w-56 shrink-0 border-r border-border-1 bg-bg-surface h-full overflow-y-auto"
      data-testid="sidebar"
    >
      <nav className="flex flex-col gap-1 p-3">
        {NAV_ENTRIES.map((entry) => (
          <SidebarItem key={entry.to} entry={entry} />
        ))}
      </nav>
      <div className="mt-auto p-3 text-xs text-text-tertiary border-t border-border-1">
        <div>v0.7.0-dev</div>
        <div className="mt-1">React SPA · FastAPI · Streamlit (legacy)</div>
      </div>
    </aside>
  );
}

function SidebarItem({ entry }: { entry: NavEntry }) {
  const baseClasses =
    'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors';
  const enabledClasses = 'text-text-primary hover:bg-bg-elevated cursor-pointer';
  const disabledClasses = 'text-text-tertiary cursor-not-allowed opacity-60';

  if (!entry.enabled) {
    return (
      <div
        data-testid={`sidebar-${entry.label}`}
        title={`TODO: ${entry.phase}`}
        className={cn(baseClasses, disabledClasses)}
      >
        <span className="text-base w-5 text-center" aria-hidden>{entry.icon}</span>
        <span className="flex-1">{entry.label}</span>
        <span className="text-[10px] text-text-tertiary">{entry.phase}</span>
      </div>
    );
  }

  return (
    <NavLink
      to={entry.to}
      data-testid={`sidebar-${entry.label}`}
      className={({ isActive }) =>
        cn(
          baseClasses,
          enabledClasses,
          isActive && 'bg-bg-elevated text-bb-accent ring-1 ring-bb-accent/30'
        )
      }
    >
      <span className="text-base w-5 text-center" aria-hidden>{entry.icon}</span>
      <span className="flex-1">{entry.label}</span>
    </NavLink>
  );
}