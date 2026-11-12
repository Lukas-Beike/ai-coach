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
  const text = document.createElement("span");
  text.className = "status-strip-text";
  const title = document.createElement("strong");
  title.textContent = item.title;
  text.append(title);
  const stand = item.stand ? statusStandLabel(statusStandAt()) : "";
  const detail = [item.detail, stand].filter(Boolean).join(" ");
  if (detail) {
    const detailNode = document.createElement("span");
    detailNode.className = "status-strip-detail";
    detailNode.textContent = ` ${detail}`;
    text.append(detailNode);
  }
  return text;
}

function statusStripAction(item) {
  if (!item.action) return null;
  const link = document.createElement("a");
  link.className = "status-strip-action";
  link.href = item.action.href;
  link.textContent = item.action.label;
  return link;
}

function statusStripDismiss(item) {
  if (!item.dismiss) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button status-strip-dismiss";
  button.setAttribute("aria-label", "Für diese Sitzung ausblenden");
  button.title = "Für diese Sitzung ausblenden";
  button.textContent = "✕";
  button.addEventListener("click", () => {
    item.dismiss();
    // The focused button is gone with the notice; keep the keyboard user on the page.
    const main = document.querySelector("main");
    if (main) { main.tabIndex = -1; main.focus({ preventScroll: true }); }
  });
  return button;
}

function statusStripListEntry(item, top) {
  const entry = document.createElement("li");
  entry.dataset.level = item.level;
  entry.dataset.statusKey = item.key;
  if (top) entry.dataset.top = "true";
  entry.append(statusStripLine(item), ...[statusStripAction(item), statusStripDismiss(item)].filter(Boolean));
  return entry;
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
  const signature = JSON.stringify([expandedNow, items.map((item) => [item.key, item.level, item.title, item.detail || "", item.stand ? stand : "", item.action?.href || "", item.action?.label || "", Boolean(item.dismiss)])]);
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

  const main = document.createElement("div");
  main.className = "status-strip-main";
  const dot = document.createElement("span");
  dot.className = "status-strip-dot";
  dot.setAttribute("aria-hidden", "true");
  const more = document.createElement("button");
  more.type = "button";
  more.className = "status-strip-more secondary-button";
  more.setAttribute("aria-controls", "statusStripList");
  const expanded = expandedNow;
  more.setAttribute("aria-expanded", String(expanded));
  const suffix = items.length === 1 ? "Hinweis" : "Hinweise";
  const allLabel = document.createElement("span");
  allLabel.className = "status-strip-more-all";
  allLabel.textContent = `${items.length} ${suffix}`;
  more.append(allLabel);
  if (rest.length) {
    const moreLabel = document.createElement("span");
    moreLabel.className = "status-strip-more-rest";
    moreLabel.textContent = `+${rest.length} ${rest.length === 1 ? "Hinweis" : "Hinweise"}`;
    more.prepend(moreLabel);
  }
  more.addEventListener("click", toggleStatusStripList);
  main.append(dot, statusStripLine(top), ...[statusStripAction(top), statusStripDismiss(top)].filter(Boolean), more);

  const list = document.createElement("ul");
  list.id = "statusStripList";
  list.className = "status-strip-list";
  list.hidden = !expanded;
  list.append(...items.map((item, index) => statusStripListEntry(item, index === 0)));
  strip.replaceChildren(main, list);
}

function toggleStatusStripList() {
  const strip = document.querySelector("#statusStrip");
  if (!strip) return;
  strip.dataset.expanded = strip.dataset.expanded === "true" ? "false" : "true";
  renderStatusStrip();
  strip.querySelector(".status-strip-more")?.focus();
}
