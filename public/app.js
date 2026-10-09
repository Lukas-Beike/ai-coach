const $ = (selector) => document.querySelector(selector);
const QUICK_TEMPLATES_INACTIVITY_MS = 6 * 60 * 60 * 1000;
const LAST_PWA_ACTIVITY_KEY = "intervals-coach-last-pwa-activity";
const APPEARANCE_KEY = "intervals-coach-appearance";
const SYNC_POLL_LEASE_KEY = "intervals-coach-sync-poll-lease";
const SYNC_POLL_CHANNEL = "intervals-coach-sync-status";
const SYNC_POLL_ACTIVE_MS = 1_500;
const SYNC_POLL_IDLE_MS = 60_000;
const SYNC_POLL_RETRY_MS = 5_000;
const SYNC_POLL_LEASE_MS = 4_000;
let mobileViewportFrame = null;
const mobileViewportBaselines = { portrait: 0, landscape: 0 };
let mobileViewportInputWasFocused = false;

if ("scrollRestoration" in globalThis.history) globalThis.history.scrollRestoration = "manual";

function applyAppearance(appearance = "system") {
  const selected = ["system", "light", "dark"].includes(appearance) ? appearance : "system";
  let resolved = selected;
  if (selected === "system") resolved = globalThis.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.dataset.theme = resolved;
  const themeColor = $("meta[name='theme-color']");
  if (themeColor) themeColor.content = resolved === "light" ? "#ffffff" : "#0b0b0d";
  const select = $("#appearanceSelect");
  if (select && select.value !== selected) select.value = selected;
  return selected;
}

function loadAppearance() {
  let appearance = "system";
  try { appearance = localStorage.getItem(APPEARANCE_KEY) || "system"; } catch { }
  return applyAppearance(appearance);
}

loadAppearance();
globalThis.matchMedia?.("(prefers-color-scheme: light)").addEventListener?.("change", () => {
  let appearance = "system";
  try { appearance = localStorage.getItem(APPEARANCE_KEY) || "system"; } catch { }
  if (appearance === "system") applyAppearance(appearance);
});

function hasTouchFirstInput() {
  return Boolean(globalThis.navigator?.maxTouchPoints > 0
    && globalThis.matchMedia?.("(pointer: coarse)").matches);
}

function shouldRestoreChatInputFocus() {
  return Boolean(globalThis.matchMedia?.("(hover: hover) and (pointer: fine)").matches);
}

function updateMobileViewportLayout() {
  mobileViewportFrame = null;
  const viewport = globalThis.visualViewport;
  // Playwright and some embedded browsers resize layoutViewport before
  // visualViewport. Use the smaller measurement so keyboard detection does
  // not miss a real visible-area reduction during that transition.
  const viewportHeight = Math.max(1, Math.round(viewport ? Math.min(viewport.height, globalThis.innerHeight) : globalThis.innerHeight));
  const viewportWidth = Math.max(1, Math.round(viewport?.width || globalThis.innerWidth));
  document.documentElement.style.setProperty("--app-viewport-height", `${viewportHeight}px`);
  const input = $("#messageInput");
  const inputFocused = document.activeElement === input;
  const screenOrientation = globalThis.screen?.orientation?.type || "";
  let orientation;
  if (screenOrientation) {
    orientation = screenOrientation.startsWith("landscape") ? "landscape" : "portrait";
  } else {
    orientation = (globalThis.screen?.width || viewportWidth) > (globalThis.screen?.height || viewportHeight) ? "landscape" : "portrait";
  }
  // A viewport resize can transiently blur the input in mobile emulation even
  // though the keyboard interaction is still active. Preserve the previous
  // baseline for that transition so the next focused measurement detects it.
  if (!mobileViewportBaselines[orientation] || (!inputFocused && !mobileViewportInputWasFocused)) {
    mobileViewportBaselines[orientation] = viewportHeight;
  }
  const keyboardOpen = hasTouchFirstInput()
    && inputFocused
    && mobileViewportBaselines[orientation] - viewportHeight >= 100;
  mobileViewportInputWasFocused = inputFocused;
  document.documentElement.classList.toggle("chat-keyboard-open", keyboardOpen);
  if (keyboardOpen && $("#chatPanel")?.classList.contains("active")) {
    const composer = $("#chatForm");
    const viewportTop = Math.round(viewport?.offsetTop || 0);
    const viewportBottom = viewportTop + viewportHeight;
    const bounds = composer?.getBoundingClientRect();
    if (bounds && (bounds.top < viewportTop || bounds.bottom > viewportBottom)) {
      composer.scrollIntoView({ block: "nearest", behavior: "auto" });
    }
  }
  updateChatComposerVisibility();
}

function scheduleMobileViewportLayout() {
  if (mobileViewportFrame !== null) return;
  mobileViewportFrame = requestAnimationFrame(updateMobileViewportLayout);
}

function currentPlanLoadAreas() {
  const areas = new Set(["chat", "performance", "feedback", "profile", "weather"]);
  const route = AppRouter.baseRoute();
  if (route === "plan") {
    areas.add("plan");
    areas.add("library");
  }
  return [...areas];
}

function ensureRouteData(route = state.route) {
  if (!state.data) return;
  const requested = [];
  const panelRoute = AppRouter.baseRoute(route);
  if (panelRoute === "plan" && !state.loadedAreas.has("plan")) requested.push("plan");
  if (panelRoute === "plan" && !state.loadedAreas.has("library")) requested.push("library");
  if (requested.length) load("/api/bootstrap?local=1", requested);
}

function renderActiveRoute(mainRoute, panelRoute) {
  document.dispatchEvent(new CustomEvent("app:route-rendered", { detail: { route: mainRoute } }));
  AppNutrition.handleRoute(panelRoute);
  if (mainRoute === "analysis") renderAnalysisSegments(panelRoute);
  if (mainRoute === "more") AppViews.renderMoreSegments(AppRouter.moreSegmentFromRoute(panelRoute));
  if (mainRoute === "plan") {
    const planSegment = AppRouter.planSegmentFromRoute(panelRoute);
    AppState.setPlanSegment(planSegment);
    if (planSegment === "season" && state.data) void renderSeasonPreparation();
    AppViews.renderPlanSegments(planSegment);
  }
  if (mainRoute === "nutrition") { renderNutritionSegments(panelRoute); if (state.data) { if (panelRoute === "nutrition/products") void loadNutritionProducts(); else void loadNutrition(); } }
  if (state.data && mainRoute === "more") {
    void loadContextPreview();
    void loadLogs();
    void loadChangeHistory();
  }
}

function restoreRouteScroll(mainRoute, returningToChat, shouldFocusPlannedToday) {
  if (mainRoute === "coach") {
    if (state.chatResponseScrollPending) scrollChatToResponseStart();
    else if (state.chatInitialScrollPending) scrollChatToLatest();
    else if (!returningToChat || !restoreChatScrollPosition()) scrollChatToLatest();
    if (state.chatProposalRefreshPending) void refreshChatProposalsInBackground(state.chatContentVersion);
    return;
  }
  requestAnimationFrame(() => {
    if (!shouldFocusPlannedToday || !focusPlannedToday()) globalThis.scrollTo({ top: 0, behavior: "auto" });
  });
}

function readLastPwaActivity() {
  try {
    const value = Number(localStorage.getItem(LAST_PWA_ACTIVITY_KEY));
    return Number.isFinite(value) && value > 0 ? value : 0;
  } catch {
    // Browsers may deny storage access; the activity marker is optional.
    return 0;
  }
}

function savePwaActivity() {
  try { localStorage.setItem(LAST_PWA_ACTIVITY_KEY, String(Date.now())); } catch { }
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

function updatePwaActivity() {
  if (!state.data || document.visibilityState !== "visible") return;
  const lastActivity = readLastPwaActivity();
  if (lastActivity && Date.now() - lastActivity >= QUICK_TEMPLATES_INACTIVITY_MS) state.quickTemplatesVisible = true;
  savePwaActivity();
  renderQuickMessageTemplates();
}

const checkPwaReturn = updatePwaActivity;
const handlePwaInteraction = updatePwaActivity;

function cookie(name) {
  return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
}

function showLogin() {
  state.sessionGeneration += 1;
  state.voiceAcquiring = false;
  stopVoiceRecording();
  stopVoiceCapture();
  state.chatGeneration += 1;
  state.loadSequence += 1;
  state.pendingLoads.clear();
  state.loadPromise = null;
  state.initialStateLoaded = false;
  state.chatStatusPollInFlight = null;
  state.chatStream?.controller.abort();
  state.chatStream = null;
  state.chatQueue = [];
  state.rejectedMessages = [];
  state.coachActionProposals = [];
  state.coachReceipts = [];
  state.voiceTranscribing = false;
  rememberChatTurn(null);
  if (state.chatStatusTimer) clearTimeout(state.chatStatusTimer);
  state.chatStatusTimer = null;
  disconnectStateEvents();
  if (state.stateEventRefreshTimer) clearTimeout(state.stateEventRefreshTimer);
  state.stateEventReconnectTimer = null;
  state.stateEventRefreshTimer = null;
  state.stateEventRefreshAreas.clear();
  state.stateEventLastId = 0;
  state.stateEventBackoff = 1000;
  state.data = null;
  globalThis.ActivityDetails?.close();
  resetNutritionView();
  state.busy = false;
  state.chatRequest = null;
  state.chatStreamText = "";
  state.chatServerOperationId = null;
  state.chatResponseStarted = false;
  state.chatResponseScrollPending = false;
  state.chatResponseMessageId = null;
  state.chatProposalRefreshPending = false;
  state.chatProposalRefreshInFlight = false;
  state.chatProposalRefreshQueued = false;
  state.chatInitialScrollPending = true;
  state.chatScrollY = null;
  state.chatScrollRestoring = false;
  cancelScheduledChatStreamRender();
  state.loadedAreas.clear();
  AppState.setPlanSegment("overview");
  state.profileDirty = false;
  state.checkinDirty = false;
  state.chatAttachments = [];
  renderChatAttachments();
  state.chatDraftDirty = false;
  $("#appShell").hidden = true;
  $("#authLoading").hidden = true;
  const dialog = $("#loginDialog");
  showAccessibleDialog(dialog, $("#loginPassword"));
}

let confirmationResolver = null;

function requestConfirmation(message, { title = "Aktion bestätigen", inputLabel = "", expectedText = "" } = {}) {
  const dialog = $("#confirmationDialog");
  const form = $("#confirmationDialogForm");
  const messageNode = $("#confirmationDialogMessage");
  const titleNode = $("#confirmationDialogTitle");
  const inputLabelNode = $("#confirmationDialogInputLabel");
  const input = $("#confirmationDialogInput");
  if (!dialog || !form || !messageNode || !titleNode || !inputLabelNode || !input) return Promise.resolve(false);
  if (confirmationResolver) confirmationResolver(false);
  dialog.dataset.expectedText = expectedText;
  titleNode.textContent = title;
  messageNode.textContent = message;
  inputLabelNode.hidden = !expectedText;
  inputLabelNode.firstChild.textContent = inputLabel || "Bestätigungstext";
  input.value = "";
  input.required = Boolean(expectedText);
  input.setCustomValidity("");
  return new Promise((resolve) => {
    confirmationResolver = resolve;
    showAccessibleDialog(dialog, expectedText ? input : $("#confirmationDialogCancel"));
  });
}

function settleConfirmation(value) {
  const resolve = confirmationResolver;
  confirmationResolver = null;
  if (resolve) resolve(value);
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
  // The first local bootstrap deliberately renders the chat while the shell is
  // still loading. Re-render after removing that state so its placeholder is
  // replaced even if a deferred domain request has not settled yet.
  renderMessages(state.data?.messages || [], true);
  void AppRouter.navigate(AppRouter.routeFromHash(), { historyMode: AppRouter.hashContainsKnownRoute() ? "none" : "replace" });
}

async function api(path, options = {}) {
  const generation = state.sessionGeneration;
  const result = await globalThis.AppApi.request(path, options, () => {
    if (generation === state.sessionGeneration) showLogin();
  });
  if (generation !== state.sessionGeneration) throw new DOMException("Session ended", "AbortError");
  renderConnectivityStatus(true);
  return result;
}

async function downloadRequest(path, fallback, timeoutMs = 25_000) {
  const timeoutMessage = timeoutMs > 25_000
    ? "Der Download konnte nicht innerhalb von zwei Minuten bestätigt werden."
    : "Der Server antwortet nicht innerhalb von 25 Sekunden.";
  const generation = state.sessionGeneration;
  return globalThis.AppApi.download(path, { fallback, signal: undefined, timeoutMessage, timeoutMs }, () => {
    if (generation === state.sessionGeneration) showLogin();
  });
}

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

async function apiAudio(path, blob) {
  const generation = state.sessionGeneration;
  const result = await globalThis.AppApi.audio(path, blob, () => {
    if (generation === state.sessionGeneration) showLogin();
  });
  if (generation !== state.sessionGeneration) throw new DOMException("Session ended", "AbortError");
  return result;
}

async function bootstrapAuth() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const status = await globalThis.AppApi.request("/api/auth/status", { cache: "no-store", signal: controller.signal });
    renderMaintenanceStatus(status.maintenance);
    if (status.authenticated) {
      $("#authLoading").hidden = true;
      $("#loginDialog").close();
      showAppShellLoading();
      notePwaActivity();
      await loadInitialState();
    } else showLogin();
  } catch {
    renderConnectivityStatus(false);
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
  node.setAttribute("role", error ? "alert" : "status");
  node.setAttribute("aria-live", error ? "assertive" : "polite");
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 3000);
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

async function waitForSyncJob(jobId) {
  if (!jobId) return { status: "unknown" };
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const job = await api(`/api/sync/jobs/${encodeURIComponent(jobId)}`);
    if (["completed", "partial", "failed"].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Die Synchronisierung läuft länger als erwartet. Der Job kann unter Betrieb & Diagnose weiter verfolgt werden.");
}

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
  button.disabled = permission === "granted" || permission === "unsupported";
  button.textContent = permission === "granted" ? "Aktiviert" : "Benachrichtigungen aktivieren";
}

async function enableNotifications() {
  if (!("Notification" in globalThis)) { toast("Dieser Browser unterstützt keine PWA-Benachrichtigungen", true); return; }
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
  } catch { }
}

function notifyState(data) {
  const next = data.planning?.season?.next_event;
  if (next && next.days_until >= 0 && next.days_until <= 3) void showPwaNotification("Wettkampf steht bevor", { body: `${next.name} ist in ${next.days_until} Tag(en).`, tag: `competition:${next.id}` }, `competition:${next.id}:${next.event_date}`);
  const error = data.sync?.last_error || data.garmin_sync?.status?.includes("Fehler") && data.garmin_sync.status;
  if (error) void showPwaNotification("Intervals Coach benötigt Aufmerksamkeit", { body: String(error), tag: "sync-error" }, `error:${error}`);
}

function todayIso() { return timezoneDateKey(state.data?.profile?.timezone, new Date()); }

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
  const illnessNeedsForecast = Boolean(illness && (!preview?.illness_pause || previewIllness !== illness || !preview.illness_pause?.approved));
  const pendingIllnessPause = Boolean(preview?.status === "preview" && preview?.illness_pause && !preview.illness_pause.approved);
  const required = Boolean(planning.needs_replan || illnessNeedsForecast || pendingIllnessPause);
  const count = Number(planning.replan_changes || changes.length);
  let caption;
  if (illnessNeedsForecast || pendingIllnessPause) caption = "Krankheit gemeldet: Sportpause prognostizieren und bestätigen.";
  else if (count === 1) caption = "Ein zukünftiger Entwurf braucht eine Anpassung.";
  else caption = `${count} zukünftige Entwürfe brauchen eine Anpassung.`;
  const coachNotice = $("#coachAdaptivePlanningNotice");
  if (coachNotice) {
    coachNotice.hidden = !required;
    const detail = coachNotice.querySelector("small");
    if (detail) detail.textContent = required ? `${caption} Bitte den Coach um die Anpassung.` : "";
  }
}

function renderExternalCalendar(data) {
  const calendar = data.external_calendar || {};
  const status = $("#externalCalendarConnectionStatus");
  const syncButton = $("#externalCalendarSyncButton");
  if (status) {
    if (!calendar.configured) status.textContent = "Nicht konfiguriert";
    else if (calendar.last_error) status.textContent = "Fehler bei letzter Aktualisierung";
    else status.textContent = "Konfiguriert · nur lesend";
    status.className = calendar.configured && !calendar.last_error ? "configured" : "not-configured";
  }
  if (syncButton) {
    syncButton.disabled = Boolean(calendar.running || state.localSync.externalCalendar);
    syncButton.textContent = calendar.running || state.localSync.externalCalendar ? "Synchronisierung läuft…" : "Synchronisieren";
  }
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

function providerRequiresManualAttention(entry) {
  if (!entry?.configured) return false;
  if (["auth_required", "invalid_configuration"].includes(entry.error_code)) return true;
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

function hasUnsavedChanges({ includeChatDraft = true } = {}) {
  return state.profileDirty
    || state.checkinDirty
    || (includeChatDraft && (state.chatQueue.length > 0 || state.rejectedMessages.length > 0 || state.chatDraftDirty || Boolean($("#messageInput")?.value.trim())));
}

function setDirtyIndicator(id, dirty) {
  const indicator = $(`#${id}`);
  if (indicator) indicator.hidden = !dirty;
}

async function confirmDiscardChanges() {
  return !hasUnsavedChanges({ includeChatDraft: false }) || Boolean(await requestConfirmation("Ungespeicherte Änderungen verwerfen?", { title: "Änderungen verwerfen?" }));
}

function discardUnsavedChanges() {
  state.profileDirty = false;
  state.checkinDirty = false;
  if (state.data) render(state.data);
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
  let statusTitle = "Coach ist bereit";
  let statusDetail = "Bereit für deine nächste Frage";
  if (missing.length) {
    statusTitle = `Einrichtung nötig: ${missing.join(" + ")}`;
    statusDetail = "Ergänze die fehlende Serverkonfiguration";
  } else if (error) {
    statusTitle = "Coach benötigt Aufmerksamkeit";
    statusDetail = error;
  } else if (morning.status === "ready") {
    statusDetail = `Morgen-Check-in abgeschlossen: ${dateLabel(morning.date)}`;
  }
  if ($("#statusTitle").textContent !== statusTitle) $("#statusTitle").textContent = statusTitle;
  if ($("#statusDetail").textContent !== statusDetail) $("#statusDetail").textContent = statusDetail;
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

function distanceLabel(value) {
  const distance = Number(value);
  if (!Number.isFinite(distance) || distance <= 0) return null;
  return `${(distance / 1000).toFixed(1)} km`;
}

function activitySportLabel(activity) {
  const value = String(activity?.type || "").toLowerCase();
  if (value === "virtualride") return "Rad indoor";
  if (/ride|bike|cycling|rad|velo|bicycle/.test(value)) return "Radfahren";
  if (/run|lauf|jog/.test(value)) return "Laufen";
  if (/swim|schwimm/.test(value)) return "Schwimmen";
  if (/strength|kraft|gym|weight/.test(value)) return "Kraft";
  return "Andere";
}

function trainingPlanEntry(item) {
  const entry = document.createElement("div");
  entry.className = "training-plan-entry";
  entry.textContent = `${item.date ? dateLabel(item.date) : "Ohne Datum"} · ${item.name || "Einheit"} · ${item.duration_minutes || Math.round(Number(item.moving_time || 0) / 60) || "?"} Min.`;
  return entry;
}

function trainingPlanCard(plan, planEntries) {
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
    planEntries.sort((a, b) => String(a.date || "").localeCompare(String(b.date || ""))).forEach((entry) => body.append(trainingPlanEntry(entry)));
    if (!planEntries.length) {
      const empty = document.createElement("p");
      empty.className = "fine-print";
      empty.textContent = "Keine aktiven Einheiten zu diesem Plan vorhanden.";
      body.append(empty);
    }
    details.append(body);
    return details;
}

function renderTrainingPlans(plans, workouts) {
  const root = $("#trainingPlans");
  if (!root) return;
  root.replaceChildren();
  const entries = (workouts || []).filter((item) => item?.plan_id && !item?.archived);
  if (!Array.isArray(plans) || !plans.length) return;
  const heading = document.createElement("h3");
  heading.className = "subsection-title";
  heading.textContent = "Mehrwochenpläne";
  root.append(heading);
  plans.forEach((plan) => {
    const planEntries = entries.filter((item) => String(item.plan_id) === String(plan.id));
    root.append(trainingPlanCard(plan, planEntries));
  });
}

function planWeekStart(dateKey) {
  const value = dateFromKey(dateKey);
  if (Number.isNaN(value.valueOf())) return "";
  const weekday = value.getDay();
  value.setDate(value.getDate() - (weekday === 0 ? 6 : weekday - 1));
  return localDateKey(value);
}

function planWeekLabel(weekStartKey) {
  const start = dateFromKey(weekStartKey);
  const end = dateFromKey(addDateKey(weekStartKey, 6));
  if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) return weekStartKey;
  const startLabel = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit" }).format(start);
  const endLabel = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" }).format(end);
  return `${startLabel} – ${endLabel}`;
}

function plannedWeatherLabel(weather) {
  if (!weather || typeof weather !== "object") return "";
  const hasForecast = weather.condition || weather.weather_code != null
    || weather.temperature_min != null || weather.temperature_max != null;
  if (!hasForecast) return "";
  const temperatures = [weather.temperature_min, weather.temperature_max]
    .filter((value) => value != null && value !== "" && Number.isFinite(Number(value)))
    .map((value) => weatherNumber(value, "°"));
  return [weatherIconFor(weather), temperatures.join(" / ")].filter(Boolean).join(" ");
}

function plannedAppointmentLabel(event) {
  if (!event || typeof event !== "object") return "";
  const name = String(event.name || "Trainingstermin").trim() || "Trainingstermin";
  if (event.all_day) return `${name} · ganztägig`;
  const time = /(?:T|\s)(\d{2}:\d{2})/.exec(String(event.start_local || ""));
  return time ? `${name} · ${time[1]}` : name;
}

function appendPlannedWeatherInsight(body, weather) {
  const weatherLabel = plannedWeatherLabel(weather);
  if (!weather || !weatherLabel) return;
  const condition = document.createElement("p");
  condition.className = "planned-weather-detail";
  condition.textContent = [weather.condition, weatherLabel].filter(Boolean).join(" · ");
  condition.title = [
    weather.archived_forecast ? "Gespeicherte Wettervorhersage" : "Wettervorhersage",
    "Open-Meteo", weather.forecast_location || state.data?.weather?.location?.name,
    weather.forecast_saved_at ? `Stand: ${formatTime(weather.forecast_saved_at)}` : null,
  ].filter(Boolean).join(" · ");
  body.append(condition);
  const directionValue = calendarMetricNumber(weather.wind_direction_dominant);
  const direction = directionValue != null && Number(weather.wind_direction_dominant) >= 0 && Number(weather.wind_direction_dominant) <= 360
    ? weatherDirection(weather.wind_direction_dominant) : "";
  const peakTime = /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(weather.rain_peak_time || "") ? weather.rain_peak_time : "";
  const values = [
    calendarMetricNumber(weather.precipitation_probability_max, ` % Regen${peakTime ? " (max. " + peakTime + " Uhr)" : ""}`),
    calendarMetricNumber(weather.wind_speed_max, ` km/h Wind${direction ? " " + direction : ""}`),
    calendarMetricNumber(weather.wind_gusts_max, " km/h Böen"),
  ].filter(Boolean);
  if (peakTime && weather.precipitation_probability_max == null) values.unshift(`Regen am ehesten ${peakTime} Uhr`);
  if (values.length) {
    const metrics = document.createElement("p");
    metrics.className = "planned-weather-metrics";
    metrics.textContent = values.join(" · ");
    body.append(metrics);
  }
}

function plannedDayInsights(weather) {
  const content = document.createElement("div");
  content.className = "planned-insights-content";
  appendPlannedWeatherInsight(content, weather);
  if (!content.childElementCount) return null;
  const section = document.createElement("div");
  section.className = "planned-day-insights";
  const title = document.createElement("p");
  title.className = "planned-insights-title";
  title.textContent = "Wetter";
  section.append(title, content);
  return section;
}

function plannedWeekSummary(weekKey, weekEndKey, weekEntries, compliance, todayKey) {
  const plannedEntryCount = weekEntries.filter((entry) => !entry.is_completed_activity).length;
  const plannedUnits = Number.isFinite(Number(compliance?.planned_units))
    ? Number(compliance.planned_units)
    : plannedEntryCount;
  const completedUnits = Number.isFinite(Number(compliance?.completed_units))
    ? Number(compliance.completed_units)
    : 0;
  const isPast = weekEndKey < todayKey;
  const units = isPast || completedUnits > 0
    ? `${plannedUnits} geplant · ${completedUnits} absolviert`
    : `${plannedUnits} geplant`;
  if (compliance?.basis !== "training_load" || compliance.planned_value == null) return units;
  const load = [`Load geplant ${formatWhole(compliance.planned_value)}`];
  if (isPast || completedUnits > 0) load.push(`absolviert ${formatWhole(compliance.actual_value || 0)}`);
  return `${units} · ${load.join(" · ")}`;
}

function calendarActualActivity(entry) {
  if (!entry || typeof entry !== "object") return null;
  if (entry.is_completed_activity) return entry;
  const actual = entry.compliance?.actual_activity;
  return actual && typeof actual === "object" ? actual : null;
}

function calendarEntryStatus(entry, dateKey, todayKey) {
  if (calendarActualActivity(entry)) return "completed";
  if (entry?.compliance?.status === "missed") return "missed";
  return dateKey === todayKey ? "today" : "planned";
}

function calendarStatusLabel(entry, dateKey, todayKey) {
  const status = calendarEntryStatus(entry, dateKey, todayKey);
  if (status === "completed") return entry.is_completed_activity ? "✓ Zusätzlich absolviert" : "✓ Abgeschlossen";
  if (status === "missed") return "Nicht absolviert";
  return status === "today" ? "Heute geplant" : "Geplant";
}

function calendarMetricNumber(value, suffix = "") {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const digits = Number.isInteger(number) ? 0 : 1;
  return `${number.toLocaleString("de-DE", { maximumFractionDigits: digits })}${suffix}`;
}

function calendarRpeLabel(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 10 ? calendarMetricNumber(number) : null;
}

function calendarIntensityLabel(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return null;
  const percent = number > 0 && number <= 2 ? number * 100 : number;
  return `${Math.round(percent)} %`;
}

function calendarStartTime(value) {
  const match = /(?:T|\s)(\d{2}:\d{2})/.exec(String(value || ""));
  return match ? match[1] : null;
}

function calendarPaceLabel(activity) {
  if (activitySportLabel(activity) !== "Laufen") return null;
  const duration = Number(activity?.moving_time);
  const distance = Number(activity?.distance);
  return duration > 0 && distance > 0 ? formatPace(duration / (distance / 1000)) : null;
}

function calendarCountLabel(entries, todayKey) {
  const counts = { completed: 0, planned: 0, missed: 0 };
  entries.forEach((entry) => {
    const status = calendarEntryStatus(entry, plannedEventDate(entry), todayKey);
    if (status === "completed") counts.completed += 1;
    else if (status === "missed") counts.missed += 1;
    else counts.planned += 1;
  });
  return [
    counts.completed ? `${counts.completed} abgeschlossen` : "",
    counts.planned ? `${counts.planned} geplant` : "",
    counts.missed ? `${counts.missed} nicht absolviert` : "",
  ].filter(Boolean).join(" · ");
}

function appendCalendarFact(root, label, value) {
  if (value == null || value === "") return;
  const item = document.createElement("span");
  const title = document.createElement("strong");
  title.textContent = label;
  item.append(title, document.createTextNode(` ${value}`));
  root.append(item);
}

function focusPlannedToday() {
  if (!state.plannedTodayFocusPending || !state.loadedAreas.has("plan")) return false;
  if (AppRouter.baseRoute(state.route) !== "plan" || AppRouter.planSegmentFromRoute(state.route) !== "overview") return false;
  const today = $("#plannedCalendar")?.querySelector(".planned-day.is-today");
  if (!today) return false;
  const week = today.closest(".planned-week");
  if (week) week.open = true;
  state.plannedTodayFocusPending = false;
  today.scrollIntoView({ block: "start", behavior: "auto" });
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (AppRouter.baseRoute(state.route) === "plan" && today.isConnected) today.scrollIntoView({ block: "start", behavior: "auto" });
  }));
  return true;
}

function plannedEntryDurationLabel(actual, entry) {
  if (actual) return formatDuration(actual.moving_time ?? actual.elapsed_time);
  if (entry.duration_minutes) return `${entry.duration_minutes} Min.`;
  return formatDuration(entry.moving_time);
}

function appendActualCalendarDetails(details, actual) {
  if (!actual) return;
  const primaryMetrics = document.createElement("span");
  primaryMetrics.className = "planned-actual-summary";
  const load = calendarMetricNumber(actual.icu_training_load);
  const rpe = calendarRpeLabel(actual.icu_rpe);
  primaryMetrics.textContent = [load != null ? `Load ${load}` : null, rpe != null ? `RPE ${rpe}/10` : "RPE offen"].filter(Boolean).join(" · ");
  const facts = document.createElement("div");
  facts.className = "planned-actual-facts";
  appendCalendarFact(facts, "Dauer", formatDuration(actual.moving_time ?? actual.elapsed_time));
  appendCalendarFact(facts, "Distanz", distanceLabel(actual.distance));
  appendCalendarFact(facts, "Trainingsload", calendarMetricNumber(actual.icu_training_load));
  appendCalendarFact(facts, "RPE", rpe != null ? `${rpe}/10` : "nicht angegeben");
  appendCalendarFact(facts, "Intensität", calendarIntensityLabel(actual.icu_intensity));
  appendCalendarFact(facts, "Ø Puls", calendarMetricNumber(actual.average_heartrate, " bpm"));
  appendCalendarFact(facts, "Ø Leistung", calendarMetricNumber(actual.weighted_average_watts ?? actual.average_watts, " W"));
  appendCalendarFact(facts, "Pace", calendarPaceLabel(actual));
  appendCalendarFact(facts, "Höhenmeter", calendarMetricNumber(actual.total_elevation_gain, " hm"));
  details.append(primaryMetrics, facts);
}

function appendPlannedCalendarComparison(details, entry, actual) {
  if (!actual || entry.is_completed_activity) return;
  const comparison = document.createElement("div");
  comparison.className = "planned-comparison";
  const plannedDuration = entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.moving_time;
  const planLine = document.createElement("p");
  planLine.textContent = `Plan: ${[
    entry.name,
    formatDuration(plannedDuration),
    entry.icu_training_load != null ? `Load ${calendarMetricNumber(entry.icu_training_load)}` : null,
  ].filter(Boolean).join(" · ")}`;
  const actualLine = document.createElement("p");
  actualLine.textContent = `Ist: ${[
    formatDuration(actual.moving_time ?? actual.elapsed_time),
    actual.icu_training_load != null ? `Load ${calendarMetricNumber(actual.icu_training_load)}` : null,
  ].filter(Boolean).join(" · ")}`;
  comparison.append(planLine, actualLine);
  if (entry.compliance?.percentage != null) {
    const ratio = document.createElement("p");
    ratio.textContent = `${entry.compliance.basis === "training_load" ? "Load" : "Umfang"} Plan/Ist: ${entry.compliance.percentage} %`;
    comparison.append(ratio);
  }
  details.append(comparison);
}

function appendPlannedSessionHeader(cardSummary, entry, actual) {
  const displayed = actual || entry;
  const header = document.createElement("span");
  header.className = "planned-session-header";
  const sport = document.createElement("span");
  sport.textContent = [activitySportLabel(displayed), calendarStartTime(displayed.start_date_local)].filter(Boolean).join(" · ");
  const duration = document.createElement("strong");
  duration.textContent = plannedEntryDurationLabel(actual, entry);
  const distance = document.createElement("span");
  distance.textContent = displayed.distance > 0 ? distanceLabel(displayed.distance) : "";
  header.append(sport, duration, distance);
  const metrics = document.createElement("span");
  metrics.className = "planned-session-metrics";
  metrics.textContent = [
    actual ? calendarMetricNumber(actual.average_heartrate, " bpm") : null,
    actual ? calendarMetricNumber(actual.average_watts ?? actual.weighted_average_watts, " W") : null,
    calendarMetricNumber(displayed.icu_training_load) != null ? `Belastung ${calendarMetricNumber(displayed.icu_training_load)}` : null,
  ].filter(Boolean).join(" · ");
  cardSummary.append(header);
  if (metrics.textContent) cardSummary.append(metrics);
}

function appendPlannedExecution(cardSummary, entry, status) {
  const percentage = calendarMetricNumber(entry.compliance?.percentage);
  const measurable = percentage != null && ["training_load", "duration"].includes(entry.compliance?.basis);
  if (status !== "missed" && !measurable) return;
  const execution = document.createElement("span");
  const value = status === "missed" ? 0 : Number(entry.compliance.percentage);
  let executionState = "is-on-target";
  if (value < 80 || value > 120) executionState = "is-deviation";
  if (value === 0) executionState = "is-zero";
  execution.className = `planned-execution ${executionState}`;
  execution.textContent = `${value === 0 ? "✕" : "✓"} ${status === "missed" ? "0" : percentage} %`;
  const basis = { training_load: "Belastung", duration: "Dauer" }[entry.compliance?.basis];
  execution.title = basis ? `Ausführung gegenüber Plan (${basis})` : "Ausführung gegenüber Plan";
  execution.setAttribute("aria-label", [`${value} Prozent des Plans`, basis].filter(Boolean).join(" · "));
  cardSummary.append(execution);
  if (status !== "missed") {
    const meter = document.createElement("span");
    meter.className = "planned-execution-track";
    meter.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, value))}%`;
    meter.append(fill);
    cardSummary.append(meter);
  }
}

let calendarProfileSequence = 0;

function calendarWorkoutProfile(profile) {
  const segments = profile?.segments;
  if (!Array.isArray(segments) || !segments.length || segments.length > 1000) return null;
  const total = segments.reduce((sum, item) => sum + (Number.isFinite(item.duration) && item.duration > 0 ? item.duration : 0), 0);
  const values = segments.flatMap((item) => [item.value, item.end_value]).filter((value) => value != null && Number.isFinite(value) && value >= 0);
  if (!total || !values.length) return null;
  const top = Math.max(...values, 1) * 1.1;
  const label = profile.source === "recorded" ? "Aufgezeichnetes Belastungsprofil" : "Geplantes Intervallprofil";
  const svg = analysisSvg("svg", { viewBox: "0 0 300 56", role: "img", "aria-label": label, class: "calendar-workout-profile", preserveAspectRatio: "none" });
  const gradientPrefix = `calendar-profile-${++calendarProfileSequence}`;
  const defs = analysisSvg("defs");
  for (const zone of [1, 2, 3, 4, 5, 6, 7, "unknown"]) {
    const gradient = analysisSvg("linearGradient", { id: `${gradientPrefix}-${zone}`, x1: 0, y1: 0, x2: 0, y2: 1, "data-zone": zone });
    gradient.append(analysisSvg("stop", { offset: "0%", "stop-color": "currentColor" }));
    gradient.append(analysisSvg("stop", { offset: "100%", "stop-color": "currentColor", "stop-opacity": .35 }));
    defs.append(gradient);
  }
  svg.append(defs);
  svg.append(analysisSvg("title", {}, `${label} · Zeitachse · ${profile.unit || ""}`));
  svg.append(analysisSvg("line", { x1: 0, x2: 300, y1: 54, y2: 54, class: "calendar-profile-baseline" }));
  let offset = 0;
  for (const item of segments) {
    if (!Number.isFinite(item.duration) || item.duration <= 0) continue;
    const x = offset / total * 300, width = item.duration / total * 300;
    offset += item.duration;
    if (item.value == null || item.end_value == null || !Number.isFinite(item.value) || !Number.isFinite(item.end_value)) continue;
    const left = 54 - Math.max(0, item.value) / top * 50;
    const right = 54 - Math.max(0, item.end_value) / top * 50;
    const zone = Number.isInteger(item.zone) && item.zone >= 1 && item.zone <= 7 ? item.zone : "unknown";
    const shape = analysisSvg("polygon", { points: `${x},54 ${x},${left} ${x + width},${right} ${x + width},54`, "data-zone": zone, fill: `url(#${gradientPrefix}-${zone})` });
    shape.append(analysisSvg("title", {}, `${formatDuration(item.duration)} · ${item.label || ""}`));
    svg.append(shape);
  }
  return svg;
}

function renderPlannedEntry(entry, dateKey, todayKey) {
  const actual = calendarActualActivity(entry);
  const status = calendarEntryStatus(entry, dateKey, todayKey);
  const card = document.createElement("details");
  card.className = `planned-entry is-${status}`;
  card.open = false;
  const cardSummary = document.createElement("summary");
  const cardTitle = document.createElement("strong");
  cardTitle.textContent = actual?.name || entry.name || "Trainingseinheit";
  const meta = document.createElement("span");
  meta.className = "planned-meta";
  const displayed = actual || entry;
  card.dataset.sport = activitySportLabel(displayed);
  meta.textContent = [
    activitySportLabel(displayed),
    calendarStartTime(displayed.start_date_local),
    plannedEntryDurationLabel(actual, entry),
  ].filter(Boolean).join(" · ");
  appendPlannedSessionHeader(cardSummary, entry, actual);
  cardSummary.append(meta);
  if (status === "completed" || status === "missed") {
    const statusText = document.createElement("span");
    statusText.className = "planned-entry-status";
    statusText.textContent = calendarStatusLabel(entry, dateKey, todayKey);
    cardSummary.append(statusText);
  }
  appendPlannedExecution(cardSummary, entry, status);
  const profile = calendarWorkoutProfile(actual?.workout_profile || entry.workout_profile);
  if (profile) cardSummary.append(profile);
  cardSummary.append(cardTitle);
  if (actual && !entry.is_completed_activity) {
    const target = document.createElement("span");
    target.className = "planned-session-target";
    const targetParts = [entry.name || "Training", plannedEntryDurationLabel(null, entry)];
    if (entry.icu_training_load != null) targetParts.push(`Belastung ${calendarMetricNumber(entry.icu_training_load)}`);
    target.textContent = `Plan: ${targetParts.join(" · ")}`;
    cardSummary.append(target);
  }
  const details = document.createElement("div");
  details.className = "planned-entry-details";
  appendActualCalendarDetails(details, actual);
  if (actual && (actual.id || actual.activity_id)) {
    const activityButton = document.createElement("button");
    activityButton.type = "button";
    activityButton.className = "secondary-button";
    activityButton.textContent = "Aktivität analysieren";
    activityButton.addEventListener("click", () => globalThis.ActivityDetails.open(actual, {
      api,
      showDialog: showAccessibleDialog,
    }));
    details.append(activityButton);
  }
  appendPlannedCalendarComparison(details, entry, actual);
  if (entry.description) {
    const description = document.createElement("p");
    description.className = "planned-description";
    description.textContent = entry.description;
    details.append(description);
  }
  if (!details.childElementCount) {
    const description = document.createElement("p");
    description.className = "planned-description";
    description.textContent = "Keine weiteren Details hinterlegt.";
    details.append(description);
  }
  card.append(cardSummary, details);
  return card;
}

function plannedDayWeather(dayContext, dateKey) {
  if (dayContext.weather) return dayContext.weather;
  const days = state.data?.weather?.days;
  return Array.isArray(days) ? days.find((item) => item?.date === dateKey) : null;
}

function appendPlannedDayHeading(day, weather, dateKey, todayKey) {
  const heading = document.createElement("div");
  heading.className = "planned-day-heading";
  const title = document.createElement("h5");
  title.id = `planned-day-${dateKey}`;
  title.textContent = new Intl.DateTimeFormat("de-DE", { weekday: "short" }).format(dateFromKey(dateKey));
  day.setAttribute("aria-labelledby", title.id);
  const dayDate = document.createElement("time");
  dayDate.dateTime = dateKey;
  const dayNumber = document.createElement("strong");
  dayNumber.textContent = new Intl.DateTimeFormat("de-DE", { day: "2-digit" }).format(dateFromKey(dateKey));
  const month = document.createElement("span");
  month.textContent = new Intl.DateTimeFormat("de-DE", { month: "short" }).format(dateFromKey(dateKey));
  dayDate.append(dayNumber, month);
  heading.append(title, dayDate);
  if (dateKey === todayKey) {
    const today = document.createElement("span");
    today.className = "planned-today-label";
    today.textContent = "Heute";
    heading.append(today);
  }
  const weatherLabel = plannedWeatherLabel(weather);
  if (weatherLabel) {
    const weatherText = document.createElement("span");
    weatherText.className = "planned-day-weather";
    weatherText.textContent = weatherLabel;
    weatherText.title = [weather.archived_forecast ? "Gespeicherte Wettervorhersage" : "Wettervorhersage", weather.condition, weatherLabel].filter(Boolean).join(": ");
    weatherText.setAttribute("aria-label", weatherText.title);
    heading.append(weatherText);
  } else {
    const weatherMissing = document.createElement("span");
    weatherMissing.className = "planned-day-weather is-missing";
    weatherMissing.textContent = "Wetter fehlt";
    if (!state.data?.weather?.configured) weatherMissing.title = "Kein Wetterort im Profil hinterlegt";
    else if (dateKey < todayKey) weatherMissing.title = "Für diesen Tag wurde keine Vorhersage gespeichert";
    else weatherMissing.title = "Für diesen Tag ist keine Vorhersage verfügbar";
    heading.append(weatherMissing);
  }
  day.append(heading);
}

function plannedDayNotes(dayContext) {
  const notes = document.createElement("div");
  notes.className = "planned-day-notes";
  const appointments = (Array.isArray(dayContext.appointments) ? dayContext.appointments : [])
    .filter((event) => event && event.training_relevant !== false)
    .map(plannedAppointmentLabel)
    .filter(Boolean);
  if (appointments.length) {
    const calendarNotice = document.createElement("p");
    calendarNotice.className = "planned-day-context planned-day-calendar";
    calendarNotice.textContent = `Kalender: ${appointments.join(", ")}`;
    notes.append(calendarNotice);
  }
  const checkin = dayContext.checkin && typeof dayContext.checkin === "object" ? dayContext.checkin : {};
  const illness = String(checkin.illness || "").trim();
  const pain = String(checkin.pain || "").trim();
  if (illness || pain) {
    const healthNotice = document.createElement("p");
    healthNotice.className = "planned-day-context planned-day-health";
    healthNotice.textContent = [
      illness ? `Krankheit: ${illness}` : "",
      pain ? `Verletzung/Beschwerden: ${pain}` : "",
    ].filter(Boolean).join(" · ");
    notes.append(healthNotice);
  }
  return notes;
}

function renderPlannedDay(view, dateKey) {
  const { eventsByDate, planningContextByDate, todayKey } = view;
  const dayEntries = eventsByDate.get(dateKey) || [];
  const dayContext = planningContextByDate.get(dateKey) || {};
  const weather = plannedDayWeather(dayContext, dateKey);
  const day = document.createElement("section");
  day.className = `planned-day${dateKey === todayKey ? " is-today" : ""}`;
  day.dataset.date = dateKey;
  appendPlannedDayHeading(day, weather, dateKey, todayKey);
  const content = document.createElement("div");
  content.className = "planned-day-content";
  const notes = plannedDayNotes(dayContext);
  if (notes.childElementCount) content.append(notes);
  if (!dayEntries.length) {
    const empty = document.createElement("p");
    empty.className = "planned-day-empty";
    empty.textContent = dateKey < todayKey ? "Keine Aktivität" : "Keine Einheit geplant";
    content.append(empty);
  }
  dayEntries.forEach((entry) => content.append(renderPlannedEntry(entry, dateKey, todayKey)));
  const insights = plannedDayInsights(weather);
  if (insights) day.append(insights);
  day.append(content);
  return day;
}

function renderPlannedWeek(view, weekIndex) {
  const { currentWeekKey, eventsByDate, firstWeekKey, nextWeekKey, previousWeekOpenState, todayKey, weeklyCompliance } = view;
  const weekKey = addDateKey(firstWeekKey, weekIndex * 7);
  const weekEndKey = addDateKey(weekKey, 6);
  const weekEntries = Array.from({ length: 7 }, (_, offset) => eventsByDate.get(addDateKey(weekKey, offset)) || []).flat();
  const week = document.createElement("details");
  week.className = "planned-week";
  week.dataset.weekKey = weekKey;
  week.open = previousWeekOpenState.has(weekKey) ? previousWeekOpenState.get(weekKey) : weekKey === currentWeekKey || weekKey === nextWeekKey;
  const heading = document.createElement("summary");
  heading.className = "planned-week-heading";
  const title = document.createElement("h4");
  title.textContent = planWeekLabel(weekKey);
  const count = document.createElement("span");
  count.className = "planned-week-summary";
  count.textContent = calendarCountLabel(weekEntries, todayKey) || "Keine Einheiten";
  heading.append(title, count);
  const totals = document.createElement("span");
  totals.className = "planned-week-metrics";
  const sum = (items, metric) => items.reduce((total, item) => total + Math.max(0, Number(metric(item)) || 0), 0);
  const planned = weekEntries.filter((entry) => !entry.is_completed_activity);
  const actual = weekEntries.map(calendarActualActivity).filter(Boolean);
  const plannedSeconds = sum(planned, (entry) => entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.moving_time);
  const actualSeconds = sum(actual, (entry) => entry.moving_time ?? entry.elapsed_time);
  for (const [label, value] of [
    ["Geplant", formatDuration(plannedSeconds)],
    ["Absolviert", formatDuration(actualSeconds)],
    ["Distanz", actual.length && actual.every((entry) => entry.distance != null) ? distanceLabel(sum(actual, (entry) => entry.distance)) || "0 km" : "–"],
    ["Belastung geplant", planned.length && planned.every((entry) => entry.icu_training_load != null) ? calendarMetricNumber(sum(planned, (entry) => entry.icu_training_load)) : "–"],
    ["Belastung absolviert", actual.length && actual.every((entry) => entry.icu_training_load != null) ? calendarMetricNumber(sum(actual, (entry) => entry.icu_training_load)) : "–"],
  ]) {
    const metric = document.createElement("span");
    const number = document.createElement("strong");
    number.textContent = value;
    metric.append(document.createTextNode(`${label} `), number);
    totals.append(metric);
  }
  heading.append(totals);
  week.append(heading);
  const days = document.createElement("div");
  days.className = "planned-week-days";
  for (let offset = 0; offset < 7; offset += 1) days.append(renderPlannedDay(view, addDateKey(weekKey, offset)));
  week.append(days);
  if (weekEntries.length) {
    const additionalCompleted = weekEntries.filter((entry) => entry.is_completed_activity).length;
    const details = document.createElement("p");
    details.className = "planned-week-totals";
    const summary = plannedWeekSummary(weekKey, weekEndKey, weekEntries, weeklyCompliance.get(weekKey), todayKey);
    details.textContent = additionalCompleted ? `${summary} · +${additionalCompleted} zusätzlich` : summary;
    week.append(details);
  }
  return week;
}

let plannedRenderSnapshot = null;

function renderPlanned(trainingCalendar) {
  const root = $("#plannedCalendar");
  const summary = $("#plannedSummary");
  if (!root) return;
  const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
  const currentWeekKey = planWeekStart(todayKey);
  const display = state.data?.calendar_display || {};
  const snapshot = JSON.stringify([trainingCalendar, todayKey, display, state.data?.daily_planning_context, state.data?.planning_compliance]);
  if (snapshot === plannedRenderSnapshot && root.childElementCount) {
    if (state.plannedTodayFocusPending) requestAnimationFrame(() => focusPlannedToday());
    return;
  }
  plannedRenderSnapshot = snapshot;
  const pastWeeks = calendarDisplayValue(display.past_weeks, 1);
  const futureWeeks = calendarDisplayValue(display.future_weeks, 4);
  const firstWeekKey = addDateKey(currentWeekKey, -7 * pastWeeks);
  const nextWeekKey = addDateKey(currentWeekKey, 7);
  const previousWeekOpenState = new Map(
    [...root.querySelectorAll(".planned-week[data-week-key]")].map((week) => [week.dataset.weekKey, week.open]),
  );
  root.replaceChildren();
  const weeklyCompliance = new Map(
    (Array.isArray(state.data?.planning_compliance) ? state.data.planning_compliance : [])
      .filter((item) => item?.week_start)
      .map((item) => [String(item.week_start).slice(0, 10), item]),
  );
  const lastDateKey = addDateKey(firstWeekKey, ((pastWeeks + futureWeeks + 1) * 7) - 1);
  const entries = (Array.isArray(trainingCalendar) ? trainingCalendar : [])
    .filter((item) => item && !item.archived && !item.local_deleted && plannedEventDate(item))
    .filter((item) => plannedEventDate(item) >= firstWeekKey && plannedEventDate(item) <= lastDateKey)
    .sort((left, right) => String(left.start_date_local || left.date || "").localeCompare(String(right.start_date_local || right.date || "")));
  if (summary) summary.textContent = calendarCountLabel(entries, todayKey) || "Keine Einheiten im Zeitraum";
  const planningContextByDate = new Map(
    (Array.isArray(state.data?.daily_planning_context) ? state.data.daily_planning_context : [])
      .filter((item) => item?.date)
      .map((item) => [String(item.date).slice(0, 10), item]),
  );
  const eventsByDate = new Map();
  entries.forEach((entry) => {
    const key = plannedEventDate(entry);
    if (!eventsByDate.has(key)) eventsByDate.set(key, []);
    eventsByDate.get(key).push(entry);
  });

  const view = {
    currentWeekKey,
    eventsByDate,
    firstWeekKey,
    nextWeekKey,
    planningContextByDate,
    previousWeekOpenState,
    todayKey,
    weeklyCompliance,
  };
  for (let weekIndex = 0; weekIndex < pastWeeks + futureWeeks + 1; weekIndex += 1) root.append(renderPlannedWeek(view, weekIndex));
  if (state.plannedTodayFocusPending) requestAnimationFrame(() => focusPlannedToday());
}

function renderLibrary(workouts) {
  const root = $("#library");
  if (!root) return;
  root.replaceChildren();
  appendHistoryPageButton(root, "library");
  const allWorkouts = Array.isArray(workouts) ? workouts : [];
  const visible = allWorkouts.filter((workout) => !workout.archived && !workout.date);
  const librarySummary = $("#librarySummary");
  if (librarySummary) librarySummary.textContent = `${visible.length} Einheit${visible.length === 1 ? "" : "en"}`;
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Noch keine Einheiten in der Bibliothek.";
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
      section.open = false;
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
        const heading = document.createElement("div");
        const cardTitle = document.createElement("h4");
        cardTitle.textContent = workout.name || "Bibliotheks-Einheit";
        const meta = document.createElement("span");
        meta.textContent = [workout.type, workout.moving_time ? formatDuration(workout.moving_time) : null].filter(Boolean).join(" · ");
        heading.append(cardTitle, meta);
        const description = document.createElement("p");
        description.textContent = workout.description || "Kein Workout-Text hinterlegt.";
        card.append(heading, description);
        cards.append(card);
      });
      section.append(cards);
      root.append(section);
    });
}


function garminPerformanceSources(garmin) {
  return [garmin.has_vo2max ? "VO2max" : null, garmin.has_estimated_run_times ? "Laufprognosen" : null, garmin.has_max_hr ? "Max HF" : null, garmin.has_weight ? "Gewicht" : null].filter(Boolean);
}

function garminPaginationDetail(garmin) {
  return Object.entries(garmin.pagination || {})
    .filter(([, value]) => value && (Number(value.windows) > 1 || value.complete === false))
    .map(([name, value]) => `${name}: ${value.records || 0} Datensätze in ${value.windows || 0} Zeitfenstern${value.complete === false ? " · unvollständig" : ""}`)
    .join(" · ");
}

function garminBodyBatteryDetail(garmin) {
  const bodyBattery = garmin.morning_body_battery || {};
  const beforeSleep = Number(bodyBattery.before_sleep?.value);
  const morning = Number(bodyBattery.morning?.value);
  if (bodyBattery.status === "ready" && Number.isFinite(beforeSleep) && Number.isFinite(morning)) {
    return `Body Battery am ${dateLabel(bodyBattery.sleep_date)}: ${beforeSleep} vor dem Schlafen → ${morning} nach dem Aufwachen`;
  }
  return bodyBattery.sleep_date ? `Body Battery am ${dateLabel(bodyBattery.sleep_date)}: nicht verfügbar` : "";
}

function garminDetailText(garmin) {
  let sourceDetail = "Noch kein Garmin-Abruf durchgeführt.";
  if (garmin.last_sync_at) {
    sourceDetail = `Letzter Abruf: ${formatTime(garmin.last_sync_at)} · ${garmin.activities || 0} Aktivitäten · Schlaf/HRV/Readiness ${[garmin.has_sleep, garmin.has_hrv, garmin.has_readiness].filter(Boolean).length}/3`;
  } else if (garmin.source === "fixture") {
    sourceDetail = "Testdatei ist konfiguriert; synchronisiere sie mit dem Button.";
  }
  const performance = garminPerformanceSources(garmin);
  return [sourceDetail, performance.length ? `${performance.join("/")} aus Garmin` : "", garminBodyBatteryDetail(garmin), garminPaginationDetail(garmin)].filter(Boolean).join(" · ");
}

function renderGarminFullResync(fullButton, fullStatus, fullResync, fullRunning) {
  if (fullButton) {
    fullButton.disabled = fullRunning || Boolean(state.data?.garmin_sync?.running || state.localSync.garmin);
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  if (!fullStatus) return;
  fullStatus.classList.toggle("error", Boolean(fullResync.last_error));
  let statusText = "Löscht nur lokale Garmin-Daten; Zugangsdaten und Cloud bleiben unverändert.";
  if (fullRunning && fullResync.status) statusText = fullResync.status;
  else if (fullResync.last_error) statusText = fullResync.last_error;
  else if (fullResync.last_resync_at) statusText = `Letzter vollständiger Resync: ${formatTime(fullResync.last_resync_at)}`;
  fullStatus.textContent = statusText;
}

function renderUnavailableGarmin(garmin, status, detail, button, fullButton) {
  const unavailable = !garmin?.available;
  if (!unavailable && garmin.configured) return false;
  status.textContent = unavailable ? "Garmin nicht verfügbar" : "Garmin nicht eingerichtet";
  detail.textContent = "";
  button.disabled = true;
  if (fullButton) fullButton.disabled = true;
  return true;
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
  if (renderUnavailableGarmin(garmin, status, detail, button, fullButton)) return;
  if (garmin.source === "fixture") status.textContent = "Lokale Garmin-Testdaten aktiv";
  else if (garmin.last_error) status.textContent = "Mit Fehlern synchronisiert";
  else status.textContent = "Optionaler Direktabruf aktiv";
  detail.textContent = garminDetailText(garmin);
  renderGarminFullResync(fullButton, fullStatus, fullResync, fullRunning);
}

function competitionSportLabel(sport) {
  return ({ Cycling: "Radfahren", Ride: "Radfahren", VirtualRide: "Rad indoor", Running: "Laufen", Run: "Laufen", Swim: "Schwimmen", Strength: "Krafttraining" })[sport] || sport || "–";
}

function competitionFact(labelText, value) {
  const item = document.createElement("div");
  const label = document.createElement("span");
  label.textContent = labelText;
  const content = document.createElement("strong");
  content.textContent = value || "–";
  item.append(label, content);
  return item;
}

function competitionCard(competition = {}, index = 0) {
  const card = document.createElement("article");
  card.className = "competition-card";

  const top = document.createElement("div");
  top.className = "competition-card-top";
  const title = document.createElement("strong");
  title.textContent = competition.name || `Wettkampf ${index + 1}`;
  const priority = document.createElement("span");
  priority.className = "competition-priority";
  priority.textContent = `${competition.priority || "B"}-Wettkampf`;
  top.append(title, priority);

  if (competition.sync_state === "local_override") {
    const status = document.createElement("small");
    status.className = "competition-sync-state";
    status.textContent = "Lokal priorisiert · der Coach kann den nächsten Sync ausführen";
    card.append(status);
  }

  const facts = document.createElement("div");
  facts.className = "competition-card-facts";
  facts.append(
    competitionFact("Datum", competition.event_date ? dateLabel(competition.event_date) : ""),
    competitionFact("Sportart", competitionSportLabel(competition.sport)),
    competitionFact("Distanz", distanceLabel(competition.distance)),
    competitionFact("Zielpace / Zielzeit", competition.target)
  );
  const additional = document.createElement("details");
  additional.className = "competition-additional-fields";
  const additionalSummary = document.createElement("summary");
  additionalSummary.textContent = "Weitere Intervals.icu-Felder";
  const additionalGrid = document.createElement("div");
  additionalGrid.className = "competition-card-facts competition-additional-grid";
  additionalGrid.append(
    competitionFact("Startzeit", competition.start_date_local ? formatLocalCompetitionTime(competition.start_date_local) : ""),
    competitionFact("Erwartete Dauer (hh:mm)", formatDuration(competition.moving_time)),
    competitionFact("Streckenprofil", competition.course_profile),
    competitionFact("Beschreibung", competition.description),
    competitionFact("Notizen", competition.notes)
  );
  additional.append(additionalSummary, additionalGrid);
  card.append(top, facts, additional);
  return card;
}

function renderCompetitions(competitions) {
  const root = $("#competitionList");
  const summary = $("#plannedCompetitionsSummary");
  if (summary) {
    const next = competitions.filter((competition) => competition.event_date).sort((a, b) => String(a.event_date).localeCompare(String(b.event_date)))[0];
    if (!competitions.length) summary.textContent = "Noch keine Wettkämpfe";
    else {
      const competitionLabel = competitions.length === 1 ? "Wettkampf" : "Wettkämpfe";
      const nextLabel = next ? ` · nächster ${dateLabel(next.event_date)}` : "";
      summary.textContent = `${competitions.length} ${competitionLabel}${nextLabel}`;
    }
  }
  root.replaceChildren();
  if (!competitions.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Noch keine Zielwettkämpfe gespeichert.";
    root.append(empty);
    return;
  }
  [...competitions]
    .sort((a, b) => String(a.event_date || "9999-12-31").localeCompare(String(b.event_date || "9999-12-31")))
    .forEach((competition, index) => root.append(competitionCard(competition, index)));
}

function formatLocalCompetitionTime(value) {
  const raw = String(value || "");
  const match = /(?:T|\s)(\d{2}:\d{2})(?::\d{2})?/.exec(raw);
  return match ? match[1] : formatTime(value);
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
  if (comparison?.delta == null) return null;
  const delta = Number(comparison.delta);
  if (!Number.isFinite(delta)) return null;
  let sign;
  if (delta > 0) sign = "+";
  else if (delta < 0) sign = "−";
  else sign = "±";
  const precision = comparison.unit === "" || comparison.unit === "bpm" || comparison.unit === "ms" ? 0 : 1;
  const amount = Math.abs(delta).toFixed(precision).replace(".", ",");
  const unit = comparison.unit ? ` ${comparison.unit}` : "";
  let arrow;
  if (comparison.direction === "up") arrow = "↑";
  else if (comparison.direction === "down") arrow = "↓";
  else arrow = "→";
  const comparisonLabel = comparison.label || `${comparison.days}-Tage-Durchschnitt`;
  return { text: `${arrow} ${sign}${amount}${unit}`, className: comparison.color || "neutral", title: `Vergleich zum ${comparisonLabel}` };
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

function metricValueParts(metricData) {
  return {
    value: metricData && typeof metricData === "object" ? metricData.value : metricData,
    unit: metricData && typeof metricData === "object" ? metricData.unit : "",
  };
}

function metricSourceDetails(metricData) {
  const source = document.createElement("small");
  source.textContent = metricData?.source || "Nicht verfügbar";
  const freshnessLabel = { stale: "Veraltet", partial: "Teilweise aktualisiert", unknown: "Aktualität unbekannt" }[metricData?.freshness];
  if (freshnessLabel) source.textContent += ` · ${freshnessLabel}`;
  if (metricData?.observed_at) source.textContent += ` · Messung ${dateLabel(String(metricData.observed_at).slice(0, 10))}`;
  else if (freshnessLabel && metricData?.fetched_at) source.textContent += ` · Stand ${formatTime(metricData.fetched_at)}`;
  if (metricData?.measurement_status === "earlier" && Number.isFinite(metricData.measurement_age_days)) {
    const ageLabel = metricData.measurement_age_days === 1 ? "Tag" : "Tage";
    source.textContent += ` · ${metricData.measurement_age_days} ${ageLabel} alt`;
  } else if (metricData?.measurement_status === "unknown") source.textContent += " · Messdatum unbekannt";
  else if (metricData?.measurement_status === "future") source.textContent += " · Messdatum liegt in der Zukunft";
  source.title = [metricData?.note || metricData?.source || "", metricData?.fetched_at ? `Abgerufen ${formatTime(metricData.fetched_at)}` : ""].filter(Boolean).join(" · ");
  source.className = metricSourceClass(metricData?.source);
  if (metricData?.source === "Garmin Connect") source.className = "metric-garmin";
  return source;
}

function metricComparisonBadge(comparison) {
  const details = comparisonText(comparison);
  if (!details) return null;
  const badge = document.createElement("small");
  badge.className = `metric-comparison ${details.className}`;
  badge.textContent = details.text;
  badge.title = details.title;
  return badge;
}

function metricEditor(item, metric, label, value, editable) {
  if (!editable?.key) return null;
  item.classList.add("metric-editable");
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "metric-edit-button";
  edit.textContent = "✎";
  edit.title = `${label} bearbeiten`;
  edit.setAttribute("aria-label", edit.title);
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
    else void saveInlineMetric(editable.key, input.value, edit);
  });
  return { edit, input };
}

function displayMetric(root, label, metricData, formatter = null, editable = null) {
  const item = document.createElement("div");
  const metric = document.createElement("strong");
  const caption = document.createElement("span");
  const source = metricSourceDetails(metricData);
  const { value, unit } = metricValueParts(metricData);
  if (value == null) metric.textContent = "—";
  else if (formatter) metric.textContent = formatter(value);
  else metric.textContent = `${value}${unit ? " " + unit : ""}`;
  caption.textContent = label;
  for (const className of [metricSourceClass(metricData?.source), metricToneClass(label, value)]) {
    if (className) item.classList.add(className);
  }
  const valueRow = document.createElement("div");
  valueRow.className = "metric-value-row";
  valueRow.append(metric);
  const badge = metricComparisonBadge(metricData?.comparison);
  if (badge) {
    valueRow.append(badge);
  }
  const editor = metricEditor(item, metric, label, value, editable);
  if (editor) {
    item.append(valueRow, editor.input, caption, source, editor.edit);
  } else {
    item.append(valueRow, caption, source);
  }
  root.append(item);
}

async function saveInlineMetric(key, value, button) {
  const profile = { ...state.data?.profile, [key]: String(value || "").trim() };
  button.disabled = true;
  try {
    const saved = await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    if (!Object.keys(profile).every((key) => Object.hasOwn(saved, key) && typeof saved[key] === "string")) {
      throw new Error("Die Profilbestätigung ist unvollständig. Der Entwurf bleibt erhalten.");
    }
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

function renderPerformance(performance, { refreshCharts = true } = {}) {
  if (refreshCharts) {
    void renderTrainingRecords();
    renderPersonalRecovery(performance?.personal_recovery);
    renderAnalysisHistory(performance?.history);
    renderTrainingFocus(performance?.training_focus);
    void loadAnalysisReports();
  }
  const root = $("#performancePredictions");
  root.replaceChildren();
  const values = performance?.metrics || {};
  const weight = values.weight_kg?.value != null ? values.weight_kg : null;
  const predictions = [["5 km (geschätzt)", values.run_5k_seconds, formatDuration],
    ["10 km (geschätzt)", values.run_10k_seconds, formatDuration],
    ["Halbmarathon (geschätzt)", values.run_half_marathon_seconds, formatDuration],
    ["Marathon (geschätzt)", values.run_marathon_seconds, formatDuration]].filter(([, metric]) => metric?.value != null);
  root.hidden = !predictions.length && !weight;
  if (predictions.length || weight) {
    root.append(reportNode("h3", "Laufprognosen"));
    const table = reportNode("table");
    const head = reportNode("thead");
    const header = reportNode("tr");
    for (const label of ["Distanz", "Gesch\u00e4tzte Zeit", "Quelle"]) {
      const cell = reportNode("th", label); cell.scope = "col"; header.append(cell);
    }
    head.append(header); table.append(head);
    const body = reportNode("tbody");
    for (const [label, metric, formatter] of predictions) {
      const row = reportNode("tr");
      row.append(reportNode("td", label), reportNode("td", formatter(metric.value)), reportNode("td", metric.source || "Unbekannt"));
      body.append(row);
    }
    if (weight) {
      const row = reportNode("tr");
      row.append(reportNode("td", "Gewicht"), reportNode("td", `${analysisValue(weight.value, "kg")}`), reportNode("td", weight.source || "Unbekannt"));
      body.append(row);
    }
    table.append(body); root.append(table);
  }
  renderAnalysisSegments(state.route);
}

const CHANGE_HISTORY_LABELS = {
  profile: "Profil",
  workout_library: "Workout-Bibliothek",
  competition: "Wettkampf",
  training_plan: "Trainingsplan",
};

function renderChangeHistory(changes = []) {
  const root = $("#changeHistoryList");
  if (!root) return;
  root.replaceChildren();
  if (!changes.length) {
    root.textContent = "Noch keine lokalen Änderungen aufgezeichnet.";
    return;
  }
  changes.forEach((change) => {
    const item = document.createElement("article");
    item.className = "change-history-item";
    const header = document.createElement("div");
    header.className = "change-history-item-header";
    const title = document.createElement("strong");
    let action = "geändert";
    if (change.action === "create") action = "erstellt";
    else if (change.action === "delete") action = "gelöscht";
    else if (change.action === "undo") action = "zurückgenommen";
    title.textContent = `${CHANGE_HISTORY_LABELS[change.entity_type] || "Lokales Objekt"} ${action}`;
    const time = document.createElement("time");
    time.dateTime = change.created_at || "";
    time.textContent = formatTime(change.created_at);
    header.append(title, time);
    const detail = document.createElement("span");
    const fields = Object.keys(change.diff?.fields || {});
    const fieldLabel = fields.length ? `Felder: ${fields.join(", ")}` : "Keine Felddetails";
    detail.textContent = `${fieldLabel} · Nur lokal · Quelle: ${change.source || "local"}`;
    item.append(header, detail);
    if (change.action !== "undo") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button";
      button.textContent = "Änderung zurücknehmen";
      button.addEventListener("click", () => undoChange(change.id, button));
      item.append(button);
    }
    root.append(item);
  });
}

async function loadChangeHistory() {
  const status = $("#changeHistoryStatus");
  const button = $("#changeHistoryRefreshButton");
  if (button) button.disabled = true;
  if (status) status.textContent = "Änderungshistorie wird geladen…";
  try {
    const result = await api("/api/change-history?limit=100");
    renderChangeHistory(result.changes || []);
    if (status) status.textContent = `${(result.changes || []).length} lokale Änderungen · Aufbewahrung begrenzt`;
  } catch (error) {
    if (status) status.textContent = error.message;
  } finally {
    if (button) button.disabled = false;
  }
}

async function undoChange(changeId, button) {
  if (!await requestConfirmation("Diese Änderung lokal zurücknehmen? Es wird kein Remote-Provider beschrieben. Neuere Änderungen führen zu einem Konflikt.", { title: "Lokale Änderung zurücknehmen?" })) return;
  button.disabled = true;
  try {
    const preview = await api("/api/change-history/undo/preview", { method: "POST", body: JSON.stringify({ change_id: changeId }) });
    if (!await requestConfirmation("Undo-Vorschau bestätigen? Die Mutation bleibt lokal; ein späterer Remote-Sync muss separat geprüft werden.", { title: "Undo-Vorschau bestätigen?" })) return;
    await api("/api/change-history/undo", { method: "POST", body: JSON.stringify(preview.proposed_action.payload) });
    toast("Lokale Änderung zurückgenommen");
    await load();
    await loadChangeHistory();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
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

async function downloadServerLogs() {
  const button = $("#logsDownloadButton");
  button.disabled = true;
  try {
    const url = URL.createObjectURL(await downloadRequest("/api/logs/download", "Server-Logs konnten nicht heruntergeladen werden."));
    const link = document.createElement("a");
    link.href = url;
    link.download = `intervals-coach-server-logs-${todayIso()}.jsonl`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Server-Logs heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function deleteServerLogs() {
  const confirmed = await requestConfirmation("Server-Logs wirklich löschen?", {
    title: "Server-Logs löschen?",
  });
  if (!confirmed) return;
  const button = $("#logsDeleteButton");
  if (button) button.disabled = true;
  try {
    await api("/api/logs/delete", { method: "POST" });
    const output = $("#logsOutput");
    if (output) output.textContent = "Noch keine Log-Einträge vorhanden.";
    toast("Server-Logs gelöscht");
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function render(data) {
  if (AppRouter.baseRoute() === "nutrition") { if (state.route === "nutrition/products") void loadNutritionProducts(); else void loadNutrition(); }
  const firstRender = !state.data;
  state.data = data;
  renderAppVersion(data.app);
  renderCoachOverview(data);
  renderCoachReceipts();
  renderQuickMessageTemplates();
  notifyState(data);
  renderStatus(data);
  renderMessages(data.messages, firstRender);
  renderPlanned(data.training_calendar || data.planned || []);
  renderLibrary(data.library || []);
  renderProfile(data.profile);
  renderCheckins(data.checkins || data.local_feedback?.recent || [], data.profile?.timezone);
  renderGarmin(data.garmin);
  renderAdaptivePlanning(data);
  renderExternalCalendar(data);
  renderPerformance(data.performance);
  renderModel(data.model);
  renderThinkingLevel(data.thinking_level);
  renderDiagnosticCapture(data.diagnostic_capture);
  renderSettings(data);
  updateVoiceButton();
}

function loadStateRequests(areas, query) {
  const requests = [];
  if (areas.has("chat")) requests.push(["chat", api("/api/chat/history?limit=100")]);
  if (areas.has("plan")) requests.push(["plan", api(`/api/plan${query}`)]);
  if (areas.has("weather") && !areas.has("plan")) requests.push(["weather", api(`/api/weather${query}`)]);
  if (areas.has("library")) requests.push(["library", api("/api/library?limit=100")]);
  if (areas.has("performance")) requests.push(["performance", api("/api/performance")]);
  if (areas.has("feedback")) requests.push(["feedback", api("/api/feedback")]);
  if (areas.has("profile")) requests.push(["profile", api("/api/profile")]);
  return Promise.all(requests.map(async ([area, request]) => {
    try { return [area, await request, null]; }
    catch (error) { return [area, null, error]; }
  }));
}

function applyLoadedArea(payload, area, result, error, bootstrap, chatGeneration, chatContentVersion) {
  if (area === "chat" && chatGeneration !== state.chatGeneration) return { applied: false };
  if (error) return { applied: false, error: `${area}: ${error.message}` };
  if (area === "chat") applyChatResult(payload, result, chatContentVersion);
  if (area === "plan") Object.assign(payload, result);
  if (area === "weather") Object.assign(payload, { weather: result });
  if (area === "library") Object.assign(payload, { library: result.workouts || [], library_next_cursor: result.next_cursor });
  if (area === "performance") Object.assign(payload, result);
  if (area === "feedback") Object.assign(payload, result);
  if (area === "profile") Object.assign(payload, { profile: result.profile || bootstrap.profile, competitions: result.competitions || bootstrap.competitions });
  state.loadedAreas.add(area);
  return { applied: true, area };
}

function mergeLoadedResults(payload, results, bootstrap, chatGeneration, chatContentVersion) {
  const failures = [];
  const appliedAreas = [];
  results.forEach(([area, result, error]) => {
    const outcome = applyLoadedArea(payload, area, result, error, bootstrap, chatGeneration, chatContentVersion);
    if (outcome.error) failures.push(outcome.error);
    if (outcome.applied) appliedAreas.push(outcome.area);
  });
  return { failures, appliedAreas };
}

function applyLoadedStateVersions(payload, appliedAreas, bootstrap, chatGeneration) {
  payload.state_versions = { ...state.data?.state_versions };
  for (const area of appliedAreas) {
    if (area === "chat" && chatGeneration !== state.chatGeneration) continue;
    const versionKeys = { feedback: ["checkins", "activity_feedback"], performance: ["performance", "garmin"] }[area] || [area];
    for (const key of versionKeys) {
      if (bootstrap.state_versions?.[key] !== undefined) payload.state_versions[key] = bootstrap.state_versions[key];
    }
  }
}

async function loadState(path = "/api/bootstrap", requestedAreas = null) {
  const requestSequence = ++state.loadSequence;
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  const chatContentVersion = state.chatContentVersion;
  const initialLoad = $("#appShell").classList.contains("is-loading");
  try {
    const localOnly = path.includes("local=1");
    const query = localOnly ? "?local=1" : "";
    const bootstrap = await api(path);
    if (sessionGeneration !== state.sessionGeneration) return;
    const existing = state.data || {};
    const payload = { ...existing, ...bootstrap };
    ["messages", "messages_next_cursor", "library", "library_next_cursor", "plans", "planned", "training_calendar", "planning_view", "planning_compliance", "weather", "parallel_cycling", "daily_planning_context", "planning", "performance", "garmin", "checkins", "local_feedback", "activity_feedback"].forEach((key) => {
      if (existing[key] !== undefined) payload[key] = existing[key];
    });
    const areas = new Set(requestedAreas || ["chat", "plan", "library", "performance", "feedback", "profile"]);
    const domainData = loadStateRequests(areas, query);
    if (initialLoad && requestSequence === state.loadSequence) {
      render(payload);
      finishAppShellLoading();
    }
    const results = await domainData;
    if (sessionGeneration !== state.sessionGeneration || requestSequence !== state.loadSequence) return;
    // Incorporate changes that arrived while these requests were in flight.
    payload.messages = state.data?.messages || [];
    const { failures, appliedAreas } = mergeLoadedResults(payload, results, bootstrap, chatGeneration, chatContentVersion);
    applyLoadedStateVersions(payload, appliedAreas, bootstrap, chatGeneration);
    if (requestSequence === state.loadSequence) render(payload);
    if (failures.length) throw new Error(failures.join("; "));
  } catch (error) {
    if (sessionGeneration !== state.sessionGeneration || /Authentication/.test(error.message)) return;
    const statusCard = $("#statusCard");
    statusCard.hidden = false;
    statusCard.classList.add("warning");
    $("#statusTitle").textContent = "Trainingsdaten konnten nicht geladen werden";
    $("#statusDetail").textContent = error.message;
  } finally {
    if (sessionGeneration === state.sessionGeneration && $("#appShell").classList.contains("is-loading")) finishAppShellLoading();
  }
}

function load(path = "/api/bootstrap", requestedAreas = null) {
  const areas = state.pendingLoads.get(path) || new Set();
  (requestedAreas || currentPlanLoadAreas()).forEach((area) => areas.add(area));
  state.pendingLoads.set(path, areas);
  if (state.loadPromise) return state.loadPromise;
  const generation = state.sessionGeneration;
  const promise = (async () => {
    while (state.pendingLoads.size && generation === state.sessionGeneration) {
      const [nextPath, nextAreas] = state.pendingLoads.entries().next().value;
      state.pendingLoads.delete(nextPath);
      await loadState(nextPath, [...nextAreas]);
    }
  })();
  const tracked = promise.finally(() => {
    if (state.loadPromise === tracked) state.loadPromise = null;
  });
  state.loadPromise = tracked;
  return tracked;
}

async function syncNow(event) {
  const button = event?.currentTarget || $("#activitiesSyncButton");
  const compactButton = button.id === "systemIntervalsSyncButton";
  const defaultCaption = compactButton ? "Synchronisieren" : "Aktivitäten aktualisieren";
  const configuredDays = $("#intervalsSyncDays")?.value || state.data?.sync_settings?.intervals_days || 84;
  state.localSync.intervals = true;
  button.disabled = true; button.classList.add("busy"); button.textContent = compactButton ? "Synchronisierung läuft…" : "Aktivitäten werden aktualisiert…";
  try {
    const result = await api("/api/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    if (!result.id) throw new Error("Die Jobbestätigung fehlt.");
    const completed = await waitForSyncJob(result.id);
    if (completed.status !== "completed") throw new Error(completed.error_detail || "Synchronisierung nicht vollständig abgeschlossen.");
    toast("Aktualisierung abgeschlossen");
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.intervals = false; button.disabled = false; button.classList.remove("busy"); button.textContent = defaultCaption; }
}

async function syncGarmin() {
  const button = $("#garminSyncButton");
  if (!button) return;
  state.localSync.garmin = true;
  button.disabled = true;
  button.textContent = "Garmin wird synchronisiert…";
  try {
    const configuredDays = $("#garminSyncDays")?.value || state.data?.sync_settings?.garmin_days || 84;
    const result = await api("/api/garmin/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    const completed = await waitForSyncJob(result.id);
    if (completed.status === "failed") throw new Error(globalThis.AppApi.messageForReason(completed.reason, "Garmin-Synchronisierung fehlgeschlagen."));
    toast(`Garmin ${completed.status === "partial" ? "teilweise " : ""}synchronisiert`);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.garmin = false; button.disabled = false; button.textContent = "Garmin synchronisieren"; }
}

async function syncExternalCalendar() {
  const button = $("#externalCalendarSyncButton");
  if (!button) return;
  state.localSync.externalCalendar = true;
  button.disabled = true;
  button.textContent = "Synchronisierung läuft…";
  try {
    const result = await api("/api/external-calendar/sync", { method: "POST", body: "{}" });
    const completed = await waitForSyncJob(result.id);
    if (completed.status === "failed") throw new Error(globalThis.AppApi.messageForReason(completed.reason, "Kalender-Synchronisierung fehlgeschlagen."));
    toast(`Kalender ${completed.status === "partial" ? "teilweise " : ""}synchronisiert`);
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
    const completed = await waitForSyncJob(result.id);
    if (completed.status === "failed") throw new Error(globalThis.AppApi.messageForReason(completed.reason, "Wetter-Synchronisierung fehlgeschlagen."));
    toast(completed.status === "partial" ? "Open-Meteo teilweise aktualisiert" : "Open-Meteo-Wetter aktualisiert");
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
  if (!await requestConfirmation(`Alle lokal gespeicherten ${providerLabel}-Daten löschen und vollständig neu laden? Die Daten in ${providerLabel} bleiben unverändert.`, { title: `${providerLabel}-Daten vollständig neu laden?` })) return;
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
  }
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
  const form = event.currentTarget;
  const generation = state.sessionGeneration;
  const submittedForm = JSON.stringify([...new FormData(form)]);
  const formData = new FormData(form);
  const profile = {
    ...state.data?.profile,
    ...Object.fromEntries(formData),
    sports: formData.getAll("sports").filter((value) => typeof value === "string").map((value) => value.trim()).filter(Boolean).join(", "),
  };
  try {
    const saved = await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    if (!Object.keys(profile).every((key) => Object.hasOwn(saved, key) && typeof saved[key] === "string")) {
      throw new Error("Die Profilbestätigung ist unvollständig. Der Entwurf bleibt erhalten.");
    }
    if (generation !== state.sessionGeneration) return;
    state.profileDirty = JSON.stringify([...new FormData(form)]) !== submittedForm;
    setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
    invalidateContextPreview();
    toast("Profil gespeichert und für den Coach aktiviert");
    // Do not keep the successful save action in its loading state while the
    // follow-up refresh loads the rest of the application state.
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = buttonLabel;
    }
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

function registerServiceWorker() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

async function saveCheckin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  values.tag_answers = {};
  for (const tag of ["travel", "late_meal", "high_stress"]) {
    if (values[`tag_${tag}`] !== "") values.tag_answers[tag] = values[`tag_${tag}`] === "true";
    delete values[`tag_${tag}`];
  }
  for (const field of ["soreness", "stress", "motivation", "session_rpe", "available_minutes"]) {
    values[field] = values[field] === "" ? null : Number(values[field]);
  }
  const button = form.querySelector("button[type=submit]");
  const errorNode = $("#checkinError");
  if (errorNode) errorNode.textContent = "";
  if (button) { button.disabled = true; button.textContent = "Check-in wird gespeichert…"; }
  try {
    const result = await api("/api/feedback", { method: "POST", body: JSON.stringify(values) });
    if (result.checkin?.checkin_date !== values.checkin_date) throw new Error("Die Check-in-Bestätigung fehlt. Der Entwurf bleibt erhalten.");
    state.checkinDirty = false;
    setDirtyIndicator("checkinDirtyIndicator", false);
    state.checkinSelectedDate = result.checkin?.checkin_date || values.checkin_date;
    toast("Tages-Check-in gespeichert");
    $("#checkinDialog")?.close();
    await load();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
  }
  finally {
    if (button) { button.disabled = false; button.textContent = "Tages-Check-in speichern"; }
  }
}

async function downloadDatabaseBackup() {
  const button = $("#backupDownloadButton");
  if (button) button.disabled = true;
  try {
    const blob = await downloadRequest(
      "/api/privacy/backup",
      "Datenbank-Backup konnte nicht erstellt werden.",
      130_000,
    );
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
  if (!file || !await requestConfirmation("Das aktuelle Datenbank-Backup wird vorher gesichert und durch die ausgewählte Datei ersetzt. Fortfahren?", { title: "Datenbank-Backup wiederherstellen?" })) return;
  const button = $("#backupRestoreButton");
  button.disabled = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 130_000);
  try {
    const generation = state.sessionGeneration;
    await globalThis.AppApi.request("/api/privacy/restore", {
      method: "POST", cache: "no-store", signal: controller.signal, timeoutMs: 130_000,
      headers: { "Content-Type": "application/octet-stream" }, body: file,
    }, () => { if (generation === state.sessionGeneration) showLogin(); });
    toast("Backup wiederhergestellt. Bitte erneut anmelden.");
    showLogin();
  } catch (error) {
    toast(error?.name === "AbortError"
      ? "Die Bestätigung der Wiederherstellung fehlt. Der Server kann den Vorgang noch abschließen; bitte vor einem erneuten Versuch den Status prüfen."
      : error.message, true);
  } finally {
    clearTimeout(timeout);
    button.disabled = false;
  }
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
    renderConnectivityStatus(true);
    const blob = await downloadRequest("/api/diagnostics", "Diagnose konnte nicht heruntergeladen werden.");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `intervals-coach-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Diagnose heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Diagnose herunterladen"; }
}

async function deleteDiagnostics() {
  const confirmed = await requestConfirmation("Diagnosedaten wirklich löschen?", {
    title: "Diagnose löschen?",
  });
  if (!confirmed) return;
  const button = $("#diagnosticsDeleteButton");
  if (button) button.disabled = true;
  try {
    await api("/api/diagnostics/delete", { method: "POST" });
    if (state.data?.diagnostic_capture) {
      state.data.diagnostic_capture.entries = 0;
    }
    renderDiagnosticCapture(state.data?.diagnostic_capture || { entries: 0 });
    toast("Diagnose gelöscht");
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

function renderDiagnosticCapture(capture = {}) {
  const status = $("#diagnosticCaptureStatus");
  if (status) status.textContent = `Erweiterte technische Diagnose ist immer aktiv · ${Number(capture.entries || 0)} technische Einträge gespeichert.`;
}

async function downloadPrivacyExport() {
  try {
    const blob = await downloadRequest(
      "/api/privacy/export",
      "Privacy-Export konnte nicht erstellt werden.",
      130_000,
    );
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
    const confirmation = await requestConfirmation(scope, {
      title: "Lokale Daten endgültig löschen?",
      inputLabel: "Bestätigungstext",
      expectedText: preview.confirmation_text,
    });
    if (!confirmation) return;
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
  if (!await confirmDiscardChanges()) return;
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch { }
  showLogin();
}

const confirmationDialog = $("#confirmationDialog");
const confirmationForm = $("#confirmationDialogForm");
const confirmationInput = $("#confirmationDialogInput");
confirmationForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  const expectedText = confirmationDialog?.dataset.expectedText || "";
  if (expectedText && confirmationInput?.value !== expectedText) {
    confirmationInput?.setCustomValidity("Bestätigungstext stimmt nicht überein.");
    confirmationInput?.reportValidity();
    confirmationInput?.focus();
    return;
  }
  confirmationInput?.setCustomValidity("");
  settleConfirmation(expectedText ? confirmationInput.value : true);
  confirmationDialog?.close();
});
$("#confirmationDialogCancel")?.addEventListener("click", () => {
  settleConfirmation(false);
  confirmationDialog?.close();
});
confirmationDialog?.addEventListener("close", () => settleConfirmation(false));

document.querySelectorAll(".nav-item").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  const linkedRoute = String(link.getAttribute("href") || "").replace(/^#/, "").trim();
  void AppRouter.navigate(linkedRoute || link.dataset.route, { historyMode: "push" });
}));
document.querySelectorAll("[data-plan-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  void AppRouter.navigate(`plan/${link.dataset.planSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("[data-analysis-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  void AppRouter.navigate(`analysis/${link.dataset.analysisSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("[data-more-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  void AppRouter.navigate(`more/${link.dataset.moreSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("close", () => restoreDialogFocus(dialog)));

$("#loginForm").addEventListener("submit", login);
setupCoachEvents();
$("#appearanceSelect").addEventListener("change", (event) => {
  const appearance = applyAppearance(event.currentTarget.value);
  try { localStorage.setItem(APPEARANCE_KEY, appearance); } catch { }
});
$("#systemIntervalsSyncButton").addEventListener("click", syncNow);
$("#systemIntervalsFullResyncButton").addEventListener("click", () => fullResync("intervals"));
$("#garminSyncButton").addEventListener("click", syncGarmin);
$("#externalCalendarSyncButton").addEventListener("click", syncExternalCalendar);
$("#weatherSyncButton").addEventListener("click", syncWeather);
$("#garminFullResyncButton").addEventListener("click", () => fullResync("garmin"));
$("#profileForm").addEventListener("submit", saveProfile);
$("#checkinForm").addEventListener("submit", saveCheckin);
$("#checkinCloseButton").addEventListener("click", () => $("#checkinDialog")?.close());
$("#profileForm").addEventListener("input", () => { state.profileDirty = true; setDirtyIndicator("profileDirtyIndicator", true); });
$("#checkinForm").addEventListener("input", () => { state.checkinDirty = true; setDirtyIndicator("checkinDirtyIndicator", true); });
$("#modelSelect").addEventListener("change", saveModel);
$("#thinkingLevelSelect").addEventListener("change", saveThinkingLevel);
$("#calendarDisplayForm").addEventListener("submit", saveCalendarDisplaySettings);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#diagnosticsDeleteButton")?.addEventListener("click", deleteDiagnostics);
$("#logsRefreshButton").addEventListener("click", loadLogs);
$("#logsDownloadButton").addEventListener("click", downloadServerLogs);
$("#logsDeleteButton")?.addEventListener("click", deleteServerLogs);
$("#privacyExportButton").addEventListener("click", downloadPrivacyExport);
$("#privacyDeleteButton").addEventListener("click", deletePrivacyData);
$("#changeHistoryRefreshButton").addEventListener("click", loadChangeHistory);
$("#notificationEnableButton").addEventListener("click", enableNotifications);
$("#backupDownloadButton").addEventListener("click", downloadDatabaseBackup);
$("#backupRestoreButton").addEventListener("click", restoreDatabaseBackup);
$("#logoutButton").addEventListener("click", logout);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") savePwaActivity();
  else {
    checkPwaReturn();
    scheduleChatStatusPoll(0);
    scheduleMobileViewportLayout();
  }
  handleSyncVisibility();
});
document.addEventListener("pointerdown", handlePwaInteraction, { passive: true });
document.addEventListener("focusin", scheduleMobileViewportLayout);
document.addEventListener("focusout", scheduleMobileViewportLayout);
globalThis.addEventListener("resize", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("orientationchange", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("pageshow", () => {
  connectStateEvents();
  scheduleMobileViewportLayout();
  if (state.chatInitialScrollPending && AppRouter.baseRoute() === "coach") scrollChatToLatest();
}, { passive: true });
globalThis.visualViewport?.addEventListener("resize", scheduleMobileViewportLayout, { passive: true });
globalThis.visualViewport?.addEventListener("scroll", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("pagehide", savePwaActivity);
globalThis.addEventListener("pagehide", disconnectStateEvents);
globalThis.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedChanges()) return;
  event.preventDefault();
});
registerServiceWorker();
setupConnectivityStatus();
renderNotificationStatus();
setupSyncStatusMonitoring();
scheduleMobileViewportLayout();
AppRouter.configure({
  hasUnsavedChanges,
  confirmDiscardChanges,
  discardUnsavedChanges,
  renderActiveRoute,
  renderStatus,
  restoreRouteScroll,
  ensureRouteData,
});
void AppRouter.syncFromHash();
void bootstrapAuth();
