## MODIFIED Requirements

### Requirement: Explicit metric export and stored automatic consent
The system SHALL offer supported metric export only to a capable target, with a preview, named target, explicit confirmation, and unchanged source/target evidence at execution. Automatic Garmin-to-Intervals export SHALL require separately stored named consent per exported field, preserve independent target edits across restarts, remain idempotent, and leave HR zones unchanged. Export failure SHALL preserve successful local Garmin import.

#### Scenario: Confirmed manual metric selection
- **WHEN** selected source observations and live remote values still match a confirmed preview
- **THEN** only selected supported fields are written, previous-value/source receipts are recorded, and HR zones recalculate only when explicitly requested for supported threshold fields.

#### Scenario: Automatic export after consent
- **WHEN** a successful eligible current Garmin sync completes and stored Garmin-to-Intervals consent is enabled
- **THEN** only the consented fields transfer; unchanged target baselines permit eligible new values to transfer; a target edited independently is preserved and reported as conflict, without blocking unrelated fields.

#### Scenario: Unconfirmed or failed export
- **WHEN** the request lacks named consent/confirmation, preview values changed, or a remote write fails
- **THEN** unauthorized or stale selection sends nothing, failures receive safe per-field results, and the imported local Garmin data is retained.

#### Scenario: Per-field consent
- **WHEN** the athlete enables the automatic export for the first time, or changes one field's consent with a confirmed request naming Garmin and Intervals.icu
- **THEN** a new consent covers every field except cycling FTP, a consent stored before per-field consent keeps all fields until a field is changed, the response lists each changed field as a receipt, and revoking the last field ends the automatic export.

Evidence: `backend/sync/metric_export.py:MetricExportService.export`, `backend/sync/metric_export.py:MetricExportService.configure_automatic`, `backend/sync/metric_export.py:MetricExportService.sync_garmin`, `backend/sync/metric_export_consent.py:enabled_fields`, `backend/sync/garmin_service.py:GarminSyncService._execute`; `tests/test_metric_export.py:test_automatic_export_requires_persisted_named_consent`, `tests/test_metric_export.py:test_legacy_consent_keeps_all_fields_until_saved_per_field`, `tests/test_metric_export.py:test_new_consent_starts_without_ftp`, `tests/test_metric_export.py:test_new_garmin_value_after_restart_preserves_a_manual_target_change`, `tests/test_sync_garmin_service.py:test_export_failure_preserves_import_and_does_not_expose_error`, `tests/metric-export.test.cjs`.
