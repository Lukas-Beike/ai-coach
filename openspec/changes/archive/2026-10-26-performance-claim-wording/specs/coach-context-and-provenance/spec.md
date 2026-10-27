## MODIFIED Requirements

### Requirement: CP7 Bounded local reads and analysis parity
The system SHALL provide read-only tools for exact local records and deterministic analysis without treating tool reads as permission to write.

#### Scenario: Recent and exact activity reads
- **WHEN** the Coach requests recent activities or one exact activity's detail by local or provider ID
- **THEN** it receives the bounded local recent view or sanitized exact-activity analysis; ordinary recent reads do not refresh the provider.

#### Scenario: Selected deterministic report
- **WHEN** `get_training_report` requests supported report, endurance, power-profile, tag-impact, season, comparison, body-history or sleep-timing-variability (`sleep_timing_variability`) sections
- **THEN** the tool uses the corresponding local analysis owners, bounds the combined result and reports completeness.

#### Scenario: Invalid report or missing owner
- **WHEN** unsupported sections (including the retired section name `sleep_regularity`), invalid list parameters or unavailable report services are requested
- **THEN** the system returns a validation/unavailable error rather than a misleading empty successful report.

#### Scenario: Recovery reads carry their limits
- **WHEN** the Coach receives the personal recovery comparison, sleep goal shortfall or sleep timing variability through the context or `get_training_report`
- **THEN** the supplied note and the tool description state that quartile positions compare the athlete's own earlier values, that sleep timing variability is not the Sleep Regularity Index, and that an isolated deviation gives no diagnosis, training clearance or training change; the Coach prompt needs no additional rule for this.

Evidence: `backend/coach/activity_read_tools.py:CoachActivityReadToolService.execute`; `backend/coach/read_tools.py:CoachReadToolService._execute_domain_read`; `backend/coach/tool_schemas.py` (`get_training_report`); `backend/coach/context.py:coach_performance_projection`; `tests/test_coach_read_tools.py:test_dispatches_every_read_tool_and_projects_existing_shapes`, `tests/test_coach_read_tools.py:test_invalid_limits_keep_bad_request_reason`; `tests/test_coach_tool_coverage.py:test_training_report_returns_same_local_facts_without_mutation`; `tests/test_coach_activity_read_tools.py:test_detail_uses_local_sources_and_keeps_sanitized_detail_projection`, `tests/test_coach_activity_read_tools.py:test_report_can_select_comparisons_and_rejects_unknown_section`, `tests/test_coach_activity_read_tools.py:test_report_can_select_body_history_and_sleep_timing_variability`; `tests/test_personal_recovery_coach_cases.py`.
