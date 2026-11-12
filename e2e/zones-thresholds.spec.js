const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

// #2262: Zonen & Schwellen as one page per sport, LT1 and LT2 on top, every zone kind below.
const GARMIN_HR = { key: "garmin|heart_rate|||2026-11-09", source: "garmin", label: "Garmin", sport: null, metric: "heart_rate", environment: null, valid_from: "2026-11-09", valid_until: null, threshold: 163, maximum: 186, limits: [130, 145, 155, 166], percent_limits: null, percent_basis: null };
const ZONES = {
  sports: ["ride", "run", "swim"],
  today: "2026-11-12",
  configurations: [GARMIN_HR],
  effective: ["ride", "run", "swim"].map((sport) => ({ sport, metric: "heart_rate", environment: null, key: GARMIN_HR.key })),
  threshold_warnings: { items: [{ label: "FTP", value_text: "285 W", source_label: "Garmin", age_days: 70, reason: "stale" }] },
};

async function openProfile(page) {
  await page.route("**/api/zones", (route) => (route.request().method() === "GET" ? route.fulfill({ json: ZONES }) : route.fallback()));
  await page.goto("/#more/profile");
  await expect(page.locator("#appShell")).toBeVisible();
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(() => {
    state.data.performance = { ...state.data.performance, metrics: { ...state.data.performance?.metrics,
      cycling_ftp_watts: { value: 285, unit: "W", source: "Garmin Connect", observed_at: "2026-11-09" },
      bike_threshold_hr_bpm: { value: 163, unit: "bpm", source: "Garmin Connect", observed_at: "2026-11-09" },
      run_threshold_pace_seconds_per_km: { value: 268, unit: "s/km", source: "Garmin Connect", observed_at: "2026-11-09" },
      run_threshold_hr_bpm: { value: 168, unit: "bpm", source: "Garmin Connect", observed_at: "2026-11-09" } } };
    state.data.profile = { ...state.data.profile, first_threshold_pct: "87", first_threshold_origin: "estimated" };
  });
}

test("@responsive the profile sections start closed in their new order, zones between goals and training", async ({ page }) => {
  await openProfile(page);
  const sections = page.locator("#profileForm details.profile-section");
  await expect(sections.locator(":scope > summary .collapsible-summary-title")).toHaveText(["Person", "Ziele & Woche", "Zonen & Schwellen", "Training", "Quellen & Coach"]);
  for (const section of await sections.all()) await expect(section).not.toHaveAttribute("open", "");
  // A stale threshold no longer opens the section; the summary names it.
  await page.evaluate(() => renderZoneWarnings({ items: [{ label: "FTP", value_text: "285 W", source_label: "Garmin", age_days: 70 }] }));
  await expect(page.locator("#zoneSettings")).not.toHaveAttribute("open", "");
  await expect(page.locator("#zoneSummary")).toHaveText("1 Wert veraltet");
  // The first threshold left Quellen & Coach.
  await expect(sections.nth(4).locator('[name="first_threshold_hr"]')).toHaveCount(0);
  // Opening the profile again closes what was open.
  await sections.first().locator(":scope > summary").click();
  await page.evaluate(() => { location.hash = "#coach"; });
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await page.evaluate(() => { location.hash = "#more/profile"; });
  await expect(sections.first()).not.toHaveAttribute("open", "");
});

test("@responsive each sport shows LT1 and LT2 and its zone kinds, and Bearbeiten opens a prefilled editor", async ({ page }) => {
  await openProfile(page);
  await page.locator("#zoneSettings > summary").click();
  const overview = page.locator("#zoneOverview");
  const thresholds = overview.locator('[data-zone-box="thresholds"]');
  await expect(thresholds.locator('[data-threshold="lt2-main"]')).toHaveText("285 W");
  await expect(thresholds.locator('[data-threshold="lt2-hr"]')).toHaveText("163 bpm");
  await expect(thresholds.locator('[data-threshold="lt1-hr"]')).toHaveText("142 bpm");
  // Without power zones LT1 power has no zone 2 to read.
  await expect(thresholds.locator('[data-threshold="lt1-main"]')).toHaveText("—");
  await expect(thresholds).toContainText("LT1 aus der Herzfrequenzvariabilität (App)");
  await expect(thresholds).toContainText("LT2 von Garmin Connect");
  const heart = overview.locator('[data-zone-box="heart_rate"]');
  await expect(heart.locator(".zone-list li")).toHaveCount(5);
  await expect(heart).toContainText("Garmin, gilt für alle Sportarten");
  const power = overview.locator('[data-zone-box="power"]');
  await expect(power).toContainText("Noch keine Werte –");
  // "Anlegen" opens the editor with the current FTP.
  await power.getByRole("button", { name: "Anlegen" }).click();
  const editor = page.locator("#zoneEditor");
  await expect(editor).toBeVisible();
  await expect(page.locator("#zoneThreshold")).toHaveValue("285");
  expect(await editor.evaluate((node) => node.previousElementSibling.dataset.zoneBox)).toBe("power");
  // Garmin's all-sports zones prefill the heart-rate editor.
  await heart.getByRole("button", { name: "Bearbeiten" }).click();
  await expect(page.locator("#zoneThreshold")).toHaveValue("163");
  await expect(page.locator("#zoneMaximum")).toHaveValue("186");
  await expect(page.locator("#zoneLimits")).toHaveValue("130, 145, 155, 166");
  await expect(page.locator("#zoneEnvironment")).toBeVisible();
  // Editing the zone form does not mark the profile unsaved.
  await page.locator("#zoneLimits").fill("130, 145, 155, 167");
  await expect(page.locator("#profileDirtyIndicator")).toBeHidden();
  // LT1 opens the first-threshold entry under the thresholds.
  await thresholds.getByRole("button", { name: "Bearbeiten" }).click();
  await expect(page.locator("#firstThresholdEditor")).toBeVisible();
  await expect(editor).toBeHidden();
  await expect(page.locator('#firstThresholdEditor [name="first_threshold_hr"]')).toBeVisible();
  // Laufen shows pace and its own LT1.
  await page.locator('#zoneSportTabs [data-zone-sport="run"]').click();
  await expect(page.locator('#zoneSportTabs [data-zone-sport="run"]')).toHaveAttribute("aria-pressed", "true");
  await expect(thresholds.locator('[data-threshold="lt2-main"]')).toHaveText("4:28 /km");
  await expect(thresholds.locator('[data-threshold="lt1-hr"]')).toHaveText("146 bpm");
  await expect(overview.locator('[data-zone-box="pace"]')).toContainText("Noch keine Werte –");
  expect((await new AxeBuilder({ page }).include("#zoneSettings").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("@responsive Analyse shows LT1 like the zones page", async ({ page }) => {
  await openProfile(page);
  await page.evaluate(async () => {
    await AppRouter.navigate("analysis/cycling", { historyMode: "replace" });
    renderCurrentPerformance(state.data.performance.metrics, state.data.performance.history);
  });
  const cycling = page.locator("#currentPerformance table[data-analysis-sport='ride']");
  await expect(cycling.locator('[data-metric="cycling_lt1_hr_bpm"] td')).toHaveText("142 bpm");
  await expect(cycling.locator('[data-metric="cycling_lt1_watts"]')).toHaveCount(0);
});
