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
