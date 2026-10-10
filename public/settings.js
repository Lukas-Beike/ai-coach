const CALENDAR_DISPLAY_DEFAULTS = { past_weeks: 1, future_weeks: 4 };

async function saveProfile(event) {
  event.preventDefault();
  const button = event.submitter || event.currentTarget.querySelector("button[type=submit]");
  const buttonLabel = button?.textContent || "Athletenkontext speichern";
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.textContent = "Athletenkontext wird gespeichert…";
  }
  const form = event.currentTarget;
  const generation = state.sessionGeneration;
  const submittedForm = JSON.stringify([...new FormData(form)]);
  const formData = new FormData(form);
  const profile = {
    ...state.data?.profile,
    ...Object.fromEntries(formData),
    sports: formData.getAll("sports").filter((value) => typeof value === "string").map((value) => value.trim()).filter(Boolean).join(", "),
  };
  try {
    const saved = await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    if (!Object.keys(profile).every((key) => Object.hasOwn(saved, key) && typeof saved[key] === "string")) {
      throw new Error("Die Profilbestätigung ist unvollständig. Der Entwurf bleibt erhalten.");
    }
    if (generation !== state.sessionGeneration) return;
    state.profileDirty = JSON.stringify([...new FormData(form)]) !== submittedForm;
    setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
    invalidateContextPreview();
    toast("Profil gespeichert und für den Coach aktiviert");
    // Do not keep the successful save action in its loading state while the
    // follow-up refresh loads the rest of the application state.
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = buttonLabel;
    }
    await load();
  } catch (error) { toast(error.message, true); }
  finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = buttonLabel;
    }
  }
}

async function saveCheckin(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  values.tag_answers = {};
  for (const tag of ["travel", "late_meal", "high_stress"]) {
    if (values[`tag_${tag}`] !== "") values.tag_answers[tag] = values[`tag_${tag}`] === "true";
    delete values[`tag_${tag}`];
  }
  for (const field of ["soreness", "stress", "motivation", "session_rpe", "available_minutes"]) {
    values[field] = values[field] === "" ? null : Number(values[field]);
  }
  const button = form.querySelector("button[type=submit]");
  const errorNode = $("#checkinError");
  if (errorNode) errorNode.textContent = "";
  if (button) { button.disabled = true; button.textContent = "Check-in wird gespeichert…"; }
  try {
    const result = await api("/api/feedback", { method: "POST", body: JSON.stringify(values) });
    if (result.checkin?.checkin_date !== values.checkin_date) throw new Error("Die Check-in-Bestätigung fehlt. Der Entwurf bleibt erhalten.");
    state.checkinDirty = false;
    setDirtyIndicator("checkinDirtyIndicator", false);
    state.checkinSelectedDate = result.checkin?.checkin_date || values.checkin_date;
    toast("Tages-Check-in gespeichert");
    $("#checkinDialog")?.close();
    await load();
  } catch (error) {
    if (errorNode) errorNode.textContent = error.message;
  }
  finally {
    if (button) { button.disabled = false; button.textContent = "Tages-Check-in speichern"; }
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
    link.download = `intervals-coach-database-${todayIso()}.backup`;
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
    link.download = `intervals-coach-export-${todayIso()}.zip`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("Datenexport erstellt");
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
      notice.hidden = !(result.remote_delete_attempted && !result.remote_conversation_deleted);
      notice.textContent = notice.hidden
        ? ""
        : "Lokale Daten wurden gelöscht, aber die OpenAI-Konversation konnte remote nicht bestätigt gelöscht werden. Prüfe den Anbieterstatus separat.";
    }
    const resultNotice = $("#privacyDeleteResult");
    if (resultNotice) {
      const deleted = Object.entries(result.deleted_categories || {}).map(([category, count]) => `${category}: ${count}`).join(" · ");
      resultNotice.hidden = false;
      resultNotice.textContent = `Lokale Datenklassen gelöscht: ${deleted || "keine"}. Remote-Providerdaten bleiben unverändert.`;
    }
    toast("Lokale Daten gelöscht");
    await load();
  } catch (error) { toast(error.message, true); }
}
