function render(data) {
  if (AppRouter.baseRoute() === "nutrition") { if (state.route === "nutrition/products") void loadNutritionProducts("", { background: true }); else void loadNutrition(); }
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

// Path key for an area-only refresh: it reads live provider-backed areas such as
// weather without recomputing the whole bootstrap a second time.
const LIVE_AREA_REFRESH = "live-areas";
// The last rendered state on this device, so every app start shows data at once
// while the fresh state loads. It survives app restarts and updates and is
// cleared by showLogin on logout, 401 and an unauthenticated start, and by a
// privacy deletion. A snapshot from other assets marks a pending update.
const STATE_SNAPSHOT_KEY = "coach-state-snapshot";
const VIEW_CACHE_KEY = "coach-view-cache";
const VIEW_CACHE_LIMIT = 24;
const STATE_SNAPSHOT_SAVE_DELAY_MS = 1000;
const STATE_SNAPSHOT_ASSET = Array.from(document.scripts || [], (script) => script.src).join(" ") || document.currentScript?.src || "";
let stateSnapshotSaveTimer = null;

function saveStateSnapshot() {
  clearTimeout(stateSnapshotSaveTimer);
  stateSnapshotSaveTimer = null;
  if (!state.initialStateLoaded || !state.data || state.replaceDataOnLoad) return;
  const snapshot = JSON.stringify({ asset: STATE_SNAPSHOT_ASSET, data: state.data });
  try {
    localStorage.setItem(STATE_SNAPSHOT_KEY, snapshot);
  } catch {
    // The view cache gives way to the state snapshot when storage is full.
    try {
      localStorage.removeItem(VIEW_CACHE_KEY);
      localStorage.setItem(STATE_SNAPSHOT_KEY, snapshot);
    } catch { clearStateSnapshot(); }
  }
}

// Coalesces the saves after loaded state, so an app closed by the system still
// starts with recent data.
function scheduleStateSnapshotSave() {
  if (stateSnapshotSaveTimer === null) stateSnapshotSaveTimer = setTimeout(saveStateSnapshot, STATE_SNAPSHOT_SAVE_DELAY_MS);
}

function readStateSnapshot() {
  try {
    const snapshot = JSON.parse(localStorage.getItem(STATE_SNAPSHOT_KEY) || "null");
    if (!snapshot?.data || typeof snapshot.data !== "object") return null;
    return { data: snapshot.data, updated: snapshot.asset !== STATE_SNAPSHOT_ASSET };
  } catch { return null; }
}

function clearStateSnapshot() {
  clearTimeout(stateSnapshotSaveTimer);
  stateSnapshotSaveTimer = null;
  try {
    localStorage.removeItem(STATE_SNAPSHOT_KEY);
    localStorage.removeItem(VIEW_CACHE_KEY);
  } catch { }
}

function readViewCacheEntries() {
  try {
    const cache = JSON.parse(localStorage.getItem(VIEW_CACHE_KEY) || "null");
    return cache?.asset === STATE_SNAPSHOT_ASSET && Array.isArray(cache.entries) ? cache.entries : [];
  } catch { return []; }
}

// The last response of a view read, shown while the view loads it again.
function readViewCache(path) {
  return readViewCacheEntries().find(([key]) => key === path)?.[1] ?? null;
}

function rememberViewCache(path, value) {
  if (!state.data) return;
  const entries = [[path, value], ...readViewCacheEntries().filter(([key]) => key !== path)].slice(0, VIEW_CACHE_LIMIT);
  try {
    localStorage.setItem(VIEW_CACHE_KEY, JSON.stringify({ asset: STATE_SNAPSHOT_ASSET, entries }));
  } catch {
    try { localStorage.removeItem(VIEW_CACHE_KEY); } catch { }
  }
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
    const versionKeys = { feedback: ["checkins", "activity_feedback"], performance: ["performance", providerIds().garmin, "activities"].filter(Boolean) }[area] || [area];
    for (const key of versionKeys) {
      if (bootstrap.state_versions?.[key] !== undefined) payload.state_versions[key] = bootstrap.state_versions[key];
    }
  }
}

// Areas the bootstrap does not cover keep their loaded values, unless the current
// data is only a placeholder (a startup snapshot or data from before a privacy
// deletion) that the next bootstrap must replace.
function bootstrapPayload(bootstrap, liveAreasOnly) {
  const existing = state.replaceDataOnLoad && !liveAreasOnly ? {} : state.data || {};
  const payload = { ...existing, ...bootstrap };
  ["messages", "messages_next_cursor", "library", "library_next_cursor", "plans", "planned", "training_calendar", "planning_view", "planning_compliance", "weather", "parallel_cycling", "daily_planning_context", "planning", "performance", providerIds().garmin, "checkins", "local_feedback", "activity_feedback"].filter(Boolean).forEach((key) => {
    if (existing[key] !== undefined) payload[key] = existing[key];
  });
  return payload;
}

function renderLoadedState(payload, liveAreasOnly) {
  render(payload);
  if (!liveAreasOnly) state.replaceDataOnLoad = false;
}

async function loadState(path = "/api/bootstrap", requestedAreas = null) {
  const requestSequence = ++state.loadSequence;
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  const chatContentVersion = state.chatContentVersion;
  const initialLoad = $("#appShell").classList.contains("is-loading");
  try {
    const liveAreasOnly = path === LIVE_AREA_REFRESH;
    const query = path.includes("local=1") ? "?local=1" : "";
    const areas = new Set(requestedAreas || ["chat", "plan", "library", "performance", "feedback", "profile"]);
    // The area reads do not depend on the bootstrap, so they run alongside it.
    const domainData = loadStateRequests(areas, query);
    // Startup syncs and the one-time canonical backfill can keep the server busy for longer than the default timeout.
    const bootstrap = liveAreasOnly ? {} : await api(path, { timeoutMs: 90_000 });
    if (sessionGeneration !== state.sessionGeneration) return;
    const payload = bootstrapPayload(bootstrap, liveAreasOnly);
    if (initialLoad && requestSequence === state.loadSequence) {
      renderLoadedState(payload, liveAreasOnly);
      // A stored snapshot may already have revealed the shell.
      if ($("#appShell").classList.contains("is-loading")) finishAppShellLoading();
    }
    const results = await domainData;
    if (sessionGeneration !== state.sessionGeneration || requestSequence !== state.loadSequence) return;
    // Incorporate changes that arrived while these requests were in flight.
    payload.messages = state.data?.messages || [];
    const { failures, appliedAreas } = mergeLoadedResults(payload, results, bootstrap, chatGeneration, chatContentVersion);
    applyLoadedStateVersions(payload, appliedAreas, bootstrap, chatGeneration);
    if (requestSequence === state.loadSequence) {
      renderLoadedState(payload, liveAreasOnly);
      scheduleStateSnapshotSave();
    }
    if (failures.length) throw new Error(failures.join("; "));
  } catch (error) {
    if (sessionGeneration !== state.sessionGeneration || error?.status === 401 || /Authentication/.test(error.message)) return;
    const statusCard = $("#statusCard");
    statusCard.hidden = false;
    statusCard.classList.add("warning");
    $("#statusTitle").textContent = "Trainingsdaten konnten nicht geladen werden";
    $("#statusDetail").textContent = error.message;
  } finally {
    if (sessionGeneration === state.sessionGeneration && $("#appShell").classList.contains("is-loading")) finishAppShellLoading();
  }
}

function areaLoading(area) {
  return state.loadingAreas.has(area) || [...state.pendingLoads.values()].some((areas) => areas.has(area));
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
      state.loadingAreas = nextAreas;
      try { await loadState(nextPath, [...nextAreas]); }
      finally { state.loadingAreas = new Set(); }
    }
  })();
  const tracked = promise.finally(() => {
    if (state.loadPromise === tracked) state.loadPromise = null;
  });
  state.loadPromise = tracked;
  return tracked;
}
