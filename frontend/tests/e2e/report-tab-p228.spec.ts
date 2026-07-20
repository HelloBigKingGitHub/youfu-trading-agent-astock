import { expect, test } from '@playwright/test';

/**
 * P2.28 — report tab end-to-end verification.
 *
 * The user reported:
 *   (a) "分析跑完，点击报告报错了：加载分析失败: GET /api/analyze/.../report 404"
 *       — backend runner never set ``results_path`` on the history entry.
 *   (b) "历史中总阶段和完成阶段对不上，总结段为什么只要7个？"
 *       — frontend ``TRADER_REPORTS`` was hardcoded to 7 analyst cards,
 *         missing quality_gate / debate / risk / trader / pm.
 *
 * This test exercises both fixes end-to-end through the real running stack:
 *   1. Open the analyze page.
 *   2. Switch to the history tab.
 *   3. Click the row for a known completed analysis
 *      (600595_2026-07-18_9ee13de6 — the one the user reported).
 *   4. Verify the report tab opens with NO 404 error banner.
 *   5. Verify all 12 stage cards render (not the old 7).
 */
test('P2.28 — completed analysis loads report tab with all 12 stage cards', async ({ page }) => {
  await page.goto('/analyze', { waitUntil: 'networkidle' });

  // Open the history tab so the recent table renders.
  await page.getByTestId('analyze-tab-history').click();
  await expect(page.getByTestId('analysis-recent-table')).toBeVisible();

  // Click the row for the analysis the user reported. handleSelectRecent
  // routes status=ok items to the report tab.
  const row = page.getByTestId('analysis-recent-row-600595_2026-07-18_9ee13de6');
  await expect(row).toBeVisible();
  await row.click();

  // The report panel must mount and render the report root.
  await expect(page.getByTestId('analysis-report')).toBeVisible({ timeout: 10_000 });

  // No 404 error banner — the report endpoint must return 200.
  await expect(page.getByTestId('analysis-report-error')).toHaveCount(0);

  // All 12 cards must render: 7 analyst + quality_gate + debate + risk +
  // trader + pm. Each has a stable testid of `analysis-report-card-<key>`.
  const expectedCards = [
    'market_report',
    'sentiment_report',
    'news_report',
    'fundamentals_report',
    'policy_report',
    'hot_money_report',
    'lockup_report',
    'quality_gate_report',
    'investment_debate_state',
    'risk_debate_state',
    'trader_investment_plan',
    'final_trade_decision',
  ];
  for (const key of expectedCards) {
    await expect(page.getByTestId(`analysis-report-card-${key}`)).toBeVisible();
  }
});