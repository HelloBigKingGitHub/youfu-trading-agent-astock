import * as React from 'react';
import { cn } from '@/lib/utils';

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        'flex h-12 w-full rounded-md border border-border-2 bg-bg-input px-3.5 py-2.5 text-base text-text-primary',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bb-accent focus-visible:border-bb-accent',
        'disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
      {...props}
    >
      {children}
    </select>
  )
);
Select.displayName = 'Select';