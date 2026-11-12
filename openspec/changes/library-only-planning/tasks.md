## 1. Template reference

- [x] 1.1 Carry `template_id` through the planned-unit normalizers, the structured change and draft schemas, and keep it out of the push payload hash
- [x] 1.2 Set `template_id` when a library template is scheduled (`apply_workout_library_plan`) or matched during plan creation; drop the free-content fallback (TP3)

## 2. Plan check

- [x] 2.1 Add `template_conformance` with the required `template_missing` and `template_mismatch` findings and the `template_scaled` note; content fingerprint without date so moving an older unit passes
- [x] 2.2 Feed the undated library templates into `PlanGuardService.findings`

## 3. Adaptive replanning

- [x] 3.1 Strength: only the light strength intensity, exercises, sets and weights unchanged; run and ride replacements marked `source: adaptive` and exempt

## 4. Coach and UI

- [x] 4.1 Prompt, playbooks and tool descriptions plan from the library and propose a template first when none fits
- [x] 4.2 Expanded planned unit shows "Vorlage: <name>"

## 5. Validation

- [x] 5.1 Regression tests: ad-hoc unit rejected; unit from a template keeps exercises and order; scaled variant saved with a receipt note; no template leads to a template first; older unit moves; adaptive strength keeps weights
- [x] 5.2 Run `python tests/run_tests.py --changed`, ruff, mypy, `node --test tests/*.cjs`, the affected browser spec where available (record unavailable checks as gaps), and `python scripts/spec_validate.py --change library-only-planning`

## Evidence gaps

- The browser check of the template label covers the plan views spec where the local Playwright runner is available; no live model run of the new dialogue cases (they go to #2221).
