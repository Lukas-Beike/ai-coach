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

// What a week's sync delivered per provider: Garmin gets structured workouts.
function plannedWeekSyncSummary(done, ids, providerLabel) {
  const totals = new Map();
  for (const job of done) {
    const item = totals.get(job.provider) || { send: 0, remove: 0 };
    item[job.kind === "remove" ? "remove" : "send"] += job.entries.length;
    totals.set(job.provider, item);
  }
  const reached = [...totals].map(([provider, item]) => {
    const verb = provider === ids.garmin ? "strukturiert" : "gesendet";
    const sent = item.send ? `${item.send} ${verb}` : "";
    const removed = item.remove ? `${item.remove} alte entfernt` : "";
    return `${providerLabel(provider)}: ${[sent, removed].filter(Boolean).join(", ")}`;
  });
  // A strength unit without a Garmin workout says why the watch did not get it.
  const blocked = new Set(done.flatMap((job) => job.units).map(plannedGarminBlockedText).filter(Boolean));
  return [...reached, ...blocked].join(" · ");
}

// Controls sit in the card summary; a click must not toggle the card.
// Before a rebuild: remember which cards are open and which control has focus.
function rememberPlannedEntryState(root) {
  openPlannedEntries = new Set([...root.querySelectorAll(".planned-entry[data-entry-key]")].filter((card) => card.open).map((card) => card.dataset.entryKey));
  for (const key of plannedFocusStatuses.keys()) if (!openPlannedEntries.has(key)) plannedFocusStatuses.delete(key);
  for (const key of plannedMoveReceipts.keys()) if (!openPlannedEntries.has(key)) plannedMoveReceipts.delete(key);
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
  details.append(h("p", "planned-description", text || "Keine weiteren Details hinterlegt."));
}

// The planned steps as a list (#2447, mockup B): zone mark, duration or distance, zone, and the target
// range of the zones in effect on the unit's day right-aligned; a step without a range shows none.
function plannedStepList(profile) {
  const segments = profile?.source === "planned" && Array.isArray(profile.segments) ? profile.segments : [];
  if (!segments.length || segments.length > 200) return null;
  const axis = profile.axis === "distance" ? "distance" : "duration";
  const rows = segments.map((segment) => {
    const zone = Number.isInteger(segment.zone) && segment.zone >= 1 && segment.zone <= 7 ? segment.zone : null;
    // The zone text is the written zone target ("Z1–Z2"); a percent or watt target shows its own text instead.
    const label = String(segment.label || "");
    const written = /^Z([1-7])(?:\s*-\s*Z([1-7]))?/.exec(label);
    const zoneText = written ? [written[1], written[2]].filter(Boolean).map((value) => `Z${value}`).join("–") : null;
    const range = plannedStepRange(segment.range) || (written ? "" : label.slice(0, 40));
    return h("li", { dataset: { zone: zone || "unknown" } },
      h("span", { className: "planned-step-mark", "aria-hidden": "true" }),
      h("span", "planned-step-text", [plannedStepExtent(Number(segment[axis]), axis), zoneText].filter(Boolean).join(" · ")),
      h("span", "planned-step-range", range));
  });
  return h("ol", { className: "planned-steps", "aria-label": "Ablauf" }, rows);
}

// A step's exact length: "30 s", "1:30 min", "55 min", "1:10 h"; "400 m", "1,25 km".
const STEP_KM_FORMAT = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });
function plannedStepExtent(size, axis) {
  if (axis === "distance") return size < 1000 ? `${Math.round(size)} m` : `${STEP_KM_FORMAT.format(size / 1000)} km`;
  if (size < 60) return `${Math.round(size)} s`;
  return size < 3600 && Math.round(size) % 60 ? `${AppFormat.clock(size)} min` : AppFormat.duration(size);
}

// "110–128 bpm", "≤ 109 bpm" for the lowest zone, "≥ 155 bpm" for the open top; pace in min/km, slower end first.
function plannedStepRange(range) {
  if (!range || !["bpm", "W", "s/km"].includes(range.unit)) return "";
  const pace = range.unit === "s/km";
  const text = (value) => (pace ? AppFormat.clock(value) : String(value));
  const unit = pace ? "/km" : range.unit;
  const { min, max } = range;
  if (Number.isFinite(min) && Number.isFinite(max)) return min === max ? `${text(min)} ${unit}` : `${text(min)}–${text(max)} ${unit}`;
  // Pace counts down with intensity: the lowest zone is slower than its limit, the top one faster.
  if (Number.isFinite(max)) return `${pace ? "≥" : "≤"} ${text(max)} ${unit}`;
  if (Number.isFinite(min)) return `${pace ? "≤" : "≥"} ${text(min)} ${unit}`;
  return "";
}

// The description without its step lines ("- 10m Z2 HR") and repeat headers ("4x").
function plannedDescriptionText(text) {
  // As the workout parser reads them: a step starts with "-", a repeat header ends with "4x".
  const step = /^\s*-/;
  const repeat = /\b\d+x\s*$/i;
  return String(text || "").split("\n").filter((line) => !step.test(line) && !repeat.test(line)).join("\n").trim();
}

function stopSummaryToggle(event) {
  event.preventDefault();
  event.stopPropagation();
}

// A request kind sends the prompt as that quick action, on the planning model (#2744); without a
// planning key the button is off like the other planning entry points.
function plannedCoachButton(label, prompt, className = "secondary-button planned-conflict-button", requestKind = null) {
  const button = h("button", { type: "button", className, dataset: requestKind ? { requestKind } : undefined }, label);
  button.disabled = Boolean(requestKind) && !coachConfigured(null, requestKind);
  button.addEventListener("click", (event) => { stopSummaryToggle(event); void globalThis.askCoach?.(prompt, { requestKind }); });
  return button;
}

function plannedGarminBlockedText(entry) {
  const reason = entry?.push_blocked && Object.values(entry.push_blocked)[0];
  if (reason === "no_structure") return "Keine Kraftstruktur – nicht an Garmin gesendet";
  if (reason === "unmapped") return "Übung ohne Garmin-Zuordnung – nicht an Garmin gesendet";
  return "";
}

// The Personal API key alone cannot write workouts: a unit Garmin would wait for needs the SDK login.
function plannedGarminSdkRequired(entry, garmin) {
  return garmin?.configured === true && garmin.can_write_workouts === false && entry?.push_pending?.[providerIds().garmin] === true;
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

// Garmin names an activity "<place> - <workout>"; the calendar shows it without the place.
// Only the athlete's own place (the profile's weather location) counts as one, so a workout
// name such as "Sweet Spot - 3 x 12 min" stays whole; the stored name never changes.
const CALENDAR_NAME_PREFIX = /^(.+?) [-–—] (\S.*)$/u;

function calendarDisplayName(name, place = "") {
  const text = String(name || "").trim();
  const match = CALENDAR_NAME_PREFIX.exec(text);
  const city = String(place || "").split(",")[0].trim().toLocaleLowerCase("de");
  return match && city && match[1].trim().toLocaleLowerCase("de") === city ? match[2] : text;
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
function calendarClock(seconds) {
  const minutes = Math.round(Math.max(0, Number(seconds) || 0) / 60);
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

function calendarHours(seconds) {
  return `${calendarClock(seconds)} h`;
}

function plannedDurationSeconds(entry) {
  return Math.max(0, Number(entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.planned_duration_s) || 0);
}

const CALENDAR_SPORT_ICONS = { Radfahren: "🚴", "Rad indoor": "🚴", Laufen: "🏃", Schwimmen: "🏊", Kraft: "🏋" };

function calendarRoundedNumber(value, suffix) {
  if (value == null || value === "") return null;
  return calendarMetricNumber(Math.round(Number(value)), suffix);
}

// The intensity factor as a fraction; stored values above 2 are percent.
function calendarIntensityFactor(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return null;
  return AppFormat.number(number <= 2 ? number : number / 100, { digits: 2 });
}

// The average speed, else distance over moving time.
function calendarSpeedLabel(activity) {
  let speed = Number(activity?.avg_speed_mps);
  if (!Number.isFinite(speed) || speed <= 0) speed = Number(activity?.distance_m) / Number(activity?.moving_duration_s);
  return Number.isFinite(speed) && speed > 0 ? `${AppFormat.number(speed * 3.6, { digits: 1 })} km/h` : null;
}

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
  root.append(h("span", null, h("strong", null, label), ` ${value}`));
}

function calendarBadge({ kind, icon, text }) {
  return h("span", `planned-badge is-${kind}`, icon ? h("span", { "aria-hidden": "true" }, icon) : null, text);
}

function calendarBadgeRow(specs) {
  return h("div", "planned-badges", specs.map(calendarBadge));
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
  return h("div", null, h("span", null, labelText), h("strong", null, value || "–"));
}

function calendarEntryStatus(entry, dateKey, todayKey) {
  if (calendarActualActivity(entry)) return "completed";
  if (entry?.compliance?.status === "missed") return "missed";
  return dateKey === todayKey ? "today" : "planned";
}

function calendarStatusLabel(entry, dateKey, todayKey) {
  const status = calendarEntryStatus(entry, dateKey, todayKey);
  if (status === "completed") return entry.is_completed_activity ? "✓ Zusätzlich" : "✓ Absolviert";
  if (status === "missed") return "✕ Nicht absolviert";
  return status === "today" ? "Heute geplant" : "Geplant";
}

function calendarRpeLabel(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 10 ? calendarMetricNumber(number) : null;
}

function plannedDayNotes(dayContext, competitions, dateKey) {
  const notes = h("div", "planned-day-notes");
  for (const { kind, icon, text } of plannedDayNoteSpecs(dayContext, competitions, dateKey)) {
    notes.append(h("p", `planned-day-context planned-day-${kind}`,
      icon ? h("span", { "aria-hidden": "true" }, `${icon} `) : null,
      kind === "calendar" ? h("span", "sr-only", "Kalender: ") : null,
      text));
  }
  const checkin = dayContext.checkin && typeof dayContext.checkin === "object" ? dayContext.checkin : {};
  const illness = String(checkin.illness || "").trim();
  const pain = String(checkin.pain || "").trim();
  if (illness || pain) {
    notes.append(h("p", "planned-day-context planned-day-health", [
      illness ? `Krankheit: ${illness}` : "",
      pain ? `Verletzung/Beschwerden: ${pain}` : "",
    ].filter(Boolean).join(" · ")));
  }
  return notes;
}

function plannedEntryDurationLabel(actual, entry) {
  if (actual) return AppFormat.duration(AppFormat.sessionSeconds(actual));
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
  return h("ul", "planned-strength", strength.exercises.map((exercise) => {
    const load = exercise.planned_kg == null ? "" : ` @ ${calendarMetricNumber(exercise.planned_kg)} kg`;
    const plan = `${exercise.planned_sets}×${exercise.planned_reps}${load}`;
    const name = plannedStrengthName(exercise);
    return h("li", null, exercise.status === "matched"
      ? `${name}: ${exercise.completed_sets}/${exercise.planned_sets} Sätze erreicht · Ist ${(exercise.reps || []).map((reps) => reps ?? "?").join("/") || "–"} Wdh. · Plan ${plan}`
      : `${name}: nicht zugeordnet · Plan ${plan}`);
  }));
}

function appendPlannedCalendarComparison(details, entry, actual) {
  if (!actual || entry.is_completed_activity) return;
  const plannedDuration = entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.planned_duration_s;
  // The actual values and the share of the plan are shown once, above and in the status.
  const planLine = h("p", null, `Plan: ${[
    entry.name,
    AppFormat.duration(plannedDuration),
    entry.training_load != null ? `Belastung ${calendarMetricNumber(entry.training_load)}` : null,
  ].filter(Boolean).join(" · ")}`);
  details.append(h("div", "planned-comparison", planLine, plannedStrengthRows(entry.compliance?.strength_sets)));
}

// "Zusätzlich" only means something next to a plan, so an extra activity in a week without one shows no status.
function appendPlannedEntryStatus(cardSummary, entry, status, restDayLabel, dateKey, todayKey, weekHasPlan) {
  if (status === "planned" || status === "today") return;
  if (entry.is_completed_activity && !weekHasPlan) return;
  if (cardSummary.textContent) cardSummary.append(" · ");
  const statusText = h("span", { className: "planned-entry-status", textContent: status === "skipped" ? `Entfallen (${restDayLabel})` : calendarStatusLabel(entry, dateKey, todayKey) });
  const percentage = calendarMetricNumber(entry.compliance?.percentage);
  const basis = { training_load: "Belastung", duration: "Dauer", strength_sets: "Sätze" }[entry.compliance?.basis];
  if (status === "completed" && percentage != null && basis) {
    statusText.textContent += ` · ${percentage} %`;
    statusText.title = `Anteil am Plan (${basis})`;
    statusText.setAttribute("aria-label", `${statusText.textContent.replace(" %", " Prozent")} des Plans · ${basis}`);
  }
  cardSummary.append(statusText);
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
// Calendar cards whose "Details" are open, so a re-render keeps them open (#2258).
const openActivityDetails = new Set();
// One read of a session's detail document per calendar data, shared by the zone bar and "Details" (#2478).
const plannedSessionReads = new Map();

// `fresh` (a retry or a detail refresh in "Details") replaces the shared read, so a rebuild shows the new document.
function plannedSessionRead(activityId, fresh = false) {
  let read = fresh ? null : plannedSessionReads.get(activityId);
  if (!read) {
    read = api(`/api/activities/${encodeURIComponent(activityId)}`, { timeoutMs: DATA_LOAD_TIMEOUT_MS });
    // A failed read is not shared: the next opening or retry reads again.
    read.catch(() => { if (plannedSessionReads.get(activityId) === read) plannedSessionReads.delete(activityId); });
    plannedSessionReads.set(activityId, read);
  }
  return read;
}

function completedSessionIds(calendar) {
  return new Set(calendar.map((item) => calendarActualActivity(item)).filter(Boolean).map((actual) => String(actual.activity_id || actual.id)));
}
const plannedFocusStatuses = new Map();
// The receipt of a moved unit by card key ({ text, change, from }); the open card shows it after the re-render.
const plannedMoveReceipts = new Map();
const MOVE_DAY_FORMAT = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });
const MOVE_WEEKDAY_FORMAT = new Intl.DateTimeFormat("de-DE", { weekday: "short" });

// The summary chip follows the saved focus without waiting for the next reload.
function refreshFocusChip(card, entry) {
  const holder = h("span");
  appendFocusChip(holder, entry);
  const row = card.querySelector("summary [data-focus-chip]");
  if (row) row.replaceWith(...holder.childNodes);
  else card.querySelector("summary .planned-session-line")?.append(...holder.childNodes);
}

function focusSelect(label, name, options, selected) {
  const select = h("select", { name }, [["", "–"], ...options].map(([value, text]) => h("option", { value, selected: value === (selected || "") }, text)));
  return { field: h("label", "planned-focus-field", label, select), select };
}

// A planned unit's load; a completed one shows its values in the facts.
function plannedSessionMetrics(entry) {
  const load = calendarMetricNumber(entry.training_load);
  if (load == null) return null;
  return h("span", "planned-session-metrics", `Belastung ${load}`);
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
      ? JSON.stringify([entry.name || "", entry.type || entry.sport || "", entry.environment || "", AppFormat.sessionSeconds(entry) ?? null, Number(entry.distance_m) > 0 ? Number(entry.distance_m) : null])
      : null;
    const previous = groups.at(-1);
    if (key && previous?.key === key) previous.entries.push(entry);
    else groups.push({ key, entries: [entry] });
  }
  return groups;
}

function appendWeekMetricCell(grid, cell) {
  grid.append(h("strong", null, cell?.value ?? "–", cell?.note ? h("small", null, cell.note) : null));
}

function plannedZoneLegend(days) {
  const zones = [...new Set([...days.querySelectorAll(".calendar-workout-profile [data-zone]")].map((node) => node.dataset.zone))]
    .filter((zone) => zone !== "unknown")
    .sort((left, right) => Number(left) - Number(right));
  if (!zones.length) return null;
  return h("p", "planned-zone-legend", zones.map((zone) => h("span", null, h("i", { dataset: { zone }, "aria-hidden": "true" }), `Z${zone}`)));
}

// Fixed grid with one column each for planned and completed values; a row appears only when it has a value.
function plannedWeekMetrics(planned, actual) {
  const columns = [planned.length ? "planned" : null, actual.length ? "actual" : null].filter(Boolean);
  if (!columns.length) return null;
  const totals = h("span", { className: "planned-week-metrics", dataset: { columns: String(columns.length) } });
  const plannedSeconds = planned.reduce((total, entry) => total + plannedDurationSeconds(entry), 0);
  const actualSeconds = actual.reduce((total, entry) => total + Math.max(0, Number(AppFormat.sessionSeconds(entry)) || 0), 0);
  const plannedDistance = planned.reduce((total, entry) => total + Math.max(0, Number(entry.distance) || 0), 0);
  const rows = [
    ["Dauer", { planned: plannedSeconds > 0 ? { value: calendarHours(plannedSeconds) } : null, actual: { value: calendarHours(actualSeconds) } }],
    ["Distanz", { planned: plannedDistance > 0 ? { value: AppFormat.distance(plannedDistance) } : null, actual: calendarWeekDistance(actual) }],
    ["Belastung", { planned: calendarWeekLoad(planned), actual: calendarWeekLoad(actual) }],
  ];
  totals.append(h("span"));
  for (const column of columns) totals.append(h("span", "planned-week-column", column === "planned" ? "Geplant" : "Absolviert"));
  for (const [label, cells] of rows) {
    if (!columns.some((column) => cells[column])) continue;
    totals.append(h("span", null, label));
    for (const column of columns) appendWeekMetricCell(totals, cells[column]);
  }
  return totals.childElementCount > columns.length + 1 ? totals : null;
}

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
  renderUndecidedNavCount();
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
  return h("p", "planned-weather-hint", state.data?.weather?.configured
    ? "Für die kommenden Tage liegt noch keine Wettervorhersage vor."
    : "Wetter fehlt: Im Profil ist kein Wetterort hinterlegt.");
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

// Each value once; duration and distance stay in the card's row.
// The values a session shows, per sport (athlete decision #2258); a value without data is left out.
function actualCalendarFacts(actual) {
  const rpe = calendarRpeLabel(actual.rpe);
  const values = {
    Belastung: calendarMetricNumber(actual.training_load),
    RPE: rpe != null ? `${rpe}/10` : null,
    Intensität: calendarIntensityLabel(actual.intensity),
    "Ø Puls": calendarMetricNumber(actual.avg_hr, " bpm"),
    "Ø Leistung": calendarMetricNumber(actual.avg_power, " W"),
    Pace: calendarPaceLabel(actual),
    Höhenmeter: calendarMetricNumber(actual.elevation_gain_m, " m"),
  };
  const sport = activitySportLabel(calendarSportType(actual));
  if (sport === "Laufen") {
    return [
      ["Pace", values.Pace], ["Ø Puls", values["Ø Puls"]],
      // Runs store the cadence per leg; the step frequency counts both legs.
      ["Schrittfrequenz", Number(actual.avg_cadence) > 0 ? calendarRoundedNumber(Number(actual.avg_cadence) * 2, " spm") : null],
      ["Ø Leistung", values["Ø Leistung"]], ["Belastung", values.Belastung], ["RPE", values.RPE],
      ["Bodenkontaktzeit", calendarRoundedNumber(actual.ground_contact_time_ms, " ms")],
      ["Höhenmeter", values.Höhenmeter],
    ];
  }
  if (sport === "Radfahren" || sport === "Rad indoor") {
    return [
      ["Normalized Power", calendarMetricNumber(actual.normalized_power, " W")], ["Ø Leistung", values["Ø Leistung"]],
      ["Intensitätsfaktor", calendarIntensityFactor(actual.intensity)], ["Ø Puls", values["Ø Puls"]],
      ["Trittfrequenz", calendarRoundedNumber(actual.avg_cadence, " rpm")],
      ["Belastung", values.Belastung], ["RPE", values.RPE],
      ["Ø Tempo", calendarSpeedLabel(actual)],
      ["Höhenmeter", values.Höhenmeter],
    ];
  }
  return Object.entries(values);
}

// Each value once; duration and distance stay in the card's row.
function appendActualCalendarDetails(details, actual) {
  if (!actual) return;
  const facts = h("div", "planned-actual-facts");
  for (const [label, value] of actualCalendarFacts(actual)) appendCalendarFact(facts, label, value);
  if (facts.childElementCount) details.append(facts);
}

// One compact row: sport icon, title, sport/time/status line, duration and distance.
function plannedSessionHeader(entry, actual, title, appendStatus, slim = false) {
  const displayed = actual || entry;
  const sportLabel = activitySportLabel(calendarSportType(displayed));
  const icon = h("span", "planned-session-icon", CALENDAR_SPORT_ICONS[sportLabel] || "•");
  // A slim row's line has no sport word, so its icon names the sport.
  if (slim) {
    icon.setAttribute("role", "img");
    icon.setAttribute("aria-label", sportLabel);
  } else icon.setAttribute("aria-hidden", "true");
  // A done or missed unit's icon names the sport; its line keeps the time and the status.
  const line = h("span", { className: "planned-session-line", textContent: [slim ? null : sportLabel, actual ? calendarStartTime(actual.started_at_local) : plannedUnitStartTime(entry.starts_at_local)].filter(Boolean).join(" · ") });
  appendStatus(line);
  const shownDistance = actual ? actual.distance_m : entry.distance;
  const value = h("span", "planned-session-value",
    h("strong", null, plannedEntryDurationLabel(actual, entry) || "–"),
    shownDistance > 0 ? h("span", null, distanceLabel(shownDistance)) : null);
  return h("span", "planned-session-header", icon, h("strong", "planned-session-title", title), line, value);
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
  const svg = svgNode("svg", { viewBox: "0 0 300 56", role: "img", "aria-label": label, class: "calendar-workout-profile", preserveAspectRatio: "none" });
  svg.append(svgNode("title", {}, `${label} · ${axis === "distance" ? "Distanzachse" : "Zeitachse"} · ${profile.unit || ""}`));
  svg.append(svgNode("line", { x1: 0, x2: 300, y1: 54, y2: 54, class: "calendar-profile-baseline" }));
  let offset = 0;
  for (const item of segments) {
    const size = extent(item);
    if (!size) continue;
    const x = offset / total * 300, width = size / total * 300;
    offset += size;
    const shape = calendarProfileShape(item, x, width, top);
    if (!shape) continue;
    shape.append(svgNode("title", {}, `${axis === "distance" ? distanceLabel(size) : formatDuration(size)} · ${item.label || ""}`));
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
  return svgNode("polygon", { points: `${start},54 ${start},${left} ${end},${right} ${end},54`, "data-zone": zone });
}

// The detail view's larger profile with its axis from start to the whole duration or distance.
function plannedDetailProfile(profile) {
  const svg = calendarWorkoutProfile(profile);
  if (!svg) return null;
  svg.classList.add("is-detail");
  const total = profileExtent(profile);
  const end = profile.axis === "distance" ? distanceLabel(total) : AppFormat.duration(total);
  const axis = h("div", { className: "planned-detail-axis", "aria-hidden": "true" }, ["0", end].map((text) => h("span", null, text)));
  return h("div", "planned-detail-profile", svg, axis);
}

// Title, day and status of the selected unit; on wide screens it heads the detail pane.
function plannedDetailHead(entry, actual, title, dateKey, status, statusLabel, weather) {
  return h("div", "planned-detail-head",
    h("strong", "planned-detail-title", title),
    h("span", "planned-detail-line", [
      DETAIL_DATE_FORMAT.format(dateFromKey(dateKey)),
      actual ? calendarStartTime(actual.started_at_local) : plannedUnitStartTime(entry.starts_at_local),
      activitySportLabel(calendarSportType(actual || entry)),
      plannedWeatherLabel(weather),
    ].filter(Boolean).join(" · ")),
    // The library template the unit comes from (#2379).
    entry?.template_name ? h("span", "planned-detail-line planned-detail-template", `Vorlage: ${entry.template_name}`) : null,
    h("span", `planned-detail-status is-${status}`, statusLabel));
}

function plannedFocusForm(entry, dateKey) {
  const sport = focusSport(entry);
  if (!sport || !entry.local_id || entry.is_completed_activity) return null;
  const isSet = entry.focus_origin === "set";
  const form = h("div", "planned-focus-form");
  const focus = focusSelect("Art der Einheit", "session_focus", FOCUS_OPTIONS[sport].map((value) => [value, FOCUS_LABELS[value]]), isSet ? entry.session_focus : "");
  const parts = [focus];
  if (sport === "strength") parts.push(focusSelect("Intensität", "strength_intensity", Object.entries(STRENGTH_INTENSITY_LABELS), entry.intensity_origin === "set" ? entry.strength_intensity : ""));
  const statusKey = plannedEntryKey(entry, dateKey);
  const status = h("span", { className: "planned-focus-status", textContent: plannedFocusStatuses.get(statusKey) || "" });
  status.setAttribute("role", "status");
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
    const chip = h("button", { type: "button", className: "planned-suggestion-chip" }, `≈ ${labels[value]} übernehmen`);
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
  return { [ids.intervals]: Boolean(state.data?.configured?.[ids.intervals]), [ids.garmin]: Boolean(state.data?.garmin?.configured) && state.data.garmin.can_write_workouts !== false, [ids.wahoo]: Boolean(state.data?.wahoo?.connected) };
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
  const button = h("button", { type: "button", className: "secondary-button planned-sync-button planned-week-sync-button", "aria-label": `Woche ${planWeekLabel(weekKey)} synchronisieren` }, "Woche synchronisieren");
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
  const button = h("button", { type: "button", className: "secondary-button planned-conflict-button" }, "Mit Coach lösen");
  button.addEventListener("click", (event) => {
    // The button sits in the card summary; a click must not toggle the card.
    event.preventDefault();
    event.stopPropagation();
    const session = [activitySportLabel(calendarSportType(entry)), plannedEntryDurationLabel(null, entry)].filter(Boolean).join(", ");
    void globalThis.askCoach?.(`Die geplante Einheit am ${dateLabel(dateKey)} (${session}) kollidiert mit: ${labels.join(", ")}. Schlage eine Anpassung vor.`);
  });
  return h("span", "planned-conflict", h("span", null, `⚠ Konflikt: ${labels.join(" · ")}`), button);
}

// Why a strength or run unit cannot reach the watch, with the action that fixes it:
// the Coach structures a free-text unit; an unmatched exercise takes one of
// the catalogue suggestions or goes to the Coach.
function plannedGarminBlocked(entry, dateKey, todayKey, actual) {
  const reason = entry.push_blocked?.[providerIds().garmin] || (plannedGarminSdkRequired(entry, state.data?.garmin) ? "sdk_required" : "");
  if (!reason || actual || dateKey < todayKey || !entry.local_id || entry.is_completed_activity) return null;
  const block = h("span", "planned-conflict planned-garmin-blocked");
  const unit = `„${entry.name || "Krafteinheit"}“ am ${dateLabel(dateKey)}`;
  if (reason === "sdk_required") {
    block.append(h("span", null, "Garmin-Anmeldung nötig"));
    return block;
  }
  if (reason !== "unmapped") {
    block.append(h("span", null, plannedGarminBlockedText(entry)), plannedCoachButton("Mit Coach strukturieren", `Strukturiere die Krafteinheit ${unit} für die Uhr: Übungen in Reihenfolge mit Sätzen, Wiederholungen, Last und Garmin-Übung. Frag nach, was fehlt.`));
    return block;
  }
  const unmapped = Array.isArray(entry.push_unmapped) ? entry.push_unmapped : [];
  block.append(...unmapped.map((exercise) => plannedUnmappedExercise(entry, exercise, unit)));
  return block.childElementCount ? block : null;
}

// One unmatched exercise: its catalogue suggestions, each a one-tap pick
// that is remembered for the exercise name, and "Andere…" for the Coach.
function plannedUnmappedExercise(entry, exercise, unit) {
  const row = h("span", "planned-garmin-exercise", h("span", null, `Keine Garmin-Übung: ${exercise.name}`));
  for (const suggestion of Array.isArray(exercise.suggestions) ? exercise.suggestions : []) {
    const chip = h("button", { type: "button", className: "planned-suggestion-chip" }, suggestion);
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

// "Details" opens the session's charts, zones, laps and all values in the card (#2258);
// the Coach analyses it in one athlete-started turn; "Feedback" opens the rating and session dialog.
// The Coach message names the session by date, sport, time, duration and its local id; the stored
// name never becomes Coach input.
function plannedActivityActions(actual, dateKey, title, entryKey) {
  const panel = h("div", "activity-analysis-panel");
  const more = h("details", "planned-activity-more", h("summary", null, "Details"), panel);
  // A re-render (sync, reload) keeps an opened "Details" open and loads it again.
  more.addEventListener("toggle", () => {
    if (entryKey && more.open) openActivityDetails.add(entryKey);
    else if (entryKey) openActivityDetails.delete(entryKey);
    if (more.open && !panel.childElementCount) void globalThis.ActivityAnalysis.loadPanel(panel, actual, id && ((fresh) => plannedSessionRead(id, fresh)));
  });
  const id = String(actual.activity_id || actual.id || "");
  more.open = Boolean(entryKey && openActivityDetails.has(entryKey));
  const prompt = `Analysiere meine Einheit vom ${dateLabel(dateKey)} (${[
    activitySportLabel(calendarSportType(actual)),
    calendarStartTime(actual.started_at_local),
    plannedEntryDurationLabel(actual, actual),
    /^[\w:.-]{1,80}$/.test(id) ? `ID ${id}` : null,
  ].filter(Boolean).join(", ")}).`;
  const coach = plannedCoachButton("Mit dem Coach analysieren", prompt, "secondary-button", "session_analysis");
  const feedback = h("button", { type: "button", className: "secondary-button planned-activity-feedback" }, "Feedback");
  feedback.addEventListener("click", () => globalThis.ActivityDetails.open({ ...actual, name: title }, { api, showDialog: showAccessibleDialog }));
  return [more, h("div", "planned-activity-actions", coach, feedback)];
}

// "Verschieben" (#2194): the next seven days from today with the unit's own day dimmed, and "…" for a
// later date. One tap moves the local unit; its open card follows it to the new week with the receipt.
function plannedUnitActions(entry, dateKey, todayKey) {
  if (!entry.local_id || entry.is_completed_activity) return [];
  const coach = plannedDiscussButton(entry, dateKey);
  if (!entry.payload_hash) return [h("div", "planned-activity-actions", coach)];
  const key = plannedEntryKey(entry, dateKey);
  const toggle = h("button", { type: "button", className: "secondary-button", "aria-expanded": "false" }, "Verschieben");
  const days = h("div", { className: "planned-move-days", role: "group", "aria-label": "Neuer Tag", hidden: true });
  const status = h("p", { className: "planned-move-status", role: "status" });
  toggle.addEventListener("click", () => {
    days.hidden = !days.hidden;
    toggle.setAttribute("aria-expanded", String(!days.hidden));
  });
  const move = async (target) => {
    if (!target || target === dateKey || (plannedLastDateKey && target > plannedLastDateKey)) return;
    const buttons = [...days.querySelectorAll("button, input")];
    buttons.forEach((item) => { item.disabled = true; });
    status.replaceChildren();
    try {
      const result = await api(`/api/planned-units/${encodeURIComponent(entry.local_id)}/date`, { method: "POST", body: JSON.stringify({ date: target, expected_payload_hash: entry.payload_hash }) });
      plannedMoveReceipts.set(key, { text: `Verschoben auf ${MOVE_DAY_FORMAT.format(dateFromKey(target))}`, change: result.change, from: dateKey });
      showPlannedDay(target);
      await globalThis.load?.();
      announcePlanChange(`Verschoben auf ${MOVE_DAY_FORMAT.format(dateFromKey(target))}`);
    } catch (error) {
      buttons.forEach((item) => { item.disabled = item.dataset.day === dateKey; });
      status.textContent = error.message;
    }
  };
  for (let offset = 0; offset < 7; offset += 1) {
    const day = addDateKey(todayKey, offset);
    if (plannedLastDateKey && day > plannedLastDateKey) break;
    const date = dateFromKey(day);
    const button = h("button", { type: "button", className: "planned-move-day", disabled: day === dateKey, dataset: { day }, "aria-label": DETAIL_DATE_FORMAT.format(date) },
      h("span", null, MOVE_WEEKDAY_FORMAT.format(date)), h("b", null, String(date.getDate())));
    button.addEventListener("click", () => void move(day));
    days.append(button);
  }
  // The system date picker opens from "…"; without showPicker the field itself is shown.
  const picker = h("input", { type: "date", className: "planned-move-picker", min: todayKey, max: plannedLastDateKey || null, tabIndex: -1, "aria-label": "Anderes Datum" });
  picker.addEventListener("change", () => void move(picker.value));
  const later = h("button", { type: "button", className: "planned-move-day", "aria-label": "Anderes Datum" }, "…");
  later.addEventListener("click", () => {
    try { picker.showPicker(); } catch { picker.classList.add("is-shown"); picker.tabIndex = 0; picker.focus(); }
  });
  days.append(later, picker);
  const receipt = plannedMoveReceipts.get(key);
  if (receipt) status.append(receipt.text, ...(receipt.change?.id ? plannedMoveUndo(key, receipt, status) : []));
  return [h("div", "planned-activity-actions", toggle, coach), days, status];
}

// "Mit dem Coach besprechen" (#2193) opens the Coach with the unit named by date, sport, start, duration and
// local id in the message field; the athlete adds the question and sends it. The stored name is never Coach input.
function plannedDiscussButton(entry, dateKey) {
  const id = String(entry.local_id);
  const reference = [
    activitySportLabel(calendarSportType(entry)),
    plannedUnitStartTime(entry.starts_at_local),
    plannedEntryDurationLabel(null, entry),
    /^[\w:.-]{1,80}$/.test(id) ? `ID ${id}` : null,
  ].filter(Boolean).join(", ");
  const button = h("button", { type: "button", className: "secondary-button" }, "Mit dem Coach besprechen");
  button.addEventListener("click", () => void globalThis.askCoach?.(`Zur geplanten Einheit am ${dateLabel(dateKey)} (${reference}): `, { send: false }));
  return button;
}

// "Rückgängig" puts the unit back on its earlier day and shows that week again.
function plannedMoveUndo(key, receipt, status) {
  const undo = h("button", { type: "button", className: "message-undo" }, "Rückgängig");
  undo.addEventListener("click", async () => {
    undo.disabled = true;
    try {
      await api("/api/change-history/undo", { method: "POST", body: JSON.stringify({ change_id: receipt.change.id, expected_current_hash: receipt.change.after_hash }) });
      plannedMoveReceipts.set(key, { text: "Zurückgenommen." });
      showPlannedDay(receipt.from);
      await globalThis.load?.();
    } catch (error) {
      undo.disabled = false;
      status.firstChild.textContent = `${error.message} `;
    }
  });
  return [" ", undo];
}

function showPlannedDay(dateKey) {
  selectedWeekKey = planWeekStart(dateKey);
  if (calendarView === "month") selectedDayKey = dateKey;
}

// One slim bar of the session's time per zone with every zone's minutes below and the zone kind and source:
// rides use power zones when they have them, every other sport heart-rate zones. No zones, no bar.
async function appendPlannedZoneTime(details, activityId, ride) {
  const box = h("div", "planned-zone-time");
  const facts = details.querySelector(".planned-actual-facts");
  if (facts) facts.after(box);
  else details.querySelector(":scope > .planned-activity-more")?.before(box);
  if (!box.isConnected) details.append(box);
  let zones;
  try {
    zones = (await plannedSessionRead(activityId))?.zones;
  } catch {
    box.remove();
    return;
  }
  const power = ride && plannedZoneBuckets(zones?.power).some((item) => item.seconds > 0) ? zones.power : null;
  const zone = power || zones?.heart_rate;
  const buckets = plannedZoneBuckets(zone);
  if (!buckets.some((item) => item.seconds > 0)) {
    box.remove();
    return;
  }
  const kind = power ? "Leistungszonen" : "HF-Zonen";
  const minutes = (seconds) => `${Math.round(seconds / 60)}′`;
  const spoken = buckets.map((item) => `${item.name} ${Math.round(item.seconds / 60)} min`).join(", ");
  const bar = h("div", { className: "planned-zone-time-bar", role: "img", "aria-label": `Zeit in ${kind}: ${spoken}` },
    buckets.filter((item) => item.seconds > 0).map((item) => {
      const part = h("i", { dataset: { zone: item.zone } });
      part.style.setProperty("flex-grow", String(item.seconds));
      return part;
    }));
  const legend = h("div", { className: "planned-zone-time-legend", "aria-hidden": "true" }, buckets.map((item) => h("span", null, `${item.name} ${minutes(item.seconds)}`)));
  box.append(bar, legend, h("p", "planned-zone-time-source", [kind, zone.source?.label].filter(Boolean).join(" · ")));
}

function plannedZoneBuckets(zone) {
  return (zone?.buckets || [])
    .filter((bucket) => Number.isFinite(bucket.seconds) && bucket.seconds >= 0)
    .map((bucket) => {
      const name = String(bucket.label || `Z${bucket.index}`).slice(0, 12);
      return { name, seconds: bucket.seconds, zone: /^Z(\d)/.exec(name)?.[1] || "" };
    });
}

// Built when the card first opens, as most cards never are: the larger profile and, for a session,
// the time in zones from the session read of "Details" (#2195).
function appendOpenedPlannedParts(details, head, entry, actual) {
  if (!details.querySelector(".planned-detail-profile")) {
    const detailProfile = plannedDetailProfile(actual?.workout_profile || entry.workout_profile);
    if (detailProfile) head.after(detailProfile);
  }
  const activityId = actual ? String(actual.activity_id || actual.id || "") : "";
  if (activityId && !details.querySelector(".planned-zone-time")) {
    void appendPlannedZoneTime(details, activityId, ["Radfahren", "Rad indoor"].includes(activitySportLabel(calendarSportType(actual))));
  }
}

// A planned unit's body: its load, its steps (#2447) and its actions; returns the step list, if any.
function appendPlannedUnitBody(details, entry, dateKey, todayKey) {
  const metrics = plannedSessionMetrics(entry);
  if (metrics) details.append(metrics);
  const steps = plannedStepList(entry.workout_profile);
  if (steps) details.append(steps);
  details.append(...plannedUnitActions(entry, dateKey, todayKey));
  return steps;
}

function renderPlannedEntry(entry, dateKey, todayKey, dayContext = {}, weekHasPlan = true) {
  const actual = calendarActualActivity(entry);
  const baseStatus = calendarEntryStatus(entry, dateKey, todayKey);
  const restDayLabel = baseStatus === "missed" ? plannedDayStatusLabel(dayContext.day_status) : null;
  const status = restDayLabel ? "skipped" : baseStatus;
  // One open card at a time: on wide screens its body is the detail pane beside the week.
  const card = h("details", { className: `planned-entry is-${status}`, name: "planned-entry" });
  const entryKey = plannedEntryKey(entry, dateKey);
  if (entryKey) card.dataset.entryKey = entryKey;
  card.open = openPlannedEntries.has(entryKey);
  const displayed = actual || entry;
  card.dataset.sport = activitySportLabel(calendarSportType(displayed));
  const meta = h("span", "planned-meta", [
    activitySportLabel(calendarSportType(displayed)),
    actual ? calendarStartTime(actual.started_at_local) : plannedUnitStartTime(entry.starts_at_local),
    plannedEntryDurationLabel(actual, entry),
  ].filter(Boolean).join(" · "));
  const title = (actual?.name ? calendarDisplayName(actual.name, state.data?.profile?.weather_location) : entry.name) || "Trainingseinheit";
  // Done and missed units are one slim row; only units still to come keep the zone bar and chips.
  const slim = ["completed", "missed", "skipped"].includes(status);
  // The sport line carries the chips and, only for a unit still to send, a compact sync button.
  const cardSummary = h("summary", null,
    plannedSessionHeader(entry, actual, title, (line) => {
      appendPlannedEntryStatus(line, entry, status, restDayLabel, dateKey, todayKey, weekHasPlan);
      if (!slim) appendFocusChip(line, entry);
    }, slim),
    meta,
    slim ? null : calendarWorkoutProfile(entry.workout_profile),
    plannedConflict(entry, dateKey),
    plannedGarminBlocked(entry, dateKey, todayKey, actual));
  const head = plannedDetailHead(entry, actual, title, dateKey, status, plannedDetailStatus(entry, dateKey, todayKey, restDayLabel, weekHasPlan), plannedDayWeather(dayContext, dateKey));
  const details = h("div", "planned-entry-details", head);
  card.addEventListener("toggle", () => {
    if (card.open) appendOpenedPlannedParts(details, head, entry, actual);
  });
  const steps = actual ? null : appendPlannedUnitBody(details, entry, dateKey, todayKey);
  appendActualCalendarDetails(details, actual);
  if (actual && (actual.id || actual.activity_id)) details.append(...plannedActivityActions(actual, dateKey, title, entryKey));
  appendPlannedCalendarComparison(details, entry, actual);
  const focusForm = plannedFocusForm(entry, dateKey);
  if (focusForm) details.append(focusForm);
  // With the step list, the description keeps only its free text; the stored text is unchanged (#2447).
  appendPlannedDescription(details, steps ? plannedDescriptionText(entry.description) : entry.description);
  card.append(cardSummary, details);
  return card;
}

// Personal calendar events (#2620): a band of chips above the day's units. Event text is untrusted
// and only ever set as text. The decision is local; it changes planning, never a remote calendar.
const EVENT_IMPACT_LABELS = new Map([["block", "Blockiert"], ["short", "Kürzer"], ["easy", "Locker"], ["none", "Egal"], ["open", "Offen"]]);
const EVENT_DECISIONS = ["block", "short", "easy", "none"];

// The local days an event covers, from its start day to the day of its last minute.
function plannedEventDays(event) {
  const start = String(event?.start_local || event?.event_date || "").slice(0, 10);
  const end = String(event?.end_local || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) return [];
  const endsAtMidnight = /T00:00(?::00)?/.test(end.slice(10, 19));
  let last = /^\d{4}-\d{2}-\d{2}/.test(end) ? end.slice(0, 10) : start;
  if (endsAtMidnight && last > start) last = addDateKey(last, -1);
  const days = [];
  for (let day = start; day <= last && days.length < 60; day = addDateKey(day, 1)) days.push(day);
  return days;
}

function plannedEventsByDate(todayKey) {
  const events = Array.isArray(state.data?.external_calendar?.events) ? state.data.external_calendar.events : [];
  const byDate = new Map();
  for (const event of events) {
    if (!event?.uid) continue;
    for (const day of plannedEventDays(event)) {
      if (day < todayKey) continue;
      if (!byDate.has(day)) byDate.set(day, []);
      byDate.get(day).push(event);
    }
  }
  return byDate;
}

function plannedNoteContext(dayContext, dayEvents) {
  if (!dayEvents.length) return dayContext;
  const shown = new Set(dayEvents.map((event) => `${event.name}|${event.start_local}`));
  const appointments = (Array.isArray(dayContext.appointments) ? dayContext.appointments : [])
    .filter((item) => !shown.has(`${item?.name}|${item?.start_local}`));
  const flag = (key) => appointments.some((item) => item?.[key]);
  return { ...dayContext, appointments, no_training: flag("no_training"), no_intensity: flag("no_intensity"), short_only: flag("short_only") };
}

function plannedEventTime(event) {
  if (event.all_day) return "ganztägig";
  const time = (value) => /(?:T|\s)(\d{2}:\d{2})/.exec(String(value || ""))?.[1] || "";
  return [time(event.start_local), time(event.end_local)].filter(Boolean).join("–");
}

function plannedEventImpact(event) {
  return EVENT_IMPACT_LABELS.has(event.impact) ? event.impact : "open";
}

function plannedEventBand(events) {
  const band = h("div", { className: "planned-event-band", "aria-label": "Termine" });
  band.setAttribute("role", "group");
  for (const event of events) {
    const impact = plannedEventImpact(event);
    const name = stripCalendarMarkers(event.name) || "Termin";
    const time = plannedEventTime(event);
    const chip = h("button", {
      type: "button", className: "planned-event-chip", dataset: { impact, uid: event.uid, start: event.start_local || "" },
      "aria-label": [name, time, EVENT_IMPACT_LABELS.get(impact)].filter(Boolean).join(", "),
    }, impact === "open" ? h("span", { className: "planned-event-dot", "aria-hidden": "true" }) : null,
    time ? h("small", null, time) : null, h("span", "planned-event-name", name));
    chip.addEventListener("click", () => openPlannedEventSheet(event));
    band.append(chip);
  }
  return band;
}

// One sheet for every event: a bottom sheet on phones, a side panel on wide screens (styles.css).
function openPlannedEventSheet(event, { queue = false } = {}) {
  const previous = document.querySelector(".planned-event-sheet");
  previous?.close();
  previous?.remove();
  const name = stripCalendarMarkers(event.name) || "Termin";
  const dateLabel = DETAIL_DATE_FORMAT.format(dateFromKey(String(event.start_local || event.event_date).slice(0, 10)));
  const dialog = h("dialog", { className: "planned-event-sheet", "aria-labelledby": "plannedEventTitle" });
  const close = h("button", { type: "button", className: "icon-button planned-event-close", "aria-label": "Schließen" }, "✕");
  close.addEventListener("click", () => { if (!dialog.dataset.pending) dialog.close(); });
  dialog.addEventListener("cancel", (cancel) => { if (dialog.dataset.pending) cancel.preventDefault(); });
  let series = Boolean(event.recurring) && event.decision_scope !== "event";
  const scope = event.recurring ? h("div", { className: "planned-event-scope", "aria-label": "Gilt für" }) : null;
  const status = h("p", "planned-event-status");
  status.setAttribute("role", "status");
  const choices = h("div", { className: "planned-event-choices", "aria-label": "Einordnung" });
  choices.setAttribute("role", "group");
  const current = event.decision_scope ? plannedEventImpact(event) : "";
  for (const impact of EVENT_DECISIONS) {
    const button = h("button", { type: "button", dataset: { impact }, "aria-pressed": String(impact === current) }, EVENT_IMPACT_LABELS.get(impact));
    button.addEventListener("click", () => decidePlannedEvent(event, impact, series, dialog, status, queue));
    choices.append(button);
  }
  if (scope) {
    scope.setAttribute("role", "group");
    for (const [value, label] of [[false, "Nur dieser Termin"], [true, "Alle Wiederholungen"]]) {
      const button = h("button", { type: "button", "aria-pressed": String(series === value) }, label);
      button.addEventListener("click", () => {
        series = value;
        for (const item of scope.children) item.setAttribute("aria-pressed", String(item === button));
      });
      scope.append(button);
    }
  }
  dialog.append(...[h("div", "planned-event-head", h("h3", { id: "plannedEventTitle" }, name), close),
    h("p", "planned-event-meta", [dateLabel, plannedEventTime(event)].filter(Boolean).join(" · ")), choices, scope, status].filter(Boolean));
  dialog.addEventListener("click", (click) => {
    const box = dialog.getBoundingClientRect();
    const outside = click.clientX < box.left || click.clientX > box.right || click.clientY < box.top || click.clientY > box.bottom;
    if (click.target === dialog && outside && !dialog.dataset.pending) dialog.close();
  });
  dialog.addEventListener("close", () => { dialog.remove(); restoreDialogFocus(dialog); }, { once: true });
  document.body.append(dialog);
  showAccessibleDialog(dialog, choices.querySelector("[aria-pressed='true']") || choices.firstElementChild);
}

// The notice (#2621) covers events without a decision from today through 14 days ahead; the
// server count is the source; the decision response carries the new count.
const UNDECIDED_NOTICE_DAYS = 14;

function undecidedPlannedEvents() {
  const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
  const lastKey = addDateKey(todayKey, UNDECIDED_NOTICE_DAYS);
  const events = Array.isArray(state.data?.external_calendar?.events) ? state.data.external_calendar.events : [];
  return events.filter((event) => event?.uid && plannedEventImpact(event) === "open"
    && String(event.start_local || "").slice(0, 10) <= lastKey && String(event.end_local || event.start_local || "") > `${todayKey}T00:00:00`);
}

function undecidedPlannedCount() {
  const count = Number(state.data?.external_calendar?.undecided_upcoming);
  return Number.isFinite(count) && count > 0 ? count : 0;
}

function undecidedNoticeText(count) {
  const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
  const until = new Intl.DateTimeFormat("de-DE", { day: "2-digit", month: "2-digit" }).format(dateFromKey(addDateKey(todayKey, UNDECIDED_NOTICE_DAYS)));
  return `${count} ${count === 1 ? "neuer Termin" : "neue Termine"} bis ${until}`;
}

function plannedUndecidedBanner() {
  const count = undecidedPlannedCount();
  const first = undecidedPlannedEvents()[0];
  if (!count) return null;
  const action = first ? h("button", { type: "button" }, "Einordnen") : null;
  action?.addEventListener("click", () => openPlannedEventSheet(first, { queue: true }));
  return h("div", "planned-undecided-banner", h("span", { className: "planned-event-dot", "aria-hidden": "true" }), h("span", null, undecidedNoticeText(count)), action);
}

// The Kalender navigation items carry the same count.
function renderUndecidedNavCount() {
  const count = undecidedPlannedCount();
  for (const link of document.querySelectorAll('.nav-item[data-route="plan"]')) {
    let badge = link.querySelector("b.nav-count");
    if (!badge) {
      badge = h("b", { className: "nav-count", "aria-hidden": "true" });
      link.append(badge);
    }
    badge.textContent = count ? String(count) : "";
    link.setAttribute("aria-label", count ? `Kalender, ${undecidedNoticeText(count)}` : "Kalender");
  }
}

async function decidePlannedEvent(event, impact, series, dialog, status, queue = false) {
  const choices = [...dialog.querySelectorAll(".planned-event-choices button")];
  if (choices.some((button) => button.disabled)) return;
  let result;
  status.textContent = "";
  choices.forEach((button) => { button.disabled = true; });
  dialog.dataset.pending = "true";
  try {
    result = await api("/api/external-calendar/decisions", {
      method: "POST",
      body: JSON.stringify({ uid: event.uid, occurrence_start: series ? null : event.start_local, impact }),
    });
  } catch (error) {
    status.textContent = error.message;
    choices.forEach((button) => { button.disabled = false; });
    return;
  } finally {
    delete dialog.dataset.pending;
  }
  scheduleStateEventRefresh(["plan"]);
  for (const item of state.data?.external_calendar?.events || []) {
    if (item.uid !== event.uid || (!series && item.start_local !== event.start_local)) continue;
    Object.assign(item, { impact, decision_scope: series ? "series" : "event" });
  }
  state.data.external_calendar.undecided_upcoming = Math.max(0, Number(result?.undecided_upcoming) || 0);
  dialog.close();
  renderPlanned(renderedCalendar);
  renderUndecidedNavCount();
  const next = queue ? undecidedPlannedEvents()[0] : null;
  if (next && undecidedPlannedCount()) {
    openPlannedEventSheet(next, { queue: true });
    return;
  }
  $("#plannedCalendar")?.querySelector(`.planned-event-chip[data-uid="${CSS.escape(event.uid)}"][data-start="${CSS.escape(event.start_local || "")}"]`)?.focus();
}

function plannedDayWeather(dayContext, dateKey) {
  if (dayContext.weather) return dayContext.weather;
  const days = state.data?.weather?.days;
  return Array.isArray(days) ? days.find((item) => item?.date === dateKey) : null;
}

// The timeline's date column: weekday over the day of the month; today's day is filled.
function plannedDayDate(day, dateKey) {
  const date = dateFromKey(dateKey);
  const title = h("h5", { className: "planned-day-date", id: `planned-day-${dateKey}` },
    h("span", null, new Intl.DateTimeFormat("de-DE", { weekday: "short" }).format(date)),
    h("time", { dateTime: dateKey }, String(date.getDate())));
  day.setAttribute("aria-labelledby", title.id);
  return title;
}

// "Heute", the weather and its flags above the day's units; none when nothing applies.
function plannedDayHeading(weather, dateKey, todayKey) {
  const heading = h("div", "planned-day-heading", dateKey === todayKey ? h("span", "planned-today-label", "Heute") : null);
  const weatherLabel = plannedWeatherLabel(weather);
  if (weatherLabel) {
    const title = [...plannedWeatherDetails(weather), weatherLabel].join("\n");
    heading.append(h("span", { className: "planned-day-weather", title, "aria-label": title.replaceAll("\n", ". ") }, weatherLabel));
    for (const flag of plannedWeatherFlags(weather)) heading.append(h("span", { className: "planned-day-flag", "aria-label": flag.label }, flag.text));
  }
  return heading.childElementCount ? heading : null;
}

function renderPlannedGroup(entries, dateKey, todayKey, dayContext, weekHasPlan) {
  const first = entries[0];
  return h("details", { className: "planned-group", dataset: { sport: activitySportLabel(calendarSportType(first)) } },
    h("summary", null, plannedSessionHeader(first, first, `${entries.length}× ${calendarDisplayName(first.name, state.data?.profile?.weather_location) || "Trainingseinheit"}`, () => {}, true)),
    h("div", "planned-group-items", entries.map((entry) => renderPlannedEntry(entry, dateKey, todayKey, dayContext, weekHasPlan))));
}

function renderPlannedDay(view, dateKey, weekHasPlan) {
  const { eventsByDate, planningContextByDate, todayKey } = view;
  const dayEntries = eventsByDate.get(dateKey) || [];
  const dayContext = planningContextByDate.get(dateKey) || {};
  const dayEvents = view.calendarEventsByDate?.get(dateKey) || [];
  const day = h("section", { className: `planned-day${dateKey === todayKey ? " is-today" : ""}`, dataset: { date: dateKey } });
  const heading = plannedDayHeading(plannedDayWeather(dayContext, dateKey), dateKey, todayKey);
  // The band names the day's events and their impact, so the calendar note line leaves them out.
  const noteContext = plannedNoteContext(dayContext, dayEvents);
  const notes = plannedDayNotes(noteContext, state.data?.competitions, dateKey);
  const emptyText = dateKey < todayKey ? "Keine Aktivität" : "Keine Einheit geplant";
  const content = h("div", "planned-day-content", heading, notes.childElementCount ? notes : null,
    dayEvents.length ? plannedEventBand(dayEvents) : null,
    dayEntries.length ? null : h("p", "planned-day-empty", emptyText));
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
  const group = h("div", { className: "planned-view-switch", "aria-label": "Ansicht" });
  group.setAttribute("role", "group");
  for (const [value, label] of [["week", "Woche"], ["month", "Monat"]]) {
    const button = h("button", { type: "button", dataset: { view: value }, "aria-pressed": String(calendarView === value) }, label);
    button.addEventListener("click", () => {
      if (calendarView === value) return;
      // The athlete's choice wins over a still pending jump to today.
      state.plannedTodayFocusPending = false;
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

// In the month view the selected day also sets the week shown below (renderPlanned).
function selectPlannedDay(dateKey) {
  selectedDayKey = dateKey;
  renderPlanned(renderedCalendar);
}

// One day of the month grid: its number and one mark per unit (a dot, on wide screens its duration).
function plannedMonthDay(view, dateKey, monthKey) {
  const { eventsByDate, firstWeekKey, lastDateKey, planningContextByDate, todayKey } = view;
  const entries = eventsByDate.get(dateKey) || [];
  const dayContext = planningContextByDate.get(dateKey) || {};
  const button = h("button", { type: "button", className: "planned-month-day", dataset: { date: dateKey }, "aria-pressed": String(dateKey === view.dayKey), disabled: dateKey < firstWeekKey || dateKey > lastDateKey });
  button.classList.toggle("is-outside", dateKey.slice(0, 7) !== monthKey.slice(0, 7));
  button.classList.toggle("is-today", dateKey === todayKey);
  const number = h("span", "planned-month-number", String(dateFromKey(dateKey).getDate()));
  const marks = h("span", "planned-month-marks");
  for (const entry of entries) {
    const actual = calendarActualActivity(entry);
    const status = calendarEntryStatus(entry, dateKey, todayKey);
    const seconds = actual ? Number(AppFormat.sessionSeconds(actual)) : plannedDurationSeconds(entry);
    // As on the card: a missed unit on a rest or pause day counts as skipped.
    // h:mm fits a day cell; the full label stays on the card.
    marks.append(h("span", {
      className: `planned-month-mark is-${status === "missed" && plannedDayStatusLabel(dayContext.day_status) ? "skipped" : status}`,
      dataset: { sport: activitySportLabel(calendarSportType(actual || entry)) },
    }, seconds >= 30 ? calendarClock(seconds) : "•"));
  }
  button.append(number, marks);
  const blocked = (view.calendarEventsByDate?.get(dateKey) || []).some((event) => event.impact === "block");
  button.classList.toggle("has-blocked-event", blocked);
  const units = entries.length ? countLabel(entries.length, "Einheit", "Einheiten") : "keine Einheit";
  button.setAttribute("aria-label", `${DETAIL_DATE_FORMAT.format(dateFromKey(dateKey))}: ${units}${blocked ? ", Termin blockiert Training" : ""}`);
  button.addEventListener("click", () => {
    state.plannedTodayFocusPending = false;
    selectPlannedDay(dateKey);
    const root = $("#plannedCalendar");
    root?.querySelector(`.planned-month-day[data-date="${dateKey}"]`)?.focus();
    if (!wideCalendar?.matches) return;
    const card = root?.querySelector(`.planned-day[data-date="${dateKey}"] .planned-entry`);
    const group = card?.closest(".planned-group");
    if (group) group.open = true;
    if (card) card.open = true;
    else {
      const shown = shownPlannedEntry(root);
      if (shown) shown.open = false;
    }
  });
  return button;
}

// The month of the selected day: weeks Monday to Sunday with the ISO week and its planned time.
function renderPlannedMonth(view) {
  const { firstWeekKey, lastDateKey, todayKey } = view;
  const monthKey = monthStartKey(view.dayKey);
  const nextMonthKey = monthStartKey(monthKey, 1);
  const month = h("section", { className: "planned-month", "aria-labelledby": "plannedMonthTitle" });
  const title = h("h4", { id: "plannedMonthTitle" }, new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" }).format(dateFromKey(monthKey)));
  // A month step selects today when it lies in that month, else the month's first loaded day.
  const stepTo = (key) => (todayKey.startsWith(key.slice(0, 7)) ? todayKey : [key, firstWeekKey].sort((left, right) => left.localeCompare(right)).at(-1));
  const heading = h("header", "planned-week-heading", title,
    plannedStep(-1, "Vorheriger Monat", addDateKey(monthKey, -1) >= firstWeekKey ? () => selectPlannedDay(stepTo(monthStartKey(monthKey, -1))) : null, "month"),
    plannedStep(1, "Nächster Monat", nextMonthKey <= lastDateKey ? () => selectPlannedDay(stepTo(nextMonthKey)) : null, "month"),
    plannedViewSwitch());
  const names = h("div", { className: "planned-month-row planned-month-names", "aria-hidden": "true" }, ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So", "KW"].map((name) => h("span", null, name)));
  const grid = h("div", "planned-month-grid", names);
  for (let weekKey = planWeekStart(monthKey); weekKey < nextMonthKey; weekKey = addDateKey(weekKey, 7)) grid.append(plannedMonthRow(view, weekKey, monthKey));
  month.append(heading, grid);
  return month;
}

// One week of the month grid: seven days, then the ISO week with its planned time.
function plannedMonthRow(view, weekKey, monthKey) {
  const row = h("div", `planned-month-row${weekKey === planWeekStart(view.todayKey) ? " is-current" : ""}`);
  for (let offset = 0; offset < 7; offset += 1) row.append(plannedMonthDay(view, addDateKey(weekKey, offset), monthKey));
  const seconds = Array.from({ length: 7 }, (_, offset) => view.eventsByDate.get(addDateKey(weekKey, offset)) || []).flat()
    .filter((entry) => !entry.is_completed_activity)
    .reduce((total, entry) => total + plannedDurationSeconds(entry), 0);
  row.append(h("span", "planned-month-kw", [`KW ${isoWeekNumber(weekKey)}`, seconds > 0 ? calendarHours(seconds) : ""].filter(Boolean).join(" · ")));
  return row;
}

// A step button; after the step, focus stays on it or on the other one of its pair.
function plannedStep(step, label, onStep, pair) {
  const button = h("button", { type: "button", className: "icon-button planned-week-step", dataset: { step: String(step), pair }, "aria-label": label, disabled: !onStep }, step < 0 ? "\u2039" : "\u203a");
  button.addEventListener("click", () => {
    state.plannedTodayFocusPending = false;
    onStep();
    const steps = [...($("#plannedCalendar")?.querySelectorAll(`.planned-week-step[data-pair="${pair}"]:not(:disabled)`) || [])];
    (steps.find((item) => item.dataset.step === String(step)) || steps[0])?.focus();
  });
  return button;
}

function plannedWeekStep(step, target) {
  const button = plannedStep(step, step < 0 ? "Vorherige Woche" : "Nächste Woche", target ? () => {
    selectedWeekKey = target;
    if (calendarView === "month") selectedDayKey = target;
    renderPlanned(renderedCalendar);
  } : null, "week");
  button.dataset.weekStep = String(step);
  return button;
}


function renderPlannedWeek(view) {
  const { eventsByDate, firstWeekKey, lastWeekKey, todayKey, weekKey, weeklyCompliance } = view;
  const weekEndKey = addDateKey(weekKey, 6);
  const weekEntries = Array.from({ length: 7 }, (_, offset) => eventsByDate.get(addDateKey(weekKey, offset)) || []).flat();
  const week = h("section", { className: "planned-week", dataset: { weekKey }, "aria-labelledby": "plannedWeekTitle" });
  const heading = h("header", "planned-week-heading",
    h("h4", { id: "plannedWeekTitle" }, planWeekLabel(weekKey)),
    h("span", "planned-week-number", `KW ${isoWeekNumber(weekKey)}`),
    plannedWeekStep(-1, weekKey > firstWeekKey ? addDateKey(weekKey, -7) : ""),
    plannedWeekStep(1, weekKey < lastWeekKey ? addDateKey(weekKey, 7) : ""),
    calendarView === "week" ? plannedViewSwitch() : null,
    h("span", "planned-week-summary", calendarCountLabel(weekEntries, todayKey) || "Keine Einheiten"));
  const planned = weekEntries.filter((entry) => !entry.is_completed_activity);
  const actual = weekEntries.map(calendarActualActivity).filter(Boolean);
  const totals = plannedWeekMetrics(planned, actual);
  if (totals) heading.append(totals);
  const syncButton = plannedWeekSyncButton(weekKey, weekEntries, view.leftoversByWeek?.get(weekKey), todayKey);
  if (syncButton) heading.append(h("div", "planned-week-sync", syncButton));
  week.append(heading);
  const days = h("div", "planned-week-days");
  for (let offset = 0; offset < 7; offset += 1) days.append(renderPlannedDay(view, addDateKey(weekKey, offset), planned.length > 0));
  week.append(days);
  const legend = plannedZoneLegend(days);
  if (legend) week.append(legend);
  if (weekEntries.length) {
    const additionalCompleted = weekEntries.filter((entry) => entry.is_completed_activity).length;
    const summary = plannedWeekSummary(weekKey, weekEndKey, weekEntries, weeklyCompliance.get(weekKey), todayKey);
    week.append(h("p", "planned-week-totals", additionalCompleted && planned.length ? `${summary} · +${additionalCompleted} zusätzlich` : summary));
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
// The last day the calendar shows; a move stays inside it, so the moved card and its receipt stay visible.
let plannedLastDateKey = "";

// Keeps the shown week (and in the month view the selected day, which sets the week) inside the loaded weeks.
// The past has no limit: older weeks stay selectable and their sessions load on demand (#2258).
function keepPlannedSelection(todayKey, lastKey) {
  const currentWeekKey = planWeekStart(todayKey);
  if (!selectedWeekKey || selectedWeekKey > lastKey) selectedWeekKey = currentWeekKey;
  if (calendarView !== "month") return;
  if (!selectedDayKey || selectedDayKey > lastKey) selectedDayKey = selectedWeekKey === currentWeekKey ? todayKey : selectedWeekKey;
  selectedWeekKey = planWeekStart(selectedDayKey);
}

// Sessions older than the loaded calendar data come page by page from the session list,
// newest first; sessions the calendar already holds are skipped.
const olderSessions = { items: [], cursor: undefined, loading: false, generation: 0 };

// New calendar data (sync, reload, undo, feedback) drops the cached older pages, so a deleted,
// split or edited session is read again; an answer for the dropped pages is ignored.
function resetOlderSessions() {
  Object.assign(olderSessions, { items: [], cursor: undefined, loading: false, generation: olderSessions.generation + 1 });
}

function withOlderSessions(calendar) {
  const known = completedSessionIds(calendar);
  return calendar.concat(olderSessions.items.filter((item) => !known.has(String(item.activity_id || item.id))));
}

// Only a week before the configured ones asks for more: the startup data covers those.
function loadOlderSessions(calendar, shownStartKey, configuredStartKey) {
  if (olderSessions.loading || olderSessions.cursor === null || shownStartKey >= configuredStartKey) return;
  const loadedStart = calendar.filter((item) => calendarActualActivity(item)).map(plannedEventDate).filter(Boolean).sort()[0];
  if (loadedStart && shownStartKey >= loadedStart) return;
  olderSessions.loading = true;
  const generation = olderSessions.generation;
  const cursor = olderSessions.cursor ? `&cursor=${encodeURIComponent(olderSessions.cursor)}` : "";
  api(`/api/activities?limit=100${cursor}`, { timeoutMs: DATA_LOAD_TIMEOUT_MS }).then((page) => {
    if (generation !== olderSessions.generation) return;
    const known = completedSessionIds(calendar);
    for (const row of Array.isArray(page?.activities) ? page.activities : []) {
      // Only sessions before the loaded ones are new; later ones are in the loaded data already.
      const day = String(row?.started_at_local || "").slice(0, 10);
      if (row?.id == null || known.has(String(row.id)) || (loadedStart && day >= loadedStart)) continue;
      olderSessions.items.push({ ...row, date: String(row.started_at_local || "").slice(0, 10), is_completed_activity: true });
    }
    olderSessions.cursor = page?.next_cursor || null;
    olderSessions.loading = false;
    renderPlanned(renderedCalendar);
  }, () => { if (generation === olderSessions.generation) olderSessions.loading = false; });
}

function renderPlanned(trainingCalendar) {
  const root = $("#plannedCalendar");
  if (!root) return;
  if (trainingCalendar !== renderedCalendar) {
    resetOlderSessions();
    plannedSessionReads.clear();
  }
  renderedCalendar = trainingCalendar;
  const calendar = withOlderSessions(Array.isArray(trainingCalendar) ? trainingCalendar : []);
  const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
  const currentWeekKey = planWeekStart(todayKey);
  const display = state.data?.calendar_display || {};
  const pastWeeks = calendarDisplayValue(display.past_weeks, 1);
  const futureWeeks = calendarDisplayValue(display.future_weeks, 4);
  const firstWeekKey = addDateKey(currentWeekKey, -7 * pastWeeks);
  const lastWeekKey = addDateKey(currentWeekKey, 7 * futureWeeks);
  const lastDateKey = addDateKey(lastWeekKey, 6);
  plannedLastDateKey = lastDateKey;
  keepPlannedSelection(todayKey, lastDateKey);
  const snapshot = JSON.stringify([calendar, todayKey, selectedWeekKey, calendarView, selectedDayKey, display, state.data?.daily_planning_context, state.data?.planning_compliance, state.data?.competitions, state.data?.weather, (state.data?.external_calendar?.events || []).map((event) => [event?.uid, event?.start_local, event?.impact, event?.name]), state.data?.external_calendar?.undecided_upcoming]);
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
  const banner = plannedUndecidedBanner();
  if (banner) root.append(banner);
  const weeklyCompliance = new Map(
    (Array.isArray(state.data?.planning_compliance) ? state.data.planning_compliance : [])
      .filter((item) => item?.week_start)
      .map((item) => [String(item.week_start).slice(0, 10), item]),
  );
  const entries = calendar
    .filter((item) => item && !item.archived && !item.local_deleted && plannedEventDate(item))
    .filter((item) => plannedEventDate(item) <= lastDateKey)
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
    calendarEventsByDate: plannedEventsByDate(todayKey),
    leftoversByWeek: plannedLeftoversByWeek(trainingCalendar, currentWeekKey, lastWeekKey),
    eventsByDate,
    dayKey: selectedDayKey,
    // No earliest week: paging back is unlimited.
    firstWeekKey: "",
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
  loadOlderSessions(calendar, calendarView === "month" ? planWeekStart(monthStartKey(selectedDayKey)) : selectedWeekKey, firstWeekKey);
}

// Wahoo state of an exported library workout. A changed one offers the
// explicit send; the job carries the payload hash the server returned, so a
// workout edited meanwhile is refused instead of pushed.
function libraryWahooRow(workout) {
  const wahoo = workout.wahoo_state;
  if (!wahoo?.state || !workout.id) return null;
  const changed = wahoo.state === "changed";
  const row = h("div", "library-wahoo", h("span", `library-wahoo-state is-${changed ? "changed" : "synced"}`, changed ? "Wahoo: geändert" : "Wahoo: synchron"));
  if (!changed || !wahoo.payload_hash) return row;
  state.librarySyncInFlight ||= new Set();
  const button = h("button", { type: "button", className: "secondary-button library-wahoo-send", "aria-label": `${workout.name || "Einheit"} an Wahoo senden`, disabled: state.librarySyncInFlight.has(workout.id) }, "Erneut senden");
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
    root.append(h("p", "context-empty", "Noch keine Einheiten in der Bibliothek. Der Coach legt hier Einheiten ab, wenn du sie planst."));
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
      const section = h("details", "library-sport",
        h("summary", null, h("strong", null, sport), h("span", null, `${sportWorkouts.length} Einheit${sportWorkouts.length === 1 ? "" : "en"}`)),
        h("div", "library-sport-cards", sportWorkouts.map((workout) => h("article", "library-card",
          h("div", null,
            h("h4", null, workout.name || "Bibliotheks-Einheit"),
            h("span", null, [workout.type, workout.planned_duration_s ? formatDuration(workout.planned_duration_s) : null].filter(Boolean).join(" · "))),
          h("p", null, workout.description || "Kein Workout-Text hinterlegt."),
          libraryWahooRow(workout)))));
      section.open = false;
      root.append(section);
    });
}



// Race plan of an expanded upcoming competition (#2803).
const RACE_PLAN_WEEKDAY = new Intl.DateTimeFormat("de-DE", { weekday: "short", timeZone: "UTC" });
const RACE_PLAN_KM = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
const RACE_PLAN_UNAVAILABLE = { distance: "Distanz fehlt", duration: "Zielzeit oder erwartete Dauer fehlt" };

function racePlanRange(values, unit) {
  return Array.isArray(values) ? `${values[0]}–${values[1]} ${unit}` : null;
}

function racePlanDay(eventDate, daysBack) {
  const start = Date.parse(`${String(eventDate).slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(start) ? null : RACE_PLAN_WEEKDAY.format(new Date(start - daysBack * 86_400_000));
}

function racePlanDays(eventDate, count) {
  const days = Array.from({ length: count }, (_, index) => racePlanDay(eventDate, count - index));
  if (days.every(Boolean)) return days.join(" + ");
  return count === 1 ? "1 Tag davor" : `${count} Tage davor`;
}

// "+4 %", "−2 %" or the zero form; the minus is typographic.
function racePlanSigned(value, zero = "") {
  if (value > 0) return `+${RACE_PLAN_KM.format(value)} %`;
  if (value < 0) return `−${RACE_PLAN_KM.format(-value)} %`;
  return `${zero}0 %`;
}

// The meal window before the start; a window before midnight names the day before.
function racePlanMeal(eventDate, startsAtLocal, hours) {
  const time = /T(\d{2}):(\d{2})/.exec(String(startsAtLocal || ""));
  const raceDay = racePlanDay(eventDate, 0);
  if (!time || (time[1] === "00" && time[2] === "00")) return [raceDay, `${hours[0]}–${hours[1]} h vor dem Start`].filter(Boolean).join(" ");
  const start = Number(time[1]) * 60 + Number(time[2]);
  const [from, to] = hours.map((offset) => {
    const minutes = start - offset * 60;
    const value = (minutes + 1440) % 1440;
    return { day: racePlanDay(eventDate, minutes < 0 ? 1 : 0), clock: `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}` };
  });
  if (from.day === to.day) return [from.day, `${from.clock}–${to.clock}`].filter(Boolean).join(" ");
  return `${from.day} ${from.clock} – ${to.day} ${to.clock}`;
}

function racePlanDuring(during) {
  if (!during) return null;
  if (during.step === "none") return "keine nötig";
  if (during.step === "mouth_rinse") return "kleine Mengen oder Mund spülen";
  const range = `${during.low_g}–${during.high_g} g/h`;
  return during.established_max_g ? `${range} · Glukose + Fruktose · über ${during.established_max_g} g/h unbelegt` : range;
}

function racePlanHeading(text, badge) {
  return h("h5", null, text, badge ? h("span", "planned-badge", badge) : null);
}

function racePlanPacing(pacing) {
  if (pacing.status !== "ready") return RACE_PLAN_UNAVAILABLE[pacing.reason] ? [racePlanHeading("Tempo"), h("p", "race-plan-gap", RACE_PLAN_UNAVAILABLE[pacing.reason])] : [];
  const ride = pacing.method === "power_variation";
  const badge = [ride ? "± 5 % Leistung" : "gleiche Anstrengung", pacing.profile_rejected ? "Streckenprofil nicht erkannt" : null].filter(Boolean).join(" · ");
  const rows = pacing.sections.map((section) => {
    const grade = racePlanSigned(section.grade_pct);
    const span = `km ${RACE_PLAN_KM.format(section.from_km)}–${RACE_PLAN_KM.format(section.to_km)}`;
    if (ride) return [span, grade, section.power_w == null ? racePlanSigned(section.power_pct, "±") : `${section.power_w} W`];
    return [span, grade, `${AppFormat.clock(section.pace_s_per_km)}/km`, AppFormat.clock(section.time_s)];
  });
  const columns = ride ? ["Abschnitt", "Steigung", "Leistung"] : ["Abschnitt", "Steigung", "Tempo", "Zeit"];
  return [racePlanHeading("Tempo", badge), table(columns, rows, { className: "race-plan-table" })];
}

function racePlanCarbohydrates(carbohydrates, competition) {
  const weight = carbohydrates.weight?.source ? `Gewicht ${carbohydrates.weight.source}` : null;
  const rows = carbohydrates.before.map((entry) => entry.kind === "meal"
    ? [racePlanMeal(competition.event_date, competition.starts_at_local, entry.hours_before), racePlanRange(entry.grams, "g") || racePlanRange(entry.g_per_kg, "g/kg")]
    : [racePlanDays(competition.event_date, entry.days_before), racePlanRange(entry.grams, "g/Tag") || racePlanRange(entry.g_per_kg, "g/kg/Tag")]);
  const during = racePlanDuring(carbohydrates.during);
  rows.push(["Im Rennen", during || RACE_PLAN_UNAVAILABLE.duration]);
  return [
    racePlanHeading("Kohlenhydrate", [carbohydrates.source, weight].filter(Boolean).join(" · ")),
    h("div", "race-plan-rows", rows.map(([label, value]) => h("div", null, h("span", null, label), h("strong", null, value)))),
  ];
}

// Read on every opening, so the plan follows weight and competition changes; nothing is kept in memory.
function loadRacePlan(section, competition) {
  if (section.dataset.state === "loading") return;
  section.dataset.state = "loading";
  const status = h("output", null, "Rennplan wird berechnet …");
  section.replaceChildren(h("h4", null, "Rennplan"), status);
  api(`/api/competitions/${encodeURIComponent(competition.id)}/race-plan`, { timeoutMs: DATA_LOAD_TIMEOUT_MS }).then((payload) => {
    const plan = payload.race_plan;
    section.dataset.state = "ready";
    section.replaceChildren(h("h4", null, "Rennplan"), ...racePlanPacing(plan.pacing), ...racePlanCarbohydrates(plan.carbohydrates, competition));
  }).catch(() => {
    section.dataset.state = "failed";
    const retry = h("button", { type: "button", className: "secondary-button" }, "Erneut laden");
    retry.addEventListener("click", () => loadRacePlan(section, competition));
    status.textContent = "Rennplan konnte nicht geladen werden.";
    section.append(retry);
  });
}

function competitionCard(competition, todayKey, openIds) {
  const sport = competition.sport_detail || competitionSportLabel(competition.sport, competition.environment);
  const when = AppFormat.relativeDay(competition.event_date, todayKey);
  const summary = h("summary", null,
    h("strong", null, `${competitionDate(competition, todayKey) ? dateLabel(competition.event_date) : "Datum unbekannt"} · ${competition.name || "Wettkampf"}`),
    h("span", "competition-summary-facts", [sport, competitionDistance(competition.distance), `Priorität ${competition.priority || "B"}`, when].filter(Boolean).join(" · ")));
  const source = h("small", "competition-sync-state", competition.external_id ? "Intervals.icu" : "Lokal");
  if (competition.sync_state === "local_override") source.textContent = "Lokal geändert";
  const optional = [
    ["Ergebnis", competitionResult(competition.result)],
    ["Startzeit", competition.starts_at_local ? formatLocalCompetitionTime(competition.starts_at_local) : null],
    ["Ziel", competition.target],
    ["Erwartete Dauer", competition.planned_duration_s == null ? null : AppFormat.duration(competition.planned_duration_s)],
    ["Streckenprofil", competition.course_profile],
    ["Beschreibung", competition.description],
    ["Notizen", competition.notes],
  ];
  const facts = optional.filter(([, value]) => value != null && String(value).trim() !== "").map(([label, value]) => competitionFact(label, value));
  const upcoming = competitionDate(competition, todayKey) && competition.event_date >= todayKey;
  const plan = upcoming ? h("section", "race-plan") : null;
  const card = h("details", { className: "competition-card", dataset: { competitionId: String(competition.id) }, open: openIds.has(String(competition.id)) },
    summary, source, facts.length ? h("div", "competition-card-facts", facts) : null, plan);
  if (plan) {
    card.addEventListener("toggle", () => { if (card.open) loadRacePlan(plan, competition); });
    if (card.open) loadRacePlan(plan, competition);
  }
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
    root.append(h("p", "context-empty", "Noch keine Wettkämpfe gespeichert."));
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
    root.append(h("h4", null, "Ohne gültiges Datum"), ...undated.map((event) => competitionCard(event, todayKey, openIds)));
  }
  if (past.length) {
    const archive = h("details", { className: "competition-archive", open: archiveOpen }, h("summary", null, `Vergangene Wettkämpfe (${past.length})`));
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
