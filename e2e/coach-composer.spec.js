const { test, expect } = require("@playwright/test");

async function openCoach(page) {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await expect(page.locator("#messageInput")).toBeVisible();
}

test("composer puts the textarea on a full-width row with controls below @responsive", async ({ page }) => {
  await openCoach(page);
  const form = await page.locator("#chatForm").boundingBox();
  const textarea = await page.locator("#messageInput").boundingBox();
  const attachment = await page.locator("#attachmentButton").boundingBox();
  const voice = await page.locator("#voiceButton").boundingBox();
  const send = await page.locator("#sendButton").boundingBox();
  expect(textarea.width).toBeGreaterThanOrEqual(form.width * 0.85);
  expect(attachment.y).toBeGreaterThanOrEqual(textarea.y + textarea.height - 1);
  expect(attachment.x + attachment.width).toBeLessThanOrEqual(send.x);
  expect(voice.x + voice.width).toBeLessThanOrEqual(send.x);
});

test("composer height does not change while busy @responsive", async ({ page }) => {
  await openCoach(page);
  const idleHeight = (await page.locator("#chatForm").boundingBox()).height;
  await page.evaluate(() => {
    document.querySelector("#chatForm").classList.add("is-busy");
    document.querySelector("#steerButton").hidden = false;
    document.querySelector("#cancelChatButton").hidden = false;
  });
  try {
    const busyHeight = (await page.locator("#chatForm").boundingBox()).height;
    expect(Math.abs(busyHeight - idleHeight)).toBeLessThanOrEqual(2);
  } finally {
    await page.evaluate(() => {
      document.querySelector("#chatForm").classList.remove("is-busy");
      document.querySelector("#steerButton").hidden = true;
      document.querySelector("#cancelChatButton").hidden = true;
    });
  }
});

test("Enter sends on desktop and inserts a line break on touch @responsive", async ({ page }, testInfo) => {
  await openCoach(page);
  const input = page.locator("#messageInput");
  const touchProject = testInfo.project.name.startsWith("mobile");
  await expect(input).toHaveAttribute("enterkeyhint", touchProject ? "enter" : "send");
  await page.evaluate(() => {
    window.__composerSubmits = 0;
    document.querySelector("#chatForm").addEventListener("submit", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      window.__composerSubmits += 1;
    }, { capture: true });
  });
  await input.fill("Erste Zeile");
  await input.press("Enter");
  if (touchProject) {
    await expect(input).toHaveValue("Erste Zeile\n");
    expect(await page.evaluate(() => window.__composerSubmits)).toBe(0);
  } else {
    await expect.poll(() => page.evaluate(() => window.__composerSubmits)).toBe(1);
    await input.press("Shift+Enter");
    await expect(input).toHaveValue("Erste Zeile\n");
  }
  await input.fill("");
});

test("single-line draft shows no textarea scrollbar @responsive", async ({ page }) => {
  await openCoach(page);
  const input = page.locator("#messageInput");
  await input.fill("Kurze Frage an den Coach");
  const metrics = await input.evaluate((element) => ({
    scrollHeight: element.scrollHeight,
    clientHeight: element.clientHeight,
  }));
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.clientHeight);
  await input.fill("");
});
