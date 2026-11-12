## MODIFIED Requirements

### Requirement: TP3 Local plan creation and reusable-template matching
The system SHALL save a requested plan's sessions locally, optionally create named plan metadata, link created units to that plan and create a unit only from a library template (`template_id`) without a remote call.

#### Scenario: Named local plan
- **WHEN** normalized sessions are saved with a plan name
- **THEN** plan metadata spans the created sessions, units carry its plan ID/name and the transaction advances planning state with audit records.

#### Scenario: Matching template
- **WHEN** a saved template satisfies the implemented sport, content, duration and conservative similarity checks
- **THEN** its supported workout content is copied into the planned unit with library source and its `template_id`, while retaining the requested local date and plan membership.

#### Scenario: No valid match or storage conflict
- **WHEN** no suitable template exists and the session names none
- **THEN** the Coach plan write is rolled back with `template_missing` (training-library: Planned units come from library templates) instead of storing free Coach content; a calendar or persistence failure aborts the owning plan transaction rather than leaving partial units.

Evidence: `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService.save`, `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService._save_in_db`, `backend/planning/local_plan_creation_service.py:LocalTrainingPlanCreationService._planned_workout_for_storage`; `backend/planning/library.py:find_similar_library_workout`; `tests/test_planning_library.py:test_exact_and_conservative_near_matches`, `tests/test_planning_library.py:test_no_match_for_unrelated_or_invalid_candidates`; `tests/test_training_plan_artifact_service.py:test_late_local_plan_failure_rolls_back_all_writes`; `tests/test_coach_tool_coverage.py:test_requested_draft_commit_and_metadata_lifecycle`.
