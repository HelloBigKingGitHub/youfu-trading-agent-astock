import { expect, test } from '@playwright/test';

test('renders schedule page with all 5 tabs and default overview panel', async ({ page }) => {
  await page.goto('/schedule', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('schedule-page')).toBeVisible();
  await expect(page.getByRole('heading', { name: /定时分析/ })).toBeVisible();
  // 5 tab buttons
  await expect(page.getByTestId('schedule-tab-overview')).toBeVisible();
  await expect(page.getByTestId('schedule-tab-runs')).toBeVisible();
  await expect(page.getByTestId('schedule-tab-watchlist')).toBeVisible();
  await expect(page.getByTestId('schedule-tab-notifier')).toBeVisible();
  await expect(page.getByTestId('schedule-tab-create')).toBeVisible();
  // Default panel is overview
  await expect(page.getByTestId('schedule-panel-overview')).toBeVisible();
});

test('switching schedule tabs reveals each panel', async ({ page }) => {
  await page.goto('/schedule', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('schedule-page')).toBeVisible();

  await page.getByTestId('schedule-tab-watchlist').click();
  await expect(page.getByTestId('schedule-panel-watchlist')).toBeVisible();

  await page.getByTestId('schedule-tab-notifier').click();
  await expect(page.getByTestId('schedule-panel-notifier')).toBeVisible();
  await expect(page.getByTestId('notifier-config')).toBeVisible();

  await page.getByTestId('schedule-tab-create').click();
  await expect(page.getByTestId('schedule-panel-create')).toBeVisible();
  await expect(page.getByTestId('schedule-form')).toBeVisible();
  await expect(page.getByTestId('schedule-form-name')).toBeVisible();
  await expect(page.getByTestId('schedule-form-cron')).toBeVisible();
});