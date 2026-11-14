# competitions-and-seasons Specification

## Purpose

Describe local target competitions, their explicit synchronization/conflict boundary, season phase projection, observed preparation evidence. Provider transport details belong to provider synchronization capabilities.

## Requirements

### Requirement: CS1 Validated target-competition records
The system SHALL normalize bounded competition identity, local start/date, sport, priority/category, distance, target, duration and notes, preserving unsupported sport detail locally rather than inventing a supported provider sport.

#### Scenario: Valid target event
- **WHEN** a competition with a name and valid event/start date is saved
- **THEN** it receives a local UUID, bounded text, normalized canonical sport/environment, and A/B/C priority with matching race category; known kilometer distance is normalized to meters.

#### Scenario: Missing or invalid data
- **WHEN** name/date, priority, start time or duration fails validation
- **THEN** the save is rejected; duration must remain between zero and 604800 seconds.

#### Scenario: Free-text distance or sport
- **WHEN** distance or sport cannot be interpreted reliably
- **THEN** free-form distance remains local text and unsupported sport remains other with detail; invalid numeric provider distance is not invented for export.

#### Scenario: Text limits
- **WHEN** a competition is saved
- **THEN** the name is cut to 200 characters, sport and distance to 80, target to 1000, course profile and notes to 2000, description to 12000 and the external id to 200.

Evidence: `backend/planning/competitions.py:COMPETITION_TEXT_LIMITS`, `backend/planning/competitions.py:normalize_competition`, `backend/planning/competitions.py:competition_start`, `backend/planning/competitions.py:competition_distance`, `backend/planning/competitions.py:competition_stored_sport`, `backend/planning/competitions.py:competition_event_optional_payload`; `tests/test_planning_competitions.py:test_normalize_preserves_existing_contract`, `tests/test_planning_competitions.py:test_validation_rejects_missing_identity_and_invalid_bounds`, `tests/test_planning_competitions.py:test_sport_aliases_and_intervals_fallbacks`, `tests/test_planning_competitions.py:test_external_id_and_optional_payload_preserve_types_and_input`.

### Requirement: CS2 Local competition create and partial edit
The system SHALL create or edit one local competition with stable identity, preserve omitted Coach edit fields, enforce the upcoming-race bound, and audit the mutation in its transaction without an implicit remote push.

#### Scenario: New local competition
- **WHEN** an authorized `save_competition` creates a valid target event without an existing ID
- **THEN** the record is stored locally and returned with the current competition list; no Intervals.icu push is performed by saving it.

#### Scenario: Partial edit
- **WHEN** the Coach resolves an existing competition ID and changes selected fields
- **THEN** the existing identity and omitted required/optional details are preserved under the implemented merge policy and the edit is audited.

#### Scenario: Upcoming-race bound
- **WHEN** twenty races dated today or later are stored and a save creates a race dated today or later or moves a past race into the future
- **THEN** it fails with "Es können maximal 20 anstehende Wettkämpfe gespeichert werden."; past races never count and are never limited, and editing an upcoming race is not blocked. A bounded list (profile, bootstrap) keeps the latest races, so no upcoming race drops out.

#### Scenario: Missing identity or history failure
- **WHEN** an edit ID is malformed/missing in storage or audit persistence fails
- **THEN** the request fails without creating a substitute event or committing an unaudited partial save.

#### Scenario: Race day from the start time
- **WHEN** a start time is sent without a race day
- **THEN** the day is taken from the start time; a sent day that differs fails with 400 "Startzeit und Wettkampftag passen nicht zusammen: <Tag der Startzeit> statt <gesendeter Tag>.".

#### Scenario: Clearing optional fields
- **WHEN** the Coach edits a competition
- **THEN** an absent field keeps its stored value, while an optional field (`starts_at_local`, `distance`, `target`, `course_profile`, `notes`, `description`, `planned_duration_s`) sent empty or null is cleared; `-1` is read as null for the planned duration.

Detailed contract: a save returns `status` (`created` or `updated`), `competition` and `competitions`; a malformed id is 400 "Ungültige lokale Wettkampf-ID." and an unknown one 404 "Wettkampf nicht gefunden.".

Evidence: `backend/planning/competition_service.py:CompetitionService.save`, `backend/planning/competition_service.py:_coach_payload`, `backend/planning/competition_service.py:_merge_update`, `backend/planning/competition_service.py:_with_derived_event_date`; `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService.execute`; `tests/test_planning_competition_service.py:test_a_start_time_on_another_day_than_the_event_date_is_rejected`, `tests/test_planning_competition_service.py:test_create_and_partial_update_share_one_transaction_with_history`, `tests/test_planning_competition_service.py:test_empty_values_clear_optional_fields_and_absent_ones_keep_them`, `tests/test_planning_competition_service.py:test_failed_history_write_rolls_back_competition`, `tests/test_planning_competition_service.py:test_twenty_past_races_do_not_block_a_new_race`, `tests/test_planning_competition_service.py:test_twenty_upcoming_races_reject_the_next_one_and_keep_the_archive`, `tests/test_planning_competition_service.py:test_full_upcoming_cap_allows_past_race_and_blocks_move_into_future`; `tests/test_coach_tool_coverage.py:test_competition_lifecycle_syncs_only_after_explicit_followup`; `tests/test_coach_dialogue.py:test_competition_edit_uses_resolved_id_without_literal_name`.

### Requirement: CS4 Competition removal and remote tombstone retention
The system SHALL delete a locally selected competition under the applicable authorization, unlink any public-event candidate, and retain remote deletion intent for linked records until an authorized remote sync succeeds.

#### Scenario: Delete linked competition
- **WHEN** an authorized local delete targets an existing linked competition
- **THEN** local removal, candidate unlink and history are committed together, a tombstone preserves remote IDs and the result reports remote sync pending.

#### Scenario: Unlinked or missing competition
- **WHEN** an unlinked event is deleted or the requested ID does not exist
- **THEN** an unlinked delete needs no remote tombstone, while a missing ID reports not-found without removing other events.

#### Scenario: Failed remote delete
- **WHEN** a requested remote deletion fails
- **THEN** it does not consume the local deletion intent as if remote deletion succeeded and no upsert follows.

Detailed contract: a delete returns `status: deleted`, `competition_id`, `remote_sync_pending` and `competitions`.

Evidence: `backend/planning/competition_service.py:CompetitionService.delete`; `backend/sync/competitions.py:CompetitionSyncReconciler.clear_tombstones`; `tests/test_planning_competition_service.py:test_delete_creates_remote_tombstone`; `tests/test_sync_competitions.py:test_failed_remote_delete_does_not_clear_tombstones_or_upsert`.

### Requirement: CS5 Explicit competition sync and conflict recovery
The system SHALL keep remote pushes explicit and output-only (Intervals.icu receives competitions and is never a source of them), detect unsafe remote identity/missing-record cases, validate approval freshness, and offer deliberate keep-local/adopt-remote conflict resolution.

#### Scenario: Output only, no import
- **WHEN** a competition sync reads the remote events to match identities
- **THEN** no remote event ever becomes a local competition and a clean local row never takes remote values; a clean linked row inside the fetched calendar window whose remote event is gone, or a dirty unlinked row that matches a remote event only by name and date, is marked as a conflict instead.

#### Scenario: Named approved push
- **WHEN** the athlete explicitly requests competition synchronization, and the manifest is frozen when the request runs
- **THEN** outbound writes use stable identity and supported sport payloads, with concurrent local edits checked before marking captured records synced.

#### Scenario: Conflict choice
- **WHEN** a stored conflict is resolved as keep_local or adopt_remote
- **THEN** keep-local retains a local override for a later explicit push, while adopt-remote requires a valid remote event and updates the local record; invalid strategy, corrupt/missing conflict or unavailable remote data fails explicitly.

#### Scenario: Remote race deletion only for app-owned future events
- **WHEN** a competition sync deletes the remote race of a recorded deletion
- **THEN** it deletes it only when the event's external id starts with `intervals-coach-competition-`, the event is not paired with an activity and it is dated today or later; otherwise it is left alone and reported in `skipped_deletions` (`name`, `event_date`, `reason`) with the reason `not_app_owned`, `paired`, `past`, or `not_found` for an event that no longer exists.

#### Scenario: Unsupported sport
- **WHEN** a competition's sport has no Intervals.icu race type
- **THEN** it is not pushed (`skipped_items` with the reason `unsupported_sport`) and stays locally pending.

#### Scenario: One sync at a time
- **WHEN** a sync starts while another holds the lock
- **THEN** it returns `{"status": "already_running"}` without side effects; otherwise the lock is held during the run and released afterwards, also after a failure, and `last_competition_sync_at` or the redacted `last_competition_sync_error` is stored afterwards.

#### Scenario: Result and tombstones
- **WHEN** a run succeeds
- **THEN** it returns `status: ok`, `synced_at`, `pushed`, `skipped`, `skipped_items`, `conflicts`, `deleted_remote`, `skipped_deletions` and `total`; the tombstone of a skipped deletion is removed like that of a deleted one, while a failed delete call keeps all tombstones; a manifest that changed since the approval answers 409 "Der Wettkampfbestand hat sich seit der Freigabe geändert.", and a row edited since it was read is left alone.

Detailed contract: a dirty row that matches a remote event only by name and date becomes a conflict of type `identity_only` unless its state is `local_override`, and a dirty linked row whose event is gone becomes `{"type": "remote_missing", "detected_at"}`.

Evidence: `backend/planning/competition_service.py:CompetitionService.resolve_conflict`, `backend/planning/competitions.py:competition_delete_skip_reason`, `backend/sync/competitions.py:CompetitionSyncReconciler._reconcile_dirty`, `backend/sync/competitions.py:CompetitionSyncService._checked_deletions`, `backend/sync/competitions.py:CompetitionSyncService.sync`; `backend/planning/competitions.py:competition_remote_match`, `backend/planning/competitions.py:competition_conflict_action`; `backend/sync/competitions.py:CompetitionSyncReconciler`; `tests/test_planning_competition_service.py:test_conflict_resolution_preserves_both_strategies`; `tests/test_sync_competitions.py:test_app_owned_past_or_paired_event_is_skipped_with_its_reason`, `tests/test_sync_competitions.py:test_foreign_future_event_is_skipped_and_app_owned_event_is_deleted`, `tests/test_sync_competitions.py:test_linked_unsupported_sport_edit_stays_dirty_and_survives_refresh`, `tests/test_sync_competitions.py:test_sync_returns_already_running_without_side_effects`, `tests/test_sync_competitions.py:test_records_rejects_competition_changes_after_approval`, `tests/test_sync_competitions.py:test_dirty_remote_deviations_persist_identity_changed_and_missing_conflicts`, `tests/test_sync_competitions.py:test_optimistic_check_skips_competition_edited_after_capture`, `tests/test_sync_competitions.py:test_clean_row_keeps_local_indoor_environment_for_the_same_remote_type`.

### Requirement: CS6 Deterministic season phases and next event
The system SHALL derive a date-based season view from valid competition dates, sort it deterministically and identify the next nonpast event without claiming that phase alone proves preparation.

#### Scenario: Phase boundaries
- **WHEN** an event is before today, today through fourteen days away, fifteen through forty-two, forty-three through eighty-four, or farther away
- **THEN** its phase is completed, taper, peak, build or base respectively, with days-until and the local as-of date.

#### Scenario: Ordering and empty data
- **WHEN** several valid events or no valid events exist
- **THEN** events sort by date, priority and name; next_event is the first nonpast event or null.

#### Scenario: Invalid dates
- **WHEN** a stored row has no parseable event date
- **THEN** it is excluded from this date-based projection rather than assigned an invented phase.

Evidence: `backend/planning/season.py:season_plan_summary`, `backend/planning/season.py:planning_state`; `tests/test_planning_season.py:test_phase_boundaries`, `tests/test_planning_season.py:test_ignores_missing_or_invalid_event_dates`, `tests/test_planning_season.py:test_sorts_by_event_date_priority_name_and_selects_next_event`, `tests/test_planning_season.py:test_empty_competitions`.

### Requirement: CS7 Observed competition preparation with explicit unknowns
The system SHALL report preparation from eligible recorded sessions and known analysis dimensions over twelve calendar weeks, separately from phase and target assumptions, with missing evidence nullable or insufficient-data.

#### Scenario: Future or completed event
- **WHEN** preparation is read for a future or completed competition
- **THEN** its evidence window ends at today or that past event date respectively, uses Monday-Sunday weeks, and reports observed volume and long-session evidence by compatible sport.

#### Scenario: Confirmed target and dimensions
- **WHEN** distance has a reliable meter/kilometer basis, a target is saved and activity analyses expose known dimensions
- **THEN** target context and specificity include those confirmed values and known counts without deriving race readiness from the phase name alone.

#### Scenario: No history or uncertain target
- **WHEN** history is absent, distance units are ambiguous or no target is saved
- **THEN** the corresponding duration/distance/target remain null and preparation reports insufficient-data rather than treating absent records as zero training or a known race capability.

#### Scenario: Eligible sessions and field names
- **WHEN** sessions are counted for an event
- **THEN** only sessions of the competition's sport with the same indoor or virtual flag inside the evidence window count; the result holds per event `preparation` with status, window, the 12 weeks, target context, weekly observed volume, long-session evidence, target-distance comparison, specificity evidence, source counts and the 3 longest sessions under the method `season-observed-training-v1`, and the field `sessions_84_days` counts the 12 Monday-based weeks (78 to 84 days).

#### Scenario: Distance text
- **WHEN** the saved distance is read
- **THEN** a value with "km" is kilometres, a value ending in "m" or a bare number of at least 100 is metres, and anything else stays unknown.

Evidence: `backend/planning/season_preparation.py:season_preparation`, `backend/planning/season_preparation.py:_evidence_window`, `backend/planning/season_preparation.py:_target_context`, `backend/planning/season_preparation.py:_specificity_evidence`; `tests/test_season_preparation.py:test_competition_sport_matches_canonical_sport_and_indoor_environment`, `tests/test_season_preparation.py:test_numeric_race_distance_needs_reliable_meter_scale`, `tests/test_season_preparation.py:test_preparation_is_observed_and_does_not_follow_calendar_phase`, `tests/test_season_preparation.py:test_race_context_requires_confirmed_units_and_reports_known_dimensions`, `tests/test_season_preparation.py:test_no_history_unknown_distance_and_target_remain_nullable`, `tests/test_season_preparation.py:test_past_competition_window_is_anchored_at_event_date`, `tests/test_season_preparation.py:test_future_competition_evidence_covers_the_weeks_up_to_today`.

### Requirement: CS9 Competition-focused overview
The system SHALL present the planning segment as `Wettkämpfe`, with individually expandable, initially collapsed upcoming events ordered by date, priority and name. Each summary SHALL show saved name, date, sport, distance, personal A/B/C priority and athlete-local relative date without requiring training history.

#### Scenario: Upcoming competitions
- **WHEN** the athlete opens the competition overview with several saved upcoming events
- **THEN** all entries start collapsed in chronological order, today's events remain upcoming, and their summary facts are visible without expansion.

#### Scenario: Missing or unsupported facts
- **WHEN** distance is missing, sport has only local free-text detail, or a record has an invalid date
- **THEN** missing distance is shown as unknown rather than zero, local sport detail is preserved, and an undated record remains accessible separately without an invented date or countdown.

Evidence: `public/plan-views.js:renderCompetitions`, `public/plan-views.js:competitionCard`, `public/plan-views.js:competitionDistance`, `public/plan-views.js:competitionDate`; `tests/competition-overview.test.cjs` (distance and invalid-date tests); `e2e/competitions.spec.js` (summaries, ordering, past-only lists).

### Requirement: CS10 Saved event details and historical archive
The system SHALL reveal saved optional event details only on expansion, omit empty optional fields, and group past events in an initially collapsed archive ordered newest first. Expansion SHALL remain keyboard accessible and render untrusted event text safely.

#### Scenario: Expand an event
- **WHEN** the athlete expands a competition
- **THEN** its saved start time, target, expected duration, course profile, description and notes are shown where present, and other entries retain their expansion state.

#### Scenario: Historical and empty lists
- **WHEN** only past competitions exist or no competitions exist
- **THEN** the screen respectively offers the collapsed historical archive or a concise empty state without fabricated events or preparation metrics.

#### Scenario: Untrusted content
- **WHEN** event text contains markup or provider-supplied instructions
- **THEN** it is displayed as safe content and never executed or treated as authorization.

Evidence: `public/plan-views.js:competitionCard`, `public/plan-views.js:competitionFact`; `e2e/competitions.spec.js` (saved details, archive, safe text, empty lists); `e2e/text-reflow.spec.js`.

### Requirement: CS11 Overview excludes training analysis
The competition overview SHALL exclude date-derived training phases, weekly training volume/history, preparation evidence and long-session analysis. Reading the overview SHALL remain usable without activity analyses.

#### Scenario: Athlete checks competition dates
- **WHEN** the competition overview is loaded or an event is expanded
- **THEN** only competition facts and existing event-workflow access are presented, without weekly charts, evidence tables, or phase labels.

Evidence: `public/plan-views.js:renderCompetitions`; `public/shared.js` requests no season preparation on route entry; `e2e/competitions.spec.js` (no analysis request on mobile and desktop); `e2e/training-feature-panels.spec.js`.

### Requirement: CS12 Read state and competition authority
The overview SHALL preserve canonical local records, existing Coach editing and receipt/undo workflows, compact source/local-change indications and explicit synchronization authorization. Opening, expanding, archiving visually or refreshing the overview SHALL perform no durable mutation or provider write.

#### Scenario: Local changes await synchronization
- **WHEN** a local competition has unsynchronized edits
- **THEN** its current local values remain authoritative and the pending local state is visible without an automatic push.

#### Scenario: Load and refresh failure
- **WHEN** the initial read is pending or a refresh fails
- **THEN** the screen distinguishes loading from an empty list, retains available cached facts with a stale/error indication, and offers retry without claiming a successful refresh. Without stored data the texts are "Wettkämpfe werden geladen …" and "Wettkämpfe konnten nicht geladen werden." with "Erneut laden"; with stored data "Gespeicherter Stand wird aktualisiert …" and "Gespeicherter Stand. Aktualisierung fehlgeschlagen.".

#### Scenario: Return after a Coach edit
- **WHEN** an authorized Coach competition edit succeeds and the overview refreshes
- **THEN** the saved updated event appears with its stable identity and existing receipt/undo behavior, without an additional remote write.

Evidence: `public/state-loader.js` (canonical competition state), `public/app.js` (local retry), `public/plan-views.js:renderCompetitionReadStatus`, `backend/http_api/bootstrap_state.py` and `backend/http_api/athlete_get.py` (reads), `backend/planning/competition_service.py:CompetitionService.save` (local mutation authority); `e2e/competitions.spec.js` (no writes while reading, failed reads with retry, saved Coach edit shown).

Evidence limits for CS9–CS12: Coach-edit refresh is exercised using simulated canonical saved state rather than an end-to-end real-model mutation. Real-device microphone/notification permissions and keyboard-open behavior were not verified.

### Requirement: CS13 Completed races link to stored competitions
The system SHALL link each stored competition to the completed sessions of its local date and sport when it reads activity summaries, without storing the link, so consumers see which session was the race.

#### Scenario: Provider races are linked
- **WHEN** a session with purpose race starts on a competition's local date in its sport
- **THEN** the race nearest the competition's start carries that `competition_id`; other sessions of the day stay unlinked, and a day with a provider race never gets a hint.

#### Scenario: A competition marks its best candidate as a race hint
- **WHEN** no session of the competition's date and sport has purpose race
- **THEN** the session that starts nearest the competition's local start time (a stored midnight counts as unknown), else the longest, else the earliest, gets purpose race with source "Lokale Wettkämpfe" and the `competition_id`; with a planned duration it must last at least half of it.

#### Scenario: No link across sports or for commutes
- **WHEN** a session has another sport, another local date, the other side of indoor (indoor, virtual) versus outdoor when both are known, or purpose commute, warm-up or cool-down, or the competition's sport is unsupported
- **THEN** the session is not linked and keeps its own purpose.

#### Scenario: A past competition shows its race result
- **WHEN** the athlete opens the competition overview and a past competition has a linked session
- **THEN** its expanded details show "Ergebnis" with the session's elapsed time (else moving time), distance, average pace (rides: average power, else speed) and the link's source label, read on `GET /api/profile` in one read snapshot without any write; a competition without a linked session shows no result, today's competition shows only a provider race (never the date hint), and a failed result read keeps the profile response.

Detailed contract: a session links to at most one competition (competitions in date then id order). A limited read links over every session of its oldest day, so the hint never depends on the page size. The athlete unlinks a session by marking another purpose, training included, in its "Feedback" dialog (local, with receipt and undo, #1759); a marked training also takes the hint away from the other sessions of that day and sport.

Evidence: `backend/activities/session_purpose.py:with_competitions`, `backend/sync/canonical_read_selector.py:activity_summaries`, `backend/db/repositories.py:CompetitionRepository.between`, `backend/planning/race_results.py:with_race_results`, `backend/performance/activity_read_service.py:summaries_on_days`, `backend/http_api/athlete_get.py`, `public/plan-views.js:competitionResult`; `tests/test_session_purpose.py` (including `test_training_removes_the_race_hint`, `test_training_on_a_provider_race_drops_its_link`), `tests/test_race_results.py`, `tests/competition-overview.test.cjs`, `e2e/activity-details.spec.js::@responsive marking the session purpose sends it with a receipt whose undo restores the previous one`.
