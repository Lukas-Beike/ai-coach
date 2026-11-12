/* Local activity view of the served activity_detail.v1 document. Provider reads require an explicit durable refresh job. */
(() => {
  let dialog;
  let generation = 0;

  function chart(times, values, label, unit) {
    if (!Array.isArray(times) || !Array.isArray(values) || times.length !== values.length) return null;
    const points = times.map((time, index) => [time, values[index]])
      .filter(([time, value]) => typeof time === "number" && typeof value === "number" && Number.isFinite(time) && Number.isFinite(value));
    if (points.length < 2) return null;
    const width = 680; const height = 220; const left = 64; const right = 12; const top = 16; const bottom = 34;
    const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${label}, Zeitachse in Minuten; Messwerte und Lücken sind in der Tabelle aufgeführt` });
    const min = Math.min(...points.map((point) => point[1]));
    const max = Math.max(...points.map((point) => point[1]));
    const start = points[0][0];
    const duration = Math.max(1, points.at(-1)[0] - start);
    // A near-constant series keeps an axis span of at least 5 % of its level (1 unit minimum) and stays a line.
    const level = (max + min) / 2;
    const axisSpan = Math.max(max - min, 1, Math.abs(level) * 0.05);
    const axisMax = level + axisSpan / 2;
    const y = (value) => top + (axisMax - value) / axisSpan * (height - top - bottom);
    const x = (time) => left + (time - start) / duration * (width - left - right);
    const ticks = [axisMax, level, level - axisSpan / 2];
    ticks.forEach((value) => {
      svg.append(svgNode("line", { x1: left, x2: width - right, y1: y(value), y2: y(value), class: "activity-gridline" }));
      svg.append(svgNode("text", { x: left - 8, y: y(value) + 4, "text-anchor": "end" }, Number(value).toLocaleString("de-DE", { maximumFractionDigits: 1 })));
    });
    const xTicks = [start, start + duration / 2, points.at(-1)[0]];
    xTicks.forEach((time) => svg.append(svgNode("text", { x: x(time), y: height - 8, "text-anchor": "middle" }, `${Math.round(time / 60)} min`)));
    let continuing = false;
    const path = times.map((time, index) => {
      const value = values[index];
      if (typeof time !== "number" || typeof value !== "number" || !Number.isFinite(time) || !Number.isFinite(value)) { continuing = false; return ""; }
      const command = continuing ? "L" : "M";
      continuing = true;
      return `${command}${x(time).toFixed(1)},${y(value).toFixed(1)}`;
    }).join(" ");
    svg.append(svgNode("path", { d: path }));
    const tableWrap = makeScrollRegionFocusable(h("div", "analysis-chart-table"), `${label} in ${unit}: Messwerte`);
    const rows = [];
    times.forEach((time, index) => {
      if (typeof time !== "number" || !Number.isFinite(time)) return;
      const value = values[index];
      const reading = typeof value === "number" && Number.isFinite(value) ? `${value.toLocaleString("de-DE", { maximumFractionDigits: 2 })} ${unit}` : "Lücke";
      rows.push([h("th", { scope: "row" }, `${Math.floor(time / 60)}:${String(Math.floor(time % 60)).padStart(2, "0")}`), reading]);
    });
    tableWrap.append(table(["Zeit", label], rows, { caption: `${label} in ${unit}; fehlende Werte sind als Lücke markiert.` }));
    return h("section", "activity-series", h("h3", null, `${label} (${unit})`), svg,
      h("p", "muted", `${Math.round(min * 10) / 10}–${Math.round(max * 10) / 10} ${unit} · ${Math.round(start / 60)}–${Math.round(points.at(-1)[0] / 60)} min · ${times.length - points.length} fehlende Messpunkte`),
      h("details", "activity-values", h("summary", null, `Alle ${points.length} Messwerte ansehen`), tableWrap));
  }

  // Served metric values by key; metrics the document does not carry stay absent.
  function metricValues(payload) {
    const values = {};
    for (const [key, metric] of Object.entries(payload?.metrics || {})) {
      if (metric?.value != null) values[key] = metric.value;
    }
    return values;
  }

  function render(payload, content, api, activityId, reload, notice) {
    content.replaceChildren();
    const session = payload.session || {};
    renderMetadata(session, metricValues(payload), content);
    renderRoute(payload.route, api, content);
    content.append(...providerNotes(payload));
    renderSeries(session, payload.streams, content);
    renderLaps(payload.laps, content);
    renderStrengthSets(payload.strength_sets, content);
    renderIntervalQuality(payload, content);
    renderAerobic(payload, content);
    renderRunningForm(payload, content);
    renderPower(payload, content);
    for (const item of payload.equipment || []) content.append(h("p", null, `Ausrüstung: ${item.name} · ${item.usage.distance_km} km${item.usage.maintenance_due ? " · persönliches Wartungsintervall erreicht" : ""}`));
    renderBundle(payload.session_bundle, api, content, reload, notice);
    renderFeedback(payload.activity_feedback, session, api, activityId, content, payload.session_rpe_load);
  }

  // CR-10 anchors after Foster et al. 2001; the other steps have no verbal anchor.
  const RPE_ANCHORS = { 0: "Ruhe", 1: "Sehr, sehr leicht", 2: "Leicht", 3: "Moderat", 4: "Etwas schwer", 5: "Schwer", 7: "Sehr schwer", 10: "Maximal" };

  function rpeOption(value) {
    const anchor = RPE_ANCHORS[value];
    const number = value.toLocaleString("de-DE");
    return h("option", { value: String(value) }, anchor ? `${number} · ${anchor}` : number);
  }

  function setRpe(select, value) {
    const number = value == null || value === "" ? Number.NaN : Number(value);
    if (!Number.isFinite(number)) { select.value = ""; return; }
    // A stored rating off the half-point grid keeps its own option, in order, instead of being rounded.
    if (![...select.options].some((option) => option.value === String(number))) {
      const next = [...select.options].find((option) => option.value !== "" && Number(option.value) > number);
      select.insertBefore(rpeOption(number), next || null);
    }
    select.value = String(number);
  }

  function rpeSelect(value) {
    const select = h("select", { name: "session_rpe" }, h("option", { value: "" }, "Keine Angabe"));
    for (let step = 0; step <= 20; step += 1) select.append(rpeOption(step / 2));
    setRpe(select, value);
    return select;
  }

  // The athlete's own marking wins over Garmin's event type and a competition hint; "" removes it.
  const PURPOSES = [["training", "Training"], ["race", "Wettkampf"], ["commute", "Pendeln"], ["warmup", "Einfahren"], ["cooldown", "Ausfahren"]];

  function purposeSelect(marked, detected) {
    const detectedLabel = PURPOSES.find(([key]) => key === detected)?.[1];
    const automatic = h("option", { value: "" }, !marked && detectedLabel ? `Automatisch · ${detectedLabel}` : "Automatisch");
    const select = h("select", { name: "purpose" }, automatic, PURPOSES.map(([key, label]) => h("option", { value: key }, label)));
    select.value = PURPOSES.some(([key]) => key === marked) ? marked : "";
    return select;
  }

  const SESSION_LOAD_REASONS = { no_rating: "kein RPE", conflicting_provider_ratings: "widersprüchliche Provider-RPE", no_elapsed_duration: "keine Gesamtdauer", invalid_duration: "ungültige Dauer" };

  function sessionLoadText(load) {
    if (!load || load.reason === "no_rating") return "";
    if (load.value == null) return `Session-RPE-Last: offen · ${SESSION_LOAD_REASONS[load.reason] || "unbekannt"}`;
    const value = Number(load.value).toLocaleString("de-DE", { maximumFractionDigits: 1 });
    const rpe = Number(load.rpe).toLocaleString("de-DE");
    const minutes = Number(load.duration_min).toLocaleString("de-DE", { maximumFractionDigits: 1 });
    const text = `Session-RPE-Last: ${value} AU · RPE ${rpe} (${load.rpe_source_label}) × ${minutes} min`;
    if (load.duration_flag !== "deviating_duration") return text;
    const moving = Number(load.moving_duration_min).toLocaleString("de-DE", { maximumFractionDigits: 1 });
    return `${text} · lange Unterbrechung, ${moving} min in Bewegung`;
  }

  function renderFeedback(feedback, session, api, activityId, content, sessionLoad) {
    const purpose = purposeSelect(feedback?.purpose, session?.purpose);
    const rpe = rpeSelect(feedback?.session_rpe);
    const reason = h("input", { name: "deviation_reason", maxLength: 500, value: feedback?.deviation_reason || "" });
    const notes = h("textarea", { name: "notes", rows: 3, maxLength: 4000, value: feedback?.notes || "" });
    const status = h("p", "muted", ""); status.setAttribute("role", "status");
    const save = h("button", { type: "submit" }, "Feedback speichern");
    const load = h("p", { dataset: { sessionRpeLoad: "" } });
    const showLoad = (value) => { load.textContent = sessionLoadText(value); load.hidden = !load.textContent; };
    showLoad(sessionLoad);
    const form = h("form", "activity-feedback-form", h("label", null, "Art der Einheit", purpose), h("label", null, "Session-RPE (0–10)", rpe), h("label", null, "Abweichungsgrund", reason), h("label", null, "Notizen", notes), save);
    content.append(h("section", "activity-feedback", h("h3", null, "Dein Feedback"), load, form, status));
    let shown = feedback;
    const fill = (value) => { purpose.value = PURPOSES.some(([key]) => key === value?.purpose) ? value.purpose : ""; setRpe(rpe, value?.session_rpe); reason.value = value?.deviation_reason || ""; notes.value = value?.notes || ""; };
    // The save and undo responses carry the load recomputed from the saved feedback and its provider fallback.
    let loadGeneration = 0;
    // Only the newest request may write, so a slow save response cannot overwrite a later undo.
    const applyLoad = async (generation, response) => {
      if (response && "session_rpe_load" in response) {
        if (generation === loadGeneration) {
          showLoad(response.session_rpe_load);
        }
        return;
      }
      // The response had no load (it could not be read): fall back to the served detail.
      try {
        const payload = await api(`/api/activities/${encodeURIComponent(activityId)}`);
        if (generation === loadGeneration) showLoad(payload.session_rpe_load);
      } catch { /* the saved feedback stays shown */ }
    };
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); save.disabled = true; status.textContent = "Speichere …";
      try {
        const raw = rpe.value; const value = { activity_name: session?.name || "", activity_date: session?.started_at_local || "", notes: notes.value, deviation_reason: reason.value, session_rpe: raw === "" ? null : Number(raw), purpose: purpose.value || null };
        if (raw !== "" && (!Number.isFinite(value.session_rpe) || value.session_rpe < 0 || value.session_rpe > 10)) throw new Error("RPE muss zwischen 0 und 10 liegen.");
        const generation = ++loadGeneration;
        const result = await api(`/api/activities/${encodeURIComponent(activityId)}/feedback`, { method: "POST", body: JSON.stringify(value) });
        const previous = shown; shown = result.activity_feedback;
        status.textContent = result.activity_feedback ? "Feedback gespeichert. " : "Feedback entfernt. ";
        if (result.change?.id) status.append(feedbackUndoButton(api, result.change, activityId, status, () => ++loadGeneration, (response, generation) => { shown = previous; fill(previous); void applyLoad(generation, response); }));
        void applyLoad(generation, result);
      } catch (error) { status.textContent = error.message; } finally { save.disabled = false; }
    });
  }

  function recordingText(entry) {
    const parts = [entry.label];
    if (entry.native_type) parts.push(entry.native_type);
    if (entry.started_at) parts.push(formatTime(entry.started_at));
    if (Number.isFinite(entry.duration_s)) parts.push(`${Math.round(entry.duration_s / 60)} min`);
    return parts.join(" · ");
  }

  // The provider copies bundled into this session; confirm, split and merge each carry an undo.
  function renderBundle(bundle, api, content, reload, notice) {
    const members = bundle?.members || []; const candidates = bundle?.merge_candidates || [];
    if (!reload || !bundle) return;
    const section = h("section", "activity-bundle", h("h3", null, "Aufzeichnungen"));
    const status = h("p", "muted", notice?.text || ""); status.setAttribute("role", "status");
    const buttons = [];
    const action = (label, body, done) => {
      const button = h("button", { className: "secondary-button", type: "button" }, label); buttons.push(button);
      button.addEventListener("click", async () => {
        buttons.forEach((item) => { item.disabled = true; }); status.textContent = "Speichere …";
        try {
          const result = await api(`/api/activities/${encodeURIComponent(bundle.activity_id)}/session`, { method: "POST", body: JSON.stringify(body) });
          await reload({ text: done, change: result.change });
        } catch (error) { buttons.forEach((item) => { item.disabled = false; }); status.textContent = error.message; }
      });
      return button;
    };
    const list = (entries, label, body, done) => {
      const items = h("ul", "activity-bundle-list");
      for (const entry of entries) {
        const item = h("li", null, recordingText(entry));
        if (label) { item.append(" ", action(label, body(entry), done)); }
        items.append(item);
      }
      return items;
    };
    const several = members.length > 1;
    section.append(list(members, several ? "Trennen" : null, (entry) => ({ action: "split", member_id: entry.session_id }), "Aufzeichnung getrennt. "));
    if (several && !bundle.athlete_confirmed) section.append(action("Zuordnung bestätigen", { action: "confirm" }, "Zuordnung bestätigt. "));
    if (candidates.length) { section.append(h("h4", null, "Am selben Tag")); section.append(list(candidates, "Zusammenführen", (entry) => ({ action: "merge", other_id: entry.session_id }), "Aktivitäten zusammengeführt. ")); }
    if (notice?.change?.id) status.append(undoButton(api, notice.change, status, reload));
    const remove = h("button", { className: "secondary-button", type: "button" }, "Aktivität löschen"); buttons.push(remove);
    remove.addEventListener("click", async () => {
      const confirmed = await requestConfirmation("Diese Aktivität mit allen Aufzeichnungen lokal löschen? Bei den Anbietern bleibt sie erhalten.", { title: "Aktivität löschen?", confirmLabel: "Löschen" });
      if (!confirmed) return;
      buttons.forEach((item) => { item.disabled = true; }); status.textContent = "Speichere …";
      try {
        const result = await api(`/api/activities/${encodeURIComponent(bundle.activity_id)}/session`, { method: "POST", body: JSON.stringify({ action: "delete", confirmed: true }) });
        const deleted = h("p", "muted", "Aktivität gelöscht. "); deleted.setAttribute("role", "status");
        if (result.change?.id) deleted.append(undoButton(api, result.change, deleted, reload));
        content.replaceChildren(deleted); reload.deleted?.();
      } catch (error) { buttons.forEach((item) => { item.disabled = false; }); status.textContent = error.message; }
    });
    section.append(remove);
    section.append(status); content.append(section);
  }

  // Undo of a session correction restores the touched sessions, then the detail reloads.
  function undoButton(api, change, status, reload) {
    const undo = h("button", { className: "message-undo", type: "button" }, "Rückgängig");
    undo.addEventListener("click", async () => {
      undo.disabled = true;
      try {
        await api("/api/change-history/undo", { method: "POST", body: JSON.stringify({ change_id: change.id, expected_current_hash: change.after_hash }) });
        await reload({ text: "Zurückgenommen." });
      } catch (error) { undo.disabled = false; status.textContent = error.message; }
    });
    return undo;
  }

  // Undo restores the feedback rows as they were before this save or removal.
  function feedbackUndoButton(api, change, activityId, status, begin, restored) {
    const undo = h("button", { className: "message-undo", type: "button" }, "Rückgängig");
    undo.addEventListener("click", async () => {
      undo.disabled = true; const generation = begin();
      try {
        const response = await api("/api/change-history/undo", { method: "POST", body: JSON.stringify({ change_id: change.id, expected_current_hash: change.after_hash, activity_id: activityId }) });
        restored(response, generation); status.textContent = "Zurückgenommen.";
      } catch (error) { undo.disabled = false; status.textContent = error.message; }
    });
    return undo;
  }


  function renderMetadata(session, metrics, content) {
    const duration = AppFormat.sessionSeconds(metrics, session.sport);
    const values = [
      session.sport ? activitySportLabel(session) : null,
      session.started_at ? formatTime(session.started_at) : null,
      duration != null ? `${Math.round(duration / 60)} min` : null,
      AppFormat.distance(metrics.distance_m),
      metrics.load != null ? `Belastung ${metrics.load}` : null,
    ].filter(Boolean);
    content.append(h("p", null, values.join(" · ")));
  }

  // The recognised route of the session as "label, n. Mal"; the athlete can rename it.
  function renderRoute(route, api, content) {
    if (!route) return;
    const line = h("p");
    let label = route.label;
    const show = () => {
      const rename = h("button", { className: "secondary-button", type: "button" }, "Umbenennen");
      rename.addEventListener("click", edit);
      line.replaceChildren(`${label}, ${route.repeat_index}. Mal `, rename);
    };
    const edit = () => {
      const input = h("input", { maxLength: 60, required: true, value: label, "aria-label": "Streckenname" });
      const save = h("button", { type: "submit" }, "Speichern");
      const cancel = h("button", { className: "secondary-button", type: "button" }, "Abbrechen"); cancel.addEventListener("click", show);
      const status = h("span", "muted"); status.setAttribute("role", "status");
      const form = h("form", null, input, " ", save, " ", cancel, " ", status);
      form.addEventListener("submit", async (event) => {
        event.preventDefault(); save.disabled = true; status.textContent = "Speichere …";
        try {
          const result = await api("/api/routes/rename", { method: "POST", body: JSON.stringify({ route_id: route.route_id, name: input.value }) });
          label = result.label; show();
        } catch (error) { status.textContent = error.message; save.disabled = false; }
      });
      line.replaceChildren(form); input.focus();
    };
    show(); content.append(line);
  }

  const COVERAGE_LABELS = { power_w: "Leistung", heart_rate_bpm: "Herzfrequenz", speed_mps: "Geschwindigkeit", altitude_m: "Höhe", distance_m: "Distanz", grade_pct: "Steigung", cadence_rpm: "Kadenz", temperature_c: "Temperatur" };

  // Per provider: the load state and the data coverage, with readable channel names.
  function providerFacts(entry) {
    const label = entry.label || entry.provider;
    const facts = [h("p", "muted", entry.fetched_at ? `${label} · Detaildaten geladen: ${formatTime(entry.fetched_at)}` : `${label} · Detaildaten wurden noch nicht geladen.`)];
    const coverage = Object.entries(entry.coverage || {}).map(([name, value]) => `${COVERAGE_LABELS[name] || name}: ${value?.valid_points} von ${value?.points}`);
    if (coverage.length) facts.push(h("p", "muted", `Datenabdeckung ${label} · ${coverage.join(" · ")} Messwerten`));
    return facts;
  }

  // Warnings and load errors stay visible; the provenance is one muted source line with the details folded away.
  // Each contributing provider reports its own load state; provider text is shown as plain text only.
  function providerNotes(payload) {
    const detail = payload?.detail_data || {};
    const providers = detail.providers || [];
    const notes = [];
    const facts = [];
    const loaded = providers.filter((entry) => entry.fetched_at);
    if (providers.length) {
      const latest = loaded.map((entry) => entry.fetched_at).sort().at(-1);
      notes.push(h("p", "muted", loaded.length ? `Quelle: ${loaded.map((entry) => entry.label || entry.provider).join(", ")} · Stand ${formatTime(latest)}` : "Detaildaten noch nicht geladen"));
    }
    for (const entry of providers) {
      const label = entry.label || entry.provider;
      if (entry.stale) notes.push(h("p", "muted", `${label}: Die Zusammenfassung hat sich seit dem Laden geändert. Aktualisiere die Detaildaten vor einer neuen Bewertung.`));
      if (entry.load_error?.message) notes.push(h("p", "activity-analysis-error", `${label}: ${entry.load_error.message} Automatischer Ladeversuch: ${formatTime(entry.load_error.observed_at)}`));
      facts.push(...providerFacts(entry));
    }
    // The simplified-charts note changes how the charts read, so it stays outside the folded details.
    if (detail.display_sampled) notes.push(h("p", "muted", "Diagramme vereinfacht dargestellt"));
    if (facts.length) {
      notes.push(h("details", "provenance-details", h("summary", null, "Herkunft im Detail"), facts));
    }
    return notes;
  }

  // One explicit detail load per provider entry the server marks refreshable.
  function refreshActions(payload, { api, isCurrent, onStatus, onLoaded, onSetup = () => {} }) {
    const actions = h("div", "dialog-actions");
    const activityId = String(payload?.session?.activity_id || "");
    for (const entry of payload?.detail_data?.providers || []) {
      const label = entry.label || entry.provider;
      if (!entry.refreshable || !activityId) {
        if (state.data?.configured?.[entry.provider] !== false) continue;
        const link = h("a", { href: "#more/connections", dataset: { connection: entry.provider } }, "Anbindung einrichten");
        link.addEventListener("click", onSetup);
        actions.append(h("p", "muted provider-setup-hint", `${label} ist nicht konfiguriert. `, link));
        continue;
      }
      const button = h("button", { className: "secondary-button", type: "button" }, `${label}: Detaildaten ${entry.fetched_at ? "aktualisieren" : "laden"}`);
      button.addEventListener("click", async () => {
        const buttons = [...actions.querySelectorAll("button")];
        buttons.forEach((item) => { item.disabled = true; });
        onStatus("Ladejob wird gestartet …");
        try {
          if (await requestDetails(activityId, { provider: entry.provider, api, isCurrent, onStatus })) { await onLoaded(); return; }
          if (isCurrent()) onStatus("Der Ladejob läuft im Hintergrund weiter.");
        } catch (error) {
          if (isCurrent()) onStatus(error.message);
        }
        buttons.forEach((item) => { item.disabled = false; });
      });
      actions.append(button);
    }
    return actions;
  }


  // Running cadence is stored per leg; foot sports show steps per minute of both legs.
  function cadenceDisplay(activity) {
    if (["run", "walk", "hike"].includes(activity?.sport)) return { label: "Schrittfrequenz", unit: "spm", factor: 2 };
    return { label: "Kadenz", unit: "rpm", factor: 1 };
  }

  // Running dynamics averages (#1870): label, unit and decimals per served metric key.
  const RUNNING_DYNAMICS = [
    ["ground_contact_time_ms", "Bodenkontaktzeit", "ms", 0],
    ["ground_contact_balance_pct", "Bodenkontakt links", "%", 1],
    ["vertical_oscillation_cm", "Vertikale Oszillation", "cm", 1],
    ["vertical_ratio_pct", "Vertikales Verhältnis", "%", 1],
    ["step_length_m", "Schrittlänge", "m", 2],
  ];
  const DRIFT_METRICS = { contact_time: ["Bodenkontaktzeit", 0], vertical_oscillation: ["Vertikale Oszillation", 1], step_length: ["Schrittlänge", 2] };
  const decimal = (value, digits) => value.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

  // Label and text of each running dynamics average a sensor measured; none when the device had no sensor.
  function runningDynamics(metrics) {
    return RUNNING_DYNAMICS
      .filter(([key]) => isNumber(metrics?.[key]))
      .map(([key, label, unit, digits]) => [label, `${decimal(metrics[key], digits)} ${unit}`]);
  }

  // Lines of the form drift check, led by its label when the run is flagged; none unless the check ran.
  function formDriftLines(drift) {
    if (drift?.status !== "ok") return [];
    const lines = Object.entries(drift.metrics || {})
      .filter(([name, metric]) => DRIFT_METRICS[name] && isNumber(metric?.first) && isNumber(metric?.last) && isNumber(metric?.change_percent))
      .map(([name, metric]) => {
        const [label, digits] = DRIFT_METRICS[name];
        const sign = metric.change_percent > 0 ? "+" : "";
        return `${label} ${decimal(metric.first, digits)} → ${decimal(metric.last, digits)} ${metric.unit} (${sign}${decimal(metric.change_percent, 1)} %)`;
      });
    return drift.flagged && typeof drift.label === "string" ? [drift.label, ...lines] : lines;
  }

  function renderRunningForm(payload, content) {
    const dynamics = runningDynamics(metricValues(payload));
    const drift = formDriftLines(payload.analysis?.form_drift);
    if (!dynamics.length && !drift.length) return;
    content.append(h("h3", null, "Laufdynamik"));
    if (dynamics.length) content.append(h("p", null, dynamics.map(([label, text]) => `${label} ${text}`).join(" · ")));
    for (const line of drift) content.append(h("p", null, line));
  }

  function renderSeries(session, streams, content) {
    let charts = 0;
    const cadence = cadenceDisplay(session);
    const labels = { power_w: ["Leistung", "W"], heart_rate_bpm: ["Herzfrequenz", "bpm"], speed_mps: ["Geschwindigkeit", "m/s"], altitude_m: ["Höhe", "m"], distance_m: ["Distanz", "m"], grade_pct: ["Steigung", "%"], cadence_rpm: [cadence.label, cadence.unit], temperature_c: ["Temperatur", "°C"] };
    const channels = streams?.channels || {};
    for (const [key, [label, unit]] of Object.entries(labels)) {
      let values = channels[key]?.values;
      if (!Array.isArray(values)) continue;
      if (key === "cadence_rpm" && cadence.factor !== 1) values = values.map((value) => (typeof value === "number" ? value * cadence.factor : value));
      const series = chart(streams.time_s, values, label, unit);
      if (series) { content.append(series); charts += 1; }
    }
    if (!charts) content.append(h("p", null, "Keine darstellbaren Messreihen vorhanden. Fehlende Sensorwerte werden nicht als Null interpretiert."));
  }


  function renderLaps(laps, content) {
    if (laps?.laps?.length) {
      content.append(h("h3", null, "Intervalle / Runden"));
      const list = h("ol", "activity-laps");
      laps.laps.forEach((lap, index) => {
        const seconds = lap.moving_duration_s ?? lap.end_offset_s - lap.start_offset_s;
        list.append(h("li", null, [
          lap.name || `Intervall ${index + 1}`,
          Number.isFinite(seconds) ? `${Math.round(seconds)} s` : null,
          lap.avg_power != null ? `${Math.round(lap.avg_power)} W` : null,
          lap.avg_hr != null ? `${Math.round(lap.avg_hr)} bpm` : null,
        ].filter(Boolean).join(" · ")));
      });
      content.append(list);
    }
  }


  const STRENGTH_SOURCES = { garmin_exercise_sets: "Garmin-Sätze", fit_set_messages: "FIT-Datei" };

  // "Kniebeuge – Barbell Back Squat": the category links it to the plan, the code names the exercise.
  function strengthExerciseLabel(exercise) {
    const category = AppFormat.strengthCategory(exercise.category);
    const code = typeof exercise.name === "string" && exercise.name
      ? exercise.name.toLowerCase().split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ")
      : null;
    return [category, code].filter(Boolean).join(" – ") || "Übung";
  }

  function strengthNumber(value, digits = 1) {
    const number = Number(value);
    return value == null || !Number.isFinite(number) ? "–" : AppFormat.number(number, { digits: Number.isInteger(number) ? 0 : digits });
  }

  function strengthSeconds(value) {
    const seconds = Number(value);
    if (value == null || !Number.isFinite(seconds)) return "–";
    return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
  }

  // Reps, else the duration of a timed set.
  function strengthAmount(set) {
    if (set.reps != null) return strengthNumber(set.reps, 0);
    return strengthSeconds(set.duration_s);
  }

  function renderStrengthSets(strength, content) {
    if (!strength?.exercises?.length) return;
    content.append(h("h3", null, "Kraftsätze"));
    const sets = Number(strength.active_sets) || 0;
    content.append(h("p", "muted", [
      `${sets} ${sets === 1 ? "Satz" : "Sätze"}`,
      strength.total_reps != null ? `${strength.total_reps} Wdh.` : null,
      strength.volume_kg != null ? `${strengthNumber(strength.volume_kg)} kg Volumen` : null,
      STRENGTH_SOURCES[strength.source],
    ].filter(Boolean).join(" · ")));
    const tableWrap = makeScrollRegionFocusable(h("div", "analysis-chart-table"), "Kraftsätze");
    const grid = h("table", null, h("caption", null, "Ausgeführte Sätze je Übung"),
      h("thead", null, h("tr", null, ["Übung", "Satz", "Wdh. / Dauer", "kg", "Pause"].map((label) => h("th", { scope: "col" }, label)))));
    strength.exercises.forEach((exercise) => {
      const setList = Array.isArray(exercise.set_list) ? exercise.set_list : [];
      // One row group per exercise, so its header covers exactly its own sets.
      const body = h("tbody");
      setList.forEach((set, index) => {
        const row = h("tr");
        if (index === 0) {
          // One header per exercise spans its sets, so every set row keeps its exercise.
          row.append(h("th", { scope: "rowgroup", rowSpan: setList.length }, strengthExerciseLabel(exercise)));
        }
        row.append(h("td", null, String(index + 1)), h("td", null, strengthAmount(set)), h("td", null, strengthNumber(set.weight_kg)), h("td", null, strengthSeconds(set.rest_s)));
        body.append(row);
      });
      grid.append(body);
    });
    tableWrap.append(grid); content.append(tableWrap);
    const omitted = Number(strength.omitted_exercises) || 0;
    if (omitted) content.append(h("p", "muted", `${omitted} weitere ${omitted === 1 ? "Übung" : "Übungen"} nicht angezeigt.`));
  }

  function renderIntervalQuality(payload, content) {
    const quality = payload.analysis?.interval_quality;
    if (quality) {
      content.append(h("h3", null, "Trainingsqualität"));
      if (quality.reason) content.append(h("p", null, quality.reason));
      if (quality.steps?.length) {
        content.append(h("p", null, `${quality.aligned_steps}/${quality.planned_steps} Schritte zugeordnet · ${quality.missing_steps} fehlen`));
        const list = h("ol", "activity-laps");
        quality.steps.forEach((step) => list.append(h("li", null, step.status === "ok"
          ? `${step.target}: ${step.mean} ${step.unit} · ${step.seconds_in_target} s im Ziel · Abweichung ${step.average_deviation_percent}% · Abdeckung ${Math.round(step.coverage * 100)}%`
          : `${step.target}: ${step.reason || "Messabdeckung unzureichend"}`)));
        content.append(list);
        quality.repeat_groups?.forEach((group) => content.append(h("p", null, `${group.target}: ${group.repetitions} vergleichbare Wiederholungen · Abfall ${group.fade_percent}%`)));
      }
      content.append(h("p", "muted", "Einzelziele verwenden ±5%; vorgegebene Bereiche bleiben unverändert. Ziele stammen aus der ersten Detailabfrage. Frühere Vorlagenänderungen sind nicht rekonstruierbar."));
    }
  }


  function renderAerobic(payload, content) {
    const aerobic = payload.analysis?.aerobic;
    if (aerobic) {
      content.append(h("h3", null, "Herzfrequenzdrift", " ", createEstimateChip()));
      let description = aerobic.reason;
      if (aerobic.status === "ok") {
        const longSession = aerobic.long_session ? " · lange Einheit" : "";
        description = `Drift ${aerobic.drift_percent}% · gleichmäßige Leistung pro Schlag ${aerobic.efficiency} ${aerobic.unit}${longSession}`;
      }
      content.append(h("p", null, description));
      content.append(h("p", "muted", "Lokale Methode: zehn Minuten Aufwärmen ausgeschlossen, danach zwei gleich lange Hälften bei gleichmäßiger Belastung und mindestens 85% Messabdeckung. Temperatur, Gelände und Indoor/Outdoor beeinflussen den Vergleich; keine pauschale Fitnessbewertung."));
    }
  }


  function renderPower(payload, content) {
    const power = payload.analysis?.power_profile;
    if (power) {
      content.append(h("h3", null, "Beobachtete Bestleistung"));
      for (const point of power.points || []) {
        const duration = point.duration_seconds < 60 ? `${point.duration_seconds} s` : `${point.duration_seconds / 60} min`;
        const measurement = point.watts == null ? "keine lückenlose Messung" : `${point.watts} W`;
        content.append(h("p", null, `${duration}: ${measurement}`));
      }
      content.append(h("p", "muted", "Zeitgewichtete Mittelwerte aus den Originaldaten dieser Aufzeichnung. Keine FTP-, Critical-Power- oder W′-Schätzung; Nullleistung zählt, Sensorausfälle und Stopps unterbrechen das Fenster."));
    }
  }

  async function open(activity, { api, showDialog }) {
    close(false);
    const activityId = String(activity.id ?? activity.activity_id ?? "");
    if (!activityId) return;
    const token = ++generation;
    const navigationState = { ...history.state };
    delete navigationState.activityDetail;
    history.replaceState(navigationState, "", location.href);
    history.pushState({ ...navigationState, activityDetail: activityId }, "", location.href);
    dialog = h("dialog", { className: "activity-detail-dialog", "aria-labelledby": "activityDetailTitle" });
    const title = h("h2", { id: "activityDetailTitle" }, activity.name || "Aktivitätsdetails");
    const back = h("button", { className: "secondary-button", type: "button" }, "Zurück zum Kalender");
    back.addEventListener("click", close);
    const content = h("div");
    const status = h("p", "muted", "Lokale Daten werden geladen …");
    status.setAttribute("role", "status");
    const actions = h("div");
    dialog.append(back, title, content, status, actions);
    document.body.append(dialog);
    const currentDialog = dialog;
    currentDialog.addEventListener("cancel", (event) => { event.preventDefault(); close(); });
    const returnFocus = document.activeElement;
    dialog.addEventListener("close", () => {
      if (token === generation) generation += 1;
      currentDialog.remove();
      if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    }, { once: true });
    showDialog(currentDialog, back);
    const isCurrent = () => token === generation;
    async function load(notice) {
      const payload = await api(`/api/activities/${encodeURIComponent(activityId)}`);
      if (!isCurrent()) return;
      render(payload, content, api, activityId, load, notice);
      title.textContent = payload.session?.name || activity.name || "Aktivitätsdetails";
      status.textContent = "";
      actions.replaceChildren(refreshActions(payload, {
        api, isCurrent, onStatus: (text) => { status.textContent = text; }, onLoaded: () => load(), onSetup: () => close(false),
      }));
    }
    // A deleted activity keeps only its receipt: its provider actions go away.
    load.deleted = () => { actions.replaceChildren(); status.textContent = ""; };
    try { await load(); } catch (error) { if (isCurrent()) status.textContent = error.message; }
  }

  // Runs the explicit detail job of one provider; resolves false when the caller is no longer current.
  async function requestDetails(activityId, { provider, api, isCurrent = () => true, onStatus = () => {} }) {
    let job = await api("/api/sync/jobs", { method: "POST", body: JSON.stringify({ provider, type: "activity_details", payload: { activity_id: activityId } }) });
    const deadline = Date.now() + 120_000;
    while (!["completed", "failed", "partial"].includes(job.status)) {
      if (!isCurrent()) return false;
      if (Date.now() >= deadline) throw new Error("Der Job läuft weiter. Öffne die Aktivität später erneut oder prüfe Mehr → Anbindungen.");
      onStatus("Detaildaten werden im Hintergrund geladen …");
      await new Promise((resolve) => setTimeout(resolve, 1500));
      if (!isCurrent()) return false;
      job = await api(`/api/sync/jobs/${encodeURIComponent(job.id)}`);
    }
    if (job.status !== "completed") throw new Error("Detaildaten konnten nicht vollständig geladen werden. Der vorherige Stand bleibt erhalten. Details stehen unter Mehr → Anbindungen.");
    return isCurrent();
  }

  function close(navigateBack = true) {
    generation += 1;
    if (dialog?.open) dialog.close();
    dialog?.remove();
    dialog = null;
    if (navigateBack && history.state?.activityDetail) history.back();
  }

  globalThis.addEventListener("popstate", () => { if (dialog) close(false); });

  globalThis.ActivityDetails = { open, close, requestDetails, cadenceDisplay, metricValues, runningDynamics, RUNNING_DYNAMICS, formDriftLines, providerNotes, refreshActions };
})();
