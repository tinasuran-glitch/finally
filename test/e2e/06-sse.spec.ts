import { test, expect } from "@playwright/test";
import { panel, expectPricesStreaming } from "./helpers";

test.describe("SSE streaming", () => {
  test("connection indicator shows LIVE while prices stream", async ({ page }) => {
    await page.goto("/");

    await expect(page.locator("header").getByText("LIVE")).toBeVisible();
    await expectPricesStreaming(panel(page, "Watchlist"));
  });
});
