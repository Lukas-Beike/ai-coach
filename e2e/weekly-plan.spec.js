const { test, expect } = require("@playwright/test");

async function openEditor(page) {
  await page.goto("/#more/profile");
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.locator("#weeklyPlanEditor").evaluate((element) => {
    for (let node = element; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  });
  await expect(page.locator("#weeklyPlanEditor .weekly-day")).toHaveCount(8);
}

// The editor re-renders on structural edits and keeps the open days open.
async function day(page, index) {
  const row = page.locator("#weeklyPlanEditor > .weekly-day").nth(index);
  if (!(await row.evaluate((element) => element.open))) await row.locator("summary").click();
  return row;
}

async function saveProfile(page) {
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/profile") && response.request().method() === "PUT");
  await page.locator("#profileForm button[type='submit']").click();
  expect((await saved).ok()).toBeTruthy();
}

test("@responsive weekly plan editor saves, reloads and shows inherited windows muted", async ({ page }) => {
  test.setTimeout(120_000);
  await openEditor(page);
  const days = page.locator("#weeklyPlanEditor > .weekly-day:not(.weekly-default)");
  await expect(days.first().locator(".weekly-summary-text")).toHaveAttribute("data-source", "fallback");
  await expect(days.first().locator(".weekly-summary-text")).toContainText("12:00–13:00");

  let monday = await day(page, 0);
  await monday.getByRole("button", { name: "+ Zeitfenster" }).click();
  monday = await day(page, 0);
  await monday.getByLabel("Zeitfenster von").fill("17:00");
  await monday.getByLabel("Zeitfenster bis").fill("19:00");
  await monday.getByLabel("Maximale Minuten").fill("90");
  await monday.getByLabel("Maximale Minuten").blur();
  monday = await day(page, 0);
  await expect(monday.locator(".weekly-summary-text")).toHaveAttribute("data-source", "profile");
  await expect(monday.locator(".weekly-summary-text")).toContainText("17:00–19:00 · max. 90 min");

  let wednesday = await day(page, 2);
  await wednesday.getByRole("button", { name: "+ Feste Einheit" }).click();
  wednesday = await day(page, 2);
  await wednesday.getByLabel("Sportart").selectOption("strength");
  wednesday = await day(page, 2);
  await wednesday.getByLabel("Art der Einheit").selectOption("legs");
  await wednesday.getByLabel("Dauer in Minuten").fill("60");
  await wednesday.getByLabel("Dauer in Minuten").blur();

  const sunday = await day(page, 6);
  await sunday.getByLabel("Ruhetag").check();
  await expect((await day(page, 6)).locator(".weekly-summary-text")).toHaveText("Ruhetag");

  const stored = JSON.parse(await page.locator("#profileForm input[name='weekly_plan']").inputValue());
  expect(stored.days.mon).toEqual({ windows: ["17:00-19:00"], max_minutes: 90 });
  expect(stored.days.wed.fixed).toEqual([{ sport: "strength", focus: "legs", minutes: 60 }]);
  expect(stored.days.sun).toEqual({ rest_day: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();

  await saveProfile(page);
  await page.reload();
  await openEditor(page);
  const reloaded = page.locator("#weeklyPlanEditor > .weekly-day");
  await expect(reloaded.nth(0).locator(".weekly-summary-text")).toContainText("17:00–19:00");
  await expect(reloaded.nth(2).locator(".weekly-summary-text")).toContainText("Kraft Beine 60′");
  await expect(reloaded.nth(1).locator(".weekly-summary-text")).toHaveAttribute("data-source", "fallback");

  // Restore the fixture profile.
  await page.evaluate(() => {
    const form = document.querySelector("#profileForm");
    form.elements.weekly_plan.value = "";
    form.elements.weekly_plan.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await saveProfile(page);
});

test("@responsive weekly plan rejects a window that ends before it starts", async ({ page }) => {
  await openEditor(page);
  await (await day(page, 3)).getByRole("button", { name: "+ Zeitfenster" }).click();
  const row = await day(page, 3);
  await row.getByLabel("Zeitfenster von").fill("18:00");
  await row.getByLabel("Zeitfenster bis").fill("17:00");
  await expect(row.getByLabel("Zeitfenster bis")).toHaveJSProperty("validationMessage", "Das Ende muss nach dem Beginn liegen.");
});
