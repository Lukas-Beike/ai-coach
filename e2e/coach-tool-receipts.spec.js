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
  const receipts = page.locator("#coachReceipts");
  await expect(receipts.locator(".action-receipt")).toHaveCount(0);
  await expect(receipts).not.toContainText("Synthetic invalid ID");
  await expect(receipts).not.toContainText("Erledigt");
  await expect(receipts.locator(".status-chip")).toHaveCount(0);
  await page.evaluate(() => addStructuredCoachReceipts({ command_receipts: [
    { tool: "get_sync_job", result: { ok: true, job: { id: "synthetic-job", status: "completed" } } },
  ] }));
  await expect(receipts.locator(".action-receipt")).toHaveCount(0);
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
  const receipts = page.locator("#coachReceipts");
  await expect(receipts).toContainText("Profil aktualisiert");
  await expect(receipts).toContainText("Geplante Einheiten angepasst");
  await expect(receipts).toContainText("Coach-Aktion fehlgeschlagen");
  await expect(receipts.locator("img")).toHaveCount(0);
  await expect(receipts.locator(".is-error .status-chip")).toHaveText("Fehler");
});
