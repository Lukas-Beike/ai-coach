## ADDED Requirements

### Requirement: Versioned method evidence cards
Every local performance or recovery method with a planned or offered physiological interpretation SHALL have a versioned evidence card in `docs/performance-methods/`. Each card SHALL record construct, formula, sources, population, protocol, exclusion and stop rules, deviations, classification, claim list and review state. Every numeric rule SHALL be tagged `source` or `product assumption` with a rationale. No numeric evidence confidence SHALL be invented.

#### Scenario: Card is incomplete
- **WHEN** a card lacks a required section, has a numeric rule without a valid tag or rationale, or cites an evidence ID missing from the register
- **THEN** the repository card check fails.

#### Scenario: Deferred method
- **WHEN** a method family is recorded as deferred in the register (M5)
- **THEN** it has no card and produces no output until its own work package adds one.

Evidence: `docs/performance-methods/README.md` and the four method cards; `tests/test_performance_method_cards.py`.

### Requirement: Claim lists bound physiological statements
API, UI and Coach output SHALL NOT make statements that the method's card forbids. A physiological interpretation SHALL stay blocked until the independent review recorded on its card releases it; descriptive statements that the card allows MAY be shown before that review.

#### Scenario: Interpretation not yet reviewed
- **WHEN** a card records the interpretation as `blocked`
- **THEN** the method is limited to the card's descriptive statements, and no training clearance, diagnosis or model-based recommendation is derived from it.

#### Scenario: Reviewed interpretation
- **WHEN** the card records `released` with date and reviewer for an interpretation
- **THEN** implementations may present exactly the allowed statements for it, with the card's limits and status.

Evidence: claim lists in `docs/performance-methods/m1-session-rpe-load.md`, `m2-hrv-resting-hr.md`, `m3-sleep-duration-timing.md`, `m4-critical-power-speed.md`. Runtime enforcement is added by the implementing work packages (#1426–#1431); this change does not alter current runtime output.
