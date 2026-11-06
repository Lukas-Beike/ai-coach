# Tasks

## 1. Implementation

- [x] 1.1 Resolve exercises against the pinned `garminconnect` catalogue (explicit name, exercise name, alias) and build the strength workout JSON without the SDK's optional models; verify with MappingTests.
- [x] 1.2 Accept and validate `garmin_exercise` in `strength_structure` and the Coach schema; verify with StructureTests and the existing strength structure tests.
- [x] 1.3 Add the Garmin `plan_push` job (hashed and `remove` entries, Garmin-only removal), the push service and its wiring; verify with JobValidationTests, PushTests, registry and architecture tests.
- [x] 1.4 Document the job, matching, verification and limits in README.

## 2. Validation

- [x] 2.1 Run the changed-test selection, compileall, Ruff and repo-wide mypy on the changed files; record unavailable checks as gaps.
- [x] 2.2 Run `npm run openspec -- validate garmin-strength-workout-push --strict` before archiving.

## Evidence gaps

- No live Garmin call in tests; the schedule response key (`workoutScheduleId`) and the rendering on the watch are verified once with the athlete on the real account after merge, with explicit consent.
