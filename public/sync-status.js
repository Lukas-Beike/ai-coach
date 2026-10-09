function scheduleStateEventRefresh(areas) {
  (areas || []).forEach((area) => state.stateEventRefreshAreas.add(area));
  if (state.stateEventRefreshTimer) clearTimeout(state.stateEventRefreshTimer);
  state.stateEventRefreshTimer = setTimeout(() => {
    state.stateEventRefreshTimer = null;
    const requested = [...state.stateEventRefreshAreas];
    state.stateEventRefreshAreas.clear();
    // A state event can arrive while a domain refresh is in flight. Keep the
    // requested areas queued instead of silently coalescing them into that
    // older request.
    if (state.loadPromise) {
      requested.forEach((area) => state.stateEventRefreshAreas.add(area));
      scheduleStateEventRefresh([]);
      return;
    }
    load("/api/bootstrap?local=1", requested).catch(() => {});
  }, 400);
}

function handleStateEvent(event) {
  if (event.lastEventId) state.stateEventLastId = Number(event.lastEventId) || state.stateEventLastId;
  let payload = {};
  try { payload = JSON.parse(event.data || "{}"); } catch (_) { return; }
  if (payload.latest_event_id !== undefined) state.stateEventLastId = Number(payload.latest_event_id) || state.stateEventLastId;
  if (event.type === "reset") {
    scheduleStateEventRefresh(["chat", "plan", "library", "performance", "feedback", "profile"]);
    return;
  }
  const areas = {
    coach: ["chat"],
    planning: ["plan", "library"],
    provider: (() => {
      if (payload.status === "loading") return [];
      return payload.area === "performance" ? ["performance"] : ["plan", "performance"];
    })(),
    job: [],
    sync: ["plan", "performance", "library"],
  }[event.type];
  if (event.type === "sync" && !["completed", "error"].includes(payload.status)) return;
  if (areas?.length) scheduleStateEventRefresh(areas);
}

function scheduleStateEventReconnect() {
  if (state.stateEventReconnectTimer || !state.data || !navigator.onLine || document.visibilityState !== "visible") return;
  const delay = state.stateEventBackoff;
  state.stateEventBackoff = Math.min(state.stateEventBackoff * 2, 30_000);
  state.stateEventReconnectTimer = setTimeout(() => {
    state.stateEventReconnectTimer = null;
    connectStateEvents();
  }, delay);
}

function disconnectStateEvents() {
  const source = state.stateEventSource;
  state.stateEventSource = null;
  source?.close();
  if (state.stateEventReconnectTimer) clearTimeout(state.stateEventReconnectTimer);
  state.stateEventReconnectTimer = null;
}

function connectStateEvents() {
  if (!state.data || !("EventSource" in globalThis) || state.stateEventSource || state.stateEventReconnectTimer
      || !navigator.onLine || document.visibilityState !== "visible") return;
  const source = new EventSource(`/api/state/events?since=${encodeURIComponent(state.stateEventLastId)}`, { withCredentials: true });
  state.stateEventSource = source;
  let openedAt = null;
  source.onopen = () => { if (state.stateEventSource === source) openedAt = performance.now(); };
  ["provider", "job", "planning", "coach", "sync", "reset"].forEach((name) => source.addEventListener(name, handleStateEvent));
  source.onerror = () => {
    if (state.stateEventSource !== source) return;
    // Receiving headers does not prove a stable stream: a proxy or browser
    // can repeatedly disconnect immediately afterward. Preserve the backoff
    // until a connection has actually stayed open for at least 30 seconds.
    if (openedAt !== null && performance.now() - openedAt >= 30_000) state.stateEventBackoff = 1000;
    disconnectStateEvents();
    scheduleStateEventReconnect();
  };
}

function syncPollLeaseAvailable() {
  try {
    const current = JSON.parse(localStorage.getItem(SYNC_POLL_LEASE_KEY) || "null");
    if (current && current.expires_at > Date.now() && current.token !== state.syncPoll.leaseToken) return false;
    const lease = { token: state.syncPoll.leaseToken, expires_at: Date.now() + SYNC_POLL_LEASE_MS };
    localStorage.setItem(SYNC_POLL_LEASE_KEY, JSON.stringify(lease));
    const verified = JSON.parse(localStorage.getItem(SYNC_POLL_LEASE_KEY) || "null");
    return verified?.token === state.syncPoll.leaseToken;
  } catch {
    // Deliberately ignore storage-access exceptions: privacy settings can deny
    // localStorage, and sync must remain available without the optional lease.
    return true;
  }
}

function releaseSyncPollLease() {
  try {
    const current = JSON.parse(localStorage.getItem(SYNC_POLL_LEASE_KEY) || "null");
    if (current?.token === state.syncPoll.leaseToken) localStorage.removeItem(SYNC_POLL_LEASE_KEY);
  } catch { }
}

function broadcastSyncMessage(message) {
  try { state.syncPoll.channel?.postMessage(message); } catch { }
}

function changedSyncAreas(nextVersions) {
  const previous = state.data?.state_versions || {};
  const areaMap = {
    activities: ["plan", "performance"],
    performance: ["performance", "plan"],
    garmin: ["performance", "plan"],
    chat: ["chat"],
    library: ["library", "plan"],
    checkins: ["feedback", "plan"],
    activity_feedback: ["feedback", "plan"],
    profile: ["profile"],
    plan: ["plan"],
  };
  const areas = new Set();
  Object.entries(areaMap).forEach(([version, mappedAreas]) => {
    if (nextVersions?.[version] !== undefined && nextVersions[version] !== previous[version]) mappedAreas.forEach((area) => areas.add(area));
  });
  return [...areas];
}

function renderSyncStatus(status) {
  renderMaintenanceStatus(status.maintenance);
  if (!state.data) return;
  state.data.sync = {
    ...state.data.sync,
    running: Boolean(status.running),
    status: status.message || null,
    message: status.message || null,
    phase: status.phase || null,
    progress: progressPercentage(status.progress),
    last_error: status.last_error || null,
  };
  renderPerformance(state.data.performance || {}, { refreshCharts: false });
  renderSettings(state.data);
}

function renderMaintenanceStatus(maintenance) {
  const active = Boolean(maintenance?.active);
  const statusCard = $("#statusCard");
  if (!statusCard) return;
  if (!active) {
    if ($("#statusTitle").textContent === "Wartungsmodus aktiv") statusCard.hidden = true;
    return;
  }
  statusCard.hidden = false;
  statusCard.classList.remove("working");
  statusCard.classList.add("warning");
  $("#statusTitle").textContent = "Wartungsmodus aktiv";
  $("#statusDetail").textContent = "Die Datenbank wird wiederhergestellt; Änderungen sind vorübergehend pausiert.";
}

function handleSyncStatus(status, broadcast = false) {
  if (!status || typeof status !== "object") return;
  if (broadcast) broadcastSyncMessage({ type: "status", status });
  if (status.operation_id && status.running) {
    state.syncPoll.operationId = status.operation_id;
    state.localSync.intervals = true;
  }
  renderSyncStatus(status);
  const changedAreas = changedSyncAreas(status.state_versions);
  if (changedAreas.length && state.data) {
    load("/api/bootstrap?local=1", changedAreas).catch(() => {});
  } else if (state.data && status.state_versions) {
    state.data.state_versions = { ...state.data.state_versions, ...status.state_versions };
  }
  if (!status.running && status.operation_id && status.operation_id === state.syncPoll.operationId) {
    state.localSync.intervals = false;
    state.syncPoll.operationId = null;
  }
}

function scheduleSyncPoll(delay = SYNC_POLL_IDLE_MS) {
  if (state.syncPoll.timer) clearTimeout(state.syncPoll.timer);
  state.syncPoll.timer = setTimeout(() => { state.syncPoll.timer = null; void pollSyncStatus(); }, delay);
}

async function pollSyncStatus() {
  if (!state.data || document.visibilityState !== "visible" || !navigator.onLine) {
    scheduleSyncPoll(SYNC_POLL_RETRY_MS);
    return;
  }
  if (!syncPollLeaseAvailable()) {
    scheduleSyncPoll(SYNC_POLL_RETRY_MS);
    return;
  }
  if (state.syncPoll.controller) return;
  const controller = new AbortController();
  state.syncPoll.controller = controller;
  try {
    const status = await api("/api/sync/status", { signal: controller.signal });
    handleSyncStatus(status, true);
    scheduleSyncPoll(status.running ? SYNC_POLL_ACTIVE_MS : SYNC_POLL_IDLE_MS);
  } catch (error) {
    if (error.name !== "AbortError") scheduleSyncPoll(SYNC_POLL_RETRY_MS);
  } finally {
    if (state.syncPoll.controller === controller) state.syncPoll.controller = null;
    releaseSyncPollLease();
  }
}

function setupSyncStatusMonitoring() {
  if ("BroadcastChannel" in globalThis) {
    state.syncPoll.channel = new BroadcastChannel(SYNC_POLL_CHANNEL);
    state.syncPoll.channel.addEventListener("message", (event) => {
      const message = event.data || {};
      if (message.type === "status") handleSyncStatus(message.status);
    });
  }
  scheduleSyncPoll(0);
}

function handleSyncVisibility() {
  if (document.visibilityState !== "visible") {
    disconnectStateEvents();
    state.syncPoll.controller?.abort();
    releaseSyncPollLease();
    return;
  }
  connectStateEvents();
  scheduleSyncPoll(0);
}

function renderConnectivityStatus(online = navigator.onLine) {
  const notice = $("#connectivityNotice");
  if (!notice) return;
  notice.hidden = online;
  notice.textContent = online ? "" : "Offline: Nur bereits geladene Daten sind verfügbar. Synchronisierung und Speichern warten auf die Verbindung.";
}


function setupConnectivityStatus() {
  renderConnectivityStatus();
  globalThis.addEventListener("online", () => renderConnectivityStatus(true));
  globalThis.addEventListener("offline", () => renderConnectivityStatus(false));
  globalThis.addEventListener("offline", disconnectStateEvents);
  globalThis.addEventListener("online", () => connectStateEvents());
}


const PROVIDER_FRESHNESS_STATUS = {
  fresh: "Frisch",
  partial: "Teilweise erfolgreich",
  stale: "Veraltet, aber nutzbar",
  syncing: "Wird aktualisiert",
  error: "Fehler",
  never_loaded: "Noch nie geladen",
  not_configured: "Nicht konfiguriert",
};


const PROVIDER_FRESHNESS_ERRORS = {
  auth_required: "Erneute Anmeldung erforderlich",
  rate_limited: "Rate Limit erreicht",
  network_error: "Netzwerkfehler",
  invalid_configuration: "Ungültige Konfiguration",
  provider_error: "Providerfehler",
  upstream_auth: globalThis.AppApi.messageForReason("upstream_auth"),
  upstream_rate_limited: globalThis.AppApi.messageForReason("upstream_rate_limited"),
  upstream_unavailable: globalThis.AppApi.messageForReason("upstream_unavailable"),
  upstream_rejected: globalThis.AppApi.messageForReason("upstream_rejected"),
  upstream_not_found: globalThis.AppApi.messageForReason("upstream_not_found"),
};


const PROVIDER_LABELS = {
  intervals: "Intervals.icu",
  garmin: "Garmin",
  calendar: "Gemeinsamer Kalender",
  weather: "Open-Meteo",
};


function coachProviderLabel(provider) {
  const key = String(provider || "").trim().toLowerCase();
  return PROVIDER_LABELS[key] || "Provider";
}


const NON_RETRYABLE_PROVIDER_ERRORS = Object.freeze(["auth_required", "invalid_configuration"]);


function providerErrorIsNonRetryable(errorCode) {
  return NON_RETRYABLE_PROVIDER_ERRORS.includes(errorCode);
}


function providerRequiresManualAttention(entry) {
  if (!entry?.configured) return false;
  if (providerErrorIsNonRetryable(entry.error_code)) return true;
  const hasFutureRetry = entry.next_retry_at && Date.parse(entry.next_retry_at) > Date.now();
  return ["error", "stale", "partial"].includes(entry.state) && !hasFutureRetry;
}


function renderProviderAttention(data) {
  const banner = $("#providerAttentionBanner");
  const detail = $("#providerAttentionDetail");
  if (!banner || !detail) return;
  const providers = (Array.isArray(data.provider_freshness) ? data.provider_freshness : [])
    .filter(providerRequiresManualAttention);
  banner.hidden = !providers.length;
  if (!providers.length) {
    detail.textContent = "";
    return;
  }
  const labels = [...new Set(providers.map((entry) => entry.label || entry.provider || "Eine Anbindung"))];
  detail.textContent = labels.length === 1
    ? `${labels[0]} benötigt manuelles Eingreifen.`
    : `${labels.length} Anbindungen benötigen manuelles Eingreifen.`;
}


function progressPercentage(value) {
  const progress = Number(value);
  return Number.isFinite(progress) ? Math.max(0, Math.min(100, Math.round(progress))) : null;
}


function garminWindowProgress(message) {
  const match = /Zeitraum\s+(\d+)\/(\d+)/i.exec(String(message || ""));
  if (!match) return null;
  const current = Number(match[1]);
  const total = Number(match[2]);
  if (!Number.isFinite(current) || !Number.isFinite(total) || total < 1) return null;
  return Math.max(1, Math.min(99, Math.round(((current - 1) / total) * 100)));
}


function connectionProgressEntry(label, message, progress = null) {
  return { label, message: String(message || "Synchronisierung läuft…"), progress };
}


function renderConnectionsSyncProgress(data) {
  const root = $("#connectionsSyncProgress");
  if (!root) return;
  root.replaceChildren();
  const entries = [];
  const activeProviders = new Set();
  const sync = data.sync || {};
  const intervalRunning = Boolean(sync.running || state.localSync.intervals);
  if (intervalRunning) {
    entries.push(connectionProgressEntry(
      "Intervals.icu",
      sync.message || sync.status || "Intervals.icu-Synchronisierung wird gestartet…",
      progressPercentage(sync.progress),
    ));
    activeProviders.add("intervals");
  }
  const garminSync = data.garmin_sync || {};
  const garminRunning = Boolean(garminSync.running || state.localSync.garmin);
  if (garminRunning) {
    const message = garminSync.status || "Garmin-Synchronisierung wird gestartet…";
    entries.push(connectionProgressEntry("Garmin", message, garminWindowProgress(message)));
    activeProviders.add("garmin");
  }
  const resyncs = data.provider_resync || {};
  [
    ["intervals", "Intervals.icu", state.localSync.intervalsFull],
    ["garmin", "Garmin", state.localSync.garminFull],
  ].forEach(([provider, label, localRunning]) => {
    const resync = resyncs[provider] || {};
    if (!resync.running && !localRunning) return;
    entries.push(connectionProgressEntry(label, resync.status || "Lokale Daten werden vollständig neu geladen…"));
    activeProviders.add(provider);
  });
  if (data.external_calendar?.running || state.localSync.externalCalendar) {
    entries.push(connectionProgressEntry("Gemeinsamer Kalender", data.external_calendar?.status || "Kalender wird synchronisiert…"));
    activeProviders.add("calendar");
  }
  if (data.weather?.loading || state.localSync.weather) {
    entries.push(connectionProgressEntry("Open-Meteo", "Wetter wird aktualisiert…"));
    activeProviders.add("weather");
  }
  (Array.isArray(sync.jobs) ? sync.jobs : [])
    .filter((job) => ["queued", "running"].includes(job?.status) && job.provider && !activeProviders.has(job.provider))
    .forEach((job) => {
      const completed = Number(job.progress?.completed || 0);
      const total = Number(job.progress?.total || 0);
      const progress = total > 0 ? Math.round((completed / total) * 100) : null;
      const label = coachProviderLabel(job.provider);
      let message;
      if (job.status === "queued") message = "Wartet auf den Start der Synchronisierung…";
      else if (total > 0) {
        const suffix = total === 1 ? "" : "e";
        message = `${completed}/${total} Arbeitsschritt${suffix} abgeschlossen`;
      }
      else message = "Synchronisierung läuft…";
      entries.push(connectionProgressEntry(label, message, progress));
    });
  root.hidden = !entries.length;
  entries.forEach((entry) => {
    const item = document.createElement("article");
    item.className = "connection-sync-progress-item";
    const header = document.createElement("div");
    header.className = "connection-sync-progress-header";
    const label = document.createElement("strong");
    label.textContent = entry.label;
    const message = document.createElement("span");
    message.textContent = entry.message;
    header.append(label, message);
    const bar = document.createElement("progress");
    bar.className = "connection-sync-progress-bar";
    bar.max = 100;
    if (entry.progress == null) {
      bar.classList.add("is-indeterminate");
      bar.removeAttribute("value");
      bar.setAttribute("aria-label", `${entry.label}: Fortschritt wird ermittelt`);
    } else {
      bar.value = entry.progress;
      bar.setAttribute("aria-label", `${entry.label}: ${entry.progress}%`);
    }
    item.append(header, bar);
    root.append(item);
  });
}


function renderProviderFreshness(data) {
  const root = $("#providerFreshnessTimeline");
  if (!root) return;
  root.replaceChildren();
  const entries = Array.isArray(data.provider_freshness) ? data.provider_freshness : [];
  if (!entries.length) {
    root.textContent = "Noch kein Provider-Status verfügbar.";
    return;
  }
  entries.forEach((entry) => {
    const item = document.createElement("article");
    item.className = "provider-freshness-item";
    const header = document.createElement("div");
    header.className = "provider-freshness-header";
    const title = document.createElement("strong");
    title.textContent = entry.label || entry.provider || "Provider";
    const status = document.createElement("span");
    status.className = entry.state === "fresh" || entry.state === "partial" ? "configured" : "not-configured";
    status.textContent = PROVIDER_FRESHNESS_STATUS[entry.state] || "Unbekannter Status";
    header.append(title, status);
    const meta = document.createElement("span");
    meta.className = "provider-freshness-meta";
    const attempt = entry.last_attempt_at ? `Letzter Versuch: ${formatTime(entry.last_attempt_at)}` : "Noch kein Versuch";
    const success = entry.last_success_at ? `Letzter Erfolg: ${formatTime(entry.last_success_at)}` : "Noch kein erfolgreicher Abruf";
    const retry = entry.next_retry_at ? `Nächster Versuch ab: ${formatTime(entry.next_retry_at)}` : "Kein automatischer Retry terminiert";
    meta.textContent = `${attempt} · ${success} · ${retry}`;
    item.append(header, meta);
    if (entry.error_code) {
      const error = document.createElement("span");
      error.className = "error";
      error.textContent = PROVIDER_FRESHNESS_ERRORS[entry.error_code] || "Providerfehler";
      item.append(error);
    }
    if (entry.read_only && entry.configured && ["error", "stale"].includes(entry.state)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button";
      button.textContent = "Erneut versuchen";
      button.addEventListener("click", () => retryProvider(entry.provider, button));
      item.append(button);
    }
    root.append(item);
  });
}


async function retryProvider(provider, button) {
  if (button) button.disabled = true;
  try {
    if (provider === "intervals") await syncNow({ currentTarget: $("#systemIntervalsSyncButton") });
    else if (provider === "garmin") await syncGarmin();
    else if (provider === "weather") await syncWeather();
    else if (provider === "calendar") await syncExternalCalendar();
  } finally {
    if (button) button.disabled = false;
  }
}
