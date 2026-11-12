# Coach tool execution coverage

This matrix covers every tool currently offered to the conversational Coach.
It measures execution through `chat_with_coach`, not the accuracy of a language
model's interpretation.

`tests/test_coach_tool_coverage.py` uses scripted model responses and disposable
athlete state. Successful scenarios run the real request validator, dispatcher,
local persistence and receipt logic. Provider network access is blocked; provider
refresh/illness-sync results are simulated, and queued jobs are inspected without
starting a provider worker. No live account or previous installation is used.

## Enforced coverage matrix

The `covers` decorator checks that every declared case actually produced a
successful tool receipt during that test. A catalog test compares the matrix to
`COACH_DIALOGUE_TOOLS`, so a newly exposed tool needs an executable success case.
Multi-action tools also have explicitly required variants. Each scenario checks
returned data, durable state or the provider boundary, not just the success flag.

All test names below refer to `tests/test_coach_tool_coverage.py`. The table is
generated from the `covers` declarations; regenerate it with
`python tests/test_coach_tool_coverage.py --write`.

<!-- BEGIN GENERATED TOOL TABLE -->
| Tool | Successful variants | Scenario tests |
| --- | --- | --- |
| `apply_adaptive_replan` | `intervals`, `local` | `test_adaptive_preview_requires_later_acceptance_before_changing_workout`, `test_illness_sync_requires_explicit_remote_acceptance_after_preview` |
| `apply_training_patch` | `archive`, `create`, `delete`, `move`, `restore`, `update` | `test_planned_unit_lifecycle_keeps_identity_until_deleted` |
| `apply_workout_library_plan` | `success` | `test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy` |
| `assign_activity_equipment` | `success` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `calculate_food_nutrition` | `success` | `test_food_database_read_tools_calculate_without_writing` |
| `cancel_coach_request` | `success` | `test_clarification_and_cancellation_preserve_athlete_data` |
| `clarify_coach_request` | `success` | `test_clarification_and_cancellation_preserve_athlete_data` |
| `commit_training_plan` | `success` | `test_requested_draft_commit_and_metadata_lifecycle` |
| `confirm_activity_session` | `success` | `test_session_tools_correct_the_bundle_and_leave_a_change_receipt` |
| `delete_activity_feedback` | `success` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `delete_competition` | `success` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `delete_nutrition_entry` | `success` | `test_nutrition_entries_can_be_saved_read_and_deleted` |
| `delete_nutrition_template` | `success` | `test_saved_meals_run_through_authorized_coach_and_receipts` |
| `fill_nutrition_product_gaps` | `success` | `test_incomplete_products_are_listed_and_filled_by_authorized_coach_turn` |
| `get_activity_details` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `get_sync_job` | `success` | `test_provider_reads_and_job_status_use_correct_provider` |
| `get_training_report` | `success` | `test_training_report_returns_same_local_facts_without_mutation` |
| `list_change_history` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_competitions` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_incomplete_nutrition_products` | `success` | `test_incomplete_products_are_listed_and_filled_by_authorized_coach_turn` |
| `list_planned_workouts` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_recent_activities` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_training_plans` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_workout_library` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `log_equipment_maintenance` | `success` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `log_nutrition_template` | `success` | `test_saved_meals_run_through_authorized_coach_and_receipts` |
| `lookup_food` | `success` | `test_food_database_read_tools_calculate_without_writing` |
| `manage_training_templates` | `archive`, `create`, `delete`, `restore`, `update` | `test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy` |
| `merge_activity_sessions` | `success` | `test_session_tools_correct_the_bundle_and_leave_a_change_receipt` |
| `preview_adaptive_replan` | `success` | `test_adaptive_preview_requires_later_acceptance_before_changing_workout` |
| `push_strength_to_garmin` | `push`, `remove` | `test_garmin_strength_push_is_bound_to_the_stored_units` |
| `read_coach_context` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `read_nutrition` | `success` | `test_nutrition_entries_can_be_saved_read_and_deleted`, `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `read_profile` | `success` | `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` |
| `read_training_records` | `success` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `read_training_state` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `replace_training_plan` | `success` | `test_replacement_changes_only_requested_period` |
| `resolve_training_sync_conflict` | `adopt_remote`, `keep_local`, `retry_push`, `retry_read` | `test_conflict_choices_and_failed_job_retries` |
| `save_activity_feedback` | `success` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `save_checkin` | `success` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `save_competition` | `create`, `update` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `save_equipment` | `success` | `test_training_records_and_equipment_tools_use_confirmed_local_state` |
| `save_nutrition_entry` | `success` | `test_nutrition_entries_can_be_saved_read_and_deleted` |
| `save_nutrition_product` | `success` | `test_confirmed_product_is_saved_locally_through_authorized_coach_receipt` |
| `save_nutrition_template` | `success` | `test_saved_meals_run_through_authorized_coach_and_receipts` |
| `search_web_for_product_values` | `success` | `test_web_search_returns_cited_values_and_degrades_to_unavailable` |
| `split_activity_session` | `success` | `test_session_tools_correct_the_bundle_and_leave_a_change_receipt` |
| `stage_training_plan` | `success` | `test_requested_draft_commit_and_metadata_lifecycle` |
| `start_intervals_plan_sync` | `all_pending`, `created`, `selected` | `test_new_plan_sync_and_later_selected_sync_use_real_ids` |
| `start_provider_refresh` | `calendar`, `garmin`, `wahoo`, `weather` | `test_provider_reads_and_job_status_use_correct_provider` |
| `sync_competitions` | `success` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `sync_nutrition` | `date`, `pending` | `test_nutrition_correction_preserves_fields_and_sync_is_explicitly_queued` |
| `undo_training_change` | `success` | `test_undo_is_a_bound_preview_until_explicit_confirmation` |
| `update_nutrition_entry` | `success` | `test_nutrition_correction_preserves_fields_and_sync_is_explicitly_queued` |
| `update_profile` | `success` | `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` |
| `update_training_plan` | `archive`, `delete`, `update` | `test_requested_draft_commit_and_metadata_lifecycle` |
<!-- END GENERATED TOOL TABLE -->

## Failure and conversation coverage

- **Every write tool carrying `_request`:** `test_every_mutating_tool_rejects_missing_user_authorization_without_effect` drives the real chat loop with missing provenance and compares all affected athlete tables before/after. Clarification and cancellation have their distinct dialogue-only contracts.
- **Invalid values, missing references, atomic rejection:** `test_invalid_arguments_and_missing_objects_do_not_partially_write` covers the tool-specific cases, including a template batch whose first valid item must roll back when a later item fails. Parameterless operations use authorization checks rather than invented invalid-field cases.
- **Wrong scope, stale profile fields, hashes and revisions:** the existing `test_coach_dialogue.py` regressions remain active, including `test_different_target_id_cannot_escape_action_scope`, `test_profile_patch_conflict_is_atomic_and_can_be_repaired`, `test_selected_sync_validates_hash_before_changing_state`, `test_failed_local_step_blocks_following_all_pending_push` and `test_stale_hash_rolls_back_whole_patch`.
- **Plan correction and explicit follow-up sync:** `test_friday_correction_retry_and_sync_keep_sunday_unchanged` replaces Friday strength with an easy run, rejects an obsolete revision, rereads current state, applies once despite repeated calls/replayed turns, preserves Sunday, and queues only the selected unit on a later sync request.
- **Short follow-up:** `test_short_answer_completes_persisted_clarification_after_an_intervening_read` resolves "Die zweite." against a saved clarification and preserves the unselected unit.
- **Permanent facts:** `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` accepts a visible proposal, reads the profile and appends information without losing existing fields or queuing remote writes.
- **Advice, negation and cancellation:** scripted advice/negation leaves athlete state unchanged; cancellation clears only the pending request. Assistant/nonexistent message IDs cannot supply user provenance.
- **Adaptive approval:** self-approval in the preview-generating turn is rejected; a later acceptance applies local changes, while illness sync additionally requires explicit Intervals authorization. A stale preview preserves an intervening workout edit.
- **Read-only previews:** undo returns a bound preview without applying it (`test_undo_is_a_bound_preview_until_explicit_confirmation`). Existing API tests cover the separate explicit confirmation/execution paths.

## Defect found by the new conversation scenario

Changing a planned unit's sport updated only its `type` projection. Normalization
then restored the unchanged canonical `sport`, so a requested run could remain
strength training despite a successful receipt. The update now changes canonical
`sport`; normalization derives the matching provider `type`. Tests cover both
exposed input fields, preserve unit identity, and keep the change local.

## What this does not prove

The model calls, parameters and authorization metadata are scripted. These tests
do not prove that a real model understands a paraphrase, notices a negation, asks
the right clarification, or chooses the right tool. There is no measured natural-
language success percentage. Full coverage here means every currently exposed
tool has a successful execution scenario and the documented variants/boundaries
are tested, not exhaustive coverage of all possible arguments or conversations.

A separate, explicitly authorized model evaluation with synthetic athlete data,
simulated provider effects, multiple phrasings and repeated runs per model remains
future work. Ordinary tests must continue to mock external services.

## Running the checks

```powershell
python -m unittest discover -s tests -p test_coach_tool_coverage.py -v
python -m unittest discover -s tests -v
python -m compileall -q server.py backend tests
```

The repository's standard discovery and CI sharding include the module. The
shared `DialogueHarness` (`tests/test_coach_dialogue.py`) is not a `TestCase`, so
reusing it does not duplicate the dialogue tests.

## Validation results

- `python -m unittest tests.test_coach_tool_coverage` passes. The module covers
  declared successful tool variants for every tool in `TOOL_SPECS`,
  invalid-argument/reference cases and missing-provenance checks for every write
  tool carrying `_request`.
- These are execution and conversation tests, not live language-model
  evaluations.
