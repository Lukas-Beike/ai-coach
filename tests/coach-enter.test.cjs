const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");
const start = source.indexOf("function chatEnterAction(");
const end = source.indexOf("\nfunction setupCoachEvents(", start);

function loadChatEnterAction() {
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(`${source.slice(start, end)};globalThis.chatEnterAction = chatEnterAction;`, context);
  return context.chatEnterAction;
}

const chatEnterAction = loadChatEnterAction();

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
