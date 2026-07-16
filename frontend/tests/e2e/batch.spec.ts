import { expect, test } from '@playwright/test';

// Phase 2.6 — /batch page renders 3 inline tabs + ticker input + start button.
// Mirrors the contract used by sector.spec.ts: heading + tabs + default panel.

test('renders batch page with all 3 tabs and default submit panel', async ({ page }) => {
  await page.goto('/batch', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('batch-page')).toBeVisible();
  // heading carries the 📊 emoji + 批量分析 wording (mirrors Streamlit tab title)
  await expect(page.getByRole('heading', { name: /批量分析/ }).first()).toBeVisible();
  // 3 tab buttons (matches Streamlit batch_panel.py 3-tab layout)
  await expect(page.getByTestId('batch-tab-submit')).toBeVisible();
  await expect(page.getByTestId('batch-tab-progress')).toBeVisible();
  await expect(page.getByTestId('batch-tab-history')).toBeVisible();
  // Default panel is the submit form (ticker textarea + config form + start CTA)
  await expect(page.getByTestId('batch-panel-submit')).toBeVisible();
  await expect(page.getByTestId('ticker-input')).toBeVisible();
  await expect(page.getByTestId('batch-config-form')).toBeVisible();
  await expect(page.getByTestId('batch-submit')).toBeVisible();
});

test('switching batch tabs reveals each panel', async ({ page }) => {
  await page.goto('/batch', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('batch-page')).toBeVisible();

  // Default tab → submit panel is visible, progress panel hidden until a batch exists.
  await expect(page.getByTestId('batch-panel-submit')).toBeVisible();
  await expect(page.getByTestId('batch-tab-submit')).toHaveAttribute('aria-selected', 'true');

  // History tab is always enabled — it just lists what the backend has.
  await page.getByTestId('batch-tab-history').click();
  await expect(page.getByTestId('batch-panel-history')).toBeVisible();
  await expect(page.getByTestId('batch-tab-history')).toHaveAttribute('aria-selected', 'true');

  // Submit tab is reachable again.
  await page.getByTestId('batch-tab-submit').click();
  await expect(page.getByTestId('batch-panel-submit')).toBeVisible();
  await expect(page.getByTestId('batch-tab-submit')).toHaveAttribute('aria-selected', 'true');
});
