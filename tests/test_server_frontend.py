"""Server integration tests for frontend."""

import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import call, Mock

from backend.http_api import state_events_get
from backend.sync.adaptive import ILLNESS_CALENDAR_CATEGORY
from server_test_support import server, ServerTestCase


class ServerFrontendTests(ServerTestCase):

    def test_structured_coach_deletes_local_planned_unit_without_ui_preview(self):
        planned = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Remove me", "description": "- 20m 60% easy",
        })
        state = server.structured_training_state_service().read()
        target = next(item for item in state["planned_units"] if item["local_id"] == planned["id"])
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan"],
        }

        result = server.coach_tool_dispatch_service().execute(
            "apply_training_changes",
            {"expected_revision": state["planning_revision"], "changes": [{
                "local_id": planned["id"], "action": "delete",
                "expected_payload_hash": target["expected_payload_hash"],
            }]},
            intent=intent, conversation_id="conversation-delete", client_turn_id="turn-delete",
            session_csrf_hash="", sync_job_ids=[],
        )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["changes"][0]["status"], "deleted")
        self.assertEqual(server.planned_unit_service().list(), [])

    def test_frontend_loads_domain_areas_instead_of_monolithic_state(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        index = (Path(__file__).resolve().parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('async function loadState(path = "/api/bootstrap", requestedAreas = null)', app)
        self.assertIn('function load(path = "/api/bootstrap", requestedAreas = null)', app)
        self.assertIn('api("/api/chat/history?limit=100")', app)
        self.assertIn('api(`/api/weather${query}`)', app)
        self.assertIn('areas.push("weather")', app)
        self.assertIn('fetch("/api/chat/stream"', app)
        self.assertIn('api("/api/chat/status")', app)
        self.assertIn('new EventSource(`/api/state/events?since=', app)
        self.assertIn('function connectStateEvents()', app)
        self.assertIn('event.type === "reset"', app)
        self.assertIn('garmin: ["performance", "plan"]', app)
        self.assertIn('checkins: ["feedback", "plan"]', app)
        self.assertIn("function scrollChatToResponseStart()", app)
        self.assertIn("function restoreChatScrollPosition()", app)
        self.assertIn('state.chatScrollY = globalThis.scrollY', app)
        self.assertIn('state.chatInitialScrollPending', app)
        self.assertIn('globalThis.history.scrollRestoration = "manual"', app)
        self.assertIn("function latestAssistantMessageKey(messages)", app)
        self.assertIn('state.chatResponseScrollPending = true', app)
        self.assertIn('state.initialStateLoaded = true', app)
        initial_state = app[app.index("async function loadInitialState()"):app.index("function queueChatMessage(")]
        self.assertIn("const sessionGeneration = state.sessionGeneration", initial_state)
        self.assertIn("state.initialStateLoaded = false", initial_state)
        self.assertLess(initial_state.index("if (sessionGeneration !== state.sessionGeneration) return"), initial_state.index("state.initialStateLoaded = true"))
        self.assertLess(initial_state.index("state.initialStateLoaded = true"), initial_state.index("if (state.data?.profile?.weather_location)"))
        self.assertIn("!state.chatScrollRestoring", app)
        self.assertIn("async function loadChatHistoryFresh()", app)
        self.assertIn("chatProposalRefreshPending", app)
        self.assertIn("chatProposalRefreshInFlight", app)
        self.assertIn("chatProposalRefreshQueued", app)
        self.assertIn("if (state.chatProposalRefreshPending) void refreshChatProposalsInBackground", app)
        self.assertIn("state.chatStatusPollInFlight", app)
        self.assertIn('request.phase = "reconciling"', app)
        self.assertIn('request.phase = "recovering"', app)
        self.assertIn('event === "background"', app)
        self.assertIn('status.mode === "background"', app)
        self.assertIn('Der Coach arbeitet · du kannst die Seite neu laden…', app)
        self.assertIn('const streamVisible = state.chatStreamText && !persistedResponse', app)
        self.assertIn('aria-label="Zum Ende des Chats springen"', index)
        self.assertIn('<svg viewBox="0 0 24 24"', index)
        self.assertNotIn(">Neue Nachricht<", index)
        styles = (Path(__file__).resolve().parents[1] / "public" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".chat-jump", styles)
        self.assertIn("position: sticky", styles)
        self.assertNotIn("--bottom-nav-clearance", styles)
        self.assertNotIn("--chat-fixed-ui-clearance", styles)
        self.assertIn('async function cancelChat()', app)
        self.assertIn('markdownToHtml(state.chatStreamText)', app)
        self.assertIn('api("/api/activities?limit=250")', app)
        self.assertIn('api(`/api/plan${query}`)', app)
        self.assertIn('render(payload);\n      finishAppShellLoading();', app)
        self.assertIn('const appShellLoading = Boolean($("#appShell")?.classList.contains("is-loading"));', app)
        self.assertIn('renderMessages(state.data?.messages || [], true);', app)
        self.assertIn('api("/api/sync/status", { signal: controller.signal })', app)
        self.assertIn('const SYNC_POLL_ACTIVE_MS = 1_500;', app)
        self.assertNotIn('setInterval(() => {\n  if (state.localSync.intervals', app)

    def test_maintenance_ui_status_and_restore_asset_versions_are_present(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        api_client = (Path(__file__).resolve().parents[1] / "public" / "api.js").read_text(encoding="utf-8")
        index = (Path(__file__).resolve().parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        service_worker = (Path(__file__).resolve().parents[1] / "public" / "service-worker.js").read_text(encoding="utf-8")
        state = (Path(__file__).resolve().parents[1] / "public" / "state.js").read_text(encoding="utf-8")
        views = (Path(__file__).resolve().parents[1] / "public" / "views.js").read_text(encoding="utf-8")
        forms = (Path(__file__).resolve().parents[1] / "public" / "forms.js").read_text(encoding="utf-8")
        components = (Path(__file__).resolve().parents[1] / "public" / "components.js").read_text(encoding="utf-8")
        self.assertIn('"Wartungsmodus aktiv"', app)
        self.assertIn('status.maintenance', app)
        self.assertIn("globalThis.AppApi = Object.freeze({ audio, request, responseError });", api_client)
        self.assertIn("globalThis.AppApi.request(path, options, () =>", app)
        self.assertIn("globalThis.AppApi.audio(path, blob, () =>", app)
        self.assertIn("Array.isArray(result.model_options)", app)
        self.assertIn("renderModel(model)", app)
        self.assertIn('/api.js?v=217', index)
        self.assertIn('/navigation.js?v=217', index)
        self.assertIn('/state.js?v=217', index)
        self.assertIn('/views.js?v=217', index)
        self.assertIn('/forms.js?v=217', index)
        self.assertIn('/components.js?v=217', index)
        self.assertIn('/app.js?v=220', index)
        self.assertIn('intervals-coach-v220', service_worker)
        self.assertIn('"/navigation.js?v=217"', service_worker)
        self.assertIn('"/state.js?v=217"', service_worker)
        self.assertIn('"/views.js?v=217"', service_worker)
        self.assertIn('"/forms.js?v=217"', service_worker)
        self.assertIn('"/components.js?v=217"', service_worker)
        self.assertIn('id="connectivityNotice"', index)
        self.assertIn('id="coachActionReview"', index)
        self.assertIn('id="diagnosticCaptureToggle"', index)
        self.assertIn('function setDiagnosticCapture(', app)
        self.assertIn('/api/diagnostics/capture', app)
        self.assertIn('function executeCoachActionProposal(', app)
        self.assertIn('function renderConnectivityStatus(online = navigator.onLine)', app)
        self.assertIn('globalThis.addEventListener("offline"', app)
        self.assertIn('const state = {', state)
        self.assertIn('chatScrollRestoring: false', state)
        self.assertNotIn('const state = {', app)
        self.assertIn('function markdownToHtml(markdown)', views)
        self.assertNotIn('function markdownToHtml(markdown)', app)
        self.assertIn('function contextField(', forms)
        self.assertNotIn('function collectCompetitions()', forms)
        self.assertNotIn('function availabilityInput(', forms)
        self.assertNotIn('function contextField(', app)
        self.assertIn('function competitionCard(', app)
        self.assertNotIn('function competitionEditor(', app)
        self.assertNotIn('function syncCompetitions(', app)
        self.assertNotIn('id="competitionCoachButton"', index)
        self.assertIn('id="workoutsPanel"', index)
        self.assertIn('function showAccessibleDialog(', components)
        self.assertIn('function restoreDialogFocus(', components)
        self.assertNotIn('function showAccessibleDialog(', app)
        self.assertNotIn('function restoreDialogFocus(', app)
        self.assertLess(index.index('/forms.js?v=217'), index.index('/components.js?v=217'))
        self.assertLess(index.index('/components.js?v=217'), index.index('/app.js?v=220'))
        self.assertIn('aria-describedby="checkinDescription"', index)
        self.assertIn('id="checkinError" class="error" role="alert"', index)
        self.assertIn(
            'path != "/api/state/events"',
            Path(state_events_get.__file__).read_text(encoding="utf-8"),
        )

    def test_main_navigation_uses_stable_hash_links_and_focuses_active_panel(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        navigation = (Path(__file__).resolve().parents[1] / "public" / "navigation.js").read_text(encoding="utf-8")
        index = (Path(__file__).resolve().parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        for route in ("coach", "plan/overview", "analysis/performance", "more"):
            self.assertIn(f'href="#{route}"', index)
        self.assertIn('globalThis.addEventListener("hashchange", syncNavigationRoute)', app)
        self.assertIn("globalThis.history.pushState", app)
        self.assertIn("panel.focus({ preventScroll: true })", app)
        self.assertNotIn('today: "todayPanel"', navigation)
        self.assertNotIn('href="#today"', index)
        self.assertIn('analysis: "dataPanel"', navigation)
        self.assertIn('plan: "workoutsPanel"', navigation)
        self.assertIn('"analysis/performance": "dataPanel"', navigation)
        self.assertNotIn('activities: "analysis/history"', navigation)
        self.assertNotIn('planned: "plan"', navigation)
        self.assertNotIn('performance: "analysis/performance"', navigation)
        self.assertIn('class="desktop-nav"', index)
        self.assertIn('class="icon-sprite"', index)
        self.assertEqual(index.count('class="bottom-nav"'), 1)
        self.assertEqual(index[index.index('<nav class="bottom-nav"'):].split('</nav>', 1)[0].count('class="nav-item'), 4)
        self.assertNotIn('function renderToday(data)', app)

    def test_task8_coach_first_views_have_shared_states_and_analysis_segments(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        components = (Path(__file__).resolve().parents[1] / "public" / "components.js").read_text(encoding="utf-8")
        index = (Path(__file__).resolve().parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        state = (Path(__file__).resolve().parents[1] / "public" / "state.js").read_text(encoding="utf-8")
        styles = (Path(__file__).resolve().parents[1] / "public" / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn('id="coachOverview"', index)
        self.assertNotIn('Was möchtest du heute klären?', index)
        self.assertNotIn('id="coachProviderStatus"', index)
        self.assertNotIn('id="coachReadyStatus"', index)
        self.assertNotIn('id="coachAdjustPlanButton"', index)
        self.assertIn('id="coachReceipts"', index)
        self.assertIn('function renderCoachOverview(data)', app)
        self.assertIn('function renderCoachReceipts()', app)
        self.assertIn('if (HIDDEN_CHAT_RECEIPT_TOOLS.has(entry.tool) && !failedSync && !failedSyncJob) return false;', app)
        self.assertIn('"get_sync_job"', app)
        self.assertIn('"start_intervals_plan_sync"', app)
        self.assertNotIn('id="chatOperationLabel"', index)
        self.assertIn('node.setAttribute("aria-label", coachWorkingLabel());', app)
        self.assertNotIn('label.id = "coachWorkingLabel"', app)
        self.assertIn('position: fixed; z-index: 6; left: 50%; bottom:', styles)
        self.assertIn('function createActionReceipt(', components)
        self.assertIn('createSkeletonStack(4)', app)
        self.assertNotIn('id="todaySummary"', index)
        self.assertNotIn('today-priority', app)
        self.assertIn('id="analysisHistorySegment"', index)
        self.assertIn('id="analysisPerformanceSegment"', index)
        self.assertIn('function analysisSegmentFromRoute(', (Path(__file__).resolve().parents[1] / "public" / "navigation.js").read_text(encoding="utf-8"))
        self.assertIn('function renderAnalysisSegments(', app)
        self.assertIn('analysis-segment-nav', styles)
        self.assertIn('analysisSegment: "performance"', state)
        self.assertLess(index.index('data-analysis-segment="performance"'), index.index('data-analysis-segment="history"'))
        self.assertIn('data-analysis-segment-panel="performance" aria-labelledby="analysisPerformanceTitle">', index)
        self.assertIn('data-analysis-segment-panel="history" aria-labelledby="analysisHistoryTitle" hidden', index)
        self.assertIn('coachReceipts: []', state)
        self.assertNotIn('id="activitiesPanel"', index)

    def test_plan_route_has_read_only_overview_and_library_segments(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        navigation = (Path(__file__).resolve().parents[1] / "public" / "navigation.js").read_text(encoding="utf-8")
        state = (Path(__file__).resolve().parents[1] / "public" / "state.js").read_text(encoding="utf-8")
        index = (Path(__file__).resolve().parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('plan: "workoutsPanel"', navigation)
        self.assertIn('"plan/overview": "workoutsPanel"', navigation)
        self.assertIn('"plan/library": "workoutsPanel"', navigation)
        self.assertIn('function ensureRouteData(route = state.route)', app)
        self.assertIn('load("/api/bootstrap?local=1", requested)', app)
        self.assertIn('api("/api/library?limit=100")', app)
        self.assertIn('aria-label="Trainingskalender und Trainingsbibliothek"', index)
        self.assertIn('id="planOverviewTitle">Trainingskalender</h3>', index)
        self.assertIn('id="library"', index)
        self.assertIn('data-plan-segment="overview"', index)
        self.assertIn('data-plan-segment="library"', index)
        self.assertIn('id="plannedCalendar"', index)
        self.assertNotIn('id="trainingPlans"', index)
        self.assertNotIn('id="libraryLoadButton"', index)
        self.assertIn("function renderPlanned(", app)
        self.assertIn("function plannedWeekSummary(", app)
        self.assertIn('document.createElement("details")', app)
        self.assertIn("weekKey === currentWeekKey || weekKey === nextWeekKey", app)
        self.assertIn("state.data?.planning_compliance", app)
        self.assertIn("function plannedWeatherLabel(", app)
        self.assertIn("function calendarActualActivity(", app)
        self.assertIn("function calendarStatusLabel(", app)
        self.assertIn('renderPlanned(data.training_calendar || data.planned || [])', app)
        self.assertIn('function focusPlannedToday()', app)
        self.assertIn('today.scrollIntoView({ block: "start", behavior: "auto" })', app)
        self.assertIn('"RPE offen"', app)
        self.assertIn('"Trainingsload"', app)
        self.assertIn('Plan/Ist:', app)
        self.assertIn("daily_planning_context", app)
        self.assertIn('card.open = false', app)
        self.assertIn('section.open = false', app)
        self.assertIn('planned-day-calendar', app)
        self.assertIn('planned-day-health', app)
        plan_markup = index[index.index('id="workoutsPanel"'):index.index('id="checkinDialog"')]
        self.assertNotIn("<button", plan_markup)
        self.assertNotIn("planningEditDirty", state)
        self.assertNotIn("plannedWeekOpen", state)

    def test_frontend_preserves_date_only_values_and_renders_checkins(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        views = (Path(__file__).resolve().parents[1] / "public" / "views.js").read_text(encoding="utf-8")
        index = (Path(__file__).resolve().parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        self.assertIn('if (typeof value === "string" && /^\\d{4}-\\d{2}-\\d{2}$/.test(value)) return value;', views)
        self.assertIn('function renderCheckins(checkins, timeZone)', app)
        self.assertIn('id="checkinForm"', index)
        self.assertIn('id="checkinHistory"', index)
        self.assertIn('id="checkinDialog"', index)
        self.assertNotIn('id="todayPanel"', index)
        self.assertIn('name="day_form"', index)
        self.assertIn('name="illness"', index)
        self.assertNotIn('id="syncIllnessToIntervals"', app)
        self.assertIn('id="coachAdaptivePlanningButton"', index)
        self.assertEqual(ILLNESS_CALENDAR_CATEGORY, "SICK")
        self.assertNotIn('class="checkin-section"', index)
        self.assertNotIn("planned-day-checkin-button", app)
        self.assertNotIn('id="weatherNotice"', index)
        self.assertNotIn("function renderWeatherNotice", app)

    def test_intervals_connection_status_has_detail_and_refreshes_assets(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        service_worker = (server.PUBLIC_DIR / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('id="intervalsConnectionDetail"', markup)
        asset_version = markup.split('app.js?v=', 1)[1].split('"', 1)[0]
        self.assertIn(f'app.js?v={asset_version}', markup)
        self.assertIn(f'intervals-coach-v{asset_version}', service_worker)
        self.assertIn(f'/app.js?v={asset_version}', service_worker)

    def test_branding_is_not_rendered_in_header_and_version_is_in_settings(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATER TRAININGSBEREICH", markup)
        self.assertNotIn('id="appVersion"', markup)
        self.assertNotIn('id="desktopNavVersion"', markup)
        self.assertIn('id="settingsAppVersion"', markup)
        self.assertIn('$("#settingsAppVersion")', app_source)

    def test_privacy_ui_keeps_delete_feedback_without_plan_conflict_notice(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="privacyDeleteNotice"', markup)
        self.assertNotIn('id="remoteDeleteNotice"', markup)
        self.assertIn("remote_delete_attempted", app_source)

    def test_frontend_uses_accessible_confirmation_dialogs(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="confirmationDialog"', markup)
        self.assertIn('id="confirmationDialogInput"', markup)
        self.assertIn("function requestConfirmation(", app_source)
        self.assertIn("confirmationForm?.addEventListener(\"submit\"", app_source)
        self.assertNotIn("window.confirm", app_source)
        self.assertNotIn("window.prompt", app_source)

    def test_task9_browser_regression_contract_covers_routes_and_responsive_guards(self):
        e2e_source = (server.PUBLIC_DIR.parent / "e2e" / "coach.spec.js").read_text(encoding="utf-8")
        playwright_config = (server.PUBLIC_DIR.parent / "playwright.config.cjs").read_text(encoding="utf-8")
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        for route in ("#coach", "plan/overview", "analysis/performance", "#more"):
            self.assertIn(route, e2e_source)
        self.assertNotIn("#today", e2e_source)
        for guard in ("expectNoBrowserErrorsOrOverflow", "reducedMotion", 'fontSize = "200%"', "touch targets below 44"):
            self.assertIn(guard, e2e_source)
        self.assertIn('name: "desktop"', playwright_config)
        self.assertIn('name: "mobile"', playwright_config)
        self.assertIn("width: 390, height: 844", playwright_config)
        self.assertIn("interactive-widget=resizes-content", markup)
        self.assertIn("globalThis.visualViewport", app_source)

    def test_static_files_reject_path_traversal(self):
        static_assets = server.StaticAssetService(server.PUBLIC_DIR)

        for path in ("/../server.py", "/public/../../server.py", "/..\\server.py"):
            with self.subTest(path=path):
                with self.assertRaises(server.AppError) as error:
                    static_assets.render(path, path, None)
                self.assertEqual(error.exception.status, 403)

    def test_static_handler_rejects_path_traversal_without_request_attributes(self):
        handler = object.__new__(server.request_handler_class())

        with self.assertRaises(server.AppError) as error:
            server.request_handler_class().send_static(handler, "/../server.py")

        self.assertEqual(error.exception.status, 403)

    def test_static_files_reject_absolute_path(self):
        static_assets = server.StaticAssetService(server.PUBLIC_DIR)

        with self.assertRaises(server.AppError) as error:
            static_assets.render("/C:/Windows/win.ini", "/C:/Windows/win.ini", None)

        self.assertEqual(error.exception.status, 403)

    def test_versioned_static_assets_are_immutable_and_support_etag_revalidation(self):
        response = server.StaticAssetService(server.PUBLIC_DIR).render("/views.js", "/views.js?v=133", None)
        headers = dict(response.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertTrue(headers["ETag"].startswith('"'))

        cached = server.StaticAssetService(server.PUBLIC_DIR).render("/views.js", "/views.js?v=133", headers["ETag"])
        self.assertEqual(cached.status, 304)
        self.assertEqual(cached.body, b"")
        self.assertEqual(dict(cached.headers)["ETag"], headers["ETag"])

        handler = object.__new__(server.request_handler_class())
        handler.path = "/views.js?v=133"
        handler.headers = {"If-None-Match": headers["ETag"]}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()

        server.request_handler_class().send_static(handler, "/views.js")

        handler.send_response.assert_called_once_with(304)
        response_headers = {call.args[0]: call.args[1] for call in handler.send_header.call_args_list}
        self.assertEqual(response_headers["ETag"], headers["ETag"])
        self.assertEqual(response_headers["Cache-Control"], "public, max-age=31536000, immutable")
        handler.end_headers.assert_called_once_with()
        handler.wfile.write.assert_not_called()

    def test_html_and_service_worker_remain_revalidatable(self):
        for path in ("/", "/service-worker.js", "/manifest.webmanifest"):
            with self.subTest(path=path):
                response = server.StaticAssetService(server.PUBLIC_DIR).render(path, path, None)
                self.assertEqual(dict(response.headers)["Cache-Control"], "no-cache")

    def test_unknown_static_asset_falls_back_to_index_with_security_headers(self):
        response = server.StaticAssetService(server.PUBLIC_DIR).render("/missing.js", "/missing.js", None)
        headers = dict(response.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Content-Length"], str(len(response.body)))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_static_response_disconnect_is_logged_by_handler_transport(self):
        handler = object.__new__(server.request_handler_class())
        handler.path = "/"
        handler.headers = {}
        handler.static_asset_service = server.StaticAssetService(server.PUBLIC_DIR)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=BrokenPipeError())
        handler.wfile = Mock()
        handler.log_client_disconnect = Mock()

        server.request_handler_class().send_static(handler, "/")

        handler.log_client_disconnect.assert_called_once_with()
        handler.wfile.write.assert_not_called()

    def test_service_worker_caches_only_versioned_static_assets_and_not_api(self):
        source = (server.PUBLIC_DIR / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('"/api.js?v=217"', source)
        self.assertIn('"/navigation.js?v=217"', source)
        self.assertIn('"/state.js?v=217"', source)
        self.assertIn('"/views.js?v=217"', source)
        self.assertIn('"/forms.js?v=217"', source)
        self.assertIn('"/components.js?v=217"', source)
        self.assertIn('"/forms.js"', source)
        self.assertIn('"/app.js?v=220"', source)
        self.assertIn('"/icon.svg?v=217"', source)
        self.assertIn('"/styles.css?v=217"', source)
        self.assertIn('pathname.startsWith("/api/")', source)
        self.assertIn('event.request.method !== "GET"', source)
        self.assertIn("const VERSIONED_ASSETS = new Set", source)
        self.assertIn("cached || fetch(event.request)", source)
        self.assertIn("fetch(event.request).then", source)
        self.assertIn("cache.put(event.request, response.clone())", source)

    def test_app_loading_status_uses_a_real_unicode_ellipsis(self):
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('"Trainingsbereich wird geladen…"', app_source)
        self.assertNotIn("geladenâ€¦", app_source)

    def test_provider_refresh_ui_exposes_safe_retry_and_versioned_assets(self):
        index = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="providerFreshnessTimeline"', index)
        self.assertIn("function renderProviderFreshness(data)", app)
        self.assertIn("async function retryProvider(provider, button)", app)
        self.assertIn('provider === "intervals"', app)
        self.assertIn('provider === "weather"', app)
        self.assertIn('v=217', index)
        self.assertIn('id="connectionsSyncProgress"', index)
        self.assertIn('id="providerAttentionBanner"', index)
        self.assertIn("function renderConnectionsSyncProgress(data)", app)
        self.assertIn("function providerRequiresManualAttention(entry)", app)
        self.assertIn("function coachProviderLabel(provider)", app)
        self.assertIn('intervals: "Intervals.icu"', app)
        self.assertIn('garmin: "Garmin"', app)
        self.assertIn('calendar: "Gemeinsamer Kalender"', app)
        self.assertIn('weather: "Open-Meteo"', app)


if __name__ == "__main__":
    unittest.main()
