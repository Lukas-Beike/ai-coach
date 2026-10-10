const { test, expect } = require("@playwright/test");
const { isFullyAbove } = require("./helpers/ui");

const SLOW_STREAM_PROMPT = "E2E fixture: slow stream";

// Older long messages make the chat scrollable in every project, independent of what earlier specs stored.
const OLDER_MESSAGES = Array.from({ length: 12 }, (_, index) => ({
  id: 95_000 + index,
  role: index % 2 ? "assistant" : "user",
  content: `${index % 2 ? "Coach" : "Athlet"} Vorlauf ${index + 1}

${"Ausführlicher Trainingskontext für die Scrollprüfung. ".repeat(10)}`,
  created_at: `2000-01-01T10:${String(index).padStart(2, "0")}:00Z`,
}));

async function openCoach(page) {
  await page.route("**/api/bootstrap*", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (Array.isArray(body.messages)) body.messages = [...OLDER_MESSAGES, ...body.messages];
    await route.fulfill({ response, json: body });
  });
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await expect(page.locator("#messageInput")).toBeVisible();
}

async function sendSlowStream(page) {
  await page.locator("#messageInput").fill(SLOW_STREAM_PROMPT);
  await page.getByRole("button", { name: "Senden", exact: true }).click();
}

async function waitForStreamToFinish(page) {
  await expect.poll(() => page.evaluate(() => state.chatRequest)).toBe(null);
}

test("the own message, reply and working indicator stay above the composer while streaming @responsive", async ({ page }) => {
  await openCoach(page);
  await sendSlowStream(page);
  const streaming = page.locator(".message.assistant.streaming");
  // Wait for later deltas so the check covers a reply that grew after the initial scroll.
  await expect(streaming).toContainText("Dauerlauf");
  const geometry = await page.evaluate((prompt) => {
    const rect = (node) => node?.getBoundingClientRect() || null;
    const own = [...document.querySelectorAll("#messages .message.user")].filter((node) => node.textContent.includes(prompt)).at(-1);
    return {
      composerTop: rect(document.querySelector("#chatForm")).top,
      own: rect(own),
      stream: rect(document.querySelector("#messages .message.assistant.streaming")),
      working: rect(document.querySelector("#coachWorking")),
    };
  }, SLOW_STREAM_PROMPT);
  // The own message is checked by its bottom edge: once the reply starts it may scroll above the viewport top.
  expect(geometry.own.bottom).toBeLessThanOrEqual(geometry.composerTop + 0.5);
  for (const name of ["stream", "working"]) {
    expect(geometry[name], `${name} rendered`).not.toBeNull();
    expect(geometry[name].top, `${name} top`).toBeGreaterThanOrEqual(0);
    expect(geometry[name].bottom, `${name} above composer`).toBeLessThanOrEqual(geometry.composerTop + 0.5);
  }
  await waitForStreamToFinish(page);
});

test("scrolling away during a stream keeps the position and offers the new reply @responsive", async ({ page }) => {
  await openCoach(page);
  await sendSlowStream(page);
  await expect(page.locator(".message.assistant.streaming")).toBeVisible();
  await page.mouse.wheel(0, -2000);
  await expect.poll(() => page.evaluate(() => state.chatFollowLatest)).toBe(false);
  const scrollAfterWheel = await page.evaluate(() => window.scrollY);
  await waitForStreamToFinish(page);
  expect(Math.abs(await page.evaluate(() => window.scrollY) - scrollAfterWheel)).toBeLessThanOrEqual(2);
  const jump = page.locator("#chatJumpToComposer");
  await expect(jump).toBeVisible();
  await expect(jump.locator(".chat-jump-label")).toHaveText("Neue Antwort");
});

test("the jump button returns to the latest reply and moves focus only on desktop @responsive", async ({ page }, testInfo) => {
  const touchProject = testInfo.project.name.startsWith("mobile");
  await openCoach(page);
  await sendSlowStream(page);
  await expect(page.locator(".message.assistant.streaming")).toBeVisible();
  await page.mouse.wheel(0, -2000);
  const jump = page.locator("#chatJumpToComposer");
  await expect(jump).toBeVisible();
  await waitForStreamToFinish(page);
  await page.evaluate(() => document.activeElement?.blur());
  await jump.click();
  await expect(jump).toBeHidden();
  await expect(jump).toHaveAttribute("aria-label", "Zu den neuesten Nachrichten springen");
  expect(await isFullyAbove(page.locator(".message.assistant").last(), page.locator("#chatForm"))).toBe(true);
  if (touchProject) expect(await page.evaluate(() => document.activeElement?.id)).not.toBe("messageInput");
  else await expect(page.locator("#messageInput")).toBeFocused();
});
