// Connection status of the providers in Mehr > Anbindungen: one text chip per
// provider (never colour alone), a count line for the collapsed section, and the
// Garmin Personal API key / SDK login lines.

const CONNECTION_CHIPS = Object.freeze({
  ok: "Verbunden",
  off: "Nicht eingerichtet",
  error: "Fehler",
  unchecked: "Nicht geprüft",
});

const CONNECTION_COUNT_LABELS = Object.freeze({
  ok: "verbunden",
  error: "Fehler",
  unchecked: "nicht geprüft",
  off: "nicht eingerichtet",
});

// Pure: "5 verbunden · 1 Fehler" from the chip counts, empty when no chip has reported.
function connectionsSummaryText(counts) {
  return Object.keys(CONNECTION_COUNT_LABELS)
    .filter((kind) => counts?.[kind] > 0)
    .map((kind) => `${counts[kind]} ${CONNECTION_COUNT_LABELS[kind]}`)
    .join(" · ");
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

function setConnectionChip(selector, kind) {
  const node = document.querySelector(selector);
  if (!node) return;
  const chip = Object.hasOwn(CONNECTION_CHIPS, kind) ? kind : "unchecked";
  node.textContent = CONNECTION_CHIPS[chip];
  node.className = `connection-chip is-${chip}`;
  node.dataset.state = chip;
  refreshConnectionsSummary();
}

function refreshConnectionsSummary() {
  const summary = document.querySelector("#connectionsSummary");
  if (!summary) return;
  const counts = {};
  document.querySelectorAll(".connection-cards .connection-chip[data-state]").forEach((chip) => {
    counts[chip.dataset.state] = (counts[chip.dataset.state] || 0) + 1;
  });
  summary.textContent = connectionsSummaryText(counts) || "Status wird geprüft…";
}

if (typeof module !== "undefined") {
  module.exports = { CONNECTION_CHIPS, connectionsSummaryText, connectionKind, intervalsConnectionKind, yazioConnectionKind, garminConnectionKind, garminSourceLines };
}
