# Tasks

## 1. Method

- [x] 1.1 Write and release evidence card M6 with the literature check and an independent review; verify `tests/test_performance_method_cards.py`.
- [x] 1.2 Implement the three branches and dated thresholds in `backend/performance/local_tss.py`; verify hand-worked examples in `tests/test_local_tss.py`.

## 2. Storage and serving

- [x] 2.1 Store, recompute and retire the derived observations in the local load stage and serve them on summaries; verify `tests/test_local_load_store.py`.
- [x] 2.2 Trigger the stage after completed sync jobs and committed local zone changes; verify `tests/test_sync_executor.py` and `tests/test_zone_configuration_canonical.py`.
- [x] 2.3 Map Garmin `avgGradeAdjustedSpeed` (mapper v15) and re-pin `tests/test_mapper_version_guard.py`.

## 3. Integration

- [x] 3.1 Run the selected checks, repo-wide mypy and strict OpenSpec validation, recording unavailable checks as evidence gaps.
