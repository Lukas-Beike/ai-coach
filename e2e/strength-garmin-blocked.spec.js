const { test, expect } = require("@playwright/test");

async function openEntry(page, name) {
  const entry = page.locator(".planned-entry").filter({ hasText: name }).first();
  await expect(entry).toHaveCount(1);
  await entry.evaluate((element) => {
    for (let node = element; node; node = node.parentElement) if (node.tagName === "DETAILS") node.open = true;
  });
  return entry;
}

test("@responsive a derived focus is offered as a one-tap suggestion", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  const name = "Tempolauf nach Distanz";
  let entry = await openEntry(page, name);
  const select = entry.locator("select[name='session_focus']");
  await expect(select).toHaveValue("");
  const chip = entry.locator(".planned-focus-form .planned-suggestion-chip").first();
  await chip.scrollIntoViewIfNeeded();
  await expect(chip).toHaveText(/^≈ .+ übernehmen$/);
  expect((await chip.boundingBox()).height).toBeGreaterThanOrEqual(32);
  const saved = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await chip.click();
  expect((await saved).ok()).toBeTruthy();
  await expect(entry.locator(".planned-focus-form .planned-suggestion-chip")).toHaveCount(0);
  await expect(select).not.toHaveValue("");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  // Restore the fixture unit.
  await page.reload();
  await page.waitForFunction(() => state.initialStateLoaded);
  entry = await openEntry(page, name);
  const cleared = page.waitForResponse((response) => response.url().includes("/focus") && response.request().method() === "POST");
  await entry.locator("select[name='session_focus']").selectOption("");
  expect((await cleared).ok()).toBeTruthy();
});

test("@responsive a strength unit says why it does not reach Garmin and offers the fix", async ({ page, request }) => {
  test.setTimeout(180_000);
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  // The demo has no future strength unit; mark the first future one as a
  // free-text and the second as an unmatched strength unit in the response.
  let marked = [];
  const changes = [
    { sport: "strength", push_blocked: { garmin: "no_structure" }, push_unmapped: [] },
    { sport: "strength", push_blocked: { garmin: "unmapped" }, push_unmapped: [{ index: 0, name: "Kabelrudern eng", suggestions: ["V-grip Cable Row", "Seated Cable Row"] }] },
  ];
  const mark = (node, ids) => {
    if (Array.isArray(node)) node.forEach((item) => mark(item, ids));
    else if (node && typeof node === "object") {
      const index = ids.indexOf(node.local_id);
      if (index >= 0 && "push_pending" in node) Object.assign(node, changes[index]);
      Object.values(node).forEach((value) => mark(value, ids));
    }
  };
  // Bootstrap and the calendar reload both carry the planned units.
  await page.route(/\/api\/(bootstrap|plan)(\?|$)/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (!marked.length) {
      const today = new Date().toISOString().slice(0, 10);
      marked = (body.planned || []).filter((unit) => unit.local_id && unit.push_pending && String(unit.date || "") > today).slice(0, 2).map((unit) => unit.local_id);
    }
    mark(body, marked);
    await route.fulfill({ status: response.status(), contentType: "application/json", body: JSON.stringify(body) });
  });
  const posted = [];
  await page.route("**/api/planned-units/*/garmin-exercise", async (route) => {
    posted.push(JSON.parse(route.request().postData() || "{}"));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ status: "local" }) });
  });
  await page.goto("/#plan/overview");
  await page.waitForFunction(() => state.initialStateLoaded);
  expect(marked).toHaveLength(2);
  const blocked = page.locator(".planned-garmin-blocked").filter({ hasText: "Keine Kraftstruktur – nicht an Garmin gesendet" }).first();
  await blocked.evaluate((element) => {
    for (let node = element.parentElement; node; node = node.parentElement) if (node.tagName === "DETAILS" && !node.classList.contains("planned-entry")) node.open = true;
  });
  await blocked.scrollIntoViewIfNeeded();
  await expect(blocked).toBeVisible();
  const coach = blocked.getByRole("button", { name: "Mit Coach strukturieren" });
  await expect(coach).toBeVisible();
  expect((await coach.boundingBox()).height).toBeGreaterThanOrEqual(32);
  const unmapped = page.locator(".planned-garmin-blocked").filter({ hasText: "Keine Garmin-Übung: Kabelrudern eng" }).first();
  await unmapped.scrollIntoViewIfNeeded();
  await expect(unmapped.getByRole("button", { name: "Andere…" })).toBeVisible();
  const card = unmapped.locator("xpath=ancestor::details[contains(@class,'planned-entry')]");
  await unmapped.getByRole("button", { name: "V-grip Cable Row" }).click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toMatchObject({ exercise_index: 0, garmin_exercise: "V-grip Cable Row" });
  expect(posted[0].expected_payload_hash).toBeTruthy();
  // A chip in the card summary must not toggle the card.
  expect(await card.evaluate((element) => element.open)).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
