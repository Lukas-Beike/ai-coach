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

async function waitForSyncJob(jobId) {
  if (!jobId) return { status: "unknown" };
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const job = await api(`/api/sync/jobs/${encodeURIComponent(jobId)}`);
    // A non-retryable error (for example a missing provider configuration) will
    // not change while polling, so stop now and show the job's own message.
    if ([job.error_class, job.error_code].some(providerErrorIsNonRetryable)) {
      throw new Error(job.error_detail || "Die Anbindung ist nicht vollständig konfiguriert. Bitte die Verbindungseinstellungen unter Mehr prüfen.");
    }
    if (["completed", "partial", "failed"].includes(job.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("Die Synchronisierung läuft länger als erwartet. Der Job kann unter Betrieb & Diagnose weiter verfolgt werden.");
}
