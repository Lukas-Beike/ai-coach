const CHANGE_HISTORY_LABELS = {
  profile: "Profil",
  workout_library: "Workout-Bibliothek",
  planned_unit: "Geplante Einheit",
  competition: "Wettkampf",
  training_plan: "Trainingsplan",
};

const CHANGE_HISTORY_ACTIONS = {
  create: "erstellt",
  update: "geändert",
  delete: "gelöscht",
  undo: "zurückgenommen",
};

const CHANGE_HISTORY_SOURCES = {
  coach_apply: "Coach-Freigabe",
  coach_replacement: "Coach-Ersatzplan",
  adaptive_replan: "Adaptive Planung",
  training_status: "Trainingsstatus",
  undo: "Rückgängig",
};

// Field keys delivered by the change-history endpoint (see backend/change_history.py).
const CHANGE_HISTORY_FIELD_LABELS = {
  name: "Name",
  goals: "Ziele",
  sports: "Sportarten",
  training_background: "Trainingshintergrund",
  typical_weekly_volume: "Typisches Wochenvolumen",
  availability: "Verfügbarkeit",
  constraints: "Einschränkungen",
  equipment: "Ausrüstung",
  training_preferences: "Trainingsvorlieben",
  coaching_style: "Coaching-Stil",
  timezone: "Zeitzone",
  weather_location: "Wetterort",
  weight_kg: "Gewicht",
  body_fat_pct: "Körperfettanteil",
  height_cm: "Körpergröße",
  performance_notes: "Leistungsnotizen",
  id: "Kennung",
  type: "Typ",
  description: "Beschreibung",
  duration_minutes: "Dauer",
  moving_time: "Bewegungszeit",
  target: "Ziel",
  date: "Datum",
  source: "Quelle",
  rationale: "Begründung",
  plan_id: "Trainingsplan-Zuordnung",
  plan_name: "Trainingsplanname",
  archived: "Archivierung",
  local_marked: "Lokale Markierung",
  private_calendar_adjustment: "Private Kalenderanpassung",
  sync_status: "Synchronisierungsstatus",
  origin: "Herkunft",
  remote_event_id: "Remote-Termin",
  remote_event_external_id: "Externe Termin-ID",
  local_deleted: "Lokal gelöscht",
  event_date: "Wettkampfdatum",
  start_date_local: "Startdatum",
  sport: "Sportart",
  priority: "Priorität",
  category: "Kategorie",
  distance: "Distanz",
  course_profile: "Streckenprofil",
  notes: "Notizen",
  sync_state: "Synchronisierungsstatus",
  goal: "Ziel",
  start_date: "Startdatum",
  end_date: "Enddatum",
  status: "Status",
};

function changeFieldLabels(change) {
  const labels = Object.keys(change?.diff?.fields || {}).map((field) => CHANGE_HISTORY_FIELD_LABELS[field] || "Sonstiges Feld");
  return [...new Set(labels)];
}

function undoPreviewMessage(preview) {
  const change = preview?.change || {};
  const label = CHANGE_HISTORY_LABELS[change.entity_type] || "Lokales Objekt";
  const action = CHANGE_HISTORY_ACTIONS[change.action] || "geändert";
  let reset;
  if (change.action === "create") {
    reset = "Das durch diese Änderung angelegte Objekt wird wieder entfernt.";
  } else if (change.action === "delete") {
    reset = "Das gelöschte Objekt wird wiederhergestellt.";
  } else {
    const fields = changeFieldLabels(change);
    reset = fields.length
      ? `Diese Felder werden auf den Stand vor der Änderung zurückgesetzt: ${fields.join(", ")}.`
      : "Der Stand vor der Änderung wird wiederhergestellt.";
  }
  return `${label}, ${action} am ${formatTime(change.created_at)}. ${reset} Die Änderung bleibt lokal; neuere Änderungen führen zu einem Konflikt.`;
}

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
    const action = CHANGE_HISTORY_ACTIONS[change.action] || "geändert";
    title.textContent = `${CHANGE_HISTORY_LABELS[change.entity_type] || "Lokales Objekt"} ${action}`;
    const time = document.createElement("time");
    time.dateTime = change.created_at || "";
    time.textContent = formatTime(change.created_at);
    header.append(title, time);
    const detail = document.createElement("span");
    const fields = changeFieldLabels(change);
    const fieldLabel = fields.length ? `Felder: ${fields.join(", ")}` : "Keine Felddetails";
    detail.textContent = `${fieldLabel} · Nur lokal · Quelle: ${CHANGE_HISTORY_SOURCES[change.source] || "App"}`;
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
  button.disabled = true;
  try {
    let preview;
    try {
      preview = await api("/api/change-history/undo/preview", { method: "POST", body: JSON.stringify({ change_id: changeId }) });
    } catch (error) {
      toast(`${error.message || "Die Undo-Vorschau konnte nicht geladen werden."} Es wurde nichts zurückgenommen.`, true);
      return;
    }
    if (!await requestConfirmation(undoPreviewMessage(preview), { title: "Lokale Änderung zurücknehmen?" })) return;
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

async function downloadServerLogs() {
  const button = $("#logsDownloadButton");
  button.disabled = true;
  try {
    const url = URL.createObjectURL(await downloadRequest("/api/logs/download", "Server-Logs konnten nicht heruntergeladen werden."));
    const link = document.createElement("a");
    link.href = url;
    link.download = `intervals-coach-server-logs-${todayIso()}.jsonl`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Server-Logs heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function deleteServerLogs() {
  const confirmed = await requestConfirmation("Server-Logs wirklich löschen?", {
    title: "Server-Logs löschen?",
  });
  if (!confirmed) return;
  const button = $("#logsDeleteButton");
  if (button) button.disabled = true;
  try {
    await api("/api/logs/delete", { method: "POST" });
    const output = $("#logsOutput");
    if (output) output.textContent = "Noch keine Log-Einträge vorhanden.";
    toast("Server-Logs gelöscht");
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}

async function downloadDiagnostics() {
  const button = $("#diagnosticsButton");
  button.disabled = true;
  button.textContent = "Wird vorbereitet…";
  try {
    renderConnectivityStatus(true);
    const blob = await downloadRequest("/api/diagnostics", "Diagnose konnte nicht heruntergeladen werden.");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `intervals-coach-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Diagnose heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Diagnose herunterladen"; }
}


async function deleteDiagnostics() {
  const confirmed = await requestConfirmation("Diagnosedaten wirklich löschen?", {
    title: "Diagnose löschen?",
  });
  if (!confirmed) return;
  const button = $("#diagnosticsDeleteButton");
  if (button) button.disabled = true;
  try {
    await api("/api/diagnostics/delete", { method: "POST" });
    if (state.data?.diagnostic_capture) {
      state.data.diagnostic_capture.entries = 0;
    }
    renderDiagnosticCapture(state.data?.diagnostic_capture || { entries: 0 });
    toast("Diagnose gelöscht");
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}


function renderDiagnosticCapture(capture = {}) {
  const status = $("#diagnosticCaptureStatus");
  if (status) status.textContent = `Erweiterte technische Diagnose ist immer aktiv · ${Number(capture.entries || 0)} technische Einträge gespeichert.`;
}
