"""Provider coverage summaries for the canonical read layer.

Coverage reports how much canonical data a provider contributed and how many
mapping issues were met, as counts only. Issue details (record references and
field names) never leave the mapper, so a summary cannot repeat provider content.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

from backend.canonical.mapping import IssueReason, MappingIssue
from backend.canonical.validation import (
    optional_aware_datetime,
    require_date,
    require_instance,
)
from backend.canonical.vocabulary import ProviderId


def _require_count(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _copy_issue_counts(counts: object) -> Mapping[IssueReason, int]:
    if not isinstance(counts, Mapping):
        raise TypeError("issue_counts must be a mapping")
    copied: dict[IssueReason, int] = {}
    for reason, count in counts.items():
        require_instance(reason, IssueReason, "issue_counts key")
        copied[reason] = _require_count(count, "issue_counts value")
    return MappingProxyType(copied)


def _validate_observed_range(first: object, last: object) -> None:
    first_day = None if first is None else require_date(first, "first_observed_on")
    last_day = None if last is None else require_date(last, "last_observed_on")
    if (first_day is None) != (last_day is None):
        raise ValueError(
            "first_observed_on and last_observed_on must both be set or both be None"
        )
    if first_day is not None and last_day is not None and first_day > last_day:
        raise ValueError("first_observed_on must not be after last_observed_on")


@dataclass(frozen=True, slots=True)
class ProviderCoverage:
    """Counts describing one provider's contribution to the canonical layer.

    ``issue_counts`` may omit reasons that did not occur; an absent reason means
    zero. ``count_issues`` always returns every reason.
    """

    provider: ProviderId
    retrieved_at: datetime | None
    activity_count: int
    observation_count: int
    issue_counts: Mapping[IssueReason, int]
    first_observed_on: date | None
    last_observed_on: date | None

    def __post_init__(self) -> None:
        require_instance(self.provider, ProviderId, "provider")
        optional_aware_datetime(self.retrieved_at, "retrieved_at")
        _require_count(self.activity_count, "activity_count")
        _require_count(self.observation_count, "observation_count")
        object.__setattr__(self, "issue_counts", _copy_issue_counts(self.issue_counts))
        _validate_observed_range(self.first_observed_on, self.last_observed_on)


def count_issues(issues: Iterable[MappingIssue]) -> Mapping[IssueReason, int]:
    """Tally mapping issues by reason, in IssueReason definition order.

    Every reason appears, with zero for reasons that did not occur. Field names
    and record references are discarded.
    """
    tally: dict[IssueReason, int] = dict.fromkeys(IssueReason, 0)
    for issue in issues:
        require_instance(issue, MappingIssue, "issues")
        tally[issue.reason] += 1
    return MappingProxyType(tally)
