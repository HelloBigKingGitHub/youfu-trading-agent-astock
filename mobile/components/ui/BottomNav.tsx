"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/", label: "分析", icon: "📊" },
  { href: "/history", label: "历史", icon: "📋" },
  { href: "/settings", label: "设置", icon: "⚙️" },
];

export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-[var(--bg-secondary)] border-t border-[var(--border-subtle)]">
      <div className="flex items-center justify-around h-14 max-w-lg mx-auto px-4">
        {tabs.map((tab) => {
          const isActive = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`
                flex flex-col items-center justify-center gap-0.5 py-1 px-3 rounded-lg min-w-[60px]
                transition-colors duration-200
                ${isActive ? "text-[var(--accent)]" : "text-[var(--text-muted)]"}
              `}
            >
              <span className="text-lg">{tab.icon}</span>
              <span className={`text-xs ${isActive ? "font-medium" : "font-normal"}`}>
                {tab.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}