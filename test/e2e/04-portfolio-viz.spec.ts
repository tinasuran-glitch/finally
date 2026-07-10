import { test, expect } from "@playwright/test";
import { panel, tradeViaBar } from "./helpers";

test.describe("portfolio visualizations", () => {
  test("heatmap renders a position and the P&L chart has data", async ({ page }) => {
    await page.goto("/");

    // Ensure at least one position exists to visualize.
    await tradeViaBar(page, "Buy", "TSLA", 3);

    const heatmap = panel(page, "Position Heatmap");
    // Treemap draws an SVG cell (rect) per position.
    await expect(heatmap.locator("svg rect").first()).toBeVisible();

    const pnl = panel(page, "Portfolio Value");
    await expect(pnl.locator("svg")).toBeVisible();
    // The area series renders at least one path once snapshots exist.
    await expect(pnl.locator("svg path").first()).toBeVisible();
  });
});
