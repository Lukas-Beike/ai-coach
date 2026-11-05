## MODIFIED Requirements

### Requirement: Metric-specific source priority and local authority
The system SHALL apply per-metric source rules rather than a universal provider order. A locally confirmed zone configuration precedes every provider for thresholds. Current ride FTP prefers the athlete-maintained Intervals.icu setting before Garmin, with Wahoo last; threshold and maximum heart rate, threshold pace and run power prefer Garmin before Intervals.icu. VO2max prefers Garmin. Current weight and body fat are the most recent dated measurement across Garmin and Intervals.icu wellness; within one day of the newest one a device measurement precedes a provider report, which precedes a local entry, and the undated Intervals.icu athlete record, the manual profile value and Wahoo's profile weight are fallbacks in that order.

#### Scenario: Three FTP sources
- **WHEN** eligible Intervals, Garmin, and Wahoo cycling FTP values coexist and no local zone configuration applies
- **THEN** current metric composition selects the Intervals.icu setting, labels its provider, lists the Garmin and Wahoo values as alternatives with a conflict flag above 3 %, and retains the other provider observations for their supported reads.

#### Scenario: Old Wahoo fallback
- **WHEN** Wahoo is the only eligible source but its dated value is older than the current-value age limit
- **THEN** the current selector returns no Wahoo value while historical storage remains intact.

#### Scenario: Stale threshold sources
- **WHEN** the Intervals.icu sync is older than 30 days or a Garmin threshold was observed more than 180 days before the local day
- **THEN** that value is not current and the next source in the rule's order supplies the threshold.

#### Scenario: A newer scale reading via Intervals.icu
- **WHEN** Intervals.icu wellness holds today's weight and Garmin's newest weight is three days old
- **THEN** the current weight is the Intervals.icu value, Garmin's stays an alternative, and a difference above 1.5 kg sets the conflict flag; were Garmin's measurement from yesterday, the Garmin device measurement would win.

Detailed contract: Body fat follows the weight rule with a 2-percentage-point conflict tolerance; readiness prefers Intervals over Garmin; sleep, RMSSD, and resting HR follow their method family (performance-and-readiness); CTL/ATL remain Intervals-owned. Wahoo current FTP/weight older than 90 days SHALL be excluded when an as-of local day is supplied, without deleting history. The PWA display preference of weight, body fat, sleep, HRV, resting HR, threshold pace, VO2max and eFTP is the first provider of that metric's rule; FTP and W/kg charts keep Garmin, whose FTP history they draw. Local profile and competition records SHALL retain their domain authority rather than being overwritten by provider read sync.

Evidence: `backend/performance/source_policy.py:CURRENT_RULES`, `backend/performance/source_policy.py:resolve_candidates`, `backend/performance/current_thresholds.py:resolve_current_thresholds`, `backend/performance/display_sources.py:PREFERRED_PROVIDER`, `backend/performance/current_metrics.py:current_performance_metrics`, `backend/sync/authority.py:PlanningAuthorityService`; `tests/test_current_thresholds.py`, `tests/test_source_policy.py:RecencyResolutionTests`, `tests/test_performance_current_metrics.py:test_intervals_ftp_beats_garmin_and_wahoo_ftp`, `tests/test_performance_current_metrics.py:test_manual_profile_weight_beats_wahoo_weight`, `tests/test_performance_display_sources.py`, `tests/test_sync_authority.py:test_revision_failure_rolls_back_planning_update_atomically`.
