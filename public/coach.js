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

async function loadChatHistoryFresh() {
  await refreshChatHistoryState();
}

async function refreshChatProposalsInBackground(expectedContentVersion) {
  if (baseRoute() !== "coach") return;
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
    if (retryAtLatestVersion && baseRoute() === "coach") void refreshChatProposalsInBackground(state.chatContentVersion);
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

async function pollChatStatus() {
  if (!state.data || document.visibilityState !== "visible" || !navigator.onLine) {
    scheduleChatStatusPoll(5_000);
    return;
  }
  if (state.chatStatusPollInFlight) return;
  const pollRequest = {};
  state.chatStatusPollInFlight = pollRequest;
  let running = false;
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
    if (state.chatStatusPollInFlight === pollRequest && !/Authentication/.test(error.message)) scheduleChatStatusPoll(5_000);
  } finally {
    if (state.chatStatusPollInFlight === pollRequest) {
      state.chatStatusPollInFlight = null;
      scheduleChatStatusPoll(running ? 1_500 : 5_000);
    }
  }
}

async function loadInitialState() {
  const sessionGeneration = state.sessionGeneration;
  state.initialStateLoaded = false;
  const route = routeFromHash();
  state.planSegment = planSegmentFromRoute(route);
  state.analysisSegment = analysisSegmentFromRoute(route);
  const areas = ["chat", "activities", "performance", "feedback", "profile"];
  areas.push("weather");
  if (baseRoute(route) === "plan") areas.push("plan", "library");
  await load("/api/bootstrap?local=1", areas);
  if (sessionGeneration !== state.sessionGeneration) return;
  state.initialStateLoaded = true;
  if (state.chatInitialScrollPending && baseRoute() === "coach") scrollChatToLatest();
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

function chatRequestIsCurrent(sessionGeneration, chatGeneration) {
  return sessionGeneration === state.sessionGeneration && chatGeneration === state.chatGeneration;
}

async function chatStreamResponse(message, requestKind, attachments, clientTurnId, stream) {
  return fetch("/api/chat/stream", {
    method: "POST",
    credentials: "same-origin",
    signal: stream.controller.signal,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": cookie("ic_csrf") },
    body: JSON.stringify({ message, client_turn_id: clientTurnId, request_kind: requestKind, attachments }),
  });
}

async function rejectChatStreamResponse(response, context) {
  const { attachments, chatGeneration, clientTurnId, message, sessionGeneration, stream } = context;
  stream.serverError = true;
  stream.rejected = true;
  let payload = {};
  try { payload = await response.json(); } catch { }
  if (!chatRequestIsCurrent(sessionGeneration, chatGeneration)) return false;
  if (response.status === 401) {
    const rejectedAttachments = [...(attachments || [])];
    showLogin();
    state.chatAttachments = rejectedAttachments;
    renderChatAttachments();
    const input = $("#messageInput");
    if (input.value.trim()) state.rejectedMessages.push({ role: "user", content: message, client_turn_id: clientTurnId, error: payload.error || "Bitte erneut anmelden." });
    else input.value = message;
    state.chatDraftDirty = true;
    toast(payload.error || "Bitte erneut anmelden; der Entwurf bleibt erhalten.", true);
  }
  throw globalThis.AppApi.responseError(response, typeof payload.error === "string" ? payload.error : `Anfrage fehlgeschlagen (${response.status})`, payload.reason || "http_error");
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
    const error = new Error(payload.message || "Die Coach-Anfrage ist fehlgeschlagen.");
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
    if (state.chatProposalRefreshPending && baseRoute() === "coach") void refreshChatProposalsInBackground(state.chatContentVersion);
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
  if (completed) scrollChatToResponseStart();
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
  const clientTurnId = secureToken("turn");
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
    if (!response.ok) {
      await rejectChatStreamResponse(response, context);
      return false;
    }
    await readChatStream(response, context);
    return await finishChatStream(context);
  } catch (error) {
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
  if (configured && !configured.openai && !configured.gemini) {
    toast("Kein KI-Dienst konfiguriert. Bitte hinterlege einen OpenAI- oder Gemini-API-Schlüssel in den Einstellungen.", true);
    return;
  }
  const input = $("#messageInput");
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
  const buttons = [$("#openaiChatResetButton"), $("#chatResetButton")].filter(Boolean);
  if (!buttons.length || !await requestConfirmation("Coach-Chat wirklich zurücksetzen und eine neue Unterhaltung beginnen?", { title: "Coach-Chat zurücksetzen?" })) return;
  buttons.forEach((button) => {
    button.disabled = true;
    button.textContent = "Wird zurückgesetzt…";
  });
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
    buttons.forEach((button) => {
      button.disabled = false;
      button.textContent = "Chat zurücksetzen";
    });
  }
}
