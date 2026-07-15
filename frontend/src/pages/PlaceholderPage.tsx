import * as React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';

export interface PlaceholderPageProps {
  title: string;
  icon: string;
  phase: string;
  description: string;
}

// Placeholder for the 8 sidebar pages not yet implemented.
// Shows route metadata so the user knows the click is wired and where the
// implementation lands in the phase plan.
export function PlaceholderPage({ title, icon, phase, description }: PlaceholderPageProps) {
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>
          <span aria-hidden className="mr-2">{icon}</span>
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div
          data-testid={`placeholder-${title}`}
          className="rounded-md border border-dashed border-border-2 bg-bg-elevated p-6 text-center"
        >
          <div className="text-text-secondary text-sm">TODO: {phase}</div>
          <div className="mt-2 text-text-tertiary text-xs">
            此页面将在后续 Phase 实现。骨架就绪 (router / sidebar / data layer)
          </div>
        </div>
      </CardContent>
    </Card>
  );
}