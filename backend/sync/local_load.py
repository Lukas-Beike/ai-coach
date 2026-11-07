"""Store and serve the local TSS-scale session load (card M6, #1725).

``LocalLoadStage`` is a follow-up stage of the canonical backfill worker. Each
pass reconciles every live session in one transaction: it computes the local
load (``backend.performance.local_tss``) with the thresholds in effect on the
session day, upserts one derived ``SESSION_LOAD`` observation per session (and
one ``INTENSITY_FACTOR`` for the power branch), owned by the canonical session,
and retires the rows of sessions that no longer have a value. A row whose
fingerprint is unchanged stays as it is, so a pass without changes writes
nothing. The pass also keeps content-free counts for diagnostics.

``with_local_loads`` sets the stored values on the summaries a reader serves:
``training_load`` and ``intensity`` come only from the local method. The
summary builder keeps provider values under ``provider_training_load``,
``provider_load_model`` and ``provider_intensity`` for cross-checking.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, tzinfo
from typing import Any, Final

from backend.activities.activity_summary import ActivitySummary, activity_summaries
from backend.canonical.activity_summary import summary_local_date
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.db import canonical_store
from backend.db.repositories import KeyValueRepository
from backend.performance.local_tss import (
    METHOD_ID,
    METHOD_VERSION,
    THRESHOLD_KINDS,
    DatedThresholds,
    LocalLoad,
    rated_sessions,
    session_loads,
)
from backend.performance.session_rpe_load import FeedbackLookup, feedback_by_session
from backend.performance.source_policy import NO_PREFERENCES, SourcePreferences
from backend.sync.canonical_backfill import BatchReport
from backend.sync.canonical_table_reader import CanonicalTableReader

# The application logger: only it has handlers (see observability.configure_logging).
_LOGGER = logging.getLogger("intervals_coach")
STAGE: Final = "local_load"
STATE_KEY: Final = "local_load_state"
DERIVED_LABEL: Final = "derived"

type Preferences = Callable[[Any], SourcePreferences]


def _summaries(
    reader: CanonicalTableReader, db: Any, zone: tzinfo | None
) -> tuple[ActivitySummary, ...]:
    """Provider summaries of every live session, before any local load is set."""
    return activity_summaries(reader.activity_sessions(db), zone or UTC)


def _recorded_by(summary: Mapping[str, Any]) -> RecordingOrigin:
    try:
        return RecordingOrigin(str(summary.get("recorded_by")))
    except ValueError:
        return RecordingOrigin.UNKNOWN


def _observation(
    summary: Mapping[str, Any],
    kind: MetricKind,
    value: float,
    load: LocalLoad,
) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(round(value, 4), kind.unit),
        observed_on=date.fromisoformat(summary_local_date(summary)),
        observed_at=datetime.fromisoformat(str(summary["started_at"])),
        provenance=Provenance(
            provider=None,
            source_kind=SourceKind.DERIVED,
            source_record_id=str(summary["id"]),
            recorded_by=_recorded_by(summary),
            retrieved_at=None,
            label=DERIVED_LABEL,
        ),
        sport=Sport(str(summary["sport"])),
        method=METHOD_ID,
        method_version=METHOD_VERSION,
        input_fingerprint=load.fingerprint,
    )


def _observations(summary: Mapping[str, Any], load: LocalLoad) -> list[Observation]:
    result = [_observation(summary, MetricKind.SESSION_LOAD, load.load, load)]
    if load.intensity_pct is not None:
        result.append(
            _observation(summary, MetricKind.INTENSITY_FACTOR, load.intensity_pct, load)
        )
    return result


def reconcile_local_loads(
    db: Any,
    summaries: Sequence[Mapping[str, Any]],
    thresholds: DatedThresholds,
    *,
    now: str,
    feedback: Mapping[str, Mapping[str, Any]] | None = None,
    sex: str | None = None,
) -> dict[str, Any]:
    """Write every session's local load and retire stale rows; return counts.

    ``feedback`` is each session's effective local feedback by stored key, which
    the session-RPE branch of strength sessions and its calibration read;
    ``sex`` is the profile sex the heart-rate branch reads.
    """
    loads = session_loads(summaries, thresholds, feedback, sex=sex)
    by_id = {str(summary.get("id")): summary for summary in summaries}
    keep: set[str] = set()
    written = 0
    branches: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    by_sport: dict[str, Counter[str]] = {}
    after_session = 0
    for session_id, load in loads.items():
        sport = by_sport.setdefault(str(by_id[session_id].get("sport")), Counter())
        observations: list[Observation] = []
        if isinstance(load, LocalLoad):
            try:
                observations = _observations(by_id[session_id], load)
            except TypeError, ValueError:
                # Outside the canonical bounds (e.g. an unstopped recording):
                # this session gets no value, the others still do.
                load = "invalid_value"
        if not isinstance(load, LocalLoad):
            missing[load] += 1
            sport["missing"] += 1
            continue
        branches[load.branch] += 1
        sport[load.branch] += 1
        if load.details.get("threshold_after_session"):
            after_session += 1
            sport["threshold_after_session"] += 1
        for observation in observations:
            keep.add(canonical_store.observation_natural_key(observation))
            outcome = canonical_store.upsert_observation(
                db,
                observation,
                mapper_version=METHOD_VERSION,
                now=now,
                owner=session_id,
                derivation=load.details,
            )
            written += outcome is not canonical_store.WriteOutcome.UNCHANGED
    retired = canonical_store.retire_derived_observations(
        db, METHOD_ID, keep=keep, now=now
    )
    return {
        "sessions": len(loads),
        "with_load": sum(branches.values()),
        "branches": dict(sorted(branches.items())),
        "threshold_after_session": after_session,
        "missing": dict(sorted(missing.items())),
        "by_sport": {
            sport: dict(sorted(counts.items()))
            for sport, counts in sorted(by_sport.items())
        },
        "written": written,
        "retired": retired,
    }


class LocalLoadStage:
    """Backfill follow-up that reconciles the local load in one batch per pass."""

    def __init__(
        self,
        *,
        key_values: KeyValueRepository,
        zone_provider: Callable[[], tzinfo | None],
        clock: Callable[[], str],
        preferences: Preferences = lambda _db: NO_PREFERENCES,
        reader: CanonicalTableReader | None = None,
        session_feedback: FeedbackLookup | None = None,
        athlete_sex: Callable[[Any], str | None] = lambda _db: None,
    ) -> None:
        self._session_feedback = session_feedback
        self._athlete_sex = athlete_sex
        self._key_values = key_values
        self._zone_provider = zone_provider
        self._clock = clock
        self._preferences = preferences
        self._reader = reader or CanonicalTableReader()

    @property
    def stage(self) -> str:
        return STAGE

    def run_batch(self, db: Any) -> BatchReport:
        """Reconcile every session's local load in the caller's transaction."""
        reader = self._reader
        thresholds = DatedThresholds(
            [
                item
                for kind in THRESHOLD_KINDS
                for item in reader.observations(db, kind)
            ],
            reader.zone_configurations(db),
            reader.observations(db, MetricKind.RESTING_HR),
            preferences=self._preferences(db),
        )
        now = self._clock()
        summaries = _summaries(reader, db, self._zone_provider())
        counts = reconcile_local_loads(
            db,
            summaries,
            thresholds,
            now=now,
            feedback=feedback_by_session(
                rated_sessions(summaries), self._session_feedback
            ),
            sex=self._athlete_sex(db),
        )
        self._save(
            db,
            {
                "status": "complete",
                "method_version": METHOD_VERSION,
                "completed_at": now,
                "counts": counts,
            },
        )
        # Counts only: branch, reason and sport identifiers, never values.
        _LOGGER.info(
            "Local session load reconciled",
            extra={"event": "local_load_reconciled", "context": counts},
        )
        return BatchReport(items=counts["sessions"], done=True)

    def mark_failed(self, db: Any) -> None:
        state = self.summary(db)
        state["status"] = "failed"
        self._save(db, state)

    def summary(self, db: Any) -> dict[str, Any]:
        """Return the content-free status and counts of the last pass."""
        return summarize_local_load(self._key_values, db)

    def _save(self, db: Any, state: Mapping[str, Any]) -> None:
        self._key_values.set(
            db, STATE_KEY, json.dumps(state, sort_keys=True, separators=(",", ":"))
        )


# Card M6 v3: a heart-rate value computed without a saved profile sex.
SEX_ASSUMED_LABEL: Final = "Geschlecht nicht gesetzt, männliche Konstanten angenommen"


# Providers whose completed jobs can change a session or a threshold.
LOAD_INPUT_PROVIDERS: Final = frozenset(
    {ProviderId.INTERVALS.value, ProviderId.GARMIN.value, ProviderId.WAHOO.value}
)


def refresh_after_job(start: Callable[[], None]) -> Callable[[Mapping[str, Any]], None]:
    """A sync-job hook that requests a local load pass after an input provider's job."""

    def after_job(job: Mapping[str, Any]) -> None:
        if job.get("provider") in LOAD_INPUT_PROVIDERS:
            start()

    return after_job


def summarize_local_load(key_values: KeyValueRepository, db: Any) -> dict[str, Any]:
    """Content-free status and counts of the last local load pass, for diagnostics."""
    raw = key_values.get(db, STATE_KEY)
    try:
        state = json.loads(raw) if raw else {}
    except ValueError:
        state = {}
    if not isinstance(state, dict):
        state = {}
    return {
        "status": state.get("status", "pending"),
        "method_version": state.get("method_version"),
        "counts": state.get("counts", {}),
    }


def stored_local_loads(
    db: Any, session_ids: Iterable[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Map each session id to its stored local load and intensity rows.

    ``session_ids`` limits the read to those owners; None reads every row.
    """
    result: dict[str, dict[str, Any]] = {}
    owners = None if session_ids is None else list(session_ids)
    for row in canonical_store.derived_observation_rows(db, METHOD_ID, owners=owners):
        owner = row.get("owner_record_id")
        if not isinstance(owner, str):
            continue
        entry = result.setdefault(owner, {})
        entry[row["metric"]] = row
    return result


def daily_local_loads(db: Any) -> dict[str, float]:
    """Sum the stored local session loads per athlete-local ISO day, every day."""
    return canonical_store.derived_daily_sums(
        db, METHOD_ID, MetricKind.SESSION_LOAD.value
    )


def with_local_loads(
    summaries: Iterable[Mapping[str, Any]],
    stored: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return the summaries with the stored local load in place of provider loads."""
    result = []
    for summary in summaries:
        item = dict(summary)
        sources = dict(item.get("sources") or {})
        rows = stored.get(str(item.get("id")), {})
        load = rows.get(MetricKind.SESSION_LOAD.value)
        if load is not None:
            derivation = load["derivation"]
            item["training_load"] = load["value"]
            item["load_method"] = METHOD_ID
            item["load_method_version"] = load.get("method_version")
            item["load_branch"] = derivation.get("branch")
            if derivation.get("threshold_after_session"):
                item["load_threshold_after_session"] = True
            if (derivation.get("inputs") or {}).get("sex_assumed"):
                item["load_assumption"] = SEX_ASSUMED_LABEL
            sources["training_load"] = DERIVED_LABEL
            if calibration := derivation.get("calibration"):
                item["load_calibration"] = {
                    "tss_per_au": calibration.get("tss_per_au"),
                    "pairs": calibration.get("pairs"),
                    "session_rpe_au": (derivation.get("inputs") or {}).get(
                        "session_rpe_au"
                    ),
                }
        intensity = rows.get(MetricKind.INTENSITY_FACTOR.value)
        if intensity is not None:
            item["intensity"] = intensity["value"]
            sources["intensity"] = DERIVED_LABEL
        item["sources"] = sources
        result.append(item)
    return tuple(result)
