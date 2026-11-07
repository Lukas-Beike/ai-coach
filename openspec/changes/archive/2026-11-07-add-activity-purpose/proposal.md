## Why

The canonical model cannot tell a race or a commute from a training session (#1678). Intervals.icu is output-only now (#1732), so its `sub_type`/`race`/`commute` fields are not read; Garmin's activity event type and the athlete's stored competitions are the sources.

## What Changes

- `ActivityPurpose` (training, race, commute, warmup, cooldown) on `ActivityRecord`, stored in the record details (no schema change).
- Garmin activity mapper v17: `eventType.typeKey` `race` -> race, `transportation` -> commute; other event types leave the purpose unset. Stored payloads are replayed by the mapper bump.
- The session summary takes race from any record, else the first purpose in derived order, with the record's source label.
- The canonical reader links each stored competition to the sessions of its local date and sport on read: provider races, else one best candidate as a race hint (source "Lokale Wettkämpfe"). Commutes are never candidates. Nothing is stored.
- The Coach activity list carries `purpose`, `competition_id` and a German `purpose_label`.

Exclusions: athlete marking in the app, warm-up/cool-down detection (follow-up issue), and the consumers (CP/CS and mean-max, plan compliance, race playbook, competition view), which follow in a later PR of #1678.

## Impact

`backend/canonical/vocabulary.py`, `backend/canonical/records.py`, `backend/providers/garmin_activity_mapping.py`, `backend/db/canonical_store.py`, `backend/activities/session_purpose.py`, `backend/activities/activity_summary.py`, `backend/sync/canonical_read_selector.py`, `backend/db/repositories.py`, `backend/coach/context.py`.
