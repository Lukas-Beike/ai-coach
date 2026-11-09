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

function markdownCodeSpanEnd(text, start, end) {
  let ticks = 0;
  while (text[start + ticks] === "`") ticks += 1;
  let index = start + ticks;
  while (index < end) {
    if (text[index] !== "`") {
      index += 1;
      continue;
    }
    let run = 0;
    while (text[index + run] === "`") run += 1;
    if (run === ticks) return index + run;
    index += run;
  }
  return null;
}

function markdownTableCells(line) {
  const text = line.trim();
  const start = text.startsWith("|") ? 1 : 0;
  const end = text.length > start && text.endsWith("|") && !text.endsWith(String.raw`\|`) ? text.length - 1 : text.length;
  const cells = [];
  let cell = "";
  let index = start;
  while (index < end) {
    const character = text[index];
    if (character === "\\" && text[index + 1] === "|") {
      cell += "|";
      index += 2;
    } else if (character === "`") {
      const spanEnd = markdownCodeSpanEnd(text, index, end);
      if (spanEnd === null) {
        cell += character;
        index += 1;
      } else {
        cell += text.slice(index, spanEnd).replaceAll(String.raw`\|`, "|");
        index = spanEnd;
      }
    } else if (character === "|") {
      cells.push(cell.trim());
      cell = "";
      index += 1;
    } else {
      cell += character;
      index += 1;
    }
  }
  cells.push(cell.trim());
  return cells;
}

function isMarkdownTableSeparator(line) {
  const value = line.trim();
  return value.includes("|") && value.includes("-") && /^[|:\- ]+$/.test(value);
}

function markdownTableRow(line, columnCount) {
  const cells = markdownTableCells(line).slice(0, columnCount);
  while (cells.length < columnCount) cells.push("");
  const row = cells.map((cell) => `<td>${inlineMarkdown(cell)}</td>`).join("");
  return `<tr>${row}</tr>`;
}

function renderMarkdownTable(lines, state, output) {
  flushMarkdownParagraph(state, output);
  closeMarkdownList(state, output);
  const headers = markdownTableCells(lines[0]);
  const head = headers.map((cell) => `<th scope="col">${inlineMarkdown(cell)}</th>`).join("");
  const body = lines.slice(2).map((line) => markdownTableRow(line, headers.length)).join("");
  output.push(`<div class="markdown-table" tabindex="0" role="region" aria-label="Tabelle"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
}

function flushMarkdownTable(state, output) {
  if (!state.tableLines.length) return;
  const lines = state.tableLines;
  state.tableLines = [];
  if (lines.length > 1 && isMarkdownTableSeparator(lines[1])) renderMarkdownTable(lines, state, output);
  else for (const line of lines) renderMarkdownLine(line, state, output);
}

function renderMarkdownSourceLine(line, state, output) {
  if (line.trimStart().startsWith("```")) {
    flushMarkdownTable(state, output);
    toggleMarkdownCode(state, output);
  } else if (state.inCode) state.codeLines.push(line);
  else if (line.includes("|")) state.tableLines.push(line);
  else if (!line.trim()) {
    flushMarkdownTable(state, output);
    flushMarkdownParagraph(state, output);
    closeMarkdownList(state, output);
  } else {
    flushMarkdownTable(state, output);
    renderMarkdownLine(line, state, output);
  }
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replaceAll("\r", "").split("\n");
  const output = [];
  const state = { paragraph: [], listType: null, inCode: false, codeLines: [], tableLines: [] };
  for (const line of lines) renderMarkdownSourceLine(line, state, output);
  flushMarkdownTable(state, output);
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
  return String(event?.starts_at_local || event?.started_at_local || event?.date || "").slice(0, 10);
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
    if (active) centerInScroller(link);
  });
}

// The one-row area bar scrolls sideways: the active area stays in view.
function centerInScroller(link) {
  const bar = link.parentElement;
  if (!bar || bar.scrollWidth <= bar.clientWidth) return;
  bar.scrollLeft = link.offsetLeft - (bar.clientWidth - link.offsetWidth) / 2;
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
function populateProfileSports(form, value) {
  const selectedSports = new Set(String(value || "").split(",").map((item) => item.trim()).filter(Boolean));
  form.querySelectorAll('input[name="sports"]').forEach((box) => { box.checked = selectedSports.has(box.value); });
}

function populateProfileTimezone(field, value) {
  if (value && ![...field.options].some((option) => option.value === value)) field.append(new Option(`${value} (gespeichert)`, value));
  field.value = value || "";
}

function populateProfileField(form, key, value) {
  if (key === "sports") return populateProfileSports(form, value);
  const field = form.elements[key];
  if (!field) return;
  if (key === "timezone" && field.tagName === "SELECT") return populateProfileTimezone(field, value);
  field.value = value || "";
}

const PROFILE_SPORT_LABELS = { Cycling: "Radfahren", Running: "Laufen", Swimming: "Schwimmen", Strength: "Krafttraining", WeightTraining: "Krafttraining", Triathlon: "Triathlon", Other: "Andere" };

function profileSportsLabel(sports) {
  return String(sports || "").split(",").map((item) => item.trim()).filter(Boolean)
    .map((item) => (Object.hasOwn(PROFILE_SPORT_LABELS, item) ? PROFILE_SPORT_LABELS[item] : item)).join(", ");
}

const PROFILE_TRAINING_MODEL_LABELS = { pyramidal: "Pyramidal", polarized: "Polarisiert", threshold: "Schwellenbetont", sweet_spot: "Sweet Spot" };
const PROFILE_SUMMARY_EMPTY = "Noch nicht ausgefüllt";
const PROFILE_SUMMARY_GOALS_LENGTH = 40;

function profileGoalsLine(goals) {
  const line = String(goals || "").trim().split("\n")[0].trim();
  return line.length > PROFILE_SUMMARY_GOALS_LENGTH ? `${line.slice(0, PROFILE_SUMMARY_GOALS_LENGTH - 1).trimEnd()}…` : line;
}

function profilePreferencesLine(profile) {
  const count = Object.entries(profile).filter(([key, value]) => key.startsWith("training_preferences") && String(value || "").trim()).length;
  if (!count) return "";
  return count === 1 ? "1 Präferenz" : `${count} Präferenzen`;
}

// One line per profile section: what the athlete finds inside before opening it.
function profileSummaries(profile) {
  const lines = {
    profileSummary: [profile.name, profileSportsLabel(profile.sports)],
    profileGoalsSummary: [profile.typical_weekly_volume, profileGoalsLine(profile.goals)],
    profileTrainingSummary: [PROFILE_TRAINING_MODEL_LABELS[profile.training_model], profilePreferencesLine(profile)],
    profileSourcesSummary: [profile.timezone, profile.weather_location],
  };
  return Object.fromEntries(Object.entries(lines).map(([id, parts]) => [id, parts.filter(Boolean).join(" · ") || PROFILE_SUMMARY_EMPTY]));
}

function renderProfileSummary(profile) {
  for (const [id, text] of Object.entries(profileSummaries(profile))) {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  }
}

function renderProfile(profile) {
  setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
  if (state.profileDirty) return;
  const form = $("#profileForm");
  for (const [key, value] of Object.entries(profile)) populateProfileField(form, key, value);
  if (form.elements.coaching_style?.value === "Supportive, direct, and evidence-aware") form.elements.coaching_style.value = "Unterstützend, direkt und evidenzbasiert";
  state.profileBaseline = profileFormValues(form);
  renderProfileSummary(profile);
}

function renderModelChoice(model, selectId, descriptionId) {
  if (!model) return;
  const select = $(selectId);
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
  $(descriptionId).textContent = selected?.description || "Wähle die Balance aus Qualität, Tempo und Kosten.";
}

function renderModel(model) {
  renderModelChoice(model, "#modelSelect", "#modelDescription");
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
  setConnectionChip("#openaiConnectionStatus", connectionKind({ configured, error: activeError }));
  const detail = $("#openaiConnectionDetail");
  if (detail) {
    detail.classList.toggle("error", Boolean(configured && activeError));
    detail.textContent = aiConnectionDetail(configured, status);
  }
}

function intervalsConnectionState(data, configured) {
  return data.intervals || {
    configured: Boolean(configured.intervals),
    state: configured.intervals ? "configured" : "not_configured",
  };
}

function intervalsConnectionDetail(intervals) {
  const librarySync = intervals.library_sync || {};
  if (!intervals.configured) return "API-Schlüssel nicht konfiguriert";
  if (intervals.state === "syncing") return "Intervals.icu wird synchronisiert.";
  if (intervals.last_error) return intervals.last_error;
  if (intervals.state === "configured") return "Noch nicht getestet";
  if (!librarySync.last_sync_at) return "Noch keine Synchronisierung durchgeführt";
  const updated = formatTime(librarySync.last_sync_at);
  const libraryCount = Number(librarySync.state?.synced || 0);
  const counts = libraryCount ? " · " + libraryCount + " Bibliothekseinheiten" : "";
  return "Letzte Aktualisierung: " + updated + counts;
}

function renderIntervalsConnection(data, configured) {
  const intervals = intervalsConnectionState(data, configured);
  setConnectionChip("#intervalsConnectionStatus", intervalsConnectionKind(intervals));
  const detail = $("#intervalsConnectionDetail");
  if (detail) {
    detail.classList.toggle("error", Boolean(intervals.last_error));
    detail.textContent = intervalsConnectionDetail(intervals);
  }
}

function weatherConnectionDetail(weather) {
  if (!weather.configured) return "Kein API-Schlüssel erforderlich · Standort im Profil hinterlegen";
  const location = [weather.location?.name, weather.location?.country].filter(Boolean).join(", ");
  const prefix = location ? "Standort: " + location + " · " : "";
  const fetched = weather.fetched_at ? "letzte Abfrage: " + formatTime(weather.fetched_at) : "Standort im Profil hinterlegen";
  return weather.loading ? prefix + "wird geladen" : prefix + fetched;
}

function renderWeatherConnection(weather) {
  setConnectionChip("#weatherConnectionStatus", connectionKind({ configured: weather.configured }));
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
  updateUnfocusedInput("#garminSyncDays", data.sync_settings?.garmin_days || 84);
}

function calendarHorizonText(data) {
  const window = data.planning_view?.provider_window || {};
  if (window.start && window.end) return "Die Ansicht bleibt auf das lokal geladene Providerfenster " + window.start + " bis " + window.end + " begrenzt.";
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

function renderIntervalsSyncControls(_data, configured) {
  setProviderSetupHint("#intervalsSetupHint", Boolean(configured.intervals));
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
  const rateLimits = usage.rate_limits || {};
  const number = (value) => Number(value || 0).toLocaleString("de-DE");
  const optionalNumber = (value) => (value == null ? "Noch nicht bekannt" : number(value));
  const lastRequest = usage.last_request_at ? new Date(usage.last_request_at) : null;
  const values = {
    usageSummary: `${number(usage.requests)} Anfragen · ${number(usage.total_tokens)} Tokens heute`,
    usageRequests: number(usage.requests),
    usageInputTokens: number(usage.input_tokens),
    usageOutputTokens: number(usage.output_tokens),
    usageTotalTokens: number(usage.total_tokens),
    usageRemainingRequests: optionalNumber(rateLimits.remaining_requests),
    usageRemainingTokens: optionalNumber(rateLimits.remaining_tokens),
    usageLastRequest: lastRequest && !Number.isNaN(lastRequest.getTime())
      ? lastRequest.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })
      : "Heute noch keine",
    usageStatus: usage.status?.state === "error" ? usage.status.message || "Fehler bei letzter Anfrage" : "In Ordnung",
  };
  for (const [id, text] of Object.entries(values)) {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  }
}

function renderGarminConnection(data) {
  const garmin = data.garmin || {};
  setConnectionChip("#garminConnectionStatus", garminConnectionKind(garmin));
  const lines = $("#garminSourceLines");
  if (!lines) return;
  const sdkConnected = Boolean(data.credentials?.garmin_connection?.connected ?? data.credentials?.garmin_connected);
  lines.replaceChildren(...garminSourceLines(garmin, sdkConnected).map((line) => {
    const item = document.createElement("li");
    item.textContent = `${line.label}: ${line.text}`;
    return item;
  }));
}

function renderSettings(data) {
  const configured = data.configured || {};
  const status = data.usage?.status || {};
  renderAiConnection(configured.openai, status);
  renderIntervalsConnection(data, configured);
  renderGarminConnection(data);
  renderWeatherConnection(data.weather || {});
  renderWahooConnection(data);
  renderSettingsInputs(data);
  renderSettingsSyncControls(data, configured);
  renderSettingsUsage(data);
  renderNotificationStatus();
  renderProviderAttention(data);
  renderConnectionsSyncProgress(data);
  renderProviderFreshness(data);
  renderProviderCredentials(data);
}

function renderServiceTier(model) {
  renderModelChoice(model, "#serviceTierSelect", "#serviceTierDescription");
}
