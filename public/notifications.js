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

function competitionCountdownText(name, days) {
  if (days === 0) return `${name} ist heute.`;
  if (days === 1) return `${name} ist morgen.`;
  return `${name} ist in ${days} Tagen.`;
}

function notifyState(data) {
  const next = data.planning?.season?.next_event;
  if (next && next.days_until >= 0 && next.days_until <= 3) void showPwaNotification("Wettkampf steht bevor", { body: competitionCountdownText(next.name, next.days_until), tag: `competition:${next.id}` }, `competition:${next.id}:${next.event_date}`);
  const error = data.sync?.last_error || data.garmin_sync?.status?.includes("Fehler") && data.garmin_sync.status;
  if (error) void showPwaNotification("Intervals Coach benötigt Aufmerksamkeit", { body: String(error), tag: "sync-error" }, `error:${error}`);
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}
