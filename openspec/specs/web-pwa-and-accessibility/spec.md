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

Evidence: `public/service-worker.js` (install/activate/fetch listeners, `CACHE`, `ASSETS`, `VERSIONED_ASSETS`), `public/manifest.webmanifest`, `public/notifications.js::registerServiceWorker`, `public/notifications.js::reloadForUpdateWhenSafe`; `e2e/contracts.spec.js::fresh service worker keeps the current shell available offline`, `tests/test_server_frontend.py::ServerFrontendTests.test_pwa_asset_versions_match_service_worker_precache`, `e2e/update-reload.spec.js::a service worker update keeps a typed draft and reloads once it is cleared`, `tests/test_server_frontend.py::ServerFrontendTests.test_service_worker_caches_only_versioned_static_assets_and_not_api`, `tests/test_server_frontend.py::ServerFrontendTests.test_nutrition_asset_is_served_as_immutable_javascript`, `e2e/offline-errors.spec.js::the offline banner states that changes are not saved and promises no later delivery @responsive`. The manifest name and short name have no covering test.

### Requirement: Locked and failing sessions show concrete safe states
The client SHALL keep the application behind the required login dialog until successful authentication, distinguish login failure reasons, clear device state when authentication ends, and show bounded connectivity and maintenance states.

#### Scenario: Dismiss locked login
- **WHEN** Escape or dialog closure is attempted while login is required
- **THEN** the login remains required and focus returns to the password field rather than leaving an inaccessible blank app.

#### Scenario: Rejected or rate-limited login
- **WHEN** a wrong password, rate limit, transient server failure, persistent configuration error, timeout, or missing connection occurs
- **THEN** the UI displays the corresponding message, using the returned retry delay where supplied, and restores the login control for retry.

#### Scenario: Start session check
- **WHEN** the client starts
- **THEN** it reads `/api/auth/status` with a 10-second deadline; an authenticated answer loads the state, an unauthenticated one clears the device data and shows the login, and no answer keeps shown device data and retries after 15 seconds or when the browser reports `online`, or shows the login with "Server nicht erreichbar." when none is shown

#### Scenario: Login message texts
- **WHEN** a login fails with HTTP 429
- **THEN** it reads "Zu viele Anmeldeversuche. Bitte in etwa N Minuten erneut versuchen." (N seconds below one minute, no time without a hint); a 5xx with a retry hint, a 502, a 504 or a non-JSON answer reads "Der Server startet gerade oder ist ausgelastet. Bitte in wenigen Sekunden erneut versuchen.", and every other failure shows the server or transport message

#### Scenario: Loading texts and logout
- **WHEN** the shell is not yet shown, or the athlete chooses "Abmelden"
- **THEN** it reads "Trainingsbereich wird geladen…" or, after an asset update, "Update wird verarbeitet…"; unsaved changes are confirmed first, then "Abmelden?" is confirmed, and a failure other than 401 shows "Abmelden fehlgeschlagen. Bitte erneut versuchen." and keeps the app open

#### Scenario: Logout or maintenance
- **WHEN** confirmed logout succeeds, a current-session 401 arrives, or restore maintenance is active
- **THEN** the client clears/locks according to the session contract or shows the maintenance pause; a failed logout leaves the session available for retry.

Evidence: `public/auth.js::installLoginDialogGuards`, `public/auth.js::loginErrorMessage`, `public/auth.js::logout`, `public/auth.js::showLogin`, `public/sync-status.js::renderMaintenanceStatus`; `e2e/login-dialog.spec.js::Escape keeps the login dialog open and logout shows it again @responsive`, `public/auth.js::bootstrapAuth`, `public/auth.js::retryBootstrapAuth`, `public/auth.js::showAppShellLoading`, `tests/frontend-failure-paths.test.cjs::a failed logout request keeps the app open, reports the error and allows a retry`, `e2e/update-start.spec.js::a start after an update without a reachable server shows the stored data @responsive`, `tests/login-errors.test.cjs::a rate-limited login names the wait from Retry-After`, `tests/login-errors.test.cjs::a lasting server error keeps its own message instead of asking to retry`.

### Requirement: One status strip ranks the notices above every screen
The client SHALL show at most one status strip above every screen: the most severe notice as text, the others behind a count button. Severity SHALL rank the start loading notice, which shows alone, then maintenance, offline, OpenAI key, Coach error, data load failure, provider attention, Garmin hint, thresholds, and last the dismissible Intervals.icu key hint, which appears only when nothing else does.

#### Scenario: Age of device data
- **WHEN** the offline or load-failure notice shows data from the device
- **THEN** it states the age of that data: "Stand gerade eben" below one minute, "Stand vor N min" below one hour, "Stand vor N h" below 48 hours, else "Stand vor N Tagen"; the label is refreshed every 60 seconds.

#### Scenario: Announcement and dismissal
- **WHEN** the strip changes or the athlete dismisses the Intervals.icu key hint
- **THEN** only a critical notice is announced as `alert`, others as `status`, and an unchanged strip is not rendered again; the dismissed hint stays hidden for the browser session and focus moves to the main region.

#### Scenario: Several notices at once
- **WHEN** the browser is offline, the Coach reports an error and an optional provider key is missing
- **THEN** one strip shows the offline notice with a "+N Hinweise" button ("+1 Hinweis" for one further notice), and the button lists the Coach error.

#### Scenario: Low screen
- **WHEN** the viewport is lower than 500 px
- **THEN** the strip is one line, non-critical notices appear only as a count button, and the composer is one row.

Evidence: `public/status-strip.js::statusStripItems`, `public/status-strip.js::renderStatusStrip`, `public/shared.js::renderStatus`, `public/sync-status.js::renderProviderAttention`, `public/settings.js::thresholdStatusItem`; `e2e/status-strip.spec.js::offline, a Coach error and the missing Intervals.icu key show one strip @responsive`, `tests/status-strip.test.cjs::the strip ranks notices by the athlete's order and shows only one as text`, `tests/status-strip.test.cjs::the loading notice stands alone`.

### Requirement: Mehr groups settings under one title with text status and a structured profile
The client SHALL show the settings areas under the fixed title "Mehr" as one swipeable row whose active area is filled, show every provider connection as one collapsible card that states its status as a text chip (Verbunden, Nicht eingerichtet, Fehler or Nicht geprüft) and let the athlete pick sports by touch. The profile SHALL be four collapsible sections with a one-line summary each and a save bar that stays above the navigation and shows the unsaved state.

#### Scenario: Sports without a hint
- **WHEN** the athlete opens the profile
- **THEN** each sport is a toggle chip of at least 44 px, selecting needs no keyboard modifier and no hint text is shown.

#### Scenario: Status without colour
- **WHEN** the athlete opens Anbindungen
- **THEN** the seven cards (Garmin, Wahoo, Intervals.icu, OpenAI, Yazio, Gemeinsamer Kalender, Open-Meteo) are collapsed and each shows only its name and a text chip with a coloured dot, and the Garmin card names the Personal API key and the SDK login in words.

#### Scenario: One card per connection
- **WHEN** the athlete opens a card or follows a setup link for one provider
- **THEN** that card opens with its status, freshness and retry history, credentials, settings and actions and no other provider's fields; several cards can be open at once, and the Open-Meteo card keeps the CC BY 4.0 attribution.

#### Scenario: A check fills a not yet checked chip
- **WHEN** a configured Intervals.icu or Claude card shows "Nicht geprüft" and the athlete runs "Verbindung prüfen"
- **THEN** its chip shows "Verbunden" after a successful check and "Fehler" after a failed one, also after a reload while the server keeps the result.

#### Scenario: Unsaved profile
- **WHEN** a profile field changes
- **THEN** the save bar shows "Ungespeichert" until the profile is saved, then "Gespeichert"; a closed section opens when it holds an invalid value.

Evidence: `public/connection-status.js::openConnectionCard`, `public/connection-status.js::garminSourceLines`, `public/sync-status.js::renderProviderFreshness`, `public/views.js::profileSummaries`; `e2e/settings-hub.spec.js::sports are toggle chips of at least 44 px and need no hint @responsive`, `e2e/settings-hub.spec.js::@responsive the seven connections start collapsed and name their status in words`, `e2e/settings-hub.spec.js::@responsive an open card holds only its own provider's status, access, settings and actions`, `e2e/provider-actions.spec.js::@responsive the setup line is shown on every tab and Jetzt einrichten opens the Intervals.icu card`, `tests/provider-checks.test.cjs::Intervals.icu and Claude chips follow the last explicit check, also after a reload`.

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

Evidence:
- `e2e/coach-history-anchor.spec.js::older chat history keeps the reading position without moving focus @responsive`
- `e2e/coach-layout.spec.js::empty coach chat does not promise quick actions and keeps the composer gap @responsive`
- `e2e/coach.spec.js::coach reload opens at the latest message and tab navigation restores the scroll position`
- `e2e/contracts.spec.js::a prior user message can be copied or edited as a regular draft`
- `public/coach.js::appendMessageChanges`
- `public/coach.js::chatUserScrolledAway`
- `public/coach.js::profileSetupButton`
- `public/coach.js::renderMessageNode`
- `public/coach.js::restoreChatHistoryAnchor`
- `public/coach.js::undoCoachTurn`
- `tests/coach-turn-undo.test.cjs::a confirmed undo marks the answer as undone and reloads the local areas`
- `tests/coach-turn-undo.test.cjs::an undoable turn lists its changes with one undo button`

Announcement updates are bounded by `public/coach.js::announceChatStatus` and `e2e/coach.spec.js::chat status announcements update once and keep history outside the live region @responsive`.

### Requirement: Attachments stay bound to their own editable turn
The client SHALL accept bounded GPX, FIT, JPEG, PNG, and WebP attachments, expose their names/types and removal controls, and preserve each submitted or queued message's own attachment set. Attachment processing SHALL not silently replace another draft or session.

#### Scenario: Attach without text
- **WHEN** a valid attachment is added to an otherwise empty draft
- **THEN** sending becomes available, removal can return it to an empty disabled draft, and the server still validates the attachment.

#### Scenario: Queue two attachment messages
- **WHEN** separate messages with separate files are queued during a turn
- **THEN** each outgoing message retains its own files rather than inheriting the current composer's file list.

#### Scenario: Picker bounds and image reduction
- **WHEN** a selection holds a file other than `.gpx`, `.fit`, `.png`, `.jpg`, `.jpeg` or `.webp`, an empty file, a GPX or FIT file above 5 000 000 bytes or an image above 15 000 000 bytes
- **THEN** the whole selection is refused with "Bis zu 4 Dateien auswählen. GPX/FIT dürfen höchstens 5 MB, Bilder höchstens 15 MB groß sein."; an accepted image is reduced like a nutrition photo (1600 px, 1 200 000 bytes) and renamed to `.jpg` when its type changed, and a failed reduction keeps the original only up to 5 000 000 bytes

#### Scenario: Invalid selection or rejected upload
- **WHEN** selection exceeds four files or file bounds, or server validation rejects the upload
- **THEN** invalid additions do not partially mutate the draft, and the rejected message/files remain recoverable for correction.

Evidence: `public/coach.js::validateChatAttachmentFiles`, `public/coach.js::prepareChatAttachment`, `public/coach.js::renderChatAttachments`, `backend/coach/attachments.py::validate_attachments`; `e2e/attachments.spec.js::attachments can be removed, rejected and sent with an empty text draft`, `e2e/attachments.spec.js::attachments stay with their own queued message`, `e2e/nutrition.spec.js::a small undecodable image falls back to attachment and allows a valid image afterwards`, `tests/test_coach_attachments.py::AttachmentTests.test_invalid_upload_does_not_create_a_command`. Packaging-image preparation uses `nutrition-photo-analysis`; general Coach attachment storage/retention is governed by the Coach domain, and is not promised transient like label extraction.

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

Evidence: `public/diagnostics.js::loadLogs`, `public/diagnostics.js::deleteDiagnostics`, `public/settings.js::restoreDatabaseBackup`, `public/settings.js::deletePrivacyData`, `public/settings.js::downloadPrivacyExport`, `public/shared.js::toast`; `e2e/privacy-delete.spec.js::the deletion stays locked while the backup before deletion is running`, `e2e/state-events.spec.js::short-lived status connections back off while logs and diagnostics stay usable`, `e2e/privacy-delete.spec.js::local data deletion requires the exact confirmation text`, `e2e/toast.spec.js::@responsive error toasts are readable, dismissible and stay above the coach composer`, `e2e/offline-errors.spec.js::a failed request without a server response shows an honest German message @responsive`. Backend diagnostic sanitization and restore validation belong to their own domains.

### Requirement: Domain views preserve supplied facts and source distinctions
The client SHALL present domain-provided planning, performance, activity, and equipment facts with their dates, units, source distinctions, and missing-data states. Rendering or opening a domain view SHALL not itself substitute for an authorized durable domain action.

#### Scenario: Agenda, library, and competitions
- **WHEN** the athlete opens plan overview, library, or the competitions tab
- **THEN** the agenda prioritizes dates and sessions with expandable weather/details, the active undated library is grouped by sport, and the competitions tab lists the saved competitions with their source labels; explicit preview/apply/export effects remain governed by the planning domain.

#### Scenario: Compact calendar week
- **WHEN** the athlete opens the calendar with past, today's and planned sessions
- **THEN** it shows the current week as a timeline (weekday and date column, today filled) with previous/next week buttons and the ISO week, limited to the configured weeks ahead (the configured weeks back load at once; paging back has no limit and older weeks load their completed sessions on demand); each session is one compact row with sport icon, title, duration and distance and, for a planned unit only, a zone bar for its workout profile (16 px high on narrow screens), and opened, its session-type and intensity labels sit above their selects so no word breaks at phone width; a completed or missed unit is one slim row whose line holds the time and the status ("✓ Absolviert" with the share of the plan, "✓ Zusätzlich", "✕ Nicht absolviert") without zone or compliance bar, its activity name shown without the place prefix of the profile's weather location; opened, it shows its chart, each value once with German labels and per sport (runs and rides have their own lists, a value without data is left out), the plan line, the "Details" toggle, "Mit dem Coach analysieren" and "Feedback" (see "Calendar cards carry the single-session analysis"); planned sessions are dashed, completed ones solid and missed ones outlined in red; identical extra activities of a day form one row; on screens at least 1100 px wide the opened session shows as a detail pane beside the week, level with its card (title, day, status, larger profile with its axis, and the session details), and one session of the week is opened by default; a "Woche | Monat" switch (never stored, entering the calendar shows the week again) shows the month of the selected day as whole weeks Monday to Sunday with neighbouring days muted, one mark per session (a dot coloured by sport, outlined when planned, red when missed; a duration chip and the ISO week with its planned time on wide screens), today filled, the selected day ringed and the current week tinted, and selecting a day shows its week below; "Zusätzlich" appears only in weeks with a plan; the week summary is a fixed planned/completed grid with one duration format and no dash-only rows; calendar notes are neutral text, each conflict is one component with one Coach action, and weeks with workout profiles show a zone legend.

#### Scenario: Move a planned unit
- **WHEN** the athlete opens a planned unit that is not a completed session and taps "Verschieben"
- **THEN** a strip of the next seven days from today (the unit's own day disabled) and "…" for the system date picker appear, both ending with the last day the calendar shows; one tap moves the local unit, the opened card follows it to its new week with "Verschoben auf <Tag, Datum>" and "Rückgängig", and undo puts it back with "Zurückgenommen."; a unit already sent shows its pending sync and nothing is written remotely.
#### Scenario: Planned steps as a list
- **WHEN** the athlete opens a planned unit whose workout has structured steps
- **THEN** the pane lists one row per step with its zone colour mark, duration or distance, zone, and the target range right-aligned ("110–128 bpm", "≤ 109 bpm", pace in min/km) from the zones in effect on the unit's day; a step without a range shows none; the description keeps only its free text, and the stored workout text and its export stay unchanged.

#### Scenario: Discuss a planned unit with the Coach
- **WHEN** the athlete taps "Mit dem Coach besprechen" on an opened planned unit
- **THEN** the Coach opens with the unit named by date, sport, start time, duration and local id in the message field (after an unsent draft, which stays), focused for the athlete's question; nothing is sent and the stored name is not part of the message.

#### Scenario: Provider send state of plan entries
- **WHEN** the athlete views a pending planned unit, a strength unit Garmin cannot receive, or a changed Wahoo library workout
- **THEN** a week with pending units or leftovers at a provider offers one "Woche synchronisieren" button in its heading (unit cards carry none; `garmin-strength-workout-push` and `training-library` define what it sends and removes); a blocked strength unit names the reason (no strength structure or an unmapped exercise) with a "Mit Coach strukturieren" action or exercise suggestions; a changed library workout shows "Wahoo: geändert" with an explicit send, and opening a view sends nothing.

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
- **WHEN** the athlete opens a completed session's "Details" in its calendar card or its "Feedback" dialog
- **THEN** sport-appropriate pace/speed and cadence/step-frequency channels, units, missing points, and available metadata remain readable; failed detail loading retains the session summary and its explicit refresh path.

#### Scenario: Equipment and maintenance
- **WHEN** equipment is displayed or maintenance is requested
- **THEN** each item is one collapsible card that starts collapsed on every visit and shows its name (with a Garmin source tag for Garmin-only items), one status chip, one short line (parent bike for components, distance, lifetime percent) and a slim lifetime bar; a screen reader hears the name (and the Garmin source tag), the state and the lifetime percent once, with its meaning and an exceeded target the chip does not name, because the bar is decorative and hidden from the accessibility tree; an open card shows usage, maintenance with its history, Garmin state and status conflict, and the maintenance action with its receipt and undo, which only eligible active local gear offers under the equipment domain contract; archived items appear only in a collapsed "Ausgemustert (n)" group.

Evidence:
- `e2e/activity-details.spec.js::@responsive analysis lists sessions whose details failed to load`
- `e2e/activity-details.spec.js::@responsive calendar details chart running dynamics per second and retry a failed read`
- `e2e/activity-details.spec.js::@responsive calendar details expand Garmin-style charts`
- `e2e/activity-details.spec.js::@responsive calendar details show running step frequency and cycling cadence`
- `e2e/analysis-info.spec.js::@responsive latest measurement stays visible without inventing measurements in empty weeks`
- `e2e/analysis-info.spec.js::@responsive recovery uses independent scales, honest coverage over exactly fourteen days`
- `e2e/analysis-info.spec.js::@responsive steps and floors show per-day units, whole numbers and the plotted basis`
- `e2e/calendar-detail-pane.spec.js::@responsive a planned unit lists its steps with zone and target range instead of the workout notation`
- `e2e/calendar-detail-pane.spec.js::@responsive Mit dem Coach besprechen puts the planned unit into the Coach field without sending`
- `e2e/calendar-detail-pane.spec.js::@responsive Verschieben moves a planned unit to a tapped day and Rückgängig puts it back`
- `e2e/calendar-week-compact.spec.js::@responsive compact calendar week shows one week, groups repeats and keeps one conflict style`
- `e2e/calendar-week-compact.spec.js::@responsive the Monat switch shows the month grid and the calendar returns to the week`
- `e2e/contracts.spec.js::planned agenda prioritizes dates and sessions with compact weather and expandable details`
- `e2e/data-states.spec.js::@responsive a failed analysis read shows an error with retry instead of a permanent loading line`
- `e2e/data-states.spec.js::@responsive a failed equipment read offers a retry`
- `e2e/data-states.spec.js::@responsive a hanging analysis read times out into the retry state`
- `e2e/data-states.spec.js::@responsive an empty install shows one empty card with one action per analysis tab`
- `e2e/library-wahoo-state.spec.js::@responsive a changed Wahoo library workout offers the explicit send`
- `e2e/planned-sync-button.spec.js::@responsive a week with pending units offers one sync button that queues their pushes`
- `e2e/session-focus.spec.js::@responsive a planned strength unit keeps its field labels whole at phone width`
- `e2e/settings-hub.spec.js::@responsive collapsible sections share one chevron and the page passes the contrast check` (axe on the equipment page)
- `e2e/strength-garmin-blocked.spec.js::@responsive a strength unit says why it does not reach Garmin and offers the fix`
- `e2e/training-feature-panels.spec.js::@responsive equipment keeps local authority and groups archived sources`
- `public/activity-analysis.js::renderPanel`
- `public/activity-details.js::render`
- `public/analysis.js::equipmentCard`
- `public/analysis.js::equipmentState`
- `public/analysis.js::recoveryReferenceLabel`
- `public/analysis.js::recoveryRollingNote`
- `public/analysis.js::renderAnalysisHistory`
- `public/analysis.js::renderRecoveryCharts`
- `public/analysis.js::renderTrainingRecords`
- `public/analysis.js::requestAnalysisReport`
- `public/coach.js::askCoach`
- `public/components.js::createErrorState`
- `public/components.js::createLoadingState`
- `public/components.js::markValueMissing`
- `public/performance-view.js::renderPerformance`
- `public/plan-views.js::plannedDiscussButton`
- `public/plan-views.js::plannedStepList`
- `public/plan-views.js::plannedUnitActions`
- `public/plan-views.js::renderLibrary`
- `public/plan-views.js::renderPlanned`
- `tests/analysis-presentation.test.cjs`
- `tests/plan-views-hr-cap.test.cjs::a step range reads as a span, an open lowest or top zone, or a pace in min/km`
- `tests/plan-views-sport-label.test.cjs`

Source sections and these browser scenarios were inspected; this requirement does not independently re-specify backend calculations.

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

Evidence: `public/coach.js::coachActionButtons`, `public/coach.js::executeCoachActionProposal`, `public/coach.js::reconcileCoachActionProposal`, `public/coach.js::toastCoachReceipts`; `e2e/coach-tool-receipts.spec.js::profile writes have a useful receipt and unresolved errors stay visible safely`, `e2e/contracts.spec.js::only current pending proposals expose an explicit confirmation action`, `tests/frontend-write-safety.test.cjs::a 409 rejection after execute was sent is a known failure and unlocks the proposal`, `tests/frontend-write-safety.test.cjs::a lost execute response keeps the action locked and is not reported as a failed confirmation`, `tests/frontend-write-safety.test.cjs::a failed reconcile keeps the unknown-outcome lock`.

### Requirement: Derived values are marked and controls stay reachable
The client SHALL mark every derived or estimated value with one "Schätzung" chip and name each dashed line. Interactive controls on the analysis and nutrition routes SHALL keep a 44 px hit area and every text/background pair SHALL meet WCAG AA in both themes. Desktop (>= 1100 px) SHALL use a 15-16 px text size, bounded form fields and two charts per row.

#### Scenario: Estimates and predictions
- **WHEN** a derived value (VO2max, race predictions, CP/CS, load, fitness/fatigue/form, heart-rate drift, projected daily expenditure) is shown
- **THEN** it carries the chip, 5 and 10 km predictions show minutes and seconds while half marathon and marathon show hours and minutes, VO2max keeps the precise provider value's one decimal, and a dashed line is named in the legend or a line key.

#### Scenario: Hit areas and contrast
- **WHEN** the analysis or nutrition routes render in the light theme
- **THEN** info buttons and summaries measure at least 44 px and axe reports no violation; zone percentages use neutral text with the colour on a swatch.

#### Scenario: Nutrition overview
- **WHEN** the diary, the history or the product tab renders
- **THEN** calories form one hero tile above one macro row, runs of days without data collapse to one row, and the product tab has one primary action.

Evidence: `public/components.js::createEstimateChip`, `public/performance-view.js::predictionTime`, `public/analysis.js::appendAnalysisLineKey`, `public/nutrition.js::nutritionChartRows`, `tests/test_css_design_tokens.py::test_training_focus_percentages_use_neutral_text_in_both_themes`, `tests/analysis-presentation.test.cjs::race prediction rows exclude body weight and empty states give a reason`, `backend/sync/garmin_payload_metrics.py:_garmin_collect_vo2_values`, `tests/test_performance_garmin_metrics.py:test_precise_vo2max_wins_over_its_rounded_twin`, `e2e/estimates-targets.spec.js`.

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

### Requirement: Calendar cards carry the single-session analysis
The calendar card of a completed session SHALL carry its single-session analysis behind a "Details" toggle, with "Mit dem Coach analysieren" and "Feedback" beside it. The Analyse tab SHALL have no separate list of sessions, the calendar SHALL page back without limit so every stored session stays reachable, and the Coach SHALL NOT receive per-second running dynamics.

#### Scenario: Details in the card
- **WHEN** the athlete opens "Details" of a completed session
- **THEN** its charts, zones, laps, values, form drift and provider notes appear in the card; a failed or timed-out read shows the retry card; an opened Details stays open and reloads when the calendar is rebuilt by a sync or reload.

#### Scenario: Time in zones
- **WHEN** the athlete opens a completed session's card
- **THEN** below its values one slim bar shows the session's time per zone (power zones for a ride that has them, else heart-rate zones) with the minutes per zone below and the zone kind and source ("HF-Zonen · Garmin Connect"), read from the same session read as "Details" (one request per session and calendar data while both are open; a failed read is read again); a session without zones or with a failed read shows no bar.

#### Scenario: Session chart scale
- **WHEN** a session channel is charted
- **THEN** its scale runs from the 1st to the 99th percentile (elevation: minimum to maximum) plus 8 % padding and never below zero for a non-negative channel; speed of a run, walk, hike or swim is drawn as pace in min/km or min/100 m with faster on top, and speeds below 0.3 m/s are gaps

#### Scenario: Running dynamics per second
- **WHEN** a run has stored running dynamics streams
- **THEN** each available one is charted per second with the same name as its average in the value list and named in the data coverage, and the Coach's activity details carry only the averages.

#### Scenario: Feedback and Coach actions
- **WHEN** the athlete taps "Feedback" or "Mit dem Coach analysieren" on an opened completed session
- **THEN** "Feedback" opens the dialog with the session type, session RPE, deviation reason, notes and the confirm, split and delete actions, and the Coach button starts one turn that names the session by date, sport, time, duration and id, never by its stored name.

#### Scenario: No sessions segment in Analyse
- **WHEN** the athlete opens the Analyse tab or an old `#analysis/sessions` link
- **THEN** Analyse shows Laufen, Radfahren, Belastung and Erholung only, and the old link opens the calendar overview instead.

#### Scenario: Paging back without limit
- **WHEN** the athlete pages back to a week before the configured weeks back and before the loaded sessions
- **THEN** the calendar loads the older completed sessions page by page from the session list, newest first, adds only sessions older than the loaded ones, and shows them with Details and Feedback like any other session.

Evidence:
- `backend/activities/detail_contract.py:activity_detail_contract`
- `backend/coach/activity_read_tools.py:CoachActivityReadToolService`
- `e2e/activity-details.spec.js::@responsive calendar details chart running dynamics per second and retry a failed read`
- `e2e/activity-details.spec.js::@responsive calendar details expand Garmin-style charts`
- `e2e/activity-details.spec.js::@responsive the calendar details open a Garmin-only indoor session; old Einheiten links land on the calendar`
- `e2e/activity-details.spec.js::@responsive the calendar pages back past the loaded weeks and loads older sessions`
- `e2e/calendar-detail-pane.spec.js::@responsive an opened completed session shows its time in zones as one bar with the source`
- `e2e/ux-polish.spec.js::a session's calendar details keep a flat series as a line on a real axis @responsive`
- `public/activity-analysis.js::loadPanel`
- `public/navigation.js::routeFromHash`
- `public/plan-views.js::appendPlannedZoneTime`
- `public/plan-views.js::loadOlderSessions`
- `public/plan-views.js::plannedActivityActions`
- `tests/test_activity_detail_contract.py:StreamTests.test_streams_are_downsampled_with_aligned_equal_length_channels`
- `tests/test_coach_activity_read_tools.py:test_activity_detail_exposes_the_session_bundle_for_corrections`

### Requirement: Analyse is split by sport
The Analyse tab SHALL show the segments Laufen, Radfahren, Belastung and Erholung in this order, without a Leistung segment. Laufen and Radfahren SHALL each show only their sport's current values, best efforts, development charts and estimates; Belastung and Erholung SHALL stay sport-independent. Every value and chart of the former Leistung segment SHALL appear in exactly one segment, and an old Leistung link SHALL open Laufen.

#### Scenario: Laufen
- **WHEN** the athlete opens Analyse › Laufen
- **THEN** it shows the running current values (threshold pace, threshold power, threshold heart rate, LT1 pace and heart rate as on the zones page, VO2max), the development charts (threshold pace, VO2max, running tolerance), the best efforts of the last 90 days (best pace over 1, 3, 5, 7, 12 and 20 minutes and best time over 1 km and 5 km, each with its date and source, missing ones marked as missing) with the experimental critical-speed line, and the race predictions; no cycling value appears.

#### Scenario: Radfahren
- **WHEN** the athlete opens Analyse › Radfahren
- **THEN** it shows the cycling current values (FTP, power per weight, threshold heart rate, LT1 power and heart rate as on the zones page, VO2max), the power profile with its coverage note and the experimental critical-power line, and the development charts (FTP, VO2max); no running value appears.

#### Scenario: Cross-sport values
- **WHEN** the athlete opens Analyse › Belastung or Erholung
- **THEN** the endurance score is charted in Belastung, readiness stays in Erholung, and the weekly training status is not charted because it repeats the acute load in Belastung.

#### Scenario: Empty sport and old links
- **WHEN** one sport has no current values, charts, best efforts or estimates, or the athlete opens `#analysis/performance`
- **THEN** that sport's segment shows its one empty card while the other sport keeps its content, and the old link opens Laufen.

#### Scenario: Empty card
- **WHEN** every container of the active segment is empty
- **THEN** one empty card shows the title "Noch keine Laufdaten", "Noch keine Raddaten", "Noch keine Belastungsdaten" or "Noch keine Erholungsdaten"; with a connected source and the 14-day period of Belastung or Erholung the cause is "Keine Daten in den letzten 14 Tagen." with the action "12 Wochen anzeigen", with a connected source otherwise "Noch keine Daten abgeglichen." with "Jetzt abgleichen", and without a source "Garmin oder Wahoo ist nicht verbunden." with "Anbindung einrichten".

#### Scenario: Slow or failed read
- **WHEN** an Analyse report or detail read takes longer than 15 seconds or fails
- **THEN** the view shows an error with "Erneut versuchen" instead of a loading state.

#### Scenario: Power table and estimate line
- **WHEN** the power profile and the critical-power estimate are shown
- **THEN** the table lists 5 s, 1 min, 5 min, 20 min and 1 h from the 90-day window, and the line "Experimentell · CP (28 Tage): …" (CS for running) names per fit CP and W′ (kJ) or CS and D′ with "(unsicher)", the count of race efforts, or "—" for a fit that is not `ok`.

Evidence: `public/analysis.js::renderAnalysisSegments`, `public/analysis.js::renderRunningBestEfforts`, `public/analysis.js::criticalPowerLine`, `public/analysis.js::renderAnalysisHistory`, `public/performance-view.js::renderCurrentPerformance`, `public/navigation.js::routeFromHash`; `tests/analysis-presentation.test.cjs::an analysis segment is empty only when every content container reports no data`, `tests/analysis-presentation.test.cjs::current performance shows the status lines below its heading`, `e2e/performance-values.spec.js::@responsive Laufen and Radfahren each show only their sport`.

### Requirement: Calendar display range setting
The system SHALL store how many weeks the training calendar shows back and ahead as `past_weeks` and `future_weeks`, each a whole number from 0 to 52 with defaults 1 and 4, stored under `calendar_display_past_weeks` and `calendar_display_future_weeks`. `PUT /api/settings/calendar-display` SHALL change only the values it names and return `status: "ok"` with both (contract in `docs/api-routes.md`).

#### Scenario: Partial update
- **WHEN** only `future_weeks` is sent
- **THEN** only that value changes.

#### Scenario: Invalid input
- **WHEN** the body is not an object, names neither value, or a value cannot be converted to an integer or lies outside 0 to 52 (a convertible value such as `3.7` or `true` is stored as its integer)
- **THEN** the request fails with 400 and nothing changes, also when one of two sent values is valid.

#### Scenario: Stored value out of range
- **WHEN** a stored value is not a number or lies outside the range
- **THEN** the default is used for the first, and the value is clamped to 0 to 52 for the second.

Evidence: `backend/settings.py::SettingsService._calendar_display_settings`, `backend/settings.py::SettingsService.save_calendar_display_settings`, `backend/http_api/settings_put.py`, `public/settings.js`; `tests/test_server_weather_calendar.py::test_calendar_display_settings_are_persisted_and_validated`, `tests/test_http_settings_put_routes.py::test_calendar_display_route_passes_whole_payload`, `tests/test_settings.py::test_calendar_defaults_clamping_and_write_keys`, `tests/test_settings.py::test_calendar_invalid_values_have_exact_errors_and_no_partial_write`.

### Requirement: Stamping inputs and refusal

The asset version SHALL be the first 10 hex characters of the SHA-256 of the file content. The service-worker cache name SHALL be computed from the worker source and from every precached path with its content hash, so a file outside the precache list does not change it. Stamping SHALL fail when the worker lacks its `ASSETS` list or the `__ASSET_HASH__` token, or lists a path that is not a static target.

#### Scenario: Unlisted file changes
- **WHEN** a static file that is not precached changes
- **THEN** the cache name stays the same

#### Scenario: Worker lists an unknown file
- **WHEN** `ASSETS` names a path without a static target
- **THEN** stamping raises an error instead of serving a partly stamped shell or worker

Evidence: `backend/http_api/static_assets.py::StaticAssetService._build_stamped`. Tests: `tests/test_server_frontend.py::test_cache_name_follows_cached_assets_and_ignores_the_rest`; `tests/test_server_frontend.py::test_stamping_refuses_a_worker_without_its_cache_token_or_asset_files`; `tests/test_server_frontend.py::test_source_files_carry_no_version_numbers`.

### Requirement: Route table and defaults

The client SHALL recognise exactly the hashes of the router table in `docs/view-catalogue.md` (case-insensitive) and resolve a former route to the one that replaced it. The main links SHALL lead to `#plan/overview`, `#analysis/running`, `#nutrition/diary` and `#more`; `#plan` without a segment opens Übersicht and `#more` opens Anbindungen.

#### Scenario: Unknown hash
- **WHEN** the hash is not in the table
- **THEN** the Coach view opens and the address is replaced by `#coach` without a new history entry

#### Scenario: Modified click
- **WHEN** a navigation or segment link is clicked with Ctrl, Cmd, Shift, Alt or a non-primary button
- **THEN** the browser handles the link itself

#### Scenario: Leaving the page with unsaved input
- **WHEN** the page is unloaded while a profile edit, a chat draft, a queued message or a rejected message exists
- **THEN** the browser's leave confirmation is requested

Evidence: `public/navigation.js::AppRouter.routeFromHash`; `public/navigation.js::AppRouter.syncFromHash`; `public/navigation.js::AppNavigation`; `public/app.js` (link click and `beforeunload` listeners); `public/shared.js::hasUnsavedChanges`. Tests: `e2e/navigation.spec.js::@responsive each hash navigation renders its target once`; `tests/navigation-state.test.cjs::a hash names a known route in any case, and a removed route falls back to the Coach`; `tests/navigation-state.test.cjs::the route parts fall back to the first plan segment and the connections section`.

### Requirement: Layout breakpoints and input adaptations

The shell SHALL use the bottom navigation below 768 px width, a 72 px rail with icons from 768 px and a 216 px labelled rail from 1100 px. On coarse pointers form controls SHALL be at least 16 px. Under reduced motion animations and transitions SHALL be cut to 0.01 ms, except the Coach working indicator, which keeps a slow fade.

#### Scenario: On-screen keyboard
- **WHEN** the chat input is focused on a touch-first device and the visible viewport is at least 100 px lower than its baseline for the current orientation
- **THEN** the bottom navigation is hidden and the composer is scrolled into the visible viewport

Evidence: `public/styles.css` (width media queries, `hover: none` and `pointer: coarse` rules, `prefers-reduced-motion` rule); `public/shared.js::updateMobileViewportLayout`. Tests: `e2e/css-cascade.spec.js::visibility, chart variants and reduced motion override component styles`; `e2e/light-theme-controls.spec.js::@responsive inputs are at least 16px under coarse pointer and dialog actions share a font size`.

### Requirement: Service-worker fetch rules

The worker SHALL answer a navigation from the network and keep the one shell copy under the key `/`. It SHALL answer with the cached shell when the network takes longer than 2500 ms, fails or returns status 500 or more. Versioned assets SHALL be cache-first; other GET requests SHALL be network-first and stored only when their path is precached. The manifest SHALL declare `id`, `start_url` and `scope` `/`, display `standalone`, language `de` and the four precached icons, one maskable.

#### Scenario: Proxy error page
- **WHEN** a navigation returns HTTP 502 and a cached shell exists
- **THEN** the cached shell is shown; without one the error response is shown

#### Scenario: Unknown path or OAuth return URL
- **WHEN** a navigation to `/?wahoo=connected` or an unknown path succeeds
- **THEN** no additional cache entry is created

#### Scenario: Unlisted file
- **WHEN** a same-origin GET for a file outside the precache list succeeds
- **THEN** it is not stored

Evidence: `public/service-worker.js` (`fetch` listener, `NAVIGATION_TIMEOUT_MS`, `CACHED_PATHS`, `VERSIONED_ASSETS`); `public/manifest.webmanifest`. Tests: `tests/service-worker-update.test.cjs::a server error on a navigation shows the cached app shell`; `tests/service-worker-update.test.cjs::navigations are cached under the app shell key only`; `tests/service-worker-update.test.cjs::only precached files are stored for other requests`; `e2e/service-worker-navigation.spec.js::@responsive unknown paths and OAuth return URLs add no navigation copies to the cache`; `tests/test_server_frontend.py::test_manifest_declares_any_and_maskable_icons_that_are_precached`.

### Requirement: Markdown subset

The Markdown renderer SHALL support only headings of level 1 to 3, unordered (`-`, `*`, `+`) and ordered (`1.`, `1)`) lists, fenced code, block quotes, horizontal rules, paragraphs with line breaks, pipe tables, strong, emphasis, code spans and links. Everything else SHALL stay escaped text.

#### Scenario: Link label hides the host
- **WHEN** a link label does not contain the host of its URL
- **THEN** the escaped host is shown in parentheses after the link

#### Scenario: Rejected link
- **WHEN** a URL does not start with `http://` or `https://`, has an empty label, contains parentheses or has surrounding spaces
- **THEN** the text stays literal and no anchor is created

#### Scenario: Table rows
- **WHEN** a table row has fewer cells than the header, or more
- **THEN** missing cells are padded and extra cells are dropped

Evidence: `public/views.js::replaceMarkdownLinks`; `public/views.js::linkHostNote`; `public/views.js::headingFromMarkdownLine`; `public/views.js::listItemFromMarkdownLine`. Tests: `tests/frontend-cleanup.test.cjs::a Coach link names its host when the label does not, and escapes it`; `tests/markdown-table.test.cjs::short rows are padded and extra cells beyond the header count are dropped`.

### Requirement: Shared confirmation dialog

Destructive or discarding actions SHALL use one modal confirmation with a title (default "Aktion bestätigen"), a message, "Abbrechen" and an accept button (default "Bestätigen"); `docs/view-catalogue.md` lists the texts per action. Closing the dialog in any way SHALL count as declined, and a newer confirmation SHALL decline a pending one.

#### Scenario: Typed confirmation
- **WHEN** an action requires a confirmation text
- **THEN** the dialog shows "Tippe „<text>“ zur Bestätigung.", focuses the text field and keeps the accept button disabled until the input equals the text exactly

#### Scenario: Secondary action
- **WHEN** the dialog offers a secondary action such as a backup download
- **THEN** the accept button stays disabled while it runs, its failure is shown inside the dialog and the dialog stays open

#### Scenario: Default focus
- **WHEN** no text is required
- **THEN** the cancel button receives the initial focus

Evidence: `public/auth.js::requestConfirmation`; `public/auth.js::runConfirmationSecondaryAction`; `public/auth.js::settleConfirmation`. Tests: `e2e/privacy-delete.spec.js::local data deletion requires the exact confirmation text`; `tests/test_server_frontend.py::test_frontend_uses_accessible_confirmation_dialogs`.

### Requirement: Toast timing and roles

A status toast SHALL be a polite `status` shown for 3 seconds. An error toast SHALL be an assertive `alert` shown for 8 seconds with a close button named "Meldung schließen". The session-ended message SHALL never be shown as a toast, because the login dialog already states it.

#### Scenario: Session ends during a request
- **WHEN** a request is aborted because the session ended
- **THEN** no toast appears

Evidence: `public/shared.js::toast`; `public/shared.js::sessionEndedError`. Tests: `tests/frontend-failure-paths.test.cjs::the session-ended abort is German, marked, and never toasted`; `e2e/status-strip.spec.js::@responsive a toast never covers the navigation`.

### Requirement: Quick message templates after a pause

The composer SHALL show the quick message templates only when the last recorded activity on this device is at least 6 hours old, and SHALL hide them while the Coach is busy. Activity SHALL be recorded on login, on return to the tab, on pointer input and when the page is hidden or left.

#### Scenario: First use on a device
- **WHEN** no activity time is stored
- **THEN** the templates are not shown

Evidence: `public/shared.js::notePwaActivity`; `public/shared.js::updatePwaActivity`; `public/shared.js::renderQuickMessageTemplates`. Tests: `e2e/coach-layout.spec.js::empty coach chat does not promise quick actions and keeps the composer gap @responsive`.

### Requirement: Composer control states

The composer SHALL never disable the draft field. The send control SHALL read "Senden", "Einreihen" while a turn runs, "Coach antwortet…" while a turn is recovered and "Antwort wird geladen…" while a completed answer is taken over, and SHALL be disabled without a draft, while the chat loads, attachments load, a recording or transcription runs, and in the last two states.

#### Scenario: Placeholder
- **WHEN** the chat is ready, busy, loading, or the selected Coach has no API key
- **THEN** the placeholder reads "Frage deinen Coach…", "Folgefrage – wird danach gesendet", "Coach-Chat wird geladen…" or "API-Schlüssel unter Mehr › Anbindungen hinterlegen…"

#### Scenario: Waiting messages
- **WHEN** messages wait behind a running turn
- **THEN** each is a bubble labelled "Als Nächstes" (the first) or "Wird nach der aktuellen Antwort gesendet", with "Bearbeiten" and "Entfernen"

#### Scenario: Cached chat
- **WHEN** the chat shows messages from the device before the server answered
- **THEN** the note "Nachrichten werden synchronisiert…" replaces the jump button until the fresh messages arrive or their load fails

Evidence: `public/coach.js::chatSendLabel`; `public/coach.js::updateChatSendButton`; `public/coach.js::chatInputPlaceholder`; `public/coach.js::createPendingMessage`; `public/coach.js::setChatCacheSyncing`. Tests: `e2e/coach-queue.spec.js::queued coach follow-ups keep order, can be edited or removed without browser persistence`; `e2e/coach-message-cache.spec.js::a failed fresh chat load ends the sync note and keeps the cached messages`.

### Requirement: Reply annotations and receipts

Under a Coach reply the client SHALL show its change labels joined by " · ", then one line per plan note as "Warnung|Hinweis: <label> · <dates> · <evidence>" using a fixed label and evidence phrase per note code; unknown codes are skipped. A user message with files SHALL show "Anhänge: <names>" and offer no edit action.

#### Scenario: Receipt toast
- **WHEN** a turn reports command receipts
- **THEN** one toast joins the distinct titles with " · ", failures first and the toast red when one failed; each tool has a fixed German title (for example `save_checkin` is "Tages-Check-in gespeichert"), read-only refresh and sync tools are left out unless they failed, a staged plan is left out when the turn also commits, and only the final plan commit counts

Evidence: `public/coach.js::appendMessageChanges`; `public/coach.js::appendPlanNotes`; `public/coach.js::messageAttachmentLabel`; `public/coach.js::receiptIsVisible`; `public/coach.js::toastCoachReceipts`; `public/coach.js` (`COACH_RECEIPT_LABELS`, `HIDDEN_CHAT_RECEIPT_TOOLS`). Tests: `tests/coach-turn-undo.test.cjs::plan notes render safe labels, dates, evidence and warning emphasis`; `tests/coach-receipts.test.cjs::a Coach action announces itself in one toast with its failures first`; `tests/coach-receipts.test.cjs::synchronization progress does not create chat cards`; `e2e/coach-plan-notes.spec.js`; `e2e/coach-tool-receipts.spec.js`.

### Requirement: Follow-latest and history paging rules

The chat SHALL follow new content only while the reader is within 48 px of the end. Following SHALL stop on a wheel-up, a downward finger move, PageUp, ArrowUp or Home outside an input, or an upward scroll of more than 4 px away from the end, and resume when the end is reached again or the jump control is used.

#### Scenario: Jump control
- **WHEN** content arrived while the reader was away
- **THEN** the control is named "Zur neuesten Antwort springen" and shows "Neue Antwort"; otherwise it is named "Zu den neuesten Nachrichten springen"

#### Scenario: Older messages
- **WHEN** "Weitere Nachrichten laden" is pressed, or comes within 200 px above the viewport after the first jump has settled
- **THEN** the next 100 messages are merged by id (else by turn id and role), the first visible message keeps its position, and "N ältere Nachrichten geladen" is announced

#### Scenario: New reply
- **WHEN** a reply starts while following
- **THEN** its start is placed 16 px below the top and later text keeps the newest line 12 px above the composer

Evidence: `public/coach.js::chatIsNearBottom`; `public/coach.js::chatScrollMovedUp`; `public/coach.js::updateChatJumpLabel`; `public/coach.js::appendHistoryPageButton`; `public/coach.js::mergeChatMessages`; `public/coach.js::scrollChatToResponseStart`. Tests: `e2e/coach-follow-latest.spec.js::a scrollbar drag upward during a stream stops following without a wheel gesture`; `e2e/coach-history-anchor.spec.js::automatic older chat loading keeps focus on the focused message action`.

### Requirement: Proposal card contract

A proposal card SHALL exist for the action types `undo_change`, `local_coach_write` and `remote_coach_write` and offer its actions only while the status is `preview` or `ready` and `expires_at` is in the future. Approval SHALL post `/api/coach/actions/confirm {proposal_id}` and then `/api/coach/actions/execute {action_token, payload_hash}` with the values of the confirm answer.

#### Scenario: Buttons
- **WHEN** a card is confirmable
- **THEN** it offers "Remote-Änderung freigeben", "Produkt speichern", "Mahlzeitvorlage speichern" or "Änderung zurücknehmen", and "Nicht freigeben" (cancels on the server) or, for an undo, "Später prüfen" (local dismissal)

#### Scenario: Known refusal
- **WHEN** confirm fails or execute answers 4xx
- **THEN** reasons `proposal_expired` and `proposal_payload_changed` retire the card as expired; `proposal_invalid`, `proposal_used`, `proposal_unavailable` and a 409 at confirm retire it as used

#### Scenario: Unknown type
- **WHEN** the action type is none of the three
- **THEN** the card is an alert "Unbekannte Aktion" without buttons

#### Scenario: After success
- **WHEN** execution succeeds
- **THEN** the client reloads plan, library, profile and feedback, and opens Produkte (saved product), Tagebuch (meal template) or the calendar (other local actions) unless the route changed meanwhile; an undo or remote action stays where it is

Evidence: `public/coach.js::coachActionCard`; `public/coach.js::coachActionButtons`; `public/coach.js::coachActionExpired`; `public/coach.js::executeCoachActionProposal`; `public/coach.js::rejectCoachActionProposal`; `public/coach.js::showCoachReceiptArea`. Tests: `tests/coach-action-confirm.test.cjs::a confirm 409 without a reason retires the card instead of re-enabling it`; `tests/coach-action-unknown.test.cjs::an unknown proposal action type renders a neutral error card without buttons`; `tests/coach-receipts.test.cjs::action destination precedes a slow refresh and preserves newer navigation`.

### Requirement: Calendar day notes and week figures

A calendar day SHALL show plain note lines for a competition ("<priority>-Wettkampf: <name>"), a day status ("Ruhetag", "Trainingspause") and one calendar line with the appointment names without marker tokens, each with " · ganztägig" or its start time, followed by the markers "Kein Training", "Keine Intensität" and "Nur kurze Einheiten". An empty day SHALL read "Keine Aktivität" (past) or "Keine Einheit geplant" (today and later), an empty week "Keine Einheiten".

#### Scenario: Week figures with missing values
- **WHEN** a completed ride, run, walk, hike, swim, nordic ski or row has no distance, or a session has no load
- **THEN** the week figure adds "N Aktivität(en) ohne Distanz" or "N Einheit(en) ohne Belastung"; other sports without a distance are not counted as missing

#### Scenario: Start time
- **WHEN** a planned unit is stored at midnight
- **THEN** no start time is shown, while a recorded activity keeps a midnight start

#### Scenario: Workout profile strip
- **WHEN** a session carries a workout profile of at most 1000 segments
- **THEN** a strip scaled to 110 % of its highest value is drawn; a profile with more segments or no value draws none

#### Scenario: Replan notice
- **WHEN** the plan needs a replan or an illness pause awaits a forecast or approval
- **THEN** the Coach view shows "Deine Planung braucht eine Anpassung" with the cause and "Coach fragen"

Evidence: `public/plan-views.js::plannedDayNoteSpecs`; `public/plan-views.js::renderPlannedDay`; `public/plan-views.js::calendarWeekDistance`; `public/plan-views.js::calendarWeekLoad`; `public/plan-views.js::plannedUnitStartTime`; `public/plan-views.js::calendarWorkoutProfile`; `public/plan-views.js::renderAdaptivePlanning`. Tests: `tests/calendar-badges.test.cjs::day notes show competition, confirmed rest status and one calendar line with deduplicated markers`; `tests/plan-views-week-distance.test.cjs::week distance reports distance sports without distance as missing`; `tests/plan-views-week-distance.test.cjs::week load sums known values and names the sessions without one`; `tests/plan-views-times.test.cjs::date-only planned units at midnight show no start time`; `tests/plan-views-times.test.cjs::completed activities keep their recorded midnight start time`; `tests/plan-views-adaptive-forecast.test.cjs`.

### Requirement: Analysis chart reading aids

Every analysis chart SHALL pad its value axis by 12 % of the span (at least a unit-specific minimum), label only the latest, highest, lowest and first reading, and offer "Werte ansehen" with a table of the plotted values. Each day with a value SHALL be one inspectable marker; the chart is one tab stop on the latest day and arrow keys, Home and End move between days.

#### Scenario: Weekly values
- **WHEN** the 12-week period is shown
- **THEN** each chart plots one value per week: the last value for acute and smoothed load, fitness and threshold pace, the sum for training time and session-RPE load, the mean for steps and floors, the median for VO2max, and every dated value for FTP

#### Scenario: Info popover
- **WHEN** the info control of a series is opened
- **THEN** it states "Daten für N von M Tagen|Wochen vorhanden." and, below three readings, "Wenige Messungen · kein belastbarer Trend."; the popover stays inside the viewport

#### Scenario: One reading
- **WHEN** a series has a single reading
- **THEN** no curve is drawn and "Ein einzelner Messwert zeigt noch keinen Verlauf; mindestens zwei datierte Werte sind erforderlich." is shown with the table

Evidence: `public/analysis.js::analysisChart`; `public/analysis.js::analysisPlotScales`; `public/analysis.js::analysisLabelledPoints`; `public/analysis.js::appendAnalysisPointInspectors`; `public/analysis.js::analysisWeeklyLastPoints`; `public/analysis.js::analysisWeeklySumPoints`; `public/analysis.js::analysisWeeklyMeanPoints`; `public/analysis.js::analysisWeeklyPerformancePoints`; `public/activity-analysis.js::chartRange`; `public/activity-analysis.js::speedChannel`. Tests: `e2e/analysis-info.spec.js::@responsive a history chart is one tab stop with arrow-key navigation inside a named region`; `tests/analysis-presentation.test.cjs::analysis popovers stay inside the viewport on narrow screens and flip above when needed`; `tests/analysis-presentation.test.cjs::weekly daily-activity mean averages known days and keeps empty weeks as gaps`.

### Requirement: Display formats

The client SHALL format numbers, dates and times for `de-DE`: numbers with at most one fraction digit unless a view states otherwise, distances in km with exactly one decimal, durations as "N min" below one hour and "h:mm h" from one hour, pace and lap times as "m:ss" or "h:mm:ss", a calendar day key without shifting the day, and relative days as "Heute", "Morgen", "Gestern", "in N Tagen" and "vor N Tagen".

#### Scenario: Sport label
- **WHEN** a session carries the neutral sport
- **THEN** it reads "Radfahren", "Rad indoor" (a ride indoors or virtual), "Laufen", "Schwimmen", "Kraft" or "Andere"

#### Scenario: Today
- **WHEN** a view needs today's date
- **THEN** it is the calendar day of the profile time zone, else of the browser

Evidence: `public/format.js` (`number`, `distance`, `duration`, `clock`, `relativeDay`); `public/performance-view.js::activitySportLabel`; `public/views.js::timezoneDateKey`. Tests: `tests/format.test.cjs::duration uses minutes under one hour and h:mm h from one hour`; `tests/plan-views-sport-label.test.cjs::completed activities are labelled from the canonical sport and environment`.

### Requirement: Operations area details

Betrieb & Diagnose SHALL read the newest 250 log entries and show each as "[time] LEVEL event: message {context}". Downloads SHALL use a 130-second deadline and the names `pacecraft-server-logs-<date>.jsonl`, `pacecraft-diagnostics-<date>.json`, `pacecraft-export-<date>.zip` and `pacecraft-database-<date>.backup`. The area SHALL offer no change-history view; undo is offered on receipts only.

#### Scenario: GPS tracks
- **WHEN** "GPS-Spuren speichern" is switched
- **THEN** the setting is saved at once and reverted on failure; "GPS-Spuren löschen (N)" appears only while storage is off and asks for the confirmation text the server supplies

#### Scenario: Privacy deletion result
- **WHEN** the deletion succeeded
- **THEN** a failed remote OpenAI conversation delete or Wahoo revocation is named, and so are recovery copies and server log files that could not be removed

Evidence: `public/diagnostics.js::loadLogs`; `public/diagnostics.js::formatLogEntry`; `public/diagnostics.js::downloadServerLogs`; `public/settings.js::downloadDatabaseBackup`; `public/settings.js::saveGpsTracks`; `public/settings.js::deleteGpsTracks`; `public/settings.js::deletePrivacyData`. Tests: `e2e/downloads.spec.js::settings and diagnostics downloads carry the Pacecraft name`; `e2e/first-threshold-gps.spec.js::the GPS-tracks switch takes clicks once loaded and a failed save restores the confirmed state`; `e2e/history-undo.spec.js::history panel is absent while diagnosis and logs remain available`.
