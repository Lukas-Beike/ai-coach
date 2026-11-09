const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/coach.js"), "utf8");
const start = source.indexOf("function coachActionDescription");
const end = source.indexOf("\nfunction renderCoachActionReview", start);

class FakeNode {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
  }

  append(...nodes) { this.children.push(...nodes); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener() {}
}

function harness() {
  const context = vm.createContext({
    document: { createElement: (tag) => new FakeNode(tag) },
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    state: { coachActionUnknownIds: new Set() },
    executeCoachActionProposal() {},
    reconcileCoachActionProposal() {},
  });
  vm.runInContext(`${source.slice(start, end)};globalThis.card = coachActionCard;`, context);
  return context;
}

function texts(node) {
  return [node.textContent, ...node.children.flatMap(texts)];
}

function tagNames(node) {
  return [node.tagName, ...node.children.flatMap(tagNames)];
}

test("an unknown proposal action type renders a neutral error card without buttons", () => {
  const card = harness().card({ id: "proposal-x", status: "ready", action_type: "delete_everything" });

  assert.deepEqual(texts(card).filter(Boolean), ["Unbekannte Aktion"]);
  assert.equal(card.dataset.proposalStatus, "unknown");
  assert.equal(tagNames(card).includes("button"), false);
  assert.doesNotMatch(texts(card).join(" "), /löschen|Garmin|Intervals/i);
});

test("a known proposal action type keeps its confirm button", () => {
  const card = harness().card({ id: "proposal-1", status: "ready", action_type: "undo_change", diff: [] });

  assert.equal(tagNames(card).includes("button"), true);
  assert.ok(texts(card).includes("Änderung zurücknehmen"));
});
