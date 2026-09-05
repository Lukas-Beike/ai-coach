"""Resolve current local object references without widening action scope."""
from typing import Any
import re


def resolve_intent_objects(intent: dict[str, Any], message: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    """Narrow selected object scopes before any action is authorized."""
    operations = {intent.get("operation"), *(intent.get("follow_up_operations") or [])}
    kinds = set()
    if operations & {"save_competition", "delete_competition"}:
        kinds.add("competition")
    if "update_training_plan" in operations:
        kinds.add("training_plan")
    if "apply_training_changes" in operations:
        kinds.add("planned_unit")
    if "manage_training_templates" in operations:
        kinds.add("library_workout")
    scope = set(intent.get("authorization_scope") or [])
    text = message.casefold()
    for kind in kinds:
        candidates = [ref for ref in refs if ref["kind"] == kind]
        mentions = []
        for ref in candidates:
            for value in {ref["id"], ref["name"]} - {""}:
                pattern = r"(?<![\w-])" + re.escape(value.casefold()) + r"(?![\w-])"
                mentions.extend((match.start(), match.end(), ref) for match in re.finditer(pattern, text))
        # A shorter name inside the explicitly named longer object does not
        # authorize a second object. Separate mentions still select both.
        named = [ref for ref in candidates if any(
            selected == ref and not any(
                outer_start <= start and end <= outer_end and (outer_start, outer_end) != (start, end)
                for outer_start, outer_end, _ in mentions
            ) for start, end, selected in mentions
        )]
        for ref in named:
            equal_names = [other for other in candidates if other["name"].casefold() == ref["name"].casefold()]
            if len(equal_names) > 1 and not any(other["id"] in message for other in equal_names):
                choices = ", ".join(f"{other['name']} ({other.get('date') or other['id'][:8]})" for other in equal_names)
                return {"intent": "needs_clarification", "operation": None, "target_system": "none", "artifact_id": None, "authorization_scope": [], "follow_up_operations": [], "ambiguities": [f"Welches Objekt meinst du: {choices}?"]}
        broad = {"competition": "local_competitions", "training_plan": "local_plan", "planned_unit": "local_plan", "library_workout": "local_template"}[kind]
        requested = [token for token in scope if token.startswith(kind + ":")]
        resolved = set()
        for token in requested:
            value = token.split(":", 1)[1]
            matches = [ref for ref in candidates if value == ref["id"] or value.casefold() == ref["name"].casefold()]
            if len(matches) != 1 or matches[0] not in named:
                return {"intent": "needs_clarification", "operation": None, "target_system": "none", "artifact_id": None, "authorization_scope": [], "follow_up_operations": [], "ambiguities": ["Welches konkret benannte lokale Objekt soll ich bearbeiten?"]}
            resolved.add(f"{kind}:{matches[0]['id']}")
        if named:
            scope.discard(broad)
            scope.difference_update(requested)
            scope.update(resolved or {f"{kind}:{ref['id']}" for ref in named})
        elif requested:
            scope.difference_update(requested)
            scope.update(resolved)
    return {**intent, "authorization_scope": sorted(scope)}
