# Tasks

## 1. Preference

- [x] 1.1 Add the preference groups to the source policy (order, recency, method family, display); verify `tests/test_source_policy.py:PreferredSourceTests` and `tests/test_performance_display_sources.py`.
- [x] 1.2 Store the preferences as validated profile fields with audit history; verify `tests/test_athlete_profile.py` and `tests/test_change_history.py`.
- [x] 1.3 Read the preferences in every consumer's unit of work; verify `tests/test_current_thresholds.py:PreferredSourceTests` and the selected checks.
- [x] 1.4 Add the profile form fieldset; verify `tests/test_server_frontend.py`.

## 2. Integration

- [x] 2.1 Run the selected checks, Node tests, repo-wide mypy and strict OpenSpec validation, recording unavailable checks as evidence gaps.
