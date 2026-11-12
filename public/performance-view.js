const SESSION_SPORT_LABELS = { ride: "Radfahren", run: "Laufen", swim: "Schwimmen", strength: "Kraft" };

// Takes a planned/provider `type` or a session's neutral `sport` and `environment`.
function activitySportLabel(activity) {
  if (!activity?.type && activity?.sport) {
    if (activity.sport === "ride" && ["indoor", "virtual"].includes(activity.environment)) return "Rad indoor";
    return SESSION_SPORT_LABELS[activity.sport] || "Andere";
  }
  const value = String(activity?.type || "").toLowerCase();
  if (value === "virtualride") return "Rad indoor";
  if (/ride|bike|cycling|rad|velo|bicycle/.test(value)) return "Radfahren";
  if (/run|lauf|jog/.test(value)) return "Laufen";
  if (/swim|schwimm/.test(value)) return "Schwimmen";
  if (/strength|kraft|gym|weight/.test(value)) return "Kraft";
  return "Andere";
}



function garminPerformanceSources(garmin) {
  return [garmin.has_vo2max ? "VO2max" : null, garmin.has_estimated_run_times ? "Laufprognosen" : null, garmin.has_max_hr ? "Max HF" : null, garmin.has_weight ? "Gewicht" : null].filter(Boolean);
}

function garminPaginationDetail(garmin) {
  return Object.entries(garmin.pagination || {})
    .filter(([, value]) => value && (Number(value.windows) > 1 || value.complete === false))
    .map(([name, value]) => `${name}: ${value.records || 0} Datensätze in ${value.windows || 0} Zeitfenstern${value.complete === false ? " · unvollständig" : ""}`)
    .join(" · ");
}

function garminBodyBatteryDetail(garmin) {
  const bodyBattery = garmin.morning_body_battery || {};
  const beforeSleep = Number(bodyBattery.before_sleep?.value);
  const morning = Number(bodyBattery.morning?.value);
  if (bodyBattery.status === "ready" && Number.isFinite(beforeSleep) && Number.isFinite(morning)) {
    return `Body Battery am ${dateLabel(bodyBattery.sleep_date)}: ${beforeSleep} vor dem Schlafen → ${morning} nach dem Aufwachen`;
  }
  return bodyBattery.sleep_date ? `Body Battery am ${dateLabel(bodyBattery.sleep_date)}: nicht verfügbar` : "";
}

function garminDetailText(garmin) {
  let sourceDetail = "Noch kein Garmin-Abruf durchgeführt.";
  if (garmin.last_sync_at) {
    sourceDetail = `Letzter Abruf: ${formatTime(garmin.last_sync_at)} · ${garmin.activities || 0} Aktivitäten · Schlaf/HRV/Readiness ${[garmin.has_sleep, garmin.has_hrv, garmin.has_readiness].filter(Boolean).length}/3`;
  } else if (garmin.source === "fixture") {
    sourceDetail = "Testdatei ist konfiguriert; synchronisiere sie mit dem Button.";
  }
  const performance = garminPerformanceSources(garmin);
  return [sourceDetail, performance.length ? `${performance.join("/")} aus Garmin` : "", garminBodyBatteryDetail(garmin), garminPaginationDetail(garmin)].filter(Boolean).join(" · ");
}

function renderGarminFullResync(data, garmin = data?.garmin || {}) {
  const fullResync = data?.provider_resync?.garmin || {};
  const fullRunning = Boolean(fullResync.running || state.localSync.garminFull);
  const usable = Boolean(garmin.available && garmin.configured);
  const fullButton = $("#garminFullResyncButton");
  if (fullButton) {
    renderFullResyncButton(fullButton, {
      running: fullRunning,
      blocked: !usable || Boolean(data?.garmin_sync?.running || state.localSync.garmin),
      idleLabel: "Lokale Daten neu laden",
    });
  }
  const fullStatus = $("#garminFullResyncStatus");
  if (!fullStatus || !usable) return;
  fullStatus.classList.toggle("error", Boolean(fullResync.last_error));
  let statusText = "";
  if (fullRunning && fullResync.status) statusText = fullResync.status;
  else if (fullResync.last_error) statusText = fullResync.last_error;
  else if (fullResync.last_resync_at) statusText = `Letzter vollständiger Resync: ${formatTime(fullResync.last_resync_at)}`;
  fullStatus.textContent = statusText;
  resumeFullResync(providerIds().garmin);
}

function renderUnavailableGarmin(garmin, status, detail, button) {
  const unavailable = !garmin?.available;
  if (!unavailable && garmin.configured) return false;
  status.textContent = unavailable ? "Garmin nicht verfügbar" : "Garmin nicht eingerichtet";
  detail.textContent = "";
  button.disabled = true;
  return true;
}

function renderGarminKeyHint(garmin) {
  const node = $("#garminKeyHint");
  if (!node) return;
  const hint = garminKeyHint(garmin);
  node.textContent = hint.text;
  node.hidden = !hint.text;
  node.classList.toggle("error", hint.urgent);
}

function renderGarmin(garmin) {
  const status = $("#garminStatus");
  const detail = $("#garminDetail");
  const button = $("#garminSyncButton");
  if (!status || !detail || !button) return;
  renderGarminKeyHint(garmin);
  const fullResync = state.data?.provider_resync?.garmin || {};
  const fullRunning = Boolean(fullResync.running || state.localSync.garminFull);
  button.disabled = Boolean(state.data?.garmin_sync?.running || fullRunning);
  const unavailable = renderUnavailableGarmin(garmin, status, detail, button);
  renderGarminFullResync(state.data, garmin);
  if (unavailable) return;
  if (garmin.source === "fixture") status.textContent = "Lokale Garmin-Testdaten aktiv";
  else if (garmin.last_error) status.textContent = "Mit Fehlern synchronisiert";
  else status.textContent = "Optionaler Direktabruf aktiv";
  detail.textContent = garminDetailText(garmin);
}


function currentPerformanceValues(metrics, history) {
  const values = { ...metrics };
  const preferred = history?.body?.preferred_providers?.cycling_w_per_kg;
  const points = (history?.body?.windows?.["12w"]?.metrics?.cycling_w_per_kg || []).flatMap((item) => (item.points || []).filter(analysisValidPoint).map((point) => ({ ...point, source: item.source, ..."source_provider" in item ? { source_provider: item.source_provider } : {}, unit: "W/kg" }))).sort((a, b) => b.date.localeCompare(a.date) || Number(isPreferredSource(b, preferred)) - Number(isPreferredSource(a, preferred)));
  // The preferred provider's newest point wins even when another provider is newer; others only fill in when it has none.
  values.cycling_w_per_kg = (preferred === undefined ? undefined : points.find((point) => isPreferredSource(point, preferred))) || points[0];
  return values;
}

function performanceDataStatus(performance) {
  return typeof performance?.status === "string" && performance.status ? [performance.status] : [];
}

// Device-computed estimates; thresholds are entered or device-reported values and carry no chip.
const ESTIMATED_METRICS = new Set(["running_vo2max_ml_kg_min", "cycling_vo2max_ml_kg_min"]);

// One row per metric with a value, in the given order.
function currentPerformanceRows(metrics, items) {
  const body = reportNode("tbody");
  for (const [key, label] of items) {
    const metric = metrics?.[key];
    if (metric?.value == null) continue;
    const row = reportNode("tr"); row.dataset.metric = key;
    const heading = reportNode("th", label); heading.scope = "row";
    if (ESTIMATED_METRICS.has(key)) heading.append(" ", createEstimateChip());
    row.append(heading, reportNode("td", analysisValue(metric.value, metric.unit || "")));
    body.append(row);
  }
  return body;
}

function renderCurrentPerformance(metrics, history, status = []) {
  metrics = currentPerformanceValues(metrics, history);
  const root = document.getElementById("currentPerformance");
  rememberAnalysisSectionState(root);
  root.replaceChildren(reportNode("h3", "Aktuelle Werte"));
  for (const text of status) root.append(reportNode("p", text, "empty"));
  const groups = [
    ["Laufen", "run", [
      ["run_threshold_pace_seconds_per_km", "Schwellenpace"],
      ["run_threshold_watts", "Schwellenleistung"],
      ["run_threshold_hr_bpm", "Schwellenpuls (LSHF)"],
      ["running_vo2max_ml_kg_min", "VO\u2082max"],
    ]],
    ["Radfahren", "ride", [
      ["cycling_ftp_watts", "FTP"],
      ["cycling_w_per_kg", "Leistung pro Gewicht"],
      ["bike_threshold_hr_bpm", "Schwellenpuls (LSHF)"],
      ["cycling_vo2max_ml_kg_min", "VO\u2082max"],
    ]],
  ];
  const grid = reportNode("div", null, "current-performance-groups");
  // Laufen and Radfahren each show their own table (#2265); the caption names it for screen readers.
  for (const [sport, analysisSport, items] of groups) {
    const table = reportNode("table", null, "current-performance-table");
    table.dataset.analysisSport = analysisSport;
    table.append(reportNode("caption", sport, "sr-only"));
    const body = currentPerformanceRows(metrics, items);
    // A status message (e.g. a failed read) keeps the section visible.
    root.dataset[analysisSport === "run" ? "analysisEmptyRunning" : "analysisEmptyCycling"] = String(!body.childElementCount && !status.length);
    if (!body.childElementCount) {
      const none = reportNode("p", "Noch keine aktuellen Werte.", "muted");
      none.dataset.analysisSport = analysisSport;
      grid.append(none);
      continue;
    }
    table.append(body);
    grid.append(table);
  }
  root.dataset.analysisEmpty = String(root.dataset.analysisEmptyRunning === "true" && root.dataset.analysisEmptyCycling === "true");
  root.append(grid);
  makeAnalysisSectionCollapsible(root, "current-performance");
}

function renderPerformance(performance, { refreshCharts = true } = {}) {
  if (refreshCharts) {
    void renderTrainingRecords();
    renderPersonalRecovery(performance?.personal_recovery);
    renderAnalysisHistory(performance?.history);
    void renderCyclingPowerProfile();
    renderTrainingFocus(performance?.training_focus_periods?.[analysisHistoryPeriod] || performance?.training_focus);
  }
  const root = $("#performancePredictions");
  root.replaceChildren();
  const values = performance?.metrics || {};
  renderCurrentPerformance(values, performance?.history, performanceDataStatus(performance));
  const predictions = racePredictionRows(values);
  root.hidden = false;
  const predictionHeading = reportNode("h4", "Laufprognosen");
  predictionHeading.append(" ", createEstimateChip());
  root.append(predictionHeading);
  root.dataset.analysisEmpty = String(!predictions.length);
  if (!predictions.length) {
    root.append(reportNode("p", racePredictionEmptyReason(values), "muted"));
  } else {
    const table = reportNode("table", null, "race-predictions-table");
    const head = reportNode("thead");
    const header = reportNode("tr");
    for (const label of ["Distanz", "Gesch\u00e4tzte Zeit"]) {
      const cell = reportNode("th", label); cell.scope = "col"; header.append(cell);
    }
    head.append(header); table.append(head);
    const body = reportNode("tbody");
    for (const { label, metric } of predictions) {
      const row = reportNode("tr");
      const distance = reportNode("th", label); distance.scope = "row";
      row.append(distance, reportNode("td", predictionTime(metric.value)));
      body.append(row);
    }
    table.append(body);
    const scroll = makeScrollRegionFocusable(reportNode("div", null, "table-scroll"), "Geschätzte Zeiten nach Distanz");
    scroll.append(table); root.append(scroll);
  }
  renderAnalysisSegments(state.route);
}

// Model estimates are shown in whole minutes: "25 min", "3:55 h".
function predictionTime(seconds) {
  const minutes = Math.round(Number(seconds) / 60);
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")} h`;
}

function racePredictionRows(metrics) {
  const distances = [["run_5k_seconds", "5 km"], ["run_10k_seconds", "10 km"],
    ["run_half_marathon_seconds", "Halbmarathon"], ["run_marathon_seconds", "Marathon"]];
  const values = metrics || {};
  return distances.filter(([key]) => values[key]?.value != null).map(([key, label]) => ({ label, metric: values[key] }));
}

function racePredictionEmptyReason(metrics) {
  const values = metrics || {};
  const runningValues = ["run_threshold_pace_seconds_per_km", "running_vo2max_ml_kg_min"].some((key) => values[key]?.value != null);
  return runningValues
    ? "Noch keine Prognosen – Laufwerte sind vorhanden, aber es wurde keine Laufprognose geliefert."
    : "Noch keine Prognosen – dafür fehlen aktuelle Leistungswerte aus Garmin oder Wahoo.";
}
