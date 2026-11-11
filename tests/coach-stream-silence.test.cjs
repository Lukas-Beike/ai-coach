const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const source = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");

// Runs the real stream reader and failure recovery with a shortened silence window.
function coach() {
  const controller = new AbortController();
  const request = { phase: "running", clientTurnId: "turn-1" };
  const stream = { controller, operationId: "op-1", cancelRequested: false, request, serverError: false };
  const state = {
    sessionGeneration: 0,
    chatGeneration: 0,
    chatRequest: request,
    chatStream: stream,
    chatServerOperationId: null,
  };
  const calls = { polls: [], history: 0, toasts: 0 };
  // The silence window is shortened to 30 ms; the production constant is pinned by the test below.
  const context = extractFunctions("coach.js", ["readChatStreamChunk", "readChatStream", "recoverChatRequestFailure"], {
    CHAT_STREAM_SILENCE_MS: 30,
    AbortController,
    TextDecoder,
    setTimeout,
    clearTimeout,
    state,
    toast() { calls.toasts += 1; },
    cancelScheduledChatStreamRender() {},
    renderMessages() {},
    updateChatControls() {},
    scheduleChatStatusPoll: (delay) => calls.polls.push(delay),
    loadChatHistoryFresh: async () => { calls.history += 1; },
    invalidateContextPreview() {},
    consumeChatStreamBlock() {},
    chatRequestIsCurrent: () => true,
  });
  const chatContext = { chatGeneration: 0, sessionGeneration: 0, completed: false, background: false, request, stream, attachments: [], clientTurnId: "turn-1", message: "x" };
  return { context, state, calls, controller, chatContext, request };
}

const silentResponse = () => ({ body: { getReader: () => ({ read: () => new Promise(() => {}), cancel: async () => {} }) } });

test("the silence window is three missed heartbeats", () => {
  assert.match(source, /const CHAT_STREAM_SILENCE_MS = 45_000;/);
});

test("a silent chat stream is aborted and handed to the recovery polls", async () => {
  const { context, state, calls, controller, chatContext, request } = coach();
  let failure;
  try {
    await context.readChatStream(silentResponse(), chatContext);
  } catch (error) {
    failure = error;
  }
  assert.ok(failure, "the silent read must reject");
  assert.equal(controller.signal.aborted, true);
  assert.notEqual(failure.name, "AbortError");

  const outcome = await context.recoverChatRequestFailure(failure, chatContext);
  assert.equal(outcome, "recovering");
  assert.equal(request.phase, "recovering");
  assert.equal(state.chatStream, null);
  assert.equal(state.chatServerOperationId, "op-1");
  assert.deepEqual(calls.polls, [0]);
  assert.equal(calls.toasts, 0);
});

test("a stream that keeps delivering events is not aborted", async () => {
  const { context, controller, chatContext } = coach();
  const encoder = new TextEncoder();
  const frames = ["event: heartbeat\ndata: {}\n\n", "event: heartbeat\ndata: {}\n\n", "event: heartbeat\ndata: {}\n\n"];
  let sent = 0;
  const reader = {
    read: () => new Promise((resolve) => setTimeout(() => {
      if (sent < frames.length) resolve({ done: false, value: encoder.encode(frames[sent++]) });
      else resolve({ done: true });
    }, 20)),
    cancel: async () => {},
  };
  await context.readChatStream({ body: { getReader: () => reader } }, chatContext);
  assert.equal(sent, 3);
  assert.equal(controller.signal.aborted, false);
});
