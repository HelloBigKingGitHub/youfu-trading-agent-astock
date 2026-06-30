import { HTMLAttributes, forwardRef } from "react";

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "buy" | "sell" | "hold" | "overweight" | "underweight";
}

const variantStyles: Record<string, string> = {
  default: "bg-[var(--bg-elevated)] text-[var(--text-secondary)]",
  buy: "bg-[rgba(34,197,94,0.12)] text-[#22c55e]",
  sell: "bg-[rgba(239,68,68,0.12)] text-[#ef4444]",
  hold: "bg-[rgba(251,191,36,0.12)] text-[#fbbf24]",
  overweight: "bg-[rgba(59,130,246,0.12)] text-[#3b82f6]",
  underweight: "bg-[rgba(168,85,247,0.12)] text-[#a855f7]",
};

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ variant = "default", className = "", children, ...props }, ref) => {
    return (
      <span
        ref={ref}
        className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${variantStyles[variant]} ${className}`}
        {...props}
      >
        {children}
      </span>
    );
  }
);

Badge.displayName = "Badge";