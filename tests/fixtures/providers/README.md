# Synthetic provider wire fixtures

These JSON files show the wire shapes that Intervals.icu and Garmin Connect
deliver today, so provider compaction and collection code can be tested
without a live account.

## Provenance and privacy

- Every value is invented. Athlete, activity, event and gear names start with
  `Synthetic`; IDs, dates, distances and metrics are plausible but not taken
  from any real athlete.
- No file holds a credential, token, cookie, password, database key, real
  email address or real device serial. `tests/test_provider_wire_fixtures.py`
  enforces the key and email rules.
- Do not replace these files with real provider exports. If a new wire shape
  must be captured, sanitise it by hand, rename every personal value and
  re-check it with the hygiene tests before committing.

## Layout

- `intervals/athlete.json`, `activities.json`, `wellness.json`, `events.json`:
  the four Intervals.icu inputs to `backend.planning.context.compact_snapshot`.
  The activities include timestamps either side of the Europe/Berlin DST
  transitions (2026-03-29 and 2026-10-25).
- `garmin/<section>.json`: one file per collected Garmin section. The section
  names match the payload keys written by `backend.providers.garmin`, with
  three exceptions: `body_battery` is fetched by the morning path,
  `user_profile` supplies the gear profile id, and `gear_stats` is the usage
  response for each gear row.

## How the tests use them

- `tests/test_provider_wire_fixtures.py` loads each file, feeds the Intervals
  inputs through the real compaction, and feeds the Garmin files through
  `collect_garmin_data` using an in-memory fake client. Responses are deep
  copies, so the fixtures on disk are never mutated.
- `tests/test_garmin_snapshot_writer_lock.py` does not use these fixtures. It
  checks that the Garmin sync and the Morning Body Battery gate share the one
  process-wide Garmin lock.

## Maintenance

- The collected-key test in `tests/test_provider_wire_fixtures.py` compares
  `GARMIN_COLLECTED_KEYS` with the payload keys produced by
  `collect_garmin_data`, ignoring metadata keys. Update that set when
  `backend.providers.garmin` adds or removes a section.
- No test checks that every collected section has a file here. The directory
  test in `tests/test_provider_wire_fixtures.py` only requires the files in
  `garmin/` to match `GARMIN_FIXTURE_FILES`, so add a new file to both by hand.
- Keep the files small: one or two representative records per file.
