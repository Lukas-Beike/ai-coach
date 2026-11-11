const assert = require("node:assert/strict");
const { test } = require("node:test");
const { loadPublicScript } = require("./frontend-harness.cjs");

const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

// Loads public/api.js with a scripted fetch; every timer the client arms is recorded.
function client(respond = () => json({ ok: true })) {
  const delays = [];
  const requests = [];
  const context = loadPublicScript("api.js", {
    AbortController, Headers, Event, Response, clearTimeout() {},
    setTimeout(_callback, delay) { delays.push(delay); return delay; },
    document: { cookie: "theme=dark; ic_csrf=token-1" },
    fetch: async (path, init) => { requests.push({ path, init }); return respond(path, init); },
  });
  return { api: context.AppApi, delays, requests };
}

test("the client exposes one frozen surface", () => {
  const { api } = client();
  assert.ok(Object.isFrozen(api));
  assert.deepEqual(Object.keys(api).sort(), ["audio", "download", "messageForReason", "request", "responseError", "stream"]);
});

test("each call arms its own timeout, and an explicit timeout wins", async () => {
  const { api, delays } = client(() => json({ ok: true, transcript: "Hallo" }));
  await api.request("/api/profile");
  await api.request("/api/coach/actions/execute", { method: "POST" });
  await api.request("/api/bootstrap", { timeoutMs: 90_000 });
  await api.audio("/api/chat/transcribe", new Blob(["x"]));
  assert.deepEqual(delays, [25_000, 55_000, 90_000, 100_000]);
  const downloads = client(() => new Response("file"));
  await downloads.api.download("/api/logs/download");
  assert.deepEqual(downloads.delays, [25_000]);
});

test("a state-changing request carries the CSRF token, a read does not", async () => {
  const { api, requests } = client();
  await api.request("/api/profile");
  await api.request("/api/profile", { method: "PUT", body: "{}" });
  assert.equal(requests[0].init.headers.get("X-CSRF-Token"), null);
  assert.equal(requests[1].init.headers.get("X-CSRF-Token"), "token-1");
  assert.equal(requests[1].init.credentials, "same-origin");
});

test("an upstream failure shows its own German message and never the upstream text", async () => {
  const reasons = ["upstream_auth", "upstream_rate_limited", "upstream_unavailable", "upstream_rejected", "upstream_not_found"];
  const messages = new Set();
  for (const reason of reasons) {
    const { api } = client(() => json({ error: "Raw upstream body with secret-token", reason }, 502));
    const error = await api.request("/api/sync").catch((caught) => caught);
    assert.equal(error.reason, reason);
    assert.match(error.message, /externen? Dienst|Ressource/);
    assert.ok(!error.message.includes("secret-token"));
    messages.add(error.message);
  }
  assert.equal(messages.size, reasons.length);
  assert.equal(client().api.messageForReason("upstream_auth"), [...messages][0]);
});

test("a missing resource asks the athlete to check it, with the server reason when there is one", async () => {
  const withReason = client(() => json({ error: "Training nicht gefunden." }, 404));
  const error = await withReason.api.request("/api/library/1").catch((caught) => caught);
  assert.equal(error.message, "Training nicht gefunden. Bitte prüfen, ob die Ressource noch verfügbar ist.");
  const without = client(() => json({}, 404));
  const bare = await without.api.request("/api/library/1").catch((caught) => caught);
  assert.equal(bare.message, "Die angeforderte Ressource wurde nicht gefunden. Bitte die Adresse prüfen.");
  assert.equal(bare.status, 404);
});
