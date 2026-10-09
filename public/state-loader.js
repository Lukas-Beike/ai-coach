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
