## MODIFIED Requirements

### Requirement: Current cached analysis and truthful freshness
The system SHALL read local details without implicit provider refresh and compare each provider's stored canonical detail fingerprint with that provider's current summary fingerprint. The reader SHALL recompute analysis from merged canonical detail streams and SHALL withhold it while a provider contributing streams or laps is stale. Detail failures SHALL preserve usable summaries and matching load-error metadata. The current summary row of a session SHALL be found in the canonical activity rows only; the stored snapshot SHALL NOT be a lookup source.

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

Detailed contract: Session scalars SHALL come from the current summary row. Intervals.icu zone times SHALL come from the current summary row when present, outside the fingerprint. Analysis aggregation for reports and calendar profiles SHALL read only canonical analysis rows whose stored fingerprint matches current activity data; no kv detail fallback is read. Analyses retained only in unverifiable kv records are no longer displayed but remain stored. Old known activities are resolvable beyond the recent performance window. The analysis read service requires its canonical source at construction.

Evidence: `backend/performance/activity_read_service.py:ActivityAnalysisReadService.detail`, `backend/performance/report_service.py:TrainingRecordsService.observations`, `backend/performance/canonical_detail.py:CanonicalDetailReader.read`; `tests/test_activity_read_service.py:test_detail_reads_an_activity_older_than_the_performance_window`, `tests/test_activity_read_service.py:test_page_keeps_activities_with_failed_details_and_names_the_error`, `tests/test_canonical_detail_reader.py:test_analysis_is_recomputed_from_the_merged_streams`. `tests/test_canonical_detail_reader.py:test_live_zone_times_replace_stored_zones_without_marking_stale`, `tests/test_canonical_detail_reader.py:test_stale_provider_withholds_analysis_and_shows_current_scalars`, `tests/test_canonical_detail_reader.py:test_set_without_a_fingerprint_is_never_stale`, `tests/test_characterization_activity_reads.py:test_changed_provider_summary_marks_record_stale_and_hides_analysis`. Missing evidence (planned in this change): lookup with a snapshot that has no activity rows and construction without a canonical source.
