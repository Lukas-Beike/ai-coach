// Explicit connection checks for the provider cards in the Anbindungen section.
// A check result says whether the credentials were accepted at one moment. It is
// separate from the configuration and sync labels above it. Passive loads read
// local server state only; the button is the only trigger of a provider request.
// Cards are found by data-check-button / data-check-result; the server supplies
// the recovery guidance for rejected credentials.

const PROVIDER_CHECK_TEXT = Object.freeze({
  not_configured: "Verbindung: nicht konfiguriert",
  unchecked: "Verbindung: nicht geprüft",
  success: "Verbindung erfolgreich",
  rate_limited: "Anfragen begrenzt – später erneut prüfen",
  unavailable: "Dienst nicht erreichbar – später erneut prüfen",
  unsupported: "Dieser Endpunkt unterstützt die Prüfung nicht",
  scope_missing: "Berechtigung fehlt – Wahoo neu verbinden",
  auth_failed: "Anmeldung abgelehnt",
  misconfigured: "Konfiguration ungültig – Einstellungen prüfen",
  busy: "Synchronisierung läuft – später prüfen",
  checking: "Verbindung wird geprüft…",
  refreshing: "Verbindung: Status wird geladen…",
  unknown: "Verbindungsstatus nicht lesbar – erneut versuchen",
});
const PROVIDER_CHECK_FAILURES = new Set(["auth_failed", "rate_limited", "unavailable", "unsupported", "misconfigured", "unknown", "scope_missing"]);

// Pure: text, tone and button state for one provider's last check result.
function providerCheckView(result, busy = false) {
  const status = typeof result?.status === "string" ? result.status : "";
  let text = PROVIDER_CHECK_TEXT[status] || "Verbindung: Status nicht verfügbar";
  if (status === "auth_failed" && typeof result.guidance === "string" && result.guidance) text = result.guidance;
  const date = result?.checked_at ? new Date(result.checked_at) : null;
  const time = date && !Number.isNaN(date.getTime()) ? date.toLocaleString("de-DE") : "";
  return {
    text: time ? `${text} · ${time}` : text,
    failed: PROVIDER_CHECK_FAILURES.has(status),
    disabled: busy || status === "not_configured" || status === "refreshing" || status === "checking",
  };
}

const PROVIDER_CHECK_POLL_MS = 3000;
// One pending poll at a time, however many loads complete meanwhile.
let providerCheckPoll = null;
let providerCheckPolls = 0;
const PROVIDER_CHECK_MAX_POLLS = 60;

function connectionsVisible() {
  return document.visibilityState !== "hidden"
    && Boolean(document.querySelector('details[data-more-segment-panel="connections"]')?.open);
}
const providerCheckResults = new Map();
const providerCheckBusy = new Set();
// Bumped when credentials change, so an in-flight answer for the old ones is dropped.
let providerCheckEpoch = 0;
let providerCheckLoad = 0;
// Per provider: bumped by every explicit check, so an older status read cannot overwrite it.
const providerCheckStamp = new Map();

function providerCheckIds() {
  return [...document.querySelectorAll("[data-check-button]")].map((node) => node.dataset.checkButton);
}

function renderProviderCheck(provider) {
  const busy = providerCheckBusy.has(provider);
  const view = providerCheckView(providerCheckResults.get(provider), busy);
  const result = document.querySelector(`[data-check-result="${provider}"]`);
  if (result) {
    result.textContent = busy ? "Verbindung wird geprüft…" : view.text;
    result.classList.toggle("error", view.failed && !busy);
  }
  const button = document.querySelector(`[data-check-button="${provider}"]`);
  if (button) button.disabled = view.disabled;
}

function renderProviderChecks() {
  for (const provider of providerCheckIds()) renderProviderCheck(provider);
}

// Reads local state only. A response that arrives after a newer load is ignored.
async function loadProviderChecks() {
  const load = ++providerCheckLoad;
  const epoch = providerCheckEpoch;
  const stamps = new Map(providerCheckStamp);
  let payload = null;
  try { payload = await api("/api/providers/connections"); }
  catch { /* Never show response bodies. */ }
  if (load !== providerCheckLoad || epoch !== providerCheckEpoch) return;
  // A failed read keeps earlier results; only a pending refresh falls back to "unavailable".
  const providers = payload?.providers || {};
  for (const provider of providerCheckIds()) {
    if (providerCheckBusy.has(provider) || providerCheckStamp.get(provider) !== stamps.get(provider)) continue;
    if (providers[provider]) providerCheckResults.set(provider, providers[provider]);
    else if (providerCheckResults.get(provider)?.status === "refreshing") providerCheckResults.set(provider, null);
  }
  renderProviderChecks();
  // A check still running on the server finishes later; read again until it has.
  clearTimeout(providerCheckPoll);
  providerCheckPoll = null;
  const running = [...providerCheckResults.values()].some((result) => result?.status === "checking");
  // Poll only while someone can see the card, and for a bounded time.
  if (running && providerCheckPolls < PROVIDER_CHECK_MAX_POLLS && connectionsVisible()) {
    providerCheckPolls += 1;
    providerCheckPoll = setTimeout(() => void loadProviderChecks(), PROVIDER_CHECK_POLL_MS);
  } else if (!running) {
    providerCheckPolls = 0;
  }
}

// Called when credentials change; the server then reports the affected providers as not yet
// checked. A button belongs to the groups named in data-check-group (default: its own id);
// without arguments every provider is reset.
function invalidateProviderChecks(...groups) {
  providerCheckEpoch += 1;
  for (const button of document.querySelectorAll("[data-check-button]")) {
    const own = new Set((button.dataset.checkGroup || button.dataset.checkButton).split(" "));
    if (groups.length && !groups.some((group) => own.has(group))) continue;
    providerCheckResults.set(button.dataset.checkButton, { status: "refreshing", checked_at: null });
  }
  renderProviderChecks();
}

async function checkProviderConnection(provider) {
  if (providerCheckBusy.has(provider)) return;
  const epoch = providerCheckEpoch;
  providerCheckStamp.set(provider, (providerCheckStamp.get(provider) || 0) + 1);
  providerCheckBusy.add(provider);
  renderProviderCheck(provider);
  let result = null;
  // The server bounds each check at 45 s; give the request more room than that.
  try { result = await api(`/api/providers/${provider}/check`, { method: "POST", body: "{}", timeoutMs: 60_000 }); }
  catch { toast("Verbindungsprüfung nicht möglich", true); }
  providerCheckBusy.delete(provider);
  providerCheckStamp.set(provider, (providerCheckStamp.get(provider) || 0) + 1);
  const transient = result?.status === "busy" || result?.status === "checking";
  if (transient) {
    // Nothing was checked: keep the earlier result and say why.
    toast(PROVIDER_CHECK_TEXT[result.status], false);
    if (!providerCheckResults.get(provider)) providerCheckResults.set(provider, { status: "unchecked", checked_at: null });
    void loadProviderChecks();
  } else if (epoch === providerCheckEpoch && result) {
    providerCheckResults.set(provider, result);
    // The result line is not a live region (passive loads would announce too much).
    const view = providerCheckView(result);
    toast(view.text, view.failed);
  }
  renderProviderCheck(provider);
  // An aborted or superseded request may still have changed the server state.
  if (!result || epoch !== providerCheckEpoch) void loadProviderChecks();
}

// Reads the status when the connections panel is already open (start, re-login).
function refreshOpenProviderChecks() {
  if (document.querySelector('details[data-more-segment-panel="connections"]')?.open) void loadProviderChecks();
}

function bindProviderChecks() {
  for (const button of document.querySelectorAll("[data-check-button]")) {
    button.addEventListener("click", () => checkProviderConnection(button.dataset.checkButton));
  }
}

if (typeof module !== "undefined") module.exports = { providerCheckView };
