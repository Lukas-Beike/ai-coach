# provider-connections Specification

## Purpose

Record the implemented connection surfaces, authentication lifecycle, safe status, and transport boundaries of supported training and environmental providers.

## Requirements

### Requirement: Supported connection surface
The system SHALL expose training-provider integration for Intervals.icu, Garmin Connect, and Wahoo according to their registry descriptors, plus location-based Open-Meteo weather and a configured read-only iCalendar feed. It SHALL distinguish provider availability, configuration, and an athlete connection where these are separate states. A recording-origin label such as Wahoo, Garmin, Strava, Zwift, manual, or upload SHALL not by itself create a direct provider connection.

#### Scenario: Unconnected Wahoo configuration
- **WHEN** Wahoo client settings exist but the athlete has not connected an account
- **THEN** status distinguishes configured from connected and scheduled Wahoo import is ineligible.

#### Scenario: Relayed activity
- **WHEN** an Intervals activity identifies a different recording app or device
- **THEN** its provenance can identify that origin while transport and connection ownership remain Intervals.icu.

Detailed contract: The current training registry contains no direct Polar, COROS, Suunto, or Strava OAuth adapter.

Evidence: `backend/providers/descriptors.py:DEFAULT_PROVIDER_DESCRIPTORS`, `backend/canonical/vocabulary.py:ProviderId`, `backend/canonical/vocabulary.py:RecordingOrigin`; `tests/test_provider_registry.py:test_capabilities_are_assigned_per_provider`, `tests/test_wahoo_connection.py:test_configured_only_with_all_three_values`.

### Requirement: Intervals server configuration and requests
The system SHALL keep the Intervals API key and athlete identifier in server-side configuration, construct authenticated read/write transports there, URL-encode provider identifiers, and reject unconfigured sync work before enqueueing. Read sync SHALL fetch provider data without treating API availability as permission to perform remote mutations. Remote writes SHALL enter their explicit domain use cases.

#### Scenario: Missing Intervals key
- **WHEN** an athlete requests Intervals synchronization without configured access
- **THEN** a safe configuration error is returned before lock acquisition or remote access.

#### Scenario: Normal import
- **WHEN** Intervals credentials permit reading activities, wellness, and events
- **THEN** the importer reads them without uploading local workouts, competition edits, or other pending local changes merely because import ran.

Evidence: `backend/providers/intervals.py:IntervalsApiClient`, `backend/providers/intervals_client.py:IntervalsClient`, `backend/http_api/sync_commands.py:SyncCommandEndpoint._require_provider_configured`; `tests/test_sync_intervals_flow.py:test_missing_api_key_fails_before_lock_and_provider_io`, `tests/test_sync_full_resync.py:test_intervals_and_competitions_share_operation_and_never_push`.

### Requirement: Garmin login and MFA
The system SHALL support authenticated Garmin login with an optional MFA continuation, bounded text/code validation, an expiring pending MFA slot, and a bounded rejection count. A newer login, cancellation, or disconnect SHALL supersede the old generation so an in-flight old login cannot store a connection later. Provider errors SHALL be mapped to safe application errors rather than exposing SDK messages or login values.

#### Scenario: MFA required
- **WHEN** Garmin requires MFA after a valid login request
- **THEN** the PWA receives `mfa_required` and a later valid continuation stores the connection only if the same pending generation remains current.

#### Scenario: Cancelled login result arrives
- **WHEN** a slow login returns after cancellation or disconnect
- **THEN** its result is rejected instead of silently reconnecting the athlete.

Evidence: `backend/sync/garmin_login.py:GarminLoginService.login`, `backend/sync/garmin_login.py:GarminLoginService.submit_mfa`, `backend/sync/garmin_login.py:GarminLoginService.cancel`; `tests/test_garmin_login.py:test_mfa_wrong_code_keeps_slot_then_correct_code_connects`, `tests/test_garmin_login.py:test_disconnect_during_login_discards_the_result`, `tests/test_sync_garmin_service.py:test_reader_mfa_and_cancellation_keep_collection_from_running`.

### Requirement: Garmin connection storage and safe status
The system SHALL use the Garmin token-store owner for encrypted-database token persistence and supported configured-file compatibility, keep login/token contents server-side, and expose only connected/source/MFA-pending metadata. Remote reads SHALL persist updated token state through their cleanup path even if collection fails. Disconnect SHALL discard pending login and clear the owned connection state.

#### Scenario: SDK tokens rotate during a failed read
- **WHEN** Garmin authentication succeeds but the following provider collection raises
- **THEN** cleanup still preserves updated token state without returning token material in public status.

#### Scenario: Optional SDK absent
- **WHEN** the optional Garmin client is unavailable or neither login configuration nor a supported token store is present
- **THEN** Garmin is reported unavailable or unconfigured and no data collection is attempted.

Evidence: `backend/sync/garmin_login.py:GarminTokenStore`, `backend/sync/garmin_login.py:GarminLoginService.status`, `backend/sync/garmin_service.py:GarminRemoteReader`; `tests/test_sync_garmin_service.py:test_fetch_persists_tokens_even_when_the_read_fails`, `tests/test_garmin_login.py:test_login_success_stores_tokens_without_password`, `tests/test_garmin_login.py:test_disconnect_clears_tokens_and_blocks_legacy_file`.

### Requirement: Wahoo authorization state and callback
The system SHALL initiate Wahoo OAuth only through an authenticated, CSRF-protected action, require a credential-free HTTPS redirect URI without a fragment, and persist only a digest of one pending authorization state with a ten-minute expiry. The cross-site callback SHALL use that single-use state instead of requiring a session cookie, exchange a bounded code only after state validation, and redirect to fixed connected/error targets without echoing callback values.

#### Scenario: Successful cross-site callback
- **WHEN** the callback carries a valid unexpired state and a usable code
- **THEN** the server stores the grant and redirects to the fixed success location without exposing the state, code, or tokens.

#### Scenario: Foreign or expired callback
- **WHEN** state is foreign, expired, missing, or already consumed
- **THEN** no code exchange occurs; a foreign nonexpired state does not cancel the athlete's legitimate pending login.

Evidence: `backend/sync/wahoo_connection.py:WahooConnectionService.start_authorization`, `backend/sync/wahoo_connection.py:WahooConnectionService.complete_authorization`, `backend/http_api/wahoo.py:WahooGetRoutes`; `tests/test_wahoo_connection.py:test_state_is_single_use`, `tests/test_wahoo_connection.py:test_wrong_state_is_rejected_without_exchange_or_cancelling_login`, `tests/test_wahoo_http.py:test_connect_callback_without_session_and_status_without_tokens`.

### Requirement: Wahoo rotation and reconnection
The system SHALL keep Wahoo grants in SQLCipher-owned key/value storage, refresh before expiry using a five-minute margin, serialize refresh-token rotation, and reuse a token another caller already rotated. A rejected refresh with upstream 400, 401, or 422 SHALL remove the unusable grant and require reconnection; transient failure SHALL retain it. A freshly refreshed access token rejected again SHALL invalidate only that same grant.

#### Scenario: Concurrent unauthorized requests
- **WHEN** a Wahoo request reports a rejected old token after another caller has rotated it
- **THEN** the newer grant is reused rather than spending the old refresh token twice.

#### Scenario: Revoked versus temporary grant failure
- **WHEN** refreshing a grant is rejected as invalid or temporarily fails upstream
- **THEN** invalid grants require reconnect, while temporary failures retain local grant state for recovery.

Evidence: `backend/sync/wahoo_connection.py:WahooConnectionService.access_token`, `backend/sync/wahoo_connection.py:WahooConnectionService.refresh_access_token`, `backend/sync/wahoo_connection.py:WahooConnectionService._refresh`; `tests/test_wahoo_connection.py:test_refresh_rotates_and_persists_both_tokens`, `tests/test_wahoo_connection.py:test_rejected_refresh_requires_reconnect_and_drops_tokens`, `tests/test_wahoo_connection.py:test_transient_refresh_failure_keeps_tokens`.

### Requirement: Wahoo disconnect and granted scopes
The system SHALL expose token-free Wahoo configured/connected/scope/connected-at status, perform best-effort remote deauthorization on explicit disconnect, and always remove local tokens and pending state. Disconnect SHALL prevent an overlapping callback from restoring a grant.

#### Scenario: Provider revocation unavailable
- **WHEN** the athlete disconnects but remote deauthorization fails
- **THEN** local disconnect succeeds, reports `remote_revoked=false`, and a repeated disconnect remains safe.

#### Scenario: Reduced OAuth grant
- **WHEN** Wahoo grants workout access but omits a profile or power-zone scope
- **THEN** workout import proceeds and reports the skipped optional source without inventing its values.

Detailed contract: Optional profile and power-zone import SHALL run only with granted `user_read` and `power_zones_read` scopes; a 403/404 refusal SHALL skip that optional source without discarding imported workouts or previously stored optional observations.

Evidence: `backend/sync/wahoo_connection.py:connection_status`, `backend/sync/wahoo_connection.py:WahooConnectionService.disconnect`, `backend/sync/wahoo_sync.py:WahooSyncService._threshold_fetch`; `tests/test_wahoo_connection.py:test_disconnect_during_code_exchange_prevents_reconnect`, `tests/test_wahoo_connection.py:test_disconnect_succeeds_locally_when_remote_revoke_fails`, `tests/test_wahoo_sync.py:test_a_forbidden_power_zones_read_is_non_fatal_and_keeps_the_workouts`.

### Requirement: Credential-safe bounded transport
The system SHALL keep external credentials and callback values out of public status, ordinary diagnostics, exports, request-target logs, and persisted activity download links. Shared HTTP transports SHALL reject redirects rather than forwarding authenticated requests to a redirect target. Wahoo FIT downloads SHALL use an allowlisted HTTPS CDN, no authorization header, and bounded time/body size; calendar and weather SHALL use their own bounded provider transports.

#### Scenario: Authenticated provider redirect
- **WHEN** an upstream responds with a redirect to the same or a different origin
- **THEN** the shared transport rejects the redirect without replaying credentials at the new location.

#### Scenario: Untrusted FIT link
- **WHEN** a Wahoo summary contains a download link outside the accepted HTTPS host/port rules
- **THEN** the downloader refuses it before network access and returns only a safe failure class.

Evidence: `backend/providers/http.py:request_json`, `backend/providers/wahoo_fit_download.py:download_wahoo_fit`, `backend/http_api/wahoo.py:WahooGetRoutes`; `tests/test_provider_redirects.py:test_json_transport_rejects_same_and_cross_origin_redirects`, `tests/test_wahoo_http.py:test_callback_code_and_state_never_reach_logs`, `tests/test_wahoo_fit_download.py:test_request_is_a_plain_get_with_only_accept_and_user_agent`.

### Requirement: Explicit metric export and stored automatic consent
The system SHALL offer supported metric export only to a capable target, with a preview, named target, explicit confirmation, and unchanged source/target evidence at execution. Automatic Garmin-to-Intervals export SHALL require separately stored named consent, preserve independent target edits across restarts, remain idempotent, and leave HR zones unchanged. Export failure SHALL preserve successful local Garmin import.

#### Scenario: Confirmed manual metric selection
- **WHEN** selected source observations and live remote values still match a confirmed preview
- **THEN** only selected supported fields are written, previous-value/source receipts are recorded, and HR zones recalculate only when explicitly requested for supported threshold fields.

#### Scenario: Automatic export after consent
- **WHEN** a successful eligible current Garmin sync completes and stored Garmin-to-Intervals consent is enabled
- **THEN** unchanged target baselines permit eligible new values to transfer; a target edited independently is preserved and reported as conflict, without blocking unrelated fields.

#### Scenario: Unconfirmed or failed export
- **WHEN** the request lacks named consent/confirmation, preview values changed, or a remote write fails
- **THEN** unauthorized or stale selection sends nothing, failures receive safe per-field results, and the imported local Garmin data is retained.

Evidence: `backend/sync/metric_export.py:MetricExportService.export`, `backend/sync/metric_export.py:MetricExportService.configure_automatic`, `backend/sync/metric_export.py:MetricExportService.sync_garmin`, `backend/sync/garmin_service.py:GarminSyncService._execute`; `tests/test_metric_export.py:test_automatic_export_requires_persisted_named_consent`, `tests/test_metric_export.py:test_new_garmin_value_after_restart_preserves_a_manual_target_change`, `tests/test_sync_garmin_service.py:test_export_failure_preserves_import_and_does_not_expose_error`.

### Requirement: Explicit Wahoo library-plan export
The system SHALL export local library workouts to Wahoo only through an explicit Wahoo `plan_push` request with expected payload hashes. It SHALL serialize supported workouts before remote writes, retain Wahoo links separately from Intervals slots, verify readback, and reuse the existing remote plan or matching coach external identity on repeat export. It SHALL refuse Wahoo calendar scheduling and repair operations.

#### Scenario: Repeat selected export
- **WHEN** a selected unchanged workout already has a Wahoo link or a discoverable prior coach external identity
- **THEN** the existing plan is updated/reused rather than creating a duplicate; its Wahoo link is persisted only after supported readback verification.

#### Scenario: Stale selection or mixed results
- **WHEN** a selected local payload hash changed or some selected entries cannot be mapped/written
- **THEN** those entries report conflict/error, valid entries may succeed with partial overall status, and retry scope identifies failed objects rather than resending all successful objects.

#### Scenario: Unsupported Wahoo target syntax
- **WHEN** a workout uses another sport, zones, ramps, unsupported pace units, or a relative target without its required athlete reference
- **THEN** Wahoo mapping rejects that entry; supported biking/running time or distance steps can use absolute power/HR/pace and relative FTP/max-HR/threshold-HR/threshold-speed targets with the needed header reference.

Evidence: `backend/sync/wahoo_plan_push.py:WahooPlanPushService`, `backend/sync/wahoo_workout_export.py:WahooWorkoutExport`, `backend/providers/wahoo_plan_mapping.py:wahoo_plan`; `tests/test_wahoo_plan_push.py:test_second_push_updates_the_same_plan_without_duplicating`, `tests/test_wahoo_plan_push.py:test_changed_workout_is_a_conflict_and_nothing_is_written`, `tests/test_wahoo_plan_push_jobs.py:test_coach_and_replanning_never_reference_the_wahoo_export`, `tests/test_wahoo_plan_mapping.py:test_zone_targets_are_rejected_instead_of_guessed`.

### Requirement: Optional Yazio configuration
The system SHALL treat Yazio as an optional read-only food source configured by server-side environment values, with account email, password and application client identifiers overridable from the PWA provider settings. Stored values SHALL take precedence, clearing them SHALL restore the environment value, and Yazio SHALL be configured only when all four values exist. Status SHALL report only presence and source, never a value.

#### Scenario: Stored override
- **WHEN** the athlete saves Yazio credentials in the provider settings
- **THEN** lookups use them without a restart and status reports source "db" and configured without returning any value.

#### Scenario: Incomplete configuration
- **WHEN** any of email, password, client id or client secret is missing
- **THEN** Yazio is reported unconfigured and is never contacted.

#### Scenario: Secret handling
- **WHEN** logs, diagnostics, exports or Coach context are produced
- **THEN** Yazio credentials and tokens are absent from them.
