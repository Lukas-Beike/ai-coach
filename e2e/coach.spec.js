const { test, expect } = require("@playwright/test");
const { AxeBuilder } = require("@axe-core/playwright");

const navigation = [
  ["Coach", "chatPanel", "coach"],
  ["Heute", "todayPanel", "today"],
  ["Geplant", "workoutsPanel", "plan/overview"],
  ["Analyse", "dataPanel", "analysis/performance"],
  ["Mehr", "settingsPanel", "more"],
];

async function openAuthenticatedApp(page) {
  await page.goto("/");
  const loginDialog = page.locator("#loginDialog");
  await expect(loginDialog).toBeHidden();
  await expect(page.locator("#appShell")).toBeVisible();
}

function installBrowserGuards(page) {
  const browserErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => browserErrors.push(`page: ${error.message}`));
  return browserErrors;
}

async function expectNoBrowserErrorsOrOverflow(page, browserErrors) {
  expect(browserErrors, "browser console/page errors").toEqual([]);
  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    body: document.body.scrollWidth > document.body.clientWidth + 1,
  }));
  expect(overflow, "horizontal overflow").toEqual({ document: false, body: false });
}

async function installControlledChatStream(page) {
  await page.evaluate(() => {
    const originalFetch = window.fetch.bind(window);
    const encoder = new TextEncoder();
    const chatTest = {
      controller: null,
      historyMessages: [],
      historyResolvers: [],
      stableMessageNode: null,
    };
    chatTest.push = (event, payload) => {
      chatTest.controller.enqueue(encoder.encode(`event: ${event}\r\ndata: ${JSON.stringify(payload)}\r\n\r\n`));
    };
    chatTest.finish = () => chatTest.controller.close();
    chatTest.releaseHistory = () => {
      const body = JSON.stringify({ messages: chatTest.historyMessages, next_cursor: null });
      chatTest.historyResolvers.splice(0).forEach((resolve) => resolve(new Response(body, {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })));
    };
    window.__chatTest = chatTest;
    window.fetch = (input, options) => {
      const url = typeof input === "string" ? input : input.url;
      if (url === "/api/chat/stream") {
        chatTest.clientTurnId = JSON.parse(options.body).client_turn_id;
        return Promise.resolve(new Response(new ReadableStream({
          start(controller) {
            chatTest.controller = controller;
            chatTest.push("started", { operation_id: "browser-test-operation" });
          },
        }), { status: 200, headers: { "Content-Type": "text/event-stream" } }));
      }
      if (url.startsWith("/api/chat/history")) {
        return new Promise((resolve) => chatTest.historyResolvers.push(resolve));
      }
      if (url.startsWith("/api/chat/receipt")) {
        return Promise.resolve(new Response(JSON.stringify({ status: "completed", proposed_actions: [], command_receipts: [] }), { status: 200 }));
      }
      return originalFetch(input, options);
    };
  });
}

test.describe("critical browser states", () => {
  test("login, main views, dialog and profile form state", async ({ page }, testInfo) => {
    const browserErrors = installBrowserGuards(page);

    const authenticatedState = await page.context().storageState();
    await page.context().clearCookies();
    await page.goto("/#more/profile");
    await expect(page.locator("#loginDialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Anmelden" })).toBeVisible();
    await expect(page.getByLabel("Passwort")).toBeEditable();
    await expect(page.getByRole("button", { name: "Anmelden" })).toBeEnabled();
    await page.context().addCookies(authenticatedState.cookies);
    await page.reload();
    await expect(page.locator("#loginDialog")).toBeHidden();
    await expect(page.locator("#appShell")).toBeVisible();
    await expect(page.locator("#profilePanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#more\/profile$/);
    await expect(page.locator("#profilePanel")).toBeFocused();
    await expect(page.locator(".dirty-indicator")).toHaveCount(3);
    const hiddenIndicators = await page.locator(".dirty-indicator").evaluateAll((nodes) => nodes.every((node) => node.hidden));
    expect(hiddenIndicators).toBe(true);
    for (const [label, panelId, route] of navigation) {
      await page.getByRole("link", { name: label, exact: true }).click();
      await expect(page.locator(`#${panelId}`)).toHaveClass(/active/);
      await expect(page.getByRole("link", { name: label, exact: true })).toHaveAttribute("aria-current", "page");
      await expect(page.getByRole("link", { name: label, exact: true })).toHaveAttribute("href", `#${route}`);
    }

    await page.getByRole("link", { name: "Analyse", exact: true }).click();
    await expect(page).toHaveURL(/#analysis\/performance$/);
    await page.getByRole("link", { name: "Verlauf", exact: true }).click();
    await expect(page).toHaveURL(/#analysis\/history$/);
    await page.goBack();
    await expect(page.locator("#dataPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#analysis\/performance$/);
    await page.getByRole("link", { name: "Mehr", exact: true }).click();
    await expect(page.locator("#settingsPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#more$/);
    await page.goto("/#analysis/performance");
    await expect(page.locator("#dataPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#analysis\/performance$/);
    await page.goto("/#unknown-route");
    await expect(page.locator("#chatPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#coach$/);

    const settingsNav = page.locator("#settingsPanel .more-segment-nav");
    await page.getByRole("link", { name: "Mehr", exact: true }).click();
    await expect(page).toHaveURL(/#more$/);
    await expect(page.locator('[data-more-segment-panel="connections"]').first()).toBeVisible();
    await page.getByRole("link", { name: "Coach & Modell", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#more\/coach$/);
    await page.getByRole("link", { name: "Mehr", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#more$/);
    await settingsNav.getByRole("link", { name: "Coach & Modell", exact: true }).click();
    await expect(page).toHaveURL(/#more\/coach$/);
    await expect(page.locator('[data-more-segment-panel="coach"]')).toHaveCount(2);
    await expect(page.locator('[data-more-segment-panel="coach"]').first()).toBeVisible();
    await expect(page.locator('[data-more-segment-panel="connections"]').first()).toBeHidden();
    await settingsNav.getByRole("link", { name: "Daten & Datenschutz", exact: true }).click();
    await expect(page).toHaveURL(/#more\/privacy$/);
    await expect(page.locator('[data-more-segment-panel="privacy"]')).toBeVisible();
    await settingsNav.getByRole("link", { name: "Betrieb & Diagnose", exact: true }).click();
    await expect(page).toHaveURL(/#more\/operations$/);
    await expect(page.locator('[data-more-segment-panel="operations"]').first()).toBeVisible();
    await settingsNav.getByRole("link", { name: "Athletenprofil", exact: true }).click();
    await expect(page).toHaveURL(/#more\/profile$/);
    await expect(page.locator("#profilePanel")).toHaveClass(/active/);
    await expect(page.locator("#profileContextNotice")).toBeVisible();

    await page.getByRole("link", { name: "Geplant", exact: true }).click();
    await expect(page).toHaveURL(/#plan\/overview$/);
    await expect(page.getByRole("heading", { name: "Geplant", exact: true })).toBeVisible();
    await page.locator(".plan-segment-nav").getByRole("link", { name: "Bibliothek", exact: true }).click();
    await expect(page).toHaveURL(/#plan\/library$/);
    await expect(page.getByRole("heading", { name: "Bibliothek", exact: true })).toBeVisible();
    await page.goto("/#plan");
    await expect(page.locator("#workoutsPanel")).toHaveClass(/active/);
    await expect(page).toHaveURL(/#plan$/);

    await page.getByRole("link", { name: "Heute", exact: true }).click();
    await expect(page.locator("#todayPanel .today-priority")).toHaveCount(0);
    await expect(page.locator("#todayPanel .today-checkin")).toHaveCount(0);
    await expect(page.locator("#todayPanel .today-feedback")).toHaveCount(0);
    await expect(page.locator("#checkinDialog")).toBeHidden();
    await expect(page.locator("#chatPanel")).toContainText("Morgen-Check-in");

    const undersizedTargets = await page.locator(".panel.active button:visible, .panel.active a:visible, .panel.active input:visible, .panel.active textarea:visible, .panel.active select:visible, .panel.active summary:visible, .bottom-nav a:visible").evaluateAll((nodes) => nodes
      .filter((node) => !node.closest("[hidden]"))
      .filter((node) => node.getBoundingClientRect().width < 44 || node.getBoundingClientRect().height < 44)
      .map((node) => ({ tag: node.tagName, id: node.id, text: node.textContent.trim().slice(0, 40) })));
    expect(undersizedTargets, "visible touch targets below 44 CSS pixels").toEqual([]);

    await page.getByRole("link", { name: "Coach", exact: true }).click();
    const safetyHint = page.getByText("Trainingsempfehlungen dienen zur Orientierung", { exact: false });
    await expect(safetyHint).toBeVisible();
    const chatIsEmpty = await page.locator("#messages").evaluate((node) => node.classList.contains("has-empty-state"));
    if (testInfo.project.name === "desktop" && chatIsEmpty) {
      const emptyLayout = await page.evaluate(() => {
        const messages = document.querySelector("#messages").getBoundingClientRect();
        const composer = document.querySelector("#chatForm").getBoundingClientRect();
        return { composerTop: composer.top, messagesHeight: messages.height, viewportHeight: window.innerHeight };
      });
      expect(emptyLayout.messagesHeight).toBeLessThanOrEqual(441);
      expect(emptyLayout.composerTop).toBeLessThanOrEqual(emptyLayout.viewportHeight * 0.78);
    }
    await page.screenshot({ path: testInfo.outputPath("coach-core.png"), fullPage: true });
    await safetyHint.scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
    await safetyHint.scrollIntoViewIfNeeded();
    const safetyLayout = await page.evaluate(() => {
      const hint = document.querySelector("#chatPanel .fine-print").getBoundingClientRect();
      const composer = document.querySelector("#chatForm").getBoundingClientRect();
      const navigationNode = document.querySelector(".bottom-nav");
      const navigation = navigationNode && getComputedStyle(navigationNode).display !== "none"
        ? navigationNode.getBoundingClientRect()
        : null;
      return { hintBottom: hint.bottom, composerTop: composer.top, navigationTop: navigation?.top ?? Number.POSITIVE_INFINITY };
    });
    expect(safetyLayout.hintBottom).toBeLessThanOrEqual(Math.min(safetyLayout.composerTop, safetyLayout.navigationTop));
    await page.evaluate(() => { document.documentElement.style.fontSize = ""; });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.getByRole("link", { name: "Heute", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#todayPanel")).toHaveClass(/active/);

    await page.goto("/#more/profile");
    await expect(page.locator("#profilePanel")).toHaveClass(/active/);
    const profileName = page.getByLabel("Name");
    await profileName.fill("Fixture Athlete");
    await expect(page.locator("#profileDirtyIndicator")).toBeVisible();
    await expect(page.getByRole("button", { name: "Athletenkontext speichern" })).toBeEnabled();

    await expectNoBrowserErrorsOrOverflow(page, browserErrors);
  });

  test("core views satisfy WCAG AA checks", async ({ page }, testInfo) => {
    const browserErrors = installBrowserGuards(page);
    const authenticatedState = await page.context().storageState();
    await page.context().clearCookies();
    await page.goto("/");
    await expect(page.locator("#loginDialog")).toBeVisible();
    const loginResults = await new AxeBuilder({ page })
      .include("#loginDialog")
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(loginResults.violations, "Login accessibility violations").toEqual([]);
    await page.context().addCookies(authenticatedState.cookies);
    await openAuthenticatedApp(page);
    const manifest = await page.request.get("/manifest.webmanifest");
    expect(manifest.ok()).toBe(true);
    expect(await manifest.json()).toMatchObject({ id: "/", scope: "/", start_url: "/", display: "standalone" });
    if (await page.evaluate(() => window.isSecureContext && "serviceWorker" in navigator)) {
      await expect.poll(() => page.evaluate(async () => (await navigator.serviceWorker.ready).active?.state)).toBe("activated");
    }

    for (const [label, panelId] of navigation) {
      await page.getByRole("link", { name: label, exact: true }).click();
      await expect(page.locator(`#${panelId}`)).toHaveClass(/active/);
      const results = await new AxeBuilder({ page })
        .include(`#${panelId}`)
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      expect(results.violations, `${label} accessibility violations`).toEqual([]);
    }

    await expectNoBrowserErrorsOrOverflow(page, browserErrors);
    await page.screenshot({ path: testInfo.outputPath("settings-core.png"), fullPage: true });
  });

  test("inactive panels stay hidden and compact labels remain readable", async ({ page }) => {
    const browserErrors = installBrowserGuards(page);
    await openAuthenticatedApp(page);
    await page.getByRole("link", { name: "Coach", exact: true }).click();
    const panelState = await page.locator("main .panel").evaluateAll((panels) => panels.map((panel) => ({
      id: panel.id,
      active: panel.classList.contains("active"),
      display: getComputedStyle(panel).display,
    })));
    expect(panelState.filter((panel) => !panel.active && panel.display !== "none"), "inactive panels must not leak into the active view").toEqual([]);
    const clippedLabels = await page.locator(".coach-provider-item strong:visible").evaluateAll((nodes) => nodes
      .filter((node) => node.scrollWidth > node.clientWidth || node.getBoundingClientRect().right > window.innerWidth + 1)
      .map((node) => node.textContent));
    expect(clippedLabels, "visible provider labels must fit their cards").toEqual([]);
    await expectNoBrowserErrorsOrOverflow(page, browserErrors);
  });

  test("coach streaming, tab changes, long markdown and scrolling stay stable", async ({ page }, testInfo) => {
    const browserErrors = installBrowserGuards(page);
    await openAuthenticatedApp(page);
    await page.getByRole("link", { name: "Coach", exact: true }).click();
    await installControlledChatStream(page);

    const input = page.locator("#messageInput");
    const touchProject = testInfo.project.name.startsWith("mobile");
    const initialViewport = page.viewportSize();
    if (touchProject) {
      expect(await page.evaluate(() => navigator.maxTouchPoints > 0 && matchMedia("(pointer: coarse)").matches)).toBe(true);
      await input.focus();
      await expect(page.locator("html")).not.toHaveClass(/chat-keyboard-open/);
      await page.setViewportSize({ width: initialViewport.width, height: Math.max(360, initialViewport.height - 180) });
      await expect(page.locator("html")).toHaveClass(/chat-keyboard-open/);
      await expect(page.locator(".bottom-nav")).toHaveCSS("visibility", "hidden");
      await expect.poll(() => page.evaluate(() => Math.abs(
        Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--app-viewport-height"))
          - (window.visualViewport?.height || window.innerHeight),
      ))).toBeLessThanOrEqual(1);
      const keyboardLayout = await page.locator("#chatForm").evaluate((composer) => ({
        composerBottom: composer.getBoundingClientRect().bottom,
        viewportBottom: (window.visualViewport?.offsetTop || 0) + (window.visualViewport?.height || window.innerHeight),
      }));
      expect(keyboardLayout.composerBottom).toBeLessThanOrEqual(keyboardLayout.viewportBottom + 1);
      await page.setViewportSize(initialViewport);
      await expect(page.locator("html")).not.toHaveClass(/chat-keyboard-open/);
    }
    await input.fill("Analysiere meine letzte Einheit gründlich.");
    await page.getByRole("button", { name: "Senden", exact: true }).click();
    if (touchProject) await expect(page.locator("html")).not.toHaveClass(/chat-keyboard-open/);
    await expect(page.locator("#coachWorking")).toContainText("Coach arbeitet");
    await expect(page.locator("#messages")).toHaveAttribute("aria-busy", "true");
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    if (!await input.isVisible()) {
      await page.locator("#chatJumpToComposer").click();
      await expect(input).toBeFocused();
    }
    await expect(input).toBeVisible();
    await input.fill("Dieser Entwurf bleibt beim Tabwechsel erhalten.");
    await page.getByRole("link", { name: "Heute", exact: true }).click();
    await expect(page.locator("#confirmationDialog")).toBeHidden();
    await expect(input).toHaveValue("Dieser Entwurf bleibt beim Tabwechsel erhalten.");
    await page.getByRole("link", { name: "Coach", exact: true }).click();

    await page.evaluate(() => window.__chatTest.push("delta", { text: "# Trainingsanalyse\n\n- Ruhiger Beginn" }));
    await expect(page.locator(".message.assistant.streaming")).toContainText("Ruhiger Beginn");
    await page.evaluate(() => { window.__chatTest.stableMessageNode = document.querySelector(".message.user"); });
    await page.evaluate(() => window.__chatTest.push("delta", { text: "\n- Stabiler Abschluss" }));
    await expect(page.locator(".message.assistant.streaming")).toContainText("Stabiler Abschluss");
    expect(await page.evaluate(() => window.__chatTest.stableMessageNode === document.querySelector(".message.user")), "persisted messages must not be rebuilt for every stream chunk").toBe(true);

    const busyOverflow = await page.locator("#chatForm").evaluate((composer) => ({
      composer: composer.scrollWidth > composer.clientWidth + 1,
      document: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    expect(busyOverflow, "busy composer must fit narrow viewports").toEqual({ composer: false, document: false });

    const longMarkdown = [
      "# Trainingsanalyse",
      "",
      "**Kurzfazit:** Die Belastung war kontrolliert.",
      "",
      "- Ruhiger Beginn",
      "- Stabiler Abschluss",
      "",
      "[Sichere Referenz](https://example.com/training)",
      "",
      "<script id=\"unsafe-coach-markdown\">window.__unsafeCoachMarkdown = true</script>",
      "",
      "```text",
      `LANGER_CODE_${"x".repeat(240)}`,
      "```",
      "",
      ...Array.from({ length: 12 }, (_, index) => `## Abschnitt ${index + 1}\n\n${"Ausführliche, gut lesbare Trainingsbegründung. ".repeat(5)}`),
    ].join("\n");
    await page.getByRole("link", { name: "Heute", exact: true }).click();
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const inactiveScrollY = await page.evaluate(() => window.scrollY);
    await page.evaluate((content) => {
      const message = { id: 2, role: "assistant", content, created_at: "2026-09-04T10:00:00Z" };
      window.__chatTest.historyMessages = [
        { id: 1, role: "user", client_turn_id: window.__chatTest.clientTurnId, content: "Analysiere meine letzte Einheit gründlich.", created_at: "2026-09-04T09:59:00Z" },
        message,
      ];
      window.__chatTest.push("delta", { text: `\n\n${content}` });
      window.__chatTest.push("completed", { message, proposed_actions: [], command_receipts: [] });
      window.__chatTest.finish();
    }, longMarkdown);
    await expect.poll(() => page.evaluate(() => state.chatRequest?.phase)).toBe("reconciling");
    await expect(page.locator('[data-message-id="2"]')).toContainText("Abschnitt 12");
    await expect(page.locator("#unsafe-coach-markdown")).toHaveCount(0);
    expect(await page.evaluate(() => window.__unsafeCoachMarkdown)).toBeUndefined();
    expect(await page.evaluate(() => window.scrollY), "background chat updates must not scroll another tab").toBe(inactiveScrollY);

    await expect.poll(() => page.evaluate(() => window.__chatTest.historyResolvers.length)).toBe(1);
    await page.evaluate(() => window.__chatTest.releaseHistory());
    await expect.poll(() => page.evaluate(() => state.chatRequest)).toBe(null);
    await expect(page.locator("#todayPanel")).toHaveClass(/active/);
    expect(await page.evaluate(() => document.activeElement?.id)).not.toBe("messageInput");

    await page.getByRole("link", { name: "Coach", exact: true }).click();
    await expect(page.locator('[data-message-id="2"]')).toBeVisible();
    await expect.poll(() => page.locator('[data-message-id="2"]').evaluate((node) => Math.round(node.getBoundingClientRect().top))).toBe(16);
    await expect(page.locator("#chatJumpToComposer")).toBeVisible();
    if (touchProject) {
      await page.setViewportSize({ width: 568, height: 320 });
      await expect(page.locator("#chatJumpToComposer")).toBeVisible();
      const landscapeJump = await page.locator("#chatJumpToComposer").boundingBox();
      expect(landscapeJump.y).toBeGreaterThanOrEqual(0);
      expect(landscapeJump.y + landscapeJump.height).toBeLessThanOrEqual(320);
      await page.setViewportSize(initialViewport);
    }
    const jumpBounds = await page.locator("#chatJumpToComposer").boundingBox();
    expect(jumpBounds.y + jumpBounds.height).toBeLessThanOrEqual((await page.viewportSize()).height);
    await page.locator("#chatJumpToComposer").click();
    await expect(input).toBeFocused();
    await expect(page.locator("#chatForm")).toBeVisible();
    await expect(input).toHaveValue("Dieser Entwurf bleibt beim Tabwechsel erhalten.");

    await input.fill("Teste eine unterbrochene Antwort.");
    await page.getByRole("button", { name: "Senden", exact: true }).click();
    await expect(page.locator("#coachWorking")).toBeVisible();
    await page.evaluate(() => window.__chatTest.push("delta", { text: "Diese Teilantwort bleibt sichtbar." }));
    await expect(page.locator(".message.assistant.streaming")).toContainText("Teilantwort bleibt sichtbar");
    await page.evaluate(() => {
      window.__chatTest.historyMessages = [
        ...window.__chatTest.historyMessages,
        { id: 3, role: "user", client_turn_id: window.__chatTest.clientTurnId, content: "Teste eine unterbrochene Antwort.", created_at: "2026-09-04T10:01:00Z" },
        { id: 4, role: "assistant", content: "Kurze Antwort nach erfolgreicher Wiederherstellung.", created_at: "2026-09-04T10:01:01Z" },
      ];
      window.__chatTest.finish();
    });
    await expect.poll(() => page.evaluate(() => state.chatRequest?.phase)).toBe("recovering");
    await expect(page.locator(".message.assistant.streaming")).toContainText("Teilantwort bleibt sichtbar");
    await expect(page.locator("#coachWorking")).toContainText("Verbindung unterbrochen");
    await expect(page.locator("#chatForm")).toHaveClass(/is-recovering/);
    await expect(page.locator("#sendButton")).toHaveText("Coach antwortet…");
    await expect(page.locator("#sendButton")).toBeDisabled();
    await expect.poll(() => page.evaluate(() => window.__chatTest.historyResolvers.length)).toBe(1);
    await page.evaluate(() => window.__chatTest.releaseHistory());
    await expect.poll(() => page.evaluate(() => state.chatRequest)).toBe(null);
    await expect(page.locator('[data-message-id="4"]')).toContainText("Kurze Antwort");
    await expect(page.locator(".message.assistant.streaming")).toHaveCount(0);
    await expect(page.locator("#messages")).toHaveAttribute("aria-busy", "false");
    if (touchProject) expect(await page.evaluate(() => document.activeElement?.id)).not.toBe("messageInput");

    await expectNoBrowserErrorsOrOverflow(page, browserErrors);
  });

});

test("authorized HTTP plan commit preserves sport through SQLCipher and calendar rendering", async ({ page }) => {
  await openAuthenticatedApp(page);
  const result = await page.evaluate(async () => {
    const staged = await api("/api/fixture/plan");
    const body = { client_turn_id: "fixture-http-commit", operation: "commit_training_plan", artifact_id: staged.artifact_id, arguments: {} };
    const first = await api("/api/planning/commands", { method: "POST", body: JSON.stringify(body) });
    const repeated = await api("/api/planning/commands", { method: "POST", body: JSON.stringify(body) });
    const plan = await api("/api/plan?local=1");
    return { first: first.status, repeated: repeated.status, entries: plan.training_calendar.filter((entry) => entry.name?.startsWith("HTTP fixture ")).map(({ name, type }) => ({ name, type })) };
  });
  expect(result.first).toBe("completed");
  expect(result.repeated).toBe("completed");
  expect(result.entries).toHaveLength(4);
  for (const sport of ["Run", "WeightTraining", "VirtualRide", "Swim"]) expect(result.entries).toContainEqual({ name: `HTTP fixture ${sport}`, type: sport });
  await page.goto("/#plan/overview");
  for (const [sport, label] of [["Run", "Laufen"], ["WeightTraining", "Kraft"], ["VirtualRide", "Rad indoor"], ["Swim", "Schwimmen"]]) {
    await expect(page.locator(".planned-entry").filter({ hasText: `HTTP fixture ${sport}` }).locator(".planned-meta")).toContainText(label);
  }
});
