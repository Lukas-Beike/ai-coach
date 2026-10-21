const { test, expect } = require("@playwright/test");

test("@responsive history panel is absent while diagnosis and logs remain available", async ({ page }) => {
  let historyRequests = 0;
  page.on("request", (request) => { if (request.url().includes("/api/change-history")) historyRequests += 1; });
  await page.goto("/#more/operations");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#changeHistoryRefreshButton, #changeHistoryList, #changeHistoryStatus")).toHaveCount(0);
  await expect(page.getByText("Lokale Änderungshistorie", { exact: true })).toHaveCount(0);
  await page.evaluate(() => AppRouter.navigate("more/operations", { historyMode: "push" }));
  await page.evaluate(() => document.querySelectorAll('details[data-more-segment-panel="operations"]').forEach((section) => { section.open = true; }));
  await expect(page.locator("#diagnosticsButton")).toBeVisible();
  await expect(page.locator("#logsOutput")).toBeVisible();
  expect(historyRequests).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
