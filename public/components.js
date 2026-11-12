// One element builder (#2111): props is a class name or an object of properties
// (`aria-*`/`data-*` become attributes, `dataset` merges); children are nodes or text,
// arrays are flattened, and null, undefined and false are skipped.
function h(tag, props = null, ...children) {
  const element = document.createElement(tag);
  const entries = typeof props === "string" ? [["className", props || null]] : Object.entries(props || {});
  for (const [key, value] of entries) {
    if (value == null) continue;
    if (key === "dataset") Object.assign(element.dataset, value);
    else if (key.includes("-")) element.setAttribute(key, String(value));
    else element[key] = value;
  }
  for (const child of children.flat()) if (child != null && child !== false) element.append(typeof child === "object" ? child : String(child));
  return element;
}

const SVG_NS = "http://www.w3.org/2000/svg";

function svgNode(tag, attributes = {}, content = "") {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  element.textContent = content;
  return element;
}

// A data table: column headers get scope=col; a td or th cell is kept, anything else goes into a td.
function table(columns, rows, { className = "", caption = "" } = {}) {
  const head = h("tr", null, ...columns.map((label) => h("th", { scope: "col" }, label)));
  const body = h("tbody", null, ...rows.map((cells) => h("tr", null, ...cells.map((cell) => (["TD", "TH"].includes(cell?.tagName) ? cell : h("td", null, cell))))));
  return h("table", className, caption ? h("caption", null, caption) : null, h("thead", null, head), body);
}

const dialogFocusReturn = new WeakMap();

function showAccessibleDialog(dialog, initialFocus = null) {
  if (!dialog) return;
  const active = document.activeElement;
  dialogFocusReturn.set(dialog, active instanceof HTMLElement && active !== document.body ? active : null);
  if (!dialog.open) dialog.showModal();
  const target = initialFocus || dialog.querySelector("button, input, textarea, select, [tabindex]:not([tabindex='-1'])");
  if (target instanceof HTMLElement) target.focus({ preventScroll: true });
}

function restoreDialogFocus(dialog) {
  const target = dialogFocusReturn.get(dialog);
  dialogFocusReturn.delete(dialog);
  if (target instanceof HTMLElement && target.isConnected && !target.disabled && !target.closest("[hidden]")) {
    target.focus({ preventScroll: true });
  }
}

function createStatusChip(label, status = "") {
  const chip = document.createElement("span");
  chip.className = "status-chip";
  if (status) chip.dataset.status = status;
  chip.textContent = label;
  return chip;
}

// One chip marks every derived or estimated value (#1789).
function createEstimateChip() {
  const chip = createStatusChip("Schätzung", "estimate");
  chip.classList.add("estimate-chip");
  return chip;
}

function createEmptyState(title, description, action = null) {
  const root = document.createElement("div");
  root.className = "empty-state";
  const heading = document.createElement("strong");
  heading.textContent = title;
  root.append(heading);
  if (description) {
    const copy = document.createElement("span");
    copy.textContent = description;
    root.append(copy);
  }
  if (action) root.append(action);
  return root;
}

// Loading, failed and absent data look different (#1783): a busy line, a warning card
// with one retry action, and a muted "nicht erfasst" value.
const DATA_LOAD_TIMEOUT_MS = 15_000;

function createLoadingState(text) {
  const root = document.createElement("p");
  root.className = "loading-state";
  root.setAttribute("role", "status");
  root.setAttribute("aria-busy", "true");
  root.textContent = text;
  return root;
}

function createErrorState(message, onRetry) {
  const root = document.createElement("div");
  root.className = "error-state";
  root.setAttribute("role", "alert");
  const heading = document.createElement("strong");
  heading.textContent = "Konnte nicht geladen werden.";
  root.append(heading);
  if (message) {
    const copy = document.createElement("span");
    copy.textContent = message;
    root.append(copy);
  }
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "secondary-button";
  retry.textContent = "Erneut versuchen";
  retry.addEventListener("click", () => { retry.disabled = true; onRetry(); }, { once: true });
  root.append(retry);
  return root;
}

function markValueMissing(element, text = "nicht erfasst") {
  element.textContent = text;
  element.classList.add("value-missing");
  return element;
}

function createSkeletonStack(rows = 3) {
  const root = document.createElement("div");
  root.className = "skeleton-stack";
  for (let index = 0; index < rows; index += 1) {
    const row = document.createElement("div");
    row.className = "skeleton-row";
    row.append(Object.assign(document.createElement("span"), { className: "skeleton skeleton-avatar" }));
    const copy = document.createElement("div");
    copy.className = "skeleton-copy";
    copy.append(Object.assign(document.createElement("span"), { className: "skeleton" }));
    copy.append(Object.assign(document.createElement("span"), { className: "skeleton skeleton-short" }));
    row.append(copy);
    root.append(row);
  }
  return root;
}

