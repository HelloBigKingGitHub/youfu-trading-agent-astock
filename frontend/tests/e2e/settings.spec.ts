import { expect, test } from '@playwright/test';

test('settings page renders its form and captures a screenshot', async ({ page }) => {
  await page.goto('/settings', { waitUntil: 'networkidle' });

  await expect(page.locator('h1')).toContainText('设置');
  await expect(page.getByTestId('settings-form')).toBeVisible();
  await expect(page.getByTestId('settings-provider')).toBeVisible();
  await expect(page.getByTestId('settings-deep')).toBeVisible();
  await expect(page.getByTestId('settings-quick')).toBeVisible();
  await expect(page.getByTestId('settings-baseurl')).toBeVisible();
  await expect(page.getByRole('button', { name: /保存/ })).toBeVisible();

  await page.screenshot({ path: '/tmp/react_settings_page.png', fullPage: true });
});
