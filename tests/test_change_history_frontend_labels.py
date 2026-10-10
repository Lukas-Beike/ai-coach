"""Contract: the diagnostics change-history labels cover the backend projection.

The backend owns the entity and field vocabulary in backend/change_history.py.
The browser renders those values with label maps in public/diagnostics.js, so a
new entity type or projected field must not fall back to raw identifiers.
"""

import ast
import re
import unittest

try:
    from .architecture_registry import BACKEND_ROOT
except ImportError:
    from architecture_registry import BACKEND_ROOT

PUBLIC_ROOT = BACKEND_ROOT.parent / "public"
FIELD_SET_NAMES = {
    "PROFILE_FIELDS",
    "LIBRARY_FIELDS",
    "PLANNED_UNIT_FIELDS",
    "COMPETITION_FIELDS",
    "PLAN_FIELDS",
}


def _backend_module_literals() -> dict[str, object]:
    tree = ast.parse((BACKEND_ROOT / "change_history.py").read_text(encoding="utf-8"))
    values: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {
                "ENTITY_TYPES",
                *FIELD_SET_NAMES,
            }:
                values[target.id] = ast.literal_eval(node.value)
    return values


def _js_object_keys(source: str, constant: str) -> dict[str, str]:
    match = re.search(rf"const {constant} = \{{(.*?)\n\}};", source, re.DOTALL)
    if match is None:
        raise AssertionError(f"{constant} is missing from diagnostics.js")
    return dict(
        re.findall(r'^\s*([a-z_]+):\s*"([^"]+)",?$', match.group(1), re.MULTILINE)
    )


class ChangeHistoryFrontendLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.diagnostics = (PUBLIC_ROOT / "diagnostics.js").read_text(encoding="utf-8")
        cls.backend = _backend_module_literals()

    def test_entity_label_map_covers_every_backend_entity_type(self):
        labels = _js_object_keys(self.diagnostics, "CHANGE_HISTORY_LABELS")
        self.assertEqual(set(labels), set(self.backend["ENTITY_TYPES"]))
        for entity_type, label in labels.items():
            self.assertTrue(label.strip(), entity_type)

    def test_field_label_map_covers_every_projected_backend_field(self):
        labels = _js_object_keys(self.diagnostics, "CHANGE_HISTORY_FIELD_LABELS")
        projected: set[str] = set()
        for name in FIELD_SET_NAMES:
            projected |= set(self.backend[name])
        self.assertEqual(sorted(projected - set(labels)), [])

    def test_action_label_map_covers_every_backend_action(self):
        actions = _js_object_keys(self.diagnostics, "CHANGE_HISTORY_ACTIONS")
        self.assertEqual(set(actions), {"create", "update", "delete", "undo"})


if __name__ == "__main__":
    unittest.main()
