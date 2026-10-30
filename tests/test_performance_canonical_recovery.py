"""Canonical recovery inputs: the only source of the recovery reads (#1411).

The inputs carry every recovery kind of all providers, read once per unit of work.
A populated temporary database is the end-to-end check: the recovery context and
the personal baselines served from the tables equal those built from the same
fixtures mapped in memory, and need no raw Garmin view. Every provider is mocked
by fixtures and all storage is temporary.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

from canonical_consumer_cases import TODAY
from canonical_read_support import CanonicalReadFixture, make_selector, populate
from canonical_recovery_support import (
    RecordingReader,
    mapped_recovery_inputs,
    recovery_inputs,
    recovery_observation,
)

from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.canonical_recovery import (
    RECOVERY_KINDS,
    read_recovery_inputs,
)
from backend.performance.context import current_performance_context
from backend.performance.personal_recovery import personal_recovery
from backend.providers.source_labels import SourceView, provider_label

DAY = date(2026, 9, 20)


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


class ReadRecoveryInputsTests(unittest.TestCase):
    def test_each_kind_is_read_once_from_the_history_start_without_an_end(
        self,
    ) -> None:
        reader = RecordingReader({})

        inputs = read_recovery_inputs(reader, None, as_of=DAY, latest_wellness_day=DAY)

        start = DAY - timedelta(days=83)
        self.assertEqual(reader.calls, [(kind, start, None) for kind in RECOVERY_KINDS])
        self.assertEqual(inputs.latest_wellness_day, DAY)
        self.assertEqual(set(inputs.observations), set(RECOVERY_KINDS))

    def test_kinds_include_both_hrv_methods_and_the_weekly_average(self) -> None:
        self.assertTrue(
            {
                MetricKind.HRV_RMSSD,
                MetricKind.HRV_SDNN,
                MetricKind.HRV_WEEKLY_AVERAGE,
            }
            <= set(RECOVERY_KINDS)
        )


class RecoveryInputsTests(unittest.TestCase):
    def test_current_pins_intervals_values_to_the_latest_wellness_day(self) -> None:
        # Wellness observations carry their row day as the record id.
        older = recovery_observation(
            MetricKind.RESTING_HR,
            50,
            "2026-09-19",
            ProviderId.INTERVALS,
            record_id="2026-09-19",
        )
        pinned = recovery_inputs([older], latest_wellness_day=DAY)
        unpinned = recovery_inputs([older])

        self.assertIsNone(pinned.current(MetricKind.RESTING_HR))
        self.assertIs(unpinned.current(MetricKind.RESTING_HR), older)

    def test_daily_keeps_the_first_record_of_each_day_and_provider(self) -> None:
        inputs = recovery_inputs(
            [
                recovery_observation(MetricKind.RESTING_HR, 50, "2026-09-20"),
                recovery_observation(
                    MetricKind.RESTING_HR, 51, "2026-09-20", record_id="second"
                ),
                recovery_observation(
                    MetricKind.RESTING_HR, 60, "2026-09-20", ProviderId.INTERVALS
                ),
            ]
        )

        self.assertEqual(
            inputs.daily(MetricKind.RESTING_HR, ProviderId.GARMIN), {DAY: 50.0}
        )
        self.assertEqual(
            inputs.daily(MetricKind.RESTING_HR, ProviderId.INTERVALS), {DAY: 60.0}
        )

    def test_bounded_daily_skips_values_outside_the_current_rule(self) -> None:
        inputs = recovery_inputs(
            [recovery_observation(MetricKind.RESTING_HR, 25, "2026-09-20")]
        )

        self.assertEqual(
            inputs.daily(MetricKind.RESTING_HR, ProviderId.GARMIN), {DAY: 25.0}
        )
        self.assertEqual(
            inputs.daily(MetricKind.RESTING_HR, ProviderId.GARMIN, bounded=True), {}
        )

    def test_unread_kind_has_no_observations(self) -> None:
        self.assertEqual(recovery_inputs().of(MetricKind.CTL), ())


class SourceLabelTests(unittest.TestCase):
    def test_personal_recovery_labels_are_the_legacy_strings(self) -> None:
        self.assertEqual(
            provider_label(ProviderId.INTERVALS, SourceView.DAILY_HEALTH),
            "Intervals.icu",
        )
        self.assertEqual(
            provider_label(ProviderId.GARMIN, SourceView.DAILY_HEALTH),
            "Garmin Connect",
        )


class PopulatedRecoveryTests(CanonicalReadFixture):
    def _inputs(self) -> Any:
        populate(self)
        selector = make_selector(self)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        with self.manager.reader() as db:
            inputs = read_performance_inputs(selector, db, as_of=TODAY)
        assert inputs is not None and inputs.recovery is not None
        return inputs

    def test_tables_serve_the_mapped_fixture_values_without_a_garmin_view(
        self,
    ) -> None:
        inputs = self._inputs()
        mapped = mapped_recovery_inputs(
            self.garmin,
            self.intervals["raw_provider_data"]["wellness"],
            latest_wellness_day=inputs.recovery.latest_wellness_day,
        )

        served = current_performance_context(
            self.intervals, {}, {}, TODAY, canonical=inputs
        )
        expected = personal_recovery([], {}, {}, TODAY, canonical=mapped)

        recovery = served["recovery"]
        self.assertIsNotNone(recovery["sleep_hours"])
        self.assertIsNotNone(recovery["resting_hr_bpm"])
        self.assertIsNotNone(recovery["hrv_ms"])
        self.assertEqual(
            _dump(served["personal_recovery"]["baselines"]),
            _dump(expected["baselines"]),
        )

    def test_without_canonical_inputs_no_recovery_value_is_shown(self) -> None:
        result = current_performance_context(self.intervals, self.garmin, {}, TODAY)

        recovery = result["recovery"]
        for key in (
            "resting_hr_bpm",
            "hrv_ms",
            "sleep_score",
            "readiness",
            "sleep_hours",
        ):
            self.assertIsNone(recovery[key], key)
        self.assertEqual(result["personal_recovery"]["baselines"], [])

    def test_selector_resolves_its_source_once_for_the_recovery_read(self) -> None:
        populate(self)
        selector = make_selector(self)
        with (
            patch.object(selector, "reader_for", wraps=selector.reader_for) as resolved,
            self.manager.reader() as db,
        ):
            inputs = read_performance_inputs(selector, db, as_of=TODAY)
        resolved.assert_called_once()
        self.assertIsNotNone(inputs)


if __name__ == "__main__":
    unittest.main()
