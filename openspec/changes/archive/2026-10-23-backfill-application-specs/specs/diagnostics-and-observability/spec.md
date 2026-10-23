# Diagnostics and observability Specification Delta

## Purpose

Expose useful local technical evidence while redacting secrets, bounding captures and keeping diagnostics distinct from athlete dialogue.

Owns logs, technical capture and local reports. Sanitized Coach request/response bodies can be retained by diagnostics; this is not a blanket body-free logging promise. Credentials, tokens, sessions and raw secret-bearing error values remain excluded/redacted by the implemented sanitizer.

## ADDED Requirements

### Requirement: Structured secret redaction

Structured log formatting and diagnostic projections SHALL redact configured secrets, common credential forms, nested/encoded variants and sensitive URL/query values before exposed logging or diagnostic output.


#### Scenario: Nested credential in an error context
- **WHEN** a log/diagnostic value contains a configured secret or recognized credential field
- **THEN** the exposed projection masks it, including nested and supported encoded representations

#### Scenario: Sensitive request query
- **WHEN** an access-log path includes free-text query values
- **THEN** logging preserves safe path context while masking the sensitive query values

#### Scenario: Credential configuration changes
- **WHEN** a configured credential is replaced
- **THEN** redaction refreshes its prepared patterns for current credential values

Evidence: `backend/observability.py::Redactor`; `backend/observability.py::JsonLogFormatter`; `backend/observability.py::redact_request_query`. Tests: `tests/test_observability.py::test_redacts_nested_values_and_secret_variants`; `tests/test_observability.py::test_redacts_url_credentials_query_and_unguessable_path`; `tests/test_observability.py::test_formatter_redacts_traceback_and_context`; `tests/test_observability.py::test_access_log_masks_free_text_query_on_success_and_error_paths`.

### Requirement: Bounded durable technical capture

Diagnostic capture SHALL sanitize captured details, bound entry count and stored byte sizes, preserve useful classified error evidence and persist dirty entries through its configured flush lifecycle.


#### Scenario: Oversized technical detail
- **WHEN** a capture exceeds configured entry or storage bounds
- **THEN** details are compacted/trimmed while classified error markers remain where supported

#### Scenario: Burst of technical events
- **WHEN** multiple captures arrive before a delayed flush
- **THEN** the dirty burst can be merged into a bounded background write

#### Scenario: Shutdown or explicit flush
- **WHEN** capture is closed or flushed
- **THEN** pending sanitized entries are persisted without leaving an active delayed write

Evidence: `backend/observability.py::DiagnosticCapture.capture`; `backend/observability.py::DiagnosticCapture._bounded_entry`; `backend/observability.py::DiagnosticCapture.flush`; `backend/observability.py::DiagnosticCapture.close`. Tests: `tests/test_observability.py::test_detail_capture_retains_evidence_and_removes_nested_and_encoded_credentials`; `tests/test_observability.py::test_capture_limits_bytes_preserves_error_and_persists_failure_before_restart`; `tests/test_observability.py::test_diagnostic_capture_is_bounded_and_keeps_recording`.

### Requirement: Local diagnostic report without provider refresh

The diagnostic report SHALL compose local configuration flags, provider/job state, source freshness, counts and technical runtime information from consistent local reads without returning raw credentials or initiating a provider refresh.


#### Scenario: Report requested
- **WHEN** the authenticated athlete opens/downloads diagnostics
- **THEN** the report returns local counts/state and configuration booleans with redacted errors

#### Scenario: Composed database evidence
- **WHEN** the report reads multiple counts and KV entries
- **THEN** those reads share one read snapshot rather than mixing committed states

#### Scenario: Unsupported process counters
- **WHEN** the platform lacks readable Linux process counter files
- **THEN** available diagnostic information is still returned without treating missing counters as athlete values

Evidence: `backend/diagnostics/report.py::DiagnosticReportService.report`; `backend/diagnostics/canonical_counts.py`; `backend/diagnostics/canonical_coverage.py`; `backend/runtime/memory.py::process_memory`. Tests: `tests/test_diagnostic_report.py::test_report_shape_counts_redaction_and_privacy`; `tests/test_diagnostic_report.py::test_database_counts_and_kv_reads_share_one_read_snapshot`; `tests/test_diagnostic_report.py::test_snapshot_size_counts_utf8_bytes_without_fetching_the_payload`.

### Requirement: Sanitized log preview and download

Log access SHALL provide sanitized recent previews and rotated/current JSONL download projections, handle missing/unparseable log lines safely, and clear only the owned active/rotated log files through the explicit clear operation.


#### Scenario: Missing log file
- **WHEN** the owned log file does not exist
- **THEN** the preview returns an empty list

#### Scenario: Malformed line
- **WHEN** a log line cannot be parsed as JSON
- **THEN** it is represented as an unparsed-log entry and sanitized before return

#### Scenario: Explicit log clear
- **WHEN** the clear operation succeeds
- **THEN** owned rotated files are removed and the active log is truncated

Evidence: `backend/diagnostics/logs.py::RecentLogEntriesService.list`; `backend/diagnostics/logs.py::RecentLogEntriesService.download`; `backend/diagnostics/logs.py::RecentLogEntriesService.clear`; `backend/http_api/diagnostics_get.py`. Tests: `tests/test_diagnostic_logs.py::test_missing_file_returns_empty_list`; `tests/test_diagnostic_logs.py::test_list_tails_lines_falls_back_for_invalid_json_and_sanitizes_values`; `tests/test_diagnostic_logs.py::test_download_includes_rotated_logs_in_order_and_redacts_secrets`; `tests/test_diagnostic_logs.py::test_clear_removes_rotated_logs_and_truncates_active_log`.

### Requirement: Privacy-safe Coach failure history

Coach diagnostic history SHALL project bounded command/step/error metadata using known status/tool values and safe classifications rather than return session credentials or arbitrary raw provider exception text.


#### Scenario: Failed or rejected tool
- **WHEN** a Coach turn records a classified tool failure or incomplete response
- **THEN** diagnostics retain the safe classification and useful bounded step metadata

#### Scenario: Unknown stored metadata
- **WHEN** stored diagnostic tool/status/error data contains unsupported values
- **THEN** the projection uses its safe fallback/allowlist instead of exposing arbitrary values

Evidence: `backend/diagnostics/history.py::CoachDiagnosticHistoryService`; `backend/observability.py::safe_diagnostic_error`; `backend/observability.py::safe_diagnostic_context`. Tests: `tests/test_diagnostic_history_service.py`; `tests/test_diagnostic_followups.py::test_failed_tool_is_diagnosable_without_session_credentials`; `tests/test_diagnostic_followups.py::test_rejected_tool_and_incomplete_reply_keep_classified_diagnostics`; `tests/test_observability.py::test_safe_diagnostic_context_and_error_never_retain_values_or_text`.

### Requirement: Clear and restore do not resurrect captures

Diagnostic clear, privacy erasure and restore SHALL coordinate pending flushes and caches so successfully removed or replaced diagnostic entries cannot later be written back from the previous in-memory state.


#### Scenario: Successful clear or state replacement
- **WHEN** diagnostic state is successfully cleared, erased or replaced during suspended flushing
- **THEN** old capture caches are discarded and cannot resurrect prior entries

#### Scenario: Mutation fails
- **WHEN** a suspended mutation fails before committing replacement diagnostic state
- **THEN** the existing cache is retained rather than falsely treating the failed clear as complete

Evidence: `backend/observability.py::DiagnosticCapture.clear`; `backend/observability.py::DiagnosticCapture.suspended`; `backend/observability.py::DiagnosticCapture.discard_cache`; `backend/backup/restore.py::DatabaseRestoreService.restore`; `backend/privacy.py::PrivacyDeleteService.delete`. Tests: `tests/test_observability.py::test_restore_swap_shows_only_restored_entries_after_discard`; `tests/test_observability.py::test_flush_during_suspension_cannot_write_cleared_entries_back`; `tests/test_observability.py::test_delayed_write_cannot_write_cleared_entries_back_after_suspension`; `tests/test_observability.py::test_suspension_keeps_the_cache_when_the_mutation_fails`.

### Requirement: Useful safe correlation and access-log levels

The application SHALL retain safe request/operation correlation for concurrent work, log successful routine GET polls at the configured reduced level, and retain higher-visibility error/other-request evidence without sensitive query text.


#### Scenario: Concurrent operations
- **WHEN** two unrelated operations log technical events concurrently
- **THEN** their safe correlation identifiers remain distinct

#### Scenario: Routine successful poll
- **WHEN** a configured routine GET endpoint responds successfully
- **THEN** the access log uses DEBUG policy

#### Scenario: Error response
- **WHEN** a request fails or is not a reduced-level routine poll
- **THEN** the access log retains the applicable INFO-level visibility

Evidence: `backend/observability.py::http_access_log_level`; `backend/observability.py::JsonLogFormatter`; `backend/http_api/handler.py::RequestHandler`. Tests: `tests/test_server_runtime.py::test_parallel_operations_keep_distinct_safe_correlation_ids`; `tests/test_observability.py::test_successful_routine_get_polls_log_at_debug`; `tests/test_observability.py::test_errors_and_other_requests_keep_info`.
