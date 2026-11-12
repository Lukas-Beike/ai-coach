"""Server integration tests for frontend."""

import json
import re
import shutil
import struct
import tempfile
import unittest
from datetime import datetime as _local_datetime
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from server_test_support import ServerTestCase, server

VERSIONED_ASSET_REF = re.compile(r'(?<=[="])(/[^"?\s]+)\?v=([0-9a-f]{10})(?=")')
CACHE_NAME_PATTERN = r'const CACHE = "pacecraft-[0-9a-f]{10}";'


def versioned_asset_refs(markup):
    """Return every local ``/path?v=<hash>`` reference found in quoted markup or JS."""
    return [
        f"{path}?v={version}" for path, version in VERSIONED_ASSET_REF.findall(markup)
    ]


def served_page(name):
    """index.html or service-worker.js as the server stamps and serves it."""
    return StaticAssetService(server.PUBLIC_DIR).stamped(name).decode("utf-8")


def ref_in(markup, path):
    """Return the one ``path?v=<hash>`` reference of ``path`` in stamped markup."""
    matches = [
        ref for ref in versioned_asset_refs(markup) if ref.split("?", 1)[0] == path
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected one versioned index reference for {path}")
    return matches[0]


def asset_ref(path):
    """Return the ``path?v=<hash>`` reference that index.html currently serves."""
    return ref_in(served_page("index.html"), path)


def frontend_source():
    return "\n".join(
        (server.PUBLIC_DIR / name).read_text(encoding="utf-8")
        for name in (
            "shared.js",
            "auth.js",
            "status-strip.js",
            "sync-status.js",
            "notifications.js",
            "performance-view.js",
            "diagnostics.js",
            "state-loader.js",
            "sync-actions.js",
            "wahoo-connection.js",
            "provider-connections.js",
            "provider-checks.js",
            "settings.js",
            "app.js",
        )
    )


from backend.errors import AppError
from backend.http_api.static_assets import (
    CACHE_NAME_TOKEN,
    STATIC_TARGETS,
    VERSIONED_STATIC_ASSETS,
    StaticAssetService,
)
from backend.sync.adaptive import ILLNESS_CALENDAR_CATEGORY


class ServerFrontendTests(ServerTestCase):
    def test_app_is_bootstrap_only_for_moved_frontend_symbols(self):
        root = server.PUBLIC_DIR
        app = (root / "app.js").read_text(encoding="utf-8")
        moved = {
            "shared.js": (
                "applyAppearance",
                "renderActiveRoute",
                "updateMobileViewportLayout",
            ),
            "auth.js": ("showLogin", "requestConfirmation", "finishAppShellLoading"),
            "sync-status.js": (
                "connectStateEvents",
                "pollSyncStatus",
                "renderSyncStatus",
            ),
            "notifications.js": (
                "notificationPermission",
                "enableNotifications",
                "registerServiceWorker",
            ),
            "performance-view.js": (
                "renderPerformance",
                "activitySportLabel",
            ),
            "diagnostics.js": ("loadLogs", "deleteDiagnostics"),
            "state-loader.js": ("loadState", "load", "render"),
            "sync-actions.js": ("syncGarmin", "fullResync"),
            "wahoo-connection.js": (
                "connectWahoo",
                "disconnectWahoo",
                "renderWahooConnection",
            ),
            "provider-connections.js": (
                "saveProviderCredentials",
                "submitGarminLogin",
                "renderProviderCredentials",
            ),
            "settings.js": (
                "saveProfile",
                "saveCalendarDisplaySettings",
            ),
        }
        for module, names in moved.items():
            source = (root / module).read_text(encoding="utf-8")
            for name in names:
                self.assertRegex(source, rf"(?:async )?function {name}\(")
                self.assertNotRegex(app, rf"(?:async )?function {name}\(")

    def test_coach_ui_module_owns_chat_functions_and_event_wiring(self):
        root = Path(__file__).resolve().parents[1] / "public"
        app = frontend_source()
        coach = (root / "coach.js").read_text(encoding="utf-8")
        for name in (
            "setVoiceStatus",
            "toggleVoiceInput",
            "chatControlState",
            "updateChatControls",
            "announceChatStatus",
            "renderCoachOverview",
            "toastCoachReceipts",
            "addStructuredCoachReceipts",
            "askCoach",
            "renderMessages",
            "handleWindowScroll",
            "executeCoachActionProposal",
            "renderContextPreview",
            "invalidateContextPreview",
            "loadContextPreview",
            "latestAssistantMessageKey",
            "applyChatGenerationChange",
            "applyChatResult",
            "refreshChatHistoryState",
            "renderChatAttachments",
            "validateChatAttachmentFiles",
            "fileBase64",
            "prepareChatAttachment",
            "setupCoachEvents",
        ):
            declaration = f"function {name}("
            self.assertIn(declaration, coach)
            self.assertNotIn(declaration, app)
        for selector in (
            "chatForm",
            "steerButton",
            "cancelChatButton",
            "voiceButton",
            "attachmentInput",
            "messageInput",
            "openaiChatResetButton",
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

    def test_coach_start_keeps_scroll_and_proposal_refresh_wiring(self):
        app = frontend_source()
        coach = (Path(__file__).resolve().parents[1] / "public" / "coach.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("await refreshChatHistoryState()", coach)
        self.assertIn('globalThis.history.scrollRestoration = "manual"', app)
        self.assertIn("!state.chatScrollRestoring", coach)
        self.assertIn("async function loadChatHistoryFresh()", coach)
        self.assertIn("chatProposalRefreshPending", coach)
        self.assertIn("chatProposalRefreshInFlight", coach)
        self.assertIn("chatProposalRefreshQueued", coach)
        self.assertIn(
            "if (state.chatProposalRefreshPending) void refreshChatProposalsInBackground",
            app,
        )
        self.assertIn('request.phase = "reconciling"', coach)
        self.assertIn('request.phase = "recovering"', coach)
        self.assertIn('event === "background"', coach)
        self.assertIn(
            "const streamVisible = state.chatStreamText && !persistedResponse", coach
        )
        self.assertIn("function resetChatAfterGenerationChange(", coach)
        self.assertIn(
            'const appShellLoading = Boolean($("#appShell")?.classList.contains("is-loading"));',
            coach,
        )
        self.assertIn("renderMessages(state.data?.messages || [], true);", app)

    def test_chat_jump_button_sits_above_the_composer(self):
        styles = (
            Path(__file__).resolve().parents[1] / "public" / "styles.css"
        ).read_text(encoding="utf-8")
        start = styles.index(".composer .chat-jump {")
        jump_rule = styles[start : styles.index("}", start)]
        self.assertIn("var(--composer-height", jump_rule)
        self.assertIn("var(--composer-bg)", jump_rule)
        self.assertIn("box-shadow: 0 8px 22px var(--composer-shadow);", jump_rule)

    def test_message_action_icons_and_styles_are_defined(self):
        root = Path(__file__).resolve().parents[1]
        index = (root / "public" / "index.html").read_text(encoding="utf-8")
        styles = (root / "public" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<symbol id="icon-copy"', index)
        self.assertIn('<symbol id="icon-edit"', index)
        self.assertRegex(styles, r"\.message\.user\s*\{[^}]*max-width:\s*85%;")
        self.assertIn(".message-action:focus-visible {", styles)

    def test_maintenance_ui_status_and_restore_asset_versions_are_present(self):
        index = served_page("index.html")
        service_worker = served_page("service-worker.js")
        self.assertIn(asset_ref("/api.js"), index)
        self.assertIn(asset_ref("/navigation.js"), index)
        self.assertIn(asset_ref("/appearance.js"), index)
        self.assertNotIn("<script>", index)
        self.assertIn(asset_ref("/state.js"), index)
        self.assertIn(asset_ref("/views.js"), index)
        self.assertNotIn("/forms.js", index)
        self.assertIn(asset_ref("/components.js"), index)
        self.assertIn(asset_ref("/coach.js"), index)
        self.assertIn(asset_ref("/app.js"), index)
        self.assertIn(asset_ref("/styles.css"), index)
        self.assertRegex(service_worker, CACHE_NAME_PATTERN)
        self.assertIn(asset_ref("/analysis.js"), index)
        self.assertIn(f'"{asset_ref("/navigation.js")}"', service_worker)
        self.assertIn(f'"{asset_ref("/appearance.js")}"', service_worker)
        self.assertIn(f'"{asset_ref("/state.js")}"', service_worker)
        self.assertIn(f'"{asset_ref("/views.js")}"', service_worker)
        self.assertNotIn("/forms.js", service_worker)
        self.assertIn(f'"{asset_ref("/components.js")}"', service_worker)
        self.assertLess(
            index.index(asset_ref("/views.js")),
            index.index(asset_ref("/components.js")),
        )
        self.assertLess(
            index.index(asset_ref("/components.js")),
            index.index(asset_ref("/coach.js")),
        )
        self.assertLess(
            index.index(asset_ref("/coach.js")), index.index(asset_ref("/app.js"))
        )

    def test_frontend_api_wiring_and_removed_symbols_stay_out_of_the_app(self):
        root = server.PUBLIC_DIR
        app = frontend_source()
        index = (root / "index.html").read_text(encoding="utf-8")
        state = (root / "state.js").read_text(encoding="utf-8")
        views = (root / "views.js").read_text(encoding="utf-8")
        # Every request goes through api(), which adds the session handling and CSRF token.
        self.assertIn("globalThis.AppApi.request(path, options, () =>", app)
        self.assertIn("globalThis.AppApi.audio(path, blob, () =>", app)
        self.assertIn("globalThis.AppApi.download(path", app)
        self.assertNotIn("function withRequestTimeout(", app)
        self.assertNotIn("JSON.stringify(report, null, 2)", app)
        self.assertNotIn("diagnosticCaptureToggle", index + app)
        self.assertNotIn("const state = {", app)
        # state.js has no public setter for an arbitrary key, so this guard is not reachable from a test.
        self.assertIn(
            "if (!Object.hasOwn(state, key)) throw new Error(`Unknown state key: ${key}`);",
            state,
        )
        self.assertNotIn("return false", state)
        self.assertNotIn("AppNavigation.moreSegmentFromRoute()", views)
        self.assertNotIn("AppState.state.planSegment", views)
        self.assertNotIn("AppState.setPlanSegment(selected)", views)
        self.assertNotIn("renderSeasonPreparation()", views)
        self.assertNotIn("renderSeasonPreparation()", app)
        public_source = "\n".join(
            path.read_text(encoding="utf-8") for path in root.glob("*.js")
        )
        self.assertNotRegex(public_source, r"\bstate\.(?:route|planSegment)\s*=(?!=)")
        self.assertNotIn("function applyNavigationRoute(", app)
        self.assertNotIn("function syncNavigationRoute(", app)
        self.assertNotIn("function markdownToHtml(markdown)", app)
        self.assertFalse((root / "forms.js").exists())
        self.assertNotIn("function contextField(", app)
        self.assertNotIn("function competitionCard(", app)
        self.assertNotIn("function competitionEditor(", app)
        self.assertNotIn("function syncCompetitions(", app)
        self.assertNotIn('id="competitionCoachButton"', index)
        self.assertNotIn("function showAccessibleDialog(", app)
        self.assertNotIn("function restoreDialogFocus(", app)
        self.assertNotIn("function renderToday(data)", app)

    def test_frontend_api_errors_and_live_status_contracts(self):
        app = frontend_source()
        coach = (server.PUBLIC_DIR / "coach.js").read_text(encoding="utf-8")
        self.assertIn('AppApi.stream("/api/chat/stream"', coach)
        self.assertNotIn('fetch("/api/', app + coach)
        self.assertNotIn("completed.error_class", app)
        self.assertIn('announceChatStatus("Antwort fertig.")', coach)

    def test_task8_coach_first_views_have_shared_states_and_analysis_segments(self):
        public = server.PUBLIC_DIR
        coach = (public / "coach.js").read_text(encoding="utf-8")
        app = frontend_source()
        components = (public / "components.js").read_text(encoding="utf-8")
        index = (public / "index.html").read_text(encoding="utf-8")
        state = (public / "state.js").read_text(encoding="utf-8")
        styles = (public / "styles.css").read_text(encoding="utf-8")
        navigation = (public / "navigation.js").read_text(encoding="utf-8")
        self.assertNotIn('id="coachOverview"', index)
        self.assertNotIn("Was möchtest du heute klären?", index)
        self.assertNotIn('id="coachProviderStatus"', index)
        self.assertNotIn('id="coachReadyStatus"', index)
        self.assertNotIn('id="coachAdjustPlanButton"', index)
        self.assertNotIn('id="coachReceipts"', index)
        self.assertNotIn('id="chatOperationLabel"', index)
        self.assertNotIn('label.id = "coachWorkingLabel"', app)
        self.assertIn(".coach-working { align-self: flex-start;", styles)
        self.assertNotIn("function createActionReceipt(", components)
        self.assertIn("createSkeletonStack(4)", coach)
        self.assertNotIn('id="todaySummary"', index)
        self.assertNotIn("today-priority", app)
        self.assertNotIn('id="analysisHistorySegment"', index)
        self.assertNotIn("function analysisSegmentFromRoute(", navigation)
        self.assertNotIn("function renderActivities(", app)
        self.assertNotIn("activityFromDate", app + state + index)
        self.assertNotIn("analysis-segment-nav", styles + index)
        self.assertEqual(index.count('aria-label="Kalender"'), 2)
        self.assertNotIn("coachReceipts", state)
        self.assertNotIn('id="activitiesPanel"', index)

    def test_plan_route_has_read_only_overview_and_library_segments(self):
        public = server.PUBLIC_DIR
        app = frontend_source()
        state = (public / "state.js").read_text(encoding="utf-8")
        index = (public / "index.html").read_text(encoding="utf-8")
        plan_views = (public / "plan-views.js").read_text(encoding="utf-8")
        self.assertIn("function ensureRouteData(route = state.route)", app)
        self.assertIn('load("/api/bootstrap?local=1", requested)', app)
        self.assertIn('api("/api/library?limit=100")', app)
        self.assertIn('aria-label="Trainingskalender und Trainingsbibliothek"', index)
        self.assertIn('id="planOverviewTitle">Trainingskalender</h3>', index)
        self.assertNotIn('id="trainingPlans"', index)
        self.assertNotIn('id="libraryLoadButton"', index)
        self.assertIn("state.data?.planning_compliance", plan_views)
        self.assertNotIn('"Trainingsload"', plan_views)
        self.assertNotIn("Plan/Ist:", plan_views)
        self.assertIn("card.open = openPlannedEntries.has(entryKey)", plan_views)
        self.assertIn("section.open = false", plan_views)
        self.assertNotIn("function renderPlanned(", app)
        plan_markup = index[
            index.index('id="workoutsPanel"') : index.index('id="dataPanel"')
        ]
        # Read-only: the retry and the refresh button (reload + shared calendar sync) are the only buttons.
        self.assertEqual(plan_markup.count("<button"), 2)
        self.assertIn('id="planRefreshButton"', plan_markup)
        self.assertIn('id="competitionRetry" type="button"', plan_markup)
        self.assertNotIn("planningEditDirty", state)
        self.assertNotIn("plannedWeekOpen", state)

    def test_calendar_badges_are_text_safe_and_status_aware(self):
        root = server.PUBLIC_DIR
        plan_views = (root / "plan-views.js").read_text(encoding="utf-8")
        styles = (root / "styles.css").read_text(encoding="utf-8")
        self.assertIn(
            "plannedDayNotes(dayContext, state.data?.competitions, dateKey)",
            plan_views,
        )
        self.assertIn("state.data?.competitions, state.data?.weather", plan_views)
        self.assertNotIn("plannedDayCheckin", plan_views)
        self.assertNotIn("innerHTML", plan_views)
        # Conflicts use one component; day markers are neutral note text, not pills or link-blue text.
        self.assertNotIn(".planned-badge.is-conflict", styles)
        self.assertNotIn(".planned-badge.is-marker", styles)
        self.assertNotIn(
            "var(--link)", styles[styles.index(".planned-day-calendar") :][:200]
        )
        self.assertIn(".planned-entry.is-skipped .planned-entry-status", styles)
        self.assertIn(".planned-badges { display: flex; flex-wrap: wrap;", styles)

    def test_calendar_polish_texts_and_wrapping(self):
        public = server.PUBLIC_DIR
        plan_views = (public / "plan-views.js").read_text(encoding="utf-8")
        styles = (public / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn("Zusätzlich absolviert", plan_views)
        self.assertNotIn("Abgeschlossen", plan_views)
        self.assertNotIn("is-missing", plan_views)
        self.assertNotIn("weatherMissing", plan_views)
        self.assertIn(".planned-weather-hint {", styles)

    def test_frontend_preserves_date_only_values_and_renders_checkins(self):
        app = frontend_source()
        index = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="checkinDialog"', index)
        self.assertNotIn('id="todayPanel"', index)
        self.assertNotIn('id="syncIllnessToIntervals"', app)
        self.assertIn('id="coachAdaptivePlanningButton"', index)
        self.assertEqual(ILLNESS_CALENDAR_CATEGORY, "SICK")
        self.assertNotIn('class="checkin-section"', index)
        self.assertNotIn("planned-day-checkin-button", app)
        self.assertNotIn('id="weatherNotice"', index)
        self.assertNotIn("function renderWeatherNotice", app)

    def test_intervals_connection_status_has_detail_and_refreshes_assets(self):
        markup = served_page("index.html")
        service_worker = served_page("service-worker.js")
        self.assertIn('id="intervalsConnectionDetail"', markup)
        asset_version = markup.split("app.js?v=", 1)[1].split('"', 1)[0]
        self.assertIn(f"app.js?v={asset_version}", markup)
        self.assertRegex(service_worker, CACHE_NAME_PATTERN)
        self.assertIn(f"/app.js?v={asset_version}", service_worker)

    def test_branding_is_not_rendered_in_header_and_version_is_in_settings(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="appVersion"', markup)
        self.assertNotIn('id="desktopNavVersion"', markup)

    def test_privacy_ui_keeps_delete_feedback_without_plan_conflict_notice(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="remoteDeleteNotice"', markup)

    def test_frontend_uses_accessible_confirmation_dialogs(self):
        app_source = frontend_source()
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
        app_source = frontend_source()
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
                with self.assertRaises(AppError) as error:
                    static_assets.render(path, path, None)
                self.assertEqual(error.exception.status, 403)

    def test_static_handler_rejects_path_traversal_without_request_attributes(self):
        handler = object.__new__(server.HTTP_API.request_handler_class())

        with self.assertRaises(AppError) as error:
            server.HTTP_API.request_handler_class().send_static(
                handler, "/../server.py"
            )

        self.assertEqual(error.exception.status, 403)

    def test_static_files_reject_absolute_path(self):
        static_assets = StaticAssetService(server.PUBLIC_DIR)

        with self.assertRaises(AppError) as error:
            static_assets.render("/C:/Windows/win.ini", "/C:/Windows/win.ini", None)

        self.assertEqual(error.exception.status, 403)

    def test_nutrition_asset_is_served_as_immutable_javascript(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/nutrition.js", asset_ref("/nutrition.js"), None
        )
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", dict(response.headers)["Content-Type"])
        self.assertEqual(
            dict(response.headers)["Cache-Control"],
            "public, max-age=31536000, immutable",
        )

    def test_view_refresh_asset_is_served_as_immutable_javascript(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/view-refresh.js", asset_ref("/view-refresh.js"), None
        )
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", dict(response.headers)["Content-Type"])
        self.assertEqual(
            dict(response.headers)["Cache-Control"],
            "public, max-age=31536000, immutable",
        )

    def test_analysis_asset_is_served_and_precached_as_javascript(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/analysis.js", asset_ref("/analysis.js"), None
        )
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", dict(response.headers)["Content-Type"])
        self.assertEqual(
            dict(response.headers)["Cache-Control"],
            "public, max-age=31536000, immutable",
        )
        self.assertIn(b"function renderAnalysisHistory", response.body)
        worker = served_page("service-worker.js")
        self.assertIn(f'"{asset_ref("/analysis.js")}"', worker)
        index = served_page("index.html")
        self.assertIn(f'{asset_ref("/analysis.js")}"', index)
        self.assertEqual(index.count("/analysis.js?v="), 1)
        self.assertRegex(worker, CACHE_NAME_PATTERN)

    def test_analysis_chart_wiring_and_removed_labels(self):
        analysis = (server.PUBLIC_DIR / "analysis.js").read_text(encoding="utf-8")
        self.assertNotIn("Endurance Score", analysis)
        self.assertNotIn("Running Tolerance", analysis)
        self.assertIn("unit: providerMetricUnit(key)", analysis)
        self.assertIn('item.cadenceDays === 7 ? "Wochen" : "Tagen"', analysis)
        self.assertNotIn("Tage mit Messung", analysis)
        self.assertNotIn("${readings.length}/${item.points.length}", analysis)
        self.assertNotIn("function analysisIsoWeek(dateKey)", analysis)
        self.assertNotIn("renderExistingPerformanceReports", analysis)
        self.assertNotIn("renderRacePredictionCharts", analysis)
        self.assertIn(
            "weekTicks ? analysisWeekTickLabel : analysisDayTickLabel", analysis
        )
        self.assertIn("calendarWeeks: true", analysis)
        self.assertIn("calendarWeeks = false", analysis)

    def test_scroll_region_focus_ring_is_styled(self):
        styles = (server.PUBLIC_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".analysis-chart-table:focus-visible", styles)

    def test_versioned_static_assets_are_immutable_and_support_etag_revalidation(self):
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/appearance.js", asset_ref("/appearance.js"), None
        )
        headers = dict(response.headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(
            headers["Cache-Control"], "public, max-age=31536000, immutable"
        )
        self.assertTrue(headers["ETag"].startswith('"'))

        cached = StaticAssetService(server.PUBLIC_DIR).render(
            "/appearance.js", asset_ref("/appearance.js"), headers["ETag"]
        )
        self.assertEqual(cached.status, 304)
        self.assertEqual(cached.body, b"")
        self.assertEqual(dict(cached.headers)["ETag"], headers["ETag"])

        handler = object.__new__(server.HTTP_API.request_handler_class())
        handler.path = asset_ref("/appearance.js")
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
            "/coach.js", asset_ref("/coach.js"), None
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

    def test_pwa_asset_versions_match_service_worker_precache(self):
        index = served_page("index.html")
        service_worker = served_page("service-worker.js")
        precache = re.search(r"const ASSETS = \[(.*?)\];", service_worker, re.DOTALL)
        self.assertIsNotNone(precache)
        cached = re.findall(r'"([^"]+)"', precache.group(1))
        index_refs = versioned_asset_refs(index)
        self.assertTrue(index_refs)
        self.assertEqual(len(index_refs), len(set(index_refs)))
        # The shell, the unversioned manifest and its icons are cached; every
        # other precache entry is exactly one stamped reference of index.html.
        unstamped = {
            "/",
            "/manifest.webmanifest",
            "/icon-192.png",
            "/icon-512.png",
            "/icon-maskable-512.png",
        }
        self.assertEqual(unstamped, set(cached) - set(index_refs))
        self.assertEqual(set(index_refs), set(cached) - unstamped)
        self.assertRegex(service_worker, CACHE_NAME_PATTERN)

    def test_service_worker_precache_excludes_logo_and_links_apple_touch_icon(self):
        index = served_page("index.html")
        service_worker = served_page("service-worker.js")
        precache = re.search(r"const ASSETS = \[(.*?)\];", service_worker, re.DOTALL)
        self.assertIsNotNone(precache)
        icon = asset_ref("/apple-touch-icon.png")
        self.assertNotIn('"/logo.png', service_worker)
        self.assertIn(
            f'<link rel="apple-touch-icon" href="{icon}" sizes="180x180">', index
        )
        self.assertIn(f'"{icon}"', precache.group(1))
        self.assertTrue((server.PUBLIC_DIR / "logo.png").is_file())
        self.assertTrue((server.PUBLIC_DIR / "apple-touch-icon.png").is_file())

    def test_manifest_declares_any_and_maskable_icons_that_are_precached(self):
        manifest = json.loads(
            (server.PUBLIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8")
        )
        service_worker = served_page("service-worker.js")
        by_src = {icon["src"]: icon for icon in manifest["icons"]}
        self.assertEqual(by_src["/icon.svg"]["purpose"], "any")
        self.assertEqual(by_src["/icon-192.png"]["sizes"], "192x192")
        self.assertEqual(by_src["/icon-512.png"]["sizes"], "512x512")
        self.assertEqual(by_src["/icon-maskable-512.png"]["purpose"], "maskable")
        for src in by_src:
            self.assertTrue((server.PUBLIC_DIR / src.lstrip("/")).is_file(), src)
            self.assertIn(f'"{src}"', service_worker)
        for name, size in (
            ("icon-192.png", 192),
            ("icon-512.png", 512),
            ("icon-maskable-512.png", 512),
        ):
            header = (server.PUBLIC_DIR / name).read_bytes()[:24]
            self.assertEqual(header[1:4], b"PNG")
            self.assertEqual(struct.unpack(">II", header[16:24]), (size, size))

    def test_csp_allows_blob_images_for_the_decode_fallback(self):
        response = StaticAssetService(server.PUBLIC_DIR).render("/", "/", None)
        policy = dict(response.headers)["Content-Security-Policy"]
        self.assertIn("img-src 'self' data: blob:;", policy)
        self.assertIn("script-src 'self';", policy)

    def test_source_files_carry_no_version_numbers(self):
        # Hand-written versions are what made parallel UI branches conflict.
        index = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        worker = (server.PUBLIC_DIR / "service-worker.js").read_text(encoding="utf-8")
        for source in (index, worker):
            self.assertNotIn("?v=", source)
            self.assertNotRegex(source, r"pacecraft-v?\d")
        self.assertIn(f'"pacecraft-{CACHE_NAME_TOKEN}"', worker)

    def test_stamped_output_never_keeps_placeholder_or_unversioned_references(self):
        service = StaticAssetService(server.PUBLIC_DIR)
        for path in ("/", "/index.html", "/service-worker.js", "/missing.js"):
            with self.subTest(path=path):
                body = service.render(path, path, None).body.decode("utf-8")
                self.assertNotIn(CACHE_NAME_TOKEN, body)
        index = service.stamped("index.html").decode("utf-8")
        for ref in re.findall(r'(?:src|href)="(/[^"?]+)(\?[^"]*)?"', index):
            if ref[0].lstrip("/") in VERSIONED_STATIC_ASSETS:
                self.assertRegex(ref[1], r"^\?v=[0-9a-f]{10}$", ref[0])

    def test_cache_name_follows_cached_assets_and_ignores_the_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            shutil.copytree(server.PUBLIC_DIR, public, dirs_exist_ok=True)
            service = StaticAssetService(public)

            def stamps():
                return {
                    name: service.stamped(name).decode("utf-8")
                    for name in ("index.html", "service-worker.js")
                }

            def cache_name(worker):
                return re.search(CACHE_NAME_PATTERN, worker).group(0)

            def ref(page, path):
                return ref_in(page["index.html"], path)

            before = stamps()
            self.assertEqual(
                cache_name(before["service-worker.js"]),
                cache_name(stamps()["service-worker.js"]),
            )
            self.assertEqual(
                cache_name(before["service-worker.js"]),
                cache_name(
                    StaticAssetService(public).stamped("service-worker.js").decode()
                ),
            )
            # An uncached file does not change the cache name.
            (public / "logo.png").write_bytes(b"changed logo")
            self.assertEqual(before, stamps())
            for name, path in (
                ("app.js", "/app.js"),
                ("styles.css", "/styles.css"),
                ("icon.svg", "/icon.svg"),
            ):
                with self.subTest(asset=name):
                    previous = stamps()
                    with (public / name).open("ab") as handle:
                        handle.write(b"\n/* changed */\n")
                    current = stamps()
                    self.assertNotEqual(
                        cache_name(previous["service-worker.js"]),
                        cache_name(current["service-worker.js"]),
                    )
                    self.assertNotEqual(ref(previous, path), ref(current, path))
                    self.assertIn(
                        f'"{ref(current, path)}"', current["service-worker.js"]
                    )
                    for other in ("/api.js", "/views.js"):
                        self.assertEqual(ref(previous, other), ref(current, other))
            # The shell, the manifest and the worker itself are cached too.
            for name in ("index.html", "manifest.webmanifest", "service-worker.js"):
                with self.subTest(asset=name):
                    previous = stamps()
                    with (public / name).open("ab") as handle:
                        handle.write(b"\n")
                    self.assertNotEqual(
                        cache_name(previous["service-worker.js"]),
                        cache_name(stamps()["service-worker.js"]),
                    )

    def test_branches_editing_different_assets_leave_version_fields_untouched(self):
        sources = {
            name: (server.PUBLIC_DIR / name).read_bytes()
            for name in ("index.html", "service-worker.js")
        }
        with tempfile.TemporaryDirectory() as directory:
            roots = {}
            for branch, asset in (("a", "app.js"), ("b", "styles.css")):
                roots[branch] = Path(directory) / branch
                shutil.copytree(server.PUBLIC_DIR, roots[branch])
                with (roots[branch] / asset).open("ab") as handle:
                    handle.write(f"\n/* {branch} */\n".encode())
            for root in roots.values():
                for name, source in sources.items():
                    self.assertEqual(source, (root / name).read_bytes())
            merged = Path(directory) / "merged"
            shutil.copytree(roots["a"], merged)
            shutil.copy(roots["b"] / "styles.css", merged / "styles.css")
            stamped = {
                key: StaticAssetService(root).stamped("index.html").decode()
                for key, root in {**roots, "merged": merged}.items()
            }
            self.assertIn(
                ref_in(stamped["a"], "/app.js"),
                stamped["merged"],
            )
            self.assertIn(
                ref_in(stamped["b"], "/styles.css"),
                stamped["merged"],
            )

    def test_stamping_refuses_a_worker_without_its_cache_token_or_asset_files(self):
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            shutil.copytree(server.PUBLIC_DIR, public, dirs_exist_ok=True)
            worker = public / "service-worker.js"
            source = worker.read_text(encoding="utf-8")
            worker.write_text(
                source.replace(CACHE_NAME_TOKEN, "pacecraft-v1"), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                StaticAssetService(public).stamped("service-worker.js")
            worker.write_text(
                source.replace('"/app.js",', '"/app.js",\n  "/ghost.js",'),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                StaticAssetService(public).stamped("service-worker.js")

    def test_every_public_asset_is_served(self):
        # An unlisted public file is answered with index.html, so the browser
        # rejects it and every browser spec fails.
        files = {
            path.name
            for path in server.PUBLIC_DIR.iterdir()
            if path.is_file() and path.name != "AGENTS.md"
        }
        self.assertEqual(
            set(),
            files - set(STATIC_TARGETS),
            "add new public files to STATIC_TARGETS in backend/http_api/static_assets.py",
        )

    def test_service_worker_caches_only_versioned_static_assets_and_not_api(self):
        source = served_page("service-worker.js")
        self.assertIn(f'"{asset_ref("/api.js")}"', source)
        self.assertIn(f'"{asset_ref("/navigation.js")}"', source)
        self.assertIn(f'"{asset_ref("/appearance.js")}"', source)
        self.assertIn(f'"{asset_ref("/state.js")}"', source)
        self.assertIn(f'"{asset_ref("/views.js")}"', source)
        self.assertIn(f'"{asset_ref("/plan-views.js")}"', source)
        self.assertIn('"/plan-views.js"', source)
        self.assertIn(f'"{asset_ref("/components.js")}"', source)
        self.assertNotIn("forms.js", source)
        self.assertIn(f'"{asset_ref("/coach.js")}"', source)
        self.assertIn(f'"{asset_ref("/app.js")}"', source)
        self.assertIn(f'"{asset_ref("/nutrition.js")}"', source)
        self.assertIn(f'"{asset_ref("/view-refresh.js")}"', source)
        self.assertIn(f'"{asset_ref("/icon.svg")}"', source)
        self.assertIn(f'"{asset_ref("/styles.css")}"', source)

    def test_provider_refresh_markup_and_versioned_icon(self):
        index = served_page("index.html")
        self.assertIn('id="providerFreshnessTimeline"', index)
        self.assertIn(asset_ref("/icon.svg"), index)
        self.assertIn('id="connectionsSyncProgress"', index)
        self.assertNotIn('id="providerAttentionBanner"', index)

    def test_shared_format_module_is_loaded_and_served_before_consumers(self):
        index = served_page("index.html")
        worker = served_page("service-worker.js")
        version = re.search(
            r'<script src="/format\.js\?v=([0-9a-f]{10})" defer></script>', index
        )
        self.assertIsNotNone(version)
        asset = f"/format.js?v={version.group(1)}"
        self.assertLess(index.index(asset), index.index("/api.js?v="))
        self.assertIn(f'"{asset}"', worker)
        self.assertIn('"/format.js"', worker)
        response = StaticAssetService(server.PUBLIC_DIR).render(
            "/format.js", asset, None
        )
        self.assertEqual(response.status, 200)
        self.assertIn("javascript", dict(response.headers)["Content-Type"])
        self.assertEqual(
            dict(response.headers)["Cache-Control"],
            "public, max-age=31536000, immutable",
        )

    def test_user_visible_number_and_date_formatting_uses_app_format(self):
        public = Path(__file__).resolve().parents[1] / "public"
        forbidden = re.compile(
            r"toLocale(?:Date|Time)?String\(\)"
            r"|Intl\.(?:DateTimeFormat|NumberFormat)\(undefined"
        )
        offenders = [
            path.name
            for path in sorted(public.glob("*.js"))
            if path.name != "format.js"
            and forbidden.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])

    def test_segmented_controls_keep_the_touch_target_height(self):
        styles = (server.PUBLIC_DIR / "styles.css").read_text(encoding="utf-8")
        self.assertIn(
            ".segmented-control > * { flex: 1 1 120px; min-height: 44px;", styles
        )
        self.assertNotIn("min-height: 40px; border: 0;", styles)

    def test_error_toast_styles_stay_readable_and_animate_with_the_composer(self):
        styles = (server.PUBLIC_DIR / "styles.css").read_text(encoding="utf-8")
        error_rule = re.search(
            r"^\.error:not\(\.toast\) \{([^}]*)\}", styles, re.MULTILINE
        )
        self.assertIsNotNone(error_rule)
        self.assertNotIn("!important", error_rule.group(1))
        toast_rule = re.search(r"^\.toast \{([^}]*)\}", styles, re.MULTILINE)
        self.assertIsNotNone(toast_rule)
        transition = re.search(r"transition: ([^;]*);", toast_rule.group(1))
        self.assertIsNotNone(transition)
        self.assertEqual(
            transition.group(1),
            "transform .2s ease, opacity .2s ease, "
            "background .2s ease, color .2s ease, box-shadow .2s ease, "
            "bottom .2s ease",
        )
        self.assertIn(".secondary-button.danger-button", styles)

    def test_removed_season_preparation_code_stays_out_of_the_competition_overview(
        self,
    ):
        public = Path(__file__).resolve().parents[1] / "public"
        analysis = (public / "analysis.js").read_text(encoding="utf-8")
        self.assertNotIn('"/api/analysis/season"', analysis)
        self.assertNotIn('"/api/analysis/scenarios"', analysis)
        self.assertNotIn("parseSeasonLoadFactor", analysis)
        plan_views = (public / "plan-views.js").read_text(encoding="utf-8")
        self.assertNotIn("SEASON_PHASE_LABELS", plan_views)

    def test_removed_ux_copy_stays_out(self):
        index = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        notifications = (server.PUBLIC_DIR / "notifications.js").read_text(
            encoding="utf-8"
        )
        coach = (server.PUBLIC_DIR / "coach.js").read_text(encoding="utf-8")
        analysis = (server.PUBLIC_DIR / "analysis.js").read_text(encoding="utf-8")
        self.assertNotIn("Tab „Kalender“", index)
        self.assertNotIn("Tab „Plan“", index)
        self.assertNotIn("-1 = alle verfügbaren Daten", index)
        self.assertNotIn("Aktiviert", notifications)
        self.assertNotIn('analysisValue(percent, "%")', analysis)
        self.assertNotIn(
            'typeof value === "string" ? value : JSON.stringify(value, null, 2)', coach
        )


if __name__ == "__main__":
    unittest.main()
