const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const fs = require("node:fs/promises");

test("@responsive completed calendar sports meet AA contrast in both themes", async ({ page, request }, testInfo) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(async () => { await AppRouter.navigate("plan/overview", { historyMode: "replace" }); });
  for (const theme of ["dark", "light"]) {
    await page.evaluate((selected) => { document.documentElement.dataset.theme = selected; }, theme);
    for (const sport of ["Radfahren", "Laufen", "Schwimmen", "Kraft"]) {
      const entry = page.locator(`.planned-entry.is-completed[data-sport="${sport}"]`).filter({ hasText: "Synthetic completed" });
      await expect(entry).toHaveCount(1);
      await entry.evaluate((element) => {
        for (let parent = element.parentElement; parent; parent = parent.parentElement) {
          if (parent.tagName === "DETAILS") parent.open = true;
        }
      });
      const header = entry.locator(".planned-session-header");
      await header.scrollIntoViewIfNeeded();
      await expect(header).toBeVisible();
    }
    const geometry = await page.locator(".planned-session-header").evaluateAll((headers) => ({
      width: innerWidth,
      headers: headers.map((header) => {
        const rect = header.getBoundingClientRect();
        return { x: rect.x + scrollX, y: rect.y + scrollY, width: rect.width, height: rect.height };
      }),
    }));
    await fs.writeFile(testInfo.outputPath(`calendar-${theme}.json`), JSON.stringify(geometry));
    await page.screenshot({ path: testInfo.outputPath(`calendar-${theme}.png`), fullPage: true, animations: "disabled" });
    const results = await new AxeBuilder({ page }).include("#plannedCalendar .planned-entry.is-completed .planned-session-header").withRules(["color-contrast"]).analyze();
    expect(results.violations).toEqual([]);
    expect(results.incomplete).toEqual([]);
  }
});
