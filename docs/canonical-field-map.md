# Canonical field map

How every provider field reaches the canonical model, read from the code of this repository. It is the reference for anyone changing a mapper, a reader or a consumer. The canonical model is the one vocabulary (`backend/canonical/`) that all providers are mapped into; everything downstream (sessions, current values, Coach context, planning) reads it instead of provider payloads.

`tests/test_canonical_field_map_doc.py` keeps this file complete: it fails when a mapper names a canonical enum member or builds a canonical record field that its section does not list, when a vocabulary member or a record field is missing, when a documented mapper version differs from `MAPPER_VERSION`, or when the map cites a file that does not exist.

## How to read it

- One section per mapper module, headed with its file name. Each section states the status (`Live`, or `Retired` when the module only replays rows stored earlier), the mapper version, the inputs, the evidence, a table of canonical field against provider key(s) and a "Not mapped" paragraph.
- Provider keys are written exactly as the code reads them. `a` → `b` is an alias chain: the first key present wins.
- Evidence: **observed** means the key exists in a sanitized real payload (Garmin SDK, Garmin Personal API, Intervals.icu); **documented** means it is known only from code, SDK or API documentation or a test fixture. Wahoo keys are all documented: no real Wahoo payload has been captured.
- Rows cite functions and constants by name. Line numbers are not used because they drift.
- Units are the canonical units: seconds, metres, metres per second, watts, beats per minute, kilograms, percent.

## Providers

| Provider | Role | Mappers |
|---|---|---|
| Garmin | Input. Activities, details, health, training status, gear. Personal API (key) serves the families it can; the SDK serves the rest. | `garmin_*` modules |
| Wahoo | Input. Activities (with FIT file detail), cycling power zones, profile weight; plan export. | `wahoo_*` modules |
| Intervals.icu | Output target only since the ingest was removed (#1728). Its mappers remain to read rows stored earlier and are marked `Retired` where no live caller exists. | `intervals_*` modules |
| FIT files | Wahoo (and Garmin) activity files decoded with the standard library parser. | `fit_activity_detail_mapping.py` |
| Local | Values the app derives or the athlete enters: session load, session metrics, morning Body Battery, zone configurations. | listed in "Locally derived records" |

## Source precedence for observations

Implemented in `backend/performance/source_policy.py` (`CURRENT_RULES`, `DAILY_RULES`, `RECENCY_ORDERS`, `SPORT_ORDERS`, `PREFERENCE_GROUPS`) and, for sport thresholds, `backend/performance/current_thresholds.py`. Intervals.icu is never a source (athlete decision 2026-11-07); its rows are stored history only. Provider order of the whole canonical model: `PROVIDER_PRECEDENCE` in `backend/canonical/vocabulary.py` is Wahoo, Garmin, Intervals.icu; it ranks provider records of one activity session (see "Activity summary resolution"), not observations.

`select_current` keeps the observations of the requested kind (and sport), drops providers outside the rule, values outside the rule's bounds and values older than the rule's age limit on the athlete-local day `as_of`, then takes the first provider in the rule's order that still has a value. Within one provider: weight ranks by newest `observed_on` then `observed_at`; other dated kinds by newest `observed_on` then the last Garmin input record; sport-scoped kinds (`ftp`, `threshold_hr`, `threshold_pace`, `max_hr`, `vo2max`) ignore dates and take the last Garmin input record. `select_daily` takes, per calendar day, the first provider of the order that has a value that day (first input record, timestamps ignored). A sport-scoped kind without a sport raises `ValueError`.

| Kind | Order (best first) | Bounds | Age limit |
|---|---|---|---|
| `weight` | Garmin, Wahoo; undated local profile weight between them (`RECENCY_ORDERS`: newest dated value wins, within `RECENCY_TIE_DAYS` = 1 day a device measurement beats a provider report beats an athlete entry) | none (validation range 20 to 400 kg) | Wahoo 90 days |
| `body_fat` | Garmin, local profile (same recency rule) | | |
| `resting_hr` | Garmin | 30 to 230 bpm | |
| `hrv_rmssd` | Garmin | 1 to 300 ms | |
| `hrv_weekly_average` | Garmin (labelled fallback for RMSSD only) | 1 to 300 ms | |
| `sleep_duration` | Garmin | | |
| `sleep_score` | Garmin | 0 to 100 | |
| `readiness` | Garmin | | |
| `ftp` | local zone configuration, Garmin, Wahoo (run FTP: local, Garmin only: `SPORT_ORDERS`) | 50 to 700 W (Garmin and Wahoo) | Garmin 180 days, Wahoo 90 days |
| `threshold_hr` | local, Garmin | 80 to 230 bpm | Garmin 180 days |
| `threshold_pace` | local, Garmin | | Garmin 180 days |
| `max_hr` | local, Garmin; activity maximum as caller-side fallback | 80 to 260 bpm | Garmin 180 days |
| `vo2max` | Garmin | 20 to 100 | |

Daily rules (`DAILY_RULES`) exist for `sleep_duration`, `sleep_score`, `hrv_rmssd`, `resting_hr` and `readiness` and reuse the order and bounds above.

- **Local first.** For `ftp`, `threshold_hr`, `threshold_pace`, `max_hr` (`LOCAL_FIRST_KINDS`) the athlete's confirmed zone configuration in effect on the day precedes every provider (`local_thresholds` builds transient observations from `ZoneConfiguration`; they are not stored). `resolve_candidates` returns the winner, the other sources as alternatives and a conflict flag when an alternative differs by more than `CONFLICT_TOLERANCE` (3 % of the winner for the threshold kinds; `ABSOLUTE_CONFLICT_TOLERANCE`: 1.5 kg weight, 2.0 points body fat).
- **Preferences.** The profile fields `preferred_source_<group>` (`thresholds`, `body`, `hrv`, `resting_hr`, `sleep`) move a preferred provider to the front of its group's order, behind a leading local value. Only providers listed in `PREFERENCE_GROUPS` count (Garmin); any other stored value is ignored.
- **Not covered here.** Profile and manual values and the activity-derived maximum heart rate stay with the caller.

## Subjective rating scales

`backend/canonical/rating_scales.py` fixes the scale of every rating by where it was entered; the stored value is raw and the scale is resolved at read time (no scale id is stored). Directions: `better` (higher is better), `worse` (higher is worse), `harder` (higher is harder).

| Scale id | Range | Direction | Entered at |
|---|---|---|---|
| `intervals_fatigue_1_4`, `intervals_soreness_1_4`, `intervals_stress_1_4`, `intervals_mood_1_4` | 1 to 4 | higher is worse (mood: 1 super … 4 mies) | Intervals.icu wellness ratings (`INTERVALS_WELLNESS_SCALES`, retired ingest) |
| `intervals_rpe_1_10`, `intervals_feel_1_5` | 1 to 10, 1 to 5 | rpe harder; feel 1 strong … 5 weak | Intervals.icu activity |
| `garmin_rpe_1_10`, `garmin_feel_1_5` | 1 to 10, 1 to 5 | rpe harder; feel 1 very strong … 5 very weak | Garmin watch; the mapper converts the watch's RPE 10..100 and feel 0..100 into these |
| `local_rpe_0_10`, `local_soreness_0_10`, `local_stress_0_10`, `local_motivation_0_10` | 0 to 10 | RPE harder, soreness and stress worse, motivation better | The app's daily check-in and activity feedback (`LOCAL_CHECKIN_SCALES`) |

`ACTIVITY_RATING_SCALES` assigns the Garmin and Intervals scales to the activity summary fields `rpe` and `feel`. `rating_fields` returns the scale text, the label and a normalized value from 0 (best or lowest strain) to 1.

## Time and dates

`backend/canonical/local_time.py`. Providers send either an instant with an offset or naive wall-clock text in the athlete's zone.

- `parse_provider_datetime` accepts ISO text with `T` or one space and an optional `Z` or offset; date-only, empty or malformed text, and text of 10 characters or fewer or longer than 64 after stripping, return None. Naive text is localised by `localize_wall_time`: an ambiguous autumn time takes its first occurrence (summer offset), a non-existent spring time moves forward by the pre-transition offset.
- Aware inputs keep their instant and offset; `local_date(value, zone)` reads the calendar date in a zone.
- An activity carries its own UTC offset (`local_offset_minutes`) when the provider names one: `wall_clock_offset_minutes(local_text, instant)` derives it from the provider's local start text (naive text: difference to the UTC instant rounded to 15 minutes; aware text: its own offset), `zone_offset_minutes` from an IANA zone name; `valid_offset_minutes` accepts whole quarter-hours within ±14 h. `wall_time` then reads the wall clock and the day in that offset, so travel does not move an activity to another day; without an offset the athlete zone applies.
- Observations carry a calendar day `observed_on` (provider day for health data) and an optional instant `observed_at`. How a sleep night is dated is stated in the `sleep_period_mapping.py` and `garmin_health_mapping.py` sections.

## Canonical record `MetricValue`

A number with its unit. Created through `Observation`, which checks the unit against `MetricKind.unit`.

| Field | Type | Rule |
|---|---|---|
| `value` | float | Finite; bool rejected. Range per kind in `METRIC_BOUNDS` (`backend/canonical/validation.py`). |
| `unit` | text, at most 16 chars | Must equal the kind's canonical unit. |

## Canonical record `MeasurementContext`

How a value was measured; every field is None when the provider does not say. Never guessed from the brand.

| Field | Type | Rule |
|---|---|---|
| `device_model` | text, at most 100 | Trimmed printable; rejected when it contains a serial-like run (8+ hex digits or 6+ digits). |
| `firmware` | text | Short version text. |
| `algorithm` | slug | Lowercase identifier. |
| `sensor` | slug | e.g. `optical_wrist`. |
| `window` | slug | Measurement window. |
| `protocol` | slug | Measurement protocol. |

`identity` is a stable hash of all six fields; `UNKNOWN_CONTEXT` is the all-None context.

## Canonical record `Provenance`

| Field | Type | Rule |
|---|---|---|
| `provider` | `ProviderId` or None | Required for `provider_reported` and `device_measured`; must be None for `athlete_entered`, `ai_estimate` and `profile`; optional for `derived`. |
| `source_kind` | `SourceKind` | Provider-reported, device-measured, derived, AI estimate, athlete-entered or profile. |
| `source_record_id` | text or None | The provider's own record id (activity id, night date, ...). |
| `recorded_by` | `RecordingOrigin` | The device brand or app that recorded the data; differs from `provider` for relayed copies. |
| `retrieved_at` | aware datetime or None | When the app fetched it. |
| `label` | text or None | Display label of the source. |
| `context` | `MeasurementContext` | Defaults to the unknown context. |

## Canonical record `ObservationPeriod`

| Field | Type | Rule |
|---|---|---|
| `start` | aware datetime, stored in UTC | Start of the summarized interval, e.g. the night. |
| `end` | aware datetime, stored in UTC | After `start`; interval at most 366 days. |

## Canonical record `Observation`

One dated metric value (`MetricKind`) with provenance.

| Field | Type | Rule |
|---|---|---|
| `kind` | `MetricKind` | See "Metric kinds". |
| `value` | `MetricValue` | Unit and range checked by kind. |
| `observed_on` | date | Provider day (health) or session local day. |
| `observed_at` | aware datetime or None | Instant when the provider gives one. |
| `provenance` | `Provenance` | |
| `sport` | `Sport` or None | Required by sport-scoped kinds when selecting. |
| `method` | slug or None | Derivation name, e.g. `ctl_minus_atl` (`FORM_METHOD`). |
| `aggregation` | `ObservationAggregation` or None | `sample`, `total`, `mean`, `minimum`, `maximum`. |
| `method_version` | int 1 to 10,000 or None | |
| `input_fingerprint` | SHA-256 hex or None | `fingerprint_inputs` of the derivation inputs. |
| `period` | `ObservationPeriod` or None | Interval the value summarizes. |

A `derived` observation must carry `method`, `method_version` and `input_fingerprint`; `method_version` and `input_fingerprint` require a `method`.

## Canonical record `ExternalRef`

The upstream provider activity a record was copied from (an Intervals.icu copy of a Garmin activity names the Garmin activity id). Used for exact duplicate linking.

| Field | Type | Rule |
|---|---|---|
| `upstream` | `ProviderId` | Provider the activity originates from. |
| `upstream_id` | text, at most 200 | That provider's activity id. |

## Metric kinds (`MetricKind`)

Each kind has exactly one canonical unit (`MetricKind.unit`) and a plausibility range (`METRIC_BOUNDS` in `backend/canonical/validation.py`); an observation outside it is rejected. "Emitted by" lists the modules that construct observations of the kind (provider mappers and the three local derivations); "Status" comes from `UNPRODUCED_METRIC_KINDS` and `EXPORT_ONLY_METRIC_KINDS` in `backend/canonical/vocabulary.py`.

| Kind | Unit | Range | Meaning | Emitted by | Status |
|---|---|---|---|---|---|
| `weight` | `kg` | 20 to 400 | Body weight. | `garmin_health_mapping.py`, `intervals_wellness_mapping.py`, `wahoo_threshold_mapping.py` | read |
| `body_fat` | `%` | 1 to 80 | Body-fat share of body weight. | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `ftp` | `W` | 0 to 2,500 | Functional threshold power; the sport field says ride or run (run FTP = running threshold power). | `garmin_health_mapping.py`, `intervals_wellness_mapping.py`, `wahoo_threshold_mapping.py` | read |
| `threshold_hr` | `bpm` | 20 to 250 | Lactate-threshold heart rate (per sport). | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `max_hr` | `bpm` | 20 to 250 | Maximum heart rate (per sport). | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `resting_hr` | `bpm` | 20 to 250 | Resting heart rate of the day. | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `hrv_rmssd` | `ms` | 0 to 500 | Heart-rate variability as RMSSD (overnight). | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `hrv_sdnn` | `ms` | 0 to 500 | Heart-rate variability as SDNN. | `intervals_wellness_mapping.py` | read |
| `hrv_weekly_average` | `ms` | 0 to 500 | Garmin weekly HRV average; only a labelled fallback for RMSSD. | `garmin_health_mapping.py` | read |
| `sleep_duration` | `s` | 0 to 86,400 | Sleep duration of the night. | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `sleep_score` | `score` | 0 to 100 | Provider sleep score. | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `spo2` | `%` | 50 to 100 | Mean blood-oxygen saturation during the night. | `garmin_health_mapping.py` | read |
| `spo2_lowest` | `%` | 50 to 100 | Lowest blood-oxygen saturation during the night. | `garmin_health_mapping.py` | read |
| `respiration_rate` | `brpm` | 4 to 60 | Mean respiration rate during the night. | `garmin_health_mapping.py` | read |
| `sleeping_hr` | `bpm` | 20 to 250 | Mean heart rate while asleep. | `garmin_health_mapping.py` | read |
| `vo2max` | `ml/kg/min` | 5 to 120 | VO2max estimate (per sport). | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `threshold_pace` | `m/s` | 0 to 15 | Threshold running pace as speed. | `garmin_health_mapping.py`, `intervals_wellness_mapping.py` | read |
| `body_battery` | `score` | 0 to 100 | Garmin Body Battery level (timed sample). | `garmin_health_mapping.py` | read |
| `readiness` | `score` | 0 to 100 | Provider readiness/training-readiness score. | `garmin_health_mapping.py`, `garmin_training_mapping.py`, `intervals_wellness_mapping.py` | read |
| `ctl` | `load` | 0 to 10,000 | Intervals.icu chronic training load (fitness). | `intervals_wellness_mapping.py` | export only: no reader |
| `atl` | `load` | 0 to 10,000 | Intervals.icu acute training load (fatigue). | `intervals_wellness_mapping.py` | export only: no reader |
| `training_load` | `load` | 0 to 10,000 | Never produced; retained so a stored value stays readable. | none | unproduced by providers; export only: no reader |
| `form` | `load` | -10,000 to 10,000 | Form: CTL minus ATL (reported or derived with method `ctl_minus_atl`). | `intervals_wellness_mapping.py` | export only: no reader |
| `eftp` | `W` | 0 to 2,500 | Intervals.icu estimated FTP. | `intervals_wellness_mapping.py` | export only: no reader |
| `run_threshold_power` | `W` | 0 to 2,500 | Legacy: run FTP before Garmin health mapper 17; now FTP with sport run. | none | unproduced by providers |
| `daily_energy_total` | `kcal` | 0 to 20,000 | Total energy expenditure of the day. | `garmin_health_mapping.py` | read |
| `daily_energy_active` | `kcal` | 0 to 20,000 | Active energy expenditure of the day. | `garmin_health_mapping.py` | read |
| `steps` | `count` | 0 to 200,000 | Step count of the day. | `garmin_health_mapping.py` | read |
| `floors` | `count` | 0 to 1,000 | Floors climbed in the day. | `garmin_health_mapping.py` | read |
| `stress` | `score` | 0 to 100 | Garmin daily physiological stress level. | `garmin_health_mapping.py` | export only: no reader |
| `race_prediction_5k` | `s` | 60 to 100,000 | Garmin predicted 5 km time. | `garmin_health_mapping.py` | read |
| `race_prediction_10k` | `s` | 60 to 100,000 | Garmin predicted 10 km time. | `garmin_health_mapping.py` | read |
| `race_prediction_half` | `s` | 60 to 100,000 | Garmin predicted half-marathon time. | `garmin_health_mapping.py` | read |
| `race_prediction_full` | `s` | 60 to 100,000 | Garmin predicted marathon time. | `garmin_health_mapping.py` | read |
| `endurance_score` | `score` | 0 to 20,000 | Garmin endurance score. | `garmin_health_mapping.py` | read |
| `daily_energy_resting` | `kcal` | 0 to 20,000 | Resting energy expenditure of the day. | `garmin_health_mapping.py` | read |
| `body_battery_charged` | `score` | 0 to 500 | Body Battery charged over the day (total). | `garmin_health_mapping.py` | export only: no reader |
| `body_battery_drained` | `score` | 0 to 500 | Body Battery drained over the day (total). | `garmin_health_mapping.py` | export only: no reader |
| `acute_load` | `load` | 0 to 100,000 | Garmin acute training load. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `chronic_load` | `load` | 0 to 100,000 | Garmin chronic training load. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `acute_chronic_ratio` | `ratio` | 0 to 100 | Garmin acute:chronic load ratio. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_aerobic_low` | `load` | 0 to 100,000 | Garmin load balance, low aerobic: load share. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_aerobic_low_target_min` | `load` | 0 to 100,000 | Garmin load balance, low aerobic: target range minimum. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_aerobic_low_target_max` | `load` | 0 to 100,000 | Garmin load balance, low aerobic: target range maximum. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_aerobic_high` | `load` | 0 to 100,000 | Garmin load balance, high aerobic: load share. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_aerobic_high_target_min` | `load` | 0 to 100,000 | Garmin load balance, high aerobic: target range minimum. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_aerobic_high_target_max` | `load` | 0 to 100,000 | Garmin load balance, high aerobic: target range maximum. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_anaerobic` | `load` | 0 to 100,000 | Garmin load balance, anaerobic: load share. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_anaerobic_target_min` | `load` | 0 to 100,000 | Garmin load balance, anaerobic: target range minimum. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `load_balance_anaerobic_target_max` | `load` | 0 to 100,000 | Garmin load balance, anaerobic: target range maximum. | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `running_tolerance` | `unknown` | 0 to 100,000 | Garmin running tolerance (score without a known unit). | `garmin_health_mapping.py`, `garmin_training_mapping.py` | read |
| `endurance_score_group_average` | `score` | 0 to 20,000 | Garmin endurance score, group average. | `garmin_training_mapping.py` | read |
| `endurance_score_group_max` | `score` | 0 to 20,000 | Garmin endurance score, group maximum. | `garmin_training_mapping.py` | read |
| `subjective_fatigue` | `rating` | 1 to 4 | Imported provider wellness rating (1-4). | `intervals_wellness_mapping.py` | export only: no reader |
| `subjective_soreness` | `rating` | 1 to 4 | Imported provider wellness rating (1-4). | `intervals_wellness_mapping.py` | export only: no reader |
| `subjective_stress` | `rating` | 1 to 4 | Imported provider wellness rating (1-4). | `intervals_wellness_mapping.py` | export only: no reader |
| `subjective_mood` | `rating` | 1 to 4 | Imported provider wellness rating (1-4). | `intervals_wellness_mapping.py` | export only: no reader |
| `w_prime` | `J` | 0 to 200,000 | W prime (anaerobic work capacity) from the Intervals.icu sport setting. | `intervals_wellness_mapping.py` | export only: no reader |
| `height` | `cm` | 30 to 300 | Body height from the Intervals.icu athlete record. | `intervals_wellness_mapping.py` | export only: no reader |
| `zone2_pace` | `m/s` | 0 to 15 | Zone-2 pace from the Intervals.icu sport setting. | `intervals_wellness_mapping.py` | export only: no reader |
| `indoor_ftp` | `W` | 0 to 2,500 | Indoor FTP from the Intervals.icu sport setting. | `intervals_wellness_mapping.py` | export only: no reader |
| `session_load` | `load` | 0 to 10,000 | Local TSS-scale load of one session (card M6). | `local_load.py` | unproduced by providers |
| `intensity_factor` | `%` | 0 to 1,000 | Local intensity factor of one session (card M6). | `local_load.py` | unproduced by providers |
| `efficiency_factor` | `ratio` | 0 to 20 | Local efficiency factor of one session (card M8). | `session_metrics.py` | unproduced by providers |
| `variability_index` | `ratio` | 0 to 10 | Local variability index of one session (card M8). | `session_metrics.py` | unproduced by providers |
| `mechanical_work` | `kJ` | 0 to 1,000,000 | Local mechanical work of one session (card M8). | `session_metrics.py` | unproduced by providers |
| `aerobic_decoupling` | `%` | -100 to 100 | Local aerobic decoupling of one session (card M8). | `session_metrics.py` | unproduced by providers |
| `body_battery_before_sleep` | `score` | 0 to 100 | Last Body Battery level up to four hours before sleep (derived locally). | `morning_battery_service.py` | unproduced by providers |
| `morning_body_battery` | `score` | 0 to 100 | First Body Battery level after waking (derived locally). | `morning_battery_service.py` | unproduced by providers |

## Canonical vocabulary

Every enumeration of `backend/canonical/vocabulary.py`. Values are stored as text and must stay readable; "Named by" lists the provider mapper modules that name the member in code (blank: no mapper does; the producer is a local derivation, the athlete, or nothing). `MetricKind` is in its own section above.

### `ProviderId`

Enum where members are also (and must be) strings

| Value | Named by |
|---|---|
| `intervals` | `intervals_activity_detail_mapping.py`, `intervals_activity_mapping.py`, `intervals_power_curve_mapping.py`, `intervals_wellness_mapping.py`, `intervals_zone_mapping.py`, `sleep_period_mapping.py` |
| `garmin` | `garmin_activity_detail_mapping.py`, `garmin_activity_mapping.py`, `garmin_gear_mapping.py`, `garmin_health_mapping.py`, `garmin_status_mapping.py`, `intervals_activity_mapping.py`, `sleep_period_mapping.py` |
| `wahoo` | `intervals_activity_mapping.py`, `wahoo_activity_mapping.py`, `wahoo_threshold_mapping.py` |

### `SourceKind`

Enum where members are also (and must be) strings

| Value | Named by |
|---|---|
| `provider_reported` | `garmin_activity_detail_mapping.py`, `garmin_activity_mapping.py`, `garmin_gear_mapping.py`, `garmin_health_mapping.py`, `garmin_status_mapping.py`, `intervals_activity_detail_mapping.py`, `intervals_activity_mapping.py`, `intervals_power_curve_mapping.py`, `intervals_wellness_mapping.py`, `intervals_zone_mapping.py`, `sleep_period_mapping.py`, `wahoo_activity_mapping.py`, `wahoo_threshold_mapping.py` |
| `device_measured` | `garmin_health_mapping.py`, `sleep_period_mapping.py` |
| `derived` | `intervals_wellness_mapping.py` |
| `ai_estimate` |  |
| `athlete_entered` |  |
| `profile` |  |

### `RecordingOrigin`

Device brand or app that recorded an activity.

| Value | Named by |
|---|---|
| `garmin` | `garmin_activity_mapping.py`, `garmin_gear_mapping.py`, `garmin_health_mapping.py`, `garmin_status_mapping.py`, `intervals_activity_fields.py`, `intervals_activity_mapping.py`, `sleep_period_mapping.py` |
| `wahoo` | `garmin_activity_mapping.py`, `intervals_activity_fields.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py`, `wahoo_threshold_mapping.py` |
| `strava` | `intervals_activity_mapping.py` |
| `zwift` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py` |
| `manual` | `garmin_activity_mapping.py`, `garmin_health_mapping.py`, `intervals_activity_mapping.py`, `intervals_wellness_mapping.py` |
| `upload` | `intervals_activity_mapping.py` |
| `unknown` | `intervals_activity_mapping.py`, `intervals_power_curve_mapping.py`, `intervals_wellness_mapping.py`, `intervals_zone_mapping.py`, `sleep_period_mapping.py` |

### `DeviceType`

The device class that recorded the activity.

| Value | Named by |
|---|---|
| `watch` | `intervals_activity_mapping.py` |
| `bike_computer` | `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `chest_strap` |  |
| `power_meter` |  |

### `Sport`

Enum where members are also (and must be) strings

| Value | Named by |
|---|---|
| `ride` | `garmin_activity_mapping.py`, `garmin_health_mapping.py`, `intervals_activity_mapping.py`, `intervals_wellness_mapping.py`, `wahoo_activity_mapping.py`, `wahoo_plan_mapping.py`, `wahoo_threshold_mapping.py` |
| `run` | `garmin_activity_mapping.py`, `garmin_health_mapping.py`, `garmin_training_mapping.py`, `intervals_activity_mapping.py`, `intervals_wellness_mapping.py`, `wahoo_activity_mapping.py`, `wahoo_plan_mapping.py`, `wahoo_threshold_mapping.py` |
| `swim` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `walk` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `hike` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `strength` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py` |
| `row` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `nordic_ski` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `alpine_ski` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `yoga` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `other` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `intervals_wellness_mapping.py`, `intervals_zone_mapping.py`, `wahoo_activity_mapping.py` |

### `Environment`

Enum where members are also (and must be) strings

| Value | Named by |
|---|---|
| `outdoor` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `indoor` | `garmin_activity_mapping.py`, `intervals_zone_mapping.py`, `wahoo_activity_mapping.py`, `wahoo_plan_mapping.py` |
| `virtual` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py`, `wahoo_plan_mapping.py` |
| `unknown` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |

### `ActivityPurpose`

Why an activity was done, where a source says so.  RACE and COMMUTE come from the provider's event type (Garmin ``eventType.typeKey``) or, for RACE, from a stored competition on the same local date and sport. WARMUP and COOLDOWN are reserved for the athlete's own marking. An activity without any of these is ordinary training.

| Value | Named by |
|---|---|
| `training` |  |
| `race` | `garmin_activity_mapping.py` |
| `commute` | `garmin_activity_mapping.py` |
| `warmup` |  |
| `cooldown` |  |

### `Terrain`

The surface an activity was done on, where the provider type names it.  Orthogonal to ``Sport`` and ``Environment``: a trail run is a RUN, OUTDOOR, TRAIL. UNKNOWN when the type names no surface.

| Value | Named by |
|---|---|
| `road` | `garmin_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `trail` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `track` | `garmin_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `gravel` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py` |
| `mountain` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `treadmill` | `garmin_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `pool` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `open_water` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `unknown` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |

### `Assist`

Motor assistance: ELECTRIC for e-bikes, NONE when the provider type names a sport without assistance, UNKNOWN when the type is not known.

| Value | Named by |
|---|---|
| `none` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `electric` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |
| `unknown` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |

### `LoadModel`

Provider model that produced an activity's reported training load.  Every member is a provider's own calculation, never a local method: a local session-RPE load is not a LoadModel (see #1427). ``UNKNOWN`` marks a load whose model the provider does not name.

| Value | Named by |
|---|---|
| `intervals_training_load` | `intervals_activity_mapping.py` |
| `garmin_training_load` | `garmin_activity_mapping.py` |
| `trimp` |  |
| `tss` | `wahoo_activity_mapping.py` |
| `unknown` | `garmin_activity_mapping.py`, `intervals_activity_mapping.py`, `wahoo_activity_mapping.py` |

### `ObservationAggregation`

How an observation's value summarizes its instant or period (optional).

| Value | Named by |
|---|---|
| `sample` | `garmin_health_mapping.py` |
| `total` | `garmin_health_mapping.py` |
| `mean` | `garmin_health_mapping.py` |
| `minimum` | `garmin_health_mapping.py` |
| `maximum` |  |

### `CategoricalDomain`

Provider status vocabularies kept as codes, never as numeric measurements.  Stored as text without a SQL CHECK, so a mapper can add a domain without a schema change.

| Value | Named by |
|---|---|
| `training_status` | `garmin_status_mapping.py` |
| `readiness_level` | `garmin_status_mapping.py` |
| `hrv_status` | `garmin_status_mapping.py` |

### `SleepKind`

Enum where members are also (and must be) strings

| Value | Named by |
|---|---|
| `night` | `sleep_period_mapping.py` |
| `unknown` | `sleep_period_mapping.py` |

### `ZoneConfigurationMetric`

Metric of a zone configuration. Separate from ZoneMetric, whose members are CHECKed by the released activity detail tables.

| Value | Named by |
|---|---|
| `heart_rate` | `intervals_zone_mapping.py` |
| `power` | `intervals_zone_mapping.py` |
| `pace` | `intervals_zone_mapping.py` |

### `ZonePercentBasis`

The reference value that percent zone limits are relative to.

| Value | Named by |
|---|---|
| `threshold` | `intervals_zone_mapping.py` |
| `maximum` |  |
| `reserve` |  |

### `ProjectionState`

Lifecycle of a row projected from one source record (schema version 15).  A reprojection that no longer emits a row retires it instead of deleting it.

| Value | Named by |
|---|---|
| `active` |  |
| `retired` |  |

### `ProviderRecordState`

Lifecycle of a raw provider record. Deleted records are kept for sync.

| Value | Named by |
|---|---|
| `active` |  |
| `deleted` |  |

### `ActivityRecordState`

Lifecycle of a provider activity record linked to a canonical session.

| Value | Named by |
|---|---|
| `active` |  |
| `deleted` |  |
| `invalid` |  |

### `ActivityLinkKind`

How an activity session was linked to its primary provider activity.

| Value | Named by |
|---|---|
| `single` |  |
| `exact` |  |
| `heuristic` |  |
| `confirmed` |  |

### `ActivitySessionState`

Lifecycle of a canonical activity session.

| Value | Named by |
|---|---|
| `active` |  |
| `hidden` |  |
| `duplicate` |  |
| `deleted` |  |

### `RemoteEntityKind`

Kind of local entity that a provider-neutral remote link refers to.

| Value | Named by |
|---|---|
| `library_workout` |  |
| `planned_unit` |  |
| `competition` |  |
| `observation` |  |

### `RemoteLinkState`

Synchronization state of one local entity at one remote provider.

| Value | Named by |
|---|---|
| `pending` |  |
| `synced` |  |

## Canonical record `ActivityRecord`

Defined in `backend/canonical/records.py`. One provider's record of a completed activity; frozen dataclass, validated in `__post_init__` (a value outside its bounds raises, so mappers bound-check first and turn a bad value into `None` plus a `MappingIssue`). Only three mappers construct it from provider data: `garmin_activity_mapping.py`, `wahoo_activity_mapping.py`, `intervals_activity_mapping.py`. `canonical_table_reader._activity` rebuilds the same record from the stored tables (columns plus the `details` JSON), field for field. The provenance block (`provenance.provider`, `provenance.source_kind`, `provenance.source_record_id`, `provenance.recorded_by`, `provenance.retrieved_at`, `provenance.label`) is described per module below; its record classes are documented elsewhere.

Evidence column abbreviations: G = `garmin_activity_mapping.py`, W = `wahoo_activity_mapping.py`, I = `intervals_activity_mapping.py`. "-" = the module never sets the field (it keeps the dataclass default `None`, or `unknown` for `terrain`/`assist`).

Shared rule `activity_duration_s(sport, moving, timer, elapsed)`: `active = moving or (timer if timer is not None else elapsed)`; for `Sport.STRENGTH` with a non-zero `elapsed` the result is `max(active or 0, elapsed)`. A zero `moving` falls through to `timer`/`elapsed`; a zero `timer` or `elapsed` is kept as a measured zero.

| Field | Type and unit | G | W | I | Notes |
|---|---|---|---|---|---|
| `activity_id` | text, provider activity id | yes | yes | yes | Not unique across providers; a session id is separate (see "Activity summary resolution"). |
| `provenance` | `Provenance` | yes | yes | yes | `provider` = `garmin` / `wahoo` / `intervals`; `source_kind` = `provider_reported` for all three; `source_record_id` = the activity id; `retrieved_at` = the fetch time passed to the mapper. |
| `sport` | `Sport` | yes | yes | yes | Type tables per module. |
| `environment` | `Environment` | yes | yes | yes | `unknown` unless the type or (Garmin, Intervals) the identity text names it. |
| `started_at` | aware datetime | yes | yes | yes | Instant; offset kept as sent. |
| `duration_s` | s, 0..604800 | yes | yes | yes | `activity_duration_s`; moving time first. |
| `distance_m` | m, 0..2,000,000 | yes | yes | yes | |
| `load` | provider load, 0..10,000 | yes | yes | yes | Scale given by `load_model`. |
| `load_model` | `LoadModel` | yes | yes | yes | G `garmin_training_load`, W `tss`, I `intervals_training_load`; `unknown` without a load. `trimp` is not emitted. |
| `avg_hr` | bpm, 20..250 | yes | yes | yes | |
| `avg_power` | W, 0..5000 | yes | yes | yes | |
| `name` | text, max 200 | yes | yes | yes | |
| `moving_duration_s` | s | yes | yes | yes | Provider's own moving time. |
| `elevation_gain_m` | m, 0..100,000 | yes | yes | yes | |
| `normalized_power` | W | yes | yes | yes | W: zero becomes `None`. |
| `avg_cadence` | rpm, 0..300, one leg for runs | yes | yes | yes | G halves run steps/min. |
| `energy_kj` | kJ, 0..1,000,000 | - | yes | - | W only (`work_accum` J / 1000). |
| `elapsed_duration_s` | s | yes | yes | yes | Including pauses. |
| `max_hr` | bpm | yes | - | yes | |
| `max_speed_mps` | m/s, 0..100 | yes | - | yes | |
| `max_power_w` | W | yes | - | yes | |
| `min_hr` | bpm | yes | - | - | G from the merged `activity_ratings` row. |
| `elevation_high_m` | m, -500..9000 | yes | - | - | `elevation_low_m` must not exceed it. |
| `elevation_low_m` | m, -500..9000 | yes | - | - | |
| `steps` | count, 0..1,000,000 | yes | - | - | |
| `device_type` | `DeviceType` | yes | yes | yes | Only `bike_computer` (G/W via `wahoo_device_type`) and `watch`/`bike_computer` (I via device name). `chest_strap` and `power_meter` are never emitted. |
| `intensity` | % of FTP, 0..1000 | - | - | yes | Provider intensity factor. |
| `rpe` | 0..10 | yes | - | yes | G: raw 10..100 divided by 10 (1..10). I: as sent. |
| `feel` | 0..10 | yes | - | yes | Both on the 1 (strong) .. 5 (weak) scale; G converts from 0..100. |
| `avg_speed_mps` | m/s | yes | - | yes | |
| `weighted_avg_speed_mps` | m/s | - | - | yes | |
| `grade_adjusted_speed_mps` | m/s | yes | - | - | |
| `pace_mps` | m/s | - | - | yes | |
| `ftp_w` | W | - | - | yes | |
| `eftp_w` | W | - | - | yes | |
| `vo2max` | 0..100 | yes | - | yes | |
| `avg_temp_c` | deg C, -60..70 | - | - | yes | |
| `min_temp_c` | deg C | yes | - | - | |
| `max_temp_c` | deg C | yes | - | - | |
| `elevation_loss_m` | m | yes | - | - | |
| `lap_count` | count, 0..10,000 | yes | - | - | |
| `aerobic_training_effect` | 0.0..5.0 | yes | - | - | |
| `anaerobic_training_effect` | 0.0..5.0 | yes | - | - | |
| `water_estimated_ml` | ml, 0..50,000 | yes | - | - | |
| `energy_kcal` | kcal, 0..20,000 | yes | yes | - | Zero becomes `None` in G and W. |
| `power_zone_times_s` | tuple of (`Z<n>`, s), max 20 | yes | - | yes | |
| `hr_zone_times_s` | tuple of (`Z<n>`, s), max 20 | yes | - | yes | |
| `pace_zone_times_s` | tuple of (`Z<n>`, s), max 20 | - | - | yes | |
| `planned_event_id` | text, max 200 | - | - | yes | Provider calendar event the activity was paired with. |
| `device_name` | text, max 200 | - | - | yes | |
| `training_effect_label` | upper-case text, max 50 | yes | - | - | |
| `external_ref` | `ExternalRef` (`upstream`, `upstream_id`) | - | - | yes | Upstream Garmin or Wahoo activity id of a synchronized copy. |
| `local_offset_minutes` | min, quarter-hour offset within 14 h | yes | yes | yes | Dates the activity on the day it was lived. |
| `terrain` | `Terrain` | yes | yes | yes | |
| `assist` | `Assist` | yes | yes | yes | |
| `native_type` | text, max 64 | yes | yes | yes | Provider type key / id / name as sent. |
| `purpose` | `ActivityPurpose` or `None` | yes | - | - | G only, from `eventType`. |

Helpers on the record module: `session_terrain(records)` returns the first non-`unknown` terrain in the given (primary first) order; `session_assist(records)` returns `electric` if any record says so, else the first non-`unknown` value.

### Canonical fields not produced by this scope

Every `ActivityRecord` field is set by at least one of the three mappers. Fields set only by the Intervals mapper, and therefore produced by no live provider since the Intervals ingest was removed: `intensity`, `weighted_avg_speed_mps`, `pace_mps`, `ftp_w`, `eftp_w`, `avg_temp_c`, `pace_zone_times_s`, `planned_event_id`, `device_name`, `external_ref`. Their values exist only on stored Intervals records until the purge (see `intervals_activity_mapping.py`). Enum members never emitted by these mappers: `ActivityPurpose` `training`, `warmup`, `cooldown`; `LoadModel` `trimp`; `DeviceType` `chest_strap`, `power_meter`; `RecordingOrigin` `strava` and `upload` by Garmin and Wahoo (Intervals only).

### `garmin_activity_mapping.py`

Status: Live. Called for every Garmin activity sync through `garmin_ingest_plan` (`canonical_plans.py`, via `_garmin_activity_mapper`), for replay of stored rows through `reprojection_plan`, and by `project_garmin_snapshot`.
Mapper version: **20**
Inputs: Garmin activity list rows (`get_activities_by_date`, SDK and Personal API share the key names), merged by `merge_training_load_rows` with the dedicated per-activity rows `training_load_activities` and `activity_ratings` (single-activity `summaryDTO`). Entry point `map_garmin_activities(rows, zone, retrieved_at)`.
Evidence: observed in `garmin_activity_list_entry_run_2026-11-03` (SDK) and `garmin_personal_activity_list_2026-11-03` (Personal API) for all keys not named under "documented" below; `directWorkoutRpe`, `directWorkoutFeel`, `minHR` observed under `summaryDTO` in `garmin_activity_detail_run_2026-11-03` and `garmin_personal_activity_detail_run_2026-11-03`. Documented only (code, no payload): `movingTime`, `averagePower`, `maxHeartRate`, `trainingEffect`, `averageBikingCadenceInRevPerMinute` (the sample is a run), `id` (alias of `activityId` in `merge_training_load_rows`), and zones above 5 (`hrTimeInZone_6`..`_20`, `powerTimeInZone_6`..`_20`). All sample values observed are from a run; ride and strength shapes are unverified against a payload.

General rules: first alias that carries a value wins (`_present`: not `None`, not blank text); a present but invalid value gives a `MappingIssue` and `None`, no fallback to a later alias (exception: start time). Numbers go through `coerce_number` (finite number or dot-decimal text) and a bounds check.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `activity_id` | `activityId` | int or text, 1..64 chars `[A-Za-z0-9][A-Za-z0-9_-]*`, stringified | `_activity_id`. Required; booleans rejected. A row without it is dropped. |
| `provenance` | - | `provenance.provider` = `garmin`; `provenance.source_kind` = `provider_reported`; `provenance.source_record_id` = `activity_id`; `provenance.retrieved_at` = argument; `provenance.label` = `GARMIN_LABEL` ("Garmin Connect") | `_provenance`. `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`. |
| `provenance.recorded_by` | `manualActivity`, `manufacturer` | `manualActivity` exactly `True` -> `manual`; else `manufacturer` upper-cased, text starting `WAHOO` -> `wahoo`, `ZWIFT` -> `zwift`; anything else -> `garmin` | `_recorded_by`. A Wahoo or Zwift recording relayed through Garmin Connect is therefore not a Garmin recording. Observed: `manualActivity`, `manufacturer` in both list payloads. |
| `started_at` | `startTimeGMT` -> `startTimeLocal` | ISO text; naive GMT read as UTC; naive local read as wall time in the athlete zone (`localize_wall_time`: ambiguous time -> first occurrence, spring gap -> forward); aware text keeps its offset | `_start_time`. An invalid GMT is reported and local is tried; both absent -> `MISSING`, row dropped. A value not representable in the athlete zone is rejected. Observed: both keys, naive 19-character text. |
| `local_offset_minutes` | `startTimeGMT`, `startTimeLocal` | `startTimeLocal` minus `startTimeGMT` (wall-clock difference), rounded to 15 min, within +-14 h (`wall_clock_offset_minutes`) | `_local_offset`. Only when `started_at` came from `startTimeGMT`; if local was the fallback, `None`. `timeZoneId` (observed in the SDK entry only) is not read. |
| `sport`, `environment` | `activityType.typeKey` (dict) or `activityType` (plain text) | key stripped, case-folded, cut to 200 chars; table `GARMIN_ACTIVITY_TYPES`; unknown key -> text classifiers on `typeKey` + space + `activityName` | `_type_key`, `_sport_and_environment`. Where the table gives `unknown`, `classify_environment_text` of the same identity text may set `virtual` (terms `virtual`, `zwift`) or `indoor` (`indoor`, `trainer`, `treadmill`, `laufband`). `outdoor` is set only by the table. Observed: `activityType.typeKey`. |
| `terrain`, `assist` | same key | `GARMIN_ACTIVITY_QUALIFIERS`; a key in the type table without an entry -> `unknown`, `none`; a key outside the table -> `unknown`, `unknown` | `_qualifiers`. |
| `native_type` | same key | the cleaned key cut to 64 chars | `None` without a key. |
| `duration_s` | `movingDuration`; `duration` -> `movingTime`; `elapsedDuration` -> `duration` | `activity_duration_s(sport, moving=movingDuration, timer=duration->movingTime, elapsed=elapsedDuration->duration)`, s | Strength: the longer elapsed time wins (`duration` is only the active timer time). Observed: `movingDuration`, `duration`, `elapsedDuration`; `movingTime` documented. |
| `moving_duration_s` | `movingDuration` | s, 0..604800 | No `movingTime` fallback (that key is a timer-time alias). |
| `elapsed_duration_s` | `elapsedDuration` -> `duration` | s | `movingTime` is not elapsed time and is excluded. |
| `distance_m` | `distance` | m, 0..2,000,000 | |
| `load` | `activityTrainingLoad` | Garmin training load, 0..10,000 | Overridden by a `training_load_activities` row of the same activity. Zero stays zero. |
| `load_model` | `activityTrainingLoad` | `garmin_training_load` if `load` is not `None`, else `unknown` | |
| `training_effect_label` | `trainingEffectLabel` | stripped, upper-cased, cut to 50 chars | Non-text -> `INVALID_TYPE`. Observed. |
| `avg_hr` | `averageHR` | bpm, 20..250 | |
| `max_hr` | `maxHR` -> `maxHeartRate` | bpm | |
| `min_hr` | `minHR` | bpm | From the `activity_ratings` row (observed in the detail `summaryDTO`, absent from the list rows). |
| `rpe` | `directWorkoutRpe` | raw 10..100, divided by 10 -> 1..10 | Watch RPE; the list rows carry it only through the merged rating row. |
| `feel` | `directWorkoutFeel` | raw 0 (very weak) .. 100 (very strong) -> `garmin_feel`: `5 - value / 25`, i.e. 100 -> 1 (strong), 0 -> 5 (weak) | Same conversion Intervals.icu applies on import. |
| `max_speed_mps` | `maxSpeed` | m/s | |
| `max_power_w` | `maxPower` | W | |
| `steps` | `steps` | count | |
| `avg_power` | `avgPower` -> `averagePower` | W | |
| `avg_speed_mps` | `averageSpeed` | m/s | |
| `grade_adjusted_speed_mps` | `avgGradeAdjustedSpeed` | m/s | Pace input of the local session load. |
| `elevation_gain_m` | `elevationGain` | m | |
| `normalized_power` | `normPower` | W | |
| `vo2max` | `vO2MaxValue` | 0..100 | Observed in the SDK entry only. |
| `aerobic_training_effect` | `aerobicTrainingEffect` -> `trainingEffect` | 0.0..5.0 | `trainingEffect` documented only. |
| `anaerobic_training_effect` | `anaerobicTrainingEffect` | 0.0..5.0 | |
| `elevation_high_m`, `elevation_low_m` | `maxElevation`, `minElevation` | m, -500..9000 | `_ordered_pair`: a minimum above its maximum drops both with one issue on `minElevation`. |
| `elevation_loss_m` | `elevationLoss` | m | |
| `min_temp_c`, `max_temp_c` | `minTemperature`, `maxTemperature` | deg C, -60..70 | Same pair rule. |
| `water_estimated_ml` | `waterEstimated` | ml, Garmin's sweat-loss estimate | |
| `lap_count` | `lapCount` | count | |
| `energy_kcal` | `calories` | kcal, whole-session estimate including the resting share; `calories or None` | Zero means not estimated. |
| `avg_cadence` | `averageBikingCadenceInRevPerMinute` else `averageRunningCadenceInStepsPerMinute` | bike: rpm as sent (used when truthy); run: steps/min divided by 2 (one leg) | `_cadence`. A bike value of 0 with no run key is no cadence (`None`), as for the other providers. Run key observed; bike key documented. |
| `hr_zone_times_s`, `power_zone_times_s` | `hrTimeInZone_1`..`_20`, `powerTimeInZone_1`..`_20` | s per zone, id `Z<n>` (`n` = key number); Garmin's own zone boundaries | `_zone_times`. Absent zones are skipped; one invalid zone drops the whole distribution with one issue. `_1`..`_5` observed. |
| `purpose` | `eventType.typeKey` (dict) or `eventType` (text) | stripped, case-folded: `race` -> `race`, `transportation` -> `commute`; everything else `None` | `_purpose`; non-text key -> `INVALID_TYPE`. Observed: `eventType.typeKey` (value was a plain category, so `None`). `training`, `warmup`, `cooldown` are never emitted. |
| `device_type` | - | `wahoo_device_type(sport, environment)` only when `provenance.recorded_by` is `wahoo`, else `None` | Garmin devices get no device type. |
| `name` | `activityName` | stripped, cut to 200 chars | Non-text -> `INVALID_TYPE`. |

#### Type tables

`GARMIN_ACTIVITY_TYPES` (`typeKey` -> sport, environment):

| `typeKey` | Sport | Environment |
|---|---|---|
| `cycling`, `bmx`, `e_bike_fitness`, `e_bike_mountain`, `gravel_cycling`, `mountain_biking`, `road_biking`, `track_cycling` | `ride` | `unknown` |
| `cyclocross` | `ride` | `outdoor` |
| `indoor_cycling` | `ride` | `indoor` |
| `virtual_ride` | `ride` | `virtual` |
| `running`, `street_running`, `track_running` | `run` | `unknown` |
| `trail_running`, `obstacle_run` | `run` | `outdoor` |
| `treadmill_running`, `indoor_running` | `run` | `indoor` |
| `virtual_run` | `run` | `virtual` |
| `lap_swimming` | `swim` | `unknown` |
| `open_water_swimming` | `swim` | `outdoor` |
| `walking` | `walk` | `unknown` |
| `indoor_walking`, `treadmill_walking` | `walk` | `indoor` |
| `hiking` | `hike` | `unknown` |
| `strength_training` | `strength` | `unknown` |
| `rowing` | `row` | `unknown` |
| `indoor_rowing` | `row` | `indoor` |
| `cross_country_skiing_ws`, `skate_skiing_ws` | `nordic_ski` | `unknown` |
| `resort_skiing_snowboarding_ws` | `alpine_ski` | `unknown` |
| `backcountry_skiing_snowboarding_ws`, `backcountry_skiing` | `alpine_ski` | `outdoor` |
| `yoga` | `yoga` | `unknown` |
| `pilates`, `hiit` | `other` | `unknown` |
| `indoor_cardio` | `other` | `indoor` |

Keys outside the table use `classify_sport_text` over the identity text; its ordered terms (substring, case-insensitive): `ride bike cycling rad velo bicycle` -> `ride`; `run lauf jog` -> `run`; `swim schwimm` -> `swim`; `strength kraft weight gym` -> `strength`; `walk geh` -> `walk`; `hike wander` -> `hike`; `row ruder` -> `row`; `nordic langlauf cross_country` -> `nordic_ski`; `alpine resort_ski` -> `alpine_ski`; `yoga` -> `yoga`; nothing -> `other`. Known false positives of substring matching (for example "stride" as ride) are inherited.

`GARMIN_ACTIVITY_QUALIFIERS` (`typeKey` -> terrain, assist):

| `typeKey` | Terrain | Assist |
|---|---|---|
| `road_biking`, `street_running` | `road` | `none` |
| `gravel_cycling` | `gravel` | `none` |
| `mountain_biking` | `mountain` | `none` |
| `track_cycling`, `track_running` | `track` | `none` |
| `e_bike_fitness` | `unknown` | `electric` |
| `e_bike_mountain` | `mountain` | `electric` |
| `trail_running`, `obstacle_run` | `trail` | `none` |
| `treadmill_running`, `treadmill_walking` | `treadmill` | `none` |
| `lap_swimming` | `pool` | `none` |
| `open_water_swimming` | `open_water` | `none` |

#### Dedicated rows merged before mapping (`merge_training_load_rows`)

| Section | Keys carried | Origin |
|---|---|---|
| `training_load_activities` | `activityTrainingLoad`, `trainingEffectLabel`, `aerobicTrainingEffect` / `trainingEffect`, `anaerobicTrainingEffect` | Garmin `get_training_load_activities`; documented (no payload). |
| `activity_ratings` | `directWorkoutRpe`, `directWorkoutFeel`, `minHR` | `rating_row` in `garmin.py` copies them from the single-activity `summaryDTO`; observed in the detail payloads. Re-read for activities of the last 3 days, once for unrated ones of the last 14 days, at most 30 reads per sync (`ACTIVITY_RATING_RECHECK_DAYS`, `ACTIVITY_RATING_NEW_DAYS`, `MAX_ACTIVITY_RATING_READS`). Manual activities (`manualActivity` true) are never read; reads run newest first and the first failed read ends that sync's reads. |

Rows are matched on `activityId` (else `id`). Rows of one id combine in order, `activity_ratings` first then `training_load_activities` (`DEDICATED_ACTIVITY_SECTIONS`), a later value replacing an earlier one including an explicit null. For each alias group (`_TRAINING_LOAD_FIELDS`) in which the combined row carries a non-null value, the activity row's own aliases of that group are dropped and replaced by the carried ones; a group the combined row leaves null keeps the activity row's own value. In the ingest, stored dedicated rows come first and the payload's own rows win (`_garmin_activity_mapper`).

Not mapped (present in the list payloads, ignored): `activityUUID`, the training-effect message texts (`aerobicTrainingEffectMessage`, `anaerobicTrainingEffectMessage`), `avgElevation`, `avgStrideLength`, `avgVerticalOscillation`, `avgVerticalRatio`, `avgGroundContactTime`, `avgGroundContactBalance`, `avgRespirationRate`, `minRespirationRate`, `maxRespirationRate`, `maxDoubleCadence`, `maxRunningCadenceInStepsPerMinute`, `maxVerticalSpeed`, `bmrCalories`, `autoCalcCalories`, `differenceBodyBattery`, `moderateIntensityMinutes`, `vigorousIntensityMinutes`, `beginTimestamp`, `endTimeGMT`, `timeZoneId`, `deviceId`, `sportTypeId`, `workoutId`, `splitSummaries`, `fastestSplit_*`, `minActivityLapDuration`, locations and coordinates, owner and privacy fields, flags (`favorite`, `pr`, `parent`, `hasSplits` ...). Reason: no canonical `ActivityRecord` field for them; detail-level data (splits, laps, streams) comes from the activity-detail mappers. `isManualActivity` duplicates `manualActivity`, which is the key read. Canonical fields this module never sets: `energy_kj`, `intensity`, `weighted_avg_speed_mps`, `pace_mps`, `ftp_w`, `eftp_w`, `avg_temp_c`, `pace_zone_times_s`, `planned_event_id`, `device_name`, `external_ref`.

### `wahoo_activity_mapping.py`

Status: Live. Called by `wahoo_ingest_plan` (`canonical_plans.py`) for the Wahoo Cloud workout sync, by `reprojection_plan`, and by `canonical_coverage_store`.
Mapper version: **8**
Inputs: Wahoo Cloud `GET /v1/workouts` rows (`WahooWorkoutFetch.workouts` from `wahoo_client.py`); each workout object with an embedded `workout_summary`. Entry point `map_wahoo_activities(rows, zone, retrieved_at)` (`zone` is accepted and unused; Wahoo sends UTC). `raw_workout_for_storage` drops `workout_summary.file` (a download URL) before the raw row is stored.
Evidence: documented only. There is no Wahoo payload in the sanitized set. Sources: the module docstring (Wahoo Cloud API documentation as cited by the mapper), and the synthetic test fixture rows in `test_wahoo_activity_mapping` (inline `row()` helper: keys `id`, `starts`, `minutes`, `name`, `workout_type_id`, `workout_summary.*`). All provider keys below are "documented".

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `activity_id` | `id` | positive integer up to 2^63-1, or ASCII digit text of at most 19 digits | `workout_id`. Missing / not an integer / out of range -> issue, row dropped. |
| `provenance` | - | `provenance.provider` = `wahoo`; `provenance.source_kind` = `provider_reported`; `provenance.source_record_id` = `activity_id`; `provenance.recorded_by` = `wahoo` (always); `provenance.retrieved_at` = argument; `provenance.label` = `WAHOO_LABEL` ("Wahoo") | `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`. |
| `started_at` | `starts` | ISO 8601 instant, UTC; text without offset read as UTC | `started_at()`. Missing / unparsable -> issue, row dropped. |
| `local_offset_minutes` | `time_zone` | IANA zone name -> its UTC offset at `started_at`, rounded to 15 min (`zone_offset_minutes`) | Any other value -> `None`, so the athlete zone dates the workout. |
| `sport`, `environment`, `terrain`, `assist` | `workout_type_id` | integer, or ASCII digit text of at most 6 digits; table `WAHOO_WORKOUT_TYPES`, `WAHOO_WORKOUT_QUALIFIERS` | `workout_type()` / `_classify`. Missing -> `MISSING`; not an integer -> `INVALID_TYPE`; id outside the table -> `UNKNOWN_VALUE`; all three give `other`, `unknown`, `unknown`, `unknown` (no row drop). |
| `native_type` | `workout_type_id` | decimal text of the id | `None` when the id is missing or unknown. |
| `duration_s` | `workout_summary.duration_active_accum`; `workout_summary.duration_total_accum` | `activity_duration_s(sport, moving=active, timer=None, elapsed=total)` | The workout's own `minutes` is the planned duration and is never used. |
| `moving_duration_s` | `workout_summary.duration_active_accum` | s, 1..604800 | Values below 1 s (including 0) give `OUT_OF_RANGE` and `None`. |
| `elapsed_duration_s` | `workout_summary.duration_total_accum` | s, 1..604800 | Same minimum. |
| `distance_m` | `workout_summary.distance_accum` | m | Decimal text, null until Wahoo has processed the workout. |
| `load` | `workout_summary.power_bike_tss_last` | Training Stress Score; zero or missing -> `None` | |
| `load_model` | same key | `tss` if `load` is not `None`, else `unknown` | Never mixed with other providers' loads. |
| `avg_hr` | `workout_summary.heart_rate_avg` | bpm | |
| `avg_power` | `workout_summary.power_avg` | W | |
| `elevation_gain_m` | `workout_summary.ascent_accum` | m | Zero is a real flat course and stays 0. |
| `normalized_power` | `workout_summary.power_bike_np_last` | W; zero -> `None` | |
| `avg_cadence` | `workout_summary.cadence_avg` | rpm as sent; zero -> `None` | |
| `energy_kj` | `workout_summary.work_accum` | joules divided by 1000 (`_JOULES_PER_KJ`); zero -> `None` | |
| `energy_kcal` | `workout_summary.calories_accum` | kcal; zero -> `None` | |
| `device_type` | - | `wahoo_device_type(sport, environment)` | See below. |
| `name` | `name` | stripped, cut to 200 chars; empty -> `None`; non-text -> `INVALID_TYPE` | |

Summary numbers arrive as decimal text and may be null until processed; a missing `workout_summary` is not an error, a non-object one gives `INVALID_TYPE`.

#### `wahoo_device_type` helper

Defined in `wahoo_activity_mapping.py`; `garmin_activity_mapping.py` imports it. Returns `bike_computer` when `sport` is `ride` and `environment` is `outdoor` or `unknown` (road, mountain and track rides name no environment); `None` for indoor/virtual rides and every other sport. Because of the `unknown` case a Wahoo e-bike ride (type 64) also counts as bike computer. Garmin uses it only when its row's `provenance.recorded_by` is `wahoo`.

#### Type tables

`WAHOO_WORKOUT_TYPES` (`workout_type_id` -> sport, environment). The ids are taken from the Wahoo Cloud API documentation as cited in the code; generic types (workout, fitness equipment, cardio class, unknown), motorised and sail/board types are `other`.

| Ids | Sport | Environment |
|---|---|---|
| 0, 11 | `ride` | `outdoor` |
| 12, 21, 49, 61 | `ride` | `indoor` |
| 68 | `ride` | `virtual` |
| 13, 14, 15, 16, 64, 70 | `ride` | `unknown` |
| 1, 4, 67 | `run` | `outdoor` |
| 3 | `run` | `unknown` |
| 5 | `run` | `indoor` |
| 71 | `run` | `virtual` |
| 6, 7, 8 | `walk` | `outdoor` |
| 56 | `walk` | `indoor` |
| 9, 10 | `hike` | `outdoor` |
| 25 | `swim` | `unknown` |
| 26 | `swim` | `outdoor` |
| 22 | `row` | `indoor` |
| 39 | `row` | `unknown` |
| 30 | `nordic_ski` | `outdoor` |
| 29 | `alpine_ski` | `outdoor` |
| 66 | `yoga` | `unknown` |
| 19, 20, 23, 44 | `other` | `indoor` |
| 2, 17, 18, 27, 28, 31-38, 40-43, 45-47, 62, 63, 65, 69, 255 | `other` | `unknown` |

`WAHOO_WORKOUT_QUALIFIERS` (id -> terrain, assist; every other id in the table above is `unknown`, `none`):

| Id | Terrain | Assist | Meaning in the code comment |
|---|---|---|---|
| 3 | `track` | `none` | running track |
| 4 | `trail` | `none` | trail running |
| 5 | `treadmill` | `none` | treadmill |
| 13 | `mountain` | `none` | mountain bike |
| 15 | `road` | `none` | road bike |
| 16 | `track` | `none` | track cycling |
| 25 | `pool` | `none` | lap swimming |
| 26 | `open_water` | `none` | open water swimming |
| 56 | `treadmill` | `none` | treadmill walking |
| 64 | `unknown` | `electric` | e-bike |

Not mapped: the workout's `minutes` (planned duration); the summary's speed and its `file` object (download location; removed by `raw_workout_for_storage`); every other workout or summary key (the module reads only the keys above; their names are unverified here). Canonical fields this module never sets: `max_hr`, `max_speed_mps`, `max_power_w`, `min_hr`, `elevation_high_m`, `elevation_low_m`, `steps`, `intensity`, `rpe`, `feel`, `avg_speed_mps`, `weighted_avg_speed_mps`, `grade_adjusted_speed_mps`, `pace_mps`, `ftp_w`, `eftp_w`, `vo2max`, temperatures, `elevation_loss_m`, `lap_count`, training-effect fields, `water_estimated_ml`, zone times, `planned_event_id`, `device_name`, `training_effect_label`, `external_ref`, `purpose`.

### `intervals_activity_mapping.py`

Status: Retired (stored-data replay only; no new data). Intervals.icu is an output target only and its activities are not read (`docs/features.md`, "Output-only Intervals.icu"; `backend/sync/intervals_ingest.py`: "Intervals.icu is output only and is not read any more"). No code path fetches Intervals.icu activities (`intervals_client.py` and `intervals.py` contain no activity read). The mapper remains called for stored data: `intervals_snapshot_ingest_plan` / `intervals_ingest_plan` (from `_ingest_work` in `canonical_backfill.py`, which reads stored snapshots), `reprojection_plan` / `_reprojected_activities` (`canonical_plans.py`, replay of stored raw rows), `project_intervals_snapshot` and `intervals_row_local_date` (`snapshot_projection.py`, used by `canonical_coverage_store.intervals_snapshot_coverage`). The one-off purge (#1728, `backend/sync/intervals_purge.py`) tombstones every Intervals.icu activity, deletes the Intervals.icu rows and snapshots and sets a completion marker; the session builder then falls back to the Garmin or Wahoo copy. `INTERVALS_LABEL` is still imported by performance modules as a source label.
Mapper version: **10**
Inputs: stored Intervals.icu activity rows (`raw_provider_data.activities` of a snapshot, or one stored raw record). Entry point `map_intervals_activities(rows, zone, retrieved_at)`; `zone` localises naive `start_date_local`.
Evidence: observed in `intervals_activity_ride_outdoor_wahoo`, `intervals_activity_ride_virtual_zwift`, `intervals_activity_run_garmin_2026-11-03`, `intervals_activity_strength_garmin` unless marked documented. Documented only (key absent from all four payloads): `averageHR`, `maxHR`, `max_watts`, `average_watts`, `average_power`, `weighted_average_watts`, `normalized_power`, `rpe`, `icu_weighted_avg_speed`, `icu_pace`, `icu_eftp`, `eftp`, `eFTP`, `vo2max`, `vo2_max`, `vO2MaxValue`, `vo2MaxValue`, `icu_vo2max`, `sport`, `sport_type`, `activityType`, `activityName`. Present in the payloads but null in all four: `timezone`, `pool_length`.

Alias rule: first usable value wins; a malformed alias gives an issue and the next alias is tried. Numbers: `coerce_number` and bounds.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `activity_id` | `id` | int (at most 800 bits) or text, stripped, at most 200 chars | `activity_id()`. Required. |
| `provenance` | `source`, `device_name`, `external_id` | `provenance.provider` = `intervals`; `provenance.source_kind` = `provider_reported`; `provenance.source_record_id` = `activity_id`; `provenance.retrieved_at` = argument; `provenance.label` = `INTERVALS_LABEL` ("Intervals.icu") | `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`. |
| `provenance.recorded_by` | `source`, `device_name`, `external_id` | `_recording_origin`: `source` equal to `manual` (case-folded, stripped) -> `manual`; else the case-folded join of the three texts is searched for the terms, first group wins: `wahoo` or `elemnt` -> `wahoo`; `garmin` -> `garmin`; `zwift` -> `zwift`; `strava` -> `strava`; `manual` -> `manual`; `upload` -> `upload`; the whole word `file` -> `upload`; else `unknown` | The recording device beats a sync source such as Strava. Observed `source` values: `WAHOO`, `ZWIFT`, `GARMIN_CONNECT`. |
| `started_at` | `start_date` -> `start_date_local` | `start_date` only if it carries its own offset (`Z`, `+hh:mm`); a naive `start_date` is reported (`INVALID_TYPE`) and skipped; `start_date_local` is athlete wall time localised by `parse_provider_datetime` | `started_at()`. Observed: `start_date` with `Z` (20 chars), `start_date_local` naive (19 chars). |
| `local_offset_minutes` | `timezone`, `start_date_local`, `start_date` | only with an exact `start_date`: `zone_offset_minutes(timezone)` (IANA zone at that instant), else `wall_clock_offset_minutes(start_date_local)` (local minus UTC, rounded to 15 min) | `_local_offset`. `timezone` is null in all four payloads, so the `start_date_local` difference applies. |
| `sport`, `environment` | `type`, plus identity text from `type`, `sport`, `sport_type`, `activityType`, `activityName`, `name` | `INTERVALS_ACTIVITY_TYPES` by exact `type`; other names -> `classify_sport_text` of the space-joined identity text (terms as listed under `garmin_activity_mapping.py`); `unknown` environments refined by `classify_environment_text` of the same text | `_classify`. `outdoor` only where the type name denotes it. Observed `type`: `Ride`, `VirtualRide`, `Run`, `WeightTraining`. |
| `terrain`, `assist` | `type`, `pool_length` | `INTERVALS_ACTIVITY_QUALIFIERS`; `Swim` with `pool_length` > 0 -> `pool`, `none`; other known type -> `unknown`, `none`; unknown type -> `unknown`, `unknown` | `_qualifiers`. |
| `native_type` | `type` | stripped, cut to 64 chars | |
| `duration_s` | `moving_time`, `elapsed_time` | `activity_duration_s(sport, moving=moving_time, timer=None, elapsed=elapsed_time)`, s | Each of the two must be at least 1 s (zero -> `OUT_OF_RANGE`, then the other is used). |
| `moving_duration_s` | `moving_time` | s, 1..604800 | |
| `elapsed_duration_s` | `elapsed_time` | s, 1..604800 | Kept so session bundling can compare it with a Garmin elapsed time. |
| `distance_m` | `distance` | m | Null in one payload (strength). |
| `load` | `icu_training_load` | Intervals.icu training load (TSS scale), 0..10,000 | |
| `load_model` | same | `intervals_training_load` if `load` is not `None`, else `unknown` | |
| `avg_hr` | `average_heartrate` -> `averageHR` | bpm | |
| `max_hr` | `max_heartrate` -> `maxHR` | bpm | |
| `avg_power` | `average_watts` -> `average_power` | W | `icu_average_watts` (observed, non-null in 3 of 4) is deliberately not read, so with these payloads `avg_power` is `None`. |
| `max_speed_mps` | `max_speed` | m/s | |
| `max_power_w` | `max_watts` | W | |
| `elevation_gain_m` | `total_elevation_gain` | m | |
| `normalized_power` | `icu_weighted_avg_watts` -> `weighted_average_watts` -> `normalized_power` | W | |
| `avg_cadence` | `average_cadence` | rpm as sent (no halving for runs) | |
| `intensity` | `icu_intensity` | % of FTP, 0..1000 | |
| `rpe` | `icu_rpe` -> `rpe` | 0..10 as sent | Observed `icu_rpe` (non-null in the Garmin run). |
| `feel` | `feel` | 0..10 as sent; Intervals scale 1 strong .. 5 weak | Observed (non-null in the Garmin run). |
| `avg_speed_mps` | `average_speed` | m/s | |
| `weighted_avg_speed_mps` | `icu_weighted_avg_speed` | m/s | |
| `pace_mps` | `icu_pace` | stored as sent under the m/s name; the provider unit of this key is unverified (key absent from the payloads) | |
| `ftp_w` | `icu_ftp` | W | |
| `eftp_w` | `icu_eftp` -> `eftp` -> `eFTP` | W | |
| `vo2max` | `vo2max` -> `vo2_max` -> `vO2MaxValue` -> `vo2MaxValue` -> `icu_vo2max` | 0..100 | |
| `avg_temp_c` | `average_temp` | deg C, -60..70 | Minimum and maximum temperature are not mapped. |
| `power_zone_times_s` | `icu_zone_times` | list of `{id, secs}`; ids starting `Z` kept (`Z1`..), others (for example sweet spot) skipped | `_zone_seconds(positional=False)`; at most 20 zones, secs 0..604800, negative skipped. Observed shape `{id, secs}`. |
| `hr_zone_times_s` | `icu_hr_zone_times` | list of plain numbers (position n -> `Z<n>`) or `{id, secs}` objects | `_zone_seconds(positional=True)`. Observed: list of numbers. |
| `pace_zone_times_s` | `pace_zone_times` | list; `{id, secs}` items with ids starting `Z` are kept | Observed key, but its only non-null value (run payload) is a list of plain numbers; the mapper reads dict items only (`positional=False`), so the observed shape maps to none. The `{id, secs}` shape is documented only. `gap_zone_times` is present in the payload and not read. |
| `planned_event_id` | `paired_event_id` | int or text, stripped, at most 200 chars | Observed value `0` (3 of 4 payloads) is stored as the text `0`, not treated as absent; null gives none. |
| `device_name` | `device_name` | stripped, cut to 200 chars | Non-text -> `INVALID_TYPE`. Observed. |
| `device_type` | `device_name` | whole-word match in the case-folded name (`_device_type`); `bike_computer` terms are checked first, then `watch` terms | Terms below. Brand-only names stay `None`. |
| `external_ref` | `source`, `external_id` | `ExternalRef(upstream, upstream_id)`; `source` case-folded `garmin_connect` -> upstream `garmin`, `wahoo` -> upstream `wahoo`; `upstream_id` = `external_id` (at most 200 chars) | `_external_ref`. Other sources (`STRAVA`, `ZWIFT`, `UPLOAD`, ...) give no reference. This is the exact link key used by session bundling. Observed `source`/`external_id` in all four. |
| `name` | `name` | stripped, cut to 200 chars | |

Device terms (`_DEVICE_TYPE_TERMS`): `bike_computer`: `edge`, `elemnt`, `bolt`, `roam`, `karoo`, `dura`, `v650`, `m450`, `m460`, `bryton rider`. `watch`: `forerunner`, `fenix`, `fēnix`, `epix`, `venu`, `enduro`, `instinct`, `vivoactive`, `apple watch`, `pace`, `apex`, `vertix`, `vantage`, `grit`, `pacer`, `ignite`, `suunto 5`, `suunto 9`, `suunto race`, `suunto vertical`.

`INTERVALS_ACTIVITY_TYPES` (`type` -> sport, environment):

| `type` | Sport | Environment |
|---|---|---|
| `Ride`, `EBikeRide`, `EMountainBikeRide`, `GravelRide`, `Handcycle`, `MountainBikeRide`, `Velomobile` | `ride` | `unknown` |
| `VirtualRide` | `ride` | `virtual` |
| `Run` | `run` | `unknown` |
| `VirtualRun` | `run` | `virtual` |
| `TrailRun` | `run` | `outdoor` |
| `Swim` | `swim` | `unknown` |
| `OpenWaterSwim` | `swim` | `outdoor` |
| `Walk` | `walk` | `unknown` |
| `Hike` | `hike` | `outdoor` |
| `WeightTraining` | `strength` | `unknown` |
| `Rowing` | `row` | `unknown` |
| `VirtualRow` | `row` | `virtual` |
| `NordicSki`, `RollerSki` | `nordic_ski` | `unknown` |
| `AlpineSki` | `alpine_ski` | `unknown` |
| `BackcountrySki` | `alpine_ski` | `outdoor` |
| `Yoga` | `yoga` | `unknown` |
| `Badminton`, `Canoeing`, `Crossfit`, `Elliptical`, `Golf`, `HighIntensityIntervalTraining`, `IceSkate`, `InlineSkate`, `Kayaking`, `Kitesurf`, `Padel`, `Pilates`, `Pickleball`, `Racquetball`, `Rugby`, `RockClimbing`, `Sail`, `Skateboard`, `Snowboard`, `Snowshoe`, `Soccer`, `Squash`, `StairStepper`, `StandUpPaddling`, `Surfing`, `TableTennis`, `Tennis`, `Transition`, `WaterSport`, `Wheelchair`, `Windsurf` | `other` | `unknown` |

`Workout` and `Other` are not in the table; they are classified from the identity text.

`INTERVALS_ACTIVITY_QUALIFIERS` (`type` -> terrain, assist): `TrailRun` `trail`, `none`; `GravelRide` `gravel`, `none`; `MountainBikeRide` `mountain`, `none`; `EBikeRide` `unknown`, `electric`; `EMountainBikeRide` `mountain`, `electric`; `OpenWaterSwim` `open_water`, `none`.

`intervals_analysis_sport(row)` returns `sport`, `environment` and a `trail` flag (terrain is `trail`) using the same classification; it has no caller in `backend/` or `server.py` besides tests.

Not mapped: `icu_average_watts` (observed; see `avg_power`), `trainer` (observed; no trainer flag is read), `calories` (observed; not mapped to `energy_kcal`), `max_temp` and `min_temp` (observed; only `average_temp` is read), `total_elevation_loss`, `average_altitude`, `max_altitude`, `min_altitude`, `race` and `commute` (observed; not mapped to `purpose`, whose only provider source is the Garmin event type), `session_rpe`, `perceived_exertion`, `trimp`, `hr_load`, `power_load`, `pace_load`, `icu_ctl`, `icu_atl`, `icu_rolling_ftp`, `icu_efficiency_factor`, `icu_variability_index`, `decoupling`, `lthr`, `gear`, `tags`, `description`, `strava_id`, weather fields and the remaining Intervals.icu analysis fields; reason: no `ActivityRecord` field, or computed locally. Canonical fields this module never sets: `min_hr`, `elevation_high_m`, `elevation_low_m`, `steps`, `grade_adjusted_speed_mps`, `min_temp_c`, `max_temp_c`, `elevation_loss_m`, `lap_count`, `aerobic_training_effect`, `anaerobic_training_effect`, `water_estimated_ml`, `energy_kj`, `energy_kcal`, `training_effect_label`, `purpose`.

### `intervals_activity_fields.py`

Status: Retired in effect. The activity mapper does not import it. Its constants are used by `intervals_activity_detail_mapping.py` (`activity_detail_laps`, reads `icu_intervals`) and `intervals_workouts.py` (`REMOTE_EVENT_METRIC_KEYS`, the planned-unit metrics a synced remote event carries back: `moving_time`, `workout_doc`, `icu_training_load`, `icu_intensity`). `ACTIVITY_FIELDS` names the Intervals.icu compact row shape (`id`, `start_date_local`, `name`, `type`, `moving_time`, `distance`, `total_elevation_gain`, `elapsed_time`, `icu_training_load`, `icu_intensity`, `icu_ctl`, `icu_atl`, `icu_ftp`, `icu_eftp`, `average_heartrate`, `max_heartrate`, `average_watts`, the weighted-power aliases, `average_speed`, `max_speed`, `icu_weighted_avg_speed`, `icu_pace`, the VO2max aliases, `feel`, `icu_rpe`, `paired_event_id`, `source`, `device_name`, `external_id`, `file_type`).
Mapper version: none (no `MAPPER_VERSION`).
Inputs: raw Intervals.icu activity rows (stored).
Evidence: observed for the keys that exist in the four Intervals payloads (all except the VO2max aliases, `icu_eftp`, `icu_pace`, `icu_weighted_avg_speed`, `average_watts`, `weighted_average_watts`, `normalized_power`, which are documented only); `file_type` observed.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `provenance.recorded_by` (value only, no record built) | `source`, `device_name`, `external_id` | `intervals_activity_device_source`: `source` equal to `manual` -> none; the case-folded join of the three texts containing `wahoo` or `elemnt` -> `wahoo`; containing `garmin` -> `garmin`; else none | Returns a `RecordingOrigin` or `None`; `intervals_activity_recorded_by_wahoo` is true when it is `wahoo`. Neither function has a caller in `backend/` or `server.py` besides tests and the architecture registry (verified by search). Unlike `_recording_origin` in the mapper it knows no `zwift`, `strava`, `upload` or `unknown`. |

Not mapped: it builds no `ActivityRecord`. `ACTIVITY_FIELDS` and the `ACTIVITY_DETAIL_*` constants (`ACTIVITY_DETAIL_PARAMS`, `ACTIVITY_DETAIL_STREAM_TYPES`, `ACTIVITY_DETAIL_STREAM_ALIASES`) have no production caller; only tests use them.

### `intervals_activity_keys.py`

Status: Retired in effect; not used by the activity mapper. Used by `activity_detail_projection`, `detail_store` (`LACTATE_THRESHOLD_HR`), `workout_text` (`activity_training_load`) and `diagnostics/provider_composition.py` (`ACTIVITY_SOURCES`).
Mapper version: none.
Inputs: stored Intervals.icu activity rows.
Evidence: observed `icu_training_load`, `icu_ftp`, `lthr`, `icu_rolling_ftp` and `source` in the Intervals payloads; the full `ACTIVITY_SOURCES` enum (`STRAVA`, `UPLOAD`, `MANUAL`, `GARMIN_CONNECT`, `OAUTH_CLIENT`, `DROPBOX`, `POLAR`, `SUUNTO`, `COROS`, `WAHOO`, `ZWIFT`, `ZEPP`, `CONCEPT2`, `HUAWEI`) is documented (Intervals.icu Activity schema), only four values observed.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| none | `icu_training_load` -> `training_load` -> `tss` (`TRAINING_LOAD_LOOKUP`), `icu_ftp` (`activity_ftp`), `lthr` (`activity_lthr`), `icu_rolling_ftp` | none | Wire-key lookups for the legacy activity projections; no canonical `ActivityRecord` field is produced. |

Not mapped: it constructs no record and emits no enum member.

### `garmin_fields.py`

Status: Live, but not used by the activity mapper. `garmin_activity_mapping.py` does not import it; it holds shared Garmin health aliases (`first_present`, `GARMIN_DATE_ALIASES`, sleep, HRV, weight, FTP, readiness aliases) used by the health, weight and performance mappers (`garmin_health_mapping.py`, `garmin_training_mapping.py`, `garmin_weight_walk.py`, `garmin_performance_fields.py`, `sleep_period_mapping.py`). The one overlap with activities is the key `calories` inside `GARMIN_TOTAL_KCAL_ALIASES`, which belongs to the daily summary, not to the activity row.
Mapper version: none.
Inputs: Garmin daily and wellness payloads.
Evidence: documented only for this scope (it contributes no activity field).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| none for `ActivityRecord` | - | - | The activity aliases live in `garmin_activity_mapping.py`. |

Not mapped: all activity keys; see `garmin_activity_mapping.py`.

## Activity summary resolution

One "session" bundles the active records of every provider that reported the same activity; `activity_summary(session_id, records, zone)` (`backend/activities/activity_summary.py`) turns the records into one `ActivitySummary` (`backend/canonical/activity_summary.py`). Readers (`canonical_read_selector.activity_summaries`) add stored local values afterwards.

### Record order

| Order | Function | Sort key | Used for |
|---|---|---|---|
| measured | `measured_order` (`detail_contract.py`) | (1) own copy first, (2) provider rank, (3) recording-origin rank (`wahoo` 0, `garmin` 1, others 2), (4) newest `provenance.retrieved_at` first (a record without one last), (5) `activity_id` ascending | the primary record, header fields, all measured values, `terrain`, `assist`, `local_offset_minutes` |
| derived | `derived_order` | (2), (3), (4) of the above: provider rank, newest retrieval, id | derived values, zone times, provider load, training effect, `purpose`, `planned_event_id` |
| rating | `rating_order` | `derived_order`, stably re-sorted by provider: `garmin` 0, `intervals` 1, everything else 2 | `rpe`, `feel`, `rpe_conflict` |

`PROVIDER_PRECEDENCE` (`vocabulary.py`) = `wahoo`, `garmin`, `intervals` (Intervals.icu is output only and ranks last). The own-copy rule: a record is the recording platform's own copy when `provenance.provider.value == provenance.recorded_by.value`. A Garmin Connect row of a Wahoo-recorded ride (`provenance.provider` `garmin`, `provenance.recorded_by` `wahoo`) is therefore not own and ranks behind the Wahoo cloud record; a Zwift-recorded row is own for no provider; an Intervals.icu record is never own (its provider value `intervals` matches no recording origin). The session's primary record (`measured[0]`) is persisted by `bundle_sessions` with the same preference (`_lead_key`: provider rank, then Wahoo-recorded before others, then input order).

Tie-break note: the summary and the `activity_detail.v1` document's `session` block share this one order; the origin step only separates records of the same provider rank that are both non-own (in practice stored Intervals.icu copies).

### Value choice per summary key

`_values` takes, for each key, the first record in the stated order whose `ActivityRecord` field is not `None`, and records that record's `provenance.label` in `sources[key]`. A value is never combined across records.

| Group | `ActivitySummary` keys | Order | Record field |
|---|---|---|---|
| header | `started_at` (primary `started_at.isoformat()`), `sport`, `environment`, `recorded_by` (`provenance.recorded_by`), `device_type` (primary only; absent if the primary has none), `source` (label of the primary) | primary of measured order | same name |
| name | `name` | first non-`None` in measured order | `name` |
| qualifiers | `terrain` (left out when `unknown`), `assist` (present only as `electric`) | measured | `session_terrain`, `session_assist` |
| local time | `started_at_local`, `local_offset_minutes` | measured | offset = first record with `local_offset_minutes`; `started_at_local` = primary `started_at` read on that offset, else on the athlete zone (`session_local_start`, `wall_time`), naive ISO to the second; `local_offset_minutes` present only when some record has one |
| measured values | `moving_duration_s`, `elapsed_duration_s`, `distance_m`, `elevation_gain_m`, `elevation_loss_m`, `avg_hr`, `max_hr`, `avg_power`, `avg_cadence`, `avg_speed_mps`, `max_speed_mps`, `avg_temp_c`, `min_temp_c`, `max_temp_c`, `device_name`, `energy_kj`, `energy_kcal` | measured (`_MEASURED`) | same name |
| derived values | `normalized_power`, `weighted_avg_speed_mps`, `pace_mps`, `provider_intensity` (from `intensity`), `grade_adjusted_speed_mps`, `ftp_w`, `vo2max`, `planned_event_id` | derived (`_DERIVED`) | same name except `provider_intensity` |
| provider zones | `power_zone_times`, `heart_rate_zone_times`, `pace_zone_times` | derived order over records whose provider is not Intervals.icu (#1743) | `power_zone_times_s`, `hr_zone_times_s`, `pace_zone_times_s`, as `[{"id": "Z1", "secs": ...}]` |
| ratings | `rpe`, `feel` | rating | `rpe`, `feel` |
| provider load | `provider_training_load`, `provider_load_model` | first derived record with `load` not `None` and `load_model` in `TSS_LIKE_LOAD_MODELS` (`intervals_training_load`, `tss`); a Garmin load is never TSS-like | `load`, `load_model` |
| training effect | `training_effect_label`, `aerobic_training_effect`, `anaerobic_training_effect`, `training_effect_load` | one record: first derived record with a label, else the first with an aerobic or anaerobic value; load only when its `load_model` is `garmin_training_load` | same names, `load` |
| purpose | `purpose` | `session_purpose(derived)`: a record with `race` wins, else the first non-`None` purpose in derived order; only Garmin sets one; the athlete's marking (`activity_feedback.purpose`) replaces it when the summaries are read (`with_marked_purposes`) | `purpose` |
| identifiers | `id`, `record_ids` | `id` = local session id; `record_ids` maps each provider (`garmin`, `wahoo`, `intervals`) to the activity id of its first record in measured order | `activity_id` |
| source labels | `sources` | maps the measured, derived, zone, rating, `provider_training_load`, training-effect (label and the two effect values) and `purpose` keys to their record's label (`Garmin Connect`, `Wahoo`, `Intervals.icu`); the header, name, qualifier, local-time, identifier, `provider_load_model` and `training_effect_load` keys have no `sources` entry (`source` names the primary record's label); `training_load`, `intensity`, `efficiency_factor`... map to `derived`; `purpose` from a competition maps to `COMPETITION_SOURCE_LABEL` | `provenance.label` |

Measured versus derived: measured values are the device's own recording and prefer the recording platform's own copy; derived values (normalized power, pace, FTP, zones, load, training effect, purpose) prefer the provider rank only, because they are computed by the provider's platform and the own-copy preference gives no accuracy gain.

Ratings: the athlete rates on the Garmin watch and Intervals.icu imports that rating, so `rating_order` puts Garmin before Intervals.icu, then Wahoo and others (which set no rating). `rpe_conflict` is `True` when the records of the provider whose rating the summary uses (the provider of the first record with an `rpe`) report different `rpe` values. The local feedback RPE (athlete entry) stays authoritative over both; it is not part of the `ActivitySummary` provider fields. Scales (`rating_scales.py`, applied in `activity_detail.v1`): Garmin and Intervals RPE 1..10 (higher is harder), feel 1..5 (higher is worse; Garmin labels 1 "sehr stark" .. 5 "sehr schwach", Intervals 1 "stark" .. 5 "schwach").

Purpose and competition link: `with_competitions` (`session_purpose.py`) links each stored competition to the sessions of its local date (`summary_local_date`) and canonical sport; indoor/virtual and outdoor must agree when both are known; `commute`, `warmup` and `cooldown` sessions are never candidates. A provider `race` session is linked first (the one nearest the competition's local start; a stored midnight start counts as unknown; sessions already linked are skipped); a day with provider races never gets a hint. Without a provider race the competition marks the session nearest its start time (else the longest, then the earliest); with a planned duration the session must last at least half of it (`MIN_HINT_SHARE_OF_PLANNED`). The linked summary gets `competition_id` and, if it was not already a race, `purpose` = `race` with `sources["purpose"]` = `COMPETITION_SOURCE_LABEL`. A session links to at most one competition.

### Session bundling of the records (who is in a session)

`bundle_sessions` (`canonical_sessions.py`) assigns records one to one; `link_activity_sessions` / `split_unmatched_sessions` (`session_linking.py`) persist and undo it. Keys the mappers supply: `activity_id` and `provenance.provider`; `started_at` (compared on the athlete wall clock); `sport` (legacy family: cycling, running, swimming, strength, else other); `duration_s`, `moving_duration_s`, `elapsed_duration_s`, `distance_m`; `provenance.recorded_by`; `external_ref` (Intervals only). Rules:

| Rule | Condition |
|---|---|
| exact link (`_assign_exact`) | an Intervals.icu record whose `external_ref` names a stored Garmin or Wahoo record joins it whatever the times say; one record per provider per session; link kind `exact` |
| Garmin or Wahoo vs Intervals.icu | starts within 30 min, same sport family (or either `other`), every comparable measurement agrees: duration within max(120 s, 10 % of the Intervals value) against `duration_s` or the Garmin `moving_duration_s` (elapsed pass: elapsed against elapsed), distance within max(500 m, 10 % of the Intervals value) when both are non-zero; a Wahoo record only joins a Wahoo-recorded Intervals copy |
| Garmin ride vs Wahoo ride (`_wahoo_copy_cost`) | both `ride`, starts within 30 min, `duration_s` and `distance_m` present and positive on both and within max(120 s, 10 % of the larger) and max(500 m, 10 % of the larger); link kind `heuristic` |

Each pass is a one-to-one minimum-cost assignment (cost = mean of the start gap as a share of the window and each compared gap as a share of its tolerance); the primary is the Wahoo record, else the Garmin record, else the Intervals.icu record. Athlete corrections (confirm, split, merge) override these rules.

### `ActivitySummary` keys

Every key of the `ActivitySummary` TypedDict (`total=False`; only values some record reports are present). Units as stored.

| Key | Source field | Unit / type |
|---|---|---|
| `id` | local session id | text |
| `started_at` | primary `started_at` | ISO datetime with offset |
| `started_at_local` | primary `started_at` on the session offset or athlete zone | naive ISO datetime, seconds |
| `local_offset_minutes` | first `local_offset_minutes` in measured order | minutes |
| `name` | `name` | text |
| `sport` | primary `sport` | `Sport` value |
| `environment` | primary `environment` | `Environment` value |
| `terrain` | `session_terrain` | `Terrain` value, absent when `unknown` |
| `assist` | `session_assist` | only `electric` |
| `recorded_by` | primary `provenance.recorded_by` | `RecordingOrigin` value |
| `device_type` | primary `device_type` | `DeviceType` value |
| `device_name` | `device_name` | text |
| `source` | primary `provenance.label` | text |
| `sources` | per-key `provenance.label` or `derived` | mapping key -> label |
| `record_ids` | `activity_id` per provider | mapping provider -> id |
| `moving_duration_s` | `moving_duration_s` | s |
| `elapsed_duration_s` | `elapsed_duration_s` | s |
| `distance_m` | `distance_m` | m |
| `elevation_gain_m` | `elevation_gain_m` | m |
| `elevation_loss_m` | `elevation_loss_m` | m |
| `avg_hr` | `avg_hr` | bpm |
| `max_hr` | `max_hr` | bpm |
| `avg_power` | `avg_power` | W |
| `avg_cadence` | `avg_cadence` | rpm |
| `avg_speed_mps` | `avg_speed_mps` | m/s |
| `max_speed_mps` | `max_speed_mps` | m/s |
| `avg_temp_c` | `avg_temp_c` | deg C |
| `min_temp_c` | `min_temp_c` | deg C |
| `max_temp_c` | `max_temp_c` | deg C |
| `energy_kj` | `energy_kj` | kJ |
| `energy_kcal` | `energy_kcal` | kcal |
| `efficiency_factor` | stored derived observation `efficiency_factor` (`with_session_metrics`, method `local-session-metrics`) | ratio |
| `efficiency_factor_unit` | `derivation.unit` of that observation | text |
| `variability_index` | stored derived observation `variability_index` | ratio |
| `work_kj` | stored derived observation `mechanical_work` | kJ |
| `decoupling_pct` | stored derived observation `aerobic_decoupling` | % |
| `rpe` | `rpe` in rating order | 1..10 |
| `rpe_conflict` | comparison of `rpe` values of one provider | bool, present only when true |
| `feel` | `feel` in rating order | 1 (strong) .. 5 (weak) |
| `normalized_power` | `normalized_power` | W |
| `weighted_avg_speed_mps` | `weighted_avg_speed_mps` | m/s |
| `pace_mps` | `pace_mps` | m/s |
| `intensity` | stored local intensity factor (`with_local_loads`, observation `intensity_factor`), not a provider value | % |
| `provider_intensity` | `intensity` | % of FTP |
| `grade_adjusted_speed_mps` | `grade_adjusted_speed_mps` | m/s |
| `ftp_w` | `ftp_w` | W |
| `vo2max` | `vo2max` | provider value, 0..100 (unit not stated in code; ml/kg/min assumed, unverified) |
| `training_load` | stored local session load (`with_local_loads`, method `local-tss-load`, observation `session_load`) | TSS scale |
| `load_method` | local load method id | text |
| `load_method_version` | stored `method_version` | int |
| `load_branch` | `derivation.branch` of the stored load | text |
| `load_threshold_after_session` | `derivation.threshold_after_session` | bool, present only when true |
| `load_assumption` | present when the load assumed the sex constants | text |
| `load_calibration` | `derivation.calibration` and inputs (strength calibration) | mapping |
| `provider_training_load` | `load` of the first TSS-like provider load | provider scale |
| `provider_load_model` | `load_model` of that record | `LoadModel` value |
| `training_effect_label` | `training_effect_label` | upper-case text |
| `training_effect_load` | `load` of the effect record when `garmin_training_load` | Garmin load |
| `aerobic_training_effect` | `aerobic_training_effect` | 0.0..5.0 |
| `anaerobic_training_effect` | `anaerobic_training_effect` | 0.0..5.0 |
| `power_zone_times` | `power_zone_times_s`; replaced by stored local zone times where a session has them (`with_zone_times`) | list of `{id, secs}`, s |
| `heart_rate_zone_times` | `hr_zone_times_s`, same replacement | list of `{id, secs}`, s |
| `pace_zone_times` | `pace_zone_times_s` (no live provider sets it), same replacement | list of `{id, secs}`, s |
| `planned_event_id` | `planned_event_id` | text |
| `purpose` | `session_purpose` or competition link | `ActivityPurpose` value |
| `competition_id` | stored competition id from `with_competitions` | text |

Keys the readers add that are not declared in the TypedDict: `zone_models` (zone key -> `local` or `provider`, set by `with_zone_times`) and `strength_sets` (`STRENGTH_KEY`, executed strength sets summary, set by `with_strength_summaries`).

### `activity_detail.v1` metrics

`activity_detail_contract` (`detail_contract.py`) uses the same orders and reports every candidate: each metric has `value`, `unit`, `source` and the other records' values as `alternatives`. Measured (`_MEASURED_METRICS`, measured order): `duration_s` s, `moving_duration_s` s, `elapsed_duration_s` s, `distance_m` m, `elevation_gain_m` m, `elevation_loss_m` m, `elevation_high_m` m, `elevation_low_m` m, `avg_hr` bpm, `max_hr` bpm, `min_hr` bpm, `avg_power` W, `max_power_w` W, `avg_cadence` rpm, `max_speed_mps` m/s, `min_temp_c` deg C, `max_temp_c` deg C, `steps` count, `lap_count` count, `energy_kj` kJ, `energy_kcal` kcal. Derived (`_DERIVED_METRICS`, derived order): `normalized_power` W, `load` (with `model`), `aerobic_training_effect`, `anaerobic_training_effect`, `water_estimated_ml` ml. Ratings `rpe`, `feel` (rating order, kind `athlete_entered`, with `scale`, `rating_label`, `normalized_0_1` from `ACTIVITY_RATING_SCALES`). `avg_hr` and `avg_power` fall back to the merged stream mean (kind `derived`) when no record has them (`_GAP_FILL`). Summary scalars fill metrics no record provides, and are kept as alternatives for `min_temp_c`, `max_temp_c`, `elevation_loss_m`.

## Canonical records for activity detail

Detail sets are stored per provider activity and per kind (`activity_detail_sets`; kinds `streams`, `laps`, `heart_rate_zones`, `power_zones`, `strength_sets`). Every set carries `provider_activity_id`, `provenance` (`provider` is required), and `origin`. All offsets are seconds from the start of that provider recording; no set stores an absolute timestamp or a local time. The session start comes from the `ActivityRecord`, and `detail_merge.clock_offset` uses record start differences to place sets of different providers on one axis.

Legend for the "emitted by" columns: Garmin mapper = `garmin_activity_detail_mapping.py`; FIT mapper = `fit_activity_detail_mapping.py` (stored under Garmin or Wahoo provenance); Intervals mapper = `intervals_activity_detail_mapping.py` (retired, see its section); derived = `stream_zones.py` (read-time, never stored). The store `activity_detail_store.py` only rebuilds records from rows and emits nothing new.

Provenance written by each producer:

| Producer | `provider` | `source_kind` | `recorded_by` | `label` | `retrieved_at` |
|---|---|---|---|---|---|
| Garmin mapper (also for FIT-decoded sets) | `garmin` | `provider_reported` | caller argument (the stored record's `recorded_by`) | `Garmin Connect` (`GARMIN_LABEL`) | caller argument |
| FIT mapper for Wahoo (`_provenance` in `wahoo_activity_details.py`) | `wahoo` | `device_measured` | `wahoo` | `Wahoo` (`WAHOO_LABEL`) | sync time |
| Intervals mapper | `intervals` | `provider_reported` | stored record's `recorded_by` | `Intervals.icu` (`INTERVALS_LABEL`) | fresh: caller argument; legacy: record `observed_at` |
| derived (`stream_zones.py`) | provider of the stream set it counted | `derived` | that stream set's `recorded_by` | `Zoneneinstellungen` | that stream set's `retrieved_at` |

At read time `canonical_detail._labelled` replaces `label` and `recorded_by` of every stored set with those of the session record it belongs to.

### `ActivityStreamSet`

Equal-length channels on one strictly increasing `time_s` axis. At most 172,800 points (`MAX_STREAM_POINTS`), axis span at most 172,800 s (`MAX_STREAM_SPAN_S`), at least one channel besides `time_s`. A point outside the channel bounds is a gap (`None`) after `clean_series`; the record constructor rejects it.

| Field | Type & unit | Emitted by | Notes |
|---|---|---|---|
| `provider_activity_id` | text, at most 200 chars at the mappers | Garmin mapper, FIT mapper, Intervals mapper | The Garmin activity id, the Wahoo workout id (FIT mapper), the Intervals.icu activity id. |
| `provenance` | `Provenance` | all producers | See the provenance table above. |
| `origin` | `ActivityDetailOrigin` | Garmin mapper `fetch`; FIT mapper `fetch`; Intervals mapper `fetch` (fresh) and `legacy_backfill` | |
| `resolution` | `StreamResolution` | Garmin mapper `downsampled` (requested with `maxchart` 2000 points); FIT mapper `full`; Intervals mapper `full` (fresh) or by the legacy `full_resolution` flag | |
| `channels` | `StreamChannel` to tuple of `float \| None` | see channel table | |

Channel bounds (`CHANNEL_BOUNDS`) and producers:

| Channel | Unit | Bounds | Garmin mapper | FIT mapper | Intervals mapper |
|---|---|---|---|---|---|
| `time_s` | s from recording start | 0 to 604,800 | yes | yes | yes |
| `distance_m` | m | 0 to 2,000,000 | yes | yes | yes |
| `altitude_m` | m | -1,000 to 10,000 | yes | yes | yes |
| `grade_pct` | percent (unverified, see Intervals section) | -100 to 100 | no | no | yes |
| `speed_mps` | m/s | 0 to 100 | yes | yes | yes |
| `power_w` | W | 0 to 5,000 | yes | yes | yes |
| `heart_rate_bpm` | bpm | 20 to 250 | yes | yes | yes |
| `cadence_rpm` | rpm, one leg for running | 0 to 300 | yes | yes | yes |
| `temperature_c` | degrees C | -60 to 70 | yes | yes | yes |
| `moving` | 1 moving, 0 paused | 0 to 1 | no | no | yes |

The property `kind` is always `streams` (`ActivityDetailKind.STREAMS`), not a stored field.

### `ActivityLap`

One lap or interval; offsets are seconds from the recording start, `end_offset_s` not before `start_offset_s`, both 0 to 604,800.

| Field | Type & unit | Emitted by | Notes |
|---|---|---|---|
| `index` | int 0 to 199 | Garmin mapper, FIT mapper, Intervals mapper | Position after ordering (`replace(lap, index=position)`). |
| `kind` | `LapKind` | Garmin mapper always `lap`; FIT mapper from `intensity` (23); Intervals mapper from `type` | |
| `start_offset_s` | s | Garmin mapper (cumulative sum of durations); FIT mapper (lap `start_time` minus time zero); Intervals mapper (`start_time`) | |
| `end_offset_s` | s | Garmin mapper (start plus duration); FIT mapper (start plus `total_elapsed_time`); Intervals mapper (`end_time`) | |
| `name` | text, at most 200 | Intervals mapper only | Garmin and FIT laps carry no name. |
| `moving_duration_s` | s | all three | Garmin `movingDuration`, FIT `total_timer_time`, Intervals `moving_time`. |
| `distance_m` | m | all three | |
| `avg_hr`, `max_hr` | bpm, 20 to 250 | all three | |
| `avg_power`, `max_power`, `normalized_power` | W, 0 to 5,000 | all three | |
| `avg_cadence` | rpm | Garmin mapper (bike only), FIT mapper, Intervals mapper | Garmin lap run cadence is not mapped (unit not verified). |
| `avg_speed_mps`, `max_speed_mps` | m/s, 0 to 100 | all three | |
| `elevation_gain_m` | m | all three | |
| `load` | 0 to 10,000 | Intervals mapper only | `icu_training_load`. |
| `intensity_pct` | percent, 0 to 1,000 | Intervals mapper only | `icu_intensity`. |

### `ActivityLapSet`

| Field | Type & unit | Emitted by | Notes |
|---|---|---|---|
| `provider_activity_id` | text | all three mappers | |
| `provenance` | `Provenance` | all three mappers | |
| `origin` | `ActivityDetailOrigin` | `fetch` (Garmin, FIT, Intervals fresh); `legacy_backfill` (Intervals legacy) | |
| `lap_source` | `LapSource` | Garmin mapper `device_laps`; FIT mapper `device_laps`; Intervals mapper `provider_intervals` | 1 to 200 laps, indexes consecutive from 0, ordered by `start_offset_s`. |
| `laps` | tuple of `ActivityLap` | all three mappers | |

The property `kind` is always `laps`.

### `ZoneBucket`

| Field | Type & unit | Emitted by | Notes |
|---|---|---|---|
| `index` | int 1 to 20 | Garmin mapper (provider `zoneNumber`), Intervals mapper (running position), derived (position) | |
| `seconds` | s, 0 to 604,800 | Garmin mapper (`secsInZone`), Intervals mapper, derived | |
| `lower`, `upper` | bpm (`heart_rate`, 0 to 250) or W (`power`, 0 to 5,000), or `None` | Garmin mapper, derived | Intervals buckets never carry bounds. Checked by `ZoneDistribution`, not by the bucket. |
| `label` | text, at most 64 | Intervals mapper only | The provider zone id (`Z1`, ...) of an `{id, secs}` item; none for plain numbers. |

### `ZoneDistribution`

| Field | Type & unit | Emitted by | Notes |
|---|---|---|---|
| `provider_activity_id` | text | Garmin mapper, Intervals mapper, derived | Derived uses the provider activity id of the stream set it counted. |
| `provenance` | `Provenance` | all | |
| `origin` | `ActivityDetailOrigin` | `fetch` (all three; derived uses `fetch` nominally); Intervals legacy `legacy_backfill` | |
| `metric` | `ZoneMetric` | all | The FIT mapper emits no zone distribution. |
| `boundary_source` | `ZoneBoundarySource` | Garmin mapper `provider_reported` or `unknown`; Intervals mapper `unknown`; derived `profile` | |
| `buckets` | tuple of `ZoneBucket`, 1 to 20 | all | Indexes consecutive from 1, `upper` not below `lower`. |

The property `kind` is `heart_rate_zones` or `power_zones` (`ZoneMetric.detail_kind`).

### `ActivityStrengthSet`

One executed strength set or the rest after it. `weight_kg` is `None` when no load was reported, never 0 (the constructor rejects 0).

| Field | Type & unit | Emitted by | Notes |
|---|---|---|---|
| `index` | int 0 to 499 | Garmin mapper, FIT mapper | Position among kept sets. |
| `set_type` | `StrengthSetType` | Garmin mapper from `setType`; FIT mapper from `set_type` (5) | |
| `exercise_category` | `ExerciseCategory` or `None` | Garmin mapper, FIT mapper | See the `ExerciseCategory` table. |
| `exercise_name` | upper-case provider code `[A-Z0-9_]{1,64}` | Garmin mapper only | The FIT mapper does not read the exercise subtype (8). |
| `reps` | int 0 to 1,000 | Garmin mapper, FIT mapper | |
| `weight_kg` | kg, greater than 0, at most 1,000 | Garmin mapper (grams / 1000), FIT mapper (/16) | |
| `duration_s` | s | Garmin mapper, FIT mapper | |
| `start_offset_s` | s | FIT mapper only | Garmin `startTime` is not mapped. |
| `workout_step_index` | int 0 to 999 | Garmin mapper, FIT mapper | Step of the planned workout the device ran. |

### `ActivityStrengthSetSet`

| Field | Type & unit | Emitted by | Notes |
|---|---|---|---|
| `provider_activity_id` | text | Garmin mapper, FIT mapper | |
| `provenance` | `Provenance` | Garmin mapper, FIT mapper | |
| `origin` | `ActivityDetailOrigin` | `fetch` | |
| `source` | `StrengthSetSource` | Garmin mapper `garmin_exercise_sets` (exercise-set part) or `fit_set_messages` (via the FIT mapper); FIT mapper for Wahoo `fit_set_messages` | |
| `sets` | tuple of `ActivityStrengthSet`, 1 to 500 | Garmin mapper, FIT mapper | Indexes consecutive from 0. |

The property `kind` is always `strength_sets`.

### `ActivityDetailKind`

| Value | Meaning | Produced by |
|---|---|---|
| `streams` | `ActivityStreamSet` | Garmin mapper, FIT mapper, Intervals mapper |
| `laps` | `ActivityLapSet` | Garmin mapper, FIT mapper, Intervals mapper |
| `heart_rate_zones` | `ZoneDistribution` with metric `heart_rate` | Garmin mapper, Intervals mapper, derived (not stored) |
| `power_zones` | `ZoneDistribution` with metric `power` | Garmin mapper, Intervals mapper, derived (not stored) |
| `strength_sets` | `ActivityStrengthSetSet` (schema version 22) | Garmin mapper, FIT mapper |

### `ActivityDetailOrigin`

| Value | Meaning | Produced by |
|---|---|---|
| `fetch` | Mapped from a provider response fetched by this build | Garmin mapper, FIT mapper, Intervals mapper (`map_intervals_activity_detail`, `map_intervals_summary_zones`), derived |
| `legacy_backfill` | Mapped from a detail document cached by an earlier release | Intervals mapper `map_legacy_activity_detail` only |

### `StreamChannel`

Members `time_s`, `distance_m`, `altitude_m`, `grade_pct`, `speed_mps`, `power_w`, `heart_rate_bpm`, `cadence_rpm`, `temperature_c`, `moving`; units and producers in the `ActivityStreamSet` channel table.

### `StreamResolution`

| Value | Meaning | Produced by |
|---|---|---|
| `full` | Every recorded point kept | FIT mapper; Intervals mapper (fresh, legacy with `full_resolution` true) |
| `downsampled` | Chart-sized series | Garmin mapper (`details` part, 2,000-point chart); Intervals mapper (legacy without `full_resolution`) |

### `LapKind`

| Value | Meaning | Produced by |
|---|---|---|
| `lap` | Plain lap or interval of unknown role | Garmin mapper (always); FIT mapper (`intensity` 0 or unknown); Intervals mapper (default) |
| `work` | Work interval | FIT mapper (`intensity` 5, interval); Intervals mapper (`type` `work`) |
| `recovery` | Recovery interval | FIT mapper (`intensity` 1 rest or 4 recovery); Intervals mapper (`type` `recovery`) |
| `warmup` | Warm-up | FIT mapper (`intensity` 2) |
| `cooldown` | Cool-down | FIT mapper (`intensity` 3) |

### `LapSource`

| Value | Meaning | Produced by |
|---|---|---|
| `provider_intervals` | Intervals detected or labelled by the provider | Intervals mapper (`icu_intervals`) |
| `device_laps` | Laps recorded by the device | Garmin mapper (`lapDTOs`), FIT mapper (lap messages) |
| `splits` | Fixed-distance splits computed by the provider | No module. Only ranked in `detail_merge._LAP_SOURCE_RANK`. |

### `ZoneMetric`

| Value | Meaning | Produced by |
|---|---|---|
| `heart_rate` | Time in heart-rate zones (bpm) | Garmin mapper (`hr_zones`), Intervals mapper (`icu_hr_zone_times`), derived |
| `power` | Time in power zones (W) | Garmin mapper (`power_zones`), Intervals mapper (`icu_zone_times`), derived |

### `ZoneBoundarySource`

| Value | Meaning | Produced by |
|---|---|---|
| `provider_reported` | Bounds taken from the provider response | Garmin mapper (every zone has `zoneLowBoundary` and they rise with the zone number) |
| `profile` | Bounds from the athlete's zone settings | derived (`stream_zones.py`) |
| `unknown` | No usable bounds | Garmin mapper (otherwise); Intervals mapper (always) |

### `StrengthSetType`

| Value | Meaning | Produced by |
|---|---|---|
| `active` | An executed set | Garmin mapper (`setType` `ACTIVE`), FIT mapper (`set_type` 1) |
| `rest` | The rest after a set | Garmin mapper (`setType` `REST`), FIT mapper (`set_type` 0) |

### `StrengthSetSource`

| Value | Meaning | Produced by |
|---|---|---|
| `garmin_exercise_sets` | Garmin exercise sets, including the athlete's corrections in Connect | Garmin mapper |
| `fit_set_messages` | FIT `set` messages (225) of the original activity file | FIT mapper (Garmin or Wahoo provenance) |

### `ExerciseCategory`

The FIT `exercise_category` enum 0 to 32. The FIT mapper takes the number (field 7 of the set message) and indexes `_FIT_EXERCISE_CATEGORIES`; the Garmin mapper takes the upper-case `category` code of the most probable exercise and applies `ExerciseCategory(code.lower())`. Garmin code and FIT name are the same text in different case.

| FIT number | Garmin code | Value |
|---|---|---|
| 0 | `BENCH_PRESS` | `bench_press` |
| 1 | `CALF_RAISE` | `calf_raise` |
| 2 | `CARDIO` | `cardio` |
| 3 | `CARRY` | `carry` |
| 4 | `CHOP` | `chop` |
| 5 | `CORE` | `core` |
| 6 | `CRUNCH` | `crunch` |
| 7 | `CURL` | `curl` |
| 8 | `DEADLIFT` | `deadlift` |
| 9 | `FLYE` | `flye` |
| 10 | `HIP_RAISE` | `hip_raise` |
| 11 | `HIP_STABILITY` | `hip_stability` |
| 12 | `HIP_SWING` | `hip_swing` |
| 13 | `HYPEREXTENSION` | `hyperextension` |
| 14 | `LATERAL_RAISE` | `lateral_raise` |
| 15 | `LEG_CURL` | `leg_curl` |
| 16 | `LEG_RAISE` | `leg_raise` |
| 17 | `LUNGE` | `lunge` |
| 18 | `OLYMPIC_LIFT` | `olympic_lift` |
| 19 | `PLANK` | `plank` |
| 20 | `PLYO` | `plyo` |
| 21 | `PULL_UP` | `pull_up` |
| 22 | `PUSH_UP` | `push_up` |
| 23 | `ROW` | `row` |
| 24 | `SHOULDER_PRESS` | `shoulder_press` |
| 25 | `SHOULDER_STABILITY` | `shoulder_stability` |
| 26 | `SHRUG` | `shrug` |
| 27 | `SIT_UP` | `sit_up` |
| 28 | `SQUAT` | `squat` |
| 29 | `TOTAL_BODY` | `total_body` |
| 30 | `TRICEPS_EXTENSION` | `triceps_extension` |
| 31 | `WARM_UP` | `warm_up` |
| 32 | `RUN` | `run` |
| 33 and above | any other valid code | `other` |

Rules outside the table:

- FIT: the category field is an array; the first entry that is an integer and not 65534 (unknown) decides. An invalid entry (65535) decodes to `None` and is skipped. A number above 32 gives `other`. No usable entry gives `None`.
- Garmin: a `category` that is not an upper-case identifier `[A-Z0-9_]{1,64}` gives `None` (the exercise `name` is still read). A valid code that is not a value above gives `other`, and the code becomes `exercise_name` when the exercise has no usable `name`. The literal code `OTHER` gives `other` and keeps `name`.
- The FIT mapper never sets `exercise_name`; the Garmin mapper sets it from the exercise `name` when it is an upper-case code.

Consumers (`strength_sets.py`): `other`, `cardio`, `warm_up`, `run` are neutral for the leg rule; `squat`, `deadlift`, `lunge`, `leg_curl`, `calf_raise`, `hip_raise`, `hip_swing`, `olympic_lift`, `plyo`, `total_body` count as leg categories.

## Activity detail mappers

Payload evidence for this scope: the sanitized payload files contain the Garmin activity summary object (`get_activity`) and the Intervals.icu activity summary only. The Garmin detail parts (`get_activity_details`, `get_activity_splits`, `get_activity_hr_in_timezones`, `get_activity_power_in_timezones`, `get_activity_exercise_sets`) and FIT files are not in the payload files, so those keys are marked **documented** with the test fixture named in each section. The Intervals files show `stream_types`, `icu_zone_times` and `icu_hr_zone_times` (**observed**) and carry no `icu_intervals` key (only `icu_intervals_edited`, null).

### `garmin_activity_detail_mapping.py`

Status: Live. Called by `_map_collected` in `backend/sync/garmin_activity_details.py` for every Garmin activity detail fetch and backfill; stored with `replace_detail_set(mapper_version=MAPPER_VERSION)`.
Mapper version: **4**
Inputs: the dict from `collect_garmin_activity_detail` (`backend/providers/garmin.py`) with the parts `details`, `splits`, `hr_zones`, `power_zones`, `exercise_sets` (strength activities only) and `fit`. Transport: the Personal API serves `details` (with `maxChartSize` 2,000) and the original FIT file (`download_activity_fit`, unzipped by `fit_from_archive`); the unofficial login serves `splits`, the two zone parts and `exercise_sets`. A part that is absent gives no set and no issue; a present but malformed part gives one value-free issue and no set for it.
Evidence: documented only (fixtures `tests/fixtures/providers/garmin/activity_detail/details.json`, `splits.json`, `hr_zones.json`, `power_zones.json`; strength and FIT cases are built inline in `tests/test_garmin_activity_detail_mapping.py`). The sanitized payload files `garmin_activity_detail_run_2026-11-03` and `garmin_personal_activity_detail_run_2026-11-03` hold the activity summary only.

Provenance: `provider` `garmin`, `source_kind` `provider_reported`, `source_record_id` the activity id, `recorded_by` and `retrieved_at` from the caller, `label` `Garmin Connect`. `provider_activity_id` is `activity_id` (text, at most 200 chars; an integer id is rejected as `invalid_type`). All sets use `origin` `fetch`.

Record keywords set per kind: stream set `provider_activity_id`, `provenance`, `origin`, `resolution`, `channels`; lap set `provider_activity_id`, `provenance`, `origin`, `lap_source`, `laps`; zone distribution `provider_activity_id`, `provenance`, `origin`, `metric`, `boundary_source`, `buckets`; strength set list `provider_activity_id`, `provenance`, `origin`, `source`, `sets`.

Which source wins per kind (`map_garmin_activity_detail`):

| Kind | Winner | Fallback |
|---|---|---|
| streams | FIT record stream (full resolution), `fit_sets.get(ActivityStreamSet)` | `details` chart (`downsampled`) |
| laps | FIT device laps | `splits.lapDTOs` |
| `heart_rate` and `power` zones | `hr_zones`, `power_zones` (the FIT file yields none) | none |
| strength sets | `exercise_sets` (athlete corrections included) | FIT `set` messages, decoded only when there are no exercise sets (`strength_sets=exercise_sets is None`) |

Streams from `details` (`_stream_set`, `_metric_columns`). Columns are read by `metricDescriptors[].key` and `metricDescriptors[].metricsIndex`; the value of a row is `activityDetailMetrics[].metrics[metricsIndex]`. The first descriptor with a known key wins. Unknown keys are ignored. A malformed descriptor, a non-list part, or a row shorter than the highest known index drops the whole stream set with an issue.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `time_s` | `sumElapsedDuration` → `sumDuration` | seconds; none | Elapsed time is preferred so offsets line up with the activity start; the timer value differs only after a pause. The axis must be gap-free, in range and strictly increasing, else the whole set is dropped (`invalid_number` or `out_of_range`). |
| `distance_m` | `sumDistance` | m; none | |
| `altitude_m` | `directElevation` | m; none | |
| `speed_mps` | `directSpeed` | m/s; none | |
| `power_w` | `directPower` | W; none | |
| `heart_rate_bpm` | `directHeartRate` | bpm; none | |
| `temperature_c` | `directAirTemperature` | degrees C; none | |
| `cadence_rpm` | `directBikeCadence` → `directRunCadence` (`_cadence_points`) | rpm; none | The bike column wins; the run column is used only when the bike column has no usable point. `directRunCadence` already counts one leg, kept as reported. |
| `grade_pct` | none | | Not produced. |
| `moving` | none | | Not produced; averages and zone counting then use every point. |
| `resolution` | | `downsampled` | Fixed. |
| `origin` | | `fetch` | Fixed. |

`clean_series` turns non-numbers, booleans, non-finite and out-of-bounds points into gaps and reports one `out_of_range` issue per key. A channel with no usable point is dropped; fewer than two channels (including `time_s`) gives no stream set.

Laps from `splits` (`_lap_set`, only when the FIT file yields no lap set). `lap_source` `device_laps`, `kind` `lap` for every lap, no `name`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `index` | position after ordering | | Rows are ordered by `lapIndex` when every row has an integer one, else file order. |
| `start_offset_s` | none (derived) | s | Running sum of the previous laps' durations, starting at 0. The payload start time is not used. |
| `end_offset_s` | `elapsedDuration` → `duration` | s; start plus duration | First key that is not null. A lap with a missing, invalid or out-of-range duration ends the lap list there (every later offset depends on it). |
| `moving_duration_s` | `movingDuration` | s | |
| `distance_m` | `distance` | m | |
| `avg_hr` | `averageHR` | bpm | |
| `max_hr` | `maxHR` | bpm | |
| `avg_power` | `averagePower` | W | |
| `max_power` | `maxPower` | W | |
| `normalized_power` | `normalizedPower` | W | |
| `avg_speed_mps` | `averageSpeed` | m/s | |
| `max_speed_mps` | `maxSpeed` | m/s | |
| `elevation_gain_m` | `elevationGain` | m | |
| `avg_cadence` | `averageBikeCadence` | rpm | Run cadence (`averageRunCadence`) is not mapped, unit not verified. |

Each lap metric goes through `coerce_number` (numbers and dot-decimal text) and `_lap_accepts` (the `ActivityLap` bounds); a rejected metric is dropped with an issue, the lap stays. More than 200 laps are cut with an `out_of_range` issue. `load`, `intensity_pct` and `name` are not produced.

Zone distributions (`_zone_distribution`). `hr_zones` gives metric `heart_rate`, `power_zones` gives metric `power`. Each part is a list of `{zoneNumber, secsInZone, zoneLowBoundary}`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `index` | `zoneNumber` | int 1 to 20 | After sorting, the numbers must be exactly 1..n; any bad zone drops the whole distribution (a gap would renumber the rest). |
| `seconds` | `secsInZone` | s; none | 0 to 604,800. |
| `lower` | `zoneLowBoundary` of this zone | bpm or W; none | Set only when `boundary_source` is `provider_reported`, else `None`. |
| `upper` | `zoneLowBoundary` of the next zone | bpm or W; none | The last zone has `None`. |
| `boundary_source` | derived | | `provider_reported` when every zone has `zoneLowBoundary` and they rise strictly with the zone number; otherwise `unknown` and all bounds `None`. |
| `label` | none | | Never set by Garmin. |

Strength sets from `exercise_sets` (`_strength_set_set`, `_exercise_set`). The part is `{exerciseSets: [...]}` or the list itself. `source` is `garmin_exercise_sets`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `index` | position among kept rows | | Rows without a usable `setType` are dropped before numbering; at most 500 sets. |
| `set_type` | `setType` | `ACTIVE` gives `active`, `REST` gives `rest` (case-insensitive) | Anything else drops the row with an issue. |
| `exercise_category` | `exercises[].category` of the entry with the highest `probability` | `ExerciseCategory(code.lower())` | Unknown code gives `other`; see the `ExerciseCategory` table. |
| `exercise_name` | `exercises[].name` of that entry | kept only as upper-case code | If the category is unknown and no name is usable, the category code is used. |
| `reps` | `repetitionCount` | whole number, else `None` | |
| `weight_kg` | `weight` | grams / 1000 (`_GRAMS_PER_KG`) | 0 or missing gives `None`. The gram unit is unverified on a live payload. |
| `duration_s` | `duration` | s | |
| `workout_step_index` | `wktStepIndex` | whole number | |
| `start_offset_s` | none | | `startTime` is not mapped (the part carries no activity start). |

A value the `ActivityStrengthSet` bounds reject is set to `None` with an `out_of_range` issue (`strength_set_accepts`).

FIT part (`_fit_sets`). `fit` bytes are decoded by `map_fit_activity_detail` with this module's Garmin provenance; its streams and laps replace the JSON ones, its strength sets are used only when `exercise_sets` is missing.

Not mapped: `directDoubleCadence`, every other metric descriptor key (for example latitude, longitude, vertical speed, power-wind or running-dynamics keys) are ignored; `splits` keys other than those above (`averageRunCadence`, `lapIndex` is used only for ordering); `splitSummaries` and `summaryDTO.*` (activity summary, mapped by `garmin_activity_mapping.py`); exercise `startTime`.

### `fit_activity_detail_mapping.py`

Status: Live. Called by `_fit_sets` in `garmin_activity_detail_mapping.py` (Garmin FIT from the Personal API) and by `WahooActivityDetailImport._import_one` in `backend/sync/wahoo_activity_details.py` (Wahoo FIT). Both store with `replace_detail_set(mapper_version=MAPPER_VERSION)`, Garmin with its own version 4.
Mapper version: **3**
Inputs: the raw bytes of one FIT activity file (`bytes`); decoding and scaling by `fit_file.py` (`fit_messages`, `fit_field`). Anything else gives one `fit` `invalid_type` issue. The caller passes `provider_activity_id` (Garmin activity id or Wahoo workout id) and the provenance (see the provenance table).
Evidence: documented only (FIT SDK profile; synthetic FIT bytes built in `tests/test_fit_activity_detail_mapping.py` and `tests/test_fit_file.py`; there is no FIT file or Wahoo payload in the payload files).

Record keywords set per kind: stream set `provider_activity_id`, `provenance`, `origin`, `resolution`, `channels`; lap set `provider_activity_id`, `provenance`, `origin`, `lap_source`, `laps`; strength set list `provider_activity_id`, `provenance`, `origin`, `source`, `sets`.

Output: stream set (`resolution` `full`), lap set (`lap_source` `device_laps`), strength set (`source` `fit_set_messages`), all `origin` `fetch`. No zone distributions, no `grade_pct`, no `moving`. `strength_sets=False` (the Garmin mapper when it has exercise sets) skips the `set` messages and their issues.

Time handling: FIT timestamps are seconds since 1989-12-31 00:00:00 UTC (`FIT_EPOCH`). The mapper only uses differences: time zero is the first usable record timestamp (`_first_record_timestamp`); lap and set offsets are measured from it. Without any record, the first lap start (laps) or the smallest set `start_time` (sets) is time zero. No timezone or local time is involved.

Streams, record message 20 (`_stream_set`, `_kept_records`, `_RECORD_CHANNEL_FIELDS`):

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `time_s` | record `timestamp` (253) | s; timestamp minus time zero | A record with no usable timestamp, a timestamp not strictly after the previous kept one, or an offset above 172,800 s is skipped (`timestamp` issues `missing` / `out_of_range`). Fewer than two kept records, or more than 172,800, gives no set. |
| `distance_m` | record `distance` (5) | /100, m | |
| `speed_mps` | record `enhanced_speed` (73) → `speed` (6) | /1000, m/s | Per record; an invalid sentinel in 73 falls back to 6. |
| `altitude_m` | record `enhanced_altitude` (78) → `altitude` (2) | /5 - 500, m | Same fallback per record. |
| `heart_rate_bpm` | record `heart_rate` (3) | bpm | |
| `power_w` | record `power` (7) | W | |
| `temperature_c` | record `temperature` (13) | degrees C | |
| `cadence_rpm` | record `cadence` (4) + `fractional_cadence` (53) | 4 whole, 53 is /128; sum (`_cadence`) | If 53 is absent only 4 is used; if 4 is missing the point is a gap. Rpm of one leg for running, as the device reports it. |
| `grade_pct` | none | | Not produced. |
| `moving` | none | | Not produced. |
| `resolution` | | `full` | Fixed. |

Position fields (0, 1) and all other record fields are not read. A channel with no usable point is dropped; out-of-bounds points become gaps with an `out_of_range` issue named by the channel.

Laps, lap message 19 (`_lap_set`, `_lap`, `_LAP_METRIC_FIELDS`, `_LAP_KINDS`):

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `index` | position after sorting by lap `start_time` | | Laps without `start_time` are dropped (`start_time` `missing`); a lap that starts before time zero is dropped (`out_of_range`). |
| `start_offset_s` | lap `start_time` (2) | s; minus time zero | |
| `end_offset_s` | lap `total_elapsed_time` (7) | /1000 s; start plus elapsed | A lap without it is dropped (`total_elapsed_time` `missing`). |
| `kind` | lap `intensity` (23, raw) | 0 `lap`, 1 `recovery`, 2 `warmup`, 3 `cooldown`, 4 `recovery`, 5 `work`; any other or missing gives `lap` | `_lap_kind`. |
| `moving_duration_s` | lap `total_timer_time` (8) | /1000 s | |
| `distance_m` | lap `total_distance` (9) | /100 m | |
| `avg_speed_mps` | lap `enhanced_avg_speed` (110) → `avg_speed` (13) | /1000 m/s | |
| `max_speed_mps` | lap `enhanced_max_speed` (111) → `max_speed` (14) | /1000 m/s | |
| `avg_hr` | lap `avg_heart_rate` (15) | bpm | |
| `max_hr` | lap `max_heart_rate` (16) | bpm | |
| `avg_cadence` | lap `avg_cadence` (17) | rpm, as reported | |
| `avg_power` | lap `avg_power` (19) | W | |
| `max_power` | lap `max_power` (20) | W | |
| `elevation_gain_m` | lap `total_ascent` (21) | m | |
| `normalized_power` | lap `normalized_power` (33) | W | |
| `name`, `load`, `intensity_pct` | none | | Not produced. |

A metric the `ActivityLap` bounds reject is dropped with an `out_of_range` issue named by the canonical metric; more than 200 laps are cut with a `lap` issue.

Strength sets, set message 225 (`_strength_set_set`, `_strength_set`), in file order, at most 500:

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `set_type` | set `set_type` (5, raw) | 0 `rest`, 1 `active` | Any other value or missing: the set is dropped (`set_type` `missing`). |
| `reps` | set `repetitions` (3, raw) | count | |
| `weight_kg` | set `weight` (4) | /16 kg | 0 or invalid gives `None` (`or None`). |
| `duration_s` | set `duration` (0) | /1000 s | |
| `start_offset_s` | set `start_time` (6) | s; minus time zero | `None` when there is no time zero or the start is before it. |
| `exercise_category` | set `category` (7, array of enum numbers) | `_FIT_EXERCISE_CATEGORIES[number]`; first entry that is an integer other than 65534 | Numbers 0 to 32 give `bench_press`, `calf_raise`, `cardio`, `carry`, `chop`, `core`, `crunch`, `curl`, `deadlift`, `flye`, `hip_raise`, `hip_stability`, `hip_swing`, `hyperextension`, `lateral_raise`, `leg_curl`, `leg_raise`, `lunge`, `olympic_lift`, `plank`, `plyo`, `pull_up`, `push_up`, `row`, `shoulder_press`, `shoulder_stability`, `shrug`, `sit_up`, `squat`, `total_body`, `triceps_extension`, `warm_up`, `run` in that order; a larger number gives `other`. |
| `workout_step_index` | set `wkt_step_index` (11, raw) | value AND 0x0FFF | Removes the message-index flag bits (`_MESSAGE_INDEX_MASK`). |
| `exercise_name` | none | | The category subtype (8) is not read. |
| `index` | position among kept sets | | |
| `source` | | `fit_set_messages` | Fixed. |

Not mapped: positions (record 0, 1), the session (18), activity and file messages, developer fields (skipped by `fit_file`), device information, lap run cadence, set `category_subtype` (8), `weight_display_unit`, `message_index`, set `timestamp`.

### `intervals_activity_detail_mapping.py`

Status: Retired (stored-data replay only; no new data). Intervals.icu is an output target since #1728. Callers: `map_legacy_activity_detail` is still wired through `CanonicalDetailWriter.write_legacy`, run by `ActivityDetailBackfill` and `ActivityDetailRetirement` (follow-ups in `canonical_backfill_assembly.py`), and replays only the stored `activity_detail:<sha>` key-value records of an old database; `STREAM_KEY_CHANNELS` and `MAPPER_VERSION` are read by the retirement. `map_intervals_activity_detail` (fresh fetch) and `map_intervals_summary_zones` have no production caller; the fetch path that fed them (`ActivityDetailRefreshService`, `normalize_streams`) exists only in `tests/intervals_detail_refresh.py`. The #1728 purge deletes the `activity_detail:*` records, the backfill and retirement state keys, and the Intervals.icu activity and detail rows, and `write_legacy` writes only for an active Intervals.icu activity record, so nothing is replayed after the purge. The live detail reader (`canonical_detail.py`) never reads Intervals.icu records or sets.
Mapper version: **2**
Inputs: fresh `GET /activity/{id}` payload plus the streams from `normalize_streams` (`map_intervals_activity_detail`, origin `fetch`); one stored kv record `{activity_id, observed_at, activity: {streams, laps, icu_hr_zone_times, icu_zone_times}, full_resolution, summary_sha256, ...}` (`map_legacy_activity_detail`, origin `legacy_backfill`); a summary row (`map_intervals_summary_zones`, zones only, caller-supplied provenance, origin `fetch`).
Evidence: `icu_zone_times` and `icu_hr_zone_times` observed in `intervals_activity_ride_outdoor_wahoo`, `intervals_activity_ride_virtual_zwift`, `intervals_activity_run_garmin_2026-11-03`, `intervals_activity_strength_garmin` (power items are `{id, secs}`, heart-rate items plain numbers; `icu_zone_times` is null on the strength activity). Stream names appear only as the `stream_types` list in those files: `time`, `distance`, `altitude`, `velocity_smooth`, `watts`, `heartrate`, `cadence` and `temp` observed; `grade_smooth`, `grade`, `velocity`, `speed`, `power`, `temperature`, `moving` documented (alias list in code and `ACTIVITY_DETAIL_STREAM_TYPES`). `icu_intervals` is absent from all four files (`icu_intervals_edited` is null), so every lap key is documented (test `tests/test_intervals_activity_detail_mapping.py`).

Provenance: `provider` `intervals`, `source_kind` `provider_reported`, `source_record_id` the activity id (string, or integer for a fresh payload `id`, at most 200 chars), `recorded_by` from the stored record, `label` `Intervals.icu`, `retrieved_at` the caller's value (fresh) or the record's `observed_at` (legacy; must be ISO text with an offset).

Record keywords set per kind (`_Header` carries `provider_activity_id`, `provenance`, `origin`): stream set `resolution`, `channels`; lap set `lap_source`, `laps`; zone distribution `metric`, `boundary_source`, `buckets`.

Streams (`_stream_set`, `_pick_channel`, `_CHANNEL_ALIASES`). The `streams` dict maps a provider stream name to a list. The fetch helper renamed `temp` to `temperature` (`ACTIVITY_DETAIL_STREAM_ALIASES`) before the mapper; the mapper itself reads `temperature`. For each channel the first alias that is a list of the time axis length and has at least one usable point wins; an alias with rejected points still adds one issue for its channel and the next alias is tried. A time axis with a gap, a rejected point, or non-increasing values drops the set.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `time_s` | `time` | s; none | |
| `distance_m` | `distance` | m; none | |
| `altitude_m` | `altitude` | m; none | |
| `grade_pct` | `grade_smooth` → `grade` | none; unit not verified (bounds -100 to 100) | Only the Intervals mapper produces this channel. |
| `speed_mps` | `velocity_smooth` → `velocity` → `speed` | m/s; none | |
| `power_w` | `watts` → `power` | W; none | |
| `heart_rate_bpm` | `heartrate` | bpm; none | |
| `cadence_rpm` | `cadence` | rpm; none | |
| `temperature_c` | `temperature` | degrees C; none | |
| `moving` | `moving` | `true` to 1.0, `false` to 0.0 (`_moving_value`) | Only the Intervals mapper produces this channel. |
| `resolution` | | fresh: `full`; legacy: `full` when the record's `full_resolution` is true, else `downsampled` | |
| `origin` | | `fetch` or `legacy_backfill` | |

No set is built when none of the known stream keys is present, or fewer than two channels remain.

Laps (`_lap_set`, `_lap`, `_LAP_METRIC_KEYS`). Rows come from `icu_intervals` (fresh, via `activity_detail_laps`) or `activity.laps` (legacy, the projected keys). `lap_source` is `provider_intervals`. Laps are sorted by `start_offset_s` with a stable sort, then numbered; more than 200 are cut with an issue. A row without a usable `start_time` or `end_time` (offsets in seconds), or with the end before the start, is dropped.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `start_offset_s` | `start_time` | s | |
| `end_offset_s` | `end_time` | s | |
| `kind` | `type` (case-insensitive) | `work` gives `work`, `recovery` gives `recovery`, anything else `lap` | Stored legacy laps never kept `type`, so legacy laps are always `lap`. |
| `name` | `name` | trimmed, at most 200 chars, empty gives `None` | |
| `moving_duration_s` | `moving_time` | s | |
| `distance_m` | `distance` | m | |
| `avg_hr` | `average_heartrate` | bpm | |
| `max_hr` | `max_heartrate` | bpm | |
| `avg_power` | `average_watts` | W | |
| `max_power` | `max_watts` | W | |
| `normalized_power` | `weighted_average_watts` → `normalized_power` → `icu_weighted_avg_watts` | W | |
| `avg_cadence` | `average_cadence` | rpm | |
| `avg_speed_mps` | `average_speed` | m/s | |
| `max_speed_mps` | `max_speed` | m/s | |
| `elevation_gain_m` | `total_elevation_gain` | m | |
| `load` | `icu_training_load` | none | |
| `intensity_pct` | `icu_intensity` | a value above 0 and up to 2 is a fraction: `round(value * 100, 1)`; otherwise as given | `_intensity_pct`. |

Zone distributions (`_zone_distribution`, `zone_times`). `icu_hr_zone_times` gives metric `heart_rate`; `icu_zone_times` gives metric `power`. Only the first 20 items are read. An item is a plain number (positional, no label) or `{id, secs}`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `index` | running position of the kept bucket | | Not the number in the id. |
| `seconds` | number, or `secs` of an `{id, secs}` item | s; none | A `None` gap in positional items, or a `Z<n>` item with invalid `secs`, drops the whole distribution (issue `invalid_number`). |
| `label` | `id` of an `{id, secs}` item | text | Only ids matching `Z<digits>` are kept; other ids (for example `SS`) are skipped with an `unsupported` issue. Plain numbers get no label. |
| `boundary_source` | | `unknown` | `lower` and `upper` are never set. |

Not mapped: `icu_intervals` items beyond the keys above (`start_index`, `end_index`, `elapsed_time`, intensity zone labels); stream keys that are not aliases above (for example `latlng`, `pace`, `timer`, `hrv`, `respiration`, running dynamics); `icu_hr_zones`, `icu_power_zones`, `pace_zone_times`, `gap_zone_times` (not read here).

### `intervals_activity_detail_projection.py`

Status: Retired as a source of canonical records; two helpers stay live. It builds a bounded dict, not a canonical record. `detailed_activity` is called by `summary_fingerprint` (`backend/activities/detail_store.py`), which `canonical_table_reader.summary_fingerprints` applies to active Intervals.icu activity records (none remain after the #1728 purge), and by the retired fetch path (tests only). `_downsample_series` and `COACH_ACTIVITY_DETAIL_MAX_SERIES_POINTS` are live: `activity_detail_contract` uses them to thin the merged streams of any provider to at most 2,000 points for the detail document (`display_sampled`), and the retirement uses `_downsample_series` to compare legacy series. `DETAIL_PROJECTION_VERSION` (2) is read only by tests.
Inputs: one raw Intervals.icu activity dict (optionally with `streams` and `laps` added by the old fetch path); symbol `detailed_activity`.
Evidence: activity summary keys observed in the four `intervals_activity_*` files except the ones marked documented below; stream and lap keys documented (`icu_intervals` is null and there is no `streams` in the files; `tests/test_activity_detail_projection.py`).

Output keys equal input keys; no unit conversion. Rules: every scalar goes through `_analysis_scalar` (non-finite floats give `None` and the key is left out; strings are cut to 200 chars, `name` to 500; booleans, ints and floats pass; other types, including lists and dicts, are dropped). Streams: only the keys below, each series scalarised (strings cut to 80 chars) and thinned by `_downsample_series` to at most 2,000 points: when longer, the indexes `round(i * (n - 1) / 1999)` for i in 0..1999 plus first and last. Laps: at most 200 items, only the lap keys below, scalars cut to 120 chars. Zones: `icu_hr_zone_times` and `icu_zone_times` through `zone_times` (first 20 items, numbers as given, `{id, secs}` items kept with `id` cut to 20 chars).

| Group | Keys (output key = input key) | Evidence |
|---|---|---|
| Activity scalars (`COACH_ACTIVITY_DETAIL_FIELDS`) | `start_date_local`, `start_date`, `name`, `type`, `moving_time`, `elapsed_time`, `distance`, `total_elevation_gain`, `total_elevation_loss`, `calories`, `average_speed`, `max_speed`, `average_heartrate`, `max_heartrate`, `icu_weighted_avg_watts`, `average_cadence`, `average_temp`, `min_temp`, `max_temp`, `icu_training_load`, `icu_intensity`, `icu_rolling_ftp`, `icu_ftp`, `lthr`, `icu_rpe`, `feel`, `decoupling` | observed |
| Activity scalars | `sport`, `subtype`, `average_watts`, `max_watts`, `weighted_average_watts`, `normalized_power`, `max_cadence`, `icu_weighted_avg_speed`, `icu_pace`, `faded` | documented |
| Stream keys (`COACH_ACTIVITY_DETAIL_STREAM_FIELDS`) | `time`, `distance`, `altitude`, `grade`, `grade_smooth`, `speed`, `velocity`, `velocity_smooth`, `pace`, `watts`, `power`, `heartrate`, `cadence`, `temperature`, `moving`, `timer` | documented |
| Lap keys (`COACH_ACTIVITY_DETAIL_LAP_FIELDS`) | `name`, `start_time`, `end_time`, `start_index`, `end_index`, `elapsed_time`, `moving_time`, `distance`, `average_speed`, `max_speed`, `average_heartrate`, `max_heartrate`, `average_watts`, `max_watts`, `weighted_average_watts`, `icu_weighted_avg_watts`, `normalized_power`, `average_cadence`, `total_elevation_gain`, `icu_training_load`, `icu_intensity` | documented |
| Zones | `icu_hr_zone_times`, `icu_zone_times` | observed |

`summary_fingerprint` removes `streams`, `laps`, both zone keys and `lthr` from the projection before hashing, so fingerprints of old stored records stay valid.

Not mapped: every other Intervals.icu activity key (for example `icu_hr_zones`, `icu_power_zones`, `pace_zone_times`, `stream_types`, `icu_lap_count`, `interval_summary`); lap keys outside the list above (notably the interval `type`, so legacy laps map to `lap`).

### `wahoo_fit_download.py`

Status: Live. Transport only: `download_wahoo_fit` is injected into `WahooActivityDetailImport` by `wahoo_sync_assembly.py` and runs after a committed Wahoo sync. It maps nothing.
Inputs: the Wahoo workout row's `workout_summary.file.url` (`wahoo_fit_url`), the signed download link of the workout's original FIT file. Decoding and mapping are done by `fit_activity_detail_mapping.py` (version 3) with Wahoo provenance (`device_measured`, `recorded_by` `wahoo`, label `Wahoo`); the sets are stored per Wahoo workout id with the summary hash of the active record. Result for Wahoo detail: `streams` (`full`), `laps` (`device_laps`) and `strength_sets` (`fit_set_messages`); no zone distribution (derived zones are added at read time).
Evidence: documented only (`tests/test_wahoo_fit_download.py`, `tests/test_wahoo_activity_details.py`); there is no Wahoo payload in the payload files.

| Item | Rule |
|---|---|
| Which file | The one file named by `workout_summary.file.url` of the workout; the raw record never stores the link (`raw_workout_for_storage`). A row without a link is skipped. |
| URL check (`_trusted_url`) | `https` only, host exactly `cdn.wahooligan.com` (`WAHOO_FIT_HOSTS`, trailing dot and case ignored), port 443 or none, no user info, no fragment, no whitespace or non-printable characters. Otherwise `WahooFitUnavailable("untrusted_url")`. |
| Request | One plain GET, `Accept: application/octet-stream`, no `Authorization` header, `User-Agent: Pacecraft`, 30 s timeout (`FIT_DOWNLOAD_TIMEOUT_SECONDS`). |
| Size | At most 16 MiB (`MAX_WAHOO_FIT_BYTES`), else `too_large`. |
| Failure reasons | `untrusted_url`, `rate_limited` (HTTP 429), `rejected` (other 4xx), `unavailable` (5xx, network error), `too_large` (`WAHOO_FIT_REASONS`). The URL never appears in an error or log. |
| Import policy (`wahoo_activity_details.py`) | Newest first; per run at most 10 downloads and a 120 s budget; per workout at most 3 attempts per summary hash; a rate-limit stops the run; a workout is skipped when a stored set already has the current summary hash and mapper version. |

Not mapped: it carries no canonical fields; the response body is returned as bytes unchanged.

### `fit_file.py`

Status: Live. Hardened stdlib FIT decoder used by `fit_activity_detail_mapping.py` (`fit_messages`, `fit_field`) and by `backend/coach/attachments.py` (uploaded FIT files; the session message 18 entries below belong to that use, not to detail mapping).
Inputs: raw FIT bytes. Returns `(global message number, {field number: value})` per data message.
Evidence: documented only (FIT SDK profile; `tests/test_fit_file.py`).

Decoder rules: header signature `.FIT` at bytes 8 to 12; header CRC checked when the header is longer than 12 bytes; file CRC checked when present (trailer must be 0 or 2 bytes); at most 200,000 data messages (`MAX_FIT_MESSAGES`, more than the 172,800 record messages a stream may hold; more gives `ValueError` and the mapper reports a `fit` issue and no sets); little- or big-endian per definition; compressed-timestamp headers rebuild field 253; developer fields are skipped; a field whose width does not divide by its base type size is kept as raw bytes. Values are `raw / divisor + offset` for the entries of `_FIT_FIELD_SCALES`, otherwise raw. The enhanced field of a pair (`_FIT_FIELD_PREFERENCES`) wins per message when it holds a usable value.

Invalid sentinels (`_FIT_INVALID_VALUES`, decoded to `None`; for arrays per element):

| Base type | Invalid value |
|---|---|
| enum (0), uint8 (2) | 0xFF |
| sint8 (1) | 0x7F |
| sint16 (3) | 0x7FFF |
| uint16 (4) | 0xFFFF |
| sint32 (5) | 0x7FFFFFFF |
| uint32 (6) | 0xFFFFFFFF |
| float32 (8), float64 (9) | NaN |
| uint8z (10), uint16z (11), uint32z (12), uint64z (16) | 0 |
| sint64 (14) | 0x7FFFFFFFFFFFFFFF |
| uint64 (15) | 0xFFFFFFFFFFFFFFFF |

Fields the detail mapper reads (global message number, field number, scale registered in `_FIT_FIELD_SCALES`):

| Message | Field | Name (`fit_file` table or SDK) | Scale / offset | Unit | Mapper use |
|---|---|---|---|---|---|
| record (20) | 253 | timestamp | 1 | s since 1989-12-31 UTC | `time_s` |
| record (20) | 5 | distance | /100 | m | `distance_m` |
| record (20) | 6, 73 | speed, enhanced_speed | /1000 | m/s | `speed_mps` (73 preferred) |
| record (20) | 2, 78 | altitude, enhanced_altitude | /5, -500 | m | `altitude_m` (78 preferred) |
| record (20) | 3 | heart_rate | 1 | bpm | `heart_rate_bpm` |
| record (20) | 4 | cadence | 1 | rpm | `cadence_rpm` |
| record (20) | 53 | fractional_cadence | /128 | rpm | added to `cadence_rpm` |
| record (20) | 7 | power | 1 | W | `power_w` |
| record (20) | 13 | temperature | 1 | degrees C | `temperature_c` |
| record (20) | 0, 1 | position_lat, position_long | raw | semicircles | not read by the detail mapper |
| lap (19) | 2 | start_time | 1 | s since FIT epoch | lap start offset |
| lap (19) | 7 | total_elapsed_time | /1000 | s | lap end offset |
| lap (19) | 8 | total_timer_time | /1000 | s | `moving_duration_s` |
| lap (19) | 9 | total_distance | /100 | m | `distance_m` |
| lap (19) | 13, 110 | avg_speed, enhanced_avg_speed | /1000 | m/s | `avg_speed_mps` (110 preferred) |
| lap (19) | 14, 111 | max_speed, enhanced_max_speed | /1000 | m/s | `max_speed_mps` (111 preferred) |
| lap (19) | 15, 16 | avg_heart_rate, max_heart_rate | 1 | bpm | `avg_hr`, `max_hr` |
| lap (19) | 17 | avg_cadence | 1 | rpm | `avg_cadence` |
| lap (19) | 19, 20 | avg_power, max_power | 1 | W | `avg_power`, `max_power` |
| lap (19) | 21 | total_ascent | 1 | m | `elevation_gain_m` |
| lap (19) | 23 | intensity | raw enum | | `kind` |
| lap (19) | 33 | normalized_power | 1 | W | `normalized_power` |
| set (225) | 0 | duration | /1000 | s | `duration_s` |
| set (225) | 3 | repetitions | raw | count | `reps` |
| set (225) | 4 | weight | /16 | kg | `weight_kg` |
| set (225) | 5 | set_type | raw enum | 0 rest, 1 active | `set_type` |
| set (225) | 6 | start_time | 1 | s since FIT epoch | `start_offset_s` |
| set (225) | 7 | category | raw array of uint16 | exercise_category enum | `exercise_category` |
| set (225) | 11 | wkt_step_index | raw | | `workout_step_index` (AND 0x0FFF) |

Also registered but not read by the detail mapper (used for uploaded files by `backend/coach/attachments.py`): the session message (18) fields 2, 7, 8, 9, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 34, 35, 36, 124, 125 with the scales listed in `_FIT_FIELD_SCALES`.

Not mapped: see the FIT mapper's "Not mapped" list.

## Candidate selection between detail sets of several providers

Selection is a read-time decision; stored sets are never merged on write. Kinds are stored once per provider activity (`replace_detail_set`: equal `content_sha256` only refreshes the fetch bookkeeping). `CanonicalDetailReader.read` (`performance/canonical_detail.py`) loads the sets of all records of the session, keeps those of non-Intervals records (`analysis_records`), pairs them with their record (`detail_candidates`, with `started_at` and `device_type`) and calls `merge_details`. Provider rank is `PROVIDER_PRECEDENCE`: `wahoo`, `garmin`, `intervals`. "Own copy" means `provenance.provider` equals `recorded_by` (the recording platform's own copy), rank 0.

| Part | Ordering key, best first (`detail_merge.py`) | What wins |
|---|---|---|
| Primary stream set (`_primary_stream_key`) | resolution (`full` before `downsampled`), own copy, more populated channels, provider rank, newest `fetched_at`, `provider_activity_id` | Fixes the time axis `time_s`. |
| Each channel (`_channel_key`) | resolution, device rank for that channel, own copy, the primary set first, provider rank, newest fetch, id | The best set that carries the channel and can be placed on the primary axis (`_place`): same axis and start, or both starts known with at least 80 % overlap (`MIN_ALIGNMENT_OVERLAP`); points are matched to the nearest sample within 2 median steps (`ALIGNMENT_TOLERANCE_INTERVALS`), else `None`. A channel taken from a set other than the primary is marked `aligned`. |
| Device rank (`_DEVICE_PREFERENCE`, from the record's `device_type`) | `heart_rate_bpm`: `chest_strap`, `watch`, `bike_computer`; `power_w` and `cadence_rpm`: `power_meter`, `bike_computer`, `watch`; `speed_mps`, `distance_m`, `altitude_m`, `grade_pct`: `bike_computer`, `watch`; other channels have no device ranking. | |
| Lap set (`_choose_laps`) | `lap_source` (`device_laps`, then `provider_intervals`, then `splits`), own copy, provider rank, newest fetch, id | One set; the others are listed as alternatives. Lap offsets are shifted onto the stream clock when the start difference is known (`on_stream_clock`). |
| Zone distribution per metric (`_choose_zones`) | bounded first (`boundary_source` not `unknown`, or every bucket has a `lower` or an `upper`), provider rank, newest fetch, id | Then `with_stream_zones` (`stream_zones.py`) puts a derived distribution first for each metric whose stream and threshold exist; the provider distribution becomes an alternative. |
| Strength sets (`select_strength_sets`, `strength_rank`) | `garmin_exercise_sets` before file sets, then provider (`garmin`, `wahoo`, `intervals`), then `provider_activity_id` | One list per session, never merged set by set. File sets (`fit_set_messages`) rank Garmin first because strength is recorded on the Garmin watch; this is not the `PROVIDER_PRECEDENCE` order of streams, laps and zones. |

The merged averages `avg_hr` and `avg_power` fall back to the merged stream mean (restricted to `moving` points when that channel is present) only when no record has the value (`_gap_fill`, labelled derived).

### Locally derived detail (`stream_zones.py`)

Only `stream_zones.py` builds a canonical detail record outside the provider mappers. It sets `buckets` (the `ZoneBucket` list, one per zone), `provider` (copied from the stream set's provenance) and reads the `speed_mps` channel for pace zones. The session analysis modules emit no stream, lap or zone record.

`stream_zones.py` (`with_stream_zones`, `_derived`, `_seconds`). Rule `METHOD_VERSION` 1 (the `mapper_version` of the in-memory candidate; it is never written to the database); `ZONE_TIMES_VERSION` 1 covers the report counting (`zone_times`). Constants: `LABEL` `Zoneneinstellungen`, `MIN_GAP_S` 30, `GAP_FACTOR` 3. For each metric `heart_rate` (channel `heart_rate_bpm`, unit bpm) and `power` (channel `power_w`, unit W) whose stream exists in the merged streams, and whose threshold (`lthr` or `ftp`) is known:

| Canonical field | Rule |
|---|---|
| `metric` | `heart_rate` or `power`. |
| `boundary_source` | `profile`. |
| `origin` | `fetch` (nominal; the record is not stored). |
| `provenance` | provider, `recorded_by`, `retrieved_at` and `source_record_id` of the stream set counted; `source_kind` `derived`; `label` `Zoneneinstellungen`. |
| `provider_activity_id` | that stream set's provider activity id. |
| `index` | zone number 1..n, n = number of limits + 1 (at most 20). Default limits in percent of threshold: power 55, 75, 90, 105, 120, 150 (7 zones, `POWER_ZONE_LIMITS`); heart rate of LTHR 68, 83, 94, 105 (5 zones, `HR_ZONE_LIMITS`); a local or provider zone configuration replaces them. |
| `seconds` | Each sample counts the time to the next sample. A step counts only when it is greater than 0 and at most `max(30, 3 x median step)`; the last sample counts nothing; where a `moving` channel exists only samples with `moving` at least 1 count; a value that is missing or negative is skipped; 0 is skipped except for `power` (coasting counts in zone 1). Zone = `ZoneSettings.absolute_zone(unit, value)` = `percent_zone(value / threshold * 100, limits)` (value at or below a limit belongs to that zone). No counted second gives no distribution. |
| `lower`, `upper` | `limit x threshold / 100` of the neighbouring limits; zone 1 has no `lower`, the top zone no `upper`; a bound outside the canonical bound range of the metric (`ZONE_BOUNDARY_BOUNDS`) is left `None`. |
| `label` | not set. |

`zone_times` (same module) counts the same way for the cross-session reports and returns plain dicts `{"id": "Z<n>", "secs": round(x, 1)}` per sensor `heart_rate`, `power` and, for runs, `pace` (speed stream against `threshold_pace`, speed 0 is no reading); these are stored in the session analysis payload (`SessionAnalysisStage._zone_times`, key `zone_times` with `label`), not as `ZoneDistribution` records.

`session_zones.py` emits no detail record. It resolves the `ZoneSettings` (thresholds at the session's local day, `DatedThresholds`: local, then Garmin, then Wahoo; indoor and virtual rides take the indoor FTP; limits from the effective zone configuration) that `stream_zones.py` counts with. Intervals.icu thresholds and configurations are never read.

`canonical_session_analysis.py` emits no `ZoneDistribution`, lap or stream record. It reads the merged streams and laps of the non-Intervals records. Versions as the code states: `ANALYSIS_VERSION` 3 (stored `analysis_version`), `METHOD_VERSION` 3 (v3: grade-adjusted Pa:HR of outdoor runs, #1770); its input fingerprint includes `stream_zones.ZONE_TIMES_VERSION` and the heart-rate histogram version. `stream_resolution` reports `full` or `downsampled` for the streams it read (`downsampled` if the time axis or any read channel comes from a `downsampled` set).

### Canonical fields not produced by this scope

| Item | Reason |
|---|---|
| `LapSource` member `splits` | No module emits it; only `detail_merge._LAP_SOURCE_RANK` ranks it. |
| `ActivityStreamSet` channels `grade_pct`, `moving` | Only the retired Intervals mapper produces them; Garmin, FIT and derived detail have none. |
| `ActivityLap` fields `name`, `load`, `intensity_pct` | Only the retired Intervals mapper. Garmin and FIT laps carry none. |
| `ActivityLap` field `kind` other than `lap` for Garmin laps | Garmin `lapDTOs` have no interval role; only the FIT mapper (`intensity`) and the Intervals mapper (`type`) set `work`, `recovery`, `warmup`, `cooldown`. |
| `ZoneBucket` field `label` | Only the retired Intervals mapper. |
| `ZoneDistribution` for FIT files | The FIT mapper reads no zone data, so Wahoo has no stored zone distribution. |
| `ActivityStrengthSet` field `exercise_name` for FIT sets, `start_offset_s` for Garmin sets | The FIT subtype (8) is not read; Garmin `startTime` is not mapped. |

## Garmin health, wellness and sleep mappers

Conventions used in the tables of this part:

- "Src" is `Provenance.source_kind` (`device_measured` or `provider_reported`), "agg" is `Observation.aggregation`
  (`ObservationAggregation`), "window" is `MeasurementContext.window`. A field without agg/window has none.
- Evidence: **observed** names a sanitized payload file stem in `userdata/attachments/payloads/`; **documented** means
  only code, SDK or Personal API docs; "fixture `x`" names `tests/fixtures/providers/garmin/<stem>.json`, the stem that
  exercises the family in `tests/test_garmin_health_mapping.py`.
- Key lists are alias priority order: `a` → `b` means first non-empty `a`, else `b` (`_named_value`, "non-empty"
  = not `None` and not `""`; `0` counts as present).

### `garmin_health_mapping.py`

Status: Live. `map_garmin_health` is called per stored element by `canonical_plans.py` (ingest and re-projection,
one-element list per list section, the record itself for single-record sections) and by `snapshot_projection.py`.
Mapper version: **19** (`MAPPER_VERSION`). Also carries the versions of `garmin_training_mapping.py` (the six
training sections and the endurance `groupMap`, see "Training sections" below), which is replayed by this module.
Inputs: the Garmin snapshot as a mapping section name → record or list of records (`GARMIN_HEALTH_SECTION_NAMES`);
`zone` = athlete zone (`ZoneInfo`), `retrieved_at` = fetch time of that section (`garmin_section_retrieved_at`: the
section's own freshness time, else the payload sync time; Body Battery also takes the morning refresh time).
Evidence: observed `garmin_sleep_daily_2026-11-03`, `garmin_personal_sleep_2026-11-03`, `garmin_personal_hrv_2026-11-03`,
`garmin_personal_dailysummaries`, `garmin_personal_weight_range`; all other families documented (fixtures named per family).

#### Common construction of every observation (`_HealthMapping.emit`)

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `kind` | from the table of the family | none | `MetricKind` member. |
| `value` | the family's key | `MetricValue(number, kind.unit)`; the unit is the `MetricKind` unit, never read from Garmin | Number must pass `coerce_number` (finite number or dot-decimal text, no bool, no comma) except weight/body fat (`coerce_comma_decimal_number`). |
| `observed_on` | per family (see Time handling) | none | Provider day, not a UTC date, except weight epoch dates. |
| `observed_at` | none for grouped fields; weight: first present of `timestampGMT` → `timestamp` → `measurementDate` → `date`; Body Battery sample: its own instant | weight: epoch > 1e11 is ms, text without offset is UTC, date-only text gives none; Body Battery sample: `utc_timestamp` (epoch > 1e10 is ms, ISO text, naive = UTC); stored as aware UTC | Only weight, body fat and Body Battery samples carry it (`_observed_at`, `_emit_body_battery_sample`). |
| `provenance` | none | `Provenance(provider=garmin, source_kind=..., source_record_id=..., recorded_by=garmin, retrieved_at=retrieved_at, label="Garmin Connect", context=...)` | Provenance keyword fields: `provider` (`garmin`), `source_kind`, `source_record_id`, `recorded_by` (`garmin`), `retrieved_at`, `label`, `context`. `recorded_by` is `manual` for a manual weigh-in only (`sourceType` = `MANUAL`, case-insensitive). `context` is `UNKNOWN_CONTEXT` except `window` = `overnight` for last-night HRV and the four sleep night values. Garmin reports no device/firmware/sensor, so `device_model`, `firmware`, `sensor` stay unset. |
| `sport` | per family | `Sport` member or none | `ride`, `run`, or none (generic). |
| `method` | only HRV last night: constant `rmssd` | none | Weekly HRV and all other fields have no method. |
| `aggregation` | per family | none | `mean`, `minimum`, `total`, `sample` only. |
| `source_record_id` | none | `<section>:<day>` + `:<index>` when the section payload is a list (index = list position; the canonical plan stores list elements one by one, so `0`) + `:<suffix>` | Suffix is the group key (`generic`, `cycling`, `running`, `speed_and_heart_rate`, `power`), the kind value (race predictions, training), the history key (`performance_history`), `level` (Body Battery sample), the node ordinal (heart-rate zones). Weight: `weight:<day>:<n>` with `<n>` = list index of the enclosing list item, else the walk ordinal. Body fat: `body_fat:<day>:<n>` with `<n>` always the walk ordinal (pre-order mapping count), never the list index. |

Plausibility (`_within_bounds`, `METRIC_BOUNDS`): a value outside the closed bounds is dropped and reported as
`OUT_OF_RANGE` (issue names record index and field only). Zero is rejected for every kind except `_ZERO_ALLOWED`:
`sleep_score`, `steps`, `floors`, `daily_energy_active`, `stress`, `body_battery`, `body_battery_charged`,
`body_battery_drained`, and the training kinds `acute_load`, `chronic_load`, `acute_chronic_ratio`,
`load_balance_aerobic_low`, `load_balance_aerobic_low_target_min`, `load_balance_aerobic_low_target_max`,
`load_balance_aerobic_high`, `load_balance_aerobic_high_target_min`, `load_balance_aerobic_high_target_max`,
`load_balance_anaerobic`, `load_balance_anaerobic_target_min`, `load_balance_anaerobic_target_max`,
`running_tolerance`. `_UNSET_WHEN_ZERO` kinds (`spo2`, `spo2_lowest`, `respiration_rate`, `sleeping_hr`) skip a `0`
silently ("not measured", no issue).

Time handling: `_record_day` takes the first present of the section's date keys; `calendarDate` for every section
except `daily_stats` (`calendarDate` → `summaryDate` → `date`, `GARMIN_DATE_ALIASES`) and FTP range records (`from`).
`sleep` also accepts `dailySleepDTO.calendarDate`. Day text must be strict `YYYY-MM-DD` (`_parse_day`); `cycling_ftp`
and `cycling_ftp_history` accept an ISO datetime and keep its date (`_iso_day`, no zone conversion). The day is
Garmin's own calendar day, never converted by the athlete zone. Undated records fall back to the sync day
`local_date(retrieved_at, zone)` for `running_threshold`, `race_predictions`, `heart_rate_zones` and the latest
`cycling_ftp`; every other undated record is reported `MISSING` (field = first date key) and not mapped.
Exceptions: Body Battery samples are dated by their own instant in the athlete zone (`local_date(observed_at, zone)`);
weight epoch milliseconds are read as a UTC date (`_epoch_day`).

#### Section index (collector call → section → mapper entry)

| Section | Garmin call (transport) | Mapper entry | Evidence |
|---|---|---|---|
| `sleep` | `get_sleep_daily(start, end)` (Personal `/sleep-service/sleep/dailySleepSummariesByDate`, rows wrapped by `wrap_daily_sleep` into `{calendarDate, dailySleepDTO}`); morning/backfill night `get_sleep_data(date)` (Personal `/sleep-service/sleep/dailySleep`, `morning_sleep_element`) | `_GROUPED_SECTIONS["sleep"]` | observed |
| `hrv` | `get_hrv_data_range(start, end)` (Personal `/hrv-service/hrv/daily/{s}/{e}`), rows unwrapped from `hrvSummaries` by `normalize_range_records` | `_GROUPED_SECTIONS["hrv"]` | observed (single-day shape) |
| `resting_hr` | `get_heart_rates(day)` per day (Personal `/wellness-service/wellness/dailyHeartRate`); backfill rows `{calendarDate, restingHeartRate}` built by `_resting_rows` from daily summaries | `_GROUPED_SECTIONS["resting_hr"]` | documented, fixture `resting_hr` |
| `readiness` | SDK `get_training_readiness(today)` | `_GROUPED_SECTIONS["readiness"]` + `morning_readiness` | documented, fixture `readiness` |
| `max_metrics` | SDK `get_max_metrics_range(today-89, today)` | `_GROUPED_SECTIONS["max_metrics"]` | documented, fixture `max_metrics` |
| `running_threshold` | SDK `get_lactate_threshold(latest=True)` | `_map_running_threshold`, `_THRESHOLD_GROUPS` | documented, fixture `running_threshold` |
| `cycling_ftp` | SDK `get_cycling_ftp()` | `_GROUPED_SECTIONS["cycling_ftp"]` | documented, fixture `cycling_ftp` |
| `cycling_ftp_history` | SDK `get_functional_threshold_power_range(start, end, sport="CYCLING", aggregation="daily")` | `_GROUPED_SECTIONS["cycling_ftp_history"]`, `_FTP_RANGE_GROUPS` | documented, fixture `cycling_ftp_history` |
| `heart_rate_zones` | `get_heart_rate_zones()` (Personal `/biometric-service/heartRateZones/v2`) | `_map_heart_rate_zones` | documented, fixtures `heart_rate_zones`, `personal/heart_rate_zones` |
| `weight` / `weigh_ins` / `weighIns` | `get_weigh_ins(start, end)` (Personal `/weight-service/weight/range/{s}/{e}?includeAll=true`) | `_map_weight`, `_WeightWalk` | observed `garmin_personal_weight_range` |
| `daily_stats` | `get_daily_summaries(start, end)` (Personal `/usersummary-service/v2/dailysummaries`), per-day `get_user_summary(day)` fallback and `_with_resting_energy` | `_GROUPED_SECTIONS["daily_stats"]` after `flatten_daily_summary` | observed `garmin_personal_dailysummaries` |
| `body_battery` | `get_body_battery(start, end)` (Personal `/wellness-service/wellness/bodyBattery/reports/daily`), read only by the morning flow (`garmin_morning.py`) | `_GROUPED_SECTIONS["body_battery"]` + `_map_body_battery_levels` | documented, fixture `body_battery` |
| `race_predictions` | SDK `get_race_predictions()` | `_map_race_predictions` | documented, fixture `race_predictions` |
| `endurance_score` | SDK `get_endurance_score(start, end, aggregation="daily")` | `_GROUPED_SECTIONS["endurance_score"]` | documented, fixture `endurance_score` |
| `performance_history` | none: written by `append_garmin_performance_history` (90 days of `{date, metrics}`) | `_map_performance_history` | documented |
| training sections | SDK calls named in "Training sections" | `training_values`, `endurance_group_values` | documented |

#### Sleep (`sleep`)

One element = one night. Every field is read from the record itself first, else from `dailySleepDTO` (SDK element and
Personal flat row wrapped by `wrap_daily_sleep` map alike, `_group_number`). Observed in
`garmin_sleep_daily_2026-11-03` (SDK, under `dailySleepDTO`) and `garmin_personal_sleep_2026-11-03` (flat, floats).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `sleep_duration` | `sleepTimeSeconds` → `sleepDuration` (`GARMIN_SLEEP_DURATION_ALIASES`) | seconds, bounds 0 to 86400, 0 rejected | Src `device_measured`. Observed. |
| `sleep_score` | `sleepScore` → `overallSleepScore` (`GARMIN_SLEEP_SCORE_ALIASES`), on the record, then on `dailySleepDTO`, then `dailySleepDTO.sleepScores.overall.value` | score 0 to 100, 0 kept | Src `provider_reported`. Only the nested `overall.value` appears in both payloads; the flat aliases are documented. |
| `spo2` | `averageSpO2Value` | percent, bounds 50 to 100 (below 50 is `OUT_OF_RANGE`); `0` = not measured, skipped silently | Src `device_measured`; agg `mean`; window `overnight`. Observed (int in SDK, float in Personal). |
| `spo2_lowest` | `lowestSpO2Value` | percent, bounds 50 to 100; `0` skipped | Src `device_measured`; agg `minimum`; window `overnight`. Observed. |
| `respiration_rate` | `averageRespirationValue` | breaths/min, bounds 4 to 60; `0` skipped | Src `device_measured`; agg `mean`; window `overnight`. Observed. |
| `sleeping_hr` | `avgHeartRate` | bpm, bounds 20 to 250; `0` skipped | Src `device_measured`; agg `mean`; window `overnight`. Observed. |

Date: `calendarDate` of the record, else of `dailySleepDTO` (provider day, no zone conversion). The same element also
yields a `SleepPeriod` (see `sleep_period_mapping.py`). Garmin's whole-day pulse-ox and respiration summaries cover
another window and are not mapped.

#### Heart-rate variability (`hrv`)

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `hrv_rmssd` | `hrvLastNight` → `lastNightAvg` | ms, bounds 0 to 500, 0 rejected | Src `device_measured`; method `rmssd`; agg `mean`; window `overnight`. Observed `lastNightAvg` (inside `hrvSummary` in `garmin_personal_hrv_2026-11-03`). |
| `hrv_weekly_average` | `hrvWeeklyAvg` → `weeklyAvg` | ms, bounds 0 to 500, 0 rejected | Src `provider_reported`; no method, agg or window (a different window, never a stand-in for last night). Observed `weeklyAvg`. |

Date: `calendarDate` of each summary row. The collector unwraps `hrvSummaries` (`normalize_range_records`); the mapper
reads the flat summary object. Unverified: the observed Personal file has the single-day shape with a singular
`hrvSummary` wrapper and `hrvReadings`, which `normalize_range_records` does not unwrap (it accepts `hrvSummaries` or a
list only) and which the mapper alone reports as `MISSING` `calendarDate`. The Personal range response is documented
(tests) as `hrvSummaries`.

#### Resting heart rate (`resting_hr`)

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `resting_hr` | `restingHeartRate` → `restingHR` → `resting_heart_rate` | bpm, bounds 20 to 250, 0 rejected | Src `device_measured`. Documented, fixture `resting_hr`. The collector adds `calendarDate` when the day response lacks one. Backfill rows take `restingHeartRate` else `heartRate.restingValue` of a daily summary (positive numbers only). |

#### Readiness (`readiness`)

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `readiness` | `score` → `trainingReadinessScore` → `overallReadinessScore` → `readinessScore` (`GARMIN_READINESS_ALIASES`) | score 0 to 100, 0 rejected | Src `provider_reported`. Documented, fixture `readiness`. Garmin lists several readings per day; `morning_readiness` keeps one per `calendarDate` (first drop `inputContext` in `AFTER_POST_EXERCISE_RESET`, `UPDATE_REALTIME_VARIABLES`; then scored before unscored, then `inputContext` = `AFTER_WAKEUP_RESET`, then earliest `timestampLocal`, then earliest `timestamp`). Quirk: the ranking also counts the planning alias `trainingReadiness` as a score, which this section does not read. |

The categorical `level` of the same reading becomes a `readiness_level` code (see `CategoricalObservation`).

#### Maximum oxygen uptake (`max_metrics`)

Row `{calendarDate, generic, cycling, running}`; each object is read separately (`_Group.key`). Record id suffix =
group key.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `vo2max` (no sport) | `generic.vo2MaxPreciseValue` → `generic.vo2MaxValue` (`GARMIN_VO2MAX_ALIASES`) | ml/kg/min, bounds 5 to 120, 0 rejected | Src `provider_reported`. Documented, fixture `max_metrics`. |
| `vo2max` (sport `ride`) | `cycling.vo2MaxPreciseValue` → `cycling.vo2MaxValue` | same | A non-mapping group is `INVALID_TYPE`. |
| `vo2max` (sport `run`) | `running.vo2MaxPreciseValue` → `running.vo2MaxValue` | same | |

#### Thresholds (`running_threshold`)

Record `{speed_and_heart_rate: {...}, power: {...}}`; day = `calendarDate` if present, else the sync day (the collector
requests the latest value).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `threshold_pace` (sport `run`) | `speed_and_heart_rate.speed` | m/s; a value below 1 is multiplied by 10 (Garmin's scaled speed; `_field_value`), bounds above 0 to 15 | Src `provider_reported`. Pace is not computed here (display concern). Documented. Fixture `running_threshold` has speed 3.6 (kept as is); the scaling is exercised by a unit test in `tests/test_garmin_health_mapping.py` (0.35833233 becomes 3.5833233 m/s). |
| `threshold_hr` (sport `run`) | `speed_and_heart_rate.heartRate` | bpm, bounds 20 to 250 | |
| `threshold_hr` (sport `ride`) | `speed_and_heart_rate.heartRateCycling` | bpm | |
| `ftp` (sport `run`) | `power.functionalThresholdPower` | W, bounds above 0 to 2500 | Running threshold power stored as `ftp` for `run`; Garmin may derive it from cycling data, consumers apply their own plausibility window. |

#### Cycling FTP (`cycling_ftp`, `cycling_ftp_history`)

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `ftp` (sport `ride`), latest | `functionalThresholdPower` → `ftp` (`GARMIN_FTP_ALIASES`) | W, bounds above 0 to 2500 | Src `provider_reported`. Day = `calendarDate` (datetime accepted), else the sync day. Documented, fixture `cycling_ftp`. |
| `ftp` (sport `ride`), history | same aliases per row | W | Day = `calendarDate`; no sync-day fallback (undated = `MISSING`). Fixture `cycling_ftp_history`. |
| `ftp` (sport `ride`), range record (`cycling_ftp_history` only) | `value` (`GARMIN_FTP_RANGE_VALUE`) when `from` (`GARMIN_FTP_RANGE_DAY`) is non-empty (`_is_range_record`) | W | Day = `from` (datetime accepted). A bare `value` without `from` is not FTP. |

#### Heart-rate zones (`heart_rate_zones`)

Day = `calendarDate` else sync day. The whole record is walked (`_heart_rate_nodes`: the record, then every nested
mapping, list items capped at 100); every node yields at most one value.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `max_hr` | `maxHeartRateUsed` → `maxHeartRate` → `maxHR` of the node | bpm, rounded to 2 decimals; below 80 `OUT_OF_RANGE` (field reported = `maxHeartRateUsed`); canonical bound 250 drops 251 to 260 | Src `provider_reported`. Sport from `sport` → `sportType` → `activityType` of the node by `_heart_rate_sport`: text containing `cycling`/`cycl`/`bike`/`ride` is `ride`, containing `running`/`run` is `run`, else none. Id suffix = node ordinal. Documented, fixtures `heart_rate_zones` and `personal/heart_rate_zones`. |

#### Weight and body fat (`weight`, `weigh_ins`, `weighIns`)

First truthy section wins (`weight_payload`: `weight`, `weigh_ins`, `weighIns`). `_WeightWalk` visits every mapping
(depth 20, 2000 visits, 500 list items, keys `minweight`/`maxweight`/`weightdelta` and the body-fat equivalents not
entered); a record's day is the first present of `calendarDate` → `summaryDate` → `date` → `timestampGMT` →
`timestamp` (`WALK_DATE_KEYS`), inherited from the nearest dated ancestor when absent. Observed
`garmin_personal_weight_range` (`dailyWeightSummaries[].latestWeight`, plus `totalAverage` and `nextDateWeight`
objects the walk also visits: `nextDateWeight` is mapped as a dated weigh-in outside the requested range, weight and body fat; the undated `totalAverage` holds `weight`, so it is reported as `MISSING calendarDate`).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `weight` | `weightKg` → `weight_kg` → `weight`; a nested object is unwrapped via `weightKg` → `weight_kg` → `weight` → `value` | kg. Unit from `unitKey` → `unit` → `weightUnit` (the nested object's unit wins): `gram`/`grams`/`g` divided by 1000, `kilogram`/`kilograms`/`kg` kept, containing `lb`/`pound` multiplied by 0.45359237; unknown or non-text unit is `UNKNOWN_VALUE`. No unit: above 300 is grams; under `latestWeight` or a nested value object a missing unit is grams. Mapper bounds 30 to 300 kg, then canonical 20 to 400. Not rounded | Src `device_measured`; a record with `sourceType` = `MANUAL` is `provider_reported` with `recorded_by` = `manual`. Observed (`latestWeight.weight` is sanitized to 0; the sibling `nextDateWeight`, `totalAverage` and `minWeight` values are floats in grams). `observed_at` as in the common table. Module docstring says kilograms are rounded to two decimals: the code does not round weight (only body fat). |
| `body_fat` | `bodyFat` → `body_fat` → `bodyFatPercent` → `bodyFatPercentage` → `fatPercent` (`GARMIN_BODY_FAT_ALIASES`); nested value `value` → `val` → `amount` | percent. Unit from `bodyFatUnit` → `bodyFatUnitKey` (nested: `unitKey` → `unit` → `bodyFatUnit`): `fraction`/`ratio` times 100, `percent`/`%`/no unit kept, any other `UNKNOWN_VALUE`. Mapper bounds 2 to 70, rounded to 2 decimals, canonical 1 to 80 | Same source/provenance rules as weight; date issues are reported once through the weight walk when the record also holds a weight. Observed (`latestWeight.bodyFat`). |

#### Daily summary (`daily_stats`)

`flatten_daily_summary` first adds flat aliases for the nested range-endpoint shape (existing flat keys win; `None`
and `""` are dropped; a nested `calories` mapping is removed): `calories.burnedTotal` → `totalKilocalories`,
`calories.burnedActive` → `activeKilocalories`, `calories.burnedResting` → `bmrKilocalories`,
`movement.steps.value` → `totalSteps`, `movement.floorsAscended.value` → `floorsAscended`, `stress.avgLevel` →
`averageStressLevel`. Undated wrappers are replaced by their dated descendants (`_daily_stats_records`, 2000 visits,
500 list items). Day = `calendarDate` → `summaryDate` → `date`. All nested paths observed in
`garmin_personal_dailysummaries`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `steps` | `totalSteps` → `total_steps` → `steps` → `stepCount` → `step_count` | count, rounded to integer (`whole`), bounds 0 to 200000, 0 kept | Src `device_measured`. |
| `floors` | `floorsAscended` → `floors_ascended` → `floors` → `floorsUp` → `floors_up` | count, rounded, bounds 0 to 1000, 0 kept | Src `device_measured`. |
| `daily_energy_total` | `totalKilocalories` → `total_kilocalories` → `totalCalories` → `total_calories` → `calories` | kcal, bounds above 0 to 20000 | Src `provider_reported`; provider total, never estimated; 0 rejected. |
| `daily_energy_active` | `activeKilocalories` → `active_kilocalories` → `activeCalories` → `active_calories` → `activeCaloriesBurned` → `active_calories_burned` | kcal, 0 kept | Src `provider_reported`. |
| `daily_energy_resting` | `bmrKilocalories` → `bmr_kilocalories` → `bmrCalories` → `bmr_calories` → `restingKilocalories` → `resting_kilocalories` → `restingCalories` → `resting_calories` → `basalMetabolicRateKilocalories` | kcal, 0 rejected | Src `provider_reported`; agg `total`. The collector completes range rows that lack it from the per-day `get_user_summary` (summary keys win on overlap, `_with_resting_energy`). |
| `stress` | `averageStressLevel` | score 0 to 100, 0 kept | Src `provider_reported`; agg `mean`. Garmin's daily mean stress. |

#### Body Battery (`body_battery`)

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `body_battery_charged` | `charged` | score units 0 to 500, 0 kept | Src `provider_reported`; agg `total`. Day = `calendarDate` else `date` (the SDK's `BodyBatteryEntry` names it `date`). Documented, fixture `body_battery`. |
| `body_battery_drained` | `drained` | score units 0 to 500, 0 kept | Same. |
| `body_battery` | each `[timestamp, level]` of `bodyBatteryValuesArray` → `body_battery_values_array` (level = element 1) | level rounded to integer, bounds 0 to 100, 0 kept | Src `provider_reported`; agg `sample`; `observed_at` = `utc_timestamp(sample[0])` (epoch s or ms, ISO); `observed_on` = that instant's date in the athlete zone; id `body_battery:<sample day>:<idx>:level`. One `INVALID_NUMBER` issue per record when any sample is unreadable; a non-list array is `INVALID_TYPE`. Documented. |

The SDK's own `BodyBatteryEntry` response model (module `garminconnect.typed`) and the transport tests key the day as `date`; the
grouped mapping reads `calendarDate` else `date` (`_SECTION_DATE_KEYS`). Samples are dated by their own instant and do
not need either.

#### Race predictions (`race_predictions`)

Day = `calendarDate` else sync day. All mapping values are searched depth-first (depth 8, list items 100): per record
first the distance/time pair, then every key. Slot of a key or distance text (`_race_kind`, casefolded letters and
digits only, order matters): contains `halfmarathon` or `half` → half; `marathon` → full; `10k`, `10km`, `10000m` → 10k;
`5k`, `5km`, `5000m` → 5k. The first readable time per slot wins.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `race_prediction_5k` | a key named for 5k (fixture `5k`), or a record pairing `raceDistance` → `distanceName` → `raceType` → `distance` (text) with `raceTime` → `racePredictionTime` → `predictedTime` → `time` → `seconds` | seconds (`_race_seconds`): a number above 100000 is ms (divided by 1000), rounded to 2 decimals; `mm:ss` or `h:mm:ss` text converted; an object uses the first time alias incl. `value`; bounds 60 to 100000 | Src `provider_reported`; sport `run`. Documented, fixture `race_predictions`. |
| `race_prediction_10k` | key named for 10k, e.g. fixture `10k` | same | |
| `race_prediction_half` | key named for half marathon, e.g. fixture `halfMarathon` | same | |
| `race_prediction_full` | key named for marathon, e.g. fixture `marathon` | same | |

The module docstring says deeper nesting is not searched; the code searches nested containers to depth 8.

#### Endurance score (`endurance_score`)

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `endurance_score` | `overallScore` (`GARMIN_ENDURANCE_SCORE_ALIASES`) after unwrapping `enduranceScoreDTO` / `enduranceScoreDTOList` repeatedly (`_endurance_records`) | score, bounds above 0 to 20000 | Src `provider_reported`. Day = `calendarDate`. Documented, fixture `endurance_score`. The per-sport `groupMap` is mapped by the training reader below, not here. |

#### Performance history (`performance_history`)

Rows `{date, metrics: {...}}` written by the sync from its own earlier values (plus daily FTP history); mapped
**fill-only** (`canonical_plans.py` passes `fill_only` for this section: a value never replaces one a dedicated
section wrote for the same natural key). Day = `date`; unreadable = `INVALID_TYPE`; a `metrics` value that is not a
positive number = `INVALID_NUMBER`. All values Src `provider_reported` (the history weight copies the latest weigh-in
without its source type, so it is not claimed as a scale value). Id `performance_history:<date>[:idx]:<key>`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `weight` | `weight_kg` | kg | |
| `ftp` (sport `ride`) | `cycling_ftp_watts` | W | |
| `vo2max` (sport `ride`) | `cycling_vo2max_ml_kg_min` | ml/kg/min | |
| `vo2max` (sport `run`) | `running_vo2max_ml_kg_min` | ml/kg/min | |
| `ftp` (sport `run`) | `run_threshold_watts` | W | |
| `threshold_pace` (sport `run`) | `run_threshold_pace_seconds_per_km` | `1000 / value` gives m/s | The only converted key. |
| `threshold_hr` (sport `run`) | `run_threshold_hr_bpm` | bpm | |
| `threshold_hr` (sport `ride`) | `bike_threshold_hr_bpm` | bpm | |
| `readiness` | `readiness` | score | |
| `race_prediction_5k` | `run_5k_seconds` | seconds (sport `run`) | |
| `race_prediction_10k` | `run_10k_seconds` | seconds (sport `run`) | |
| `race_prediction_half` | `run_half_marathon_seconds` | seconds (sport `run`) | |
| `race_prediction_full` | `run_marathon_seconds` | seconds (sport `run`) | |

Other `metrics` keys (including the activity-derived max heart rate keys) are not mapped.

#### Training sections (delegated to `garmin_training_mapping.py`, ride on `MAPPER_VERSION` 18)

`TRAINING_SECTIONS` are mapped through `training_values` / `endurance_group_values` (another writer documents the
reader). The health mapper emits each value Src `provider_reported`, no agg or window, number via `coerce_number`, id
`<section>:<day>:<suffix>`. A device-keyed section whose devices disagree yields no value and one `UNKNOWN_VALUE` issue
(`unresolved_device_record`). Documented only (fixtures `daily_training_status`, `training_load_balance`,
`training_status`, `running_tolerance`, `endurance_score`).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `acute_load` | `daily_training_status`: primary device record `acuteTrainingLoadDTO.dailyTrainingLoadAcute`; `training_status`, `weekly_training_status`: `acuteTrainingLoad` → `dailyTrainingLoadAcute` at any depth | load units, bounds 0 to 100000, 0 kept | A row with two different values yields none. |
| `chronic_load` | `acuteTrainingLoadDTO.dailyTrainingLoadChronic` | load units | |
| `acute_chronic_ratio` | `acuteTrainingLoadDTO.dailyAcuteChronicWorkloadRatio` | ratio, bounds 0 to 100 | |
| `load_balance_aerobic_low`, `load_balance_aerobic_low_target_min`, `load_balance_aerobic_low_target_max` | `training_load_balance` device record `monthlyLoadAerobicLow`, `...TargetMin`, `...TargetMax` | load units | Primary device record, not an average. |
| `load_balance_aerobic_high`, `load_balance_aerobic_high_target_min`, `load_balance_aerobic_high_target_max` | `monthlyLoadAerobicHigh`, `...TargetMin`, `...TargetMax` | load units | |
| `load_balance_anaerobic`, `load_balance_anaerobic_target_min`, `load_balance_anaerobic_target_max` | `monthlyLoadAnaerobic`, `...TargetMin`, `...TargetMax` | load units | |
| `running_tolerance` (sport `run`) | `toleranceScore` | unit unknown, bounds 0 to 100000 | |
| `readiness` | `training_readiness_history` rows: `trainingReadinessScore` → `overallReadinessScore` → `readinessScore` → `score` → `trainingReadiness` | score | Morning reading of the day as in `readiness`. |
| `endurance_score_group_average`, `endurance_score_group_max` | `groupMap.<YYYY-MM-DD>.groupAverage`, `.groupMax` (read from the payload top level, not from the unwrapped DTO) | score, bounds above 0 to 20000 | Day = the `groupMap` key. |

Not mapped: Sleep (observed `garmin_sleep_daily_2026-11-03`, `garmin_personal_sleep_2026-11-03`): `napTimeSeconds`,
stage seconds (`deepSleepSeconds`, `lightSleepSeconds`, `remSleepSeconds`, `awakeSleepSeconds`),
`unmeasurableSleepSeconds`, `highestSpO2Value`, `lowestRespirationValue`, `highestRespirationValue`, `awakeCount`,
`avgSleepStress`, `sleepScores` parts other than `overall.value`, `sleepNeed`, `nextSleepNeed`, the SpO2/respiration/
heart-rate/stress/Body Battery/HRV sample arrays, skin temperature, and the SDK top-level `avgOvernightHrv`,
`hrvStatus`, `restingHeartRate`, `bodyBatteryChange` (no canonical kind in this wave; HRV, resting HR and Body Battery
come from their own sections). HRV: `lastNight5MinHigh`, `baseline.*`, `feedbackPhrase`, `hrvReadings`,
`createTimeStamp`. Daily summary: `heartRate.*` (resting heart rate is read via the `resting_hr` rows),
`bodyBattery.*`, `respiration.*`, `pulseOx.*`, `intensityMinutes.*`, `hydration.*`, `movement.floorsDescended`,
`stress.maxLevel` and proportions. Weight: `bmi`, `bodyWater`, `boneMass`, `muscleMass`, `physiqueRating`,
`visceralFat`, `metabolicAge`, min/max/delta values, `totalAverage`/`nextDateWeight` are visited by the walk like any
dated mapping. `activities` and `gear` sections are ignored here (own mappers). Fitness age (observed
`garmin_personal_fitnessage`) and profile settings (observed `garmin_personal_userprofile_settings`) have no mapper in
this module. Zone floors, `restingHeartRateUsed`, `lactateThresholdHeartRateUsed` and `trainingMethod` of the heart-rate
zones are not mapped. `hrvStatus`, readiness `level` and `trainingStatus` are mapped as categorical codes by the status
mapper, not here.

## Canonical record `SleepPeriod`

One sleep period with its bounds as one provider reported it (`backend/canonical/domain_records.py`); built only by `sleep_period_mapping.py`, whose section holds the provider keys and rules. Bounds are stored in UTC, a period is at most 24 hours, and `wake_date` must equal the local date of `end` in `timezone` (without a zone: within one day of the UTC date of `end`).

| Field | Type / rule | Notes |
|---|---|---|
| `start` | aware instant, UTC | Must be before `end`. |
| `end` | aware instant, UTC | |
| `wake_date` | date | Provider day when it fits, else the local date of `end`. |
| `kind` | `SleepKind`: `night` or `unknown` | |
| `timezone` | zone key or None | Set only when `local_date(end, zone)` equals `wake_date`. |
| `reported_duration_s` | seconds, 0 to 86,400, or None | The provider's sleep time; can be shorter than the bounds. |
| `bounds_method` | slug or None | Names the provider field pair the bounds came from. |
| `provenance` | `Provenance` | Provider required (`device_measured` for Garmin, `provider_reported` for Intervals.icu). |

### `sleep_period_mapping.py`

Status: Live for Garmin; the Intervals.icu branch only replays stored wellness rows (Intervals.icu is an output target
and is not read; the stored ingest store is removed by the #1728 purge).
Mapper version: none. Garmin periods are replayed by `garmin_health_mapping.py` v 19 (`GARMIN_HEALTH_VERSION`), the
Intervals.icu branch by the Intervals wellness mapper version (`INTERVALS_WELLNESS_VERSION`) in `canonical_plans.py`.
Inputs: `map_sleep_periods(payload, provider, source_record_id, retrieved_at, zone)`. Consumers: `canonical_plans.py`
`_garmin_batch` (Garmin `sleep` section element, `provider` = `garmin`, `source_record_id` = raw record id
`sleep/<element key>`) and `_wellness_batch` (Intervals.icu wellness row, `provider` = `intervals`, `source_record_id` =
the row id, a `YYYY-MM-DD` day). The intervals come from `backend/canonical/sleep_bounds.py`, shared with the sleep
timing variability methods.
Evidence: observed `garmin_sleep_daily_2026-11-03` (bounds `sleepStartTimestampGMT`/`sleepEndTimestampGMT`, epoch ms),
`garmin_personal_sleep_2026-11-03`, `intervals_wellness_2026-11-03` (has `sleepSecs` but no start/end field, so it yields
no period).

Interval rule (`sleep_intervals`): every mapping in the row (row itself, then nested mappings/lists, 2000 visits, 500 list
items) holding a start field and an end field gives one interval when end is after start and at most 24 hours later.
Start fields, first present wins: `sleepStartTimestampGMT`, `sleepStartTimestamp`, `sleep_start_at`, `sleepStart`,
`sleep_start`, `onset_at`. End fields: `sleepEndTimestampGMT`, `sleepEndTimestamp`, `sleep_end_at`, `sleepEnd`,
`sleep_end`, `wake_at`. Timestamps: number above 1e10 is epoch ms, other numbers epoch s, text is ISO (no offset = UTC)
(`utc_timestamp`). The `...Local` fields (`sleepStartTimestampLocal`) are not read. Duplicates: one interval per
(start, end) pair (last wins), then one per start (first wins) (`_distinct`).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `start` | start fields above | UTC instant | |
| `end` | end fields above | UTC instant | |
| `wake_date` | Garmin: `calendarDate` of `dailySleepDTO`, else of the row; Intervals.icu: `source_record_id` (the wellness day) | provider day text `YYYY-MM-DD` (`_provider_day`) | Used only when within one day of the end's UTC date (`_wake_date`); otherwise `local_date(end, zone)`. Garmin's own calendar day, not zone-converted. |
| `kind` | none | `night` for Garmin when the interval is at depth 0 or is the `dailySleepDTO` object (Garmin's main sleep of the day, whatever the clock time); `unknown` for every other interval and for all Intervals.icu intervals | Never classified by hour or length; naps are not mapped. |
| `timezone` | the ingest zone | zone key (only for a `ZoneInfo`) when `local_date(end, zone)` equals `wake_date`, else none | |
| `reported_duration_s` | Garmin: `sleepTimeSeconds` → `sleepDuration`; Intervals.icu: `sleepSecs`, from the same object as the interval | seconds, comma decimal accepted, kept when 0 to 86400 (`MAX_REPORTED_SLEEP_S`) else none | First present alias decides (an out-of-range first alias does not fall through). Observed `sleepTimeSeconds` and `sleepSecs`. |
| `bounds_method` | the field pair actually used | lower-cased `<start field>.<end field>`, e.g. `sleepstarttimestampgmt.sleependtimestampgmt` (`bounds_method`) | |
| `provenance` | none | `Provenance(provider=garmin or intervals, source_kind=..., source_record_id=..., recorded_by=..., retrieved_at=..., label=...)` | Provenance keyword fields: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`. Garmin: `device_measured`, `recorded_by` `garmin`, label "Garmin Connect". Intervals.icu: `provider_reported`, `recorded_by` `unknown`, label "Intervals.icu". |

Not mapped: napping (`napTimeSeconds`), sleep stage times, `...Local` timestamps, `autoSleepStartTimestampGMT`
(null in the observed payloads), any object with only one of start/end, intervals longer than 24 hours.

### `garmin_morning.py`

Status: Live (morning Body Battery refresh, `MorningBodyBatteryService`). Transport and record helpers, no
mapper version and no canonical record constructed here.
Inputs: `fetch_morning_body_battery` (login, `get_sleep_data(check-in date)`, then
`get_body_battery(range_start, check-in date)` with `range_start` = local date of the sleep start in the profile
timezone, else the athlete clock zone, else UTC); `morning_sleep_element`; `merge_garmin_records` (`merge_records`);
`latest_garmin_record` (fixture path). Callers: `garmin_service.py` and `morning_battery_service.py`.
Evidence: documented only (fixture `body_battery`; the sleep night shape is observed in `garmin_sleep_daily_2026-11-03`).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `sleep` section element | `dailySleepDTO` of the night (`morning_sleep_element`) | stored as `{calendarDate: <check-in date>, dailySleepDTO: <dto>}`; none when the DTO is empty | Mapped by `garmin_health_mapping.py` (sleep family) and `sleep_period_mapping.py`; the element is dated by the check-in date, the day the daily sleep read gives the same night. |
| `body_battery` section | the list returned by `get_body_battery` | stored as fetched (merged with the previous list by identity, new wins) | Mapped by `garmin_health_mapping.py` (Body Battery family): `body_battery`, `body_battery_charged`, `body_battery_drained`. |
| sleep bounds used to choose the range | `sleepStartTimestampGMT` → `sleepStartTimestamp` → `startTimestampGMT` and `sleepEndTimestampGMT` → `sleepEndTimestamp` → `endTimestampGMT` (`morning_battery.sleep_bounds`: first valid pair, `dailySleepDTO` first, 100 visits) | UTC instants | Only the fetch window; no canonical value. |
| record identity / date (`latest_garmin_record`) | `calendarDate` → `summaryDate` → `date` → `timestamp` → `id` (`RECORD_IDENTITY_KEYS`); newest record with a timestamp, then greatest identity text | none | Used to build the sleep payload from a fixture. |

#### Derived morning observations (Body Battery around sleep; fields in the locally derived section)

Not a provider mapper: derived local observations stored from the canonical `sleep` NIGHT period and `body_battery`
levels just stored (`canonical_morning_record`; without a canonical reader the fetched payloads are used). Method
`morning_body_battery`, method version 1.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `body_battery_before_sleep` | last Garmin `body_battery` level with `observed_at` in [sleep start minus 4 h, sleep start] | score 0 to 100, rounded | `Observation`: `observed_on` = check-in date (`sleep_date`), `observed_at` = sample instant, `kind`, `value`, `method`, `method_version` 1, `input_fingerprint` (sample plus sleep bounds), `provenance`. |
| `morning_body_battery` | first Garmin `body_battery` level in [sleep end, min(attempt time, sleep end plus 1 h)] | score 0 to 100, rounded | Same. |
| `provenance` | none | `Provenance(provider=none, source_kind=derived, source_record_id="night:<date>", recorded_by=garmin, retrieved_at=none, label="Garmin Connect (abgeleitet)")` | Rows are owned by the night; a refresh that picks another sample or none retires the earlier rows. The record is `ready` only with both values. |

The night is the Garmin `night` period whose `source_record_id` is `sleep/<check-in date>`; levels are read for
[check-in minus 2 days, check-in plus 1 day]; the sleep window is read for [check-in minus 1 day, check-in plus 1 day].

Not mapped: the rest of the sleep payload (see `garmin_health_mapping.py`); Body Battery `date`, `startTimestampGMT`,
other row fields.

### `garmin_fields.py`

Status: Live. Provider key constants and alias tuples (no mapping logic besides `flatten_daily_summary`,
`colon_time_parts`, `first_present`). Evidence: as in `garmin_health_mapping.py`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| dates | `GARMIN_CALENDAR_DATE_KEY` = `calendarDate`; `GARMIN_DATE_ALIASES` = `calendarDate`, `summaryDate`, `date`; `GARMIN_MEASUREMENT_DATE_ALIASES` = `date`, `calendarDate`, `summaryDate`, `measurementTime`, `timestamp`; `GARMIN_EXTENDED_DATE_ALIASES` = date aliases + `measurementTime`, `timestamp`; `GARMIN_SLEEP_DATE_KEYS` = `calendarDate`, `summaryDate` | | Only `GARMIN_DATE_ALIASES` is used by the health mapper (daily stats). |
| sleep family | `GARMIN_SLEEP_DURATION_ALIASES` = `sleepTimeSeconds`, `sleepDuration`; `GARMIN_SLEEP_SCORE_ALIASES` = `sleepScore`, `overallSleepScore` | | Also used by `sleep_period_mapping.py` (duration). |
| HRV family | `GARMIN_HRV_SUMMARIES_KEY` = `hrvSummaries`; `GARMIN_HRV_LAST_NIGHT_ALIASES` = `hrvLastNight`, `lastNightAvg`; `GARMIN_HRV_WEEKLY_ALIASES` = `hrvWeeklyAvg`, `weeklyAvg` | | |
| resting HR family | `GARMIN_RESTING_HR_ALIASES` = `restingHeartRate`, `restingHR`, `resting_heart_rate` | | |
| readiness family | `GARMIN_READINESS_ALIASES` = `score`, `trainingReadinessScore`, `overallReadinessScore`, `readinessScore` | | |
| VO2max / FTP | `GARMIN_VO2MAX_ALIASES` = `vo2MaxPreciseValue`, `vo2MaxValue`; `GARMIN_FTP_ALIASES` = `functionalThresholdPower`, `ftp`; `GARMIN_FTP_RANGE_DAY` = `from`; `GARMIN_FTP_RANGE_VALUE` = `value` | | |
| weight family | `GARMIN_BODY_FAT_ALIASES` = `bodyFat`, `body_fat`, `bodyFatPercent`, `bodyFatPercentage`, `fatPercent`; `GARMIN_WEIGHT_UNIT_ALIASES` = `unitKey`, `unit`, `weightUnit` | | The mapper uses its own `_WEIGHT_KEYS` / `_WEIGHT_VALUE_KEYS`. |
| daily stats | `GARMIN_STEPS_ALIASES`, `GARMIN_FLOORS_ALIASES`, `GARMIN_TOTAL_KCAL_ALIASES`, `GARMIN_ACTIVE_KCAL_ALIASES`, `GARMIN_RESTING_KCAL_ALIASES` (lists in the daily summary table); nested map `_NESTED_DAILY_FIELDS` | | |
| endurance | `GARMIN_ENDURANCE_SCORE_ALIASES` = `overallScore`; `GARMIN_ENDURANCE_WRAPPER_KEYS` = `enduranceScoreDTO`, `enduranceScoreDTOList` | | |
| race predictions | `GARMIN_RACE_TIME_ALIASES` = `raceTime`, `racePredictionTime`, `predictedTime`, `time`, `seconds`, `value`; `GARMIN_RACE_DISTANCE_ALIASES` = `raceDistance`, `distanceName`, `raceType`, `distance` | | `colon_time_parts` parses `mm:ss` / `h:mm:ss` (1 to 6 ASCII digits per part). |

Not mapped: n/a (constants only).

### `garmin_performance_fields.py`

Status: Live. Wire key names for the performance package and the sync (no mapping logic). Imports aliases from
`garmin_fields.py`. Evidence: documented only.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| dates | `CALENDAR_DATE` = `calendarDate`; `SUMMARY_DATE` = `summaryDate`; `ACTIVITY_START_LOCAL` = `startTimeLocal`; `RECORD_TIMESTAMP_KEYS` = date aliases + `timestamp`; `RECORD_IDENTITY_KEYS` = date aliases + `timestamp`, `id`; `METRIC_DATE_KEYS` = `date`, `calendarDate`, `summaryDate`, `from`; `PLANNING_ROW_DATE_KEYS` = `id`, `date`, `calendarDate`; `WELLNESS_ROW_DATE_KEYS` = `calendarDate`, `date`, `id`, `timestamp`; `OBSERVATION_DATE_FIELDS` = `calendarDate`, `summaryDate`, `date`, `measurementDate`, `timestampGMT`, `timestamp`, `startTimeLocal`, `startTimeGMT` | | Date resolution of the training readers (`METRIC_DATE_KEYS`), `latest_garmin_record` (identity/timestamp keys) and the ingest metrics. |
| HRV family | `WEEKLY_HRV_AVERAGE` = `hrvWeeklyAvg`, `WEEKLY_AVERAGE` = `weeklyAvg`, `HRV_NIGHT_AVERAGE` = `lastNightAvg`, `HRV_WITH_WEEKLY_ALIASES` = last-night + weekly aliases | | |
| resting HR | `RESTING_HEART_RATE` = `restingHeartRate` | | |
| readiness | `READINESS_SCORE` = `trainingReadinessScore`; `PLANNING_READINESS_ALIASES` = `trainingReadinessScore`, `overallReadinessScore`, `readinessScore`, `score`, `trainingReadiness` | | Differs from the health mapper's `GARMIN_READINESS_ALIASES` (order and the extra `trainingReadiness`); `training_readiness_history` uses this list. |
| weight family | `WEIGHT_KG` = `weightKg`; `WEIGHT_VALUE_ALIASES` = `weightKg`, `weight_kg`, `weight`, `value`; `WEIGHT_READING_ALIASES` = `weightKg`, `weight_kg`, `weight`; `WEIGHT_TIMESTAMP_ALIASES` = `timestampGMT`, `timestamp`, `measurementDate`, `date` | | Same order as the health mapper's `_WEIGHT_VALUE_KEYS` and `_WALK_TIMESTAMP_KEYS`. |
| sleep | `SLEEP_SECONDS` = `sleepTimeSeconds`; `SLEEP_DURATION_ALIASES` = `GARMIN_SLEEP_DURATION_ALIASES` | | |
| FTP | `FTP_VALUE` = `functionalThresholdPower`; `ACTIVITY_FTP_ALIASES` = `ftp`, `functionalThresholdPower`; `FTP_RANGE_DAY` = `from`; `FTP_RANGE_VALUE` = `value` | | Activity FTP alias order is the reverse of `GARMIN_FTP_ALIASES`. |
| max heart rate | `MAX_HEART_RATE_ALIASES` = `maxHeartRateUsed`, `maxHeartRate`, `maxHR` | | Same order as `_MAX_HR_KEYS`. |

Not mapped: n/a (constants only).

### Canonical fields not produced by this scope

- `Observation.period` (`ObservationPeriod`): no Garmin health observation sets a period; daily values use
  `observed_on` only.
- `ObservationAggregation.MAXIMUM`: not emitted by the health mapper.
- `Observation.method_version`, `Observation.input_fingerprint`: only the derived morning Body Battery observations
  (`morning_battery_service.py`) set them; the provider mapper does not.
- `MeasurementContext.device_model`, `firmware`, `algorithm`, `sensor`, `protocol`: Garmin reports none with these
  values, so only `window` is ever set.
- `Observation.sport` values other than `ride` and `run`: not emitted (generic readings carry no sport).
- `SleepPeriod`: all fields are produced by `sleep_period_mapping.py`.

## Canonical record `CategoricalObservation`

Defined in `backend/canonical/domain_records.py`. A provider status code on one day (for example a training status). Frozen dataclass; `__post_init__` validates, a bad value raises. Constructed only by `garmin_status_mapping.py` from provider data; `canonical_table_reader._categorical_observation` rebuilds it from the `categorical_observations` table. Stored per provider source record (`replace_categorical_observations` replaces all rows of one `source_record_id`). The table's `natural_key` is `provider|domain|sport|(observed_at or observed_on)` (`categorical_natural_key`), so a provider keeps one code per domain and day (sport is empty for Garmin).

| Field | Type / unit / rule | Emitted by | Notes |
|---|---|---|---|
| `domain` | `CategoricalDomain`: `training_status`, `readiness_level`, `hrv_status` | `garmin_status_mapping.py` | The domain follows the section: `hrv` -> `hrv_status`; `readiness` and `training_readiness_history` -> `readiness_level`; `daily_training_status` -> `training_status`. |
| `code` | text, regex `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}` in the record; the mapper uses the stricter `[A-Za-z][A-Za-z0-9_.-]{0,63}` | `garmin_status_mapping.py` | Kept exactly as Garmin sends it (case kept, never turned into a number). |
| `observed_on` | date | `garmin_status_mapping.py` | First 10 characters of the row's `calendarDate`; no time zone conversion. |
| `observed_at` | aware datetime or `None` | - (always `None`) | Garmin gives no instant for these codes in the mapper; `timestamp` / `timestampLocal` are read only to pick the morning readiness reading. |
| `provenance` | `Provenance`; the record requires a provider, a source record id and a `source_kind` other than `derived` | `garmin_status_mapping.py` | `provider` `garmin`, `source_kind` `provider_reported`, `recorded_by` `garmin`, `source_record_id` = raw record id (`<section>/<key>`, for example `hrv/<calendarDate>`; `daily_training_status` is one whole record), `retrieved_at` = fetch time of the section, `label` `Garmin Connect`. `context` stays the default (unknown). |
| `sport` | `Sport` or `None` | - | Not produced: the Garmin status codes are not per sport; the reader still accepts the column. |

### `garmin_training_mapping.py`

Status: Live. Pure reader module, no own mapper version and it builds no canonical record itself: it returns `TrainingValue` rows (`day`, `kind`, `raw`, `field`, `key`, `sport`) that `garmin_health_mapping.py` validates and emits as `Observation`s (`_HealthMapping._emit_training`). Called through `map_garmin_health` from `canonical_plans.py` (`_garmin_section_observations`, ingest and re-projection). Its helpers `history_rows` and `morning_readiness_records` are also used by `garmin_status_mapping.py` and by the stored-history readers `backend/sync/garmin_metric_history.py` and `backend/sync/garmin_performance_history.py`.
Mapper version: none of its own. Replayed by `garmin_health_mapping.py` v 19.
Inputs: Garmin sections of the stored collection payload (one raw record per element, `backend/canonical/garmin_payload.py`):
`daily_training_status` (SDK `get_daily_training_status(day)`), `training_load_balance` (SDK `get_training_four_week_load_balance(day)`), `training_status` (SDK `get_training_status(day)`, read per day), `weekly_training_status` (SDK `get_weekly_training_status`), `running_tolerance` (SDK `get_running_tolerance`, daily aggregation), `training_readiness_history` (SDK `get_training_readiness_range`) and `endurance_score` (SDK `get_endurance_score`, daily aggregation; only the `groupMap` part is read here). The Personal API does not serve any of them (`PERSONAL_METHODS` in `garmin_personal.py` lists them as SDK-only), so they exist only when the SDK client is connected. `garmin.py` reads `daily_training_status` and `training_load_balance` on every current-metrics read, the other history sections (`running_tolerance`, `training_readiness_history`, `weekly_training_status`, `endurance_score`) once per local day (`GARMIN_DAILY_METRIC_SOURCES`). The provider descriptor for Garmin declares the capabilities `activities`, `activity_details`, `daily_health`, `body`, `thresholds`, `gear`; no code maps an individual section to one of them (which one covers these sections: unverified). Range reads of a source are paused after repeated failures per source name (`garmin_capability_<source>`, `capability_allowed`).
Evidence: documented only. No file in the sanitized payload directory contains any of these keys (`acuteTrainingLoad`, `dailyTrainingLoadAcute`, `monthlyLoad*`, `toleranceScore`, `groupMap`, `trainingReadinessScore`, `latestTrainingStatusData`). Exercised by the synthetic wire fixtures `tests/fixtures/providers/garmin/daily_training_status.json`, `training_load_balance.json`, `training_status.json`, `running_tolerance.json`, `endurance_score.json`, `readiness.json` and by `tests/test_garmin_training_mapping.py`, `tests/test_garmin_health_mapping.py`, `tests/test_garmin_health_parity.py`, `tests/test_provider_wire_fixtures.py`.

Common emission rule (`_HealthMapping._emit_training`, `emit`): `number = coerce_number(raw)` (finite number or dot-decimal text; booleans, comma decimals, other types give no number). No number -> `MappingIssue(section, <provider key>, INVALID_NUMBER)` and the value is skipped. A number outside `METRIC_BOUNDS` -> `OUT_OF_RANGE`. Zero is kept as a measured value only for the load, load balance, ratio and tolerance kinds (`_ZERO_ALLOWED`); for `readiness`, `endurance_score_group_average`, `endurance_score_group_max` zero is rejected. No rounding, no unit conversion: the number is stored as sent. The `Observation` is `kind`, `value` (the number in the kind's unit), `observed_on` = the row's day, `observed_at` `None`, `provenance` (`provider` `garmin`, `source_kind` `provider_reported`, `recorded_by` `garmin`, `label` `Garmin Connect`, `retrieved_at` = section fetch time, `source_record_id` = `<section>:<day>:<key>`, with `key` the last column of the table), `sport` as in the table, `method` and `aggregation` unset. All values are Garmin's own calculation, never rebuilt locally.

Device-keyed sections (`daily_training_status`, `training_load_balance`): Garmin answers with one record per device, keyed by a device id; the key is never stored. `primary_device_record(payload, section_key, devices_key, comparable, day=...)` chooses the record. The devices map is read from the top level (`latestTrainingStatusData` / `metricsTrainingLoadBalanceDTOMap`) or, if absent there, from inside `mostRecentTrainingStatus` / `mostRecentTrainingLoadBalance`. Rules: at most 100 devices are looked at; exactly one record with `primaryTrainingDevice` `true` and a readable `calendarDate` wins (two primaries, or an undated primary, give no record); without a primary, the records with the latest readable `calendarDate` count, and one such record wins, several win only when they agree on every comparable field (daily status: `calendarDate` and the three `acuteTrainingLoadDTO` keys; load balance: `calendarDate` and the nine `monthlyLoad*` keys); otherwise no record. `unresolved_device_record(section, payload)` is true when devices are listed but no record can be chosen; the health mapper then reports `MappingIssue(None, <section>, UNKNOWN_VALUE)` so coverage shows the gap, and no value is emitted. The day is the chosen record's `calendarDate` (first 10 characters, `_iso_day`); a record without a readable day yields nothing.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `acute_load` (section `daily_training_status`) | `acuteTrainingLoadDTO.dailyTrainingLoadAcute` of the chosen device record | Garmin load, as sent; bound 0..100,000, zero kept | `_DAILY_FIELDS`. Record id `daily_training_status:<day>:acute_load`. |
| `chronic_load` | `acuteTrainingLoadDTO.dailyTrainingLoadChronic` | load, 0..100,000, zero kept | Same record, record id suffix `chronic_load`. |
| `acute_chronic_ratio` | `acuteTrainingLoadDTO.dailyAcuteChronicWorkloadRatio` | ratio, 0..100, zero kept | Record id suffix `acute_chronic_ratio`. |
| `load_balance_aerobic_low` (section `training_load_balance`) | `monthlyLoadAerobicLow` | load, 0..100,000, zero kept | `_BALANCE_FIELDS`; keys sit directly on the chosen device record (no nested DTO). Record id `training_load_balance:<day>:<kind>`. |
| `load_balance_aerobic_low_target_min` | `monthlyLoadAerobicLowTargetMin` | load | Target band of the low-aerobic load, lower end. |
| `load_balance_aerobic_low_target_max` | `monthlyLoadAerobicLowTargetMax` | load | Upper end. |
| `load_balance_aerobic_high` | `monthlyLoadAerobicHigh` | load | |
| `load_balance_aerobic_high_target_min` | `monthlyLoadAerobicHighTargetMin` | load | |
| `load_balance_aerobic_high_target_max` | `monthlyLoadAerobicHighTargetMax` | load | |
| `load_balance_anaerobic` | `monthlyLoadAnaerobic` | load | |
| `load_balance_anaerobic_target_min` | `monthlyLoadAnaerobicTargetMin` | load | |
| `load_balance_anaerobic_target_max` | `monthlyLoadAnaerobicTargetMax` | load | |
| `acute_load` (sections `training_status`, `weekly_training_status`) | `acuteTrainingLoad` or `dailyTrainingLoadAcute`, found at any depth of the row | load, 0..100,000, zero kept | `_history_value` / `_acute_load`: iterative walk over all nested mappings and lists (at most 2,000 nodes, 500 list items per list). Every candidate in 0..100,000 is collected by numeric value; exactly one distinct value gives the row's value (the same number under both keys counts once), two different values make the row ambiguous and give none. `field` in an issue is the key that carried the value. Record id `<section>:<day>:acute_load`. The value of these sections and of `daily_training_status` is one quantity; per the module docstring a day reported by several sections is one row (the exact dedupe lives in the ingest, not verified here). |
| `running_tolerance` (section `running_tolerance`) | `toleranceScore` | Garmin score, unit stays `unknown` in the vocabulary; 0..100,000, zero kept | Sport is always `run` (`Sport.RUN`). Record id `running_tolerance:<day>:running_tolerance`. A row without `toleranceScore` is skipped silently. |
| `readiness` (section `training_readiness_history`) | `trainingReadinessScore` -> `overallReadinessScore` -> `readinessScore` -> `score` -> `trainingReadiness` (`PLANNING_READINESS_ALIASES`) | score 0..100; zero rejected as out of range | First alias that is not `None` wins (a present non-number gives `INVALID_NUMBER`, no fallback). `trainingReadiness` is documented only. Record id `training_readiness_history:<day>:readiness`. Only the morning reading of each day is used (see `morning_readiness`). The separate `readiness` section is mapped by `garmin_health_mapping.py` with `GARMIN_READINESS_ALIASES` (`score` first) and the same morning rule; the alias order differs between the two. |
| `endurance_score_group_average` (section `endurance_score`) | `groupMap.<YYYY-MM-DD>.groupAverage` | score, 0..20,000; zero rejected | `endurance_group_values`: only a section value that is itself a mapping with a `groupMap` mapping is read (not under `enduranceScoreDTO` / `enduranceScoreDTOList`, not when the stored section is a list). At most 1,000 entries; the group key must be exactly 10 characters and an ISO day, otherwise the entry is skipped silently. Record id `endurance_score:<day>:endurance_score_group_average`. The overall `endurance_score` (`overallScore`) is mapped by `garmin_health_mapping.py`, not here. |
| `endurance_score_group_max` | `groupMap.<YYYY-MM-DD>.groupMax` | score, 0..20,000; zero rejected | Same rules; record id suffix `endurance_score_group_max`. |

Day of a history row (`training_status`, `weekly_training_status`, `running_tolerance`, `training_readiness_history`): `_row_day` collects the readable dates (first 10 characters) of `date`, `calendarDate`, `summaryDate`, `from` (`METRIC_DATE_KEYS`); exactly one distinct date gives the day, none or disagreeing dates skip the row silently. Rows come from `history_rows`, which unwraps up to eight levels of `data`, `weeklyTrainingStatusDTO`, `weeklyTrainingStatusDTOList`, `weeklyTrainingStatus`, `trainingStatusDTOList` and keeps at most 1,000 mapping rows.

`morning_readiness` (readiness history here, the `readiness` section in `garmin_health_mapping.py`, the readiness level in `garmin_status_mapping.py`): Garmin re-scores readiness during the day. A reading whose `inputContext` is `AFTER_POST_EXERCISE_RESET` or `UPDATE_REALTIME_VARIABLES` is dropped even when it is the only one (the raw layer stores each reading as its own element). Per day (`calendarDate` first, else `_row_day`) one reading is kept, ranked by: has a score (any `PLANNING_READINESS_ALIASES` or `GARMIN_READINESS_ALIASES` key), then `inputContext` `AFTER_WAKEUP_RESET`, then a local time `timestampLocal` (earliest text first; local times are compared with local times only), then a UTC `timestamp`, then list order. Undated readings are kept so their issues are reported. Note: a reading dated by `calendarDate` here can still be skipped later by `_row_day` when `date` / `summaryDate` / `from` disagree with it.

Not mapped (the code reads no other key; real extra keys are unverified because no payload covers these families): the device id keys of the two device-keyed sections; `primaryTrainingDevice` (used only to choose the record); `trainingStatus` and every other key of the device record except `calendarDate` and the named load keys (the status code is mapped by `garmin_status_mapping.py`); every `groupMap` key except `groupAverage` and `groupMax`; `groupMap` under the endurance-score wrappers `enduranceScoreDTO` / `enduranceScoreDTOList`, and a list-shaped `endurance_score` section (see the `endurance_score_group_average` row); readiness `level` (mapped as a status by `garmin_status_mapping.py`) and every other readiness key except the score aliases and the date and context keys named above.

### `garmin_status_mapping.py`

Status: Live. `map_garmin_status_codes(section, element, *, source_record_id, retrieved_at)` is called from `canonical_plans.py` (`_garmin_batch`) for the sections in `STATUS_SECTIONS` (`hrv`, `readiness`, `training_readiness_history`, `daily_training_status`), at ingest (`garmin_ingest_plan` via `_stored_garmin_batch`) and when stored rows are re-projected (`reprojection_plan`). The result travels as `DomainBatch.categorical` under the raw record's own `source_record_id`; any other section gives an empty tuple.
Mapper version: none of its own. Replayed by `garmin_health_mapping.py` v 19 (`GARMIN_HEALTH_VERSION` in `canonical_plans.py`).
Inputs: one stored element of the section (the exact mapper input, `wrapped` / `unwrapped` in `backend/canonical/section_items.py`). Feeds: `hrv` from SDK or Personal API `get_hrv_data_range` (Personal route `/hrv-service/hrv/daily/{start}/{end}`, unwrapped from `hrvSummaries` by `normalize_range_records`; it is the only family of this scope that `PERSONAL_METHODS` serves); `readiness` from SDK `get_training_readiness` (today) and `get_training_readiness_range` (recovery window); `training_readiness_history` from SDK `get_training_readiness_range` (daily metrics); `daily_training_status` from SDK `get_daily_training_status`. The element is a mapping or, for the list shaped sections, one row.
Evidence: documented only for the keys the mapper reads on the hrv rows. `hrvStatus` exists in the sanitized sleep response `garmin_sleep_daily_2026-11-03` as a top-level key, but the `sleep` section is not a status section and is not read here. `garmin_personal_hrv_2026-11-03` is the single-night shape: it carries `hrvSummary.status` and `hrvSummary.calendarDate` (nested), which this mapper does not read: it reads `hrvStatus` else `status`, and `calendarDate`, on the element itself, which is the shape of a range row (`hrvSummaries[]`; same field names as the observed summary). Shapes: `tests/fixtures/providers/garmin/hrv.json`, `readiness.json`, `daily_training_status.json` (synthetic) and `tests/test_garmin_training_mapping.py` (`StatusCodeTests`, `PlanTests`). `level` and `trainingStatus` are not in any payload file.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `domain` = `hrv_status` | section `hrv` | - | `CategoricalDomain.HRV_STATUS`. Rows: the element if it is a mapping, or at most 1,000 mapping rows of a list. |
| `code` (`hrv_status`) | `hrvStatus` else `status` | text, verbatim (for example `BALANCED`) | Must be text matching the code regex `[A-Za-z][A-Za-z0-9_.-]{0,63}`; free text with spaces, numbers or `None` give nothing, silently. No issue list is produced by this mapper. |
| `domain` = `readiness_level` | sections `readiness`, `training_readiness_history` | - | `CategoricalDomain.READINESS_LEVEL`. |
| `code` (`readiness_level`) | `level` | text, verbatim | Rows pass `morning_readiness_records` first (see `garmin_training_mapping.py`): re-score readings are dropped, one reading per day is kept, the same one the numeric `readiness` value is taken from. `training_readiness_history` rows come from `history_rows` (wrappers `data`, `weeklyTrainingStatusDTO`, ... are unwrapped). |
| `domain` = `training_status` | section `daily_training_status` | - | `CategoricalDomain.TRAINING_STATUS`. |
| `code` (`training_status`) | `trainingStatus` on the chosen device record | text, verbatim | The device is chosen by `primary_device_record` with comparable fields `calendarDate` and `trainingStatus` (the numeric loads in `garmin_training_mapping.py` use other comparable fields, so with several non-primary devices the two mappers can disagree about whether a record exists). A numeric `trainingStatus` has no verified meaning and is not mapped. |
| `observed_on` | `calendarDate` of the same row | first 10 characters as an ISO date; no time zone conversion | A row without a readable `calendarDate` is skipped silently, for every domain. If several rows give the same day only the first is kept (`setdefault` by day). |
| `observed_at` | - | always `None` | |
| `provenance` | - | `Provenance(provider=garmin, source_kind=provider_reported, source_record_id=<argument>, recorded_by=garmin, retrieved_at=<argument>, label="Garmin Connect")` | `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`. `provider` is `garmin`, `source_kind` is `provider_reported`, `recorded_by` is `garmin`. The mapper is bound to Garmin by `GARMIN_LABEL`. |
| `sport` | - | not set | Stays `None`. |

The constructor keywords used are `domain`, `code`, `observed_on`, `observed_at`, `provenance`.

Not mapped: the numeric hrv values of a row (`weeklyAvg`, `lastNightAvg`, ... are mapped by `garmin_health_mapping.py` as `Observation`s); the Personal API single-night wrapper `hrvSummary` (observed in `garmin_personal_hrv_2026-11-03`; if a stored element had only that nested shape no code would be produced, and no HRV value either, since the collector stores range rows); readiness `score` and its aliases (numeric, mapped in `garmin_training_mapping.py` / `garmin_health_mapping.py`), `inputContext`, `timestamp`, `timestampLocal` (used only to choose the reading); a numeric `trainingStatus`; every other key of the device record; the `sleep` section (`hrvStatus` in the sleep response is not read); any Garmin status outside the four sections.

## Canonical record `GearItem`

Defined in `backend/canonical/domain_records.py`. One piece of provider gear with its reported labels and totals. Frozen dataclass; `__post_init__` validates. Constructed only by `garmin_gear_mapping.py`; `canonical_table_reader._gear_item` rebuilds it from `gear_items` (the `details` column holds `activity_list_partial`). Stored per provider source record (`replace_gear_items`); the source record is `gear/<gearUUID>`.

| Field | Type / unit / rule | Emitted by | Notes |
|---|---|---|---|
| `gear_id` | text, 1..256 non-blank characters | `garmin_gear_mapping.py` | From `gearUUID`, stripped, cut to 200 characters. An element without it maps to nothing. |
| `name` | text up to 200 or `None` | `garmin_gear_mapping.py` | From `gearName`. |
| `type_label` | text up to 100 or `None` | `garmin_gear_mapping.py` | From `gearTypeName`. A Garmin label, not a canonical enum. |
| `activity_type_label` | text up to 100 or `None` | `garmin_gear_mapping.py` | From `activityTypeName`. Whether the real Garmin response carries this key is unverified. |
| `status_label` | text up to 100 or `None` | `garmin_gear_mapping.py` | From `gearStatusName`. |
| `maximum_distance_m` | m, 0..1,000,000,000 or `None` | `garmin_gear_mapping.py` | From `maximumMeters`, as sent. Out of range or non-number -> `None`. |
| `total_distance_m` | m, 0..1,000,000,000 or `None` | `garmin_gear_mapping.py` | From `stats.totalDistance`, as sent (metres). |
| `total_activities` | integer 0..1,000,000 or `None` | `garmin_gear_mapping.py` | From `stats.totalActivities`; a fractional, negative or non-number value -> `None`. |
| `provenance` | `Provenance` with provider and source record id, not `derived` | `garmin_gear_mapping.py` | `garmin`, `provider_reported`, `recorded_by` `garmin`, `label` `Garmin Connect`. |
| `activity_list_partial` | `bool` or `None` | `garmin_gear_mapping.py` | `None` = the link list is unknown (no `activity_ids` list); `True` = the list is truncated or kept from an earlier sync; `False` = complete. |

## Canonical record `GearActivityLink`

Defined in `backend/canonical/domain_records.py`. A provider's statement that one of its activities used one piece of gear. Frozen dataclass; the record requires the default (unknown) measurement context. Constructed only by `garmin_gear_mapping.py`; `canonical_table_reader._gear_activity_link` rebuilds it from `gear_activity_links` (`replace_gear_activity_links`). Equipment reads resolve `provider_activity_id` to canonical sessions through the provider activity id.

| Field | Type / unit / rule | Emitted by | Notes |
|---|---|---|---|
| `gear_id` | text, same value as the item's | `garmin_gear_mapping.py` | The `gearUUID` of the element. |
| `provider_activity_id` | text, 1..256 non-blank characters | `garmin_gear_mapping.py` | One link per distinct id of `activity_ids`. |
| `provenance` | `Provenance` as for `GearItem` | `garmin_gear_mapping.py` | Same instance as the item's. |

### `garmin_gear_mapping.py`

Status: Live. `map_garmin_gear(element, *, source_record_id, retrieved_at)` is called from `canonical_plans.py` (`_garmin_batch`, section `gear`) at ingest and at re-projection; the result is `DomainBatch.gear_items` and `DomainBatch.gear_links` under the raw record `gear/<gearUUID>` (one raw record per gear element).
Mapper version: none of its own. Replayed by `garmin_health_mapping.py` v 19 (`GARMIN_HEALTH_VERSION`).
Inputs: the `gear` section of the Garmin payload, built by `garmin.py` (`_collect_profile_metrics`, `_gear_inventory`) from SDK calls only (`get_user_profile` for the profile id, `get_gear(profile_number)` for the inventory, `get_gear_stats(uuid)` for totals, `get_gear_activities(uuid, 1000)` for the links; fallback `connectapi` read of the same activities URL when the list is an ambiguous empty result). The Personal API returns 404 for all gear calls (`PERSONAL_METHODS` comment), so gear needs the SDK client. An inventory of more than 100 items is rejected as invalid (the whole section is then an error); read at most once per local day (`GARMIN_DAILY_METRIC_SOURCES`) or after a new activity. The descriptor capability is `gear`. The stored element is the SDK gear row plus: `gearUUID` (from `gearUUID` or `uuid`), `gearName` (from `gearName`, else `displayName`, else `customMakeModel`, else `gearMakeName` + space + `gearModelName`), `stats` (the stats response or `{}`), `activity_ids` (list of strings: the `activityId` of each linked activity, order kept, duplicates removed), `activity_ids_truncated` (`True` when 1,000 or more were returned). `backend/sync/garmin.py` (`_keep_gear_activity_ids`) copies the previous `activity_ids` into an item whose link read failed and marks it `activity_ids_stale` `True` (plus the previous `activity_ids_truncated`).
Evidence: documented only (no gear key in any sanitized payload file). Shapes: `tests/fixtures/providers/garmin/gear.json`, `gear_stats.json` (synthetic SDK wire fixtures), `tests/test_garmin_gear_mapping.py`, `tests/test_sync_garmin_payload.py`, `tests/test_equipment_canonical_sessions.py`, `tests/test_provider_wire_fixtures.py`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `gear_id` (`GearItem`, `GearActivityLink`) | `gearUUID` | text stripped, cut to 200 characters | `_text`. Non-mapping element, missing or blank `gearUUID` -> `(), ()` (nothing). |
| `name` | `gearName` | stripped, cut to 200; blank -> `None` | The normalized name (see Inputs). |
| `type_label` | `gearTypeName` | stripped, cut to 100 | |
| `activity_type_label` | `activityTypeName` | stripped, cut to 100 | Documented only; not in the SDK wire fixture. |
| `status_label` | `gearStatusName` | stripped, cut to 100 | |
| `maximum_distance_m` | `maximumMeters` | m as sent; kept only if a finite number in 0..1,000,000,000 (`_distance`) | See open issue below on the spelling of the key. |
| `total_distance_m` | `stats.totalDistance` | m as sent, same bound | `stats.totalDuration` is not read. |
| `total_activities` | `stats.totalActivities` | integer; `_count` accepts a whole number in 0..1,000,000, else `None` | |
| `activity_list_partial` | `activity_ids`, `activity_ids_truncated`, `activity_ids_stale` | `None` if `activity_ids` is not a list; else `True` when `activity_ids_truncated` is `True` or `activity_ids_stale` is `True`, otherwise `False` | `_list_partial`. A missing `activity_ids` means the links are unknown, so no link is emitted. |
| `provenance` | - | `Provenance(provider=garmin, source_kind=provider_reported, source_record_id=<argument>, recorded_by=garmin, retrieved_at=<argument>, label="Garmin Connect")` | `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`. Values: `provider` `garmin`, `source_kind` `provider_reported`, `recorded_by` `garmin`. |
| `provider_activity_id` (`GearActivityLink`) | `activity_ids[]` | `str(value)`; at most 1,000 entries read, duplicates removed in order | Only text or integers (booleans rejected) that are non-blank and at most 256 characters; a longer id is skipped, never stored. The stored id is not stripped. |

Item construction is wrapped in `try/except (TypeError, ValueError)`: a record validation failure drops the item and its links. An implausible distance or count is left out (`None`) without dropping the item. Time: gear has no dates; `retrieved_at` is the fetch time of the `gear` section.

Not mapped: `uuid`, `displayName`, `customMakeModel`, `gearMakeName`, `gearModelName` (used only by `garmin.py` to build `gearUUID` and `gearName`); every other key of the SDK gear row (real extra keys unverified, no payload); `stats.totalDuration` (present in the synthetic stats fixture `gear_stats.json`); activity ids beyond the first 1,000 (`activity_ids_truncated`); per-activity dates of a link (a link is only gear plus activity id).

### Canonical fields not produced by this scope

- `CategoricalObservation.sport` and `CategoricalObservation.observed_at`: always `None` from `garmin_status_mapping.py`; no other mapper constructs `CategoricalObservation` from provider data (only `canonical_table_reader.py` rebuilds stored rows).
- `CategoricalDomain` members: all three (`training_status`, `readiness_level`, `hrv_status`) are produced, all by Garmin only. No other provider produces a categorical observation.
- `GearItem` and `GearActivityLink`: produced by Garmin only; Wahoo and Intervals.icu produce no gear.
- Sports of the training observations: only `run` (running tolerance) is set; every other training kind has `sport` `None`.
- `LoadModel` is not involved: the load balance and acute/chronic values here are Observations (`MetricKind`), not activity load; the per-activity Garmin training load is documented under `garmin_activity_mapping.py`.

## Wahoo thresholds and plans, Intervals.icu wellness, zones and power curve

Evidence terms: **observed** = the key exists in a sanitized payload file (stem named); **documented** = seen only in code, tests or a synthetic fixture. No sanitized Wahoo payload exists, so every Wahoo key is documented. Tests named by stem (`tests/<stem>.py`) build synthetic input only. The synthetic fixture `tests/fixtures/providers/intervals/athlete.json` shows an Intervals.icu athlete record with `sportSettings`; it is invented data, so keys seen only there are documented.

Time handling in this group: a wellness row has no instant; its `id` is the calendar day and becomes `observed_on` (`observed_at` stays `None`). Athlete-record values carry no date; the caller passes the athlete-local day of the fetch (`local_date(retrieved_at, zone)`). Wahoo zone sets are dated on the athlete-local day of `updated_at`, the profile weight on the athlete-local day of the fetch.

### `wahoo_threshold_mapping.py`

Status: Live. `WahooSyncService._threshold_fetch` (`backend/sync/wahoo_sync.py`) fetches both sources each Wahoo sync; `wahoo_ingest_plan` (`canonical_plans.py`, via `_wahoo_threshold_items`) maps them; `wahoo_payload_coverage` (`canonical_coverage_store.py`) counts them; `reprojection_plan` replays stored raw records of kind `power_zones` and `user` through `map_wahoo_power_zones` and `map_wahoo_user`.
Mapper version: **2**
Inputs: `GET /v1/power_zones` (scope `power_zones_read`, list of zone-set rows, `WahooClient.power_zones`) and `GET /v1/user` (scope `user_read`, one object, `WahooClient.user`). Entry points `map_wahoo_power_zones(rows, zone, retrieved_at)`, `map_wahoo_user(user, observed_on, retrieved_at)`, `map_wahoo_threshold_payload(power_zones, user, zone, retrieved_at)`; `None` for a source means it was not fetched.
Evidence: documented only (`tests/test_wahoo_threshold_mapping.py`, `tests/test_wahoo_client.py`, `tests/test_wahoo_sync.py`).

Both numbers accept numbers or text with a dot or comma decimal mark (`coerce_comma_decimal_number`); a boolean or other type is `INVALID_TYPE`, unreadable text `INVALID_NUMBER`, a value outside `METRIC_BOUNDS` `OUT_OF_RANGE`. Zero or blank means "not set" and yields nothing and no issue (`_measured`). Every observation has `observed_at` = `None`, `provenance.provider` = `wahoo`, `provenance.source_kind` = `provider_reported`, `provenance.recorded_by` = `wahoo`, `provenance.label` = `WAHOO_LABEL` ("Wahoo"), `provenance.retrieved_at` = the fetch time argument, `provenance.source_record_id` as below (`_provenance`). `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`; `Observation` arguments set: `kind`, `value`, `observed_on`, `observed_at`, `provenance`, `sport`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `kind` = `ftp`, `value` | power-zone row `ftp` | W, bounds 0 to 2,500 (`METRIC_BOUNDS`); unit from `MetricKind.FTP.unit` | `map_wahoo_power_zones`. One observation per workout-type family, from the newest zone set only (`select_power_zone_sets`). Zone boundaries of the row are not read. |
| `sport` | power-zone row `workout_type_family_id` | table `_FAMILY_SPORTS`: `0` -> `ride`, `1` -> `run` | Integer or digit text, minimum 0. Any other family id is an issue `UNKNOWN_VALUE` and the row is dropped (no observation). |
| `observed_on` | power-zone row `updated_at` | ISO text -> aware instant (`parse_provider_datetime`, naive text read as UTC) -> athlete-local calendar day (`local_date(updated, zone)`) | Missing -> `MISSING`, unparsable or non-text -> `INVALID_TYPE`, row dropped. |
| `provenance.source_record_id` | power-zone row `id` | integer or digit text, 1 to 2^63-1 (`_identifier`), stringified | Missing -> `MISSING`, non-digit text or boolean -> `INVALID_TYPE`, more than 19 digits or out of range -> `OUT_OF_RANGE`. |
| `kind` = `weight`, `value` | user `weight` | kg, bounds 20 to 400; unit `MetricKind.WEIGHT.unit` | `map_wahoo_user`. Out of range (below 20) is an issue, zero is "not set". `sport` = `None`. |
| `observed_on` (weight) | none in the profile | athlete-local day of the fetch: `local_date(retrieved_at, zone)` in `map_wahoo_threshold_payload`; `local_date(fetched, zone)` in `reprojection_plan` | The profile carries no date. |
| `provenance.source_record_id` (weight) | none | constant `USER_RECORD_ID` = `user` | Issues for the weight use the same id. |

Selection rule (`select_power_zone_sets`): per family keep the row with the greatest `(updated_at, input index)`, so an equal time keeps the later row; the chosen rows are returned in input order. A superseded readable row is not an issue. The input may be a list (stored rows) or a tuple (client rows); anything else is one issue on `power_zones` (`INVALID_TYPE`). The ingest stores exactly the chosen rows as raw records, so re-mapping one stored row reproduces its observation. A non-mapping row is an issue on `row`.

Not mapped: the rest of a power-zone row (zone boundaries, zone names and any other key; the key names are unverified, no payload), and from the profile every key except `weight` (the module names height, birth date and gender as not mapped; they stay in the raw record). Bike FTP of other sports is never produced: families other than 0 and 1 are dropped.

### `wahoo_plan_mapping.py`

Status: Live, outbound only. There is no inbound mapping; the module builds the Wahoo plan file for a local library workout. Caller: `WahooWorkoutExport.serialize_library` (`backend/sync/wahoo_workout_export.py`), created by `WahooSyncAssembly.workout_export` (`backend/sync/wahoo_sync_assembly.py`) for the plan push (`WahooPlanPushService`); `plan_references` (same file) builds the `WahooPlanReferences`. `tests/test_mapper_version_guard.py` lists it in `NOT_REPLAYED`; it has no `MAPPER_VERSION`.
Mapper version: none (nothing stored is replayed).
Inputs: a local library workout dict plus the expanded steps from `structured_steps(description, target)` (`backend/activities/workout_text.py`). Output: the plan document `{"header": ..., "intervals": [...]}` (version `PLAN_SCHEMA_VERSION` = `1.0.0`). `WahooClient.create_plan` / `update_plan` send it as the base64 data URI form field `plan[file]` with `plan[filename]` (`<external_id>.json`) and `plan[provider_updated_at]`; create also sends `plan[external_id]` = `coach-library-<local id>` (`wahoo_external_id`). These form fields are not part of the plan JSON.
Evidence: documented only (`tests/test_wahoo_plan_mapping.py`, `tests/test_wahoo_plan_push.py`, `tests/test_wahoo_plan_push_e2e.py`, `tests/test_wahoo_client_plans.py`). The plan JSON key semantics (for example that `ftp`-type targets are fractions of the header `ftp`) follow the Wahoo plan format PDF named in the module docstring; the PDF was not checked here, so that reading is **unverified** beyond what the code emits.

Workout fields read by `serialize_library`:

| Canonical planned-workout field | Plan JSON key | Unit / conversion | Notes |
|---|---|---|---|
| `name` (default `Coach-Einheit`) | `header.name` | text cut to `MAX_PLAN_NAME_LENGTH` = 200; `Coach workout` if empty | |
| `description` | `header.description` | text cut to `MAX_PLAN_DESCRIPTION_LENGTH` = 5000; key omitted when empty | The same text is parsed into the steps. |
| `sport` or legacy `type`, `environment`, `sport_detail` | `header.workout_type_family` | `Sport.RIDE` (`ride`) -> `0` (biking), `Sport.RUN` (`run`) -> `1` (running) | Resolved by `planned_sport_environment` (`workout_sport_from_record`). Any other sport raises `WahooPlanMappingError`. |
| `environment` | `header.workout_type_location` | `Environment.INDOOR` (`indoor`) and `Environment.VIRTUAL` (`virtual`) -> `0` (indoor); every other value (`outdoor`, `unknown`) -> `1` (outdoor) | |
| constant | `header.version` | `PLAN_SCHEMA_VERSION` = `1.0.0` | |
| `target` (`AUTO`, `POWER`, `HR`, `PACE`) | none | passed to `structured_steps` only | A step whose target kind differs from a non-`AUTO` unit target is rejected there. |
| `local_id` or `id` | none | `external_id` `coach-library-<id>`, filename `<external_id>.json` | Missing id raises `WahooPlanMappingError`. |

Plan header references (`WahooPlanReferences.header`): a key is written only when its value is set and non-zero. Values come from `plan_references(thresholds, sport)`: the resolved export thresholds of the plan's own sport (local zones, then Garmin, then Wahoo; never Intervals.icu), read once per push run and sport.

| Plan JSON key | Canonical source | Unit / conversion | Notes |
|---|---|---|---|
| `header.ftp` | `MetricKind.FTP` (`ftp`) observation | W, rounded to a whole number | Needed by percent-of-FTP power targets. |
| `header.max_hr` | `MetricKind.MAX_HR` (`max_hr`) | bpm, rounded | Needed by `% HR` targets. |
| `header.threshold_hr` | `MetricKind.THRESHOLD_HR` (`threshold_hr`) | bpm, rounded | Needed by `% LTHR` targets. |
| `header.threshold_speed` | `MetricKind.THRESHOLD_PACE` (`threshold_pace`) | m/s, not rounded | Needed by `% Pace` targets. |

A relative target whose reference is missing or zero is rejected (`_require`), never exported against a guessed value.

Step to interval (`_interval`, `_target`). The step dict from `structured_steps` carries `kind` (`power`, `hr`, `pace`), `target` (upper-cased text), `ramp` (bool) and either `duration` (seconds) or `distance` (metres; km, mi, yd converted by the parser):

| Plan JSON key | Step key / target text | Unit / conversion | Notes |
|---|---|---|---|
| `intervals[].intensity_type` | none | constant `active` | Rest and warm-up types are not written. |
| `intervals[].exit_trigger_type` / `exit_trigger_value` | `duration` | `time`, seconds, rounded to 3 decimals, integer when whole (`_number`) | `duration` wins when both keys exist. |
| same | `distance` | `distance`, metres, same rounding | Neither key: error. |
| (no key) | `ramp` true | rejected | Ramps are not supported. |
| `targets[0]` (`type`, `low`, `high`), kind `power`, bike only | `N-MW` or `NW` | `type` `watts`, W; `low` = min, `high` = max, single value gives `low` = `high` | Run plans reject power targets. |
| same | `N%`, `N-M%`, `N%-M%`, optional basis `FTP` | `type` `ftp`, fraction = percent / 100 | Needs `header.ftp`. |
| `targets[0]`, kind `hr` | `N-MBPM` | `type` `hr`, bpm | |
| same | `N-M% HR` | `type` `max_hr`, fraction = percent / 100 | Needs `header.max_hr`. |
| same | `N-M% LTHR` | `type` `threshold_hr`, fraction = percent / 100 | Needs `header.threshold_hr`. |
| `targets[0]`, kind `pace`, run only | `m:ss/KM` or `m:ss/MI`, optionally a range, then `PACE` | `type` `speed`, m/s = 1000 (km) or 1609.344 (mile) / seconds per unit; a faster pace is the larger value, so `low` = min speed | The high end's unit wins if both carry one; `/100M`, `/100Y` and other units, or no unit, are rejected; zero seconds is rejected. Bike plans reject pace targets. |
| same | `N-M% PACE` | `type` `threshold_speed`, fraction = percent / 100 | Needs `header.threshold_speed`. |
| (no key) | zone targets `Z2`, `Z1-Z3`, `Z2 HR`, `Z2 PACE` | rejected | Zones need the athlete's zone model. |

Every unsupported part raises `WahooPlanMappingError` (HTTP 422, reason `wahoo_plan_unsupported`, German text naming the step); nothing is dropped silently. No Intervals.icu key and no activity record is involved.

Not mapped (plan format features this module never writes): `intensity_type` other than `active`, several targets per interval, ramps, repeats as nested blocks (the parser expands them to flat steps, at most 5000), zone targets, sports other than bike and run, other pace units. Which of these exist in the Wahoo format is **unverified** (PDF not checked).

### `intervals_wellness_mapping.py`

Status: Retired (stored-data replay only; no new data). No code fetches Intervals.icu any more (`backend/sync/intervals_ingest.py`: the ingest is removed and only the purge state helpers remain; the one-off purge is `backend/sync/intervals_purge.py`, #1728). The module is still called, on rows already stored, by: `intervals_ingest_plan` (`canonical_plans.py`; reached through `intervals_snapshot_ingest_plan` from `_ingest_work` in the canonical backfill, `backend/sync/canonical_backfill.py`, which reads stored `snapshots` rows), `reprojection_plan` for stored raw records of kind `wellness` and `athlete` (`canonical_backfill._reprojection_work`), and `project_intervals_snapshot` (`snapshot_projection.py`, whose only non-test caller `intervals_snapshot_coverage` in `canonical_coverage_store.py` has no caller in `backend/` or `server.py`). The purge deletes the stored snapshots, raw records and Intervals.icu observations, after which nothing reaches the mapper.
Mapper version: **12**
Inputs: wellness rows (`raw_provider_data.wellness`, snapshot `recent_wellness`, or one stored raw record of kind `wellness`) through `map_intervals_wellness(rows, retrieved_at)`; the athlete record (`raw_provider_data.athlete`, snapshot `athlete`, or the raw record of kind `athlete`, source record id `athlete`) through `map_intervals_athlete_thresholds(athlete, observed_on, retrieved_at)`.
Evidence: wellness row keys **observed** in `intervals_wellness_2026-11-03` unless marked documented; sport-settings and athlete keys documented only (`tests/test_intervals_wellness_mapping.py`, `tests/test_intervals_mapping_parity.py`, synthetic `tests/fixtures/providers/intervals/athlete.json`). Alias rules: for each field the first alias whose value is neither `None` nor `""` is used, even when invalid; a rejected value never falls back to a later alias (`_first_present`). Numbers follow `coerce_comma_decimal_number`. Every observation has `observed_at` = `None`, `provenance.provider` = `intervals`, `provenance.source_kind` = `provider_reported`, `provenance.recorded_by` = `unknown` (except the subjective ratings), `provenance.label` = "Intervals.icu", `provenance.retrieved_at` = the argument. `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`; `Observation` arguments set: `kind`, `value`, `observed_on`, `observed_at`, `provenance`, `sport`, and for derived form `method`, `method_version`, `input_fingerprint`. Zero means "not set" for `ftp`, `indoor_ftp`, `threshold_hr`, `max_hr`, `threshold_pace`, `zone2_pace`, `vo2max`, `eftp` (nothing emitted, no issue, the alias chain stops there).

Wellness rows. The row `id` is required: ISO `YYYY-MM-DD` with ASCII digits and a real date -> `observed_on` and `provenance.source_record_id`; missing -> `MISSING`, non-text -> `INVALID_TYPE`, other text -> `UNKNOWN_VALUE`, row dropped. `sport` is `None` for all of them.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `weight` | `weight` | kg, 20 to 400 | Observed key (null in the payload). Zero is out of range, not "unset". |
| `body_fat` | `bodyFat` -> `body_fat` -> `body_fat_pct` | %, 1 to 80 | `bodyFat` observed; the others documented. |
| `resting_hr` | `restingHR` -> `resting_hr` | bpm, 20 to 250 | `restingHR` observed. |
| `hrv_rmssd` | `hrv` -> `hrv_ms` | ms, 0 to 500 | `hrv` observed; the code treats it as RMSSD. |
| `hrv_sdnn` | `hrvSDNN` | ms, 0 to 500 | Observed key (null). |
| `sleep_duration` | `sleepSecs` -> `sleep_seconds` | s, 0 to 86,400 | `sleepSecs` observed. |
| `sleep_score` | `sleepScore` | score, 0 to 100 | Observed. |
| `readiness` | `readiness` -> `readinessScore` -> `readiness_score` -> `trainingReadiness` -> `training_readiness` | score, 0 to 100 | `readiness` observed (null); others documented. |
| `vo2max` | `vo2max` -> `vo2_max` | ml/kg/min, 5 to 120 | `vo2max` observed. |
| `ctl` | `ctl` -> `ctLoad` | load, 0 to 10,000 | `ctl` observed. See defect note on `ctLoad`. |
| `atl` | `atl` -> `atlLoad` | load, 0 to 10,000 | `atl` observed; `atlLoad` observed. |
| `form` (reported) | `tsb` -> `form` -> `freshness` | load, -10,000 to 10,000 | All three documented (none in the payload; `tsb` appears in the synthetic fixture). |
| `form` (derived) | `ctl`, `atl` of the same row | `round(CTL - ATL, 2)` using the mapped values | Only when no reported form key is present and both CTL and ATL were mapped. `provenance.source_kind` = `derived`, `method` = `FORM_METHOD` (`ctl_minus_atl`), `method_version` = `FORM_METHOD_VERSION` (1), `input_fingerprint` = `fingerprint_inputs({"ctl", "atl"})`. A present but rejected reported form gives an issue and no derivation. |
| `subjective_fatigue` | `fatigue` | rating 1 to 4 | Observed key (null). `provenance.recorded_by` = `manual`: the athlete's own rating entered in Intervals.icu, kept apart from local check-ins and Garmin stress. |
| `subjective_soreness` | `soreness` | rating 1 to 4 | Observed key (null); `recorded_by` `manual`. |
| `subjective_stress` | `stress` | rating 1 to 4 | Observed key (null); `recorded_by` `manual`. |
| `subjective_mood` | `mood` | rating 1 to 4 | Observed key (null); `recorded_by` `manual`. |
| `eftp` (with `sport`) | `sport_info[]` entry, else `sportInfo[]` (first non-empty key): `mmp_model.ftp` -> `mmp_model.eftp` -> `mmp_model.eFTP` (used when non-zero), else entry `eftp` -> `eFTP` | W, 0 to 2,500; zero unset | `sportInfo`, `type`, `eftp` observed; `mmp_model`, `sport_info` documented. The entry's sport comes from the `types` list if it is a list, else the texts of `type`, `sport`, `sport_type`, each classified by `classify_sport_text`; a text that classifies to `other` is skipped, and `other` is used only when no text names a known sport. Only the first entry of each sport is mapped. A non-list `sportInfo` or a non-mapping entry is an issue (`INVALID_TYPE`). |

The wellness row also feeds canonical sleep periods (`sleep_period_mapping.py` reads `sleepSecs` for Intervals.icu) through `_wellness_batch`, replayed by this module's version; it is described with `sleep_period_mapping.py`, not here.

Athlete record, per sport. `sportSettings` (else `sport_settings`, an empty list also falls back) must be a list (else issue on `sportSettings`, `INVALID_TYPE`). Each entry's sports are those its `types` list classifies to (OTHER skipped; OTHER only if no text names a known sport; a missing or empty `types` is an issue `MISSING`, a non-list `INVALID_TYPE`). Only the first entry of each sport is mapped. Values carry `sport` and are dated on the caller's `observed_on`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `ftp` (per sport) | entry `ftp` -> `indoor_ftp` | W, 0 to 2,500 | `indoor_ftp` is used only when `ftp` is absent or null. |
| `indoor_ftp` | entry `indoor_ftp` | W | Also emitted as its own kind. |
| `threshold_hr` | entry `lthr` | bpm | |
| `max_hr` | entry `max_hr` -> `maxHR` -> `maxHeartRate` -> `max_heartrate` | bpm | |
| `eftp` | entry `mmp_model.*` then `eftp` -> `eFTP` (as in `sportInfo`) | W | Stored with the sport; the observation key has the athlete series so it never replaces the wellness eFTP of the same day. |
| `vo2max` (`ride`) | entry `vo2max` -> `vo2_max` -> `cycling_vo2max` | ml/kg/min | Ride only. |
| `vo2max` (`run`) | entry `vo2max` -> `vo2_max` -> `running_vo2max` | ml/kg/min | Run only; other sports get no VO2max. |
| `threshold_pace` | entry `threshold_pace` (Run only) | m/s: a value below 20 is read as m/s, 20 or more as seconds per km and converted to `1000 / value`; bounds 0 to 15 m/s | |
| `zone2_pace` | entry `zone2_pace` -> `zone_2_pace` -> `z2_pace` -> `pace_zone2` -> `paceZone2` -> `zone2Pace` (Run only) | m/s, same conversion | |

Athlete record, athlete-wide (`sport` = `None`, read after the sport entries; a consumer applies the per-sport fallback itself):

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `weight` | `weight` | kg, 20 to 400 | |
| `threshold_hr` | `lthr` | bpm | Fallback for a sport without its own value. |
| `max_hr` | `max_hr` -> `maxHR` -> `maxHeartRate` -> `max_heartrate` | bpm | |
| `body_fat` | `bodyFat` -> `body_fat` | %, 1 to 80 | |
| `height` | `height_cm` -> `height` | cm, 30 to 300; a value from 1.2 to 2.5 is read as metres and becomes `round(value * 100, 1)` | |
| `w_prime` | `icu_w_prime` (constant `W_PRIME`) | J, 0 to 200,000 | Zero is not treated as unset here and is emitted as 0 J. |
| `vo2max` | `vo2max` -> `vo2_max` | ml/kg/min, 5 to 120 | |
| `vo2max` (Ride / Run, with `sport`) | `cycling_vo2max` / `running_vo2max` | ml/kg/min | Only when no `vo2max` of that sport was mapped from a sport setting. |
| `ftp` (Ride) | `icu_ftp` (constant `CONFIGURED_FTP`) | W | Only when no Ride `ftp` observation exists, also when a sport-setting FTP was rejected. |

`provenance.source_record_id` of athlete values is the athlete `id` only when it is text of at most 200 characters matching `[\w.-]+` (ASCII); otherwise `None`.

Not mapped. Wellness keys **observed** in `intervals_wellness_2026-11-03` and ignored without an issue: `rampRate`, `ctlLoad` (only `ctLoad` is an alias), `updated`, `menstrualPhase`, `menstrualPhasePredicted`, `kcalConsumed`, `sleepQuality`, `avgSleepingHR`, `motivation`, `injury`, `spO2`, `systolic`, `diastolic`, `hydration`, `hydrationVolume`, `baevskySI`, `bloodGlucose`, `lactate`, `abdomen`, `comments`, `steps`, `floorsClimbed`, `respiration`, `carbohydrates`, `protein`, `fatTotal`, `locked`, `tempWeight`, `tempRestingHR`; and inside each `sportInfo` entry `wPrime` and `pMax`. The payload is the only evidence for the list of wellness keys the API sends; the full OpenAPI schema was not checked, so keys it may define beyond these are **unverified**. Athlete and sport-setting keys seen in the synthetic fixture and ignored: athlete `name`, `sex`, `dob`; setting `id`, `warmup_time`, `cooldown_time`; the zone lists `hr_zones`, `power_zones`, `pace_zones` are not read here (see `intervals_zone_mapping.py`). Warm-up and cool-down times are deliberately not read. Athlete-wide VO2max, body fat and activity-derived max HR beyond the rows above are not mapped. Known deviations from the legacy readers are pinned in `tests/test_intervals_mapping_parity.py` (for example a zero athlete-wide `lthr` is unset here, a rejected `tsb` does not fall back to CTL minus ATL).

### `intervals_zone_mapping.py`

Status: Retired (stored-data replay only; no new data). Same callers as `intervals_wellness_mapping.py`: `_athlete_batch` (`canonical_plans.py`) from `intervals_ingest_plan` and from `reprojection_plan` for the stored `athlete` raw record. `type_sports` is also imported by `intervals_wellness_mapping.py` to classify type texts. The configurations it wrote stay readable: `CanonicalTableReader.zone_configurations` returns them next to local ones.
Mapper version: Replayed by `intervals_wellness_mapping.py` v12 (`tests/test_mapper_version_guard.py` `REPLAYED_BY`).
Inputs: the stored Intervals.icu athlete record, `map_intervals_zone_configurations(athlete, source_record_id, retrieved_at)`, called with `source_record_id` = `athlete`. Returns a tuple, no issues.
Evidence: documented only (`tests/test_intervals_zone_mapping.py`, `tests/test_plan_zone_canonical_parity.py`, synthetic athlete fixture).

Each sport takes the first `sportSettings` (else `sport_settings`) entry whose `types` list contains a text that classifies to it (`_first_settings`, `type_sports`; OTHER is skipped, an entry can serve several sports). A zone list needs 3 to 7 numbers (ints or floats, not booleans or text), finite, positive and strictly ascending (`_zone_list`); anything else, or a configuration that fails `ZoneConfiguration` validation, is left out silently. Absolute limits are never derived from percentages. All configurations: `valid_from` = `None`, `valid_until` = `None`, `resting` = `None`, `model` unset (`None`), `provenance.provider` = `intervals`, `provenance.source_kind` = `provider_reported`, `provenance.source_record_id` = the argument, `provenance.recorded_by` = `unknown`, `provenance.retrieved_at` = the argument, `provenance.label` = "Intervals.icu" (`INTERVALS_LABEL`). `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`.

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `metric` = `heart_rate`, `limits` | entry `hr_zones` | bpm, each 20 to 250 | `percent_limits` and `percent_basis` are `None`. A top entry above 250 (an open-top marker) makes the whole configuration invalid and it is dropped. |
| `threshold` (heart rate) | `lthr` | bpm | Absent or non-positive -> `None`. A value outside 20 to 250 drops the configuration. |
| `maximum` (heart rate) | `max_hr` | bpm | Same rule. |
| `metric` = `power`, `percent_limits` | entry `power_zones` | percent of `ftp`, each 1 to 1,000 (an open-top marker such as 999 is kept) | `limits` is `None`; `percent_basis` = `threshold`. |
| `threshold` (power) | `ftp` | W, 1 to 5,000 | Absent or non-positive -> `None`; the configuration is still emitted. |
| `environment` = `indoor`, `threshold` | `indoor_ftp` | W | When `indoor_ftp` is a positive number, a second power configuration with the same percent limits and `environment` = `indoor` is emitted. The first has `environment` = `None`. |
| `metric` = `pace`, `percent_limits` | entry `pace_zones` | percent of the threshold speed, each 1 to 1,000 | `limits` is `None`; `percent_basis` = `threshold`. |
| `threshold` (pace) | `threshold_pace` | m/s: below 20 is m/s, 20 or more is seconds per km and becomes `1000 / value` (`_pace_speed`); bounds 0.1 to 100 | |
| `sport` | entry `types` | `classify_sport_text` per text; any sport except `other` | Every sport that a type text names gets configurations, also ones the editor does not offer. |
| `maximum`, `resting` (power, pace) | none | `None` | |

Downstream use: `effective_zone_configuration` ranks Intervals.icu configurations after local ones; `ZoneSettings.from_configurations` (`backend/activities/zone_settings.py`) takes only their limits and never their threshold (`_threshold`).

Not mapped: any `sportSettings` key besides `types`, `hr_zones`, `lthr`, `max_hr`, `power_zones`, `ftp`, `indoor_ftp`, `pace_zones`, `threshold_pace`. The synthetic fixture also shows `id`, `eftp`, `warmup_time`, `cooldown_time`; zone names or other zone-related keys of the live API are **unverified** (no sanitized payload). The `maximum` and `reserve` bases (`ZonePercentBasis`) are never produced by this module.

### `intervals_power_curve_mapping.py`

Status: Retired (stored-data replay only; no new data). The Intervals.icu power-curve reader no longer exists (`backend/providers/intervals_power.py` keeps only `POWER_CURVE_LABEL`, "kept for stored curves"). Callers: `_power_curve_batch` (`canonical_plans.py`), reached from `intervals_ingest_plan` (the snapshot key `cycling_power_profile`, `INTERVALS_POWER_CURVE_KEY`; the canonical backfill plans it only for the newest snapshot, `include_power_curve`) and from `reprojection_plan` for the stored raw record of kind `power_curve` (record id `power_curve`). The purge deletes those rows.
Mapper version: **1**
Inputs: the stored envelope `{status, start, end, synced_at, points}`; `map_intervals_power_curve(envelope, source_record_id, fetched_at, zone)` returns a `PowerCurveMapping` (`fetch`, `points`; `None` means keep what is stored).
Evidence: documented only (`tests/test_power_curve_canonical.py`; no sanitized payload).

All records have `provenance.provider` = `intervals`, `provenance.source_kind` = `provider_reported`, `provenance.source_record_id` = the argument, `provenance.recorded_by` = `unknown`, `provenance.label` = `POWER_CURVE_LABEL` ("Intervals.icu gemessene Leistungskurve"). `Provenance` arguments set: `provider`, `source_kind`, `source_record_id`, `recorded_by`, `retrieved_at`, `label`; the record fields are in the index tables below (`PowerCurveFetch`: `fetch_status`, `window_start`, `window_end`, `provenance`; `PowerCurvePoint`: `duration_s`, `watts`, `observed_on`, `provider_activity_id`, `provenance`).

| Canonical field | Provider key(s) | Unit / conversion | Notes |
|---|---|---|---|
| `fetch_status` (`PowerCurveFetch`) | envelope `status` | lowercase identifier `[a-z0-9][a-z0-9_.-]{0,63}`, kept as sent (`ok`, `insufficient_data`, `failed`) | Non-text status -> no fetch and nothing mapped. Text that is not a lowercase identifier fails validation -> no fetch. |
| `window_start`, `window_end` | envelope `start`, `end` | ISO date (`date.fromisoformat`) | Both must parse; `start` after `end` gives no window (both `None`). |
| `provenance.retrieved_at` (fetch) | envelope `synced_at` | `parse_provider_datetime(text, zone)`: naive text is athlete wall time | `None` when unusable. |
| `provenance.retrieved_at` (points) | envelope `synced_at`, else `fetched_at` | as above; fallback is the raw record's fetch time | |
| `duration_s` (`PowerCurvePoint`) | point `duration_seconds` | integer seconds, 1 to 86,400 | A float or boolean fails validation and the point is dropped. The first point of a duration wins; points are sorted by duration. |
| `watts` | point `watts` | W, 0 to 5,000 | |
| `observed_on` | point `date` | ISO date, must lie inside the window (inclusive) | Day of the best effort. |
| `provider_activity_id` | point `activity_id` | text, else `None` | Non-text or empty -> `None`. |
| (filter) | point `status` | only `ok` points are mapped | Other statuses are dropped. |

An envelope without a usable window or with a non-list `points` maps to the fetch only (`points` = `None`, stored best efforts kept). A non-mapping envelope maps to nothing.

Not mapped: any other envelope or point key. The module docstring refers to `backend.providers.intervals_power.cycling_power_points` and `IntervalsReader` as producers of the points; neither exists in this checkout, so the exact producer shape of a point (beyond the keys above) is **unverified**.

### `intervals_performance_fields.py`

Status: Retired (key constants for stored Intervals.icu payloads). The module defines no mapper and no `MAPPER_VERSION`. Constants are imported by the retired activity mappers (`intervals_activity_keys.py`, `intervals_activity_detail_mapping.py`, `intervals_activity_detail_projection.py`), by `intervals_wellness_mapping.py` (`CONFIGURED_FTP`, `W_PRIME`), by `activities/detail_store.py` (`ZONE_TIMES`, `HEART_RATE_ZONE_TIMES`) and by `intervals_workouts.py` (`INTENSITY`, `TRAINING_LOAD`, for the outbound workout export). `TRAINING_LOAD`, `CONFIGURED_FTP` and `W_PRIME` are also keys of the app's own performance JSON and must not change.
Evidence: documented only.

| Constant | Value | Read by |
|---|---|---|
| `TRAINING_LOAD` | `icu_training_load` | activity keys, detail mapping and projection, `intervals_workouts.py` |
| `CONFIGURED_FTP` | `icu_ftp` | `intervals_wellness_mapping.py` (athlete-level Ride `ftp`), activity keys, detail projection |
| `W_PRIME` | `icu_w_prime` | `intervals_wellness_mapping.py` (`w_prime`) |
| `INTENSITY` | `icu_intensity` | activity keys, detail mapping and projection, `intervals_workouts.py` |
| `WEIGHTED_AVG_WATTS` | `icu_weighted_avg_watts` | activity keys, detail mapping and projection |
| `WEIGHTED_AVG_SPEED` | `icu_weighted_avg_speed` | activity keys, detail projection |
| `PACE` | `icu_pace` | activity keys, detail projection |
| `RPE` | `icu_rpe` | activity keys, detail projection |
| `ZONE_TIMES` | `icu_zone_times` | detail mapping and projection, `detail_store.py` |
| `HEART_RATE_ZONE_TIMES` | `icu_hr_zone_times` | detail mapping and projection, `detail_store.py` |
| `TRAINING_LOAD_ALIASES` | `(icu_training_load,)` | no importer found in `backend/` or `server.py` |
| `INTENSITY_ALIASES` | `(icu_intensity,)` | no importer found |
| `RPE_ALIASES` | `(icu_rpe, rpe)` | no importer found |
| `PACE_ALIASES` | `(icu_pace, average_pace, pace)` | no importer found |
| `SPEED_ALIASES` | `(average_speed, icu_weighted_avg_speed)` | no importer found |
| `WEIGHTED_POWER_ALIASES` | `(icu_weighted_avg_watts, weighted_average_watts, normalized_power)` | no importer found |
| `VO2_MAX_ALIASES` | `(vo2max, vo2_max, vO2MaxValue, vo2MaxValue, icu_vo2max)` | no importer found |
| `CONFIGURED_FTP_ALIASES` | `(icu_ftp,)` | no importer found |
| `ESTIMATED_FTP_ALIASES` | `(icu_eftp, eftp, eFTP)` | no importer found |
| `DIRECT_ESTIMATED_FTP_ALIASES` | `(eftp, eFTP, icu_eftp)` | no importer found |

Not mapped: the module emits no canonical field. Activity-level keys are mapped in the Intervals activity sections; the alias tuples above are unused leftovers, so the lookup orders the activity mappers use are the ones in their own sections.

### Canonical fields not produced by this scope

- `ZoneConfiguration.resting` and `ZoneConfiguration.model`: no producer sets them (`intervals_zone_mapping.py` passes `resting=None` and omits `model`; the local producer passes `resting=None`). `ZonePercentBasis` `maximum` and `reserve` are never produced. Garmin and Wahoo produce no zone configurations.
- `ZoneConfiguration.valid_until` is `None` for every producer; a local configuration ends by replacement or retirement, not by an end date.
- `PowerCurve` is never built by a mapper; only `CanonicalTableReader.power_curve` assembles it from stored rows. `PowerCurvePoint` and `PowerCurveFetch` have no producer other than `intervals_power_curve_mapping.py` (and the table reader that rebuilds them); no live provider produces a power curve.
- `MetricKind` `ctl`, `atl`, `form`, `eftp`, `subjective_*`, `w_prime`, `height`, `zone2_pace`, `indoor_ftp` are produced only by `intervals_wellness_mapping.py`, i.e. only from stored Intervals.icu rows; no live provider produces them.

## Canonical record `ZoneConfiguration`

Defined in `backend/canonical/domain_records.py`. Zone limits of one metric for one sport, as a provider reported them or as the athlete set them locally. Frozen dataclass, validated in `__post_init__`. Producers: I = `intervals_zone_mapping.py` (retired), L = local (`local_configuration` in `backend/athlete/zones.py`, saved by `ZoneConfigurationService.save`). `CanonicalTableReader._zone_configuration` rebuilds the record from the `zone_configurations` table. Table key (`zone_configuration_key`): `provider|metric|sport|environment|valid_from`, empty for `NULL`; a local key starts with `|`.

| Field | Type / unit / rule | Emitted by | Notes |
|---|---|---|---|
| `metric` | `ZoneConfigurationMetric`: `heart_rate`, `power`, `pace` | I, L | I emits all three; L accepts all three. |
| `sport` | `Sport` or `None` | I, L | L accepts only `ride`, `run`, `swim` (`EDITABLE_SPORTS`). I: any sport a type text names except `other`. |
| `environment` | `Environment` or `None` | I, L | Only `indoor` is produced (I from `indoor_ftp`, L from the request); `None` applies to every session. |
| `valid_from` | date or `None` | L | I leaves it `None`. L reads the optional ISO day `valid_from` of the request. |
| `valid_until` | date or `None`, not before `valid_from` | not produced | Always `None`. |
| `threshold` | number or `None`: bpm 20 to 250, W 1 to 5,000, m/s 0.1 to 100 | I, L | I: `lthr`, `ftp` / `indoor_ftp`, `threshold_pace`. L: `threshold` of the request, required for `heart_rate` and `power`. |
| `maximum` | number or `None`, same bounds | I, L | Heart rate only in practice: I `max_hr`, L `maximum` kept only for `heart_rate`. |
| `resting` | number or `None`; heart rate zones only | not produced | Always `None`. |
| `limits` | tuple of 1 to 19 strictly ascending upper limits in the metric's unit (bpm, W, m/s) or `None` | I (heart rate), L | I: `hr_zones`. L: request `limits` (3 to 7 values). |
| `percent_limits` | tuple of 1 to 19 strictly ascending percents, 1 to 1,000, or `None` | I (power, pace), L | I: `power_zones`, `pace_zones`. L: request `percent_limits` (3 to 7 values). Exactly one of `limits` and `percent_limits` is set by both producers; the record needs at least one. |
| `percent_basis` | `ZonePercentBasis` or `None`; set together with `percent_limits` | I, L | Both produce `threshold` only. `reserve` is valid for heart rate only but never produced. |
| `provenance` | `Provenance`, not derived | I, L | I: provider `intervals`, `provider_reported`, `recorded_by` `unknown`, label "Intervals.icu". L: provider `None`, `source_kind` `athlete_entered`, `source_record_id` `None`, `recorded_by` `manual`, `retrieved_at` `None`, label "Lokal". |
| `model` | lowercase identifier or `None` | not produced | Stored in the row's `details` under `model`; no producer sets it. |

Local producer. `local_configuration(payload)` validates one API request or a restored history row: `sport` and `metric` enum values, `environment` null/absent or `indoor` (an empty string is rejected), exactly one of `limits` (3 to 7 numbers, absolute) and `percent_limits` (3 to 7 numbers), `threshold` (required for `heart_rate` and `power`), `maximum` (kept for `heart_rate`), optional `valid_from`. `valid_until` and `resting` are always `None`. `ZoneConfigurationService.save` writes it with `upsert_local_zone_configuration`: the same key replaces the active row, and saving unchanged values still re-dates the row so a re-confirmed threshold counts as current. It records a change-history entry (create or update) with a receipt and undo (`restore_in_transaction`, which keeps the replaced save date). `remove` needs `confirmed: true`, retires the row (`state` retired, the row stays) and records a delete entry. A provider refresh replaces only rows of its own source record and never touches local rows. Only active rows are read back.

`effective_zone_configuration(configurations, metric, sport, indoor, day)` (`backend/activities/zone_settings.py`) picks the one configuration that applies: it keeps those with the same `metric` and `sport`, whose `environment` is `None` (or also `indoor`, when the session is indoor or virtual) and that are valid on `day` (`valid_from` <= `day` <= `valid_until`, an open end counts as valid; `day` `None` skips the test). Order of preference: local before providers (providers rank Garmin, Wahoo, Intervals.icu), then an `indoor` configuration before an environment-free one, then the latest `valid_from` (a missing one is the oldest). It returns `None` when nothing applies.

## Canonical record `PowerCurvePoint`

Defined in `backend/canonical/domain_records.py`. The best mean power over one duration from a provider's power curve. Produced by `intervals_power_curve_mapping.py` (retired); rebuilt from the `power_curve` table by `CanonicalTableReader._power_curve_point`.

| Field | Type / unit / rule | Emitted by | Notes |
|---|---|---|---|
| `duration_s` | integer seconds, 1 to 86,400 (not boolean) | `intervals_power_curve_mapping.py` | Point `duration_seconds`. |
| `watts` | W, 0 to 5,000 | `intervals_power_curve_mapping.py` | Point `watts`. |
| `observed_on` | date | `intervals_power_curve_mapping.py` | Point `date`, inside the fetch window. |
| `provider_activity_id` | text or `None` | `intervals_power_curve_mapping.py` | Point `activity_id`. |
| `provenance` | `Provenance` with provider and source record id, not derived | `intervals_power_curve_mapping.py` | `retrieved_at` = envelope `synced_at`, else the raw record's fetch time. |

## Canonical record `PowerCurveFetch`

Defined in `backend/canonical/domain_records.py`. The outcome of a provider's latest power curve fetch, once per source record. Produced by `intervals_power_curve_mapping.py` (retired); rebuilt by `CanonicalTableReader._power_curve_fetch`.

| Field | Type / unit / rule | Emitted by | Notes |
|---|---|---|---|
| `fetch_status` | lowercase identifier, max 64 characters | `intervals_power_curve_mapping.py` | Envelope `status` (`ok`, `insufficient_data`, `failed`). |
| `window_start` | date or `None`; set together with `window_end` | `intervals_power_curve_mapping.py` | Envelope `start`; `None` when the window is unusable. |
| `window_end` | date or `None` | `intervals_power_curve_mapping.py` | Envelope `end`; not before `window_start`. |
| `provenance` | `Provenance` with provider and source record id, not derived | `intervals_power_curve_mapping.py` | `retrieved_at` = envelope `synced_at`, else `None`. |

## Canonical record `PowerCurve`

Defined in `backend/canonical/domain_records.py`. The stored power curve as read back: each provider's latest fetch and its best efforts. Assembled only by `CanonicalTableReader.power_curve`; no mapper constructs it (`EMPTY_POWER_CURVE` is the empty value).

| Field | Type / unit / rule | Emitted by | Notes |
|---|---|---|---|
| `fetches` | tuple of `PowerCurveFetch`, default empty | not produced by a mapper | Active `power_curve_fetch` rows. |
| `points` | tuple of `PowerCurvePoint`, default empty | not produced by a mapper | Active `power_curve` rows. `is_empty` is true when both tuples are empty. |

## Locally derived records

No provider payload feeds these modules. They read the canonical session summary (`activity_summaries` over the stored `ActivityRecord` rows, provider precedence as in "Activity summary resolution"), stored thresholds, stored streams and Garmin Body Battery levels, and write `Observation` rows with `provenance.provider` = none, `provenance.source_kind` = `derived`. Evidence: derived from stored canonical data; no payload file applies. Common envelope of the per-session kinds (`local_load.py`, `session_metrics.py`):

| `Observation` argument | Value |
|---|---|
| `kind` | `MetricKind` per table below |
| `value` | `MetricValue(round(x, 4), kind.unit)`; the unit comes from `kind.unit` |
| `observed_on` | `summary_local_date(summary)`: the session's athlete-local day (summary `started_at_local`, first 10 characters) |
| `observed_at` | summary `started_at` (aware instant, offset as stored) |
| `provenance` | `Provenance(provider=None, source_kind=SourceKind.DERIVED, source_record_id=<canonical session id>, recorded_by=<summary recorded_by, else unknown>, retrieved_at=None, label="derived")` |
| `sport` | summary `sport` |
| `method`, `method_version`, `input_fingerprint` | module constants below; the fingerprint is a SHA-256 hex (`fingerprint_inputs`) |
| `aggregation`, `period` | not set (none) |

Stored extras: row column `mapper_version` = the module's method version, column `owner_record_id` = the session id, and `details.derivation` = the module's derivation object (see "Observation storage and lifecycle"). Natural key: `|<kind>|<sport>|session:<session id>|<started_at>`. The bounds of `Observation` apply (`validation.py`); a session whose value (or any of its values in M8) is out of bounds gets no row at all for that pass.

`stream_zones.py` (the other locally derived module) is documented in the activity detail section ("Locally derived detail"), not here.

### `local_load.py`

Status: Live. `LocalLoadStage` is a follow-up stage of the canonical backfill worker (`build_canonical_backfill` in `canonical_backfill_assembly.py`), run first after the backfill on every pass; `refresh_after_job` requests a pass after a completed sync job of provider `garmin` or `wahoo` (`LOAD_INPUT_PROVIDERS`), and a zone-configuration save, removal or undo requests one too.
Method: `METHOD_ID` = `local-tss-load`, `METHOD_VERSION` = **5** (`local_tss.py`; `CARD` = `M6`; card `docs/performance-methods/m6-local-tss-load.md`). The numbers below are the code's.
Inputs: per session the merged summary (`normalized_power`, `avg_hr`, `grade_adjusted_speed_mps`, `avg_speed_mps`, `moving_duration_s` else `elapsed_duration_s` via `summary_duration_s`, `sport`, `environment`, `id`, `started_at`, `recorded_by`); thresholds at the session day (`DatedThresholds`); resting heart rate observations; the profile sex (`athlete_sex`); the stored per-session heart-rate histogram (`stored_heart_rate_histogram`, analysis row `hr_histogram`, read only for sessions that reach the heart-rate branch); local session feedback and the Garmin RPE for strength (`feedback_by_session`, `session_load` of `session_rpe_load.py`). A provider load or intensity (Garmin `activityTrainingLoad`, Wahoo TSS, Intervals.icu) is never an input.

| Canonical field | Derivation / formula | Unit | Notes |
|---|---|---|---|
| `session_load` | One value per session from the first branch that succeeds: power, pace, heart rate (not strength), or session RPE (strength only). Branch formulas below. Rounded to 4 decimals. | `load` (TSS scale; 60 min at threshold = 100); bounds 0..10,000 | `kind` = `session_load`, `method` = `local-tss-load`, `method_version` = 5, `aggregation` none, `period` none. |
| `intensity_factor` | Power branch only: `NP / FTP * 100`. | `%` of FTP; bounds 0..1,000; the branch rejects a factor above `MAX_INTENSITY_FACTOR` 2.0 (reason `implausible_intensity`), so a stored value is at most 200 % | Same envelope. No other branch writes it. |

Branches (`session_local_load`):

| Branch (`details.branch`) | Applies to | Formula | Reasons it yields none |
|---|---|---|---|
| `power` | `ride`, `run` with `normalized_power` > 0 | `IF = NP / FTP`; `load = hours * IF^2 * 100`; hours = `summary_duration_s / 3600` | `no_ftp`, `implausible_intensity` (IF > 2.0) |
| `pace` | `run` with `grade_adjusted_speed_mps`, else `avg_speed_mps`, > 0 (`pace_basis` `grade_adjusted_speed` / `average_speed`) | `IF = v / threshold_pace`; `load = hours * IF^2 * 100`; no `intensity_factor` row | `no_threshold_pace`, `implausible_intensity` |
| `heart_rate` | every other sport incl. `walk`, `hike`, `swim`, `row`, `nordic_ski`, `other`, and `ride`/`run` that fell through; needs `avg_hr` > 0 | Banister TRIMP: `TRIMP = min * HRr * a * exp(b * HRr)`, `HRr = (HR - rest) / (max - rest)`; `(a, b)` = (0.64, 1.92) male, (0.86, 1.67) female (`TRIMP_CONSTANTS`); `load = TRIMP_session / TRIMP(60 min at threshold HRr) * 100`. `hr_basis` `distribution`: TRIMP summed over the stored histogram (per integer bpm, `HRr` clamped to 0..1), scaled by `duration / covered`, used when the histogram covers at least `HR_COVERAGE_MIN` 0.8 of the duration and its summed TRIMP is positive; else `average`: `HRr` from `avg_hr` must be in (0, 1] | `no_resting_hr`, `no_threshold_hr`, `no_max_hr`, `inconsistent_heart_rate_thresholds` (needs rest < threshold < max), `heart_rate_outside_reserve` |
| `session_rpe` | `strength` only (`SESSION_RPE_SPORTS`) | `load = AU * tss_per_au`; `AU = elapsed minutes * RPE` (card M1); no thresholds, no `intensity_factor` | `no_rating` (and M1 reasons `conflicting_provider_ratings`, `no_elapsed_duration`, `invalid_duration`), `not_calibrated`; RPE 0 gives load 0 |

- `Observation` arguments: `kind` (`session_load` / `intensity_factor`), `value`, `observed_on`, `observed_at`, `sport`, `method`, `method_version`, `input_fingerprint`, `provenance` with `provider` none, `source_kind` `derived`, `source_record_id` (session id), `recorded_by` (summary `recorded_by`; `unknown` when it is not a `RecordingOrigin`), `retrieved_at` none, `label` `derived` (`DERIVED_LABEL`). The heart-rate branch also reads `resting_hr` observations (`MetricKind.RESTING_HR`, key `resting_hr` in the thresholds) for the resting heart rate, Garmin before Wahoo.
- No-load sports (`NO_TSS_SPORTS`): `yoga`, `alpine_ski` (`sport_without_load`). Other reasons: `no_duration`, `no_inputs`, `no_date`, `invalid_value` (value outside the canonical bounds). A branch with its input but no valid threshold falls through to the next; the first reason is kept if none succeeds. Sessions without a value keep no row and have an earlier row retired.
- Sex: profile `sex` `male`/`female`; unset takes the male constants and sets `inputs.sex_assumed` (served as the label `SEX_ASSUMED_LABEL`).
- Strength calibration (`RpeCalibrations`): `tss_per_au` is the median of `TSS / (duration minutes * RPE)` over rated `ride`/`run` sessions with a local load, in the 365 days up to and including the session day (`CALIBRATION_WINDOW_DAYS`), RPE within 1 of the strength RPE, else within 2 (`CALIBRATION_RPE_BANDS`), from at least 20 pairs (`CALIBRATION_MIN_PAIRS`). A pair needs RPE > 0, a local or Garmin rating scale (an Intervals.icu rating never counts), and a load at most `MAX_ACTIVITY_LOAD`. The derivation keeps the factor, pair count, window, RPE band, pairs by source and a per-RPE table (RPE 1..10, factor from at least 20 pairs of the ±1 band).
- Thresholds on the session day (`DatedThresholds.for_session`): FTP (`ride`/`run`), threshold pace (`run`), threshold HR and max HR (sport `ride` for rides, `run` for every other sport), resting HR. FTP, pace and HR thresholds: the athlete-confirmed local zone configuration in effect that day, the newest Garmin or Wahoo observation on or before the day, resolved by the current-threshold source policy (`resolve_current_thresholds`); Intervals.icu observations are dropped. An indoor or virtual ride reads the local indoor FTP (`indoor_ftp`, source `local_indoor`) when an indoor power configuration with a threshold exists. Resting HR: newest observation within the 7 days up to the day (`RESTING_HR_LOOKBACK_DAYS`), Garmin before Wahoo.
- Stand-in: a key with no value on the day takes the earliest later value only if observed at most 90 days after the day (`LATER_STAND_IN_MAX_DAYS`), marked `after_session` (derivation `threshold_after_session`); otherwise the branch has no threshold.
- Fingerprint: `fingerprint_inputs` of `method`, `method_version`, `branch`, `inputs`, `thresholds` (each: `value`, `source` `local` / `local_indoor` / provider id, `observed_on`, `after_session`) and `calibration`. A row whose fingerprint (and every other column) is unchanged is not rewritten. `details.derivation`: `branch`, `card`, `inputs`, `thresholds`, optional `calibration`, `threshold_after_session`. Inputs per branch: `sport`, `duration_s`, plus `normalized_power` (power), `speed_mps` and `pace_basis` (pace), `avg_hr`, `sex`, `sex_assumed` (only when the profile sex is unset), `hr_basis`, `hr_coverage` and `hr_histogram_sha256` (both only when a stored histogram exists) (heart rate), `session_rpe_au`, `rpe`, `rpe_scale` (strength).
- Owner: the canonical session id (`owner_record_id`); `canonical_store.retire_derived_observations` retires every row of the method that the pass did not write, so a deleted or merged session, or a session that lost its value, retires its rows. Reads: `stored_local_loads` (per session), `daily_local_loads` (per local day, live sessions only), `with_local_loads` (puts `training_load`, `intensity` on the served summaries with source label `derived`; the provider values stay under `provider_training_load`, `provider_load_model`, `provider_intensity`).

Not mapped: provider TSS/intensity/load values (`LoadModel` provider loads are only cross-check data), swim/row-specific loads, any per-sport intensity factor besides power, Intervals.icu thresholds.

### `session_metrics.py`

Status: Live. `SessionMetricsStage` (`backend/sync/session_metrics.py`) is a follow-up stage of the canonical backfill worker, after `local_load`; the arithmetic is in `backend/performance/session_metrics.py`.
Method: `METHOD_ID` = `local-session-metrics`, `METHOD_VERSION` = **3**, `CARD` = `M8` (card `docs/performance-methods/m8-local-session-metrics.md`). Decoupling uses `session_analysis.METHOD` = `time-weighted-session-analysis-v2`, which is part of the fingerprint.
Inputs: sessions with sport `ride` or `run` only (`METRIC_SPORTS`, `wants_metrics`); the summary values `avg_hr`, `avg_power`, `normalized_power`, `grade_adjusted_speed_mps`, `avg_speed_mps`, `energy_kj`, `moving_duration_s`, `elapsed_duration_s`; and, where stored, the merged full-resolution stream sets (`time`, `watts`, `heartrate`, speed, grade/altitude) of the session's Garmin, Wahoo and local records. Intervals.icu streams and downsampled sets are never read; missing streams are not fetched here. Provider values of these metrics (Intervals.icu `icu_efficiency_factor`, `icu_variability_index`, `decoupling`, `icu_joules`) are never used.

| Canonical field | Derivation / formula | Unit | Notes |
|---|---|---|---|
| `efficiency_factor` | needs `avg_hr` in 30..240 (`HEART_RATE_RANGE`). Ride: `normalized_power / avg_hr` (needs `normalized_power` > 0). Run: `speed * 60 / avg_hr` with `speed` = `grade_adjusted_speed_mps`, else `avg_speed_mps`, > 0 | ride W/bpm, run (m/min)/bpm; `Observation` unit `ratio`; bounds 0..20 | `details.basis` `normalized_power` (`EF_POWER_BASIS`), `grade_adjusted_speed` (`EF_GAP_BASIS`) or `average_speed` (`EF_SPEED_BASIS`); `details.unit` names the unit. Uses the summary NP, not recomputed from streams. |
| `variability_index` | `normalized_power / avg_power`, `ride` only, both > 0; dropped when outside 0.5..5.0 (`VARIABILITY_BOUNDS`) | `ratio`; bounds 0..10 | `details` empty. |
| `mechanical_work` | `ride` or `run`. Device total `energy_kj` > 0 (`basis` `device_total`), else the power stream: `sum(P_i * dt_i) / 1000` over consecutive `time` samples, skipping `dt` <= 0 or > `MAX_SAMPLE_GAP_S` 5 s and a missing or negative `watts`; needs `len(time)` >= 2, equal `watts` length, coverage `sum(dt) / duration` >= `MIN_WORK_COVERAGE` 0.85 (duration = `summary_duration_s`) and a positive sum (`basis` `power_stream`, `coverage` rounded to 3 decimals, capped at 1) | `kJ` (`JOULES_PER_KJ` 1000); bounds up to 1,000,000 | For `run` the derivation adds `power_model` = `running_power_model` (`RUN_POWER_MODEL`): Garmin's running-power model, not a measured force. `energy_kj` is mapped by the Wahoo activity mapper only (Garmin sets `energy_kcal`, which is not used here). |
| `aerobic_decoupling` | `aerobic_analysis` on the merged streams: `100 * (EF1 - EF2) / EF1`, `EF_h` = time-weighted mean non-zero output / mean HR of half `h`. Output: `watts` for rides, `velocity_smooth` for road runs (trail runs excluded; outdoor runs use the Minetti 2002 grade-adjusted speed per sample, needing a grade or altitude plus distance stream; indoor/virtual runs stay flat). Starts 600 s after the first sample, split at the midpoint of the remainder | `%`; bounds -100..100; positive = less output per heartbeat in the second half | Eligibility (else no row): `status` `ok`, recording >= 1800 s, >= 85 % paired output and HR time (HR 30..240, gaps > 5 s and stops excluded, output > 0) in each half, output coefficient of variation <= 15 % per half, half means within 10 %. `details`: `sensor` (`watts`, `velocity_smooth` or `grade_adjusted_speed`), `unit` (`W/bpm` or `(m/s)/bpm`), `steady_output_per_hr` (both halves: sum of mean outputs / sum of mean HRs), `halves[]` (`measured_seconds`, `mean_output`, `mean_hr`, `output_per_hr`), `long_session` (end - start >= 5400 s). Not the session EF (that uses NP / Garmin's grade-adjusted speed). |

- `Observation` arguments: `kind` (per row above), `value`, `observed_on`, `observed_at`, `sport`, `method`, `method_version`, `input_fingerprint`, `provenance` with `provider` none, `source_kind` `derived`, `source_record_id` (session id), `recorded_by` (summary `recorded_by`; `unknown` when it is not a `RecordingOrigin`), `retrieved_at` none, `label` `derived`. The stage skips stream sets of provider `intervals`.
- Envelope as above with `method` = `local-session-metrics`, `method_version` = 3. A session gets only the kinds that pass their rules; a session without any value has no row and is never zero. Sessions without full-resolution streams get EF, VI and a device work total only.
- Fingerprint (`metrics_fingerprint`, computed before any stream is decoded): `fingerprint_inputs` of `method`, `method_version`, `analysis_method`, the summary inputs (`started_at`, `local_offset_minutes`, `recorded_by`, `sport`, `environment`, `terrain`, `assist`, `moving_duration_s`, `elapsed_duration_s`, `avg_hr`, `avg_power`, `normalized_power`, `grade_adjusted_speed_mps`, `avg_speed_mps`, `energy_kj`), `local_date`, the sorted content hashes of the stream sets, and the session members in merge order (provider, activity id, recording origin, device type). All kinds of one session share the fingerprint.
- Recompute: a changed fingerprint recomputes the session, at most `DEFAULT_BATCH_SIZE` 100 sessions per transaction; an unchanged session is neither decoded nor written; a computed session with no value keeps its fingerprint in the stage state (`empty`) so it is not decoded again. Rows not written or kept (sessions gone, a metric that no longer passes) are retired by `retire_derived_observations`. Owner: the session id.

Not mapped: calories (device `energy_kcal`, a separate summary value), EF/VI of other sports, trend or comparability across sessions, provider EF/VI/decoupling/joules.

### `morning_battery_service.py`

Status: Live. `MorningBatteryStore.persist` runs inside the morning Body Battery refresh (`MorningBodyBatteryService`, composed in `server.py` `morning_body_battery_service` with a `CanonicalTableReader`; the first refresh each day after 05:00 local time, or an explicit check-in date). Without a canonical reader `persist` stores no observation; production always passes one.
Method: `METHOD_ID` = `morning_body_battery`, `METHOD_VERSION` = **1** (the module's constants; column `mapper_version` = 1). `_DERIVED_LABEL` = "Garmin Connect (abgeleitet)".
Inputs: the Garmin `NIGHT` sleep period of the check-in date and the Garmin `BODY_BATTERY` level observations (`canonical_morning_record`, see `morning_battery.py` below), read back inside the same unit of work that stored the refreshed `sleep` and `body_battery` sections.

| Canonical field | Derivation / formula | Unit | Notes |
|---|---|---|---|
| `body_battery_before_sleep` | Record key `before_sleep`: the latest Garmin Body Battery level with `sleep_start - 4 h <= observed_at <= sleep_start` | `score`, whole number 0..100 | `Observation` arguments as in the table below. |
| `morning_body_battery` | Record key `morning`: the earliest Garmin level with `sleep_end <= observed_at <= min(attempt time, sleep_end + 1 h)` | `score`, whole number 0..100 | Needs the attempt time to be after the wake-up; later refreshes of the same night can pick an earlier or different sample. |

Observation arguments (`_store_values`): `kind` as above; `value` = `MetricValue(float(sample value), "score")` (the level was rounded to an integer when the sample was read); `observed_on` = the check-in date (`sleep_date`, the wake-up day, not the sample's date); `observed_at` = the sample instant (aware, as stored); `sport` none; `method` = `morning_body_battery`; `method_version` = 1; `input_fingerprint` = `fingerprint_inputs` of the sample (`observed_at`, `value`) plus `sleep_start_at` and `sleep_end_at`; `aggregation` and `period` not set (none; the level is a point sample, the night window lives in the derivation). `Provenance(provider=None, source_kind=SourceKind.DERIVED, source_record_id="night:<check-in date>", recorded_by=RecordingOrigin.GARMIN, retrieved_at=None, label="Garmin Connect (abgeleitet)")`. `details.derivation` = `sleep_start_at`, `sleep_end_at` (ISO instants, when present). Owner (`owner_record_id`): `night:<check-in date>` (`_night_owner`). Natural key: `|<kind>||<empty series>|<observed_at>` (these kinds are not in the `session:` series), so another sample time is another row.
- Provenance arguments: `provider` none, `source_kind` `derived`, `source_record_id` `night:<date>`, `recorded_by` `garmin`, `retrieved_at` none, `label` as above; `provenance` is the keyword that carries them.
- Lifecycle: per refresh the two present values are upserted and `retire_derived_observations(owner=night)` retires the night's other rows; a refresh without a sample (or a failed refresh, which stores an empty record) therefore retires the night's earlier values. The record is `ready` only when both values exist; `status` `not_available_today` otherwise. `MorningBatteryStore.current_in` serves the record from the view bookkeeping plus the active rows (`round(row value)`), falling back to inline values only for records stored before #1686.
- Time handling: sleep bounds are aware instants (UTC); the check-in date is the athlete-local calendar date passed by the caller; windows are inclusive.

Not mapped: Body Battery charged/drained totals and stress (stored by `garmin_health_mapping.py`), naps, the sleep stages.

### `morning_battery.py`

Status: Live, pure projection used by the service above; it constructs no canonical record (it returns the dict record `sleep_date`, `attempted_at`, `status`, `before_sleep`, `morning`, `source`, `sleep_start_at`, `sleep_end_at`). It names `SleepKind.NIGHT` (`night`) and `ProviderId.GARMIN` (`garmin`).
Mapper version: none (the method constants live in the service).

| Record field | Source | Notes |
|---|---|---|
| night window | `canonical_morning_record`: the `SleepPeriod`s with `kind` `night`, `provenance.provider` `garmin` and `provenance.source_record_id` = `sleep/<check-in date>` (`record_id("sleep", date)`); the latest `end` wins; `sleep_start` = `start`, `sleep_end` = `end` | Read for check-in -1 day .. +1 day. Without a night: no values. |
| samples | Garmin `BODY_BATTERY` observations with an `observed_at`, read for check-in -2 days .. +1 day | `observed_at` = instant, `value` = `round(level)`; sorted by instant. |
| `before_sleep`, `morning` | `morning_record`: windows as in the service table; `before` takes the last sample, `morning` the first | `ready` when both exist. |
| payload path | `morning_body_battery_record` parses fetched payloads (`bodyBatteryValuesArray` → `body_battery_values_array`, each `[timestamp, level]` with level 0..100, timestamp via `utc_timestamp`, deduplicated by instant; sleep bounds from `sleepStartTimestampGMT` → `sleepStartTimestamp` → `startTimestampGMT` and `sleepEndTimestampGMT` → `sleepEndTimestamp` → `endTimestampGMT`, `dailySleepDTO` first) | Documented only. With the canonical reader its `before_sleep`/`morning` are replaced by the canonical record before storing; only `attempted_at` and the retry bookkeeping (`attempts`, `cached_result`: 3 attempts, 15 minutes) survive. |

Not mapped: every other key of the sleep or Body Battery payload.

### `zones.py`

Status: Live. `backend/athlete/zones.py` is the only producer of athlete-confirmed `ZoneConfiguration` records (`local_configuration`, called by `ZoneConfigurationService.save`, and by `restore_in_transaction` for an undo). The `ZoneConfiguration` field index is documented with that record; this section covers how the local producer sets it. The row is written by `canonical_domain_store.upsert_local_zone_configuration` into `zone_configurations`.
Inputs: the athlete's save request (API/UI) or a restored change-history value; no provider payload.

| `ZoneConfiguration` field | Local value | Notes |
|---|---|---|
| `metric` | request `metric` as `ZoneConfigurationMetric`: `heart_rate`, `power` or `pace` | Invalid value: HTTP 400. |
| `sport` | request `sport`, one of `EDITABLE_SPORTS`: `ride`, `run`, `swim` | Other sports: HTTP 400. |
| `environment` | none, or `indoor` (`Environment.INDOOR`) | Any other value: HTTP 400. An indoor row applies to indoor and virtual sessions. |
| `valid_from` | request `valid_from` (ISO day) or none | Part of the key; none = valid from the beginning. |
| `valid_until` | always none | The local producer never closes a validity; a newer `valid_from` supersedes. |
| `threshold` | request `threshold` (number) | Required for `heart_rate` (LTHR, bpm) and `power` (FTP, W); optional for `pace` (m/s). Bounds: heart rate 20..250, power 1..5000, pace 0.1..100. |
| `maximum` | request `maximum`, `heart_rate` only (else none) | Maximum heart rate, bpm. |
| `resting` | always none | |
| `limits` | request `limits`: 3..7 ascending absolute upper zone limits, canonical units (bpm, W, m/s), open top zone included | Exactly one of `limits` / `percent_limits`. |
| `percent_limits` | request `percent_limits`: 3..7 ascending percent of the threshold, 1..1000 | |
| `percent_basis` | `ZonePercentBasis.THRESHOLD` (`threshold`) when `percent_limits` is given, else none | `maximum` and `reserve` are never set locally. |
| `provenance` | `Provenance(provider=None, source_kind=SourceKind.ATHLETE_ENTERED, source_record_id=None, recorded_by=RecordingOrigin.MANUAL, retrieved_at=None, label="Lokal")` | `LOCAL_LABEL`. |
| `model` | not set (none) | |

- `Provenance` arguments: `provider` none, `source_kind` `athlete_entered`, `source_record_id` none, `recorded_by` `manual`, `retrieved_at` none, `label` `Lokal`.
- Key (`zone_configuration_key`): `|<metric>|<sport>|<environment>|<valid_from>`; saving the same key replaces the row. Stored row: `provider` NULL, `mapper_version` NULL, `source_kind` `athlete_entered`, `recorded_by` `manual`, details only `previous_saved_at`.
- Dating: `updated_at` is the confirmation date; saving unchanged values renews it (the stale-threshold warning reads it), an undo (`renew=False`) restores the replaced date from `previous_saved_at`.
- Retirement: `ZoneConfigurationService.remove` (request needs `confirmed: true`) sets the row `retired` via `retire_local_zone_configuration` and keeps it; an undo of a create retires it, an undo of a delete or update rewrites it. Each change records a change-history row (`zone_configuration`). A provider refresh never touches local rows.
- Consumers: `effective_zone_configuration` / `ZoneSettings.from_configurations` (below) and `local_thresholds` (`current_thresholds.py`), which turns the effective local configuration into an in-memory (not stored) threshold `Observation` per key: `ftp` from `power` `threshold` (`ride`, `run`), `threshold_pace` from `pace` `threshold` (`run`), `threshold_hr` from `heart_rate` `threshold` and `max_hr` from `heart_rate` `maximum` (`ride`, `run`), with the configuration's own `provenance` (`athlete_entered`).

Not mapped: `ZoneBoundarySource` is not set here (it belongs to zone distributions, set to `profile` by `stream_zones.py`); `swim` configurations are stored but feed no threshold.

### `zone_settings.py`

Status: Live. Resolves and reads zone configurations; it constructs no `ZoneConfiguration` and no `Observation`. Local confirmed rows win over provider rows (`_source_rank`: local 0, then Garmin, Wahoo, Intervals.icu).
Inputs: stored `ZoneConfiguration` rows (`CanonicalTableReader.zone_configurations`) and the source-policy threshold winners.

| Result (`ZoneSettings` field) | Source | Notes |
|---|---|---|
| `ftp` | `power` configuration `threshold`, else the fallback winner (`MetricKind` `ftp`) | `_threshold`: a local value wins over the fallback, a provider configuration only fills an empty fallback; an Intervals.icu configuration (`ProviderId.INTERVALS`) never gives a threshold, only limits. |
| `lthr`, `max_hr` | `heart_rate` configuration `threshold` / `maximum`, else the fallback (`threshold_hr`, `max_hr`) | Same rule. |
| `threshold_pace` | fallback only (`threshold_pace`) | Pace configuration thresholds are not read here. |
| `power_limits`, `hr_limits`, `pace_limits` | `percent_limits` without the open top entry when `percent_basis` is `threshold`; else absolute `limits` divided by `threshold / 100` (needs a threshold); fewer than 2 limits = ignored | Defaults without a configuration: power 55/75/90/105/120/150, heart rate 68/83/94/105 (% of LTHR), pace 77.5/87.7/94.3/100/103.4/111.5 (% of threshold speed). |

- Enum members named: `Sport` (any), `Environment` `indoor`, `virtual` and the default `unknown`, `ZoneConfigurationMetric` `power`, `heart_rate`, `pace`, `ZonePercentBasis` `threshold`, `MetricKind` `ftp`, `threshold_hr`, `max_hr`, `threshold_pace`, `ProviderId` `intervals`.
- Selection (`effective_zone_configuration`): same `metric` and `sport`; `environment` none, or also `indoor` for `indoor`/`virtual` sessions (indoor preferred); `valid_from <= day <= valid_until` where set; lowest source rank, then indoor first, then the latest `valid_from`.
- `from_thresholds` builds a `ZoneSettings` from the first observation of `ftp`, `threshold_hr`, `max_hr` and `threshold_pace` for the sport.

Not mapped: `resting`, `model` and the `reserve`/`maximum` percent bases are not interpreted (a configuration with such a basis falls back to the default limits).

## Observation storage and lifecycle

Code: `backend/db/canonical_store.py`; replay in `backend/sync/canonical_backfill.py`; ingest in `backend/sync/canonical_ingest.py`.

- Table `observations`: one row per natural key `provider|metric|sport|series|(observed_at or observed_on)` (`observation_natural_key`); empty parts are empty strings. `series` is `athlete` (Intervals.icu athlete profile weight/eFTP/body fat/sport-less VO2max) or `session:<id>` (the six local per-session kinds `session_load`, `intensity_factor`, `efficiency_factor`, `variability_index`, `mechanical_work`, `aerobic_decoupling`: `SESSION_SERIES_KINDS`), else empty.
- Columns: `metric`, `value`, `unit`, `source_kind`, `recorded_by`, `provider` (NULL for derived), `source_record_id`, `sport`, `observed_on`, `observed_at`, `retrieved_at`, `label`, `mapper_version`, `method`, `aggregation`, `details` (JSON: `context`, `method_version`, `input_fingerprint`, `period`, `derivation`), `state`, `owner_record_id`.
- Write (`upsert_observation`): insert, or update by natural key when any column differs (then `UPDATED`; identical = `UNCHANGED`). The row always becomes `active` again. `fill_only` (history fills) never replaces an active row of another source record at the same or a newer `mapper_version`. `insert_observation_if_absent` never revives a retired row.
- State (`ProjectionState`): `active` / `retired`. Retiring never deletes: the row stays for history, backups and export, and a later write of the same key makes it `active` again.
- Owner: provider observations carry the raw `provider_records.source_record_id` that produced them in `owner_record_id`; local derived rows carry the session id or `night:<date>`.
- Provider retirement: each ingest plan first calls `retire_unemitted_observations(provider, scopes)`: every active row an owner holds on the days it covers (its own day plus the days it emits) whose key the plan no longer emits becomes `retired`, so a value the provider drops or empties disappears from reads without being deleted. A plan that lacks the owner's raw record (failed or skipped fetch) leaves its rows alone. Garmin raw records that leave the sync window retire their window rows (`garmin_store._retire_window_observations`).
- Replay (`canonical_backfill`): an active raw record whose `mapped_version` is below its mapper's current version (or every record after a time-zone change, `reproject_all`) is mapped again from the stored payload; the rows are rewritten in place with the new `mapper_version`, the owner's no-longer-emitted rows are retired, then `mapped_version` advances in the same transaction.
- Reads: provider reads (`current_observation_rows`) return only `active` rows at each provider's current mapper version (plus the pending older window while a replay runs) and never rows without a provider; local derived rows are read with `derived_observation_rows` (by `method`, optional owners) and `derived_daily_sums` (only owners that are live sessions).
- Local derived rows are not replayed from raw records: their stage recomputes on a changed `input_fingerprint` or `method_version` and calls `retire_derived_observations(method, keep, owner)`; `local_load` writes every session each pass, `session_metrics` only changed ones, `morning_battery_service` the one night of the refresh.

## Known gaps

State of the code when this map was written. The defects below are tracked in [#1826](https://github.com/Lukas-Beike/pacecraft/issues/1826); the other items are properties of the data.

### Data the app does not hold

- **No full-resolution Garmin or Wahoo streams yet.** Stream-based values (critical power/speed, running bests, aerobic decoupling, HR-distribution TRIMP) stay empty for sessions whose streams came from Intervals.icu; #1763 re-fetches them from Garmin and Wahoo.
- **No Wahoo payload has been captured.** Every Wahoo key in this map is "documented" (mapper docstrings, synthetic test rows, FIT SDK field definitions).
- **Garmin ride and strength list rows**, and every Garmin family without a file in the payload set (readiness, thresholds, FTP, race predictions, VO2max, heart-rate zones, endurance score, training status, gear), are documented through synthetic fixtures only.
- **Metric kinds nothing produces:** `training_load` (never), `run_threshold_power` (legacy: run FTP is `ftp` with sport `run`). Kinds stored for export that no reader uses: see the "Status" column of "Metric kinds".
- **`LapSource` value `splits`** has no producer; it is only ranked when sets are merged.

### Retired Intervals.icu mappers

`intervals_activity_mapping.py`, `intervals_activity_detail_mapping.py`, `intervals_activity_detail_projection.py`, `intervals_wellness_mapping.py`, `intervals_zone_mapping.py` and `intervals_power_curve_mapping.py` are kept only to read rows stored before the ingest was removed (#1728). They are removed after the purge has run in production. Their sections remain so that stored rows can still be explained.

### Findings still open

Found while writing the map and tracked in [#1826](https://github.com/Lukas-Beike/pacecraft/issues/1826); the Garmin defects that could be verified were fixed there (mapper versions 19 and 20).

1. **Gear key spelling.** `garmin_gear_mapping.py` reads `maximumMeters`; the SDK-shaped fixture `tests/fixtures/providers/garmin/gear.json` spells `maximumMeter`, and the installed SDK has no gear response model to decide. If the live key is `maximumMeter`, `maximum_distance_m` is always empty. Unverified against a live payload.
2. **Endurance score group values** are read only when the stored section is a mapping; a list-shaped section (the shape of the `endurance_score.json` fixture, which holds daily `overallScore` rows) gives none. Whether Garmin ever sends `groupMap` inside a list is unverified.
3. **Readiness alias order** differs between the history rows (`trainingReadinessScore` first) and the `readiness` section (`score` first). Which spelling Garmin sends first is unverified.
4. **Intervals.icu retired mappers** (removed with the retirement): `ctLoad` is read as the CTL fallback but the real key is `ctlLoad` (ignored; harmless while `ctl` is present); a zero `icu_w_prime` is stored as 0 J while other thresholds treat zero as unset; a heart-rate zone list with an open top marker above 250 drops the configuration silently; `intervals_power_curve_mapping.py` names `intervals_power.cycling_power_points` and `IntervalsReader`, which no longer exist; ten `*_ALIASES` tuples in `intervals_performance_fields.py` have no importer.
