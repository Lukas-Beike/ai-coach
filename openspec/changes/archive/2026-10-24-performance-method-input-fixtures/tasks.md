# Tasks

## 1. Fixtures

- [x] 1.1 M1: ingest a ride from Intervals.icu and Garmin with local feedback; assert one canonical session, per-provider duration fields (`duration_s`, `moving_duration_s`, elapsed), provenance split, feedback keyed by provider id; incomplete (Wahoo-only, no RPE) and contradictory (local RPE versus `icu_rpe`) sets.
- [x] 1.2 M2: personal recovery with complete, incomplete (fewer than 14 earlier nights) and contradictory (Intervals versus Garmin, RMSSD versus SDNN, canonical versus legacy resting HR) inputs; pin the canonical HRV bypass (#1411) and the exact-match override (#1415).
- [x] 1.3 M3: goal shortfall and timing with complete, incomplete and contradictory inputs; pin deviations below 14 intervals and the canonical sleep-duration bypass (#1411), and the absent sleep periods (#1419).
- [x] 1.4 M4: full-resolution power stream of a CP 250 W / W′ 18 kJ rider, Garmin downsampled only, and Intervals full versus Garmin downsampled for one session; assert stored resolution, merge choice and the missing 180/420/720 s windows (#1430).

## 2. Trace document

- [x] 2.1 Write `docs/performance-methods/inputs.md` (inputs, provenance, consumer trace, gaps and persistence needs per issue, fixture index) and link it from the README; verify every file:line reference against the tree.

## 3. Review and validation

- [x] 3.1 Independent L3 review of fixtures and trace; resolve findings with evidence.
- [x] 3.2 Run the focused tests, `python -m unittest discover -s tests -v`, `python -m compileall -q server.py backend tests`, repo-wide Ruff/mypy as in CI, and `npm run openspec -- validate performance-method-input-fixtures --strict`.

## Workflow follow-up

- Sync `performance-and-readiness`, archive the change, then publish through the PR workflow.
