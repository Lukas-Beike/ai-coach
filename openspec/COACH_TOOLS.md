# Coach tool to specification requirement map

One row per Coach tool. The table is generated from the tool specs
(`backend/coach/tool_specs.py`: owner, effect, gate domain and the requirements
each tool serves), the capability catalog (`backend/coach/capabilities.py`:
surface) and the `covers` declarations of `tests/test_coach_tool_coverage.py`
(scenario tests). A test fails when a referenced requirement no longer exists in
`openspec/specs`. Regenerate the table with
`python tests/test_coach_tool_coverage.py --write`.

The owner is the Coach tool service the dispatch calls; it may delegate further.
Every row also inherits CA1 catalog ownership and, where they apply, the CA2,
CA7 and CA8 execution boundaries. Schemas come from
`backend/coach/tool_schemas.py:build_structured_tool_schemas` and
`backend/coach/tool_registry.py:build_tool_contracts`; dispatch runs through
`backend/coach/tool_execution_service.py` and `backend/coach/tool_dispatch.py`.
`apply_training_changes` is offered only to the canonical (non-dialogue) surface,
so it has no scenario in the coverage matrix; its success case is
`tests/test_planning_change_service.py:test_mixed_batch_derives_plan_preserves_order_and_projects_deduplicated_result`.
Nutrition tools are mapped here for Coach authority only; food, diary and
product semantics belong to the nutrition capability specs, and provider payload
and repair details remain with the provider capabilities.

<!-- BEGIN GENERATED TOOL TABLE -->
| Tool | Surface / effect | Gate domain | Owner | Requirements | Scenario tests |
| --- | --- | --- | --- | --- | --- |
| `apply_adaptive_replan` | canonical_and_dialogue / conditional_remote_write | planning | CoachPlanningActionToolService | `training-plans-and-adaptation / TP9 Separate approval of the latest published adaptive preview`; `training-plans-and-adaptation / TP10 Adaptive stale-state protection and repeat behavior`; `training-plans-and-adaptation / TP11 Illness pause local records and optional remote sync`; `coach-tool-authority / CA6 Session-bound immutable approval contents` | `test_adaptive_preview_requires_later_acceptance_before_changing_workout`, `test_illness_sync_requires_explicit_remote_acceptance_after_preview` |
| `apply_training_changes` | canonical_only / local_write | planning | CoachPlanningChangeToolService | `training-plans-and-adaptation / TP5 Atomic scoped training changes and patches`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` |  |
| `apply_training_patch` | dialogue_only / local_write | planning | CoachTrainingPatchService | `training-plans-and-adaptation / TP5 Atomic scoped training changes and patches`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_planned_unit_lifecycle_keeps_identity_until_deleted` |
| `apply_workout_library_plan` | canonical_and_dialogue / local_write | planning | CoachLibraryPlanToolService | `training-library / TL3 Independent local scheduling from the library`; `training-library / TL4 Calendar-constrained local planning` | `test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy` |
| `assign_activity_equipment` | canonical_and_dialogue / local_write | profile | CoachAthleteRecordToolService | `athlete-profile-and-checkins / AP9 Explicit equipment assignments and honest usage`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `calculate_food_nutrition` | canonical_and_dialogue / read | read | CoachReadToolService | `coach-tool-authority / CA1 Complete owned tool capability catalog`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_food_database_read_tools_calculate_without_writing` |
| `cancel_coach_request` | dialogue_only / control | ungated | CoachStructuredToolExecutionService | `coach-conversation / CC6 Persisted clarification and conversational continuation`; `coach-tool-authority / CA8 Bounded execution and cancellation boundaries` | `test_clarification_and_cancellation_preserve_athlete_data` |
| `clarify_coach_request` | dialogue_only / control | ungated | CoachClarificationService | `coach-conversation / CC6 Persisted clarification and conversational continuation`; `coach-tool-authority / CA8 Bounded execution and cancellation boundaries` | `test_clarification_and_cancellation_preserve_athlete_data` |
| `commit_training_plan` | canonical_and_dialogue / local_write | planning | CoachPlanArtifactToolService | `training-plans-and-adaptation / TP2 Atomic revision-checked plan commit`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_requested_draft_commit_and_metadata_lifecycle` |
| `confirm_activity_session` | canonical_and_dialogue / local_write | profile | CoachAthleteRecordToolService | `activity-ingestion-and-storage / Athlete session corrections`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_session_tools_correct_the_bundle_and_leave_a_change_receipt` |
| `delete_activity_feedback` | canonical_and_dialogue / local_write | checkin | CoachAthleteRecordToolService | `athlete-profile-and-checkins / AP7 Exact completed-activity feedback`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `delete_competition` | canonical_and_dialogue / local_write | competition | CoachAthleteRecordToolService | `competitions-and-seasons / CS4 Competition removal and remote tombstone retention`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `delete_nutrition_entry` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_nutrition_entries_can_be_saved_read_and_deleted` |
| `delete_nutrition_template` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_saved_meals_run_through_authorized_coach_and_receipts` |
| `fill_nutrition_product_gaps` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `food-catalog-and-meal-library / Coach fills empty product fields`; `coach-tool-authority / Tool-specific bulk threshold`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_incomplete_products_are_listed_and_filled_by_authorized_coach_turn` |
| `get_activity_details` | canonical_and_dialogue / read | read | CoachReadToolService | `coach-context-and-provenance / CP7 Bounded local reads and analysis parity` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `get_sync_job` | canonical_and_dialogue / read | read | CoachSyncToolService | `coach-context-and-provenance / CP6 Explicit provider refresh and current results` | `test_provider_reads_and_job_status_use_correct_provider` |
| `get_training_report` | canonical_and_dialogue / read | read | CoachReadToolService | `coach-context-and-provenance / CP7 Bounded local reads and analysis parity`; `competitions-and-seasons / CS7 Observed competition preparation with explicit unknowns` | `test_training_report_returns_same_local_facts_without_mutation` |
| `list_change_history` | canonical_and_dialogue / read | read | CoachReadToolService | `change-history-and-undo / HU2 Retention and private public history` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_competitions` | canonical_and_dialogue / read | read | CoachReadToolService | `competitions-and-seasons / CS2 Local competition create and partial edit`; `coach-context-and-provenance / CP1 Durable local athlete authority` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_incomplete_nutrition_products` | canonical_and_dialogue / read | read | CoachReadToolService | `food-catalog-and-meal-library / Coach fills empty product fields`; `coach-tool-authority / CA1 Complete owned tool capability catalog` | `test_incomplete_products_are_listed_and_filled_by_authorized_coach_turn` |
| `list_planned_workouts` | canonical_and_dialogue / read | read | CoachReadToolService | `training-library / TL5 Stable dated planned-unit edits and soft deletion`; `training-library / TL6 Bounded library browsing and revision-bound plan enumeration` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_recent_activities` | canonical_and_dialogue / read | read | CoachReadToolService | `coach-context-and-provenance / CP7 Bounded local reads and analysis parity` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_training_plans` | canonical_and_dialogue / read | read | CoachReadToolService | `training-plans-and-adaptation / TP4 Plan membership, metadata and persistent constraints` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_workout_library` | canonical_and_dialogue / read | read | CoachReadToolService | `training-library / TL6 Bounded library browsing and revision-bound plan enumeration` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `log_equipment_maintenance` | canonical_and_dialogue / local_write | profile | CoachAthleteRecordToolService | `athlete-profile-and-checkins / AP10 Maintenance events without invented material diagnosis`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `log_nutrition_template` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope`; `coach-tool-authority / CA9 Truthful durable receipts and supported undo` | `test_saved_meals_run_through_authorized_coach_and_receipts` |
| `lookup_food` | canonical_and_dialogue / read | read | CoachReadToolService | `coach-tool-authority / CA1 Complete owned tool capability catalog`; `coach-context-and-provenance / CP8 External text is evidence only` | `test_food_database_read_tools_calculate_without_writing` |
| `manage_training_templates` | canonical_and_dialogue / local_write | planning | TrainingTemplateToolService | `training-library / TL1 Undated local training templates`; `training-library / TL2 Atomic template lifecycle`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy` |
| `merge_activity_sessions` | canonical_and_dialogue / local_write | profile | CoachAthleteRecordToolService | `activity-ingestion-and-storage / Athlete session corrections`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_session_tools_correct_the_bundle_and_leave_a_change_receipt` |
| `preview_adaptive_replan` | canonical_and_dialogue / local_write | planning | CoachPlanningActionToolService | `training-plans-and-adaptation / TP8 Persisted adaptive previews with trigger evidence` | `test_adaptive_preview_requires_later_acceptance_before_changing_workout` |
| `push_strength_to_garmin` | canonical_and_dialogue / remote_write | remote_garmin | CoachSyncToolService | `garmin-strength-workout-push / Explicit Garmin strength push`; `coach-tool-authority / CA5 Named remote synchronization and explicit proposals` | `test_garmin_strength_push_is_bound_to_the_stored_units` |
| `read_coach_context` | canonical_and_dialogue / read | read | CoachReadToolService | `coach-context-and-provenance / CP4 On-demand omitted context` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `read_nutrition` | canonical_and_dialogue / read | read | CoachReadToolService | `coach-tool-authority / CA1 Complete owned tool capability catalog`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_nutrition_entries_can_be_saved_read_and_deleted`, `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `read_profile` | canonical_and_dialogue / read | read | CoachReadToolService | `athlete-profile-and-checkins / AP1 Normalized durable profile and athlete-local dates`; `athlete-profile-and-checkins / AP2 Partial profile edits and optimistic Coach conflicts` | `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` |
| `read_training_records` | canonical_and_dialogue / read | read | CoachReadToolService | `athlete-profile-and-checkins / AP8 Versioned local equipment records`; `athlete-profile-and-checkins / AP9 Explicit equipment assignments and honest usage`; `athlete-profile-and-checkins / AP10 Maintenance events without invented material diagnosis` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `read_training_state` | canonical_and_dialogue / read | read | CoachReadToolService | `training-library / TL6 Bounded library browsing and revision-bound plan enumeration` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `replace_training_plan` | canonical_and_dialogue / local_write | planning | CoachPlanningChangeToolService | `training-plans-and-adaptation / TP6 Inclusive bounded local plan replacement`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_replacement_changes_only_requested_period` |
| `resolve_training_sync_conflict` | canonical_and_dialogue / conditional_remote_write | remote_intervals | CoachSyncToolService | `training-library / TL10 Exact explicit sync selection and complete repair manifests`; `coach-tool-authority / CA5 Named remote synchronization and explicit proposals` | `test_conflict_choices_and_failed_job_retries` |
| `save_activity_feedback` | canonical_and_dialogue / local_write | checkin | CoachAthleteRecordToolService | `athlete-profile-and-checkins / AP7 Exact completed-activity feedback` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `save_checkin` | canonical_and_dialogue / local_write | checkin | CoachAthleteRecordToolService | `athlete-profile-and-checkins / AP4 Validated daily subjective check-ins`; `athlete-profile-and-checkins / AP5 Coach check-in merging and explicit clearing`; `athlete-profile-and-checkins / AP6 Explicit day status, tags and durable check-in saves` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `save_competition` | canonical_and_dialogue / local_write | competition | CoachAthleteRecordToolService | `competitions-and-seasons / CS1 Validated target-competition records`; `competitions-and-seasons / CS2 Local competition create and partial edit` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `save_equipment` | canonical_and_dialogue / local_write | profile | CoachAthleteRecordToolService | `athlete-profile-and-checkins / AP8 Versioned local equipment records`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `save_nutrition_entry` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope`; `coach-tool-authority / CA3 Direct local writes with impact checks`; `coach-tool-authority / CA9 Truthful durable receipts and supported undo` | `test_nutrition_entries_can_be_saved_read_and_deleted` |
| `save_nutrition_product` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `coach-tool-authority / CA6 Session-bound immutable approval contents`; `coach-tool-authority / CA10 Validated repair dependencies and exceptional approvals` | `test_confirmed_product_is_saved_locally_through_authorized_coach_receipt` |
| `save_nutrition_template` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `coach-tool-authority / CA6 Session-bound immutable approval contents`; `coach-tool-authority / CA10 Validated repair dependencies and exceptional approvals` | `test_saved_meals_run_through_authorized_coach_and_receipts` |
| `search_web_for_product_values` | canonical_and_dialogue / read | read | CoachReadToolService | `food-catalog-and-meal-library / Coach web search for missing product values`; `coach-tool-authority / CA1 Complete owned tool capability catalog` | `test_web_search_returns_cited_values_and_degrades_to_unavailable` |
| `split_activity_session` | canonical_and_dialogue / local_write | profile | CoachAthleteRecordToolService | `activity-ingestion-and-storage / Athlete session corrections`; `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope` | `test_session_tools_correct_the_bundle_and_leave_a_change_receipt` |
| `stage_training_plan` | canonical_and_dialogue / local_write | planning | CoachPlanArtifactToolService | `training-plans-and-adaptation / TP1 Validated durable local plan drafts` | `test_requested_draft_commit_and_metadata_lifecycle` |
| `start_intervals_plan_sync` | canonical_and_dialogue / remote_write | remote_intervals | CoachSyncToolService | `training-library / TL10 Exact explicit sync selection and complete repair manifests`; `training-library / TL11 Planned-calendar upsert identity and in-flight local changes`; `training-library / TL12 Guarded explicit removal of a linked planned event`; `training-library / TL13 Exact repair ownership and bounded duplicate cleanup`; `training-library / TL14 Repair identity retention and final collection verification`; `training-library / TL15 Selected execution reports mixed outcomes and failed-object retry scope`; `coach-tool-authority / CA5 Named remote synchronization and explicit proposals`; `coach-tool-authority / CA6 Session-bound immutable approval contents` | `test_new_plan_sync_and_later_selected_sync_use_real_ids` |
| `start_provider_refresh` | canonical_and_dialogue / provider_read_job | ungated | CoachSyncToolService | `coach-context-and-provenance / CP6 Explicit provider refresh and current results` | `test_provider_reads_and_job_status_use_correct_provider` |
| `sync_competitions` | canonical_and_dialogue / remote_write | remote_intervals | CoachSyncToolService | `competitions-and-seasons / CS5 Explicit competition sync and conflict recovery`; `coach-tool-authority / CA5 Named remote synchronization and explicit proposals`; `coach-tool-authority / CA6 Session-bound immutable approval contents` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `sync_nutrition` | canonical_and_dialogue / remote_write | remote_intervals | CoachSyncToolService | `coach-tool-authority / CA5 Named remote synchronization and explicit proposals`; `coach-tool-authority / CA6 Session-bound immutable approval contents` | `test_nutrition_correction_preserves_fields_and_sync_is_explicitly_queued` |
| `undo_training_change` | canonical_and_dialogue / local_write | undo | CoachPlanningActionToolService | `change-history-and-undo / HU3 Read-only undo previews bound to current state`; `change-history-and-undo / HU4 Atomic hash-checked domain restore`; `change-history-and-undo / HU6 Scoped Coach undo and explicit proposal path` | `test_undo_is_a_bound_preview_until_explicit_confirmation` |
| `update_nutrition_entry` | canonical_and_dialogue / local_write | nutrition | CoachAthleteRecordToolService | `coach-tool-authority / CA2 Athlete-message provenance and exact effect scope`; `coach-tool-authority / CA3 Direct local writes with impact checks` | `test_nutrition_correction_preserves_fields_and_sync_is_explicitly_queued` |
| `update_profile` | canonical_and_dialogue / local_write | profile | CoachProfileUpdateService | `athlete-profile-and-checkins / AP2 Partial profile edits and optimistic Coach conflicts` | `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` |
| `update_training_plan` | canonical_and_dialogue / local_write | planning | CoachPlanningActionToolService | `training-plans-and-adaptation / TP4 Plan membership, metadata and persistent constraints`; `coach-tool-authority / CA4 Domain-confirmed destructive and bulk effects` | `test_requested_draft_commit_and_metadata_lifecycle` |
<!-- END GENERATED TOOL TABLE -->

## Tool contracts

Per tool: the parameters the model receives (`*` required; dotted paths for
nested fields, `[]` for list items), from the schemas of
`backend/coach/tool_schemas.py` and `backend/coach/authorization.py`, and the
gate facts, receipt label, proposal card and turn undo from
`backend/coach/tool_specs.py` and `backend/coach/change_receipts.py`. A tool
`fully tracked by change history` writes only change-history records, so a
turn made only of such tools, each with a recorded change, can be undone as a
whole. The checks the request validator runs
beyond the schema are specified in `coach-tool-authority`. Generated by
`python tests/test_coach_tool_coverage.py --write`.

<!-- BEGIN GENERATED TOOL CONTRACTS -->
### `_request` envelope

Every dialogue tool marked `_request`* below requires this object:

- `summary`* (string; ≤2000 chars)
- `source_message_ids`* (array of integer; ≥1 items; ≤24 items)
- `target`* (string; one of `"local"`, `"intervals"`, `"garmin"`, `"calendar"`, `"weather"`, `"wahoo"`)
- `scope`* (array of string; ≤400 items)
- `period`* (object/null)
- `period.start`* (string)
- `period.end`* (string)
- `constraints`* (array of string; ≤24 items)
- `remote_write`* (boolean)
- `sync_scope`* (string/null; one of `"created"`, `"selected"`, `"all_pending"`, `null`)

### `apply_adaptive_replan`

effect `conditional_remote_write`; gate domain `planning`; counts no records toward the bulk check; applies only an approved preview; plan checked; plan check inside the tool; receipt „Freigegebene Plananpassung angewendet“; proposal card „Freigegebene Plananpassung anwenden“; not fully tracked (no turn undo).

- `adjustment_id` (string)
- `sync_illness_to_intervals` (boolean)
- `accept_plan_findings` (array of string; ≤1 items; each one of `"illness_hard"`)
- `_request`* (the envelope above)

### `apply_training_changes`

effect `local_write`; gate domain `planning`; plan checked; records counted from `changes`; receipt „Geplante Einheiten bearbeitet“; proposal card „Geplante Einheiten bearbeiten“; not fully tracked (no turn undo).

- `accept_plan_findings` (array of string; ≤1 items; each one of `"illness_hard"`)
- `changes` (array; ≥1 items; ≤366 items)
- `changes[].local_id` (string)
- `changes[].action` (string; one of `"update"`, `"archive"`, `"restore"`, `"delete"`)
- `changes[].date` (string)
- `changes[].starts_at_local` (string)
- `changes[].name` (string)
- `changes[].description` (string)
- `changes[].duration_minutes` (integer)
- `changes[].target` (string)
- `changes[].type` (string)
- `changes[].sport` (string)
- `changes[].expected_payload_hash` (string)
- `changes[].plan_id` (string)
- `changes[].rationale` (string)
- `changes[].environment` (string)
- `changes[].sport_detail` (string)
- `changes[].session_focus` (string/null; one of `"recovery"`, `"easy"`, `"endurance"`, `"long"`, `"tempo"`, `"threshold"`, `"sweet_spot"`, `"vo2max"`, `"anaerobic"`, `"race"`, `"test"`, `"legs"`, `"upper"`, `"full_body"`, `"core"`, `"plyometrics"`, `"mobility"`, `null`)
- `changes[].strength_intensity` (string/null; one of `"light"`, `"moderate"`, `"heavy"`, `null`)
- `changes[].strength_structure` (array/null; ≤12 items)
- `changes[].strength_structure[].name`* (string; ≥1 chars; ≤80 chars)
- `changes[].strength_structure[].sets`* (integer; ≥1; ≤10)
- `changes[].strength_structure[].reps`* (integer; ≥1; ≤100)
- `changes[].strength_structure[].kg`* (number/null; ≥0; ≤1000)
- `changes[].strength_structure[].pct_1rm`* (number/null; ≥1; ≤150)
- `changes[].strength_structure[].rpe`* (number/null; ≥1; ≤10)
- `changes[].strength_structure[].rir`* (integer/null; ≥0; ≤10)
- `changes[].strength_structure[].rest_s`* (integer/null; ≥0; ≤600)
- `changes[].strength_structure[].warmup`* (object/null)
- `changes[].strength_structure[].warmup.sets`* (integer; ≥1; ≤5)
- `changes[].strength_structure[].warmup.reps`* (integer; ≥1; ≤100)
- `changes[].strength_structure[].warmup.kg`* (number/null; ≥0; ≤1000)
- `changes[].strength_structure[].note`* (string/null; ≤100 chars)
- `changes[].strength_structure[].garmin_exercise`* (string/null; ≤80 chars)
- `changes[].hr_cap` (object/null)
- `changes[].hr_cap.percent_lthr`* (number; ≥20; ≤120)
- `changes[].hr_cap.low_percent_lthr`* (number; ≥20; ≤120)
- `changes[].hr_cap.source`* (string; one of `"default"`, `"measured"`, `"estimated"`)
- `changes[].template_id` (string/null)
- `expected_revision` (integer)

### `apply_training_patch`

effect `local_write`; gate domain `planning`; plan checked; records counted from `changes`, `workouts`; receipt „Geplante Einheiten angepasst“; proposal card „Geplante Einheiten anpassen“; not fully tracked (no turn undo).

- `changes` (array; ≥0 items; ≤366 items)
- `changes[].local_id` (string)
- `changes[].action` (string; one of `"update"`, `"archive"`, `"restore"`, `"delete"`)
- `changes[].date` (string)
- `changes[].starts_at_local` (string)
- `changes[].name` (string)
- `changes[].description` (string)
- `changes[].duration_minutes` (integer)
- `changes[].target` (string)
- `changes[].type` (string)
- `changes[].sport` (string)
- `changes[].expected_payload_hash` (string)
- `changes[].plan_id` (string)
- `changes[].rationale` (string)
- `changes[].environment` (string)
- `changes[].sport_detail` (string)
- `changes[].session_focus` (string/null; one of `"recovery"`, `"easy"`, `"endurance"`, `"long"`, `"tempo"`, `"threshold"`, `"sweet_spot"`, `"vo2max"`, `"anaerobic"`, `"race"`, `"test"`, `"legs"`, `"upper"`, `"full_body"`, `"core"`, `"plyometrics"`, `"mobility"`, `null`)
- `changes[].strength_intensity` (string/null; one of `"light"`, `"moderate"`, `"heavy"`, `null`)
- `changes[].strength_structure` (array/null; ≤12 items)
- `changes[].strength_structure[].name`* (string; ≥1 chars; ≤80 chars)
- `changes[].strength_structure[].sets`* (integer; ≥1; ≤10)
- `changes[].strength_structure[].reps`* (integer; ≥1; ≤100)
- `changes[].strength_structure[].kg`* (number/null; ≥0; ≤1000)
- `changes[].strength_structure[].pct_1rm`* (number/null; ≥1; ≤150)
- `changes[].strength_structure[].rpe`* (number/null; ≥1; ≤10)
- `changes[].strength_structure[].rir`* (integer/null; ≥0; ≤10)
- `changes[].strength_structure[].rest_s`* (integer/null; ≥0; ≤600)
- `changes[].strength_structure[].warmup`* (object/null)
- `changes[].strength_structure[].warmup.sets`* (integer; ≥1; ≤5)
- `changes[].strength_structure[].warmup.reps`* (integer; ≥1; ≤100)
- `changes[].strength_structure[].warmup.kg`* (number/null; ≥0; ≤1000)
- `changes[].strength_structure[].note`* (string/null; ≤100 chars)
- `changes[].strength_structure[].garmin_exercise`* (string/null; ≤80 chars)
- `changes[].hr_cap` (object/null)
- `changes[].hr_cap.percent_lthr`* (number; ≥20; ≤120)
- `changes[].hr_cap.low_percent_lthr`* (number; ≥20; ≤120)
- `changes[].hr_cap.source`* (string; one of `"default"`, `"measured"`, `"estimated"`)
- `changes[].template_id` (string/null)
- `workouts` (array; ≥0 items; ≤366 items)
- `workouts[].date`* (string)
- `workouts[].starts_at_local`* (string/null)
- `workouts[].sport`* (string)
- `workouts[].name`* (string)
- `workouts[].description`* (string; ≥1 chars)
- `workouts[].duration_minutes`* (integer; ≥5; ≤600)
- `workouts[].target`* (string; one of `"AUTO"`, `"POWER"`, `"HR"`, `"PACE"`)
- `workouts[].rationale`* (string; ≥1 chars)
- `workouts[].session_focus`* (string/null; one of `"recovery"`, `"easy"`, `"endurance"`, `"long"`, `"tempo"`, `"threshold"`, `"sweet_spot"`, `"vo2max"`, `"anaerobic"`, `"race"`, `"test"`, `"legs"`, `"upper"`, `"full_body"`, `"core"`, `"plyometrics"`, `"mobility"`, `null`)
- `workouts[].strength_intensity`* (string/null; one of `"light"`, `"moderate"`, `"heavy"`, `null`)
- `workouts[].strength_structure`* (array/null; ≤12 items)
- `workouts[].strength_structure[].name`* (string; ≥1 chars; ≤80 chars)
- `workouts[].strength_structure[].sets`* (integer; ≥1; ≤10)
- `workouts[].strength_structure[].reps`* (integer; ≥1; ≤100)
- `workouts[].strength_structure[].kg`* (number/null; ≥0; ≤1000)
- `workouts[].strength_structure[].pct_1rm`* (number/null; ≥1; ≤150)
- `workouts[].strength_structure[].rpe`* (number/null; ≥1; ≤10)
- `workouts[].strength_structure[].rir`* (integer/null; ≥0; ≤10)
- `workouts[].strength_structure[].rest_s`* (integer/null; ≥0; ≤600)
- `workouts[].strength_structure[].warmup`* (object/null)
- `workouts[].strength_structure[].warmup.sets`* (integer; ≥1; ≤5)
- `workouts[].strength_structure[].warmup.reps`* (integer; ≥1; ≤100)
- `workouts[].strength_structure[].warmup.kg`* (number/null; ≥0; ≤1000)
- `workouts[].strength_structure[].note`* (string/null; ≤100 chars)
- `workouts[].strength_structure[].garmin_exercise`* (string/null; ≤80 chars)
- `workouts[].hr_cap`* (object/null)
- `workouts[].hr_cap.percent_lthr`* (number; ≥20; ≤120)
- `workouts[].hr_cap.low_percent_lthr`* (number; ≥20; ≤120)
- `workouts[].hr_cap.source`* (string; one of `"default"`, `"measured"`, `"estimated"`)
- `workouts[].template_id`* (string/null)
- `expected_revision` (integer)
- `accept_plan_findings` (array of string; ≤1 items; each one of `"illness_hard"`)
- `plan_name` (string)
- `goal` (string)
- `_request`* (the envelope above)

### `apply_workout_library_plan`

effect `local_write`; gate domain `planning`; plan checked; records counted from `entries`; receipt „Vorlagen eingeplant“; proposal card „Vorlagen einplanen“; not fully tracked (no turn undo).

- `entries` (array; ≥1 items; ≤14 items)
- `entries[].library_workout_id`* (string; uuid)
- `entries[].date`* (string; date)
- `accept_plan_findings` (array of string; ≤1 items; each one of `"illness_hard"`)
- `_request`* (the envelope above)

### `assign_activity_equipment`

effect `local_write`; gate domain `profile`; receipt „Ausrüstung zugeordnet“; proposal card „Ausrüstung zuordnen“; fully tracked by change history.

- `payload` (object)
- `payload.activity_id`* (string)
- `payload.equipment_id`* (string/null)
- `_request`* (the envelope above)

### `calculate_food_nutrition`

effect `read`; may call the food database.

- `ingredients` (array; ≥1 items; ≤20 items)
- `ingredients[].food_id`* (string)
- `ingredients[].amount`* (number; >0; ≤5000)
- `ingredients[].unit`* (string; one of `"g"`, `"ml"`)
- `components` (array; ≥1 items; ≤20 items)
- `components[](kind=local_product).kind`* (string; one of `"local_product"`)
- `components[](kind=local_product).product_id`* (string)
- `components[](kind=local_product).amount`* (number; >0; ≤10000)
- `components[](kind=local_product).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `components[](kind=database).kind`* (string; one of `"database"`)
- `components[](kind=database).food_id`* (string)
- `components[](kind=database).amount`* (number; >0; ≤10000)
- `components[](kind=database).unit`* (string; one of `"g"`, `"ml"`)
- `components[](kind=estimate|packaging_label|manual).kind`* (string; one of `"estimate"`, `"packaging_label"`, `"manual"`)
- `components[](kind=estimate|packaging_label|manual).name`* (string; ≥1 chars; ≤200 chars)
- `components[](kind=estimate|packaging_label|manual).amount`* (number; >0; ≤10000)
- `components[](kind=estimate|packaging_label|manual).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `components[](kind=estimate|packaging_label|manual).kcal`* (number; ≥0; ≤10000)
- `components[](kind=estimate|packaging_label|manual).carbs_g`* (number/null; ≥0; ≤1000)
- `components[](kind=estimate|packaging_label|manual).protein_g`* (number/null; ≥0; ≤1000)
- `components[](kind=estimate|packaging_label|manual).fat_g`* (number/null; ≥0; ≤1000)
- `product_id` (string)
- `amount` (number; >0; ≤10000)
- `unit` (string; one of `"g"`, `"ml"`, `"portion"`)

### `cancel_coach_request`

effect `control`; not fully tracked (no turn undo).

- no parameters

### `clarify_coach_request`

effect `control`; not fully tracked (no turn undo).

- `source_message_ids`* (array of integer; ≤24 items)
- `summary`* (string)
- `question`* (string)

### `commit_training_plan`

effect `local_write`; gate domain `planning`; whole-plan change; plan checked; receipt „Trainingsplan gespeichert“; proposal card „Trainingsplan speichern“; not fully tracked (no turn undo).

- `artifact_id` (string)
- `accept_plan_findings` (array of string; ≤1 items; each one of `"illness_hard"`)
- `_request`* (the envelope above)

### `confirm_activity_session`

effect `local_write`; gate domain `profile`; receipt „Aufzeichnungen bestätigt“; proposal card „Aufzeichnungen bestätigen“; fully tracked by change history.

- `payload` (object)
- `payload.activity_id`* (string; ≥1 chars)
- `_request`* (the envelope above)

### `delete_activity_feedback`

effect `local_write`; gate domain `checkin`; needs a confirmed delete request; receipt „Aktivitätsfeedback entfernt“; proposal card „Aktivitätsfeedback entfernen“; fully tracked by change history.

- `activity_id` (string)
- `_request`* (the envelope above)

### `delete_competition`

effect `local_write`; gate domain `competition`; needs a confirmed delete request; receipt „Wettkampf entfernt“; proposal card „Wettkampf entfernen“; not fully tracked (no turn undo).

- `competition_id` (string)
- `_request`* (the envelope above)

### `delete_nutrition_entry`

effect `local_write`; gate domain `nutrition`; needs a confirmed delete request; receipt „Ernährungseintrag entfernt“; proposal card „Ernährungseintrag entfernen“; fully tracked by change history.

- `id` (string)
- `_request`* (the envelope above)

### `delete_nutrition_template`

effect `local_write`; gate domain `nutrition`; needs a confirmed delete request; receipt „Mahlzeitvorlage entfernt“; proposal card „Mahlzeitvorlage entfernen“; fully tracked by change history.

- `id` (string)
- `_request`* (the envelope above)

### `fill_nutrition_product_gaps`

effect `local_write`; gate domain `nutrition`; bulk from 2 records; records counted from `products`; receipt „Produktlücken gefüllt“; proposal card „Produktlücken füllen“; fully tracked by change history.

- `products` (array; ≥1 items; ≤25 items)
- `products[].id`* (string)
- `products[].values`* (object; ≥1 properties)
- `products[].values.kcal` (number; ≥0; ≤9000)
- `products[].values.carbs_g` (number; ≥0; ≤1000)
- `products[].values.protein_g` (number; ≥0; ≤1000)
- `products[].values.fat_g` (number; ≥0; ≤1000)
- `products[].values.sugar_g` (number; ≥0; ≤1000)
- `products[].values.fiber_g` (number; ≥0; ≤1000)
- `products[].values.salt_g` (number; ≥0; ≤1000)
- `products[].origin`* (string; one of `"bls"`, `"manual"`, `"open_food_facts"`, `"web"`, `"yazio"`)
- `products[].source_url` (string; ≤500 chars)
- `products[].source_urls` (object)
- `products[].source_urls.kcal` (string; ≤500 chars)
- `products[].source_urls.carbs_g` (string; ≤500 chars)
- `products[].source_urls.protein_g` (string; ≤500 chars)
- `products[].source_urls.fat_g` (string; ≤500 chars)
- `products[].source_urls.sugar_g` (string; ≤500 chars)
- `products[].source_urls.fiber_g` (string; ≤500 chars)
- `products[].source_urls.salt_g` (string; ≤500 chars)
- `_request`* (the envelope above)

### `get_activity_details`

effect `read`.

- `activity_id`* (string; ≥1 chars; ≤200 chars)

### `get_sync_job`

effect `read`.

- `job_id` (string)

### `get_training_report`

effect `read`.

- `start` (string; date)
- `days` (integer; one of `7`, `28`, `42`, `56`, `84`)
- `since_last_test` (boolean)
- `sport` (string; ≤40 chars)
- `sections` (array of string; ≥1 items; ≤10 items; unique items; each one of `"report"`, `"progress"`, `"block_review"`, `"endurance"`, `"power_profiles"`, `"tag_impact"`, `"season"`, `"comparisons"`, `"body_history"`, `"sleep_timing_variability"`)

### `list_change_history`

effect `read`.

- `limit` (integer; ≥1; ≤500)

### `list_competitions`

effect `read`.

- no parameters

### `list_incomplete_nutrition_products`

effect `read`.

- no parameters

### `list_planned_workouts`

effect `read`.

- `limit` (integer; ≥1; ≤366)

### `list_recent_activities`

effect `read`.

- `days` (integer; ≥1; ≤3660)
- `limit` (integer; ≥1; ≤500)

### `list_training_plans`

effect `read`.

- no parameters

### `list_workout_library`

effect `read`.

- `limit` (integer; ≥1; ≤100)
- `include_archived` (boolean)

### `log_equipment_maintenance`

effect `local_write`; gate domain `profile`; receipt „Wartung lokal erfasst“; proposal card „Wartung erfassen“; fully tracked by change history.

- `payload` (object)
- `payload.equipment_id`* (string)
- `payload.date`* (string; date)
- `payload.notes` (string; ≤1000 chars)
- `_request`* (the envelope above)

### `log_nutrition_template`

effect `local_write`; gate domain `nutrition`; receipt „Verzehr gespeichert“; proposal card „Verzehr erfassen“; fully tracked by change history.

- `id` (string)
- `portions` (number; >0; ≤20)
- `meal_date` (string)
- `meal_time` (string)
- `_request`* (the envelope above)

### `lookup_food`

effect `read`; may call the food database.

- `query` (string; ≥2 chars; ≤120 chars)
- `queries` (array of string; ≥1 items; ≤20 items; each ≥2 chars; each ≤120 chars)
- `barcode` (string; pattern `^[0-9]{8,14}$`)
- `source` (string; one of `"bls"`, `"open_food_facts"`, `"yazio"`)

### `manage_training_templates`

effect `local_write`; gate domain `planning`; records counted from `templates`; receipt „Trainingsvorlagen bearbeitet“; proposal card „Trainingsvorlagen bearbeiten“; fully tracked by change history.

- `templates` (array; ≥1 items; ≤28 items)
- `templates[].action`* (string; one of `"create"`, `"update"`, `"archive"`, `"restore"`, `"delete"`)
- `templates[].local_id` (string; uuid)
- `templates[].name` (string)
- `templates[].description` (string)
- `templates[].sport` (string; one of `"Ride"`, `"VirtualRide"`, `"Run"`, `"Swim"`, `"WeightTraining"`)
- `templates[].type` (string; one of `"Ride"`, `"VirtualRide"`, `"Run"`, `"Swim"`, `"WeightTraining"`)
- `templates[].duration_minutes` (integer; ≥5; ≤1440)
- `templates[].target` (string; one of `"AUTO"`, `"POWER"`, `"HR"`, `"PACE"`)
- `templates[].session_focus` (string/null; one of `"recovery"`, `"easy"`, `"endurance"`, `"long"`, `"tempo"`, `"threshold"`, `"sweet_spot"`, `"vo2max"`, `"anaerobic"`, `"race"`, `"test"`, `"legs"`, `"upper"`, `"full_body"`, `"core"`, `"plyometrics"`, `"mobility"`, `null`)
- `templates[].strength_intensity` (string/null; one of `"light"`, `"moderate"`, `"heavy"`, `null`)
- `templates[].strength_structure` (array/null; ≤12 items)
- `templates[].strength_structure[].name`* (string; ≥1 chars; ≤80 chars)
- `templates[].strength_structure[].sets`* (integer; ≥1; ≤10)
- `templates[].strength_structure[].reps`* (integer; ≥1; ≤100)
- `templates[].strength_structure[].kg`* (number/null; ≥0; ≤1000)
- `templates[].strength_structure[].pct_1rm`* (number/null; ≥1; ≤150)
- `templates[].strength_structure[].rpe`* (number/null; ≥1; ≤10)
- `templates[].strength_structure[].rir`* (integer/null; ≥0; ≤10)
- `templates[].strength_structure[].rest_s`* (integer/null; ≥0; ≤600)
- `templates[].strength_structure[].warmup`* (object/null)
- `templates[].strength_structure[].warmup.sets`* (integer; ≥1; ≤5)
- `templates[].strength_structure[].warmup.reps`* (integer; ≥1; ≤100)
- `templates[].strength_structure[].warmup.kg`* (number/null; ≥0; ≤1000)
- `templates[].strength_structure[].note`* (string/null; ≤100 chars)
- `templates[].strength_structure[].garmin_exercise`* (string/null; ≤80 chars)
- `templates[].hr_cap` (object/null)
- `templates[].hr_cap.percent_lthr`* (number; ≥20; ≤120)
- `templates[].hr_cap.low_percent_lthr`* (number; ≥20; ≤120)
- `templates[].hr_cap.source`* (string; one of `"default"`, `"measured"`, `"estimated"`)
- `_request`* (the envelope above)

### `merge_activity_sessions`

effect `local_write`; gate domain `profile`; receipt „Aktivitäten zusammengeführt“; proposal card „Aktivitäten zusammenführen“; fully tracked by change history.

- `payload` (object)
- `payload.activity_id`* (string; ≥1 chars)
- `payload.other_id`* (string; ≥1 chars)
- `_request`* (the envelope above)

### `preview_adaptive_replan`

effect `local_write`; gate domain `planning`; counts no records toward the bulk check; receipt „Plananpassung vorgeschlagen“; proposal card „Plananpassung vorschlagen“; not fully tracked (no turn undo).

- `_request`* (the envelope above)

### `push_strength_to_garmin`

effect `remote_write`; gate domain `remote_garmin`; receipt „Garmin-Krafteinheiten beauftragt“; proposal card „Krafteinheiten an Garmin senden“; not fully tracked (no turn undo).

- `entries` (array; ≥1 items; ≤28 items)
- `entries[].local_id`* (string; uuid)
- `entries[].remove`* (boolean)
- `reason` (string)
- `_request`* (the envelope above)

### `read_coach_context`

effect `read`.

- `sections`* (array of string; ≥1 items; ≤15 items; each one of `"durable_profile"`, `"target_competitions"`, `"training_plans"`, `"local_feedback"`, `"activity_feedback"`, `"planning"`, `"local_planned_workouts"`, `"calendar"`, `"external_calendar"`, `"activities"`, `"current_performance"`, `"recovery"`, `"weather"`, `"daily_planning_context"`, `"nutrition_products"`, `"planning_brief"`, `"source_policy"`)

### `read_nutrition`

effect `read`.

- `date` (string)
- `start` (string)
- `end` (string)

### `read_profile`

effect `read`.

- no parameters

### `read_training_records`

effect `read`.

- `record_type` (string; one of `"equipment"`)
- `record_id` (string; uuid)

### `read_training_state`

effect `read`.

- `include_inactive` (boolean)
- `cursor` (string)
- `limit` (integer; ≥1; ≤366)

### `replace_training_plan`

effect `local_write`; gate domain `planning`; whole-plan change; plan checked; receipt „Trainingsplan ersetzt“; proposal card „Trainingsplan vollständig ersetzen“; not fully tracked (no turn undo).

- `payload`* (object)
- `payload.plan_name`* (string; ≥1 chars)
- `payload.goal`* (string)
- `payload.workouts`* (array; ≥1 items; ≤366 items)
- `payload.workouts[].date`* (string)
- `payload.workouts[].starts_at_local`* (string/null)
- `payload.workouts[].sport`* (string)
- `payload.workouts[].name`* (string)
- `payload.workouts[].description`* (string; ≥1 chars)
- `payload.workouts[].duration_minutes`* (integer; ≥5; ≤600)
- `payload.workouts[].target`* (string; one of `"AUTO"`, `"POWER"`, `"HR"`, `"PACE"`)
- `payload.workouts[].rationale`* (string; ≥1 chars)
- `payload.workouts[].session_focus`* (string/null; one of `"recovery"`, `"easy"`, `"endurance"`, `"long"`, `"tempo"`, `"threshold"`, `"sweet_spot"`, `"vo2max"`, `"anaerobic"`, `"race"`, `"test"`, `"legs"`, `"upper"`, `"full_body"`, `"core"`, `"plyometrics"`, `"mobility"`, `null`)
- `payload.workouts[].strength_intensity`* (string/null; one of `"light"`, `"moderate"`, `"heavy"`, `null`)
- `payload.workouts[].strength_structure`* (array/null; ≤12 items)
- `payload.workouts[].strength_structure[].name`* (string; ≥1 chars; ≤80 chars)
- `payload.workouts[].strength_structure[].sets`* (integer; ≥1; ≤10)
- `payload.workouts[].strength_structure[].reps`* (integer; ≥1; ≤100)
- `payload.workouts[].strength_structure[].kg`* (number/null; ≥0; ≤1000)
- `payload.workouts[].strength_structure[].pct_1rm`* (number/null; ≥1; ≤150)
- `payload.workouts[].strength_structure[].rpe`* (number/null; ≥1; ≤10)
- `payload.workouts[].strength_structure[].rir`* (integer/null; ≥0; ≤10)
- `payload.workouts[].strength_structure[].rest_s`* (integer/null; ≥0; ≤600)
- `payload.workouts[].strength_structure[].warmup`* (object/null)
- `payload.workouts[].strength_structure[].warmup.sets`* (integer; ≥1; ≤5)
- `payload.workouts[].strength_structure[].warmup.reps`* (integer; ≥1; ≤100)
- `payload.workouts[].strength_structure[].warmup.kg`* (number/null; ≥0; ≤1000)
- `payload.workouts[].strength_structure[].note`* (string/null; ≤100 chars)
- `payload.workouts[].strength_structure[].garmin_exercise`* (string/null; ≤80 chars)
- `payload.workouts[].hr_cap`* (object/null)
- `payload.workouts[].hr_cap.percent_lthr`* (number; ≥20; ≤120)
- `payload.workouts[].hr_cap.low_percent_lthr`* (number; ≥20; ≤120)
- `payload.workouts[].hr_cap.source`* (string; one of `"default"`, `"measured"`, `"estimated"`)
- `payload.workouts[].template_id`* (string/null)
- `expected_revision`* (integer)
- `accept_plan_findings`* (array of string; ≤1 items; each one of `"illness_hard"`)
- `_request`* (the envelope above)

### `resolve_training_sync_conflict`

effect `conditional_remote_write`; gate domain `remote_intervals`; receipt „Synchronisierungskonflikt bearbeitet“; proposal card „Synchronisierungskonflikt bearbeiten“; not fully tracked (no turn undo).

- `local_id` (string)
- `job_id` (string)
- `strategy` (string; one of `"keep_local"`, `"adopt_remote"`)
- `_request`* (the envelope above)

### `save_activity_feedback`

effect `local_write`; gate domain `checkin`; receipt „Aktivitätsfeedback gespeichert“; proposal card „Aktivitätsfeedback speichern“; fully tracked by change history.

- `payload` (object)
- `payload.activity_id`* (string; ≥1 chars)
- `payload.activity_name` (string/null)
- `payload.activity_date` (string/null)
- `payload.notes` (string)
- `payload.session_rpe` (number/null; ≥0; ≤10)
- `payload.deviation_reason` (string/null; ≤500 chars)
- `payload.purpose` (string/null; one of `"training"`, `"race"`, `"commute"`, `"warmup"`, `"cooldown"`, `null`)
- `_request`* (the envelope above)

### `save_checkin`

effect `local_write`; gate domain `checkin`; receipt „Tages-Check-in gespeichert“; proposal card „Tages-Check-in speichern“; fully tracked by change history.

- `payload` (object)
- `payload.checkin_date` (string; date)
- `payload.day_status` (string; one of `"unknown"`, `"rest"`, `"pause"`)
- `payload.tag_answers` (object)
- `payload.tag_answers.travel` (boolean)
- `payload.tag_answers.late_meal` (boolean)
- `payload.tag_answers.high_stress` (boolean)
- `payload.day_form` (string; ≤2000 chars)
- `payload.illness` (string; ≤1000 chars)
- `payload.pain` (string; ≤1000 chars)
- `payload.availability_notes` (string; ≤2000 chars)
- `payload.notes` (string; ≤4000 chars)
- `payload.soreness` (integer/null; ≥0; ≤10)
- `payload.stress` (integer/null; ≥0; ≤10)
- `payload.motivation` (integer/null; ≥0; ≤10)
- `payload.session_rpe` (integer/null; ≥0; ≤10)
- `payload.available_minutes` (integer/null; ≥0; ≤1440)
- `payload.clear_fields` (array of string; unique items; each one of `"soreness"`, `"stress"`, `"motivation"`, `"session_rpe"`, `"available_minutes"`, `"day_form"`, `"illness"`, `"pain"`, `"availability_notes"`, `"notes"`)
- `_request`* (the envelope above)

### `save_competition`

effect `local_write`; gate domain `competition`; receipt „Wettkampf gespeichert“; proposal card „Wettkampf speichern“; fully tracked by change history.

- `payload` (object)
- `payload.competition_id` (string; uuid)
- `payload.name` (string)
- `payload.event_date` (string)
- `payload.starts_at_local` (string)
- `payload.sport` (string)
- `payload.distance` (string)
- `payload.target` (string)
- `payload.course_profile` (string)
- `payload.notes` (string)
- `payload.description` (string)
- `payload.priority` (string; one of `"A"`, `"B"`, `"C"`)
- `payload.planned_duration_s` (integer/null; ≥0)
- `_request`* (the envelope above)

### `save_equipment`

effect `local_write`; gate domain `profile`; receipt „Ausrüstung lokal gespeichert“; proposal card „Ausrüstung speichern“; fully tracked by change history.

- `payload` (object)
- `payload.id` (string; uuid)
- `payload.expected_revision` (integer; ≥1)
- `payload.name`* (string; ≤200 chars)
- `payload.sport`* (string; one of `"Ride"`, `"VirtualRide"`, `"Run"`, `"Swim"`, `"WeightTraining"`, `"Other"`)
- `payload.kind`* (string; one of `"shoes"`, `"bike"`, `"component"`, `"other"`)
- `payload.status` (string; one of `"active"`, `"archived"`)
- `payload.parent_id` (string/null)
- `payload.start_date`* (string; date)
- `payload.initial_distance_km`* (number; ≥0)
- `payload.initial_hours`* (number; ≥0)
- `payload.maintenance_km` (number/null; ≥0)
- `payload.maintenance_hours` (number/null; ≥0)
- `_request`* (the envelope above)

### `save_nutrition_entry`

effect `local_write`; gate domain `nutrition`; receipt „Ernährungseintrag gespeichert“; proposal card „Ernährungseintrag speichern“; fully tracked by change history.

- `payload` (object; exactly one of: with `components`, `description` without `kcal`, `carbs_g`, `protein_g`, `fat_g`, `food_ingredients`, `product_id`, `amount`, `unit` | without `components`)
- `payload.meal_date` (string)
- `payload.meal_time` (string)
- `payload.logged_time_known` (boolean)
- `payload.meal_type` (string; one of `"breakfast"`, `"lunch"`, `"dinner"`, `"snack"`)
- `payload.description` (string)
- `payload.kcal` (integer; ≥0; ≤10000)
- `payload.carbs_g` (number; ≥0; ≤1000)
- `payload.protein_g` (number; ≥0; ≤1000)
- `payload.fat_g` (number; ≥0; ≤1000)
- `payload.source` (string; one of `"voice"`, `"photo"`, `"manual"`, `"coach"`)
- `payload.packaging_label` (boolean)
- `payload.components` (array; ≥1 items; ≤20 items)
- `payload.components[](kind=local_product).kind`* (string; one of `"local_product"`)
- `payload.components[](kind=local_product).product_id`* (string)
- `payload.components[](kind=local_product).amount`* (number; >0; ≤10000)
- `payload.components[](kind=local_product).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `payload.components[](kind=database).kind`* (string; one of `"database"`)
- `payload.components[](kind=database).food_id`* (string)
- `payload.components[](kind=database).amount`* (number; >0; ≤10000)
- `payload.components[](kind=database).unit`* (string; one of `"g"`, `"ml"`)
- `payload.components[](kind=estimate|packaging_label|manual).kind`* (string; one of `"estimate"`, `"packaging_label"`, `"manual"`)
- `payload.components[](kind=estimate|packaging_label|manual).name`* (string; ≥1 chars; ≤200 chars)
- `payload.components[](kind=estimate|packaging_label|manual).amount`* (number; >0; ≤10000)
- `payload.components[](kind=estimate|packaging_label|manual).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `payload.components[](kind=estimate|packaging_label|manual).kcal`* (number; ≥0; ≤10000)
- `payload.components[](kind=estimate|packaging_label|manual).carbs_g`* (number/null; ≥0; ≤1000)
- `payload.components[](kind=estimate|packaging_label|manual).protein_g`* (number/null; ≥0; ≤1000)
- `payload.components[](kind=estimate|packaging_label|manual).fat_g`* (number/null; ≥0; ≤1000)
- `payload.food_ingredients` (array; ≥1 items; ≤20 items)
- `payload.food_ingredients[].food_id`* (string)
- `payload.food_ingredients[].amount`* (number; >0; ≤5000)
- `payload.food_ingredients[].unit`* (string; one of `"g"`, `"ml"`)
- `payload.product_id` (string)
- `payload.amount` (number; >0; ≤10000)
- `payload.unit` (string; one of `"g"`, `"ml"`, `"portion"`)
- `_request`* (the envelope above)

### `save_nutrition_product`

effect `local_write`; gate domain `nutrition`; may call the food database; receipt „Produkt lokal gespeichert“; proposal card „Produkt lokal speichern“; fully tracked by change history.

- `payload` (object)
- `payload.id` (string)
- `payload.barcode` (string/null)
- `payload.name`* (string; ≤200 chars)
- `payload.brand` (string; ≤120 chars)
- `payload.basis_amount`* (number; >0; ≤10000)
- `payload.basis_unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `payload.kcal` (number/null; ≥0; ≤10000)
- `payload.carbs_g` (number/null; ≥0; ≤1000)
- `payload.protein_g` (number/null; ≥0; ≤1000)
- `payload.fat_g` (number/null; ≥0; ≤1000)
- `payload.sugar_g` (number/null; ≥0; ≤1000)
- `payload.fiber_g` (number/null; ≥0; ≤1000)
- `payload.salt_g` (number/null; ≥0; ≤1000)
- `payload.source`* (string; one of `"packaging_label"`, `"manual"`, `"open_food_facts"`, `"yazio"`, `"bls"`, `"fddb_export"`)
- `payload.source_url` (string; ≤500 chars)
- `payload.external_id` (string; ≤200 chars)
- `_request`* (the envelope above)

### `save_nutrition_template`

effect `local_write`; gate domain `nutrition`; may call the food database; receipt „Mahlzeitvorlage gespeichert“; proposal card „Mahlzeitvorlage speichern“; fully tracked by change history.

- `payload` (object; needs one of `components`, `food_ingredients`, `kcal`, `id`)
- `payload.logged_time_known` (boolean)
- `payload.meal_type` (string; one of `"breakfast"`, `"lunch"`, `"dinner"`, `"snack"`)
- `payload.description`* (string)
- `payload.kcal` (integer; ≥0; ≤10000)
- `payload.carbs_g` (number; ≥0; ≤1000)
- `payload.protein_g` (number; ≥0; ≤1000)
- `payload.fat_g` (number; ≥0; ≤1000)
- `payload.source` (string; one of `"voice"`, `"photo"`, `"manual"`, `"coach"`)
- `payload.packaging_label` (boolean)
- `payload.components` (array; ≥1 items; ≤20 items)
- `payload.components[](kind=local_product).kind`* (string; one of `"local_product"`)
- `payload.components[](kind=local_product).product_id`* (string)
- `payload.components[](kind=local_product).amount`* (number; >0; ≤10000)
- `payload.components[](kind=local_product).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `payload.components[](kind=database).kind`* (string; one of `"database"`)
- `payload.components[](kind=database).food_id`* (string)
- `payload.components[](kind=database).amount`* (number; >0; ≤10000)
- `payload.components[](kind=database).unit`* (string; one of `"g"`, `"ml"`)
- `payload.components[](kind=estimate|packaging_label|manual).kind`* (string; one of `"estimate"`, `"packaging_label"`, `"manual"`)
- `payload.components[](kind=estimate|packaging_label|manual).name`* (string; ≥1 chars; ≤200 chars)
- `payload.components[](kind=estimate|packaging_label|manual).amount`* (number; >0; ≤10000)
- `payload.components[](kind=estimate|packaging_label|manual).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `payload.components[](kind=estimate|packaging_label|manual).kcal`* (number; ≥0; ≤10000)
- `payload.components[](kind=estimate|packaging_label|manual).carbs_g`* (number/null; ≥0; ≤1000)
- `payload.components[](kind=estimate|packaging_label|manual).protein_g`* (number/null; ≥0; ≤1000)
- `payload.components[](kind=estimate|packaging_label|manual).fat_g`* (number/null; ≥0; ≤1000)
- `payload.food_ingredients` (array; ≥1 items; ≤20 items)
- `payload.food_ingredients[].food_id`* (string)
- `payload.food_ingredients[].amount`* (number; >0; ≤5000)
- `payload.food_ingredients[].unit`* (string; one of `"g"`, `"ml"`)
- `payload.product_id` (string)
- `payload.amount` (number; >0; ≤10000)
- `payload.unit` (string; one of `"g"`, `"ml"`, `"portion"`)
- `payload.name`* (string; ≤120 chars)
- `payload.id` (string)
- `_request`* (the envelope above)

### `search_web_for_product_values`

effect `read`; may call the food database.

- `products` (array of string; ≥1 items; ≤5 items)

### `split_activity_session`

effect `local_write`; gate domain `profile`; receipt „Aufzeichnung getrennt“; proposal card „Aufzeichnung trennen“; fully tracked by change history.

- `payload` (object)
- `payload.activity_id`* (string; ≥1 chars)
- `payload.member_id`* (string; ≥1 chars)
- `_request`* (the envelope above)

### `stage_training_plan`

effect `local_write`; gate domain `planning`; counts no records toward the bulk check; receipt „Planentwurf gespeichert“; proposal card „Planentwurf erstellen“; not fully tracked (no turn undo).

- `payload`* (object)
- `payload.plan_name`* (string)
- `payload.goal`* (string)
- `payload.workouts`* (array; ≥1 items; ≤366 items)
- `payload.workouts[].date`* (string)
- `payload.workouts[].starts_at_local`* (string/null)
- `payload.workouts[].sport`* (string)
- `payload.workouts[].name`* (string)
- `payload.workouts[].description`* (string; ≥1 chars)
- `payload.workouts[].duration_minutes`* (integer; ≥5; ≤600)
- `payload.workouts[].target`* (string; one of `"AUTO"`, `"POWER"`, `"HR"`, `"PACE"`)
- `payload.workouts[].rationale`* (string; ≥1 chars)
- `payload.workouts[].session_focus`* (string/null; one of `"recovery"`, `"easy"`, `"endurance"`, `"long"`, `"tempo"`, `"threshold"`, `"sweet_spot"`, `"vo2max"`, `"anaerobic"`, `"race"`, `"test"`, `"legs"`, `"upper"`, `"full_body"`, `"core"`, `"plyometrics"`, `"mobility"`, `null`)
- `payload.workouts[].strength_intensity`* (string/null; one of `"light"`, `"moderate"`, `"heavy"`, `null`)
- `payload.workouts[].strength_structure`* (array/null; ≤12 items)
- `payload.workouts[].strength_structure[].name`* (string; ≥1 chars; ≤80 chars)
- `payload.workouts[].strength_structure[].sets`* (integer; ≥1; ≤10)
- `payload.workouts[].strength_structure[].reps`* (integer; ≥1; ≤100)
- `payload.workouts[].strength_structure[].kg`* (number/null; ≥0; ≤1000)
- `payload.workouts[].strength_structure[].pct_1rm`* (number/null; ≥1; ≤150)
- `payload.workouts[].strength_structure[].rpe`* (number/null; ≥1; ≤10)
- `payload.workouts[].strength_structure[].rir`* (integer/null; ≥0; ≤10)
- `payload.workouts[].strength_structure[].rest_s`* (integer/null; ≥0; ≤600)
- `payload.workouts[].strength_structure[].warmup`* (object/null)
- `payload.workouts[].strength_structure[].warmup.sets`* (integer; ≥1; ≤5)
- `payload.workouts[].strength_structure[].warmup.reps`* (integer; ≥1; ≤100)
- `payload.workouts[].strength_structure[].warmup.kg`* (number/null; ≥0; ≤1000)
- `payload.workouts[].strength_structure[].note`* (string/null; ≤100 chars)
- `payload.workouts[].strength_structure[].garmin_exercise`* (string/null; ≤80 chars)
- `payload.workouts[].hr_cap`* (object/null)
- `payload.workouts[].hr_cap.percent_lthr`* (number; ≥20; ≤120)
- `payload.workouts[].hr_cap.low_percent_lthr`* (number; ≥20; ≤120)
- `payload.workouts[].hr_cap.source`* (string; one of `"default"`, `"measured"`, `"estimated"`)
- `payload.workouts[].template_id`* (string/null)
- `_request`* (the envelope above)

### `start_intervals_plan_sync`

effect `remote_write`; gate domain `remote_intervals`; receipt „Plansynchronisierung beauftragt“; proposal card „Plan synchronisieren“; not fully tracked (no turn undo).

- `entries` (array; ≥1 items; ≤100 items)
- `entries[].library_workout_id`* (string; uuid)
- `entries[].expected_payload_hash`* (string; pattern `^[0-9a-f]{64}$`)
- `reason` (string)
- `expected_revision` (integer)
- `repair` (boolean)
- `_request`* (the envelope above)

### `start_provider_refresh`

effect `provider_read_job`; receipt „Datenabruf beauftragt“; proposal card „Datenabruf starten“; not fully tracked (no turn undo).

- `days` (integer one of `-1` or integer ≥1 ≤365)
- `reason` (string)
- `_request`* (the envelope above)

### `sync_competitions`

effect `remote_write`; gate domain `remote_intervals`; receipt „Wettkampfsynchronisierung beauftragt“; proposal card „Wettkämpfe synchronisieren“; not fully tracked (no turn undo).

- `reason` (string)
- `_request`* (the envelope above)

### `sync_nutrition`

effect `remote_write`; gate domain `remote_intervals`; receipt „Ernährungssynchronisierung beauftragt“; proposal card „Ernährung synchronisieren“; not fully tracked (no turn undo).

- `date` (string)
- `pending_limit` (integer; ≥1; ≤31)
- `_request`* (the envelope above)

### `undo_training_change`

effect `local_write`; gate domain `undo`; receipt „Rückgängig-Vorschau vorbereitet“; proposal card „Rückgängig-Vorschau erstellen“; not fully tracked (no turn undo).

- `change_id` (string)
- `apply` (boolean)
- `_request`* (the envelope above)

### `update_nutrition_entry`

effect `local_write`; gate domain `nutrition`; receipt „Ernährungseintrag korrigiert“; proposal card „Ernährungseintrag korrigieren“; fully tracked by change history.

- `id` (string)
- `changes` (object)
- `changes.meal_date` (string)
- `changes.logged_at` (string)
- `changes.meal_time` (string)
- `changes.logged_time_known` (boolean)
- `changes.meal_type` (string; one of `"breakfast"`, `"lunch"`, `"dinner"`, `"snack"`)
- `changes.description` (string)
- `changes.kcal` (integer; ≥0; ≤10000)
- `changes.carbs_g` (number/null; ≥0; ≤1000)
- `changes.protein_g` (number/null; ≥0; ≤1000)
- `changes.fat_g` (number/null; ≥0; ≤1000)
- `changes.packaging_label` (boolean)
- `changes.components` (array; ≥1 items; ≤20 items)
- `changes.components[](kind=local_product).kind`* (string; one of `"local_product"`)
- `changes.components[](kind=local_product).product_id`* (string)
- `changes.components[](kind=local_product).amount`* (number; >0; ≤10000)
- `changes.components[](kind=local_product).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `changes.components[](kind=database).kind`* (string; one of `"database"`)
- `changes.components[](kind=database).food_id`* (string)
- `changes.components[](kind=database).amount`* (number; >0; ≤10000)
- `changes.components[](kind=database).unit`* (string; one of `"g"`, `"ml"`)
- `changes.components[](kind=estimate|packaging_label|manual).kind`* (string; one of `"estimate"`, `"packaging_label"`, `"manual"`)
- `changes.components[](kind=estimate|packaging_label|manual).name`* (string; ≥1 chars; ≤200 chars)
- `changes.components[](kind=estimate|packaging_label|manual).amount`* (number; >0; ≤10000)
- `changes.components[](kind=estimate|packaging_label|manual).unit`* (string; one of `"g"`, `"ml"`, `"portion"`)
- `changes.components[](kind=estimate|packaging_label|manual).kcal`* (number; ≥0; ≤10000)
- `changes.components[](kind=estimate|packaging_label|manual).carbs_g`* (number/null; ≥0; ≤1000)
- `changes.components[](kind=estimate|packaging_label|manual).protein_g`* (number/null; ≥0; ≤1000)
- `changes.components[](kind=estimate|packaging_label|manual).fat_g`* (number/null; ≥0; ≤1000)
- `changes.food_ingredients` (array; ≥1 items; ≤20 items)
- `changes.food_ingredients[].food_id`* (string)
- `changes.food_ingredients[].amount`* (number; >0; ≤5000)
- `changes.food_ingredients[].unit`* (string; one of `"g"`, `"ml"`)
- `_request`* (the envelope above)

### `update_profile`

effect `local_write`; gate domain `profile`; receipt „Profil aktualisiert“; proposal card „Profil aktualisieren“; fully tracked by change history.

- `changes`* (array; ≥1 items; ≤30 items)
- `changes[].field`* (string; one of `"name"`, `"goals"`, `"sports"`, `"training_background"`, `"typical_weekly_volume"`, `"availability"`, `"constraints"`, `"equipment"`, `"training_preferences"`, `"training_preferences_running"`, `"training_preferences_cycling"`, `"training_preferences_swimming"`, `"training_preferences_strength"`, `"training_preferences_mobility"`, `"training_model"`, `"performance_notes"`, `"weight_kg"`, `"body_fat_pct"`, `"height_cm"`, `"sex"`, `"coaching_style"`, `"timezone"`, `"weather_location"`, `"sleep_target_hours"`, `"fueling_tolerance"`, `"preferred_source_thresholds"`, `"preferred_source_body"`, `"preferred_source_hrv"`, `"preferred_source_resting_hr"`, `"preferred_source_sleep"`)
- `changes[].expected_value`* (string; ≤4000 chars)
- `changes[].value`* (string; ≤4000 chars)
- `_request`* (the envelope above)

### `update_training_plan`

effect `local_write`; gate domain `planning`; receipt „Planinformationen bearbeitet“; proposal card „Planinformationen bearbeiten“; not fully tracked (no turn undo).

- `payload` (object)
- `payload.plan_id`* (string; uuid)
- `payload.action` (string; one of `"update"`, `"delete"`)
- `payload.name` (string)
- `payload.goal` (string)
- `payload.start_date` (string)
- `payload.end_date` (string)
- `payload.status` (string; one of `"active"`, `"archived"`, `"cancelled"`, `"completed"`, `"draft"`, `"paused"`, `"planned"`)
- `_request`* (the envelope above)
<!-- END GENERATED TOOL CONTRACTS -->
