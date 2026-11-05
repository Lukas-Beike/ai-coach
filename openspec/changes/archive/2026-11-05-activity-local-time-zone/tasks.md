# Tasks

## 1. Activity offset

- [x] 1.1 Add `local_offset_minutes` to `ActivityRecord` with quarter-hour and +-14 h validation and the time helpers in `backend/canonical/local_time.py`; verify `tests/test_activity_local_offset.py:OffsetHelperTests`.
- [x] 1.2 Map the offset in the Garmin, Intervals.icu and Wahoo activity mappers and bump their versions; verify the mapper tests and `tests/test_activity_local_offset.py:ActivityDateTests`.
- [x] 1.3 Date activities, sessions and summaries by the offset and keep it in the stored details; verify `tests/test_activity_local_offset.py:SummaryTests` and `test_the_offset_survives_the_stored_details`.

## 2. Sleep day

- [x] 2.1 Date sleep periods by the provider day and bump the Garmin health and Intervals.icu wellness mapper versions; verify `tests/test_activity_local_offset.py:TravelDaySleepTests` and `tests/test_sleep_period_mapping.py`.

## 3. Integration

- [x] 3.1 Run the selected checks, repo-wide mypy and strict OpenSpec validation, recording unavailable checks as evidence gaps.
