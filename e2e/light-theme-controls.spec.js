const { test, expect } = require("@playwright/test");

async function openApp(page, request) {
  expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
  await page.goto("/");
  await page.waitForFunction(() => state.initialStateLoaded);
}

test("@responsive form, error and graphic tokens meet 4.5:1 in both themes", async ({ page, request }) => {
  await openApp(page, request);
  const ratios = await page.evaluate(() => {
    const channel = (value) => { const c = value / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    const luminance = (rgb) => 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
    const probe = document.createElement("span");
    document.body.append(probe);
    const resolve = (value) => { probe.style.color = value; return getComputedStyle(probe).color.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number); };
    const contrast = (a, b) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
    const out = {};
    for (const theme of ["dark", "light"]) {
      document.documentElement.dataset.theme = theme;
      const css = getComputedStyle(document.documentElement);
      for (const token of ["--form-caution-ink", "--form-error-ink", "--calendar-profile-ink", "--training-zone-3"]) {
        for (const surface of ["--bg", "--surface-raised"]) {
          out[`${theme} ${token} on ${surface}`] = contrast(resolve(css.getPropertyValue(token)), resolve(css.getPropertyValue(surface)));
        }
      }
      // The real rules must consume the tokens.
      const tile = document.createElement("div");
      tile.className = "metric-grid";
      tile.innerHTML = '<div class="metric-form-caution"><strong>x</strong></div><div class="metric-form-bad"><strong>y</strong></div>';
      const error = document.createElement("p");
      error.className = "credential-error";
      document.body.append(tile, error);
      const bg = resolve(css.getPropertyValue("--bg"));
      for (const element of [tile.querySelector(".metric-form-caution strong"), tile.querySelector(".metric-form-bad strong"), error]) {
        out[`${theme} ${element.className || element.parentElement.className} text`] = contrast(resolve(getComputedStyle(element).color), bg);
      }
      tile.remove();
      error.remove();
    }
    probe.remove();
    return out;
  });
  for (const [name, ratio] of Object.entries(ratios)) expect(ratio, name).toBeGreaterThanOrEqual(4.5);
});

test("@responsive inputs are at least 16px under coarse pointer and dialog actions share a font size", async ({ page, request }) => {
  await openApp(page, request);
  const coarse = await page.evaluate(() => matchMedia("(hover: none) and (pointer: coarse)").matches);
  if (coarse) {
    const small = await page.evaluate(() => [...document.querySelectorAll("input, select, textarea")]
      .filter((el) => !["hidden", "checkbox", "radio", "range", "file"].includes(el.type))
      .map((el) => ({ id: el.id || el.name || el.className, size: parseFloat(getComputedStyle(el).fontSize) }))
      .filter((el) => el.size < 16));
    expect(small).toEqual([]);
  }
  const sizes = await page.evaluate(() => [...document.querySelectorAll("dialog .dialog-actions")]
    .map((actions) => [...actions.querySelectorAll("button")].map((b) => getComputedStyle(b).fontSize)));
  expect(sizes.length).toBeGreaterThan(0);
  for (const group of sizes) expect(new Set(group).size).toBe(1);
});
