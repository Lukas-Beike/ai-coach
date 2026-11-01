## ADDED Requirements

### Requirement: Retired backup schema rejection

Restore SHALL reject backups with schema versions older than v16 without changing the active database.

#### Scenario: Older backup is selected
- **WHEN** a backup with schema v15 or older is staged for restore
- **THEN** validation fails and the active database remains unchanged.

Evidence: `backend/backup/restore_validation.py`; `tests/test_database_restore_validation.py::test_validate_rejects_v9_backup_without_modifying_it` and `tests/test_database_restore_v13_upgrade.py`.
