import { test, expect } from "@playwright/test";
import { panel } from "./helpers";

test.describe("watchlist management", () => {
  test("add and remove a ticker", async ({ page }) => {
    await page.goto("/");
    const watchlist = panel(page, "Watchlist");
    const NEW = "PLTR";

    await expect(watchlist.getByText(NEW, { exact: true })).toHaveCount(0);

    await watchlist.getByLabel("Add ticker to watchlist").fill(NEW);
    await watchlist.getByRole("button", { name: "+" }).click();

    // Appears in the list with a streamed price.
    const row = watchlist.locator("li").filter({ hasText: NEW });
    await expect(row).toBeVisible();
    await expect(row.locator("span.tnum").first()).not.toHaveText("");

    // Remove it.
    await row.hover();
    await watchlist.getByRole("button", { name: `Remove ${NEW}` }).click();
    await expect(watchlist.getByText(NEW, { exact: true })).toHaveCount(0);
  });
});
