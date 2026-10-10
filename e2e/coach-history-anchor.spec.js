const { test, expect } = require("@playwright/test");

function historyMessage(id, index, day) {
  return {
    id,
    role: index % 2 ? "assistant" : "user",
    content: `${index % 2 ? "Coach" : "Athlet"} Verlauf ${id}\n\n${"Ausführlicher Trainingskontext für die Scrollprüfung. ".repeat(12)}`,
    created_at: `${day}T10:${String(index).padStart(2, "0")}:00Z`,
  };
}

async function openHistoryFixture(page) {
  const generation = "e2e-history-anchor";
  const olderMessages = Array.from({ length: 30 }, (_, index) => historyMessage(60_000 + index, index, "2026-10-01"));
  const recentMessages = Array.from({ length: 40 }, (_, index) => historyMessage(61_000 + index, index, "2026-10-02"));
  const firstId = recentMessages[0].id;
  await page.route("**/api/chat/history?*", (route) => {
    const olderPage = new URL(route.request().url()).searchParams.has("cursor");
    route.fulfill({
      json: olderPage
        ? { messages: olderMessages, generation, next_cursor: null, proposed_actions: [] }
        : { messages: recentMessages, generation, next_cursor: "older-page", proposed_actions: [] },
    });
  });

  // The bootstrap also carries the shared fixture chat; replace it so only the mocked pages are rendered.
  await page.route("**/api/bootstrap*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (Array.isArray(body.messages)) Object.assign(body, { messages: recentMessages, messages_next_cursor: "older-page", messages_generation: generation });
    await route.fulfill({ response, json: body });
  });

  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator(`#messages [data-message-id="${firstId}"]`)).toBeAttached();
  await expect.poll(() => page.evaluate(() => state.initialStateLoaded)).toBe(true);
  await expect(page.locator('#messages [data-page-area="chat"]')).toBeAttached();
  return { firstId };
}

test("older chat history keeps the reading position without moving focus @responsive", async ({ page }) => {
  const { firstId } = await openHistoryFixture(page);

  // Scrolling the history button into view triggers the observer; the visible anchor is restored after the older page renders.
  const before = await page.evaluate((messageId) => {
    const root = document.querySelector("#messages");
    window.scrollTo({ top: window.scrollY + root.getBoundingClientRect().top, behavior: "auto" });
    return document.querySelector(`#messages [data-message-id="${messageId}"]`).getBoundingClientRect().top;
  }, firstId);

  await expect(page.locator("#messages [data-message-id]")).toHaveCount(70);
  await expect(page.locator("#chatOperationStatus")).toHaveText("30 ältere Nachrichten geladen");
  const after = await page.evaluate((messageId) => (
    document.querySelector(`#messages [data-message-id="${messageId}"]`).getBoundingClientRect().top
  ), firstId);
  expect(Math.abs(after - before)).toBeLessThanOrEqual(2);
  // Automatic loading must not move focus away from where the reader is.
  expect(await page.evaluate(() => document.activeElement?.matches("[data-message-id]"))).toBe(false);
});

test("automatic older chat loading keeps focus on the focused message action @responsive", async ({ page }) => {
  const { firstId } = await openHistoryFixture(page);

  // Focus a message action in the first loaded message before the scroll triggers the automatic load, as a keyboard user moving toward the start would.
  const focused = await page.evaluate((messageId) => {
    const action = document.querySelector(`#messages [data-message-id="${messageId}"] .message-action[aria-label="Nachricht kopieren"]`);
    action.focus({ preventScroll: true });
    const root = document.querySelector("#messages");
    window.scrollTo({ top: window.scrollY + root.getBoundingClientRect().top, behavior: "auto" });
    return document.activeElement === action;
  }, firstId);
  expect(focused).toBe(true);

  await expect(page.locator("#messages [data-message-id]")).toHaveCount(70);
  await expect(page.locator("#chatOperationStatus")).toHaveText("30 ältere Nachrichten geladen");
  expect(await page.evaluate(() => {
    const active = document.activeElement;
    return {
      tag: active?.tagName ?? null,
      label: active?.getAttribute("aria-label") ?? null,
      messageId: active?.closest("[data-message-id]")?.dataset.messageId ?? null,
    };
  })).toEqual({ tag: "BUTTON", label: "Nachricht kopieren", messageId: String(firstId) });
});
