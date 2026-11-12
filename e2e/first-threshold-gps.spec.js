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
  const response = await loaded;
  expect(response.ok()).toBe(true);
  const enabled = Boolean((await response.json()).enabled);
  await expect(page.locator("#gpsTracksToggle")).toBeChecked({ checked: enabled });
  return enabled;
}

async function flipGpsTracks(page) {
  const saved = page.waitForResponse((response) => response.url().endsWith("/api/privacy/gps") && response.request().method() === "POST");
  await page.locator("#gpsTracksToggle").click();
  expect((await saved).ok()).toBe(true);
}

test("the GPS-tracks switch persists across a reload", async ({ page }) => {
  const before = await openPrivacy(page);
  try {
    await flipGpsTracks(page);
    await expect(page.locator("#gpsTracksToggle")).toBeChecked({ checked: !before });
    await page.reload();
    expect(await openPrivacy(page)).toBe(!before);
  } finally {
    // Restore the fixture state for later specs, also after a failure.
    await page.reload();
    if ((await openPrivacy(page)) !== before) await flipGpsTracks(page);
  }
  await expect(page.locator("#gpsTracksToggle")).toBeChecked({ checked: before });
});

test("the GPS-tracks switch takes clicks once loaded and a failed save restores the confirmed state", async ({ page }) => {
  // #2418: no click before the stored state is shown.
  const isGet = (response) => response.url().endsWith("/api/privacy/gps") && response.request().method() === "GET";
  let releaseLoad;
  let gets = 0;
  const loadHeld = new Promise((resolve) => { releaseLoad = resolve; });
  await page.route("**/api/privacy/gps", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    gets += 1;
    await loadHeld;
    return route.continue();
  });
  await openMore(page, "operations");
  const summary = page.locator("#privacySection summary");
  const toggle = page.locator("#gpsTracksToggle");
  await expect(page.locator("#privacySection")).not.toHaveAttribute("open", "");
  const loaded = page.waitForResponse(isGet);
  await summary.click();
  await expect(toggle).toBeDisabled();
  releaseLoad();
  const before = Boolean((await (await loaded).json()).enabled);
  await expect(toggle).toBeEnabled();
  await expect(toggle).toBeChecked({ checked: before });

  // A pending save takes no click, and a failed one restores the server-confirmed state.
  let failSave;
  const saveHeld = new Promise((resolve) => { failSave = resolve; });
  await page.route("**/api/privacy/gps", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await saveHeld;
    return route.fulfill({ status: 500, json: { error: "Synthetischer Fehler" } });
  });
  await toggle.click();
  await expect(toggle).toBeChecked({ checked: !before });
  await expect(toggle).toBeDisabled();
  // Reopening during the save loads nothing that could overwrite the switch.
  const getsBeforeReopen = gets;
  await summary.click();
  await summary.click();
  await expect(page.locator("#privacySection")).toHaveAttribute("open", "");
  // Give a load a moment to start; none may run, and the switch stays locked.
  await page.waitForTimeout(500);
  expect(gets).toBe(getsBeforeReopen);
  await expect(toggle).toBeDisabled();
  failSave();
  await expect(page.locator("#toast")).toBeVisible();
  await expect(toggle).toBeChecked({ checked: before });
  await expect(toggle).toBeEnabled();
});
