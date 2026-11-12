## MODIFIED Requirements

### Requirement: CS5 Explicit competition sync and conflict recovery
The system SHALL keep remote pushes explicit and output-only (Intervals.icu receives competitions and is never a source of them), detect unsafe remote identity/missing-record cases, validate approval freshness, and offer deliberate keep-local/adopt-remote conflict resolution.

#### Scenario: Output only, no import
- **WHEN** a competition sync reads the remote events to match identities
- **THEN** no remote event ever becomes a local competition and a clean local row never takes remote values; a clean linked row inside the fetched calendar window whose remote event is gone, or a dirty unlinked row that matches a remote event only by name and date, is marked as a conflict instead.

#### Scenario: Named approved push
- **WHEN** the athlete explicitly requests competition synchronization, and the manifest is frozen when the request runs
- **THEN** outbound writes use stable identity and supported sport payloads, with concurrent local edits checked before marking captured records synced.

#### Scenario: Conflict choice
- **WHEN** a stored conflict is resolved as keep_local or adopt_remote
- **THEN** keep-local retains a local override for a later explicit push, while adopt-remote requires a valid remote event and updates the local record; invalid strategy, corrupt/missing conflict or unavailable remote data fails explicitly.

Evidence: `backend/planning/competition_service.py:CompetitionService.resolve_conflict`; `backend/planning/competitions.py:competition_remote_match`, `backend/planning/competitions.py:competition_conflict_action`; `backend/sync/competitions.py:CompetitionSyncReconciler`; `tests/test_planning_competition_service.py:test_conflict_resolution_preserves_both_strategies`; `tests/test_sync_competitions.py:test_records_rejects_competition_changes_after_approval`, `tests/test_sync_competitions.py:test_dirty_remote_deviations_persist_identity_changed_and_missing_conflicts`, `tests/test_sync_competitions.py:test_optimistic_check_skips_competition_edited_after_capture`, `tests/test_sync_competitions.py:test_clean_row_keeps_local_indoor_environment_for_the_same_remote_type`.
