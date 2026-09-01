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
  } catch (_) { return localDateKey(instant); }
}

function dateFromKey(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : new Date(NaN);
}

function addDateKey(value, days) {
  const date = dateFromKey(value);
  if (Number.isNaN(date.valueOf())) return "";
  date.setDate(date.getDate() + days);
  return localDateKey(date);
}

function dateKeyDifference(left, right) {
  const a = dateFromKey(left);
  const b = dateFromKey(right);
  if (Number.isNaN(a.valueOf()) || Number.isNaN(b.valueOf())) return 0;
  return Math.round((Date.UTC(a.getFullYear(), a.getMonth(), a.getDate()) - Date.UTC(b.getFullYear(), b.getMonth(), b.getDate())) / 86400000);
}

function plannedEventDate(event) {
  return String(event?.start_date_local || event?.date || "").slice(0, 10);
}

function isCoachOwnedWorkout(event) {
  return String(event?.category || "").toUpperCase() === "WORKOUT"
    && String(event?.external_id || "").startsWith("intervals-coach-");
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
