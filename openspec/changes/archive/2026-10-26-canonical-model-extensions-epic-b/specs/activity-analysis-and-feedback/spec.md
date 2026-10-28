# Spec Delta

## ADDED Requirements

### Requirement: Session-owned effective feedback
Feedback SHALL resolve to canonical session identity across provider imports. Each session SHALL expose one effective feedback and one effective sRPE contribution. Legacy conflicting feedback SHALL remain recoverable with deterministic selection; heuristic similarity alone SHALL not combine athlete feedback.

#### Scenario: Same session through two providers
- **WHEN** two provider activities are confirmed copies of one session and feedback is saved through either supported reference
- **THEN** reads expose the same effective feedback and session-RPE is counted once.

#### Scenario: Existing conflicting feedback
- **WHEN** an upgrade or confirmed merge encounters different feedback on two provider copies
- **THEN** every original row remains recoverable and the effective selection is deterministic and exposes the conflict rather than averaging or discarding athlete input.

### Requirement: Feedback identity survives lifecycle changes
Merge, provider deletion, restart and backup/restore SHALL preserve athlete feedback and the session it was written for, so a later unmerge can restore the association without loss. Undo of a feedback save or clear SHALL restore the prior records and values without duplicating the effective feedback. Provider deletion SHALL not delete local feedback.

#### Scenario: Merged copies and feedback undo
- **WHEN** sessions with saved feedback are merged and a later feedback save or clear is undone
- **THEN** merged reads count feedback once and undo restores every prior feedback record with its original session association.

#### Scenario: Provider activity deleted
- **WHEN** a provider copy is marked deleted
- **THEN** stored athlete feedback remains intact and reachable through its canonical session/history.

#### Scenario: Existing save and Coach contracts
- **WHEN** feedback is saved or undone through the supported API or an athlete-started Coach turn
- **THEN** existing partial-edit, validation, authorization, receipt and undo behavior remains available.

Evidence baseline: `backend/activities/feedback.py`, `backend/activities/activity_reference.py`, `backend/db/repositories.py:ActivityFeedbackRepository`; `tests/test_activity_feedback.py`, `tests/test_activity_reference.py`. Canonical session resolution and lifecycle evidence are new acceptance checks.
