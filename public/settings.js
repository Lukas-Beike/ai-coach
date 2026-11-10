const CALENDAR_DISPLAY_DEFAULTS = { past_weeks: 1, future_weeks: 4 };

// Profile values as the form presents them; sports is the comma-joined multi-select.
let profileSaveInFlight = false;
function profileFormValues(form) {
  const values = Object.fromEntries(new FormData(form));
  values.sports = new FormData(form).getAll("sports").filter((value) => typeof value === "string").map((value) => value.trim()).filter(Boolean).join(", ");
  return values;
}

// Entry-only fields: the server turns them into first_threshold_pct and never echoes them.
const PROFILE_ENTRY_FIELDS = ["first_threshold_hr", "first_threshold_on"];

function profileSaveConfirmed(changed, saved) {
  // An entered bpm value must come back as the stored percent.
  if (profileFieldText(changed.first_threshold_hr) && typeof saved.first_threshold_pct !== "string") return false;
  return Object.keys(changed)
    .filter((key) => !PROFILE_ENTRY_FIELDS.includes(key))
    .every((key) => Object.hasOwn(saved, key) && typeof saved[key] === "string");
}

function clearProfileEntryFields(form) {
  for (const key of PROFILE_ENTRY_FIELDS) {
    const field = form.elements?.[key];
    if (field) field.value = "";
  }
}

// After a confirmed save: clear the entry and show the stored percent.
function resetProfileEntryFields(form, savedPercent) {
  clearProfileEntryFields(form);
  const field = form.elements?.first_threshold_pct;
  if (savedPercent !== undefined && field) field.value = savedPercent;
}

function profileFieldText(value) {
  return typeof value === "string" ? value : "";
}

function bodyExportMessage(status) {
  const messages = {
    success: "Profil gespeichert und an Garmin gesendet.",
    invalid: "Profil gespeichert. Garmin braucht gültiges Gewicht und Körperfett.",
    unavailable: "Profil gespeichert. Garmin ist nicht verfügbar.",
    superseded: "Profil gespeichert. Neuere Körperwerte haben den Garmin-Upload ersetzt.",
    rejected: "Profil gespeichert. Garmin hat den Upload abgelehnt.",
    uncertain: "Profil gespeichert. Garmin-Upload unklar und möglicherweise noch aktiv. Bitte abwarten und Garmin prüfen, bevor du erneut sendest.",
  };
  return messages[status] || messages.uncertain;
}

function reportBodyExport(status) {
  const button = document.getElementById("retryBodyGarmin");
  if (button) button.hidden = !["invalid", "unavailable", "rejected"].includes(status);
  toast(bodyExportMessage(status), status !== "success");
}

function isDefiniteProfileRejection(error) {
  return Number.isInteger(error?.status) && error.status >= 400 && error.status < 500 && error.status !== 408;
}

async function retryBodyGarmin(event) {
  if (profileSaveInFlight) return;
  profileSaveInFlight = true;
  const button = event.currentTarget;
  button.disabled = true;
  button.hidden = true;
  try {
    const saved = await api("/api/profile", { method: "PUT", body: JSON.stringify({ sync_body_to_garmin: true, retry_body_to_garmin: true }) });
    reportBodyExport(saved.garmin_body_export || "uncertain");
  } catch (error) {
    if (isDefiniteProfileRejection(error)) {
      button.hidden = false;
      toast(error.message, true);
    } else reportBodyExport("uncertain");
  } finally { button.disabled = false; profileSaveInFlight = false; }
}

// The adopted value reaches the open form even while it holds unsaved edits: only the
// stored-percent input and the estimate block change, every other edit stays.
function applyAdoptedFirstThreshold(result) {
  const form = $("#profileForm");
  const stored = profileFieldText(result.profile?.first_threshold_pct);
  if (form?.elements.first_threshold_pct) form.elements.first_threshold_pct.value = stored;
  if (state.profileBaseline) state.profileBaseline = { ...state.profileBaseline, first_threshold_pct: stored };
  if (state.data) state.data = { ...state.data, profile: { ...state.data.profile, ...result.profile }, first_threshold_estimate: result.first_threshold_estimate };
  renderFirstThresholdEstimate(result.first_threshold_estimate, result.profile);
  if (state.profileDirty && form && state.profileBaseline) {
    state.profileDirty = Object.keys(determineChangedProfileFields(profileFormValues(form), state.profileBaseline)).length > 0;
    setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
  }
}

async function adoptFirstThreshold(event) {
  const button = event.currentTarget;
  const percent = Number($("#firstThresholdEstimate").dataset.percent);
  if (!Number.isFinite(percent) || button.disabled) return;
  const profile = state.data?.profile || {};
  const replacesMeasured = Boolean(profile.first_threshold_pct) && profile.first_threshold_origin === "measured";
  if (replacesMeasured && !(await requestConfirmation("Der gemessene Wert wird durch die Schätzung ersetzt.", { title: "Gemessenen Wert ersetzen?", confirmLabel: "Ersetzen" }))) return;
  button.disabled = true;
  try {
    const result = await api("/api/profile/first-threshold/adopt", { method: "POST", body: JSON.stringify({ percent_lthr: percent, ...(replacesMeasured ? { replace_measured: true } : {}) }) });
    applyAdoptedFirstThreshold(result);
    invalidateContextPreview();
    toast(result.adopted === false ? "Schätzung ist bereits übernommen" : "Erste Schwelle übernommen");
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

function determineChangedProfileFields(formValues, baseline) {
  if (!baseline) {
    throw new Error("Das Profil wird noch geladen. Bitte kurz warten und erneut speichern.");
  }
  return Object.fromEntries(
    Object.entries(formValues).filter(([key, value]) => profileFieldText(value) !== profileFieldText(baseline[key]))
  );
}

function handleProfileSaveOutcome(saved, bodyChanged, retryControl, retryBeforeSave) {
  const status = saved.garmin_body_export;
  if (bodyChanged && !status) {
    reportBodyExport("uncertain");
  } else if (status === "unchanged") {
    if (retryControl && retryBeforeSave) retryControl.hidden = false;
    toast("Profil gespeichert; Körperwerte waren unverändert.");
  } else if (status) {
    reportBodyExport(status);
  } else {
    toast("Profil gespeichert und für den Coach aktiviert");
  }
}

function handleProfileSaveError(error, changed, retryBeforeSave) {
  const hasBodyChanges = Object.hasOwn(changed, "weight_kg") || Object.hasOwn(changed, "body_fat_pct");
  const retry = document.getElementById("retryBodyGarmin");
  if (hasBodyChanges && !isDefiniteProfileRejection(error)) {
    if (retry) retry.hidden = true;
    toast("Profil-Speicherung und Garmin-Upload unklar und möglicherweise noch aktiv. Bitte abwarten und beide prüfen, bevor du erneut speicherst.", true);
  } else {
    if (retry && retryBeforeSave) retry.hidden = false;
    toast(error.message, true);
  }
}

async function saveProfile(event) {
  event.preventDefault();
  if (profileSaveInFlight) return;
  profileSaveInFlight = true;
  const button = event.submitter || event.currentTarget.querySelector("button[type=submit]");
  const buttonLabel = button?.textContent || "Athletenkontext speichern";
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Athletenkontext wird gespeichert…";
  }
  const form = event.currentTarget;
  const retryControl = document.getElementById("retryBodyGarmin");
  const retryBeforeSave = retryControl?.hidden === false;
  if (retryControl) retryControl.disabled = true;
  const generation = state.sessionGeneration;
  const submittedForm = JSON.stringify([...new FormData(form)]);
  let changed = {};
  try {
    changed = determineChangedProfileFields(profileFormValues(form), state.profileBaseline);
    const bodyChanged = Object.hasOwn(changed, "weight_kg") || Object.hasOwn(changed, "body_fat_pct");
    const retryButton = document.getElementById("retryBodyGarmin");
    if (bodyChanged && retryButton) retryButton.hidden = true;
    const requestBody = { ...changed, ...(bodyChanged ? { sync_body_to_garmin: true } : {}) };
    const saved = await api("/api/profile", { method: "PUT", body: JSON.stringify(requestBody) });
    if (!profileSaveConfirmed(changed, saved)) {
      throw new Error("Die Profilbestätigung ist unvollständig. Der Entwurf bleibt erhalten.");
    }
    const entryReset = Object.fromEntries(PROFILE_ENTRY_FIELDS.map((key) => [key, ""]));
    const savedPercent = typeof saved.first_threshold_pct === "string" ? { first_threshold_pct: saved.first_threshold_pct } : {};
    state.profileBaseline = { ...state.profileBaseline, ...changed, ...entryReset, ...savedPercent };
    if (generation !== state.sessionGeneration) return;
    state.profileDirty = JSON.stringify([...new FormData(form)]) !== submittedForm;
    if (!state.profileDirty) resetProfileEntryFields(form, savedPercent.first_threshold_pct);
    setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
    invalidateContextPreview();
    handleProfileSaveOutcome(saved, bodyChanged, retryControl, retryBeforeSave);
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = buttonLabel;
    }
    await load();
  } catch (error) {
    handleProfileSaveError(error, changed, retryBeforeSave);
  } finally {
    profileSaveInFlight = false;
    if (retryControl) retryControl.disabled = false;
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = buttonLabel;
    }
  }
}

// Rejects when the backup fails so callers can report the error and keep their own state consistent.
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
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = `pacecraft-database-${todayIso()}.backup`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Verschlüsseltes Backup heruntergeladen");
  } finally { if (button) button.disabled = false; }
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
    invalidateProviderChecks();
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

async function downloadPrivacyExport() {
  try {
    const blob = await downloadRequest(
      "/api/privacy/export",
      "Privacy-Export konnte nicht erstellt werden.",
      130_000,
    );
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = `pacecraft-export-${todayIso()}.zip`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Datenexport erstellt");
  } catch (error) { toast(error.message, true); }
}

let gpsTracksState = { confirmation_text: "" };

function renderGpsTracks(gps) {
  gpsTracksState = gps;
  $("#gpsTracksToggle").checked = Boolean(gps.enabled);
  const button = $("#gpsTracksDeleteButton");
  button.hidden = gps.enabled || !gps.stored_tracks;
  button.textContent = `GPS-Spuren löschen (${gps.stored_tracks || 0})`;
}

async function loadGpsTracks() {
  try { renderGpsTracks(await api("/api/privacy/gps")); } catch (error) { toast(error.message, true); }
}

async function saveGpsTracks(event) {
  const toggle = event.currentTarget;
  try {
    renderGpsTracks(await api("/api/privacy/gps", { method: "POST", body: JSON.stringify({ enabled: toggle.checked }) }));
  } catch (error) {
    toggle.checked = !toggle.checked;
    toast(error.message, true);
  }
}

async function deleteGpsTracks() {
  try {
    const expectedText = gpsTracksState.confirmation_text;
    if (!expectedText) throw new Error("Die Löschbestätigung ist derzeit nicht verfügbar.");
    const confirmation = await requestConfirmation(
      `Alle gespeicherten GPS-Spuren (${gpsTracksState.stored_tracks}) werden unwiderruflich lokal gelöscht. Streckenerkennung und Wetter am Ort nutzen sie nicht mehr. Die übrigen Aufzeichnungen bleiben.`,
      { title: "GPS-Spuren löschen?", inputLabel: "Bestätigungstext", expectedText, confirmLabel: "Löschen" },
    );
    if (!confirmation) return;
    const result = await api("/api/privacy/gps/delete", { method: "POST", body: JSON.stringify({ confirm: confirmation }) });
    renderGpsTracks(result);
    toast("GPS-Spuren gelöscht");
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
    // The backend preview is the single source of the required text; fail closed without it.
    if (!preview.confirmation_text) throw new Error("Die Löschbestätigung ist derzeit nicht verfügbar.");
    const confirmation = await requestConfirmation(scope, {
      title: "Lokale Daten endgültig löschen?",
      inputLabel: "Bestätigungstext",
      expectedText: preview.confirmation_text,
      confirmLabel: "Endgültig löschen",
      secondaryAction: { label: "Erst Backup erstellen", onClick: downloadDatabaseBackup },
    });
    if (!confirmation) return;
    const result = await api("/api/privacy/delete", { method: "POST", body: JSON.stringify({ confirm: confirmation }) });
    const notice = $("#privacyDeleteNotice");
    if (notice) {
      const problems = [];
      if (result.remote_delete_attempted && !result.remote_conversation_deleted) problems.push("die OpenAI-Konversation konnte remote nicht bestätigt gelöscht werden");
      if (result.wahoo_revoke_attempted && !result.wahoo_revoked) problems.push("der Wahoo-Zugriff konnte bei Wahoo nicht widerrufen werden (in den Wahoo-Kontoeinstellungen entfernen)");
      notice.hidden = !problems.length;
      notice.textContent = problems.length
        ? `Lokale Daten wurden gelöscht, aber ${problems.join(" und ")}. Prüfe den Anbieterstatus separat.`
        : "";
    }
    const resultNotice = $("#privacyDeleteResult");
    if (resultNotice) {
      const deleted = Object.entries(result.deleted_categories || {}).map(([category, count]) => `${category}: ${count}`).join(" · ");
      resultNotice.hidden = false;
      const kept = result.recovery_copies_failed
        ? ` ${result.recovery_copies_failed} Wiederherstellungskopie(n) im Datenordner konnten nicht gelöscht werden.`
        : "";
      resultNotice.textContent = `Lokale Datenklassen gelöscht: ${deleted || "keine"}. Remote-Providerdaten bleiben unverändert.${kept}`;
    }
    toast("Lokale Daten gelöscht");
    // Deleted records must neither stay on screen nor reach the session snapshot.
    clearStateSnapshot();
    invalidateProviderChecks();
    void loadProviderChecks();
    // Loads that started before the deletion are dropped instead of rendered.
    state.loadSequence += 1;
    state.replaceDataOnLoad = true;
    state.loadedAreas.clear();
    await load();
  } catch (error) { toast(error.message, true); }
}

async function saveServiceTier(event) {
  const select = event.currentTarget;
  select.disabled = true;
  try {
    await api("/api/settings/service-tier", { method: "PUT", body: JSON.stringify({ service_tier: select.value }) });
    toast(`Geschwindigkeit: ${select.options[select.selectedIndex].text}`);
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  } finally { select.disabled = false; }
}

// Local zones win over provider zones; the editor shows both and saves local values only.
const ZONE_METRIC_LABELS = {
  power: { threshold: "FTP (W)", limits: "Zonenobergrenzen (% der FTP)", key: "percent_limits" },
  heart_rate: { threshold: "Schwellenpuls (LSHF, bpm)", limits: "Zonenobergrenzen (bpm)", key: "limits" },
  pace: { threshold: "", limits: "Zonenobergrenzen (% der Schwellenpace)", key: "percent_limits" },
};
let zoneConfigurations = [];
let zoneEffective = [];
let zoneToday = "";

async function loadZones() {
  try {
    const result = await api("/api/zones");
    zoneConfigurations = result.configurations || [];
    zoneEffective = result.effective || [];
    zoneToday = result.today || "";
    renderZoneEditor();
    renderZoneWarnings(result.threshold_warnings);
    // The strip follows a save or removal at once, not only the next bootstrap.
    if (state.data) state.data.threshold_warnings = result.threshold_warnings ?? null;
    updateStatusSources({ thresholds: thresholdStatusItem(result.threshold_warnings) });
  } catch (error) {
    renderZoneWarnings(null);
    toast(error.message, true);
  }
}

const SDK_FAILURE_TEXT = {
  login_failed: "Garmin-Login fehlgeschlagen",
  mfa_required: "Garmin-Login braucht MFA",
  requests_failed: "Garmin-Abruf schlägt wiederholt fehl",
};

// Pure: one line per stale threshold with value, source and age (#1768).
function zoneWarningLine(item) {
  const unit = item.age_days === 1 ? "Tag" : "Tage";
  const age = item.age_days == null ? "" : ` · ${item.age_days} ${unit} alt`;
  const suffix = { expired: " – nicht mehr verwendet", sdk_failed: " – wird nicht aktualisiert" }[item.reason] || "";
  return `${item.label} ${item.value_text} · ${item.source_label}${age}${suffix}`;
}

function zoneWarningTitle(warnings) {
  const sdk = warnings.sdk_failure ? `${SDK_FAILURE_TEXT[warnings.sdk_failure.reason] || "Garmin-SDK ausgefallen"} · ` : "";
  return `${sdk}Schwellen prüfen und neue Werte hier lokal speichern`;
}

// Pure: the status strip notice for stale thresholds (#1768), or null.
function thresholdStatusItem(warnings) {
  const items = Array.isArray(warnings?.items) ? warnings.items : [];
  if (!items.length) return null;
  return {
    level: "warning",
    title: "Schwellenwerte prüfen",
    detail: items.length === 1 ? zoneWarningLine(items[0]) : `${items.length} Werte sind veraltet.`,
    action: { href: "#more/profile", label: "Prüfen" },
  };
}

function renderZoneWarnings(warnings) {
  const node = $("#zoneWarnings");
  if (!node) return;
  const items = Array.isArray(warnings?.items) ? warnings.items : [];
  node.hidden = !items.length;
  if (!items.length) {
    node.replaceChildren();
    return;
  }
  const title = document.createElement("strong");
  title.textContent = zoneWarningTitle(warnings);
  // Phrasing content only: <output> holds one line per threshold.
  const lines = items.flatMap((item) => [document.createElement("br"), document.createTextNode(`• ${zoneWarningLine(item)}`)]);
  node.replaceChildren(title, ...lines);
  const section = $("#zoneSettings");
  if (section) section.open = true;
}

function selectedZoneConfigurations() {
  const sport = $("#zoneSport").value;
  const metric = $("#zoneMetric").value;
  const environment = $("#zoneEnvironment").value || null;
  // The server picks the configuration in effect today, Garmin defaults included.
  const effective = zoneEffective.find((item) => item.sport === sport && item.metric === metric && item.environment === environment);
  return zoneConfigurations.filter((item) => item.key === effective?.key);
}

function zoneLimitsText(item) {
  return (item[ZONE_METRIC_LABELS[item.metric].key] || item.limits || item.percent_limits || []).join(", ");
}

function renderZoneEditor() {
  const metric = $("#zoneMetric").value;
  const labels = ZONE_METRIC_LABELS[metric];
  const selected = selectedZoneConfigurations();
  const local = selected.find((item) => item.source === "local");
  const shown = local || selected[0];
  $("#zoneThresholdLabel").textContent = labels.threshold;
  $("#zoneThresholdField").hidden = !labels.threshold;
  $("#zoneThreshold").required = Boolean(labels.threshold);
  $("#zoneMaximumField").hidden = metric !== "heart_rate";
  $("#zoneLimitsLabel").textContent = labels.limits;
  $("#zoneThreshold").value = shown?.threshold ?? "";
  $("#zoneMaximum").value = shown?.maximum ?? "";
  $("#zoneLimits").value = shown ? zoneLimitsText(shown) : "";
  $("#zoneRemoveButton").hidden = !local;
  $("#zoneFromBeginningField").hidden = selected.length > 0;
  $("#zoneFromBeginning").checked = false;
  $("#zoneValidFrom").disabled = false;
  $("#zoneValidFrom").value = zoneToday;
  $("#zoneRemoveButton").dataset.key = local?.key || "";
  const sources = $("#zoneSources");
  sources.replaceChildren(...selected.map((item) => {
    const line = document.createElement("li");
    const threshold = item.threshold == null ? "" : ` · Schwelle ${item.threshold}`;
    line.textContent = `${item.source === "local" ? "Lokal (gilt)" : item.label || item.source}${threshold} · ${zoneLimitsText(item)}`;
    return line;
  }));
}

function toggleZoneFromBeginning() {
  const beginning = $("#zoneFromBeginning").checked;
  $("#zoneValidFrom").disabled = beginning;
  $("#zoneValidFrom").required = !beginning;
}

function zoneNumber(value) {
  return value === "" ? null : Number(value);
}

async function saveZones(event) {
  event.preventDefault();
  const metric = $("#zoneMetric").value;
  const button = $("#zoneSaveButton");
  const limits = $("#zoneLimits").value.split(/[\s,;]+/).filter(Boolean).map(Number);
  button.disabled = true;
  try {
    const result = await api("/api/zones", {
      method: "PUT",
      body: JSON.stringify({
        sport: $("#zoneSport").value,
        metric,
        environment: $("#zoneEnvironment").value || null,
        ...($("#zoneFromBeginning").checked ? { from_beginning: true } : { valid_from: $("#zoneValidFrom").value }),
        threshold: ZONE_METRIC_LABELS[metric].threshold ? zoneNumber($("#zoneThreshold").value) : null,
        maximum: metric === "heart_rate" ? zoneNumber($("#zoneMaximum").value) : null,
        [ZONE_METRIC_LABELS[metric].key]: limits,
      }),
    });
    showZoneReceipt("Lokale Zonen gespeichert", result.change);
    await loadZones();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function removeZones() {
  const button = $("#zoneRemoveButton");
  const confirmed = await requestConfirmation("Lokale Zonen entfernen? Danach gelten wieder die Zonen des Anbieters.", { title: "Lokale Zonen entfernen?", confirmLabel: "Entfernen" });
  if (!confirmed) return;
  button.disabled = true;
  try {
    const result = await api("/api/zones/remove", { method: "PUT", body: JSON.stringify({ key: button.dataset.key, confirmed: true }) });
    showZoneReceipt("Lokale Zonen entfernt", result.change);
    await loadZones();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

function showZoneReceipt(message, change) {
  const receipt = $("#zoneReceipt");
  const text = document.createElement("span");
  text.textContent = `${message}. `;
  receipt.replaceChildren(text);
  if (change?.id) {
    const undo = document.createElement("button");
    undo.type = "button";
    undo.className = "message-undo";
    undo.textContent = "Rückgängig";
    undo.addEventListener("click", async () => {
      undo.disabled = true;
      try {
        await api("/api/change-history/undo", { method: "POST", body: JSON.stringify({ change_id: change.id, expected_current_hash: change.after_hash }) });
        receipt.replaceChildren(document.createTextNode("Zurückgenommen."));
        await loadZones();
      } catch (error) {
        undo.disabled = false;
        toast(error.message, true);
      }
    });
    receipt.append(undo);
  }
  receipt.hidden = false;
}
