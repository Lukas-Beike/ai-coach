const { test, expect } = require("@playwright/test");

async function openCoachWithScrollableChat(page) {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !state.loadPromise)).toBe(true);
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  // Synthetic spacer that makes the chat page taller than the viewport.
  await page.evaluate(() => {
    const spacer = document.createElement("div");
    spacer.dataset.e2eSpacer = "true";
    spacer.style.height = "2400px";
    document.querySelector("#messages").append(spacer);
  });
  // Let scroll anchoring settle before the test measures and changes the page position.
  await nextFrames(page);
}

async function nextFrames(page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function expectComposerBottomStable(page) {
  const maxScroll = await page.evaluate(() => document.documentElement.scrollHeight - globalThis.innerHeight);
  expect(maxScroll).toBeGreaterThan(0);

  const composer = page.locator("#chatForm");
  const bottoms = [];
  for (const top of [0, Math.round(maxScroll / 2), maxScroll]) {
    await page.evaluate((y) => globalThis.scrollTo({ top: y, behavior: "instant" }), top);
    await nextFrames(page);
    const scrollY = await page.evaluate(() => globalThis.scrollY);
    expect(Math.abs(scrollY - top)).toBeLessThanOrEqual(1);
    const box = await composer.boundingBox();
    expect(box).not.toBeNull();
    bottoms.push(box.y + box.height);
  }

  for (const bottom of bottoms) {
    expect(Math.abs(bottom - bottoms[0])).toBeLessThanOrEqual(1);
  }
}

test("coach composer keeps a stable bottom edge and publishes its height @responsive", async ({ page }) => {
  await openCoachWithScrollableChat(page);

  const composerHeight = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--composer-height").trim());
  expect(composerHeight).toMatch(/^\d+(\.\d+)?px$/);
  expect(Number.parseFloat(composerHeight)).toBeGreaterThan(0);

  await expectComposerBottomStable(page);
});

test("coach composer keeps a stable bottom edge in phone landscape @responsive", async ({ page }) => {
  await page.setViewportSize({ width: 700, height: 400 });
  await openCoachWithScrollableChat(page);

  await expectComposerBottomStable(page);
});

test("coach composer keeps a stable bottom edge while the voice status is visible @responsive", async ({ page }) => {
  await openCoachWithScrollableChat(page);
  await page.evaluate(() => {
    const status = document.querySelector("#voiceStatus");
    status.textContent = "Aufnahme läuft";
    status.hidden = false;
  });

  await expectComposerBottomStable(page);
});

test("empty coach chat does not promise quick actions and keeps the composer gap @responsive", async ({ page }) => {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !state.loadPromise)).toBe(true);
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  // Quick actions appear only after inactivity, so a first visit must not be pointed at them.
  await page.evaluate(() => { state.quickTemplatesVisible = false; renderQuickMessageTemplates(); });
  const empty = page.locator("#messages .empty-state");
  await expect(empty).toBeVisible();
  await expect(empty).not.toContainText("Schnellaktion");

  const nav = page.locator(".bottom-nav");
  const composerGap = async () => {
    await nextFrames(page);
    const composer = await page.locator("#chatForm").boundingBox();
    return (await nav.boundingBox()).y - (composer.y + composer.height);
  };
  if (!(await nav.isVisible())) return;
  const emptyGap = await composerGap();
  await page.evaluate(() => {
    const spacer = document.createElement("div");
    spacer.dataset.e2eSpacer = "true";
    spacer.style.height = "2400px";
    document.querySelector("#messages").append(spacer);
  });
  expect(Math.abs(emptyGap - (await composerGap()))).toBeLessThanOrEqual(1);
});
