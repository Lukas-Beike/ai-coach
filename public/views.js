function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function markdownEmphasis(value) {
  return value.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>");
}

// The host after a link whose label does not name it, so a label cannot hide the destination.
function linkHostNote(label, url) {
  let host = "";
  try { host = new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
  if (!host || label.toLowerCase().includes(host.toLowerCase())) return "";
  return `<span class="link-host"> (${escapeHtml(host)})</span>`;
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
    linkSpans.push(`<a href="${url}" target="_blank" rel="noopener noreferrer">${markdownEmphasis(label)}</a>${linkHostNote(label, url)}`);
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
  renderFirstThresholdEstimate(state.data?.first_threshold_estimate, profile);
  refreshThresholdBox();
  setDirtyIndicator("profileDirtyIndicator", state.profileDirty);
  if (state.profileDirty) return;
  const form = $("#profileForm");
  for (const [key, value] of Object.entries(profile)) populateProfileField(form, key, value);
  if (form.elements.coaching_style?.value === "Supportive, direct, and evidence-aware") form.elements.coaching_style.value = "Unterstützend, direkt und evidenzbasiert";
  state.profileBaseline = profileFormValues(form);
  renderProfileSummary(profile);
}

const FIRST_THRESHOLD_QUALITY_LABELS = { good: "gut", low: "niedrig" };

function firstThresholdEstimateText(estimate) {
  const percent = `${String(estimate.percent_lthr).replace(".", ",")} % LSHF`;
  const sessions = `${estimate.sessions} ${estimate.sessions === 1 ? "Einheit" : "Einheiten"}`;
  const quality = `Qualität ${FIRST_THRESHOLD_QUALITY_LABELS[estimate.quality] || estimate.quality}`;
  return ["Schätzung", Number.isFinite(estimate.bpm) ? `${estimate.bpm} bpm` : null, percent, sessions, quality].filter(Boolean).join(" · ");
}

function renderFirstThresholdEstimate(estimate, profile = {}) {
  const box = document.getElementById("firstThresholdEstimate");
  if (!box) return;
  box.hidden = !estimate;
  if (estimate) {
    document.getElementById("firstThresholdEstimateText").textContent = firstThresholdEstimateText(estimate);
    box.dataset.percent = String(estimate.percent_lthr);
  }
  const stored = document.getElementById("firstThresholdStoredLabel");
  if (stored) stored.textContent = profile?.first_threshold_pct && profile.first_threshold_origin === "estimated" ? "Gespeichert (% LSHF, geschätzt)" : "Gespeichert (% LSHF)";
}

const MODEL_PROVIDER_GROUPS = Object.freeze({ openai: "OpenAI", anthropic: "Claude" });

// Pure: a Claude family names the model it resolves to; the rest keep their label.
function modelOptionLabel(option) {
  return option.provider === "anthropic" && option.model ? `${option.label} (${option.model})` : option.label;
}

function modelOptionElement(option) {
  const element = document.createElement("option");
  element.value = option.id;
  element.textContent = modelOptionLabel(option);
  element.title = option.description || "";
  element.disabled = Boolean(option.disabled);
  return element;
}

function renderModelChoice(model, selectId) {
  if (!model) return;
  const select = $(selectId);
  const options = model.options || [];
  const signature = options.map((option) => [option.id, modelOptionLabel(option), Boolean(option.disabled)].join(":")).join(",");
  if (select.dataset.signature !== signature) {
    select.replaceChildren();
    const groups = new Map();
    for (const option of options) {
      const name = MODEL_PROVIDER_GROUPS[option.provider];
      if (!name) {
        select.append(modelOptionElement(option));
        continue;
      }
      if (!groups.has(name)) {
        const group = document.createElement("optgroup");
        group.label = name;
        groups.set(name, group);
        select.append(group);
      }
      groups.get(name).append(modelOptionElement(option));
    }
    select.dataset.signature = signature;
  }
  select.value = model.selected;
}

// Pure: the notice for a newly resolved Claude model that was rejected.
function modelNoticeText(model) {
  const selected = (model?.options || []).find((option) => option.id === model.selected);
  return selected?.rejected ? `${selected.rejected} abgelehnt – Coach nutzt ${selected.model}.` : "";
}

// The selects of one task: conversation keeps the original ids.
const COACH_TASKS = ["conversation", "planning", "nutrition"];
function taskSelectId(task, name) {
  return task === "conversation" ? `#${name[0].toLowerCase()}${name.slice(1)}Select` : `#${task}${name}Select`;
}

function renderModel(model) {
  for (const task of COACH_TASKS) {
    const taskModel = model && { ...model, selected: model.tasks?.[task]?.model ?? model.selected };
    renderModelChoice(taskModel, taskSelectId(task, "Model"));
    // Each task block names its own rejected Claude model (#2639).
    const notice = $(task === "conversation" ? "#modelNotice" : `#${task}ModelNotice`);
    if (notice) {
      notice.textContent = modelNoticeText(taskModel);
      notice.hidden = !notice.textContent;
    }
  }
  // A task whose provider has no key disables only its own entry points.
  const planning = $("#quickAnalysisButton");
  if (planning) planning.disabled = model?.tasks?.planning?.ready === false;
  const label = $("#nutritionLabelButton");
  if (label) label.disabled = model?.tasks?.nutrition?.ready === false;
  // Speed modes exist only at OpenAI.
  const tierRow = $("#serviceTierRow");
  const provider = (id) => (model?.options || []).find((option) => option.id === id)?.provider;
  if (tierRow) tierRow.hidden = Boolean(model) && COACH_TASKS.every((task) => provider(model.tasks?.[task]?.model ?? model.selected) === "anthropic");
}

function renderThinkingLevel(thinkingLevel, tasks = {}) {
  if (!thinkingLevel) return;
  const nextIds = (thinkingLevel.options || []).map((option) => option.id).join(",");
  for (const task of COACH_TASKS) {
    const select = $(taskSelectId(task, "ThinkingLevel"));
    if ([...select.options].map((option) => option.value).join(",") !== nextIds) {
      select.replaceChildren();
      for (const option of thinkingLevel.options || []) {
        const element = document.createElement("option");
        element.value = option.id;
        element.textContent = option.label;
        element.title = option.description || "";
        select.append(element);
      }
    }
    select.value = tasks?.[task]?.thinking_level ?? thinkingLevel.selected;
  }
  const modelSummary = $("#modelSettingsSummary");
  const labels = COACH_TASKS.map((task) => $(taskSelectId(task, "Model"))?.selectedOptions?.[0]?.textContent).filter(Boolean);
  if (modelSummary) modelSummary.textContent = [...new Set(labels)].join(" · ");
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

// Before a first Claude request a configured key reads as not checked.
function renderClaudeConnection(configured, status) {
  setConnectionChip("#anthropicConnectionStatus", connectionKind({ configured, error: status.state === "error", unchecked: !status.state }));
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
  if (intervals.state === "error") return intervals.last_error || "Letzter Export fehlgeschlagen";
  if (intervals.state === "configured") return "Noch nicht getestet";
  const usedAt = intervals.last_used_at || librarySync.last_sync_at;
  if (!usedAt) return "Noch keine Synchronisierung durchgeführt";
  const updated = formatTime(usedAt);
  const libraryCount = Number(librarySync.state?.synced || 0);
  const counts = libraryCount ? " · " + libraryCount + " Bibliothekseinheiten" : "";
  return "Letzte Aktualisierung: " + updated + counts;
}

function renderIntervalsConnection(data, configured) {
  const intervals = intervalsConnectionState(data, configured);
  setConnectionChip("#intervalsConnectionStatus", intervalsConnectionKind(intervals));
  const detail = $("#intervalsConnectionDetail");
  if (detail) {
    detail.classList.toggle("error", intervals.state === "error");
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

function renderCalendarDisplayInputs(data) {
  const display = data.calendar_display || CALENDAR_DISPLAY_DEFAULTS;
  const pastWeeks = calendarDisplayValue(display.past_weeks, CALENDAR_DISPLAY_DEFAULTS.past_weeks);
  const futureWeeks = calendarDisplayValue(display.future_weeks, CALENDAR_DISPLAY_DEFAULTS.future_weeks);
  updateUnfocusedInput("#calendarDisplayPastWeeks", pastWeeks);
  updateUnfocusedInput("#calendarDisplayFutureWeeks", futureWeeks);
  const summary = $("#calendarDisplaySummary");
  if (summary) summary.textContent = pastWeeks + " zurück · " + futureWeeks + " voraus";
}

function renderSettingsInputs(data) {
  renderSettingsSyncDayInputs(data);
  renderCalendarDisplayInputs(data);
}

function renderIntervalsSyncControls(configured) {
  setProviderSetupHint("#intervalsSetupHint", Boolean(configured.intervals));
}

function renderGarminSyncControl(data) {
  const garminConfigured = Boolean(data.garmin?.configured);
  setProviderSetupHint("#garminSetupHint", garminConfigured);
  const button = $("#garminSyncButton");
  if (!button) return;
  const running = Boolean(data.garmin_sync?.running || state.localSync.garmin);
  const fullRunning = Boolean(data.provider_resync?.garmin?.running || state.localSync.garminFull);
  button.disabled = running || fullRunning || !garminConfigured;
  button.textContent = running ? "Synchronisierung läuft…" : "Garmin synchronisieren";
  renderGarminFullResync(data);
}

function setProviderSetupHint(selector, configured) {
  const hint = $(selector);
  if (hint) hint.hidden = Boolean(configured);
}

function renderSettingsSyncControls(data, configured) {
  renderIntervalsSyncControls(configured);
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

function renderUsageMonth(data) {
  const usageMonth = data.usage_month || {};
  const models = Array.isArray(usageMonth.models) ? usageMonth.models : [];
  const section = document.getElementById("usageMonth");
  const rows = document.getElementById("usageMonthRows");
  if (!section || !rows) return;
  section.hidden = models.length === 0;
  const [year, month] = String(usageMonth.month || "").split("-").map(Number);
  const title = document.getElementById("usageMonthTitle");
  if (title && year && month) title.textContent = new Date(year, month - 1, 1).toLocaleDateString("de-DE", { month: "long", year: "numeric" });
  const labels = new Map((data.model?.options || []).map((option) => [option.id, option.label]));
  const tokens = new Intl.NumberFormat("de-DE", { notation: "compact", maximumFractionDigits: 1 });
  rows.replaceChildren(...models.map((entry) => {
    const row = document.createElement("tr");
    const cells = [
      labels.get(entry.model) || entry.model || "Unbekannt",
      Number(entry.answers || 0).toLocaleString("de-DE"),
      tokens.format(Number(entry.input_tokens || 0)),
      tokens.format(Number(entry.cached_input_tokens || 0)),
      tokens.format(Number(entry.output_tokens || 0)),
    ];
    row.replaceChildren(...cells.map((text, index) => {
      const cell = document.createElement(index === 0 ? "th" : "td");
      if (index === 0) cell.scope = "row";
      cell.textContent = text;
      return cell;
    }));
    return row;
  }));
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
  const status = data.provider_status?.openai || {};
  renderAiConnection(configured.openai, status);
  renderClaudeConnection(Boolean(configured.anthropic), data.provider_status?.anthropic || {});
  renderIntervalsConnection(data, configured);
  renderGarminConnection(data);
  renderWeatherConnection(data.weather || {});
  renderWahooConnection(data);
  renderSettingsInputs(data);
  renderSettingsSyncControls(data, configured);
  renderSettingsUsage(data);
  renderUsageMonth(data);
  renderNotificationStatus();
  renderProviderAttention(data);
  renderConnectionsSyncProgress(data);
  renderProviderFreshness(data);
  renderProviderCredentials(data);
}

function renderServiceTier(model) {
  renderModelChoice(model, "#serviceTierSelect");
}
