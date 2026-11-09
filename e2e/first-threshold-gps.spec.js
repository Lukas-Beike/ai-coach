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
  const sources = form.locator("details.profile-section").filter({ has: page.locator('[name="first_threshold_hr"]') });
  if (!(await sources.evaluate((element) => element.open))) await sources.locator("summary").click();

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
  await loaded;
}

test("the GPS-tracks switch persists across a reload", async ({ page }) => {
  await openPrivacy(page);
  const toggle = page.locator("#gpsTracksToggle");
  const before = await toggle.isChecked();
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/privacy/gps") && response.request().method() === "POST");
  await toggle.click();
  expect((await saved).ok()).toBe(true);
  await expect(toggle).toBeChecked({ checked: !before });

  await page.reload();
  await openPrivacy(page);
  await expect(page.locator("#gpsTracksToggle")).toBeChecked({ checked: !before });

  // Restore the fixture state for later specs.
  const restored = page.waitForResponse((response) => response.url().endsWith("/api/privacy/gps") && response.request().method() === "POST");
  await page.locator("#gpsTracksToggle").click();
  await restored;
  await expect(page.locator("#gpsTracksToggle")).toBeChecked({ checked: before });
});

test("a failed GPS-tracks save restores the previous switch state", async ({ page }) => {
  await openPrivacy(page);
  const toggle = page.locator("#gpsTracksToggle");
  const before = await toggle.isChecked();
  await page.route("**/api/privacy/gps", (route) => (
    route.request().method() === "POST"
      ? route.fulfill({ status: 500, json: { error: "Synthetischer Fehler" } })
      : route.continue()
  ));
  await toggle.click();
  await expect(page.locator("#toast")).toBeVisible();
  await expect(toggle).toBeChecked({ checked: before });
});
