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

function analysisChart(title, series, unit, start, end, note) {
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
  section.append(description);
  if (!values.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Noch keine datierten Werte in den letzten 90 Tagen vorhanden.";
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
    entry.textContent = analysisLegendText(item, latest, unit);
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
  const x = (date) => 66 + ((Date.parse(date) - Date.parse(start)) / (Date.parse(end) - Date.parse(start))) * (chartRight - 66);
  const y = (value) => 160 - (Number(value) - min) / (max - min) * 130;
  const svg = analysisSvg("svg", { viewBox: `0 0 ${chartWidth} 200`, role: "img", "aria-label": `${title}: 90-Tage-Verlauf. Einzelwerte stehen unter Werte ansehen.` });
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
  if (series.some((item) => item.unit)) section.append(legend);
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
  const root = document.querySelector("#analysisHistoryCharts");
  const expandedDetails = Array.from(root.querySelectorAll(".analysis-chart-card details"), (details) => details.open);
  root.replaceChildren();
  if (!history?.start || !history?.end) return;
  const load = history.load || { points: [] };
  const loadSeries = [["ctl", "Fitness / CTL"], ["atl", "Ermüdung / ATL"], ["tsb", "Form / TSB"]].map(([key, label]) => ({
    label, points: load.points.map((point) => ({ date: point.date, value: point[key] })),
  }));
  root.append(analysisChart("Belastung und Form", loadSeries, "", load.start || history.start, load.end || history.end,
    "CTL: langfristige Belastung (üblich 42 Tage), ATL: kurzfristige Belastung (7 Tage). Die Providerkonfiguration gilt. TSB = CTL − ATL am selben Tag. Historische Werte bis gestern; CTL ist kein Leistungstest."));
  const performanceSeries = [
    ["cycling_ftp_watts", "Rad · FTP", "W"],
    ["cycling_eftp_watts", "Rad · eFTP", "W"],
    ["run_threshold_pace_seconds_per_km", "Lauf · Schwellenpace", "s/km"],
    ["cycling_vo2max_ml_kg_min", "Rad · VO₂max", "ml/kg/min"],
    ["running_vo2max_ml_kg_min", "Lauf · VO₂max", "ml/kg/min"],
  ].flatMap(([key, label, unit], color) => (history.metrics?.[key] || []).filter((item) => item.source === (key === "cycling_eftp_watts" ? "Intervals.icu" : "Garmin Connect")).map((item) => {
    const baseline = item.points.find((point) => point.value != null && Number(point.value) > 0);
    return {
      label: `${label} · ${item.source}`, unit, color,
      line: item.source === "Garmin Connect" ? "dashed" : "solid",
      baselineDate: baseline?.date,
      points: item.points.map((point) => ({
        date: point.date, actual: point.value,
        value: analysisRelativeValue(point.value, baseline, unit),
      })),
    };
  }));
  root.append(analysisChart("Leistungsentwicklung", performanceSeries, "%", history.start, history.end,
    "Relative Veränderung ab dem ersten vorhandenen Wert je Reihe (0 %). Bei Schwellenpace bedeutet positives Wachstum eine kürzere Zeit pro Kilometer. Originalwerte und Basisdatum stehen in der Legende. Leistungswerte: Garmin; nur eFTP: Intervals.icu. VO₂max und eFTP sind Schätzungen. Datenlücken bleiben sichtbar."));
  root.querySelectorAll(".analysis-chart-card details").forEach((details, index) => {
    details.open = expandedDetails[index] ?? false;
  });
}
