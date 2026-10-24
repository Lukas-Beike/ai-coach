# Proposal

## Why

Epic S (#1409) adds local performance and recovery metrics M1–M4. Work package
P0 (#1424, gate G0) requires that every intended statement is mapped to a source
or to an explicit product assumption before a method's physiological
interpretation is implemented or released. Today the method limits live only in
code comments, UI text and the issue body, so no durable, reviewable reference
exists for later implementations and Coach wording.

## What Changes

- Add versioned evidence cards for M1 session-RPE load, M2 personal HRV and
  resting HR description, M3 sleep duration and timing, and M4 Critical Power /
  Critical Speed under `docs/performance-methods/`, with the field set required
  by #1424.
- Add an evidence register (R1–R17 plus the unverified lead) with access level,
  verification date and correction/retraction check, and record M5 (#1432) as
  deferred.
- Add per-method claim lists (allowed/forbidden statements for API, UI and Coach).
- Tag every numeric product rule as `source` or `product assumption` with
  rationale, including rules already implemented in `personal-quartiles-v1`,
  `sleep-regularity-v1` and the existing load/best-effort code.
- Record the athlete as the independent method reviewer (decision on #1406) and
  keep each card's physiological interpretation `blocked` until that review is
  recorded on the card.
- Add a repository test that rejects a card with a missing required field, an
  untagged numeric rule, or an unknown evidence reference.
- No application behavior, API, UI, persistence or schema change.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `performance-and-readiness`: adds a requirement that local methods with a
  physiological interpretation are governed by a reviewed evidence card and its
  claim list.

## Impact

- New documentation: `docs/performance-methods/` (README/register, four cards).
- New test: `tests/test_performance_method_cards.py` (stdlib only, no data).
- Main spec `openspec/specs/performance-and-readiness/spec.md` gains one
  requirement after sync.
- Follow-up issues (#1425, #1426–#1433) reference the cards; their gates stay
  bound to the prerequisites in #1409.
