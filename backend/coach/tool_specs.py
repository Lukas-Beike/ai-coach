"""One description per Coach tool; the tool tables are derived from it.

A ``ToolSpec`` names the Coach tool service the dispatch calls, the effect
class, the write-gate domain and gate facts, the plan and transaction traits,
and the German receipt and action labels. The schema sent to the model stays in
``backend/coach/tool_schemas.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Effect classes (backend/coach/capabilities.py).
READ = "read"
CONTROL = "control"
PROVIDER_READ_JOB = "provider_read_job"
REMOTE_WRITE = "remote_write"
CONDITIONAL_REMOTE_WRITE = "conditional_remote_write"
LOCAL_WRITE = "local_write"

# Write-gate domains (backend/coach/write_gate.py).
PLANNING = "planning"
PROFILE = "profile"
COMPETITION = "competition"
CHECKIN = "checkin"
NUTRITION = "nutrition"
UNDO = "undo"
REMOTE_INTERVALS = "remote_intervals"
REMOTE_GARMIN = "remote_garmin"

# The Coach tool service the dispatch calls (it may delegate further).
READS = "CoachReadToolService"
PROFILE_UPDATE = "CoachProfileUpdateService"
ATHLETE_RECORDS = "CoachAthleteRecordToolService"
PLAN_ARTIFACTS = "CoachPlanArtifactToolService"
PLANNING_CHANGES = "CoachPlanningChangeToolService"
TRAINING_PATCH = "CoachTrainingPatchService"
TEMPLATES = "TrainingTemplateToolService"
LIBRARY_PLANS = "CoachLibraryPlanToolService"
SYNC = "CoachSyncToolService"
PLANNING_ACTIONS = "CoachPlanningActionToolService"
CLARIFICATION = "CoachClarificationService"
EXECUTION = "CoachStructuredToolExecutionService"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    owner: str
    effect: str = LOCAL_WRITE
    # Write-gate domain; None for reads and for the ungated control and
    # provider-refresh tools.
    domain: str | None = None
    done: str | None = None  # receipt label
    action: str | None = None  # proposal action label
    deletes: bool = False  # needs a confirmed delete request
    whole_plan: bool = False  # creates, replaces or archives a whole plan
    no_record: bool = False  # a draft or preview; changes no record
    record_lists: tuple[str, ...] = ()  # argument lists with one record per item
    needs_approval: bool = False  # the classifier confirms an approved preview
    plan_checked: bool = False  # the resulting plan is checked
    self_guarded: bool = False  # the plan check runs inside the tool
    mutates_profile: bool = False  # runs under the profile coordinator
    external_food_lookup: bool = False  # may call the food database


def _read(
    name: str, owner: str = READS, *, external_food_lookup: bool = False
) -> ToolSpec:
    return ToolSpec(name, owner, READ, external_food_lookup=external_food_lookup)


TOOL_SPECS: tuple[ToolSpec, ...] = (
    _read("read_coach_context"),
    _read("read_profile"),
    _read("read_training_state"),
    _read("list_recent_activities"),
    _read("get_activity_details"),
    _read("get_training_report"),
    _read("read_training_records"),
    _read("list_workout_library"),
    _read("list_planned_workouts"),
    _read("list_change_history"),
    _read("list_competitions"),
    _read("list_training_plans"),
    _read("get_sync_job", SYNC),
    _read("read_nutrition"),
    _read("lookup_food", external_food_lookup=True),
    _read("calculate_food_nutrition", external_food_lookup=True),
    ToolSpec(
        "update_profile",
        PROFILE_UPDATE,
        domain=PROFILE,
        done="Profil aktualisiert",
        action="Profil aktualisieren",
        mutates_profile=True,
    ),
    ToolSpec(
        "save_checkin",
        ATHLETE_RECORDS,
        domain=CHECKIN,
        done="Tages-Check-in gespeichert",
        action="Tages-Check-in speichern",
    ),
    ToolSpec(
        "save_activity_feedback",
        ATHLETE_RECORDS,
        domain=CHECKIN,
        done="Aktivitätsfeedback gespeichert",
        action="Aktivitätsfeedback speichern",
    ),
    ToolSpec(
        "delete_activity_feedback",
        ATHLETE_RECORDS,
        domain=CHECKIN,
        done="Aktivitätsfeedback entfernt",
        action="Aktivitätsfeedback entfernen",
        deletes=True,
    ),
    ToolSpec(
        "save_competition",
        ATHLETE_RECORDS,
        domain=COMPETITION,
        done="Wettkampf gespeichert",
        action="Wettkampf speichern",
    ),
    ToolSpec(
        "delete_competition",
        ATHLETE_RECORDS,
        domain=COMPETITION,
        done="Wettkampf entfernt",
        action="Wettkampf entfernen",
        deletes=True,
    ),
    ToolSpec(
        "save_nutrition_template",
        ATHLETE_RECORDS,
        domain=NUTRITION,
        done="Mahlzeitvorlage gespeichert",
        action="Mahlzeitvorlage speichern",
        external_food_lookup=True,
    ),
    ToolSpec(
        "save_nutrition_product",
        ATHLETE_RECORDS,
        domain=NUTRITION,
        done="Produkt lokal gespeichert",
        action="Produkt lokal speichern",
        external_food_lookup=True,
    ),
    ToolSpec(
        "delete_nutrition_template",
        ATHLETE_RECORDS,
        domain=NUTRITION,
        done="Mahlzeitvorlage entfernt",
        action="Mahlzeitvorlage entfernen",
        deletes=True,
    ),
    ToolSpec(
        "log_nutrition_template",
        ATHLETE_RECORDS,
        domain=NUTRITION,
        done="Verzehr gespeichert",
        action="Verzehr erfassen",
    ),
    ToolSpec(
        "save_nutrition_entry",
        ATHLETE_RECORDS,
        domain=NUTRITION,
        done="Ernährungseintrag gespeichert",
        action="Ernährungseintrag speichern",
    ),
    ToolSpec(
        "update_nutrition_entry",
        ATHLETE_RECORDS,
        domain=NUTRITION,
        done="Ernährungseintrag korrigiert",
        action="Ernährungseintrag korrigieren",
    ),
    ToolSpec(
        "delete_nutrition_entry",
        ATHLETE_RECORDS,
        domain=NUTRITION,
        done="Ernährungseintrag entfernt",
        action="Ernährungseintrag entfernen",
        deletes=True,
    ),
    ToolSpec(
        "save_equipment",
        ATHLETE_RECORDS,
        domain=PROFILE,
        done="Ausrüstung lokal gespeichert",
        action="Ausrüstung speichern",
    ),
    ToolSpec(
        "assign_activity_equipment",
        ATHLETE_RECORDS,
        domain=PROFILE,
        done="Ausrüstung zugeordnet",
        action="Ausrüstung zuordnen",
    ),
    ToolSpec(
        "confirm_activity_session",
        ATHLETE_RECORDS,
        domain=PROFILE,
        done="Aufzeichnungen bestätigt",
        action="Aufzeichnungen bestätigen",
    ),
    ToolSpec(
        "split_activity_session",
        ATHLETE_RECORDS,
        domain=PROFILE,
        done="Aufzeichnung getrennt",
        action="Aufzeichnung trennen",
    ),
    ToolSpec(
        "merge_activity_sessions",
        ATHLETE_RECORDS,
        domain=PROFILE,
        done="Aktivitäten zusammengeführt",
        action="Aktivitäten zusammenführen",
    ),
    ToolSpec(
        "log_equipment_maintenance",
        ATHLETE_RECORDS,
        domain=PROFILE,
        done="Wartung lokal erfasst",
        action="Wartung erfassen",
    ),
    ToolSpec(
        "stage_training_plan",
        PLAN_ARTIFACTS,
        domain=PLANNING,
        done="Planentwurf gespeichert",
        action="Planentwurf erstellen",
        no_record=True,
    ),
    ToolSpec(
        "commit_training_plan",
        PLAN_ARTIFACTS,
        domain=PLANNING,
        done="Trainingsplan gespeichert",
        action="Trainingsplan speichern",
        whole_plan=True,
        plan_checked=True,
    ),
    ToolSpec(
        "replace_training_plan",
        PLANNING_CHANGES,
        domain=PLANNING,
        done="Trainingsplan ersetzt",
        action="Trainingsplan vollständig ersetzen",
        whole_plan=True,
        plan_checked=True,
    ),
    ToolSpec(
        "apply_training_changes",
        PLANNING_CHANGES,
        domain=PLANNING,
        done="Geplante Einheiten bearbeitet",
        action="Geplante Einheiten bearbeiten",
        record_lists=("changes",),
        plan_checked=True,
    ),
    ToolSpec(
        "apply_training_patch",
        TRAINING_PATCH,
        domain=PLANNING,
        done="Geplante Einheiten angepasst",
        action="Geplante Einheiten anpassen",
        record_lists=("changes", "workouts"),
        plan_checked=True,
    ),
    ToolSpec(
        "manage_training_templates",
        TEMPLATES,
        domain=PLANNING,
        done="Trainingsvorlagen bearbeitet",
        action="Trainingsvorlagen bearbeiten",
        record_lists=("templates",),
    ),
    ToolSpec(
        "apply_workout_library_plan",
        LIBRARY_PLANS,
        domain=PLANNING,
        done="Vorlagen eingeplant",
        action="Vorlagen einplanen",
        record_lists=("entries",),
        plan_checked=True,
    ),
    ToolSpec(
        "start_provider_refresh",
        SYNC,
        PROVIDER_READ_JOB,
        done="Datenabruf beauftragt",
        action="Datenabruf starten",
    ),
    ToolSpec(
        "start_intervals_plan_sync",
        SYNC,
        REMOTE_WRITE,
        REMOTE_INTERVALS,
        done="Plansynchronisierung beauftragt",
        action="Plan synchronisieren",
    ),
    ToolSpec(
        "push_strength_to_garmin",
        SYNC,
        REMOTE_WRITE,
        REMOTE_GARMIN,
        done="Garmin-Krafteinheiten beauftragt",
        action="Krafteinheiten an Garmin senden",
    ),
    ToolSpec(
        "sync_competitions",
        SYNC,
        REMOTE_WRITE,
        REMOTE_INTERVALS,
        done="Wettkampfsynchronisierung beauftragt",
        action="Wettkämpfe synchronisieren",
    ),
    ToolSpec(
        "resolve_training_sync_conflict",
        SYNC,
        CONDITIONAL_REMOTE_WRITE,
        REMOTE_INTERVALS,
        done="Synchronisierungskonflikt bearbeitet",
        action="Synchronisierungskonflikt bearbeiten",
    ),
    ToolSpec(
        "sync_nutrition",
        SYNC,
        REMOTE_WRITE,
        REMOTE_INTERVALS,
        done="Ernährungssynchronisierung beauftragt",
        action="Ernährung synchronisieren",
    ),
    ToolSpec(
        "preview_adaptive_replan",
        PLANNING_ACTIONS,
        domain=PLANNING,
        done="Plananpassung vorgeschlagen",
        action="Plananpassung vorschlagen",
        no_record=True,
    ),
    ToolSpec(
        "apply_adaptive_replan",
        PLANNING_ACTIONS,
        CONDITIONAL_REMOTE_WRITE,
        # Applying is local; the sync_illness_to_intervals flag adds
        # remote_intervals (write_gate._remote_effect).
        PLANNING,
        done="Freigegebene Plananpassung angewendet",
        action="Freigegebene Plananpassung anwenden",
        no_record=True,
        needs_approval=True,
        plan_checked=True,
        self_guarded=True,
    ),
    ToolSpec(
        "update_training_plan",
        PLANNING_ACTIONS,
        domain=PLANNING,
        done="Planinformationen bearbeitet",
        action="Planinformationen bearbeiten",
    ),
    ToolSpec(
        "undo_training_change",
        PLANNING_ACTIONS,
        domain=UNDO,
        done="Rückgängig-Vorschau vorbereitet",
        action="Rückgängig-Vorschau erstellen",
        mutates_profile=True,
    ),
    ToolSpec("clarify_coach_request", CLARIFICATION, CONTROL),
    ToolSpec("cancel_coach_request", EXECUTION, CONTROL),
)
SPECS = {spec.name: spec for spec in TOOL_SPECS}


def _names(predicate: Callable[[ToolSpec], bool]) -> frozenset[str]:
    return frozenset(spec.name for spec in TOOL_SPECS if predicate(spec))


READ_ONLY_TOOLS = _names(lambda spec: spec.effect == READ)
CONTROL_TOOLS = _names(lambda spec: spec.effect == CONTROL)
PROVIDER_READ_JOB_TOOLS = _names(lambda spec: spec.effect == PROVIDER_READ_JOB)
REMOTE_WRITE_TOOLS = _names(lambda spec: spec.effect == REMOTE_WRITE)
CONDITIONAL_REMOTE_WRITE_TOOLS = _names(
    lambda spec: spec.effect == CONDITIONAL_REMOTE_WRITE
)
UNGATED_TOOLS = CONTROL_TOOLS | PROVIDER_READ_JOB_TOOLS
TOOL_DOMAIN = {spec.name: spec.domain for spec in TOOL_SPECS if spec.domain}
DELETE_TOOLS = _names(lambda spec: spec.deletes)
WHOLE_PLAN_TOOLS = _names(lambda spec: spec.whole_plan)
NO_RECORD_TOOLS = _names(lambda spec: spec.no_record)
RECORD_LISTS = {
    spec.name: spec.record_lists for spec in TOOL_SPECS if spec.record_lists
}
APPROVAL_TOOLS = _names(lambda spec: spec.needs_approval)
PLAN_CHECKED_TOOLS = _names(lambda spec: spec.plan_checked)
SELF_GUARDED_TOOLS = _names(lambda spec: spec.self_guarded)
PROFILE_MUTATING_TOOLS = _names(lambda spec: spec.mutates_profile)
EXTERNAL_FOOD_LOOKUP_TOOLS = _names(lambda spec: spec.external_food_lookup)
SYNC_TOOL_NAMES = _names(lambda spec: spec.owner == SYNC)
OPERATION_LABELS = {spec.name: spec.done for spec in TOOL_SPECS if spec.done}
ACTION_LABELS = {spec.name: spec.action for spec in TOOL_SPECS if spec.action}
