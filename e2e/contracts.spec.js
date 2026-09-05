const { test, expect } = require("@playwright/test");
const { captureReadFixture, installReadFixture } = require("./read-fixture");

let fixture;
test.beforeAll(async ({ request }) => { fixture = await captureReadFixture(request); });
test.beforeEach(async ({ page }) => { await installReadFixture(page, fixture); });

async function ready(page) {
  await page.goto("/");
  await expect(page.locator("#appShell")).toBeVisible();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(state.data))).toBe(true);
  await page.evaluate(() => {
    state.stateEventSource?.close();
    clearTimeout(state.chatStatusTimer);
    state.data.messages = [];
    renderMessages([]);
  });
}

async function controlled(page) {
  await page.evaluate(() => {
    const original = fetch.bind(window);
    const fixture = { histories: [], planCalls: 0, libraryCalls: 0 };
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    fixture.push = (event, payload) => fixture.controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`));
    window.__contract = fixture;
    window.fetch = (path, options) => {
      if (path === "/api/chat/stream") {
        fixture.turn = JSON.parse(options.body).client_turn_id;
        return Promise.resolve(new Response(new ReadableStream({ start(controller) {
          fixture.controller = controller;
          fixture.push("started", { operation_id: "fixture-operation" });
        } }), { status: 200 }));
      }
      if (path.startsWith("/api/chat/history")) return new Promise((resolve) => fixture.histories.push((messages) => resolve(json({ messages, next_cursor: null }))));
      if (path.startsWith("/api/plan")) fixture.planCalls++;
      if (path.startsWith("/api/library")) fixture.libraryCalls++;
      return original(path, options);
    };
  });
}

test("chat reset detaches a delayed status poll without releasing its successor", async ({ page }) => {
  await ready(page);
  await page.evaluate(() => {
    const original = fetch.bind(window);
    window.__statusCalls = [];
    window.fetch = (path, options) => {
      if (path === "/api/chat/status") return new Promise((resolve) => __statusCalls.push((status) => resolve(new Response(JSON.stringify(status), { headers: { "Content-Type": "application/json" } }))));
      if (path === "/api/chat/reset") return Promise.resolve(new Response('{"status":"ok"}', { headers: { "Content-Type": "application/json" } }));
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

test("history barriers preserve optimistic and completed messages through navigation", async ({ page }) => {
  await ready(page);
  await controlled(page);
  await page.evaluate(() => { void load("/api/bootstrap?local=1", ["chat"]); });
  await expect.poll(() => page.evaluate(() => __contract.histories.length)).toBe(1);
  await page.locator("#messageInput").fill("Fixture Run plan");
  await page.locator("#sendButton").click();
  await page.evaluate(() => __contract.histories.shift()([]));
  await expect(page.locator(".message.user")).toHaveText("Fixture Run plan");
  await page.evaluate(() => { void load("/api/bootstrap?local=1", ["chat"]); });
  await expect.poll(() => page.evaluate(() => __contract.histories.length)).toBe(1);
  await page.getByRole("link", { name: "Geplant", exact: true }).click();
  await page.evaluate(() => {
    __contract.push("completed", { message: { id: 102, content: "Run plan saved", client_turn_id: __contract.turn }, proposed_actions: [], command_receipts: [] });
    __contract.controller.close();
    __contract.histories.shift()([]);
  });
  await expect.poll(() => page.evaluate(() => __contract.planCalls)).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => __contract.libraryCalls)).toBeGreaterThan(0);
  await expect.poll(() => page.evaluate(() => __contract.histories.length)).toBe(1);
  await page.evaluate(() => __contract.histories.shift()([
    { id: 101, role: "user", client_turn_id: __contract.turn, content: "Fixture Run plan" },
    { id: 102, role: "assistant", client_turn_id: __contract.turn, content: "Run plan saved" },
  ]));
  await page.getByRole("link", { name: "Coach", exact: true }).click();
  await expect(page.locator(".message.user")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveText("Run plan saved");
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
  await page.evaluate(() => jumpToChatComposer());
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
  await page.evaluate(() => sessionStorage.setItem("coachPendingTurn", "fixture-persisted-turn"));
  await page.route("**/api/chat/receipt?*", (route) => route.fulfill({ json: {
    client_turn_id: "fixture-persisted-turn", status: "partial",
    message: { id: 501, client_turn_id: "fixture-persisted-turn", content: "Check-in saved; summary unavailable." },
    command_receipts: [{ tool: "save_checkin", result: { ok: true, status: "saved" } }],
    proposed_actions: [{ id: "fixture-undo", action_type: "undo_change", status: "preview", target_system: "local", diff: [] }],
  } }));
  await page.reload();
  await expect(page.locator(".message.assistant")).toContainText("Check-in saved; summary unavailable.");
  await expect(page.locator("#coachReceipts")).toContainText("Tages-Check-in gespeichert");
  await expect(page.getByRole("button", { name: "Änderung zurücknehmen", exact: true })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("coachPendingTurn"))).toBe(null);
});

test("progress and cancel remain reachable while the composer is hidden", async ({ page }) => {
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

test("provider source retains visible stale and partial measurement context", async ({ page }) => {
  await ready(page);
  await page.getByRole("link", { name: "Analyse", exact: true }).click();
  await page.evaluate(() => {
    const root = document.querySelector("#dataPanel");
    displayMetric(root, "Fixture retained HRV", { value: 58, unit: "ms", source: "Garmin Connect", freshness: "stale", observed_at: "2026-09-01", fetched_at: "2026-09-02T10:00:00Z" });
    displayMetric(root, "Fixture retained readiness", { value: 65, source: "Garmin Connect", freshness: "partial", observed_at: "2026-09-02" });
  });
  await expect(page.locator("#dataPanel")).toContainText("Garmin Connect · Veraltet · Messung");
  await expect(page.locator("#dataPanel")).toContainText("Garmin Connect · Teilweise aktualisiert · Messung");
});

test("fresh service worker keeps the current shell available offline", async ({ page }) => {
  await ready(page);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.context().setOffline(true);
  try {
    await page.reload();
    await expect(page.locator("#loginDialog")).toBeVisible();
    await expect(page.locator("#loginPassword")).toBeEditable();
    expect(await page.evaluate(async () => {
      const names = await caches.keys();
      const cache = await caches.open(names[0]);
      return (await cache.keys()).some((request) => new URL(request.url).pathname.startsWith("/api/"));
    })).toBe(false);
  } finally { await page.context().setOffline(false); }
});

test("current plan payload displays each requested sport exactly", async ({ page }) => {
  await ready(page);
  await page.getByRole("link", { name: "Geplant", exact: true }).click();
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

test("planned agenda prioritizes dates and sessions with compact weather and expandable details", async ({ page }, testInfo) => {
  await ready(page);
  await page.getByRole("link", { name: "Geplant", exact: true }).click();
  await expect.poll(() => page.evaluate(() => state.loadPromise === null)).toBe(true);
  const today = await page.evaluate(() => {
    const date = timezoneDateKey(state.data?.profile?.timezone, new Date());
    state.data.calendar_display = { past_weeks: 1, future_weeks: 1 };
    state.data.daily_planning_context = [{ date,
      weather: { weather_code: 2, condition: "Leicht bewölkt", temperature_min: 12, temperature_max: 21, precipitation_probability_max: 0, wind_speed_max: 14, forecast_location: "Emsdetten" },
      appointments: [{ name: "Zeit für Training ab 18 Uhr", all_day: true }],
      checkin: { pain: "Leichte Beschwerden im Knie", day_form: "Gut erholt", soreness: 0, stress: 2, motivation: 8, available_minutes: 60, notes: "<img src=x onerror=alert(1)>" },
      recovery: { sleep_hours: 8, hrv: 54, resting_hr: 48, readiness: 80, body_battery: 85, sources: { sleep_hours: "Garmin Connect", hrv: "Intervals.icu Wellness" } },
    }, { date: addDateKey(date, -1),
      weather: { weather_code: 63, temperature_min: 10, temperature_max: 17, archived_forecast: true, forecast_location: "Emsdetten" },
      recovery: { sleep_hours: 6.5, hrv: 42, resting_hr: 53 },
      checkin: { stress: 5 },
    }];
    state.data.training_calendar = [
      { id: "agenda-run", date, name: "Lockerer Dauerlauf mit Steigerungen", type: "Run", duration_minutes: 45, description: "Locker laufen. <img src=x onerror=alert(1)>" },
      { id: "agenda-strength", date, name: "Mobilität und Rumpfstabilität", type: "WeightTraining", duration_minutes: 20 },
      { id: "agenda-completed", date: addDateKey(date, 1), name: "Grundlagenausfahrt", type: "Ride", is_completed_activity: true, moving_time: 3600, distance: 28000, icu_training_load: 42, icu_rpe: 3 },
    ];
    renderPlanned(state.data.training_calendar);
    document.querySelectorAll(".planned-week").forEach((week) => { week.open = true; });
    return date;
  });
  const day = page.locator(`.planned-day[data-date="${today}"]`);
  await expect(day.locator("time")).toHaveAttribute("datetime", today);
  await expect(day.locator(".planned-today-label")).toHaveText("Heute");
  await expect(day.locator(".planned-day-weather")).toContainText("12° / 21°");
  await expect(day.locator(".planned-day-health")).toBeVisible();
  await expect(day.locator(".planned-day-calendar")).toBeVisible();
  await expect(day.locator(".planned-entry")).toHaveCount(2);
  await expect(day.locator(".planned-day-content .planned-day-insights")).toHaveCount(0);
  await expect(day.locator(".planned-day-insights summary, .planned-day-insights details")).toHaveCount(0);
  await expect(day.locator(".planned-day-metrics")).toBeVisible();
  await expect(day.locator(".planned-day-metrics")).toContainText("Schlaf8 h");
  await expect(day.locator(".planned-day-metrics")).toContainText("Muskelkater0/10");
  await expect(day.locator(".planned-day-metrics")).toContainText("Body Battery85/100");
  await expect(day.locator(".planned-day-observations")).toContainText("0 % Regenwahrscheinlichkeit");
  await expect(day.locator(".planned-day-metrics > div", { hasText: "HRV54 ms" })).toHaveAttribute("title", "HRV: Intervals.icu Wellness");
  await expect(day.locator(".planned-insights-sources")).toContainText("Intervals.icu Wellness");
  await expect(day.locator(".planned-day-observations img")).toHaveCount(0);
  const previous = page.locator(".planned-day").filter({ has: page.locator(".planned-day-metrics", { hasText: "Schlaf6,5 h" }) });
  await expect(previous).toHaveCount(1);
  await expect(previous.locator(".planned-day-metrics")).not.toContainText("85/100");
  await expect(previous.locator(".planned-day-metrics")).toBeVisible();
  await expect(previous.locator(".planned-weather-detail")).toContainText("Gespeicherte Wettervorhersage");
  const workout = day.locator(".planned-entry").first();
  await expect(workout.locator(".planned-meta")).toHaveText("Laufen · 45 Min.");
  await expect(workout.locator(".planned-description")).toBeHidden();
  await workout.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(workout.locator(".planned-description")).toBeVisible();
  await expect(workout.locator("img")).toHaveCount(0);
  await page.keyboard.press("Enter");
  const completed = page.locator(".planned-entry.is-completed");
  await expect(completed.locator(".planned-entry-status")).toBeVisible();
  await expect(completed.locator(".planned-actual-facts")).toBeHidden();
  await completed.locator("summary").click();
  await expect(completed.locator(".planned-actual-facts")).toContainText("Trainingsload 42");
  await completed.locator("summary").click();
  expect(await day.evaluate((element) => {
    const heading = element.querySelector(".planned-day-heading").getBoundingClientRect();
    const content = element.querySelector(".planned-day-content").getBoundingClientRect();
    const insights = element.querySelector(".planned-day-insights").getBoundingClientRect();
    return heading.right <= content.left && element.scrollWidth <= element.clientWidth
      && insights.top >= content.bottom && insights.left < content.left;
  })).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await day.screenshot({ path: testInfo.outputPath("planned-agenda.png") });
  const week = page.locator(".planned-week").first();
  await week.locator(":scope > summary").click();
  await page.evaluate(() => renderPlanned(state.data.training_calendar));
  await expect(week).not.toHaveAttribute("open", "");
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

test("another tab takes over an expired polling lease after the leader closes", async ({ page, context }) => {
  await ready(page);
  const follower = await context.newPage();
  await installReadFixture(follower, fixture);
  await ready(follower);
  for (const tab of [page, follower]) await tab.evaluate(() => {
    clearTimeout(state.syncPoll.timer);
    state.syncPoll.controller?.abort();
    state.syncPoll.channel?.close();
  });
  await page.evaluate(() => {
    localStorage.setItem(SYNC_POLL_LEASE_KEY, JSON.stringify({ token: state.syncPoll.leaseToken, expires_at: Date.now() + 60000 }));
  });
  expect(await follower.evaluate(() => syncPollLeaseAvailable())).toBe(false);
  await page.close();
  expect(await follower.evaluate(() => syncPollLeaseAvailable())).toBe(true);
  await follower.evaluate(() => {
    localStorage.setItem(SYNC_POLL_LEASE_KEY, JSON.stringify({ token: "closed-fixture-tab", expires_at: Date.now() - 1 }));
  });
  expect(await follower.evaluate(() => syncPollLeaseAvailable())).toBe(true);
  await follower.evaluate(() => releaseSyncPollLease());
  expect(await follower.evaluate(() => localStorage.getItem(SYNC_POLL_LEASE_KEY))).toBe(null);
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
