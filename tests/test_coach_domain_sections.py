"""Coach context domain sections: legacy aliases, source blocks, budgets and labels."""

import unittest
from datetime import date
from unittest.mock import Mock, patch

from backend.canonical.vocabulary import ProviderId
from backend.coach.context import (
    COACH_CONTEXT_SECTION_LIMITS,
    CoachIntervalsContextService,
    CoachPerformanceContextReader,
    coach_context_json_size,
)
from backend.coach.context_selection import (
    CONTEXT_SECTIONS,
    CoachContextSelection,
    canonical_section,
)
from backend.coach.read_tools import CoachReadToolService
from backend.coach.tool_schemas import build_structured_tool_schemas
from backend.providers.source_labels import SourceView, provider_label
from tests import test_coach_structured_context as context_tests

TODAY = date(2026, 9, 23)
SYNCED_AT = "2026-09-22T08:00:00Z"
GARMIN_SYNCED_AT = "2026-09-22T06:30:00Z"


def _label(provider: ProviderId) -> str:
    return provider_label(provider, SourceView.CURRENT_METRIC)


def _garmin_projection() -> dict:
    return {
        "synced_at": GARMIN_SYNCED_AT,
        "start": "2026-09-16",
        "end": "2026-09-22",
        "source_freshness": {"sleep": "fresh"},
        "recovery": {
            "sleep": {"score": 81},
            "hrv": {"last_night_avg": 62},
            "resting_hr": {"value": 44},
            "readiness": {},
            "body_battery": {"value": 70},
        },
        "scope": "Nur der aktuellste Garmin-Recovery-Datensatz.",
        "errors": [],
    }


def _populated_fixture():
    fixture = context_tests.CoachStructuredContextServiceTests()
    fixture.setUp()
    fixture.garmin_projection_service.coach_context.return_value = _garmin_projection()
    return fixture


def _read_service(context):
    return CoachReadToolService(
        *(Mock() for _index in range(8)),
        training_change_limit=366,
        context_service=lambda: context,
    )


def _structured_tools():
    return build_structured_tool_schemas(
        default_profile={},
        checkin_text_limits={},
        checkin_score_fields=(),
        training_change_limit=366,
        library_bulk_max_entries=100,
        training_plan_statuses=(),
    )


class CoachDomainSectionAliasTests(unittest.TestCase):
    def test_legacy_provider_names_resolve_to_one_canonical_section(self):
        for name, canonical in (
            ("intervals", "activities"),
            ("garmin", "recovery"),
            ("activities", "activities"),
            ("recovery", "recovery"),
            ("current_performance", "current_performance"),
            ("unknown_section", "unknown_section"),
        ):
            with self.subTest(name=name):
                self.assertEqual(canonical_section(name), canonical)

    def test_selection_resolves_aliases_once(self):
        selection = CoachContextSelection(
            "requested_details",
            frozenset({"intervals", "garmin", "recovery", "activities"}),
        )
        self.assertEqual(selection.sections, frozenset({"activities", "recovery"}))

    def test_read_tool_accepts_legacy_names_and_reports_canonical_sections(self):
        context = Mock()
        context.build.return_value = {"activities": {}, "recovery": {}}
        result = _read_service(context).execute(
            "read_coach_context", {"sections": ["intervals", "garmin"]}
        )
        self.assertEqual(
            context.build.call_args.kwargs["selection"].sections,
            frozenset({"activities", "recovery"}),
        )
        self.assertEqual(
            result["projection"]["requested_sections"], ["activities", "recovery"]
        )

    def test_tool_enum_advertises_only_the_new_names(self):
        tools = _structured_tools()
        read_tool = next(tool for tool in tools if tool["name"] == "read_coach_context")
        enum = read_tool["parameters"]["properties"]["sections"]["items"]["enum"]
        self.assertEqual(set(enum), CONTEXT_SECTIONS)
        self.assertNotIn("intervals", enum)
        self.assertNotIn("garmin", enum)


class CoachDomainSectionSourceTests(unittest.TestCase):
    def test_activities_source_block_comes_first_and_uses_provider_label(self):
        projection = CoachIntervalsContextService().project(
            {"synced_at": SYNCED_AT, "recent_activities": []}, [], TODAY
        )
        self.assertEqual(next(iter(projection)), "source")
        self.assertEqual(
            projection["source"],
            {
                "provider": ProviderId.INTERVALS.value,
                "label": _label(ProviderId.INTERVALS),
                "synced_at": SYNCED_AT,
                "applies_to": [
                    "recent_activities_by_sport",
                    "activity_rollups_by_sport",
                ],
            },
        )
        self.assertEqual(projection["source"]["label"], "Intervals.icu")
        self.assertEqual(projection["synced_at"], SYNCED_AT)

    def test_recovery_source_block_wraps_unchanged_garmin_projection(self):
        projection_service = Mock()
        projection_service.coach_context.return_value = _garmin_projection()
        reader = CoachPerformanceContextReader(
            Mock(), Mock(), projection_service, lambda: TODAY
        )
        result = reader.recovery({"synced_at": SYNCED_AT})
        projection_service.coach_context.assert_called_once_with(
            include_performance=False
        )
        self.assertEqual(next(iter(result)), "source")
        self.assertEqual(
            result["source"],
            {
                "provider": ProviderId.GARMIN.value,
                "label": _label(ProviderId.GARMIN),
                "synced_at": GARMIN_SYNCED_AT,
            },
        )
        self.assertEqual(
            {key: value for key, value in result.items() if key != "source"},
            _garmin_projection(),
        )
        self.assertEqual(result["source"]["label"], "Garmin Connect")

    def test_budgets_follow_domain_sections_and_total_stays_within_72k(self):
        self.assertEqual(COACH_CONTEXT_SECTION_LIMITS["activities"], 32_000)
        self.assertEqual(COACH_CONTEXT_SECTION_LIMITS["recovery"], 16_000)
        self.assertEqual(COACH_CONTEXT_SECTION_LIMITS["current_performance"], 24_000)
        self.assertNotIn("intervals", COACH_CONTEXT_SECTION_LIMITS)
        self.assertNotIn("garmin", COACH_CONTEXT_SECTION_LIMITS)
        self.assertLessEqual(
            sum(
                COACH_CONTEXT_SECTION_LIMITS[name]
                for name in ("activities", "recovery", "current_performance")
            ),
            72_000,
        )

    def test_source_policy_texts_are_built_from_labels(self):
        fixture = _populated_fixture()
        policy = fixture.service.build()["source_policy"]
        self.assertIn(_label(ProviderId.INTERVALS), policy["activities"])
        self.assertIn(_label(ProviderId.GARMIN), policy["recovery"])
        self.assertIn(_label(ProviderId.INTERVALS), policy["current_performance"])
        self.assertEqual(
            policy["durable_profile"],
            "Vom Athleten bestätigte Werte, lokal in SQLite gespeichert",
        )

    def test_source_policy_follows_the_label_table(self):
        fixture = _populated_fixture()

        def label_for(provider):
            if provider == ProviderId.GARMIN:
                return "Test Source"
            return _label(provider)

        with patch("backend.coach.context._source_label", side_effect=label_for):
            policy = fixture.service.build()["source_policy"]
        self.assertIn("Test Source", policy["recovery"])
        self.assertNotIn(_label(ProviderId.GARMIN), policy["recovery"])


class CoachDomainSectionFullContextTests(unittest.TestCase):
    def test_full_context_keeps_values_and_stays_within_budget(self):
        fixture = _populated_fixture()
        result = fixture.service.build()

        self.assertNotIn("intervals", result)
        self.assertNotIn("garmin", result)
        self.assertIn("current_performance", result)

        activities = result["activities"]
        self.assertEqual(
            activities["source"],
            {
                "provider": ProviderId.INTERVALS.value,
                "label": _label(ProviderId.INTERVALS),
                "synced_at": fixture.snapshot["synced_at"],
                "applies_to": [
                    "recent_activities_by_sport",
                    "activity_rollups_by_sport",
                ],
            },
        )
        expected_activities = CoachIntervalsContextService().project(
            fixture.snapshot, [], TODAY
        )
        self.assertEqual(
            _without(activities, "source", "planned_workouts"),
            _without(expected_activities, "source", "planned_workouts"),
        )

        self.assertEqual(result["recovery"]["source"]["synced_at"], GARMIN_SYNCED_AT)
        self.assertEqual(
            _without(result["recovery"], "source"),
            _garmin_projection(),
        )

        sizes = {
            name: coach_context_json_size(result[name])
            for name in ("activities", "recovery", "current_performance")
        }
        for name, size in sizes.items():
            self.assertLessEqual(size, COACH_CONTEXT_SECTION_LIMITS[name])
        self.assertLessEqual(sum(sizes.values()), 72_000)


def _without(mapping, *keys):
    return {key: value for key, value in mapping.items() if key not in keys}


if __name__ == "__main__":
    unittest.main()
