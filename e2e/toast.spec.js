const { test, expect } = require("@playwright/test");

async function toastContrast(page) {
  return page.locator("#toast").evaluate((node) => {
    const parse = (value) => value.match(/[\d.]+/g).slice(0, 3).map(Number).map((channel) => {
      const normalized = channel / 255;
      return normalized <= 0.04045 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
    });
    const luminance = (rgb) => 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
    const style = getComputedStyle(node);
    const foreground = luminance(parse(style.color));
    const background = luminance(parse(style.backgroundColor));
    return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
  });
}

test("@responsive error toasts are readable, dismissible and stay above the coach composer", async ({ page }) => {
  await page.goto("/#coach");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => !state.loadPromise)).toBe(true);
  await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  await expect(page.locator("#chatForm")).toBeVisible();

  await page.evaluate(() => toast("Testfehler", true));
  const toastNode = page.locator("#toast");
  const close = toastNode.locator(".toast-close");
  await expect(toastNode).toHaveClass(/show/);
  await expect(toastNode).toHaveCSS("opacity", "1");
  await expect(close).toBeVisible();
  await expect(close).toHaveAccessibleName("Meldung schließen");

  for (const theme of ["dark", "light"]) {
    await page.evaluate((selectedTheme) => { document.documentElement.dataset.theme = selectedTheme; }, theme);
    expect(await toastContrast(page), `${theme} error toast contrast`).toBeGreaterThanOrEqual(4.5);
  }

  const toastBox = await toastNode.boundingBox();
  const composerBox = await page.locator("#chatForm").boundingBox();
  expect(toastBox.y + toastBox.height).toBeLessThanOrEqual(composerBox.y + 1);

  // Growing the composer while the toast is visible must move the toast up with it.
  await page.locator("#chatForm textarea").fill("Zeile\n".repeat(12));
  await expect.poll(async () => (await page.locator("#chatForm").boundingBox()).height).toBeGreaterThan(composerBox.height);
  await expect.poll(async () => {
    const [grownToast, grownComposer] = await Promise.all([toastNode.boundingBox(), page.locator("#chatForm").boundingBox()]);
    return grownToast.y + grownToast.height <= grownComposer.y + 1;
  }, { message: "toast stays above the grown composer" }).toBe(true);

  // The geometry checks can outlast the 8 s error lifetime on a slow runner, so dismiss a freshly shown toast.
  await page.evaluate(() => toast("Testfehler", true));
  await expect(close).toBeVisible();
  await close.click();
  await expect(toastNode).not.toHaveClass(/show/);

  await page.evaluate(() => toast("Normale Meldung"));
  await expect(toastNode).toHaveClass(/show/);
  await expect(toastNode.locator(".toast-close")).toHaveCount(0);
});
