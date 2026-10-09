const { test, expect } = require("@playwright/test");

const CHANGE_ID = "0f0e1d2c-3b4a-4958-8a7b-6c5d4e3f2a1b";
const CHANGE = {
  id: CHANGE_ID,
  entity_type: "workout_library",
  entity_id: "wl-fixture-1",
  action: "update",
  source: "local",
  created_at: "2026-10-08T09:30:00Z",
  before_hash: "before-hash",
  after_hash: "after-hash",
  diff: {
    fields: { name: { changed: true }, moving_time: { changed: true } },
    before_present: true,
    after_present: true,
  },
  remote_sync: "local_only",
};

function previewResponse() {
  return {
    status: "preview",
    change: CHANGE,
    undo_target_hash: "target-hash",
    proposed_action: {
      action_type: "undo_change",
      target_system: "local",
      object_ids: { change_id: CHANGE_ID },
      diff: CHANGE.diff,
      payload: { change_id: CHANGE_ID, expected_current_hash: "after-hash" },
    },
  };
}

async function openChangeHistory(page, { previewStatus = 200 } = {}) {
  const calls = { preview: 0, undo: 0, undoBodies: [] };
  await page.route((url) => url.pathname === "/api/change-history", (route) => route.fulfill({
    json: { changes: [CHANGE] },
  }));
  await page.route((url) => url.pathname === "/api/change-history/undo/preview", (route) => {
    calls.preview += 1;
    if (previewStatus !== 200) {
      return route.fulfill({ status: previewStatus, json: { error: "Vorschau nicht verfügbar." } });
    }
    return route.fulfill({ json: previewResponse() });
  });
  await page.route((url) => url.pathname === "/api/change-history/undo", (route) => {
    calls.undo += 1;
    calls.undoBodies.push(route.request().postDataJSON());
    return route.fulfill({
      json: { status: "undone", change_id: CHANGE_ID, entity_type: "workout_library", entity_id: "wl-fixture-1", remote_untouched: true },
    });
  });

  await page.goto("/#more/privacy");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !state.loadPromise)).toBe(true);
  await page.evaluate(() => { document.querySelector('details[data-more-segment-panel="privacy"]').open = true; });
  await page.locator("#changeHistoryRefreshButton").click();
  await expect(page.locator("#changeHistoryList")).toContainText("Workout-Bibliothek geändert");
  return calls;
}

test("undo loads the preview first and shows exactly one dialog @responsive", async ({ page }) => {
  const calls = await openChangeHistory(page);
  const row = page.locator("#changeHistoryList .change-history-item");
  await expect(row).toContainText("Workout-Bibliothek geändert");
  await expect(row).not.toContainText("moving_time");
  await expect(row).toContainText("Bewegungszeit");
  await expect(row).toContainText("Quelle: App");

  await row.getByRole("button", { name: "Änderung zurücknehmen" }).click();

  const dialog = page.locator("#confirmationDialog");
  await expect(dialog).toBeVisible();
  await expect(page.locator("dialog[open]")).toHaveCount(1);
  await expect(page.locator("#confirmationDialogMessage")).toContainText("Workout-Bibliothek, geändert am");
  await expect(page.locator("#confirmationDialogMessage")).toContainText("auf den Stand vor der Änderung zurückgesetzt: Name, Bewegungszeit");
  expect(calls.preview).toBe(1);
  expect(calls.undo).toBe(0);
});

test("cancelling the undo preview changes nothing @responsive", async ({ page }) => {
  const calls = await openChangeHistory(page);
  await page.locator("#changeHistoryList .change-history-item").getByRole("button", { name: "Änderung zurücknehmen" }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();

  await page.locator("#confirmationDialogCancel").click();

  await expect(page.locator("#confirmationDialog")).toBeHidden();
  expect(calls.preview).toBe(1);
  expect(calls.undo).toBe(0);
});

test("confirming the undo preview applies exactly that change @responsive", async ({ page }) => {
  const calls = await openChangeHistory(page);
  await page.locator("#changeHistoryList .change-history-item").getByRole("button", { name: "Änderung zurücknehmen" }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();

  await page.locator("#confirmationDialogAccept").click();

  await expect(page.locator("#confirmationDialog")).toBeHidden();
  await expect(page.locator("#toast")).toContainText("Lokale Änderung zurückgenommen");
  expect(calls.preview).toBe(1);
  expect(calls.undo).toBe(1);
  expect(calls.undoBodies[0]).toEqual({ change_id: CHANGE_ID, expected_current_hash: "after-hash" });
});

test("a failed undo preview shows an error and never opens the confirmation @responsive", async ({ page }) => {
  const calls = await openChangeHistory(page, { previewStatus: 409 });
  await page.locator("#changeHistoryList .change-history-item").getByRole("button", { name: "Änderung zurücknehmen" }).click();

  await expect(page.locator("#toast")).toContainText("Vorschau nicht verfügbar.");
  await expect(page.locator("#toast")).toContainText("Es wurde nichts zurückgenommen.");
  await expect(page.locator("#confirmationDialog")).toBeHidden();
  expect(calls.preview).toBe(1);
  expect(calls.undo).toBe(0);
});
