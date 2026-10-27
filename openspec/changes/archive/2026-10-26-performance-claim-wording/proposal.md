## Why

Issue #1426 (Epic S #1409, gate G2) corrects four overclaiming points in the existing recovery outputs, using the released evidence cards M2 and M3 (`docs/performance-methods/`, gate G0 #1424) as the claim list:

1. Personal quartiles are a comparison with the athlete's own earlier values. The middle two quartiles hold about half of the values by definition, so a value outside them is neither rare nor a normal-range violation, and never abnormal or clinical.
2. 14/28 nights, the 42-day window, status `ok` and `personal-quartiles-v1` are product rules. They prove neither medical validity nor an optimal baseline.
3. The sleep deficit is the sum of known shortfalls against the athlete's own sleep goal. It is not sleep debt and not a recovery need.
4. `sleep-regularity-v1` compares clock times circularly with the athlete's own earlier nights. It is not the Sleep Regularity Index (Phillips, R13) and must not share its name.

The athlete decided on 2026-10-26 to rename the timing method and its Coach section now instead of deferring to #1413, and to replace the green comparison band with a neutral one.

## What Changes

Existing behavior (verified in source on origin/develop `6eab8617d`):

- `backend/performance/personal_recovery.py:personal_recovery` returns `method: "personal-quartiles-v1"`, `baselines` with `position` (`below`/`within`/`above`), `sleep_deficits` (`deficit_hours`), `regularity` (`method: "sleep-regularity-v1"`) and a German `note`: "Persönliche Quartile beschreiben Abweichungen, keine medizinische Trainingsfreigabe. ... lange Nächte gleichen Defizite nicht rechnerisch aus." The note is the only wording of these metrics the Coach receives (`backend/coach/context.py:coach_performance_projection` passes it through). `COACH_PROMPT` and the dialogue instructions mention none of the four points.
- `backend/coach/tool_schemas.py` (`get_training_report`) and `backend/coach/activity_read_tools.py` expose the section `sleep_regularity`, served by `TrainingDerivedReadService.sleep_regularity` (`backend/performance/report_service.py`).
- `public/analysis.js` shows, for HRV and resting HR only, a band tooltip "Grüner Bereich: persönliche Quartile · 42 Tage vor der letzten Messung", position labels "Unter / Innerhalb / Über deinem üblichen Bereich", a reference label "… · Basis a–b · Status: bestätigt" (`providerMetricStatus` maps `ok` to "bestätigt"), "Persönlicher Bereich aus N früheren Nächten." and the group note "Persönliche Normalbereiche werden nur für HRV und Ruhepuls angezeigt." The band is filled with `--chart-baseline` (green, `public/styles.css`).
- The UI shows neither the sleep deficit nor the regularity (`e2e/analysis-info.spec.js` asserts "Schlafdefizit" and "Schlafregelm" are absent). `public/index.html` carries the helper "Bestätigtes Ziel für die Auswertung bekannter Nächte; keine automatische Vorgabe." under the sleep goal.
- The evidence cards already forbid the four statements and list the rename as an open point (M3, `inputs.md` gap table); nothing enforces them at runtime (`performance-and-readiness`: "Runtime enforcement is added by the implementing work packages (#1426–#1431)").

Proposed behavior:

- **BREAKING (identifier)** The timing method id becomes `sleep-timing-variability-v1` and the Coach report section `sleep_regularity` becomes `sleep_timing_variability`, with the internal function and service method. The algorithm, thresholds, API fields (`regularity`, `*_deviation_minutes`, `sleep_deficits`, `deficit_hours`, `position`) and `personal-quartiles-v1` are unchanged. No stored value uses the old names in a way that is read back (design D2); there is no alias.
- The `personal_recovery.note` states the limits in neutral words: comparison with the athlete's own earlier values, middle quartiles hold about half of the values, no health norm, no diagnosis, no training clearance or change from an isolated deviation, shortfall counts known nights only and is not offset. It avoids the forbidden terms.
- The `get_training_report` description states that `sleep_timing_variability` is clock-time variability against the athlete's own earlier nights, not the Sleep Regularity Index, and that the Coach describes observed values without diagnosis or training clearance. No new `COACH_PROMPT` rule, so the pinned prompt digest stays valid.
- UI labels drop "Grüner Bereich", "üblichen Bereich", "Normalbereich", "Basis" and the "bestätigt" status for recovery baselines, and say "Bereich deiner früheren Werte". The group note and the sleep-goal helper are cut (repository helper-text rule). The band uses a neutral existing token in the light and dark themes.
- A forbidden-term scan test and four deterministic Coach cases (small data, fresh device change, stale values, contradictory check-in against objective values) pin the wording. They test context and instruction text, not model behavior.
- M2 and M3 are updated (card version 2, rename, allowed statements, closed open points), together with `inputs.md`, README and the coach evaluation document.
- Unchanged reasons: "Mindestens 14 frühere passende Nächte erforderlich." and "Messung veraltet." state product rules and stay.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-and-readiness`: the baseline/deficit requirement is renamed to comparison and sleep goal shortfall with the four wording rules; the sleep timing requirement gets the new name and the not-SRI rule; claim lists gain runtime enforcement.
- `coach-context-and-provenance`: the deterministic report section is `sleep_timing_variability`; recovery reads carry their limits to the Coach.
- `web-pwa-and-accessibility`: recovery comparison labels and the neutral band.

## Impact

- Backend: `backend/performance/personal_recovery.py`, `backend/performance/report_service.py`, `backend/coach/activity_read_tools.py`, `backend/coach/tool_schemas.py`, `backend/coach/context.py` (docstring).
- Frontend: `public/analysis.js`, `public/styles.css`, `public/index.html`, `public/service-worker.js` (asset versions and cache name together).
- Tests: `tests/test_personal_recovery.py`, `tests/test_coach_activity_read_tools.py`, `tests/test_training_report.py`, `tests/test_performance_method_inputs.py` (messages), `e2e/analysis-info.spec.js`, `e2e/training-feature-panels.spec.js`, plus the new scan and Coach-case tests.
- Docs: `docs/performance-methods/m2-hrv-resting-hr.md`, `m3-sleep-duration-timing.md`, `inputs.md`, `README.md`, `docs/coach-dialogue-evaluation.md`.
- Data: no schema change and no migration. The method id and section name are computed per request and not stored as a key; only historic Coach receipts and diagnostic captures contain the old strings as inert text (design D2).
- Compatibility: independent of Epic B PR #1464 (`t3/canonical-extensions-issues-1408-1423`); expected rebase conflicts are listed in design D8.
