function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function markdownEmphasis(value) {
  return value.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>");
}

function replaceMarkdownLinks(value, linkSpans) {
  let html = "";
  let cursor = 0;
  while (cursor < value.length) {
    const labelStart = value.indexOf("[", cursor);
    if (labelStart < 0) return html + value.slice(cursor);
    const linkStart = value.indexOf("](", labelStart + 1);
    if (linkStart < 0) return html + value.slice(cursor);
    const urlEnd = value.indexOf(")", linkStart + 2);
    if (urlEnd < 0) return html + value.slice(cursor);
    const label = value.slice(labelStart + 1, linkStart);
    const url = value.slice(linkStart + 2, urlEnd);
    const validScheme = url.startsWith("https://") || url.startsWith("http://");
    const validUrl = validScheme && label && !url.includes("(") && !url.includes(")") && url === url.trim();
    if (!validUrl) {
      html += value.slice(cursor, labelStart + 1);
      cursor = labelStart + 1;
      continue;
    }
    html += value.slice(cursor, labelStart);
    const token = `\uE000COACHLINKSPAN${linkSpans.length}\uE001`;
    linkSpans.push(`<a href="${url}" target="_blank" rel="noopener noreferrer">${markdownEmphasis(label)}</a>`);
    html += token;
    cursor = urlEnd + 1;
  }
  return html;
}

function inlineMarkdown(value) {
  let html = escapeHtml(value);
  const codeSpans = [];
  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `\uE000COACHCODESPAN${codeSpans.length}\uE001`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  const linkSpans = [];
  html = markdownEmphasis(replaceMarkdownLinks(html, linkSpans));
  html = html.replace(/\uE000COACHLINKSPAN(\d+)\uE001/g, (_, index) => linkSpans[Number(index)]);
  return html.replace(/\uE000COACHCODESPAN(\d+)\uE001/g, (_, index) => codeSpans[Number(index)]);
}

function headingFromMarkdownLine(line) {
  const trimmed = line.trimStart();
  let level = 0;
  while (level < trimmed.length && trimmed[level] === "#") level += 1;
  if (!level || level > 3 || !trimmed[level] || trimmed[level].trim()) return null;
  return { level, text: trimmed.slice(level).trim() };
}

function listItemFromMarkdownLine(line) {
  const trimmed = line.trimStart();
  const marker = trimmed[0];
  if (marker && "-*+".includes(marker) && trimmed[1] && !trimmed[1].trim()) {
    return { type: "ul", text: trimmed.slice(2).trimStart() };
  }
  let digitCount = 0;
  while (digitCount < trimmed.length && trimmed[digitCount] >= "0" && trimmed[digitCount] <= "9") digitCount += 1;
  const orderedMarker = trimmed[digitCount];
  if (!digitCount || !orderedMarker || !".)".includes(orderedMarker) || !trimmed[digitCount + 1] || trimmed[digitCount + 1].trim()) return null;
  return { type: "ol", text: trimmed.slice(digitCount + 1).trimStart() };
}

function closeMarkdownList(state, output) {
  if (state.listType) output.push(`</${state.listType}>`);
  state.listType = null;
}

function flushMarkdownParagraph(state, output) {
  if (!state.paragraph.length) return;
  output.push(`<p>${inlineMarkdown(state.paragraph.join("\n")).replaceAll("\n", "<br>")}</p>`);
  state.paragraph = [];
}

function toggleMarkdownCode(state, output) {
  flushMarkdownParagraph(state, output);
  closeMarkdownList(state, output);
  if (state.inCode) output.push(`<pre><code>${escapeHtml(state.codeLines.join("\n"))}</code></pre>`);
  state.codeLines = [];
  state.inCode = !state.inCode;
}

function isHorizontalRule(line) {
  const value = line.trim();
  return value.length >= 3 && (value.split("").every((character) => character === "-")
    || value.split("").every((character) => character === "*"));
}

function renderMarkdownHeading(heading, state, output) {
  flushMarkdownParagraph(state, output);
  closeMarkdownList(state, output);
  let headingText = heading.text.trim();
  while (headingText.endsWith("#")) headingText = headingText.slice(0, -1).trimEnd();
  output.push(`<h${heading.level}>${inlineMarkdown(headingText)}</h${heading.level}>`);
}

function renderMarkdownListItem(item, state, output) {
  flushMarkdownParagraph(state, output);
  if (state.listType !== item.type) {
    closeMarkdownList(state, output);
    output.push(`<${item.type}>`);
    state.listType = item.type;
  }
  output.push(`<li>${inlineMarkdown(item.text)}</li>`);
}

function renderMarkdownLine(line, state, output) {
  const heading = headingFromMarkdownLine(line);
  if (heading) return renderMarkdownHeading(heading, state, output);
  if (isHorizontalRule(line)) {
    flushMarkdownParagraph(state, output);
    closeMarkdownList(state, output);
    output.push("<hr>");
    return;
  }
  const listItem = listItemFromMarkdownLine(line);
  if (listItem) return renderMarkdownListItem(listItem, state, output);
  const quote = /^\s*>\s?(.*)$/.exec(line);
  if (quote) {
    flushMarkdownParagraph(state, output);
    closeMarkdownList(state, output);
    output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`);
    return;
  }
  closeMarkdownList(state, output);
  state.paragraph.push(line);
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replaceAll("\r", "").split("\n");
  const output = [];
  const state = { paragraph: [], listType: null, inCode: false, codeLines: [] };
  for (const line of lines) {
    if (line.trimStart().startsWith("```")) toggleMarkdownCode(state, output);
    else if (state.inCode) state.codeLines.push(line);
    else if (!line.trim()) {
      flushMarkdownParagraph(state, output);
      closeMarkdownList(state, output);
    } else renderMarkdownLine(line, state, output);
  }
  if (state.inCode) output.push(`<pre><code>${escapeHtml(state.codeLines.join("\n"))}</code></pre>`);
  flushMarkdownParagraph(state, output);
  closeMarkdownList(state, output);
  return output.join("");
}

const CALENDAR_DISPLAY_MAX_WEEKS = 52;

function calendarDisplayValue(value, fallback) {
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 && number <= CALENDAR_DISPLAY_MAX_WEEKS ? number : fallback;
}

function localDateKey(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.valueOf())) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function timezoneDateKey(timeZone, instant = new Date()) {
  if (!timeZone) return localDateKey(instant);
  try {
    const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(instant);
    const values = Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  } catch {
    return localDateKey(instant);
  }
}

function dateFromKey(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : new Date(Number.NaN);
}

function addDateKey(value, days) {
  const date = dateFromKey(value);
  if (Number.isNaN(date.valueOf())) return "";
  date.setDate(date.getDate() + days);
  return localDateKey(date);
}

function plannedEventDate(event) {
  return String(event?.start_date_local || event?.date || "").slice(0, 10);
}

function weatherIcon(code) {
  const number = Number(code);
  if (!Number.isFinite(number)) return "🌡️";
  const exact = { 0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️", 75: "❄️" };
  if (exact[number]) return exact[number];
  const range = [
    [51, 57, "🌦️"], [61, 67, "🌧️"], [71, 74, "🌨️"], [76, 77, "🌨️"],
    [80, 80, "🌦️"], [81, 82, "🌧️"], [85, 86, "🌨️"], [95, Number.POSITIVE_INFINITY, "⛈️"],
  ].find(([minimum, maximum]) => number >= minimum && number <= maximum);
  return range?.[2] || "🌤️";
}

function weatherIconFor(item) {
  return item?.icon || weatherIcon(item?.weather_code);
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

function renderMoreSegments(segment) {
  const selected = AppNavigation.moreSegments.includes(segment) ? segment : AppNavigation.moreSegments[2];
  document.querySelectorAll("[data-more-segment-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.moreSegmentPanel !== selected;
  });
  document.querySelectorAll("[data-more-segment]").forEach((link) => {
    const active = link.dataset.moreSegment === selected;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

function renderPlanSegments(segment) {
  const selected = AppNavigation.planSegments.includes(segment) ? segment : AppNavigation.planSegments[0];
  document.querySelectorAll("[data-plan-segment-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.planSegmentPanel !== selected;
  });
  document.querySelectorAll("[data-plan-segment]").forEach((link) => {
    const active = link.dataset.planSegment === selected;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

globalThis.AppViews = Object.freeze({ renderMoreSegments, renderPlanSegments });
function populateProfileSports(field, value) {
  const selectedSports = new Set(String(value || "").split(",").map((item) => item.trim()).filter(Boolean));
  [...field.options].forEach((option) => { option.selected = selectedSports.has(option.value); });
}

function populateProfileTimezone(field, value) {
  if (value && ![...field.options].some((option) => option.value === value)) field.append(new Option(`${value} (gespeichert)`, value));
  field.value = value || "";
}

function populateProfileField(form, key, value) {
  const field = form.elements[key];
  if (!field) return;
  if (key === "sports" && field.multiple) return populateProfileSports(field, value);
  if (key === "timezone" && field.tagName === "SELECT") return populateProfileTimezone(field, value);
  field.value = value || "";
}

function renderProfileSummary(profile) {
  const summary = $("#profileSummary");
  if (!summary) return;
  const values = [profile.name, profile.sports, profile.typical_weekly_volume].filter(Boolean);
  summary.textContent = values.length ? values.join(" · ") : "Noch nicht ausgefüllt";
}

function renderProfile(profile) {
  setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
  if (state.profileDirty) return;
  const form = $("#profileForm");
  for (const [key, value] of Object.entries(profile)) populateProfileField(form, key, value);
  if (form.elements.coaching_style?.value === "Supportive, direct, and evidence-aware") form.elements.coaching_style.value = "Unterstützend, direkt und evidenzbasiert";
  renderProfileSummary(profile);
}

function populateCheckin(checkin, timeZone) {
  const form = $("#checkinForm");
  if (!form) return;
  const values = checkin || { checkin_date: timezoneDateKey(timeZone) };
  for (const field of ["checkin_date", "soreness", "stress", "motivation", "session_rpe", "day_form", "available_minutes", "illness", "pain", "availability_notes", "notes"]) {
    if (form.elements[field]) form.elements[field].value = values[field] ?? "";
  }
  state.checkinSelectedDate = values.checkin_date || null;
  form.elements.day_status.value = values.day_status || "unknown";
  for (const tag of ["travel", "late_meal", "high_stress"]) form.elements[`tag_${tag}`].value = values.tag_answers?.[tag] == null ? "" : String(values.tag_answers[tag]);
  state.checkinDirty = false;
}

function selectedCheckin(rows, timeZone) {
  return rows.find((row) => row.checkin_date === state.checkinSelectedDate)
    || (!state.checkinSelectedDate ? rows.find((row) => row.checkin_date === timezoneDateKey(timeZone)) : null);
}

function checkinSummary(row) {
  const dayStatus = { rest: "Best\u00e4tigter Ruhetag", pause: "Best\u00e4tigte Trainingspause" }[row.day_status] || null;
  return [
    row.day_form ? `Tagesform: ${row.day_form}` : null,
    dayStatus,
    row.soreness != null ? `Schmerz/Muskelkater ${row.soreness}/10` : null,
    row.stress != null ? `Stress ${row.stress}/10` : null,
    row.motivation != null ? `Motivation ${row.motivation}/10` : null,
    row.illness ? `Krankheit: ${row.illness}` : null,
    row.pain ? "Schmerz notiert" : null,
  ].filter(Boolean).join(" · ") || "Ohne Bewertungen";
}

function checkinHistoryButton(row, rows, timeZone) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "checkin-history-item";
  button.classList.toggle("selected", row.checkin_date === state.checkinSelectedDate);
  const title = document.createElement("strong");
  title.textContent = dateLabel(row.checkin_date);
  const summary = document.createElement("span");
  summary.textContent = checkinSummary(row);
  button.append(title, summary);
  button.addEventListener("click", () => {
    populateCheckin(row, timeZone);
    renderCheckins(rows, timeZone);
  });
  return button;
}

function renderCheckinHistory(history, rows, timeZone) {
  history.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "fine-print";
    empty.textContent = "Noch kein Tages-Check-in gespeichert.";
    history.append(empty);
    return;
  }
  const heading = document.createElement("strong");
  heading.textContent = "Gespeicherte Check-ins";
  history.append(heading, ...rows.map((row) => checkinHistoryButton(row, rows, timeZone)));
}

function renderCheckins(checkins, timeZone) {
  const form = $("#checkinForm");
  const history = $("#checkinHistory");
  if (!form || !history) return;
  setDirtyIndicator("checkinDirtyIndicator", state.checkinDirty);
  const rows = Array.isArray(checkins) ? checkins : [];
  if (!state.checkinDirty) {
    const selected = selectedCheckin(rows, timeZone);
    populateCheckin(selected || (state.checkinSelectedDate ? { checkin_date: state.checkinSelectedDate } : null), timeZone);
  }
  renderCheckinHistory(history, rows, timeZone);
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
  $("#thinkingLevelDescription").textContent = selected?.description || "Steuert die Gründlichkeit der Antwort.";
  const modelSelect = $("#modelSelect");
  const modelSummary = $("#modelSettingsSummary");
  if (modelSummary) modelSummary.textContent = [modelSelect?.selectedOptions?.[0]?.textContent, selected?.label || select.selectedOptions?.[0]?.textContent].filter(Boolean).join(" · ");
}

function renderAppVersion(app = {}) {
  const settingsVersionNode = $("#settingsAppVersion");
  if (settingsVersionNode) settingsVersionNode.textContent = app.version ? `v${app.version}` : "unbekannt";
}

function settingsStatus(selector, ok, text) {
  const node = $(selector);
  if (!node) return;
  node.textContent = text;
  node.className = ok ? "configured" : "not-configured";
}

function aiConnectionLabel(configured, activeError) {
  if (!configured) return "Nicht konfiguriert";
  return activeError ? "Fehler bei letzter Anfrage" : "Konfiguriert";
}

function aiConnectionConfigurationDetail() { return "OPENAI_API_KEY nicht konfiguriert"; }

function aiConnectionErrorDetail(status) {
  const message = status.message || "OpenAI-Anfrage fehlgeschlagen.";
  const updated = status.updated_at ? " · " + formatTime(status.updated_at) : "";
  return message + updated;
}

function aiConnectionDetail(configured, status) {
  if (!configured) return aiConnectionConfigurationDetail();
  if (status.state === "error") return aiConnectionErrorDetail(status);
  if (status.state === "ok") return "Letzter erfolgreicher API-Aufruf: " + formatTime(status.updated_at);
  return "OpenAI Responses API";
}

function renderAiConnection(configured, status) {
  const activeError = status.state === "error";
  const healthy = configured && !activeError;
  settingsStatus("#openaiConnectionStatus", healthy, aiConnectionLabel(configured, activeError));
  const detail = $("#openaiConnectionDetail");
  if (detail) {
    detail.classList.toggle("error", Boolean(configured && activeError));
    detail.textContent = aiConnectionDetail(configured, status);
  }
  return healthy;
}

function intervalsConnectionState(data, configured) {
  return data.intervals || {
    configured: Boolean(configured.intervals),
    state: configured.intervals ? "configured" : "not_configured",
  };
}

function intervalsPaginationDetail(intervals) {
  return Object.entries(intervals.pagination || {})
    .filter(([, value]) => value && (Number(value.pages) > 1 || value.complete === false))
    .map(([name, value]) => {
      const completeness = value.complete === false ? " · unvollständig" : "";
      return name + ": " + (value.records || 0) + " Datensätze auf " + (value.pages || 0) + " Seiten" + completeness;
    })
    .join(" · ");
}

function intervalsConnectionDetail(intervals) {
  const librarySync = intervals.library_sync || {};
  if (!intervals.configured) return "API-Schlüssel nicht konfiguriert";
  if (intervals.state === "syncing") return intervals.status || "Intervals.icu wird synchronisiert.";
  if (intervals.last_error) return intervals.last_error;
  if (!(intervals.last_sync_at || librarySync.last_sync_at)) return "Noch keine Synchronisierung durchgeführt";
  const updated = formatTime(intervals.last_sync_at || librarySync.last_sync_at);
  const libraryCount = Number(librarySync.state?.synced || 0);
  const counts = libraryCount ? " · " + libraryCount + " Bibliothekseinheiten" : "";
  const pagination = intervalsPaginationDetail(intervals);
  const paginationSuffix = pagination ? " · " + pagination : "";
  return "Letzte Aktualisierung: " + updated + counts + paginationSuffix;
}

function renderIntervalsConnection(data, configured) {
  const intervals = intervalsConnectionState(data, configured);
  const healthy = intervals.configured && intervals.state !== "error";
  const labels = {
    not_configured: "Nicht konfiguriert",
    syncing: "Synchronisierung läuft…",
    error: "Fehler bei letzter Aktualisierung",
    connected: "Verbunden",
  };
  settingsStatus("#intervalsConnectionStatus", healthy, labels[intervals.state] || "Konfiguriert · noch nicht getestet");
  const detail = $("#intervalsConnectionDetail");
  if (detail) {
    detail.classList.toggle("error", Boolean(intervals.last_error));
    detail.textContent = intervalsConnectionDetail(intervals);
  }
  return healthy;
}

function weatherConnectionLabel(weather) {
  if (!weather.configured) return "Nicht konfiguriert";
  return weather.loading ? "Wird geladen" : "Konfiguriert";
}

function weatherConnectionDetail(weather) {
  if (!weather.configured) return "Kein API-Schlüssel erforderlich · Standort im Profil hinterlegen";
  const location = [weather.location?.name, weather.location?.country].filter(Boolean).join(", ");
  const prefix = location ? "Standort: " + location + " · " : "";
  const fetched = weather.fetched_at ? "letzte Abfrage: " + formatTime(weather.fetched_at) : "Standort im Profil hinterlegen";
  return prefix + fetched;
}

function renderWeatherConnection(weather) {
  settingsStatus("#weatherConnectionStatus", weather.configured, weatherConnectionLabel(weather));
  const detail = $("#weatherConnectionDetail");
  if (detail) detail.textContent = weatherConnectionDetail(weather);
  const button = $("#weatherSyncButton");
  if (button) {
    const running = Boolean(state.localSync.weather);
    button.disabled = !weather.configured || running;
    button.textContent = running ? "Wetter wird aktualisiert…" : "Wetter aktualisieren";
  }
}

function updateUnfocusedInput(selector, value) {
  const input = $(selector);
  if (input && document.activeElement !== input) input.value = value;
}

function renderSettingsSyncDayInputs(data) {
  updateUnfocusedInput("#intervalsSyncDays", data.sync_settings?.intervals_days || 84);
  updateUnfocusedInput("#garminSyncDays", data.sync_settings?.garmin_days || 84);
}

function calendarHorizonText(data) {
  const window = data.planning_view?.provider_window || {};
  if (window.start && window.end) return "Die Ansicht bleibt auf das lokal geladene Intervals.icu-Fenster " + window.start + " bis " + window.end + " begrenzt.";
  return "Die Ansicht wird auf das lokal geladene Providerfenster begrenzt.";
}

function renderCalendarDisplayInputs(data) {
  const display = data.calendar_display || CALENDAR_DISPLAY_DEFAULTS;
  const pastWeeks = calendarDisplayValue(display.past_weeks, CALENDAR_DISPLAY_DEFAULTS.past_weeks);
  const futureWeeks = calendarDisplayValue(display.future_weeks, CALENDAR_DISPLAY_DEFAULTS.future_weeks);
  updateUnfocusedInput("#calendarDisplayPastWeeks", pastWeeks);
  updateUnfocusedInput("#calendarDisplayFutureWeeks", futureWeeks);
  const summary = $("#calendarDisplaySummary");
  if (summary) summary.textContent = pastWeeks + " zurück · " + futureWeeks + " voraus";
  const hint = $("#calendarHorizonHint");
  if (hint) hint.textContent = calendarHorizonText(data);
}

function renderSettingsInputs(data) {
  renderSettingsSyncDayInputs(data);
  renderCalendarDisplayInputs(data);
}

function intervalsSyncRunning(data, fullRunning) {
  return Boolean(data.sync?.running || state.localSync.intervals || fullRunning);
}

function intervalsFullResyncText(fullResync, fullRunning) {
  if (fullRunning && fullResync.status) return fullResync.status;
  if (fullResync.last_error) return fullResync.last_error;
  if (fullResync.last_resync_at) return "Letzter vollständiger Resync: " + formatTime(fullResync.last_resync_at);
  return "Löscht nur lokale Intervals.icu-Daten; die Cloud bleibt unverändert.";
}

function renderIntervalsSyncControls(data, configured) {
  const fullResync = data.provider_resync?.intervals || {};
  const fullRunning = Boolean(fullResync.running || state.localSync.intervalsFull);
  const syncRunning = intervalsSyncRunning(data, fullRunning);
  const intervalsConfigured = Boolean(configured.intervals);
  setProviderSetupHint("#intervalsSetupHint", intervalsConfigured);
  const syncButton = $("#systemIntervalsSyncButton");
  if (syncButton) {
    syncButton.disabled = syncRunning || !intervalsConfigured;
    syncButton.textContent = data.sync?.running || state.localSync.intervals ? "Synchronisierung läuft…" : "Synchronisieren";
  }
  const fullButton = $("#systemIntervalsFullResyncButton");
  if (fullButton) {
    fullButton.disabled = !intervalsConfigured || fullRunning || Boolean(data.sync?.running || state.localSync.intervals);
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  const status = $("#intervalsFullResyncStatus");
  if (status) {
    status.classList.toggle("error", Boolean(fullResync.last_error));
    status.textContent = intervalsFullResyncText(fullResync, fullRunning);
  }
}

function renderGarminSyncControl(data) {
  const garminConfigured = Boolean(data.garmin?.configured);
  setProviderSetupHint("#garminSetupHint", garminConfigured);
  const button = $("#garminSyncButton");
  if (!button) return;
  const running = Boolean(data.garmin_sync?.running || state.localSync.garmin);
  button.disabled = running || !garminConfigured;
  button.textContent = running ? "Synchronisierung läuft…" : "Garmin synchronisieren";
  const fullButton = $("#garminFullResyncButton");
  if (fullButton && !garminConfigured) fullButton.disabled = true;
}

function setProviderSetupHint(selector, configured) {
  const hint = $(selector);
  if (hint) hint.hidden = Boolean(configured);
}

function renderSettingsSyncControls(data, configured) {
  renderIntervalsSyncControls(data, configured);
  renderGarminSyncControl(data);
}

function renderSettingsUsage(data) {
  const usage = data.usage || {};
  const providerLabel = "OpenAI";
  const usageNode = $("#usageSummary");
  if (usageNode) {
    const rateLimits = usage.rate_limits || {};
    const remaining = rateLimits.remaining_requests != null || rateLimits.remaining_tokens != null
      ? ` · Restkontingent im aktuellen Anbieterfenster: ${rateLimits.remaining_requests ?? "?"} Anfragen / ${rateLimits.remaining_tokens ?? "?"} Tokens`
      : " · Restkontingent wird nach einem API-Aufruf angezeigt";
    const error = usage.status?.state === "error" ? ` · Status: ${usage.status.message || "Fehler bei letzter Anfrage"}` : "";
    usageNode.textContent = `${providerLabel} heute: ${usage.requests || 0} Anfragen · ${usage.total_tokens || 0} Tokens${remaining}${error}`;
  }
  const privacy = $("#privacySummary");
  if (privacy) privacy.textContent = `${usage.requests || 0} ${providerLabel}-Anfragen heute`;
}

function garminConnectionLabel(garmin, running) {
  if (!garmin.configured) return "Nicht konfiguriert";
  if (running) return "Synchronisierung läuft…";
  return garmin.source === "fixture" ? "Lokale Testdatei aktiv" : "Konfiguriert";
}

function renderConnectionsSummary(openaiHealthy, intervalsHealthy, garminConfigured, weatherConfigured) {
  const connections = $("#connectionsSummary");
  if (!connections) return;
  const values = [["OpenAI", openaiHealthy], ["Intervals", intervalsHealthy], ["Garmin", garminConfigured], ["Open-Meteo", weatherConfigured]];
  connections.textContent = values.map(([label, active]) => `${label} ${active ? "✓" : "–"}`).join(" · ");
}

function renderSettings(data) {
  const configured = data.configured || {};
  const status = data.usage?.status || {};
  const openaiHealthy = renderAiConnection(configured.openai, status);
  const intervalsHealthy = renderIntervalsConnection(data, configured);
  const garmin = data.garmin || {};
  const garminRunning = Boolean(data.garmin_sync?.running || state.localSync.garmin);
  settingsStatus("#garminConnectionStatus", garmin.configured, garminConnectionLabel(garmin, garminRunning));
  renderWeatherConnection(data.weather || {});
  renderConnectionsSummary(openaiHealthy, intervalsHealthy, garmin.configured, data.weather?.configured);
  renderSettingsInputs(data);
  renderSettingsSyncControls(data, configured);
  renderSettingsUsage(data);
  renderNotificationStatus();
  renderProviderAttention(data);
  renderConnectionsSyncProgress(data);
  renderProviderFreshness(data);
}
