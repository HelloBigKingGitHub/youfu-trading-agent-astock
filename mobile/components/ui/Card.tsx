import { HTMLAttributes, forwardRef } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "elevated" | "bordered";
}

const variantStyles: Record<string, string> = {
  default: "bg-[var(--bg-card)]",
  elevated: "bg-[var(--bg-elevated)] shadow-xl shadow-black/40",
  bordered: "bg-[var(--bg-card)] border border-[var(--border-subtle)]",
};

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ variant = "default", className = "", children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={`rounded-2xl p-4 ${variantStyles[variant]} ${className}`}
        {...props}
      >
        {children}
      </div>
    );
  }
);

Card.displayName = "Card";