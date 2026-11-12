const assert = require("node:assert/strict");
const { test } = require("node:test");
const { extractFunctions, FakeElement } = require("./frontend-harness.cjs");

function helpers() {
  return extractFunctions("plan-views.js", [
    "CALENDAR_MARKERS", "MARKER_WORD_GAP", "calendarMarkerSource", "CALENDAR_MARKER_PATTERN", "PLANNED_RAIN_FLAG_MIN_PERCENT", "PLANNED_UV_FLAG_MIN",
    "PLANNED_AQI_FLAG_MIN", "PLANNED_CAMS_POLLEN_FLAG_MIN", "PLANNED_DAY_STATUS_LABELS",
    "stripCalendarMarkers", "calendarMarkerKeys", "plannedDayStatusLabel", "plannedDayNoteSpecs", "plannedConflictLabels", "plannedAppointmentLabel",
  ]);
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

test("day notes show competition, confirmed rest status and one calendar line with deduplicated markers", () => {
  const { plannedDayNoteSpecs } = helpers();
  const specs = plannedDayNoteSpecs(
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
    { kind: "calendar", icon: "📅", text: "Arzt · Kein Training" },
  ]);
});

test("pause status and unknown status values are handled explicitly", () => {
  const { plannedDayStatusLabel, plannedDayNoteSpecs } = helpers();
  assert.equal(plannedDayStatusLabel("pause"), "Trainingspause");
  assert.equal(plannedDayStatusLabel("unknown"), null);
  assert.equal(plannedDayStatusLabel("constructor"), null);
  assert.deepEqual(plain(plannedDayNoteSpecs({}, [], "2026-10-10")), []);
});

test("conflicts use the backend labels as text, skip empty entries and drop duplicates", () => {
  const { plannedConflictLabels } = helpers();
  assert.deepEqual(
    plain(plannedConflictLabels([
      { code: "short_only", label: "Nur kurze Einheiten" },
      { code: "competition_ab", label: "" },
      { code: "short_only", label: "Nur kurze Einheiten" },
      null,
    ])),
    ["Nur kurze Einheiten"],
  );
  assert.deepEqual(plain(plannedConflictLabels(undefined)), []);
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

test("each calendar marker is named in German on the day note", () => {
  const { plannedDayNoteSpecs } = helpers();
  const labels = { "[NO_TRAINING]": "Kein Training", "[NO_INTENSITY]": "Keine Intensität", "[SHORT_ONLY]": "Nur kurze Einheiten" };
  for (const [token, label] of Object.entries(labels)) {
    const [note] = plannedDayNoteSpecs({ appointments: [{ name: `Kurs ${token}` }] }, [], "2026-10-10");
    assert.equal(note.text, `Kurs · ${label}`, token);
  }
});

test("a badge shows its text as text and hides its glyph from screen readers", () => {
  const { calendarBadge, calendarBadgeRow } = extractFunctions("plan-views.js", ["calendarBadge", "calendarBadgeRow"], {
    document: { createElement: (tag) => new FakeElement(tag), createTextNode: (text) => ({ text }) },
  });
  const badge = calendarBadge({ kind: "calendar", icon: "*", text: "<img src=x onerror=alert(1)>" });
  assert.equal(badge.className, "planned-badge is-calendar");
  assert.equal(badge.children[0].attributes["aria-hidden"], "true");
  assert.deepEqual(badge.children[1], { text: "<img src=x onerror=alert(1)>" });
  const row = calendarBadgeRow([{ kind: "calendar", text: "A" }, { kind: "day-status", text: "B" }]);
  assert.equal(row.className, "planned-badges");
  assert.deepEqual(row.children.map((child) => child.className), ["planned-badge is-calendar", "planned-badge is-day-status"]);
});
