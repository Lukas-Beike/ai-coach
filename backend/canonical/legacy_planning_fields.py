"""Frozen Intervals.icu keys stored by releases through schema v18."""

from collections.abc import Mapping
from typing import Any

LEGACY_PLANNING_METRICS = {
    "icu_training_load": "planned_load",
    "icu_intensity": "planned_intensity",
}
LEGACY_TARGET_BASIS = {"icu_ftp": "ftp"}


def normalize_legacy_detail_targets(record: Mapping[str, Any]) -> dict[str, Any]:
    """Translate frozen target bases while leaving the original record untouched."""

    def target(value: object) -> object:
        if not isinstance(value, dict) or not isinstance(value.get("basis"), dict):
            return value
        basis = dict(value["basis"])
        for old, new in LEGACY_TARGET_BASIS.items():
            if old in basis:
                if new in basis and (
                    type(basis[new]) is not type(basis[old]) or basis[new] != basis[old]
                ):
                    raise RuntimeError(f"Conflicting planning fields: {old} and {new}")
                old_value = basis.pop(old)
                basis.setdefault(new, old_value)
        return {**value, "basis": basis}

    result = dict(record)
    if "target_snapshot" in result:
        result["target_snapshot"] = target(result["target_snapshot"])
    analysis = result.get("session_analysis")
    if isinstance(analysis, dict) and isinstance(
        analysis.get("interval_quality"), dict
    ):
        quality = analysis["interval_quality"]
        if "target_snapshot" in quality:
            result["session_analysis"] = {
                **analysis,
                "interval_quality": {
                    **quality,
                    "target_snapshot": target(quality["target_snapshot"]),
                },
            }
    return result
