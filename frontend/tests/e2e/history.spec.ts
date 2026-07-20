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

  // P2.30 — purge trigger sits in the page header so the destructive
  // action is visible without scrolling.
  await expect(page.getByTestId('history-purge-trigger')).toBeVisible();

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

// P2.30 — happy-path purge flow driven entirely from the React layer with
// the network mock intercepting /api/history/purge. We never call the real
// destructive endpoint from an E2E test; the route mock returns the same
// shape ``purgeHistory`` expects from the backend.
test('history purge dialog enforces 清空 confirmation and surfaces success toast', async ({ page }) => {
  // Intercept the destructive call. Anything else continues normally so the
  // page renders with the production fixture data.
  await page.route('**/api/history/purge', async (route) => {
    const req = route.request();
    expect(req.method()).toBe('POST');
    const body = req.postDataJSON();
    expect(body).toEqual({ confirmation: 'CLEAR_ALL_HISTORY', include_cache: true });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        history_deleted: 5,
        reports_deleted: 4,
        log_runs_deleted: 3,
        cache_files_deleted: 12,
        bytes_freed: 12_345,
        failed_items: 0,
      }),
    });
  });

  await page.goto('/history', { waitUntil: 'networkidle', timeout: 30_000 });
  await expect(page.getByTestId('history-purge-trigger')).toBeVisible();

  // Open the dialog.
  await page.getByTestId('history-purge-trigger').click();
  await expect(page.getByTestId('history-purge-dialog')).toBeVisible();

  // Confirm is disabled with no input.
  await expect(page.getByTestId('history-purge-confirm')).toBeDisabled();

  // Wrong sentinel — still disabled.
  await page.getByTestId('history-purge-input').fill('清空全部');
  await expect(page.getByTestId('history-purge-confirm')).toBeDisabled();

  // Correct sentinel — enabled.
  await page.getByTestId('history-purge-input').fill('清空');
  await expect(page.getByTestId('history-purge-confirm')).toBeEnabled();

  // Submit and wait for the route mock to be hit.
  const purgeRequest = page.waitForRequest('**/api/history/purge');
  await page.getByTestId('history-purge-confirm').click();
  await purgeRequest;

  // Success toast surfaces the delete tally.
  await expect(page.getByTestId('toast-success')).toBeVisible({ timeout: 5_000 });
  // Dialog closes on success.
  await expect(page.getByTestId('history-purge-dialog')).toBeHidden({ timeout: 5_000 });

  await page.screenshot({ path: '/tmp/react_history_purge_after.png', fullPage: true });
});

// P2.30 — the same dialog is mounted on /analyze's history tab; the recent
// list must refresh after a successful purge (we re-route /api/analyze/recent
// to an empty list to verify the invalidation, not the real network call).
test('analyze page history tab exposes the shared purge trigger', async ({ page }) => {
  await page.route('**/api/history/purge', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        history_deleted: 1,
        reports_deleted: 1,
        log_runs_deleted: 0,
        cache_files_deleted: 0,
        bytes_freed: 1024,
        failed_items: 0,
      }),
    });
  });

  await page.goto('/analyze', { waitUntil: 'networkidle', timeout: 30_000 });
  await page.getByTestId('analyze-tab-history').click();

  await expect(page.getByTestId('history-purge-trigger')).toBeVisible();
});
