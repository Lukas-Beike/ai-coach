const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const { chatEnterAction } = extractFunctions("coach.js", ["chatEnterAction"]);

test("desktop Enter sends the draft", () => {
  assert.equal(chatEnterAction({ key: "Enter", shiftKey: false, isComposing: false, touchFirst: false }), "send");
});

test("desktop Shift+Enter inserts a line break", () => {
  assert.equal(chatEnterAction({ key: "Enter", shiftKey: true, isComposing: false, touchFirst: false }), "newline");
});

test("touch Enter inserts a line break and leaves sending to the send button", () => {
  assert.equal(chatEnterAction({ key: "Enter", shiftKey: false, isComposing: false, touchFirst: true }), "newline");
});

test("touch Shift+Enter inserts a line break", () => {
  assert.equal(chatEnterAction({ key: "Enter", shiftKey: true, isComposing: false, touchFirst: true }), "newline");
});

test("touch Ctrl/Cmd+Enter sends from a physical keyboard", () => {
  assert.equal(chatEnterAction({ key: "Enter", modifierKey: true, touchFirst: true }), "send");
  assert.equal(chatEnterAction({ key: "Enter", shiftKey: true, modifierKey: true, touchFirst: true }), "newline");
});

test("IME composition never triggers an action", () => {
  assert.equal(chatEnterAction({ key: "Enter", shiftKey: false, isComposing: true, touchFirst: false }), "none");
  assert.equal(chatEnterAction({ key: "Enter", shiftKey: false, isComposing: true, touchFirst: true }), "none");
});

test("keys other than Enter trigger no action", () => {
  assert.equal(chatEnterAction({ key: "a", shiftKey: false, isComposing: false, touchFirst: false }), "none");
  assert.equal(chatEnterAction({ key: "Escape", shiftKey: false, isComposing: false, touchFirst: true }), "none");
});
