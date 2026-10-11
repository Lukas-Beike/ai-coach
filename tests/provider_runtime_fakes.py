"""Shared fakes for provider runtime and orchestration tests.

The ``acme-mock`` provider exists only in tests. It is registered alongside the
real descriptors to prove that orchestration needs no provider literal. Helper
module, not a test module: it is imported by test modules and discovered by none.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from backend.providers.descriptors import (
    Capability,
    FreshnessArea,
    ProviderDescriptor,
    SchedulePolicy,
)
from backend.sync.provider_runtime import (
    FreshnessInputs,
    FreshnessSource,
    ProviderRuntimeBinding,
)

ACME_ID = "acme-mock"
ACME_AREA = "activities"
TWO_DAYS_SECONDS = 48 * 60 * 60


def acme_descriptor() -> ProviderDescriptor:
    """Return the test-only descriptor: ranks 99, daily marker, one area."""
    return ProviderDescriptor(
        provider_id=ACME_ID,
        label="Acme mock",
        capabilities=frozenset({Capability.ACTIVITIES}),
        freshness_areas=(
            FreshnessArea(
                area=ACME_AREA,
                label="Acme mock · Training",
                stale_after_s=TWO_DAYS_SECONDS,
                read_only=True,
            ),
        ),
        max_sync_days=60,
        resync_keys=(),
        default_sync_days=14,
        schedule=SchedulePolicy(daily_rank=99, startup_rank=99, daily_marker=True),
        coach_rank=99,
    )


class FakeJobOwner:
    """Records every job it executes and returns a fixed outcome."""

    def __init__(self, result: Mapping[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._result: dict[str, Any] = dict(result or {"status": "completed"})

    def execute(
        self,
        job: Mapping[str, Any],
        payload: dict[str, Any],
        reason: str,
        *,
        job_type: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "job": dict(job),
                "payload": dict(payload),
                "reason": reason,
                "job_type": job_type,
            }
        )
        return dict(self._result)


class FakeSchedulePolicy:
    """Answers scheduling questions from fixed flags and records refreshes."""

    def __init__(self, *, configured: bool = True, blocked: bool = False) -> None:
        self._configured = configured
        self._blocked = blocked
        self.refresh_calls: list[tuple[str, str]] = []

    def configured(self) -> bool:
        return self._configured

    def blocked(self) -> bool:
        return self._blocked

    def refresh_payload(
        self, trigger: Literal["daily", "startup"], reason: str
    ) -> dict[str, Any]:
        self.refresh_calls.append((trigger, reason))
        return {"days": 14, "reason": reason, "trigger": trigger}


def acme_freshness_source() -> FreshnessSource:
    """Return a freshness source that reads only the fake profile and values."""
    return FreshnessSource(
        fallback_at=lambda inputs: inputs.get_value("acme_last_sync_at"),
        fallback_error=lambda inputs: inputs.get_value("acme_last_sync_error"),
        configured=lambda inputs: bool(inputs.profile.get("acme_enabled")),
    )


def fake_freshness_inputs(
    *,
    values: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
) -> FreshnessInputs:
    """Build freshness inputs backed by a plain mapping of key-value settings."""
    stored: dict[str, Any] = dict(values or {})
    return FreshnessInputs(
        config=None,
        get_value=stored.get,
        profile=dict(profile or {}),
        signals={},
    )


def fake_binding(
    provider_id: str = ACME_ID,
    *,
    owner: FakeJobOwner | None = None,
    policy: FakeSchedulePolicy | None = None,
    freshness: Mapping[str, FreshnessSource] | None = None,
    configured: bool = True,
) -> ProviderRuntimeBinding:
    """Build a binding around fakes; freshness defaults to the acme area."""
    job_owner = FakeJobOwner() if owner is None else owner
    schedule_policy = FakeSchedulePolicy() if policy is None else policy
    sources: Mapping[str, FreshnessSource] = (
        {ACME_AREA: acme_freshness_source()} if freshness is None else freshness
    )
    return ProviderRuntimeBinding(
        provider_id=provider_id,
        job_owner=lambda: job_owner,
        configured=lambda: configured,
        schedule=lambda: schedule_policy,
        freshness=sources,
    )
