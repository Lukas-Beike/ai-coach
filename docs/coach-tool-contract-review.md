# Conversational Coach tool review — 2026-09-08

The Coach receives the local dialogue, current user message ID, pending request,
and provider context. It resolves meaning and object references; the server
validates provenance, targets, scope, current state and effects. No trigger-word
classifier or routine confirmation loop is introduced.

## Tool inventory

| Tools | Conversation contract and execution boundary |
| --- | --- |
| `read_profile`, `update_profile` | Explicit permanent facts or acceptance of a concrete profile proposal. Read current fields; atomically patch named fields using expected values. Preserve omitted fields and existing facts when appending. |
| `read_training_state`, `list_planned_workouts`, `list_workout_library`, `list_training_plans` | Resolve existing local IDs, dates, planning revision and hashes before choosing or changing units, templates or plans. |
| `list_recent_activities` | Read completed activities and resolve actual activity IDs; cannot create completed activity records. |
| `list_competitions`, `list_change_history` | Resolve competition IDs or history references for edits and undo previews. |
| `apply_training_patch` | One atomic batch for related additions, moves, edits and removals, bounded by the requested period and current revision/hashes. Preserved units retain identity. |
| `replace_training_plan` | Replace only the explicitly requested inclusive period; validate the whole final schedule first. |
| `stage_training_plan`, `commit_training_plan` | Draft only when requested; commit only a draft from this local dialogue with its source user message. Ordinary plan creation uses the direct patch/replace tools. |
| `manage_training_templates`, `apply_workout_library_plan` | Undated reusable templates versus local dated scheduling. Schemas expose action, ID, workout fields and dates. Neither pushes remotely. |
| `save_checkin` | Daily athlete statements, local date, bounded scores and availability; omitted/empty fields preserve existing feedback. Not permanent profile storage. |
| `save_activity_feedback`, `delete_activity_feedback` | Persist or remove observations for a real completed activity. Mentioning an activity as planning context does not itself request a feedback write. |
| `save_competition`, `delete_competition`, `update_training_plan` | Change resolved local objects. Schemas expose supported fields. Deleting plan metadata leaves its scheduled workouts intact. |
| `start_provider_refresh`, `refresh_current_performance` | Named provider reads, with provider target and refresh scope. Intervals activity refresh completes before analysis; other queued work needs job status inspection. Performance refresh is distinct from activity refresh. |
| `start_intervals_plan_sync`, `sync_competitions` | Explicit Intervals push, separate from local saving. Selected units use exact local UUIDs and current hashes. `created` means additions in this turn; a later follow-up reads current state and uses `selected` or explicitly `all_pending`. |
| `get_sync_job` | Read actual queued/running/completed/partial/failed state. Acceptance into a queue is not completion. |
| `resolve_training_sync_conflict` | A local conflict decision uses local target and an object reference. Retrying a failed job uses its original provider; pushes require remote-write authorization, reads require provider-refresh scope. |
| `preview_adaptive_replan`, `apply_adaptive_replan` | A generated preview must be shown before a later user message approves applying it. Optional remote illness sync additionally requires explicit Intervals authorization. |
| `undo_training_change` | Produces the existing explicit undo preview, not a silent undo. |
| `inspect_activity_duplicates` | Inspects latest cycling duplicates and may produce a deletion preview; remote deletion still needs explicit confirmation. |
| `clarify_coach_request`, `cancel_coach_request` | Preserve a specific unresolved request across replies/reloads or close it on cancellation. Completed effects remain recorded. |

## Repairs and evidence

- Added the missing profile read/update capability with field validation and
  concurrency checks, plus a readable action receipt.
- Replaced opaque nested objects in template, scheduling, check-in, competition,
  plan metadata and sync schemas with documented fields.
- Selected sync validates hashes before changing local conflict state and queues
  hashes of the resulting state.
- Corrected calls resolve earlier failures for the same scope; success on a
  different object does not hide a remaining failure. The UI hides resolved
  attempts and marks queued/running synchronization as pending.
- Retry authorization follows the persisted job's provider and operation.

Regression tests use synthetic multi-turn dialogue and mocked model/provider
responses. They verify the tool execution contract, short acceptance, scope,
rollback, stale state, retries, idempotency and rendered receipts. Browser checks
use a disposable SQLCipher fixture and a fresh profile. These tests do not measure
the language model's recognition accuracy on live conversations and do not
replay the athlete's actual failed operations or modify the live installation.

Validation results:

- Native Python 3.13: 573 tests, successful, 12 skipped.
- Isolated Python 3.14/SQLCipher container with networking disabled: 573 tests,
  successful, 9 skipped.
- Focused conversational suite: 55 tests successful.
- Mobile and desktop browser checks covered 66 scenarios. The initial shared
  fixture run passed 63; the offline checks required a localhost secure origin,
  and the streaming check passed on a fresh fixture. All eight focused receipt,
  streaming and offline checks then passed on the fresh fixture. The final
  receipt-label checks also passed on both viewports.
- Python syntax compilation, Git whitespace validation and Docker build passed.
