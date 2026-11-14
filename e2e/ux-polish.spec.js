const { test, expect } = require("@playwright/test");
const { renderCalendarSessions, openSessionDetails } = require("./helpers/ui");

// P3 polish of the 2026-11 UX review (#1790).
const style = (locator) => locator.evaluate((element) => {
  const computed = getComputedStyle(element);
  return [computed.backgroundColor, computed.color];
});

test.describe("login", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("names the app, shows the password on demand and marks a rejected one @responsive", async ({ page }) => {
    await page.goto("/");
    const dialog = page.locator("#loginDialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Pacecraft · AI Coach");
    const input = page.getByLabel("Passwort", { exact: true });
    await expect(input).toHaveAttribute("type", "password");
    await dialog.getByRole("button", { name: "Anzeigen", exact: true }).click();
    await expect(input).toHaveAttribute("type", "text");
    await dialog.getByRole("button", { name: "Verbergen", exact: true }).click();
    await expect(input).toHaveAttribute("type", "password");
    await expect(input).not.toHaveAttribute("aria-invalid", "true");
    await input.fill("wrong-password-123");
    await dialog.getByRole("button", { name: "Anmelden", exact: true }).click();
    await expect(page.locator("#loginError")).not.toBeEmpty();
    await expect(input).toHaveAttribute("aria-invalid", "true");
    // The border takes the theme's danger colour once its transition has run.
    await expect(async () => {
      const [border, danger] = await input.evaluate((element) => {
        const probe = document.createElement("i");
        probe.style.color = "var(--danger)";
        document.body.append(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return [getComputedStyle(element).borderTopColor, color];
      });
      expect(border).toBe(danger);
    }).toPass();
  });
});

test.describe("with demo data", () => {
  test.beforeEach(async ({ request }) => {
    expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  });

test("the calendar tab shows a calendar and a selected tab is one filled style @responsive", async ({ page }) => {
  await page.goto("/#analysis/load");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("symbol#icon-plan > rect")).toHaveCount(1);
  const segment = page.locator("#dataPanel .plan-segment-nav a.active");
  const range = page.locator('#analysisLoadPeriod button[aria-pressed="true"]');
  await expect(segment).toBeVisible();
  await expect(range).toBeVisible();
  const [segmentBackground, segmentColor] = await style(segment);
  // A selected tab is the raised surface item with ink text, in either theme.
  const onAccent = await page.evaluate(() => {
    const probe = document.body.appendChild(document.createElement("i"));
    probe.style.color = "var(--ink)";
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  });
  expect(segmentColor).toBe(onAccent);
  // The background of a button eases in; wait for it instead of reading the first frame.
  await expect(range).toHaveCSS("background-color", segmentBackground);
  await expect(range).toHaveCSS("color", segmentColor);
  // The active tab of the main navigation is visibly filled, not only bold.
  const active = page.locator(".nav-item.active:visible").first();
  const parent = await active.evaluate((element) => getComputedStyle(element.parentElement).backgroundColor);
  const [activeBackground] = await style(active);
  expect(activeBackground).not.toBe("rgba(0, 0, 0, 0)");
  expect(activeBackground).not.toBe(parent);
});

test("the calendar has a refresh button and the library rows show a count and a chevron @responsive", async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.locator("#planRefreshButton").click();
  await expect(page.locator("#planRefreshStatus")).toHaveText("Lokale Daten aktualisiert.");
  await page.goto("/#plan/library");
  const row = page.locator(".library-sport > summary").first();
  await expect(row).toContainText(/\d+ Einheit/);
  expect(await row.evaluate((element) => getComputedStyle(element, "::after").content)).not.toBe("none");
});

test("a session's calendar details keep a flat series as a line on a real axis @responsive", async ({ page }) => {
  await page.route(/\/api\/activities\//, (route) => {
    const times = Array.from({ length: 30 }, (_, index) => index * 10);
    return route.fulfill({ json: { session: { activity_id: "flat-ride", sport: "ride" }, metrics: {}, streams: { time_s: times, channels: { heart_rate_bpm: { values: times.map(() => 200) } } }, detail_data: { providers: [] } } });
  });
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.initialStateLoaded);
  await renderCalendarSessions(page, [{ id: "flat-ride", name: "Flat ride", sport: "ride", environment: "outdoor", started_at_local: "2026-10-17T08:30:00", moving_duration_s: 3600, avg_hr: 142 }]);
  const card = page.locator(".planned-entry.is-completed").filter({ hasText: "Flat ride" });
  await expect(card.locator(".planned-session-icon")).toBeVisible();
  await expect(card).toContainText("08:30");
  const details = await openSessionDetails(page, "Flat ride");
  const chart = details.locator(".activity-analysis-chart.is-heart");
  await expect(chart.getByRole("img")).toBeVisible();
  await expect(chart.locator("path.activity-analysis-area")).toHaveCount(0);
  const ticks = (await chart.locator("svg text").allTextContents()).filter((text) => /^\d+$/.test(text)).map(Number);
  expect(Math.max(...ticks) - Math.min(...ticks)).toBeGreaterThanOrEqual(6);
});

test("charts name weeks and space their ticks evenly; a single series does not repeat its title @responsive", async ({ page }) => {
  await page.goto("/#analysis/load");
  await expect(page.locator("#appShell")).toBeVisible();
  const weekly = page.locator("#analysisLoadCharts .analysis-chart-card:has(svg)").first();
  await expect(weekly.locator(".analysis-tick-mark").first()).toBeAttached();
  await expect(weekly.locator(".analysis-week-caption")).toHaveCount(1);
  const positions = await weekly.locator(".analysis-date-tick").evaluateAll((labels) => labels.map((label) => Number(label.getAttribute("x"))));
  expect(positions.length).toBeGreaterThanOrEqual(3);
  const gaps = positions.slice(1).map((value, index) => value - positions[index]);
  for (const gap of gaps) expect(Math.abs(gap - gaps[0])).toBeLessThan(1.5);

  await page.goto("/#nutrition/body");
  const weight = page.locator("#bodyAnalysisCharts .analysis-chart-card:has(svg)").first();
  await expect(weight.locator(".analysis-chart-legend")).toHaveCount(0);
  await expect(weight.getByRole("button", { name: "Gewicht: Informationen" })).toBeVisible();
});

test("a meal shows its source only when it differs from the default @responsive", async ({ page }) => {
  // #2709: the fixture seeds meals once per run, up to the day it ran; read after local midnight,
  // the server's today is empty. The day before today always holds seeded meals.
  await page.goto("/#nutrition/diary");
  await page.getByRole("button", { name: "Vorheriger Tag" }).click();
  await expect(page.locator("#nutritionEntries .nutrition-card").first()).toBeVisible();
  await expect(page.locator("#nutritionEntries")).not.toContainText("Manuelle Angabe");
});
});
