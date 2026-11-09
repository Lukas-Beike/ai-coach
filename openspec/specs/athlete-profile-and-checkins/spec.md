# athlete-profile-and-checkins Specification

## Purpose

Describe durable athlete facts, local-day subjective feedback, completed-activity feedback and explicit equipment records, including validation, partial updates, optimistic conflicts and local provenance.

## Requirements

### Requirement: AP1 Normalized durable profile and athlete-local dates
The system SHALL persist the known profile fields with normalized bounded text, validate explicit timezone changes, sleep targets and the training model, and use the saved athlete timezone for local-day behavior.

#### Scenario: Valid profile facts
- **WHEN** the athlete saves known facts, sport-specific preferences, the training model, constraints, measurements, coaching style or location
- **THEN** known values are trimmed and bounded to 4000 characters per field, unknown fields are ignored, and the normalized local profile is returned.

#### Scenario: Invalid timezone or sleep target
- **WHEN** an explicit save supplies an invalid IANA timezone, a nonfinite/out-of-range sleep target outside 4 through 12 hours, or a training model other than pyramidal, polarized, threshold or sweet_spot
- **THEN** the save is rejected before replacing the stored profile.

#### Scenario: Sex and preferred sources
- **WHEN** the athlete saves `sex` (male, female or empty) or a preferred source for thresholds, body, HRV, resting heart rate or sleep (Garmin or empty for automatic)
- **THEN** an explicit save rejects any other value and a non-strict read clears it; changing the sex, a preferred source or the timezone requests a recomputation of the stored local load, and an unset sex makes the heart-rate load use the male TRIMP constants and mark the value as assumed.

#### Scenario: Missing or malformed stored profile
- **WHEN** no valid profile JSON is stored
- **THEN** profile reads return the implemented defaults, including the pyramidal training model; a non-strict legacy invalid timezone falls back to Europe/Berlin rather than requiring an empty database.

#### Scenario: Retired weekly plan
- **WHEN** a stored profile, or a database restored from an older backup, still carries the retired `weekly_plan` field
- **THEN** profile reads and saves ignore it, and a one-time versioned stage of the canonical backfill worker deletes that one key from the stored profile (status only in diagnostics); a restored older backup runs the stage again.

Evidence: `backend/athlete/profile.py:normalize_profile`, `backend/athlete/profile.py:timezone_name`, `backend/athlete/profile.py:_normalize_sex`, `backend/athlete/profile.py:_normalize_preferred_sources`, `backend/performance/local_tss.py:trimp_sex`, `backend/athlete/profile.py:ProfileService.get_from_db`; `backend/sync/profile_weekly_plan_removal.py`; `tests/test_profile_weekly_plan_removal.py`; `backend/athlete/clock.py:AthleteLocalClock`; `tests/test_athlete_profile.py:test_known_values_are_stringified_trimmed_and_limited`, `tests/test_athlete_profile.py:test_unknown_fields_are_ignored`, `tests/test_athlete_profile.py:test_timezone_name_raises_exact_strict_error`, `tests/test_athlete_profile.py:test_training_model_defaults_and_rejects_unknown_only_when_strict`, `tests/test_athlete_profile.py:test_sex_is_male_female_or_unset_and_rejects_unknown_only_when_strict`, `tests/test_athlete_profile.py:test_preferred_sources_accept_known_providers_only`, `tests/test_local_tss.py:test_unknown_sex_takes_the_assumed_male_constants`; `tests/test_athlete_profile_service.py:test_get_returns_default_for_missing_or_malformed_payload`; `tests/test_characterization_recovery.py:test_sleep_target_bounds_and_falsy_zero_target`.

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

#### Scenario: Check-in score direction
- **WHEN** check-in scores reach the Coach
- **THEN** soreness and stress read 0–10 with higher worse, motivation 0–10 with higher better and session RPE 0–10 with higher harder, labelled as the local check-in scale and never mixed with a provider rating on another scale.

Evidence: `backend/athlete/checkins.py:normalize_checkin`, `backend/athlete/checkins.py:CheckinService.save`, `backend/athlete/checkins.py:CheckinService.context`; `tests/test_athlete_checkins.py:test_normalize_checkin_defaults_date_and_normalizes_values`, `tests/test_athlete_checkins.py:test_normalize_checkin_rejects_invalid_and_future_dates`, `tests/test_athlete_checkins.py:test_bounded_score_rejects_non_integer_and_out_of_range_values`, `tests/test_athlete_checkins.py:test_context_limits_recent_and_uses_today`; `backend/canonical/rating_scales.py:LOCAL_CHECKIN_SCALES`, `backend/coach/prompt.py` (rating-scale rule).

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
The system SHALL save subjective notes, optional finite session RPE from 0 through 10 and bounded deviation reasons against a resolved existing activity, preserving omitted fields and keeping feedback separate from daily/provider records. An activity exists when its local session id, or the provider activity id of an active record of any provider, leads to a live canonical session.

#### Scenario: Existing activity and partial edit
- **WHEN** the Coach or the detail view saves nonempty feedback for a live canonical session by local or provider ID, including a Garmin- or Wahoo-only session
- **THEN** it resolves the activity reference, stores local feedback, preserves omitted fields and attaches that feedback to activity reads.

#### Scenario: Empty, unknown or invalid feedback
- **WHEN** the Coach submits empty observations, an id that leads to no live canonical session, or invalid/nonfinite/out-of-range RPE
- **THEN** the save fails rather than creating a completed activity or inventing feedback.

#### Scenario: Explicit removal
- **WHEN** the authorized delete-feedback tool clears notes, RPE and deviation reason for an activity
- **THEN** the local feedback row is removed without deleting the activity or altering provider feedback.

Evidence: `backend/activities/feedback.py:normalize_activity_feedback`, `backend/activities/feedback.py:ActivityFeedbackService.save_coach`, `backend/db/canonical_store.py:live_session_id`, `backend/activities/feedback.py:ActivityFeedbackService._save`, `backend/activities/feedback.py:ActivityFeedbackService.attach_to_activities`; `backend/coach/athlete_record_tools.py:CoachAthleteRecordToolService.execute`; `tests/test_activity_feedback.py:test_rpe_only_preserves_notes_and_explicit_clear_deletes`, `tests/test_activity_feedback.py:test_coach_save_requires_a_live_canonical_session`, `tests/test_activity_feedback.py:test_attach_finds_feedback_older_than_the_newest_500_rows`; `tests/test_coach_tool_coverage.py:test_daily_feedback_and_activity_feedback_are_separate_from_profile`.

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

### Requirement: Estimated first threshold from chest-strap RR intervals
The system SHALL show an estimated first threshold heart rate, derived from stored chest-strap RR results, as an estimate and SHALL store it only when the athlete explicitly adopts it. The Coach SHALL have no tool that adopts it.

#### Scenario: Athlete-level estimate
- **WHEN** at least three good-quality run sessions of the last 60 days hold a DFA-a1 result
- **THEN** the profile shows the median of their values, each as percent of the run threshold HR in effect on its day, with quality, session count and date range, and the Coach sees it in its performance context labelled a research-grade estimate.

#### Scenario: Adopt the estimate
- **WHEN** the athlete adopts the shown estimate
- **THEN** the profile stores the percent with the origin `estimated` as one change with receipt and undo; an estimate that changed since it was shown, or a missing one, is refused, and a measured value is replaced only when the request says so.

Evidence: `backend/performance/first_threshold_estimate.py:first_threshold_estimate`, `backend/athlete/first_threshold.py:FirstThresholdService`; `tests/test_first_threshold_estimate.py`.

### Requirement: Recorded sensors linked to equipment
The system SHALL list the distinct heart rate, power meter and trainer sensors named by recordings, each with its hashed short id, role, manufacturer, product, first and last day and session count, and SHALL let the athlete link a sensor to an active main equipment item or remove the link. A serial number SHALL never be stored or shown.

#### Scenario: Link a sensor
- **WHEN** the athlete links a listed sensor to an active main equipment item
- **THEN** the registry shows that equipment id for the sensor; an unknown sensor or an archived, component or unknown item is rejected, and a null equipment id removes the link.

Evidence: `backend/athlete/equipment.py:EquipmentService.assign_sensor`, `backend/canonical/sensor_registry.py:registry`; `tests/test_sensor_equipment.py`.

### Requirement: AP9 Explicit equipment assignments and honest usage
The system SHALL assign only resolved canonical completed activities to compatible active main equipment, allow explicit unassignment, and calculate usage from known assignments and supported Garmin links with coverage metadata. Usage, hours, distance, maintenance and sport derivation SHALL read canonical session summaries, so each session counts once whichever providers recorded it.

#### Scenario: Assign or reassign
- **WHEN** the athlete explicitly assigns an existing activity to compatible active main equipment
- **THEN** the local assignment is saved and both old and new equipment usage reflect the current assignment; unknown/component/archived/incompatible equipment is rejected.

#### Scenario: Explicit assignment beats provider link
- **WHEN** Garmin links an activity to gear but a local assignment or unassignment exists
- **THEN** the explicit local decision takes precedence without inferring a favorite bicycle or shoe.

#### Scenario: Bounded lists and incomplete history
- **WHEN** assignment display exceeds its list bound or provider history is incomplete/stale
- **THEN** usage still counts eligible known assignments, the list avoids splitting one activity's gear and incomplete coverage remains explicit.

#### Scenario: Sessions from any provider
- **WHEN** a Garmin- or Wahoo-only session is assigned or linked by a Garmin gear item, and a session bundled from several providers is assigned
- **THEN** each counts once in usage, hours, distance and maintenance; a new assignment is stored under the session it was made for, and an earlier assignment stored under a provider record id or an alias session id still applies (the session-id assignment wins over it, else the newest).

Evidence: `backend/athlete/equipment.py:EquipmentService.assign`, `backend/athlete/equipment.py:EquipmentService.read`, `backend/athlete/equipment.py:_effective_assignments`, `backend/athlete/equipment.py:_assignment_list`; `tests/test_training_record_features.py:test_equipment_assignment_is_explicit_and_unassignable`, `tests/test_training_record_features.py:test_explicit_assignment_and_unassignment_beat_the_garmin_link`, `tests/test_training_record_features.py:test_assignment_list_limit_keeps_activities_whole`, `tests/test_training_record_features.py:test_assignment_list_is_bounded_but_usage_counts_every_link`; `tests/test_equipment_canonical_sessions.py:test_wahoo_only_session_counts_in_usage_hours_distance_and_maintenance`, `tests/test_equipment_canonical_sessions.py:test_garmin_gear_links_the_garmin_only_session_and_the_bundled_one`, `tests/test_equipment_canonical_sessions.py:test_bundled_session_counts_once_under_its_session_id`, `tests/test_equipment_canonical_sessions.py:test_assignment_stored_under_an_intervals_id_still_applies`, `tests/test_equipment_canonical_sessions.py:test_an_assignment_under_the_session_id_wins_over_a_legacy_one`, `tests/test_equipment_canonical_sessions.py:test_an_assignment_under_an_alias_session_id_applies_and_newest_wins`; `backend/athlete/equipment.py:_session_assignments`.

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
The athlete SHALL be able to read and explicitly edit local zones and thresholds for riding, running and swimming (power, heart rate or pace) through Profil → Zonen & Schwellen. Saves SHALL validate units, three to seven ascending boundaries and the required threshold, preserve provider alternatives and record change history with undo. Confirmed local configuration SHALL remain authoritative across provider refresh and restart.

#### Scenario: Valid local edit
- **WHEN** an authenticated athlete saves valid local zone boundaries for a sport and metric
- **THEN** effective calendar/plan configuration uses those boundaries, the provider alternative remains separately visible and the save produces an undoable receipt.

#### Scenario: Invalid boundaries
- **WHEN** a save contains nonfinite, incompatible-unit or nonascending boundaries
- **THEN** the whole edit fails without partially modifying existing zones or history.

#### Scenario: Removal needs confirmation
- **WHEN** the athlete removes local zones
- **THEN** the request is rejected unless it carries an explicit confirmation, the provider zones apply again afterwards, and the removal produces an undoable receipt.

#### Scenario: Stale threshold warning
- **WHEN** an active FTP, lactate-threshold heart rate or threshold pace is older than 56 days, is past its source's age limit, comes from Garmin while the unofficial Garmin SDK is failing, or a locally saved indoor FTP is older than 56 days
- **THEN** the zone view lists one line per threshold with its value, source and age (or the reason it is no longer used), asks to save new values locally, and opens the section; fresh thresholds, an undated local value, and indoor rides without a saved indoor FTP (they use the cycling FTP) produce no warning, and no value is estimated.

#### Scenario: Undo after provider refresh
- **WHEN** a saved local zone edit is undone after a provider refresh
- **THEN** the previous local state is restored and effective selection follows local authority or the applicable provider alternative when no local configuration remains.

Evidence: `backend/athlete/zones.py:ZoneConfigurationService.save`, `backend/athlete/zones.py:ZoneConfigurationService.remove`, `backend/athlete/zones.py:ZoneConfigurationService.restore_in_transaction`, `backend/athlete/zones.py:local_configuration`, `backend/http_api/athlete_put.py:AthletePutRoutes._handle_zones`, `backend/activities/zone_settings.py`, `backend/performance/threshold_staleness.py`, `public/settings.js::saveZones`, `public/settings.js::removeZones`, `public/settings.js::zoneWarningLine`; `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_save_keeps_provider_alternatives_and_survives_a_refresh`, `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_undo_restores_the_previous_local_state_after_a_refresh`, `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_removal_needs_confirmation_and_can_be_undone`, `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_an_invalid_edit_changes_nothing`, `tests/test_threshold_staleness.py:AssessTests.test_stale_threshold_names_value_source_and_age`, `tests/test_threshold_staleness.py:AssessTests.test_indoor_ftp_is_judged_only_when_the_athlete_set_one`, `tests/test_threshold_staleness.py:ServiceTests.test_indoor_rides_use_the_ride_ftp_without_a_warning`, `tests/zone-warnings.test.cjs`, `tests/test_zone_settings.py`. Backup/restore of local zones has no dedicated test.
