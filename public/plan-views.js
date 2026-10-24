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

globalThis.AppPlanViews = Object.freeze({ create });

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

function plannedConflictBadgeSpecs(conflicts) {
  return (Array.isArray(conflicts) ? conflicts : [])
    .map((conflict) => String(conflict?.label || "").trim())
    .filter(Boolean)
    .map((label) => ({ kind: "conflict", icon: "⚠", text: `Konflikt: ${label}` }));
}

function plannedDayBadgeSpecs(dayContext, competitions, dateKey) {
  const context = dayContext && typeof dayContext === "object" ? dayContext : {};
  const appointments = Array.isArray(context.appointments) ? context.appointments : [];
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
  for (const { key, label } of CALENDAR_MARKERS) {
    if (markerKeys.has(key)) specs.push({ kind: "marker", icon: "", text: label });
  }
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

// Sports that normally record a distance; only these count as "ohne Distanz" when the distance is missing.
const DISTANCE_SPORT_TYPES = new Set(["ride", "virtualride", "gravelride", "mountainbikeride", "emountainbikeride", "ebikeride", "run", "virtualrun", "trailrun", "walk", "hike", "swim", "openwaterswim", "nordicski", "rollerski", "rowing", "virtualrow", "canoeing", "kayaking", "standuppaddling", "snowshoe"]);

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
function calendarWeekDistanceLabel(activities) {
  const measured = activities.filter((entry) => Number(entry.distance) > 0);
  const unmeasured = activities.filter((entry) => {
    const distance = Number(entry.distance);
    return distance <= 0 || Number.isNaN(distance);
  });
  const missing = unmeasured.filter((entry) => DISTANCE_SPORT_TYPES.has(String(entry.type || "").toLowerCase())).length;
  if (!measured.length && !missing) return "–";
  const total = measured.length
    ? AppFormat.distance(measured.reduce((sum, entry) => sum + Number(entry.distance), 0))
    : "–";
  if (!missing) return total;
  return `${total} · ohne ${missing} ${missing === 1 ? "Aktivität" : "Aktivitäten"}`;
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
  if (Number.isFinite(numeric)) return numeric < 0 ? "Distanz unbekannt" : numeric === 0 ? "0 km" : AppFormat.distance(numeric);
  return String(value);
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
  const measurable = percentage != null && ["training_load", "duration"].includes(entry.compliance?.basis);
  if (status !== "missed" && !measurable) return;
  const execution = document.createElement("span");
  const value = status === "missed" ? 0 : Number(entry.compliance.percentage);
  let executionState = "is-on-target";
  if (value < 80 || value > 120) executionState = "is-deviation";
  if (value === 0) executionState = "is-zero";
  execution.className = `planned-execution ${executionState}`;
  execution.textContent = `${value === 0 ? "✕" : "✓"} ${status === "missed" ? "0" : percentage} %`;
  const basis = { training_load: "Belastung", duration: "Dauer" }[entry.compliance?.basis];
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

function plannedDayNotes(dayContext) {
  const notes = document.createElement("div");
  notes.className = "planned-day-notes";
  const appointments = (Array.isArray(dayContext.appointments) ? dayContext.appointments : [])
    .filter((event) => event && (event.training_relevant !== false || calendarMarkerKeys(event).length > 0))
    .map(plannedAppointmentLabel)
    .filter(Boolean);
  if (appointments.length) {
    const calendarNotice = document.createElement("p");
    calendarNotice.className = "planned-day-context planned-day-calendar";
    calendarNotice.textContent = `Kalender: ${appointments.join(", ")}`;
    notes.append(calendarNotice);
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
  if (actual) return AppFormat.duration(actual.moving_time ?? actual.elapsed_time);
  if (entry.duration_minutes) return AppFormat.duration(Number(entry.duration_minutes) * 60);
  return AppFormat.duration(entry.moving_time);
}

function appendPlannedCalendarComparison(details, entry, actual) {
  if (!actual || entry.is_completed_activity) return;
  const comparison = document.createElement("div");
  comparison.className = "planned-comparison";
  const plannedDuration = entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.moving_time;
  const planLine = document.createElement("p");
  planLine.textContent = `Plan: ${[
    entry.name,
    AppFormat.duration(plannedDuration),
    entry.training_load != null ? `Load ${calendarMetricNumber(entry.training_load)}` : null,
  ].filter(Boolean).join(" · ")}`;
  const actualLine = document.createElement("p");
  actualLine.textContent = `Ist: ${[
    AppFormat.duration(actual.moving_time ?? actual.elapsed_time),
    actual.training_load != null ? `Load ${calendarMetricNumber(actual.training_load)}` : null,
  ].filter(Boolean).join(" · ")}`;
  comparison.append(planLine, actualLine);
  if (entry.compliance?.percentage != null) {
    const ratio = document.createElement("p");
    ratio.textContent = `${entry.compliance.basis === "training_load" ? "Load" : "Umfang"} Plan/Ist: ${entry.compliance.percentage} %`;
    comparison.append(ratio);
  }
  details.append(comparison);
}

function appendPlannedEntryStatus(cardSummary, entry, status, restDayLabel, dateKey, todayKey) {
  if (status !== "completed" && status !== "missed" && status !== "skipped") return;
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

const SEASON_PHASE_LABELS = { base: "Basis", build: "Aufbau", peak: "Spezifische Vorbereitung", taper: "Taper", completed: "Vergangen" };

function nextCompetitionSummary(next, dateLabel, todayKey) {
  if (!next) return "Noch kein zukünftiger Wettkampf gespeichert.";
  const when = AppFormat.relativeDay(next.event_date, todayKey) ?? `${next.days_until} Tage`;
  const phase = SEASON_PHASE_LABELS[next.phase] || next.phase;
  return `Nächster Wettkampf: ${next.name} am ${dateLabel(next.event_date)} · Phase: ${phase} · ${when}`;
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

function adaptiveCaption(illnessPending, count) {
  if (illnessPending) return "Krankheit gemeldet: Sportpause prognostizieren und bestätigen.";
  if (count === 1) return "Ein zukünftiger Entwurf braucht eine Anpassung.";
  return `${count} zukünftige Entwürfe brauchen eine Anpassung.`;
}

function create({ $, state, dateLabel, formatTime, formatDuration, formatPace, formatWhole, distanceLabel, activitySportLabel, analysisSvg, api, showAccessibleDialog, appendHistoryPageButton, AppRouter, dateFromKey, localDateKey, addDateKey, weatherNumber, weatherIconFor, weatherDirection, plannedEventDate, timezoneDateKey, calendarDisplayValue }) {
  function renderAdaptivePlanning(data) {
    const planning = data.planning || {};
    const next = planning.season?.next_event;
    const summary = $("#planningSummary");
    if (summary) summary.textContent = nextCompetitionSummary(next, dateLabel, todayIso());
    const preview = planning.latest_replan;
    const changes = Array.isArray(preview?.changes) ? preview.changes : [];
    const illnessPending = adaptiveIllnessPending(data, preview);
    const required = Boolean(planning.needs_replan || illnessPending);
    const caption = adaptiveCaption(illnessPending, Number(planning.replan_changes || changes.length));
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
    const status = $("#externalCalendarConnectionStatus");
    const syncButton = $("#externalCalendarSyncButton");
    if (status) {
      if (!calendar.configured) status.textContent = "Nicht konfiguriert";
      else if (calendar.last_error) status.textContent = "Fehler bei letzter Aktualisierung";
      else status.textContent = "Konfiguriert · nur lesend";
      status.className = calendar.configured && !calendar.last_error ? "configured" : "not-configured";
    }
    if (syncButton) {
      syncButton.disabled = Boolean(calendar.running || state.localSync.externalCalendar);
      syncButton.textContent = calendar.running || state.localSync.externalCalendar ? "Synchronisierung läuft…" : "Synchronisieren";
    }
  }


  function trainingPlanEntry(item) {
    const entry = document.createElement("div");
    entry.className = "training-plan-entry";
    entry.textContent = `${item.date ? dateLabel(item.date) : "Ohne Datum"} · ${item.name || "Einheit"} · ${item.duration_minutes || Math.round(Number(item.moving_time || 0) / 60) || "?"} Min.`;
    return entry;
  }

  function trainingPlanCard(plan, planEntries) {
      const details = document.createElement("details");
      details.className = "training-plan";
      const summary = document.createElement("summary");
      const title = document.createElement("strong");
      title.textContent = plan.name || "Mehrwochenplan";
      const meta = document.createElement("span");
      meta.textContent = [plan.start_date && plan.end_date ? `${dateLabel(plan.start_date)} – ${dateLabel(plan.end_date)}` : null, `${planEntries.length} Einheiten`, plan.status].filter(Boolean).join(" · ");
      summary.append(title, meta);
      details.append(summary);
      const body = document.createElement("div");
      body.className = "training-plan-body";
      if (plan.goal) {
        const goal = document.createElement("p");
        goal.textContent = plan.goal;
        body.append(goal);
      }
      planEntries.sort((a, b) => String(a.date || "").localeCompare(String(b.date || ""))).forEach((entry) => body.append(trainingPlanEntry(entry)));
      if (!planEntries.length) {
        const empty = document.createElement("p");
        empty.className = "fine-print";
        empty.textContent = "Keine aktiven Einheiten zu diesem Plan vorhanden.";
        body.append(empty);
      }
      details.append(body);
      return details;
  }

  function renderTrainingPlans(plans, workouts) {
    const root = $("#trainingPlans");
    if (!root) return;
    root.replaceChildren();
    const entries = (workouts || []).filter((item) => item?.plan_id && !item?.archived);
    if (!Array.isArray(plans) || !plans.length) return;
    const heading = document.createElement("h3");
    heading.className = "subsection-title";
    heading.textContent = "Mehrwochenpläne";
    root.append(heading);
    plans.forEach((plan) => {
      const planEntries = entries.filter((item) => String(item.plan_id) === String(plan.id));
      root.append(trainingPlanCard(plan, planEntries));
    });
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
    const load = [`Load geplant ${formatWhole(compliance.planned_value)}`];
    if (isPast || completedUnits > 0) load.push(`absolviert ${formatWhole(compliance.actual_value || 0)}`);
    return `${units} · ${load.join(" · ")}`;
  }

  function calendarPaceLabel(activity) {
    if (activitySportLabel(activity) !== "Laufen") return null;
    const duration = Number(activity?.moving_time);
    const distance = Number(activity?.distance);
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

  function focusPlannedToday() {
    if (!state.plannedTodayFocusPending || !state.loadedAreas.has("plan")) return false;
    if (AppRouter.baseRoute(state.route) !== "plan" || AppRouter.planSegmentFromRoute(state.route) !== "overview") return false;
    const today = $("#plannedCalendar")?.querySelector(".planned-day.is-today");
    if (!today) return false;
    const week = today.closest(".planned-week");
    if (week) week.open = true;
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
    primaryMetrics.textContent = [load != null ? `Load ${load}` : null, rpe != null ? `RPE ${rpe}/10` : "RPE offen"].filter(Boolean).join(" · ");
    const facts = document.createElement("div");
    facts.className = "planned-actual-facts";
    appendCalendarFact(facts, "Dauer", AppFormat.duration(actual.moving_time ?? actual.elapsed_time));
    appendCalendarFact(facts, "Distanz", distanceLabel(actual.distance));
    appendCalendarFact(facts, "Trainingsload", calendarMetricNumber(actual.training_load));
    appendCalendarFact(facts, "RPE", rpe != null ? `${rpe}/10` : "nicht angegeben");
    appendCalendarFact(facts, "Intensität", calendarIntensityLabel(actual.intensity));
    appendCalendarFact(facts, "Ø Puls", calendarMetricNumber(actual.average_heartrate, " bpm"));
    appendCalendarFact(facts, "Ø Leistung", calendarMetricNumber(actual.weighted_average_watts ?? actual.average_watts, " W"));
    appendCalendarFact(facts, "Pace", calendarPaceLabel(actual));
    appendCalendarFact(facts, "Höhenmeter", calendarMetricNumber(actual.total_elevation_gain, " hm"));
    details.append(primaryMetrics, facts);
  }

  function appendPlannedSessionHeader(cardSummary, entry, actual) {
    const displayed = actual || entry;
    const header = document.createElement("span");
    header.className = "planned-session-header";
    const sport = document.createElement("span");
    sport.textContent = [activitySportLabel(displayed), actual ? calendarStartTime(actual.start_date_local) : plannedUnitStartTime(entry.start_date_local)].filter(Boolean).join(" · ");
    const duration = document.createElement("strong");
    duration.textContent = plannedEntryDurationLabel(actual, entry);
    const distance = document.createElement("span");
    distance.textContent = displayed.distance > 0 ? distanceLabel(displayed.distance) : "";
    header.append(sport, duration, distance);
    const metrics = document.createElement("span");
    metrics.className = "planned-session-metrics";
    metrics.textContent = [
      actual ? calendarMetricNumber(actual.average_heartrate, " bpm") : null,
      actual ? calendarMetricNumber(actual.average_watts ?? actual.weighted_average_watts, " W") : null,
      calendarMetricNumber(displayed.training_load) != null ? `Belastung ${calendarMetricNumber(displayed.training_load)}` : null,
    ].filter(Boolean).join(" · ");
    cardSummary.append(header);
    if (metrics.textContent) cardSummary.append(metrics);
  }

  function calendarWorkoutProfile(profile) {
    const segments = profile?.segments;
    if (!Array.isArray(segments) || !segments.length || segments.length > 1000) return null;
    const axis = profile.axis === "distance" ? "distance" : "duration";
    const extent = (item) => (Number.isFinite(item[axis]) && item[axis] > 0 ? item[axis] : 0);
    const total = segments.reduce((sum, item) => sum + extent(item), 0);
    const values = segments.flatMap((item) => [item.value, item.end_value]).filter((value) => value != null && Number.isFinite(value) && value >= 0);
    if (!total || !values.length) return null;
    const top = Math.max(...values, 1) * 1.1;
    const baseLabel = profile.source === "recorded" ? "Aufgezeichnetes Belastungsprofil" : "Geplantes Intervallprofil";
    const label = profile.estimated ? `${baseLabel} (Zonen geschätzt aus FTP/LTHR)` : baseLabel;
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
    return analysisSvg("polygon", { points: `${x},54 ${x},${left} ${x + width},${right} ${x + width},54`, "data-zone": zone });
  }

  function renderPlannedEntry(entry, dateKey, todayKey, dayContext = {}) {
    const actual = calendarActualActivity(entry);
    const baseStatus = calendarEntryStatus(entry, dateKey, todayKey);
    const restDayLabel = baseStatus === "missed" ? plannedDayStatusLabel(dayContext.day_status) : null;
    const status = restDayLabel ? "skipped" : baseStatus;
    const card = document.createElement("details");
    card.className = `planned-entry is-${status}`;
    card.open = false;
    const cardSummary = document.createElement("summary");
    const cardTitle = document.createElement("strong");
    cardTitle.textContent = actual?.name || entry.name || "Trainingseinheit";
    const meta = document.createElement("span");
    meta.className = "planned-meta";
    const displayed = actual || entry;
    card.dataset.sport = activitySportLabel(displayed);
    meta.textContent = [
      activitySportLabel(displayed),
      actual ? calendarStartTime(actual.start_date_local) : plannedUnitStartTime(entry.start_date_local),
      plannedEntryDurationLabel(actual, entry),
    ].filter(Boolean).join(" · ");
    appendPlannedSessionHeader(cardSummary, entry, actual);
    cardSummary.append(meta);
    appendPlannedEntryStatus(cardSummary, entry, status, restDayLabel, dateKey, todayKey);
    appendPlannedExecution(cardSummary, entry, status);
    const profile = calendarWorkoutProfile(actual?.workout_profile || entry.workout_profile);
    if (profile) cardSummary.append(profile);
    cardSummary.append(cardTitle);
    const conflictSpecs = plannedConflictBadgeSpecs(entry.conflicts);
    if (conflictSpecs.length) cardSummary.append(calendarBadgeRow(conflictSpecs));
    if (actual && !entry.is_completed_activity) appendPlannedTarget(cardSummary, entry);
    const details = document.createElement("div");
    details.className = "planned-entry-details";
    appendActualCalendarDetails(details, actual);
    if (actual && (actual.id || actual.activity_id)) {
      const activityButton = document.createElement("button");
      activityButton.type = "button";
      activityButton.className = "secondary-button";
      activityButton.textContent = "Aktivität analysieren";
      activityButton.addEventListener("click", () => globalThis.ActivityDetails.open(actual, {
        api,
        showDialog: showAccessibleDialog,
      }));
      details.append(activityButton);
    }
    appendPlannedCalendarComparison(details, entry, actual);
    if (entry.description) {
      const description = document.createElement("p");
      description.className = "planned-description";
      description.textContent = entry.description;
      details.append(description);
    }
    if (!details.childElementCount) {
      const description = document.createElement("p");
      description.className = "planned-description";
      description.textContent = "Keine weiteren Details hinterlegt.";
      details.append(description);
    }
    card.append(cardSummary, details);
    return card;
  }

  function plannedDayWeather(dayContext, dateKey) {
    if (dayContext.weather) return dayContext.weather;
    const days = state.data?.weather?.days;
    return Array.isArray(days) ? days.find((item) => item?.date === dateKey) : null;
  }

  function appendPlannedDayHeading(day, weather, dateKey, todayKey) {
    const heading = document.createElement("div");
    heading.className = "planned-day-heading";
    const title = document.createElement("h5");
    title.id = `planned-day-${dateKey}`;
    title.textContent = new Intl.DateTimeFormat("de-DE", { weekday: "short" }).format(dateFromKey(dateKey));
    day.setAttribute("aria-labelledby", title.id);
    const dayDate = document.createElement("time");
    dayDate.dateTime = dateKey;
    const dayNumber = document.createElement("strong");
    dayNumber.textContent = new Intl.DateTimeFormat("de-DE", { day: "2-digit" }).format(dateFromKey(dateKey));
    const month = document.createElement("span");
    month.textContent = new Intl.DateTimeFormat("de-DE", { month: "short" }).format(dateFromKey(dateKey));
    dayDate.append(dayNumber, month);
    heading.append(title, dayDate);
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
    day.append(heading);
  }

  function renderPlannedDay(view, dateKey) {
    const { eventsByDate, planningContextByDate, todayKey } = view;
    const dayEntries = eventsByDate.get(dateKey) || [];
    const dayContext = planningContextByDate.get(dateKey) || {};
    const weather = plannedDayWeather(dayContext, dateKey);
    const day = document.createElement("section");
    day.className = `planned-day${dateKey === todayKey ? " is-today" : ""}`;
    day.dataset.date = dateKey;
    appendPlannedDayHeading(day, weather, dateKey, todayKey);
    const content = document.createElement("div");
    content.className = "planned-day-content";
    const notes = plannedDayNotes(dayContext);
    const dayBadges = plannedDayBadgeSpecs(dayContext, state.data?.competitions, dateKey);
    if (dayBadges.length) notes.prepend(calendarBadgeRow(dayBadges));
    if (notes.childElementCount) content.append(notes);
    if (!dayEntries.length) {
      const empty = document.createElement("p");
      empty.className = "planned-day-empty";
      empty.textContent = dateKey < todayKey ? "Keine Aktivität" : "Keine Einheit geplant";
      content.append(empty);
    }
    dayEntries.forEach((entry) => content.append(renderPlannedEntry(entry, dateKey, todayKey, dayContext)));
    day.append(content);
    return day;
  }

  function renderPlannedWeek(view, weekIndex) {
    const { currentWeekKey, eventsByDate, firstWeekKey, nextWeekKey, previousWeekOpenState, todayKey, weeklyCompliance } = view;
    const weekKey = addDateKey(firstWeekKey, weekIndex * 7);
    const weekEndKey = addDateKey(weekKey, 6);
    const weekEntries = Array.from({ length: 7 }, (_, offset) => eventsByDate.get(addDateKey(weekKey, offset)) || []).flat();
    const week = document.createElement("details");
    week.className = "planned-week";
    week.dataset.weekKey = weekKey;
    week.open = previousWeekOpenState.has(weekKey) ? previousWeekOpenState.get(weekKey) : weekKey === currentWeekKey || weekKey === nextWeekKey;
    const heading = document.createElement("summary");
    heading.className = "planned-week-heading";
    const title = document.createElement("h4");
    title.textContent = planWeekLabel(weekKey);
    const count = document.createElement("span");
    count.className = "planned-week-summary";
    count.textContent = calendarCountLabel(weekEntries, todayKey) || "Keine Einheiten";
    heading.append(title, count);
    const totals = document.createElement("span");
    totals.className = "planned-week-metrics";
    const sum = (items, metric) => items.reduce((total, item) => total + Math.max(0, Number(metric(item)) || 0), 0);
    const planned = weekEntries.filter((entry) => !entry.is_completed_activity);
    const actual = weekEntries.map(calendarActualActivity).filter(Boolean);
    const plannedSeconds = sum(planned, (entry) => entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.moving_time);
    const actualSeconds = sum(actual, (entry) => entry.moving_time ?? entry.elapsed_time);
    for (const [label, value] of [
      ["Geplant", plannedSeconds > 0 ? AppFormat.duration(plannedSeconds) : "–"],
      ["Absolviert", AppFormat.duration(actualSeconds)],
      ["Distanz", calendarWeekDistanceLabel(actual)],
      ["Belastung geplant", planned.length && planned.every((entry) => entry.training_load != null) ? calendarMetricNumber(sum(planned, (entry) => entry.training_load)) : "–"],
      ["Belastung absolviert", actual.length && actual.every((entry) => entry.training_load != null) ? calendarMetricNumber(sum(actual, (entry) => entry.training_load)) : "–"],
    ]) {
      const metric = document.createElement("span");
      const number = document.createElement("strong");
      number.textContent = value;
      metric.append(document.createTextNode(`${label} `), number);
      totals.append(metric);
    }
    heading.append(totals);
    week.append(heading);
    const days = document.createElement("div");
    days.className = "planned-week-days";
    for (let offset = 0; offset < 7; offset += 1) days.append(renderPlannedDay(view, addDateKey(weekKey, offset)));
    week.append(days);
    if (weekEntries.length) {
      const additionalCompleted = weekEntries.filter((entry) => entry.is_completed_activity).length;
      const details = document.createElement("p");
      details.className = "planned-week-totals";
      const summary = plannedWeekSummary(weekKey, weekEndKey, weekEntries, weeklyCompliance.get(weekKey), todayKey);
      details.textContent = additionalCompleted ? `${summary} · +${additionalCompleted} zusätzlich` : summary;
      week.append(details);
    }
    return week;
  }

  let plannedRenderSnapshot = null;

  function renderPlanned(trainingCalendar) {
    const root = $("#plannedCalendar");
    const summary = $("#plannedSummary");
    if (!root) return;
    const todayKey = timezoneDateKey(state.data?.profile?.timezone, new Date());
    const currentWeekKey = planWeekStart(todayKey);
    const display = state.data?.calendar_display || {};
    const snapshot = JSON.stringify([trainingCalendar, todayKey, display, state.data?.daily_planning_context, state.data?.planning_compliance, state.data?.competitions, state.data?.weather]);
    if (snapshot === plannedRenderSnapshot && root.childElementCount) {
      if (state.plannedTodayFocusPending) requestAnimationFrame(() => focusPlannedToday());
      return;
    }
    plannedRenderSnapshot = snapshot;
    const pastWeeks = calendarDisplayValue(display.past_weeks, 1);
    const futureWeeks = calendarDisplayValue(display.future_weeks, 4);
    const firstWeekKey = addDateKey(currentWeekKey, -7 * pastWeeks);
    const nextWeekKey = addDateKey(currentWeekKey, 7);
    const previousWeekOpenState = new Map(
      [...root.querySelectorAll(".planned-week[data-week-key]")].map((week) => [week.dataset.weekKey, week.open]),
    );
    root.replaceChildren();
    const weeklyCompliance = new Map(
      (Array.isArray(state.data?.planning_compliance) ? state.data.planning_compliance : [])
        .filter((item) => item?.week_start)
        .map((item) => [String(item.week_start).slice(0, 10), item]),
    );
    const lastDateKey = addDateKey(firstWeekKey, ((pastWeeks + futureWeeks + 1) * 7) - 1);
    const entries = (Array.isArray(trainingCalendar) ? trainingCalendar : [])
      .filter((item) => item && !item.archived && !item.local_deleted && plannedEventDate(item))
      .filter((item) => plannedEventDate(item) >= firstWeekKey && plannedEventDate(item) <= lastDateKey)
      .sort((left, right) => String(left.start_date_local || left.date || "").localeCompare(String(right.start_date_local || right.date || "")));
    if (summary) summary.textContent = calendarCountLabel(entries, todayKey) || "Keine Einheiten im Zeitraum";
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
      currentWeekKey,
      eventsByDate,
      firstWeekKey,
      nextWeekKey,
      planningContextByDate,
      previousWeekOpenState,
      todayKey,
      weeklyCompliance,
    };
    for (let weekIndex = 0; weekIndex < pastWeeks + futureWeeks + 1; weekIndex += 1) root.append(renderPlannedWeek(view, weekIndex));
    if (state.plannedTodayFocusPending) requestAnimationFrame(() => focusPlannedToday());
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
          card.append(heading, description);
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
    source.textContent = competition.sync_state === "local_override" ? "Lokal geändert" : competition.external_id ? "Intervals.icu" : "Lokal";
    card.append(source);
    const details = document.createElement("div");
    details.className = "competition-card-facts";
    const optional = [
      ["Startzeit", competition.start_date_local ? formatLocalCompetitionTime(competition.start_date_local) : null],
      ["Ziel", competition.target],
      ["Erwartete Dauer", competition.moving_time == null ? null : AppFormat.duration(competition.moving_time)],
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
    node.textContent = status === "error" ? (hasData ? "Gespeicherter Stand. Aktualisierung fehlgeschlagen." : "Wettkämpfe konnten nicht geladen werden.")
      : status === "loading" ? (hasData ? "Gespeicherter Stand wird aktualisiert …" : "Wettkämpfe werden geladen …") : "";
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
  return Object.freeze({ renderAdaptivePlanning, renderExternalCalendar, renderTrainingPlans, renderPlanned, renderLibrary, renderCompetitions, renderCompetitionReadStatus, focusPlannedToday, bindPlanNavigation, bindExternalCalendar });
}
