"""Canonical resting HR for the personal recovery baselines.

The personal recovery baselines keep one distribution per provider, so the daily
resting HR is selected per provider with ``select_daily`` applied to that
provider's observations alone. Cross-provider precedence is not used here,
because the legacy baselines keep Garmin and Intervals.icu apart.

The legacy 84-day history starts 83 days before ``today``. The reader window starts
83 days before the snapshot's latest wellness day and has no upper bound, because
Garmin records may be newer than the latest wellness row. This assumes ``today``
is not earlier than that wellness day, which the caller does not enforce. If the
assumption fails, legacy days before the canonical window keep their legacy values.
That is a coverage gap, never a wrong value, because a canonical value replaces a
legacy one only when the number matches. A day without a canonical observation
also keeps the legacy value.

Only resting HR is read here. Sleep, HRV and regularity stay on the legacy path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.source_policy import select_daily
from backend.runtime.ports import ObservationReader

PERSONAL_RECOVERY_PROVIDERS: Final = (ProviderId.INTERVALS, ProviderId.GARMIN)


@dataclass(frozen=True, slots=True)
class CanonicalPersonalRecoveryInputs:
    """Daily resting HR observations keyed by provider, then by ISO day."""

    resting_hr: Mapping[ProviderId, Mapping[str, Observation]]


def read_personal_recovery_inputs(
    reader: ObservationReader, db: Any, *, start: date
) -> CanonicalPersonalRecoveryInputs:
    """Read resting HR from ``start`` on and select one observation per provider and day.

    ``reader`` must already be the source chosen for the unit of work.
    """
    observations = reader.observations(db, MetricKind.RESTING_HR, start=start)
    return CanonicalPersonalRecoveryInputs(
        resting_hr={
            provider: {
                day.isoformat(): observation
                for day, observation in select_daily(
                    (
                        observation
                        for observation in observations
                        if observation.provenance.provider is provider
                    ),
                    MetricKind.RESTING_HR,
                ).items()
            }
            for provider in PERSONAL_RECOVERY_PROVIDERS
        }
    )
