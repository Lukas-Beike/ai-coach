const { test, expect } = require("@playwright/test");

async function openCoach(page) {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await expect(page.locator("#messageInput")).toBeVisible();
}

test("composer puts the textarea on a full-width row with controls below, or on one row on a low screen @responsive", async ({ page }) => {
  await openCoach(page);
  const form = await page.locator("#chatForm").boundingBox();
  const textarea = await page.locator("#messageInput").boundingBox();
  const attachment = await page.locator("#attachmentButton").boundingBox();
  const voice = await page.locator("#voiceButton").boundingBox();
  const send = await page.locator("#sendButton").boundingBox();
  if (page.viewportSize().height < 500) {
    // Phone landscape: input and controls share one row (#1784).
    expect(attachment.x).toBeGreaterThanOrEqual(textarea.x + textarea.width - 1);
    expect(attachment.y).toBeLessThan(textarea.y + textarea.height);
  } else {
    expect(textarea.width).toBeGreaterThanOrEqual(form.width * 0.85);
    expect(attachment.y).toBeGreaterThanOrEqual(textarea.y + textarea.height - 1);
  }
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

test("analysis and plan menu sends the chosen period with its request kind @responsive", async ({ page }) => {
  await openCoach(page);
  await page.evaluate(() => {
    state.quickTemplatesVisible = true;
    renderQuickMessageTemplates();
    window.__quickSubmit = null;
    document.querySelector("#chatForm").addEventListener("submit", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const input = document.querySelector("#messageInput");
      window.__quickSubmit = { kind: input.dataset.requestKind, message: input.value };
    }, { capture: true });
  });
  const trigger = page.getByRole("button", { name: "Analyse & Plan" });
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("menuitem", { name: "Einheit analysieren" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("menuitem", { name: "Fortschritt 4 Wochen" })).toBeFocused();
  const target = await page.getByRole("menuitem", { name: "Plan 3 Wochen" }).boundingBox();
  expect(target.width).toBeGreaterThanOrEqual(44);
  expect(target.height).toBeGreaterThanOrEqual(44);
  await page.keyboard.press("Escape");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await trigger.click();
  await page.getByRole("menuitem", { name: "Plan 3 Wochen" }).click();
  const sent = await page.evaluate(() => window.__quickSubmit);
  expect(sent.kind).toBe("plan_block");
  expect(sent.message).toContain("3 Wochen");
  await trigger.click();
  const adjust = page.getByRole("menuitem", { name: "Woche anpassen" });
  await expect(adjust).toBeVisible();
  const box = await adjust.boundingBox();
  expect(box.height).toBeGreaterThanOrEqual(44);
  await adjust.click();
  const adjusted = await page.evaluate(() => window.__quickSubmit);
  expect(adjusted.kind).toBe("adjust_week");
});

test("composer plus menu starts a session analysis anytime and fits the viewport @responsive", async ({ page }) => {
  await openCoach(page);
  await page.evaluate(() => {
    state.quickTemplatesVisible = false;
    renderQuickMessageTemplates();
    window.__quickSubmit = null;
    document.querySelector("#chatForm").addEventListener("submit", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const input = document.querySelector("#messageInput");
      window.__quickSubmit = { kind: input.dataset.requestKind, message: input.value };
    }, { capture: true });
  });
  const trigger = page.locator("#attachmentButton");
  await trigger.click();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  const menu = page.locator("#composerPlusMenu");
  await expect(menu).toBeVisible();
  await expect(page.locator("#composerPlusMenu").getByRole("menuitem", { name: "Datei anhängen" })).toBeFocused();
  const viewport = page.viewportSize();
  const box = await menu.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
  await expect(menu.getByRole("menuitem", { name: "Morgen-Check-in" })).toBeVisible();
  for (const item of await menu.getByRole("menuitem").all()) {
    const target = await item.boundingBox();
    expect(target.height).toBeGreaterThanOrEqual(44);
    expect(target.width).toBeGreaterThanOrEqual(44);
  }
  await page.keyboard.press("Escape");
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
  await expect(trigger).toBeFocused();
  await trigger.click();
  await menu.getByRole("menuitem", { name: "Einheit analysieren" }).click();
  const sent = await page.evaluate(() => window.__quickSubmit);
  expect(sent.kind).toBe("session_analysis");
  await trigger.click();
  const chooser = page.waitForEvent("filechooser");
  await menu.getByRole("menuitem", { name: "Datei anhängen" }).click();
  await chooser;
});
