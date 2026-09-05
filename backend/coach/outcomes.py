"""Deterministic labels for durable Coach effects, independent of model prose."""
from typing import Any


COACH_OPERATION_LABELS = {
    "stage_training_plan": "Planentwurf gespeichert", "commit_training_plan": "Trainingsplan gespeichert",
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


def coach_effect_label(item: dict[str, Any]) -> str:
    label = COACH_OPERATION_LABELS.get(item.get("tool"), "Lokale Aktion")
    result = item.get("result") or {}
    count = len(result.get("library_entry_ids") or result.get("templates") or result.get("changes") or [])
    return f"{label} ({count})" if count else label

