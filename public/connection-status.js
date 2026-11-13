// Connection status of the providers in Mehr > Anbindungen: one card per provider
// whose summary names its status in a text chip (never colour alone), and the
// Garmin Personal API key / SDK login lines.

const CONNECTION_CHIPS = Object.freeze({
  ok: "Verbunden",
  off: "Nicht eingerichtet",
  error: "Fehler",
  unchecked: "Nicht geprüft",
});

// Mehr › Anbindungen is the shown route ("more" alone lands there too).
function connectionsShown() {
  return globalThis.AppRouter?.baseRoute() === "more" && AppRouter.moreSegmentFromRoute() === "connections";
}

// Opens one provider card, focuses its summary and brings it into view after the route has scrolled to the top.
function openConnectionCard(provider) {
  const card = document.getElementById(`connection-${provider}`);
  if (!card) return;
  card.open = true;
  card.querySelector("summary")?.focus({ preventScroll: true });
  requestAnimationFrame(() => card.scrollIntoView({ block: "start" }));
}

// The full-resync button of every provider: label, disabled state and pulse all follow the running state.
function renderFullResyncButton(button, { running, blocked = false, idleLabel }) {
  button.classList.toggle("busy", running);
  button.disabled = running || blocked;
  button.textContent = running ? "Vollständiger Resync läuft…" : idleLabel;
}

// Pure: chip kind of a provider that is either set up or not, with an optional error.
function connectionKind({ configured, error = false, unchecked = false }) {
  if (!configured) return "off";
  if (error) return "error";
  return unchecked ? "unchecked" : "ok";
}

const INTERVALS_CHIP_KINDS = Object.freeze({
  not_configured: "off",
  error: "error",
  configured: "unchecked",
});

// Pure: Intervals.icu is an output target; "configured" only means a key exists.
function intervalsConnectionKind(intervals) {
  if (!intervals?.configured) return "off";
  return INTERVALS_CHIP_KINDS[intervals.state] || "ok";
}

const YAZIO_CHIP_KINDS = Object.freeze({
  not_configured: "off",
  success: "ok",
  auth_failed: "error",
  rate_limited: "error",
  unavailable: "error",
});

function yazioConnectionKind(status) {
  return YAZIO_CHIP_KINDS[status] || "unchecked";
}

const GARMIN_KEY_LINES = Object.freeze({
  valid: "gültig",
  expiring: "läuft bald ab",
  expired: "abgelaufen",
  rejected: "abgelehnt",
  expiry_missing: "Ablaufdatum fehlt",
});

// Pure: Garmin chip. The Personal API key and the SDK login are two ways in; a
// rejected or expired key, or a failed sync, is an error.
function garminConnectionKind(garmin) {
  if (garmin?.available === false || !garmin?.configured) return "off";
  const keyState = garmin.personal_api?.state;
  return connectionKind({ configured: true, error: Boolean(garmin.last_error) || ["rejected", "expired"].includes(keyState) });
}

// Pure: the status lines under the Garmin name. Each way in states its own state
// in words, so the card reads without colour.
function garminSourceLines(garmin, sdkConnected) {
  const lines = [];
  const key = garmin?.personal_api;
  if (key?.configured) {
    const label = GARMIN_KEY_LINES[key.state] || "gespeichert";
    const until = key.state === "valid" && key.expires_on ? `${label} bis ${globalThis.AppFormat?.date?.(key.expires_on) ?? key.expires_on}` : label;
    lines.push({ label: "Personal API", text: until });
  } else lines.push({ label: "Personal API", text: "nicht eingerichtet" });
  if (garmin?.sdk_skipped) lines.push({ label: "SDK-Login", text: "erneuern" });
  else lines.push({ label: "SDK-Login", text: sdkConnected ? "aktiv" : "nicht eingerichtet" });
  return lines;
}

// #2443: a configured but not yet used Intervals.icu or Claude card takes its chip
// from the last explicit check of its card's check button.
const CHECKED_CONNECTION_CHIPS = Object.freeze(["#intervalsConnectionStatus", "#anthropicConnectionStatus"]);

function setConnectionChip(selector, kind) {
  const node = document.querySelector(selector);
  if (!node) return;
  const checked = CHECKED_CONNECTION_CHIPS.includes(selector);
  if (checked) node.dataset.base = kind;
  const provider = checked ? node.closest(".connection-card")?.querySelector("[data-check-button]")?.dataset.checkButton : "";
  const shown = provider ? checkedConnectionKind(kind, providerCheckResults.get(provider)) : kind;
  const chip = Object.hasOwn(CONNECTION_CHIPS, shown) ? shown : "unchecked";
  node.textContent = CONNECTION_CHIPS[chip];
  node.className = `connection-chip is-${chip}`;
  node.dataset.state = chip;
}

if (typeof module !== "undefined") {
  module.exports = { CONNECTION_CHIPS, connectionKind, intervalsConnectionKind, yazioConnectionKind, garminConnectionKind, garminSourceLines };
}
