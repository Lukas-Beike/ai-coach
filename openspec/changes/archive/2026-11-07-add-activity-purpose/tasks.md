## 1. Implementation

- [x] 1.1 Add `ActivityPurpose`, the record field and its details persistence
- [x] 1.2 Map Garmin `eventType.typeKey` in mapper v17 and re-pin the mapper guard
- [x] 1.3 Session purpose precedence and on-read competition link in the canonical reader
- [x] 1.4 Coach activity list carries purpose, competition id and German label

## 2. Validation

- [x] 2.1 Focused tests (`tests/test_session_purpose.py`, mapper guard, Garmin mapping, Coach parity) and `python tests/run_tests.py --changed`
- [x] 2.2 Scoped evidence review against the sanitized Garmin list payloads (SDK and Personal API carry `eventType.typeKey`)
- [x] 2.3 `npm run openspec -- validate add-activity-purpose --strict`
