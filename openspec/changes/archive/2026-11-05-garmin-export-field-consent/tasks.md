# Tasks

## 1. Consent

- [x] 1.1 Store per-field consent with the legacy-flag migration and filter the automatic export by it; verify `tests/test_metric_export.py`.
- [x] 1.2 Expose the fields in the Garmin status and accept them with a receipt; verify `tests/test_metric_export.py` and `tests/test_sync_garmin_projection_service.py`.
- [x] 1.3 Show one confirmed checkbox per field in Anbindungen; verify `tests/metric-export.test.cjs` and `e2e/training-feature-panels.spec.js`.

## 2. Integration

- [x] 2.1 Run the selected checks, Node tests, repo-wide mypy and strict OpenSpec validation, recording unavailable checks as evidence gaps.
