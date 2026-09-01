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
