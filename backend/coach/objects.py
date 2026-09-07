"""Resolve current local object references without widening action scope."""
from typing import Any
import re


_CREATE_REQUEST_RE = re.compile(
    r"\b(?:add\w*|schedule\w*|create\w*|include\w*|"
    r"zus[aä]tzlich\w*|erg[aä]nz\w*|hinzuf[uü]g\w*|hinzu\w*|"
    r"anleg\w*|erstell\w*)\b"
    r"(?:\W+\w+){0,6}\W+\b(?:workout\w*|session\w*|ride\w*|run\w*|"
    r"walk\w*|swim\w*|bike\w*|training\w*|einheit\w*|lauf\w*|"
    r"fahrt\w*|rad\w*|schwimm\w*)\b"
)
_NEGATED_CREATE_REQUEST_RE = re.compile(
    r"\b(?:do\s+not|don't|never|not|nicht|kein\w*)\b.{0,50}\b(?:"
    r"add\w*|schedule\w*|create\w*|include\w*|new\w*|"
    r"zus[aä]tzlich\w*|erg[aä]nz\w*|hinzuf[uü]g\w*|hinzu\w*|"
    r"anleg\w*|erstell\w*|neu\w*)\b"
)
_POST_VERBAL_NEGATED_CREATE_REQUEST_RE = re.compile(
    r"\b(?:add\w*|schedule\w*|create\w*|include\w*|"
    r"zus[aä]tzlich\w*|erg[aä]nz\w*|hinzuf[uü]g\w*|hinzu\w*|"
    r"anleg\w*|erstell\w*)\b"
    r"(?:\W+\w+){0,4}\W+\b(?:no|not|kein\w*|nicht|never)\b"
)


def _has_non_negated_creation_request(text: str) -> bool:
    """Detect a create request without letting another clause veto it."""
    boundaries = re.compile(r"[;,.!?]|\b(?:and|und|but|aber)\b", re.IGNORECASE)
    for match in _CREATE_REQUEST_RE.finditer(text):
        before = list(boundaries.finditer(text, 0, match.start()))
        clause_start = before[-1].end() if before else 0
        after = boundaries.search(text, match.end())
        clause_end = after.start() if after else len(text)
        clause = text[clause_start:clause_end]
        if not _NEGATED_CREATE_REQUEST_RE.search(clause) and not _POST_VERBAL_NEGATED_CREATE_REQUEST_RE.search(clause):
            return True
    return False


def _creation_clause_spans(text: str, candidates: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Return create clauses without treating an existing target as new."""
    spans = []
    candidate_names = {
        str(ref.get("name") or "").casefold()
        for ref in candidates
        if str(ref.get("name") or "").strip()
    }
    for match in _CREATE_REQUEST_RE.finditer(text):
        existing_target_after_to = False
        for name in candidate_names:
            pattern = r"(?<![\w-])" + re.escape(name) + r"(?![\w-])"
            for target in re.finditer(pattern, text[match.start():match.end()]):
                prefix = text[match.start():match.start() + target.start()]
                if re.search(r"\bto\b", prefix):
                    existing_target_after_to = True
                    break
            if existing_target_after_to:
                break
        if not existing_target_after_to:
            spans.append(match.span())
    return spans


def resolve_intent_objects(intent: dict[str, Any], message: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    """Narrow selected object scopes before any action is authorized."""
    operations = {intent.get("operation"), *(intent.get("follow_up_operations") or [])}
    kinds = set()
    if operations & {"save_competition", "delete_competition"}:
        kinds.add("competition")
    if operations & {"update_training_plan", "replace_training_plan"}:
        kinds.add("training_plan")
    if "apply_training_changes" in operations:
        kinds.add("planned_unit")
    if "manage_training_templates" in operations:
        kinds.add("library_workout")
    scope = set(intent.get("authorization_scope") or [])
    text = message.casefold()
    for kind in kinds:
        all_candidates = [ref for ref in refs if ref["kind"] == kind]
        candidates = all_candidates
        if kind == "training_plan" and "replace_training_plan" in operations:
            candidates = [ref for ref in candidates if ref.get("status") != "archived"]
            archived_spans = [
                match.span()
                for ref in all_candidates if ref.get("status") == "archived"
                for value in (ref.get("id"), ref.get("name")) if value
                for match in re.finditer(r"(?<![\w-])" + re.escape(str(value).casefold()) + r"(?![\w-])", text)
            ]
            active_spans = [
                match.span()
                for ref in candidates
                for value in (ref.get("id"), ref.get("name")) if value
                for match in re.finditer(r"(?<![\w-])" + re.escape(str(value).casefold()) + r"(?![\w-])", text)
            ]
            archived_mentioned = any(
                (
                    not any(start <= a_start and a_end <= end for start, end in active_spans)
                    or bool(re.search(r"\barchiv\w*\b", text[max(0, a_start - 30):a_end + 30]))
                )
                for a_start, a_end in archived_spans
            )
            active_id_mentioned = any(
                ref.get("id") and str(ref["id"]).casefold() in text
                for ref in candidates
            )
            if archived_mentioned and not active_id_mentioned:
                return {"intent": "needs_clarification", "operation": None, "target_system": "none", "artifact_id": None, "authorization_scope": [], "follow_up_operations": [], "ambiguities": ["Der genannte Trainingsplan ist archiviert; bitte nenne einen aktiven Plan oder bestätige eine neue Planung."]}
        creation_clause_spans = (
            _creation_clause_spans(text, candidates)
            if kind == "planned_unit" and "apply_training_changes" in operations else []
        )
        mentions = []
        for ref in candidates:
            for value in {ref["id"], ref["name"]} - {""}:
                pattern = r"(?<![\w-])" + re.escape(value.casefold()) + r"(?![\w-])"
                mentions.extend(
                    (match.start(), match.end(), ref)
                    for match in re.finditer(pattern, text)
                    if not any(
                        clause_start <= match.start() and match.end() <= clause_end
                        for clause_start, clause_end in creation_clause_spans
                    )
                )
        # A shorter name inside the explicitly named longer object does not
        # authorize a second object. Separate mentions still select both.
        explicit_id_refs = [
            ref for ref in candidates
            if ref.get("id") and re.search(
                r"(?<![\w-])" + re.escape(str(ref["id"]).casefold()) + r"(?![\w-])", text
            )
        ]
        natural_named = [ref for ref in candidates if any(
            selected == ref and not any(
                outer_start <= start and end <= outer_end and (outer_start, outer_end) != (start, end)
                for outer_start, outer_end, _ in mentions
            ) for start, end, selected in mentions
        )]
        if explicit_id_refs:
            # An exact ID disambiguates only its duplicate-name group. Keep
            # independent names in the same multi-object request selected.
            duplicate_id_refs = [
                ref for ref in explicit_id_refs
                if sum(1 for other in candidates if other["name"].casefold() == ref["name"].casefold()) > 1
            ]
            duplicate_groups = {
                other["name"].casefold()
                for ref in duplicate_id_refs
                for other in candidates
                if other["name"].casefold() == ref["name"].casefold()
            }
            named = [
                ref for ref in natural_named
                if ref["name"].casefold() not in duplicate_groups
            ] + duplicate_id_refs
        else:
            named = natural_named
        if named and kind == "training_plan" and "replace_training_plan" in operations and "start_intervals_plan_sync" in operations:
            return {"intent": "needs_clarification", "operation": None, "target_system": "none", "artifact_id": None, "authorization_scope": [], "follow_up_operations": [], "ambiguities": ["Einen benannten Plan kann ich ersetzen; die Synchronisierung muss danach separat bestätigt werden."]}
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
            creates_new_workout = False
            if kind == "planned_unit" and "apply_training_changes" in operations:
                creation_text = text
                name_spans = [
                    (start, end)
                    for start, end, ref in mentions
                    if ref in named
                ]
                if name_spans:
                    masked = list(text)
                    for start, end in name_spans:
                        masked[start:end] = " " * (end - start)
                    creation_text = "".join(masked)
                creates_new_workout = _has_non_negated_creation_request(creation_text)
            if creates_new_workout:
                scope.discard(broad)
                scope.add("local_plan_create")
            else:
                scope.discard(broad)
                scope.discard("local_plan_create")
            scope.difference_update(requested)
            scope.update(resolved or {f"{kind}:{ref['id']}" for ref in named})
        elif requested:
            scope.difference_update(requested)
            scope.update(resolved)
    return {**intent, "authorization_scope": sorted(scope)}
