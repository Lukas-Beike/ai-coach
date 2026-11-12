const { test, expect } = require("@playwright/test");
const { captureReadFixture, installReadFixture } = require("./read-fixture");
const { contrastRatio, showCalendarDay } = require("./helpers/ui");

let fixture;
test.beforeAll(async ({ request }) => { fixture = await captureReadFixture(request); });
test.beforeEach(async ({ page }) => { await installReadFixture(page, fixture); });

async function ready(page) {
  // These UI contracts don't exercise the SSE transport; abort it before the
  // app starts so closed browser contexts don't hold fixture server slots.
  await page.route("**/api/state/events*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  await expect.poll(() => page.evaluate(() => !state.chatProposalRefreshInFlight)).toBe(true);
  await page.evaluate(() => {
    if (state.stateEventSource) {
      state.stateEventSource.onmessage = null;
      state.stateEventSource.onerror = null;
      state.stateEventSource.close();
      state.stateEventSource = null;
    }
    clearTimeout(state.chatStatusTimer);
    state.data.messages = [];
    renderMessages([]);
  });
  await expect.poll(() => page.evaluate(() => state.chatStatusPollInFlight === null)).toBe(true);
  await page.evaluate(async () => {
    await state.loadPromise?.catch(() => {});
    state.pendingLoads.clear();
  });
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
}

async function controlled(page) {
  await page.evaluate(() => {
    const original = fetch.bind(window);
    const fixture = { histories: [], historyCallStacks: [], planCalls: 0, libraryCalls: 0, streamCalls: 0, proposedActions: null };
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    fixture.push = (event, payload) => fixture.controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`));
    window.__contract = fixture;
    // The caller assertions need frames beyond V8's default ten-frame stack.
    Error.stackTraceLimit = 50;
    window.fetch = (path, options) => {
      if (path === "/api/chat/stream") {
        fixture.streamCalls++;
        fixture.turn = JSON.parse(options.body).client_turn_id;
        return Promise.resolve(new Response(new ReadableStream({ start(controller) {
          fixture.controller = controller;
          fixture.push("started", { operation_id: "fixture-operation" });
        } }), { status: 200 }));
      }
      if (path.startsWith("/api/chat/history")) {
        fixture.historyCallStacks.push(new Error().stack);
        return new Promise((resolve) => fixture.histories.push((messages) => resolve(json({ messages, generation: state.data.messages_generation, next_cursor: null, ...(fixture.proposedActions ? { proposed_actions: fixture.proposedActions } : {}) }))));
      }
      if (path.startsWith("/api/plan")) fixture.planCalls++;
      if (path.startsWith("/api/library")) fixture.libraryCalls++;
      return original(path, options);
    };
  });
}

test("Markdown links preserve URLs and format labels without interpreting markup", async ({ page }) => {
  await ready(page);
  const urls = [
    "https://example.invalid/a_b_c",
    "https://example.invalid/a__b__c?first=a*b*c&second=__value__",
    "https://example.invalid/code_path",
  ];
  await page.evaluate((urls) => renderMessages([{
    id: 900001,
    role: "assistant",
    content: `[**Strong label**](${urls[0]}) [_Emphasis label_](${urls[1]}) [\`Code label\`](${urls[2]})\n\n<script id="markdown-injection">window.markdownInjection = true</script>\n\n[Unsafe](javascript:alert(1))`,
  }]), urls);
  const message = page.locator('[data-message-id="900001"]');
  for (const [index, label] of ["Strong label", "Emphasis label", "Code label"].entries()) {
    const link = message.getByRole("link", { name: label, exact: true });
    await expect(link).toHaveAttribute("href", urls[index]);
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAttribute("target", "_blank");
  }
  await expect(message.locator("a strong")).toHaveText("Strong label");
  await expect(message.locator("a em")).toHaveText("Emphasis label");
  await expect(message.locator("a code")).toHaveText("Code label");
  await expect(message.getByRole("link")).toHaveCount(3);
  await expect(page.locator("#markdown-injection")).toHaveCount(0);
  expect(await page.evaluate(() => window.markdownInjection)).toBeUndefined();
});

test("@responsive Coach links are underlined, keep their contrast in both themes and show a differing host", async ({ page }) => {
  await ready(page);
  await page.evaluate(() => renderMessages([{
    id: 900002,
    role: "assistant",
    content: "Siehe [die Quelle](https://www.example.invalid/a) oder [example.invalid/b](https://example.invalid/b) für Details.",
  }]));
  const message = page.locator('[data-message-id="900002"]');
  const link = message.getByRole("link", { name: "die Quelle", exact: true });
  await expect(message.locator(".link-host")).toHaveCount(1);
  await expect(message.locator(".link-host")).toHaveText("(example.invalid)");
  await expect(message.getByRole("link", { name: "example.invalid/b", exact: true })).toBeVisible();
  for (const theme of ["dark", "light"]) {
    await page.evaluate((selected) => { document.documentElement.dataset.theme = selected; }, theme);
    const colors = await link.evaluate((anchor) => {
      const paragraph = anchor.closest("p");
      return {
        decoration: getComputedStyle(anchor).textDecorationLine,
        link: getComputedStyle(anchor).color,
        text: getComputedStyle(paragraph).color,
        host: getComputedStyle(paragraph.querySelector(".link-host")).color,
        background: getComputedStyle(document.body).backgroundColor,
      };
    });
    expect(colors.decoration, theme).toContain("underline");
    expect(contrastRatio(colors.link, colors.text), `${theme} link against text`).toBeGreaterThanOrEqual(3);
    expect(contrastRatio(colors.link, colors.background), `${theme} link against background`).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(colors.host, colors.background), `${theme} host against background`).toBeGreaterThanOrEqual(4.5);
  }
});

test("appearance choice updates the theme and survives reload on this device", { tag: "@responsive" }, async ({ page }) => {
  await ready(page);
  await page.getByRole("link", { name: "Mehr", exact: true }).click();
  await page.locator("#settingsPanel").getByRole("link", { name: "Darstellung", exact: true }).click();
  await page.locator("#appearanceSelect").selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect.poll(() => page.locator('meta[name="theme-color"]').getAttribute("content")).toBe("#ffffff");
  await page.reload();
  await expect(page.locator("#appearanceSelect")).toHaveValue("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("a prior user message can be copied or edited as a regular draft", { tag: "@responsive" }, async ({ page }) => {
  await ready(page);
  await page.evaluate(() => {
    state.data.messages = [{ id: 9001, role: "user", content: "Review this interval session", attachment_names: "[]" }];
    renderMessages(state.data.messages);
    $("#messageInput").dataset.requestKind = "morning";
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text) => { window.__copiedMessage = text; } },
    });
  });
  await page.getByRole("button", { name: "Nachricht kopieren" }).click();
  await expect.poll(() => page.evaluate(() => window.__copiedMessage)).toBe("Review this interval session");
  await page.getByRole("button", { name: "Als Entwurf bearbeiten" }).click();
  await expect(page.locator("#messageInput")).toHaveValue("Review this interval session");
  expect(await page.locator("#messageInput").evaluate((input) => input.dataset.requestKind || null)).toBe(null);
  await page.locator("#messageInput").fill("Current unsent draft");
  await page.evaluate(() => {
    state.chatAttachments = [{ name: "current.gpx", data: "fixture" }];
    renderChatAttachments();
  });
  await page.getByRole("button", { name: "Als Entwurf bearbeiten" }).click();
  await expect(page.locator("#messageInput")).toHaveValue("Current unsent draft");
  await expect(page.locator("#chatAttachments")).toContainText("current.gpx");
});

test("light mode keeps performance source badges readable", { tag: "@responsive" }, async ({ page }) => {
  await ready(page);
  await page.evaluate(() => {
    document.documentElement.dataset.theme = "light";
    state.data.performance = { available: true, metrics: {
      weight_kg: { value: 70, unit: "kg", source: "Manuell" },
      cycling_ftp_watts: { value: 250, unit: "W", source: "Garmin Connect" },
    } };
    renderPerformance(state.data.performance);
  });
  await expect(page.locator("#performanceSummary")).toBeHidden();
});

test("chat reset detaches a delayed status poll without releasing its successor", async ({ page }) => {
  await ready(page);
  await expect(page.locator("#coachChatResetButton")).toHaveCount(1);
  await expect(page.locator("#chatResetButton, #aiProviderSelect")).toHaveCount(0);
  await page.evaluate(() => {
    const original = fetch.bind(window);
    window.__statusCalls = [];
    window.fetch = (path, options) => {
      if (path === "/api/chat/status") return new Promise((resolve) => __statusCalls.push((status) => resolve(new Response(JSON.stringify(status), { headers: { "Content-Type": "application/json" } }))));
      if (path === "/api/chat/reset") return Promise.resolve(new Response(JSON.stringify({ status: 'ok', generation: state.data.messages_generation }), { headers: { "Content-Type": "application/json" } }));
      return original(path, options);
    };
    requestConfirmation = async () => true;
    window.__oldPoll = pollChatStatus();
  });
  await expect.poll(() => page.evaluate(() => __statusCalls.length)).toBe(1);
  await page.evaluate(() => resetCoachChat());
  await expect.poll(() => page.evaluate(() => __statusCalls.length)).toBe(2);
  await page.evaluate(async () => {
    window.__newPoll = state.chatStatusPollInFlight;
    __statusCalls[0]({ status: "running", operation_id: "obsolete-operation" });
    await __oldPoll;
  });
  expect(await page.evaluate(() => state.chatStatusPollInFlight === __newPoll)).toBe(true);
  expect(await page.evaluate(() => state.chatServerOperationId)).toBe(null);
  await page.evaluate(() => __statusCalls[1]({ status: "idle" }));
  await expect.poll(() => page.evaluate(() => state.chatStatusPollInFlight)).toBe(null);
  await page.evaluate(() => { clearTimeout(state.chatStatusTimer); void pollChatStatus(); });
  await expect.poll(() => page.evaluate(() => __statusCalls.length)).toBe(3);
  await page.evaluate(() => __statusCalls[2]({ status: "running", operation_id: "current-operation" }));
  await expect.poll(() => page.evaluate(() => state.chatServerOperationId)).toBe("current-operation");
});

for (const provider of ["openai", "anthropic"]) {
  test(`chat reset sits with the Coach model and resets with ${provider} selected @responsive`, async ({ page }) => {
    await ready(page);
    const resets = [];
    await page.route("**/api/chat/reset", async (route) => {
      const request = route.request();
      resets.push({ body: request.postDataJSON(), csrf: request.headers()["x-csrf-token"] });
      await route.fulfill({ json: { status: "ok", generation: "fixture-generation" } });
    });
    await page.evaluate((selected) => renderModel({
      provider: selected,
      selected: `${selected}-fixture`,
      options: [
        { id: "openai-fixture", provider: "openai", label: "OpenAI Fixture", model: "openai-fixture" },
        { id: "anthropic-fixture", provider: "anthropic", label: "Claude Fixture", model: "anthropic-fixture" },
      ],
    }), provider);
    await page.goto("/#more/coach");
    const section = page.locator("details", { has: page.locator("#modelSelect") });
    await section.locator("summary").click();
    await expect(page.locator("#modelSelect")).toHaveValue(`${provider}-fixture`);
    // Claude hides the OpenAI-only speed row; the reset stays.
    await expect(page.locator("#serviceTierRow")).toHaveJSProperty("hidden", provider === "anthropic");
    const button = section.getByRole("button", { name: "Chat zurücksetzen", exact: true });
    await expect(button).toBeVisible();
    await expect(page.locator("#connection-openai").getByRole("button", { name: "Chat zurücksetzen" })).toHaveCount(0);
    await button.click();
    await expect(page.locator("#confirmationDialog")).toBeVisible();
    await page.locator("#confirmationDialogAccept").click();
    await expect.poll(() => resets.length).toBe(1);
    expect(resets[0].body).toEqual({ confirmed: true });
    expect(resets[0].csrf).toBeTruthy();
    await expect(button).toHaveText("Chat zurücksetzen");
    await expect(button).toBeEnabled();
  });
}

test("history barriers preserve optimistic and completed messages through navigation", async ({ page }) => {
  await ready(page);
  await controlled(page);
  await page.evaluate(() => { void load("/api/bootstrap?local=1", ["chat"]); });
  await expect.poll(() => page.evaluate(() => __contract.histories.length)).toBe(1);
  const caller = await page.evaluate(() => __contract.historyCallStacks[0]);
  expect(caller).toContain("loadStateRequests");
  await page.locator("#messageInput").fill("Fixture Run plan");
  await page.locator("#sendButton").click();
  await page.evaluate(() => __contract.histories.shift()([]));
  await expect(page.locator(".message.user")).toContainText("Fixture Run plan");
  await page.evaluate(() => { void load("/api/bootstrap?local=1", ["chat"]); });
  await expect.poll(() => page.evaluate(() => __contract.histories.length)).toBe(1);
  await page.getByRole("link", { name: "Kalender", exact: true }).click();
  await page.evaluate(() => {
    __contract.push("completed", { message: { id: 102, content: "Run plan saved", client_turn_id: __contract.turn }, proposed_actions: [], command_receipts: [] });
    __contract.controller.close();
    __contract.histories.shift()([]);
  });
  // The calendar and library already loaded with the start.
  await expect.poll(() => page.evaluate(() => state.loadedAreas.has("plan") && state.loadedAreas.has("library"))).toBe(true);
  await page.getByRole("link", { name: "Coach", exact: true }).click();
  await expect(page.locator(".message.user")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toContainText("Run plan saved");
});

test("a completed answer accepts an immediate follow-up without showing a queue", async ({ page }) => {
  await ready(page);
  await controlled(page);
  await page.locator("#messageInput").fill("First question");
  await page.locator("#sendButton").click();
  await page.evaluate(() => {
    __contract.push("completed", { message: { id: 201, content: "First answer", client_turn_id: __contract.turn }, proposed_actions: [], command_receipts: [] });
  });
  await expect(page.locator(".message.assistant")).toContainText("First answer");
  await expect.poll(() => page.evaluate(() => state.chatRequest)).toBe(null);

  await page.locator("#messageInput").fill("Immediate follow-up");
  await page.locator("#messageInput").press("Enter");

  await expect.poll(() => page.evaluate(() => __contract.streamCalls)).toBe(2);
  await expect(page.locator(".message.pending")).toHaveCount(0);
  await expect(page.locator("#chatQueueStatus")).toBeHidden();
});

test("completed answers refresh outstanding action proposals asynchronously", async ({ page }) => {
  await ready(page);
  await controlled(page);
  await page.evaluate(() => {
    state.coachActionProposals = [{ id: "active-proposal", action_type: "undo_change", status: "preview", diff: [] }];
    renderCoachActionReview();
    __contract.proposedActions = [{ id: "active-proposal", action_type: "undo_change", status: "preview", diff: [] }];
  });
  await page.locator("#messageInput").fill("Question with completed answer");
  await page.locator("#sendButton").click();
  await page.evaluate(() => {
    __contract.push("completed", { message: { id: 202, content: "Answer", client_turn_id: __contract.turn }, proposed_actions: [], command_receipts: [] });
    __contract.controller.close();
  });
  await expect.poll(() => page.evaluate(() => state.chatRequest)).toBe(null);
  await expect.poll(() => page.evaluate(() => __contract.histories.length)).toBe(1);
  const caller = await page.evaluate(() => __contract.historyCallStacks[0]);
  expect(caller).toContain("refreshChatProposalsInBackground");
  await page.evaluate(() => __contract.histories.shift()([]));
  await expect.poll(() => page.evaluate(() => ({
    ids: state.coachActionProposals.map((proposal) => proposal.id),
    contentVersion: state.chatContentVersion,
    loadSequence: state.loadSequence,
    caller: __contract.historyCallStacks[0],
  })), { timeout: 5_000 }).toEqual({
    ids: ["active-proposal"],
    contentVersion: 1,
    loadSequence: await page.evaluate(() => state.loadSequence),
    caller,
  });
});

test("every definite HTTP rejection retains the draft and concrete error", async ({ page }) => {
  await ready(page);
  for (const status of [400, 403, 404, 409, 413, 422, 429, 500, 502, 503, 504]) {
    await page.route("**/api/chat/stream", (route) => route.fulfill({ status, headers: status === 429 ? { "Retry-After": "19" } : {}, json: { error: `Fixture rejection ${status}`, reason: "fixture_rejection" } }));
    await page.locator("#messageInput").fill(`Fixture draft ${status}`);
    await page.locator("#sendButton").click();
    await expect(page.locator("#messageInput")).toHaveValue(`Fixture draft ${status}`);
    await expect(page.locator("#toast")).toContainText(`Fixture rejection ${status}`);
    if (status === 429) await expect(page.locator("#toast")).toContainText("19 Sekunden");
    await expect.poll(() => page.evaluate(() => state.chatRequest)).toBe(null);
    await page.unroute("**/api/chat/stream");
  }
});

test("rejection preserves a newer draft separately from the rejected message", async ({ page }) => {
  await ready(page);
  let reject;
  await page.route("**/api/chat/stream", (route) => new Promise((resolve) => {
    reject = async () => { await route.fulfill({ status: 422, json: { error: "Fixture invalid request" } }); resolve(); };
  }));
  await page.locator("#messageInput").fill("Rejected original");
  await page.locator("#sendButton").click();
  await page.evaluate(() => jumpToLatestMessages());
  await page.locator("#messageInput").fill("New independent draft");
  await reject();
  await expect(page.locator("#messageInput")).toHaveValue("New independent draft");
  await expect(page.locator(".message.user")).toContainText("Rejected original");
  await expect(page.locator(".message-error")).toHaveText("Fixture invalid request");
});

test("a delayed old-session 401 cannot log out the new session", async ({ page }) => {
  await ready(page);
  await page.evaluate(() => {
    const original = fetch.bind(window);
    window.fetch = (path, options) => path === "/api/chat/stream"
      ? new Promise((resolve) => { window.__releaseOld = () => resolve(new Response('{"error":"old session"}', { status: 401 })); })
      : original(path, options);
    void requestCoachResponse("Previous session request");
  });
  await page.evaluate(() => {
    const data = state.data;
    showLogin();
    document.querySelector("#loginDialog").close();
    document.querySelector("#appShell").hidden = false;
    state.data = { ...data, messages: [] };
    document.querySelector("#messageInput").value = "New session draft";
    window.__releaseOld();
  });
  await expect(page.locator("#loginDialog")).toBeHidden();
  await expect(page.locator("#messageInput")).toHaveValue("New session draft");
  await expect.poll(() => page.evaluate(() => state.chatRequest)).toBe(null);
});

test("new session loads are independent of a delayed previous session load", async ({ page }) => {
  await ready(page);
  await controlled(page);
  await page.evaluate(() => { void load("/api/bootstrap?local=1", ["chat"]); });
  await expect.poll(() => page.evaluate(() => __contract.histories.length)).toBe(1);
  await page.evaluate(() => {
    const data = state.data;
    showLogin();
    document.querySelector("#loginDialog").close();
    document.querySelector("#appShell").hidden = false;
    state.data = { ...data, messages: [] };
    void load("/api/bootstrap?local=1", ["plan", "library"]);
  });
  await expect.poll(() => page.evaluate(() => __contract.planCalls)).toBe(1);
  await expect.poll(() => page.evaluate(() => state.loadedAreas.has("plan"))).toBe(true);
  await page.evaluate(() => __contract.histories.shift()([{ id: 99, role: "assistant", content: "Previous session data" }]));
  await expect(page.locator("#messages")).not.toContainText("Previous session data");
});

test("profile invalid JSON and incomplete success preserve the dirty draft", async ({ page }) => {
  await ready(page);
  await page.goto("/#more/profile");
  // Every profile section starts closed (#2262).
  await page.locator("#profileForm > details.profile-section").first().locator(":scope > summary").click();
  for (const body of ["{", "<html>proxy error</html>", "{}"] ) {
    await page.route("**/api/profile", (route) => route.request().method() === "PUT"
      ? route.fulfill({ status: 200, contentType: "application/json", body }) : route.continue());
    await page.getByLabel("Name", { exact: true }).fill("Unsaved fixture athlete");
    await page.getByRole("button", { name: "Athletenkontext speichern", exact: true }).click();
    await expect(page.locator("#profileDirtyIndicator")).toBeVisible();
    await expect(page.getByLabel("Name", { exact: true })).toHaveValue("Unsaved fixture athlete");
    await expect(page.locator("#toast")).not.toContainText("Athletenprofil gespeichert");
    await page.unroute("**/api/profile");
  }
});

test("reload recovers a partial write receipt and executable undo proposal", async ({ page }) => {
  await ready(page);
  // Store the turn only for the reloaded page: the unloading page would otherwise
  // recover the receipt itself and clear the turn before the reload starts.
  await page.addInitScript(() => sessionStorage.setItem("coachPendingTurn", "fixture-persisted-turn"));
  await page.route("**/api/chat/receipt?*", (route) => route.fulfill({ json: {
    client_turn_id: "fixture-persisted-turn", status: "partial",
    message: { id: 501, client_turn_id: "fixture-persisted-turn", content: "Check-in saved; summary unavailable." },
    command_receipts: [{ tool: "save_checkin", result: { ok: true, status: "saved" } }],
    proposed_actions: [{ id: "fixture-undo", action_type: "undo_change", status: "preview", target_system: "local", diff: [] }],
  } }));
  await page.reload();
  await expect(page.locator(".message.assistant").filter({ hasText: "Check-in saved; summary unavailable." })).toBeVisible();
  await expect(page.locator("#toast")).toContainText("Tages-Check-in gespeichert");
  await expect(page.getByRole("button", { name: "Änderung zurücknehmen", exact: true })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("coachPendingTurn"))).toBe(null);
});

test("progress and cancel remain reachable while the composer is hidden", { tag: "@responsive" }, async ({ page }) => {
  await ready(page);
  await controlled(page);
  await page.locator("#messageInput").fill("Long fixture task");
  await page.locator("#sendButton").click();
  await page.evaluate(() => {
    __contract.push("delta", { text: "Long fixture analysis\n\n".repeat(100) });
    document.querySelector("#messageInput").blur();
    window.scrollTo(0, 0);
    updateChatComposerVisibility();
  });
  await expect(page.locator("#chatOperationStatus")).toBeVisible();
  await expect(page.locator("#cancelChatButton")).toBeVisible();
  await expect(page.locator("#cancelChatButton")).toBeEnabled();
});

test("voice input records a follow-up while the Coach is working", async ({ page }) => {
  await ready(page);
  await controlled(page);
  await page.evaluate(() => {
    const original = fetch;
    window.fetch = (path, options) => path === "/api/transcribe"
      ? Promise.resolve(new Response('{"transcript":"Gesprochene Folgefrage"}', { status: 200, headers: { "Content-Type": "application/json" } }))
      : original(path, options);
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } });
    window.MediaRecorder = class extends EventTarget {
      state = "inactive";
      mimeType = "audio/webm";
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        const chunk = new Event("dataavailable");
        chunk.data = new Blob(["synthetic audio"]);
        this.dispatchEvent(chunk);
        this.dispatchEvent(new Event("stop"));
      }
    };
  });
  await page.locator("#messageInput").fill("Long fixture task");
  await page.locator("#sendButton").click();
  await expect(page.locator("#cancelChatButton")).toBeVisible();
  const voice = page.locator("#voiceButton");
  await expect(voice).toBeEnabled();
  await voice.click();
  await expect(voice).toHaveAttribute("aria-pressed", "true");
  await voice.click();
  await expect(page.locator("#messageInput")).toHaveValue("Gesprochene Folgefrage");
  await expect(page.locator("#sendButton")).toHaveAttribute("aria-label", "Einreihen");
  await expect(page.locator("#sendButton")).toBeEnabled();
});

test("delayed receipt and transcription cannot alter a new session", async ({ page }) => {
  await ready(page);
  await page.evaluate(() => {
    const original = fetch.bind(window);
    window.fetch = (path, options) => {
      if (path.startsWith("/api/chat/receipt")) return new Promise((resolve) => {
        window.__oldReceipt = () => resolve(new Response('{"error":"previous session"}', { status: 403 }));
      });
      if (path === "/api/transcribe") return new Promise((resolve) => {
        window.__oldAudio = () => resolve(new Response('{"transcript":"Previous session transcript"}', { status: 200 }));
      });
      return original(path, options);
    };
    rememberChatTurn("previous-turn");
    void pollChatStatus();
    void transcribeVoice(new Blob(["synthetic audio"]));
  });
  await expect.poll(() => page.evaluate(() => Boolean(window.__oldReceipt && window.__oldAudio))).toBe(true);
  await page.evaluate(() => {
    const data = state.data;
    showLogin();
    document.querySelector("#loginDialog").close();
    document.querySelector("#appShell").hidden = false;
    state.data = data;
    document.querySelector("#messageInput").value = "New session draft";
    rememberChatTurn("new-turn");
    window.__oldReceipt();
    window.__oldAudio();
  });
  await expect(page.locator("#messageInput")).toHaveValue("New session draft");
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem("coachPendingTurn"))).toBe("new-turn");
});

test("fresh service worker keeps the current shell available offline", async ({ page }) => {
  await ready(page);
  await page.evaluate(() => navigator.serviceWorker.ready);
  // The cache name is stamped by the server, so the served worker names it.
  const worker = await (await page.request.get("/service-worker.js")).text();
  const cacheName = worker.match(/const CACHE = "(pacecraft-[0-9a-f]{10})";/)[1];
  expect(await page.evaluate(() => caches.keys())).toEqual([cacheName]);
  // Every stamped asset reference of the shell is in the fresh cache.
  expect(await page.evaluate(async (name) => {
    const cached = new Set((await (await caches.open(name)).keys()).map((request) => new URL(request.url).pathname + new URL(request.url).search));
    const refs = [...document.querySelectorAll("script[src], link[rel~=stylesheet][href], link[rel~=icon][href], link[rel=apple-touch-icon][href]")]
      .map((element) => new URL(element.src || element.href).pathname + new URL(element.src || element.href).search);
    return { refs: refs.length, missing: refs.filter((ref) => !cached.has(ref)) };
  }, cacheName)).toEqual({ refs: expect.any(Number), missing: [] });
  await expect.poll(() => page.evaluate(() => Boolean(localStorage.getItem("coach-state-snapshot")))).toBe(true);
  await page.context().setOffline(true);
  try {
    // The device snapshot starts the cached shell without the server.
    await page.reload();
    await expect(page.locator("#appShell")).toBeVisible();
    await expect(page.locator("#loginDialog")).not.toBeVisible();
    // Without stored data the offline start offers the login instead.
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await expect(page.locator("#loginDialog")).toBeVisible();
    await expect(page.locator("#loginPassword")).toBeEditable();
    expect(await page.evaluate(async () => {
      const names = await caches.keys();
      const cacheName = names.find((name) => /^pacecraft-[0-9a-f]{10}$/.test(name));
      const cache = await caches.open(cacheName);
      return (await cache.keys()).some((request) => new URL(request.url).pathname.startsWith("/api/"));
    })).toBe(false);
  } finally { await page.context().setOffline(false); }
});

test("plan overview deep link focuses and reveals today after loading", { tag: "@responsive" }, async ({ page }) => {
  await page.goto("/#plan/overview");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null && state.loadedAreas.has("plan"))).toBe(true);
  const today = page.locator(".planned-day.is-today");
  await expect(today).toHaveCount(1);
  await expect(today).toBeInViewport();
  const position = await today.evaluate((element) => ({
    top: element.getBoundingClientRect().top,
    viewportHeight: window.innerHeight,
    atBottom: window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 1,
  }));
  expect(position.top).toBeGreaterThanOrEqual(0);
  // One week is shown, so a late weekday sits lower only when the page cannot scroll further.
  expect(position.top < position.viewportHeight / 2 || position.atBottom).toBe(true);
});

test("current plan payload displays each requested sport exactly", async ({ page }) => {
  await ready(page);
  await page.getByRole("link", { name: "Kalender", exact: true }).click();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
  await page.evaluate(() => {
    const today = localDateKey(new Date());
    const entries = ["Run", "WeightTraining", "VirtualRide", "Swim"].map((sport, index) => ({
      id: `fixture-sport-${index}`, name: `Fixture ${sport}`, type: sport, sport,
      date: today, duration_minutes: 30, sync_status: "local",
    }));
    state.data.training_calendar = entries;
    renderPlanned(entries);
  });
  for (const [sport, label] of [["Run", "Laufen"], ["WeightTraining", "Kraft"], ["VirtualRide", "Rad indoor"], ["Swim", "Schwimmen"]]) {
    await expect(page.locator(".planned-entry").filter({ hasText: `Fixture ${sport}` }).locator(".planned-meta")).toContainText(label);
  }
});

test("planned agenda prioritizes dates and sessions with compact weather and expandable details", { tag: "@responsive" }, async ({ page }, testInfo) => {
  await ready(page);
  await page.getByRole("link", { name: "Kalender", exact: true }).click();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
  const today = await page.evaluate(() => {
    const date = timezoneDateKey(state.data?.profile?.timezone, new Date());
    state.data.calendar_display = { past_weeks: 1, future_weeks: 1 };
    state.data.daily_planning_context = [{ date,
      weather: { weather_code: 2, condition: "Leicht bewölkt", temperature_min: 12, temperature_max: 21, precipitation_probability_max: 0, wind_speed_max: 14, wind_gusts_max: 25, wind_direction_dominant: 225, forecast_location: "Emsdetten",
        air_quality: { european_aqi_max: 64, european_aqi_category: "schlecht", uv_index_max: 5.2 },
        pollen: { source: "DWD", region: "Westfälische Tieflandsbucht", levels: { Birke: "1-2" } } },
      appointments: [{ name: "Zeit für Training ab 18 Uhr", all_day: true }],
      checkin: { pain: "Leichte Beschwerden im Knie", day_form: "Gut erholt", soreness: 0, stress: 2, motivation: 8, available_minutes: 60, notes: "<img src=x onerror=alert(1)>" },
      recovery: { sleep_hours: 8, hrv: 54, resting_hr: 48, readiness: 80, body_battery: 85, sources: { sleep_hours: "Garmin Connect", hrv: "Intervals.icu Wellness" } },
    }, { date: addDateKey(date, -1),
      weather: { weather_code: 63, temperature_min: 10, temperature_max: 17, archived_forecast: true, forecast_location: "Emsdetten", precipitation_probability_max: 75, rain_peak_time: "14:00", wind_speed_max: 21.1 },
      recovery: { sleep_hours: 6.5, hrv: 42, resting_hr: 53 },
      checkin: { stress: 5, illness: "Magen-Darm" },
    }];
    state.data.training_calendar = [
      { id: "agenda-run", date, starts_at_local: `${date}T18:30:00`, name: "Lockerer Dauerlauf mit Steigerungen", type: "Run", duration_minutes: 45, description: "Locker laufen. <img src=x onerror=alert(1)>" },
      { id: "agenda-strength", date, name: "Mobilität und Rumpfstabilität", type: "WeightTraining", duration_minutes: 20 },
      { id: "agenda-completed", date: addDateKey(date, 1), started_at_local: `${addDateKey(date, 1)}T07:15:00`, name: "Grundlagenausfahrt", type: "Ride", is_completed_activity: true, moving_duration_s: 3600, distance_m: 28000, training_load: 42, rpe: 3 },
      { id: "agenda-completed-run", date: addDateKey(date, 1), name: "Absolvierte Laufeinheit", type: "Run", is_completed_activity: true, moving_duration_s: 2700, distance_m: 7000 },
      { id: "agenda-completed-swim", date: addDateKey(date, 1), name: "Absolvierte Schwimmeinheit", type: "Swim", is_completed_activity: true, moving_duration_s: 1800, distance_m: 1500 },
      { id: "agenda-completed-strength", date: addDateKey(date, 1), name: "Absolvierte Krafteinheit", type: "WeightTraining", is_completed_activity: true, moving_duration_s: 1800 },
      { id: "agenda-completed-other", date: addDateKey(date, 1), name: "Absolvierte sonstige Einheit", type: "Hike", is_completed_activity: true, moving_duration_s: 1800 },
      // Keeps a plan in the week of date + 1 on Sundays too, so extra activities there still show "Zusätzlich".
      { id: "agenda-next-plan", date: addDateKey(date, 1), name: "Geplante Folgeeinheit", type: "Run", duration_minutes: 30 },
      { id: "agenda-matched", date: addDateKey(date, -2), name: "Aktivierung", type: "Ride", duration_minutes: 45, training_load: 25,
        compliance: { status: "completed", percentage: 136, basis: "training_load", actual_activity: { name: "Aktivierung absolviert", type: "Ride", moving_duration_s: 3600, distance_m: 24000, training_load: 34, avg_hr: 125, avg_power: 201 } } },
      { id: "agenda-missed", date: addDateKey(date, -3), name: "Ausgefallene Einheit", type: "Ride", duration_minutes: 45, compliance: { status: "missed", percentage: 0 } },
    ];
    renderPlanned(state.data.training_calendar);
    return date;
  });
  // The week view opens on today's week; on wide screens a unit of it is already open as the detail pane.
  const day = page.locator(`.planned-day[data-date="${today}"]`);
  await expect(day.locator("time")).toHaveAttribute("datetime", today);
  await expect(day.locator(".planned-today-label")).toHaveText("Heute");
  await expect(day.locator(".planned-day-weather")).toContainText("12° / 21°");
  await expect(day.locator(".planned-day-health")).toBeVisible();
  await expect(day.locator(".planned-day-calendar")).toBeVisible();
  await expect(day.locator(".planned-entry")).toHaveCount(2);
  // Weather stays a small symbol in the day heading; its details live in the tooltip, not in a block of their own.
  await expect(day.locator(".planned-day-insights, .planned-weather-detail, .planned-weather-metrics, .planned-air-quality")).toHaveCount(0);
  await expect(day.locator(".planned-day-metrics")).toHaveCount(0);
  await expect(day.locator(".planned-day-weather")).toHaveAttribute("title", /Leicht bewölkt\n0 % Regen · 14 km\/h Wind SW · 25 km\/h Böen\nAQI 64 \(schlecht\) · UV 5,2 · Pollen: Birke 1-2/);
  await expect(day).not.toContainText("Emsdetten");
  await expect(day).not.toContainText("Open-Meteo");
  await expect(day.locator(".planned-day-observations img")).toHaveCount(0);
  await expect(page.locator(".planned-week").filter({ has: day }).locator(".planned-week-metrics")).toContainText("Geplant");
  await expect(day.locator(".planned-day-flag")).toHaveText(["AQI 64", "🌿 1-2"]);
  const workout = day.locator(".planned-entry").filter({ hasText: "Lockerer Dauerlauf mit Steigerungen" });
  await expect(workout.locator(".planned-meta")).toHaveText("Laufen · 18:30 · 45 min");
  await expect(workout.locator(".planned-session-header")).toContainText("Laufen · 18:30");
  await expect(workout.locator(".planned-session-header")).toBeVisible();
  if (await workout.evaluate((element) => element.open)) await day.locator(".planned-entry").filter({ hasText: "Mobilität" }).locator("summary").click();
  await expect(workout.locator(".planned-description")).toBeHidden();
  await workout.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(workout.locator(".planned-description")).toBeVisible();
  await expect(workout.locator("img")).toHaveCount(0);
  await page.keyboard.press("Enter");
  await expect(workout.locator(".planned-description")).toBeHidden();
  expect(await day.evaluate((element) => {
    const heading = element.querySelector(".planned-day-heading").getBoundingClientRect();
    const firstUnit = element.querySelector(".planned-entry").getBoundingClientRect();
    return heading.bottom <= firstUnit.top + 1 && element.scrollWidth <= element.clientWidth;
  })).toBe(true);
  await day.screenshot({ path: testInfo.outputPath("planned-agenda.png") });
  const previousDate = await page.evaluate((date) => addDateKey(date, -1), today);
  await showCalendarDay(page, previousDate);
  const previous = page.locator(`.planned-day[data-date="${previousDate}"]`);
  await expect(previous).toHaveCount(1);
  await expect(previous.locator(".planned-day-metrics")).toHaveCount(0);
  await expect(previous.locator(".planned-day-health")).toHaveText("Krankheit: Magen-Darm");
  await expect(previous.locator(".planned-day-empty")).toBeVisible();
  await expect(previous.locator(".planned-day-flag")).toHaveText(["💧 75 %"]);
  await expect(previous.locator(".planned-day-weather")).toHaveAttribute("title", /Gespeicherte Wettervorhersage\n75 % Regen \(max\. 14:00 Uhr\) · 21,1 km\/h Wind/);
  await showCalendarDay(page, await page.evaluate((date) => addDateKey(date, -2), today));
  const matched = page.locator(".planned-entry", { hasText: "Aktivierung absolviert" });
  // #2258 mockup A: a done unit is one slim row; status and share of the plan in one, no bars.
  await expect(matched.locator(".planned-entry-status")).toHaveText("✓ Absolviert · 136 %");
  await expect(matched.locator("summary .calendar-workout-profile, .planned-execution, .planned-session-target")).toHaveCount(0);
  await expect(matched.locator(".planned-session-line")).not.toContainText("Laufen");
  await matched.screenshot({ path: testInfo.outputPath("planned-execution.png") });
  await showCalendarDay(page, await page.evaluate((date) => addDateKey(date, -3), today));
  await expect(page.locator(".planned-entry.is-missed .planned-entry-status")).toHaveText("✕ Nicht absolviert");
  await expect(page.locator(".planned-entry.is-missed summary .calendar-workout-profile")).toHaveCount(0);
  await showCalendarDay(page, await page.evaluate((date) => addDateKey(date, 1), today));
  const completed = page.locator(".planned-entry.is-completed").filter({ hasText: "Grundlagenausfahrt" });
  await expect(completed.locator(".planned-session-line")).toContainText("07:15");
  await expect(completed.locator(".planned-entry-status")).toBeVisible();
  if (!(await completed.evaluate((element) => element.open))) await expect(completed.locator(".planned-actual-facts")).toBeHidden();
  const completedHeaders = page.locator(".planned-entry.is-completed .planned-session-header");
  await expect(page.locator(`.planned-day[data-date="${await page.evaluate((date) => addDateKey(date, 1), today)}"] .planned-entry.is-completed`)).toHaveCount(5);
  for (const theme of ["dark", "light"]) {
    await page.evaluate((selectedTheme) => { document.documentElement.dataset.theme = selectedTheme; }, theme);
    const computedColors = await completedHeaders.evaluateAll((headers) => headers.map((header) => {
      const style = getComputedStyle(header);
      return [style.color, style.backgroundColor];
    }));
    const contrasts = computedColors.map(([foreground, background]) => contrastRatio(foreground, background));
    expect(contrasts.every((ratio) => ratio >= 4.5), `${theme} completed session contrast`).toBe(true);
  }
  if (!(await completed.evaluate((element) => element.open))) await completed.locator(":scope > summary").click();
  // Every value once with German labels; the Coach button names the session, never its stored name.
  const facts = completed.locator(".planned-actual-facts");
  await expect(facts).toContainText("Belastung 42");
  await expect(facts).not.toContainText("Trainingsload");
  await expect(completed.locator(".planned-entry-details")).not.toContainText(/Belastung 42.*Belastung 42/);
  const analyse = completed.getByRole("button", { name: "Mit dem Coach analysieren" });
  const sent = await analyse.evaluate((button) => {
    let text = null;
    const original = globalThis.askCoach;
    globalThis.askCoach = (message) => { text = message; };
    button.click();
    globalThis.askCoach = original;
    return text;
  });
  expect(sent).toMatch(/^Analysiere meine Einheit vom .+ \(Radfahren, 07:15, .+\)\.$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("JSON and audio errors retain status, reason and retry delay", async ({ page }) => {
  await ready(page);
  await page.route("**/api/fixture-error", (route) => route.fulfill({ status: 429, headers: { "Retry-After": "7" }, json: { error: "Synthetic rate limit", reason: "rate_limited" } }));
  const errors = await page.evaluate(async () => {
    const results = [];
    for (const invoke of [() => AppApi.request("/api/fixture-error", { method: "POST", body: "{}" }), () => AppApi.audio("/api/fixture-error", new Blob(["synthetic"]))]) {
      try { await invoke(); }
      catch (error) { results.push({ status: error.status, reason: error.reason, retryAfter: error.retryAfter, message: error.message }); }
    }
    return results;
  });
  expect(errors).toHaveLength(2);
  for (const error of errors) {
    expect(error).toMatchObject({ status: 429, reason: "rate_limited", retryAfter: 7 });
    expect(error.message).toContain("7 Sekunden");
  }
});

test("only current pending proposals expose an explicit confirmation action", async ({ page }) => {
  await ready(page);
  for (const status of ["preview", "ready", "used", "expired"]) {
    await page.evaluate((proposalStatus) => {
      state.coachActionProposals = [{ id: "fixture-status", action_type: "undo_change", status: proposalStatus, diff: [] }];
      renderCoachActionReview();
    }, status);
    const button = page.getByRole("button", { name: "Änderung zurücknehmen", exact: true });
    if (["preview", "ready"].includes(status)) await expect(button).toBeVisible();
    else {
      await expect(button).toHaveCount(0);
      await expect(page.locator("#coachActionReview")).toContainText(status === "used" ? "Freigabe bereits verwendet" : "abgelaufen");
    }
  }
});


test("analysis charts preserve sources, gaps and dated values", { tag: "@responsive" }, async ({ page }) => {
  const history = (() => {
    const points = Array.from({ length: 90 }, (_, i) => ({
      date: new Date(Date.UTC(2026, 6, 5 + i)).toISOString().slice(0, 10),
      ctl: i === 40 || i === 89 ? null : 40 + i / 10,
      atl: i === 40 || i === 89 ? null : 50 + Math.sin(i / 5) * 10,
      tsb: i === 40 || i === 89 ? null : -10 + Math.cos(i / 5) * 10,
    }));
    const metrics = Object.fromEntries([
      ["cycling_ftp_watts", 250], ["run_threshold_pace_seconds_per_km", 300],
      ["cycling_vo2max_ml_kg_min", 52], ["running_vo2max_ml_kg_min", 54],
    ].map(([key, value]) => [key, ["Intervals.icu", "Garmin Connect"].map((source, index) => ({
      source, source_provider: index ? "garmin" : "intervals", points: points.map((point, i) => ({ date: point.date, value: i >= 36 && i <= 42 ? null : value + index + i / 20 })),
    }))]));
    const preferred_providers = Object.fromEntries(Object.keys(metrics).map((key) => [key, "garmin"]));
    return { start: points[0].date, end: points.at(-1).date, load: { points }, metrics, preferred_providers };
  })();
  const projection = fixture.get("/api/performance");
  await page.route("**/api/performance", (route) => route.fulfill({ json: {
    ...projection, performance: { ...projection.performance, history },
  } }));
  await ready(page);
  await page.getByRole("link", { name: "Analyse", exact: true }).click();
  const charts = page.locator("#analysisHistoryCharts");
  await expect(charts.locator("svg")).toHaveCount(4);
  const running = charts.locator('[data-analysis-section="development-Lauf"]').locator("..");
  const cycling = charts.locator('[data-analysis-section="development-Rad"]').locator("..");
  // Each sport's development sits in its own segment (#2265).
  await expect(running.getByRole("heading", { name: "Entwicklung", exact: true })).toBeVisible();
  await expect(running.getByRole("button", { name: "Entwicklung: Informationen", exact: true })).toBeVisible();
  await expect(cycling).toBeHidden();
  await page.locator('[data-analysis-segment="cycling"]').click();
  await expect(cycling.getByRole("heading", { name: "Entwicklung", exact: true })).toBeVisible();
  await expect(cycling.getByRole("button", { name: "Entwicklung: Informationen", exact: true })).toBeVisible();
  await expect(running).toContainText("Schwellenpace: 5:05 min/km");
  await expect(running).toContainText("VO₂max: 59,4 ml/kg/min");
  await expect(cycling).toContainText("FTP: 255,5 W");
  await expect(cycling).not.toContainText("eFTP");
  await expect(cycling).toContainText("VO₂max: 57,4 ml/kg/min");
  await expect(running.locator("path[data-series]")).toHaveCount(2);
  await expect(cycling.locator("path[data-series]")).toHaveCount(2);
  await expect(running).not.toContainText("%");
  await expect(cycling).not.toContainText("%");
  await expect(cycling.locator(".analysis-coverage")).toHaveCount(0);
  await cycling.getByRole("button", { name: "Erklärung zu FTP", exact: true }).click();
  await expect(cycling.locator(".analysis-info-tooltip:popover-open")).toContainText(/Daten für \d+ von \d+ Tagen vorhanden\./);
  await page.keyboard.press("Escape");
  expect((await cycling.locator('path[data-series="0"]').first().getAttribute("d")).match(/M/g)).toHaveLength(1);
  const details = cycling.locator("details:not([data-analysis-section])").filter({ has: page.getByText("Werte ansehen", { exact: true }) }).first();
  await details.locator(":scope > summary").click();
  await expect(details).toHaveAttribute("open", "");
  await expect(details.getByRole("table")).toBeVisible();
  await expect(cycling.getByRole("columnheader", { name: /Rad.*FTP.*Garmin Connect/ })).toBeVisible();
  const AxeBuilder = require("@axe-core/playwright").default;
  expect((await new AxeBuilder({ page }).include("#analysisHistoryCharts").analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  const predictionsText = await charts.locator("#performancePredictions").textContent();
  await page.evaluate(() => renderAnalysisHistory({
    start: "2026-07-05", end: "2026-10-02", load: { points: [] }, metrics: {},
  }));
  await expect(charts.locator("svg")).toHaveCount(0);
  await expect(charts.locator(".empty").filter({ hasText: "Noch keine datierten Werte im Zeitraum vorhanden." })).toHaveCount(0);
  await expect(charts).not.toContainText("Keine Daten");
  await expect(charts.locator("#performancePredictions")).toHaveText(predictionsText);
});
