## Purpose

Describe the private athlete-facing PWA shell, navigation, accessible controls, safe content, Coach interaction, and operational UIs at application revision `b8c911c9dda83a7920171916ace32681c0c38ba0`. This is an inspected brownfield contract, not a claim of full browser execution or universal accessibility compliance. Durable training, planning, performance, activity, profile, history/undo, authentication, credentials, backup/restore, and privacy effects belong to their domain specifications. Nutrition behavior is specified in `nutrition-diary-and-targets` and `food-catalog-and-meal-library`; refresh/cache behavior in `view-refresh-and-client-state`; microphone/notification behavior in `voice-and-notifications`.

## ADDED Requirements

### Requirement: Hash navigation selects one semantic active view
The client SHALL provide Coach, plan, nutrition, analysis, and more navigation with supported subroutes, an active-page indication, browser history, and focus transfer. Unknown hashes SHALL resolve to the Coach route.

#### Scenario: Direct or back navigation
- **WHEN** the athlete selects or returns to a recognized hash
- **THEN** the matching panel and segment render once, inactive panels stay hidden, and navigation exposes the current page.

#### Scenario: Unsaved profile form
- **WHEN** navigation would leave a dirty profile panel
- **THEN** the athlete can cancel discarding edits and remain on that route; ordinary navigation does not silently drop the dirty form.

#### Scenario: Return to Coach or today's plan
- **WHEN** the athlete returns to Coach or opens the plan overview
- **THEN** route-specific scroll restoration preserves Coach reading position or reveals the planned-today section according to the recorded navigation state.

Evidence: `public/navigation.js::AppRouter.navigate`, `public/shared.js::restoreRouteScroll`, `public/views.js::renderPlanSegments`; `e2e/navigation.spec.js::@responsive each hash navigation renders its target once`, `e2e/coach.spec.js::login, main views, dialog and profile form state`, `e2e/contracts.spec.js::plan overview deep link focuses and reveals today after loading`.

### Requirement: Responsive controls remain named and keyboard reachable
The client SHALL use semantic labels, focusable controls and scroll regions, current-route indications, and responsive layouts for the supported mobile, tablet, and desktop views. Icon actions SHALL retain accessible names and the existing touch target sizing.

#### Scenario: Narrow viewport or on-screen keyboard
- **WHEN** the viewport narrows, rotates, or shrinks around a focused chat input
- **THEN** the composer and relevant controls remain reachable using the visible viewport and safe-area layout instead of being covered by navigation.

#### Scenario: Dialog opens and closes
- **WHEN** an accessible application dialog opens and later closes
- **THEN** initial focus enters an available control and returns to the connected, enabled originating control when appropriate.

#### Scenario: Tables, charts, and reduced motion
- **WHEN** content exceeds the viewport or reduced motion is requested
- **THEN** designated scroll regions remain keyboard focusable and labelled, chart/table alternatives remain available, and reduced-motion CSS applies to the relevant animations.

Evidence: `public/components.js::showAccessibleDialog`, `public/components.js::restoreDialogFocus`, `public/shared.js::updateMobileViewportLayout`, `public/shared.js::makeScrollRegionFocusable`, `public/styles.css` (touch targets, safe-area, focus-visible, reduced-motion rules); `e2e/coach.spec.js::core views satisfy WCAG AA checks`, `e2e/coach-layout.spec.js::coach composer keeps a stable bottom edge and publishes its height @responsive`, `e2e/analysis-info.spec.js::@responsive legend info buttons are at least 44x44 and never overlap each other`. These tests were inspected; no browser accessibility scan ran here.

### Requirement: Markdown and external display text remain inert
The client SHALL escape untrusted content before rendering its supported Markdown, permit only supported HTTP(S) links, and render external values through safe text or escaped templates. Tables SHALL have semantic headers and labelled scroll containers.

#### Scenario: Script-like content
- **WHEN** Coach/provider text contains raw HTML, scripts, event-handler-looking attributes, or unsafe link schemes
- **THEN** the text does not become executable markup through Markdown rendering.

#### Scenario: Supported formatting
- **WHEN** a message contains headings, lists, code, emphasis, or valid HTTP(S) links
- **THEN** supported formatting renders while links open with `noopener noreferrer` and code content remains escaped.

#### Scenario: Markdown table
- **WHEN** a valid table delimiter row follows a header
- **THEN** the client renders header/body cells with escaped contents in a keyboard-focusable labelled region; table-looking lines inside code fences stay code.

Evidence: `public/views.js::inlineMarkdown`, `public/views.js::replaceMarkdownLinks`, `public/views.js::markdownToHtml`, `public/activity-details.js::node`; `tests/markdown-table.test.cjs::table cells are escaped and never pass raw HTML through`, `tests/markdown-table.test.cjs::a table inside a code fence is rendered as code, not as a table`, `e2e/contracts.spec.js::Markdown links preserve URLs and format labels without interpreting markup`.

### Requirement: Installable shell has a coherent offline asset set
The PWA SHALL advertise its standalone manifest and precache the current shell asset set. The service worker SHALL exclude API requests and non-GET mutations from offline asset caching and retain exact versioned-asset matching.

#### Scenario: Fresh installation
- **WHEN** the service worker installs successfully
- **THEN** the declared current shell, scripts, styles, icons, and manifest are cached as one versioned set.

#### Scenario: Asset update
- **WHEN** a new worker activates
- **THEN** obsolete shell caches are removed and clients are claimed; versioned asset requests use their matching cached URL or fetch/cache that exact asset.

#### Scenario: Offline or slow navigation
- **WHEN** navigation cannot reach the server or exceeds the shell's short network wait and a cached page exists
- **THEN** the cached shell can start; API writes are not queued for later delivery and loaded data freshness remains governed by `view-refresh-and-client-state`.

Evidence: `public/service-worker.js` (install/activate/fetch listeners, `ASSETS`, `VERSIONED_ASSETS`), `public/manifest.webmanifest`, `public/notifications.js::registerServiceWorker`; `e2e/contracts.spec.js::fresh service worker keeps the current shell available offline`, `tests/test_nutrition_frontend_contract.py::NutritionFrontendContractTests.test_camera_and_product_assets_are_versioned_in_pwa_cache`, `e2e/offline-errors.spec.js::the offline banner states that changes are not saved and promises no later delivery @responsive`.

### Requirement: Locked and failing sessions show concrete safe states
The client SHALL keep the application behind the required login dialog until successful authentication, distinguish login failure reasons, clear device state when authentication ends, and show bounded connectivity and maintenance states.

#### Scenario: Dismiss locked login
- **WHEN** Escape or dialog closure is attempted while login is required
- **THEN** the login remains required and focus returns to the password field rather than leaving an inaccessible blank app.

#### Scenario: Rejected or rate-limited login
- **WHEN** a wrong password, rate limit, transient server failure, persistent configuration error, timeout, or missing connection occurs
- **THEN** the UI displays the corresponding message, using the returned retry delay where supplied, and restores the login control for retry.

#### Scenario: Logout or maintenance
- **WHEN** confirmed logout succeeds, a current-session 401 arrives, or restore maintenance is active
- **THEN** the client clears/locks according to the session contract or shows the maintenance pause; a failed logout leaves the session available for retry.

Evidence: `public/auth.js::installLoginDialogGuards`, `public/auth.js::loginErrorMessage`, `public/auth.js::logout`, `public/auth.js::showLogin`, `public/sync-status.js::renderMaintenanceStatus`; `e2e/login-dialog.spec.js::Escape keeps the login dialog open and logout shows it again @responsive`, `tests/login-errors.test.cjs::a rate-limited login names the wait from Retry-After`, `tests/login-errors.test.cjs::a lasting server error keeps its own message instead of asking to retry`.

### Requirement: Composer follows desktop and touch input conventions
The client SHALL support editable multiline Coach drafts, sending with the explicit send control, desktop Enter-to-send, and touch-first Enter-for-newline. IME composition SHALL never submit a turn.

#### Scenario: Desktop keyboard
- **WHEN** Enter is pressed outside composition on a desktop pointer device
- **THEN** the form submits; Shift+Enter inserts a newline.

#### Scenario: Touch-first device
- **WHEN** Enter is pressed on a touch-first device
- **THEN** it inserts a newline; the send button or Ctrl/Cmd+Enter without Shift submits.

#### Scenario: Composer grows or Coach works
- **WHEN** the draft grows, the Coach becomes busy, or voice status appears
- **THEN** the composer resizes within its bounds and keeps the existing control layout and bottom-edge behavior without a busy-state height jump.

Evidence: `public/coach.js::chatEnterAction`, `public/coach.js::resizeChatInput`, `public/coach.js::publishComposerHeight`, `public/shared.js::hasTouchFirstInput`; `tests/coach-enter.test.cjs::desktop Enter sends the draft`, `tests/coach-enter.test.cjs::IME composition never triggers an action`, `tests/coach-enter.test.cjs::touch Ctrl/Cmd+Enter sends from a physical keyboard`, `e2e/coach-composer.spec.js::composer height does not change while busy @responsive`.

### Requirement: Streamed Coach responses preserve recoverable turn state
The client SHALL display incremental response text and distinguish started, background, completed, rejected, recovering, and cancelled turns. A transport failure SHALL not silently resend an already accepted turn or erase its draft/recovery path.

#### Scenario: Normal streamed completion
- **WHEN** a submitted turn emits deltas and a persisted completion receipt
- **THEN** incremental text appears, the completed message/receipts replace transient output, the finite reader is released, and a follow-up can be sent.

#### Scenario: Definite rejection or unknown transport outcome
- **WHEN** the server definitely rejects a message or the transport ends without a known terminal result
- **THEN** a definite rejection restores the draft or retains it separately from a newer draft; an unknown outcome enters receipt/status recovery using the same turn identity.

#### Scenario: Explicit stop or next message
- **WHEN** the athlete stops a running response or queues a follow-up
- **THEN** stop targets the matching operation, busy-state follow-ups retain their order/content, and later completion/recovery controls do not act on a replacement session.

Evidence: `public/coach.js::readChatStream`, `public/coach.js::recoverChatRequestFailure`, `public/coach.js::drainChatQueue`, `public/coach.js::cancelChat`; `e2e/contracts.spec.js::every definite HTTP rejection retains the draft and concrete error`, `e2e/contracts.spec.js::a completed answer accepts an immediate follow-up without showing a queue`, `e2e/audit-remediation.spec.js::cancel before stream identity is retained for the matching operation`. Durable Coach effects, receipts, approvals, and undo use the Coach/history specifications.

### Requirement: Chat reading position and message actions remain stable
The client SHALL keep history reading independent of live announcements, preserve a reader's position while older pages or new content arrive, and offer explicit return-to-latest, message copy/edit, and server-authorized receipt/undo actions.

#### Scenario: Read older messages during a reply
- **WHEN** the athlete scrolls away from the latest content while a response arrives
- **THEN** automatic following stops and an explicit jump control makes the latest message/composer reachable.

#### Scenario: Load older history
- **WHEN** older messages are requested
- **THEN** they append/prepend without duplication and the visible reading anchor/focus is restored rather than jumping to the newest answer.

#### Scenario: Copy, edit, or inspect a receipt
- **WHEN** the athlete selects a prior message or completed change receipt
- **THEN** copy/edit creates ordinary editable draft content, and receipt navigation/undo delegates to the relevant domain action rather than inventing a new local mutation.

Evidence: `public/coach.js::chatUserScrolledAway`, `public/coach.js::restoreChatHistoryAnchor`, `public/coach.js::renderMessageNode`, `public/coach.js::undoCoachTurn`; `e2e/contracts.spec.js::a prior user message can be copied or edited as a regular draft`, `e2e/coach.spec.js::coach reload opens at the latest message and tab navigation restores the scroll position`, `e2e/coach-history-anchor.spec.js::older chat history keeps the reading position without moving focus @responsive`. Announcement updates are bounded by `public/coach.js::announceChatStatus` and `e2e/coach.spec.js::chat status announcements update once and keep history outside the live region @responsive`.

### Requirement: Attachments stay bound to their own editable turn
The client SHALL accept bounded GPX, FIT, JPEG, PNG, and WebP attachments, expose their names/types and removal controls, and preserve each submitted or queued message's own attachment set. Attachment processing SHALL not silently replace another draft or session.

#### Scenario: Attach without text
- **WHEN** a valid attachment is added to an otherwise empty draft
- **THEN** sending becomes available, removal can return it to an empty disabled draft, and the server still validates the attachment.

#### Scenario: Queue two attachment messages
- **WHEN** separate messages with separate files are queued during a turn
- **THEN** each outgoing message retains its own files rather than inheriting the current composer's file list.

#### Scenario: Invalid selection or rejected upload
- **WHEN** selection exceeds four files or file bounds, or server validation rejects the upload
- **THEN** invalid additions do not partially mutate the draft, and the rejected message/files remain recoverable for correction.

Evidence: `public/coach.js::validateChatAttachmentFiles`, `public/coach.js::prepareChatAttachment`, `public/coach.js::renderChatAttachments`, `backend/coach/attachments.py::validate_attachments`; `e2e/attachments.spec.js::attachments can be removed, rejected and sent with an empty text draft`, `e2e/attachments.spec.js::attachments stay with their own queued message`, `tests/test_coach_attachments.py::AttachmentTests.test_invalid_upload_does_not_create_a_command`. Packaging-image preparation uses `nutrition-photo-analysis`; general Coach attachment storage/retention is governed by the Coach domain, and is not promised transient like label extraction.

### Requirement: Connection UI protects secrets and exposes explicit provider actions
The client SHALL show safe configured/connected/source/freshness states, accept credential input only for explicit saves, and never prefill secret credential values. Provider connection, disconnection, resync, and automatic metric-export consent SHALL remain explicit actions.

#### Scenario: Save credentials or poll connection state
- **WHEN** the athlete saves a credential form or background state renders
- **THEN** only nonblank submitted fields are sent, secret inputs are cleared after success/failure, polling does not overwrite typed input, and stored-value removal requires confirmation.

#### Scenario: Garmin login or MFA
- **WHEN** Garmin requests MFA, completes login, or is disconnected
- **THEN** the card shows the appropriate form/connected state, clears submitted password/code values, and asks before disconnecting.

#### Scenario: Wahoo or export consent
- **WHEN** the athlete starts Wahoo connection or enables Garmin-to-Intervals metric export
- **THEN** the UI follows only an HTTPS authorization URL or explicit consent action and renders the returned connection/export receipt without browser token exposure.

Evidence: `public/provider-connections.js::saveProviderCredentials`, `public/provider-connections.js::renderGarminCard`, `public/provider-connections.js::toggleMetricExport`, `public/wahoo-connection.js::connectWahoo`, `public/sync-actions.js::fullResync`; `tests/provider-connections.test.cjs::saving sends only non-blank values and leaves no secret in the DOM`, `tests/provider-connections.test.cjs::re-rendering from polling never writes input values`, `tests/wahoo-connection.test.cjs::only https authorize URLs are followed`, `tests/metric-export.test.cjs::declining consent never saves an automatic export setting`. Provider durable authorization and conflict rules remain in their domain contracts.

### Requirement: Settings preserve explicit choices and unsaved edits
The client SHALL expose server-advertised model, thinking, and speed capabilities; profile and operational settings; and device appearance choices. Save controls SHALL reflect pending/error state and avoid claiming success without an accepted server response.

#### Scenario: Model capability changes
- **WHEN** an explicit model, thinking level, or service tier is selected
- **THEN** the client submits the dedicated setting, reloads the accepted server state, and renders only supported options rather than silently choosing a different provider.

#### Scenario: Profile save overlaps newer typing
- **WHEN** a profile save is in flight and the athlete continues editing
- **THEN** the newer edits remain visible/dirty; invalid JSON or an incomplete save response does not mark the draft saved.

#### Scenario: Device and read settings
- **WHEN** appearance, calendar horizon, or activity-detail start date changes
- **THEN** appearance persists on the device with system/light/dark support, while server-owned settings use their explicit API and report validation errors.

Evidence: `public/settings.js::saveProfile`, `public/settings.js::saveModel`, `public/settings.js::saveThinkingLevel`, `public/settings.js::saveServiceTier`, `public/shared.js::applyAppearance`, `public/appearance.js` (early theme projection), `public/views.js::renderModel`; `e2e/model-settings.spec.js::model and speed selection persist with capability checks @responsive`, `e2e/audit-remediation.spec.js::profile edits made while saving remain dirty and visible`, `e2e/contracts.spec.js::appearance choice updates the theme and survives reload on this device`, `e2e/activity-detail-floor.spec.js::@responsive an empty day is rejected and keeps the saved value`.

### Requirement: Diagnostics and destructive operational controls retain reviewable outcomes
The client SHALL expose operations through their explicit controls, keep downloads and destructive requests visibly pending, request applicable confirmation, and display failures without implying a completed restore/deletion. Diagnostic values SHALL be displayed as inert text.

#### Scenario: Download or delete technical diagnostics
- **WHEN** the athlete requests logs/diagnostics or confirms their deletion
- **THEN** the client uses the corresponding authenticated endpoint, restores controls after completion/error, and shows the returned outcome; formatted log text is not executable HTML.

#### Scenario: Restore or privacy deletion
- **WHEN** the athlete starts restore or typed-confirmed privacy deletion
- **THEN** the UI follows the backup/privacy contract, retains failed-action recovery, and clears session/device state after a successful destructive transition as appropriate.

#### Scenario: Timeout, network failure, or persistent error
- **WHEN** an operational request cannot be confirmed
- **THEN** an error toast remains readable and dismissible, and the UI does not announce success or promise offline deferred delivery.

Evidence: `public/diagnostics.js::loadLogs`, `public/diagnostics.js::deleteDiagnostics`, `public/settings.js::restoreDatabaseBackup`, `public/settings.js::deletePrivacyData`, `public/shared.js::toast`; `e2e/state-events.spec.js::short-lived status connections back off while logs and diagnostics stay usable`, `e2e/privacy-delete.spec.js::local data deletion requires the exact confirmation text`, `e2e/toast.spec.js::@responsive error toasts are readable, dismissible and stay above the coach composer`, `e2e/offline-errors.spec.js::a failed request without a server response shows an honest German message @responsive`. Backend diagnostic sanitization and restore validation belong to their own domains.

### Requirement: Domain views preserve supplied facts and source distinctions
The client SHALL present domain-provided planning, performance, activity, and equipment facts with their dates, units, source distinctions, and missing-data states. Rendering or opening a domain view SHALL not itself substitute for an authorized durable domain action.

#### Scenario: Agenda, library, and season
- **WHEN** the athlete opens plan overview, library, or season
- **THEN** the agenda prioritizes dates and sessions with expandable weather/details, the active undated library is grouped by sport, and season calculations retain their evidence and estimate labels; explicit preview/apply/export effects remain governed by the planning domain.

#### Scenario: Performance and recovery charts
- **WHEN** domain series contain sparse, stale, current, or missing observations
- **THEN** charts/tables retain dates, gaps, provenance and period-specific coverage, distinguish current reference lines from historical observations, and avoid fabricating normal ranges or duplicate prediction charts.

#### Scenario: Activity list and detail measurements
- **WHEN** the athlete expands a completed session or activity details
- **THEN** sport-appropriate pace/speed and cadence/step-frequency channels, units, missing points, and available metadata remain readable; failed detail loading retains the session summary and its explicit refresh path.

#### Scenario: Equipment and maintenance
- **WHEN** equipment is displayed or maintenance is requested
- **THEN** local authoritative items and imported/archived sources remain distinguishable, and only eligible active local gear offers the maintenance action under the equipment domain contract.

Evidence: `public/plan-views.js::renderPlanned`, `public/plan-views.js::renderLibrary`, `public/analysis.js::renderAnalysisHistory`, `public/analysis.js::renderTrainingRecords`, `public/performance-view.js::renderPerformance`, `public/activity-analysis.js::renderPanel`, `public/activity-details.js::render`; `e2e/contracts.spec.js::planned agenda prioritizes dates and sessions with compact weather and expandable details`, `e2e/analysis-info.spec.js::@responsive latest measurement stays visible without inventing measurements in empty weeks`, `e2e/activity-details.spec.js::@responsive analysis lists sessions whose details failed to load`, `e2e/training-feature-panels.spec.js::@responsive equipment keeps local authority and groups archived sources`. Source sections and these browser scenarios were inspected; this requirement does not independently re-specify backend calculations.

### Requirement: Action reviews distinguish known rejection from unknown outcome
The client SHALL offer confirmation only for current confirmable proposals, preserve pending/failed/completed receipt states, and keep an action locked when its execution outcome cannot be confirmed. Reconciliation SHALL determine whether retry is safe rather than automatically repeating an uncertain write.

#### Scenario: Current authorized action
- **WHEN** a pending current proposal exposes a confirmable action
- **THEN** the client presents its concrete review/diff and submits the identified server action, showing the resulting receipt and available domain navigation/undo affordances.

#### Scenario: Definite conflict rejection
- **WHEN** execution receives a definite client/conflict rejection
- **THEN** the client reports the rejection and can restore the action's retryable controls according to the returned proposal state.

#### Scenario: Lost response after execution
- **WHEN** a sent execution loses its response or receives an ambiguous server error
- **THEN** the proposal remains locked as unknown until reconciliation confirms consumed or still-confirmable state; a failed reconciliation does not unlock it for duplicate execution.

Evidence: `public/coach.js::coachActionButtons`, `public/coach.js::executeCoachActionProposal`, `public/coach.js::reconcileCoachActionProposal`, `public/components.js::createActionReceipt`; `e2e/contracts.spec.js::only current pending proposals expose an explicit confirmation action`, `tests/frontend-write-safety.test.cjs::a 409 rejection after execute was sent is a known failure and unlocks the proposal`, `tests/frontend-write-safety.test.cjs::a lost execute response keeps the action locked and is not reported as a failed confirmation`, `tests/frontend-write-safety.test.cjs::a failed reconcile keeps the unknown-outcome lock`.
