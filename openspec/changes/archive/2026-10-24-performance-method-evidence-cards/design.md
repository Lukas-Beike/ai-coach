# Design

## Context

See proposal.md for motivation. The method limits for the existing
`personal-quartiles-v1`, `sleep-regularity-v1`, `original-stream-integral-v1`
and load reconstruction live in code and UI text. The future methods M1–M4 have
no implementation yet, and their prerequisites (#1410, #1411, #1418, #1419,
#1420, #1423) are open. The athlete is the independent method reviewer
(decision on #1406, 2026-10-24). The evidence register from #1424 was researched
on 2026-10-24 as a targeted overview, not a systematic review.

## Goals / Non-Goals

**Goals:**

- One durable, versioned, reviewable source of allowed statements per method that
  later code, UI text and Coach context can cite by card ID.
- A cheap automated check that keeps the required structure intact.

**Non-Goals:**

- No runtime enforcement, method registry, UI or Coach change (later packages).
- No formal GRADE assessment, no numeric evidence confidence.
- No full systematic review, no automated literature monitoring.

## Decisions

- **Location and format.** `docs/performance-methods/` with a `README.md`
  (scope, register, review procedure, M5 deferral) and one Markdown card per
  method (`m1-session-rpe-load.md`, `m2-hrv-resting-hr.md`,
  `m3-sleep-duration-timing.md`, `m4-critical-power-speed.md`). Chosen by the
  athlete over an OpenSpec design artifact because cards must outlive one change
  and be referenced from code. Alternative: one large file; rejected because each
  method is reviewed and versioned independently.
- **Fixed headings.** Each card uses the same `##` headings, one per required
  field from #1424, plus a front block with `Card`, `Card version`, `Method ID`,
  `Status`, `Literature checked` and `Review`. The test checks these headings,
  so the structure is enforced without a parser or schema dependency.
- **Numeric rules table.** Every numeric rule appears in a `## Numeric rules`
  table with a `Tag` column restricted to `source` and `product assumption` and a
  non-empty rationale column. Rules already in code cite the code location so a
  later change to the constant is visible against the card.
- **Evidence references.** Cards cite register IDs (`R1`–`R17`, `L1` for the
  unverified lead). The test fails on an ID that is not in the register.
- **Review state.** `Review: blocked` until the athlete's review is recorded as
  `Review: released YYYY-MM-DD (athlete)` per interpretation. Descriptive
  statements are listed separately and are not blocked by the review state, per
  the G0 rule "open domain points block the affected interpretation, not
  independent descriptive work".
- **Verification honesty.** The register records the access level actually
  achieved (abstract / full-text sections / not accessible) and the
  correction/retraction check path per source; unverifiable items stay marked
  open instead of being filled with plausible numbers.

## Risks / Trade-offs

- [Cards drift from code] → numeric rules cite code locations; implementing
  packages must update the card and bump `Card version` with the method version.
- [Literature check is limited by access] → access level per source is explicit;
  the 90-day maintenance rule is recorded as a product assumption, not automated.
- [Reviewer is not a sports scientist] → the card records who reviewed; this is
  the athlete's decision on #1406 and limits claims to the athlete's own use.
- [Structure test gives false assurance] → it checks completeness only; content
  quality is covered by the independent L3 review and the athlete's G0 review.

## Migration Plan

Documentation and a test only; no deployment or rollback steps.
