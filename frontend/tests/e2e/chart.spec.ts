import { expect, test } from '@playwright/test';

test('renders chart page with default ticker', async ({ page }) => {
  await page.goto('/chart?ticker=600595&range=6m', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('chart-page')).toBeVisible();
  await expect(page.getByTestId('chart-ticker-input')).toBeVisible();
  await expect(page.getByTestId('chart-range-6m')).toHaveAttribute('aria-pressed', 'true');
});

test('chart range switch reloads the selected range', async ({ page }) => {
  await page.goto('/chart?ticker=600595&range=6m', { waitUntil: 'networkidle' });
  await page.getByTestId('chart-range-1m').click();
  await expect(page).toHaveURL(/\/chart\?ticker=600595&range=1m/);
  await expect(page.getByTestId('chart-range-1m')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('chart-page')).toBeVisible();
});
