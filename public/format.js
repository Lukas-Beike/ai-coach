(function initAppFormat() {
  const LOCALE = "de-DE";
  const DAY_MS = 24 * 60 * 60 * 1000;
  const DATE_KEY = /^(\d{4})-(\d{2})-(\d{2})$/;

  // Returns the UTC midnight timestamp for a valid YYYY-MM-DD key, otherwise null.
  function dateKeyUtc(value) {
    const match = DATE_KEY.exec(String(value ?? ""));
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const timestamp = Date.UTC(year, month - 1, day);
    const check = new Date(timestamp);
    if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null;
    return timestamp;
  }

  function toDate(value) {
    if (value == null || value === "") return null;
    const parsed = value instanceof Date ? value : new Date(value);
    return Number.isNaN(parsed.valueOf()) ? null : parsed;
  }

  // Formats in the requested zone; an invalid or missing zone falls back to the browser zone.
  function formatDateTime(options, date, timeZone) {
    if (timeZone) {
      try {
        return new Intl.DateTimeFormat(LOCALE, { ...options, timeZone }).format(date);
      } catch (_) {
        // Invalid zone names are ignored; the browser zone is used below.
      }
    }
    return new Intl.DateTimeFormat(LOCALE, options).format(date);
  }

  function number(value, { digits = 1 } = {}) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return null;
    return new Intl.NumberFormat(LOCALE, { maximumFractionDigits: digits }).format(numeric);
  }

  function distance(meters) {
    if (meters == null || meters === "") return null;
    const value = Number(meters);
    if (!Number.isFinite(value) || value <= 0) return null;
    const km = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value / 1000);
    return `${km} km`;
  }

  // Training duration: "45 min" under one hour, otherwise "1:05 h".
  function duration(seconds) {
    if (seconds == null || seconds === "") return null;
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return null;
    const totalMinutes = Math.round(value / 60);
    if (totalMinutes < 60) return `${totalMinutes} min`;
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return `${hours}:${String(minutes).padStart(2, "0")} h`;
  }

  // Stopwatch-style clock for pace and lap values: "h:mm:ss" or "m:ss".
  function clock(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return null;
    const total = Math.round(Number(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainder = total % 60;
    return hours
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
      : `${minutes}:${String(remainder).padStart(2, "0")}`;
  }

  function date(value, { timeZone } = {}) {
    const dayStart = dateKeyUtc(value);
    if (dayStart != null) return formatDateTime({ dateStyle: "medium", timeZone: "UTC" }, new Date(dayStart));
    const parsed = toDate(value);
    return parsed ? formatDateTime({ dateStyle: "medium" }, parsed, timeZone) : null;
  }

  function dateTime(value, { timeZone } = {}) {
    const parsed = toDate(value);
    return parsed ? formatDateTime({ dateStyle: "medium", timeStyle: "short" }, parsed, timeZone) : null;
  }

  function relativeDay(dateKey, todayKey) {
    const target = dateKeyUtc(dateKey);
    const today = dateKeyUtc(todayKey);
    if (target == null || today == null) return null;
    const days = Math.round((target - today) / DAY_MS);
    if (days === 0) return "Heute";
    if (days === 1) return "Morgen";
    if (days === -1) return "Gestern";
    return days > 0 ? `in ${days} Tagen` : `vor ${-days} Tagen`;
  }

  const AppFormat = Object.freeze({ number, distance, duration, clock, date, dateTime, relativeDay });
  globalThis.AppFormat = AppFormat;
  if (typeof module !== "undefined") module.exports = AppFormat;
})();
