const { test, expect } = require("@playwright/test");

test("@responsive nutrition diary presents Garmin energy expenditure and unavailable states", async ({ page }) => {
  let responseMode = "measured";
  let holdResponse = false;
  let releaseResponse;
  const requestedDates = [];
  const requestedDateQueries = [];
  await page.route("**/api/nutrition/day**", async (route) => {
    const dateQuery = new URL(route.request().url()).searchParams.get("date");
    requestedDateQueries.push(dateQuery);
    const requestedDate = dateQuery || "2026-10-06";
    requestedDates.push(requestedDate);
    const mode = responseMode;
    if (mode === "error") return route.abort();
    if (holdResponse) await new Promise((resolve) => { releaseResponse = resolve; });
    const energyExpenditure = mode === "measured"
      ? {
        status: "measured",
        total_kcal: 2100,
        active_kcal: 600,
        resting_kcal: 1500,
        projected_total_kcal: 2350,
        projection_resting_kcal: 1750,
        projection_reference_date: "2026-10-05",
        source: "Garmin Connect",
        measured_date: requestedDate,
        date: requestedDate,
        freshness: "current",
        provisional: true,
        fetched_at: "2026-10-06T09:00:00Z",
        synced_at: "2026-10-06T09:15:00Z",
      }
      : {
        status: "unavailable",
        total_kcal: null,
        active_kcal: null,
        resting_kcal: null,
        measured_date: null,
        freshness: "unknown",
        provisional: false,
      };
    return route.fulfill({ json: {
      date: requestedDate,
      entry_count: 0,
      entries: [],
      total_kcal: null,
      total_carbs_g: null,
      total_protein_g: null,
      total_fat_g: null,
      energy_expenditure: energyExpenditure,
    } });
  });

  await page.goto("/#nutrition/diary");
  const expenditure = page.locator("#nutritionExpenditure");
  await expect.poll(() => requestedDates.length).toBeGreaterThan(0);
  expect(requestedDates[0]).toBe("2026-10-06");
  expect(requestedDateQueries[0]).toBeNull();
  await expect(page.locator("#nutritionDate")).toHaveValue("2026-10-06");
  await expect(expenditure).toContainText("Garmin Connect");
  await expect(expenditure).toContainText("Aktuell");
  await expect(expenditure).toContainText("Vorläufig");
  await expect(expenditure).toContainText("06.10.2026");
  await expect(expenditure).toContainText("2.100 kcal");
  await expect(expenditure).toContainText("Abgerufen: 06.10.2026");
  await expect(expenditure).toContainText("Garmin-Sync: 06.10.2026");
  const totals = expenditure.locator("#nutritionExpenditureTotals");
  await expect(totals).toContainText("Tagesverbrauch (vorläufig)");
  await expect(totals).toContainText("Aktivkalorien");
  await expect(totals).toContainText("Grundumsatz (vorläufig)");
  await expect(totals).toContainText("600 kcal");
  await expect(totals).toContainText("1.500 kcal");
  await expect(totals).toContainText("Prognose Tagesverbrauch (abgeleitet)");
  await expect(totals).toContainText("2.350 kcal");
  await expect(expenditure.locator("#nutritionExpenditureDate")).toContainText("Prognose: Grundumsatz vom 05.10.2026 (1.750 kcal) + bisherige Aktivkalorien (600 kcal), eigene Schätzung");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);

  responseMode = "unavailable";
  holdResponse = true;
  await page.evaluate(() => {
    const input = document.querySelector("#nutritionDate");
    input.value = "2026-10-05";
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await expect(expenditure.locator("#nutritionExpenditureTotals")).not.toContainText("2.100 kcal");
  await expect(page.locator("#nutritionExpenditureStatus")).toContainText("wird geladen");
  await expect(page.locator("#nutritionExpenditureDate")).toBeEmpty();
  await expect.poll(() => requestedDateQueries.at(-1)).toBe("2026-10-05");
  await expect.poll(() => requestedDates.at(-1)).toBe("2026-10-05");
  await expect.poll(() => Boolean(releaseResponse)).toBe(true);
  holdResponse = false;
  releaseResponse();
  await expect(expenditure).toContainText("keine Garmin-Verbrauchsdaten");
  await expect(expenditure).toContainText("Status: nicht verfügbar");
  await expect(expenditure).toContainText("05.10.2026");
  await expect(expenditure).toContainText("Nicht verfügbar");

  responseMode = "error";
  await page.evaluate(() => loadNutrition());
  // A failed refresh keeps the stored day on this device and says so.
  await expect(page.locator("#nutritionExpenditureStatus")).toContainText("Gespeicherter Stand. Tagesverbrauch konnte nicht aktualisiert werden");
  await expect(expenditure).toContainText("05.10.2026");
  await page.evaluate(() => { localStorage.removeItem("coach-view-cache"); return loadNutrition(); });
  await expect(page.locator("#nutritionExpenditureStatus")).toContainText("Tagesverbrauch konnte nicht geladen werden");
  await expect(expenditure.locator("#nutritionExpenditureTotals")).not.toContainText("2.100 kcal");
  await expect(page.locator("#nutritionExpenditureDate")).toBeEmpty();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
