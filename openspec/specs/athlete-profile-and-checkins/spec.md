# athlete-profile-and-checkins Specification

## Purpose

Describe durable athlete facts, local-day subjective feedback, completed-activity feedback and explicit equipment records, including validation, partial updates, optimistic conflicts and local provenance.

## Requirements

### Requirement: AP1 Normalized durable profile and athlete-local dates
The system SHALL persist the known profile fields with normalized bounded text, validate explicit timezone changes and sleep targets, and use the saved athlete timezone for local-day behavior.

#### Scenario: Valid profile facts
- **WHEN** the athlete saves known facts, sport-specific preferences, constraints, measurements, coaching style or location
- **THEN** known values are trimmed and bounded to 4000 characters per field, unknown fields are ignored, and the normalized local profile is returned.

#### Scenario: Invalid timezone or sleep target
- **WHEN** an explicit save supplies an invalid IANA timezone or a nonfinite/out-of-range sleep target outside 4 through 12 hours
- **THEN** the save is rejected before replacing the stored profile.

#### Scenario: Missing or malformed stored profile
- **WHEN** no valid profile JSON is stored
- **THEN** profile reads return the implemented defaults; a non-strict legacy invalid timezone falls back to Europe/Berlin rather than requiring an empty database.

Evidence: `backend/athlete/profile.py:normalize_profile`, `backend/athlete/profile.py:timezone_name`, `backend/athlete/profile.py:ProfileService.get_from_db`; `backend/athlete/clock.py:AthleteLocalClock`; `tests/test_athlete_profile.py:test_known_values_are_stringified_trimmed_and_limited`, `tests/test_athlete_profile.py:test_unknown_fields_are_ignored`, `tests/test_athlete_profile.py:test_timezone_name_raises_exact_strict_error`; `tests/test_athlete_profile_service.py:test_get_returns_default_for_missing_or_malformed_payload`; `tests/test_characterization_recovery.py:test_sleep_target_bounds_and_falsy_zero_target`.

### Requirement: AP2 Partial profile edits and optimistic Coach conflicts
The system SHALL preserve unsubmitted profile fields on the profile patch API and require exact expected field values for a Coach batch, with atomic rejection of stale or invalid batches.

#### Scenario: Profile patch
- **WHEN** `/api/profile` receives a valid partial update such as weight only
- **THEN** it merges against the profile read in the transaction and preserves saved names, preferences and other omitted fields.

#### Scenario: Coach partial update
- **WHEN** `update_profile` supplies distinct known fields with their current expected values and local-profile authority
- **THEN** only those fields change and the receipt identifies the fields stored locally.

#### Scenario: Later-field conflict
- **WHEN** any expected value differs, a field is unknown/duplicated, or operation/scope authorization is missing
- **THEN** the whole Coach batch is rejected without applying earlier fields.

Evidence: `backend/athlete/profile.py:ProfileService.patch`; `backend/http_api/athlete_put.py:AthletePutRoutes.handle`; `backend/coach/profile_update.py:CoachProfileUpdateService.apply`; `tests/test_athlete_profile_service.py:test_patch_with_only_weight_keeps_name_and_normalizes_changed_field`; `tests/test_coach_profile_update.py:test_valid_batch_saves_only_selected_fields`, `tests/test_coach_profile_update.py:test_later_field_conflict_aborts_entire_batch`, `tests/test_coach_profile_update.py:test_authorization_precedes_profile_read_and_write`.

### Requirement: AP3 Atomic complete athlete context and location invalidation
The system SHALL distinguish complete athlete-context replacement from a profile patch, save profile and the supplied complete competition set atomically, and invalidate location-derived weather state only when the saved location changes.

#### Scenario: Complete profile and competitions
- **WHEN** the athlete submits the complete athlete context
- **THEN** the profile and validated competition set are saved in one transaction, with omitted competitions treated as removals and existing remote identities retained as implemented.

#### Scenario: Failure after earlier writes
- **WHEN** a later competition upsert or profile validation fails
- **THEN** profile, prior upserts, removals and tombstones from that context save roll back together.

#### Scenario: Location unchanged or restored
- **WHEN** location stays the same
- **THEN** its weather cache is retained; changing or restoring a different location invokes the location-change invalidation hook and the profile audit record follows the save transaction.

Evidence: `backend/athlete/context.py:AthleteContextService.save`; `backend/athlete/profile.py:ProfileService.save_in_transaction`, `backend/athlete/profile.py:ProfileService.restore_in_transaction`; `tests/test_athlete_context.py:test_rolls_back_profile_tombstone_and_prior_upsert_after_later_failure`, `tests/test_athlete_context.py:test_profile_only_save_keeps_unchanged_competition_sync_state`; `tests/test_athlete_profile_service.py:test_same_location_keeps_weather_cache_and_skips_unchanged_history`, `tests/test_athlete_profile_service.py:test_restore_of_location_change_invokes_location_hook_and_clears_weather`.

### Requirement: AP4 Validated daily subjective check-ins
The system SHALL store a check-in for an explicit nonfuture calendar date or athlete-local today, validate score/minute bounds and bounded text, and expose today's and recent athlete-entered feedback separately from providers.

#### Scenario: Valid local check-in
- **WHEN** the athlete supplies daily form, illness, pain, availability, notes or scores
- **THEN** the date defaults to local today, scores normalize to integers from 0 through 10 or unknown, available minutes to 0 through 1440 or unknown, and bounded text is saved by date.

#### Scenario: Invalid date or values
- **WHEN** a future/invalid date, invalid score or invalid available-minute value is supplied
- **THEN** validation rejects the check-in instead of saving a partial row.

#### Scenario: Read today's feedback
- **WHEN** feedback context is requested
- **THEN** it includes today's matching row or null and at most fourteen recent rows from the bounded local list, with an athlete-entered scope label.

Evidence: `backend/athlete/checkins.py:normalize_checkin`, `backend/athlete/checkins.py:CheckinService.save`, `backend/athlete/checkins.py:CheckinService.context`; `tests/test_athlete_checkins.py:test_normalize_checkin_defaults_date_and_normalizes_values`, `tests/test_athlete_checkins.py:test_normalize_checkin_rejects_invalid_and_future_dates`, `tests/test_athlete_checkins.py:test_bounded_score_rejects_non_integer_and_out_of_range_values`, `tests/test_athlete_checkins.py:test_context_limits_recent_and_uses_today`.

### Requirement: AP5 Coach check-in merging and explicit clearing
The system SHALL preserve existing daily scores/text/minutes when Coach updates omit or leave them empty, and SHALL clear only fields explicitly listed in a validated nonconflicting clear-fields list.

#### Scenario: Partial correction
- **WHEN** `save_checkin` changes one field while others are omitted, empty or use the supported unknown sentinel
- **THEN** existing preserved fields remain stored for that date and the result identifies local storage.

#### Scenario: Explicit clear
- **WHEN** the athlete asks to remove listed supported fields and the Coach supplies valid unique clear-fields names
- **THEN** only those listed values are cleared while other saved fields remain.

#### Scenario: Contradictory clear
- **WHEN** a clear field also supplies a nonempty value, or names are unknown, duplicated or malformed
- **THEN** the update is rejected without silently erasing unrelated feedback.

Evidence: `backend/athlete/checkins.py:coach_clear_fields`, `backend/athlete/checkins.py:CheckinService.save_coach`; `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService.execute`; `tests/test_athlete_checkins.py:test_save_coach_merges_omitted_and_minus_one_values`, `tests/test_athlete_checkins.py:test_save_coach_clear_fields_removes_listed_values_and_keeps_omitted`, `tests/test_athlete_checkins.py:test_save_coach_rejects_clear_field_that_also_has_value`, `tests/test_athlete_checkins.py:test_save_coach_rejects_invalid_clear_fields`.

### Requirement: AP6 Explicit day status, tags and durable check-in saves
The system SHALL preserve unknown versus confirmed day status and yes/no tags, commit check-in state before returning its follow-up read, and preserve a committed save if that later read fails.

#### Scenario: Confirmed rest or pause and tags
- **WHEN** a check-in supplies day_status as unknown/rest/pause and known travel, late-meal or high-stress boolean answers
- **THEN** the system persists those values; omission preserves separately saved status/tags, and a supplied tag object replaces that day's tag answers.

#### Scenario: Unconfirmed tag value
- **WHEN** a supplied tag is unknown or has a nonboolean answer
- **THEN** it is rejected rather than interpreted as false or inferred from illness or missing activity data.

#### Scenario: Storage failure versus read failure
- **WHEN** the upsert fails
- **THEN** the transaction rolls back; if the save commits but its follow-up list fails, the committed check-in remains available for a later read.

Evidence: `backend/athlete/checkins.py:normalize_checkin`, `backend/athlete/checkins.py:CheckinService._save_normalized`, `backend/athlete/checkins.py:CheckinService.list`; `tests/test_training_record_features.py:test_checkin_rejects_non_boolean_and_unknown_tag_answers`; `tests/test_athlete_checkins.py:test_save_upserts_and_returns_saved_row`, `tests/test_athlete_checkins.py:test_save_rolls_back_failed_upsert`, `tests/test_athlete_checkins.py:test_save_preserves_committed_upsert_when_followup_read_fails`. The requirement describes persisted tri-state data; universal semantic enforcement of athlete confirmation is not claimed.

### Requirement: AP7 Exact completed-activity feedback
The system SHALL save subjective notes, optional finite session RPE from 0 through 10 and bounded deviation reasons against a resolved existing activity, preserving omitted fields and keeping feedback separate from daily/provider records.

#### Scenario: Existing activity and partial edit
- **WHEN** the Coach saves nonempty feedback for a known canonical activity by local or provider ID
- **THEN** it resolves the activity reference, stores local feedback, preserves omitted fields and attaches that feedback to activity reads.

#### Scenario: Empty, unknown or invalid feedback
- **WHEN** the Coach submits empty observations, an activity absent from canonical reads, or invalid/nonfinite/out-of-range RPE
- **THEN** the save fails rather than creating a completed activity or inventing feedback.

#### Scenario: Explicit removal
- **WHEN** the authorized delete-feedback tool clears notes, RPE and deviation reason for an activity
- **THEN** the local feedback row is removed without deleting the activity or altering provider feedback.

Evidence: `backend/activities/feedback.py:normalize_activity_feedback`, `backend/activities/feedback.py:ActivityFeedbackService.save_coach`, `backend/activities/feedback.py:ActivityFeedbackService._save`, `backend/activities/feedback.py:ActivityFeedbackService.attach_to_activities`; `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService.execute`; `tests/test_activity_feedback.py:test_rpe_only_preserves_notes_and_explicit_clear_deletes`, `tests/test_activity_feedback.py:test_coach_save_requires_known_snapshot_activity_and_accepts_aliases`, `tests/test_activity_feedback.py:test_attach_finds_feedback_older_than_the_newest_500_rows`; `tests/test_coach_tool_coverage.py:test_daily_feedback_and_activity_feedback_are_separate_from_profile`.

### Requirement: AP8 Versioned local equipment records
The system SHALL save explicitly entered main equipment/components with validated sport, parent, start date, initial usage and personal service/lifetime intervals, preserving historical references on archival and rejecting stale revisions.

#### Scenario: Create or update equipment
- **WHEN** a valid equipment record is created or edited with its current exact revision
- **THEN** local data is persisted with an incremented revision and source label; linked Garmin identity metadata is preserved by the implemented update policy.

#### Scenario: Missing sport/parent or stale edit
- **WHEN** an item is marked sport-pending or parent-pending, or an edit uses an obsolete revision
- **THEN** unresolved details remain visible for athlete clarification, invalid assignment is blocked and a stale edit returns a conflict rather than overwriting newer state.

#### Scenario: One-time Garmin initialization
- **WHEN** a current nonempty Garmin inventory is first available
- **THEN** supported gear is imported once; later syncs refresh Garmin-owned mileage rather than overwriting athlete-owned fields, while an empty initial inventory leaves import recoverable.

Evidence: `backend/athlete/equipment.py:EquipmentService.save`, `backend/athlete/equipment.py:EquipmentService.sync_garmin_snapshot`; `backend/coach/tool_schemas.py:build_structured_tool_schemas` (equipment fields); `tests/test_coach_tool_coverage.py:test_training_records_and_equipment_tools_use_confirmed_local_state`; `tests/test_training_record_features.py:test_empty_initial_gear_snapshot_does_not_finalize_import`, `tests/test_training_record_features.py:test_legacy_empty_import_recovers_once_and_preserves_local_equipment`; `tests/test_coach_write_gate.py:test_archiving_equipment_is_a_delete`.

### Requirement: AP9 Explicit equipment assignments and honest usage
The system SHALL assign only resolved canonical completed activities to compatible active main equipment, allow explicit unassignment, and calculate usage from known assignments and supported Garmin links with coverage metadata.

#### Scenario: Assign or reassign
- **WHEN** the athlete explicitly assigns an existing activity to compatible active main equipment
- **THEN** the local assignment is saved and both old and new equipment usage reflect the current assignment; unknown/component/archived/incompatible equipment is rejected.

#### Scenario: Explicit assignment beats provider link
- **WHEN** Garmin links an activity to gear but a local assignment or unassignment exists
- **THEN** the explicit local decision takes precedence without inferring a favorite bicycle or shoe.

#### Scenario: Bounded lists and incomplete history
- **WHEN** assignment display exceeds its list bound or provider history is incomplete/stale
- **THEN** usage still counts eligible known assignments, the list avoids splitting one activity's gear and incomplete coverage remains explicit.

Evidence: `backend/athlete/equipment.py:EquipmentService.assign`, `backend/athlete/equipment.py:EquipmentService.read`, `backend/athlete/equipment.py:_effective_assignments`, `backend/athlete/equipment.py:_assignment_list`; `tests/test_training_record_features.py:test_equipment_assignment_is_explicit_and_unassignable`, `tests/test_training_record_features.py:test_explicit_assignment_and_unassignment_beat_the_garmin_link`, `tests/test_training_record_features.py:test_assignment_list_limit_keeps_activities_whole`, `tests/test_training_record_features.py:test_assignment_list_is_bounded_but_usage_counts_every_link`; `tests/test_activity_reference.py:test_equipment_assignment_resolves_the_reference_at_the_boundary`.

### Requirement: AP10 Maintenance events without invented material diagnosis
The system SHALL record explicitly completed equipment maintenance within the item's valid date range, preserve lifetime usage/history, and report personal interval progress with unknown or partial measurements honestly.

#### Scenario: Valid maintenance
- **WHEN** the athlete records maintenance for an existing item from its start date through local today
- **THEN** the event is persisted with bounded notes and the applicable known usage snapshot, without resetting lifetime usage or deleting earlier events.

#### Scenario: Invalid maintenance date
- **WHEN** the item is missing, the date precedes its start, or the date is in the future
- **THEN** no maintenance event is saved.

#### Scenario: Same-day or incomplete ordering
- **WHEN** a service interval depends on session history with same-day ordering unknown or a stale/truncated Garmin activity list
- **THEN** maintenance counters use the implemented later-calendar-day rule and mark incomplete coverage rather than diagnosing wear or replacement need.

Evidence: `backend/athlete/equipment.py:EquipmentService.maintain`, `backend/athlete/equipment.py:_maintenance_usage`, `backend/athlete/equipment.py:_lifetime_projection`; `tests/test_training_record_features.py:test_garmin_linked_sessions_feed_maintenance_usage`, `tests/test_training_record_features.py:test_truncated_or_stale_garmin_list_makes_session_maintenance_partial`; `tests/test_coach_tool_coverage.py:test_training_records_and_equipment_tools_use_confirmed_local_state`; `tests/test_equipment_post_route.py:test_maintenance_post_delegates_to_equipment_service`.

### Requirement: Authoritative local zone edits and undo
The athlete SHALL be able to read and explicitly edit local sport-specific zones and thresholds through the supported application contract. Saves SHALL validate units and ascending boundaries, preserve provider alternatives and record change history with undo. Confirmed local configuration SHALL remain authoritative across provider refresh, restart and backup/restore.

#### Scenario: Valid local edit
- **WHEN** an authenticated athlete saves valid local zone boundaries for a sport and metric
- **THEN** effective calendar/plan configuration uses those boundaries, the provider alternative remains separately visible and the save produces an undoable receipt.

#### Scenario: Invalid boundaries
- **WHEN** a save contains nonfinite, incompatible-unit or nonascending boundaries
- **THEN** the whole edit fails without partially modifying existing zones or history.

#### Scenario: Undo after provider refresh
- **WHEN** a saved local zone edit is undone after a provider refresh
- **THEN** the previous local state is restored and effective selection follows local authority or the applicable provider alternative when no local configuration remains.

Evidence baseline: `backend/activities/zone_settings.py`, `backend/change_history.py`, `backend/athlete/profile.py`; `tests/test_zone_settings.py`. Local canonical zone editing and its receipt/undo paths require new implementation and tests.
