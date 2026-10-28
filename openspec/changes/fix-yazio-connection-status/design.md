# Design

## Context

See the proposal. At revision `c6ddecc8`, the Yazio adapter keeps tokens, identity and backoff in memory and groups login HTTP 400/401/403 into one error. The food lookup service owns fallback; the credentials service returns only presence/source. The connections UI has no Yazio card. The supplied diagnostic records an authentication failure but neither the upstream status nor the response, so the concrete compatibility defect is not yet established. `tests/test_yazio.py` and `tests/test_food_lookup_chain.py` use synthetic providers; no live authentication has been verified.

The community's [unofficial v22 documentation](https://github.com/yazio-community/yazio-api-specification/blob/main/README.md) describes version blocking on non-token endpoints. One falsifiable hypothesis is that account or app credentials were rejected at the token endpoint; a safe category for the failing endpoint and upstream status would help distinguish it from a product-request rejection. The supplied diagnostic does not contain those details, and the documentation is not an official compatibility guarantee. No protocol mismatch has been established for this incident.

## Goals / Non-Goals

**Goals:** Make the last explicitly verified result visible and enable a focused, evidence-led repair without leaking secrets or overstating the diagnosis.

**Non-Goals:** Remote diary writes, automatic provider calls on polling or startup, persistent tokens or connection history, schema migrations, or using an athlete account in automated tests.

## Decisions

- Expose a bounded authenticated, CSRF-protected check that shares the existing Yazio client, credential identity, locking and backoff. A check authenticates without inventing a food query or mutating diary data. A separate client or bypassing backoff would produce inconsistent status and excessive logins.
- Keep a sanitized last-check result and timestamp in memory associated with the effective credential generation. Clear it on credential changes and restart; discard results from in-flight checks against an old identity. Render configuration separately from last checked authentication; never interpret a stored credential as a live connection. Persisting status would require invalidation and migration without providing durable truth.
- Classify failures using only safely established signals; ambiguous 400/401/403 remains an ambiguous rejection unless a bounded, validated signal reliably distinguishes a version block. Never log or return raw bodies, tokens, values or request payloads. Preserve the existing local-first and alternative-provider fallback, request limits, and refresh behavior.
- Trace the actual failure with existing sanitized evidence and reproducible synthetic cases, then correct an evidenced protocol mismatch. If no cause can be established without live access, retain that limitation and do not claim a verified repair. Do not hard-code guessed app credentials or versions.
- Add a mobile connection card to the existing settings flow and update bootstrap/status consumers, cache versions and README together. A passive status refresh reads local state only; the check action gives the athlete control over upstream traffic.

## Risks / Trade-offs

- [Unofficial upstream interface can change] -> Preserve safe failure and fallback, and avoid claiming live compatibility from mocked tests.
- [Credential changes race an in-flight check] -> Associate results with identity and discard stale completions; exercise concurrent cases with synthetic credentials.
- [Authentication success is not permanent availability] -> Label the result with check time and reset it after restart or configuration changes.
- [Rate limits and rejection backoff] -> Reuse the current bounded client; report paused/rate-limited states without circumventing them.

## Migration Plan

No schema change or persistent connection state is planned. Deploy with aligned PWA assets; rollback removes the card and endpoint without modifying athlete data. Verify cache refresh with the isolated browser fixture.
