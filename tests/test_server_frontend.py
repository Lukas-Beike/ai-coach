"""Server integration tests for frontend."""

import re
import unittest
from datetime import datetime as _local_datetime
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from server_test_support import ServerTestCase, server

from backend.http_api import state_events_get
from backend.http_api.static_assets import StaticAssetService
from backend.sync.adaptive import ILLNESS_CALENDAR_CATEGORY


class ServerFrontendTests(ServerTestCase):
    def test_coach_ui_module_owns_chat_functions_and_event_wiring(self):
        root = Path(__file__).resolve().parents[1] / "public"
        app = (root / "app.js").read_text(encoding="utf-8")
        coach = (root / "coach.js").read_text(encoding="utf-8")
        for name in (
            "setVoiceStatus", "toggleVoiceInput", "chatControlState",
            "updateChatControls", "announceChatStatus", "renderCoachOverview",
            "renderCoachReceipts", "addStructuredCoachReceipts", "askCoach",
            "renderMessages", "handleWindowScroll", "executeCoachActionProposal",
            "renderContextPreview", "invalidateContextPreview", "loadContextPreview",
            "latestAssistantMessageKey", "applyChatGenerationChange", "applyChatResult",
            "refreshChatHistoryState", "renderChatAttachments",
            "validateChatAttachmentFiles", "fileBase64", "prepareChatAttachment",
            "setupCoachEvents",
        ):
            declaration = f"function {name}("
            self.assertIn(declaration, coach)
            self.assertNotIn(declaration, app)
        for selector in (
            "chatForm", "steerButton", "cancelChatButton", "voiceButton",
            "attachmentInput", "messageInput", "openaiChatResetButton",
        ):
            binding = f'$("#{selector}").addEventListener('
            self.assertIn(binding, coach)
            self.assertNotIn(binding, app)
        self.assertIn("setupCoachEvents();", app)

    def test_reset_button_selectors_exist_in_markup(self):
        root = Path(__file__).resolve().parents[1]
        scripts = "\n".join(
            (root / "public" / name).read_text(encoding="utf-8")
            for name in ("app.js", "coach.js")
        )
        index = (root / "public" / "index.html").read_text(encoding="utf-8")
        referenced_ids = set(
            re.findall(
                r"(?:getElementById\(|querySelector\(\s*|\$\(\s*)['\"]#([A-Za-z0-9_-]*reset[A-Za-z0-9_-]*)",
                scripts,
                re.IGNORECASE,
            )
        )
        markup_ids = set(re.findall(r"\bid=['\"]([^'\"]+)['\"]", index))

        self.assertTrue(referenced_ids)
        self.assertLessEqual(referenced_ids, markup_ids)

    def test_removed_ai_controls_and_reset_binding_match_markup(self):
        coach = (Path(__file__).resolve().parents[1] / "public" / "coach.js").read_text(encoding="utf-8")
        root = Path(__file__).resolve().parents[1]
        app = (root / "public" / "app.js").read_text(encoding="utf-8")
        index = (root / "public" / "index.html").read_text(encoding="utf-8")

        for identifier in ("chat" + "ResetButton", "ai" + "ProviderSelect"):
            self.assertNotIn(f'$("#{identifier}")', app)
            self.assertNotIn(f'id="{identifier}"', index)
        self.assertEqual(index.count('id="openaiChatResetButton"'), 1)
        self.assertIn('$("#openaiChatResetButton").addEventListener', coach)

    def test_structured_coach_deletes_local_planned_unit_without_ui_preview(self):
        planned = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    _local_datetime.now().astimezone().date() + timedelta(days=1)
                ).isoformat(),
                "sport": "Ride",
                "name": "Remove me",
                "description": "- 20m 60% easy",
            }
        )
        state = server.PLANNING_WORKFLOWS.structured_training_state_service().read()
        target = next(
            item for item in state["planned_units"] if item["local_id"] == planned["id"]
        )
        intent = {
            "intent": "local_action",
            "operation": "apply_training_changes",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_plan"],
        }

        result = server.COACH_TOOL_DISPATCH.service().execute(
            "apply_training_changes",
            {
                "expected_revision": state["planning_revision"],
                "changes": [
                    {
                        "local_id": planned["id"],
                        "action": "delete",
                        "expected_payload_hash": target["expected_payload_hash"],
                    }
                ],
            },
            intent=intent,
            conversation_id="conversation-delete",
            client_turn_id="turn-delete",
            session_csrf_hash="",
            sync_job_ids=[],
        )

        self.assertEqual(result["status"], "applied")
        self.assertEqual(result["changes"][0]["status"], "deleted")
        self.assertEqual(server.PLANNING_DATA.planned_unit().list(), [])

    def test_frontend_loads_domain_areas_instead_of_monolithic_state(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(
            encoding="utf-8"
        )
        coach = (Path(__file__).resolve().parents[1] / "public" / "coach.js").read_text(
            encoding="utf-8"
        )
        index = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'async function loadState(path = "/api/bootstrap", requestedAreas = null)',
            app,
        )
        self.assertIn(
            'function load(path = "/api/bootstrap", requestedAreas = null)', app
        )
        self.assertIn("await refreshChatHistoryState()", coach)
        self.assertIn("api(`/api/weather${query}`)", app)
        self.assertIn('areas.push("weather")', coach)
        self.assertIn('AppApi.stream("/api/chat/stream"', coach)
        self.assertIn('api("/api/chat/status")', coach)
        self.assertIn("new EventSource(`/api/state/events?since=", app)
        self.assertIn("function connectStateEvents()", app)
        self.assertIn('event.type === "reset"', app)
        self.assertIn('garmin: ["performance", "plan"]', app)
        self.assertIn('checkins: ["feedback", "plan"]', app)
        self.assertIn("function scrollChatToResponseStart()", coach)
        self.assertIn("function restoreChatScrollPosition()", coach)
        self.assertIn("state.chatScrollY = globalThis.scrollY", coach)
        self.assertIn("state.chatInitialScrollPending", app)
        self.assertIn('globalThis.history.scrollRestoration = "manual"', app)
        self.assertIn("function latestAssistantMessageKey(messages)", coach)
        self.assertIn("state.chatResponseScrollPending = true", coach)
        self.assertIn("state.initialStateLoaded = true", coach)
        initial_state = coach[
            coach.index("async function loadInitialState()") : coach.index(
                "function queueChatMessage("
            )
        ]
        self.assertIn(
            "const sessionGeneration = state.sessionGeneration", initial_state
        )
        self.assertIn("state.initialStateLoaded = false", initial_state)
        self.assertLess(
            initial_state.index(
                "if (sessionGeneration !== state.sessionGeneration) return"
            ),
            initial_state.index("state.initialStateLoaded = true"),
        )
        self.assertLess(
            initial_state.index("state.initialStateLoaded = true"),
            initial_state.index("if (state.data?.profile?.weather_location)"),
        )
        self.assertIn("!state.chatScrollRestoring", coach)
        self.assertIn("async function loadChatHistoryFresh()", coach)
        self.assertIn("chatProposalRefreshPending", coach)
        self.assertIn("chatProposalRefreshInFlight", coach)
        self.assertIn("chatProposalRefreshQueued", coach)
        self.assertIn(
            "if (state.chatProposalRefreshPending) void refreshChatProposalsInBackground",
            app,
        )
        self.assertIn("state.chatStatusPollInFlight", coach)
        self.assertIn('request.phase = "reconciling"', coach)
        self.assertIn('request.phase = "recovering"', coach)
        self.assertIn('event === "background"', coach)
        self.assertIn('status.mode === "background"', coach)
        self.assertIn("Der Coach arbeitet · du kannst die Seite neu laden…", coach)
        self.assertIn(
            "const streamVisible = state.chatStreamText && !persistedResponse", coach
        )
        self.assertIn('aria-label="Zu den neuesten Nachrichten springen"', index)
        self.assertIn('<svg viewBox="0 0 24 24"', index)
        self.assertNotIn(">Neue Nachricht<", index)
        styles = (
            Path(__file__).resolve().parents[1] / "public" / "styles.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".chat-jump", styles)
        self.assertIn("position: sticky", styles)
        self.assertNotIn("--bottom-nav-clearance", styles)
        self.assertNotIn("--chat-fixed-ui-clearance", styles)
        self.assertIn("async function cancelChat()", coach)
        self.assertIn("async function resetCoachChat()", coach)
        self.assertIn("function resetChatAfterGenerationChange(", coach)
        self.assertIn("markdownToHtml(state.chatStreamText)", coach)
        self.assertNotIn('api("/api/activities?limit=250")', app)
        self.assertIn("api(`/api/plan${query}`)", app)
        self.assertIn("render(payload);\n      finishAppShellLoading();", app)
        self.assertIn(
            'const appShellLoading = Boolean($("#appShell")?.classList.contains("is-loading"));',
            coach,
        )
        self.assertIn("renderMessages(state.data?.messages || [], true);", app)
        self.assertIn('api("/api/sync/status", { signal: controller.signal })', app)
        self.assertIn("const SYNC_POLL_ACTIVE_MS = 1_500;", app)
        self.assertNotIn("setInterval(() => {\n  if (state.localSync.intervals", app)

    def test_mobile_busy_composer_keeps_round_actions_and_centers_controls(self):
        styles = (
            Path(__file__).resolve().parents[1] / "public" / "styles.css"
        ).read_text(encoding="utf-8")
        self.assertIn(".composer-actions { display: flex; align-items: center;", styles)
        self.assertIn(
            ".composer.is-busy .composer-actions button:not(.attachment-button):not(.composer-stop-button):not(#sendButton)",
            styles,
        )

    def test_mobile_chat_layout_keeps_composer_clear_of_navigation_and_keyboard(self):
        coach = (Path(__file__).resolve().parents[1] / "public" / "coach.js").read_text(encoding="utf-8")
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(
            encoding="utf-8"
        )
        styles = (
            Path(__file__).resolve().parents[1] / "public" / "styles.css"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "#chatPanel .composer { bottom: calc(74px + max(12px, env(safe-area-inset-bottom))); }",
            styles,
        )
        self.assertIn(
            "html.chat-keyboard-open #chatPanel .composer { bottom: max(12px, env(safe-area-inset-bottom)); }",
            styles,
        )
        self.assertIn("root.scrollTop = root.scrollHeight;", coach)
        self.assertIn(
            "const viewportBottom = (viewport?.offsetTop || 0) + (viewport?.height || globalThis.innerHeight);",
            coach,
        )
        self.assertNotIn("chat-composer-hidden", app + styles)
        self.assertIn(".quick-message-templates::after", styles)

    def test_maintenance_ui_status_and_restore_asset_versions_are_present(self):
        coach = (Path(__file__).resolve().parents[1] / "public" / "coach.js").read_text(encoding="utf-8")
        root = Path(__file__).resolve().parents[1]
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(
            encoding="utf-8"
        )
        api_client = (
            Path(__file__).resolve().parents[1] / "public" / "api.js"
        ).read_text(encoding="utf-8")
        index = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        service_worker = (
            Path(__file__).resolve().parents[1] / "public" / "service-worker.js"
        ).read_text(encoding="utf-8")
        state = (Path(__file__).resolve().parents[1] / "public" / "state.js").read_text(
            encoding="utf-8"
        )
        views = (Path(__file__).resolve().parents[1] / "public" / "views.js").read_text(
            encoding="utf-8"
        )
        forms = (Path(__file__).resolve().parents[1] / "public" / "forms.js").read_text(
            encoding="utf-8"
        )
        components = (
            Path(__file__).resolve().parents[1] / "public" / "components.js"
        ).read_text(encoding="utf-8")
        self.assertIn('"Wartungsmodus aktiv"', app)
        self.assertIn("status.maintenance", app)
        self.assertIn(
            "globalThis.AppApi = Object.freeze({ audio, download, messageForReason, request, responseError, stream });",
            api_client,
        )
        self.assertIn("const REQUEST_TIMEOUT_MS = 25_000;", api_client)
        self.assertIn(
            "async function downloadRequest(path, fallback, timeoutMs = 25_000)", app
        )
        self.assertIn("globalThis.AppApi.request(path, options, () =>", app)
        self.assertIn("globalThis.AppApi.audio(path, blob, () =>", app)
        self.assertIn("renderModel(model)", views)
        self.assertIn("/api.js?v=223", index)
        self.assertIn("/navigation.js?v=231", index)
        self.assertIn("/appearance.js?v=218", index)
        self.assertNotIn("<script>", index)
        self.assertIn("/state.js?v=219", index)
        self.assertIn("/views.js?v=220", index)
        self.assertIn("/forms.js?v=217", index)
        self.assertIn("/components.js?v=217", index)
        self.assertIn("/coach.js?v=9", index)
        self.assertIn("/app.js?v=275", index)
        self.assertIn("/styles.css?v=281", index)
        self.assertIn("intervals-coach-v369", service_worker)
        self.assertIn("/analysis.js?v=94", index)
        self.assertIn('"/navigation.js?v=231"', service_worker)
        self.assertIn('"/appearance.js?v=218"', service_worker)
        self.assertIn('"/state.js?v=219"', service_worker)
        self.assertIn('"/views.js?v=220"', service_worker)
        self.assertIn('"/forms.js?v=217"', service_worker)
        self.assertIn('"/components.js?v=217"', service_worker)
        self.assertIn('id="connectivityNotice"', index)
        self.assertIn('id="coachActionReview"', index)
        self.assertIn('id="logsDownloadButton"', index)
        self.assertIn('id="logsDeleteButton"', index)
        self.assertIn('id="diagnosticsDeleteButton"', index)
        self.assertIn("function downloadServerLogs(", app)
        self.assertIn("function deleteServerLogs(", app)
        self.assertIn("function deleteDiagnostics(", app)
        self.assertIn(
            "async function downloadRequest(path, fallback, timeoutMs = 25_000)", app
        )
        self.assertNotIn("function withRequestTimeout(", app)
        self.assertIn("130_000", app)
        self.assertIn("/api/logs/download", app)
        self.assertIn("/api/logs/delete", app)
        self.assertIn('downloadRequest("/api/diagnostics"', app)
        self.assertIn("/api/diagnostics/delete", app)
        self.assertIn("globalThis.AppApi.download(path", app)
        self.assertNotIn("JSON.stringify(report, null, 2)", app)
        self.assertNotIn("diagnosticCaptureToggle", index + app)
        self.assertIn("function executeCoachActionProposal(", coach)
        self.assertIn(
            "function renderConnectivityStatus(online = navigator.onLine)", app
        )
        self.assertIn('globalThis.addEventListener("offline"', app)
        self.assertIn("const state = {", state)
        self.assertIn("chatScrollRestoring: false", state)
        self.assertNotIn("const state = {", app)
        navigation = (root / "public" / "navigation.js").read_text(encoding="utf-8")
        self.assertIn("globalThis.AppState = (() =>", state)
        self.assertIn("return Object.freeze({ state, secureToken, setRoute, setPlanSegment });", state)
        self.assertIn("if (!Object.hasOwn(state, key)) throw new Error(`Unknown state key: ${key}`);", state)
        self.assertNotIn("return false", state)
        self.assertIn("function setRoute(route)", state)
        self.assertIn("function setPlanSegment(segment)", state)
        self.assertIn("globalThis.AppRouter = (() =>", navigation)
        self.assertIn("globalThis.addEventListener(\"hashchange\", syncFromHash);", navigation)
        self.assertIn("if (!configured) throw new Error(\"AppRouter is not configured\");", navigation)
        self.assertIn("requiredHandlers.some((name) => typeof nextHandlers[name] !== \"function\")", navigation)
        self.assertIn("globalThis.AppNavigation = Object.freeze", navigation)
        self.assertIn('planSegments: PLAN_SEGMENTS', navigation)
        self.assertIn('moreSegments: MORE_SEGMENTS', navigation)
        self.assertIn('const PLAN_SEGMENTS = Object.freeze(["overview", "library", "season"]);', navigation)
        self.assertIn('const MORE_SEGMENTS = Object.freeze(["profile", "equipment", "connections", "coach", "privacy", "operations", "appearance"]);', navigation)
        self.assertLess(
            navigation.index("function configure(nextHandlers)"),
            navigation.index('globalThis.addEventListener("hashchange", syncFromHash);'),
        )
        self.assertIn("if (!hashchangeRegistered)", navigation)
        self.assertIn("function routeFromHash(", navigation)
        self.assertIn("function renderMoreSegments(segment)", views)
        self.assertIn("AppNavigation.moreSegments.includes(segment)", views)
        self.assertIn("AppNavigation.planSegments.includes(segment)", views)
        self.assertNotIn("AppNavigation.moreSegmentFromRoute()", views)
        self.assertNotIn("AppState.state.planSegment", views)
        self.assertNotIn("AppState.setPlanSegment(selected)", views)
        self.assertNotIn("renderSeasonPreparation()", views)
        self.assertIn("AppState.setPlanSegment(planSegment);", app)
        self.assertIn("if (planSegment === \"season\" && state.data) void renderSeasonPreparation();", app)
        public_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (root / "public").glob("*.js")
        )
        self.assertNotRegex(public_source, r"\bstate\.(?:route|planSegment)\s*=(?!=)")
        self.assertNotIn("function applyNavigationRoute(", app)
        self.assertNotIn("function syncNavigationRoute(", app)
        self.assertIn("function markdownToHtml(markdown)", views)
        self.assertNotIn("function markdownToHtml(markdown)", app)
        self.assertIn("function contextField(", forms)
        self.assertNotIn("function collectCompetitions()", forms)
        self.assertNotIn("function availabilityInput(", forms)
        self.assertNotIn("function contextField(", app)
        self.assertIn("function competitionCard(", app)
        self.assertNotIn("function competitionEditor(", app)
        self.assertNotIn("function syncCompetitions(", app)
        self.assertNotIn('id="competitionCoachButton"', index)
        self.assertIn('id="workoutsPanel"', index)
        self.assertIn("function showAccessibleDialog(", components)
        self.assertIn("function restoreDialogFocus(", components)
        self.assertNotIn("function showAccessibleDialog(", app)
        self.assertNotIn("function restoreDialogFocus(", app)
        self.assertLess(
            index.index("/forms.js?v=217"), index.index("/components.js?v=217")
        )
        self.assertLess(
            index.index("/components.js?v=217"), index.index("/coach.js?v=9")
        )
        self.assertLess(index.index("/coach.js?v=9"), index.index("/app.js?v=275"))
        self.assertIn('aria-describedby="checkinDescription"', index)
        self.assertIn('id="checkinError" class="error" role="alert"', index)
        self.assertIn(
            'path != "/api/state/events"',
            Path(state_events_get.__file__).read_text(encoding="utf-8"),
        )

    def test_frontend_api_errors_and_live_status_contracts(self):
        root = Path(__file__).resolve().parents[1]
        api_client = (root / "public" / "api.js").read_text(encoding="utf-8")
        app = (root / "public" / "app.js").read_text(encoding="utf-8")
        coach = (root / "public" / "coach.js").read_text(encoding="utf-8")
        index = (root / "public" / "index.html").read_text(encoding="utf-8")
        for reason in (
            "upstream_auth",
            "upstream_rate_limited",
            "upstream_unavailable",
            "upstream_rejected",
            "upstream_not_found",
        ):
            self.assertIn(f'{reason}: "', api_client)
        self.assertIn("function safeErrorMessage(response, payload, fallback)", api_client)
        self.assertIn('if (response.status === 404)', api_client)
        self.assertIn("globalThis.AppApi.download(path", app)
        self.assertIn('AppApi.stream("/api/chat/stream"', coach)
        self.assertNotIn('fetch("/api/', app + coach)
        self.assertNotIn("completed.error_class", app)
        self.assertNotIn('id="messages" class="messages" aria-live=', index)
        self.assertIn('<output id="chatOperationStatus" class="sr-only" aria-live="polite"', index)
        self.assertIn("if (!status || status.textContent === message) return;", coach)
        self.assertIn('announceChatStatus("Antwort fertig.")', coach)

    def test_main_navigation_uses_stable_hash_links_and_focuses_active_panel(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(
            encoding="utf-8"
        )
        router = (Path(__file__).resolve().parents[1] / "public" / "navigation.js").read_text(
            encoding="utf-8"
        )
        navigation = (
            Path(__file__).resolve().parents[1] / "public" / "navigation.js"
        ).read_text(encoding="utf-8")
        index = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        for route in ("coach", "plan/overview", "analysis/performance", "more"):
            self.assertIn(f'href="#{route}"', index)
        self.assertIn('globalThis.addEventListener("hashchange", syncFromHash)', router)
        self.assertIn("globalThis.history.pushState", router)
        self.assertIn("panel.focus({ preventScroll: true })", router)
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
        self.assertEqual(
            index[index.index('<nav class="bottom-nav"') :]
            .split("</nav>", 1)[0]
            .count('class="nav-item'),
            5,
        )
        self.assertNotIn("function renderToday(data)", app)

    def test_task8_coach_first_views_have_shared_states_and_analysis_segments(self):
        coach = (Path(__file__).resolve().parents[1] / "public" / "coach.js").read_text(encoding="utf-8")
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(
            encoding="utf-8"
        )
        components = (
            Path(__file__).resolve().parents[1] / "public" / "components.js"
        ).read_text(encoding="utf-8")
        index = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        state = (Path(__file__).resolve().parents[1] / "public" / "state.js").read_text(
            encoding="utf-8"
        )
        styles = (
            Path(__file__).resolve().parents[1] / "public" / "styles.css"
        ).read_text(encoding="utf-8")
        self.assertNotIn('id="coachOverview"', index)
        self.assertNotIn("Was möchtest du heute klären?", index)
        self.assertNotIn('id="coachProviderStatus"', index)
        self.assertNotIn('id="coachReadyStatus"', index)
        self.assertNotIn('id="coachAdjustPlanButton"', index)
        self.assertIn('id="coachReceipts"', index)
        self.assertIn("function renderCoachOverview(data)", coach)
        self.assertIn("function renderCoachReceipts()", coach)
        self.assertIn(
            "if (HIDDEN_CHAT_RECEIPT_TOOLS.has(entry.tool) && !failedSync && !failedSyncJob) return false;",
            coach,
        )
        self.assertIn('"get_sync_job"', coach)
        self.assertIn('"start_intervals_plan_sync"', coach)
        self.assertNotIn('id="chatOperationLabel"', index)
        self.assertIn('node.setAttribute("aria-label", coachWorkingLabel());', coach)
        self.assertNotIn('label.id = "coachWorkingLabel"', app)
        self.assertIn(".coach-working { align-self: flex-start;", styles)
        self.assertIn("function createActionReceipt(", components)
        self.assertIn("createSkeletonStack(4)", coach)
        self.assertNotIn('id="todaySummary"', index)
        self.assertNotIn("today-priority", app)
        self.assertNotIn('id="analysisHistorySegment"', index)
        self.assertNotIn(
            "analysis/history",
            navigation_source := (
                Path(__file__).resolve().parents[1] / "public" / "navigation.js"
            ).read_text(encoding="utf-8"),
        )
        self.assertNotIn("function analysisSegmentFromRoute(", navigation_source)
        self.assertNotIn("function renderActivities(", app)
        self.assertNotIn("activityFromDate", app + state + index)
        self.assertNotIn("analysis-segment-nav", styles + index)
        self.assertIn('id="performancePredictions"', index)
        self.assertEqual(index.count('aria-label="Kalender"'), 2)
        self.assertIn("<h2>Kalender</h2>", index)
        self.assertIn("coachReceipts: []", state)
        self.assertNotIn('id="activitiesPanel"', index)

    def test_plan_route_has_read_only_overview_and_library_segments(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(
            encoding="utf-8"
        )
        navigation = (
            Path(__file__).resolve().parents[1] / "public" / "navigation.js"
        ).read_text(encoding="utf-8")
        state = (Path(__file__).resolve().parents[1] / "public" / "state.js").read_text(
            encoding="utf-8"
        )
        index = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn('plan: "workoutsPanel"', navigation)
        self.assertIn('"plan/overview": "workoutsPanel"', navigation)
        self.assertIn('"plan/library": "workoutsPanel"', navigation)
        self.assertIn("function ensureRouteData(route = state.route)", app)
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
        self.assertIn(
            "renderPlanned(data.training_calendar || data.planned || [])", app
        )
        self.assertIn("function focusPlannedToday()", app)
        self.assertIn('today.scrollIntoView({ block: "start", behavior: "auto" })', app)
        self.assertIn('"RPE offen"', app)
        self.assertIn('"Trainingsload"', app)
        self.assertIn("Plan/Ist:", app)
        self.assertIn("daily_planning_context", app)
        self.assertIn("card.open = false", app)
        self.assertIn("section.open = false", app)
        self.assertIn("planned-day-calendar", app)
        self.assertIn("planned-day-health", app)
        plan_markup = index[
            index.index('id="workoutsPanel"') : index.index('id="checkinDialog"')
        ]
        self.assertNotIn("<button", plan_markup)
        self.assertNotIn("planningEditDirty", state)
        self.assertNotIn("plannedWeekOpen", state)

    def test_frontend_preserves_date_only_values_and_renders_checkins(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(
            encoding="utf-8"
        )
        views = (Path(__file__).resolve().parents[1] / "public" / "views.js").read_text(
            encoding="utf-8"
        )
        index = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'if (typeof value === "string" && /^\\d{4}-\\d{2}-\\d{2}$/.test(value)) return value;',
            views,
        )
        self.assertIn("function renderCheckins(checkins, timeZone)", views)
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
        service_worker = (server.PUBLIC_DIR / "service-worker.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="intervalsConnectionDetail"', markup)
        asset_version = markup.split("app.js?v=", 1)[1].split('"', 1)[0]
        self.assertIn(f"app.js?v={asset_version}", markup)
        self.assertIn("intervals-coach-v369", service_worker)
        self.assertIn(f"/app.js?v={asset_version}", service_worker)

    def test_branding_is_not_rendered_in_header_and_version_is_in_settings(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATER TRAININGSBEREICH", markup)
        self.assertNotIn('id="appVersion"', markup)
        self.assertNotIn('id="desktopNavVersion"', markup)
        self.assertIn('id="settingsAppVersion"', markup)
        views_source = (server.PUBLIC_DIR / "views.js").read_text(encoding="utf-8")
        self.assertIn('$("#settingsAppVersion")', views_source)

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
        self.assertIn('confirmationForm?.addEventListener("submit"', app_source)
        self.assertNotIn("window.confirm", app_source)
        self.assertNotIn("window.prompt", app_source)

    def test_task9_browser_regression_contract_covers_routes_and_responsive_guards(
        self,
    ):
        e2e_source = (server.PUBLIC_DIR.parent / "e2e" / "coach.spec.js").read_text(
            encoding="utf-8"
        )
        playwright_config = (
            server.PUBLIC_DIR.parent / "playwright.config.cjs"
        ).read_text(encoding="utf-8")
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        for route in ("#coach", "plan/overview", "analysis/performance", "#more"):
            self.assertIn(route, e2e_source)
        self.assertNotIn("#today", e2e_source)
        for guard in (
            "expectNoBrowserErrorsOrOverflow",
            "reducedMotion",
            'fontSize = "200%"',
            "touch targets below 44",
        ):
            self.assertIn(guard, e2e_source)
        self.assertIn('name: "desktop"', playwright_config)
        self.assertIn('name: "mobile"', playwright_config)
        self.assertIn("width: 390, height: 844", playwright_config)
        self.assertIn("interactive-widget=resizes-content", markup)
        self.assertIn("globalThis.visualViewport", app_source)

    def test_static_files_reject_path_traversal(self):
        static_assets = StaticAssetService(server.PUBLIC_DIR)

        for path in ("/../server.py", "/public/../../server.py", "/..\\server.py"):
            with self.subTest(path=path):
                with self.assertRaises(server.AppError) as error:
                    static_assets.render(path, path, None)
                self.assertEqual(error.exception.status, 403)

    def test_static_handler_rejects_path_traversal_without_request_attributes(self):
        handler = object.__new__(server.HTTP_API.request_handler_class())

        with self.assertRaises(server.AppError) as error:
            server.HTTP_API.request_handler_class().send_static(
                handler, "/../server.py"
            )

        self.assertEqual(error.exception.status, 403)

    def test_static_files_reject_absolute_path(self):
        static_assets = StaticAssetService(server.PUBLIC_DIR)

        with self.assertRaises(server.AppError) as error:
            static_assets.render("/C:/Windows/win.ini", "/C:/Windows/win.ini", None)

        self.assertEqual(error.exception.status, 403)

    def test_nutrition_asset_is_served_as_immutable_javascript(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/nutrition.js", "/nutrition.js?v=21", None
        )
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", dict(response.headers)["Content-Type"])
        self.assertEqual(
            dict(response.headers)["Cache-Control"],
            "public, max-age=31536000, immutable",
        )

    def test_nutrition_source_label_leaves_sync_state_to_card(self):
        source = (server.PUBLIC_DIR / "nutrition.js").read_text(encoding="utf-8")
        self.assertIn("return sourceLabel;", source)
        self.assertNotIn(
            'return sourceLabel + (item.template ? "" : item.syncLabel);', source
        )

    def test_analysis_asset_is_served_and_precached_as_javascript(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/analysis.js", "/analysis.js?v=94", None
        )
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", dict(response.headers)["Content-Type"])
        self.assertEqual(
            dict(response.headers)["Cache-Control"],
            "public, max-age=31536000, immutable",
        )
        self.assertIn(b"function renderAnalysisHistory", response.body)
        worker = (server.PUBLIC_DIR / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('"/analysis.js?v=94"', worker)
        index = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('/analysis.js?v=94"', index)
        self.assertNotIn("/analysis.js?v=93", index + worker)
        self.assertIn('const CACHE = "intervals-coach-v369";', worker)
        source = response.body.decode("utf-8")
        self.assertIn("equipment-archive", source)
        self.assertIn("function appendEquipmentLifetime", source)
        self.assertIn("function renderBodyAnalysis", source)
        self.assertIn("history?.body", source)
        self.assertIn(r"Ziel \u00fcberschritten", source)

    def test_versioned_static_assets_are_immutable_and_support_etag_revalidation(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/appearance.js", "/appearance.js?v=218", None
        )
        headers = dict(response.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(
            headers["Cache-Control"], "public, max-age=31536000, immutable"
        )
        self.assertTrue(headers["ETag"].startswith('"'))

        cached = StaticAssetService(server.PUBLIC_DIR).render(
            "/appearance.js", "/appearance.js?v=218", headers["ETag"]
        )
        self.assertEqual(cached.status, 304)
        self.assertEqual(cached.body, b"")
        self.assertEqual(dict(cached.headers)["ETag"], headers["ETag"])

        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.path = "/appearance.js?v=218"
        handler.headers = {"If-None-Match": headers["ETag"]}
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()

        server.HTTP_API.request_handler_class().send_static(handler, "/appearance.js")

        handler.send_response.assert_called_once_with(304)
        response_headers = {
            call.args[0]: call.args[1] for call in handler.send_header.call_args_list
        }
        self.assertEqual(response_headers["ETag"], headers["ETag"])
        self.assertEqual(
            response_headers["Cache-Control"], "public, max-age=31536000, immutable"
        )
        handler.end_headers.assert_called_once_with()
        handler.wfile.write.assert_not_called()

        coach = StaticAssetService(server.PUBLIC_DIR).render(
            "/coach.js", "/coach.js?v=9", None
        )
        self.assertEqual(coach.status, 200)
        self.assertEqual(
            dict(coach.headers)["Cache-Control"], "public, max-age=31536000, immutable"
        )

    def test_html_and_service_worker_remain_revalidatable(self):
        for path in ("/", "/service-worker.js", "/manifest.webmanifest"):
            with self.subTest(path=path):
                response = StaticAssetService(server.PUBLIC_DIR).render(
                    path, path, None
                )
                self.assertEqual(dict(response.headers)["Cache-Control"], "no-cache")

    def test_unknown_static_asset_falls_back_to_index_with_security_headers(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/missing.js", "/missing.js", None
        )
        headers = dict(response.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(headers["Content-Type"], "text/html; charset=utf-8")
        self.assertEqual(headers["Content-Length"], str(len(response.body)))
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_static_response_disconnect_is_logged_by_handler_transport(self):
        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.path = "/"
        handler.headers = {}
        handler.static_asset_service = StaticAssetService(server.PUBLIC_DIR)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=BrokenPipeError())
        handler.wfile = Mock()
        handler.log_client_disconnect = Mock()

        server.HTTP_API.request_handler_class().send_static(handler, "/")

        handler.log_client_disconnect.assert_called_once_with()
        handler.wfile.write.assert_not_called()

    def test_service_worker_caches_only_versioned_static_assets_and_not_api(self):
        source = (server.PUBLIC_DIR / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('"/api.js?v=223"', source)
        self.assertIn('"/navigation.js?v=231"', source)
        self.assertIn('"/appearance.js?v=218"', source)
        self.assertIn('"/state.js?v=219"', source)
        self.assertIn('"/views.js?v=220"', source)
        self.assertIn('"/forms.js?v=217"', source)
        self.assertIn('"/components.js?v=217"', source)
        self.assertIn('"/forms.js"', source)
        self.assertIn('"/coach.js?v=9"', source)
        self.assertIn('"/app.js?v=275"', source)
        self.assertIn('"/nutrition.js?v=21"', source)
        self.assertIn('"/icon.svg?v=217"', source)
        self.assertIn('"/styles.css?v=281"', source)
        self.assertIn('pathname.startsWith("/api/")', source)
        self.assertIn('event.request.method !== "GET"', source)
        self.assertIn("const VERSIONED_ASSETS = new Set", source)
        self.assertIn("cached || fetch(event.request)", source)
        self.assertIn("fetch(event.request).then", source)
        self.assertIn("cache.put(event.request, response.clone())", source)

    def test_service_worker_cleans_old_caches_and_scopes_cache_lookups(self):
        source = (server.PUBLIC_DIR / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn("const keys = await caches.keys()", source)
        self.assertIn(
            "await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))",
            source,
        )
        self.assertEqual(
            source.count(
                "caches.open(CACHE).then((cache) => cache.match(event.request))"
            ),
            2,
        )
        self.assertNotIn("caches.match(", source)

    def test_app_loading_status_uses_a_real_unicode_ellipsis(self):
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('"Trainingsbereich wird geladen…"', app_source)

    def test_provider_refresh_ui_exposes_safe_retry_and_versioned_assets(self):
        index = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="providerFreshnessTimeline"', index)
        self.assertIn("function renderProviderFreshness(data)", app)
        self.assertIn("async function retryProvider(provider, button)", app)
        self.assertIn('provider === "intervals"', app)
        self.assertIn('provider === "weather"', app)
        self.assertIn("v=217", index)
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
