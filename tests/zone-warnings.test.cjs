const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function slice(source, marker, terminator) {
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, `${marker} must exist`);
  return source.slice(start, source.indexOf(terminator, start) + terminator.length);
}

function loadZoneWarnings() {
  const source = fs.readFileSync(path.join(__dirname, "../public/settings.js"), "utf8").replace(/\r\n/g, "\n");
  const code = [
    slice(source, "const SDK_FAILURE_TEXT", "\n};\n"),
    slice(source, "function zoneWarningLine(", "\n}\n"),
    slice(source, "function zoneWarningTitle(", "\n}\n"),
  ].join("");
  const context = vm.createContext({});
  vm.runInContext(`${code}\nthis.line = zoneWarningLine; this.title = zoneWarningTitle;`, context);
  return context;
}

const { line, title } = loadZoneWarnings();
const item = { label: "FTP Rad", value_text: "260 W", source_label: "Garmin", age_days: 98 };

test("a stale threshold names value, source and age", () => {
  assert.equal(line({ ...item, reason: "stale" }), "FTP Rad 260 W · Garmin · 98 Tage alt");
  assert.equal(line({ ...item, reason: "stale", age_days: 1 }), "FTP Rad 260 W · Garmin · 1 Tag alt");
});

test("expired and SDK-frozen values say why", () => {
  assert.match(line({ ...item, reason: "expired" }), /nicht mehr verwendet$/);
  assert.match(line({ ...item, reason: "sdk_failed", age_days: 3 }), /3 Tage alt – wird nicht aktualisiert$/);
});

test("a missing indoor FTP names the outdoor FTP used instead", () => {
  assert.equal(
    line({ label: "Indoor-FTP", value_text: "260 W", reason: "indoor_missing" }),
    "Indoor-FTP fehlt – Indoor-Fahrten nutzen FTP Rad 260 W",
  );
  assert.equal(line({ label: "Indoor-FTP", value_text: null, reason: "indoor_missing" }), "Indoor-FTP fehlt");
});

test("the title names an SDK failure first", () => {
  assert.equal(title({ sdk_failure: null }), "Schwellen prüfen und neue Werte hier lokal speichern");
  assert.match(title({ sdk_failure: { reason: "login_failed" } }), /^Garmin-Login fehlgeschlagen · /);
  assert.match(title({ sdk_failure: { reason: "requests_failed" } }), /^Garmin-Abruf schlägt wiederholt fehl · /);
});
