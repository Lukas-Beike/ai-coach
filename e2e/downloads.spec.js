const { test, expect } = require("@playwright/test");

// The responses are mocked: this spec checks the file names the client chooses.
test.use({ serviceWorkers: "block" });

const DOWNLOADS = [
  { button: "Backup herunterladen", route: "**/api/privacy/backup", name: /^pacecraft-database-\d{4}-\d{2}-\d{2}\.backup$/ },
  { button: "Daten exportieren", route: "**/api/privacy/export", name: /^pacecraft-export-\d{4}-\d{2}-\d{2}\.zip$/ },
  { button: "Diagnose herunterladen", route: "**/api/diagnostics", name: /^pacecraft-diagnostics-\d{4}-\d{2}-\d{2}\.json$/ },
  { button: "Logs herunterladen", route: "**/api/logs/download", name: /^pacecraft-server-logs-\d{4}-\d{2}-\d{2}\.jsonl$/ },
];

test("settings and diagnostics downloads carry the Pacecraft name", async ({ page }) => {
  await page.goto("/#more/operations");
  await expect(page.locator("#loginDialog")).toBeHidden();
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(() => { for (const details of document.querySelectorAll("#settingsPanel details")) details.open = true; });
  for (const { button, route, name } of DOWNLOADS) {
    await page.route(route, (request) => request.fulfill({ status: 200, contentType: "application/octet-stream", body: "fixture" }));
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#settingsPanel").getByRole("button", { name: button, exact: true }).click(),
    ]);
    expect(download.suggestedFilename()).toMatch(name);
    await page.unroute(route);
  }
});

const DELETIONS = [
  { button: "Logs löschen", route: "**/api/logs/delete", done: "Server-Logs gelöscht" },
  { button: "Diagnose löschen", route: "**/api/diagnostics/delete", done: "Diagnose gelöscht" },
];

test("deleting logs or diagnostics asks first, gives focus back on cancel and sends one POST on confirm", async ({ page }) => {
  await page.goto("/#more/operations");
  await expect(page.locator("#loginDialog")).toBeHidden();
  await page.waitForFunction(() => state.initialStateLoaded);
  await page.evaluate(() => { for (const details of document.querySelectorAll("#settingsPanel details")) details.open = true; });
  const dialog = page.locator("#confirmationDialog");
  for (const { button, route, done } of DELETIONS) {
    const methods = [];
    await page.route(route, (request) => {
      methods.push(request.request().method());
      return request.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    });
    const trigger = page.locator("#settingsPanel").getByRole("button", { name: button, exact: true });
    await trigger.click();
    await expect(dialog).toBeVisible();
    await expect(page.locator("#confirmationDialogCancel")).toBeFocused();
    await page.locator("#confirmationDialogCancel").click();
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
    expect(methods).toEqual([]);
    await trigger.click();
    await page.locator("#confirmationDialogAccept").click();
    await expect(page.locator(".toast", { hasText: done })).toBeVisible();
    expect(methods).toEqual(["POST"]);
    await page.unroute(route);
  }
});
