## Why

Issue #1669: every activity was dated in the athlete's profile time zone at write time. While travelling, a morning run in Tokyo landed on the previous Berlin day, apart from that morning's HRV and sleep, and changing the profile zone re-dated the whole history.

## What Changes

- Activity records carry their own UTC offset (`local_offset_minutes`) where the provider reports it: Garmin `startTimeLocal` minus `startTimeGMT`, the Intervals.icu activity `timezone` (else `start_date_local` minus an exact `start_date`), the Wahoo workout's IANA `time_zone`.
- The local date and the wall-clock start (`started_at_local`) of an activity and its session use that offset; without one the athlete zone applies as before. A profile zone change therefore re-dates only offset-less activities.
- Readers that convert a summary's start to the athlete zone keep the lived day when the summary carries an offset, so weeks and plan compliance follow it.
- Sleep periods take the provider's own day (Garmin `calendarDate`, the Intervals.icu wellness day) as wake date, so sleep, wellness and activities of a travel day line up.
- Mapper versions: Garmin activity 11, Intervals.icu activity 8, Wahoo 4, Garmin health 16, Intervals.icu wellness 12. The canonical backfill replays stored raw payloads, so history fills in without a refetch.

## Impact

- `backend/canonical/local_time.py`, `backend/canonical/records.py`, the three activity mappers, `backend/providers/sleep_period_mapping.py`, `backend/providers/canonical_plans.py`, `backend/db/canonical_store.py`, `backend/activities/activity_summary.py`, `backend/activities/detail_contract.py`, `backend/canonical/activity_summary.py`.
- No schema change: the offset lives in the activity record's `details` JSON, which backups already carry.
- Historical sessions recorded abroad change their `local_date` after the backfill. Feedback and analyses keyed by session id are unaffected; day-keyed reads (plan compliance, weekly load, check-in pairing) follow the new date.
- Excluded: a zone label in the PWA ("06:30 JST"), travel periods in the profile (solution B), and FIT `local_timestamp` (FIT files only feed activity detail, not activity records).
