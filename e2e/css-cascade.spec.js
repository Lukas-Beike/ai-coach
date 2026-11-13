const { test, expect } = require("@playwright/test");

const stylesheet = "/styles.css";

// The computed colour a custom property resolves to in the current theme.
const resolvedColour = (page, token) => page.locator("#tokenProbe").evaluate((probe, name) => {
  probe.style.color = `var(${name})`;
  return getComputedStyle(probe).color;
}, token);

test("visibility, chart variants and reduced motion override component styles", { tag: "@responsive" }, async ({ page }) => {
  await page.route("**/css-cascade-fixture", (route) => route.fulfill({
    contentType: "text/html",
    body: `<!doctype html><html><head><link rel="stylesheet" href="${stylesheet}"></head><body>
      <div id="settingsPanel" class="panel active" hidden></div>
      <video id="nutritionBarcodeVideo" hidden></video>
      <div class="auth-loading" hidden></div>
      <div class="chat-queue-status"></div>
      <input class="nutrition-low-confidence" aria-label="Uncertain nutrition value">
      <span id="tokenProbe"></span>
      <div class="analysis-chart-card"><svg>
        <path class="analysis-form-area" data-series="2" data-color="2" d="M0 0L10 10Z" />
        <path class="analysis-range-whisker" data-series="1" data-color="1" d="M0 0L10 10" />
      </svg></div>
      <div class="skeleton"></div><button class="icon-button busy"></button>
      <div class="composer"><button class="voice-button recording"></button></div>
      <div class="message assistant streaming"></div>
      <div class="working-dots"><i></i><i></i><i></i></div>
    </body></html>`,
  }));
  await page.goto("/css-cascade-fixture");
  for (const theme of ["dark", "light"]) {
    await page.locator("html").evaluate((element, theme) => { element.dataset.theme = theme; }, theme);
    for (const selector of ["[hidden]", ".chat-queue-status"]) {
      for (const element of await page.locator(selector).all()) await expect(element).toHaveCSS("display", "none");
    }
    await expect(page.locator(".analysis-form-area")).toHaveCSS("stroke", "none");
    await expect(page.locator(".analysis-range-whisker")).toHaveCSS("stroke-width", "8px");
    // The expected colours are the theme's resolved tokens, so a palette change keeps the cascade check green (#2667).
    const warning = await resolvedColour(page, "--nutrition-warning-border");
    const focusRing = await resolvedColour(page, "--accent-soft");
    await expect(page.locator(".nutrition-low-confidence")).toHaveCSS("border-top-color", warning);
    await page.locator(".nutrition-low-confidence").focus();
    await expect(page.locator(".nutrition-low-confidence")).toBeFocused();
    await expect(page.locator(".nutrition-low-confidence")).toHaveCSS("border-top-color", warning);
    await expect(page.locator(".nutrition-low-confidence")).toHaveCSS("box-shadow", `${focusRing} 0px 0px 0px 3px`);
    await page.locator(".nutrition-low-confidence").blur();
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const selector of [".skeleton", ".icon-button.busy", ".voice-button.recording"]) {
    await expect(page.locator(selector)).toHaveCSS("animation-duration", "1e-05s");
    await expect(page.locator(selector)).toHaveCSS("animation-iteration-count", "1");
  }
  expect(await page.locator(".message.streaming").evaluate((element) => getComputedStyle(element, "::after").animationDuration)).toBe("1e-05s");
  await expect(page.locator(".icon-button")).toHaveCSS("transition-duration", "1e-05s");
  for (const [index, dot] of (await page.locator(".working-dots i").all()).entries()) {
    await expect(dot).toHaveCSS("animation-name", "working-dot-fade");
    await expect(dot).toHaveCSS("animation-duration", "1.1s");
    await expect(dot).toHaveCSS("animation-iteration-count", "infinite");
    await expect(dot).toHaveCSS("animation-delay", `${index * 0.15}s`);
  }
});
