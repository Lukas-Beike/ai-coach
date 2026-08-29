const $ = (selector) => document.querySelector(selector);
const state = { data: null, busy: false, profileDirty: false, localSync: { intervals: false, garmin: false, performance: false } };

function cookie(name) {
  return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
}

function showLogin() {
  state.data = null;
  $("#appShell").hidden = true;
  const dialog = $("#loginDialog");
  if (!dialog.open) dialog.showModal();
  $("#loginPassword").focus();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers: { "Content-Type": "application/json", ...(options.method && options.method !== "GET" ? { "X-CSRF-Token": cookie("ic_csrf") } : {}), ...(options.headers || {}) },
  });
  let payload = {};
  try { payload = await response.json(); } catch (_) {}
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(payload.error || `Anfrage fehlgeschlagen (${response.status})`);
  }
  return payload;
}

async function bootstrapAuth() {
  try {
    const response = await fetch("/api/auth/status", { credentials: "same-origin", cache: "no-store" });
    const status = await response.json();
    if (status.authenticated) {
      $("#loginDialog").close();
      $("#appShell").hidden = false;
      if (status.state) render(status.state);
      else await load();
    } else showLogin();
  } catch (_) {
    $("#loginError").textContent = "Server nicht erreichbar.";
    showLogin();
  }
}

async function login(event) {
  event.preventDefault();
  const button = $("#loginButton");
  const error = $("#loginError");
  button.disabled = true;
  error.textContent = "";
  try {
    const result = await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("#loginPassword").value }) });
    $("#loginPassword").value = "";
    $("#loginDialog").close();
    $("#appShell").hidden = false;
    if (result.state) render(result.state);
    else await load();
  } catch (exception) {
    error.textContent = exception.message;
  } finally { button.disabled = false; }
}

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = "toast"; }, 3000);
}

function formatTime(value) {
  if (!value) return "Noch nicht aktualisiert";
  const dt = new Date(value);
  return Number.isNaN(dt.valueOf()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(dt);
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function inlineMarkdown(value) {
  let html = escapeHtml(value);
  const codeSpans = [];
  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const token = `\u0000code${codeSpans.length}\u0000`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__(.+?)__/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  html = html.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  return html.replace(/\u0000code(\d+)\u0000/g, (_, index) => codeSpans[Number(index)]);
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").replace(/\r/g, "").split("\n");
  const output = [];
  let paragraph = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  };
  const flushParagraph = () => {
    if (paragraph.length) {
      output.push(`<p>${inlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
      paragraph = [];
    }
  };

  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      flushParagraph(); closeList();
      if (inCode) {
        output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
      }
      inCode = !inCode;
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }
    if (!line.trim()) { flushParagraph(); closeList(); continue; }
    const heading = line.match(/^\s*(#{1,3})\s+(.+?)\s*#*\s*$/);
    if (heading) { flushParagraph(); closeList(); output.push(`<h${heading[1].length}>${inlineMarkdown(heading[2])}</h${heading[1].length}>`); continue; }
    if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { flushParagraph(); closeList(); output.push("<hr>"); continue; }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const nextType = unordered ? "ul" : "ol";
      if (listType !== nextType) { closeList(); output.push(`<${nextType}>`); listType = nextType; }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      continue;
    }
    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) { flushParagraph(); closeList(); output.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); continue; }
    closeList(); paragraph.push(line);
  }
  if (inCode) output.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  flushParagraph(); closeList();
  return output.join("");
}

function renderStatus(data) {
  const configured = data.configured;
  const morning = data.morning_checkin || {};
  const missing = [];
  if (!configured.openai) missing.push("OpenAI-API-Schlüssel");
  if (!configured.intervals) missing.push("Intervals.icu-API-Schlüssel");
  const performanceRefresh = data.performance_refresh || {};
  const error = data.sync.last_error || data.library_sync?.last_error || morning.last_error || performanceRefresh.last_error;
  const statusCard = $("#statusCard");
  const activePanel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  const hasProblem = Boolean(missing.length || error);
  statusCard.hidden = !hasProblem || activePanel === "settingsPanel";
  statusCard.classList.toggle("warning", hasProblem);
  $("#statusTitle").textContent = missing.length
    ? `Einrichtung nötig: ${missing.join(" + ")}`
    : error ? "Coach benötigt Aufmerksamkeit" : "Coach ist bereit";
  $("#statusDetail").textContent = missing.length
    ? "Ergänze die fehlende Serverkonfiguration"
    : error || (morning.status === "ready" ? `Morgen-Check-in abgeschlossen: ${formatTime(morning.date)}` : "Bereit für deine nächste Frage");
  statusCard.classList.remove("working");
}

function dateLabel(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? String(value).slice(0, 10) : new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(parsed);
}

function distanceLabel(value) {
  const distance = Number(value);
  if (!Number.isFinite(distance) || distance <= 0) return null;
  return `${(distance / 1000).toFixed(1)} km`;
}

function activitySportLabel(activity) {
  const value = String(activity?.type || activity?.sport || activity?.sport_type || activity?.name || "").toLowerCase();
  if (/ride|bike|cycling|rad|velo|bicycle/.test(value)) return "Radfahren";
  if (/run|lauf|jog/.test(value)) return "Laufen";
  if (/swim|schwimm/.test(value)) return "Schwimmen";
  if (/strength|kraft|gym|weight/.test(value)) return "Kraft";
  return "Andere";
}

function renderActivityStats(activities) {
  const root = $("#activityStats");
  if (!root) return;
  root.replaceChildren();
  const list = Array.isArray(activities) ? activities : [];
  const counts = new Map();
  list.forEach((activity) => counts.set(activitySportLabel(activity), (counts.get(activitySportLabel(activity)) || 0) + 1));
  const dates = list.map((activity) => activity.start_date_local || activity.start_date).filter(Boolean).map((value) => new Date(value)).filter((value) => !Number.isNaN(value.valueOf()));
  const range = dates.length
    ? `${new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(Math.min(...dates)))} – ${new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(Math.max(...dates)))}`
    : "Keine Einheiten";
  const entries = [["Einheiten gesamt", list.length], ...[...counts.entries()].sort((a, b) => a[0].localeCompare(b[0], "de")).map(([sport, count]) => [`${sport}`, count]), ["Zeitraum", range]];
  entries.forEach(([label, value]) => {
    const card = document.createElement("div");
    const number = document.createElement("strong");
    number.textContent = String(value);
    const caption = document.createElement("span");
    caption.textContent = label;
    card.append(number, caption);
    root.append(card);
  });
}

function renderActivities(activities) {
  renderActivityStats(activities);
  const root = $("#activities");
  root.replaceChildren();
  if (!activities?.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("strong");
    title.textContent = "Noch keine absolvierten Einheiten";
    empty.append(title, document.createTextNode("Aktualisiere die Trainingsdaten, um deine synchronisierten Aktivitäten hier zu sehen."));
    root.append(empty);
    return;
  }
  activities.slice(0, 250).forEach((activity) => {
    const card = document.createElement("article");
    card.className = "activity-card";
    const top = document.createElement("div");
    top.className = "activity-top";
    const title = document.createElement("h3");
    title.textContent = activity.name || activity.type || "Einheit";
    const date = document.createElement("span");
    date.className = "eyebrow";
    date.textContent = dateLabel(activity.start_date_local);
    top.append(title, date);
    const meta = document.createElement("div");
    meta.className = "activity-meta";
    meta.textContent = activity.type || "Sportart unbekannt";
    const stats = document.createElement("div");
    stats.className = "activity-stats";
    const addStat = (label, value) => {
      if (value == null || value === "") return;
      const item = document.createElement("span");
      item.innerHTML = `${escapeHtml(label)} <strong>${escapeHtml(String(value))}</strong>`;
      stats.append(item);
    };
    addStat("Dauer", formatDuration(activity.moving_time));
    addStat("Distanz", distanceLabel(activity.distance));
    addStat("Belastung", activity.icu_training_load);
    addStat("Ø Puls", activity.average_heartrate ? `${Math.round(activity.average_heartrate)} bpm` : null);
    addStat("Ø Leistung", activity.average_watts ? `${Math.round(activity.average_watts)} W` : null);
    card.append(top, meta, stats);
    root.append(card);
  });
  if (activities.length > 250) {
    const note = document.createElement("p");
    note.className = "fine-print";
    note.textContent = "Es werden die 250 neuesten Einheiten angezeigt.";
    root.append(note);
  }
}

function renderParallelCyclingWarning(groups) {
  const root = $("#parallelCyclingWarning");
  if (!root) return;
  root.replaceChildren();
  root.hidden = !groups?.length;
  if (!groups?.length) return;

  const title = document.createElement("strong");
  title.textContent = "Parallele Radeinheiten erkannt";
  const intro = document.createElement("p");
  intro.textContent = "Bitte auswählen, welche Einheit aus Intervals.icu gelöscht werden soll. Es wird nur die ausgewählte Einheit per API entfernt.";
  root.append(title, intro);
  groups.forEach((group, groupIndex) => {
    const groupRoot = document.createElement("div");
    groupRoot.className = "parallel-cycling-group";
    const options = document.createElement("div");
    options.className = "parallel-cycling-options";
    group.forEach((event, eventIndex) => {
      const label = document.createElement("label");
      label.className = "parallel-cycling-option";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = `parallel-cycling-${groupIndex}`;
      radio.value = String(event.id);
      radio.checked = eventIndex === 0;
      const text = document.createElement("span");
      text.textContent = `${event.name || "Radeinheit"} · ${dateLabel(event.start_date_local || event.date)}${event.type ? ` · ${event.type}` : ""}`;
      label.append(radio, text);
      options.append(label);
    });
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "secondary-button danger-button";
    deleteButton.textContent = "Ausgewählte Einheit löschen";
    deleteButton.addEventListener("click", () => {
      const selectedId = options.querySelector("input:checked")?.value;
      const selected = group.find((event) => String(event.id) === selectedId);
      if (selected) deletePlanned(selected.id, deleteButton, selected.name);
    });
    groupRoot.append(options, deleteButton);
    root.append(groupRoot);
  });
}

function renderPlanned(planned) {
  renderParallelCyclingWarning(state.data?.parallel_cycling || []);
  const root = $("#plannedCalendar");
  root.replaceChildren();
  if (!planned?.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Keine geplanten Intervals.icu-Einheiten im Zeitraum.";
    root.append(empty);
    return;
  }
  planned.forEach((event) => {
    const card = document.createElement("article");
    card.className = "planned-card";
    const top = document.createElement("div");
    top.className = "planned-top";
    const title = document.createElement("h3");
    title.textContent = event.name || "Geplante Einheit";
    const date = document.createElement("span");
    date.className = "eyebrow";
    date.textContent = dateLabel(event.start_date_local);
    top.append(title, date);
    const meta = document.createElement("div");
    meta.className = "planned-meta";
    const parts = [event.type, event.category, event.moving_time ? formatDuration(event.moving_time) : null].filter(Boolean);
    meta.textContent = parts.join(" · ");
    card.append(top, meta);
    if (event.description) {
      const description = document.createElement("div");
      description.className = "planned-description";
      description.textContent = event.description;
      card.append(description);
    }
    if (event.id != null) {
      const actions = document.createElement("div");
      actions.className = "card-actions";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary-button danger-button";
      button.textContent = "Einheit löschen";
      button.addEventListener("click", () => deletePlanned(event.id, button, event.name));
      actions.append(button);
      card.append(actions);
    }
    root.append(card);
  });
}

async function deletePlanned(eventId, button, name) {
  if (!window.confirm(`„${name || "Geplante Einheit"}“ wirklich aus Intervals.icu löschen?`)) return;
  button.disabled = true;
  button.textContent = "Wird gelöscht…";
  try {
    await api(`/api/planned/${encodeURIComponent(eventId)}`, { method: "DELETE" });
    toast("Geplante Einheit gelöscht");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = "Einheit löschen";
  }
}

function chatIsNearBottom() {
  return document.documentElement.scrollHeight - (window.scrollY + window.innerHeight) <= 140;
}

function renderMessages(messages, forceScroll = false) {
  const root = $("#messages");
  // Synchronisation and refresh notices belong to their respective tabs,
  // not to the personal conversation history.
  const visibleMessages = (messages || []).filter((message) => message.role !== "event");
  const signature = JSON.stringify(visibleMessages.map((message) => [message.id || null, message.created_at || null, message.role, message.content]));
  if (root.dataset.signature === signature) return;
  const shouldScroll = forceScroll || chatIsNearBottom();
  root.dataset.signature = signature;
  root.replaceChildren();
  if (!visibleMessages.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("strong");
    title.textContent = "Dein Coach ist bereit";
    empty.append(title, document.createTextNode("Lege deine Ziele im Profil fest. Bitte den Coach jederzeit, deine letzten Einheiten neu zu analysieren."));
    root.append(empty);
    return;
  }
  for (const message of visibleMessages) {
    const node = document.createElement("div");
    node.className = `message ${message.role}`;
    if (message.role === "assistant") node.innerHTML = markdownToHtml(message.content);
    else node.textContent = message.content;
    root.append(node);
  }
  if (shouldScroll) scrollChatToLatest();
}

function scrollChatToLatest() {
  const panel = $("#chatPanel");
  const root = $("#messages");
  if (!panel?.classList.contains("active") || !root) return;
  requestAnimationFrame(() => {
    const target = root.lastElementChild;
    if (!target) return;
    const composer = $("#chatForm");
    const bottomOffset = (composer?.offsetHeight || 70) + 105 + window.visualViewport?.offsetTop || 175;
    const targetBottom = target.getBoundingClientRect().bottom + window.scrollY;
    window.scrollTo({ top: Math.max(0, targetBottom - window.innerHeight + bottomOffset), behavior: "auto" });
  });
}

function renderContextPreview(preview) {
  const status = $("#contextPreviewStatus");
  const content = $("#contextPreviewContent");
  if (!status || !content) return;
  content.replaceChildren();
  content.hidden = true;
  if (!preview) {
    status.textContent = "Noch nicht geladen.";
    status.classList.remove("error");
    return;
  }
  const sections = [
    ["Zusammensetzung", preview.assembly],
    ["Dauerhaftes Profil", preview.structured_athlete_context?.durable_profile],
    ["Zielwettkämpfe", preview.structured_athlete_context?.target_competitions],
    ["Aktuelle Leistungsdaten", preview.structured_athlete_context?.current_performance],
    ["Garmin-Kontext", preview.structured_athlete_context?.garmin],
    ["Gesprächskontinuität", preview.conversation],
    ["Intervals.icu-Snapshot", preview.latest_intervals_snapshot],
    ["Exakt zusammengesetzter Kontext", preview.context_text],
  ];
  sections.forEach(([title, value], index) => {
    if (value == null) return;
    const details = document.createElement("details");
    if (index < 3) details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    details.append(summary, pre);
    content.append(details);
  });
  status.classList.remove("error");
  status.textContent = `Zuletzt erstellt: ${formatTime(preview.generated_at)}${preview.snapshot_truncated ? " (Snapshot im Coach-Kontext gekürzt)" : ""}`;
  content.hidden = false;
}

function invalidateContextPreview() {
  const button = $("#contextPreviewButton");
  if (!button) return;
  button.dataset.loaded = "false";
  button.textContent = "Kontext aktualisieren";
}

async function loadContextPreview() {
  const button = $("#contextPreviewButton");
  const status = $("#contextPreviewStatus");
  if (!button || !status || button.dataset.loaded === "true") return;
  button.disabled = true;
  button.textContent = "Kontext wird geladen…";
  status.classList.remove("error");
  status.textContent = "Der aktuelle Coach-Kontext wird zusammengestellt…";
  try {
    const preview = await api("/api/context-preview");
    renderContextPreview(preview);
    button.dataset.loaded = "true";
    button.textContent = "Kontext aktualisieren";
  } catch (error) {
    status.classList.add("error");
    status.textContent = error.message;
    button.textContent = "Kontext laden";
  } finally { button.disabled = false; }
}

function renderDrafts(drafts) {
  const root = $("#drafts");
  root.replaceChildren();
  const pending = drafts.filter((draft) => draft.status !== "pushed").length;
  $("#draftCount").textContent = pending ? String(pending) : "";
  if (!drafts.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    const title = document.createElement("strong");
    title.textContent = "Noch keine Entwürfe";
    empty.append(title, document.createTextNode("Bitte deinen Coach um die morgige Einheit oder eine ganze Woche."));
    root.append(empty);
    return;
  }
  for (const draft of drafts) {
    const card = document.createElement("article");
    card.className = "draft";
    const top = document.createElement("div"); top.className = "draft-top";
    const heading = document.createElement("div");
    const date = document.createElement("span"); date.className = "eyebrow"; date.textContent = draft.date;
    const title = document.createElement("h3"); title.textContent = draft.name;
    const meta = document.createElement("div"); meta.className = "draft-meta"; meta.textContent = `${draft.sport} · ${draft.duration_minutes} Min. · ${draft.target}`;
    heading.append(date, title, meta);
    const badge = document.createElement("span"); badge.className = `badge ${draft.status}`; badge.textContent = draft.status === "pushed" ? "übertragen" : draft.status === "error" ? "Fehler" : "Entwurf";
    top.append(heading, badge);
    const workout = document.createElement("div"); workout.className = "workout-text"; workout.textContent = draft.description;
    const rationale = document.createElement("p"); rationale.className = "rationale"; rationale.textContent = draft.rationale;
    card.append(top, workout, rationale);
    if (draft.error) {
      const error = document.createElement("p"); error.className = "error"; error.textContent = draft.error; card.append(error);
    }
    const button = document.createElement("button");
    button.className = "push-button";
    button.textContent = draft.status === "pushed" ? "Zu Intervals.icu übertragen" : "Zu Intervals.icu übertragen";
    button.disabled = draft.status === "pushed";
    button.addEventListener("click", () => pushDraft(draft.id, button));
    card.append(button);
    if (draft.status !== "pushed") {
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "secondary-button danger-button";
      deleteButton.textContent = "Entwurf löschen";
      deleteButton.addEventListener("click", () => deleteDraft(draft.id, deleteButton, draft.name));
      card.append(deleteButton);
    }
    root.append(card);
  }
}

async function deleteDraft(id, button, name) {
  if (!window.confirm(`„${name || "Entwurf"}“ wirklich löschen?`)) return;
  button.disabled = true;
  button.textContent = "Wird gelöscht…";
  try {
    await api(`/api/drafts/${encodeURIComponent(id)}`, { method: "DELETE" });
    toast("Entwurf gelöscht");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = "Entwurf löschen";
  }
}

function renderLibrary(workouts) {
  const root = $("#library");
  if (!root) return;
  root.replaceChildren();
  if (!Array.isArray(workouts) || !workouts.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Keine Einheiten in der Intervals.icu-Trainingsbibliothek gefunden.";
    root.append(empty);
    return;
  }
  const groups = new Map();
  workouts.forEach((workout) => {
    const sport = activitySportLabel(workout);
    if (!groups.has(sport)) groups.set(sport, []);
    groups.get(sport).push(workout);
  });
  [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "de"))
    .forEach(([sport, sportWorkouts]) => {
      const section = document.createElement("details");
      section.className = "library-sport";
      const summary = document.createElement("summary");
      const title = document.createElement("strong");
      title.textContent = sport;
      summary.append(title);
      section.append(summary);
      const cards = document.createElement("div");
      cards.className = "library-sport-cards";
      sportWorkouts.forEach((workout) => {
        const card = document.createElement("article");
        card.className = "library-card";
        const heading = document.createElement("div");
        const cardTitle = document.createElement("h4");
        cardTitle.textContent = workout.name || "Bibliotheks-Einheit";
        const meta = document.createElement("span");
        meta.textContent = [workout.type, workout.moving_time ? formatDuration(workout.moving_time) : null].filter(Boolean).join(" · ");
        heading.append(cardTitle, meta);
        const description = document.createElement("p");
        description.textContent = workout.description || "Kein Workout-Text hinterlegt.";
        const controls = document.createElement("div");
        controls.className = "library-controls";
        const dateLabelNode = document.createElement("label");
        dateLabelNode.textContent = "Datum";
        const dateInput = document.createElement("input");
        dateInput.type = "date";
        dateInput.value = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
        dateLabelNode.append(dateInput);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "secondary-button";
        button.textContent = "Als geplant übernehmen";
        button.addEventListener("click", () => planLibraryWorkout(workout.id, dateInput, button));
        controls.append(dateLabelNode, button);
        card.append(heading, description, controls);
        cards.append(card);
      });
      section.append(cards);
      root.append(section);
    });
}

async function loadLibrary() {
  const button = $("#libraryLoadButton");
  const root = $("#library");
  if (!button || !root) return;
  button.disabled = true;
  button.textContent = "Bibliothek wird geladen…";
  try {
    await api("/api/library/sync", { method: "POST", body: "{}" });
    await load();
  } catch (error) {
    root.replaceChildren();
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = error.message;
    root.append(message);
  } finally {
    button.disabled = false;
    button.textContent = "Bibliothek synchronisieren";
  }
}

async function planLibraryWorkout(workoutId, dateInput, button) {
  if (!dateInput.value) { toast("Bitte ein Datum auswählen", true); return; }
  button.disabled = true;
  button.textContent = "Wird eingeplant…";
  try {
    await api("/api/library/" + encodeURIComponent(workoutId) + "/plan", { method: "POST", body: JSON.stringify({ date: dateInput.value }) });
    toast("Einheit eingeplant");
    await load();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Als geplant übernehmen"; }
}

function renderProfile(profile) {
  if (state.profileDirty) return;
  const form = $("#profileForm");
  for (const [key, value] of Object.entries(profile)) {
    if (form.elements[key]) form.elements[key].value = value || "";
  }
}

function renderGarmin(garmin) {
  const status = $("#garminStatus");
  const detail = $("#garminDetail");
  const button = $("#garminSyncButton");
  if (!status || !detail || !button) return;
  button.disabled = Boolean(state.data?.garmin_sync?.running);
  if (!garmin?.available) {
    status.textContent = "Garmin nicht verfügbar";
    detail.textContent = "";
    button.disabled = true;
    return;
  }
  if (!garmin.configured) {
    status.textContent = "Garmin nicht eingerichtet";
    detail.textContent = "";
    button.disabled = true;
    return;
  }
  const performanceSources = [garmin.has_vo2max ? "VO2max" : null, garmin.has_estimated_run_times ? "Laufprognosen" : null].filter(Boolean);
  status.textContent = garmin.source === "fixture"
    ? "Lokale Garmin-Testdaten aktiv"
    : garmin.last_error ? "Mit Fehlern synchronisiert" : "Optionaler Direktabruf aktiv";
  detail.textContent = garmin.last_sync_at
    ? `Letzter Abruf: ${formatTime(garmin.last_sync_at)} · ${garmin.activities || 0} Aktivitäten · Schlaf/HRV/Readiness ${[garmin.has_sleep, garmin.has_hrv, garmin.has_readiness].filter(Boolean).length}/3`
    : garmin.source === "fixture" ? "Testdatei ist konfiguriert; synchronisiere sie mit dem Button."
      : "Noch kein Garmin-Abruf durchgeführt.";
  if (performanceSources.length) detail.textContent += ` · ${performanceSources.join("/")} aus Garmin`;
}

function contextField(labelText, field, value = "", options = {}) {
  const label = document.createElement("label");
  label.textContent = labelText;
  let input;
  if (options.choices) {
    input = document.createElement("select");
    for (const choice of options.choices) {
      const option = document.createElement("option");
      option.value = choice;
      option.textContent = choice;
      input.append(option);
    }
  } else if (options.multiline) {
    input = document.createElement("textarea");
    input.rows = options.rows || 2;
  } else {
    input = document.createElement("input");
    input.type = options.type || "text";
  }
  input.dataset.field = field;
  input.value = value || "";
  if (options.placeholder) input.placeholder = options.placeholder;
  label.append(input);
  return label;
}

function competitionEditor(competition = {}, index = 0) {
  const card = document.createElement("article");
  card.className = "competition-editor";
  card.dataset.id = competition.id || "";

  const top = document.createElement("div");
  top.className = "competition-editor-top";
  const title = document.createElement("strong");
  title.textContent = competition.name || `Wettkampf ${index + 1}`;
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "remove-context-button";
  remove.textContent = "Entfernen";
  remove.addEventListener("click", () => {
    card.remove();
    state.profileDirty = true;
  });
  top.append(title, remove);

  const mainGrid = document.createElement("div");
  mainGrid.className = "form-grid";
  mainGrid.append(
    contextField("Name", "name", competition.name, { placeholder: "Münsterland Giro" }),
    contextField("Datum", "event_date", competition.event_date, { type: "date" }),
    contextField("Sportart", "sport", competition.sport || "Radfahren"),
    contextField("Priorität", "priority", competition.priority || "B", { choices: ["A", "B", "C"] }),
    contextField("Distanz", "distance", competition.distance, { placeholder: "125 km" })
  );
  card.append(
    top,
    mainGrid,
    contextField("Ergebnisziel", "target", competition.target, { multiline: true, placeholder: "Zielzeit, Platzierung, Finish-Ziel…" }),
    contextField("Streckenprofil", "course_profile", competition.course_profile, { multiline: true, placeholder: "Höhenmeter, Technik, erwartete Dauer…" }),
    contextField("Notizen", "notes", competition.notes, { multiline: true })
  );
  return card;
}

function renderCompetitions(competitions) {
  if (state.profileDirty) return;
  const root = $("#competitionList");
  root.replaceChildren();
  if (!competitions.length) {
    const empty = document.createElement("p");
    empty.className = "context-empty";
    empty.textContent = "Noch keine Zielwettkämpfe gespeichert.";
    root.append(empty);
    return;
  }
  competitions.forEach((competition, index) => root.append(competitionEditor(competition, index)));
}

function collectCompetitions() {
  return [...document.querySelectorAll(".competition-editor")].map((card) => {
    const competition = { id: card.dataset.id || "" };
    card.querySelectorAll("[data-field]").forEach((input) => { competition[input.dataset.field] = input.value.trim(); });
    return competition;
  });
}

function addCompetition() {
  const root = $("#competitionList");
  root.querySelector(".context-empty")?.remove();
  root.append(competitionEditor({}, root.querySelectorAll(".competition-editor").length));
  state.profileDirty = true;
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const total = Math.round(Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}` : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatWhole(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number).toLocaleString("de-DE") : String(value);
}

function formatPace(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return null;
  const total = Math.round(Number(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")} min/km`;
}

function comparisonText(comparison) {
  if (!comparison || comparison.delta == null) return null;
  const delta = Number(comparison.delta);
  if (!Number.isFinite(delta)) return null;
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const precision = comparison.unit === "" || comparison.unit === "bpm" || comparison.unit === "ms" ? 0 : 1;
  const amount = Math.abs(delta).toFixed(precision).replace(".", ",");
  const unit = comparison.unit ? ` ${comparison.unit}` : "";
  const arrow = comparison.direction === "up" ? "↑" : comparison.direction === "down" ? "↓" : "→";
  return { text: `${arrow} ${sign}${amount}${unit}`, className: comparison.color || "neutral", title: `Vergleich zum ${comparison.label || `${comparison.days}-Tage-Durchschnitt`}` };
}

function displayMetric(root, label, metricData, formatter = null, editable = null) {
  const item = document.createElement("div");
  const metric = document.createElement("strong");
  const caption = document.createElement("span");
  const source = document.createElement("small");
  const value = metricData && typeof metricData === "object" ? metricData.value : metricData;
  const unit = metricData && typeof metricData === "object" ? metricData.unit : "";
  metric.textContent = value == null ? "—" : (formatter ? formatter(value) : `${value}${unit ? ` ${unit}` : ""}`);
  caption.textContent = label;
  source.textContent = metricData?.source || "Nicht verfügbar";
  source.title = metricData?.note || metricData?.source || "";
  if (metricData?.source === "KI-Schätzung" || metricData?.source === "Berechnete Schätzung") source.className = "metric-estimate";
  if (metricData?.source === "Garmin Connect") source.className = "metric-garmin";
  if (editable?.key) {
    item.classList.add("metric-editable");
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "metric-edit-button";
    edit.textContent = "✎";
    edit.title = `${label} bearbeiten`;
    edit.setAttribute("aria-label", `${label} bearbeiten`);
    const input = document.createElement("input");
    input.className = "metric-edit-input";
    input.type = "number";
    input.step = editable.step || "any";
    input.min = editable.min ?? "0";
    input.value = state.data?.profile?.[editable.key] || (value == null ? "" : value);
    input.hidden = true;
    edit.addEventListener("click", () => {
      const editing = item.classList.toggle("editing");
      input.hidden = !editing;
      metric.hidden = editing;
      edit.textContent = editing ? "✓" : "✎";
      edit.title = editing ? "Wert speichern" : `${label} bearbeiten`;
      edit.setAttribute("aria-label", edit.title);
      if (editing) { input.focus(); input.select(); }
      else saveInlineMetric(editable.key, input.value, edit);
    });
    item.append(metric, input, caption, source, edit);
  } else {
    item.append(metric, caption, source);
  }
  const comparison = comparisonText(metricData?.comparison);
  if (comparison) {
    const badge = document.createElement("small");
    badge.className = `metric-comparison ${comparison.className}`;
    badge.textContent = comparison.text;
    badge.title = comparison.title;
    item.append(badge);
  }
  root.append(item);
}

async function saveInlineMetric(key, value, button) {
  const profile = { ...(state.data?.profile || {}), [key]: String(value || "").trim() };
  button.disabled = true;
  try {
    await api("/api/profile", { method: "PUT", body: JSON.stringify(profile) });
    toast("Wert gespeichert und für den Coach aktiviert");
    await load();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

function performanceSection(root, title, items, detail = "") {
  const section = document.createElement("section");
  section.className = "performance-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const headingWrap = document.createElement("div");
  headingWrap.className = "performance-section-heading";
  headingWrap.append(heading);
  if (detail) {
    const stamp = document.createElement("span");
    stamp.className = "tab-sync-detail";
    stamp.textContent = detail;
    headingWrap.append(stamp);
  }
  section.append(headingWrap);
  const grid = document.createElement("div");
  grid.className = "metric-grid";
  items.forEach(([label, value, formatter, editable]) => displayMetric(grid, label, value, formatter, editable));
  section.append(grid);
  root.append(section);
}

function renderPerformance(performance) {
  const root = $("#performanceSummary");
  root.replaceChildren();
  const syncNotices = [];
  if (state.data?.sync?.running || state.localSync.intervals) syncNotices.push(state.data?.sync?.status || "Intervals.icu wird synchronisiert…");
  if (state.data?.garmin_sync?.running || state.localSync.garmin) syncNotices.push(state.data?.garmin_sync?.status || "Garmin wird synchronisiert…");
  if (state.data?.performance_refresh?.running || state.localSync.performance) syncNotices.push("Leistungsdaten werden aktualisiert…");
  if (!performance?.available) {
    const info = document.createElement("p");
    info.className = "fine-print";
    info.textContent = "Nach dem ersten Trainingsdaten-Update werden hier Leistungswerte angezeigt.";
    root.append(info);
    if (syncNotices.length) {
      const status = document.createElement("p");
      status.className = "tab-sync-detail";
      status.textContent = syncNotices.join(" · ");
      root.append(status);
    }
    return;
  }

  const values = performance.metrics || {};
  const load = performance.current_load || {};
  const actualLoad = performance.actual_load || {};
  const recovery = performance.recovery || {};
  const comparisons = performance.comparisons || {};
  const week = performance.rolling_training?.last_7_days || {};
  const refreshedAt = state.data?.sync?.last_sync_at || performance.as_of;
  const performanceDetail = syncNotices.length ? syncNotices.join(" · ") : refreshedAt ? `Letzte Aktualisierung: ${formatTime(refreshedAt)}` : "";
  const compared = (value, key) => value && typeof value === "object" ? { ...value, comparison: comparisons[key] } : { value, comparison: comparisons[key] };
  performanceSection(root, "Gesundheitsdaten", [
    ["Gewicht", values.weight_kg, null, { key: "weight_kg", step: "0.1" }],
    ["Körperfett", values.body_fat_pct, null, { key: "body_fat_pct", step: "0.1" }],
    ["Größe", values.height_cm, null, { key: "height_cm", step: "0.1" }],
    ["Schlaf", compared({ value: recovery.sleep_hours, unit: "h", source: "Intervals.icu Wellness" }, "sleep_hours")],
    ["Readiness", compared({ value: recovery.readiness, unit: "", source: "Intervals.icu Wellness" }, "readiness")],
    ["Ruhepuls", compared({ value: recovery.restingHR, unit: "bpm", source: "Intervals.icu Wellness" }, "restingHR")],
    ["HRV", compared({ value: recovery.hrv, unit: "ms", source: "Intervals.icu Wellness" }, "hrv")],
  ], performanceDetail);
  performanceSection(root, "Allgemeine Leistungsdaten", [
    ["Fitness / CTL", compared({ value: load.ctl, unit: "", source: "Intervals.icu" }, "fitness_ctl"), formatWhole],
    ["Form / TSB", compared({ value: load.tsb, unit: "", source: "Intervals.icu" }, "form_tsb"), formatWhole],
    ["Ermüdung / ATL (inkl. Planung)", compared({ value: load.atl, unit: "", source: "Intervals.icu" }, "fatigue_atl"), formatWhole],
    ["Ermüdung / ATL (nur absolviert)", compared({ value: actualLoad.atl, unit: "", source: actualLoad.source || "Berechnet" }, "fatigue_atl_actual"), formatWhole],
    ["Belastung letzte 7 Tage", compared({ value: week.training_load, unit: "", source: "Aus Aktivitäten" }, "training_load_7d")],
    ["Trainingsumfang letzte 7 Tage", compared({ value: week.duration_hours, unit: "h", source: "Aus Aktivitäten" }, "training_volume_7d")],
  ]);
  performanceSection(root, "Radfahren", [
    ["FTP", values.cycling_ftp_watts],
    ["eFTP", compared(values.cycling_eftp_watts, "cycling_eftp_30d")],
    ["Schwellenpuls", values.bike_threshold_hr_bpm],
    ["VO₂max", values.cycling_vo2max_ml_kg_min],
  ]);
  performanceSection(root, "Laufen", [
    ["Schwellenleistung", values.run_threshold_watts],
    ["Schwellenpace", values.run_threshold_pace_seconds_per_km, formatPace],
    ["Schwellenpuls", values.run_threshold_hr_bpm],
    ["VO₂max", values.running_vo2max_ml_kg_min],
    ["5 km (geschätzt)", values.run_5k_seconds, formatDuration],
    ["10 km (geschätzt)", values.run_10k_seconds, formatDuration],
    ["Halbmarathon (geschätzt)", values.run_half_marathon_seconds, formatDuration],
    ["Marathon (geschätzt)", values.run_marathon_seconds, formatDuration],
  ]);
  const explanation = document.createElement("p");
  explanation.className = "fine-print";
  explanation.textContent = "Garmin-Connect-Werte werden als solche markiert und haben bei VO₂max sowie Laufprognosen Vorrang. Fehlen Garmin-Werte, werden Intervals.icu-Werte bzw. vorsichtige KI-Schätzungen verwendet.";
  root.append(explanation);
  const estimationError = state.data?.performance_refresh?.last_error;
  if (estimationError) {
    const error = document.createElement("p");
    error.className = "error";
    error.textContent = `KI-Schätzung fehlgeschlagen: ${estimationError}`;
    root.append(error);
  }
  const estimationReason = performance.ai_estimates?.reason;
  if (estimationReason && !estimationError) {
    const note = document.createElement("p");
    note.className = "fine-print estimate-note";
    note.textContent = estimationReason;
    root.append(note);
  }
}

function updateHeaderAction() {
  const button = $("#headerActionButton");
  if (!button) return;
  const panel = document.querySelector(".nav-item.active")?.dataset.panel || "chatPanel";
  if (panel === "dataPanel") {
    button.hidden = false;
    button.dataset.action = "performance";
    button.title = "Aktuelle Leistungsdaten von Intervals.icu und KI aktualisieren";
    button.disabled = Boolean(state.data?.performance_refresh?.running || state.data?.sync?.running || state.data?.garmin_sync?.running || state.localSync.performance || state.localSync.intervals || state.localSync.garmin);
    button.textContent = state.data?.sync?.running || state.data?.garmin_sync?.running || state.localSync.intervals || state.localSync.garmin
      ? "Synchronisierung läuft…"
      : button.disabled ? "Leistungsdaten werden aktualisiert…" : "Leistungsdaten aktualisieren";
  } else if (panel === "activitiesPanel") {
    button.hidden = false;
    button.dataset.action = "activities";
    button.title = "Aktivitäten der letzten 90 Tage von Intervals.icu laden";
    button.disabled = Boolean(state.data?.sync?.running || state.localSync.intervals);
    button.textContent = button.disabled ? "Synchronisierung läuft…" : "Aktivitäten aktualisieren";
  } else {
    button.hidden = true;
    button.disabled = false;
    button.dataset.action = "";
  }
}

function renderModel(model) {
  if (!model) return;
  const select = $("#modelSelect");
  const currentIds = [...select.options].map((option) => option.value).join(",");
  const nextIds = (model.options || []).map((option) => option.id).join(",");
  if (currentIds !== nextIds) {
    select.replaceChildren();
    for (const option of model.options || []) {
      const element = document.createElement("option");
      element.value = option.id;
      element.textContent = option.label;
      element.title = option.description || "";
      select.append(element);
    }
  }
  select.value = model.selected;
  const selected = (model.options || []).find((option) => option.id === model.selected);
  $("#modelDescription").textContent = selected?.description || "Wähle die Balance aus Qualität, Tempo und Kosten.";
}

function renderThinkingLevel(thinkingLevel) {
  if (!thinkingLevel) return;
  const select = $("#thinkingLevelSelect");
  const currentIds = [...select.options].map((option) => option.value).join(",");
  const nextIds = (thinkingLevel.options || []).map((option) => option.id).join(",");
  if (currentIds !== nextIds) {
    select.replaceChildren();
    for (const option of thinkingLevel.options || []) {
      const element = document.createElement("option");
      element.value = option.id;
      element.textContent = option.label;
      element.title = option.description || "";
      select.append(element);
    }
  }
  select.value = thinkingLevel.selected;
  const selected = (thinkingLevel.options || []).find((option) => option.id === thinkingLevel.selected);
  $("#thinkingLevelDescription").textContent = selected?.description || "Steuert die GrÃ¼ndlichkeit der Antwort.";
}

function renderSettings(data) {
  const configured = data.configured || {};
  const garmin = data.garmin || {};
  const setStatus = (selector, ok, text) => {
    const node = $(selector);
    if (!node) return;
    node.textContent = text;
    node.className = ok ? "configured" : "not-configured";
  };
  setStatus("#openaiConnectionStatus", configured.openai, configured.openai ? "Konfiguriert" : "Nicht konfiguriert");
  setStatus("#intervalsConnectionStatus", configured.intervals, configured.intervals ? "Konfiguriert" : "Nicht konfiguriert");
  setStatus("#garminConnectionStatus", garmin.configured, garmin.configured ? (garmin.source === "fixture" ? "Lokale Testdatei aktiv" : "Konfiguriert") : "Nicht konfiguriert");
  const intervalsDays = $("#intervalsSyncDays");
  const garminDays = $("#garminSyncDays");
  if (intervalsDays && document.activeElement !== intervalsDays) intervalsDays.value = data.sync_settings?.intervals_days || 90;
  if (garminDays && document.activeElement !== garminDays) garminDays.value = data.sync_settings?.garmin_days || 30;
  const intervalsSyncButton = $("#systemIntervalsSyncButton");
  if (intervalsSyncButton) {
    intervalsSyncButton.disabled = Boolean(data.sync?.running || state.localSync.intervals);
    intervalsSyncButton.textContent = data.sync?.running || state.localSync.intervals ? "Synchronisierung läuft…" : "Synchronisieren";
  }
  const garminSyncButton = $("#garminSyncButton");
  if (garminSyncButton) {
    garminSyncButton.disabled = Boolean(data.garmin_sync?.running || state.localSync.garmin);
    garminSyncButton.textContent = data.garmin_sync?.running || state.localSync.garmin ? "Synchronisierung läuft…" : "Garmin synchronisieren";
  }
  const usage = data.usage || {};
  const usageNode = $("#usageSummary");
  if (usageNode) {
    const rateLimits = usage.rate_limits || {};
    const remaining = rateLimits.remaining_requests != null || rateLimits.remaining_tokens != null
      ? ` · Verfügbar im aktuellen OpenAI-Fenster: ${rateLimits.remaining_requests ?? "?"} Anfragen / ${rateLimits.remaining_tokens ?? "?"} Tokens`
      : " · OpenAI-Kontingent nach dem nächsten API-Aufruf verfügbar";
    usageNode.textContent = `OpenAI heute: ${usage.requests || 0} Anfragen · ${usage.total_tokens || 0} Tokens${remaining}`;
  }
}

function formatLogEntry(entry) {
  const timestamp = entry.timestamp ? `[${formatTime(entry.timestamp)}] ` : "";
  const level = entry.level ? `${entry.level} ` : "";
  const event = entry.event ? `${entry.event}: ` : "";
  const context = entry.context ? ` ${JSON.stringify(entry.context)}` : "";
  return `${timestamp}${level}${event}${entry.message || ""}${context}`;
}

async function loadLogs() {
  const output = $("#logsOutput");
  const button = $("#logsRefreshButton");
  if (!output || !button) return;
  button.disabled = true;
  output.textContent = "Logs werden geladen…";
  try {
    const result = await api("/api/logs?limit=250");
    output.textContent = result.entries?.length ? result.entries.map(formatLogEntry).join("\n") : "Noch keine Log-Einträge vorhanden.";
    output.scrollTop = output.scrollHeight;
  } catch (error) { output.textContent = error.message; }
  finally { button.disabled = false; }
}

function render(data) {
  const firstRender = !state.data;
  state.data = data;
  renderStatus(data);
  renderMessages(data.messages, firstRender);
  renderActivities(data.activities || []);
  const activitiesSyncDetail = $("#activitiesSyncDetail");
  if (activitiesSyncDetail) {
    activitiesSyncDetail.textContent = data.sync?.running || state.localSync.intervals
      ? (data.sync?.status || "Intervals.icu wird synchronisiert…")
      : data.garmin_sync?.running || state.localSync.garmin
        ? (data.garmin_sync?.status || "Garmin wird synchronisiert…")
        : data.sync?.last_sync_at ? `Letzte Aktualisierung: ${formatTime(data.sync.last_sync_at)}` : "Noch nicht synchronisiert";
    if (!data.sync?.running && !state.localSync.intervals && data.sync?.last_window_start && data.sync?.last_window_end) {
      activitiesSyncDetail.textContent += ` · Zeitraum ${data.sync.last_window_start} bis ${data.sync.last_window_end}`;
    }
  }
  renderPlanned(data.planned || []);
  renderDrafts(data.drafts || []);
  renderLibrary(data.library || []);
  const librarySyncDetail = $("#librarySyncDetail");
  if (librarySyncDetail) {
    librarySyncDetail.textContent = data.library_sync?.last_error
      ? data.library_sync.last_error
      : data.library_sync?.last_sync_at
        ? "Letzte Aktualisierung: " + formatTime(data.library_sync.last_sync_at)
        : "Noch nicht synchronisiert";
    librarySyncDetail.classList.toggle("error", Boolean(data.library_sync?.last_error));
  }
  renderProfile(data.profile);
  renderGarmin(data.garmin);
  renderCompetitions(data.competitions || []);
  renderPerformance(data.performance);
  renderModel(data.model);
  renderThinkingLevel(data.thinking_level);
  renderSettings(data);
  updateHeaderAction();
}

async function load() {
  try { render(await api("/api/state")); }
  catch (error) { if (!/Authentication/.test(error.message)) toast(error.message, true); }
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if (!message || state.busy) return;
  state.busy = true;
  const sendButton = $("#sendButton");
  const working = $("#coachWorking");
  sendButton.disabled = true;
  sendButton.textContent = "Coach arbeitet…";
  if (working) working.hidden = false;
  input.value = "";
  if (state.data) {
    state.data.messages.push({ role: "user", content: message });
    renderMessages(state.data.messages, true);
  }
  try {
    await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
    await load();
  } catch (error) {
    toast(error.message, true);
    input.value = message;
    await load();
  } finally {
    state.busy = false;
    sendButton.disabled = false;
    sendButton.textContent = "Senden";
    if (working) working.hidden = true;
    input.focus();
  }
}

async function syncNow(event) {
  const button = event?.currentTarget || $("#activitiesSyncButton");
  const compactButton = button.id === "systemIntervalsSyncButton";
  const defaultCaption = compactButton ? "Synchronisieren" : "Aktivitäten aktualisieren";
  const configuredDays = $("#intervalsSyncDays")?.value || state.data?.sync_settings?.intervals_days || 90;
  state.localSync.intervals = true;
  button.disabled = true; button.classList.add("busy"); button.textContent = compactButton ? "Synchronisierung läuft…" : "Aktivitäten werden aktualisiert…";
  try {
    const result = await api("/api/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    const periodLabel = result.activity_days === -1 ? "aller verfügbaren Daten" : `der letzten ${result.activity_days} Tage`;
    toast(result.status === "ok" ? `${result.activities} Aktivitäten ${periodLabel} aktualisiert${result.estimates ? ` · ${result.estimates} KI-Schätzungen ergänzt` : ""}` : "Aktualisierung läuft bereits");
    if (result.estimate_error) toast(`Trainingsdaten aktualisiert, KI-Schätzung fehlgeschlagen: ${result.estimate_error}`, true);
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.intervals = false; button.disabled = false; button.classList.remove("busy"); button.textContent = defaultCaption; updateHeaderAction(); }
}

async function refreshPerformance() {
  const button = $("#headerActionButton");
  if (!button) return;
  state.localSync.performance = true;
  button.disabled = true;
  button.textContent = "Aktualisierung läuft…";
  try {
    const result = await api("/api/performance/refresh", { method: "POST", body: "{}" });
    toast(result.status === "ok" ? `Leistungsdaten aktualisiert${result.estimates ? ` · ${result.estimates} KI-Schätzungen ergänzt` : ""}` : "Aktualisierung läuft bereits");
    if (result.estimate_error) toast(`Leistungsdaten aktualisiert, KI-Schätzung fehlgeschlagen: ${result.estimate_error}`, true);
    invalidateContextPreview();
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  }
  finally { state.localSync.performance = false; updateHeaderAction(); }
}

async function syncGarmin() {
  const button = $("#garminSyncButton");
  if (!button) return;
  state.localSync.garmin = true;
  button.disabled = true;
  button.textContent = "Garmin wird synchronisiert…";
  try {
    const configuredDays = $("#garminSyncDays")?.value || state.data?.sync_settings?.garmin_days || 30;
    const result = await api("/api/garmin/sync", { method: "POST", body: JSON.stringify({ days: configuredDays }) });
    toast(result.status === "ok" ? `Garmin synchronisiert${result.activities ? ` · ${result.activities} Aktivitäten` : ""}` : "Garmin-Synchronisierung läuft bereits");
    invalidateContextPreview();
    await load();
  } catch (error) { toast(error.message, true); await load(); }
  finally { state.localSync.garmin = false; button.disabled = false; button.textContent = "Garmin synchronisieren"; updateHeaderAction(); }
}

async function resetCoachChat() {
  const button = $("#chatResetButton");
  if (!button || !window.confirm("Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen?")) return;
  button.disabled = true;
  button.textContent = "Wird zurückgesetzt…";
  try {
    await api("/api/chat/reset", { method: "POST", body: "{}" });
    if (state.data) {
      state.data.messages = [];
      renderMessages([], true);
    }
    toast("Neuer Coach-Chat gestartet");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Chat zurücksetzen"; }
}

async function pushDraft(id, button) {
  button.disabled = true; button.textContent = "Wird übertragen…";
  try {
    await api(`/api/workouts/${id}/push`, { method: "POST", body: "{}" });
    toast("Training zu Intervals.icu übertragen");
  } catch (error) { toast(error.message, true); }
  finally { await load(); }
}

async function saveProfile(event) {
  event.preventDefault();
  const profile = { ...(state.data?.profile || {}), ...Object.fromEntries(new FormData(event.currentTarget)) };
  const payload = {
    profile,
    competitions: collectCompetitions(),
  };
  try {
    await api("/api/athlete-context", { method: "PUT", body: JSON.stringify(payload) });
    state.profileDirty = false;
    invalidateContextPreview();
    toast("Athletenkontext gespeichert und für den Coach aktiviert");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function saveModel(event) {
  const select = event.currentTarget;
  select.disabled = true;
  try {
    await api("/api/settings/model", { method: "PUT", body: JSON.stringify({ model: select.value }) });
    toast(`Aktiv: ${select.options[select.selectedIndex].text}`);
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  } finally { select.disabled = false; }
}

async function saveThinkingLevel(event) {
  const select = event.currentTarget;
  select.disabled = true;
  try {
    await api("/api/settings/thinking-level", { method: "PUT", body: JSON.stringify({ thinking_level: select.value }) });
    toast(`Thinking Level: ${select.options[select.selectedIndex].text}`);
    await load();
  } catch (error) {
    toast(error.message, true);
    await load();
  } finally { select.disabled = false; }
}

async function downloadDiagnostics() {
  const button = $("#diagnosticsButton");
  button.disabled = true;
  button.textContent = "Wird vorbereitet…";
  try {
    const report = await api("/api/diagnostics");
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `intervals-coach-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    toast("Diagnose heruntergeladen");
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; button.textContent = "Diagnose herunterladen"; }
}

async function downloadPrivacyExport() {
  try {
    const payload = await api("/api/privacy/export");
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "intervals-coach-export.json";
    link.click();
    URL.revokeObjectURL(link.href);
    toast("Datenexport erstellt");
  } catch (error) { toast(error.message, true); }
}

async function deletePrivacyData() {
  if (!window.confirm("Alle lokalen Chats, Snapshots, Entwürfe und Profile löschen? Dieser Schritt kann nicht rückgängig gemacht werden.")) return;
  try {
    await api("/api/privacy/delete", { method: "POST", body: JSON.stringify({ confirm: "DELETE" }) });
    toast("Lokale Daten gelöscht");
    await load();
  } catch (error) { toast(error.message, true); }
}

async function logout() {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (_) {}
  showLogin();
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item, .panel").forEach((node) => node.classList.remove("active"));
  button.classList.add("active");
  $(`#${button.dataset.panel}`).classList.add("active");
  if (state.data) renderStatus(state.data);
  updateHeaderAction();
  if (button.dataset.panel === "profilePanel") loadContextPreview();
  if (button.dataset.panel === "settingsPanel") loadLogs();
  window.scrollTo({ top: 0, behavior: "auto" });
  if (button.dataset.panel === "chatPanel") scrollChatToLatest(true);
}));

$("#loginForm").addEventListener("submit", login);
$("#chatForm").addEventListener("submit", sendMessage);
$("#headerActionButton").addEventListener("click", (event) => {
  if (event.currentTarget.dataset.action === "performance") refreshPerformance();
  else if (event.currentTarget.dataset.action === "activities") syncNow(event);
});
$("#systemIntervalsSyncButton").addEventListener("click", syncNow);
$("#garminSyncButton").addEventListener("click", syncGarmin);
$("#profileForm").addEventListener("submit", saveProfile);
$("#profileForm").addEventListener("input", () => { state.profileDirty = true; });
$("#addCompetitionButton").addEventListener("click", addCompetition);
$("#modelSelect").addEventListener("change", saveModel);
$("#thinkingLevelSelect").addEventListener("change", saveThinkingLevel);
$("#diagnosticsButton").addEventListener("click", downloadDiagnostics);
$("#logsRefreshButton").addEventListener("click", loadLogs);
$("#chatResetButton").addEventListener("click", resetCoachChat);
$("#privacyExportButton").addEventListener("click", downloadPrivacyExport);
$("#privacyDeleteButton").addEventListener("click", deletePrivacyData);
$("#logoutButton").addEventListener("click", logout);
$("#libraryLoadButton").addEventListener("click", loadLibrary);
$("#contextPreviewButton").addEventListener("click", () => {
  $("#contextPreviewButton").dataset.loaded = "false";
  loadContextPreview();
});
$("#messageInput").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 150)}px`;
});
$("#messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("#chatForm").requestSubmit();
  }
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js");
setInterval(() => {
  if (state.localSync.intervals || state.localSync.garmin || state.localSync.performance) load();
}, 1500);
bootstrapAuth();
