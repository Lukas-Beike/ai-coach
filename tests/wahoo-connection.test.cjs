const assert = require("node:assert/strict");
const { test } = require("node:test");

const { wahooConnectionView, safeWahooAuthorizeUrl } = require("../public/wahoo-connection.js");

const authRequired = { provider: "wahoo", error_code: "auth_required" };

test("a server without Wahoo credentials is not configured and offers no action", () => {
  const view = wahooConnectionView({ wahoo: { configured: false, connected: false } });
  assert.equal(view.status, "Nicht konfiguriert");
  assert.equal(view.showSetupHint, true);
  assert.equal(view.canConnect, false);
  assert.equal(view.canDisconnect, false);
});

test("configured but not connected offers only Connect", () => {
  const view = wahooConnectionView({ wahoo: { configured: true, connected: false } });
  assert.equal(view.status, "Nicht verbunden");
  assert.equal(view.canConnect, true);
  assert.equal(view.canDisconnect, false);
  assert.equal(view.connectLabel, "Wahoo verbinden");
  assert.equal(view.showSetupHint, false);
});

test("connected offers only Disconnect and never exposes the scope", () => {
  const view = wahooConnectionView({ wahoo: { configured: true, connected: true, scope: "workouts_read" } });
  assert.equal(view.status, "Verbunden");
  assert.equal(view.ok, true);
  assert.equal(view.canConnect, false);
  assert.equal(view.canDisconnect, true);
  assert.ok(!JSON.stringify(view).includes("workouts_read"));
});

test("a rejected token (auth_required freshness) asks for a reconnect", () => {
  const view = wahooConnectionView({
    wahoo: { configured: true, connected: false },
    provider_freshness: [{ provider: "intervals", error_code: "auth_required" }, authRequired],
  });
  assert.equal(view.reconnect, true);
  assert.equal(view.status, "Erneute Verbindung erforderlich");
  assert.equal(view.connectLabel, "Wahoo erneut verbinden");
  assert.equal(view.canConnect, true);
});

test("an auth error of another provider or a connected Wahoo is not a reconnect", () => {
  assert.equal(wahooConnectionView({
    wahoo: { configured: true, connected: false },
    provider_freshness: [{ provider: "garmin", error_code: "auth_required" }],
  }).reconnect, false);
  assert.equal(wahooConnectionView({
    wahoo: { configured: true, connected: true },
    provider_freshness: [authRequired],
  }).reconnect, false);
});

test("missing state degrades to not configured", () => {
  assert.equal(wahooConnectionView({}).status, "Nicht konfiguriert");
  assert.equal(wahooConnectionView(undefined).canConnect, false);
});

test("only https authorize URLs are followed", () => {
  assert.equal(safeWahooAuthorizeUrl("https://api.wahooligan.com/oauth/authorize?x=1"), "https://api.wahooligan.com/oauth/authorize?x=1");
  assert.equal(safeWahooAuthorizeUrl("javascript:alert(1)"), null);
  assert.equal(safeWahooAuthorizeUrl("http://example.test/"), null);
  assert.equal(safeWahooAuthorizeUrl(""), null);
});
