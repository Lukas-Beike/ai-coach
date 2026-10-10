const { test, expect } = require("@playwright/test");

const CHANGE_ID = "0f0e1d2c-3b4a-4958-8a7b-6c5d4e3f2a1b";
const PROPOSAL_ID = "5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d";
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
    // Mirrors coach_action_view(): the private payload never reaches the browser.
    proposed_action: proposedAction("preview"),
  };
}

function proposedAction(status) {
  return {
    id: PROPOSAL_ID,
    action_type: "undo_change",
    target_system: "local",
    object_ids: { change_id: CHANGE_ID },
    diff: CHANGE.diff,
    payload_hash: "payload-hash",
    expires_at: 4102444800,
    status,
  };
}

async function openChangeHistory(page, { previewStatus = 200 } = {}) {
  const calls = { preview: 0, confirm: [], execute: [], cancel: [], directUndo: 0 };
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
    calls.directUndo += 1;
    return route.fulfill({ status: 400, json: { error: "Direktes Undo ist nicht vorgesehen." } });
  });
  await page.route((url) => url.pathname === "/api/coach/actions/confirm", (route) => {
    calls.confirm.push(route.request().postDataJSON());
    return route.fulfill({ json: { status: "ready", action_token: "action-token", proposed_action: proposedAction("ready") } });
  });
  await page.route((url) => url.pathname === "/api/coach/actions/execute", (route) => {
    calls.execute.push(route.request().postDataJSON());
    return route.fulfill({
      json: { status: "undone", change_id: CHANGE_ID, entity_type: "workout_library", entity_id: "wl-fixture-1", remote_untouched: true },
    });
  });
  await page.route((url) => url.pathname === "/api/coach/actions/cancel", (route) => {
    calls.cancel.push(route.request().postDataJSON());
    return route.fulfill({ json: { status: "cancelled", proposal_id: PROPOSAL_ID } });
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
  expect(calls.confirm).toHaveLength(0);
  expect(calls.execute).toHaveLength(0);
});

test("cancelling the undo preview changes nothing @responsive", async ({ page }) => {
  const calls = await openChangeHistory(page);
  await page.locator("#changeHistoryList .change-history-item").getByRole("button", { name: "Änderung zurücknehmen" }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();

  await page.locator("#confirmationDialogCancel").click();

  await expect(page.locator("#confirmationDialog")).toBeHidden();
  await expect.poll(() => calls.cancel).toEqual([{ proposal_id: PROPOSAL_ID }]);
  expect(calls.preview).toBe(1);
  expect(calls.confirm).toHaveLength(0);
  expect(calls.execute).toHaveLength(0);
});

test("confirming the undo preview applies exactly that change @responsive", async ({ page }) => {
  const calls = await openChangeHistory(page);
  await page.locator("#changeHistoryList .change-history-item").getByRole("button", { name: "Änderung zurücknehmen" }).click();
  await expect(page.locator("#confirmationDialog")).toBeVisible();

  await page.locator("#confirmationDialogAccept").click();

  await expect(page.locator("#confirmationDialog")).toBeHidden();
  await expect(page.locator("#toast")).toContainText("Lokale Änderung zurückgenommen");
  expect(calls.preview).toBe(1);
  expect(calls.confirm).toEqual([{ proposal_id: PROPOSAL_ID }]);
  expect(calls.execute).toEqual([{ action_token: "action-token", payload_hash: "payload-hash" }]);
  expect(calls.cancel).toHaveLength(0);
  expect(calls.directUndo).toBe(0);
});

test("a failed undo preview shows an error and never opens the confirmation @responsive", async ({ page }) => {
  const calls = await openChangeHistory(page, { previewStatus: 409 });
  await page.locator("#changeHistoryList .change-history-item").getByRole("button", { name: "Änderung zurücknehmen" }).click();

  await expect(page.locator("#toast")).toContainText("Vorschau nicht verfügbar.");
  await expect(page.locator("#toast")).toContainText("Es wurde nichts zurückgenommen.");
  await expect(page.locator("#confirmationDialog")).toBeHidden();
  expect(calls.preview).toBe(1);
  expect(calls.confirm).toHaveLength(0);
  expect(calls.execute).toHaveLength(0);
});
