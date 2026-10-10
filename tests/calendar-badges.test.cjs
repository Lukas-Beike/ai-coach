const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../public/plan-views.js"), "utf8");
const start = source.indexOf("const CALENDAR_MARKERS");
const end = source.indexOf("\nfunction calendarActualActivity(", start);

function helpers() {
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({});
  vm.runInContext(
    `${source.slice(start, end)};globalThis.helpers = { stripCalendarMarkers, calendarMarkerKeys, plannedDayStatusLabel, plannedDayBadgeSpecs, plannedConflictBadgeSpecs, plannedAppointmentLabel };`,
    context,
  );
  return context.helpers;
}

// vm contexts have their own Array/Object prototypes; normalise before deep comparison.
const plain = (value) => JSON.parse(JSON.stringify(value));

test("raw calendar marker tokens are removed from appointment labels", () => {
  const { stripCalendarMarkers, plannedAppointmentLabel } = helpers();
  assert.equal(stripCalendarMarkers("Arzt [NO_TRAINING]  [short_only] Termin"), "Arzt Termin");
  assert.equal(stripCalendarMarkers("[NO_INTENSITY]"), "");
  assert.equal(
    plannedAppointmentLabel({ name: "Physio [NO_INTENSITY]", start_local: "2026-10-10T08:30:00" }),
    "Physio · 08:30",
  );
  assert.equal(plannedAppointmentLabel({ name: "[SHORT_ONLY]", all_day: true }), "Trainingstermin · ganztägig");
});

test("marker flags and raw tokens both map to marker keys in a stable order", () => {
  const { calendarMarkerKeys } = helpers();
  assert.deepEqual(plain(calendarMarkerKeys({ short_only: true, no_training: true })), ["no_training", "short_only"]);
  assert.deepEqual(plain(calendarMarkerKeys({ name: "Sauna [NO_INTENSITY]" })), ["no_intensity"]);
  assert.deepEqual(plain(calendarMarkerKeys({ name: "Ruhig", no_training: false })), []);
  assert.deepEqual(plain(calendarMarkerKeys(null)), []);
});

test("day badges show competition, confirmed rest status and deduplicated markers", () => {
  const { plannedDayBadgeSpecs } = helpers();
  const specs = plannedDayBadgeSpecs(
    {
      day_status: "rest",
      no_training: true,
      appointments: [{ name: "Arzt [NO_TRAINING]", no_training: true, training_relevant: false }],
    },
    [
      { event_date: "2026-10-10", name: "Stadtlauf", priority: "A" },
      { event_date: "2026-10-11", name: "Anderer Tag", priority: "C" },
    ],
    "2026-10-10",
  );
  assert.deepEqual(plain(specs), [
    { kind: "competition", icon: "🏁", text: "A-Wettkampf: Stadtlauf" },
    { kind: "day-status", icon: "", text: "Ruhetag" },
    { kind: "marker", icon: "", text: "Kein Training" },
  ]);
});

test("pause status and unknown status values are handled explicitly", () => {
  const { plannedDayStatusLabel, plannedDayBadgeSpecs } = helpers();
  assert.equal(plannedDayStatusLabel("pause"), "Trainingspause");
  assert.equal(plannedDayStatusLabel("unknown"), null);
  assert.equal(plannedDayStatusLabel("constructor"), null);
  assert.deepEqual(plain(plannedDayBadgeSpecs({}, [], "2026-10-10")), []);
});

test("conflict badges use the backend labels as text and skip empty entries", () => {
  const { plannedConflictBadgeSpecs } = helpers();
  assert.deepEqual(
    plain(plannedConflictBadgeSpecs([
      { code: "short_only", label: "Nur kurze Einheiten" },
      { code: "competition_ab", label: "" },
      null,
    ])),
    [{ kind: "conflict", icon: "⚠", text: "Konflikt: Nur kurze Einheiten" }],
  );
  assert.deepEqual(plain(plannedConflictBadgeSpecs(undefined)), []);
});

test("tolerant marker spellings are stripped and detected like the backend", () => {
  const { stripCalendarMarkers, calendarMarkerKeys, plannedAppointmentLabel } = helpers();
  assert.equal(stripCalendarMarkers("Arzt (NO TRAINING) Termin"), "Arzt Termin");
  assert.equal(stripCalendarMarkers("Physio [NO-TRAINING]"), "Physio");
  assert.equal(stripCalendarMarkers("Sauna [ no intensity ]"), "Sauna");
  assert.equal(stripCalendarMarkers("Lauf (short-only] Termin"), "Lauf Termin");
  assert.equal(stripCalendarMarkers("Kurs [NOTRAINING]"), "Kurs");
  assert.equal(stripCalendarMarkers("Stadtlauf Termin"), "Stadtlauf Termin");
  assert.equal(stripCalendarMarkers("NO TRAINING ohne Klammern"), "NO TRAINING ohne Klammern");
  assert.deepEqual(plain(calendarMarkerKeys({ name: "Arzt (NO TRAINING)" })), ["no_training"]);
  assert.deepEqual(plain(calendarMarkerKeys({ name: "Lauf [short_only" })), []);
  assert.equal(
    plannedAppointmentLabel({ name: "Physio (No-Intensity)", start_local: "2026-10-10T08:30:00" }),
    "Physio · 08:30",
  );
});
