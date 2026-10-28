# Tasks

## 1. Diagnose and provider behavior

- [x] 1.1 Review the sanitized diagnostic metadata, current Yazio authentication and relevant documented protocol evidence; record the falsifiable cause and evidence gap without credentials or raw provider payloads. Verify a synthetic regression reproduces any established protocol mismatch; if no cause is established, explicitly report that limitation.
- [x] 1.2 Correct any evidenced authentication compatibility defect and classify ambiguous rejection, recognized version blocking, outage and throttling safely; verify mocked Yazio tests cover success, errors, redaction, retry/backoff and existing lookup fallback.
- [x] 1.3 Implement a bounded explicit authentication check using the shared client and credential identity; verify mocked tests cover missing configuration, successful check, failures, stale in-flight results, credential replacement, restart and existing rate limits without remote writes.

## 2. Status API and connections screen

- [x] 2.1 Expose token-free local status and an authenticated, CSRF-protected check through the owning backend routes; verify focused HTTP tests cover authorization, no passive network calls, safe responses and credential-change races.
- [x] 2.2 Add the Yazio card, check action, check time and truthful states to the mobile connections screen; update asset versions and service worker together and verify focused JavaScript tests cover all states and failed requests.
- [x] 2.3 Update README setup, check and troubleshooting guidance without claiming an unverified cause; verify it matches implemented behavior and preserves credential safety.

## 3. Integration validation

- [x] 3.1 Review the complete final diff and scoped evidence; run focused backend and JavaScript tests, relevant architecture and lint/type checks, `python -m unittest discover -s tests -v`, and `python -m compileall -q server.py backend tests`; document failures or unavailable checks.
- [ ] 3.2 Run the affected isolated Playwright project and applicable manual PWA/browser checks, including the connection flow and fresh/offline assets; rebuild the Docker image as required for application changes and report any unavailable runtime evidence.
- [x] 3.3 Run `npm run openspec -- validate fix-yazio-connection-status --strict --no-interactive` and verify the change is valid before completion.
