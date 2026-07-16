import { expect, test } from '@playwright/test';

// Phase 2.7 — /portfolio page renders 6 inline tabs (总览/流水/配置/预警/导入导出/收益风险)
// + default overview panel + positions table.  Mirrors the contract used by
// batch.spec.ts: heading + 6 tabs + default panel.

test('renders portfolio page with all 6 tabs and default overview panel', async ({ page }) => {
  await page.goto('/portfolio', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('portfolio-page')).toBeVisible();

  // heading carries the 💼 emoji + 我的仓位 wording (mirrors Streamlit tab title)
  await expect(page.getByRole('heading', { name: /我的仓位/ }).first()).toBeVisible();

  // 6 tab buttons (matches Streamlit portfolio_panel.py 6-tab layout)
  await expect(page.getByTestId('portfolio-tab-overview')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-transactions')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-allocation')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-alerts')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-import')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-risk')).toBeVisible();

  // Default panel is overview (positions table)
  await expect(page.getByTestId('portfolio-panel-overview')).toBeVisible();
  // The positions summary banner OR the empty state should be visible on first paint.
  // Both are valid: positions-empty when the store is empty, otherwise the table.
  const empty = page.getByTestId('positions-empty');
  const table = page.getByTestId('positions-table');
  await expect(empty.or(table)).toBeVisible();
});

test('switching portfolio tabs reveals each panel', async ({ page }) => {
  await page.goto('/portfolio', { waitUntil: 'networkidle' });
  await expect(page.getByTestId('portfolio-page')).toBeVisible();

  // Default tab → overview panel visible, others hidden.
  await expect(page.getByTestId('portfolio-panel-overview')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-overview')).toHaveAttribute('aria-selected', 'true');

  // Switch to transactions tab
  await page.getByTestId('portfolio-tab-transactions').click();
  await expect(page.getByTestId('portfolio-panel-transactions')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-transactions')).toHaveAttribute('aria-selected', 'true');

  // Switch to allocation tab
  await page.getByTestId('portfolio-tab-allocation').click();
  await expect(page.getByTestId('portfolio-panel-allocation')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-allocation')).toHaveAttribute('aria-selected', 'true');

  // Switch to alerts tab
  await page.getByTestId('portfolio-tab-alerts').click();
  await expect(page.getByTestId('portfolio-panel-alerts')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-alerts')).toHaveAttribute('aria-selected', 'true');

  // Switch to import/export tab
  await page.getByTestId('portfolio-tab-import').click();
  await expect(page.getByTestId('portfolio-panel-import')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-import')).toHaveAttribute('aria-selected', 'true');

  // Switch to risk tab
  await page.getByTestId('portfolio-tab-risk').click();
  await expect(page.getByTestId('portfolio-panel-risk')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-risk')).toHaveAttribute('aria-selected', 'true');

  // Back to overview
  await page.getByTestId('portfolio-tab-overview').click();
  await expect(page.getByTestId('portfolio-panel-overview')).toBeVisible();
  await expect(page.getByTestId('portfolio-tab-overview')).toHaveAttribute('aria-selected', 'true');
});