# Design

## Context

Inspected revision: `9ac74808` (develop).

Activity objects reach the browser in three ways:
- `/api/activities` and `/api/bootstrap` `activities` send compact rows (`ACTIVITY_FIELDS`), translated by `neutral_activity_records`.
- `training_calendar`, `planned`, `calendar` and `planning_view.items` of `/api/bootstrap` and `/api/plan` send completed-activity entries and `compliance.actual_activity`, both shaped by `calendar_activity_payload`.
- `/api/activities/{id}` sends the detail document, which is already neutral and stays unchanged here.

A completed-activity calendar entry carries `is_completed_activity: true`; planned units carry `compliance`.

## Decisions

### D1 — One key map, applied by object kind

`public_metrics` gains a full activity map:
- `start_date_local` becomes `started_at_local`, and `start_date` becomes `started_at`.
- `moving_time` becomes `moving_duration_s`, and `elapsed_time` becomes `elapsed_duration_s`.
- `distance` becomes `distance_m`, and `total_elevation_gain` becomes `elevation_gain_m`.
- `average_heartrate` becomes `avg_hr`, and `max_heartrate` becomes `max_hr`.
- `average_watts` becomes `avg_power`, and `weighted_average_watts` becomes `weighted_avg_power`.
- `average_speed` becomes `avg_speed_mps`, `max_speed` becomes `max_speed_mps`, and `icu_weighted_avg_speed` becomes `weighted_avg_speed_mps`.
- `icu_pace` becomes `pace_mps` (the activity pace that `activity_pace_seconds_per_km` reads).
- `icu_ctl` becomes `ctl`, `icu_atl` becomes `atl`, `icu_ftp` becomes `ftp_w`, and `icu_eftp` becomes `eftp_w`.
- `vo2max`, `vo2_max`, `vO2MaxValue`, `vo2MaxValue` and `icu_vo2max` become `vo2max`; the first one present wins.
- The six existing metric renames stay as they are: `training_load`, `intensity`, `rpe`, `normalized_power` and the two zone-time keys.

The names follow the detail document's metric vocabulary, with one exception: `training_load` keeps its existing neutral name rather than becoming `load`. Planned units keep their keys until #1507 and carry the same `training_load`, and the week totals sum planned and actual load.

A neutral key that is already present wins over a renamed one, as today. `weighted_average_watts` stays separate from `normalized_power`: they are different provider values, and the calendar shows `weighted_average_watts`.

The full map applies to list rows, to entries with `is_completed_activity`, and to `compliance.actual_activity`. Every other calendar entry gets only the metric renames.

Alternative considered: an allowlist that drops unknown keys. Rejected, because it could silently drop a key that a reader still uses. Instead, a test asserts that no translated payload contains a key from `ACTIVITY_FIELDS` other than the generic ones: `id`, `name`, `type`, `feel`, `source`, `device_name`, `external_id`, `file_type`, `paired_event_id`, `normalized_power` and `vo2max`.

### D2 — Translation covers `calendar` and `planning_view.items`

Both lists currently pass through untranslated. `bootstrap_calendar` and `public_plan` now apply `neutral_calendar_entries` to them as well, so no HTTP payload carries a raw activity object.

### D3 — The PWA reads neutral keys on activity objects only

Planned-entry reads stay as they are. Where code is shared by planned and completed entries, such as the calendar sort, it reads the neutral key on the activity and the stored key on the planned entry.

### D4 — Field-module import rule in the existing ratchet

`tests/provider_coupling.py` gains a `field_module_import` rule. It applies outside `backend/providers/`, `backend/sync/` and `backend/canonical/`, and each finding is keyed by the importing module and the imported field module. It is an owner-read rule rather than a ratchet entry, because the ratchet baseline must stay empty. The explained allowlist names the owning issue of each current importer, and a stale entry fails the guard.

## Risks / Trade-offs

- [A PWA reader of a renamed key is missed] → The renames were mapped by a grep over `public/`. The e2e specs for analysis, activity details, contracts and the plan run on all projects, and a unit test pins the map.
- [An installed PWA keeps a cached app shell against a new server] → Query versions and the service-worker cache are bumped together, and the existing safe-reload update applies.
