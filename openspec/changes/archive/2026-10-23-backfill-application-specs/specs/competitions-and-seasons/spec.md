## Purpose

Describe local target competitions, their explicit synchronization/conflict boundary, season phase projection, observed preparation evidence and nonmutating load scenarios. Provider transport details belong to provider synchronization capabilities.

## ADDED Requirements

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

Evidence: `backend/planning/competitions.py:normalize_competition`, `backend/planning/competitions.py:competition_start`, `backend/planning/competitions.py:competition_distance`, `backend/planning/competitions.py:competition_stored_sport`, `backend/planning/competitions.py:competition_event_optional_payload`; `tests/test_planning_competitions.py:test_normalize_preserves_existing_contract`, `tests/test_planning_competitions.py:test_validation_rejects_missing_identity_and_invalid_bounds`, `tests/test_planning_competitions.py:test_sport_aliases_and_intervals_fallbacks`, `tests/test_planning_competitions.py:test_external_id_and_optional_payload_preserve_types_and_input`.

### Requirement: CS2 Local competition create and partial edit
The system SHALL create or edit one local competition with stable identity, preserve omitted Coach edit fields, enforce the twenty-event creation bound, and audit the mutation in its transaction without an implicit remote push.

#### Scenario: New local competition
- **WHEN** an authorized `save_competition` creates a valid target event without an existing ID
- **THEN** the record is stored locally and returned with the current competition list; no Intervals.icu push is performed by saving it.

#### Scenario: Partial edit
- **WHEN** the Coach resolves an existing competition ID and changes selected fields
- **THEN** the existing identity and omitted required/optional details are preserved under the implemented merge policy and the edit is audited.

#### Scenario: Missing identity, capacity or history failure
- **WHEN** an edit ID is malformed/missing in storage, a new event exceeds twenty, or audit persistence fails
- **THEN** the request fails without creating a substitute event or committing an unaudited partial save.

Evidence: `backend/planning/competition_service.py:CompetitionService.save`, `backend/planning/competition_service.py:_coach_payload`, `backend/planning/competition_service.py:_merge_update`; `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService.execute`; `tests/test_planning_competition_service.py:test_create_and_partial_update_share_one_transaction_with_history`, `tests/test_planning_competition_service.py:test_failed_history_write_rolls_back_competition`; `tests/test_coach_tool_coverage.py:test_competition_lifecycle_syncs_only_after_explicit_followup`; `tests/test_coach_dialogue.py:test_competition_edit_uses_resolved_id_without_literal_name`.

### Requirement: CS3 Complete competition-set save and unchanged round trips
The system SHALL save a complete athlete-context competition set atomically, reject duplicate normalized IDs, preserve stored remote identities, and leave unchanged competition sync state intact.

#### Scenario: Profile-only context round trip
- **WHEN** the complete competition list is resubmitted unchanged while profile fields change
- **THEN** competition rows retain their existing synced/conflict state rather than becoming dirty solely because of the round trip.

#### Scenario: Changed or removed competition
- **WHEN** a complete context changes an event or omits an existing event
- **THEN** changed records become local dirty state and removed linked records retain the corresponding remote-deletion tombstones, all in the profile/context transaction.

#### Scenario: Invalid complete set
- **WHEN** the list is not an array, exceeds twenty, duplicates normalized IDs or a later write fails
- **THEN** no partial profile, competition or tombstone changes from that context save remain.

Evidence: `backend/athlete/context.py:AthleteContextService.save`, `backend/athlete/context.py:AthleteContextService._competition_unchanged`; `tests/test_athlete_context.py:test_rejects_duplicate_normalized_ids`, `tests/test_athlete_context.py:test_profile_only_save_keeps_unchanged_competition_sync_state`, `tests/test_athlete_context.py:test_changed_competition_marks_dirty_and_clears_conflict`, `tests/test_athlete_context.py:test_unchanged_round_trip_of_listed_competitions_is_not_a_change`, `tests/test_athlete_context.py:test_rolls_back_profile_tombstone_and_prior_upsert_after_later_failure`.

### Requirement: CS4 Competition removal and remote tombstone retention
The system SHALL delete a locally selected competition under the applicable authorization, unlink any public-event candidate, and retain remote deletion intent for linked records until an authorized remote sync succeeds.

#### Scenario: Delete linked competition
- **WHEN** an authorized local delete targets an existing linked competition
- **THEN** local removal, candidate unlink and history are committed together, a tombstone preserves remote IDs and the result reports remote sync pending.

#### Scenario: Unlinked or missing competition
- **WHEN** an unlinked event is deleted or the requested ID does not exist
- **THEN** an unlinked delete needs no remote tombstone, while a missing ID reports not-found without removing other events.

#### Scenario: Read sync or failed remote delete
- **WHEN** a provider read refresh occurs or a requested remote deletion fails
- **THEN** it does not consume the local deletion intent as if remote deletion succeeded.

Evidence: `backend/planning/competition_service.py:CompetitionService.delete`; `backend/athlete/context.py:AthleteContextService._record_removed_competition_tombstones`; `backend/sync/competitions.py:CompetitionSyncReconciler.clear_tombstones`; `tests/test_planning_competition_service.py:test_delete_creates_remote_tombstone_and_unlinks_public_candidate`; `tests/test_sync_competitions.py:test_read_only_sync_never_deletes_or_upserts_and_keeps_tombstones`, `tests/test_sync_competitions.py:test_failed_remote_delete_does_not_clear_tombstones_or_upsert`.

### Requirement: CS5 Explicit competition sync and conflict recovery
The system SHALL keep remote pushes explicit, detect unsafe remote identity/missing-record cases, validate approval freshness, and offer deliberate keep-local/adopt-remote conflict resolution.

#### Scenario: Read reconciliation
- **WHEN** the existing competition sync runs without push authority
- **THEN** it may reconcile/import supported clean remote records under its current policy, but never delete or upsert remote events or consume tombstones.

#### Scenario: Named approved push
- **WHEN** the athlete explicitly requests competition synchronization and approves its frozen manifest
- **THEN** outbound writes use stable identity and supported sport payloads, with concurrent local edits checked before marking captured records synced.

#### Scenario: Conflict choice
- **WHEN** a stored conflict is resolved as keep_local or adopt_remote
- **THEN** keep-local retains a local override for a later explicit push, while adopt-remote requires a valid remote event and updates the local record; invalid strategy, corrupt/missing conflict or unavailable remote data fails explicitly.

Evidence: `backend/planning/competition_service.py:CompetitionService.resolve_conflict`; `backend/planning/competitions.py:competition_remote_match`, `backend/planning/competitions.py:competition_conflict_action`; `backend/sync/competitions.py:CompetitionSyncReconciler`; `tests/test_planning_competition_service.py:test_conflict_resolution_preserves_both_strategies`; `tests/test_sync_competitions.py:test_records_rejects_competition_changes_after_approval`, `tests/test_sync_competitions.py:test_dirty_remote_deviations_persist_identity_changed_and_missing_conflicts`, `tests/test_sync_competitions.py:test_optimistic_check_skips_competition_edited_after_capture`, `tests/test_sync_competitions.py:test_synced_local_row_is_updated_from_remote`.

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

Evidence: `backend/planning/season_preparation.py:season_preparation`, `backend/planning/season_preparation.py:_evidence_window`, `backend/planning/season_preparation.py:_target_context`, `backend/planning/season_preparation.py:_specificity_evidence`; `tests/test_season_preparation.py:test_preparation_is_observed_and_does_not_follow_calendar_phase`, `tests/test_season_preparation.py:test_race_context_requires_confirmed_units_and_reports_known_dimensions`, `tests/test_season_preparation.py:test_no_history_unknown_distance_and_target_remain_nullable`, `tests/test_season_preparation.py:test_past_competition_window_is_anchored_at_event_date`, `tests/test_season_preparation.py:test_future_competition_evidence_covers_the_weeks_up_to_today`.

### Requirement: CS8 Read-only load scenarios with labeled estimates
The system SHALL provide deterministic current/alternative load curves from the dated canonical CTL/ATL basis and known completed/planned load, expose model assumptions and input identity, and leave local/remote workouts unchanged.

#### Scenario: Valid current and alternative scenarios
- **WHEN** yesterday's CTL/ATL and all required loads are known with valid scale/taper/end parameters
- **THEN** the system returns reproducible curves and an input hash, labels the local 42-day/7-day model assumptions, keeps today's completed load fixed and avoids double-counting completed planned sessions.

#### Scenario: Estimated planned load
- **WHEN** a future unit lacks recorded load but has usable duration and intensity
- **THEN** its duration/intensity load estimate is explicitly labeled; recorded load takes precedence over estimates.

#### Scenario: Missing basis, missing load or invalid parameters
- **WHEN** CTL/ATL or a required load is unknown, or parameters are invalid
- **THEN** the response reports insufficient-data with missing units, or rejects invalid parameters; it does not fabricate provider settings, race-time predictions or an applied replan.

Evidence: `backend/planning/season_preparation.py:load_scenarios`, `backend/planning/season_preparation.py:_scenario_values`, `backend/planning/season_preparation.py:_planned_loads`, `backend/planning/season_preparation.py:_estimated_load`; `tests/test_season_preparation.py:test_scenarios_are_deterministic_nonmutating_and_taper_changes_load`, `tests/test_season_preparation.py:test_missing_basis_or_planned_load_is_not_zero_filled`, `tests/test_season_preparation.py:test_completed_today_load_is_fixed_and_not_double_counted_or_scaled`, `tests/test_season_preparation.py:test_planned_load_is_estimated_from_duration_and_intensity`, `tests/test_season_preparation.py:test_recorded_planned_load_wins_over_estimate`, `tests/test_season_preparation.py:test_load_scale_accepts_german_decimal_comma`.
