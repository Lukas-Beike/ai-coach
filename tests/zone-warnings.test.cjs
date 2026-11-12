const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions } = require("./frontend-harness.cjs");

const { zoneWarningLine: line, zoneWarningTitle: title } = extractFunctions("settings.js", ["SDK_FAILURE_TEXT", "zoneWarningLine", "zoneWarningTitle"]);
const item = { label: "FTP Rad", value_text: "260 W", source_label: "Garmin", age_days: 98 };

test("a stale threshold names value, source and age", () => {
  assert.equal(line({ ...item, reason: "stale" }), "FTP Rad 260 W · Garmin · 98 Tage alt");
  assert.equal(line({ ...item, reason: "stale", age_days: 1 }), "FTP Rad 260 W · Garmin · 1 Tag alt");
});

test("expired and SDK-frozen values say why", () => {
  assert.match(line({ ...item, reason: "expired" }), /nicht mehr verwendet$/);
  assert.match(line({ ...item, reason: "sdk_failed", age_days: 3 }), /3 Tage alt – wird nicht aktualisiert$/);
});

test("an explicitly set indoor FTP is a plain stale threshold", () => {
  assert.equal(
    line({ label: "Indoor-FTP", value_text: "250 W", source_label: "Lokal", age_days: 70, reason: "stale" }),
    "Indoor-FTP 250 W · Lokal · 70 Tage alt",
  );
});

test("the title names an SDK failure first", () => {
  assert.equal(title({ sdk_failure: null }), "Schwellen prüfen und neue Werte hier lokal speichern");
  assert.match(title({ sdk_failure: { reason: "login_failed" } }), /^Garmin-Login fehlgeschlagen · /);
  assert.match(title({ sdk_failure: { reason: "requests_failed" } }), /^Garmin-Abruf schlägt wiederholt fehl · /);
});
