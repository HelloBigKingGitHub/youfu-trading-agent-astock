import * as React from 'react';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

// Tiny in-house Dialog — same role as shadcn Dialog (overlay + content +
// escape) but without @radix-ui/react-dialog dependency. The History page
// only needs one modal at a time; if other pages need richer a11y later we
// can swap in Radix without changing the call sites.

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  testId?: string;
  footer?: React.ReactNode;
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  className,
  testId,
  footer,
}: DialogProps) {
  // Stable IDs per dialog open cycle so a11y bindings don't drift across
  // re-renders. ``React.useId`` is stable across SSR/CSR boundaries.
  const titleId = React.useId();
  const descriptionId = React.useId();

  // Escape closes; backdrop click closes; body scroll lock while open.
  React.useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      data-testid={testId}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <div
        className={cn(
          'relative z-10 w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-lg border border-border-1 bg-bg-surface shadow-2xl',
          className
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 p-6 border-b border-border-1">
          <div>
            <h2 id={titleId} className="text-xl font-semibold leading-tight text-text-primary">
              {title}
            </h2>
            {description && (
              <p id={descriptionId} className="text-sm text-text-secondary mt-1.5">
                {description}
              </p>
            )}
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded p-1 text-text-tertiary hover:bg-bg-elevated hover:text-text-primary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6">{children}</div>
        {footer && (
          <div className="flex justify-end gap-3 p-6 border-t border-border-1 bg-bg-elevated/30">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
