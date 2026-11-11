const { test, expect } = require("@playwright/test");

test("synchronization progress stays outside chat receipts", async ({ page }) => {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !state.loadPromise)).toBe(true);
  await page.evaluate(() => addStructuredCoachReceipts({ command_receipts: [
    { tool: "start_intervals_plan_sync", resolved: true, result: { ok: false, error: "Synthetic invalid ID" } },
    { tool: "start_intervals_plan_sync", result: { ok: true, status: "queued", sync_job_id: "synthetic-job" } },
    { tool: "get_sync_job", result: { ok: true, job: { id: "synthetic-job", status: "running" } } },
  ] }));
  // J-203: the toast is the receipt; synchronization progress shows none and no hidden region exists.
  await expect(page.locator("#coachReceipts")).toHaveCount(0);
  const receipts = page.locator("#toast");
  await expect(receipts).not.toHaveClass(/show/);
  await page.evaluate(() => addStructuredCoachReceipts({ command_receipts: [
    { tool: "get_sync_job", result: { ok: true, job: { id: "synthetic-job", status: "completed" } } },
  ] }));
  await expect(receipts).not.toHaveClass(/show/);
  await expect(receipts).not.toContainText("Synchronisierung abgeschlossen");
});

test("profile writes have a useful receipt and unresolved errors stay visible safely", async ({ page }) => {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !state.loadPromise)).toBe(true);
  await page.evaluate(() => addStructuredCoachReceipts({ command_receipts: [
    { tool: "apply_training_patch", result: { ok: true, status: "applied" } },
    { tool: "update_profile", result: { ok: true, stored_locally: true } },
    { tool: "save_checkin", resolved: false, result: { ok: false, error: "<img src=x onerror=alert(1)>" } },
  ] }));
  // An unresolved failure leads the toast as an alert, as inert text.
  const receipts = page.locator("#toast");
  await expect(receipts).toHaveAttribute("role", "alert");
  await expect(receipts).toContainText("Coach-Aktion fehlgeschlagen: <img src=x onerror=alert(1)>");
  await expect(receipts.locator("img")).toHaveCount(0);
  await page.evaluate(() => addStructuredCoachReceipts({ command_receipts: [
    { tool: "apply_training_patch", result: { ok: true, status: "applied" } },
    { tool: "update_profile", result: { ok: true, stored_locally: true } },
  ] }));
  await expect(receipts).toHaveAttribute("role", "status");
  await expect(receipts).toContainText("Geplante Einheiten angepasst · Profil aktualisiert");
});
