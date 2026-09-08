const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#loginDialog")).toBeHidden();
  await page.waitForFunction(() => state.initialStateLoaded);
});

test("queued unsent text protects reload without browser persistence", async ({ page }) => {
  const result = await page.evaluate(() => {
    queueChatMessage("Synthetic queued draft", "queue");
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return { guarded: hasUnsavedChanges(), prevented: event.defaultPrevented,
      stored: JSON.stringify({ ...localStorage, ...sessionStorage }).includes("Synthetic queued draft") };
  });
  expect(result).toEqual({ guarded: true, prevented: true, stored: false });
});

test("profile edits made while saving remain dirty and visible", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => url === "/api/profile" && options?.method === "PUT"
      ? new Promise((resolve) => { window.releaseSave = () => resolve(new Response(options.body, { headers: { "Content-Type": "application/json" } })); })
      : original(url, options);
    const form = document.querySelector("#profileForm");
    form.elements.name.value = "Submitted name";
    state.profileDirty = true;
    window.saveFinished = saveProfile({ preventDefault() {}, currentTarget: form });
  });
  await page.evaluate(() => {
    document.querySelector("#profileForm").elements.name.value = "New unsaved name";
    document.querySelector("#profileForm").dispatchEvent(new Event("input"));
    window.releaseSave();
  });
  await page.evaluate(() => window.saveFinished);
  expect(await page.evaluate(() => ({ dirty: state.profileDirty, name: document.querySelector("#profileForm").elements.name.value })))
    .toEqual({ dirty: true, name: "New unsaved name" });
});

test("performance polling preserves the active inline editor", async ({ page }) => {
  const result = await page.evaluate(() => {
    const root = document.querySelector("#performanceSummary");
    root.replaceChildren();
    displayMetric(root, "Weight", { value: 70 }, null, { key: "weight" });
    root.querySelector("button").click();
    const input = root.querySelector("input");
    input.value = "67.8";
    renderPerformance(state.data.performance);
    return { connected: input.isConnected, value: input.value, editing: !input.hidden };
  });
  expect(result).toEqual({ connected: true, value: "67.8", editing: true });
});

test("late microphone permission after logout stops and discards capture", async ({ page }) => {
  const result = await page.evaluate(async () => {
    window.stoppedTracks = 0;
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: () => new Promise((resolve) => { window.releaseMicrophone = resolve; }) });
    const capture = toggleVoiceInput();
    showLogin();
    window.releaseMicrophone({ getTracks: () => [{ stop: () => { window.stoppedTracks += 1; } }] });
    await capture;
    return { stopped: window.stoppedTracks, recording: voiceIsRecording(), acquiring: state.voiceAcquiring };
  });
  expect(result).toEqual({ stopped: 1, recording: false, acquiring: false });
});

test("cancel before stream identity is retained for the matching operation", async ({ page }) => {
  await page.evaluate(() => {
    window.cancelCalls = [];
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => {
      if (url === "/api/chat/stream") return Promise.resolve(new Response(new ReadableStream({ start(controller) { window.chatController = controller; } })));
      if (url === "/api/chat/cancel") { window.cancelCalls.push(JSON.parse(options.body)); return Promise.resolve(new Response('{"status":"cancelling"}')); }
      return original(url, options);
    };
    state.busy = true;
    void requestCoachResponse("Synthetic delayed acceptance");
  });
  await page.evaluate(() => cancelChat());
  expect(await page.evaluate(() => state.chatRequest.cancelRequested)).toBe(true);
  await page.evaluate(() => {
    window.chatController.enqueue(new TextEncoder().encode('event: started\ndata: {"operation_id":"synthetic-delayed"}\n\n'));
  });
  await expect.poll(() => page.evaluate(() => window.cancelCalls)).toEqual([{ operation_id: "synthetic-delayed" }]);
  await page.evaluate(() => window.chatController.close());
});

test("a missing acceptance receipt leaves a recoverable failed message", async ({ page }) => {
  await page.evaluate(async () => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => {
      if (String(url).startsWith("/api/chat/receipt")) return Promise.resolve(new Response('{"error":"Missing"}', { status: 404 }));
      if (url === "/api/chat/status") return Promise.resolve(new Response('{"status":"idle"}'));
      return original(url, options);
    };
    state.chatRequest = { phase: "recovering", clientTurnId: "never-accepted", message: "Synthetic offline draft" };
    state.chatStream = null;
    state.busy = true;
    state.chatStatusPollInFlight = null;
    await pollChatStatus();
  });
  await expect(page.locator(".message-error").filter({ hasText: "nicht angenommen" })).toBeVisible();
  expect(await page.evaluate(() => state.busy)).toBe(false);
});

test("cross-tab reset removes the old authoritative history", async ({ page }) => {
  await page.evaluate(async () => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => String(url).startsWith("/api/chat/history")
      ? Promise.resolve(new Response('{"messages":[],"generation":"synthetic-new-chat","next_cursor":null}')) : original(url, options);
    state.data.messages_generation = "synthetic-old-chat";
    state.data.messages = [{ id: 123456, role: "assistant", content: "Deleted synthetic message" }];
    await loadChatHistoryFresh();
  });
  expect(await page.evaluate(() => state.data.messages)).toEqual([]);
});

test("chat reset clears a recovered busy state", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => url === "/api/chat/reset"
      ? Promise.resolve(new Response('{"status":"ok","generation":"synthetic-reset"}')) : original(url, options);
    state.busy = true;
    state.chatRequest = { phase: "recovering" };
    void resetCoachChat();
  });
  await page.locator("#confirmationDialogAccept").click();
  await expect.poll(() => page.evaluate(() => ({ busy: state.busy, request: state.chatRequest }))).toEqual({ busy: false, request: null });
});

test("cross-tab reset retains a new turn already accepted in the new history", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => String(url).startsWith("/api/chat/history")
      ? Promise.resolve(new Response(JSON.stringify({ messages: [{ id: 200, role: "user", content: "New request", client_turn_id: "new-turn" }], generation: "new-generation", next_cursor: null })))
      : original(url, options);
    state.data.messages_generation = "old-generation";
    state.data.messages = [{ id: 100, role: "assistant", content: "Deleted old reply" }, { role: "user", content: "New request", client_turn_id: "new-turn", optimistic: true }];
    state.chatRequest = { phase: "recovering", clientTurnId: "new-turn", message: "New request" };
    await loadChatHistoryFresh();
    return { ids: state.data.messages.map((message) => message.id), turn: state.chatRequest?.clientTurnId };
  });
  expect(result).toEqual({ ids: [200], turn: "new-turn" });
});

test("cross-tab reset retains a rejected unsent draft and its recovery action", async ({ page }) => {
  await page.evaluate(async () => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => String(url).startsWith("/api/chat/history")
      ? Promise.resolve(new Response('{"messages":[],"generation":"new-generation","next_cursor":null}'))
      : original(url, options);
    state.data.messages_generation = "old-generation";
    state.data.messages = [{ id: 100, role: "assistant", content: "Deleted old reply" }];
    state.rejectedMessages = [{ role: "user", content: "Unsent rejected draft", client_turn_id: "rejected-turn", error: "Synthetic rejection" }];
    await loadChatHistoryFresh();
  });
  await expect(page.locator("#messages")).not.toContainText("Deleted old reply");
  await expect(page.locator("#messages")).toContainText("Unsent rejected draft");
  await page.getByRole("button", { name: "Als Entwurf übernehmen" }).click();
  await expect(page.locator("#messageInput")).toHaveValue("Unsent rejected draft");
});

test("history and library cursors expose and append another page once", async ({ page }) => {
  await page.evaluate(() => {
    const original = window.fetch.bind(window);
    window.fetch = (url, options) => {
      if (String(url).includes("cursor=synthetic-history")) return Promise.resolve(new Response(JSON.stringify({ generation: state.data.messages_generation, messages: [{ id: 1, role: "user", content: "Older synthetic message" }], next_cursor: null })));
      if (String(url).includes("cursor=synthetic-library")) return Promise.resolve(new Response('{"workouts":[{"id":"older-template","name":"Older synthetic template","type":"Ride"}],"next_cursor":null}'));
      return original(url, options);
    };
    state.data.messages = [{ id: 2, role: "assistant", content: "Current synthetic message" }];
    state.data.messages_next_cursor = "synthetic-history";
    renderMessages(state.data.messages);
    state.data.library = [];
    state.data.library_next_cursor = "synthetic-library";
    renderLibrary([]);
  });
  await page.locator('[data-page-area="chat"]').click();
  await expect.poll(() => page.evaluate(() => state.data.messages.map((item) => item.id))).toEqual([1, 2]);
  await page.evaluate(() => document.querySelector('[data-page-area="library"]').click());
  await expect.poll(() => page.evaluate(() => state.data.library.map((item) => item.id))).toEqual(["older-template"]);
});

test("empty activity filter results still allow the next server page", async ({ page }) => {
  expect(await page.evaluate(() => {
    state.activityFromDate = "2099-01-01";
    state.data.activities_next_cursor = "synthetic-older-page";
    renderActivities([{ id: "old", name: "Synthetic", start_date_local: "2020-01-01", type: "Ride" }]);
    return Boolean(document.querySelector(".activity-load-more"));
  })).toBe(true);
});
