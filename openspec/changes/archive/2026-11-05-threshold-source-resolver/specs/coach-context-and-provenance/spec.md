## ADDED Requirements

### Requirement: Coach and plan share the resolved thresholds
The system SHALL give the Coach context the same current FTP, threshold heart rate and maximum heart rate that plan zones and planned loads use on that day, resolved by one source policy. The Coach thresholds SHALL name the FTP source and, when another source holds a different current FTP, list it as an alternative with a conflict flag.

#### Scenario: Garmin and Intervals.icu FTP differ
- **WHEN** Garmin reports 280 W, the Intervals.icu setting is 265 W and no local zone configuration applies
- **THEN** `thresholds.ftp_w` is 265 with `ftp_source` Intervals.icu, `ftp_alternatives` lists Garmin 280 W, `ftp_conflict` is true, and planned loads and zones use 265 W.

#### Scenario: Local zone configuration
- **WHEN** the athlete has a confirmed local power zone configuration in effect today
- **THEN** both the Coach thresholds and the plan use its FTP, labelled as local.

Detailed contract: the plan playbook tells the Coach to use these thresholds for targets and to name a flagged conflict once. Each current metric with other current sources carries `alternatives` (value, source label, provider id) and `conflict`.

Evidence: `backend/performance/current_metrics.py:coach_thresholds`, `backend/performance/canonical_current.py:read_current_inputs`, `backend/planning/load_checks.py:load_thresholds`, `backend/coach/playbooks.py:_THRESHOLDS`; `tests/test_current_thresholds.py:CoachAndPlanParityTests`.
