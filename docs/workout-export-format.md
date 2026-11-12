# Intervals.icu workout export

The supported upload contract is native workout text in `description`.
Intervals.icu generates `workout_doc`; the application never uploads a
self-generated `workout_doc` as evidence of successful parsing.

Executable steps are required for endurance families such as cycling, running,
swimming, walking/hiking, rowing, Nordic skiing and their indoor variants.
Other supported activities, including Yoga, Pilates, Golf and RockClimbing,
retain prose instructions. Their exported sport is still checked on provider
readback; no endurance graph or calculated load is required.

A strength unit goes to Intervals.icu as a `NOTE` calendar event (type
`WeightTraining`), never as a `WORKOUT`, because Intervals.icu forwards workouts
to Garmin as one unnamed step. Its text is generated from the unit's exercise
structure (one line per exercise; free text without a structure), and readback requires the `NOTE` category.
The structured strength workout reaches the watch only through the explicit
Garmin push.

A run unit with step text goes to Garmin through the same push as a running
workout (sport running, one segment; the name defaults to "Lauf", the
description starts with "Pacecraft"). Warm-up and cool-down steps follow their
block header, a repeated block is a repeat group, and a step ends by time or
distance. Percent and zone targets are resolved to absolute watts, bpm or m/s
from the athlete's run zones on the unit's date, and the heart-rate cap is sent
as bpm. A ramp, a pace unit other than /km or /mi, or a capped run without a
known threshold heart rate is not sent. Switch off Intervals.icu's Garmin
upload for running, or each run arrives twice.

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
effort. Together with the other reported steps that yields 43 minutes. The
application rejects such a line as an ambiguous step.
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
timed totals. Strength notes carry prose only. Distance-based steps
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
IDs, and queues `start_intervals_plan_sync` with `repair=true`, the current
`expected_revision`, `local_plan` authorization and the requested period
(`sync_scope=selected`, omitting `entries`). The server selects and validates
the complete period before splitting its manifest into jobs. An explicit
selection must include every unit in that period; incomplete selections are
rejected before any job is queued. Already-synchronized entries are included;
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

Each bounded repair job shares one initial calendar collection read and one
final provider read across its units. Confirmed writes update the in-memory
index, but only the final provider snapshot can mark a unit synchronized. A
failed final read leaves the affected units retryable, retaining remote IDs.

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
Adaptive recovery uses Pace for pool and open-water swimming, power for cycling and HR for running
and other aerobic sports.

The regression suite executes the real Coach tool and job path with synthetic
responses for a run incorrectly stored as WeightTraining, two remote copies,
sport correction, duplicate removal, and a second idempotent repair.

## Native workout text syntax

Endurance workouts synchronized to Intervals.icu must comply with its native workout builder syntax. The application validates the text locally before any remote synchronization.

### Cycling Intervals (Power & Cadence Targets)
```text
Warmup
- 15m ramp 50-70%
- 3m 80%
- 3m 50-60%

Main Set
3x
- 8m 88-92% 85-95rpm
- 4m 50-60%

Cooldown
- 10m 50-60%
```

### Running Workout (Pace & Heart Rate Targets)
```text
Warmup
- 15m Z1 HR

Main Set
- 6km Z2 Pace
- 1km 90-95% HR

Cooldown
- 10m Z1 HR
```

## Strict Validation Rules
1. **Executable Steps Required**: Endurance workouts (Ride, Run, Swim, Row) require explicit step durations (`h`, `m`, `s`, `'`, `"`) or distances (`km`, `mtr`, `mi`, `yd`) paired with an intensity target.
2. **Relative Targets Preferred**: Use percentage FTP (`88-92%`) or zones (`Z2 HR`). Do not hardcode absolute wattages into steps, as they conflict with dynamic FTP adjustments.
3. **Repeat Block Formatting**: Multi-interval blocks must begin with a repeat line (e.g., `3x`) and must be surrounded by blank lines. All steps within the block repeat equally.
4. **Non-Endurance Activities**: Strength training, yoga, and mobility workouts use free-text prose instructions and bypass step validation.
