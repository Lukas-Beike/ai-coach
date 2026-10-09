globalThis.AppPlanViews = Object.freeze({ create });

function plannedAppointmentLabel(event) {
  if (!event || typeof event !== "object") return "";
  const name = String(event.name || "Trainingstermin").trim() || "Trainingstermin";
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

function calendarMetricNumber(value, suffix = "") {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const digits = Number.isInteger(number) ? 0 : 1;
  return `${number.toLocaleString("de-DE", { maximumFractionDigits: digits })}${suffix}`;
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

function appendCalendarFact(root, label, value) {
  if (value == null || value === "") return;
  const item = document.createElement("span");
  const title = document.createElement("strong");
  title.textContent = label;
  item.append(title, document.createTextNode(` ${value}`));
  root.append(item);
}

function competitionSportLabel(sport) {
  return ({ Cycling: "Radfahren", Ride: "Radfahren", VirtualRide: "Rad indoor", Running: "Laufen", Run: "Laufen", Swim: "Schwimmen", Strength: "Krafttraining" })[sport] || sport || "–";
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

function create({ $, state, dateLabel, formatTime, formatDuration, formatPace, formatWhole, distanceLabel, activitySportLabel, analysisSvg, api, showAccessibleDialog, appendHistoryPageButton, AppRouter, dateFromKey, localDateKey, addDateKey, weatherNumber, weatherIconFor, weatherDirection, plannedEventDate, timezoneDateKey, calendarDisplayValue }) {
  function renderAdaptivePlanning(data) {
    const planning = data.planning || {};
    const next = planning.season?.next_event;
    const summary = $("#planningSummary");
    if (summary) {
      summary.textContent = next
        ? `Nächster Wettkampf: ${next.name} am ${dateLabel(next.event_date)} · Phase: ${next.phase} · ${next.days_until} Tage`
        : "Noch kein zukünftiger Wettkampf gespeichert.";
    }
    const preview = planning.latest_replan;
    const changes = Array.isArray(preview?.changes) ? preview.changes : [];
    const illness = String(data.local_feedback?.today?.illness || "").trim();
    const previewIllness = String(preview?.illness_pause?.illness || "").trim();
    const illnessNeedsForecast = Boolean(illness && (!preview?.illness_pause || previewIllness !== illness || !preview.illness_pause?.approved));
    const pendingIllnessPause = Boolean(preview?.status === "preview" && preview?.illness_pause && !preview.illness_pause.approved);
    const required = Boolean(planning.needs_replan || illnessNeedsForecast || pendingIllnessPause);
    const count = Number(planning.replan_changes || changes.length);
    let caption;
    if (illnessNeedsForecast || pendingIllnessPause) caption = "Krankheit gemeldet: Sportpause prognostizieren und bestätigen.";
    else if (count === 1) caption = "Ein zukünftiger Entwurf braucht eine Anpassung.";
    else caption = `${count} zukünftige Entwürfe brauchen eine Anpassung.`;
    const coachNotice = $("#coachAdaptivePlanningNotice");
    if (coachNotice) {
      coachNotice.hidden = !required;
      const detail = coachNotice.querySelector("small");
      if (detail) detail.textContent = required ? `${caption} Bitte den Coach um die Anpassung.` : "";
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

  function appendPlannedWeatherInsight(body, weather) {
    const weatherLabel = plannedWeatherLabel(weather);
    if (!weather || !weatherLabel) return;
    const condition = document.createElement("p");
    condition.className = "planned-weather-detail";
    condition.textContent = [weather.condition, weatherLabel].filter(Boolean).join(" · ");
    condition.title = [
      weather.archived_forecast ? "Gespeicherte Wettervorhersage" : "Wettervorhersage",
      "Open-Meteo", weather.forecast_location || state.data?.weather?.location?.name,
      weather.forecast_saved_at ? `Stand: ${formatTime(weather.forecast_saved_at)}` : null,
    ].filter(Boolean).join(" · ");
    body.append(condition);
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
    if (values.length) {
      const metrics = document.createElement("p");
      metrics.className = "planned-weather-metrics";
      metrics.textContent = values.join(" · ");
      body.append(metrics);
    }
  }

  function plannedDayInsights(weather) {
    const content = document.createElement("div");
    content.className = "planned-insights-content";
    appendPlannedWeatherInsight(content, weather);
    if (!content.childElementCount) return null;
    const section = document.createElement("div");
    section.className = "planned-day-insights";
    const title = document.createElement("p");
    title.className = "planned-insights-title";
    title.textContent = "Wetter";
    section.append(title, content);
    return section;
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

  function calendarEntryStatus(entry, dateKey, todayKey) {
    if (calendarActualActivity(entry)) return "completed";
    if (entry?.compliance?.status === "missed") return "missed";
    return dateKey === todayKey ? "today" : "planned";
  }

  function calendarStatusLabel(entry, dateKey, todayKey) {
    const status = calendarEntryStatus(entry, dateKey, todayKey);
    if (status === "completed") return entry.is_completed_activity ? "✓ Zusätzlich absolviert" : "✓ Abgeschlossen";
    if (status === "missed") return "Nicht absolviert";
    return status === "today" ? "Heute geplant" : "Geplant";
  }

  function calendarRpeLabel(value) {
    if (value == null || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 && number <= 10 ? calendarMetricNumber(number) : null;
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

  function plannedEntryDurationLabel(actual, entry) {
    if (actual) return formatDuration(actual.moving_time ?? actual.elapsed_time);
    if (entry.duration_minutes) return `${entry.duration_minutes} Min.`;
    return formatDuration(entry.moving_time);
  }

  function appendActualCalendarDetails(details, actual) {
    if (!actual) return;
    const primaryMetrics = document.createElement("span");
    primaryMetrics.className = "planned-actual-summary";
    const load = calendarMetricNumber(actual.icu_training_load);
    const rpe = calendarRpeLabel(actual.icu_rpe);
    primaryMetrics.textContent = [load != null ? `Load ${load}` : null, rpe != null ? `RPE ${rpe}/10` : "RPE offen"].filter(Boolean).join(" · ");
    const facts = document.createElement("div");
    facts.className = "planned-actual-facts";
    appendCalendarFact(facts, "Dauer", formatDuration(actual.moving_time ?? actual.elapsed_time));
    appendCalendarFact(facts, "Distanz", distanceLabel(actual.distance));
    appendCalendarFact(facts, "Trainingsload", calendarMetricNumber(actual.icu_training_load));
    appendCalendarFact(facts, "RPE", rpe != null ? `${rpe}/10` : "nicht angegeben");
    appendCalendarFact(facts, "Intensität", calendarIntensityLabel(actual.icu_intensity));
    appendCalendarFact(facts, "Ø Puls", calendarMetricNumber(actual.average_heartrate, " bpm"));
    appendCalendarFact(facts, "Ø Leistung", calendarMetricNumber(actual.weighted_average_watts ?? actual.average_watts, " W"));
    appendCalendarFact(facts, "Pace", calendarPaceLabel(actual));
    appendCalendarFact(facts, "Höhenmeter", calendarMetricNumber(actual.total_elevation_gain, " hm"));
    details.append(primaryMetrics, facts);
  }

  function appendPlannedCalendarComparison(details, entry, actual) {
    if (!actual || entry.is_completed_activity) return;
    const comparison = document.createElement("div");
    comparison.className = "planned-comparison";
    const plannedDuration = entry.duration_minutes ? Number(entry.duration_minutes) * 60 : entry.moving_time;
    const planLine = document.createElement("p");
    planLine.textContent = `Plan: ${[
      entry.name,
      formatDuration(plannedDuration),
      entry.icu_training_load != null ? `Load ${calendarMetricNumber(entry.icu_training_load)}` : null,
    ].filter(Boolean).join(" · ")}`;
    const actualLine = document.createElement("p");
    actualLine.textContent = `Ist: ${[
      formatDuration(actual.moving_time ?? actual.elapsed_time),
      actual.icu_training_load != null ? `Load ${calendarMetricNumber(actual.icu_training_load)}` : null,
    ].filter(Boolean).join(" · ")}`;
    comparison.append(planLine, actualLine);
    if (entry.compliance?.percentage != null) {
      const ratio = document.createElement("p");
      ratio.textContent = `${entry.compliance.basis === "training_load" ? "Load" : "Umfang"} Plan/Ist: ${entry.compliance.percentage} %`;
      comparison.append(ratio);
    }
    details.append(comparison);
  }

  function appendPlannedSessionHeader(cardSummary, entry, actual) {
    const displayed = actual || entry;
    const header = document.createElement("span");
    header.className = "planned-session-header";
    const sport = document.createElement("span");
    sport.textContent = [activitySportLabel(displayed), calendarStartTime(displayed.start_date_local)].filter(Boolean).join(" · ");
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
      calendarMetricNumber(displayed.icu_training_load) != null ? `Belastung ${calendarMetricNumber(displayed.icu_training_load)}` : null,
    ].filter(Boolean).join(" · ");
    cardSummary.append(header);
    if (metrics.textContent) cardSummary.append(metrics);
  }

  function appendPlannedExecution(cardSummary, entry, status) {
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

  let calendarProfileSequence = 0;

  function calendarWorkoutProfile(profile) {
    const segments = profile?.segments;
    if (!Array.isArray(segments) || !segments.length || segments.length > 1000) return null;
    const total = segments.reduce((sum, item) => sum + (Number.isFinite(item.duration) && item.duration > 0 ? item.duration : 0), 0);
    const values = segments.flatMap((item) => [item.value, item.end_value]).filter((value) => value != null && Number.isFinite(value) && value >= 0);
    if (!total || !values.length) return null;
    const top = Math.max(...values, 1) * 1.1;
    const label = profile.source === "recorded" ? "Aufgezeichnetes Belastungsprofil" : "Geplantes Intervallprofil";
    const svg = analysisSvg("svg", { viewBox: "0 0 300 56", role: "img", "aria-label": label, class: "calendar-workout-profile", preserveAspectRatio: "none" });
    const gradientPrefix = `calendar-profile-${++calendarProfileSequence}`;
    const defs = analysisSvg("defs");
    for (const zone of [1, 2, 3, 4, 5, 6, 7, "unknown"]) {
      const gradient = analysisSvg("linearGradient", { id: `${gradientPrefix}-${zone}`, x1: 0, y1: 0, x2: 0, y2: 1, "data-zone": zone });
      gradient.append(analysisSvg("stop", { offset: "0%", "stop-color": "currentColor" }));
      gradient.append(analysisSvg("stop", { offset: "100%", "stop-color": "currentColor", "stop-opacity": .35 }));
      defs.append(gradient);
    }
    svg.append(defs);
    svg.append(analysisSvg("title", {}, `${label} · Zeitachse · ${profile.unit || ""}`));
    svg.append(analysisSvg("line", { x1: 0, x2: 300, y1: 54, y2: 54, class: "calendar-profile-baseline" }));
    let offset = 0;
    for (const item of segments) {
      if (!Number.isFinite(item.duration) || item.duration <= 0) continue;
      const x = offset / total * 300, width = item.duration / total * 300;
      offset += item.duration;
      if (item.value == null || item.end_value == null || !Number.isFinite(item.value) || !Number.isFinite(item.end_value)) continue;
      const left = 54 - Math.max(0, item.value) / top * 50;
      const right = 54 - Math.max(0, item.end_value) / top * 50;
      const zone = Number.isInteger(item.zone) && item.zone >= 1 && item.zone <= 7 ? item.zone : "unknown";
      const shape = analysisSvg("polygon", { points: `${x},54 ${x},${left} ${x + width},${right} ${x + width},54`, "data-zone": zone, fill: `url(#${gradientPrefix}-${zone})` });
      shape.append(analysisSvg("title", {}, `${formatDuration(item.duration)} · ${item.label || ""}`));
      svg.append(shape);
    }
    return svg;
  }

  function renderPlannedEntry(entry, dateKey, todayKey) {
    const actual = calendarActualActivity(entry);
    const status = calendarEntryStatus(entry, dateKey, todayKey);
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
      calendarStartTime(displayed.start_date_local),
      plannedEntryDurationLabel(actual, entry),
    ].filter(Boolean).join(" · ");
    appendPlannedSessionHeader(cardSummary, entry, actual);
    cardSummary.append(meta);
    if (status === "completed" || status === "missed") {
      const statusText = document.createElement("span");
      statusText.className = "planned-entry-status";
      statusText.textContent = calendarStatusLabel(entry, dateKey, todayKey);
      cardSummary.append(statusText);
    }
    appendPlannedExecution(cardSummary, entry, status);
    const profile = calendarWorkoutProfile(actual?.workout_profile || entry.workout_profile);
    if (profile) cardSummary.append(profile);
    cardSummary.append(cardTitle);
    if (actual && !entry.is_completed_activity) {
      const target = document.createElement("span");
      target.className = "planned-session-target";
      const targetParts = [entry.name || "Training", plannedEntryDurationLabel(null, entry)];
      if (entry.icu_training_load != null) targetParts.push(`Belastung ${calendarMetricNumber(entry.icu_training_load)}`);
      target.textContent = `Plan: ${targetParts.join(" · ")}`;
      cardSummary.append(target);
    }
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
      weatherText.title = [weather.archived_forecast ? "Gespeicherte Wettervorhersage" : "Wettervorhersage", weather.condition, weatherLabel].filter(Boolean).join(": ");
      weatherText.setAttribute("aria-label", weatherText.title);
      heading.append(weatherText);
    } else {
      const weatherMissing = document.createElement("span");
      weatherMissing.className = "planned-day-weather is-missing";
      weatherMissing.textContent = "Wetter fehlt";
      if (!state.data?.weather?.configured) weatherMissing.title = "Kein Wetterort im Profil hinterlegt";
      else if (dateKey < todayKey) weatherMissing.title = "Für diesen Tag wurde keine Vorhersage gespeichert";
      else weatherMissing.title = "Für diesen Tag ist keine Vorhersage verfügbar";
      heading.append(weatherMissing);
    }
    day.append(heading);
  }

  function plannedDayNotes(dayContext) {
    const notes = document.createElement("div");
    notes.className = "planned-day-notes";
    const appointments = (Array.isArray(dayContext.appointments) ? dayContext.appointments : [])
      .filter((event) => event && event.training_relevant !== false)
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
    if (notes.childElementCount) content.append(notes);
    if (!dayEntries.length) {
      const empty = document.createElement("p");
      empty.className = "planned-day-empty";
      empty.textContent = dateKey < todayKey ? "Keine Aktivität" : "Keine Einheit geplant";
      content.append(empty);
    }
    dayEntries.forEach((entry) => content.append(renderPlannedEntry(entry, dateKey, todayKey)));
    const insights = plannedDayInsights(weather);
    if (insights) day.append(insights);
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
      ["Geplant", formatDuration(plannedSeconds)],
      ["Absolviert", formatDuration(actualSeconds)],
      ["Distanz", actual.length && actual.every((entry) => entry.distance != null) ? distanceLabel(sum(actual, (entry) => entry.distance)) || "0 km" : "–"],
      ["Belastung geplant", planned.length && planned.every((entry) => entry.icu_training_load != null) ? calendarMetricNumber(sum(planned, (entry) => entry.icu_training_load)) : "–"],
      ["Belastung absolviert", actual.length && actual.every((entry) => entry.icu_training_load != null) ? calendarMetricNumber(sum(actual, (entry) => entry.icu_training_load)) : "–"],
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
    const snapshot = JSON.stringify([trainingCalendar, todayKey, display, state.data?.daily_planning_context, state.data?.planning_compliance]);
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
      empty.textContent = "Noch keine Einheiten in der Bibliothek.";
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



  function competitionCard(competition = {}, index = 0) {
    const card = document.createElement("article");
    card.className = "competition-card";

    const top = document.createElement("div");
    top.className = "competition-card-top";
    const title = document.createElement("strong");
    title.textContent = competition.name || `Wettkampf ${index + 1}`;
    const priority = document.createElement("span");
    priority.className = "competition-priority";
    priority.textContent = `${competition.priority || "B"}-Wettkampf`;
    top.append(title, priority);

    if (competition.sync_state === "local_override") {
      const status = document.createElement("small");
      status.className = "competition-sync-state";
      status.textContent = "Lokal priorisiert · der Coach kann den nächsten Sync ausführen";
      card.append(status);
    }

    const facts = document.createElement("div");
    facts.className = "competition-card-facts";
    facts.append(
      competitionFact("Datum", competition.event_date ? dateLabel(competition.event_date) : ""),
      competitionFact("Sportart", competitionSportLabel(competition.sport)),
      competitionFact("Distanz", distanceLabel(competition.distance)),
      competitionFact("Zielpace / Zielzeit", competition.target)
    );
    const additional = document.createElement("details");
    additional.className = "competition-additional-fields";
    const additionalSummary = document.createElement("summary");
    additionalSummary.textContent = "Weitere Intervals.icu-Felder";
    const additionalGrid = document.createElement("div");
    additionalGrid.className = "competition-card-facts competition-additional-grid";
    additionalGrid.append(
      competitionFact("Startzeit", competition.start_date_local ? formatLocalCompetitionTime(competition.start_date_local) : ""),
      competitionFact("Erwartete Dauer (hh:mm)", formatDuration(competition.moving_time)),
      competitionFact("Streckenprofil", competition.course_profile),
      competitionFact("Beschreibung", competition.description),
      competitionFact("Notizen", competition.notes)
    );
    additional.append(additionalSummary, additionalGrid);
    card.append(top, facts, additional);
    return card;
  }

  function renderCompetitions(competitions) {
    const root = $("#competitionList");
    const summary = $("#plannedCompetitionsSummary");
    if (summary) {
      const next = competitions.filter((competition) => competition.event_date).sort((a, b) => String(a.event_date).localeCompare(String(b.event_date)))[0];
      if (!competitions.length) summary.textContent = "Noch keine Wettkämpfe";
      else {
        const competitionLabel = competitions.length === 1 ? "Wettkampf" : "Wettkämpfe";
        const nextLabel = next ? ` · nächster ${dateLabel(next.event_date)}` : "";
        summary.textContent = `${competitions.length} ${competitionLabel}${nextLabel}`;
      }
    }
    root.replaceChildren();
    if (!competitions.length) {
      const empty = document.createElement("p");
      empty.className = "context-empty";
      empty.textContent = "Noch keine Zielwettkämpfe gespeichert.";
      root.append(empty);
      return;
    }
    [...competitions]
      .sort((a, b) => String(a.event_date || "9999-12-31").localeCompare(String(b.event_date || "9999-12-31")))
      .forEach((competition, index) => root.append(competitionCard(competition, index)));
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
  return Object.freeze({ renderAdaptivePlanning, renderExternalCalendar, renderTrainingPlans, renderPlanned, renderLibrary, renderCompetitions, focusPlannedToday, bindPlanNavigation, bindExternalCalendar });
}
