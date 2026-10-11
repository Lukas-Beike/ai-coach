# Code review: coach intent detection and Garmin health mapping

Date: 2026-10-11
Branch: `t3code/fix-coach-intent-detection`
Scope: changes in `backend/coach/` (turn outcome, context selection) and
`backend/providers/garmin_health_mapping.py`.

## Findings

### 1. P1 - Empty-text successful turn no longer clears a failed pending request

`backend/coach/turn_outcome.py:299`

The new `not missing_answer` term in the clean-turn gate stops a successful
turn with tool effects but no model text from clearing a failed pending
request. `missing_answer` is true whenever the text is empty (line 210).

Scenario: a failed `save_nutrition_entry` leaves `coach_pending_request` with
`status=failed`. The athlete writes "Versuch es nochmal". The retry succeeds,
but the model returns only tool calls, so `response_text` returns `''`
(`backend/providers/openai_responses.py:219-226`). `missing_answer` is true,
the branch at lines 299-305 is skipped and the failed record survives. The
athlete's next "ja" is a continuation, selection falls back, and the model sees
the failed request and can re-run the completed write, creating a duplicate
diary entry. Before this change, effects alone cleared the pending request. No
test covers the empty-text case.

### 2. P2 - Short or unmatched messages keep a stale clarification active

`backend/coach/context_selection.py:183`

For `needs_clarification` pending requests, any message of three words or
fewer, or any message with no keyword match, keeps the stale clarification
active and forces fallback, skipping the domain check added by this change.

Scenario: pending clarification "Snack erfassen ... Soll ich den Snack so
eintragen?". The athlete writes "Plane Intervalle morgen" (3 words,
`weekly_planning`). The domain comparison is never reached, `is_pending_active`
is true, selection is fallback, and `compact_coach_dialogue` keeps the
nutrition clarification in context. The model is shown an unexecuted nutrition
write it was told to abandon and may run it. Lines 183-184 also cover longer
unmatched messages such as "Was haeltst du von Faszienrollen nach einem langen
Lauf".

### 3. P2 - Failed pending requests reactivated by common unanchored tokens

`backend/coach/context_selection.py:166`

`das`, `it` and `ok` in `CONTINUATION_PATTERN` (line 68) and `wiederhol` in
`RETRY_PATTERN` (line 69) are unanchored, so unrelated messages keep a failed
write active.

Scenario: failed "Fruehstueck erfassen" pending request. The athlete writes
"Das Training heute war hart, was empfiehlst du morgen?". `das` matches the
continuation pattern, `is_pending_active` is true and selection falls back with
the failed write still in context. "Wiederhole die Einheit von gestern" also
matches `RETRY_PATTERN`. This is the cross-domain hijack the change is meant to
prevent, and the new tests cover neither case.

### 4. P2 (latent) - Garmin weight/sleep shapes do not match the mapper

`backend/providers/garmin_health_mapping.py:337`

The mapper expects flat records with `calendarDate` and a unit, but the
collected Garmin weight shape is `dailyWeightSummaries[].summaryDate` with
`latestWeight.weight` and no unit. The mapper is not yet wired into
production, so real snapshots currently map to nothing.

Scenario: the snapshot holds
`{'weight': {'dailyWeightSummaries': [{'summaryDate': '2026-09-07', 'latestWeight': {'weight': 72800}}]}}`,
the shape read by `garmin_metrics` and `garmin_weight` and used in
`tests/test_performance_garmin_metrics.py`. `_records` (line 397) wraps the
whole dict as one record, finds no `calendarDate`, and emits one MISSING issue
with zero weight observations. If the nested record were reached, the missing
unit would produce UNKNOWN_VALUE. Sleep has the same gap:
`backend/performance/morning_battery.py:68` reads the nested `dailySleepDTO`,
which the sleep group at line 134 does not unwrap. Unit tests use only flat
fixtures, so this is not caught.

### 5. P2 - Abandoned clarification is never cleared by an unrelated clean turn

`backend/coach/turn_outcome.py:302`

The no-effects branch only clears `status=failed`. A `needs_clarification`
request abandoned by a clean, unrelated turn stays, so a later short "Ja"
revives it.

Scenario: pending nutrition clarification. The athlete ignores it and asks an
unrelated advisory question. The turn is clean, so lines 302-313 leave the
clarification in `coach_pending_request`
(`test_clean_advisory_turn_does_not_clear_active_clarification_pending_request`
codifies this). On the next turn "Ja" is a continuation, selection falls back
and the abandoned nutrition write is revived in context. The dialogue rules say
a new topic abandons the pending clarification, but the database state keeps it
alive.

### 6. P3 - `profile_or_checkin` regex lost terms

`backend/coach/context_selection.py:60`

The regex dropped `nutrition`, `ernaehrung`, `mahlzeit`, `fruehstueck` and
`befinden`, and narrowed `check.?in` to `check-in`, so "check in", "checkin"
and "Ernaehrung" no longer select that domain.

Scenario: "Mein Check in ist fertig" matched `profile_or_checkin` before and now
matches nothing, so the name becomes `general_coaching`. The continuation rule
(`len(set(matched) - {'today_training'}) > 1`) and the `needs_clarification`
domain check then see different inputs. Routing changes silently, and no test
covers the removed terms.

### 7. P3 - Non-atomic read/clear of `coach_pending_request`

`backend/coach/turn_outcome.py:305`

The clean-turn check reads `coach_pending_request` in one lock acquisition
(305-306) and clears it in a separate `unit_of_work` (317-318), so a failed
request written in between can be overwritten with null.

Scenario: a background Coach job persists a new failed request between line 306
and line 318. The read saw an older value or null, the later write sets null,
and the new failed request is lost. Doing the read, check and write in one
`unit_of_work` removes the window.

### 8. P3 - Record ids for list payloads drop the list index

`backend/providers/garmin_health_mapping.py:275`

Record ids for list payloads use only the `calendarDate`, so two records on the
same day share a `source_record_id`.

Scenario: a `readiness` or `cycling_ftp_history` list with two entries for one
`calendarDate` yields two observations of the same kind with identical
`provenance.source_record_id` (for example `readiness:2026-10-10`). Any dedupe
or provenance lookup keyed on that id merges or drops one of them. The record
index appears only in `MappingIssue` refs and is never stored with the
observation.

### 9. P3 (altitude) - Pending-request activation is a stack of heuristics

`backend/coach/context_selection.py:165`

Activation now combines word count, unmatched keywords, domain mapping and a
second continuation rule, and each has produced a bypass (findings 2 and 3).
The root cause is that a pending request's topic is inferred from message text
on every turn. Recording the pending request's domain or intent when it is
created, and reactivating only on an explicit retry or same-domain signal,
would remove the word-count and unmatched-keyword shortcuts.

### 10. P3 (reuse) - Duplicated Garmin key helpers

`backend/providers/garmin_health_mapping.py:256`

`_first_value` and the alias tuples duplicate helpers and key lists already
spread across `backend/performance`. `_first_present` is copied in at least five
performance modules (for example `eftp.py:10` and `daily_health.py:55`), and the
alias tuples at lines 96-134 repeat the lists in
`backend/performance/garmin_projection.py:12-66`. A Garmin key change would then
need edits in several places, and the copies can drift apart.

## Remediation

All ten findings are addressed in the task worktree:

| Findings | Change |
|---|---|
| 1 | Successful tool effects clear the failed pending request even when model text is empty. |
| 2, 3, 6, 9 | Pending requests record their domain; selection rejects domain conflicts and unrelated messages, restores check-in/nutrition terms, and retains explicit retries and clarification replies. Full-context and attachment-continuity payloads respect the same pending-request projection. |
| 4 | The mapper accepts daily weight summaries, nested latest weights with Garmin's implicit gram unit, and nested daily sleep DTOs including overall sleep scores. |
| 5 | Clean advisory turns clear abandoned clarifications, including turns using read tools. Incomplete new topics do not reuse an abandoned summary. |
| 7 | Pending-request reads, status checks, and clears run inside one writer transaction. |
| 8 | List observations include their record index in provenance IDs. |
| 10 | Provider-owned field aliases and first-present lookup are shared with performance readers; the provider-coupling baseline shrinks accordingly. |

Regression coverage includes empty-text success, topic changes, incidental pronouns,
retry wording, weekday clarification replies, attachment continuity, transaction
boundaries, nested Garmin payloads, declared units, and duplicate-date provenance.
Validation uses synthetic fixtures, temporary storage, and mocked providers.

Validation: the full backend suite passed in four shards (4,140 tests, 16
skipped). The final advisory-cleanup refinement also passed 28 focused tests,
including the intervening-read continuation regression. Changed Python files
pass Ruff checks and formatting, backend files pass mypy, and compilation and
Git whitespace checks pass. The Docker build succeeds; SQLCipher container
regressions use read-only sources, temporary storage and disabled networking.
