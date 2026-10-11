"""Tests for the shared walk over Garmin weight payloads.

The walk is pure and standard-library only. Each test builds its payload inline; no
provider, network, database or real data directory is involved.
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from typing import Any

from backend.providers.garmin_weight_walk import (
    BODY_FAT_SKIP_KEYS,
    WALK_DATE_KEYS,
    WALK_MAX_DEPTH,
    WALK_MAX_LIST_ITEMS,
    WALK_MAX_VISITS,
    WEIGHT_SKIP_KEYS,
    WalkedRecord,
    alnum_key,
    walk_records,
    weight_payload,
)

NO_SKIP: frozenset[str] = frozenset()


def _day(record: Mapping[str, Any]) -> str | None:
    value = record.get("day")
    return value if isinstance(value, str) else None


def _walk(
    payload: object,
    *,
    skip_keys: frozenset[str] = NO_SKIP,
    marker_keys: frozenset[str] = frozenset(),
) -> list[WalkedRecord[str | None]]:
    return list(
        walk_records(
            payload,
            skip_keys=skip_keys,
            resolve_day=_day,
            marker_keys=marker_keys,
        )
    )


class AlnumKeyTests(unittest.TestCase):
    def test_keys_compare_without_case_or_punctuation(self) -> None:
        self.assertEqual(alnum_key("Min-Weight"), "minweight")
        self.assertEqual(alnum_key("minBodyFat_Delta"), "minbodyfatdelta")
        self.assertEqual(alnum_key(5), "5")

    def test_shared_constants_are_lowercase_keys(self) -> None:
        self.assertIn("timestampGMT", WALK_DATE_KEYS)
        self.assertIn("minweight", WEIGHT_SKIP_KEYS)
        self.assertIn("bodyfatdelta", BODY_FAT_SKIP_KEYS)


class WeightPayloadTests(unittest.TestCase):
    def test_first_truthy_section_wins(self) -> None:
        sections = {"weight": [], "weigh_ins": [{"day": "2026-10-10"}], "weighIns": [1]}

        self.assertEqual(weight_payload(sections), [{"day": "2026-10-10"}])

    def test_later_section_is_used_when_earlier_ones_are_falsy(self) -> None:
        self.assertEqual(weight_payload({"weight": 0, "weighIns": [{}]}), [{}])

    def test_last_lookup_is_returned_when_every_section_is_falsy(self) -> None:
        self.assertEqual(weight_payload({"weighIns": []}), [])
        self.assertIsNone(weight_payload({}))


class WalkLimitTests(unittest.TestCase):
    def test_depth_limit_stops_the_walk(self) -> None:
        payload: dict[str, Any] = {}
        for _ in range(WALK_MAX_DEPTH + 10):
            payload = {"child": payload}

        records = _walk(payload)

        self.assertEqual(len(records), WALK_MAX_DEPTH + 1)

    def test_scalars_count_towards_the_visit_limit(self) -> None:
        payload: dict[str, Any] = {
            f"k{index}": 1 for index in range(WALK_MAX_VISITS - 1)
        }
        payload["late"] = {}

        records = _walk(payload)

        self.assertEqual(len(records), 1)

    def test_visit_limit_caps_mapping_records(self) -> None:
        payload: dict[str, Any] = {
            f"k{index}": {} for index in range(WALK_MAX_VISITS + 500)
        }

        records = _walk(payload)

        self.assertEqual(len(records), WALK_MAX_VISITS)

    def test_list_items_are_capped(self) -> None:
        payload: list[Any] = [{} for _ in range(WALK_MAX_LIST_ITEMS + 100)]

        records = _walk(payload)

        self.assertEqual(len(records), WALK_MAX_LIST_ITEMS)
        self.assertEqual(records[-1].list_index, WALK_MAX_LIST_ITEMS - 1)


class WalkStructureTests(unittest.TestCase):
    def test_scalar_root_yields_nothing(self) -> None:
        self.assertEqual(_walk("2026-10-10"), [])
        self.assertEqual(_walk(5), [])
        self.assertEqual(_walk(None), [])

    def test_records_are_yielded_in_pre_order(self) -> None:
        payload: dict[str, Any] = {"a": {"b": {}}, "c": {}}

        records = _walk(payload)

        self.assertEqual([record.ordinal for record in records], [0, 1, 2, 3])
        self.assertIs(records[0].record, payload)
        self.assertIs(records[1].record, payload["a"])
        self.assertIs(records[2].record, payload["a"]["b"])
        self.assertIs(records[3].record, payload["c"])

    def test_skipped_keys_are_not_entered(self) -> None:
        payload = {
            "minWeight": {"day": "2026-10-01"},
            "min_weight": {"day": "2026-10-02"},
            "keep": {"day": "2026-10-03"},
        }

        records = _walk(payload, skip_keys=WEIGHT_SKIP_KEYS)

        self.assertEqual([record.day for record in records], [None, "2026-10-03"])

    def test_marker_keys_mark_their_whole_subtree(self) -> None:
        payload: dict[str, Any] = {"latestWeight": {"nested": {}}, "other": {}}

        records = _walk(payload, marker_keys=frozenset({"latestWeight"}))

        self.assertEqual(
            [record.marked for record in records], [False, True, True, False]
        )

    def test_list_index_is_the_nearest_enclosing_list_item(self) -> None:
        payload: list[Any] = [{"x": [{}, {}]}]

        records = _walk(payload)

        self.assertEqual([record.list_index for record in records], [0, 0, 1])

    def test_mapping_root_has_no_list_index(self) -> None:
        records = _walk({"x": {}})

        self.assertEqual([record.list_index for record in records], [None, None])

    def test_list_items_inherit_the_day_of_their_ancestor(self) -> None:
        payload = {"day": "2026-10-10", "items": [{}, {"day": "2026-10-11"}]}

        records = _walk(payload)

        self.assertEqual(
            [record.day for record in records],
            ["2026-10-10", "2026-10-10", "2026-10-11"],
        )

    def test_record_without_day_inherits_and_undated_root_stays_none(self) -> None:
        payload = {"items": {"day": "2026-10-10", "child": {}}}

        records = _walk(payload)

        self.assertEqual(
            [record.day for record in records],
            [None, "2026-10-10", "2026-10-10"],
        )


if __name__ == "__main__":
    unittest.main()
