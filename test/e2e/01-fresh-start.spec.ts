import { test, expect } from "@playwright/test";
import { panel, headerStat, expectPricesStreaming } from "./helpers";

const DEFAULT_TICKERS = [
  "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
  "NVDA", "META", "JPM", "V", "NFLX",
];

test.describe("fresh start", () => {
  test("default watchlist, $10k cash, and streaming prices", async ({ page }) => {
    await page.goto("/");

    const watchlist = panel(page, "Watchlist");
    await expect(watchlist).toBeVisible();

    for (const ticker of DEFAULT_TICKERS) {
      await expect(watchlist.getByText(ticker, { exact: true })).toBeVisible();
    }

    // Untouched seed: $10,000 cash and $10,000 total value.
    await expect(headerStat(page, "Cash")).toHaveText("$10,000.00");
    await expect(headerStat(page, "Total Value")).toHaveText("$10,000.00");

    // No positions yet.
    await expect(
      panel(page, "Positions").getByText(/hold no positions/i),
    ).toBeVisible();

    // Prices are live: at least one displayed value changes on the stream.
    await expectPricesStreaming(watchlist);

    // Connection indicator reflects the live stream.
    await expect(page.locator("header").getByText("LIVE")).toBeVisible();
  });
});
