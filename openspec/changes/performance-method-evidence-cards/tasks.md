# Tasks

## 1. Evidence register and card structure

- [x] 1.1 Write `docs/performance-methods/README.md` with scope, the three-proof standard, register R1–R17 and lead L1 (access level, check date, correction/retraction check path), search blocks and limits, review procedure, 90-day maintenance rule as product assumption, and the M5 deferral; verify every row against the 2026-10-24 literature verification report.
- [x] 1.2 Add `tests/test_performance_method_cards.py` checking required headings and front block, `Tag` values in numeric-rule tables, non-empty rationales and known evidence IDs; verify with `python -m unittest tests.test_performance_method_cards -v` failing on a deliberately broken temporary copy and passing on the cards.

## 2. Method cards

- [x] 2.1 Write `m1-session-rpe-load.md` (formula, CR-10 anchors as verified, duration definition, collection timing, D3 RPE source rule, claim list, numeric rules); verify with the card test.
- [x] 2.2 Write `m2-hrv-resting-hr.md` covering the existing `personal-quartiles-v1` rules (42/83 days, 14/28 nights, inclusive quartiles, plausibility bounds) and planned device/method segmentation; verify with the card test.
- [x] 2.3 Write `m3-sleep-duration-timing.md` covering sleep-goal shortfall, `sleep-regularity-v1` clock-time deviation (not SRI) and SRI entry conditions; verify with the card test.
- [x] 2.4 Write `m4-critical-power-speed.md` covering both models, three-point release rule, protocol choice, reference cases (350/292.857142857/275 W; 920/1880/3080 m) and current window gap; verify with the card test.

## 3. Review and validation

- [x] 3.1 Obtain an independent L3 review of the register and cards for unsupported claims, citation mismatches and untagged rules; resolve findings with evidence.
- [ ] 3.2 Present the cards to the athlete for the G0 review and record the result (`released` per interpretation, or `blocked` with the open points) on each card.
- [ ] 3.3 Run `python -m unittest discover -s tests -v`, `python -m compileall -q server.py backend tests`, repo-wide Ruff/mypy as in CI, and `npm run openspec -- validate performance-method-evidence-cards --strict`.

## Workflow follow-up

- Sync `performance-and-readiness`, archive the change, then publish through the PR workflow.
