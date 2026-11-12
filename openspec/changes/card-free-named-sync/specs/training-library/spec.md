## MODIFIED Requirements

### Requirement: TL10 Exact explicit sync selection and complete repair manifests
The system SHALL bind explicit plan pushes to concrete local IDs/current hashes, resolve created/all-pending selections on the server, and require a complete future-period manifest for repair rather than widening a partial model selection.

#### Scenario: Selected, created or all-pending push
- **WHEN** a named plan sync selects existing units, this turn's successfully created units or all pending units
- **THEN** selected entries require exact current IDs/hashes, created resolves only successful additions from this turn, and all-pending freezes the server-resolved concrete selection; later additions do not expand it.

#### Scenario: Complete repair request
- **WHEN** an explicit repair requests a future period with current revision and no entries
- **THEN** the server includes active, already-synced and superseded inactive units in that period, validates the complete current manifest, and queues bounded provider jobs; an explicit incomplete selection conflicts.

#### Scenario: Failed prerequisite or stale manifest
- **WHEN** local creation failed, current hashes/revision changed or approval no longer matches
- **THEN** no dependent push is queued and the caller must repair/reread the actual local state rather than sync partially created data.

#### Scenario: Conflict recovery and job retry
- **WHEN** an explicit conflict choice reaches the authorized conflict service or a failed/partial sync job is retried
- **THEN** the recorded strategy is applied locally or the original job is retried with its original provider and required read/push authority; a mismatched provider or remote-write declaration is rejected.

Evidence: `backend/coach/tool_preparation.py:CoachStructuredToolPreparationService._prepare_plan_sync`; `backend/coach/proposal_creation.py:_approved_plan_sync_arguments`; `backend/sync/plan_selection.py:StructuredPlanSyncService`; `backend/sync/plan_repair.py:PlanRepairManifestService`; `backend/sync/plan_commands.py:PlanPushCommandService.enqueue`; `backend/coach/sync_tools.py:CoachSyncToolService._resolve_conflict`; `tests/test_coach_tool_preparation.py:test_created_plan_sync_projects_exact_ids_and_scopes`, `tests/test_coach_tool_preparation.py:test_all_pending_captures_a_concrete_manifest_for_approval`, `tests/test_coach_tool_preparation.py:test_selected_sync_requires_entries_unless_repairing`; `tests/test_coach_sync_tools.py:test_plan_repair_checks_object_scopes_before_mutation`, `tests/test_coach_sync_tools.py:test_retry_requires_matching_provider_and_remote_write_intent`; `tests/test_coach_tool_coverage.py:test_all_pending_sync_binds_the_units_pending_at_the_request`. Intervals planned-calendar execution and recovery are specified in TL11-TL15; no real remote sync was exercised here. The local-choice tool's catalog/write-gate mismatch is recorded separately rather than promised as universally available through chat.
