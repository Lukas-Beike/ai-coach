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

async function syncWahoo() {
  const button = $("#wahooSyncButton");
  if (!button) return;
  state.localSync.wahoo = true;
  button.disabled = true;
  button.textContent = "Synchronisierung läuft…";
  try {
    const result = await api("/api/wahoo/sync", { method: "POST", body: "{}" });
    if (!result?.id) throw new Error("Die Jobbestätigung fehlt.");
    const completed = await waitForSyncJob(result.id);
    if (completed.status === "failed") throw new Error(providerJobErrorDetail(completed) || globalThis.AppApi.messageForReason(completed.reason, "Wahoo-Synchronisierung fehlgeschlagen."));
    toast(`Wahoo ${completed.status === "partial" ? "teilweise " : ""}synchronisiert`);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.wahoo = false; renderSettings(state.data || {}); }
}

function fullResyncButtonSelector(source) {
  return `#${source}FullResyncButton`;
}

// Wahoo's full resync re-reads the last 90 days and deletes nothing; the wording must say so.
function fullResyncConfirmation(source, providerLabel) {
  if (source === providerIds().wahoo) {
    return {
      title: `${providerLabel} vollständig neu synchronisieren?`,
      message: `Die ${providerLabel}-Einheiten der letzten 90 Tage werden erneut aus ${providerLabel} geladen. Lokal gespeicherte Einheiten werden nicht gelöscht; ${providerLabel} wird nicht verändert.`,
    };
  }
  // The destructive branch requires the athlete to type the provider name before local data is deleted.
  return {
    title: `${providerLabel}-Daten vollständig neu laden?`,
    message: `Alle lokal gespeicherten ${providerLabel}-Daten löschen und vollständig neu laden? Die Daten in ${providerLabel} bleiben unverändert.`,
    expectedText: providerLabel,
  };
}

// The server answers the start at once and reads in the background; the browser asks for the state.
const FULL_RESYNC_POLL_MS = 1000;
const FULL_RESYNC_POLL_FAILURES = 5;

async function fullResync(source) {
  if (!source) return;
  const button = $(fullResyncButtonSelector(source));
  if (!button) return;
  const providerLabel = coachProviderLabel(source);
  const confirmation = fullResyncConfirmation(source, providerLabel);
  if (!await requestConfirmation(confirmation.message, {
    title: confirmation.title,
    expectedText: confirmation.expectedText || "",
    inputLabel: "Name des Anbieters",
  })) return;
  const stateKey = `${source}Full`;
  state.localSync[stateKey] = true;
  renderFullResyncControls(source);
  try {
    const started = await api(`/api/${source}/full-resync`, { method: "POST", body: JSON.stringify({ confirm: "FULL_RESYNC" }) });
    if (started.status === "already_running") toast(`${providerLabel} läuft bereits`);
    await trackFullResync(source, started.operation_id);
  } catch (error) {
    toast(error.message, true);
    await load();
  } finally {
    settleFullResync(source);
  }
}

// A page that opens while a resync runs follows it too, so its button ends in the idle state.
function resumeFullResync(source) {
  const stateKey = `${source}Full`;
  if (!source || state.localSync[stateKey] || !state.data?.provider_resync?.[source]?.running) return;
  state.localSync[stateKey] = true;
  trackFullResync(source, null)
    .catch((error) => toast(error.message, true))
    .finally(() => settleFullResync(source));
}

// The run ended or is no longer followed: the controls follow the server's answer, not an older load.
function settleFullResync(source) {
  state.localSync[`${source}Full`] = false;
  const resync = state.data?.provider_resync?.[source];
  if (resync) resync.running = false;
  renderFullResyncControls(source);
}

async function trackFullResync(source, operationId) {
  const providerLabel = coachProviderLabel(source);
  const resync = await waitForFullResync(source);
  const outcome = resync.outcome && (!operationId || resync.outcome.operation_id === operationId) ? resync.outcome : null;
  if (outcome?.status === "ok") toast(`${providerLabel} vollständig neu geladen`);
  else if (outcome?.status === "partial") toast(`${providerLabel} teilweise geladen`);
  else if (["already_running", "provider_resync_running"].includes(outcome?.reason) || outcome?.status === "already_running") toast(`${providerLabel} läuft bereits`);
  else if (resync.last_error) toast(resync.last_error, true);
  else toast(`${providerLabel}: Resync nicht mehr aktiv`, true);
  invalidateContextPreview();
  await load();
}

async function waitForFullResync(source) {
  let failures = 0;
  for (;;) {
    try {
      const resync = await api(`/api/${source}/full-resync`);
      failures = 0;
      if (!resync.running) return resync;
    } catch {
      failures += 1;
      if (failures >= FULL_RESYNC_POLL_FAILURES) throw new Error("Der Resync-Status ist nicht erreichbar. Er läuft auf dem Server weiter.");
    }
    await new Promise((resolve) => setTimeout(resolve, FULL_RESYNC_POLL_MS));
  }
}

// One path for both providers: label, disabled state and pulse follow the running state.
function renderFullResyncControls(source) {
  const data = state.data || {};
  if (source === providerIds().wahoo) renderWahooSyncControls(data, wahooConnectionView(data));
  else renderGarminFullResync(data);
}

// The job DTO exposes the redacted explanation on its items; the job itself has no error_detail.
function providerJobErrorDetail(job) {
  const details = (Array.isArray(job?.items) ? job.items : []).filter((item) => typeof item?.error_detail === "string" && item.error_detail);
  const actionable = details.find((item) => providerErrorIsNonRetryable(item.error_class)) || details.find((item) => item.status === "failed");
  return actionable?.error_detail || job?.error_detail || "";
}

// Calendar refresh: reloads the local calendar and also runs the shared calendar sync when one is set up.
function bindPlanRefresh() {
  const refresh = AppViewRefresh.create({
    api: (path, options) => (path === "local" ? Promise.resolve({ status: "local" }) : api(path, options)),
    waitForJob: (...args) => waitForSyncJob(...args),
    getRoute: () => state.route,
    getRequest: () => ({ path: state.data?.external_calendar?.configured ? "/api/external-calendar/sync" : "local", body: {} }),
    reload: () => load(),
    button: $("#planRefreshButton"),
    status: $("#planRefreshStatus"),
  });
  $("#planRefreshButton").addEventListener("click", () => void refresh());
}

async function waitForSyncJob(jobId) {
  if (!jobId) return { status: "unknown" };
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const job = await api(`/api/sync/jobs/${encodeURIComponent(jobId)}`);
    // A non-retryable error (for example a missing provider configuration) will
    // not change while polling, so stop now and show the job's own message.
    if ([job.error_class, job.error_code].some((value) => providerErrorIsNonRetryable(value))) {
      throw new Error(providerJobErrorDetail(job) || "Die Anbindung ist nicht vollständig konfiguriert. Bitte die Verbindungseinstellungen unter Mehr prüfen.");
    }
    if (["completed", "partial", "failed"].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Die Synchronisierung läuft länger als erwartet. Der Job kann unter Betrieb & Diagnose weiter verfolgt werden.");
}
