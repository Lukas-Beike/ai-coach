## Context

Inspected revision: origin/develop `6eab8617d`. The claim lists are the Allowed/Forbidden sections of `docs/performance-methods/m2-hrv-resting-hr.md` and `m3-sleep-duration-timing.md` (released 2026-10-24 by the athlete). Motivation is in proposal.md.

Where the four points surface today:

- API/Coach: `personal_recovery.note`, the method ids, the `get_training_report` description and its `sleep_regularity` section. The Coach receives the whole `personal_recovery` dict except per-day arrays (`coach_performance_projection`).
- UI: only the HRV and resting-HR comparison band and its labels (`public/analysis.js` lines 175, 1129-1134, 1159-1171). The sleep chart has no band; sleep deficit and regularity are not rendered.
- Docs: README (Erholung paragraphs, "Analysis Coverage"), both cards, `inputs.md`.

## Goals / Non-Goals

**Goals:**
- No runtime text calls a quartile position abnormal, clinical or a normal range, names "sleep debt", or calls the timing method an SRI.
- Product rules are described as product rules; "bestätigt" no longer suggests validity.
- The timing method and its Coach section carry a name that does not claim the SRI.
- A neutral comparison band in both themes.
- Deterministic tests keep the wording and the Coach context limits from regressing.

**Non-Goals:**
- Renaming `regularity`, `*_deviation_minutes`, `sleep_deficits`, `deficit_hours`, `position` or `personal-quartiles-v1` (the words do not claim the SRI, sleep debt or a normal range; provider-neutral key naming stays with #1413).
- Changing thresholds (14/28 nights, 42 days), the algorithm, status values or the "Mindestens 14 …" / "Messung veraltet." reasons.
- Showing sleep goal shortfall or timing variability in the UI; computing a real SRI; naps.
- A new `COACH_PROMPT` rule or any change to the pinned prompt digest (`tests/test_coach_prompt.py`).
- Measuring language-model accuracy. Tests mock OpenAI and check context and instruction text only, as `docs/coach-dialogue-evaluation.md` states.

## Decisions

### D1 Rename the timing method and its section

| Old | New |
|---|---|
| method id `sleep-regularity-v1` | `sleep-timing-variability-v1` |
| report section and result key `sleep_regularity` | `sleep_timing_variability` |
| `personal_recovery.sleep_regularity()` | `sleep_timing_variability()` |
| `TrainingDerivedReadService.sleep_regularity` | `sleep_timing_variability` |

The id keeps `-v1` because the algorithm is unchanged; the name is new, so the evidence cards bump their card version (D9). The enum in `tool_schemas.py`, the `allowed` set and `readers` in `activity_read_tools.py`, mocks and fixtures change in the same commit. The `regularity` key of the `personal_recovery` dict and the `*_deviation_minutes` points stay: "regularity" alone is a plain English word, and the athlete asked to keep fields unless a rename is needed for the shared-name rule. The rule is satisfied by the method id, the section name, the descriptions and the not-SRI statement. Alternative considered: also rename `regularity` to `timing`. Rejected: it changes the API shape and every consumer without removing an additional claim.

### D2 Persistence check and compatibility

Searched `backend/`, `public/`, `tests/`, `e2e/`, `docs/`, `openspec/` and the schema for the old names.

- Not stored as a key: `personal_recovery` is computed per request from observations; the method id is part of the response only. The PWA device snapshot (`public/state-loader.js`, `localStorage`) may hold an old response, but no UI code reads `regularity.method`, and the next state load replaces it.
- `coach_commands.receipt` (JSON) keeps `command_receipts[].result` of past tool calls, so a historic `get_training_report` result contains the key `sleep_regularity` and the old method id. Replays are matched by `call_id`/`effect_key` and return the stored result without revalidating arguments (`backend/coach/tool_replay.py`); the receipt is not parsed by section name anywhere else. The tool-round journal stores only `call_id` and tool name.
- `DiagnosticCapture` (key-value, redacted, bounded) may hold old tool arguments as evidence text. It is never parsed back.
- OpenAI Responses chains are per command (bounded); a section name in an old chain is history only.

Decision: no alias and no data migration. A model that repeats the old section name receives the existing validation error `Unbekannter Analysebereich.` and retries with the current schema through the normal tool-failure path. Fallback if this proves noisy: accept `sleep_regularity` in `allowed` as a hidden alias mapped to the new reader. Not added, because it would keep the old name alive in code. No schema change is involved, so the migration contract (versioned migrations, frozen fixtures) is not triggered.

### D3 Wording (final copy)

| Place | New text |
|---|---|
| Position labels (`analysis.js:1161`) | "Unter dem Bereich deiner früheren Werte" / "Im Bereich deiner früheren Werte" / "Über dem Bereich deiner früheren Werte" |
| Reference label with band (`recoveryReferenceLabel`) | `<position> · <lower>–<upper>` plus " · vorläufig" when `provisional`. No "Basis", no "Status:" suffix. |
| Reference label without band | the backend `reason` as is ("Mindestens 14 frühere passende Nächte erforderlich.", "Messung veraltet."), without "Persönliche Basis:" and without "Status:" |
| Sleep reference label | "Durchschnitt der angezeigten Werte" (no status suffix; sleep has no band) |
| Band tooltip (`analysis.js:175`) | "Mittlere Hälfte deiner früheren Werte (Quartile) · 42 Tage vor der letzten Messung" plus " · vorläufig" |
| Coverage (`analysis.js:1163`) | " Vergleich mit N früheren Nächten." |
| Group note (`analysis.js:1171`) | removed (`note` is empty; `analysisChartGroup` already skips an empty note) |
| Sleep goal helper (`index.html:243` `<small>`) | removed; the label "Persönliches Schlafziel (Stunden)" stays |
| `personal_recovery.note` (German, Coach-visible) | "Quartile vergleichen den letzten Wert mit deinen eigenen früheren Werten. Die mittleren zwei Quartile enthalten per Definition etwa die Hälfte der Werte; ein Wert außerhalb ist weder selten noch ein Warnsignal. Keine Diagnose, keine Trainingsfreigabe und keine Trainingsänderung allein aus einer Abweichung. Krankheit und Schmerzen separat berücksichtigen. Quellen und Messfelder werden nicht gemischt. Der Fehlbetrag zum Schlafziel summiert nur bekannte Nächte und wird nicht mit längeren Nächten verrechnet; fehlende Nächte und nicht erfasste Nickerchen begrenzen diese Aussage. Die Schlafzeit-Streuung ist kein Sleep Regularity Index." |
| `get_training_report` description (appended, English) | "sleep_timing_variability reports sleep onset and wake clock-time deviations from the athlete's own earlier nights; it is not the Sleep Regularity Index. Describe observed values; make no diagnosis and derive no training clearance or change from an isolated deviation." |

`providerMetricStatus` (which mapped `ok` to "bestätigt") has no caller left once the recovery labels drop the status, so it is deleted; the provider-metric charts never used it. The `position` values stay `below`/`within`/`above` in the API. The wording "Bereich deiner früheren Werte" follows the issue ("above your previous comparison distribution") and the M2 allowed statement, which is updated to match (D9). Label lengths are checked at 320 px in the mobile-small project.

### D4 Coach text without a prompt rule

The limits live in the `note` and the tool description (D3), both data/schema text. `COACH_PROMPT` rule 2 already requires conservative, non-diagnostic answers when data is contradictory, so a new rule would only add digest churn. `coach_performance_projection` keeps `note` and the `regularity` summary, so the text reaches the Coach in every recovery context. The scan (D6) and the Coach cases (D7) pin this.

### D5 Neutral comparison band

`.analysis-baseline-band` fills with `--chart-baseline`, which is defined only for this class (`#22c55e` dark in `:root`, `#16a34a` in `:root[data-theme="light"]`). Replace the fill with the existing neutral `var(--muted)` (`#a1a1a7` dark, `#5d5d5d` light) and remove the two `--chart-baseline` declarations. The opacities (.17 dark, .14 light) stay.

Contrast evidence (WCAG 1.4.11, series stroke against the band composited on the real card surface). The first column pair was computed at design time on the page background; the measured values from the disposable fixture (`vsBand`, `vsSurface`) at apply time are dark band `#323235` with 3.91, 4.67, 5.93, 4.72 against the band and 5.24, 6.27, 7.97, 6.34 against the surface; light band `#e8e8e8` with 4.11, 4.66, 4.86, 5.14 and 5.02, 5.70, 5.93, 6.29.

| Theme | Band colour | Series 1-4 against band | Series 1-4 against background |
|---|---|---|---|
| dark | `#252527` | 4.70, 5.62, 7.14, 5.68 | 6.04, 7.23, 9.18, 7.31 |
| light | `#e8e8e8` | 4.10, 4.65, 4.84, 5.13 | 5.02, 5.70, 5.93, 6.29 |

All stay at or above 3:1, and the neutral band lowers contrast no more than the green one did (green band: 4.67-7.09 dark, 4.29-5.37 light). The band is decorative: its meaning is carried by the text label. `public/styles.css?v` and `public/service-worker.js` change with it (D10).

### D6 Forbidden-term scan

A unit test `tests/test_performance_claim_wording.py` scans the runtime sources that produce these statements: `backend/performance/personal_recovery.py`, `backend/performance/report_service.py`, `backend/coach/tool_schemas.py`, `backend/coach/context.py`, `backend/coach/activity_read_tools.py`, `public/analysis.js`, `public/index.html`, plus the JSON-serialized output of `personal_recovery` for the D7 fixtures. Docs and specs are excluded because they name the terms to forbid them.

Forbidden (case-insensitive): `sleep debt`, `Schlafschuld`, `Schlafdefizit`, `Normalbereich`, `normal range`, `üblichen Bereich`, `Grüner Bereich`, `abnormal`, `auffällig`, `klinisch`, `clinical`, `Basis` (UI recovery labels only), `Sleep Regularity Index` and `SRI`. The last two are allowed only in a negating phrase (`not`/`kein`/`keine`/`nicht` within three words before them). The identifiers `sleep-regularity-v1` and `sleep_regularity` are forbidden after the rename; the unchanged `regularity` field is allowed. The test fails with file, line and term. It is the runtime enforcement that the claim-lists requirement promised for #1426.

### D7 Deterministic Coach cases

A test module `tests/test_personal_recovery_coach_cases.py` builds synthetic observations with the existing helper (`tests/canonical_recovery_support.py:mapped_personal_recovery`), runs `coach_performance_projection`, and asserts structure and text. Its docstring states that it checks context and instruction text, not model quality (`docs/coach-dialogue-evaluation.md`).

| Case | Fixture | Assertions |
|---|---|---|
| Small data | 9 earlier nights | `status = insufficient_data`, no `position`/`median`/`lower`/`upper`, `reason` is the unchanged 14-night text; `note` carries the no-clearance sentence |
| Fresh device change | Intervals series ends, a new Garmin series starts with 3 nights | two separate baselines, each with its own `nights`; the new one `insufficient_data`; no cross-provider baseline |
| Stale values | newest value 3 days old with 30 earlier nights | `reason = "Messung veraltet."`, no `position`; the old value stays in `value`/`observed_at` |
| Contradictory check-in | HRV `within` with 30 nights, a real `CheckinService` (in-memory store) holding a check-in reporting heavy legs, the context built through the real `CoachStructuredContextService` | `local_feedback.today` carries the check-in while `current_performance.personal_recovery` keeps `position: "within"` and contains none of the check-in text; `note` states that a deviation alone gives no clearance or change; the existing `COACH_PROMPT` markers stay unchanged |

Each case also runs the D6 scan over the serialized projection.

### D8 Independence from Epic B PR #1464 and expected rebase conflicts

Implement on develop; PR #1464 (`t3/canonical-extensions-issues-1408-1423`) may land first or second. Overlaps found with `git diff origin/develop...t3/canonical-extensions-issues-1408-1423`:

- `public/service-worker.js`: cache `v513` here, `v516` there, and the `ASSETS` line. Certain conflict: re-bump on top of the merged value.
- `public/index.html`: script versions of `app.js`, `settings.js`, `activity-details.js` change there; our `analysis.js`/`styles.css` lines are adjacent. Mechanical.
- `backend/performance/personal_recovery.py`: that branch adds `periods=` to `sleep_regularity(...)`, new helpers and docstrings. Our rename touches the same function header, the two `"method"` values and the docstrings. Textual conflict; keep its logic, apply our names.
- `tests/test_sleep_regularity_canonical_parity.py` (new there), `tests/test_sleep_period_mapping.py`, `backend/canonical/sleep_bounds.py`, `backend/providers/sleep_period_mapping.py`: reference `sleep-regularity-v1` and `sleep_regularity()`. Whoever lands second renames them; the parity test file name may stay.
- `openspec/specs/performance-and-readiness/spec.md`: that branch adds the requirement "Canonical sleep regularity parity" naming `sleep-regularity-v1` and "original SRI". The delta cannot modify a requirement that did not exist on develop at planning time. Once #1464 had merged, the rename was applied directly to the main spec (requirement now "Canonical sleep timing variability parity", naming `sleep-timing-variability-v1`) in the rebase commit that applies the rename to the canonical sleep periods.
- `e2e/analysis-info.spec.js` (recovery fixtures near lines 146 and 419), `docs/performance-methods/m3-sleep-duration-timing.md`, `inputs.md`, README, `backend/coach/context.py`: different hunks, mechanical merges.

#1464 landed first; this branch was rebased on it and the rename grep (task 1.1) rerun. Either way, a search for `sleep.regularity|sleep_regularity` must return only the unchanged `regularity` field and archived changes.

### D9 Evidence cards and athlete review

M2 and M3 get `Card version: 2`. M3: method id line, timing formula heading, allowed statements, and the closed open point "Rename 'sleep deficit' and the regularity label … (#1426)". M2: the allowed statement "within your usual range" becomes "within the range of your earlier values". The implementation does not touch the `Review` line: changed allowed statements need the athlete's release (`released YYYY-MM-DD (athlete)`), so the PR description asks the athlete to confirm. `tests/test_performance_method_cards.py` keeps passing because sections and tags are unchanged. Stale line numbers in the numeric-rule tables are pre-existing; only rows touched by this change are corrected.

### D10 Asset versions

Bump `analysis.js` 136 to 137 and `styles.css` 341 to 342 in `public/index.html` and in `public/service-worker.js` `ASSETS`, and the cache name `intervals-coach-v513` to `v514`, in one commit. `tests/test_server_frontend.py` (`asset_ref`) and `tests/service-worker-update.test.cjs` enforce the pairing. `index.html` itself is not versioned.

## Risks / Trade-offs

- [A model repeats the removed section name] → one validation error and a retry (D2). The alias fallback is documented.
- [Rename misses a consumer] → the final search (task 1.1) and the unit tests for the tool enum and reader.
- [Coach answers still over-claim] → tests prove only that the limits are present in context and instruction text; real model behavior is not measured and is not claimed.
- [Label length at 320 px] → the Playwright mobile-small project runs the affected specs.
- [Neutral band is less visible in light mode] → ratios in D5; recheck against the real surface; the opacity can be raised without changing the token.
- [Card edit without athlete release] → D9; the PR asks for the release.
- [Rebase friction with #1464] → D8.

## Migration Plan

No schema or data migration. Rollback is a plain revert: the renamed names are not persisted (D2). Cached PWA clients pick up the new assets through the cache-name bump and the existing update path.

## Open Questions

None. The rename, the neutral band, no prompt rule, the kept reasons and the cut helper texts were decided by the athlete on 2026-10-26.
