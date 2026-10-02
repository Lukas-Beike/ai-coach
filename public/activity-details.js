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
    svg.setAttribute("viewBox", "0 0 640 160");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `${label}, Zeitachse in Minuten`);
    const min = Math.min(...points.map((point) => point[1]));
    const max = Math.max(...points.map((point) => point[1]));
    const start = points[0][0];
    const duration = Math.max(1, points.at(-1)[0] - start);
    const path = document.createElementNS(SVG_NS, "path");
    let continuing = false;
    path.setAttribute("d", times.map((time, index) => {
      const value = values[index];
      if (typeof time !== "number" || typeof value !== "number" || !Number.isFinite(time) || !Number.isFinite(value)) { continuing = false; return ""; }
      const command = continuing ? "L" : "M";
      continuing = true;
      return `${command}${(10 + (time - start) / duration * 620).toFixed(1)},${(130 - (value - min) / Math.max(1, max - min) * 115).toFixed(1)}`;
    }).join(" "));
    svg.append(path);
    section.append(svg, node("p", `${Math.round(min)}–${Math.round(max)} ${unit} · ${Math.round(start / 60)}–${Math.round(points.at(-1)[0] / 60)} min`, "muted"));
    return section;
  }

  function render(payload, content) {
    content.replaceChildren();
    const activity = payload.activity || {};
    const metadata = payload.detail_data || {};
    const values = [
      activity.type,
      activity.start_date_local?.replace("T", " "),
      activity.moving_time != null ? `${Math.round(activity.moving_time / 60)} min` : null,
      activity.distance != null ? `${(activity.distance / 1000).toFixed(1)} km` : null,
      activity.icu_training_load != null ? `Belastung ${activity.icu_training_load}` : null,
    ].filter(Boolean);
    content.append(node("p", values.join(" · ")));
    content.append(node("p", metadata.observed_at
      ? `${metadata.source} · Detaildaten geladen: ${new Date(metadata.observed_at).toLocaleString("de-DE")}${metadata.display_sampled ? " · Diagramme vereinfacht dargestellt" : ""}`
      : "Zusammenfassung aus dem lokalen Snapshot. Detaildaten wurden noch nicht geladen.", "muted"));
    if (metadata.stale) content.append(node("p", "Die Zusammenfassung hat sich seit dem Laden geändert. Aktualisiere die Detaildaten vor einer neuen Bewertung.", "muted"));
    const channels = Object.entries(metadata.coverage || {}).map(([name, coverage]) => `${name}: ${coverage.valid_points}/${coverage.points} Messwerte`);
    if (channels.length) content.append(node("p", `Datenabdeckung · ${channels.join(" · ")}`, "muted"));
    let charts = 0;
    for (const [key, label, unit] of [["watts", "Leistung", "W"], ["heartrate", "Herzfrequenz", "bpm"], ["velocity_smooth", "Geschwindigkeit", "m/s"], ["speed", "Geschwindigkeit", "m/s"], ["altitude", "Höhe", "m"], ["cadence", "Kadenz", "rpm"]]) {
      const series = chart(activity.streams || {}, key, label, unit);
      if (series) { content.append(series); charts += 1; }
    }
    if (!charts) content.append(node("p", "Keine darstellbaren Messreihen vorhanden. Fehlende Sensorwerte werden nicht als Null interpretiert."));
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
    const aerobic = payload.session_analysis?.aerobic;
    if (aerobic) {
      content.append(node("h3", "Aerobe Effizienz"));
      if (aerobic.provider_decoupling?.value != null) content.append(node("p", `Intervals.icu Decoupling: ${aerobic.provider_decoupling.value}% (Anbieterberechnung)`));
      content.append(node("p", aerobic.status === "ok"
        ? `${aerobic.efficiency} ${aerobic.unit} · lokale Herzfrequenzdrift ${aerobic.drift_percent}%${aerobic.long_session ? " · lange Einheit" : ""}`
        : aerobic.reason));
      content.append(node("p", "Lokale Methode: zehn Minuten Aufwärmen ausgeschlossen, danach zwei gleich lange Hälften bei gleichmäßiger Belastung und mindestens 85% Messabdeckung. Temperatur, Gelände und Indoor/Outdoor beeinflussen den Vergleich; keine pauschale Fitnessbewertung.", "muted"));
    }
    const power = payload.session_analysis?.power_profile;
    if (power) {
      content.append(node("h3", "Beobachtete Bestleistung"));
      for (const point of power.points || []) content.append(node("p", `${point.duration_seconds < 60 ? `${point.duration_seconds} s` : `${point.duration_seconds / 60} min`}: ${point.watts == null ? "keine lückenlose Messung" : `${point.watts} W`}`));
      content.append(node("p", "Zeitgewichtete Mittelwerte aus den Originaldaten dieser Aufzeichnung. Keine FTP-, Critical-Power- oder W′-Schätzung; Nullleistung zählt, Sensorausfälle und Stopps unterbrechen das Fenster.", "muted"));
    }
    const feedback = payload.activity_feedback;
    for (const item of payload.equipment || []) content.append(node("p", `Ausrüstung: ${item.name} · ${item.usage.distance_km} km${item.usage.maintenance_due ? " · persönliches Wartungsintervall erreicht" : ""}`));
    if (feedback && (feedback.notes || feedback.session_rpe != null || feedback.deviation_reason)) {
      content.append(node("h3", "Dein Feedback"));
      if (feedback.notes) content.append(node("p", feedback.notes));
      if (feedback.session_rpe != null) content.append(node("p", `Session-RPE: ${feedback.session_rpe}/10`));
      if (feedback.deviation_reason) content.append(node("p", feedback.deviation_reason));
    }
  }

  async function open(activity, { api, showDialog }) {
    close(false);
    const activityId = String(activity.id ?? activity.activity_id ?? "");
    if (!activityId) return;
    const token = ++generation;
    const navigationState = { ...(history.state || {}) };
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
    const refresh = node("button", "Detaildaten laden", "secondary-button");
    refresh.type = "button";
    const actions = node("div", null, "dialog-actions");
    actions.append(refresh);
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
      render(payload, content);
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
        if (token === generation) refresh.disabled = false;
      }
    });
    try { await load(); } catch (error) { if (token === generation) status.textContent = error.message; }
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
