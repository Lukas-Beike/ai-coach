## MODIFIED Requirements

### Requirement: Provider-neutral session detail document
The system SHALL assemble an `activity_detail.v1` document for a canonical session with session identity, metrics, streams, laps, zones, analysis, feedback/equipment envelope, and per-provider detail state, and SHALL serve that document as the only session detail contract of the authenticated HTTP detail route, the Coach `get_activity_details` tool, and the PWA detail views. Measured metrics SHALL prefer the recorder's own copy and preserve alternatives; derived metrics SHALL identify source and load model. Missing values SHALL remain absent rather than becoming zeros. Every `source` object SHALL carry an additive `recorded_by` field naming the recording device from the record provenance, and the response `data_scope` SHALL name the contributing provider(s) and the recording device instead of a fixed provider. A local session id of any provider session, including Garmin-only and Wahoo-only sessions, SHALL resolve through the same read path.

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

Detailed contract: Detail status SHALL expose available kinds, refreshability, stale/load-error metadata, and coverage. The PWA SHALL render only from the served document and SHALL derive its refresh offer from `detail_data.providers[]` entries rather than from an Intervals-only activity check. Frontend asset query versions and the service-worker cache name SHALL change together with the contract.

Evidence: `backend/activities/detail_contract.py:activity_detail_contract`, `backend/performance/canonical_detail.py:CanonicalDetailReader`; `tests/test_activity_detail_contract.py:test_document_has_the_contract_sections`, `tests/test_activity_detail_contract.py:test_recorders_own_copy_provides_the_measured_value_and_others_are_alternatives`, `tests/test_activity_detail_contract.py:test_status_adds_stale_load_error_and_coverage_per_provider`. Missing evidence (planned in this change): production wiring in `backend/http_api/activity_assembly.py`, HTTP/Coach/PWA consumers, the `recorded_by` field, provider-neutral `data_scope`, and parity tests for synthetic Intervals, Garmin and Wahoo/FIT sessions plus `e2e/activity-details.spec.js` on all five Playwright projects.

### Requirement: Current cached analysis and truthful freshness
The system SHALL read local details without implicit provider refresh and compare each provider's stored canonical detail fingerprint with that provider's current summary fingerprint. Session scalars SHALL come from the current summary row. Intervals.icu zone times SHALL come from the current summary row when present, outside the fingerprint. The reader SHALL recompute analysis from merged canonical detail streams and SHALL withhold that analysis while a provider contributing streams or laps is stale. Detail failures SHALL preserve usable summaries and matching load-error metadata.

#### Scenario: Summary corrected after analysis
- **WHEN** the Intervals.icu summary fingerprint no longer matches the fingerprint stored with that record's canonical detail sets
- **THEN** that provider entry reports `stale: true`, `analysis` is null, and the session metrics show the current summary values rather than values cached with the older detail.

#### Scenario: Valid old activity
- **WHEN** a local activity lies outside the recent performance-input window
- **THEN** detail lookup may consult full local history in the same read snapshot rather than returning a false not-found result.

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

Detailed contract: Analysis aggregation for reports and calendar profiles SHALL read only canonical analysis rows whose stored fingerprint matches current activity data; no kv detail fallback is read. Analyses retained only in unverifiable kv records are no longer displayed but remain stored. Old known activities are resolvable beyond the recent performance window.

Evidence: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/canonical_detail.py:CanonicalDetailReader.read`; `tests/test_activity_read_service.py:test_detail_reads_an_activity_older_than_the_performance_window`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_canonical_detail_reader.py:test_analysis_is_recomputed_from_the_merged_streams`. Intended behavior change: `tests/test_characterization_activity_reads.py:test_changed_provider_summary_marks_record_stale_and_hides_analysis` currently pins cached stale scalars and SHALL be updated to the current summary values. Missing evidence (planned): live-zone and stale-withholding tests for the canonical reader, and removal of `backend/db/activity_analysis_reads.py:recent_kv_analyses`.

### Requirement: Authenticated analysis and scoped refresh
The system SHALL require authentication for local activity/analysis reads, including the session detail document, and preserve the POST authentication/CSRF boundary for feedback and refresh actions. Analysis refresh SHALL accept only load, performance, recovery, or sessions, with optional 14/84-day periods only for load/recovery, and refresh the selected bounded sources. Session detail reads SHALL never trigger provider requests; detail loading SHALL happen only through the explicit authenticated activity-detail job for a provider that supports it.

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

Evidence: `backend/http_api/analysis.py:AnalysisRoutes`, `backend/http_api/sync_get.py:SyncGetRoutes`, `backend/http_api/feedback_post.py:FeedbackPostRoutes`, `backend/sync/analysis_refresh.py:AnalysisRefreshService.refresh`; `tests/test_training_report.py:test_get_authentication_precedes_analysis_reads`, `tests/test_training_report.py:test_analysis_refresh_rejects_unknown_area`, `tests/test_analysis_refresh.py:test_failed_provider_does_not_discard_other_fresh_results`. Missing evidence (planned): an authentication-first test for the v1 detail route, and a Playwright check that the refresh offer follows `detail_data.providers[]`.
