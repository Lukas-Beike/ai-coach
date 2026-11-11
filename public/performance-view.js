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


function comparisonText(comparison) {
  if (comparison?.delta == null) return null;
  const delta = Number(comparison.delta);
  if (!Number.isFinite(delta)) return null;
  let sign;
  if (delta > 0) sign = "+";
  else if (delta < 0) sign = "−";
  else sign = "±";
  const precision = comparison.unit === "" || comparison.unit === "bpm" || comparison.unit === "ms" ? 0 : 1;
  const amount = Math.abs(delta).toFixed(precision).replace(".", ",");
  const unit = comparison.unit ? ` ${comparison.unit}` : "";
  let arrow;
  if (comparison.direction === "up") arrow = "↑";
  else if (comparison.direction === "down") arrow = "↓";
  else arrow = "→";
  const comparisonLabel = comparison.label || `${comparison.days}-Tage-Durchschnitt`;
  return { text: `${arrow} ${sign}${amount}${unit}`, className: comparison.color || "neutral", title: `Vergleich zum ${comparisonLabel}` };
}

function metricSourceClass(metricData) {
  const provider = metricData?.source_provider;
  if (typeof provider === "string" && /^[a-z0-9-]+$/.test(provider)) return `metric-${provider}`;
  const source = metricData?.source;
  if (source === "Manuell") return "metric-manual";
  if (source === "Aus Aktivitäten") return "metric-intervals";
  return "";
}

function metricToneClass(label, value) {
  if (!label.startsWith("Form") || !Number.isFinite(Number(value))) return "";
  const tsb = Number(value);
  if (tsb >= -10 && tsb <= 5) return "metric-form-good";
  if (tsb >= -20 && tsb <= 15) return "metric-form-caution";
  return "metric-form-bad";
}

function metricValueParts(metricData) {
  return {
    value: metricData && typeof metricData === "object" ? metricData.value : metricData,
    unit: metricData && typeof metricData === "object" ? metricData.unit : "",
  };
}

function metricSourceDetails(metricData) {
  const source = document.createElement("small");
  source.textContent = metricData?.source || "Nicht verfügbar";
  const freshnessLabel = { stale: "Veraltet", partial: "Teilweise aktualisiert", unknown: "Aktualität unbekannt" }[metricData?.freshness];
  if (freshnessLabel) source.textContent += ` · ${freshnessLabel}`;
  if (metricData?.observed_at) source.textContent += ` · Messung ${dateLabel(String(metricData.observed_at).slice(0, 10))}`;
  else if (freshnessLabel && metricData?.fetched_at) source.textContent += ` · Stand ${formatTime(metricData.fetched_at)}`;
  if (metricData?.measurement_status === "earlier" && Number.isFinite(metricData.measurement_age_days)) {
    const ageLabel = metricData.measurement_age_days === 1 ? "Tag" : "Tage";
    source.textContent += ` · ${metricData.measurement_age_days} ${ageLabel} alt`;
  } else if (metricData?.measurement_status === "unknown") source.textContent += " · Messdatum unbekannt";
  else if (metricData?.measurement_status === "future") source.textContent += " · Messdatum liegt in der Zukunft";
  source.title = [metricData?.note || metricData?.source || "", metricData?.fetched_at ? `Abgerufen ${formatTime(metricData.fetched_at)}` : ""].filter(Boolean).join(" · ");
  source.className = metricSourceClass(metricData);
  return source;
}

function metricComparisonBadge(comparison) {
  const details = comparisonText(comparison);
  if (!details) return null;
  const badge = document.createElement("small");
  badge.className = `metric-comparison ${details.className}`;
  badge.textContent = details.text;
  badge.title = details.title;
  return badge;
}

function metricEditor(item, metric, label, value, editable) {
  if (!editable?.key) return null;
  item.classList.add("metric-editable");
  const edit = document.createElement("button");
  edit.type = "button";
  edit.className = "metric-edit-button";
  edit.textContent = "✎";
  edit.title = `${label} bearbeiten`;
  edit.setAttribute("aria-label", edit.title);
  const input = document.createElement("input");
  input.className = "metric-edit-input";
  input.type = "number";
  input.step = editable.step || "any";
  input.min = editable.min ?? "0";
  input.value = state.data?.profile?.[editable.key] || (value == null ? "" : value);
  input.hidden = true;
  edit.addEventListener("click", () => {
    const editing = item.classList.toggle("editing");
    input.hidden = !editing;
    metric.hidden = editing;
    edit.textContent = editing ? "✓" : "✎";
    edit.title = editing ? "Wert speichern" : `${label} bearbeiten`;
    edit.setAttribute("aria-label", edit.title);
    if (editing) { input.focus(); input.select(); }
    else void saveInlineMetric(editable.key, input.value, edit);
  });
  return { edit, input };
}

function displayMetric(root, label, metricData, formatter = null, editable = null) {
  const item = document.createElement("div");
  const metric = document.createElement("strong");
  const caption = document.createElement("span");
  const source = metricSourceDetails(metricData);
  const { value, unit } = metricValueParts(metricData);
  // A tile without a value is hidden; an editable one stays so the value can still be entered.
  if (value == null && !editable?.key) return;
  if (value == null) metric.textContent = "—";
  else if (formatter) metric.textContent = formatter(value);
  else metric.textContent = `${value}${unit ? " " + unit : ""}`;
  caption.textContent = label;
  for (const className of [metricSourceClass(metricData), metricToneClass(label, value)]) {
    if (className) item.classList.add(className);
  }
  const valueRow = document.createElement("div");
  valueRow.className = "metric-value-row";
  valueRow.append(metric);
  const badge = metricComparisonBadge(metricData?.comparison);
  if (badge) {
    valueRow.append(badge);
  }
  const editor = metricEditor(item, metric, label, value, editable);
  if (editor) {
    item.append(valueRow, editor.input, caption, source, editor.edit);
  } else {
    item.append(valueRow, caption, source);
  }
  root.append(item);
}

async function saveInlineMetric(key, value, button) {
  button.disabled = true;
  try {
    // PUT /api/profile applies only this metric to the server's current profile.
    const profile = { [key]: String(value || "").trim() };
    const saved = await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    if (!Object.keys(profile).every((key) => Object.hasOwn(saved, key) && typeof saved[key] === "string")) {
      throw new Error("Die Profilbestätigung ist unvollständig. Der Entwurf bleibt erhalten.");
    }
    toast("Wert gespeichert und für den Coach aktiviert");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
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

function renderCurrentPerformance(metrics, history, status = []) {
  metrics = currentPerformanceValues(metrics, history);
  const root = document.getElementById("currentPerformance");
  rememberAnalysisSectionState(root);
  root.replaceChildren(reportNode("h3", "Aktuelle Leistungswerte"));
  for (const text of status) root.append(reportNode("p", text, "empty"));
  const groups = [
    ["Laufen", [
      ["run_threshold_pace_seconds_per_km", "Schwellenpace"],
      ["run_threshold_watts", "Schwellenleistung"],
      ["run_threshold_hr_bpm", "Schwellenpuls (LSHF)"],
      ["running_vo2max_ml_kg_min", "VO\u2082max"],
    ]],
    ["Radfahren", [
      ["cycling_ftp_watts", "FTP"],
      ["cycling_w_per_kg", "Leistung pro Gewicht"],
      ["bike_threshold_hr_bpm", "Schwellenpuls (LSHF)"],
      ["cycling_vo2max_ml_kg_min", "VO\u2082max"],
    ]],
  ];
  const grid = reportNode("div", null, "current-performance-groups");
  for (const [sport, items] of groups) {
    const table = reportNode("table", null, "current-performance-table");
    table.append(reportNode("caption", sport));
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
    if (!body.childElementCount) continue;
    table.append(body);
    grid.append(table);
  }
  // A status message (e.g. a failed read) keeps the section visible.
  root.dataset.analysisEmpty = String(!grid.childElementCount && !status.length);
  if (!grid.childElementCount) grid.append(reportNode("p", "Noch keine aktuellen Leistungswerte.", "muted"));
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
