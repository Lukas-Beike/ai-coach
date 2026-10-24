# view-refresh-and-client-state Specification

## Purpose

Describe device snapshots, session-scoped client state, view loading, explicit refresh, and sync-event/poll recovery at application revision `b8c911c9dda83a7920171916ace32681c0c38ba0`. A cached view is a device read snapshot, not evidence of current provider data or queued offline writes. Nutrition reads and provider refresh semantics are specified by `nutrition-diary-and-targets` and `nutrition-provider-sync`; shell/controls by `web-pwa-and-accessibility`. Source and existing tests were inspected; the handoff distinguishes actual bounded test execution from unexecuted browser scenarios.

## Requirements

### Requirement: API calls preserve session and response semantics
The client SHALL send same-origin credentials and the current CSRF token for mutations, retain safe status/reason/retry metadata on errors, and reject malformed responses. It SHALL only retry a CSRF-failed mutation when a session-status read supplies a changed token.

#### Scenario: Mutation with refreshed CSRF
- **WHEN** a state-changing request receives 403 and a no-store auth-status request changes the CSRF cookie
- **THEN** the client retries once with the new token; an unchanged token does not cause repeated mutation attempts.

#### Scenario: Network, HTTP, or malformed success
- **WHEN** the request has no response, returns an error, or reports success with invalid JSON/shape or a missing required confirmation
- **THEN** the client surfaces a bounded error with available status/reason/retry delay instead of treating the write as confirmed.

#### Scenario: Timeout or old-session response
- **WHEN** a request exceeds its configured deadline or resolves after session generation changed
- **THEN** the timeout/cancellation or superseded-session result cannot silently update the current session's UI.

Evidence: `public/api.js::send`, `public/api.js::request`, `public/api.js::readResponse`, `public/shared.js::api`; `e2e/contracts.spec.js::JSON and audio errors retain status, reason and retry delay`, `e2e/contracts.spec.js::a delayed old-session 401 cannot log out the new session`, `e2e/contracts.spec.js::profile invalid JSON and incomplete success preserve the dirty draft`. Token-retry policy is inspected source evidence; these named tests are not a complete CSRF transport matrix.

### Requirement: Device reads are cached with bounded precedence
The client SHALL retain a last loaded state snapshot, up to twenty latest persisted Coach messages, and up to twenty-four recent view responses. Message cache SHALL take precedence over older snapshot messages; view cache SHALL be tied to the current asset set.

#### Scenario: Restart with recent messages
- **WHEN** the device has a saved state and separately saved newer Coach messages
- **THEN** the start view uses the newer persisted message page, with a cursor for older history, rather than restoring older snapshot messages over it.

#### Scenario: View read and asset update
- **WHEN** a recent view is reopened or a saved view cache belongs to other assets
- **THEN** matching current-asset reads can display while loading; obsolete view-cache entries are not treated as current-asset responses.

#### Scenario: Storage unavailable or full
- **WHEN** browser storage rejects writes
- **THEN** cache failures do not block the application, lower-priority view cache gives way to message/state storage, and invalid cache JSON is ignored.

Evidence: `public/state-loader.js::rememberChatCache`, `public/state-loader.js::readStateSnapshot`, `public/state-loader.js::rememberViewCache`, `public/state-loader.js::writeStateSnapshot`; `tests/state-loader-startup.test.cjs::shown messages are cached at once as the latest page and replace older snapshot messages`, `tests/state-loader-startup.test.cjs::the view cache keeps recent reads for the same assets and is cleared with the snapshot`, `tests/state-loader-startup.test.cjs::a full storage drops the view cache before the message cache`.

### Requirement: Startup distinguishes cached state from fresh bootstrap
The client SHALL show compatible stored reads promptly while authentication and fresh state load, and show a noninteractive update-loading screen for a snapshot from different assets. Stored data SHALL not establish fresh server versions or trigger notifications as newly loaded state.

#### Scenario: Normal cached start
- **WHEN** a compatible snapshot exists
- **THEN** it can appear immediately while auth/bootstrap refreshes it, with message synchronization state until fresh chat arrives.

#### Scenario: Start after asset update
- **WHEN** a saved snapshot belongs to an earlier asset set
- **THEN** update processing stays visible until fresh bootstrap/state is available; a server-unreachable start can fall back to the stored data and retry authentication later.

#### Scenario: Slow or failed area
- **WHEN** one startup area is slow or fails while others load
- **THEN** usable prior values remain for the pending/failed area while successful areas replace and save their own data; placeholders are not persisted as a successful full read.

Evidence: `public/auth.js::bootstrapAuth`, `public/auth.js::showStateSnapshot`, `public/state-loader.js::withShownSnapshotAreas`, `public/state-loader.js::render`; `e2e/update-start.spec.js::a start after an update shows the update loading screen until fresh data loads @responsive`, `tests/state-loader-startup.test.cjs::snapshot data never overrides the startup bootstrap or claims its versions`, `tests/state-loader-startup.test.cjs::a failed area keeps its previous snapshot value while the others are stored early`.

### Requirement: Session and privacy transitions invalidate device state
The client SHALL clear cached state, view reads, and recent messages when login becomes required or privacy data is deleted, and invalidate already-started loads so deleted or previous-session data cannot reappear.

#### Scenario: Logout or current-session unauthorized response
- **WHEN** successful logout, an unauthenticated start, or a current-session 401 requires login
- **THEN** cached athlete reads are removed, streams/queues and view state are reset, and the app is locked.

#### Scenario: Privacy deletion during a read
- **WHEN** a load started before confirmed privacy deletion resolves afterward
- **THEN** its old sequence/cache epoch cannot render or save deleted records.

#### Scenario: Replaced login session
- **WHEN** the athlete logs in again before an old session's delayed load, receipt, or transcription returns
- **THEN** generation checks keep that old result from affecting the new session.

Evidence: `public/auth.js::showLogin`, `public/state-loader.js::clearStateSnapshot`, `public/settings.js::deletePrivacyData`, `public/shared.js::apiAudio`; `tests/state-loader-startup.test.cjs::a load that started before a privacy deletion is dropped`, `tests/state-loader-startup.test.cjs::area responses of a replaced session or load are neither rendered nor stored`, `e2e/contracts.spec.js::delayed receipt and transcription cannot alter a new session`.

### Requirement: Independent area loads render as they arrive
The client SHALL start independent requested area reads alongside bootstrap, render successful current results without waiting for slower areas, and coalesce overlapping requests into bounded follow-up loads while retaining accurate requested versions.

#### Scenario: Fast area and slow area
- **WHEN** one requested area arrives before another
- **THEN** the fast area's current data renders and becomes cacheable without waiting for the slower response.

#### Scenario: Overlapping refreshes
- **WHEN** more reload requests arrive while a load is running
- **THEN** requested areas merge into a follow-up load and a version already requested is not redundantly requested again.

#### Scenario: Newer load supersedes older work
- **WHEN** a load sequence or session is replaced
- **THEN** late old-area results neither render nor write caches and cannot claim versions that arrived after their request started.

Evidence: `public/state-loader.js::loadState`, `public/state-loader.js::renderAreasAsTheyArrive`, `public/state-loader.js::load`, `public/sync-status.js::changedSyncAreas`; `tests/state-loader-startup.test.cjs::area reads start before the bootstrap response arrives`, `tests/state-loader-startup.test.cjs::each area is rendered and stored as soon as it arrives, without waiting for a slower one`, `tests/reload-coalescing.test.cjs::reloads requested during a load run as one follow-up`, `tests/reload-coalescing.test.cjs::a live load records the version it was started for, not one that arrived while it ran`.

### Requirement: Explicit view refresh reports only its matching view
The client SHALL issue one refresh at a time per refresh control, retain visible values during refresh, and report completion only after the matching view reload succeeds. Route, selected date/period, and view key SHALL guard delayed results.

#### Scenario: Successful, partial, or local refresh
- **WHEN** a synchronous refresh or completed job reports success, partial, or local status
- **THEN** the matching view reloads and announces the corresponding full, partial, or local result after reload succeeds.

#### Scenario: Repeated click or changed selection
- **WHEN** the control is clicked again while running or the athlete changes route, date, query, or period before completion
- **THEN** duplicate refresh is suppressed and the superseded result does not announce success or repaint the wrong selected view.

#### Scenario: Failure or already-running operation
- **WHEN** refresh/reload fails or the server reports an existing running refresh
- **THEN** failure is shown without a success announcement, or already-running status is shown without unnecessary reload; controls recover from busy state.

Evidence: `public/view-refresh.js::AppViewRefresh.create`, `public/nutrition.js::nutritionRefresh`, `public/analysis.js::analysisRefresh`; `tests/view-refresh.test.cjs::does not announce or reload when the route or selected request changed`, `tests/view-refresh.test.cjs::reports a refresh reload failure instead of announcing success`, `tests/view-refresh.test.cjs::waits for a queued job and reports partial completion after reloading`, `e2e/view-refresh.spec.js::@responsive view refresh targets its active area and ignores stale views`.

### Requirement: Refresh scope follows active domain and selection
The client SHALL use the active analysis/nutrition refresh endpoint and selected area/period rather than invoking broad sync or nutrition export. Nutrition product refresh SHALL preserve the selected query; body refresh SHALL let the server choose the athlete-local date.

#### Scenario: Analysis refresh
- **WHEN** the athlete refreshes load, recovery, sessions, or performance
- **THEN** the request names the active analysis area and applicable fourteen/eighty-four-day period; the relevant reports are reread under the analysis contract.

#### Scenario: Nutrition refresh
- **WHEN** the athlete refreshes diary, history, body, or products
- **THEN** the client sends only the matching nutrition area and relevant date/period; it never substitutes `/api/nutrition/sync` for refresh.

#### Scenario: Product query and lookup race
- **WHEN** a selected product search is refreshed or a barcode result arrives while a background product list is loading
- **THEN** the selected query is retained and the older background result cannot overwrite the newer explicit lookup.

Evidence: `public/nutrition.js::nutritionRefresh`, `public/nutrition.js::loadNutritionProducts`, `public/analysis.js::analysisRefreshDays`; `tests/view-refresh.test.cjs::nutrition product refresh reload preserves the selected search query`, `tests/view-refresh.test.cjs::nutrition body refresh lets the server choose the athlete-local date`, `tests/nutrition-lookup-status.test.cjs::a product reload started before the lookup cannot overwrite its result`, `e2e/view-refresh.spec.js::@responsive view refresh targets its active area and ignores stale views`.

### Requirement: Lazy reports and details retain cache and request ownership
The client SHALL load expensive report/detail views when needed, cache appropriate read responses by path and state version, and reject obsolete route/detail results. Opening local activity details SHALL not itself initiate an implicit provider refresh.

#### Scenario: Revisit a cached report
- **WHEN** an unchanged report path/state-version is requested again
- **THEN** its cached or in-flight read can be reused; explicit invalidation permits a new read.

#### Scenario: Close or replace details
- **WHEN** an activity detail dialog or selected analysis view changes before its response arrives
- **THEN** its obsolete generation cannot paint the newly selected detail/view.

#### Scenario: Incomplete activity details
- **WHEN** a local activity lacks provider detail
- **THEN** the UI preserves available metadata/gaps and offers the explicit detail-refresh operation instead of hiding the activity or fetching provider detail just by opening it.

Evidence: `public/analysis.js::requestAnalysisReport`, `public/analysis.js::clearAnalysisReportCache`, `public/activity-details.js::open`, `public/activity-analysis.js::render`; `tests/analysis-report-cache.test.cjs::training records are reused for the same state version until invalidated`, `e2e/analysis-on-demand.spec.js::@responsive equipment records load only on the equipment route and stay cached`, `e2e/activity-details.spec.js::@responsive analysis lists sessions whose details failed to load`. Cache and detail request implementation was inspected; browser behavior was not executed by this worker.

### Requirement: Background updates coordinate events and polling
The client SHALL use authenticated state events when available, coalesce changed-area reloads, reconnect with bounded backoff, and fall back to status polling when event delivery is unavailable or stale. Hidden/offline views SHALL release their active polling/event resources appropriately.

#### Scenario: Healthy event stream
- **WHEN** ready/heartbeat and state-change events arrive
- **THEN** replay baseline is respected, changed areas coalesce, and Coach status uses its slow safety check rather than constant fast polling.

#### Scenario: Event interruption or multiple tabs
- **WHEN** event delivery fails or another tab owns the optional sync-poll lease
- **THEN** reconnect/poll fallback remains bounded, lease/broadcast coordination avoids needless duplicate sync polling, and storage denial does not disable sync monitoring.

#### Scenario: Active sync and visibility change
- **WHEN** sync is running, idle, hidden, or offline
- **THEN** the ordinary sync poll uses active/idle/retry intervals and hidden/offline transitions close events or release/abort the relevant poll; returning visible triggers fresh status checking.

Evidence: `public/sync-status.js::connectStateEvents`, `public/sync-status.js::handleStateEvent`, `public/sync-status.js::pollSyncStatus`, `public/sync-status.js::syncPollLeaseAvailable`, `public/coach.js::pollChatStatus`; `tests/reload-coalescing.test.cjs::the status is not polled every 1.5 seconds while the event stream is healthy`, `tests/reload-coalescing.test.cjs::a silently stalled event stream switches to the fast check once it counts as stale`, `e2e/state-events.spec.js::hidden and offline pages release status streams and resume only one connection`.

### Requirement: Busy Coach turns defer bounded background work
The client SHALL defer nonessential automatic area reloads during an active Coach turn while keeping transcript/profile and athlete-initiated operations live. Deferred background work SHALL coalesce and run when the turn ends or the sixty-second cap is reached.

#### Scenario: Provider event during a turn
- **WHEN** a background provider/planning refresh arrives while the Coach is busy
- **THEN** nonlive areas wait and merge rather than causing repeated broad reloads during the turn.

#### Scenario: Athlete action or transcript update
- **WHEN** the athlete performs an explicit refresh or live chat/profile data changes
- **THEN** that direct/live work proceeds without waiting behind the background deferral.

#### Scenario: Turn ends or session is cleared
- **WHEN** the turn finishes, sixty seconds elapse, or login becomes required
- **THEN** deferred work runs once under the current session or is cancelled when the session ends.

Evidence: `public/state-loader.js::requestBackgroundLoad`, `public/state-loader.js::deferBackgroundLoad`, `public/state-loader.js::flushDeferredLoads`, `public/auth.js::showLogin`; `tests/reload-coalescing.test.cjs::background reloads wait while the Coach works and run once after 60 seconds`, `tests/reload-coalescing.test.cjs::athlete actions and the live transcript do not wait for a busy Coach`, `tests/reload-coalescing.test.cjs::leaving the session drops the waiting background reloads`.
