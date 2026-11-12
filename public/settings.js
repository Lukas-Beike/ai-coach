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
  // The zone editor's save button sits in the same section list but submits its own form.
  const button = event.submitter || event.currentTarget.querySelector(".save-bar button[type=submit]");
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

// One select that saves on change: PUT /api/settings/<name> with the chosen value, then names the active option.
function saveSelectSetting({ currentTarget: select }, name, field, label) {
  return runAction(select, async () => {
    await api(`/api/settings/${name}`, { method: "PUT", body: JSON.stringify({ [field]: select.value }) });
    return `${label}: ${select.options[select.selectedIndex].text}`;
  });
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

// Export and deletion run up to minutes: a second click starts nothing, and no deletion runs
// during an export. aria-disabled keeps the focused button focusable.
const privacyInFlight = { export: false, delete: false };
function setPrivacyButtonBusy(button, busy) {
  if (!button) return;
  for (const name of ["aria-busy", "aria-disabled"]) {
    if (busy) button.setAttribute(name, "true");
    else button.removeAttribute(name);
  }
}

async function downloadPrivacyExport() {
  if (privacyInFlight.export) return;
  const button = $("#privacyExportButton");
  privacyInFlight.export = true;
  setPrivacyButtonBusy(button, true);
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
  } catch (error) { toast(error.message, true); } finally {
    privacyInFlight.export = false;
    setPrivacyButtonBusy(button, false);
  }
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

// Files beside the database that the erasure could not remove.
function privacyDeleteLeftovers(result) {
  const copies = result.recovery_copies_failed
    ? ` ${result.recovery_copies_failed} Wiederherstellungskopie(n) im Datenordner konnten nicht gelöscht werden.`
    : "";
  const logs = result.log_files_failed ? " Die Server-Protokolldateien konnten nicht gelöscht werden." : "";
  return copies + logs;
}

async function deletePrivacyData() {
  if (privacyInFlight.delete) return;
  if (privacyInFlight.export) { toast("Der Datenexport läuft noch.", true); return; }
  const button = $("#privacyDeleteButton");
  privacyInFlight.delete = true;
  setPrivacyButtonBusy(button, true);
  const release = () => { privacyInFlight.delete = false; setPrivacyButtonBusy(button, false); };
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
    release();
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
      resultNotice.textContent = `Lokale Datenklassen gelöscht: ${deleted || "keine"}. Remote-Providerdaten bleiben unverändert.${privacyDeleteLeftovers(result)}`;
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
  } catch (error) { toast(error.message, true); } finally { release(); }
}

// Local zones win over provider zones; the editor shows both and saves local values only.
const ZONE_METRIC_LABELS = {
  power: { threshold: "FTP (W)", limits: "Zonenobergrenzen (% der FTP)", key: "percent_limits" },
  heart_rate: { threshold: "Schwellenpuls (LSHF, bpm)", limits: "Zonenobergrenzen (bpm)", key: "limits" },
  pace: { threshold: "", limits: "Zonenobergrenzen (% der Schwellenpace)", key: "percent_limits" },
};
// One page per sport with its zone kinds (#2262); the performance values name its thresholds.
const ZONE_SPORTS = {
  ride: { kinds: ["power", "heart_rate"], lt2: ["cycling_ftp_watts", "bike_threshold_hr_bpm"], maximum: "cycling_max_hr_bpm", power: "cycling_ftp_watts" },
  run: { kinds: ["pace", "heart_rate", "power"], lt2: ["run_threshold_pace_seconds_per_km", "run_threshold_hr_bpm"], maximum: "running_max_hr_bpm", power: "run_threshold_watts" },
  swim: { kinds: ["pace", "heart_rate"], lt2: [null, null], maximum: null, power: null },
};
const ZONE_KIND_TITLES = { power: "Leistungszonen", heart_rate: "Pulszonen", pace: "Pacezonen" };
const POWER_ZONE_NAMES = ["Regeneration", "Grundlage", "Tempo", "Schwelle", "VO2max", "Anaerob", "Neuromuskulär"];
let zoneConfigurations = [];
let zoneEffective = [];
let zoneToday = "";
let zoneSport = "ride";
let zoneDataLoad = null;

function applyZoneData(result) {
  zoneConfigurations = result.configurations || [];
  zoneEffective = result.effective || [];
  zoneToday = result.today || "";
}

async function loadZones() {
  try {
    const result = await api("/api/zones");
    applyZoneData(result);
    renderZoneOverview();
    renderZoneWarnings(result.threshold_warnings);
    // The strip follows a save or removal at once, not only the next bootstrap.
    if (state.data) state.data.threshold_warnings = result.threshold_warnings ?? null;
    updateStatusSources({ thresholds: thresholdStatusItem(result.threshold_warnings) });
  } catch (error) {
    renderZoneWarnings(null);
    toast(error.message, true);
  }
}

// Analyse reads the zones once for its LT1 values; the profile page reloads them on opening.
// A failed read stays failed until then, so a render never starts another one.
function ensureZoneData() {
  zoneDataLoad ||= api("/api/zones").then(applyZoneData, () => {});
  return zoneDataLoad;
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

// The closed section names the stale values; it no longer opens by itself (#2262).
function renderZoneSummary(warnings) {
  const node = $("#zoneSummary");
  if (!node) return;
  const count = Array.isArray(warnings?.items) ? warnings.items.length : 0;
  const noun = count === 1 ? "Wert" : "Werte";
  node.textContent = count ? `${count} ${noun} veraltet` : "";
  node.classList.toggle("is-warning", count > 0);
}

function renderZoneWarnings(warnings) {
  renderZoneSummary(warnings);
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
}

// Pure: the configuration in effect today for one sport, metric and environment, Garmin's
// zones for all sports included (the server picks it and names its key).
function zoneConfigurationFor(sport, metric, environment = null, configurations = zoneConfigurations, effective = zoneEffective) {
  const chosen = effective.find((item) => item.sport === sport && item.metric === metric && (item.environment || null) === environment);
  return chosen ? configurations.find((item) => item.key === chosen.key) || null : null;
}

function zoneLimitsOf(item) {
  return item[ZONE_METRIC_LABELS[item.metric].key] || item.limits || item.percent_limits || [];
}

function zoneLimitsText(item) {
  return zoneLimitsOf(item).join(", ");
}

function zoneMetricValue(key, metrics = state.data?.performance?.metrics) {
  const value = key ? Number(metrics?.[key]?.value) : Number.NaN;
  return Number.isFinite(value) && value > 0 ? value : null;
}

// Pure: a zone's upper limit in its unit (W, bpm, s/km), or null.
function zoneLimitValue(item, limit, thresholdPace) {
  const value = Number(limit);
  if (!Number.isFinite(value) || value <= 0) return null;
  if (item.metric === "pace") return thresholdPace ? thresholdPace * 100 / value : null;
  if (item.metric === "heart_rate" && item.limits) return value;
  const base = item.percent_basis === "maximum" ? item.maximum : item.threshold;
  return Number(base) > 0 ? Number(base) * value / 100 : null;
}

function zoneValueText(metric, value) {
  if (value == null) return "—";
  if (metric === "pace") return formatPace(value).replace(" min/km", "");
  return `${Math.round(value)}${metric === "power" ? " W" : ""}`;
}

// Pure: the rows of one zone kind. The stored limits end with the open top zone, so each limit
// is one zone; a limit without a value to convert (no threshold pace) is shown as its percent.
function zoneRows(item, thresholdPace = null) {
  const limits = zoneLimitsOf(item);
  const percent = !(item.metric === "heart_rate" && item.limits);
  const pace = item.metric === "pace";
  const text = (index, step = 0) => {
    const value = zoneLimitValue(item, limits[index], thresholdPace);
    if (value == null) return percent ? `${AppFormat.number(limits[index])} %` : "—";
    return zoneValueText(item.metric, pace ? value : value + step);
  };
  const last = limits.length - 1;
  return limits.map((limit, index) => {
    const label = item.metric === "power" ? POWER_ZONE_NAMES[index] : null;
    const name = label ? `Z${index + 1} ${label}` : `Z${index + 1}`;
    const share = percent && index < last && zoneLimitValue(item, limit, thresholdPace) != null ? ` · ${AppFormat.number(limit)} %` : "";
    return { zone: `Z${Math.min(index + 1, 5)}`, name, range: zoneRange(item, index, last, text) + share };
  });
}

// The range of one zone: pace zones run from slower to faster, the others from low to high.
function zoneRange(item, index, last, text) {
  if (item.metric === "pace") {
    if (index === 0) return `langsamer als ${text(0)}`;
    if (index === last) return `schneller als ${text(index - 1)}`;
    return `${text(index - 1)}–${text(index)}`;
  }
  if (index === 0) return `bis ${text(0)}`;
  if (index === last) {
    const maximum = item.metric === "heart_rate" && item.maximum ? ` · max ${Math.round(item.maximum)}` : "";
    return `ab ${text(index - 1, 1)}${maximum}`;
  }
  return `${text(index - 1, 1).replace(/ W$/, "")}–${text(index)}`;
}

function zoneSourceText(item) {
  if (item.source === "local") return "Lokal gespeichert";
  // The configuration names its provider; the source key stands in without a label.
  const provider = item.label || item.source;
  return item.sport == null ? `${provider}, gilt für alle Sportarten` : provider;
}

// Pure: LT1 and LT2 of a sport (#2262). LT2 comes from the performance values; LT1 is the
// stored share of the threshold heart rate and the power or pace at the top of zone 2.
function thresholdRows(sport, metrics = state.data?.performance?.metrics || {}, profile = state.data?.profile || {}) {
  const spec = ZONE_SPORTS[sport];
  const metric = sport === "ride" ? "power" : "pace";
  const lt2 = { main: zoneMetricValue(spec.lt2[0], metrics), hr: zoneMetricValue(spec.lt2[1], metrics) };
  const share = Number(profile.first_threshold_pct);
  const zones = zoneConfigurationFor(sport, metric);
  const zoneTwo = zones ? zoneLimitValue(zones, zoneLimitsOf(zones)[1], lt2.main) : null;
  const lt1 = { main: zoneTwo, hr: lt2.hr && share > 0 ? lt2.hr * share / 100 : null };
  const sources = [metrics[spec.lt2[0]], metrics[spec.lt2[1]]].filter((item) => item?.value != null);
  return {
    metric,
    lt1,
    lt2,
    lt1Source: share > 0 ? firstThresholdSource(profile) : null,
    lt1Derived: zoneTwo != null,
    lt2Source: sources[0]?.source || null,
    validFrom: sources.map((item) => String(item.observed_at || "")).filter(Boolean).sort((a, b) => a.localeCompare(b)).at(-1) || null,
  };
}

function firstThresholdSource(profile) {
  return profile.first_threshold_origin === "estimated" ? "LT1 aus der Herzfrequenzvariabilität (App)" : "LT1 gemessen";
}

function thresholdMainText(metric, value) {
  return metric === "pace" && value != null ? `${zoneValueText("pace", value)} /km` : zoneValueText(metric, value);
}

function zoneEditButton(label, attributes) {
  const button = reportNode("button", label, "zone-edit");
  button.type = "button";
  Object.assign(button.dataset, attributes);
  return button;
}

function thresholdBox(sport) {
  const rows = thresholdRows(sport);
  const box = reportNode("section", null, "zone-box");
  box.dataset.zoneBox = "thresholds";
  const heading = reportNode("h3", "Schwellen");
  if (rows.validFrom) heading.append(reportNode("small", `gilt seit ${dateLabel(String(rows.validFrom).slice(0, 10))}`));
  const grid = reportNode("div", null, "zone-thresholds");
  grid.append(reportNode("span"), reportNode("span", rows.metric === "power" ? "Leistung" : "Pace", "zone-muted"), reportNode("span", "Puls", "zone-muted"));
  const lt2Label = sport === "ride" ? "LT2 / FTP" : "LT2";
  const lines = [{ label: "LT1", values: rows.lt1, main: "lt1-main", hr: "lt1-hr" }, { label: lt2Label, values: rows.lt2, main: "lt2-main", hr: "lt2-hr" }];
  for (const { label, values, ...names } of lines) {
    const main = reportNode("b", thresholdMainText(rows.metric, values.main));
    const hr = reportNode("b", values.hr == null ? "—" : `${Math.round(values.hr)} bpm`);
    main.dataset.threshold = names.main;
    hr.dataset.threshold = names.hr;
    grid.append(reportNode("span", label, "zone-muted"), main, hr);
  }
  const derived = rows.metric === "power" ? ", Leistung aus Zone 2" : ", Pace aus Zone 2";
  const lt1Line = rows.lt1Source ? rows.lt1Source + (rows.lt1Derived ? derived : "") : null;
  const source = [lt1Line, rows.lt2Source && `LT2 von ${rows.lt2Source}`].filter(Boolean).join(" · ");
  const foot = reportNode("p", source || null, "zone-source");
  foot.append(zoneEditButton("Bearbeiten", { zoneEdit: "lt1" }));
  box.append(heading, grid, foot);
  return box;
}

function zoneKindBox(sport, metric, environment = null) {
  const item = zoneConfigurationFor(sport, metric, environment);
  const box = reportNode("section", null, "zone-box");
  box.dataset.zoneBox = environment ? `${metric}-${environment}` : metric;
  const heading = reportNode("h3", environment ? `${ZONE_KIND_TITLES[metric]} · Indoor` : ZONE_KIND_TITLES[metric]);
  const basis = { power: sport === "run" ? "% der Schwellenleistung" : "% der FTP", heart_rate: "bpm", pace: "% der Schwellenpace" }[metric];
  heading.append(reportNode("small", basis));
  box.append(heading);
  const attributes = { zoneEdit: metric, zoneEnvironment: environment || "" };
  if (!item) {
    const empty = reportNode("p", "Noch keine Werte – ", "zone-source");
    empty.append(zoneEditButton("Anlegen", attributes));
    box.append(empty);
    return box;
  }
  const list = reportNode("ul", null, "zone-list");
  for (const row of zoneRows(item, metric === "pace" ? zoneMetricValue(ZONE_SPORTS[sport].lt2[0]) : null)) {
    const line = reportNode("li");
    line.dataset.zone = row.zone;
    line.append(reportNode("i"), reportNode("span", row.name), reportNode("em", row.range));
    list.append(line);
  }
  const foot = reportNode("p", zoneSourceText(item), "zone-source");
  foot.append(zoneEditButton("Bearbeiten", attributes));
  box.append(list, foot);
  return box;
}

function renderZoneOverview() {
  const root = $("#zoneOverview");
  if (!root) return;
  document.querySelectorAll("#zoneSportTabs [data-zone-sport]").forEach((button) => {
    const active = button.dataset.zoneSport === zoneSport;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const boxes = [thresholdBox(zoneSport)];
  for (const metric of ZONE_SPORTS[zoneSport].kinds) {
    boxes.push(zoneKindBox(zoneSport, metric));
    // Indoor zones of their own stay visible beside the general ones.
    if (zoneConfigurationFor(zoneSport, metric, "indoor")) boxes.push(zoneKindBox(zoneSport, metric, "indoor"));
  }
  // The editors move under a box when opened; they go back before the boxes are replaced.
  const editors = [$("#firstThresholdEditor"), $("#zoneEditor")];
  editors.forEach((editor) => { editor.hidden = true; });
  $("#zoneReceipt").after(...editors);
  root.replaceChildren(...boxes);
}

function refreshThresholdBox() {
  const box = document.querySelector('#zoneOverview [data-zone-box="thresholds"]');
  if (box) box.replaceWith(thresholdBox(zoneSport));
}

function showZoneSport(sport) {
  if (!ZONE_SPORTS[sport]) return;
  zoneSport = sport;
  renderZoneOverview();
}

// "Bearbeiten" opens the existing form under its box, prefilled with the values in effect.
function openZoneEditor(button) {
  const box = button.closest("[data-zone-box]");
  if (button.dataset.zoneEdit === "lt1") {
    const editor = $("#firstThresholdEditor");
    $("#zoneEditor").hidden = true;
    editor.hidden = false;
    box.after(editor);
    editor.querySelector("input")?.focus();
    return;
  }
  $("#zoneSport").value = zoneSport;
  $("#zoneMetric").value = button.dataset.zoneEdit;
  $("#zoneEnvironment").value = button.dataset.zoneEnvironment || "";
  renderZoneEditor();
  const editor = $("#zoneEditor");
  $("#firstThresholdEditor").hidden = true;
  editor.hidden = false;
  box.after(editor);
  $("#zoneLimits").focus();
}

function selectedZoneConfigurations() {
  const shown = zoneConfigurationFor($("#zoneSport").value, $("#zoneMetric").value, $("#zoneEnvironment").value || null);
  return shown ? zoneConfigurations.filter((item) => item.key === shown.key) : [];
}

// Pure: the editor values in effect today, or the current threshold from the performance
// values when the kind has no zones yet (#2262).
function zoneEditorValues(sport, metric, shown, metricValue = zoneMetricValue) {
  if (shown) return { threshold: shown.threshold ?? "", maximum: shown.maximum ?? "", limits: zoneLimitsText(shown) };
  const spec = ZONE_SPORTS[sport] || {};
  const threshold = { power: metricValue(spec.power), heart_rate: metricValue(spec.lt2?.[1]) }[metric] ?? "";
  return { threshold, maximum: metric === "heart_rate" ? metricValue(spec.maximum) ?? "" : "", limits: "" };
}

function renderZoneEditor() {
  const sport = $("#zoneSport").value;
  const metric = $("#zoneMetric").value;
  const labels = ZONE_METRIC_LABELS[metric];
  const selected = selectedZoneConfigurations();
  const local = selected.find((item) => item.source === "local");
  const values = zoneEditorValues(sport, metric, local || selected[0]);
  $("#zoneThresholdLabel").textContent = labels.threshold;
  $("#zoneThresholdField").hidden = !labels.threshold;
  $("#zoneThreshold").required = Boolean(labels.threshold);
  $("#zoneMaximumField").hidden = metric !== "heart_rate";
  $("#zoneLimitsLabel").textContent = labels.limits;
  $("#zoneThreshold").value = values.threshold;
  $("#zoneMaximum").value = values.maximum;
  $("#zoneLimits").value = values.limits;
  $("#zoneRemoveButton").hidden = !local;
  $("#zoneFromBeginningField").hidden = selected.length > 0;
  $("#zoneFromBeginning").checked = false;
  $("#zoneValidFrom").disabled = false;
  $("#zoneValidFrom").max = zoneToday;
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
