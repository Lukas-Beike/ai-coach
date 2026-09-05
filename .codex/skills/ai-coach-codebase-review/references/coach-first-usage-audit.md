# Coach-first and complete usage audit

This is the mandatory runtime and white-box audit for the application's primary user experience. Execute it against the local test application where possible and trace every observed behavior back through source and tests. Do not reduce it to a visual smoke test.

## 1. Required coverage artifacts

Create these ledgers before testing. Derive their rows from the current source rather than assuming this document is exhaustive.

1. **Coach capability ledger:** user goal, UI/API capability, natural-language examples, intent classifier, canonical tool, read/write scope, authorization rule, implementation, durable effect, receipt, refresh event, UI result, tests, runtime result.
2. **Message lifecycle ledger:** state, initiating event, frontend variables/DOM, server job/receipt/message state, exit events, restart behavior, test and runtime evidence.
3. **API contract ledger:** every route and frontend caller with method, auth/CSRF, request shape, success shape, 400/401/403/404/409/413/422/429/5xx behavior, retry rule, user-visible error, and tests.
4. **Provider ledger:** capability, data window, cursor/pagination, freshness/provenance, local persistence, last-good behavior, timeout/retry, partial failure, Coach visibility, UI visibility, named-sync path, remote-write risk, tests, and runtime result.
5. **Journey/viewport ledger:** scenario across every configured Playwright project, pointer/keyboard behavior, loading/error/empty/success states, accessibility, console/network errors, and screenshots only when sanitized.

An implementation path is not covered until its schema, callers, state transitions, failure behavior, UI observation, and relevant test are reconciled.

## 2. Coach-first acceptance model

Build the current tool inventory from `COACH_TOOLS`, `COACH_PROPOSAL_TOOLS`, `COACH_STRUCTURED_TOOLS`, `COACH_CANONICAL_TOOL_NAMES`, `COACH_INTENT_TOOL_MAP`, `MUTATING_COACH_TOOL_NAMES`, `STRUCTURED_READ_ONLY_TOOLS`, `requested_coach_tool`, and `_structured_coach_tool_result`. Find drift and unreachable or unrepresented operations between these sets.

For every user-facing capability, verify whether the athlete can perform it naturally through the Coach when the product intends that capability. Include at least:

- inspect current performance, activities, feedback, planned units, library, training plans, competitions, weather, calendar constraints, and provider status;
- create and change dated workouts, create/change templates, plan from the library, bulk or multi-session planning, feedback and check-ins, training-plan changes, competitions, and adaptive replanning;
- explicitly refresh Intervals, Garmin, performance, library, weather, external calendar, or competitions and synchronize the permitted local objects;
- handle missing identifiers by listing/resolving current objects rather than hallucinating IDs or asking the athlete to use a hidden manual UI workflow;
- provide a truthful action receipt and final answer that names what changed, what stayed local, what synchronized remotely, what failed, and what remains pending.

Test direct German natural-language variants, short commands, polite commands, corrections, follow-ups that rely on dialogue context, multiple actions in one prompt, mixed read/write prompts, ambiguous requests, negation, hypothetical questions, quotations of an instruction, and provider/calendar text containing instruction-like language.

Coach-first invariants:

- explicit local action or named read-sync request is sufficient authorization for the matching action;
- no redundant generic preview/confirm/execute loop is imposed where current product rules allow direct execution;
- adaptive replan apply, destructive privacy actions, and remote workout/library synchronization retain their explicit safety boundary;
- automatic morning check-in and informational/status prompts cannot mutate;
- model output alone never grants authority, widens scope, changes target system, or supplies missing user intent;
- a partial multi-tool failure is reported precisely and does not describe the entire request as successful;
- retries, repeated tool calls, browser resubmission, and recovered jobs do not duplicate durable or remote effects.

## 3. Message lifecycle and disappearing-message audit

Model the actual state machine around `state.chatQueue`, `state.chatRequest`, `state.chatStream`, `state.chatStreamText`, `state.chatServerOperationId`, `state.chatStatusTimer`, `state.busy`, `client_turn_id`, persisted messages, Coach command receipts, and background job receipts. Trace `renderMessages`, pending-message reconciliation, fresh history loading, status polling, queue draining, cancellation, reset, state events, and bootstrap refreshes.

For every transition, assert these invariants:

- the submitted user text becomes visible immediately and remains visible until it is represented exactly once by persisted history;
- an assistant placeholder/partial response is never silently removed; completion replaces it exactly once, while failure or recovery leaves an understandable state;
- message identity and ordering do not depend only on array position, timing, text equality, or a stale history response;
- an older bootstrap/history/status response cannot overwrite newer messages, drafts, receipts, or in-progress state;
- reload, navigation, tab visibility changes, service-worker activation, and a second tab converge to the server-authoritative history without duplication or loss;
- queue, send, steer, cancel, retry, reset, and timeout controls match the actual server operation and never act on a newer request;
- scroll anchoring, focus, draft text, and the response-start position remain stable without hiding new content or stealing focus on another view;
- an error never clears the athlete's input before it is either accepted durably or recoverably restored.

Execute at least these scenarios with controlled timing:

| Scenario | Required interleaving |
|---|---|
| Fast success | started, deltas, completed, then history refresh |
| Completion/history race | fresh history arrives before, during, and after `completed` |
| Bootstrap race | local bootstrap and delayed area refresh return in reverse order |
| State-event race | chat event triggers refresh while stream completion reconciles |
| Stream disconnect | disconnect before first delta, mid-response, and after server completion |
| Background fallback | request becomes background, page reloads, status polling resumes and reconciles |
| Conversation lock/recovery | temporary lock, retry, invalid conversation state, one-time recovery, final result |
| Empty/malformed upstream | no assistant text, invalid event JSON, unknown event, oversized stream, error terminal state |
| Cancel races | cancel before operation ID, during stream, during background polling, and simultaneous completion |
| Multiple sends | rapid Enter/click, queued second prompt, steer while busy, duplicate `client_turn_id` |
| Navigation | leave Coach during response, use other views, return before and after completion |
| Reload/close | reload immediately after send, after first delta, and after completion before history refresh |
| Multi-tab | send in one tab while another polls/refreshes; cancel/reset ownership stays session-correct |
| Offline/online | lose network at submit, mid-stream, and reconciliation; reconnect without duplicate send |
| Reset | reset while idle, streaming, recovering, or queued; stale callbacks cannot restore deleted UI state |
| Long content | long Markdown, lists, code, receipts, and many messages across all viewports |

Repeat timing-sensitive cases enough to expose non-determinism and use bounded deterministic delays rather than arbitrary sleeps where tests can intercept requests.

## 4. Race-condition and shared-state audit

Create an explicit happens-before diagram for chat, state refresh, sync, and restore. Inspect sequence numbers, operation IDs, abort controllers, event cursors, server receipts, database transactions, and locks instead of assuming single-threaded behavior.

Frontend interleavings to test:

- overlapping `/api/bootstrap`, scoped bootstrap, chat history, chat status, state-event refresh, sync polling, navigation loads, and optimistic edits;
- abort of an old request after a new request starts; late success and late error from both;
- BroadcastChannel messages from another tab with older/newer operation IDs;
- visibility/focus events, mobile keyboard resize, route changes, and streaming DOM updates;
- service-worker mixed-version frontend/backend contracts.

Backend interleavings to inspect/test:

- simultaneous chat requests for one session and separate sessions;
- background worker claim/requeue/restart versus browser polling/cancel/reset;
- duplicate `client_turn_id`, duplicate tool calls, and process restart after effect but before receipt;
- provider sync, full resync, planning/library sync, adaptive apply, privacy delete, backup, and restore competing for database or provider state;
- lock acquisition order among database, sync, Garmin, performance, OpenAI conversation, usage, session, stream/job, calendar, weather, and library locks;
- SQLite connection replacement/cache invalidation during restore and background writes;
- cursor/freshness/status updates committing before or after snapshot data.

A race finding must identify the competing operations, shared state, possible ordering, missing guard/version check, and resulting visible or durable failure.

## 5. 400-class and API-contract audit

Inventory every frontend `request`, `fetch`, EventSource, download, and audio caller and match it to the exact backend route. Most unexplained 400 errors arise from schema/version drift, stale IDs/hashes, wrong action boundaries, or lost client state; test those paths end to end.

For every route, cover:

- valid minimum and maximum payloads; omitted, null, empty, extra, duplicated, wrong-type, malformed JSON, wrong content type, and oversized bodies;
- date/time/unit boundary values, stale payload hashes, expired proposals/tokens, unknown IDs, duplicate IDs, and already-applied operations;
- missing/expired session, missing/wrong CSRF, and session change while a background action is pending;
- old cached frontend against the current backend and current frontend against a simulated old response shape;
- every emitted `reason` code and status. Verify the UI preserves actionable server detail safely and distinguishes validation, conflict/stale state, authorization, rate limiting, provider failure, and retryable server failure;
- whether a failed request leaves loading/busy/disabled controls, drafts, optimistic UI, queues, and polling in a recoverable state.

Inject and observe 400, 401, 403, 404, 409, 413, 422, 429, 500, 502, 503, 504, invalid JSON success/error bodies, connection reset, timeout, and aborted requests. Do not accept a generic toast as sufficient when the athlete needs to know which object/action failed or how to recover.

Correlate browser network evidence with the backend validator and originating UI state. Redact cookies, credentials, provider content, and athlete data from artifacts.

## 6. Coach tool end-to-end audit

For every current tool, verify this complete chain:

```text
athlete wording -> intent/scope -> forced or model-selected tool -> schema arguments
-> canonical name -> authorization -> idempotency/version guard -> handler/transaction
-> provider job if any -> command receipt/change history -> state event/bootstrap
-> final Coach wording -> visible UI and reload persistence
```

Test each tool with valid, boundary, malformed, stale, duplicate, unauthorized, ambiguous, and partial-provider-failure inputs. Specifically look for:

- schema fields accepted by the model but rejected or ignored by handlers, and handler capabilities absent from schemas;
- alias/canonical-name drift, wrong `COACH_INTENT_TOOL_MAP`, missing dispatcher branches, tools excluded from the wrong read/write set, or forced-tool logic selecting a different operation;
- arguments synthesized from stale context, hallucinated IDs, unsafe defaults, silent truncation, and date or timezone changes;
- local durable success followed by failed Coach follow-up, missing receipt, stale UI, or wording that claims remote success;
- multi-round tool loops, repeated non-read-only tools, tool-order dependency, limit exhaustion, and mixed success;
- direct paths and proposal paths implementing contradictory authorization or validation;
- API/UI actions that the Coach cannot perform even though Coach-first product behavior requires them.

## 7. Integration and source-of-truth matrix

Audit Intervals.icu, Garmin Connect, iCalendar, weather, GitHub release status, and OpenAI separately and in combination.

For each integration, execute or inject:

- never configured/never loaded, authenticating, fresh, stale, partial, rate-limited, invalid credential, timeout, malformed response, schema drift, empty success, pagination boundary, duplicate/out-of-order records, transient failure, persistent failure, and recovery;
- manual UI refresh, explicit Coach named refresh, startup refresh, daily refresh, concurrent refresh, full resync where safe, and status polling/reload;
- success of one provider while another fails, and a provider recovering while the Coach request is in flight;
- last-known-good preservation, cursor advancement, freshness timestamps, safe error persistence, provenance labels, Coach-context inclusion, and accurate UI status;
- source conflicts among provider data, confirmed local profile/competitions, local feedback, derived metrics, and AI estimates.

Integration-specific focus:

- **Intervals.icu:** activity pagination/windowing, competition reconciliation/tombstones, local workout/library synchronization, remote IDs, partial batches, retries, duplicate writes, remote deletion protections, and explicit remote-write authorization.
- **Garmin:** token-store behavior, MFA/setup boundary, date windows, concurrent range fetches, Body Battery/morning data, activity/profile zones, partial metric availability, error freshness, and no snapshot erasure.
- **iCalendar:** secret URL redaction, HTTPS/SSRF/DNS rebinding/redirect defense, recurrence/exception/timezone expansion, bounded feeds, last-good snapshot, and event text as untrusted scheduling data.
- **Weather:** location derivation, attribution, forecast horizon, timezone, negative cache/backoff, stale forecast communication, and no invented precise recommendation beyond available data.
- **OpenAI:** Responses status/stream/background state, conversation lock and recovery, base URL/path construction, model selection, tool response linkage, usage/cost accounting, timeouts, and raw-error redaction.
- **GitHub/release status:** token optionality, rate limits/cache, repository validation, no release check blocking core app use, and correct version messaging.

The connected local test environment may be used for read-sync and observation when the user has confirmed it is a test environment. Never perform remote workout writes, deletions, or destructive provider actions unless a separate disposable target and explicit authorization are provided.

## 8. Complete UI/UX journey audit

Do not review screens in isolation. Exercise full journeys on `mobile-small`, `mobile`, `tablet`, `tablet-landscape`, and `desktop`, plus touch/keyboard where relevant:

- cold start -> loading shell -> login failure/success -> initial bootstrap -> Coach ready;
- ask a read-only question -> receive streaming answer -> navigate away/back -> reload;
- issue every supported Coach mutation and named sync -> observe progress/receipt/result -> reload and verify persistence;
- queue, steer, cancel, retry, recover, and reset Coach conversations;
- view/edit profile, check-in, activities/feedback, performance, plans, library, competitions, connections/operations, privacy, and diagnostics;
- empty, first-use, long-list, long-text, loading, slow, stale, partial, conflict, validation-error, provider-error, offline, session-expired, and maintenance states;
- installation/update/offline/service-worker flow and old-client/new-server compatibility;
- microphone unsupported/denied/granted/timeout/oversized/aborted transcription and editable result;
- notifications unsupported/denied/granted/duplicate/click navigation.

For each journey inspect:

- no blank panel, layout shift that hides controls, clipped content, horizontal overflow, unreachable composer/action, accidental background scrolling, or mobile keyboard trap;
- visible and accurate ownership/source/sync/freshness/pending/error status;
- useful error recovery without losing input or forcing a reload;
- focus order, focus restoration, dialog trapping, semantic names, landmarks/headings, live regions, contrast, motion, touch targets, and axe results;
- browser console exceptions, failed/unexpected network calls, duplicate event listeners, and requests continuing after navigation/logout.

## 9. Runtime observation protocol

1. Record source commit, image/container identity, application version, browser/project, service-worker/cache version, and whether providers are fixtures or test accounts. Do not record secret values.
2. Start or reuse the repository's local Docker runtime without deleting volumes. Confirm health and readiness, then authenticate locally without exposing the password.
3. Establish a clean observable baseline: console, failed requests, pending operations, provider freshness, and current message count/IDs through safe UI/API projections.
4. Execute journeys with deterministic request interception or mocked providers for destructive, rare, and failure states. Use the connected test environment for non-destructive reality checks.
5. After each scenario verify DOM, frontend state, network result, safe API state, reload persistence, and absence of delayed regressions.
6. Re-run race-sensitive scenarios and vary response order. A single successful run does not clear a race risk.
7. Preserve only sanitized evidence. Never attach authenticated storage state or screenshots containing sensitive athlete/provider data.

## 10. Usage-review completion gate

The review is incomplete if any of these remain merely sampled:

- a Coach tool, canonical operation, intent mapping, or mutation path;
- a frontend API caller or backend route;
- a message lifecycle state or race interleaving listed above;
- a provider state, named-sync path, or multi-provider partial-failure case;
- a core journey, error class, or configured viewport;
- a durable effect whose result was not checked after refresh/reload;
- an observed console/network/UI anomaly that was not explained or recorded as a finding/follow-up.

Blocked destructive or unavailable scenarios are acceptable only when individually recorded with the missing prerequisite and the static/test evidence used instead. Existing automated coverage may satisfy a row only after its assertions and production path are inspected.
