# Spec Delta

## ADDED Requirements

### Requirement: Canonical sleep regularity parity
Sleep timing regularity SHALL read canonical periods without traversing raw provider payloads. Equivalent synthetic periods SHALL preserve the existing sleep-regularity-v1 results, source separation and coverage before any intentional method change. Nightly bounds SHALL not be labelled as a complete sleep/wake series or original SRI.

#### Scenario: Equivalent stored nights
- **WHEN** equivalent synthetic nights are supplied through canonical periods rather than the previous provider aliases
- **THEN** regularity values, method identity and coverage match the existing method.

#### Scenario: Sparse coverage
- **WHEN** missing nights or overlapping provider periods exist
- **THEN** those distinctions remain explicit and the result does not claim original SRI or fabricate full-day coverage.

### Requirement: Canonical retained provider performance reads
Affected history, recovery, nutrition and Coach reads SHALL obtain retained provider status, load balance, tolerance, score details, performance history, Body Battery, stress, resting energy and subjective wellness from canonical data. Provider labels, dates and missing-value semantics SHALL survive without a snapshot dependency in these paths.

#### Scenario: Canonical data without snapshot
- **WHEN** retained canonical provider data is available and provider views/snapshots are absent
- **THEN** affected read surfaces remain available with their supported values, dates and source labels.

#### Scenario: Proprietary score absent
- **WHEN** a proprietary provider score is not recorded
- **THEN** it remains unknown and no local recreation is substituted.

Evidence baseline: `backend/performance/personal_recovery.py`, `backend/performance/canonical_personal_recovery.py`, `backend/performance/chart_history.py`, `backend/performance/garmin_projection.py`; `tests/test_personal_recovery.py`, `tests/test_performance_chart_history.py`. Canonical-only reads and parity require new regression evidence.
