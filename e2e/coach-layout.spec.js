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
}

async function nextFrames(page) {
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

test("coach composer keeps a stable bottom edge and publishes its height @responsive", async ({ page }) => {
  await openCoachWithScrollableChat(page);

  const composerHeight = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--composer-height").trim());
  expect(composerHeight).toMatch(/^\d+(\.\d+)?px$/);
  expect(Number.parseFloat(composerHeight)).toBeGreaterThan(0);

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
});
