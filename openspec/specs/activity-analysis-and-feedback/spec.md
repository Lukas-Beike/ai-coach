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
- **THEN** the body is the `activity_detail.v1` document with `contract`, `session`, `metrics`, `streams`, `laps`, `zones`, `strength_sets` (the executed strength sets per exercise with reps, kg and rest, or null), `analysis`, `detail_data` and the envelope keys `activity_feedback`, `equipment` and `session_rpe_load`. `session` also carries `purpose`, `competition_id` and `purpose_source` when the session summary has them. The legacy keys `activity`, `session_analysis` and `local_activity_id`, and the flat legacy `detail_data` fields, are absent.
- **AND** the HTTP body omits `activity_validation`, while the Coach tool result keeps it.

#### Scenario: Executed strength sets in plan compliance
- **WHEN** a completed strength session with executed sets is matched to a planned unit with a `strength_structure`
- **THEN** its compliance uses basis `strength_sets`: per planned exercise, matched by the exercise category of its Garmin catalogue exercise, the sets done at or above the planned reps against the planned sets; planned warm-up sets of an exercise are not counted as working sets; exercises without a known category are `unknown`, never a miss, and without a matched exercise or executed sets the duration or load basis stays. The PWA calendar entry lists each planned exercise with its completed sets, executed reps and plan, and the activity detail shows every executed set with exercise, reps, kg and rest.

Evidence: `backend/activities/strength_sets.py:plan_comparison`, `backend/activities/calendar_projection.py:workout_compliance`; `tests/test_strength_consumers.py`, `tests/test_strength_sets.py`.

#### Scenario: Provider ratings with their scale
- **WHEN** a record of the session carries the watch's `rpe` or `feel`
- **THEN** the metric is `athlete_entered` with the value of the first record in rating order (Garmin, then retired Intervals.icu copies, then the rest) and, for a known provider scale, the scale text, label and a `normalized_0_1` value; the local feedback RPE stays separate and authoritative.

Evidence: `backend/activities/detail_contract.py:rating_order`, `backend/canonical/rating_scales.py:rating_fields`; `tests/test_garmin_activity_ratings.py:test_detail_document_names_the_garmin_scale`.

#### Scenario: Garmin-only or Wahoo-only session
- **WHEN** the athlete opens the local `act_` id of a session whose only active records come from Garmin or Wahoo
- **THEN** the document is returned with that provider's detail sets and summary metrics instead of a 404, and `data_scope` names that provider and the recording device.

#### Scenario: Recording device provenance
- **WHEN** a provider record relays an activity recorded by another platform's device
- **THEN** each `source` object derived from that record states its `provider`, label, kind and `recorded_by` (for example a relayed copy of a Garmin recording states the relaying provider and `recorded_by: "garmin"`). An unknown recorder is reported as `"unknown"`, not omitted.

#### Scenario: Unknown or invalid id
- **WHEN** the id is empty, longer than 200 characters, unknown, or resolves to a session without active records
- **THEN** the read fails with the existing `invalid_activity_request` or `activity_details_not_found` error and a provider-neutral message, and no provider request or write occurs.

Detailed contract: Derived metrics SHALL identify source and load model. Every `source` object SHALL carry an additive `recorded_by` field naming the recording device from the record provenance, and the response `data_scope` SHALL name the contributing provider(s) and the recording device instead of a fixed provider. A local session id of any provider session, including Garmin-only and Wahoo-only sessions, SHALL resolve through the same read path. Detail status SHALL expose available kinds, refreshability, stale/load-error metadata, and coverage. The PWA SHALL render only from the served document and SHALL derive its refresh offer from `detail_data.providers[]` entries rather than from an Intervals-only activity check. Frontend asset query versions and the service-worker cache name SHALL change together with the contract.

Evidence: `backend/activities/detail_contract.py:activity_detail_contract`, `backend/performance/canonical_detail.py:CanonicalDetailReader`; `tests/test_activity_detail_contract.py:test_document_has_the_contract_sections`, `tests/test_activity_detail_contract.py:test_recorders_own_copy_provides_the_measured_value_and_others_are_alternatives`, `tests/test_activity_detail_contract.py:test_status_adds_stale_load_error_and_coverage_per_provider`. Served contract: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`, `backend/performance/detail_envelope.py:DetailEnvelopeReader`, `backend/http_api/activity_assembly.py`; `tests/test_detail_envelope.py:test_envelope_is_filled_for_intervals_garmin_and_wahoo_sessions`, `tests/test_http_sync_get_routes.py:test_garmin_only_session_is_served`, `tests/test_http_sync_get_routes.py:test_unknown_session_is_not_found`, and `e2e/activity-details.spec.js` on all five Playwright projects.

### Requirement: Sample provenance and clock-aware detail merging
The system SHALL merge alternative detail sets deterministically without mutating them, prefer full-resolution over downsampled streams, choose channels by device and source quality, and align them to a common clock only when supported. Provider ties follow Wahoo, Garmin, Intervals.icu; laps prefer device laps, then provider intervals, then splits; zones keep sensor and boundary-source identity. Downsampling keeps aligned equal-length channels and is flagged.

#### Scenario: Sensor source decides the channel
- **WHEN** two alternative sets carry the same heart rate or power channel and one names a chest strap or power meter while the other names optical heart rate or an estimate
- **THEN** the channel comes from the set whose named source is better; the activity device class only breaks ties between equal sources and ranks sets that name none. Heart rate ranks chest strap, then unknown or absent, then optical; power ranks power meter, trainer, unknown or absent, estimated. The session analysis states the shown heart rate and power source and marks optical heart rate in intervals as less reliable.

#### Scenario: Power meter change marker
- **WHEN** a recording of a sport names external power meters that share none with any earlier recording of that sport (recordings without a named meter are skipped, so alternating between two bikes with their own meters raises a marker only when the second meter first appears)
- **THEN** a marker with the day and the hashed sensor ids is served with the power profiles and the Coach, and critical power inside its window carries it; a serial number is never stored, shown or logged. The day is the date part of the stored start time, which Garmin and Wahoo records store in UTC, not the athlete-local day.

#### Scenario: Complementary sensors
- **WHEN** a chest-strap heart-rate stream and a power-meter power stream can align to the selected axis
- **THEN** each channel may use its better source while preserving its provenance.

#### Scenario: Unalignable alternative
- **WHEN** start times or overlap do not support clock alignment
- **THEN** the alternative is skipped for that channel or retains its own lap clock, rather than combining unrelated sample positions.

Evidence: `backend/activities/detail_merge.py:merge_details`, `backend/activities/detail_merge.py:clock_offset`, `backend/activities/detail_contract.py:activity_detail_contract`; `tests/test_activity_detail_merge.py:test_full_set_beats_downsampled_even_when_relayed`, `tests/test_activity_detail_merge.py:test_power_and_heart_rate_come_from_their_best_devices`, `tests/test_activity_detail_contract.py:test_unalignable_laps_keep_their_own_clock`, `backend/canonical/sensor_registry.py:power_meter_changes`; `tests/test_sensor_sources.py`.

### Requirement: Current cached analysis and truthful freshness
The system SHALL read local details without implicit provider refresh, serve only the detail sets of the session's Garmin, Wahoo and local records, and compare each provider's stored canonical detail fingerprint with that provider's current summary fingerprint. The reader SHALL compute the canonical session analysis from that merged detail and SHALL withhold it while a provider contributing streams or laps is stale. Intervals.icu detail sets, summary rows and failure notes SHALL NOT be read.

#### Scenario: Summary corrected after analysis
- **WHEN** a Garmin or Wahoo record's current payload hash no longer matches the fingerprint stored with its canonical detail sets
- **THEN** that provider entry reports `stale: true`, `analysis` is null, and the session metrics show the current record values rather than values cached with the older detail.

#### Scenario: Valid old activity
- **WHEN** a local activity lies outside the recent performance-input window
- **THEN** detail lookup may consult full local history in the same read snapshot rather than returning a false not-found result.

#### Scenario: Lookup without snapshot rows
- **WHEN** a known local activity is requested and the stored snapshot holds no activity rows
- **THEN** the session is found in the canonical rows and the document is returned, and an unknown id gives the existing not-found response.

#### Scenario: Canonical merged analysis
- **WHEN** canonical detail sets from multiple providers are available and none is stale
- **THEN** analysis is computed from the merged Garmin, Wahoo and local channels with their source labels and separate per-provider stale status; an Intervals.icu-only session has no analysis.

#### Scenario: One stored analysis for every consumer
- **WHEN** a session's records, stream or lap sets, staleness, frozen targets or locally resolved thresholds change, or the method version changes
- **THEN** the canonical backfill stage `session_analysis` recomputes its `activity_detail_analysis` version 3 row (analysis, recorded workout profile, carried-over target snapshot, input fingerprint) in bounded batches, an unchanged input writes nothing, and the detail view, Coach detail tool, calendar profiles and recurring comparisons show the same values for Garmin- and Wahoo-only sessions too.

#### Scenario: Intervals.icu copy not served
- **WHEN** a session holds an Intervals.icu record with stored detail sets, zone times or a failure note
- **THEN** its provider entry lists no kinds, no load error and no refresh, the document serves no Intervals.icu streams, laps, zone times or summary-row metrics, and its staleness withholds nothing.

#### Scenario: Zone times from streams
- **WHEN** a session has a heart-rate or power stream
- **THEN** the document derives a distribution on read from the merged stream with the zones in effect for the session's sport, environment and local day (thresholds local, then Garmin, then Wahoo; limits of the effective local, then Garmin (the zones set on the watch) or Wahoo configuration; never Intervals.icu), labelled derived with profile boundaries and with the zone source (`Zoneneinstellungen: Garmin-Zonen`, `lokale Zonen` or `Standardzonen`), chosen over a provider distribution, which stays an alternative; pauses and samples marked not moving count nothing, and without the threshold the provider distribution, if any, stays.

#### Scenario: Report zone times in one zone model
- **WHEN** the canonical session analysis stage computes a session with streams
- **THEN** it stores heart-rate, power and (for runs, against the threshold speed) pace seconds per zone counted by the same rule and resolver as the detail document, with the thresholds, limits and zone source of each sensor in the input fingerprint (a changed watch zone set recomputes the stored zone times) and the source named in the summary's source label; the activity summaries carry these local zone times with a `zone_models` marker, a session without them keeps its Garmin or Wahoo zone times marked `provider`, Intervals.icu zone times are never read, the zone distribution reports each zone model as its own entry, and the 3-zone intensity adds local zone times only.

#### Scenario: Stored detail without fingerprint
- **WHEN** a stored detail set has no summary fingerprint
- **THEN** it is never reported stale.

Detailed contract: A session SHALL be found in the canonical activity rows only; the stored snapshot SHALL NOT be a lookup source. Session scalars SHALL come from the canonical activity records and the local session metrics (card M8); no provider summary row is read. Analysis aggregation for reports and calendar profiles SHALL read only version-3 canonical analysis rows of live sessions, keyed by session id, except the best-effort curve, which reads full-resolution canonical stream sets; Intervals.icu-path rows and kv records are never read. The recorded profile colors power by the FTP and heart rate by the threshold HR resolved locally (local, Garmin, Wahoo) for the session day. Existing target snapshots, also those kept under a session merged into another, carry over unchanged; a session without one freezes its matched planned targets at its first computation when it started within the last seven days, and a legacy kv copy hands its frozen targets to a canonical row without one. Analyses retained only in unverifiable kv records are no longer displayed but remain stored. Old known activities are resolvable beyond the recent performance window. The analysis read service requires its canonical source at construction.

Evidence: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/canonical_detail.py:CanonicalDetailReader.read`, `backend/activities/stream_zones.py:with_stream_zones`; `tests/test_stream_zones.py`, `tests/test_activity_read_service.py:test_detail_reads_an_activity_older_than_the_performance_window`, `tests/test_canonical_detail_reader.py:test_analysis_is_recomputed_from_the_merged_streams`, `tests/test_canonical_detail_reader.py:test_intervals_detail_and_decoupling_are_never_analysis_inputs`, `tests/test_session_analysis_stage.py`. `tests/test_canonical_detail_reader.py:test_intervals_copies_are_never_served`, `tests/test_canonical_detail_reader.py:test_stale_provider_withholds_analysis_and_keeps_the_streams`, `tests/test_canonical_detail_reader.py:test_set_without_a_fingerprint_is_never_stale`, `tests/test_characterization_activity_reads.py:test_intervals_detail_is_never_served`. `tests/test_activity_read_service.py:test_detail_reads_no_provider_summary_row_without_snapshot_activities`, `tests/test_activity_read_service.py:test_detail_service_requires_a_canonical_source`.

### Requirement: Descriptive session execution
The system SHALL describe how one run or ride was executed from its own merged streams and laps, without a plan match, norms or other sessions: structure, work laps, recoveries, warm-up, cool-down, halves of a continuous main part, and sensor-quality flags. Other sports are not applicable.

#### Scenario: Interval session
- **WHEN** a run or ride has at least two work laps
- **THEN** each work lap reports its output (pace in s/km for runs, power in W for rides, else km/h), first and second half, the first 30 s against the rest, the spread after the first 10 s, average, peak, half and closing heart rate, cadence and stride length per half, altitude change and, with a lap distance, the lap pace; each following recovery reports its heart-rate drop 60 s in and closing heart rate, and a rep summary closes the list; work laps under 120 s are marked short so their heart rate is not judged, and an indoor ride with power held within 3 % is `erg_like`.

#### Scenario: Unlabelled interval laps
- **WHEN** a run has laps without work or recovery labels whose outputs split into a faster and a slower group
- **THEN** the faster laps are work laps, slower laps before and after them warm-up and cool-down, the ones between recoveries, and `structure_origin` is `lap_output`; equal automatic laps stay one continuous session.

#### Scenario: Sensor doubt
- **WHEN** heart rate jumps by more than 20 bpm within 2 s in over 2 % of samples, a run's heart rate follows its step cadence, or speed jumps by more than 2.5 m/s within 2 s in over 1 % of samples
- **THEN** `data_quality` names `spikes`, `possible_cadence_lock` or `jumps`, so the Coach can doubt the reading before calling it fatigue.

Evidence: `backend/performance/session_execution.py:session_execution`, `backend/performance/canonical_session_analysis.py`, `backend/performance/analysis_input.py:analysis_input`; `tests/test_session_execution.py`, `tests/test_canonical_detail_reader.py:test_analysis_is_recomputed_from_the_merged_streams`.

### Requirement: Work laps against planned targets
The system SHALL pair the executed work laps of a run or ride in order with the planned work steps of its matched local planned unit, without requiring matching durations, and describe each rep against its target from the athlete's current thresholds; ramps and unresolved targets stay unscored.

#### Scenario: Choosing the work steps
- **WHEN** a plan mixes warm-up, work and recovery steps or rises in a progression
- **THEN** the hardest steps form the work steps when their count fits the executed laps, else the steps within 10 % of the hardest target, each as a fraction of its threshold; the unit is the focus unit, else the one unit of that day and sport; single values count as plus or minus 2.5 %, the top zone is open upwards, and heart-rate targets of laps under 120 s stay unscored.

#### Scenario: Rep slower than its target
- **WHEN** a planned 4:20-4:30/km rep is run at 4:38/km
- **THEN** the rep reports its target pace range, a negative `deviation_pct` to the nearer bound, `time_in_target_pct` from the displayed streams, planned and actual duration and recovery, and the summary counts it below target.

#### Scenario: Nothing to compare
- **WHEN** the session is continuous, no planned unit matches, or no planned step has a resolvable target
- **THEN** no comparison is invented: the result is absent or `not_covered` with the reason and any unknown target reasons.

Evidence: `backend/performance/planned_targets.py:planned_target_execution`, `backend/activities/workout_load.py:step_target_range`, `backend/coach/activity_read_tools.py:CoachActivityReadToolService._planned_targets`, `backend/planning/planned_unit_load.py:PlannedUnitEstimator.thresholds`; `tests/test_planned_targets.py`.

### Requirement: Comparable earlier sessions
The system SHALL set a run's or ride's execution against comparable earlier sessions of the last 84 days, read from each session's execution in the curve window, and report this session, the peers' median and the difference with peer count and temperatures; nothing is scored.

#### Scenario: Comparable peers
- **WHEN** at least three earlier sessions with sound heart rate and speed share sport, indoor or outdoor, trail or road (runs) and structure, with a continuous main part within 35 % of this one's duration and 8 bpm of its average heart rate, or intervals within 2 reps and 35 % of the median rep duration
- **THEN** `comparable_sessions` lists the median and difference of output, heart rate, drift and cadence (continuous) or rep output, closing heart rate, recovery drop, fade and cadence (intervals), and up to six peers with their temperatures.

#### Scenario: Too few peers
- **WHEN** fewer than three sessions compare, or the session lies outside the curve window
- **THEN** the result is `not_covered` with the reason and the count, never a trend; a peer window reaching before the curve window is cut there and named `window_truncated`.

Evidence: `backend/performance/comparable_sessions.py:comparable_sessions`, `backend/performance/session_execution.py:comparison_metrics`, `backend/performance/mean_max_curve.py:SessionCurveReader.curves`, `backend/db/activity_detail_store.py:lap_set_keys`, `backend/coach/activity_read_tools.py:CoachActivityReadToolService._session_checks`; `tests/test_comparable_sessions.py`, `tests/test_coach_session_checks.py:ComparableSessionsCheckTests`, `tests/test_mean_max_curve.py:SessionExecutionCurveTests`.

### Requirement: Recognised routes of outdoor sessions
The system SHALL group repeated rides and runs with a stored GPS track that are not known to be indoor or virtual (an unknown environment, such as Garmin's generic running and cycling types, counts) into routes and give the activity view and the Coach only a route label, visit number, visit count and opaque id. The athlete SHALL be able to rename a route.

#### Scenario: Repeats of one loop
- **WHEN** several outdoor sessions, or sessions of unknown environment, follow the same loop, also with GPS jitter or in the reverse direction: distances within 10 %, start in or beside the other's start (or end) cell and a Jaccard overlap of the coarse grid cells of at least 0.6
- **THEN** they share one route and `get_activity_details` returns `route` with the label ("Strecke n" until renamed), `repeat_index` by start time and `repeat_count`

#### Scenario: Different or short tracks
- **WHEN** another loop from the same start, a distance more than 10 % apart, an indoor or virtual session, a short track or a session without positions is compared
- **THEN** it joins no route of the first loop and the last three get no route

#### Scenario: Rename
- **WHEN** the athlete posts a name of 1 to 60 characters without control characters for a known route to `/api/routes/rename`
- **THEN** the route shows that label from then on, also after recomputation; an unknown route answers 404 and an invalid name 400

Evidence: `backend/activities/routes.py:same_route`, `backend/sync/activity_routes.py:ActivityRoutesStage`, `backend/activities/route_store.py:ActivityRouteService`, `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`; `tests/test_activity_routes.py`, `tests/test_activity_read_service.py:test_detail_carries_only_the_route_label_and_repeat_count`, `tests/activity-route.test.cjs`.

### Requirement: Conservative planned-workout matching and interval quality
The system SHALL match planned units to compatible completed activities using the implemented identity/time/sport rules and freeze targets only for an unambiguous local plan match. Interval-quality calculations SHALL use frozen target basis and original measured samples/laps, report missing steps as partial, and leave ambiguous or unsupported targets unscored. Completed duration alone SHALL not establish target achievement.

#### Scenario: Percentage target with frozen FTP
- **WHEN** a uniquely matched planned step targets a percentage of the frozen FTP and only some planned steps have measured laps
- **THEN** achieved seconds and deviation use that basis and the overall result reports partial completion with missing steps.

#### Scenario: Commute, warm-up or cool-down
- **WHEN** a session has purpose commute, warm-up or cool-down
- **THEN** it never completes a planned workout and no target is frozen for it; a workout the provider paired with such a session stays open instead of matching another session by date.

Evidence: `backend/activities/matching.py:match_planned_workouts`; `tests/test_activity_matching.py:test_commutes_and_warmups_never_complete_a_planned_workout`.

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

### Requirement: Canonical mean-maximal curve
The analysis power and running best-effort curve (`mean-max-curve` version 2, windows including 180, 420, 720 and 1200 s) SHALL be computed at read time only from full-resolution canonical stream sets, count each canonical session once, give overlapping bests of one session the same effort group, and carry the method, version and an input fingerprint. The stored Intervals.icu power curve is not read by any view.

#### Scenario: Protocol windows
- **WHEN** a full-resolution stream holds 3, 7, 12 and 20 minute efforts between gaps and pauses
- **THEN** the 180, 420, 720 and 1200 s windows reproduce their mean values and no window spans a gap or pause.

#### Scenario: Downsampled, duplicate or changed streams
- **WHEN** a session has only downsampled streams, a duplicate session is merged into another, a stream set was fetched for an older provider summary, or a session's stored streams change
- **THEN** the downsampled session gives no best value and its activity detail profile is labelled `downsampled`, the merged pair counts once, the outdated set is left out, and the changed session is recomputed under a new fingerprint without provider access.

Evidence: `backend/performance/mean_max_curve.py:SessionCurveReader`, `backend/performance/report_service.py:TrainingProfileSelectionService`, `backend/performance/canonical_session_analysis.py:stream_resolution`; `tests/test_power_profile.py:test_protocol_windows_reproduce_known_maxima_around_gaps_and_pauses`, `tests/test_mean_max_curve.py`, `tests/test_performance_method_inputs.py:M4BestEffortInputs`.

### Requirement: Critical Power and Critical Speed model estimate
The power profile SHALL carry `critical-power-speed` version 2 (card M4) as an experimental model estimate: least squares of work or distance on time over the best 180, 420, 720 and 1200 s efforts (cycling) or 180, 420 and 720 s efforts (running) of the last 28 days, each effort from another session or at least 30 minutes apart in one session. It SHALL apply the card's stop rules and never set FTP, thresholds or zones.

#### Scenario: Fit groups
- **WHEN** the fit runs
- **THEN** cycling outdoor and indoor are fitted separately, running only outdoor and not trail, and each effort states whether it is a race or everyday training.

#### Scenario: Reference efforts
- **WHEN** four separate cycling efforts follow CP 250 W and W′ 18,000 J, or three separate running efforts follow CS 4 m/s and D′ 200 m
- **THEN** the fit returns exactly these parameters with the 1/t and leave-one-out fits (and for cycling the 3/7/12 min fit) as sensitivity, and Analysis and Coach show the same values.

#### Scenario: Dependent or unsuitable efforts
- **WHEN** the bests overlap in one session, fewer efforts than the protocol lists remain, a parameter or leave-one-out fit is not positive, a residual exceeds 3 %, or values fall outside CP 50–600 W, W′ 1–50 kJ, CS 1.5–7 m/s or D′ 10–500 m
- **THEN** the fit reports `insufficient_data` or `withheld` with its reason and no parameter.

Evidence: `backend/performance/critical_power.py:critical_power_speed`; `tests/test_critical_power.py`, `tests/test_performance_coach_ui_parity.py:test_mean_max_curve_is_the_analysis_route_payload`, `e2e/performance-values.spec.js`.

### Requirement: Durable athlete feedback separate from provider values
The system SHALL normalize and persist local notes, session RPE from 0 through 10, and deviation reason under the local session the activity reference names. Omitted fields SHALL preserve existing values; explicit clearing of all meaningful fields SHALL delete the local feedback. Coach saves SHALL require a currently known local activity and nonempty feedback.

#### Scenario: RPE-only correction
- **WHEN** the athlete submits only a valid RPE, including zero
- **THEN** existing notes and other omitted fields remain stored and the new RPE is returned.

#### Scenario: Explicit clear or invalid feedback
- **WHEN** all meaningful fields are explicitly cleared
- **THEN** the local feedback row is deleted; invalid/nonfinite RPE is rejected before writing.

#### Scenario: Unknown Coach target
- **WHEN** a Coach feedback save names an activity absent from local canonical reads
- **THEN** it fails without inventing an activity or writing feedback to an unrelated record.

Detailed contract: Feedback SHALL remain separate from provider measurements and daily check-ins, attach by exact activity identity, and survive unrelated provider reads. The activity feedback save response and the change-history undo response for an activity feedback change that names `activity_id` SHALL carry `session_rpe_load` under the same rules as the detail document, so the PWA updates the load line without refetching the detail.

Evidence: `backend/activities/feedback.py:normalize_activity_feedback`, `backend/activities/feedback.py:ActivityFeedbackService.save`, `backend/activities/feedback.py:ActivityFeedbackService.save_coach`; `tests/test_activity_feedback.py:test_rpe_only_preserves_notes_and_explicit_clear_deletes`, `tests/test_activity_feedback.py:test_coach_save_requires_a_live_canonical_session`, `tests/test_activity_feedback.py:test_for_activity_ids_queries_in_bounded_chunks`. Served load: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.session_rpe_load`; `tests/test_detail_envelope.py:test_save_response_load_matches_the_served_detail_load`, `tests/test_http_feedback_post.py:test_activity_feedback_save_returns_the_session_load`, `tests/test_http_history_undo_post_routes.py:test_feedback_undo_returns_the_session_load_of_the_named_activity`, and `e2e/activity-details.spec.js`.

### Requirement: Athlete marking of the session purpose
The system SHALL let the athlete mark a completed session as training, race, commute, warm-up or cool-down in the activity details and through the Coach tool `save_activity_feedback` (`purpose`, null removes it). The marking SHALL be stored with the feedback rows of the session, so receipts, undo and merge groups apply, and SHALL win over the provider event type and the competition hint on every read of the activity summaries.

#### Scenario: Training overrides a race
- **WHEN** the athlete marks a Garmin race or a hint-linked session as training
- **THEN** the summaries report purpose training from the athlete, the competition link is gone, and no other session of that day and sport takes the hint.

#### Scenario: Marked race
- **WHEN** the athlete marks a session as race
- **THEN** it is linked to the stored competition of its day like a provider race.

#### Scenario: Commute, warm-up and cool-down
- **WHEN** a session is marked commute, warm-up or cool-down
- **THEN** it stays out of bests, mean-maximal curves, critical-power efforts and planned-session matching.

#### Scenario: Undo restores the previous purpose
- **WHEN** the athlete undoes the marking
- **THEN** the previous marking, or the Garmin purpose and the competition hint, is served again.

#### Scenario: Feedback delete and unassignable activity
- **WHEN** the feedback is deleted, including by the Coach tool `delete_activity_feedback`, **THEN** the marking stays; **WHEN** the activity cannot be assigned to exactly one session, **THEN** a marking is refused.

Evidence: `backend/activities/feedback.py:session_purpose_marks`, `backend/activities/session_purpose.py:with_marked_purposes`; `tests/test_feedback_purpose.py`, `tests/test_session_purpose.py:SelectorMarkedPurposeTests`, `e2e/activity-details.spec.js`.

### Requirement: Authenticated analysis and scoped refresh
The system SHALL require authentication for local activity/analysis reads, including the session detail document, and preserve the POST authentication/CSRF boundary for feedback and refresh actions. Analysis refresh SHALL accept only load, performance, recovery, or sessions, with optional 14/84-day periods only for load/recovery, and refresh the selected bounded sources. Session detail reads SHALL never trigger provider requests.

#### Scenario: Sources
- **WHEN** an area is refreshed
- **THEN** Garmin is read for the area and Wahoo additionally for sessions and performance; a source that is not configured is neither refreshed nor reported missing.

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

Evidence: `backend/http_api/analysis.py:AnalysisRoutes`, `backend/http_api/sync_get.py:SyncGetRoutes`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `backend/sync/analysis_refresh.py:AnalysisRefreshService.refresh`; `tests/test_training_report.py:test_get_authentication_precedes_analysis_reads`, `tests/test_training_report.py:test_analysis_refresh_rejects_unknown_area`, `tests/test_analysis_refresh.py:test_both_sources_refresh_and_a_failed_wahoo_read_is_partial`, `tests/test_analysis_refresh.py:test_a_failed_garmin_read_is_reported_as_not_refreshed`. `tests/test_http_sync_get_routes.py:test_authentication_precedes_every_detail_read`, `tests/test_detail_envelope.py:test_refresh_is_offered_for_configured_detail_providers_only`, and `e2e/activity-details.spec.js` ("Garmin-only session shows per-provider notes and its own refresh").

### Requirement: Session-owned effective feedback
Feedback and equipment assignments SHALL be stored under the local session they were written for, stay with it when a bundle is split, and be read through the live session across provider imports. Each session SHALL expose one effective feedback and one effective sRPE contribution. Rows stored under a provider record id of the session SHALL still be found; the session-id row wins, conflicting legacy feedback stays recoverable, and heuristic similarity alone SHALL not combine athlete feedback.

#### Scenario: Same session through two providers
- **WHEN** two provider activities are confirmed copies of one session and feedback is saved through either supported reference
- **THEN** reads expose the same effective feedback and session-RPE is counted once.

#### Scenario: Feedback stored under a provider record id
- **WHEN** feedback or an equipment assignment was stored under a provider record id of a session (before sessions were stored, or under an Intervals.icu record id)
- **THEN** every reader (detail, load rollups, block review, training report, equipment usage) finds it for the session, and a row under the session id wins over it.

#### Scenario: Legacy row without a session
- **WHEN** a feedback row has no stored session and its id names exactly one record (of its provider, when set)
- **THEN** it joins that session's group for reads, edits and clearing; an id that names records of several sessions stays standalone, and an edit moves the effective row to the session id instead of adding one.

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
Every completed-activity object that the HTTP API returns SHALL carry provider-neutral keys, and SHALL NOT carry the former Intervals.icu activity keys. Values SHALL be unchanged. Local planning records already carry the provider-neutral `starts_at_local` and `planned_duration_s` and receive only the metric renames.

#### Scenario: Activity list row
- **WHEN** `/api/activities` returns a session
- **THEN** it is the session summary with `id`, `started_at`, `started_at_local`, `sport`, `environment`, `record_ids` and the neutral metric names such as `moving_duration_s`, `distance_m` and `training_load`, and none of `start_date_local`, `moving_time`, `type`, `local_activity_id` or `icu_*` is present.

#### Scenario: Calendar actual activity
- **WHEN** `/api/bootstrap` or `/api/plan` returns, in `training_calendar`, `planned`, `calendar` or `planning_view.items`, a completed-activity calendar entry or a planned unit matched to an activity
- **THEN** the completed entry and `compliance.actual_activity` use the neutral keys. The planned unit keeps its own `starts_at_local` and `planned_duration_s` unchanged, and its `icu_training_load` appears as `training_load`.

#### Scenario: Neutral value already present
- **WHEN** a stored row carries both a provider key and its neutral counterpart, such as `icu_weighted_avg_watts` and `normalized_power`
- **THEN** the neutral value wins and the provider key is dropped.

#### Scenario: Browser shows unchanged values
- **WHEN** the activity analysis list renders a session summary, including one with `sport` `ride` and `environment` `virtual`, and the calendar renders its completed and matched entries
- **THEN** they show the same dates, durations, distances, heart rate, power and load as the summary, and the indoor ride is labelled "Rad indoor".

Detailed contract: the calendar key map is the activity map in `backend/canonical/public_metrics.py`. A neutral key that is already present wins. `weighted_average_watts` stays separate from `normalized_power`. The activity detail document (`/api/activities/{id}`) is already neutral and stays unchanged. The provider-coupling guard rejects an import of a provider field-name module outside the provider, sync and canonical packages, except for the explained owners in its allowlist.

Evidence: `backend/canonical/public_metrics.py:neutral_activity`, `backend/canonical/public_metrics.py:neutral_calendar_state`, `backend/activities/read_service.py:ActivityReadService.page`, `backend/http_api/public_plan.py:PublicPlanStateService.read_public`, `public/activity-analysis.js`, `public/performance-view.js`, `public/plan-views.js`; `tests/test_canonical_public_metrics.py:NeutralPublicMetricsTests`, `tests/test_activity_canonical_reads.py:test_list_rows_carry_neutral_names_only`, `tests/plan-views-sport-label.test.cjs`, `tests/test_provider_coupling_guard.py:OwnerReadGuardTests.test_consumers_cannot_import_provider_field_name_modules`; `e2e/contracts.spec.js`, `e2e/activity-details.spec.js`.

### Requirement: Session RPE rating time and session load in the detail
The system SHALL store when the athlete last set a feedback row's session RPE, keep it while the RPE stays the same and clear it with the RPE; ratings stored before schema v18 SHALL keep an unknown rating time. The activity detail document SHALL carry the session's session-RPE load, and the PWA SHALL offer the RPE as a 0–10 half-point selection with the CR-10 anchors.

#### Scenario: Rating time follows the RPE
- **WHEN** the athlete saves a new RPE, then saves only notes, then clears the RPE
- **THEN** the rating time is set, kept, then cleared; undo restores the recorded rating time with the row.

#### Scenario: Detail shows the load
- **WHEN** the activity detail of a session with local RPE 6.5 and 62 elapsed minutes is opened or its feedback is saved
- **THEN** it shows `Session-RPE-Last: 403 AU · RPE 6,5 (Athletenfeedback) × 62 min`; a session without a summary shows no load line.

Evidence: `backend/db/repositories.py:ActivityFeedbackRepository.upsert`, `backend/performance/detail_envelope.py:DetailEnvelopeReader`, `public/activity-details.js:rpeSelect`; `tests/test_activity_feedback.py::test_rating_time_is_recorded_only_on_an_rpe_change`, `tests/test_detail_envelope.py`, `e2e/activity-details.spec.js`.

### Requirement: One activity list entry per canonical session
The activity list (`GET /api/activities`) and the Coach tool `list_recent_activities` SHALL list each live canonical session exactly once, from every provider, as its session summary keyed by the local session id, newest first. Paging SHALL use a version-3 keyset cursor; any other cursor SHALL restart at page one. Rows SHALL carry no `detail_error`: Intervals.icu details are never served (#1685), so their failure notes mark no session.

#### Scenario: Sessions from several providers
- **WHEN** the tables hold a Garmin-only session, a Wahoo-only session, a bundled Garmin and Wahoo session and, in a database that still holds stored Intervals.icu rows, Intervals.icu-only sessions or an Intervals.icu duplicate pair bundled into one session
- **THEN** the list and the Coach tool contain each session once under its `act_` id, the Garmin-only session included, and paging with limit 1 walks all of them in the same order.

#### Scenario: Older cursor
- **WHEN** a client sends a version-2 cursor
- **THEN** the first page is returned.

#### Scenario: Intervals.icu failure note
- **WHEN** a listed session's Intervals.icu record has a stored detail failure note
- **THEN** the row carries no `detail_error`.

Evidence: `backend/activities/read_service.py:ActivityReadService.page`, `backend/activities/read_service.py:ActivityReadService.recent`; `tests/test_activity_canonical_reads.py:test_read_service_lists_nothing_until_the_tables_serve`, `tests/test_activity_canonical_reads.py:test_limit_one_pages_walk_every_session_and_old_cursors_restart`, `tests/test_activity_canonical_reads.py:test_garmin_only_session_is_listed_and_its_detail_loads`, `e2e/activity-details.spec.js::@responsive analysis lists a Garmin-only indoor session and loads more`.

### Requirement: Summary fingerprints from one sync-owned port
Freshness checks outside the sync owner SHALL read current summary fingerprints only through the `summary_fingerprints` port, for the requested activities only. Providers SHALL use the payload hash of the active raw record. Intervals.icu is an output target, so its stored rows have no fingerprint and the port returns none for them.

#### Scenario: Stored fingerprints stay valid
- **WHEN** the port reads fingerprints for a Garmin record, a missing record and a stored Intervals.icu activity of a database restored from an earlier release
- **THEN** only the Garmin value is returned and it equals its record's payload hash, so no stored detail, analysis or profile becomes stale.

Evidence: `backend/sync/canonical_table_reader.py:CanonicalTableReader.summary_fingerprints`; `tests/test_activity_canonical_reads.py:test_fingerprints_are_the_payload_hash_and_intervals_has_none`, `tests/test_canonical_detail_reader.py:CanonicalDetailStatusTests`.
