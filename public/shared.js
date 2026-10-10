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

async function apiAudio(path, blob) {
  const generation = state.sessionGeneration;
  const result = await globalThis.AppApi.audio(path, blob, () => {
    if (generation === state.sessionGeneration) showLogin();
  });
  if (generation !== state.sessionGeneration) throw new DOMException("Session ended", "AbortError");
  return result;
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


function todayIso() { return timezoneDateKey(state.data?.profile?.timezone, new Date()); }



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


function distanceLabel(value) {
  const distance = Number(value);
  if (!Number.isFinite(distance) || distance <= 0) return null;
  return `${(distance / 1000).toFixed(1)} km`;
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
