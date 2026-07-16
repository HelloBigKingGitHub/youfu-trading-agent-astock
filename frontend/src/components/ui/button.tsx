import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-base font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bb-accent focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-bb-accent text-white hover:bg-bb-accent-bright shadow-sm',
        destructive: 'bg-bb-up text-white hover:opacity-90',
        outline: 'border border-border-2 bg-transparent hover:bg-bg-elevated hover:text-text-primary',
        secondary: 'bg-bg-elevated text-text-primary hover:bg-bg-surface',
        ghost: 'hover:bg-bg-elevated hover:text-text-primary',
        link: 'text-bb-accent underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-11 px-5 py-2.5',
        sm: 'h-9 rounded-md px-3 text-sm',
        lg: 'h-12 rounded-md px-7 text-base',
        icon: 'h-11 w-11',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  )
);
Button.displayName = 'Button';

export { buttonVariants };