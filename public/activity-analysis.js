/* One session's details in its calendar card (#2258). Charts follow the Garmin Connect app: one filled area per channel, average line and tap readout. */
(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const WIDTH = 340; const HEIGHT = 150; const LEFT = 40; const RIGHT = 8; const TOP = 10; const BOTTOM = 22;
  // The latest load of each panel; an older answer for the same panel is dropped.
  const panelLoads = new WeakMap();

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function svgNode(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
    return element;
  }

  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const numberText = (value, digits = 0) => AppFormat.number(value, { digits }) ?? "—";
  const clock = (seconds) => {
    const total = Math.round(seconds);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const rest = String(total % 60).padStart(2, "0");
    return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
  };

  // The calendar entry and the loaded document both carry the session's neutral sport.
  function sportKind(activity) {
    const sport = activity?.sport;
    if (sport === "swim") return "swim";
    if (["run", "walk", "hike"].includes(sport)) return "run";
    return "other";
  }

  // Pace sports show min/km (or min/100 m); others km/h. Stops below 0.3 m/s become gaps.
  function speedChannel(activity) {
    const kind = sportKind(activity);
    if (kind === "other") return { label: "Geschwindigkeit", unit: "km/h", convert: (v) => v * 3.6, format: (v) => numberText(v, 1), color: "speed", floorAtZero: true };
    const meters = kind === "swim" ? 100 : 1000;
    return { label: "Pace", unit: kind === "swim" ? "min/100 m" : "min/km", convert: (v) => (v >= 0.3 ? meters / v : null), format: clock, invert: true, color: "speed" };
  }

  function cadenceChannel(activity, metrics) {
    const { label, unit, factor } = ActivityDetails.cadenceDisplay(activity);
    const convert = (value) => value * factor;
    return { key: "cadence_rpm", label, unit, convert, color: "cadence", format: (v) => numberText(v), floorAtZero: true, average: finite(metrics.avg_cadence) ? convert(metrics.avg_cadence) : null, max: finite(metrics.max_cadence) ? convert(metrics.max_cadence) : null };
  }

  function channels(activity, metrics, streams) {
    const speed = speedChannel(activity);
    return [
      { key: "heart_rate_bpm", label: "Herzfrequenz", unit: "bpm", color: "heart", format: (v) => numberText(v), floorAtZero: true, average: metrics.avg_hr, max: metrics.max_hr },
      { ...speed, key: "speed_mps", average: finite(metrics.avg_speed_mps) ? speed.convert(metrics.avg_speed_mps) : null, max: finite(metrics.max_speed_mps) ? speed.convert(metrics.max_speed_mps) : null },
      { key: "power_w", label: "Leistung", unit: "W", color: "power", format: (v) => numberText(v), floorAtZero: true, average: metrics.avg_power, max: metrics.max_power_w },
      cadenceChannel(activity, metrics),
      { key: "altitude_m", label: "Höhe", unit: "m", color: "elevation", format: (v) => numberText(v), elevation: true },
      { key: "temperature_c", label: "Temperatur", unit: "°C", color: "temperature", format: (v) => numberText(v, 1), average: metrics.avg_temp_c, max: metrics.max_temp_c },
      // Running dynamics per second, named like their averages in the values (#2258).
      ...ActivityDetails.RUNNING_DYNAMICS.map(([key, label, unit, digits]) => ({ key, label, unit, color: "dynamics", format: (v) => numberText(v, digits), average: metrics[key] })),
    ].filter((channel) => Array.isArray(streams.channels?.[channel.key]?.values));
  }

  function percentile(sorted, share) {
    return sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(share * (sorted.length - 1))))];
  }

  function channelValue(channel, value) {
    if (!finite(value)) return null;
    return channel.convert ? channel.convert(value) : value;
  }

  // Robust range: single sensor spikes must not flatten the curve.
  function chartRange(sorted, channel) {
    let low = channel.elevation ? sorted[0] : percentile(sorted, 0.01);
    let high = channel.elevation ? sorted.at(-1) : percentile(sorted, 0.99);
    // A near-constant series would zoom into a solid block: the axis keeps a span of at least 5 % of the level (1 unit minimum).
    const minimumSpan = Math.max(1, Math.abs(low + high) / 2 * 0.05);
    const flat = high - low < minimumSpan;
    if (flat) { const middle = (low + high) / 2; low = middle - minimumSpan / 2; high = middle + minimumSpan / 2; }
    const padding = (high - low) * 0.08;
    // Only non-negative channels clamp at zero; elevation, pace and temperature may go below it.
    low = channel.floorAtZero ? Math.max(0, low - padding) : low - padding;
    return { low, high: high + padding, flat };
  }

  function chartSummary(channel, sorted, valid) {
    if (channel.elevation) return `Min ${channel.format(sorted[0])} · Max ${channel.format(sorted.at(-1))} ${channel.unit}`;
    const bestShare = channel.invert ? 0.01 : 0.99;
    const best = finite(channel.max) ? channel.max : percentile(sorted, bestShare);
    const bestLabel = channel.invert ? "Beste" : "Max";
    return `Ø ${channel.format(chartAverage(channel, valid))} · ${bestLabel} ${channel.format(best)} ${channel.unit}`;
  }

  // The provider's values win; otherwise the plotted mean and 1st/99th percentile ignore single GPS spikes.
  function chartAverage(channel, valid) {
    if (finite(channel.average)) return channel.average;
    return valid.reduce((sum, [, value]) => sum + value, 0) / valid.length;
  }

  function chartPaths(points, scale) {
    let line = ""; let area = ""; let segment = [];
    const flush = () => {
      if (segment.length > 1) {
        const edges = segment.map(([px, py]) => `L${px},${py}`).join(" ");
        area += `M${segment[0][0]},${scale.baseline} ${edges} L${segment.at(-1)[0]},${scale.baseline} Z `;
      }
      segment = [];
    };
    for (const [time, value] of points) {
      if (!finite(value)) { flush(); continue; }
      const px = scale.x(time).toFixed(1); const py = scale.y(value).toFixed(1);
      line += `${segment.length ? "L" : "M"}${px},${py} `;
      segment.push([px, py]);
    }
    flush();
    return { line, area };
  }

  function appendAxes(svg, channel, scale) {
    const { low, high, start, span } = scale;
    const ticks = [low + (high - low) * 0.1, (low + high) / 2, high - (high - low) * 0.1];
    for (const value of ticks) {
      svg.append(svgNode("line", { x1: LEFT, x2: WIDTH - RIGHT, y1: scale.y(value), y2: scale.y(value), class: "activity-analysis-grid" }));
      const label = svgNode("text", { x: LEFT - 6, y: scale.y(value) + 4, "text-anchor": "end" });
      label.textContent = channel.format(value);
      svg.append(label);
    }
    [0, 0.5, 1].forEach((fraction) => {
      const label = svgNode("text", { x: scale.x(start + span * fraction), y: HEIGHT - 6, "text-anchor": ["start", "middle", "end"][fraction * 2] });
      label.textContent = clock(span * fraction);
      svg.append(label);
    });
  }

  // Tap or drag shows the nearest reading, like the Garmin chart scrubber.
  function attachScrubber(svg, channel, scale, valid, readout) {
    const cursor = svgNode("line", { y1: TOP, y2: scale.baseline, class: "activity-analysis-cursor", visibility: "hidden" });
    const dot = svgNode("circle", { r: 3.5, class: "activity-analysis-dot", visibility: "hidden" });
    svg.append(cursor, dot);
    const inspect = (event) => {
      const box = svg.getBoundingClientRect();
      const time = scale.start + ((event.clientX - box.left) / box.width * WIDTH - LEFT) / (WIDTH - LEFT - RIGHT) * scale.span;
      const nearest = valid.reduce((best, point) => (Math.abs(point[0] - time) < Math.abs(best[0] - time) ? point : best), valid[0]);
      cursor.setAttribute("x1", scale.x(nearest[0])); cursor.setAttribute("x2", scale.x(nearest[0]));
      dot.setAttribute("cx", scale.x(nearest[0])); dot.setAttribute("cy", scale.y(nearest[1]));
      cursor.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
      readout.textContent = `${clock(nearest[0] - scale.start)} · ${channel.format(nearest[1])} ${channel.unit}`;
    };
    svg.addEventListener("pointerdown", inspect);
    svg.addEventListener("pointermove", (event) => { if (event.buttons || event.pointerType === "mouse") inspect(event); });
    // Touch keeps the last reading visible after lifting the finger.
    svg.addEventListener("pointerleave", (event) => {
      if (event.pointerType !== "mouse") return;
      cursor.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); readout.textContent = "";
    });
  }

  function chart(streams, channel) {
    const times = streams.time_s;
    const raw = streams.channels[channel.key].values;
    if (!Array.isArray(times) || times.length !== raw.length) return null;
    const points = times.map((time, index) => [time, channelValue(channel, raw[index])]).filter(([time]) => finite(time));
    const valid = points.filter(([, value]) => finite(value));
    if (valid.length < 2) return null;
    const sorted = valid.map(([, value]) => value).sort((a, b) => a - b);
    const { low, high, flat } = chartRange(sorted, channel);
    const start = points[0][0];
    const span = Math.max(1, points.at(-1)[0] - start);
    const share = (value) => (Math.min(high, Math.max(low, value)) - low) / (high - low);
    const scale = {
      low, high, start, span, baseline: HEIGHT - BOTTOM,
      x: (time) => LEFT + (time - start) / span * (WIDTH - LEFT - RIGHT),
      y: (value) => TOP + (channel.invert ? share(value) : 1 - share(value)) * (HEIGHT - TOP - BOTTOM),
    };

    const section = node("section", null, `activity-analysis-chart is-${channel.color}`);
    const header = node("div", null, "activity-analysis-chart-header");
    header.append(node("h4", channel.label));
    const stats = node("p", null, "activity-analysis-chart-stats");
    const readout = node("span", null, "activity-analysis-readout");
    const summaryText = chartSummary(channel, sorted, valid);
    stats.append(node("span", summaryText), readout);
    header.append(stats);

    const svg = svgNode("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT}`, role: "img", "aria-label": `${channel.label}: ${summaryText}, über ${clock(span)}` });
    appendAxes(svg, channel, scale);
    const { line, area } = chartPaths(points, scale);
    // A flat series is a line only; a filled area would read as a solid block.
    if (!flat) svg.append(svgNode("path", { d: area, class: "activity-analysis-area" }));
    svg.append(svgNode("path", { d: line, class: "activity-analysis-line" }));
    if (!channel.elevation) {
      const average = scale.y(chartAverage(channel, valid));
      svg.append(svgNode("line", { x1: LEFT, x2: WIDTH - RIGHT, y1: average, y2: average, class: "activity-analysis-average" }));
    }
    attachScrubber(svg, channel, scale, valid, readout);
    section.append(header, svg);
    return section;
  }

  const measure = (value, unit) => {
    if (!finite(value)) return null;
    return unit ? `${numberText(value)} ${unit}` : numberText(value);
  };
  const duration = (value) => (finite(value) ? clock(value) : null);
  function efficiencyText(metrics) {
    if (!finite(metrics.efficiency_factor)) return null;
    const value = numberText(metrics.efficiency_factor, 2);
    return metrics.efficiency_factor_unit ? `${value} ${metrics.efficiency_factor_unit}` : value;
  }

  function speedText(speed, value) {
    const converted = finite(value) ? speed.convert(value) : null;
    return converted == null ? null : speed.format(converted);
  }

  // When the document cannot be read, the calendar entry's summary values stand in under the document's metric keys.
  function rowMetrics(row) {
    const keys = ["distance_m", "moving_duration_s", "elapsed_duration_s", "avg_speed_mps", "max_speed_mps", "avg_hr", "max_hr", "avg_power", "normalized_power", "elevation_gain_m", "intensity", "efficiency_factor", "efficiency_factor_unit", "variability_index", "work_kj", "decoupling_pct", "energy_kj", "energy_kcal", "ground_contact_time_ms", "ground_contact_balance_pct", "vertical_oscillation_cm", "vertical_ratio_pct", "step_length_m"];
    const metrics = {};
    for (const key of keys) if (row?.[key] != null) metrics[key] = row[key];
    // The calendar entry names its load like planned units do (training_load); the document calls it load.
    if (row?.training_load != null) metrics.load = row.training_load;
    return metrics;
  }

  // Strength leads with the total time, the moving time follows (#2317).
  function sessionTimes(activity, metrics) {
    const times = [["Bewegungszeit", duration(metrics.moving_duration_s ?? metrics.duration_s)], ["Gesamtzeit", duration(metrics.elapsed_duration_s)]];
    return activity?.sport === "strength" ? times.reverse() : times;
  }

  function overview(activity, metrics) {
    const speed = speedChannel(activity);
    const averageSpeed = speedText(speed, metrics.avg_speed_mps);
    const cadence = cadenceChannel(activity, metrics);
    const values = [
      ["Distanz", AppFormat.distance(metrics.distance_m)],
      ...sessionTimes(activity, metrics),
      [speed.invert ? "Ø Pace" : "Ø Geschwindigkeit", averageSpeed && `${averageSpeed} ${speed.unit}`],
      ["Ø Herzfrequenz", measure(metrics.avg_hr, "bpm")],
      ["Max. Herzfrequenz", measure(metrics.max_hr, "bpm")],
      ["Ø Leistung", measure(metrics.avg_power, "W")],
      ["Normalized Power", measure(metrics.normalized_power, "W")],
      ["Max. Leistung", measure(metrics.max_power_w, "W")],
      [`Ø ${cadence.label}`, measure(cadence.average, cadence.unit)],
      ["Anstieg", measure(metrics.elevation_gain_m, "m")],
      ["Kalorien", measure(metrics.energy_kcal ?? metrics.calories_kcal, "kcal")],
      // Local session metrics (card M8): descriptive values, no verdict.
      ["Arbeit", measure(metrics.work_kj ?? metrics.energy_kj, "kJ")],
      ["Effizienzfaktor", efficiencyText(metrics)],
      ["Variabilitätsindex", finite(metrics.variability_index) ? numberText(metrics.variability_index, 2) : null],
      ["Decoupling", finite(metrics.decoupling_pct) ? `${numberText(metrics.decoupling_pct, 1)} %` : null],
      ["Trainingsbelastung", measure(metrics.load)],
      // Intensity arrives as a fraction or in percent; the calendar helper normalizes both.
      ["Intensität", calendarIntensityLabel(metrics.intensity)],
      ...ActivityDetails.runningDynamics(metrics),
    ].filter(([, value]) => value);
    if (!values.length) return null;
    const grid = node("dl", null, "activity-analysis-stats");
    for (const [label, value] of values) {
      const item = node("div");
      item.append(node("dt", label), node("dd", value));
      grid.append(item);
    }
    return grid;
  }

  function zones(title, zone) {
    const items = (zone?.buckets || []).filter((bucket) => finite(bucket.seconds) && bucket.seconds >= 0)
      .map((bucket) => ({ id: String(bucket.label || `Z${bucket.index}`), secs: bucket.seconds }));
    const total = items.reduce((sum, item) => sum + item.secs, 0);
    if (!total) return null;
    const section = node("section", null, "activity-analysis-zones");
    section.append(node("h4", title));
    const rows = node("ol");
    for (const item of [...items].reverse()) {
      const share = item.secs / total;
      const row = node("li");
      row.dataset.zone = item.id.match(/^Z\d/)?.[0] || "";
      const bar = node("span", null, "activity-analysis-zone-bar");
      bar.style.setProperty("--zone-share", `${Math.round(share * 1000) / 10}%`);
      row.append(node("span", item.id.slice(0, 20), "activity-analysis-zone-label"), bar, node("span", `${clock(item.secs)} · ${Math.round(share * 100)} %`, "activity-analysis-zone-value"));
      rows.append(row);
    }
    // Derived zones use the zone settings of the session day, as the reports (#1743).
    section.append(rows, node("p", `Zonen laut ${zone.source?.label || "Anbieter"} am Tag der Einheit.`, "muted"));
    return section;
  }

  function laps(activity, lapSet) {
    const items = lapSet?.laps || [];
    if (!items.length) return null;
    const speed = speedChannel(activity);
    const seconds = (lap) => lap.moving_duration_s ?? lap.end_offset_s - lap.start_offset_s;
    const columns = [
      ["Zeit", (lap) => (finite(seconds(lap)) ? clock(seconds(lap)) : null)],
      ["Distanz", (lap) => AppFormat.distance(lap.distance_m)],
      [speed.invert ? "Pace" : "km/h", (lap) => (finite(lap.avg_speed_mps) && speed.convert(lap.avg_speed_mps) != null ? speed.format(speed.convert(lap.avg_speed_mps)) : null)],
      ["Ø W", (lap) => (finite(lap.avg_power) ? numberText(lap.avg_power) : null)],
      ["Ø HF", (lap) => (finite(lap.avg_hr) ? numberText(lap.avg_hr) : null)],
      ["Anstieg", (lap) => (finite(lap.elevation_gain_m) ? `${numberText(lap.elevation_gain_m)} m` : null)],
    ].filter(([, read]) => items.some((lap) => read(lap) != null));
    if (!columns.length) return null;
    const section = node("section", null, "activity-analysis-laps");
    section.append(node("h4", "Runden"));
    const wrap = makeScrollRegionFocusable(node("div", null, "analysis-chart-table"), "Runden dieser Einheit");
    const table = node("table");
    const head = node("tr");
    ["#", ...columns.map(([label]) => label)].forEach((label) => { const cell = node("th", label); cell.scope = "col"; head.append(cell); });
    const thead = node("thead"); thead.append(head);
    const body = node("tbody");
    items.forEach((lap, index) => {
      const row = node("tr");
      const label = node("th", String(index + 1)); label.scope = "row";
      row.append(label, ...columns.map(([, read]) => node("td", read(lap) ?? "—")));
      body.append(row);
    });
    table.append(thead, body); wrap.append(table); section.append(wrap);
    return section;
  }

  function renderPanel(panel, summary, payload, token) {
    panel.replaceChildren();
    // The document's session wins; the calendar entry stands in until it loads.
    const session = payload?.session || summary;
    const activity = { sport: session.sport, environment: session.environment };
    const metrics = payload ? ActivityDetails.metricValues(payload) : rowMetrics(summary);
    if (payload?.metrics?.efficiency_factor?.unit) metrics.efficiency_factor_unit = payload.metrics.efficiency_factor.unit;
    const stats = overview(activity, metrics);
    if (stats) panel.append(stats);
    const driftLines = ActivityDetails.formDriftLines(payload?.analysis?.form_drift);
    if (driftLines.length) {
      const drift = node("div");
      drift.append(...driftLines.map((line) => node("p", line)));
      panel.append(drift);
    }
    // The running dynamics share the time axis of the other channels.
    const streams = payload?.streams && { ...payload.streams, channels: { ...payload.streams.channels, ...payload.running_dynamics_streams } };
    const charts = streams ? channels(activity, metrics, streams).map((channel) => chart(streams, channel)).filter(Boolean) : [];
    if (charts.length) {
      const grid = node("div", null, "activity-analysis-charts");
      grid.append(...charts);
      panel.append(grid);
    }
    for (const section of [zones("Zeit in HF-Zonen", payload?.zones?.heart_rate), zones("Zeit in Leistungszonen", payload?.zones?.power), laps(activity, payload?.laps)]) {
      if (section) panel.append(section);
    }
    if (!payload) return;
    if (streams && !charts.length) panel.append(node("p", "Keine darstellbaren Messreihen", "muted"));
    panel.append(...ActivityDetails.providerNotes(payload));
    appendRefresh(panel, summary, payload, token);
  }

  // The newest activities are preloaded after each provider refresh; older ones load through these actions.
  function appendRefresh(panel, summary, payload, token) {
    const status = node("p", "", "muted"); status.setAttribute("role", "status");
    const isCurrent = () => panelLoads.get(panel) === token && panel.isConnected;
    panel.append(ActivityDetails.refreshActions(payload, {
      api, isCurrent, onStatus: (text) => { status.textContent = text; }, onLoaded: () => loadPanel(panel, summary),
    }), status);
  }

  async function loadPanel(panel, summary) {
    const token = {};
    panelLoads.set(panel, token);
    const current = () => panelLoads.get(panel) === token && panel.isConnected;
    panel.replaceChildren(createLoadingState("Details werden geladen …"));
    let payload;
    try {
      payload = await api(`/api/activities/${encodeURIComponent(String(summary.activity_id || summary.id))}`, { timeoutMs: DATA_LOAD_TIMEOUT_MS });
    } catch (error) {
      if (!current()) return;
      // The card's summary values still render when the detail document cannot be read.
      renderPanel(panel, summary, null, token);
      panel.prepend(createErrorState(error.message, () => void loadPanel(panel, summary)));
      return;
    }
    if (current()) renderPanel(panel, summary, payload, token);
  }

  globalThis.ActivityAnalysis = { loadPanel };
})();
