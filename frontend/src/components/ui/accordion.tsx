/**
 * Accordion — radix-ui/react-accordion wrapper using the project's cva + cn +
 * forwardRef convention (cf. ui/button.tsx, ui/tabs.tsx).
 *
 * P2.29 — used by ``analysis-report.tsx`` to collapse the seven analyst sections
 * (market / sentiment / news / fundamentals / policy / hot_money / lockup)
 * into a single dense block instead of seven stacked full-height cards. Each
 * AccordionItem child *must* carry the analysis-report-card-{key} testid so
 * the E2E suite (``tests/e2e/report-tab-p228.spec.ts``) continues to find
 * all 12 cards.
 */
import * as React from 'react';
import * as AccordionPrimitive from '@radix-ui/react-accordion';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';

export const Accordion = AccordionPrimitive.Root;

export const AccordionItem = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Item>
>(({ className, ...props }, ref) => (
  <AccordionPrimitive.Item
    ref={ref}
    className={cn(
      'rounded-md border border-border-2 bg-bg-elevated/40',
      className,
    )}
    {...props}
  />
));
AccordionItem.displayName = 'AccordionItem';

export const AccordionTrigger = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <AccordionPrimitive.Header className="flex">
    <AccordionPrimitive.Trigger
      ref={ref}
      className={cn(
        'flex flex-1 items-center justify-between gap-2 px-4 py-3 text-sm font-medium text-text-primary transition-all',
        'hover:bg-bg-surface/60',
        '[&[data-state=open]>svg]:rotate-180',
        className,
      )}
      {...props}
    >
      {children}
      <ChevronDown className="h-4 w-4 shrink-0 text-text-tertiary transition-transform duration-200" />
    </AccordionPrimitive.Trigger>
  </AccordionPrimitive.Header>
));
AccordionTrigger.displayName = 'AccordionTrigger';

export const AccordionContent = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <AccordionPrimitive.Content
    ref={ref}
    className={cn(
      'overflow-hidden text-sm',
      'data-[state=closed]:animate-accordion-up',
      'data-[state=open]:animate-accordion-down',
    )}
    {...props}
  >
    <div className={cn('px-4 pb-4 pt-2', className)}>{children}</div>
  </AccordionPrimitive.Content>
));
AccordionContent.displayName = 'AccordionContent';
