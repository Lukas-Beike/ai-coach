# Bootstrap contract

`GET /api/bootstrap` (session required, query ignored) returns the start data
of the PWA in one read-only database snapshot. The field table between the
markers is generated from a real call on an empty database by
`python tests/test_server_database.py --write ServerDatabaseTests.test_bootstrap_contract_is_current`;
a test fails when it is out of date. The producing code is
`backend/http_api/bootstrap_state.py:PublicBootstrapService.read`.

- The area fields marked "always empty" stay in the start data on purpose
  (athlete decision 2026-11-13, #2115): they keep the shape of the stored device
  snapshot, so an update never reuses outdated stored area data. Each is
  filled by its own area route (`docs/api-routes.md`).
- The start data carries the newest 100 chat messages, the local planned units
  (`planned`, at most 250), the profile, up to 100 competitions and `calendar`,
  which merges the planned units, the competitions and up to 250
  training-relevant external calendar events; no further copy of the planned
  units is sent (#2115 removed `training_calendar`).
- `threshold_warnings` is always present (null when there is none), so a
  cleared warning also clears on a client that merges start data.

## Version markers

`state_versions` holds one string per browser area; the client reloads an area
when its marker changes. Each marker is built from local durable state
(`backend/http_api/state_versions.py:StateVersionService.versions`):

- `activities`: the last Garmin and Wahoo sync times and the activity count.
- `performance`: the last Garmin and Wahoo sync times, the observation count
  and a hash of the zone configurations.
- `garmin`: the last Garmin sync time.
- `chat`: the newest message and the message count.
- `library`: the newest library change and the library count.
- `checkins`: the newest check-in and the check-in count.
- `activity_feedback`: the newest activity feedback and its count.
- `profile`: the first 16 hex characters of the SHA-256 of the sorted profile
  JSON.
- `plan`: the last calendar sync time and the newest library, planned-unit and
  check-in change.

## Fields

<!-- BEGIN GENERATED BOOTSTRAP -->
| Field | Type | Fields or note |
| --- | --- | --- |
| `activities` | list | always empty here; its area route loads it |
| `activity_feedback` | object | `recent`, `scope` |
| `app` | object | `name`, `version` |
| `calendar` | list |  |
| `calendar_display` | object | `future_weeks`, `past_weeks` |
| `checkins` | list | always empty here; its area route loads it |
| `coach_quick_actions` | object | `adjust_plan`, `analyze_latest_activity`, `horizon_days`, `morning_checkin`, `plan_blockers` |
| `competitions` | list |  |
| `configured` | object | `anthropic`, `coach`, `external_calendar`, `intervals`, `openai`, `weather` |
| `credentials` | object | `anthropic_configured`, `fields`, `garmin_connected`, `garmin_connection`, `garmin_connection_source`, `intervals_configured`, `openai_configured`, `wahoo_configured`, `yazio_configured` |
| `daily_planning_context` | list | always empty here; its area route loads it |
| `diagnostic_capture` | object | `active`, `bytes`, `entries`, `maximum_age_days`, `maximum_bytes`, `maximum_entries`, `maximum_entry_bytes` |
| `external_calendar` | object | `configured`, `events`, `last_error`, `last_sync_at`, `provider`, `read_only`, `running`, `skipped_events`, `window_days` |
| `garmin` | object | `activities`, `available`, `can_write_workouts`, `configured`, `duplicate_activities_skipped`, `has_estimated_run_times`, `has_hrv`, `has_max_hr`, `has_race_predictions`, `has_readiness`, `has_resting_hr`, `has_sleep`, `has_thresholds`, `has_vo2max`, `has_weight`, `last_error`, `last_sync_at`, `metric_export_enabled`, `morning_body_battery`, `pagination`, `source`, `source_freshness` |
| `garmin_sync` | object | `running`, `status` |
| `intervals` | object | `configured`, `last_error`, `library_sync`, `running`, `state` |
| `library` | list | always empty here; its area route loads it |
| `library_sync` | object | `last_error`, `last_sync_at`, `state` |
| `local_feedback` | object | `recent`, `scope`, `today` |
| `messages` | list |  |
| `messages_next_cursor` | null |  |
| `model` | object | `options`, `provider`, `selected` |
| `morning_checkin` | object | `current_for_today`, `date`, `status` |
| `performance` | object | always empty here; its area route loads it |
| `planned` | list |  |
| `planning` | object | `illness_pause_pending`, `illness_return_pending`, `latest_replan`, `needs_replan`, `replan_changes`, `season` |
| `planning_compliance` | list | always empty here; its area route loads it |
| `profile` | object | `availability`, `body_fat_pct`, `coaching_style`, `constraints`, `equipment`, `first_threshold_origin`, `first_threshold_pct`, `fueling_tolerance`, `goals`, `height_cm`, `name`, `performance_notes`, `preferred_source_body`, `preferred_source_hrv`, `preferred_source_resting_hr`, `preferred_source_sleep`, `preferred_source_thresholds`, `sex`, `sleep_target_hours`, `sports`, `timezone`, `training_background`, `training_model`, `training_preferences`, `training_preferences_cycling`, `training_preferences_mobility`, `training_preferences_running`, `training_preferences_strength`, `training_preferences_swimming`, `typical_weekly_volume`, `weather_location`, `weight_kg` |
| `provider_freshness` | list |  |
| `provider_ids` | object | `garmin`, `intervals`, `wahoo` |
| `provider_labels` | object | `calendar`, `garmin`, `intervals`, `wahoo`, `weather` |
| `provider_resync` | object | `garmin`, `wahoo` |
| `provider_status` | object | `anthropic`, `openai` |
| `service_tier` | object | `options`, `selected` |
| `state_versions` | object | `activities`, `activity_feedback`, `chat`, `checkins`, `garmin`, `library`, `performance`, `plan`, `profile` |
| `sync` | object | `finished_at`, `jobs`, `last_error`, `message`, `operation_id`, `phase`, `progress`, `running`, `started_at`, `status` |
| `sync_settings` | object | `garmin_days`, `wahoo_days` |
| `thinking_level` | object | `options`, `selected` |
| `threshold_warnings` | null |  |
| `usage` | object | `date`, `input_tokens`, `output_tokens`, `rate_limits`, `requests`, `status`, `total_tokens` |
| `wahoo` | object | `configured`, `connected`, `connected_at`, `scope` |
| `weather` | object | always empty here; its area route loads it |

`state_versions` markers: `activities`, `activity_feedback`, `chat`, `checkins`, `garmin`, `library`, `performance`, `plan`, `profile`.
<!-- END GENERATED BOOTSTRAP -->
