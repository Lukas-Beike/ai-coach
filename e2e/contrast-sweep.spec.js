const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;
const { waitForSettledState } = require("./helpers/settled-state");
const { waitForOlderSessions } = require("./helpers/calendar");
const { contrastRatio, showCalendarEntry, openSessionDetails } = require("./helpers/ui");

// #2530: WCAG AA text contrast of every main view and segment, collapsibles opened, in both themes.
const THEMES = ["light", "dark"];
// [view label, route, calendar view]. One test per group and theme keeps each test short.
const GROUPS = {
  "Coach und Kalender": [
    ["Coach", "coach"],
    ["Kalender Woche", "plan/overview"],
    ["Kalender Monat", "plan/overview", "month"],
    ["Kalender Bibliothek", "plan/library"],
    ["Kalender Wettkämpfe", "plan/season"],
  ],
  Analyse: ["running", "cycling", "load", "recovery"].map((segment) => [`Analyse ${segment}`, `analysis/${segment}`]),
  "Ernährung": ["diary", "week", "body", "products"].map((segment) => [`Ernährung ${segment}`, `nutrition/${segment}`]),
  Mehr: ["appearance", "profile", "equipment", "connections", "coach", "operations"].map((segment) => [`Mehr ${segment}`, `more/${segment}`]),
};
// The active view plus the shell around it: sidebar, topbar, status strip and bottom navigation with the active item.
const SCOPES = [".panel.active", ".desktop-nav", ".topbar", "#statusStrip", ".bottom-nav"];
// Content that a collapsible loads or renders when it opens; the scan waits for it.
const READY = { "more/profile": ["#zoneOverview [data-zone-box]"], "more/operations": ["#gpsTracksToggle:enabled"] };
// Nodes axe reports as "incomplete" because it has no text to measure or cannot sample their backdrop. Each entry
// names the node and axe's message and why it is accepted; anything else fails the sweep.
const INCOMPLETE_ALLOWED = [
  {
    target: /^\.status-strip-main > \.status-strip-dismiss|^#nutrition(Previous|Next)$|\.nutrition-favorite/,
    message: /only non-text characters/,
    reason: "Icon-only buttons (a cross, week arrows, a favourite star) hold a glyph without text content; there is no text contrast to measure.",
  },
  {
    target: /svg|^text\[|^\.analysis-(date-tick|value-tick|axis-unit)\[/,
    message: /image node|overlapped by another element|too short to determine/,
    reason: "Chart axis ticks, units and value labels are SVG text drawn over the plot elements (or a one-character unit); axe reports an image node, an overlap or too little text and cannot decide.",
  },
  {
    target: /^\.analysis-point-value\[/,
    message: /image node|overlapped by another element|too short to determine/,
    reason: "A chart value label is drawn with a halo over the plot lines; when it has one or two characters, crosses a line or sits on a plot mark axe cannot decide. Its fill against its halo and the card is asserted in \"chart value labels meet AA contrast\" below for every analysis view (#2708).",
  },
  {
    target: /(^| > )tr:nth-child\(\d+\) > t[dh]/,
    message: /partially obscured/,
    reason: "Rows of a value table scrolled out of its own max-height scroll area (.analysis-chart-table); the visible rows are decided.",
  },
  {
    target: /^#group-info-\d+ > p/,
    message: /partially overlaps other elements/,
    reason: "A paragraph of the opened explanation popover on the narrow viewport; the popover is a top-layer box over the chart, whose elements axe sees overlapping it. Its other nodes are decided.",
  },
];

// Only finite animations: a spinner or pulse never ends and must not hang the test.
async function finishAnimations(page) {
  await page.evaluate(() => Promise.allSettled(document.getAnimations()
    .filter((animation) => animation.effect?.getTiming().iterations !== Infinity)
    .map((animation) => animation.finished)));
}

// The dark page background is a flat colour under two soft radial glows (at most 15 % alpha) that axe cannot flatten
// and reports every text on as undecided. The scan measures against the flat colour instead; the light theme has no glow.
async function flattenPageGlow(page) {
  await page.evaluate(() => {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync("body { background-image: none !important; }");
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  });
}

async function applyTheme(page, theme) {
  await page.evaluate((selected) => { document.documentElement.dataset.theme = selected; }, theme);
  await finishAnimations(page);
}

// `opened` also waits for what the opened collapsibles render.
async function settle(page, route, opened = false) {
  await waitForSettledState(page);
  const panel = page.locator(".panel.active");
  await expect(panel.locator(".loading-state, [aria-busy='true'], .skeleton")).toHaveCount(0);
  if (opened) for (const selector of READY[route] || []) await expect(panel.locator(selector).first()).toBeVisible();
}

// Opens the collapsibles of the active view and again those that opening them rendered. Calendar cards stay
// closed: they are an exclusive accordion and a session's "Details" starts a read per session.
async function openCollapsibles(page, route) {
  for (let pass = 0; pass < 5; pass += 1) {
    const opened = await page.evaluate(() => {
      const closed = [...document.querySelectorAll(".panel.active details:not([open])")].filter((element) => !element.matches(".planned-entry, .planned-activity-more"));
      for (const element of closed) element.open = true;
      return closed.length;
    });
    await settle(page, route, true);
    if (!opened) return;
  }
}

// Opens the completed session that holds `match` with its "Details" panel once it has loaded.
async function openSessionWithDetails(page, match) {
  await showCalendarEntry(page, match);
  const card = page.locator(".planned-entry.is-completed").filter({ hasText: match }).first();
  await card.evaluate((element) => {
    for (let parent = element.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === "DETAILS") parent.open = true;
    }
  });
  const panel = (await openSessionDetails(page, match)).locator(".activity-analysis-panel");
  await expect(panel).not.toBeEmpty();
  await expect(panel.locator(".loading-state")).toHaveCount(0);
  await expect(panel.locator(".error-state")).toHaveCount(0);
}

async function showView(page, route, calendarView) {
  await page.evaluate((target) => AppRouter.navigate(target, { historyMode: "replace" }), route);
  await settle(page, route);
  if (route === "plan/overview" && calendarView === "month") {
    await page.locator('.planned-view-switch [data-view="month"]').click();
    await expect(page.locator('.planned-view-switch [data-view="month"]')).toHaveAttribute("aria-pressed", "true");
    await waitForOlderSessions(page);
    // The month shows the week of a tapped day with sessions below the grid.
    await page.locator(".planned-month-day:not([disabled]):has(.planned-month-mark)").last().click();
    await waitForOlderSessions(page);
    const entry = page.locator("#plannedCalendar .planned-entry").first();
    await expect(entry).toBeVisible();
    await entry.evaluate((element) => { element.open = true; });
  } else if (route === "plan/overview") {
    await openSessionWithDetails(page, "Synthetic completed");
  }
  await openCollapsibles(page, route);
}

// Fails with the view, the theme and every failing node with its measured and expected contrast.
async function expectContrast(page, view, theme, scopes = SCOPES) {
  await page.mouse.move(0, 0);
  await finishAnimations(page);
  const builder = new AxeBuilder({ page }).withRules(["color-contrast"]);
  for (const scope of scopes) builder.include(scope);
  const { violations, incomplete, passes } = await builder.analyze();
  // A scope that matches nothing would pass without measuring anything.
  expect(passes.concat(violations).reduce((count, rule) => count + rule.nodes.length, 0), `${view} [${theme}]: no node measured`).toBeGreaterThan(0);
  const failures = violations.flatMap((violation) => violation.nodes.map((node) => {
    const data = node.any.find((check) => check.id === "color-contrast")?.data || {};
    return `${view} [${theme}] ${node.target.join(" ")}: ${data.contrastRatio} < ${data.expectedContrastRatio} (${data.fgColor} on ${data.bgColor}, ${data.fontSize}, ${data.fontWeight})`;
  }));
  expect(failures, `colour contrast violations:\n${failures.join("\n")}`).toEqual([]);
  const undecided = incomplete.flatMap((result) => result.nodes.map((node) => ({ target: node.target.join(" "), message: node.any[0]?.message || result.help })))
    .filter(({ target, message }) => !INCOMPLETE_ALLOWED.some((allowed) => allowed.target.test(target) && allowed.message.test(message)))
    .map(({ target, message }) => `${view} [${theme}] ${target}: ${message}`);
  expect(undecided, `colour contrast axe could not decide:\n${undecided.join("\n")}`).toEqual([]);
}

test.describe("colour contrast sweep", () => {
  for (const [group, views] of Object.entries(GROUPS)) {
    for (const theme of THEMES) {
      test(`@responsive ${group} meets AA contrast in the ${theme} theme`, async ({ page, request }) => {
        test.setTimeout(120_000);
        expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
        await page.goto("/");
        await page.waitForFunction(() => state.initialStateLoaded);
        await flattenPageGlow(page);
        for (const [view, route, calendarView] of views) {
          await showView(page, route, calendarView);
          await applyTheme(page, theme);
          await expectContrast(page, view, theme);
          if (route === "analysis/running") {
            // One opened explanation popover.
            await page.locator(".panel.active .analysis-legend-info:visible").first().click();
            await expect(page.locator(".analysis-info-tooltip:popover-open")).toHaveCount(1);
            await expectContrast(page, `${view} Erklärung`, theme);
            await page.keyboard.press("Escape");
          }
          if (route === "analysis/load" || route === "analysis/recovery") {
            // The other period of the view (the page default is scanned above).
            await page.locator(".panel.active .analysis-period-controls:visible button[aria-pressed='false']").first().click();
            await openCollapsibles(page, route);
            await expectContrast(page, `${view} Zeitraum`, theme);
          }
        }
      });
    }
  }

  // #2708: the value labels' own contrast, measured from computed colours, whatever their length.
  test("@responsive chart value labels meet AA contrast against their halo and card in both themes", async ({ page, request }) => {
    expect((await request.get("/api/fixture/demo")).ok()).toBeTruthy();
    await page.goto("/");
    await page.waitForFunction(() => state.initialStateLoaded);
    for (const [segment, theme] of ["running", "cycling", "load", "recovery"].flatMap((name) => THEMES.map((mode) => [name, mode]))) {
      await showView(page, `analysis/${segment}`);
      await applyTheme(page, theme);
      const labels = await page.locator(".panel.active .analysis-point-value").evaluateAll((nodes) => nodes.map((node) => {
        let holder = node.parentElement;
        while (holder && /rgba\([^)]*,\s*0\)|transparent/.test(getComputedStyle(holder).backgroundColor)) holder = holder.parentElement;
        const style = getComputedStyle(node);
        return { text: node.textContent, fill: style.fill, halo: style.stroke, card: getComputedStyle(holder || document.body).backgroundColor };
      }));
      if (segment === "load" || segment === "recovery") expect(labels.length, `${segment} ${theme}`).toBeGreaterThan(0);
      for (const label of labels) {
        expect(contrastRatio(label.fill, label.card), `${segment} ${theme} ${label.text} on card`).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(label.fill, label.halo), `${segment} ${theme} ${label.text} on halo`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  test.describe("login dialog", () => {
    // Start unauthenticated; the project default storage state holds the authenticated session.
    test.use({ storageState: { cookies: [], origins: [] } });

    test("@responsive meets AA contrast in both themes", async ({ page }) => {
      await page.goto("/");
      await expect(page.locator("#loginDialog")).toBeVisible();
      await flattenPageGlow(page);
      for (const theme of THEMES) {
        await applyTheme(page, theme);
        await expectContrast(page, "Anmeldung", theme, ["#loginDialog"]);
      }
    });
  });
});
