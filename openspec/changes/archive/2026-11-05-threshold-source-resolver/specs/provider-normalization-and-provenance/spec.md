## MODIFIED Requirements

### Requirement: Metric-specific source priority and local authority
The system SHALL apply per-metric source rules rather than a universal provider order. A locally confirmed zone configuration precedes every provider for thresholds. Current ride FTP prefers the athlete-maintained Intervals.icu setting before Garmin, with Wahoo last; threshold and maximum heart rate, threshold pace and run power prefer Garmin before Intervals.icu. Current weight and VO2max prefer Garmin; manual profile weight precedes Wahoo fallback.

#### Scenario: Three FTP sources
- **WHEN** eligible Intervals, Garmin, and Wahoo cycling FTP values coexist and no local zone configuration applies
- **THEN** current metric composition selects the Intervals.icu setting, labels its provider, lists the Garmin and Wahoo values as alternatives with a conflict flag above 3 %, and retains the other provider observations for their supported reads.

#### Scenario: Old Wahoo fallback
- **WHEN** Wahoo is the only eligible source but its dated value is older than the current-value age limit
- **THEN** the current selector returns no Wahoo value while historical storage remains intact.

#### Scenario: Stale threshold sources
- **WHEN** the Intervals.icu sync is older than 30 days or a Garmin threshold was observed more than 180 days before the local day
- **THEN** that value is not current and the next source in the rule's order supplies the threshold.

Detailed contract: Body-fat current composition uses Intervals and manual profile paths; readiness prefers Intervals over Garmin; sleep, RMSSD, and resting HR prefer eligible Garmin readings; CTL/ATL remain Intervals-owned. Wahoo current FTP/weight older than 90 days SHALL be excluded when an as-of local day is supplied, without deleting history. The PWA display preference per metric is the first provider of that metric's rule. Local profile and competition records SHALL retain their domain authority rather than being overwritten by provider read sync.

Evidence: `backend/performance/source_policy.py:CURRENT_RULES`, `backend/performance/source_policy.py:resolve_candidates`, `backend/performance/current_thresholds.py:resolve_current_thresholds`, `backend/performance/display_sources.py:PREFERRED_PROVIDER`, `backend/performance/current_metrics.py:current_performance_metrics`, `backend/sync/authority.py:PlanningAuthorityService`; `tests/test_current_thresholds.py`, `tests/test_performance_current_metrics.py:test_intervals_ftp_beats_garmin_and_wahoo_ftp`, `tests/test_performance_current_metrics.py:test_manual_profile_weight_beats_wahoo_weight`, `tests/test_performance_display_sources.py`, `tests/test_sync_authority.py:test_revision_failure_rolls_back_planning_update_atomically`.
