const { test, expect } = require("@playwright/test");
const { showCalendarEntry } = require("./helpers/ui");

async function openEntry(page, name) {
  await showCalendarEntry(page, name);
  const entry = page.locator(".planned-entry").filter({ hasText: name }).first();
  await expect(entry).toHaveCount(1);
  await entry.evaluate((element) => {
    for (let node = element; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  });
  return entry;
}

test("@responsive session focus chip and select on a planned unit", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  const name = "Tempolauf nach Distanz";
  let entry = await openEntry(page, name);
  const select = entry.locator("select[name='session_focus']");
  await select.scrollIntoViewIfNeeded();
  await expect(select).toBeVisible();
  await expect(select.locator("option[value='threshold']")).toHaveCount(1);
  await expect(select.locator("option[value='sweet_spot']")).toHaveCount(0);
  await expect(entry.locator("[data-focus-chip='derived'] .planned-badge")).toContainText("≈");
  await expect(entry.locator("select[name='strength_intensity']")).toHaveCount(0);
  // The derived focus is offered next to the empty field; one tap sets it.
  await expect(select).toHaveValue("");
  const suggestion = entry.locator(".planned-focus-form .planned-suggestion-chip");
  await expect(suggestion).toHaveText(/^≈ .+ übernehmen$/);
  expect((await suggestion.boundingBox()).height).toBeGreaterThanOrEqual(32);
  const suggested = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await suggestion.click();
  expect((await suggested).ok()).toBeTruthy();
  await expect(suggestion).toHaveCount(0);
  await expect(select).not.toHaveValue("");
  const saved = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await select.selectOption("threshold");
  expect((await saved).ok()).toBeTruthy();
  await expect(entry.locator("[data-focus-chip='set'] .planned-badge")).toHaveText("Schwelle");
  // A calendar reload keeps the card open with its status and focus.
  await expect(entry.locator(".planned-focus-status")).toHaveText("Gespeichert");
  await select.focus();
  await page.evaluate(async () => { await load(); });
  await expect(entry).toHaveJSProperty("open", true);
  await expect(entry.locator(".planned-focus-status")).toHaveText("Gespeichert");
  await expect(entry.locator("select[name='session_focus']")).toBeFocused();
  await page.reload();
  await page.waitForFunction(() => state.initialStateLoaded);
  entry = await openEntry(page, name);
  const chip = entry.locator("[data-focus-chip='set'] .planned-badge");
  await expect(chip).toHaveText("Schwelle");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  const hit = await entry.locator("select[name='session_focus']").boundingBox();
  expect(hit.height).toBeGreaterThanOrEqual(32);
  // Restore the fixture unit.
  const cleared = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await entry.locator("select[name='session_focus']").selectOption("");
  expect((await cleared).ok()).toBeTruthy();
});

test("@responsive a planned strength unit keeps its field labels whole at phone width", async ({ page }) => {
  // #2370: at 412 px the selects squeezed their inline labels until "Intensität" broke inside the word.
  await page.setViewportSize({ width: 412, height: 900 });
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(() => {
    const today = timezoneDateKey(state.data?.profile?.timezone, new Date());
    state.data.training_calendar = [{ local_id: "pu_strength_2370", date: today, starts_at_local: `${today}T17:00:00`, name: "Oberkörper kurz", type: "WeightTraining", sport: "strength", description: "Schrägbankdrücken: 3x10 @ 25 kg", planned_duration_s: 2400, session_focus: "upper", focus_origin: "set" }];
    renderPlanned(state.data.training_calendar);
    for (let node = document.querySelector(".planned-entry[data-entry-key]"); node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  });
  const fields = page.locator(".planned-entry").filter({ hasText: "Oberkörper kurz" }).first().locator(".planned-focus-field");
  await expect(fields).toHaveCount(2);
  const broken = await fields.evaluateAll((labels) => labels.flatMap((label) => {
    const text = label.firstChild;
    return [...text.textContent.matchAll(/\S+/g)].filter((word) => {
      const range = document.createRange();
      range.setStart(text, word.index);
      range.setEnd(text, word.index + word[0].length);
      return range.getClientRects().length > 1;
    }).map((word) => word[0]);
  }));
  expect(broken).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
