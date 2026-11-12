function notificationPermission() {
  return "Notification" in globalThis ? Notification.permission : "unsupported";
}

function renderNotificationStatus() {
  const node = $("#notificationStatus");
  const button = $("#notificationEnableButton");
  const permission = notificationPermission();
  if (!node || !button) return;
  if (permission === "granted") node.textContent = "Aktiv";
  else if (permission === "denied") node.textContent = "Im Browser blockiert";
  else if (permission === "unsupported") node.textContent = "Von diesem Browser nicht unterstützt";
  else node.textContent = "Noch nicht aktiviert";
  button.hidden = permission === "granted";
  button.disabled = permission === "unsupported";
  button.textContent = "Benachrichtigungen aktivieren";
}

async function enableNotifications() {
  if (!("Notification" in globalThis)) { toast("Dieser Browser unterstützt keine PWA-Benachrichtigungen", true); return; }
  const permission = await Notification.requestPermission();
  renderNotificationStatus();
  if (permission === "granted") toast("PWA-Benachrichtigungen aktiviert");
}

const NOTIFICATION_MAX_ATTEMPTS = 3;
const NOTIFICATION_RETRY_DELAY_MS = 30000;

function reserveNotificationAttempt(key) {
  state.notificationAttempts ??= new Map();
  const previous = state.notificationAttempts.get(key) ?? { count: 0, at: 0 };
  if (previous.count >= NOTIFICATION_MAX_ATTEMPTS) {
    state.notificationKeys.add(key);
    return false;
  }
  if (previous.count > 0 && Date.now() - previous.at < NOTIFICATION_RETRY_DELAY_MS) return false;
  state.notificationAttempts.set(key, { count: previous.count + 1, at: Date.now() });
  return true;
}

async function showPwaNotification(title, options, key) {
  if (notificationPermission() !== "granted" || state.notificationKeys.has(key)) return;
  if (!reserveNotificationAttempt(key)) return;
  state.notificationKeys.add(key);
  try {
    const registration = await navigator.serviceWorker.ready;
    await registration.showNotification(title, { icon: "/icon.svg", badge: "/icon.svg", ...options });
  } catch {
    state.notificationKeys.delete(key);
  }
}

// Notification bodies can be shown on a locked screen, so they carry no competition names or provider error text.
function competitionCountdownText(days) {
  if (days === 0) return "Der Wettkampf ist heute.";
  if (days === 1) return "Der Wettkampf ist morgen.";
  return `Der Wettkampf ist in ${days} Tagen.`;
}

function notifyState(data) {
  const next = data.planning?.season?.next_event;
  if (next && next.days_until >= 0 && next.days_until <= 3) void showPwaNotification("Wettkampf steht bevor", { body: competitionCountdownText(next.days_until), tag: `competition:${next.id}` }, `competition:${next.id}:${next.event_date}`);
  const error = data.sync?.last_error || data.garmin_sync?.status?.includes("Fehler") && data.garmin_sync.status;
  if (error) void showPwaNotification("Pacecraft benötigt Aufmerksamkeit", { body: "Eine Synchronisierung ist fehlgeschlagen. Details stehen in der App.", tag: "sync-error" }, `error:${error}`);
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  // The first install also takes control of the page; only a replaced worker brings new assets.
  const replacesWorker = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!replacesWorker) return;
    serviceWorkerReplaced = true;
    reloadForUpdateWhenSafe();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") reloadForUpdateWhenSafe();
  });
  trackUnsavedForms();
  // Leaving a field may end the last edit; focus moves on after focusout. A pointer
  // press on a save button must reach its click first, so the check waits a frame
  // after the press ends.
  document.addEventListener("focusout", () => { if (!pointerHeld) requestAnimationFrame(reloadForUpdateWhenSafe); });
  document.addEventListener("pointerdown", () => { pointerHeld = true; }, true);
  for (const type of ["pointerup", "pointercancel"]) document.addEventListener(type, () => { pointerHeld = false; setTimeout(() => requestAnimationFrame(reloadForUpdateWhenSafe), 0); }, true);
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

// A replaced service worker serves the new assets, so the page reloads once to run
// them, but only while nothing would be lost. Otherwise the reload waits for the
// next check: when a chat or load state ends, or when the page is hidden.
let serviceWorkerReplaced = false;
let serviceWorkerReloaded = false;
let pointerHeld = false;

// Any form the athlete typed into counts as unsaved until it is submitted or reset.
function trackUnsavedForms() {
  document.addEventListener("input", (event) => {
    const scope = event.isTrusted && event.target.closest?.("form:not(#chatForm), #garminSyncDays");
    if (scope) scope.dataset.dirty = "1";
  });
  // A submitted form stays unsaved until the server confirms a change, so a rejected save keeps its input.
  document.addEventListener("submit", (event) => { if (event.target.dataset) event.target.dataset.saving = "1"; });
  document.addEventListener("reset", (event) => { delete event.target.dataset?.dirty; });
  globalThis.addEventListener("pacecraft:saved", () => {
    for (const form of document.querySelectorAll("form[data-saving]")) { delete form.dataset.dirty; delete form.dataset.saving; }
  });
}

// An edited form counts unless it sits in a closed dialog (cancelled or dismissed).
function editedFormPending() {
  return [...document.querySelectorAll("form[data-dirty], #garminSyncDays[data-dirty]")].some((field) => !field.closest?.("dialog:not([open])"));
}

// Settings fields that start empty, so any value in them is still being entered.
const UPDATE_RELOAD_INPUT_FIELDS = "#cred-form-openai input, #cred-form-anthropic input, #cred-form-intervals input, #cred-form-wahoo input, #cred-form-garmin_personal input, #garmin-login-form input, #garmin-mfa-form input, #nutritionProductQuery";

function pageInputPending() {
  const active = document.activeElement;
  return Boolean(active?.matches?.("input, textarea, select") && !active.closest?.("#chatForm"))
    || [...document.querySelectorAll(UPDATE_RELOAD_INPUT_FIELDS)].some((field) => field.value.trim())
    || (typeof providerCredentialBusy !== "undefined" && providerCredentialBusy.size > 0)
    || Boolean($("#calendarDisplaySaveButton")?.disabled)
    || editedFormPending()
    || Boolean($("#nutritionExtraction") && !$("#nutritionExtraction").hidden && $("#nutritionExtraction").childElementCount);
}

function updateReloadIsSafe() {
  return !hasUnsavedChanges() && !pageInputPending()
    && !(state.chatAttachments || []).length && !state.chatAttachmentsLoading
    && !chatStatusJobActive() && !voiceIsRecording() && !state.voiceTranscribing
    && !state.loadPromise && !$("#backupRestoreButton")?.disabled && !$("dialog[open]");
}

function reloadForUpdateWhenSafe() {
  if (!serviceWorkerReplaced || serviceWorkerReloaded || !updateReloadIsSafe()) return;
  serviceWorkerReloaded = true;
  location.reload();
}
