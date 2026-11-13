# external-calendars Specification

## Purpose

Describe implemented read-only connected iCalendar import, safe bounded recurrence handling, training constraints, durable last-good state, and calendar composition. The public-source and candidate tables remain in storage, export and data deletion, but nothing fills them.

## Requirements

### Requirement: Public feed URL and transport safety
The system SHALL accept only the implemented credential-free HTTPS feed URL form, reject local/private or mixed public/private DNS results and unsafe ports, resolve within bounded time, pin the resolved address, and retain the TLS hostname. It SHALL reject redirects and bound the fetch to a 30-second total deadline, ten-second connection steps, and five million bytes. Feed text and errors SHALL not become instructions or expose private request URLs in logs.

#### Scenario: Public HTTPS feed
- **WHEN** the configured host resolves to supported public addresses
- **THEN** fetch uses a resolved pinned address with the original hostname for TLS and bounded resource use.

#### Scenario: SSRF or oversized response
- **WHEN** a URL resolves to a private address, redirects, exceeds the deadline, or returns an oversized body
- **THEN** the fetch fails before unsafe follow-up access and no feed replacement is committed.

Evidence: `backend/providers/calendar.py:external_calendar_url`, `backend/providers/calendar.py:fetch_calendar_feed`; `tests/test_provider_calendar.py:test_calendar_dns_rejects_private_mixed_and_resolution_errors`, `tests/test_provider_calendar.py:test_calendar_feed_resolves_once_pins_ip_and_uses_tls_hostname`, `tests/test_provider_calendar.py:test_calendar_feed_timeout_redirect_http_and_size_errors`.

### Requirement: Temporal event normalization
The system SHALL unfold and validate bounded UTF-8 iCalendar structure, parse supported DTSTART/DTEND/DURATION forms, preserve all-day and timed-event distinctions, and project dates, local start/end, and duration into the athlete timezone. Valid overlapping multiday events SHALL be retained. Known TZID and UTC source times SHALL preserve their temporal meaning; floating or unsupported-zone cases SHALL use the implemented local-zone fallback.

#### Scenario: All-day or overnight event
- **WHEN** a valid all-day or multiday event overlaps the requested window
- **THEN** normalized local bounds and duration preserve that overlap rather than truncating it to a start-date-only record.

#### Scenario: Invalid structure
- **WHEN** the payload has malformed component nesting, invalid encoding, or exceeds parser limits
- **THEN** parsing raises its bounded error and no partial imported event set is installed.

Evidence: `backend/providers/calendar.py:parse_ical_calendar`, `backend/providers/calendar.py:unfold_ical`; `tests/test_provider_calendar.py:test_normal_all_day_duration_and_markers`, `tests/test_provider_calendar.py:test_overlapping_multiday_event_and_nested_alarm`, `tests/test_provider_calendar.py:test_malformed_structure_utf8_and_limits`.

### Requirement: Bounded recurrence and exceptions
The system SHALL expand supported daily, weekly, monthly, and yearly recurrence rules within the requested date window, apply supported filters and week starts, and honor RDATE, EXDATE, RECURRENCE-ID overrides, and cancellation. It SHALL preserve the source timezone's recurrence clock across DST. An unsupported or invalid recurrence rule SHALL skip and count only its component; expansion SHALL enforce fixed count, period, raw-event, and result limits instead of unbounded iteration.

#### Scenario: Zoned weekly recurrence across DST
- **WHEN** a TZID-bound recurrence crosses a DST transition
- **THEN** instances preserve the source local wall time and are projected correctly into the athlete's local timezone.

#### Scenario: Exception and cancellation
- **WHEN** an instance is excluded, overridden by recurrence identity, or cancelled
- **THEN** the expanded set reflects the exception without retaining an extra unchanged duplicate.

#### Scenario: Yearly weekday position
- **WHEN** a yearly rule names a weekday with a position, such as `BYDAY=20MO` or `BYDAY=-1MO`
- **THEN** without BYMONTH the position counts within the year (one date a year), and with BYMONTH within each named month.

#### Scenario: Unsupported component
- **WHEN** a component has an unsupported or invalid recurrence rule or lacks UID or DTSTART
- **THEN** only that component is dropped, the skip is counted under its reason class without event text, and the remaining events are installed.

#### Scenario: Excessive feed
- **WHEN** a feed has more than 10,000 components, more than 1000 unique events in the sync window, or needs more than 1,000,000 expansion steps
- **THEN** the parser rejects the feed instead of claiming a complete truncated event set.

Detailed contract: skipped are components with `COUNT` or `INTERVAL` outside 1 to 1000, an `EXRULE` on a series whose `RRULE` reaches the sync window, an `RDATE` period, an invalid `RECURRENCE-ID`, or no UID or DTSTART.

Evidence: `backend/providers/calendar.py:_ical_rrule`, `backend/providers/calendar.py:_ical_instances`, `backend/providers/calendar.py:parse_ical_calendar`; `tests/test_provider_calendar.py:test_tzid_weekly_recurrence_keeps_source_wall_time_across_dst`, `tests/test_provider_calendar.py:test_rdate_exdate_recurrence_id_and_cancelled`, `tests/test_provider_calendar.py:test_recurrence_iteration_caps_are_fixed_not_tautological`, `tests/test_provider_calendar.py:test_unsupported_series_is_skipped_and_counted_without_event_text`.

### Requirement: Training constraints from external event data
The system SHALL derive training constraints from recognized NO_TRAINING, NO_INTENSITY, and SHORT_ONLY markers in event title/description, tolerating supported case, whitespace, hyphen, underscore, and bracket variants. It SHALL project constraint flags while dropping free-text description from persisted external-event DTOs. Blocking markers SHALL remain visible to planning even if ordinary training relevance is false; plain nonrelevant events may be excluded from that planning projection.

#### Scenario: Title-only blocker
- **WHEN** a title contains a recognized blocking marker but no training description
- **THEN** planning retains the corresponding constraint despite ordinary relevance being false.

#### Scenario: Ordinary descriptive text
- **WHEN** text lacks an accepted marker or resembles a bare unbracketed marker word
- **THEN** it does not acquire that marker's constraint through speculative interpretation.

#### Scenario: Round brackets
- **WHEN** a title or description contains `(no training)` or `[No-Training]`
- **THEN** the event carries the NO_TRAINING constraint; the words may be separated by spaces, hyphens or underscores, in any letter case.

#### Scenario: Event without description
- **WHEN** an event has a title only and no marker
- **THEN** it is stored with `training_relevant` 0 and is left out of reads that ask for relevant events, while window reads without that filter still return it.

Detailed contract: an event is training-relevant only with a non-empty description and no NO_TRAINING marker in title or description. The stored flags are `training_relevant`, `no_training`, `no_intensity` and `short_only`. A relevant-only read returns events with `training_relevant = 1` or any marker flag, after the athlete's decision is applied.

Evidence: `backend/calendar/markers.py:has_marker`, `backend/calendar/ical_mapping.py:calendar_event_constraints`, `backend/calendar/local.py:local_calendar_events`; `tests/test_calendar_markers.py:test_variants_match`, `tests/test_calendar_markers.py:test_bare_or_other_marker_does_not_match`, `tests/test_calendar_external.py:test_training_relevance_filter_keeps_no_training_blockers`, `tests/test_calendar_external.py:test_training_relevance_filter_keeps_title_only_no_intensity_markers`, `tests/test_provider_calendar.py:test_timing_default_relevance_and_description_markers`, `tests/test_provider_calendar.py:test_training_markers_are_contains_matched_in_title_and_description`, `tests/test_server_weather_calendar.py:test_non_relevant_external_events_are_stored_but_not_in_canonical_calendar_or_coach`.

### Requirement: Athlete decision per event
The system SHALL let the athlete set the training impact of a stored external event (`block`, `short`, `easy` or `none`) for one occurrence or for every occurrence of its UID, keep decisions apart from the feed rows so a refresh keeps them, and SHALL apply an occurrence decision over a series decision over the markers, replacing the marker flags. Decisions SHALL store no event text and come only from the explicit route.

#### Scenario: Feed refresh after a decision
- **WHEN** the sync replaces every stored event and a decided UID and start come back
- **THEN** the event keeps its decision; an occurrence whose start moved keeps only a series decision and otherwise counts as open again.

#### Scenario: Series decision
- **WHEN** the athlete decides for every occurrence
- **THEN** the single-occurrence decisions of that UID are replaced and the adaptive preview is recalculated.

Detailed contract: `block` sets `no_training` without ordinary relevance like its marker, `short` `short_only`, `easy` `no_intensity`, `none` clears all and the relevance; title markers yield too. Event reads carry `impact` (`open` without decision or marker), `decision_scope` and `recurring`; the status carries `undecided_upcoming`, the `open` events from today through 14 days ahead. `POST /api/external-calendar/decisions` (contract in `docs/api-routes.md`); `impact` `null` removes the decision, and a series removal removes the occurrence decisions too. A feed refresh drops single-occurrence decisions whose start lies before today. Decisions are in the export and the local data purge.

Evidence: `backend/calendar/external.py:list_events`, `backend/calendar/external.py:undecided_upcoming`, `backend/calendar/decisions.py:ExternalCalendarDecisionService.decide`; `tests/test_calendar_external.py:test_decisions_override_markers_and_survive_a_feed_refresh`, `tests/test_calendar_external.py:test_undecided_count_covers_open_events_of_the_next_fourteen_days`, `tests/test_calendar_external.py:test_decision_service_sets_replaces_and_removes_decisions`, `tests/test_calendar_external.py:test_decision_service_rejects_unknown_events_and_values`, `tests/test_sync_external_calendar.py:test_success_keeps_series_and_future_decisions_and_drops_past_ones`, `tests/test_db_migrations.py:test_populated_v27_database_gains_the_decision_table_with_every_row`.

### Requirement: Atomic connected-feed replacement and recovery
The system SHALL serialize configured external-calendar refresh, parse the future import window, and atomically replace stored feed events with success timestamp, daily marker, and cleared error/constraint-refresh state. A fetch, parse, insert, or marker failure SHALL preserve the last-good event set. Success SHALL publish changed state and request an adaptive preview/status projection without applying a replan or writing remote calendar events.

#### Scenario: Complete feed refresh
- **WHEN** a configured feed parses successfully for today through its 56-day future window
- **THEN** the new normalized event set replaces the previous set in one transaction, including removal of no-longer-present imported events and update of freshness metadata.

#### Scenario: Replacement or preview fails
- **WHEN** an insert/marker write fails
- **THEN** the old event set and success timestamps survive rollback; a post-commit adaptive-preview failure uses the supported status projection without reversing the committed import.

Evidence: `backend/sync/external_calendar.py:ExternalCalendarSyncService._sync_locked`, `backend/sync/external_calendar.py:ExternalCalendarSyncService._replan_projection`; `tests/test_sync_external_calendar.py:test_insert_failure_rolls_back_delete_and_keeps_last_good_events`, `tests/test_sync_external_calendar.py:test_daily_marker_failure_rolls_back_events_and_success_timestamps`, `tests/test_sync_external_calendar.py:test_adaptive_preview_failure_uses_status_projection`.

### Requirement: Read-only status and complete constraint-window reads
The system SHALL expose configured/read-only/running/last-sync/last-error/window metadata and bounded upcoming external-event lists from local storage. General event lists SHALL clamp to 1 through 1000; planning window reads SHALL retrieve all overlapping relevant events without that row cap so late events cannot hide constraint markers. Missing configuration SHALL fail sync before lock/provider access, and a concurrent refresh SHALL return already running without disturbing the owner.

#### Scenario: Many events within a planning window
- **WHEN** more than the normal public list limit of events overlap a planning window
- **THEN** the constraint-window read still sees all qualifying events, including late blockers.

#### Scenario: Missing configuration or held lock
- **WHEN** the URL is missing or another sync holds the calendar lock
- **THEN** sync returns the corresponding safe configuration/already-running outcome and preserves stored event data.

Evidence: `backend/calendar/external.py:list_events`, `backend/calendar/external.py:list_events_in_window`, `backend/calendar/external.py:state`, `backend/sync/external_calendar.py:ExternalCalendarSyncService.sync`; `tests/test_calendar_external.py:test_window_query_is_not_capped_so_day_markers_see_late_events`, `tests/test_sync_external_calendar.py:test_missing_url_precedes_held_lock_and_preserves_existing_error`, `tests/test_sync_external_calendar.py:test_lock_competition_is_observed_without_provider_or_database_calls`.

### Requirement: Local authority in the calendar composition
The system SHALL compose local planned units, competitions with their recorded Intervals.icu links, and relevant external constraints without reading Intervals.icu events and without losing local dirty/conflict state to a stale remote link. External feed events SHALL remain read-only constraints.

#### Scenario: Local conflict and stale remote snapshot
- **WHEN** a linked local unit is dirty or conflicted while it carries a remote link
- **THEN** calendar composition preserves local sync state and one linked representation rather than marking it clean merely from the link.

Evidence: `backend/calendar/canonical.py:canonical_planned_workouts`, `backend/calendar/local.py:local_calendar_events`; `tests/test_calendar_canonical.py:test_local_status_defaults_and_is_kept`, `tests/test_calendar_local.py:test_complete_read_model_uses_explicit_inputs`.

### Requirement: Skipped components are counted and reported
The system SHALL install the rest of a feed when a component is skipped, count each skip under a reason class (`recurrence` or `component`) without event text, store the counts of the last successful sync and show their sum in the connection status. Only a size or work limit SHALL reject the whole feed.

#### Scenario: Reason classes
- **WHEN** a feed contains an event with an unsupported or invalid recurrence rule, `EXRULE`, `RDATE` period or invalid `RECURRENCE-ID`, and a non-cancelled event without UID or DTSTART
- **THEN** the first is counted under `recurrence`, the second under `component`, and every other event is installed.

#### Scenario: Series that ended
- **WHEN** every rule of a series has an `UNTIL` more than one day before the widened sync window
- **THEN** the series yields nothing and is not counted as skipped.

#### Scenario: Limit exceeded
- **WHEN** the feed has more than 10,000 event components, more than 1000 unique events in the window or needs more than 1,000,000 expansion steps
- **THEN** it is rejected with 400, nothing is counted, and the stored events stay.

Detailed contract: the sync result carries `skipped: {count, reasons}`; the reason map is stored with the last sync and cleared by a sync without skips. The status read has `skipped_events`, the sum of the stored counts.

Evidence: `backend/providers/calendar.py::parse_ical_calendar`, `backend/providers/calendar.py::_ical_note_skip`, `backend/providers/calendar.py::_ical_base_starts`, `backend/sync/external_calendar.py::ExternalCalendarSyncService._sync_locked`, `backend/calendar/external.py::state`; `tests/test_provider_calendar.py::test_unsupported_series_is_skipped_and_counted_without_event_text`, `tests/test_provider_calendar.py::test_past_only_series_is_dropped_silently`, `tests/test_provider_calendar.py::test_feed_expansion_budget_bounds_unsatisfiable_recurrences`, `tests/test_sync_external_calendar.py::test_unsupported_component_is_skipped_stored_and_reported`, `tests/test_calendar_external.py::test_state_reports_the_skipped_component_count`.

### Requirement: Feed URL rules and failure codes
The system SHALL accept a feed URL only with scheme `https`, no port or port 443, a host, no user information, no fragment and no control characters, and SHALL refuse the hosts `localhost`, `localhost.localdomain`, `local` and any ending in `.local`. It SHALL fetch with TLS 1.2 or newer, `Accept: text/calendar, text/plain;q=0.9` and `User-Agent: Pacecraft/<version>`.

#### Scenario: Failure codes
- **WHEN** the URL is invalid, its host does not resolve or resolves to a non-global address during validation, or the feed redirects
- **THEN** the error status is 400; a validation that exceeds its deadline is 504; during the fetch, a resolution or network failure, a non-global address or an HTTP status of 400 and above is 502, a timeout is 504 and a body above 5,000,000 bytes is 413.

#### Scenario: Several addresses
- **WHEN** the first resolved address fails with a network error
- **THEN** the next address is tried; an application error or a timeout ends the attempt.

Detailed contract: the messages of each failure are row C1 of `docs/provider-endpoints.md`. Log entries of the fetch carry the path `/redacted`, the status, duration, byte count and address count, never the URL. The host is resolved twice, once to validate and once to fetch, and each time every address must be global.

Evidence: `backend/providers/calendar.py::_calendar_url_parts`, `backend/providers/calendar.py::_resolve_calendar_addresses`, `backend/providers/calendar.py::_calendar_feed_request`, `backend/providers/calendar.py::fetch_calendar_feed`, `backend/providers/calendar.py::external_calendar_url`; `tests/test_provider_calendar.py::test_external_calendar_url_validates_https_credentials_ports_and_local_hosts`, `tests/test_provider_calendar.py::test_calendar_url_rejects_control_characters_before_resolution`, `tests/test_provider_calendar.py::test_calendar_feed_falls_back_only_for_network_errors`, `tests/test_provider_calendar.py::test_calendar_transport_logs_only_redacted_path`, `tests/test_provider_calendar.py::test_calendar_fetch_deadline_bounds_blocking_dns_resolution`.

### Requirement: Parser bounds and event defaults
The system SHALL require one complete `VCALENDAR` document in UTF-8 with no line over 20,000 characters, and SHALL store per event an id derived from UID and local start, the UID (500 characters), the name (200 characters, default "Privater Kalendereintrag"), local date, local start and end, a duration in minutes of at least 1 and the all-day flag.

#### Scenario: Missing or invalid end
- **WHEN** an event has neither DTEND nor DURATION, or its end is not after its start
- **THEN** it lasts one day when all-day; otherwise one hour without an end, or 30 minutes with an invalid end.

#### Scenario: Supported recurrence parts
- **WHEN** a rule uses FREQ (DAILY, WEEKLY, MONTHLY, YEARLY), COUNT, UNTIL, INTERVAL, BYDAY, BYMONTHDAY (-31 to 31), BYMONTH (1 to 12), BYSETPOS (-366 to 366, monthly and yearly only) or WKST
- **THEN** it is expanded, and a date-only UNTIL includes that whole day in the instance's own zone.

#### Scenario: Duration forms
- **WHEN** DURATION is given in weeks, days, hours, minutes or seconds, also combined
- **THEN** a positive duration is used.

Detailed contract: the event id is `uuid5(NAMESPACE_URL, "ical-calendar:{uid}:{start_local}")`. DESCRIPTION is read up to 2000 characters for marker detection only and STATUS up to 30. The text escapes `\n`, `\N`, `\,`, `\;` and `\\` are decoded, property parameters may contain quoted colons and a byte-order mark is accepted. The import window is at most 56 days.

Evidence: `backend/providers/calendar.py::_unfold_lines`, `backend/providers/calendar.py::_ical_duration`, `backend/providers/calendar.py::ical_duration`, `backend/providers/calendar.py::_ical_rrule`, `backend/providers/calendar.py::_ical_past_until`, `backend/providers/calendar.py::_ical_instances`, `backend/providers/calendar.py::_ical_window`; `tests/test_provider_calendar.py::test_unfold_default_and_configurable_payload_limit`, `tests/test_provider_calendar.py::test_ical_duration_accepts_weeks_and_combined_forms`, `tests/test_provider_calendar.py::test_date_only_until_includes_the_until_day_in_the_source_zone`, `tests/test_provider_calendar.py::test_property_split_ignores_colons_inside_quoted_parameters`, `tests/test_provider_calendar.py::test_monthly_yearly_filters_and_bounds`.

### Requirement: Calendar sync entry point, result and stored status
`POST /api/external-calendar/sync` SHALL queue a calendar refresh job (contract in `docs/api-routes.md`). A successful sync SHALL return `status: "ok"`, `synced_at`, `events`, `skipped`, `window_days` 56, `needs_replan` and `replan_changes`, and SHALL publish a changed-state event. While a sync runs the stored status text SHALL be "Kalender: Synchronisierung läuft…", cleared afterwards in every case.

#### Scenario: Not configured
- **WHEN** no feed URL is configured
- **THEN** the sync fails with 503 `not_configured` ("CALENDAR_ICAL_URL ist nicht konfiguriert.") before it takes the lock.

#### Scenario: Recorded error
- **WHEN** a sync fails with a known error
- **THEN** its redacted message, cut to 1000 characters, is stored as the last error; an unexpected error is stored and raised as the generic safe provider error.

Evidence: `backend/sync/external_calendar.py::ExternalCalendarSyncService.sync`, `backend/sync/external_calendar.py::ExternalCalendarSyncService._sync_locked`, `backend/sync/external_calendar.py::ExternalCalendarSyncService._record_error`; `tests/test_sync_external_calendar.py::test_success_replaces_exact_columns_marks_daily_and_publishes_replan`, `tests/test_sync_external_calendar.py::test_invalid_app_error_is_redacted_and_preserves_last_good_events`, `tests/test_sync_external_calendar.py::test_generic_failure_maps_to_safe_provider_error_and_preserves_cause`, `tests/test_sync_external_calendar.py::test_cleanup_kv_failure_still_releases_module_lock`, `tests/test_server_weather_calendar.py::test_external_calendar_sync_keeps_url_server_side_and_replaces_events`.

### Requirement: Public-event tables have no import path
The system SHALL keep the tables for public event sources and candidates in storage, in the export and in the data deletion, and SHALL NOT fill them: no route, job or Coach tool creates a source or a candidate. Deleting a source SHALL delete its candidates.

#### Scenario: Settings screen
- **WHEN** the settings are shown
- **THEN** they offer no calendar event list and no public competition import.

Evidence: `backend/db/schema.py` (`public_event_sources`, `public_event_candidates`), `backend/backup/export.py`, `backend/privacy.py`; `tests/test_server_weather_calendar.py::test_public_calendar_source_delete_cascades_to_candidates`, `tests/test_server_weather_calendar.py::test_settings_do_not_render_calendar_events_or_public_competition_import`.

### Requirement: External calendar in the client
The client SHALL show the external calendar under the connections with a status chip, the count of skipped appointments or the note of a failed last update, and a "Synchronisieren" button that is disabled and reads "Synchronisierung läuft…" while a sync runs. Appointment titles in the planned days SHALL omit the constraint markers.

#### Scenario: Status detail
- **WHEN** the last update failed, or appointments were skipped
- **THEN** the detail reads "Fehler bei letzter Aktualisierung", which takes precedence, or "{n} Termine übersprungen".

#### Scenario: Marker in a title
- **WHEN** an appointment is named "Familienfeier [NO_TRAINING]"
- **THEN** the planned day shows "Familienfeier", and the marker as its own label ("Kein Training").

Evidence: `public/plan-views.js::externalCalendarDetail`, `public/plan-views.js::stripCalendarMarkers`, `public/plan-views.js::plannedAppointmentLabel`, `public/plan-views.js::renderExternalCalendar`, `public/sync-actions.js::syncExternalCalendar`; `tests/plan-views-external-calendar.test.cjs::the calendar status names the skipped appointments`, `tests/plan-views-external-calendar.test.cjs::an error outranks the skipped count`.

### Requirement: Local calendar projection fields
The system SHALL project a local planned workout with `id` (the remote event id when linked, else the local id), `local_id`, `remote_id`, `category` "WORKOUT", `starts_at_local` (midnight of its date when no time is set), `is_local: true`, `is_remote: false`, `sync_source: "local"` and its stored `sync_status` (default `local`).

#### Scenario: Ordering and limit
- **WHEN** planned workouts are projected
- **THEN** they are sorted by start, name and id, and at most 500 are returned by default (limit clamped to 1 to 1000).

#### Scenario: Competitions and external events
- **WHEN** the calendar read model is built
- **THEN** a competition has `is_competition: true`, category default `RACE_B`, `sync_source` `local+intervals` and `is_remote` when it carries a remote link (else `local`), and `sync_status` from its stored sync state; an external event has `is_external_calendar: true`, `sync_source: "external-calendar"` and `sync_status: "read-only"`, and is included only when training-relevant or marked.

Evidence: `backend/calendar/canonical.py::canonical_planned_workouts`, `backend/calendar/local.py::local_calendar_events`; `tests/test_calendar_canonical.py::test_sorting_uses_start_name_and_identity_with_stable_ties`, `tests/test_calendar_canonical.py::test_limit_is_clamped_to_one_and_one_thousand`, `tests/test_calendar_local.py::test_competition_and_external_event_fields_preserve_contract`.
