# Intervals.icu workout export

The supported upload contract is native workout text in `description`.
Intervals.icu generates `workout_doc`; the application never uploads a
self-generated `workout_doc` as evidence of successful parsing.

References:

- [Official workout builder guide](https://forum.intervals.icu/t/workout-builder/1163/1)
- [Official API upload guide](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- [Provider response structure](https://forum.intervals.icu/t/downloading-planned-workouts-from-the-api/93737)

## Three eight-minute Sweetspot intervals

Use `duration_minutes: 63`, `sport: Ride`, and `target: POWER` with this
description. The two four-minute recoveries occur only between efforts.
The progressive warmup explicitly uses `ramp`.

```text
Warmup
- 15m ramp 50-70%
- 3m 80%
- 3m 50-60%

Main Set
- 8m 88-92% 85-95rpm
- 4m 50-60%
- 8m 88-92% 85-95rpm
- 4m 50-60%
- 8m 88-92% 85-95rpm

Cooldown
- 10m 50-60%

Wenn die Beine nach dem Wochenende noch schwer sind: nur 2 Intervalle fahren und den Rest locker ausrollen.
```

The optional alternative is plain text and does not alter the scheduled
63-minute baseline. A different baseline needs an explicit local workout edit.
Do not add parenthesized watt conversions to the steps: they introduce another
machine-readable target and may override the percentage target. Percentages
use the athlete's current Intervals.icu FTP settings.

`- 3x 8m ...` is not a repeat block. It can produce just one eight-minute
effort. Together with the other reported steps that yields 43 minutes.
Native repeats instead use a separate `3x` header immediately before the
steps, with blank lines around the block. Every contained step repeats, so
putting a four-minute recovery in that block adds a third recovery too.

## Two fifteen-minute Sweetspot intervals

The reported instructions total 61 minutes, not 65:

```text
Warmup
- 15m 50-70%

Main Set
- 15m 88-92%
- 6m 50-60%
- 15m 88-92%

Cooldown
- 10m 50-60%
```

The application rejects a conflicting 65-minute total instead of inventing
the missing four minutes or silently changing the training prescription.

## Success criteria

Local validation requires quantity-first steps, one intensity target per
step, explicit HR/Pace suffixes, unambiguous repeat boundaries, and consistent
timed totals. Strength descriptions remain unstructured. Distance-based steps
retain their distance; Intervals.icu estimates their time from athlete settings.

During an explicitly requested synchronization, the provider's response must
contain the expected expanded step sequence, matching durations/distances,
intensity types, units and values, ramp flags, internally consistent duration,
and positive calculated training load. A successful HTTP response or nonempty
diagram alone is insufficient. Failed verification leaves a sync error and
retains the remote identity, so correction and retry update the same resource.

Regression tests use synthetic provider responses, including the reported
43-minute structure and missing/changed targets. They do not connect to a live
athlete account. Actual provider parsing is checked at runtime on each export;
the local code update itself does not repair already synchronized workouts.

## Repair an existing calendar through the Coach

For example, ask in ordinary language:

> Pruefe und korrigiere alle zukuenftigen Einheiten: Sportart, Trainingsschritte,
> Zonen und Gesamtdauer. Gleiche danach den Plan vollstaendig mit Intervals.icu
> ab und entferne die alten falschen Eintraege und Dubletten.

The Coach reads local workout details, corrects them using the existing local
IDs, and queues `start_intervals_plan_sync` with `repair=true`, selected current
hashes and the requested period. Already-synchronized entries are included;
`all_pending` alone is insufficient. `read_training_state(include_inactive=true)`
also exposes superseded future units for removal. Larger selections are split
into batches. Follow `planned_units_page.next_cursor` until `has_more=false`
before edits or syncs, including every active unit and archived predecessor.
The cursor binds the ordering, inactive filter, date and planning revision;
concurrent plan changes require restarting enumeration. Reread all pages after
corrections to obtain current hashes. No fixed wording or trigger phrase is required.

Repair matches stored event IDs and exact external identities, updates the
existing event, checks its sport and provider-generated steps, removes its
identified duplicate copies, and rereads the future calendar. Archived/deleted
selected units are removed remotely. A repeated repair updates the same event;
failed parsing prevents duplicate cleanup, and failed cleanup remains an error
that can be retried. Races, unrelated workouts and completed/past records are
not cleanup targets. An ambiguous same-name/date record without a matching
identity is a conflict; the application never guesses ownership from a title.

Provider requests do not hold the database lock, so status polling remains
available. A per-unit guard excludes simultaneous pushes of the same workout.
Payload hashes are rechecked before remote mutations and before recording
success. An intervening local edit stays unsynchronized; a remote identity
created before the edit was detected is retained for the next repair.

An approved illness pause archives the original local units and preserves their
prescriptions and identities. It creates no placeholder workout or artificial
training load. A later explicit plan sync removes the mapped calendar workouts;
repair sync also removes their identified duplicate copies. The separate,
explicitly selected SICK calendar-event export remains available.

Editing a prescription clears its old load, intensity and parsed workout;
successful provider readback refreshes these values in the local calendar.
Adaptive recovery uses Pace for swimming, power for cycling and HR for running
and other aerobic sports.

The regression suite executes the real Coach tool and job path with synthetic
responses for a run incorrectly stored as WeightTraining, two remote copies,
sport correction, duplicate removal, and a second idempotent repair.
