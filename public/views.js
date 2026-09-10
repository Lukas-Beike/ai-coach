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
    const validUrl = validScheme && label && ![...url].some((character) => "()\r\n\t ".includes(character));
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
    const token = `__COACH_CODE_SPAN_${codeSpans.length}__`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  html = replaceMarkdownLinks(html);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__(.+?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  return html.replace(/__COACH_CODE_SPAN_(\d+)__/g, (_, index) => codeSpans[Number(index)]);
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

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replaceAll("\r", "").split("\n");
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
      output.push(`<p>${inlineMarkdown(paragraph.join("\n")).replaceAll("\n", "<br>")}</p>`);
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
    const heading = headingFromMarkdownLine(line);
    if (heading) { flushParagraph(); closeList(); output.push(`<h${heading.level}>${inlineMarkdown(heading.text.replace(/#+$/, "").trim())}</h${heading.level}>`); continue; }
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { flushParagraph(); closeList(); output.push("<hr>"); continue; }
    const listItem = listItemFromMarkdownLine(line);
    if (listItem) {
      flushParagraph();
      const nextType = listItem.type;
      if (listType !== nextType) { closeList(); output.push(`<${nextType}>`); listType = nextType; }
      output.push(`<li>${inlineMarkdown(listItem.text)}</li>`);
      continue;
    }
    const quote = /^\s*>\s?(.*)$/.exec(line);
    if (quote) { flushParagraph(); closeList(); output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); continue; }
    closeList(); paragraph.push(line);
  }
  if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  flushParagraph(); closeList();
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
  } catch (error) { void error; return localDateKey(instant); }
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
  if (number === 0) return "☀️";
  if (number === 1) return "🌤️";
  if (number === 2) return "⛅";
  if (number === 3) return "☁️";
  if ([45, 48].includes(number)) return "🌫️";
  if (number >= 51 && number <= 57) return "🌦️";
  if (number >= 61 && number <= 67) return "🌧️";
  if (number >= 71 && number <= 77) return number === 75 ? "❄️" : "🌨️";
  if (number >= 80 && number <= 82) return number === 80 ? "🌦️" : "🌧️";
  if (number >= 85 && number <= 86) return "🌨️";
  if (number >= 95) return "⛈️";
  return "🌤️";
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
