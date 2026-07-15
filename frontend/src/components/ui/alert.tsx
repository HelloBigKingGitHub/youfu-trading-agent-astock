import * as React from 'react';
import { cn } from '@/lib/utils';

// Minimal Alert — for inline banners (success / error / info). Mirrors shadcn.
type AlertVariant = 'default' | 'destructive' | 'success' | 'warning';

const VARIANT: Record<AlertVariant, string> = {
  default: 'border-border-2 bg-bg-elevated text-text-primary',
  destructive: 'border-bb-up/40 bg-bb-up/10 text-bb-up',
  success: 'border-bb-down/40 bg-bb-down/10 text-bb-down',
  warning: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-500',
};

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: AlertVariant;
}

export const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = 'default', ...props }, ref) => (
    <div
      ref={ref}
      role="alert"
      className={cn('relative w-full rounded-lg border p-4 [&>svg~*]:pl-7 [&>svg+div]:translate-y-[-3px]', VARIANT[variant], className)}
      {...props}
    />
  )
);
Alert.displayName = 'Alert';

export const AlertTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h5 ref={ref} className={cn('mb-1 font-medium leading-none tracking-tight', className)} {...props} />
  )
);
AlertTitle.displayName = 'AlertTitle';

export const AlertDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('text-sm [&_p]:leading-relaxed', className)} {...props} />
  )
);
AlertDescription.displayName = 'AlertDescription';