# Test development instructions

- Run tests from the repository root with:

  ```powershell
  python -m unittest discover -s tests -v
  python -m py_compile server.py tests/test_server.py
  ```

- Every test must use temporary `DATA_DIR`/database state or isolated patches.
  Never read or modify the real `.env`, `/data`, production database, Garmin
  token store, or runtime logs.
- Mock all OpenAI, Intervals.icu, Garmin, iCalendar, and other network calls.
  Do not use real credentials, external accounts, or live network access.
- Do not print secrets or full athlete payloads in failures, fixtures, or test
  diagnostics. Use clearly fake values and sanitized/minimal fixtures.
- Preserve coverage for the security and approval boundaries: APP_PASSWORD,
  session/CSRF authentication, SQLCipher/plaintext migration, path traversal,
  public-calendar SSRF validation, redacted logs/diagnostics, bounded request
  bodies, backup validation/restore, local-only drafts, and explicit remote
  workout approval.
- When changing sync or context behavior, test source precedence and provenance
  for Intervals.icu, Garmin, local feedback, derived metrics, and AI estimates.
- When changing the frontend, backend API contracts, PWA cache behavior, or
  deployment, add or update focused regression tests where the current
  standard-library test setup permits it.
