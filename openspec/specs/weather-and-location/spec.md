# weather-and-location Specification

## Purpose

Describe location-specific weather fetches, forecast/air/pollen source composition, cache and retry state, saved forecasts, and advisory training projections. Saved historical values are archived forecasts, not observed historical weather, as are the weather values stored for past sessions.

## Requirements

### Requirement: Profile weather location and geocoding
The system SHALL obtain the weather query from the stored athlete profile, report not configured when blank, and geocode the bounded city/postcode query through Open-Meteo. It SHALL retain the selected location's bounded name/country/code, finite coordinates, and timezone metadata. Missing or unusable geocoding SHALL produce a safe location error rather than inventing coordinates or silently using another stored location.

#### Scenario: Valid configured location
- **WHEN** the profile contains a usable query and geocoding returns a supported location
- **THEN** forecast requests use its coordinates and retain location metadata with the cached result.

#### Scenario: No location match
- **WHEN** the query is blank or geocoding returns no usable coordinate-bearing location
- **THEN** state is not configured or the supported location error is returned, with no fabricated forecast.

Evidence: `backend/providers/weather.py:WeatherClient._geocoded_location`, `backend/weather/service.py:WeatherService._state`; `tests/test_weather_provider.py:test_missing_geocoded_location_raises_400`, `tests/test_weather_service.py:test_location_change_discards_refresh_after_commit`.

### Requirement: Forecast model composition
The system SHALL fetch the configured forecast horizon from ECMWF through Open-Meteo with automatic timezone selection and the supported hourly/daily fields. For German locations it SHALL attempt a two-day ICON-D2 overlay, aligning usable values by timestamp and keeping base values for null/nonfinite overlay values. ICON-D2 failure SHALL retain the base forecast.

#### Scenario: German location with short forecast
- **WHEN** both base and ICON-D2 sections are structurally usable
- **THEN** matching valid short-range values override the corresponding base positions and model attribution names both sources.

#### Scenario: Optional model unavailable
- **WHEN** ICON-D2 fails or the location is outside Germany
- **THEN** the ECMWF forecast remains available with its own attribution; an unusable base response fails instead of returning the optional response as a complete replacement.

Detailed contract: Missing daily/hourly object sections SHALL fail the base fetch; current completeness checks are structural, not proof of every timestamp or field.

Evidence: `backend/providers/weather.py:WeatherClient.fetch`, `backend/providers/weather.py:WeatherClient._fetch_icon_d2`, `backend/providers/weather_data.py:merge_weather_forecasts`, `backend/providers/weather_data.py:weather_forecast_is_complete`; `tests/test_weather_provider.py:test_german_location_merges_icon_d2_and_preserves_request_contract`, `tests/test_weather_forecast.py:test_merge_keeps_base_values_when_short_values_are_null_or_non_finite`, `tests/test_weather_provider.py:test_incomplete_ecmwf_forecast_raises_502_without_icon_request`.

### Requirement: Optional air quality and pollen provenance
The system SHALL optionally merge timestamp-aligned CAMS/Open-Meteo air-quality and pollen data and German DWD pollen region forecasts without making those sources prerequisites for weather. DWD region lookup SHALL use longitude/latitude WKT order; accepted DWD levels SHALL replace CAMS pollen on each date they cover. Daily projection SHALL retain units/categories/source labels and attribute each included source. Unknown optional data SHALL remain absent.

#### Scenario: German DWD pollen coverage
- **WHEN** coordinate lookup returns a DWD region and valid issued species levels
- **THEN** each date with DWD levels carries only the DWD pollen labels, CAMS pollen remains for the other dates, and DWD attribution is included.

#### Scenario: Optional overlay failure
- **WHEN** air quality or DWD lookup fails or provides no supported region/data
- **THEN** the weather forecast remains usable, logs contain only safe error classification, and missing optional measurements are not reported as zero.

Evidence: `backend/providers/air_quality.py:merge_air_quality`, `backend/providers/dwd_pollen.py:pollen_region_params`, `backend/providers/dwd_pollen.py:pollen_forecast`, `backend/weather/cache.py:attribution`; `tests/test_weather_air_quality.py:test_region_query_uses_lat_lon_point`, `tests/test_weather_air_quality.py:test_dwd_pollen_takes_precedence_over_cams`, `tests/test_weather_air_quality.py:test_optional_source_failures_keep_weather_and_log_type_only`.

### Requirement: Location-keyed cache and freshness
The system SHALL persist a forecast cache keyed to the exact current query, treat it fresh for 10800 seconds, and distinguish not-configured, loading, ready, stale, and error states. Local reads with refresh disabled SHALL perform no provider access. An expired matching cache SHALL remain visible with stale/error metadata when refresh fails; a cache for another query SHALL not be served as the current location. Manual force SHALL bypass cache age and retry delay.

#### Scenario: Fresh local read
- **WHEN** a matching cache is younger than three hours or the caller requests a local-only projection
- **THEN** the stored projection is served without a provider fetch and retains fetched-at metadata.

#### Scenario: Failed refresh with last-good cache
- **WHEN** a matching cache expires and provider refresh fails
- **THEN** existing days remain visible with stale/error state instead of being erased or described as freshly fetched.

Evidence: `backend/weather/cache.py:cache_state`, `backend/weather/cache.py:ready_state`, `backend/weather/service.py:WeatherService.state`, `backend/weather/service.py:WeatherService.refresh_due`; `tests/test_weather_cache.py:test_freshness_boundary_and_utc_z_timestamp`, `tests/test_weather_service.py:test_local_read_does_not_fetch_and_uses_cached_projection`, `tests/test_weather_cache.py:test_ready_stale_and_refreshed_projection`.

### Requirement: Bounded retry and atomic refresh persistence
The system SHALL persist weather cache/history/success state atomically and store safe failure metadata before emitting failure completion. Nonforced retry delay SHALL start at 900 seconds, grow exponentially, and cap at 21600 seconds. Refresh-due checks SHALL respect both expiry and retry time. Database failures SHALL roll back cache/history together, and maintenance SHALL bound the stateful refresh operation.

#### Scenario: Repeated provider failure
- **WHEN** weather fetch repeatedly fails
- **THEN** retry-at/count metadata grows within the six-hour cap and ordinary automatic refresh waits until eligible.

#### Scenario: History write fails
- **WHEN** persistence fails after a new cache value is prepared
- **THEN** cache/history roll back as one transaction instead of combining a new forecast with old history metadata.

Evidence: `backend/weather/cache.py:failure_record`, `backend/weather/service.py:WeatherCacheStore.store_refresh`, `backend/weather/service.py:WeatherService._record_failure`; `tests/test_weather_cache.py:test_failure_delay_caps_at_six_hours`, `tests/test_weather_service.py:test_cache_and_history_writes_roll_back_together`, `tests/test_weather_service.py:test_failure_is_persisted_before_error_event_and_retry_is_bounded`.

### Requirement: Location-change race protection
The system SHALL invalidate the current cache and failure state transactionally when profile weather location changes. Before committing an in-flight forecast or failure, the store SHALL recheck that the requested location still matches the profile. A result for an old location SHALL be discarded and the returned state reevaluated for the current location rather than overwriting it.

#### Scenario: Location changed during successful fetch
- **WHEN** the athlete changes or clears weather location before the old fetch returns
- **THEN** that result is not installed and state reflects the new query or not-configured condition.

#### Scenario: Location changed during failed fetch
- **WHEN** an old-location request fails after a profile change
- **THEN** its retry backoff is not attached to the new location.

Evidence: `backend/weather/cache.py:invalidate_for_location_change`, `backend/weather/service.py:WeatherCacheStore.store_refresh`, `backend/weather/service.py:WeatherCacheStore.store_failure`; `tests/test_weather_service.py:test_location_change_discards_refresh_after_commit`, `tests/test_weather_service.py:test_location_change_discards_failure_retry_state_for_previous_location`.

### Requirement: Calendar forecast history and projections
The system SHALL archive daily forecast projections with saved-at/location metadata, merge current forecast days with past saved days, and mark past values as archived forecasts. It SHALL not label them measured weather. Planned-event enrichment SHALL prefer exact event identity before the supported date/name fallback and SHALL avoid mutating caller data. Daily/hourly projections SHALL bound rows and retain unknown measurements instead of replacing them with zero.

#### Scenario: Day becomes historical
- **WHEN** a previously saved forecast day moves before today
- **THEN** calendar state can still expose it with archived-forecast and save/location metadata.

#### Scenario: Recommendation identity collision
- **WHEN** a planned event has both an exact recommendation id match and a date/name match
- **THEN** exact identity wins and the original planned input remains unchanged.

Evidence: `backend/weather/history.py:remember_forecasts`, `backend/weather/history.py:calendar_state`, `backend/weather/history.py:add_to_planned`, `backend/weather/projection.py:daily_summary`; `tests/test_weather_history.py:test_calendar_state_keeps_past_history_and_current_weather_wins`, `tests/test_weather_history.py:test_add_to_planned_matches_id_before_date_and_name_without_mutation`, `tests/test_weather_projection.py:test_daily_summary_filters_dates_caps_rows_and_projects_fields`.

### Requirement: Weather during outdoor sessions
The system SHALL store Open-Meteo historical-forecast weather per outdoor ride or run since 2022 as derived observations, at the first stored GPS position or else the saved weather location, labelled home. Only two-decimal coordinates SHALL be sent; none SHALL reach observations, logs, diagnostics or the Coach. Requests SHALL run outside the writer transaction; a current result SHALL not be refetched. The Coach read SHALL note heat from 25 C apparent temperature.

#### Scenario: Position and fallback
- **WHEN** a session has a stored position, or is outdoors with none and a weather location is saved
- **THEN** the request uses the rounded position or home coordinates and the label names "Startposition" or "Wohnort".

#### Scenario: Unknown environment
- **WHEN** a session has an unknown environment and no stored position
- **THEN** no request is made and the home location is never used for it.

#### Scenario: Cache and failure
- **WHEN** a session already has a current result, or a request fails
- **THEN** no second request is made for the result, and a failure writes no observation and waits before a retry.

#### Scenario: Not yet settled
- **WHEN** a session ended less than 48 hours ago
- **THEN** nothing is requested for it yet.

#### Scenario: Pass size and backoff
- **WHEN** more than 20 sessions need a look-up, or a request fails
- **THEN** at most 20 are looked up per pass, newest first; a failure ends the pass and delays that session by 30 minutes, doubling per failure up to 24 hours, and the delay is lost on restart.

#### Scenario: Empty answer
- **WHEN** a request succeeds without any value
- **THEN** the session is remembered as empty and not requested again until its inputs change.

#### Scenario: Changed inputs
- **WHEN** a session's streams or times change, or the home location moves for a session stored at home
- **THEN** it is looked up again; the rows of sessions that no longer exist are retired.

Detailed contract: a session of unknown environment is included only with a stored GPS position and never uses the home location. Each value is the mean of the hourly values weighted by their overlap with the session, where an hourly value at `h` covers `h - 30 min` to `h + 30 min`; precipitation at `h` is the amount of the preceding hour and its value the amount that fell during the session. A session counts at least one minute, and the requested UTC days run from 30 minutes before the start to one hour after the end. The stored metrics are temperature, apparent temperature, relative humidity, wind speed in m/s and precipitation in mm, reduced to two decimals, with method `open-meteo-activity-weather` version 1 and `location_kind` `activity_start` or `home`. The heat note reads "Hitze: gefühlte Temperatur {x} °C (ab 25 °C). Puls, Entkopplung und Tempo nicht als Fitnessänderung lesen.". The stage status (`pending`, `running`, `complete`, `retry`, `failed`) and its counts carry no position, value or session id.

Evidence: `backend/sync/activity_weather.py:ActivityWeatherStage`, `backend/providers/activity_weather.py:activity_weather_params`, `backend/weather/activity_weather.py:reduce_hourly`, `backend/weather/activity_weather.py:heat_note`; `tests/test_activity_weather.py:test_start_position_is_fetched_rounded_and_stored`, `tests/test_activity_weather.py:test_an_unknown_environment_needs_a_stored_start_position`, `tests/test_activity_weather.py:test_a_stored_result_is_never_fetched_again`, `tests/test_activity_weather.py:test_no_raw_coordinate_leaves_the_stored_streams`, `tests/test_activity_weather.py:test_a_session_that_just_ended_waits_for_its_forecast`, `tests/test_activity_weather.py:test_a_failed_fetch_writes_nothing_and_backs_off`, `tests/test_activity_weather.py:test_a_response_without_values_is_remembered_not_refetched`, `tests/test_activity_weather.py:test_a_moved_home_looks_up_a_home_session_again_but_not_a_start`, `tests/test_activity_weather.py:test_hours_around_a_full_hour_are_averaged_by_overlap`, `tests/test_activity_weather.py:test_gone_sessions_retire_their_rows`.

### Requirement: Advisory weather training windows and adaptive reasons
The system SHALL propose supported near-term outdoor cycling/running windows from contiguous hourly forecast data, required precipitation/temperature inputs, event duration, weekday availability, and optional wind/rain/air-quality penalties. The list function SHALL skip indoor/virtual activities, and inadequate hourly coverage SHALL yield no recommendation.

#### Scenario: Suitable weekday window
- **WHEN** a supported outdoor event has sufficient contiguous usable forecast hours inside an allowed weekday/weekend window
- **THEN** the deterministic candidate ranking returns a bounded recommendation with its weather reason and known measurements.

#### Scenario: Sparse forecast or indoor session
- **WHEN** required measurements/hours are missing or the workout is indoor/virtual
- **THEN** no confident outdoor recommendation is returned; unknown optional wind/air values remain unknown.

#### Scenario: Persistent precipitation before long ride
- **WHEN** an at-least-three-hour outdoor ride lies within the three-day adaptive horizon and meets the implemented rain/snow rule
- **THEN** a weather reason can contribute to a replan preview without directly changing local or remote workouts.

Detailed contract: Separately, the adaptive reason SHALL consider outdoor cycling of at least 180 minutes only within today and the next two days, using implemented persistent rain/snow thresholds; producing a reason SHALL not apply or export a changed workout.

Evidence: `backend/weather/recommendations.py:weather_recommendation`, `backend/weather/recommendations.py:weather_recommendations` (the indoor/virtual filter), `backend/weather/adaptive.py:weather_adaptive_reason`; `tests/test_weather_recommendations.py:test_weekday_and_friday_windows_are_selected_deterministically`, `tests/test_weather_recommendations.py:test_all_measurements_missing_yield_no_recommendation`, `tests/test_weather_adaptive.py:test_forecast_window_includes_today_and_third_day_only`, `tests/test_weather_adaptive.py:test_duration_threshold_is_inclusive`.

### Requirement: Weather state payload and refresh entry points
The system SHALL answer `GET /api/weather` (contract in `docs/api-routes.md`) with `configured`, `state`, `provider` "Open-Meteo", `days` and `recommendations`; a cached forecast adds `attribution`, `model`, `location` and `fetched_at`, and stale data `error` and `stale: true`. `?local=1` SHALL read without provider access. `POST /api/weather/sync` SHALL queue a forced refresh job.

#### Scenario: States
- **WHEN** no location is saved, a local read finds no cached forecast, a cached forecast is fresh, a cached forecast is older than 10800 seconds or a failure is recorded, or no forecast exists after a failed refresh
- **THEN** `state` is `not_configured`, `loading` (with `loading: true`), `ready`, `stale`, or `error`.

#### Scenario: Location not found
- **WHEN** geocoding finds no location
- **THEN** the error text is "Der Wetterort wurde nicht gefunden."; every other failure shows "Wetterdaten konnten derzeit nicht aktualisiert werden."

#### Scenario: Concurrent refreshes
- **WHEN** an unforced refresh waited for the refresh lock while another one stored a fresh forecast
- **THEN** it uses the stored forecast and makes no request; a forced refresh always fetches.

#### Scenario: Sync job result
- **WHEN** a weather sync job ends
- **THEN** its result is `{status: "not_configured"}` without a location, else `{status: "ok" | "stale", reason, fetched_at, needs_replan, replan_changes}`; a refresh that ends with an error and no days fails the job with 502.

Detailed contract: the messages are "Hinterlege im Profil einen Wetterort (Stadt oder PLZ).", "Wetterdaten werden nachgeladen.", "Wetterdaten sind veraltet.", "Wetterdaten konnten nach einem Fehler noch nicht erneut geladen werden." (retry still waiting) and "Wetterdaten sind nicht verfügbar.". The cache row (`weather_cache`) holds `query`, `location`, `model`, `forecast`, `fetched_at` and optional `air_quality_source` and `pollen`; the failure row (`weather_failure`) holds `count`, `failed_at` and `retry_at` and is not exposed.

Evidence: `backend/weather/service.py::WeatherService._state`, `backend/weather/service.py::WeatherService._record_failure`, `backend/weather/cache.py::cache_state`, `backend/weather/cache.py::unavailable_state`, `backend/weather/cache.py::ready_state`, `backend/http_api/public_weather.py::PublicWeatherStateService.state`, `backend/sync/weather.py::WeatherSyncService._sync_inner`; `tests/test_weather_service.py::test_refresh_that_waited_for_the_lock_reuses_the_fresh_forecast`, `tests/test_weather_service.py::test_forced_refresh_still_fetches_inside_the_lock`, `tests/test_weather_cache.py::test_unavailable_state_loading_and_error_messages`, `tests/test_sync_weather.py::test_provider_error_without_days_is_raised`, `tests/test_server_weather_calendar.py::test_public_weather_state_service_refreshes_only_when_not_local_and_hides_marker`.

### Requirement: Weather provider requests
The system SHALL geocode with `name` (at most 200 characters), `count=1` and `language=de`, request the forecast for 14 days with `models=ecmwf_ifs`, `timezone=auto` and fixed hourly and daily field lists, request ICON-D2 for 2 days with the same fields, request air quality for 5 days, and read DWD pollen through a region lookup and the national feed. Each request SHALL time out after 10 seconds.

#### Scenario: Model label
- **WHEN** ICON-D2 values were merged
- **THEN** `model` is "ICON-D2 (0–2 Tage) + ECMWF IFS HRES (3–14 Tage)"; otherwise it is "ECMWF IFS HRES" without a day range.

#### Scenario: DWD region and levels
- **WHEN** the location is in Germany
- **THEN** the region is found with a WFS point query on `dwd:Pollenfluggebiete` (coordinates rounded to four decimals), and only the levels `0`, `0-1`, `1`, `1-2`, `2`, `2-3` and `3` of the eight known species for today, tomorrow and the day after the feed's issue date are kept.

#### Scenario: Incomplete base forecast
- **WHEN** the ECMWF response lacks its daily or hourly section
- **THEN** the fetch fails with 502 "Open-Meteo hat keine vollständige Wettervorhersage geliefert." and no ICON-D2 request is made.

Detailed contract: the endpoints, models, timeouts and error mapping are rows M1 to M6 of `docs/provider-endpoints.md`. Only the first geocoding result is used. The stored location keeps the name (200 characters, the query when the result has none), country (100), country code (2, upper case), time zone (80) and finite coordinates; without coordinates the lookup fails with 400 "Der Wetterort wurde nicht gefunden.". Hourly fields are `temperature_2m, apparent_temperature, precipitation_probability, rain, showers, snowfall, weather_code, wind_speed_10m, wind_direction_10m, wind_gusts_10m`; daily fields are `weather_code, temperature_2m_min, temperature_2m_max, apparent_temperature_min, apparent_temperature_max, precipitation_probability_max, rain_sum, showers_sum, snowfall_sum, wind_speed_10m_max, wind_gusts_10m_max, wind_direction_10m_dominant, sunrise, sunset`. Air quality reads hourly `european_aqi, pm2_5, pm10, ozone, nitrogen_dioxide, uv_index` and six pollen series (alder, birch, grass, mugwort, olive, ragweed) with `domains=auto`. The DWD species are Hasel, Erle, Esche, Birke, Gräser, Roggen, Beifuß and Ambrosia.

Evidence: `backend/providers/weather.py::WeatherClient.fetch`, `backend/providers/weather.py::WeatherClient._geocoded_location`, `backend/providers/weather.py::WeatherClient._fetch_icon_d2`, `backend/providers/weather_data.py::weather_forecast_params`, `backend/providers/air_quality.py::air_quality_params`, `backend/providers/dwd_pollen.py::pollen_region_params`, `backend/providers/dwd_pollen.py::pollen_forecast`; `tests/test_weather_forecast.py::test_params_preserve_location_days_model_and_requested_fields`, `tests/test_weather_air_quality.py::test_params_request_hourly_cams_variables`, `tests/test_weather_air_quality.py::test_forecast_maps_partregion_levels_to_dates`, `tests/test_weather_air_quality.py::test_client_skips_lookup_outside_germany`, `tests/test_weather_provider.py::test_non_german_location_skips_icon_d2`, `tests/test_weather_provider.py::test_incomplete_ecmwf_forecast_raises_502_without_icon_request`.

### Requirement: Daily weather row
The system SHALL project at most 14 daily rows with `date`, `weather_code`, `condition`, `icon`, minimum and maximum temperature and apparent temperature, `precipitation_probability_max`, `rain_peak_time`, rain, shower and snowfall sums, maximum wind speed and gusts, dominant wind direction, `sunrise`, `sunset`, and optional `air_quality` and `pollen`.

#### Scenario: Condition text
- **WHEN** the weather code is known, unknown, or absent
- **THEN** `condition` is its German WMO label, "Unbekannte Wetterlage", or "Keine Angabe".

#### Scenario: Air quality category
- **WHEN** the day's highest European AQI is at most 20, 40, 60, 80, 100, or higher
- **THEN** the category is "gut", "ordentlich", "mäßig", "schlecht", "sehr schlecht", or "extrem schlecht".

#### Scenario: Rain peak time
- **WHEN** the day's hourly rain probabilities have a highest value that at least one other hour stays below
- **THEN** `rain_peak_time` is the first hour of that maximum as `HH:MM`; otherwise it is absent.

#### Scenario: Pollen
- **WHEN** DWD levels exist for the date
- **THEN** `pollen` is `{source: "DWD", region, levels}` without species at level "0"; otherwise it holds the daily maxima of the CAMS series of at least 1 grain per cubic metre, rounded, with unit "Körner/m³".

Detailed contract: `air_quality` holds `<field>_max` (one decimal, negative values ignored) for the six air fields plus `european_aqi_category`. The attribution is "Wetterdaten: Open-Meteo.com[, Copernicus Atmosphere Monitoring Service (CAMS)][, Deutscher Wetterdienst (Pollenflug-Gefahrenindex)] (CC BY 4.0)". The code and icon tables are `WEATHER_CONDITIONS` and `WEATHER_ICONS`.

Evidence: `backend/weather/projection.py::daily_summary`, `backend/weather/projection.py::european_aqi_category`, `backend/weather/projection.py::_daily_pollen`, `backend/weather/cache.py::attribution`; `tests/test_weather_air_quality.py::test_european_aqi_categories`, `tests/test_weather_air_quality.py::test_daily_summary_adds_air_quality_and_cams_pollen`, `tests/test_weather_air_quality.py::test_ready_state_attributes_every_present_source`, `tests/test_weather_projection.py::test_daily_peak_requires_valid_time_and_a_real_peak`, `tests/test_weather_projection.py::test_daily_fallbacks_unknown_codes_and_missing_arrays`.

### Requirement: Forecast archive horizon
The system SHALL keep archived daily forecasts for 14 days before today and drop older days whenever a forecast is stored. Archived days SHALL survive a refresh, a change of the weather location and a restart.

#### Scenario: Pruning
- **WHEN** a refresh is stored
- **THEN** archive days older than 14 days are removed, and the days of the replaced and the new forecast are written with their own save time and location name.

#### Scenario: Old unpruned archive
- **WHEN** the calendar state is built from an archive that still holds older days
- **THEN** only days from the last 14 days are shown.

Evidence: `backend/weather/history.py::remember_forecasts`, `backend/weather/history.py::calendar_state`, `backend/weather/service.py::WeatherCacheStore.store_refresh`; `tests/test_weather_history.py::test_history_older_than_the_horizon_is_pruned_when_remembering`, `tests/test_weather_history.py::test_calendar_state_stays_bounded_for_an_old_unpruned_history`, `tests/test_server_weather_calendar.py::test_calendar_weather_history_survives_refresh_location_change_and_restart`.

### Requirement: Training window selection
For each planned outdoor ride or run from today to four days ahead, the system SHALL pick the start hour with the lowest score among windows of whole hours covering the planned duration: Monday to Thursday 05–06 ("vor der Arbeit"), 12–13 ("Mittagspause") and 16–22 ("nach der Arbeit"); Friday 05–06, 12–13 and 14–22; Saturday and Sunday 06–21 ("Wochenende"). Ties SHALL go to the earlier hour.

#### Scenario: Score
- **WHEN** a window has mean rain probability `p`, rain `r` mm (sum of rain and showers), mean wind `w` and highest gusts `g` km/h, mean apparent temperature `t` and highest European AQI `a`
- **THEN** its score is `0.8p + 8r + max(0, w-20)·k + max(0, g-30)·m + 1.5·max(0, 4-t) + 1.2·max(0, t-27) + 0.6·max(0, a-40)`, plus 25 per hour with a weather code of 95 or more and 8 per hour with a code from 61 to 86, plus 2 for a window before work; `k` is 0.5 for a run and 1.4 otherwise, `m` is 1.0 for an outdoor ride and 0.5 otherwise.

#### Scenario: Duration
- **WHEN** the planned duration is unknown or zero, below 5 or above 600 minutes
- **THEN** 60, 5 or 600 minutes are used, rounded up to whole hours.

#### Scenario: Result
- **WHEN** a window is chosen
- **THEN** the recommendation has `date`, `event_id`, `event_name`, `suggested_time` ("HH:00–HH:00 Uhr"), `availability`, `weather_code`, `icon`, `duration_minutes`, rounded `precipitation_probability`, `apparent_temperature`, `wind_speed`, `wind_direction`, `wind_gusts`, optional `european_aqi`, and a German `reason` that names the air quality only from AQI 60.

Detailed contract: unknown wind, rain or air values add no penalty; rain probability and apparent temperature must be known. An entry is outdoor when its canonical sport is ride or run and its environment is not indoor or virtual; an entry without a resolvable sport is classified by whole-word name patterns, and words such as indoor, virtual, trainer, zwift, treadmill, ergometer, laufband and rolle mark it indoor. The duration is read from `planned_duration_s` only.

Evidence: `backend/weather/recommendations.py::weather_recommendation`, `backend/weather/recommendations.py::weather_recommendations`, `backend/weather/recommendations.py::_weather_window_score`, `backend/weather/recommendations.py::_weather_training_windows`, `backend/weather/recommendations.py::_event_sport`; `tests/test_weather_recommendations.py::test_weekend_and_missing_hour_gaps`, `tests/test_weather_recommendations.py::test_invalid_dates_and_duration_bounds`, `tests/test_weather_recommendations.py::test_output_fields_rounding_bounds_and_input_nonmutation`, `tests/test_weather_recommendations.py::test_classification_uses_sport_and_environment_before_the_name`, `tests/test_weather_air_quality.py::test_poor_air_quality_moves_window`, `tests/test_server_weather_calendar.py::test_weather_recommendation_respects_weekday_work_and_friday_hours`.

### Requirement: Weather reason thresholds
The weather reason for a long outdoor ride SHALL be given only for persistent rain or snow on the planned day.

#### Scenario: Persistent rain
- **WHEN** the day's weather code is one of 61, 63, 65, 80, 81, 82, 95, 96 and 99, and either the rain probability is at least 70 percent with at least 3 mm of rain and showers, or at least 8 mm are forecast, or the code is one of 63, 65, 81, 82, 95, 96 and 99
- **THEN** the reason is "Wetterprognose für {date}: anhaltenden Regen (…); lange Outdoor-Ausfahrt nicht sinnvoll".

#### Scenario: Persistent snow
- **WHEN** the code is one of 71, 73, 75, 77, 85 and 86 and the probability is at least 70 percent or at least 2 cm of snow are forecast
- **THEN** the reason names "anhaltenden Schneefall".

#### Scenario: Other weather
- **WHEN** heat, wind or lighter precipitation is forecast
- **THEN** no weather reason is produced.

Detailed contract: the bracket lists "bis zu {p} % Niederschlagswahrscheinlichkeit" and "ca. {x} mm Regen" or "ca. {x} cm Schnee" when known. The duration is `duration_minutes`, else `planned_duration_s / 60`.

Evidence: `backend/weather/adaptive.py::weather_adaptive_reason`, `backend/weather/adaptive.py::_weather_adaptive_precipitation`; `tests/test_weather_adaptive.py::test_rain_thresholds_and_code_handling`, `tests/test_weather_adaptive.py::test_snow_thresholds`, `tests/test_weather_adaptive.py::test_exact_reason_text_and_input_nonmutation`, `tests/test_weather_adaptive.py::test_duration_prefers_duration_minutes_then_moving_time`.

### Requirement: Calendar weather display
The client SHALL show, beside each calendar day, the weather symbol with the temperature range, and flags only for a rain probability of at least 50 percent, a UV index of at least 6, a European AQI of at least 60, a DWD pollen level whose upper bound is at least 1 or a CAMS pollen concentration of at least 10 grains per cubic metre. All other figures SHALL be in the symbol's tooltip.

#### Scenario: Archived day
- **WHEN** a day shows an archived forecast
- **THEN** its tooltip starts with "Gespeicherte Wettervorhersage" instead of "Wettervorhersage".

#### Scenario: No weather
- **WHEN** no forecast exists for the coming days
- **THEN** the hint reads "Für die kommenden Tage liegt noch keine Wettervorhersage vor.", or without a saved location "Wetter fehlt: Im Profil ist kein Wetterort hinterlegt."

Evidence: `public/plan-views.js::plannedWeatherFlags`, `public/plan-views.js::plannedPollenPeak`, `public/plan-views.js::plannedWeatherDetails`, `public/plan-views.js::plannedWeatherHint`.
