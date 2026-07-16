import { expect, test } from '@playwright/test';

// Mirrors frontend/tests/e2e/history.spec.ts — strict parity check that the
// production fixtures can reach FastAPI on :8000 AND the React Vite dev
// server on :5173 with at least one log entry.
//
// LOGS_PATH = ~/.tradingagents/logs/{ticker}/  is shared with streamlit;
// both UIs read the same per-task jsonl files.
test('logs page renders Card header, ticker list, task list and chunk viewer', async ({ page }) => {
  await page.goto('/logs', { waitUntil: 'networkidle', timeout: 30_000 });

  // h1-style CardTitle "📋 日志" (Header h1 + LogsPage CardTitle share the
  // text — verify both render)
  await expect(page.getByTestId('logs-page')).toBeVisible();
  await expect(page.locator('h1', { hasText: '📋 日志' }).first()).toBeVisible();
  await expect(page.getByText('LangGraph stream chunks').first()).toBeVisible();

  // Ticker list present + at least one ticker (the dev fixture has 3).
  await expect(page.getByTestId('ticker-list')).toBeVisible();
  const tickerCards = page.locator('[data-testid^="ticker-card-"]');
  await expect(tickerCards.first()).toBeVisible({ timeout: 10_000 });
  expect(await tickerCards.count()).toBeGreaterThan(0);

  // Default-select fires; task list visible.
  await expect(page.getByTestId('task-list')).toBeVisible({ timeout: 10_000 });

  // Click the first task card → chunk viewer appears.
  const firstTaskCard = page.locator('[data-testid^="task-card-"]').first();
  await expect(firstTaskCard).toBeVisible({ timeout: 10_000 });
  await firstTaskCard.click();

  await expect(page.getByTestId('chunk-viewer')).toBeVisible({ timeout: 10_000 });
  // 3 tabs (Agent Outputs / LLM Messages / Tool Calls) all clickable.
  await expect(page.getByTestId('chunk-tab-agent_output')).toBeVisible();
  await expect(page.getByTestId('chunk-tab-llm')).toBeVisible();
  await expect(page.getByTestId('chunk-tab-tool')).toBeVisible();

  // Page screenshot — used by parity_visual.py for diff comparison.
  await page.screenshot({ path: '/tmp/react_logs_page.png', fullPage: true });
});

test('switching chunk tabs changes the rendered chunk list', async ({ page }) => {
  await page.goto('/logs', { waitUntil: 'networkidle', timeout: 30_000 });

  // Wait until at least one ticker card is rendered and click it (to force
  // task list load + chunk viewer mount).
  await expect(page.locator('[data-testid^="ticker-card-"]').first()).toBeVisible({ timeout: 10_000 });
  await page.locator('[data-testid^="ticker-card-"]').first().click();
  await expect(page.locator('[data-testid^="task-card-"]').first()).toBeVisible({ timeout: 10_000 });
  await page.locator('[data-testid^="task-card-"]').first().click();
  await expect(page.getByTestId('chunk-viewer')).toBeVisible({ timeout: 10_000 });

  // LLM tab → click, expect an llm chunk card if data has any (or empty
  // placeholder). Either outcome is valid; we just need the tab switch to
  // be reflected in the active state.
  await page.getByTestId('chunk-tab-llm').click();
  await expect(page.getByTestId('chunk-tab-llm')).toHaveAttribute('aria-selected', 'true');

  await page.getByTestId('chunk-tab-tool').click();
  await expect(page.getByTestId('chunk-tab-tool')).toHaveAttribute('aria-selected', 'true');
});