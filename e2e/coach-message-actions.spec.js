const { test, expect } = require("@playwright/test");
const { captureReadFixture, installReadFixture } = require("./read-fixture");

let fixture;
test.beforeAll(async ({ request }) => { fixture = await captureReadFixture(request); });
test.beforeEach(async ({ page }) => { await installReadFixture(page, fixture); });

async function openCoach(page) {
  // Abort the SSE transport so the fixture server is not held open by the stream.
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  await page.evaluate(() => {
    if (state.stateEventSource) {
      state.stateEventSource.onmessage = null;
      state.stateEventSource.onerror = null;
      state.stateEventSource.close();
      state.stateEventSource = null;
    }
    clearTimeout(state.chatStatusTimer);
  });
  await page.evaluate(async () => {
    await state.chatStatusPollInFlight?.catch(() => {});
    await state.loadPromise?.catch(() => {});
    state.pendingLoads.clear();
  });
}

// Realistic coach replies are several paragraphs long; short bubbles would make
// the row-height ratio meaningless.
const coachParagraph = "Plane die Einheit locker im Grundlagenbereich, achte auf eine saubere Technik und beende sie mit ein paar Minuten Auslauf, damit die Belastung gut verdaut wird.";
const seededMessages = [
  { id: 9301, role: "user", content: "Wie sieht meine Woche aus?", attachment_names: "[]" },
  { id: 9302, role: "assistant", content: Array.from({ length: 7 }, (_, index) => `Absatz ${index + 1}: ${coachParagraph}`).join("\n\n") },
  { id: 9303, role: "user", content: "Und wie steht es mit der Erholung?", attachment_names: "[]" },
  { id: 9304, role: "assistant", content: Array.from({ length: 7 }, (_, index) => `Absatz ${index + 1}: ${coachParagraph}`).join("\n\n") },
  { id: 9305, role: "assistant", content: Array.from({ length: 7 }, (_, index) => `Absatz ${index + 1}: ${coachParagraph}`).join("\n\n") },
  { id: 9306, role: "assistant", content: Array.from({ length: 7 }, (_, index) => `Absatz ${index + 1}: ${coachParagraph}`).join("\n\n") },
];

test("chat message actions keep 44px hit areas, accessible names and a compact row @responsive", async ({ page }) => {
  await openCoach(page);
  await page.evaluate((messages) => {
    state.data.messages = messages;
    renderMessages(messages, true);
  }, seededMessages);

  const lastAssistantAction = page.locator("#messages .message.assistant").last().locator(".message-action");
  await expect(lastAssistantAction).toHaveCount(1);
  await expect(lastAssistantAction).toHaveAccessibleName("Nachricht kopieren");

  const actions = page.locator("#messages .message-action");
  const actionCount = await actions.count();
  expect(actionCount, "copy and edit actions for all seeded messages").toBeGreaterThanOrEqual(seededMessages.length);
  for (let index = 0; index < actionCount; index += 1) {
    const action = actions.nth(index);
    await action.scrollIntoViewIfNeeded();
    const box = await action.boundingBox();
    expect(box, `action ${index} has a layout box`).not.toBeNull();
    expect(box.width, `action ${index} hit area width`).toBeGreaterThanOrEqual(44);
    expect(box.height, `action ${index} hit area height`).toBeGreaterThanOrEqual(44);
    await expect(action).toHaveAccessibleName(/\S/);
  }

  const ratio = await page.evaluate(() => {
    const root = document.querySelector("#messages");
    const rowHeight = [...root.querySelectorAll(".message-actions")]
      .reduce((sum, row) => sum + row.getBoundingClientRect().height, 0);
    return rowHeight / root.scrollHeight;
  });
  expect(ratio, "action rows as share of #messages scroll height").toBeLessThan(0.15);
});
