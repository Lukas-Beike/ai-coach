# external-calendars Specification

## Purpose

Describe implemented read-only connected iCalendar import, safe bounded recurrence handling, training constraints, durable last-good state, and calendar composition. Stored public-source/candidate query helpers are included as persistence reads; no active public-source import API is inferred from their existence.

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
The system SHALL expand supported daily, weekly, monthly, and yearly recurrence rules within the requested date window, apply supported filters and week starts, and honor RDATE, EXDATE, RECURRENCE-ID overrides, and cancellation. It SHALL preserve the source timezone's recurrence clock across DST. Unsupported rules SHALL fail explicitly; expansion SHALL enforce fixed count, period, raw-event, and result limits instead of unbounded iteration.

#### Scenario: Zoned weekly recurrence across DST
- **WHEN** a TZID-bound recurrence crosses a DST transition
- **THEN** instances preserve the source local wall time and are projected correctly into the athlete's local timezone.

#### Scenario: Exception and cancellation
- **WHEN** an instance is excluded, overridden by recurrence identity, or cancelled
- **THEN** the expanded set reflects the exception without retaining an extra unchanged duplicate.

#### Scenario: Excessive recurrence
- **WHEN** requested recurrence count exceeds 1000, iteration exceeds supported bounds, or expanded results exceed 1000 events
- **THEN** the parser rejects the unsafe feed instead of claiming a complete truncated event set.

Evidence: `backend/providers/calendar.py:_ical_rrule`, `backend/providers/calendar.py:_ical_instances`, `backend/providers/calendar.py:parse_ical_calendar`; `tests/test_provider_calendar.py:test_tzid_weekly_recurrence_keeps_source_wall_time_across_dst`, `tests/test_provider_calendar.py:test_rdate_exdate_recurrence_id_and_cancelled`, `tests/test_provider_calendar.py:test_recurrence_iteration_caps_are_fixed_not_tautological`.

### Requirement: Training constraints from external event data
The system SHALL derive training constraints from recognized NO_TRAINING, NO_INTENSITY, and SHORT_ONLY markers in event title/description, tolerating supported case, whitespace, hyphen, underscore, and bracket variants. It SHALL project constraint flags while dropping free-text description from persisted external-event DTOs. Blocking markers SHALL remain visible to planning even if ordinary training relevance is false; plain nonrelevant events may be excluded from that planning projection.

#### Scenario: Title-only blocker
- **WHEN** a title contains a recognized blocking marker but no training description
- **THEN** planning retains the corresponding constraint despite ordinary relevance being false.

#### Scenario: Ordinary descriptive text
- **WHEN** text lacks an accepted marker or resembles a bare unbracketed marker word
- **THEN** it does not acquire that marker's constraint through speculative interpretation.

Evidence: `backend/calendar/markers.py:has_marker`, `backend/calendar/ical_mapping.py:calendar_event_constraints`, `backend/calendar/local.py:local_calendar_events`; `tests/test_calendar_markers.py:test_variants_match`, `tests/test_calendar_markers.py:test_bare_or_other_marker_does_not_match`, `tests/test_calendar_external.py:test_training_relevance_filter_keeps_no_training_blockers`.

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

### Requirement: Local authority and stored public-event projections
The system SHALL compose local planned units, competitions, linked Intervals events, and relevant external constraints without losing local dirty/conflict state to a stale provider snapshot. External feed events SHALL remain read-only constraints.

#### Scenario: Local conflict and stale remote snapshot
- **WHEN** a linked local unit is dirty or conflicted while its remote event is present
- **THEN** calendar composition preserves local sync state and one linked representation rather than marking it clean merely from remote presence.

#### Scenario: Stored candidate query
- **WHEN** public-event candidates already exist in storage
- **THEN** the query joins their source name, sorts by date/name, and clamps its limit to 1 through 500 without creating competitions or provider writes.

Detailed contract: Existing public-source/candidate query helpers SHALL preserve source names, candidate import links, dates, sorting, and bounded query limits; these stored reads SHALL not be interpreted as an implemented remote publication or automatic competition-import workflow.

Evidence: `backend/calendar/canonical.py:canonical_planned_workouts`, `backend/calendar/local.py:local_calendar_events`, `backend/calendar/public_events.py:list_candidates`; `tests/test_calendar_canonical.py:test_dirty_and_conflict_local_status_overrides_stale_remote_state`, `tests/test_calendar_local.py:test_complete_read_model_uses_explicit_inputs`, `tests/test_public_event_calendar.py:test_candidates_join_source_name_and_project_exact_fields`.
