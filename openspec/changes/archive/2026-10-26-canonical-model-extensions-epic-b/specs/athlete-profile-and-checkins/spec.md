# Spec Delta

## ADDED Requirements

### Requirement: Authoritative local zone edits and undo
The athlete SHALL be able to read and explicitly edit local sport-specific zones and thresholds through the supported application contract. Saves SHALL validate units and ascending boundaries, preserve provider alternatives and record change history with undo. Confirmed local configuration SHALL remain authoritative across provider refresh, restart and backup/restore.

#### Scenario: Valid local edit
- **WHEN** an authenticated athlete saves valid local zone boundaries for a sport and metric
- **THEN** effective calendar/plan configuration uses those boundaries, the provider alternative remains separately visible and the save produces an undoable receipt.

#### Scenario: Invalid boundaries
- **WHEN** a save contains nonfinite, incompatible-unit or nonascending boundaries
- **THEN** the whole edit fails without partially modifying existing zones or history.

#### Scenario: Undo after provider refresh
- **WHEN** a saved local zone edit is undone after a provider refresh
- **THEN** the previous local state is restored and effective selection follows local authority or the applicable provider alternative when no local configuration remains.

Evidence baseline: `backend/activities/zone_settings.py`, `backend/change_history.py`, `backend/athlete/profile.py`; `tests/test_zone_settings.py`. Local canonical zone editing and its receipt/undo paths require new implementation and tests.
