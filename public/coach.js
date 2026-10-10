/** Own Coach submission, queue, streaming, polling, cancellation and recovery. */
function resetChatAfterGenerationChange(currentTurn) {
  if (state.chatRequest?.message) {
    state.rejectedMessages.push({ role: "user", content: state.chatRequest.message, client_turn_id: currentTurn,
      error: "Der Chat wurde zurückgesetzt. Prüfe den Verlauf, bevor du diese Nachricht erneut sendest." });
  }
  state.chatGeneration += 1;
  state.chatStream?.controller.abort();
  state.chatStream = null;
  state.chatRequest = null;
  state.chatServerOperationId = null;
  state.busy = false;
  rememberChatTurn(null);
}

function scheduleChatStatusPoll(delay = 1_500) {
  if (state.chatStatusTimer) clearTimeout(state.chatStatusTimer);
  state.chatStatusTimer = setTimeout(() => {
    state.chatStatusTimer = null;
    void pollChatStatus();
  }, delay);
}

function chatStatusJobActive() {
  return Boolean(state.busy || state.chatRequest || state.chatServerOperationId || state.chatStream || pendingChatTurn());
}

function chatStatusPollWanted() {
  return document.visibilityState === "visible" && chatStatusJobActive();
}

function stopChatStatusPoll() {
  if (state.chatStatusTimer) clearTimeout(state.chatStatusTimer);
  state.chatStatusTimer = null;
}

async function loadChatHistoryFresh() {
  await refreshChatHistoryState();
}

async function refreshChatProposalsInBackground(expectedContentVersion) {
  if (AppRouter.baseRoute() !== "coach") return;
  if (state.chatProposalRefreshInFlight) {
    state.chatProposalRefreshQueued = true;
    return;
  }
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  state.chatProposalRefreshInFlight = true;
  try {
    await refreshChatHistoryState();
    if (sessionGeneration !== state.sessionGeneration
      || chatGeneration !== state.chatGeneration
      || expectedContentVersion !== state.chatContentVersion) return;
  } catch (_) {
    // Keep the pending flag so the next completed turn retries the authoritative refresh.
  } finally {
    state.chatProposalRefreshInFlight = false;
    const retryAtLatestVersion = state.chatProposalRefreshPending && state.chatProposalRefreshQueued;
    state.chatProposalRefreshQueued = false;
    if (retryAtLatestVersion && AppRouter.baseRoute() === "coach") void refreshChatProposalsInBackground(state.chatContentVersion);
  }
}

async function resumeQueuedChat() {
  if (!state.chatQueue.length || state.chatRequest || state.chatServerOperationId) {
    if (!state.chatQueue.length && !state.chatRequest && !state.chatServerOperationId) {
      state.busy = false;
      renderQuickMessageTemplates();
      renderMessages(state.data?.messages || [], true);
      updateChatControls();
    }
    return;
  }
  const next = state.chatQueue.shift();
  renderMessages(state.data?.messages || [], true);
  try {
    await drainChatQueue(next.message, next.requestKind, next.attachments);
  } catch (error) {
    toast(error.message, true);
  } finally {
    if (!state.chatRequest && !state.chatServerOperationId) state.busy = false;
    renderQuickMessageTemplates();
    renderMessages(state.data?.messages || [], true);
    updateChatControls();
  }
}

function chatPollStateIsCurrent(sessionGeneration, chatGeneration) {
  return sessionGeneration === state.sessionGeneration && chatGeneration === state.chatGeneration;
}

function pendingChatTurn() {
  if (state.chatRequest?.clientTurnId) return state.chatRequest.clientTurnId;
  try {
    return sessionStorage.getItem("coachPendingTurn");
  } catch {
    return null;
  }
}

async function pollPendingChatReceipt(clientTurnId, sessionGeneration, chatGeneration) {
  if (!clientTurnId || state.chatStream) return { running: false, stale: false };
  try {
    const receipt = await api(`/api/chat/receipt?client_turn_id=${encodeURIComponent(clientTurnId)}`);
    if (!chatPollStateIsCurrent(sessionGeneration, chatGeneration)) return { running: false, stale: true };
    if (["running", "queued"].includes(receipt.status)) {
      if (!state.chatRequest) state.chatRequest = { phase: "recovering", clientTurnId, message: null };
      return { running: true, stale: false };
    }
    applyChatReceipt(receipt);
    rememberChatTurn(null);
    return { running: false, stale: false };
  } catch (error) {
    if (!chatPollStateIsCurrent(sessionGeneration, chatGeneration)) return { running: false, stale: true };
    if (![403, 404].includes(error.status)) throw error;
    rememberChatTurn(null);
    const request = state.chatRequest;
    if (request?.message) {
      state.rejectedMessages.push({ role: "user", content: request.message, client_turn_id: clientTurnId,
        error: "Die Nachricht wurde nicht angenommen. Bitte erneut senden." });
    }
    return { running: false, stale: false };
  }
}

function showRunningChatStatus(status) {
  state.chatServerOperationId = status.operation_id || null;
  if (!state.chatRequest) {
    state.chatRequest = { phase: "recovering", operationId: state.chatServerOperationId, message: null, background: status.mode === "background" };
  } else if (state.chatRequest.phase === "recovering") {
    state.chatRequest.operationId = state.chatServerOperationId;
    state.chatRequest.background = status.mode === "background";
  }
  if (!state.busy) {
    state.busy = true;
    renderQuickMessageTemplates();
    updateChatControls();
    renderMessages(state.data.messages || [], true);
  }
}

async function finishRecoveredChatStatus() {
  if (state.chatStream) return;
  const request = state.chatRequest;
  state.chatServerOperationId = null;
  if (request?.phase !== "recovering") return;
  await loadChatHistoryFresh();
  if (state.chatRequest !== request) return;
  state.chatRequest = null;
  state.busy = Boolean(state.chatQueue.length);
  state.chatStreamText = "";
  state.chatResponseStarted = false;
  state.chatResponseScrollPending = true;
  renderQuickMessageTemplates();
  renderMessages(state.data?.messages || [], true);
  updateChatControls();
  void resumeQueuedChat();
  scrollChatToResponseStart();
}

function rescheduleChatStatusPoll(delay) {
  if (chatStatusPollWanted()) scheduleChatStatusPoll(delay);
}

function settleChatStatusPoll(pollRequest, authFailed, running) {
  if (state.chatStatusPollInFlight !== pollRequest) return;
  state.chatStatusPollInFlight = null;
  if (!authFailed) rescheduleChatStatusPoll(running ? 1_500 : 5_000);
}

async function pollChatStatus() {
  if (!state.data || document.visibilityState !== "visible") return;
  if (!navigator.onLine) {
    rescheduleChatStatusPoll(5_000);
    return;
  }
  if (state.chatStatusPollInFlight) return;
  const pollRequest = {};
  state.chatStatusPollInFlight = pollRequest;
  let running = false;
  let authFailed = false;
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  try {
    const receiptState = await pollPendingChatReceipt(pendingChatTurn(), sessionGeneration, chatGeneration);
    if (receiptState.stale) return;
    const status = await api("/api/chat/status");
    if (!chatPollStateIsCurrent(sessionGeneration, chatGeneration)) return;
    running = receiptState.running || status.status === "running";
    if (running) showRunningChatStatus(status);
    else await finishRecoveredChatStatus();
  } catch (error) {
    authFailed = /Authentication/.test(error.message);
  } finally {
    settleChatStatusPoll(pollRequest, authFailed, running);
  }
}

async function loadInitialState() {
  const sessionGeneration = state.sessionGeneration;
  state.initialStateLoaded = false;
  const route = AppRouter.routeFromHash();
  AppState.setPlanSegment(AppRouter.planSegmentFromRoute(route));
  const areas = ["chat", "performance", "feedback", "profile"];
  areas.push("weather");
  if (AppRouter.baseRoute(route) === "plan") areas.push("plan", "library");
  await load("/api/bootstrap?local=1", areas);
  if (sessionGeneration !== state.sessionGeneration) return;
  state.initialStateLoaded = true;
  if (state.chatInitialScrollPending && AppRouter.baseRoute() === "coach") scrollChatToLatest();
  if (state.data?.profile?.weather_location) {
    await load("/api/bootstrap", state.loadedAreas.has("plan") ? ["plan"] : ["weather"]);
  }
  connectStateEvents();
  scheduleChatStatusPoll(0);
}

function queueChatMessage(message, mode, requestKind = null, attachments = []) {
  const queuedAttachmentBytes = state.chatQueue.reduce((total, entry) => total + (entry.attachments || []).reduce((bytes, item) => bytes + String(item.data || "").length, 0), 0);
  const attachmentBytes = attachments.reduce((total, item) => total + String(item.data || "").length, 0);
  if (queuedAttachmentBytes + attachmentBytes > MAX_QUEUED_ATTACHMENT_BYTES) {
    state.chatAttachments = attachments;
    renderChatAttachments();
    toast("Die Warteschlange enthält bereits zu viele Bilddaten. Warte auf die laufende Coach-Antwort.", true);
    return false;
  }
  state.chatQueue[mode === "steer" ? "unshift" : "push"]({
    id: ++state.chatQueueSequence,
    message,
    mode,
    requestKind,
    attachments,
  });
  const input = $("#messageInput");
  input.value = "";
  state.chatDraftDirty = false;
  input.style.height = "auto";
  renderMessages(state.data?.messages || [], true);
  updateChatControls();
  return true;
}

function removeQueuedChatMessage(id) {
  state.chatQueue = state.chatQueue.filter((entry) => entry.id !== id);
  renderMessages(state.data?.messages || [], false, true);
  updateChatControls();
}

function queuedChatEditFitsDraft(entry, draftAttachments = []) {
  return (entry.attachments || []).length + draftAttachments.length <= MAX_CHAT_ATTACHMENTS;
}

function editQueuedChatMessage(id) {
  const entry = state.chatQueue.find((item) => item.id === id);
  if (!entry) return;
  if (!queuedChatEditFitsDraft(entry, state.chatAttachments || [])) {
    toast(`Höchstens ${MAX_CHAT_ATTACHMENTS} Anhänge pro Nachricht. Entferne zuerst Anhänge aus dem Entwurf.`, true);
    return;
  }
  removeQueuedChatMessage(id);
  const input = $("#messageInput");
  input.value = input.value.trim() ? `${input.value.trimEnd()}\n${entry.message}` : entry.message;
  if (entry.attachments.length) {
    state.chatAttachments = [...entry.attachments, ...(state.chatAttachments || [])];
    renderChatAttachments();
  }
  input.dispatchEvent(new Event("input"));
  input.focus({ preventScroll: true });
}

function chatRequestIsCurrent(sessionGeneration, chatGeneration) {
  return sessionGeneration === state.sessionGeneration && chatGeneration === state.chatGeneration;
}

async function chatStreamResponse(message, requestKind, attachments, clientTurnId, stream) {
  const generation = state.sessionGeneration;
  try {
    return await globalThis.AppApi.stream("/api/chat/stream", {
      method: "POST",
      signal: stream.controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, client_turn_id: clientTurnId, request_kind: requestKind, attachments }),
    }, () => { if (generation === state.sessionGeneration) showLogin(); });
  } catch (error) {
    if (error.status) {
      stream.serverError = true;
      stream.rejected = true;
    }
    throw error;
  }
}

function rejectChatStreamResponse(error, context) {
  const { attachments, chatGeneration, clientTurnId, message, sessionGeneration, stream } = context;
  stream.serverError = true;
  stream.rejected = true;
  if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return false;
  if (error.status === 401) {
    const rejectedAttachments = [...(attachments || [])];
    showLogin();
    state.chatAttachments = rejectedAttachments;
    renderChatAttachments();
    const input = $("#messageInput");
    if (input.value.trim()) state.rejectedMessages.push({ role: "user", content: message, client_turn_id: clientTurnId, error: "Bitte erneut anmelden." });
    else { input.value = message; resizeChatInput(input); }
    state.chatDraftDirty = true;
  }
  throw error;
}

function parseChatStreamEvent(block) {
  let event = "message";
  const data = [];
  for (const line of block.replaceAll("\r", "").split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, payload: JSON.parse(data.join("\n")) } : null;
}

function applyStartedChatStreamEvent(payload, context) {
  const { request, stream } = context;
  stream.operationId = payload.operation_id || null;
  request.operationId = stream.operationId;
  state.chatServerOperationId = stream.operationId;
  if (stream.cancelRequested) void cancelChat();
}

function applyDeltaChatStreamEvent(payload) {
  const responseJustStarted = !state.chatStreamText;
  state.chatStreamText += payload.text || "";
  state.chatResponseStarted = state.chatResponseStarted || responseJustStarted;
  if (responseJustStarted) state.chatResponseScrollPending = true;
  scheduleChatStreamRender(responseJustStarted);
}

function applyBackgroundChatStreamEvent(payload, context) {
  const { request, stream } = context;
  context.background = true;
  request.background = true;
  request.phase = "recovering";
  stream.operationId = payload.operation_id || stream.operationId;
  request.operationId = stream.operationId;
  state.chatServerOperationId = stream.operationId;
  renderMessages(state.data?.messages || [], false);
  updateChatControls();
}

function applyCompletedChatStreamEvent(payload, context) {
  const { clientTurnId, request } = context;
  cancelScheduledChatStreamRender();
  context.completed = true;
  announceChatStatus("Antwort fertig.");
  context.completedPayload = payload;
  state.chatContentVersion += 1;
  rememberChatTurn(null);
  request.phase = "reconciling";
  request.responseMessageId = payload.message?.id || null;
  state.chatResponseMessageId = request.responseMessageId;
  request.responseMessageReceived = reconcileCompletedChatMessage(payload.message ? { ...payload.message, client_turn_id: clientTurnId } : null);
  if (request.responseMessageReceived) state.chatStreamText = "";
  request.hadOutstandingProposals = Array.isArray(state.coachActionProposals) && state.coachActionProposals.length > 0;
  if (request.hadOutstandingProposals) state.chatProposalRefreshPending = true;
  state.coachActionProposals = Array.isArray(payload?.proposed_actions) ? payload.proposed_actions : [];
  if (payload?.coach_quick_actions && state.data) {
    state.data.coach_quick_actions = payload.coach_quick_actions;
    renderCoachOverview(state.data);
  }
  addStructuredCoachReceipts(payload);
  renderMessages(state.data?.messages || [], false);
  updateChatControls();
}

function applyChatStreamEvent(event, payload, context) {
  if (event === "started") return applyStartedChatStreamEvent(payload, context);
  if (event === "delta") return applyDeltaChatStreamEvent(payload);
  if (event === "background") return applyBackgroundChatStreamEvent(payload, context);
  if (event === "completed") return applyCompletedChatStreamEvent(payload, context);
  if (event === "error") {
    context.stream.serverError = true;
    if (!context.background) context.stream.rejected = true;
    const fallback = "Die Coach-Anfrage ist fehlgeschlagen. Bitte später erneut versuchen.";
    const message = typeof payload.reason === "string" && payload.reason.startsWith("upstream_")
      ? globalThis.AppApi.messageForReason(payload.reason, fallback)
      : payload.message || fallback;
    const error = new Error(message);
    error.reason = payload.reason;
    throw error;
  }
}

function consumeChatStreamBlock(block, context) {
  if (!chatRequestIsCurrent(context.sessionGeneration, context.chatGeneration)) return;
  const parsed = parseChatStreamEvent(block);
  if (parsed) applyChatStreamEvent(parsed.event, parsed.payload, context);
}

async function readChatStream(response, context) {
  if (!response.body) throw new Error("Der Browser unterstützt keinen Antwort-Stream.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) consumeChatStreamBlock(block, context);
    // The chat endpoint is a finite SSE response. A proxy may keep the HTTP
    // connection open after the terminal event, so release the reader as
    // soon as the persisted result has arrived instead of trapping the
    // composer in the reconciling state.
    if (context.completed || context.background) {
      await reader.cancel().catch(() => {});
      break;
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) consumeChatStreamBlock(buffer, context);
}

async function refreshCompletedChatStream(context) {
  const { completedPayload, request } = context;
  const hasPersistedReceipt = request.responseMessageReceived || Boolean(completedPayload?.message?.content && state.data);
  if (hasPersistedReceipt) {
    if (state.chatProposalRefreshPending && AppRouter.baseRoute() === "coach") void refreshChatProposalsInBackground(state.chatContentVersion);
    return;
  }
  await loadChatHistoryFresh();
}

async function finishChatStream(context) {
  const { completed, stream } = context;
  if (context.background) {
    scheduleChatStatusPoll(0);
    return "recovering";
  }
  if (!completed && !stream.cancelRequested) throw new Error("Der Antwort-Stream wurde unerwartet beendet.");
  await refreshCompletedChatStream(context);
  if (completed && state.chatFollowLatest) scrollChatToResponseStart();
  if (completed) markChatContentArrived();
  invalidateContextPreview();
  return completed ? "completed" : "failed";
}

async function recoverChatRequestFailure(error, context) {
  const { attachments, chatGeneration, clientTurnId, completed, message, request, sessionGeneration, stream } = context;
  if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return false;
  cancelScheduledChatStreamRender();
  if (stream.rejected) {
    rememberChatTurn(null);
    const input = $("#messageInput");
    if (input.value.trim()) {
      const failed = state.data.messages.find((entry) => entry.optimistic && entry.client_turn_id === clientTurnId);
      if (failed) { failed.error = error.message; failed.attachments = attachments; }
    } else {
      state.data.messages = (state.data.messages || []).filter((entry) => !(entry.optimistic && entry.client_turn_id === clientTurnId));
      input.value = message;
      resizeChatInput(input);
      state.chatAttachments = [...attachments, ...(state.chatAttachments || [])];
      renderChatAttachments();
    }
    state.chatDraftDirty = true;
    toast(error.message, true);
    return false;
  }
  const cancelled = stream.cancelRequested || error?.name === "AbortError" || error?.reason === "chat_cancelled";
  if (!completed && !stream.serverError) {
    request.phase = "recovering";
    state.chatServerOperationId = stream.operationId || state.chatServerOperationId;
    if (state.chatStream === stream) state.chatStream = null;
    renderMessages(state.data?.messages || [], false);
    updateChatControls();
    scheduleChatStatusPoll(0);
    return "recovering";
  }
  if (!cancelled) toast(error.message, true);
  scheduleChatStatusPoll(0);
  await loadChatHistoryFresh();
  invalidateContextPreview();
  return false;
}

function finishChatRequest(context) {
  const { chatGeneration, completed, request, sessionGeneration, stream } = context;
  if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return;
  if (state.chatStream === stream) state.chatStream = null;
  if (request.phase !== "recovering") {
    cancelScheduledChatStreamRender();
    state.chatStreamText = "";
  }
  if (!completed && request.phase !== "recovering") state.chatResponseScrollPending = false;
  if (!completed && request.phase !== "recovering") state.chatResponseMessageId = null;
  state.chatResponseStarted = false;
  if (state.chatRequest === request && request.phase !== "recovering") state.chatRequest = null;
  if (request.phase !== "recovering") state.chatServerOperationId = null;
  updateChatControls();
}

async function requestCoachResponse(message, requestKind = null, attachments = []) {
  const sessionGeneration = state.sessionGeneration;
  const chatGeneration = state.chatGeneration;
  const clientTurnId = AppState.secureToken("turn");
  if (chatIsNearBottom()) state.chatFollowLatest = true;
  if (state.data) {
    state.data.messages = mergeChatMessages([{ role: "user", content: message, attachment_names: JSON.stringify(attachments.map(item => item.name)), client_turn_id: clientTurnId, created_at: new Date().toISOString(), optimistic: true }]);
    renderMessages(state.data.messages, true);
  }
  state.chatStreamText = "";
  rememberChatTurn(clientTurnId);
  const request = { phase: "running", message, clientTurnId, operationId: null, responseMessageId: null, responseMessageReceived: false, cancelRequested: false };
  state.chatRequest = request;
  const stream = { controller: new AbortController(), operationId: null, cancelRequested: false, request, serverError: false };
  state.chatStream = stream;
  updateChatControls();
  renderMessages(state.data?.messages || [], true);
  const context = { attachments, background: false, chatGeneration, clientTurnId, completed: false, completedPayload: null, message, request, sessionGeneration, stream };
  try {
    const response = await chatStreamResponse(message, requestKind, attachments, clientTurnId, stream);
    if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return false;
    await readChatStream(response, context);
    return await finishChatStream(context);
  } catch (error) {
    if (error.status) {
      try { rejectChatStreamResponse(error, context); } catch (rejectedError) { error = rejectedError; }
    }
    return await recoverChatRequestFailure(error, context);
  } finally {
    finishChatRequest(context);
  }
}

async function drainChatQueue(firstMessage, requestKind = null, attachments = []) {
  const firstResult = await requestCoachResponse(firstMessage, requestKind, attachments);
  if (firstResult !== "completed") return firstResult;
  while (state.chatQueue.length) {
    const next = state.chatQueue.shift();
    renderMessages(state.data?.messages || [], true);
    if (await requestCoachResponse(next.message, next.requestKind, next.attachments) !== "completed") return;
  }
  return "completed";
}

async function cancelChat() {
  const stream = state.chatStream;
  const operationId = stream?.operationId || state.chatServerOperationId;
  if (stream) stream.cancelRequested = true;
  if (state.chatRequest) state.chatRequest.cancelRequested = true;
  if (!operationId) { updateChatControls(); return; }
  if (state.chatRequest) {
    state.chatRequest.cancelRequested = true;
    state.chatRequest.phase = "recovering";
  }
  await api("/api/chat/cancel", {
    method: "POST",
    body: JSON.stringify({ operation_id: operationId }),
  }).catch(() => {});
  stream?.controller.abort();
  scheduleChatStatusPoll(0);
}

async function sendMessage(event) {
  event.preventDefault();
  const configured = state.data?.configured;
  if (configured && !configured.openai) {
    toast("Kein OpenAI-API-Schlüssel konfiguriert. Bitte hinterlege OPENAI_API_KEY auf dem Server.", true);
    return;
  }
  const input = $("#messageInput");
  if (!chatControlState(input).chatReady) return;
  const attachments = state.chatAttachments || [];
  const message = input.value.trim() || (attachments.length ? "Bitte analysiere die angehängten Dateien." : "");
  const requestKind = input.dataset.requestKind || null;
  if (state.chatAttachmentsLoading || !message || voiceIsRecording() || state.voiceTranscribing) return;
  state.chatAttachments = [];
  renderChatAttachments();
  if (state.chatRequest || state.chatServerOperationId) {
    if (state.busy) queueChatMessage(message, "queue", requestKind, attachments);
    return;
  }
  if (state.busy) {
    queueChatMessage(message, "queue", requestKind, attachments);
    return;
  }
  state.busy = true;
  state.quickTemplatesVisible = false;
  renderQuickMessageTemplates();
  input.value = "";
  delete input.dataset.requestKind;
  state.chatDraftDirty = false;
  input.style.height = "auto";
  updateChatControls();
  updateVoiceButton();
  try {
    await drainChatQueue(message, requestKind, attachments);
  } finally {
    if (!state.chatRequest && !state.chatServerOperationId) state.busy = false;
    updateChatControls();
    renderMessages(state.data?.messages || [], false, true);
    updateVoiceButton();
    if ($("#chatPanel")?.classList.contains("active") && document.visibilityState === "visible" && shouldRestoreChatInputFocus()) {
      input.focus({ preventScroll: true });
    }
  }
}

function steerCurrentChat(event) {
  event.preventDefault();
  const input = $("#messageInput");
  const message = input.value.trim();
  if ((state.chatAttachments || []).length) { toast("Bitte Anhänge mit Senden in die Warteschlange stellen.", true); return; }
  if (!message || !state.busy || voiceIsRecording() || state.voiceTranscribing) return;
  queueChatMessage(message, "steer");
}

async function resetCoachChat() {
  const button = $("#openaiChatResetButton");
  if (!button || !await requestConfirmation("Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen?", { title: "Coach-Chat zurücksetzen?" })) return;
  button.disabled = true;
  button.textContent = "Wird zurückgesetzt…";
  try {
    const reset = await api("/api/chat/reset", { method: "POST", body: "{}" });
    state.chatAttachments = [];
    renderChatAttachments();
    if (state.data) state.data.messages_generation = reset.generation;
    state.chatGeneration += 1;
    state.chatStatusPollInFlight = null;
    scheduleChatStatusPoll(0);
    state.rejectedMessages = [];
    state.chatStream?.controller.abort();
    state.chatStream = null;
    rememberChatTurn(null);
    if (state.data) {
      state.data.messages = [];
      state.chatQueue = [];
      state.chatRequest = null;
      state.chatStreamText = "";
      state.chatServerOperationId = null;
      state.chatResponseStarted = false;
      state.chatResponseScrollPending = false;
      state.chatResponseMessageId = null;
      state.chatScrollY = null;
      cancelScheduledChatStreamRender();
      renderMessages([], true);
    }
    state.busy = false;
    updateChatControls();
    updateVoiceButton();
    toast("Neuer Coach-Chat gestartet");
  } catch (error) { toast(error.message, true); }
  finally {
    button.disabled = false;
    button.textContent = "Chat zurücksetzen";
  }
}

const MAX_QUEUED_ATTACHMENT_BYTES = 16_000_000;
const MAX_CHAT_ATTACHMENTS = 4;

const VOICE_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

const VOICE_MAX_DURATION_MS = 60_000;

function setVoiceStatus(message = "", error = false) {
  const node = $("#voiceStatus");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("error", error);
  node.hidden = !message;
}

function voiceIsRecording() {
  return state.voiceRecorder?.state === "recording";
}

function formatVoiceDuration() {
  const elapsed = Math.min(Date.now() - state.voiceStartedAt, VOICE_MAX_DURATION_MS);
  return `${String(Math.floor(elapsed / 1000)).padStart(2, "0")} s / 60 s`;
}

function setVoiceButtonIcon(icon) {
  const button = $("#voiceButton");
  if (button) button.innerHTML = `<svg class="nav-icon" aria-hidden="true"><use href="#icon-${icon}"></use></svg>`;
}

function updateVoiceButton() {
  const button = $("#voiceButton");
  if (!button) return;
  const recording = voiceIsRecording();
  const transcribing = state.voiceTranscribing;
  const chatReady = Boolean(state.data && Array.isArray(state.data.messages));
  button.disabled = !chatReady || state.busy || transcribing;
  button.classList.toggle("recording", recording);
  button.classList.toggle("transcribing", transcribing);
  button.setAttribute("aria-pressed", recording ? "true" : "false");
  if (recording) {
    setVoiceButtonIcon("stop");
    button.setAttribute("aria-label", "Spracheingabe beenden");
    button.title = "Spracheingabe beenden";
  } else if (transcribing) {
    button.innerHTML = "<span class=\"button-spinner\" aria-hidden=\"true\"></span>";
    button.setAttribute("aria-label", "Audio wird transkribiert");
    button.title = "Audio wird transkribiert";
  } else {
    setVoiceButtonIcon("microphone");
    button.setAttribute("aria-label", "Spracheingabe starten");
    button.title = "Spracheingabe starten";
  }
  updateChatControls();
}

function chatControlState(input) {
  const configured = state.data?.configured;
  const aiConfigured = !configured || Boolean(configured.openai);
  const chatReady = Boolean(state.data && Array.isArray(state.data.messages) && aiConfigured);
  const hasDraft = Boolean((state.chatAttachments || []).length || input?.value.trim());
  const inputAvailable = !voiceIsRecording() && !state.voiceTranscribing;
  const resuming = Boolean(state.chatRequest?.phase === "recovering" || (state.chatServerOperationId && !state.chatStream));
  return { aiConfigured, chatReady, hasDraft, inputAvailable, resuming, reconciling: state.chatRequest?.phase === "reconciling" };
}

function chatSendLabel(controls) {
  if (controls.reconciling) return "Antwort wird geladen…";
  if (controls.resuming) return "Coach antwortet…";
  return state.busy ? "Einreihen" : "Senden";
}

function updateChatSendButton(button, controls) {
  if (!button) return;
  button.disabled = state.chatAttachmentsLoading || !controls.chatReady || !controls.hasDraft || !controls.inputAvailable || controls.resuming || controls.reconciling;
  const label = chatSendLabel(controls);
  button.setAttribute("aria-label", label);
  button.title = label;
}

function steerButtonHint(controls) {
  if (controls.resuming || controls.reconciling) return "Der Coach lädt die Antwort noch.";
  if (!controls.inputAvailable) return "Die Spracheingabe läuft noch.";
  if (!controls.hasDraft) return "Schreibe zuerst eine Nachricht, um sie als Nächstes zu senden.";
  return "Wird nach der aktuellen Antwort vor den übrigen wartenden Nachrichten gesendet.";
}

function updateChatSteerButton(button, controls) {
  if (!button) return;
  button.hidden = !state.busy || controls.resuming || controls.reconciling;
  button.disabled = !controls.hasDraft || !controls.inputAvailable || controls.resuming || controls.reconciling;
  const hint = steerButtonHint(controls);
  button.title = hint;
  const hintNode = $("#steerButtonHint");
  if (hintNode) hintNode.textContent = hint;
}

function updateChatCancelButton(button, controls) {
  if (!button) return;
  button.hidden = !state.busy || controls.reconciling;
  const requested = Boolean(state.chatStream?.cancelRequested || state.chatRequest?.cancelRequested);
  button.disabled = (!state.chatStream && !state.chatServerOperationId) || requested;
  const label = requested ? "Antwort wird gestoppt" : "Antwort stoppen";
  button.setAttribute("aria-label", label);
  button.title = label;
}

function updateChatControls() {
  const input = $("#messageInput");
  const controls = chatControlState(input);
  const form = $("#chatForm");
  if (form) {
    form.classList.toggle("is-busy", state.busy);
    form.classList.toggle("is-recovering", controls.resuming);
    form.classList.toggle("is-reconciling", controls.reconciling);
  }
  if (input) {
    // Drafting stays available while the Coach loads or works; readiness only
    // gates the actions that submit the draft.
    input.disabled = false;
    input.placeholder = chatInputPlaceholder(controls);
  }
  updateChatSendButton($("#sendButton"), controls);
  updateChatSteerButton($("#steerButton"), controls);
  updateChatCancelButton($("#cancelChatButton"), controls);
  syncChatWorkingStatus(controls);
  updateChatQueueStatus();
}

function chatInputPlaceholder(controls) {
  if (!controls.aiConfigured) return "OPENAI_API_KEY in den Server-Einstellungen konfigurieren…";
  if (!controls.chatReady) return "Coach-Chat wird geladen…";
  return state.busy ? "Folgefrage – wird danach gesendet" : "Frage deinen Coach…";
}

function syncChatWorkingStatus(controls) {
  const progress = $("#chatOperationStatus");
  if (!progress) return;
  const operationActive = Boolean(state.chatRequest || state.chatServerOperationId || state.chatQueue.length);
  if (state.busy && operationActive && !controls.reconciling) {
    announceChatStatus(coachWorkingLabel());
    state.chatStatusWorking = true;
  } else if (!state.busy && state.chatStatusWorking) {
    // Keep the completion announcement; clear only a stale working status.
    state.chatStatusWorking = false;
    if (progress.textContent !== "Antwort fertig.") progress.textContent = "";
  }
}

function announceChatStatus(message) {
  const status = $("#chatOperationStatus");
  if (!status || status.textContent === message) return;
  status.textContent = message;
}
function stopVoiceCapture(recorder = state.voiceRecorder) {
  if (state.voiceTimer) clearInterval(state.voiceTimer);
  state.voiceTimer = null;
  if (state.voiceStream) {
    state.voiceStream.getTracks().forEach((track) => track.stop());
    state.voiceStream = null;
  }
  if (state.voiceRecorder === recorder) state.voiceRecorder = null;
  updateVoiceButton();
}

function stopVoiceRecording() {
  const recorder = state.voiceRecorder;
  if (recorder?.state === "recording") recorder.stop();
}

async function transcribeVoice(blob) {
  const generation = state.sessionGeneration;
  state.voiceTranscribing = true;
  setVoiceStatus("Aufnahme wird transkribiert …");
  updateVoiceButton();
  try {
    const result = await apiAudio("/api/transcribe", blob);
    if (generation !== state.sessionGeneration) return;
    const transcript = String(result.transcript || "").trim();
    if (!transcript) throw new Error("OpenAI hat kein Transkript zurückgegeben.");
    const input = $("#messageInput");
    const current = input.value.trim();
    input.value = current ? `${current}\n${transcript}` : transcript;
    input.dispatchEvent(new Event("input"));
    updateVoiceButton();
    if ($("#chatPanel")?.classList.contains("active") && document.visibilityState === "visible") input.focus({ preventScroll: true });
    setVoiceStatus("Transkript eingefügt. Bitte prüfen und anschließend senden.");
    } catch (error) {
      if (generation !== state.sessionGeneration) return;
      setVoiceStatus(error.message, true);
      toast(error.message, true);
    } finally {
    if (generation === state.sessionGeneration) {
      state.voiceTranscribing = false;
      updateVoiceButton();
    }
  }
}

async function toggleVoiceInput() {
  if (state.busy || state.voiceTranscribing || state.voiceAcquiring) return;
  if (voiceIsRecording()) {
    stopVoiceRecording();
    return;
  }
  if (!globalThis.isSecureContext || !navigator.mediaDevices?.getUserMedia || !globalThis.MediaRecorder) {
    const message = "Spracheingabe benötigt eine HTTPS-Verbindung und einen unterstützten Browser.";
    setVoiceStatus(message, true);
    toast(message, true);
    return;
  }
  const generation = state.sessionGeneration;
  state.voiceAcquiring = true;
  setVoiceStatus("Mikrofon wird aktiviert …");
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    if (generation !== state.sessionGeneration) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    state.voiceAcquiring = false;
    state.voiceStream = stream;
    const mimeType = typeof MediaRecorder.isTypeSupported === "function"
      ? VOICE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || ""
      : "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    state.voiceRecorder = recorder;
    state.voiceStartedAt = Date.now();
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) chunks.push(event.data);
    });
    recorder.addEventListener("error", () => {
      if (generation !== state.sessionGeneration) return;
      stopVoiceCapture(recorder);
      setVoiceStatus("Die Audioaufnahme ist fehlgeschlagen.", true);
    });
    recorder.addEventListener("stop", () => {
      if (generation !== state.sessionGeneration) return;
      const recordedType = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunks, { type: recordedType });
      stopVoiceCapture(recorder);
      if (blob.size) void transcribeVoice(blob);
      else setVoiceStatus("Es wurde keine Sprache aufgenommen.", true);
    }, { once: true });
    recorder.start();
    setVoiceStatus(`Aufnahme läuft · ${formatVoiceDuration()}`);
    updateVoiceButton();
    state.voiceTimer = setInterval(() => {
      if (!voiceIsRecording()) return;
      setVoiceStatus(`Aufnahme läuft · ${formatVoiceDuration()}`);
      if (Date.now() - state.voiceStartedAt >= VOICE_MAX_DURATION_MS) stopVoiceRecording();
    }, 250);
  } catch (error) {
    if (generation !== state.sessionGeneration) return;
    state.voiceAcquiring = false;
    stopVoiceCapture();
    const message = error.name === "NotAllowedError"
      ? "Der Mikrofonzugriff wurde nicht erlaubt."
      : "Das Mikrofon konnte nicht aktiviert werden.";
    setVoiceStatus(message, true);
    toast(message, true);
  }
}


function renderCoachOverview(data) {
  const actions = data.coach_quick_actions || {};
  const quickMorning = $("#quickMorningCheckinButton");
  if (quickMorning) quickMorning.hidden = actions.morning_checkin === false;
}

function renderCoachReceipts() {
  const root = $("#coachReceipts");
  if (!root) return;
  root.hidden = true;
  root.replaceChildren();
  (state.coachReceipts || []).slice(-3).reverse().forEach((receipt) => root.append(createActionReceipt(receipt)));
}

function addCoachReceipt(receipt) {
  state.coachReceipts = [...(state.coachReceipts || []), { ...receipt, createdAt: Date.now() }].slice(-3);
  renderCoachReceipts();
}

const HIDDEN_CHAT_RECEIPT_TOOLS = new Set([
  "get_sync_job", "refresh_current_performance", "start_intervals_plan_sync",
  "start_provider_refresh", "sync_competitions",
]);
const COACH_RECEIPT_LABELS = {
  update_profile: "Profil aktualisiert", apply_training_patch: "Geplante Einheiten angepasst",
  stage_training_plan: "Planvorlage vorbereitet", commit_training_plan: "Trainingsplan gespeichert",
  replace_training_plan: "Trainingsplan vollständig ersetzt",
  apply_training_changes: "Lokale Planung geändert", manage_training_templates: "Trainingsvorlagen bearbeitet",
  apply_workout_library_plan: "Einheiten lokal geplant", save_checkin: "Tages-Check-in gespeichert",
  save_activity_feedback: "Aktivitätsfeedback gespeichert", delete_activity_feedback: "Aktivitätsfeedback gelöscht",
  save_competition: "Wettkampf gespeichert", delete_competition: "Wettkampf gelöscht",
  update_training_plan: "Trainingsplan geändert", undo_training_change: "Rücknahme zur Prüfung bereit",
  preview_adaptive_replan: "Plananpassung zur Prüfung bereit", apply_adaptive_replan: "Plananpassung gespeichert",
  start_provider_refresh: "Datenabruf beauftragt", refresh_current_performance: "Leistungsdatenabruf beauftragt",
  sync_competitions: "Wettkampfsynchronisierung beauftragt",
  resolve_training_sync_conflict: "Synchronisierungsentscheidung gespeichert",
  start_intervals_plan_sync: "Intervals-Synchronisierung beauftragt",
  delete_duplicate_intervals_activity: "Garmin-Duplikat gelöscht",
};
const SYNC_JOB_RECEIPT_LABELS = {
  queued: "Synchronisierung beauftragt", running: "Synchronisierung läuft",
  completed: "Synchronisierung abgeschlossen", partial: "Synchronisierung teilweise abgeschlossen",
  failed: "Synchronisierung fehlgeschlagen",
};

function receiptIsVisible(entry, planCommitRequested, finalCommit) {
  if (entry.resolved) return false;
  const result = entry.result || {};
  const failedSync = entry.tool === "start_intervals_plan_sync" && result.ok === false;
  const failedSyncJob = entry.tool === "get_sync_job" && result.job?.status === "failed";
  if (HIDDEN_CHAT_RECEIPT_TOOLS.has(entry.tool) && !failedSync && !failedSyncJob) return false;
  if (planCommitRequested && entry.tool === "stage_training_plan") return false;
  return entry.tool !== "commit_training_plan" || entry === finalCommit;
}

function syncJobReceipt(job) {
  const title = SYNC_JOB_RECEIPT_LABELS[job.status] || "Synchronisierungsstatus unklar";
  let status = "pending";
  if (["partial", "failed"].includes(job.status)) status = "error";
  else if (job.status === "completed") status = "success";
  return { title, message: job.error_detail || title, status };
}

function commandReceiptTitle(entry, result, failed, queued) {
  if (failed) return "Coach-Aktion fehlgeschlagen";
  if (entry.tool === "start_provider_refresh" && result.status === "completed") return "Daten aktualisiert";
  if (COACH_RECEIPT_LABELS[entry.tool]) return COACH_RECEIPT_LABELS[entry.tool];
  return queued ? "Synchronisierung beauftragt" : "Informationen geladen";
}

function commandReceiptMessage(result, failed, queued) {
  if (failed) return result.error || "Die Aktion konnte nicht ausgeführt werden.";
  return queued ? "Der Auftrag wird im Hintergrund bearbeitet; das Ergebnis steht noch aus." : "Der lokale Beleg liegt vor.";
}

function commandReceiptStatus(failed, queued) {
  if (failed) return "error";
  return queued ? "pending" : "success";
}

function commandReceipt(entry) {
  const result = entry.result || {};
  if (entry.tool === "get_sync_job" && result.job) return syncJobReceipt(result.job);
  const failed = result.ok === false;
  const queued = Boolean(result.sync_job_id || result.job_id || result.job?.id || result.status === "queued");
  const details = [];
  if (Array.isArray(result.library_entry_ids) && result.library_entry_ids.length) details.push(`${result.library_entry_ids.length} lokale Einheit(en) gespeichert`);
  if (result.remote_untouched) details.push("Providerdaten unverändert");
  return {
    title: commandReceiptTitle(entry, result, failed, queued),
    message: commandReceiptMessage(result, failed, queued),
    status: commandReceiptStatus(failed, queued),
    details,
  };
}

function addStructuredCoachReceipts(payload) {
  const commands = Array.isArray(payload?.command_receipts) ? payload.command_receipts : [];
  const planCommitRequested = payload?.intent?.operation === "commit_training_plan"
    || payload?.intent?.follow_up_operations?.includes("commit_training_plan")
    || commands.some((entry) => entry.tool === "commit_training_plan");
  const finalCommit = commands.findLast((entry) => entry.tool === "commit_training_plan");
  state.coachReceipts = [];
  renderCoachReceipts();
  commands.filter((entry) => receiptIsVisible(entry, planCommitRequested, finalCommit))
    .forEach((entry) => addCoachReceipt(commandReceipt(entry)));
}

async function askCoach(message) {
  const applied = await AppRouter.navigate("coach", { historyMode: "push", focus: false });
  if (!applied) return;
  const input = $("#messageInput");
  if (!input) return;
  input.value = message;
  input.dispatchEvent(new Event("input"));
  $("#chatForm")?.requestSubmit();
}


let chatStreamRenderFrame = null;
let chatStreamStartScrollPending = false;
function chatIsNearBottom() {
  const messages = $("#messages");
  if (messages && messages.scrollHeight > messages.clientHeight + 1) {
    return messages.scrollHeight - messages.scrollTop - messages.clientHeight <= 48;
  }
  return document.documentElement.scrollHeight - (globalThis.scrollY + globalThis.innerHeight) <= 48;
}

function updateChatComposerVisibility() {
  const panel = $("#chatPanel");
  if (!panel) return;
  const jump = $("#chatJumpToComposer");
  const active = panel.classList.contains("active");
  const nearBottom = chatIsNearBottom();
  // Reaching the latest content re-enables following; a hidden panel measures the wrong scroller and must not change it.
  if (active && nearBottom) {
    state.chatFollowLatest = true;
    state.chatUnseenContent = false;
  }
  if (jump) {
    jump.hidden = nearBottom || !$("#messages")?.childElementCount || !active;
    updateChatJumpLabel(jump);
  }
}

// Content that arrives while the reader is scrolled away is flagged so the jump button can say so.
function markChatContentArrived() {
  if (!state.chatFollowLatest) state.chatUnseenContent = true;
  updateChatComposerVisibility();
}

function updateChatJumpLabel(jump) {
  const unseen = Boolean(state.chatUnseenContent) && !state.chatFollowLatest;
  const name = unseen ? "Zur neuesten Antwort springen" : "Zu den neuesten Nachrichten springen";
  jump.classList.toggle("has-label", unseen);
  jump.querySelector(".chat-jump-label")?.toggleAttribute("hidden", !unseen);
  if (jump.getAttribute("aria-label") !== name) {
    jump.setAttribute("aria-label", name);
    jump.title = name;
  }
}

// Only a real upward gesture leaves the latest content; programmatic scrolls never reach these listeners.
let chatTouchLastY = null;
function chatUserScrolledAway() {
  if (!$("#chatPanel")?.classList.contains("active")) return;
  state.chatFollowLatest = false;
  updateChatComposerVisibility();
}

function handleChatWheel(event) {
  if (event.deltaY < 0) chatUserScrolledAway();
}

function handleChatTouchStart(event) {
  chatTouchLastY = event.touches[0]?.clientY ?? null;
}

function handleChatTouchMove(event) {
  const y = event.touches[0]?.clientY;
  if (y == null) return;
  // A finger moving down scrolls the page up, away from the latest content.
  if (chatTouchLastY != null && y > chatTouchLastY) chatUserScrolledAway();
  chatTouchLastY = y;
}

function handleChatScrollKey(event) {
  if (!["PageUp", "ArrowUp", "Home"].includes(event.key)) return;
  // Editing the draft moves the caret, not the page.
  if (event.target?.closest?.("input, textarea, [contenteditable]")) return;
  chatUserScrolledAway();
}

// Offsets the app last set or accepted. A scroll that moves above them by more than a few pixels is the reader,
// including a scrollbar drag, which sends no wheel event. Programmatic scrolls re-anchor through scrollWindowForChat.
const CHAT_UPWARD_SCROLL_PX = 4;
const chatScrollAnchors = { window: null, messages: null };
function chatScrollMovedUp(kind, position) {
  const anchor = chatScrollAnchors[kind];
  if (anchor == null || position > anchor) {
    chatScrollAnchors[kind] = position;
    return false;
  }
  if (position >= anchor - CHAT_UPWARD_SCROLL_PX) return false;
  chatScrollAnchors[kind] = position;
  return true;
}

function scrollWindowForChat(top) {
  globalThis.scrollTo({ top, behavior: "auto" });
  chatScrollAnchors.window = globalThis.scrollY;
}

function chatAcceptsReaderScroll() {
  return !state.chatInitialScrollPending && !state.chatScrollRestoring && Boolean($("#chatPanel")?.classList.contains("active"));
}

// A small upward drag near the newest content keeps following; anything further away leaves it.
function chatReaderScrolledUp() {
  if (chatIsNearBottom()) return;
  chatUserScrolledAway();
}

function handleChatMessagesScroll(event) {
  const movedUp = chatScrollMovedUp("messages", event.target.scrollTop);
  if (movedUp && chatAcceptsReaderScroll()) chatReaderScrolledUp();
  updateChatComposerVisibility();
}

function jumpToLatestMessages() {
  const input = $("#messageInput");
  if (!input) return;
  const jump = $("#chatJumpToComposer");
  if (jump) jump.hidden = true;
  state.chatFollowLatest = true;
  state.chatUnseenContent = false;
  // Touch devices keep the keyboard closed; focusing the draft there would open it.
  if (shouldRestoreChatInputFocus()) input.focus({ preventScroll: true });
  scrollChatToLatest();
  updateChatComposerVisibility();
}

function updateChatQueueStatus() {
  const status = $("#chatQueueStatus");
  if (!status) return;
  status.hidden = true;
  status.textContent = "";
}

function coachWorkingLabel() {
  if (state.chatRequest?.background) return "Der Coach arbeitet · du kannst die Seite neu laden…";
  if (state.chatRequest?.phase === "recovering") return "Verbindung unterbrochen · die Antwort wird im Hintergrund fertiggestellt…";
  if (state.chatRequest?.phase === "reconciling") return "Antwort wird sicher übernommen…";
  return "Coach arbeitet an deiner Antwort…";
}

function createCoachWorkingIndicator() {
  const node = document.createElement("div");
  node.id = "coachWorking";
  node.className = "coach-working";
  node.setAttribute("aria-hidden", "true");
  node.setAttribute("aria-label", coachWorkingLabel());
  const dots = document.createElement("span");
  dots.className = "working-dots";
  dots.setAttribute("aria-hidden", "true");
  dots.innerHTML = "<i></i><i></i><i></i>";
  const label = document.createElement("span");
  label.textContent = coachWorkingLabel();
  node.append(dots, label);
  return node;
}

function coachActionDescription(proposal) {
  if (proposal.action_type === "undo_change") return "Diese lokale Änderung zurücknehmen? Der aktuelle Stand wird vor der Ausführung erneut geprüft.";
  if (proposal.action_type === "local_coach_write") {
    return proposal.object_ids?.operation === "save_nutrition_product"
      ? "Dieses Produkt wird lokal gespeichert. Es wird erst nach deiner Bestätigung angelegt."
      : "Diese Mahlzeitvorlage wird lokal gespeichert. Sie wird erst nach deiner Bestätigung angelegt.";
  }
  if (proposal.action_type === "remote_coach_write") {
    return "Diese Änderung wird an Intervals.icu gesendet. Sie wird erst ausgeführt, wenn du sie hier freigibst.";
  }
  return "Diese Garmin-Aufzeichnung ist nahezu identisch mit der Wahoo-Einheit. Nur das Garmin-Duplikat aus Intervals.icu löschen?";
}

function coachActionStatus(proposal) {
  return proposal.status === "used"
    ? "Freigabe bereits verwendet. Bitte den Ausführungsbeleg prüfen."
    : "Dieser Vorschlag ist abgelaufen oder nicht mehr ausführbar. Bitte den Coach um eine neue Prüfung bitten.";
}

function coachActionDiff(proposal) {
  const entries = document.createElement("ul");
  for (const entry of Array.isArray(proposal.diff) ? proposal.diff : []) {
    const item = document.createElement("li");
    item.textContent = [
      entry.name, entry.date, entry.sport, entry.scope, entry.units,
      entry.id && `ID: ${entry.id}`,
      entry.kcal, entry.entries && `${entry.entries} Einträge`,
      entry.carbs, entry.protein, entry.fat, entry.source,
      entry.keep && `Behalten: ${entry.keep}`,
      entry.delete && `Löschen: ${entry.delete}`,
    ].filter(Boolean).join(" · ");
    entries.append(item);
  }
  return entries;
}

function coachActionButtons(proposal) {
  const undo = proposal.action_type === "undo_change";
  const localWrite = proposal.action_type === "local_coach_write";
  const remoteWrite = proposal.action_type === "remote_coach_write";
  const actions = document.createElement("div");
  actions.className = "coach-action-card-actions";
  const later = document.createElement("button");
  later.type = "button";
  later.className = "secondary-button";
  later.textContent = remoteWrite || localWrite ? "Nicht freigeben" : "Später prüfen";
  later.addEventListener("click", () => {
    if (remoteWrite || localWrite) {
      later.disabled = true;
      api("/api/coach/actions/cancel", {
        method: "POST",
        body: JSON.stringify({ proposal_id: proposal.id }),
      }).then(() => {
        state.coachActionProposals = (state.coachActionProposals || []).filter((item) => item.id !== proposal.id);
        renderCoachActionReview();
      }).catch((error) => {
        later.disabled = false;
        toast(error.message, true);
      });
      return;
    }
    state.chatProposalRefreshPending = true;
    state.coachActionProposals = state.coachActionProposals.filter((item) => item.id !== proposal.id);
    renderCoachActionReview();
  });
  const confirm = document.createElement("button");
  confirm.type = "button";
  if (remoteWrite) {
    confirm.textContent = "Remote-Änderung freigeben";
  } else if (localWrite) {
    confirm.textContent = proposal.object_ids?.operation === "save_nutrition_product"
      ? "Produkt speichern"
      : "Mahlzeitvorlage speichern";
  } else if (undo) {
    confirm.textContent = "Änderung zurücknehmen";
  } else {
    confirm.textContent = "Garmin-Duplikat löschen";
  }
  confirm.addEventListener("click", () => executeCoachActionProposal(proposal, confirm));
  actions.append(later, confirm);
  return actions;
}

function coachActionCard(proposal) {
  const card = document.createElement("div");
  card.className = "coach-action-card";
  card.dataset.proposalStatus = proposal.status;
  const description = document.createElement("p");
  description.textContent = coachActionDescription(proposal);
  card.append(description);
  if (!["preview", "ready"].includes(proposal.status)) {
    const status = document.createElement("p");
    status.textContent = coachActionStatus(proposal);
    card.append(status);
    return card;
  }
  card.append(coachActionDiff(proposal), coachActionButtons(proposal));
  return card;
}

function renderCoachActionReview() {
  const root = $("#coachActionReview");
  const content = $("#coachActionReviewContent");
  if (!root || !content) return;
  const proposals = (state.coachActionProposals || []).filter((proposal) => ["undo_change", "delete_duplicate_intervals_activity", "remote_coach_write", "local_coach_write"].includes(proposal.action_type));
  content.replaceChildren(...proposals.map(coachActionCard));
  root.hidden = proposals.length === 0;
  $("#coachActionReviewTitle").textContent = "Aktion prüfen";
  root.querySelector(".coach-action-review-status").textContent = "Freigabe und Ergebnis getrennt prüfen";
}

function coachActionReceipt(proposal, result) {
  function content() {
    if (localWrite) {
      return nutritionProductWrite
        ? { message: "Das Produkt wurde lokal gespeichert.", title: "Produkt gespeichert", details: ["Nur lokal gespeichert; keine Synchronisierung an Intervals.icu"] }
        : { message: "Die Mahlzeitvorlage wurde lokal gespeichert.", title: "Mahlzeitvorlage gespeichert", details: ["Nur lokal gespeichert; keine Synchronisierung an Intervals.icu"] };
    }
    if (undo) return { message: "Die lokale Änderung wurde zurückgenommen.", title: "Änderung zurückgenommen" };
    if (duplicateDelete) return {
      message: "Garmin-Duplikat aus Intervals.icu gelöscht; die Wahoo-Aktivität bleibt erhalten.",
      title: "Duplikat gelöscht",
      details: ["Garmin-Duplikat in Intervals.icu gelöscht; Wahoo bleibt kanonisch"],
    };
    if (remoteWrite) {
      const queued = ["queued", "running"].includes(result.status)
        || Boolean(result.sync_job_id || result.sync_job_ids?.length);
      return queued
        ? { message: "Die freigegebene Änderung ist eingereiht; das Ergebnis steht noch aus.", title: "Remote-Änderung eingereiht" }
        : { message: "Die freigegebene Remote-Änderung wurde ausgeführt.", title: "Remote-Änderung ausgeführt" };
    }
    return { message: `${result.local_planned} Einheit(en) lokal geplant.` };
  }
  const undo = proposal.action_type === "undo_change";
  const duplicateDelete = proposal.action_type === "delete_duplicate_intervals_activity";
  const remoteWrite = proposal.action_type === "remote_coach_write";
  const localWrite = proposal.action_type === "local_coach_write";
  const nutritionProductWrite = localWrite && proposal.object_ids?.operation === "save_nutrition_product";
  let { message, title, details = ["Keine implizite Remote-Änderung"] } = content();
  if (!duplicateDelete && result.sync_job_ids?.length) details = result.sync_job_ids.map((id) => `Syncjob ${id} eingereiht`);
  else if (!duplicateDelete && result.sync_job_id) details = [`Syncjob ${result.sync_job_id} eingereiht`];
  else if (remoteWrite) details = ["Freigegebene Remote-Änderung direkt ausgeführt"];
  return { title, message, details, duplicateDelete, undo, remoteWrite, localWrite, nutritionProductWrite };
}

async function executeCoachActionProposal(proposal, button) {
  if (!proposal?.id || button.disabled || !["preview", "ready"].includes(proposal.status)) return;
  button.disabled = true;
  try {
    const confirmed = await api("/api/coach/actions/confirm", {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposal.id }),
    });
    const result = await api("/api/coach/actions/execute", {
      method: "POST",
      body: JSON.stringify({ action_token: confirmed.action_token, payload_hash: confirmed.proposed_action.payload_hash }),
    });
    if (proposal.action_type === "undo_change" && result.status !== "undone") throw new Error("Die Undo-Bestätigung fehlt; bitte den aktuellen Stand prüfen.");
    state.coachActionProposals = (state.coachActionProposals || []).filter((item) => item.id !== proposal.id);
    renderCoachActionReview();
    const receipt = coachActionReceipt(proposal, result);
    addCoachReceipt(receipt);
    toast(receipt.message);
    await load("/api/bootstrap?local=1", receipt.duplicateDelete ? ["plan", "performance"] : ["plan", "library", "profile", "feedback"]);
    if (receipt.nutritionProductWrite) void AppRouter.navigate("nutrition/products", { historyMode: "push" });
    else if (receipt.localWrite) void AppRouter.navigate("nutrition/meals", { historyMode: "push" });
    else if (!receipt.duplicateDelete && !receipt.undo && !receipt.remoteWrite) void AppRouter.navigate("plan", { historyMode: "push" });
  } catch (error) {
    addCoachReceipt({ title: "Aktion nicht bestätigt", message: error.message, status: "error" });
    if (error.reason === "proposal_expired") {
      proposal.status = "expired";
      renderCoachActionReview();
    } else if (["proposal_invalid", "proposal_used", "proposal_unavailable"].includes(error.reason)) {
      proposal.status = "used";
      renderCoachActionReview();
    }
    toast(error.message, true);
    button.disabled = false;
  }
}

function createPendingMessage(entry, index = 0) {
  const node = document.createElement("div");
  node.className = "message user pending";
  const text = document.createElement("div");
  text.textContent = entry.message;
  const label = document.createElement("span");
  label.className = "pending-label";
  label.textContent = index === 0 ? "Als Nächstes" : "Wird nach der aktuellen Antwort gesendet";
  const actions = document.createElement("div");
  actions.className = "pending-actions";
  const position = index + 1;
  actions.append(
    pendingQueueButton("Bearbeiten", `Bearbeiten: wartende Nachricht ${position}`, () => editQueuedChatMessage(entry.id)),
    pendingQueueButton("Entfernen", `Entfernen: wartende Nachricht ${position}`, () => removeQueuedChatMessage(entry.id)),
  );
  node.append(text, label, actions);
  return node;
}

function pendingQueueButton(text, name, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "message-action";
  button.textContent = text;
  button.setAttribute("aria-label", name);
  button.title = name;
  button.addEventListener("click", onClick);
  return button;
}

function mergeChatMessages(incoming, existing = state.data?.messages || []) {
  const messages = [];
  for (const message of [...existing, ...state.rejectedMessages, ...incoming]) {
    const index = messages.findIndex((entry) =>
      (message.id != null && entry.id != null && String(message.id) === String(entry.id))
      || (message.client_turn_id && entry.client_turn_id === message.client_turn_id && entry.role === message.role));
    if (index < 0) messages.push(message);
    else if (messages[index].id == null || message.id != null) messages[index] = { ...messages[index], ...message, optimistic: message.id == null };
  }
  return messages.sort((a, b) => {
    if (a.id != null && b.id != null) return Number(a.id) - Number(b.id);
    if (a.client_turn_id && a.client_turn_id === b.client_turn_id) return a.role === "user" ? -1 : 1;
    return (a.created_at || "").localeCompare(b.created_at || "");
  });
}

function reconcileCompletedChatMessage(message) {
  if (!state.data || !message || typeof message.content !== "string") return false;
  state.data.messages = mergeChatMessages([{ ...message, role: "assistant" }]);
  return true;
}

function rememberChatTurn(clientTurnId) {
  // Only an opaque operation identity survives a reload. No athlete text or credentials.
  try {
    if (clientTurnId) sessionStorage.setItem("coachPendingTurn", clientTurnId);
    else sessionStorage.removeItem("coachPendingTurn");
  } catch { }
}

function applyChatReceipt(receipt) {
  state.chatContentVersion += 1;
  if (receipt.message) reconcileCompletedChatMessage(receipt.message);
  if (Array.isArray(state.coachActionProposals) && state.coachActionProposals.length > 0) state.chatProposalRefreshPending = true;
  state.coachActionProposals = Array.isArray(receipt.proposed_actions) ? receipt.proposed_actions : [];
  addStructuredCoachReceipts(receipt);
  renderMessages(state.data?.messages || [], false);
}

let chatHistoryObserver = null;

function chatHistoryScroller(root) {
  return root.scrollHeight > root.clientHeight ? root : globalThis;
}

function chatHistoryAnchor(root) {
  // Anchor the first message the reader can see, not merely the first one in the DOM.
  const viewportTop = chatHistoryScroller(root) === root ? root.getBoundingClientRect().top : 0;
  const nodes = [...root.querySelectorAll("[data-message-id]")];
  const node = nodes.find((item) => item.getBoundingClientRect().bottom > viewportTop) || nodes[0];
  return node ? { id: node.dataset.messageId, top: node.getBoundingClientRect().top } : null;
}

function restoreChatHistoryAnchor(root, anchor, added, moveFocus) {
  const node = anchor && [...root.querySelectorAll("[data-message-id]")].find((item) => item.dataset.messageId === anchor.id);
  if (!node) return;
  chatHistoryScroller(root).scrollBy(0, node.getBoundingClientRect().top - anchor.top);
  if (moveFocus) {
    if (!node.hasAttribute("tabindex")) node.tabIndex = -1;
    node.focus({ preventScroll: true });
  }
  if (added === 1) announceChatStatus("1 ältere Nachricht geladen");
  else if (added > 1) announceChatStatus(`${added} ältere Nachrichten geladen`);
}

const chatFocusableSelector = "button, a[href], input, select, textarea, [tabindex]";

function chatFocusSnapshot(root) {
  // Automatic history loads replace every message node, which would drop focus from a message action to BODY.
  const active = document.activeElement;
  const message = active && root.contains(active) ? active.closest("[data-message-id]") : null;
  if (!message) return null;
  const index = active === message ? -1 : [...message.querySelectorAll(chatFocusableSelector)].indexOf(active);
  return { messageId: message.dataset.messageId, index };
}

function restoreChatFocus(root, snapshot) {
  if (!snapshot) return;
  const message = [...root.querySelectorAll("[data-message-id]")].find((item) => item.dataset.messageId === snapshot.messageId);
  if (!message) return;
  const control = snapshot.index >= 0 ? [...message.querySelectorAll(chatFocusableSelector)][snapshot.index] : null;
  const target = control || message;
  if (!target.hasAttribute("tabindex") && target === message) message.tabIndex = -1;
  target.focus({ preventScroll: true });
}

function appendHistoryPageButton(root, area) {
  const chat = area === "chat";
  if (chat) chatHistoryObserver?.disconnect();
  const cursor = state.data?.[chat ? "messages_next_cursor" : "library_next_cursor"];
  if (!cursor) return;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary-button";
  button.dataset.pageArea = area;
  button.textContent = chat ? "Weitere Nachrichten laden" : "Weitere Bibliothekseinheiten laden";
  let autoLoad = false;
  button.addEventListener("click", async () => {
    if (chat) chatHistoryObserver?.disconnect();
    const moveFocus = !autoLoad;
    autoLoad = false;
    const generation = state.sessionGeneration;
    const chatGeneration = state.chatGeneration;
    button.disabled = true;
    try {
      const result = await api(`${chat ? "/api/chat/history" : "/api/library"}?limit=100&cursor=${encodeURIComponent(cursor)}`);
      if (generation !== state.sessionGeneration || chatGeneration !== state.chatGeneration) return;
      if (chat) {
        if (result.generation !== state.data.messages_generation) { await loadChatHistoryFresh(); return; }
        const anchor = chatHistoryAnchor(root);
        const focus = moveFocus ? null : chatFocusSnapshot(root);
        const previousCount = (state.data.messages || []).length;
        state.data.messages = mergeChatMessages(result.messages || []);
        state.data.messages_next_cursor = result.next_cursor;
        renderMessages(state.data.messages, false, true);
        restoreChatHistoryAnchor(root, anchor, state.data.messages.length - previousCount, moveFocus);
        restoreChatFocus(root, focus);
      } else {
        const all = [...(state.data.library || []), ...(result.workouts || [])];
        state.data.library = [...new Map(all.map((entry) => [entry.id, entry])).values()];
        state.data.library_next_cursor = result.next_cursor;
        renderLibrary(state.data.library);
      }
    } catch (error) { toast(error.message, true); button.disabled = false; }
  });
  if (chat && "IntersectionObserver" in globalThis) {
    const observer = new IntersectionObserver((entries) => {
      // Wait until the initial jump to the latest message has settled; the next intersection re-arms loading.
      if (!entries.some((entry) => entry.isIntersecting) || state.chatInitialScrollPending || state.chatScrollRestoring) return;
      observer.disconnect();
      if (button.disabled) return;
      autoLoad = true;
      button.click();
    }, { rootMargin: "200px 0px 0px 0px" });
    chatHistoryObserver = observer;
    observer.observe(button);
  }
  root.append(button);
}

function messageAttachmentLabel(names) {
  try {
    const parsed = JSON.parse(names);
    return parsed.length ? String.fromCodePoint(10) + "Anhänge: " + parsed.join(", ") : "";
  } catch (parseError) {
    if (!(parseError instanceof SyntaxError)) throw parseError;
    return "";
  }
}

function restoreRejectedMessage(message) {
  const input = $("#messageInput");
  if (input.value.trim() || (state.chatAttachments || []).length) return toast("Bitte zuerst den aktuellen Entwurf bearbeiten.", true);
  input.value = message.content;
  resizeChatInput(input);
  state.chatAttachments = message.attachments || [];
  renderChatAttachments();
  state.chatDraftDirty = true;
  state.data.messages = state.data.messages.filter((entry) => entry !== message);
  state.rejectedMessages = state.rejectedMessages.filter((entry) => entry.client_turn_id !== message.client_turn_id);
  renderMessages(state.data.messages);
  jumpToLatestMessages();
  updateChatControls();
}

function appendMessageRetry(node, message) {
  if (!message.error) return;
  const error = document.createElement("p");
  error.className = "message-error";
  error.textContent = message.error;
  const retry = document.createElement("button");
  retry.type = "button";
  retry.textContent = "Als Entwurf übernehmen";
  retry.addEventListener("click", () => restoreRejectedMessage(message));
  node.append(error, retry);
}

function messageActionButton(icon, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "message-action";
  button.setAttribute("aria-label", label);
  button.title = label;
  button.innerHTML = `<svg class="message-action-icon" aria-hidden="true"><use href="#icon-${icon}"></use></svg>`;
  return button;
}

function renderMessageNode(message) {
  const node = document.createElement("div");
  node.className = `message ${message.role}`;
  if (message.id != null) node.dataset.messageId = String(message.id);
  if (message.role === "assistant") node.innerHTML = markdownToHtml(message.content);
  else {
    node.textContent = message.content;
    if (message.attachment_names) {
      const label = document.createElement("small");
      label.textContent = messageAttachmentLabel(message.attachment_names);
      node.append(label);
    }
  }
  appendMessageRetry(node, message);
  const actions = document.createElement("div");
  actions.className = "message-actions";
  const copy = messageActionButton("copy", "Nachricht kopieren");
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(String(message.content || ""));
      toast("Nachricht kopiert");
    } catch { toast("Nachricht konnte nicht kopiert werden", true); }
  });
  actions.append(copy);
  if (message.role === "user" && !messageAttachmentLabel(message.attachment_names)) {
    const edit = messageActionButton("edit", "Als Entwurf bearbeiten");
    edit.addEventListener("click", () => {
      const input = $("#messageInput");
      if (input.value.trim() || (state.chatAttachments || []).length) return toast("Bitte zuerst den aktuellen Entwurf bearbeiten.", true);
      input.value = String(message.content || "");
      delete input.dataset.requestKind;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      jumpToLatestMessages();
    });
    actions.append(edit);
  }
  node.append(actions);
  return node;
}

function appendChatStream(root, streamVisible) {
  const phase = state.chatRequest?.phase;
  if (!streamVisible) return false;
  const node = document.createElement("div");
  node.className = `message assistant streaming${phase === "recovering" ? " is-recovering" : ""}`;
  node.innerHTML = markdownToHtml(state.chatStreamText);
  root.append(node);
  return true;
}

function renderMessages(messages, forceScroll = false, preserveScroll = false) {
  const root = $("#messages");
  const appShellLoading = Boolean($("#appShell")?.classList.contains("is-loading"));
  const visibleMessages = messages || [];
  const signature = JSON.stringify([
    visibleMessages.map((message) => [message.id || null, message.created_at || null, message.role, message.content, message.attachment_names, message.error]),
    appShellLoading, state.data?.messages_next_cursor, state.chatStreamText, state.chatServerOperationId,
    state.chatResponseStarted, state.chatRequest?.phase || null, state.chatRequest?.responseMessageId || null,
    state.chatRequest?.responseMessageReceived || false,
    (state.coachActionProposals || []).map((proposal) => [proposal.id, proposal.status]),
    state.chatQueue.map((entry) => [entry.id, entry.mode, entry.message]),
  ]);
  const hasEmptyState = !visibleMessages.length && !appShellLoading && !state.chatRequest && !state.chatQueue.length;
  root.classList.toggle("has-empty-state", hasEmptyState);
  root.setAttribute("aria-busy", String(Boolean(state.chatRequest || state.chatServerOperationId)));
  $("#chatPanel")?.classList.toggle("chat-empty", hasEmptyState);
  if (root.dataset.signature === signature) return;
  const shouldScroll = !preserveScroll && (forceScroll || chatIsNearBottom());
  root.dataset.signature = signature;
  root.replaceChildren();
  appendHistoryPageButton(root, "chat");
  if (!visibleMessages.length && !state.chatRequest && !state.chatQueue.length) {
    root.append(appShellLoading ? createSkeletonStack(4) : createEmptyState("Dein Coach ist bereit", "Lege deine Ziele im Profil fest oder starte mit einer Schnellaktion."));
  }
  visibleMessages.forEach((message) => root.append(renderMessageNode(message)));
  state.chatQueue.forEach((entry, index) => root.append(createPendingMessage(entry, index)));
  const persistedResponse = Boolean(
    state.chatRequest?.responseMessageReceived
    || (state.chatRequest?.responseMessageId != null
      && visibleMessages.some((message) => message.id != null && String(message.id) === String(state.chatRequest.responseMessageId)))
  );
  const streamVisible = state.chatStreamText && !persistedResponse && ["running", "recovering", "reconciling"].includes(state.chatRequest?.phase);
  const showWorking = !persistedResponse && ["running", "recovering", "reconciling"].includes(state.chatRequest?.phase);
  appendChatStream(root, streamVisible);
  if (showWorking) root.append(createCoachWorkingIndicator());
  renderCoachActionReview();
  updateChatQueueStatus();
  updateChatComposerVisibility();
  if ((state.chatInitialScrollPending || shouldScroll) && !state.chatResponseStarted) scrollChatToLatest();
}
function cancelScheduledChatStreamRender() {
  if (chatStreamRenderFrame != null) cancelAnimationFrame(chatStreamRenderFrame);
  chatStreamRenderFrame = null;
  chatStreamStartScrollPending = false;
}

function scheduleChatStreamRender(scrollToStart = false) {
  chatStreamStartScrollPending = chatStreamStartScrollPending || scrollToStart;
  if (chatStreamRenderFrame != null) return;
  chatStreamRenderFrame = requestAnimationFrame(() => {
    chatStreamRenderFrame = null;
    const shouldScrollToStart = chatStreamStartScrollPending;
    chatStreamStartScrollPending = false;
    const root = $("#messages");
    const streaming = root?.querySelector(".message.assistant.streaming");
    if (!streaming) renderMessages(state.data?.messages || [], false);
    else {
      streaming.classList.toggle("is-recovering", state.chatRequest?.phase === "recovering");
      streaming.innerHTML = markdownToHtml(state.chatStreamText);
      if (!shouldScrollToStart) keepChatStreamInView(streaming);
      markChatContentArrived();
    }
    if (shouldScrollToStart && state.chatFollowLatest) scrollChatToResponseStart();
  });
}

function scrollChatToResponseStart() {
  const panel = $("#chatPanel");
  const root = $("#messages");
  if (!panel?.classList.contains("active") || !root) {
    state.chatResponseScrollPending = true;
    return;
  }
  state.chatResponseScrollPending = false;
  requestAnimationFrame(() => {
    if (!panel.classList.contains("active")) {
      state.chatResponseScrollPending = true;
      return;
    }
    const assistants = [...root.querySelectorAll(".message.assistant")];
    const responseId = state.chatRequest?.responseMessageId ?? state.chatResponseMessageId;
    const target = root.querySelector(".message.assistant.streaming")
      || (responseId == null ? null : assistants.find((node) => node.dataset.messageId === String(responseId)))
      || (!state.chatRequest ? assistants.at(-1) : null);
    if (!target) {
      state.chatResponseScrollPending = true;
      return;
    }
    const topGap = 16;
    scrollWindowForChat(Math.max(0, globalThis.scrollY + target.getBoundingClientRect().top - topGap));
    state.chatResponseMessageId = null;
    requestAnimationFrame(updateChatComposerVisibility);
  });
}

// While following, growing stream content keeps the newest line above the composer without hiding the start of the reply.
function keepChatStreamInView(streaming) {
  if (!state.chatFollowLatest || !$("#chatPanel")?.classList.contains("active")) return;
  const root = $("#messages");
  const latest = root && chatLatestVisibleNode(root);
  const composerTop = $("#chatForm")?.getBoundingClientRect().top;
  if (!latest || !Number.isFinite(composerTop)) return;
  const overlap = latest.getBoundingClientRect().bottom - (composerTop - 12);
  const headroom = streaming.getBoundingClientRect().top - 16;
  const delta = Math.min(overlap, headroom);
  if (delta > 0) scrollWindowForChat(globalThis.scrollY + delta);
}

// The newest visible child: a working indicator, stream, queued or optimistic message can sit below the last persisted reply.
function chatLatestVisibleNode(root) {
  return [...root.children].findLast((node) => !node.hidden && node.getClientRects().length > 0) || null;
}

function scrollChatToLatest() {
  const panel = $("#chatPanel");
  const root = $("#messages");
  if (!panel?.classList.contains("active") || !root) return;
  requestAnimationFrame(() => {
    if (state.chatInitialScrollPending && (!state.initialStateLoaded || document.readyState !== "complete")) return;
    root.scrollTop = root.scrollHeight;
    chatScrollAnchors.messages = root.scrollTop;
    const target = chatLatestVisibleNode(root);
    if (!target) return;
    state.chatInitialScrollPending = false;
    const composer = $("#chatForm");
    const targetBottom = target.getBoundingClientRect().bottom;
    const composerTop = composer?.getBoundingClientRect().top;
    const viewport = globalThis.visualViewport;
    const viewportBottom = (viewport?.offsetTop || 0) + (viewport?.height || globalThis.innerHeight);
    const targetGap = 12;
    const desiredBottom = Math.min(
      viewportBottom,
      Number.isFinite(composerTop) ? composerTop : viewportBottom,
    ) - targetGap;
    scrollWindowForChat(Math.max(0, globalThis.scrollY + targetBottom - desiredBottom));
    requestAnimationFrame(updateChatComposerVisibility);
  });
}

function restoreChatScrollPosition() {
  const panel = $("#chatPanel");
  const scrollY = state.chatScrollY;
  if (!panel?.classList.contains("active") || !Number.isFinite(scrollY)) return false;
  state.chatScrollRestoring = true;
  requestAnimationFrame(() => {
    if (!panel.classList.contains("active")) {
      state.chatScrollRestoring = false;
      return;
    }
    scrollWindowForChat(scrollY);
    requestAnimationFrame(() => {
      if (panel.classList.contains("active")) scrollWindowForChat(scrollY);
      state.chatScrollRestoring = false;
      updateChatComposerVisibility();
    });
  });
  return true;
}

function handleWindowScroll() {
  // The offset is tracked even while the chat is hidden, so a later comparison starts from the real position.
  const movedUp = chatScrollMovedUp("window", globalThis.scrollY);
  if (chatAcceptsReaderScroll()) {
    state.chatScrollY = globalThis.scrollY;
    if (movedUp) chatReaderScrolledUp();
  }
  updateChatComposerVisibility();
}

const CONTEXT_KEY_LABELS = {
  content: "Inhalt",
  note: "Hinweis",
  mode: "Modus",
  included_separately: "Separat übergeben",
  generated_at: "Erstellt am",
  snapshot_truncated: "Snapshot gekürzt",
  snapshot_compacted: "Snapshot kompakt aufbereitet",
  context_characters: "Zeichen im Kontext",
  projection: "Projektion",
  name: "Name",
  sports: "Sportarten",
  typical_weekly_volume: "Typischer Wochenumfang",
  timezone: "Zeitzone",
  source: "Quelle",
  status: "Status",
  unit: "Einheit",
  value: "Wert",
  date: "Datum",
  updated_at: "Aktualisiert am",
};
const CONTEXT_HIDDEN_KEYS = new Set(["field", "role"]);

function contextPreNode(text) {
  const pre = document.createElement("pre");
  pre.textContent = text;
  return pre;
}

function contextTextNode(text) {
  const node = document.createElement("p");
  node.className = "context-preview-text";
  node.textContent = text;
  return node;
}

function contextScalarText(key, value) {
  if (value === null || value === undefined || value === "") return "–";
  if (typeof value === "boolean") return value ? "Ja" : "Nein";
  if (typeof value === "number") return value.toLocaleString("de-DE", { maximumFractionDigits: 2 });
  if (typeof value === "string" && key.endsWith("_at")) return formatTime(value);
  return String(value);
}

const CONTEXT_PREVIEW_MAX_DEPTH = 3;
const CONTEXT_PREVIEW_MAX_ITEMS = 25;

function contextListNode(items, depth) {
  const list = document.createElement("ul");
  list.className = "context-preview-list";
  for (const item of items.slice(0, CONTEXT_PREVIEW_MAX_ITEMS)) {
    const entry = document.createElement("li");
    entry.append(contextValueNode(item, "", depth + 1));
    list.append(entry);
  }
  if (items.length > CONTEXT_PREVIEW_MAX_ITEMS) {
    const more = document.createElement("li");
    more.textContent = `… ${(items.length - CONTEXT_PREVIEW_MAX_ITEMS).toLocaleString("de-DE")} weitere Einträge`;
    list.append(more);
  }
  return list;
}

function contextObjectNode(object, depth) {
  const list = document.createElement("dl");
  list.className = "context-preview-values";
  for (const [key, item] of Object.entries(object)) {
    if (CONTEXT_HIDDEN_KEYS.has(key)) continue;
    const term = document.createElement("dt");
    term.textContent = CONTEXT_KEY_LABELS[key] || key.replaceAll("_", " ");
    const definition = document.createElement("dd");
    definition.append(contextValueNode(item, key, depth + 1));
    list.append(term, definition);
  }
  return list;
}

function contextValueNode(value, key = "", depth = 0) {
  if (value !== null && typeof value === "object") {
    const empty = Array.isArray(value) ? value.length === 0 : Object.keys(value).length === 0;
    if (empty) return contextTextNode("Keine Angaben");
    // Deeply nested provider data stays compact instead of building a huge DOM tree.
    if (depth >= CONTEXT_PREVIEW_MAX_DEPTH) return contextPreNode(JSON.stringify(value, null, 2));
    return Array.isArray(value) ? contextListNode(value, depth) : contextObjectNode(value, depth);
  }
  if (key === "content" && typeof value === "string") return contextPreNode(value);
  return contextTextNode(contextScalarText(key, value));
}

function renderContextPreview(preview) {
  const status = $("#systemContextPreviewStatus");
  const content = $("#systemContextPreviewContent");
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
    ["Letzte Chat-Eingabe", preview.chat_prompt],
    ["Coach-Kontext (vollständiger Text)", preview.context_text],
  ];
  sections.forEach(([title, value], index) => {
    if (value == null) return;
    const details = document.createElement("details");
    if (index < 4) details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = title;
    const body = document.createElement("div");
    body.className = "context-preview-body";
    body.append(typeof value === "string" ? contextPreNode(value) : contextValueNode(value));
    details.append(summary, body);
    content.append(details);
  });
  status.classList.remove("error");
  let snapshotNote = "";
  if (preview.snapshot_compacted) snapshotNote = " (Snapshot für den Coach kompakt aufbereitet)";
  else if (preview.snapshot_truncated) snapshotNote = " (Snapshot im Coach-Kontext gekürzt)";
  status.textContent = `Zuletzt erstellt: ${formatTime(preview.generated_at)}${snapshotNote}`;
  content.hidden = false;
}

function invalidateContextPreview() {
  const button = $("#systemContextPreviewButton");
  if (!button) return;
  button.dataset.loaded = "false";
  button.textContent = "Kontext aktualisieren";
}

async function loadContextPreview() {
  const button = $("#systemContextPreviewButton");
  const status = $("#systemContextPreviewStatus");
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


function latestAssistantMessageKey(messages) {
  const message = [...(messages || [])].reverse().find((entry) => entry.role === "assistant");
  if (!message) return null;
  if (message.id != null) return `id:${message.id}`;
  return `fallback:${message.created_at || ""}:${message.content || ""}`;
}

function applyChatGenerationChange(payload, result) {
  const previousAssistantKey = latestAssistantMessageKey(payload.messages);
  const generationChanged = state.data?.messages_generation !== undefined && result.generation !== state.data.messages_generation;
  const currentTurn = state.chatRequest?.clientTurnId;
  const currentTurnRetained = currentTurn && result.messages.some((message) => message.client_turn_id === currentTurn);
  if (generationChanged) {
    state.coachActionProposals = [];
    state.coachReceipts = [];
    if (!currentTurnRetained) resetChatAfterGenerationChange(currentTurn);
  }
  return { previousAssistantKey, generationChanged, currentTurn, currentTurnRetained };
}

function applyChatResult(payload, result, chatContentVersion) {
  if (!Array.isArray(result.messages)) throw new Error("Die Nachrichtenbestätigung fehlt.");
  const { previousAssistantKey, generationChanged, currentTurn, currentTurnRetained } = applyChatGenerationChange(payload, result);
  const retainedMessages = generationChanged
    ? (state.data?.messages || []).filter((message) => currentTurnRetained && message.client_turn_id === currentTurn)
    : undefined;
  const messages = mergeChatMessages(result.messages, retainedMessages);
  payload.messages_generation = result.generation;
  const nextAssistantKey = latestAssistantMessageKey(messages);
  if (state.initialStateLoaded && AppRouter.baseRoute() !== "coach" && nextAssistantKey && nextAssistantKey !== previousAssistantKey) {
    state.chatResponseScrollPending = true;
    const nextAssistant = [...messages].reverse().find((message) => message.role === "assistant");
    state.chatResponseMessageId = nextAssistant?.id ?? null;
  }
  Object.assign(payload, { messages, messages_next_cursor: result.next_cursor });
  if (chatContentVersion === state.chatContentVersion && Array.isArray(result.proposed_actions)) {
    state.coachActionProposals = result.proposed_actions;
    state.chatProposalRefreshPending = false;
  }
}


let chatHistoryReconciliation = null;
let chatHistoryReconciliationVersion = null;

async function refreshChatHistoryState() {
  const requestedVersion = state.chatContentVersion;
  if (chatHistoryReconciliation) {
    const activeVersion = chatHistoryReconciliationVersion;
    await chatHistoryReconciliation;
    if (requestedVersion === state.chatContentVersion && activeVersion === requestedVersion) return;
    return refreshChatHistoryState();
  }
  if (state.loadPromise) {
    await state.loadPromise.catch(() => {});
    return refreshChatHistoryState();
  }

  const version = state.chatContentVersion;
  const reconciliation = load("/api/bootstrap", ["chat"]);
  chatHistoryReconciliation = reconciliation;
  chatHistoryReconciliationVersion = version;
  try {
    await reconciliation;
  } finally {
    if (chatHistoryReconciliation === reconciliation) {
      chatHistoryReconciliation = null;
      chatHistoryReconciliationVersion = null;
    }
  }
  if (version !== state.chatContentVersion) await refreshChatHistoryState();
}


function chatAttachmentKind(name) {
  if (/\.gpx$/i.test(name)) return "GPX";
  if (/\.fit$/i.test(name)) return "FIT";
  return "Bild";
}

function chatAttachmentSize(item) {
  const data = String(item.data || "");
  let padding = 0;
  while (padding < 2 && data[data.length - 1 - padding] === "=") padding += 1;
  const bytes = Math.max(0, Math.floor(data.length * 3 / 4) - padding);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 }).format(Math.round(bytes / 1024))} KB`;
  return `${new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 }).format(bytes / (1024 * 1024))} MB`;
}

function renderChatAttachments() {
  const list = $("#chatAttachments");
  if (!list) return;
  list.replaceChildren();
  for (const [index, item] of (state.chatAttachments || []).entries()) {
    const chip = document.createElement("div");
    chip.className = "chat-attachment";
    const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    icon.setAttribute("class", "chat-attachment-icon");
    icon.setAttribute("viewBox", "0 0 24 24");
    icon.setAttribute("aria-hidden", "true");
    icon.setAttribute("focusable", "false");
    const iconPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    iconPath.setAttribute("d", "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5");
    icon.append(iconPath);
    const name = document.createElement("span");
    name.className = "chat-attachment-name";
    name.textContent = item.name;
    name.title = item.name;
    const meta = document.createElement("span");
    meta.className = "chat-attachment-meta";
    meta.textContent = `${chatAttachmentKind(item.name)} · ${chatAttachmentSize(item)}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chat-attachment-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Anhang ${item.name} entfernen`);
    remove.title = `Anhang ${item.name} entfernen`;
    remove.addEventListener("click", () => {
      state.chatAttachments.splice(index, 1);
      renderChatAttachments();
      updateChatControls();
    });
    chip.append(icon, name, meta, remove);
    list.append(chip);
  }
  list.hidden = !list.childElementCount;
  updateChatComposerVisibility();
}


function validateChatAttachmentFiles(files) {
  const valid = file => file.size && /\.(gpx|fit|png|jpe?g|webp)$/i.test(file.name) && (/\.(gpx|fit)$/i.test(file.name) ? file.size <= 5000000 : file.size <= 15000000);
  if ((state.chatAttachments || []).length + files.length > MAX_CHAT_ATTACHMENTS || files.some(file => !valid(file))) throw new Error(`Bis zu ${MAX_CHAT_ATTACHMENTS} Dateien auswählen. GPX/FIT dürfen höchstens 5 MB, Bilder höchstens 15 MB groß sein.`);
}
async function fileBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer()); let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) binary += String.fromCodePoint(...bytes.subarray(offset, Math.min(offset + 0x8000, bytes.length)));
  return btoa(binary);
}
async function prepareChatAttachment(file) {
  if (!/\.(png|jpe?g|webp)$/i.test(file.name)) return { name: file.name, data: await fileBase64(file) };
  try {
    const prepared = await prepareNutritionImage(file); const name = prepared.mime === file.type ? file.name : file.name.replace(/\.[^.]+$/, ".jpg");
    return { name, data: prepared.dataUrl.split(",")[1], type: prepared.mime };
  } catch (error) {
    if (file.size > 5_000_000) throw error;
    return { name: file.name, data: await fileBase64(file), type: file.type };
  }
}

function publishComposerHeight() {
  const composer = $("#chatForm");
  if (!composer || typeof ResizeObserver === "undefined") return;
  const publish = () => document.documentElement.style.setProperty("--composer-height", `${composer.offsetHeight}px`);
  new ResizeObserver(publish).observe(composer);
  publish();
}

// Decides what Enter does in the chat draft. Touch-first devices keep Enter for
// line breaks (the send button sends); desktop Enter sends and Shift+Enter breaks
// the line. IME composition never sends.
function chatEnterAction({ key, shiftKey = false, modifierKey = false, isComposing = false, touchFirst = false } = {}) {
  if (key !== "Enter" || isComposing) return "none";
  // Ctrl/Cmd+Enter keeps sending available to physical keyboards on touch devices.
  if (touchFirst) return modifierKey && !shiftKey ? "send" : "newline";
  return shiftKey ? "newline" : "send";
}

// Grows the draft up to the CSS max-height; the scrollbar appears only once the
// content no longer fits.
function resizeChatInput(input) {
  input.style.overflowY = "hidden";
  input.style.height = "auto";
  input.style.height = `${input.scrollHeight}px`;
  if (input.scrollHeight > input.clientHeight + 1) input.style.overflowY = "auto";
}

function setupCoachEvents() {
  publishComposerHeight();
  $("#messageInput").setAttribute("enterkeyhint", hasTouchFirstInput() ? "enter" : "send");
  $("#attachmentButton").addEventListener("click", () => $("#attachmentInput").click());

  $("#attachmentInput").addEventListener("change", async (event) => {
    const files = [...event.target.files]; event.target.value = "";
    if (!files.length || state.chatAttachmentsLoading) return;
    const generation = state.sessionGeneration; const chatGeneration = state.chatGeneration;
    state.chatAttachmentsLoading = true; updateChatControls();
    try {
      validateChatAttachmentFiles(files);
      const attachments = await Promise.all(files.map(prepareChatAttachment));
      if (generation !== state.sessionGeneration || chatGeneration !== state.chatGeneration) return;
      state.chatAttachments = [...(state.chatAttachments || []), ...attachments]; state.chatDraftDirty = true;
      renderChatAttachments(); jumpToLatestMessages();
    } catch (error) { toast(error.message, true); }
    finally { state.chatAttachmentsLoading = false; updateChatControls(); }
  });

  $("#chatForm").addEventListener("submit", sendMessage);
  $("#steerButton").addEventListener("click", steerCurrentChat);
  $("#cancelChatButton").addEventListener("click", cancelChat);

  $("#quickMessageTemplates").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-message]");
    if (!button || state.busy) return;
    const input = $("#messageInput");
    input.value = button.dataset.message || "";
    if (button.dataset.requestKind) input.dataset.requestKind = button.dataset.requestKind;
    else delete input.dataset.requestKind;
    input.dispatchEvent(new Event("input"));
    $("#chatForm").requestSubmit();
  });
  $("#voiceButton").addEventListener("click", toggleVoiceInput);
  $("#chatJumpToComposer").addEventListener("click", () => {
    jumpToLatestMessages();
  });

  $("#coachAdaptivePlanningButton").addEventListener("click", () => askCoach("Prüfe meine nächsten geplanten Einheiten und schlage sinnvolle Anpassungen vor."));

  $("#openaiChatResetButton").addEventListener("click", resetCoachChat);

  $("#systemContextPreviewButton").addEventListener("click", () => {
    $("#systemContextPreviewButton").dataset.loaded = "false";
    void loadContextPreview();
  });
  $("#messageInput").addEventListener("input", (event) => {
    // Capture the scroll position before the draft grows; only a reader already at the latest message follows the growth.
    const keepLatestVisible = $("#chatPanel")?.classList.contains("active") && chatIsNearBottom();
    state.chatDraftDirty = Boolean(event.target.value.trim());
    resizeChatInput(event.target);
    updateChatControls();
    if (keepLatestVisible) scrollChatToLatest();
  });
  $("#messageInput").addEventListener("keydown", (event) => {
    const action = chatEnterAction({
      key: event.key,
      shiftKey: event.shiftKey,
      modifierKey: event.ctrlKey || event.metaKey,
      isComposing: event.isComposing || event.keyCode === 229,
      touchFirst: hasTouchFirstInput(),
    });
    if (action !== "send") return;
    event.preventDefault();
    $("#chatForm").requestSubmit();
  });

  globalThis.addEventListener("scroll", handleWindowScroll, { passive: true });
  globalThis.addEventListener("wheel", handleChatWheel, { passive: true });
  globalThis.addEventListener("touchstart", handleChatTouchStart, { passive: true });
  globalThis.addEventListener("touchmove", handleChatTouchMove, { passive: true });
  globalThis.addEventListener("keydown", handleChatScrollKey);
  $("#messages").addEventListener("scroll", handleChatMessagesScroll, { passive: true });
}
