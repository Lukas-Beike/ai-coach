// One status strip above every screen (#1784): the most severe notice as text,
// the others behind "+N Hinweise". Sources set or clear their own notice by key;
// the strip ranks them and renders once.

// Order of severity, first = shown first. Loading is exclusive and always wins.
const STATUS_SOURCE_RANK = {
  loading: 0,
  maintenance: 1,
  offline: 2,
  openai: 3,
  coach_error: 4,
  load_failure: 5,
  provider: 6,
  provider_key: 7,
  thresholds: 8,
  intervals_key: 9,
};
const STATUS_STAND_REFRESH_MS = 60_000;

const statusSources = new Map();
let statusStandTimer = null;

// Pure: the notices in display order. Slim info lines only show when nothing else does.
function statusStripItems(sources) {
  const items = [...sources.entries()]
    .filter(([key]) => key in STATUS_SOURCE_RANK)
    .map(([key, item]) => ({ ...item, key, rank: STATUS_SOURCE_RANK[key] }))
    .sort((a, b) => a.rank - b.rank);
  if (items[0]?.level === "working") return [items[0]];
  const important = items.filter((item) => item.level !== "info");
  return important.length ? important : items;
}

// Pure: "Stand vor 5 min" for data shown from the device.
function statusStandLabel(standAt, now = Date.now()) {
  const stand = Number(standAt);
  if (!Number.isFinite(stand) || stand <= 0) return "";
  const minutes = Math.max(0, Math.floor((now - stand) / 60_000));
  if (minutes < 1) return "Stand gerade eben";
  if (minutes < 60) return `Stand vor ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return hours < 48 ? `Stand vor ${hours} h` : `Stand vor ${Math.floor(hours / 24)} Tagen`;
}

function statusStandAt() {
  return typeof state === "undefined" ? null : state.dataStandAt;
}

// Sets (item) or clears (null) the notices; "stand" adds the age of the shown data.
function updateStatusSources(changes) {
  for (const [key, item] of Object.entries(changes)) {
    if (item) statusSources.set(key, item);
    else statusSources.delete(key);
  }
  renderStatusStrip();
}

function statusStripLine(item) {
  const stand = item.stand ? statusStandLabel(statusStandAt()) : "";
  const detail = [item.detail, stand].filter(Boolean).join(" ");
  return h("span", "status-strip-text", h("strong", null, item.title), detail ? h("span", "status-strip-detail", ` ${detail}`) : null);
}

function statusStripAction(item) {
  if (!item.action) return null;
  const dataset = item.action.connection ? { connection: item.action.connection } : null;
  return h("a", { className: "status-strip-action", href: item.action.href, dataset }, item.action.label);
}

function statusStripDismiss(item) {
  if (!item.dismiss) return null;
  const button = h("button", { type: "button", className: "secondary-button status-strip-dismiss", "aria-label": "Für diese Sitzung ausblenden", title: "Für diese Sitzung ausblenden" }, "✕");
  button.addEventListener("click", () => {
    item.dismiss();
    // The focused button is gone with the notice; keep the keyboard user on the page.
    const main = document.querySelector("main");
    if (main) { main.tabIndex = -1; main.focus({ preventScroll: true }); }
  });
  return button;
}

function statusStripListEntry(item, top) {
  const dataset = { level: item.level, statusKey: item.key, ...(top ? { top: "true" } : {}) };
  return h("li", { dataset }, statusStripLine(item), statusStripAction(item), statusStripDismiss(item));
}

function renderStatusStrip() {
  const strip = document.querySelector("#statusStrip");
  if (!strip) return;
  const items = statusStripItems(statusSources);
  clearTimeout(statusStandTimer);
  statusStandTimer = null;
  strip.hidden = !items.length;
  if (!items.length) {
    strip.replaceChildren();
    delete strip.dataset.level;
    delete strip.dataset.signature;
    strip.dataset.expanded = "false";
    return;
  }
  const stand = statusStandLabel(statusStandAt());
  const expandedNow = strip.dataset.expanded === "true";
  // An unchanged strip is left alone, so assistive technology does not announce it again.
  const signature = JSON.stringify([expandedNow, items.map((item) => [item.key, item.level, item.title, item.detail || "", item.stand ? stand : "", item.action?.href || "", item.action?.label || "", item.action?.connection || "", Boolean(item.dismiss)])]);
  if (items.some((item) => item.stand)) statusStandTimer = setTimeout(renderStatusStrip, STATUS_STAND_REFRESH_MS);
  if (strip.dataset.signature === signature) return;
  strip.dataset.signature = signature;
  const [top, ...rest] = items;
  const level = top.level;
  strip.dataset.level = level;
  strip.classList.toggle("working", level === "working");
  strip.classList.toggle("has-more", rest.length > 0);
  // Only hard problems interrupt assistive technology.
  const alert = level === "critical";
  if (strip.getAttribute("role") !== (alert ? "alert" : "status")) strip.setAttribute("role", alert ? "alert" : "status");
  strip.setAttribute("aria-live", alert ? "assertive" : "polite");

  const hints = (count) => `${count} ${count === 1 ? "Hinweis" : "Hinweise"}`;
  const more = h("button", { type: "button", className: "status-strip-more secondary-button", "aria-controls": "statusStripList", "aria-expanded": String(expandedNow) },
    rest.length ? h("span", "status-strip-more-rest", `+${hints(rest.length)}`) : null,
    h("span", "status-strip-more-all", hints(items.length)));
  more.addEventListener("click", toggleStatusStripList);
  const main = h("div", "status-strip-main", h("span", { className: "status-strip-dot", "aria-hidden": "true" }), statusStripLine(top), statusStripAction(top), statusStripDismiss(top), more);
  const list = h("ul", { id: "statusStripList", className: "status-strip-list", hidden: !expandedNow }, ...items.map((item, index) => statusStripListEntry(item, index === 0)));
  strip.replaceChildren(main, list);
}

function toggleStatusStripList() {
  const strip = document.querySelector("#statusStrip");
  if (!strip) return;
  strip.dataset.expanded = strip.dataset.expanded === "true" ? "false" : "true";
  renderStatusStrip();
  strip.querySelector(".status-strip-more")?.focus();
}
