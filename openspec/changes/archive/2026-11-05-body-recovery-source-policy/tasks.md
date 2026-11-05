# Tasks

## 1. Policy

- [x] 1.1 Add the recency rule for weight and body fat and the method family with relay detection to the source policy, with bounds in the daily rules; verify with `tests/test_source_policy.py`.
- [x] 1.2 Resolve current weight and body fat with Garmin's dated measurements; verify `tests/test_performance_current_metrics.py` and `tests/test_characterization_current_metrics.py`.
- [x] 1.3 Use the method family for current recovery values, averages and planning days, labelling relays; verify `tests/test_performance_recovery_context.py` and `tests/test_planning_canonical_recovery.py`.
- [x] 1.4 Derive the body and recovery display preferences from the policy; verify `tests/test_performance_display_sources.py`.

## 2. Integration

- [x] 2.1 Run the selected checks, repo-wide mypy and strict OpenSpec validation, recording unavailable checks as evidence gaps.
