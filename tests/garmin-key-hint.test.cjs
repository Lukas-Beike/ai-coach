const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function loadGarminKeyHint() {
  const source = fs.readFileSync(path.join(__dirname, "../public/sync-status.js"), "utf8").replace(/\r\n/g, "\n");
  const constant = source.slice(source.indexOf("const GARMIN_KEY_RENEWAL"), source.indexOf("\n", source.indexOf("const GARMIN_KEY_RENEWAL")) + 1);
  const start = source.indexOf("function garminKeyHint(");
  assert.notEqual(start, -1, "garminKeyHint must exist");
  const end = source.indexOf("\n}\n", start);
  const context = vm.createContext({});
  vm.runInContext(`${constant}${source.slice(start, end + 3)}\nthis.garminKeyHint = garminKeyHint;`, context);
  return context.garminKeyHint;
}

const garminKeyHint = loadGarminKeyHint();

test("no Personal API key shows no hint", () => {
  assert.deepEqual({ ...garminKeyHint({ personal_api: { configured: false }, sdk_skipped: { reason: "login_failed" } }) }, { text: "", urgent: false });
  assert.deepEqual({ ...garminKeyHint(undefined) }, { text: "", urgent: false });
});

test("rejected and expired keys are urgent and name the renewal", () => {
  for (const [state, word] of [["rejected", "abgelehnt"], ["expired", "abgelaufen"]]) {
    const hint = garminKeyHint({ personal_api: { configured: true, state, days_left: -2 } });
    assert.equal(hint.urgent, true);
    assert.match(hint.text, new RegExp(`Personal-API-Schlüssel ${word}`));
    assert.match(hint.text, /Garmin Connect Web erneuern/);
  }
});

test("expiring keys warn with the remaining days", () => {
  const view = (days) => garminKeyHint({ personal_api: { configured: true, state: "expiring", days_left: days } });
  assert.match(view(14).text, /läuft in 14 Tagen ab/);
  assert.match(view(1).text, /läuft in 1 Tag ab/);
  assert.match(view(0).text, /läuft heute ab/);
  assert.equal(view(5).urgent, false);
});

test("missing expiry and a skipped SDK login are quiet hints", () => {
  const hint = garminKeyHint({ personal_api: { configured: true, state: "expiry_missing" }, sdk_skipped: { reason: "mfa_required", at: "x" } });
  assert.equal(hint.urgent, false);
  assert.equal(hint.text, "Ablaufdatum des Personal-API-Schlüssels fehlt · Garmin-Login für Zusatzwerte erneuern");
  assert.equal(garminKeyHint({ personal_api: { configured: true, state: "valid" } }).text, "");
});
