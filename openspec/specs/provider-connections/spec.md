# provider-connections Specification

## Purpose

Record the implemented connection surfaces, authentication lifecycle, safe status, and transport boundaries of supported training and environmental providers.

## Requirements

### Requirement: Supported connection surface
The system SHALL expose Garmin Connect and Wahoo as data sources and Intervals.icu as an output target according to their provider table entries, plus Open-Meteo weather and a read-only iCalendar feed. It SHALL distinguish provider availability, configuration and an athlete connection where these are separate states. A recording-origin label such as Wahoo, Garmin, Strava, Zwift, manual or upload SHALL not by itself create a direct provider connection.

#### Scenario: Unconnected Wahoo configuration
- **WHEN** Wahoo client settings exist but the athlete has not connected an account
- **THEN** status distinguishes configured from connected and scheduled Wahoo import is ineligible.

#### Scenario: Relayed activity
- **WHEN** a Garmin Connect activity names a Wahoo or Zwift manufacturer
- **THEN** its provenance records that recording origin while transport and connection ownership remain Garmin.

Detailed contract: The current training registry contains no direct Polar, COROS, Suunto, or Strava OAuth adapter.

Evidence: `backend/sync/provider_table.py:DEFAULT_PROVIDER_DESCRIPTORS`, `backend/canonical/vocabulary.py:ProviderId`, `backend/canonical/vocabulary.py:RecordingOrigin`; `tests/test_provider_registry.py:test_capabilities_are_assigned_per_provider`, `tests/test_wahoo_connection.py:test_configured_only_with_all_three_values`, `tests/test_garmin_activity_mapping.py:test_manufacturer_names_the_recording_origin`.

### Requirement: Intervals server configuration and requests
The system SHALL keep the Intervals API key and athlete identifier in server-side configuration, construct the authenticated transport there, URL-encode provider identifiers, and reject unconfigured sync work before enqueueing. Intervals.icu is an output target: the system SHALL NOT read its activities or wellness history; its only reads are those listed in docs/provider-endpoints.md, and remote writes SHALL enter their explicit domain use cases.

#### Scenario: Missing Intervals key
- **WHEN** an athlete requests an Intervals.icu synchronization without configured access
- **THEN** a safe configuration error is returned before remote access.

#### Scenario: Output only
- **WHEN** Intervals credentials are configured
- **THEN** no activity or wellness-history read is part of any sync; only an explicit push, its read-back (library, folders, calendar events), the one-day wellness and sport-settings reads of a metric export or the explicit connection check (one athlete-endpoint request) reaches Intervals.icu.

#### Scenario: Endpoint table
- **WHEN** a provider call is added, removed or changed
- **THEN** docs/provider-endpoints.md, the normative table of every outbound provider call with method and path, kind, caller, timeout, retry and error mapping, changes in the same pull request.

Evidence: `backend/providers/intervals.py:IntervalsApiClient`, `backend/providers/intervals_client.py:IntervalsClient`, `backend/http_api/sync_commands.py:SyncCommandEndpoint._require_provider_configured`; `tests/test_sync_wiring_matrix.py:test_an_unconfigured_provider_gets_409_before_any_job_is_stored`, `tests/test_sync_wiring_matrix.py:test_an_unconfigured_provider_gets_409_before_its_manual_route_stores_a_job`, `tests/test_sync_jobs.py:test_every_provider_and_job_type_pair_matches_the_live_validator`.

### Requirement: Intervals.icu connection status from output outcomes
The system SHALL project the Intervals.icu connection state from durable stamps of the last export success and the last provider failure, and an unreadable stamp SHALL be ignored.

#### Scenario: Only a round trip counts
- **WHEN** a plan, competition or nutrition push ends
- **THEN** a synced entry or completed run stamps a success and a provider failure stamps a failure; a skipped, already synced or conflicting entry, a local failure and a contended run stamp nothing.

#### Scenario: An export outlives a restart
- **WHEN** a plan push synced an entry and the server restarts or the page reloads, however long ago the push was
- **THEN** the Intervals.icu state is connected and `last_used_at` names that push, without a provider request.

#### Scenario: A provider failure after a success
- **WHEN** an output job fails with a provider answer or without a response after the last success
- **THEN** the state is error until a later export succeeds; the state is connected when the newest success is newer, and configured when there is neither.

Evidence: `backend/sync/intervals_state.py::public_state`, `backend/sync/executor.py::IntervalsJobAdapter.execute`, `backend/sync/execution_wiring.py::build_sync_job_execution`; `tests/test_intervals_state.py`, `tests/test_sync_executor.py::ProviderJobAdapterTests.test_intervals_output_leaves_a_stamp_only_for_a_real_round_trip`, `tests/test_sync_executor.py::ProviderJobAdapterTests.test_only_a_provider_failure_leaves_a_failed_stamp`, `tests/test_server_http.py::ServerHttpTests.test_intervals_public_state_follows_the_output_stamps`.

### Requirement: Intervals.icu request contract
The system SHALL call Intervals.icu only at `https://intervals.icu/api/v1`, with basic authentication (user `API_KEY`, password the stored key), and only for the explicit writes and read-backs of its output role. Collection reads SHALL page with `limit` 500 and an offset, read at most 100 pages, and fail on a page that is no list of objects or that repeats an earlier non-empty page.

#### Scenario: Library workout without a stored remote id
- **WHEN** a library workout is pushed and no remote id is stored, or the stored one answers 404
- **THEN** the remote library is listed first and a matching workout is adopted; only without a match a workout is created in the folder `Pacecraft`, an existing folder `Intervals Coach` is reused, and the folder is created when neither exists.

Detailed contract: the writes are workout folders, library workouts, planned events and competitions (bulk upsert by external id, single and bulk delete), the wellness day and the Ride and Run sport settings; the read-backs are the library workouts and folders, the events (competition push: today-365 to today+730; repair: its repair window), one event, the wellness day (404 means empty) and the sport settings; the connection check reads the athlete. No activity path and no wellness range is called. The call table belongs to the provider endpoint reference, not to this capability.

Evidence: `backend/providers/intervals.py:IntervalsApiClient`, `backend/providers/intervals.py:fetch_paged_collection`, `backend/providers/intervals_client.py:IntervalsClient`, `backend/sync/library.py:WorkoutLibrarySyncService._upsert_remote`; `tests/test_provider_intervals.py:test_pagination_page_limit_is_bounded`, `tests/test_server_sync.py:test_intervals_collection_rejects_repeated_full_page`, `tests/test_server_sync.py:test_pacecraft_folder_wins_over_the_legacy_folder`, `tests/test_server_sync.py:test_library_sync_reconciles_remote_template_before_creating`.

### Requirement: Stored provider credentials
The system SHALL store provider credentials from `PUT /api/settings/credentials` in the encrypted database for a fixed set of fields, let a non-empty stored value override the environment value, let a blank or `null` value remove only the stored one, validate the whole submission before writing, and apply changes without a restart. The fields, limits and errors are the contract of `docs/api-routes.md`.

#### Scenario: Validation before any write
- **WHEN** the body is no object, names an unknown field, or a value is no string, is longer than 4096 characters, holds a control character, is an unsafe base URL or, for the key expiry, no ISO date
- **THEN** the answer is 400 and nothing is stored.

#### Scenario: Clearing
- **WHEN** a field is `null` or blank
- **THEN** only the value stored in the app is removed and the environment value applies again.

#### Scenario: Answer
- **WHEN** a write succeeds
- **THEN** the answer is the credential status: per field its `source` (`db`, `env`, `none`) and `configured`, a `value` only for the base URLs, the athlete id, the Wahoo client id and the key expiry, and the Garmin connection; no secret, e-mail address or submitted value is returned and the write is not recorded in the change history.

#### Scenario: Applies without a restart
- **WHEN** Intervals.icu or Garmin credentials are saved or removed
- **THEN** the next job of that provider uses the live values, because its job owner is built per job.

Evidence: `backend/provider_credentials.py:validated_changes`, `backend/provider_credentials.py:CREDENTIAL_FIELDS`, `backend/provider_credentials.py:ProviderCredentialService.update`, `backend/provider_credentials.py:credential_status`, `backend/http_api/credentials_put.py:CredentialsPutRoutes`, `backend/sync/executor.py:PerJobOwner`; `tests/test_provider_credentials.py`, `tests/test_sync_live_credentials.py:test_builds_a_fresh_owner_for_every_job`.

### Requirement: Password re-entry for redirecting credentials
Setting, not clearing, `openai_base_url`, `anthropic_base_url`, `wahoo_client_id` or `wahoo_client_secret` SHALL require the APP_PASSWORD again in the body field `app_password`, compared in constant time before anything is written and never stored. A session alone SHALL NOT redirect a model key or replace the Wahoo application.

#### Scenario: Wrong or missing password
- **WHEN** the password is absent or wrong
- **THEN** the answer is 403 "Das App-Passwort fehlt oder ist falsch. Es wurde nichts geändert." and no field of the submission is stored.

#### Scenario: Too many attempts
- **WHEN** a client address makes more than 10 re-entries in 900 seconds
- **THEN** the answer is 429 `rate_limited` with the seconds to wait, the limit of the authentication capability.

Evidence: `backend/provider_credentials.py:requires_password`, `backend/provider_credentials.py:REAUTH_FIELDS`, `backend/http_api/credentials_put.py:CredentialsPutRoutes`, `backend/http_api/auth.py:SessionAuthService.require_password`; `tests/test_provider_credentials.py`, `tests/test_http_post_maintenance_reauth.py`, `e2e/credential-password.spec.js`.

### Requirement: Garmin login and MFA
The system SHALL support authenticated Garmin login with an optional MFA continuation, bounded text/code validation, an expiring pending MFA slot, and a bounded rejection count. A newer login, a disconnect, or the local data purge SHALL supersede the old generation so an in-flight old login cannot store a connection later. Provider errors SHALL be mapped to safe application errors rather than exposing SDK messages or login values.

#### Scenario: MFA required
- **WHEN** Garmin requires MFA after a valid login request
- **THEN** the PWA receives `mfa_required` and a later valid continuation stores the connection only if the same pending generation remains current.

#### Scenario: Superseded login result arrives
- **WHEN** a slow login returns after a disconnect or the local data purge
- **THEN** its result is rejected instead of silently reconnecting the athlete.

#### Scenario: Fifth wrong code
- **WHEN** a wrong code is submitted for a pending login
- **THEN** the answer is 422 and the login stays pending, except the fifth wrong code, which discards it and answers 409 "Zu viele falsche MFA-Codes. Bitte die Garmin-Anmeldung neu starten."

#### Scenario: Cancel in the PWA
- **WHEN** the athlete chooses "Abbrechen" on the code step
- **THEN** only the form returns to the login step; no route cancels the server slot, so the pending login stays until a newer login, a disconnect or the purge replaces it, or it expires after 10 minutes.

Detailed contract: one pending MFA login exists at a time and expires 600 seconds after the challenge; `email` and `password` are non-blank strings of at most 512 characters, the MFA `code` has 4 to 10 digits, and the password is never stored. The answers and their German texts are the contract of `docs/api-routes.md`.

Evidence: `backend/sync/garmin_login.py:GarminLoginService.login`, `backend/sync/garmin_login.py:GarminLoginService.submit_mfa`, `backend/sync/garmin_login.py:GarminLoginService.cancel`, `backend/sync/garmin_login.py:MFA_TTL_SECONDS`, `backend/sync/garmin_login.py:MAX_MFA_ATTEMPTS`; `tests/test_garmin_login.py:test_mfa_wrong_code_keeps_slot_then_correct_code_connects`, `tests/test_garmin_login.py:test_disconnect_during_login_discards_the_result`, `tests/test_sync_garmin_service.py:test_reader_mfa_and_cancellation_keep_collection_from_running`.

### Requirement: Garmin connection storage and safe status
The system SHALL use the Garmin token-store owner for encrypted-database token persistence and supported configured-file compatibility, keep login/token contents server-side, and expose only connected/source/MFA-pending metadata. Remote reads SHALL persist updated token state through their cleanup path even if collection fails. Disconnect SHALL discard pending login and clear the owned connection state.

#### Scenario: SDK tokens rotate during a failed read
- **WHEN** Garmin authentication succeeds but the following provider collection raises
- **THEN** cleanup still preserves updated token state without returning token material in public status.

#### Scenario: Optional SDK absent
- **WHEN** the optional Garmin client is unavailable, or none of a login configuration, a supported token store and a Personal API key is present
- **THEN** Garmin is reported unavailable or unconfigured and no data collection is attempted.

#### Scenario: Login sources
- **WHEN** the sync needs the Garmin login
- **THEN** it uses the login stored in the encrypted database, else a preserved legacy token file, else the environment e-mail and password; the reported source is `db`, `file`, `env` or `none`, and only `db` and `file` count as connected.

#### Scenario: One-time import and refresh
- **WHEN** a sync logged in from the legacy file or received refreshed login data
- **THEN** the data is written to the database only while the stored login is still the one the sync started with, so a disconnect, purge or new login during the sync is never undone; the file stays in place.

#### Scenario: After disconnect
- **WHEN** the athlete disconnected Garmin
- **THEN** the stored login is deleted and neither the legacy file nor the environment e-mail and password are used until a new login in the app, so Garmin counts as configured only through a Personal API key.

Evidence: `backend/sync/garmin_login.py:GarminTokenStore`, `backend/sync/garmin_login.py:GarminTokenStore.write_back`, `backend/sync/garmin_service.py:_garmin_sync_configured`, `backend/sync/garmin_login.py:GarminLoginService.status`, `backend/sync/garmin_service.py:GarminRemoteReader`; `tests/test_sync_garmin_service.py:test_fetch_persists_tokens_even_when_the_read_fails`, `tests/test_garmin_login.py:test_login_success_stores_tokens_without_password`, `tests/test_garmin_login.py:test_disconnect_clears_tokens_and_blocks_legacy_file`.

### Requirement: Garmin Personal API key and SDK fallback
The system SHALL read the Garmin families the official Personal API serves through it whenever a key is configured, and every other family only through the unofficial SDK login. The key is a server-side credential that the provider settings may also store. Public status SHALL expose only whether a key is set, its entered expiry date and a state, never the key.

#### Scenario: Key without SDK login
- **WHEN** a Personal API key is configured and no SDK login is connected
- **THEN** every Personal API family syncs and the SDK-only families are absent as an unsupported capability without failing the sync.

#### Scenario: SDK login skipped
- **WHEN** a key is configured and the SDK login fails or needs MFA
- **THEN** only the SDK-only families are dropped, the reason `login_failed` or `mfa_required` and its time are kept so the card asks for a new login, and the next successful SDK login clears it.

#### Scenario: SDK threshold reads fail
- **WHEN** an SDK login is configured and the reads of cycling FTP, FTP history or lactate threshold failed in three syncs in a row
- **THEN** the sync reports `requests_failed` with its time, like `login_failed` and `mfa_required`, and one successful threshold read clears the count; without an SDK setup or in fixture mode nothing is reported.

#### Scenario: One token for the process
- **WHEN** several jobs read through the Personal API with the same key
- **THEN** they share one client and one token exchange, and a changed key builds a new client.

#### Scenario: History walks never log the SDK in
- **WHEN** the wellness or stream backfill runs with a key
- **THEN** it reads through the Personal API alone and records no skipped SDK login; the stream backfill without a key reads nothing.

#### Scenario: Key check answers
- **WHEN** the key exchange is refused with 401 or 403, or gives no usable answer
- **THEN** the check fails with 401 `personal_key_rejected` "Der Garmin-Personal-API-Schlüssel wurde abgelehnt." or with 502 "Garmin Personal API nicht erreichbar."

#### Scenario: Key state
- **WHEN** the athlete entered an expiry date for the key
- **THEN** the state is valid, expiring within 14 days, or expired; a missing date reads `expiry_missing`, a key Garmin refused (401 or 403 on the exchange) reads `rejected` above every expiry state, and an unreachable Garmin is no rejection.

#### Scenario: Key replaced or removed
- **WHEN** the athlete saves or removes the key
- **THEN** its stored expiry date and rejection are cleared and the environment expiry does not apply to a stored key.

Detailed contract (transport): the key is exchanged with `Authorization: ApiKey <key>` for a bearer token that is kept in memory until 600 seconds before its own expiry claim (else 24 hours) and exchanged once more after a 401. A request times out after 45 seconds and an answer above 10 MB is refused; an activity file may reach 50 MB and is a bare FIT file or the first `.fit` member of a zip, and a 404 or another format means no file. Activity lists come in pages of 20 and at most 500 pages, and sleep, daily-summary and Body Battery ranges in requests of at most 31 days. The method table belongs to the provider endpoint reference.

Evidence:
- `backend/provider_credentials.py`
- `backend/providers/garmin_personal.py:fit_from_archive`
- `backend/providers/garmin_personal.py:GarminPersonalClient`
- `backend/providers/garmin_personal.py:GarminTransportClient`
- `backend/providers/garmin_personal.py:PERSONAL_METHODS`
- `backend/sync/garmin.py:GarminSyncStateService.sdk_threshold_failure`
- `backend/sync/garmin_personal_status.py:personal_key_state`
- `backend/sync/garmin_projection_service.py:GarminProjectionService._personal_api_state`
- `backend/sync/garmin_service.py:_verify_personal_key`
- `backend/sync/garmin_service.py:GarminRemoteReader._authenticated_client`
- `backend/sync/garmin_service.py:GarminRemoteReader.personal_client`
- `tests/test_garmin_personal_key_status.py:test_a_rejected_key_wins_over_every_expiry_state`
- `tests/test_garmin_personal_key_status.py:test_saving_or_removing_the_key_clears_its_expiry`
- `tests/test_garmin_personal_key_status.py:test_state_follows_the_entered_expiry_date`
- `tests/test_garmin_personal_key_status.py:test_unreachable_personal_api_is_not_a_rejection`
- `tests/test_garmin_personal_only_batches.py:test_two_personal_only_jobs_exchange_the_key_once`
- `tests/test_garmin_personal_transport.py:test_bare_fit_is_accepted_and_other_archives_are_rejected`
- `tests/test_garmin_personal_transport.py:test_failed_sdk_login_keeps_the_personal_families`
- `tests/test_garmin_personal_transport.py:test_pending_mfa_keeps_the_personal_families`
- `tests/test_garmin_personal_transport.py:test_personal_key_alone_syncs_every_personal_family_without_errors`
- `tests/test_garmin_personal_transport.py:test_ranges_are_split_into_the_personal_api_day_limits`
- `tests/test_sync_garmin.py:test_sdk_threshold_failure_counts_syncs_in_a_row`
- `tests/test_sync_garmin.py:test_skipped_sdk_login_freezes_thresholds_at_once`

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

### Requirement: Wahoo transport contract
The system SHALL request the Wahoo scopes `user_read`, `workouts_read`, `workouts_write`, `plans_read`, `plans_write` and `power_zones_read`, send token requests form-encoded with a 20-second timeout and API requests with a bearer token and a 30-second timeout, and map every Wahoo failure to a typed error without provider text.

#### Scenario: Rejected access token
- **WHEN** Wahoo answers 401
- **THEN** the token is refreshed once and the request repeated once; a second 401 drops the grant and raises 409 `wahoo_reconnect_required`.

#### Scenario: Other failures
- **WHEN** Wahoo answers 429, 408 or 5xx, another 4xx, or an unreadable body
- **THEN** the error is 429 `wahoo_rate_limited` (with the wait Wahoo named), 503 `wahoo_unavailable`, 502 `wahoo_request_rejected` or 502 `wahoo_invalid_response`; a transport failure without an upstream status keeps its safe text under the reason `wahoo_request_failed` when it has none.

#### Scenario: Workout list completeness
- **WHEN** the workouts are listed
- **THEN** the list is complete when a page reaches before the window start, or a page shorter than the page size Wahoo applied (1 to 50) arrives and the rows read reach Wahoo's `total`, and it is truncated when an empty page arrives below `total` or the page bound is reached; rows that are no objects are counted as skipped and a row without a readable start is kept.

#### Scenario: Plan upload
- **WHEN** a plan is written
- **THEN** it is sent form-encoded as `plan[file]` (a `data:application/json;base64,` URI of the compact plan JSON), `plan[filename]` and `plan[provider_updated_at]` (UTC), plus `plan[external_id]` on create, and remote ids must be integers from 1 to 2^63-1.

Detailed contract: the callback `state` and `code` are refused above 2048 characters and the callback always answers 302 to `/?wahoo=connected` or `/?wahoo=error`; the endpoint paths belong to the provider endpoint reference, the route answers to `docs/api-routes.md`.

Evidence: `backend/providers/wahoo_oauth.py:WAHOO_SCOPES`, `backend/providers/wahoo_oauth.py:WahooOAuthClient`, `backend/providers/wahoo_client.py:WahooClient`, `backend/providers/wahoo_client.py:_translated`, `backend/providers/wahoo_client.py:_plan_fields`, `backend/http_api/wahoo.py:WahooGetRoutes`; `tests/test_wahoo_client.py:test_a_short_page_below_the_reported_total_continues_paging`, `tests/test_wahoo_client.py:test_an_empty_page_below_the_reported_total_is_truncated`, `tests/test_wahoo_client_plans.py:test_create_posts_a_form_with_the_base64_plan_and_external_id`, `tests/test_wahoo_connection.py`, `tests/test_wahoo_http.py`.

### Requirement: Credential-safe bounded transport
The system SHALL keep external credentials and callback values out of public status, ordinary diagnostics, exports, request-target logs, and persisted activity download links. Provider transports SHALL reject redirects rather than forwarding authenticated requests to a redirect target. Wahoo FIT downloads SHALL use an allowlisted HTTPS CDN, no authorization header, and bounded time/body size; the calendar feed SHALL use its own bounded transport and weather the shared one.

#### Scenario: Authenticated provider redirect
- **WHEN** an upstream responds with a redirect to the same or a different origin
- **THEN** the shared transport rejects the redirect without replaying credentials at the new location.

#### Scenario: Untrusted FIT link
- **WHEN** a Wahoo summary contains a download link outside the accepted HTTPS host/port rules
- **THEN** the downloader refuses it before network access and returns only a safe failure class.

#### Scenario: Shared limits
- **WHEN** a JSON provider request is sent without its own limits
- **THEN** it carries `Accept: application/json` and `User-Agent: Pacecraft/<version>`, times out after 45 seconds, is not retried, returns null for an empty answer, and an answer above 10,000,000 bytes is refused with 502 "Die Antwort des externen Dienstes ist zu groß."

#### Scenario: Cancelled request
- **WHEN** the caller's cancel signal is set before, during or after the request
- **THEN** the request ends with 499 `chat_cancelled` and is not counted as a provider failure.

#### Scenario: Intervals.icu rejection text
- **WHEN** Intervals.icu rejects a request with an error body
- **THEN** the message is "Intervals.icu weist die Anfrage zurück (<status>): <detail>", where the detail is the first of `error`, `error.message|detail|title` and `message|detail|title`, redacted and cut to 500 characters; any other provider error without a classified mapping gets "Anfrage an externen Dienst fehlgeschlagen (<status>).", and the status is kept as the upstream status.

Detailed contract: redaction replaces URLs, e-mail addresses, `sk-` keys and `authorization: basic|bearer` values. The public status of an upstream error is the contract of the authentication capability.

Evidence: `backend/providers/http.py:request_json`, `backend/providers/http.py:JsonHttpClient.request`, `backend/providers/http.py:redact_provider_text`, `backend/providers/http.py:error_detail`, `tests/test_provider_http.py:test_json_http_client_maps_size_invalid_network_and_client_errors`, `tests/test_provider_http.py:test_json_http_client_cancellation_and_cleanup`, `tests/test_server_sync.py:test_intervals_validation_error_includes_safe_provider_detail`, `backend/providers/wahoo_fit_download.py:download_wahoo_fit`, `backend/http_api/wahoo.py:WahooGetRoutes`; `tests/test_provider_redirects.py:test_json_transport_rejects_same_and_cross_origin_redirects`, `tests/test_wahoo_http.py:test_callback_code_and_state_never_reach_logs`, `tests/test_wahoo_fit_download.py:test_request_is_a_plain_get_with_only_accept_and_user_agent`.

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

#### Scenario: Offered values
- **WHEN** the automatic export builds its candidates
- **THEN** body metrics are the newest Garmin observation per field of the last 90 days, values are compared with a relative tolerance of 0.001 and sent rounded (weight 2 decimals, body fat 1, threshold pace 4, others whole numbers).

#### Scenario: Delayed automatic run
- **WHEN** a local zone change or a finished Wahoo refresh asks for the automatic export
- **THEN** one run starts 5 seconds later off the request thread, a request during a run causes exactly one more run, and the status line "Intervals.icu: <n> Werte gesendet, <n> Konflikte, <n> fehlgeschlagen." is stored.

Evidence:
- `backend/performance/canonical_current.py:read_export_thresholds`
- `backend/sync/garmin_service.py:GarminSyncService._execute`
- `backend/sync/intervals_metric_export.py:_remote_number`
- `backend/sync/metric_export.py:MetricExportService._candidates`
- `backend/sync/metric_export.py:MetricExportService.configure_automatic`
- `backend/sync/metric_export.py:MetricExportService.sync_automatic`
- `backend/sync/metric_export_consent.py:enabled_fields`
- `backend/sync/metric_export_runner.py:MetricExportRunner.request`
- `backend/sync/metric_export_runner.py:MetricExportRunner`
- `tests/metric-export.test.cjs`
- `tests/test_current_thresholds.py:test_local_then_garmin_then_wahoo_and_never_intervals`
- `tests/test_metric_export.py:test_a_target_side_threshold_change_is_overwritten_after_restart`
- `tests/test_metric_export.py:test_automatic_export_requires_persisted_named_consent`
- `tests/test_metric_export.py:test_heart_rate_thresholds_recalculate_target_zones`
- `tests/test_metric_export.py:test_legacy_consent_keeps_all_fields_until_saved_per_field`
- `tests/test_metric_export.py:test_new_consent_starts_with_heart_rate_and_pace_thresholds_only`
- `tests/test_metric_export.py:test_writes_are_in_the_change_history_without_undo`
- `tests/test_metric_export_runner.py`
- `tests/test_sync_garmin_service.py:test_export_failure_preserves_import_and_does_not_expose_error`

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

#### Scenario: Plan document and identity
- **WHEN** a ride or run library workout is serialized
- **THEN** it becomes a plan document of schema version `1.0.0` under the external id `coach-library-<local_id>` and the filename `<external id>.json`: `header` holds `name` (at most 200 characters, default "Coach-Einheit"), `version`, `workout_type_family` (0 ride, 1 run), `workout_type_location` (0 indoor or virtual, 1 otherwise), the known references `ftp`, `max_hr`, `threshold_hr` and `threshold_speed`, and `description` (at most 5000 characters); `intervals` holds one entry per step `{intensity_type: "active", exit_trigger_type: "time" or "distance", exit_trigger_value, targets: [{type, low, high}]}` with `type` `watts`, `hr`, `speed` (m/s) or the relative `ftp`, `max_hr`, `threshold_hr`, `threshold_speed` as fractions.

#### Scenario: Update, recreate and baseline
- **WHEN** a workout is pushed again
- **THEN** its plan is updated by the stored link, a 404 on update creates the plan again, and without a link an earlier upload is found by its external id in the plan list; the link stores a SHA-256 baseline of the plan in which a header reference counts only when a step uses it, so a moved FTP does not change an absolute-only plan.

#### Scenario: Request errors
- **WHEN** a request carries `repair`, or Wahoo is not connected
- **THEN** the job fails with 400 `invalid_job_request` or 409 `not_configured`; an unsupported workout is 422 `wahoo_plan_unsupported` with a text that names the step, an entry error is isolated with a redacted text of at most 500 characters, and a reconnect-required error ends the whole run.

Evidence: `backend/providers/wahoo_plan_mapping.py:comparable_plan`, `backend/sync/wahoo_plan_push.py:plan_baseline`, `backend/sync/wahoo_plan_push.py:WahooPlanPushService`, `backend/sync/wahoo_workout_export.py:WahooWorkoutExport`, `backend/sync/wahoo_workout_export.py:plan_references`, `backend/providers/wahoo_plan_mapping.py:wahoo_plan`; `tests/test_wahoo_plan_mapping.py:ExportReferenceTests`, `tests/test_wahoo_plan_mapping.py:AssemblyReferenceTests`, `tests/test_wahoo_plan_mapping.py:test_every_error_is_an_app_error_with_a_stable_reason`, `tests/test_wahoo_plan_push.py:test_second_push_updates_the_same_plan_without_duplicating`, `tests/test_wahoo_plan_push.py:test_a_deleted_entry_is_listed_and_its_plan_removed_on_request`, `tests/test_wahoo_plan_push.py:test_changed_workout_is_a_conflict_and_nothing_is_written`, `tests/test_wahoo_plan_push_jobs.py:test_coach_and_replanning_never_reference_the_wahoo_export`, `tests/test_wahoo_plan_mapping.py:test_zone_targets_are_rejected_instead_of_guessed`.

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

#### Scenario: Probe per provider
- **WHEN** a check runs
- **THEN** it sends one request with a 15-second timeout: OpenAI and Claude list their models (404, 405 or 501 means `unsupported`), Intervals.icu reads the athlete (404 means `misconfigured`), Wahoo reads the user (a grant without `user_read` means `scope_missing` without a request), and Open-Meteo reads a forecast for fixed public coordinates.

#### Scenario: Classification
- **WHEN** the provider answers 429; 401 or 403; another 4xx except 408; or cannot be reached
- **THEN** the result is `rate_limited`, `auth_failed`, `misconfigured` or `unavailable`; a local failure is `unknown`, shown neither as an outage nor stored.

#### Scenario: Slow or repeated check
- **WHEN** a check runs longer than 45 seconds, or the same check is requested again within 10 seconds of a stored success, rejection, rate limit, misconfiguration, unsupported or missing-scope result
- **THEN** the answer is `checking` while the late result is still stored, or the stored result without a new request; an `unavailable` or `unknown` result is always retried.

#### Scenario: Garmin busy or fixture
- **WHEN** a Garmin sync or full resync runs, or the Garmin fixture is active
- **THEN** the result is `busy` (the earlier result is kept) or `unsupported`.

#### Scenario: Interrupted by a restore
- **WHEN** a restore or privacy delete interrupts a check
- **THEN** it reports `unknown` and stores nothing.

Detailed contract: the route answers and the twelve statuses are the contract of `docs/api-routes.md`; results live in memory and are bound to a fingerprint of the effective credentials (Garmin: connection, login digest and key; Wahoo: client id, secret and connection time).

Evidence:
- `backend/providers/connection_check_probes.py:build_probes`
- `backend/providers/connection_checks.py:classify_failure`
- `backend/providers/connection_checks.py:ProviderConnectionChecks`
- `backend/sync/garmin_wiring.py:build_garmin`
- `backend/sync/garmin_service.py:GarminRemoteReader.check_stored_login`
- `tests/provider-connections.test.cjs`
- `tests/test_provider_connection_checks.py:test_a_check_past_its_deadline_reports_checking_and_still_stores_its_result`
- `tests/test_provider_connection_checks.py:test_local_failure_is_not_reported_as_a_provider_outage_and_not_stored`
- `tests/test_provider_connection_checks.py:test_model_provider_listing_failures_are_classified`
- `tests/test_provider_connection_checks.py:test_other_provider_404_is_a_misconfiguration_not_unsupported`
- `tests/test_provider_connection_checks.py:test_restore_during_the_check_is_not_stored_as_verified`
- `tests/test_provider_connection_checks.py:test_running_resync_reports_busy_and_skips_the_login`
- `tests/test_provider_connection_checks.py:test_unknown_intervals_athlete_is_a_misconfiguration`
- `tests/test_provider_connection_checks.py`

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

#### Scenario: A food lookup counts as a check
- **WHEN** a food search or product read gets an HTTP answer from Yazio with the current credentials
- **THEN** the passive status reports its outcome as the last check, `success` when Yazio accepted the login and the safe failure category otherwise, without a separate button press; a local rate limit or login pause never changes it.

#### Scenario: Credentials change or server restarts
- **WHEN** effective Yazio credentials change or the server restarts
- **THEN** an old successful result is not presented as a current verification; complete configuration is shown as unchecked.

#### Scenario: Passive status refresh
- **WHEN** the connections screen is loaded or polled
- **THEN** it reads local status without starting a Yazio network request.

#### Scenario: Unauthorized check
- **WHEN** a check request lacks an authenticated session or valid CSRF protection
- **THEN** it is rejected before contacting Yazio.

Evidence: `backend/providers/yazio.py::YazioClient.connection_status`, `backend/providers/yazio.py::YazioClient.check_connection`, `backend/http_api/nutrition.py::NutritionGetRoutes.routes`, `backend/http_api/nutrition.py::NutritionPostRoutes._check_yazio`, `public/provider-connections.js::checkYazioConnection`, `public/provider-connections.js::loadYazioStatus`; `tests/test_yazio.py::YazioConnectionTests.test_passive_status_check_and_credential_change`, `tests/test_yazio.py::YazioConnectionTests.test_check_uses_password_grant_and_restart_is_unchecked`, `tests/test_yazio.py::YazioConnectionTests.test_inflight_result_is_discarded_after_credential_replacement`, `tests/test_yazio.py::YazioConnectionTests.test_lookup_outcomes_become_the_last_check_without_a_button_press`, `tests/test_yazio_connection_routes.py`, `tests/provider-connections.test.cjs`, `e2e/yazio-connection.spec.js::@responsive Yazio shows a checked login and refreshes its local status`. The check reports `not_configured`, `unchecked`, `success`, `auth_failed`, `rate_limited` or `unavailable`.

### Requirement: Optional Anthropic configuration
The system SHALL accept an Anthropic API key and base URL from server-side environment values, overridable from the PWA and stored encrypted. Stored values SHALL take precedence and clearing them SHALL restore the environment value. The base URL SHALL default to the official endpoint and be validated like the OpenAI base URL; setting it SHALL need the app password. Status SHALL report the key's presence and source only, never its value.

#### Scenario: Stored override
- **WHEN** the athlete saves an Anthropic API key in the Claude (Anthropic) card
- **THEN** it takes effect without a restart and status reports source "db" and configured without returning the key.

#### Scenario: Default and environment base URL
- **WHEN** no base URL is stored or set in the environment
- **THEN** the official Anthropic endpoint is used; an environment value applies when nothing is stored.

#### Scenario: Unsafe base URL
- **WHEN** a base URL uses plain HTTP to a non-loopback host or carries credentials, a query, a fragment or dot segments
- **THEN** the save is rejected without writing, and an invalid stored value is ignored at load in favor of the environment value.

#### Scenario: Base URL needs the app password
- **WHEN** the athlete sets the base URL without the app password
- **THEN** the save is rejected without writing.

#### Scenario: Secret handling
- **WHEN** logs, diagnostics, exports, browser state or Coach context are produced
- **THEN** the Anthropic API key is absent from them.

Evidence: `backend/config.py:load_config`, `backend/config.py:validated_base_url`, `backend/provider_credentials.py:SECRET_FIELDS`, `backend/provider_credentials.py:REAUTH_FIELDS`, `backend/observability.py:config_secret_values`; `tests/test_provider_credentials.py`, `tests/test_config.py`, `tests/test_observability.py`.

### Requirement: Anthropic connection check
The system SHALL offer the explicit read-only connection check of the uniform provider checks on the Claude (Anthropic) card. The check SHALL send one model-listing request with the configured key and base URL, store nothing from the answer, and report rejected credentials with guidance to check the key and base URL.

#### Scenario: Check without a key
- **WHEN** no Anthropic API key is configured
- **THEN** the card reports not configured and a check makes no provider request.

#### Scenario: Check succeeds
- **WHEN** the athlete checks the card and Anthropic accepts the key
- **THEN** the card reports success with the check time and nothing from the answer is stored.

#### Scenario: Rejected key or unsupported endpoint
- **WHEN** the key is rejected, or a compatible endpoint does not implement the model listing
- **THEN** the card shows the safe failure category with key and base URL guidance, or reports that the endpoint does not support the check.

Evidence: `backend/providers/connection_check_probes.py:build_probes`, `public/index.html` (`connection-anthropic`), `public/provider-connections.js:CREDENTIAL_FORMS`; `tests/test_provider_connection_checks.py`, `tests/provider-connections.test.cjs`.

### Requirement: Connection status in the PWA

A configured provider SHALL ask for manual attention when its error is `auth_required` or `invalid_configuration`, or its state is error, stale or partial without a retry in the future; a busy local database SHALL never count. The freshness list SHALL name each state ("Frisch", "Teilweise erfolgreich", "Veraltet, aber nutzbar", "Wird aktualisiert", "Fehler", "Noch nie geladen", "Nicht konfiguriert").

#### Scenario: Retry
- **WHEN** a configured provider is in error or stale
- **THEN** "Erneut versuchen" starts that provider's normal sync

#### Scenario: Connection check
- **WHEN** "Verbindung prüfen" is used
- **THEN** `POST /api/providers/{id}/check` runs with a 60-second deadline; while the server reports `checking` the status is read every 3 seconds, at most 200 times and only while the section is visible; a `busy` or `checking` answer keeps the earlier result

Evidence: `public/sync-status.js::providerRequiresManualAttention`; `public/sync-status.js::renderProviderFreshness`; `public/provider-checks.js::checkProviderConnection`; `public/provider-checks.js::readProviderChecks`. Tests: `tests/sync-actions.test.cjs::a busy local database never asks for manual attention`; `tests/provider-checks.test.cjs::a concurrent-check or busy answer does not replace the stored result`.

### Requirement: Credential and connection cards in the PWA

Each credential field SHALL state its source ("In der App gespeichert", "Aus Umgebung", "Nicht gesetzt"), show its current value only for the base URLs of OpenAI and Anthropic, the Intervals.icu athlete id, the Wahoo client id and the Garmin key expiry, and offer "Entfernen" only for a value stored in the app.

#### Scenario: Garmin login
- **WHEN** the login answers `mfa_required`, or the code step answers 409
- **THEN** the code form is shown, or the login form returns with the server message; both requests use a 55-second deadline

#### Scenario: Full resync
- **WHEN** a full resync is confirmed (for Garmin after typing the provider name)
- **THEN** the client posts `{confirm: "FULL_RESYNC"}`, reads the state every second, ends tracking after five failed reads in a row with "Der Resync-Status ist nicht erreichbar. Er läuft auf dem Server weiter.", and a page opened during a run follows it

#### Scenario: Wahoo return
- **WHEN** the page opens with `?wahoo=connected` or `?wahoo=error`
- **THEN** the outcome is announced once and removed from the address, and Anbindungen is shown unless the address names a route

#### Scenario: Garmin period
- **WHEN** "Garmin synchronisieren" is used
- **THEN** the day count of the field (-1 to 90, default 84) is sent as `days`

Evidence: `public/provider-connections.js::credentialSourceView`; `public/provider-connections.js::submitGarminLogin`; `public/provider-connections.js::submitGarminMfa`; `public/sync-actions.js::fullResync`; `public/sync-actions.js::waitForFullResync`; `public/sync-actions.js::syncGarmin`; `public/wahoo-connection.js::takeWahooReturnOutcome`. Tests: `tests/provider-connections.test.cjs::a discarded pending login returns from the MFA step to the login form`; `tests/wahoo-connection.test.cjs::a slow resync is polled, not reported as a failure, even when a single poll fails`; `e2e/wahoo-connection.spec.js::the OAuth return outcome is announced once and removed from the address`.
