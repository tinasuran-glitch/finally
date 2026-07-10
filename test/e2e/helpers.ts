import { type Page, type Locator, expect } from "@playwright/test";

/** Parse a formatted USD string like "$10,000.00" into a number. */
export function parseUsd(text: string): number {
  return Number(text.replace(/[^0-9.-]/g, ""));
}

/** The value <span> next to a header stat label ("Cash", "Total Value"). */
export function headerStat(page: Page, label: string): Locator {
  return page
    .locator("header")
    .getByText(label, { exact: true })
    .locator("xpath=following-sibling::span[1]");
}

export async function readUsdStat(page: Page, label: string): Promise<number> {
  return parseUsd(await headerStat(page, label).innerText());
}

/**
 * Wait until the portfolio has loaded from `/api/portfolio`. The header stats
 * render "$0.00" from the initial store state until the fetch resolves, so any
 * test that reads Cash right after `goto` must wait for a real value first.
 */
export async function waitForPortfolioLoaded(page: Page): Promise<void> {
  await expect(headerStat(page, "Cash")).not.toHaveText("$0.00");
}

/** A dashboard panel <section> located by its uppercase title heading. */
export function panel(page: Page, title: string): Locator {
  return page.locator("section").filter({
    has: page.getByRole("heading", { name: title }),
  });
}

/** Execute a market order via the trade bar and wait for the result toast. */
export async function tradeViaBar(
  page: Page,
  side: "Buy" | "Sell",
  ticker: string,
  qty: number,
): Promise<void> {
  // The trade bar mirrors the selected watchlist ticker: once the watchlist
  // loads, an effect overwrites this input with the default selection. Wait for
  // that default to land before typing, otherwise our value gets clobbered.
  const tickerInput = page.getByLabel("Ticker", { exact: true });
  await expect(tickerInput).not.toHaveValue("");
  await tickerInput.fill(ticker);
  await expect(tickerInput).toHaveValue(ticker);
  await page.getByLabel("Quantity").fill(String(qty));
  await page.getByRole("button", { name: side, exact: true }).click();
  const expected = side === "Buy" ? "Bought" : "Sold";
  await expect(page.getByText(new RegExp(`${expected}\\s`))).toBeVisible();
}

/** Wait until the price stream has updated at least one visible price. */
export async function expectPricesStreaming(watchlist: Locator): Promise<void> {
  const snapshot = () =>
    watchlist.locator("li span.tnum").allInnerTexts().then((a) => a.join("|"));
  const initial = await snapshot();
  await expect.poll(snapshot, { timeout: 15_000 }).not.toBe(initial);
}
