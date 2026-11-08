"""Library workout to Wahoo plan JSON mapping, including explicit rejections."""

from __future__ import annotations

import unittest
from contextlib import nullcontext
from datetime import UTC, date, datetime
from unittest.mock import Mock

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.errors import AppError
from backend.providers.wahoo_plan_mapping import (
    WahooPlanMappingError,
    WahooPlanReferences,
    wahoo_plan,
)
from backend.sync.wahoo_sync_assembly import WahooSyncAssembly, WahooSyncInputs
from backend.sync.wahoo_workout_export import (
    WahooWorkoutExport,
    plan_references,
    wahoo_external_id,
)

RIDE_TEXT = "Warmup\n- 10m 150W\n\nMain Set 2x\n- 5m 250-280W\n- 2m 120W"


def step(**values):
    return {
        "kind": "power",
        "target": "200W",
        "ramp": False,
        "duration": 300.0,
        **values,
    }


def plan(steps, **values):
    return wahoo_plan(
        name="Sweet spot",
        description="text",
        sport=values.pop("sport", Sport.RIDE),
        environment=values.pop("environment", Environment.INDOOR),
        steps=steps,
        **values,
    )


class MappingTests(unittest.TestCase):
    def test_maps_absolute_power_steps_to_time_intervals(self) -> None:
        document = plan([step(target="250-280W", duration=600.0)])

        self.assertEqual("1.0.0", document["header"]["version"])
        self.assertEqual(0, document["header"]["workout_type_family"])
        self.assertEqual(0, document["header"]["workout_type_location"])
        self.assertEqual("Sweet spot", document["header"]["name"])
        interval = document["intervals"][0]
        self.assertEqual("time", interval["exit_trigger_type"])
        self.assertEqual(600, interval["exit_trigger_value"])
        self.assertEqual(
            [{"type": "watts", "low": 250, "high": 280}], interval["targets"]
        )

    def test_runs_and_outdoor_environments_use_their_wahoo_codes(self) -> None:
        document = plan(
            [step(kind="hr", target="140-150BPM")],
            sport=Sport.RUN,
            environment=Environment.OUTDOOR,
        )

        self.assertEqual(1, document["header"]["workout_type_family"])
        self.assertEqual(1, document["header"]["workout_type_location"])
        self.assertEqual(
            [{"type": "hr", "low": 140, "high": 150}],
            document["intervals"][0]["targets"],
        )

    def test_references_are_written_to_the_header_only_when_set(self) -> None:
        document = plan([step()], references=WahooPlanReferences(ftp=250))

        self.assertEqual(250, document["header"]["ftp"])
        self.assertNotIn("max_hr", document["header"])

    def test_unsupported_sport_is_rejected_with_a_clear_error(self) -> None:
        with self.assertRaises(WahooPlanMappingError) as caught:
            plan([step()], sport=Sport.SWIM)

        self.assertEqual(422, caught.exception.status)
        self.assertIn("Rad- und Laufeinheiten", caught.exception.message)

    def test_workout_without_steps_is_rejected(self) -> None:
        with self.assertRaises(WahooPlanMappingError):
            plan([])

    def test_ramps_are_rejected_with_the_step_number(self) -> None:
        with self.assertRaises(WahooPlanMappingError) as caught:
            plan([step(), step(ramp=True, target="100-200W")])

        self.assertIn("Schritt 2", caught.exception.message)
        self.assertIn("Rampen", caught.exception.message)

    def test_zone_targets_are_rejected_instead_of_guessed(self) -> None:
        with self.assertRaises(WahooPlanMappingError) as caught:
            plan([step(target="Z2")])

        self.assertIn("Zonenziele", caught.exception.message)

    def test_relative_power_without_an_ftp_reference_is_rejected(self) -> None:
        with self.assertRaises(WahooPlanMappingError):
            plan([step(target="75%")])

    def test_relative_power_with_an_ftp_reference_maps(self) -> None:
        document = plan([step(target="75%")], references=WahooPlanReferences(ftp=200))

        self.assertEqual(1, len(document["intervals"][0]["targets"]))

    def test_every_error_is_an_app_error_with_a_stable_reason(self) -> None:
        with self.assertRaises(AppError) as caught:
            plan([step(target="Z3")])

        self.assertEqual("wahoo_plan_unsupported", caught.exception.reason)


class ExportSerializationTests(unittest.TestCase):
    def export(self) -> WahooWorkoutExport:
        return WahooWorkoutExport(
            Mock(), now=lambda: datetime(2026, 10, 13, tzinfo=UTC)
        )

    def test_serializes_a_library_workout_with_a_stable_external_id(self) -> None:
        envelope = self.export().serialize_library(
            {
                "local_id": "w1",
                "type": "Ride",
                "name": "Tempo",
                "description": RIDE_TEXT,
            }
        )

        self.assertEqual(wahoo_external_id("w1"), envelope["external_id"])
        self.assertEqual("coach-library-w1.json", envelope["filename"])
        self.assertEqual("Tempo", envelope["plan"]["header"]["name"])
        self.assertEqual(5, len(envelope["plan"]["intervals"]))

    def test_unparseable_text_becomes_a_mapping_error(self) -> None:
        with self.assertRaises(WahooPlanMappingError):
            self.export().serialize_library(
                {"local_id": "w1", "type": "Ride", "description": "no steps here"}
            )

    def test_missing_local_id_is_rejected(self) -> None:
        with self.assertRaises(WahooPlanMappingError):
            self.export().serialize_library({"type": "Ride", "description": RIDE_TEXT})

    def test_swim_workouts_are_rejected_per_workout(self) -> None:
        with self.assertRaises(WahooPlanMappingError):
            self.export().serialize_library(
                {"local_id": "w1", "type": "Swim", "description": "- 10m 150W"}
            )

    def test_planning_a_calendar_date_is_not_supported(self) -> None:
        with self.assertRaises(AppError) as caught:
            self.export().library_plan("1", {}, "2026-10-14")

        self.assertEqual("unsupported_export", caught.exception.reason)


def threshold(kind: MetricKind, sport: Sport, value: float) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=datetime(2026, 10, 1, tzinfo=UTC).date(),
        observed_at=None,
        provenance=Provenance(
            provider=ProviderId.GARMIN,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=None,
            label=None,
        ),
        sport=sport,
    )


THRESHOLDS = {
    (kind, sport): threshold(kind, sport, value)
    for kind, sport, value in (
        (MetricKind.FTP, Sport.RIDE, 251.6),
        (MetricKind.THRESHOLD_HR, Sport.RIDE, 165.0),
        (MetricKind.MAX_HR, Sport.RIDE, 186.0),
        (MetricKind.FTP, Sport.RUN, 300.0),
        (MetricKind.THRESHOLD_HR, Sport.RUN, 170.0),
        (MetricKind.MAX_HR, Sport.RUN, 190.0),
        (MetricKind.THRESHOLD_PACE, Sport.RUN, 4.0),
    )
}


class ExportReferenceTests(unittest.TestCase):
    """Relative steps resolve against the resolved export thresholds (#1686)."""

    def test_references_are_read_for_the_plan_sport(self) -> None:
        self.assertEqual(
            WahooPlanReferences(ftp=252, max_hr=186, threshold_hr=165),
            plan_references(THRESHOLDS, Sport.RIDE),
        )
        self.assertEqual(
            WahooPlanReferences(
                ftp=300, max_hr=190, threshold_hr=170, threshold_speed=4.0
            ),
            plan_references(THRESHOLDS, Sport.RUN),
        )
        self.assertEqual(WahooPlanReferences(), plan_references({}, Sport.RIDE))

    def test_relative_steps_export_with_header_references(self) -> None:
        sports: list[Sport] = []

        def references(sport: Sport) -> WahooPlanReferences:
            sports.append(sport)
            return plan_references(THRESHOLDS, sport)

        export = WahooWorkoutExport(
            Mock(),
            now=lambda: datetime(2026, 10, 13, tzinfo=UTC),
            references=references,
        )
        envelope = export.serialize_library(
            {
                "local_id": "w1",
                "type": "Ride",
                "description": "- 10m 88-94%\n- 5m 80% LTHR",
            }
        )

        self.assertEqual([Sport.RIDE], sports)
        header = envelope["plan"]["header"]
        self.assertEqual(252, header["ftp"])
        self.assertEqual(165, header["threshold_hr"])

    def test_missing_reference_is_still_rejected_by_name(self) -> None:
        export = WahooWorkoutExport(
            Mock(),
            now=lambda: datetime(2026, 10, 13, tzinfo=UTC),
            references=lambda sport: plan_references({}, sport),
        )

        with self.assertRaises(WahooPlanMappingError) as caught:
            export.serialize_library(
                {"local_id": "w1", "type": "Ride", "description": "- 10m 88%"}
            )

        self.assertIn("FTP", str(caught.exception))


class AssemblyReferenceTests(unittest.TestCase):
    def test_assembled_export_reads_thresholds_once_per_run_inside_a_reader(
        self,
    ) -> None:
        database = object()
        seen: list[object] = []
        manager = Mock()
        manager.reader.return_value = nullcontext(database)

        def thresholds(db: object) -> dict[tuple[MetricKind, Sport], Observation]:
            seen.append(db)
            return THRESHOLDS

        assembly = WahooSyncAssembly(
            WahooSyncInputs(
                config=Mock(),
                connection=Mock(),
                json_request=Mock(),
                database_manager=lambda: manager,
                database_lock=Mock(),
                key_values=Mock(),
                daily_markers=Mock(),
                observer=Mock(),
                registry=Mock(),
                zone_provider=Mock(),
                now=lambda: datetime(2026, 10, 13, tzinfo=UTC),
                logger=Mock(),
                redactor=Mock(),
                resync_gate=Mock(),
                export_thresholds=thresholds,
                history_earliest_date=date(2020, 1, 1),
            )
        )

        export = assembly.workout_export()
        envelope = export.serialize_library(
            {"local_id": "w1", "type": "Ride", "description": "- 10m 88%"}
        )
        export.serialize_library(
            {"local_id": "w2", "type": "Ride", "description": "- 5m 90%"}
        )

        self.assertEqual([database], seen)
        self.assertEqual(252, envelope["plan"]["header"]["ftp"])


if __name__ == "__main__":
    unittest.main()
