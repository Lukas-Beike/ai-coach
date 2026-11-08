"""docs/canonical-field-map.md stays complete when mappers or the vocabulary change.

The map is read as text. The checks fail when

* a provider mapper names a canonical enum member or builds a canonical record
  field that its section in the map does not list,
* a canonical vocabulary enum member or record field has no entry,
* a mapper's documented version differs from its ``MAPPER_VERSION``,
* the map cites a source file that no longer exists.

A new mapper module needs a section headed with its file name in backticks.
"""

from __future__ import annotations

import importlib
import re
import unittest
from typing import Final

from tests import canonical_field_map_support as support

# Provider modules that name canonical enum members without mapping provider payloads.
NOT_MAPPERS: Final[dict[str, str]] = {
    "canonical_plans": "versioned observation/plan projections of stored rows",
    "descriptors": "provider capability and sync descriptors",
    "source_labels": "display labels for provider ids and source kinds",
    "intervals_workouts": "outbound workout payloads for the output target",
}
NO_SECTION_NEEDED: Final = frozenset(NOT_MAPPERS)
# Local producers of canonical records: each needs a section like a mapper.
LOCAL_PRODUCERS: Final = (
    "backend/sync/local_load.py",
    "backend/sync/session_metrics.py",
    "backend/performance/session_metrics.py",
    "backend/performance/morning_battery_service.py",
    "backend/athlete/zones.py",
    "backend/activities/stream_zones.py",
)
# Other backend files that build canonical records without producing new data.
NOT_PRODUCERS: Final[dict[str, str]] = {
    "backend/activities/session_linking.py": "rebuilds a record with another link",
    "backend/db/activity_detail_store.py": "decodes stored detail rows",
    "backend/db/canonical_store.py": "decodes stored observation rows",
    "backend/sync/canonical_table_reader.py": "decodes stored rows",
    "backend/performance/current_thresholds.py": "transient observation of a zone",
    "backend/sync/wahoo_activity_details.py": "stores sets the FIT mapper produced",
}
PATH_TOKEN = re.compile(r"^(?:backend|tests|scripts|public|docs)/[\w./-]+\.\w+$")
MODULE_TOKEN = re.compile(r"^[a-z][a-z0-9_]*\.py$")


def _doc_text() -> str:
    return support.DOC.read_text(encoding="utf-8")


class CanonicalFieldMapDocTests(unittest.TestCase):
    text: str
    sections: list[tuple[int, str, str]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = _doc_text()
        cls.sections = support.doc_sections(cls.text)

    def _section_by_name(self, name: str) -> str:
        for _, title, body in self.sections:
            if f"`{name}`" in title:
                return body
        self.fail(f"docs/canonical-field-map.md has no section headed `{name}`")

    def test_every_mapper_module_has_a_section_with_all_emitted_fields(self) -> None:
        problems = []
        for path in support.mapper_modules():
            if path.stem in NO_SECTION_NEEDED:
                continue
            body = support.section_for_module(self.sections, path.name)
            if body is None:
                problems.append(f"{path.name}: no section")
                continue
            missing = sorted(
                support.emitted_tokens(path.read_text(encoding="utf-8"))
                - support.backticked(body)
            )
            if missing:
                problems.append(f"{path.name}: not listed: {', '.join(missing)}")
            if "Not mapped" not in body:
                problems.append(f"{path.name}: no 'Not mapped' paragraph")
        self.assertEqual([], problems)

    def test_local_producers_have_sections_with_all_emitted_fields(self) -> None:
        problems = []
        for relative in LOCAL_PRODUCERS:
            path = support.ROOT / relative
            body = support.section_for_module(self.sections, path.name)
            if body is None:
                problems.append(f"{relative}: no section")
                continue
            missing = sorted(
                support.emitted_tokens(path.read_text(encoding="utf-8"))
                - support.backticked(body)
            )
            if missing:
                problems.append(f"{relative}: not listed: {', '.join(missing)}")
        self.assertEqual([], problems)

    def test_no_unlisted_backend_file_builds_canonical_records(self) -> None:
        known = {*LOCAL_PRODUCERS, *NOT_PRODUCERS}
        unknown = [
            path.relative_to(support.ROOT).as_posix()
            for path in support.record_builders_outside_providers()
            if path.relative_to(support.ROOT).as_posix() not in known
        ]
        self.assertEqual([], unknown)

    def test_documented_mapper_version_matches_the_code(self) -> None:
        problems = []
        for path in support.mapper_modules():
            module = importlib.import_module(f"backend.providers.{path.stem}")
            version = getattr(module, "MAPPER_VERSION", None)
            body = support.section_for_module(self.sections, path.name)
            if version is None or body is None:
                continue
            if f"Mapper version: **{version}**" not in body:
                problems.append(
                    f"{path.name}: section must state 'Mapper version: **{version}**'"
                )
        self.assertEqual([], problems)

    def test_every_vocabulary_enum_member_is_listed(self) -> None:
        problems = []
        for name, enum in support.vocabulary_enums().items():
            body = self._section_by_name(name)
            listed = support.backticked(body)
            missing = [m.value for m in enum if m.value not in listed]
            if missing:
                problems.append(f"{name}: not listed: {', '.join(missing)}")
        self.assertEqual([], problems)

    def test_every_canonical_record_field_is_listed(self) -> None:
        problems = []
        for name, cls in support.record_classes().items():
            listed = support.backticked(self._section_by_name(name))
            missing = [f for f in support.record_fields(cls) if f not in listed]
            if missing:
                problems.append(f"{name}: not listed: {', '.join(missing)}")
        self.assertEqual([], problems)

    def test_cited_source_files_exist(self) -> None:
        missing = []
        names = {
            path.name
            for folder in ("backend", "tests", "scripts")
            for path in (support.ROOT / folder).rglob("*.py")
        } | {path.name for path in support.ROOT.glob("*.py")}
        for token in support.backticked(self.text):
            if PATH_TOKEN.match(token):
                if not (support.ROOT / token).exists():
                    missing.append(token)
            elif MODULE_TOKEN.match(token) and token not in names:
                missing.append(token)
        self.assertEqual([], sorted(set(missing)))


if __name__ == "__main__":
    unittest.main()
