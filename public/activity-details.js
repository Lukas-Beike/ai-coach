/* Local activity view of the served activity_detail.v1 document. Provider reads require an explicit durable refresh job. */
(() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  let dialog;
  let generation = 0;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function chart(times, values, label, unit) {
    if (!Array.isArray(times) || !Array.isArray(values) || times.length !== values.length) return null;
    const points = times.map((time, index) => [time, values[index]])
      .filter(([time, value]) => typeof time === "number" && typeof value === "number" && Number.isFinite(time) && Number.isFinite(value));
    if (points.length < 2) return null;
    const section = node("section", null, "activity-series");
    section.append(node("h3", `${label} (${unit})`));
    const svg = document.createElementNS(SVG_NS, "svg");
    const width = 680; const height = 220; const left = 64; const right = 12; const top = 16; const bottom = 34;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${label}, Zeitachse in Minuten; Messwerte und Lücken sind in der Tabelle aufgeführt`);
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
      const line = document.createElementNS(SVG_NS, "line"); line.setAttribute("x1", String(left)); line.setAttribute("x2", String(width - right)); line.setAttribute("y1", String(y(value))); line.setAttribute("y2", String(y(value))); line.setAttribute("class", "activity-gridline"); svg.append(line);
      const tick = document.createElementNS(SVG_NS, "text"); tick.setAttribute("x", String(left - 8)); tick.setAttribute("y", String(y(value) + 4)); tick.setAttribute("text-anchor", "end"); tick.textContent = Number(value).toLocaleString("de-DE", { maximumFractionDigits: 1 }); svg.append(tick);
    });
    const xTicks = [start, start + duration / 2, points.at(-1)[0]];
    xTicks.forEach((time) => { const tick = document.createElementNS(SVG_NS, "text"); tick.setAttribute("x", String(x(time))); tick.setAttribute("y", String(height - 8)); tick.setAttribute("text-anchor", "middle"); tick.textContent = `${Math.round(time / 60)} min`; svg.append(tick); });
    const path = document.createElementNS(SVG_NS, "path");
    let continuing = false;
    path.setAttribute("d", times.map((time, index) => {
      const value = values[index];
      if (typeof time !== "number" || typeof value !== "number" || !Number.isFinite(time) || !Number.isFinite(value)) { continuing = false; return ""; }
      const command = continuing ? "L" : "M";
      continuing = true;
      return `${command}${x(time).toFixed(1)},${y(value).toFixed(1)}`;
    }).join(" "));
    svg.append(path);
    section.append(svg, node("p", `${Math.round(min * 10) / 10}–${Math.round(max * 10) / 10} ${unit} · ${Math.round(start / 60)}–${Math.round(points.at(-1)[0] / 60)} min · ${times.length - points.length} fehlende Messpunkte`, "muted"));
    const details = node("details", null, "activity-values"); details.append(node("summary", `Alle ${points.length} Messwerte ansehen`));
    const tableWrap = makeScrollRegionFocusable(node("div", null, "analysis-chart-table"), `${label} in ${unit}: Messwerte`); const table = node("table");
    table.append(node("caption", `${label} in ${unit}; fehlende Werte sind als Lücke markiert.`));
    const thead = node("thead"); const heading = node("tr"); ["Zeit", label].forEach((value) => { const cell = node("th", value); cell.scope = "col"; heading.append(cell); }); thead.append(heading); table.append(thead);
    const body = node("tbody");
    times.forEach((time, index) => { if (typeof time !== "number" || !Number.isFinite(time)) { return; }
      const row = node("tr"); const timeCell = node("th", `${Math.floor(time / 60)}:${String(Math.floor(time % 60)).padStart(2, "0")}`); timeCell.scope = "row"; row.append(timeCell); const value = values[index]; row.append(node("td", typeof value === "number" && Number.isFinite(value) ? `${value.toLocaleString("de-DE", { maximumFractionDigits: 2 })} ${unit}` : "Lücke")); body.append(row); });
    table.append(body); tableWrap.append(table); details.append(tableWrap); section.append(details);
    return section;
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
    for (const item of payload.equipment || []) content.append(node("p", `Ausrüstung: ${item.name} · ${item.usage.distance_km} km${item.usage.maintenance_due ? " · persönliches Wartungsintervall erreicht" : ""}`));
    renderBundle(payload.session_bundle, api, content, reload, notice);
    renderFeedback(payload.activity_feedback, session, api, activityId, content, payload.session_rpe_load);
  }

  // CR-10 anchors after Foster et al. 2001; the other steps have no verbal anchor.
  const RPE_ANCHORS = { 0: "Ruhe", 1: "Sehr, sehr leicht", 2: "Leicht", 3: "Moderat", 4: "Etwas schwer", 5: "Schwer", 7: "Sehr schwer", 10: "Maximal" };

  function rpeOption(value) {
    const anchor = RPE_ANCHORS[value];
    const number = value.toLocaleString("de-DE");
    const option = node("option", anchor ? `${number} · ${anchor}` : number);
    option.value = String(value);
    return option;
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
    const select = document.createElement("select"); select.name = "session_rpe";
    const empty = node("option", "Keine Angabe"); empty.value = ""; select.append(empty);
    for (let step = 0; step <= 20; step += 1) select.append(rpeOption(step / 2));
    setRpe(select, value);
    return select;
  }

  // The athlete's own marking wins over Garmin's event type and a competition hint; "" removes it.
  const PURPOSES = [["training", "Training"], ["race", "Wettkampf"], ["commute", "Pendeln"], ["warmup", "Einfahren"], ["cooldown", "Ausfahren"]];

  function purposeSelect(marked, detected) {
    const select = document.createElement("select"); select.name = "purpose";
    const detectedLabel = PURPOSES.find(([key]) => key === detected)?.[1];
    const automatic = node("option", !marked && detectedLabel ? `Automatisch · ${detectedLabel}` : "Automatisch"); automatic.value = ""; select.append(automatic);
    for (const [key, label] of PURPOSES) { const option = node("option", label); option.value = key; select.append(option); }
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
    const section = node("section", null, "activity-feedback"); section.append(node("h3", "Dein Feedback"));
    const form = document.createElement("form"); form.className = "activity-feedback-form";
    const purposeLabel = node("label", "Art der Einheit"); const purpose = purposeSelect(feedback?.purpose, session?.purpose); purposeLabel.append(purpose);
    const rpeLabel = node("label", "Session-RPE (0–10)"); const rpe = rpeSelect(feedback?.session_rpe); rpeLabel.append(rpe);
    const reasonLabel = node("label", "Abweichungsgrund"); const reason = document.createElement("input"); reason.name = "deviation_reason"; reason.maxLength = 500; reason.value = feedback?.deviation_reason || ""; reasonLabel.append(reason);
    const notesLabel = node("label", "Notizen"); const notes = document.createElement("textarea"); notes.name = "notes"; notes.rows = 3; notes.maxLength = 4000; notes.value = feedback?.notes || ""; notesLabel.append(notes);
    const status = node("p", "", "muted"); status.setAttribute("role", "status"); const save = node("button", "Feedback speichern"); save.type = "submit";
    const load = node("p"); load.dataset.sessionRpeLoad = "";
    const showLoad = (value) => { load.textContent = sessionLoadText(value); load.hidden = !load.textContent; };
    showLoad(sessionLoad);
    form.append(purposeLabel, rpeLabel, reasonLabel, notesLabel, save); section.append(load, form, status); content.append(section);
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
    const section = node("section", null, "activity-bundle"); section.append(node("h3", "Aufzeichnungen"));
    const status = node("p", notice?.text || "", "muted"); status.setAttribute("role", "status");
    const buttons = [];
    const action = (label, body, done) => {
      const button = node("button", label, "secondary-button"); button.type = "button"; buttons.push(button);
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
      const items = node("ul", null, "activity-bundle-list");
      for (const entry of entries) {
        const item = node("li", recordingText(entry));
        if (label) { item.append(" ", action(label, body(entry), done)); }
        items.append(item);
      }
      return items;
    };
    const several = members.length > 1;
    section.append(list(members, several ? "Trennen" : null, (entry) => ({ action: "split", member_id: entry.session_id }), "Aufzeichnung getrennt. "));
    if (several && !bundle.athlete_confirmed) section.append(action("Zuordnung bestätigen", { action: "confirm" }, "Zuordnung bestätigt. "));
    if (candidates.length) { section.append(node("h4", "Am selben Tag")); section.append(list(candidates, "Zusammenführen", (entry) => ({ action: "merge", other_id: entry.session_id }), "Aktivitäten zusammengeführt. ")); }
    if (notice?.change?.id) status.append(undoButton(api, notice.change, status, reload));
    const remove = node("button", "Aktivität löschen", "secondary-button"); remove.type = "button"; buttons.push(remove);
    remove.addEventListener("click", async () => {
      const confirmed = await requestConfirmation("Diese Aktivität mit allen Aufzeichnungen lokal löschen? Bei den Anbietern bleibt sie erhalten.", { title: "Aktivität löschen?", confirmLabel: "Löschen" });
      if (!confirmed) return;
      buttons.forEach((item) => { item.disabled = true; }); status.textContent = "Speichere …";
      try {
        const result = await api(`/api/activities/${encodeURIComponent(bundle.activity_id)}/session`, { method: "POST", body: JSON.stringify({ action: "delete", confirmed: true }) });
        const deleted = node("p", "Aktivität gelöscht. ", "muted"); deleted.setAttribute("role", "status");
        if (result.change?.id) deleted.append(undoButton(api, result.change, deleted, reload));
        content.replaceChildren(deleted); reload.deleted?.();
      } catch (error) { buttons.forEach((item) => { item.disabled = false; }); status.textContent = error.message; }
    });
    section.append(remove);
    section.append(status); content.append(section);
  }

  // Undo of a session correction restores the touched sessions, then the detail reloads.
  function undoButton(api, change, status, reload) {
    const undo = node("button", "Rückgängig", "message-undo"); undo.type = "button";
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
    const undo = node("button", "Rückgängig", "message-undo"); undo.type = "button";
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
    const duration = metrics.moving_duration_s ?? metrics.duration_s;
    const values = [
      session.sport ? activitySportLabel(session) : null,
      session.started_at ? formatTime(session.started_at) : null,
      duration != null ? `${Math.round(duration / 60)} min` : null,
      AppFormat.distance(metrics.distance_m),
      metrics.load != null ? `Belastung ${metrics.load}` : null,
    ].filter(Boolean);
    content.append(node("p", values.join(" · ")));
  }

  // The recognised route of the session as "label, n. Mal"; the athlete can rename it.
  function renderRoute(route, api, content) {
    if (!route) return;
    const line = node("p");
    let label = route.label;
    const show = () => {
      const rename = node("button", "Umbenennen", "secondary-button"); rename.type = "button";
      rename.addEventListener("click", edit);
      line.replaceChildren(`${label}, ${route.repeat_index}. Mal `, rename);
    };
    const edit = () => {
      const form = document.createElement("form");
      const input = document.createElement("input"); input.maxLength = 60; input.required = true; input.value = label; input.setAttribute("aria-label", "Streckenname");
      const save = node("button", "Speichern"); save.type = "submit";
      const cancel = node("button", "Abbrechen", "secondary-button"); cancel.type = "button"; cancel.addEventListener("click", show);
      const status = node("span", null, "muted"); status.setAttribute("role", "status");
      form.addEventListener("submit", async (event) => {
        event.preventDefault(); save.disabled = true; status.textContent = "Speichere …";
        try {
          const result = await api("/api/routes/rename", { method: "POST", body: JSON.stringify({ route_id: route.route_id, name: input.value }) });
          label = result.label; show();
        } catch (error) { status.textContent = error.message; save.disabled = false; }
      });
      form.append(input, " ", save, " ", cancel, " ", status); line.replaceChildren(form); input.focus();
    };
    show(); content.append(line);
  }

  const COVERAGE_LABELS = { power_w: "Leistung", heart_rate_bpm: "Herzfrequenz", speed_mps: "Geschwindigkeit", altitude_m: "Höhe", distance_m: "Distanz", grade_pct: "Steigung", cadence_rpm: "Kadenz", temperature_c: "Temperatur" };

  // Per provider: the load state and the data coverage, with readable channel names.
  function providerFacts(entry) {
    const label = entry.label || entry.provider;
    const facts = [node("p", entry.fetched_at ? `${label} · Detaildaten geladen: ${formatTime(entry.fetched_at)}` : `${label} · Detaildaten wurden noch nicht geladen.`, "muted")];
    const coverage = Object.entries(entry.coverage || {}).map(([name, value]) => `${COVERAGE_LABELS[name] || name}: ${value?.valid_points} von ${value?.points}`);
    if (coverage.length) facts.push(node("p", `Datenabdeckung ${label} · ${coverage.join(" · ")} Messwerten`, "muted"));
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
      notes.push(node("p", loaded.length ? `Quelle: ${loaded.map((entry) => entry.label || entry.provider).join(", ")} · Stand ${formatTime(latest)}` : "Detaildaten noch nicht geladen", "muted"));
    }
    for (const entry of providers) {
      const label = entry.label || entry.provider;
      if (entry.stale) notes.push(node("p", `${label}: Die Zusammenfassung hat sich seit dem Laden geändert. Aktualisiere die Detaildaten vor einer neuen Bewertung.`, "muted"));
      if (entry.load_error?.message) notes.push(node("p", `${label}: ${entry.load_error.message} Automatischer Ladeversuch: ${formatTime(entry.load_error.observed_at)}`, "activity-analysis-error"));
      facts.push(...providerFacts(entry));
    }
    // The simplified-charts note changes how the charts read, so it stays outside the folded details.
    if (detail.display_sampled) notes.push(node("p", "Diagramme vereinfacht dargestellt", "muted"));
    if (facts.length) {
      const details = node("details", null, "provenance-details");
      details.append(node("summary", "Herkunft im Detail"), ...facts);
      notes.push(details);
    }
    return notes;
  }

  // One explicit detail load per provider entry the server marks refreshable.
  function refreshActions(payload, { api, isCurrent, onStatus, onLoaded, onSetup = () => {} }) {
    const actions = node("div", null, "dialog-actions");
    const activityId = String(payload?.session?.activity_id || "");
    for (const entry of payload?.detail_data?.providers || []) {
      const label = entry.label || entry.provider;
      if (!entry.refreshable || !activityId) {
        if (state.data?.configured?.[entry.provider] !== false) continue;
        const hint = node("p", `${label} ist nicht konfiguriert. `, "muted provider-setup-hint");
        const link = node("a", "Anbindung einrichten");
        link.href = "#more/connections";
        link.addEventListener("click", onSetup);
        hint.append(link);
        actions.append(hint);
        continue;
      }
      const button = node("button", `${label}: Detaildaten ${entry.fetched_at ? "aktualisieren" : "laden"}`, "secondary-button");
      button.type = "button";
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
    content.append(node("h3", "Laufdynamik"));
    if (dynamics.length) content.append(node("p", dynamics.map(([label, text]) => `${label} ${text}`).join(" · ")));
    for (const line of drift) content.append(node("p", line));
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
    if (!charts) content.append(node("p", "Keine darstellbaren Messreihen vorhanden. Fehlende Sensorwerte werden nicht als Null interpretiert."));
  }


  function renderLaps(laps, content) {
    if (laps?.laps?.length) {
      content.append(node("h3", "Intervalle / Runden"));
      const list = node("ol", null, "activity-laps");
      laps.laps.forEach((lap, index) => {
        const seconds = lap.moving_duration_s ?? lap.end_offset_s - lap.start_offset_s;
        list.append(node("li", [
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
    content.append(node("h3", "Kraftsätze"));
    const sets = Number(strength.active_sets) || 0;
    content.append(node("p", [
      `${sets} ${sets === 1 ? "Satz" : "Sätze"}`,
      strength.total_reps != null ? `${strength.total_reps} Wdh.` : null,
      strength.volume_kg != null ? `${strengthNumber(strength.volume_kg)} kg Volumen` : null,
      STRENGTH_SOURCES[strength.source],
    ].filter(Boolean).join(" · "), "muted"));
    const tableWrap = makeScrollRegionFocusable(node("div", null, "analysis-chart-table"), "Kraftsätze");
    const table = node("table");
    table.append(node("caption", "Ausgeführte Sätze je Übung"));
    const thead = node("thead"); const heading = node("tr");
    ["Übung", "Satz", "Wdh. / Dauer", "kg", "Pause"].forEach((label) => { const cell = node("th", label); cell.scope = "col"; heading.append(cell); });
    thead.append(heading); table.append(thead);
    strength.exercises.forEach((exercise) => {
      const setList = Array.isArray(exercise.set_list) ? exercise.set_list : [];
      // One row group per exercise, so its header covers exactly its own sets.
      const body = node("tbody");
      setList.forEach((set, index) => {
        const row = node("tr");
        if (index === 0) {
          // One header per exercise spans its sets, so every set row keeps its exercise.
          const nameCell = node("th", strengthExerciseLabel(exercise)); nameCell.scope = "rowgroup"; nameCell.rowSpan = setList.length; row.append(nameCell);
        }
        row.append(node("td", String(index + 1)), node("td", strengthAmount(set)), node("td", strengthNumber(set.weight_kg)), node("td", strengthSeconds(set.rest_s)));
        body.append(row);
      });
      table.append(body);
    });
    tableWrap.append(table); content.append(tableWrap);
    const omitted = Number(strength.omitted_exercises) || 0;
    if (omitted) content.append(node("p", `${omitted} weitere ${omitted === 1 ? "Übung" : "Übungen"} nicht angezeigt.`, "muted"));
  }

  function renderIntervalQuality(payload, content) {
    const quality = payload.analysis?.interval_quality;
    if (quality) {
      content.append(node("h3", "Trainingsqualität"));
      if (quality.reason) content.append(node("p", quality.reason));
      if (quality.steps?.length) {
        content.append(node("p", `${quality.aligned_steps}/${quality.planned_steps} Schritte zugeordnet · ${quality.missing_steps} fehlen`));
        const list = node("ol", null, "activity-laps");
        quality.steps.forEach((step) => list.append(node("li", step.status === "ok"
          ? `${step.target}: ${step.mean} ${step.unit} · ${step.seconds_in_target} s im Ziel · Abweichung ${step.average_deviation_percent}% · Abdeckung ${Math.round(step.coverage * 100)}%`
          : `${step.target}: ${step.reason || "Messabdeckung unzureichend"}`)));
        content.append(list);
        quality.repeat_groups?.forEach((group) => content.append(node("p", `${group.target}: ${group.repetitions} vergleichbare Wiederholungen · Abfall ${group.fade_percent}%`)));
      }
      content.append(node("p", "Einzelziele verwenden ±5%; vorgegebene Bereiche bleiben unverändert. Ziele stammen aus der ersten Detailabfrage. Frühere Vorlagenänderungen sind nicht rekonstruierbar.", "muted"));
    }
  }


  function renderAerobic(payload, content) {
    const aerobic = payload.analysis?.aerobic;
    if (aerobic) {
      const driftHeading = node("h3", "Herzfrequenzdrift");
      driftHeading.append(" ", createEstimateChip());
      content.append(driftHeading);
      let description = aerobic.reason;
      if (aerobic.status === "ok") {
        const longSession = aerobic.long_session ? " · lange Einheit" : "";
        description = `Drift ${aerobic.drift_percent}% · gleichmäßige Leistung pro Schlag ${aerobic.efficiency} ${aerobic.unit}${longSession}`;
      }
      content.append(node("p", description));
      content.append(node("p", "Lokale Methode: zehn Minuten Aufwärmen ausgeschlossen, danach zwei gleich lange Hälften bei gleichmäßiger Belastung und mindestens 85% Messabdeckung. Temperatur, Gelände und Indoor/Outdoor beeinflussen den Vergleich; keine pauschale Fitnessbewertung.", "muted"));
    }
  }


  function renderPower(payload, content) {
    const power = payload.analysis?.power_profile;
    if (power) {
      content.append(node("h3", "Beobachtete Bestleistung"));
      for (const point of power.points || []) {
        const duration = point.duration_seconds < 60 ? `${point.duration_seconds} s` : `${point.duration_seconds / 60} min`;
        const measurement = point.watts == null ? "keine lückenlose Messung" : `${point.watts} W`;
        content.append(node("p", `${duration}: ${measurement}`));
      }
      content.append(node("p", "Zeitgewichtete Mittelwerte aus den Originaldaten dieser Aufzeichnung. Keine FTP-, Critical-Power- oder W′-Schätzung; Nullleistung zählt, Sensorausfälle und Stopps unterbrechen das Fenster.", "muted"));
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
    dialog = node("dialog", null, "activity-detail-dialog");
    dialog.setAttribute("aria-labelledby", "activityDetailTitle");
    const title = node("h2", activity.name || "Aktivitätsdetails");
    title.id = "activityDetailTitle";
    const back = node("button", "Zurück zum Kalender", "secondary-button");
    back.type = "button";
    back.addEventListener("click", close);
    const content = node("div");
    const status = node("p", "Lokale Daten werden geladen …", "muted");
    status.setAttribute("role", "status");
    const actions = node("div");
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

  globalThis.ActivityDetails = { open, close, requestDetails, cadenceDisplay, metricValues, runningDynamics, formDriftLines, providerNotes, refreshActions };
})();
