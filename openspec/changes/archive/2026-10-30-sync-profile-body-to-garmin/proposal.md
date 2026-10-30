# Proposal

## Why

The athlete cannot manually enter body fat in Garmin Connect and wants profile edits to update Garmin.

## What Changes

- Display the profile body-fat value in the Body overview with its source.
- When a profile form save changes weight or body fat, send both current values to Garmin as a dated body-composition entry when both are valid.
- Preserve the local save and clearly report remote success, skipped or superseded uploads, and failures.
- Coordinate profile mutations across HTTP, Coach and undo so concurrent edits cannot send an outdated profile while network calls do not hold a database transaction.

## Capabilities

### New Capabilities

- `garmin-profile-body-export`: Explicit profile-save body composition export to Garmin.

### Modified Capabilities

- `performance-and-readiness`: Show profile body fat in the Body overview.

## Impact

Profile save UI and HTTP route, Garmin transport and synchronization, Body presentation, tests and documentation. Observed baseline 52870061: profile patch is local; Garmin remote reader already owns authentication; SDK 0.3.20 exposes body composition upload. No real account has been tested.
