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

// Runs the backup restore for a chosen file against a scripted confirmation and server answer.
async function restoreWith({ file = { name: "x.backup" }, confirmed = true, answer = async () => ({}) } = {}) {
  const nodes = { "#backupFileInput": { files: file ? [file] : [] }, "#backupRestoreButton": new FakeElement("button") };
  const log = [];
  const context = extractFunctions("settings.js", ["restoreDatabaseBackup"], {
    $: (selector) => nodes[selector],
    state: { sessionGeneration: 0 },
    AbortController,
    setTimeout: () => 1,
    clearTimeout() {},
    requestConfirmation: async (message, options) => { log.push(["confirm", options.title, message]); return confirmed; },
    toast: (message, isError) => log.push(["toast", message, Boolean(isError)]),
    invalidateProviderChecks: () => log.push(["invalidate"]),
    showLogin: () => log.push(["login"]),
    AppApi: { request: async (path, options, onUnauthorized) => { log.push(["request", path, options]); return answer(onUnauthorized); } },
  });
  await context.restoreDatabaseBackup();
  return { log, button: nodes["#backupRestoreButton"], steps: log.map(([step]) => step) };
}

test("a restore asks for confirmation first and sends the chosen file only after it", async () => {
  const file = { name: "pacecraft.backup" };
  const { log, steps, button } = await restoreWith({ file });
  assert.deepEqual(steps, ["confirm", "request", "toast", "invalidate", "login"]);
  assert.equal(log[0][1], "Datenbank-Backup wiederherstellen?");
  assert.match(log[0][2], /vorher gesichert und durch die ausgewählte Datei ersetzt/);
  const [, path, options] = log[1];
  assert.equal(path, "/api/privacy/restore");
  assert.deepEqual([options.method, options.headers["Content-Type"], options.timeoutMs], ["POST", "application/octet-stream", 130_000]);
  assert.equal(options.body, file);
  assert.deepEqual(log[2].slice(1), ["Backup wiederhergestellt. Bitte erneut anmelden.", false]);
  assert.equal(button.disabled, false);
});

test("a restore without a chosen file or without confirmation sends nothing", async () => {
  const noFile = await restoreWith({ file: null });
  assert.deepEqual(noFile.steps, []);
  const declined = await restoreWith({ confirmed: false });
  assert.deepEqual(declined.steps, ["confirm"]);
  assert.equal(declined.button.disabled, false);
});

test("a failed restore reports the error, keeps the session and the data, and allows a retry", async () => {
  const unconfirmed = Object.assign(new Error("abort"), { name: "AbortError" });
  for (const [failure, message] of [
    [new Error("Das Backup ist ungültig."), "Das Backup ist ungültig."],
    [unconfirmed, "Die Bestätigung der Wiederherstellung fehlt. Der Server kann den Vorgang noch abschließen; bitte vor einem erneuten Versuch den Status prüfen."],
  ]) {
    const { log, steps, button } = await restoreWith({ answer: async () => { throw failure; } });
    assert.deepEqual(steps, ["confirm", "request", "toast"]);
    assert.deepEqual(log[2].slice(1), [message, true]);
    assert.equal(button.disabled, false);
  }
});

test("a restore answered with 401 shows the login once for the session that asked", async () => {
  const { steps } = await restoreWith({ answer: async (unauthorized) => { unauthorized(); throw new Error("Deine Sitzung ist abgelaufen."); } });
  assert.deepEqual(steps, ["confirm", "request", "login", "toast"]);
});
