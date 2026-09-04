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
let mobileViewportFrame = null;
const mobileViewportBaselines = { portrait: 0, landscape: 0 };

function hasTouchFirstInput() {
  return Boolean(window.matchMedia?.("(hover: none) and (pointer: coarse)").matches);
}

function shouldRestoreChatInputFocus() {
  return Boolean(window.matchMedia?.("(hover: hover) and (pointer: fine)").matches);
}

function updateMobileViewportLayout() {
  mobileViewportFrame = null;
  const viewport = window.visualViewport;
  const viewportHeight = Math.max(1, Math.round(viewport?.height || window.innerHeight));
  const viewportWidth = Math.max(1, Math.round(viewport?.width || window.innerWidth));
  document.documentElement.style.setProperty("--app-viewport-height", `${viewportHeight}px`);
  const input = $("#messageInput");
  const inputFocused = document.activeElement === input;
  const screenOrientation = window.screen?.orientation?.type || "";
  const orientation = screenOrientation
    ? (screenOrientation.startsWith("landscape") ? "landscape" : "portrait")
    : ((window.screen?.width || viewportWidth) > (window.screen?.height || viewportHeight) ? "landscape" : "portrait");
  if (!inputFocused) mobileViewportBaselines[orientation] = viewportHeight;
  else if (!mobileViewportBaselines[orientation]) mobileViewportBaselines[orientation] = viewportHeight;
  const keyboardOpen = hasTouchFirstInput()
    && inputFocused
    && mobileViewportBaselines[orientation] - viewportHeight >= 100;
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
  if (route === "today") areas.add("plan");
  if (route === "plan") {
    areas.add("plan");
    areas.add("library");
  }
  return [...areas];
}

function ensureRouteData(route = state.route) {
  if (!state.data || state.loadPromise) return;
  const requested = [];
  const panelRoute = baseRoute(route);
  if (panelRoute === "today" && !state.loadedAreas.has("plan")) requested.push("plan");
  if (panelRoute === "plan" && !state.loadedAreas.has("plan")) requested.push("plan");
  if (panelRoute === "plan" && !state.loadedAreas.has("library")) requested.push("library");
  if (requested.length) load("/api/bootstrap?local=1", requested);
}

async function applyNavigationRoute(route, { historyMode = "none", focus = true } = {}) {
  const panelRoute = NAV_ROUTES[route] ? route : DEFAULT_NAV_ROUTE;
  const mainRoute = baseRoute(panelRoute);
  const navigationRoute = NAV_LINK_ROUTES[mainRoute] || mainRoute;
  const currentPanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  if (currentPanel !== NAV_ROUTES[panelRoute] && !(await confirmDiscardChanges())) return false;
  if (currentPanel !== NAV_ROUTES[panelRoute] && hasUnsavedChanges({ includeChatDraft: false })) discardUnsavedChanges();
  if (currentPanel === "chatPanel" && mainRoute !== "coach" && (state.chatRequest || state.chatServerOperationId)) {
    state.chatResponseScrollPending = true;
  }
  document.querySelectorAll(".nav-item, .panel").forEach((node) => node.classList.remove("active"));
  const navigation = document.querySelector(`.nav-item[data-route="${navigationRoute}"]`);
  const panel = document.querySelector(`#${NAV_ROUTES[panelRoute]}`);
  if (!navigation || !panel) return false;
  document.querySelectorAll(".nav-item").forEach((item) => item.removeAttribute("aria-current"));
  document.querySelectorAll(`.nav-item[data-route="${navigationRoute}"]`).forEach((item) => {
    item.classList.add("active");
    item.setAttribute("aria-current", "page");
  });
  panel.classList.add("active");
  state.route = panelRoute;
  if (mainRoute === "more") renderMoreSegments(moreSegmentFromRoute(panelRoute));
  if (mainRoute === "plan") renderPlanSegments(planSegmentFromRoute(panelRoute));
  if (mainRoute === "analysis") renderAnalysisSegments(analysisSegmentFromRoute(panelRoute));
  const targetHash = `#${panelRoute}`;
  if (window.location.hash !== targetHash) {
    if (historyMode === "push") window.history.pushState({ route: panelRoute }, "", targetHash);
    else if (historyMode === "replace") window.history.replaceState({ route: panelRoute }, "", targetHash);
  }
  if (state.data) renderStatus(state.data);
  updateHeaderAction();
  if (state.data && mainRoute === "more") loadContextPreview();
  if (state.data && mainRoute === "more") loadLogs();
  if (state.data && mainRoute === "more") loadChangeHistory();
  requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "auto" }));
  if (mainRoute === "coach") {
    if (state.chatResponseScrollPending) scrollChatToResponseStart();
    else scrollChatToLatest(true);
  }
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
  if (state.chatStatusTimer) clearTimeout(state.chatStatusTimer);
  state.chatStatusTimer = null;
  state.stateEventSource?.close();
  state.stateEventSource = null;
  if (state.stateEventReconnectTimer) clearTimeout(state.stateEventReconnectTimer);
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
  cancelScheduledChatStreamRender();
  state.loadedAreas.clear();
  state.planSegment = "overview";
  state.analysisSegment = "performance";
  state.profileDirty = false;
  state.checkinDirty = false;
  state.chatDraftDirty = false;
  state.activityFeedbackDirty.clear();
  state.activityFeedbackDrafts.clear();
  state.activityFromDate = "";
  state.activityToDate = "";
  state.activityVisibleCount = 250;
  setDirtyIndicator("activityDirtyIndicator", false);
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
  return window.AppApi.request(path, options, showLogin);
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
    provider: payload.status === "loading" ? [] : payload.area === "performance" ? ["performance"] : ["activities", "performance"],
    job: [],
    sync: ["activities", "performance", "plan", "library"],
  }[event.type];
  if (event.type === "sync" && !["completed", "error"].includes(payload.status)) return;
  if (areas?.length) scheduleStateEventRefresh(areas);
}

function scheduleStateEventReconnect() {
  if (state.stateEventReconnectTimer || !state.data || !navigator.onLine) return;
  const delay = state.stateEventBackoff;
  state.stateEventBackoff = Math.min(state.stateEventBackoff * 2, 30_000);
  state.stateEventReconnectTimer = setTimeout(() => {
    state.stateEventReconnectTimer = null;
    connectStateEvents();
  }, delay);
}

function connectStateEvents() {
  if (!state.data || !("EventSource" in window) || state.stateEventSource) return;
  const source = new EventSource(`/api/state/events?since=${encodeURIComponent(state.stateEventLastId)}`, { withCredentials: true });
  state.stateEventSource = source;
  source.onopen = () => { state.stateEventBackoff = 1000; };
  ["provider", "job", "planning", "coach", "sync", "reset"].forEach((name) => source.addEventListener(name, handleStateEvent));
  source.onerror = () => {
    if (state.stateEventSource !== source) return;
    source.close();
    state.stateEventSource = null;
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
    garmin: ["performance"],
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
    message: status.message || null,
    phase: status.phase || null,
    progress: progressPercentage(status.progress),
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

function renderConnectivityStatus(online = navigator.onLine) {
  const notice = $("#connectivityNotice");
  if (!notice) return;
  notice.hidden = online;
  notice.textContent = online ? "" : "Offline: Nur bereits geladene Daten sind verfügbar. Synchronisierung und Speichern warten auf die Verbindung.";
}

function setupConnectivityStatus() {
  renderConnectivityStatus();
  window.addEventListener("online", () => renderConnectivityStatus(true));
  window.addEventListener("offline", () => renderConnectivityStatus(false));
  window.addEventListener("online", () => connectStateEvents());
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

function updateChatControls() {
  const form = $("#chatForm");
  const input = $("#messageInput");
  const sendButton = $("#sendButton");
  const steerButton = $("#steerButton");
  const cancelButton = $("#cancelChatButton");
  const chatReady = Boolean(state.data && Array.isArray(state.data.messages));
  const hasDraft = Boolean(input?.value.trim());
  const inputAvailable = !voiceIsRecording() && !state.voiceTranscribing;
  const chatIsResuming = Boolean(state.chatRequest?.phase === "recovering" || (state.chatServerOperationId && !state.chatStream));
  const chatIsReconciling = state.chatRequest?.phase === "reconciling";
  if (form) {
    form.classList.toggle("is-busy", state.busy);
    form.classList.toggle("is-recovering", chatIsResuming);
    form.classList.toggle("is-reconciling", chatIsReconciling);
  }
  if (input) {
    input.disabled = !chatReady;
    input.placeholder = chatReady ? "Frage deinen Coach…" : "Coach-Chat wird geladen…";
  }
  if (sendButton) {
    sendButton.disabled = !chatReady || !hasDraft || !inputAvailable || chatIsResuming || chatIsReconciling;
    sendButton.textContent = chatIsReconciling ? "Antwort wird geladen…" : chatIsResuming ? "Coach antwortet…" : state.busy ? "Einreihen" : "Senden";
  }
  if (steerButton) {
    steerButton.hidden = !state.busy || chatIsResuming || chatIsReconciling;
    steerButton.disabled = !hasDraft || !inputAvailable || chatIsResuming || chatIsReconciling;
  }
  if (cancelButton) {
    cancelButton.hidden = !state.busy || chatIsReconciling;
    const cancelRequested = Boolean(state.chatStream?.cancelRequested || state.chatRequest?.cancelRequested);
    cancelButton.disabled = (!state.chatStream && !state.chatServerOperationId) || cancelRequested;
    cancelButton.textContent = cancelRequested ? "Wird abgebrochen…" : "Abbrechen";
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
    if ($("#chatPanel")?.classList.contains("active") && document.visibilityState === "visible") input.focus({ preventScroll: true });
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
    status.textContent = calendar.configured ? (calendar.last_error ? "Fehler bei letzter Aktualisierung" : "Konfiguriert · nur lesend") : "Nicht konfiguriert";
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
  const match = String(message || "").match(/Zeitraum\s+(\d+)\/(\d+)/i);
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
      const message = job.status === "queued"
        ? "Wartet auf den Start der Synchronisierung…"
        : total > 0 ? `${completed}/${total} Arbeitsschritt${total === 1 ? "" : "e"} abgeschlossen` : "Synchronisierung läuft…";
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

function addStructuredCoachReceipts(payload) {
  const receipts = Array.isArray(payload?.command_receipts) ? payload.command_receipts : [];
  const jobIds = Array.isArray(payload?.sync_job_ids) ? payload.sync_job_ids : [];
  receipts.forEach((entry) => {
    const result = entry?.result || {};
    const tool = entry?.tool || "Coach-Aktion";
    const failed = result.ok === false;
    const details = [];
    if (result.artifact_id) details.push(`Planartefakt ${result.artifact_id} · ${result.status || "bereit"}`);
    if (Array.isArray(result.library_entry_ids) && result.library_entry_ids.length) details.push(`${result.library_entry_ids.length} lokale Einheit(en) gespeichert`);
    if (result.sync_job_id) details.push(`Syncjob ${result.sync_job_id} eingereiht`);
    if (result.remote_untouched) details.push("Remote-Provider unverändert");
    addCoachReceipt({
      title: failed ? `${tool} fehlgeschlagen` : `${tool} ausgeführt`,
      message: failed ? (result.error || "Die Aktion konnte nicht ausgeführt werden.") : (result.status || "Lokale Aktion bestätigt."),
      status: failed ? "error" : "success",
      details: [...details, ...jobIds.filter((id) => !details.some((detail) => detail.includes(id))).map((id) => `Syncjob ${id} eingereiht`)],
    });
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
    || (includeChatDraft && (state.chatDraftDirty || Boolean($("#messageInput")?.value.trim())))
    || state.activityFeedbackDirty.size > 0;
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
  state.activityFeedbackDirty.clear();
  state.activityFeedbackDrafts.clear();
  setDirtyIndicator("activityDirtyIndicator", false);
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

async function askCoach(message) {
  const applied = await applyNavigationRoute("coach", { historyMode: "push", focus: false });
  if (!applied) return;
  const input = $("#messageInput");
  if (!input) return;
  input.value = message;
  input.dispatchEvent(new Event("input"));
  $("#chatForm")?.requestSubmit();
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
  const morning = data.morning_checkin || {};
  const automaticMorningRunning = morning.running || morning.status === "working";
  const automaticMorningReady = morning.status === "ready" && morning.date === todayKey;
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

  const adjustment = data.planning?.latest_replan;
  const priorityCard = todayCard("Coach-Einordnung", "today-priority");
  if (checkin?.illness) {
    todayCardText(priorityCard, `Im Morgen-Check-in ist Krankheit vermerkt: ${checkin.illness}. Die Belastung für heute wird vorsichtig eingeordnet.`, "today-card-summary");
  } else if (adjustment?.changes?.length || adjustment?.illness_pause) {
    todayCardText(priorityCard, "Für die lokale Planung liegt eine Anpassung vor. Sie wird in der Einordnung für heute berücksichtigt.", "today-card-summary");
  } else if (todayWorkouts.length) {
    todayCardText(priorityCard, `${todayWorkouts.length} geplante Einheit${todayWorkouts.length === 1 ? "" : "en"} für heute. Die verfügbaren Quellen und der Morgen-Check-in bilden die Grundlage der Einordnung.`, "today-card-summary");
  } else if (automaticMorningRunning) {
    todayCardText(priorityCard, "Der Morgen-Check-in wird noch erstellt.", "today-card-summary");
  } else if (automaticMorningReady) {
    todayCardText(priorityCard, "Der Morgen-Check-in ist abgeschlossen. Die Einordnung basiert auf dem aktualisierten Snapshot.", "today-card-summary");
  } else if (!checkin) {
    todayCardText(priorityCard, "Für heute liegt noch kein Morgen-Check-in vor. Die Einordnung basiert deshalb auf den verfügbaren Quellendaten.", "today-card-summary");
  } else {
    todayCardText(priorityCard, "Die verfügbaren Quellen und der Morgen-Check-in zeigen keine dringende Anpassung für heute.", "today-card-summary");
  }
  root.append(priorityCard);

  const checkinCard = todayCard("Morgen-Check-in", "today-checkin");
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
  } else if (automaticMorningRunning) {
    todayCardText(checkinCard, "Der Morgen-Check-in wird noch erstellt.", "today-card-summary");
  } else if (automaticMorningReady) {
    todayCardText(checkinCard, "Morgen-Check-in abgeschlossen. Die ausführliche Einordnung findest du im Coach-Chat.", "today-card-summary");
  } else todayCardText(checkinCard, "Noch kein Tages-Check-in gespeichert.");
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
    meta.textContent = [event.type || event.category, formatDuration(event.moving_time), distanceLabel(event.distance)].filter(Boolean).join(" · ") || "Kein Umfang hinterlegt";
    item.append(title, meta);
    workoutCard.append(item);
  });
  root.append(workoutCard);

  const weatherCard = todayCard("Wetter", "today-weather");
  if (!data.weather?.configured) todayCardText(weatherCard, "Kein Wetterort hinterlegt.");
  else if (data.weather?.error && !data.weather?.days?.length) todayCardText(weatherCard, data.weather.error, "today-empty today-error");
  else if (!weather) todayCardText(weatherCard, "Für heute ist noch keine Wettervorhersage geladen.");
  else todayCardText(weatherCard, [weatherIconFor(weather), weather.condition || "Vorhersage", weatherNumber(weather.temperature_min, " °C"), weatherNumber(weather.temperature_max, " °C"), weatherNumber(weather.precipitation_probability_max, " % Regen")].join(" · "), "today-card-summary");
  root.append(weatherCard);

  const feedbackCard = todayCard("Offene Rückmeldung", "today-feedback");
  const openFeedback = (data.activities || []).find((activity) => todayActivityDate(activity) && !activity.activity_feedback);
  if (openFeedback) {
    todayCardText(feedbackCard, `Noch keine Rückmeldung zu „${openFeedback.name || "letzter Aktivität"}“ gespeichert.`, "today-card-summary");
  } else todayCardText(feedbackCard, "Keine offene Rückmeldung zu den geladenen Aktivitäten.");
  root.append(feedbackCard);

  if (adjustment && (adjustment.changes?.length || adjustment.illness_pause)) {
    const adjustmentCard = todayCard("Aktuelle Plananpassung", "today-adjustment");
    todayCardText(adjustmentCard, "Eine lokale Planänderung liegt vor.", "today-card-summary");
    root.append(adjustmentCard);
  }
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

let chatStreamRenderFrame = null;
let chatStreamStartScrollPending = false;
let chatComposerRevealPending = false;

function chatIsNearBottom() {
  return document.documentElement.scrollHeight - (window.scrollY + window.innerHeight) <= 48;
}

function updateChatComposerVisibility() {
  const panel = $("#chatPanel");
  if (!panel) return;
  const inputFocused = document.activeElement === $("#messageInput");
  const hidden = !panel.classList.contains("chat-empty")
    && !chatComposerRevealPending
    && !inputFocused
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
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
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
  if (state.chatRequest?.phase === "recovering") return "Verbindung unterbrochen · die Antwort wird im Hintergrund fertiggestellt…";
  if (state.chatRequest?.phase === "reconciling") return "Antwort wird sicher übernommen…";
  return "Coach arbeitet an deiner Antwort…";
}

function createCoachWorkingIndicator() {
  const node = document.createElement("div");
  node.id = "coachWorking";
  node.className = "coach-working";
  node.setAttribute("role", "status");
  const dots = document.createElement("span");
  dots.className = "working-dots";
  dots.setAttribute("aria-hidden", "true");
  dots.innerHTML = "<i></i><i></i><i></i>";
  const label = document.createElement("span");
  label.id = "coachWorkingLabel";
  label.textContent = coachWorkingLabel();
  node.append(dots, label);
  return node;
}

function renderCoachActionReview() {
  const root = $("#coachActionReview");
  const content = $("#coachActionReviewContent");
  if (!root || !content) return;
  content.replaceChildren();
  const proposals = Array.isArray(state.coachActionProposals) ? state.coachActionProposals : [];
  root.hidden = proposals.length === 0;
  const reviewTitle = $("#coachActionReviewTitle");
  if (reviewTitle) reviewTitle.textContent = proposals.length === 1 && proposals[0].action_type === "delete_duplicate_intervals_activity"
    ? "Doppelte Radaufzeichnung"
    : "Lokale Planung";
  proposals.forEach((proposal) => {
    const duplicateDelete = proposal.action_type === "delete_duplicate_intervals_activity";
    const card = document.createElement("div");
    card.className = "coach-action-card";
    const description = document.createElement("p");
    const target = proposal.target_system === "local+intervals"
      ? "lokal und optional in Intervals.icu"
      : proposal.target_system === "intervals" ? "in Intervals.icu" : "nur lokal";
    description.textContent = duplicateDelete
      ? "Diese Garmin-Radaufzeichnung ist nahezu identisch mit der Wahoo-Einheit. Soll nur das Garmin-Duplikat aus Intervals.icu gelöscht werden?"
      : `Der Coach schlägt ${target} ${proposal.diff?.length || 0} Einheiten vor. Noch nicht gespeichert.`;
    const entries = document.createElement("ul");
    (Array.isArray(proposal.diff) ? proposal.diff : []).forEach((entry) => {
      const item = document.createElement("li");
      item.textContent = duplicateDelete
        ? [entry.name, entry.date, "Garmin löschen · Wahoo behalten"].filter(Boolean).join(" · ")
        : [entry.name, entry.date, entry.sport, entry.duration_minutes ? `${entry.duration_minutes} min` : null].filter(Boolean).join(" · ");
      entries.append(item);
    });
    const actions = document.createElement("div");
    actions.className = "coach-action-card-actions";
    const later = document.createElement("button");
    later.type = "button";
    later.className = "secondary-button";
    later.textContent = duplicateDelete ? "Garmin behalten" : "Später prüfen";
    later.addEventListener("click", () => {
      state.coachActionProposals = (state.coachActionProposals || []).filter((item) => item.id !== proposal.id);
      renderCoachActionReview();
    });
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "adaptive-planning-button";
    confirm.textContent = duplicateDelete
      ? "Garmin-Duplikat löschen"
      : proposal.target_system === "local+intervals" ? "Planung freigeben" : "Lokal speichern";
    confirm.addEventListener("click", () => executeCoachActionProposal(proposal, confirm));
    actions.append(later, confirm);
    card.append(description, entries, actions);
    content.append(card);
  });
}

async function executeCoachActionProposal(proposal, button) {
  if (!proposal?.id || button.disabled) return;
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
    state.coachActionProposals = (state.coachActionProposals || []).filter((item) => item.id !== proposal.id);
    renderCoachActionReview();
    const duplicateDelete = proposal.action_type === "delete_duplicate_intervals_activity";
    const receiptMessage = duplicateDelete
      ? "Garmin-Duplikat aus Intervals.icu gelöscht; die Wahoo-Aktivität bleibt erhalten."
      : result.local_planned
      ? `${result.local_planned} Einheit(en) lokal geplant.`
      : "Planung lokal gespeichert.";
    addCoachReceipt({
      title: duplicateDelete ? "Duplikat gelöscht" : "Planung gespeichert",
      message: receiptMessage,
      details: duplicateDelete ? ["Wahoo bleibt die kanonische Radaufzeichnung"] : [result.sync_job_ids?.length ? `${result.sync_job_ids.length} Syncjobs eingereiht` : result.sync_job_id ? `Syncjob ${result.sync_job_id} eingereiht` : "Keine implizite Remote-Änderung"],
    });
    toast(duplicateDelete ? "Garmin-Duplikat gelöscht" : result.local_planned ? `${result.local_planned} Einheit(en) lokal geplant` : "Planung lokal gespeichert");
    await load("/api/bootstrap?local=1", duplicateDelete ? ["activities"] : ["plan", "library"]);
    if (!duplicateDelete) applyNavigationRoute("plan", { historyMode: "push" });
  } catch (error) {
    addCoachReceipt({ title: "Planung nicht gespeichert", message: error.message, status: "error" });
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

function reconcileCompletedChatMessage(message) {
  if (!state.data || !message || typeof message.content !== "string") return false;
  const completed = { ...message, role: "assistant" };
  const messages = Array.isArray(state.data.messages) ? state.data.messages : [];
  const messageId = completed.id == null ? "" : String(completed.id);
  const existingIndex = messageId
    ? messages.findIndex((entry) => entry?.id != null && String(entry.id) === messageId)
    : -1;
  if (existingIndex >= 0) messages[existingIndex] = completed;
  else messages.push(completed);
  state.data.messages = messages;
  return true;
}

function renderMessages(messages, forceScroll = false, preserveScroll = false) {
  const root = $("#messages");
  const appShellLoading = Boolean($("#appShell")?.classList.contains("is-loading"));
  // Synchronisation and refresh notices belong to their respective tabs,
  // not to the personal conversation history.
  const visibleMessages = (messages || []).filter((message) => message.role !== "event");
  const signature = JSON.stringify([
    visibleMessages.map((message) => [message.id || null, message.created_at || null, message.role, message.content]),
    appShellLoading,
    state.chatStreamText,
    state.chatServerOperationId,
    state.chatResponseStarted,
    state.chatRequest?.phase || null,
    state.chatRequest?.responseMessageId || null,
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
  if (!visibleMessages.length && !state.chatRequest && !state.chatQueue.length) {
    if (appShellLoading) root.append(createSkeletonStack(4));
    else root.append(createEmptyState("Dein Coach ist bereit", "Lege deine Ziele im Profil fest oder starte mit einer Schnellaktion."));
  }
  for (const message of visibleMessages) {
    const node = document.createElement("div");
    node.className = `message ${message.role}`;
    if (message.id != null) node.dataset.messageId = String(message.id);
    if (message.role === "assistant") node.innerHTML = markdownToHtml(message.content);
    else node.textContent = message.content;
    root.append(node);
  }
  for (const entry of state.chatQueue) root.append(createPendingMessage(entry));
  const persistedResponse = Boolean(
    state.chatRequest?.responseMessageReceived
    || (state.chatRequest?.responseMessageId != null
      && visibleMessages.some((message) => message.id != null && String(message.id) === String(state.chatRequest.responseMessageId)))
  );
  const streamVisible = state.chatStreamText && !persistedResponse && ["running", "recovering", "reconciling"].includes(state.chatRequest?.phase);
  if (streamVisible) {
    const node = document.createElement("div");
    node.className = `message assistant streaming${state.chatRequest?.phase === "recovering" ? " is-recovering" : ""}`;
    node.innerHTML = markdownToHtml(state.chatStreamText);
    root.append(node);
  }
  const showWorking = !persistedResponse
    && ["running", "recovering", "reconciling"].includes(state.chatRequest?.phase);
  if (showWorking) {
    root.append(createCoachWorkingIndicator());
  }
  renderCoachActionReview();
  updateChatQueueStatus();
  updateChatComposerVisibility();
  if (shouldScroll && !state.chatResponseStarted) scrollChatToLatest();
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
    const responseId = state.chatRequest?.responseMessageId;
    const target = root.querySelector(".message.assistant.streaming")
      || (responseId == null ? null : assistants.find((node) => node.dataset.messageId === String(responseId)))
      || (!state.chatRequest ? assistants[assistants.length - 1] : null);
    if (!target) {
      state.chatResponseScrollPending = true;
      return;
    }
    const topGap = 16;
    window.scrollTo({ top: Math.max(0, window.scrollY + target.getBoundingClientRect().top - topGap), behavior: "auto" });
    requestAnimationFrame(updateChatComposerVisibility);
  });
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
    requestAnimationFrame(updateChatComposerVisibility);
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
  return [
    weatherIconFor(weather),
    weather.condition,
    weatherNumber(weather.temperature_min, " °C"),
    weatherNumber(weather.temperature_max, " °C"),
  ].filter((value) => value && value !== "–").join(" · ");
}

function plannedAppointmentLabel(event) {
  if (!event || typeof event !== "object") return "";
  const name = String(event.name || "Trainingstermin").trim() || "Trainingstermin";
  if (event.all_day) return `${name} · ganztägig`;
  const time = String(event.start_local || "").match(/(?:T|\s)(\d{2}:\d{2})/);
  return time ? `${name} · ${time[1]}` : name;
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
  const match = String(value || "").match(/(?:T|\s)(\d{2}:\d{2})/);
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

function renderPlanned(trainingCalendar) {
  const root = $("#plannedCalendar");
  const summary = $("#plannedSummary");
  if (!root) return;
  root.replaceChildren();
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
  const weeklyCompliance = new Map(
    (Array.isArray(state.data?.planning_compliance) ? state.data.planning_compliance : [])
      .filter((item) => item && item.week_start)
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
      .filter((item) => item && item.date)
      .map((item) => [String(item.date).slice(0, 10), item]),
  );
  const eventsByDate = new Map();
  entries.forEach((entry) => {
    const key = plannedEventDate(entry);
    if (!eventsByDate.has(key)) eventsByDate.set(key, []);
    eventsByDate.get(key).push(entry);
  });

  for (let weekIndex = 0; weekIndex < pastWeeks + futureWeeks + 1; weekIndex += 1) {
    const weekKey = addDateKey(firstWeekKey, weekIndex * 7);
    const weekEndKey = addDateKey(weekKey, 6);
    const weekCompliance = weeklyCompliance.get(weekKey);
    const weekEntries = Array.from({ length: 7 }, (_, offset) => eventsByDate.get(addDateKey(weekKey, offset)) || []).flat();
    const week = document.createElement("details");
    week.className = "planned-week";
    week.dataset.weekKey = weekKey;
    week.open = previousWeekOpenState.has(weekKey)
      ? previousWeekOpenState.get(weekKey)
      : weekKey === currentWeekKey || weekKey === nextWeekKey;
    const heading = document.createElement("summary");
    heading.className = "planned-week-heading";
    const title = document.createElement("h4");
    title.textContent = planWeekLabel(weekKey);
    const count = document.createElement("span");
    count.className = "planned-week-summary";
    const additionalCompleted = weekEntries.filter((entry) => entry.is_completed_activity).length;
    const weekSummary = plannedWeekSummary(weekKey, weekEndKey, weekEntries, weekCompliance, todayKey);
    count.textContent = additionalCompleted ? `${weekSummary} · +${additionalCompleted} zusätzlich` : weekSummary;
    heading.append(title, count);
    week.append(heading);

    const days = document.createElement("div");
    days.className = "planned-week-days";
    for (let offset = 0; offset < 7; offset += 1) {
      const dateKey = addDateKey(weekKey, offset);
      const dayEntries = eventsByDate.get(dateKey) || [];
      const dayContext = planningContextByDate.get(dateKey) || {};
      const weather = dayContext.weather || (Array.isArray(state.data?.weather?.days)
        ? state.data.weather.days.find((item) => item && item.date === dateKey)
        : null);
      const day = document.createElement("section");
      day.className = `planned-day${dateKey === todayKey ? " is-today" : ""}`;
      const dayHeading = document.createElement("div");
      dayHeading.className = "planned-day-heading";
      const dayHeadingMain = document.createElement("div");
      dayHeadingMain.className = "planned-day-heading-main";
      const dayTitle = document.createElement("h5");
      dayTitle.textContent = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long" }).format(dateFromKey(dateKey));
      dayHeadingMain.append(dayTitle);
      const weatherLabel = plannedWeatherLabel(weather);
      if (weatherLabel) {
        const weatherText = document.createElement("span");
        weatherText.className = "planned-day-weather";
        weatherText.textContent = weatherLabel;
        weatherText.title = "Wettervorhersage";
        dayHeadingMain.append(weatherText);
      }
      const dayCount = document.createElement("span");
      dayCount.textContent = calendarCountLabel(dayEntries, todayKey) || (dateKey > todayKey ? "frei" : "keine Aktivität");
      dayHeading.append(dayHeadingMain, dayCount);
      day.append(dayHeading);

      const appointments = (Array.isArray(dayContext.appointments) ? dayContext.appointments : [])
        .filter((event) => event && event.training_relevant !== false)
        .map(plannedAppointmentLabel)
        .filter(Boolean);
      if (appointments.length) {
        const calendarNotice = document.createElement("p");
        calendarNotice.className = "planned-day-context planned-day-calendar";
        calendarNotice.textContent = `Kalender: ${appointments.join(", ")}`;
        day.append(calendarNotice);
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
        day.append(healthNotice);
      }
      if (!dayEntries.length) {
        const empty = document.createElement("p");
        empty.className = "planned-day-empty";
        empty.textContent = dateKey < todayKey
          ? "Keine Aktivität"
          : dateKey === todayKey ? "Noch keine Einheit geplant oder abgeschlossen" : "Keine Einheit geplant";
        day.append(empty);
      }
      dayEntries.forEach((entry) => {
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
          calendarStatusLabel(entry, dateKey, todayKey),
          activitySportLabel(displayed),
          calendarStartTime(displayed.start_date_local),
          actual ? formatDuration(actual.moving_time ?? actual.elapsed_time) : entry.duration_minutes ? `${entry.duration_minutes} Min.` : formatDuration(entry.moving_time),
          actual ? distanceLabel(actual.distance) : null,
        ].filter(Boolean).join(" · ");
        cardSummary.append(cardTitle, meta);
        if (actual) {
          const primaryMetrics = document.createElement("span");
          primaryMetrics.className = "planned-actual-summary";
          const load = calendarMetricNumber(actual.icu_training_load);
          const rpe = calendarRpeLabel(actual.icu_rpe);
          primaryMetrics.textContent = [load != null ? `Load ${load}` : null, rpe != null ? `RPE ${rpe}/10` : "RPE offen"].filter(Boolean).join(" · ");
          cardSummary.append(primaryMetrics);
        }
        card.append(cardSummary);
        if (actual) {
          const facts = document.createElement("div");
          facts.className = "planned-actual-facts";
          const rpe = calendarRpeLabel(actual.icu_rpe);
          const averageHeartRate = calendarMetricNumber(actual.average_heartrate, " bpm");
          const averagePower = calendarMetricNumber(actual.weighted_average_watts ?? actual.average_watts, " W");
          const elevation = calendarMetricNumber(actual.total_elevation_gain, " hm");
          appendCalendarFact(facts, "Dauer", formatDuration(actual.moving_time ?? actual.elapsed_time));
          appendCalendarFact(facts, "Distanz", distanceLabel(actual.distance));
          appendCalendarFact(facts, "Trainingsload", calendarMetricNumber(actual.icu_training_load));
          appendCalendarFact(facts, "RPE", rpe != null ? `${rpe}/10` : "nicht angegeben");
          appendCalendarFact(facts, "Intensität", calendarIntensityLabel(actual.icu_intensity));
          appendCalendarFact(facts, "Ø Puls", averageHeartRate);
          appendCalendarFact(facts, "Ø Leistung", averagePower);
          appendCalendarFact(facts, "Pace", calendarPaceLabel(actual));
          appendCalendarFact(facts, "Höhenmeter", elevation);
          card.append(facts);
        }
        if (actual && !entry.is_completed_activity) {
          const comparison = document.createElement("div");
          comparison.className = "planned-comparison";
          const plannedDuration = entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.moving_time;
          const plannedLoad = entry.icu_training_load;
          const planLine = document.createElement("p");
          planLine.textContent = `Plan: ${[
            entry.name,
            formatDuration(plannedDuration),
            plannedLoad != null ? `Load ${calendarMetricNumber(plannedLoad)}` : null,
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
          card.append(comparison);
        }
        if (entry.description) {
          const description = document.createElement("p");
          description.className = "planned-description";
          description.textContent = entry.description;
          card.append(description);
        }
        day.append(card);
      });
      days.append(day);
    }
    week.append(days);
    root.append(week);
  }
}

function renderLibrary(workouts) {
  const root = $("#library");
  if (!root) return;
  root.replaceChildren();
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
  const morningBodyBattery = garmin.morning_body_battery || {};
  const beforeSleepBattery = Number(morningBodyBattery.before_sleep?.value);
  const morningBattery = Number(morningBodyBattery.morning?.value);
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
  if (morningBodyBattery.status === "ready" && Number.isFinite(beforeSleepBattery) && Number.isFinite(morningBattery)) {
    detail.textContent += ` · Body Battery morgens: ${beforeSleepBattery} vor dem Schlafen → ${morningBattery} aktuell`;
  } else if (morningBodyBattery.sleep_date) {
    detail.textContent += " · Body Battery: heute Morgen nicht verfügbar";
  }
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
  const match = raw.match(/(?:T|\s)(\d{2}:\d{2})(?::\d{2})?/);
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
  const performanceDetail = syncNotices.length ? syncNotices.join(" · ") : refreshedAt ? `Letzte Aktualisierung: ${formatTime(refreshedAt)}` : "";
  const compared = (value, key) => value && typeof value === "object" ? { ...value, comparison: comparisons[key] } : { value, comparison: comparisons[key] };
  performanceSection(root, "Gesundheitsdaten", [
    ["Gewicht", compared(values.weight_kg, "weight_kg_30d"), null, { key: "weight_kg", step: "0.1" }],
    ["Körperfett", values.body_fat_pct, null, { key: "body_fat_pct", step: "0.1" }],
    ["Größe", values.height_cm, null, { key: "height_cm", step: "0.1" }],
    ["Schlaf", compared({ value: recovery.sleep_hours, unit: "h", source: recovery.sleep_source || "Intervals.icu Wellness" }, "sleep_hours")],
    ["Readiness", compared({ value: recovery.readiness, unit: "", source: recovery.readiness_source || "Intervals.icu Wellness" }, "readiness_30d")],
    ["Ruhepuls", compared({ value: recovery.restingHR, unit: "bpm", source: recovery.restingHR_source || "Intervals.icu Wellness" }, "restingHR")],
    ["HRV", compared({ value: recovery.hrv, unit: "ms", source: recovery.hrv_source || "Intervals.icu Wellness" }, "hrv")],
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
      button.textContent = state.data?.sync?.running || state.data?.garmin_sync?.running || state.localSync.intervals || state.localSync.garmin
        ? "Synchronisierung läuft…"
        : button.disabled ? "Leistungsdaten werden aktualisiert…" : "Leistungsdaten aktualisieren";
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
  const garminSyncRunning = Boolean(data.garmin_sync?.running || state.localSync.garmin);
  setStatus("#garminConnectionStatus", garmin.configured, !garmin.configured
    ? "Nicht konfiguriert"
    : garminSyncRunning
      ? "Synchronisierung läuft…"
      : garmin.source === "fixture" ? "Lokale Testdatei aktiv" : "Konfiguriert");
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
    const action = change.action === "create" ? "erstellt" : change.action === "delete" ? "gelöscht" : change.action === "undo" ? "zurückgenommen" : "geändert";
    title.textContent = `${CHANGE_HISTORY_LABELS[change.entity_type] || "Lokales Objekt"} ${action}`;
    const time = document.createElement("time");
    time.dateTime = change.created_at || "";
    time.textContent = formatTime(change.created_at);
    header.append(title, time);
    const detail = document.createElement("span");
    const fields = Object.keys(change.diff?.fields || {});
    detail.textContent = `${fields.length ? `Felder: ${fields.join(", ")}` : "Keine Felddetails"} · Nur lokal · Quelle: ${change.source || "local"}`;
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
  renderToday(data);
  renderActivities(data.activities || []);
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
      if (area === "weather") Object.assign(payload, { weather: result });
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
    await drainChatQueue(next.message);
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (!state.chatRequest && !state.chatServerOperationId) state.busy = false;
    renderQuickMessageTemplates();
    renderMessages(state.data?.messages || [], true);
    updateChatControls();
  }
}

async function pollChatStatus() {
  if (!state.data || document.visibilityState !== "visible" || !navigator.onLine) {
    scheduleChatStatusPoll(5_000);
    return;
  }
  if (state.chatStatusPollInFlight) return;
  state.chatStatusPollInFlight = true;
  let running = false;
  try {
    const status = await api("/api/chat/status");
    running = status.status === "running";
    if (running) {
      state.chatServerOperationId = status.operation_id || null;
      if (!state.chatRequest) state.chatRequest = { phase: "recovering", operationId: state.chatServerOperationId, message: null };
      else if (state.chatRequest.phase === "recovering") state.chatRequest.operationId = state.chatServerOperationId;
      if (!state.busy) {
        state.busy = true;
        renderQuickMessageTemplates();
        updateChatControls();
        renderMessages(state.data.messages || [], true);
      }
    } else {
      if (state.chatStream) return;
      const recoveringRequest = state.chatRequest?.phase === "recovering";
      state.chatServerOperationId = null;
      if (recoveringRequest) {
        const request = state.chatRequest;
        await loadChatHistoryFresh();
        if (state.chatRequest === request) {
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
      }
    }
  } catch (error) {
    if (!/Authentication/.test(error.message)) scheduleChatStatusPoll(5_000);
  } finally {
    state.chatStatusPollInFlight = false;
    scheduleChatStatusPoll(running ? 1_500 : 5_000);
  }
}

async function loadInitialState() {
  const route = routeFromHash();
  state.planSegment = planSegmentFromRoute(route);
  state.analysisSegment = analysisSegmentFromRoute(route);
  const areas = ["chat", "activities", "performance", "feedback", "profile"];
  areas.push("weather");
  if (route === "today") areas.push("plan");
  if (baseRoute(route) === "plan") areas.push("plan", "library");
  await load("/api/bootstrap?local=1", areas);
  if (state.data?.profile?.weather_location) {
    await load("/api/bootstrap", state.loadedAreas.has("plan") ? ["plan"] : ["weather"]);
  }
  connectStateEvents();
  scheduleChatStatusPoll(0);
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

async function requestCoachResponse(message) {
  if (state.data) {
    state.data.messages.push({ role: "user", content: message });
    renderMessages(state.data.messages, true);
  }
  state.chatStreamText = "";
  const clientTurnId = globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const request = { phase: "running", message, clientTurnId, operationId: null, responseMessageId: null, responseMessageReceived: false, cancelRequested: false };
  state.chatRequest = request;
  const stream = { controller: new AbortController(), operationId: null, cancelRequested: false, request, serverError: false };
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
      body: JSON.stringify({ message, client_turn_id: clientTurnId }),
    });
    if (!response.ok) {
      if (response.status === 401) stream.serverError = true;
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
      for (const line of block.replace(/\r/g, "").split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (!data.length) return;
      const payload = JSON.parse(data.join("\n"));
      if (event === "started") {
        stream.operationId = payload.operation_id || null;
        request.operationId = stream.operationId;
        state.chatServerOperationId = stream.operationId;
      }
      else if (event === "delta") {
        const responseJustStarted = !state.chatStreamText;
        state.chatStreamText += payload.text || "";
        state.chatResponseStarted = state.chatResponseStarted || responseJustStarted;
        if (responseJustStarted) state.chatResponseScrollPending = true;
        scheduleChatStreamRender(responseJustStarted);
      } else if (event === "error") {
        stream.serverError = true;
        const error = new Error(payload.message || "Die Coach-Anfrage ist fehlgeschlagen.");
        error.reason = payload.reason;
        throw error;
      } else if (event === "completed") {
        cancelScheduledChatStreamRender();
        completed = true;
        request.phase = "reconciling";
        request.responseMessageId = payload.message?.id || null;
        request.responseMessageReceived = reconcileCompletedChatMessage(payload.message);
        if (request.responseMessageReceived) state.chatStreamText = "";
        state.coachActionProposals = Array.isArray(payload?.proposed_actions) ? payload.proposed_actions : [];
        if (payload?.coach_quick_actions && state.data) {
          state.data.coach_quick_actions = payload.coach_quick_actions;
          renderCoachOverview(state.data);
        }
        addStructuredCoachReceipts(payload);
        renderMessages(state.data?.messages || [], false);
        updateChatControls();
      }
    };
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || "";
      for (const block of blocks) consume(block);
    }
    buffer += decoder.decode();
    if (buffer.trim()) consume(buffer);
    if (!completed && !stream.cancelRequested) throw new Error("Der Antwort-Stream wurde unerwartet beendet.");
    await loadChatHistoryFresh();
    if (completed) scrollChatToResponseStart();
    invalidateContextPreview();
    return completed ? "completed" : "failed";
  } catch (error) {
    cancelScheduledChatStreamRender();
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
    await loadChatHistoryFresh();
    invalidateContextPreview();
    return false;
  } finally {
    if (state.chatStream === stream) state.chatStream = null;
    if (request.phase !== "recovering") {
      cancelScheduledChatStreamRender();
      state.chatStreamText = "";
    }
    if (!completed && request.phase !== "recovering") state.chatResponseScrollPending = false;
    state.chatResponseStarted = false;
    if (state.chatRequest === request && request.phase !== "recovering") state.chatRequest = null;
    if (request.phase !== "recovering") state.chatServerOperationId = null;
    updateChatControls();
  }
}

async function drainChatQueue(firstMessage) {
  const firstResult = await requestCoachResponse(firstMessage);
  if (firstResult !== "completed") return firstResult;
  while (state.chatQueue.length) {
    const next = state.chatQueue.shift();
    renderMessages(state.data?.messages || [], true);
    if (await requestCoachResponse(next.message) !== "completed") return;
  }
  return "completed";
}

async function cancelChat() {
  const stream = state.chatStream;
  const operationId = stream?.operationId || state.chatServerOperationId;
  if (!operationId) return;
  if (stream) stream.cancelRequested = true;
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
  const message = input.value.trim();
  if (!message || voiceIsRecording() || state.voiceTranscribing) return;
  if (state.chatRequest || state.chatServerOperationId) {
    if (state.busy) queueChatMessage(message, "queue");
    return;
  }
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
  const button = $("#chatResetButton");
  if (!button || !await requestConfirmation("Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen?", { title: "Coach-Chat zurücksetzen?" })) return;
  button.disabled = true;
  button.textContent = "Wird zurückgesetzt…";
  try {
    await api("/api/chat/reset", { method: "POST", body: "{}" });
    if (state.data) {
      state.data.messages = [];
      state.chatQueue = [];
      state.chatRequest = null;
      state.chatStreamText = "";
      state.chatServerOperationId = null;
      state.chatResponseStarted = false;
      state.chatResponseScrollPending = false;
      cancelScheduledChatStreamRender();
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
  };
  try {
    await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    state.profileDirty = false;
    setDirtyIndicator("profileDirtyIndicator", false);
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
  if (!await confirmDiscardChanges()) return;
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
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (_) {}
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
$("#thinkingLevelSelect").addEventListener("change", saveThinkingLevel);
$("#calendarDisplayForm").addEventListener("submit", saveCalendarDisplaySettings);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#diagnosticCaptureToggle").addEventListener("change", setDiagnosticCapture);
$("#logsRefreshButton").addEventListener("click", loadLogs);
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
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "auto" });
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
window.addEventListener("scroll", updateChatComposerVisibility, { passive: true });
window.addEventListener("resize", scheduleMobileViewportLayout, { passive: true });
window.addEventListener("orientationchange", scheduleMobileViewportLayout, { passive: true });
window.addEventListener("pageshow", scheduleMobileViewportLayout, { passive: true });
window.visualViewport?.addEventListener("resize", scheduleMobileViewportLayout, { passive: true });
window.visualViewport?.addEventListener("scroll", scheduleMobileViewportLayout, { passive: true });
window.addEventListener("pagehide", savePwaActivity);
window.addEventListener("beforeunload", (event) => {
  if (!hasUnsavedChanges()) return;
  event.preventDefault();
  event.returnValue = "";
});
setupPwaUpdates();
setupConnectivityStatus();
renderNotificationStatus();
setupSyncStatusMonitoring();
scheduleMobileViewportLayout();
syncNavigationRoute();
bootstrapAuth();
