function activitySportLabel(activity) {
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

function renderGarminFullResync(fullButton, fullStatus, fullResync, fullRunning) {
  if (fullButton) {
    fullButton.disabled = fullRunning || Boolean(state.data?.garmin_sync?.running || state.localSync.garmin);
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Lokale Daten neu laden";
  }
  if (!fullStatus) return;
  fullStatus.classList.toggle("error", Boolean(fullResync.last_error));
  let statusText = "Löscht nur lokale Garmin-Daten; Zugangsdaten und Cloud bleiben unverändert.";
  if (fullRunning && fullResync.status) statusText = fullResync.status;
  else if (fullResync.last_error) statusText = fullResync.last_error;
  else if (fullResync.last_resync_at) statusText = `Letzter vollständiger Resync: ${formatTime(fullResync.last_resync_at)}`;
  fullStatus.textContent = statusText;
}

function renderUnavailableGarmin(garmin, status, detail, button, fullButton) {
  const unavailable = !garmin?.available;
  if (!unavailable && garmin.configured) return false;
  status.textContent = unavailable ? "Garmin nicht verfügbar" : "Garmin nicht eingerichtet";
  detail.textContent = "";
  button.disabled = true;
  if (fullButton) fullButton.disabled = true;
  return true;
}

function renderGarmin(garmin) {
  const status = $("#garminStatus");
  const detail = $("#garminDetail");
  const button = $("#garminSyncButton");
  const fullButton = $("#garminFullResyncButton");
  const fullStatus = $("#garminFullResyncStatus");
  if (!status || !detail || !button) return;
  const fullResync = state.data?.provider_resync?.garmin || {};
  const fullRunning = Boolean(fullResync.running || state.localSync.garminFull);
  button.disabled = Boolean(state.data?.garmin_sync?.running || fullRunning);
  if (renderUnavailableGarmin(garmin, status, detail, button, fullButton)) return;
  if (garmin.source === "fixture") status.textContent = "Lokale Garmin-Testdaten aktiv";
  else if (garmin.last_error) status.textContent = "Mit Fehlern synchronisiert";
  else status.textContent = "Optionaler Direktabruf aktiv";
  detail.textContent = garminDetailText(garmin);
  renderGarminFullResync(fullButton, fullStatus, fullResync, fullRunning);
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

function metricSourceClass(source) {
  if (source === "Garmin Connect") return "metric-garmin";
  if (source === "Manuell") return "metric-manual";
  if (source && (source.startsWith("Intervals.icu") || source === "Aus Aktivitäten")) return "metric-intervals";
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
  source.className = metricSourceClass(metricData?.source);
  if (metricData?.source === "Garmin Connect") source.className = "metric-garmin";
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
  if (value == null) metric.textContent = "—";
  else if (formatter) metric.textContent = formatter(value);
  else metric.textContent = `${value}${unit ? " " + unit : ""}`;
  caption.textContent = label;
  for (const className of [metricSourceClass(metricData?.source), metricToneClass(label, value)]) {
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
  const profile = { ...state.data?.profile, [key]: String(value || "").trim() };
  button.disabled = true;
  try {
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

function performanceSection(root, title, items, detail = "") {
  const section = document.createElement("section");
  section.className = "performance-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const headingWrap = document.createElement("div");
  headingWrap.className = "performance-section-heading";
  headingWrap.append(heading);
  if (detail) {
    const stamp = document.createElement("span");
    stamp.className = "tab-sync-detail";
    stamp.textContent = detail;
    headingWrap.append(stamp);
  }
  section.append(headingWrap);
  const grid = document.createElement("div");
  grid.className = "metric-grid";
  items.forEach(([label, value, formatter, editable]) => displayMetric(grid, label, value, formatter, editable));
  section.append(grid);
  root.append(section);
}

function renderCurrentPerformance(metrics) {
  const root = document.getElementById("currentPerformance");
  root.replaceChildren(reportNode("h3", "Aktuelle Leistungswerte"));
  const groups = [
    ["Laufen", [
      ["run_threshold_pace_seconds_per_km", "Schwellenpace"],
      ["run_threshold_watts", "Schwellenleistung"],
      ["run_threshold_hr_bpm", "Schwellen-Herzfrequenz"],
      ["running_max_hr_bpm", "Maximale Herzfrequenz"],
      ["running_vo2max_ml_kg_min", "VO\u2082max \u00b7 Sch\u00e4tzung"],
    ]],
    ["Radfahren", [
      ["cycling_ftp_watts", "FTP"],
      ["cycling_eftp_watts", "eFTP \u00b7 Sch\u00e4tzung"],
      ["bike_threshold_hr_bpm", "Schwellen-Herzfrequenz"],
      ["cycling_max_hr_bpm", "Maximale Herzfrequenz"],
      ["cycling_vo2max_ml_kg_min", "VO\u2082max \u00b7 Sch\u00e4tzung"],
    ]],
  ];
  const grid = reportNode("div", null, "current-performance-groups");
  for (const [sport, items] of groups) {
    const table = reportNode("table", null, "current-performance-table");
    table.append(reportNode("caption", sport));
    const body = reportNode("tbody");
    for (const [key, label] of items) {
      const metric = metrics?.[key];
      const row = reportNode("tr"); row.dataset.metric = key;
      const heading = reportNode("th", label); heading.scope = "row";
      row.append(heading, reportNode("td", metric?.value == null ? "\u2014" : analysisValue(metric.value, metric.unit || "")));
      body.append(row);
    }
    table.append(body); grid.append(table);
  }
  root.append(grid);
  makeAnalysisSectionCollapsible(root, "current-performance");
}

function renderPerformance(performance, { refreshCharts = true } = {}) {
  if (refreshCharts) {
    void renderTrainingRecords();
    renderPersonalRecovery(performance?.personal_recovery);
    renderAnalysisHistory(performance?.history);
    void renderCyclingPowerProfile();
    renderTrainingFocus(performance?.training_focus);
  }
  const root = $("#performancePredictions");
  root.replaceChildren();
  const values = performance?.metrics || {};
  renderCurrentPerformance(values);
  const predictions = racePredictionRows(values);
  root.hidden = false;
  root.append(reportNode("h4", "Laufprognosen"));
  if (!predictions.length) {
    root.append(reportNode("p", racePredictionEmptyReason(values), "empty"));
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
      row.append(distance, reportNode("td", formatDuration(metric.value)));
      body.append(row);
    }
    table.append(body); root.append(table);
  }
  renderAnalysisSegments(state.route);
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
    : "Noch keine Prognosen – dafür fehlen aktuelle Leistungswerte aus Intervals.icu oder Garmin.";
}
