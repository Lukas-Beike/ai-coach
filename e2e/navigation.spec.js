const { test, expect } = require("@playwright/test");

test("@responsive each hash navigation renders its target once", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  await page.evaluate(() => {
    globalThis.__routeRenderCounts = {};
    document.addEventListener("app:route-rendered", (event) => {
      const route = event.detail?.route;
      if (route) globalThis.__routeRenderCounts[route] = (globalThis.__routeRenderCounts[route] || 0) + 1;
    });
  });
  for (const route of ["plan", "nutrition", "analysis", "more", "coach"]) {
    await page.evaluate(async (nextRoute) => {
      const changed = new Promise((resolve) => globalThis.addEventListener("hashchange", resolve, { once: true }));
      const rendered = new Promise((resolve) => document.addEventListener("app:route-rendered", resolve, { once: true }));
      globalThis.location.hash = nextRoute;
      await changed;
      await rendered;
    }, route);
    expect(await page.evaluate((name) => globalThis.__routeRenderCounts[name] || 0, route)).toBe(1);
  }
});

test("@responsive the logout button only appears in Betrieb & Diagnose", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  for (const segment of ["appearance", "equipment", "connections", "coach"]) {
    await page.goto(`/#more/${segment}`);
    await expect(page.locator(`#settingsPanel [data-more-segment-panel="${segment}"]`).first()).toBeVisible();
    await expect(page.locator("#logoutButton"), segment).toBeHidden();
  }
  await page.goto("/#more/operations");
  await expect(page.locator("#logoutButton")).toBeVisible();
  // The version sits in the settings, not in the header.
  await expect(page.locator("#settingsAppVersion")).toHaveText(/^v\d+\.\d+\.\d+/);
  await expect(page.locator("header.topbar")).not.toContainText(/PRIVATER TRAININGSBEREICH|v\d+\.\d+\.\d+/);
  await expect(page.locator("#privacyExportButton")).toBeHidden();
  await page.evaluate(() => document.querySelectorAll('details[data-more-segment-panel="operations"]').forEach((section) => { section.open = true; }));
  await expect(page.locator("#privacyExportButton")).toBeVisible();
});

test("@responsive the navigation shows fitting labels and no panel outline after reload", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await page.reload();
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  const panel = page.locator(".panel.active");
  await expect(panel).toBeFocused();
  const outline = await panel.evaluate((element) => {
    const { outlineStyle, outlineWidth } = getComputedStyle(element);
    return { outlineStyle, outlineWidth };
  });
  expect(outline.outlineStyle === "none" || Number.parseFloat(outline.outlineWidth) === 0).toBe(true);
  const items = page.locator(".desktop-nav:visible .nav-item, .bottom-nav:visible .nav-item");
  await expect(items).toHaveCount(5);
  for (const item of await items.all()) {
    const label = item.locator("span:visible");
    await expect(label).toBeVisible();
    const fit = await item.evaluate((element) => {
      const text = element.querySelector("span:not([hidden])");
      const box = element.getBoundingClientRect();
      const textBox = text.getBoundingClientRect();
      return { height: box.height, width: box.width, textFits: text.scrollWidth <= text.clientWidth + 1 && textBox.left >= box.left - 1 && textBox.right <= box.right + 1 };
    });
    expect(fit.height).toBeGreaterThanOrEqual(44);
    expect(fit.width).toBeGreaterThanOrEqual(44);
    expect(fit.textFits).toBe(true);
  }
});

test("@responsive each navigation item is a stable hash link that opens and focuses its panel", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
  await expect(page.locator("svg.icon-sprite")).toHaveCount(1);
  for (const [name, hash, panel] of [["Kalender", "#plan/overview", "workoutsPanel"], ["Analyse", "#analysis/running", "dataPanel"], ["Mehr", "#more", "settingsPanel"], ["Coach", "#coach", "chatPanel"]]) {
    const item = page.locator(`.desktop-nav:visible .nav-item[aria-label="${name}"], .bottom-nav:visible .nav-item[aria-label="${name}"]`);
    await expect(item, name).toHaveAttribute("href", hash);
    await item.click();
    await expect(page).toHaveURL(new RegExp(`${hash}$`));
    await expect(page.locator(`#${panel}`)).toHaveClass(/active/);
    await expect(page.locator(`#${panel}`)).toBeFocused();
    await expect(item).toHaveAttribute("aria-current", "page");
  }
  // A hash of a removed route opens the Coach and replaces the address.
  for (const removed of ["#today", "#activities", "#planned", "#analysis/history"]) {
    await page.goto(`/${removed}`);
    await expect(page).toHaveURL(/#coach$/);
    await expect(page.locator("#chatPanel")).toHaveClass(/active/);
  }
});

test("@responsive Alt+1 to Alt+5 switch the main views outside text fields and are listed in Darstellung", async ({ page }) => {
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  const current = page.locator(".bottom-nav .nav-item[aria-current='page'], .desktop-nav .nav-item[aria-current='page']").first();
  // Navigation order, as the nav lists them (#2812).
  for (const [digit, name, hash] of [[2, "Kalender", /#plan/], [3, "Analyse", /#analysis/], [4, "Ernährung", /#nutrition/], [5, "Mehr", /#more/], [1, "Coach", /#coach/]]) {
    await page.keyboard.press(`Alt+Digit${digit}`);
    await expect(page).toHaveURL(hash);
    await expect(current).toHaveAttribute("aria-label", name);
    await expect(page.locator(`.desktop-nav .nav-item[aria-label='${name}']`)).toHaveAttribute("aria-keyshortcuts", `Alt+${digit}`);
  }
  // Typing keeps the view; Ctrl+Alt (AltGr) types characters and switches nothing.
  await page.locator("#messageInput").focus();
  await page.keyboard.press("Alt+Digit2");
  await page.locator("#messageInput").blur();
  await page.keyboard.press("Control+Alt+Digit2");
  // An open dialog or popover menu keeps the view behind it; an open tooltip does not.
  const probe = (role) => page.evaluate((kind) => {
    const layer = document.body.appendChild(document.createElement(kind === "dialog" ? "dialog" : "div"));
    layer.id = "shortcutProbe";
    if (kind === "dialog") return layer.showModal();
    layer.setAttribute("role", kind);
    layer.popover = "manual";
    layer.showPopover();
  }, role);
  for (const role of ["dialog", "menu"]) {
    await probe(role);
    await page.keyboard.press("Alt+Digit2");
    await page.evaluate(() => document.getElementById("shortcutProbe").remove());
  }
  await expect(page).toHaveURL(/#coach/);
  await probe("tooltip");
  await page.keyboard.press("Alt+Digit3");
  await expect(page).toHaveURL(/#analysis/);
  await page.evaluate(async () => { document.getElementById("shortcutProbe").remove(); await AppRouter.navigate("more/appearance", { historyMode: "replace" }); });
  const help = page.locator(".shortcut-help");
  if ((page.viewportSize()?.width || 0) < 768) {
    await expect(help).toBeHidden();
    return;
  }
  await help.locator("summary").click();
  await expect(help.locator("dt")).toHaveText(["Alt+1", "Alt+2", "Alt+3", "Alt+4", "Alt+5"]);
  await expect(help.locator("dd")).toHaveText(["Coach", "Kalender", "Analyse", "Ernährung", "Mehr"]);
});
