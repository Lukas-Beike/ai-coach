// One athlete action on a control: busy state, `run` (returns the success toast), reload, error toast and cleanup.
// `flag` locks a state.localSync entry against a second tap; `rerender` lets the settings redraw the control.
async function runAction(control, run, { flag, busyText, idleText, pulse, invalidate, rerender } = {}) {
  if (!control || (flag && state.localSync[flag])) return;
  if (flag) state.localSync[flag] = true;
  control.disabled = true;
  if (busyText) control.textContent = busyText;
  if (pulse) control.classList.add("busy");
  try {
    toast(await run());
    if (invalidate) invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally {
    if (flag) state.localSync[flag] = false;
    if (pulse) control.classList.remove("busy");
    if (rerender) renderSettings(state.data || {});
    else {
      control.disabled = false;
      if (idleText) control.textContent = idleText;
    }
  }
}

// Starts a provider job and follows it to the end; a failed job throws its own cause.
async function runSyncJob(path, body, failure, requireId = false) {
  const result = await api(path, { method: "POST", body });
  if (requireId && !result?.id) throw new Error("Die Jobbestätigung fehlt.");
  const completed = await waitForSyncJob(result.id);
  if (completed.status === "failed") throw new Error(providerJobErrorDetail(completed) || globalThis.AppApi.messageForReason(completed.reason, failure));
  return completed;
}

const partially = (job) => (job.status === "partial" ? "teilweise " : "");

function syncGarmin() {
  return runAction($("#garminSyncButton"), async () => {
    $("#garminSyncDays")?.removeAttribute?.("data-dirty");
    const days = $("#garminSyncDays")?.value || state.data?.sync_settings?.garmin_days || 84;
    const job = await runSyncJob("/api/garmin/sync", JSON.stringify({ days }), "Garmin-Synchronisierung fehlgeschlagen.");
    return `Garmin ${partially(job)}synchronisiert`;
  }, { flag: providerIds().garmin, busyText: "Garmin wird synchronisiert…", idleText: "Garmin synchronisieren", invalidate: true });
}

function syncExternalCalendar() {
  return runAction($("#externalCalendarSyncButton"), async () => {
    const job = await runSyncJob("/api/external-calendar/sync", "{}", "Kalender-Synchronisierung fehlgeschlagen.");
    return `Kalender ${partially(job)}synchronisiert`;
  }, { flag: "externalCalendar", busyText: "Synchronisierung läuft…", idleText: "Synchronisieren", invalidate: true });
}

function syncWeather() {
  return runAction($("#weatherSyncButton"), async () => {
    const job = await runSyncJob("/api/weather/sync", "{}", "Wetter-Synchronisierung fehlgeschlagen.");
    return job.status === "partial" ? "Open-Meteo teilweise aktualisiert" : "Open-Meteo-Wetter aktualisiert";
  }, { flag: "weather", busyText: "Wetter wird aktualisiert…", pulse: true, invalidate: true, rerender: true });
}

function syncWahoo() {
  return runAction($("#wahooSyncButton"), async () => {
    const job = await runSyncJob("/api/wahoo/sync", "{}", "Wahoo-Synchronisierung fehlgeschlagen.", true);
    return `Wahoo ${partially(job)}synchronisiert`;
  }, { flag: providerIds().wahoo, busyText: "Synchronisierung läuft…", invalidate: true, rerender: true });
}

function fullResyncButtonSelector(source) {
  return `#${source}FullResyncButton`;
}

// A full resync re-reads from the provider; locally it removes only the units the provider dropped.
function fullResyncConfirmation(source, providerLabel) {
  if (source === providerIds().wahoo) {
    return {
      title: `${providerLabel} vollständig neu synchronisieren?`,
      message: `Die ${providerLabel}-Einheiten der letzten 90 Tage werden erneut aus ${providerLabel} geladen. Lokale Daten bleiben erhalten; nur in ${providerLabel} gelöschte Einheiten werden auch hier entfernt. ${providerLabel} wird nicht verändert.`,
    };
  }
  // Garmin reads its whole history, so the athlete types the provider name before it starts.
  return {
    title: `${providerLabel}-Daten vollständig neu laden?`,
    message: `Alle ${providerLabel}-Daten werden erneut aus ${providerLabel} geladen. Lokale Daten bleiben erhalten; nur in ${providerLabel} gelöschte Einheiten werden auch hier entfernt. ${providerLabel} wird nicht verändert.`,
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
  // The regular sync buttons are disabled while the flag is set; redraw them too.
  renderSettings(state.data || {});
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
      const { outcome, ...current } = resync;
      if (state.data?.provider_resync) state.data.provider_resync[source] = current;
      if (!resync.running) return resync;
      renderFullResyncControls(source);
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

// job.error_detail is the DTO's one redacted cause (an item's detail, failed items first); items stay as the fallback.
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
    if (providerErrorIsNonRetryable(job.error_class)) {
      throw new Error(providerJobErrorDetail(job) || "Die Anbindung ist nicht vollständig konfiguriert. Bitte die Verbindungseinstellungen unter Mehr prüfen.");
    }
    if (["completed", "partial", "failed"].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Die Synchronisierung läuft länger als erwartet. Der Job kann unter Betrieb & Diagnose weiter verfolgt werden.");
}
