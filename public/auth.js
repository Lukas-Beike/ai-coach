function cookie(name) {
  return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
}

// True while the app is locked behind the login dialog. Escape must not leave
// the athlete on a blank app, so the dialog is kept open until login succeeds.
let loginDialogRequired = false;

function showLogin() {
  cancelBootstrapRetry();
  state.sessionGeneration += 1;
  clearStateSnapshot();
  state.voiceAcquiring = false;
  stopVoiceRecording();
  stopVoiceCapture();
  state.chatGeneration += 1;
  state.loadSequence += 1;
  state.pendingLoads.clear();
  state.loadPromise = null;
  state.requestedStateVersions = {};
  cancelDeferredLoads();
  state.initialStateLoaded = false;
  state.chatStatusPollInFlight = null;
  state.chatStatusRecheck = false;
  state.chatStatusTurnEnded = false;
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
  state.stateEventReady = false;
  state.stateEventBaselined = false;
  state.stateEventActivityAt = 0;
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
  clearAnalysisReportCache();
  AppState.setPlanSegment("overview");
  state.profileDirty = false;
  state.checkinDirty = false;
  state.chatAttachments = [];
  renderChatAttachments();
  state.chatDraftDirty = false;
  $("#appShell").hidden = true;
  $("#authLoading").hidden = true;
  const dialog = $("#loginDialog");
  loginDialogRequired = true;
  showAccessibleDialog(dialog, $("#loginPassword"));
}

function installLoginDialogGuards() {
  const dialog = $("#loginDialog");
  if (!dialog) return;
  dialog.addEventListener("cancel", (event) => {
    if (loginDialogRequired) event.preventDefault();
  });
  dialog.addEventListener("close", () => {
    if (!loginDialogRequired) return;
    // Defer so the global close handler restores focus first; the password field must keep focus.
    // Only reopen while the app shell is still locked, so a programmatic session handover is not undone.
    setTimeout(() => {
      if (loginDialogRequired && !dialog.open && $("#appShell").hidden) showAccessibleDialog(dialog, $("#loginPassword"));
    }, 0);
  });
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

// After an app update the loading screen says that the update is processed.
function showAppShellLoading({ updated = false } = {}) {
  const shell = $("#appShell");
  const statusCard = $("#statusCard");
  const loader = $("#authLoading");
  const title = updated ? "Update wird verarbeitet…" : "Trainingsbereich wird geladen…";
  loader.hidden = false;
  loader.textContent = title;
  shell.hidden = true;
  shell.classList.add("is-loading");
  shell.setAttribute("aria-busy", "true");
  statusCard.hidden = false;
  statusCard.classList.remove("warning");
  statusCard.classList.add("working");
  $("#statusTitle").textContent = title;
  $("#statusDetail").textContent = updated ? "Die App wurde aktualisiert. Deine Trainingsdaten werden neu geladen." : "Deine Trainingsdaten werden im Hintergrund geladen";
}

// Shows the device snapshot before the session check, so a start does not wait
// for the network. The fresh bootstrap replaces it; an unauthenticated start
// clears it through showLogin.
function showStateSnapshot(snapshot) {
  if (!snapshot) return false;
  state.replaceDataOnLoad = true;
  try {
    render(snapshot.data);
  } catch {
    // A snapshot from earlier assets may not fit the current views.
    clearStateSnapshot();
    state.data = null;
    state.replaceDataOnLoad = false;
    return false;
  }
  finishAppShellLoading();
  return true;
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

// The server can be unreachable while the device stays online, so the session
// check also retries after a delay, not only when the connection returns.
const BOOTSTRAP_RETRY_MS = 15_000;

let cancelBootstrapRetry = () => {};

function retryBootstrapAuth() {
  cancelBootstrapRetry();
  const retry = () => {
    cancelBootstrapRetry();
    void bootstrapAuth();
  };
  const timer = setTimeout(retry, BOOTSTRAP_RETRY_MS);
  globalThis.addEventListener("online", retry, { once: true });
  cancelBootstrapRetry = () => {
    clearTimeout(timer);
    globalThis.removeEventListener("online", retry);
    cancelBootstrapRetry = () => {};
  };
}

async function bootstrapAuth() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  const snapshot = state.data ? null : readStateSnapshot();
  // A snapshot from earlier assets waits behind the update loading screen, so the
  // new views start with fresh data.
  const updated = Boolean(snapshot?.updated);
  const shellShown = Boolean(state.data) || (!updated && showStateSnapshot(snapshot));
  if (updated) showAppShellLoading({ updated });
  try {
    const status = await globalThis.AppApi.request("/api/auth/status", { cache: "no-store", signal: controller.signal });
    renderMaintenanceStatus(status.maintenance);
    if (status.authenticated) {
      $("#authLoading").hidden = true;
      loginDialogRequired = false;
      $("#loginDialog").close();
      if (!shellShown) showAppShellLoading({ updated });
      notePwaActivity();
      await loadInitialState();
    } else showLogin();
  } catch {
    renderConnectivityStatus(false);
    if (shellShown || (updated && showStateSnapshot(snapshot))) {
      // An offline start keeps the stored data and checks the session again later.
      retryBootstrapAuth();
      return;
    }
    $("#loginError").textContent = "Server nicht erreichbar.";
    showLogin();
  } finally { clearTimeout(timeout); }
}


// Maps a failed login request to its own message. A wrong password (401), the
// request timeout and a missing connection keep the text api() already built.
function loginErrorMessage(exception) {
  const status = exception?.status;
  if (status === 429) {
    const seconds = Number(exception.retryAfter);
    const wait = !(seconds > 0) ? "" : seconds < 60 ? ` in ${Math.ceil(seconds)} Sekunden` : ` in etwa ${Math.ceil(seconds / 60)} Minuten`;
    return `Zu viele Anmeldeversuche. Bitte${wait} erneut versuchen.`;
  }
  if (status >= 500) return "Der Server startet gerade oder ist ausgelastet. Bitte in wenigen Sekunden erneut versuchen.";
  return exception.message;
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
    loginDialogRequired = false;
    $("#loginDialog").close();
    showAppShellLoading();
    notePwaActivity();
    await loadInitialState();
  } catch (exception) {
    error.textContent = loginErrorMessage(exception);
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    buttonLabel.textContent = "Anmelden";
  }
}


async function logout() {
  if (!await confirmDiscardChanges()) return;
  const confirmed = await requestConfirmation("Du wirst auf diesem Gerät abgemeldet. Deine Daten bleiben verschlüsselt gespeichert.", { title: "Abmelden?" });
  if (!confirmed) return;
  try {
    await api("/api/logout", { method: "POST", body: "{}" });
  } catch (error) {
    // api() has already shown the login for a 401 or an ended session; any other failure
    // leaves the server session valid, so the app stays open and the athlete can retry.
    if (error?.name !== "AbortError" && error?.status !== 401) toast("Abmelden fehlgeschlagen. Bitte erneut versuchen.", true);
    return;
  }
  showLogin();
}
