const { test, expect } = require("@playwright/test");

// #1891: the measured first threshold form and the GPS-tracks switch.
test.use({ serviceWorkers: "block" });

async function openMore(page, segment) {
  await page.goto(`/#more/${segment}`);
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.initialStateLoaded);
}

test("saving a measured first threshold confirms, clears the entry and leaves nothing to save", async ({ page }) => {
  const puts = [];
  await page.route("**/api/profile", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    const body = JSON.parse(route.request().postData() || "{}");
    puts.push(body);
    const profile = await page.evaluate(() => ({ ...state.profileBaseline }));
    delete profile.first_threshold_hr;
    delete profile.first_threshold_on;
    await route.fulfill({ json: { ...profile, first_threshold_pct: "82" } });
  });
  await openMore(page, "profile");
  const form = page.locator("#profileForm");
  // #2262: the entry sits behind "Bearbeiten" on LT1 in Zonen & Schwellen.
  await page.locator("#zoneSettings > summary").click();
  await page.locator('#zoneOverview [data-zone-box="thresholds"]').getByRole("button", { name: "Bearbeiten" }).click();

  await form.locator('[name="first_threshold_hr"]').fill("150");
  await form.locator('[name="first_threshold_on"]').fill("2026-11-01");
  await form.getByRole("button", { name: "Athletenkontext speichern" }).click();

  await expect(page.locator("#toast")).toContainText("Profil gespeichert");
  await expect(page.locator("#toast")).not.toContainText("unvollständig");
  expect(puts[0]).toMatchObject({ first_threshold_hr: "150", first_threshold_on: "2026-11-01" });
  await expect(form.locator('[name="first_threshold_hr"]')).toHaveValue("");
  await expect(form.locator('[name="first_threshold_on"]')).toHaveValue("");
  const baseline = await page.evaluate(() => state.profileBaseline);
  expect(baseline.first_threshold_hr || "").toBe("");
  expect(baseline.first_threshold_on || "").toBe("");

  await form.getByRole("button", { name: "Athletenkontext speichern" }).click();
  await expect(page.locator("#profileDirtyIndicator")).toBeHidden();
  await page.waitForTimeout(500);
  expect(puts.filter((body) => "first_threshold_hr" in body)).toHaveLength(1);
  await expect(page.locator("#toast")).not.toContainText("unvollständig");
});

async function openPrivacy(page) {
  await openMore(page, "operations");
  const panel = page.locator("#privacySection");
  const loaded = page.waitForResponse((response) => response.url().endsWith("/api/privacy/gps") && response.request().method() === "GET");
  if (!(await panel.evaluate((element) => element.open))) await panel.locator("summary").click();
  // #2390: start from the state the server reported, once the switch shows it.
  const { enabled } = await (await loaded).json();
  await expect(page.locator("#gpsTracksToggle")).toBeChecked({ checked: Boolean(enabled) });
  return Boolean(enabled);
}

test("the GPS-tracks switch persists across a reload", async ({ page }) => {
  const before = await openPrivacy(page);
  const toggle = page.locator("#gpsTracksToggle");
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/privacy/gps") && response.request().method() === "POST");
  await toggle.click();
  expect((await saved).ok()).toBe(true);
  await expect(toggle).toBeChecked({ checked: !before });

  await page.reload();
  expect(await openPrivacy(page)).toBe(!before);

  // Restore the fixture state for later specs.
  const restored = page.waitForResponse((response) => response.url().endsWith("/api/privacy/gps") && response.request().method() === "POST");
  await page.locator("#gpsTracksToggle").click();
  await restored;
  await expect(page.locator("#gpsTracksToggle")).toBeChecked({ checked: before });
});

test("a failed GPS-tracks save restores the previous switch state", async ({ page }) => {
  const before = await openPrivacy(page);
  const toggle = page.locator("#gpsTracksToggle");
  await page.route("**/api/privacy/gps", (route) => (
    route.request().method() === "POST"
      ? route.fulfill({ status: 500, json: { error: "Synthetischer Fehler" } })
      : route.continue()
  ));
  await toggle.click();
  await expect(page.locator("#toast")).toBeVisible();
  await expect(toggle).toBeChecked({ checked: before });
});
