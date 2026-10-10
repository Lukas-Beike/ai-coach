const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const publicDir = path.join(__dirname, "../public");
const statusSource = fs.readFileSync(path.join(publicDir, "sync-status.js"), "utf8");
const actionsSource = fs.readFileSync(path.join(publicDir, "sync-actions.js"), "utf8");

// Runs the real waitForSyncJob against one terminal job DTO; non-retryable errors
// throw before any polling delay, so the test does not wait.
function waitForJob(job) {
  const start = statusSource.indexOf("const NON_RETRYABLE_PROVIDER_ERRORS");
  const end = statusSource.indexOf("function providerRequiresManualAttention");
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({ api: async () => job });
  vm.runInContext(statusSource.slice(start, end), context);
  vm.runInContext(actionsSource, context);
  return vm.runInContext("waitForSyncJob('job-1')", context);
}

const FALLBACK = "Die Anbindung ist nicht vollständig konfiguriert. Bitte die Verbindungseinstellungen unter Mehr prüfen.";

test("an expired Garmin login shows the item's actionable detail, not the configuration fallback", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "auth_required", items: [
      { status: "failed", error_class: "auth_required", error_detail: "Garmin-Login abgelaufen. Bitte MFA-Code eingeben." },
    ],
  }), { message: "Garmin-Login abgelaufen. Bitte MFA-Code eingeben." });
});

test("a non-retryable item takes precedence over another failed item", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "invalid_configuration", items: [
      { status: "failed", error_class: "plan_push_error", error_detail: "Generic push failure." },
      { status: "failed", error_class: "invalid_configuration", error_detail: "Der API-Schlüssel fehlt." },
    ],
  }), { message: "Der API-Schlüssel fehlt." });
});

test("a top-level job detail is used when no item explains the failure", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "invalid_configuration", error_detail: "Top-level detail.", items: [],
  }), { message: "Top-level detail." });
});

test("without any detail the configuration fallback is still shown", async () => {
  await assert.rejects(waitForJob({
    id: "job-1", status: "failed", error_class: "invalid_configuration", items: [{ status: "failed", error_class: "invalid_configuration", error_detail: null }],
  }), { message: FALLBACK });
});
