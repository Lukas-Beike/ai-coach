"""Canonical power curve records (schema v17): point and fetch validation.

Synthetic values only.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any

from backend.canonical.domain_records import PowerCurveFetch, PowerCurvePoint
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, SourceKind

POWER_CURVE_RECORD_ID = "power_curve"
POWER_CURVE_LABEL = "Synthetic power curve"
TODAY = date(2026, 10, 20)
FETCHED = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)


def provenance(source_record_id: str | None = POWER_CURVE_RECORD_ID) -> Provenance:
    return Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=FETCHED,
        label=POWER_CURVE_LABEL,
    )


def curve_point(**overrides: Any) -> PowerCurvePoint:
    values: dict[str, Any] = {
        "duration_s": 60,
        "watts": 450.0,
        "observed_on": date(2026, 10, 1),
        "provider_activity_id": "i1",
        "provenance": provenance(),
    }
    values.update(overrides)
    return PowerCurvePoint(**values)


def curve_fetch(**overrides: Any) -> PowerCurveFetch:
    values: dict[str, Any] = {
        "fetch_status": "ok",
        "window_start": date(2026, 7, 1),
        "window_end": TODAY,
        "provenance": provenance(),
    }
    values.update(overrides)
    return PowerCurveFetch(**values)


class PowerCurveRecordTests(unittest.TestCase):
    def test_invalid_points_are_rejected(self) -> None:
        for overrides, error in (
            ({"duration_s": 0}, ValueError),
            ({"duration_s": True}, TypeError),
            ({"watts": -1}, ValueError),
            ({"watts": 6000}, ValueError),
            ({"provenance": provenance(None)}, ValueError),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(error):
                curve_point(**overrides)

    def test_invalid_fetches_are_rejected(self) -> None:
        for overrides, error in (
            ({"fetch_status": "Failed"}, ValueError),
            ({"fetch_status": None}, TypeError),
            ({"window_end": None}, ValueError),
            ({"window_end": date(2026, 6, 1)}, ValueError),
            ({"provenance": provenance(None)}, ValueError),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(error):
                curve_fetch(**overrides)
        self.assertIsNone(curve_fetch(window_start=None, window_end=None).window_end)


if __name__ == "__main__":
    unittest.main()
