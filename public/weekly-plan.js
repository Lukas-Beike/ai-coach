// Weekly plan editor of the profile. The hidden field `weekly_plan` holds the
// canonical JSON that backend/athlete/weekly_plan.py validates and normalizes.
const WEEKLY_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const WEEKLY_DAY_LABELS = { mon: "Mo", tue: "Di", wed: "Mi", thu: "Do", fri: "Fr", sat: "Sa", sun: "So" };
const WEEKLY_SPORT_LABELS = { run: "Laufen", ride: "Rad", strength: "Kraft" };
const WEEKLY_WORKDAY = ["00:00-06:00", "12:00-13:00", "15:30-24:00"];
const WEEKLY_FALLBACK = { mon: WEEKLY_WORKDAY, tue: WEEKLY_WORKDAY, wed: WEEKLY_WORKDAY, thu: WEEKLY_WORKDAY, fri: ["14:00-24:00"], sat: ["00:00-24:00"], sun: ["00:00-24:00"] };
const WEEKLY_MAX_ROWS = 4;
const weeklyPlan = { model: { default: {}, days: {} }, open: new Set() };

function weeklyRow(text) {
  const [start = "", end = ""] = String(text || "").split("-");
  return { start, end: end === "24:00" ? "00:00" : end };
}

function weeklyWindowText(row) {
  if (!row.start || !row.end) return null;
  const end = row.end === "00:00" ? "24:00" : row.end;
  return row.start < end ? `${row.start}-${end}` : null;
}

function weeklyWindows(rows) {
  const merged = [];
  for (const text of rows.map(weeklyWindowText).filter(Boolean).sort()) {
    const [start, end] = text.split("-");
    const last = merged.at(-1);
    if (last && start <= last[1]) last[1] = end > last[1] ? end : last[1];
    else merged.push([start, end]);
  }
  return merged.slice(0, WEEKLY_MAX_ROWS).map((item) => item.join("-"));
}

function weeklyParse(text) {
  let source = {};
  try { source = JSON.parse(text || "{}") || {}; } catch { source = {}; }
  const model = { default: {}, days: {} };
  for (const day of WEEKLY_DAYS) {
    model.default[day] = (source.default?.[day] || []).map(weeklyRow);
    const item = source.days?.[day] || {};
    model.days[day] = {
      windows: (item.windows || []).map(weeklyRow),
      max: item.max_minutes ? String(item.max_minutes) : "",
      rest: item.rest_day === true,
      fixed: (item.fixed || []).map((fixed) => ({ sport: fixed.sport, focus: fixed.focus || "", minutes: fixed.minutes ? String(fixed.minutes) : "", ...weeklyRow(fixed.window) })),
    };
  }
  return model;
}

function weeklyFixedPayload(fixed) {
  const result = { sport: fixed.sport };
  if (fixed.focus) result.focus = fixed.focus;
  if (fixed.minutes) result.minutes = Number(fixed.minutes);
  const window = weeklyWindowText(fixed);
  if (window) result.window = window;
  return result;
}

function weeklyDayPayload(item) {
  if (item.rest) return { rest_day: true };
  const result = {};
  const windows = weeklyWindows(item.windows);
  if (windows.length) result.windows = windows;
  if (item.max) result.max_minutes = Number(item.max);
  if (item.fixed.length) result.fixed = item.fixed.map(weeklyFixedPayload);
  return result;
}

// Same key order as the backend, so an unchanged plan compares equal.
function weeklySerialize(model) {
  const result = {};
  const defaults = {};
  const days = {};
  for (const day of WEEKLY_DAYS) {
    const windows = weeklyWindows(model.default[day]);
    if (windows.length && windows.join() !== WEEKLY_FALLBACK[day].join()) defaults[day] = windows;
    const payload = weeklyDayPayload(model.days[day]);
    if (Object.keys(payload).length) days[day] = payload;
  }
  if (Object.keys(defaults).length) result.default = defaults;
  if (Object.keys(days).length) result.days = days;
  return Object.keys(result).length ? JSON.stringify(result) : "";
}

function weeklyCommit(form) {
  const field = form.elements.weekly_plan;
  const value = weeklySerialize(weeklyPlan.model);
  if (field.value === value) return;
  field.value = value;
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

function weeklyEffective(day) {
  const own = weeklyWindows(weeklyPlan.model.days[day].windows);
  if (own.length) return { windows: own, source: "profile" };
  const standard = weeklyWindows(weeklyPlan.model.default[day]);
  if (standard.length) return { windows: standard, source: "default" };
  return { windows: WEEKLY_FALLBACK[day], source: "fallback" };
}

function weeklySummary(day) {
  const item = weeklyPlan.model.days[day];
  const effective = weeklyEffective(day);
  const parts = [];
  if (item.rest) parts.push("Ruhetag");
  else parts.push(effective.windows.map((text) => text.replace("-", "–")).join(", "));
  if (!item.rest && item.max) parts.push(`max. ${item.max} min`);
  for (const fixed of item.fixed) parts.push([WEEKLY_SPORT_LABELS[fixed.sport], FOCUS_LABELS?.[fixed.focus], fixed.minutes ? `${fixed.minutes}′` : ""].filter(Boolean).join(" "));
  return { text: parts.join(" · "), source: item.rest ? "profile" : effective.source };
}

function weeklyElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function weeklyInput(type, value, label, onChange) {
  const input = document.createElement("input");
  input.type = type;
  input.value = value || "";
  input.setAttribute("aria-label", label);
  input.addEventListener("change", () => onChange(input.value, input));
  return input;
}

function weeklyButton(label, onClick, className = "secondary-button") {
  const button = weeklyElement("button", className, label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

function weeklyTimes(row, label, onChange) {
  let end = null;
  const validate = () => end.setCustomValidity(row.start && row.end && !weeklyWindowText(row) ? "Das Ende muss nach dem Beginn liegen." : "");
  const start = weeklyInput("time", row.start, `${label} von`, (value) => { row.start = value; validate(); onChange(); });
  end = weeklyInput("time", row.end, `${label} bis`, (value) => { row.end = value; validate(); onChange(); });
  validate();
  return [start, end];
}

function weeklyWindowEditor(rows, label, onChange) {
  const box = weeklyElement("div", "weekly-windows");
  rows.forEach((row, index) => {
    const line = weeklyElement("div", "weekly-line");
    line.append(...weeklyTimes(row, label, onChange), weeklyButton("✕", () => { rows.splice(index, 1); onChange(true); }, "secondary-button weekly-remove"));
    line.lastChild.setAttribute("aria-label", `${label} entfernen`);
    box.append(line);
  });
  if (rows.length < WEEKLY_MAX_ROWS) box.append(weeklyButton("+ Zeitfenster", () => { rows.push({ start: "", end: "" }); onChange(true); }));
  return box;
}

function weeklySelect(options, value, label, onChange) {
  const select = document.createElement("select");
  select.setAttribute("aria-label", label);
  for (const [key, text] of options) select.append(new Option(text, key, false, key === value));
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

function weeklyFixedEditor(item, onChange) {
  const box = weeklyElement("div", "weekly-fixed");
  item.fixed.forEach((fixed, index) => {
    const line = weeklyElement("div", "weekly-line weekly-fixed-line");
    const sports = Object.entries(WEEKLY_SPORT_LABELS);
    const foci = [["", "Art"], ...(FOCUS_OPTIONS[fixed.sport] || []).map((key) => [key, FOCUS_LABELS[key]])];
    line.append(
      weeklySelect(sports, fixed.sport, "Sportart", (value) => { fixed.sport = value; fixed.focus = ""; onChange(true); }),
      weeklySelect(foci, fixed.focus, "Art der Einheit", (value) => { fixed.focus = value; onChange(); }),
      weeklyInput("number", fixed.minutes, "Dauer in Minuten", (value) => { fixed.minutes = value; onChange(); }),
      ...weeklyTimes(fixed, "Feste Einheit", onChange),
      weeklyButton("✕", () => { item.fixed.splice(index, 1); onChange(true); }, "secondary-button weekly-remove"),
    );
    const [, , minutes, , , remove] = line.children;
    Object.assign(minutes, { min: 10, max: 600, step: 5, placeholder: "min" });
    remove.setAttribute("aria-label", "Feste Einheit entfernen");
    box.append(line);
  });
  if (item.fixed.length < WEEKLY_MAX_ROWS) box.append(weeklyButton("+ Feste Einheit", () => { item.fixed.push({ sport: "run", focus: "", minutes: "", start: "", end: "" }); onChange(true); }));
  return box;
}

function weeklyDayEditor(day, form, rerender) {
  const item = weeklyPlan.model.days[day];
  const details = weeklyElement("details", "weekly-day");
  details.open = weeklyPlan.open.has(day);
  details.addEventListener("toggle", () => weeklyPlan.open[details.open ? "add" : "delete"](day));
  const summary = weeklyElement("summary", "weekly-summary");
  const info = weeklySummary(day);
  const text = weeklyElement("span", "weekly-summary-text", info.text);
  text.dataset.source = info.source;
  summary.append(weeklyElement("strong", "", WEEKLY_DAY_LABELS[day]), text);
  const changed = (structural) => {
    weeklyCommit(form);
    if (structural) return rerender();
    const next = weeklySummary(day);
    text.textContent = next.text;
    text.dataset.source = next.source;
  };
  const rest = weeklyElement("label", "weekly-check");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = item.rest;
  box.addEventListener("change", () => { item.rest = box.checked; if (item.rest) item.fixed = []; changed(true); });
  rest.append(box, " Ruhetag");
  const body = weeklyElement("div", "weekly-body");
  body.append(rest);
  if (!item.rest) {
    const max = weeklyInput("number", item.max, "Maximale Minuten", (value) => { item.max = value; changed(); });
    Object.assign(max, { min: 15, max: 600, step: 5, placeholder: "Max. min" });
    body.append(weeklyWindowEditor(item.windows, "Zeitfenster", changed), max);
  }
  if (!item.rest) body.append(weeklyFixedEditor(item, changed));
  details.append(summary, body);
  return details;
}

function weeklyDefaultEditor(form, rerender) {
  const details = weeklyElement("details", "weekly-day weekly-default");
  details.open = weeklyPlan.open.has("default");
  details.addEventListener("toggle", () => weeklyPlan.open[details.open ? "add" : "delete"]("default"));
  details.append(weeklyElement("summary", "weekly-summary", "Standard-Zeitfenster"));
  const body = weeklyElement("div", "weekly-body");
  for (const day of WEEKLY_DAYS) {
    // The built-in hours are shown as editable rows but only stored once edited.
    const rows = weeklyPlan.model.default[day].length ? weeklyPlan.model.default[day] : WEEKLY_FALLBACK[day].map(weeklyRow);
    const line = weeklyElement("div", "weekly-default-day");
    line.append(weeklyElement("strong", "", WEEKLY_DAY_LABELS[day]), weeklyWindowEditor(rows, `Standard ${WEEKLY_DAY_LABELS[day]}`, (structural) => {
      weeklyPlan.model.default[day] = rows;
      weeklyCommit(form);
      if (structural) rerender();
    }));
    body.append(line);
  }
  details.append(body);
  return details;
}

function renderWeeklyPlan(form, reparse = true) {
  const host = form?.querySelector("#weeklyPlanEditor");
  if (!host) return;
  if (reparse) weeklyPlan.model = weeklyParse(form.elements.weekly_plan.value);
  const rerender = () => renderWeeklyPlan(form, false);
  host.replaceChildren(...WEEKLY_DAYS.map((day) => weeklyDayEditor(day, form, rerender)), weeklyDefaultEditor(form, rerender));
}
