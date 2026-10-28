const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const {
  CREDENTIAL_FORMS,
  credentialFieldIds,
  credentialFormIds,
  credentialSavePayload,
  credentialSourceView,
  garminCardView,
} = require("../public/provider-connections.js");

const source = fs.readFileSync(path.join(__dirname, "../public/provider-connections.js"), "utf8");

// Loads the real provider-connections.js into a vm context. Every element is created on
// demand, so each test reads the same DOM state the renderer wrote. The API stub records
// each request; the server's answer is supplied per test through setApi.
function loadProviderConnections() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, { id, value: "", textContent: "", className: "", hidden: false, disabled: false, addEventListener() {} });
    }
    return elements.get(id);
  };
  const calls = [];
  const confirmations = [];
  const toasts = [];
  let invalidated = 0;
  let apiHandler = async () => ({});
  let loadedData = {};
  const context = {
    $: (selector) => element(selector.replace(/^#/, "")),
    api: (requestPath, options = {}) => {
      calls.push({ path: requestPath, method: options.method || "GET", body: options.body });
      return apiHandler(requestPath, options);
    },
    load: async () => {
      context.state.data = loadedData;
      vm.runInContext("renderProviderCredentials(state.data)", context);
    },
    state: { data: {} },
    toast: (message, isError = false) => toasts.push({ message, isError }),
    requestConfirmation: async (message, options) => {
      confirmations.push({ message, title: options?.title });
      return context.confirmAnswer;
    },
    confirmAnswer: true,
    invalidateContextPreview: () => { invalidated += 1; },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  const fn = (name) => vm.runInContext(name, context);
  return {
    context,
    calls,
    confirmations,
    toasts,
    element,
    elements,
    fn,
    invalidatedCount: () => invalidated,
    setApi(handler) { apiHandler = handler; },
    setData(data) {
      loadedData = data;
      context.state.data = data;
      vm.runInContext("renderProviderCredentials(state.data)", context);
    },
    // The server state that the next reload will show.
    setLoadedData(data) { loadedData = data; },
  };
}

const event = () => ({ preventDefault() {} });

const statusFields = {
  openai_api_key: { source: "db", configured: true },
  openai_base_url: { source: "env", configured: true, value: "https://example.test/v1" },
  intervals_api_key: { source: "none", configured: false },
  intervals_athlete_id: { source: "db", configured: true, value: "i123" },
  wahoo_client_id: { source: "env", configured: true, value: "wahoo-id" },
  wahoo_client_secret: { source: "none", configured: false },
};

test("badges show the source and only stored values offer removal", () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { fields: statusFields, garmin_connection: { connected: true, source: "db" } } });
  const badge = (field) => harness.element(credentialFieldIds(field).source);
  const clear = (field) => harness.element(credentialFieldIds(field).clear);

  assert.equal(badge("openai_api_key").textContent, "In der App gespeichert");
  assert.equal(badge("openai_api_key").className, "credential-source is-db");
  assert.equal(badge("openai_base_url").textContent, "Aus Umgebung");
  assert.equal(badge("openai_base_url").className, "credential-source is-env");
  assert.equal(badge("intervals_api_key").textContent, "Nicht gesetzt");
  assert.equal(badge("intervals_api_key").className, "credential-source is-none");

  assert.equal(clear("openai_api_key").hidden, false);
  assert.equal(clear("openai_base_url").hidden, true);
  assert.equal(clear("intervals_api_key").hidden, true);
});

test("visible fields show the current value and secrets never do", () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { fields: statusFields } });
  const current = (field) => harness.element(credentialFieldIds(field).current).textContent;

  assert.equal(current("openai_base_url"), "Aktuell: https://example.test/v1");
  assert.equal(current("intervals_athlete_id"), "Aktuell: i123");
  assert.equal(current("wahoo_client_id"), "Aktuell: wahoo-id");
  assert.equal(current("openai_api_key"), "");
  assert.equal(current("wahoo_client_secret"), "");
});

test("re-rendering from polling never writes input values", () => {
  const harness = loadProviderConnections();
  harness.element("cred-openai_api_key").value = "typed-but-unsaved";
  harness.setData({ credentials: { fields: statusFields } });
  harness.setData({ credentials: { fields: statusFields } });
  assert.equal(harness.element("cred-openai_api_key").value, "typed-but-unsaved");
});

test("saving sends only non-blank values and leaves no secret in the DOM", async () => {
  const harness = loadProviderConnections();
  const secret = "sk-test-secret-1234567890";
  harness.setData({ credentials: { fields: statusFields } });
  harness.element("cred-openai_api_key").value = `  ${secret}  `;
  harness.element("cred-openai_base_url").value = "   ";
  harness.setApi(async () => ({ fields: statusFields }));

  await harness.fn("saveProviderCredentials")(event(), "openai");

  assert.equal(harness.calls.length, 1);
  assert.equal(harness.calls[0].path, "/api/settings/credentials");
  assert.equal(harness.calls[0].method, "PUT");
  assert.deepEqual(JSON.parse(harness.calls[0].body), { openai_api_key: secret });
  assert.equal(harness.element("cred-openai_api_key").value, "");
  assert.equal(harness.element("cred-openai_base_url").value, "");
  for (const el of harness.elements.values()) {
    assert.ok(!String(el.value).includes(secret), `value of ${el.id} holds the secret`);
    assert.ok(!String(el.textContent).includes(secret), `text of ${el.id} holds the secret`);
  }
  assert.equal(harness.toasts.at(-1).message, "Zugangsdaten gespeichert");
  assert.equal(harness.invalidatedCount(), 1);
});

test("a save with only blank inputs is rejected without a request", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { fields: statusFields } });
  harness.element("cred-wahoo_client_id").value = "  ";
  harness.element("cred-wahoo_client_secret").value = "";

  await harness.fn("saveProviderCredentials")(event(), "wahoo");

  assert.equal(harness.calls.length, 0);
  const error = harness.element(credentialFormIds("wahoo").error);
  assert.equal(error.textContent, "Bitte mindestens einen Wert eingeben.");
  assert.equal(error.hidden, false);
});

test("the submit button and its clear buttons are disabled while a save is in flight", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { fields: statusFields } });
  harness.element("cred-intervals_api_key").value = "key-123456";
  let finish;
  harness.setApi(() => new Promise((resolve) => { finish = resolve; }));

  const pending = harness.fn("saveProviderCredentials")(event(), "intervals");
  const submit = harness.element(credentialFormIds("intervals").submit);
  assert.equal(submit.disabled, true);
  assert.equal(submit.textContent, "Wird gespeichert…");

  finish({ fields: statusFields });
  await pending;
  assert.equal(submit.disabled, false);
  assert.equal(submit.textContent, "Speichern");
});

test("a failed save shows the server message and still clears the inputs", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { fields: statusFields } });
  harness.element("cred-intervals_athlete_id").value = "not valid";
  harness.setApi(async () => { throw new Error("Athlete-ID ist ungültig."); });

  await harness.fn("saveProviderCredentials")(event(), "intervals");

  assert.equal(harness.element("cred-intervals_athlete_id").value, "");
  const error = harness.element(credentialFormIds("intervals").error);
  assert.equal(error.textContent, "Athlete-ID ist ungültig.");
  assert.equal(error.hidden, false);
});

test("clearing a stored value asks first and then sends null", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { fields: statusFields } });
  harness.setApi(async () => ({ fields: statusFields }));

  harness.context.confirmAnswer = false;
  await harness.fn("clearProviderCredential")("openai_api_key", "openai");
  assert.equal(harness.calls.length, 0);

  harness.context.confirmAnswer = true;
  await harness.fn("clearProviderCredential")("openai_api_key", "openai");
  assert.equal(harness.confirmations.length, 2);
  assert.match(harness.confirmations[0].message, /OpenAI-API-Schlüssel/);
  assert.equal(harness.calls.length, 1);
  assert.equal(harness.calls[0].method, "PUT");
  assert.deepEqual(JSON.parse(harness.calls[0].body), { openai_api_key: null });
});

test("Garmin login stores nothing in the page and moves to the MFA step", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { garmin_connection: { connected: false, source: "none", mfa_pending: false } } });
  harness.setApi(async (requestPath) => {
    if (requestPath === "/api/garmin/login") {
      harness.setLoadedData({ credentials: { garmin_connection: { connected: false, source: "none", mfa_pending: true } } });
      return { status: "mfa_required", garmin_connection: { connected: false, mfa_pending: true } };
    }
    return {};
  });
  harness.element("garmin-email").value = " athlete@example.test ";
  harness.element("garmin-password").value = "garmin-pass-value";

  await harness.fn("submitGarminLogin")(event());

  assert.deepEqual(JSON.parse(harness.calls[0].body), { email: "athlete@example.test", password: "garmin-pass-value" });
  assert.equal(harness.element("garmin-email").value, "");
  assert.equal(harness.element("garmin-password").value, "");
  assert.equal(harness.element("garmin-login-form").hidden, true);
  assert.equal(harness.element("garmin-mfa-form").hidden, false);
  assert.equal(harness.element("garmin-connection-status").textContent, "Bestätigungscode von Garmin erforderlich");
  for (const el of harness.elements.values()) {
    assert.ok(!String(el.value).includes("garmin-pass-value"), `value of ${el.id} holds the password`);
  }
});

test("the MFA code completes the login and clears the code input", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { garmin_connection: { connected: false, source: "none", mfa_pending: true } } });
  harness.setApi(async (requestPath) => {
    if (requestPath === "/api/garmin/login/mfa") {
      harness.setLoadedData({ credentials: { garmin_connection: { connected: true, source: "db", connected_at: "2026-10-18T06:00:00Z" } } });
      return { status: "connected", garmin_connection: { connected: true, source: "db" } };
    }
    return {};
  });
  harness.element("garmin-mfa-code").value = "123456";

  await harness.fn("submitGarminMfa")(event());

  assert.equal(harness.calls[0].path, "/api/garmin/login/mfa");
  assert.equal(harness.calls[0].method, "POST");
  assert.deepEqual(JSON.parse(harness.calls[0].body), { code: "123456" });
  assert.equal(harness.element("garmin-mfa-code").value, "");
  assert.equal(harness.element("garmin-connected").hidden, false);
  assert.equal(harness.element("garmin-mfa-form").hidden, true);
  assert.equal(harness.element("garmin-connection-status").textContent, "Verbunden");
  assert.equal(harness.element("garmin-source").textContent, "In der App gespeichert");
});

test("an empty MFA code is rejected without a request", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { garmin_connection: { connected: false, mfa_pending: true } } });
  harness.element("garmin-mfa-code").value = "   ";

  await harness.fn("submitGarminMfa")(event());

  assert.equal(harness.calls.length, 0);
  assert.equal(harness.element("garmin-mfa-error").hidden, false);
});

test("a discarded pending login returns from the MFA step to the login form", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { garmin_connection: { connected: false, mfa_pending: true } } });
  harness.setApi(async () => {
    const error = new Error("Zu viele falsche Codes.");
    error.status = 409;
    throw error;
  });
  harness.element("garmin-mfa-code").value = "000000";

  await harness.fn("submitGarminMfa")(event());

  assert.equal(harness.element("garmin-mfa-form").hidden, true);
  assert.equal(harness.element("garmin-login-form").hidden, false);
  assert.equal(harness.element("garmin-login-error").textContent, "Zu viele falsche Codes.");
});

test("cancelling the MFA step returns to the login form", () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { garmin_connection: { connected: false, mfa_pending: true } } });
  assert.equal(harness.element("garmin-mfa-form").hidden, false);

  harness.fn("cancelGarminMfa")();

  assert.equal(harness.element("garmin-mfa-form").hidden, true);
  assert.equal(harness.element("garmin-login-form").hidden, false);
  assert.equal(harness.calls.length, 0);
});

test("disconnecting Garmin asks first and posts an empty body", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { garmin_connection: { connected: true, source: "db" } } });
  harness.setApi(async () => ({ garmin_connection: { connected: false, source: "none" } }));

  harness.context.confirmAnswer = false;
  await harness.fn("disconnectGarmin")();
  assert.equal(harness.calls.length, 0);

  harness.context.confirmAnswer = true;
  await harness.fn("disconnectGarmin")();
  assert.equal(harness.calls.length, 1);
  assert.equal(harness.calls[0].path, "/api/garmin/disconnect");
  assert.equal(harness.calls[0].method, "POST");
  assert.equal(harness.calls[0].body, "{}");
});

test("the save payload drops blank and non-string values", () => {
  const payload = credentialSavePayload(
    { openai_api_key: "  sk-1  ", openai_base_url: "   ", intervals_api_key: null },
    CREDENTIAL_FORMS.openai.concat(CREDENTIAL_FORMS.intervals),
  );
  assert.deepEqual(payload, { openai_api_key: "sk-1" });
});

test("source views fall back to none for unknown sources", () => {
  assert.deepEqual(credentialSourceView({ source: "db" }), { source: "db", label: "In der App gespeichert", removable: true });
  assert.deepEqual(credentialSourceView({ source: "env" }), { source: "env", label: "Aus Umgebung", removable: false });
  assert.deepEqual(credentialSourceView({ source: "weird" }), { source: "none", label: "Nicht gesetzt", removable: false });
  assert.deepEqual(credentialSourceView(undefined), { source: "none", label: "Nicht gesetzt", removable: false });
});

test("the Garmin card mode follows garmin_connection and the legacy flag", () => {
  assert.equal(garminCardView({ connected: true, source: "file" }).sourceLabel, "Aus Token-Datei");
  assert.equal(garminCardView(undefined, true).mode, "connected");
  assert.equal(garminCardView({ connected: false, mfa_pending: true }).mode, "mfa");
  assert.equal(garminCardView({ connected: false }, false, { mfaHint: true }).mode, "mfa");
  assert.equal(garminCardView({ connected: false, mfa_pending: true }, false, { loginRestarted: true }).mode, "login");
  assert.equal(garminCardView({ connected: false }).status, "Nicht verbunden");
});

test("the Yazio form saves only filled fields and clears every input", async () => {
  const harness = loadProviderConnections();
  harness.setData({ credentials: { fields: { ...statusFields, yazio_email: { source: "db", configured: true } } } });
  assert.equal(harness.element(credentialFieldIds("yazio_email").source).textContent, "In der App gespeichert");
  assert.equal(harness.element(credentialFieldIds("yazio_email").current).textContent, "");
  harness.element("cred-yazio_email").value = " athlete@example.test ";
  harness.element("cred-yazio_password").value = "synthetic-password";
  harness.setApi(async () => ({ fields: statusFields }));

  await harness.fn("saveProviderCredentials")(event(), "yazio");

  assert.deepEqual(JSON.parse(harness.calls[0].body), { yazio_email: "athlete@example.test", yazio_password: "synthetic-password" });
  for (const field of ["yazio_email", "yazio_password", "yazio_client_id", "yazio_client_secret"]) {
    assert.equal(harness.element(`cred-${field}`).value, "");
  }
});


test("Yazio status is passive and explicit check renders a safe result", async () => {
  const harness = loadProviderConnections();
  harness.setApi(async (url) => url.endsWith("/status") ? { status: "unchecked" } : { status: "success", checked_at: "2026-01-01T00:00:00Z" });
  await harness.fn("loadYazioStatus")();
  assert.equal(harness.element("yazioConnectionStatus").textContent, "Noch nicht geprüft");
  assert.equal(harness.calls[0].method, "GET");
  await harness.fn("checkYazioConnection")();
  assert.equal(harness.calls[1].method, "POST");
  assert.equal(harness.element("yazioConnectionStatus").textContent, "Anmeldung erfolgreich");
  assert.match(harness.element("yazioConnectionDetail").textContent, /Geprüft:/);
  harness.setApi(async () => { throw Error("synthetic secret"); });
  await harness.fn("checkYazioConnection")();
  assert.equal(harness.element("yazioConnectionStatus").textContent, "Status nicht verfügbar");
});

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("Yazio ignores out-of-order status GET and overlapping checks", async () => {
  const harness = loadProviderConnections();
  const requests = [];
  harness.setApi(() => { const request = deferred(); requests.push(request); return request.promise; });
  const oldGet = harness.fn("loadYazioStatus")();
  const newerGet = harness.fn("loadYazioStatus")();
  requests[1].resolve({ status: "unchecked" });
  await newerGet;
  requests[0].resolve({ status: "success" });
  await oldGet;
  assert.equal(harness.element("yazioConnectionStatus").textContent, "Noch nicht geprüft");

  const first = harness.fn("checkYazioConnection")();
  const second = harness.fn("checkYazioConnection")();
  requests[2].resolve({ status: "success" });
  await first;
  assert.equal(harness.element("yazioCheckButton").disabled, true);
  requests[3].resolve({ status: "auth_failed" });
  await second;
  assert.match(harness.element("yazioConnectionStatus").textContent, /abgelehnt/);
  assert.equal(harness.element("yazioCheckButton").disabled, false);
});

test("a pending passive status cannot overwrite a newer explicit check", async () => {
  const harness = loadProviderConnections();
  const oldStatus = deferred();
  harness.setApi((url) => url.endsWith("/status") ? oldStatus.promise : Promise.resolve({ status: "success" }));
  const pending = harness.fn("loadYazioStatus")();
  await harness.fn("checkYazioConnection")();
  oldStatus.resolve({ status: "unchecked" });
  await pending;
  assert.equal(harness.element("yazioConnectionStatus").textContent, "Anmeldung erfolgreich");
});

test("credential changes invalidate pending GET and POST status results", async () => {
  for (const operation of ["loadYazioStatus", "checkYazioConnection"]) {
    const harness = loadProviderConnections();
    const pendingStatus = deferred();
    const save = deferred();
    harness.setApi((url, options) => {
      if (options.method === "PUT") return save.promise;
      if (url.endsWith("/status") && harness.calls.length > 2) return Promise.resolve({ status: "unchecked" });
      return pendingStatus.promise;
    });
    const pending = harness.fn(operation)();
    harness.element("cred-yazio_password").value = "new-synthetic-password";
    const saving = harness.fn("saveProviderCredentials")(event(), "yazio");
    pendingStatus.resolve({ status: "success" });
    await pending;
    assert.notEqual(harness.element("yazioConnectionStatus").textContent, "Anmeldung erfolgreich");
    save.resolve({});
    await saving;
    assert.equal(harness.element("yazioConnectionStatus").textContent, "Noch nicht geprüft");
  }
});
