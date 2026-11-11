  function plannedAirValues(weather) {
    const air = weather.air_quality && typeof weather.air_quality === "object" ? weather.air_quality : {};
    const aqi = calendarMetricNumber(air.european_aqi_max);
    const category = air.european_aqi_category ? " (" + air.european_aqi_category + ")" : "";
    return [
      aqi ? `AQI ${aqi}${category}` : "",
      calendarMetricNumber(air.uv_index_max) ? `UV ${calendarMetricNumber(air.uv_index_max)}` : "",
      plannedPollenLabel(weather.pollen),
    ].filter(Boolean);
  }

globalThis.AppPlanViews = Object.freeze({ create, plannedPushTargets, plannedWeekSyncJobs, runPlannedWeekSync, plannedGarminBlockedText });

// One explicit plan_push job, carrying the hashes the entries were shown with.
async function runPlanPush(provider, entries) {
  const job = await api("/api/sync/jobs", { method: "POST", body: JSON.stringify({ provider, type: "plan_push", payload: { entries } }) });
  return globalThis.waitForSyncJob(job.id);
}

// The job entry that removes one listed leftover of a deleted or replaced unit:
// a Garmin workout or Wahoo plan by a remove entry, an Intervals.icu event by the hidden unit's own entry.
function leftoverEntry(provider, item, ids) {
  return provider !== ids.intervals ? { library_workout_id: item.id, remove: true } : { library_workout_id: item.id, expected_payload_hash: item.hash };
}

// What a week's sync delivered per provider: Garmin gets structured workouts, Intervals.icu gets
// strength only as a calendar note, so a note is never mistaken for a workout on the watch.
function plannedWeekSyncSummary(done, ids, providerLabel) {
  const totals = new Map();
  for (const job of done) {
    const item = totals.get(job.provider) || { send: 0, notes: 0, remove: 0 };
    if (job.kind === "remove") item.remove += job.entries.length;
    else {
      item.send += job.entries.length;
      item.notes += job.units.filter((entry) => focusSport(entry) === "strength").length;
    }
    totals.set(job.provider, item);
  }
  const reached = [...totals].map(([provider, item]) => {
    const verb = provider === ids.garmin ? "strukturiert" : "gesendet";
    const sent = item.send ? `${item.send} ${verb}` : "";
    const notes = provider === ids.intervals && item.notes ? `davon ${item.notes} als Notiz` : "";
    const removed = item.remove ? `${item.remove} alte entfernt` : "";
    return `${providerLabel(provider)}: ${[sent, notes, removed].filter(Boolean).join(", ")}`;
  });
  // A strength unit that reached Intervals.icu only as a note says why the watch did not get it.
  const blocked = new Set(done.flatMap((job) => job.units).map(plannedGarminBlockedText).filter(Boolean));
  return [...reached, ...blocked].join(" · ");
}

// Controls sit in the card summary; a click must not toggle the card.
// Before a rebuild: remember which cards are open and which control has focus.
function rememberPlannedEntryState(root) {
  openPlannedEntries = new Set([...root.querySelectorAll(".planned-entry[data-entry-key]")].filter((card) => card.open).map((card) => card.dataset.entryKey));
  for (const key of plannedFocusStatuses.keys()) if (!openPlannedEntries.has(key)) plannedFocusStatuses.delete(key);
  const active = document.activeElement;
  const card = active?.closest?.(".planned-entry[data-entry-key]");
  if (!card || !root.contains(card)) return null;
  return { key: card.dataset.entryKey, name: active.matches("select") ? active.name : "" };
}

function restorePlannedEntryFocus(root, focused) {
  if (!focused) return;
  const card = [...root.querySelectorAll(".planned-entry[data-entry-key]")].find((node) => node.dataset.entryKey === focused.key);
  const target = focused.name ? card?.querySelector(`select[name="${focused.name}"]`) : null;
  (target || card?.querySelector("summary"))?.focus({ preventScroll: true });
}

// The unit's description, or a placeholder when the card body would stay empty.
function appendPlannedDescription(details, text) {
  if (!text && details.childElementCount) return;
  const description = document.createElement("p");
  description.className = "planned-description";
  description.textContent = text || "Keine weiteren Details hinterlegt.";
  details.append(description);
}

function stopSummaryToggle(event) {
  event.preventDefault();
  event.stopPropagation();
}

function plannedCoachButton(label, prompt) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button planned-conflict-button";
  button.textContent = label;
  button.addEventListener("click", (event) => { stopSummaryToggle(event); void globalThis.askCoach?.(prompt); });
  return button;
}

function plannedGarminBlockedText(entry) {
  const reason = entry?.push_blocked && Object.values(entry.push_blocked)[0];
  if (reason === "no_structure") return "Keine Kraftstruktur – nicht an Garmin gesendet";
  if (reason === "unmapped") return "Übung ohne Garmin-Zuordnung – nicht an Garmin gesendet";
  return "";
}

// Providers this planned unit still needs an explicit push to. Past, done,
// in-flight and unconfigured targets get none.
function plannedPushTargets(entry, dateKey, todayKey, { configured = {}, completed = false } = {}) {
  const pending = entry?.push_pending;
  if (!entry?.local_id || !entry.payload_hash || entry.is_completed_activity || completed) return [];
  if (!pending || typeof pending !== "object" || !dateKey || dateKey < todayKey) return [];
  const targets = Object.keys(pending).filter((provider) => pending[provider] === true && configured[provider] === true);
  return targets.sort((a, b) => a.localeCompare(b));
}

const PLAN_PUSH_MAX_ENTRIES = 28;

// The week's replacing sync as plan_push jobs, Intervals.icu last: per provider the week's units
// still to send, then the leftovers the app created there for that week (linked ids only).
function plannedWeekSyncJobs(units, leftovers, todayKey, configured, ids) {
  const jobs = [];
  for (const provider of [ids.garmin, ids.wahoo, ids.intervals]) {
    if (!provider || configured[provider] !== true) continue;
    const sends = units
      .filter(({ entry, dateKey, completed }) => plannedPushTargets(entry, dateKey, todayKey, { configured, completed }).includes(provider))
      .map(({ entry }) => ({ unit: entry, entry: { library_workout_id: entry.local_id, expected_payload_hash: entry.payload_hash } }));
    const removals = (leftovers[provider] || []).map((item) => ({ item, entry: leftoverEntry(provider, item, ids) }));
    for (const [kind, parts] of [["send", sends], ["remove", removals]]) {
      for (let index = 0; index < parts.length; index += PLAN_PUSH_MAX_ENTRIES) {
        const chunk = parts.slice(index, index + PLAN_PUSH_MAX_ENTRIES);
        jobs.push({
          provider,
          kind,
          entries: chunk.map((part) => part.entry),
          units: chunk.map((part) => part.unit).filter(Boolean),
          items: chunk.map((part) => part.item).filter(Boolean),
        });
      }
    }
  }
  return jobs;
}

// Run a week's jobs one after another; a failed job never stops the others. The message names
// the failures first, then what arrived where.
async function runPlannedWeekSync(jobs, ids, providerLabel) {
  const failures = [];
  const done = [];
  for (const job of jobs) {
    const name = providerLabel(job.provider);
    try {
      const outcome = await runPlanPush(job.provider, job.entries);
      if (outcome.status === "completed") {
        done.push(job);
        continue;
      }
      // A partial job still delivered its completed entries; name those as well.
      const reached = new Set((outcome.items || []).filter((item) => item.status === "completed").map((item) => item.item_key));
      const entries = job.entries.filter((entry) => reached.has(entry.library_workout_id));
      if (entries.length) done.push({ ...job, entries, units: job.units.filter((unit) => reached.has(unit.local_id)) });
      failures.push(`${name}: ${job.kind === "remove" ? "Alte Einträge nicht entfernt: " : ""}${globalThis.providerJobErrorDetail?.(outcome) || "Synchronisierung fehlgeschlagen"}`);
    } catch (error) {
      failures.push(`${name}: ${error.message}`);
    }
  }
  const summary = plannedWeekSyncSummary(done, ids, providerLabel);
  return { failed: failures.length > 0, message: [...failures, summary].filter(Boolean).join(" · ") || "Synchronisiert" };
}

// A leftover belongs to the week of its day; an undated or earlier one to the current week and a
// later one to the last shown week, so every leftover stays reachable from a week button.
function plannedLeftoverWeek(item, currentWeekKey, lastWeekKey, weekStart) {
  const day = String(item?.date || "").slice(0, 10);
  const week = day ? weekStart(day) : "";
  if (!week || week < currentWeekKey) return currentWeekKey;
  if (week > lastWeekKey) return lastWeekKey;
  return week;
}

const CALENDAR_MARKERS = [
  { key: "no_training", name: "NO_TRAINING", label: "Kein Training" },
  { key: "no_intensity", name: "NO_INTENSITY", label: "Keine Intensität" },
  { key: "short_only", name: "SHORT_ONLY", label: "Nur kurze Einheiten" },
];
// Mirrors backend/calendar/markers.py::has_marker: "[" or "(" opens, "]" or ")" closes,
// the words may be separated by spaces, underscores or hyphens (or none), and case is ignored.
const MARKER_WORD_GAP = String.raw`[\s_-]*`;
const calendarMarkerSource = (name) => String.raw`[\[(]\s*${name.replaceAll("_", MARKER_WORD_GAP)}\s*[\])]`;
const CALENDAR_MARKER_PATTERN = new RegExp(
  CALENDAR_MARKERS.map(({ name }) => calendarMarkerSource(name)).join("|"),
  "gi",
);
// The day heading flags rain, UV, air and pollen only when notable; all figures stay in the weather symbol's tooltip.
const PLANNED_RAIN_FLAG_MIN_PERCENT = 50;
const PLANNED_UV_FLAG_MIN = 6;
const PLANNED_AQI_FLAG_MIN = 60; // European AQI "schlecht" and worse
const PLANNED_CAMS_POLLEN_FLAG_MIN = 10; // grains/m³; DWD levels count from 1
const PLANNED_DAY_STATUS_LABELS = new Map([["rest", "Ruhetag"], ["pause", "Trainingspause"]]);

function externalCalendarDetail(calendar) {
  if (calendar.last_error) return "Fehler bei letzter Aktualisierung";
  const skipped = Number(calendar.skipped_events) || 0;
  return skipped ? `${skipped} Termine übersprungen` : "";
}

function stripCalendarMarkers(text) {
  return String(text || "").replace(CALENDAR_MARKER_PATTERN, "").replace(/\s{2,}/g, " ").trim();
}

function calendarMarkerKeys(source) {
  if (!source || typeof source !== "object") return [];
  const name = String(source.name || "");
  return CALENDAR_MARKERS
    .filter(({ key, name: markerName }) => Boolean(source[key]) || new RegExp(calendarMarkerSource(markerName), "i").test(name))
    .map(({ key }) => key);
}

function plannedDayStatusLabel(dayStatus) {
  return PLANNED_DAY_STATUS_LABELS.get(dayStatus) || null;
}

function plannedConflictLabels(conflicts) {
  return [...new Set((Array.isArray(conflicts) ? conflicts : [])
    .map((conflict) => String(conflict?.label || "").trim())
    .filter(Boolean))];
}

// Day context is plain text lines in one neutral style; conflicts belong to the planned session itself.
function plannedDayNoteSpecs(dayContext, competitions, dateKey) {
  const context = dayContext && typeof dayContext === "object" ? dayContext : {};
  const appointments = (Array.isArray(context.appointments) ? context.appointments : [])
    .filter((event) => event && (event.training_relevant !== false || calendarMarkerKeys(event).length > 0));
  const specs = (Array.isArray(competitions) ? competitions : [])
    .filter((competition) => String(competition?.event_date || "").slice(0, 10) === dateKey)
    .map((competition) => ({
      kind: "competition",
      icon: "🏁",
      text: `${competition.priority || "B"}-Wettkampf: ${String(competition.name || "").trim() || "Wettkampf"}`,
    }));
  const dayStatus = plannedDayStatusLabel(context.day_status);
  if (dayStatus) specs.push({ kind: "day-status", icon: "", text: dayStatus });
  const markerKeys = new Set(appointments.concat([context]).flatMap((source) => calendarMarkerKeys(source)));
  const calendarParts = [
    ...appointments.map(plannedAppointmentLabel).filter(Boolean),
    ...CALENDAR_MARKERS.filter(({ key }) => markerKeys.has(key)).map(({ label }) => label),
  ];
  if (calendarParts.length) specs.push({ kind: "calendar", icon: "📅", text: calendarParts.join(" · ") });
  return specs;
}

function plannedAppointmentLabel(event) {
  if (!event || typeof event !== "object") return "";
  const name = stripCalendarMarkers(event.name) || "Trainingstermin";
  if (event.all_day) return `${name} · ganztägig`;
  const time = /(?:T|\s)(\d{2}:\d{2})/.exec(String(event.start_local || ""));
  return time ? `${name} · ${time[1]}` : name;
}

function calendarActualActivity(entry) {
  if (!entry || typeof entry !== "object") return null;
  if (entry.is_completed_activity) return entry;
  const actual = entry.compliance?.actual_activity;
  return actual && typeof actual === "object" ? actual : null;
}

// Canonical sports that normally record a distance; only these count as "ohne Distanz" when the distance is missing.
const DISTANCE_SPORTS = new Set(["ride", "run", "walk", "hike", "swim", "nordic_ski", "row"]);

function calendarMetricNumber(value, suffix = "") {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return `${AppFormat.number(number, { digits: Number.isInteger(number) ? 0 : 1 })}${suffix}`;
}

// DWD levels (0–3 index) or Open-Meteo/CAMS concentrations become one short pollen line.
function plannedPollenLabel(pollen) {
  if (!pollen || typeof pollen !== "object") return "";
  const source = pollen.source === "DWD" ? pollen.levels : pollen.concentrations;
  if (!source || typeof source !== "object") return "";
  const entries = Object.entries(source)
    .filter(([, value]) => value != null && String(value) !== "0" && String(value) !== "")
    .map(([name, value]) => `${name} ${value}`);
  return entries.length ? `Pollen: ${entries.join(", ")}` : "Pollen: keine Belastung";
}

// Highest pollen entry: DWD hazard levels such as "1-2" rank by their upper bound, CAMS concentrations by value.
function plannedPollenPeak(pollen) {
  if (!pollen || typeof pollen !== "object") return null;
  const dwd = pollen.source === "DWD";
  const source = dwd ? pollen.levels : pollen.concentrations;
  if (!source || typeof source !== "object") return null;
  let peak = null;
  for (const [name, value] of Object.entries(source)) {
    const rank = dwd ? Number(String(value).split(/[-–]/).pop()) : Number(value);
    if (Number.isFinite(rank) && (!peak || rank > peak.rank)) peak = { name, value, rank };
  }
  const minRank = dwd ? 1 : PLANNED_CAMS_POLLEN_FLAG_MIN;
  return peak && peak.rank >= minRank ? peak : null;
}

// Compact day-heading flags; an ordinary day yields none.
function plannedWeatherFlags(weather) {
  if (!weather || typeof weather !== "object") return [];
  const flags = [];
  const number = (value) => (value == null || value === "" ? Number.NaN : Number(value));
  const rain = number(weather.precipitation_probability_max);
  if (rain >= PLANNED_RAIN_FLAG_MIN_PERCENT) flags.push({ text: `💧 ${calendarMetricNumber(rain, " %")}`, label: `${calendarMetricNumber(rain)} Prozent Regenwahrscheinlichkeit` });
  const air = weather.air_quality && typeof weather.air_quality === "object" ? weather.air_quality : {};
  const uv = number(air.uv_index_max);
  if (uv >= PLANNED_UV_FLAG_MIN) flags.push({ text: `☀ UV ${calendarMetricNumber(uv)}`, label: `UV-Index ${calendarMetricNumber(uv)}` });
  const aqi = number(air.european_aqi_max);
  if (aqi >= PLANNED_AQI_FLAG_MIN) flags.push({ text: `AQI ${calendarMetricNumber(aqi)}`, label: `Luftqualität, Europäischer AQI ${calendarMetricNumber(aqi)}${air.european_aqi_category ? " (" + air.european_aqi_category + ")" : ""}` });
  const pollen = plannedPollenPeak(weather.pollen);
  if (pollen) flags.push({ text: `🌿 ${pollen.value}`, label: `Pollen: ${pollen.name} ${pollen.value}` });
  return flags;
}

// Every activity with a positive distance adds to the total; only distance sports without one count as missing.
function calendarWeekDistance(activities) {
  const measured = activities.filter((entry) => Number(entry.distance_m) > 0);
  const unmeasured = activities.filter((entry) => {
    const distance = Number(entry.distance_m);
    return distance <= 0 || Number.isNaN(distance);
  });
  const missing = unmeasured.filter((entry) => DISTANCE_SPORTS.has(String(entry.sport || "").toLowerCase())).length;
  if (!measured.length && !missing) return null;
  const total = measured.length
    ? AppFormat.distance(measured.reduce((sum, entry) => sum + Number(entry.distance_m), 0))
    : "–";
  return { value: total, note: missing ? `${countLabel(missing, "Aktivität", "Aktivitäten")} ohne Distanz` : null };
}

function countLabel(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}

// Load sums only the sessions that carry a value and names the rest; no value at all hides the cell.
function calendarWeekLoad(items) {
  const known = items.filter((item) => item.training_load != null && item.training_load !== "" && Number.isFinite(Number(item.training_load)));
  if (!known.length) return null;
  const missing = items.length - known.length;
  return {
    value: calendarMetricNumber(known.reduce((sum, item) => sum + Math.max(0, Number(item.training_load)), 0)),
    note: missing ? `${countLabel(missing, "Einheit", "Einheiten")} ohne Belastung` : null,
  };
}

// The week summary uses one duration format, hours and minutes.
function calendarHours(seconds) {
  const minutes = Math.round(Math.max(0, Number(seconds) || 0) / 60);
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")} h`;
}

const CALENDAR_SPORT_ICONS = { Radfahren: "🚴", "Rad indoor": "🚴", Laufen: "🏃", Schwimmen: "🏊", Kraft: "🏋" };

function calendarIntensityLabel(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return null;
  const percent = number > 0 && number <= 2 ? number * 100 : number;
  return `${Math.round(percent)} %`;
}

function calendarStartTime(value) {
  const match = /(?:T|\s)(\d{2}:\d{2})/.exec(String(value || ""));
  return match ? match[1] : null;
}

function plannedUnitStartTime(value) {
  // Date-only planned units are stored as midnight; that is not a start time.
  const time = calendarStartTime(value);
  return time === "00:00" ? null : time;
}

function appendCalendarFact(root, label, value) {
  if (value == null || value === "") return;
  const item = document.createElement("span");
  const title = document.createElement("strong");
  title.textContent = label;
  item.append(title, document.createTextNode(` ${value}`));
  root.append(item);
}

function calendarBadge({ kind, icon, text }) {
  const badge = document.createElement("span");
  badge.className = `planned-badge is-${kind}`;
  if (icon) {
    const glyph = document.createElement("span");
    glyph.setAttribute("aria-hidden", "true");
    glyph.textContent = icon;
    badge.append(glyph);
  }
  badge.append(document.createTextNode(text));
  return badge;
}

function calendarBadgeRow(specs) {
  const row = document.createElement("div");
  row.className = "planned-badges";
  row.append(...specs.map(calendarBadge));
  return row;
}

function competitionSportLabel(sport, environment) {
  if (sport === "ride" && environment === "virtual") return "Rad indoor";
  return ({ Cycling: "Radfahren", Ride: "Radfahren", ride: "Radfahren", VirtualRide: "Rad indoor", Running: "Laufen", Run: "Laufen", run: "Laufen", Swim: "Schwimmen", swim: "Schwimmen", Strength: "Krafttraining", strength: "Krafttraining", other: "Andere" })[sport] || sport || "–";
}

function competitionDate(competition, todayKey) {
  return AppFormat.relativeDay(competition.event_date, todayKey) !== null;
}

function competitionDistance(value) {
  if (value == null || String(value).trim() === "") return "Distanz unbekannt";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (numeric < 0) return "Distanz unbekannt";
  return numeric === 0 ? "0 km" : AppFormat.distance(numeric);
}

function competitionResult(result) {
  if (!result || typeof result !== "object") return null;
  const speed = Number(result.avg_speed_mps);
  const power = Number(result.avg_power);
  const hasSpeed = Number.isFinite(speed) && speed > 0;
  let effort = null;
  if (result.sport === "ride") {
    if (Number.isFinite(power) && power > 0) effort = `${Math.round(power)} W`;
    else if (hasSpeed) effort = `${AppFormat.number(speed * 3.6)} km/h`;
  } else if (hasSpeed) {
    effort = result.sport === "swim" ? `${AppFormat.clock(100 / speed)} /100 m` : `${AppFormat.clock(1000 / speed)} /km`;
  }
  const time = result.duration_s == null ? null : AppFormat.clock(result.duration_s);
  const value = [time, AppFormat.distance(result.distance_m), effort].filter(Boolean).join(" · ");
  if (!value) return null;
  return result.source ? `${value} (${result.source})` : value;
}

function competitionFact(labelText, value) {
  const item = document.createElement("div");
  const label = document.createElement("span");
  label.textContent = labelText;
  const content = document.createElement("strong");
  content.textContent = value || "–";
  item.append(label, content);
  return item;
}

function calendarEntryStatus(entry, dateKey, todayKey) {
  if (calendarActualActivity(entry)) return "completed";
  if (entry?.compliance?.status === "missed") return "missed";
  return dateKey === todayKey ? "today" : "planned";
}

function calendarStatusLabel(entry, dateKey, todayKey) {
  const status = calendarEntryStatus(entry, dateKey, todayKey);
  if (status === "completed") return entry.is_completed_activity ? "✓ Zusätzlich" : "✓ Absolviert";
  if (status === "missed") return "Nicht absolviert";
  return status === "today" ? "Heute geplant" : "Geplant";
}

function calendarRpeLabel(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 10 ? calendarMetricNumber(number) : null;
}

function appendPlannedExecution(cardSummary, entry, status) {
  if (status === "skipped") return;
  const percentage = calendarMetricNumber(entry.compliance?.percentage);
  const measurable = percentage != null && ["training_load", "duration", "strength_sets"].includes(entry.compliance?.basis);
  if (status !== "missed" && !measurable) return;
  const execution = document.createElement("span");
  const value = status === "missed" ? 0 : Number(entry.compliance.percentage);
  let executionState = "is-on-target";
  if (value < 80 || value > 120) executionState = "is-deviation";
  if (value === 0) executionState = "is-zero";
  execution.className = `planned-execution ${executionState}`;
  execution.textContent = `${value === 0 ? "✕" : "✓"} ${status === "missed" ? "0" : percentage} %`;
  const basis = { training_load: "Belastung", duration: "Dauer", strength_sets: "Sätze" }[entry.compliance?.basis];
  execution.title = basis ? `Ausführung gegenüber Plan (${basis})` : "Ausführung gegenüber Plan";
  execution.setAttribute("aria-label", [`${value} Prozent des Plans`, basis].filter(Boolean).join(" · "));
  cardSummary.append(execution);
  if (status !== "missed") {
    const meter = document.createElement("span");
    meter.className = "planned-execution-track";
    meter.setAttribute("aria-hidden", "true");
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, value))}%`;
    meter.append(fill);
    cardSummary.append(meter);
  }
}

function plannedDayNotes(dayContext, competitions, dateKey) {
  const notes = document.createElement("div");
  notes.className = "planned-day-notes";
  for (const { kind, icon, text } of plannedDayNoteSpecs(dayContext, competitions, dateKey)) {
    const note = document.createElement("p");
    note.className = `planned-day-context planned-day-${kind}`;
    if (icon) {
      const glyph = document.createElement("span");
      glyph.setAttribute("aria-hidden", "true");
      glyph.textContent = `${icon} `;
      note.append(glyph);
    }
    if (kind === "calendar") {
      const label = document.createElement("span");
      label.className = "sr-only";
      label.textContent = "Kalender: ";
      note.append(label);
    }
    note.append(document.createTextNode(text));
    notes.append(note);
  }
  const checkin = dayContext.checkin && typeof dayContext.checkin === "object" ? dayContext.checkin : {};
  const illness = String(checkin.illness || "").trim();
  const pain = String(checkin.pain || "").trim();
  if (illness || pain) {
    const healthNotice = document.createElement("p");
    healthNotice.className = "planned-day-context planned-day-health";
    healthNotice.textContent = [
      illness ? `Krankheit: ${illness}` : "",
      pain ? `Verletzung/Beschwerden: ${pain}` : "",
    ].filter(Boolean).join(" · ");
    notes.append(healthNotice);
  }
  return notes;
}

function plannedEntryDurationLabel(actual, entry) {
  if (actual) return AppFormat.duration(actual.moving_duration_s ?? actual.elapsed_duration_s);
  if (entry.duration_minutes) return AppFormat.duration(Number(entry.duration_minutes) * 60);
  return AppFormat.duration(entry.planned_duration_s);
}

// The planned name with its category when they differ, else the category.
function plannedStrengthName(exercise) {
  const category = AppFormat.strengthCategory(exercise.category);
  const planned = typeof exercise.name === "string" && exercise.name ? exercise.name : null;
  if (!planned) return category || "Übung";
  return category && category !== planned ? `${planned} (${category})` : planned;
}

function plannedStrengthRows(strength) {
  if (!strength?.exercises?.length) return null;
  const list = document.createElement("ul");
  list.className = "planned-strength";
  strength.exercises.forEach((exercise) => {
    const load = exercise.planned_kg == null ? "" : ` @ ${calendarMetricNumber(exercise.planned_kg)} kg`;
    const plan = `${exercise.planned_sets}×${exercise.planned_reps}${load}`;
    const item = document.createElement("li");
    const name = plannedStrengthName(exercise);
    item.textContent = exercise.status === "matched"
      ? `${name}: ${exercise.completed_sets}/${exercise.planned_sets} Sätze erreicht · Ist ${(exercise.reps || []).map((reps) => reps ?? "?").join("/") || "–"} Wdh. · Plan ${plan}`
      : `${name}: nicht zugeordnet · Plan ${plan}`;
    list.append(item);
  });
  return list;
}

function appendPlannedCalendarComparison(details, entry, actual) {
  if (!actual || entry.is_completed_activity) return;
  const comparison = document.createElement("div");
  comparison.className = "planned-comparison";
  const plannedDuration = entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.planned_duration_s;
  const planLine = document.createElement("p");
  planLine.textContent = `Plan: ${[
    entry.name,
    AppFormat.duration(plannedDuration),
    entry.training_load != null ? `Belastung ${calendarMetricNumber(entry.training_load)}` : null,
  ].filter(Boolean).join(" · ")}`;
  const actualLine = document.createElement("p");
  actualLine.textContent = `Ist: ${[
    AppFormat.duration(actual.moving_duration_s ?? actual.elapsed_duration_s),
    actual.training_load != null ? `Belastung ${calendarMetricNumber(actual.training_load)}` : null,
  ].filter(Boolean).join(" · ")}`;
  comparison.append(planLine, actualLine);
  if (entry.compliance?.percentage != null) {
    const ratio = document.createElement("p");
    const ratioLabel = { training_load: "Belastung", strength_sets: "Sätze" }[entry.compliance.basis] || "Umfang";
    ratio.textContent = `${ratioLabel} Plan/Ist: ${entry.compliance.percentage} %`;
    comparison.append(ratio);
  }
  const strengthRows = plannedStrengthRows(entry.compliance?.strength_sets);
  if (strengthRows) comparison.append(strengthRows);
  details.append(comparison);
}

// "Zusätzlich" only means something next to a plan, so an extra activity in a week without one shows no status.
function appendPlannedEntryStatus(cardSummary, entry, status, restDayLabel, dateKey, todayKey, weekHasPlan) {
  if (status === "planned" || status === "today") return;
  if (entry.is_completed_activity && !weekHasPlan) return;
  if (cardSummary.textContent) cardSummary.append(" · ");
  const statusText = document.createElement("span");
  statusText.className = "planned-entry-status";
  statusText.textContent = status === "skipped" ? `Entfallen (${restDayLabel})` : calendarStatusLabel(entry, dateKey, todayKey);
  cardSummary.append(statusText);
}

function appendPlannedTarget(cardSummary, entry) {
  const target = document.createElement("span");
  target.className = "planned-session-target";
  const targetParts = [entry.name || "Training", plannedEntryDurationLabel(null, entry)];
  if (entry.training_load != null) targetParts.push(`Belastung ${calendarMetricNumber(entry.training_load)}`);
  target.textContent = `Plan: ${targetParts.join(" · ")}`;
  cardSummary.append(target);
}

function adaptiveForecastNote(forecast, formatTime) {
  if (!forecast?.fetched_at) return "";
  return `Wetterprognose Stand ${formatTime(forecast.fetched_at)}${forecast.stale ? " (veraltet)" : ""}`;
}

function adaptiveIllnessPending(data, preview) {
  const illness = String(data.local_feedback?.today?.illness || "").trim();
  const previewIllness = String(preview?.illness_pause?.illness || "").trim();
  const needsForecast = Boolean(illness && (!preview?.illness_pause || previewIllness !== illness || !preview.illness_pause?.approved));
  const pendingPause = Boolean(preview?.status === "preview" && preview?.illness_pause && !preview.illness_pause.approved);
  return needsForecast || pendingPause;
}

function adaptiveCaption(illnessPending, count, returnPending = false) {
  if (illnessPending) return "Krankheit gemeldet: Sportpause prognostizieren und bestätigen.";
  if (returnPending && !count) return "Rückkehr nach Krankheit: nächste Stufe bestätigen.";
  if (count === 1) return "Ein zukünftiger Entwurf braucht eine Anpassung.";
  return `${count} zukünftige Entwürfe brauchen eine Anpassung.`;
}

// Completed activities carry a canonical sport and environment; planned units keep their type.
function calendarSportType(item) {
  if (!item || item.type || !item.sport) return item;
  const indoor = item.sport === "ride" && ["indoor", "virtual"].includes(item.environment);
  return { type: indoor ? "VirtualRide" : item.sport };
}

const FOCUS_LABELS = {
  recovery: "Regeneration", easy: "Locker", endurance: "Grundlage", long: "Lang", tempo: "Tempo", threshold: "Schwelle", sweet_spot: "Sweet Spot",
  vo2max: "VO2max", anaerobic: "Anaerob", race: "Wettkampf", test: "Test",
  legs: "Beine", upper: "Oberkörper", full_body: "Ganzkörper", core: "Rumpf", plyometrics: "Sprungkraft", mobility: "Mobilität",
};
const STRENGTH_INTENSITY_LABELS = { light: "Leicht", moderate: "Mittel", heavy: "Schwer" };
const FOCUS_OPTIONS = {
  run: ["recovery", "easy", "endurance", "long", "tempo", "threshold", "vo2max", "anaerobic", "race", "test"],
  ride: ["recovery", "easy", "endurance", "long", "tempo", "threshold", "sweet_spot", "vo2max", "anaerobic", "race", "test"],
  strength: ["legs", "upper", "full_body", "core", "plyometrics", "mobility"],
};

function focusSport(entry) {
  const sport = String(entry?.sport || "").toLowerCase();
  return FOCUS_OPTIONS[sport] ? sport : null;
}

function focusChipSpec(entry) {
  const label = FOCUS_LABELS[entry?.session_focus];
  if (!label) return null;
  const intensityLabel = STRENGTH_INTENSITY_LABELS[entry.strength_intensity];
  const intensity = intensityLabel && entry.intensity_origin === "derived" ? `≈${intensityLabel}` : intensityLabel;
  const derived = entry.focus_origin === "derived";
  return { kind: derived ? "focus-derived" : "focus", text: [derived ? "≈" : null, label, intensity].filter(Boolean).join(" "), derived };
}

const HR_CAP_SOURCE_LABELS = { default: "Standard", measured: "gemessen", estimated: "geschätzt" };

function hrCapChipSpec(entry) {
  const percent = Number(entry?.hr_cap?.percent_lthr);
  const source = HR_CAP_SOURCE_LABELS[entry?.hr_cap?.source];
  if (!Number.isFinite(percent) || !source) return null;
  const high = entry?.hr_cap_bpm?.high;
  const bpm = typeof high === "number" ? high : Number.NaN;
  const parts = [`≤ ${percent} % LSHF`, Number.isFinite(bpm) ? `${bpm} bpm` : null, source];
  return { kind: "focus", text: parts.filter(Boolean).join(" · "), derived: false };
}

function appendFocusChip(root, entry) {
  const chip = focusChipSpec(entry);
  const cap = hrCapChipSpec(entry);
  if (!chip && !cap) return;
  const row = calendarBadgeRow([chip, cap].filter(Boolean));
  row.dataset.focusChip = chip?.derived ? "derived" : "set";
  if (chip?.derived) row.firstElementChild.setAttribute("aria-label", `${chip.text} (abgeleitet)`);
  root.append(row);
}

// A unit is identified by its local id, else by provider id and day; the open
// cards and the "Gespeichert" status survive the re-render of a calendar reload.
function plannedEntryKey(entry, dateKey) {
  if (entry?.local_id) return `local:${entry.local_id}`;
  const id = entry?.id ?? entry?.activity_id;
  return id ? `id:${id}@${dateKey}` : "";
}

let openPlannedEntries = new Set();
const plannedFocusStatuses = new Map();

// The summary chip follows the saved focus without waiting for the next reload.
function refreshFocusChip(card, entry) {
  const holder = document.createElement("span");
  appendFocusChip(holder, entry);
  const row = card.querySelector("summary [data-focus-chip]");
  if (row) row.replaceWith(...holder.childNodes);
  else card.querySelector("summary .planned-session-line")?.append(...holder.childNodes);
}

function focusSelect(label, name, options, selected) {
  const field = document.createElement("label");
  field.className = "planned-focus-field";
  field.append(document.createTextNode(label));
  const select = document.createElement("select");
  select.name = name;
  for (const [value, text] of [["", "–"], ...options]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    option.selected = value === (selected || "");
    select.append(option);
  }
  field.append(select);
  return { field, select };
}

function plannedSessionMetrics(entry, actual) {
  const displayed = actual || entry;
  const metrics = document.createElement("span");
  metrics.className = "planned-session-metrics";
  metrics.textContent = [
    actual ? calendarMetricNumber(actual.avg_hr, " bpm") : null,
    actual ? calendarMetricNumber(actual.avg_power, " W") : null,
    calendarMetricNumber(displayed.training_load) != null ? `Belastung ${calendarMetricNumber(displayed.training_load)}` : null,
  ].filter(Boolean).join(" · ");
  return metrics.textContent ? metrics : null;
}

function profileSegmentExtent(item, axis) {
  return Number.isFinite(item[axis]) && item[axis] > 0 ? item[axis] : 0;
}

function profileExtent(profile) {
  const axis = profile.axis === "distance" ? "distance" : "duration";
  return profile.segments.reduce((sum, item) => sum + profileSegmentExtent(item, axis), 0);
}

// The open card whose body is shown: not inside a collapsed group.
function shownPlannedEntry(root) {
  return [...(root?.querySelectorAll(".planned-entry[open]") || [])].find((card) => !card.parentElement.closest("details:not([open])")) || null;
}

// The detail pane's status: as on the card, but always named.
function plannedDetailStatus(entry, dateKey, todayKey, restDayLabel, weekHasPlan) {
  if (restDayLabel) return `Entfallen (${restDayLabel})`;
  if (entry.is_completed_activity && !weekHasPlan) return "✓ Absolviert";
  return calendarStatusLabel(entry, dateKey, todayKey);
}

const DETAIL_DATE_FORMAT = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "2-digit", month: "2-digit" });

// Extra activities that look the same (title, sport, duration, distance, no profile) collapse into one row.
function plannedEntryGroups(dayEntries) {
  const groups = [];
  for (const entry of dayEntries) {
    const key = entry.is_completed_activity && !entry.workout_profile
      ? JSON.stringify([entry.name || "", entry.type || entry.sport || "", entry.environment || "", entry.moving_duration_s ?? entry.elapsed_duration_s ?? null, Number(entry.distance_m) > 0 ? Number(entry.distance_m) : null])
      : null;
    const previous = groups.at(-1);
    if (key && previous?.key === key) previous.entries.push(entry);
    else groups.push({ key, entries: [entry] });
  }
  return groups;
}

function appendWeekMetricCell(grid, cell) {
  const value = document.createElement("strong");
  value.textContent = cell?.value ?? "–";
  if (cell?.note) {
    const note = document.createElement("small");
    note.textContent = cell.note;
    value.append(note);
  }
  grid.append(value);
}

function plannedZoneLegend(days) {
  const zones = [...new Set([...days.querySelectorAll(".calendar-workout-profile [data-zone]")].map((node) => node.dataset.zone))]
    .filter((zone) => zone !== "unknown")
    .sort((left, right) => Number(left) - Number(right));
  if (!zones.length) return null;
  const legend = document.createElement("p");
  legend.className = "planned-zone-legend";
  for (const zone of zones) {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.dataset.zone = zone;
    swatch.setAttribute("aria-hidden", "true");
    item.append(swatch, document.createTextNode(`Z${zone}`));
    legend.append(item);
  }
  return legend;
}

// Fixed grid with one column each for planned and completed values; a row appears only when it has a value.
function plannedWeekMetrics(planned, actual) {
  const columns = [planned.length ? "planned" : null, actual.length ? "actual" : null].filter(Boolean);
  if (!columns.length) return null;
  const totals = document.createElement("span");
  totals.className = "planned-week-metrics";
  totals.dataset.columns = String(columns.length);
  const plannedSeconds = planned.reduce((total, entry) => total + Math.max(0, Number(entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.planned_duration_s) || 0), 0);
  const actualSeconds = actual.reduce((total, entry) => total + Math.max(0, Number(entry.moving_duration_s ?? entry.elapsed_duration_s) || 0), 0);
  const plannedDistance = planned.reduce((total, entry) => total + Math.max(0, Number(entry.distance) || 0), 0);
  const rows = [
    ["Dauer", { planned: plannedSeconds > 0 ? { value: calendarHours(plannedSeconds) } : null, actual: { value: calendarHours(actualSeconds) } }],
    ["Distanz", { planned: plannedDistance > 0 ? { value: AppFormat.distance(plannedDistance) } : null, actual: calendarWeekDistance(actual) }],
    ["Belastung", { planned: calendarWeekLoad(planned), actual: calendarWeekLoad(actual) }],
  ];
  totals.append(document.createElement("span"));
  for (const column of columns) {
    const label = document.createElement("span");
    label.className = "planned-week-column";
    label.textContent = column === "planned" ? "Geplant" : "Absolviert";
    totals.append(label);
  }
  for (const [label, cells] of rows) {
    if (!columns.some((column) => cells[column])) continue;
    const name = document.createElement("span");
    name.textContent = label;
    totals.append(name);
    for (const column of columns) appendWeekMetricCell(totals, cells[column]);
  }
  return totals.childElementCount > columns.length + 1 ? totals : null;
}

function create({ $, state, dateLabel, formatTime, formatDuration, formatPace, formatWhole, distanceLabel, activitySportLabel, analysisSvg, api, showAccessibleDialog, appendHistoryPageButton, AppRouter, dateFromKey, localDateKey, addDateKey, weatherNumber, weatherIconFor, weatherDirection, plannedEventDate, timezoneDateKey, calendarDisplayValue }) {
  // The lists are re-rendered as a whole; only the outcome of a user action is announced.
  function announcePlanChange(message) {
    const region = $("#planListStatus");
    if (region) region.textContent = message;
  }

  function renderAdaptivePlanning(data) {
    const planning = data.planning || {};
    const preview = planning.latest_replan;
    const changes = Array.isArray(preview?.changes) ? preview.changes : [];
    const illnessPending = adaptiveIllnessPending(data, preview);
    const required = Boolean(planning.needs_replan || illnessPending);
    const caption = adaptiveCaption(illnessPending, Number(planning.replan_changes || changes.length), Boolean(planning.illness_return_pending));
    const weatherChanged = changes.some((change) => Array.isArray(change?.blocking_triggers) && change.blocking_triggers.includes("weather"));
    const forecastNote = weatherChanged ? adaptiveForecastNote(preview?.weather_forecast, formatTime) : "";
    const coachNotice = $("#coachAdaptivePlanningNotice");
    if (coachNotice) {
      coachNotice.hidden = !required;
      const detail = coachNotice.querySelector("small");
      if (detail) detail.textContent = required ? [caption, forecastNote ? `${forecastNote}.` : "", "Bitte den Coach um die Anpassung."].filter(Boolean).join(" ") : "";
    }
  }

  function renderExternalCalendar(data) {
    const calendar = data.external_calendar || {};
    const syncButton = $("#externalCalendarSyncButton");
    setConnectionChip("#externalCalendarConnectionStatus", connectionKind({ configured: calendar.configured, error: Boolean(calendar.last_error) }));
    const detail = $("#externalCalendarConnectionDetail");
    if (detail) detail.textContent = externalCalendarDetail(calendar);
    if (syncButton) {
      syncButton.disabled = Boolean(calendar.running || state.localSync.externalCalendar);
      syncButton.textContent = calendar.running || state.localSync.externalCalendar ? "Synchronisierung läuft…" : "Synchronisieren";
    }
  }


  function planWeekStart(dateKey) {
    const value = dateFromKey(dateKey);
    if (Number.isNaN(value.valueOf())) return "";
    const weekday = value.getDay();
    value.setDate(value.getDate() - (weekday === 0 ? 6 : weekday - 1));
    return localDateKey(value);
  }

  function planWeekLabel(weekStartKey) {
    const start = dateFromKey(weekStartKey);
    const end = dateFromKey(addDateKey(weekStartKey, 6));
    if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf())) return weekStartKey;
    const startLabel = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit" }).format(start);
    const endLabel = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" }).format(end);
    return `${startLabel} – ${endLabel}`;
  }

  function plannedWeatherLabel(weather) {
    if (!weather || typeof weather !== "object") return "";
    const hasForecast = weather.condition || weather.weather_code != null
      || weather.temperature_min != null || weather.temperature_max != null;
    if (!hasForecast) return "";
    const temperatures = [weather.temperature_min, weather.temperature_max]
      .filter((value) => value != null && value !== "" && Number.isFinite(Number(value)))
      .map((value) => weatherNumber(value, "°"));
    return [weatherIconFor(weather), temperatures.join(" / ")].filter(Boolean).join(" ");
  }

  // Rain, wind and air details stay out of the day card; they are the tooltip/accessible name of the small weather symbol.
  function plannedWeatherDetails(weather) {
    const directionValue = calendarMetricNumber(weather.wind_direction_dominant);
    const direction = directionValue != null && Number(weather.wind_direction_dominant) >= 0 && Number(weather.wind_direction_dominant) <= 360
      ? weatherDirection(weather.wind_direction_dominant) : "";
    const peakTime = /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(weather.rain_peak_time || "") ? weather.rain_peak_time : "";
    const values = [
      calendarMetricNumber(weather.precipitation_probability_max, ` % Regen${peakTime ? " (max. " + peakTime + " Uhr)" : ""}`),
      calendarMetricNumber(weather.wind_speed_max, ` km/h Wind${direction ? " " + direction : ""}`),
      calendarMetricNumber(weather.wind_gusts_max, " km/h Böen"),
    ].filter(Boolean);
    if (peakTime && weather.precipitation_probability_max == null) values.unshift(`Regen am ehesten ${peakTime} Uhr`);
    return [
      weather.archived_forecast ? "Gespeicherte Wettervorhersage" : "Wettervorhersage",
      weather.condition,
      values.join(" · "),
      plannedAirValues(weather).join(" · "),
    ].filter(Boolean);
  }

  function plannedWeatherHint() {
    const hint = document.createElement("p");
    hint.className = "planned-weather-hint";
    hint.textContent = state.data?.weather?.configured
      ? "Für die kommenden Tage liegt noch keine Wettervorhersage vor."
      : "Wetter fehlt: Im Profil ist kein Wetterort hinterlegt.";
    return hint;
  }

  function plannedWeekSummary(weekKey, weekEndKey, weekEntries, compliance, todayKey) {
    const plannedEntryCount = weekEntries.filter((entry) => !entry.is_completed_activity).length;
    const plannedUnits = Number.isFinite(Number(compliance?.planned_units))
      ? Number(compliance.planned_units)
      : plannedEntryCount;
    const completedUnits = Number.isFinite(Number(compliance?.completed_units))
      ? Number(compliance.completed_units)
      : 0;
    const isPast = weekEndKey < todayKey;
    const units = isPast || completedUnits > 0
      ? `${plannedUnits} geplant · ${completedUnits} absolviert`
      : `${plannedUnits} geplant`;
    if (compliance?.basis !== "training_load" || compliance.planned_value == null) return units;
    const load = [`Belastung geplant ${formatWhole(compliance.planned_value)}`];
    if (isPast || completedUnits > 0) load.push(`absolviert ${formatWhole(compliance.actual_value || 0)}`);
    return `${units} · ${load.join(" · ")}`;
  }

  function calendarPaceLabel(activity) {
    if (activitySportLabel(calendarSportType(activity)) !== "Laufen") return null;
    const duration = Number(activity?.moving_duration_s);
    const distance = Number(activity?.distance_m);
    return duration > 0 && distance > 0 ? formatPace(duration / (distance / 1000)) : null;
  }

  function calendarCountLabel(entries, todayKey) {
    const counts = { completed: 0, planned: 0, missed: 0 };
    entries.forEach((entry) => {
      const status = calendarEntryStatus(entry, plannedEventDate(entry), todayKey);
      if (status === "completed") counts.completed += 1;
      else if (status === "missed") counts.missed += 1;
      else counts.planned += 1;
    });
    return [
      counts.completed ? `${counts.completed} abgeschlossen` : "",
      counts.planned ? `${counts.planned} geplant` : "",
      counts.missed ? `${counts.missed} nicht absolviert` : "",
    ].filter(Boolean).join(" · ");
  }

  // Entering the calendar shows the current week in the week view and scrolls to today.
  function focusPlannedToday() {
    if (!state.plannedTodayFocusPending || !state.loadedAreas.has("plan")) return false;
    if (AppRouter.baseRoute(state.route) !== "plan" || AppRouter.planSegmentFromRoute(state.route) !== "overview") return false;
    const currentWeekKey = planWeekStart(timezoneDateKey(state.data?.profile?.timezone, new Date()));
    if (selectedWeekKey !== currentWeekKey || calendarView !== "week") {
      selectedWeekKey = currentWeekKey;
      calendarView = "week";
      selectedDayKey = "";
      renderPlanned(renderedCalendar);
    }
    const today = $("#plannedCalendar")?.querySelector(".planned-day.is-today");
    if (!today) return false;
    state.plannedTodayFocusPending = false;
    today.scrollIntoView({ block: "start", behavior: "auto" });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (AppRouter.baseRoute(state.route) === "plan" && today.isConnected) today.scrollIntoView({ block: "start", behavior: "auto" });
    }));
    return true;
  }

  function appendActualCalendarDetails(details, actual) {
    if (!actual) return;
    const primaryMetrics = document.createElement("span");
    primaryMetrics.className = "planned-actual-summary";
    const load = calendarMetricNumber(actual.training_load);
    const rpe = calendarRpeLabel(actual.rpe);
    primaryMetrics.textContent = [load != null ? `Belastung ${load}` : null, rpe != null ? `RPE ${rpe}/10` : "RPE offen"].filter(Boolean).join(" · ");
    const facts = document.createElement("div");
    facts.className = "planned-actual-facts";
    appendCalendarFact(facts, "Dauer", AppFormat.duration(actual.moving_duration_s ?? actual.elapsed_duration_s));
    appendCalendarFact(facts, "Distanz", distanceLabel(actual.distance_m));
    appendCalendarFact(facts, "Trainingsload", calendarMetricNumber(actual.training_load));
    appendCalendarFact(facts, "RPE", rpe != null ? `${rpe}/10` : "nicht angegeben");
    appendCalendarFact(facts, "Intensität", calendarIntensityLabel(actual.intensity));
    appendCalendarFact(facts, "Ø Puls", calendarMetricNumber(actual.avg_hr, " bpm"));
    appendCalendarFact(facts, "Ø Leistung", calendarMetricNumber(actual.avg_power, " W"));
    appendCalendarFact(facts, "Pace", calendarPaceLabel(actual));
    appendCalendarFact(facts, "Höhenmeter", calendarMetricNumber(actual.elevation_gain_m, " hm"));
    details.append(primaryMetrics, facts);
  }

  // One compact row: sport icon, title, sport/time/status line, duration and distance.
  function plannedSessionHeader(entry, actual, title, appendStatus) {
    const displayed = actual || entry;
    const sportLabel = activitySportLabel(calendarSportType(displayed));
    const header = document.createElement("span");
    header.className = "planned-session-header";
    const icon = document.createElement("span");
    icon.className = "planned-session-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = CALENDAR_SPORT_ICONS[sportLabel] || "•";
    const cardTitle = document.createElement("strong");
    cardTitle.className = "planned-session-title";
    cardTitle.textContent = title;
    const line = document.createElement("span");
    line.className = "planned-session-line";
    line.textContent = [sportLabel, actual ? calendarStartTime(actual.started_at_local) : plannedUnitStartTime(entry.starts_at_local)].filter(Boolean).join(" · ");
    appendStatus(line);
    const value = document.createElement("span");
    value.className = "planned-session-value";
    const duration = document.createElement("strong");
    duration.textContent = plannedEntryDurationLabel(actual, entry) || "–";
    value.append(duration);
    const shownDistance = actual ? actual.distance_m : entry.distance;
    if (shownDistance > 0) {
      const distance = document.createElement("span");
      distance.textContent = distanceLabel(shownDistance);
      value.append(distance);
    }
    header.append(icon, cardTitle, line, value);
    return header;
  }

  function calendarWorkoutProfile(profile) {
    const segments = profile?.segments;
    if (!Array.isArray(segments) || !segments.length || segments.length > 1000) return null;
    const axis = profile.axis === "distance" ? "distance" : "duration";
    const extent = (item) => profileSegmentExtent(item, axis);
    const total = profileExtent(profile);
    const values = segments.flatMap((item) => [item.value, item.end_value]).filter((value) => value != null && Number.isFinite(value) && value >= 0);
    if (!total || !values.length) return null;
    const top = Math.max(...values, 1) * 1.1;
    const baseLabel = profile.source === "recorded" ? "Aufgezeichnetes Belastungsprofil" : "Geplantes Intervallprofil";
    const label = profile.estimated ? `${baseLabel} (Zonen geschätzt aus FTP oder Schwellenpuls (LSHF))` : baseLabel;
    const svg = analysisSvg("svg", { viewBox: "0 0 300 56", role: "img", "aria-label": label, class: "calendar-workout-profile", preserveAspectRatio: "none" });
    svg.append(analysisSvg("title", {}, `${label} · ${axis === "distance" ? "Distanzachse" : "Zeitachse"} · ${profile.unit || ""}`));
    svg.append(analysisSvg("line", { x1: 0, x2: 300, y1: 54, y2: 54, class: "calendar-profile-baseline" }));
    let offset = 0;
    for (const item of segments) {
      const size = extent(item);
      if (!size) continue;
      const x = offset / total * 300, width = size / total * 300;
      offset += size;
      const shape = calendarProfileShape(item, x, width, top);
      if (!shape) continue;
      shape.append(analysisSvg("title", {}, `${axis === "distance" ? distanceLabel(size) : formatDuration(size)} · ${item.label || ""}`));
      svg.append(shape);
    }
    return svg;
  }

  function calendarProfileShape(item, x, width, top) {
    if (item.value == null || item.end_value == null || !Number.isFinite(item.value) || !Number.isFinite(item.end_value)) return null;
    const left = 54 - Math.max(0, item.value) / top * 50;
    const right = 54 - Math.max(0, item.end_value) / top * 50;
    const zone = Number.isInteger(item.zone) && item.zone >= 1 && item.zone <= 7 ? item.zone : "unknown";
    // A hairline gap keeps neighbouring intervals apart without hiding a short one.
    const gap = Math.min(0.6, width / 4);
    const start = x + gap / 2, end = x + width - gap / 2;
    return analysisSvg("polygon", { points: `${start},54 ${start},${left} ${end},${right} ${end},54`, "data-zone": zone });
  }

  // The detail view's larger profile with its axis from start to the whole duration or distance.
  function plannedDetailProfile(profile) {
    const svg = calendarWorkoutProfile(profile);
    if (!svg) return null;
    svg.classList.add("is-detail");
    const total = profileExtent(profile);
    const axis = document.createElement("div");
    axis.className = "planned-detail-axis";
    axis.setAttribute("aria-hidden", "true");
    const end = profile.axis === "distance" ? distanceLabel(total) : AppFormat.duration(total);
    for (const text of ["0", end]) axis.append(Object.assign(document.createElement("span"), { textContent: text }));
    const figure = document.createElement("div");
    figure.className = "planned-detail-profile";
    figure.append(svg, axis);
    return figure;
  }

  // Title, day and status of the selected unit; on wide screens it heads the detail pane.
  function plannedDetailHead(entry, actual, title, dateKey, status, statusLabel, weather) {
    const head = document.createElement("div");
    head.className = "planned-detail-head";
    const name = document.createElement("strong");
    name.className = "planned-detail-title";
    name.textContent = title;
    const line = document.createElement("span");
    line.className = "planned-detail-line";
    line.textContent = [
      DETAIL_DATE_FORMAT.format(dateFromKey(dateKey)),
      actual ? calendarStartTime(actual.started_at_local) : plannedUnitStartTime(entry.starts_at_local),
      activitySportLabel(calendarSportType(actual || entry)),
      plannedWeatherLabel(weather),
    ].filter(Boolean).join(" · ");
    const pill = document.createElement("span");
    pill.className = `planned-detail-status is-${status}`;
    pill.textContent = statusLabel;
    head.append(name, line, pill);
    return head;
  }

  function plannedFocusForm(entry, dateKey) {
    const sport = focusSport(entry);
    if (!sport || !entry.local_id || entry.is_completed_activity) return null;
    const isSet = entry.focus_origin === "set";
    const form = document.createElement("div");
    form.className = "planned-focus-form";
    const focus = focusSelect("Art der Einheit", "session_focus", FOCUS_OPTIONS[sport].map((value) => [value, FOCUS_LABELS[value]]), isSet ? entry.session_focus : "");
    const parts = [focus];
    if (sport === "strength") parts.push(focusSelect("Intensität", "strength_intensity", Object.entries(STRENGTH_INTENSITY_LABELS), entry.intensity_origin === "set" ? entry.strength_intensity : ""));
    const status = document.createElement("span");
    status.className = "planned-focus-status";
    status.setAttribute("role", "status");
    const statusKey = plannedEntryKey(entry, dateKey);
    status.textContent = plannedFocusStatuses.get(statusKey) || "";
    const previous = parts.map((part) => part.select.value);
    const save = async () => {
      status.textContent = "";
      plannedFocusStatuses.delete(statusKey);
      try {
        const body = { session_focus: focus.select.value || null, strength_intensity: parts[1]?.select.value || null };
        await api(`/api/planned-units/${encodeURIComponent(entry.local_id)}/focus`, { method: "POST", body: JSON.stringify(body) });
        previous.splice(0, previous.length, ...parts.map((part) => part.select.value));
        status.textContent = "Gespeichert";
        if (statusKey) plannedFocusStatuses.set(statusKey, "Gespeichert");
        const card = form.closest(".planned-entry");
        if (card) {
          const saved = { ...entry, session_focus: focus.select.value || entry.session_focus, focus_origin: focus.select.value ? "set" : entry.focus_origin };
          if (parts[1]?.select.value) Object.assign(saved, { strength_intensity: parts[1].select.value, intensity_origin: "set" });
          refreshFocusChip(card, saved);
        }
        return true;
      } catch (error) {
        parts.forEach((part, index) => { part.select.value = previous[index]; });
        status.textContent = error.message;
        return false;
      }
    };
    for (const part of parts) part.select.addEventListener("change", save);
    form.append(...parts.map((part) => part.field), status);
    // A derived value is offered next to its empty field; one tap sets it.
    const derived = [
      [focus, entry.focus_origin === "derived" ? entry.session_focus : "", FOCUS_LABELS],
      [parts[1], entry.intensity_origin === "derived" ? entry.strength_intensity : "", STRENGTH_INTENSITY_LABELS],
    ];
    for (const [part, value, labels] of derived) {
      if (!part || !value || !labels[value]) continue;
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "planned-suggestion-chip";
      chip.textContent = `≈ ${labels[value]} übernehmen`;
      chip.addEventListener("click", async () => {
        part.select.value = value;
        if (await save()) chip.remove();
      });
      part.field.after(chip);
    }
    return form;
  }

  // Leftovers of every provider, deduplicated, keyed by the week whose button removes them.
  function plannedLeftoversByWeek(trainingCalendar, currentWeekKey, lastWeekKey) {
    const byWeek = new Map();
    for (const [provider, item] of plannedLeftoverItems(trainingCalendar)) {
      const week = plannedLeftoverWeek(item, currentWeekKey, lastWeekKey, planWeekStart);
      const lists = byWeek.get(week) || {};
      lists[provider] = [...(lists[provider] || []), item];
      byWeek.set(week, lists);
    }
    return byWeek;
  }

  // Each configured provider's leftovers once, as [provider, item] pairs.
  function plannedLeftoverItems(trainingCalendar) {
    const ids = providerIds();
    const configured = plannedProviderConfiguration();
    const providers = new Set([ids.garmin, ids.intervals, ids.wahoo].filter((provider) => configured[provider] === true));
    const found = new Map();
    for (const entry of Array.isArray(trainingCalendar) ? trainingCalendar : []) {
      for (const [provider, items] of Object.entries(entry?.push_cleanup || {})) {
        if (!providers.has(provider) || !Array.isArray(items)) continue;
        for (const item of items) if (item?.id) found.set(provider + ":" + item.id, [provider, item]);
      }
    }
    return [...found.values()];
  }

  function plannedProviderConfiguration() {
    const ids = providerIds();
    return { [ids.intervals]: Boolean(state.data?.configured?.[ids.intervals]), [ids.garmin]: Boolean(state.data?.garmin?.configured), [ids.wahoo]: Boolean(state.data?.wahoo?.connected) };
  }

  // The week's sync jobs from its calendar entries and leftovers; none when nothing waits. Each job
  // carries the hashes the units were shown with, so a unit edited meanwhile is refused instead of sent.
  function plannedWeekJobs(weekEntries, leftovers, todayKey) {
    const units = weekEntries
      .filter((entry) => !entry.is_completed_activity)
      .map((entry) => ({ entry, dateKey: plannedEventDate(entry), completed: Boolean(calendarActualActivity(entry)) }));
    return plannedWeekSyncJobs(units, leftovers || {}, todayKey, plannedProviderConfiguration(), providerIds());
  }

  // One button per week: it sends every unit of the week a provider still waits for and removes
  // what the app left there for that week; its tooltip names what it removes.
  function plannedWeekSyncButton(weekKey, weekEntries, leftovers, todayKey) {
    const ids = providerIds();
    const jobs = plannedWeekJobs(weekEntries, leftovers, todayKey);
    if (!jobs.length) return null;
    state.plannedSyncInFlight ||= new Set();
    const key = "week:" + weekKey;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button planned-sync-button planned-week-sync-button";
    button.textContent = "Woche synchronisieren";
    button.setAttribute("aria-label", `Woche ${planWeekLabel(weekKey)} synchronisieren`);
    const removed = jobs.flatMap((job) => job.items).map((item) => [item.name, item.date ? dateLabel(item.date) : ""].filter(Boolean).join(" "));
    if (removed.length) button.title = `Wird entfernt: ${removed.join(", ")}`;
    button.disabled = state.plannedSyncInFlight.has(key);
    button.addEventListener("click", async () => {
      if (state.plannedSyncInFlight.has(key)) return;
      state.plannedSyncInFlight.add(key);
      button.disabled = true;
      button.classList.add("busy");
      const outcome = await runPlannedWeekSync(jobs, ids, coachProviderLabel);
      state.plannedSyncInFlight.delete(key);
      globalThis.toast?.(outcome.message, outcome.failed);
      button.disabled = false;
      button.classList.remove("busy");
      await globalThis.load?.();
    });
    return button;
  }

  // One conflict component per planned session; its single action hands the conflict to the Coach.
  function plannedConflict(entry, dateKey) {
    const labels = plannedConflictLabels(entry.conflicts);
    if (!labels.length) return null;
    const conflict = document.createElement("span");
    conflict.className = "planned-conflict";
    const text = document.createElement("span");
    text.textContent = `⚠ Konflikt: ${labels.join(" · ")}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button planned-conflict-button";
    button.textContent = "Mit Coach lösen";
    button.addEventListener("click", (event) => {
      // The button sits in the card summary; a click must not toggle the card.
      event.preventDefault();
      event.stopPropagation();
      const session = [activitySportLabel(calendarSportType(entry)), plannedEntryDurationLabel(null, entry)].filter(Boolean).join(", ");
      void globalThis.askCoach?.(`Die geplante Einheit am ${dateLabel(dateKey)} (${session}) kollidiert mit: ${labels.join(", ")}. Schlage eine Anpassung vor.`);
    });
    conflict.append(text, button);
    return conflict;
  }

  // Why a strength unit cannot reach the watch, with the action that fixes it:
  // the Coach structures a free-text unit; an unmatched exercise takes one of
  // the catalogue suggestions or goes to the Coach.
  function plannedGarminBlocked(entry, dateKey, todayKey, actual) {
    const reason = entry.push_blocked?.[providerIds().garmin];
    // A unit in a sync conflict shows only its conflict; that decision comes first.
    if (!reason || actual || dateKey < todayKey || !entry.local_id || entry.is_completed_activity || entry.sync_status === "conflict") return null;
    const block = document.createElement("span");
    block.className = "planned-conflict planned-garmin-blocked";
    const unit = `„${entry.name || "Krafteinheit"}“ am ${dateLabel(dateKey)}`;
    if (reason !== "unmapped") {
      const text = document.createElement("span");
      text.textContent = plannedGarminBlockedText(entry);
      block.append(text, plannedCoachButton("Mit Coach strukturieren", `Strukturiere die Krafteinheit ${unit} für die Uhr: Übungen in Reihenfolge mit Sätzen, Wiederholungen, Last und Garmin-Übung. Frag nach, was fehlt.`));
      return block;
    }
    const unmapped = Array.isArray(entry.push_unmapped) ? entry.push_unmapped : [];
    block.append(...unmapped.map((exercise) => plannedUnmappedExercise(entry, exercise, unit)));
    return block.childElementCount ? block : null;
  }

  // One unmatched exercise: its catalogue suggestions, each a one-tap pick
  // that is remembered for the exercise name, and "Andere…" for the Coach.
  function plannedUnmappedExercise(entry, exercise, unit) {
    const row = document.createElement("span");
    row.className = "planned-garmin-exercise";
    const text = document.createElement("span");
    text.textContent = `Keine Garmin-Übung: ${exercise.name}`;
    row.append(text);
    for (const suggestion of Array.isArray(exercise.suggestions) ? exercise.suggestions : []) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "planned-suggestion-chip";
      chip.textContent = suggestion;
      chip.addEventListener("click", async (event) => {
        stopSummaryToggle(event);
        chip.disabled = true;
        try {
          await api(`/api/planned-units/${encodeURIComponent(entry.local_id)}/garmin-exercise`, { method: "POST", body: JSON.stringify({ exercise_index: exercise.index, garmin_exercise: suggestion, expected_payload_hash: entry.payload_hash }) });
          await globalThis.load?.();
          announcePlanChange(`Garmin-Übung „${suggestion}“ zugeordnet`);
        } catch (error) {
          chip.disabled = false;
          globalThis.toast?.(error.message, true);
        }
      });
      row.append(chip);
    }
    row.append(plannedCoachButton("Andere…", `Ordne in der Krafteinheit ${unit} der Übung „${exercise.name}“ die passende Garmin-Übung zu. Frag mich mit Vorschlägen aus dem Katalog.`));
    return row;
  }

  function plannedActivityButton(actual) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button";
    button.textContent = "Aktivität analysieren";
    button.addEventListener("click", () => globalThis.ActivityDetails.open(actual, { api, showDialog: showAccessibleDialog }));
    return button;
  }

  function renderPlannedEntry(entry, dateKey, todayKey, dayContext = {}, weekHasPlan = true) {
    const actual = calendarActualActivity(entry);
    const baseStatus = calendarEntryStatus(entry, dateKey, todayKey);
    const restDayLabel = baseStatus === "missed" ? plannedDayStatusLabel(dayContext.day_status) : null;
    const status = restDayLabel ? "skipped" : baseStatus;
    const card = document.createElement("details");
    card.className = `planned-entry is-${status}`;
    // One open card at a time: on wide screens its body is the detail pane beside the week.
    card.name = "planned-entry";
    const entryKey = plannedEntryKey(entry, dateKey);
    if (entryKey) card.dataset.entryKey = entryKey;
    card.open = openPlannedEntries.has(entryKey);
    const cardSummary = document.createElement("summary");
    const meta = document.createElement("span");
    meta.className = "planned-meta";
    const displayed = actual || entry;
    card.dataset.sport = activitySportLabel(calendarSportType(displayed));
    meta.textContent = [
      activitySportLabel(calendarSportType(displayed)),
      actual ? calendarStartTime(actual.started_at_local) : plannedUnitStartTime(entry.starts_at_local),
      plannedEntryDurationLabel(actual, entry),
    ].filter(Boolean).join(" · ");
    const title = actual?.name || entry.name || "Trainingseinheit";
    // The sport line carries the chips and, only for a unit still to send, a compact sync button.
    cardSummary.append(plannedSessionHeader(entry, actual, title, (line) => {
      appendPlannedEntryStatus(line, entry, status, restDayLabel, dateKey, todayKey, weekHasPlan);
      appendFocusChip(line, entry);
    }), meta);
    appendPlannedExecution(cardSummary, entry, status);
    const profile = calendarWorkoutProfile(actual?.workout_profile || entry.workout_profile);
    if (profile) cardSummary.append(profile);
    const conflict = plannedConflict(entry, dateKey);
    if (conflict) cardSummary.append(conflict);
    const garminBlocked = plannedGarminBlocked(entry, dateKey, todayKey, actual);
    if (garminBlocked) cardSummary.append(garminBlocked);
    if (actual && !entry.is_completed_activity) appendPlannedTarget(cardSummary, entry);
    const details = document.createElement("div");
    details.className = "planned-entry-details";
    const head = plannedDetailHead(entry, actual, title, dateKey, status, plannedDetailStatus(entry, dateKey, todayKey, restDayLabel, weekHasPlan), plannedDayWeather(dayContext, dateKey));
    details.append(head);
    // The larger profile is drawn when the card first opens; most cards never do.
    card.addEventListener("toggle", () => {
      if (!card.open || details.querySelector(".planned-detail-profile")) return;
      const detailProfile = plannedDetailProfile(actual?.workout_profile || entry.workout_profile);
      if (detailProfile) head.after(detailProfile);
    });
    const metrics = plannedSessionMetrics(entry, actual);
    if (metrics) details.append(metrics);
    appendActualCalendarDetails(details, actual);
    if (actual && (actual.id || actual.activity_id)) details.append(plannedActivityButton(actual));
    appendPlannedCalendarComparison(details, entry, actual);
    const focusForm = plannedFocusForm(entry, dateKey);
    if (focusForm) details.append(focusForm);
    appendPlannedDescription(details, entry.description);
    card.append(cardSummary, details);
    return card;
  }

  function plannedDayWeather(dayContext, dateKey) {
    if (dayContext.weather) return dayContext.weather;
    const days = state.data?.weather?.days;
    return Array.isArray(days) ? days.find((item) => item?.date === dateKey) : null;
  }

  // The timeline's date column: weekday over the day of the month; today's day is filled.
  function plannedDayDate(day, dateKey) {
    const title = document.createElement("h5");
    title.className = "planned-day-date";
    title.id = `planned-day-${dateKey}`;
    const date = dateFromKey(dateKey);
    const weekday = document.createElement("span");
    weekday.textContent = new Intl.DateTimeFormat("de-DE", { weekday: "short" }).format(date);
    const number = document.createElement("time");
    number.dateTime = dateKey;
    number.textContent = String(date.getDate());
    title.append(weekday, number);
    day.setAttribute("aria-labelledby", title.id);
    return title;
  }

  // "Heute", the weather and its flags above the day's units; none when nothing applies.
  function plannedDayHeading(weather, dateKey, todayKey) {
    const heading = document.createElement("div");
    heading.className = "planned-day-heading";
    if (dateKey === todayKey) {
      const today = document.createElement("span");
      today.className = "planned-today-label";
      today.textContent = "Heute";
      heading.append(today);
    }
    const weatherLabel = plannedWeatherLabel(weather);
    if (weatherLabel) {
      const weatherText = document.createElement("span");
      weatherText.className = "planned-day-weather";
      weatherText.textContent = weatherLabel;
      weatherText.title = [...plannedWeatherDetails(weather), weatherLabel].join("\n");
      weatherText.setAttribute("aria-label", weatherText.title.replaceAll("\n", ". "));
      heading.append(weatherText);
      for (const flag of plannedWeatherFlags(weather)) {
        const flagText = document.createElement("span");
        flagText.className = "planned-day-flag";
        flagText.textContent = flag.text;
        flagText.setAttribute("aria-label", flag.label);
        heading.append(flagText);
      }
    }
    return heading.childElementCount ? heading : null;
  }

  function renderPlannedGroup(entries, dateKey, todayKey, dayContext, weekHasPlan) {
    const group = document.createElement("details");
    group.className = "planned-group";
    const first = entries[0];
    group.dataset.sport = activitySportLabel(calendarSportType(first));
    const summary = document.createElement("summary");
    summary.append(plannedSessionHeader(first, first, `${entries.length}× ${first.name || "Trainingseinheit"}`, () => {}));
    const items = document.createElement("div");
    items.className = "planned-group-items";
    items.append(...entries.map((entry) => renderPlannedEntry(entry, dateKey, todayKey, dayContext, weekHasPlan)));
    group.append(summary, items);
    return group;
  }

  function renderPlannedDay(view, dateKey, weekHasPlan) {
    const { eventsByDate, planningContextByDate, todayKey } = view;
    const dayEntries = eventsByDate.get(dateKey) || [];
    const dayContext = planningContextByDate.get(dateKey) || {};
    const day = document.createElement("section");
    day.className = `planned-day${dateKey === todayKey ? " is-today" : ""}`;
    day.dataset.date = dateKey;
    const content = document.createElement("div");
    content.className = "planned-day-content";
    const heading = plannedDayHeading(plannedDayWeather(dayContext, dateKey), dateKey, todayKey);
    if (heading) content.append(heading);
    const notes = plannedDayNotes(dayContext, state.data?.competitions, dateKey);
    if (notes.childElementCount) content.append(notes);
    if (!dayEntries.length) {
      const empty = document.createElement("p");
      empty.className = "planned-day-empty";
      empty.textContent = dateKey < todayKey ? "Keine Aktivität" : "Keine Einheit geplant";
      content.append(empty);
    }
    for (const group of plannedEntryGroups(dayEntries)) {
      content.append(group.entries.length > 1
        ? renderPlannedGroup(group.entries, dateKey, todayKey, dayContext, weekHasPlan)
        : renderPlannedEntry(group.entries[0], dateKey, todayKey, dayContext, weekHasPlan));
    }
    day.append(plannedDayDate(day, dateKey), content);
    return day;
  }

  // ISO 8601 week number: the week holding the year's first Thursday is week 1.
  function isoWeekNumber(weekKey) {
    const thursday = dateFromKey(addDateKey(weekKey, 3));
    const firstWeek = planWeekStart(localDateKey(new Date(thursday.getFullYear(), 0, 4)));
    return 1 + Math.round((dateFromKey(weekKey) - dateFromKey(firstWeek)) / (7 * 86_400_000));
  }

  // "Woche | Monat": the view is a switch only; the calendar always opens on the week.
  function plannedViewSwitch() {
    const group = document.createElement("div");
    group.className = "planned-view-switch";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Ansicht");
    for (const [value, label] of [["week", "Woche"], ["month", "Monat"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.view = value;
      button.textContent = label;
      button.setAttribute("aria-pressed", String(calendarView === value));
      button.addEventListener("click", () => {
        if (calendarView === value) return;
        calendarView = value;
        selectedDayKey = "";
        renderPlanned(renderedCalendar);
        $("#plannedCalendar")?.querySelector(`.planned-view-switch [data-view="${value}"]`)?.focus();
      });
      group.append(button);
    }
    return group;
  }

  function monthStartKey(dateKey, offset = 0) {
    const date = dateFromKey(`${dateKey.slice(0, 8)}01`);
    date.setMonth(date.getMonth() + offset);
    return localDateKey(date);
  }

  function selectPlannedDay(dateKey) {
    selectedDayKey = dateKey;
    selectedWeekKey = planWeekStart(dateKey);
    renderPlanned(renderedCalendar);
  }

  // One day of the month grid: its number and one mark per unit (a dot, on wide screens its duration).
  function plannedMonthDay(view, dateKey, monthKey) {
    const { eventsByDate, firstWeekKey, lastDateKey, todayKey } = view;
    const entries = eventsByDate.get(dateKey) || [];
    const button = document.createElement("button");
    button.type = "button";
    button.className = "planned-month-day";
    button.dataset.date = dateKey;
    button.classList.toggle("is-outside", dateKey.slice(0, 7) !== monthKey.slice(0, 7));
    button.classList.toggle("is-today", dateKey === todayKey);
    button.setAttribute("aria-pressed", String(dateKey === view.dayKey));
    button.disabled = dateKey < firstWeekKey || dateKey > lastDateKey;
    const number = document.createElement("span");
    number.className = "planned-month-number";
    number.textContent = String(dateFromKey(dateKey).getDate());
    const marks = document.createElement("span");
    marks.className = "planned-month-marks";
    for (const entry of entries) {
      const actual = calendarActualActivity(entry);
      const mark = document.createElement("span");
      mark.className = `planned-month-mark is-${calendarEntryStatus(entry, dateKey, todayKey)}`;
      mark.dataset.sport = activitySportLabel(calendarSportType(actual || entry));
      const seconds = actual ? Number(actual.moving_duration_s ?? actual.elapsed_duration_s) : Number(entry.duration_minutes) * 60 || Number(entry.planned_duration_s);
      // h:mm fits a day cell; the full label stays on the card.
      const minutes = Math.round(seconds / 60);
      mark.textContent = minutes > 0 ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}` : "";
      marks.append(mark);
    }
    button.append(number, marks);
    const units = entries.length ? countLabel(entries.length, "Einheit", "Einheiten") : "keine Einheit";
    button.setAttribute("aria-label", `${DETAIL_DATE_FORMAT.format(dateFromKey(dateKey))}: ${units}`);
    button.addEventListener("click", () => {
      selectPlannedDay(dateKey);
      const root = $("#plannedCalendar");
      root?.querySelector(`.planned-month-day[data-date="${dateKey}"]`)?.focus();
      const card = root?.querySelector(`.planned-day[data-date="${dateKey}"] .planned-day-content > .planned-entry`);
      if (card && wideCalendar?.matches) card.open = true;
    });
    return button;
  }

  // The month of the selected day: weeks Monday to Sunday with the ISO week and its planned time.
  function renderPlannedMonth(view) {
    const { eventsByDate, firstWeekKey, lastDateKey, todayKey } = view;
    const monthKey = monthStartKey(view.dayKey);
    const nextMonthKey = monthStartKey(monthKey, 1);
    const month = document.createElement("section");
    month.className = "planned-month";
    month.setAttribute("aria-labelledby", "plannedMonthTitle");
    const heading = document.createElement("header");
    heading.className = "planned-week-heading";
    const title = document.createElement("h4");
    title.id = "plannedMonthTitle";
    title.textContent = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" }).format(dateFromKey(monthKey));
    const previousKey = monthStartKey(monthKey, -1);
    const stepTo = (key) => {
      const day = [todayKey, key].find((item) => item.slice(0, 7) === key.slice(0, 7) && item >= key && item >= firstWeekKey && item <= lastDateKey);
      return day || (key < firstWeekKey ? firstWeekKey : key);
    };
    heading.append(title,
      plannedStep(-1, "Vorheriger Monat", addDateKey(monthKey, -1) >= firstWeekKey ? () => selectPlannedDay(stepTo(previousKey)) : null),
      plannedStep(1, "Nächster Monat", nextMonthKey <= lastDateKey ? () => selectPlannedDay(stepTo(nextMonthKey)) : null),
      plannedViewSwitch());
    const grid = document.createElement("div");
    grid.className = "planned-month-grid";
    const names = document.createElement("div");
    names.className = "planned-month-row planned-month-names";
    names.setAttribute("aria-hidden", "true");
    for (const name of ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So", "KW"]) names.append(Object.assign(document.createElement("span"), { textContent: name }));
    grid.append(names);
    const currentWeekKey = planWeekStart(todayKey);
    for (let weekKey = planWeekStart(monthKey); weekKey < nextMonthKey; weekKey = addDateKey(weekKey, 7)) {
      const row = document.createElement("div");
      row.className = `planned-month-row${weekKey === currentWeekKey ? " is-current" : ""}`;
      for (let offset = 0; offset < 7; offset += 1) row.append(plannedMonthDay(view, addDateKey(weekKey, offset), monthKey));
      const planned = Array.from({ length: 7 }, (_, offset) => eventsByDate.get(addDateKey(weekKey, offset)) || []).flat()
        .filter((entry) => !entry.is_completed_activity);
      const seconds = planned.reduce((total, entry) => total + Math.max(0, Number(entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.planned_duration_s) || 0), 0);
      const week = document.createElement("span");
      week.className = "planned-month-kw";
      week.textContent = [`KW ${isoWeekNumber(weekKey)}`, seconds > 0 ? calendarHours(seconds) : ""].filter(Boolean).join(" · ");
      row.append(week);
      grid.append(row);
    }
    month.append(heading, grid);
    return month;
  }

  function plannedStep(step, label, onStep) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button planned-week-step";
    button.dataset.step = String(step);
    button.textContent = step < 0 ? "‹" : "›";
    button.setAttribute("aria-label", label);
    button.disabled = !onStep;
    button.addEventListener("click", () => {
      onStep();
      const steps = [...($("#plannedCalendar")?.querySelectorAll(`.planned-week-step[aria-label="${label}"]`) || [])];
      (steps.find((item) => !item.disabled) || $("#plannedCalendar")?.querySelector(".planned-week-step:not(:disabled)"))?.focus();
    });
    return button;
  }

  function plannedWeekStep(step, target) {
    const button = plannedStep(step, step < 0 ? "Vorherige Woche" : "Nächste Woche", target ? () => {
      selectedWeekKey = target;
      if (calendarView === "month") selectedDayKey = target;
      renderPlanned(renderedCalendar);
    } : null);
    button.dataset.weekStep = String(step);
    return button;
  }

  function renderPlannedWeek(view) {
    const { eventsByDate, firstWeekKey, lastWeekKey, todayKey, weekKey, weeklyCompliance } = view;
    const weekEndKey = addDateKey(weekKey, 6);
    const weekEntries = Array.from({ length: 7 }, (_, offset) => eventsByDate.get(addDateKey(weekKey, offset)) || []).flat();
    const week = document.createElement("section");
    week.className = "planned-week";
    week.dataset.weekKey = weekKey;
    week.setAttribute("aria-labelledby", "plannedWeekTitle");
    const heading = document.createElement("header");
    heading.className = "planned-week-heading";
    const title = document.createElement("h4");
    title.id = "plannedWeekTitle";
    title.textContent = planWeekLabel(weekKey);
    const number = document.createElement("span");
    number.className = "planned-week-number";
    number.textContent = `KW ${isoWeekNumber(weekKey)}`;
    const count = document.createElement("span");
    count.className = "planned-week-summary";
    count.textContent = calendarCountLabel(weekEntries, todayKey) || "Keine Einheiten";
    heading.append(title, number,
      plannedWeekStep(-1, weekKey > firstWeekKey ? addDateKey(weekKey, -7) : ""),
      plannedWeekStep(1, weekKey < lastWeekKey ? addDateKey(weekKey, 7) : ""));
    if (calendarView === "week") heading.append(plannedViewSwitch());
    heading.append(count);
    const planned = weekEntries.filter((entry) => !entry.is_completed_activity);
    const actual = weekEntries.map(calendarActualActivity).filter(Boolean);
    const totals = plannedWeekMetrics(planned, actual);
    if (totals) heading.append(totals);
    const syncButton = plannedWeekSyncButton(weekKey, weekEntries, view.leftoversByWeek?.get(weekKey), todayKey);
    if (syncButton) {
      const bar = document.createElement("div");
      bar.className = "planned-week-sync";
      bar.append(syncButton);
      heading.append(bar);
    }
    week.append(heading);
    const days = document.createElement("div");
    days.className = "planned-week-days";
    for (let offset = 0; offset < 7; offset += 1) days.append(renderPlannedDay(view, addDateKey(weekKey, offset), planned.length > 0));
    week.append(days);
    const legend = plannedZoneLegend(days);
    if (legend) week.append(legend);
    if (weekEntries.length) {
      const additionalCompleted = weekEntries.filter((entry) => entry.is_completed_activity).length;
      const details = document.createElement("p");
      details.className = "planned-week-totals";
      const summary = plannedWeekSummary(weekKey, weekEndKey, weekEntries, weeklyCompliance.get(weekKey), todayKey);
      details.textContent = additionalCompleted && planned.length ? `${summary} · +${additionalCompleted} zusätzlich` : summary;
      week.append(details);
    }
    return week;
  }

  // Wide screens show the open card's body as the detail pane beside the week, level with its card
  // (styles.css); the calendar keeps room for it, and a week opens with today's or the next unit.
  const wideCalendar = globalThis.matchMedia?.("(min-width: 1100px)");
  const detailObserver = globalThis.ResizeObserver ? new ResizeObserver(() => syncPlannedDetailHeight()) : null;

  function syncPlannedDetailHeight() {
    const root = $("#plannedCalendar");
    if (!root) return;
    const card = wideCalendar?.matches ? shownPlannedEntry(root) : null;
    const body = card?.querySelector(":scope > .planned-entry-details");
    if (!body) {
      root.style.minHeight = "";
      return;
    }
    const top = Math.max(0, card.getBoundingClientRect().top - root.getBoundingClientRect().top);
    body.style.top = `${top}px`;
    root.style.minHeight = `${top + body.offsetHeight}px`;
  }

  // A closed card leaves the pane empty; a collapsed group or a switch to a wide screen opens the default.
  function watchPlannedDetail(event) {
    const root = $("#plannedCalendar");
    if (!event?.target?.classList?.contains("planned-entry")) openDefaultPlannedEntry(root?.querySelector(".planned-week"));
    detailObserver?.disconnect();
    const body = shownPlannedEntry(root)?.querySelector(":scope > .planned-entry-details");
    if (body) detailObserver?.observe(body);
    syncPlannedDetailHeight();
  }

  function openDefaultPlannedEntry(week) {
    if (!wideCalendar?.matches || !week || shownPlannedEntry(week)) return;
    const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const upcoming = (cards) => cards.find((item) => item.closest(".planned-day").dataset.date >= todayKey) || cards.at(-1);
    const single = upcoming([...week.querySelectorAll(".planned-day-content > .planned-entry")]);
    const card = single || upcoming([...week.querySelectorAll(".planned-group-items > .planned-entry")]);
    if (!card) return;
    if (!single) card.closest(".planned-group").open = true;
    card.open = true;
  }

  let plannedRenderSnapshot = null;
  let selectedWeekKey = "";
  let calendarView = "week";
  let selectedDayKey = "";
  let renderedCalendar = [];

  function renderPlanned(trainingCalendar) {
    const root = $("#plannedCalendar");
    if (!root) return;
    renderedCalendar = trainingCalendar;
    const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const currentWeekKey = planWeekStart(todayKey);
    const display = state.data?.calendar_display || {};
    const pastWeeks = calendarDisplayValue(display.past_weeks, 1);
    const futureWeeks = calendarDisplayValue(display.future_weeks, 4);
    const firstWeekKey = addDateKey(currentWeekKey, -7 * pastWeeks);
    const lastWeekKey = addDateKey(currentWeekKey, 7 * futureWeeks);
    if (!selectedWeekKey || selectedWeekKey < firstWeekKey || selectedWeekKey > lastWeekKey) selectedWeekKey = currentWeekKey;
    const lastDateKey = addDateKey(lastWeekKey, 6);
    if (calendarView === "month") {
      if (!selectedDayKey || selectedDayKey < firstWeekKey || selectedDayKey > lastDateKey) selectedDayKey = selectedWeekKey === currentWeekKey ? todayKey : selectedWeekKey;
      selectedWeekKey = planWeekStart(selectedDayKey);
    }
    const snapshot = JSON.stringify([trainingCalendar, todayKey, selectedWeekKey, calendarView, selectedDayKey, display, state.data?.daily_planning_context, state.data?.planning_compliance, state.data?.competitions, state.data?.weather]);
    if (snapshot === plannedRenderSnapshot && root.childElementCount) {
      if (state.plannedTodayFocusPending) requestAnimationFrame(() => focusPlannedToday());
      return;
    }
    plannedRenderSnapshot = snapshot;
    if (!root.dataset.detailWatch) {
      root.dataset.detailWatch = "true";
      root.addEventListener("toggle", watchPlannedDetail, true);
      wideCalendar?.addEventListener?.("change", watchPlannedDetail);
    }
    const focusedEntry = rememberPlannedEntryState(root);
    root.replaceChildren();
    const weeklyCompliance = new Map(
      (Array.isArray(state.data?.planning_compliance) ? state.data.planning_compliance : [])
        .filter((item) => item?.week_start)
        .map((item) => [String(item.week_start).slice(0, 10), item]),
    );
    const entries = (Array.isArray(trainingCalendar) ? trainingCalendar : [])
      .filter((item) => item && !item.archived && !item.local_deleted && plannedEventDate(item))
      .filter((item) => plannedEventDate(item) >= firstWeekKey && plannedEventDate(item) <= lastDateKey)
      .sort((left, right) => String(left.starts_at_local || left.started_at_local || left.date || "").localeCompare(String(right.starts_at_local || right.started_at_local || right.date || "")));
    const planningContextByDate = new Map(
      (Array.isArray(state.data?.daily_planning_context) ? state.data.daily_planning_context : [])
        .filter((item) => item?.date)
        .map((item) => [String(item.date).slice(0, 10), item]),
    );
    const eventsByDate = new Map();
    entries.forEach((entry) => {
      const key = plannedEventDate(entry);
      if (!eventsByDate.has(key)) eventsByDate.set(key, []);
      eventsByDate.get(key).push(entry);
    });

    const upcomingDays = Array.from({ length: (pastWeeks + futureWeeks + 1) * 7 }, (_, offset) => addDateKey(firstWeekKey, offset))
      .filter((dateKey) => dateKey >= todayKey);
    if (!upcomingDays.some((dateKey) => plannedWeatherLabel(plannedDayWeather(planningContextByDate.get(dateKey) || {}, dateKey)))) root.append(plannedWeatherHint());
    const view = {
      leftoversByWeek: plannedLeftoversByWeek(trainingCalendar, currentWeekKey, lastWeekKey),
      eventsByDate,
      dayKey: selectedDayKey,
      firstWeekKey,
      lastDateKey,
      lastWeekKey,
      planningContextByDate,
      todayKey,
      weekKey: selectedWeekKey,
      weeklyCompliance,
    };
    if (calendarView === "month") root.append(renderPlannedMonth(view));
    const week = renderPlannedWeek(view);
    openDefaultPlannedEntry(week);
    root.append(week);
    restorePlannedEntryFocus(root, focusedEntry);
    watchPlannedDetail();
    if (state.plannedTodayFocusPending) requestAnimationFrame(() => focusPlannedToday());
  }

  // Wahoo state of an exported library workout. A changed one offers the
  // explicit send; the job carries the payload hash the server returned, so a
  // workout edited meanwhile is refused instead of pushed.
  function libraryWahooRow(workout) {
    const wahoo = workout.wahoo_state;
    if (!wahoo?.state || !workout.id) return null;
    const changed = wahoo.state === "changed";
    const row = document.createElement("div");
    row.className = "library-wahoo";
    const label = document.createElement("span");
    label.className = `library-wahoo-state is-${changed ? "changed" : "synced"}`;
    label.textContent = changed ? "Wahoo: geändert" : "Wahoo: synchron";
    row.append(label);
    if (!changed || !wahoo.payload_hash) return row;
    state.librarySyncInFlight ||= new Set();
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button library-wahoo-send";
    button.textContent = "Erneut senden";
    button.setAttribute("aria-label", `${workout.name || "Einheit"} an Wahoo senden`);
    button.disabled = state.librarySyncInFlight.has(workout.id);
    button.addEventListener("click", async () => {
      if (state.librarySyncInFlight.has(workout.id)) return;
      state.librarySyncInFlight.add(workout.id);
      button.disabled = true;
      let failure = "";
      try {
        const done = await runPlanPush(providerIds().wahoo, [{ library_workout_id: workout.id, expected_payload_hash: wahoo.payload_hash }]);
        if (done.status !== "completed") failure = globalThis.providerJobErrorDetail?.(done) || "Synchronisierung fehlgeschlagen";
      } catch (error) {
        failure = error.message;
      }
      state.librarySyncInFlight.delete(workout.id);
      globalThis.toast?.(failure || "An Wahoo gesendet", Boolean(failure));
      button.disabled = false;
      await globalThis.load?.();
    });
    row.append(button);
    return row;
  }

  function renderLibrary(workouts) {
    const root = $("#library");
    if (!root) return;
    root.replaceChildren();
    appendHistoryPageButton(root, "library");
    const allWorkouts = Array.isArray(workouts) ? workouts : [];
    const visible = allWorkouts.filter((workout) => !workout.archived && !workout.date);
    const librarySummary = $("#librarySummary");
    if (librarySummary) librarySummary.textContent = `${visible.length} Einheit${visible.length === 1 ? "" : "en"}`;
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.className = "context-empty";
      empty.textContent = "Noch keine Einheiten in der Bibliothek. Der Coach legt hier Einheiten ab, wenn du sie planst.";
      root.append(empty);
      return;
    }
    const groups = new Map();
    visible.forEach((workout) => {
      const sport = activitySportLabel(workout);
      if (!groups.has(sport)) groups.set(sport, []);
      groups.get(sport).push(workout);
    });
    [...groups.entries()]
      .sort(([a], [b]) => a.localeCompare(b, "de"))
      .forEach(([sport, sportWorkouts]) => {
        const section = document.createElement("details");
        section.className = "library-sport";
        section.open = false;
        const summary = document.createElement("summary");
        const title = document.createElement("strong");
        title.textContent = sport;
        summary.append(title, Object.assign(document.createElement("span"), { textContent: `${sportWorkouts.length} Einheit${sportWorkouts.length === 1 ? "" : "en"}` }));
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
          meta.textContent = [workout.type, workout.planned_duration_s ? formatDuration(workout.planned_duration_s) : null].filter(Boolean).join(" · ");
          heading.append(cardTitle, meta);
          const description = document.createElement("p");
          description.textContent = workout.description || "Kein Workout-Text hinterlegt.";
          card.append(heading, description);
          const wahoo = libraryWahooRow(workout);
          if (wahoo) card.append(wahoo);
          cards.append(card);
        });
        section.append(cards);
        root.append(section);
      });
  }



  function competitionCard(competition, todayKey, openIds) {
    const card = document.createElement("details");
    card.className = "competition-card";
    card.dataset.competitionId = String(competition.id);
    card.open = openIds.has(String(competition.id));
    const summary = document.createElement("summary");
    const title = document.createElement("strong");
    title.textContent = `${competitionDate(competition, todayKey) ? dateLabel(competition.event_date) : "Datum unbekannt"} · ${competition.name || "Wettkampf"}`;
    const facts = document.createElement("span");
    facts.className = "competition-summary-facts";
    const sport = competition.sport_detail || competitionSportLabel(competition.sport, competition.environment);
    const when = AppFormat.relativeDay(competition.event_date, todayKey);
    facts.textContent = [sport, competitionDistance(competition.distance), `Priorität ${competition.priority || "B"}`, when].filter(Boolean).join(" · ");
    summary.append(title, facts);
    card.append(summary);
    const source = document.createElement("small");
    source.className = "competition-sync-state";
    source.textContent = competition.external_id ? "Intervals.icu" : "Lokal";
    if (competition.sync_state === "local_override") source.textContent = "Lokal geändert";
    card.append(source);
    const details = document.createElement("div");
    details.className = "competition-card-facts";
    const optional = [
      ["Ergebnis", competitionResult(competition.result)],
      ["Startzeit", competition.starts_at_local ? formatLocalCompetitionTime(competition.starts_at_local) : null],
      ["Ziel", competition.target],
      ["Erwartete Dauer", competition.planned_duration_s == null ? null : AppFormat.duration(competition.planned_duration_s)],
      ["Streckenprofil", competition.course_profile],
      ["Beschreibung", competition.description],
      ["Notizen", competition.notes],
    ];
    for (const [label, value] of optional) {
      if (value != null && String(value).trim() !== "") details.append(competitionFact(label, value));
    }
    if (details.childElementCount) card.append(details);
    return card;
  }

  function renderCompetitions(competitions) {
    const root = $("#competitionList");
    if (!root || !Array.isArray(competitions)) return;
    const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const snapshot = JSON.stringify([competitions, todayKey]);
    if (root.dataset.snapshot === snapshot) return;
    const openIds = new Set([...root.querySelectorAll("details[data-competition-id][open]")].map((node) => node.dataset.competitionId));
    const focusedId = document.activeElement?.closest("details[data-competition-id]")?.dataset.competitionId;
    const archiveOpen = root.querySelector(".competition-archive")?.open || false;
    root.dataset.snapshot = snapshot;
    root.replaceChildren();
    if (!competitions.length) {
      const empty = document.createElement("p");
      empty.className = "context-empty";
      empty.textContent = "Noch keine Wettkämpfe gespeichert.";
      root.append(empty);
      return;
    }
    const ordered = [...competitions].sort((a, b) =>
      String(a.event_date || "").localeCompare(String(b.event_date || ""))
      || String(a.priority || "B").localeCompare(String(b.priority || "B"))
      || String(a.name || "").localeCompare(String(b.name || ""), "de")
      || String(a.id).localeCompare(String(b.id)));
    const past = [], undated = [];
    for (const competition of ordered) {
      if (!competitionDate(competition, todayKey)) undated.push(competition);
      else if (competition.event_date < todayKey) past.push(competition);
      else root.append(competitionCard(competition, todayKey, openIds));
    }
    if (undated.length) {
      const heading = document.createElement("h4");
      heading.textContent = "Ohne gültiges Datum";
      root.append(heading, ...undated.map((event) => competitionCard(event, todayKey, openIds)));
    }
    if (past.length) {
      const archive = document.createElement("details");
      archive.className = "competition-archive";
      archive.open = archiveOpen;
      const summary = document.createElement("summary");
      summary.textContent = `Vergangene Wettkämpfe (${past.length})`;
      archive.append(summary);
      past.sort((a, b) => b.event_date.localeCompare(a.event_date) || ordered.indexOf(a) - ordered.indexOf(b));
      archive.append(...past.map((event) => competitionCard(event, todayKey, openIds)));
      root.append(archive);
    }
    if (focusedId) [...root.querySelectorAll("details[data-competition-id]")].find((node) => node.dataset.competitionId === focusedId)?.querySelector("summary")?.focus();
  }

  function renderCompetitionReadStatus(status) {
    const node = $("#competitionReadStatus");
    const retry = $("#competitionRetry");
    if (!node || !retry) return;
    const hasData = Array.isArray(state.data?.competitions);
    let message = "";
    if (status === "error") {
      message = hasData ? "Gespeicherter Stand. Aktualisierung fehlgeschlagen." : "Wettkämpfe konnten nicht geladen werden.";
    } else if (status === "loading") {
      message = hasData ? "Gespeicherter Stand wird aktualisiert …" : "Wettkämpfe werden geladen …";
    }
    node.textContent = message;
    retry.hidden = status !== "error";
  }

  function formatLocalCompetitionTime(value) {
    const raw = String(value || "");
    const match = /(?:T|\s)(\d{2}:\d{2})(?::\d{2})?/.exec(raw);
    return match ? match[1] : formatTime(value);
  }


  function bindPlanNavigation() {
    document.querySelectorAll("[data-plan-segment]").forEach((link) => link.addEventListener("click", (event) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      void AppRouter.navigate(`plan/${link.dataset.planSegment}`, { historyMode: "push" });
    }));
  }
  function bindExternalCalendar(syncExternalCalendar) {
    $("#externalCalendarSyncButton").addEventListener("click", syncExternalCalendar);
  }
  return Object.freeze({ renderAdaptivePlanning, renderExternalCalendar, renderPlanned, renderLibrary, renderCompetitions, renderCompetitionReadStatus, focusPlannedToday, bindPlanNavigation, bindExternalCalendar });
}
