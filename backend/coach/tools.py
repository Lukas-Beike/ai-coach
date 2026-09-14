"""Canonical Coach tool schemas and inventory."""

from __future__ import annotations

from typing import Any, Callable


def build_tool_contracts(
    *,
    default_profile: dict[str, Any],
    checkin_text_limits: dict[str, int],
    checkin_score_fields: tuple[str, ...],
    training_change_limit: int,
    library_bulk_max_entries: int,
    training_plan_statuses: Any,
    dialogue_tools: Callable[..., list[dict[str, Any]]],
):
    COACH_TRAINING_CHANGE_LIMIT = training_change_limit
    LIBRARY_BULK_MAX_ENTRIES = library_bulk_max_entries
    DEFAULT_PROFILE = default_profile
    CHECKIN_TEXT_LIMITS = checkin_text_limits
    CHECKIN_SCORE_FIELDS = checkin_score_fields
    TRAINING_PLAN_STATUSES = training_plan_statuses

    COACH_CANONICAL_TOOL_NAMES = (
        "read_profile",
        "update_profile",
        "read_training_state",
        "list_recent_activities",
        "get_activity_details",
        "list_workout_library",
        "list_planned_workouts",
        "list_change_history",
        "list_competitions",
        "list_training_plans",
        "stage_training_plan",
        "commit_training_plan",
        "replace_training_plan",
        "apply_training_changes",
        "manage_training_templates",
        "save_checkin",
        "save_activity_feedback",
        "delete_activity_feedback",
        "save_competition",
        "delete_competition",
        "start_provider_refresh",
        "refresh_current_performance",
        "start_intervals_plan_sync",
        "sync_competitions",
        "get_sync_job",
        "resolve_training_sync_conflict",
        "preview_adaptive_replan",
        "apply_adaptive_replan",
        "update_training_plan",
        "undo_training_change",
        "apply_workout_library_plan",
    )
    
    
    def _canonical_coach_tool(
        name: str,
        description: str,
        properties: dict[str, Any] | None = None,
        *,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Declare a focused schema for one structured Coach operation.
    
        Read-only tools with no arguments are strict. Mutable tools retain
        optional fields where the operation supports partial updates, but no
        longer receive every unrelated Coach parameter.
        """
        return {
            "type": "function",
            "name": name,
            "description": description,
            "strict": strict or not bool(properties),
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": list(properties or {}) if strict else [],
                "additionalProperties": False,
            },
        }
    
    
    COACH_STRUCTURED_TOOLS = [
        _canonical_coach_tool("read_profile", "Read the current durable athlete profile before making a partial profile update."),
        _canonical_coach_tool("update_profile", "Save explicitly requested permanent athlete facts or preferences. Read the profile first; change only named fields, preserving existing text when adding facts. Temporary planning constraints belong to the plan or check-in.", {
            "changes": {"type": "array", "minItems": 1, "maxItems": len(DEFAULT_PROFILE), "items": {
                "type": "object", "additionalProperties": False, "required": ["field", "expected_value", "value"],
                "properties": {"field": {"type": "string", "enum": list(DEFAULT_PROFILE)},
                               "expected_value": {"type": "string", "maxLength": 4000},
                               "value": {"type": "string", "maxLength": 4000}},
            }},
        }, strict=True),
        _canonical_coach_tool("read_training_state", "Read current local training references. For full repair include inactive entries and follow planned_units_page.next_cursor until has_more is false BEFORE editing or syncing. A changed planning revision invalidates the cursor; restart enumeration in that case.", {"include_inactive": {"type": "boolean"}, "cursor": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": COACH_TRAINING_CHANGE_LIMIT}}),
        _canonical_coach_tool("list_recent_activities", "Read completed activities from the latest local snapshot without refreshing a provider.", {"days": {"type": "integer"}, "limit": {"type": "integer"}}),
        _canonical_coach_tool("get_activity_details", "Read a bounded, sanitized detailed analysis projection for exactly one completed Intervals.icu activity from the local snapshot. Use only after an explicit request to analyse or deeply review that one activity; resolve its exact activity ID with list_recent_activities first when needed. Never use this for generic activity summaries or all past activities.", {"activity_id": {"type": "string", "minLength": 1, "maxLength": 200}}, strict=True),
        _canonical_coach_tool("list_workout_library", "Read saved local training templates; local library data is authoritative.", {"limit": {"type": "integer"}, "include_archived": {"type": "boolean"}}),
        _canonical_coach_tool("list_planned_workouts", "Read future locally scheduled workouts.", {"limit": {"type": "integer"}}),
        _canonical_coach_tool("list_change_history", "Read local change-history references that can be used to request an undo preview.", {"limit": {"type": "integer"}}),
        _canonical_coach_tool("list_competitions", "Read locally stored target competitions."),
        _canonical_coach_tool("list_training_plans", "Read locally stored training-plan metadata."),
        _canonical_coach_tool("stage_training_plan", "Store a complete local training-plan draft. Include only future workouts, no rest-day placeholders or already completed activities. At most one workout per date; respect existing calendar conflicts. Correct rejected arguments before committing. Never writes remotely.", {"payload": {
            "type": "object", "additionalProperties": False,
            "required": ["plan_name", "goal", "workouts"],
            "properties": {
                "plan_name": {"type": "string"},
                "goal": {"type": "string"},
                "workouts": {
                    "type": "array", "minItems": 1, "maxItems": 366,
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["date", "sport", "name", "description", "duration_minutes", "target", "rationale"],
                        "properties": {
                            "date": {"type": "string", "description": "Local workout date in YYYY-MM-DD format; plan span at most 730 days."},
                            "sport": {"type": "string", "description": "Sport, e.g. Ride, VirtualRide, Run, Swim or WeightTraining."},
                            "name": {"type": "string"},
                            "description": {"type": "string", "minLength": 1, "description": "Workout instructions, including intervals or strength exercises as appropriate."},
                            "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 600},
                            "target": {"type": "string", "enum": ["AUTO", "POWER", "HR", "PACE"]},
                            "rationale": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        }}, strict=True),
        _canonical_coach_tool("commit_training_plan", "Commit a referenced local training-plan artifact atomically.", {"artifact_id": {"type": "string"}}),
        _canonical_coach_tool(
            "replace_training_plan",
            "Atomically replace local Coach/library plan units within the requested period. Use the planning revision returned by read_training_state. "
            "This operation may create, update, and archive a different number of sessions and never writes remotely.",
            {
                "payload": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["plan_name", "goal", "workouts"],
                    "properties": {
                        "plan_name": {"type": "string", "minLength": 1},
                        "goal": {"type": "string"},
                        "workouts": {
                            "type": "array", "minItems": 1, "maxItems": 366,
                            "items": {
                                "type": "object", "additionalProperties": False,
                                "required": ["date", "sport", "name", "description", "duration_minutes", "target", "rationale"],
                                "properties": {
                                    "date": {"type": "string", "description": "Local workout date in YYYY-MM-DD format."},
                                    "sport": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string", "minLength": 1},
                                    "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 600},
                                    "target": {"type": "string", "enum": ["AUTO", "POWER", "HR", "PACE"]},
                                    "rationale": {"type": "string", "minLength": 1},
                                },
                            },
                        },
                    },
                },
                "expected_revision": {"type": "integer"},
            },
            strict=True,
        ),
        _canonical_coach_tool("apply_training_changes", "Apply an explicitly authorized set of local training changes atomically. For a complete-plan edit, always include the planning_revision from read_training_state and expected_payload_hash on every change.", {"changes": {"type": "array", "minItems": 1, "maxItems": COACH_TRAINING_CHANGE_LIMIT, "description": "For complete-plan edits, include the expected_payload_hash returned for every local_id.", "items": {"type": "object", "properties": {"local_id": {"type": "string"}, "action": {"type": "string", "enum": ["update", "archive", "restore", "delete"], "description": "Moving a workout uses update with its new date."}, "date": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}, "duration_minutes": {"type": "integer"}, "target": {"type": "string"}, "type": {"type": "string"}, "sport": {"type": "string"}, "expected_payload_hash": {"type": "string"}}}}, "expected_revision": {"type": "integer", "description": "Required for complete-plan edits; use planning_revision from read_training_state."}}),
        _canonical_coach_tool("manage_training_templates", "Create, update, archive, restore, or delete undated local templates. Resolve local_id with list_workout_library for edits; creation requires name and workout description. Scheduling is a separate local action.", {"templates": {"type": "array", "minItems": 1, "maxItems": 28, "items": {
            "type": "object", "additionalProperties": False, "required": ["action"], "properties": {
                "action": {"type": "string", "enum": ["create", "update", "archive", "restore", "delete"]},
                "local_id": {"type": "string", "format": "uuid"}, "name": {"type": "string"},
                "description": {"type": "string"}, "sport": {"type": "string", "enum": ["Ride", "VirtualRide", "Run", "Swim", "WeightTraining"]},
                "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 1440},
                "target": {"type": "string", "enum": ["AUTO", "POWER", "HR", "PACE"]},
            },
        }}}),
        _canonical_coach_tool("apply_workout_library_plan", "Schedule saved templates locally after conflict checks. Resolve the template ID from list_workout_library. Never writes remotely.", {"entries": {"type": "array", "minItems": 1, "maxItems": 14, "items": {
            "type": "object", "additionalProperties": False, "required": ["library_workout_id", "date"],
            "properties": {"library_workout_id": {"type": "string", "format": "uuid"}, "date": {"type": "string", "format": "date"}},
        }}}),
        _canonical_coach_tool("save_checkin", "Save explicitly stated daily condition, illness, pain or availability. Omit unknown fields; scores are 0-10. checkin_date defaults to the athlete-local today and cannot be in the future. Empty fields preserve existing feedback.", {"payload": {
            "type": "object", "additionalProperties": False, "properties": {
                "checkin_date": {"type": "string", "format": "date"},
                **{field: {"type": "string", "maxLength": limit} for field, limit in CHECKIN_TEXT_LIMITS.items()},
                **{field: {"type": ["integer", "null"], "minimum": 0, "maximum": 10} for field in CHECKIN_SCORE_FIELDS},
                "available_minutes": {"type": ["integer", "null"], "minimum": 0, "maximum": 1440},
            },
        }}),
        _canonical_coach_tool("save_activity_feedback", "Save the athlete's explicitly stated observations about an existing completed activity. Resolve its exact ID from the local snapshot or list_recent_activities first. Never invent an activity ID or observations. This tool cannot create completed activities.", {"payload": {
            "type": "object", "additionalProperties": False,
            "required": ["activity_id", "activity_name", "activity_date", "notes"],
            "properties": {
                "activity_id": {"type": "string", "minLength": 1, "description": "Exact existing activity ID from the current local snapshot."},
                "activity_name": {"type": ["string", "null"]},
                "activity_date": {"type": ["string", "null"]},
                "notes": {"type": "string", "minLength": 1, "description": "Only observations explicitly stated by the athlete."},
            },
        }}, strict=True),
        _canonical_coach_tool("delete_activity_feedback", "Delete the local feedback record for one completed activity.", {"activity_id": {"type": "string"}}),
        _canonical_coach_tool("save_competition", "Create or update one local target competition. Creation needs name, event_date and sport; for edits use competition_id from list_competitions and only changed fields. This does not push to Intervals.icu.", {"payload": {
            "type": "object", "additionalProperties": False, "properties": {
                "competition_id": {"type": "string", "format": "uuid"},
                **{field: {"type": "string"} for field in ("name", "event_date", "start_date_local", "sport", "distance", "target", "course_profile", "notes", "description")},
                "priority": {"type": "string", "enum": ["A", "B", "C"]},
                "moving_time_seconds": {"type": ["integer", "null"], "minimum": 0},
            },
        }}),
        _canonical_coach_tool("delete_competition", "Delete one locally stored target competition.", {"competition_id": {"type": "string"}}),
        _canonical_coach_tool("start_provider_refresh", "Queue an explicitly requested read-only provider refresh.", {"days": {"type": "integer"}, "reason": {"type": "string"}}),
        _canonical_coach_tool("refresh_current_performance", "Queue an explicit Intervals.icu performance-metrics refresh without reloading activities.", {"reason": {"type": "string"}}),
        _canonical_coach_tool("start_intervals_plan_sync", "Queue an explicitly requested Intervals.icu push. For repair use repair=true, the current expected_revision, local_plan scope and no entries: the server selects the complete requested period, including already-synced and inactive units. First correct local workout text and sport. Repair verifies the remote calendar and removes only exact identity duplicates. An explicit repair selection must cover the entire period. For ordinary selected entries copy local_id and expected_payload_hash from read_training_state into library_workout_id and expected_payload_hash. For all_pending or created omit entries; the server resolves them. A follow-up sync of previously saved workouts uses selected or all_pending; created only refers to additions in THIS turn.", {"entries": {"type": "array", "minItems": 1, "maxItems": LIBRARY_BULK_MAX_ENTRIES, "items": {
            "type": "object", "additionalProperties": False, "required": ["library_workout_id", "expected_payload_hash"],
            "properties": {"library_workout_id": {"type": "string", "format": "uuid", "description": "Exact local_id of a planned unit, never a remote event ID or a scope token."},
                           "expected_payload_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
        }}, "reason": {"type": "string"}, "expected_revision": {"type": "integer", "description": "For complete-period repair omit entries, authorize local_plan and pass planning_revision from read_training_state. The server resolves every active and inactive unit and chunks the complete manifest."}, "repair": {"type": "boolean", "description": "Reconcile the complete requested future period; requires an explicit repair/resync request. An explicit entries selection must cover the entire period."}}),
        _canonical_coach_tool("sync_competitions", "Queue an explicitly requested push of local target competitions to Intervals.icu.", {"reason": {"type": "string"}}),
        _canonical_coach_tool("get_sync_job", "Read one local synchronization job.", {"job_id": {"type": "string"}}),
        _canonical_coach_tool("resolve_training_sync_conflict", "Resolve a local conflict using local_id and strategy (keep_local or adopt_remote), with local target. Or retry a failed/partial job using only job_id: read get_sync_job first, use its provider target, and include sync_job:<id> plus intervals_sync for pushes (remote_write=true) or <provider>_refresh for reads.", {"local_id": {"type": "string"}, "job_id": {"type": "string"}, "strategy": {"type": "string", "enum": ["keep_local", "adopt_remote"]}}),
        _canonical_coach_tool("preview_adaptive_replan", "Calculate a local adaptive planning preview without changing workouts."),
        _canonical_coach_tool("apply_adaptive_replan", "Apply the latest adaptive planning preview after explicit Coach approval.", {"adjustment_id": {"type": "string"}, "sync_illness_to_intervals": {"type": "boolean"}}),
        _canonical_coach_tool("update_training_plan", "Update or delete metadata for a plan resolved by list_training_plans. Deletion removes only the plan metadata; scheduled workouts remain. Use apply_training_patch for workout changes.", {"payload": {
            "type": "object", "additionalProperties": False, "required": ["plan_id"], "properties": {
                "plan_id": {"type": "string", "format": "uuid"}, "action": {"type": "string", "enum": ["update", "delete"]},
                **{field: {"type": "string"} for field in ("name", "goal", "start_date", "end_date")},
                "status": {"type": "string", "enum": sorted(TRAINING_PLAN_STATUSES)},
            },
        }}),
        _canonical_coach_tool("undo_training_change", "Return an undo preview for a local change; do not apply it silently.", {"change_id": {"type": "string"}}),
    ]
    
    
    STRUCTURED_READ_ONLY_TOOLS = {
        "read_profile",
        "read_training_state", "list_recent_activities", "get_activity_details", "list_workout_library", "list_planned_workouts",
        "list_change_history", "list_competitions", "list_training_plans", "get_sync_job",
    }
    
    
    COACH_DIALOGUE_TOOLS = dialogue_tools(
        [tool for tool in COACH_STRUCTURED_TOOLS if tool["name"] != "apply_training_changes"],
        STRUCTURED_READ_ONLY_TOOLS,
    )
    _patch_properties = {
        "changes": next(tool for tool in COACH_STRUCTURED_TOOLS if tool["name"] == "apply_training_changes")["parameters"]["properties"]["changes"],
        "workouts": next(tool for tool in COACH_STRUCTURED_TOOLS if tool["name"] == "stage_training_plan")["parameters"]["properties"]["payload"]["properties"]["workouts"],
        "expected_revision": {"type": "integer"}, "plan_name": {"type": "string"}, "goal": {"type": "string"},
    }
    _patch_properties["changes"] = {**_patch_properties["changes"], "minItems": 0}
    _patch_properties["workouts"] = {**_patch_properties["workouts"], "minItems": 0}
    COACH_DIALOGUE_TOOLS.extend(dialogue_tools([
        _canonical_coach_tool("apply_training_patch", "Apply related moves, edits, deletions and additions in one atomic local change. Read revision and per-unit hashes first. Existing objects keep their IDs. No remote writes.", _patch_properties),
    ], STRUCTURED_READ_ONLY_TOOLS))
    COACH_DIALOGUE_TOOLS.extend([
        _canonical_coach_tool("clarify_coach_request", "Keep the current request and its constraints for a concrete clarification. Source IDs refer to user messages; summary includes all unresolved requirements.", {
            "source_message_ids": {"type": "array", "items": {"type": "integer"}, "maxItems": 24},
            "summary": {"type": "string"}, "question": {"type": "string"},
        }, strict=True),
        _canonical_coach_tool("cancel_coach_request", "Close the pending request when the athlete cancels it; completed effects remain recorded."),
        _canonical_coach_tool("inspect_activity_duplicates", "Inspect the latest cycling activity for duplicate Wahoo/Garmin recordings. Prefer Wahoo for analysis. A returned removal preview still requires the athlete's explicit confirmation; this tool never deletes remotely."),
    ])
    STRUCTURED_READ_ONLY_TOOLS.add("inspect_activity_duplicates")
    

    return COACH_CANONICAL_TOOL_NAMES, COACH_STRUCTURED_TOOLS, STRUCTURED_READ_ONLY_TOOLS, COACH_DIALOGUE_TOOLS

