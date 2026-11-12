// Provider credential forms in the Anbindungen section. Values are written through
// PUT /api/settings/credentials and the Garmin login routes. The server answers with
// status only, so the page never receives a secret back. Inputs are never prefilled
// and are cleared as soon as their values are taken for a request.

const CREDENTIAL_FORMS = Object.freeze({
  openai: Object.freeze(["openai_api_key", "openai_base_url"]),
  anthropic: Object.freeze(["anthropic_api_key", "anthropic_base_url"]),
  intervals: Object.freeze(["intervals_api_key", "intervals_athlete_id"]),
  garmin_personal: Object.freeze(["garmin_personal_api_key", "garmin_personal_api_key_expires"]),
  wahoo: Object.freeze(["wahoo_client_id", "wahoo_client_secret"]),
  yazio: Object.freeze(["yazio_email", "yazio_password"]),
});

// Setting one of these needs the APP_PASSWORD again; the password is sent once with the
// request and never stored. Only the OpenAI, Claude and Wahoo forms have the password input.
const CREDENTIAL_REAUTH_FIELDS = new Set(["openai_base_url", "anthropic_base_url", "wahoo_client_id", "wahoo_client_secret"]);

const CREDENTIAL_FIELD_LABELS = Object.freeze({
  openai_api_key: "OpenAI-API-Schlüssel",
  openai_base_url: "OpenAI-Basis-URL",
  anthropic_api_key: "Anthropic-API-Schlüssel",
  anthropic_base_url: "Anthropic-Basis-URL",
  intervals_api_key: "Intervals.icu-API-Schlüssel",
  intervals_athlete_id: "Intervals.icu-Athlete-ID",
  garmin_personal_api_key: "Garmin-Personal-API-Schlüssel",
  garmin_personal_api_key_expires: "Ablaufdatum des Garmin-Personal-API-Schlüssels",
  wahoo_client_id: "Wahoo-Client-ID",
  wahoo_client_secret: "Wahoo-Client-Secret",
  yazio_email: "Yazio-E-Mail",
  yazio_password: ["Yazio", "Passwort"].join("-"),
});

// Non-secret values the server echoes back; they are shown as the current value.
const CREDENTIAL_VISIBLE_FIELDS = new Set(["openai_base_url", "anthropic_base_url", "intervals_athlete_id", "wahoo_client_id", "garmin_personal_api_key_expires"]);

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

// Pure: whether a save payload sets a field that needs the APP_PASSWORD.
function credentialNeedsPassword(payload) {
  return Object.keys(payload || {}).some((field) => CREDENTIAL_REAUTH_FIELDS.has(field));
}

function credentialPasswordIds(provider) {
  return { row: `cred-password-row-${provider}`, input: `cred-app_password-${provider}` };
}

// Shows the password input only while a field that needs it is filled in.
function syncCredentialPasswordRow(provider) {
  const ids = credentialPasswordIds(provider);
  const row = $("#" + ids.row);
  if (!row) return;
  const values = {};
  for (const field of CREDENTIAL_FORMS[provider]) values[field] = $("#" + credentialFieldIds(field).input)?.value;
  const needed = credentialNeedsPassword(credentialSavePayload(values, CREDENTIAL_FORMS[provider]));
  row.hidden = !needed;
  const input = $("#" + ids.input);
  if (!needed && input) input.value = "";
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
  // Stored consent stays visible and revocable while Garmin is disconnected.
  setCredentialHidden("garmin-metric-export", view.mode !== "connected" && !data.garmin?.metric_export_enabled);
  for (const id of ["garmin-login-submit", "garmin-mfa-submit", "garmin-mfa-cancel", "garmin-disconnect"]) {
    const node = $("#" + id);
    if (node) node.disabled = busy;
  }
}

// Pure: consent text, toggle label and last sync receipt of the automatic Intervals.icu export.
function metricExportView(enabled, status) {
  return {
    text: enabled
      ? "Schwellenwerte aus lokalen Zonen, sonst Garmin, sonst Wahoo, überschreiben Intervals.icu; Körperwerte von Garmin."
      : "Schwellenwerte aus lokalen Zonen, sonst Garmin, sonst Wahoo, automatisch an Intervals.icu senden.",
    button: enabled ? "Automatischen Abgleich deaktivieren" : "Werte automatisch an Intervals.icu senden",
    status: status || "",
  };
}

function renderMetricExport(garmin) {
  const view = metricExportView(Boolean(garmin?.metric_export_enabled), garmin?.metric_export_status);
  setCredentialText("garmin-metric-export-text", view.text);
  setCredentialText("garmin-metric-export-toggle", view.button);
  setCredentialText("garmin-metric-export-status", view.status);
  setCredentialHidden("garmin-metric-export-status", !view.status);
  renderMetricExportFields(garmin);
}

// Pure: one checkbox per exportable field, shown only while the export is enabled.
function metricExportFieldsView(enabled, fields) {
  return enabled ? (fields || []).map((item) => ({ key: item.key, label: item.label, checked: Boolean(item.enabled) })) : [];
}

// Pure: the receipt of a consent change, one entry per changed field.
function metricExportReceipt(receipt) {
  const changes = (receipt?.changes || []).map((item) => item.label + (item.enabled ? " an" : " aus"));
  return "Intervals.icu-Abgleich: " + (changes.length ? changes.join(", ") : "keine Änderung");
}

// Rebuilds the checkboxes only when the field list changes; otherwise it updates
// them in place, so polling and saved changes keep keyboard focus.
let metricExportFieldsKeys = "";
const metricExportInputs = new Map();
let metricExportFieldsBusy = false;
function renderMetricExportFields(garmin) {
  const node = $("#garmin-metric-export-fields");
  if (!node) return;
  const items = metricExportFieldsView(Boolean(garmin?.metric_export_enabled), garmin?.metric_export_fields);
  node.hidden = !items.length;
  const keys = items.map((item) => `${item.key}:${item.label}`).join("|");
  if (metricExportFieldsKeys !== keys) {
    metricExportFieldsKeys = keys;
    metricExportInputs.clear();
    node.replaceChildren(...items.map((item) => {
      const label = document.createElement("label");
      label.className = "garmin-metric-export-field";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.addEventListener("change", () => void changeMetricExportField(item, input));
      metricExportInputs.set(item.key, input);
      label.append(input, document.createTextNode(item.label));
      return label;
    }));
  }
  if (metricExportFieldsBusy) return;
  for (const item of items) {
    const input = metricExportInputs.get(item.key);
    if (input) input.checked = item.checked;
  }
}

function setMetricExportFieldsBusy(busy) {
  metricExportFieldsBusy = busy;
  for (const input of metricExportInputs.values()) input.disabled = busy;
}

// Each field change names the field and the target, and is confirmed first.
// The server applies the one change to the stored consent; all boxes wait for the reload.
async function changeMetricExportField(item, input) {
  const enabled = input.checked;
  const remaining = (state.data?.garmin?.metric_export_fields || [])
    .filter((field) => field.enabled && field.key !== item.key).length;
  let message = `${item.label} künftig automatisch an Intervals.icu senden?`;
  if (!enabled) {
    message = `${item.label} nicht mehr automatisch an Intervals.icu senden?`;
    if (!remaining) message += " Damit endet der automatische Abgleich.";
  }
  setMetricExportFieldsBusy(true);
  try {
    if (!await requestConfirmation(message, { title: "Intervals.icu-Abgleich" })) {
      input.checked = !enabled;
      return;
    }
    const body = { enabled: true, field: item.key, field_enabled: enabled, confirmed: true, source: providerIds().garmin, provider: providerIds().intervals };
    toast(metricExportReceipt(await api("/api/metric-export/automatic", { method: "POST", body: JSON.stringify(body) })));
    await load();
  } catch (error) {
    input.checked = !enabled;
    toast(error.message, true);
  } finally { setMetricExportFieldsBusy(false); }
}

// The toggle reads the last loaded state; the confirmation and the POST live in configureAutomaticMetricExport.
function toggleMetricExport(button) {
  void configureAutomaticMetricExport(!state.data?.garmin?.metric_export_enabled, button);
}

async function configureAutomaticMetricExport(enabled, button) {
  const message = enabled
    ? "Schwellenpuls (LSHF), maximale HF und Lauf-Schwellenpace künftig automatisch an Intervals.icu senden (lokale Zonen, sonst Garmin, sonst Wahoo)? Abweichende Werte dort werden überschrieben, die HF-Zonen neu berechnet."
    : "Den automatischen Abgleich mit Intervals.icu deaktivieren?";
  if (!await requestConfirmation(message, { title: enabled ? "Automatischen Abgleich aktivieren?" : "Automatischen Abgleich deaktivieren?" })) return;
  button.disabled = true;
  try {
    const receipt = await api("/api/metric-export/automatic", { method: "POST", body: JSON.stringify({ enabled, confirmed: true, source: providerIds().garmin, provider: providerIds().intervals }) });
    toast(metricExportReceipt(receipt));
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
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
  renderMetricExport(data.garmin);
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
  const errorId = credentialFormIds(provider).error;
  const passwordInput = $("#" + credentialPasswordIds(provider).input);
  const clearInputs = () => {
    for (const field of fields) {
      const input = $("#" + credentialFieldIds(field).input);
      if (input) input.value = "";
    }
    if (passwordInput) passwordInput.value = "";
    syncCredentialPasswordRow(provider);
  };
  for (const field of fields) {
    const input = $("#" + credentialFieldIds(field).input);
    if (input) values[field] = input.value;
  }
  const payload = credentialSavePayload(values, fields);
  if (credentialNeedsPassword(payload) && !passwordInput?.value) {
    // Nothing is sent, so the entries stay for the next try.
    setCredentialError(errorId, "Bitte das App-Passwort eingeben.");
    return;
  }
  if (credentialNeedsPassword(payload)) payload.app_password = passwordInput.value;
  // Cleared even when the save fails, so secrets never linger in the DOM.
  clearInputs();
  if (Object.keys(payload).length === 0) {
    setCredentialError(errorId, "Bitte mindestens einen Wert eingeben.");
    return;
  }
  setCredentialError(errorId, "");
  if (provider === "yazio") invalidateYazioStatus();
  else invalidateProviderChecks(provider);
  try {
    await runCredentialRequest(provider, async () => {
      await api("/api/settings/credentials", { method: "PUT", body: JSON.stringify(payload) });
      toast("Zugangsdaten gespeichert");
      invalidateContextPreview();
      await load();
    });
  } catch (error) {
    setCredentialError(errorId, error.message);
  } finally {
    if (provider === "yazio") await loadYazioStatus();
    else await loadProviderChecks();
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
  if (provider === "yazio") invalidateYazioStatus();
  else invalidateProviderChecks(provider);
  try {
    await runCredentialRequest(provider, async () => {
      await api("/api/settings/credentials", { method: "PUT", body: JSON.stringify({ [field]: null }) });
      toast(`${label} entfernt`);
      invalidateContextPreview();
      await load();
    });
  } catch (error) {
    setCredentialError(credentialFormIds(provider).error, error.message);
  } finally {
    if (provider === "yazio") await loadYazioStatus();
    else await loadProviderChecks();
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
      invalidateProviderChecks(GARMIN_CARD);
      void loadProviderChecks();
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
      invalidateProviderChecks(GARMIN_CARD);
      void loadProviderChecks();
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
      invalidateProviderChecks(GARMIN_CARD);
      void loadProviderChecks();
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
    credentialNeedsPassword,
    credentialPasswordIds,
    credentialSavePayload,
    credentialSourceView,
    garminCardView,
  };
}

let yazioStatusGeneration = 0;

function invalidateYazioStatus() {
  yazioStatusGeneration += 1;
  providerCredentialBusy.delete("yazio-check");
  renderYazioStatus(null);
}

function renderYazioStatus(result) {
  const messages = {
    unchecked: "Noch nicht geprüft",
    success: "Anmeldung erfolgreich", auth_failed: "Anmeldung abgelehnt – Zugangsdaten und App-Konfiguration prüfen",
    rate_limited: "Anfragen begrenzt – später erneut versuchen", unavailable: "Momentan nicht verfügbar – später erneut versuchen",
  };
  setConnectionChip("#yazioConnectionStatus", yazioConnectionKind(result?.status));
  const date = result?.checked_at ? new Date(result.checked_at) : null;
  const checked = date && !Number.isNaN(date.getTime()) ? `Geprüft: ${date.toLocaleString("de-DE")}` : "";
  const message = result ? messages[result.status] : "Status nicht verfügbar";
  setCredentialText("yazioConnectionDetail", [message, checked].filter(Boolean).join(" · "));
  const button = $("#yazioCheckButton");
  if (button) button.disabled = providerCredentialBusy.has("yazio-check") || result?.status === "not_configured";
}

async function loadYazioStatus() {
  if (providerCredentialBusy.has("yazio") || providerCredentialBusy.has("yazio-check")) return;
  const generation = ++yazioStatusGeneration;
  let result = null;
  try { result = await api("/api/nutrition/yazio/status"); }
  catch { /* Do not display response bodies. */ }
  if (generation === yazioStatusGeneration) renderYazioStatus(result);
}

async function checkYazioConnection() {
  if (providerCredentialBusy.has("yazio")) return;
  const generation = ++yazioStatusGeneration;
  providerCredentialBusy.add("yazio-check");
  const button = $("#yazioCheckButton");
  if (button) button.disabled = true;
  let result = null;
  try { result = await api("/api/nutrition/yazio/check", { method: "POST", body: "{}" }); }
  catch { /* Show an unavailable status without exposing an error body. */ }
  finally {
    if (generation === yazioStatusGeneration) {
      providerCredentialBusy.delete("yazio-check");
      renderYazioStatus(result);
    }
  }
}
