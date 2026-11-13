const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, fakeDocument } = require("./frontend-harness.cjs");

function harness() {
  return extractFunctions("coach.js", ["coachActionCard", "coachActionDescription", "coachActionExpired", "coachActionStatus", "coachActionDiff", "coachActionButtons"], {
    document: fakeDocument(),
    providerIds: () => ({ garmin: "garmin", intervals: "intervals" }),
    state: { coachActionUnknownIds: new Set() },
    executeCoachActionProposal() {},
    reconcileCoachActionProposal() {},
  });
}

// A leaf's text; the whole card is read through its own textContent.
function elements(node) {
  return node.children.filter((child) => typeof child !== "string");
}

function texts(node) {
  return elements(node).length ? elements(node).flatMap(texts) : [node.textContent];
}

function tagNames(node) {
  return [node.tag, ...elements(node).flatMap(tagNames)];
}

test("an unknown proposal action type renders a neutral error card without buttons", () => {
  const card = harness().coachActionCard({ id: "proposal-x", status: "ready", action_type: "delete_everything" });

  assert.equal(card.textContent, "Unbekannte Aktion");
  assert.equal(card.dataset.proposalStatus, "unknown");
  assert.equal(tagNames(card).includes("button"), false);
  assert.doesNotMatch(card.textContent, /löschen|Garmin|Intervals/i);
});

test("a known proposal action type keeps its confirm button", () => {
  const card = harness().coachActionCard({ id: "proposal-1", status: "ready", action_type: "undo_change", diff: [] });

  assert.equal(tagNames(card).includes("button"), true);
  assert.ok(texts(card).includes("Änderung zurücknehmen"));
});
