# provider-connections Specification

## Purpose

Record the implemented connection surfaces, authentication lifecycle, safe status, and transport boundaries of supported training and environmental providers.

## Requirements

### Requirement: Supported connection surface
The system SHALL expose Garmin Connect and Wahoo as data sources and Intervals.icu as an output target according to their registry descriptors, plus Open-Meteo weather and a read-only iCalendar feed. It SHALL distinguish provider availability, configuration and an athlete connection where these are separate states. A recording-origin label such as Wahoo, Garmin, Strava, Zwift, manual or upload SHALL not by itself create a direct provider connection.

#### Scenario: Unconnected Wahoo configuration
- **WHEN** Wahoo client settings exist but the athlete has not connected an account
- **THEN** status distinguishes configured from connected and scheduled Wahoo import is ineligible.

#### Scenario: Relayed activity
- **WHEN** a Garmin Connect activity names a Wahoo or Zwift manufacturer
- **THEN** its provenance records that recording origin while transport and connection ownership remain Garmin.

Detailed contract: The current training registry contains no direct Polar, COROS, Suunto, or Strava OAuth adapter.

Evidence: `backend/providers/descriptors.py:DEFAULT_PROVIDER_DESCRIPTORS`, `backend/canonical/vocabulary.py:ProviderId`, `backend/canonical/vocabulary.py:RecordingOrigin`; `tests/test_provider_registry.py:test_capabilities_are_assigned_per_provider`, `tests/test_wahoo_connection.py:test_configured_only_with_all_three_values`, `tests/test_garmin_activity_mapping.py:test_manufacturer_names_the_recording_origin`.

### Requirement: Intervals server configuration and requests
The system SHALL keep the Intervals API key and athlete identifier in server-side configuration, construct the authenticated transport there, URL-encode provider identifiers, and reject unconfigured sync work before enqueueing. Intervals.icu is an output target: the system SHALL NOT read its activities, wellness history or athlete record, and remote writes SHALL enter their explicit domain use cases.

#### Scenario: Missing Intervals key
- **WHEN** an athlete requests an Intervals.icu synchronization without configured access
- **THEN** a safe configuration error is returned before remote access.

#### Scenario: Output only
- **WHEN** Intervals credentials are configured
- **THEN** no activity, wellness-history or athlete-record read is part of any sync; only an explicit push, its read-back (library, calendar events, the wellness day and sport settings of an export) or the explicit connection check reaches Intervals.icu.

Evidence: `backend/providers/intervals.py:IntervalsApiClient`, `backend/providers/intervals_client.py:IntervalsClient`, `backend/http_api/sync_commands.py:SyncCommandEndpoint._require_provider_configured`; `tests/test_http_sync_registry_routes.py:test_not_configured_message_rejects_manual_and_job_routes`, `tests/test_sync_jobs.py:test_every_provider_and_job_type_pair_matches_the_live_validator`.

### Requirement: Garmin login and MFA
The system SHALL support authenticated Garmin login with an optional MFA continuation, bounded text/code validation, an expiring pending MFA slot, and a bounded rejection count. A newer login, a disconnect, or the local data purge SHALL supersede the old generation so an in-flight old login cannot store a connection later. Provider errors SHALL be mapped to safe application errors rather than exposing SDK messages or login values.

#### Scenario: MFA required
- **WHEN** Garmin requires MFA after a valid login request
- **THEN** the PWA receives `mfa_required` and a later valid continuation stores the connection only if the same pending generation remains current.

#### Scenario: Superseded login result arrives
- **WHEN** a slow login returns after a disconnect or the local data purge
- **THEN** its result is rejected instead of silently reconnecting the athlete.

#### Scenario: Cancel in the PWA
- **WHEN** the athlete chooses "Abbrechen" on the code step
- **THEN** only the form returns to the login step; no route cancels the server slot, so the pending login stays until a newer login, a disconnect or the purge replaces it, or it expires after 10 minutes.

Evidence: `backend/sync/garmin_login.py:GarminLoginService.login`, `backend/sync/garmin_login.py:GarminLoginService.submit_mfa`, `backend/sync/garmin_login.py:GarminLoginService.cancel`; `tests/test_garmin_login.py:test_mfa_wrong_code_keeps_slot_then_correct_code_connects`, `tests/test_garmin_login.py:test_disconnect_during_login_discards_the_result`, `tests/test_sync_garmin_service.py:test_reader_mfa_and_cancellation_keep_collection_from_running`.

### Requirement: Garmin connection storage and safe status
The system SHALL use the Garmin token-store owner for encrypted-database token persistence and supported configured-file compatibility, keep login/token contents server-side, and expose only connected/source/MFA-pending metadata. Remote reads SHALL persist updated token state through their cleanup path even if collection fails. Disconnect SHALL discard pending login and clear the owned connection state.

#### Scenario: SDK tokens rotate during a failed read
- **WHEN** Garmin authentication succeeds but the following provider collection raises
- **THEN** cleanup still preserves updated token state without returning token material in public status.

#### Scenario: Optional SDK absent
- **WHEN** the optional Garmin client is unavailable, or none of a login configuration, a supported token store and a Personal API key is present
- **THEN** Garmin is reported unavailable or unconfigured and no data collection is attempted.

Evidence: `backend/sync/garmin_login.py:GarminTokenStore`, `backend/sync/garmin_login.py:GarminLoginService.status`, `backend/sync/garmin_service.py:GarminRemoteReader`; `tests/test_sync_garmin_service.py:test_fetch_persists_tokens_even_when_the_read_fails`, `tests/test_garmin_login.py:test_login_success_stores_tokens_without_password`, `tests/test_garmin_login.py:test_disconnect_clears_tokens_and_blocks_legacy_file`.

### Requirement: Garmin Personal API key and SDK fallback
The system SHALL read the Garmin families the official Personal API serves through it whenever a key is configured, and every other family only through the unofficial SDK login. The key is a server-side credential that the provider settings may also store. Public status SHALL expose only whether a key is set, its entered expiry date and a state, never the key.

#### Scenario: Key without SDK login
- **WHEN** a Personal API key is configured and no SDK login is connected
- **THEN** every Personal API family syncs and the SDK-only families are absent as an unsupported capability without failing the sync.

#### Scenario: SDK login skipped
- **WHEN** a key is configured and the SDK login fails or needs MFA
- **THEN** only the SDK-only families are dropped, the reason `login_failed` or `mfa_required` and its time are kept so the card asks for a new login, and the next successful SDK login clears it.

#### Scenario: Key state
- **WHEN** the athlete entered an expiry date for the key
- **THEN** the state is valid, expiring within 14 days, or expired; a missing date reads `expiry_missing`, a key Garmin refused (401 or 403 on the exchange) reads `rejected` above every expiry state, and an unreachable Garmin is no rejection.

#### Scenario: Key replaced or removed
- **WHEN** the athlete saves or removes the key
- **THEN** its stored expiry date and rejection are cleared and the environment expiry does not apply to a stored key.

Evidence: `backend/providers/garmin_personal.py:GarminTransportClient`, `backend/providers/garmin_personal.py:PERSONAL_METHODS`, `backend/sync/garmin_personal_status.py:personal_key_state`, `backend/sync/garmin_service.py:GarminRemoteReader._authenticated_client`, `backend/sync/garmin_projection_service.py:GarminProjectionService._personal_api_state`, `backend/provider_credentials.py`; `tests/test_garmin_personal_key_status.py:test_state_follows_the_entered_expiry_date`, `tests/test_garmin_personal_key_status.py:test_a_rejected_key_wins_over_every_expiry_state`, `tests/test_garmin_personal_key_status.py:test_unreachable_personal_api_is_not_a_rejection`, `tests/test_garmin_personal_key_status.py:test_saving_or_removing_the_key_clears_its_expiry`, `tests/test_garmin_personal_transport.py:test_personal_key_alone_syncs_every_personal_family_without_errors`, `tests/test_garmin_personal_transport.py:test_failed_sdk_login_keeps_the_personal_families`, `tests/test_garmin_personal_transport.py:test_pending_mfa_keeps_the_personal_families`.

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
The system SHALL export metrics only to a capable target and only automatically; no HTTP route previews or sends a manual selection. Thresholds SHALL be the resolved local, else Garmin, else Wahoo values, never the target's own. Automatic export SHALL need stored per-field consent and stay idempotent. Every write SHALL be in the change history without undo; export failure SHALL keep the local import.

#### Scenario: Automatic export after consent
- **WHEN** a successful eligible current Garmin sync completes, a local zone configuration is saved, removed or undone, or a Wahoo sync succeeds, and stored consent is enabled
- **THEN** only the consented fields transfer, with body metrics taken from Garmin measurements only; a different Intervals.icu sport setting is overwritten by the resolved threshold, heart-rate thresholds are written with `recalcHrZones=true`; a wellness target edited independently is preserved and reported as conflict, without blocking unrelated fields.

#### Scenario: Unconfirmed or failed export
- **WHEN** the request lacks named consent/confirmation or a remote write fails
- **THEN** an unauthorized request sends nothing, failures receive safe per-field results, and the imported local data is retained.

#### Scenario: Per-field consent
- **WHEN** the athlete enables the automatic export for the first time, or changes one field's consent with a confirmed request naming Intervals.icu
- **THEN** a new consent covers threshold heart rate, maximum heart rate and running threshold pace; cycling FTP, running FTP and the wellness fields are opt-in; a consent stored before per-field consent keeps the fields of that time (all but running FTP) until a field is changed; the response lists each changed field as a receipt, and revoking the last field ends the automatic export.

Evidence: `backend/sync/metric_export.py:MetricExportService.configure_automatic`, `backend/sync/metric_export.py:MetricExportService.sync_automatic`, `backend/sync/metric_export_consent.py:enabled_fields`, `backend/performance/canonical_current.py:read_export_thresholds`, `backend/sync/metric_export_runner.py:MetricExportRunner`, `backend/sync/garmin_service.py:GarminSyncService._execute`; `tests/test_metric_export.py:test_automatic_export_requires_persisted_named_consent`, `tests/test_metric_export.py:test_legacy_consent_keeps_all_fields_until_saved_per_field`, `tests/test_metric_export.py:test_new_consent_starts_with_heart_rate_and_pace_thresholds_only`, `tests/test_metric_export.py:test_a_target_side_threshold_change_is_overwritten_after_restart`, `tests/test_metric_export.py:test_heart_rate_thresholds_recalculate_target_zones`, `tests/test_metric_export.py:test_writes_are_in_the_change_history_without_undo`, `tests/test_current_thresholds.py:test_local_then_garmin_then_wahoo_and_never_intervals`, `tests/test_metric_export_runner.py`, `tests/test_sync_garmin_service.py:test_export_failure_preserves_import_and_does_not_expose_error`, `tests/metric-export.test.cjs`.

### Requirement: Explicit Wahoo library-plan export
The system SHALL export local library workouts to Wahoo only through an explicit Wahoo `plan_push` request with expected payload hashes. It SHALL serialize supported workouts before remote writes, retain Wahoo links separately from Intervals slots, verify readback, and reuse the existing remote plan or matching coach external identity on repeat export. It SHALL refuse Wahoo calendar scheduling and repair operations.

#### Scenario: Repeat selected export
- **WHEN** a selected unchanged workout already has a Wahoo link or a discoverable prior coach external identity
- **THEN** the existing plan is updated/reused rather than creating a duplicate; its Wahoo link is persisted only after supported readback verification.

#### Scenario: Explicit removal
- **WHEN** a job entry carries `remove: true` for a library workout that is gone from the local library
- **THEN** its linked Wahoo plan and link are deleted; an entry without a link reports `already_synced`, and one still in the library reports a conflict.

#### Scenario: Stale selection or mixed results
- **WHEN** a selected local payload hash changed or some selected entries cannot be mapped/written
- **THEN** those entries report conflict/error, valid entries may succeed with partial overall status, and retry scope identifies failed objects rather than resending all successful objects.

#### Scenario: Unsupported Wahoo target syntax
- **WHEN** a workout uses another sport, zones, ramps, unsupported pace units, or a relative target without its required athlete reference
- **THEN** Wahoo mapping rejects that entry; supported biking/running time or distance steps can use absolute power/HR/pace and relative FTP/max-HR/threshold-HR/threshold-speed targets with the needed header reference.

#### Scenario: Header references from resolved thresholds
- **WHEN** a library workout with relative steps is serialized for Wahoo
- **THEN** its header references are the plan sport's export thresholds (local zones, else Garmin, else Wahoo, never Intervals.icu; threshold speed from the run threshold pace), read at serialization time.

Evidence: `backend/sync/wahoo_plan_push.py:WahooPlanPushService`, `backend/sync/wahoo_workout_export.py:WahooWorkoutExport`, `backend/sync/wahoo_workout_export.py:plan_references`, `backend/providers/wahoo_plan_mapping.py:wahoo_plan`; `tests/test_wahoo_plan_mapping.py:ExportReferenceTests`, `tests/test_wahoo_plan_mapping.py:AssemblyReferenceTests`, `tests/test_wahoo_plan_push.py:test_second_push_updates_the_same_plan_without_duplicating`, `tests/test_wahoo_plan_push.py:test_a_deleted_entry_is_listed_and_its_plan_removed_on_request`, `tests/test_wahoo_plan_push.py:test_changed_workout_is_a_conflict_and_nothing_is_written`, `tests/test_wahoo_plan_push_jobs.py:test_coach_and_replanning_never_reference_the_wahoo_export`, `tests/test_wahoo_plan_mapping.py:test_zone_targets_are_rejected_instead_of_guessed`.

### Requirement: Optional Yazio configuration
The system SHALL treat Yazio as an optional read-only food source configured by server-side environment values, with the account email and password overridable from the PWA provider settings; the application client pair is a built-in constant. Stored values SHALL take precedence, clearing them SHALL restore the environment value, and Yazio SHALL be configured only when both values exist. Status SHALL report only presence and source, never a value.

#### Scenario: Stored override
- **WHEN** the athlete saves Yazio credentials in the provider settings
- **THEN** lookups use them without a restart and status reports source "db" and configured without returning any value.

#### Scenario: Incomplete configuration
- **WHEN** the email or the password is missing
- **THEN** Yazio is reported unconfigured and is never contacted.

#### Scenario: Secret handling
- **WHEN** logs, diagnostics, exports or Coach context are produced
- **THEN** Yazio credentials and tokens are absent from them.

Evidence: `backend/config.py:Config.yazio_configured`, `backend/provider_credentials.py:CREDENTIAL_FIELDS`; `tests/test_provider_credentials.py:test_yazio_needs_email_and_password_and_never_appears_in_status`, `tests/test_yazio.py`.

### Requirement: Uniform explicit provider connection checks
The system SHALL offer an explicit read-only connection check on the OpenAI, Intervals.icu, Garmin, Wahoo and Open-Meteo cards and present its last result in a line separate from configuration and synchronization state. A result SHALL describe the last check rather than promise current availability.

#### Scenario: Missing configuration
- **WHEN** the provider is not configured, or Wahoo or Garmin is not connected
- **THEN** the card reports not configured and a check makes no provider request.

#### Scenario: Configured but not checked
- **WHEN** the provider is configured and has not been checked for the current credentials
- **THEN** the card reports the connection as not checked and does not claim it is connected.

#### Scenario: Explicit check succeeds
- **WHEN** the athlete requests a check and the provider accepts the current credentials
- **THEN** the card reports success with the check time and no remote data is changed.

#### Scenario: Distinguishable failures
- **WHEN** a check is rejected, rate limited, unreachable, or the endpoint cannot answer the probe
- **THEN** the card shows the matching safe category with provider-specific recovery guidance and reveals no provider response, credential or token.

#### Scenario: Connection health is not sync freshness
- **WHEN** a sync succeeded earlier or later than a check
- **THEN** the sync label and the check result are shown separately and neither changes the other.

#### Scenario: Credentials change or restart
- **WHEN** the effective credentials of a provider change or the server restarts
- **THEN** an earlier result is not shown as current and a configured provider is reported as not checked.

#### Scenario: Result completes after a change
- **WHEN** credentials change while a check is in flight
- **THEN** the late result is discarded.

#### Scenario: Passive status
- **WHEN** the connections screen is loaded or polled, or unrelated settings are saved
- **THEN** it reads local state without any provider request and keeps existing results.

#### Scenario: Unauthorized check
- **WHEN** a check lacks an authenticated session or valid CSRF protection
- **THEN** it is rejected before any provider request.

#### Scenario: Garmin never logs in with credentials
- **WHEN** the Garmin check runs
- **THEN** it exchanges the Personal API key when one is configured and authenticates the SDK with stored tokens only; without a key or tokens it reports not configured, and it never uses e-mail and password.

#### Scenario: Intervals.icu check
- **WHEN** the athlete checks Intervals.icu
- **THEN** one athlete-endpoint request verifies the credentials and nothing from it is stored.

#### Scenario: Providers without a check
- **WHEN** the card is the shared calendar or Open Food Facts
- **THEN** no check action is offered because a check would equal the full feed fetch or the provider needs no credentials.

Evidence: `backend/providers/connection_checks.py:ProviderConnectionChecks`, `backend/providers/connection_check_probes.py:build_probes`, `backend/sync/garmin_service.py:GarminRemoteReader.check_stored_login`; `tests/test_provider_connection_checks.py`, `tests/provider-connections.test.cjs`.

### Requirement: Yazio connection status and explicit check
The system SHALL present Yazio on the connections screen, distinguish missing configuration, an unchecked configuration, a successful check, and a safely classified failure, and provide an explicit authenticated connection check. Status SHALL describe the last check rather than promise current availability.

#### Scenario: Missing configuration
- **WHEN** any required Yazio credential is absent
- **THEN** the card reports not configured and a check makes no upstream request.

#### Scenario: Configured but not checked
- **WHEN** configuration is complete but has not been checked for the current credentials
- **THEN** the card reports that the connection has not been checked and does not claim it is connected.

#### Scenario: Explicit check succeeds
- **WHEN** the athlete requests a check and Yazio accepts the current authentication
- **THEN** the card reports successful authentication and the time of the check; no food or diary record is changed.

#### Scenario: Authentication or service failure
- **WHEN** a check is rejected, rate-limited, or encounters a transient or unexpected provider failure
- **THEN** the card shows a safe actionable category and does not claim success or reveal provider responses, account values, or tokens.

#### Scenario: Credentials change or server restarts
- **WHEN** effective Yazio credentials change or the server restarts
- **THEN** an old successful result is not presented as a current verification; complete configuration is shown as unchecked.

#### Scenario: Passive status refresh
- **WHEN** the connections screen is loaded or polled
- **THEN** it reads local status without starting a Yazio network request.

#### Scenario: Unauthorized check
- **WHEN** a check request lacks an authenticated session or valid CSRF protection
- **THEN** it is rejected before contacting Yazio.

Evidence: `backend/providers/yazio.py::YazioClient.connection_status`, `backend/providers/yazio.py::YazioClient.check_connection`, `backend/http_api/nutrition.py::NutritionGetRoutes.routes`, `backend/http_api/nutrition.py::NutritionPostRoutes._check_yazio`, `public/provider-connections.js::checkYazioConnection`, `public/provider-connections.js::loadYazioStatus`; `tests/test_yazio.py::YazioConnectionTests.test_passive_status_check_and_credential_change`, `tests/test_yazio.py::YazioConnectionTests.test_check_uses_password_grant_and_restart_is_unchecked`, `tests/test_yazio.py::YazioConnectionTests.test_inflight_result_is_discarded_after_credential_replacement`, `tests/test_yazio_connection_routes.py`, `tests/provider-connections.test.cjs`, `e2e/yazio-connection.spec.js::@responsive Yazio shows a checked login and refreshes its local status`. The check reports `not_configured`, `unchecked`, `success`, `auth_failed`, `rate_limited` or `unavailable`.
