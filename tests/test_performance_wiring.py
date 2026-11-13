"""The training report builder reads its owners from the application context (#2100)."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.performance import wiring as performance_wiring


class PerformanceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = Mock()
        self.today = self.ctx.clock.now.return_value.date.return_value
        self.athlete = self.ctx.athlete
        # The composition root passes the public-state projections and the
        # planning functions; this domain imports neither layer.
        self.public = Mock()
        self.inputs = {
            "session_activities": Mock(name="session_activities"),
            "plan_state": self.public.plan_state_service,
            "performance_state": self.public.performance_state_service,
            "canonical_performance_source": self.public.canonical_performance_source,
            "season_source": self.public.season_source,
            "block_review": Mock(name="block_review"),
            "last_completed_test": Mock(name="last_completed_test"),
            "season_preparation": Mock(name="season_preparation"),
        }
        self.patches = {
            name: patch.object(performance_wiring, name)
            for name in (
                "SessionCurveReader",
                "TrainingRecordsService",
                "TrainingProfileSelectionService",
                "TrainingReportReadService",
                "TrainingDerivedReadService",
                "TrainingSeasonReadService",
                "TrainingReportServices",
            )
        }
        self.mocks = {name: p.start() for name, p in self.patches.items()}
        self.addCleanup(patch.stopall)

    def build(self) -> performance_wiring.PerformanceServices:
        return performance_wiring.build_performance(self.ctx, **self.inputs)

    def test_building_creates_the_one_curve_reader_and_resolves_nothing_else(
        self,
    ) -> None:
        self.build()

        self.mocks["SessionCurveReader"].assert_called_once_with(
            self.inputs["session_activities"]
        )
        self.ctx.database.assert_not_called()
        self.public.canonical_performance_source.assert_not_called()
        self.mocks["TrainingReportServices"].assert_not_called()

    def test_every_call_builds_fresh_services_over_the_one_curve_reader(self) -> None:
        services = self.build()

        services.training_reports()
        services.training_reports()

        self.assertEqual(2, self.public.canonical_performance_source.call_count)
        self.assertEqual(2, self.public.season_source.call_count)
        self.assertEqual(2, self.ctx.database.call_count)
        self.mocks["SessionCurveReader"].assert_called_once()
        curves = self.mocks["SessionCurveReader"].return_value
        for call in self.mocks["TrainingProfileSelectionService"].call_args_list:
            self.assertIs(curves, call.kwargs["curves"])
            self.assertIs(
                self.public.canonical_performance_source.return_value,
                call.kwargs["canonical"],
            )

    def test_the_session_curve_records_are_the_shared_read_over_the_one_reader(
        self,
    ) -> None:
        services = self.build()

        records = services.curve_records(60)

        selection = self.mocks["TrainingProfileSelectionService"]
        selection.return_value.curve_records.assert_called_once_with(60, shared=True)
        self.assertIs(selection.return_value.curve_records.return_value, records)
        self.assertIs(
            self.mocks["SessionCurveReader"].return_value,
            selection.call_args.kwargs["curves"],
        )
        self.mocks["TrainingReportServices"].assert_not_called()

    def test_the_records_read_the_equipment_of_the_athlete(self) -> None:
        self.build().training_reports()

        kwargs = self.mocks["TrainingRecordsService"].call_args.kwargs
        self.assertIs(self.ctx.database.return_value, kwargs["database_manager"])
        self.athlete.equipment.return_value.read.return_value = {"items": ["x"]}
        self.assertEqual({"items": ["x"]}, kwargs["read_equipment"]())
        self.athlete.equipment.return_value.read.return_value = {"items": ["gear"]}
        self.assertEqual(
            {"record_type": "equipment", "record": "gear"},
            kwargs["read_record"]("equipment", "id-1"),
        )
        self.athlete.equipment.return_value.read.assert_called_with("id-1")
        self.assertEqual({}, kwargs["read_record"]("other", "id-2"))

    def test_the_report_reads_plan_checkins_feedback_and_profile_live(self) -> None:
        services = self.build()
        services.training_reports()
        kwargs = self.mocks["TrainingReportReadService"].call_args.kwargs

        kwargs["read_plan"]()
        self.public.plan_state_service.return_value.read.assert_called_once_with(
            local_only=True
        )
        kwargs["read_checkins"]()
        self.athlete.checkin.return_value.list.assert_called_once_with(365)
        feedback = self.athlete.activity_feedback.return_value.for_activity_ids
        kwargs["read_feedback"](["a"])
        feedback.assert_called_with(["a"])
        kwargs["session_feedback"](["b"])
        feedback.assert_called_with(["b"], sessions_only=True)
        self.assertIs(self.today, kwargs["today"]())
        self.assertIs(self.ctx.clock.now, kwargs["now"])
        self.assertIs(
            self.mocks["TrainingProfileSelectionService"].return_value.curve_records,
            kwargs["curve_records"],
        )
        source = kwargs["block_review"]
        self.assertIs(self.inputs["block_review"], source.review)
        self.assertIs(self.inputs["last_completed_test"], source.last_test)
        profile = self.athlete.profile.return_value
        profile.get.return_value = {"training_model": "polarized"}
        self.assertEqual("polarized", kwargs["training_model"]())
        profile.get.return_value = {}
        self.assertEqual("", kwargs["training_model"]())

    def test_the_derived_reads_take_the_public_performance_state(self) -> None:
        self.build().training_reports()
        kwargs = self.mocks["TrainingDerivedReadService"].call_args.kwargs
        state = self.public.performance_state_service.return_value.performance_state
        state.return_value = {"performance": {"personal_recovery": {"score": 7}}}

        self.assertEqual({"score": 7}, kwargs["read_recovery"]())
        self.assertEqual(
            {"personal_recovery": {"score": 7}}, kwargs["read_performance"]()
        )
        state.return_value = {"performance": {}}
        self.assertEqual({}, kwargs["read_recovery"]())
        kwargs["read_checkins"]()
        self.athlete.checkin.return_value.list.assert_called_with(365)
        self.assertIs(self.today, kwargs["today"]())

    def test_the_season_reads_competitions_and_planning_sources(self) -> None:
        self.build().training_reports()
        kwargs = self.mocks["TrainingSeasonReadService"].call_args.kwargs

        kwargs["read_competitions"]()
        self.ctx.planning.competition.return_value.list.assert_called_once_with(100)
        self.assertIs(
            self.mocks["TrainingRecordsService"].return_value.observations,
            kwargs["read_observations"],
        )
        self.assertIs(
            self.inputs["season_preparation"],
            kwargs["season_preparation"],
        )
        self.assertIs(self.public.season_source.return_value, kwargs["season_source"])

    def test_the_timezone_defaults_to_utc(self) -> None:
        self.build().training_reports()
        timezone = self.mocks["TrainingReportServices"].call_args.kwargs["timezone"]
        profile = self.athlete.profile.return_value

        profile.get.return_value = {"timezone": "Europe/Berlin"}
        self.assertEqual("Europe/Berlin", timezone())
        profile.get.return_value = {}
        self.assertEqual("UTC", timezone())


if __name__ == "__main__":
    unittest.main()
