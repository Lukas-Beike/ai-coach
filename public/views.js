function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function replaceMarkdownLinks(value) {
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
    html += `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
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
  html = replaceMarkdownLinks(html);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__(.+?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/_([^_\n]+)_/g, "<em>$1</em>");
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
