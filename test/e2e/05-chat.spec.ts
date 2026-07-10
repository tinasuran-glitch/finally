import { test, expect } from "@playwright/test";
import { panel, readUsdStat, waitForPortfolioLoaded } from "./helpers";

test.describe("AI chat (mocked)", () => {
  test("a chat command executes a trade and shows it inline", async ({ page }) => {
    await page.goto("/");
    await waitForPortfolioLoaded(page);
    const positions = panel(page, "Positions");
    const cashBefore = await readUsdStat(page, "Cash");

    await page.getByLabel("Message FinAlly").fill("buy 3 META");
    await page.getByRole("button", { name: "Send", exact: true }).click();

    // Assistant reply from the deterministic mock.
    await expect(page.getByText(/\[MOCK\] Executing:/i)).toBeVisible();
    // Inline action confirmation chip.
    await expect(page.getByText(/Bought\s+3\s+META/)).toBeVisible();

    // The trade actually executed: cash dropped and the position opened.
    await expect
      .poll(() => readUsdStat(page, "Cash"))
      .toBeLessThan(cashBefore);
    await expect(positions.locator("tr").filter({ hasText: "META" })).toBeVisible();
  });
});
