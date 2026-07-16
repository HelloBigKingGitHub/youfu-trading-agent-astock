import { expect, test } from '@playwright/test';

// Mirrors frontend/tests/e2e/settings.spec.ts — strict parity check that the
// production fixtures can reach FastAPI on :8000 AND the React Vite dev
// server on :5173 with at least one history row.
//
// HISTORY_PATH is shared with streamlit; both UIs read the same JSON files.
test('history page renders Card header, filter bar, table and at least one row', async ({ page }) => {
  // The /history page should hit /api/history on the FastAPI server (default
  // Vite baseURL). Use `networkidle` so the React Query fetch + UI settle.
  await page.goto('/history', { waitUntil: 'networkidle', timeout: 30_000 });

  // h1-style CardTitle "📋 历史报告" + brief "历史分析记录查询" subtitle
  await expect(page.getByTestId('history-page')).toBeVisible();
  await expect(page.locator('h1, h2', { hasText: '📋 历史报告' }).first()).toBeVisible();
  await expect(page.getByText('历史分析记录查询').first()).toBeVisible();

  // FilterBar present with all 5 controls
  await expect(page.getByTestId('history-filter-bar')).toBeVisible();
  await expect(page.getByTestId('filter-ticker')).toBeVisible();
  await expect(page.getByTestId('filter-signal')).toBeVisible();
  await expect(page.getByTestId('filter-status')).toBeVisible();
  await expect(page.getByTestId('filter-search')).toBeVisible();
  await expect(page.getByTestId('filter-refresh')).toBeVisible();

  // Body table present
  await expect(page.getByTestId('history-table-body')).toBeVisible();

  // At least one row (history dir has 88 entries on the dev fixture).
  await expect(page.locator('[data-testid^="history-row-"]').first()).toBeVisible({ timeout: 10_000 });

  // Total counter mirrors API /api/history total
  const total = await page.getByTestId('history-total').innerText();
  expect(Number(total)).toBeGreaterThan(0);

  // Page screenshot — used by parity_visual.py for diff comparison.
  await page.screenshot({ path: '/tmp/react_history_page.png', fullPage: true });
});

test('clicking a history row opens the detail dialog', async ({ page }) => {
  await page.goto('/history', { waitUntil: 'networkidle', timeout: 30_000 });

  const firstRow = page.locator('[data-testid^="history-row-"]').first();
  await expect(firstRow).toBeVisible({ timeout: 10_000 });

  await firstRow.click();

  await expect(page.getByTestId('history-detail-dialog')).toBeVisible();
  await expect(page.getByTestId('history-detail-close')).toBeVisible();
});
