const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { waitForSettledState } = require("./helpers/settled-state");

// #2530: WCAG AA text contrast of every main view and segment, collapsibles opened, in both themes.
const THEMES = ["light", "dark"];
// [view label, route, calendar view]. One test per group and theme keeps each test inside the default timeout.
const GROUPS = {
  "Coach und Kalender": [
    ["Coach", "coach"],
    ["Kalender Woche", "plan/overview"],
    ["Kalender Monat", "plan/overview", "month"],
    ["Kalender Bibliothek", "plan/library"],
    ["Kalender Wettkämpfe", "plan/season"],
  ],
  Analyse: ["running", "cycling", "load", "recovery"].map((segment) => [`Analyse ${segment}`, `analysis/${segment}`]),
  "Ernährung": ["diary", "week", "body", "products"].map((segment) => [`Ernährung ${segment}`, `nutrition/${segment}`]),
  Mehr: ["appearance", "profile", "equipment", "connections", "coach", "operations"].map((segment) => [`Mehr ${segment}`, `more/${segment}`]),
};

// Fails with the view, the theme and every failing node with its measured and expected contrast.
// The shell is measured with the first view only: axe walks the whole document, and the other panels stay hidden.
async function expectContrast(page, view, theme, scope) {
  const builder = new AxeBuilder({ page }).withRules(["color-contrast"]);
  const { violations } = await (scope ? builder.include(scope) : builder).analyze();
  const failures = violations.flatMap((violation) => violation.nodes.map((node) => {
    const data = node.any.find((check) => check.id === "color-contrast")?.data || {};
    return `${view} [${theme}] ${node.target.join(" ")}: ${data.contrastRatio} < ${data.expectedContrastRatio} (${data.fgColor} on ${data.bgColor}, ${data.fontSize}, ${data.fontWeight})`;
  }));
  expect(failures, `colour contrast violations:\n${failures.join("\n")}`).toEqual([]);
}

// Theme change and leaving hover transition colours; axe reads them only once they are settled.
async function applyTheme(page, theme) {
  await page.evaluate((selected) => { document.documentElement.dataset.theme = selected; }, theme);
  await page.evaluate(() => Promise.allSettled(document.getAnimations().map((animation) => animation.finished)));
}

async function showView(page, route, calendarView) {
  await page.evaluate((target) => AppRouter.navigate(target, { historyMode: "replace" }), route);
  await waitForSettledState(page);
  await expect(page.locator(".loading-state, [aria-busy='true'], .skeleton")).toHaveCount(0);
  if (calendarView) {
    await page.locator(`.planned-view-switch [data-view="${calendarView}"]`).click();
    await expect(page.locator(`.planned-view-switch [data-view="${calendarView}"]`)).toHaveAttribute("aria-pressed", "true");
  }
  if (route === "plan/overview") {
    // One entry is opened: the month shows the week of a tapped day with sessions below the grid.
    if (calendarView === "month") await page.locator(".planned-month-day:not([disabled]):has(.planned-month-mark)").last().click();
    const entry = page.locator("#plannedCalendar .planned-entry").first();
    await expect(entry).toBeVisible();
    await entry.evaluate((element) => { element.open = true; });
  }
  await page.evaluate(() => {
    // Nested collapsibles render only once their parent is open.
    for (let pass = 0; pass < 3; pass += 1) document.querySelectorAll("details").forEach((element) => { element.open = true; });
  });
  await page.evaluate(() => Promise.allSettled(document.getAnimations().map((animation) => animation.finished)));
}

test.describe("colour contrast sweep", () => {
  for (const [group, views] of Object.entries(GROUPS)) {
    for (const theme of THEMES) {
      test(`@responsive ${group} meets AA contrast in the ${theme} theme`, async ({ page, request }) => {
        expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
        await page.goto("/");
        await page.waitForFunction(() => state.initialStateLoaded);
        await applyTheme(page, theme);
        for (const [view, route, calendarView] of views) {
          await showView(page, route, calendarView);
          await applyTheme(page, theme);
          await expectContrast(page, view, theme, route === "coach" ? "" : ".panel.active");
        }
      });
    }
  }

  test.describe("login dialog", () => {
    // Start unauthenticated; the project default storage state holds the authenticated session.
    test.use({ storageState: { cookies: [], origins: [] } });

    test("@responsive meets AA contrast in both themes", async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("#loginDialog")).toBeVisible();
      for (const theme of THEMES) {
        await applyTheme(page, theme);
        await expectContrast(page, "Anmeldung", theme);
      }
    });
  });
});
