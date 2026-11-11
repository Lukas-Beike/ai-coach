# web-pwa-and-accessibility Specification

## Purpose

Describe the private athlete-facing PWA shell, navigation, accessible controls, safe content, Coach interaction, and operational UIs. This is an inspected brownfield contract, not a claim of full browser execution or universal accessibility compliance. Durable training, planning, performance, activity, profile, history/undo, authentication, credentials, backup/restore, and privacy effects belong to their domain specifications. Nutrition behavior is specified in `nutrition-diary-and-targets` and `food-catalog-and-meal-library`; refresh/cache behavior in `view-refresh-and-client-state`; microphone/notification behavior in `voice-and-notifications`.

## Requirements

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

Evidence: `public/navigation.js::AppRouter.navigate`, `public/shared.js::restoreRouteScroll`, `public/views.js::renderPlanSegments`; `e2e/navigation.spec.js::@responsive each hash navigation renders its target once`, `e2e/coach.spec.js::login, main views, dialog and profile form state`, `e2e/settings-hub.spec.js::@responsive sports are toggle chips of at least 44 px and need no hint`, `e2e/contracts.spec.js::plan overview deep link focuses and reveals today after loading`.

### Requirement: Responsive controls remain named and keyboard reachable
The client SHALL use semantic labels, focusable controls and scroll regions, current-route indications, and responsive layouts for the supported mobile, tablet, and desktop views. Icon actions SHALL retain accessible names and the existing touch target sizing.

#### Scenario: Narrow viewport or on-screen keyboard
- **WHEN** the viewport narrows, rotates, or shrinks around a focused chat input
- **THEN** the composer and relevant controls remain reachable using the visible viewport and safe-area layout instead of being covered by navigation.

#### Scenario: Large text size
- **WHEN** the text size grows up to 200 %
- **THEN** navigation labels that no longer fit collapse to named icons and the status strip wraps, so neither clips text nor leaves the viewport.

#### Scenario: Dialog opens and closes
- **WHEN** an accessible application dialog opens and later closes
- **THEN** initial focus enters an available control and returns to the connected, enabled originating control when appropriate.

#### Scenario: Tables, charts, and reduced motion
- **WHEN** content exceeds the viewport or reduced motion is requested
- **THEN** designated scroll regions remain keyboard focusable and labelled, chart/table alternatives remain available, and reduced-motion CSS applies to the relevant animations.

Evidence: `public/components.js::showAccessibleDialog`, `public/components.js::restoreDialogFocus`, `public/shared.js::updateMobileViewportLayout`, `public/shared.js::makeScrollRegionFocusable`, `public/styles.css` (touch targets, safe-area, focus-visible, reduced-motion, large-text navigation container rules); `e2e/coach.spec.js::core views satisfy WCAG AA checks`, `e2e/text-reflow.spec.js::@responsive navigation and banners keep their text inside at 200 % text size`, `e2e/coach-layout.spec.js::coach composer keeps a stable bottom edge and publishes its height @responsive`, `e2e/analysis-info.spec.js::@responsive legend info buttons are at least 44x44 and never overlap each other`. These tests were inspected; no browser accessibility scan ran here.

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
The PWA SHALL advertise a standalone manifest named "Pacecraft · AI Coach" (short name "Pacecraft") and precache the current shell asset set. The server SHALL stamp the `?v=` asset versions and the service worker cache name `pacecraft-<hash>` from the content of the shell assets when serving; source files carry no versions. API requests and non-GET mutations SHALL NOT be cached.

#### Scenario: Fresh installation
- **WHEN** the service worker installs successfully
- **THEN** the declared current shell, scripts, styles, icons, and manifest are cached as one versioned set.

#### Scenario: Asset update
- **WHEN** a new worker installs and activates
- **THEN** it takes over at once, obsolete shell caches are removed and clients are claimed; versioned asset requests use their matching cached URL or fetch/cache that exact asset.

#### Scenario: Release asset set
- **WHEN** the shell assets change
- **THEN** every stamped reference in the served `index.html` appears in the served service-worker precache list, and the cache name changes exactly when a cached asset changes.

#### Scenario: Open page after an update
- **WHEN** a replaced worker takes control of an open page
- **THEN** the page reloads once, only while no unsaved edit, pending input, attachment, running Coach job, recording, load or open dialog would be lost; otherwise the reload waits until the page is hidden or the blocker ends.

#### Scenario: Offline or slow navigation
- **WHEN** navigation cannot reach the server or exceeds the shell's short network wait and a cached page exists
- **THEN** the cached shell can start; API writes are not queued for later delivery and loaded data freshness remains governed by `view-refresh-and-client-state`.

Evidence: `public/service-worker.js` (install/activate/fetch listeners, `CACHE`, `ASSETS`, `VERSIONED_ASSETS`), `public/manifest.webmanifest`, `public/notifications.js::registerServiceWorker`, `public/notifications.js::reloadForUpdateWhenSafe`; `e2e/contracts.spec.js::fresh service worker keeps the current shell available offline`, `tests/test_server_frontend.py::ServerFrontendTests.test_pwa_asset_versions_match_service_worker_precache`, `e2e/update-reload.spec.js::a service worker update keeps a typed draft and reloads once it is cleared`, `tests/test_nutrition_frontend_contract.py::NutritionFrontendContractTests.test_camera_and_product_assets_are_versioned_in_pwa_cache`, `e2e/offline-errors.spec.js::the offline banner states that changes are not saved and promises no later delivery @responsive`. The manifest name and short name have no covering test.

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

### Requirement: One status strip ranks the notices above every screen
The client SHALL show at most one status strip above every screen: the most severe notice as text, the others behind a count button. Severity SHALL rank the start loading notice, which shows alone, then maintenance, offline, OpenAI key, Coach error, data load failure, provider attention, Garmin hint, thresholds, and last the dismissible Intervals.icu key hint, which appears only when nothing else does.

#### Scenario: Age of device data
- **WHEN** the offline or load-failure notice shows data from the device
- **THEN** it states the age of that data, for example "Stand vor 12 min".

#### Scenario: Several notices at once
- **WHEN** the browser is offline, the Coach reports an error and an optional provider key is missing
- **THEN** one strip shows the offline notice with a "+N Hinweise" button ("+1 Hinweis" for one further notice), and the button lists the Coach error.

#### Scenario: Low screen
- **WHEN** the viewport is lower than 500 px
- **THEN** the strip is one line, non-critical notices appear only as a count button, and the composer is one row.

Evidence: `public/status-strip.js::statusStripItems`, `public/status-strip.js::renderStatusStrip`, `public/shared.js::renderStatus`, `public/sync-status.js::renderProviderAttention`, `public/settings.js::thresholdStatusItem`; `e2e/status-strip.spec.js::offline, a Coach error and the missing Intervals.icu key show one strip @responsive`, `tests/status-strip.test.cjs::the strip ranks notices by the athlete's order and shows only one as text`, `tests/status-strip.test.cjs::the loading notice stands alone`.

### Requirement: Mehr groups settings under one title with text status and a structured profile
The client SHALL show the settings areas under the fixed title "Mehr" as one swipeable row whose active area is filled, state every provider connection as a text chip (Verbunden, Nicht eingerichtet, Fehler or Nicht geprüft) and let the athlete pick sports by touch. The profile SHALL be four collapsible sections with a one-line summary each and a save bar that stays above the navigation and shows the unsaved state.

#### Scenario: Sports without a hint
- **WHEN** the athlete opens the profile
- **THEN** each sport is a toggle chip of at least 44 px, selecting needs no keyboard modifier and no hint text is shown.

#### Scenario: Status without colour
- **WHEN** the athlete opens Anbindungen
- **THEN** every provider names its status as a text chip, the section header counts them (for example "5 verbunden · 1 Fehler") and the Garmin card names the Personal API key and the SDK login in words.

#### Scenario: Unsaved profile
- **WHEN** a profile field changes
- **THEN** the save bar shows "Ungespeichert" until the profile is saved, then "Gespeichert"; a closed section opens when it holds an invalid value.

Evidence: `public/connection-status.js::connectionsSummaryText`, `public/connection-status.js::garminSourceLines`, `public/views.js::profileSummaries`; `e2e/settings-hub.spec.js::sports are toggle chips of at least 44 px and need no hint @responsive`, `tests/settings-hub.test.cjs::the section header counts chips instead of listing providers`.

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

#### Scenario: Failed reply
- **WHEN** the newest Coach reply of a turn failed and the request was plain text
- **THEN** that reply shows its error with one "Erneut senden" action that sends the same text and request kind as a new turn without disturbing the current draft or attachments; older replies and requests with attachments offer no retry.

Evidence: `public/coach.js::readChatStream`, `public/coach.js::recoverChatRequestFailure`, `public/coach.js::drainChatQueue`, `public/coach.js::cancelChat`, `public/coach.js::appendFailedTurnRetry`; `e2e/contracts.spec.js::every definite HTTP rejection retains the draft and concrete error`, `e2e/contracts.spec.js::a completed answer accepts an immediate follow-up without showing a queue`, `e2e/audit-remediation.spec.js::cancel before stream identity is retained for the matching operation`, `tests/coach-turn-undo.test.cjs::the newest failed reply sends its request again and keeps the draft`, `tests/coach-turn-undo.test.cjs::older, attached or successful replies offer no retry`. Durable Coach effects, receipts, approvals, and undo use the Coach/history specifications.

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

#### Scenario: Turn changes line and empty chat
- **WHEN** a Coach reply carries recorded changes, or the chat has no messages
- **THEN** the reply shows its changes in one line with a visible "Rückgängig" action that asks for confirmation and undoes the whole turn locally (shown as "Zurückgenommen" afterwards, absent when not undoable); an empty chat shows one empty state with a "Profil ausfüllen" action that starts a normal Coach turn.

Evidence: `public/coach.js::chatUserScrolledAway`, `public/coach.js::restoreChatHistoryAnchor`, `public/coach.js::renderMessageNode`, `public/coach.js::undoCoachTurn`, `public/coach.js::appendMessageChanges`, `public/coach.js::profileSetupButton`; `e2e/contracts.spec.js::a prior user message can be copied or edited as a regular draft`, `e2e/coach.spec.js::coach reload opens at the latest message and tab navigation restores the scroll position`, `e2e/coach-history-anchor.spec.js::older chat history keeps the reading position without moving focus @responsive`, `tests/coach-turn-undo.test.cjs::an undoable turn lists its changes with one undo button`, `tests/coach-turn-undo.test.cjs::a confirmed undo marks the answer as undone and reloads the local areas`, `e2e/coach-layout.spec.js::empty coach chat does not promise quick actions and keeps the composer gap @responsive`. Announcement updates are bounded by `public/coach.js::announceChatStatus` and `e2e/coach.spec.js::chat status announcements update once and keep history outside the live region @responsive`.

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

#### Scenario: Garmin Personal API key hint
- **WHEN** a Garmin Personal API key is configured and the key is rejected, expired, within 14 days of its entered expiry date, or has no expiry date, or the Garmin SDK login was skipped
- **THEN** the Garmin card shows one hint naming the state and the renewal in Garmin Connect Web; a rejected or expired key is marked urgent and raises the provider attention banner, and without a configured key no hint appears. The hint never contains the key.

#### Scenario: Wahoo or export consent
- **WHEN** the athlete starts Wahoo connection or enables the automatic metric export to Intervals.icu
- **THEN** the UI follows only an HTTPS authorization URL or explicit consent action and renders the returned connection/export receipt without browser token exposure.

Evidence: `public/provider-connections.js::saveProviderCredentials`, `public/provider-connections.js::renderGarminCard`, `public/provider-connections.js::toggleMetricExport`, `public/wahoo-connection.js::connectWahoo`, `public/sync-actions.js::fullResync`, `public/sync-status.js::garminKeyHint`; `tests/provider-connections.test.cjs::saving sends only non-blank values and leaves no secret in the DOM`, `tests/provider-connections.test.cjs::re-rendering from polling never writes input values`, `tests/wahoo-connection.test.cjs::only https authorize URLs are followed`, `tests/metric-export.test.cjs::declining consent never saves an automatic export setting`, `tests/garmin-key-hint.test.cjs::rejected and expired keys are urgent and name the renewal`, `tests/garmin-key-hint.test.cjs::expiring keys warn with the remaining days`. Provider durable authorization and conflict rules remain in their domain contracts.

### Requirement: Settings preserve explicit choices and unsaved edits
The client SHALL expose server-advertised model, thinking, and speed capabilities; profile and operational settings; and device appearance choices. Save controls SHALL reflect pending/error state and avoid claiming success without an accepted server response.

#### Scenario: Model capability changes
- **WHEN** an explicit model, thinking level, or service tier is selected
- **THEN** the client submits the dedicated setting, reloads the accepted server state, and renders only supported options rather than silently choosing a different provider.

#### Scenario: Profile save overlaps newer typing
- **WHEN** a profile save is in flight and the athlete continues editing
- **THEN** the newer edits remain visible/dirty; invalid JSON or an incomplete save response does not mark the draft saved.

#### Scenario: Device and read settings
- **WHEN** appearance or the calendar display (weeks back and ahead) changes
- **THEN** appearance persists on the device with system/light/dark support, while the calendar display uses its explicit API and reports validation errors.

Evidence: `public/settings.js::saveProfile`, `public/settings.js::saveModel`, `public/settings.js::saveThinkingLevel`, `public/settings.js::saveServiceTier`, `public/settings.js::saveCalendarDisplaySettings`, `public/shared.js::applyAppearance`, `public/appearance.js` (early theme projection), `public/views.js::renderModel`; `e2e/model-settings.spec.js::model and speed selection persist with capability checks @responsive`, `e2e/audit-remediation.spec.js::profile edits made while saving remain dirty and visible`, `e2e/contracts.spec.js::appearance choice updates the theme and survives reload on this device`, `tests/test_settings.py::SettingsServiceTests.test_calendar_defaults_clamping_and_write_keys`.

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

#### Scenario: Agenda, library, and competitions
- **WHEN** the athlete opens plan overview, library, or the competitions tab
- **THEN** the agenda prioritizes dates and sessions with expandable weather/details, the active undated library is grouped by sport, and the competitions tab lists the saved competitions with their source labels; explicit preview/apply/export effects remain governed by the planning domain.

#### Scenario: Compact calendar week
- **WHEN** the athlete opens a calendar week with past, today's and planned sessions
- **THEN** each session is one compact row with sport icon, title, duration and distance; planned sessions look distinct from completed ones; identical extra activities of a day form one row; past days with sessions collapse to one line; "Zusätzlich" appears only in weeks with a plan; the week summary is a fixed planned/completed grid with one duration format and no dash-only rows; calendar notes are neutral text, each conflict is one component with one Coach action, and weeks with workout profiles show a zone legend.

#### Scenario: Provider send state of plan entries
- **WHEN** the athlete views a pending planned unit, a strength unit Garmin cannot receive, or a changed Wahoo library workout
- **THEN** a pending unit offers a "Synchronisieren" action that queues only that unit's push; a blocked strength unit names the reason (no strength structure or an unmapped exercise) with a "Mit Coach strukturieren" action or exercise suggestions; a changed library workout shows "Wahoo: geändert" with an explicit send, and opening a view sends nothing.

#### Scenario: Loading, empty, missing and failed reads
- **WHEN** an analysis or session read is pending, has no data yet, lacks a single value, or fails
- **THEN** a pending read shows a busy status line; an install without data shows one empty card per analysis tab with one action (the connections when no Garmin or Wahoo source is connected, "12 Wochen anzeigen" when a source is connected and the tab shows the 14-day period, otherwise a sync); a missing value reads "nicht erfasst" in a muted style; a failed or 15-second timed-out read shows a "Konnte nicht geladen werden." alert with an "Erneut versuchen" action and neither a permanent loading line nor the empty card.

#### Scenario: Chart units and labels
- **WHEN** an analysis chart plots daily values, weekly sums, or weekly means
- **THEN** its axis names the unit and the aggregation (for example "h · Wochensumme", "Schritte/Tag · Wochenmittel"), whole-number metrics show whole numbers, and value labels stay inside the chart and off marks and other labels.

#### Scenario: Performance and recovery charts
- **WHEN** domain series contain sparse, stale, current, or missing observations
- **THEN** charts/tables retain dates, gaps, provenance and period-specific coverage, distinguish current reference lines from historical observations, and avoid fabricating normal ranges or duplicate prediction charts.

#### Scenario: Recovery comparison wording and band
- **WHEN** the Erholung view shows the HRV or resting-HR comparison for the athlete's earlier values
- **THEN** the labels call it the range of the athlete's earlier values with its quartile limits, provisional state and earlier-night count, use no "normal", "usual", "green", "Basis" or "confirmed" wording and no helper sentence repeating it, the band uses a neutral colour whose series strokes keep at least 3:1 contrast against it in the light and dark themes, and the sleep chart shows no band.

#### Scenario: Seven-day HRV mean
- **WHEN** the Erholung view has at least three nights of HRV in the last seven days
- **THEN** its information text adds the seven-day mean of ln(RMSSD) back-transformed to milliseconds with the night count, its position below, in or above the athlete's range, the variation and a provisional marker; otherwise it states the missing minimum.

#### Scenario: Activity list and detail measurements
- **WHEN** the athlete expands a completed session or activity details
- **THEN** sport-appropriate pace/speed and cadence/step-frequency channels, units, missing points, and available metadata remain readable; failed detail loading retains the session summary and its explicit refresh path.

#### Scenario: Equipment and maintenance
- **WHEN** equipment is displayed or maintenance is requested
- **THEN** local authoritative items and imported/archived sources remain distinguishable, and only eligible active local gear offers the maintenance action under the equipment domain contract.

Evidence: `public/plan-views.js::renderPlanned`, `public/plan-views.js::renderLibrary`, `public/analysis.js::renderAnalysisHistory`, `public/analysis.js::renderTrainingRecords`, `public/analysis.js::recoveryReferenceLabel`, `public/analysis.js::recoveryRollingNote`, `public/components.js::createErrorState`, `public/components.js::createLoadingState`, `public/components.js::markValueMissing`, `public/analysis.js::requestAnalysisReport`, `public/analysis.js::renderRecoveryCharts`, `public/performance-view.js::renderPerformance`, `public/activity-analysis.js::renderPanel`, `public/activity-details.js::render`; `e2e/contracts.spec.js::planned agenda prioritizes dates and sessions with compact weather and expandable details`, `e2e/calendar-week-compact.spec.js::@responsive compact calendar week collapses past days, groups repeats and keeps one conflict style`, `e2e/analysis-info.spec.js::@responsive latest measurement stays visible without inventing measurements in empty weeks`, `e2e/analysis-info.spec.js::@responsive recovery uses independent scales, honest coverage over exactly fourteen days`, `e2e/activity-details.spec.js::@responsive analysis lists sessions whose details failed to load`, `e2e/training-feature-panels.spec.js::@responsive equipment keeps local authority and groups archived sources`, `e2e/data-states.spec.js::@responsive an empty install shows one empty card with one action per analysis tab`, `e2e/data-states.spec.js::@responsive a failed analysis read shows an error with retry instead of a permanent loading line`, `e2e/data-states.spec.js::@responsive a hanging analysis read times out into the retry state`, `e2e/analysis-info.spec.js::@responsive steps and floors show per-day units, whole numbers and the plotted basis`, `tests/analysis-presentation.test.cjs`, `e2e/planned-sync-button.spec.js::@responsive a week with pending units offers one sync button that queues their pushes`, `e2e/strength-garmin-blocked.spec.js::@responsive a strength unit says why it does not reach Garmin and offers the fix`, `e2e/library-wahoo-state.spec.js::@responsive a changed Wahoo library workout offers the explicit send`. Source sections and these browser scenarios were inspected; this requirement does not independently re-specify backend calculations.

### Requirement: Action reviews distinguish known rejection from unknown outcome
The client SHALL offer confirmation only for current confirmable proposals, preserve pending/failed/completed receipt states, and keep an action locked when its execution outcome cannot be confirmed. Reconciliation SHALL determine whether retry is safe rather than automatically repeating an uncertain write.

#### Scenario: Current authorized action
- **WHEN** a pending current proposal exposes a confirmable action
- **THEN** the client presents its concrete review/diff and submits the identified server action, reporting the outcome as a toast and showing the available domain navigation/undo affordances.

#### Scenario: Definite conflict rejection
- **WHEN** execution receives a definite client/conflict rejection
- **THEN** the client reports the rejection and can restore the action's retryable controls according to the returned proposal state.

#### Scenario: Lost response after execution
- **WHEN** a sent execution loses its response or receives an ambiguous server error
- **THEN** the proposal remains locked as unknown until reconciliation confirms consumed or still-confirmable state; a failed reconciliation does not unlock it for duplicate execution.

Evidence: `public/coach.js::coachActionButtons`, `public/coach.js::executeCoachActionProposal`, `public/coach.js::reconcileCoachActionProposal`, `public/components.js::createActionReceipt`; `e2e/contracts.spec.js::only current pending proposals expose an explicit confirmation action`, `tests/frontend-write-safety.test.cjs::a 409 rejection after execute was sent is a known failure and unlocks the proposal`, `tests/frontend-write-safety.test.cjs::a lost execute response keeps the action locked and is not reported as a failed confirmation`, `tests/frontend-write-safety.test.cjs::a failed reconcile keeps the unknown-outcome lock`.

### Requirement: Derived values are marked and controls stay reachable
The client SHALL mark every derived or estimated value with one "Schätzung" chip and name each dashed line. Interactive controls on the analysis and nutrition routes SHALL keep a 44 px hit area and every text/background pair SHALL meet WCAG AA in both themes. Desktop (>= 1100 px) SHALL use a 15-16 px text size, bounded form fields and two charts per row.

#### Scenario: Estimates and predictions
- **WHEN** a derived value (VO2max, race predictions, CP/CS, load, fitness/fatigue/form, heart-rate drift, projected daily expenditure) is shown
- **THEN** it carries the chip, race predictions are whole minutes, and a dashed line is named in the legend or a line key.

#### Scenario: Hit areas and contrast
- **WHEN** the analysis or nutrition routes render in the light theme
- **THEN** info buttons and summaries measure at least 44 px and axe reports no violation; zone percentages use neutral text with the colour on a swatch.

#### Scenario: Nutrition overview
- **WHEN** the diary, the history or the product tab renders
- **THEN** calories form one hero tile above one macro row, runs of days without data collapse to one row, and the product tab has one primary action.

Evidence: `public/components.js::createEstimateChip`, `public/performance-view.js::predictionTime`, `public/analysis.js::appendAnalysisLineKey`, `public/nutrition.js::nutritionChartRows`, `tests/test_css_design_tokens.py::test_training_focus_percentages_use_neutral_text_in_both_themes`, `e2e/estimates-targets.spec.js`.

### Requirement: Selection, sources and axes read consistently
The client SHALL fill the selected tab or range with one accent style everywhere, show the app name, a password toggle and an invalid-field border on the login, and show a meal source only when it differs from the manual local default. Charts SHALL keep a minimum axis span, draw a flat series as a line and space tick labels evenly, naming weeks "Woche ab". Session detail SHALL show one muted source line with the provenance folded away.

#### Scenario: Selection and login
- **WHEN** a segment tab, a range switch or the main navigation shows its active entry, or the login rejects a password
- **THEN** tabs and range switch share one filled accent style, the active navigation entry is filled, and the password field gets a red border with `aria-invalid`.

#### Scenario: Flat series and weekly axes
- **WHEN** a session series is constant or a weekly chart renders
- **THEN** the axis spans at least 5 % of the level and the series is a line; weekly charts name "Woche ab" and label evenly spaced weeks.

#### Scenario: Source lines
- **WHEN** a diary entry is manual and local, or a session carries provider data
- **THEN** the entry shows no source line, and the session shows one muted "Quelle" line with the provenance details folded.

Evidence: `public/analysis.js::appendAnalysisDateTicks`, `public/activity-analysis.js::chartRange`, `public/activity-details.js::providerNotes`, `public/nutrition.js::nutritionCard`, `public/auth.js::setLoginError`, `e2e/ux-polish.spec.js`.
