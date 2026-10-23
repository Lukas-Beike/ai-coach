# Authentication and HTTP Specification Delta

## Purpose

Protect the single-athlete HTTP boundary with persistent sessions, CSRF checks, bounded requests and safe errors.

Owns transport/authentication policy. Domain authorization remains with Coach, planning, nutrition and provider capabilities. Evidence is the recorded source snapshot; cited tests are not all executed in this backfill.

## ADDED Requirements

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

Evidence: `backend/http_api/auth.py::SessionAuthService.login_user`; `backend/http_api/auth.py::SessionAuthService.logout_user`; `backend/http_api/responses.py::session_cookies`. Tests: `tests/test_http_auth_post.py::test_login_success_dispatches_password_and_sets_cookies`; `tests/test_http_auth_post.py::test_logout_success_authenticates_operates_gate_and_clears_cookies`; `tests/test_server_database.py::test_session_is_persisted_and_restored_from_database`.

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

State-changing authenticated HTTP requests SHALL require the X-CSRF-Token value matching the stored session hash; session cookies SHALL be HttpOnly and both cookies SHALL use SameSite=Strict and the configured Secure setting.


#### Scenario: Missing or mismatched CSRF token
- **WHEN** a state-changing request has a session but no matching CSRF header
- **THEN** the API rejects it with HTTP 403 before the domain mutation

#### Scenario: Cookie policy
- **WHEN** login or logout response cookies are formatted
- **THEN** the session cookie has HttpOnly, both cookies have Path=/ and SameSite=Strict, and Secure follows configuration

Evidence: `backend/http_api/auth.py::SessionAuthService.require_csrf`; `backend/http_api/handler.py::RequestHandler.do_POST`; `backend/http_api/handler.py::RequestHandler._do_PUT`; `backend/http_api/responses.py::session_cookies`. Tests: `tests/test_server_http.py::test_csrf_rejects_missing_or_foreign_token`; `tests/test_server_http.py::test_session_cookies_secure_flag_is_configurable_without_changing_csrf_visibility`.

### Requirement: Bounded client-specific rate limits

The authentication service SHALL limit login attempts and authenticated API requests by resolved client IP, honoring forwarded chains only through configured trusted proxies.


#### Scenario: Exceeded login allowance
- **WHEN** more than the allowed five login attempts occur in a 900-second client window
- **THEN** the next login is rejected with a rate-limited response and retry metadata

#### Scenario: Untrusted forwarding header
- **WHEN** an untrusted socket peer supplies X-Forwarded-For
- **THEN** the socket peer remains the rate-limit identity

#### Scenario: Authenticated API allowance
- **WHEN** the resolved client exceeds 180 authenticated API requests in 60 seconds
- **THEN** the API returns HTTP 429 with retry information

Evidence: `backend/http_api/auth.py::resolve_client_ip`; `backend/http_api/auth.py::SessionAuthService.login_user`; `backend/http_api/auth.py::SessionAuthService.require_auth`; `backend/http_api/rate_limit.py::RateLimiter`. Tests: `tests/test_config.py::test_trusted_proxies_parse_addresses_and_networks`; `tests/test_http_database_busy.py::test_rate_limit_errors_also_send_retry_after`.

### Requirement: Request body shape and size

The HTTP boundary SHALL enforce configured body-size limits and supported content types, accept object-shaped JSON only, and reject truncated streamed uploads.


#### Scenario: Invalid JSON shape or type
- **WHEN** a JSON route receives malformed JSON, a non-object value, or an unsupported content type
- **THEN** the route returns its bounded HTTP 400 or 415 validation error

#### Scenario: Oversized request
- **WHEN** the declared payload exceeds the route body limit
- **THEN** the route rejects the payload with HTTP 413

#### Scenario: Truncated stream
- **WHEN** a streamed upload ends before its declared Content-Length
- **THEN** the parser rejects the incomplete body without treating it as complete

Evidence: `backend/http_api/requests.py::read_json`; `backend/http_api/requests.py::read_body_stream`; `backend/http_api/requests.py::read_audio_body`. Tests: `tests/test_server_http.py::test_http_request_helpers_are_dependency_light_and_preserve_limits`; `tests/test_server_http.py::test_streamed_body_checks_limits_before_reading_and_bounds_each_chunk`.

### Requirement: Post-maintenance authorization recheck

Authenticated ordinary POST mutations SHALL revalidate the current session and CSRF token after entering the maintenance gate so a restore-invalidated session cannot write through an earlier successful check.


#### Scenario: Session invalidated during gate entry
- **WHEN** a restore removes the session after the initial auth check but before an ordinary POST enters the operation gate
- **THEN** the second session check returns HTTP 401 and no authenticated route mutation runs

#### Scenario: Session remains current
- **WHEN** the session and CSRF token still match after gate entry
- **THEN** the request dispatches once without consuming a second require_auth rate-limit slot

Evidence: `backend/http_api/handler.py::RequestHandler.do_POST`; `backend/http_api/post_dispatch.py::HttpPostDispatcher`. Tests: `tests/test_http_post_maintenance_reauth.py`; `tests/test_runtime_maintenance.py::test_operation_rejects_stale_generation`.

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

Evidence: `backend/errors.py::public_error_payload`; `backend/errors.py::public_error_contract`; `backend/http_api/handler.py::RequestHandler._send_app_error`. Tests: `tests/test_http_database_busy.py::test_busy_writer_during_login_is_a_retryable_503`; `tests/test_http_database_busy.py::test_other_failures_stay_an_internal_500`; `tests/test_http_database_busy.py::test_rate_limit_errors_also_send_retry_after`.

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

Evidence: `backend/http_api/route_dispatch.py::HttpRouteDispatcher`; `backend/http_api/static_assets.py::StaticAssetService.render`; `backend/http_api/responses.py::response_headers`. Tests: `tests/test_http_route_dispatch.py`; `tests/test_server_frontend.py::test_static_files_reject_path_traversal`; `tests/test_server_frontend.py::test_unknown_static_asset_falls_back_to_index_with_security_headers`.
