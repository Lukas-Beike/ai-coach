# Coach tool execution coverage

This matrix covers the 34 tools currently offered to the conversational Coach.
It builds on the profile/sync fix in `ebbe311`. It measures execution through
`chat_with_coach`, not the accuracy of a language model's interpretation.

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

All test names below refer to `tests/test_coach_tool_coverage.py`.

| Tool | Successful variants | Scenario tests |
| --- | --- | --- |
| `apply_adaptive_replan` | `intervals`, `local` | `test_adaptive_preview_requires_later_acceptance_before_changing_workout`, `test_illness_sync_requires_explicit_remote_acceptance_after_preview` |
| `apply_training_patch` | `archive`, `create`, `delete`, `move`, `restore`, `update` | `test_planned_unit_lifecycle_keeps_identity_until_deleted` |
| `apply_workout_library_plan` | `success` | `test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy` |
| `cancel_coach_request` | `success` | `test_clarification_and_cancellation_preserve_athlete_data` |
| `clarify_coach_request` | `success` | `test_clarification_and_cancellation_preserve_athlete_data` |
| `commit_training_plan` | `success` | `test_requested_draft_commit_and_metadata_lifecycle` |
| `delete_activity_feedback` | `success` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `delete_competition` | `success` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `get_sync_job` | `success` | `test_provider_reads_and_job_status_use_correct_provider` |
| `get_activity_details` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `inspect_activity_duplicates` | `success` | `test_duplicate_inspection_returns_preview_without_deleting_provider_data` |
| `list_change_history` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_competitions` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_planned_workouts` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_recent_activities` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_training_plans` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `list_workout_library` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `manage_training_templates` | `archive`, `create`, `delete`, `restore`, `update` | `test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy` |
| `preview_adaptive_replan` | `success` | `test_adaptive_preview_requires_later_acceptance_before_changing_workout` |
| `read_profile` | `success` | `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` |
| `read_training_state` | `success` | `test_read_tools_return_seeded_objects_without_mutating_them` |
| `refresh_current_performance` | `success` | `test_provider_reads_and_job_status_use_correct_provider` |
| `replace_training_plan` | `success` | `test_replacement_changes_only_requested_period` |
| `resolve_training_sync_conflict` | `adopt_remote`, `keep_local`, `retry_push`, `retry_read` | `test_conflict_choices_and_failed_job_retries` |
| `save_activity_feedback` | `success` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `save_checkin` | `success` | `test_daily_feedback_and_activity_feedback_are_separate_from_profile` |
| `save_competition` | `create`, `update` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `stage_training_plan` | `success` | `test_requested_draft_commit_and_metadata_lifecycle` |
| `start_intervals_plan_sync` | `all_pending`, `created`, `selected` | `test_new_plan_sync_and_later_selected_sync_use_real_ids` |
| `start_provider_refresh` | `calendar`, `garmin`, `intervals`, `weather` | `test_provider_reads_and_job_status_use_correct_provider` |
| `sync_competitions` | `success` | `test_competition_lifecycle_syncs_only_after_explicit_followup` |
| `undo_training_change` | `success` | `test_undo_is_a_bound_preview_until_explicit_confirmation` |
| `update_profile` | `success` | `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` |
| `update_training_plan` | `archive`, `delete`, `update` | `test_requested_draft_commit_and_metadata_lifecycle` |

## Failure and conversation coverage

- **Every write tool carrying `_request`:** `test_every_mutating_tool_rejects_missing_user_authorization_without_effect` drives the real chat loop with missing provenance and compares all affected athlete tables before/after. Clarification and cancellation have their distinct dialogue-only contracts.
- **Invalid values, missing references, atomic rejection:** `test_invalid_arguments_and_missing_objects_do_not_partially_write` covers 20 tool-specific cases, including a template batch whose first valid item must roll back when a later item fails. Parameterless operations use authorization checks rather than invented invalid-field cases.
- **Wrong scope, stale profile fields, hashes and revisions:** the existing `test_coach_dialogue.py` regressions remain active, including `test_different_target_id_cannot_escape_action_scope`, `test_profile_patch_conflict_is_atomic_and_can_be_repaired`, `test_selected_sync_validates_hash_before_changing_state`, `test_failed_local_step_blocks_following_all_pending_push` and `test_stale_hash_rolls_back_whole_patch`.
- **Plan correction and explicit follow-up sync:** `test_friday_correction_retry_and_sync_keep_sunday_unchanged` replaces Friday strength with an easy run, rejects an obsolete revision, rereads current state, applies once despite repeated calls/replayed turns, preserves Sunday, and queues only the selected unit on a later sync request.
- **Short follow-up:** `test_short_answer_completes_persisted_clarification_after_an_intervening_read` resolves ?Die zweite? against a saved clarification and preserves the unselected unit.
- **Permanent facts:** `test_permanent_profile_acceptance_reads_and_preserves_existing_facts` accepts a visible proposal, reads the profile and appends information without losing existing fields or queuing remote writes.
- **Advice, negation and cancellation:** scripted advice/negation leaves athlete state unchanged; cancellation clears only the pending request. Assistant/nonexistent message IDs cannot supply user provenance.
- **Adaptive approval:** self-approval in the preview-generating turn is rejected; a later acceptance applies local changes, while illness sync additionally requires explicit Intervals authorization. A stale preview preserves an intervening workout edit.
- **Read-only previews:** undo and duplicate inspection return previews without applying undo or deleting provider records. Existing API tests cover the separate explicit confirmation/execution paths.

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
python -m py_compile server.py tests/test_server.py tests/test_coach_dialogue.py tests/test_coach_tool_coverage.py
```

The repository's standard discovery and CI sharding include the new module. The
shared `DialogueHarness` is not a `TestCase`, so reusing it does not duplicate the
55 existing dialogue tests.

## Validation results

- 26 new tests pass, including 54 declared successful tool variants across all
  33 tools, 20 invalid-argument/reference cases and missing-provenance checks
  for every write tool carrying `_request`.
- Together with the 55 existing dialogue tests, this provides 81 execution and
  conversation tests. These are not 81 live language-model evaluations.
- Full Python 3.13 suite: 599 tests, successful, 12 skipped.
- Full Python 3.14/SQLCipher suite in an isolated container with networking
  disabled and source mounted read-only: 599 tests, successful, 9 skipped.
- Syntax compilation, Git whitespace checks and the Docker image build pass.
