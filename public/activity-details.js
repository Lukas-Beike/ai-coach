/* Local activity view. Provider reads require an explicit durable refresh job. */
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

  function chart(streams, key, label, unit) {
    const times = streams.time;
    const values = streams[key];
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
    const tableWrap = node("div", null, "analysis-chart-table"); const table = node("table");
    table.append(node("caption", `${label} in ${unit}; fehlende Werte sind als Lücke markiert.`));
    const thead = node("thead"); const heading = node("tr"); ["Zeit", label].forEach((value) => { const cell = node("th", value); cell.scope = "col"; heading.append(cell); }); thead.append(heading); table.append(thead);
    const body = node("tbody");
    times.forEach((time, index) => { if (typeof time !== "number" || !Number.isFinite(time)) { return; }
      const row = node("tr"); const timeCell = node("th", `${Math.floor(time / 60)}:${String(Math.floor(time % 60)).padStart(2, "0")}`); timeCell.scope = "row"; row.append(timeCell); const value = values[index]; row.append(node("td", typeof value === "number" && Number.isFinite(value) ? `${value.toLocaleString("de-DE", { maximumFractionDigits: 2 })} ${unit}` : "Lücke")); body.append(row); });
    table.append(body); tableWrap.append(table); details.append(tableWrap); section.append(details);
    return section;
  }

  function render(payload, content, api, activityId) {
    content.replaceChildren();
    const activity = payload.activity || {};
    const metadata = payload.detail_data || {};
    renderMetadata(activity, metadata, content);
    renderSeries(activity, content);
    renderLaps(activity, content);
    renderIntervalQuality(payload, content);
    renderAerobic(payload, content);
    renderPower(payload, content);
    for (const item of payload.equipment || []) content.append(node("p", `Ausrüstung: ${item.name} · ${item.usage.distance_km} km${item.usage.maintenance_due ? " · persönliches Wartungsintervall erreicht" : ""}`));
    renderFeedback(payload.activity_feedback, payload.activity, api, activityId, content);
  }

  function renderFeedback(feedback, activity, api, activityId, content) {
    const section = node("section", null, "activity-feedback"); section.append(node("h3", "Dein Feedback"));
    const form = document.createElement("form"); form.className = "activity-feedback-form";
    const rpeLabel = node("label", "Session-RPE (0–10)"); const rpe = document.createElement("input"); rpe.name = "session_rpe"; rpe.type = "number"; rpe.min = "0"; rpe.max = "10"; rpe.step = "0.5"; rpe.inputMode = "decimal"; rpe.value = feedback?.session_rpe ?? ""; rpeLabel.append(rpe);
    const reasonLabel = node("label", "Abweichungsgrund"); const reason = document.createElement("input"); reason.name = "deviation_reason"; reason.maxLength = 500; reason.value = feedback?.deviation_reason || ""; reasonLabel.append(reason);
    const notesLabel = node("label", "Notizen"); const notes = document.createElement("textarea"); notes.name = "notes"; notes.rows = 3; notes.maxLength = 4000; notes.value = feedback?.notes || ""; notesLabel.append(notes);
    const status = node("p", "", "muted"); status.setAttribute("role", "status"); const save = node("button", "Feedback speichern"); save.type = "submit";
    form.append(rpeLabel, reasonLabel, notesLabel, save); section.append(form, status); content.append(section);
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); save.disabled = true; status.textContent = "Speichere …";
      try {
        const raw = rpe.value.trim(); const value = { activity_name: activity?.name || "", activity_date: String(activity?.start_date_local || "").slice(0, 40), notes: notes.value, deviation_reason: reason.value, session_rpe: raw === "" ? null : Number(raw) };
        if (raw !== "" && (!Number.isFinite(value.session_rpe) || value.session_rpe < 0 || value.session_rpe > 10)) throw new Error("RPE muss zwischen 0 und 10 liegen.");
        const result = await api(`/api/activities/${encodeURIComponent(activityId)}/feedback`, { method: "POST", body: JSON.stringify(value) });
        status.textContent = result.activity_feedback ? "Feedback gespeichert." : "Feedback entfernt.";
      } catch (error) { status.textContent = error.message; } finally { save.disabled = false; }
    });
  }


  function renderMetadata(activity, metadata, content) {
    const values = [
      activity.type,
      activity.start_date_local?.replace("T", " "),
      activity.moving_time != null ? `${Math.round(activity.moving_time / 60)} min` : null,
      AppFormat.distance(activity.distance),
      activity.icu_training_load != null ? `Belastung ${activity.icu_training_load}` : null,
    ].filter(Boolean);
    content.append(node("p", values.join(" · ")));
    let description = "Zusammenfassung aus dem lokalen Snapshot. Detaildaten wurden noch nicht geladen.";
    if (metadata.observed_at) {
      const sampled = metadata.display_sampled ? " \u00b7 Diagramme vereinfacht dargestellt" : "";
      description = `${metadata.source} \u00b7 Detaildaten geladen: ${new Date(metadata.observed_at).toLocaleString("de-DE")}${sampled}`;
    }
    content.append(node("p", description, "muted"));
    if (metadata.stale) content.append(node("p", "Die Zusammenfassung hat sich seit dem Laden geändert. Aktualisiere die Detaildaten vor einer neuen Bewertung.", "muted"));
    const channels = Object.entries(metadata.coverage || {}).map(([name, coverage]) => `${name}: ${coverage.valid_points}/${coverage.points} Messwerte`);
    if (channels.length) content.append(node("p", `Datenabdeckung · ${channels.join(" · ")}`, "muted"));
  }


  function renderSeries(activity, content) {
    let charts = 0;
    const labels = { watts: ["Leistung", "W"], power: ["Leistung", "W"], heartrate: ["Herzfrequenz", "bpm"], velocity_smooth: ["Geschwindigkeit", "m/s"], velocity: ["Geschwindigkeit", "m/s"], speed: ["Geschwindigkeit", "m/s"], altitude: ["Höhe", "m"], distance: ["Distanz", "m"], grade: ["Steigung", "%"], grade_smooth: ["Steigung geglättet", "%"], pace: ["Pace", "s/km"], cadence: ["Kadenz", "rpm"], temperature: ["Temperatur", "°C"] };
    const streams = activity.streams || {};
    const preferred = new Set(["watts", "power", "heartrate", "velocity_smooth", "velocity", "speed", "altitude", "distance", "grade_smooth", "grade", "pace", "cadence", "temperature"]);
    const channels = Object.keys(labels).filter((key) => preferred.has(key) && Array.isArray(streams[key]) && !(key === "speed" && (streams.velocity_smooth || streams.velocity)) && !(key === "velocity" && streams.velocity_smooth) && !(key === "grade" && streams.grade_smooth) && !(key === "power" && streams.watts));
    for (const key of channels) {
      const [label, unit] = labels[key];
      const series = chart(activity.streams || {}, key, label, unit);
      if (series) { content.append(series); charts += 1; }
    }
    if (!charts) content.append(node("p", "Keine darstellbaren Messreihen vorhanden. Fehlende Sensorwerte werden nicht als Null interpretiert."));
  }


  function renderLaps(activity, content) {
    if (activity.laps?.length) {
      content.append(node("h3", "Intervalle / Runden"));
      const list = node("ol", null, "activity-laps");
      activity.laps.forEach((lap, index) => list.append(node("li", [
        lap.name || `Intervall ${index + 1}`,
        lap.moving_time != null ? `${Math.round(lap.moving_time)} s` : null,
        lap.average_watts != null ? `${Math.round(lap.average_watts)} W` : null,
        lap.average_heartrate != null ? `${Math.round(lap.average_heartrate)} bpm` : null,
      ].filter(Boolean).join(" · "))));
      content.append(list);
    }
  }


  function renderIntervalQuality(payload, content) {
    const quality = payload.session_analysis?.interval_quality;
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
    const aerobic = payload.session_analysis?.aerobic;
    if (aerobic) {
      content.append(node("h3", "Aerobe Effizienz"));
      if (aerobic.provider_decoupling?.value != null) content.append(node("p", `Intervals.icu Decoupling: ${aerobic.provider_decoupling.value}% (Anbieterberechnung)`));
      let description = aerobic.reason;
      if (aerobic.status === "ok") {
        const longSession = aerobic.long_session ? " \u00b7 lange Einheit" : "";
        description = `${aerobic.efficiency} ${aerobic.unit} \u00b7 lokale Herzfrequenzdrift ${aerobic.drift_percent}%${longSession}`;
      }
      content.append(node("p", description));
      content.append(node("p", "Lokale Methode: zehn Minuten Aufwärmen ausgeschlossen, danach zwei gleich lange Hälften bei gleichmäßiger Belastung und mindestens 85% Messabdeckung. Temperatur, Gelände und Indoor/Outdoor beeinflussen den Vergleich; keine pauschale Fitnessbewertung.", "muted"));
    }
  }


  function renderPower(payload, content) {
    const power = payload.session_analysis?.power_profile;
    if (power) {
      content.append(node("h3", "Beobachtete Bestleistung"));
      for (const point of power.points || []) {
        const duration = point.duration_seconds < 60 ? `${point.duration_seconds} s` : `${point.duration_seconds / 60} min`;
        const measurement = point.watts == null ? "keine l\u00fcckenlose Messung" : `${point.watts} W`;
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
    const actions = node("div", null, "dialog-actions");
    const setupHint = node("p", "Intervals.icu ist nicht konfiguriert. ", "muted provider-setup-hint");
    const setupLink = node("a", "Anbindung einrichten");
    setupLink.href = "#more/connections";
    setupLink.addEventListener("click", () => close(false));
    setupHint.append(setupLink);
    const refresh = node("button", "Detaildaten laden", "secondary-button");
    refresh.type = "button";
    // Detail jobs read Intervals.icu only, so they are offered for Intervals.icu
    // activities and need a configured Intervals.icu connection.
    const detailsAvailable = isIntervalsActivity(activity);
    const canRefresh = () => Boolean(state.data?.configured?.intervals);
    refresh.disabled = !canRefresh();
    setupHint.hidden = canRefresh();
    if (detailsAvailable) actions.append(refresh, setupHint);
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
    async function load() {
      const payload = await api(`/api/activities/${encodeURIComponent(activityId)}`);
      if (token !== generation) return;
      render(payload, content, api, activityId);
      title.textContent = payload.activity?.name || activity.name || "Aktivitätsdetails";
      refresh.textContent = payload.detail_data?.observed_at ? "Detaildaten aktualisieren" : "Detaildaten laden";
      status.textContent = "";
    }
    refresh.addEventListener("click", async () => {
      refresh.disabled = true;
      status.textContent = "Ladejob wird gestartet …";
      try {
        let job = await api("/api/sync/jobs", { method: "POST", body: JSON.stringify({ provider: "intervals", type: "activity_details", payload: { activity_id: activityId } }) });
        const deadline = Date.now() + 120_000;
        while (!["completed", "failed", "partial"].includes(job.status)) {
          if (token !== generation) return;
          if (Date.now() >= deadline) throw new Error("Der Job läuft weiter. Öffne die Aktivität später erneut oder prüfe den Sync-Status unter Mehr.");
          status.textContent = "Detaildaten werden im Hintergrund geladen …";
          await new Promise((resolve) => setTimeout(resolve, 1500));
          if (token !== generation) return;
          job = await api(`/api/sync/jobs/${encodeURIComponent(job.id)}`);
        }
        if (job.status !== "completed") throw new Error("Detaildaten konnten nicht vollständig geladen werden. Der vorherige Stand bleibt erhalten. Details stehen im Sync-Status unter Mehr.");
        await load();
      } catch (error) {
        if (token === generation) status.textContent = error.message;
      } finally {
        if (token === generation) refresh.disabled = !canRefresh();
      }
    });
    try { await load(); } catch (error) { if (token === generation) status.textContent = error.message; }
  }

  function isIntervalsActivity(activity) {
    // Intervals.icu rows keep their device origin (for example "GARMIN") in
    // `source`, so only an explicit provider field marks a non-Intervals record.
    const provider = String(activity?.provider ?? "intervals").trim().toLowerCase();
    return provider === "intervals" || provider === "intervals.icu";
  }

  function close(navigateBack = true) {
    generation += 1;
    if (dialog?.open) dialog.close();
    dialog?.remove();
    dialog = null;
    if (navigateBack && history.state?.activityDetail) history.back();
  }

  globalThis.addEventListener("popstate", () => { if (dialog) close(false); });

  globalThis.ActivityDetails = { open, close };
})();
