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
const MAX_QUEUED_ATTACHMENT_BYTES = 16_000_000;
let mobileViewportFrame = null;
const mobileViewportBaselines = { portrait: 0, landscape: 0 };
let mobileViewportInputWasFocused = false;

if ("scrollRestoration" in globalThis.history) globalThis.history.scrollRestoration = "manual";

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

function renderAnalysisSegments(segment = state.analysisSegment) {
  const selected = ["history", "performance"].includes(segment) ? segment : "performance";
  state.analysisSegment = selected;
  document.querySelectorAll("[data-analysis-segment-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.analysisSegmentPanel !== selected;
  });
  document.querySelectorAll("[data-analysis-segment]").forEach((link) => {
    const active = link.dataset.analysisSegment === selected;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function renderPlanSegments(segment = state.planSegment) {
  const selected = ["overview", "library"].includes(segment) ? segment : "overview";
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
  const areas = new Set(["chat", "activities", "performance", "feedback", "profile", "weather"]);
  const route = baseRoute();
  if (route === "plan") {
    areas.add("plan");
    areas.add("library");
  }
  return [...areas];
}

function ensureRouteData(route = state.route) {
  if (!state.data) return;
  const requested = [];
  const panelRoute = baseRoute(route);
  if (panelRoute === "plan" && !state.loadedAreas.has("plan")) requested.push("plan");
  if (panelRoute === "plan" && !state.loadedAreas.has("library")) requested.push("library");
  if (requested.length) load("/api/bootstrap?local=1", requested);
}

function activateNavigationPanel(panelRoute, navigationRoute) {
  document.querySelectorAll(".nav-item, .panel").forEach((node) => node.classList.remove("active"));
  const navigation = document.querySelector(`.nav-item[data-route="${navigationRoute}"]`);
  const panel = document.querySelector(`#${NAV_ROUTES[panelRoute]}`);
  if (!navigation || !panel) return null;
  document.querySelectorAll(".nav-item").forEach((item) => item.removeAttribute("aria-current"));
  document.querySelectorAll(`.nav-item[data-route="${navigationRoute}"]`).forEach((item) => {
    item.classList.add("active");
    item.setAttribute("aria-current", "page");
  });
  panel.classList.add("active");
  return panel;
}

function updateNavigationHistory(panelRoute, historyMode) {
  const targetHash = `#${panelRoute}`;
  if (globalThis.location.hash === targetHash) return;
  if (historyMode === "push") globalThis.history.pushState({ route: panelRoute }, "", targetHash);
  else if (historyMode === "replace") globalThis.history.replaceState({ route: panelRoute }, "", targetHash);
}

function renderActiveRoute(mainRoute, panelRoute) {
  if (mainRoute === "more") renderMoreSegments(moreSegmentFromRoute(panelRoute));
  if (mainRoute === "plan") renderPlanSegments(planSegmentFromRoute(panelRoute));
  if (mainRoute === "analysis") renderAnalysisSegments(analysisSegmentFromRoute(panelRoute));
  if (state.data && mainRoute === "more") {
    loadContextPreview();
    loadLogs();
    loadChangeHistory();
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

async function applyNavigationRoute(route, { historyMode = "none", focus = true } = {}) {
  const panelRoute = NAV_ROUTES[route] ? route : DEFAULT_NAV_ROUTE;
  const mainRoute = baseRoute(panelRoute);
  const shouldFocusPlannedToday = mainRoute === "plan" && planSegmentFromRoute(panelRoute) === "overview";
  const navigationRoute = NAV_LINK_ROUTES[mainRoute] || mainRoute;
  const currentPanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  if (currentPanel !== NAV_ROUTES[panelRoute] && hasUnsavedChanges({ includeChatDraft: false })) {
    if (!(await confirmDiscardChanges())) return false;
    discardUnsavedChanges();
  }
  const returningToChat = currentPanel !== "chatPanel" && mainRoute === "coach";
  if (state.data && !state.chatInitialScrollPending && historyMode === "push" && currentPanel === "chatPanel" && mainRoute !== "coach") {
    state.chatScrollY = globalThis.scrollY;
  }
  if (currentPanel === "chatPanel" && mainRoute !== "coach" && (state.chatRequest || state.chatServerOperationId)) state.chatResponseScrollPending = true;
  const panel = activateNavigationPanel(panelRoute, navigationRoute);
  if (!panel) return false;
  state.plannedTodayFocusPending = shouldFocusPlannedToday;
  state.route = panelRoute;
  renderActiveRoute(mainRoute, panelRoute);
  updateNavigationHistory(panelRoute, historyMode);
  if (state.data) renderStatus(state.data);
  updateHeaderAction();
  restoreRouteScroll(mainRoute, returningToChat, shouldFocusPlannedToday);
  ensureRouteData(panelRoute);
  if (focus && !$("#appShell")?.hidden) {
    panel.setAttribute("tabindex", "-1");
    panel.focus({ preventScroll: true });
  }
  return true;
}
async function syncNavigationRoute() {
  const route = routeFromHash();
  const applied = await applyNavigationRoute(route, {
    historyMode: !hashContainsKnownRoute() ? "replace" : "none",
  });
  if (!applied && state.route) globalThis.history.replaceState({ route: state.route }, "", `#${state.route}`);
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
  state.planSegment = "overview";
  state.analysisSegment = "performance";
  state.profileDirty = false;
  state.checkinDirty = false;
  state.chatAttachments = [];
  renderChatAttachments();
  state.chatDraftDirty = false;
  state.activityFromDate = "";
  state.activityToDate = "";
  state.activityVisibleCount = 250;
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
  applyNavigationRoute(routeFromHash(), { historyMode: hashContainsKnownRoute() ? "none" : "replace" });
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
      return payload.area === "performance" ? ["performance"] : ["activities", "performance"];
    })(),
    job: [],
    sync: ["activities", "performance", "plan", "library"],
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
  } catch (_) {
    // Intentionally ignored: privacy settings can deny storage; fail open to keep sync available.
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
    activities: ["activities"],
    performance: ["performance", "plan"],
    garmin: ["performance", "plan"],
    chat: ["chat"],
    library: ["library", "plan"],
    checkins: ["feedback", "plan"],
    activity_feedback: ["feedback", "activities"],
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
  renderActivities(state.data.activities || []);
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

function setVoiceButtonIcon(icon) {
  const button = $("#voiceButton");
  if (button) button.innerHTML = `<svg class="nav-icon" aria-hidden="true"><use href="#icon-${icon}"></use></svg>`;
}

function updateVoiceButton() {
  const button = $("#voiceButton");
  if (!button) return;
  const recording = voiceIsRecording();
  const transcribing = state.voiceTranscribing;
  const chatReady = Boolean(state.data && Array.isArray(state.data.messages));
  button.disabled = !chatReady || state.busy || transcribing;
  button.classList.toggle("recording", recording);
  button.classList.toggle("transcribing", transcribing);
  button.setAttribute("aria-pressed", recording ? "true" : "false");
  if (recording) {
    setVoiceButtonIcon("stop");
    button.setAttribute("aria-label", "Spracheingabe beenden");
    button.title = "Spracheingabe beenden";
  } else if (transcribing) {
    button.innerHTML = "<span class=\"button-spinner\" aria-hidden=\"true\"></span>";
    button.setAttribute("aria-label", "Audio wird transkribiert");
    button.title = "Audio wird transkribiert";
  } else {
    setVoiceButtonIcon("microphone");
    button.setAttribute("aria-label", "Spracheingabe starten");
    button.title = "Spracheingabe starten";
  }
  updateChatControls();
}

function chatControlState(input) {
  const chatReady = Boolean(state.data && Array.isArray(state.data.messages));
  const hasDraft = Boolean((state.chatAttachments || []).length || input?.value.trim());
  const inputAvailable = !voiceIsRecording() && !state.voiceTranscribing;
  const resuming = Boolean(state.chatRequest?.phase === "recovering" || (state.chatServerOperationId && !state.chatStream));
  return { chatReady, hasDraft, inputAvailable, resuming, reconciling: state.chatRequest?.phase === "reconciling" };
}

function chatSendLabel(controls) {
  if (controls.reconciling) return "Antwort wird geladen…";
  if (controls.resuming) return "Coach antwortet…";
  return state.busy ? "Einreihen" : "Senden";
}

function updateChatSendButton(button, controls) {
  if (!button) return;
  button.disabled = state.chatAttachmentsLoading || !controls.chatReady || !controls.hasDraft || !controls.inputAvailable || controls.resuming || controls.reconciling;
  button.textContent = chatSendLabel(controls);
}

function updateChatSteerButton(button, controls) {
  if (!button) return;
  button.hidden = !state.busy || controls.resuming || controls.reconciling;
  button.disabled = !controls.hasDraft || !controls.inputAvailable || controls.resuming || controls.reconciling;
}

function updateChatCancelButton(button, controls) {
  if (!button) return;
  button.hidden = !state.busy || controls.reconciling;
  const requested = Boolean(state.chatStream?.cancelRequested || state.chatRequest?.cancelRequested);
  button.disabled = (!state.chatStream && !state.chatServerOperationId) || requested;
  button.textContent = requested ? "Wird abgebrochen…" : "Abbrechen";
}

function updateChatControls() {
  const input = $("#messageInput");
  const controls = chatControlState(input);
  const form = $("#chatForm");
  if (form) {
    form.classList.toggle("is-busy", state.busy);
    form.classList.toggle("is-recovering", controls.resuming);
    form.classList.toggle("is-reconciling", controls.reconciling);
  }
  if (input) {
    input.disabled = !controls.chatReady;
    input.placeholder = controls.chatReady ? "Frage deinen Coach…" : "Coach-Chat wird geladen…";
  }
  updateChatSendButton($("#sendButton"), controls);
  updateChatSteerButton($("#steerButton"), controls);
  updateChatCancelButton($("#cancelChatButton"), controls);
  const progress = $("#chatOperationStatus");
  if (progress) progress.hidden = !state.busy || controls.reconciling;
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
  const generation = state.sessionGeneration;
  state.voiceTranscribing = true;
  setVoiceStatus("Aufnahme wird transkribiert …");
  updateVoiceButton();
  try {
    const result = await apiAudio("/api/transcribe", blob);
    if (generation !== state.sessionGeneration) return;
    const transcript = String(result.transcript || "").trim();
    if (!transcript) throw new Error("OpenAI hat kein Transkript zurückgegeben.");
    const input = $("#messageInput");
    const current = input.value.trim();
    input.value = current ? `${current}\n${transcript}` : transcript;
    input.dispatchEvent(new Event("input"));
    updateVoiceButton();
    if ($("#chatPanel")?.classList.contains("active") && document.visibilityState === "visible") input.focus({ preventScroll: true });
    setVoiceStatus("Transkript eingefügt. Bitte prüfen und anschließend senden.");
  } catch (error) {
    if (generation !== state.sessionGeneration) return;
    setVoiceStatus(error.message, true);
    toast(error.message, true);
  } finally {
    if (generation === state.sessionGeneration) {
      state.voiceTranscribing = false;
      updateVoiceButton();
    }
  }
}

async function toggleVoiceInput() {
  if (state.busy || state.voiceTranscribing || state.voiceAcquiring) return;
  if (voiceIsRecording()) {
    stopVoiceRecording();
    return;
  }
  if (!globalThis.isSecureContext || !navigator.mediaDevices?.getUserMedia || !globalThis.MediaRecorder) {
    const message = "Spracheingabe benötigt eine HTTPS-Verbindung und einen unterstützten Browser.";
    setVoiceStatus(message, true);
    toast(message, true);
    return;
  }
  const generation = state.sessionGeneration;
  state.voiceAcquiring = true;
  setVoiceStatus("Mikrofon wird aktiviert …");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (generation !== state.sessionGeneration) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    state.voiceAcquiring = false;
    state.voiceStream = stream;
    const mimeType = typeof MediaRecorder.isTypeSupported === "function"
      ? VOICE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || ""
      : "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    state.voiceRecorder = recorder;
    state.voiceStartedAt = Date.now();
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) chunks.push(event.data);
    });
    recorder.addEventListener("error", () => {
      if (generation !== state.sessionGeneration) return;
      stopVoiceCapture(recorder);
      setVoiceStatus("Die Audioaufnahme ist fehlgeschlagen.", true);
    });
    recorder.addEventListener("stop", () => {
      if (generation !== state.sessionGeneration) return;
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
    if (generation !== state.sessionGeneration) return;
    state.voiceAcquiring = false;
    stopVoiceCapture();
    const message = error.name === "NotAllowedError"
      ? "Der Mikrofonzugriff wurde nicht erlaubt."
      : "Das Mikrofon konnte nicht aktiviert werden.";
    setVoiceStatus(message, true);
    toast(message, true);
  }
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
  if (next && next.days_until >= 0 && next.days_until <= 3) showPwaNotification("Wettkampf steht bevor", { body: `${next.name} ist in ${next.days_until} Tag(en).`, tag: `competition:${next.id}` }, `competition:${next.id}:${next.event_date}`);
  const error = data.sync?.last_error || data.garmin_sync?.status?.includes("Fehler") && data.garmin_sync.status;
  if (error) showPwaNotification("Intervals Coach benötigt Aufmerksamkeit", { body: String(error), tag: "sync-error" }, `error:${error}`);
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

function renderCoachOverview(data) {
  const actions = data.coach_quick_actions || {};
  const quickMorning = $("#quickMorningCheckinButton");
  if (quickMorning) quickMorning.hidden = actions.morning_checkin === false;
}

function renderCoachReceipts() {
  const root = $("#coachReceipts");
  if (!root) return;
  root.replaceChildren();
  (state.coachReceipts || []).slice(-3).reverse().forEach((receipt) => root.append(createActionReceipt(receipt)));
}

function addCoachReceipt(receipt) {
  state.coachReceipts = [...(state.coachReceipts || []), { ...receipt, createdAt: Date.now() }].slice(-3);
  renderCoachReceipts();
}

const HIDDEN_CHAT_RECEIPT_TOOLS = new Set([
  "get_sync_job", "refresh_current_performance", "start_intervals_plan_sync",
  "start_provider_refresh", "sync_competitions",
]);
const COACH_RECEIPT_LABELS = {
  update_profile: "Profil aktualisiert", apply_training_patch: "Geplante Einheiten angepasst",
  stage_training_plan: "Planvorlage vorbereitet", commit_training_plan: "Trainingsplan gespeichert",
  replace_training_plan: "Trainingsplan vollständig ersetzt",
  apply_training_changes: "Lokale Planung geändert", manage_training_templates: "Trainingsvorlagen bearbeitet",
  apply_workout_library_plan: "Einheiten lokal geplant", save_checkin: "Tages-Check-in gespeichert",
  save_activity_feedback: "Aktivitätsfeedback gespeichert", delete_activity_feedback: "Aktivitätsfeedback gelöscht",
  save_competition: "Wettkampf gespeichert", delete_competition: "Wettkampf gelöscht",
  update_training_plan: "Trainingsplan geändert", undo_training_change: "Rücknahme zur Prüfung bereit",
  preview_adaptive_replan: "Plananpassung zur Prüfung bereit", apply_adaptive_replan: "Plananpassung gespeichert",
  start_provider_refresh: "Datenabruf beauftragt", refresh_current_performance: "Leistungsdatenabruf beauftragt",
  sync_competitions: "Wettkampfsynchronisierung beauftragt",
  resolve_training_sync_conflict: "Synchronisierungsentscheidung gespeichert",
  start_intervals_plan_sync: "Intervals-Synchronisierung beauftragt",
};
const SYNC_JOB_RECEIPT_LABELS = {
  queued: "Synchronisierung beauftragt", running: "Synchronisierung läuft",
  completed: "Synchronisierung abgeschlossen", partial: "Synchronisierung teilweise abgeschlossen",
  failed: "Synchronisierung fehlgeschlagen",
};

function receiptIsVisible(entry, planCommitRequested, finalCommit) {
  if (entry.resolved) return false;
  const result = entry.result || {};
  const failedSync = entry.tool === "start_intervals_plan_sync" && result.ok === false;
  const failedSyncJob = entry.tool === "get_sync_job" && result.job?.status === "failed";
  if (HIDDEN_CHAT_RECEIPT_TOOLS.has(entry.tool) && !failedSync && !failedSyncJob) return false;
  if (planCommitRequested && entry.tool === "stage_training_plan") return false;
  return entry.tool !== "commit_training_plan" || entry === finalCommit;
}

function syncJobReceipt(job) {
  const title = SYNC_JOB_RECEIPT_LABELS[job.status] || "Synchronisierungsstatus unklar";
  let status = "pending";
  if (["partial", "failed"].includes(job.status)) status = "error";
  else if (job.status === "completed") status = "success";
  return { title, message: job.error_detail || title, status };
}

function commandReceiptTitle(entry, result, failed, queued) {
  if (failed) return "Coach-Aktion fehlgeschlagen";
  if (entry.tool === "start_provider_refresh" && result.status === "completed") return "Daten aktualisiert";
  if (COACH_RECEIPT_LABELS[entry.tool]) return COACH_RECEIPT_LABELS[entry.tool];
  return queued ? "Synchronisierung beauftragt" : "Informationen geladen";
}

function commandReceiptMessage(result, failed, queued) {
  if (failed) return result.error || "Die Aktion konnte nicht ausgeführt werden.";
  return queued ? "Der Auftrag wird im Hintergrund bearbeitet; das Ergebnis steht noch aus." : "Der lokale Beleg liegt vor.";
}

function commandReceiptStatus(failed, queued) {
  if (failed) return "error";
  return queued ? "pending" : "success";
}

function commandReceipt(entry) {
  const result = entry.result || {};
  if (entry.tool === "get_sync_job" && result.job) return syncJobReceipt(result.job);
  const failed = result.ok === false;
  const queued = Boolean(result.sync_job_id || result.job_id || result.job?.id || result.status === "queued");
  const details = [];
  if (Array.isArray(result.library_entry_ids) && result.library_entry_ids.length) details.push(`${result.library_entry_ids.length} lokale Einheit(en) gespeichert`);
  if (result.remote_untouched) details.push("Providerdaten unverändert");
  return {
    title: commandReceiptTitle(entry, result, failed, queued),
    message: commandReceiptMessage(result, failed, queued),
    status: commandReceiptStatus(failed, queued),
    details,
  };
}

function addStructuredCoachReceipts(payload) {
  const commands = Array.isArray(payload?.command_receipts) ? payload.command_receipts : [];
  const planCommitRequested = payload?.intent?.operation === "commit_training_plan"
    || payload?.intent?.follow_up_operations?.includes("commit_training_plan")
    || commands.some((entry) => entry.tool === "commit_training_plan");
  const finalCommit = commands.findLast((entry) => entry.tool === "commit_training_plan");
  state.coachReceipts = [];
  renderCoachReceipts();
  commands.filter((entry) => receiptIsVisible(entry, planCommitRequested, finalCommit))
    .forEach((entry) => addCoachReceipt(commandReceipt(entry)));
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
  if (!configured.openai && !configured.gemini) missing.push("OpenAI- oder Gemini-API-Schlüssel");
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
  $("#statusTitle").textContent = statusTitle;
  $("#statusDetail").textContent = statusDetail;
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

async function askCoach(message) {
  const applied = await applyNavigationRoute("coach", { historyMode: "push", focus: false });
  if (!applied) return;
  const input = $("#messageInput");
  if (!input) return;
  input.value = message;
  input.dispatchEvent(new Event("input"));
  $("#chatForm")?.requestSubmit();
}

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

function activityTypeKey(activity) {
  return String(activity?.type || "Sportart unbekannt").trim() || "Sportart unbekannt";
}

function activityTypeCounts(activities) {
  const counts = new Map();
  (Array.isArray(activities) ? activities : []).forEach((activity) => {
    const type = activityTypeKey(activity);
    counts.set(type, (counts.get(type) || 0) + 1);
  });
  return counts;
}

function refreshActivityFilters() {
  state.activityVisibleCount = 250;
  renderActivities(state.data?.activities || []);
}

function activityFilterButton(type, count) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `activity-filter-button${state.activityTypes.has(type) ? " active" : ""}`;
  button.textContent = `${type} (${count})`;
  button.setAttribute("aria-pressed", state.activityTypes.has(type) ? "true" : "false");
  button.addEventListener("click", () => {
    if (state.activityTypes.has(type)) state.activityTypes.delete(type);
    else state.activityTypes.add(type);
    refreshActivityFilters();
  });
  return button;
}

function renderActivityFilters(activities) {
  const root = $("#activityFilters");
  if (!root) return;
  root.replaceChildren();
  const counts = activityTypeCounts(activities);
  if (!counts.size) {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  const label = document.createElement("span");
  label.className = "activity-filters-label";
  label.textContent = "Typ filtern:";
  root.append(label);
  [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "de")).forEach(([type, count]) => root.append(activityFilterButton(type, count)));
  if (state.activityTypes.size) {
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "activity-filter-button clear";
    clear.textContent = "Zurücksetzen";
    clear.addEventListener("click", () => {
      state.activityTypes.clear();
      refreshActivityFilters();
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

function renderActivitySyncDetail() {
  const syncDetail = $("#activitySyncDetail");
  if (!syncDetail) return;
  const syncNotices = [];
  if (state.data?.provider_resync?.intervals?.running || state.localSync.intervalsFull) syncNotices.push(state.data?.provider_resync?.intervals?.status || "Intervals.icu wird vollständig neu geladen…");
  if (state.data?.provider_resync?.garmin?.running || state.localSync.garminFull) syncNotices.push(state.data?.provider_resync?.garmin?.status || "Garmin wird vollständig neu geladen…");
  if (state.data?.sync?.running || state.localSync.intervals) syncNotices.push(state.data?.sync?.status || "Intervals.icu wird synchronisiert…");
  const refreshedAt = state.data?.sync?.last_sync_at;
  const refreshedText = refreshedAt ? `Letzte Aktualisierung: ${formatTime(refreshedAt)}` : "Noch nicht aktualisiert";
  syncDetail.textContent = syncNotices.length ? syncNotices.join(" · ") : refreshedText;
}

function filteredActivities(list) {
  const dateFiltered = list.filter((activity) => {
    const activityDate = String(activity.start_date_local || activity.date || "").slice(0, 10);
    if (state.activityFromDate && (!activityDate || activityDate < state.activityFromDate)) return false;
    if (state.activityToDate && (!activityDate || activityDate > state.activityToDate)) return false;
    return true;
  });
  return state.activityTypes.size
    ? dateFiltered.filter((activity) => state.activityTypes.has(activityTypeKey(activity)))
    : dateFiltered;
}

function renderActivitiesEmpty(root, list) {
  const empty = document.createElement("div");
  empty.className = "empty";
  const title = document.createElement("strong");
  title.textContent = list.length ? "Keine passenden Einheiten" : "Noch keine absolvierten Einheiten";
  let emptyMessage;
  if (!list.length) emptyMessage = "Aktualisiere die Trainingsdaten, um deine synchronisierten Aktivitäten hier zu sehen.";
  else if (state.activityFromDate || state.activityToDate) emptyMessage = "Passe den Zeitraum an oder setze den Filter zurück.";
  else emptyMessage = "Wähle einen weiteren Aktivitätstyp oder setze den Filter zurück.";
  empty.append(title, document.createTextNode(emptyMessage));
  root.append(empty);
}

function renderActivityCard(activity) {
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
  card.append(top, stats);
  const feedbackNotes = String(activity.activity_feedback?.notes || "").trim();
  if (feedbackNotes) {
    const feedback = document.createElement("section");
    feedback.className = "activity-feedback";
    const feedbackTitle = document.createElement("h4");
    feedbackTitle.className = "activity-feedback-title";
    feedbackTitle.textContent = "Besonderheiten";
    const feedbackText = document.createElement("p");
    feedbackText.className = "activity-feedback-notes";
    feedbackText.textContent = feedbackNotes;
    feedback.append(feedbackTitle, feedbackText);
    card.append(feedback);
  }
  return card;
}

function appendActivitiesLoadMore(root, displayedActivities) {
  if (!(displayedActivities.length > state.activityVisibleCount || state.data?.activities_next_cursor)) return;
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

function renderActivities(activities) {
  const list = Array.isArray(activities) ? activities : [];
  renderActivitySyncDetail();
  renderActivityFilters(list);
  const displayedActivities = filteredActivities(list);
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
  if (!displayedActivities.length) renderActivitiesEmpty(root, list);
  displayedActivities.slice(0, state.activityVisibleCount).forEach((activity) => root.append(renderActivityCard(activity)));
  appendActivitiesLoadMore(root, displayedActivities);
}
let chatStreamRenderFrame = null;
let chatStreamStartScrollPending = false;
let chatComposerRevealPending = false;

function chatIsNearBottom() {
  return document.documentElement.scrollHeight - (globalThis.scrollY + globalThis.innerHeight) <= 48;
}

function updateChatComposerVisibility() {
  const panel = $("#chatPanel");
  if (!panel) return;
  const inputFocused = Boolean($("#chatForm")?.contains(document.activeElement));
  const hidden = !panel.classList.contains("chat-empty")
    && !chatComposerRevealPending
    && !inputFocused
    && !(state.chatAttachments || []).length
    && !chatIsNearBottom();
  panel.classList.toggle("chat-composer-hidden", hidden);
  const jump = $("#chatJumpToComposer");
  if (jump) jump.hidden = !hidden || !panel.classList.contains("active");
}

function jumpToChatComposer() {
  const input = $("#messageInput");
  if (!input) return;
  const panel = $("#chatPanel");
  const composer = $("#chatForm");
  chatComposerRevealPending = true;
  panel?.classList.remove("chat-composer-hidden");
  const jump = $("#chatJumpToComposer");
  if (jump) jump.hidden = true;
  input.focus({ preventScroll: true });
  composer?.scrollIntoView({ block: "end", behavior: "auto" });
  requestAnimationFrame(() => {
    globalThis.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
    input.focus({ preventScroll: true });
    chatComposerRevealPending = false;
    updateChatComposerVisibility();
    panel?.classList.remove("chat-composer-hidden");
    if (jump) jump.hidden = true;
    scheduleMobileViewportLayout();
  });
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

function coachWorkingLabel() {
  if (state.chatRequest?.background) return "Der Coach arbeitet · du kannst die Seite neu laden…";
  if (state.chatRequest?.phase === "recovering") return "Verbindung unterbrochen · die Antwort wird im Hintergrund fertiggestellt…";
  if (state.chatRequest?.phase === "reconciling") return "Antwort wird sicher übernommen…";
  return "Coach arbeitet an deiner Antwort…";
}

function createCoachWorkingIndicator() {
  const node = document.createElement("div");
  node.id = "coachWorking";
  node.className = "coach-working";
  node.setAttribute("role", "status");
  node.setAttribute("aria-label", coachWorkingLabel());
  const dots = document.createElement("span");
  dots.className = "working-dots";
  dots.setAttribute("aria-hidden", "true");
  dots.innerHTML = "<i></i><i></i><i></i>";
  node.append(dots);
  return node;
}

function renderCoachActionReview() {
  const root = $("#coachActionReview");
  const content = $("#coachActionReviewContent");
  if (!root || !content) return;
  content.replaceChildren();
  const proposals = (state.coachActionProposals || []).filter((proposal) => ["undo_change", "delete_duplicate_intervals_activity"].includes(proposal.action_type));
  root.hidden = proposals.length === 0;
  $("#coachActionReviewTitle").textContent = "Aktion prüfen";
  root.querySelector(".coach-action-review-status").textContent = "Freigabe und Ergebnis getrennt prüfen";
  for (const proposal of proposals) {
    const undo = proposal.action_type === "undo_change";
    const actionable = ["preview", "ready"].includes(proposal.status);
    const card = document.createElement("div");
    card.className = "coach-action-card";
    card.dataset.proposalStatus = proposal.status;
    const description = document.createElement("p");
    description.textContent = undo ? "Diese lokale Änderung zurücknehmen? Der aktuelle Stand wird vor der Ausführung erneut geprüft." : "Diese Garmin-Aufzeichnung ist nahezu identisch mit der Wahoo-Einheit. Nur das Garmin-Duplikat aus Intervals.icu löschen?";
    card.append(description);
    if (!actionable) {
      const status = document.createElement("p");
      status.textContent = proposal.status === "used" ? "Freigabe bereits verwendet. Bitte den Ausführungsbeleg prüfen." : "Dieser Vorschlag ist abgelaufen oder nicht mehr ausführbar. Bitte den Coach um eine neue Prüfung bitten.";
      card.append(status);
    } else {
      const entries = document.createElement("ul");
      for (const entry of Array.isArray(proposal.diff) ? proposal.diff : []) {
        const item = document.createElement("li");
        item.textContent = [entry.name, entry.date, entry.sport].filter(Boolean).join(" · ");
        entries.append(item);
      }
      const actions = document.createElement("div");
      actions.className = "coach-action-card-actions";
      const later = document.createElement("button");
      later.type = "button";
      later.className = "secondary-button";
      later.textContent = "Später prüfen";
      later.addEventListener("click", () => {
        state.chatProposalRefreshPending = true;
        state.coachActionProposals = state.coachActionProposals.filter((item) => item.id !== proposal.id);
        renderCoachActionReview();
      });
      const confirm = document.createElement("button");
      confirm.type = "button";
      confirm.textContent = undo ? "Änderung zurücknehmen" : "Garmin-Duplikat löschen";
      confirm.addEventListener("click", () => executeCoachActionProposal(proposal, confirm));
      actions.append(later, confirm);
      card.append(entries, actions);
    }
    content.append(card);
  }
}

async function executeCoachActionProposal(proposal, button) {
  if (!proposal?.id || button.disabled || !["preview", "ready"].includes(proposal.status)) return;
  button.disabled = true;
  try {
    const confirmed = await api("/api/coach/actions/confirm", {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposal.id }),
    });
    const result = await api("/api/coach/actions/execute", {
      method: "POST",
      body: JSON.stringify({ action_token: confirmed.action_token, payload_hash: confirmed.proposed_action.payload_hash }),
    });
    if (proposal.action_type === "undo_change" && result.status !== "undone") throw new Error("Die Undo-Bestätigung fehlt; bitte den aktuellen Stand prüfen.");
    state.coachActionProposals = (state.coachActionProposals || []).filter((item) => item.id !== proposal.id);
    renderCoachActionReview();
    const duplicateDelete = proposal.action_type === "delete_duplicate_intervals_activity";
    const undo = proposal.action_type === "undo_change";
    let receiptMessage;
    if (undo) receiptMessage = "Die lokale Änderung wurde zurückgenommen.";
    else if (duplicateDelete) receiptMessage = "Garmin-Duplikat aus Intervals.icu gelöscht; die Wahoo-Aktivität bleibt erhalten.";
    else if (result.local_planned) receiptMessage = `${result.local_planned} Einheit(en) lokal geplant.`;
    else receiptMessage = "Planung lokal gespeichert.";
    let receiptTitle;
    if (undo) receiptTitle = "Änderung zurückgenommen";
    else if (duplicateDelete) receiptTitle = "Duplikat gelöscht";
    else receiptTitle = "Planung gespeichert";
    let receiptDetails;
    if (duplicateDelete) receiptDetails = ["Wahoo bleibt die kanonische Radaufzeichnung"];
    else if (result.sync_job_ids?.length) receiptDetails = [`${result.sync_job_ids.length} Syncjobs eingereiht`];
    else if (result.sync_job_id) receiptDetails = [`Syncjob ${result.sync_job_id} eingereiht`];
    else receiptDetails = ["Keine implizite Remote-Änderung"];
    addCoachReceipt({ title: receiptTitle, message: receiptMessage, details: receiptDetails });
    toast(receiptMessage);
    await load("/api/bootstrap?local=1", duplicateDelete ? ["activities"] : ["plan", "library", "profile", "feedback"]);
    if (!duplicateDelete && !undo) applyNavigationRoute("plan", { historyMode: "push" });
  } catch (error) {
    addCoachReceipt({ title: "Aktion nicht bestätigt", message: error.message, status: "error" });
    if ([409, 410].includes(error.status)) { proposal.status = "expired"; renderCoachActionReview(); }
    toast(error.message, true);
    button.disabled = false;
  }
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

function mergeChatMessages(incoming, existing = state.data?.messages || []) {
  const messages = [];
  for (const message of [...existing, ...state.rejectedMessages, ...incoming]) {
    const index = messages.findIndex((entry) =>
      (message.id != null && entry.id != null && String(message.id) === String(entry.id))
      || (message.client_turn_id && entry.client_turn_id === message.client_turn_id && entry.role === message.role));
    if (index < 0) messages.push(message);
    else if (messages[index].id == null || message.id != null) messages[index] = { ...messages[index], ...message, optimistic: message.id == null };
  }
  return messages.sort((a, b) => {
    if (a.id != null && b.id != null) return Number(a.id) - Number(b.id);
    if (a.client_turn_id && a.client_turn_id === b.client_turn_id) return a.role === "user" ? -1 : 1;
    return (a.created_at || "").localeCompare(b.created_at || "");
  });
}

function reconcileCompletedChatMessage(message) {
  if (!state.data || !message || typeof message.content !== "string") return false;
  state.data.messages = mergeChatMessages([{ ...message, role: "assistant" }]);
  return true;
}

function rememberChatTurn(clientTurnId) {
  // Only an opaque operation identity survives a reload. No athlete text or credentials.
  try {
    if (clientTurnId) sessionStorage.setItem("coachPendingTurn", clientTurnId);
    else sessionStorage.removeItem("coachPendingTurn");
  } catch { }
}

function applyChatReceipt(receipt) {
  state.chatContentVersion += 1;
  if (receipt.message) reconcileCompletedChatMessage(receipt.message);
  if (Array.isArray(state.coachActionProposals) && state.coachActionProposals.length > 0) state.chatProposalRefreshPending = true;
  state.coachActionProposals = Array.isArray(receipt.proposed_actions) ? receipt.proposed_actions : [];
  addStructuredCoachReceipts(receipt);
  renderMessages(state.data?.messages || [], false);
}

function appendHistoryPageButton(root, area) {
  const chat = area === "chat";
  const cursor = state.data?.[chat ? "messages_next_cursor" : "library_next_cursor"];
  if (!cursor) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.dataset.pageArea = area;
  button.textContent = chat ? "Weitere Nachrichten laden" : "Weitere Bibliothekseinheiten laden";
  button.addEventListener("click", async () => {
    const generation = state.sessionGeneration;
    const chatGeneration = state.chatGeneration;
    button.disabled = true;
    try {
      const result = await api(`${chat ? "/api/chat/history" : "/api/library"}?limit=100&cursor=${encodeURIComponent(cursor)}`);
      if (generation !== state.sessionGeneration || chatGeneration !== state.chatGeneration) return;
      if (chat) {
        if (result.generation !== state.data.messages_generation) { await loadChatHistoryFresh(); return; }
        state.data.messages = mergeChatMessages(result.messages || []);
        state.data.messages_next_cursor = result.next_cursor;
        renderMessages(state.data.messages, false, true);
      } else {
        const all = [...(state.data.library || []), ...(result.workouts || [])];
        state.data.library = [...new Map(all.map((entry) => [entry.id, entry])).values()];
        state.data.library_next_cursor = result.next_cursor;
        renderLibrary(state.data.library);
      }
    } catch (error) { toast(error.message, true); button.disabled = false; }
  });
  root.append(button);
}

function messageAttachmentLabel(names) {
  try {
    const parsed = JSON.parse(names);
    return parsed.length ? String.fromCodePoint(10) + "Anhänge: " + parsed.join(", ") : "";
  } catch (parseError) {
    if (!(parseError instanceof SyntaxError)) throw parseError;
    return "";
  }
}

function restoreRejectedMessage(message) {
  const input = $("#messageInput");
  if (input.value.trim() || (state.chatAttachments || []).length) return toast("Bitte zuerst den aktuellen Entwurf bearbeiten.", true);
  input.value = message.content;
  state.chatAttachments = message.attachments || [];
  renderChatAttachments();
  state.chatDraftDirty = true;
  state.data.messages = state.data.messages.filter((entry) => entry !== message);
  state.rejectedMessages = state.rejectedMessages.filter((entry) => entry.client_turn_id !== message.client_turn_id);
  renderMessages(state.data.messages);
  jumpToChatComposer();
  updateChatControls();
}

function appendMessageRetry(node, message) {
  if (!message.error) return;
  const error = document.createElement("p");
  error.className = "message-error";
  error.textContent = message.error;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "Als Entwurf übernehmen";
  retry.addEventListener("click", () => restoreRejectedMessage(message));
  node.append(error, retry);
}

function renderMessageNode(message) {
  const node = document.createElement("div");
  node.className = `message ${message.role}`;
  if (message.id != null) node.dataset.messageId = String(message.id);
  if (message.role === "assistant") node.innerHTML = markdownToHtml(message.content);
  else {
    node.textContent = message.content;
    if (message.attachment_names) {
      const label = document.createElement("small");
      label.textContent = messageAttachmentLabel(message.attachment_names);
      node.append(label);
    }
  }
  appendMessageRetry(node, message);
  return node;
}

function appendChatStream(root, streamVisible) {
  const phase = state.chatRequest?.phase;
  if (!streamVisible) return false;
  const node = document.createElement("div");
  node.className = `message assistant streaming${phase === "recovering" ? " is-recovering" : ""}`;
  node.innerHTML = markdownToHtml(state.chatStreamText);
  root.append(node);
  return true;
}

function renderMessages(messages, forceScroll = false, preserveScroll = false) {
  const root = $("#messages");
  const appShellLoading = Boolean($("#appShell")?.classList.contains("is-loading"));
  const visibleMessages = messages || [];
  const signature = JSON.stringify([
    visibleMessages.map((message) => [message.id || null, message.created_at || null, message.role, message.content, message.attachment_names, message.error]),
    appShellLoading, state.data?.messages_next_cursor, state.chatStreamText, state.chatServerOperationId,
    state.chatResponseStarted, state.chatRequest?.phase || null, state.chatRequest?.responseMessageId || null,
    state.chatRequest?.responseMessageReceived || false,
    (state.coachActionProposals || []).map((proposal) => [proposal.id, proposal.status]),
    state.chatQueue.map((entry) => [entry.id, entry.mode, entry.message]),
  ]);
  const hasEmptyState = !visibleMessages.length && !appShellLoading && !state.chatRequest && !state.chatQueue.length;
  root.classList.toggle("has-empty-state", hasEmptyState);
  root.setAttribute("aria-busy", String(Boolean(state.chatRequest || state.chatServerOperationId)));
  $("#chatPanel")?.classList.toggle("chat-empty", hasEmptyState);
  if (root.dataset.signature === signature) return;
  const shouldScroll = !preserveScroll && (forceScroll || chatIsNearBottom());
  root.dataset.signature = signature;
  root.replaceChildren();
  appendHistoryPageButton(root, "chat");
  if (!visibleMessages.length && !state.chatRequest && !state.chatQueue.length) {
    root.append(appShellLoading ? createSkeletonStack(4) : createEmptyState("Dein Coach ist bereit", "Lege deine Ziele im Profil fest oder starte mit einer Schnellaktion."));
  }
  visibleMessages.forEach((message) => root.append(renderMessageNode(message)));
  state.chatQueue.forEach((entry) => root.append(createPendingMessage(entry)));
  const persistedResponse = Boolean(
    state.chatRequest?.responseMessageReceived
    || (state.chatRequest?.responseMessageId != null
      && visibleMessages.some((message) => message.id != null && String(message.id) === String(state.chatRequest.responseMessageId)))
  );
  const streamVisible = state.chatStreamText && !persistedResponse && ["running", "recovering", "reconciling"].includes(state.chatRequest?.phase);
  const showWorking = !persistedResponse && ["running", "recovering", "reconciling"].includes(state.chatRequest?.phase);
  appendChatStream(root, streamVisible);
  if (showWorking) root.append(createCoachWorkingIndicator());
  renderCoachActionReview();
  updateChatQueueStatus();
  updateChatComposerVisibility();
  if ((state.chatInitialScrollPending || shouldScroll) && !state.chatResponseStarted) scrollChatToLatest();
}
function cancelScheduledChatStreamRender() {
  if (chatStreamRenderFrame != null) cancelAnimationFrame(chatStreamRenderFrame);
  chatStreamRenderFrame = null;
  chatStreamStartScrollPending = false;
}

function scheduleChatStreamRender(scrollToStart = false) {
  chatStreamStartScrollPending = chatStreamStartScrollPending || scrollToStart;
  if (chatStreamRenderFrame != null) return;
  chatStreamRenderFrame = requestAnimationFrame(() => {
    chatStreamRenderFrame = null;
    const shouldScrollToStart = chatStreamStartScrollPending;
    chatStreamStartScrollPending = false;
    const root = $("#messages");
    const streaming = root?.querySelector(".message.assistant.streaming");
    if (!streaming) renderMessages(state.data?.messages || [], false);
    else {
      streaming.classList.toggle("is-recovering", state.chatRequest?.phase === "recovering");
      streaming.innerHTML = markdownToHtml(state.chatStreamText);
      updateChatComposerVisibility();
    }
    if (shouldScrollToStart) scrollChatToResponseStart();
  });
}

function scrollChatToResponseStart() {
  const panel = $("#chatPanel");
  const root = $("#messages");
  if (!panel?.classList.contains("active") || !root) {
    state.chatResponseScrollPending = true;
    return;
  }
  state.chatResponseScrollPending = false;
  requestAnimationFrame(() => {
    if (!panel.classList.contains("active")) {
      state.chatResponseScrollPending = true;
      return;
    }
    const assistants = [...root.querySelectorAll(".message.assistant")];
    const responseId = state.chatRequest?.responseMessageId ?? state.chatResponseMessageId;
    const target = root.querySelector(".message.assistant.streaming")
      || (responseId == null ? null : assistants.find((node) => node.dataset.messageId === String(responseId)))
      || (!state.chatRequest ? assistants.at(-1) : null);
    if (!target) {
      state.chatResponseScrollPending = true;
      return;
    }
    const topGap = 16;
    globalThis.scrollTo({ top: Math.max(0, globalThis.scrollY + target.getBoundingClientRect().top - topGap), behavior: "auto" });
    state.chatResponseMessageId = null;
    requestAnimationFrame(updateChatComposerVisibility);
  });
}

function scrollChatToLatest() {
  const panel = $("#chatPanel");
  const root = $("#messages");
  if (!panel?.classList.contains("active") || !root) return;
  requestAnimationFrame(() => {
    if (state.chatInitialScrollPending && (!state.initialStateLoaded || document.readyState !== "complete")) return;
    const target = root.lastElementChild;
    if (!target) return;
    state.chatInitialScrollPending = false;
    const composer = $("#chatForm");
    const targetBottom = target.getBoundingClientRect().bottom;
    const composerTop = composer?.getBoundingClientRect().top;
    const targetGap = 12;
    const desiredBottom = Math.min(
      globalThis.innerHeight,
      Number.isFinite(composerTop) ? composerTop : globalThis.innerHeight,
    ) - targetGap;
    globalThis.scrollTo({ top: Math.max(0, globalThis.scrollY + targetBottom - desiredBottom), behavior: "auto" });
    requestAnimationFrame(updateChatComposerVisibility);
  });
}

function restoreChatScrollPosition() {
  const panel = $("#chatPanel");
  const scrollY = state.chatScrollY;
  if (!panel?.classList.contains("active") || !Number.isFinite(scrollY)) return false;
  state.chatScrollRestoring = true;
  requestAnimationFrame(() => {
    if (!panel.classList.contains("active")) {
      state.chatScrollRestoring = false;
      return;
    }
    globalThis.scrollTo({ top: scrollY, behavior: "auto" });
    requestAnimationFrame(() => {
      if (panel.classList.contains("active")) globalThis.scrollTo({ top: scrollY, behavior: "auto" });
      state.chatScrollRestoring = false;
      updateChatComposerVisibility();
    });
  });
  return true;
}

function handleWindowScroll() {
  if (!state.chatInitialScrollPending && !state.chatScrollRestoring && $("#chatPanel")?.classList.contains("active")) {
    state.chatScrollY = globalThis.scrollY;
  }
  updateChatComposerVisibility();
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
  let snapshotNote = "";
  if (preview.snapshot_compacted) snapshotNote = " (Snapshot für den Coach kompakt aufbereitet)";
  else if (preview.snapshot_truncated) snapshotNote = " (Snapshot im Coach-Kontext gekürzt)";
  status.textContent = `Zuletzt erstellt: ${formatTime(preview.generated_at)}${snapshotNote}`;
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

function plannedInsightMetrics(checkin, recovery) {
  const metrics = [];
  const addMetric = (label, value, suffix, source) => {
    const formatted = calendarMetricNumber(value, suffix);
    if (formatted != null) metrics.push({ label, value: formatted, source });
  };
  for (const [key, label, suffix] of [
    ["sleep_hours", "Schlaf", " h"], ["sleep_score", "Schlafscore", "/100"],
    ["hrv", "HRV", " ms"], ["resting_hr", "Ruhepuls", " bpm"],
    ["readiness", "Readiness", "/100"], ["body_battery", "Body Battery", "/100"],
  ]) addMetric(label, recovery[key], suffix, recovery.sources?.[key]);
  for (const [key, label, suffix] of [
    ["soreness", "Muskelkater", "/10"], ["stress", "Stress", "/10"],
    ["motivation", "Motivation", "/10"], ["available_minutes", "Zeit verfügbar", " Min."],
  ]) addMetric(label, checkin[key], suffix, "Eigene Angabe");
  return metrics;
}

function appendPlannedInsightMeasurements(content, metrics, checkin, dateKey, todayKey) {
  if (metrics.length || Object.keys(checkin).length) {
    if (checkin.day_form) {
      const form = document.createElement("p");
      form.className = "planned-day-form";
      form.textContent = checkin.day_form;
      content.append(form);
    }
    if (metrics.length) {
      const grid = document.createElement("dl");
      grid.className = "planned-day-metrics";
      metrics.forEach(({ label, value, source }) => {
        const item = document.createElement("div");
        if (source) item.title = `${label}: ${source}`;
        const term = document.createElement("dt");
        term.textContent = label;
        const measurement = document.createElement("dd");
        measurement.textContent = value;
        item.append(term, measurement);
        grid.append(item);
      });
      content.append(grid);
    }
  } else if (dateKey <= todayKey) {
    const empty = document.createElement("p");
    empty.className = "planned-insights-empty";
    empty.textContent = "Keine Check-in- oder Erholungswerte gespeichert";
    content.append(empty);
  }
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

function appendPlannedCheckinObservations(body, checkin) {
  for (const [field, label] of [["availability_notes", "Zeitplanung"], ["notes", "Notizen"]]) {
    if (checkin[field]) {
      const note = document.createElement("p");
      note.textContent = `${label}: ${checkin[field]}`;
      body.append(note);
    }
  }
  const rpe = calendarRpeLabel(checkin.session_rpe);
  if (rpe != null) {
    const effort = document.createElement("p");
    effort.textContent = `Belastung nach dem Training: RPE ${rpe}/10 · Eigene Angabe`;
    body.append(effort);
  }
}

function plannedDayInsights(context, weather, dateKey, todayKey) {
  const checkin = context.checkin || {};
  const recovery = dateKey <= todayKey ? context.recovery || {} : {};
  const metrics = plannedInsightMetrics(checkin, recovery);
  const section = document.createElement("div");
  section.className = "planned-day-insights";
  const content = document.createElement("div");
  content.className = "planned-insights-content";
  appendPlannedInsightMeasurements(content, metrics, checkin, dateKey, todayKey);
  const details = document.createElement("div");
  details.className = "planned-day-observations";
  const body = document.createElement("div");
  appendPlannedWeatherInsight(body, weather);
  appendPlannedCheckinObservations(body, checkin);
  if (body.childElementCount) {
    details.append(body);
    content.append(details);
  }
  if (!content.childElementCount) return null;
  const title = document.createElement("p");
  title.className = "planned-insights-title";
  title.textContent = metrics.length || Object.keys(checkin).length
    ? "Check-in & Erholung" : "Tagesdetails";
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
  if (baseRoute(state.route) !== "plan" || planSegmentFromRoute(state.route) !== "overview") return false;
  const today = $("#plannedCalendar")?.querySelector(".planned-day.is-today");
  if (!today) return false;
  const week = today.closest(".planned-week");
  if (week) week.open = true;
  state.plannedTodayFocusPending = false;
  today.scrollIntoView({ block: "start", behavior: "auto" });
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (baseRoute(state.route) === "plan" && today.isConnected) today.scrollIntoView({ block: "start", behavior: "auto" });
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
  meta.textContent = [
    activitySportLabel(displayed),
    calendarStartTime(displayed.start_date_local),
    plannedEntryDurationLabel(actual, entry),
  ].filter(Boolean).join(" · ");
  cardSummary.append(cardTitle, meta);
  if (status === "completed" || status === "missed") {
    const statusText = document.createElement("span");
    statusText.className = "planned-entry-status";
    statusText.textContent = calendarStatusLabel(entry, dateKey, todayKey);
    cardSummary.append(statusText);
  }
  const details = document.createElement("div");
  details.className = "planned-entry-details";
  appendActualCalendarDetails(details, actual);
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
  title.textContent = new Intl.DateTimeFormat("de-DE", { weekday: "long" }).format(dateFromKey(dateKey));
  day.setAttribute("aria-labelledby", title.id);
  const dayDate = document.createElement("time");
  dayDate.dateTime = dateKey;
  dayDate.textContent = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "short" }).format(dateFromKey(dateKey));
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
  if (!dayEntries.length) {
    const empty = document.createElement("p");
    empty.className = "planned-day-empty";
    empty.textContent = dateKey < todayKey ? "Keine Aktivität" : "Keine Einheit geplant";
    content.append(empty);
  }
  dayEntries.forEach((entry) => content.append(renderPlannedEntry(entry, dateKey, todayKey)));
  const notes = plannedDayNotes(dayContext);
  if (notes.childElementCount) content.append(notes);
  day.append(content);
  const insights = plannedDayInsights(dayContext, weather, dateKey, todayKey);
  if (insights) day.append(insights);
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

function renderPlanned(trainingCalendar) {
  const root = $("#plannedCalendar");
  const summary = $("#plannedSummary");
  if (!root) return;
  const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
  const currentWeekKey = planWeekStart(todayKey);
  const display = state.data?.calendar_display || {};
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

function renderProfile(profile) {
  setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
  if (state.profileDirty) return;
  const form = $("#profileForm");
  for (const [key, value] of Object.entries(profile)) {
    const field = form.elements[key];
    if (!field) continue;
    if (key === "sports" && field.multiple) {
      const selectedSports = new Set(String(value || "").split(",").map((item) => item.trim()).filter(Boolean));
      [...field.options].forEach((option) => { option.selected = selectedSports.has(option.value); });
      continue;
    }
    if (key === "timezone" && field.tagName === "SELECT") {
      if (value && ![...field.options].some((option) => option.value === value)) field.append(new Option(`${value} (gespeichert)`, value));
      field.value = value || "";
      continue;
    }
    field.value = value || "";
  }
  if (form.elements.coaching_style?.value === "Supportive, direct, and evidence-aware") form.elements.coaching_style.value = "Unterstützend, direkt und evidenzbasiert";
  const summary = $("#profileSummary");
  if (summary) {
    const values = [profile.name, profile.sports, profile.typical_weekly_volume].filter(Boolean);
    summary.textContent = values.length ? values.join(" · ") : "Noch nicht ausgefüllt";
  }
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
  const morningBodyBattery = garmin.morning_body_battery || {};
  const beforeSleepBattery = Number(morningBodyBattery.before_sleep?.value);
  const morningBattery = Number(morningBodyBattery.morning?.value);
  const paginationDetail = Object.entries(garmin.pagination || {})
    .filter(([, value]) => value && (Number(value.windows) > 1 || value.complete === false))
    .map(([name, value]) => `${name}: ${value.records || 0} Datensätze in ${value.windows || 0} Zeitfenstern${value.complete === false ? " · unvollständig" : ""}`)
    .join(" · ");
  if (garmin.source === "fixture") status.textContent = "Lokale Garmin-Testdaten aktiv";
  else if (garmin.last_error) status.textContent = "Mit Fehlern synchronisiert";
  else status.textContent = "Optionaler Direktabruf aktiv";
  if (garmin.last_sync_at) {
    detail.textContent = `Letzter Abruf: ${formatTime(garmin.last_sync_at)} · ${garmin.activities || 0} Aktivitäten · Schlaf/HRV/Readiness ${[garmin.has_sleep, garmin.has_hrv, garmin.has_readiness].filter(Boolean).length}/3`;
  } else if (garmin.source === "fixture") {
    detail.textContent = "Testdatei ist konfiguriert; synchronisiere sie mit dem Button.";
  } else {
    detail.textContent = "Noch kein Garmin-Abruf durchgeführt.";
  }
  if (performanceSources.length) detail.textContent += ` · ${performanceSources.join("/")} aus Garmin`;
  if (morningBodyBattery.status === "ready" && Number.isFinite(beforeSleepBattery) && Number.isFinite(morningBattery)) {
    detail.textContent += ` · Body Battery am ${dateLabel(morningBodyBattery.sleep_date)}: ${beforeSleepBattery} vor dem Schlafen → ${morningBattery} nach dem Aufwachen`;
  } else if (morningBodyBattery.sleep_date) {
    detail.textContent += ` · Body Battery am ${dateLabel(morningBodyBattery.sleep_date)}: nicht verfügbar`;
  }
  if (paginationDetail) detail.textContent += ` · ${paginationDetail}`;
  if (fullButton) {
    fullButton.disabled = fullRunning || Boolean(state.data?.garmin_sync?.running || state.localSync.garmin);
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  if (fullStatus) {
    fullStatus.classList.toggle("error", Boolean(fullResync.last_error));
    if (fullRunning && fullResync.status) fullStatus.textContent = fullResync.status;
    else if (fullResync.last_error) fullStatus.textContent = fullResync.last_error;
    else if (fullResync.last_resync_at) fullStatus.textContent = `Letzter vollständiger Resync: ${formatTime(fullResync.last_resync_at)}`;
    else fullStatus.textContent = "Löscht nur lokale Garmin-Daten; Zugangsdaten und Cloud bleiben unverändert.";
  }
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

function askCoachAboutCompetitions() {
  const input = $("#messageInput");
  if (!input) return;
  if (input.value.trim()) {
    applyNavigationRoute("coach", { historyMode: "push" });
    requestAnimationFrame(() => input.focus());
    return;
  }
  input.value = "Ich möchte meine Zielwettkämpfe hinzufügen oder überarbeiten.";
  input.dispatchEvent(new Event("input"));
  applyNavigationRoute("coach", { historyMode: "push" });
  requestAnimationFrame(() => input.focus());
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

function displayMetric(root, label, metricData, formatter = null, editable = null) {
  const item = document.createElement("div");
  const metric = document.createElement("strong");
  const caption = document.createElement("span");
  const source = document.createElement("small");
  const value = metricData && typeof metricData === "object" ? metricData.value : metricData;
  const unit = metricData && typeof metricData === "object" ? metricData.unit : "";
  if (value == null) metric.textContent = "—";
  else if (formatter) metric.textContent = formatter(value);
  else metric.textContent = `${value}${unit ? " " + unit : ""}`;
  caption.textContent = label;
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
    if (state.data?.profile?.[editable.key]) input.value = state.data.profile[editable.key];
    else input.value = value == null ? "" : value;
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

function renderPerformance(performance) {
  const root = $("#performanceSummary");
  if (root.querySelector(".metric-editable.editing")) return;
  root.replaceChildren();
  const syncNotices = [];
  if (state.data?.sync?.running || state.localSync.intervals) syncNotices.push(state.data?.sync?.status || "Intervals.icu wird synchronisiert…");
  if (state.data?.garmin_sync?.running || state.localSync.garmin) syncNotices.push(state.data?.garmin_sync?.status || "Garmin wird synchronisiert…");
  if (state.data?.performance_refresh?.running || state.localSync.performance) syncNotices.push("Leistungsdaten werden aktualisiert…");
  if (!performance?.available) {
    const info = document.createElement("p");
    info.className = "fine-print";
    info.textContent = !state.loadedAreas.has("performance") && state.loadPromise
      ? "Leistungsdaten werden geladen…"
      : "Nach dem ersten Trainingsdaten-Update werden hier Leistungswerte angezeigt.";
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
  const refreshedAt = performance.as_of || state.data?.performance_refresh?.last_refresh_at || state.data?.sync?.last_sync_at;
  let performanceDetail = "";
  if (syncNotices.length) performanceDetail = syncNotices.join(" · ");
  else if (refreshedAt) performanceDetail = `Letzte Aktualisierung: ${formatTime(refreshedAt)}`;
  const compared = (value, key) => value && typeof value === "object" ? { ...value, comparison: comparisons[key] } : { value, comparison: comparisons[key] };
  performanceSection(root, "Gesundheitsdaten", [
    ["Gewicht", compared(values.weight_kg, "weight_kg_30d"), null, { key: "weight_kg", step: "0.1" }],
    ["Körperfett", values.body_fat_pct, null, { key: "body_fat_pct", step: "0.1" }],
    ["Größe", values.height_cm, null, { key: "height_cm", step: "0.1" }],
    ["Schlaf", compared({ ...recovery.source_freshness?.sleep_hours, value: recovery.sleep_hours, unit: "h", source: recovery.sleep_source || "Intervals.icu Wellness" }, "sleep_hours")],
    ["Readiness", compared({ ...recovery.source_freshness?.readiness, value: recovery.readiness, unit: "", source: recovery.readiness_source || "Intervals.icu Wellness" }, "readiness_30d")],
    ["Ruhepuls", compared({ ...recovery.source_freshness?.restingHR, value: recovery.restingHR, unit: "bpm", source: recovery.restingHR_source || "Intervals.icu Wellness" }, "restingHR")],
    ["HRV", compared({ ...recovery.source_freshness?.hrv, value: recovery.hrv, unit: "ms", source: recovery.hrv_source || "Intervals.icu Wellness" }, "hrv")],
    ["Schritte (Ø letzte 7 Tage)", values.steps_7d],
    ["Stockwerke (Ø letzte 7 Tage)", values.floors_7d],
    ["Kalorien (Ø letzte 7 Tage)", values.calories_7d],
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
    if (state.analysisSegment === "performance") {
      button.dataset.action = "performance";
      button.title = "Aktuelle Leistungsdaten von Intervals.icu aktualisieren";
      button.disabled = Boolean(state.data?.performance_refresh?.running || state.data?.sync?.running || state.data?.garmin_sync?.running || state.data?.provider_resync?.intervals?.running || state.data?.provider_resync?.garmin?.running || state.localSync.performance || state.localSync.intervals || state.localSync.garmin || state.localSync.intervalsFull || state.localSync.garminFull);
      if (state.data?.sync?.running || state.data?.garmin_sync?.running || state.localSync.intervals || state.localSync.garmin) {
        button.textContent = "Synchronisierung läuft…";
      } else if (button.disabled) {
        button.textContent = "Leistungsdaten werden aktualisiert…";
      } else {
        button.textContent = "Leistungsdaten aktualisieren";
      }
    } else {
      button.dataset.action = "activities";
      button.title = "Aktivitäten der letzten 90 Tage von Intervals.icu laden";
      button.disabled = Boolean(state.data?.sync?.running || state.data?.provider_resync?.intervals?.running || state.localSync.intervals || state.localSync.intervalsFull);
      button.textContent = button.disabled ? "Synchronisierung läuft…" : "Aktivitäten aktualisieren";
    }
  } else {
    button.hidden = true;
    button.disabled = false;
    button.dataset.action = "";
  }
}

function renderAiProvider(provider) {
  if (!provider) return;
  const select = $("#aiProviderSelect");
  const currentIds = [...select.options].map((option) => option.value).join(",");
  const nextIds = (provider.options || []).map((option) => option.id).join(",");
  if (currentIds !== nextIds) {
    select.replaceChildren();
    for (const option of provider.options || []) {
      const element = document.createElement("option");
      element.value = option.id;
      element.textContent = option.label;
      element.title = option.description || "";
      select.append(element);
    }
  }
  select.value = provider.selected;
  const selected = (provider.options || []).find((option) => option.id === provider.selected);
  $("#aiProviderDescription").textContent = selected?.description || "Der ausgewählte Anbieter erhält den Coach-Kontext.";
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
  const settingsVersionNode = $("#settingsAppVersion");
  if (settingsVersionNode) settingsVersionNode.textContent = app.version ? `v${app.version}` : "unbekannt";
}

function settingsStatus(selector, ok, text) {
  const node = $(selector);
  if (!node) return;
  node.textContent = text;
  node.className = ok ? "configured" : "not-configured";
}

function aiProviderName(provider) {
  return provider === "gemini" ? "Gemini" : "OpenAI";
}

function aiConnectionLabel(configured, activeError) {
  if (!configured) return "Nicht konfiguriert";
  return activeError ? "Fehler bei letzter Anfrage" : "Konfiguriert";
}

function aiConnectionConfigurationDetail(provider) {
  return provider === "gemini" ? "GEMINI_API_KEY nicht konfiguriert" : "API-Schlüssel nicht konfiguriert";
}

function aiConnectionErrorDetail(provider, status) {
  const message = status.message || aiProviderName(provider) + "-Anfrage fehlgeschlagen.";
  const updated = status.updated_at ? " · " + formatTime(status.updated_at) : "";
  return message + updated;
}

function aiConnectionDetail(provider, configured, activeProvider, activeError, status) {
  if (!configured) return aiConnectionConfigurationDetail(provider);
  if (activeError) return aiConnectionErrorDetail(provider, status);
  if (activeProvider === provider && status.state === "ok") return "Letzter erfolgreicher API-Aufruf: " + formatTime(status.updated_at);
  return "Als alternativer Anbieter konfiguriert";
}

function renderAiConnection(provider, configured, activeProvider, status) {
  const activeError = activeProvider === provider && status.state === "error";
  const healthy = configured && !activeError;
  settingsStatus("#" + provider + "ConnectionStatus", healthy, aiConnectionLabel(configured, activeError));
  const detail = $("#" + provider + "ConnectionDetail");
  if (detail) {
    detail.classList.toggle("error", Boolean(configured && activeError));
    detail.textContent = aiConnectionDetail(provider, configured, activeProvider, activeError, status);
  }
  return healthy;
}

function intervalsConnectionState(data, configured) {
  return data.intervals || {
    configured: Boolean(configured.intervals),
    state: configured.intervals ? "configured" : "not_configured",
  };
}

function intervalsPaginationDetail(intervals) {
  return Object.entries(intervals.pagination || {})
    .filter(([, value]) => value && (Number(value.pages) > 1 || value.complete === false))
    .map(([name, value]) => {
      const completeness = value.complete === false ? " · unvollständig" : "";
      return name + ": " + (value.records || 0) + " Datensätze auf " + (value.pages || 0) + " Seiten" + completeness;
    })
    .join(" · ");
}

function intervalsConnectionDetail(intervals) {
  const librarySync = intervals.library_sync || {};
  if (!intervals.configured) return "API-Schlüssel nicht konfiguriert";
  if (intervals.state === "syncing") return intervals.status || "Intervals.icu wird synchronisiert.";
  if (intervals.last_error) return intervals.last_error;
  if (!(intervals.last_sync_at || librarySync.last_sync_at)) return "Noch keine Synchronisierung durchgeführt";
  const updated = formatTime(intervals.last_sync_at || librarySync.last_sync_at);
  const libraryCount = Number(librarySync.state?.synced || 0);
  const counts = libraryCount ? " · " + libraryCount + " Bibliothekseinheiten" : "";
  const pagination = intervalsPaginationDetail(intervals);
  const paginationSuffix = pagination ? " · " + pagination : "";
  return "Letzte Aktualisierung: " + updated + counts + paginationSuffix;
}

function renderIntervalsConnection(data, configured) {
  const intervals = intervalsConnectionState(data, configured);
  const healthy = intervals.configured && intervals.state !== "error";
  const labels = {
    not_configured: "Nicht konfiguriert",
    syncing: "Synchronisierung läuft…",
    error: "Fehler bei letzter Aktualisierung",
    connected: "Verbunden",
  };
  settingsStatus("#intervalsConnectionStatus", healthy, labels[intervals.state] || "Konfiguriert · noch nicht getestet");
  const detail = $("#intervalsConnectionDetail");
  if (detail) {
    detail.classList.toggle("error", Boolean(intervals.last_error));
    detail.textContent = intervalsConnectionDetail(intervals);
  }
  return healthy;
}

function weatherConnectionLabel(weather) {
  if (!weather.configured) return "Nicht konfiguriert";
  return weather.loading ? "Wird geladen" : "Konfiguriert";
}

function weatherConnectionDetail(weather) {
  if (!weather.configured) return "Kein API-Schlüssel erforderlich · Standort im Profil hinterlegen";
  const location = [weather.location?.name, weather.location?.country].filter(Boolean).join(", ");
  const prefix = location ? "Standort: " + location + " · " : "";
  const fetched = weather.fetched_at ? "letzte Abfrage: " + formatTime(weather.fetched_at) : "Standort im Profil hinterlegen";
  return prefix + fetched;
}

function renderWeatherConnection(weather) {
  settingsStatus("#weatherConnectionStatus", weather.configured, weatherConnectionLabel(weather));
  const detail = $("#weatherConnectionDetail");
  if (detail) detail.textContent = weatherConnectionDetail(weather);
  const button = $("#weatherSyncButton");
  if (button) {
    const running = Boolean(state.localSync.weather);
    button.disabled = !weather.configured || running;
    button.textContent = running ? "Wetter wird aktualisiert…" : "Wetter aktualisieren";
  }
}

function updateUnfocusedInput(selector, value) {
  const input = $(selector);
  if (input && document.activeElement !== input) input.value = value;
}

function renderSettingsSyncDayInputs(data) {
  updateUnfocusedInput("#intervalsSyncDays", data.sync_settings?.intervals_days || 90);
  updateUnfocusedInput("#garminSyncDays", data.sync_settings?.garmin_days || 30);
}

function calendarHorizonText(data) {
  const window = data.planning_view?.provider_window || {};
  if (window.start && window.end) return "Die Ansicht bleibt auf das lokal geladene Intervals.icu-Fenster " + window.start + " bis " + window.end + " begrenzt.";
  return "Die Ansicht wird auf das lokal geladene Providerfenster begrenzt.";
}

function renderCalendarDisplayInputs(data) {
  const display = data.calendar_display || CALENDAR_DISPLAY_DEFAULTS;
  const pastWeeks = calendarDisplayValue(display.past_weeks, CALENDAR_DISPLAY_DEFAULTS.past_weeks);
  const futureWeeks = calendarDisplayValue(display.future_weeks, CALENDAR_DISPLAY_DEFAULTS.future_weeks);
  updateUnfocusedInput("#calendarDisplayPastWeeks", pastWeeks);
  updateUnfocusedInput("#calendarDisplayFutureWeeks", futureWeeks);
  const summary = $("#calendarDisplaySummary");
  if (summary) summary.textContent = pastWeeks + " zurück · " + futureWeeks + " voraus";
  const hint = $("#calendarHorizonHint");
  if (hint) hint.textContent = calendarHorizonText(data);
}

function renderSettingsInputs(data) {
  renderSettingsSyncDayInputs(data);
  renderCalendarDisplayInputs(data);
}

function intervalsSyncRunning(data, fullRunning) {
  return Boolean(data.sync?.running || state.localSync.intervals || fullRunning);
}

function intervalsFullResyncText(fullResync, fullRunning) {
  if (fullRunning && fullResync.status) return fullResync.status;
  if (fullResync.last_error) return fullResync.last_error;
  if (fullResync.last_resync_at) return "Letzter vollständiger Resync: " + formatTime(fullResync.last_resync_at);
  return "Löscht nur lokale Intervals.icu-Daten; die Cloud bleibt unverändert.";
}

function renderIntervalsSyncControls(data, configured) {
  const fullResync = data.provider_resync?.intervals || {};
  const fullRunning = Boolean(fullResync.running || state.localSync.intervalsFull);
  const syncRunning = intervalsSyncRunning(data, fullRunning);
  const syncButton = $("#systemIntervalsSyncButton");
  if (syncButton) {
    syncButton.disabled = syncRunning;
    syncButton.textContent = data.sync?.running || state.localSync.intervals ? "Synchronisierung läuft…" : "Synchronisieren";
  }
  const fullButton = $("#systemIntervalsFullResyncButton");
  if (fullButton) {
    fullButton.disabled = !configured.intervals || fullRunning || Boolean(data.sync?.running || state.localSync.intervals);
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  const status = $("#intervalsFullResyncStatus");
  if (status) {
    status.classList.toggle("error", Boolean(fullResync.last_error));
    status.textContent = intervalsFullResyncText(fullResync, fullRunning);
  }
}

function renderGarminSyncControl(data) {
  const button = $("#garminSyncButton");
  if (!button) return;
  const running = Boolean(data.garmin_sync?.running || state.localSync.garmin);
  button.disabled = running;
  button.textContent = running ? "Synchronisierung läuft…" : "Garmin synchronisieren";
}

function renderSettingsSyncControls(data, configured) {
  renderIntervalsSyncControls(data, configured);
  renderGarminSyncControl(data);
}

function renderSettingsUsage(data, activeProvider) {
  const usage = data.usage || {};
  const providerLabel = activeProvider === "gemini" ? "Gemini" : "OpenAI";
  const usageNode = $("#usageSummary");
  if (usageNode) {
    const rateLimits = usage.rate_limits || {};
    const remaining = rateLimits.remaining_requests != null || rateLimits.remaining_tokens != null
      ? ` · Restkontingent im aktuellen Anbieterfenster: ${rateLimits.remaining_requests ?? "?"} Anfragen / ${rateLimits.remaining_tokens ?? "?"} Tokens`
      : " · Restkontingent wird nach einem API-Aufruf angezeigt";
    const error = usage.status?.state === "error" ? ` · Status: ${usage.status.message || "Fehler bei letzter Anfrage"}` : "";
    usageNode.textContent = `${providerLabel} heute: ${usage.requests || 0} Anfragen · ${usage.total_tokens || 0} Tokens${remaining}${error}`;
  }
  const privacy = $("#privacySummary");
  if (privacy) privacy.textContent = `${usage.requests || 0} ${providerLabel}-Anfragen heute`;
}

function garminConnectionLabel(garmin, running) {
  if (!garmin.configured) return "Nicht konfiguriert";
  if (running) return "Synchronisierung läuft…";
  return garmin.source === "fixture" ? "Lokale Testdatei aktiv" : "Konfiguriert";
}

function renderConnectionsSummary(openaiHealthy, geminiHealthy, intervalsHealthy, garminConfigured, weatherConfigured) {
  const connections = $("#connectionsSummary");
  if (!connections) return;
  const values = [["OpenAI", openaiHealthy], ["Gemini", geminiHealthy], ["Intervals", intervalsHealthy], ["Garmin", garminConfigured], ["Open-Meteo", weatherConfigured]];
  connections.textContent = values.map(([label, active]) => `${label} ${active ? "✓" : "–"}`).join(" · ");
}

function renderSettings(data) {
  const configured = data.configured || {};
  const activeProvider = data.ai_provider?.selected || "openai";
  const status = data.usage?.status || {};
  const openaiHealthy = renderAiConnection("openai", configured.openai, activeProvider, status);
  const geminiHealthy = renderAiConnection("gemini", configured.gemini, activeProvider, status);
  const intervalsHealthy = renderIntervalsConnection(data, configured);
  const garmin = data.garmin || {};
  const garminRunning = Boolean(data.garmin_sync?.running || state.localSync.garmin);
  settingsStatus("#garminConnectionStatus", garmin.configured, garminConnectionLabel(garmin, garminRunning));
  renderWeatherConnection(data.weather || {});
  renderConnectionsSummary(openaiHealthy, geminiHealthy, intervalsHealthy, garmin.configured, data.weather?.configured);
  renderSettingsInputs(data);
  renderSettingsSyncControls(data, configured);
  renderSettingsUsage(data, activeProvider);
  renderNotificationStatus();
  renderProviderAttention(data);
  renderConnectionsSyncProgress(data);
  renderProviderFreshness(data);
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

function render(data) {
  const firstRender = !state.data;
  state.data = data;
  renderAppVersion(data.app);
  renderCoachOverview(data);
  renderCoachReceipts();
  renderQuickMessageTemplates();
  notifyState(data);
  renderStatus(data);
  renderMessages(data.messages, firstRender);
  renderActivities(data.activities || []);
  renderPlanned(data.training_calendar || data.planned || []);
  renderLibrary(data.library || []);
  renderProfile(data.profile);
  renderCheckins(data.checkins || data.local_feedback?.recent || [], data.profile?.timezone);
  renderGarmin(data.garmin);
  renderAdaptivePlanning(data);
  renderExternalCalendar(data);
  renderPerformance(data.performance);
  renderAiProvider(data.ai_provider);
  renderModel(data.model);
  renderThinkingLevel(data.thinking_level);
  renderDiagnosticCapture(data.diagnostic_capture);
  renderSettings(data);
  updateVoiceButton();
  updateHeaderAction();
}

function latestAssistantMessageKey(messages) {
  const message = [...(messages || [])].reverse().find((entry) => entry.role === "assistant");
  if (!message) return null;
  if (message.id != null) return `id:${message.id}`;
  return `fallback:${message.created_at || ""}:${message.content || ""}`;
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
    ["messages", "messages_next_cursor", "activities", "activities_next_cursor", "library", "library_next_cursor", "plans", "planned", "training_calendar", "planning_view", "planning_compliance", "weather", "parallel_cycling", "daily_planning_context", "planning", "performance", "garmin", "checkins", "local_feedback", "activity_feedback"].forEach((key) => {
      if (existing[key] !== undefined) payload[key] = existing[key];
    });
    const areas = new Set(requestedAreas || ["chat", "activities", "plan", "library", "performance", "feedback", "profile"]);
    const requests = [];
    if (areas.has("chat")) requests.push(["chat", api("/api/chat/history?limit=100")]);
    if (areas.has("activities")) requests.push(["activities", api("/api/activities?limit=250")]);
    if (areas.has("plan")) requests.push(["plan", api(`/api/plan${query}`)]);
    if (areas.has("weather") && !areas.has("plan")) requests.push(["weather", api(`/api/weather${query}`)]);
    if (areas.has("library")) requests.push(["library", api("/api/library?limit=100")]);
    if (areas.has("performance")) requests.push(["performance", api("/api/performance")]);
    if (areas.has("feedback")) requests.push(["feedback", api("/api/feedback")]);
    if (areas.has("profile")) requests.push(["profile", api("/api/profile")]);
    const domainData = Promise.all(requests.map(async ([area, request]) => {
      try { return [area, await request, null]; }
      catch (error) { return [area, null, error]; }
    }));
    if (initialLoad && requestSequence === state.loadSequence) {
      render(payload);
      finishAppShellLoading();
    }
    const results = await domainData;
    if (sessionGeneration !== state.sessionGeneration || requestSequence !== state.loadSequence) return;
    // Incorporate changes that arrived while these requests were in flight.
    payload.messages = state.data?.messages || [];
    const failures = [];
    const appliedAreas = [];
    results.forEach(([area, result, error]) => {
      if (area === "chat" && chatGeneration !== state.chatGeneration) return;
      if (error) { failures.push(`${area}: ${error.message}`); return; }
      if (area === "chat") {
        if (!Array.isArray(result.messages)) throw new Error("Die Nachrichtenbestätigung fehlt.");
        const previousAssistantKey = latestAssistantMessageKey(payload.messages);
        const generationChanged = state.data?.messages_generation !== undefined && result.generation !== state.data.messages_generation;
        const currentTurn = state.chatRequest?.clientTurnId;
        const currentTurnRetained = currentTurn && result.messages.some((message) => message.client_turn_id === currentTurn);
        if (generationChanged) {
          state.coachActionProposals = [];
          state.coachReceipts = [];
          if (!currentTurnRetained) {
            if (state.chatRequest?.message) {
              state.rejectedMessages.push({ role: "user", content: state.chatRequest.message, client_turn_id: currentTurn,
                error: "Der Chat wurde zurückgesetzt. Prüfe den Verlauf, bevor du diese Nachricht erneut sendest." });
            }
            state.chatGeneration += 1;
            state.chatStream?.controller.abort();
            state.chatStream = null;
            state.chatRequest = null;
            state.chatServerOperationId = null;
            state.busy = false;
            rememberChatTurn(null);
          }
        }
        const retainedMessages = generationChanged
          ? (state.data?.messages || []).filter((message) => currentTurnRetained && message.client_turn_id === currentTurn)
          : undefined;
        const messages = mergeChatMessages(result.messages, retainedMessages);
        payload.messages_generation = result.generation;

        const nextAssistantKey = latestAssistantMessageKey(messages);
        if (state.initialStateLoaded && baseRoute() !== "coach" && nextAssistantKey && nextAssistantKey !== previousAssistantKey) {
          state.chatResponseScrollPending = true;
          const nextAssistant = [...messages].reverse().find((message) => message.role === "assistant");
          state.chatResponseMessageId = nextAssistant?.id ?? null;
        }
        Object.assign(payload, { messages, messages_next_cursor: result.next_cursor });
        if (chatContentVersion === state.chatContentVersion && Array.isArray(result.proposed_actions)) {
          state.coachActionProposals = result.proposed_actions;
          state.chatProposalRefreshPending = false;
        }
      }
      if (area === "activities") Object.assign(payload, { activities: result.activities || [], activities_next_cursor: result.next_cursor });
      if (area === "plan") Object.assign(payload, result);
      if (area === "weather") Object.assign(payload, { weather: result });
      if (area === "library") Object.assign(payload, { library: result.workouts || [], library_next_cursor: result.next_cursor });
      if (area === "performance") Object.assign(payload, result);
      if (area === "feedback") Object.assign(payload, result);
      if (area === "profile") Object.assign(payload, { profile: result.profile || bootstrap.profile, competitions: result.competitions || bootstrap.competitions });
      state.loadedAreas.add(area);
      appliedAreas.push(area);
    });
    payload.state_versions = { ...state.data?.state_versions };
    for (const area of appliedAreas) {
      if (area === "chat" && chatGeneration !== state.chatGeneration) continue;
      const versionKeys = { feedback: ["checkins", "activity_feedback"], performance: ["performance", "garmin"] }[area] || [area];
      for (const key of versionKeys) {
        if (bootstrap.state_versions?.[key] !== undefined) payload.state_versions[key] = bootstrap.state_versions[key];
      }
    }
    if (requestSequence === state.loadSequence) render(payload);
    if (failures.length) throw new Error(failures.join("; "));
  } catch (error) {
    if (sessionGeneration !== state.sessionGeneration || /Authentication/.test(error.message)) return;
    const statusCard = $("#statusCard");
    statusCard.hidden = false;
    statusCard.classList.add("warning");
    $("#statusTitle").textContent = "Trainingsdaten konnten nicht geladen werden";
    $("#statusDetail").textContent = error.message;
    toast(error.message, true);
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

function scheduleChatStatusPoll(delay = 1_500) {
  if (state.chatStatusTimer) clearTimeout(state.chatStatusTimer);
  state.chatStatusTimer = setTimeout(() => {
    state.chatStatusTimer = null;
    pollChatStatus();
  }, delay);
}

async function loadChatHistoryFresh() {
  const pendingLoad = state.loadPromise;
  if (pendingLoad) await pendingLoad.catch(() => {});
  await load("/api/bootstrap", ["chat"]);
}

async function refreshChatProposalsInBackground(expectedContentVersion) {
  if (baseRoute() !== "coach") return;
  if (state.chatProposalRefreshInFlight) {
    state.chatProposalRefreshQueued = true;
    return;
  }
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  state.chatProposalRefreshInFlight = true;
  try {
    const result = await api("/api/chat/history?limit=100");
    if (sessionGeneration !== state.sessionGeneration
      || chatGeneration !== state.chatGeneration
      || expectedContentVersion !== state.chatContentVersion
      || !Array.isArray(result.proposed_actions)) return;
    state.coachActionProposals = result.proposed_actions;
    state.chatProposalRefreshPending = false;
    renderCoachActionReview();
    renderMessages(state.data?.messages || [], false);
  } catch (_) {
    // Keep the pending flag so the next completed turn retries the authoritative refresh.
  } finally {
    state.chatProposalRefreshInFlight = false;
    const retryAtLatestVersion = state.chatProposalRefreshPending && state.chatProposalRefreshQueued;
    state.chatProposalRefreshQueued = false;
    if (retryAtLatestVersion && baseRoute() === "coach") void refreshChatProposalsInBackground(state.chatContentVersion);
  }
}

async function resumeQueuedChat() {
  if (!state.chatQueue.length || state.chatRequest || state.chatServerOperationId) {
    if (!state.chatQueue.length && !state.chatRequest && !state.chatServerOperationId) {
      state.busy = false;
      renderQuickMessageTemplates();
      renderMessages(state.data?.messages || [], true);
      updateChatControls();
    }
    return;
  }
  const next = state.chatQueue.shift();
  renderMessages(state.data?.messages || [], true);
  try {
    await drainChatQueue(next.message, next.requestKind, next.attachments);
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (!state.chatRequest && !state.chatServerOperationId) state.busy = false;
    renderQuickMessageTemplates();
    renderMessages(state.data?.messages || [], true);
    updateChatControls();
  }
}

function chatPollStateIsCurrent(sessionGeneration, chatGeneration) {
  return sessionGeneration === state.sessionGeneration && chatGeneration === state.chatGeneration;
}

function pendingChatTurn() {
  if (state.chatRequest?.clientTurnId) return state.chatRequest.clientTurnId;
  try {
    return sessionStorage.getItem("coachPendingTurn");
  } catch {
    return null;
  }
}

async function pollPendingChatReceipt(clientTurnId, sessionGeneration, chatGeneration) {
  if (!clientTurnId || state.chatStream) return { running: false, stale: false };
  try {
    const receipt = await api(`/api/chat/receipt?client_turn_id=${encodeURIComponent(clientTurnId)}`);
    if (!chatPollStateIsCurrent(sessionGeneration, chatGeneration)) return { running: false, stale: true };
    if (["running", "queued"].includes(receipt.status)) {
      if (!state.chatRequest) state.chatRequest = { phase: "recovering", clientTurnId, message: null };
      return { running: true, stale: false };
    }
    applyChatReceipt(receipt);
    rememberChatTurn(null);
    return { running: false, stale: false };
  } catch (error) {
    if (!chatPollStateIsCurrent(sessionGeneration, chatGeneration)) return { running: false, stale: true };
    if (![403, 404].includes(error.status)) throw error;
    rememberChatTurn(null);
    const request = state.chatRequest;
    if (request?.message) {
      state.rejectedMessages.push({ role: "user", content: request.message, client_turn_id: clientTurnId,
        error: "Die Nachricht wurde nicht angenommen. Bitte erneut senden." });
    }
    return { running: false, stale: false };
  }
}

function showRunningChatStatus(status) {
  state.chatServerOperationId = status.operation_id || null;
  if (!state.chatRequest) {
    state.chatRequest = { phase: "recovering", operationId: state.chatServerOperationId, message: null, background: status.mode === "background" };
  } else if (state.chatRequest.phase === "recovering") {
    state.chatRequest.operationId = state.chatServerOperationId;
    state.chatRequest.background = status.mode === "background";
  }
  if (!state.busy) {
    state.busy = true;
    renderQuickMessageTemplates();
    updateChatControls();
    renderMessages(state.data.messages || [], true);
  }
}

async function finishRecoveredChatStatus() {
  if (state.chatStream) return;
  const request = state.chatRequest;
  state.chatServerOperationId = null;
  if (request?.phase !== "recovering") return;
  await loadChatHistoryFresh();
  if (state.chatRequest !== request) return;
  state.chatRequest = null;
  state.busy = Boolean(state.chatQueue.length);
  state.chatStreamText = "";
  state.chatResponseStarted = false;
  state.chatResponseScrollPending = true;
  renderQuickMessageTemplates();
  renderMessages(state.data?.messages || [], true);
  updateChatControls();
  void resumeQueuedChat();
  scrollChatToResponseStart();
}

async function pollChatStatus() {
  if (!state.data || document.visibilityState !== "visible" || !navigator.onLine) {
    scheduleChatStatusPoll(5_000);
    return;
  }
  if (state.chatStatusPollInFlight) return;
  const pollRequest = {};
  state.chatStatusPollInFlight = pollRequest;
  let running = false;
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  try {
    const receiptState = await pollPendingChatReceipt(pendingChatTurn(), sessionGeneration, chatGeneration);
    if (receiptState.stale) return;
    const status = await api("/api/chat/status");
    if (!chatPollStateIsCurrent(sessionGeneration, chatGeneration)) return;
    running = receiptState.running || status.status === "running";
    if (running) showRunningChatStatus(status);
    else await finishRecoveredChatStatus();
  } catch (error) {
    if (state.chatStatusPollInFlight === pollRequest && !/Authentication/.test(error.message)) scheduleChatStatusPoll(5_000);
  } finally {
    if (state.chatStatusPollInFlight === pollRequest) {
      state.chatStatusPollInFlight = null;
      scheduleChatStatusPoll(running ? 1_500 : 5_000);
    }
  }
}

async function loadInitialState() {
  const sessionGeneration = state.sessionGeneration;
  state.initialStateLoaded = false;
  const route = routeFromHash();
  state.planSegment = planSegmentFromRoute(route);
  state.analysisSegment = analysisSegmentFromRoute(route);
  const areas = ["chat", "activities", "performance", "feedback", "profile"];
  areas.push("weather");
  if (baseRoute(route) === "plan") areas.push("plan", "library");
  await load("/api/bootstrap?local=1", areas);
  if (sessionGeneration !== state.sessionGeneration) return;
  state.initialStateLoaded = true;
  if (state.chatInitialScrollPending && baseRoute() === "coach") scrollChatToLatest();
  if (state.data?.profile?.weather_location) {
    await load("/api/bootstrap", state.loadedAreas.has("plan") ? ["plan"] : ["weather"]);
  }
  connectStateEvents();
  scheduleChatStatusPoll(0);
}

function queueChatMessage(message, mode, requestKind = null, attachments = []) {
  const queuedAttachmentBytes = state.chatQueue.reduce((total, entry) => total + (entry.attachments || []).reduce((bytes, item) => bytes + String(item.data || "").length, 0), 0);
  const attachmentBytes = attachments.reduce((total, item) => total + String(item.data || "").length, 0);
  if (queuedAttachmentBytes + attachmentBytes > MAX_QUEUED_ATTACHMENT_BYTES) {
    state.chatAttachments = attachments;
    renderChatAttachments();
    toast("Die Warteschlange enthält bereits zu viele Bilddaten. Warte auf die laufende Coach-Antwort.", true);
    return false;
  }
  state.chatQueue[mode === "steer" ? "unshift" : "push"]({
    id: ++state.chatQueueSequence,
    message,
    mode,
    requestKind,
    attachments,
  });
  const input = $("#messageInput");
  input.value = "";
  state.chatDraftDirty = false;
  input.style.height = "auto";
  renderMessages(state.data?.messages || [], true);
  updateChatControls();
  return true;
}

function chatRequestIsCurrent(sessionGeneration, chatGeneration) {
  return sessionGeneration === state.sessionGeneration && chatGeneration === state.chatGeneration;
}

async function chatStreamResponse(message, requestKind, attachments, clientTurnId, stream) {
  return fetch("/api/chat/stream", {
    method: "POST",
    credentials: "same-origin",
    signal: stream.controller.signal,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": cookie("ic_csrf") },
    body: JSON.stringify({ message, client_turn_id: clientTurnId, request_kind: requestKind, attachments }),
  });
}

async function rejectChatStreamResponse(response, context) {
  const { attachments, chatGeneration, clientTurnId, message, sessionGeneration, stream } = context;
  stream.serverError = true;
  stream.rejected = true;
  let payload = {};
  try { payload = await response.json(); } catch { }
  if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return false;
  if (response.status === 401) {
    const rejectedAttachments = [...(attachments || [])];
    showLogin();
    state.chatAttachments = rejectedAttachments;
    renderChatAttachments();
    const input = $("#messageInput");
    if (input.value.trim()) state.rejectedMessages.push({ role: "user", content: message, client_turn_id: clientTurnId, error: payload.error || "Bitte erneut anmelden." });
    else input.value = message;
    state.chatDraftDirty = true;
    toast(payload.error || "Bitte erneut anmelden; der Entwurf bleibt erhalten.", true);
  }
  throw globalThis.AppApi.responseError(response, typeof payload.error === "string" ? payload.error : `Anfrage fehlgeschlagen (${response.status})`, payload.reason || "http_error");
}

function parseChatStreamEvent(block) {
  let event = "message";
  const data = [];
  for (const line of block.replaceAll("\r", "").split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, payload: JSON.parse(data.join("\n")) } : null;
}

function applyStartedChatStreamEvent(payload, context) {
  const { request, stream } = context;
  stream.operationId = payload.operation_id || null;
  request.operationId = stream.operationId;
  state.chatServerOperationId = stream.operationId;
  if (stream.cancelRequested) void cancelChat();
}

function applyDeltaChatStreamEvent(payload) {
  const responseJustStarted = !state.chatStreamText;
  state.chatStreamText += payload.text || "";
  state.chatResponseStarted = state.chatResponseStarted || responseJustStarted;
  if (responseJustStarted) state.chatResponseScrollPending = true;
  scheduleChatStreamRender(responseJustStarted);
}

function applyBackgroundChatStreamEvent(payload, context) {
  const { request, stream } = context;
  context.background = true;
  request.background = true;
  request.phase = "recovering";
  stream.operationId = payload.operation_id || stream.operationId;
  request.operationId = stream.operationId;
  state.chatServerOperationId = stream.operationId;
  renderMessages(state.data?.messages || [], false);
  updateChatControls();
}

function applyCompletedChatStreamEvent(payload, context) {
  const { clientTurnId, request } = context;
  cancelScheduledChatStreamRender();
  context.completed = true;
  context.completedPayload = payload;
  state.chatContentVersion += 1;
  rememberChatTurn(null);
  request.phase = "reconciling";
  request.responseMessageId = payload.message?.id || null;
  state.chatResponseMessageId = request.responseMessageId;
  request.responseMessageReceived = reconcileCompletedChatMessage(payload.message ? { ...payload.message, client_turn_id: clientTurnId } : null);
  if (request.responseMessageReceived) state.chatStreamText = "";
  request.hadOutstandingProposals = Array.isArray(state.coachActionProposals) && state.coachActionProposals.length > 0;
  if (request.hadOutstandingProposals) state.chatProposalRefreshPending = true;
  state.coachActionProposals = Array.isArray(payload?.proposed_actions) ? payload.proposed_actions : [];
  if (payload?.coach_quick_actions && state.data) {
    state.data.coach_quick_actions = payload.coach_quick_actions;
    renderCoachOverview(state.data);
  }
  addStructuredCoachReceipts(payload);
  renderMessages(state.data?.messages || [], false);
  updateChatControls();
}

function applyChatStreamEvent(event, payload, context) {
  if (event === "started") return applyStartedChatStreamEvent(payload, context);
  if (event === "delta") return applyDeltaChatStreamEvent(payload);
  if (event === "background") return applyBackgroundChatStreamEvent(payload, context);
  if (event === "completed") return applyCompletedChatStreamEvent(payload, context);
  if (event === "error") {
    context.stream.serverError = true;
    if (!context.background) context.stream.rejected = true;
    const error = new Error(payload.message || "Die Coach-Anfrage ist fehlgeschlagen.");
    error.reason = payload.reason;
    throw error;
  }
}

function consumeChatStreamBlock(block, context) {
  if (!chatRequestIsCurrent(context.sessionGeneration, context.chatGeneration)) return;
  const parsed = parseChatStreamEvent(block);
  if (parsed) applyChatStreamEvent(parsed.event, parsed.payload, context);
}

async function readChatStream(response, context) {
  if (!response.body) throw new Error("Der Browser unterstützt keinen Antwort-Stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) consumeChatStreamBlock(block, context);
    // The chat endpoint is a finite SSE response. A proxy may keep the HTTP
    // connection open after the terminal event, so release the reader as
    // soon as the persisted result has arrived instead of trapping the
    // composer in the reconciling state.
    if (context.completed || context.background) {
      await reader.cancel().catch(() => {});
      break;
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) consumeChatStreamBlock(buffer, context);
}

async function refreshCompletedChatStream(context) {
  const { completedPayload, request } = context;
  const hasPersistedReceipt = request.responseMessageReceived || Boolean(completedPayload?.message?.content && state.data);
  if (hasPersistedReceipt) {
    if (state.chatProposalRefreshPending && baseRoute() === "coach") void refreshChatProposalsInBackground(state.chatContentVersion);
    return;
  }
  await loadChatHistoryFresh();
}

async function finishChatStream(context) {
  const { completed, stream } = context;
  if (context.background) {
    scheduleChatStatusPoll(0);
    return "recovering";
  }
  if (!completed && !stream.cancelRequested) throw new Error("Der Antwort-Stream wurde unerwartet beendet.");
  await refreshCompletedChatStream(context);
  if (completed) scrollChatToResponseStart();
  invalidateContextPreview();
  return completed ? "completed" : "failed";
}

async function recoverChatRequestFailure(error, context) {
  const { attachments, chatGeneration, clientTurnId, completed, message, request, sessionGeneration, stream } = context;
  if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return false;
  cancelScheduledChatStreamRender();
  if (stream.rejected) {
    rememberChatTurn(null);
    const input = $("#messageInput");
    if (input.value.trim()) {
      const failed = state.data.messages.find((entry) => entry.optimistic && entry.client_turn_id === clientTurnId);
      if (failed) { failed.error = error.message; failed.attachments = attachments; }
    } else {
      state.data.messages = (state.data.messages || []).filter((entry) => !(entry.optimistic && entry.client_turn_id === clientTurnId));
      input.value = message;
      state.chatAttachments = [...attachments, ...(state.chatAttachments || [])];
      renderChatAttachments();
    }
    state.chatDraftDirty = true;
    toast(error.message, true);
    return false;
  }
  const cancelled = stream.cancelRequested || error?.name === "AbortError" || error?.reason === "chat_cancelled";
  if (!completed && !stream.serverError) {
    request.phase = "recovering";
    state.chatServerOperationId = stream.operationId || state.chatServerOperationId;
    if (state.chatStream === stream) state.chatStream = null;
    renderMessages(state.data?.messages || [], false);
    updateChatControls();
    scheduleChatStatusPoll(0);
    return "recovering";
  }
  if (!cancelled) toast(error.message, true);
  scheduleChatStatusPoll(0);
  await loadChatHistoryFresh();
  invalidateContextPreview();
  return false;
}

function finishChatRequest(context) {
  const { chatGeneration, completed, request, sessionGeneration, stream } = context;
  if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return;
  if (state.chatStream === stream) state.chatStream = null;
  if (request.phase !== "recovering") {
    cancelScheduledChatStreamRender();
    state.chatStreamText = "";
  }
  if (!completed && request.phase !== "recovering") state.chatResponseScrollPending = false;
  if (!completed && request.phase !== "recovering") state.chatResponseMessageId = null;
  state.chatResponseStarted = false;
  if (state.chatRequest === request && request.phase !== "recovering") state.chatRequest = null;
  if (request.phase !== "recovering") state.chatServerOperationId = null;
  updateChatControls();
}

async function requestCoachResponse(message, requestKind = null, attachments = []) {
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  const clientTurnId = secureToken("turn");
  if (state.data) {
    state.data.messages = mergeChatMessages([{ role: "user", content: message, attachment_names: JSON.stringify(attachments.map(item => item.name)), client_turn_id: clientTurnId, created_at: new Date().toISOString(), optimistic: true }]);
    renderMessages(state.data.messages, true);
  }
  state.chatStreamText = "";
  rememberChatTurn(clientTurnId);
  const request = { phase: "running", message, clientTurnId, operationId: null, responseMessageId: null, responseMessageReceived: false, cancelRequested: false };
  state.chatRequest = request;
  const stream = { controller: new AbortController(), operationId: null, cancelRequested: false, request, serverError: false };
  state.chatStream = stream;
  updateChatControls();
  renderMessages(state.data?.messages || [], true);
  const context = { attachments, background: false, chatGeneration, clientTurnId, completed: false, completedPayload: null, message, request, sessionGeneration, stream };
  try {
    const response = await chatStreamResponse(message, requestKind, attachments, clientTurnId, stream);
    if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return false;
    if (!response.ok) {
      await rejectChatStreamResponse(response, context);
      return false;
    }
    await readChatStream(response, context);
    return await finishChatStream(context);
  } catch (error) {
    return await recoverChatRequestFailure(error, context);
  } finally {
    finishChatRequest(context);
  }
}

async function drainChatQueue(firstMessage, requestKind = null, attachments = []) {
  const firstResult = await requestCoachResponse(firstMessage, requestKind, attachments);
  if (firstResult !== "completed") return firstResult;
  while (state.chatQueue.length) {
    const next = state.chatQueue.shift();
    renderMessages(state.data?.messages || [], true);
    if (await requestCoachResponse(next.message, next.requestKind, next.attachments) !== "completed") return;
  }
  return "completed";
}

async function cancelChat() {
  const stream = state.chatStream;
  const operationId = stream?.operationId || state.chatServerOperationId;
  if (stream) stream.cancelRequested = true;
  if (state.chatRequest) state.chatRequest.cancelRequested = true;
  if (!operationId) { updateChatControls(); return; }
  if (state.chatRequest) {
    state.chatRequest.cancelRequested = true;
    state.chatRequest.phase = "recovering";
  }
  await api("/api/chat/cancel", {
    method: "POST",
    body: JSON.stringify({ operation_id: operationId }),
  }).catch(() => {});
  stream?.controller.abort();
  scheduleChatStatusPoll(0);
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const attachments = state.chatAttachments || [];
  const message = input.value.trim() || (attachments.length ? "Bitte analysiere die angehängten Dateien." : "");
  const requestKind = input.dataset.requestKind || null;
  if (state.chatAttachmentsLoading || !message || voiceIsRecording() || state.voiceTranscribing) return;
  state.chatAttachments = [];
  renderChatAttachments();
  if (state.chatRequest || state.chatServerOperationId) {
    if (state.busy) queueChatMessage(message, "queue", requestKind, attachments);
    return;
  }
  if (state.busy) {
    queueChatMessage(message, "queue", requestKind, attachments);
    return;
  }
  state.busy = true;
  state.quickTemplatesVisible = false;
  renderQuickMessageTemplates();
  input.value = "";
  delete input.dataset.requestKind;
  state.chatDraftDirty = false;
  input.style.height = "auto";
  updateChatControls();
  updateVoiceButton();
  try {
    await drainChatQueue(message, requestKind, attachments);
  } finally {
    if (!state.chatRequest && !state.chatServerOperationId) state.busy = false;
    updateChatControls();
    renderMessages(state.data?.messages || [], false, true);
    updateVoiceButton();
    if ($("#chatPanel")?.classList.contains("active") && document.visibilityState === "visible" && shouldRestoreChatInputFocus()) {
      input.focus({ preventScroll: true });
    }
  }
}

function steerCurrentChat(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if ((state.chatAttachments || []).length) { toast("Bitte Anhänge mit Senden in die Warteschlange stellen.", true); return; }
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
    if (!result.id) throw new Error("Die Jobbestätigung fehlt.");
    const completed = await waitForSyncJob(result.id);
    if (completed.status !== "completed") throw new Error(completed.error_detail || "Synchronisierung nicht vollständig abgeschlossen.");
    toast("Aktualisierung abgeschlossen");
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.intervals = false; button.disabled = false; button.classList.remove("busy"); button.textContent = defaultCaption; updateHeaderAction(); }
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
    const completed = await waitForSyncJob(result.id);
    if (completed.status === "failed") throw new Error(completed.error_class || "Garmin-Synchronisierung fehlgeschlagen.");
    toast(`Garmin ${completed.status === "partial" ? "teilweise " : ""}synchronisiert`);
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
    const completed = await waitForSyncJob(result.id);
    if (completed.status === "failed") throw new Error(completed.error_class || "Kalender-Synchronisierung fehlgeschlagen.");
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
    if (completed.status === "failed") throw new Error(completed.error_class || "Wetter-Synchronisierung fehlgeschlagen.");
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
    updateHeaderAction();
  }
}

async function resetCoachChat() {
  const buttons = [$("#openaiChatResetButton"), $("#chatResetButton")].filter(Boolean);
  if (!buttons.length || !await requestConfirmation("Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen?", { title: "Coach-Chat zurücksetzen?" })) return;
  buttons.forEach((button) => {
    button.disabled = true;
    button.textContent = "Wird zurückgesetzt…";
  });
  try {
    const reset = await api("/api/chat/reset", { method: "POST", body: "{}" });
    state.chatAttachments = [];
    renderChatAttachments();
    if (state.data) state.data.messages_generation = reset.generation;
    state.chatGeneration += 1;
    state.chatStatusPollInFlight = null;
    scheduleChatStatusPoll(0);
    state.rejectedMessages = [];
    state.chatStream?.controller.abort();
    state.chatStream = null;
    rememberChatTurn(null);
    if (state.data) {
      state.data.messages = [];
      state.chatQueue = [];
      state.chatRequest = null;
      state.chatStreamText = "";
      state.chatServerOperationId = null;
      state.chatResponseStarted = false;
      state.chatResponseScrollPending = false;
      state.chatResponseMessageId = null;
      state.chatScrollY = null;
      cancelScheduledChatStreamRender();
      renderMessages([], true);
    }
    state.busy = false;
    updateChatControls();
    updateVoiceButton();
    toast("Neuer Coach-Chat gestartet");
  } catch (error) { toast(error.message, true); }
  finally {
    buttons.forEach((button) => {
      button.disabled = false;
      button.textContent = "Chat zurücksetzen";
    });
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
    toast("Athletenprofil gespeichert und für den Coach aktiviert");
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
    toast(error.message, true);
  }
  finally {
    if (button) { button.disabled = false; button.textContent = "Tages-Check-in speichern"; }
  }
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
  if (!file || !await requestConfirmation("Das aktuelle Datenbank-Backup wird vorher gesichert und durch die ausgewählte Datei ersetzt. Fortfahren?", { title: "Datenbank-Backup wiederherstellen?" })) return;
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

async function saveAiProvider(event) {
  const select = event.currentTarget;
  select.disabled = true;
  try {
    const result = await api("/api/settings/ai-provider", { method: "PUT", body: JSON.stringify({ provider: select.value }) });
    if (result?.provider && Array.isArray(result.model_options)) {
      const provider = { ...state.data?.ai_provider, selected: result.provider };
      const model = { selected: result.model, options: result.model_options };
      state.data = { ...state.data, ai_provider: provider, model };
      renderAiProvider(provider);
      renderModel(model);
      renderThinkingLevel(state.data.thinking_level);
    }
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

function renderDiagnosticCapture(capture = {}) {
  const toggle = $("#diagnosticCaptureToggle");
  const status = $("#diagnosticCaptureStatus");
  if (!toggle || !status) return;
  const active = Boolean(capture.active);
  toggle.checked = active;
  if (active) {
    const entries = Number(capture.entries || 0);
    status.textContent = `Aktiv bis ${formatTime(capture.expires_at)} · ${entries} technische Einträge gespeichert. Es werden nur Antwortformen und technische Metadaten gespeichert; keine Antwortinhalte, Athletendaten, Zugangsdaten oder Tokens.`;
  } else {
    status.textContent = "Aus. Antwortinhalte und Athletendaten werden nicht aufgezeichnet.";
  }
}

async function setDiagnosticCapture(event) {
  const toggle = event.currentTarget;
  const previous = !toggle.checked;
  toggle.disabled = true;
  try {
    const capture = await api("/api/diagnostics/capture", {
      method: "POST",
      body: JSON.stringify({ enabled: toggle.checked }),
    });
    if (state.data) state.data.diagnostic_capture = capture;
    renderDiagnosticCapture(capture);
    toast(capture.active ? "Erweiterte technische Diagnose ist für eine Stunde aktiv" : "Erweiterte technische Diagnose beendet");
  } catch (error) {
    toggle.checked = previous;
    toast(error.message, true);
  } finally {
    toggle.disabled = false;
  }
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
  applyNavigationRoute(linkedRoute || link.dataset.route, { historyMode: "push" });
}));
document.querySelectorAll("[data-analysis-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  applyNavigationRoute(`analysis/${link.dataset.analysisSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("[data-plan-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  applyNavigationRoute(`plan/${link.dataset.planSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("[data-more-segment]").forEach((link) => link.addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  applyNavigationRoute(`more/${link.dataset.moreSegment}`, { historyMode: "push" });
}));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("close", () => restoreDialogFocus(dialog)));
globalThis.addEventListener("hashchange", syncNavigationRoute);

$("#loginForm").addEventListener("submit", login);
function renderChatAttachments() {
  const list = $("#chatAttachments");
  if (!list) return;
  list.replaceChildren();
  for (const [index, item] of (state.chatAttachments || []).entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = `${item.name} ×`;
    button.setAttribute("aria-label", `${item.name} entfernen`);
    button.addEventListener("click", () => {
      state.chatAttachments.splice(index, 1);
      renderChatAttachments();
      updateChatControls();
    });
    list.append(button);
  }
  list.hidden = !list.childElementCount;
  updateChatComposerVisibility();
}

$("#attachmentButton").addEventListener("click", () => $("#attachmentInput").click());
$("#attachmentInput").addEventListener("change", async (event) => {
  const files = [...event.target.files];
  event.target.value = "";
  if (!files.length || state.chatAttachmentsLoading) return;
  const generation = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  state.chatAttachmentsLoading = true;
  updateChatControls();
  try {
    if ((state.chatAttachments || []).length + files.length > 4 || files.some(file => !file.size || file.size > 5000000 || !/\.(gpx|fit|png|jpe?g|webp)$/i.test(file.name))) {
      throw new Error("Bis zu 4 GPX-, FIT-, PNG-, JPEG- oder WebP-Dateien mit je höchstens 5 MB auswählen.");
    }
    const attachments = await Promise.all(files.map(file => new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        if (typeof reader.result !== "string") {
          reject(new Error("Die Datei konnte nicht als Data-URL gelesen werden."));
          return;
        }
        resolve({ name: file.name, data: reader.result.split(",")[1] });
      };
      reader.onerror = () => reject(new Error("Die Datei konnte nicht gelesen werden."));
      reader.readAsDataURL(file);
    })));
    if (generation !== state.sessionGeneration || chatGeneration !== state.chatGeneration) return;
    state.chatAttachments = [...(state.chatAttachments || []), ...attachments];
    state.chatDraftDirty = true;
    renderChatAttachments();
    jumpToChatComposer();
  } catch (error) { toast(error.message, true); }
  finally { state.chatAttachmentsLoading = false; updateChatControls(); }
});

$("#chatForm").addEventListener("submit", sendMessage);
$("#steerButton").addEventListener("click", steerCurrentChat);
$("#cancelChatButton").addEventListener("click", cancelChat);
$("#quickMessageTemplates").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-message]");
  if (!button || state.busy) return;
  const input = $("#messageInput");
  input.value = button.dataset.message || "";
  if (button.dataset.requestKind) input.dataset.requestKind = button.dataset.requestKind;
  else delete input.dataset.requestKind;
  input.dispatchEvent(new Event("input"));
  $("#chatForm").requestSubmit();
});
$("#voiceButton").addEventListener("click", toggleVoiceInput);
$("#chatJumpToComposer").addEventListener("click", () => {
  jumpToChatComposer();
});
$("#headerActionButton").addEventListener("click", (event) => {
  if (event.currentTarget.dataset.action === "performance") refreshPerformance();
  else if (event.currentTarget.dataset.action === "activities") syncNow(event);
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
$("#coachAdaptivePlanningButton").addEventListener("click", () => askCoach("Prüfe meine nächsten geplanten Einheiten und schlage sinnvolle Anpassungen vor."));
$("#profileForm").addEventListener("input", () => { state.profileDirty = true; setDirtyIndicator("profileDirtyIndicator", true); });
$("#checkinForm").addEventListener("input", () => { state.checkinDirty = true; setDirtyIndicator("checkinDirtyIndicator", true); });
$("#modelSelect").addEventListener("change", saveModel);
$("#aiProviderSelect").addEventListener("change", saveAiProvider);
$("#thinkingLevelSelect").addEventListener("change", saveThinkingLevel);
$("#calendarDisplayForm").addEventListener("submit", saveCalendarDisplaySettings);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#diagnosticCaptureToggle").addEventListener("change", setDiagnosticCapture);
$("#logsRefreshButton").addEventListener("click", loadLogs);
$("#openaiChatResetButton").addEventListener("click", resetCoachChat);
$("#chatResetButton").addEventListener("click", resetCoachChat);
$("#privacyExportButton").addEventListener("click", downloadPrivacyExport);
$("#privacyDeleteButton").addEventListener("click", deletePrivacyData);
$("#changeHistoryRefreshButton").addEventListener("click", loadChangeHistory);
$("#notificationEnableButton").addEventListener("click", enableNotifications);
$("#backupDownloadButton").addEventListener("click", downloadDatabaseBackup);
$("#backupRestoreButton").addEventListener("click", restoreDatabaseBackup);
$("#logoutButton").addEventListener("click", logout);
$("#systemContextPreviewButton").addEventListener("click", () => {
  $("#systemContextPreviewButton").dataset.loaded = "false";
  loadContextPreview();
});
$("#messageInput").addEventListener("input", (event) => {
  const panel = $("#chatPanel");
  const keepComposerVisible = panel?.classList.contains("active")
    && !panel.classList.contains("chat-composer-hidden");
  state.chatDraftDirty = Boolean(event.target.value.trim());
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 150)}px`;
  updateChatControls();
  if (keepComposerVisible) {
    requestAnimationFrame(() => {
      globalThis.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
      updateChatComposerVisibility();
    });
  }
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
globalThis.addEventListener("scroll", handleWindowScroll, { passive: true });
globalThis.addEventListener("resize", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("orientationchange", scheduleMobileViewportLayout, { passive: true });
globalThis.addEventListener("pageshow", () => {
  connectStateEvents();
  scheduleMobileViewportLayout();
  if (state.chatInitialScrollPending && baseRoute() === "coach") scrollChatToLatest();
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
syncNavigationRoute();
bootstrapAuth();
