const CHANGE_HISTORY_LABELS = {
  profile: "Profil",
  workout_library: "Workout-Bibliothek",
  competition: "Wettkampf",
  training_plan: "Trainingsplan",
};

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
    let action = "geändert";
    if (change.action === "create") action = "erstellt";
    else if (change.action === "delete") action = "gelöscht";
    else if (change.action === "undo") action = "zurückgenommen";
    title.textContent = `${CHANGE_HISTORY_LABELS[change.entity_type] || "Lokales Objekt"} ${action}`;
    const time = document.createElement("time");
    time.dateTime = change.created_at || "";
    time.textContent = formatTime(change.created_at);
    header.append(title, time);
    const detail = document.createElement("span");
    const fields = Object.keys(change.diff?.fields || {});
    const fieldLabel = fields.length ? `Felder: ${fields.join(", ")}` : "Keine Felddetails";
    detail.textContent = `${fieldLabel} · Nur lokal · Quelle: ${change.source || "local"}`;
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
  if (!await requestConfirmation("Diese Änderung lokal zurücknehmen? Es wird kein Remote-Provider beschrieben. Neuere Änderungen führen zu einem Konflikt.", { title: "Lokale Änderung zurücknehmen?" })) return;
  button.disabled = true;
  try {
    const preview = await api("/api/change-history/undo/preview", { method: "POST", body: JSON.stringify({ change_id: changeId }) });
    if (!await requestConfirmation("Undo-Vorschau bestätigen? Die Mutation bleibt lokal; ein späterer Remote-Sync muss separat geprüft werden.", { title: "Undo-Vorschau bestätigen?" })) return;
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
