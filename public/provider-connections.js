// Provider credential forms in the Anbindungen section. Values are written through
// PUT /api/settings/credentials and the Garmin login routes. The server answers with
// status only, so the page never receives a secret back. Inputs are never prefilled
// and are cleared as soon as their values are taken for a request.

const CREDENTIAL_FORMS = Object.freeze({
  openai: Object.freeze(["openai_api_key", "openai_base_url"]),
  intervals: Object.freeze(["intervals_api_key", "intervals_athlete_id"]),
  wahoo: Object.freeze(["wahoo_client_id", "wahoo_client_secret"]),
});

const CREDENTIAL_FIELD_LABELS = Object.freeze({
  openai_api_key: "OpenAI-API-Schlüssel",
  openai_base_url: "OpenAI-Basis-URL",
  intervals_api_key: "Intervals.icu-API-Schlüssel",
  intervals_athlete_id: "Intervals.icu-Athlete-ID",
  wahoo_client_id: "Wahoo-Client-ID",
  wahoo_client_secret: "Wahoo-Client-Secret",
});

// Non-secret values the server echoes back; they are shown as the current value.
const CREDENTIAL_VISIBLE_FIELDS = new Set(["openai_base_url", "intervals_athlete_id", "wahoo_client_id"]);

const CREDENTIAL_SOURCE_LABELS = Object.freeze({
  db: "In der App gespeichert",
  env: "Aus Umgebung",
  none: "Nicht gesetzt",
});

const GARMIN_SOURCE_LABELS = Object.freeze({
  db: "In der App gespeichert",
  file: "Aus Token-Datei",
  env: "Aus Umgebung",
  none: "Nicht gesetzt",
});

// Requests in flight per card (GARMIN_CARD for the Garmin card). Re-renders from
// polling keep these controls disabled until the request settles.
const providerCredentialBusy = new Set();
const GARMIN_CARD = "garmin-login";
// Garmin login can take longer than the default request timeout.
const GARMIN_LOGIN_TIMEOUT_MS = 55_000;
// Set when the login response reports MFA, so a stale or failed reload still shows
// the code step. Cleared by a successful code, cancel or disconnect.
let garminMfaHint = false;
// Set by "Abbrechen" in the MFA step so the login form returns without a reload.
let garminLoginRestarted = false;

function credentialFieldIds(field) {
  return {
    input: `cred-${field}`,
    source: `cred-source-${field}`,
    current: `cred-current-${field}`,
    clear: `cred-clear-${field}`,
  };
}

function credentialFormIds(provider) {
  return { form: `cred-form-${provider}`, submit: `cred-submit-${provider}`, error: `cred-error-${provider}` };
}

// Pure projection of one status field: badge text, its tone and whether a DB value can be removed.
function credentialSourceView(entry) {
  const source = Object.hasOwn(CREDENTIAL_SOURCE_LABELS, entry?.source) ? entry.source : "none";
  return { source, label: CREDENTIAL_SOURCE_LABELS[source], removable: source === "db" };
}

// Pure: the body of a save. Blank inputs are left out, so they never clear a stored value.
function credentialSavePayload(values, fields) {
  const payload = {};
  for (const field of fields) {
    const text = typeof values?.[field] === "string" ? values[field].trim() : "";
    if (text) payload[field] = text;
  }
  return payload;
}

// Pure: Garmin card mode from garmin_connection, falling back to the legacy connected flag.
function garminCardView(connection, legacyConnected = false, { mfaHint = false, loginRestarted = false } = {}) {
  const connected = typeof connection?.connected === "boolean" ? connection.connected : Boolean(legacyConnected);
  if (connected) {
    const source = Object.hasOwn(GARMIN_SOURCE_LABELS, connection?.source) && connection.source !== "none" ? connection.source : "db";
    return { mode: "connected", status: "Verbunden", sourceLabel: GARMIN_SOURCE_LABELS[source] };
  }
  const mfa = !loginRestarted && (mfaHint || Boolean(connection?.mfa_pending));
  return {
    mode: mfa ? "mfa" : "login",
    status: mfa ? "Bestätigungscode von Garmin erforderlich" : "Nicht verbunden",
    sourceLabel: GARMIN_SOURCE_LABELS.none,
  };
}

function setCredentialText(id, text) {
  const node = $("#" + id);
  if (node) node.textContent = text;
}

function setCredentialHidden(id, hidden) {
  const node = $("#" + id);
  if (node) node.hidden = hidden;
}

function setCredentialError(id, message) {
  const node = $("#" + id);
  if (!node) return;
  node.textContent = message || "";
  node.hidden = !message;
}

function setProviderBusy(key, busy) {
  if (busy) providerCredentialBusy.add(key);
  else providerCredentialBusy.delete(key);
  renderProviderCredentials(state.data || {});
}

function renderCredentialField(field, fields, busy) {
  const ids = credentialFieldIds(field);
  const entry = fields[field];
  const view = credentialSourceView(entry);
  const source = $("#" + ids.source);
  if (source) {
    source.textContent = view.label;
    source.className = `credential-source is-${view.source}`;
  }
  const clear = $("#" + ids.clear);
  if (clear) {
    clear.hidden = !view.removable;
    clear.disabled = busy;
  }
  if (CREDENTIAL_VISIBLE_FIELDS.has(field)) {
    const value = typeof entry?.value === "string" ? entry.value : "";
    setCredentialText(ids.current, value ? `Aktuell: ${value}` : "");
  }
}

function renderGarminCard(data) {
  const busy = providerCredentialBusy.has(GARMIN_CARD);
  const view = garminCardView(data.credentials?.garmin_connection, Boolean(data.credentials?.garmin_connected), {
    mfaHint: garminMfaHint,
    loginRestarted: garminLoginRestarted,
  });
  setCredentialText("garmin-connection-status", view.status);
  setCredentialText("garmin-source", view.sourceLabel);
  setCredentialHidden("garmin-login-form", view.mode !== "login");
  setCredentialHidden("garmin-mfa-form", view.mode !== "mfa");
  setCredentialHidden("garmin-connected", view.mode !== "connected");
  for (const id of ["garmin-login-submit", "garmin-mfa-submit", "garmin-mfa-cancel", "garmin-disconnect"]) {
    const node = $("#" + id);
    if (node) node.disabled = busy;
  }
}

// Updates badges, current values and busy states from the bootstrap or public state.
// It never touches input values, so typing survives polling re-renders.
function renderProviderCredentials(data = {}) {
  const fields = data.credentials?.fields;
  for (const provider of Object.keys(CREDENTIAL_FORMS)) {
    const busy = providerCredentialBusy.has(provider);
    const submit = $("#" + credentialFormIds(provider).submit);
    if (submit) {
      submit.disabled = busy;
      submit.textContent = busy ? "Wird gespeichert…" : "Speichern";
    }
    // Without the credential status (older state), the badges keep their last text.
    if (!fields) continue;
    for (const field of CREDENTIAL_FORMS[provider]) renderCredentialField(field, fields, busy);
  }
  renderGarminCard(data);
}

// Keeps the provider's controls disabled for the whole request, including the reload.
async function runCredentialRequest(key, action) {
  setProviderBusy(key, true);
  try {
    await action();
  } finally {
    setProviderBusy(key, false);
  }
}

// Saves the non-blank fields of one provider form with a single PUT.
async function saveProviderCredentials(event, provider) {
  event.preventDefault();
  const fields = CREDENTIAL_FORMS[provider];
  const values = {};
  for (const field of fields) {
    const input = $("#" + credentialFieldIds(field).input);
    if (!input) continue;
    values[field] = input.value;
    // Cleared even when the save fails, so secrets never linger in the DOM.
    input.value = "";
  }
  const errorId = credentialFormIds(provider).error;
  const payload = credentialSavePayload(values, fields);
  if (Object.keys(payload).length === 0) {
    setCredentialError(errorId, "Bitte mindestens einen Wert eingeben.");
    return;
  }
  setCredentialError(errorId, "");
  try {
    await runCredentialRequest(provider, async () => {
      await api("/api/settings/credentials", { method: "PUT", body: JSON.stringify(payload) });
      toast("Zugangsdaten gespeichert");
      invalidateContextPreview();
      await load();
    });
  } catch (error) {
    setCredentialError(errorId, error.message);
  }
}

// Removes a value stored in the app; the environment value applies again afterwards.
async function clearProviderCredential(field, provider) {
  const label = CREDENTIAL_FIELD_LABELS[field];
  const confirmed = await requestConfirmation(
    `${label} aus der App entfernen? Danach gilt wieder der Wert aus der Serverumgebung, falls dort einer gesetzt ist.`,
    { title: `${label} entfernen?` },
  );
  if (!confirmed) return;
  try {
    await runCredentialRequest(provider, async () => {
      await api("/api/settings/credentials", { method: "PUT", body: JSON.stringify({ [field]: null }) });
      toast(`${label} entfernt`);
      invalidateContextPreview();
      await load();
    });
  } catch (error) {
    setCredentialError(credentialFormIds(provider).error, error.message);
  }
}

// The password is sent once and never stored; the server keeps only the Garmin tokens.
async function submitGarminLogin(event) {
  event.preventDefault();
  const emailInput = $("#garmin-email");
  const passwordInput = $("#garmin-password");
  const email = (emailInput?.value || "").trim();
  const password = passwordInput?.value || "";
  if (emailInput) emailInput.value = "";
  if (passwordInput) passwordInput.value = "";
  if (!email || !password) {
    setCredentialError("garmin-login-error", "Bitte E-Mail und Passwort eingeben.");
    return;
  }
  setCredentialError("garmin-login-error", "");
  garminLoginRestarted = false;
  try {
    await runCredentialRequest(GARMIN_CARD, async () => {
      const result = await api("/api/garmin/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
        timeoutMs: GARMIN_LOGIN_TIMEOUT_MS,
      });
      garminMfaHint = result?.status === "mfa_required";
      toast(garminMfaHint ? "Bitte den Bestätigungscode von Garmin eingeben" : "Garmin verbunden");
      await load();
    });
  } catch (error) {
    setCredentialError("garmin-login-error", error.message);
  } finally {
    renderProviderCredentials(state.data || {});
  }
}

async function submitGarminMfa(event) {
  event.preventDefault();
  const codeInput = $("#garmin-mfa-code");
  const code = (codeInput?.value || "").trim();
  if (codeInput) codeInput.value = "";
  if (!code) {
    setCredentialError("garmin-mfa-error", "Bitte den Bestätigungscode eingeben.");
    return;
  }
  setCredentialError("garmin-mfa-error", "");
  try {
    await runCredentialRequest(GARMIN_CARD, async () => {
      await api("/api/garmin/login/mfa", {
        method: "POST",
        body: JSON.stringify({ code }),
        timeoutMs: GARMIN_LOGIN_TIMEOUT_MS,
      });
      garminMfaHint = false;
      toast("Garmin verbunden");
      await load();
    });
  } catch (error) {
    if (error.status === 409) {
      // The server already discarded the pending login (expired, superseded or too
      // many wrong codes); return to the login form with the message.
      garminMfaHint = false;
      garminLoginRestarted = true;
      setCredentialError("garmin-mfa-error", "");
      setCredentialError("garmin-login-error", error.message);
      renderProviderCredentials(state.data || {});
    } else {
      setCredentialError("garmin-mfa-error", error.message);
    }
  }
}

// Leaves the MFA step for the login form. The server keeps the pending login until it
// expires (10 minutes) or the next login replaces it.
function cancelGarminMfa() {
  garminMfaHint = false;
  garminLoginRestarted = true;
  setCredentialError("garmin-mfa-error", "");
  renderProviderCredentials(state.data || {});
}

async function disconnectGarmin() {
  const confirmed = await requestConfirmation(
    "Garmin trennen? Die in der App gespeicherten Garmin-Tokens werden gelöscht. Bereits geladene Daten bleiben erhalten.",
    { title: "Garmin trennen?" },
  );
  if (!confirmed) return;
  try {
    await runCredentialRequest(GARMIN_CARD, async () => {
      await api("/api/garmin/disconnect", { method: "POST", body: "{}" });
      garminMfaHint = false;
      garminLoginRestarted = false;
      toast("Garmin getrennt");
      await load();
    });
  } catch (error) {
    toast(error.message, true);
  }
}

if (typeof module !== "undefined") {
  module.exports = {
    CREDENTIAL_FORMS,
    credentialFieldIds,
    credentialFormIds,
    credentialSavePayload,
    credentialSourceView,
    garminCardView,
  };
}
