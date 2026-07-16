import * as React from 'react';
import { Button } from '@/components/ui/button';

// "开始批量分析" CTA — mirrors `web/components/batch_panel.py` line 243-248:
//   submit = st.button("🚀 开始批量分析", type="primary", use_container_width=True)
//
// React equivalent is a single primary button. Caller owns the
// `onClick` + `disabled` + `isSubmitting` state, so this component stays
// purely presentational and easy to reuse inside BatchPage.

export interface StartButtonProps {
  onClick: () => void;
  disabled?: boolean;
  isSubmitting?: boolean;
  totalJobs: number;
}

export function StartButton({
  onClick, disabled, isSubmitting, totalJobs,
}: StartButtonProps) {
  return (
    <Button
      type="button"
      variant="default"
      size="lg"
      onClick={onClick}
      disabled={disabled || totalJobs === 0}
      data-testid="batch-submit"
      className="w-full"
    >
      {isSubmitting ? '提交中…' : `🚀 开始批量分析 (${totalJobs} 个 ticker)`}
    </Button>
  );
}