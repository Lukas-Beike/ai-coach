## ADDED Requirements

### Requirement: Method input fixtures
Every method with an evidence card SHALL have synthetic input fixtures for one complete, one incomplete and one contradictory input set, each with a defined outcome: a value, no value with a status or reason, or an exclusion. The fixtures SHALL keep transport provider, recording origin and local method apart and SHALL count an activity imported from several providers once.

#### Scenario: Incomplete input
- **WHEN** a required input is missing for a method (for example no session RPE, too few earlier nights, or only a downsampled stream)
- **THEN** the fixture asserts that no value is produced or that the input is excluded, with the status or reason the current code gives; where current code still produces a value from that input, the fixture pins it as a known gap naming the owning issue.

#### Scenario: Contradictory providers
- **WHEN** two providers report different values for the same input
- **THEN** the fixture asserts that the values stay separate per provider and method and are not averaged.

Evidence: `tests/test_performance_method_inputs.py`.

### Requirement: Method input trace and gaps
A document SHALL trace each method's inputs from canonical storage to its HTTP, UI and Coach consumers and SHALL map each data gap to an owning issue. A reader that bypasses an available canonical input SHALL be pinned by a fixture assertion naming that issue.

#### Scenario: Gap closed by later work
- **WHEN** a later change makes a reader use a canonical input that it bypasses today
- **THEN** the pinned gap assertion fails with a message naming the owning issue, and the fixture and trace are updated in that change.

Evidence: `docs/performance-methods/inputs.md`, `tests/test_performance_method_inputs.py`.
