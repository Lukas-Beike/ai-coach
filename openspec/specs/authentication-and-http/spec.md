# authentication-and-http Specification

## Purpose

Protect the single-athlete HTTP boundary with persistent sessions, CSRF checks, bounded requests and safe errors.

Owns transport/authentication policy. Domain authorization remains with Coach, planning, nutrition and provider capabilities. Evidence is the recorded source snapshot; cited tests are not all executed in this backfill.

## Requirements

### Requirement: Secure configuration before authentication

The application SHALL refuse secure startup and authenticated API use when APP_PASSWORD is absent, shorter than 12 characters, or SQLCipher is unavailable.


#### Scenario: Incomplete secure configuration
- **WHEN** the configured password is missing or short, or SQLCipher is unavailable
- **THEN** startup is refused and login/protected API access returns an unavailable configuration response

#### Scenario: Complete secure configuration
- **WHEN** the password meets the length requirement and SQLCipher is available
- **THEN** the security configuration check permits normal authentication without bypassing session checks

Evidence: `backend/config.py::security_configuration_error`; `server.py::main`; `backend/http_api/auth.py::SessionAuthService.require_auth`. Tests: `tests/test_config.py::test_security_error_order_and_success`.

### Requirement: Durable session creation and invalidation

The application SHALL verify the submitted password with constant-time comparison, persist only hashes of random session/CSRF tokens with expiry, and invalidate the session on successful logout.


#### Scenario: Valid login
- **WHEN** the athlete submits the correct password
- **THEN** the API creates a persistent 30-day session and returns session and CSRF cookies

#### Scenario: Successful logout
- **WHEN** an authenticated CSRF-authorized logout succeeds
- **THEN** the stored session is deleted and both cookies are cleared

#### Scenario: Expired or missing token
- **WHEN** a protected request presents no current unexpired stored session
- **THEN** the request is rejected as unauthenticated

Evidence: `backend/http_api/auth.py::SessionAuthService.login_user`; `backend/http_api/auth.py::SessionAuthService.logout_user`; `backend/http_api/responses.py::session_cookies`. Tests: `tests/test_http_auth_post.py::test_login_success_dispatches_password_and_sets_cookies`; `tests/test_http_auth_post.py::test_logout_success_operates_gate_and_clears_cookies`; `tests/test_server_database.py::test_session_is_persisted_and_restored_from_database`.

### Requirement: Read-only session verification under contention

Session authentication SHALL decide validity from its committed read snapshot without waiting for the writer; nonessential touch/expiry cleanup SHALL be bounded and skippable under writer contention without accepting expired sessions.

#### Scenario: Busy writer with a valid session
- **WHEN** a valid session is read while a background writer is busy
- **THEN** authentication succeeds from committed session state and a nonessential last-seen write can be retried later

#### Scenario: Expired session with a busy writer
- **WHEN** an expired session is read and its cleanup writer cannot be acquired
- **THEN** authentication still rejects the expired session without waiting for successful deletion

Evidence: `backend/http_api/auth.py::SessionAuthService.authenticated_session`; `backend/http_api/auth.py::SessionAuthService._write_if_idle`. Tests: `tests/test_session_auth_read_path.py::test_valid_session_authenticates_without_the_writer`; `tests/test_session_auth_read_path.py::test_busy_writer_never_blocks_or_fails_a_valid_stale_session`; `tests/test_session_auth_read_path.py::test_expired_session_is_rejected_even_when_the_writer_is_busy`.

### Requirement: CSRF and cookie boundaries

State-changing authenticated HTTP requests SHALL require the X-CSRF-Token value matching the stored session hash; the session cookie SHALL be HttpOnly (the CSRF cookie stays script-readable) and both cookies SHALL use SameSite=Strict and the configured Secure setting.


#### Scenario: Missing or mismatched CSRF token
- **WHEN** a state-changing request has a session but no matching CSRF header
- **THEN** the API rejects it with HTTP 403 before the domain mutation

#### Scenario: Cookie policy
- **WHEN** login or logout response cookies are formatted
- **THEN** the session cookie has HttpOnly, both cookies have Path=/ and SameSite=Strict, and Secure follows configuration

Evidence: `backend/http_api/auth.py::SessionAuthService.require_csrf`; `backend/http_api/handler.py::RequestHandler._post`; `backend/http_api/handler.py::RequestHandler._put`; `backend/http_api/responses.py::session_cookies`. Tests: `tests/test_server_http.py::test_csrf_rejects_missing_or_foreign_token`; `tests/test_server_http.py::test_session_cookies_secure_flag_is_configurable_without_changing_csrf_visibility`.

### Requirement: Bounded client-specific rate limits

The authentication service SHALL limit login attempts and authenticated API requests by resolved client IP, honoring forwarded chains only through configured trusted proxies.


#### Scenario: Exceeded login allowance
- **WHEN** five login attempts with a wrong password or an invalid body occur in a 900-second client window
- **THEN** the next login is rejected with a rate-limited response and retry metadata before its body is read; a correct password returns its slot, so successful logins never use up the allowance

#### Scenario: Untrusted forwarding header
- **WHEN** an untrusted socket peer supplies X-Forwarded-For
- **THEN** the socket peer remains the rate-limit identity

#### Scenario: Forwarded chain behind a trusted proxy
- **WHEN** the socket peer is in `TRUSTED_PROXY_IPS` and `X-Forwarded-For` holds several hops, also over several header instances
- **THEN** the chain is read from the right, trusted hops are skipped and the first untrusted hop is the client; a malformed hop stops the walk at the last valid address, and IPv4-mapped IPv6 addresses count as IPv4

#### Scenario: Authenticated API allowance
- **WHEN** the resolved client exceeds 180 authenticated API requests in 60 seconds
- **THEN** the API returns HTTP 429 with retry information

#### Scenario: Limit windows and response
- **WHEN** a client exceeds a limit: login 5 per 900 seconds, authenticated API 180 per 60 seconds counted only for requests with a valid session, or APP_PASSWORD re-entry 10 per 900 seconds with every attempt counted
- **THEN** the request answers HTTP 429 with reason `rate_limited`, a `Retry-After` header and `retry_after_seconds`; the windows are in memory and a restart resets them, and public routes and requests without a session never count against the API limit

Evidence: `backend/http_api/auth.py::resolve_client_ip`; `backend/http_api/auth.py::SessionAuthService.client_ip`; `backend/http_api/auth.py::SessionAuthService.login_user`; `backend/http_api/auth.py::SessionAuthService.require_auth`; `backend/http_api/rate_limit.py::RateLimiter`. Tests: `tests/test_config.py::test_trusted_proxies_parse_addresses_and_networks`; `tests/test_server_http.py::test_rate_limiter_enforces_limit_retry_after_and_independent_keys`; `tests/test_session_auth_read_path.py::test_successful_logins_do_not_use_up_the_login_limit`; `tests/test_security_resource_limits.py::test_login_throttles_before_reading_and_counts_malformed_requests`; `tests/test_http_database_busy.py::test_rate_limit_errors_also_send_retry_after`.

### Requirement: Request body shape and size

The HTTP boundary SHALL enforce configured body-size limits and supported content types, accept object-shaped JSON only, and reject truncated streamed uploads.


#### Scenario: Invalid JSON shape or type
- **WHEN** a JSON route receives malformed JSON, a non-object value, or an unsupported content type
- **THEN** the route returns its bounded HTTP 400 or 415 validation error

#### Scenario: Oversized request
- **WHEN** the declared payload exceeds the route body limit
- **THEN** the route rejects the payload with HTTP 413

#### Scenario: Unparseable length and body errors
- **WHEN** `Content-Length` is not an integer, or the body is not UTF-8 JSON, nests too deeply, holds an oversized integer or is not an object
- **THEN** the answers are HTTP 400 "Ungültige Content-Length.", "Ungültiges JSON." or "Der JSON-Inhalt muss ein Objekt sein.", and a JSON route without `application/json` answers 415 "Content-Type muss application/json sein."

#### Scenario: Truncated stream
- **WHEN** a streamed upload ends before its declared Content-Length
- **THEN** the parser rejects the incomplete body without treating it as complete

#### Scenario: Body limits per route class
- **WHEN** a request declares its size in `Content-Length`, the only source of the body size
- **THEN** ordinary JSON routes accept up to 1 000 000 bytes, the Coach chat routes 28 000 000, voice audio 8 000 000 and a backup restore 1 000 000 000 read in 1 MiB chunks; a route with its own limit states it in `docs/api-routes.md`

#### Scenario: Missing or out-of-range size
- **WHEN** `Content-Length` is missing, zero or above the route limit
- **THEN** a JSON or body route answers "Ungültige Größe des Anfrageinhalts." with HTTP 413 when the size also exceeds 1 000 000 bytes and HTTP 400 otherwise, voice audio answers "Ungültige Größe der Audioaufnahme." with HTTP 413 only above 8 000 000 bytes, and a JSON route without `application/json` in `Content-Type` answers HTTP 415

Evidence: `backend/http_api/requests.py::read_json`; `backend/http_api/requests.py::read_body_stream`; `backend/http_api/requests.py::read_audio_body`. Tests: `tests/test_http_input_robustness.py::test_malformed_login_bodies_return_400_without_tracebacks`; `tests/test_http_input_robustness.py::test_oversize_body_limit_is_unchanged`; `tests/test_server_http.py::test_http_request_helpers_are_dependency_light_and_preserve_limits`; `tests/test_server_http.py::test_streamed_body_checks_limits_before_reading_and_bounds_each_chunk`.

### Requirement: Post-maintenance authorization recheck

Authenticated ordinary POST mutations SHALL revalidate the current session and CSRF token after entering the maintenance gate so a restore-invalidated session cannot write through an earlier successful check.


#### Scenario: Session invalidated during gate entry
- **WHEN** a restore removes the session after the initial auth check but before an ordinary POST enters the operation gate
- **THEN** the second session check returns HTTP 401 and no authenticated route mutation runs

#### Scenario: Session remains current
- **WHEN** the session and CSRF token still match after gate entry
- **THEN** the request dispatches once without consuming a second require_auth rate-limit slot

Evidence: `backend/http_api/handler.py::RequestHandler._post`; `backend/http_api/route_table.py::Route`. Tests: `tests/test_http_post_maintenance_reauth.py`; `tests/test_runtime_maintenance.py::test_operation_rejects_stale_generation`.

### Requirement: Safe classified HTTP errors

The API SHALL expose bounded redacted error text, a safe reason and request correlation where available, map transient database contention to retryable HTTP 503, and keep unexpected internal exceptions out of response bodies.


#### Scenario: Busy database
- **WHEN** a request cannot acquire its bounded database resource
- **THEN** the response is HTTP 503 with database_busy retry metadata rather than an unclassified internal error

#### Scenario: Unexpected exception
- **WHEN** a route raises an unhandled internal exception
- **THEN** the client receives the generic internal-server-error envelope

#### Scenario: Upstream authentication error
- **WHEN** a provider returns an upstream 401 or 403
- **THEN** the public contract classifies it as upstream_auth with HTTP 502 rather than logging the athlete out

#### Scenario: Error envelope
- **WHEN** a classified application error is answered
- **THEN** the JSON body has `error` (redacted German text of at most 1000 characters), `reason` (`[a-z0-9_]{1,80}`, else `request_failed`), `request_id` (12 hex characters) and, for HTTP 429 and 503 with a known delay, `retry_after_seconds` with a matching `Retry-After` header; route-specific errors are listed per route in `docs/api-routes.md`

#### Scenario: Server error logging
- **WHEN** the public status is 500 or higher
- **THEN** one `http_app_error` log entry with method, status and request id is written; an unhandled exception answers HTTP 500 with only `{"error": "Interner Serverfehler."}`, and the query string is redacted in every access log line

#### Scenario: Other upstream statuses
- **WHEN** a provider answers 404, 429, 408 or 5xx, or another error status
- **THEN** the public contract is HTTP 502 `upstream_not_found`, 429 `upstream_rate_limited`, 503 `upstream_unavailable` or 502 `upstream_rejected`

Evidence: `backend/errors.py::public_error_payload`; `backend/errors.py::public_error_contract`; `backend/http_api/handler.py::RequestHandler._send_app_error`. Tests: `tests/test_http_database_busy.py::test_busy_writer_during_login_is_a_retryable_503`; `tests/test_http_database_busy.py::test_other_failures_stay_an_internal_500`; `tests/test_server_http.py::test_app_error_handler_logs_redacted_event_for_each_method`; `tests/test_server_http.py::test_missing_request_id_is_omitted_from_error_response`; `tests/test_http_database_busy.py::test_rate_limit_errors_also_send_retry_after`.

### Requirement: Static and API routing boundaries

The server SHALL return API not-found errors for unmatched API paths, restrict static assets to the owned public target projection, reject traversal separators, and provide no-store/default hardening headers and configured asset-cache policy.


#### Scenario: Unknown API route
- **WHEN** no concrete API route handles an /api/ path
- **THEN** the request returns HTTP 404 rather than serving the application shell

#### Scenario: Traversal-shaped static path
- **WHEN** a static asset name contains prohibited traversal or path separators
- **THEN** the request is rejected with HTTP 403

#### Scenario: Ordinary response
- **WHEN** an API response is formatted with the default response policy
- **THEN** it includes Cache-Control=no-store, nosniff and DENY framing protection

#### Scenario: Static response headers
- **WHEN** a static file is served
- **THEN** it carries nosniff, DENY, an `ETag`, `Referrer-Policy: no-referrer` and the Content-Security-Policy `default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'`; a stamped asset requested with a non-blank `?v=` is cached for a year as immutable, the shell, service worker and manifest use `no-cache`, other files one hour, and no response sends CORS headers

#### Scenario: Conditional request and unknown path
- **WHEN** `If-None-Match` equals the current `ETag` (the first 24 hex characters of the SHA-256 of the served bytes), or a non-API path names no static file
- **THEN** the answer is HTTP 304 with only `ETag` and `Cache-Control`, or the stamped `index.html` with HTTP 200

#### Scenario: Version value not checked
- **WHEN** a versioned asset is requested with any non-blank `v` value, also one that is not its current hash
- **THEN** it is served as immutable for a year; correctness relies on the shell being `no-cache`, and the unversioned icons and font stay at one hour

Evidence: `backend/http_api/route_table.py::RouteTable`; `backend/http_api/handler.py::RequestHandler._get`; `backend/http_api/static_assets.py::StaticAssetService.render`; `backend/http_api/responses.py::response_headers`. Tests: `tests/test_http_route_dispatch.py`; `tests/test_server_frontend.py::test_static_files_reject_path_traversal`; `tests/test_server_frontend.py::test_unknown_static_asset_falls_back_to_index_with_security_headers`; `tests/test_server_frontend.py::test_versioned_static_assets_are_immutable_and_support_etag_revalidation`; `tests/test_server_frontend.py::test_html_and_service_worker_remain_revalidatable`.

### Requirement: Registered route surface

The server SHALL register exactly the API routes of `docs/api-routes.md`, each with one method and one access class (public, session, session with CSRF), and SHALL answer every other `/api/` path with HTTP 404 "Nicht gefunden." after the checks of its method. Domain specifications name the routes they own; the table gives each route's fields and errors.

#### Scenario: Documented and registered routes agree
- **WHEN** the registered route table and the generated table of `docs/api-routes.md` are compared
- **THEN** they are identical and every handler states its purpose and contract

#### Scenario: Retired alias
- **WHEN** a client posts to `/api/nutrition/sync`, `/api/logs/clear` or `/api/diagnostics/clear`
- **THEN** no route handles it and an authenticated request receives HTTP 404

Evidence: `backend/http_api/route_table.py::RouteTable`; `backend/http_api/handler.py::RequestHandler._get`. Tests: `tests/test_api_routes_doc.py::test_generated_route_table_is_current`; `tests/test_api_routes_doc.py::test_every_route_handler_states_its_purpose_and_contract`; `tests/test_api_routes_doc.py::test_routes_named_in_the_prose_are_registered`; `tests/test_nutrition_api_and_sync.py::test_the_removed_sync_route_is_not_handled`.

### Requirement: Check order per method

The request handler SHALL check each method in a fixed order: GET matches its route, then checks the session; POST serves login first, otherwise checks session and CSRF (also for an unknown path) before the maintenance gate; PUT enters the gate first. `docs/api-routes.md` gives each route's gate. A gated route answers HTTP 503 `maintenance` during a restore.

#### Scenario: Unknown POST without a session
- **WHEN** an unauthenticated client posts to an unregistered API path
- **THEN** the answer is HTTP 401, not 404; an authenticated client with a valid CSRF token receives 404

#### Scenario: Ungated POST routes during a restore
- **WHEN** a restore is draining and an authenticated, CSRF-valid client posts to `/api/chat/cancel`
- **THEN** the cancel is served although gated POST routes answer HTTP 503; logout enters the gate only to delete the session, and login and the restore itself are not gated

#### Scenario: PUT during maintenance
- **WHEN** a restore is active and a PUT arrives, with or without a session
- **THEN** the answer is HTTP 503 `maintenance` before authentication: "Die Anwendung befindet sich gerade im Wartungsmodus. Bitte später erneut versuchen."

#### Scenario: Reads and the Wahoo callback
- **WHEN** a GET arrives while a restore is active
- **THEN** the handler does not reject it as maintenance; only the public `GET /api/wahoo/callback` enters the gate inside its handler while it completes the authorization

Evidence: `backend/http_api/handler.py::RequestHandler._get`; `backend/http_api/handler.py::RequestHandler._post`; `backend/http_api/handler.py::RequestHandler._put`; `backend/http_api/route_table.py::Route`; `backend/runtime/maintenance.py::MaintenanceGate.operation`; `backend/http_api/wahoo.py::WahooGetRoutes`. Tests: `tests/test_http_route_dispatch.py::test_authentication_and_the_maintenance_gate_wrap_each_route`; `tests/test_http_post_maintenance_reauth.py::test_pre_gate_routes_still_use_the_first_session_and_skip_the_gate`; `tests/test_http_chat_cancel_post.py::test_success_dispatches_csrf_hash_and_operation_id`.

### Requirement: Login and cookie wire contract

`POST /api/login` SHALL take `{"password": <text>}` and answer HTTP 200 `{"status": "ok", "authenticated": true, "csrf": <token>}` with the cookies `ic_session` (HttpOnly) and `ic_csrf` (script-readable), both `Path=/; SameSite=Strict; Max-Age=2592000`, plus `Secure` when configured. `POST /api/logout` SHALL answer `{"status": "ok"}` and set both cookies empty with `Max-Age=0`.

#### Scenario: Wrong or missing password
- **WHEN** the password is absent, not a string or wrong
- **THEN** the answer is HTTP 401 "Ungültiges Passwort." and no cookie is set

#### Scenario: Missing session or CSRF token
- **WHEN** a protected route receives no valid `ic_session` cookie, or a mutation lacks an `X-CSRF-Token` whose SHA-256 matches the stored hash
- **THEN** the answer is HTTP 401 "Anmeldung erforderlich." with `WWW-Authenticate: Session`, or HTTP 403 "Ungültiges CSRF-Token."; an upstream provider 401 never carries that header

#### Scenario: Foreign cookies
- **WHEN** the Cookie header contains malformed cookies of other applications
- **THEN** the session value is still read and a quoted value is unwrapped

#### Scenario: Incomplete secure configuration at request time
- **WHEN** the password or SQLCipher check fails for a login or an authenticated request
- **THEN** the answer is HTTP 503 "Die sichere App-Konfiguration ist unvollständig."

Evidence: `backend/http_api/auth.py::SessionAuthService.login_user`; `backend/http_api/auth.py::SessionAuthService.require_auth`; `backend/http_api/auth.py::SessionAuthService.require_csrf`; `backend/http_api/auth.py::SessionAuthService.cookie_value`; `backend/http_api/responses.py::session_cookies`; `backend/http_api/handler.py::RequestHandler._send_app_error`. Tests: `tests/test_http_auth_post.py::test_login_success_dispatches_password_and_sets_cookies`; `tests/test_server_http.py::test_local_session_401_receives_session_challenge`; `tests/test_server_http.py::test_provider_auth_error_does_not_receive_session_challenge`; `tests/test_session_auth_read_path.py::test_foreign_non_rfc_cookies_keep_the_session_and_csrf_values`.

### Requirement: Fixed session lifetime and bounded upkeep

A session SHALL expire 30 days after login and SHALL NOT be extended by use. `last_seen` SHALL be written at most every 300 seconds and expired rows SHALL be removed at most every 900 seconds, 100 per run; both writes are skipped while the writer is busy. Login and logout SHALL wait at most 10 seconds for the writer, then answer HTTP 503 `database_busy`.

#### Scenario: Active use on day 30
- **WHEN** a session was used daily and its 30 days have passed
- **THEN** the next request is rejected with HTTP 401 and the row is deleted when the writer is free

#### Scenario: Busy writer at login
- **WHEN** the writer stays busy for 10 seconds during a login with the correct password
- **THEN** the answer is HTTP 503 with reason `database_busy` and `Retry-After: 5`, and no session exists

Evidence: `backend/http_api/auth.py` (`SESSION_TTL_SECONDS`, `SESSION_TOUCH_INTERVAL_SECONDS`, `SESSION_CLEANUP_INTERVAL_SECONDS`, `SESSION_CLEANUP_BATCH_SIZE`, `SESSION_WRITE_WAIT_SECONDS`); `backend/http_api/auth.py::SessionAuthService.authenticated_session`. Tests: `tests/test_server_http.py::test_authenticated_session_throttles_last_seen_without_extending_fixed_expiry`; `tests/test_server_http.py::test_expired_session_cleanup_is_bounded_and_periodic`; `tests/test_session_auth_read_path.py::test_login_wait_for_a_busy_writer_is_bounded`; `tests/test_http_database_busy.py::test_busy_writer_during_login_is_a_retryable_503`.

### Requirement: Input deadlines and unsupported methods

The server SHALL give the request line and headers 20 seconds and every body chunk of at most 1 MiB its own 20 seconds. When a body deadline passes it SHALL close the connection without a response and log `http_client_timeout`. These deadlines SHALL NOT limit the response duration. Only GET, POST and PUT are implemented.

#### Scenario: Slow but steady upload
- **WHEN** each 1 MiB chunk arrives within 20 seconds although the upload takes longer in total
- **THEN** the upload is accepted

#### Scenario: Dripping client
- **WHEN** a client sends less than one chunk in 20 seconds
- **THEN** the connection is closed and no HTTP 500 is produced

#### Scenario: Other method
- **WHEN** HEAD, DELETE, PATCH or OPTIONS is requested
- **THEN** the standard library answers HTTP 501

Evidence: `backend/http_api/handler.py::RequestHandler.handle_one_request`; `backend/http_api/handler.py::RequestHandler._read_input`; `backend/http_api/handler.py::RequestHandler._end_after_input_timeout`. Tests: `tests/test_http_input_robustness.py::test_steady_trickle_longer_than_one_window_is_accepted`; `tests/test_http_input_robustness.py::test_drip_below_the_chunk_rule_closes_without_a_server_error`; `tests/test_security_resource_limits.py::test_input_deadlines_interrupt_drips_but_do_not_limit_response_duration`.

### Requirement: Public status payloads

`GET /api/auth/status`, `/api/health` and `/api/readiness` SHALL need no session and no rate-limit slot; `/api/readiness` SHALL answer HTTP 503 while any of its four checks (`database`, `schema`, `data_directory`, `maintenance`) fails. The payload fields are those of `docs/api-routes.md`.

#### Scenario: Expired cookie
- **WHEN** `/api/auth/status` is read with an expired or unknown session cookie
- **THEN** the answer is HTTP 200 with `authenticated` false

#### Scenario: Read-only data directory
- **WHEN** the readiness write probe cannot create its file
- **THEN** `checks.data_directory` is false, the status is 503 and no probe file remains; every readiness call creates and removes one probe file

Evidence: `backend/http_api/public_get.py::PublicGetRoutes`; `backend/http_api/readiness.py::ReadinessService.state`. Tests: `tests/test_http_public_get_routes.py::test_auth_status_uses_optional_authenticated_session_and_live_gate`; `tests/test_http_readiness.py::test_a_read_only_data_directory_is_not_ready`; `tests/test_http_readiness.py::test_the_probe_is_removed_after_a_write_failure`.

### Requirement: State event stream transport

`GET /api/state/events?since=<id>` SHALL require a session and answer `text/event-stream` with `id:`, `event:` and compact JSON `data:` lines: retained events after `since`, then `ready` with `latest_event_id`, then new events or a `heartbeat` after at most 15 seconds without one. Events are `provider`, `job`, `planning`, `coach`, `sync`, `reset`, `ready` and `heartbeat`.

#### Scenario: Invalid cursor
- **WHEN** `since` is not 1 to 19 ASCII digits
- **THEN** the answer is HTTP 400 "Die Event-ID ist ungültig." with reason `invalid_event_cursor` and no stream opens

#### Scenario: Retention gap
- **WHEN** the cursor is older than the retained window or from an earlier process
- **THEN** one `reset` with reason `gap` and `latest_event_id` is sent instead of a partial list

#### Scenario: Session ends or error after the headers
- **WHEN** the session expires or is deleted while the stream is open, or an error occurs after the 200 status line
- **THEN** the stream ends at the next round without a second HTTP response

Evidence: `backend/http_api/state_events_transport.py::StateEventTransport.handle`; `backend/runtime/events.py::StateEventBuffer`. Tests: `tests/test_state_events_transport.py::test_cursor_is_bounded_to_nineteen_digits`; `tests/test_state_events_transport.py::test_gap_reset_and_heartbeat_preserve_cursor_sequence`; `tests/test_state_events_transport.py::test_session_expiry_after_heartbeat_stops_further_events`; `tests/test_state_events_transport.py::test_errors_after_the_headers_end_the_stream_without_a_second_response`.
