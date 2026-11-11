const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, FakeElement } = require("./frontend-harness.cjs");

// Runs the confirmed local deletion against a scripted server and reports what the athlete is shown.
async function deleteWith(result) {
  const nodes = { "#privacyDeleteNotice": new FakeElement("p"), "#privacyDeleteResult": new FakeElement("p"), "#privacyDeleteButton": new FakeElement("button") };
  nodes["#privacyDeleteButton"].removeAttribute = (name) => { delete nodes["#privacyDeleteButton"].attributes[name]; };
  const toasts = [];
  const posts = [];
  const context = extractFunctions("settings.js", ["privacyInFlight", "setPrivacyButtonBusy", "privacyDeleteLeftovers", "deletePrivacyData"], {
    $: (selector) => nodes[selector],
    state: { loadSequence: 0, loadedAreas: new Set() },
    toast: (message, isError) => toasts.push([message, Boolean(isError)]),
    api: async (path, options) => {
      if (path === "/api/privacy/delete/preview") return { categories: [], confirmation_text: "LOKALE DATEN LÖSCHEN" };
      posts.push([path, options.method, JSON.parse(options.body)]);
      return result;
    },
    requestConfirmation: async () => "LOKALE DATEN LÖSCHEN",
    downloadDatabaseBackup() {}, clearStateSnapshot() {}, invalidateProviderChecks() {}, loadProviderChecks: async () => {}, load: async () => {},
  });
  await context.deletePrivacyData();
  return { notice: nodes["#privacyDeleteNotice"], result: nodes["#privacyDeleteResult"], toasts, posts };
}

test("a deletion that reached every provider shows no problem notice", async () => {
  const { notice, result, toasts, posts } = await deleteWith({ deleted_categories: { chat: 3 }, remote_delete_attempted: true, remote_conversation_deleted: true });
  assert.equal(notice.hidden, true);
  assert.equal(notice.textContent, "");
  assert.equal(result.hidden, false);
  assert.match(result.textContent, /chat: 3\. Remote-Providerdaten bleiben unverändert\./);
  assert.deepEqual(toasts, [["Lokale Daten gelöscht", false]]);
  assert.deepEqual(posts, [["/api/privacy/delete", "POST", { confirm: "LOKALE DATEN LÖSCHEN" }]]);
});

test("a remote deletion that could not be confirmed is named next to the local result", async () => {
  const { notice } = await deleteWith({ remote_delete_attempted: true, remote_conversation_deleted: false, wahoo_revoke_attempted: true, wahoo_revoked: false });
  assert.equal(notice.hidden, false);
  assert.match(notice.textContent, /^Lokale Daten wurden gelöscht, aber die OpenAI-Konversation konnte remote nicht bestätigt gelöscht werden und der Wahoo-Zugriff konnte bei Wahoo nicht widerrufen werden/);
});
