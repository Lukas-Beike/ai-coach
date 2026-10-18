/* Single-session analysis list. Charts follow the Garmin Connect app: one filled area per channel, average line and tap readout. */
(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PAGE_SIZE = 20;
  const WIDTH = 340; const HEIGHT = 150; const LEFT = 40; const RIGHT = 8; const TOP = 10; const BOTTOM = 22;
  // `epoch` changes only when the list is rebuilt; open panels and pagination stay valid across unchanged renders.
  let list = { key: null, cursor: null, epoch: 0 };
  let pending = null; let rerun = false;

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

  function sportKind(activity) {
    const type = String(activity?.type || "").toLowerCase();
    if (/swim/.test(type)) return "swim";
    if (/run|walk|hike/.test(type)) return "run";
    return "other";
  }

  // Walking and hiking use pace charts like running, so they need their own labels instead of "Andere".
  function sportLabel(activity) {
    const type = String(activity?.type || "").toLowerCase();
    if (/hike/.test(type)) return "Wandern";
    if (/walk/.test(type)) return "Gehen";
    return activitySportLabel(activity);
  }

  // Pace sports show min/km (or min/100 m); others km/h. Stops below 0.3 m/s become gaps.
  function speedChannel(activity) {
    const kind = sportKind(activity);
    if (kind === "other") return { label: "Geschwindigkeit", unit: "km/h", convert: (v) => v * 3.6, format: (v) => numberText(v, 1), color: "speed", floorAtZero: true };
    const meters = kind === "swim" ? 100 : 1000;
    return { label: "Pace", unit: kind === "swim" ? "min/100 m" : "min/km", convert: (v) => (v >= 0.3 ? meters / v : null), format: clock, invert: true, color: "speed" };
  }

  function channels(activity) {
    const streams = activity.streams || {};
    const speedKey = ["velocity_smooth", "velocity", "speed"].find((key) => Array.isArray(streams[key]));
    const powerKey = ["watts", "power"].find((key) => Array.isArray(streams[key]));
    const speed = speedChannel(activity);
    return [
      { key: "heartrate", label: "Herzfrequenz", unit: "bpm", color: "heart", format: (v) => numberText(v), floorAtZero: true, average: activity.average_heartrate, max: activity.max_heartrate },
      speedKey && { ...speed, key: speedKey, average: finite(activity.average_speed) ? speed.convert(activity.average_speed) : null, max: finite(activity.max_speed) ? speed.convert(activity.max_speed) : null },
      powerKey && { key: powerKey, label: "Leistung", unit: "W", color: "power", format: (v) => numberText(v), floorAtZero: true, average: activity.average_watts, max: activity.max_watts },
      { key: "cadence", label: "Kadenz", unit: "/min", color: "cadence", format: (v) => numberText(v), floorAtZero: true, average: activity.average_cadence, max: activity.max_cadence },
      { key: "altitude", label: "Höhe", unit: "m", color: "elevation", format: (v) => numberText(v), elevation: true },
      { key: "temperature", label: "Temperatur", unit: "°C", color: "temperature", format: (v) => numberText(v, 1), average: activity.average_temp, max: activity.max_temp },
    ].filter((channel) => channel && Array.isArray(streams[channel.key]));
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
    if (high - low < 1e-6) { low -= 1; high += 1; }
    const padding = (high - low) * 0.08;
    // Only non-negative channels clamp at zero; elevation, pace and temperature may go below it.
    low = channel.floorAtZero ? Math.max(0, low - padding) : low - padding;
    return { low, high: high + padding };
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

  function chart(activity, channel) {
    const times = activity.streams.time;
    const raw = activity.streams[channel.key];
    if (!Array.isArray(times) || times.length !== raw.length) return null;
    const points = times.map((time, index) => [time, channelValue(channel, raw[index])]).filter(([time]) => finite(time));
    const valid = points.filter(([, value]) => finite(value));
    if (valid.length < 2) return null;
    const sorted = valid.map(([, value]) => value).sort((a, b) => a - b);
    const { low, high } = chartRange(sorted, channel);
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
    svg.append(svgNode("path", { d: area, class: "activity-analysis-area" }), svgNode("path", { d: line, class: "activity-analysis-line" }));
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

  function speedText(speed, value) {
    const converted = finite(value) ? speed.convert(value) : null;
    return converted == null ? null : speed.format(converted);
  }

  function overview(activity) {
    const speed = speedChannel(activity);
    const averageSpeed = speedText(speed, activity.average_speed);
    const values = [
      ["Distanz", AppFormat.distance(activity.distance)],
      ["Bewegungszeit", duration(activity.moving_time)],
      ["Gesamtzeit", duration(activity.elapsed_time)],
      [speed.invert ? "Ø Pace" : "Ø Geschwindigkeit", averageSpeed && `${averageSpeed} ${speed.unit}`],
      ["Ø Herzfrequenz", measure(activity.average_heartrate, "bpm")],
      ["Max. Herzfrequenz", measure(activity.max_heartrate, "bpm")],
      ["Ø Leistung", measure(activity.average_watts, "W")],
      ["Normalized Power", [activity.weighted_average_watts, activity.normalized_power].map((value) => measure(value, "W")).find(Boolean)],
      ["Max. Leistung", measure(activity.max_watts, "W")],
      ["Ø Kadenz", measure(activity.average_cadence, "/min")],
      ["Anstieg", measure(activity.total_elevation_gain, "m")],
      ["Kalorien", measure(activity.calories, "kcal")],
      ["Trainingsbelastung", measure(activity.training_load)],
      ["Intensität", measure(activity.intensity, "%")],
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

  function zoneSeconds(values) {
    if (!Array.isArray(values)) return [];
    return values.map((value, index) => (finite(value) ? { id: `Z${index + 1}`, secs: value } : value))
      .filter((value) => value && finite(value.secs) && value.secs >= 0 && String(value.id || "").startsWith("Z"));
  }

  function zones(title, values) {
    const items = zoneSeconds(values);
    const total = items.reduce((sum, item) => sum + item.secs, 0);
    if (!total) return null;
    const section = node("section", null, "activity-analysis-zones");
    section.append(node("h4", title));
    const rows = node("ol");
    for (const item of [...items].reverse()) {
      const share = item.secs / total;
      const row = node("li");
      row.dataset.zone = String(item.id).slice(0, 3);
      const bar = node("span", null, "activity-analysis-zone-bar");
      bar.style.setProperty("--zone-share", `${Math.round(share * 1000) / 10}%`);
      row.append(node("span", String(item.id).slice(0, 20), "activity-analysis-zone-label"), bar, node("span", `${clock(item.secs)} · ${Math.round(share * 100)} %`, "activity-analysis-zone-value"));
      rows.append(row);
    }
    section.append(rows, node("p", "Zonen laut Intervals.icu zum Zeitpunkt der Aufzeichnung.", "muted"));
    return section;
  }

  function laps(activity) {
    if (!activity.laps?.length) return null;
    const speed = speedChannel(activity);
    const columns = [
      ["Zeit", (lap) => (finite(lap.moving_time) ? clock(lap.moving_time) : null)],
      ["Distanz", (lap) => AppFormat.distance(lap.distance)],
      [speed.invert ? "Pace" : "km/h", (lap) => (finite(lap.average_speed) && speed.convert(lap.average_speed) != null ? speed.format(speed.convert(lap.average_speed)) : null)],
      ["Ø W", (lap) => (finite(lap.average_watts) ? numberText(lap.average_watts) : null)],
      ["Ø HF", (lap) => (finite(lap.average_heartrate) ? numberText(lap.average_heartrate) : null)],
      ["Anstieg", (lap) => (finite(lap.total_elevation_gain) ? `${numberText(lap.total_elevation_gain)} m` : null)],
    ].filter(([, read]) => activity.laps.some((lap) => read(lap) != null));
    if (!columns.length) return null;
    const section = node("section", null, "activity-analysis-laps");
    section.append(node("h4", "Runden"));
    const wrap = makeScrollRegionFocusable(node("div", null, "analysis-chart-table"), "Runden dieser Einheit");
    const table = node("table");
    const head = node("tr");
    ["#", ...columns.map(([label]) => label)].forEach((label) => { const cell = node("th", label); cell.scope = "col"; head.append(cell); });
    const thead = node("thead"); thead.append(head);
    const body = node("tbody");
    activity.laps.forEach((lap, index) => {
      const row = node("tr");
      const label = node("th", String(index + 1)); label.scope = "row";
      row.append(label, ...columns.map(([, read]) => node("td", read(lap) ?? "—")));
      body.append(row);
    });
    table.append(thead, body); wrap.append(table); section.append(wrap);
    return section;
  }

  function sourceText(metadata, hasCharts) {
    if (!metadata.observed_at) return "Intervals.icu · Zusammenfassung aus dem lokalen Snapshot. Verlaufsdiagramme brauchen die Detaildaten.";
    const parts = [metadata.source, `Detaildaten geladen: ${formatTime(metadata.observed_at)}`];
    if (metadata.display_sampled) parts.push("Diagramme vereinfacht dargestellt");
    if (!hasCharts) parts.push("keine darstellbaren Messreihen");
    return parts.join(" · ");
  }

  function appendSourceNotes(panel, metadata, hasCharts) {
    panel.append(node("p", sourceText(metadata, hasCharts), "muted"));
    const coverage = Object.entries(metadata.coverage || {}).map(([name, value]) => `${name}: ${value?.valid_points}/${value?.points} Messwerte`);
    if (coverage.length) panel.append(node("p", `Datenabdeckung · ${coverage.join(" · ")}`, "muted"));
    if (metadata.stale) panel.append(node("p", "Die Zusammenfassung hat sich seit dem Laden geändert. Aktualisiere die Detaildaten.", "muted"));
  }

  function renderPanel(panel, summary, payload, epoch) {
    panel.replaceChildren();
    const activity = { ...summary, ...payload?.activity };
    const metadata = payload?.detail_data || {};
    const stats = overview(activity);
    if (stats) panel.append(stats);
    const charts = activity.streams ? channels(activity).map((channel) => chart(activity, channel)).filter(Boolean) : [];
    if (charts.length) {
      const grid = node("div", null, "activity-analysis-charts");
      grid.append(...charts);
      panel.append(grid);
    }
    for (const section of [zones("Zeit in HF-Zonen", activity.heart_rate_zone_times), zones("Zeit in Leistungszonen", activity.power_zone_times), laps(activity)]) {
      if (section) panel.append(section);
    }
    appendSourceNotes(panel, metadata, charts.length > 0);
    if (ActivityDetails.isIntervalsActivity(summary)) appendRefresh(panel, summary, metadata, epoch);
  }

  // Missing detail is requested only through the athlete's explicit refresh action.
  function appendRefresh(panel, summary, metadata, epoch) {
    const status = node("p", "", "muted"); status.setAttribute("role", "status");
    const refresh = node("button", metadata.observed_at ? "Detaildaten aktualisieren" : "Detaildaten laden", "secondary-button");
    refresh.type = "button";
    refresh.disabled = !state.data?.configured?.intervals;
    if (refresh.disabled) status.textContent = "Intervals.icu ist nicht konfiguriert.";
    refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      status.textContent = "Ladejob wird gestartet …";
      const isCurrent = () => epoch === list.epoch && panel.isConnected;
      try {
        if (await ActivityDetails.requestDetails(String(summary.id), { api, isCurrent, onStatus: (text) => { status.textContent = text; } })) {
          await loadPanel(panel, summary);
          return;
        }
        status.textContent = "Der Ladejob läuft im Hintergrund weiter.";
      } catch (error) {
        status.textContent = error.message;
      }
      refresh.disabled = false;
    });
    const actions = node("div", null, "dialog-actions");
    actions.append(refresh);
    panel.append(actions, status);
  }

  async function loadPanel(panel, summary) {
    const epoch = list.epoch;
    panel.replaceChildren(node("p", "Analyse wird geladen …", "muted"));
    let payload;
    try {
      payload = await api(`/api/activities/${encodeURIComponent(String(summary.id))}`);
    } catch (error) {
      if (epoch !== list.epoch || !panel.isConnected) return;
      // The summary still renders when the local detail record is missing.
      renderPanel(panel, summary, null, epoch);
      panel.prepend(node("p", error.message, "muted"));
      return;
    }
    if (epoch === list.epoch && panel.isConnected) renderPanel(panel, summary, payload, epoch);
  }

  function item(activity) {
    const entry = node("details", null, "activity-analysis-item");
    entry.dataset.sport = sportKind(activity);
    const summary = node("summary");
    const text = node("span", null, "activity-analysis-title");
    text.append(node("strong", activity.name || sportLabel(activity)));
    // Local start dates are already day keys; reparsing them as UTC instants could shift the day.
    const day = String(activity.start_date_local || activity.start_date || "").slice(0, 10);
    const facts = [day ? dateLabel(day) : null, sportLabel(activity), finite(activity.moving_time) ? AppFormat.duration(activity.moving_time) : null, AppFormat.distance(activity.distance)].filter(Boolean);
    text.append(node("span", facts.join(" · "), "muted"));
    summary.append(text);
    if (finite(activity.training_load)) summary.append(node("span", `${numberText(activity.training_load)} Last`, "activity-analysis-load"));
    const panel = node("div", null, "activity-analysis-panel");
    entry.append(summary, panel);
    entry.addEventListener("toggle", () => { if (entry.open && !panel.childElementCount) void loadPanel(panel, activity); });
    return entry;
  }

  function appendPage(root, payload) {
    root.querySelector(".activity-analysis-more")?.remove();
    const items = (payload.activities || []).filter((activity) => activity?.id != null);
    root.querySelector(".activity-analysis-list").append(...items.map(item));
    list.cursor = payload.next_cursor || null;
    if (!list.cursor) return;
    const more = node("button", "Weitere Einheiten laden", "secondary-button activity-analysis-more");
    more.type = "button";
    more.addEventListener("click", async () => {
      more.disabled = true;
      const epoch = list.epoch;
      try {
        const next = await api(`/api/activities?limit=${PAGE_SIZE}&cursor=${encodeURIComponent(list.cursor)}`);
        if (epoch === list.epoch && more.isConnected) appendPage(root, next);
      } catch (error) {
        if (!more.isConnected) return;
        more.disabled = false;
        more.textContent = `${error.message} Erneut versuchen`;
      }
    });
    root.append(more);
  }

  // Route entry and performance refreshes may both ask for the list; overlapping calls share one request plus one follow-up.
  function render() {
    if (pending) { rerun = true; return pending; }
    pending = load().finally(() => {
      pending = null;
      if (rerun) { rerun = false; void render(); }
    });
    return pending;
  }

  async function load() {
    const root = document.getElementById("activityAnalysis");
    if (!root) return;
    if (!root.childElementCount) root.append(node("p", "Einheiten werden geladen …", "muted"));
    try {
      const payload = await api(`/api/activities?limit=${PAGE_SIZE}`);
      const key = `${payload.snapshot_synced_at}|${(payload.activities || []).map((activity) => activity.id).join(",")}`;
      // An unchanged sync keeps opened sessions and loaded pages in place.
      if (key === list.key && root.querySelector(".activity-analysis-list")) return;
      list = { key, cursor: null, epoch: list.epoch + 1 };
      const heading = node("div", null, "analysis-segment-heading");
      const intro = node("div");
      intro.append(node("h3", "Einheiten"), node("p", "Einheit aufklappen für Kennzahlen, Verlaufsdiagramme, Zonen und Runden.", "muted"));
      heading.append(intro);
      const items = node("div", null, "activity-analysis-list");
      root.replaceChildren(heading, items);
      if (!payload.activities?.length) items.append(node("p", "Noch keine abgeschlossenen Einheiten synchronisiert.", "muted"));
      appendPage(root, payload);
    } catch (error) {
      if (error?.name === "AbortError") return;
      // A failed refresh keeps an already rendered list.
      if (root.querySelector(".activity-analysis-list")) return;
      root.replaceChildren(node("p", error.message, "muted"));
    }
  }

  globalThis.ActivityAnalysis = { render };
})();
