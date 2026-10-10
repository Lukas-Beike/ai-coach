function cookie(name) {
  return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
}

function showLogin() {
  state.sessionGeneration += 1;
  state.voiceAcquiring = false;
  stopVoiceRecording();
  stopVoiceCapture();
  state.chatGeneration += 1;
  state.loadSequence += 1;
  state.pendingLoads.clear();
  state.loadPromise = null;
  state.initialStateLoaded = false;
  state.chatStatusPollInFlight = null;
  state.chatStream?.controller.abort();
  state.chatStream = null;
  state.chatQueue = [];
  state.rejectedMessages = [];
  state.coachActionProposals = [];
  state.coachReceipts = [];
  state.voiceTranscribing = false;
  rememberChatTurn(null);
  if (state.chatStatusTimer) clearTimeout(state.chatStatusTimer);
  state.chatStatusTimer = null;
  disconnectStateEvents();
  if (state.stateEventRefreshTimer) clearTimeout(state.stateEventRefreshTimer);
  state.stateEventReconnectTimer = null;
  state.stateEventRefreshTimer = null;
  state.stateEventRefreshAreas.clear();
  state.stateEventLastId = 0;
  state.stateEventBackoff = 1000;
  state.data = null;
  globalThis.ActivityDetails?.close();
  resetNutritionView();
  state.busy = false;
  state.chatRequest = null;
  state.chatStreamText = "";
  state.chatServerOperationId = null;
  state.chatResponseStarted = false;
  state.chatResponseScrollPending = false;
  state.chatResponseMessageId = null;
  state.chatProposalRefreshPending = false;
  state.chatProposalRefreshInFlight = false;
  state.chatProposalRefreshQueued = false;
  state.chatInitialScrollPending = true;
  state.chatScrollY = null;
  state.chatScrollRestoring = false;
  cancelScheduledChatStreamRender();
  state.loadedAreas.clear();
  AppState.setPlanSegment("overview");
  state.profileDirty = false;
  state.checkinDirty = false;
  state.chatAttachments = [];
  renderChatAttachments();
  state.chatDraftDirty = false;
  $("#appShell").hidden = true;
  $("#authLoading").hidden = true;
  const dialog = $("#loginDialog");
  showAccessibleDialog(dialog, $("#loginPassword"));
}

let confirmationResolver = null;
let confirmationGeneration = 0;
let confirmationSecondaryPending = false;

// Keeps the confirm button disabled until the typed text matches exactly and no secondary action (such as a backup) is running.
function syncConfirmationAcceptState() {
  const dialog = $("#confirmationDialog");
  const input = $("#confirmationDialogInput");
  const acceptButton = $("#confirmationDialogAccept");
  if (!dialog || !input || !acceptButton) return;
  const expectedText = dialog.dataset.expectedText || "";
  acceptButton.disabled = confirmationSecondaryPending || (Boolean(expectedText) && input.value !== expectedText);
}

function requestConfirmation(message, {
  title = "Aktion bestätigen",
  inputLabel = "",
  expectedText = "",
  confirmLabel = "Bestätigen",
  secondaryAction = null,
} = {}) {
  const dialog = $("#confirmationDialog");
  const form = $("#confirmationDialogForm");
  const messageNode = $("#confirmationDialogMessage");
  const titleNode = $("#confirmationDialogTitle");
  const inputLabelNode = $("#confirmationDialogInputLabel");
  const input = $("#confirmationDialogInput");
  const expectedNode = $("#confirmationDialogExpected");
  const acceptButton = $("#confirmationDialogAccept");
  const secondaryButton = $("#confirmationDialogSecondary");
  const errorNode = $("#confirmationDialogError");
  if (!dialog || !form || !messageNode || !titleNode || !inputLabelNode || !input || !expectedNode || !acceptButton || !secondaryButton) {
    return Promise.resolve(false);
  }
  confirmationGeneration += 1;
  confirmationSecondaryPending = false;
  if (confirmationResolver) confirmationResolver(false);
  dialog.dataset.expectedText = expectedText;
  titleNode.textContent = title;
  messageNode.textContent = message;
  expectedNode.hidden = !expectedText;
  expectedNode.textContent = expectedText ? `Tippe „${expectedText}“ zur Bestätigung.` : "";
  if (expectedText) input.setAttribute("aria-describedby", expectedNode.id);
  else input.removeAttribute("aria-describedby");
  inputLabelNode.hidden = !expectedText;
  inputLabelNode.firstChild.textContent = inputLabel || "Bestätigungstext";
  input.value = "";
  input.required = Boolean(expectedText);
  input.setCustomValidity("");
  input.oninput = syncConfirmationAcceptState;
  acceptButton.textContent = confirmLabel;
  // The secondary action never settles the confirmation; the dialog stays open.
  secondaryButton.hidden = !secondaryAction;
  secondaryButton.textContent = secondaryAction?.label || "";
  secondaryButton.onclick = secondaryAction ? () => { void runConfirmationSecondaryAction(secondaryAction.onClick); } : null;
  secondaryButton.disabled = false;
  secondaryButton.removeAttribute("aria-busy");
  if (errorNode) { errorNode.hidden = true; errorNode.textContent = ""; }
  syncConfirmationAcceptState();
  return new Promise((resolve) => {
    confirmationResolver = resolve;
    showAccessibleDialog(dialog, expectedText ? input : $("#confirmationDialogCancel"));
  });
}

function settleConfirmation(value) {
  const resolve = confirmationResolver;
  confirmationResolver = null;
  if (resolve) resolve(value);
}

// Runs the secondary action (e.g. a backup) and keeps the confirm button locked until it has succeeded.
// A failure stays visible in the dialog and the action remains available for a retry.
async function runConfirmationSecondaryAction(onClick) {
  const generation = confirmationGeneration;
  const secondaryButton = $("#confirmationDialogSecondary");
  const errorNode = $("#confirmationDialogError");
  confirmationSecondaryPending = true;
  secondaryButton.disabled = true;
  secondaryButton.setAttribute("aria-busy", "true");
  if (errorNode) { errorNode.hidden = true; errorNode.textContent = ""; }
  syncConfirmationAcceptState();
  try {
    await onClick();
  } catch (error) {
    if (generation === confirmationGeneration && errorNode) {
      errorNode.textContent = error.message;
      errorNode.hidden = false;
    }
  } finally {
    // A dialog that was cancelled or replaced while the action ran must not be touched.
    if (generation === confirmationGeneration) {
      confirmationSecondaryPending = false;
      secondaryButton.disabled = false;
      secondaryButton.removeAttribute("aria-busy");
      syncConfirmationAcceptState();
    }
  }
}

function showAppShellLoading() {
  const shell = $("#appShell");
  const statusCard = $("#statusCard");
  const loader = $("#authLoading");
  loader.hidden = false;
  loader.textContent = "Trainingsbereich wird geladen…";
  shell.hidden = true;
  shell.classList.add("is-loading");
  shell.setAttribute("aria-busy", "true");
  statusCard.hidden = false;
  statusCard.classList.remove("warning");
  statusCard.classList.add("working");
  $("#statusTitle").textContent = "Trainingsbereich wird geladen…";
  $("#statusDetail").textContent = "Deine Trainingsdaten werden im Hintergrund geladen";
}

function finishAppShellLoading() {
  const shell = $("#appShell");
  $("#authLoading").hidden = true;
  if (!$("#loginDialog")?.open) shell.hidden = false;
  shell.classList.remove("is-loading");
  shell.removeAttribute("aria-busy");
  // The first local bootstrap deliberately renders the chat while the shell is
  // still loading. Re-render after removing that state so its placeholder is
  // replaced even if a deferred domain request has not settled yet.
  renderMessages(state.data?.messages || [], true);
  void AppRouter.navigate(AppRouter.routeFromHash(), { historyMode: AppRouter.hashContainsKnownRoute() ? "none" : "replace" });
}

async function bootstrapAuth() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  try {
    const status = await globalThis.AppApi.request("/api/auth/status", { cache: "no-store", signal: controller.signal });
    renderMaintenanceStatus(status.maintenance);
    if (status.authenticated) {
      $("#authLoading").hidden = true;
      $("#loginDialog").close();
      showAppShellLoading();
      notePwaActivity();
      await loadInitialState();
    } else showLogin();
  } catch {
    renderConnectivityStatus(false);
    $("#loginError").textContent = "Server nicht erreichbar.";
    showLogin();
  } finally { clearTimeout(timeout); }
}


async function login(event) {
  event.preventDefault();
  const button = $("#loginButton");
  const buttonLabel = $("#loginButtonLabel");
  const error = $("#loginError");
  button.disabled = true;
  button.classList.add("is-loading");
  button.setAttribute("aria-busy", "true");
  buttonLabel.textContent = "Anmelden …";
  error.textContent = "";
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("#loginPassword").value }) });
    $("#loginPassword").value = "";
    $("#loginDialog").close();
    showAppShellLoading();
    notePwaActivity();
    await loadInitialState();
  } catch (exception) {
    error.textContent = exception.message;
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    buttonLabel.textContent = "Anmelden";
  }
}


async function logout() {
  if (!await confirmDiscardChanges()) return;
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch { }
  showLogin();
}
