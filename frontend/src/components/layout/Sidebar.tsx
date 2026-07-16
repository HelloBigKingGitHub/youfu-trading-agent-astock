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
  { to: '/history',  icon: '📋', label: '历史',   phase: 'Phase 2.2 ✅', enabled: true  },
  { to: '/logs',     icon: '📋', label: '日志',   phase: 'Phase 2.3 ✅', enabled: true  },
  { to: '/chart',    icon: '📈', label: '走势',   phase: 'Phase 2.4 ✅', enabled: true  },
  { to: '/schedule', icon: '⏰', label: '定时',   phase: 'Phase 2.8', enabled: false },
  { to: '/settings', icon: '⚙️', label: '设置',   phase: 'Phase 1 ✅', enabled: true  },
];

const _BUILD = 'v0.7.0-dev';

// Inline "phase tag" — kept local so the Sidebar diff stays under 30 lines.
// Renders as a faint, uppercase pill right-aligned next to disabled labels.
function PhaseTag({ phase }: { phase: string }) {
  return (
    <span
      className="text-[9px] uppercase tracking-wider text-text-tertiary
                 border border-border-1 rounded-sm px-1.5 py-0.5 leading-none"
    >
      {phase}
    </span>
  );
}

export function Sidebar() {
  return (
    <aside
      className="flex flex-col w-56 shrink-0 border-r border-border-1 bg-bg-elevated h-full overflow-y-auto"
      data-testid="sidebar"
    >
      {/* Logo header — two-tone TRADING AGENTS - ASTOCK (mirrors web/components/sidebar.py bb-logo-box). */}
      <div className="px-4 pt-4 pb-3 border-b border-border-1 text-center">
        <div className="font-mono text-[0.88rem] font-bold leading-tight tracking-wider whitespace-nowrap">
          <span className="text-bb-accent-bright" style={{ textShadow: '0 0 12px var(--bb-accent-glow)' }}>
            TRADING
          </span>
          <span className="text-text-primary">AGENTS</span>
          <span className="text-text-primary">-</span>
          <span className="text-bb-accent-bright" style={{ textShadow: '0 0 12px var(--bb-accent-glow)' }}>
            ASTOCK
          </span>
        </div>
        <div className="font-mono text-[0.66rem] text-text-secondary mt-1.5">
          A股多 Agent 投研系统
        </div>
        <div className="font-mono text-[0.66rem] text-text-tertiary mt-1">
          {_BUILD} · 实时数据 · 7 位 AI 分析师
        </div>
      </div>

      <nav className="flex flex-col gap-0.5 p-2 flex-1">
        {NAV_ENTRIES.map((entry) => (
          <SidebarItem key={entry.to} entry={entry} />
        ))}
      </nav>

      <div className="mt-auto p-3 text-xs text-text-tertiary border-t border-border-1
                      font-mono leading-relaxed">
        <div>⚠️ 仅供学习研究，不构成投资建议</div>
        <div className="mt-1.5 text-text-tertiary">v0.7.0-dev · React SPA + FastAPI</div>
      </div>
    </aside>
  );
}

function SidebarItem({ entry }: { entry: NavEntry }) {
  const baseClasses =
    'flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors';

  if (!entry.enabled) {
    // Disabled: full button shape, muted text, phase pill on the right.
    // No opacity-60 — still looks like a button, just inert.
    return (
      <div
        data-testid={`sidebar-${entry.label}`}
        title={`TODO: ${entry.phase}`}
        aria-disabled="true"
        className={cn(
          baseClasses,
          'bg-bg-surface text-text-secondary cursor-not-allowed'
        )}
      >
        <span className="text-base w-5 text-center opacity-80" aria-hidden>{entry.icon}</span>
        <span className="flex-1">{entry.label}</span>
        <PhaseTag phase={entry.phase} />
      </div>
    );
  }

  // Enabled: real button. Inactive = transparent with hover lift.
  // Active = bb-accent fill background, semibold text, ring, left blue bar
  //          (mirrors elements.css .st-key-nav_* button[kind="primary"]
  //          box-shadow inset 3px 0 0 0 var(--bb-accent-bright)).
  return (
    <NavLink
      to={entry.to}
      data-testid={`sidebar-${entry.label}`}
      className={({ isActive }) =>
        cn(
          baseClasses,
          'bg-transparent text-text-primary hover:bg-bg-surface cursor-pointer',
          isActive &&
            '!bg-bb-accent-glow !text-bb-accent font-semibold ring-1 ring-bb-accent/40 ' +
              'shadow-[inset_3px_0_0_0_var(--bb-accent-bright)]'
        )
      }
    >
      <span className="text-base w-5 text-center" aria-hidden>{entry.icon}</span>
      <span className="flex-1">{entry.label}</span>
    </NavLink>
  );
}
