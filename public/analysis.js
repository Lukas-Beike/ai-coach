const ANALYSIS_SVG_NS = "http://www.w3.org/2000/svg";

function analysisSvg(tag, attributes = {}, content = "") {
  const node = document.createElementNS(ANALYSIS_SVG_NS, tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  node.textContent = content;
  return node;
}

function analysisValue(value, unit) {
  if (unit === "s/km") return formatPace(value);
  const suffix = unit ? ` ${unit}` : "";
  return `${Number(value).toLocaleString("de-DE", { maximumFractionDigits: 1 })}${suffix}`;
}

function analysisLegendText(item, latest, unit) {
  if (!latest) return `${item.label}: keine Werte`;
  const baseline = item.baselineDate ? ` · Basis ${dateLabel(item.baselineDate)}` : "";
  return `${item.label}: ${analysisPointValue(item, latest, unit)} · ${dateLabel(latest.date)}${baseline}`;
}

function analysisRelativeValue(value, baseline, unit) {
  if (value == null || !baseline) return null;
  const current = Number(value);
  const initial = Number(baseline.value);
  return (unit === "s/km" ? 1 - current / initial : current / initial - 1) * 100;
}

function analysisPointValue(item, point, unit) {
  if (point.actual == null) return analysisValue(point.value, unit);
  return `${analysisValue(point.actual, item.unit)} (${analysisValue(point.value, "%")})`;
}

function appendAnalysisCoverage(section, series, compactInfo) {
  const coverageSeries = series;
  if (!coverageSeries.length && !compactInfo) return;
  const coverage = document.createElement("details");
  coverage.className = "analysis-coverage";
  const summary = document.createElement("summary");
  summary.textContent = "Datenabdeckung";
  const note = document.createElement("p");
  note.className = "muted";
  note.textContent = "Fehlende Messungen bleiben unbekannt; sie sind keine Nullwerte oder bestätigten Ruhetage.";
  const rows = document.createElement("ul");
  coverageSeries.forEach((item) => {
    const row = document.createElement("li");
    const points = item.points.filter((point) => point?.value != null && Number.isFinite(Number(point.value)));
    const range = points.length ? " · " + dateLabel(points[0].date) + " bis " + dateLabel(points.at(-1).date) : "";
    const valueCoverage = item.coverage || points.length + "/" + item.points.length + " datierte Werte" + range;
    row.textContent = `${item.label}: ${valueCoverage}`;
    rows.append(row);
  });
  if (!coverageSeries.length) {
    const row = document.createElement("li");
    row.textContent = "Keine Messhistorie vorhanden.";
    rows.append(row);
  }
  coverage.append(summary, note, rows);
  section.append(coverage);
}

let analysisInfoId = 0;

function analysisChart(title, series, unit, start, end, note, compactInfo = false) {
  const section = document.createElement("section");
  section.className = "analysis-chart-card";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading);
  const valid = (point) => point?.value != null && Number.isFinite(Number(point.value));
  const values = series.flatMap((item) => item.points.filter(valid).map((point) => Number(point.value)));
  const description = document.createElement("p");
  description.className = "analysis-chart-note";
  description.textContent = note;
  if (!compactInfo) section.append(description);
  appendAnalysisCoverage(section, series, compactInfo);
  if (!values.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Noch keine datierten Werte im Zeitraum vorhanden.";
    section.append(empty);
    return section;
  }
  const legend = document.createElement("ul");
  legend.className = "analysis-chart-legend";
  series.forEach((item, index) => {
    const latest = item.points.findLast(valid);
    const entry = document.createElement("li");
    entry.dataset.series = String(index);
    entry.dataset.color = String(item.color ?? index);
    if (compactInfo) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "analysis-legend-info";
      button.textContent = `${item.legendLabel || item.label}: ${latest ? analysisPointValue(item, latest, unit) : "keine Werte"}`;
      const tooltip = document.createElement("div");
      tooltip.id = `analysis-info-${++analysisInfoId}`;
      tooltip.className = "analysis-info-tooltip";
      tooltip.setAttribute("popover", "auto");
      tooltip.setAttribute("role", "tooltip");
      const sourceLabel = item.source ? ` · Quelle: ${item.source}` : "";
      tooltip.textContent = `${analysisLegendText(item, latest, unit)}${sourceLabel}. ${note}`;
      button.setAttribute("popovertarget", tooltip.id);
      button.setAttribute("aria-describedby", tooltip.id);
      button.setAttribute("aria-expanded", "false");
      tooltip.addEventListener("toggle", (event) => {
        button.setAttribute("aria-expanded", String(event.newState === "open"));
        if (event.newState !== "open") return;
        const rect = button.getBoundingClientRect();
        tooltip.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - tooltip.offsetWidth - 12))}px`;
        tooltip.style.top = `${Math.max(12, Math.min(rect.bottom + 8, innerHeight - tooltip.offsetHeight - 12))}px`;
      });
      entry.append(button, tooltip);
    } else entry.textContent = analysisLegendText(item, latest, unit);
    legend.append(entry);
  });
  section.append(legend);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const padding = Math.max((high - low) * .12, 1);
  const min = low - padding;
  const max = high + padding;
  const chartWidth = globalThis.innerWidth < 600 ? 360 : 680;
  const chartRight = chartWidth - 30;
  const x = (date) => 66 + ((Date.parse(date) - Date.parse(start)) / Math.max(86400000, Date.parse(end) - Date.parse(start))) * (chartRight - 66);
  const y = (value) => 160 - (Number(value) - min) / (max - min) * 130;
  const svg = analysisSvg("svg", { viewBox: `0 0 ${chartWidth} 200`, role: "img", "aria-label": `${title}: datierter Verlauf. Einzelwerte stehen unter Werte ansehen.` });
  svg.append(analysisSvg("title", {}, `${title} · ${dateLabel(start)} bis ${dateLabel(end)}`));
  [min, (min + max) / 2, max].forEach((value) => {
    svg.append(analysisSvg("line", { x1: 66, x2: chartRight, y1: y(value), y2: y(value), class: "analysis-grid-line" }));
    svg.append(analysisSvg("text", { x: 58, y: y(value) + 4, "text-anchor": "end" }, unit === "s/km" ? formatPace(value).split(" ")[0] : value.toLocaleString("de-DE", { maximumFractionDigits: 0 })));
  });
  series.forEach((item, index) => {
    let path = "";
    let continuing = false;
    item.points.forEach((point, pointIndex) => {
      if (!valid(point)) { continuing = false; return; }
      path += `${continuing ? "L" : "M"}${x(point.date).toFixed(2)},${y(point.value).toFixed(2)} `;
      continuing = true;
      if (!valid(item.points[pointIndex - 1]) || !valid(item.points[pointIndex + 1])) {
        const dot = analysisSvg("circle", { cx: x(point.date), cy: y(point.value), r: 2.5, "data-series": index, "data-color": item.color ?? index });
        dot.append(analysisSvg("title", {}, `${item.label} · ${dateLabel(point.date)}: ${analysisPointValue(item, point, unit)}`));
        svg.append(dot);
      }
    });
    svg.append(analysisSvg("path", { d: path, fill: "none", "data-series": index, "data-color": item.color ?? index, ...(item.line ? { "data-line": item.line } : {}) }));
  });
  if (min < 0 && max > 0) svg.append(analysisSvg("line", { x1: 66, x2: chartRight, y1: y(0), y2: y(0), class: "analysis-zero-line" }));
  svg.append(analysisSvg("text", { x: 66, y: 188 }, dateLabel(start)));
  svg.append(analysisSvg("text", { x: chartRight, y: 188, "text-anchor": "end" }, dateLabel(end)));
  section.append(svg);
  if (compactInfo || series.some((item) => item.unit)) section.append(legend);
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Werte ansehen";
  const scroll = document.createElement("div");
  scroll.className = "analysis-chart-table";
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", `${title}: Einzelwerte`);
  const table = document.createElement("table");
  const caption = document.createElement("caption");
  caption.textContent = `${title} · ${unit || "Belastungspunkte"} · nur vorhandene Werte`;
  table.append(caption);
  const header = document.createElement("tr");
  ["Tag", ...series.map((item) => item.label)].forEach((label) => {
    const cell = document.createElement("th"); cell.scope = "col"; cell.textContent = label; header.append(cell);
  });
  const thead = document.createElement("thead"); thead.append(header); table.append(thead);
  const body = document.createElement("tbody");
  series[0].points.forEach((point, index) => {
    if (!series.some((item) => valid(item.points[index]))) return;
    const row = document.createElement("tr");
    const day = document.createElement("th"); day.scope = "row"; day.textContent = dateLabel(point.date); row.append(day);
    series.forEach((item) => {
      const cell = document.createElement("td");
      cell.textContent = valid(item.points[index]) ? analysisPointValue(item, item.points[index], unit) : "–";
      row.append(cell);
    });
    body.append(row);
  });
  table.append(body); scroll.append(table); details.append(summary, scroll); section.append(details);
  return section;
}

globalThis.matchMedia("(max-width: 599px)").addEventListener("change", () => {
  if (state.data) renderAnalysisHistory(state.data.performance?.history);
});

function renderAnalysisHistory(history) {
  void renderTrainingReport();
  const root = document.querySelector("#analysisHistoryCharts");
  const expandedDetails = Array.from(root.querySelectorAll(".analysis-chart-card details"), (details) => details.open);
  root.replaceChildren();
  if (!history?.start || !history?.end) return;
  const end = history.end;
  const start = addDateKey(end, -55);
  const withinPeriod = (point) => point.date >= start && point.date <= end;
  const load = history.load || { points: [] };
  const loadSeries = [["ctl", "Fitness"], ["atl", "Ermüdung"], ["tsb", "Form"]].map(([key, label]) => ({
    label, source: "Intervals.icu", points: load.points.filter(withinPeriod).map((point) => ({ date: point.date, value: point[key] })),
  }));
  root.append(analysisChart("Belastung und Form", loadSeries, "", start, end,
    "Fitness: langfristige Belastung (üblich 42 Tage), Ermüdung: kurzfristige Belastung (7 Tage). Die Providerkonfiguration gilt. Form = Fitness − Ermüdung am selben Tag. Historische Werte bis gestern; Fitness ist kein Leistungstest.", true));
  const performanceSeries = [
    ["cycling_ftp_watts", "Rad · FTP", "W"],
    ["cycling_eftp_watts", "Rad · eFTP", "W"],
    ["run_threshold_pace_seconds_per_km", "Lauf · Schwellenpace", "s/km"],
    ["cycling_vo2max_ml_kg_min", "Rad · VO₂max", "ml/kg/min"],
    ["running_vo2max_ml_kg_min", "Lauf · VO₂max", "ml/kg/min"],
  ].flatMap(([key, label, unit], color) => (history.metrics?.[key] || []).filter((item) => item.source === (key === "cycling_eftp_watts" ? "Intervals.icu" : "Garmin Connect")).map((item) => {
    const points = item.points.filter(withinPeriod);
    const baseline = points.find((point) => point.value != null && Number(point.value) > 0);
    return {
      label: `${label} · ${item.source}`, legendLabel: label, unit, color,
      line: item.source === "Garmin Connect" ? "dashed" : "solid",
      baselineDate: baseline?.date,
      points: points.map((point) => ({
        date: point.date, actual: point.value,
        value: analysisRelativeValue(point.value, baseline, unit),
      })),
    };
  }));
  root.append(analysisChart("Leistungsentwicklung", performanceSeries, "%", start, end,
    "Relative Veränderung ab dem ersten vorhandenen Wert je Reihe (0 %). Bei Schwellenpace bedeutet positives Wachstum eine kürzere Zeit pro Kilometer. Leistungswerte: Garmin; nur eFTP: Intervals.icu. VO₂max und eFTP sind Schätzungen. Datenlücken bleiben sichtbar.", true));
  root.querySelectorAll(".analysis-chart-card details").forEach((details, index) => {
    details.open = expandedDetails[index] ?? false;
  });
}

let trainingReportGeneration = 0;
let seasonGeneration = 0;
let trainingRecordsGeneration = 0;

async function renderTrainingRecords() {
  const generation = ++trainingRecordsGeneration;
  const session = state.sessionGeneration;
  try {
    const result = await api("/api/analysis/training-records");
    if (generation !== trainingRecordsGeneration || session !== state.sessionGeneration) return;
    const gear = document.getElementById("equipmentItems"); gear.replaceChildren(reportNode("h3", "Ausrüstung und Wartung"));
    const equipment = result.equipment || {};
    const items = equipment.garmin_items || [];
    if (!items.length) gear.append(reportNode("p", "Noch keine Ausr\u00fcstung aus Garmin synchronisiert.", "muted"));
    for (const item of items) {
      gear.append(garminEquipmentCard(item));
    }
    appendLocalEquipment(equipment.items || [], gear);
    if (equipment.garmin_synced_at) gear.append(reportNode("p", `Garmin \u00b7 Stand ${new Date(equipment.garmin_synced_at).toLocaleString("de-DE")}${equipment.garmin_freshness === "stale" ? " \u00b7 letzter erfolgreicher Abruf" : ""}`, "muted"));
  } catch (error) {
    if (generation === trainingRecordsGeneration && session === state.sessionGeneration) {
      for (const id of ["equipmentItems"]) document.getElementById(id).textContent=error.message;
    }
  }
}

async function renderSeasonPreparation() {
  const root = document.getElementById("seasonPreparation");
  const generation = ++seasonGeneration;
  root.replaceChildren(reportNode("h3", "Saison und Wettkampfvorbereitung"));
  try {
    const season = await api("/api/analysis/season");
    if (generation !== seasonGeneration) return;
    if (!season.events?.length) root.append(reportNode("p", "Noch keine Wettkämpfe im Athletenprofil bestätigt."));
    for (const event of season.events || []) {
      root.append(seasonEventCard(event, generation));
    }
  } catch (error) { if (generation === seasonGeneration) root.append(reportNode("p", error.message)); }
}

function renderAnalysisSegments(route = state.route) {
  const segment = { "analysis/recovery": "recovery", "analysis/review": "review" }[route] || "performance";
  for (const id of ["analysisHistoryCharts", "analysisPerformanceSegment"]) document.getElementById(id).hidden = segment !== "performance";
  document.getElementById("trainingReport").hidden = segment !== "review";
  document.getElementById("personalRecovery").hidden = segment !== "recovery";
  if (segment === "review") void renderTrainingReport();
  document.querySelectorAll("[data-analysis-segment]").forEach((link) => {
    const active = link.dataset.analysisSegment === segment;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
}

function selectedRecoveryBaselines(report) {
  return ["sleep", "hrv", "resting_hr"].flatMap((metric) => {
    const candidates = (report?.baselines || []).filter((item) => item.metric === metric);
    candidates.sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at))
      || Number(b.source === "Intervals.icu") - Number(a.source === "Intervals.icu")
      || b.history.length - a.history.length);
    return candidates.slice(0, 1);
  });
}

function renderRecoveryCharts(report, root) {
  const metrics = [["sleep", "Schlafdauer", "h"], ["hrv", "HRV", "ms"], ["resting_hr", "Ruhepuls", "bpm"]];
  const baselines = selectedRecoveryBaselines(report);
  const today = report?.as_of || timezoneDateKey(state.data?.profile?.timezone, new Date());
  const weekStart = addDateKey(today, -((new Date(`${today}T12:00:00Z`).getUTCDay() + 6) % 7));
  const currentDates = Array.from({ length: 7 }, (_, index) => addDateKey(weekStart, index));
  const weekDates = Array.from({ length: 8 }, (_, index) => addDateKey(weekStart, (index - 7) * 7));
  const makeSeries = (dates, weekly) => recoveryChartSeries(metrics, baselines, dates, weekly, today);
  const note = "Gemeinsame Skala: relative Veränderung zum ersten vorhandenen Wert jeder Reihe (0 %). Originalwerte stehen in Legende und Tabelle. Ein höherer Ruhepuls bedeutet keine bessere Erholung. Pro Messwert wird eine Quelle verwendet, ohne Methoden zu mischen.";
  const currentChart = analysisChart("Erholung · Aktuelle Woche", makeSeries(currentDates, false), "%", currentDates[0], currentDates.at(-1), `${note} Fehlende Tagesmessungen bleiben als Lücken sichtbar.`, true);
  const weeklyChart = analysisChart("Erholung · Letzte 8 Wochen", makeSeries(weekDates, true), "%", weekDates[0], weekDates.at(-1), `${note} Jeder Datenpunkt ist der Durchschnitt der vorhandenen Tagesmessungen dieser Kalenderwoche. Die laufende Woche ist noch unvollständig; fehlende Messungen zählen nicht als null.`, true);
  root.replaceChildren(currentChart, weeklyChart);

}

function renderPersonalRecovery(report) {
  const root = document.getElementById("personalRecovery");
  renderRecoveryCharts(report, root);
  const impact = reportNode("details"); impact.append(reportNode("summary", "Was beeinflusst deine Erholung?"));
  const impactBody = reportNode("div"); impact.append(impactBody); root.append(impact);
  impact.addEventListener("toggle", async () => {
    if (!impact.open) return;
    try {
      const result = await api("/api/analysis/impact");
      if (!root.contains(impact)) return;
      impactBody.replaceChildren(reportNode("p", "Vergleich ausdrücklich beantworteter Tages-Tags mit der nachfolgenden Nacht. Mindestens zehn gemessene Tage je Gruppe; unbeantwortete Tage bleiben ausgeschlossen. Zusammenhänge beweisen keine Ursache.", "muted"));
      const selected = selectedRecoveryBaselines(report);
      for (const row of (result.reports || []).filter((row) => selected.some((item) => item.metric === row.metric && item.source === row.source && item.measurement === row.measurement))) {
        const title = {travel:"Reise",late_meal:"Spätes Essen",high_stress:"Hoher Stress"}[row.tag];
        const withTag = row.groups.with, without = row.groups.without;
        const details = reportNode("details"); details.append(reportNode("summary", `${title} · ${row.source} · ${row.metric}: ${withTag.days}/${without.days} Tage`));
        details.append(reportNode("p", row.status === "insufficient_data" ? "Zu wenig ausdrücklich beantwortete, gemessene Tage für einen Vergleich."
          : `Median mit: ${withTag.median.toFixed(1)}, ohne: ${without.median.toFixed(1)} ${row.unit} · Quartile ${withTag.quartiles.map(x=>x.toFixed(1)).join("–")} / ${without.quartiles.map(x=>x.toFixed(1)).join("–")}`));
        details.append(reportNode("p", `Bekannte Belastung: ${withTag.load_known_days}/${withTag.days} und ${without.load_known_days}/${without.days} Tage · gleichzeitige Tags: ${withTag.co_tag_days}/${without.co_tag_days}. Selektive Erfassung und weitere Einflüsse begrenzen die Aussage.`, "muted"));
        impactBody.append(details);
      }
      if (!result.reports?.length) impactBody.append(reportNode("p", "Noch keine passende Messhistorie. Bestätige Tags und auch Nein-Antworten im Tages-Check-in."));
    } catch (error) { if (root.contains(impact)) impactBody.textContent=error.message; }
  });
  renderAnalysisSegments();
}

function reportNode(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function reportMetric(metric, unit) {
  if (metric?.value == null) return "nicht gemessen";
  const suffix = unit ? " " + unit : "";
  const value = unit === "Dauer" ? formatDuration(metric.value) : `${Math.round(metric.value)}${suffix}`;
  return `${value} (${metric.measured_sessions}/${metric.total_sessions} Einheiten)`;
}

function weeklyLoadTooltip(section, marker, title, lines) {
  const tooltip = reportNode("div", null, "analysis-info-tooltip");
  tooltip.id = `weekly-info-${++analysisInfoId}`;
  tooltip.setAttribute("popover", "auto");
  tooltip.setAttribute("role", "tooltip");
  tooltip.append(reportNode("strong", title));
  for (const line of lines) tooltip.append(reportNode("p", line));
  marker.setAttribute("role", "button");
  marker.setAttribute("tabindex", "0");
  marker.setAttribute("aria-label", title);
  marker.setAttribute("aria-describedby", tooltip.id);
  marker.setAttribute("aria-expanded", "false");
  const open = () => tooltip.togglePopover();
  marker.addEventListener("click", open);
  marker.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault(); open();
  });
  tooltip.addEventListener("toggle", (event) => {
    marker.setAttribute("aria-expanded", String(event.newState === "open"));
    if (event.newState !== "open") return;
    const rect = marker.getBoundingClientRect();
    tooltip.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - tooltip.offsetWidth - 12))}px`;
    tooltip.style.top = `${Math.max(12, Math.min(rect.bottom + 8, innerHeight - tooltip.offsetHeight - 12))}px`;
  });
  section.append(tooltip);
}

function weeklyPointGroup(point, index, chart) {
  const {weekly, x, y} = chart;
  const value = point.metric.value;
  const partial = point.metric.measured_sessions < point.metric.total_sessions;
    const group = analysisSvg("g", { [weekly ? "data-week" : "data-day"]: point.date, opacity: point.future ? .4 : 1 });
    const shortDate = point.date.slice(5).split("-").reverse().join(".");
    group.append(analysisSvg("text", { x: x(index), y: 177, "text-anchor": "middle" }, weekly ? shortDate : new Date(`${point.date}T12:00:00Z`).toLocaleDateString("de-DE", { weekday: "short", timeZone: "UTC" })));
    if (!weekly) group.append(analysisSvg("text", { x: x(index), y: 193, "text-anchor": "middle" }, shortDate));
    if (!point.future) {
      const markerY = value == null ? 152 : y(value);
      group.append(analysisSvg("circle", { cx: x(index), cy: markerY, r: 12, fill: "transparent" }));
      group.append(analysisSvg("circle", { cx: x(index), cy: markerY, r: 4, class: "weekly-load-point", ...(point.partial_period || partial || value == null ? { "stroke-dasharray": "2 2", fill: "var(--surface)" } : {}) }));
      let valueText = String.fromCodePoint(8211);
      if (value != null) valueText = String(Math.round(value)) + (partial ? "?" : "");
      group.append(analysisSvg("text", { x: x(index), y: markerY - 12, "text-anchor": "middle" }, valueText));
      appendWeeklyPointTooltip(point, group, chart);
    }
    return group;

}

function appendWeeklyPointTooltip(point, group, chart) {
  const {section, weekly} = chart;
  const partial = point.metric.measured_sessions < point.metric.total_sessions;
      weeklyLoadTooltip(section, group, weekly ? `${dateLabel(point.start)} – ${dateLabel(point.end)}` : dateLabel(point.date), [
        `Wochenbelastung: ${reportMetric(point.metric, "")}`,
        ...(point.partial_period ? ["Diese Woche läuft noch."] : []),
        ...(partial ? ["Die Summe enthält nur bekannte Belastungswerte."] : []),
        ...(!point.metric.total_sessions ? ["Bisher keine aufgezeichneten Einheiten."] : []),
        ...(point.activities || []).map((activity) => activitySportLabel({ type: activity.sport })),
        "Quelle: Intervals.icu · Aufsummierte Trainingsbelastung aufgezeichneter Einheiten. Ohne neue Einheiten bleibt die Summe konstant; keine Ermüdungskurve.",
      ]);
}

function appendWeeklyActivityMarkers(point, index, chart) {
  const {svg, x, sports, colors} = chart;
  (point.activities || []).forEach((activity, activityIndex) => {
      const marker = analysisSvg("g", { "data-activity": activity.activity_id });
      const markerY = 216 + activityIndex * 26;
      const color = colors[sports.indexOf(activity.sport) % colors.length];
      const sportName = activitySportLabel({ type: activity.sport });
      const shortName = { Radfahren: "Rad", Laufen: "Lauf", Schwimmen: "Swim" }[sportName] || sportName;
      marker.append(analysisSvg("title", {}, sportName));
      const label = analysisSvg("text", { x: x(index), y: markerY + 4, "text-anchor": "middle", ...(shortName.length > 6 ? { textLength: 42, lengthAdjust: "spacingAndGlyphs" } : {}) }, shortName);
      label.style.fill = color;
      marker.append(label);
      svg.append(marker);
    });
}

function weeklyTrainingChart(report, weekly = false) {
  const section = reportNode("section", null, "weekly-chart");
  const title = weekly ? "Trainingsbelastung · letzte 8 Wochen" : "Trainingsbelastung · aktuelle Woche";
  section.append(reportNode("h4", title));
  const points = weekly ? (report.weekly_load || []).map((week) => ({ ...week, date: week.start, metric: week.training_load }))
    : (report.daily || []).map((day) => ({ ...day, metric: day.cumulative_training_load }));
  const sports = Object.keys(report.sports || {});
  const colors = ["#10b981", "#38bdf8", "#a78bfa", "#f59e0b", "#fb7185", "#94a3b8"];
  const max = Math.max(10, ...points.map((point) => point.metric.value || 0)) * 1.2;
  const rows = Math.max(1, ...points.map((point) => point.activities?.length || 0));
  const height = weekly ? 220 : 216 + rows * 26;
  const svg = analysisSvg("svg", { viewBox: `0 0 360 ${height}`, role: "img", "aria-label": title });
  svg.append(analysisSvg("title", {}, title));
  svg.append(analysisSvg("desc", {}, points.map((point) => `${dateLabel(point.date)}: ${point.future ? "steht noch bevor" : reportMetric(point.metric, "")}`).join(". ")));
  const x = (index) => 46 + index / Math.max(1, points.length - 1) * 294;
  const y = (value) => 152 - value / max * 118;
  [0, max / 2, max].forEach((value) => {
    svg.append(analysisSvg("line", { x1: 36, x2: 350, y1: y(value), y2: y(value), class: "analysis-grid-line" }));
    svg.append(analysisSvg("text", { x: 30, y: y(value) + 4, "text-anchor": "end" }, Math.round(value)));
  });
  let previous = null;
  points.forEach((point, index) => {
    const value = point.metric.value;
    const partial = point.metric.measured_sessions < point.metric.total_sessions;
    if (previous && value != null && !point.future) {
      svg.append(analysisSvg("path", { d: `M${x(index - 1)},${y(previous.metric.value)} L${x(index)},${y(value)}`, class: "weekly-load-line", ...(partial || previous.metric.measured_sessions < previous.metric.total_sessions ? { "stroke-dasharray": "4 4" } : {}) }));
    }
    previous = value == null || point.future ? null : point;
    svg.append(weeklyPointGroup(point, index, {weekly, x, y, section}));
    if (!weekly) appendWeeklyActivityMarkers(point, index, {svg, x, sports, colors});
  });
  section.append(svg);
  if (!weekly) {
    const legend = reportNode("ul", null, "weekly-sport-legend");
    sports.forEach((sport, index) => {
      const item = reportNode("li", activitySportLabel({ type: sport }));
      item.style.setProperty("--sport-color", colors[index % colors.length]); legend.append(item);
    });
    section.append(legend);
  }
  return section;
}

function renderTrainingReportBody(report, root) {
  root.replaceChildren();
  root.append(reportNode("h3", `Aktuelle Woche: ${dateLabel(report.start)} – ${dateLabel(report.end)}`));
  const facts = reportNode("div", null, "weekly-metrics");
  for (const [value, label] of [
    [String(report.totals.sessions), "Einheiten"],
    [report.totals.moving_time.value == null ? "–" : formatDuration(report.totals.moving_time.value), "Trainingszeit"],
    [report.totals.icu_training_load.value == null ? "–" : String(Math.round(report.totals.icu_training_load.value)), "Belastung"],
  ]) {
    const card = reportNode("div");
    card.append(reportNode("strong", value), reportNode("span", label));
    facts.append(card);
  }
  root.append(facts, weeklyTrainingChart(report), weeklyTrainingChart(report, true));


}

async function renderTrainingReport() {
  const root = document.querySelector("#trainingReport");
  if (!root) return;
  const generation = ++trainingReportGeneration;
  const session = state.sessionGeneration;
  const current = () => generation === trainingReportGeneration && session === state.sessionGeneration;
  const body = reportNode("div", "Bericht wird geladen \u2026");
  body.setAttribute("aria-live", "polite");
  root.replaceChildren(body);
  try {
    const report = await api("/api/analysis/report");
    if (current()) renderTrainingReportBody(report, body);
  } catch (error) { if (current()) body.textContent = error.message; }
}

function renderTrainingFocus(report) {
  const root = document.getElementById("sessionPerformance");
  root.replaceChildren(reportNode("h3", "Trainingsfokus"));
  if (!report) { root.append(reportNode("p", "Noch keine Trainingsdaten vorhanden.", "muted")); return; }

  const categories = [["low_aerobic", "Leicht aerob"], ["high_aerobic", "Hoch aerob"], ["anaerobic", "Anaerob"]];
  const info = reportNode("button", "i", "analysis-legend-info");
  info.type = "button"; info.setAttribute("aria-label", "Trainingsfokus: Informationen");
  const explanation = reportNode("div", `Letzte 8 Wochen: ${dateLabel(report.start)} bis ${dateLabel(report.end)}. Garmin: aufgezeichnete Belastung nach der Hauptwirkung der Einheit (Training Effect). Keine aus Zonen abgeleitete Einteilung und nicht Garmins separat berechnete Load-Focus-Metrik. ${report.unclassified_sessions || 0} Einheiten ohne bekannte Wirkung oder Belastung bleiben ausgeschlossen.`, "analysis-info-tooltip");
  explanation.id = `focus-info-${++analysisInfoId}`; explanation.setAttribute("popover", "auto"); explanation.setAttribute("role", "tooltip");
  info.setAttribute("popovertarget", explanation.id); root.firstChild.append(info); root.append(explanation);
  const coverage = report.coverage || {};
  const coverageRange = coverage.observed_start && coverage.observed_end
    ? ` · erfasste Daten ${dateLabel(coverage.observed_start)} bis ${dateLabel(coverage.observed_end)}`
    : "";
  root.append(reportNode("p", `${coverage.known_sessions ?? 0} erfasste Garmin-Einheiten im Zeitraum${coverageRange}.`, "muted training-focus-coverage"));
  appendTrainingFocusShare(report, categories, root);
  const details = reportNode("details", null, "training-focus-details");
  const disclosure = reportNode("summary", "Zonen im Detail");
  const chevron = analysisSvg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
  chevron.append(analysisSvg("path", { d: "m6 9 6 6 6-6" }));
  disclosure.append(chevron); details.append(disclosure); root.append(details);
  appendTrainingFocusZones(report, details);
}

function appendLocalEquipment(items, root) {
  if (!items.length) return;
  const details = reportNode("details", null, "training-focus-details");
  details.append(reportNode("summary", "Lokale Ausr\u00fcstung und Wartung"));
  for (const item of items) details.append(localEquipmentCard(item));
  root.append(details);
}

function localEquipmentCard(item) {
  const card = reportNode("section", null, "garmin-equipment-card");
  const usage = item.usage || {};
  card.append(reportNode("h4", item.name));
  card.append(reportNode("p", `${item.kind} \u00b7 Revision ${item.revision}`));
  card.append(reportNode("p", `${analysisValue(usage.distance_km, "km")} \u00b7 ${analysisValue(usage.hours, "h")} \u00b7 ${usage.assigned_sessions || 0} zugeordnete Einheiten`));
  card.append(reportNode("p", `Seit letzter Wartung: ${analysisValue(usage.maintenance_distance_km, "km")} \u00b7 ${analysisValue(usage.maintenance_hours, "h")}`));
  const status = new Map([[true, "Wartung f\u00e4llig"], [false, "Wartung nicht f\u00e4llig"]]);
  card.append(reportNode("p", status.get(usage.maintenance_due) || "Wartungsstand unklar"));
  if (usage.maintenance_coverage === "partial") card.append(reportNode("p", "Nutzung unvollst\u00e4ndig bekannt.", "muted"));
  const history = reportNode("ul");
  for (const event of item.maintenance || []) history.append(reportNode("li", `${dateLabel(event.date)} \u00b7 ${event.notes || "Wartung erfasst"}`));
  if (history.childElementCount) card.append(history);
  else card.append(reportNode("p", "Keine Wartung erfasst.", "muted"));
  return card;
}

function garminEquipmentCard(item) {
  const card = reportNode("section", null, "garmin-equipment-card");
  card.append(reportNode("h4", item.name));
  card.append(reportNode("p", [item.kind, item.status].filter(Boolean).join(" \u00b7 ")));
  card.append(reportNode("strong", item.distance_km == null ? "Nutzung unbekannt" : `${analysisValue(item.distance_km, "km")}`));
  if (item.sessions != null) card.append(reportNode("p", `${item.sessions} Einheiten`));
  if (item.usage_percent != null) {
    const progress = reportNode("progress"); progress.max = 100; progress.value = Math.min(100, item.usage_percent);
    progress.setAttribute("aria-label", `${item.name}: ${item.usage_percent}% des Garmin-Nutzungsziels`);
    card.append(progress, reportNode("p", `${analysisValue(item.distance_km, "km")} von ${analysisValue(item.goal_km, "km")} \u00b7 ${item.usage_percent}%`));
  }
  return card;
}

function seasonEventCard(event, generation) {
  const section = reportNode("section", null, "analysis-chart-card");
  section.append(reportNode("h4", `${event.name} · ${dateLabel(event.event_date)} · Priorität ${event.priority}`));
  const phase = {base:"Basis",build:"Aufbau",peak:"Spezifische Vorbereitung",taper:"Taper",completed:"Vergangen"}[event.phase];
  section.append(reportNode("p", `${event.days_until} Tage · kalendarische Phase: ${phase} · ${event.preparation.sessions_84_days} passende Einheiten in 84 Tagen`));
  const weekly = reportNode("details"); weekly.append(reportNode("summary", `${event.preparation.weeks_with_recorded_training}/12 Wochen mit erfasstem sportartspezifischem Training`));
  for (const week of event.preparation.weeks || []) weekly.append(reportNode("p", seasonWeekSummary(week)));
  weekly.append(reportNode("p", "Wochen ohne Aufzeichnung beweisen keine Trainingspause; Umfang enthält nur lokal bekannte Einheiten.", "muted")); section.append(weekly);
  for (const item of event.preparation.long_sessions) {
    const button = reportNode("button", `${dateLabel(item.date)} · ${item.name} · ${item.duration_seconds == null ? "Dauer unbekannt" : formatDuration(item.duration_seconds)}`, "secondary-button");
    button.type = "button";
    button.addEventListener("click", () => globalThis.ActivityDetails.open({ id:item.activity_id, name:item.name }, { api, showDialog:showAccessibleDialog }));
    section.append(button);
    if (item.aerobic?.status === "ok") section.append(reportNode("p", `Gleichmäßige Belastung: lokale Herzfrequenzdrift ${item.aerobic.drift_percent}% · Effizienz ${item.aerobic.efficiency} ${item.aerobic.unit}`, "muted"));
  }
  section.append(reportNode("p", "Absolviertes Training ist ein Beleg, keine Wettkampffreigabe oder Zeitprognose. Gelände, spezifische Intensität und erprobte Verpflegung bleiben ohne passende Nachweise offen.", "muted"));
  if (event.days_until > 0 && event.days_until <= 180) {
    appendSeasonScenario(event, section, generation);
  }
  return section;
}

function appendSeasonScenario(event, section, generation) {
  const form = reportNode("form", null, "report-controls");
  const scaleLabel = reportNode("label", "Alternative: Belastungsfaktor"); const scale = reportNode("input"); scale.type="number"; scale.min="0.5"; scale.max="1.5"; scale.step="0.05"; scale.value="0.8"; scale.required=true; scaleLabel.append(scale);
  const taperLabel = reportNode("label", "Zusätzliche Entlastung (Tage)"); const taper = reportNode("input"); taper.type="number"; taper.min="0"; taper.max="21"; taper.value="7"; taper.required=true; taperLabel.append(taper);
  const calculate = reportNode("button", "Szenarien vergleichen", "secondary-button"); calculate.type="submit";
  const output = reportNode("div"); output.setAttribute("aria-live", "polite");
  form.append(scaleLabel, taperLabel, calculate); section.append(form, output);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); calculate.disabled=true;
    try {
      const values = {end:event.event_date,load_scale:Number(scale.value),taper_days:Number(taper.value)};
      const result = await api("/api/analysis/scenarios", {method:"POST",body:JSON.stringify(values)});
      if (generation !== seasonGeneration) return;
      output.replaceChildren(reportNode("p", "Lokales Standardmodell: CTL 42 Tage, ATL 7 Tage. Nicht geplante Tage werden mit 0 Belastung modelliert; die Alternative halbiert die Belastung zusätzlich in den gewählten letzten Tagen. CTL und Form sagen keine Wettkampfzeit voraus.", "muted"));
      if (result.status !== "ok") { output.append(reportNode("p", result.reason)); return; }
      output.append(analysisChart("Modellierte Form", result.curves.map((curve) => ({label:curve.name === "current" ? "Aktueller Plan" : "Alternative", points:curve.points.map((point) => ({date:point.date,value:point.tsb}))})), "TSB", result.curves[0].points[0].date, event.event_date, `Ausgang: CTL ${result.basis.ctl}, ATL ${result.basis.atl} vom ${result.basis.as_of}. Szenario ${result.input_sha256.slice(0,12)}; neue Aktivitäten oder Planänderungen erfordern eine Neuberechnung.`));
    } catch (error) { if (generation === seasonGeneration) output.textContent=error.message; }
    finally { calculate.disabled=false; }
  });
}

function seasonWeekSummary(week) {
  const duration = week.duration_seconds == null ? "Dauer unbekannt" : formatDuration(week.duration_seconds);
  const distance = week.distance_meters == null ? "Distanz unbekannt" : `${(week.distance_meters / 1000).toFixed(1)} km`;
  return `${dateLabel(week.start)} \u2013 ${dateLabel(week.end)}: ${week.sessions} erfasste Einheiten \u00b7 ${duration} (${week.duration_known_sessions}/${week.sessions} gemessen) \u00b7 ${distance} (${week.distance_known_sessions}/${week.sessions} gemessen)`;
}

function recoveryChartSeries(metrics, baselines, dates, weekly, today) {
  const series = [];
  for (const [color, metric] of metrics.entries()) {
    for (const item of baselines.filter((candidate) => candidate.metric === metric[0])) {
      series.push(recoverySeries(metric, item, dates, weekly, color, today));
    }
  }
  return series;
}

function recoverySeries([metric, title, unit], item, dates, weekly, color, today) {
  const values = new Map(item.history.map((point) => [point.date, point.value]));
  const points = dates.map((date) => recoveryPoint(date, values, weekly));
  const baseline = points.find((point) => point.actual != null && Number(point.actual) > 0);
  const method = metric === "hrv" ? " · " + item.measurement : "";
  const chartEnd = dates.at(-1);
  const coverageEnd = weekly || today < chartEnd ? today : chartEnd;
  const readings = item.history.filter((point) => point.date >= dates[0] && point.date <= coverageEnd);
  const expectedDays = Math.max(0, Math.round((Date.parse(coverageEnd) - Date.parse(dates[0])) / 86400000) + 1);
  const coverageLabel = `${readings.length}/${expectedDays} Tage mit Messung · 42-Tage-Normalbereich: ${item.nights} frühere Messnächte`;
  const coverageRange = readings.length ? ` · ${dateLabel(readings[0].date)} bis ${dateLabel(readings.at(-1).date)}` : "";
  return { label: `${title} · ${item.source}${method}`, legendLabel: title, unit, color, baselineDate: baseline?.date,
    coverage: coverageLabel + coverageRange,
    points: points.map((point) => ({ ...point, value: point.actual == null || !baseline ? null : (point.actual / baseline.actual - 1) * 100 })) };
}

function recoveryPoint(date, values, weekly) {
  if (!weekly) return { date, actual: values.get(date) ?? null };
  const readings = Array.from({ length: 7 }, (_, offset) => values.get(addDateKey(date, offset))).filter((value) => value != null && Number.isFinite(Number(value)));
  return { date, actual: readings.length ? readings.reduce((sum, value) => sum + Number(value), 0) / readings.length : null };
}

function trainingFocusDistribution(title, readings, unit, info) {
  const section = reportNode("section", null, "training-focus-distribution");
  const heading = reportNode("h4", title);
  const help = reportNode("button", "i", "analysis-legend-info");
  help.type = "button"; help.setAttribute("aria-label", `${title}: Informationen`);
  const tooltip = reportNode("div", info, "analysis-info-tooltip");
  tooltip.id = `focus-info-${++analysisInfoId}`; tooltip.setAttribute("popover", "auto"); tooltip.setAttribute("role", "tooltip");
  help.setAttribute("popovertarget", tooltip.id); heading.append(help); section.append(heading, tooltip);
  const total = readings.reduce((sum, item) => sum + item.value, 0);
  for (const item of readings) {
    const row = reportNode("div", null, "training-focus-row");
    row.dataset.zone = item.label;
    const bar = reportNode("progress"); bar.max = Math.max(total, 1); bar.value = item.value;
    bar.setAttribute("aria-label", `${item.label}: ${Math.round(total ? item.value / total * 100 : 0)} Prozent`);
    row.append(reportNode("span", item.label), bar, reportNode("span", `${Math.round(total ? item.value / total * 100 : 0)} % · ${unit === "seconds" ? formatDuration(item.value) : formatWhole(item.value)}`));
    section.append(row);
  }
  return section;
}

function appendTrainingFocusShare(report, categories, root) {
  if (report.classified_sessions) {
    const total = categories.reduce((sum, [key]) => sum + report.categories[key].load, 0);
    const bar = reportNode("div", null, "training-focus-share");
    bar.setAttribute("role", "img"); bar.setAttribute("aria-label", "Anteile leicht aerob, hoch aerob und anaerob an der bekannten Belastung");
    const legend = reportNode("ul", null, "training-focus-legend");
    for (const [index, [key, label]] of categories.entries()) {
      const percent = total ? report.categories[key].load / total * 100 : 0;
      const part = reportNode("span"); part.dataset.color = String(index); part.style.width = `${percent}%`; bar.append(part);
      const item = reportNode("li"); item.dataset.color = String(index);
      item.append(reportNode("strong", `${Math.round(percent)} %`), reportNode("span", label)); legend.append(item);
    }
    root.append(bar, legend);
  } else root.append(reportNode("p", "Noch keine Garmin-Einheiten mit auswertbarer Trainingswirkung vorhanden.", "muted"));
}

function appendTrainingFocusZones(report, details) {
  const zones = report.zones || [];
  for (const sensor of ["power", "heart_rate"]) {
    const matching = zones.filter((item) => item.sensor === sensor);
    const title = sensor === "heart_rate" ? "HF-Zonen" : "Power-Zonen";
    const seconds = new Map();
    for (const item of matching) for (const [zone, value] of Object.entries(item.seconds)) seconds.set(zone, (seconds.get(zone) || 0) + value);
    if (![...seconds.values()].some((value) => value > 0)) { details.append(reportNode("p", `${title}: keine aufgezeichneten Zonenzeiten.`, "muted")); continue; }
    details.append(trainingFocusDistribution(title, [...seconds.entries()].sort(([a], [b]) => Number(a.slice(1)) - Number(b.slice(1))).map(([label, value]) => ({label, value})), "seconds",
      `Intervals.icu: aufgezeichnete Zonenzeiten aller Sportarten in den letzten acht Wochen. HF und Power werden separat summiert; eine Einheit kann in beiden Ansichten vorkommen. Zonen beziehen sich auf die jeweils aufgezeichneten sportartspezifischen Schwellen. Fehlende Messungen werden nicht als null gewertet.`));
  }
  if (!zones.length) details.append(reportNode("p", "Noch keine aufgezeichneten HF- oder Power-Zonenzeiten vorhanden.", "muted"));
}
