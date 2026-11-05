## Why

The automatic Garmin-to-Intervals.icu export has one all-or-nothing consent. Enabling it would also push Garmin's auto-detected FTP into Intervals.icu and override the athlete's decision (issue #1668, 2026-11-04) that the athlete-maintained Intervals.icu FTP precedes Garmin's.

## What Changes

- Consent is stored per exported field (weight, body fat, resting HR, running threshold pace, threshold HR, maximum HR, cycling FTP) under `garmin_metric_export_fields`.
- The earlier flag `garmin_metric_export_enabled` means "all fields as before" until the athlete saves per-field consent; it is kept in step so an older build still honours a revocation.
- A new consent starts with every field except cycling FTP.
- `POST /api/metric-export/automatic` accepts an optional `fields` list and answers with a receipt of the changed fields; the Garmin status exposes `metric_export_fields`.
- The Anbindungen card shows one checkbox per field while the export is enabled; each change is confirmed and shows the receipt.

## Impact

- `backend/sync/metric_export_consent.py` (new), `metric_export.py`, `garmin_projection_service.py`, `public/provider-connections.js`, `public/index.html`, `public/styles.css`, `public/service-worker.js`.
- No schema change: consent stays in the encrypted key-value settings and backups.
