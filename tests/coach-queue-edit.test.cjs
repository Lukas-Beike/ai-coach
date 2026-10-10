const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");
const constStart = source.indexOf("const MAX_CHAT_ATTACHMENTS");
const start = source.indexOf("function removeQueuedChatMessage");
const end = source.indexOf("\nfunction chatRequestIsCurrent", start);

function attachments(count) {
  return Array.from({ length: count }, (_, index) => ({ name: `route-${index}.gpx`, data: "AA==" }));
}

function editQueue(queuedCount, draftCount) {
  assert.ok(constStart >= 0 && start >= 0 && end > start);
  const state = {
    chatQueue: [{ id: 1, message: "Nachricht", mode: "queue", requestKind: null, attachments: attachments(queuedCount) }],
    chatAttachments: attachments(draftCount),
  };
  const toasts = [];
  const context = vm.createContext({
    state,
    $: () => ({ value: "", style: {}, dispatchEvent() {}, focus() {} }),
    Event: class {},
    toast(message, isError) { toasts.push({ message, isError }); },
    renderMessages() {},
    renderChatAttachments() {},
    updateChatControls() {},
  });
  vm.runInContext(source.slice(constStart, source.indexOf("\n", constStart) + 1) + source.slice(start, end), context);
  const draft = state.chatAttachments;
  context.editQueuedChatMessage(1);
  return { state, draft, toasts };
}

test("editing a queued message merges attachments when the combined count is within the limit", () => {
  const { state, toasts } = editQueue(2, 2);
  assert.equal(state.chatQueue.length, 0);
  assert.equal(state.chatAttachments.length, 4);
  assert.deepEqual(toasts, []);
});

test("editing a queued message is refused and leaves the queue untouched when the combined count exceeds the limit", () => {
  const { state, draft, toasts } = editQueue(3, 2);
  assert.equal(state.chatQueue.length, 1);
  assert.equal(state.chatQueue[0].id, 1);
  assert.equal(state.chatQueue[0].attachments.length, 3);
  assert.equal(state.chatAttachments, draft);
  assert.equal(draft.length, 2);
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0].isError, true);
  assert.match(toasts[0].message, /^Höchstens 4 Anhänge pro Nachricht\./);
});
