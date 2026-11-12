## MODIFIED Requirements

### Requirement: Authoritative local zone edits and undo
The athlete SHALL be able to read and explicitly edit local zones and thresholds for riding, running and swimming (power, heart rate or pace) through Profil → Zonen & Schwellen, one page per sport. Saves SHALL validate units, three to seven ascending boundaries and the required threshold, preserve provider alternatives and record change history with undo. Confirmed local configuration SHALL remain authoritative across provider refresh and restart.

#### Scenario: Valid local edit
- **WHEN** an authenticated athlete saves valid local zone boundaries for a sport and metric
- **THEN** effective calendar/plan configuration uses those boundaries, the provider alternative remains separately visible and the save produces an undoable receipt.

#### Scenario: Invalid boundaries
- **WHEN** a save contains nonfinite, incompatible-unit or nonascending boundaries
- **THEN** the whole edit fails without partially modifying existing zones or history.

#### Scenario: Removal needs confirmation
- **WHEN** the athlete removes local zones
- **THEN** the request is rejected unless it carries an explicit confirmation, the provider zones apply again afterwards, and the removal produces an undoable receipt.

#### Scenario: Stale threshold warning
- **WHEN** an active FTP, lactate-threshold heart rate or threshold pace is older than 56 days, is past its source's age limit, comes from Garmin while the unofficial Garmin SDK is failing, or a locally saved indoor FTP is older than 56 days
- **THEN** the zone view lists one line per threshold with its value, source and age (or the reason it is no longer used), asks to save new values locally, and names the count in the closed section's summary line and the status strip without opening the section; fresh thresholds, an undated local value, and indoor rides without a saved indoor FTP (they use the cycling FTP) produce no warning, and no value is estimated.

#### Scenario: Undo after provider refresh
- **WHEN** a saved local zone edit is undone after a provider refresh
- **THEN** the previous local state is restored and effective selection follows local authority or the applicable provider alternative when no local configuration remains.

Evidence: `backend/athlete/zones.py:ZoneConfigurationService.save`, `backend/athlete/zones.py:ZoneConfigurationService.remove`, `backend/athlete/zones.py:ZoneConfigurationService.restore_in_transaction`, `backend/athlete/zones.py:local_configuration`, `backend/http_api/athlete_put.py:AthletePutRoutes._handle_zones`, `backend/activities/zone_settings.py`, `backend/performance/threshold_staleness.py`, `public/settings.js::saveZones`, `public/settings.js::removeZones`, `public/settings.js::zoneWarningLine`; `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_save_keeps_provider_alternatives_and_survives_a_refresh`, `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_undo_restores_the_previous_local_state_after_a_refresh`, `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_removal_needs_confirmation_and_can_be_undone`, `tests/test_zone_configuration_canonical.py:LocalZoneEditTests.test_an_invalid_edit_changes_nothing`, `tests/test_threshold_staleness.py:AssessTests.test_stale_threshold_names_value_source_and_age`, `tests/test_threshold_staleness.py:AssessTests.test_indoor_ftp_is_judged_only_when_the_athlete_set_one`, `tests/test_threshold_staleness.py:ServiceTests.test_indoor_rides_use_the_ride_ftp_without_a_warning`, `tests/zone-warnings.test.cjs`, `tests/test_zone_settings.py`. Backup/restore of local zones has no dedicated test.

## ADDED Requirements

### Requirement: Zones and thresholds on one page per sport
Profil SHALL order its closed sections Person, Ziele & Woche, Zonen & Schwellen, Training, Quellen & Coach. Zonen & Schwellen SHALL show one page per sport with LT1 and LT2 on top and every zone kind of the sport below, each with its source and a "Bearbeiten" that opens the editor prefilled with the values in effect today; saving stores local values only.

#### Scenario: Thresholds
- **WHEN** the athlete opens a sport's page
- **THEN** LT2 shows the current threshold power (FTP) or threshold pace and the threshold heart rate with their source and date; LT1 shows the heart rate from the stored share of that threshold heart rate (measured or estimated from heart-rate variability) and the power or pace at the upper limit of zone 2 of the zones in effect, labelled as derived from the zones; a missing value shows "—".

#### Scenario: Zone kinds
- **WHEN** a sport has power, pace or heart-rate zones in effect, including Garmin's zones for all sports
- **THEN** each kind lists its zones with name, range and percent basis and its source ("Lokal gespeichert", "Garmin, gilt für alle Sportarten"); a kind without zones shows "Noch keine Werte – Anlegen".

#### Scenario: Prefilled editor
- **WHEN** the athlete taps "Bearbeiten" or "Anlegen" on a zone kind
- **THEN** the existing editor opens under it with the threshold, maximum and limits in effect today (Garmin's zones for all sports included), or with the current FTP or threshold pace from the performance values when the kind has no zones; environment, valid-from date, "Gilt von Anfang an" and the removal of local zones stay available.

#### Scenario: First threshold entry
- **WHEN** the athlete taps "Bearbeiten" on LT1
- **THEN** the first-threshold entry (measured bpm, measurement date, stored share and the estimate to adopt) opens there, prefilled with the value in effect, and is saved with the profile as before; Quellen & Coach no longer holds it.

#### Scenario: Closed sections
- **WHEN** the athlete opens Profil, also with a stale-threshold warning
- **THEN** every section starts closed.

Evidence: `public/settings.js::renderZoneOverview`, `public/settings.js::openZoneEditor`, `public/settings.js::renderZoneWarnings`, `public/performance-view.js::thresholdRows`, `public/index.html`; `tests/zone-overview.test.cjs`, `e2e/zones-thresholds.spec.js`.
