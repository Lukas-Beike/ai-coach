const $ = (selector) => document.querySelector(selector);
const state = {
  data: null,
  busy: false,
  chatQueue: [],
  chatQueueSequence: 0,
  profileDirty: false,
  activityTypes: new Set(),
  plannedWeekOpen: new Map(),
  voiceRecorder: null,
  voiceStream: null,
  voiceTimer: null,
  voiceStartedAt: 0,
  voiceTranscribing: false,
  localSync: { intervals: false, competitions: false, garmin: false, externalCalendar: false, performance: false, intervalsFull: false, garminFull: false },
  notificationKeys: new Set(),
  quickTemplatesVisible: false,
  activityTracked: false,
};
const VOICE_MAX_DURATION_MS = 60_000;
const VOICE_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const QUICK_TEMPLATES_INACTIVITY_MS = 6 * 60 * 60 * 1000;
const LAST_PWA_ACTIVITY_KEY = "intervals-coach-last-pwa-activity";

function readLastPwaActivity() {
  try {
    const value = Number(localStorage.getItem(LAST_PWA_ACTIVITY_KEY));
    return Number.isFinite(value) && value > 0 ? value : 0;
  } catch (_) { return 0; }
}

function savePwaActivity() {
  try { localStorage.setItem(LAST_PWA_ACTIVITY_KEY, String(Date.now())); } catch (_) {}
}

function notePwaActivity() {
  if (!state.activityTracked) {
    const lastActivity = readLastPwaActivity();
    state.quickTemplatesVisible = Boolean(lastActivity && Date.now() - lastActivity >= QUICK_TEMPLATES_INACTIVITY_MS);
    state.activityTracked = true;
  }
  savePwaActivity();
}

function renderQuickMessageTemplates() {
  const root = $("#quickMessageTemplates");
  if (root) root.hidden = !state.quickTemplatesVisible || state.busy;
}

function checkPwaReturn() {
  if (!state.data || document.visibilityState !== "visible") return;
  const lastActivity = readLastPwaActivity();
  if (lastActivity && Date.now() - lastActivity >= QUICK_TEMPLATES_INACTIVITY_MS) state.quickTemplatesVisible = true;
  savePwaActivity();
  renderQuickMessageTemplates();
}

function handlePwaInteraction() {
  if (!state.data || document.visibilityState !== "visible") return;
  const lastActivity = readLastPwaActivity();
  if (lastActivity && Date.now() - lastActivity >= QUICK_TEMPLATES_INACTIVITY_MS) state.quickTemplatesVisible = true;
  savePwaActivity();
  renderQuickMessageTemplates();
}

function cookie(name) {
  return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
}

function showLogin() {
  state.data = null;
  $("#appShell").hidden = true;
  const dialog = $("#loginDialog");
  if (!dialog.open) dialog.showModal();
  $("#loginPassword").focus();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.method && options.method !== "GET" ? { "X-CSRF-Token": cookie("ic_csrf") } : {}), ...(options.headers || {}) },
  });
  let payload = {};
  try { payload = await response.json(); } catch (_) {}
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(payload.error || `Anfrage fehlgeschlagen (${response.status})`);
  }
  return payload;
}

async function apiAudio(path, blob) {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    body: blob,
    headers: { "Content-Type": blob.type || "application/octet-stream", "X-CSRF-Token": cookie("ic_csrf") },
  });
  let payload = {};
  try { payload = await response.json(); } catch (_) {}
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(payload.error || `Anfrage fehlgeschlagen (${response.status})`);
  }
  return payload;
}

async function bootstrapAuth() {
  try {
    const response = await fetch("/api/auth/status", { credentials: "same-origin", cache: "no-store" });
    const status = await response.json();
    if (status.authenticated) {
      $("#loginDialog").close();
      $("#appShell").hidden = false;
      notePwaActivity();
      if (status.state) render(status.state);
      else await load();
    } else showLogin();
  } catch (_) {
    $("#loginError").textContent = "Server nicht erreichbar.";
    showLogin();
  }
}

async function login(event) {
  event.preventDefault();
  const button = $("#loginButton");
  const buttonLabel = $("#loginButtonLabel");
  const error = $("#loginError");
  button.disabled = true;
  button.classList.add("is-loading");
  button.setAttribute("aria-busy", "true");
  buttonLabel.textContent = "Anmelden …";
  error.textContent = "";
  try {
    const result = await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("#loginPassword").value }) });
    $("#loginPassword").value = "";
    $("#loginDialog").close();
    $("#appShell").hidden = false;
    notePwaActivity();
    if (result.state) render(result.state);
    else await load();
  } catch (exception) {
    error.textContent = exception.message;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    buttonLabel.textContent = "Anmelden";
  }
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 3000);
}

function setVoiceStatus(message = "", error = false) {
  const node = $("#voiceStatus");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = !message;
}

function voiceIsRecording() {
  return state.voiceRecorder?.state === "recording";
}

function formatVoiceDuration() {
  const elapsed = Math.min(Date.now() - state.voiceStartedAt, VOICE_MAX_DURATION_MS);
  return `${String(Math.floor(elapsed / 1000)).padStart(2, "0")} s / 60 s`;
}

function updateVoiceButton() {
  const button = $("#voiceButton");
  if (!button) return;
  const recording = voiceIsRecording();
  const transcribing = state.voiceTranscribing;
  button.disabled = state.busy || transcribing;
  button.classList.toggle("recording", recording);
  button.classList.toggle("transcribing", transcribing);
  button.setAttribute("aria-pressed", recording ? "true" : "false");
  if (recording) {
    button.textContent = "■";
    button.setAttribute("aria-label", "Spracheingabe beenden");
    button.title = "Spracheingabe beenden";
  } else if (transcribing) {
    button.textContent = "…";
    button.setAttribute("aria-label", "Audio wird transkribiert");
    button.title = "Audio wird transkribiert";
  } else {
    button.textContent = "🎙";
    button.setAttribute("aria-label", "Spracheingabe starten");
    button.title = "Spracheingabe starten";
  }
  updateChatControls();
}

function updateChatControls() {
  const sendButton = $("#sendButton");
  const steerButton = $("#steerButton");
  const inputAvailable = !voiceIsRecording() && !state.voiceTranscribing;
  if (sendButton) {
    sendButton.disabled = !inputAvailable;
    sendButton.textContent = state.busy ? "Einreihen" : "Senden";
  }
  if (steerButton) {
    steerButton.hidden = !state.busy;
    steerButton.disabled = !inputAvailable;
  }
  updateChatQueueStatus();
}

function stopVoiceCapture(recorder = state.voiceRecorder) {
  if (state.voiceTimer) clearInterval(state.voiceTimer);
  state.voiceTimer = null;
  if (state.voiceStream) {
    state.voiceStream.getTracks().forEach((track) => track.stop());
    state.voiceStream = null;
  }
  if (state.voiceRecorder === recorder) state.voiceRecorder = null;
  updateVoiceButton();
}

function stopVoiceRecording() {
  const recorder = state.voiceRecorder;
  if (recorder?.state === "recording") recorder.stop();
}

async function transcribeVoice(blob) {
  state.voiceTranscribing = true;
  setVoiceStatus("Aufnahme wird transkribiert …");
  updateVoiceButton();
  try {
    const result = await apiAudio("/api/transcribe", blob);
    const transcript = String(result.transcript || "").trim();
    if (!transcript) throw new Error("OpenAI hat kein Transkript zurückgegeben.");
    const input = $("#messageInput");
    const current = input.value.trim();
    input.value = current ? `${current}\n${transcript}` : transcript;
    input.dispatchEvent(new Event("input"));
    updateVoiceButton();
    input.focus();
    setVoiceStatus("Transkript eingefügt. Bitte prüfen und anschließend senden.");
  } catch (error) {
    setVoiceStatus(error.message, true);
    toast(error.message, true);
  } finally {
    state.voiceTranscribing = false;
    updateVoiceButton();
  }
}

async function toggleVoiceInput() {
  if (state.busy || state.voiceTranscribing) return;
  if (voiceIsRecording()) {
    stopVoiceRecording();
    return;
  }
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    const message = "Spracheingabe benötigt eine HTTPS-Verbindung und einen unterstützten Browser.";
    setVoiceStatus(message, true);
    toast(message, true);
    return;
  }
  setVoiceStatus("Mikrofon wird aktiviert …");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const mimeType = typeof MediaRecorder.isTypeSupported === "function"
      ? VOICE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || ""
      : "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    state.voiceStream = stream;
    state.voiceRecorder = recorder;
    state.voiceStartedAt = Date.now();
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) chunks.push(event.data);
    });
    recorder.addEventListener("error", () => {
      stopVoiceCapture(recorder);
      setVoiceStatus("Die Audioaufnahme ist fehlgeschlagen.", true);
    });
    recorder.addEventListener("stop", () => {
      const recordedType = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunks, { type: recordedType });
      stopVoiceCapture(recorder);
      if (blob.size) transcribeVoice(blob);
      else setVoiceStatus("Es wurde keine Sprache aufgenommen.", true);
    }, { once: true });
    recorder.start();
    setVoiceStatus(`Aufnahme läuft · ${formatVoiceDuration()}`);
    updateVoiceButton();
    state.voiceTimer = setInterval(() => {
      if (!voiceIsRecording()) return;
      setVoiceStatus(`Aufnahme läuft · ${formatVoiceDuration()}`);
      if (Date.now() - state.voiceStartedAt >= VOICE_MAX_DURATION_MS) stopVoiceRecording();
    }, 250);
  } catch (error) {
    stopVoiceCapture();
    const message = error.name === "NotAllowedError"
      ? "Der Mikrofonzugriff wurde nicht erlaubt."
      : "Das Mikrofon konnte nicht aktiviert werden.";
    setVoiceStatus(message, true);
    toast(message, true);
  }
}

function notificationPermission() {
  return "Notification" in window ? Notification.permission : "unsupported";
}

function renderNotificationStatus() {
  const node = $("#notificationStatus");
  const button = $("#notificationEnableButton");
  const permission = notificationPermission();
  if (!node || !button) return;
  node.textContent = permission === "granted" ? "Aktiv" : permission === "denied" ? "Im Browser blockiert" : permission === "unsupported" ? "Von diesem Browser nicht unterstützt" : "Noch nicht aktiviert";
  button.disabled = permission === "granted" || permission === "unsupported";
  button.textContent = permission === "granted" ? "Aktiviert" : "Benachrichtigungen aktivieren";
}

async function enableNotifications() {
  if (!("Notification" in window)) { toast("Dieser Browser unterstützt keine PWA-Benachrichtigungen", true); return; }
  const permission = await Notification.requestPermission();
  renderNotificationStatus();
  if (permission === "granted") toast("PWA-Benachrichtigungen aktiviert");
}

async function showPwaNotification(title, options, key) {
  if (notificationPermission() !== "granted" || state.notificationKeys.has(key)) return;
  state.notificationKeys.add(key);
  try {
    const registration = await navigator.serviceWorker.ready;
    await registration.showNotification(title, { icon: "/icon.svg", badge: "/icon.svg", ...options });
  } catch (_) {}
}

function notifyState(data) {
  const pendingDrafts = (data.drafts || []).filter(draft => draft.status !== "pushed").length;
  if (pendingDrafts) showPwaNotification("Intervals Coach", { body: `${pendingDrafts} Trainingsentwurf/-entwürfe warten auf deine Freigabe.`, tag: "drafts" }, `drafts:${pendingDrafts}`);
  const next = data.planning?.season?.next_event;
  if (next && next.days_until >= 0 && next.days_until <= 3) showPwaNotification("Wettkampf steht bevor", { body: `${next.name} ist in ${next.days_until} Tag(en).`, tag: `competition:${next.id}` }, `competition:${next.id}:${next.event_date}`);
  const error = data.sync?.last_error || data.garmin_sync?.status?.includes("Fehler") && data.garmin_sync.status;
  if (error) showPwaNotification("Intervals Coach benötigt Aufmerksamkeit", { body: String(error), tag: "sync-error" }, `error:${error}`);
}

function todayIso() { return new Date().toISOString().slice(0, 10); }

function setFormValue(form, name, value) {
  const field = form?.elements?.namedItem(name);
  if (field) field.value = value == null ? "" : value;
}

function renderLocalFeedback(data) {
  const form = $("#feedbackForm");
  const feedback = data.local_feedback || {};
  const today = feedback.today || {};
  if (form && !form.contains(document.activeElement)) {
    setFormValue(form, "checkin_date", today.checkin_date || todayIso());
    for (const field of ["available_minutes", "soreness", "stress", "motivation", "session_rpe", "illness", "pain", "availability_notes", "notes"]) setFormValue(form, field, today[field]);
  }
  const history = $("#feedbackHistory");
  const summary = $("#feedbackSummary");
  if (summary) summary.textContent = today.checkin_date ? `Letzter Check-in: ${dateLabel(today.checkin_date)}` : "Noch kein Eintrag";
  if (!history) return;
  history.replaceChildren();
  for (const entry of (feedback.recent || []).slice(0, 7)) {
    const node = document.createElement("div");
    node.className = "feedback-entry";
    const scores = [entry.soreness == null ? "" : `Muskelkater ${entry.soreness}/10`, entry.stress == null ? "" : `Stress ${entry.stress}/10`, entry.motivation == null ? "" : `Motivation ${entry.motivation}/10`, entry.session_rpe == null ? "" : `RPE ${entry.session_rpe}/10`].filter(Boolean).join(" · ");
    node.innerHTML = `<strong>${escapeHtml(entry.checkin_date)}</strong>${scores ? ` · ${escapeHtml(scores)}` : ""}${entry.available_minutes == null ? "" : ` · ${escapeHtml(String(entry.available_minutes))} Min.`}${entry.illness || entry.pain ? `<br>${escapeHtml([entry.illness, entry.pain].filter(Boolean).join(" · "))}` : ""}`;
    history.append(node);
  }
}

function renderPlanning(data) {
  const planning = data.planning || {};
  const next = planning.season?.next_event;
  const summary = $("#planningSummary");
  if (summary) summary.textContent = next ? `Nächster Wettkampf: ${next.name} am ${dateLabel(next.event_date)} · Phase: ${next.phase} · ${next.days_until} Tage` : "Noch kein zukünftiger Wettkampf gespeichert.";
  const compact = $("#planningSummaryCompact");
  if (compact) compact.textContent = next ? `${next.name} · ${next.days_until} Tage` : "Kein zukünftiger Wettkampf";
  const preview = planning.latest_replan;
  const node = $("#replanPreview");
  const apply = $("#applyReplanButton");
  if (!node) return;
  if (!preview || preview.status !== "preview") {
    node.hidden = true;
    if (apply) apply.hidden = true;
    return;
  }
  node.hidden = false;
  const signals = preview.signals?.length ? `Signale: ${preview.signals.map(escapeHtml).join(", ")}` : "Keine kritischen lokalen Signale erkannt.";
  const changes = (preview.changes || []).map(change => `<div class="replan-change"><strong>${escapeHtml(change.date || "")}: ${escapeHtml(change.name || "Einheit")}</strong><br>${escapeHtml(change.before?.description || "")}<br>→ ${escapeHtml(change.after?.description || "")}</div>`).join("");
  node.innerHTML = `<div><strong>${escapeHtml(preview.message || "Adaptive Prüfung")}</strong><br>${signals}</div>${changes || "<div>Es gibt keine lokalen Entwürfe, die angepasst werden müssen.</div>"}<small>${escapeHtml(preview.scope || "")}</small>`;
  if (apply) { apply.hidden = !(preview.changes || []).length; apply.dataset.adjustmentId = preview.id || ""; }
}

function renderExternalCalendar(data) {
  const calendar = data.external_calendar || {};
  const status = $("#externalCalendarConnectionStatus");
  const syncButton = $("#externalCalendarSyncButton");
  if (status) {
    status.textContent = calendar.configured ? (calendar.last_error ? "Fehler bei letzter Aktualisierung" : "Konfiguriert · nur lesend") : "Nicht konfiguriert";
    status.className = calendar.configured && !calendar.last_error ? "configured" : "not-configured";
  }
  if (syncButton) {
    syncButton.disabled = Boolean(calendar.running || state.localSync.externalCalendar);
    syncButton.textContent = calendar.running || state.localSync.externalCalendar ? "Synchronisierung läuft…" : "Synchronisieren";
  }
  const root = $("#externalCalendarEvents");
  if (!root) return;
  const events = calendar.events || [];
  if (!calendar.configured) {
    root.textContent = "Kein externer Kalender konfiguriert.";
    return;
  }
  if (!events.length) {
    root.textContent = calendar.last_error ? `Kalender: ${calendar.last_error}` : "Keine externen Termine in den nächsten 90 Tagen.";
    return;
  }
  const items = events.slice(0, 12).map((event) => {
    const time = event.all_day ? "Ganztägig" : `${formatTime(event.start_local)} – ${formatTime(event.end_local)}`;
    const duration = `${event.duration_minutes || 0} Min.`;
    return `<div class="external-calendar-event"><strong>${escapeHtml(String(event.name || "Kalendereintrag"))}</strong><span>${escapeHtml(String(event.event_date || ""))} · ${escapeHtml(time)} · ${escapeHtml(duration)}</span></div>`;
  }).join("");
  root.innerHTML = `<div class="external-calendar-heading"><strong>Externe Termine</strong><span>nächste 90 Tage · ${events.length} Einträge</span></div>${items}`;
}

function renderPublicCalendar(data) {
  return;
  const root = $("#publicCalendarCandidates");
  if (!root) return;
  root.replaceChildren();
  const candidates = data.public_calendar?.candidates || [];
  if (!candidates.length) return;
  for (const candidate of candidates.slice(0, 30)) {
    const card = document.createElement("article");
    card.className = "public-calendar-candidate";
    const imported = Boolean(candidate.imported_competition_id);
    card.innerHTML = `<div><strong>${escapeHtml(candidate.name)}</strong><span>${escapeHtml(candidate.event_date)} · ${escapeHtml(candidate.sport)}</span></div>${candidate.location ? `<span>${escapeHtml(candidate.location)}</span>` : ""}${candidate.description ? `<p>${escapeHtml(candidate.description)}</p>` : ""}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button";
    button.textContent = imported ? "Als Wettkampf übernommen" : "Als Wettkampf übernehmen";
    button.disabled = imported;
    button.addEventListener("click", () => importPublicCandidate(candidate.id, button));
    card.append(button);
    root.append(card);
  }
}

function formatTime(value) {
  if (!value) return "Noch nicht aktualisiert";
  const dt = new Date(value);
  return Number.isNaN(dt.valueOf()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(dt);
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function inlineMarkdown(value) {
  let html = escapeHtml(value);
  const codeSpans = [];
  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `\u0000code${codeSpans.length}\u0000`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__(.+?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  return html.replace(/\u0000code(\d+)\u0000/g, (_, index) => codeSpans[Number(index)]);
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r/g, "").split("\n");
  const output = [];
  let paragraph = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  const flushParagraph = () => {
    if (paragraph.length) {
      output.push(`<p>${inlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
      paragraph = [];
    }
  };

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      flushParagraph(); closeList();
      if (inCode) {
        output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }
    if (!line.trim()) { flushParagraph(); closeList(); continue; }
    const heading = line.match(/^\s*(#{1,3})\s+(.+?)\s*#*\s*$/);
    if (heading) { flushParagraph(); closeList(); output.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`); continue; }
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { flushParagraph(); closeList(); output.push("<hr>"); continue; }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) { closeList(); output.push(`<${nextType}>`); listType = nextType; }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) { flushParagraph(); closeList(); output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); continue; }
    closeList(); paragraph.push(line);
  }
  if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  flushParagraph(); closeList();
  return output.join("");
}

function renderStatus(data) {
  const configured = data.configured;
  const morning = data.morning_checkin || {};
  const missing = [];
  if (!configured.openai) missing.push("OpenAI-API-Schlüssel");
  if (!configured.intervals) missing.push("Intervals.icu-API-Schlüssel");
  const performanceRefresh = data.performance_refresh || {};
  const error = data.sync.last_error || data.library_sync?.last_error || morning.last_error || performanceRefresh.last_error;
  const statusCard = $("#statusCard");
  const activePanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  const hasProblem = Boolean(missing.length || error);
  statusCard.hidden = !hasProblem || activePanel === "settingsPanel";
  statusCard.classList.toggle("warning", hasProblem);
  $("#statusTitle").textContent = missing.length
    ? `Einrichtung nötig: ${missing.join(" + ")}`
    : error ? "Coach benötigt Aufmerksamkeit" : "Coach ist bereit";
  $("#statusDetail").textContent = missing.length
    ? "Ergänze die fehlende Serverkonfiguration"
    : error || (morning.status === "ready" ? `Morgen-Check-in abgeschlossen: ${formatTime(morning.date)}` : "Bereit für deine nächste Frage");
  statusCard.classList.remove("working");
}

function dateLabel(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? String(value).slice(0, 10) : new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(parsed);
}

const PLANNED_CALENDAR_WEEKS = 5;

function localDateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function plannedEventDate(event) {
  return String(event?.start_date_local || event?.date || "").slice(0, 10);
}

function plannedDayLabel(date, offset) {
  const formatted = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long" }).format(date);
  if (offset === 0) return `Heute · ${formatted}`;
  if (offset === 1) return `Morgen · ${formatted}`;
  return formatted;
}

function plannedWeekStart(date) {
  const start = new Date(date);
  const day = start.getDay();
  start.setDate(start.getDate() - (day === 0 ? 6 : day - 1));
  start.setHours(0, 0, 0, 0);
  return start;
}

function plannedWeekLabel(start) {
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const format = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "short" });
  return `${format.format(start)} – ${format.format(end)} ${end.getFullYear()}`;
}

function plannedWeekSummary(events) {
  const duration = events.reduce((total, event) => total + (Number(event.moving_time) || 0), 0);
  const distance = events.reduce((total, event) => total + (Number(event.distance) || 0), 0);
  const load = events.reduce((total, event) => total + (Number(event.icu_training_load) || 0), 0);
  const values = [`${events.length} ${events.length === 1 ? "Einheit" : "Einheiten"}`];
  if (duration > 0) values.push(`${(duration / 3600).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} h`);
  if (distance > 0) values.push(`${(distance / 1000).toLocaleString("de-DE", { maximumFractionDigits: 0 })} km`);
  if (load > 0) values.push(`Belastung ${Math.round(load).toLocaleString("de-DE")}`);
  return values.join(" · ");
}

function weatherForDate(date) {
  return (state.data?.weather?.days || []).find((item) => item.date === date) || null;
}

function weatherNumber(value, suffix = "") {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number)}${suffix}` : "–";
}

function weatherDirection(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return ["N", "NO", "O", "SO", "S", "SW", "W", "NW"][Math.round(number / 45) % 8];
}

function renderWeatherNotice(weather) {
  const notice = $("#weatherNotice");
  if (!notice) return;
  notice.hidden = false;
  notice.className = "weather-notice";
  if (!weather?.configured) {
    notice.textContent = "Wetterhinweise: Hinterlege im Profil einen Wetterort (Stadt oder PLZ).";
    return;
  }
  if (weather.error && !weather.days?.length) {
    notice.classList.add("error");
    notice.textContent = weather.error;
    return;
  }
  const location = [weather.location?.name, weather.location?.country].filter(Boolean).join(", ");
  notice.textContent = `${location ? `Wetter für ${location}` : "Wettervorhersage"} · ${weather.model || "Open-Meteo"} · Tageswerte bis 14 Tage · Zeitvorschläge bis 5 Tage · Quelle: Open-Meteo.com${weather.stale ? " · letzte verfügbare Daten" : ""}`;
}

function distanceLabel(value) {
  const distance = Number(value);
  if (!Number.isFinite(distance) || distance <= 0) return null;
  return `${(distance / 1000).toFixed(1)} km`;
}

function activitySportLabel(activity) {
  const value = String(activity?.type || activity?.sport || activity?.sport_type || activity?.name || "").toLowerCase();
  if (/ride|bike|cycling|rad|velo|bicycle/.test(value)) return "Radfahren";
  if (/run|lauf|jog/.test(value)) return "Laufen";
  if (/swim|schwimm/.test(value)) return "Schwimmen";
  if (/strength|kraft|gym|weight/.test(value)) return "Kraft";
  return "Andere";
}

function activityTypeKey(activity) {
  return String(activity?.type || activity?.sport || activity?.sport_type || "Sportart unbekannt").trim() || "Sportart unbekannt";
}

function renderActivityFilters(activities) {
  const root = $("#activityFilters");
  if (!root) return;
  root.replaceChildren();
  const counts = new Map();
  (Array.isArray(activities) ? activities : []).forEach((activity) => {
    const type = activityTypeKey(activity);
    counts.set(type, (counts.get(type) || 0) + 1);
  });
  if (!counts.size) {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  const label = document.createElement("span");
  label.className = "activity-filters-label";
  label.textContent = "Typ filtern:";
  root.append(label);
  [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "de")).forEach(([type, count]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `activity-filter-button${state.activityTypes.has(type) ? " active" : ""}`;
    button.textContent = `${type} (${count})`;
    button.setAttribute("aria-pressed", state.activityTypes.has(type) ? "true" : "false");
    button.addEventListener("click", () => {
      if (state.activityTypes.has(type)) state.activityTypes.delete(type);
      else state.activityTypes.add(type);
      renderActivities(state.data?.activities || []);
    });
    root.append(button);
  });
  if (state.activityTypes.size) {
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "activity-filter-button clear";
    clear.textContent = "Zurücksetzen";
    clear.addEventListener("click", () => {
      state.activityTypes.clear();
      renderActivities(state.data?.activities || []);
    });
    root.append(clear);
  }
}

function renderActivityStats(activities) {
  const root = $("#activityStats");
  if (!root) return;
  root.replaceChildren();
  const list = Array.isArray(activities) ? activities : [];
  const counts = new Map();
  list.forEach((activity) => counts.set(activitySportLabel(activity), (counts.get(activitySportLabel(activity)) || 0) + 1));
  const entries = [["Einheiten gesamt", list.length], ...[...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "de")).map(([sport, count]) => [`${sport}`, count])];
  entries.forEach(([label, value]) => {
    const card = document.createElement("div");
    const number = document.createElement("strong");
    number.textContent = String(value);
    const caption = document.createElement("span");
    caption.textContent = label;
    card.append(number, caption);
    root.append(card);
  });
}

function renderActivities(activities) {
  const list = Array.isArray(activities) ? activities : [];
  const syncDetail = $("#activitySyncDetail");
  const syncNotices = [];
  if (state.data?.provider_resync?.intervals?.running || state.localSync.intervalsFull) syncNotices.push(state.data?.provider_resync?.intervals?.status || "Intervals.icu wird vollständig neu geladen…");
  if (state.data?.provider_resync?.garmin?.running || state.localSync.garminFull) syncNotices.push(state.data?.provider_resync?.garmin?.status || "Garmin wird vollständig neu geladen…");
  if (state.data?.sync?.running || state.localSync.intervals) syncNotices.push(state.data?.sync?.status || "Intervals.icu wird synchronisiert…");
  if (syncDetail) {
    const refreshedAt = state.data?.sync?.last_sync_at;
    syncDetail.textContent = syncNotices.length
      ? syncNotices.join(" · ")
      : refreshedAt ? `Letzte Aktualisierung: ${formatTime(refreshedAt)}` : "Noch nicht aktualisiert";
  }
  renderActivityFilters(list);
  const filteredActivities = state.activityTypes.size
    ? list.filter((activity) => state.activityTypes.has(activityTypeKey(activity)))
    : list;
  renderActivityStats(filteredActivities);
  const root = $("#activities");
  root.replaceChildren();
  if (!filteredActivities.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("strong");
    title.textContent = list.length ? "Keine passenden Einheiten" : "Noch keine absolvierten Einheiten";
    empty.append(title, document.createTextNode(list.length ? "Wähle einen weiteren Aktivitätstyp oder setze den Filter zurück." : "Aktualisiere die Trainingsdaten, um deine synchronisierten Aktivitäten hier zu sehen."));
    root.append(empty);
    return;
  }
  filteredActivities.slice(0, 250).forEach((activity) => {
    const card = document.createElement("article");
    card.className = "activity-card";
    const top = document.createElement("div");
    top.className = "activity-top";
    const title = document.createElement("h3");
    title.textContent = activity.name || activity.type || "Einheit";
    const date = document.createElement("span");
    date.className = "eyebrow";
    date.textContent = dateLabel(activity.start_date_local);
    top.append(title, date);
    const meta = document.createElement("button");
    meta.type = "button";
    meta.className = "activity-meta";
    meta.classList.add("activity-type-button");
    const type = activityTypeKey(activity);
    meta.textContent = type;
    meta.setAttribute("aria-pressed", state.activityTypes.has(type) ? "true" : "false");
    meta.addEventListener("click", () => {
      if (state.activityTypes.has(type)) state.activityTypes.delete(type);
      else state.activityTypes.add(type);
      renderActivities(state.data?.activities || []);
    });
    const stats = document.createElement("div");
    stats.className = "activity-stats";
    const addStat = (label, value) => {
      if (value == null || value === "") return;
      const item = document.createElement("span");
      item.innerHTML = `${escapeHtml(label)} <strong>${escapeHtml(String(value))}</strong>`;
      stats.append(item);
    };
    addStat("Dauer", formatDuration(activity.moving_time));
    addStat("Distanz", distanceLabel(activity.distance));
    addStat("Belastung", activity.icu_training_load);
    addStat("Ø Puls", activity.average_heartrate ? `${Math.round(activity.average_heartrate)} bpm` : null);
    addStat("Ø Leistung", activity.average_watts ? `${Math.round(activity.average_watts)} W` : null);
    card.append(top, meta, stats);
    root.append(card);
  });
  if (filteredActivities.length > 250) {
    const note = document.createElement("p");
    note.className = "fine-print";
    note.textContent = "Es werden die 250 neuesten Einheiten angezeigt.";
    root.append(note);
  }
}

function renderParallelCyclingWarning(groups) {
  const root = $("#parallelCyclingWarning");
  if (!root) return;
  root.replaceChildren();
  root.hidden = !groups?.length;
  if (!groups?.length) return;

  const title = document.createElement("strong");
  title.textContent = "Parallele Radeinheiten erkannt";
  const intro = document.createElement("p");
  intro.textContent = "Bitte auswählen, welche Einheit aus Intervals.icu gelöscht werden soll. Es wird nur die ausgewählte Einheit per API entfernt.";
  root.append(title, intro);
  groups.forEach((group, groupIndex) => {
    const groupRoot = document.createElement("div");
    groupRoot.className = "parallel-cycling-group";
    const options = document.createElement("div");
    options.className = "parallel-cycling-options";
    group.forEach((event, eventIndex) => {
      const label = document.createElement("label");
      label.className = "parallel-cycling-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = `parallel-cycling-${groupIndex}`;
      radio.value = String(event.id);
      radio.checked = eventIndex === 0;
      const text = document.createElement("span");
      text.textContent = `${event.name || "Radeinheit"} · ${dateLabel(event.start_date_local || event.date)}${event.type ? ` · ${event.type}` : ""}`;
      label.append(radio, text);
      options.append(label);
    });
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "secondary-button danger-button";
    deleteButton.textContent = "Ausgewählte Einheit löschen";
    deleteButton.addEventListener("click", () => {
      const selectedId = options.querySelector("input:checked")?.value;
      const selected = group.find((event) => String(event.id) === selectedId);
      if (selected) deletePlanned(selected.id, deleteButton, selected.name);
    });
    groupRoot.append(options, deleteButton);
    root.append(groupRoot);
  });
}

function renderPlanned(planned) {
  renderParallelCyclingWarning(state.data?.parallel_cycling || []);
  renderWeatherNotice(state.data?.weather);
  const root = $("#plannedCalendar");
  root.querySelectorAll("details.planned-week").forEach((week) => state.plannedWeekOpen.set(week.dataset.week, week.open));
  root.replaceChildren();
  const eventsByDate = new Map();
  (planned || []).forEach((event) => {
    const date = plannedEventDate(event);
    if (!date) return;
    if (!eventsByDate.has(date)) eventsByDate.set(date, []);
    eventsByDate.get(date).push(event);
  });

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const firstWeek = plannedWeekStart(today);
  for (let weekIndex = 0; weekIndex < PLANNED_CALENDAR_WEEKS; weekIndex += 1) {
    const weekStart = new Date(firstWeek);
    weekStart.setDate(firstWeek.getDate() + weekIndex * 7);
    const weekKey = localDateKey(weekStart);
    const weekEvents = [];
    for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
      const date = new Date(weekStart);
      date.setDate(weekStart.getDate() + dayIndex);
      weekEvents.push(...(eventsByDate.get(localDateKey(date)) || []));
    }

    const weekRoot = document.createElement("details");
    weekRoot.className = "planned-week";
    weekRoot.dataset.week = weekKey;
    weekRoot.open = state.plannedWeekOpen.has(weekKey) ? state.plannedWeekOpen.get(weekKey) : weekIndex === 0;
    weekRoot.addEventListener("toggle", () => state.plannedWeekOpen.set(weekKey, weekRoot.open));
    const weekHeading = document.createElement("summary");
    weekHeading.className = "planned-week-heading";
    const weekTitle = document.createElement("span");
    weekTitle.className = "planned-week-title";
    weekTitle.textContent = plannedWeekLabel(weekStart);
    if (weekIndex === 0) {
      const current = document.createElement("small");
      current.textContent = "Diese Woche";
      weekTitle.append(current);
    }
    const weekSummary = document.createElement("span");
    weekSummary.className = "planned-week-summary";
    weekSummary.textContent = plannedWeekSummary(weekEvents);
    weekHeading.append(weekTitle, weekSummary);
    weekRoot.append(weekHeading);

    const weekDays = document.createElement("div");
    weekDays.className = "planned-week-days";
    for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
      const day = new Date(weekStart);
      day.setDate(weekStart.getDate() + dayIndex);
      const date = localDateKey(day);
      const events = eventsByDate.get(date) || [];
      const dayRoot = document.createElement("section");
      dayRoot.className = "planned-day";

      const heading = document.createElement("div");
      heading.className = "planned-day-heading";
      const title = document.createElement("h3");
      title.textContent = plannedDayLabel(day, Math.round((day - today) / 86400000));
      const count = document.createElement("span");
      count.className = "planned-day-count";
      count.textContent = events.length ? `${events.length} ${events.length === 1 ? "Einheit" : "Einheiten"}` : "frei";
      heading.append(title, count);
      dayRoot.append(heading);

      const weather = weatherForDate(date);
      if (weather) {
        const weatherRoot = document.createElement("div");
        weatherRoot.className = "planned-weather";
        const condition = document.createElement("strong");
        condition.textContent = weather.condition || "Wetter";
        const summary = document.createElement("span");
        const direction = weatherDirection(weather.wind_direction_dominant);
        summary.textContent = `${weatherNumber(weather.temperature_min, " °C")} bis ${weatherNumber(weather.temperature_max, " °C")} · Regenrisiko ${weatherNumber(weather.precipitation_probability_max, " %")} · Wind bis ${weatherNumber(weather.wind_speed_max, " km/h")} / Böen ${weatherNumber(weather.wind_gusts_max, " km/h")}${direction ? ` aus ${direction}` : ""}`;
        weatherRoot.append(condition, summary);
        dayRoot.append(weatherRoot);
      }

      if (!events.length) {
        const empty = document.createElement("p");
        empty.className = "planned-day-empty";
        empty.textContent = "Keine Einheit geplant";
        dayRoot.append(empty);
      } else {
        const entries = document.createElement("div");
        entries.className = "planned-day-entries";
        events.forEach((event) => {
          const details = document.createElement("details");
          details.className = "planned-entry";
          const summary = document.createElement("summary");
          const summaryMain = document.createElement("span");
          summaryMain.className = "planned-summary-main";
          const eventTitle = document.createElement("strong");
          eventTitle.textContent = event.name || "Geplante Einheit";
          const meta = document.createElement("span");
          meta.className = "planned-meta";
          meta.textContent = [event.type, event.category, event.moving_time ? `Dauer ${formatDuration(event.moving_time)}` : null].filter(Boolean).join(" · ");
          summaryMain.append(eventTitle, meta);
          summary.append(summaryMain);
          details.append(summary);

          const body = document.createElement("div");
          body.className = "planned-entry-body";
          if (event.description) {
            const description = document.createElement("div");
            description.className = "planned-description";
            description.textContent = event.description;
            body.append(description);
          }
          if (event.weather_recommendation) {
            const recommendation = document.createElement("div");
            recommendation.className = "planned-weather-recommendation";
            const recommendationTitle = document.createElement("strong");
            recommendationTitle.textContent = `Beste Wetterzeit: ${event.weather_recommendation.suggested_time}`;
            const recommendationReason = document.createElement("span");
            const direction = weatherDirection(event.weather_recommendation.wind_direction);
            recommendationReason.textContent = `${event.weather_recommendation.reason || "Günstigstes verfügbares Zeitfenster laut Vorhersage."}${direction ? ` Windrichtung: ${direction}.` : ""}`;
            recommendation.append(recommendationTitle, recommendationReason);
            body.append(recommendation);
          }
          if (event.id != null) {
            const actions = document.createElement("div");
            actions.className = "card-actions";
            const button = document.createElement("button");
            button.type = "button";
            button.className = "secondary-button danger-button";
            button.textContent = "Einheit löschen";
            button.addEventListener("click", () => deletePlanned(event.id, button, event.name));
            actions.append(button);
            body.append(actions);
          }
          details.append(body);
          entries.append(details);
        });
        dayRoot.append(entries);
      }
      weekDays.append(dayRoot);
    }
    weekRoot.append(weekDays);
    root.append(weekRoot);
  }
}

async function deletePlanned(eventId, button, name) {
  if (!window.confirm(`„${name || "Geplante Einheit"}“ wirklich aus Intervals.icu löschen?`)) return;
  button.disabled = true;
  button.textContent = "Wird gelöscht…";
  try {
    await api(`/api/planned/${encodeURIComponent(eventId)}`, { method: "DELETE" });
    toast("Geplante Einheit gelöscht");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = "Einheit löschen";
  }
}

function chatIsNearBottom() {
  return document.documentElement.scrollHeight - (window.scrollY + window.innerHeight) <= 48;
}

function updateChatComposerVisibility() {
  const panel = $("#chatPanel");
  if (!panel) return;
  panel.classList.toggle("chat-composer-hidden", !chatIsNearBottom());
}

function updateChatQueueStatus() {
  const status = $("#chatQueueStatus");
  if (!status) return;
  const count = state.chatQueue.length;
  if (!state.busy || !count) {
    status.hidden = true;
    status.textContent = "";
    return;
  }
  const steering = state.chatQueue.filter((entry) => entry.mode === "steer").length;
  const queued = count - steering;
  const details = [];
  if (steering) details.push(`${steering} Steuerung${steering === 1 ? "" : "en"}`);
  if (queued) details.push(`${queued} Nachricht${queued === 1 ? "" : "en"} in der Warteschlange`);
  status.hidden = false;
  status.textContent = `${details.join(" · ")} · wird nach der aktuellen Antwort verarbeitet`;
}

function createCoachWorkingIndicator() {
  const node = document.createElement("div");
  node.id = "coachWorking";
  node.className = "coach-working";
  node.setAttribute("aria-live", "polite");
  node.innerHTML = '<span class="working-dots" aria-hidden="true"><i></i><i></i><i></i></span><span>Coach arbeitet an deiner Antwort…</span>';
  return node;
}

function createPendingMessage(entry) {
  const node = document.createElement("div");
  node.className = "message user pending";
  node.textContent = entry.message;
  const label = document.createElement("span");
  label.className = "pending-label";
  label.textContent = entry.mode === "steer" ? "Steuerung · als Nächstes" : "Warteschlange · danach";
  node.append(label);
  return node;
}

function renderMessages(messages, forceScroll = false) {
  const root = $("#messages");
  // Synchronisation and refresh notices belong to their respective tabs,
  // not to the personal conversation history.
  const visibleMessages = (messages || []).filter((message) => message.role !== "event");
  const signature = JSON.stringify([
    visibleMessages.map((message) => [message.id || null, message.created_at || null, message.role, message.content]),
    state.busy,
    state.chatQueue.map((entry) => [entry.id, entry.mode, entry.message]),
  ]);
  if (root.dataset.signature === signature) return;
  const shouldScroll = forceScroll || chatIsNearBottom();
  root.dataset.signature = signature;
  root.replaceChildren();
  if (!visibleMessages.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("strong");
    title.textContent = "Dein Coach ist bereit";
    empty.append(title, document.createTextNode("Lege deine Ziele im Profil fest. Bitte den Coach jederzeit, deine letzten Einheiten neu zu analysieren."));
    root.append(empty);
  }
  for (const message of visibleMessages) {
    const node = document.createElement("div");
    node.className = `message ${message.role}`;
    if (message.role === "assistant") node.innerHTML = markdownToHtml(message.content);
    else node.textContent = message.content;
    root.append(node);
  }
  for (const entry of state.chatQueue) root.append(createPendingMessage(entry));
  if (state.busy) root.append(createCoachWorkingIndicator());
  updateChatQueueStatus();
  updateChatComposerVisibility();
  if (shouldScroll) scrollChatToLatest();
}

function scrollChatToLatest() {
  const panel = $("#chatPanel");
  const root = $("#messages");
  if (!panel?.classList.contains("active") || !root) return;
  requestAnimationFrame(() => {
    const target = root.lastElementChild;
    if (!target) return;
    const composer = $("#chatForm");
    const bottomOffset = (composer?.offsetHeight || 70) + 94 + (window.visualViewport?.offsetTop || 0);
    const targetBottom = target.getBoundingClientRect().bottom + window.scrollY;
    window.scrollTo({ top: Math.max(0, targetBottom - window.innerHeight + bottomOffset), behavior: "auto" });
  });
}

function renderContextPreview(preview) {
  const status = $("#systemContextPreviewStatus");
  const content = $("#systemContextPreviewContent");
  if (!status || !content) return;
  content.replaceChildren();
  content.hidden = true;
  if (!preview) {
    status.textContent = "Noch nicht geladen.";
    status.classList.remove("error");
    return;
  }
  const sections = [
    ["Zusammensetzung", preview.assembly],
    ["Dauerhaftes Profil", preview.structured_athlete_context?.durable_profile],
    ["Zielwettkämpfe", preview.structured_athlete_context?.target_competitions],
    ["Aktuelle Leistungsdaten", preview.structured_athlete_context?.current_performance],
    ["Garmin-Kontext", preview.structured_athlete_context?.garmin],
    ["Gesprächskontinuität", preview.conversation],
    ["Intervals.icu-Snapshot", preview.latest_intervals_snapshot],
    ["Letzte Chat-Eingabe (input)", preview.chat_prompt],
    ["Kontext (instructions)", preview.context_text],
  ];
  sections.forEach(([title, value], index) => {
    if (value == null) return;
    const details = document.createElement("details");
    if (index < 4) details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    details.append(summary, pre);
    content.append(details);
  });
  status.classList.remove("error");
  status.textContent = `Zuletzt erstellt: ${formatTime(preview.generated_at)}${preview.snapshot_truncated ? " (Snapshot im Coach-Kontext gekürzt)" : ""}`;
  content.hidden = false;
}

function invalidateContextPreview() {
  const button = $("#systemContextPreviewButton");
  if (!button) return;
  button.dataset.loaded = "false";
  button.textContent = "Kontext aktualisieren";
}

async function loadContextPreview() {
  const button = $("#systemContextPreviewButton");
  const status = $("#systemContextPreviewStatus");
  if (!button || !status || button.dataset.loaded === "true") return;
  button.disabled = true;
  button.textContent = "Kontext wird geladen…";
  status.classList.remove("error");
  status.textContent = "Der aktuelle Coach-Kontext wird zusammengestellt…";
  try {
    const preview = await api("/api/context-preview");
    renderContextPreview(preview);
    button.dataset.loaded = "true";
    button.textContent = "Kontext aktualisieren";
  } catch (error) {
    status.classList.add("error");
    status.textContent = error.message;
    button.textContent = "Kontext laden";
  } finally { button.disabled = false; }
}

function renderLibrary(workouts) {
  const root = $("#library");
  if (!root) return;
  root.replaceChildren();
  if (!Array.isArray(workouts) || !workouts.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Keine Einheiten in der Intervals.icu-Trainingsbibliothek gefunden.";
    root.append(empty);
    return;
  }
  const groups = new Map();
  workouts.forEach((workout) => {
    const sport = activitySportLabel(workout);
    if (!groups.has(sport)) groups.set(sport, []);
    groups.get(sport).push(workout);
  });
  [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "de"))
    .forEach(([sport, sportWorkouts]) => {
      const section = document.createElement("details");
      section.className = "library-sport";
      const summary = document.createElement("summary");
      const title = document.createElement("strong");
      title.textContent = sport;
      summary.append(title);
      section.append(summary);
      const cards = document.createElement("div");
      cards.className = "library-sport-cards";
      sportWorkouts.forEach((workout) => {
        const card = document.createElement("article");
        card.className = "library-card";
        const heading = document.createElement("div");
        const cardTitle = document.createElement("h4");
        cardTitle.textContent = workout.name || "Bibliotheks-Einheit";
        const meta = document.createElement("span");
        meta.textContent = [workout.type, workout.moving_time ? formatDuration(workout.moving_time) : null].filter(Boolean).join(" · ");
        heading.append(cardTitle, meta);
        const description = document.createElement("p");
        description.textContent = workout.description || "Kein Workout-Text hinterlegt.";
        const controls = document.createElement("div");
        controls.className = "library-controls";
        const dateLabelNode = document.createElement("label");
        dateLabelNode.textContent = "Datum";
        const dateInput = document.createElement("input");
        dateInput.type = "date";
        dateInput.value = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
        dateLabelNode.append(dateInput);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary-button";
        button.textContent = "Als geplant übernehmen";
        button.addEventListener("click", () => planLibraryWorkout(workout.id, dateInput, button));
        controls.append(dateLabelNode, button);
        card.append(heading, description, controls);
        cards.append(card);
      });
      section.append(cards);
      root.append(section);
    });
}

async function loadLibrary() {
  const button = $("#libraryLoadButton");
  const root = $("#library");
  if (!button || !root) return;
  if (state.data?.provider_resync?.intervals?.running || state.localSync.intervalsFull) {
    toast("Intervals.icu wird gerade vollständig neu geladen.", true);
    return;
  }
  button.disabled = true;
  button.textContent = "Bibliothek wird geladen…";
  try {
    await api("/api/library/sync", { method: "POST", body: "{}" });
    await load();
  } catch (error) {
    root.replaceChildren();
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = error.message;
    root.append(message);
  } finally {
    button.disabled = false;
    button.textContent = "Bibliothek synchronisieren";
  }
}

async function planLibraryWorkout(workoutId, dateInput, button) {
  if (!dateInput.value) { toast("Bitte ein Datum auswählen", true); return; }
  button.disabled = true;
  button.textContent = "Wird eingeplant…";
  try {
    await api("/api/library/" + encodeURIComponent(workoutId) + "/plan", { method: "POST", body: JSON.stringify({ date: dateInput.value }) });
    toast("Einheit eingeplant");
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Als geplant übernehmen"; }
}

function renderProfile(profile) {
  if (state.profileDirty) return;
  const form = $("#profileForm");
  for (const [key, value] of Object.entries(profile)) {
    if (form.elements[key]) form.elements[key].value = value || "";
  }
  const summary = $("#profileSummary");
  if (summary) {
    const values = [profile.name, profile.sports, profile.typical_weekly_volume].filter(Boolean);
    summary.textContent = values.length ? values.join(" · ") : "Noch nicht ausgefüllt";
  }
}

function renderGarmin(garmin) {
  const status = $("#garminStatus");
  const detail = $("#garminDetail");
  const button = $("#garminSyncButton");
  const fullButton = $("#garminFullResyncButton");
  const fullStatus = $("#garminFullResyncStatus");
  if (!status || !detail || !button) return;
  const fullResync = state.data?.provider_resync?.garmin || {};
  const fullRunning = Boolean(fullResync.running || state.localSync.garminFull);
  button.disabled = Boolean(state.data?.garmin_sync?.running || fullRunning);
  if (!garmin?.available) {
    status.textContent = "Garmin nicht verfügbar";
    detail.textContent = "";
    button.disabled = true;
    if (fullButton) fullButton.disabled = true;
    return;
  }
  if (!garmin.configured) {
    status.textContent = "Garmin nicht eingerichtet";
    detail.textContent = "";
    button.disabled = true;
    if (fullButton) fullButton.disabled = true;
    return;
  }
  const performanceSources = [garmin.has_vo2max ? "VO2max" : null, garmin.has_estimated_run_times ? "Laufprognosen" : null, garmin.has_max_hr ? "Max HF" : null, garmin.has_weight ? "Gewicht" : null].filter(Boolean);
  status.textContent = garmin.source === "fixture"
    ? "Lokale Garmin-Testdaten aktiv"
    : garmin.last_error ? "Mit Fehlern synchronisiert" : "Optionaler Direktabruf aktiv";
  detail.textContent = garmin.last_sync_at
    ? `Letzter Abruf: ${formatTime(garmin.last_sync_at)} · ${garmin.activities || 0} Aktivitäten · Schlaf/HRV/Readiness ${[garmin.has_sleep, garmin.has_hrv, garmin.has_readiness].filter(Boolean).length}/3`
    : garmin.source === "fixture" ? "Testdatei ist konfiguriert; synchronisiere sie mit dem Button."
      : "Noch kein Garmin-Abruf durchgeführt.";
  if (performanceSources.length) detail.textContent += ` · ${performanceSources.join("/")} aus Garmin`;
  if (fullButton) {
    fullButton.disabled = fullRunning || Boolean(state.data?.garmin_sync?.running || state.localSync.garmin);
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  if (fullStatus) {
    fullStatus.classList.toggle("error", Boolean(fullResync.last_error));
    fullStatus.textContent = fullRunning && fullResync.status
      ? fullResync.status
      : fullResync.last_error
        ? fullResync.last_error
        : fullResync.last_resync_at
          ? `Letzter vollständiger Resync: ${formatTime(fullResync.last_resync_at)}`
          : "Löscht nur lokale Garmin-Daten; Zugangsdaten und Cloud bleiben unverändert.";
  }
}

function contextField(labelText, field, value = "", options = {}) {
  const label = document.createElement("label");
  label.textContent = labelText;
  let input;
  if (options.choices) {
    input = document.createElement("select");
    for (const choice of options.choices) {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice;
      input.append(option);
    }
  } else if (options.multiline) {
    input = document.createElement("textarea");
    input.rows = options.rows || 2;
  } else {
    input = document.createElement("input");
    input.type = options.type || "text";
  }
  input.dataset.field = field;
  input.value = value || "";
  if (options.placeholder) input.placeholder = options.placeholder;
  label.append(input);
  return label;
}

function competitionEditor(competition = {}, index = 0) {
  const card = document.createElement("article");
  card.className = "competition-editor";
  card.dataset.id = competition.id || "";

  const top = document.createElement("div");
  top.className = "competition-editor-top";
  const title = document.createElement("strong");
  title.textContent = competition.name || `Wettkampf ${index + 1}`;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-context-button";
  remove.textContent = "Entfernen";
  remove.addEventListener("click", () => {
    card.remove();
    state.profileDirty = true;
  });
  top.append(title, remove);

  const mainGrid = document.createElement("div");
  mainGrid.className = "form-grid";
  mainGrid.append(
    contextField("Name", "name", competition.name, { placeholder: "Münsterland Giro" }),
    contextField("Datum", "event_date", competition.event_date, { type: "date" }),
    contextField("Startzeit (lokal)", "start_date_local", (competition.start_date_local || "").slice(0, 16), { type: "datetime-local" }),
    contextField("Sportart", "sport", competition.sport || "Radfahren", { placeholder: "Radfahren, Rad indoor, Laufen oder Krafttraining" }),
    contextField("Kategorie", "category", competition.category || `RACE_${competition.priority || "B"}`, { choices: ["RACE_A", "RACE_B", "RACE_C"] }),
    contextField("Dauer (Sekunden)", "moving_time", competition.moving_time, { type: "number", placeholder: "14400" }),
    contextField("Distanz (Meter)", "distance", competition.distance, { placeholder: "125000" }),
    contextField("Externe ID", "external_id", competition.external_id, { placeholder: "Wird automatisch vergeben" })
  );
  card.append(
    top,
    mainGrid,
    contextField("Ergebnisziel", "target", competition.target, { multiline: true, placeholder: "Zielzeit, Platzierung, Finish-Ziel…" }),
    contextField("Streckenprofil", "course_profile", competition.course_profile, { multiline: true, placeholder: "Höhenmeter, Technik, erwartete Dauer…" }),
    contextField("Beschreibung", "description", competition.description, { multiline: true, placeholder: "Beschreibung des Intervals.icu-Events…" }),
    contextField("Notizen", "notes", competition.notes, { multiline: true })
  );
  return card;
}

function renderCompetitions(competitions) {
  if (state.profileDirty) return;
  const root = $("#competitionList");
  const summary = $("#plannedCompetitionsSummary");
  if (summary) {
    const next = competitions.filter((competition) => competition.event_date).sort((a, b) => String(a.event_date).localeCompare(String(b.event_date)))[0];
    summary.textContent = competitions.length
      ? `${competitions.length} ${competitions.length === 1 ? "Wettkampf" : "Wettkämpfe"}${next ? ` · nächster ${dateLabel(next.event_date)}` : ""}`
      : "Noch keine Wettkämpfe";
  }
  root.replaceChildren();
  if (!competitions.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Noch keine Zielwettkämpfe gespeichert.";
    root.append(empty);
    return;
  }
  competitions.forEach((competition, index) => root.append(competitionEditor(competition, index)));
}

function renderCompetitionSync(data) {
  const sync = data.competition_sync || {};
  const fullRunning = Boolean(data.provider_resync?.intervals?.running || state.localSync.intervalsFull);
  const button = $("#competitionSyncButton");
  const detail = $("#competitionSyncDetail");
  if (button) {
    button.disabled = Boolean(sync.running || state.localSync.competitions || fullRunning);
    button.textContent = sync.running || state.localSync.competitions ? "Synchronisierung läuft…" : "Mit Intervals.icu synchronisieren";
  }
  if (detail) {
    detail.textContent = sync.last_error
      ? sync.last_error
      : sync.running
        ? (sync.status || "Zielwettkämpfe werden synchronisiert…")
        : sync.last_sync_at
          ? `Letzte Aktualisierung: ${formatTime(sync.last_sync_at)}`
          : "Noch nicht synchronisiert";
    detail.classList.toggle("error", Boolean(sync.last_error));
  }
}

function collectCompetitions() {
  return [...document.querySelectorAll(".competition-editor")].map((card) => {
    const competition = { id: card.dataset.id || "" };
    card.querySelectorAll("[data-field]").forEach((input) => { competition[input.dataset.field] = input.value.trim(); });
    return competition;
  });
}

function addCompetition() {
  const root = $("#competitionList");
  root.querySelector(".context-empty")?.remove();
  root.append(competitionEditor({}, root.querySelectorAll(".competition-editor").length));
  state.profileDirty = true;
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const total = Math.round(Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}` : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatWhole(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number).toLocaleString("de-DE") : String(value);
}

function formatPace(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const total = Math.round(Number(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")} min/km`;
}

function comparisonText(comparison) {
  if (!comparison || comparison.delta == null) return null;
  const delta = Number(comparison.delta);
  if (!Number.isFinite(delta)) return null;
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const precision = comparison.unit === "" || comparison.unit === "bpm" || comparison.unit === "ms" ? 0 : 1;
  const amount = Math.abs(delta).toFixed(precision).replace(".", ",");
  const unit = comparison.unit ? ` ${comparison.unit}` : "";
  const arrow = comparison.direction === "up" ? "↑" : comparison.direction === "down" ? "↓" : "→";
  return { text: `${arrow} ${sign}${amount}${unit}`, className: comparison.color || "neutral", title: `Vergleich zum ${comparison.label || `${comparison.days}-Tage-Durchschnitt`}` };
}

function metricSourceClass(source) {
  if (source === "Garmin Connect") return "metric-garmin";
  if (source === "Manuell") return "metric-manual";
  if (source && (source.startsWith("Intervals.icu") || source === "Aus Aktivitäten")) return "metric-intervals";
  if (source === "KI-Schätzung" || source === "Berechnete Schätzung") return "metric-estimate";
  return "";
}

function metricToneClass(label, value) {
  if (!label.startsWith("Form") || !Number.isFinite(Number(value))) return "";
  const tsb = Number(value);
  if (tsb >= -10 && tsb <= 5) return "metric-form-good";
  if (tsb >= -20 && tsb <= 15) return "metric-form-caution";
  return "metric-form-bad";
}

function displayMetric(root, label, metricData, formatter = null, editable = null) {
  const item = document.createElement("div");
  const metric = document.createElement("strong");
  const caption = document.createElement("span");
  const source = document.createElement("small");
  const value = metricData && typeof metricData === "object" ? metricData.value : metricData;
  const unit = metricData && typeof metricData === "object" ? metricData.unit : "";
  metric.textContent = value == null ? "—" : (formatter ? formatter(value) : `${value}${unit ? ` ${unit}` : ""}`);
  caption.textContent = label;
  source.textContent = metricData?.source || "Nicht verfügbar";
  source.title = metricData?.note || metricData?.source || "";
  for (const className of [metricSourceClass(metricData?.source), metricToneClass(label, value)]) {
    if (className) item.classList.add(className);
  }
  source.className = metricSourceClass(metricData?.source);
  if (metricData?.source === "KI-Schätzung" || metricData?.source === "Berechnete Schätzung") source.className = "metric-estimate";
  if (metricData?.source === "Garmin Connect") source.className = "metric-garmin";
  const valueRow = document.createElement("div");
  valueRow.className = "metric-value-row";
  valueRow.append(metric);
  const comparison = comparisonText(metricData?.comparison);
  if (comparison) {
    const badge = document.createElement("small");
    badge.className = `metric-comparison ${comparison.className}`;
    badge.textContent = comparison.text;
    badge.title = comparison.title;
    valueRow.append(badge);
  }
  if (editable?.key) {
    item.classList.add("metric-editable");
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "metric-edit-button";
    edit.textContent = "✎";
    edit.title = `${label} bearbeiten`;
    edit.setAttribute("aria-label", `${label} bearbeiten`);
    const input = document.createElement("input");
    input.className = "metric-edit-input";
    input.type = "number";
    input.step = editable.step || "any";
    input.min = editable.min ?? "0";
    input.value = state.data?.profile?.[editable.key] || (value == null ? "" : value);
    input.hidden = true;
    edit.addEventListener("click", () => {
      const editing = item.classList.toggle("editing");
      input.hidden = !editing;
      metric.hidden = editing;
      edit.textContent = editing ? "✓" : "✎";
      edit.title = editing ? "Wert speichern" : `${label} bearbeiten`;
      edit.setAttribute("aria-label", edit.title);
      if (editing) { input.focus(); input.select(); }
      else saveInlineMetric(editable.key, input.value, edit);
    });
    item.append(valueRow, input, caption, source, edit);
  } else {
    item.append(valueRow, caption, source);
  }
  root.append(item);
}

async function saveInlineMetric(key, value, button) {
  const profile = { ...(state.data?.profile || {}), [key]: String(value || "").trim() };
  button.disabled = true;
  try {
    await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    toast("Wert gespeichert und für den Coach aktiviert");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

function performanceSection(root, title, items, detail = "") {
  const section = document.createElement("section");
  section.className = "performance-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const headingWrap = document.createElement("div");
  headingWrap.className = "performance-section-heading";
  headingWrap.append(heading);
  if (detail) {
    const stamp = document.createElement("span");
    stamp.className = "tab-sync-detail";
    stamp.textContent = detail;
    headingWrap.append(stamp);
  }
  section.append(headingWrap);
  const grid = document.createElement("div");
  grid.className = "metric-grid";
  items.forEach(([label, value, formatter, editable]) => displayMetric(grid, label, value, formatter, editable));
  section.append(grid);
  root.append(section);
}

function renderPerformance(performance) {
  const root = $("#performanceSummary");
  root.replaceChildren();
  const syncNotices = [];
  if (state.data?.sync?.running || state.localSync.intervals) syncNotices.push(state.data?.sync?.status || "Intervals.icu wird synchronisiert…");
  if (state.data?.garmin_sync?.running || state.localSync.garmin) syncNotices.push(state.data?.garmin_sync?.status || "Garmin wird synchronisiert…");
  if (state.data?.performance_refresh?.running || state.localSync.performance) syncNotices.push("Leistungsdaten werden aktualisiert…");
  if (!performance?.available) {
    const info = document.createElement("p");
    info.className = "fine-print";
    info.textContent = "Nach dem ersten Trainingsdaten-Update werden hier Leistungswerte angezeigt.";
    root.append(info);
    if (syncNotices.length) {
      const status = document.createElement("p");
      status.className = "tab-sync-detail";
      status.textContent = syncNotices.join(" · ");
      root.append(status);
    }
    return;
  }

  const values = performance.metrics || {};
  const load = performance.current_load || {};
  const actualLoad = performance.actual_load || {};
  const recovery = performance.recovery || {};
  const comparisons = performance.comparisons || {};
  const week = performance.rolling_training?.last_7_days || {};
  const refreshedAt = state.data?.sync?.last_sync_at || performance.as_of;
  const performanceDetail = syncNotices.length ? syncNotices.join(" · ") : refreshedAt ? `Letzte Aktualisierung: ${formatTime(refreshedAt)}` : "";
  const compared = (value, key) => value && typeof value === "object" ? { ...value, comparison: comparisons[key] } : { value, comparison: comparisons[key] };
  performanceSection(root, "Gesundheitsdaten", [
    ["Gewicht", compared(values.weight_kg, "weight_kg_30d"), null, { key: "weight_kg", step: "0.1" }],
    ["Körperfett", values.body_fat_pct, null, { key: "body_fat_pct", step: "0.1" }],
    ["Größe", values.height_cm, null, { key: "height_cm", step: "0.1" }],
    ["Schlaf", compared({ value: recovery.sleep_hours, unit: "h", source: "Intervals.icu Wellness" }, "sleep_hours")],
    ["Readiness", compared({ value: recovery.readiness, unit: "", source: recovery.readiness_source || "Intervals.icu Wellness" }, "readiness_30d")],
    ["Ruhepuls", compared({ value: recovery.restingHR, unit: "bpm", source: "Intervals.icu Wellness" }, "restingHR")],
    ["HRV", compared({ value: recovery.hrv, unit: "ms", source: "Intervals.icu Wellness" }, "hrv")],
  ], performanceDetail);
  performanceSection(root, "Allgemeine Leistungsdaten", [
    ["Fitness / CTL", compared({ value: load.ctl, unit: "", source: "Intervals.icu" }, "fitness_ctl"), formatWhole],
    ["Form / TSB", compared({ value: load.tsb, unit: "", source: "Intervals.icu" }, "form_tsb"), formatWhole],
    ["Ermüdung / ATL (inkl. Planung)", compared({ value: load.atl, unit: "", source: "Intervals.icu" }, "fatigue_atl"), formatWhole],
    ["Ermüdung / ATL (nur absolviert)", compared({ value: actualLoad.atl, unit: "", source: actualLoad.source || "Berechnet" }, "fatigue_atl_actual"), formatWhole],
    ["Belastung letzte 7 Tage", compared({ value: week.training_load, unit: "", source: "Aus Aktivitäten" }, "training_load_7d")],
    ["Trainingsumfang letzte 7 Tage", compared({ value: week.duration_hours, unit: "h", source: "Aus Aktivitäten" }, "training_volume_7d")],
  ]);
  performanceSection(root, "Radfahren", [
    ["FTP", compared(values.cycling_ftp_watts, "cycling_ftp_watts_30d")],
    ["eFTP", compared(values.cycling_eftp_watts, "cycling_eftp_30d")],
    ["Schwellenpuls", compared(values.bike_threshold_hr_bpm, "bike_threshold_hr_bpm_30d")],
    ["Max HF", values.cycling_max_hr_bpm],
    ["VO₂max", compared(values.cycling_vo2max_ml_kg_min, "cycling_vo2max_ml_kg_min_30d")],
  ]);
  performanceSection(root, "Laufen", [
    ["Schwellenleistung", compared(values.run_threshold_watts, "run_threshold_watts_30d")],
    ["Schwellenpace", compared(values.run_threshold_pace_seconds_per_km, "run_threshold_pace_seconds_per_km_30d"), formatPace],
    ["Schwellenpuls", compared(values.run_threshold_hr_bpm, "run_threshold_hr_bpm_30d")],
    ["Max HF", values.running_max_hr_bpm],
    ["VO₂max", compared(values.running_vo2max_ml_kg_min, "running_vo2max_ml_kg_min_30d")],
    ["5 km (geschätzt)", compared(values.run_5k_seconds, "run_5k_seconds_30d"), formatDuration],
    ["10 km (geschätzt)", compared(values.run_10k_seconds, "run_10k_seconds_30d"), formatDuration],
    ["Halbmarathon (geschätzt)", compared(values.run_half_marathon_seconds, "run_half_marathon_seconds_30d"), formatDuration],
    ["Marathon (geschätzt)", compared(values.run_marathon_seconds, "run_marathon_seconds_30d"), formatDuration],
  ]);
  const explanation = document.createElement("p");
  explanation.className = "fine-print";
  explanation.textContent = "Garmin-Connect-Werte werden als solche markiert und haben bei VO₂max sowie Laufprognosen Vorrang. Fehlen Garmin-Werte, werden Intervals.icu-Werte bzw. vorsichtige KI-Schätzungen verwendet.";
  root.append(explanation);
  const estimationError = state.data?.performance_refresh?.last_error;
  if (estimationError) {
    const error = document.createElement("p");
    error.className = "error";
    error.textContent = `KI-Schätzung fehlgeschlagen: ${estimationError}`;
    root.append(error);
  }
  const estimationReason = performance.ai_estimates?.reason;
  if (estimationReason && !estimationError) {
    const note = document.createElement("p");
    note.className = "fine-print estimate-note";
    note.textContent = estimationReason;
    root.append(note);
  }
}

function updateHeaderAction() {
  const button = $("#headerActionButton");
  if (!button) return;
  const panel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  if (panel === "dataPanel") {
    button.hidden = false;
    button.dataset.action = "performance";
    button.title = "Aktuelle Leistungsdaten von Intervals.icu und KI aktualisieren";
    button.disabled = Boolean(state.data?.performance_refresh?.running || state.data?.sync?.running || state.data?.garmin_sync?.running || state.data?.provider_resync?.intervals?.running || state.data?.provider_resync?.garmin?.running || state.localSync.performance || state.localSync.intervals || state.localSync.garmin || state.localSync.intervalsFull || state.localSync.garminFull);
    button.textContent = state.data?.sync?.running || state.data?.garmin_sync?.running || state.localSync.intervals || state.localSync.garmin
      ? "Synchronisierung läuft…"
      : button.disabled ? "Leistungsdaten werden aktualisiert…" : "Leistungsdaten aktualisieren";
  } else if (panel === "activitiesPanel") {
    button.hidden = false;
    button.dataset.action = "activities";
    button.title = "Aktivitäten der letzten 90 Tage von Intervals.icu laden";
    button.disabled = Boolean(state.data?.sync?.running || state.data?.provider_resync?.intervals?.running || state.localSync.intervals || state.localSync.intervalsFull);
    button.textContent = button.disabled ? "Synchronisierung läuft…" : "Aktivitäten aktualisieren";
  } else {
    button.hidden = true;
    button.disabled = false;
    button.dataset.action = "";
  }
}

function renderModel(model) {
  if (!model) return;
  const select = $("#modelSelect");
  const currentIds = [...select.options].map((option) => option.value).join(",");
  const nextIds = (model.options || []).map((option) => option.id).join(",");
  if (currentIds !== nextIds) {
    select.replaceChildren();
    for (const option of model.options || []) {
      const element = document.createElement("option");
      element.value = option.id;
      element.textContent = option.label;
      element.title = option.description || "";
      select.append(element);
    }
  }
  select.value = model.selected;
  const selected = (model.options || []).find((option) => option.id === model.selected);
  $("#modelDescription").textContent = selected?.description || "Wähle die Balance aus Qualität, Tempo und Kosten.";
}

function renderThinkingLevel(thinkingLevel) {
  if (!thinkingLevel) return;
  const select = $("#thinkingLevelSelect");
  const currentIds = [...select.options].map((option) => option.value).join(",");
  const nextIds = (thinkingLevel.options || []).map((option) => option.id).join(",");
  if (currentIds !== nextIds) {
    select.replaceChildren();
    for (const option of thinkingLevel.options || []) {
      const element = document.createElement("option");
      element.value = option.id;
      element.textContent = option.label;
      element.title = option.description || "";
      select.append(element);
    }
  }
  select.value = thinkingLevel.selected;
  const selected = (thinkingLevel.options || []).find((option) => option.id === thinkingLevel.selected);
  $("#thinkingLevelDescription").textContent = selected?.description || "Steuert die GrÃ¼ndlichkeit der Antwort.";
  const modelSelect = $("#modelSelect");
  const modelSummary = $("#modelSettingsSummary");
  if (modelSummary) modelSummary.textContent = [modelSelect?.selectedOptions?.[0]?.textContent, selected?.label || select.selectedOptions?.[0]?.textContent].filter(Boolean).join(" · ");
}

function renderSettings(data) {
  const configured = data.configured || {};
  const garmin = data.garmin || {};
  const setStatus = (selector, ok, text) => {
    const node = $(selector);
    if (!node) return;
    node.textContent = text;
    node.className = ok ? "configured" : "not-configured";
  };
  setStatus("#openaiConnectionStatus", configured.openai, configured.openai ? "Konfiguriert" : "Nicht konfiguriert");
  setStatus("#intervalsConnectionStatus", configured.intervals, configured.intervals ? "Konfiguriert" : "Nicht konfiguriert");
  setStatus("#garminConnectionStatus", garmin.configured, garmin.configured ? (garmin.source === "fixture" ? "Lokale Testdatei aktiv" : "Konfiguriert") : "Nicht konfiguriert");
  const connectionsSummary = $("#connectionsSummary");
  if (connectionsSummary) {
    connectionsSummary.textContent = [["OpenAI", configured.openai], ["Intervals", configured.intervals], ["Garmin", garmin.configured]]
      .map(([label, active]) => `${label} ${active ? "✓" : "–"}`).join(" · ");
  }
  const intervalsDays = $("#intervalsSyncDays");
  const garminDays = $("#garminSyncDays");
  if (intervalsDays && document.activeElement !== intervalsDays) intervalsDays.value = data.sync_settings?.intervals_days || 90;
  if (garminDays && document.activeElement !== garminDays) garminDays.value = data.sync_settings?.garmin_days || 30;
  const intervalsSyncButton = $("#systemIntervalsSyncButton");
  const intervalsFullButton = $("#systemIntervalsFullResyncButton");
  const intervalsFullStatus = $("#intervalsFullResyncStatus");
  const intervalsFullResync = data.provider_resync?.intervals || {};
  const intervalsFullRunning = Boolean(intervalsFullResync.running || state.localSync.intervalsFull);
  if (intervalsSyncButton) {
    intervalsSyncButton.disabled = Boolean(data.sync?.running || state.localSync.intervals || intervalsFullRunning);
    intervalsSyncButton.textContent = data.sync?.running || state.localSync.intervals ? "Synchronisierung läuft…" : "Synchronisieren";
  }
  if (intervalsFullButton) {
    intervalsFullButton.disabled = !configured.intervals || intervalsFullRunning || Boolean(data.sync?.running || state.localSync.intervals);
    intervalsFullButton.textContent = intervalsFullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  if (intervalsFullStatus) {
    intervalsFullStatus.classList.toggle("error", Boolean(intervalsFullResync.last_error));
    intervalsFullStatus.textContent = intervalsFullRunning && intervalsFullResync.status
      ? intervalsFullResync.status
      : intervalsFullResync.last_error
        ? intervalsFullResync.last_error
        : intervalsFullResync.last_resync_at
          ? `Letzter vollständiger Resync: ${formatTime(intervalsFullResync.last_resync_at)}`
          : "Löscht nur lokale Intervals.icu-Daten; die Cloud bleibt unverändert.";
  }
  const garminSyncButton = $("#garminSyncButton");
  if (garminSyncButton) {
    garminSyncButton.disabled = Boolean(data.garmin_sync?.running || state.localSync.garmin);
    garminSyncButton.textContent = data.garmin_sync?.running || state.localSync.garmin ? "Synchronisierung läuft…" : "Garmin synchronisieren";
  }
  const usage = data.usage || {};
  const usageNode = $("#usageSummary");
  if (usageNode) {
    const rateLimits = usage.rate_limits || {};
    const remaining = rateLimits.remaining_requests != null || rateLimits.remaining_tokens != null
      ? ` · Verfügbar im aktuellen OpenAI-Fenster: ${rateLimits.remaining_requests ?? "?"} Anfragen / ${rateLimits.remaining_tokens ?? "?"} Tokens`
      : " · OpenAI-Kontingent nach dem nächsten API-Aufruf verfügbar";
    usageNode.textContent = `OpenAI heute: ${usage.requests || 0} Anfragen · ${usage.total_tokens || 0} Tokens${remaining}`;
  }
  const privacySummary = $("#privacySummary");
  if (privacySummary) privacySummary.textContent = `${usage.requests || 0} OpenAI-Anfragen heute`;
  renderNotificationStatus();
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

function render(data) {
  const firstRender = !state.data;
  state.data = data;
  renderQuickMessageTemplates();
  notifyState(data);
  renderStatus(data);
  renderMessages(data.messages, firstRender);
  renderActivities(data.activities || []);
  renderPlanned(data.planned || []);
  renderLibrary(data.library || []);
  const librarySyncDetail = $("#librarySyncDetail");
  if (librarySyncDetail) {
    librarySyncDetail.textContent = data.library_sync?.last_error
      ? data.library_sync.last_error
      : data.library_sync?.last_sync_at
        ? "Letzte Aktualisierung: " + formatTime(data.library_sync.last_sync_at)
        : "Noch nicht synchronisiert";
    librarySyncDetail.classList.toggle("error", Boolean(data.library_sync?.last_error));
  }
  renderProfile(data.profile);
  renderGarmin(data.garmin);
  renderCompetitions(data.competitions || []);
  renderLocalFeedback(data);
  renderPlanning(data);
  renderExternalCalendar(data);
  renderCompetitionSync(data);
  renderPerformance(data.performance);
  renderModel(data.model);
  renderThinkingLevel(data.thinking_level);
  renderSettings(data);
  updateHeaderAction();
}

async function load() {
  try { render(await api("/api/state")); }
  catch (error) { if (!/Authentication/.test(error.message)) toast(error.message, true); }
}

function queueChatMessage(message, mode) {
  state.chatQueue[mode === "steer" ? "unshift" : "push"]({
    id: ++state.chatQueueSequence,
    message,
    mode,
  });
  const input = $("#messageInput");
  input.value = "";
  input.style.height = "auto";
  renderMessages(state.data?.messages || [], true);
  updateChatControls();
}

async function requestCoachResponse(message, restoreInputOnError = false) {
  if (state.data) {
    state.data.messages.push({ role: "user", content: message });
    renderMessages(state.data.messages, true);
  }
  try {
    await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    await load();
    invalidateContextPreview();
    return true;
  } catch (error) {
    toast(error.message, true);
    if (restoreInputOnError) $("#messageInput").value = message;
    await load();
    invalidateContextPreview();
    return false;
  }
}

async function drainChatQueue(firstMessage) {
  await requestCoachResponse(firstMessage, true);
  while (state.chatQueue.length) {
    const next = state.chatQueue.shift();
    renderMessages(state.data?.messages || [], true);
    await requestCoachResponse(next.message);
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if (!message || voiceIsRecording() || state.voiceTranscribing) return;
  if (state.busy) {
    queueChatMessage(message, "queue");
    return;
  }
  state.busy = true;
  state.quickTemplatesVisible = false;
  renderQuickMessageTemplates();
  input.value = "";
  input.style.height = "auto";
  updateChatControls();
  updateVoiceButton();
  try {
    await drainChatQueue(message);
  } finally {
    state.busy = false;
    updateChatControls();
    renderMessages(state.data?.messages || [], true);
    updateVoiceButton();
    input.focus();
  }
}

function steerCurrentChat(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if (!message || !state.busy || voiceIsRecording() || state.voiceTranscribing) return;
  queueChatMessage(message, "steer");
}

async function syncNow(event) {
  const button = event?.currentTarget || $("#activitiesSyncButton");
  const compactButton = button.id === "systemIntervalsSyncButton";
  const defaultCaption = compactButton ? "Synchronisieren" : "Aktivitäten aktualisieren";
  const configuredDays = $("#intervalsSyncDays")?.value || state.data?.sync_settings?.intervals_days || 90;
  state.localSync.intervals = true;
  button.disabled = true; button.classList.add("busy"); button.textContent = compactButton ? "Synchronisierung läuft…" : "Aktivitäten werden aktualisiert…";
  try {
    const result = await api("/api/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    const periodLabel = result.activity_days === -1 ? "aller verfügbaren Daten" : `der letzten ${result.activity_days} Tage`;
    toast(result.status === "ok" ? `${result.activities} Aktivitäten ${periodLabel} aktualisiert${result.estimates ? ` · ${result.estimates} KI-Schätzungen ergänzt` : ""}` : "Aktualisierung läuft bereits");
    if (result.estimate_error) toast(`Trainingsdaten aktualisiert, KI-Schätzung fehlgeschlagen: ${result.estimate_error}`, true);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.intervals = false; button.disabled = false; button.classList.remove("busy"); button.textContent = defaultCaption; updateHeaderAction(); }
}

async function syncCompetitions() {
  if (state.profileDirty) {
    toast("Bitte zuerst die lokalen Änderungen speichern.", true);
    return;
  }
  const button = $("#competitionSyncButton");
  if (!button) return;
  state.localSync.competitions = true;
  button.disabled = true;
  button.textContent = "Synchronisierung läuft…";
  try {
    const result = await api("/api/competitions/sync", { method: "POST", body: "{}" });
    if (result.status === "already_running") toast("Zielwettkämpfe werden bereits synchronisiert");
    else toast(`Zielwettkämpfe synchronisiert · ${result.pushed || 0} übertragen · ${result.imported || 0} importiert${result.skipped ? ` · ${result.skipped} nicht unterstützte Sportart(en) übersprungen` : ""}`);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.competitions = false; renderCompetitionSync(state.data || {}); }
}

async function refreshPerformance() {
  const button = $("#headerActionButton");
  if (!button) return;
  state.localSync.performance = true;
  button.disabled = true;
  button.textContent = "Aktualisierung läuft…";
  try {
    const result = await api("/api/performance/refresh", { method: "POST", body: "{}" });
    toast(result.status === "ok" ? `Leistungsdaten aktualisiert${result.estimates ? ` · ${result.estimates} KI-Schätzungen ergänzt` : ""}` : "Aktualisierung läuft bereits");
    if (result.estimate_error) toast(`Leistungsdaten aktualisiert, KI-Schätzung fehlgeschlagen: ${result.estimate_error}`, true);
    invalidateContextPreview();
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  }
  finally { state.localSync.performance = false; updateHeaderAction(); }
}

async function syncGarmin() {
  const button = $("#garminSyncButton");
  if (!button) return;
  state.localSync.garmin = true;
  button.disabled = true;
  button.textContent = "Garmin wird synchronisiert…";
  try {
    const configuredDays = $("#garminSyncDays")?.value || state.data?.sync_settings?.garmin_days || 30;
    const result = await api("/api/garmin/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    toast(result.status === "ok" ? `Garmin synchronisiert${result.activities ? ` · ${result.activities} Aktivitäten` : ""}` : "Garmin-Synchronisierung läuft bereits");
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.garmin = false; button.disabled = false; button.textContent = "Garmin synchronisieren"; updateHeaderAction(); }
}

async function syncExternalCalendar() {
  const button = $("#externalCalendarSyncButton");
  if (!button) return;
  state.localSync.externalCalendar = true;
  button.disabled = true;
  button.textContent = "Synchronisierung läuft…";
  try {
    const result = await api("/api/external-calendar/sync", { method: "POST", body: "{}" });
    toast(result.status === "ok" ? `Kalender synchronisiert · ${result.events || 0} Einträge` : "Kalender wird bereits synchronisiert");
    if (result.replan_changes) toast(`${result.replan_changes} Trainingsentwurf/-entwürfe als Anpassung vorgeschlagen`);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.externalCalendar = false; button.disabled = false; button.textContent = "Synchronisieren"; }
}

async function fullResync(source) {
  const isGarmin = source === "garmin";
  const button = $(isGarmin ? "#garminFullResyncButton" : "#systemIntervalsFullResyncButton");
  if (!button) return;
  const providerLabel = isGarmin ? "Garmin" : "Intervals.icu";
  if (!window.confirm(`Alle lokal gespeicherten ${providerLabel}-Daten löschen und vollständig neu laden? Die Daten in ${providerLabel} bleiben unverändert.`)) return;
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
    updateHeaderAction();
  }
}

async function resetCoachChat() {
  const button = $("#chatResetButton");
  if (!button || !window.confirm("Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen?")) return;
  button.disabled = true;
  button.textContent = "Wird zurückgesetzt…";
  try {
    await api("/api/chat/reset", { method: "POST", body: "{}" });
    if (state.data) {
      state.data.messages = [];
      state.chatQueue = [];
      renderMessages([], true);
    }
    toast("Neuer Coach-Chat gestartet");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Chat zurücksetzen"; }
}

async function saveProfile(event) {
  event.preventDefault();
  const profile = { ...(state.data?.profile || {}), ...Object.fromEntries(new FormData(event.currentTarget)) };
  const payload = {
    profile,
    competitions: collectCompetitions(),
  };
  try {
    await api("/api/athlete-context", { method: "PUT", body: JSON.stringify(payload) });
    state.profileDirty = false;
    invalidateContextPreview();
    toast("Athletenkontext gespeichert und für den Coach aktiviert");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function saveFeedback(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  try {
    await api("/api/feedback", { method: "POST", body: JSON.stringify(payload) });
    toast("Lokales Feedback gespeichert");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function prepareReplan() {
  const button = $("#replanButton");
  if (!button) return;
  button.disabled = true;
  button.textContent = "Wird vorbereitet…";
  try {
    await api("/api/planning/replan", { method: "POST", body: JSON.stringify({ apply: false }) });
    toast("Adaptive Anpassung vorbereitet");
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Anpassung vorbereiten"; }
}

async function applyReplan() {
  const button = $("#applyReplanButton");
  const adjustmentId = button?.dataset.adjustmentId;
  if (!button || !adjustmentId || !window.confirm("Die vorgeschlagenen Änderungen auf lokale zukünftige Entwürfe anwenden? Intervals.icu wird dabei nicht verändert.")) return;
  button.disabled = true;
  try {
    await api("/api/planning/replan", { method: "POST", body: JSON.stringify({ apply: true, adjustment_id: adjustmentId }) });
    toast("Adaptive Anpassung angewendet");
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function importPublicCalendar() {
  const button = $("#publicCalendarImportButton");
  const url = $("#publicCalendarUrl")?.value.trim();
  const name = $("#publicCalendarName")?.value.trim();
  if (!url) { toast("Bitte eine HTTPS-iCalendar-URL eintragen", true); return; }
  button.disabled = true;
  button.textContent = "Kalender wird geladen…";
  try {
    const result = await api("/api/calendar/import", { method: "POST", body: JSON.stringify({ url, name }) });
    toast(`${result.events || 0} Veranstaltungen gefunden`);
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Kalender durchsuchen"; }
}

async function importPublicCandidate(id, button) {
  button.disabled = true;
  try {
    await api(`/api/calendar/candidates/${encodeURIComponent(id)}/import`, { method: "POST", body: "{}" });
    toast("Veranstaltung als Wettkampf übernommen");
    await load();
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

async function downloadDatabaseBackup() {
  const button = $("#backupDownloadButton");
  if (button) button.disabled = true;
  try {
    const response = await fetch("/api/privacy/backup", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("Datenbank-Backup konnte nicht erstellt werden.");
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `intervals-coach-database-${todayIso()}.backup`;
    link.click();
    URL.revokeObjectURL(link.href);
    toast("Verschlüsseltes Backup heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { if (button) button.disabled = false; }
}

async function restoreDatabaseBackup() {
  const input = $("#backupFileInput");
  const file = input?.files?.[0];
  if (!file || !window.confirm("Das aktuelle Datenbank-Backup wird vorher gesichert und durch die ausgewählte Datei ersetzt. Fortfahren?")) return;
  const button = $("#backupRestoreButton");
  button.disabled = true;
  try {
    const response = await fetch("/api/privacy/restore", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/octet-stream", "X-CSRF-Token": cookie("ic_csrf") }, body: file });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Backup konnte nicht wiederhergestellt werden.");
    toast("Backup wiederhergestellt. Bitte erneut anmelden.");
    showLogin();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
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

async function downloadDiagnostics() {
  const button = $("#diagnosticsButton");
  button.disabled = true;
  button.textContent = "Wird vorbereitet…";
  try {
    const report = await api("/api/diagnostics");
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `intervals-coach-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast("Diagnose heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Diagnose herunterladen"; }
}

async function downloadPrivacyExport() {
  try {
    const payload = await api("/api/privacy/export");
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "intervals-coach-export.json";
    link.click();
    URL.revokeObjectURL(link.href);
    toast("Datenexport erstellt");
  } catch (error) { toast(error.message, true); }
}

async function deletePrivacyData() {
  if (!window.confirm("Alle lokalen Chats, Snapshots, Entwürfe und Profile löschen? Dieser Schritt kann nicht rückgängig gemacht werden.")) return;
  try {
    await api("/api/privacy/delete", { method: "POST", body: JSON.stringify({ confirm: "DELETE" }) });
    toast("Lokale Daten gelöscht");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function logout() {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (_) {}
  showLogin();
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item, .panel").forEach((node) => node.classList.remove("active"));
  button.classList.add("active");
  $(`#${button.dataset.panel}`).classList.add("active");
  if (state.data) renderStatus(state.data);
  updateHeaderAction();
  if (button.dataset.panel === "settingsPanel") loadContextPreview();
  if (button.dataset.panel === "settingsPanel") loadLogs();
  window.scrollTo({ top: 0, behavior: "auto" });
  if (button.dataset.panel === "chatPanel") scrollChatToLatest(true);
}));

$("#loginForm").addEventListener("submit", login);
$("#chatForm").addEventListener("submit", sendMessage);
$("#steerButton").addEventListener("click", steerCurrentChat);
$("#quickMessageTemplates").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-message]");
  if (!button || state.busy) return;
  const input = $("#messageInput");
  input.value = button.dataset.message || "";
  input.dispatchEvent(new Event("input"));
  $("#chatForm").requestSubmit();
});
$("#voiceButton").addEventListener("click", toggleVoiceInput);
$("#headerActionButton").addEventListener("click", (event) => {
  if (event.currentTarget.dataset.action === "performance") refreshPerformance();
  else if (event.currentTarget.dataset.action === "activities") syncNow(event);
});
$("#systemIntervalsSyncButton").addEventListener("click", syncNow);
$("#systemIntervalsFullResyncButton").addEventListener("click", () => fullResync("intervals"));
$("#competitionSyncButton").addEventListener("click", syncCompetitions);
$("#garminSyncButton").addEventListener("click", syncGarmin);
$("#externalCalendarSyncButton").addEventListener("click", syncExternalCalendar);
$("#garminFullResyncButton").addEventListener("click", () => fullResync("garmin"));
$("#profileForm").addEventListener("submit", saveProfile);
$("#feedbackForm").addEventListener("submit", saveFeedback);
$("#replanButton").addEventListener("click", prepareReplan);
$("#applyReplanButton").addEventListener("click", applyReplan);
$("#profileForm").addEventListener("input", () => { state.profileDirty = true; });
$("#competitionList").addEventListener("input", () => { state.profileDirty = true; });
$("#addCompetitionButton").addEventListener("click", addCompetition);
$("#modelSelect").addEventListener("change", saveModel);
$("#thinkingLevelSelect").addEventListener("change", saveThinkingLevel);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#logsRefreshButton").addEventListener("click", loadLogs);
$("#chatResetButton").addEventListener("click", resetCoachChat);
$("#privacyExportButton").addEventListener("click", downloadPrivacyExport);
$("#privacyDeleteButton").addEventListener("click", deletePrivacyData);
$("#notificationEnableButton").addEventListener("click", enableNotifications);
$("#backupDownloadButton").addEventListener("click", downloadDatabaseBackup);
$("#backupRestoreButton").addEventListener("click", restoreDatabaseBackup);
$("#logoutButton").addEventListener("click", logout);
$("#libraryLoadButton").addEventListener("click", loadLibrary);
$("#systemContextPreviewButton").addEventListener("click", () => {
  $("#systemContextPreviewButton").dataset.loaded = "false";
  loadContextPreview();
});
$("#messageInput").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 150)}px`;
});
$("#messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("#chatForm").requestSubmit();
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") savePwaActivity();
  else checkPwaReturn();
});
document.addEventListener("pointerdown", handlePwaInteraction, { passive: true });
window.addEventListener("scroll", updateChatComposerVisibility, { passive: true });
window.addEventListener("resize", updateChatComposerVisibility);
window.addEventListener("pagehide", savePwaActivity);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js");
setInterval(() => {
  if (state.localSync.intervals || state.localSync.competitions || state.localSync.garmin || state.localSync.performance || state.localSync.intervalsFull || state.localSync.garminFull) load();
}, 1500);
setInterval(() => {
  if (state.data && document.visibilityState === "visible") load();
}, 60_000);
renderNotificationStatus();
bootstrapAuth();
