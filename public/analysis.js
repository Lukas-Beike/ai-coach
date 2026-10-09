const ANALYSIS_SVG_NS = "http://www.w3.org/2000/svg";

const KIND_LABELS = { bike: "Fahrrad", component: "Komponente", shoes: "Schuhe", other: "Sonstiges" };
const SPORT_LABELS = { Ride: "Rad", VirtualRide: "Indoor-Rad", Run: "Laufen", Swim: "Schwimmen", Walk: "Gehen" };
const SENSOR_LABELS = { power: "Leistung", heart_rate: "Herzfrequenz", pace: "Tempo" };
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
  return `${AppFormat.number(value)}${suffix}`;
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

let analysisInfoId = 0;

function analysisChart(title, series, unit, start, end, note, {
  sparse = false, zeroCentered = false, showLegend = true,
} = {}) {
  const section = reportNode("section", null, "analysis-chart-card");
  section.append(reportNode("h3", title));
  const valid = analysisValidPoint;
  const values = series.flatMap((item) => item.points.filter(valid));

  const legend = reportNode("ul", null, "analysis-chart-legend");
  series.forEach((item, index) => {
    const latest = analysisLatestPoint(item);
    const entry = reportNode("li");
    entry.dataset.color = String(item.color ?? index);
    const label = item.legendLabel || item.label;
    const button = reportNode("button", label, "analysis-legend-info");
    button.type = "button";
    const sourceInfo = item.source ? " · Quelle: " + item.source : "";
    const info = reportNode("div", `${analysisLegendText(item, latest, unit)}${sourceInfo}. ${item.explanation || note}`, "analysis-info-tooltip");
    info.dataset.series = String(index);
    info.id = `analysis-info-${++analysisInfoId}`;
    info.setAttribute("popover", "auto");
    info.setAttribute("role", "tooltip");
    button.setAttribute("popovertarget", info.id);
    button.setAttribute("aria-describedby", info.id);
    button.setAttribute("aria-expanded", "false");
    info.addEventListener("toggle", (event) => {
      button.setAttribute("aria-expanded", String(event.newState === "open"));
      if (event.newState !== "open") return;
      const rect = button.getBoundingClientRect();
      info.style.left = `${Math.max(12, Math.min(rect.left, innerWidth - info.offsetWidth - 12))}px`;
      info.style.top = `${Math.max(12, Math.min(rect.bottom + 8, innerHeight - info.offsetHeight - 12))}px`;
    });
    entry.append(button, info);
    const sourceSuffix = item.source ? " · " + item.source : "";
    if (latest) info.append(reportNode("span", `${dateLabel(latest.observedDate || latest.date)}${sourceSuffix}`, "analysis-metric-meta"));
    if (item.referenceLabel) info.append(reportNode("span", item.referenceLabel, "analysis-metric-context"));
    const readings = item.points.filter(valid);
    info.append(reportNode("span", item.coverageShort || `${readings.length}/${item.points.length} datierte Werte`, "analysis-metric-meta"));
    if (readings.length > 1) {
      const first = readings[0];
      const delta = Number(latest.value) - Number(first.value);
      const change = analysisChange(delta, item.unit || unit);
      info.append(reportNode("span", `Seit ${dateLabel(first.observedDate || first.date)}: ${change}`, "analysis-metric-change"));
    }
    legend.append(entry);
  });
  if (showLegend) section.append(legend);

  if (!series.some((item) => item.bars || item.points.filter(valid).length >= 2)) {
    section.append(reportNode("p", values.length ? "Ein einzelner Messwert zeigt noch keinen Verlauf; mindestens zwei datierte Werte sind erforderlich." : "Noch keine datierten Werte im Zeitraum vorhanden.", "empty"));
    appendAnalysisTable(section, title, series, unit);
    return section;
  }
  const fewReadings = sparse && series.every((item) => item.points.filter(valid).length < 3);
  if (fewReadings) legend.querySelectorAll(".analysis-info-tooltip").forEach((info) => info.append(reportNode("p", "Wenige Messungen · kein belastbarer Trend.", "analysis-sparse-note")));
  const scales = analysisPlotScales(series, start, end, { unit, zeroCentered });
  const svg = analysisSvg("svg", { viewBox: `0 0 ${scales.chartWidth} 200`, role: "group", "aria-label": `${title}: datierter Verlauf. Tageswerte auswählen oder Werte ansehen öffnen.` });
  svg.append(analysisSvg("title", {}, `${title} · ${dateLabel(start)} bis ${dateLabel(end)}`));
  svg.append(analysisSvg("desc", {}, `Eigene Skala in ${unit || "Belastungspunkten"}. Fehlende Messungen bleiben unbekannt.`));
  appendAnalysisAxes(svg, unit, scales);
  appendAnalysisSeries(svg, series, unit, scales, zeroCentered, sparse);
  appendAnalysisDateTicks(svg, start, end, scales);
  appendAnalysisPointInspectors(section, svg, series, unit, scales);
  section.append(svg);
  appendAnalysisReferenceNotes(section, series, unit);
  appendAnalysisTable(section, title, series, unit);
  return section;
}

function analysisChange(delta, unit) {
  if (unit === "s/km") return `${delta < 0 ? "−" : "+"}${formatPace(Math.abs(delta))}`;
  return `${delta < 0 ? "" : "+"}${analysisValue(delta, unit)}`;
}

function appendAnalysisReferenceNotes(section, series, unit) {
  series.forEach((item, index) => {
    const info = section.querySelector(`.analysis-legend-info + .analysis-info-tooltip[data-series="${index}"]`);
    if (item.points.some((point) => point.lower != null)) info?.append(reportNode("p", "Wochenmedian mit Streuung (25.–75. Perzentil) · nur vorhandene Messungen", "analysis-reference-note"));
    if (item.range) info?.append(reportNode("p", "Grüner Bereich: persönliche Quartile · 42 Tage vor der letzten Messung" + (item.range.status === "provisional" ? " · vorläufig" : ""), "analysis-reference-note"));
    if (item.target != null) info?.append(reportNode("p", `Ziellinie: ${analysisValue(item.target, item.unit || unit)} · persönliches Schlafziel`, "analysis-reference-note"));
    if (item.average && item.bars) {
      info?.append(reportNode("p", "Gestrichelte Linie: Durchschnitt der angezeigten Schlafwerte.", "analysis-reference-note"));
    }
  });
}

function analysisReadingDetails(point, unit) {
  let details = point.count ? ` · ${point.count} Messungen` : "";
  if (point.observedDate && point.observedDate !== point.date) details += ` · letzter Messwert ${dateLabel(point.observedDate)}`;
  if (point.ftp_observed_at) details += ` · ${point.power_method || "FTP"} ${dateLabel(point.ftp_observed_at)}`;
  if (point.weight_observed_at) details += ` · Gewicht ${dateLabel(point.weight_observed_at)} (${point.weight_source || "Quelle unbekannt"})`;
  if (point.lower != null) details += ` · Streuung ${analysisValue(point.lower, unit)} bis ${analysisValue(point.upper, unit)}`;
  return details;
}

function analysisValidPoint(point) {
  return point?.value != null && Number.isFinite(Number(point.value));
}

function appendAnalysisTable(section, title, series, unit) {
  const details = reportNode("details");
  details.append(reportNode("summary", "Werte ansehen"));
  const scroll = reportNode("div", null, "analysis-chart-table");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", `${title}: Einzelwerte`);
  const table = reportNode("table");
  table.append(reportNode("caption", `${title} · ${unit || "Belastungspunkte"} · nur vorhandene Werte`));
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
      if (point?.count || point?.observedDate) value += analysisReadingDetails(point, item.unit || unit);
      row.append(reportNode("td", value));
    });
    body.append(row);
  });
  table.append(body); scroll.append(table); details.append(scroll); section.append(details);
}

function analysisPlotScales(series, start, end, { unit = "", zeroCentered = false } = {}) {
  const values = series.flatMap((item) => [
    ...(item.bars || item.points.filter(analysisValidPoint).length >= 2 ? item.points.filter(analysisValidPoint) : []).flatMap((point) => [Number(point.value), point.lower, point.upper].filter((v) => v != null && Number.isFinite(Number(v))).map(Number)),
    ...(item.range ? [item.range.lower, item.range.upper] : []),
    ...(item.target != null ? [item.target] : []),
  ]);
  let low = Math.min(...values), high = Math.max(...values);
  if (zeroCentered) { const extent = Math.max(Math.abs(low), Math.abs(high), 1); low = -extent; high = extent; }
  if (series.some((item) => item.bars)) low = Math.min(0, low);
  const padding = Math.max((high - low) * .12, unit === "s/km" ? 5 : 1);
  const rawStep = (high - low + padding * 2) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  let step = [1, 2, 5, 10].find((factor) => factor * magnitude >= rawStep) * magnitude;
  if (unit === "s/km") step = Math.max(5, Math.ceil(step / 5) * 5);
  const min = series.some((item) => item.bars) ? 0 : Math.floor((low - padding) / step) * step;
  const max = Math.ceil((high + padding) / step) * step;
  const chartWidth = globalThis.innerWidth < 600 ? Math.max(220, globalThis.innerWidth - 80) : 680;
  const chartRight = chartWidth - 24;
  const x = (date) => 60 + ((Date.parse(date) - Date.parse(start)) / Math.max(86400000, Date.parse(end) - Date.parse(start))) * (chartRight - 60);
  const y = unit === "s/km" ? (value) => 30 + (Number(value) - min) / (max - min) * 130 : (value) => 160 - (Number(value) - min) / (max - min) * 130;
  return { min, max, step, chartWidth, chartRight, x, y };
}

function analysisAxisLabel(value, unit) {
  if (unit === "s/km") return formatPace(value).split(" ")[0];
  if (unit === "s") return formatDuration(Math.round(value));
  return AppFormat.number(Number(value.toFixed(3)));
}

function appendAnalysisAxes(svg, unit, { min, max, step, chartRight, y }) {
  for (let value = min; value <= max + step / 100; value += step) {
    svg.append(analysisSvg("line", { x1: 60, x2: chartRight, y1: y(value), y2: y(value), class: Math.abs(value) < step / 100 ? "analysis-zero-line" : "analysis-grid-line" }));
    const label = analysisAxisLabel(value, unit);
    svg.append(analysisSvg("text", { x: 52, y: y(value) + 4, "text-anchor": "end", class: "analysis-value-tick" }, label));
  }
  svg.append(analysisSvg("text", { x: 60, y: 15, class: "analysis-axis-unit" }, unit === "s/km" ? "min/km · schneller oben" : unit || "Belastungspunkte"));
}

function appendAnalysisReferenceLines(svg, item, index, unit, scales) {
  const { chartRight, y } = scales;
  if (item.range) svg.append(analysisSvg("rect", { x: 60, y: Math.min(y(item.range.lower), y(item.range.upper)), width: chartRight - 60, height: Math.max(1, Math.abs(y(item.range.lower) - y(item.range.upper))), class: "analysis-baseline-band" }));
  if (item.target != null) svg.append(analysisSvg("line", { x1: 60, x2: chartRight, y1: y(item.target), y2: y(item.target), class: "analysis-target-line" }));
  if (item.average) {
    const readings = item.points.filter(analysisValidPoint).map((point) => Number(point.value));
    if (readings.length) {
      const average = readings.reduce((sum, value) => sum + value, 0) / readings.length;
      const line = analysisSvg("line", { x1: 60, x2: chartRight, y1: y(average), y2: y(average), class: "analysis-average-line" });
      line.append(analysisSvg("title", {}, `${item.label}: Durchschnitt ${analysisValue(average, item.unit || unit)}`));
      svg.append(line);
      if (!item.averageInHeading) svg.append(analysisSvg("text", { x: chartRight, y: y(average) - 8, "text-anchor": "end", class: "analysis-point-value analysis-average-value", stroke: "var(--surface)", "stroke-width": 4, "paint-order": "stroke", "stroke-linejoin": "round" }, `\u00d8 ${analysisValue(average, item.unit || unit)}`));
    }
  }
}

function flushAnalysisArea(svg, segment, zeroCentered, color, x, y) {
  if (zeroCentered && segment.length > 1) svg.append(analysisSvg("path", { d: `M${x(segment[0].date)},${y(0)} ` + segment.map((point) => `L${x(point.date)},${y(point.value)}`).join(" ") + ` L${x(segment.at(-1).date)},${y(0)} Z`, class: "analysis-form-area", "data-color": color }));
}

function appendAnalysisPointMark(svg, item, point, index, unit, scales) {
  const { chartRight, x, y } = scales;
  if (point.lower != null) svg.append(analysisSvg("line", { x1: x(point.date), x2: x(point.date), y1: y(point.lower), y2: y(point.upper), class: "analysis-range-whisker", "data-color": item.color ?? index }));
  if (!item.bars) {
    const dot = analysisSvg("circle", { cx: x(point.date), cy: y(point.value), r: 2.5, "data-series": index, "data-color": item.color ?? index });
    dot.append(analysisSvg("title", {}, `${item.label} \u00b7 ${dateLabel(point.date)}: ${analysisPointValue(item, point, unit)}`));
    svg.append(dot);
    return;
  }
  const width = Math.min(24, (chartRight - 60) / Math.max(1, item.points.length) * .55);
  const left = Math.max(60, Math.min(chartRight - width, x(point.date) - width / 2));
  svg.append(analysisSvg("rect", { x: left, y: y(point.value), width, height: Math.max(0, y(0) - y(point.value)), rx: 3, class: "recovery-sleep-bar" }));
}

function analysisPointValueLabel(item, point, { pointIndex, index, unit, scales, latest, latestIndex, labelledValues }) {
  if (item.bars) return null;
  const label = analysisValue(point.value, item.unit || unit).split(" ")[0];
  if (labelledValues.has(label) || (label === latest && pointIndex !== latestIndex)) return null;
  labelledValues.add(label);
  const { chartRight, x, y } = scales;
  const pointX = x(point.date);
  let anchor = "middle";
  if (pointX <= 70) anchor = "start";
  else if (pointX >= chartRight - 10) anchor = "end";
  const width = label.length * 8 + 8;
  const pointY = y(point.value);
  const nearby = item.points.filter((other) => analysisValidPoint(other) && other !== point && Math.abs(x(other.date) - pointX) < width + 12);
  const aboveClear = pointY >= 30 && !nearby.some((other) => Math.abs(y(other.value) - pointY) < 22);
  return { label, x: pointX, y: aboveClear ? pointY - 10 : Math.min(174, pointY + 16), anchor, width, index, latest: pointIndex === latestIndex };
}

function appendAnalysisBarExtremaLabels(item, unit, index, scales, labels) {
  if (!item.bars) return;
  const values = item.points.filter(analysisValidPoint).map((point) => Number(point.value));
  if (!values.length) return;
  const { x, y } = scales;
  const extrema = [...new Set([Math.min(...values), Math.max(...values)])];
  for (const value of extrema) {
    const point = item.points.find((candidate) => analysisValidPoint(candidate) && Number(candidate.value) === value);
    if (point) {
      const width = Math.min(24, (scales.chartRight - 60) / Math.max(1, item.points.length) * .55);
      const center = Math.max(60, Math.min(scales.chartRight - width, x(point.date) - width / 2)) + width / 2;
      labels.push({ label: analysisValue(value, item.unit || unit).split(" ")[0], x: center, y: y(value) - 10, anchor: "middle", width: 50, index, latest: false, extrema: true });
    }
  }
}

function appendAnalysisSeriesPoints(svg, item, { index, unit, scales, zeroCentered, labels }) {
  const { x, y } = scales;
  const color = item.color ?? index;
  let path = "", previous = null, segment = [], hasLinePoint = false;
  const labelledValues = new Set();
  const latest = item.points.findLast(analysisValidPoint);
  const latestLabel = latest ? analysisValue(latest.value, item.unit || unit).split(" ")[0] : null;
  const latestIndex = item.points.findLastIndex(analysisValidPoint);
  if (!item.bars && item.points.filter(analysisValidPoint).length < 2) return path;
  item.points.forEach((point, pointIndex) => {
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
    appendAnalysisPointMark(svg, item, point, index, unit, scales);
    const label = analysisPointValueLabel(item, point, { pointIndex, index, unit, scales, latest: latestLabel, latestIndex, labelledValues });
    if (label) labels.push(label);
    previous = point;
  });
  flushAnalysisArea(svg, segment, zeroCentered, color, x, y);
  appendAnalysisBarExtremaLabels(item, unit, index, scales, labels);
  return path;
}

function appendAnalysisPointLabels(svg, labels) {
  const occupied = [];
  const accepted = [];
  labels.sort((a, b) => Number(b.extrema) - Number(a.extrema) || Number(b.latest) - Number(a.latest));
  labels.forEach((label) => {
    let left = label.x - label.width / 2;
    if (label.anchor === "start") left = label.x;
    else if (label.anchor === "end") left = label.x - label.width;
    const box = { left, right: left + label.width, top: label.y - 12, bottom: label.y + 3 };
    if (occupied.some((other) => box.left < other.right + 6 && box.right > other.left - 6 && box.top < other.bottom + 4 && box.bottom > other.top - 4)) {
      if (!label.extrema) return;
      label.y = Math.max(18, label.y - 18);
      box.top = label.y - 12; box.bottom = label.y + 3;
    }
    occupied.push(box);
    accepted.push(label);
  });
  accepted.sort((a, b) => a.index - b.index || a.x - b.x);
  accepted.forEach((label) => svg.append(analysisSvg("text", { x: label.x, y: label.y, "text-anchor": label.anchor, class: "analysis-point-value", "data-value-series": label.index }, label.label)));
}

function appendAnalysisSeries(svg, series, unit, scales, zeroCentered, sparse) {
  const labels = [];
  series.forEach((item, index) => {
    const color = item.color ?? index;
    appendAnalysisReferenceLines(svg, item, index, unit, scales);
    const path = appendAnalysisSeriesPoints(svg, item, { index, unit, scales, zeroCentered, labels });
    if (!item.bars && item.points.filter(analysisValidPoint).length >= 2) svg.append(analysisSvg("path", { d: path, fill: "none", "data-series": index, "data-color": color, "data-line": item.line || (index ? "dashed" : "solid") }));
  });
  appendAnalysisPointLabels(svg, labels);
}

function appendAnalysisDateTicks(svg, start, end, { chartWidth, x }) {
  const days = Math.round((Date.parse(end) - Date.parse(start)) / 86400000);
  const intervals = Math.min(Math.max(1, days), chartWidth < 600 ? 3 : 7);
  for (let index = 0; index <= intervals; index++) {
    const date = addDateKey(start, Math.round(days * index / intervals));
    let anchor = "middle";
    if (index === 0) anchor = "start";
    else if (index === intervals) anchor = "end";
    svg.append(analysisSvg("text", { x: x(date), y: 188, "text-anchor": anchor, class: "analysis-date-tick" }, date.slice(5).split("-").reverse().join(".")));
  }
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

function analysisChartGroup(title, charts, series, note) {
  const group = reportNode("section", null, "analysis-chart-card analysis-chart-stack");
  const heading = reportNode("h3", title);
  if (series?.length) {
    const help = reportNode("button", "i", "analysis-legend-info");
    help.type = "button"; help.setAttribute("aria-label", `${title}: Informationen`);
    const info = reportNode("div", null, "analysis-info-tooltip");
    info.id = `group-info-${++analysisInfoId}`; info.setAttribute("popover", "auto"); info.setAttribute("role", "tooltip");
    series.forEach((item) => {
      const details = [item.source, item.coverage, item.referenceLabel].filter(Boolean).join(" · ");
      if (details) info.append(reportNode("p", `${item.legendLabel || item.label}: ${details}`));
    });
    if (note) info.append(reportNode("p", note));
    help.setAttribute("popovertarget", info.id); heading.append(help); group.append(info);
  }
  group.append(heading);
  if (note) charts.forEach((chart) => chart.querySelectorAll(".analysis-legend-info + .analysis-info-tooltip").forEach((info) => info.append(reportNode("p", note))));
  charts.forEach((chart) => {
    chart.classList.remove("analysis-chart-card"); chart.classList.add("analysis-subchart");
    const heading = chart.querySelector("h3");
    const subheading = reportNode("h4", heading.textContent); heading.replaceWith(subheading);
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
let analysisReportGeneration = 0;

function renderExistingPerformanceReports(endurance, profiles) {
  const root = document.querySelector("#existingPerformanceReports"); root.replaceChildren();
  const bySport = new Map();
  (endurance?.activities || []).forEach((item) => {
    const efficiency = Number(item.aerobic?.efficiency);
    if (item.aerobic?.efficiency == null || !Number.isFinite(efficiency) || !item.date) return;
    const sport = String(item.sport || "Sportart unbekannt");
    if (!bySport.has(sport)) bySport.set(sport, []);
    bySport.get(sport).push({ date: String(item.date).slice(0, 10), value: efficiency, unit: item.aerobic.unit || "" });
  });
  const cards = [];
  bySport.forEach((items, sport) => {
    const points = items.sort((a, b) => a.date.localeCompare(b.date));
    if (points.length < 2 || points[0].date === points.at(-1).date) return;
    const unit = points.find((point) => point.unit)?.unit || "";
    const series = [{ label: sport, legendLabel: sport, source: "Intervals.icu", unit, color: 0, cadenceDays: 1, points: points.map(({ date, value }) => ({ date, value })), currentPoint: points.at(-1) }];
    const chart = analysisChart(`Ausdauer-Effizienz \u00b7 ${sport}`, series, unit, points[0].date, points.at(-1).date, "", { sparse: true, showLegend: false });
    chart.querySelector(".analysis-chart-legend")?.remove();
    cards.push(chart);
  });
  const order = new Map([[5, 0], [60, 1], [300, 2], [1200, 3]]);
  const best = (profiles?.best || []).filter((item) => item.watts != null).slice()
    .sort((a, b) => String(a.sport).localeCompare(String(b.sport)) || (order.get(a.duration_seconds) ?? 9) - (order.get(b.duration_seconds) ?? 9));
  if (best.length) {
    const card = reportNode("section", null, "analysis-chart-card");
    card.append(reportNode("h3", "Beste Fenster je Aktivit\u00e4t"));
    const wrap = reportNode("div", null, "analysis-chart-table");
    const table = reportNode("table"); const head = reportNode("tr");
    ["Sport", "Fenster", "Watt", "Datum"].forEach((label) => head.append(reportNode("th", label)));
    const thead = reportNode("thead"); thead.append(head); table.append(thead);
    const body = reportNode("tbody");
    best.forEach((item) => {
      const row = reportNode("tr");
      row.append(reportNode("td", item.sport || "unbekannt"), reportNode("td", item.duration_seconds < 60 ? `${item.duration_seconds} s` : `${item.duration_seconds / 60} min`), reportNode("td", `${item.watts} W`), reportNode("td", item.date ? dateLabel(item.date) : "unbekannt"));
      body.append(row);
    });
    table.append(body); wrap.append(table); card.append(wrap); cards.push(card);
  }
  if (cards.length) root.append(reportNode("h3", "Ausdauer und Bestleistungen"), ...cards);
}

// Report responses are reused per content version (state_versions) and in-flight requests are shared.
const analysisReportCache = new Map();

function analysisReportVersionKey() {
  const versions = state.data?.state_versions || {};
  return JSON.stringify(Object.keys(versions).sort().map((key) => [key, versions[key]]));
}

function requestAnalysisReport(path, { force = false } = {}) {
  const version = analysisReportVersionKey();
  const cached = analysisReportCache.get(path);
  if (!force && cached?.version === version) return cached.request;
  const request = api(path).catch((error) => {
    if (analysisReportCache.get(path)?.request === request) analysisReportCache.delete(path);
    throw error;
  });
  analysisReportCache.set(path, { version, request });
  return request;
}

function clearAnalysisReportCache() {
  analysisReportCache.clear();
}

function analysisRouteActive() {
  return AppRouter.baseRoute(state.route) === "analysis";
}

function equipmentRouteActive() {
  return state.route === "more/equipment";
}

async function loadAnalysisReports() {
  if (!state.data || !analysisRouteActive()) return;
  const generation = ++analysisReportGeneration;
  try {
    const results = await Promise.allSettled([requestAnalysisReport("/api/analysis/endurance"), requestAnalysisReport("/api/analysis/power-profiles")]);
    if (generation !== analysisReportGeneration) return;
    renderExistingPerformanceReports(results[0].status === "fulfilled" ? results[0].value : null, results[1].status === "fulfilled" ? results[1].value : null);
  } catch (_) { /* individual report failures stay scoped to their cards */ }
}

globalThis.matchMedia("(max-width: 599px)").addEventListener("change", () => {
  if (state.data) { renderAnalysisHistory(state.data.performance?.history); renderPersonalRecovery(state.data.performance?.personal_recovery); }
});

function renderAnalysisHistory(history) { // NOSONAR
  const root = document.querySelector("#analysisHistoryCharts");
  const loadRoot = document.querySelector("#analysisLoadCharts");
  renderBodyAnalysis(history?.body);
  const openDetails = new Set([...root.querySelectorAll("details[open]"), ...loadRoot.querySelectorAll("details[open]")].map((details) => `${details.closest("section")?.querySelector("h3,h4")?.textContent}:${details.querySelector("summary")?.textContent}`));
  root.replaceChildren(); loadRoot.replaceChildren();
  if (!history?.start || !history?.end) return;
  const end = history.end;
  const weekStart = addDateKey(end, -((new Date(`${end}T12:00:00Z`).getUTCDay() + 6) % 7));
  const start = analysisHistoryPeriod === "fortnight" ? addDateKey(end, -13) : addDateKey(weekStart, -77);
  loadRoot.append(analysisPeriodControls("Zeitraum für Belastung", analysisHistoryPeriod, (period) => { analysisHistoryPeriod = period; renderAnalysisHistory(history); }));
  const performanceStart = addDateKey(weekStart, -77);
  renderRacePredictionCharts(state.data?.performance?.metrics, history, root, performanceStart, end);
  const load = history.load || { points: [] };
  const loadSeries = [{ label: "Akute Belastung", legendLabel: "Akute Belastung", source: "Garmin Connect", unit: "", color: 0,
    cadenceDays: analysisHistoryPeriod === "twelveWeeks" ? 7 : 1, average: true, averageInHeading: true,
    points: analysisHistoryPeriod === "twelveWeeks" ? analysisWeeklyLastPoints(load.points.filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value })), start, end) : load.points.filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value })),
    currentPoint: load.points.filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value })).findLast(analysisValidPoint) }];
  const loadValues = loadSeries[0].points.filter(analysisValidPoint).map((point) => Number(point.value));
  const loadAverage = loadValues.length ? loadValues.reduce((sum, value) => sum + value, 0) / loadValues.length : null;
  const loadTitle = loadAverage == null ? "Akute Belastung" : `Akute Belastung \u00b7 \u00d8 ${analysisValue(loadAverage, "")}`;
  const loadChart = analysisChart(loadTitle, loadSeries, "", start, end, "Garmin Connect: gemessene akute Trainingsbelastung. Gestrichelte Linie: Durchschnitt der angezeigten Werte. Fehlende Messungen bleiben L\u00fccken.");
  loadChart.querySelector(".analysis-chart-legend")?.remove();
  loadRoot.append(loadChart);
  const timePoints = (history.training_time?.points || []).filter((point) => point.date >= start && point.date <= end).map((point) => ({ date: point.date, value: point.value }));
  if (timePoints.some(analysisValidPoint)) {
    const weekly = analysisHistoryPeriod === "twelveWeeks";
    const timeSeries = [{ label: weekly ? "Trainingszeit pro Woche" : "Trainingszeit pro Tag", legendLabel: "Trainingszeit", source: history.training_time.source || "Intervals.icu", unit: "h", color: 1, cadenceDays: weekly ? 7 : 1, average: true, averageInHeading: true, points: weekly ? analysisWeeklySumPoints(timePoints, start, end) : timePoints }];
    const timeValues = timeSeries[0].points.filter(analysisValidPoint).map((point) => Number(point.value));
    const timeAverage = timeValues.reduce((sum, value) => sum + value, 0) / timeValues.length;
    const timeChart = analysisChart(`Trainingszeit \u00b7 \u00d8 ${analysisValue(timeAverage, "h")}${weekly ? " pro Woche" : " pro Tag"}`, timeSeries, "h", start, end, "Intervals.icu: Summe der Bewegungszeit erfasster Aktivit\u00e4ten, jede Aktivit\u00e4t einmal. Tage und Wochen ohne erfasste Dauer bleiben L\u00fccken.");
    timeChart.querySelector(".analysis-chart-legend")?.remove();
    loadRoot.append(timeChart);
  }
  const performanceSeries = [
    ["cycling_ftp_watts", "Rad · FTP", "W", 0],
    ["cycling_eftp_watts", "Rad · eFTP", "W", 1],
    ["run_threshold_pace_seconds_per_km", "Lauf · Schwellenpace", "s/km", 2],
    ["cycling_vo2max_ml_kg_min", "Rad · VO₂max", "ml/kg/min", 3],
    ["running_vo2max_ml_kg_min", "Lauf · VO₂max", "ml/kg/min", 4],
  ].flatMap(([key, label, unit, color]) => (history.metrics?.[key] || []).filter((item) => item.source === (key === "cycling_eftp_watts" ? "Intervals.icu" : "Garmin Connect")).map((item) => ({
    label: `${label} · ${item.source}`, legendLabel: label.replace(/^Rad \u00b7 /, ""), source: item.source, unit, color,
    line: key === "cycling_eftp_watts" || key.includes("vo2max") ? "dashed" : "solid",
    cadenceDays: 7,
    explanation: key === "cycling_eftp_watts" || key.includes("vo2max") ? "Wochenmedian aus vorhandenen Messungen." : "Letzter gültiger Messwert je Woche.",
    currentPoint: item.points.filter((point) => point.date <= end).findLast(analysisValidPoint),
    points: analysisWeeklyPerformancePoints(item.points, performanceStart, end, key === "cycling_eftp_watts" || key.includes("vo2max")),
  })));
  for (const [sport, title, primaryUnit] of [["Lauf", "Laufen", "s/km"], ["Rad", "Rad", "W"]]) {
    const sportSeries = performanceSeries.filter((item) => item.label.startsWith(sport));
    const charts = [[primaryUnit, primaryUnit === "W" ? "Leistungsschwelle · FTP / eFTP" : "Schwellenpace"], ["ml/kg/min", "VO₂max · Schätzung"]].map(([unit, metric]) => analysisChart(metric, sportSeries.filter((item) => item.unit === unit), unit, performanceStart, end, "", { compactInfo: true, sparse: true, includeCoverage: false, showLegend: unit === "W" }));
    root.append(analysisChartGroup(`Leistungsentwicklung · ${title}`, charts, sportSeries, "Letzte 12 Kalenderwochen einschließlich der laufenden Woche: letzter gültiger Wochenwert für FTP und Schwellenpace, Wochenmedian für eFTP und VO₂max. Jede Woche mit Messung bleibt als Punkt sichtbar; fehlende Wochen bleiben Lücken. Garmin; nur eFTP: Intervals.icu. VO₂max und eFTP sind Schätzungen. Quellen und Messdatum bleiben sichtbar."));
  }
  renderProviderMetrics(history.provider_metrics, root, performanceStart, end);
  for (const target of [root, loadRoot]) target.querySelectorAll("details").forEach((details) => { details.open = openDetails.has(`${details.closest("section")?.querySelector("h3,h4")?.textContent}:${details.querySelector("summary")?.textContent}`); });
}

// The backend reports these metrics with source "Garmin Connect" and labels them in `note`.
const RACE_PREDICTION_SOURCE = "Garmin Connect Laufprognose";
const racePredictionSeries = [
  ["run_5k_seconds", "5 km"],
  ["run_10k_seconds", "10 km"],
  ["run_half_marathon_seconds", "Halbmarathon"],
  ["run_marathon_seconds", "Marathon"],
];

function renderRacePredictionCharts(metrics, history, root, start, end) {
  const predictions = racePredictionSeries.map(([key, label]) => {
    const metric = metrics?.[key];
    const value = Number(metric?.value);
    return [metric?.source, metric?.note].includes(RACE_PREDICTION_SOURCE) && Number.isFinite(value) && value > 0 && value <= 86400
      ? { key, label, value, source: RACE_PREDICTION_SOURCE }
      : null;
  }).filter(Boolean);
  const historical = racePredictionSeries.flatMap(([key, label], index) => {
    const series = history.metrics?.[key] || [];
    return series.filter((item) => item.source === "Garmin Connect" && item.points.filter(analysisValidPoint).length >= 2).map((item) => ({
      label,
      source: item.source,
      unit: "s",
      color: index,
      line: index ? "dashed" : "solid",
      cadenceDays: 7,
      points: analysisWeeklyPerformancePoints(item.points, start, end, false),
      currentPoint: item.points.filter((point) => point.date <= end).findLast(analysisValidPoint),
    }));
  });
  if (!predictions.length && !historical.length) return;

  const section = reportNode("section", null, "analysis-chart-card");
  section.append(reportNode("h3", "Laufprognosen · geschätzte Zeiten"));
  if (predictions.length) {
    const chartWidth = globalThis.innerWidth < 600 ? Math.max(260, globalThis.innerWidth - 48) : 680;
    const left = 120, right = chartWidth - 68, rowHeight = 34, top = 28;
    const maxSeconds = Math.max(...predictions.map((item) => item.value));
    const svg = analysisSvg("svg", { viewBox: `0 0 ${chartWidth} ${top + predictions.length * rowHeight + 12}`, role: "img", "aria-label": "Garmin Connect Laufprognosen nach Distanz" });
    svg.append(analysisSvg("title", {}, "Geschätzte Laufzeiten nach Distanz"));
    svg.append(analysisSvg("desc", {}, "Aktuelle Garmin Connect Laufprognosen; Balkenlänge entspricht der geschätzten Zeit."));
    predictions.forEach((item, index) => {
      const y = top + index * rowHeight;
      const width = (right - left) * item.value / maxSeconds;
      svg.append(analysisSvg("text", { x: left - 8, y: y + 14, "text-anchor": "end", class: "analysis-date-tick" }, item.label));
      svg.append(analysisSvg("rect", { x: left, y, width, height: 20, rx: 3, class: "recovery-sleep-bar", "data-race-distance": item.key }));
      svg.append(analysisSvg("text", { x: Math.min(right + 56, left + width + 6), y: y + 15, class: "analysis-point-value" }, formatDuration(Math.round(item.value))));
    });
    section.append(svg, reportNode("p", `Quelle: ${predictions[0].source}. Alle Zeiten sind Schätzungen.`, "analysis-metric-meta"));
  }
  if (predictions.length && !historical.length) {
    section.append(reportNode("p", "Noch keine historische Entwicklung der Laufprognosen verfügbar.", "empty"));
  }
  if (historical.length) {
    section.append(reportNode("h4", "Historische Entwicklung"));
    for (const item of historical) {
      section.append(analysisChart(item.label, [item], "s", start, end, `Wöchentlicher letzter Garmin-Messwert. Quelle: ${item.source}. Fehlende Wochen bleiben ohne Messwert; die Linie verbindet nur vorhandene Schätzungen.`, { sparse: true }));
    }
  }
  root.append(section);
}

function providerMetricStatus(status) {
  return {
    current: "aktuell",
    ok: "bestätigt",
    provisional: "vorläufig",
    insufficient_data: "nicht genügend Daten",
    partial: "teilweise",
    unavailable: "nicht verfügbar",
    failed: "fehlgeschlagen",
    stale: "veraltet",
    unsupported: "nicht unterstützt",
    unknown: "unbekannt",
  }[status] || "unbekannt";
}

function providerMetricLabel(key) {
  return { endurance_score: "Endurance Score", running_tolerance: "Running Tolerance" }[key] || key;
}

function providerMetricValue(metric, values) {
  const fields = {
    endurance_score: ["overallScore", "enduranceScore", "score"],
    running_tolerance: ["runningTolerance", "tolerance"],
  }[metric] || [];
  for (const field of fields) {
    const value = values?.[field];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function renderProviderMetrics(metrics, root, start, end) {
  Object.entries(metrics || {}).forEach(([key, item], index) => {
    const raw = (Array.isArray(item?.points) ? item.points : []).map((point) => ({ date: point?.date, value: providerMetricValue(key, point?.values) })).filter((point) => point.date && point.value !== undefined);
    if (!raw.some(analysisValidPoint)) return;
    const points = analysisWeeklyPerformancePoints(raw, start, end, false);
    const series = [{ label: providerMetricLabel(key), legendLabel: providerMetricLabel(key), source: item.source || "Garmin Connect", unit: "", color: index, cadenceDays: 7, points, currentPoint: raw.filter((point) => point.date <= end).findLast(analysisValidPoint) }];
    const chart = analysisChart(providerMetricLabel(key), series, "", start, end, "", { sparse: true, showLegend: false });
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
    const values = readings.map((point) => Number(point.value)).sort((a, b) => a - b);
    const middle = Math.floor(values.length / 2);
    let value = null;
    if (values.length) value = values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
    const latest = readings.at(-1);
    weeks.push(latest
      ? { ...latest, date: boundedEnd, value, count: readings.length, observedDate: latest.observed_at || latest.date }
      : { date: boundedEnd, value: null, count: 0 });
  }
  return weeks;
}

function bodySeriesPoints(item, window) {
  const points = (item.points || []).filter((point) => point.date >= window.start && point.date <= window.end)
    .map((point) => ({ ...point, power_method: item.power_method, observedDate: point.observed_at || point.date }));
  return bodyHistoryPeriod === "twelveWeeks" ? bodyWeeklyPoints(points, window.start, window.end) : points;
}

function renderBodyAnalysis(body) {
  const root = document.getElementById("bodyAnalysisCharts");
  if (!root) return;
  const openDetails = new Set([...root.querySelectorAll("details[open]")].map((item) => item.querySelector("summary")?.textContent));
  root.replaceChildren();
  const key = bodyHistoryPeriod === "fortnight" ? "14d" : "12w";
  const window = body?.windows?.[key];
  root.append(analysisPeriodControls("Zeitraum für Body", bodyHistoryPeriod, (period) => {
    bodyHistoryPeriod = period;
    renderBodyAnalysis(body);
  }));
  if (!window?.start || !window?.end) {
    root.append(reportNode("p", "Noch keine Body-Historie verfügbar.", "empty"));
    return;
  }
  const metrics = [
    ["weight_kg", "Gewicht", "kg"],
    ["body_fat_pct", "Körperfett", "%"],
    ["cycling_w_per_kg", "Rad-Leistung pro Gewicht", "W/kg"],
  ];
  for (const [metric, title, unit] of metrics) {
    const entries = window.metrics?.[metric] || [];
    const series = entries.map((item, index) => ({
      label: [item.power_method, item.source].filter(Boolean).join(" \u00b7 "),
      legendLabel: item.source,
      source: item.source,
      unit,
      color: index,
      noCurrentLine: true,
      sparse: true,
      cadenceDays: bodyHistoryPeriod === "twelveWeeks" ? 7 : 1,
      explanation: metric === "cycling_w_per_kg"
        ? "Tageswert aus FTP oder eFTP geteilt durch das letzte Körpergewicht der vorherigen sieben Tage."
        : "Nur gemessene Tageswerte; fehlende Tage bleiben Lücken.",
      points: bodySeriesPoints(item, window),
    }));
    const chart = analysisChart(title, series, unit, window.start, window.end,
      metric === "cycling_w_per_kg"
        ? "W/kg verwendet FTP (Garmin Connect) oder eFTP (Intervals.icu) und ein höchstens sieben Tage altes gemessenes Gewicht."
        : "Gemessene Verlaufswerte aus Intervals.icu Wellness oder Garmin Connect. Fehlende Messungen werden nicht ergänzt.",
      { sparse: true });
    chart.dataset.bodyMetric = metric;
    if (bodyHistoryPeriod === "twelveWeeks") chart.querySelectorAll(".analysis-info-tooltip").forEach((info) => {
      info.append(reportNode("p", "12 rollierende Wochen: Median der Messungen je Woche. Datum nennt den letzten Messwert der Woche.", "analysis-reference-note"));
    });
    if (metric === "cycling_w_per_kg") chart.querySelectorAll(".analysis-info-tooltip").forEach((info, index) => {
      const item = entries[index];
      if (item?.power_method) info.append(reportNode("p", `Methode: ${item.power_method}. FTP- und Gewichtsdatum sind in den Einzelwerten getrennt ausgewiesen.`, "analysis-reference-note"));
    });
    root.append(chart);
  }
  root.querySelectorAll("details").forEach((details) => { details.open = openDetails.has(details.querySelector("summary")?.textContent); });
}

let seasonGeneration = 0;
let trainingRecordsGeneration = 0;
let equipmentTab = "bike";

async function renderTrainingRecords({ force = false } = {}) { // NOSONAR
  if (!state.data || !equipmentRouteActive()) return;
  const generation = ++trainingRecordsGeneration;
  const session = state.sessionGeneration;
  try {
    const result = await requestAnalysisReport("/api/analysis/training-records", { force });
    if (generation !== trainingRecordsGeneration || session !== state.sessionGeneration) return;
    const gear = document.getElementById("equipmentItems");
    const openDetails = new Set([...gear.querySelectorAll("details[open]")]
      .map((details) => `${details.closest(".equipment-tab-panel")?.id || "other"}:${details.querySelector("summary")?.textContent || ""}`));
    gear.replaceChildren(reportNode("h3", "Ausrüstung und Wartung"));
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
    const bikeItems = activeLocalItems.filter((item) => ["Ride", "VirtualRide"].includes(item.sport) || item.kind === "bike" || item.kind === "component");
    const runItems = activeLocalItems.filter((item) => item.sport === "Run" || item.kind === "shoes");
    const archivedBikeItems = archivedLocalItems.filter((item) => ["Ride", "VirtualRide"].includes(item.sport) || item.kind === "bike" || item.kind === "component");
    const archivedRunItems = archivedLocalItems.filter((item) => item.sport === "Run" || item.kind === "shoes");
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
      bike: [...archivedBikeItems.map((item) => ({ item, source: "local" })), ...archivedGarminBikeItems.map((item) => ({ item, source: "garmin" }))],
      run: [...archivedRunItems.map((item) => ({ item, source: "local" })), ...archivedGarminRunItems.map((item) => ({ item, source: "garmin" }))],
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
          ...archivedUncategorizedGarminItems.map((item) => ({ item, source: "garmin" })),
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
  const segment = { "analysis/load": "load", "analysis/body": "body", "analysis/recovery": "recovery" }[route] || "performance";
  document.getElementById("analysisHistoryCharts").hidden = segment !== "performance";
  document.getElementById("existingPerformanceReports").hidden = segment !== "performance";
  document.getElementById("bodyAnalysisCharts").hidden = segment !== "body";
  document.getElementById("performancePredictions").hidden = segment !== "performance" || !document.getElementById("performancePredictions").childElementCount;
  document.getElementById("sessionPerformance").hidden = segment !== "load";
  document.getElementById("trainingZoneCharts").hidden = segment !== "load";
  document.getElementById("analysisLoadCharts").hidden = segment !== "load";
  document.getElementById("personalRecovery").hidden = segment !== "recovery";
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

function recoveryReferenceLabel(item, range, target, unit, position) {
  const status = `Status: ${providerMetricStatus(item.status || "unknown")}`;
  if (range) {
    const provisional = item.status === "provisional" ? " · vorläufig" : "";
    return `${position || "Persönlicher Bereich"} · Basis ${analysisValue(range.lower, unit)}–${analysisValue(range.upper, unit)}${provisional} · ${status}`;
  }
  if (target != null) return `Persönliches Schlafziel: ${analysisValue(target, unit)} · ${status}`;
  return `Persönliche Basis: ${item.reason || "noch nicht verfügbar"} · ${status}`;
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
    const position = { below: "Unter deinem üblichen Bereich", within: "Innerhalb deines üblichen Bereichs", above: "Über deinem üblichen Bereich" }[item.position];
    const measurement = metric === "hrv" ? " · " + item.measurement : "";
    const rangeDescription = range ? " - persönlicher Bereich aus " + item.nights + " früheren Nächten" : "";
    return { label: `${title} · ${item.source}${measurement}`, legendLabel: title, source: item.source, unit, color,
      bars: metric === "sleep", average: true, averageInHeading: true, cadenceDays: recoveryHistoryPeriod === "twelveWeeks" ? 7 : 1, range, target,
      currentPoint: points.some(analysisValidPoint) ? null : item.history.findLast((point) => point.date <= today && analysisValidPoint(point)),
      referenceLabel: metric === "sleep" ? `Durchschnitt der angezeigten Werte · Status: ${providerMetricStatus(item.status || "unknown")}` : recoveryReferenceLabel(item, range, target, unit, position),
      coverageShort: `${readings.length}/${expectedDays} Tage mit Messung`,
      coverage: `${readings.length}/${expectedDays} Tage mit Messung${rangeDescription}`, points };
  });
  const note = "Schlaf zeigt den Durchschnitt der angezeigten Messungen. Persönliche Normalbereiche werden nur für HRV und Ruhepuls angezeigt.";
  const charts = series.map((item) => {
    const values = item.points.filter(analysisValidPoint).map((point) => Number(point.value));
    const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    const title = average == null ? item.legendLabel : `${item.legendLabel} · Ø ${analysisValue(average, item.unit)}`;
    return analysisChart(title, [item], item.unit, start, end, "", { compactInfo: true, includeCoverage: false, showLegend: false });
  });
  root.append(analysisPeriodControls("Zeitraum für Erholung", recoveryHistoryPeriod, (period) => { recoveryHistoryPeriod = period; renderPersonalRecovery(report); }));
  root.append(analysisChartGroup(`Erholung · ${recoveryHistoryPeriod === "twelveWeeks" ? "Letzte 12 Wochen" : "Letzte 14 Tage"}`, charts, series, note));
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

function renderTrainingFocus(report) {
  const root = document.getElementById("sessionPerformance");
  const zones = document.getElementById("trainingZoneCharts");
  zones.replaceChildren();
  root.replaceChildren(reportNode("h3", "Trainingsfokus"));
  if (!report) { root.append(reportNode("p", "Noch keine Trainingsdaten vorhanden.", "muted")); return; }

  const categories = [["low_aerobic", "Leicht aerob"], ["high_aerobic", "Hoch aerob"], ["anaerobic", "Anaerob"]];
  const info = reportNode("button", "i", "analysis-legend-info");
  info.type = "button"; info.setAttribute("aria-label", "Trainingsfokus: Informationen");
  const explanation = reportNode("div", `Letzte 4 Wochen: ${dateLabel(report.start)} bis ${dateLabel(report.end)}. ${report.coverage?.known_sessions ?? 0} erfasste Garmin-Einheiten im Zeitraum${report.coverage?.observed_start && report.coverage?.observed_end ? ` · erfasste Daten ${dateLabel(report.coverage.observed_start)} bis ${dateLabel(report.coverage.observed_end)}` : ""}. Garmin: aufgezeichnete Belastung nach der Hauptwirkung der Einheit (Training Effect). Keine aus Zonen abgeleitete Einteilung und nicht Garmins separat berechnete Load-Focus-Metrik. ${report.unclassified_sessions || 0} Einheiten ohne bekannte Wirkung oder Belastung bleiben ausgeschlossen.`, "analysis-info-tooltip"); // NOSONAR
  explanation.id = `focus-info-${++analysisInfoId}`; explanation.setAttribute("popover", "auto"); explanation.setAttribute("role", "tooltip");
  info.setAttribute("popovertarget", explanation.id); root.firstChild.append(info); root.append(explanation);
  appendTrainingFocusShare(report, categories, root);
  appendTrainingFocusZones(report, zones);
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
  card.append(reportNode("p", [KIND_LABELS[item.kind] || item.kind, item.sport_pending ? "Sportart offen" : (SPORT_LABELS[item.sport] || item.sport), item.parent_pending ? "Fahrrad offen" : "", item.status === "archived" ? "ausgemustert" : "aktiv"].filter(Boolean).join(" \u00b7 ")));
  card.append(reportNode("p", `${analysisValue(usage.distance_km, "km")} \u00b7 ${analysisValue(usage.hours, "h")} \u00b7 ${usage.assigned_sessions || 0} zugeordnete Einheiten`));
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
      await api("/api/equipment/maintenance", { method: "POST", body: JSON.stringify({ equipment_id: item.id, date: timezoneDateKey(state.data?.profile?.timezone, new Date()) }) });
      await renderTrainingRecords({ force: true });
    } catch (error) {
      button.disabled = false;
      button.textContent = error.message || "Wartung fehlgeschlagen";
    }
  });
  return button;
}

function garminEquipmentCard(item) {
  const card = reportNode("section", null, "garmin-equipment-card");
  card.append(reportNode("h4", item.name));
  card.append(reportNode("p", [KIND_LABELS[item.kind] || item.kind, item.garmin_status || "Unbekannter Garmin-Status"].filter(Boolean).join(" \u00b7 ")));
  if (item.sessions != null) card.append(reportNode("p", `${item.sessions} Einheiten`));
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
  progress.setAttribute("aria-label", `${card.querySelector("h4")?.textContent || "Ausr\u00fcstung"}: ${percent}% Lebensdauer${overage ? ", Ziel \u00fcberschritten" : ""}`);
  card.append(progress, reportNode("p", `${analysisValue(usage, "km")} von ${analysisValue(target, "km")} \u00b7 ${percent}%${overage ? " \u00b7 Ziel \u00fcberschritten" : ""}`));
}

function seasonEventCard(event, generation) {
  const section = reportNode("section", null, "analysis-chart-card");
  section.append(reportNode("h4", `${event.name} · ${dateLabel(event.event_date)} · Priorität ${event.priority}`));
  const phase = {base:"Basis",build:"Aufbau",peak:"Spezifische Vorbereitung",taper:"Taper",completed:"Vergangen"}[event.phase];
  section.append(reportNode("p", `${event.days_until} Tage · kalendarische Phase: ${phase} · ${event.preparation.sessions_84_days} passende Einheiten in 84 Tagen`));
  const weekly = reportNode("details"); weekly.append(reportNode("summary", `${event.preparation.weeks_with_recorded_training}/12 Wochen mit erfasstem sportartspezifischem Training`));
  for (const week of event.preparation.weeks || []) weekly.append(reportNode("p", seasonWeekSummary(week)));
  weekly.append(reportNode("p", "Wochen ohne Aufzeichnung beweisen keine Trainingspause; Umfang enthält nur lokal bekannte Einheiten.", "muted")); section.append(weekly);
  appendSeasonEvidence(event.preparation, section);
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

function seasonStatusLabel(status) {
  return { observations: "Beobachtungen", observed: "beobachtet", insufficient_data: "nicht genügend Daten", unknown: "unbekannt" }[status] || status || "unbekannt";
}

function seasonDistance(value) {
  const km = value == null ? null : AppFormat.number(Number(value) / 1000);
  return km == null ? "unbekannt" : `${km} km`;
}

function seasonDuration(value) {
  return value == null ? "unbekannt" : formatDuration(Number(value));
}

function appendSeasonEvidence(preparation, section) {
  const target = preparation?.target_context || {};
  const weekly = preparation?.weekly_observed_volume || {};
  const long = preparation?.long_session_evidence || {};
  const specificity = preparation?.specificity_evidence || {};
  const comparison = preparation?.target_distance_comparison || {};
  const details = reportNode("details", null, "season-evidence");
  details.open = true;
  details.append(reportNode("summary", "Beobachtete Nachweise und Lücken"));
  details.append(reportNode("p", `Zielkontext · Sport: ${target.sport || "unbekannt"} · Distanz: ${target.distance_confirmed ? seasonDistance(target.distance_meters) : "unbekannt"} · Ziel: ${target.target_confirmed ? target.target : "unbekannt"} · Quelle: ${target.source || "unbekannt"}`));
  details.append(reportNode("p", `Wöchentlicher beobachteter Umfang · Status: ${seasonStatusLabel(weekly.status)} · ${weekly.weeks_with_sessions ?? 0}/${weekly.weeks_total ?? 12} Wochen mit Einheiten · ${weekly.sessions ?? 0} Einheiten · Dauer: ${seasonDuration(weekly.duration_seconds)} (${weekly.duration_known_sessions ?? 0} bekannte Einheiten) · Distanz: ${seasonDistance(weekly.distance_meters)} (${weekly.distance_known_sessions ?? 0} bekannte Einheiten) · Quelle: ${weekly.source || "unbekannt"}`));
  appendSeasonWeeklyHistory(preparation.weeks || [], weekly.source || "Intervals.icu recorded activities", details);
  details.append(reportNode("p", `Lange Einheit · Status: ${seasonStatusLabel(long.status)} · ${long.sessions ?? 0} Nachweise · längste Dauer: ${seasonDuration(long.duration_seconds)} · längste Distanz: ${seasonDistance(long.distance_meters)} · Quelle: ${long.source || "unbekannt"}`));
  const dimensions = specificity.known_dimensions || {};
  details.append(reportNode("p", `Spezifitätsnachweise · Status: ${seasonStatusLabel(specificity.status)} · Ausdauer: ${dimensions.aerobic ?? 0} · Power-Profil: ${dimensions.power_profile ?? 0} · Intervallqualität: ${dimensions.interval_quality ?? 0} · Quelle: ${specificity.source || "unbekannt"}`));
  details.append(reportNode("p", `Zieldistanzvergleich · Status: ${seasonStatusLabel(comparison.status)} · Ziel: ${seasonDistance(comparison.target_distance_meters)} · beobachtete lange Einheit: ${seasonDistance(comparison.observed_long_session_distance_meters)} · Quelle: ${comparison.source || "unbekannt"}`));
  section.append(details);
}

function appendSeasonWeeklyHistory(weeks, source, root) {
  const validWeeks = weeks.filter((week) => week?.start && week?.end);
  if (!validWeeks.length) {
    root.append(reportNode("p", "Wöchentlicher Verlauf: unbekannt · keine datierten Wochen verfügbar.", "muted"));
    return;
  }
  const start = validWeeks[0].end;
  const end = validWeeks.at(-1).end;
  const duration = validWeeks.map((week) => ({ date: week.end, value: week.duration_seconds == null ? null : Number(week.duration_seconds) / 3600, count: week.duration_known_sessions ?? 0 }));
  const distance = validWeeks.map((week) => ({ date: week.end, value: week.distance_meters == null ? null : Number(week.distance_meters) / 1000, count: week.distance_known_sessions ?? 0 }));
  const durationSeries = [{ label: "Dauer", legendLabel: "Dauer", source, unit: "h", cadenceDays: 7, noCurrentLine: true, points: duration }];
  const distanceSeries = [{ label: "Distanz", legendLabel: "Distanz", source, unit: "km", cadenceDays: 7, noCurrentLine: true, points: distance }];
  if (duration.some(analysisValidPoint)) root.append(analysisChart("Beobachtete Trainingsdauer je Woche", durationSeries, "h", start, end, "Nur bekannte Aktivitätsdauern; fehlende Wochen bleiben Lücken.", { sparse: true }));
  else root.append(reportNode("p", "Wöchentliche Dauer: unbekannt · keine bekannten Aktivitätsdauern.", "muted"));
  if (distance.some(analysisValidPoint)) root.append(analysisChart("Beobachtete Trainingsdistanz je Woche", distanceSeries, "km", start, end, "Nur bekannte Aktivitätsdistanzen; fehlende Wochen bleiben Lücken.", { sparse: true }));
  else root.append(reportNode("p", "Wöchentliche Distanz: unbekannt · keine bekannten Aktivitätsdistanzen.", "muted"));
  const table = reportNode("table");
  table.append(reportNode("caption", `Wochenabdeckung · ${source}`));
  const head = reportNode("thead"); const header = reportNode("tr");
  for (const label of ["Woche", "Einheiten", "Dauer · bekannt", "Distanz · bekannt"]) header.append(reportNode("th", label));
  head.append(header); table.append(head);
  const body = reportNode("tbody");
  for (const week of validWeeks) {
    const row = reportNode("tr");
    row.append(reportNode("td", `${dateLabel(week.start)} – ${dateLabel(week.end)}`));
    row.append(reportNode("td", String(week.sessions ?? 0)));
    row.append(reportNode("td", `${seasonDuration(week.duration_seconds)} · ${week.duration_known_sessions ?? 0}/${week.sessions ?? 0}`));
    row.append(reportNode("td", `${seasonDistance(week.distance_meters)} · ${week.distance_known_sessions ?? 0}/${week.sessions ?? 0}`));
    body.append(row);
  }
  table.append(body);
  const wrap = reportNode("div", null, "analysis-chart-table"); wrap.append(table); root.append(wrap);
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
  const duration = week.duration_seconds == null ? "Dauer unbekannt" : AppFormat.duration(week.duration_seconds);
  const distance = week.distance_meters == null ? "Distanz unbekannt" : (AppFormat.distance(week.distance_meters) ?? "0 km");
  return `${dateLabel(week.start)} \u2013 ${dateLabel(week.end)}: ${week.sessions} erfasste Einheiten \u00b7 ${duration} (${week.duration_known_sessions}/${week.sessions} gemessen) \u00b7 ${distance} (${week.distance_known_sessions}/${week.sessions} gemessen)`;
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
    legend.style.gridTemplateColumns = categories.map(([key]) => `${Math.max(report.categories[key].load, 0.001)}fr`).join(" ");
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
  for (const sensor of ["heart_rate", "power"]) {
    const matching = zones.filter((item) => item.sensor === sensor);
    const title = sensor === "heart_rate" ? "HF-Zonen" : "Power-Zonen";
    const seconds = new Map();
    for (const item of matching) for (const [zone, value] of Object.entries(item.seconds)) seconds.set(zone, (seconds.get(zone) || 0) + value);
    if (![...seconds.values()].some((value) => value > 0)) { details.append(reportNode("p", `${title}: keine aufgezeichneten Zonenzeiten.`, "muted")); continue; }
    details.append(trainingFocusDistribution(title, [...seconds.entries()].sort(([a], [b]) => Number(a.slice(1)) - Number(b.slice(1))).map(([label, value]) => ({label, value})), "seconds",
      `Intervals.icu: aufgezeichnete Zonenzeiten aller Sportarten in den letzten vier Wochen. HF und Power werden separat summiert; eine Einheit kann in beiden Ansichten vorkommen. Zonen beziehen sich auf die jeweils aufgezeichneten sportartspezifischen Schwellen. Fehlende Messungen werden nicht als null gewertet.`));
  }
  if (!zones.length) details.append(reportNode("p", "Noch keine aufgezeichneten HF- oder Power-Zonenzeiten vorhanden.", "muted"));
}
