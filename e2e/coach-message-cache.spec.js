const { test, expect } = require("@playwright/test");

const GENERATION = "e2e-message-cache";
const CACHE_LIMIT = 20;
const FIRST_ID = 62_000;
const LAST_ID = FIRST_ID + 59;
const FIRST_PAGE_SIZE = 25;
const PAGE_SIZE = 30;
// The delayed answers are released by the test, so the cached start is observed before they arrive.
const RELEASE_TIMEOUT_MS = 30_000;

const conversation = Array.from({ length: LAST_ID - FIRST_ID + 1 }, (_, index) => ({
  id: FIRST_ID + index,
  role: index % 2 ? "assistant" : "user",
  content: `${index % 2 ? "Coach" : "Athlet"} Cache ${FIRST_ID + index}\n\n${"Ausführlicher Trainingskontext für die Scrollprüfung. ".repeat(12)}`,
  created_at: `2026-10-02T10:${String(index).padStart(2, "0")}:00Z`,
}));

// Same encoding as the server's history cursor: the oldest id of the page already delivered.
const cursorFor = (messageId) => Buffer.from(JSON.stringify(messageId)).toString("base64url");
const idFromCursor = (cursor) => Number(JSON.parse(Buffer.from(cursor, "base64url").toString()));

function historyPage(cursor, limit) {
  const end = cursor ? conversation.findIndex((message) => message.id === idFromCursor(cursor)) : conversation.length;
  const start = Math.max(0, end - (cursor ? Math.min(limit, PAGE_SIZE) : Math.min(limit, FIRST_PAGE_SIZE)));
  const messages = conversation.slice(start, end);
  return { messages, generation: GENERATION, next_cursor: start > 0 ? cursorFor(messages[0].id) : null, proposed_actions: [] };
}

test("cached latest messages show before the start answers and older ones page in @responsive", async ({ page }) => {
  const requestedCursors = [];
  let delayed = false;
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const waitForGate = () => Promise.race([gate, new Promise((resolve) => setTimeout(resolve, RELEASE_TIMEOUT_MS))]);

  await page.route("**/api/chat/history?*", async (route) => {
    const params = new URL(route.request().url()).searchParams;
    const cursor = params.get("cursor");
    if (cursor) requestedCursors.push(cursor);
    if (delayed && !cursor) await waitForGate();
    await route.fulfill({ json: historyPage(cursor, Number(params.get("limit") || FIRST_PAGE_SIZE)) });
  });
  await page.route("**/api/bootstrap*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (Array.isArray(body.messages)) {
      const first = historyPage(null, FIRST_PAGE_SIZE);
      Object.assign(body, { messages: first.messages, messages_next_cursor: first.next_cursor, messages_generation: GENERATION });
    }
    if (delayed) await waitForGate();
    await route.fulfill({ response, json: body });
  });

  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.initialStateLoaded)).toBe(true);
  await expect(page.locator(`#messages [data-message-id="${LAST_ID}"]`)).toBeAttached();

  // The cache keeps only the newest messages plus the cursor that continues behind them.
  const cacheStart = LAST_ID - CACHE_LIMIT + 1;
  await expect.poll(() => page.evaluate(() => {
    const cache = JSON.parse(localStorage.getItem("coach-chat-cache") || "null");
    return cache?.messages?.at(-1)?.id ?? null;
  })).toBe(LAST_ID);
  const cache = await page.evaluate(() => JSON.parse(localStorage.getItem("coach-chat-cache")));
  expect(cache.messages.map((message) => message.id)).toEqual(
    Array.from({ length: CACHE_LIMIT }, (_, index) => cacheStart + index),
  );
  expect(cache.generation).toBe(GENERATION);
  expect(cache.next_cursor).toBe(cursorFor(cacheStart));
  // The device snapshot is stored with a short delay; the reload below needs it.
  await expect.poll(() => page.evaluate(() => Boolean(localStorage.getItem("coach-state-snapshot")))).toBe(true);

  // Reload with the start answers held back: the cached messages must already be shown.
  delayed = true;
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  const cached = page.locator("#messages [data-message-id]");
  await expect(page.locator(`#messages [data-message-id="${LAST_ID}"]`)).toBeAttached({ timeout: 5_000 });
  await expect(cached).toHaveCount(CACHE_LIMIT);
  await expect(page.locator(`#messages [data-message-id="${cacheStart}"]`)).toBeAttached();
  await expect(page.locator(`#messages [data-message-id="${cacheStart - 1}"]`)).toHaveCount(0);
  // The answers are still pending, so the messages came from the device cache.
  expect(await page.evaluate(() => state.initialStateLoaded)).toBe(false);

  // Cached messages are not current: the chat sits at the newest one and a sync note replaces the jump button.
  const syncNote = page.locator("#chatSyncStatus");
  const newestInView = () => page.evaluate((messageId) => {
    const message = document.querySelector(`#messages [data-message-id="${messageId}"]`).getBoundingClientRect();
    const composerTop = document.querySelector("#chatForm").getBoundingClientRect().top;
    return message.bottom > 0 && message.bottom <= Math.min(composerTop, window.innerHeight) + 1;
  }, LAST_ID);
  await expect(syncNote).toBeVisible();
  await expect(syncNote).toHaveText("Nachrichten werden synchronisiert…");
  await expect(syncNote).toHaveAttribute("role", "status");
  await expect(page.locator("#chatJumpToComposer")).toBeHidden();
  await expect.poll(newestInView).toBe(true);
  // Leaving and returning to the Coach during the sync starts at the newest message again.
  await page.evaluate(() => { location.hash = "#plan"; });
  await expect(page.locator("#chatPanel")).not.toHaveClass(/active/);
  await expect(syncNote).toBeHidden();
  await page.evaluate(() => { window.scrollTo({ top: 0, behavior: "auto" }); location.hash = "#coach"; });
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await expect(syncNote).toBeVisible();
  await expect(page.locator("#chatJumpToComposer")).toBeHidden();
  await expect.poll(newestInView).toBe(true);

  release();
  await expect.poll(() => page.evaluate(() => state.initialStateLoaded)).toBe(true);
  await expect(syncNote).toBeHidden();
  expect(await page.evaluate(() => state.chatCacheSyncing)).toBe(false);
  await expect(cached).toHaveCount(FIRST_PAGE_SIZE);
  await expect(page.locator('#messages [data-page-area="chat"]')).toBeAttached();

  // Scrolling to the oldest shown message pages in the older history and keeps the reading position.
  const firstShownId = LAST_ID - FIRST_PAGE_SIZE + 1;
  const before = await page.evaluate((messageId) => {
    const root = document.querySelector("#messages");
    window.scrollTo({ top: window.scrollY + root.getBoundingClientRect().top, behavior: "auto" });
    return document.querySelector(`#messages [data-message-id="${messageId}"]`).getBoundingClientRect().top;
  }, firstShownId);

  await expect(cached).toHaveCount(FIRST_PAGE_SIZE + PAGE_SIZE);
  await expect(page.locator(`#messages [data-message-id="${firstShownId - PAGE_SIZE}"]`)).toBeAttached();
  await expect(page.locator("#chatOperationStatus")).toHaveText("30 ältere Nachrichten geladen");
  expect(requestedCursors[0]).toBe(cursorFor(firstShownId));
  const after = await page.evaluate((messageId) => (
    document.querySelector(`#messages [data-message-id="${messageId}"]`).getBoundingClientRect().top
  ), firstShownId);
  expect(Math.abs(after - before)).toBeLessThanOrEqual(2);
});

test("a failed fresh chat load ends the sync note and keeps the cached messages @responsive", async ({ page }) => {
  let failing = false;
  await page.route("**/api/chat/history?*", async (route) => {
    if (failing) return route.fulfill({ status: 500, json: { error: "Chat nicht verfügbar" } });
    const params = new URL(route.request().url()).searchParams;
    return route.fulfill({ json: historyPage(params.get("cursor"), Number(params.get("limit") || FIRST_PAGE_SIZE)) });
  });
  await page.route("**/api/bootstrap*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (Array.isArray(body.messages)) {
      const first = historyPage(null, FIRST_PAGE_SIZE);
      Object.assign(body, { messages: first.messages, messages_next_cursor: first.next_cursor, messages_generation: GENERATION });
    }
    await route.fulfill({ response, json: body });
  });

  await page.goto("/#coach");
  await expect.poll(() => page.evaluate(() => state.initialStateLoaded)).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(localStorage.getItem("coach-state-snapshot")))).toBe(true);

  failing = true;
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.chatCacheSyncing)).toBe(false);
  await expect(page.locator("#chatSyncStatus")).toBeHidden();
  await expect(page.locator(`#messages [data-message-id="${LAST_ID}"]`)).toBeAttached();
});
