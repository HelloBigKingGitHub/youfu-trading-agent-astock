import * as React from 'react';
import { cn } from '@/lib/utils';
import { CheckCircle2, AlertCircle, Info, XCircle, X } from 'lucide-react';

type ToastVariant = 'default' | 'success' | 'error' | 'warning';

export interface Toast {
  id: string;
  title?: string;
  description?: string;
  variant?: ToastVariant;
  duration?: number;
}

interface ToastContextValue {
  toast: (t: Omit<Toast, 'id'>) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

const ICONS: Record<ToastVariant, React.ComponentType<{ className?: string }>> = {
  default: Info,
  success: CheckCircle2,
  error: XCircle,
  warning: AlertCircle,
};

const VARIANT_CLASSES: Record<ToastVariant, string> = {
  default: 'border-border-2',
  success: 'border-bb-down/40',
  error: 'border-bb-up/40',
  warning: 'border-yellow-500/40',
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const toast = React.useCallback((t: Omit<Toast, 'id'>) => {
    const id = Math.random().toString(36).slice(2, 9);
    const full: Toast = { duration: 4000, variant: 'default', ...t, id };
    setToasts((prev) => [...prev, full]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((x) => x.id !== id));
    }, full.duration);
  }, []);

  const dismiss = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((x) => x.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-96 max-w-[90vw]">
        {toasts.map((t) => {
          const Icon = ICONS[t.variant ?? 'default'];
          return (
            <div
              key={t.id}
              role="status"
              data-testid={`toast-${t.variant}`}
              className={cn(
                'flex items-start gap-3 rounded-md border bg-bg-elevated p-4 shadow-lg text-text-primary',
                VARIANT_CLASSES[t.variant ?? 'default']
              )}
            >
              <Icon className="h-5 w-5 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                {t.title && <div className="font-semibold text-sm">{t.title}</div>}
                {t.description && <div className="text-xs text-text-secondary mt-1">{t.description}</div>}
              </div>
              <button
                aria-label="Dismiss"
                onClick={() => dismiss(t.id)}
                className="text-text-tertiary hover:text-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}