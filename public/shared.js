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
  if (panelRoute === "analysis") void loadAnalysisReports();
  if (route === "more/equipment") void renderTrainingRecords();
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


function hideToast() {
  const node = $("#toast");
  clearTimeout(toast.timer);
  node.className = "toast";
  const close = node.querySelector(".toast-close");
  if (close) close.inert = true;
}

function toast(message, error = false) {
  const node = $("#toast");
  const text = document.createElement("span");
  text.textContent = message;
  node.replaceChildren(text);
  if (error) {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast-close";
    close.setAttribute("aria-label", "Meldung schließen");
    close.textContent = "×";
    close.addEventListener("click", hideToast);
    node.append(close);
  }
  node.setAttribute("role", error ? "alert" : "status");
  node.setAttribute("aria-live", error ? "assertive" : "polite");
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(hideToast, error ? 8000 : 3000);
}

function makeScrollRegionFocusable(element, label) {
  element.tabIndex = 0;
  element.setAttribute("role", "region");
  element.setAttribute("aria-label", label);
  return element;
}


function todayIso() { return timezoneDateKey(state.data?.profile?.timezone, new Date()); }



function formatTime(value) {
  if (!value) return "Noch nicht aktualisiert";
  return AppFormat.dateTime(value, { timeZone: state.data?.profile?.timezone }) ?? value;
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


async function confirmDiscardDraft(isDirty) {
  return !isDirty || Boolean(await requestConfirmation("Ungespeicherte Änderungen verwerfen?", { title: "Änderungen verwerfen?" }));
}


async function confirmDiscardChanges() {
  return confirmDiscardDraft(hasUnsavedChanges({ includeChatDraft: false }));
}


function discardUnsavedChanges() {
  state.profileDirty = false;
  state.checkinDirty = false;
  if (state.data) render(state.data);
}


const SETUP_BANNER_DISMISSED_KEY = "intervalsCoachSetupBannerDismissed";


function setupBannerDismissed() {
  // Session-only: dismissal must not persist beyond the browser session.
  try { return sessionStorage.getItem(SETUP_BANNER_DISMISSED_KEY) === "1"; } catch { return false; }
}


function dismissSetupBanner() {
  try { sessionStorage.setItem(SETUP_BANNER_DISMISSED_KEY, "1"); } catch { }
  const banner = $("#setupBanner");
  if (banner) banner.hidden = true;
}


function renderSetupBanner(missing) {
  const banner = $("#setupBanner");
  if (!banner) return;
  banner.hidden = !missing.length || setupBannerDismissed();
  const detail = $("#setupBannerDetail");
  if (detail) detail.textContent = `Fehlt: ${missing.join(" + ")}. Ergänze die fehlende Serverkonfiguration.`;
}


function renderStatus(data) {
  const configured = data.configured;
  const morning = data.morning_checkin || {};
  const missing = [];
  if (!configured.openai) missing.push("OpenAI-API-Schlüssel");
  if (!configured.intervals) missing.push("Intervals.icu-API-Schlüssel");
  // The setup state is shown by the page-wide setup banner on every tab, so the
  // status card only reports runtime problems.
  renderSetupBanner(missing);
  const performanceRefresh = data.performance_refresh || {};
  const openaiStatus = data.usage?.status || {};
  const error = data.sync.last_error || data.library_sync?.last_error || morning.last_error || performanceRefresh.last_error
    || (openaiStatus.state === "error" ? openaiStatus.message : null);
  const statusCard = $("#statusCard");
  const activePanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  const hasProblem = Boolean(error);
  statusCard.hidden = !hasProblem || activePanel === "settingsPanel";
  statusCard.classList.toggle("warning", hasProblem);
  let statusTitle = "Coach ist bereit";
  let statusDetail = "Bereit für deine nächste Frage";
  if (error) {
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
  return AppFormat.date(value, { timeZone: state.data?.profile?.timezone }) ?? String(value).slice(0, 10);
}


function distanceLabel(value) {
  return AppFormat.distance(value);
}


function formatDuration(seconds) {
  return AppFormat.clock(seconds);
}


function formatWhole(value) {
  return AppFormat.number(Math.round(Number(value)), { digits: 0 }) ?? String(value);
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
