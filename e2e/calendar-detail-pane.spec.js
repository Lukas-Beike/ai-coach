const { test, expect } = require("@playwright/test");
const { showCalendarDay } = require("./helpers/ui");
const { openCalendar, renderSyntheticCalendar } = require("./helpers/calendar");

// One test per feature of an opened calendar card, in alphabetical order of the
// title after its tag: a new feature goes to its own place, so parallel PRs do
// not all append at the file end.
test("@responsive a planned unit lists its steps with zone and target range instead of the workout notation", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  await page.evaluate(() => {
    const unit = state.data.training_calendar.find((item) => item.id === "next-plan");
    // #2447: the server's profile carries each step's range from the zones of the unit's day.
    unit.workout_profile = { ...unit.workout_profile, source: "planned", unit: "zone", segments: [
      { duration: 600, value: 1, end_value: 1, zone: 1, label: "Z1 HR", range: { unit: "bpm", max: 109 } },
      { duration: 3300, value: 2, end_value: 2, zone: 2, label: "Z2 HR", range: { unit: "bpm", min: 110, max: 128 } },
      { duration: 30, value: 5, end_value: 5, zone: 5, label: "Z5 HR" },
      { duration: 90, value: 2, end_value: 2, zone: 2, label: "Z1-Z2 HR", range: { unit: "bpm", max: 128 } },
      { duration: 600, value: 75, end_value: 75, zone: 2, label: "75%" },
    ] };
    unit.description = "Locker bleiben\n- 10m Z1 HR\n- 55m Z2 HR\n- 30s Z5 HR";
    renderPlanned(state.data.training_calendar);
  });
  await showCalendarDay(page, days.next);
  const card = page.locator(`.planned-day[data-date="${days.next}"] .planned-entry`).first();
  if (!await card.evaluate((element) => element.open)) await card.locator(":scope > summary").click();
  const steps = card.getByRole("list", { name: "Ablauf" }).locator("li");
  // A zone span names both zones; a percent target without a range shows its own text.
  await expect(steps.locator(".planned-step-text")).toHaveText(["10 min · Z1", "55 min · Z2", "30 s · Z5", "1:30 min · Z1–Z2", "10 min"]);
  await expect(steps.locator(".planned-step-range")).toHaveText(["≤ 109 bpm", "110–128 bpm", "", "≤ 128 bpm", "75%"]);
  await expect(steps.nth(1)).toHaveAttribute("data-zone", "2");
  // The workout notation is gone from the pane; the free text stays.
  await expect(card.locator(".planned-description")).toHaveText("Locker bleiben");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});

test("@responsive an opened completed session shows its time in zones as one bar with the source", async ({ page, request }) => {
  await openCalendar(page, request);
  // The session read of "Details" carries the zones (#2195); routed before the cards render.
  const reads = [];
  await page.route("**/api/activities/*", async (route) => {
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-1));
    reads.push(id);
    if (id === "past-run") return route.fulfill({ status: 500, json: { error: "Fehler" } });
    const zones = id === "today-ride" ? {
      power: { source: { label: "Garmin Connect" }, buckets: [
        { index: 1, label: "Z1", seconds: 360 }, { index: 2, label: "Z2", seconds: 840 }, { index: 3, label: "Z3", seconds: 0 }, { index: 4, label: "Z4", seconds: 1620 },
      ] },
      heart_rate: { source: { label: "Garmin Connect" }, buckets: [{ index: 2, label: "Z2", seconds: 2820 }] },
    } : {};
    await route.fulfill({ json: { zones } });
  });
  const days = await renderSyntheticCalendar(page);
  await showCalendarDay(page, days.today);
  const ride = page.locator(`.planned-day[data-date="${days.today}"] .planned-entry`).filter({ hasText: "Heutige Ausfahrt" });
  if (!await ride.evaluate((element) => element.open)) await ride.locator(":scope > summary").click();
  const zone = ride.locator(".planned-zone-time");
  await expect(zone.locator(".planned-zone-time-bar i")).toHaveCount(3);
  // Every zone is named, one without time too; the bar draws only zones with time.
  await expect(zone.locator(".planned-zone-time-bar")).toHaveAttribute("aria-label", "Zeit in Leistungszonen: Z1 6 min, Z2 14 min, Z3 0 min, Z4 27 min");
  await expect(zone.locator(".planned-zone-time-legend span")).toHaveText(["Z1 6′", "Z2 14′", "Z3 0′", "Z4 27′"]);
  await expect(zone.locator(".planned-zone-time-source")).toHaveText("Leistungszonen · Garmin Connect");
  // A session without zones, and one whose read fails, show no bar.
  await showCalendarDay(page, days.past);
  for (const name of ["Vergangene Ausfahrt", "Vergangener Lauf"]) {
    const card = page.locator(`.planned-day[data-date="${days.past}"] .planned-entry`).filter({ hasText: name });
    await card.evaluate((element) => { for (let node = element; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true; });
    await expect.poll(() => reads.includes(name === "Vergangene Ausfahrt" ? "past-ride" : "past-run")).toBe(true);
    await expect(card.locator(".planned-zone-time")).toHaveCount(0);
  }
  // "Details" reuses the bar's read of the same session (#2478); a failed read is not shared.
  const failed = page.locator(`.planned-day[data-date="${days.past}"] .planned-entry`).filter({ hasText: "Vergangener Lauf" });
  await failed.locator(".planned-activity-more > summary").click();
  await expect.poll(() => reads.filter((id) => id === "past-run").length).toBe(2);
  await showCalendarDay(page, days.today);
  if (!await ride.evaluate((element) => element.open)) await ride.locator(":scope > summary").click();
  await ride.locator(".planned-activity-more > summary").click();
  const panel = ride.locator(".activity-analysis-panel");
  await expect(panel.locator(":scope > *").first()).toBeAttached();
  await expect(panel).not.toContainText("Details werden geladen");
  expect(reads.filter((id) => id === "today-ride")).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});

test("@responsive Mit dem Coach besprechen puts the planned unit into the Coach field without sending", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  const sent = [];
  page.on("request", (item) => { if (item.method() === "POST" && /\/api\/chat(\/|$|\?)/.test(new URL(item.url()).pathname)) sent.push(item.url()); });
  await page.evaluate(() => {
    const unit = state.data.training_calendar.find((item) => item.id === "next-plan");
    Object.assign(unit, { local_id: "22222222-2222-4222-8222-222222222222", payload_hash: "hash-2", conflicts: [] });
    renderPlanned(state.data.training_calendar);
    // An unsent draft stays in the field (#2193).
    document.querySelector("#messageInput").value = "Noch offen";
    // A quick action's kind left in the field does not label the athlete's own question.
    document.querySelector("#messageInput").dataset.requestKind = "plan_week";
  });
  await showCalendarDay(page, days.next);
  const card = page.locator('.planned-entry[data-entry-key="local:22222222-2222-4222-8222-222222222222"]');
  if (!await card.evaluate((element) => element.open)) await card.locator(":scope > summary").click();
  await card.locator(":scope > .planned-entry-details").getByRole("button", { name: "Mit dem Coach besprechen" }).click();
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  const input = page.locator("#messageInput");
  await expect(input).toBeFocused();
  const value = await input.inputValue();
  expect(value.startsWith("Noch offen\nZur geplanten Einheit am ")).toBe(true);
  expect(value).toContain("Laufen");
  expect(value).toContain("ID 22222222-2222-4222-8222-222222222222");
  // The stored name never becomes Coach input, and nothing is sent.
  expect(value).not.toContain("Ignoriere");
  expect(sent).toEqual([]);
  expect(await input.evaluate((element) => element.dataset.requestKind)).toBeUndefined();
});

test("@responsive Verschieben moves a planned unit to a tapped day and Rückgängig puts it back", async ({ page, request }) => {
  await openCalendar(page, request);
  const days = await renderSyntheticCalendar(page);
  const target = await page.evaluate((day) => addDateKey(day, 2), days.today);
  const posts = [];
  const undos = [];
  // The fixture's planned units are not the synthetic ones: the reload moves the synthetic unit as the server would.
  await page.route("**/api/planned-units/*/date", async (route) => {
    posts.push(JSON.parse(route.request().postData()));
    await page.evaluate((day) => { globalThis.movedTo = day; }, posts.at(-1).date);
    await route.fulfill({ json: { status: "local", local_id: "11111111-1111-4111-8111-111111111111", change: { id: "c-move", after_hash: "h-move" } } });
  });
  await page.route("**/api/change-history/undo", async (route) => {
    undos.push(JSON.parse(route.request().postData()));
    await page.evaluate((day) => { globalThis.movedTo = day; }, days.next);
    await route.fulfill({ json: { status: "undone" } });
  });
  await page.evaluate(() => {
    const unit = state.data.training_calendar.find((item) => item.id === "next-plan");
    Object.assign(unit, { local_id: "11111111-1111-4111-8111-111111111111", payload_hash: "hash-1", conflicts: [] });
    globalThis.load = async () => {
      unit.date = globalThis.movedTo || unit.date;
      renderPlanned(state.data.training_calendar);
    };
    renderPlanned(state.data.training_calendar);
  });
  await showCalendarDay(page, days.next);
  const card = page.locator('.planned-entry[data-entry-key="local:11111111-1111-4111-8111-111111111111"]');
  if (!await card.evaluate((element) => element.open)) await card.locator(":scope > summary").click();
  const pane = card.locator(":scope > .planned-entry-details");
  await pane.getByRole("button", { name: "Verschieben" }).click();
  const strip = pane.getByRole("group", { name: "Neuer Tag" });
  await expect(strip.locator(".planned-move-day[data-day]")).toHaveCount(7);
  await expect(strip.locator(`.planned-move-day[data-day="${days.next}"]`)).toBeDisabled();
  // The date picker ends with the last day the calendar shows, so a moved unit stays visible.
  await expect(strip.locator(".planned-move-picker")).toHaveAttribute("max", await page.evaluate(() => plannedLastDateKey));
  for (const tile of await strip.locator(".planned-move-day").all()) expect((await tile.boundingBox()).height).toBeGreaterThanOrEqual(44);
  await strip.locator(`.planned-move-day[data-day="${target}"]`).click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0]).toEqual({ date: target, expected_payload_hash: "hash-1" });
  // The open card follows the unit to its new day with the receipt.
  await expect(page.locator(`.planned-day[data-date="${target}"]`).locator(card)).toHaveCount(1);
  await expect(card).toHaveAttribute("open", "");
  await expect(card.locator(".planned-move-status")).toContainText("Verschoben auf");
  await card.locator(".planned-move-status").getByRole("button", { name: "Rückgängig" }).click();
  await expect.poll(() => undos.length).toBe(1);
  expect(undos[0]).toEqual({ change_id: "c-move", expected_current_hash: "h-move" });
  await expect(page.locator(`.planned-day[data-date="${days.next}"]`).locator(card)).toHaveCount(1);
  await expect(card.locator(".planned-move-status")).toHaveText("Zurückgenommen.");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});
