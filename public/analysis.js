const ANALYSIS_SVG_NS = "http://www.w3.org/2000/svg";

const KIND_LABELS = { bike: "Fahrrad", component: "Komponente", shoes: "Schuhe", other: "Sonstiges" };
const SPORT_LABELS = { Ride: "Rad", VirtualRide: "Indoor-Rad", WeightTraining: "Kraft", Run: "Laufen", Swim: "Schwimmen", Walk: "Gehen", ride: "Rad", run: "Laufen", swim: "Schwimmen", walk: "Gehen", hike: "Wandern", strength: "Kraft", row: "Rudern", nordic_ski: "Langlauf", alpine_ski: "Alpinski", yoga: "Yoga", other: "Andere" };
const equipmentSportLabel = (item) => (item.sport === "ride" && item.environment === "virtual" ? "Indoor-Rad" : SPORT_LABELS[item.sport] || item.sport);
const isRideEquipment = (item) => ["Ride", "VirtualRide", "ride"].includes(item.sport);
const isRunEquipment = (item) => ["Run", "run"].includes(item.sport);
function analysisSvg(tag, attributes = {}, content = "") {
  const node = document.createElementNS(ANALYSIS_SVG_NS, tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  node.textContent = content;
  return node;
}

function analysisValue(value, unit) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) return "unbekannt";
  if (unit === "s/km") return formatPace(value);
  if (unit === "s") return formatDuration(Math.round(Number(value)));
  if (unit === "h") {
    const minutes = Math.round(Math.abs(Number(value)) * 60);
    return `${Number(value) < 0 ? "−" : ""}${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")} h`;
  }
  const suffix = unit ? ` ${unit}` : "";
  return `${analysisNumber(value, unit)}${suffix}`;
}

function analysisRatioUnit(unit) {
  return String(unit || "").endsWith("/bpm");
}

function analysisMinimumPadding(unit, high) {
  if (unit === "s/km") return 5;
  return analysisRatioUnit(unit) ? Math.abs(high) * .02 : 1;
}

function analysisCountUnit(unit) {
  return unit === "Schritte/Tag" || unit === "Stockwerke/Tag";
}

// Ratio units such as W/bpm keep three significant digits so small efficiencies are not rounded to zero.
function analysisNumber(value, unit) {
  const numeric = Number(value);
  if (analysisCountUnit(unit)) return AppFormat.number(Math.round(numeric), { digits: 0 });
  if (!analysisRatioUnit(unit) || !numeric) return AppFormat.number(numeric);
  return AppFormat.number(numeric, { digits: Math.max(1, 2 - Math.floor(Math.log10(Math.abs(numeric)))) });
}

function analysisCountLabel(count, singular, plural) {
  const value = Number.isFinite(Number(count)) ? Number(count) : 0;
  return `${value.toLocaleString("de-DE")} ${value === 1 ? singular : plural}`;
}

function analysisPercent(value) {
  return `${Number(value).toLocaleString("de-DE", { maximumFractionDigits: 1 })}%`;
}

function analysisLegendText(item, latest, unit) {
  if (!latest) return `${item.label}: keine Werte`;
  return `${item.label}: ${analysisPointValue(item, latest, unit)} · ${dateLabel(latest.observedDate || latest.date)}`;
}

function analysisPointValue(item, point, unit) {
  if (point.actual == null) return analysisValue(point.value, item.unit || unit);
  return `${analysisValue(point.actual, item.unit)} (${analysisValue(point.value, "%")})`;
}

function analysisLatestPoint(item) {
  return item.currentPoint || item.points.findLast(analysisValidPoint);
}

function analysisCoverageText(count, total, unitWord) {
  return `Daten für ${count} von ${total} ${unitWord} vorhanden.`;
}

let analysisInfoId = 0;

function analysisPopoverPosition(anchor, popover, viewport) {
  const margin = 12, gap = 8;
  const width = Math.min(popover.width, viewport.width - margin * 2);
  const height = Math.min(popover.height, viewport.height - margin * 2);
  const left = Math.max(margin, Math.min(anchor.left, viewport.width - width - margin));
  const below = anchor.bottom + gap;
  const above = anchor.top - gap - height;
  const fitsBelow = below + height <= viewport.height - margin;
  const top = fitsBelow || above < margin ? Math.max(margin, Math.min(below, viewport.height - height - margin)) : above;
  return { left, top };
}

function positionAnalysisPopover(button, info) {
  const rect = button.getBoundingClientRect();
  const { left, top } = analysisPopoverPosition(
    { left: rect.left, top: rect.top, bottom: rect.bottom },
    { width: info.offsetWidth, height: info.offsetHeight },
    { width: innerWidth, height: innerHeight });
  info.style.left = `${left}px`;
  info.style.top = `${top}px`;
}

function bindAnalysisPopover(button, info) {
  info.setAttribute("popover", "auto");
  info.setAttribute("role", "tooltip");
  button.setAttribute("popovertarget", info.id);
  button.setAttribute("aria-expanded", "false");
  info.addEventListener("toggle", (event) => {
    button.setAttribute("aria-expanded", String(event.newState === "open"));
    if (event.newState === "open") positionAnalysisPopover(button, info);
  });
}

function analysisChart(title, series, unit, start, end, note, {
  sparse = false, zeroCentered = false, showLegend = true, calendarWeeks = false, caption = analysisAxisCaption(unit), estimate = false,
} = {}) {
  if (!analysisHasData(series)) return null;
  const section = reportNode("section", null, "analysis-chart-card");
  const heading = reportNode("h3", title);
  if (estimate) heading.append(" ", createEstimateChip());
  section.append(heading);
  const valid = analysisValidPoint;

  const legend = reportNode("ul", null, "analysis-chart-legend");
  series.forEach((item, index) => {
    const latest = analysisLatestPoint(item);
    const entry = reportNode("li");
    entry.dataset.color = String(item.color ?? index);
    entry.dataset.line = analysisLineStyle(item, index);
    const label = item.legendLabel || item.label;
    const button = reportNode("button", label, "analysis-legend-info");
    button.type = "button";
    button.setAttribute("aria-label", `Erklärung zu ${label}`);
    const sourceInfo = item.source ? " · Quelle: " + item.source : "";
    const info = reportNode("div", `${analysisLegendText(item, latest, unit)}${sourceInfo}. ${item.explanation || note}`, "analysis-info-tooltip");
    info.dataset.series = String(index);
    info.id = `analysis-info-${++analysisInfoId}`;
    bindAnalysisPopover(button, info);
    button.setAttribute("aria-describedby", info.id);
    entry.append(button, info);
    const sourceSuffix = item.source ? " · " + item.source : "";
    if (latest) info.append(reportNode("span", `${dateLabel(latest.observedDate || latest.date)}${sourceSuffix}`, "analysis-metric-meta"));
    if (item.referenceLabel) info.append(reportNode("span", item.referenceLabel, "analysis-metric-context"));
    const readings = item.points.filter(valid);
    info.append(reportNode("span", item.coverageShort || analysisCoverageText(readings.length, item.points.length, item.cadenceDays === 7 ? "Wochen" : "Tagen"), "analysis-metric-meta"));
    if (readings.length > 1) {
      const first = readings[0];
      const delta = Number(latest.value) - Number(first.value);
      const change = analysisChange(delta, item.unit || unit);
      info.append(reportNode("span", `Seit ${dateLabel(first.observedDate || first.date)}: ${change}`, "analysis-metric-change"));
    }
    legend.append(entry);
  });
  if (showLegend && analysisLegendRepeatsTitle(series, title)) analysisLegendInfoToHeading(heading, legend, title);
  else if (showLegend) section.append(legend);
  else appendAnalysisLineKey(section, series);

  if (!series.some(analysisPlottable)) {
    section.append(reportNode("p", "Ein einzelner Messwert zeigt noch keinen Verlauf; mindestens zwei datierte Werte sind erforderlich.", "empty"));
    appendAnalysisTable(section, title, series, unit, caption);
    return section;
  }
  const fewReadings = sparse && series.every((item) => item.points.filter(valid).length < 3);
  if (fewReadings) section.querySelectorAll(".analysis-info-tooltip").forEach((info) => info.append(reportNode("p", "Wenige Messungen · kein belastbarer Trend.", "analysis-sparse-note")));
  const scales = analysisPlotScales(series, start, end, { unit, zeroCentered });
  const svg = analysisSvg("svg", { viewBox: `0 0 ${scales.chartWidth} 200`, role: "group", "aria-label": `${title}: datierter Verlauf. Tageswerte auswählen oder Werte ansehen öffnen.` });
  svg.append(analysisSvg("title", {}, `${title} · ${dateLabel(start)} bis ${dateLabel(end)}`));
  svg.append(analysisSvg("desc", {}, `Eigene Skala: ${caption}. Fehlende Messungen bleiben unbekannt.`));
  appendAnalysisAxes(svg, unit, scales, caption);
  appendAnalysisSeries(svg, series, unit, scales, zeroCentered, caption);
  const weekTicks = calendarWeeks && series.length > 0 && series.every((item) => item.cadenceDays === 7);
  appendAnalysisDateTicks(svg, start, end, scales, weekTicks ? analysisWeekTickLabel : analysisDayTickLabel);
  appendAnalysisPointInspectors(section, svg, series, unit, scales);
  section.append(svg);
  appendAnalysisReferenceNotes(section, series, unit);
  appendAnalysisTable(section, title, series, unit, caption);
  return section;
}

// A single series named like the chart only repeats the heading in its legend; its info button joins the heading instead.
function analysisLegendRepeatsTitle(series, title) {
  return series.length === 1 && (series[0].legendLabel || series[0].label) === title;
}

function analysisLegendInfoToHeading(heading, legend, title) {
  const button = legend.querySelector(".analysis-legend-info");
  button.textContent = "i";
  button.className = "analysis-legend-info analysis-info-icon";
  button.setAttribute("aria-label", `${title}: Informationen`);
  heading.append(button, legend.querySelector(".analysis-info-tooltip"));
}

// A bar series is solid; a line is dashed when the series says so or by its position (see appendAnalysisSeries).
function analysisLineStyle(item, index) {
  if (item.bars) return "solid";
  return item.line || (index ? "dashed" : "solid");
}

// Without a legend, a dashed line is named once under the heading.
function appendAnalysisLineKey(section, series) {
  const dashed = series.filter((item, index) => analysisLineStyle(item, index) === "dashed" && item.points.filter(analysisValidPoint).length >= 2);
  if (!dashed.length) return;
  const key = reportNode("p", null, "analysis-line-key");
  key.append(reportNode("span", null, "analysis-line-key-swatch"), ` Gestrichelt: ${dashed.map((item) => item.legendLabel || item.label).join(", ")}`);
  section.append(key);
}

function analysisChange(delta, unit) {
  if (unit === "s/km") return `${delta < 0 ? "−" : "+"}${formatPace(Math.abs(delta))}`;
  return `${delta < 0 ? "" : "+"}${analysisValue(delta, unit)}`;
}

function appendAnalysisReferenceNotes(section, series, unit) {
  series.forEach((item, index) => {
    const info = section.querySelector(`.analysis-legend-info + .analysis-info-tooltip[data-series="${index}"]`);
    if (item.points.some((point) => point.lower != null)) info?.append(reportNode("p", "Wochenmedian mit Streuung (25.–75. Perzentil) · nur vorhandene Messungen", "analysis-reference-note"));
    if (item.range) info?.append(reportNode("p", "Mittlere Hälfte deiner früheren Werte (Quartile) · 42 Tage vor der letzten Messung" + (item.range.status === "provisional" ? " · vorläufig" : ""), "analysis-reference-note"));
    if (item.target != null) info?.append(reportNode("p", `Ziellinie: ${analysisValue(item.target, item.unit || unit)} · persönliches Schlafziel`, "analysis-reference-note"));
    if (item.average && item.bars) {
      info?.append(reportNode("p", "Gestrichelte Linie: Durchschnitt der angezeigten Werte.", "analysis-reference-note"));
    }
  });
}

function analysisReadingDetails(point, unit) {
  let details = point.count ? ` · ${point.count} Messungen` : "";
  if (point.weekReadings > 1) details += ` · ${point.weekReadings} Messungen in der Woche`;
  if (point.observedDate && point.observedDate !== point.date) details += ` · letzter Messwert ${dateLabel(point.observedDate)}`;
  if (point.ftp_observed_at) details += ` · ${point.power_method || "FTP"} ${dateLabel(point.ftp_observed_at)}`;
  if (point.weight_observed_at) details += ` · Gewicht ${dateLabel(point.weight_observed_at)} (${point.weight_source || "Quelle unbekannt"})`;
  if (point.lower != null) details += ` · Streuung ${analysisValue(point.lower, unit)} bis ${analysisValue(point.upper, unit)}`;
  return details;
}

function analysisValidPoint(point) {
  return point?.value != null && Number.isFinite(Number(point.value));
}

// A series may lower the default two-point minimum with minPoints.
function analysisPlottable(item) {
  return item.bars || item.points.filter(analysisValidPoint).length >= (item.minPoints ?? 2);
}

function analysisHasData(series) {
  return series.some((item) => item.points.some(analysisValidPoint));
}

// A chart without any valid point is omitted without a note (#1783); its title is still collected.
function collectAnalysisChart(missing, title, ...chartArguments) {
  const chart = analysisChart(title, ...chartArguments);
  if (!chart) missing.push(title);
  return chart;
}

function appendAnalysisTable(section, title, series, unit, caption = analysisAxisCaption(unit)) {
  const details = reportNode("details");
  details.append(reportNode("summary", "Werte ansehen"));
  const scroll = makeScrollRegionFocusable(reportNode("div", null, "analysis-chart-table"), `${title}: Einzelwerte`);
  const table = reportNode("table");
  table.append(reportNode("caption", `${title} · ${caption} · nur vorhandene Werte`));
  const header = reportNode("tr");
  ["Tag", ...series.map((item) => item.label)].forEach((label) => {
    const cell = reportNode("th", label); cell.scope = "col"; header.append(cell);
  });
  const thead = reportNode("thead"); thead.append(header); table.append(thead);
  const body = reportNode("tbody");
  const dates = [...new Set(series.flatMap((item) => item.points.filter(analysisValidPoint).map((point) => point.date)))].sort((a, b) => a.localeCompare(b));
  dates.forEach((date) => {
    const row = reportNode("tr");
    const day = reportNode("th", dateLabel(date)); day.scope = "row"; row.append(day);
    series.forEach((item) => {
      const point = item.points.find((candidate) => candidate.date === date);
      let value = analysisValidPoint(point) ? analysisPointValue(item, point, unit) : "–";
      if (point?.count || point?.weekReadings || point?.observedDate) value += analysisReadingDetails(point, item.unit || unit);
      row.append(reportNode("td", value));
    });
    body.append(row);
  });
  table.append(body); scroll.append(table); details.append(scroll); section.append(details);
}

function analysisPlotScales(series, start, end, { unit = "", zeroCentered = false } = {}) {
  const values = series.flatMap((item) => [
    ...(analysisPlottable(item) ? item.points.filter(analysisValidPoint) : []).flatMap((point) => [Number(point.value), point.lower, point.upper].filter((v) => v != null && Number.isFinite(Number(v))).map(Number)),
    ...(item.range ? [item.range.lower, item.range.upper] : []),
    ...(item.target != null ? [item.target] : []),
  ]);
  let low = Math.min(...values), high = Math.max(...values);
  if (zeroCentered) { const extent = Math.max(Math.abs(low), Math.abs(high), 1); low = -extent; high = extent; }
  if (series.some((item) => item.bars)) low = Math.min(0, low);
  const padding = Math.max((high - low) * .12, analysisMinimumPadding(unit, high));
  const rawStep = (high - low + padding * 2) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  let step = [1, 2, 5, 10].find((factor) => factor * magnitude >= rawStep) * magnitude;
  if (unit === "s/km") step = Math.max(5, Math.ceil(step / 5) * 5);
  if (analysisCountUnit(unit)) step = Math.max(1, step);
  const min = series.some((item) => item.bars) ? 0 : Math.floor((low - padding) / step) * step;
  const max = Math.ceil((high + padding) / step) * step;
  // Wide screens place two charts per row, so the plot is drawn at the column width and keeps its text size.
  let chartWidth = 680;
  if (globalThis.innerWidth < 600) chartWidth = Math.max(220, globalThis.innerWidth - 80);
  else if (globalThis.innerWidth >= 1100) chartWidth = 460;
  const chartRight = chartWidth - 24;
  const x = (date) => 60 + ((Date.parse(date) - Date.parse(start)) / Math.max(86400000, Date.parse(end) - Date.parse(start))) * (chartRight - 60);
  const y = unit === "s/km" ? (value) => 30 + (Number(value) - min) / (max - min) * 130 : (value) => 160 - (Number(value) - min) / (max - min) * 130;
  return { min, max, step, chartWidth, chartRight, x, y };
}

function analysisAxisLabel(value, unit) {
  if (unit === "s/km") return formatPace(value).split(" ")[0];
  if (unit === "s") return formatDuration(Math.round(value));
  return analysisNumber(analysisRatioUnit(unit) ? value : Number(value.toFixed(3)), unit);
}

function analysisAxisCaption(unit) {
  if (unit === "s/km") return "min/km · schneller oben";
  return unit || "Belastungspunkte";
}

function appendAnalysisAxes(svg, unit, { min, max, step, chartRight, y }, caption = analysisAxisCaption(unit)) {
  for (let value = min; value <= max + step / 100; value += step) {
    svg.append(analysisSvg("line", { x1: 60, x2: chartRight, y1: y(value), y2: y(value), class: Math.abs(value) < step / 100 ? "analysis-zero-line" : "analysis-grid-line" }));
    const label = analysisAxisLabel(value, unit);
    svg.append(analysisSvg("text", { x: 52, y: y(value) + 4, "text-anchor": "end", class: "analysis-value-tick" }, label));
  }
  svg.append(analysisSvg("text", { x: 4, y: 15, class: "analysis-axis-unit" }, caption));
}

function appendAnalysisReferenceLines(svg, item, index, unit, scales, obstacles = []) {
  const { chartRight, y } = scales;
  const lineBox = (value) => ({ left: 60, right: chartRight, top: y(value) - 1.5, bottom: y(value) + 1.5 });
  if (item.range) svg.append(analysisSvg("rect", { x: 60, y: Math.min(y(item.range.lower), y(item.range.upper)), width: chartRight - 60, height: Math.max(1, Math.abs(y(item.range.lower) - y(item.range.upper))), class: "analysis-baseline-band" }));
  if (item.target != null) {
    svg.append(analysisSvg("line", { x1: 60, x2: chartRight, y1: y(item.target), y2: y(item.target), class: "analysis-target-line" }));
    obstacles.push(lineBox(item.target));
  }
  if (item.average) {
    const readings = item.points.filter(analysisValidPoint).map((point) => Number(point.value));
    if (readings.length) {
      const average = readings.reduce((sum, value) => sum + value, 0) / readings.length;
      const line = analysisSvg("line", { x1: 60, x2: chartRight, y1: y(average), y2: y(average), class: "analysis-average-line" });
      line.append(analysisSvg("title", {}, `${item.label}: Durchschnitt ${analysisValue(average, item.unit || unit)}`));
      svg.append(line);
      obstacles.push(lineBox(average));
      const text = `\u00d8 ${analysisValue(average, item.unit || unit)}`;
      if (!item.averageInHeading) obstacles.push({ left: chartRight - text.length * 7.5, right: chartRight, top: y(average) - 20, bottom: y(average) - 5 });
      if (!item.averageInHeading) svg.append(analysisSvg("text", { x: chartRight, y: y(average) - 8, "text-anchor": "end", class: "analysis-point-value analysis-average-value", stroke: "var(--surface)", "stroke-width": 4, "paint-order": "stroke", "stroke-linejoin": "round" }, `\u00d8 ${analysisValue(average, item.unit || unit)}`));
    }
  }
}

function flushAnalysisArea(svg, segment, zeroCentered, color, x, y) {
  if (zeroCentered && segment.length > 1) svg.append(analysisSvg("path", { d: `M${x(segment[0].date)},${y(0)} ` + segment.map((point) => `L${x(point.date)},${y(point.value)}`).join(" ") + ` L${x(segment.at(-1).date)},${y(0)} Z`, class: "analysis-form-area", "data-color": color }));
}

function analysisBarGeometry(item, point, { chartRight, x }) {
  const width = Math.min(24, (chartRight - 60) / Math.max(1, item.points.length) * .55);
  const left = item.connected ? x(point.date) - width / 2 : Math.max(60, Math.min(chartRight - width, x(point.date) - width / 2));
  return { left, width };
}

function appendAnalysisPointMark(svg, item, point, index, unit, scales, obstacles) {
  const { x, y } = scales;
  if (point.lower != null) {
    svg.append(analysisSvg("line", { x1: x(point.date), x2: x(point.date), y1: y(point.lower), y2: y(point.upper), class: "analysis-range-whisker", "data-color": item.color ?? index }));
    obstacles.push({ left: x(point.date) - 1, right: x(point.date) + 1, top: Math.min(y(point.lower), y(point.upper)), bottom: Math.max(y(point.lower), y(point.upper)) });
  }
  // One mark type per series (#1782): bars for per-day or per-week sums and means, dots on a line otherwise.
  if (item.bars) {
    const { left, width } = analysisBarGeometry(item, point, scales);
    const top = Math.min(y(point.value), y(0));
    const bottom = Math.max(y(point.value), y(0));
    svg.append(analysisSvg("rect", { x: left, y: top, width, height: bottom - top, rx: 3, class: item.connected ? "analysis-series-bar" : "recovery-sleep-bar", "data-color": item.color ?? index }));
    obstacles.push({ left, right: left + width, top, bottom });
    return;
  }
  const dot = analysisSvg("circle", { cx: x(point.date), cy: y(point.value), r: 2.5, "data-series": index, "data-color": item.color ?? index });
  dot.append(analysisSvg("title", {}, `${item.label} · ${dateLabel(point.date)}: ${analysisPointValue(item, point, unit)}`));
  svg.append(dot);
  obstacles.push({ left: x(point.date) - 3, right: x(point.date) + 3, top: y(point.value) - 3, bottom: y(point.value) + 3 });
}

// Only the latest, highest, lowest and first reading carry a value label (#1782); the tap readout shows the rest.
function analysisLabelledPoints(item) {
  const readings = item.points.filter(analysisValidPoint);
  if (!readings.length) return [];
  const byValue = [...readings].sort((a, b) => Number(a.value) - Number(b.value));
  return [...new Set([readings.at(-1), byValue.at(-1), byValue[0], readings[0]])];
}

function analysisPointValueLabel(item, point, { index, unit, scales }) {
  const label = analysisValue(point.value, item.unit || unit).split(" ")[0];
  const { chartRight, x, y } = scales;
  let pointX = x(point.date);
  if (item.bars) {
    const { left, width } = analysisBarGeometry(item, point, scales);
    pointX = left + width / 2;
  }
  const width = label.length * 8 + 8;
  let anchor = "middle";
  let left = pointX - width / 2;
  if (left < 60) { anchor = "start"; left = pointX - 4; }
  else if (left + width > chartRight + 16) { anchor = "end"; left = pointX - width + 4; }
  return { label, x: pointX, left, width, anchor, index, bars: Boolean(item.bars), pointY: item.bars ? Math.min(y(point.value), y(0)) : y(point.value) };
}

function analysisTextBox(x, y, text, charWidth) {
  return { left: x, right: x + String(text).length * charWidth, top: y - 12, bottom: y + 3 };
}

function analysisLineObstacles(points, { x, y }) {
  const boxes = [];
  for (let index = 1; index < points.length; index++) {
    const [x1, y1, x2, y2] = [x(points[index - 1].date), y(points[index - 1].value), x(points[index].date), y(points[index].value)];
    const steps = Math.max(1, Math.ceil(Math.hypot(x2 - x1, y2 - y1) / 3));
    for (let step = 0; step <= steps; step++) {
      const px = x1 + (x2 - x1) * step / steps;
      const py = y1 + (y2 - y1) * step / steps;
      boxes.push({ left: px - 1, right: px + 1, top: py - 1, bottom: py + 1 });
    }
  }
  return boxes;
}

function appendAnalysisSeriesPoints(svg, item, { index, unit, scales, zeroCentered, labels, obstacles }) {
  const { x, y } = scales;
  const color = item.color ?? index;
  let path = "", previous = null, segment = [], hasLinePoint = false;
  if (!analysisPlottable(item)) return path;
  item.points.forEach((point) => {
    if (!analysisValidPoint(point)) {
      flushAnalysisArea(svg, segment, zeroCentered, color, x, y);
      segment = [];
      return;
    }
    const continuous = previous && Date.parse(point.date) - Date.parse(previous.date) <= (item.cadenceDays || 1) * 86400000;
    if (!continuous) {
      flushAnalysisArea(svg, segment, zeroCentered, color, x, y);
      segment = [];
    }
    segment.push(point);
    path += `${hasLinePoint ? "L" : "M"}${x(point.date).toFixed(2)},${y(point.value).toFixed(2)} `;
    hasLinePoint = true;
    appendAnalysisPointMark(svg, item, point, index, unit, scales, obstacles);
    previous = point;
  });
  flushAnalysisArea(svg, segment, zeroCentered, color, x, y);
  for (const point of analysisLabelledPoints(item)) labels.push(analysisPointValueLabel(item, point, { index, unit, scales }));
  return path;
}

function analysisBoxesOverlap(box, other, gapX, gapY) {
  return box.left < other.right + gapX && box.right > other.left - gapX && box.top < other.bottom + gapY && box.bottom > other.top - gapY;
}

// Labels avoid marks, lines, the caption and each other and stay inside the plot; a label without a free slot is dropped.
function appendAnalysisPointLabels(svg, labels, obstacles, { chartWidth }) {
  const occupied = [];
  const accepted = [];
  const clear = (box) => box.left >= 56 && box.right <= chartWidth && box.top >= 2 && box.bottom <= 176
    && !obstacles.some((other) => analysisBoxesOverlap(box, other, 1, 1))
    && !occupied.some((other) => analysisBoxesOverlap(box, other, 6, 4));
  const seen = new Set();
  labels.forEach((label) => {
    const key = `${label.index}:${label.label}`;
    if (seen.has(key)) return;
    const offsets = label.bars ? [-10, -32, -54, -76] : [-10, 18, -30, 38, -50, 58];
    const position = offsets.map((offset) => label.pointY + offset)
      .find((y) => clear({ left: label.left, right: label.left + label.width, top: y - 12, bottom: y + 3 }));
    if (position == null) return;
    label.y = position;
    seen.add(key);
    occupied.push({ left: label.left, right: label.left + label.width, top: position - 12, bottom: position + 3 });
    accepted.push(label);
  });
  accepted.sort((a, b) => a.index - b.index || a.x - b.x);
  accepted.forEach((label) => svg.append(analysisSvg("text", { x: label.x, y: label.y, "text-anchor": label.anchor, class: "analysis-point-value", "data-value-series": label.index }, label.label)));
}

function appendAnalysisSeries(svg, series, unit, scales, zeroCentered, caption) {
  const labels = [];
  const obstacles = [analysisTextBox(4, 15, caption, 6.4)];
  series.forEach((item, index) => {
    const color = item.color ?? index;
    appendAnalysisReferenceLines(svg, item, index, unit, scales, obstacles);
    const path = appendAnalysisSeriesPoints(svg, item, { index, unit, scales, zeroCentered, labels, obstacles });
    const readings = item.points.filter(analysisValidPoint);
    if (!item.bars && readings.length >= 2) {
      svg.append(analysisSvg("path", { d: path, fill: "none", "data-series": index, "data-color": color, "data-line": analysisLineStyle(item, index) }));
      obstacles.push(...analysisLineObstacles(readings, scales));
    }
  });
  appendAnalysisPointLabels(svg, labels, obstacles, scales);
}

function analysisWeekTickLabel(dateKey) {
  return analysisDayTickLabel(dateKey);
}

function analysisDayTickLabel(dateKey) {
  return dateKey.slice(5).split("-").reverse().join(".");
}

// Tick marks sit on every day (or every week start of a weekly chart); labels repeat at an even step counted back from the latest tick.
function appendAnalysisDateTicks(svg, start, end, { chartWidth, x }, tickLabel = analysisDayTickLabel) {
  const weekly = tickLabel === analysisWeekTickLabel;
  const dates = analysisTickDates(start, end, weekly);
  const maxLabels = chartWidth < 600 ? 4 : 7;
  const step = [1, 2, 3, 4, 7, 14, 28].find((candidate) => Math.floor((dates.length - 1) / candidate) + 1 <= maxLabels) || 28;
  dates.forEach((date, index) => {
    const labelled = (dates.length - 1 - index) % step === 0;
    if (!labelled && dates.length > 31) return;
    svg.append(analysisSvg("line", { x1: x(date), x2: x(date), y1: 160, y2: labelled ? 168 : 164, class: "analysis-tick-mark" }));
    if (labelled) svg.append(analysisSvg("text", { x: x(date), y: 188, "text-anchor": "middle", class: "analysis-date-tick" }, tickLabel(date)));
  });
  if (weekly) svg.append(analysisSvg("text", { x: 4, y: 188, class: "analysis-week-caption" }, "Woche ab"));
}

function analysisTickDates(start, end, weekly) {
  const dates = [];
  for (let date = start; date <= end && dates.length < 400; date = addDateKey(date, weekly ? 7 : 1)) dates.push(date);
  return dates.length ? dates : [start];
}

function analysisPointTooltip(section, marker, title, lines) {
  const tooltip = reportNode("div", null, "analysis-info-tooltip");
  tooltip.id = `point-info-${++analysisInfoId}`;
  tooltip.setAttribute("popover", "auto");
  tooltip.setAttribute("role", "tooltip");
  tooltip.append(reportNode("strong", title));
  for (const line of lines) tooltip.append(reportNode("p", line));
  marker.setAttribute("role", "button");
  marker.setAttribute("tabindex", "0");
  marker.setAttribute("aria-label", title);
  marker.setAttribute("aria-describedby", tooltip.id);
  marker.setAttribute("aria-expanded", "false");
  marker.addEventListener("click", () => tooltip.togglePopover());
  marker.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault(); tooltip.togglePopover();
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

function appendAnalysisPointInspectors(section, svg, series, unit, { x, chartRight }) {
  const dates = [...new Set(series.flatMap((item) => item.points.map((point) => point.date)))].sort((a, b) => a.localeCompare(b));
  const hitWidth = Math.min(44, (chartRight - 60) / Math.max(1, dates.length - 1));
  const candidates = [];
  dates.forEach((date) => {
    const readings = series.map((item) => ({ item, point: item.points.find((point) => point.date === date) })).filter(({ point }) => analysisValidPoint(point));
    if (!readings.length) return;
    const marker = analysisSvg("g", { class: "analysis-day-marker", "data-date": date });
    marker.append(analysisSvg("rect", { x: Math.max(60, x(date) - hitWidth / 2), y: 26, width: Math.min(hitWidth, chartRight - Math.max(60, x(date) - hitWidth / 2)), height: 137, fill: "transparent" }));
    const lines = readings.map(({item, point}) => {
      const source = item.source ? " · " + item.source : "";
      return `${item.legendLabel || item.label}: ${analysisPointValue(item, point, unit)}${source}${analysisReadingDetails(point, item.unit || unit)}`;
    });
    analysisPointTooltip(section, marker, dateLabel(date), lines);
    const tooltip = section.lastElementChild;
    candidates.push({ date, marker, tooltip });
    marker.addEventListener("mouseenter", () => { if (matchMedia("(hover: hover)").matches && !tooltip.matches(":popover-open")) tooltip.showPopover(); });
    marker.addEventListener("mouseleave", () => { if (tooltip.matches(":popover-open") && document.activeElement !== marker) tooltip.hidePopover(); });
    marker.addEventListener("focus", () => {
      const root = section.closest(".analysis-history-charts");
      root?.querySelectorAll(".analysis-day-marker").forEach((node) => node.classList.toggle("is-selected", node.dataset.date === date));
    });
    svg.append(marker);
  });
  if (!candidates.length) return;
  // Roving tabindex: one tab stop per chart (the latest day); arrows move between days.
  const markers = candidates.map((candidate) => candidate.marker);
  const rove = (target) => markers.forEach((node) => node.setAttribute("tabindex", node === target ? "0" : "-1"));
  rove(markers.at(-1));
  markers.forEach((marker, index) => {
    marker.addEventListener("focus", () => rove(marker));
    marker.addEventListener("keydown", (event) => {
      const target = { ArrowLeft: Math.max(0, index - 1), ArrowRight: Math.min(markers.length - 1, index + 1), Home: 0, End: markers.length - 1 }[event.key];
      if (target === undefined) return;
      event.preventDefault();
      markers[target].focus();
    });
  });
  const overlay = analysisSvg("rect", { x: 60, y: 26, width: chartRight - 60, height: 137, fill: "transparent", class: "analysis-plot-hit", "aria-hidden": "true" });
  const nearest = (event) => {
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
    return candidates.reduce((best, candidate) => Math.abs(x(candidate.date) - point.x) < Math.abs(x(best.date) - point.x) ? candidate : best, candidates[0]);
  };
  overlay.addEventListener("click", (event) => {
    const candidate = nearest(event); candidate.marker.focus();
    if (!candidate.tooltip.matches(":popover-open")) candidate.tooltip.showPopover();
  });
  overlay.addEventListener("pointermove", (event) => {
    if (event.pointerType !== "mouse" || !matchMedia("(hover: hover)").matches) return;
    const candidate = nearest(event); if (!candidate.tooltip.matches(":popover-open")) candidate.tooltip.showPopover();
  });
  overlay.addEventListener("pointerleave", () => {
    candidates.forEach(({ marker, tooltip }) => { if (tooltip.matches(":popover-open") && document.activeElement !== marker) tooltip.hidePopover(); });
  });
  svg.append(overlay);
}

const analysisSectionState = new Map();

function makeAnalysisSectionCollapsible(section, key) {
  const heading = section.querySelector(":scope > h3");
  if (!heading) return section;
  const details = reportNode("details", null, "analysis-section-toggle");
  details.dataset.analysisSection = key;
  details.open = analysisSectionState.get(key) ?? true;
  const help = heading.querySelector(":scope > .analysis-legend-info");
  if (help) { help.remove(); help.classList.add("analysis-section-help"); }
  const summary = reportNode("summary"); summary.append(heading);
  const content = reportNode("div", null, "analysis-section-content");
  content.append(...section.childNodes);
  details.append(summary, content); section.append(details);
  if (help) section.append(help);
  details.addEventListener("toggle", () => analysisSectionState.set(key, details.open));
  return section;
}

function rememberAnalysisSectionState(...roots) {
  // The toggle event fires asynchronously, so a render right after a click must read the live state.
  for (const root of roots) root.querySelectorAll("details[data-analysis-section]").forEach((details) => analysisSectionState.set(details.dataset.analysisSection, details.open));
}

function analysisChartGroup(title, charts, series, note) {
  const group = reportNode("section", null, "analysis-chart-card analysis-chart-stack");
  const heading = reportNode("h3");
  heading.append(reportNode("span", title, "analysis-group-title"));
  heading.className = "analysis-group-heading";
  if (series?.length) {
    const help = reportNode("button", "i", "analysis-legend-info analysis-info-icon");
    help.type = "button"; help.setAttribute("aria-label", `${title}: Informationen`);
    const info = reportNode("div", null, "analysis-info-tooltip");
    info.id = `group-info-${++analysisInfoId}`;
    series.forEach((item) => {
      const details = [item.source, item.coverage, item.referenceLabel].filter(Boolean).join(" · ");
      if (details) info.append(reportNode("p", `${item.legendLabel || item.label}: ${details}`));
    });
    if (note) info.append(reportNode("p", note));
    bindAnalysisPopover(help, info); heading.append(help); group.append(info);
  }
  group.append(heading);
  if (note) charts.forEach((chart) => chart.querySelectorAll(".analysis-legend-info + .analysis-info-tooltip").forEach((info) => info.append(reportNode("p", note))));
  charts.forEach((chart) => {
    chart.classList.remove("analysis-chart-card"); chart.classList.add("analysis-subchart");
    const heading = chart.querySelector("h3");
    const subheading = reportNode("h4"); subheading.append(...heading.childNodes); heading.replaceWith(subheading);
    group.append(chart);
  });
  return group;
}

function analysisPeriodControls(label, value, change) {
  const controls = reportNode("div", null, "analysis-period-controls");
  controls.setAttribute("role", "group"); controls.setAttribute("aria-label", label);
  for (const [period, text] of [["fortnight", "Letzte 14 Tage"], ["twelveWeeks", "12 Wochen"]]) {
    const button = reportNode("button", text, "secondary-button"); button.type = "button";
    button.setAttribute("aria-pressed", String(period === value));
    button.addEventListener("click", () => change(period)); controls.append(button);
  }
  return controls;
}

let analysisHistoryPeriod = "twelveWeeks";
let recoveryHistoryPeriod = "fortnight";
// Report responses are reused per content version (state_versions) and in-flight requests are shared.
const analysisReportCache = new Map();

function analysisReportVersionKey() {
  const versions = state.data?.state_versions || {};
  return JSON.stringify(Object.keys(versions).sort((left, right) => left.localeCompare(right)).map((key) => [key, versions[key]]));
}

function requestAnalysisReport(path) {
  const version = analysisReportVersionKey();
  const cached = analysisReportCache.get(path);
  if (cached?.version === version) return cached.request;
  const request = api(path, { timeoutMs: DATA_LOAD_TIMEOUT_MS }).catch((error) => {
    if (analysisReportCache.get(path)?.request === request) analysisReportCache.delete(path);
    throw error;
  });
  analysisReportCache.set(path, { version, request });
  return request;
}

function invalidateAnalysisReport(path) {
  analysisReportCache.delete(path);
}

function clearAnalysisReportCache() {
  analysisReportCache.clear();
}

let cyclingPowerProfileGeneration = 0;
// One power-profile read fills the cycling profile and the running best efforts (#2265).
const PROFILE_CARDS = [["cyclingPowerProfile", "Leistungsprofil"], ["runningBestEfforts", "Bestwerte · 90 Tage"]];
const ANALYSIS_PERFORMANCE_ROUTES = new Set(["analysis", "analysis/running", "analysis/cycling"]);
const CYCLING_POWER_PROFILE_DURATIONS = [[5, "5 Sekunden"], [60, "1 Minute"], [300, "5 Minuten"], [1200, "20 Minuten"], [3600, "1 Stunde"]];

function cyclingPowerProfilePoint(result, duration) {
  const candidates = result?.windows?.["90"]?.power || [];
  return candidates.filter((item) => item.duration_seconds === duration && item.status === "ok" && item.watts != null && Number.isFinite(Number(item.watts))).sort((a, b) => Number(b.watts) - Number(a.watts))[0];
}

function cyclingPowerProfileHasValues(result) {
  return CYCLING_POWER_PROFILE_DURATIONS.some(([duration]) => cyclingPowerProfilePoint(result, duration));
}

function cyclingPowerProfileTable(result) {
  const table = reportNode("table", null, "race-predictions-table");
  const head = reportNode("thead"); const header = reportNode("tr");
  for (const label of ["Dauer", "Leistung"]) {
    const cell = reportNode("th", label); cell.scope = "col"; header.append(cell);
  }
  head.append(header); table.append(head);
  const body = reportNode("tbody");
  for (const [duration, label] of CYCLING_POWER_PROFILE_DURATIONS) {
    const row = reportNode("tr"); row.dataset.powerDuration = String(duration);
    const heading = reportNode("th", label); heading.scope = "row"; row.append(heading);
    const point = cyclingPowerProfilePoint(result, duration);
    const cell = reportNode("td", point ? analysisValue(point.watts, "W") : null);
    if (point) cell.title = [dateLabel(point.date), point.source].filter(Boolean).join(" · ");
    else markValueMissing(cell);
    row.append(cell);
    body.append(row);
  }
  table.append(body);
  const scroll = makeScrollRegionFocusable(reportNode("div", null, "table-scroll"), "Leistung nach Dauer");
  scroll.append(table);
  return scroll;
}

// One sport's experimental estimate: CS/D′ under the running best efforts, CP/W′ under the power profile (#2265).
// Beside measured bests it also names missing estimates; alone, a line of only missing ones is dropped.
function criticalPowerLine(result, sport, hasValues) {
  const estimate = result?.critical_power;
  const fits = (estimate?.fits || []).filter((fit) => fit.sport === sport);
  if (!fits.length || (!hasValues && !fits.some((fit) => fit.status === "ok"))) return null;
  const labels = { "ride:outdoor": "Rad outdoor", "ride:indoor": "Rad indoor", "run:outdoor": "Lauf" };
  const parts = fits.map((fit) => {
    const label = labels[`${fit.sport}:${fit.environment}`] || fit.sport;
    if (fit.status !== "ok") return `${label} —`;
    const value = fit.sport === "run"
      ? `${label} CS ${AppFormat.number(fit.cs_mps, { digits: 2 })} m/s · D′ ${analysisValue(fit.d_prime_meters, "m")} (unsicher)`
      : `${label} CP ${analysisValue(fit.cp_watts, "W")} · W′ ${analysisValue(fit.w_prime_joules / 1000, "kJ")} (unsicher)`;
    const races = (fit.efforts || []).filter((effort) => effort.effort_context === "race").length;
    return races ? `${value} · ${races}× Wettkampf` : value;
  });
  const line = reportNode("p", null, "analysis-reference-note");
  line.append(createEstimateChip(), ` Experimentell · ${sport === "run" ? "CS" : "CP"} (${estimate.window_days} Tage): ${parts.join(" · ")}`);
  line.dataset.criticalPower = "true";
  line.title = estimate.scope || "";
  return line;
}

// Both profile cards show the read's loading state once, or its failure with a retry.
function showProfileCardsState(error) {
  for (const [id, title] of PROFILE_CARDS) {
    const target = document.getElementById(id);
    if (!error && target.childElementCount && target.dataset.analysisEmpty !== "failed") continue;
    target.dataset.analysisEmpty = error ? "failed" : "loading";
    target.replaceChildren(reportNode("h4", title), error
      ? createErrorState(error.message, () => void renderCyclingPowerProfile())
      : createLoadingState(`${title} wird geladen…`));
  }
}

async function renderCyclingPowerProfile() {
  if (!ANALYSIS_PERFORMANCE_ROUTES.has(state.route) || !state.data?.performance) return;
  const generation = ++cyclingPowerProfileGeneration;
  const session = state.sessionGeneration;
  showProfileCardsState(null);
  try {
    const result = await requestAnalysisReport("/api/analysis/power-profiles");
    if (generation !== cyclingPowerProfileGeneration || session !== state.sessionGeneration) return;
    renderPowerProfile(result);
    renderRunningBestEfforts(result);
    renderAnalysisSegmentsIfActive();
  } catch (error) {
    if (generation === cyclingPowerProfileGeneration && session === state.sessionGeneration) {
      showProfileCardsState(error || new Error());
      renderAnalysisSegmentsIfActive();
    }
  }
}

function renderPowerProfile(result) {
  const root = document.getElementById("cyclingPowerProfile");
  root.replaceChildren(reportNode("h4", "Leistungsprofil"));
  const hasValues = cyclingPowerProfileHasValues(result);
  if (hasValues) {
    root.append(reportNode("p", "Beste gemessene Durchschnittsleistung · letzte 90 Tage · Rad und Indoor zusammen", "analysis-reference-note"));
    root.append(cyclingPowerProfileTable(result));
  } else root.append(reportNode("p", "Noch keine Leistungsdaten.", "muted"));
  const coverage = result.windows?.["90"]?.cache_coverage;
  if (coverage?.power_unknown_records > 0) {
    const gap = reportNode("p", `Für ${coverage.power_unknown_records} von ${coverage.power_records} Radeinheiten fehlen vollständige Messreihen; die Bestwerte können höher liegen.`, "analysis-reference-note");
    gap.dataset.powerProfileGap = "true";
    root.append(gap);
  }
  const criticalPower = criticalPowerLine(result, "ride", hasValues);
  if (criticalPower) root.append(criticalPower);
  root.dataset.analysisEmpty = String(!hasValues && !criticalPower);
}

// The fastest observed pace per duration and time per distance of the last 90 days (#2265),
// in the targets and order the report returns.
function runningBestEffortRow(kind, point) {
  const minutes = point.duration_seconds / 60;
  const unit = minutes === 1 ? "Minute" : "Minuten";
  const label = kind === "speed" ? `${AppFormat.number(minutes)} ${unit}` : `${AppFormat.number(point.distance_meters / 1000)} km`;
  let text = null;
  if (kind === "speed" && point.speed_mps > 0) text = formatPace(1000 / Number(point.speed_mps));
  else if (kind === "distance" && point.seconds > 0) text = AppFormat.clock(point.seconds);
  return { label, text, key: `${kind}:${kind === "speed" ? point.duration_seconds : point.distance_meters}` };
}

function renderRunningBestEfforts(result) {
  const root = document.getElementById("runningBestEfforts");
  const running = result?.windows?.["90"]?.running || {};
  root.replaceChildren(reportNode("h4", "Bestwerte · 90 Tage"));
  const body = reportNode("tbody");
  let values = 0;
  for (const kind of ["speed", "distance"]) {
    for (const point of running[kind] || []) {
      const { label, text, key } = runningBestEffortRow(kind, point);
      const row = reportNode("tr"); row.dataset.runningBest = key;
      const heading = reportNode("th", label); heading.scope = "row";
      const cell = reportNode("td", text);
      if (text) { values += 1; cell.title = [dateLabel(point.date), point.source].filter(Boolean).join(" · "); } else markValueMissing(cell);
      row.append(heading, cell); body.append(row);
    }
  }
  if (values) {
    const table = reportNode("table", null, "race-predictions-table");
    table.append(body);
    const scroll = makeScrollRegionFocusable(reportNode("div", null, "table-scroll"), "Lauf-Bestwerte");
    scroll.append(table); root.append(scroll);
  } else root.append(reportNode("p", "Noch keine Lauf-Bestwerte.", "muted"));
  const criticalSpeed = criticalPowerLine(result, "run", values > 0);
  if (criticalSpeed) root.append(criticalSpeed);
  root.dataset.analysisEmpty = String(!values && !criticalSpeed);
}

function equipmentRouteActive() {
  return state.route === "more/equipment";
}

globalThis.matchMedia("(max-width: 599px)").addEventListener("change", () => {
  if (state.data) { renderAnalysisHistory(state.data.performance?.history); renderPersonalRecovery(state.data.performance?.personal_recovery); }
});

function performanceSeriesExplanation(key) {
  if (key === "cycling_ftp_watts") return "Alle datierten Garmin-FTP-Messungen.";
  if (key.includes("vo2max")) return "Wochenmedian aus vorhandenen Messungen.";
  return "Letzter gültiger Messwert je Woche.";
}

function renderAnalysisHistory(history) { // NOSONAR
  const root = document.querySelector("#analysisHistoryCharts");
  const loadRoot = document.querySelector("#analysisLoadCharts");
  const enduranceRoot = document.querySelector("#performanceEnduranceCharts");
  const predictions = document.getElementById("performancePredictions");
  const powerProfile = document.getElementById("cyclingPowerProfile");
  const runningBest = document.getElementById("runningBestEfforts");
  powerProfile.remove();
  predictions.remove();
  runningBest.remove();
  predictions.classList.remove("analysis-chart-card");
  predictions.classList.add("analysis-subchart");
  renderBodyAnalysis(history?.body);
  const openDetails = new Set([...root.querySelectorAll("details[open]"), ...loadRoot.querySelectorAll("details[open]"), ...enduranceRoot.querySelectorAll("details[open]")].map((details) => `${details.closest("section")?.querySelector("h3,h4")?.textContent}:${details.querySelector("summary")?.textContent}`));
  const periodRoot = document.getElementById("analysisLoadPeriod");
  rememberAnalysisSectionState(root, loadRoot, enduranceRoot);
  root.replaceChildren(); loadRoot.replaceChildren(); enduranceRoot.replaceChildren(); periodRoot.replaceChildren();
  if (!history?.start || !history?.end) {
    // Without a history window there are no charts, so no empty sport groups; the async tables stay attached.
    root.append(predictions, runningBest, powerProfile);
    for (const target of [root, loadRoot, enduranceRoot]) target.dataset.analysisEmpty = "true";
    Object.assign(root.dataset, { analysisEmptyRunning: "true", analysisEmptyCycling: "true" });
    return;
  }
  const end = history.end;
  const weekStart = addDateKey(end, -((new Date(`${end}T12:00:00Z`).getUTCDay() + 6) % 7));
  const start = analysisHistoryPeriod === "fortnight" ? addDateKey(end, -13) : addDateKey(weekStart, -77);
  periodRoot.append(analysisPeriodControls("Zeitraum für Belastung", analysisHistoryPeriod, (period) => {
    analysisHistoryPeriod = period;
    renderAnalysisHistory(history);
    renderTrainingFocus(state.data?.performance?.training_focus_periods?.[period] || state.data?.performance?.training_focus);
  }));
  const performanceStart = addDateKey(weekStart, -77);
  const load = history.load || { points: [] };
  const loadSeries = [{ label: "Akute Belastung", legendLabel: "Akute Belastung", source: load.source, unit: "", color: 0,
    cadenceDays: analysisHistoryPeriod === "twelveWeeks" ? 7 : 1, average: true, averageInHeading: true,
    points: analysisHistoryPeriod === "twelveWeeks" ? analysisWeeklyLastPoints(load.points.filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value })), start, end) : load.points.filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value })),
    currentPoint: load.points.filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value })).findLast(analysisValidPoint) }];
  const loadValues = loadSeries[0].points.filter(analysisValidPoint).map((point) => Number(point.value));
  const loadAverage = loadValues.length ? loadValues.reduce((sum, value) => sum + value, 0) / loadValues.length : null;
  const loadTitle = loadAverage == null ? "Akute Belastung" : `Akute Belastung \u00b7 \u00d8 ${analysisValue(loadAverage, "")}`;
  const sourcePrefix = (source) => (source ? `${source}: ` : "");
  const loadMissing = [];
  const loadChart = collectAnalysisChart(loadMissing, loadTitle, loadSeries, "", start, end, `${sourcePrefix(load.source)}gemessene akute Trainingsbelastung. Gestrichelte Linie: Durchschnitt der angezeigten Werte. Fehlende Messungen bleiben L\u00fccken.`, { calendarWeeks: analysisHistoryPeriod === "twelveWeeks", caption: analysisBasisCaption("Belastungspunkte", analysisHistoryPeriod === "twelveWeeks", "state") });
  if (loadChart) {
    loadChart.querySelector(".analysis-chart-legend")?.remove();
    loadRoot.append(loadChart);
  }
  const timePoints = (history.training_time?.points || []).filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value }));
  if (timePoints.some(analysisValidPoint)) {
    const weekly = analysisHistoryPeriod === "twelveWeeks";
    const timeSeries = [{ label: weekly ? "Trainingszeit pro Woche" : "Trainingszeit pro Tag", legendLabel: "Trainingszeit", source: history.training_time.source, unit: "h", color: 1, bars: true, connected: true, cadenceDays: weekly ? 7 : 1, average: true, averageInHeading: true, points: weekly ? analysisWeeklySumPoints(timePoints, start, end) : timePoints }];
    const timeValues = timeSeries[0].points.filter(analysisValidPoint).map((point) => Number(point.value));
    const timeAverage = timeValues.reduce((sum, value) => sum + value, 0) / timeValues.length;
    const timeCadence = weekly ? " pro Woche" : " pro Tag";
    const timeTitle = timeValues.length ? `Trainingszeit \u00b7 \u00d8 ${analysisValue(timeAverage, "h")}${timeCadence}` : "Trainingszeit";
    const timeChart = collectAnalysisChart(loadMissing, timeTitle, timeSeries, "h", start, end, `${sourcePrefix(history.training_time.source)}Summe der Bewegungszeit erfasster Aktivit\u00e4ten, jede Aktivit\u00e4t einmal. Tage und Wochen ohne erfasste Dauer bleiben L\u00fccken.`, { calendarWeeks: weekly, caption: analysisBasisCaption("h", weekly, "sum") });
    if (timeChart) {
      timeChart.querySelector(".analysis-chart-legend")?.remove();
      loadRoot.append(timeChart);
    }
  } else {
    loadMissing.push("Trainingszeit");
  }
  appendSessionRpeLoadChart(history.session_rpe_load, loadRoot, loadMissing, start, end);
  appendSmoothedLoadChart(history.smoothed_session_load, history.session_rpe_load, loadRoot, loadMissing, start, end);
  appendLocalFitnessChart(history.local_fitness_fatigue, loadRoot, loadMissing, start, end);
  appendDailyActivityGroup(history.daily_activity, loadRoot, loadMissing, start, end);
  const performanceSeries = [
    ["cycling_ftp_watts", "Rad · FTP", "W", 0],
    ["run_threshold_pace_seconds_per_km", "Lauf · Schwellenpace", "s/km", 2],
    ["cycling_vo2max_ml_kg_min", "Rad · VO₂max", "ml/kg/min", 3],
    ["running_vo2max_ml_kg_min", "Lauf · VO₂max", "ml/kg/min", 4],
  ].flatMap(([key, label, unit, color]) => (history.metrics?.[key] || []).filter((item) => isPreferredSource(item, history.preferred_providers?.[key])).map((item) => ({
    label: `${label} · ${item.source}`, legendLabel: label.replace(/^Rad \u00b7 /, ""), source: item.source, unit, color,
    line: key.includes("vo2max") ? "dashed" : "solid",
    cadenceDays: key === "cycling_ftp_watts" ? 1 : 7,
    explanation: performanceSeriesExplanation(key),
    currentPoint: item.points.filter((point) => point.date <= end).findLast(analysisValidPoint),
    points: key === "cycling_ftp_watts" ? item.points.filter((point) => point.date >= performanceStart && point.date <= end) : analysisWeeklyPerformancePoints(item.points, performanceStart, end, key.includes("vo2max")),
  })));
  // Each sport's development sits in its own segment, so the group is only "Entwicklung" (#2265).
  for (const [sport, primaryUnit, analysisSport] of [["Lauf", "s/km", "run"], ["Rad", "W", "ride"]]) {
    const sportSeries = performanceSeries.filter((item) => item.label.startsWith(sport));
    const missing = [];
    const charts = [[primaryUnit, primaryUnit === "W" ? "Leistungsschwelle · FTP" : "Schwellenpace"], ["ml/kg/min", "VO₂max"]].map(([unit, metric]) => collectAnalysisChart(missing, metric, sportSeries.filter((item) => item.unit === unit), unit, performanceStart, end, "", { compactInfo: true, sparse: true, includeCoverage: false, showLegend: unit === "W", calendarWeeks: true, estimate: unit === "ml/kg/min" })).filter(Boolean);
    if (sport === "Lauf") {
      const extra = document.createDocumentFragment();
      renderProviderMetrics({ running_tolerance: history.provider_metrics?.running_tolerance }, extra, performanceStart, end, missing);
      charts.push(...extra.children);
    }
    root.dataset[analysisSport === "run" ? "analysisEmptyRunning" : "analysisEmptyCycling"] = String(!charts.length);
    const group = analysisChartGroup("Entwicklung", charts, sportSeries, "Letzte 12 Kalenderwochen einschließlich der laufenden Woche: alle datierten Garmin-FTP-Werte, letzter gültiger Wochenwert für Schwellenpace, Wochenmedian für VO₂max. Fehlende Messungen bleiben Lücken. Garmin. VO₂max ist eine Schätzung. Quellen und Messdatum bleiben sichtbar.");
    makeAnalysisSectionCollapsible(group, `development-${sport}`);
    group.dataset.analysisSport = analysisSport;
    if (sport === "Lauf") group.querySelector(".analysis-section-content").append(runningBest, predictions);
    else group.querySelector(".analysis-section-content").prepend(powerProfile);
    root.append(group);
  }
  // The endurance score rates all sports' long-term training, so it sits in Belastung (#2265);
  // readiness is charted in Erholung and the weekly training status only repeats the acute load.
  const extra = document.createDocumentFragment();
  renderProviderMetrics({ endurance_score: history.provider_metrics?.endurance_score }, extra, start, end, []);
  while (extra.firstElementChild) enduranceRoot.append(makeAnalysisSectionCollapsible(extra.firstElementChild, "endurance-score"));
  root.dataset.analysisEmpty = String(root.dataset.analysisEmptyRunning === "true" && root.dataset.analysisEmptyCycling === "true");
  loadRoot.dataset.analysisEmpty = String(!loadRoot.childElementCount);
  enduranceRoot.dataset.analysisEmpty = String(!enduranceRoot.childElementCount);
  for (const target of [root, loadRoot, enduranceRoot]) target.querySelectorAll("details:not([data-analysis-section])").forEach((details) => { details.open = openDetails.has(`${details.closest("section")?.querySelector("h3,h4")?.textContent}:${details.querySelector("summary")?.textContent}`); });
}

function sessionRpeSourceLabel(days, rated) {
  const provider = days.reduce((sum, day) => sum + day.rpe_sources.provider, 0);
  const providerLabel = [...new Set(days.flatMap((day) => day.rpe_provider_labels || []))].sort((a, b) => a.localeCompare(b)).join(" + ") || "Anbieter";
  if (!rated) return "Athletenfeedback";
  if (provider === rated) return providerLabel;
  return provider ? `Athletenfeedback + ${providerLabel}` : "Athletenfeedback";
}

// Session-RPE load (AU) stays its own chart: it is never added to or compared with provider load.
function appendSessionRpeLoadChart(report, loadRoot, loadMissing, start, end) {
  const days = (report?.days || []).filter((day) => day.date >= start && day.date <= end);
  const rated = days.reduce((sum, day) => sum + day.rated_sessions, 0);
  if (!rated) { loadMissing.push("Session-RPE-Last"); return; }
  const total = days.reduce((sum, day) => sum + day.total_sessions, 0);
  const source = sessionRpeSourceLabel(days, rated);
  const weekly = analysisHistoryPeriod === "twelveWeeks";
  const points = days.map((day) => ({ date: day.date, value: day.value }));
  const series = [{ label: weekly ? "Session-RPE-Last pro Woche" : "Session-RPE-Last pro Tag", legendLabel: "Session-RPE-Last", source, unit: "AU", color: 2, bars: true, connected: true, cadenceDays: weekly ? 7 : 1, points: weekly ? analysisWeeklySumPoints(points, start, end) : points }];
  const chart = analysisChart(`Session-RPE-Last · ${rated}/${total} bewertet`, series, "AU", start, end, `${source}: RPE × Gesamtdauer je Einheit.`, { calendarWeeks: weekly, caption: analysisBasisCaption("AU", weekly, "sum"), estimate: true });
  if (!chart) { loadMissing.push("Session-RPE-Last"); return; }
  chart.querySelector(".analysis-chart-legend")?.remove();
  loadRoot.append(chart);
}

// Smoothed session-RPE load: own AU curves, never compared with provider load; gaps stay gaps.
function appendSmoothedLoadChart(report, rpeReport, loadRoot, loadMissing, start, end) {
  const days = (report?.days || []).filter((day) => day.date >= start && day.date <= end);
  if (!days.some((day) => day.short != null || day.long != null)) { loadMissing.push("Kurz-/Langzeitbelastung"); return; }
  const weekly = analysisHistoryPeriod === "twelveWeeks";
  // The curves carry load from before the window, so their label reads every reported day.
  const rpeDays = (rpeReport?.days || []).filter((day) => day.date <= end);
  const source = sessionRpeSourceLabel(rpeDays, rpeDays.reduce((sum, day) => sum + day.rated_sessions, 0));
  const series = [["short", "Kurzzeitbelastung", 2], ["long", "Langzeitbelastung", 5]].map(([key, label, color]) => {
    const points = days.map((day) => ({ date: day.date, value: day[key] }));
    return { label, legendLabel: label, source, unit: "AU", color, connected: true, cadenceDays: weekly ? 7 : 1,
      points: weekly ? analysisWeeklyLastPoints(points, start, end) : points, currentPoint: points.findLast(analysisValidPoint) };
  });
  const chart = collectAnalysisChart(loadMissing, "Kurz-/Langzeitbelastung", series, "AU", start, end, "", { calendarWeeks: weekly, caption: analysisBasisCaption("AU", weekly, "state"), estimate: true });
  if (chart) loadRoot.append(chart);
}

// Local fitness, fatigue and form (card M7): TSS-scale, never mixed with Intervals.icu CTL/ATL.
function appendLocalFitnessChart(report, loadRoot, loadMissing, start, end) {
  const title = "Fitness, Ermüdung, Form";
  const days = (report?.days || []).filter((day) => day.date >= start && day.date <= end);
  if (!days.some((day) => day.fitness != null || day.fatigue != null)) { loadMissing.push(title); return; }
  const weekly = analysisHistoryPeriod === "twelveWeeks";
  const series = [["fitness", "Fitness", 0], ["fatigue", "Ermüdung", 1], ["form", "Form", 3]].map(([key, label, color]) => {
    const points = days.map((day) => ({ date: day.date, value: day[key] }));
    return { label, legendLabel: label, source: "Lokal berechnet", unit: "TSS/Tag", color, connected: true, cadenceDays: weekly ? 7 : 1,
      points: weekly ? analysisWeeklyLastPoints(points, start, end) : points, currentPoint: points.findLast(analysisValidPoint) };
  });
  const unloaded = days.reduce((sum, day) => sum + (day.sessions_without_load || 0), 0);
  const unloadedNote = unloaded === 1 ? "1 Einheit ohne TSS" : `${unloaded} Einheiten ohne TSS`;
  // Share of the visible days, so the note matches the shown period like the session count.
  const incompletePercent = Math.round(100 * days.filter((day) => day.state === "incomplete").length / days.length);
  const notes = [];
  if (unloaded) notes.push(unloadedNote);
  if (incompletePercent > 0) notes.push(`${incompletePercent} % der Tage unvollständig`);
  const chart = collectAnalysisChart(loadMissing, title, series, "TSS/Tag", start, end, notes.join(" · "), { calendarWeeks: weekly, caption: analysisBasisCaption("TSS/Tag", weekly, "state"), estimate: true });
  if (chart) loadRoot.append(chart);
}

// Steps and floors are whole counts per day; the weekly view plots the daily mean of each week (#1782).
function dailyActivityMetrics() {
  return [
    { key: "steps", label: "Schritte", unit: "Schritte/Tag", color: 3 },
    { key: "floors", label: "Stockwerke", unit: "Stockwerke/Tag", color: 4 },
  ];
}

// Names what one plotted value is: a daily value, a weekly sum or mean, or the state at the end of the week.
function analysisBasisCaption(unit, weekly, kind) {
  const basis = {
    state: weekly ? "Wochenstand" : "Tageswert",
    sum: weekly ? "Wochensumme" : "Tagessumme",
    mean: weekly ? "Wochenmittel" : "",
  }[kind];
  return basis ? `${unit} · ${basis}` : unit;
}

function dailyActivityTitle(label, unit, daily) {
  const values = daily.filter(analysisValidPoint).map((point) => Number(point.value));
  if (!values.length) return label;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return `${label} · Ø ${analysisNumber(mean, unit)} pro Tag`;
}

function appendDailyActivityGroup(activity, loadRoot, loadMissing, start, end) {
  if (!activity) return;
  const weekly = analysisHistoryPeriod === "twelveWeeks";
  const charts = []; const allSeries = [];
  for (const { key, label, unit, color } of dailyActivityMetrics()) {
    const daily = (activity[key] || []).filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value }));
    const points = weekly ? analysisWeeklyMeanPoints(daily, start, end) : daily;
    const current = daily.findLast(analysisValidPoint);
    const series = [{ label: weekly ? `${label} Ø pro Tag` : label, legendLabel: label, source: activity.source, unit, color, bars: true, connected: true, cadenceDays: weekly ? 7 : 1, points, currentPoint: current }];
    const chart = collectAnalysisChart(loadMissing, dailyActivityTitle(label, unit, daily), series, unit, start, end, `${activity.source}: ${weekly ? "Tagesdurchschnitt je Woche" : "Tageswerte"}. Fehlende Tage bleiben Lücken.`, { calendarWeeks: weekly, caption: analysisBasisCaption(unit, weekly, "mean") });
    if (!chart) continue;
    chart.querySelector(".analysis-chart-legend")?.remove();
    charts.push(chart); allSeries.push(series[0]);
  }
  if (charts.length) loadRoot.append(analysisChartGroup("Alltagsaktivität", charts, allSeries));
}

function providerMetricLabel(key) {
  return { endurance_score: "Ausdauer-Score", running_tolerance: "Lauf-Belastbarkeit", training_readiness_history: "Trainingsbereitschaft", weekly_training_status: "Trainingsstatus · akute Belastung" }[key] || key;
}

function providerMetricUnit(key) {
  return { endurance_score: "Punkte", training_readiness_history: "Punkte" }[key] || "";
}

function providerMetricValue(metric, values) {
  const fields = {
    endurance_score: ["overallScore", "enduranceScore", "score", "groupAverage"],
    running_tolerance: ["toleranceScore", "runningTolerance", "tolerance"],
  }[metric] || [];
  for (const field of fields) {
    const value = values?.[field];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function renderProviderMetrics(metrics, root, start, end, missing) {
  Object.entries(metrics || {}).forEach(([key, item], index) => {
    const projected = key === "training_readiness_history" || key === "weekly_training_status";
    const raw = (Array.isArray(item?.points) ? item.points : []).map((point) => ({ date: point?.date, value: projected ? point?.value : providerMetricValue(key, point?.values) })).filter((point) => point.date && typeof point.value === "number" && Number.isFinite(point.value));
    if (!raw.some(analysisValidPoint)) { missing.push(providerMetricLabel(key)); return; }
    const daily = key === "training_readiness_history";
    const points = daily ? raw.filter((point) => point.date >= start && point.date <= end) : analysisWeeklyPerformancePoints(raw, start, end, false);
    const series = [{ label: providerMetricLabel(key), legendLabel: providerMetricLabel(key), source: item.source, unit: providerMetricUnit(key), color: index, cadenceDays: daily ? 1 : 7, points, currentPoint: raw.filter((point) => point.date <= end).findLast(analysisValidPoint) }];
    const chart = collectAnalysisChart(missing, providerMetricLabel(key), series, providerMetricUnit(key), start, end, "", { sparse: true, showLegend: false, calendarWeeks: true });
    if (!chart) return;
    chart.querySelector(".analysis-chart-legend")?.remove();
    root.append(chart);
  });
}

let bodyHistoryPeriod = "twelveWeeks";

function bodyWeeklyPoints(points, start, end) {
  const weeks = [];
  for (let weekStart = start; weekStart <= end; weekStart = addDateKey(weekStart, 7)) {
    const offset = Math.min(6, Math.round((Date.parse(end) - Date.parse(weekStart)) / 86400000));
    const boundedEnd = addDateKey(weekStart, offset);
    const readings = points.filter((point) => point.date >= weekStart && point.date <= boundedEnd && analysisValidPoint(point));
    const latest = readings.at(-1);
    weeks.push(latest
      ? { ...latest, date: boundedEnd, weekReadings: readings.length, observedDate: latest.observed_at || latest.date }
      : { date: boundedEnd, value: null, weekReadings: 0 });
  }
  return weeks;
}

function bodySeriesPoints(item, window, period = bodyHistoryPeriod) {
  const points = (item.points || []).filter((point) => point.date >= window.start && point.date <= window.end)
    .map((point) => ({ ...point, power_method: item.power_method, observedDate: point.observed_at || point.date }));
  return period === "twelveWeeks" ? bodyWeeklyPoints(points, window.start, window.end) : points;
}

function bodyMetricChart(metric, title, unit, window, period, preferred = {}) {
  const power = metric === "cycling_w_per_kg";
  const entries = (window.metrics?.[metric] || []).filter((item) => power || isPreferredSource(item, preferred[metric]));
  const series = entries.map((item, index) => ({
    label: power ? [item.power_method, item.source].filter(Boolean).join(" \u00b7 ") : title,
    legendLabel: power ? item.source : title,
    source: power ? item.source : "",
    unit,
    color: index,
    noCurrentLine: true,
    sparse: true,
    // A single measured week is still drawn as a point.
    minPoints: period === "twelveWeeks" ? 1 : 2,
    cadenceDays: period === "twelveWeeks" ? 7 : 1,
    explanation: metric === "cycling_w_per_kg"
      ? "Tageswert aus FTP geteilt durch das letzte Körpergewicht der vorherigen sieben Tage."
      : "Nur gemessene Tageswerte; fehlende Tage bleiben Lücken.",
    points: bodySeriesPoints(item, window, period),
  }));
  const chart = analysisChart(title, series, unit, window.start, window.end,
    metric === "cycling_w_per_kg"
      ? "W/kg verwendet FTP (Garmin Connect) und ein höchstens sieben Tage altes gemessenes Gewicht."
      : "Gemessene Verlaufswerte. Fehlende Messungen werden nicht ergänzt.",
    { sparse: true });
  if (!chart) return null;
  chart.dataset.bodyMetric = metric;
  if (period === "twelveWeeks") chart.querySelectorAll(".analysis-info-tooltip").forEach((info) => {
    info.append(reportNode("p", "12 rollierende Wochen: letzter Messwert je Woche.", "analysis-reference-note"));
  });
  if (metric === "cycling_w_per_kg") chart.querySelectorAll(".analysis-info-tooltip").forEach((info, index) => {
    const item = entries[index];
    if (item?.power_method) info.append(reportNode("p", `Methode: ${item.power_method}. FTP- und Gewichtsdatum sind in den Einzelwerten getrennt ausgewiesen.`, "analysis-reference-note"));
  });
  return chart;
}

function bodyProfileFat(profile) {
  const raw = profile?.body_fat_pct;
  if (raw == null || String(raw).trim() === "") return null;
  const value = Number(String(raw).replace(",", "."));
  return Number.isFinite(value) && value >= 1 && value <= 70 ? value : null;
}

function bodyOverviewDisplayValue(profileFat, latest, unit) {
  if (profileFat != null) return analysisValue(profileFat, unit);
  if (latest) return analysisValue(latest.value, unit);
  return "\u2014";
}

function renderBodyOverviewRow(metric, title, unit, body, preferred) {
  const readings = Object.values(body?.windows || {}).flatMap((window) => (window.metrics?.[metric] || [])
    .filter((item) => isPreferredSource(item, preferred[metric]))
    .flatMap((item) => (item.points || []).filter((point) => point.date >= window.start && point.date <= window.end && analysisValidPoint(point))));
  readings.sort((a, b) => (a.observed_at || a.date).localeCompare(b.observed_at || b.date));
  const latest = readings.at(-1);
  const row = reportNode("tr");
  row.dataset.metric = metric;
  const heading = reportNode("th", title);
  heading.scope = "row";
  const profileFat = metric === "body_fat_pct" ? bodyProfileFat(state.data?.profile) : null;
  if (profileFat != null) heading.append(reportNode("small", "Profil"));
  else if (latest) heading.append(reportNode("small", dateLabel(latest.observed_at || latest.date)));
  row.append(heading, reportNode("td", bodyOverviewDisplayValue(profileFat, latest, unit)));
  return row;
}

function renderBodyAnalysis(body) {
  const root = document.getElementById("bodyAnalysisCharts");
  if (!root) return;
  const openDetails = new Set([...root.querySelectorAll("details[open]")].map((item) => item.querySelector("summary")?.textContent));
  root.replaceChildren();
  const metrics = [
    ["weight_kg", "Gewicht", "kg"],
    ["body_fat_pct", "Körperfett", "%"],
  ];
  const preferred = body?.preferred_providers || {};
  const overview = reportNode("section", null, "analysis-chart-card");
  const table = reportNode("table", null, "current-performance-table");
  table.dataset.bodyOverview = "";
  table.append(reportNode("caption", "Körperwerte"));
  const rows = reportNode("tbody");
  for (const [metric, title, unit] of metrics) {
    rows.append(renderBodyOverviewRow(metric, title, unit, body, preferred));
  }
  table.append(rows); overview.append(table); root.append(overview);
  const key = bodyHistoryPeriod === "fortnight" ? "14d" : "12w";
  const window = body?.windows?.[key];
  root.append(analysisPeriodControls("Zeitraum für Körper", bodyHistoryPeriod, (period) => {
    bodyHistoryPeriod = period;
    renderBodyAnalysis(body);
  }));
  if (!window?.start || !window?.end) {
    root.append(reportNode("p", "Noch keine Körper-Historie verfügbar.", "empty"));
    return;
  }
  for (const [metric, title, unit] of metrics) {
    const chart = bodyMetricChart(metric, title, unit, window, bodyHistoryPeriod, preferred);
    if (chart) root.append(chart);
  }
  root.querySelectorAll("details").forEach((details) => { details.open = openDetails.has(details.querySelector("summary")?.textContent); });
}

let trainingRecordsGeneration = 0;
let equipmentTab = "bike";

async function renderTrainingRecords() { // NOSONAR
  if (!state.data || !equipmentRouteActive()) return;
  const generation = ++trainingRecordsGeneration;
  const session = state.sessionGeneration;
  const gear = document.getElementById("equipmentItems");
  const heading = () => reportNode("h3", "Ausrüstung und Wartung");
  // Only a section without a rendered list shows loading and failure; a failed refresh keeps the list.
  const rendered = () => Boolean(gear.querySelector(".equipment-tabs"));
  if (!rendered()) gear.replaceChildren(heading(), createLoadingState("Ausrüstung wird geladen…"));
  try {
    const result = await requestAnalysisReport("/api/analysis/training-records");
    if (generation !== trainingRecordsGeneration || session !== state.sessionGeneration) return;
    const openDetails = new Set([...gear.querySelectorAll("details[open]")]
      .map((details) => `${details.closest(".equipment-tab-panel")?.id || "other"}:${details.querySelector("summary")?.textContent || ""}`));
    gear.replaceChildren(heading());
    const equipment = result.equipment || {};
    const items = equipment.garmin_items || [];
    const tabs = reportNode("div", null, "segmented-control equipment-tabs");
    tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Ausrüstung nach Sportart");
    const localItems = equipment.items || [];
    const isArchivedEquipment = (item) => item.status === "archived";
    const activeLocalItems = localItems.filter((item) => !isArchivedEquipment(item));
    const archivedLocalItems = localItems.filter(isArchivedEquipment);
    const activeGarminItems = items.filter((item) => item.status !== "archived");
    const archivedGarminItems = items.filter((item) => item.status === "archived");
    const bikeItems = activeLocalItems.filter((item) => isRideEquipment(item) || item.kind === "bike" || item.kind === "component");
    const runItems = activeLocalItems.filter((item) => isRunEquipment(item) || item.kind === "shoes");
    const archivedBikeItems = archivedLocalItems.filter((item) => isRideEquipment(item) || item.kind === "bike" || item.kind === "component");
    const archivedRunItems = archivedLocalItems.filter((item) => isRunEquipment(item) || item.kind === "shoes");
    const uncategorizedItems = activeLocalItems.filter((item) => !bikeItems.includes(item) && !runItems.includes(item));
    const archivedUncategorizedItems = archivedLocalItems.filter((item) => !archivedBikeItems.includes(item) && !archivedRunItems.includes(item));
    const groups = {
      bike: { label: "Fahrrad", items: bikeItems },
      run: { label: "Laufschuhe", items: runItems },
    };
    const garminBikeItems = activeGarminItems.filter((item) => /bike|cycl|component|rad/i.test(`${item.kind} ${item.name}`));
    const garminRunItems = activeGarminItems.filter((item) => /shoe|run|lauf/i.test(`${item.kind} ${item.name}`));
    const archivedGarminBikeItems = archivedGarminItems.filter((item) => /bike|cycl|component|rad/i.test(`${item.kind} ${item.name}`));
    const archivedGarminRunItems = archivedGarminItems.filter((item) => /shoe|run|lauf/i.test(`${item.kind} ${item.name}`));
    const uncategorizedGarminItems = activeGarminItems.filter((item) => !garminBikeItems.includes(item) && !garminRunItems.includes(item));
    const archivedUncategorizedGarminItems = archivedGarminItems.filter((item) => !archivedGarminBikeItems.includes(item) && !archivedGarminRunItems.includes(item));
    const garminGroups = {
      bike: garminBikeItems,
      run: garminRunItems,
    };
    const archivedGroups = {
      bike: [...archivedBikeItems.map((item) => ({ item, source: "local" })), ...archivedGarminBikeItems.map((item) => ({ item, source: "provider" }))],
      run: [...archivedRunItems.map((item) => ({ item, source: "local" })), ...archivedGarminRunItems.map((item) => ({ item, source: "provider" }))],
    };
    for (const key of ["bike", "run"]) {
      const tab = reportNode("button", groups[key].label); tab.type = "button";
      tab.id = `equipmentTab-${key}`; tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", `equipmentPanel-${key}`); tabs.append(tab);
      const panel = reportNode("div", null, "equipment-tab-panel");
      panel.id = `equipmentPanel-${key}`; panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id); panel.tabIndex = 0;
      panel.hidden = equipmentTab !== key;
      if (groups[key].items.length) {
        const local = reportNode("details", null, "training-focus-details");
        local.append(reportNode("summary", "Lokale Ausrüstung und Wartung"));
        for (const item of groups[key].items) local.append(localEquipmentCard(item));
        panel.append(local);
      }
      for (const item of garminGroups[key]) panel.append(garminEquipmentCard(item));
      if (archivedGroups[key].length) {
        const archived = reportNode("details", null, "training-focus-details equipment-archive");
        archived.append(reportNode("summary", `Archivierte Ausr\u00fcstung (${archivedGroups[key].length})`));
        for (const { item, source } of archivedGroups[key]) archived.append(source === "local" ? localEquipmentCard(item) : garminEquipmentCard(item));
        panel.append(archived);
      }
      if (!groups[key].items.length && !garminGroups[key].length && !archivedGroups[key].length) {
        panel.append(reportNode("p", key === "bike" ? "Noch keine Fahrräder oder Komponenten erfasst." : "Noch keine Laufschuhe erfasst.", "muted"));
      }
      gear.append(panel);
      tab.setAttribute("aria-selected", String(equipmentTab === key));
      tab.tabIndex = equipmentTab === key ? 0 : -1;
      tab.classList.toggle("active", equipmentTab === key);
      tab.addEventListener("click", () => { equipmentTab = key; void renderTrainingRecords(); });
      tab.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault(); equipmentTab = equipmentTab === "bike" ? "run" : "bike";
        void renderTrainingRecords().then(() => document.getElementById(`equipmentTab-${equipmentTab}`)?.focus());
      });
    }
    if (uncategorizedItems.length || uncategorizedGarminItems.length || archivedUncategorizedItems.length || archivedUncategorizedGarminItems.length) {
      const other = reportNode("section", null, "equipment-uncategorized");
      other.append(reportNode("h4", "Weitere Ausrüstung"));
      for (const item of uncategorizedItems) other.append(localEquipmentCard(item));
      for (const item of uncategorizedGarminItems) other.append(garminEquipmentCard(item));
      if (archivedUncategorizedItems.length || archivedUncategorizedGarminItems.length) {
        const archived = reportNode("details", null, "training-focus-details equipment-archive");
        const archivedItems = [
          ...archivedUncategorizedItems.map((item) => ({ item, source: "local" })),
          ...archivedUncategorizedGarminItems.map((item) => ({ item, source: "provider" })),
        ];
        archived.append(reportNode("summary", `Archivierte Ausr\u00fcstung (${archivedItems.length})`));
        for (const { item, source } of archivedItems) archived.append(source === "local" ? localEquipmentCard(item) : garminEquipmentCard(item));
        other.append(archived);
      }
      gear.append(other);
    }
    gear.prepend(tabs);
    gear.querySelectorAll("details").forEach((details) => {
      const key = `${details.closest(".equipment-tab-panel")?.id || "other"}:${details.querySelector("summary")?.textContent || ""}`;
      details.open = openDetails.has(key);
    });
    if (equipment.garmin_synced_at) gear.append(reportNode("p", `Garmin \u00b7 Stand ${new Date(equipment.garmin_synced_at).toLocaleString("de-DE")}${equipment.garmin_freshness === "stale" ? " \u00b7 letzter erfolgreicher Abruf" : ""}`, "muted"));
  } catch (error) {
    if (generation === trainingRecordsGeneration && session === state.sessionGeneration) {
      if (!rendered()) gear.replaceChildren(heading(), createErrorState(error?.message, () => void renderTrainingRecords()));
    }
  }
}

// Containers whose data decides whether a segment shows its one empty card (#1783). A container
// without a marker, still loading or failed counts as not empty; period controls stay visible.
// A container shared by both sports names the marker of the sport's part (#2265).
const ANALYSIS_SEGMENT_CONTENT = {
  running: [["currentPerformance", "analysisEmptyRunning"], ["analysisHistoryCharts", "analysisEmptyRunning"], ["performancePredictions"], ["runningBestEfforts"]],
  cycling: [["currentPerformance", "analysisEmptyCycling"], ["analysisHistoryCharts", "analysisEmptyCycling"], ["cyclingPowerProfile"]],
  load: [["sessionPerformance"], ["analysisLoadCharts"], ["trainingZoneCharts"], ["performanceEnduranceCharts"]],
  recovery: [["personalRecovery"]],
};
const ANALYSIS_EMPTY_TITLES = { running: "Noch keine Laufdaten", cycling: "Noch keine Raddaten", load: "Noch keine Belastungsdaten", recovery: "Noch keine Erholungsdaten" };
const ANALYSIS_SEGMENT_LABELS = { running: "Laufen", cycling: "Radfahren", load: "Belastung", recovery: "Erholung" };
const ANALYSIS_SEGMENT_SPORTS = { running: "run", cycling: "ride" };

function analysisSegmentEmpty(segment) {
  return ANALYSIS_SEGMENT_CONTENT[segment].every(([id, marker = "analysisEmpty"]) => document.getElementById(id)?.dataset[marker] === "true");
}

function analysisDataSourceConnected(data = state.data) {
  return Boolean(data?.garmin?.configured || data?.wahoo?.connected);
}

function analysisSegmentPeriod(segment) {
  if (segment === "load") return analysisHistoryPeriod;
  return segment === "recovery" ? recoveryHistoryPeriod : null;
}

function analysisEmptyCard(segment) {
  let action;
  let cause;
  const connected = analysisDataSourceConnected();
  if (connected && analysisSegmentPeriod(segment) === "fortnight") {
    // Data may exist outside the short window, so the one action widens the period.
    cause = "Keine Daten in den letzten 14 Tagen.";
    action = reportNode("button", "12 Wochen anzeigen", "push-button");
    action.type = "button";
    action.addEventListener("click", () => {
      const controls = document.querySelectorAll(segment === "load" ? "#analysisLoadPeriod button" : "#personalRecovery .analysis-period-controls button");
      [...controls].find((button) => button.textContent === "12 Wochen")?.click();
    });
  } else if (connected) {
    cause = "Noch keine Daten abgeglichen.";
    action = reportNode("button", "Jetzt abgleichen", "push-button");
    action.type = "button";
    action.addEventListener("click", () => void analysisRefresh());
  } else {
    cause = "Garmin oder Wahoo ist nicht verbunden.";
    action = reportNode("a", "Anbindung einrichten", "push-button");
    action.href = "#more/connections";
  }
  return createEmptyState(ANALYSIS_EMPTY_TITLES[segment], cause, action);
}

function renderAnalysisEmptyState(segment) {
  const root = document.getElementById("analysisEmptyState");
  const empty = analysisSegmentEmpty(segment);
  const key = empty ? `${segment}:${analysisDataSourceConnected()}:${analysisSegmentPeriod(segment)}` : "";
  if (root.dataset.segment !== key) {
    root.dataset.segment = key;
    root.replaceChildren(...(empty ? [analysisEmptyCard(segment)] : []));
  }
  root.hidden = !empty;
  return empty;
}

function renderAnalysisSegmentsIfActive() {
  if (String(state.route || "").startsWith("analysis")) renderAnalysisSegments(state.route);
}

function renderAnalysisSegments(route = state.route) {
  const segment = { "analysis/load": "load", "analysis/recovery": "recovery", "analysis/cycling": "cycling" }[route] || "running";
  const empty = renderAnalysisEmptyState(segment);
  document.getElementById("analysisRefreshButton").setAttribute("aria-label", `Analyse aktualisieren: ${ANALYSIS_SEGMENT_LABELS[segment]}`);
  const sport = empty ? null : ANALYSIS_SEGMENT_SPORTS[segment];
  const load = segment === "load" && !empty;
  document.getElementById("analysisHistoryCharts").hidden = !sport;
  document.getElementById("currentPerformance").hidden = !sport;
  // Laufen and Radfahren share the containers; each part names its sport.
  document.querySelectorAll("#dataPanel [data-analysis-sport]").forEach((part) => { part.hidden = part.dataset.analysisSport !== sport || !part.hasChildNodes(); });
  const endurance = document.getElementById("performanceEnduranceCharts");
  endurance.hidden = !load || !endurance.childElementCount;
  document.getElementById("analysisLoadPeriod").hidden = segment !== "load";
  document.getElementById("sessionPerformance").hidden = !load;
  document.getElementById("trainingZoneCharts").hidden = !load;
  document.getElementById("analysisLoadCharts").hidden = !load;
  document.getElementById("personalRecovery").hidden = segment !== "recovery";
  document.querySelectorAll("[data-analysis-segment]").forEach((link) => {
    const active = link.dataset.analysisSegment === segment;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
}

const analysisRefresh = AppViewRefresh.create({
  api,
  waitForJob: (...args) => waitForSyncJob(...args),
  getRoute: () => state.route,
  getRequest: (route) => {
    // Laufen and Radfahren read the same performance values.
    const area = { running: "performance", cycling: "performance" }[route.split("/")[1]] || route.split("/")[1] || "performance";
    const days = analysisRefreshDays(area);
    return { path: "/api/analysis/refresh", body: { area, ...(days ? { days } : {}) } };
  },
  getViewKey: analysisRefreshViewKey,
  reload: async (route) => {
    const result = await api("/api/performance");
    if (state.route !== route || !state.data) return;
    state.data.performance = result.performance || result;
    const performance = state.data.performance;
    clearAnalysisReportCache();
    if (route === "analysis/recovery") renderPersonalRecovery(performance.personal_recovery);
    else {
      renderAnalysisHistory(performance.history);
      if (route === "analysis/load") renderTrainingFocus(performance.training_focus_periods?.[analysisHistoryPeriod] || performance.training_focus);
      else {
        renderPerformance(performance, { refreshCharts: false });
        // The cleared report cache is read again for the power profile and the running best efforts.
        void renderCyclingPowerProfile();
      }
    }
  },
  button: document.getElementById("analysisRefreshButton"),
  status: document.getElementById("analysisRefreshStatus"),
});

function analysisRefreshDays(area) {
  if (area === "load") return analysisHistoryPeriod === "fortnight" ? 14 : 84;
  if (area === "recovery") return recoveryHistoryPeriod === "fortnight" ? 14 : 84;
  return null;
}

function analysisRefreshViewKey(route) {
  if (route === "analysis/load") return analysisHistoryPeriod;
  if (route === "analysis/recovery") return recoveryHistoryPeriod;
  return null;
}
document.getElementById("analysisRefreshButton").addEventListener("click", () => void analysisRefresh());

function selectedRecoveryBaselines(report) {
  const preferred = report?.preferred_providers || {};
  return ["sleep", "hrv", "resting_hr"].flatMap((metric) => {
    const candidates = (report?.baselines || []).filter((item) => item.metric === metric);
    candidates.sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at))
      || Number(isPreferredSource(b, preferred[metric])) - Number(isPreferredSource(a, preferred[metric]))
      || b.history.length - a.history.length);
    return candidates.slice(0, 1);
  });
}

function recoveryReferenceLabel(item, range, target, unit, position) {
  if (range) {
    const provisional = item.status === "provisional" ? " · vorläufig" : "";
    return `${position || "Bereich deiner früheren Werte"} · ${analysisValue(range.lower, unit)}–${analysisValue(range.upper, unit)}${provisional}`;
  }
  if (target != null) return `Persönliches Schlafziel: ${analysisValue(target, unit)}`;
  return item.reason || "Noch kein Vergleich verfügbar";
}

// M2 rolling-lnrmssd-v1 (#1772): seven-day mean of ln(RMSSD), back-transformed to ms.
// The caller ends the note with a full stop, so a reason drops its own.
function recoveryRollingNote(rolling) {
  if (!["ok", "provisional"].includes(rolling.status)) return `7-Tage-Mittel: ${String(rolling.reason || "kein Vergleich").replace(/\.$/, "")}`;
  const position = { below: "unter", within: "in", above: "über" }[rolling.position] || "neben";
  const range = `${analysisValue(rolling.lower_ms, "ms")}–${analysisValue(rolling.upper_ms, "ms")}`;
  const spread = rolling.cv_pct == null ? "" : ` · Schwankung ${analysisValue(rolling.cv_pct, "%")}`;
  const provisional = rolling.status === "provisional" ? " · vorläufig" : "";
  return `7-Tage-Mittel ${analysisValue(rolling.mean_ms, "ms")} (${rolling.window_nights} Nächte) · ${position} deinem Bereich ${range}${spread}${provisional}`;
}

function renderRecoveryCharts(report, root) {
  const metrics = [["sleep", "Schlafdauer", "h", 0], ["hrv", "HRV", "ms", 2], ["resting_hr", "Ruhepuls", "bpm", 3]];
  const baselines = selectedRecoveryBaselines(report);
  const today = report?.as_of || timezoneDateKey(state.data?.profile?.timezone, new Date());
  const dayCount = recoveryHistoryPeriod === "twelveWeeks" ? 84 : 14;
  const dates = Array.from({ length: dayCount }, (_, index) => addDateKey(today, index - dayCount + 1));
  const start = dates[0], end = today;
  const series = metrics.map(([metric, title, unit, color]) => {
    const item = baselines.find((candidate) => candidate.metric === metric);
    if (!item) return { label: title, legendLabel: title, unit, color, points: dates.map((date) => ({ date, value: null })) };
    const values = new Map(item.history.filter((point) => point.date <= today).map((point) => [point.date, point.value]));
    const points = recoveryHistoryPeriod === "twelveWeeks"
      ? Array.from({ length: 12 }, (_, weekIndex) => {
        const offset = weekIndex * 7;
        const weekDates = dates.slice(offset, offset + 7);
        const weekValues = weekDates.map((date) => values.get(date)).filter((value) => Number.isFinite(Number(value))).map(Number);
        return { date: weekDates.at(-1), value: weekValues.length ? weekValues.reduce((sum, value) => sum + value, 0) / weekValues.length : null };
      })
      : dates.map((date) => ({ date, value: values.get(date) ?? null }));
    const readings = item.history.filter((point) => point.date >= start && point.date <= today);
    const expectedDays = Math.max(0, Math.round((Date.parse(today) - Date.parse(start)) / 86400000) + 1);
    const range = metric !== "sleep" && ["ok", "provisional"].includes(item.status) && Number.isFinite(item.lower) && Number.isFinite(item.upper) ? { lower: item.lower, upper: item.upper, status: item.status } : null;
    const target = null;
    const position = { below: "Unter dem Bereich deiner früheren Werte", within: "Im Bereich deiner früheren Werte", above: "Über dem Bereich deiner früheren Werte" }[item.position];
    const measurement = metric === "hrv" ? " · " + item.measurement : "";
    const rangeDescription = range ? " Vergleich mit " + item.nights + " früheren Nächten." : "";
    const changed = item.context_changed_on ? ` Messkontext geändert am ${dateLabel(item.context_changed_on)}.` : "";
    const continuity = `${changed}${item.continuity === "unknown" ? " Messkontext unbekannt." : ""}`;
    const rolling = item.rolling ? ` ${recoveryRollingNote(item.rolling)}.` : "";
    return { label: `${title} · ${item.source}${measurement}`, legendLabel: title, source: item.source, unit, color,
      bars: metric === "sleep", average: true, averageInHeading: true, cadenceDays: recoveryHistoryPeriod === "twelveWeeks" ? 7 : 1, range, target,
      currentPoint: points.some(analysisValidPoint) ? null : item.history.findLast((point) => point.date <= today && analysisValidPoint(point)),
      referenceLabel: metric === "sleep" ? "Durchschnitt der angezeigten Werte" : recoveryReferenceLabel(item, range, target, unit, position),
      coverageShort: analysisCoverageText(readings.length, expectedDays, "Tagen"),
      coverage: `${analysisCoverageText(readings.length, expectedDays, "Tagen")}${rangeDescription}${continuity}${rolling}`, points };
  });
  const missing = [];
  const charts = series.map((item) => {
    const values = item.points.filter(analysisValidPoint).map((point) => Number(point.value));
    const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    const title = average == null ? item.legendLabel : `${item.legendLabel} · Ø ${analysisValue(average, item.unit)}`;
    return collectAnalysisChart(missing, title, [item], item.unit, start, end, "", { compactInfo: true, includeCoverage: false, showLegend: false });
  }).filter(Boolean);
  const readiness = state.data?.performance?.history?.provider_metrics?.training_readiness_history;
  if (readiness) {
    const readinessCharts = document.createDocumentFragment();
    renderProviderMetrics({ training_readiness_history: readiness }, readinessCharts, start, end, missing);
    charts.unshift(...readinessCharts.children);
  }
  root.append(analysisPeriodControls("Zeitraum für Erholung", recoveryHistoryPeriod, (period) => { recoveryHistoryPeriod = period; renderPersonalRecovery(report); }));
  root.dataset.analysisEmpty = String(!charts.length);
  if (!charts.length) return;
  const group = analysisChartGroup(`Erholung · ${recoveryHistoryPeriod === "twelveWeeks" ? "Letzte 12 Wochen" : "Letzte 14 Tage"}`, charts, series);
  root.append(group);
}

function renderPersonalRecovery(report) {
  const root = document.getElementById("personalRecovery");
  root.replaceChildren();
  renderRecoveryCharts(report, root);
  renderAnalysisSegments(state.route);
}

function reportNode(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function trainingFocusPeriodLabel(report) {
  const days = Math.round((Date.parse(report.end) - Date.parse(report.start)) / 86400000) + 1;
  return { 14: "Letzte 14 Tage", 84: "Letzte 12 Wochen" }[days] || `Letzte ${days} Tage`;
}

function renderTrainingFocus(report) {
  const root = document.getElementById("sessionPerformance");
  const zones = document.getElementById("trainingZoneCharts");
  zones.replaceChildren();
  root.replaceChildren(reportNode("h3", "Trainingsfokus"));
  // Unclassified sessions keep the card, which explains why they are not counted.
  root.dataset.analysisEmpty = String(!report?.classified_sessions && !report?.unclassified_sessions);
  zones.dataset.analysisEmpty = "true";
  if (!report) { root.append(reportNode("p", "Noch keine Trainingsdaten vorhanden.", "muted")); renderAnalysisSegmentsIfActive(); return; }

  const categories = [["low_aerobic", "Leicht aerob"], ["high_aerobic", "Hoch aerob"], ["anaerobic", "Anaerob"]];
  const info = reportNode("button", "i", "analysis-legend-info analysis-info-icon");
  info.type = "button"; info.setAttribute("aria-label", "Trainingsfokus: Informationen");
  const explanation = reportNode("div", `${trainingFocusPeriodLabel(report)}: ${dateLabel(report.start)} bis ${dateLabel(report.end)}. ${report.coverage?.known_sessions ?? 0} erfasste Garmin-Einheiten im Zeitraum${report.coverage?.observed_start && report.coverage?.observed_end ? ` · erfasste Daten ${dateLabel(report.coverage.observed_start)} bis ${dateLabel(report.coverage.observed_end)}` : ""}. Garmin: aufgezeichnete Belastung nach der Hauptwirkung der Einheit (Training Effect). Keine aus Zonen abgeleitete Einteilung und nicht Garmins separat berechnete Load-Focus-Metrik. ${report.unclassified_sessions || 0} Einheiten ohne bekannte Wirkung oder Belastung bleiben ausgeschlossen.`, "analysis-info-tooltip"); // NOSONAR
  explanation.id = `focus-info-${++analysisInfoId}`;
  bindAnalysisPopover(info, explanation); root.firstChild.append(info); root.append(explanation);
  appendTrainingFocusShare(report, categories, root);
  appendTrainingFocusZones(report, zones);
  zones.dataset.analysisEmpty = String(!zones.childElementCount);
  renderAnalysisSegmentsIfActive();
}

function localEquipmentCard(item) {
  const card = reportNode("section", null, "garmin-equipment-card");
  const usage = item.usage || {};
  card.append(reportNode("h4", item.name));
  card.append(reportNode("p", [KIND_LABELS[item.kind] || item.kind, item.sport_pending ? "Sportart offen" : equipmentSportLabel(item), item.parent_pending ? "Fahrrad offen" : "", item.status === "archived" ? "ausgemustert" : "aktiv"].filter(Boolean).join(" \u00b7 ")));
  card.append(reportNode("p", `${analysisValue(usage.distance_km, "km")} \u00b7 ${analysisValue(usage.hours, "h")} \u00b7 ${analysisCountLabel(usage.assigned_sessions, "zugeordnete Einheit", "zugeordnete Einheiten")}`));
  const garminStatus = String(item.garmin_status || "").trim();
  if (garminStatus && normalizeEquipmentStatus(garminStatus) !== item.status) {
    card.append(reportNode("p", `Statuskonflikt \u00b7 Coach: ${item.status === "archived" ? "archiviert" : "aktiv"} \u00b7 Garmin: ${garminStatus}`, "muted"));
  }
  appendEquipmentLifetime(card, item.lifetime, usage.distance_km, item.lifetime_target_km);
  if (Number.isFinite(Number(usage.maintenance_distance_km ?? Number.NaN)) || Number.isFinite(Number(usage.maintenance_hours ?? Number.NaN))) {
    card.append(reportNode("p", `Seit letzter Wartung: ${analysisValue(usage.maintenance_distance_km, "km")} \u00b7 ${analysisValue(usage.maintenance_hours, "h")}`));
  }
  const status = new Map([[true, "Wartung f\u00e4llig"], [false, "Wartung nicht f\u00e4llig"]]);
  card.append(reportNode("p", status.get(usage.maintenance_due) || "Wartungsstand unklar"));
  if (usage.maintenance_coverage === "partial") card.append(reportNode("p", "Nutzung unvollst\u00e4ndig bekannt.", "muted"));
  const history = reportNode("ul");
  for (const event of item.maintenance || []) history.append(reportNode("li", `${dateLabel(event.date)} \u00b7 ${event.notes || "Wartung erfasst"}`));
  if (history.childElementCount) card.append(history);
  else card.append(reportNode("p", "Keine Wartung erfasst.", "muted"));
  if (item.status !== "archived") card.append(maintenanceButton(item));
  return card;
}

function maintenanceButton(item) {
  const button = reportNode("button", "Wartung erledigt", "secondary-button");
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const result = await api("/api/equipment/maintenance", { method: "POST", body: JSON.stringify({ equipment_id: item.id, date: timezoneDateKey(state.data?.profile?.timezone, new Date()) }) });
      // Maintenance does not advance state_versions, so drop the cached response even if the athlete has left the route.
      invalidateAnalysisReport("/api/analysis/training-records");
      await renderTrainingRecords();
      showMaintenanceReceipt(result?.change);
    } catch (error) {
      button.disabled = false;
      if (!isSessionEndedError(error)) button.textContent = error.message || "Wartung fehlgeschlagen";
    }
  });
  return button;
}

function showMaintenanceReceipt(change, message = "Wartung erfasst. ") {
  const status = reportNode("p", message);
  status.setAttribute("role", "status");
  document.getElementById("equipmentItems")?.querySelector("h3")?.after(status);
  if (!change?.id) return;
  const undo = reportNode("button", "Rückgängig", "message-undo");
  undo.type = "button";
  undo.addEventListener("click", async () => {
    undo.disabled = true;
    try {
      await api("/api/change-history/undo", { method: "POST", body: JSON.stringify({ change_id: change.id, expected_current_hash: change.after_hash }) });
      invalidateAnalysisReport("/api/analysis/training-records");
      await renderTrainingRecords();
      showMaintenanceReceipt(null, "Zurückgenommen.");
    } catch (error) {
      undo.disabled = false;
      status.firstChild.textContent = `${error.message} `;
    }
  });
  status.append(undo);
}

function garminEquipmentCard(item) {
  const card = reportNode("section", null, "garmin-equipment-card");
  card.append(reportNode("h4", item.name));
  card.append(reportNode("p", [KIND_LABELS[item.kind] || item.kind, item.garmin_status || "Unbekannter Garmin-Status"].filter(Boolean).join(" \u00b7 ")));
  if (item.sessions != null) card.append(reportNode("p", `${analysisCountLabel(item.sessions, "Einheit", "Einheiten")}`));
  appendEquipmentLifetime(card, item.lifetime, item.distance_km, item.goal_km);
  return card;
}

function normalizeEquipmentStatus(value) {
  return /retir|archiv|inactive|inaktiv|ausgemustert/i.test(value || "") ? "archived" : "active";
}

function appendEquipmentLifetime(card, lifetime, usageKm, targetKm) {
  const usage = lifetime?.usage_km ?? usageKm;
  const target = lifetime?.target_km ?? targetKm;
  if (!Number.isFinite(usage) || usage < 0) {
    card.append(reportNode("p", Number.isFinite(target) && target > 0
      ? `Nutzung unbekannt \u00b7 Ziel ${analysisValue(target, "km")}`
      : "Nutzung und Lebensdauerziel unbekannt", "muted"));
    return;
  }
  if (!Number.isFinite(target) || target <= 0) {
    card.append(reportNode("p", `${analysisValue(usage, "km")} Nutzung \u00b7 Lebensdauerziel unbekannt`, "muted"));
    return;
  }
  const percent = Number.isFinite(lifetime?.percent) ? lifetime.percent : Math.round(usage / target * 1000) / 10;
  const progress = reportNode("progress");
  progress.max = 100;
  progress.value = Math.min(100, Math.max(0, Number.isFinite(lifetime?.progress_percent) ? lifetime.progress_percent : percent));
  const overage = percent > 100;
  progress.setAttribute("aria-label", `${card.querySelector("h4")?.textContent || "Ausr\u00fcstung"}: ${analysisPercent(percent)} Lebensdauer${overage ? ", Ziel \u00fcberschritten" : ""}`);
  card.append(progress, reportNode("p", `${analysisValue(usage, "km")} von ${analysisValue(target, "km")} \u00b7 ${analysisPercent(percent)}${overage ? " \u00b7 Ziel \u00fcberschritten" : ""}`));
}

function analysisWeeklyPerformancePoints(points, start, end, median = false) {
  const weeks = [];
  for (let weekStart = start; weekStart <= end; weekStart = addDateKey(weekStart, 7)) {
    let weekEnd = addDateKey(weekStart, 6);
    if (weekEnd > end) weekEnd = end;
    const readings = points.filter((point) => point.date >= weekStart && point.date <= weekEnd && analysisValidPoint(point)).sort((a, b) => a.date.localeCompare(b.date));
    if (!readings.length) { weeks.push({ date: weekEnd, value: null }); continue; }
    const latest = readings.at(-1);
    const values = readings.map((point) => Number(point.value)).sort((a, b) => a - b);
    const middle = Math.floor(values.length / 2);
    let value = latest.value;
    if (median) value = values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
    weeks.push({ date: weekEnd, value, observedDate: latest.date, ...(median ? { count: readings.length } : {}) });
  }
  return weeks;
}

function analysisWeeklySumPoints(points, start, end) {
  const weeks = [];
  for (let weekStart = start; weekStart <= end; weekStart = addDateKey(weekStart, 7)) {
    let weekEnd = addDateKey(weekStart, 6);
    if (weekEnd > end) weekEnd = end;
    const known = points.filter((point) => point.date >= weekStart && point.date <= weekEnd && analysisValidPoint(point));
    weeks.push(known.length ? { date: weekEnd, value: Math.round(known.reduce((sum, point) => sum + Number(point.value), 0) * 10) / 10, observedDate: known.at(-1).date } : { date: weekEnd, value: null });
  }
  return weeks;
}

function analysisWeeklyMeanPoints(points, start, end) {
  const weeks = [];
  for (let weekStart = start; weekStart <= end; weekStart = addDateKey(weekStart, 7)) {
    let weekEnd = addDateKey(weekStart, 6);
    if (weekEnd > end) weekEnd = end;
    const known = points.filter((point) => point.date >= weekStart && point.date <= weekEnd && analysisValidPoint(point));
    weeks.push(known.length ? { date: weekEnd, value: Math.round(known.reduce((sum, point) => sum + Number(point.value), 0) / known.length * 10) / 10, observedDate: known.at(-1).date } : { date: weekEnd, value: null });
  }
  return weeks;
}

function analysisWeeklyLastPoints(points, start, end) {
  const weeks = [];
  for (let weekStart = start; weekStart <= end; weekStart = addDateKey(weekStart, 7)) {
    let weekEnd = addDateKey(weekStart, 6);
    if (weekEnd > end) weekEnd = end;
    const last = points.findLast((point) => point.date >= weekStart && point.date <= weekEnd && analysisValidPoint(point));
    weeks.push(last ? { ...last, date: weekEnd, observedDate: last.date } : { date: weekEnd, value: null });
  }
  return weeks;
}

function trainingFocusDistribution(title, readings, unit, info) {
  const section = reportNode("section", null, "analysis-chart-card training-focus-distribution");
  const heading = reportNode("h4", title);
  const help = reportNode("button", "i", "analysis-legend-info analysis-info-icon");
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

function trainingFocusZoneSeconds(items) {
  const seconds = new Map();
  for (const item of items) for (const [zone, value] of Object.entries(item.seconds)) seconds.set(zone, (seconds.get(zone) || 0) + value);
  // Highest zone on top, as in the session detail (#1782).
  return [...seconds.entries()].sort(([a], [b]) => Number(b.slice(1)) - Number(a.slice(1))).map(([label, value]) => ({label, value}));
}

function trainingFocusZoneInfo(report, model, items) {
  const period = trainingFocusPeriodLabel(report).toLowerCase();
  const source = [...new Set(items.map((item) => item.source).filter(Boolean))].join(", ");
  // Each zone model is summed on its own (#1743); a session can appear for HF and power.
  const basis = model === "provider" ? "Zonen des Geräts, für Einheiten ohne lokale Zonenzeiten" : "Lokale Zonen am Tag der Einheit, aus den Streams gezählt";
  return `${basis} (${period}). Quelle: ${source || "unbekannt"}.`;
}

function appendTrainingFocusZones(report, details) {
  const zones = report.zones || [];
  for (const sensor of ["heart_rate", "power"]) {
    const name = sensor === "heart_rate" ? "HF-Zonen" : "Power-Zonen";
    const matching = zones.filter((item) => item.sensor === sensor);
    if (!matching.some((item) => item.measured_seconds > 0)) continue;
    for (const model of ["local", "provider"]) {
      const items = matching.filter((item) => (item.zone_model || "provider") === model);
      const readings = trainingFocusZoneSeconds(items);
      if (!readings.some((item) => item.value > 0)) continue;
      const title = model === "provider" ? `${name} (Gerät)` : name;
      details.append(trainingFocusDistribution(title, readings, "seconds", trainingFocusZoneInfo(report, model, items)));
    }
  }
}
