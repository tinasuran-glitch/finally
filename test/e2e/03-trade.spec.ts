import { test, expect } from "@playwright/test";
import { panel, readUsdStat, tradeViaBar, waitForPortfolioLoaded } from "./helpers";

test.describe("trading via the trade bar", () => {
  test("buy decreases cash, opens a position, updates total", async ({ page }) => {
    await page.goto("/");
    await waitForPortfolioLoaded(page);
    const positions = panel(page, "Positions");
    const cashBefore = await readUsdStat(page, "Cash");

    await tradeViaBar(page, "Buy", "NVDA", 2);

    await expect
      .poll(() => readUsdStat(page, "Cash"))
      .toBeLessThan(cashBefore);

    await expect(positions.locator("tr").filter({ hasText: "NVDA" })).toBeVisible();

    // Total value now reflects the position, so it exceeds remaining cash.
    const cashAfter = await readUsdStat(page, "Cash");
    const totalAfter = await readUsdStat(page, "Total Value");
    expect(totalAfter).toBeGreaterThan(cashAfter);
  });

  test("sell increases cash and closes the position", async ({ page }) => {
    await page.goto("/");
    const positions = panel(page, "Positions");

    await tradeViaBar(page, "Buy", "AMZN", 4);
    await expect(positions.locator("tr").filter({ hasText: "AMZN" })).toBeVisible();
    const cashAfterBuy = await readUsdStat(page, "Cash");

    await tradeViaBar(page, "Sell", "AMZN", 4);

    await expect
      .poll(() => readUsdStat(page, "Cash"))
      .toBeGreaterThan(cashAfterBuy);

    await expect(positions.locator("tr").filter({ hasText: "AMZN" })).toHaveCount(0);
  });
});
