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

function createActionReceipt({ title, message, status = "success", details = [] } = {}) {
  const root = document.createElement("article");
  root.className = `action-receipt${status === "error" ? " is-error" : ""}`;
  root.setAttribute("role", status === "error" ? "alert" : "status");
  const heading = document.createElement("div");
  heading.className = "action-receipt-heading";
  const label = document.createElement("strong");
  label.textContent = title || "Aktion";
  heading.append(label, createStatusChip(status === "error" ? "Fehler" : "Erledigt", status === "error" ? "error" : "ready"));
  root.append(heading);
  if (message) {
    const copy = document.createElement("p");
    copy.textContent = message;
    root.append(copy);
  }
  if (details.length) {
    const list = document.createElement("ul");
    details.slice(0, 4).forEach((detail) => {
      const item = document.createElement("li");
      item.textContent = detail;
      list.append(item);
    });
    root.append(list);
  }
  return root;
}
