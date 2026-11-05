# Tasks

## 1. Reads

- [x] 1.1 Serve the activity list and `list_recent_activities` from session summaries with a version-3 keyset cursor; verify with `tests/test_activity_canonical_reads.py` and `tests/test_activity_read_service.py`.
- [x] 1.2 Add the `summary_fingerprints` port and move the detail, training-record, power-profile and calendar-profile freshness checks to it; verify unchanged Intervals.icu fingerprint values on a populated fixture.
- [x] 1.3 Check feedback saves against live canonical sessions; verify with `tests/test_activity_feedback.py`.
- [x] 1.4 Read equipment usage, maintenance, assignment and Garmin gear links from session summaries; verify with `tests/test_equipment_canonical_sessions.py`.
- [x] 1.5 Rename the raw-row read to `intervals_activity_payloads` and guard it to `backend/sync/`; verify with `tests/test_provider_coupling_guard.py`.

## 2. Browser

- [x] 2.1 Label list rows from `sport`/`environment`, update asset versions, and cover a Garmin-only indoor session with load-more in `e2e/activity-details.spec.js`.

## 3. Integration

- [x] 3.1 Run the selected checks and strict OpenSpec validation, recording unavailable checks as evidence gaps.

## Evidence gaps

- Playwright was not run locally (it needs the Docker runtime); CI runs every browser project on the PR.
