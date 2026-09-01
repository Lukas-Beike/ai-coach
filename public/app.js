const $ = (selector) => document.querySelector(selector);
const VOICE_MAX_DURATION_MS = 60_000;
const VOICE_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const QUICK_TEMPLATES_INACTIVITY_MS = 6 * 60 * 60 * 1000;
const LAST_PWA_ACTIVITY_KEY = "intervals-coach-last-pwa-activity";
const SYNC_POLL_LEASE_KEY = "intervals-coach-sync-poll-lease";
const SYNC_POLL_CHANNEL = "intervals-coach-sync-status";
const SYNC_POLL_ACTIVE_MS = 1_500;
const SYNC_POLL_IDLE_MS = 60_000;
const SYNC_POLL_RETRY_MS = 5_000;
const SYNC_POLL_LEASE_MS = 4_000;
const dialogFocusReturn = new WeakMap();

function showAccessibleDialog(dialog, initialFocus = null) {
  if (!dialog) return;
  const active = document.activeElement;
  dialogFocusReturn.set(dialog, active instanceof HTMLElement && active !== document.body ? active : null);
  if (!dialog.open) dialog.showModal();
  const target = initialFocus || dialog.querySelector("button, input, textarea, select, [tabindex]:not([tabindex='-1'])");
  if (target instanceof HTMLElement) target.focus({ preventScroll: true });
}

function restoreDialogFocus(dialog) {
  const target = dialogFocusReturn.get(dialog);
  dialogFocusReturn.delete(dialog);
  if (target instanceof HTMLElement && target.isConnected && !target.disabled && !target.closest("[hidden]")) {
    target.focus({ preventScroll: true });
  }
}

function renderMoreSegments(segment = moreSegmentFromRoute()) {
  const selected = ["profile", "connections", "coach", "privacy", "operations"].includes(segment) ? segment : "connections";
  document.querySelectorAll("[data-more-segment-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.moreSegmentPanel !== selected;
  });
  document.querySelectorAll("[data-more-segment]").forEach((link) => {
    const active = link.dataset.moreSegment === selected;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function renderPlanSegments(segment = state.planSegment) {
  const selected = ["calendar", "library", "goals"].includes(segment) ? segment : "calendar";
  state.planSegment = selected;
  document.querySelectorAll("[data-plan-segment-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.planSegmentPanel !== selected;
  });
  document.querySelectorAll("[data-plan-segment]").forEach((link) => {
    const active = link.dataset.planSegment === selected;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function currentPlanLoadAreas() {
  const areas = new Set(["chat", "activities", "performance", "feedback", "profile"]);
  const route = baseRoute();
  if (route === "today" || (route === "planned" && state.planSegment !== "library")) areas.add("plan");
  if (route === "planned" && state.planSegment === "library") areas.add("library");
  return [...areas];
}

function ensureRouteData(route = state.route) {
  if (!state.data || state.loadPromise) return;
  const requested = [];
  const panelRoute = baseRoute(route);
  if ((panelRoute === "today" || (panelRoute === "planned" && state.planSegment !== "library")) && !state.loadedAreas.has("plan")) requested.push("plan");
  if (panelRoute === "planned" && state.planSegment === "library" && !state.loadedAreas.has("library")) requested.push("library");
  if (requested.length) load("/api/bootstrap", requested);
}

function applyNavigationRoute(route, { historyMode = "none", focus = true } = {}) {
  const panelRoute = NAV_ROUTES[route] ? route : DEFAULT_NAV_ROUTE;
  const mainRoute = baseRoute(panelRoute);
  const navigationRoute = NAV_LINK_ROUTES[mainRoute] || mainRoute;
  const currentPanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  if (currentPanel !== NAV_ROUTES[panelRoute] && !confirmDiscardChanges()) return false;
  if (currentPanel !== NAV_ROUTES[panelRoute] && hasUnsavedChanges()) discardUnsavedChanges();
  if (currentPanel === "workoutsPanel" && mainRoute !== "planned") state.planSegmentScroll[state.planSegment] = window.scrollY;
  if (currentPanel === "workoutsPanel" && mainRoute === "planned" && state.planSegment !== planSegmentFromRoute(panelRoute)) state.planSegmentScroll[state.planSegment] = window.scrollY;
  document.querySelectorAll(".nav-item, .panel").forEach((node) => node.classList.remove("active"));
  const navigation = document.querySelector(`.nav-item[data-route="${navigationRoute}"]`);
  const panel = document.querySelector(`#${NAV_ROUTES[panelRoute]}`);
  if (!navigation || !panel) return false;
  navigation.classList.add("active");
  document.querySelectorAll(".nav-item").forEach((item) => item.removeAttribute("aria-current"));
  navigation.setAttribute("aria-current", "page");
  panel.classList.add("active");
  state.route = panelRoute;
  if (mainRoute === "more") renderMoreSegments(moreSegmentFromRoute(panelRoute));
  if (mainRoute === "planned") {
    renderPlanSegments(planSegmentFromRoute(panelRoute));
    renderActivePlanSegment(state.data);
  }
  const targetHash = `#${panelRoute}`;
  if (window.location.hash !== targetHash) {
    if (historyMode === "push") window.history.pushState({ route: panelRoute }, "", targetHash);
    else if (historyMode === "replace") window.history.replaceState({ route: panelRoute }, "", targetHash);
  }
  if (state.data) renderStatus(state.data);
  updateHeaderAction();
  if (state.data && (panelRoute === "settings" || panelRoute === "more")) loadContextPreview();
  if (state.data && (panelRoute === "settings" || panelRoute === "more")) loadLogs();
  const targetScroll = mainRoute === "planned" ? (state.planSegmentScroll[state.planSegment] || 0) : 0;
  requestAnimationFrame(() => window.scrollTo({ top: targetScroll, behavior: "auto" }));
  if (mainRoute === "coach") scrollChatToLatest(true);
  ensureRouteData(panelRoute);
  if (focus && !$("#appShell")?.hidden) {
    panel.setAttribute("tabindex", "-1");
    panel.focus({ preventScroll: true });
  }
  return true;
}

function syncNavigationRoute() {
  const route = routeFromHash();
  const applied = applyNavigationRoute(route, { historyMode: hashContainsKnownRoute() ? "none" : "replace" });
  if (!applied && state.route) window.history.replaceState({ route: state.route }, "", `#${state.route}`);
}

function readLastPwaActivity() {
  try {
    const value = Number(localStorage.getItem(LAST_PWA_ACTIVITY_KEY));
    return Number.isFinite(value) && value > 0 ? value : 0;
  } catch (_) { return 0; }
}

function savePwaActivity() {
  try { localStorage.setItem(LAST_PWA_ACTIVITY_KEY, String(Date.now())); } catch (_) {}
}

function notePwaActivity() {
  if (!state.activityTracked) {
    const lastActivity = readLastPwaActivity();
    state.quickTemplatesVisible = Boolean(lastActivity && Date.now() - lastActivity >= QUICK_TEMPLATES_INACTIVITY_MS);
    state.activityTracked = true;
  }
  savePwaActivity();
}

function renderQuickMessageTemplates() {
  const root = $("#quickMessageTemplates");
  if (root) root.hidden = !state.quickTemplatesVisible || state.busy;
}

function checkPwaReturn() {
  if (!state.data || document.visibilityState !== "visible") return;
  const lastActivity = readLastPwaActivity();
  if (lastActivity && Date.now() - lastActivity >= QUICK_TEMPLATES_INACTIVITY_MS) state.quickTemplatesVisible = true;
  savePwaActivity();
  renderQuickMessageTemplates();
}

function handlePwaInteraction() {
  if (!state.data || document.visibilityState !== "visible") return;
  const lastActivity = readLastPwaActivity();
  if (lastActivity && Date.now() - lastActivity >= QUICK_TEMPLATES_INACTIVITY_MS) state.quickTemplatesVisible = true;
  savePwaActivity();
  renderQuickMessageTemplates();
}

function cookie(name) {
  return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
}

function showLogin() {
  state.data = null;
  state.loadedAreas.clear();
  state.planSegment = "calendar";
  state.profileDirty = false;
  state.checkinDirty = false;
  state.chatDraftDirty = false;
  state.activityFeedbackDirty.clear();
  state.planningEditDirty.clear();
  state.libraryDateDirty.clear();
  state.activityFeedbackDrafts.clear();
  state.planningDrafts.clear();
  state.libraryDateDrafts.clear();
  state.activityFromDate = "";
  state.activityToDate = "";
  state.activityVisibleCount = 250;
  setDirtyIndicator("activityDirtyIndicator", false);
  setDirtyIndicator("planningDirtyIndicator", false);
  setDirtyIndicator("libraryDirtyIndicator", false);
  $("#appShell").hidden = true;
  $("#authLoading").hidden = true;
  const dialog = $("#loginDialog");
  showAccessibleDialog(dialog, $("#loginPassword"));
}

function showAppShellLoading() {
  const shell = $("#appShell");
  const statusCard = $("#statusCard");
  const loader = $("#authLoading");
  loader.hidden = false;
  loader.textContent = "Trainingsbereich wird geladen…";
  shell.hidden = true;
  shell.classList.add("is-loading");
  shell.setAttribute("aria-busy", "true");
  statusCard.hidden = false;
  statusCard.classList.remove("warning");
  statusCard.classList.add("working");
  $("#statusTitle").textContent = "Trainingsbereich wird geladen…";
  $("#statusDetail").textContent = "Deine Trainingsdaten werden im Hintergrund geladen";
}

function finishAppShellLoading() {
  const shell = $("#appShell");
  $("#authLoading").hidden = true;
  if (!$("#loginDialog")?.open) shell.hidden = false;
  shell.classList.remove("is-loading");
  shell.removeAttribute("aria-busy");
  applyNavigationRoute(routeFromHash(), { historyMode: hashContainsKnownRoute() ? "none" : "replace" });
}

async function api(path, options = {}) {
  return window.AppApi.request(path, options, showLogin);
}

function syncPollLeaseAvailable() {
  try {
    const current = JSON.parse(localStorage.getItem(SYNC_POLL_LEASE_KEY) || "null");
    if (current && current.expires_at > Date.now() && current.token !== state.syncPoll.leaseToken) return false;
    const lease = { token: state.syncPoll.leaseToken, expires_at: Date.now() + SYNC_POLL_LEASE_MS };
    localStorage.setItem(SYNC_POLL_LEASE_KEY, JSON.stringify(lease));
    const verified = JSON.parse(localStorage.getItem(SYNC_POLL_LEASE_KEY) || "null");
    return verified?.token === state.syncPoll.leaseToken;
  } catch (_) {
    return true;
  }
}

function releaseSyncPollLease() {
  try {
    const current = JSON.parse(localStorage.getItem(SYNC_POLL_LEASE_KEY) || "null");
    if (current?.token === state.syncPoll.leaseToken) localStorage.removeItem(SYNC_POLL_LEASE_KEY);
  } catch (_) {}
}

function broadcastSyncMessage(message) {
  try { state.syncPoll.channel?.postMessage(message); } catch (_) {}
}

function changedSyncAreas(nextVersions) {
  const previous = state.data?.state_versions || {};
  const areaMap = {
    activities: ["activities"],
    performance: ["performance"],
    chat: ["chat"],
    library: ["library", "plan"],
    checkins: ["feedback"],
    activity_feedback: ["feedback"],
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
    ...(state.data.sync || {}),
    running: Boolean(status.running),
    status: status.message || null,
    last_error: status.last_error || null,
  };
  renderActivities(state.data.activities || []);
  renderToday(state.data);
  renderPerformance(state.data.performance || {});
  renderSettings(state.data);
  updateHeaderAction();
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
    const waiters = state.syncPoll.waiters.splice(0);
    waiters.forEach((resolve) => resolve(status));
  }
}

function scheduleSyncPoll(delay = SYNC_POLL_IDLE_MS) {
  if (state.syncPoll.timer) clearTimeout(state.syncPoll.timer);
  state.syncPoll.timer = setTimeout(() => { state.syncPoll.timer = null; pollSyncStatus(); }, delay);
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

function waitForSync(operationId) {
  if (!operationId) return Promise.resolve({ status: "unknown" });
  state.syncPoll.operationId = operationId;
  state.localSync.intervals = true;
  broadcastSyncMessage({ type: "started", operation_id: operationId });
  scheduleSyncPoll(0);
  return new Promise((resolve) => state.syncPoll.waiters.push(resolve));
}

function setupSyncStatusMonitoring() {
  if ("BroadcastChannel" in window) {
    state.syncPoll.channel = new BroadcastChannel(SYNC_POLL_CHANNEL);
    state.syncPoll.channel.addEventListener("message", (event) => {
      const message = event.data || {};
      if (message.type === "started" && message.operation_id) {
        state.syncPoll.operationId = message.operation_id;
        state.localSync.intervals = true;
        scheduleSyncPoll(0);
      } else if (message.type === "status") handleSyncStatus(message.status);
    });
  }
  scheduleSyncPoll(0);
}

function handleSyncVisibility() {
  if (document.visibilityState !== "visible") {
    state.syncPoll.controller?.abort();
    releaseSyncPollLease();
    return;
  }
  scheduleSyncPoll(0);
}

async function apiAudio(path, blob) {
  return window.AppApi.audio(path, blob, showLogin);
}

async function bootstrapAuth() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const response = await fetch("/api/auth/status", { credentials: "same-origin", cache: "no-store", signal: controller.signal });
    const status = await response.json();
    renderMaintenanceStatus(status.maintenance);
    if (status.authenticated) {
      $("#authLoading").hidden = true;
      $("#loginDialog").close();
      showAppShellLoading();
      notePwaActivity();
      await loadInitialState();
    } else showLogin();
  } catch (_) {
    $("#loginError").textContent = "Server nicht erreichbar.";
    showLogin();
  } finally { clearTimeout(timeout); }
}

async function login(event) {
  event.preventDefault();
  const button = $("#loginButton");
  const buttonLabel = $("#loginButtonLabel");
  const error = $("#loginError");
  button.disabled = true;
  button.classList.add("is-loading");
  button.setAttribute("aria-busy", "true");
  buttonLabel.textContent = "Anmelden …";
  error.textContent = "";
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("#loginPassword").value }) });
    $("#loginPassword").value = "";
    $("#loginDialog").close();
    showAppShellLoading();
    notePwaActivity();
    await loadInitialState();
  } catch (exception) {
    error.textContent = exception.message;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    buttonLabel.textContent = "Anmelden";
  }
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 3000);
}

function setVoiceStatus(message = "", error = false) {
  const node = $("#voiceStatus");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = !message;
}

function voiceIsRecording() {
  return state.voiceRecorder?.state === "recording";
}

function formatVoiceDuration() {
  const elapsed = Math.min(Date.now() - state.voiceStartedAt, VOICE_MAX_DURATION_MS);
  return `${String(Math.floor(elapsed / 1000)).padStart(2, "0")} s / 60 s`;
}

function updateVoiceButton() {
  const button = $("#voiceButton");
  if (!button) return;
  const recording = voiceIsRecording();
  const transcribing = state.voiceTranscribing;
  button.disabled = state.busy || transcribing;
  button.classList.toggle("recording", recording);
  button.classList.toggle("transcribing", transcribing);
  button.setAttribute("aria-pressed", recording ? "true" : "false");
  if (recording) {
    button.textContent = "■";
    button.setAttribute("aria-label", "Spracheingabe beenden");
    button.title = "Spracheingabe beenden";
  } else if (transcribing) {
    button.textContent = "…";
    button.setAttribute("aria-label", "Audio wird transkribiert");
    button.title = "Audio wird transkribiert";
  } else {
    button.textContent = "🎙";
    button.setAttribute("aria-label", "Spracheingabe starten");
    button.title = "Spracheingabe starten";
  }
  updateChatControls();
}

function updateChatControls() {
  const sendButton = $("#sendButton");
  const steerButton = $("#steerButton");
  const cancelButton = $("#cancelChatButton");
  const inputAvailable = !voiceIsRecording() && !state.voiceTranscribing;
  if (sendButton) {
    sendButton.disabled = !inputAvailable;
    sendButton.textContent = state.busy ? "Einreihen" : "Senden";
  }
  if (steerButton) {
    steerButton.hidden = !state.busy;
    steerButton.disabled = !inputAvailable;
  }
  if (cancelButton) {
    cancelButton.hidden = !state.busy;
    cancelButton.disabled = !state.chatStream || state.chatStream.cancelRequested;
    cancelButton.textContent = state.chatStream?.cancelRequested ? "Wird abgebrochen…" : "Abbrechen";
  }
  updateChatQueueStatus();
}

function stopVoiceCapture(recorder = state.voiceRecorder) {
  if (state.voiceTimer) clearInterval(state.voiceTimer);
  state.voiceTimer = null;
  if (state.voiceStream) {
    state.voiceStream.getTracks().forEach((track) => track.stop());
    state.voiceStream = null;
  }
  if (state.voiceRecorder === recorder) state.voiceRecorder = null;
  updateVoiceButton();
}

function stopVoiceRecording() {
  const recorder = state.voiceRecorder;
  if (recorder?.state === "recording") recorder.stop();
}

async function transcribeVoice(blob) {
  state.voiceTranscribing = true;
  setVoiceStatus("Aufnahme wird transkribiert …");
  updateVoiceButton();
  try {
    const result = await apiAudio("/api/transcribe", blob);
    const transcript = String(result.transcript || "").trim();
    if (!transcript) throw new Error("OpenAI hat kein Transkript zurückgegeben.");
    const input = $("#messageInput");
    const current = input.value.trim();
    input.value = current ? `${current}\n${transcript}` : transcript;
    input.dispatchEvent(new Event("input"));
    updateVoiceButton();
    input.focus();
    setVoiceStatus("Transkript eingefügt. Bitte prüfen und anschließend senden.");
  } catch (error) {
    setVoiceStatus(error.message, true);
    toast(error.message, true);
  } finally {
    state.voiceTranscribing = false;
    updateVoiceButton();
  }
}

async function toggleVoiceInput() {
  if (state.busy || state.voiceTranscribing) return;
  if (voiceIsRecording()) {
    stopVoiceRecording();
    return;
  }
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    const message = "Spracheingabe benötigt eine HTTPS-Verbindung und einen unterstützten Browser.";
    setVoiceStatus(message, true);
    toast(message, true);
    return;
  }
  setVoiceStatus("Mikrofon wird aktiviert …");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const mimeType = typeof MediaRecorder.isTypeSupported === "function"
      ? VOICE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || ""
      : "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    state.voiceStream = stream;
    state.voiceRecorder = recorder;
    state.voiceStartedAt = Date.now();
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) chunks.push(event.data);
    });
    recorder.addEventListener("error", () => {
      stopVoiceCapture(recorder);
      setVoiceStatus("Die Audioaufnahme ist fehlgeschlagen.", true);
    });
    recorder.addEventListener("stop", () => {
      const recordedType = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunks, { type: recordedType });
      stopVoiceCapture(recorder);
      if (blob.size) transcribeVoice(blob);
      else setVoiceStatus("Es wurde keine Sprache aufgenommen.", true);
    }, { once: true });
    recorder.start();
    setVoiceStatus(`Aufnahme läuft · ${formatVoiceDuration()}`);
    updateVoiceButton();
    state.voiceTimer = setInterval(() => {
      if (!voiceIsRecording()) return;
      setVoiceStatus(`Aufnahme läuft · ${formatVoiceDuration()}`);
      if (Date.now() - state.voiceStartedAt >= VOICE_MAX_DURATION_MS) stopVoiceRecording();
    }, 250);
  } catch (error) {
    stopVoiceCapture();
    const message = error.name === "NotAllowedError"
      ? "Der Mikrofonzugriff wurde nicht erlaubt."
      : "Das Mikrofon konnte nicht aktiviert werden.";
    setVoiceStatus(message, true);
    toast(message, true);
  }
}

function notificationPermission() {
  return "Notification" in window ? Notification.permission : "unsupported";
}

function renderNotificationStatus() {
  const node = $("#notificationStatus");
  const button = $("#notificationEnableButton");
  const permission = notificationPermission();
  if (!node || !button) return;
  node.textContent = permission === "granted" ? "Aktiv" : permission === "denied" ? "Im Browser blockiert" : permission === "unsupported" ? "Von diesem Browser nicht unterstützt" : "Noch nicht aktiviert";
  button.disabled = permission === "granted" || permission === "unsupported";
  button.textContent = permission === "granted" ? "Aktiviert" : "Benachrichtigungen aktivieren";
}

async function enableNotifications() {
  if (!("Notification" in window)) { toast("Dieser Browser unterstützt keine PWA-Benachrichtigungen", true); return; }
  const permission = await Notification.requestPermission();
  renderNotificationStatus();
  if (permission === "granted") toast("PWA-Benachrichtigungen aktiviert");
}

async function showPwaNotification(title, options, key) {
  if (notificationPermission() !== "granted" || state.notificationKeys.has(key)) return;
  state.notificationKeys.add(key);
  try {
    const registration = await navigator.serviceWorker.ready;
    await registration.showNotification(title, { icon: "/icon.svg", badge: "/icon.svg", ...options });
  } catch (_) {}
}

function notifyState(data) {
  const next = data.planning?.season?.next_event;
  if (next && next.days_until >= 0 && next.days_until <= 3) showPwaNotification("Wettkampf steht bevor", { body: `${next.name} ist in ${next.days_until} Tag(en).`, tag: `competition:${next.id}` }, `competition:${next.id}:${next.event_date}`);
  const error = data.sync?.last_error || data.garmin_sync?.status?.includes("Fehler") && data.garmin_sync.status;
  if (error) showPwaNotification("Intervals Coach benötigt Aufmerksamkeit", { body: String(error), tag: "sync-error" }, `error:${error}`);
}

function todayIso() { return timezoneDateKey(state.data?.profile?.timezone, new Date()); }

function adaptivePreviewMarkup(preview) {
  const signals = preview.signals?.length
    ? `Signale: ${preview.signals.map((signal) => escapeHtml(String(signal))).join(", ")}`
    : "Keine kritischen lokalen Signale erkannt.";
  const changes = (preview.changes || []).map((change) => `<div class="replan-change"><strong>${escapeHtml(String(change.date || ""))}: ${escapeHtml(String(change.name || "Einheit"))}${change.after?.name ? ` → ${escapeHtml(String(change.after.name))}` : ""}</strong><br>${escapeHtml(String(change.before?.description || ""))}<br>→ ${escapeHtml(String(change.after?.description || ""))}</div>`).join("");
  const pause = preview.illness_pause;
  const pauseMarkup = pause && !pause.approved ? `<div class="illness-pause-preview"><strong>Krankheitspause</strong><span>${escapeHtml(String(pause.forecast || "Vorsichtige Prognose"))}</span><span>Vorgeschlagen: ${escapeHtml(String(pause.recommended_pause_days || ""))} Tage (${escapeHtml(String(pause.start_date || ""))} bis ${escapeHtml(String(pause.end_date || ""))})</span><label><input id="syncIllnessToIntervals" type="checkbox"> Krankheitstage zusätzlich als <code>SICK</code>-Einträge nach Intervals.icu synchronisieren</label></div>` : "";
  return `<div><strong>${escapeHtml(String(preview.message || "Adaptive Prüfung"))}</strong><br>${signals}</div>${pauseMarkup}${changes || "<div>Es gibt keine lokalen Einheiten, die angepasst werden müssen.</div>"}<small>${escapeHtml(String(preview.scope || ""))}</small>`;
}

function openAdaptivePlanningDialog(preview) {
  const dialog = $("#adaptivePlanningDialog");
  const node = $("#adaptivePlanningPreview");
  const apply = $("#applyAdaptivePlanningButton");
  if (!dialog || !node || !preview) return;
  node.innerHTML = adaptivePreviewMarkup(preview);
  if (apply) {
    apply.hidden = !(preview.changes || []).length && !(preview.illness_pause && !preview.illness_pause.approved);
    apply.dataset.adjustmentId = preview.id || "";
  }
  showAccessibleDialog(dialog, $("#cancelAdaptivePlanningButton"));
}

function renderAdaptivePlanning(data) {
  const planning = data.planning || {};
  const next = planning.season?.next_event;
  const summary = $("#planningSummary");
  if (summary) {
    summary.textContent = next
      ? `Nächster Wettkampf: ${next.name} am ${dateLabel(next.event_date)} · Phase: ${next.phase} · ${next.days_until} Tage`
      : "Noch kein zukünftiger Wettkampf gespeichert.";
  }
  const preview = planning.latest_replan;
  const changes = Array.isArray(preview?.changes) ? preview.changes : [];
  const illness = String(data.local_feedback?.today?.illness || "").trim();
  const previewIllness = String(preview?.illness_pause?.illness || "").trim();
  const illnessNeedsForecast = Boolean(illness && (!preview || !preview.illness_pause || previewIllness !== illness || !preview.illness_pause.approved));
  const pendingIllnessPause = Boolean(preview?.status === "preview" && preview?.illness_pause && !preview.illness_pause.approved);
  const required = Boolean(planning.needs_replan || illnessNeedsForecast || pendingIllnessPause);
  const count = Number(planning.replan_changes || changes.length);
  const caption = illnessNeedsForecast || pendingIllnessPause
    ? "Krankheit gemeldet: Sportpause prognostizieren und bestätigen."
    : count === 1
    ? "Ein zukünftiger Entwurf braucht eine Anpassung."
    : `${count} zukünftige Entwürfe brauchen eine Anpassung.`;
  const notice = $("#adaptivePlanningNotice");
  const coachNotice = $("#coachAdaptivePlanningNotice");
  if (notice) {
    notice.hidden = !required;
    const captionNode = $("#adaptivePlanningCaption");
    if (captionNode) captionNode.textContent = required ? caption : "";
    const button = $("#adaptivePlanningButton");
    if (button) {
      button.disabled = Boolean(state.localSync.adaptivePlanning);
      button.textContent = state.localSync.adaptivePlanning ? "Prüfung läuft…" : illnessNeedsForecast ? "Krankheitspause prüfen" : "Vorschau prüfen";
    }
  }
  if (coachNotice) coachNotice.hidden = !required;
}

function renderExternalCalendar(data) {
  const calendar = data.external_calendar || {};
  const status = $("#externalCalendarConnectionStatus");
  const syncButton = $("#externalCalendarSyncButton");
  if (status) {
    status.textContent = calendar.configured ? (calendar.last_error ? "Fehler bei letzter Aktualisierung" : "Konfiguriert · nur lesend") : "Nicht konfiguriert";
    status.className = calendar.configured && !calendar.last_error ? "configured" : "not-configured";
  }
  if (syncButton) {
    syncButton.disabled = Boolean(calendar.running || state.localSync.externalCalendar);
    syncButton.textContent = calendar.running || state.localSync.externalCalendar ? "Synchronisierung läuft…" : "Synchronisieren";
  }
}

function renderRemoteDeleteNotice() {
  const root = $("#remoteDeleteNotice");
  if (!root) return;
  root.replaceChildren();
  const failure = state.remoteDeleteFailure;
  root.hidden = !failure;
  if (!failure) return;
  const title = document.createElement("strong");
  title.textContent = `Remote-Löschung fehlgeschlagen: ${failure.name || "Geplante Einheit"}`;
  const message = document.createElement("span");
  message.textContent = `${failure.message || "Der Remote-Kalendereintrag wurde nicht bestätigt gelöscht."} Bitte synchronisieren und den Eintrag erneut prüfen.`;
  const close = document.createElement("button");
  close.type = "button";
  close.className = "secondary-button";
  close.textContent = "Hinweis schließen";
  close.addEventListener("click", () => { state.remoteDeleteFailure = null; renderRemoteDeleteNotice(); });
  root.append(title, message, close);
}

function formatTime(value) {
  if (!value) return "Noch nicht aktualisiert";
  const dt = new Date(value);
  if (Number.isNaN(dt.valueOf())) return value;
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short", timeZone: state.data?.profile?.timezone || undefined }).format(dt);
  } catch (_) {
    return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(dt);
  }
}

function hasUnsavedChanges() {
  return state.profileDirty
    || state.checkinDirty
    || state.chatDraftDirty
    || Boolean($("#messageInput")?.value.trim())
    || state.activityFeedbackDirty.size > 0
    || state.planningEditDirty.size > 0
    || state.libraryDateDirty.size > 0;
}

function setDirtyIndicator(id, dirty) {
  const indicator = $(`#${id}`);
  if (indicator) indicator.hidden = !dirty;
}

function confirmDiscardChanges() {
  return !hasUnsavedChanges() || window.confirm("Ungespeicherte Änderungen verwerfen?");
}

function discardUnsavedChanges() {
  state.profileDirty = false;
  state.checkinDirty = false;
  state.chatDraftDirty = false;
  state.activityFeedbackDirty.clear();
  state.planningEditDirty.clear();
  state.libraryDateDirty.clear();
  state.activityFeedbackDrafts.clear();
  state.planningDrafts.clear();
  state.libraryDateDrafts.clear();
  setDirtyIndicator("activityDirtyIndicator", false);
  setDirtyIndicator("planningDirtyIndicator", false);
  setDirtyIndicator("libraryDirtyIndicator", false);
  if (state.data) render(state.data);
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function inlineMarkdown(value) {
  let html = escapeHtml(value);
  const codeSpans = [];
  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `\u0000code${codeSpans.length}\u0000`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__(.+?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  return html.replace(/\u0000code(\d+)\u0000/g, (_, index) => codeSpans[Number(index)]);
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r/g, "").split("\n");
  const output = [];
  let paragraph = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  const flushParagraph = () => {
    if (paragraph.length) {
      output.push(`<p>${inlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
      paragraph = [];
    }
  };

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      flushParagraph(); closeList();
      if (inCode) {
        output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }
    if (!line.trim()) { flushParagraph(); closeList(); continue; }
    const heading = line.match(/^\s*(#{1,3})\s+(.+?)\s*#*\s*$/);
    if (heading) { flushParagraph(); closeList(); output.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`); continue; }
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { flushParagraph(); closeList(); output.push("<hr>"); continue; }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) { closeList(); output.push(`<${nextType}>`); listType = nextType; }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) { flushParagraph(); closeList(); output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); continue; }
    closeList(); paragraph.push(line);
  }
  if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  flushParagraph(); closeList();
  return output.join("");
}

function renderStatus(data) {
  const configured = data.configured;
  const morning = data.morning_checkin || {};
  const missing = [];
  if (!configured.openai) missing.push("OpenAI-API-Schlüssel");
  if (!configured.intervals) missing.push("Intervals.icu-API-Schlüssel");
  const performanceRefresh = data.performance_refresh || {};
  const openaiStatus = data.usage?.status || {};
  const error = data.sync.last_error || data.library_sync?.last_error || morning.last_error || performanceRefresh.last_error
    || (openaiStatus.state === "error" ? openaiStatus.message : null);
  const statusCard = $("#statusCard");
  const activePanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  const hasProblem = Boolean(missing.length || error);
  statusCard.hidden = !hasProblem || activePanel === "settingsPanel";
  statusCard.classList.toggle("warning", hasProblem);
  $("#statusTitle").textContent = missing.length
    ? `Einrichtung nötig: ${missing.join(" + ")}`
    : error ? "Coach benötigt Aufmerksamkeit" : "Coach ist bereit";
  $("#statusDetail").textContent = missing.length
    ? "Ergänze die fehlende Serverkonfiguration"
    : error || (morning.status === "ready" ? `Morgen-Check-in abgeschlossen: ${dateLabel(morning.date)}` : "Bereit für deine nächste Frage");
  statusCard.classList.remove("working");
}

function dateLabel(value) {
  if (!value) return "—";
  const raw = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    const [year, month, day] = raw.split("-").map(Number);
    return new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(year, month - 1, day));
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return raw.slice(0, 10);
  try {
    return new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeZone: state.data?.profile?.timezone || undefined }).format(parsed);
  } catch (_) {
    return new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(parsed);
  }
}

const CALENDAR_DISPLAY_DEFAULTS = { past_weeks: 1, future_weeks: 4 };
const CALENDAR_DISPLAY_MAX_WEEKS = 52;

function calendarDisplayValue(value, fallback) {
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 && number <= CALENDAR_DISPLAY_MAX_WEEKS ? number : fallback;
}

function localDateKey(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function timezoneDateKey(timeZone, instant = new Date()) {
  if (!timeZone) return localDateKey(instant);
  try {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(instant);
    const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  } catch (_) { return localDateKey(instant); }
}

function dateFromKey(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : new Date(NaN);
}

function addDateKey(value, days) {
  const date = dateFromKey(value);
  if (Number.isNaN(date.valueOf())) return "";
  date.setDate(date.getDate() + days);
  return localDateKey(date);
}

function dateKeyDifference(left, right) {
  const a = dateFromKey(left);
  const b = dateFromKey(right);
  if (Number.isNaN(a.valueOf()) || Number.isNaN(b.valueOf())) return 0;
  return Math.round((Date.UTC(a.getFullYear(), a.getMonth(), a.getDate()) - Date.UTC(b.getFullYear(), b.getMonth(), b.getDate())) / 86400000);
}

function plannedEventDate(event) {
  return String(event?.start_date_local || event?.date || "").slice(0, 10);
}

function isCoachOwnedWorkout(event) {
  return String(event?.category || "").toUpperCase() === "WORKOUT"
    && String(event?.external_id || "").startsWith("intervals-coach-");
}

function plannedDayLabel(date, offset) {
  const formatted = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long" }).format(date);
  if (offset === 0) return `Heute · ${formatted}`;
  if (offset === 1) return `Morgen · ${formatted}`;
  return formatted;
}

function plannedWeekStart(date) {
  const start = new Date(date);
  const day = start.getDay();
  start.setDate(start.getDate() - (day === 0 ? 6 : day - 1));
  start.setHours(0, 0, 0, 0);
  return start;
}

function complianceMetricLabel(compliance) {
  if (!compliance || compliance.planned_value == null || compliance.actual_value == null) return "";
  if (compliance.basis === "training_load") return `Belastung ${formatWhole(compliance.actual_value)} / ${formatWhole(compliance.planned_value)}`;
  if (compliance.basis === "duration") return `${formatDuration(compliance.actual_value)} / ${formatDuration(compliance.planned_value)}`;
  return "";
}

function complianceLabel(compliance) {
  if (!compliance) return "";
  if (compliance.status === "planned") return "Noch nicht absolviert";
  if (compliance.status === "missed") return "Nicht umgesetzt · 0%";
  if (compliance.percentage == null) return "Absolviert · Vergleich nicht verfügbar";
  const metric = complianceMetricLabel(compliance);
  return `Umsetzung ${compliance.percentage}%${metric ? ` · ${metric}` : ""}`;
}

function plannedWeekLabel(start) {
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const format = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "short" });
  return `${format.format(start)} – ${format.format(end)} ${end.getFullYear()}`;
}

function plannedComplianceForWeek(weekKey) {
  return (state.data?.planning_compliance || []).find((item) => item.week_start === weekKey) || null;
}

function plannedWeekSummary(events, weekKey) {
  const duration = events.reduce((total, event) => total + (Number(event.moving_time) || 0), 0);
  const distance = events.reduce((total, event) => total + (Number(event.distance) || 0), 0);
  const load = events.reduce((total, event) => total + (Number(event.icu_training_load) || 0), 0);
  const compliance = plannedComplianceForWeek(weekKey);
  const values = [`${events.length} ${events.length === 1 ? "Einheit" : "Einheiten"}`];
  if (compliance) {
    values.push(`${compliance.completed_units}/${compliance.planned_units} umgesetzt (${compliance.unit_percentage}%)`);
    if (compliance.percentage != null) values.push(`Umsetzung ${compliance.percentage}%`);
  }
  if (duration > 0) values.push(`${(duration / 3600).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} h`);
  if (distance > 0) values.push(`${(distance / 1000).toLocaleString("de-DE", { maximumFractionDigits: 0 })} km`);
  if (load > 0) values.push(`Belastung ${Math.round(load).toLocaleString("de-DE")}`);
  return values.join(" · ");
}

function weatherForDate(date) {
  return (state.data?.weather?.days || []).find((item) => item.date === date) || null;
}

function weatherIcon(code) {
  const number = Number(code);
  if (!Number.isFinite(number)) return "🌡️";
  if (number === 0) return "☀️";
  if (number === 1) return "🌤️";
  if (number === 2) return "⛅";
  if (number === 3) return "☁️";
  if ([45, 48].includes(number)) return "🌫️";
  if (number >= 51 && number <= 57) return "🌦️";
  if (number >= 61 && number <= 67) return "🌧️";
  if (number >= 71 && number <= 77) return number === 75 ? "❄️" : "🌨️";
  if (number >= 80 && number <= 82) return number === 80 ? "🌦️" : "🌧️";
  if (number >= 85 && number <= 86) return "🌨️";
  if (number >= 95) return "⛈️";
  return "🌤️";
}

function weatherIconFor(item) {
  return item?.icon || weatherIcon(item?.weather_code);
}

function weatherNumber(value, suffix = "") {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number)}${suffix}` : "–";
}

function weatherDirection(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return ["N", "NO", "O", "SO", "S", "SW", "W", "NW"][Math.round(number / 45) % 8];
}

function renderWeatherNotice(weather) {
  const notice = $("#weatherNotice");
  if (!notice) return;
  notice.hidden = false;
  notice.className = "weather-notice";
  if (!weather?.configured) {
    notice.textContent = "Wetterhinweise: Hinterlege im Profil einen Wetterort (Stadt oder PLZ).";
    return;
  }
  if (weather.loading) {
    notice.textContent = weather.message || "Wetterdaten werden nachgeladen.";
    return;
  }
  if (weather.error && !weather.days?.length) {
    notice.classList.add("error");
    notice.textContent = weather.error;
    return;
  }
  const location = [weather.location?.name, weather.location?.country].filter(Boolean).join(", ");
  notice.textContent = `${location ? `Wetter für ${location}` : "Wettervorhersage"} · ${weather.model || "Open-Meteo"} · Tageswerte bis 14 Tage · Zeitvorschläge bis 5 Tage · Quelle: Open-Meteo.com${weather.stale ? " · letzte verfügbare Daten" : ""}`;
}

function todayCard(title, className = "") {
  const card = document.createElement("section");
  card.className = `today-card${className ? ` ${className}` : ""}`;
  const heading = document.createElement("h3");
  heading.textContent = title;
  card.append(heading);
  return card;
}

function todayCardText(card, text, className = "today-empty") {
  const node = document.createElement("p");
  node.className = className;
  node.textContent = text;
  card.append(node);
  return node;
}

function todayAction(text, handler, className = "secondary-button") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = text;
  button.addEventListener("click", handler);
  return button;
}

function todayActivityDate(activity) {
  return String(activity?.start_date_local || activity?.date || activity?.activity_date || "").slice(0, 10);
}

function renderToday(data) {
  const root = $("#todaySummary");
  const status = $("#todayStatus");
  const detail = $("#todaySyncDetail");
  if (!root || !status) return;
  root.replaceChildren();
  status.className = "today-status";
  status.textContent = "";
  if (!data) {
    status.textContent = "Heute wird geladen…";
    return;
  }
  const todayKey = timezoneDateKey(data.profile?.timezone, new Date());
  const context = (data.daily_planning_context || []).find((item) => item.date === todayKey) || {};
  const checkin = data.local_feedback?.today || data.checkins?.find((item) => item.checkin_date === todayKey) || context.checkin;
  const recovery = context.recovery || data.performance?.recovery || {};
  const todayWorkouts = (data.planned || []).filter((event) => plannedEventDate(event) === todayKey);
  const weather = context.weather || (data.weather?.days || []).find((item) => item.date === todayKey);
  const syncMessages = [];
  if ($("#appShell")?.classList.contains("is-loading")) syncMessages.push("Heute wird geladen…");
  if (data.sync?.running || state.localSync.intervals) syncMessages.push(data.sync?.status || "Synchronisierung läuft…");
  if (data.garmin_sync?.running || state.localSync.garmin) syncMessages.push(data.garmin_sync?.status || "Garmin wird synchronisiert…");
  if (data.performance_refresh?.running || state.localSync.performance) syncMessages.push("Leistungsdaten werden aktualisiert…");
  if (!navigator.onLine) syncMessages.push("Offline: Es werden nur bereits geladene Daten angezeigt.");
  if (data.sync?.last_error) {
    status.classList.add("error");
    syncMessages.push(`Letzte Synchronisierung fehlgeschlagen: ${data.sync.last_error}`);
  } else if (syncMessages.length) status.classList.add("working");
  status.textContent = syncMessages.join(" · ");
  if (detail) detail.textContent = syncMessages.length ? syncMessages.join(" · ") : `Stand: ${dateLabel(todayKey)}`;

  const checkinCard = todayCard("Tages-Check-in", "today-checkin");
  if (checkin) {
    const values = [
      checkin.day_form,
      checkin.soreness != null ? `Muskelkater ${checkin.soreness}/10` : null,
      checkin.stress != null ? `Stress ${checkin.stress}/10` : null,
      checkin.motivation != null ? `Motivation ${checkin.motivation}/10` : null,
      checkin.available_minutes != null ? `${checkin.available_minutes} Min. verfügbar` : null,
      checkin.illness ? `Krankheit: ${checkin.illness}` : null,
    ].filter(Boolean);
    todayCardText(checkinCard, values.join(" · ") || "Check-in gespeichert.", "today-card-summary");
  } else todayCardText(checkinCard, "Noch kein Tages-Check-in gespeichert.");
  checkinCard.append(todayAction(checkin ? "Check-in bearbeiten" : "Check-in ausfüllen", () => openCheckinEditor(todayKey)));
  root.append(checkinCard);

  const readinessCard = todayCard("Readiness & Erholung", "today-readiness");
  const recoveryValues = [
    recovery.readiness != null ? `Readiness ${recovery.readiness}` : null,
    recovery.sleep_hours != null ? `${recovery.sleep_hours} h Schlaf` : null,
    recovery.hrv != null ? `${recovery.hrv} ms HRV` : null,
    recovery.resting_hr != null ? `${recovery.resting_hr} bpm Ruhepuls` : null,
  ].filter(Boolean);
  todayCardText(readinessCard, recoveryValues.join(" · ") || "Keine Erholungsdaten für heute geladen.", recoveryValues.length ? "today-card-summary" : "today-empty");
  if (recovery.readiness_source) todayCardText(readinessCard, `Quelle: ${recovery.readiness_source}`, "today-source");
  root.append(readinessCard);

  const workoutCard = todayCard("Heutiges Training", "today-workout");
  if (!todayWorkouts.length) todayCardText(workoutCard, "Für heute ist keine geplante Einheit geladen.");
  todayWorkouts.forEach((event) => {
    const item = document.createElement("div");
    item.className = "today-item";
    const title = document.createElement("strong");
    title.textContent = event.name || "Geplante Einheit";
    const meta = document.createElement("span");
    meta.textContent = [event.type || event.category, formatDuration(event.moving_time), distanceLabel(event.distance)].filter(Boolean).join(" · ") || "Details in Plan";
    item.append(title, meta);
    workoutCard.append(item);
  });
  workoutCard.append(todayAction("Plan öffnen", () => applyNavigationRoute("planned", { historyMode: "push" })));
  root.append(workoutCard);

  const weatherCard = todayCard("Wetter", "today-weather");
  if (!data.weather?.configured) todayCardText(weatherCard, "Kein Wetterort hinterlegt. Du kannst ihn im Profil ergänzen.");
  else if (data.weather?.error && !data.weather?.days?.length) todayCardText(weatherCard, data.weather.error, "today-empty today-error");
  else if (!weather) todayCardText(weatherCard, "Für heute ist noch keine Wettervorhersage geladen.");
  else todayCardText(weatherCard, [weatherIconFor(weather), weather.condition || "Vorhersage", weatherNumber(weather.temperature_min, " °C"), weatherNumber(weather.temperature_max, " °C"), weatherNumber(weather.precipitation_probability_max, " % Regen")].join(" · "), "today-card-summary");
  root.append(weatherCard);

  const feedbackCard = todayCard("Offene Rückmeldung", "today-feedback");
  const openFeedback = (data.activities || []).find((activity) => todayActivityDate(activity) && !activity.activity_feedback);
  if (openFeedback) {
    todayCardText(feedbackCard, `Rückmeldung zu „${openFeedback.name || "letzter Aktivität"}“ ergänzen.`, "today-card-summary");
    feedbackCard.append(todayAction("Verlauf öffnen", () => applyNavigationRoute("activities", { historyMode: "push" })));
  } else todayCardText(feedbackCard, "Keine offene Rückmeldung zu den geladenen Aktivitäten.");
  root.append(feedbackCard);

  const adjustment = data.planning?.latest_replan;
  if (adjustment && (adjustment.changes?.length || adjustment.illness_pause)) {
    const adjustmentCard = todayCard("Aktuelle Plananpassung", "today-adjustment");
    todayCardText(adjustmentCard, "Eine Planänderung wartet auf deine Prüfung.", "today-card-summary");
    adjustmentCard.append(todayAction("Plananpassung prüfen", () => applyNavigationRoute("planned", { historyMode: "push" })));
    root.append(adjustmentCard);
  }
}

function planningContextForDate(date) {
  return (state.data?.daily_planning_context || []).find((item) => item.date === date) || { date };
}

function planningContextNumber(value, suffix = "") {
  const number = Number(value);
  return Number.isFinite(number) ? `${number % 1 ? number.toLocaleString("de-DE", { maximumFractionDigits: 1 }) : number}${suffix}` : null;
}

function renderDailyPlanningContext(date, todayKey) {
  const context = planningContextForDate(date);
  const weather = context.weather || weatherForDate(date);
  const checkin = context.checkin;
  const recovery = context.recovery;
  const appointments = Array.isArray(context.appointments) ? context.appointments : [];
  const hasSignals = weather || checkin || recovery || appointments.length;
  if (!hasSignals && dateKeyDifference(date, todayKey) > 0) return document.createDocumentFragment();
  const root = document.createElement("div");
  root.className = "planned-day-context";
  const heading = document.createElement("strong");
  heading.textContent = "Tageskontext";
  root.append(heading);
  const signals = document.createElement("div");
  signals.className = "planned-day-context-signals";
  const addSignal = (label, value, className = "") => {
    if (!value) return;
    const signal = document.createElement("div");
    signal.className = `planned-day-signal${className ? ` ${className}` : ""}`;
    const title = document.createElement("span");
    title.className = "planned-day-signal-label";
    title.textContent = label;
    const detail = document.createElement("span");
    detail.textContent = value;
    signal.append(title, detail);
    signals.append(signal);
  };
  if (weather) {
    const weatherValues = [
      weather.condition || "Vorhersage",
      [planningContextNumber(weather.temperature_min, " °C"), planningContextNumber(weather.temperature_max, " °C")].filter(Boolean).join(" bis "),
      planningContextNumber(weather.precipitation_probability_max, " % Regen"),
      planningContextNumber(weather.wind_speed_max, " km/h Wind"),
    ].filter(Boolean);
    addSignal(`${weatherIconFor(weather)} Wetter`, weatherValues.join(" · "));
  }
  if (recovery) {
    const recoveryValues = [
      planningContextNumber(recovery.sleep_hours, " h Schlaf"),
      planningContextNumber(recovery.sleep_score, " Schlafscore"),
      planningContextNumber(recovery.hrv, " ms HRV"),
      planningContextNumber(recovery.readiness, " Readiness"),
      planningContextNumber(recovery.resting_hr, " bpm Ruhepuls"),
      planningContextNumber(recovery.body_battery, " Body Battery"),
    ].filter(Boolean);
    const recoverySources = [...new Set(Object.values(recovery.sources || {}))].filter(Boolean);
    if (recoverySources.length) recoveryValues.push(`Quelle: ${recoverySources.join(", ")}`);
    addSignal("Erholung", recoveryValues.join(" · "), "recovery");
  }
  if (checkin) {
    const checkinValues = [
      checkin.day_form ? `Tagesform: ${checkin.day_form}` : null,
      checkin.soreness != null ? `Muskelkater ${checkin.soreness}/10` : null,
      checkin.stress != null ? `Stress ${checkin.stress}/10` : null,
      checkin.motivation != null ? `Motivation ${checkin.motivation}/10` : null,
      checkin.available_minutes != null ? `${checkin.available_minutes} Min. verfügbar` : null,
      checkin.pain ? "Schmerz notiert" : null,
      checkin.availability_notes || checkin.notes ? "Notizen vorhanden" : null,
    ].filter(Boolean);
    addSignal("Tages-Check-in", checkinValues.join(" · ") || "Gespeichert", "checkin");
    if (checkin.illness) addSignal("Krankheit (wichtig)", checkin.illness, "illness");
  }
  if (appointments.length) {
    const appointmentValues = appointments.map((event) => {
      const time = event.all_day ? "ganztägig" : event.start_local ? formatTime(event.start_local) : "Termin";
      return `${event.name || "Kalendereintrag"} (${time})`;
    });
    addSignal("Termine", appointmentValues.join(" · "), "appointments");
  }
  if (hasSignals) root.append(signals);
  else {
    const empty = document.createElement("span");
    empty.className = "planned-day-context-empty";
    empty.textContent = "Noch keine Tagesinfos hinterlegt.";
    root.append(empty);
  }
  if (dateKeyDifference(date, todayKey) <= 0) {
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "planned-day-checkin-button";
    editButton.textContent = checkin ? "Tages-Check-in bearbeiten" : "Tages-Check-in hinzufügen";
    editButton.addEventListener("click", () => openCheckinEditor(date));
    root.append(editButton);
  }
  return root;
}

function distanceLabel(value) {
  const distance = Number(value);
  if (!Number.isFinite(distance) || distance <= 0) return null;
  return `${(distance / 1000).toFixed(1)} km`;
}

function activitySportLabel(activity) {
  const value = String(activity?.type || activity?.sport || activity?.sport_type || activity?.name || "").toLowerCase();
  if (/ride|bike|cycling|rad|velo|bicycle/.test(value)) return "Radfahren";
  if (/run|lauf|jog/.test(value)) return "Laufen";
  if (/swim|schwimm/.test(value)) return "Schwimmen";
  if (/strength|kraft|gym|weight/.test(value)) return "Kraft";
  return "Andere";
}

function activityTypeKey(activity) {
  return String(activity?.type || activity?.sport || activity?.sport_type || "Sportart unbekannt").trim() || "Sportart unbekannt";
}

function renderActivityFilters(activities) {
  const root = $("#activityFilters");
  if (!root) return;
  root.replaceChildren();
  const counts = new Map();
  (Array.isArray(activities) ? activities : []).forEach((activity) => {
    const type = activityTypeKey(activity);
    counts.set(type, (counts.get(type) || 0) + 1);
  });
  if (!counts.size) {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  const label = document.createElement("span");
  label.className = "activity-filters-label";
  label.textContent = "Typ filtern:";
  root.append(label);
  [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "de")).forEach(([type, count]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `activity-filter-button${state.activityTypes.has(type) ? " active" : ""}`;
    button.textContent = `${type} (${count})`;
    button.setAttribute("aria-pressed", state.activityTypes.has(type) ? "true" : "false");
    button.addEventListener("click", () => {
      if (state.activityTypes.has(type)) state.activityTypes.delete(type);
      else state.activityTypes.add(type);
      state.activityVisibleCount = 250;
      renderActivities(state.data?.activities || []);
    });
    root.append(button);
  });
  if (state.activityTypes.size) {
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "activity-filter-button clear";
    clear.textContent = "Zurücksetzen";
    clear.addEventListener("click", () => {
      state.activityTypes.clear();
      state.activityVisibleCount = 250;
      renderActivities(state.data?.activities || []);
    });
    root.append(clear);
  }
}

function renderActivityStats(activities, filtered = false) {
  const root = $("#activityStats");
  if (!root) return;
  root.replaceChildren();
  const list = Array.isArray(activities) ? activities : [];
  const counts = new Map();
  list.forEach((activity) => counts.set(activitySportLabel(activity), (counts.get(activitySportLabel(activity)) || 0) + 1));
  const entries = [[filtered ? "Einheiten im Filter" : "Einheiten gesamt", list.length], ...[...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "de")).map(([sport, count]) => [`${sport}`, count])];
  entries.forEach(([label, value]) => {
    const card = document.createElement("div");
    const number = document.createElement("strong");
    number.textContent = String(value);
    const caption = document.createElement("span");
    caption.textContent = label;
    card.append(number, caption);
    root.append(card);
  });
}

function renderActivities(activities) {
  setDirtyIndicator("activityDirtyIndicator", state.activityFeedbackDirty.size > 0);
  const list = Array.isArray(activities) ? activities : [];
  const syncDetail = $("#activitySyncDetail");
  const syncNotices = [];
  if (state.data?.provider_resync?.intervals?.running || state.localSync.intervalsFull) syncNotices.push(state.data?.provider_resync?.intervals?.status || "Intervals.icu wird vollständig neu geladen…");
  if (state.data?.provider_resync?.garmin?.running || state.localSync.garminFull) syncNotices.push(state.data?.provider_resync?.garmin?.status || "Garmin wird vollständig neu geladen…");
  if (state.data?.sync?.running || state.localSync.intervals) syncNotices.push(state.data?.sync?.status || "Intervals.icu wird synchronisiert…");
  if (syncDetail) {
    const refreshedAt = state.data?.sync?.last_sync_at;
    syncDetail.textContent = syncNotices.length
      ? syncNotices.join(" · ")
      : refreshedAt ? `Letzte Aktualisierung: ${formatTime(refreshedAt)}` : "Noch nicht aktualisiert";
  }
  renderActivityFilters(list);
  const dateFilteredActivities = list.filter((activity) => {
    const activityDate = String(activity.start_date_local || activity.date || "").slice(0, 10);
    if (state.activityFromDate && (!activityDate || activityDate < state.activityFromDate)) return false;
    if (state.activityToDate && (!activityDate || activityDate > state.activityToDate)) return false;
    return true;
  });
  const filteredActivities = state.activityTypes.size
    ? dateFilteredActivities.filter((activity) => state.activityTypes.has(activityTypeKey(activity)))
    : dateFilteredActivities;
  const displayedActivities = filteredActivities;
  const isFiltered = Boolean(state.activityTypes.size || state.activityFromDate || state.activityToDate);
  renderActivityStats(displayedActivities, isFiltered);
  const stats = $("#activityStats");
  if (stats) stats.setAttribute("aria-label", isFiltered ? "Gefilterte Aktivitätsstatistik" : "Aktivitätsstatistik");
  const root = $("#activities");
  const fromDate = $("#activityFromDate");
  const toDate = $("#activityToDate");
  if (fromDate && fromDate.value !== state.activityFromDate) fromDate.value = state.activityFromDate;
  if (toDate && toDate.value !== state.activityToDate) toDate.value = state.activityToDate;
  root.replaceChildren();
  if (!displayedActivities.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("strong");
    title.textContent = list.length ? "Keine passenden Einheiten" : "Noch keine absolvierten Einheiten";
    empty.append(title, document.createTextNode(list.length
      ? state.activityFromDate || state.activityToDate ? "Passe den Zeitraum an oder setze den Filter zurück." : "Wähle einen weiteren Aktivitätstyp oder setze den Filter zurück."
      : "Aktualisiere die Trainingsdaten, um deine synchronisierten Aktivitäten hier zu sehen."));
    root.append(empty);
    return;
  }
  displayedActivities.slice(0, state.activityVisibleCount).forEach((activity) => {
    const card = document.createElement("article");
    card.className = "activity-card";
    const top = document.createElement("div");
    top.className = "activity-top";
    const title = document.createElement("h3");
    title.textContent = activity.name || activity.type || "Einheit";
    const date = document.createElement("span");
    date.className = "eyebrow";
    date.textContent = dateLabel(activity.start_date_local);
    top.append(title, date);
    const meta = document.createElement("button");
    meta.type = "button";
    meta.className = "activity-meta";
    meta.classList.add("activity-type-button");
    const type = activityTypeKey(activity);
    meta.textContent = type;
    meta.setAttribute("aria-pressed", state.activityTypes.has(type) ? "true" : "false");
    meta.addEventListener("click", () => {
      if (state.activityTypes.has(type)) state.activityTypes.delete(type);
      else state.activityTypes.add(type);
      state.activityVisibleCount = 250;
      renderActivities(state.data?.activities || []);
    });
    const stats = document.createElement("div");
    stats.className = "activity-stats";
    const addStat = (label, value) => {
      if (value == null || value === "") return;
      const item = document.createElement("span");
      item.innerHTML = `${escapeHtml(label)} <strong>${escapeHtml(String(value))}</strong>`;
      stats.append(item);
    };
    addStat("Dauer", formatDuration(activity.moving_time));
    addStat("Distanz", distanceLabel(activity.distance));
    addStat("Belastung", activity.icu_training_load);
    addStat("Ø Puls", activity.average_heartrate ? `${Math.round(activity.average_heartrate)} bpm` : null);
    addStat("Ø Leistung", activity.average_watts ? `${Math.round(activity.average_watts)} W` : null);
    card.append(top, meta, stats);

    const activityId = activity.id ?? activity.activityId ?? activity.external_id;
    if (activityId != null && String(activityId).trim()) {
      const feedback = activity.activity_feedback || {};
      const feedbackDetails = document.createElement("details");
      feedbackDetails.className = "activity-feedback";
      feedbackDetails.open = Boolean(feedback.notes);
      const feedbackSummary = document.createElement("summary");
      feedbackSummary.className = "activity-feedback-summary";
      const feedbackTitle = document.createElement("span");
      feedbackTitle.textContent = "Besonderheiten";
      const feedbackHint = document.createElement("span");
      feedbackHint.className = "activity-feedback-hint";
      feedbackHint.textContent = feedback.notes ? "Eintrag vorhanden" : "Nach Abschluss notieren";
      feedbackSummary.append(feedbackTitle, feedbackHint);
      const feedbackForm = document.createElement("form");
      feedbackForm.className = "activity-feedback-form";
      const feedbackLabel = document.createElement("label");
      feedbackLabel.textContent = "Gab es bei dieser Einheit Besonderheiten?";
      const feedbackInput = document.createElement("textarea");
      feedbackInput.name = "notes";
      feedbackInput.rows = 3;
      feedbackInput.maxLength = 4000;
      feedbackInput.placeholder = "Zum Beispiel Schmerzen, ungewohnte Müdigkeit oder etwas, das besonders gut lief …";
      feedbackInput.value = state.activityFeedbackDrafts.has(String(activityId))
        ? state.activityFeedbackDrafts.get(String(activityId))
        : feedback.notes || "";
      feedbackLabel.append(feedbackInput);
      const feedbackButton = document.createElement("button");
      feedbackButton.type = "submit";
      feedbackButton.textContent = "Besonderheiten speichern";
      feedbackForm.append(feedbackLabel, feedbackButton);
      feedbackInput.addEventListener("input", () => {
        const key = String(activityId);
        state.activityFeedbackDrafts.set(key, feedbackInput.value);
        state.activityFeedbackDirty.add(key);
        setDirtyIndicator("activityDirtyIndicator", true);
      });
      feedbackForm.addEventListener("submit", (event) => saveActivityFeedback(event, activity, feedbackButton));
      feedbackDetails.append(feedbackSummary, feedbackForm);
      card.append(feedbackDetails);
    }
    root.append(card);
  });
  if (displayedActivities.length > state.activityVisibleCount || state.data?.activities_next_cursor) {
    const loadMore = document.createElement("button");
    loadMore.type = "button";
    loadMore.className = "secondary-button activity-load-more";
    loadMore.textContent = displayedActivities.length > state.activityVisibleCount
      ? `Weitere Einheiten laden (${displayedActivities.length - state.activityVisibleCount} verbleibend)`
      : "Weitere Einheiten laden";
    loadMore.addEventListener("click", async () => {
      if (displayedActivities.length > state.activityVisibleCount) {
        state.activityVisibleCount += 250;
        renderActivities(state.data?.activities || []);
        return;
      }
      loadMore.disabled = true;
      try {
        const page = await api(`/api/activities?limit=250&cursor=${encodeURIComponent(state.data.activities_next_cursor)}`);
        state.data.activities = [...(state.data.activities || []), ...(page.activities || [])];
        state.data.activities_next_cursor = page.next_cursor;
        state.activityVisibleCount += 250;
        renderActivities(state.data.activities);
      } catch (error) {
        toast(error.message, true);
        loadMore.disabled = false;
      }
    });
    root.append(loadMore);
  }
}

function renderParallelCyclingWarning(groups) {
  const root = $("#parallelCyclingWarning");
  if (!root) return;
  root.replaceChildren();
  root.hidden = !groups?.length;
  if (!groups?.length) return;

  const title = document.createElement("strong");
  title.textContent = "Parallele Radeinheiten erkannt";
  const intro = document.createElement("p");
  intro.textContent = "Bitte auswählen, welche Einheit aus Intervals.icu gelöscht werden soll. Es wird nur die ausgewählte Einheit per API entfernt.";
  root.append(title, intro);
  groups.forEach((group, groupIndex) => {
    const groupRoot = document.createElement("div");
    groupRoot.className = "parallel-cycling-group";
    const options = document.createElement("div");
    options.className = "parallel-cycling-options";
    group.forEach((event, eventIndex) => {
      const label = document.createElement("label");
      label.className = "parallel-cycling-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = `parallel-cycling-${groupIndex}`;
      radio.value = String(event.id);
      radio.checked = eventIndex === 0;
      const text = document.createElement("span");
      text.textContent = `${event.name || "Radeinheit"} · ${dateLabel(event.start_date_local || event.date)}${event.type ? ` · ${event.type}` : ""}`;
      label.append(radio, text);
      options.append(label);
    });
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "secondary-button danger-button";
    deleteButton.textContent = "Ausgewählte Einheit löschen";
    deleteButton.addEventListener("click", () => {
      const selectedId = options.querySelector("input:checked")?.value;
      const selected = group.find((event) => String(event.id) === selectedId);
      if (selected) deletePlanned(selected.id, deleteButton, selected.name);
    });
    groupRoot.append(options, deleteButton);
    root.append(groupRoot);
  });
}

function renderExternalCalendarMarker(event) {
  const root = document.createElement("div");
  root.className = "planned-calendar-marker";
  root.setAttribute("role", "note");
  const title = document.createElement("strong");
  title.textContent = event.name || "Kalendereintrag";
  const markers = [
    Number(event.training_relevant) === 0 ? "Kein Training" : null,
    Number(event.no_intensity) === 1 ? "Keine Intensität" : null,
  ].filter(Boolean);
  const label = document.createElement("span");
  label.textContent = markers.join(" · ") || "Kalenderhinweis";
  const time = event.all_day ? "Ganztägig" : `${formatTime(event.start_local)} – ${formatTime(event.end_local)}`;
  const meta = document.createElement("small");
  meta.textContent = `${time} · ${event.duration_minutes || 0} Min.`;
  root.append(title, label, meta);
  return root;
}

function renderLocalPlanningActions(event, body) {
  if (!event?.is_local || !event.local_id) return;
  const actions = document.createElement("div");
  actions.className = "card-actions local-planning-actions";
  const editor = document.createElement("details");
  const editorSummary = document.createElement("summary");
  editorSummary.textContent = "Lokale Planung bearbeiten oder verschieben";
  const form = document.createElement("form");
  form.className = "local-planning-form";
  form.addEventListener("input", () => {
    const key = String(event.local_id);
    state.planningDrafts.set(key, {
      date: dateInput.value,
      name: nameInput.value,
      duration: durationInput.value,
      description: descriptionInput.value,
    });
    state.planningEditDirty.add(key);
    setDirtyIndicator("planningDirtyIndicator", true);
  });
  const planningDraft = state.planningDrafts.get(String(event.local_id)) || {};
  const dateLabel = document.createElement("label");
  dateLabel.textContent = "Datum";
  const dateInput = document.createElement("input");
  dateInput.type = "date";
  dateInput.required = true;
  dateInput.value = planningDraft.date ?? plannedEventDate(event);
  dateLabel.append(dateInput);
  const nameLabel = document.createElement("label");
  nameLabel.textContent = "Name";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.maxLength = 200;
  nameInput.required = true;
  nameInput.value = planningDraft.name ?? event.name ?? "Geplante Einheit";
  nameLabel.append(nameInput);
  const durationLabel = document.createElement("label");
  durationLabel.textContent = "Dauer (Minuten)";
  const durationInput = document.createElement("input");
  durationInput.type = "number";
  durationInput.min = "5";
  durationInput.max = "600";
  durationInput.required = true;
  durationInput.value = planningDraft.duration ?? (event.duration_minutes || Math.round(Number(event.moving_time || 0) / 60) || 30);
  durationLabel.append(durationInput);
  const descriptionLabel = document.createElement("label");
  descriptionLabel.textContent = "Workout-Text";
  const descriptionInput = document.createElement("textarea");
  descriptionInput.rows = 4;
  descriptionInput.maxLength = 12000;
  descriptionInput.required = true;
  descriptionInput.value = planningDraft.description ?? event.description ?? "";
  descriptionLabel.append(descriptionInput);
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.className = "secondary-button";
  saveButton.textContent = "Lokale Planung speichern";
  form.append(dateLabel, nameLabel, durationLabel, descriptionLabel, saveButton);
  form.addEventListener("submit", async (submitEvent) => {
    submitEvent.preventDefault();
    saveButton.disabled = true;
    saveButton.setAttribute("aria-busy", "true");
    saveButton.textContent = "Lokale Planung wird gespeichert…";
    try {
      await api(`/api/planned/local/${encodeURIComponent(event.local_id)}`, {
        method: "POST",
        body: JSON.stringify({
          action: "update",
          date: dateInput.value,
          name: nameInput.value,
          duration_minutes: Number(durationInput.value),
          description: descriptionInput.value,
        }),
      });
      state.planningEditDirty.delete(String(event.local_id));
      state.planningDrafts.delete(String(event.local_id));
      setDirtyIndicator("planningDirtyIndicator", state.planningEditDirty.size > 0);
      toast("Lokale Planung gespeichert");
      await load();
    } catch (error) {
      toast(error.message, true);
      saveButton.disabled = false;
      saveButton.removeAttribute("aria-busy");
      saveButton.textContent = "Lokale Planung speichern";
    }
  });
  editor.append(editorSummary, form);
  actions.append(editor);
  const archiveButton = document.createElement("button");
  archiveButton.type = "button";
  archiveButton.className = "secondary-button";
  archiveButton.textContent = event.archived ? "Lokale Einheit wiederherstellen" : "Lokale Einheit archivieren";
  archiveButton.addEventListener("click", async () => {
    archiveButton.disabled = true;
    try {
      await api(`/api/planned/local/${encodeURIComponent(event.local_id)}`, { method: "POST", body: JSON.stringify({ action: event.archived ? "restore" : "archive" }) });
      toast(event.archived ? "Lokale Einheit wiederhergestellt" : "Lokale Einheit archiviert");
      await load();
    } catch (error) { toast(error.message, true); archiveButton.disabled = false; }
  });
  actions.append(archiveButton);
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "secondary-button danger-button";
  deleteButton.textContent = "Nur lokal entfernen";
  deleteButton.addEventListener("click", async () => {
    if (!window.confirm(`„${event.name || "Geplante Einheit"}“ wirklich nur aus der lokalen Planung entfernen?`)) return;
    deleteButton.disabled = true;
    try {
      await api(`/api/planned/local/${encodeURIComponent(event.local_id)}`, {
        method: "POST",
        body: JSON.stringify({ action: "delete" }),
      });
      toast("Lokale Planung entfernt");
      await load();
    } catch (error) {
      toast(error.message, true);
      deleteButton.disabled = false;
    }
  });
  actions.append(deleteButton);
  body.append(actions);
}

function renderPlanned(planned, externalCalendarEvents = [], dailyPlanningContext = []) {
  setDirtyIndicator("planningDirtyIndicator", state.planningEditDirty.size > 0);
  renderParallelCyclingWarning(state.data?.parallel_cycling || []);
  renderWeatherNotice(state.data?.weather);
  const root = $("#plannedCalendar");
  state.data.daily_planning_context = Array.isArray(dailyPlanningContext) ? dailyPlanningContext : [];
  root.querySelectorAll("details.planned-week").forEach((week) => state.plannedWeekOpen.set(week.dataset.week, week.open));
  root.replaceChildren();
  const eventsByDate = new Map();
  (planned || []).forEach((event) => {
    const date = plannedEventDate(event);
    if (!date) return;
    if (!eventsByDate.has(date)) eventsByDate.set(date, []);
    eventsByDate.get(date).push(event);
  });
  const calendarEventsByDate = new Map();
  (externalCalendarEvents || [])
    .filter((event) => event && (Number(event.training_relevant) === 0 || Number(event.no_intensity) === 1))
    .forEach((event) => {
      const date = String(event.event_date || "").slice(0, 10);
      if (!date) return;
      if (!calendarEventsByDate.has(date)) calendarEventsByDate.set(date, []);
      calendarEventsByDate.get(date).push(event);
    });

  const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
  const today = dateFromKey(todayKey);
  const calendarDisplay = state.data?.calendar_display || {};
  const configuredPastWeeks = calendarDisplayValue(calendarDisplay.past_weeks, CALENDAR_DISPLAY_DEFAULTS.past_weeks);
  const configuredFutureWeeks = calendarDisplayValue(calendarDisplay.future_weeks, CALENDAR_DISPLAY_DEFAULTS.future_weeks);
  const providerWindow = state.data?.planning_view?.provider_window || {};
  const windowStartKey = String(providerWindow.start || "").slice(0, 10);
  const windowEndKey = String(providerWindow.end || "").slice(0, 10);
  const loadedPastWeeks = windowStartKey ? Math.max(0, Math.ceil(dateKeyDifference(todayKey, windowStartKey) / 7)) : configuredPastWeeks;
  const loadedFutureWeeks = windowEndKey ? Math.max(0, Math.ceil(dateKeyDifference(windowEndKey, todayKey) / 7)) : configuredFutureWeeks;
  const pastWeeks = Math.min(configuredPastWeeks, loadedPastWeeks);
  const futureWeeks = Math.min(configuredFutureWeeks, loadedFutureWeeks);
  const historyStart = new Date(today);
  historyStart.setDate(today.getDate() - pastWeeks * 7);
  const firstWeek = plannedWeekStart(historyStart);
  const currentWeekIndex = pastWeeks;
  const calendarWeeks = pastWeeks + 1 + futureWeeks;
  for (let weekIndex = 0; weekIndex < calendarWeeks; weekIndex += 1) {
    const weekStart = new Date(firstWeek);
    weekStart.setDate(firstWeek.getDate() + weekIndex * 7);
    const weekKey = localDateKey(weekStart);
    const weekEvents = [];
    for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
      const date = new Date(weekStart);
      date.setDate(weekStart.getDate() + dayIndex);
      weekEvents.push(...(eventsByDate.get(localDateKey(date)) || []));
    }

    const weekRoot = document.createElement("details");
    weekRoot.className = "planned-week";
    weekRoot.dataset.week = weekKey;
    weekRoot.open = state.plannedWeekOpen.has(weekKey) ? state.plannedWeekOpen.get(weekKey) : weekIndex === currentWeekIndex;
    weekRoot.addEventListener("toggle", () => state.plannedWeekOpen.set(weekKey, weekRoot.open));
    const weekHeading = document.createElement("summary");
    weekHeading.className = "planned-week-heading";
    const weekTitle = document.createElement("span");
    weekTitle.className = "planned-week-title";
    weekTitle.textContent = plannedWeekLabel(weekStart);
    if (weekIndex === currentWeekIndex) {
      const current = document.createElement("small");
      current.textContent = "Diese Woche";
      weekTitle.append(current);
    }
    const weekSummary = document.createElement("span");
    weekSummary.className = "planned-week-summary";
    weekSummary.textContent = plannedWeekSummary(weekEvents, weekKey);
    weekHeading.append(weekTitle, weekSummary);
    weekRoot.append(weekHeading);

    const weekDays = document.createElement("div");
    weekDays.className = "planned-week-days";
    for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
      const day = new Date(weekStart);
      day.setDate(weekStart.getDate() + dayIndex);
      const date = localDateKey(day);
      const events = eventsByDate.get(date) || [];
      const calendarEvents = calendarEventsByDate.get(date) || [];
      const dayRoot = document.createElement("section");
      dayRoot.className = "planned-day";

      const heading = document.createElement("div");
      heading.className = "planned-day-heading";
      const title = document.createElement("h3");
      title.textContent = plannedDayLabel(day, dateKeyDifference(date, todayKey));
      const count = document.createElement("span");
      count.className = "planned-day-count";
      count.textContent = events.length ? `${events.length} ${events.length === 1 ? "Einheit" : "Einheiten"}` : "frei";
      heading.append(title, count);
      dayRoot.append(heading);

      dayRoot.append(renderDailyPlanningContext(date, todayKey));
      const weather = weatherForDate(date);
      if (weather && !planningContextForDate(date).weather) {
        const weatherRoot = document.createElement("div");
        weatherRoot.className = "planned-weather";
        const icon = document.createElement("span");
        icon.className = "weather-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = weatherIconFor(weather);
        const condition = document.createElement("strong");
        condition.textContent = weather.condition || "Wetter";
        condition.title = weather.condition || "Wetter";
        const summary = document.createElement("span");
        const direction = weatherDirection(weather.wind_direction_dominant);
        summary.textContent = `${weatherNumber(weather.temperature_min, " °C")} bis ${weatherNumber(weather.temperature_max, " °C")} · Regenrisiko ${weatherNumber(weather.precipitation_probability_max, " %")} · Wind bis ${weatherNumber(weather.wind_speed_max, " km/h")} / Böen ${weatherNumber(weather.wind_gusts_max, " km/h")}${direction ? ` aus ${direction}` : ""}`;
        weatherRoot.append(icon, condition, summary);
        dayRoot.append(weatherRoot);
      }

      if (!events.length && !calendarEvents.length) {
        const empty = document.createElement("p");
        empty.className = "planned-day-empty";
        empty.textContent = "Keine Einheit geplant";
        dayRoot.append(empty);
      } else if (events.length) {
        const entries = document.createElement("div");
        entries.className = "planned-day-entries";
        events.forEach((event) => {
          const details = document.createElement("details");
          details.className = "planned-entry";
          const summary = document.createElement("summary");
          const summaryMain = document.createElement("span");
          summaryMain.className = "planned-summary-main";
          const eventTitle = document.createElement("strong");
          eventTitle.textContent = event.name || "Geplante Einheit";
          const meta = document.createElement("span");
          meta.className = "planned-meta";
          const compliance = event.compliance;
          const complianceSummary = compliance?.percentage != null ? `Umsetzung ${compliance.percentage}%` : compliance?.status === "missed" ? "Nicht umgesetzt" : compliance?.status === "completed" ? "Absolviert" : null;
          const syncLabel = event.sync_source === "local+intervals"
            ? "Lokal + Intervals.icu"
            : event.sync_source === "local"
              ? "Nur lokal"
              : "Intervals.icu";
          meta.textContent = [event.type, event.category, event.moving_time ? `Dauer ${formatDuration(event.moving_time)}` : null, syncLabel, event.sync_status, complianceSummary].filter(Boolean).join(" · ");
          summaryMain.append(eventTitle, meta);
          const recommendation = event.weather_recommendation;
          if (recommendation) {
            const weatherSlot = document.createElement("span");
            weatherSlot.className = "planned-weather-slot";
            weatherSlot.textContent = `${weatherIconFor(recommendation)} Beste Zeit ${recommendation.suggested_time}${recommendation.availability ? ` · ${recommendation.availability}` : ""}`;
            summaryMain.append(weatherSlot);
          }
          summary.append(summaryMain);
          if (compliance) details.classList.add(`planned-compliance-${compliance.status}`);
          details.append(summary);

          const body = document.createElement("div");
          body.className = "planned-entry-body";
          if (compliance) {
            const complianceRoot = document.createElement("div");
            complianceRoot.className = "planned-compliance";
            const complianceTitle = document.createElement("strong");
            complianceTitle.textContent = complianceLabel(compliance);
            complianceRoot.append(complianceTitle);
            if (compliance.status === "completed" && compliance.activity_name) {
              const completed = document.createElement("span");
              completed.textContent = `Absolviert: ${compliance.activity_name}`;
              complianceRoot.append(completed);
            }
            body.append(complianceRoot);
          }
          const privateAdjustment = event.private_calendar_adjustment;
          if (privateAdjustment) {
            const originRoot = document.createElement("div");
            originRoot.className = "planned-origin";
            const originTitle = document.createElement("strong");
            originTitle.textContent = privateAdjustment.label || "Aufgrund privater Termine angepasst";
            originRoot.append(originTitle);
            const durationChange = document.createElement("span");
            const originalMinutes = Number(privateAdjustment.original_duration_minutes);
            const adjustedMinutes = Number(privateAdjustment.adjusted_duration_minutes);
            if (Number.isFinite(originalMinutes) && Number.isFinite(adjustedMinutes)) {
              durationChange.textContent = `Dauer: ${originalMinutes} Min. → ${adjustedMinutes} Min. · Intensität reduziert`;
              originRoot.append(durationChange);
            }
            if (privateAdjustment.reason) {
              const reason = document.createElement("span");
              reason.textContent = privateAdjustment.reason;
              originRoot.append(reason);
            }
            body.append(originRoot);
          }
          if (event.description) {
            const description = document.createElement("div");
            description.className = "planned-description";
            description.textContent = event.description;
            body.append(description);
          }
          if (recommendation) {
            const recommendation = document.createElement("div");
            recommendation.className = "planned-weather-recommendation";
            const icon = document.createElement("span");
            icon.className = "weather-icon";
            icon.setAttribute("aria-hidden", "true");
            icon.textContent = weatherIconFor(event.weather_recommendation);
            const recommendationTitle = document.createElement("strong");
            recommendationTitle.textContent = `Beste Wetterzeit: ${event.weather_recommendation.suggested_time}${event.weather_recommendation.availability ? ` · ${event.weather_recommendation.availability}` : ""}`;
            const recommendationReason = document.createElement("span");
            const direction = weatherDirection(event.weather_recommendation.wind_direction);
            recommendationReason.textContent = `${event.weather_recommendation.reason || "Günstigstes verfügbares Zeitfenster laut Vorhersage."}${direction ? ` Windrichtung: ${direction}.` : ""}`;
            recommendation.append(icon, recommendationTitle, recommendationReason);
            body.append(recommendation);
          }
          if (event.local_id) {
            const identity = document.createElement("small");
            identity.className = "planned-sync-identity";
            identity.textContent = [
              event.local_id ? `Lokal-ID: ${event.local_id}` : null,
              event.remote_id ? `Remote-ID: ${event.remote_id}` : null,
            ].filter(Boolean).join(" · ");
            body.append(identity);
          } else if (event.remote_id) {
            const identity = document.createElement("small");
            identity.className = "planned-sync-identity";
            identity.textContent = `Remote-ID: ${event.remote_id}`;
            body.append(identity);
          }
          renderLocalPlanningActions(event, body);
          if (event.id != null && event.is_remote && isCoachOwnedWorkout(event)) {
            const actions = document.createElement("div");
            actions.className = "card-actions";
            const button = document.createElement("button");
            button.type = "button";
            button.className = "secondary-button danger-button";
            button.textContent = "Einheit löschen";
            button.addEventListener("click", () => deletePlanned(event.id, button, event.name));
            actions.append(button);
            body.append(actions);
          }
          details.append(body);
          entries.append(details);
        });
        dayRoot.append(entries);
      }
      if (calendarEvents.length) {
        const calendarRoot = document.createElement("div");
        calendarRoot.className = "planned-calendar-markers";
        calendarEvents.forEach((event) => calendarRoot.append(renderExternalCalendarMarker(event)));
        dayRoot.append(calendarRoot);
      }
      weekDays.append(dayRoot);
    }
    weekRoot.append(weekDays);
    root.append(weekRoot);
  }
}

async function deletePlanned(eventId, button, name) {
  if (!window.confirm(`„${name || "Geplante Einheit"}“ wirklich aus Intervals.icu löschen?`)) return;
  button.disabled = true;
  button.textContent = "Wird gelöscht…";
  try {
    await api(`/api/planned/${encodeURIComponent(eventId)}`, { method: "DELETE" });
    state.remoteDeleteFailure = null;
    toast("Geplante Einheit gelöscht");
    await load();
  } catch (error) {
    state.remoteDeleteFailure = { name: name || "Geplante Einheit", message: error.message };
    renderRemoteDeleteNotice();
    toast(error.message, true);
    button.disabled = false;
    button.textContent = "Einheit löschen";
  }
}

function chatIsNearBottom() {
  return document.documentElement.scrollHeight - (window.scrollY + window.innerHeight) <= 48;
}

function updateChatComposerVisibility() {
  const panel = $("#chatPanel");
  if (!panel) return;
  const hidden = !chatIsNearBottom();
  panel.classList.toggle("chat-composer-hidden", hidden);
  const jump = $("#chatJumpToComposer");
  if (jump) jump.hidden = !hidden || !panel.classList.contains("active");
}

function jumpToChatComposer() {
  const input = $("#messageInput");
  if (!input) return;
  const reducedMotion = Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
  let focused = false;
  const focusComposer = () => {
    if (focused) return;
    focused = true;
    updateChatComposerVisibility();
    input.focus({ preventScroll: true });
  };
  if (!reducedMotion && "onscrollend" in window) window.addEventListener("scrollend", focusComposer, { once: true });
  window.setTimeout(focusComposer, reducedMotion ? 0 : 500);
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: reducedMotion ? "auto" : "smooth" });
}

function updateChatQueueStatus() {
  const status = $("#chatQueueStatus");
  if (!status) return;
  const count = state.chatQueue.length;
  if (!state.busy || !count) {
    status.hidden = true;
    status.textContent = "";
    return;
  }
  const steering = state.chatQueue.filter((entry) => entry.mode === "steer").length;
  const queued = count - steering;
  const details = [];
  if (steering) details.push(`${steering} Steuerung${steering === 1 ? "" : "en"}`);
  if (queued) details.push(`${queued} Nachricht${queued === 1 ? "" : "en"} in der Warteschlange`);
  status.hidden = false;
  status.textContent = `${details.join(" · ")} · wird nach der aktuellen Antwort verarbeitet`;
}

function createCoachWorkingIndicator() {
  const node = document.createElement("div");
  node.id = "coachWorking";
  node.className = "coach-working";
  node.setAttribute("aria-live", "polite");
  node.innerHTML = '<span class="working-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>Coach arbeitet an deiner Antwort…</span>';
  return node;
}

function createPendingMessage(entry) {
  const node = document.createElement("div");
  node.className = "message user pending";
  node.textContent = entry.message;
  const label = document.createElement("span");
  label.className = "pending-label";
  label.textContent = entry.mode === "steer" ? "Steuerung · als Nächstes" : "Warteschlange · danach";
  node.append(label);
  return node;
}

function renderMessages(messages, forceScroll = false) {
  const root = $("#messages");
  // Synchronisation and refresh notices belong to their respective tabs,
  // not to the personal conversation history.
  const visibleMessages = (messages || []).filter((message) => message.role !== "event");
  const signature = JSON.stringify([
    visibleMessages.map((message) => [message.id || null, message.created_at || null, message.role, message.content]),
    state.busy,
    state.chatStreamText,
    state.chatQueue.map((entry) => [entry.id, entry.mode, entry.message]),
  ]);
  if (root.dataset.signature === signature) return;
  const shouldScroll = forceScroll || chatIsNearBottom();
  root.dataset.signature = signature;
  root.replaceChildren();
  if (!visibleMessages.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("strong");
    title.textContent = "Dein Coach ist bereit";
    empty.append(title, document.createTextNode("Lege deine Ziele im Profil fest. Bitte den Coach jederzeit, deine letzten Einheiten neu zu analysieren."));
    root.append(empty);
  }
  for (const message of visibleMessages) {
    const node = document.createElement("div");
    node.className = `message ${message.role}`;
    if (message.role === "assistant") node.innerHTML = markdownToHtml(message.content);
    else node.textContent = message.content;
    root.append(node);
  }
  for (const entry of state.chatQueue) root.append(createPendingMessage(entry));
  if (state.busy && state.chatStreamText) {
    const node = document.createElement("div");
    node.className = "message assistant streaming";
    node.innerHTML = markdownToHtml(state.chatStreamText);
    root.append(node);
  }
  if (state.busy) root.append(createCoachWorkingIndicator());
  updateChatQueueStatus();
  updateChatComposerVisibility();
  if (shouldScroll) scrollChatToLatest();
}

function scrollChatToLatest() {
  const panel = $("#chatPanel");
  const root = $("#messages");
  if (!panel?.classList.contains("active") || !root) return;
  requestAnimationFrame(() => {
    const target = root.lastElementChild;
    if (!target) return;
    const composer = $("#chatForm");
    const targetBottom = target.getBoundingClientRect().bottom;
    const composerTop = composer?.getBoundingClientRect().top;
    const targetGap = 12;
    const desiredBottom = Number.isFinite(composerTop)
      ? composerTop - targetGap
      : window.innerHeight - targetGap;
    window.scrollTo({ top: Math.max(0, window.scrollY + targetBottom - desiredBottom), behavior: "auto" });
  });
}

function renderContextPreview(preview) {
  const status = $("#systemContextPreviewStatus");
  const content = $("#systemContextPreviewContent");
  if (!status || !content) return;
  content.replaceChildren();
  content.hidden = true;
  if (!preview) {
    status.textContent = "Noch nicht geladen.";
    status.classList.remove("error");
    return;
  }
  const sections = [
    ["Zusammensetzung", preview.assembly],
    ["Dauerhaftes Profil", preview.structured_athlete_context?.durable_profile],
    ["Zielwettkämpfe", preview.structured_athlete_context?.target_competitions],
    ["Aktuelle Leistungsdaten", preview.structured_athlete_context?.current_performance],
    ["Garmin-Kontext", preview.structured_athlete_context?.garmin],
    ["Gesprächskontinuität", preview.conversation],
    ["Intervals.icu-Snapshot", preview.latest_intervals_snapshot],
    ["Letzte Chat-Eingabe (input)", preview.chat_prompt],
    ["Kontext (instructions)", preview.context_text],
  ];
  sections.forEach(([title, value], index) => {
    if (value == null) return;
    const details = document.createElement("details");
    if (index < 4) details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    details.append(summary, pre);
    content.append(details);
  });
  status.classList.remove("error");
  status.textContent = `Zuletzt erstellt: ${formatTime(preview.generated_at)}${preview.snapshot_compacted ? " (Snapshot für den Coach kompakt aufbereitet)" : preview.snapshot_truncated ? " (Snapshot im Coach-Kontext gekürzt)" : ""}`;
  content.hidden = false;
}

function invalidateContextPreview() {
  const button = $("#systemContextPreviewButton");
  if (!button) return;
  button.dataset.loaded = "false";
  button.textContent = "Kontext aktualisieren";
}

async function loadContextPreview() {
  const button = $("#systemContextPreviewButton");
  const status = $("#systemContextPreviewStatus");
  if (!button || !status || button.dataset.loaded === "true") return;
  button.disabled = true;
  button.textContent = "Kontext wird geladen…";
  status.classList.remove("error");
  status.textContent = "Der aktuelle Coach-Kontext wird zusammengestellt…";
  try {
    const preview = await api("/api/context-preview");
    renderContextPreview(preview);
    button.dataset.loaded = "true";
    button.textContent = "Kontext aktualisieren";
  } catch (error) {
    status.classList.add("error");
    status.textContent = error.message;
    button.textContent = "Kontext laden";
  } finally { button.disabled = false; }
}

function renderTrainingPlans(plans, workouts) {
  const root = $("#trainingPlans");
  if (!root) return;
  root.replaceChildren();
  const entries = (workouts || []).filter((item) => item && item.plan_id && !item.archived);
  if (!Array.isArray(plans) || !plans.length) return;
  const heading = document.createElement("h3");
  heading.className = "subsection-title";
  heading.textContent = "Mehrwochenpläne";
  root.append(heading);
  plans.forEach((plan) => {
    const planEntries = entries.filter((item) => String(item.plan_id) === String(plan.id));
    const details = document.createElement("details");
    details.className = "training-plan";
    const summary = document.createElement("summary");
    const title = document.createElement("strong");
    title.textContent = plan.name || "Mehrwochenplan";
    const meta = document.createElement("span");
    meta.textContent = [plan.start_date && plan.end_date ? `${dateLabel(plan.start_date)} – ${dateLabel(plan.end_date)}` : null, `${planEntries.length} Einheiten`, plan.status].filter(Boolean).join(" · ");
    summary.append(title, meta);
    details.append(summary);
    const body = document.createElement("div");
    body.className = "training-plan-body";
    if (plan.goal) {
      const goal = document.createElement("p");
      goal.textContent = plan.goal;
      body.append(goal);
    }
    planEntries.sort((a, b) => String(a.date || "").localeCompare(String(b.date || ""))).forEach((entry) => {
      const item = document.createElement("div");
      item.className = "training-plan-entry";
      item.textContent = `${entry.date ? dateLabel(entry.date) : "Ohne Datum"} · ${entry.name || "Einheit"} · ${entry.duration_minutes || Math.round(Number(entry.moving_time || 0) / 60) || "?"} Min.`;
      body.append(item);
    });
    if (!planEntries.length) {
      const empty = document.createElement("p");
      empty.className = "fine-print";
      empty.textContent = "Keine aktiven Einheiten zu diesem Plan vorhanden.";
      body.append(empty);
    }
    details.append(body);
    root.append(details);
  });
}

function renderLibrary(workouts) {
  const root = $("#library");
  if (!root) return;
  setDirtyIndicator("libraryDirtyIndicator", state.libraryDateDirty.size > 0);
  root.replaceChildren();
  const allWorkouts = Array.isArray(workouts) ? workouts : [];
  const filter = state.libraryFilter || "active";
  const filterSelect = $("#libraryFilter");
  if (filterSelect && filterSelect.value !== filter) filterSelect.value = filter;
  const visible = allWorkouts.filter((workout) => {
    if (filter === "archived") return Boolean(workout.archived);
    if (filter === "all") return true;
    if (filter === "templates") return !workout.archived && !workout.date;
    if (filter === "planned") return !workout.archived && Boolean(workout.date);
    return !workout.archived;
  });
  const librarySummary = $("#librarySummary");
  if (librarySummary) librarySummary.textContent = `${visible.length} von ${allWorkouts.length} Einheiten`;
  renderLibraryPagination();
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = filter === "archived" ? "Keine archivierten Einheiten vorhanden." : "Keine Einheiten für diesen Filter gefunden.";
    root.append(empty);
    return;
  }
  const groups = new Map();
  visible.forEach((workout) => {
    const sport = activitySportLabel(workout);
    if (!groups.has(sport)) groups.set(sport, []);
    groups.get(sport).push(workout);
  });
  [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "de"))
    .forEach(([sport, sportWorkouts]) => {
      const section = document.createElement("details");
      section.className = "library-sport";
      const summary = document.createElement("summary");
      const title = document.createElement("strong");
      title.textContent = sport;
      summary.append(title);
      section.append(summary);
      const cards = document.createElement("div");
      cards.className = "library-sport-cards";
      sportWorkouts.forEach((workout) => {
        const card = document.createElement("article");
        card.className = "library-card";
        if (workout.archived) card.classList.add("library-card-archived");
        const heading = document.createElement("div");
        const cardTitle = document.createElement("h4");
        cardTitle.textContent = workout.name || "Bibliotheks-Einheit";
        const meta = document.createElement("span");
        const syncLabel = workout.sync_status === "remote_missing"
          ? "Remote nicht gefunden - wird beim nächsten Sync neu abgeglichen"
          : workout.sync_status === "sync_error"
            ? "Synchronisationsfehler - beim nächsten Sync erneut versuchen"
            : workout.sync_status === "syncing"
              ? "Synchronisierung läuft"
              : workout.sync_status === "local"
                ? "Lokal - noch nicht synchronisiert"
                : workout.external_id
                  ? "Mit Intervals.icu synchronisiert"
                  : "Lokal";
        meta.textContent = [workout.date ? `Geplant: ${dateLabel(workout.date)}` : null, workout.type, workout.moving_time ? formatDuration(workout.moving_time) : null, syncLabel].filter(Boolean).join(" - ");
        heading.append(cardTitle, meta);
        const description = document.createElement("p");
        description.textContent = workout.description || "Kein Workout-Text hinterlegt.";
        const controls = document.createElement("div");
        controls.className = "library-controls";
        const dateLabelNode = document.createElement("label");
        dateLabelNode.textContent = "Datum";
        const dateInput = document.createElement("input");
        dateInput.type = "date";
        dateInput.value = state.libraryDateDrafts.get(String(workout.id))
          ?? addDateKey(timezoneDateKey(state.data?.profile?.timezone, new Date()), 1);
        const markLibraryDateDirty = () => {
          const key = String(workout.id);
          state.libraryDateDrafts.set(key, dateInput.value);
          state.libraryDateDirty.add(key);
          setDirtyIndicator("libraryDirtyIndicator", true);
        };
        dateInput.addEventListener("input", markLibraryDateDirty);
        dateInput.addEventListener("change", markLibraryDateDirty);
        dateLabelNode.append(dateInput);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary-button";
        button.textContent = "Als lokale Einheit einplanen";
        button.addEventListener("click", () => planLibraryWorkout(workout.id, dateInput, button));
        controls.append(dateLabelNode, button);
        if (!workout.date) {
          const editor = document.createElement("details");
          editor.className = "library-editor";
          const editorSummary = document.createElement("summary");
          editorSummary.textContent = "Vorlage bearbeiten";
          const form = document.createElement("form");
          form.className = "library-edit-form";
          const nameInput = document.createElement("input");
          nameInput.value = workout.name || "";
          nameInput.maxLength = 200;
          nameInput.required = true;
          const descriptionInput = document.createElement("textarea");
          descriptionInput.value = workout.description || "";
          descriptionInput.maxLength = 12000;
          descriptionInput.rows = 3;
          const save = document.createElement("button");
          save.type = "submit";
          save.className = "secondary-button";
          save.textContent = "Speichern";
          form.append(nameInput, descriptionInput, save);
          form.addEventListener("submit", async (event) => {
            event.preventDefault();
            save.disabled = true;
            try { await updateLibraryEntry(workout.id, { action: "update", name: nameInput.value, description: descriptionInput.value }); toast("Bibliothekseinheit gespeichert"); await load(); }
            catch (error) { toast(error.message, true); save.disabled = false; }
          });
          editor.append(editorSummary, form);
          controls.append(editor);
          const archive = document.createElement("button");
          archive.type = "button";
          archive.className = "secondary-button";
          archive.textContent = workout.archived ? "Wiederherstellen" : "Archivieren";
          archive.addEventListener("click", () => updateLibraryEntry(workout.id, { action: workout.archived ? "restore" : "archive" }));
          controls.append(archive);
          if (!workout.external_id) {
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "secondary-button danger-button";
            remove.textContent = "Löschen";
            remove.addEventListener("click", () => {
              if (window.confirm(`„${workout.name || "Bibliothekseinheit"}“ wirklich lokal löschen?`)) updateLibraryEntry(workout.id, { action: "delete" });
            });
            controls.append(remove);
          }
        }
        card.append(heading, description, controls);
        cards.append(card);
      });
      section.append(cards);
      root.append(section);
    });
}

function renderLibraryPagination() {
  const pagination = $("#libraryPagination");
  if (!pagination) return;
  pagination.replaceChildren();
  if (!state.data?.library_next_cursor) return;
  const more = document.createElement("button");
  more.type = "button";
  more.className = "secondary-button";
  more.textContent = "Weitere lokale Vorlagen laden";
  more.addEventListener("click", loadMoreLibrary);
  pagination.append(more);
}

async function loadMoreLibrary() {
  const pagination = $("#libraryPagination");
  const cursor = state.data?.library_next_cursor;
  if (!pagination || !cursor) return;
  const button = pagination.querySelector("button");
  if (button) { button.disabled = true; button.textContent = "Weitere Vorlagen werden geladen…"; }
  try {
    const result = await api(`/api/library?limit=100&cursor=${encodeURIComponent(cursor)}`);
    state.data.library = [...(state.data.library || []), ...(result.workouts || [])];
    state.data.library_next_cursor = result.next_cursor;
    renderLibrary(state.data.library);
  } catch (error) {
    toast(error.message, true);
    if (button) button.disabled = false;
  }
}

async function loadLibrary() {
  const button = $("#libraryLoadButton");
  const root = $("#library");
  if (!button || !root) return;
  if (state.data?.provider_resync?.intervals?.running || state.localSync.intervalsFull) {
    toast("Intervals.icu wird gerade vollständig neu geladen.", true);
    return;
  }
  button.disabled = true;
  button.textContent = "Bibliothek wird geladen…";
  try {
    const preview = await api("/api/library/sync/preview", { method: "POST", body: "{}" });
    const summary = preview.summary || {};
    const changeCount = Object.values(summary).reduce((total, value) => total + Number(value || 0), 0);
    const confirmed = window.confirm(
      `Bibliothekssync zu Intervals.icu freigeben? ${changeCount} lokale Einträge: ` +
      `${summary.new || 0} neu, ${summary.changed || 0} geändert, ` +
      `${summary.missing || 0} fehlend, ${summary.error_retry || 0} Fehlerwiederholung. ` +
      "Die Vorschau ist nur 10 Minuten gültig."
    );
    if (!confirmed) return;
    const actionPreview = await api("/api/coach/actions/preview", {
      method: "POST",
      body: JSON.stringify({
        action_type: "sync_workout_library",
        target_system: "intervals",
        object_ids: {},
        diff: preview.entries || [],
        payload: { fingerprint: preview.fingerprint },
      }),
    });
    const confirmedAction = await api("/api/coach/actions/confirm", {
      method: "POST",
      body: JSON.stringify({ proposal_id: actionPreview.proposed_action.id }),
    });
    await api("/api/coach/actions/execute", {
      method: "POST",
      body: JSON.stringify({ action_token: confirmedAction.action_token, payload_hash: confirmedAction.proposed_action.payload_hash }),
    });
    await load();
  } catch (error) {
    root.replaceChildren();
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = error.message;
    root.append(message);
  } finally {
    button.disabled = false;
    button.textContent = "Vorschau für Remote-Sync öffnen";
  }
}

async function updateLibraryEntry(id, payload) {
  try {
    await api(`/api/library/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify(payload) });
    toast(payload.action === "archive" ? "Bibliothekseinheit archiviert" : payload.action === "restore" ? "Bibliothekseinheit wiederhergestellt" : payload.action === "delete" ? "Bibliothekseinheit gelöscht" : "Bibliothekseinheit gespeichert");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function planLibraryWorkout(workoutId, dateInput, button) {
  if (!dateInput.value) { toast("Bitte ein Datum auswählen", true); return; }
  button.disabled = true;
  button.textContent = "Lokale Einheit wird gespeichert…";
  try {
    await api("/api/library/" + encodeURIComponent(workoutId) + "/plan", { method: "POST", body: JSON.stringify({ date: dateInput.value }) });
    state.libraryDateDirty.delete(String(workoutId));
    state.libraryDateDrafts.delete(String(workoutId));
    setDirtyIndicator("libraryDirtyIndicator", state.libraryDateDirty.size > 0);
    toast("Lokale Bibliothekseinheit gespeichert");
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Als lokale Einheit einplanen"; }
}

function renderProfile(profile) {
  setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
  if (state.profileDirty) return;
  const form = $("#profileForm");
  for (const [key, value] of Object.entries(profile)) {
    const field = form.elements[key];
    if (!field) continue;
    if (key === "sports" && field.multiple) {
      const selectedSports = String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
      [...field.options].forEach((option) => { option.selected = selectedSports.includes(option.value); });
      continue;
    }
    if (key === "timezone" && field.tagName === "SELECT") {
      if (value && ![...field.options].some((option) => option.value === value)) field.append(new Option(`${value} (gespeichert)`, value));
      field.value = value || "";
      continue;
    }
    field.value = value || "";
  }
  renderWeeklyAvailability(profile.availability_schedule);
  if (form.elements.coaching_style?.value === "Supportive, direct, and evidence-aware") form.elements.coaching_style.value = "Unterstützend, direkt und evidenzbasiert";
  const summary = $("#profileSummary");
  if (summary) {
    const values = [profile.name, profile.sports, profile.typical_weekly_volume].filter(Boolean);
    summary.textContent = values.length ? values.join(" · ") : "Noch nicht ausgefüllt";
  }
}

const WEEKDAY_LABELS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];

function availabilityInput(labelText, name, type, value, attributes = {}) {
  const label = document.createElement("label");
  label.textContent = labelText;
  const input = document.createElement(type === "select" ? "select" : "input");
  input.name = name;
  input.type = type === "select" ? "text" : type;
  input.value = value || "";
  Object.entries(attributes).forEach(([key, attributeValue]) => input.setAttribute(key, attributeValue));
  label.append(input);
  return label;
}

function renderWeeklyAvailability(schedule = []) {
  const root = $("#weeklyAvailabilityEditor");
  if (!root) return;
  const entries = Array.isArray(schedule) ? schedule : [];
  root.className = "weekly-availability";
  root.replaceChildren();
  WEEKDAY_LABELS.forEach((dayLabel, weekday) => {
    const entry = entries.find((item) => Number(item?.weekday) === weekday) || {};
    const periods = entry.periods || {};
    const day = document.createElement("div");
    day.className = "availability-day";
    day.dataset.availabilityDay = String(weekday);
    const heading = document.createElement("strong");
    heading.textContent = dayLabel;
    const fields = document.createElement("div");
    fields.className = "availability-day-fields";
    for (const [period, label] of [["early", "Früh"], ["late", "Spät"]]) {
      const window = periods[period] || {};
      fields.append(
        availabilityInput(`${label} von`, `availability-${weekday}-${period}-start`, "time", window.start),
        availabilityInput(`${label} bis`, `availability-${weekday}-${period}-end`, "time", window.end)
      );
    }
    fields.append(availabilityInput("Max. Minuten", `availability-${weekday}-max`, "number", entry.max_minutes, { min: "0", max: "1440", step: "1", placeholder: "Optional" }));
    const environment = availabilityInput("Umgebung", `availability-${weekday}-environment`, "select", entry.environment || "either");
    environment.querySelector("select").replaceChildren(
      new Option("Drinnen oder draußen", "either"),
      new Option("Nur drinnen", "indoor"),
      new Option("Nur draußen", "outdoor")
    );
    environment.querySelector("select").value = entry.environment || "either";
    fields.append(environment);
    fields.append(availabilityInput("Notiz", `availability-${weekday}-note`, "text", entry.note, { maxlength: "500", placeholder: "Optional" }));
    day.append(heading, fields);
    root.append(day);
  });
}

function collectWeeklyAvailability() {
  return [...document.querySelectorAll("[data-availability-day]")].map((day) => {
    const weekday = Number(day.dataset.availabilityDay);
    const value = (name) => day.querySelector(`[name="availability-${weekday}-${name}"]`)?.value.trim() || "";
    const periods = {};
    for (const period of ["early", "late"]) {
      const start = value(`${period}-start`);
      const end = value(`${period}-end`);
      if (start || end) periods[period] = { start, end };
    }
    const max = value("max");
    const note = value("note");
    if (!Object.keys(periods).length && !max && !note) return null;
    return { weekday, periods, max_minutes: max, environment: value("environment") || "either", note };
  }).filter(Boolean);
}

function populateCheckin(checkin, timeZone) {
  const form = $("#checkinForm");
  if (!form) return;
  const values = checkin || { checkin_date: timezoneDateKey(timeZone) };
  for (const field of ["checkin_date", "soreness", "stress", "motivation", "session_rpe", "day_form", "available_minutes", "illness", "pain", "availability_notes", "notes"]) {
    if (form.elements[field]) form.elements[field].value = values[field] ?? "";
  }
  state.checkinSelectedDate = values.checkin_date || null;
  state.checkinDirty = false;
}

function openCheckinEditor(date) {
  const dialog = $("#checkinDialog");
  const form = $("#checkinForm");
  if (!dialog || !form) return;
  const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
  if (date > todayKey) return;
  const checkin = (state.data?.checkins || []).find((row) => row.checkin_date === date) || { checkin_date: date };
  form.elements.checkin_date.max = todayKey;
  populateCheckin(checkin, state.data?.profile?.timezone);
  renderCheckins(state.data?.checkins || [], state.data?.profile?.timezone);
  if (state.route !== "today") applyNavigationRoute("today", { historyMode: "push", focus: false });
  // The dialog may still be nested in a hidden panel in older cached markup.
  // Move it to the document root before opening so that panel cannot suppress the modal.
  if (dialog.parentElement?.classList.contains("panel")) document.body.append(dialog);
  showAccessibleDialog(dialog, form.elements.soreness);
}

function renderCheckins(checkins, timeZone) {
  const form = $("#checkinForm");
  const history = $("#checkinHistory");
  if (!form || !history) return;
  setDirtyIndicator("checkinDirtyIndicator", state.checkinDirty);
  const rows = Array.isArray(checkins) ? checkins : [];
  if (!state.checkinDirty) {
    const selected = rows.find((row) => row.checkin_date === state.checkinSelectedDate)
      || (!state.checkinSelectedDate ? rows.find((row) => row.checkin_date === timezoneDateKey(timeZone)) : null);
    populateCheckin(selected || (state.checkinSelectedDate ? { checkin_date: state.checkinSelectedDate } : null), timeZone);
  }
  history.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "fine-print";
    empty.textContent = "Noch kein Tages-Check-in gespeichert.";
    history.append(empty);
    return;
  }
  const heading = document.createElement("strong");
  heading.textContent = "Gespeicherte Check-ins";
  history.append(heading);
  for (const row of rows) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "checkin-history-item";
    button.classList.toggle("selected", row.checkin_date === state.checkinSelectedDate);
    const title = document.createElement("strong");
    title.textContent = dateLabel(row.checkin_date);
    const values = [
      row.day_form ? `Tagesform: ${row.day_form}` : null,
      row.soreness != null ? `Schmerz/Muskelkater ${row.soreness}/10` : null,
      row.stress != null ? `Stress ${row.stress}/10` : null,
      row.motivation != null ? `Motivation ${row.motivation}/10` : null,
      row.illness ? `Krankheit: ${row.illness}` : null,
      row.pain ? "Schmerz notiert" : null,
    ].filter(Boolean);
    const summary = document.createElement("span");
    summary.textContent = values.join(" · ") || "Ohne Bewertungen";
    button.append(title, summary);
    button.addEventListener("click", () => {
      populateCheckin(row, timeZone);
      renderCheckins(rows, timeZone);
    });
    history.append(button);
  }
}

function renderGarmin(garmin) {
  const status = $("#garminStatus");
  const detail = $("#garminDetail");
  const button = $("#garminSyncButton");
  const fullButton = $("#garminFullResyncButton");
  const fullStatus = $("#garminFullResyncStatus");
  if (!status || !detail || !button) return;
  const fullResync = state.data?.provider_resync?.garmin || {};
  const fullRunning = Boolean(fullResync.running || state.localSync.garminFull);
  button.disabled = Boolean(state.data?.garmin_sync?.running || fullRunning);
  if (!garmin?.available) {
    status.textContent = "Garmin nicht verfügbar";
    detail.textContent = "";
    button.disabled = true;
    if (fullButton) fullButton.disabled = true;
    return;
  }
  if (!garmin.configured) {
    status.textContent = "Garmin nicht eingerichtet";
    detail.textContent = "";
    button.disabled = true;
    if (fullButton) fullButton.disabled = true;
    return;
  }
  const performanceSources = [garmin.has_vo2max ? "VO2max" : null, garmin.has_estimated_run_times ? "Laufprognosen" : null, garmin.has_max_hr ? "Max HF" : null, garmin.has_weight ? "Gewicht" : null].filter(Boolean);
  const paginationDetail = Object.entries(garmin.pagination || {})
    .filter(([, value]) => value && (Number(value.windows) > 1 || value.complete === false))
    .map(([name, value]) => `${name}: ${value.records || 0} Datensätze in ${value.windows || 0} Zeitfenstern${value.complete === false ? " · unvollständig" : ""}`)
    .join(" · ");
  status.textContent = garmin.source === "fixture"
    ? "Lokale Garmin-Testdaten aktiv"
    : garmin.last_error ? "Mit Fehlern synchronisiert" : "Optionaler Direktabruf aktiv";
  detail.textContent = garmin.last_sync_at
    ? `Letzter Abruf: ${formatTime(garmin.last_sync_at)} · ${garmin.activities || 0} Aktivitäten · Schlaf/HRV/Readiness ${[garmin.has_sleep, garmin.has_hrv, garmin.has_readiness].filter(Boolean).length}/3`
    : garmin.source === "fixture" ? "Testdatei ist konfiguriert; synchronisiere sie mit dem Button."
      : "Noch kein Garmin-Abruf durchgeführt.";
  if (performanceSources.length) detail.textContent += ` · ${performanceSources.join("/")} aus Garmin`;
  if (paginationDetail) detail.textContent += ` · ${paginationDetail}`;
  if (fullButton) {
    fullButton.disabled = fullRunning || Boolean(state.data?.garmin_sync?.running || state.localSync.garmin);
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  if (fullStatus) {
    fullStatus.classList.toggle("error", Boolean(fullResync.last_error));
    fullStatus.textContent = fullRunning && fullResync.status
      ? fullResync.status
      : fullResync.last_error
        ? fullResync.last_error
        : fullResync.last_resync_at
          ? `Letzter vollständiger Resync: ${formatTime(fullResync.last_resync_at)}`
          : "Löscht nur lokale Garmin-Daten; Zugangsdaten und Cloud bleiben unverändert.";
  }
}

function contextField(labelText, field, value = "", options = {}) {
  const label = document.createElement("label");
  label.textContent = labelText;
  let input;
  if (options.choices) {
    input = document.createElement("select");
    for (const choice of options.choices) {
      const option = document.createElement("option");
      option.value = typeof choice === "string" ? choice : choice.value;
      option.textContent = typeof choice === "string" ? choice : choice.label;
      input.append(option);
    }
  } else if (options.multiline) {
    input = document.createElement("textarea");
    input.rows = options.rows || 2;
  } else {
    input = document.createElement("input");
    input.type = options.type || "text";
  }
  input.dataset.field = field;
  input.value = value || "";
  if (options.placeholder) input.placeholder = options.placeholder;
  label.append(input);
  return label;
}

function competitionEditor(competition = {}, index = 0) {
  const card = document.createElement("article");
  card.className = "competition-editor";
  card.dataset.id = competition.id || "";

  const top = document.createElement("div");
  top.className = "competition-editor-top";
  const title = document.createElement("strong");
  title.textContent = competition.name || `Wettkampf ${index + 1}`;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-context-button";
  remove.textContent = "Entfernen";
  remove.addEventListener("click", () => {
    card.remove();
    state.profileDirty = true;
  });
  top.append(title, remove);

  if (competition.sync_state === "conflict") {
    const conflict = document.createElement("div");
    conflict.className = "competition-conflict";
    const remote = (() => {
      try { return JSON.parse(competition.sync_conflict || "{}").remote || {}; } catch (_) { return {}; }
    })();
    const message = document.createElement("span");
    message.textContent = remote.name
      ? `Konflikt: Remote enthält „${remote.name}“ am ${dateLabel(remote.event_date || "")}.`
      : "Konflikt: Das Remote-Event konnte nicht eindeutig zugeordnet werden.";
    const actions = document.createElement("div");
    actions.className = "competition-conflict-actions";
    for (const [strategy, labelText] of [["keep_local", "Lokal behalten"], ["adopt_remote", "Remote übernehmen"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button";
      button.textContent = labelText;
      button.addEventListener("click", () => resolveCompetitionConflict(competition.id, strategy, button));
      actions.append(button);
    }
    conflict.append(message, actions);
    card.append(conflict);
  } else if (competition.sync_state === "local_override") {
    const status = document.createElement("small");
    status.className = "competition-sync-state";
    status.textContent = "Lokal priorisiert · beim nächsten Sync wird das Remote-Event aktualisiert";
    card.append(status);
  }

  const mainGrid = document.createElement("div");
  mainGrid.className = "form-grid";
  mainGrid.append(
    contextField("Name", "name", competition.name, { placeholder: "Münsterland Giro" }),
    contextField("Datum", "event_date", competition.event_date, { type: "date" }),
    contextField("Startzeit (lokal)", "start_date_local", (competition.start_date_local || "").slice(0, 16), { type: "datetime-local" }),
    contextField("Sportart", "sport", competition.sport || "Cycling", { choices: [{ value: "Cycling", label: "Radfahren" }, { value: "Ride", label: "Radfahren (Provider)" }, { value: "VirtualRide", label: "Rad indoor" }, { value: "Running", label: "Laufen" }, { value: "Run", label: "Laufen (Provider)" }, { value: "Swim", label: "Schwimmen" }, { value: "Strength", label: "Krafttraining" }, { value: "Other", label: "Andere" }] }),
    contextField("Kategorie", "category", competition.category || `RACE_${competition.priority || "B"}`, { choices: [{ value: "RACE_A", label: "A · Hauptwettkampf" }, { value: "RACE_B", label: "B · Aufbauwettkampf" }, { value: "RACE_C", label: "C · Trainingswettkampf" }] }),
    contextField("Dauer (hh:mm)", "moving_time", competition.moving_time == null ? "" : `${String(Math.floor(Number(competition.moving_time) / 3600)).padStart(2, "0")}:${String(Math.floor(Number(competition.moving_time) % 3600 / 60)).padStart(2, "0")}`, { type: "time", step: 60 }),
    contextField("Distanz (km)", "distance", competition.distance ? String((Number(competition.distance) / 1000).toLocaleString("en-US", { maximumFractionDigits: 3 })) : "", { type: "number", step: "0.001", min: "0", placeholder: "125" }),
    contextField("Externe ID", "external_id", competition.external_id, { placeholder: "Wird automatisch vergeben" })
  );
  card.append(
    top,
    mainGrid,
    contextField("Ergebnisziel", "target", competition.target, { multiline: true, placeholder: "Zielzeit, Platzierung, Finish-Ziel…" }),
    contextField("Streckenprofil", "course_profile", competition.course_profile, { multiline: true, placeholder: "Höhenmeter, Technik, erwartete Dauer…" }),
    contextField("Beschreibung", "description", competition.description, { multiline: true, placeholder: "Beschreibung des Intervals.icu-Events…" }),
    contextField("Notizen", "notes", competition.notes, { multiline: true })
  );
  return card;
}

function renderCompetitions(competitions) {
  if (state.profileDirty) return;
  const root = $("#competitionList");
  const summary = $("#plannedCompetitionsSummary");
  if (summary) {
    const next = competitions.filter((competition) => competition.event_date).sort((a, b) => String(a.event_date).localeCompare(String(b.event_date)))[0];
    summary.textContent = competitions.length
      ? `${competitions.length} ${competitions.length === 1 ? "Wettkampf" : "Wettkämpfe"}${next ? ` · nächster ${dateLabel(next.event_date)}` : ""}`
      : "Noch keine Wettkämpfe";
  }
  root.replaceChildren();
  if (!competitions.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Noch keine Zielwettkämpfe gespeichert.";
    root.append(empty);
    return;
  }
  competitions.forEach((competition, index) => root.append(competitionEditor(competition, index)));
}

function renderCompetitionSync(data) {
  const sync = data.competition_sync || {};
  const fullRunning = Boolean(data.provider_resync?.intervals?.running || state.localSync.intervalsFull);
  const button = $("#competitionSyncButton");
  const detail = $("#competitionSyncDetail");
  if (button) {
    button.disabled = Boolean(sync.running || state.localSync.competitions || fullRunning);
    button.textContent = sync.running || state.localSync.competitions ? "Remote-Sync läuft…" : "Vorschau für Wettkampf-Push";
  }
  if (detail) {
    detail.textContent = sync.last_error
      ? sync.last_error
      : sync.running
        ? (sync.status || "Zielwettkämpfe werden synchronisiert…")
        : sync.last_sync_at
          ? `Letzte Aktualisierung: ${formatTime(sync.last_sync_at)}`
          : "Status: noch nicht synchronisiert";
    detail.classList.toggle("error", Boolean(sync.last_error));
  }
}

async function resolveCompetitionConflict(competitionId, strategy, button) {
  if (!competitionId) return;
  if (state.profileDirty) {
    toast("Bitte zuerst die lokalen Profiländerungen speichern oder verwerfen.", true);
    return;
  }
  button.disabled = true;
  try {
    await api(`/api/competitions/${encodeURIComponent(competitionId)}/resolve`, {
      method: "POST",
      body: JSON.stringify({ strategy }),
    });
    toast(strategy === "adopt_remote" ? "Remote-Wettkampf übernommen" : "Lokaler Wettkampf wird priorisiert");
    invalidateContextPreview();
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

function collectCompetitions() {
  return [...document.querySelectorAll(".competition-editor")].map((card) => {
    const competition = { id: card.dataset.id || "" };
    card.querySelectorAll("[data-field]").forEach((input) => {
      const field = input.dataset.field;
      const value = input.value.trim();
      if (field === "moving_time") {
        const [hours, minutes] = value.split(":").map(Number);
        competition[field] = value && Number.isFinite(hours) && Number.isFinite(minutes) ? hours * 3600 + minutes * 60 : "";
      } else if (field === "distance") {
        const kilometers = Number(value.replace(",", "."));
        competition[field] = value && Number.isFinite(kilometers) ? String(Math.round(kilometers * 1000)) : "";
      } else competition[field] = value;
    });
    return competition;
  });
}

function addCompetition() {
  const root = $("#competitionList");
  root.querySelector(".context-empty")?.remove();
  root.append(competitionEditor({}, root.querySelectorAll(".competition-editor").length));
  state.profileDirty = true;
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const total = Math.round(Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}` : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatWhole(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number).toLocaleString("de-DE") : String(value);
}

function formatPace(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const total = Math.round(Number(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")} min/km`;
}

function comparisonText(comparison) {
  if (!comparison || comparison.delta == null) return null;
  const delta = Number(comparison.delta);
  if (!Number.isFinite(delta)) return null;
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const precision = comparison.unit === "" || comparison.unit === "bpm" || comparison.unit === "ms" ? 0 : 1;
  const amount = Math.abs(delta).toFixed(precision).replace(".", ",");
  const unit = comparison.unit ? ` ${comparison.unit}` : "";
  const arrow = comparison.direction === "up" ? "↑" : comparison.direction === "down" ? "↓" : "→";
  return { text: `${arrow} ${sign}${amount}${unit}`, className: comparison.color || "neutral", title: `Vergleich zum ${comparison.label || `${comparison.days}-Tage-Durchschnitt`}` };
}

function metricSourceClass(source) {
  if (source === "Garmin Connect") return "metric-garmin";
  if (source === "Manuell") return "metric-manual";
  if (source && (source.startsWith("Intervals.icu") || source === "Aus Aktivitäten")) return "metric-intervals";
  return "";
}

function metricToneClass(label, value) {
  if (!label.startsWith("Form") || !Number.isFinite(Number(value))) return "";
  const tsb = Number(value);
  if (tsb >= -10 && tsb <= 5) return "metric-form-good";
  if (tsb >= -20 && tsb <= 15) return "metric-form-caution";
  return "metric-form-bad";
}

function displayMetric(root, label, metricData, formatter = null, editable = null) {
  const item = document.createElement("div");
  const metric = document.createElement("strong");
  const caption = document.createElement("span");
  const source = document.createElement("small");
  const value = metricData && typeof metricData === "object" ? metricData.value : metricData;
  const unit = metricData && typeof metricData === "object" ? metricData.unit : "";
  metric.textContent = value == null ? "—" : (formatter ? formatter(value) : `${value}${unit ? ` ${unit}` : ""}`);
  caption.textContent = label;
  source.textContent = metricData?.source || "Nicht verfügbar";
  source.title = metricData?.note || metricData?.source || "";
  for (const className of [metricSourceClass(metricData?.source), metricToneClass(label, value)]) {
    if (className) item.classList.add(className);
  }
  source.className = metricSourceClass(metricData?.source);
  if (metricData?.source === "Garmin Connect") source.className = "metric-garmin";
  const valueRow = document.createElement("div");
  valueRow.className = "metric-value-row";
  valueRow.append(metric);
  const comparison = comparisonText(metricData?.comparison);
  if (comparison) {
    const badge = document.createElement("small");
    badge.className = `metric-comparison ${comparison.className}`;
    badge.textContent = comparison.text;
    badge.title = comparison.title;
    valueRow.append(badge);
  }
  if (editable?.key) {
    item.classList.add("metric-editable");
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "metric-edit-button";
    edit.textContent = "✎";
    edit.title = `${label} bearbeiten`;
    edit.setAttribute("aria-label", `${label} bearbeiten`);
    const input = document.createElement("input");
    input.className = "metric-edit-input";
    input.type = "number";
    input.step = editable.step || "any";
    input.min = editable.min ?? "0";
    input.value = state.data?.profile?.[editable.key] || (value == null ? "" : value);
    input.hidden = true;
    edit.addEventListener("click", () => {
      const editing = item.classList.toggle("editing");
      input.hidden = !editing;
      metric.hidden = editing;
      edit.textContent = editing ? "✓" : "✎";
      edit.title = editing ? "Wert speichern" : `${label} bearbeiten`;
      edit.setAttribute("aria-label", edit.title);
      if (editing) { input.focus(); input.select(); }
      else saveInlineMetric(editable.key, input.value, edit);
    });
    item.append(valueRow, input, caption, source, edit);
  } else {
    item.append(valueRow, caption, source);
  }
  root.append(item);
}

async function saveInlineMetric(key, value, button) {
  const profile = { ...(state.data?.profile || {}), [key]: String(value || "").trim() };
  button.disabled = true;
  try {
    await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    toast("Wert gespeichert und für den Coach aktiviert");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

function performanceSection(root, title, items, detail = "") {
  const section = document.createElement("section");
  section.className = "performance-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const headingWrap = document.createElement("div");
  headingWrap.className = "performance-section-heading";
  headingWrap.append(heading);
  if (detail) {
    const stamp = document.createElement("span");
    stamp.className = "tab-sync-detail";
    stamp.textContent = detail;
    headingWrap.append(stamp);
  }
  section.append(headingWrap);
  const grid = document.createElement("div");
  grid.className = "metric-grid";
  items.forEach(([label, value, formatter, editable]) => displayMetric(grid, label, value, formatter, editable));
  section.append(grid);
  root.append(section);
}

function renderPerformance(performance) {
  const root = $("#performanceSummary");
  root.replaceChildren();
  const syncNotices = [];
  if (state.data?.sync?.running || state.localSync.intervals) syncNotices.push(state.data?.sync?.status || "Intervals.icu wird synchronisiert…");
  if (state.data?.garmin_sync?.running || state.localSync.garmin) syncNotices.push(state.data?.garmin_sync?.status || "Garmin wird synchronisiert…");
  if (state.data?.performance_refresh?.running || state.localSync.performance) syncNotices.push("Leistungsdaten werden aktualisiert…");
  if (!performance?.available) {
    const info = document.createElement("p");
    info.className = "fine-print";
    info.textContent = "Nach dem ersten Trainingsdaten-Update werden hier Leistungswerte angezeigt.";
    root.append(info);
    if (syncNotices.length) {
      const status = document.createElement("p");
      status.className = "tab-sync-detail";
      status.textContent = syncNotices.join(" · ");
      root.append(status);
    }
    return;
  }

  const values = performance.metrics || {};
  const load = performance.current_load || {};
  const actualLoad = performance.actual_load || {};
  const recovery = performance.recovery || {};
  const comparisons = performance.comparisons || {};
  const week = performance.rolling_training?.last_7_days || {};
  const refreshedAt = state.data?.sync?.last_sync_at || performance.as_of;
  const performanceDetail = syncNotices.length ? syncNotices.join(" · ") : refreshedAt ? `Letzte Aktualisierung: ${formatTime(refreshedAt)}` : "";
  const compared = (value, key) => value && typeof value === "object" ? { ...value, comparison: comparisons[key] } : { value, comparison: comparisons[key] };
  performanceSection(root, "Gesundheitsdaten", [
    ["Gewicht", compared(values.weight_kg, "weight_kg_30d"), null, { key: "weight_kg", step: "0.1" }],
    ["Körperfett", values.body_fat_pct, null, { key: "body_fat_pct", step: "0.1" }],
    ["Größe", values.height_cm, null, { key: "height_cm", step: "0.1" }],
    ["Schlaf", compared({ value: recovery.sleep_hours, unit: "h", source: "Intervals.icu Wellness" }, "sleep_hours")],
    ["Readiness", compared({ value: recovery.readiness, unit: "", source: recovery.readiness_source || "Intervals.icu Wellness" }, "readiness_30d")],
    ["Ruhepuls", compared({ value: recovery.restingHR, unit: "bpm", source: "Intervals.icu Wellness" }, "restingHR")],
    ["HRV", compared({ value: recovery.hrv, unit: "ms", source: "Intervals.icu Wellness" }, "hrv")],
  ], performanceDetail);
  performanceSection(root, "Allgemeine Leistungsdaten", [
    ["Fitness / CTL", compared({ value: load.ctl, unit: "", source: "Intervals.icu" }, "fitness_ctl"), formatWhole],
    ["Form / TSB", compared({ value: load.tsb, unit: "", source: "Intervals.icu" }, "form_tsb"), formatWhole],
    ["Ermüdung / ATL (inkl. Planung)", compared({ value: load.atl, unit: "", source: "Intervals.icu" }, "fatigue_atl"), formatWhole],
    ["Ermüdung / ATL (nur absolviert)", compared({ value: actualLoad.atl, unit: "", source: actualLoad.source || "Berechnet" }, "fatigue_atl_actual"), formatWhole],
    ["Belastung letzte 7 Tage", compared({ value: week.training_load, unit: "", source: "Aus Aktivitäten" }, "training_load_7d")],
    ["Trainingsumfang letzte 7 Tage", compared({ value: week.duration_hours, unit: "h", source: "Aus Aktivitäten" }, "training_volume_7d")],
  ]);
  performanceSection(root, "Radfahren", [
    ["FTP", compared(values.cycling_ftp_watts, "cycling_ftp_watts_30d")],
    ["eFTP", compared(values.cycling_eftp_watts, "cycling_eftp_30d")],
    ["Schwellenpuls", compared(values.bike_threshold_hr_bpm, "bike_threshold_hr_bpm_30d")],
    ["Max HF", values.cycling_max_hr_bpm],
    ["VO₂max", compared(values.cycling_vo2max_ml_kg_min, "cycling_vo2max_ml_kg_min_30d")],
  ]);
  performanceSection(root, "Laufen", [
    ["Schwellenleistung", compared(values.run_threshold_watts, "run_threshold_watts_30d")],
    ["Schwellenpace", compared(values.run_threshold_pace_seconds_per_km, "run_threshold_pace_seconds_per_km_30d"), formatPace],
    ["Schwellenpuls", compared(values.run_threshold_hr_bpm, "run_threshold_hr_bpm_30d")],
    ["Max HF", values.running_max_hr_bpm],
    ["VO₂max", compared(values.running_vo2max_ml_kg_min, "running_vo2max_ml_kg_min_30d")],
    ["5 km (geschätzt)", compared(values.run_5k_seconds, "run_5k_seconds_30d"), formatDuration],
    ["10 km (geschätzt)", compared(values.run_10k_seconds, "run_10k_seconds_30d"), formatDuration],
    ["Halbmarathon (geschätzt)", compared(values.run_half_marathon_seconds, "run_half_marathon_seconds_30d"), formatDuration],
    ["Marathon (geschätzt)", compared(values.run_marathon_seconds, "run_marathon_seconds_30d"), formatDuration],
  ]);
}

function updateHeaderAction() {
  const button = $("#headerActionButton");
  if (!button) return;
  const panel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  if (panel === "dataPanel") {
    button.hidden = false;
    button.dataset.action = "performance";
    button.title = "Aktuelle Leistungsdaten von Intervals.icu aktualisieren";
    button.disabled = Boolean(state.data?.performance_refresh?.running || state.data?.sync?.running || state.data?.garmin_sync?.running || state.data?.provider_resync?.intervals?.running || state.data?.provider_resync?.garmin?.running || state.localSync.performance || state.localSync.intervals || state.localSync.garmin || state.localSync.intervalsFull || state.localSync.garminFull);
    button.textContent = state.data?.sync?.running || state.data?.garmin_sync?.running || state.localSync.intervals || state.localSync.garmin
      ? "Synchronisierung läuft…"
      : button.disabled ? "Leistungsdaten werden aktualisiert…" : "Leistungsdaten aktualisieren";
  } else if (panel === "activitiesPanel") {
    button.hidden = false;
    button.dataset.action = "activities";
    button.title = "Aktivitäten der letzten 90 Tage von Intervals.icu laden";
    button.disabled = Boolean(state.data?.sync?.running || state.data?.provider_resync?.intervals?.running || state.localSync.intervals || state.localSync.intervalsFull);
    button.textContent = button.disabled ? "Synchronisierung läuft…" : "Aktivitäten aktualisieren";
  } else {
    button.hidden = true;
    button.disabled = false;
    button.dataset.action = "";
  }
}

function renderModel(model) {
  if (!model) return;
  const select = $("#modelSelect");
  const currentIds = [...select.options].map((option) => option.value).join(",");
  const nextIds = (model.options || []).map((option) => option.id).join(",");
  if (currentIds !== nextIds) {
    select.replaceChildren();
    for (const option of model.options || []) {
      const element = document.createElement("option");
      element.value = option.id;
      element.textContent = option.label;
      element.title = option.description || "";
      select.append(element);
    }
  }
  select.value = model.selected;
  const selected = (model.options || []).find((option) => option.id === model.selected);
  $("#modelDescription").textContent = selected?.description || "Wähle die Balance aus Qualität, Tempo und Kosten.";
}

function renderThinkingLevel(thinkingLevel) {
  if (!thinkingLevel) return;
  const select = $("#thinkingLevelSelect");
  const currentIds = [...select.options].map((option) => option.value).join(",");
  const nextIds = (thinkingLevel.options || []).map((option) => option.id).join(",");
  if (currentIds !== nextIds) {
    select.replaceChildren();
    for (const option of thinkingLevel.options || []) {
      const element = document.createElement("option");
      element.value = option.id;
      element.textContent = option.label;
      element.title = option.description || "";
      select.append(element);
    }
  }
  select.value = thinkingLevel.selected;
  const selected = (thinkingLevel.options || []).find((option) => option.id === thinkingLevel.selected);
  $("#thinkingLevelDescription").textContent = selected?.description || "Steuert die GrÃ¼ndlichkeit der Antwort.";
  const modelSelect = $("#modelSelect");
  const modelSummary = $("#modelSettingsSummary");
  if (modelSummary) modelSummary.textContent = [modelSelect?.selectedOptions?.[0]?.textContent, selected?.label || select.selectedOptions?.[0]?.textContent].filter(Boolean).join(" · ");
}

function renderAppVersion(app = {}) {
  const versionNode = $("#appVersion");
  const updateNode = $("#appUpdateIndicator");
  if (versionNode) versionNode.textContent = app.version ? `v${app.version}` : "";
  if (!updateNode) return;
  const release = app.github_release || {};
  const hasNewerVersion = release.status === "ok" && release.is_newer;
  updateNode.hidden = !hasNewerVersion;
  if (hasNewerVersion) {
    updateNode.href = release.url;
    updateNode.title = `Neuere Version verfügbar: v${release.version}`;
    updateNode.setAttribute("aria-label", `Neuere Version verfügbar: v${release.version}`);
  } else {
    updateNode.removeAttribute("href");
    updateNode.removeAttribute("title");
  }
}

function renderGithubRelease(app = {}) {
  const statusNode = $("#releaseStatus");
  const summaryNode = $("#releaseSummary");
  const changelogNode = $("#releaseChangelog");
  const linkNode = $("#releaseLink");
  if (!statusNode || !changelogNode || !linkNode) return;
  const release = app.github_release || {};
  const available = release.status === "ok";
  statusNode.classList.toggle("error", !available && release.status === "unavailable");
  if (!available) {
    if (release.status === "loading") {
      statusNode.classList.remove("error");
      statusNode.textContent = release.message || "GitHub-Release wird nachgeladen.";
      if (summaryNode) summaryNode.textContent = "Wird geladen";
      changelogNode.textContent = "Release-Informationen werden nachgeladen.";
      linkNode.hidden = true;
      linkNode.removeAttribute("href");
      return;
    }
    statusNode.textContent = release.status === "disabled"
      ? "GitHub-Release-Prüfung ist nicht konfiguriert."
      : (release.message || "GitHub-Release konnte nicht geladen werden.");
    if (summaryNode) summaryNode.textContent = release.status === "disabled" ? "Nicht konfiguriert" : "Nicht verfügbar";
    changelogNode.textContent = "Kein Changelog verfügbar.";
    linkNode.hidden = true;
    linkNode.removeAttribute("href");
    return;
  }
  const publication = release.published_at ? ` · veröffentlicht ${formatTime(release.published_at)}` : "";
  statusNode.classList.remove("error");
  statusNode.textContent = `Neuestes Release: v${release.version}${publication}${release.is_newer ? " · Neuere Version verfügbar" : " · Aktuelle Version"}`;
  if (summaryNode) summaryNode.textContent = release.is_newer ? `v${release.version} verfügbar` : `v${release.version} · aktuell`;
  changelogNode.textContent = release.changelog || "Für dieses Release ist kein Changelog hinterlegt.";
  linkNode.hidden = false;
  linkNode.href = release.url;
}

function renderSettings(data) {
  const configured = data.configured || {};
  const garmin = data.garmin || {};
  const weather = data.weather || {};
  const openaiStatus = data.usage?.status || {};
  const setStatus = (selector, ok, text) => {
    const node = $(selector);
    if (!node) return;
    node.textContent = text;
    node.className = ok ? "configured" : "not-configured";
  };
  const openaiHealthy = configured.openai && openaiStatus.state !== "error";
  setStatus(
    "#openaiConnectionStatus",
    openaiHealthy,
    !configured.openai ? "Nicht konfiguriert" : openaiStatus.state === "error" ? "Fehler bei letzter Anfrage" : "Konfiguriert",
  );
  const openaiDetail = $("#openaiConnectionDetail");
  if (openaiDetail) {
    openaiDetail.classList.toggle("error", Boolean(configured.openai && openaiStatus.state === "error"));
    openaiDetail.textContent = !configured.openai
      ? "API-Schlüssel nicht konfiguriert"
      : openaiStatus.state === "error"
        ? `${openaiStatus.message || "OpenAI-Anfrage fehlgeschlagen."}${openaiStatus.updated_at ? ` · ${formatTime(openaiStatus.updated_at)}` : ""}`
        : openaiStatus.state === "ok"
          ? `Letzter erfolgreicher API-Aufruf: ${formatTime(openaiStatus.updated_at)}`
          : "Noch kein API-Aufruf geprüft";
  }
  const intervals = data.intervals || {
    configured: Boolean(configured.intervals),
    state: configured.intervals ? "configured" : "not_configured",
  };
  const intervalsHealthy = intervals.configured && intervals.state !== "error";
  setStatus(
    "#intervalsConnectionStatus",
    intervalsHealthy,
    !intervals.configured
      ? "Nicht konfiguriert"
      : intervals.state === "syncing"
        ? "Synchronisierung läuft…"
        : intervals.state === "error"
          ? "Fehler bei letzter Aktualisierung"
          : intervals.state === "connected"
            ? "Verbunden"
            : "Konfiguriert · noch nicht getestet",
  );
  const intervalsDetail = $("#intervalsConnectionDetail");
  if (intervalsDetail) {
    const librarySync = intervals.library_sync || {};
    const libraryState = librarySync.state || {};
    const libraryCount = Number(libraryState.synced || 0);
    const paginationDetail = Object.entries(intervals.pagination || {})
      .filter(([, value]) => value && (Number(value.pages) > 1 || value.complete === false))
      .map(([name, value]) => `${name}: ${value.records || 0} Datensätze auf ${value.pages || 0} Seiten${value.complete === false ? " · unvollständig" : ""}`)
      .join(" · ");
    intervalsDetail.classList.toggle("error", Boolean(intervals.last_error));
    intervalsDetail.textContent = !intervals.configured
      ? "API-Schlüssel nicht konfiguriert"
      : intervals.state === "syncing"
        ? intervals.status || "Intervals.icu wird synchronisiert."
        : intervals.last_error
          ? intervals.last_error
          : intervals.last_sync_at || librarySync.last_sync_at
            ? `Letzte Aktualisierung: ${formatTime(intervals.last_sync_at || librarySync.last_sync_at)}${libraryCount ? ` · ${libraryCount} Bibliothekseinheiten` : ""}${paginationDetail ? ` · ${paginationDetail}` : ""}`
            : "Noch keine Synchronisierung durchgeführt";
  }
  setStatus("#garminConnectionStatus", garmin.configured, garmin.configured ? (garmin.source === "fixture" ? "Lokale Testdatei aktiv" : "Konfiguriert") : "Nicht konfiguriert");
  const weatherLocation = [weather.location?.name, weather.location?.country].filter(Boolean).join(", ");
  setStatus("#weatherConnectionStatus", weather.configured, weather.configured ? (weather.loading ? "Wird geladen" : "Konfiguriert") : "Nicht konfiguriert");
  const weatherDetail = $("#weatherConnectionDetail");
  if (weatherDetail) {
    weatherDetail.textContent = weather.configured
      ? `${weatherLocation ? `Standort: ${weatherLocation} · ` : ""}${weather.fetched_at ? `letzte Abfrage: ${formatTime(weather.fetched_at)}` : "Standort im Profil hinterlegen"}`
      : "Kein API-Schlüssel erforderlich · Standort im Profil hinterlegen";
  }
  const weatherSyncButton = $("#weatherSyncButton");
  if (weatherSyncButton) {
    const weatherSyncRunning = Boolean(state.localSync.weather);
    weatherSyncButton.disabled = !weather.configured || weatherSyncRunning;
    weatherSyncButton.textContent = weatherSyncRunning ? "Wetter wird aktualisiert…" : "Wetter aktualisieren";
  }
  const connectionsSummary = $("#connectionsSummary");
  if (connectionsSummary) {
    connectionsSummary.textContent = [["OpenAI", openaiHealthy], ["Intervals", intervalsHealthy], ["Garmin", garmin.configured], ["Open-Meteo", weather.configured]]
      .map(([label, active]) => `${label} ${active ? "✓" : "–"}`).join(" · ");
  }
  const intervalsDays = $("#intervalsSyncDays");
  const garminDays = $("#garminSyncDays");
  if (intervalsDays && document.activeElement !== intervalsDays) intervalsDays.value = data.sync_settings?.intervals_days || 90;
  if (garminDays && document.activeElement !== garminDays) garminDays.value = data.sync_settings?.garmin_days || 30;
  const calendarDisplay = data.calendar_display || CALENDAR_DISPLAY_DEFAULTS;
  const calendarPastWeeks = $("#calendarDisplayPastWeeks");
  const calendarFutureWeeks = $("#calendarDisplayFutureWeeks");
  const pastWeeks = calendarDisplayValue(calendarDisplay.past_weeks, CALENDAR_DISPLAY_DEFAULTS.past_weeks);
  const futureWeeks = calendarDisplayValue(calendarDisplay.future_weeks, CALENDAR_DISPLAY_DEFAULTS.future_weeks);
  if (calendarPastWeeks && document.activeElement !== calendarPastWeeks) calendarPastWeeks.value = pastWeeks;
  if (calendarFutureWeeks && document.activeElement !== calendarFutureWeeks) calendarFutureWeeks.value = futureWeeks;
  const calendarDisplaySummary = $("#calendarDisplaySummary");
  if (calendarDisplaySummary) calendarDisplaySummary.textContent = `${pastWeeks} zurück · ${futureWeeks} voraus`;
  const calendarHorizonHint = $("#calendarHorizonHint");
  if (calendarHorizonHint) {
    const window = data.planning_view?.provider_window || {};
    calendarHorizonHint.textContent = window.start && window.end
      ? `Die Ansicht bleibt auf das lokal geladene Intervals.icu-Fenster ${window.start} bis ${window.end} begrenzt.`
      : "Die Ansicht wird auf das lokal geladene Providerfenster begrenzt.";
  }
  const intervalsSyncButton = $("#systemIntervalsSyncButton");
  const intervalsFullButton = $("#systemIntervalsFullResyncButton");
  const intervalsFullStatus = $("#intervalsFullResyncStatus");
  const intervalsFullResync = data.provider_resync?.intervals || {};
  const intervalsFullRunning = Boolean(intervalsFullResync.running || state.localSync.intervalsFull);
  if (intervalsSyncButton) {
    intervalsSyncButton.disabled = Boolean(data.sync?.running || state.localSync.intervals || intervalsFullRunning);
    intervalsSyncButton.textContent = data.sync?.running || state.localSync.intervals ? "Synchronisierung läuft…" : "Synchronisieren";
  }
  if (intervalsFullButton) {
    intervalsFullButton.disabled = !configured.intervals || intervalsFullRunning || Boolean(data.sync?.running || state.localSync.intervals);
    intervalsFullButton.textContent = intervalsFullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  if (intervalsFullStatus) {
    intervalsFullStatus.classList.toggle("error", Boolean(intervalsFullResync.last_error));
    intervalsFullStatus.textContent = intervalsFullRunning && intervalsFullResync.status
      ? intervalsFullResync.status
      : intervalsFullResync.last_error
        ? intervalsFullResync.last_error
        : intervalsFullResync.last_resync_at
          ? `Letzter vollständiger Resync: ${formatTime(intervalsFullResync.last_resync_at)}`
          : "Löscht nur lokale Intervals.icu-Daten; die Cloud bleibt unverändert.";
  }
  const garminSyncButton = $("#garminSyncButton");
  if (garminSyncButton) {
    garminSyncButton.disabled = Boolean(data.garmin_sync?.running || state.localSync.garmin);
    garminSyncButton.textContent = data.garmin_sync?.running || state.localSync.garmin ? "Synchronisierung läuft…" : "Garmin synchronisieren";
  }
  const usage = data.usage || {};
  const usageNode = $("#usageSummary");
  if (usageNode) {
    const rateLimits = usage.rate_limits || {};
    const remaining = rateLimits.remaining_requests != null || rateLimits.remaining_tokens != null
      ? ` · Restkontingent im aktuellen OpenAI-Fenster: ${rateLimits.remaining_requests ?? "?"} Anfragen / ${rateLimits.remaining_tokens ?? "?"} Tokens`
      : " · Restkontingent wird nach einem API-Aufruf angezeigt";
    const openaiError = usage.status?.state === "error" ? ` · Status: ${usage.status.message || "Fehler bei letzter Anfrage"}` : "";
    usageNode.textContent = `OpenAI heute: ${usage.requests || 0} Anfragen · ${usage.total_tokens || 0} Tokens${remaining}${openaiError}`;
  }
  const privacySummary = $("#privacySummary");
  if (privacySummary) privacySummary.textContent = `${usage.requests || 0} OpenAI-Anfragen heute`;
  renderGithubRelease(data.app);
  renderNotificationStatus();
}

function formatLogEntry(entry) {
  const timestamp = entry.timestamp ? `[${formatTime(entry.timestamp)}] ` : "";
  const level = entry.level ? `${entry.level} ` : "";
  const event = entry.event ? `${entry.event}: ` : "";
  const context = entry.context ? ` ${JSON.stringify(entry.context)}` : "";
  return `${timestamp}${level}${event}${entry.message || ""}${context}`;
}

async function loadLogs() {
  const output = $("#logsOutput");
  const button = $("#logsRefreshButton");
  if (!output || !button) return;
  button.disabled = true;
  output.textContent = "Logs werden geladen…";
  try {
    const result = await api("/api/logs?limit=250");
    output.textContent = result.entries?.length ? result.entries.map(formatLogEntry).join("\n") : "Noch keine Log-Einträge vorhanden.";
    output.scrollTop = output.scrollHeight;
  } catch (error) { output.textContent = error.message; }
  finally { button.disabled = false; }
}

function render(data) {
  const firstRender = !state.data;
  state.data = data;
  renderAppVersion(data.app);
  renderRemoteDeleteNotice();
  renderQuickMessageTemplates();
  notifyState(data);
  renderStatus(data);
  renderMessages(data.messages, firstRender);
  renderToday(data);
  renderActivities(data.activities || []);
  renderPlanned(data.planned || [], data.external_calendar?.events || [], data.daily_planning_context || []);
  renderActivePlanSegment(data);
  const librarySyncDetail = $("#librarySyncDetail");
  if (librarySyncDetail) {
    const libraryState = data.library_sync?.state || {};
    const pending = Number(libraryState.local || 0) + Number(libraryState.sync_error || 0);
    const missing = Number(libraryState.remote_missing || 0);
    const stateHint = [
      pending ? `${pending} lokale Einheit${pending === 1 ? "" : "en"} noch nicht synchronisiert` : null,
      missing ? `${missing} Remote-Einheit${missing === 1 ? "" : "en"} nicht gefunden` : null,
    ].filter(Boolean).join(" · ");
    librarySyncDetail.textContent = data.library_sync?.last_error
      ? data.library_sync.last_error
      : data.library_sync?.last_sync_at
        ? ["Letzte Aktualisierung: " + formatTime(data.library_sync.last_sync_at), stateHint].filter(Boolean).join(" · ")
        : stateHint || "Noch nicht synchronisiert";
    librarySyncDetail.classList.toggle("error", Boolean(data.library_sync?.last_error || libraryState.sync_error));
  }
  renderProfile(data.profile);
  renderCheckins(data.checkins || data.local_feedback?.recent || [], data.profile?.timezone);
  renderGarmin(data.garmin);
  if (state.planSegment === "goals") renderCompetitions(data.competitions || []);
  renderAdaptivePlanning(data);
  renderExternalCalendar(data);
  renderCompetitionSync(data);
  renderPerformance(data.performance);
  renderModel(data.model);
  renderThinkingLevel(data.thinking_level);
  renderSettings(data);
  updateHeaderAction();
}

async function loadState(path = "/api/bootstrap", requestedAreas = null) {
  const requestSequence = ++state.loadSequence;
  const initialLoad = $("#appShell").classList.contains("is-loading");
  try {
    const localOnly = path.includes("local=1");
    const query = localOnly ? "?local=1" : "";
    const bootstrap = await api(path);
    const existing = state.data || {};
    const payload = { ...existing, ...bootstrap };
    ["messages", "messages_next_cursor", "activities", "activities_next_cursor", "library", "library_next_cursor", "plans", "planned", "planning_view", "planning_compliance", "weather", "parallel_cycling", "daily_planning_context", "planning", "performance", "garmin", "checkins", "local_feedback", "activity_feedback"].forEach((key) => {
      if (existing[key] !== undefined) payload[key] = existing[key];
    });
    const areas = new Set(requestedAreas || ["chat", "activities", "plan", "library", "performance", "feedback", "profile"]);
    const requests = [];
    if (areas.has("chat")) requests.push(["chat", api("/api/chat/history?limit=100")]);
    if (areas.has("activities")) requests.push(["activities", api("/api/activities?limit=250")]);
    if (areas.has("plan")) requests.push(["plan", api(`/api/plan${query}`)]);
    if (areas.has("library")) requests.push(["library", api("/api/library?limit=100")]);
    if (areas.has("performance")) requests.push(["performance", api("/api/performance")]);
    if (areas.has("feedback")) requests.push(["feedback", api("/api/feedback")]);
    if (areas.has("profile")) requests.push(["profile", api("/api/profile")]);
    const domainData = Promise.all(requests.map(async ([area, request]) => [area, await request]));
    if (initialLoad && requestSequence === state.loadSequence) {
      render(payload);
      finishAppShellLoading();
    }
    const results = await domainData;
    results.forEach(([area, result]) => {
      state.loadedAreas.add(area);
      if (area === "chat") Object.assign(payload, { messages: result.messages || [], messages_next_cursor: result.next_cursor });
      if (area === "activities") Object.assign(payload, { activities: result.activities || [], activities_next_cursor: result.next_cursor });
      if (area === "plan") Object.assign(payload, result);
      if (area === "library") Object.assign(payload, { library: result.workouts || [], library_next_cursor: result.next_cursor });
      if (area === "performance") Object.assign(payload, result);
      if (area === "feedback") Object.assign(payload, result);
      if (area === "profile") Object.assign(payload, { profile: result.profile || bootstrap.profile, competitions: result.competitions || bootstrap.competitions });
    });
    payload.state_versions = bootstrap.state_versions || payload.state_versions;
    if (requestSequence === state.loadSequence) render(payload);
  } catch (error) {
    if (/Authentication/.test(error.message)) return;
    const statusCard = $("#statusCard");
    statusCard.hidden = false;
    statusCard.classList.add("warning");
    $("#statusTitle").textContent = "Trainingsdaten konnten nicht geladen werden";
    $("#statusDetail").textContent = error.message;
    toast(error.message, true);
  } finally {
    if ($("#appShell").classList.contains("is-loading")) finishAppShellLoading();
  }
}

function load(path = "/api/bootstrap", requestedAreas = null) {
  if (state.loadPromise) return state.loadPromise;
  const areas = requestedAreas || currentPlanLoadAreas();
  const promise = loadState(path, areas);
  const tracked = promise.finally(() => {
    if (state.loadPromise === tracked) state.loadPromise = null;
  });
  state.loadPromise = tracked;
  return tracked;
}

async function loadInitialState() {
  const route = routeFromHash();
  const segment = planSegmentFromRoute(route);
  const areas = ["chat", "activities", "performance", "feedback", "profile"];
  if (route === "today" || (baseRoute(route) === "planned" && segment !== "library")) areas.push("plan");
  if (baseRoute(route) === "planned" && segment === "library") areas.push("library");
  await load("/api/bootstrap?local=1", areas);
}

function renderActivePlanSegment(data = state.data) {
  if (!data) return;
  renderPlanSegments(state.planSegment);
  if (state.planSegment === "library") renderLibrary(data.library || []);
  if (state.planSegment === "goals") {
    renderCompetitions(data.competitions || []);
    renderTrainingPlans(data.plans || [], data.library || []);
  }
}

function queueChatMessage(message, mode) {
  state.chatQueue[mode === "steer" ? "unshift" : "push"]({
    id: ++state.chatQueueSequence,
    message,
    mode,
  });
  const input = $("#messageInput");
  input.value = "";
  state.chatDraftDirty = false;
  input.style.height = "auto";
  renderMessages(state.data?.messages || [], true);
  updateChatControls();
}

async function requestCoachResponse(message, restoreInputOnError = false) {
  if (state.data) {
    state.data.messages.push({ role: "user", content: message });
    renderMessages(state.data.messages, true);
  }
  state.chatStreamText = "";
  const stream = { controller: new AbortController(), operationId: null, cancelRequested: false };
  state.chatStream = stream;
  updateChatControls();
  renderMessages(state.data?.messages || [], true);
  let completed = false;
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      credentials: "same-origin",
      signal: stream.controller.signal,
      headers: { "Content-Type": "application/json", "X-CSRF-Token": cookie("ic_csrf") },
      body: JSON.stringify({ message }),
    });
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch (_) {}
      if (response.status === 401) showLogin();
      throw new Error(payload.error || `Anfrage fehlgeschlagen (${response.status})`);
    }
    if (!response.body) throw new Error("Der Browser unterstützt keinen Antwort-Stream.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const consume = (block) => {
      let event = "message";
      const data = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (!data.length) return;
      const payload = JSON.parse(data.join("\n"));
      if (event === "started") stream.operationId = payload.operation_id || null;
      else if (event === "delta") {
        state.chatStreamText += payload.text || "";
        renderMessages(state.data?.messages || [], true);
      } else if (event === "error") {
        const error = new Error(payload.message || "Die Coach-Anfrage ist fehlgeschlagen.");
        error.reason = payload.reason;
        throw error;
      } else if (event === "completed") completed = true;
    };
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";
      for (const block of blocks) consume(block);
    }
    buffer += decoder.decode();
    if (buffer.trim()) consume(buffer);
    if (!completed && !stream.cancelRequested) throw new Error("Der Antwort-Stream wurde unerwartet beendet.");
    await load();
    invalidateContextPreview();
    return completed;
  } catch (error) {
    const cancelled = stream.cancelRequested || error?.name === "AbortError" || error?.reason === "chat_cancelled";
    if (!cancelled) toast(error.message, true);
    if (restoreInputOnError) {
      $("#messageInput").value = message;
      state.chatDraftDirty = true;
    }
    await load();
    invalidateContextPreview();
    return false;
  } finally {
    if (state.chatStream === stream) state.chatStream = null;
    state.chatStreamText = "";
    updateChatControls();
  }
}

async function drainChatQueue(firstMessage) {
  if (!await requestCoachResponse(firstMessage, true)) return;
  while (state.chatQueue.length) {
    const next = state.chatQueue.shift();
    renderMessages(state.data?.messages || [], true);
    if (!await requestCoachResponse(next.message)) return;
  }
}

async function cancelChat() {
  const stream = state.chatStream;
  if (!stream) return;
  stream.cancelRequested = true;
  await api("/api/chat/cancel", {
    method: "POST",
    body: JSON.stringify({ operation_id: stream.operationId }),
  }).catch(() => {});
  stream.controller.abort();
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if (!message || voiceIsRecording() || state.voiceTranscribing) return;
  if (state.busy) {
    queueChatMessage(message, "queue");
    return;
  }
  state.busy = true;
  state.quickTemplatesVisible = false;
  renderQuickMessageTemplates();
  input.value = "";
  state.chatDraftDirty = false;
  input.style.height = "auto";
  updateChatControls();
  updateVoiceButton();
  try {
    await drainChatQueue(message);
  } finally {
    state.busy = false;
    updateChatControls();
    renderMessages(state.data?.messages || [], true);
    updateVoiceButton();
    input.focus();
  }
}

function steerCurrentChat(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if (!message || !state.busy || voiceIsRecording() || state.voiceTranscribing) return;
  queueChatMessage(message, "steer");
}

async function syncNow(event) {
  const button = event?.currentTarget || $("#activitiesSyncButton");
  const compactButton = button.id === "systemIntervalsSyncButton";
  const defaultCaption = compactButton ? "Synchronisieren" : "Aktivitäten aktualisieren";
  const configuredDays = $("#intervalsSyncDays")?.value || state.data?.sync_settings?.intervals_days || 90;
  state.localSync.intervals = true;
  button.disabled = true; button.classList.add("busy"); button.textContent = compactButton ? "Synchronisierung läuft…" : "Aktivitäten werden aktualisiert…";
  try {
    const result = await api("/api/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    if (result.operation_id) {
      const completed = await waitForSync(result.operation_id);
      if (completed.status === "error") throw new Error(completed.last_error || "Synchronisierung fehlgeschlagen.");
      toast(result.status === "already_running" ? "Aktualisierung läuft bereits" : "Aktualisierung abgeschlossen");
      invalidateContextPreview();
    } else toast("Aktualisierung läuft bereits");
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.intervals = false; button.disabled = false; button.classList.remove("busy"); button.textContent = defaultCaption; updateHeaderAction(); }
}

async function syncCompetitions() {
  if (state.profileDirty) {
    toast("Bitte zuerst die lokalen Änderungen speichern.", true);
    return;
  }
  const button = $("#competitionSyncButton");
  if (!button) return;
  state.localSync.competitions = true;
  button.disabled = true;
  button.textContent = "Vorschau wird erstellt…";
  try {
    const preview = await api("/api/competitions/sync/preview", { method: "POST", body: "{}" });
    if (preview.status === "already_running") {
      toast("Zielwettkämpfe werden bereits synchronisiert");
      return;
    }
    const summary = preview.summary || {};
    const actions = (preview.actions || []).map((action) => {
      const label = action.type === "create" ? "Erstellen" : action.type === "change" ? "Ändern" : action.type === "delete" ? "Löschen" : "Konflikt";
      return `${label}: ${action.name || action.local_id || action.remote_id || "Wettkampf"}${action.event_date ? ` (${action.event_date})` : ""}`;
    });
    const details = actions.length ? `\n\n${actions.join("\n")}` : "\n\nKeine Remote-Änderungen erforderlich.";
    const message = `Intervals.icu-Wettkampf-Sync bestätigen?\n\nErstellen: ${summary.create || 0} · Ändern: ${summary.change || 0} · Löschen: ${summary.delete || 0} · Konflikte: ${summary.conflict || 0}${details}`;
    if (!window.confirm(message)) return;
    button.textContent = "Synchronisierung läuft…";
    const actionPreview = await api("/api/coach/actions/preview", {
      method: "POST",
      body: JSON.stringify({
        action_type: "sync_competitions",
        target_system: "intervals",
        object_ids: {},
        diff: preview.actions || [],
        payload: { fingerprint: preview.fingerprint },
      }),
    });
    const confirmedAction = await api("/api/coach/actions/confirm", {
      method: "POST",
      body: JSON.stringify({ proposal_id: actionPreview.proposed_action.id }),
    });
    const result = await api("/api/coach/actions/execute", {
      method: "POST",
      body: JSON.stringify({ action_token: confirmedAction.action_token, payload_hash: confirmedAction.proposed_action.payload_hash }),
    });
    if (result.status === "already_running") toast("Zielwettkämpfe werden bereits synchronisiert");
    else toast(`Zielwettkämpfe synchronisiert · ${result.pushed || 0} übertragen · ${result.imported || 0} importiert${result.conflicts ? ` · ${result.conflicts} Konflikt(e) bitte prüfen` : ""}${result.skipped ? ` · ${result.skipped} nicht unterstützte Sportart(en) übersprungen` : ""}`);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.competitions = false; renderCompetitionSync(state.data || {}); }
}

async function refreshPerformance() {
  const button = $("#headerActionButton");
  if (!button) return;
  state.localSync.performance = true;
  button.disabled = true;
  button.textContent = "Aktualisierung läuft…";
  try {
    const result = await api("/api/performance/refresh", { method: "POST", body: "{}" });
    toast(result.status === "ok" ? "Leistungsdaten aktualisiert" : "Aktualisierung läuft bereits");
    invalidateContextPreview();
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  }
  finally { state.localSync.performance = false; updateHeaderAction(); }
}

async function syncGarmin() {
  const button = $("#garminSyncButton");
  if (!button) return;
  state.localSync.garmin = true;
  button.disabled = true;
  button.textContent = "Garmin wird synchronisiert…";
  try {
    const configuredDays = $("#garminSyncDays")?.value || state.data?.sync_settings?.garmin_days || 30;
    const result = await api("/api/garmin/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    toast(result.status === "ok" ? `Garmin synchronisiert${result.activities ? ` · ${result.activities} Aktivitäten` : ""}` : "Garmin-Synchronisierung läuft bereits");
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.garmin = false; button.disabled = false; button.textContent = "Garmin synchronisieren"; updateHeaderAction(); }
}

async function syncExternalCalendar() {
  const button = $("#externalCalendarSyncButton");
  if (!button) return;
  state.localSync.externalCalendar = true;
  button.disabled = true;
  button.textContent = "Synchronisierung läuft…";
  try {
    const result = await api("/api/external-calendar/sync", { method: "POST", body: "{}" });
    toast(result.status === "ok" ? `Kalender synchronisiert · ${result.events || 0} Einträge` : "Kalender wird bereits synchronisiert");
    if (result.replan_changes) toast(`${result.replan_changes} lokale Bibliothekseinheit(en) als Anpassung vorgeschlagen`);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.externalCalendar = false; button.disabled = false; button.textContent = "Synchronisieren"; }
}

async function syncWeather() {
  const button = $("#weatherSyncButton");
  if (!button) return;
  state.localSync.weather = true;
  button.disabled = true;
  button.classList.add("busy");
  button.textContent = "Wetter wird aktualisiert…";
  try {
    const result = await api("/api/weather/sync", { method: "POST", body: "{}" });
    toast(result.status === "ok" ? "Open-Meteo-Wetter aktualisiert" : result.status === "stale" ? "Open-Meteo nicht erreichbar · letzte Daten bleiben sichtbar" : "Bitte zuerst einen Wetterort im Profil hinterlegen", result.status === "stale");
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally {
    state.localSync.weather = false;
    button.classList.remove("busy");
    renderSettings(state.data || {});
  }
}

async function fullResync(source) {
  const isGarmin = source === "garmin";
  const button = $(isGarmin ? "#garminFullResyncButton" : "#systemIntervalsFullResyncButton");
  if (!button) return;
  const providerLabel = isGarmin ? "Garmin" : "Intervals.icu";
  if (!window.confirm(`Alle lokal gespeicherten ${providerLabel}-Daten löschen und vollständig neu laden? Die Daten in ${providerLabel} bleiben unverändert.`)) return;
  const stateKey = isGarmin ? "garminFull" : "intervalsFull";
  state.localSync[stateKey] = true;
  button.disabled = true;
  button.classList.add("busy");
  button.textContent = "Vollständiger Resync läuft…";
  try {
    const result = await api(`/api/${source}/full-resync`, { method: "POST", body: JSON.stringify({ confirm: "FULL_RESYNC" }) });
    toast(result.status === "already_running" ? `${providerLabel} wird bereits vollständig neu geladen` : `${providerLabel} lokal vollständig neu geladen`);
    invalidateContextPreview();
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  } finally {
    state.localSync[stateKey] = false;
    renderSettings(state.data || {});
    updateHeaderAction();
  }
}

async function resetCoachChat() {
  const button = $("#chatResetButton");
  if (!button || !window.confirm("Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen?")) return;
  button.disabled = true;
  button.textContent = "Wird zurückgesetzt…";
  try {
    await api("/api/chat/reset", { method: "POST", body: "{}" });
    if (state.data) {
      state.data.messages = [];
      state.chatQueue = [];
      renderMessages([], true);
    }
    toast("Neuer Coach-Chat gestartet");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Chat zurücksetzen"; }
}

async function saveProfile(event) {
  event.preventDefault();
  const button = event.submitter || event.currentTarget.querySelector("button[type=submit]");
  const buttonLabel = button?.textContent || "Athletenkontext speichern";
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Athletenkontext wird gespeichert…";
  }
  const formData = new FormData(event.currentTarget);
  const profile = {
    ...(state.data?.profile || {}),
    ...Object.fromEntries(formData),
    sports: formData.getAll("sports").map((value) => String(value).trim()).filter(Boolean).join(", "),
    availability_schedule: collectWeeklyAvailability(),
  };
  const payload = {
    profile,
    competitions: collectCompetitions(),
  };
  try {
    await api("/api/athlete-context", { method: "PUT", body: JSON.stringify(payload) });
    state.profileDirty = false;
    setDirtyIndicator("profileDirtyIndicator", false);
    invalidateContextPreview();
    toast("Athletenkontext gespeichert und für den Coach aktiviert");
    await load();
  } catch (error) { toast(error.message, true); }
  finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = buttonLabel;
    }
  }
}

let pwaReloadPending = false;

function showPwaUpdate() {
  const button = $("#pwaUpdateButton");
  if (!button) return;
  button.hidden = false;
  button.title = "Neue App-Version laden";
  button.setAttribute("aria-label", "Neue App-Version laden");
}

function setupPwaUpdates() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (pwaReloadPending) window.location.reload();
  });
  navigator.serviceWorker.register("/service-worker.js").then((registration) => {
    if (registration.waiting) showPwaUpdate();
    registration.addEventListener("updatefound", () => {
      const worker = registration.installing;
      if (!worker) return;
      worker.addEventListener("statechange", () => {
        if (worker.state === "installed" && navigator.serviceWorker.controller) showPwaUpdate();
      });
    });
  }).catch(() => {});
}

async function applyPwaUpdate() {
  if (!confirmDiscardChanges()) return;
  try {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration?.waiting) {
      await registration?.update();
      if (!registration?.waiting) return window.location.reload();
    }
    pwaReloadPending = true;
    registration.waiting.postMessage({ type: "SKIP_WAITING" });
  } catch (_) {
    toast("App-Update konnte nicht geladen werden.", true);
  }
}

async function saveCheckin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  for (const field of ["soreness", "stress", "motivation", "session_rpe", "available_minutes"]) {
    values[field] = values[field] === "" ? null : Number(values[field]);
  }
  const button = form.querySelector("button[type=submit]");
  const errorNode = $("#checkinError");
  if (errorNode) errorNode.textContent = "";
  if (button) { button.disabled = true; button.textContent = "Check-in wird gespeichert…"; }
  try {
    const result = await api("/api/feedback", { method: "POST", body: JSON.stringify(values) });
    state.checkinDirty = false;
    setDirtyIndicator("checkinDirtyIndicator", false);
    state.checkinSelectedDate = result.checkin?.checkin_date || values.checkin_date;
    toast("Tages-Check-in gespeichert");
    $("#checkinDialog")?.close();
    await load();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
    toast(error.message, true);
  }
  finally {
    if (button) { button.disabled = false; button.textContent = "Tages-Check-in speichern"; }
  }
}

async function saveActivityFeedback(event, activity, button) {
  event.preventDefault();
  const form = event.currentTarget;
  const activityId = activity.id ?? activity.activityId ?? activity.external_id;
  const payload = {
    activity_name: activity.name || activity.type || "",
    activity_date: activity.start_date_local || "",
    notes: String(new FormData(form).get("notes") || ""),
  };
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = "Wird gespeichert…";
  try {
    await api(`/api/activities/${encodeURIComponent(String(activityId))}/feedback`, { method: "POST", body: JSON.stringify(payload) });
    state.activityFeedbackDirty.delete(String(activityId));
    state.activityFeedbackDrafts.delete(String(activityId));
    setDirtyIndicator("activityDirtyIndicator", state.activityFeedbackDirty.size > 0);
    toast(payload.notes.trim() ? "Besonderheiten gespeichert" : "Besonderheiten entfernt");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = "Besonderheiten speichern";
  }
}

async function prepareReplan() {
  const button = $("#adaptivePlanningButton");
  if (!button) return;
  state.localSync.adaptivePlanning = true;
  button.disabled = true;
  button.textContent = "Prüfung läuft…";
  try {
    const result = await api("/api/planning/replan", { method: "POST", body: JSON.stringify({ apply: false }) });
    await load();
    if (result.changes?.length || result.illness_pause) openAdaptivePlanningDialog(result);
    else toast("Keine Planungsanpassung nötig");
  } catch (error) { toast(error.message, true); }
  finally {
    state.localSync.adaptivePlanning = false;
    renderAdaptivePlanning(state.data || {});
  }
}

async function applyReplan() {
  const button = $("#applyAdaptivePlanningButton");
  const adjustmentId = button?.dataset.adjustmentId;
  const syncIllness = Boolean($("#syncIllnessToIntervals")?.checked);
  const confirmation = syncIllness
    ? "Krankheitspause bestätigen, die nächsten Tage im lokalen Check-in füllen, die Planung umbauen und Krankheitstage als SICK-Einträge nach Intervals.icu synchronisieren?"
    : "Krankheitspause bestätigen, die nächsten Tage im lokalen Check-in füllen und die lokale Planung umbauen? Intervals.icu wird dabei nicht verändert.";
  if (!button || !adjustmentId || !window.confirm(confirmation)) return;
  button.disabled = true;
  try {
    const changes = state.data?.planning?.latest_replan?.changes || [];
    const illnessPause = state.data?.planning?.latest_replan?.illness_pause || null;
    const preview = await api("/api/coach/actions/preview", {
      method: "POST",
      body: JSON.stringify({
        action_type: "apply_adaptive_replan",
        target_system: syncIllness ? "local+intervals" : "local",
        object_ids: { adjustment_id: adjustmentId },
        diff: { changes, illness_pause: illnessPause },
        payload: { adjustment_id: adjustmentId, sync_illness_to_intervals: syncIllness },
      }),
    });
    const confirmed = await api("/api/coach/actions/confirm", {
      method: "POST",
      body: JSON.stringify({ proposal_id: preview.proposed_action.id }),
    });
    const result = await api("/api/coach/actions/execute", {
      method: "POST",
      body: JSON.stringify({ action_token: confirmed.action_token, payload_hash: confirmed.proposed_action.payload_hash }),
    });
    $("#adaptivePlanningDialog")?.close();
    toast(result.intervals_sync?.status === "error" ? "Lokale Krankheitspause angewendet; Intervals.icu-Synchronisierung fehlgeschlagen" : "Krankheitspause und adaptive Anpassung angewendet");
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function downloadDatabaseBackup() {
  const button = $("#backupDownloadButton");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/api/privacy/backup", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("Datenbank-Backup konnte nicht erstellt werden.");
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `intervals-coach-database-${todayIso()}.backup`;
    link.click();
    URL.revokeObjectURL(link.href);
    toast("Verschlüsseltes Backup heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { if (button) button.disabled = false; }
}

async function restoreDatabaseBackup() {
  const input = $("#backupFileInput");
  const file = input?.files?.[0];
  if (!file || !window.confirm("Das aktuelle Datenbank-Backup wird vorher gesichert und durch die ausgewählte Datei ersetzt. Fortfahren?")) return;
  const button = $("#backupRestoreButton");
  button.disabled = true;
  try {
    const response = await fetch("/api/privacy/restore", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/octet-stream", "X-CSRF-Token": cookie("ic_csrf") }, body: file });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Backup konnte nicht wiederhergestellt werden.");
    toast("Backup wiederhergestellt. Bitte erneut anmelden.");
    showLogin();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function saveModel(event) {
  const select = event.currentTarget;
  select.disabled = true;
  try {
    await api("/api/settings/model", { method: "PUT", body: JSON.stringify({ model: select.value }) });
    toast(`Aktiv: ${select.options[select.selectedIndex].text}`);
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  } finally { select.disabled = false; }
}

async function saveThinkingLevel(event) {
  const select = event.currentTarget;
  select.disabled = true;
  try {
    await api("/api/settings/thinking-level", { method: "PUT", body: JSON.stringify({ thinking_level: select.value }) });
    toast(`Thinking Level: ${select.options[select.selectedIndex].text}`);
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  } finally { select.disabled = false; }
}

async function saveCalendarDisplaySettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#calendarDisplaySaveButton");
  if (!button) return;
  button.disabled = true;
  button.textContent = "Wird gespeichert...";
  try {
    await api("/api/settings/calendar-display", {
      method: "PUT",
      body: JSON.stringify({
        past_weeks: $("#calendarDisplayPastWeeks")?.value,
        future_weeks: $("#calendarDisplayFutureWeeks")?.value,
      }),
    });
    toast("Kalenderansicht gespeichert");
    await load();
  } catch (error) {
    toast(error.message, true);
    renderSettings(state.data || {});
  } finally {
    button.disabled = false;
    button.textContent = "Kalenderansicht speichern";
    form.querySelectorAll("input").forEach((input) => { input.disabled = false; });
  }
}

async function downloadDiagnostics() {
  const button = $("#diagnosticsButton");
  button.disabled = true;
  button.textContent = "Wird vorbereitet…";
  try {
    const report = await api("/api/diagnostics");
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `intervals-coach-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast("Diagnose heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Diagnose herunterladen"; }
}

async function downloadPrivacyExport() {
  try {
    const response = await fetch("/api/privacy/export", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) {
      let message = "Privacy-Export konnte nicht erstellt werden.";
      try { message = (await response.json()).error || message; } catch (_) { /* keep safe fallback */ }
      throw new Error(message);
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `intervals-coach-export-${todayIso()}.zip`;
    link.click();
    URL.revokeObjectURL(link.href);
    toast("Datenexport erstellt");
  } catch (error) { toast(error.message, true); }
}

async function deletePrivacyData() {
  try {
    const preview = await api("/api/privacy/delete/preview");
    const categories = (preview.categories || []).map((category) => `${category.label}: ${category.records || 0}`).join("\n");
    const scope = `Unwiderruflich lokal gelöscht werden:\n${categories}\n\n` +
      `${(preview.remote_untouched || []).join("\n")}\n\n` +
      `${preview.openai_conversation || "Eine vorhandene OpenAI-Konversation wird separat behandelt."}\n\n` +
      "Erstelle bei Bedarf vorher ein verschlüsseltes Backup oder einen Export. Dieser Schritt kann nicht rückgängig gemacht werden.";
    if (!window.confirm(scope)) return;
    const confirmation = window.prompt(`Zur Bestätigung exakt eingeben: ${preview.confirmation_text}`, "");
    if (confirmation !== preview.confirmation_text) {
      toast("Löschen abgebrochen: Bestätigungstext stimmt nicht überein.", true);
      return;
    }
    const result = await api("/api/privacy/delete", { method: "POST", body: JSON.stringify({ confirm: confirmation }) });
    const notice = $("#privacyDeleteNotice");
    if (notice) {
      notice.hidden = !(result.remote_delete_attempted && !result.remote_conversation_deleted);
      notice.textContent = notice.hidden
        ? ""
        : "Lokale Daten wurden gelöscht, aber die OpenAI-Konversation konnte remote nicht bestätigt gelöscht werden. Prüfe den Anbieterstatus separat.";
    }
    const resultNotice = $("#privacyDeleteResult");
    if (resultNotice) {
      const deleted = Object.entries(result.deleted_categories || {}).map(([category, count]) => `${category}: ${count}`).join(" · ");
      resultNotice.hidden = false;
      resultNotice.textContent = `Lokale Datenklassen gelöscht: ${deleted || "keine"}. Remote-Providerdaten bleiben unverändert.`;
    }
    toast("Lokale Daten gelöscht");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function logout() {
  if (!confirmDiscardChanges()) return;
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (_) {}
  showLogin();
}

document.querySelectorAll(".nav-item").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  applyNavigationRoute(link.dataset.route, { historyMode: "push" });
}));
document.querySelectorAll("[data-plan-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  applyNavigationRoute(`planned/${link.dataset.planSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("[data-more-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  applyNavigationRoute(`more/${link.dataset.moreSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("close", () => restoreDialogFocus(dialog)));
window.addEventListener("hashchange", syncNavigationRoute);

$("#loginForm").addEventListener("submit", login);
$("#chatForm").addEventListener("submit", sendMessage);
$("#steerButton").addEventListener("click", steerCurrentChat);
$("#cancelChatButton").addEventListener("click", cancelChat);
$("#quickMessageTemplates").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-message]");
  if (!button || state.busy) return;
  const input = $("#messageInput");
  input.value = button.dataset.message || "";
  input.dispatchEvent(new Event("input"));
  $("#chatForm").requestSubmit();
});
$("#voiceButton").addEventListener("click", toggleVoiceInput);
$("#pwaUpdateButton").addEventListener("click", applyPwaUpdate);
$("#chatJumpToComposer").addEventListener("click", () => {
  jumpToChatComposer();
});
$("#headerActionButton").addEventListener("click", (event) => {
  if (event.currentTarget.dataset.action === "performance") refreshPerformance();
  else if (event.currentTarget.dataset.action === "activities") syncNow(event);
});
$("#systemIntervalsSyncButton").addEventListener("click", syncNow);
$("#systemIntervalsFullResyncButton").addEventListener("click", () => fullResync("intervals"));
$("#competitionSyncButton").addEventListener("click", syncCompetitions);
$("#garminSyncButton").addEventListener("click", syncGarmin);
$("#externalCalendarSyncButton").addEventListener("click", syncExternalCalendar);
$("#weatherSyncButton").addEventListener("click", syncWeather);
$("#garminFullResyncButton").addEventListener("click", () => fullResync("garmin"));
$("#profileForm").addEventListener("submit", saveProfile);
$("#checkinForm").addEventListener("submit", saveCheckin);
$("#checkinCloseButton").addEventListener("click", () => $("#checkinDialog")?.close());
$("#adaptivePlanningButton").addEventListener("click", prepareReplan);
$("#applyAdaptivePlanningButton").addEventListener("click", applyReplan);
$("#cancelAdaptivePlanningButton").addEventListener("click", () => $("#adaptivePlanningDialog")?.close());
$("#coachAdaptivePlanningButton").addEventListener("click", () => applyNavigationRoute("planned", { historyMode: "push" }));
$("#profileForm").addEventListener("input", () => { state.profileDirty = true; setDirtyIndicator("profileDirtyIndicator", true); });
$("#checkinForm").addEventListener("input", () => { state.checkinDirty = true; setDirtyIndicator("checkinDirtyIndicator", true); });
$("#competitionList").addEventListener("input", () => { state.profileDirty = true; setDirtyIndicator("profileDirtyIndicator", true); });
$("#addCompetitionButton").addEventListener("click", addCompetition);
$("#modelSelect").addEventListener("change", saveModel);
$("#thinkingLevelSelect").addEventListener("change", saveThinkingLevel);
$("#calendarDisplayForm").addEventListener("submit", saveCalendarDisplaySettings);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#logsRefreshButton").addEventListener("click", loadLogs);
$("#chatResetButton").addEventListener("click", resetCoachChat);
$("#privacyExportButton").addEventListener("click", downloadPrivacyExport);
$("#privacyDeleteButton").addEventListener("click", deletePrivacyData);
$("#notificationEnableButton").addEventListener("click", enableNotifications);
$("#backupDownloadButton").addEventListener("click", downloadDatabaseBackup);
$("#backupRestoreButton").addEventListener("click", restoreDatabaseBackup);
$("#logoutButton").addEventListener("click", logout);
$("#libraryLoadButton").addEventListener("click", loadLibrary);
$("#libraryFilter").addEventListener("change", (event) => { state.libraryFilter = event.target.value; renderLibrary(state.data?.library || []); });
$("#systemContextPreviewButton").addEventListener("click", () => {
  $("#systemContextPreviewButton").dataset.loaded = "false";
  loadContextPreview();
});
$("#messageInput").addEventListener("input", (event) => {
  state.chatDraftDirty = Boolean(event.target.value.trim());
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 150)}px`;
});
$("#messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("#chatForm").requestSubmit();
  }
});
$("#activityFromDate").addEventListener("input", (event) => {
  state.activityFromDate = event.target.value;
  state.activityVisibleCount = 250;
  renderActivities(state.data?.activities || []);
});
$("#activityToDate").addEventListener("input", (event) => {
  state.activityToDate = event.target.value;
  state.activityVisibleCount = 250;
  renderActivities(state.data?.activities || []);
});
$("#activityFilterReset").addEventListener("click", () => {
  state.activityTypes.clear();
  state.activityFromDate = "";
  state.activityToDate = "";
  state.activityVisibleCount = 250;
  renderActivities(state.data?.activities || []);
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") savePwaActivity();
  else checkPwaReturn();
  handleSyncVisibility();
});
document.addEventListener("pointerdown", handlePwaInteraction, { passive: true });
window.addEventListener("scroll", updateChatComposerVisibility, { passive: true });
window.addEventListener("resize", updateChatComposerVisibility);
window.addEventListener("pagehide", savePwaActivity);
window.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedChanges()) return;
  event.preventDefault();
  event.returnValue = "";
});
setupPwaUpdates();
renderNotificationStatus();
setupSyncStatusMonitoring();
syncNavigationRoute();
bootstrapAuth();
