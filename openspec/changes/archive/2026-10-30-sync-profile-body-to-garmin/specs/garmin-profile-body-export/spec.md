# Spec Delta

## Purpose

Enable the athlete to send profile body composition changes to Garmin Connect while preserving local data.

## ADDED Requirements

### Requirement: Profile body updates are sent to Garmin
When an athlete saves a changed weight or body-fat value in the profile, the system SHALL send the resulting valid profile weight and body-fat values together as one dated Garmin body-composition entry.

#### Scenario: One or both values changed
- **WHEN** either body field changes and both saved values are valid and Garmin is connected
- **THEN** one entry containing both saved values is sent to Garmin, with the current athlete-local time.

#### Scenario: No change
- **WHEN** neither body value changes
- **THEN** no Garmin body entry is sent.

#### Scenario: Body values were already current
- **WHEN** the opted-in save makes no actual change to either stored body value
- **THEN** the response identifies that no upload was needed.

#### Scenario: Missing or invalid data
- **WHEN** either value is missing or invalid, or Garmin is unavailable
- **THEN** the local profile remains saved, no entry is sent, and the athlete is informed why.

#### Scenario: A later local change supersedes a waiting export
- **WHEN** the saved weight or body fat changes before the waiting export can begin
- **THEN** the older pair is not uploaded and the athlete is informed that the export was superseded.

#### Scenario: Body values change away and back while an export waits
- **WHEN** body values change after a save and later return to the earlier pair before its pending export begins
- **THEN** that earlier export is superseded, rather than duplicated by the newer export.

#### Scenario: Garmin is busy or authentication is too slow
- **WHEN** the export cannot begin within the bounded request deadline
- **THEN** no upload starts later and the athlete receives a known unavailable outcome if the response can be delivered.

#### Scenario: A profile mutation arrives during upload
- **WHEN** another profile mutation arrives while the Garmin upload is in progress
- **THEN** it is serialized after the upload, while unrelated database writes remain available and no database transaction remains open for the network call.

#### Scenario: Upload fails
- **WHEN** the remote upload fails or its outcome is uncertain
- **THEN** the local profile remains saved and the athlete is informed; the system SHALL NOT silently retry an uncertain upload.

#### Scenario: Known failed export is retried explicitly
- **WHEN** Garmin was unavailable, explicitly rejected the upload, or the profile values were invalid and subsequently corrected, and the athlete chooses retry
- **THEN** the system sends the currently saved valid pair once, even if the profile values have not changed.

#### Scenario: Browser response is lost
- **WHEN** the profile-save or explicit retry response is lost, malformed or times out after a body edit
- **THEN** the athlete is warned that local and remote outcomes are unknown and that Garmin must be checked before another upload.

#### Scenario: Concurrent actions in one profile view
- **WHEN** a profile save or explicit retry is already pending in the current view
- **THEN** the other action does not issue a concurrent request or overwrite its result.

#### Scenario: Other mutations
- **WHEN** a Coach, undo, import, or unrelated API action changes a profile value
- **THEN** it does not implicitly write to Garmin.

Evidence baseline: `backend/http_api/athlete_put.py`, `backend/athlete/profile.py`, `backend/sync/garmin_service.py`. Remote write tests and live compatibility are not yet established.
