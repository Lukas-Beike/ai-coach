# Test development instructions

- Run tests from the repository root with:

  ```powershell
  python tests/run_tests.py --changed
  python -m compileall -q server.py backend tests
  ```

- `tests/changed_tests.py` selects modules by imports and by string literals
  naming changed paths or modules. A test that depends on a file another way
  (computed paths, dynamic imports) must name it as a literal, or the selector
  misses it locally.

- Helpers shared by several `TestCase` subclasses are module-level functions
  taking the case or its fixtures as arguments, not methods of a base `TestCase`
  (Sonar python:S5899 flags those as unused).
- Every test must use temporary `DATA_DIR`/database state or isolated patches.
  Never read or modify the real `.env`, `/data`, production database, Garmin
  token store, or runtime logs.
- Mock all OpenAI, Intervals.icu, Garmin, iCalendar, and other network calls.
  Do not use real credentials, external accounts, or live network access.
- Do not print secrets or full athlete payloads in failures, fixtures, or test
  diagnostics. Use clearly fake values and sanitized/minimal fixtures.
- Preserve coverage for the security and approval boundaries: APP_PASSWORD,
  session/CSRF authentication, SQLCipher startup, path traversal,
  public-calendar SSRF validation, redacted logs/diagnostics, bounded request
  bodies, backup validation/restore, local-only planned units, and explicit remote
  workout approval.
- When changing sync or context behavior, test source precedence and provenance
  for Intervals.icu, Garmin, local feedback, derived metrics, and AI estimates.
- When changing the frontend, backend API contracts, PWA cache behavior, or
  deployment, add or update focused regression tests where the current
  standard-library test setup permits it.
