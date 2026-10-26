# Spec Delta

## ADDED Requirements

### Requirement: Reproducible observation metadata
Canonical observations SHALL round-trip optional method, aggregation, method version, input fingerprint and observation-period metadata. Derived observations MUST supply a method, version and input fingerprint. Numeric and categorical provider values SHALL remain distinct, validated values.

#### Scenario: Metadata survives storage
- **WHEN** a valid observation with method metadata and a bounded period is stored and read again
- **THEN** its value, source, method, version, aggregation, fingerprint and period remain unchanged.

#### Scenario: Incomplete derived record
- **WHEN** a derived observation lacks its method, version or input fingerprint
- **THEN** validation rejects it before persistence.

#### Scenario: Mapper method correction
- **WHEN** stored provider records are reprojected by a newer mapper
- **THEN** provider-fixed HRV method and aggregation metadata are populated without refetching or changing displayed measurements and labels; obsolete projections do not appear current.

### Requirement: Canonical sleep periods
Canonical sleep periods SHALL retain aware UTC start/end, the timezone used, local wake date, night/unknown kind, reported duration and provenance. Invalid or reversed periods SHALL be rejected. Periods from different providers SHALL remain separate.

#### Scenario: Midnight and DST
- **WHEN** a valid period crosses midnight or a DST transition
- **THEN** its instants preserve actual duration and its assigned date is the wake date in the recorded timezone.

#### Scenario: Missing nights and overlapping providers
- **WHEN** nights are missing or two providers overlap
- **THEN** no missing night is fabricated and provider periods are not silently merged.

#### Scenario: Garmin main sleep during daytime
- **WHEN** Garmin identifies a period as its main daily sleep episode, including daytime sleep for a shift worker
- **THEN** its canonical kind is NIGHT, meaning main sleep rather than a clock-night classification; arbitrary periods are not classified by hour or duration.


### Requirement: Explicit measurement context and continuity
Observations and activities SHALL preserve supported device model, firmware, algorithm, sensor, measurement window and protocol, explicitly representing unavailable context as unknown. Canonical readers SHALL expose a deterministic context identity so downstream consumers can identify changes. Context SHALL not infer device or protocol from the provider brand or expose device serials.

#### Scenario: Device changes mid-series
- **WHEN** two otherwise comparable observations have different known device or measurement context
- **THEN** their canonical context identities differ and the continuity break is visible to readers.

#### Scenario: Provider omits context
- **WHEN** a payload omits device or protocol information
- **THEN** reads report unknown context rather than a guessed device, sensor or protocol.

#### Scenario: Known measurement semantics without hardware attribution
- **WHEN** Garmin last-night HRV supplies the established RMSSD measurement but no trustworthy measurement-associated hardware fields
- **THEN** canonical metadata preserves the RMSSD method and overnight window while device model, firmware and sensor remain explicitly unknown; inventories and primary-device selection do not fill those fields.

### Requirement: Canonical sport zone configuration
Canonical zone configuration SHALL retain sport, metric, boundaries in canonical units, model, source and validity date. Provider and confirmed local configurations SHALL remain separately readable. Effective selections SHALL prefer applicable confirmed local values and SHALL never promote CP/CS into FTP, lactate threshold or zone-2 boundaries automatically.

#### Scenario: Canonical-only calendar and plan
- **WHEN** canonical zones exist without a provider snapshot
- **THEN** calendar, plan and affected time-in-zone calculations use those boundaries and retain source labels.

#### Scenario: Local configuration and provider refresh
- **WHEN** provider zones are refreshed after a confirmed local edit
- **THEN** local values retain authority and the refreshed provider alternative remains available separately.

### Requirement: Retained provider domains and equipment links
Training status and load balance, running tolerance, readiness history, endurance score details/history, performance history, Body Battery, stress, resting energy, subjective provider wellness and equipment SHALL have canonical representations. Their affected consumers SHALL read canonical values with provider labels. Proprietary scores SHALL not be rebuilt locally; equipment links SHALL resolve to canonical sessions.

#### Scenario: Stored provider-only history
- **WHEN** existing provider records contain supported retained domains
- **THEN** local reprojection makes them available to canonical readers and affected consumers without network access or backdating current values.

#### Scenario: Provider resting energy
- **WHEN** a provider reports resting energy
- **THEN** it remains a labelled provider observation; absence does not trigger an unrequested local estimate.

#### Scenario: Garmin daily physiological stress
- **WHEN** an existing daily summary reports nested stress.avgLevel or flat averageStressLevel
- **THEN** canonical STRESS retains the daily provider mean, source date and established field precedence on the 0-100 scale, including valid zero, without a second stress fetch or substitution from subjective stress; missing or invalid values do not become measurements.

#### Scenario: Gear on duplicate imports
- **WHEN** provider gear links refer to copies of the same canonical session
- **THEN** equipment reads resolve those links through session identity without duplicating usage or overriding an explicit local assignment.

### Requirement: Metric vocabulary accountability
Every metric kind SHALL have an implemented provider producer or a documented local method and a consumer or explicit export-only retention purpose. Retiring a kind SHALL preserve or migrate stored observations. Provider load-model vocabulary SHALL remain separate from local session-RPE methods.

#### Scenario: Unsupported vocabulary addition
- **WHEN** a kind is added without a producer/method or consumer/retention purpose
- **THEN** the vocabulary consistency check fails.

## MODIFIED Requirements

### Requirement: Provenance and incomplete coverage remain visible
The system SHALL expose source labels, observation dates, retrieval freshness, and missing or unsupported coverage without synthesizing measurements. Canonically mapped Garmin status, load balance and Body Battery SHALL retain provider-estimate labels, their supported measurement windows and explicit partial coverage.

#### Scenario: Source not canonically supported
- **WHEN** a stored Garmin section contains an unsupported field
- **THEN** coverage records the limitation and consumers do not advertise complete support for that field.

#### Scenario: Derived value displayed
- **WHEN** a detail average is calculated from samples or a load value carries a provider calculation
- **THEN** its public document includes the corresponding source and kind/model rather than presenting it as an athlete-entered measurement.

Detailed contract: Public metric names SHALL be provider-neutral while source labels identify origin, derived values, and AI estimates when present.

Evidence baseline: `backend/canonical/records.py`, `backend/db/canonical_store.py`, `backend/providers/canonical_plans.py`, `backend/sync/canonical_table_reader.py`, `backend/activities/zone_settings.py`; tests in `tests/test_canonical_records.py`, `tests/test_canonical_store.py`, `tests/test_garmin_health_mapping.py`. The added behavior requires new implementation and regression evidence.
