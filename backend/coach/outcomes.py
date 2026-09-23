"""Deterministic labels for durable Coach effects, independent of model prose."""
from typing import Any


COACH_OPERATION_LABELS = {
    "update_profile": "Profil aktualisiert",
    "apply_training_patch": "Geplante Einheiten angepasst",
    "stage_training_plan": "Planentwurf gespeichert", "commit_training_plan": "Trainingsplan gespeichert",
    "replace_training_plan": "Trainingsplan ersetzt",
    "manage_training_templates": "Trainingsvorlagen bearbeitet", "apply_training_changes": "Geplante Einheiten bearbeitet",
    "save_checkin": "Tages-Check-in gespeichert", "save_activity_feedback": "Aktivitaetsfeedback gespeichert",
    "delete_activity_feedback": "Aktivitaetsfeedback entfernt", "save_competition": "Wettkampf gespeichert",
    "delete_competition": "Wettkampf entfernt", "start_provider_refresh": "Datenabruf beauftragt",
    "refresh_current_performance": "Leistungsdatenabruf beauftragt", "start_intervals_plan_sync": "Plansynchronisierung beauftragt",
    "sync_competitions": "Wettkampfsynchronisierung beauftragt", "undo_training_change": "Rueckgaengig-Vorschau vorbereitet",
    "apply_adaptive_replan": "Freigegebene Plananpassung angewendet", "preview_adaptive_replan": "Plananpassung vorgeschlagen",
    "update_training_plan": "Planinformationen bearbeitet", "apply_workout_library_plan": "Vorlagen eingeplant",
    "resolve_training_sync_conflict": "Synchronisierungskonflikt bearbeitet",
}

COACH_ACTION_LABELS = {
    "update_profile": "Profil aktualisieren",
    "apply_training_patch": "Geplante Einheiten anpassen",
    "stage_training_plan": "Planentwurf erstellen", "commit_training_plan": "Trainingsplan speichern",
    "replace_training_plan": "Trainingsplan vollständig ersetzen",
    "manage_training_templates": "Trainingsvorlagen bearbeiten", "apply_training_changes": "Geplante Einheiten bearbeiten",
    "save_checkin": "Tages-Check-in speichern", "save_activity_feedback": "Aktivitaetsfeedback speichern",
    "delete_activity_feedback": "Aktivitaetsfeedback entfernen", "save_competition": "Wettkampf speichern",
    "delete_competition": "Wettkampf entfernen", "start_provider_refresh": "Datenabruf starten",
    "refresh_current_performance": "Leistungsdaten abrufen", "start_intervals_plan_sync": "Plan synchronisieren",
    "sync_competitions": "Wettkaempfe synchronisieren", "undo_training_change": "Rueckgaengig-Vorschau erstellen",
    "apply_adaptive_replan": "Freigegebene Plananpassung anwenden", "preview_adaptive_replan": "Plananpassung vorschlagen",
    "update_training_plan": "Planinformationen bearbeiten", "apply_workout_library_plan": "Vorlagen einplanen",
    "resolve_training_sync_conflict": "Synchronisierungskonflikt bearbeiten",
}


def coach_failure_lines(commands: list[dict[str, Any]], pending_operations: set[str]) -> str:
    """Describe unresolved failures without success labels or retry history."""
    lines = []
    for item in commands:
        result = item.get("result") or {}
        if result.get("ok") or item.get("tool") not in pending_operations:
            continue
        label = COACH_ACTION_LABELS.get(item.get("tool"), "Angeforderter Schritt")
        detail = " ".join(str(result.get("error") or "Die Aktion konnte nicht ausgefuehrt werden.").split())
        if result.get("reason") in {"request_invalid", "request_target", "request_scope", "intent_scope_denied", "tool_scope_denied", "tool_arguments_invalid"}:
            detail = "Diese Änderung konnte nicht zuverlässig ausgeführt werden; dafür wurde nichts gespeichert."
        if result.get("reason") in {"missing_workout_target", "invalid_workout_step", "missing_workout_steps",
                                   "ambiguous_workout_step", "ambiguous_workout_target", "workout_target_mismatch",
                                   "invalid_workout_repeat", "workout_duration_mismatch"}:
            detail = "Der Coach konnte die Einheit noch nicht korrekt in ein ausführbares Workout übersetzen. Die Änderung wurde nicht gespeichert."
        line = f"- {label}: {detail}"
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


def coach_effect_label(item: dict[str, Any]) -> str:
    label = COACH_OPERATION_LABELS.get(item.get("tool"), "Lokale Aktion")
    result = item.get("result") or {}
    if item.get("tool") == "start_provider_refresh" and result.get("status") == "completed":
        label = "Daten aktualisiert"
    count = len(result.get("library_entry_ids") or result.get("templates") or result.get("changes") or [])
    return f"{label} ({count})" if count else label


def coach_observed_sync_lines(commands: list[dict[str, Any]]) -> str:
    """Retain the last confirmed status of each inspected plan-sync job."""
    jobs = {}
    for command in commands:
        result = command.get("result") or {}
        job = result.get("job") or {}
        if (command.get("tool") == "get_sync_job" and result.get("ok")
                and job.get("provider") == "intervals" and job.get("type") == "plan_push" and job.get("id")):
            jobs[job["id"]] = job
    labels = {
        "queued": "wartet auf Verarbeitung", "running": "läuft noch",
        "completed": "erfolgreich abgeschlossen", "partial": "nur teilweise abgeschlossen",
        "failed": "fehlgeschlagen", "cancelled": "abgebrochen",
    }
    return "\n".join(f"Zuletzt bestätigter Stand des geprüften Plan-Sync-Auftrags: {labels.get(job.get('status'), 'Abschluss noch nicht bestätigt')}."
                     for job in jobs.values())


def _result(entry: dict[str, Any]) -> dict[str, Any]:
    result = entry.get("result")
    return result if isinstance(result, dict) else {}


def _alternative_planning_steps_repaired(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Allow an invalid patch to be repaired by an equivalent plan replacement."""
    before_tool, after_tool = previous.get("tool"), current.get("tool")
    alternatives = (
        (before_tool == "apply_training_patch" and after_tool == "replace_training_plan")
        or (before_tool == "replace_training_plan" and after_tool == "apply_training_patch")
    )
    before, after = _result(previous), _result(current)
    request_key = previous.get("request_binding_key")
    effect_key = previous.get("plan_effect_key")
    return (
        alternatives
        and before.get("reason") in ("request_invalid", "tool_arguments_invalid")
        and request_key and request_key == current.get("request_binding_key")
        and effect_key and effect_key == current.get("plan_effect_key")
    )


def _profile_repair_fields(entry: dict[str, Any]) -> Any:
    repair_key = entry.get("repair_key")
    return repair_key.get("profile_fields") if isinstance(repair_key, dict) else None


def _profile_steps_repaired(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """A profile-conflict retry must affect the same fields."""
    if previous.get("tool") != "update_profile" or _result(previous).get("reason") != "profile_conflict":
        return True
    previous_fields = _profile_repair_fields(previous)
    current_fields = _profile_repair_fields(current)
    return bool(previous_fields) and previous_fields == current_fields


def _matching_coach_steps_repaired(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Compare equivalent actions without allowing one object to repair another."""
    before = previous.get("request") or {}
    after = current.get("request") or {}
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    if not before:
        return _result(previous).get("reason") in ("request_invalid", "tool_arguments_invalid")
    if before.get("target") != after.get("target"):
        return False
    if (current.get("tool") == "start_intervals_plan_sync" and after.get("sync_scope") == "all_pending"
            and before.get("sync_scope") in ("selected", "all_pending")):
        return True
    try:
        scopes_match = set(before.get("scope") or []) == set(after.get("scope") or [])
    except TypeError:
        return False
    return before.get("period") == after.get("period") and scopes_match


def _coach_steps_repaired(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """Corrections resolve the same step, never a different object with the same tool."""
    if previous.get("tool") != current.get("tool"):
        return _alternative_planning_steps_repaired(previous, current)
    if not _profile_steps_repaired(previous, current):
        return False
    scope_key = previous.get("scope_repair_key")
    if (_result(previous).get("reason") == "request_scope" and scope_key
            and scope_key == current.get("scope_repair_key")):
        return True
    return _matching_coach_steps_repaired(previous, current)


def unresolved_coach_steps(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return failed steps not repaired by a later equivalent successful receipt.

    Receipts are persisted and may contain malformed values. Invalid structures
    cannot establish equivalence, except for the legacy missing-request fallback
    on invalid-argument failures, which is preserved during this extraction.
    """
    latest: dict[Any, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        if not isinstance(tool, str) or not tool:
            continue
        if _result(entry).get("ok"):
            latest = {key: previous for key, previous in latest.items()
                      if not _coach_steps_repaired(previous, entry)}
        step_key = entry.get("step_key") or tool
        try:
            latest[step_key] = entry
        except TypeError:
            latest[tool] = entry
    return [entry for entry in latest.values() if not _result(entry).get("ok")]
