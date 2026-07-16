import { expect, test } from '@playwright/test';

test('renders sector page with all 5 tabs and default heatmap panel', async ({ page }) => {
  await page.goto('/sector', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('sector-page')).toBeVisible();
  await expect(page.getByRole('heading', { name: /板块轮动/ })).toBeVisible();
  // 5 tab buttons
  await expect(page.getByTestId('sector-tab-heatmap')).toBeVisible();
  await expect(page.getByTestId('sector-tab-top-stocks')).toBeVisible();
  await expect(page.getByTestId('sector-tab-concepts')).toBeVisible();
  await expect(page.getByTestId('sector-tab-limit-up')).toBeVisible();
  await expect(page.getByTestId('sector-tab-digest')).toBeVisible();
  // Default panel is heatmap
  await expect(page.getByTestId('sector-panel-heatmap')).toBeVisible();
});

test('switching sector tabs reveals each panel', async ({ page }) => {
  await page.goto('/sector', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('sector-page')).toBeVisible();

  await page.getByTestId('sector-tab-top-stocks').click();
  await expect(page.getByTestId('sector-panel-top_stocks')).toBeVisible();
  await expect(page.getByTestId('sector-tab-top-stocks')).toHaveAttribute('aria-selected', 'true');

  await page.getByTestId('sector-tab-concepts').click();
  await expect(page.getByTestId('sector-panel-concepts')).toBeVisible();

  await page.getByTestId('sector-tab-limit-up').click();
  await expect(page.getByTestId('sector-panel-limit_up')).toBeVisible();

  await page.getByTestId('sector-tab-digest').click();
  await expect(page.getByTestId('sector-panel-digest')).toBeVisible();
  await expect(page.getByTestId('digest-markdown')).toBeVisible();
});