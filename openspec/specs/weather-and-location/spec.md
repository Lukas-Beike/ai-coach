# weather-and-location Specification

## Purpose

Describe location-specific weather fetches, forecast/air/pollen source composition, cache and retry state, saved forecasts, and advisory training projections. Saved historical values are archived forecasts, not observed historical weather.

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
The system SHALL optionally merge timestamp-aligned CAMS/Open-Meteo air-quality and pollen data and German DWD pollen region forecasts without making those sources prerequisites for weather. DWD region lookup SHALL use longitude/latitude WKT order; accepted DWD levels SHALL take precedence over CAMS pollen for available species/dates. Daily projection SHALL retain units/categories/source labels and attribute each included source. Unknown optional data SHALL remain absent.

#### Scenario: German DWD pollen coverage
- **WHEN** coordinate lookup returns a DWD region and valid issued species levels
- **THEN** its dated pollen labels override the corresponding CAMS projection and DWD attribution is included.

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

### Requirement: Advisory weather training windows and adaptive reasons
The system SHALL propose supported near-term outdoor cycling/running windows from contiguous hourly forecast data, required precipitation/temperature inputs, event duration, weekday availability, and optional wind/rain/air-quality penalties. Indoor/virtual activities and inadequate hourly coverage SHALL yield no recommendation.

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

Evidence: `backend/weather/recommendations.py:weather_recommendation`, `backend/weather/recommendations.py:weather_recommendations`, `backend/weather/adaptive.py:weather_adaptive_reason`; `tests/test_weather_recommendations.py:test_weekday_and_friday_windows_are_selected_deterministically`, `tests/test_weather_recommendations.py:test_all_measurements_missing_yield_no_recommendation`, `tests/test_weather_adaptive.py:test_forecast_window_includes_today_and_third_day_only`, `tests/test_weather_adaptive.py:test_duration_threshold_is_inclusive`.
