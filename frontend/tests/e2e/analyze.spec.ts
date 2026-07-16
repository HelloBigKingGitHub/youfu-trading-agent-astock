import { expect, test } from '@playwright/test';

test('renders analyze page with all 5 tabs and default new-panel form', async ({ page }) => {
  await page.goto('/analyze', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('analyze-page')).toBeVisible();
  await expect(page.getByRole('heading', { name: '📝 单股分析', level: 1 })).toBeVisible();
  // 5 tab buttons
  await expect(page.getByTestId('analyze-tab-new')).toBeVisible();
  await expect(page.getByTestId('analyze-tab-progress')).toBeVisible();
  await expect(page.getByTestId('analyze-tab-report')).toBeVisible();
  await expect(page.getByTestId('analyze-tab-history')).toBeVisible();
  await expect(page.getByTestId('analyze-tab-workspace')).toBeVisible();
  // Default panel is "new"
  await expect(page.getByTestId('analyze-panel-new')).toBeVisible();
  await expect(page.getByTestId('analysis-form')).toBeVisible();
  await expect(page.getByTestId('ticker-input')).toBeVisible();
  await expect(page.getByTestId('analysis-form-submit')).toBeVisible();
});

test('switching analyze tabs reveals each panel', async ({ page }) => {
  await page.goto('/analyze', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('analyze-page')).toBeVisible();

  await page.getByTestId('analyze-tab-progress').click();
  await expect(page.getByTestId('analyze-panel-progress')).toBeVisible();

  await page.getByTestId('analyze-tab-history').click();
  await expect(page.getByTestId('analyze-panel-history')).toBeVisible();

  await page.getByTestId('analyze-tab-workspace').click();
  await expect(page.getByTestId('analyze-panel-workspace')).toBeVisible();

  await page.getByTestId('analyze-tab-report').click();
  await expect(page.getByTestId('analyze-panel-report')).toBeVisible();
});