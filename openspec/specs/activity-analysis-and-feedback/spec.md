# activity-analysis-and-feedback Specification

## Purpose

Record local completed-session detail, evidence-based analysis, planned-versus-completed matching, and athlete feedback. This backfill describes inspected implementation; mocked unit evidence does not establish live-provider or browser conformance.

## Requirements

### Requirement: Provider-neutral session detail document
The system SHALL assemble an `activity_detail.v1` document for a canonical session with session identity, metrics, streams, laps, zones, analysis, feedback/equipment envelope, and per-provider detail state. Measured metrics SHALL prefer the recorder's own copy and preserve alternatives; derived metrics SHALL identify source and load model. Missing values SHALL remain absent rather than becoming zeros.

#### Scenario: Several provider copies
- **WHEN** a session has both a recorder's original activity and a relayed copy
- **THEN** measured scalar values prefer the original and alternative values retain their source metadata.

#### Scenario: Detail unavailable
- **WHEN** no streams or a particular measured metric exist
- **THEN** the document remains valid with explicit available coverage and absent unsupported sections/metrics; a missing source does not become a zero measurement.

Detailed contract: Detail status SHALL expose available kinds, refreshability, stale/load-error metadata, and coverage.

Evidence: `backend/activities/detail_contract.py:activity_detail_contract`, `backend/performance/canonical_detail.py:CanonicalDetailReader`; `tests/test_activity_detail_contract.py:test_document_has_the_contract_sections`, `tests/test_activity_detail_contract.py:test_recorders_own_copy_provides_the_measured_value_and_others_are_alternatives`, `tests/test_activity_detail_contract.py:test_status_adds_stale_load_error_and_coverage_per_provider`.

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
The system SHALL read local details without implicit provider refresh and compare stored summary fingerprints with current summaries. The compatibility reader SHALL suppress stale cached analysis; the canonical reader SHALL recompute analysis from merged detail streams and report per-provider staleness. Detail failures SHALL preserve usable summaries and matching load-error metadata.

#### Scenario: Summary corrected after analysis
- **WHEN** the activity summary hash no longer matches cached detail analysis
- **THEN** stale metadata is exposed and cached analysis is not treated as current evidence.

#### Scenario: Valid old activity
- **WHEN** a local activity lies outside the recent performance-input window
- **THEN** detail lookup may consult full local history in the same read snapshot rather than returning a false not-found result.

#### Scenario: Canonical merged analysis
- **WHEN** canonical detail sets from multiple providers are available
- **THEN** analysis is recomputed from the merged original channels with their source labels and separate per-provider stale status, rather than merely replaying cached compatibility analysis.

Detailed contract: Compatibility analysis record aggregation includes only summaries whose stored fingerprint matches current activity data, and old known activities are resolvable beyond the recent performance window. Live zone totals remain authoritative in the compatibility path where excluded from its summary fingerprint.

Evidence: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/canonical_detail.py:CanonicalDetailReader.read`; `tests/test_activity_read_service.py:test_detail_reads_an_activity_older_than_the_performance_window`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_canonical_detail_reader.py:test_analysis_is_recomputed_from_the_merged_streams`.

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
The system SHALL require authentication for local activity/analysis reads and preserve the POST authentication/CSRF boundary for feedback and refresh actions. Analysis refresh SHALL accept only load, performance, recovery, or sessions, with optional 14/84-day periods only for load/recovery, and refresh the selected bounded sources.

#### Scenario: Selected recovery refresh
- **WHEN** the athlete refreshes recovery for a supported period
- **THEN** only the selected analysis sources/windows are refreshed and partial source results are reported honestly.

#### Scenario: Unauthorized or invalid area
- **WHEN** the caller lacks authentication or submits an unknown analysis area/unsupported period
- **THEN** the request fails before the selected provider use case is invoked.

Detailed contract: It SHALL separately report refreshed, incomplete, pending, truncated, and not-refreshed sources, preserving successful results when another provider fails. GET analysis SHALL remain a local read.

Evidence: `backend/http_api/analysis.py:AnalysisRoutes`, `backend/http_api/sync_get.py:SyncGetRoutes`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `backend/sync/analysis_refresh.py:AnalysisRefreshService.refresh`; `tests/test_training_report.py:test_get_authentication_precedes_analysis_reads`, `tests/test_training_report.py:test_analysis_refresh_rejects_unknown_area`, `tests/test_analysis_refresh.py:test_failed_provider_does_not_discard_other_fresh_results`.
