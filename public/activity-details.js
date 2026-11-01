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
    const y = (value) => top + (max - value) / Math.max(1, max - min) * (height - top - bottom);
    const x = (time) => left + (time - start) / duration * (width - left - right);
    const ticks = max === min ? [min] : [max, (max + min) / 2, min];
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

  function render(payload, content, api, activityId) {
    content.replaceChildren();
    const session = payload.session || {};
    renderMetadata(session, metricValues(payload), content);
    content.append(...providerNotes(payload));
    renderSeries(session, payload.streams, content);
    renderLaps(payload.laps, content);
    renderIntervalQuality(payload, content);
    renderAerobic(payload, content);
    renderPower(payload, content);
    for (const item of payload.equipment || []) content.append(node("p", `Ausrüstung: ${item.name} · ${item.usage.distance_km} km${item.usage.maintenance_due ? " · persönliches Wartungsintervall erreicht" : ""}`));
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

  const SESSION_LOAD_REASONS = { no_rating: "kein RPE", conflicting_provider_ratings: "widersprüchliche Provider-RPE", no_elapsed_duration: "keine Gesamtdauer", invalid_duration: "ungültige Dauer" };

  function sessionLoadText(load) {
    if (!load || load.reason === "no_rating") return "";
    if (load.value == null) return `Session-RPE-Last: offen · ${SESSION_LOAD_REASONS[load.reason] || "unbekannt"}`;
    const value = Number(load.value).toLocaleString("de-DE", { maximumFractionDigits: 1 });
    const rpe = Number(load.rpe).toLocaleString("de-DE");
    const minutes = Number(load.duration_min).toLocaleString("de-DE", { maximumFractionDigits: 1 });
    return `Session-RPE-Last: ${value} AU · RPE ${rpe} (${load.rpe_source_label}) × ${minutes} min`;
  }

  function renderFeedback(feedback, session, api, activityId, content, sessionLoad) {
    const section = node("section", null, "activity-feedback"); section.append(node("h3", "Dein Feedback"));
    const form = document.createElement("form"); form.className = "activity-feedback-form";
    const rpeLabel = node("label", "Session-RPE (0–10)"); const rpe = rpeSelect(feedback?.session_rpe); rpeLabel.append(rpe);
    const reasonLabel = node("label", "Abweichungsgrund"); const reason = document.createElement("input"); reason.name = "deviation_reason"; reason.maxLength = 500; reason.value = feedback?.deviation_reason || ""; reasonLabel.append(reason);
    const notesLabel = node("label", "Notizen"); const notes = document.createElement("textarea"); notes.name = "notes"; notes.rows = 3; notes.maxLength = 4000; notes.value = feedback?.notes || ""; notesLabel.append(notes);
    const status = node("p", "", "muted"); status.setAttribute("role", "status"); const save = node("button", "Feedback speichern"); save.type = "submit";
    const load = node("p"); load.dataset.sessionRpeLoad = "";
    const showLoad = (value) => { load.textContent = sessionLoadText(value); load.hidden = !load.textContent; };
    showLoad(sessionLoad);
    form.append(rpeLabel, reasonLabel, notesLabel, save); section.append(load, form, status); content.append(section);
    let shown = feedback;
    const fill = (value) => { setRpe(rpe, value?.session_rpe); reason.value = value?.deviation_reason || ""; notes.value = value?.notes || ""; };
    // The served document recomputes the load from the saved feedback and its provider fallback.
    let loadGeneration = 0;
    // Only the newest refresh may write, so a slow save response cannot overwrite a later undo.
    const refreshLoad = async () => {
      const current = ++loadGeneration;
      try {
        const payload = await api(`/api/activities/${encodeURIComponent(activityId)}`);
        if (current === loadGeneration) showLoad(payload.session_rpe_load);
      } catch { /* the saved feedback stays shown */ }
    };
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); save.disabled = true; status.textContent = "Speichere …";
      try {
        const raw = rpe.value; const value = { activity_name: session?.name || "", activity_date: session?.started_at_local || "", notes: notes.value, deviation_reason: reason.value, session_rpe: raw === "" ? null : Number(raw) };
        if (raw !== "" && (!Number.isFinite(value.session_rpe) || value.session_rpe < 0 || value.session_rpe > 10)) throw new Error("RPE muss zwischen 0 und 10 liegen.");
        const result = await api(`/api/activities/${encodeURIComponent(activityId)}/feedback`, { method: "POST", body: JSON.stringify(value) });
        const previous = shown; shown = result.activity_feedback;
        status.textContent = result.activity_feedback ? "Feedback gespeichert. " : "Feedback entfernt. ";
        if (result.change?.id) status.append(feedbackUndoButton(api, result.change, status, () => { shown = previous; fill(previous); void refreshLoad(); }));
        void refreshLoad();
      } catch (error) { status.textContent = error.message; } finally { save.disabled = false; }
    });
  }

  // Undo restores the feedback rows as they were before this save or removal.
  function feedbackUndoButton(api, change, status, restored) {
    const undo = node("button", "Rückgängig", "message-undo"); undo.type = "button";
    undo.addEventListener("click", async () => {
      undo.disabled = true;
      try {
        await api("/api/change-history/undo", { method: "POST", body: JSON.stringify({ change_id: change.id, expected_current_hash: change.after_hash }) });
        restored(); status.textContent = "Zurückgenommen.";
      } catch (error) { undo.disabled = false; status.textContent = error.message; }
    });
    return undo;
  }


  function renderMetadata(session, metrics, content) {
    const duration = metrics.moving_duration_s ?? metrics.duration_s;
    const values = [
      session.sport ? activitySportLabel({ type: session.sport }) : null,
      session.started_at ? formatTime(session.started_at) : null,
      duration != null ? `${Math.round(duration / 60)} min` : null,
      AppFormat.distance(metrics.distance_m),
      metrics.load != null ? `Belastung ${metrics.load}` : null,
    ].filter(Boolean);
    content.append(node("p", values.join(" · ")));
  }

  // Each contributing provider reports its own load state; provider text is shown as plain text only.
  function providerNotes(payload) {
    const detail = payload?.detail_data || {};
    const notes = [];
    for (const entry of detail.providers || []) {
      const label = entry.label || entry.provider;
      notes.push(node("p", entry.fetched_at ? `${label} · Detaildaten geladen: ${formatTime(entry.fetched_at)}` : `${label} · Detaildaten wurden noch nicht geladen.`, "muted"));
      if (entry.stale) notes.push(node("p", `${label}: Die Zusammenfassung hat sich seit dem Laden geändert. Aktualisiere die Detaildaten vor einer neuen Bewertung.`, "muted"));
      if (entry.load_error?.message) notes.push(node("p", `${label}: ${entry.load_error.message} Automatischer Ladeversuch: ${formatTime(entry.load_error.observed_at)}`, "activity-analysis-error"));
      const coverage = Object.entries(entry.coverage || {}).map(([name, value]) => `${name}: ${value?.valid_points}/${value?.points} Messwerte`);
      if (coverage.length) notes.push(node("p", `Datenabdeckung ${label} · ${coverage.join(" · ")}`, "muted"));
    }
    if (detail.display_sampled) notes.push(node("p", "Diagramme vereinfacht dargestellt", "muted"));
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
    if (/run|walk|hike/i.test(String(activity?.type || ""))) return { label: "Schrittfrequenz", unit: "spm", factor: 2 };
    return { label: "Kadenz", unit: "rpm", factor: 1 };
  }

  function renderSeries(session, streams, content) {
    let charts = 0;
    const cadence = cadenceDisplay({ type: session.sport });
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
      content.append(node("h3", "Aerobe Effizienz"));
      const decoupling = aerobic.provider_decoupling;
      if (decoupling?.value != null) content.append(node("p", `${decoupling.source} Decoupling: ${decoupling.value}% (Anbieterberechnung)`));
      let description = aerobic.reason;
      if (aerobic.status === "ok") {
        const longSession = aerobic.long_session ? " · lange Einheit" : "";
        description = `${aerobic.efficiency} ${aerobic.unit} · lokale Herzfrequenzdrift ${aerobic.drift_percent}%${longSession}`;
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
    async function load() {
      const payload = await api(`/api/activities/${encodeURIComponent(activityId)}`);
      if (!isCurrent()) return;
      render(payload, content, api, activityId);
      title.textContent = payload.session?.name || activity.name || "Aktivitätsdetails";
      status.textContent = "";
      actions.replaceChildren(refreshActions(payload, {
        api, isCurrent, onStatus: (text) => { status.textContent = text; }, onLoaded: load, onSetup: () => close(false),
      }));
    }
    try { await load(); } catch (error) { if (isCurrent()) status.textContent = error.message; }
  }

  // Runs the explicit detail job of one provider; resolves false when the caller is no longer current.
  async function requestDetails(activityId, { provider, api, isCurrent = () => true, onStatus = () => {} }) {
    let job = await api("/api/sync/jobs", { method: "POST", body: JSON.stringify({ provider, type: "activity_details", payload: { activity_id: activityId } }) });
    const deadline = Date.now() + 120_000;
    while (!["completed", "failed", "partial"].includes(job.status)) {
      if (!isCurrent()) return false;
      if (Date.now() >= deadline) throw new Error("Der Job läuft weiter. Öffne die Aktivität später erneut oder prüfe den Sync-Status unter Mehr.");
      onStatus("Detaildaten werden im Hintergrund geladen …");
      await new Promise((resolve) => setTimeout(resolve, 1500));
      if (!isCurrent()) return false;
      job = await api(`/api/sync/jobs/${encodeURIComponent(job.id)}`);
    }
    if (job.status !== "completed") throw new Error("Detaildaten konnten nicht vollständig geladen werden. Der vorherige Stand bleibt erhalten. Details stehen im Sync-Status unter Mehr.");
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

  globalThis.ActivityDetails = { open, close, requestDetails, cadenceDisplay, metricValues, providerNotes, refreshActions };
})();
