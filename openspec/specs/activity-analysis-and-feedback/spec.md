# activity-analysis-and-feedback Specification

## Purpose

Record local completed-session detail, evidence-based analysis, planned-versus-completed matching, and athlete feedback. This backfill describes inspected implementation; mocked unit evidence does not establish live-provider or browser conformance.

## Requirements

### Requirement: Provider-neutral session detail document
The system SHALL assemble an `activity_detail.v1` document for a canonical session with session identity, metrics, streams, laps, zones, analysis, feedback/equipment envelope, and per-provider detail state, and SHALL serve it as the only session detail contract of the HTTP detail route, the Coach `get_activity_details` tool, and the PWA detail views. Measured metrics SHALL prefer the recorder's own copy and preserve alternatives. Missing values SHALL remain absent rather than becoming zeros.

#### Scenario: Several provider copies
- **WHEN** a session has both a recorder's original activity and a relayed copy
- **THEN** measured scalar values prefer the original and alternative values retain their source metadata.

#### Scenario: Detail unavailable
- **WHEN** no streams or a particular measured metric exist
- **THEN** the document remains valid with explicit available coverage and absent unsupported sections/metrics; a missing source does not become a zero measurement.

#### Scenario: One served contract
- **WHEN** an authenticated client reads `GET /api/activities/<id>` or the Coach calls `get_activity_details` for a known session
- **THEN** the body is the `activity_detail.v1` document with `contract`, `session`, `metrics`, `streams`, `laps`, `zones`, `analysis`, `detail_data` and the envelope keys `activity_feedback` and `equipment`. The legacy keys `activity`, `session_analysis` and `local_activity_id`, and the flat legacy `detail_data` fields, are absent.
- **AND** the HTTP body omits `activity_validation`, while the Coach tool result keeps it.

#### Scenario: Garmin-only or Wahoo-only session
- **WHEN** the athlete opens the local `act_` id of a session whose only active records come from Garmin or Wahoo
- **THEN** the document is returned with that provider's detail sets and summary metrics instead of a 404, and `data_scope` names that provider and the recording device.

#### Scenario: Recording device provenance
- **WHEN** an Intervals.icu record relays an activity recorded by a Garmin device
- **THEN** each `source` object derived from that record states `provider: "intervals"`, its label, its kind and `recorded_by: "garmin"`. An unknown recorder is reported as `"unknown"`, not omitted.

#### Scenario: Unknown or invalid id
- **WHEN** the id is empty, longer than 200 characters, unknown, or resolves to a session without active records
- **THEN** the read fails with the existing `invalid_activity_request` or `activity_details_not_found` error and a provider-neutral message, and no provider request or write occurs.

Detailed contract: Derived metrics SHALL identify source and load model. Every `source` object SHALL carry an additive `recorded_by` field naming the recording device from the record provenance, and the response `data_scope` SHALL name the contributing provider(s) and the recording device instead of a fixed provider. A local session id of any provider session, including Garmin-only and Wahoo-only sessions, SHALL resolve through the same read path. Detail status SHALL expose available kinds, refreshability, stale/load-error metadata, and coverage. The PWA SHALL render only from the served document and SHALL derive its refresh offer from `detail_data.providers[]` entries rather than from an Intervals-only activity check. Frontend asset query versions and the service-worker cache name SHALL change together with the contract.

Evidence: `backend/activities/detail_contract.py:activity_detail_contract`, `backend/performance/canonical_detail.py:CanonicalDetailReader`; `tests/test_activity_detail_contract.py:test_document_has_the_contract_sections`, `tests/test_activity_detail_contract.py:test_recorders_own_copy_provides_the_measured_value_and_others_are_alternatives`, `tests/test_activity_detail_contract.py:test_status_adds_stale_load_error_and_coverage_per_provider`. Served contract: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`, `backend/performance/detail_envelope.py:DetailEnvelopeReader`, `backend/http_api/activity_assembly.py`; `tests/test_activity_detail_parity.py:test_old_projection_values_appear_in_the_v1_fields`, `tests/test_activity_detail_parity.py:test_data_scope_names_the_provider_and_the_recorder`, `tests/test_detail_envelope.py:test_envelope_is_filled_for_intervals_garmin_and_wahoo_sessions`, `tests/test_http_sync_get_routes.py:test_garmin_only_session_is_served`, `tests/test_http_sync_get_routes.py:test_unknown_session_is_not_found`, and `e2e/activity-details.spec.js` on all five Playwright projects.

### Requirement: Sample provenance and clock-aware detail merging
The system SHALL merge alternative detail sets deterministically without mutating them, prefer full-resolution streams over downsampled streams, choose channels by eligible device/source quality, and place them on a common clock only when alignment is supported. Laps SHALL prefer provider intervals before device laps and splits; zones SHALL retain sensor and boundary-source identity. Presentation downsampling SHALL retain aligned equal-length channels and identify that sampling occurred.

#### Scenario: Complementary sensors
- **WHEN** a chest-strap heart-rate stream and a power-meter power stream can align to the selected axis
- **THEN** each channel may use its better source while preserving its provenance.

#### Scenario: Unalignable alternative
- **WHEN** start times or overlap do not support clock alignment
- **THEN** the alternative is skipped for that channel or retains its own lap clock, rather than combining unrelated sample positions.

Evidence: `backend/activities/detail_merge.py:merge_details`, `backend/activities/detail_merge.py:clock_offset`, `backend/activities/detail_contract.py:activity_detail_contract`; `tests/test_activity_detail_merge.py:test_full_set_beats_downsampled_even_when_relayed`, `tests/test_activity_detail_merge.py:test_power_and_heart_rate_come_from_their_best_devices`, `tests/test_activity_detail_contract.py:test_unalignable_laps_keep_their_own_clock`.

### Requirement: Current cached analysis and truthful freshness
The system SHALL read local details without implicit provider refresh and compare each provider's stored canonical detail fingerprint with that provider's current summary fingerprint. The reader SHALL recompute analysis from merged canonical detail streams and SHALL withhold it while a provider contributing streams or laps is stale. Detail failures SHALL preserve usable summaries and matching load-error metadata.

#### Scenario: Summary corrected after analysis
- **WHEN** the Intervals.icu summary fingerprint no longer matches the fingerprint stored with that record's canonical detail sets
- **THEN** that provider entry reports `stale: true`, `analysis` is null, and the session metrics show the current summary values rather than values cached with the older detail.

#### Scenario: Valid old activity
- **WHEN** a local activity lies outside the recent performance-input window
- **THEN** detail lookup may consult full local history in the same read snapshot rather than returning a false not-found result.

#### Scenario: Lookup without snapshot rows
- **WHEN** a known local activity is requested and the stored snapshot holds no activity rows
- **THEN** the summary row is found in the canonical rows and the document is returned, and an unknown id gives the existing not-found response.

#### Scenario: Canonical merged analysis
- **WHEN** canonical detail sets from multiple providers are available and none is stale
- **THEN** analysis is recomputed from the merged original channels with their source labels and separate per-provider stale status.

#### Scenario: Live zone times
- **WHEN** the current Intervals.icu summary row carries heart-rate or power zone times that differ from the stored zone sets
- **THEN** the served Intervals zone buckets use the live values and the provider entry is not marked stale for that difference alone.

#### Scenario: Stored detail without fingerprint
- **WHEN** a stored detail set has no summary fingerprint
- **THEN** it is never reported stale.

#### Scenario: Load failure note
- **WHEN** a failure note exists for the current summary fingerprint
- **THEN** the Intervals.icu provider entry reports its message and time. A note keyed by another fingerprint is ignored, and a later successful detail write removes the note in the same transaction.

Detailed contract: The current summary row of a session SHALL be found in the canonical activity rows only; the stored snapshot SHALL NOT be a lookup source. Session scalars SHALL come from the current summary row. Intervals.icu zone times SHALL come from the current summary row when present, outside the fingerprint. Analysis aggregation for reports and calendar profiles SHALL read only canonical analysis rows whose stored fingerprint matches current activity data; no kv detail fallback is read. Analyses retained only in unverifiable kv records are no longer displayed but remain stored. Old known activities are resolvable beyond the recent performance window. The analysis read service requires its canonical source at construction.

Evidence: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/canonical_detail.py:CanonicalDetailReader.read`; `tests/test_activity_read_service.py:test_detail_reads_an_activity_older_than_the_performance_window`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_canonical_detail_reader.py:test_analysis_is_recomputed_from_the_merged_streams`. `tests/test_canonical_detail_reader.py:test_live_zone_times_replace_stored_zones_without_marking_stale`, `tests/test_canonical_detail_reader.py:test_stale_provider_withholds_analysis_and_shows_current_scalars`, `tests/test_canonical_detail_reader.py:test_set_without_a_fingerprint_is_never_stale`, `tests/test_characterization_activity_reads.py:test_changed_provider_summary_marks_record_stale_and_hides_analysis`. Missing evidence (planned in this change): lookup with a snapshot that has no activity rows and construction without a canonical source.

### Requirement: Conservative planned-workout matching and interval quality
The system SHALL match planned units to compatible completed activities using the implemented identity/time/sport rules and freeze targets only for an unambiguous local plan match. Interval-quality calculations SHALL use frozen target basis and original measured samples/laps, report missing steps as partial, and leave ambiguous or unsupported targets unscored. Completed duration alone SHALL not establish target achievement.

#### Scenario: Percentage target with frozen FTP
- **WHEN** a uniquely matched planned step targets a percentage of the frozen FTP and only some planned steps have measured laps
- **THEN** achieved seconds and deviation use that basis and the overall result reports partial completion with missing steps.

#### Scenario: Ambiguous or unmeasurable target
- **WHEN** several completed activities could match a local plan, lap duration does not match, or the percentage basis is missing
- **THEN** no confident frozen target/score is invented.

Evidence: `backend/activities/matching.py:match_planned_workouts`, `backend/performance/session_analysis.py:interval_quality`, `backend/planning/target_snapshot.py:freeze_targets`; `tests/test_session_analysis.py:test_only_unique_local_match_can_freeze_targets`, `tests/test_session_analysis.py:test_target_uses_frozen_ftp_and_partial_completion_is_partial`, `tests/test_session_analysis.py:test_measured_duration_does_not_imply_target_achievement`.

### Requirement: Measured aerobic observations
The system SHALL calculate aerobic efficiency/drift only from sufficiently continuous, moving, appropriate original pulse/output samples and use time weighting for irregular sample intervals. Missing pulse, stopped recordings, excessive gaps, or highly variable interval output SHALL produce insufficient data. Aggregated endurance reads SHALL label results as individual observations with comparability limits rather than inferring a fitness trend from unsuitable sessions.

#### Scenario: Steady measured ride
- **WHEN** a suitable steady ride has continuous heart-rate and output measurements
- **THEN** the result reports time-weighted drift and the stream provider's source label.

#### Scenario: Unsuitable endurance evidence
- **WHEN** pulse is absent, samples have large gaps, the recording is stopped, or output is highly variable
- **THEN** the analysis reports insufficient data instead of a confident drift value.

Evidence: `backend/performance/session_analysis.py:aerobic_analysis`, `backend/performance/report_service.py:TrainingRecordsService.endurance`; `tests/test_session_analysis.py:test_irregular_time_spacing_preserves_time_weighted_result`, `tests/test_session_analysis.py:test_missing_pulse_stops_and_variable_intervals_stay_open`, `tests/test_session_analysis.py:test_source_label_names_the_stream_provider`.

### Requirement: Original-stream best efforts and validation evidence
The system SHALL compute observed power-duration and running speed/distance efforts from original time-weighted streams, preserve unknown windows across gaps, keep measured zeros, and keep display downsampling separate from calculations. Latest-activity validation SHALL expose bounded sport-specific direct evidence alongside provider references without claiming a laboratory threshold, VO2max, Zone-2, or race-prediction validation from one activity.

#### Scenario: Brief sprint
- **WHEN** an original stream contains a sprint shorter than the display sampling interval
- **THEN** best-effort calculation can retain it even if a rendered chart has fewer points.

#### Scenario: Unsupported or sparse activity
- **WHEN** no usable completed activity exists, the sport lacks a specific validation path, or required samples contain gaps
- **THEN** validation states the relevant no-data/unsupported scope and effort windows remain unknown.

Evidence: `backend/performance/power_profile.py:power_profile`, `backend/performance/power_profile.py:running_profile`, `backend/performance/activity_validation.py:activity_performance_validation`; `tests/test_power_profile.py:test_sprint_is_not_lost_to_display_downsampling`, `tests/test_power_profile.py:test_missing_or_stopped_recording_never_yields_peak`, `tests/test_activity_performance_validation.py:test_unknown_sport_and_no_activity_are_explicit`.

### Requirement: Durable athlete feedback separate from provider values
The system SHALL normalize and persist local notes, session RPE from 0 through 10, and deviation reason against the resolved activity reference. Omitted fields SHALL preserve existing values; explicit clearing of all meaningful fields SHALL delete the local feedback. Coach saves SHALL require a currently known local activity and nonempty feedback.

#### Scenario: RPE-only correction
- **WHEN** the athlete submits only a valid RPE, including zero
- **THEN** existing notes and other omitted fields remain stored and the new RPE is returned.

#### Scenario: Explicit clear or invalid feedback
- **WHEN** all meaningful fields are explicitly cleared
- **THEN** the local feedback row is deleted; invalid/nonfinite RPE is rejected before writing.

#### Scenario: Unknown Coach target
- **WHEN** a Coach feedback save names an activity absent from local canonical reads
- **THEN** it fails without inventing an activity or writing feedback to an unrelated record.

Detailed contract: Feedback SHALL remain separate from provider measurements and daily check-ins, attach by exact activity identity, and survive unrelated provider reads.

Evidence: `backend/activities/feedback.py:normalize_activity_feedback`, `backend/activities/feedback.py:ActivityFeedbackService.save`, `backend/activities/feedback.py:ActivityFeedbackService.save_coach`; `tests/test_activity_feedback.py:test_rpe_only_preserves_notes_and_explicit_clear_deletes`, `tests/test_activity_feedback.py:test_coach_save_requires_known_snapshot_activity_and_accepts_aliases`, `tests/test_activity_feedback.py:test_for_activity_ids_queries_in_bounded_chunks`.

### Requirement: Authenticated analysis and scoped refresh
The system SHALL require authentication for local activity/analysis reads, including the session detail document, and preserve the POST authentication/CSRF boundary for feedback and refresh actions. Analysis refresh SHALL accept only load, performance, recovery, or sessions, with optional 14/84-day periods only for load/recovery, and refresh the selected bounded sources. Session detail reads SHALL never trigger provider requests.

#### Scenario: Selected recovery refresh
- **WHEN** the athlete refreshes recovery for a supported period
- **THEN** only the selected analysis sources/windows are refreshed and partial source results are reported honestly.

#### Scenario: Unauthorized or invalid area
- **WHEN** the caller lacks authentication or submits an unknown analysis area/unsupported period
- **THEN** the request fails before the selected provider use case is invoked.

#### Scenario: Unauthenticated detail read
- **WHEN** a caller without a valid session requests `GET /api/activities/<id>`
- **THEN** the request is rejected before any database read of detail sets, feedback or equipment.

#### Scenario: Explicit detail load from the document
- **WHEN** the PWA shows a provider entry with `refreshable: true` and the athlete starts a detail load
- **THEN** a CSRF-protected activity-detail job is posted for that provider's activity id, and the GET read itself never contacts a provider.

Detailed contract: It SHALL separately report refreshed, incomplete, pending, truncated, and not-refreshed sources, preserving successful results when another provider fails. GET analysis SHALL remain a local read.

Detailed contract: Detail loading SHALL happen only through the explicit authenticated activity-detail job for a provider that supports it.

Evidence: `backend/http_api/analysis.py:AnalysisRoutes`, `backend/http_api/sync_get.py:SyncGetRoutes`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `backend/sync/analysis_refresh.py:AnalysisRefreshService.refresh`; `tests/test_training_report.py:test_get_authentication_precedes_analysis_reads`, `tests/test_training_report.py:test_analysis_refresh_rejects_unknown_area`, `tests/test_analysis_refresh.py:test_failed_provider_does_not_discard_other_fresh_results`. `tests/test_http_sync_get_routes.py:test_authentication_precedes_every_detail_read`, `tests/test_detail_envelope.py:test_refresh_is_offered_for_configured_detail_providers_only`, and `e2e/activity-details.spec.js` ("Garmin-only session shows per-provider notes and its own refresh").

### Requirement: Session-owned effective feedback
Feedback SHALL resolve to canonical session identity across provider imports. Each session SHALL expose one effective feedback and one effective sRPE contribution. Legacy conflicting feedback SHALL remain recoverable with deterministic selection; heuristic similarity alone SHALL not combine athlete feedback.

#### Scenario: Same session through two providers
- **WHEN** two provider activities are confirmed copies of one session and feedback is saved through either supported reference
- **THEN** reads expose the same effective feedback and session-RPE is counted once.

#### Scenario: Existing conflicting feedback
- **WHEN** an upgrade or confirmed merge encounters different feedback on two provider copies
- **THEN** every original row remains recoverable and the effective selection is deterministic and exposes the conflict rather than averaging or discarding athlete input.

### Requirement: Feedback identity survives lifecycle changes
Merge, provider deletion, restart and backup/restore SHALL preserve athlete feedback and the session it was written for, so a later unmerge can restore the association without loss. Undo of a feedback save or clear SHALL restore the prior records and values without duplicating the effective feedback. Provider deletion SHALL not delete local feedback.

#### Scenario: Merged copies and feedback undo
- **WHEN** sessions with saved feedback are merged and a later feedback save or clear is undone
- **THEN** merged reads count feedback once and undo restores every prior feedback record with its original session association.

#### Scenario: Provider activity deleted
- **WHEN** a provider copy is marked deleted
- **THEN** stored athlete feedback remains intact and reachable through its canonical session/history.

#### Scenario: Existing save and Coach contracts
- **WHEN** feedback is saved or undone through the supported API or an athlete-started Coach turn
- **THEN** existing partial-edit, validation, authorization, receipt and undo behavior remains available.

Evidence baseline: `backend/activities/feedback.py`, `backend/activities/activity_reference.py`, `backend/db/repositories.py:ActivityFeedbackRepository`; `tests/test_activity_feedback.py`, `tests/test_activity_reference.py`. Canonical session resolution and lifecycle evidence are new acceptance checks.

### Requirement: Completed-activity summaries use provider-neutral keys over HTTP
Every completed-activity object that the HTTP API returns SHALL carry provider-neutral keys produced by one translation, and SHALL NOT carry the former Intervals.icu activity keys. Values SHALL be unchanged. Local planning records keep their stored keys until #1507 and receive only the metric renames.

#### Scenario: Activity list row
- **WHEN** `/api/activities` or `/api/bootstrap` returns an activity with start, duration, distance, heart-rate, power, speed, load, threshold and VO2max values
- **THEN** they appear as `started_at_local`, `moving_duration_s`, `elapsed_duration_s`, `distance_m`, `avg_hr`, `max_hr`, `avg_power`, `weighted_avg_power`, `normalized_power`, `avg_speed_mps`, `elevation_gain_m`, `training_load`, `intensity`, `rpe`, `ctl`, `atl`, `ftp_w`, `eftp_w` and `vo2max` with the stored values, and none of `start_date_local`, `moving_time`, `distance`, `average_heartrate`, `average_watts` or `icu_*` is present.

#### Scenario: Calendar actual activity
- **WHEN** `/api/bootstrap` or `/api/plan` returns, in `training_calendar`, `planned`, `calendar` or `planning_view.items`, a completed-activity calendar entry or a planned unit matched to an activity
- **THEN** the completed entry and `compliance.actual_activity` use the neutral keys. The planned unit keeps its own `start_date_local` and `moving_time` unchanged, and its `icu_training_load` appears as `training_load`.

#### Scenario: Neutral value already present
- **WHEN** a stored row carries both a provider key and its neutral counterpart, such as `icu_weighted_avg_watts` and `normalized_power`
- **THEN** the neutral value wins and the provider key is dropped.

#### Scenario: Browser shows unchanged values
- **WHEN** the activity analysis list, the analysis row summary before the detail loads, and the calendar's completed and matched entries render the same synthetic data as before
- **THEN** they show the same dates, durations, distances, heart rate, power and load.

Detailed contract: the key map is listed in `openspec/changes/archive/2026-10-30-neutral-activity-http-shape/design.md` (D1). A neutral key that is already present wins. `weighted_average_watts` stays separate from `normalized_power`. The activity detail document (`/api/activities/{id}`) is already neutral and stays unchanged. The provider-coupling ratchet records every module outside the provider, sync and canonical packages that imports a provider field-name module, and that record may only shrink.

Evidence: `backend/canonical/public_metrics.py:neutral_activity`, `backend/canonical/public_metrics.py:neutral_calendar_state`, `backend/http_api/bootstrap_calendar.py`, `backend/http_api/public_plan.py:PublicPlanStateService.read_public`, `backend/http_api/bootstrap_state.py`, `public/activity-analysis.js`, `public/plan-views.js`; `tests/test_canonical_public_metrics.py:NeutralPublicMetricsTests`, `tests/test_http_sync_get_routes.py:test_activity_page_uses_neutral_names_and_detail_is_passed_through`, `tests/test_public_plan.py:test_internal_read_keeps_stored_metrics_and_public_read_translates`, `tests/plan-views-week-distance.test.cjs`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_consumers_cannot_import_provider_field_name_modules`; `e2e/contracts.spec.js`, `e2e/activity-details.spec.js`.
