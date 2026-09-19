# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `3bc49609df65da8e12fd6bc794678160f06704468d60199d0842a33fd7082d5e`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 19.917 physische Zeilen
- Inventareinträge: 1.551
- Definitionen (Funktionen/Klassen): 1.103
- Globale Bindungen einschließlich Imports: 258 Zuweisungen. 190 Imports
- Planbereich: bis Zeile 21.702; Einträge dahinter: 0 (zielbestimmt über Symbol-/Verantwortungsanalyse)
- Status dieses Stands: P0 ist integriert; bereits ausgelagerte Namen erscheinen als Importbindungen. `offen` bedeutet, dass die fachliche Eigentümerschaft noch migriert werden muss.

## Reproduzierbare Prüfungen

```text
python scripts/server_extraction_inventory.py
python scripts/server_extraction_inventory.py --check
python -m py_compile scripts/server_extraction_inventory.py
git diff --check
python -m unittest discover -s tests -v
```
Baseline am unveränderten Ausgangs-HEAD `362d6ca` (separater isolierter Worktree): `python -m unittest discover -s tests -v` — 779 Tests, 12 übersprungen, OK; `python -m compileall -q server.py backend` — PASS; `git diff --check` — PASS.
Infrastruktur-Baseline: `docker build -t ai-coach:server-extraction-baseline .` konnte wegen nicht erreichbarer Docker-API (`npipe`, Docker-Desktop-Daemon unavailable) nicht starten; deshalb wurde E2E nicht gegen einen isolierten Server ausgeführt. Das ist ein externer Infrastruktur-Befund, kein Codefehler.
Der Generator führt selbst keine Tests und keine Laufzeitinitialisierung aus. Synthetische/temporäre Testdaten und gemockte Provider sind verbindlich.

## Verteilung

| Phase | Funktionen/Klassen | Globale Bindungen | Importbindungen |
| --- | ---: | ---: | ---: |
| P0 (Zuordnung offen) | 0 | 0 | 0 |
| P1 | 20 | 40 | 143 |
| P2 | 87 | 10 | 0 |
| P3 | 189 | 27 | 0 |
| P4 | 285 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 228 | 43 | 0 |
| P7 | 201 | 39 | 0 |
| P8 | 13 | 11 | 0 |
| P9 | 25 | 6 | 0 |
| P10 | 30 | 39 | 0 |
| P11 | 1 | 3 | 47 |

## Referenzanalyse außerhalb von server.py

Direkte `server.<name>`-Zugriffe und erkennbare Import-/Patchstellen sind pro Eintrag in der Tabelle vermerkt. Die Ortsangaben decken `backend/`, `tests/`, `e2e/`, `scripts/`, Docker und GitHub-Workflows ab.

### Dynamische Zugriffe und Monkeypatches

Diese Stellen benötigen bei jeder Migration eine manuelle Prüfung des Lookup-Ortes:

- `tests/support.py:106: patch.object(server, "CONFIG", replace(server.CONFIG, app_password=app_password)),`
- `tests/support.py:107: patch.object(server, "DATA_DIR", root),`
- `tests/support.py:108: patch.object(server, "DB_PATH", root / "test.db"),`
- `tests/support.py:109: patch.object(server, "LOG_PATH", root / "test.log"),`
- `tests/test_audit_remediation.py:107: with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):`
- `tests/test_audit_remediation.py:148: with patch.object(server, "weather_state", return_value={"stale": True, "days": [{}], "error": "Synthetic failure"}):`
- `tests/test_audit_remediation.py:154: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="", calendar_ical_url="")), patch.object(server, "garmin_fixture_path", return_value="synthetic"), patch.object(server, "daily_sync_due", return_value=True):`
- `tests/test_audit_remediation.py:206: startup = patch.object(server.app_config, "security_configuration_error", return_value=None)`
- `tests/test_audit_remediation.py:244: with patch.object(server, "apply_adaptive_replan", return_value={"status": "applied"}) as mutation:`
- `tests/test_audit_remediation.py:262: with patch.object(server, "ensure_conversation", return_value="synthetic"), patch.object(server, "build_training_context", side_effect=["Old Garmin data", "Fresh Garmin data"]) as context, patch.object(server, "responses_request", side_effect=response) as model:`
- `tests/test_audit_remediation.py:278: with patch.object(server, "_restore_coach_session_csrf_hash", side_effect=restore), patch.object(server, "chat_with_coach", side_effect=coach) as execute:`
- `tests/test_audit_remediation.py:286: with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="synthetic-encrypted-key")), patch.object(server, "DATA_DIR", root), patch.object(server, "DB_PATH", root / "test.db"), patch.object(server, "LOG_PATH", root / "test.log"):`
- `tests/test_audit_remediation.py:301: with patch.object(server, "sync_intervals", return_value={"status": "ok"}), patch.object(server, "chat_with_coach", return_value={"status": "failed"}), patch.object(server, "garmin_fixture_path", return_value=None):`
- `tests/test_audit_remediation.py:44: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:55: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:71: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:82: with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):`
- `tests/test_coach_attachments.py:169: with patch.object(server, "MAX_ATTACHMENT_STORAGE_BYTES", 10):`
- `tests/test_coach_attachments.py:176: with patch.object(server.SETTINGS, "selected_ai_provider", return_value="gemini"), patch.object(server, "MAX_GEMINI_INLINE_IMAGE_BYTES", 1):`
- `tests/test_coach_attachments.py:198: with patch.object(server, "_gemini_history", return_value=saved_history):`
- `tests/test_coach_attachments.py:214: with patch.object(server, "MAX_GEMINI_INLINE_IMAGE_BYTES", encoded_size + 1):`
- `tests/test_coach_attachments.py:227: with patch.object(server, "_gemini_local_chat_history", return_value=history), patch.object(server, "_gemini_history", return_value=history):`
- `tests/test_coach_attachments.py:246: with patch.object(server, "responses_background_request", side_effect=respond), patch.object(server, "ensure_conversation", return_value="synthetic-conversation"):`
- `tests/test_coach_attachments.py:260: with patch.object(server, "responses_background_request", side_effect=respond), patch.object(server, "ensure_conversation", return_value="synthetic-conversation"):`
- `tests/test_coach_dialogue.py:28: fixed = patch.object(server, "local_now", return_value=datetime(2026, 9, 7, 12, tzinfo=timezone.utc))`
- `tests/test_coach_dialogue.py:382: with patch.object(server.SETTINGS, "selected_ai_provider", return_value="gemini"):`
- `tests/test_coach_dialogue.py:398: with patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_coach_dialogue.py:405: with patch.object(server, "sync_intervals", return_value={"status": "ok", "activity_days": 7}) as sync:`
- `tests/test_coach_dialogue.py:57: with patch.object(server, "ensure_conversation", return_value="synthetic-conversation"), patch.object(`
- `tests/test_coach_dialogue.py:59: ), patch.object(server, "responses_request", side_effect=response) as model, patch.object(server, "responses_background_request", side_effect=response) as background_model:`
- `tests/test_coach_dialogue.py:649: with patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue:`
- `tests/test_coach_dialogue.py:671: with patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_coach_dialogue.py:705: with patch.object(server, "_restore_coach_session_csrf_hash", return_value="synthetic-session"), patch.object(`
- `tests/test_coach_dialogue.py:728: with patch.object(server, "_restore_coach_session_csrf_hash", return_value="synthetic-session"), patch.object(`
- `tests/test_coach_dialogue.py:755: with patch.object(server, "save_coach_checkin", wraps=server.save_coach_checkin) as save_checkin:`
- `tests/test_coach_dialogue.py:777: with patch.object(server, "_structured_coach_tool_result", side_effect=AssertionError("must not replay")):`
- `tests/test_coach_dialogue.py:793: with patch.object(server, "COACH_TOOL_MAX_ROUNDS", 1):`
- `tests/test_coach_dialogue.py:824: with patch.object(server, "save_coach_checkin") as save:`
- `tests/test_coach_dialogue.py:892: with patch.object(server, "save_coach_checkin", wraps=server.save_coach_checkin) as save:`
- `tests/test_coach_dialogue.py:97: with patch.object(server, "_structured_coach_tool_result", wraps=server._structured_coach_tool_result) as execute:`
- `tests/test_coach_language_recovery.py:108: with patch.object(server.time, "sleep"):`
- `tests/test_coach_language_recovery.py:41: patch.object(server.time, "sleep") as sleep,`
- `tests/test_coach_language_recovery.py:42: patch.object(server.secrets, "randbelow", return_value=0),`
- `tests/test_coach_language_recovery.py:43: patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue,`
- `tests/test_coach_language_recovery.py:58: with patch.object(server.time, "sleep") as sleep, patch.object(server.secrets, "randbelow", return_value=0):`
- `tests/test_coach_language_recovery.py:69: with patch.object(server.secrets, "randbelow", return_value=250):`
- `tests/test_coach_language_recovery.py:95: with patch.object(server.time, "sleep"):`
- `tests/test_coach_response_failure.py:34: with patch.object(server, "ensure_conversation", return_value="synthetic-conversation"), \`
- `tests/test_coach_response_failure.py:35: patch.object(server, "build_training_context", return_value="Synthetic local context"), \`
- `tests/test_coach_response_failure.py:36: patch.object(server, "responses_request", side_effect=create), \`
- `tests/test_coach_response_failure.py:37: patch.object(server, "http_json", return_value={"id": "resp_limited", "status": "failed", "error": {"code": "rate_limit_exceeded"}}), \`
- `tests/test_coach_response_failure.py:38: patch.object(server.time, "sleep"), \`
- `tests/test_coach_response_failure.py:39: patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue:`
- `tests/test_coach_response_failure.py:70: with patch.object(server, "ensure_conversation", return_value="synthetic-conversation"), \`
- `tests/test_coach_response_failure.py:71: patch.object(server, "build_training_context", return_value="Synthetic local context"), \`
- `tests/test_coach_response_failure.py:72: patch.object(server, "responses_request", side_effect=create), \`
- `tests/test_coach_response_failure.py:73: patch.object(server, "http_json", return_value=failed_response) as retrieve, \`
- `tests/test_coach_response_failure.py:74: patch.object(server, "enqueue_sync_job", wraps=server.enqueue_sync_job) as enqueue:`
- `tests/test_coach_review.py:133: with patch.object(server, "ensure_conversation", return_value="summary-recovery-conversation"), patch.object(`
- `tests/test_coach_review.py:24: context=patch.object(server,name,value);context.start();self.addCleanup(context.stop)`
- `tests/test_coach_review.py:257: with patch.object(server.time, "time", return_value=time.time() + server.COACH_ACTION_TTL_SECONDS + 1):`
- `tests/test_coach_review.py:282: with patch.object(server, "local_now", return_value=advanced):`
- `tests/test_coach_review.py:62: with patch.object(server, "get_kv", side_effect=observe_previous_sync_read):`
- `tests/test_coach_review.py:80: with patch.object(server, "sync_intervals") as sync:`
- `tests/test_coach_tool_coverage.py:265: with patch.object(server, "sync_intervals", return_value={"status": "ok", "activity_days": 7}) as sync:`
- `tests/test_coach_tool_coverage.py:336: with patch.object(server, "sync_illness_pause_to_intervals", return_value={"status": "ok", "synced": 3}) as remote:`
- `tests/test_coach_tool_coverage.py:436: with patch.object(server, "_apply_training_patch", wraps=server._apply_training_patch) as apply:`
- `tests/test_coach_tool_coverage.py:74: guard = patch.object(server, name, side_effect=AssertionError("Unexpected network access in synthetic Coach test"))`
- `tests/test_diagnostic_followups.py:100: patch.object(server, "sync_intervals", return_value={"status": "ok"}), \`
- `tests/test_diagnostic_followups.py:101: patch.object(server, "refresh_morning_body_battery"), \`
- `tests/test_diagnostic_followups.py:102: patch.object(server, "chat_with_coach", return_value={"status": "completed", "message": {"id": "morning"}}) as chat:`
- `tests/test_diagnostic_followups.py:120: with patch.object(server, "CONFIG", config), \`
- `tests/test_diagnostic_followups.py:121: patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json")), \`
- `tests/test_diagnostic_followups.py:122: patch.object(server, "sync_garmin", return_value={"status": "ok"}) as sync, \`
- `tests/test_diagnostic_followups.py:123: patch.object(server, "sync_intervals", return_value={"status": "ok"}), \`
- `tests/test_diagnostic_followups.py:124: patch.object(server, "refresh_morning_body_battery"), \`
- `tests/test_diagnostic_followups.py:125: patch.object(server, "chat_with_coach", return_value={"status": "completed", "message": {"id": "morning"}}):`
- `tests/test_diagnostic_followups.py:139: with patch.object(server, "CONFIG", config), \`
- `tests/test_diagnostic_followups.py:140: patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json")), \`
- `tests/test_diagnostic_followups.py:141: patch.object(server, "sync_garmin", return_value={"status": "ok"}), \`
- `tests/test_diagnostic_followups.py:142: patch.object(server, "refresh_morning_body_battery") as recovery, \`
- `tests/test_diagnostic_followups.py:143: patch.object(server, "chat_with_coach") as chat:`
- `tests/test_diagnostic_followups.py:155: with patch.object(server, "CONFIG", config), \`
- `tests/test_diagnostic_followups.py:156: patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json")), \`
- `tests/test_diagnostic_followups.py:157: patch.object(server, "sync_garmin", return_value={"status": "ok"}), \`
- `tests/test_diagnostic_followups.py:158: patch.object(server, "sync_intervals", return_value={"status": "ok"}), \`
- `tests/test_diagnostic_followups.py:159: patch.object(server, "refresh_morning_body_battery"), \`
- `tests/test_diagnostic_followups.py:160: patch.object(server, "chat_with_coach", return_value={"status": "completed", "message": {"id": "morning"}}) as chat:`
- `tests/test_diagnostic_followups.py:170: with patch.object(server.threading, "Thread") as thread:`
- `tests/test_diagnostic_followups.py:182: with patch.object(server, "CONFIG", config):`
- `tests/test_diagnostic_followups.py:194: with patch.object(server, "CONFIG", config):`
- `tests/test_diagnostic_followups.py:211: with patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json")), \`
- `tests/test_diagnostic_followups.py:212: patch.object(server, "load_garmin_fixture", return_value={}) as fetch:`
- `tests/test_diagnostic_followups.py:221: with patch.object(server, "_morning_body_battery_record", return_value=ready):`
- `tests/test_diagnostic_followups.py:23: with self.subTest(hour=hour), patch.object(server, "local_now", return_value=datetime(2026, 9, 7, hour, tzinfo=timezone.utc)):`
- `tests/test_diagnostic_followups.py:244: with patch.object(server, "GARMIN_LOCK", Mock(acquire=Mock(return_value=False))):`
- `tests/test_diagnostic_followups.py:249: with patch.object(server, "sync_garmin", return_value={"status": "partial"}), patch.object(server, "refresh_morning_body_battery") as recovery:`
- `tests/test_diagnostic_followups.py:312: with patch.object(server, "IntervalsClient") as provider:`
- `tests/test_diagnostic_followups.py:329: with patch.object(server, "save_coach_activity_feedback", side_effect=RuntimeError(private)):`
- `tests/test_diagnostic_followups.py:37: with patch.object(server.threading, "Thread", side_effect=thread), \`
- `tests/test_diagnostic_followups.py:38: patch.object(server, "sync_intervals", return_value={"status": "ok"}), \`
- `tests/test_diagnostic_followups.py:39: patch.object(server, "sync_garmin"), patch.object(server, "refresh_morning_body_battery"), \`
- `tests/test_diagnostic_followups.py:40: patch.object(server, "chat_with_coach", side_effect=[{"status": "failed"}, {"status": "completed", "message": {"id": 1}}]) as chat:`
- `tests/test_diagnostic_followups.py:56: with patch.object(server.threading, "Thread") as thread:`
- `tests/test_diagnostic_followups.py:72: with patch.object(server, "CONFIG", config), \`
- `tests/test_diagnostic_followups.py:73: patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json")), \`
- `tests/test_diagnostic_followups.py:74: patch.object(server, "sync_garmin", return_value={"status": "ok"}) as sync, \`
- `tests/test_diagnostic_followups.py:75: patch.object(server, "sync_intervals") as intervals, \`
- `tests/test_diagnostic_followups.py:76: patch.object(server, "refresh_morning_body_battery") as recovery, \`
- `tests/test_diagnostic_followups.py:77: patch.object(server, "chat_with_coach") as chat:`
- `tests/test_diagnostic_followups.py:97: with patch.object(server, "CONFIG", config), \`
- `tests/test_diagnostic_followups.py:98: patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json")), \`
- `tests/test_diagnostic_followups.py:99: patch.object(server, "sync_garmin", return_value={"status": "ok"}) as sync, \`
- `tests/test_provider_review.py:138: with patch.object(server, "_execute_sync_job") as execute:`
- `tests/test_provider_review.py:147: with patch.object(server, "chat_with_coach") as coach, patch.object(server, "_persist_structured_command_failure") as failure:`
- `tests/test_provider_review.py:167: with patch.object(server, "_execute_sync_job", side_effect=execute):`
- `tests/test_provider_review.py:183: with self.subTest(kind="utf8"), patch.object(server, "CONFIG", replace(server.CONFIG, app_password=password)), \`
- `tests/test_provider_review.py:184: patch.object(server.app_config, "security_configuration_error", return_value=None), \`
- `tests/test_provider_review.py:185: patch.object(server, "allow_rate", return_value=(True, 0)):`
- `tests/test_provider_review.py:187: with patch.object(server, "database_manager", return_value=self.manager_for_login()):`
- `tests/test_provider_review.py:196: with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="")):`
- `tests/test_provider_review.py:215: with patch.object(server, "Garmin", return_value=client), patch.object(server, "collect_garmin_data", return_value=payload):`
- `tests/test_provider_review.py:238: with patch.object(server, "Garmin", return_value=client), \`
- `tests/test_provider_review.py:239: patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json") if fixture else None), \`
- `tests/test_provider_review.py:240: patch.object(server, "load_garmin_fixture", return_value=payload), \`
- `tests/test_provider_review.py:241: patch.object(server, "collect_garmin_data", return_value=payload):`
- `tests/test_provider_review.py:27: patch.object(server, "CONFIG", replace(server.CONFIG, app_password="", garmin_fixture_path="", garmin_email="synthetic@example.invalid")),`
- `tests/test_provider_review.py:28: patch.object(server, "DATA_DIR", root),`
- `tests/test_provider_review.py:29: patch.object(server, "DB_PATH", root / "fresh.db"),`
- `tests/test_provider_review.py:30: patch.object(server, "LOG_PATH", root / "synthetic.log"),`
- `tests/test_provider_review.py:314: with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="\U0001f6b4" * length)), \`
- `tests/test_provider_review.py:315: patch.object(server, "SQLCIPHER_AVAILABLE", True):`
- `tests/test_provider_review.py:31: patch.object(server.LOGGER, "disabled", True),`
- `tests/test_provider_review.py:328: with patch.object(server, "DB_PATH", encrypted_path), patch.object(server, "CONFIG", configured), \`
- `tests/test_provider_review.py:329: patch.object(server, "allow_rate", return_value=(True, 0)):`
- `tests/test_provider_review.py:32: patch.object(server.observability, "configure_logging"),`
- `tests/test_provider_review.py:81: with patch.object(server.IntervalsClient, "fetch_performance_snapshot", side_effect=fetch):`
- `tests/test_server.py:1020: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=True) as active, patch.object(`
- `tests/test_server.py:1029: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=False), patch.object(`
- `tests/test_server.py:1031: ), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:1211: with patch.object(server, "_fetch_weather_forecast", side_effect=[old, new]) as fetch:`
- `tests/test_server.py:1237: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1265: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1279: with patch.object(server, "_fetch_weather_forecast", return_value=forecast) as fetch:`
- `tests/test_server.py:1298: with patch.object(server, "_fetch_weather_forecast", side_effect=[server.AppError(503, "upstream"), forecast]) as fetch:`
- `tests/test_server.py:1314: with patch.object(server, "CONFIG", replace(server.CONFIG, secure_cookies=True)):`
- `tests/test_server.py:1532: with patch.object(server, "delete_remote_conversation", side_effect=server.AppError(503, "upstream")):`
- `tests/test_server.py:1548: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:1565: with patch.object(server, "_fetch_weather_forecast", return_value=forecast), patch.object(`
- `tests/test_server.py:1581: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("coach context must not refresh weather")):`
- `tests/test_server.py:1591: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1608: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1618: with patch.object(server, "latest_replan_preview", return_value={"status": "preview", "changes": [{"date": "2026-09-01"}]}):`
- `tests/test_server.py:1642: self.assertEqual(getattr(server.local_now().tzinfo, "key", None), "UTC")`
- `tests/test_server.py:1661: with patch.object(server, "local_now", return_value=fixed_now):`
- `tests/test_server.py:177: with patch.object(server, "CONFIG", config), patch.object(server, "DATA_DIR", Path(temporary)), patch.object(`
- `tests/test_server.py:1782: with patch.object(server, "http_json", side_effect=AssertionError("network")), patch.object(server, "external_call", side_effect=AssertionError("network")):`
- `tests/test_server.py:1825: with patch.object(server.sqlite3, "connect", wraps=sqlite3.connect) as connect:`
- `tests/test_server.py:1903: with patch.object(server, "state_versions", return_value={"activities": "v1"}):`
- `tests/test_server.py:206: with patch.object(server, "resume_interrupted_sync_jobs") as sync_recovery, patch.object(`
- `tests/test_server.py:216: with patch.object(server.observability, "configure_logging"), patch.object(`
- `tests/test_server.py:218: ), patch.object(server, "initialise_database", side_effect=lambda: order.append("schema")), patch.object(`
- `tests/test_server.py:222: ), patch.object(server, "CoachHTTPServer", return_value=http_server), patch.object(`
- `tests/test_server.py:226: ), patch.object(server, "enqueue_startup_sync_jobs"), patch.object(`
- `tests/test_server.py:228: ), patch.object(server.threading, "Thread"):`
- `tests/test_server.py:236: with patch.object(server, "resume_interrupted_sync_jobs") as sync_recovery, patch.object(`
- `tests/test_server.py:238: ) as coach_recovery, patch.object(server.threading, "Thread") as thread, patch.object(`
- `tests/test_server.py:240: ), patch.object(server, "COACH_JOB_WORKER", None):`
- `tests/test_server.py:2446: with patch.object(server, "CONFIG", replace(server.CONFIG, calendar_ical_url="https://calendar.example/feed.ics")), patch.object(`
- `tests/test_server.py:2486: with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", return_value=payload) as fetch, patch.object(`
- `tests/test_server.py:2516: with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", return_value=payload):`
- `tests/test_server.py:2531: with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", side_effect=server.AppError(502, "upstream unavailable")):`
- `tests/test_server.py:257: with patch.object(server, "_execute_sync_job", return_value={"status": "ok"}):`
- `tests/test_server.py:2592: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:2687: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=-1)):`
- `tests/test_server.py:268: with patch.object(server, "_execute_sync_job", side_effect=server.AppError(503, provider_detail, reason="network_error")):`
- `tests/test_server.py:2696: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=30)):`
- `tests/test_server.py:2706: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:2753: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)):`
- `tests/test_server.py:279: with patch.object(server, "sync_garmin") as sync:`
- `tests/test_server.py:2813: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 20, 0)):`
- `tests/test_server.py:2840: patch.object(server, "latest_snapshot", return_value=snapshot),`
- `tests/test_server.py:2841: patch.object(server, "list_dated_local_planned_workouts", return_value=planned),`
- `tests/test_server.py:2842: patch.object(server, "weather_state", return_value={"days": []}),`
- `tests/test_server.py:2843: patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)),`
- `tests/test_server.py:301: with patch.object(server, "_execute_sync_job", return_value=result):`
- `tests/test_server.py:311: with patch.object(server, "_repair_local_planned_unit_calendar_entry", return_value=None) as repair:`
- `tests/test_server.py:3247: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:3742: with patch.object(server.IntervalsClient, "get_workout_library", return_value=[]), \`
- `tests/test_server.py:3743: patch.object(server.IntervalsClient, "create_library_workouts", return_value=[{"id": "synthetic-remote", "type": "Ride"}]) as create, \`
- `tests/test_server.py:3744: patch.object(server.IntervalsClient, "update_library_workout", return_value={"id": "synthetic-remote", **parsed_workout_fixture()}) as update:`
- `tests/test_server.py:3762: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=[`
- `tests/test_server.py:3787: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:3805: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:3807: ), patch.object(server.IntervalsClient, "create_library_workouts") as create:`
- `tests/test_server.py:389: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-plan-push"}) as enqueue:`
- `tests/test_server.py:4014: with patch.object(server, "garmin_fixture_path", return_value="fixture.json"), \`
- `tests/test_server.py:4015: patch.object(server, "sync_garmin") as sync_garmin, \`
- `tests/test_server.py:4016: patch.object(server, "garmin_sleep_ready_for_checkin", return_value=False), \`
- `tests/test_server.py:4061: with patch.object(server, "CONFIG", config), patch.object(server, "Garmin", FakeGarmin):`
- `tests/test_server.py:420: with patch.object(server, "_mark_local_planning_authoritative"), patch.object(`
- `tests/test_server.py:4230: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4274: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=fake_urlopen):`
- `tests/test_server.py:4299: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4423: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value=response):`
- `tests/test_server.py:4438: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4449: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:444: with patch.object(server, "_enqueue_coach_plan_push") as enqueue, self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:4463: with patch.object(server, "CONFIG", replace(server.CONFIG, gemini_api_key=key)):`
- `tests/test_server.py:4469: with patch.object(server, "CONFIG", config), patch.object(server, "gemini_responses_request", return_value={"output_text": "ok"}) as gemini, patch.object(server, "openai_request") as openai:`
- `tests/test_server.py:4482: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4502: with patch.object(server, "CONFIG", config), patch.object(server, "delete_remote_conversation", return_value=True) as delete:`
- `tests/test_server.py:4520: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:4569: with patch.object(server, "urlopen", side_effect=blocked_urlopen):`
- `tests/test_server.py:4600: with patch.object(server, "urlopen", return_value=response):`
- `tests/test_server.py:4633: with patch.object(server, "urlopen", side_effect=return_cancelled_response):`
- `tests/test_server.py:4652: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")), patch.object(`
- `tests/test_server.py:4677: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4701: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:4708: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:476: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-competition"}) as enqueue:`
- `tests/test_server.py:4880: with patch.object(server, "calendar_conflicts", return_value=[{"name": "Occupied"}]) as conflicts:`
- `tests/test_server.py:5194: with patch.object(server, "structured_athlete_context", return_value={"source_policy": {"untrusted": "x" * 200_000}}):`
- `tests/test_server.py:5301: with patch.object(server, "openai_request", side_effect=fake_openai):`
- `tests/test_server.py:5307: with patch.object(server, "http_json", return_value=response), patch.object(`
- `tests/test_server.py:5323: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:5437: with patch.object(server, "CHANGE_HISTORY_MAX_ROWS", 3), self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:5574: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 2):`
- `tests/test_server.py:5588: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 1):`
- `tests/test_server.py:5674: with patch.object(server, "save_workout_library_entries", side_effect=RuntimeError("creation failed")):`
- `tests/test_server.py:5676: server._apply_training_patch(arguments, {`
- `tests/test_server.py:5693: with patch.object(server, "responses_request", side_effect=create), patch.object(`
- `tests/test_server.py:5698: ) as retrieve, patch.object(server, "OPENAI_BACKGROUND_POLL_SECONDS", 0), patch.object(server, "record_openai_usage"):`
- `tests/test_server.py:572: with patch.object(server, "enqueue_sync_job", side_effect=[{"id": "job-performance"}, {"id": "job-competition"}]) as enqueue:`
- `tests/test_server.py:5746: with patch.object(server, "chat_with_coach", side_effect=lambda *args, **kwargs: seen.update(kwargs) or {}):`
- `tests/test_server.py:5770: with patch.object(server, "chat_with_coach", side_effect=complete_chat):`
- `tests/test_server.py:5799: with patch.object(server, "responses_stream_request", side_effect=streamed_response) as streamed, patch.object(`
- `tests/test_server.py:5824: ), patch.object(server, "_restore_coach_session_csrf_hash", return_value="csrf-background-requeue"):`
- `tests/test_server.py:5865: with patch.object(server, "chat_with_coach", side_effect=capture_phase), patch.object(`
- `tests/test_server.py:5901: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:5903: ) as fetch_snapshot, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:5914: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:5930: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:5932: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:5943: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:5945: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:595: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:5961: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:5974: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6002: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6004: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=remote) as get_library:`
- `tests/test_server.py:6042: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6044: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6064: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6068: ) as import_units, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6086: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6088: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[{`
- `tests/test_server.py:608: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:6105: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6109: ) as library_sync, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6124: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6178: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6187: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:619: with patch.object(server, "sync_intervals", return_value={"status": "ok"}) as sync, patch.object(`
- `tests/test_server.py:6206: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6215: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6224: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6232: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6249: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6293: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6307: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_server.py:631: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6325: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6370: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6372: ), patch.object(server, "_sync_selected_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6395: with patch.object(server, "IntervalsClient", FailingIntervalsClient), patch.object(`
- `tests/test_server.py:6405: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6418: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", db_path), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6463: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:6484: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6493: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir), patch.dict(`
- `tests/test_server.py:650: with patch.object(server, "CONFIG", config), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:6513: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir):`
- `tests/test_server.py:659: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:661: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:663: ) as enqueue, patch.object(server, "_wait_for_performance_refresh") as wait:`
- `tests/test_server.py:6660: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6692: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:672: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6730: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:674: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:6762: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6778: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6817: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6850: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6877: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7160: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:7161: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:7290: with patch.object(server, "http_json", side_effect=[`
- `tests/test_server.py:7373: with patch.object(server.LOGGER, "info") as logger:`
- `tests/test_server.py:7550: with patch.object(server.IntervalsClient, "delete_activity", return_value=None) as delete:`
- `tests/test_server.py:7600: with patch.object(server, "get_kv", side_effect=get_kv_after_read):`
- `tests/test_server.py:7632: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7654: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7682: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7701: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7718: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7752: with patch.object(server, "urlopen", side_effect=server.URLError("offline")):`
- `tests/test_server.py:7769: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7783: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7793: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7809: with patch.object(server, "database", side_effect=OSError("database unavailable")):`
- `tests/test_server.py:7817: with patch.object(server.tempfile, "NamedTemporaryFile", side_effect=OSError("read-only")):`
- `tests/test_server.py:7836: with patch.object(server.time, "monotonic", return_value=20 * 60):`
- `tests/test_server.py:7865: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:7867: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[]):`
- `tests/test_server.py:7894: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7930: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7957: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7978: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8009: with patch.object(server, "openai_request", side_effect=fake_request), patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8028: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8070: with patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:8083: with patch.object(server, "urlopen") as urlopen:`
- `tests/test_server.py:8107: with patch.object(server, "urlopen", return_value=TimeoutResponse()):`
- `tests/test_server.py:8117: with patch.object(server.LOGGER, "log") as log:`
- `tests/test_server.py:8128: with patch.object(server.LOGGER, "log") as log:`
- `tests/test_server.py:8157: with patch.object(server, "urlopen", return_value=DisconnectResponse()):`
- `tests/test_server.py:8165: with patch.object(server, "openai_stream_request", side_effect=responses) as request, patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8212: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), \`
- `tests/test_server.py:8213: patch.object(server, "unregister_chat_stream") as unregister, \`
- `tests/test_server.py:8214: patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8239: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), patch.object(`
- `tests/test_server.py:8241: ) as unregister, patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8293: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value={"status": "completed"}) as request:`
- `tests/test_server.py:8346: with patch.object(server, "DB_LOCK", database_lock), patch.object(`
- `tests/test_server.py:8363: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8450: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:8464: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8475: with patch.object(server, "CONFIG", replace(config, intervals_api_key="")):`
- `tests/test_server.py:8532: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:912: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-changed"}) as enqueue:`
- `tests/test_server.py:938: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-large-changed"}) as enqueue:`
- `tests/test_server.py:983: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-all"}) as enqueue:`
- `tests/test_workout_repair.py:152: with patch.object(server.IntervalsClient, "get_paged_collection", side_effect=read), patch.object(`
- `tests/test_workout_repair.py:178: with patch.object(server.IntervalsClient, "fetch_snapshot", return_value=snapshot), patch.object(`
- `tests/test_workout_repair.py:180: ), patch.object(server, "_enqueue_automatic_performance_refresh", return_value=None), patch.object(`
- `tests/test_workout_repair.py:204: with patch.object(server.IntervalsClient, "fetch_snapshot", side_effect=fetch), patch.object(`
- `tests/test_workout_repair.py:206: ), patch.object(server, "_enqueue_automatic_performance_refresh", return_value=None), patch.object(`
- `tests/test_workout_repair.py:21: self.enterContext(patch.object(server, "http_json", side_effect=AssertionError("Unexpected live network")))`
- `tests/test_workout_repair.py:22: self.enterContext(patch.object(server.IntervalsClient, "get_paged_collection", side_effect=lambda *a, **k: deepcopy(list(self.remote.values()))))`
- `tests/test_workout_repair.py:238: with patch.object(server.IntervalsClient, "get_paged_collection", side_effect=read):`
- `tests/test_workout_repair.py:23: self.enterContext(patch.object(server.IntervalsClient, "get", side_effect=self.get))`
- `tests/test_workout_repair.py:24: self.enterContext(patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=self.upsert))`
- `tests/test_workout_repair.py:25: self.enterContext(patch.object(server.IntervalsClient, "delete_event", side_effect=self.delete))`
- `tests/test_workout_repair.py:266: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=upsert_with_intensity):`
- `tests/test_workout_repair.py:282: with patch.object(server, "local_feedback_context", return_value={"today": {"available_minutes": 30}}), patch.object(`
- `tests/test_workout_repair.py:284: ), patch.object(server, "list_external_calendar_events", return_value=[]):`
- `tests/test_workout_repair.py:294: with patch.object(server.IntervalsClient, "upsert_calendar_events", return_value=[{"id": "swim-event", **parsed}]):`
- `tests/test_workout_repair.py:318: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=slow_upsert):`
- `tests/test_workout_repair.py:334: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=edit_during_upsert):`
- `tests/test_workout_repair.py:355: with patch.object(server.IntervalsClient, "get_paged_collection", side_effect=read):`
- `tests/test_workout_repair.py:378: with patch.object(server, "local_feedback_context", return_value={"today": {"illness": "Synthetic illness"}}), patch.object(`
- `tests/test_workout_repair.py:380: ), patch.object(server, "list_external_calendar_events", return_value=[]):`
- `tests/test_workout_repair.py:422: with patch.object(server.IntervalsClient, "get", side_effect=restore_during_read):`
- `tests/test_workout_repair.py:458: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=wrong_date):`
- `tests/test_workout_repair.py:78: with patch.object(server, "list_workout_library", return_value=[invalid]):`
- `tests/test_workout_repair.py:85: with patch.object(server, "list_workout_library", return_value=[valid]):`
- `tests/test_workout_text.py:14: self.enterContext(patch.object(server, "local_now", return_value=datetime.now()))`

## P1-Aufruf- und Zustandsabhängigkeiten

Die folgende Tabelle ist die statische Grundlage für P1. Reads/Writes sind nur Namen, die im globalen Modulnamespace gebunden werden; lokale Variablen werden soweit AST-statisch erkennbar ausgefiltert. Dynamische Attribute, Closure-Zustand und indirekte Callbacks bleiben unsicher.

| Definition | Zeile | Direkte lokale Aufrufe | Globale Reads | Globale Writes | Imports im Body |
| --- | ---: | --- | --- | --- | --- |
| `ProviderResyncGate` | 300 | – | `AppError`, `contextmanager`, `threading` | – | – |
| `provider_operation` | 351 | – | `GARMIN_RESYNC_GATE`, `INTERVALS_RESYNC_GATE` | – | – |
| `intervals_operation` | 356 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `garmin_operation` | 364 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `IntervalsClient` | 375 | `_raise_chat_cancelled`, `compact_snapshot`, `deduplicate_api_records`, `intervals_workout_sport`, `latest_snapshot`, `local_now`, `selected`, `sync_date_windows`, `validate_intervals_workout_result`, `validate_workout_description`, `workout_event_payload` | `ALL_SYNC_DAYS`, `APP_NAME`, `Any`, `AppError`, `CONFIG`, `Callable`, `Config`, `IntervalsReadTransport`, `IntervalsWriteTransport`, `PLANNED_CALENDAR_FUTURE_DAYS`, `PLANNED_CALENDAR_HISTORY_DAYS`, `_raise_chat_cancelled`, … (+18) | – | – |
| `external_call` | 682 | `operation_error_code` | `Any`, `AppError`, `DATA_DIR`, `DIAGNOSTIC_CAPTURE`, `LOGGER`, `LOG_PATH`, `OPERATION_CONTEXT`, `REDACTOR`, `observability`, `operation_error_code`, `provider_error`, `time` | – | – |
| `serialise_conversation` | 874 | – | `AppError`, `CHAT_LOCK_TIMEOUT_SECONDS`, `CHAT_QUEUE`, `OPENAI_CONVERSATION_LOCK`, `wraps` | – | – |
| `utc_now` | 891 | – | `datetime`, `timezone` | – | – |
| `operation_trigger` | 964 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 970 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 979 | – | `Any` | – | – |
| `log_operation_event` | 989 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1016 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1037 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count`, `runtime_maintenance`, `wraps` | – | – |
| `database_manager` | 1080 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE` | – |
| `database` | 1107 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1113 | `database`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `KEY_VALUE_REPOSITORY`, `PROVIDER_RESYNC_KEYS`, `database`, `datetime`, `initialize_application_database`, `json`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_cleanup` | 1125 | – | `Any`, `cleanup_refresh_history`, `datetime`, `sync_freshness`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1133 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `runtime_events`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1145 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `runtime_events`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1179 | – | – | – | – |
| `_sync_job_error_class` | 1194 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1208 | – | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1217 | – | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1231 | `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1244 | `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1254 | `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1263 | – | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1273 | – | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1280 | `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1305 | `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1314 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1320 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1325 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1348 | – | `AppError` | – | – |
| `_pending_performance_job_id` | 1356 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1365 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1383 | `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1410 | – | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1419 | – | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1426 | – | `Any` | – | – |
| `_insert_sync_job` | 1436 | – | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 1461 | – | `Any`, `runtime_events` | – | – |
| `enqueue_sync_job` | 1475 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `runtime_maintenance`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 1502 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 1522 | `database`, `utc_now` | `Any`, `DB_LOCK`, `database`, `runtime_maintenance`, `utc_now` | – | – |
| `_sync_job_update` | 1543 | `database`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `runtime_events`, `utc_now` | – | – |
| `_sync_job_item_results` | 1581 | – | `Any` | – | – |
| `_sync_job_result_target` | 1587 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 1598 | `_sync_job_result_target` | `Any`, `REDACTOR`, `_sync_job_result_target` | – | – |
| `_sync_job_completion_snapshot` | 1618 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 1633 | – | `runtime_events` | – | – |
| `_sync_job_update_from_result` | 1650 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 1663 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 1672 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 1679 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 1696 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 1708 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 1720 | `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 1743 | – | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 1752 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 1772 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 1792 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | `Any`, `LOGGER`, `REDACTOR`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | – | – |
| `_run_claimed_sync_job` | 1810 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `runtime_maintenance` | – | – |
| `_sync_job_worker_loop` | 1820 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job`, `runtime_maintenance` | – | – |
| `start_sync_job_worker` | 1835 | – | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 1846 | `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_current_provider_freshness` | 1869 | `_garmin_core_error_entries`, `database`, `get_profile` | `Any`, `CONFIG`, `DB_LOCK`, `Path`, `_garmin_core_error_entries`, `database`, `datetime`, `get_kv`, `get_profile`, `sync_freshness`, `timezone` | – | – |
| `_audit_projection_fields` | 1883 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 1897 | – | `Any`, `json` | – | – |
| `_audit_projection` | 1908 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 1932 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 1937 | – | `Any` | – | – |
| `_cleanup_change_history` | 1949 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 1959 | – | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 1976 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2015 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2047 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2058 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2070 | – | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2084 | – | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2100 | `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2138 | `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2158 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2168 | `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2193 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2214 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2224 | `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2233 | `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2259 | `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2275 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2304 | `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2319 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |
| `sync_period` | 2357 | `get_kv` | `ALL_SYNC_DAYS`, `SYNC_PERIOD_DEFAULTS`, `get_kv` | – | – |
| `set_sync_period` | 2368 | `set_kv` | `ALL_SYNC_DAYS`, `Any`, `AppError`, `set_kv` | – | – |
| `sync_date_windows` | 2380 | `local_now` | `ALL_SYNC_DAYS`, `SYNC_CHUNK_DAYS`, `SYNC_EARLIEST_DATE`, `date`, `local_now`, `split_date_windows` | – | – |
| `provider_sync_cursor` | 2391 | `database` | `Any`, `DB_LOCK`, `database`, `read_cursor` | – | – |
| `update_provider_sync_cursor` | 2396 | `database`, `utc_now` | `DB_LOCK`, `database`, `utc_now`, `write_cursor` | – | – |
| `set_kv` | 2402 | `database`, `set_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `set_kv`, `sqlite3` | – | – |
| `_coach_error_metadata` | 2414 | – | `Any`, `Path`, `ROOT`, `observability` | – | – |
| `_safe_response_headers` | 2429 | – | `Any`, `REDACTOR` | – | – |
| `garmin_snapshot` | 2446 | `get_kv` | `Any`, `get_kv`, `json` | – | – |
| `garmin_configured` | 2454 | – | `CONFIG`, `Garmin` | – | – |
| `garmin_fixture_path` | 2458 | – | `CONFIG`, `Path`, `ROOT` | – | – |
| `activity_datetime` | 2466 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `activity_kind` | 2478 | – | `Any` | – | – |
| `_cycling_event_candidates` | 2493 | `activity_kind` | `Any`, `activity_kind` | – | – |
| `_cycling_event_interval` | 2503 | `activity_datetime`, `as_number` | `Any`, `activity_datetime`, `as_number`, `datetime`, `timedelta` | – | – |
| `_cycling_intervals_share_group` | 2514 | – | `datetime` | – | – |
| `_cycling_event_edges` | 2523 | `_cycling_intervals_share_group` | `_cycling_intervals_share_group`, `datetime` | – | – |
| `_cycling_event_group` | 2538 | – | `Any` | – | – |
| `parallel_cycling_event_groups` | 2552 | `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | `Any`, `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | – | – |
| `_garmin_duplicate_measurements` | 2564 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_activity_matches` | 2580 | `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | `Any`, `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | – | – |
| `garmin_activity_duplicates_intervals` | 2595 | `_garmin_activity_matches` | `Any`, `_garmin_activity_matches` | – | – |
| `filter_garmin_activities` | 2602 | `garmin_activity_duplicates_intervals` | `Any`, `garmin_activity_duplicates_intervals` | – | – |
| `intervals_activity_device_source` | 2609 | – | `Any` | – | – |
| `intervals_cycling_activities_match` | 2624 | `activity_datetime`, `activity_kind`, `as_number`, `first_present` | `Any`, `activity_datetime`, `activity_kind`, `as_number`, `first_present` | – | – |
| `_latest_activity_id` | 2647 | `activity_datetime`, `first_present` | `Any`, `activity_datetime`, `first_present` | – | – |
| `_wahoo_garmin_pairs` | 2660 | `activity_datetime`, `activity_kind`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | `Any`, `activity_datetime`, `activity_kind`, `datetime`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | – | – |
| `_wahoo_garmin_duplicate_view` | 2678 | `first_present` | `Any`, `datetime`, `first_present` | – | – |
| `latest_wahoo_garmin_duplicate` | 2696 | `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | `Any`, `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | – | – |
| `garmin_activity_max_hr` | 2711 | `activity_kind`, `as_number`, `first_present` | `Any`, `activity_kind`, `as_number`, `first_present` | – | – |
| `merge_garmin_max_hr` | 2726 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_key` | 2754 | – | `Any` | – | – |
| `_garmin_numeric` | 2758 | `as_number`, `first_present` | `Any`, `as_number`, `first_present` | – | – |
| `_garmin_vo2_value` | 2764 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_colon_duration_seconds` | 2769 | – | – | – | – |
| `_garmin_duration_seconds` | 2778 | `_garmin_colon_duration_seconds`, `as_number`, `first_present` | `Any`, `_garmin_colon_duration_seconds`, `as_number`, `first_present` | – | – |
| `_garmin_race_slot` | 2797 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_race_time` | 2810 | `_garmin_duration_seconds` | `Any`, `_garmin_duration_seconds` | – | – |
| `_garmin_weight_kg` | 2814 | `_garmin_key`, `as_number`, `first_present` | `Any`, `_garmin_key`, `as_number`, `first_present` | – | – |
| `_garmin_record_date` | 2832 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_collect_garmin_weight_records` | 2846 | `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | `Any`, `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | – | – |
| `garmin_weight_records` | 2862 | `_collect_garmin_weight_records` | `Any`, `_collect_garmin_weight_records` | – | – |
| `garmin_weight_metric` | 2868 | `garmin_weight_records`, `metric` | `Any`, `GARMIN_PERFORMANCE_SOURCE`, `garmin_weight_records`, `metric` | – | – |
| `garmin_weight_average` | 2876 | `garmin_weight_records` | `Any`, `date`, `garmin_weight_records`, `timedelta` | – | – |
| `_collect_garmin_numeric_values` | 2889 | `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | `Any`, `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | – | – |
| `_garmin_last_numeric` | 2902 | `_collect_garmin_numeric_values` | `Any`, `_collect_garmin_numeric_values` | – | – |
| `_garmin_last_value` | 2909 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_bounded_metric` | 2927 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_pace_seconds` | 2932 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_mapping_nodes` | 2958 | `_garmin_mapping_nodes` | `Any`, `Iterator`, `_garmin_mapping_nodes` | – | – |
| `_garmin_sport_category` | 2968 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `garmin_profile_max_hr` | 2977 | `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | `Any`, `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | – | – |
| `_garmin_collect_vo2_values` | 2987 | `_garmin_collect_vo2_values`, `_garmin_key`, `_garmin_sport_category`, `_garmin_vo2_value` | `Any`, `_garmin_collect_vo2_values`, `_garmin_key`, `_garmin_sport_category`, `_garmin_vo2_value` | – | – |

### Zyklische Gruppen

Statisch erkannte SCCs im direkten lokalen Aufrufgraphen: 12. Jede Gruppe ist als gemeinsame Umzugseinheit zu prüfen.

- `_collect_garmin_numeric_values`
- `_collect_garmin_weight_records`
- `_fixture_sleep_dates`
- `_garmin_collect_race_predictions`
- `_garmin_collect_vo2_values`
- `_garmin_mapping_nodes`
- `_shift_fixture_sleep_dates`
- `compact_garmin_context`
- `get_kv`
- `readiness_score_value`
- `set_kv`
- `weather_state`

## Vollständiges Inventar

`Zielmodul` und `Phase` folgen der Bereichstabelle des vollständigen Plans. Jede Zuordnung ist konkret; eine künftig neu hinzukommende nicht auflösbare Bindung wird als offen markiert und darf nicht stillschweigend erfunden werden. `Status` beschreibt den jeweils inventarisierten Stand.

| Art | Quellname | Ausgangszeile | Zielmodul | Phase | Status | Referenzen außerhalb von server.py |
| --- | --- | ---: | --- | --- | --- | --- |
| Importbindung | `annotations` | 1 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `MAX_ATTACHMENT_STORAGE_BYTES` | 2 | `backend/coach/attachments` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_attachments.py:169 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `MAX_GEMINI_INLINE_IMAGE_BYTES` | 2 | `backend/coach/attachments` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_attachments.py:176 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:214 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `MAX_REQUEST_BYTES` | 2 | `backend/coach/attachments` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_inline_image_bytes` | 2 | `backend/coach/attachments` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `model_input` | 2 | `backend/coach/attachments` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_attachment_data` | 2 | `backend/coach/attachments` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_attachments` | 2 | `backend/coach/attachments` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `base64` | 7 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `difflib` | 8 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `hashlib` | 9 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `hmac` | 10 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `json` | 11 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_workout_repair.py:572 (direkt/dynamisch unklar) |
| Importbindung | `logging` | 12 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `math` | 13 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `mimetypes` | 14 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `os` | 15 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `platform` | 16 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `queue` | 17 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:8208 (direkt/dynamisch unklar); tests/test_server.py:8234 (direkt/dynamisch unklar) |
| Importbindung | `re` | 18 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `secrets` | 19 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_coach_language_recovery.py:42 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:69 (direkt/dynamisch unklar) |
| Importbindung | `shutil` | 20 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `socket` | 21 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `sqlite3` | 22 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1068 (direkt/dynamisch unklar); tests/test_server.py:1243 (direkt/dynamisch unklar); tests/test_server.py:1825 (direkt/dynamisch unklar) |
| Importbindung | `threading` | 23 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_diagnostic_followups.py:170 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:37 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:56 (direkt/dynamisch unklar); tests/test_server.py:228 (direkt/dynamisch unklar); tests/test_server.py:238 (direkt/dynamisch unklar) |
| Importbindung | `tempfile` | 24 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7817 (direkt/dynamisch unklar) |
| Importbindung | `time` | 25 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/support.py:130 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:108 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:41 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:95 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:38 (direkt/dynamisch unklar); tests/test_coach_review.py:257 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:257 (direkt/dynamisch unklar); tests/test_server.py:1357 (direkt/dynamisch unklar); tests/test_server.py:1370 (direkt/dynamisch unklar); tests/test_server.py:4096 (direkt/dynamisch unklar); tests/test_server.py:7836 (direkt/dynamisch unklar); tests/test_server.py:8009 (direkt/dynamisch unklar); tests/test_server.py:8120 (direkt/dynamisch unklar); tests/test_server.py:8131 (direkt/dynamisch unklar); tests/test_server.py:8165 (direkt/dynamisch unklar) |
| Importbindung | `uuid` | 26 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `zipfile` | 27 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ContextVar` | 28 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `nullcontext` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `contextmanager` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `dataclass` | 30 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `date` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1618 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `datetime` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `timedelta` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:541 (direkt/dynamisch unklar) |
| Importbindung | `timezone` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `wraps` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `BaseHTTPRequestHandler` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ThreadingHTTPServer` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `SimpleCookie` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Path` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Any` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Callable` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Iterator` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `NoReturn` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPError` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4513 (direkt/dynamisch unklar); tests/test_server.py:7680 (direkt/dynamisch unklar); tests/test_server.py:7711 (direkt/dynamisch unklar); tests/test_server.py:7762 (direkt/dynamisch unklar); tests/test_server.py:7947 (direkt/dynamisch unklar); tests/test_server.py:7971 (direkt/dynamisch unklar); tests/test_server.py:7986 (direkt/dynamisch unklar); tests/test_server.py:8023 (direkt/dynamisch unklar) |
| Importbindung | `URLError` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7752 (direkt/dynamisch unklar) |
| Importbindung | `parse_qs` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `quote` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlencode` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlparse` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Request` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlopen` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4274 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4520 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4569 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4600 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4633 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4701 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7682 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7701 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7718 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7752 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7769 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7894 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7930 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7957 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7978 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8028 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8070 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8083 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8107 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8157 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `database_row_factory` | 41 | `backend/db` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ABORTED_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COMPETITION_NOT_FOUND_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_LIBRARY_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_PLANNING_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GEMINI_API_KEY_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERNAL_SERVER_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERVALS_API_KEY_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_LIBRARY_ID_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_DATE_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_ID_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `NOT_FOUND_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `OPENAI_API_KEY_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PLANNED_CALENDAR_RECHECK_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STALE_PLANNING_REVISION_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STRUCTURED_AUTHORIZATION_ERROR` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AppError` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:161 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_server.py:1008 (direkt/dynamisch unklar); tests/test_server.py:1298 (direkt/dynamisch unklar); tests/test_server.py:1408 (direkt/dynamisch unklar); tests/test_server.py:1415 (direkt/dynamisch unklar); tests/test_server.py:1532 (direkt/dynamisch unklar); tests/test_server.py:1633 (direkt/dynamisch unklar); tests/test_server.py:1637 (direkt/dynamisch unklar); tests/test_server.py:1663 (direkt/dynamisch unklar); tests/test_server.py:1800 (direkt/dynamisch unklar); tests/test_server.py:2051 (direkt/dynamisch unklar); tests/test_server.py:2057 (direkt/dynamisch unklar); tests/test_server.py:2068 (direkt/dynamisch unklar); tests/test_server.py:2072 (direkt/dynamisch unklar); tests/test_server.py:2073 (direkt/dynamisch unklar); tests/test_server.py:2075 (direkt/dynamisch unklar); tests/test_server.py:2080 (direkt/dynamisch unklar); tests/test_server.py:2083 (direkt/dynamisch unklar); tests/test_server.py:2088 (direkt/dynamisch unklar); tests/test_server.py:2091 (direkt/dynamisch unklar); tests/test_server.py:2096 (direkt/dynamisch unklar); tests/test_server.py:2099 (direkt/dynamisch unklar); tests/test_server.py:2106 (direkt/dynamisch unklar); tests/test_server.py:2131 (direkt/dynamisch unklar); tests/test_server.py:2387 (direkt/dynamisch unklar); tests/test_server.py:2449 (direkt/dynamisch unklar); tests/test_server.py:2531 (direkt/dynamisch unklar); tests/test_server.py:2532 (direkt/dynamisch unklar); tests/test_server.py:268 (direkt/dynamisch unklar); tests/test_server.py:280 (direkt/dynamisch unklar); tests/test_server.py:3073 (direkt/dynamisch unklar); tests/test_server.py:3110 (direkt/dynamisch unklar); tests/test_server.py:333 (direkt/dynamisch unklar); tests/test_server.py:3544 (direkt/dynamisch unklar); tests/test_server.py:3644 (direkt/dynamisch unklar); tests/test_server.py:365 (direkt/dynamisch unklar); tests/test_server.py:3660 (direkt/dynamisch unklar); tests/test_server.py:3699 (direkt/dynamisch unklar); tests/test_server.py:3726 (direkt/dynamisch unklar); tests/test_server.py:3734 (direkt/dynamisch unklar); tests/test_server.py:3745 (direkt/dynamisch unklar); tests/test_server.py:3766 (direkt/dynamisch unklar); tests/test_server.py:3778 (direkt/dynamisch unklar); tests/test_server.py:3782 (direkt/dynamisch unklar); tests/test_server.py:3970 (direkt/dynamisch unklar); tests/test_server.py:4131 (direkt/dynamisch unklar); tests/test_server.py:4192 (direkt/dynamisch unklar); tests/test_server.py:4289 (direkt/dynamisch unklar); tests/test_server.py:4302 (direkt/dynamisch unklar); tests/test_server.py:4312 (direkt/dynamisch unklar); tests/test_server.py:4327 (direkt/dynamisch unklar); tests/test_server.py:4341 (direkt/dynamisch unklar); tests/test_server.py:4424 (direkt/dynamisch unklar); tests/test_server.py:444 (direkt/dynamisch unklar); tests/test_server.py:4508 (direkt/dynamisch unklar); tests/test_server.py:4510 (direkt/dynamisch unklar); tests/test_server.py:4521 (direkt/dynamisch unklar); tests/test_server.py:4566 (direkt/dynamisch unklar); tests/test_server.py:4634 (direkt/dynamisch unklar); tests/test_server.py:4709 (direkt/dynamisch unklar); tests/test_server.py:4711 (direkt/dynamisch unklar); tests/test_server.py:4735 (direkt/dynamisch unklar); tests/test_server.py:4810 (direkt/dynamisch unklar); tests/test_server.py:4881 (direkt/dynamisch unklar); tests/test_server.py:5046 (direkt/dynamisch unklar); tests/test_server.py:5063 (direkt/dynamisch unklar); tests/test_server.py:5269 (direkt/dynamisch unklar); tests/test_server.py:5276 (direkt/dynamisch unklar); tests/test_server.py:5286 (direkt/dynamisch unklar); tests/test_server.py:5288 (direkt/dynamisch unklar); tests/test_server.py:533 (direkt/dynamisch unklar); tests/test_server.py:5437 (direkt/dynamisch unklar); tests/test_server.py:5550 (direkt/dynamisch unklar); tests/test_server.py:5602 (direkt/dynamisch unklar); tests/test_server.py:5615 (direkt/dynamisch unklar); tests/test_server.py:5823 (direkt/dynamisch unklar); tests/test_server.py:5929 (direkt/dynamisch unklar); tests/test_server.py:5933 (direkt/dynamisch unklar); tests/test_server.py:5942 (direkt/dynamisch unklar); tests/test_server.py:5946 (direkt/dynamisch unklar); tests/test_server.py:5964 (direkt/dynamisch unklar); tests/test_server.py:5975 (direkt/dynamisch unklar); tests/test_server.py:6442 (direkt/dynamisch unklar); tests/test_server.py:6455 (direkt/dynamisch unklar); tests/test_server.py:6467 (direkt/dynamisch unklar); tests/test_server.py:7390 (direkt/dynamisch unklar); tests/test_server.py:7397 (direkt/dynamisch unklar); tests/test_server.py:7655 (direkt/dynamisch unklar); tests/test_server.py:7663 (direkt/dynamisch unklar); tests/test_server.py:7683 (direkt/dynamisch unklar); tests/test_server.py:7719 (direkt/dynamisch unklar); tests/test_server.py:7753 (direkt/dynamisch unklar); tests/test_server.py:7770 (direkt/dynamisch unklar); tests/test_server.py:784 (direkt/dynamisch unklar); tests/test_server.py:7958 (direkt/dynamisch unklar); tests/test_server.py:7979 (direkt/dynamisch unklar); tests/test_server.py:7993 (direkt/dynamisch unklar); tests/test_server.py:8000 (direkt/dynamisch unklar); tests/test_server.py:8029 (direkt/dynamisch unklar); tests/test_server.py:803 (direkt/dynamisch unklar); tests/test_server.py:8084 (direkt/dynamisch unklar); tests/test_server.py:8108 (direkt/dynamisch unklar); tests/test_server.py:8163 (direkt/dynamisch unklar); tests/test_server.py:8176 (direkt/dynamisch unklar); tests/test_server.py:8179 (direkt/dynamisch unklar); tests/test_server.py:8271 (direkt/dynamisch unklar); tests/test_server.py:8280 (direkt/dynamisch unklar); tests/test_server.py:8283 (direkt/dynamisch unklar); tests/test_server.py:8286 (direkt/dynamisch unklar); tests/test_server.py:8364 (direkt/dynamisch unklar); tests/test_server.py:8413 (direkt/dynamisch unklar); tests/test_server.py:8434 (direkt/dynamisch unklar); tests/test_server.py:8534 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Importbindung | `ClientDisconnected` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8158 (direkt/dynamisch unklar); tests/test_server.py:8159 (direkt/dynamisch unklar); tests/test_server.py:8207 (direkt/dynamisch unklar) |
| Importbindung | `provider_error` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `public_app_error_status` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4509 (direkt/dynamisch unklar); tests/test_server.py:4510 (direkt/dynamisch unklar) |
| Importbindung | `app_config` | 63 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_audit_remediation.py:206 (direkt/dynamisch unklar); tests/test_provider_review.py:184 (direkt/dynamisch unklar); tests/test_provider_review.py:317 (direkt/dynamisch unklar); tests/test_server.py:217 (direkt/dynamisch unklar); tests/test_server.py:6498 (direkt/dynamisch unklar); tests/test_server.py:6505 (direkt/dynamisch unklar); tests/test_server.py:6514 (direkt/dynamisch unklar); tests/test_server.py:6530 (direkt/dynamisch unklar) |
| Importbindung | `observability` | 64 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar); tests/test_provider_review.py:32 (direkt/dynamisch unklar); tests/test_server.py:216 (direkt/dynamisch unklar); tests/test_server.py:7616 (direkt/dynamisch unklar); tests/test_server.py:7681 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:8091 (direkt/dynamisch unklar); tests/test_server.py:8370 (direkt/dynamisch unklar); tests/test_server.py:8375 (direkt/dynamisch unklar); tests/test_server.py:8378 (direkt/dynamisch unklar) |
| Importbindung | `runtime_events` | 65 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `runtime_maintenance` | 66 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `sync_freshness` | 67 | `backend/sync` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8498 (direkt/dynamisch unklar); tests/test_server.py:8503 (direkt/dynamisch unklar) |
| Importbindung | `SettingsService` | 68 | `backend/settings` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `initialize_application_database` | 69 | `backend/db/bootstrap` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ActivityFeedbackRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1159 (direkt/dynamisch unklar) |
| Importbindung | `ChatRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1085 (direkt/dynamisch unklar) |
| Importbindung | `CheckinRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1093 (direkt/dynamisch unklar) |
| Importbindung | `CompetitionRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1125 (direkt/dynamisch unklar) |
| Importbindung | `KeyValueRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1076 (direkt/dynamisch unklar); tests/test_server.py:1110 (direkt/dynamisch unklar) |
| Importbindung | `PlanAdjustmentRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1149 (direkt/dynamisch unklar) |
| Importbindung | `ProfileRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1110 (direkt/dynamisch unklar) |
| Importbindung | `SnapshotRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1172 (direkt/dynamisch unklar) |
| Importbindung | `TrainingPlanRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1134 (direkt/dynamisch unklar) |
| Importbindung | `DatabaseManager` | 71 | `backend/db/manager` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CURRENT_DATABASE_INDEXES` | 72 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:163 (direkt/dynamisch unklar) |
| Importbindung | `CURRENT_DATABASE_SCHEMA` | 72 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1540 (direkt/dynamisch unklar); tests/test_server.py:162 (direkt/dynamisch unklar) |
| Importbindung | `configure_cipher` | 72 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `database_index_names` | 72 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:163 (direkt/dynamisch unklar) |
| Importbindung | `database_schema_is_current` | 72 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `Config` | 79 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `DEFAULT_OPENAI_BASE_URL` | 79 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `load_config` | 79 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsReadTransport` | 80 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsWriteTransport` | 80 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `fetch_paged_collection` | 80 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `audio_provider` | 81 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `calendar_provider` | 82 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_provider` | 83 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_http` | 84 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_provider` | 85 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_usage` | 86 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_error_detail` | 87 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_bounded_response` | 87 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `WorkoutTextError` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `canonical_workout_zones` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `structured_duration` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `verify_workout_readback` | 88 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GarminCollectionOptions` | 89 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `collect_garmin_data` | 89 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:241 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `split_date_windows` | 90 | `backend/sync/windows` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_cursor` | 91 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `write_cursor` | 91 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_sync_operation_state` | 92 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `project_sync_status` | 92 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `daily_sync_is_due` | 93 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_daily_sync_value` | 93 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `cleanup_refresh_history` | 94 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `create_refresh_record` | 94 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `finish_refresh_record` | 94 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `latest_snapshot_in_transaction` | 95 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `save_snapshot_in_transaction` | 95 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ReconcileDependencies` | 96 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_planned_unit_state` | 96 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_payload` | 97 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_rows` | 97 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_bounds` | 98 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `TRAINING_PLAN_STATUSES` | 99 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_metadata` | 99 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AdaptiveDependencies` | 100 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_adaptive_changes` | 100 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PlanningChangeDependencies` | 101 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes` | 101 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes_in_db` | 101 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `JOB_STATUSES` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ITEM_STATUSES` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `aggregate_job_status` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_progress` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `decode_job_payload` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `has_active_job` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `job_dto` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `list_jobs` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_job` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `is_retryable_error` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `retry_delay` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_job_request` | 104 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTIVITY_FIELDS` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_sections_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_value_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_json_size_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_projection_meta_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_activity_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workout_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workouts_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_planned_event_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `detailed_coach_activity_value` | 118 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_DIALOGUE_INSTRUCTIONS` | 130 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `dialogue_tools` | 130 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_request` | 130 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `build_tool_contracts` | 131 | `backend/coach/tools` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `command_receipt` | 132 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `effects_from_receipts` | 132 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_resolved_receipts` | 132 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `outcome_status` | 132 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `authorized_operations` | 136 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_operation` | 136 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_scope` | 136 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `scope_values` | 136 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTION_LABELS` | 137 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_effect_label` | 137 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_failure_lines` | 137 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_language_recovery.py:163 (direkt/dynamisch unklar) |
| Importbindung | `coach_observed_sync_lines` | 137 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_header_items` | 138 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_json_bytes` | 138 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:7381 (direkt/dynamisch unklar) |
| Importbindung | `response_headers` | 138 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `session_cookies` | 138 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_audio_body` | 144 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_body` | 144 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_json` | 144 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_application_state` | 149 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_decode_payload` | 149 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_workout_library` | 149 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_manifest` | 149 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_jsonl_rows` | 149 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Globale Bindung | `Garmin` | 158 | `sync/` | P6 | offen | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4061 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `sqlite_backend` | 163 | `db/` | P1 | offen | tests/test_server.py:1243 (direkt/dynamisch unklar); tests/test_server.py:6435 (direkt/dynamisch unklar); tests/test_server.py:6448 (direkt/dynamisch unklar) |
| Globale Bindung | `SQLCIPHER_AVAILABLE` | 164 | `db/` | P1 | offen | tests/test_audit_remediation.py:282 (direkt/dynamisch unklar); tests/test_provider_review.py:315 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:323 (direkt/dynamisch unklar); tests/test_server.py:2701 (direkt/dynamisch unklar); tests/test_server.py:3236 (direkt/dynamisch unklar); tests/test_server.py:6412 (direkt/dynamisch unklar) |
| Globale Bindung | `ROOT` | 170 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:6493 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6513 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PUBLIC_DIR` | 171 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2411 (direkt/dynamisch unklar); tests/test_server.py:2412 (direkt/dynamisch unklar); tests/test_server.py:2428 (direkt/dynamisch unklar); tests/test_server.py:2429 (direkt/dynamisch unklar); tests/test_server.py:7179 (direkt/dynamisch unklar); tests/test_server.py:7180 (direkt/dynamisch unklar); tests/test_server.py:7191 (direkt/dynamisch unklar); tests/test_server.py:7192 (direkt/dynamisch unklar); tests/test_server.py:7200 (direkt/dynamisch unklar); tests/test_server.py:7201 (direkt/dynamisch unklar); tests/test_server.py:7209 (direkt/dynamisch unklar); tests/test_server.py:7210 (direkt/dynamisch unklar); tests/test_server.py:7216 (direkt/dynamisch unklar); tests/test_server.py:7217 (direkt/dynamisch unklar); tests/test_server.py:7226 (direkt/dynamisch unklar); tests/test_server.py:7227 (direkt/dynamisch unklar); tests/test_server.py:7228 (direkt/dynamisch unklar); tests/test_server.py:7229 (direkt/dynamisch unklar); tests/test_server.py:7440 (direkt/dynamisch unklar); tests/test_server.py:7459 (direkt/dynamisch unklar); tests/test_server.py:8509 (direkt/dynamisch unklar); tests/test_server.py:8510 (direkt/dynamisch unklar) |
| Globale Bindung | `DATA_DIR` | 172 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:112 (direkt/dynamisch unklar); tests/test_server.py:121 (direkt/dynamisch unklar); tests/test_server.py:177 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2706 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3247 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6418 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6493 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6513 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7616 (direkt/dynamisch unklar); tests/test_server.py:7681 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:8091 (direkt/dynamisch unklar); tests/test_server.py:8378 (direkt/dynamisch unklar); tests/test_server.py:97 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 173 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:107 (direkt/dynamisch unklar); tests/test_server.py:111 (direkt/dynamisch unklar); tests/test_server.py:113 (direkt/dynamisch unklar); tests/test_server.py:122 (direkt/dynamisch unklar); tests/test_server.py:2706 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3247 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6418 (Monkeypatch/getattr/sys.modules); tests/test_server.py:98 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 174 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:30 (Monkeypatch/getattr/sys.modules); tests/test_server.py:108 (direkt/dynamisch unklar); tests/test_server.py:114 (direkt/dynamisch unklar); tests/test_server.py:123 (direkt/dynamisch unklar); tests/test_server.py:7616 (direkt/dynamisch unklar); tests/test_server.py:7681 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:8091 (direkt/dynamisch unklar); tests/test_server.py:8378 (direkt/dynamisch unklar); tests/test_server.py:99 (direkt/dynamisch unklar) |
| Globale Bindung | `ASSET_INDEX_HTML` | 175 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_API_JS` | 176 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_APP_JS` | 177 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_NAVIGATION_JS` | 178 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STATE_JS` | 179 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_VIEWS_JS` | 180 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_FORMS_JS` | 181 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_COMPONENTS_JS` | 182 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STYLES_CSS` | 183 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_SERVICE_WORKER_JS` | 184 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_MANIFEST` | 185 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_LOGO` | 186 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_ICON` | 187 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_TARGETS` | 188 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `VERSIONED_STATIC_ASSETS` | 203 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_REVALIDATE_ASSETS` | 204 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_NAME` | 205 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_GARMIN_NAME` | 206 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_WELLNESS_NAME` | 207 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UTC_OFFSET_SUFFIX` | 208 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ISO_MIDNIGHT_SUFFIX` | 209 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `JSON_MEDIA_TYPE` | 210 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OCTET_STREAM_MIME` | 211 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSES_PATH` | 212 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VO2MAX_UNIT` | 213 | `performance/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_RUN_PREDICTION_SOURCE` | 214 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_STARTED_EVENT` | 215 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_COMPLETED_EVENT` | 216 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLAN_CONSTRAINTS_PREFIX` | 217 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_SCOPE_PREFIX` | 218 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LOCAL_INTERVALS_SCOPE` | 219 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `WORKDAY_TIME_LABEL` | 220 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_WORKOUT_LABEL` | 221 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `FULL_RESYNC_LABEL` | 222 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DAILY_AUTO_UPDATE_LABEL` | 223 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `APP_NAME` | 224 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UUID_PATTERN` | 225 | `http_api/` | P10 | offen | tests/test_server.py:3072 (direkt/dynamisch unklar) |
| Globale Bindung | `PAYLOAD_HASH_PATTERN` | 226 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `DATE_ONLY_PATTERN` | 227 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMPETITION_SQL` | 228 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_ACTION_PROPOSAL_SQL` | 229 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INSERT_LIBRARY_SQL` | 230 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_PLANNED_UNIT_SQL` | 231 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMPETITION_CONFLICT_SQL` | 232 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNED_PAYLOAD_SQL` | 233 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_LIBRARY_PAYLOAD_SQL` | 234 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMMAND_RECEIPT_SQL` | 235 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMMAND_RECEIPT_SQL` | 236 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNING_REVISION_SQL` | 237 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_USER_MESSAGE_SQL` | 238 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_IMMUTABLE_MAX_AGE` | 239 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `APP_VERSION` | 240 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2503 (direkt/dynamisch unklar); tests/test_server.py:7173 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 241 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 242 | `http_api/` | P10 | offen | tests/test_server.py:4712 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 243 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 244 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 245 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 246 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 247 | `coach/streams.py` | P8 | offen | tests/test_server.py:1511 (direkt/dynamisch unklar); tests/test_server.py:1521 (direkt/dynamisch unklar); tests/test_server.py:1522 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_EXTERNAL_RESPONSE_BYTES` | 248 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_DEFAULT_MAX_OUTPUT_TOKENS` | 252 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LONG_PLAN_MAX_OUTPUT_TOKENS` | 253 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_FOLLOWUP_MAX_OUTPUT_TOKENS` | 254 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_TIMEOUT_SECONDS` | 255 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MESSAGE_ATTACHMENTS_QUERY` | 256 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_BASE_URL` | 257 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 258 | `providers/` | P2 | offen | tests/test_server.py:5698 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 259 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 260 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 261 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 262 | `coach/` | P7 | offen | tests/test_server.py:4740 (direkt/dynamisch unklar); tests/test_server.py:5066 (direkt/dynamisch unklar); tests/test_server.py:5074 (direkt/dynamisch unklar); tests/test_server.py:5426 (direkt/dynamisch unklar); tests/test_server.py:5556 (direkt/dynamisch unklar); tests/test_server.py:5566 (direkt/dynamisch unklar); tests/test_server.py:5568 (direkt/dynamisch unklar); tests/test_server.py:5571 (direkt/dynamisch unklar); tests/test_server.py:5574 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5588 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 263 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 264 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:150 (direkt/dynamisch unklar); tests/test_audit_remediation.py:156 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:199 (direkt/dynamisch unklar); tests/test_audit_remediation.py:32 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:73 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1056 (direkt/dynamisch unklar); tests/test_server.py:128 (direkt/dynamisch unklar); tests/test_server.py:1330 (direkt/dynamisch unklar); tests/test_server.py:1335 (direkt/dynamisch unklar); tests/test_server.py:1338 (direkt/dynamisch unklar); tests/test_server.py:1356 (direkt/dynamisch unklar); tests/test_server.py:1359 (direkt/dynamisch unklar); tests/test_server.py:1363 (direkt/dynamisch unklar); tests/test_server.py:1440 (direkt/dynamisch unklar); tests/test_server.py:1552 (direkt/dynamisch unklar); tests/test_server.py:159 (direkt/dynamisch unklar); tests/test_server.py:1689 (direkt/dynamisch unklar); tests/test_server.py:2441 (direkt/dynamisch unklar); tests/test_server.py:2455 (direkt/dynamisch unklar); tests/test_server.py:2468 (direkt/dynamisch unklar); tests/test_server.py:2525 (direkt/dynamisch unklar); tests/test_server.py:2542 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2684 (direkt/dynamisch unklar); tests/test_server.py:2689 (direkt/dynamisch unklar); tests/test_server.py:2887 (direkt/dynamisch unklar); tests/test_server.py:2967 (direkt/dynamisch unklar); tests/test_server.py:4490 (direkt/dynamisch unklar); tests/test_server.py:4759 (direkt/dynamisch unklar); tests/test_server.py:4891 (direkt/dynamisch unklar); tests/test_server.py:4914 (direkt/dynamisch unklar); tests/test_server.py:4937 (direkt/dynamisch unklar); tests/test_server.py:4959 (direkt/dynamisch unklar); tests/test_server.py:4973 (direkt/dynamisch unklar); tests/test_server.py:4979 (direkt/dynamisch unklar); tests/test_server.py:4996 (direkt/dynamisch unklar); tests/test_server.py:5004 (direkt/dynamisch unklar); tests/test_server.py:5326 (direkt/dynamisch unklar); tests/test_server.py:5368 (direkt/dynamisch unklar); tests/test_server.py:5456 (direkt/dynamisch unklar); tests/test_server.py:5479 (direkt/dynamisch unklar); tests/test_server.py:5721 (direkt/dynamisch unklar); tests/test_server.py:5733 (direkt/dynamisch unklar); tests/test_server.py:5752 (direkt/dynamisch unklar); tests/test_server.py:5826 (direkt/dynamisch unklar); tests/test_server.py:5848 (direkt/dynamisch unklar); tests/test_server.py:5857 (direkt/dynamisch unklar); tests/test_server.py:5982 (direkt/dynamisch unklar); tests/test_server.py:6274 (direkt/dynamisch unklar); tests/test_server.py:6337 (direkt/dynamisch unklar); tests/test_server.py:6382 (direkt/dynamisch unklar); tests/test_server.py:640 (direkt/dynamisch unklar); tests/test_server.py:6421 (direkt/dynamisch unklar); tests/test_server.py:6430 (direkt/dynamisch unklar); tests/test_server.py:6606 (direkt/dynamisch unklar); tests/test_server.py:6615 (direkt/dynamisch unklar); tests/test_server.py:6625 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:684 (direkt/dynamisch unklar); tests/test_server.py:695 (direkt/dynamisch unklar); tests/test_server.py:709 (direkt/dynamisch unklar); tests/test_server.py:7570 (direkt/dynamisch unklar); tests/test_server.py:8346 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8351 (direkt/dynamisch unklar); tests/test_server.py:8487 (direkt/dynamisch unklar); tests/test_server.py:8501 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 265 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7580 (direkt/dynamisch unklar); tests/test_server.py:7592 (direkt/dynamisch unklar); tests/test_server.py:7595 (direkt/dynamisch unklar); tests/test_server.py:7608 (direkt/dynamisch unklar); tests/test_server.py:7609 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 266 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 267 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 268 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 269 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 270 | `performance/` | P3 | offen | tests/test_server.py:648 (direkt/dynamisch unklar); tests/test_server.py:654 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 271 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 272 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 273 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:154 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 274 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8264 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 275 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8264 (direkt/dynamisch unklar); tests/test_server.py:8277 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 276 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 277 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 278 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 279 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 280 | `coach/jobs.py` | P8 | offen | tests/test_server.py:240 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 281 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:155 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 282 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:300 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 283 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 284 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 285 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 286 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 287 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 288 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 289 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 290 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5733 (direkt/dynamisch unklar); tests/test_server.py:5752 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 291 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LOCK` | 292 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7832 (direkt/dynamisch unklar); tests/test_server.py:7838 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 293 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7833 (direkt/dynamisch unklar); tests/test_server.py:7834 (direkt/dynamisch unklar); tests/test_server.py:7839 (direkt/dynamisch unklar); tests/test_server.py:7840 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 294 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 295 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 296 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 297 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Klasse | `ProviderResyncGate` | 300 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 347 | `sync/` | P6 | offen | tests/test_server.py:6460 (direkt/dynamisch unklar); tests/test_server.py:6475 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 348 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 351 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 356 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 364 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `CONFIG` | 372 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:154 (direkt/dynamisch unklar); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (direkt/dynamisch unklar); tests/test_provider_review.py:196 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:314 (direkt/dynamisch unklar); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:327 (direkt/dynamisch unklar); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1019 (direkt/dynamisch unklar); tests/test_server.py:1020 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1028 (direkt/dynamisch unklar); tests/test_server.py:1029 (Monkeypatch/getattr/sys.modules); tests/test_server.py:103 (direkt/dynamisch unklar); tests/test_server.py:120 (direkt/dynamisch unklar); tests/test_server.py:1243 (direkt/dynamisch unklar); tests/test_server.py:1314 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1314 (direkt/dynamisch unklar); tests/test_server.py:175 (direkt/dynamisch unklar); tests/test_server.py:177 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2446 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2446 (direkt/dynamisch unklar); tests/test_server.py:2485 (direkt/dynamisch unklar); tests/test_server.py:2486 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2515 (direkt/dynamisch unklar); tests/test_server.py:2516 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2530 (direkt/dynamisch unklar); tests/test_server.py:2531 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2592 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2592 (direkt/dynamisch unklar); tests/test_server.py:2687 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2687 (direkt/dynamisch unklar); tests/test_server.py:2696 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2696 (direkt/dynamisch unklar); tests/test_server.py:2705 (direkt/dynamisch unklar); tests/test_server.py:2706 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3246 (direkt/dynamisch unklar); tests/test_server.py:3247 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3488 (direkt/dynamisch unklar); tests/test_server.py:3561 (direkt/dynamisch unklar); tests/test_server.py:3581 (direkt/dynamisch unklar); tests/test_server.py:3592 (direkt/dynamisch unklar); tests/test_server.py:3611 (direkt/dynamisch unklar); tests/test_server.py:3787 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3787 (direkt/dynamisch unklar); tests/test_server.py:3805 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3805 (direkt/dynamisch unklar); tests/test_server.py:3815 (direkt/dynamisch unklar); tests/test_server.py:4060 (direkt/dynamisch unklar); tests/test_server.py:4061 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4128 (direkt/dynamisch unklar); tests/test_server.py:4136 (direkt/dynamisch unklar); tests/test_server.py:4228 (direkt/dynamisch unklar); tests/test_server.py:4230 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4273 (direkt/dynamisch unklar); tests/test_server.py:4274 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4298 (direkt/dynamisch unklar); tests/test_server.py:4299 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4422 (direkt/dynamisch unklar); tests/test_server.py:4423 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4437 (direkt/dynamisch unklar); tests/test_server.py:4438 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4448 (direkt/dynamisch unklar); tests/test_server.py:4449 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4463 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4463 (direkt/dynamisch unklar); tests/test_server.py:4467 (direkt/dynamisch unklar); tests/test_server.py:4469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4477 (direkt/dynamisch unklar); tests/test_server.py:4482 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4501 (direkt/dynamisch unklar); tests/test_server.py:4502 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4652 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4652 (direkt/dynamisch unklar); tests/test_server.py:4676 (direkt/dynamisch unklar); tests/test_server.py:4677 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4700 (direkt/dynamisch unklar); tests/test_server.py:4701 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4707 (direkt/dynamisch unklar); tests/test_server.py:4708 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5899 (direkt/dynamisch unklar); tests/test_server.py:59 (direkt/dynamisch unklar); tests/test_server.py:5901 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5913 (direkt/dynamisch unklar); tests/test_server.py:5914 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5928 (direkt/dynamisch unklar); tests/test_server.py:5930 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5940 (direkt/dynamisch unklar); tests/test_server.py:5943 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5953 (direkt/dynamisch unklar); tests/test_server.py:5961 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5973 (direkt/dynamisch unklar); tests/test_server.py:5974 (Monkeypatch/getattr/sys.modules); tests/test_server.py:60 (direkt/dynamisch unklar); tests/test_server.py:6001 (direkt/dynamisch unklar); tests/test_server.py:6002 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6041 (direkt/dynamisch unklar); tests/test_server.py:6042 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6063 (direkt/dynamisch unklar); tests/test_server.py:6064 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6085 (direkt/dynamisch unklar); tests/test_server.py:6086 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6104 (direkt/dynamisch unklar); tests/test_server.py:6105 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6124 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6124 (direkt/dynamisch unklar); tests/test_server.py:6178 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6178 (direkt/dynamisch unklar); tests/test_server.py:6187 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6187 (direkt/dynamisch unklar); tests/test_server.py:6206 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6206 (direkt/dynamisch unklar); tests/test_server.py:6215 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6215 (direkt/dynamisch unklar); tests/test_server.py:6224 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6224 (direkt/dynamisch unklar); tests/test_server.py:6232 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6232 (direkt/dynamisch unklar); tests/test_server.py:6249 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6249 (direkt/dynamisch unklar); tests/test_server.py:6293 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6293 (direkt/dynamisch unklar); tests/test_server.py:630 (direkt/dynamisch unklar); tests/test_server.py:631 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6325 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6325 (direkt/dynamisch unklar); tests/test_server.py:6371 (direkt/dynamisch unklar); tests/test_server.py:6396 (direkt/dynamisch unklar); tests/test_server.py:6404 (direkt/dynamisch unklar); tests/test_server.py:6405 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6416 (direkt/dynamisch unklar); tests/test_server.py:6418 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6463 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6463 (direkt/dynamisch unklar); tests/test_server.py:647 (direkt/dynamisch unklar); tests/test_server.py:6483 (direkt/dynamisch unklar); tests/test_server.py:6484 (Monkeypatch/getattr/sys.modules); tests/test_server.py:650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:658 (direkt/dynamisch unklar); tests/test_server.py:659 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6661 (direkt/dynamisch unklar); tests/test_server.py:6693 (direkt/dynamisch unklar); tests/test_server.py:671 (direkt/dynamisch unklar); tests/test_server.py:672 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6731 (direkt/dynamisch unklar); tests/test_server.py:6763 (direkt/dynamisch unklar); tests/test_server.py:6779 (direkt/dynamisch unklar); tests/test_server.py:6818 (direkt/dynamisch unklar); tests/test_server.py:6851 (direkt/dynamisch unklar); tests/test_server.py:6878 (direkt/dynamisch unklar); tests/test_server.py:7161 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7161 (direkt/dynamisch unklar); tests/test_server.py:7628 (direkt/dynamisch unklar); tests/test_server.py:7632 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7653 (direkt/dynamisch unklar); tests/test_server.py:7654 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7678 (direkt/dynamisch unklar); tests/test_server.py:7682 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7782 (direkt/dynamisch unklar); tests/test_server.py:7783 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7792 (direkt/dynamisch unklar); tests/test_server.py:7793 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7863 (direkt/dynamisch unklar); tests/test_server.py:7865 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8027 (direkt/dynamisch unklar); tests/test_server.py:8028 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8292 (direkt/dynamisch unklar); tests/test_server.py:8293 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8362 (direkt/dynamisch unklar); tests/test_server.py:8363 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8457 (direkt/dynamisch unklar); tests/test_server.py:8464 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8475 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8531 (direkt/dynamisch unklar); tests/test_server.py:8532 (Monkeypatch/getattr/sys.modules); tests/test_server.py:96 (direkt/dynamisch unklar) |
| Klasse | `IntervalsClient` | 375 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:44 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:55 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:71 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:81 (direkt/dynamisch unklar); tests/test_server.py:3488 (direkt/dynamisch unklar); tests/test_server.py:3561 (direkt/dynamisch unklar); tests/test_server.py:3581 (direkt/dynamisch unklar); tests/test_server.py:3592 (direkt/dynamisch unklar); tests/test_server.py:3611 (direkt/dynamisch unklar); tests/test_server.py:3683 (direkt/dynamisch unklar); tests/test_server.py:3711 (direkt/dynamisch unklar); tests/test_server.py:3742 (direkt/dynamisch unklar); tests/test_server.py:3743 (direkt/dynamisch unklar); tests/test_server.py:3744 (direkt/dynamisch unklar); tests/test_server.py:3762 (direkt/dynamisch unklar); tests/test_server.py:3806 (direkt/dynamisch unklar); tests/test_server.py:3807 (direkt/dynamisch unklar); tests/test_server.py:3815 (direkt/dynamisch unklar); tests/test_server.py:4128 (direkt/dynamisch unklar); tests/test_server.py:4136 (direkt/dynamisch unklar); tests/test_server.py:5902 (direkt/dynamisch unklar); tests/test_server.py:5915 (direkt/dynamisch unklar); tests/test_server.py:5931 (direkt/dynamisch unklar); tests/test_server.py:5944 (direkt/dynamisch unklar); tests/test_server.py:5962 (direkt/dynamisch unklar); tests/test_server.py:6003 (direkt/dynamisch unklar); tests/test_server.py:6004 (direkt/dynamisch unklar); tests/test_server.py:6043 (direkt/dynamisch unklar); tests/test_server.py:6065 (direkt/dynamisch unklar); tests/test_server.py:6087 (direkt/dynamisch unklar); tests/test_server.py:6088 (direkt/dynamisch unklar); tests/test_server.py:6106 (direkt/dynamisch unklar); tests/test_server.py:6307 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6370 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6395 (Monkeypatch/getattr/sys.modules); tests/test_server.py:660 (direkt/dynamisch unklar); tests/test_server.py:6660 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6692 (Monkeypatch/getattr/sys.modules); tests/test_server.py:673 (direkt/dynamisch unklar); tests/test_server.py:6730 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6762 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6778 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6817 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6850 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6877 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7160 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7550 (direkt/dynamisch unklar); tests/test_server.py:7866 (direkt/dynamisch unklar); tests/test_server.py:7867 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 678 | `observability.py` | P1 | offen | tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:23 (direkt/dynamisch unklar); tests/test_provider_review.py:31 (direkt/dynamisch unklar); tests/test_provider_review.py:40 (direkt/dynamisch unklar); tests/test_provider_review.py:42 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_server.py:7373 (direkt/dynamisch unklar); tests/test_server.py:7616 (direkt/dynamisch unklar); tests/test_server.py:7617 (direkt/dynamisch unklar); tests/test_server.py:7618 (direkt/dynamisch unklar); tests/test_server.py:7681 (direkt/dynamisch unklar); tests/test_server.py:7703 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7755 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7869 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:7900 (direkt/dynamisch unklar); tests/test_server.py:8091 (direkt/dynamisch unklar); tests/test_server.py:8117 (direkt/dynamisch unklar); tests/test_server.py:8128 (direkt/dynamisch unklar); tests/test_server.py:8378 (direkt/dynamisch unklar); tests/test_server.py:8385 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTOR` | 679 | `observability.py` | P1 | offen | tests/test_server.py:4464 (direkt/dynamisch unklar); tests/test_server.py:7616 (direkt/dynamisch unklar); tests/test_server.py:7643 (direkt/dynamisch unklar); tests/test_server.py:7681 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:8091 (direkt/dynamisch unklar); tests/test_server.py:8378 (direkt/dynamisch unklar) |
| Funktion | `external_call` | 682 | `providers/http.py` | P2 | offen | tests/test_server.py:1782 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7656 (direkt/dynamisch unklar); tests/test_server.py:7732 (direkt/dynamisch unklar); tests/test_server.py:7747 (direkt/dynamisch unklar); tests/test_server.py:8379 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 745 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 764 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 765 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 766 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 767 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 768 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 769 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 770 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 771 | `weather/` | P3 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_server.py:1231 (direkt/dynamisch unklar); tests/test_server.py:1233 (direkt/dynamisch unklar); tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:1260 (direkt/dynamisch unklar); tests/test_server.py:1437 (direkt/dynamisch unklar); tests/test_server.py:1575 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 772 | `weather/` | P3 | offen | tests/test_audit_remediation.py:122 (direkt/dynamisch unklar); tests/test_audit_remediation.py:85 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 773 | `history/` | P5 | offen | tests/test_server.py:4070 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 774 | `weather/` | P3 | offen | tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:1306 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 775 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 776 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 777 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 778 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 779 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 809 | `weather/` | P3 | offen | tests/test_server.py:7306 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 841 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `serialise_conversation` | 874 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8267 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 891 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:186 (direkt/dynamisch unklar); tests/test_audit_remediation.py:201 (direkt/dynamisch unklar); tests/test_audit_remediation.py:69 (direkt/dynamisch unklar); tests/test_audit_remediation.py:81 (direkt/dynamisch unklar); tests/test_audit_remediation.py:95 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1055 (direkt/dynamisch unklar); tests/test_server.py:1206 (direkt/dynamisch unklar); tests/test_server.py:1209 (direkt/dynamisch unklar); tests/test_server.py:1277 (direkt/dynamisch unklar); tests/test_server.py:1296 (direkt/dynamisch unklar); tests/test_server.py:1443 (direkt/dynamisch unklar); tests/test_server.py:1447 (direkt/dynamisch unklar); tests/test_server.py:1563 (direkt/dynamisch unklar); tests/test_server.py:1692 (direkt/dynamisch unklar); tests/test_server.py:2444 (direkt/dynamisch unklar); tests/test_server.py:2458 (direkt/dynamisch unklar); tests/test_server.py:2471 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2545 (direkt/dynamisch unklar); tests/test_server.py:2674 (direkt/dynamisch unklar); tests/test_server.py:2970 (direkt/dynamisch unklar); tests/test_server.py:2974 (direkt/dynamisch unklar); tests/test_server.py:4893 (direkt/dynamisch unklar); tests/test_server.py:4916 (direkt/dynamisch unklar); tests/test_server.py:4939 (direkt/dynamisch unklar); tests/test_server.py:4961 (direkt/dynamisch unklar); tests/test_server.py:4982 (direkt/dynamisch unklar); tests/test_server.py:5006 (direkt/dynamisch unklar); tests/test_server.py:5457 (direkt/dynamisch unklar); tests/test_server.py:5481 (direkt/dynamisch unklar); tests/test_server.py:5736 (direkt/dynamisch unklar); tests/test_server.py:5755 (direkt/dynamisch unklar); tests/test_server.py:7571 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 895 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 896 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 897 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 898 | `planning/` | P4 | offen | tests/test_server.py:4892 (direkt/dynamisch unklar); tests/test_server.py:4915 (direkt/dynamisch unklar); tests/test_server.py:4938 (direkt/dynamisch unklar); tests/test_server.py:4960 (direkt/dynamisch unklar); tests/test_server.py:4974 (direkt/dynamisch unklar); tests/test_server.py:4981 (direkt/dynamisch unklar); tests/test_server.py:4997 (direkt/dynamisch unklar); tests/test_server.py:5005 (direkt/dynamisch unklar); tests/test_server.py:5457 (direkt/dynamisch unklar); tests/test_server.py:5480 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 899 | `planning/` | P4 | offen | tests/test_server.py:7571 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 900 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4412 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 901 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 902 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 903 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CONTEXT` | 906 | `observability.py` | P1 | offen | tests/test_server.py:7850 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 907 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:335 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:184 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 908 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:336 (direkt/dynamisch unklar); tests/test_provider_review.py:49 (direkt/dynamisch unklar); tests/test_server.py:185 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 910 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 911 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 912 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 913 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 914 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 915 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 916 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 917 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 918 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 919 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 920 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 923 | `history/` | P5 | offen | tests/test_server.py:5426 (direkt/dynamisch unklar); tests/test_server.py:5437 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 924 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 925 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 926 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 927 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 932 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 937 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 942 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 946 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 948 | `planning/` | P4 | offen | tests/test_server.py:408 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 949 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 950 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 953 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 964 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 970 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 979 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 989 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1016 | `observability.py` | P1 | offen | tests/test_server.py:7847 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1037 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1080 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:297 (direkt/dynamisch unklar); tests/test_provider_review.py:187 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:197 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_provider_review.py:334 (direkt/dynamisch unklar); tests/test_server.py:182 (direkt/dynamisch unklar) |
| Funktion | `database` | 1107 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:150 (direkt/dynamisch unklar); tests/test_audit_remediation.py:156 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:199 (direkt/dynamisch unklar); tests/test_audit_remediation.py:32 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:73 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1056 (direkt/dynamisch unklar); tests/test_server.py:1077 (direkt/dynamisch unklar); tests/test_server.py:1086 (direkt/dynamisch unklar); tests/test_server.py:1100 (direkt/dynamisch unklar); tests/test_server.py:1112 (direkt/dynamisch unklar); tests/test_server.py:1126 (direkt/dynamisch unklar); tests/test_server.py:1135 (direkt/dynamisch unklar); tests/test_server.py:1144 (direkt/dynamisch unklar); tests/test_server.py:1151 (direkt/dynamisch unklar); tests/test_server.py:1162 (direkt/dynamisch unklar); tests/test_server.py:1173 (direkt/dynamisch unklar); tests/test_server.py:128 (direkt/dynamisch unklar); tests/test_server.py:1330 (direkt/dynamisch unklar); tests/test_server.py:1335 (direkt/dynamisch unklar); tests/test_server.py:1338 (direkt/dynamisch unklar); tests/test_server.py:1356 (direkt/dynamisch unklar); tests/test_server.py:1359 (direkt/dynamisch unklar); tests/test_server.py:1363 (direkt/dynamisch unklar); tests/test_server.py:1440 (direkt/dynamisch unklar); tests/test_server.py:1552 (direkt/dynamisch unklar); tests/test_server.py:159 (direkt/dynamisch unklar); tests/test_server.py:1689 (direkt/dynamisch unklar); tests/test_server.py:2441 (direkt/dynamisch unklar); tests/test_server.py:2455 (direkt/dynamisch unklar); tests/test_server.py:2468 (direkt/dynamisch unklar); tests/test_server.py:2525 (direkt/dynamisch unklar); tests/test_server.py:2542 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2684 (direkt/dynamisch unklar); tests/test_server.py:2689 (direkt/dynamisch unklar); tests/test_server.py:2708 (direkt/dynamisch unklar); tests/test_server.py:2887 (direkt/dynamisch unklar); tests/test_server.py:2967 (direkt/dynamisch unklar); tests/test_server.py:3255 (direkt/dynamisch unklar); tests/test_server.py:4411 (direkt/dynamisch unklar); tests/test_server.py:4490 (direkt/dynamisch unklar); tests/test_server.py:4759 (direkt/dynamisch unklar); tests/test_server.py:4891 (direkt/dynamisch unklar); tests/test_server.py:4914 (direkt/dynamisch unklar); tests/test_server.py:4937 (direkt/dynamisch unklar); tests/test_server.py:4959 (direkt/dynamisch unklar); tests/test_server.py:4973 (direkt/dynamisch unklar); tests/test_server.py:4979 (direkt/dynamisch unklar); tests/test_server.py:4996 (direkt/dynamisch unklar); tests/test_server.py:5004 (direkt/dynamisch unklar); tests/test_server.py:5326 (direkt/dynamisch unklar); tests/test_server.py:5368 (direkt/dynamisch unklar); tests/test_server.py:5456 (direkt/dynamisch unklar); tests/test_server.py:5479 (direkt/dynamisch unklar); tests/test_server.py:5721 (direkt/dynamisch unklar); tests/test_server.py:5733 (direkt/dynamisch unklar); tests/test_server.py:5752 (direkt/dynamisch unklar); tests/test_server.py:5826 (direkt/dynamisch unklar); tests/test_server.py:5848 (direkt/dynamisch unklar); tests/test_server.py:5857 (direkt/dynamisch unklar); tests/test_server.py:5982 (direkt/dynamisch unklar); tests/test_server.py:6274 (direkt/dynamisch unklar); tests/test_server.py:6337 (direkt/dynamisch unklar); tests/test_server.py:6382 (direkt/dynamisch unklar); tests/test_server.py:640 (direkt/dynamisch unklar); tests/test_server.py:6421 (direkt/dynamisch unklar); tests/test_server.py:6430 (direkt/dynamisch unklar); tests/test_server.py:6606 (direkt/dynamisch unklar); tests/test_server.py:6615 (direkt/dynamisch unklar); tests/test_server.py:6625 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:684 (direkt/dynamisch unklar); tests/test_server.py:695 (direkt/dynamisch unklar); tests/test_server.py:709 (direkt/dynamisch unklar); tests/test_server.py:7570 (direkt/dynamisch unklar); tests/test_server.py:7809 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8217 (direkt/dynamisch unklar); tests/test_server.py:8351 (direkt/dynamisch unklar); tests/test_server.py:8487 (direkt/dynamisch unklar); tests/test_server.py:8501 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1113 | `db/bootstrap.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:288 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:37 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:115 (direkt/dynamisch unklar); tests/test_server.py:1215 (direkt/dynamisch unklar); tests/test_server.py:158 (direkt/dynamisch unklar); tests/test_server.py:181 (direkt/dynamisch unklar); tests/test_server.py:201 (direkt/dynamisch unklar); tests/test_server.py:209 (direkt/dynamisch unklar); tests/test_server.py:218 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2688 (direkt/dynamisch unklar); tests/test_server.py:2697 (direkt/dynamisch unklar); tests/test_server.py:2707 (direkt/dynamisch unklar); tests/test_server.py:3248 (direkt/dynamisch unklar); tests/test_server.py:6419 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1125 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1133 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8469 (direkt/dynamisch unklar); tests/test_server.py:8485 (direkt/dynamisch unklar); tests/test_server.py:8499 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1145 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8470 (direkt/dynamisch unklar); tests/test_server.py:8486 (direkt/dynamisch unklar); tests/test_server.py:8500 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1179 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1194 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1208 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1217 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1231 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1244 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1254 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1263 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1273 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1280 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1305 | `sync/` | P6 | offen | tests/test_audit_remediation.py:294 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:253 (direkt/dynamisch unklar); tests/test_server.py:255 (direkt/dynamisch unklar); tests/test_server.py:259 (direkt/dynamisch unklar); tests/test_server.py:270 (direkt/dynamisch unklar); tests/test_server.py:303 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1314 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:142 (direkt/dynamisch unklar); tests/test_provider_review.py:179 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1320 | `sync/` | P6 | offen | tests/test_server.py:1020 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1029 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1325 | `sync/` | P6 | offen | tests/test_server.py:651 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1348 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1356 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1365 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1383 | `sync/` | P6 | offen | tests/test_server.py:663 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1410 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1419 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1426 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1436 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 1461 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 1475 | `sync/` | P6 | offen | tests/test_audit_remediation.py:256 (direkt/dynamisch unklar); tests/test_audit_remediation.py:289 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:1031 (Monkeypatch/getattr/sys.modules); tests/test_server.py:248 (direkt/dynamisch unklar); tests/test_server.py:265 (direkt/dynamisch unklar); tests/test_server.py:292 (direkt/dynamisch unklar); tests/test_server.py:389 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4732 (direkt/dynamisch unklar); tests/test_server.py:4736 (direkt/dynamisch unklar); tests/test_server.py:476 (Monkeypatch/getattr/sys.modules); tests/test_server.py:572 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6181 (direkt/dynamisch unklar); tests/test_server.py:6190 (direkt/dynamisch unklar); tests/test_server.py:6209 (direkt/dynamisch unklar); tests/test_server.py:6218 (direkt/dynamisch unklar); tests/test_server.py:632 (direkt/dynamisch unklar); tests/test_server.py:635 (direkt/dynamisch unklar); tests/test_server.py:650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8479 (direkt/dynamisch unklar); tests/test_server.py:912 (Monkeypatch/getattr/sys.modules); tests/test_server.py:938 (Monkeypatch/getattr/sys.modules); tests/test_server.py:983 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 1502 | `sync/` | P6 | offen | tests/test_server.py:206 (Monkeypatch/getattr/sys.modules); tests/test_server.py:236 (Monkeypatch/getattr/sys.modules); tests/test_server.py:254 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 1522 | `sync/` | P6 | offen | tests/test_audit_remediation.py:290 (direkt/dynamisch unklar); tests/test_audit_remediation.py:295 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:154 (direkt/dynamisch unklar); tests/test_server.py:251 (direkt/dynamisch unklar); tests/test_server.py:256 (direkt/dynamisch unklar); tests/test_server.py:266 (direkt/dynamisch unklar); tests/test_server.py:299 (direkt/dynamisch unklar); tests/test_server.py:6182 (direkt/dynamisch unklar); tests/test_server.py:6191 (direkt/dynamisch unklar); tests/test_server.py:6210 (direkt/dynamisch unklar); tests/test_server.py:6219 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 1543 | `sync/` | P6 | offen | tests/test_audit_remediation.py:257 (direkt/dynamisch unklar); tests/test_audit_remediation.py:292 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 1581 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 1587 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 1598 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 1618 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 1633 | `sync/jobs.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 1650 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 1663 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 1672 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 1679 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 1696 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 1708 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 1720 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:138 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:167 (Monkeypatch/getattr/sys.modules); tests/test_server.py:257 (Monkeypatch/getattr/sys.modules); tests/test_server.py:268 (Monkeypatch/getattr/sys.modules); tests/test_server.py:281 (direkt/dynamisch unklar); tests/test_server.py:301 (Monkeypatch/getattr/sys.modules); tests/test_server.py:598 (direkt/dynamisch unklar); tests/test_server.py:599 (direkt/dynamisch unklar); tests/test_server.py:611 (direkt/dynamisch unklar); tests/test_server.py:624 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 1743 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 1752 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 1772 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 1792 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 1810 | `sync/` | P6 | offen | tests/test_provider_review.py:139 (direkt/dynamisch unklar); tests/test_provider_review.py:168 (direkt/dynamisch unklar); tests/test_server.py:258 (direkt/dynamisch unklar); tests/test_server.py:269 (direkt/dynamisch unklar); tests/test_server.py:302 (direkt/dynamisch unklar); tests/test_server.py:6182 (direkt/dynamisch unklar); tests/test_server.py:6191 (direkt/dynamisch unklar); tests/test_server.py:6210 (direkt/dynamisch unklar); tests/test_server.py:6219 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 1820 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 1835 | `sync/` | P6 | offen | tests/test_server.py:241 (direkt/dynamisch unklar) |
| Funktion | `resolve_sync_job` | 1846 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_current_provider_freshness` | 1869 | `sync/freshness.py` | P6 | offen | tests/test_server.py:5979 (direkt/dynamisch unklar); tests/test_server.py:8466 (direkt/dynamisch unklar); tests/test_server.py:8471 (direkt/dynamisch unklar); tests/test_server.py:8476 (direkt/dynamisch unklar); tests/test_server.py:8483 (direkt/dynamisch unklar); tests/test_server.py:8493 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 1883 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 1897 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 1908 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 1932 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 1937 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 1949 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 1959 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 1976 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2015 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2047 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3015 (direkt/dynamisch unklar); tests/test_server.py:5409 (direkt/dynamisch unklar); tests/test_server.py:5498 (direkt/dynamisch unklar); tests/test_server.py:5547 (direkt/dynamisch unklar); tests/test_server.py:8420 (direkt/dynamisch unklar); tests/test_server.py:8440 (direkt/dynamisch unklar); tests/test_server.py:8449 (direkt/dynamisch unklar); tests/test_server.py:8452 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2058 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2070 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2084 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2100 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8429 (direkt/dynamisch unklar); tests/test_server.py:8435 (direkt/dynamisch unklar); tests/test_server.py:8441 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2138 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2158 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2168 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2193 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2214 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2224 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2233 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2259 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2275 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2295 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2304 | `history/` | P5 | offen | tests/test_server.py:3022 (direkt/dynamisch unklar); tests/test_server.py:5416 (direkt/dynamisch unklar); tests/test_server.py:5551 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2319 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:122 (direkt/dynamisch unklar); tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_audit_remediation.py:303 (direkt/dynamisch unklar); tests/test_audit_remediation.py:304 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_audit_remediation.py:85 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar); tests/test_provider_review.py:337 (direkt/dynamisch unklar); tests/test_server.py:1233 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1260 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:1306 (direkt/dynamisch unklar); tests/test_server.py:202 (direkt/dynamisch unklar); tests/test_server.py:203 (direkt/dynamisch unklar); tests/test_server.py:2698 (direkt/dynamisch unklar); tests/test_server.py:2699 (direkt/dynamisch unklar); tests/test_server.py:4021 (direkt/dynamisch unklar); tests/test_server.py:4022 (direkt/dynamisch unklar); tests/test_server.py:4305 (direkt/dynamisch unklar); tests/test_server.py:4428 (direkt/dynamisch unklar); tests/test_server.py:5936 (direkt/dynamisch unklar); tests/test_server.py:5948 (direkt/dynamisch unklar); tests/test_server.py:5949 (direkt/dynamisch unklar); tests/test_server.py:6052 (direkt/dynamisch unklar); tests/test_server.py:6071 (direkt/dynamisch unklar); tests/test_server.py:6075 (direkt/dynamisch unklar); tests/test_server.py:6410 (direkt/dynamisch unklar); tests/test_server.py:6429 (direkt/dynamisch unklar); tests/test_server.py:6487 (direkt/dynamisch unklar); tests/test_server.py:7582 (direkt/dynamisch unklar); tests/test_server.py:7600 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 2326 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 2327 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 2328 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 2329 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 2330 | `planning/` | P4 | offen | tests/test_server.py:2564 (direkt/dynamisch unklar); tests/test_server.py:2574 (direkt/dynamisch unklar); tests/test_server.py:2599 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 2331 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 2332 | `planning/` | P4 | offen | tests/test_server.py:2361 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 2333 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 2336 | `planning/` | P4 | offen | tests/test_server.py:3506 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 2337 | `planning/` | P4 | offen | tests/test_server.py:3507 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 2338 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 2339 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 2340 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 2341 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 2342 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 2343 | `coach/` | P7 | offen | tests/test_server.py:5187 (direkt/dynamisch unklar); tests/test_server.py:5198 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 2344 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 2357 | `sync/` | P6 | offen | tests/test_server.py:5873 (direkt/dynamisch unklar); tests/test_server.py:5875 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 2368 | `sync/` | P6 | offen | tests/test_server.py:5872 (direkt/dynamisch unklar); tests/test_server.py:5874 (direkt/dynamisch unklar); tests/test_server.py:5900 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 2380 | `sync/` | P6 | offen | tests/test_server.py:5876 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 2391 | `settings.py` | P1 | offen | tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:223 (direkt/dynamisch unklar); tests/test_provider_review.py:247 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 2396 | `settings.py` | P1 | offen | tests/test_provider_review.py:210 (direkt/dynamisch unklar); tests/test_provider_review.py:211 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 2402 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_server.py:1231 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:1436 (direkt/dynamisch unklar); tests/test_server.py:1437 (direkt/dynamisch unklar); tests/test_server.py:1438 (direkt/dynamisch unklar); tests/test_server.py:1439 (direkt/dynamisch unklar); tests/test_server.py:1531 (direkt/dynamisch unklar); tests/test_server.py:1543 (direkt/dynamisch unklar); tests/test_server.py:1575 (direkt/dynamisch unklar); tests/test_server.py:1683 (direkt/dynamisch unklar); tests/test_server.py:1898 (direkt/dynamisch unklar); tests/test_server.py:1899 (direkt/dynamisch unklar); tests/test_server.py:1900 (direkt/dynamisch unklar); tests/test_server.py:1901 (direkt/dynamisch unklar); tests/test_server.py:1902 (direkt/dynamisch unklar); tests/test_server.py:199 (direkt/dynamisch unklar); tests/test_server.py:200 (direkt/dynamisch unklar); tests/test_server.py:2694 (direkt/dynamisch unklar); tests/test_server.py:2695 (direkt/dynamisch unklar); tests/test_server.py:3119 (direkt/dynamisch unklar); tests/test_server.py:3143 (direkt/dynamisch unklar); tests/test_server.py:3154 (direkt/dynamisch unklar); tests/test_server.py:3202 (direkt/dynamisch unklar); tests/test_server.py:3309 (direkt/dynamisch unklar); tests/test_server.py:3341 (direkt/dynamisch unklar); tests/test_server.py:3360 (direkt/dynamisch unklar); tests/test_server.py:3401 (direkt/dynamisch unklar); tests/test_server.py:3421 (direkt/dynamisch unklar); tests/test_server.py:4071 (direkt/dynamisch unklar); tests/test_server.py:4077 (direkt/dynamisch unklar); tests/test_server.py:4361 (direkt/dynamisch unklar); tests/test_server.py:4385 (direkt/dynamisch unklar); tests/test_server.py:4398 (direkt/dynamisch unklar); tests/test_server.py:4478 (direkt/dynamisch unklar); tests/test_server.py:4500 (direkt/dynamisch unklar); tests/test_server.py:5254 (direkt/dynamisch unklar); tests/test_server.py:5290 (direkt/dynamisch unklar); tests/test_server.py:5785 (direkt/dynamisch unklar); tests/test_server.py:5941 (direkt/dynamisch unklar); tests/test_server.py:6403 (direkt/dynamisch unklar); tests/test_server.py:6420 (direkt/dynamisch unklar); tests/test_server.py:6478 (direkt/dynamisch unklar); tests/test_server.py:6479 (direkt/dynamisch unklar); tests/test_server.py:7561 (direkt/dynamisch unklar); tests/test_server.py:7562 (direkt/dynamisch unklar); tests/test_server.py:7579 (direkt/dynamisch unklar); tests/test_server.py:7594 (direkt/dynamisch unklar); tests/test_server.py:7668 (direkt/dynamisch unklar); tests/test_server.py:7784 (direkt/dynamisch unklar); tests/test_server.py:7794 (direkt/dynamisch unklar); tests/test_server.py:8291 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS` | 2410 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:382 (direkt/dynamisch unklar); tests/test_server.py:4450 (direkt/dynamisch unklar); tests/test_server.py:4451 (direkt/dynamisch unklar); tests/test_server.py:4452 (direkt/dynamisch unklar); tests/test_server.py:4456 (direkt/dynamisch unklar); tests/test_server.py:4457 (direkt/dynamisch unklar); tests/test_server.py:4458 (direkt/dynamisch unklar); tests/test_server.py:4459 (direkt/dynamisch unklar); tests/test_server.py:5266 (direkt/dynamisch unklar); tests/test_server.py:5267 (direkt/dynamisch unklar); tests/test_server.py:5268 (direkt/dynamisch unklar); tests/test_server.py:5270 (direkt/dynamisch unklar); tests/test_server.py:5273 (direkt/dynamisch unklar); tests/test_server.py:5274 (direkt/dynamisch unklar); tests/test_server.py:5275 (direkt/dynamisch unklar); tests/test_server.py:5277 (direkt/dynamisch unklar); tests/test_server.py:5280 (direkt/dynamisch unklar); tests/test_server.py:5282 (direkt/dynamisch unklar); tests/test_server.py:5285 (direkt/dynamisch unklar); tests/test_server.py:5287 (direkt/dynamisch unklar); tests/test_server.py:5289 (direkt/dynamisch unklar); tests/test_server.py:5291 (direkt/dynamisch unklar); tests/test_server.py:5294 (direkt/dynamisch unklar) |
| Globale Bindung | `DIAGNOSTIC_CAPTURE` | 2411 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7724 (direkt/dynamisch unklar); tests/test_server.py:7725 (direkt/dynamisch unklar); tests/test_server.py:7739 (direkt/dynamisch unklar); tests/test_server.py:7745 (direkt/dynamisch unklar); tests/test_server.py:7746 (direkt/dynamisch unklar); tests/test_server.py:8026 (direkt/dynamisch unklar); tests/test_server.py:8032 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 2414 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 2429 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 2446 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:217 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar); tests/test_server.py:5259 (direkt/dynamisch unklar); tests/test_server.py:5261 (direkt/dynamisch unklar); tests/test_server.py:6488 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 2454 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 2458 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4014 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 2466 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 2478 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 2493 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 2503 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 2514 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 2523 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 2538 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 2552 | `activities/` | P3 | offen | tests/test_server.py:3472 (direkt/dynamisch unklar); tests/test_server.py:3480 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 2564 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 2580 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 2595 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7470 (direkt/dynamisch unklar); tests/test_server.py:7481 (direkt/dynamisch unklar); tests/test_server.py:7489 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 2602 | `sync/` | P6 | offen | tests/test_server.py:3285 (direkt/dynamisch unklar); tests/test_server.py:7471 (direkt/dynamisch unklar); tests/test_server.py:7497 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 2609 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 2624 | `activities/` | P3 | offen | tests/test_server.py:7536 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 2647 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 2660 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 2678 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 2696 | `sync/` | P6 | offen | tests/test_server.py:7512 (direkt/dynamisch unklar); tests/test_server.py:7525 (direkt/dynamisch unklar); tests/test_server.py:7537 (direkt/dynamisch unklar); tests/test_server.py:7549 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 2711 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3288 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 2726 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 2739 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 2751 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 2754 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 2758 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 2764 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 2769 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 2778 | `sync/` | P6 | offen | tests/test_server.py:3196 (direkt/dynamisch unklar); tests/test_server.py:3197 (direkt/dynamisch unklar); tests/test_server.py:3198 (direkt/dynamisch unklar); tests/test_server.py:3199 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 2797 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 2810 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 2814 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 2832 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 2846 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 2862 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 2868 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 2876 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 2889 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 2902 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 2909 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 2927 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 2932 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 2958 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 2968 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 2977 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3303 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 2987 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3002 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3011 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3016 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3024 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3038 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3049 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3068 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3079 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3096 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3120 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3129 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3140 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3159 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:292 (direkt/dynamisch unklar); tests/test_provider_review.py:307 (direkt/dynamisch unklar); tests/test_server.py:3171 (direkt/dynamisch unklar); tests/test_server.py:3228 (direkt/dynamisch unklar); tests/test_server.py:3261 (direkt/dynamisch unklar); tests/test_server.py:3288 (direkt/dynamisch unklar); tests/test_server.py:3295 (direkt/dynamisch unklar); tests/test_server.py:3335 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3181 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 3196 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 3201 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 3217 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:302 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 3235 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 3254 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 3283 | `planning/` | P4 | offen | tests/test_server.py:3114 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 3300 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 3308 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 3336 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 3343 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 3367 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 3376 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 3393 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 3409 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 3414 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3971 (direkt/dynamisch unklar); tests/test_server.py:3975 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 3415 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 3418 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3974 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 3426 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3973 (direkt/dynamisch unklar); tests/test_server.py:3978 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 3435 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3972 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 3448 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3977 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 3453 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 3475 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 3485 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 3489 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4026 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 3504 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 3505 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 3508 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 3527 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 3541 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 3552 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4016 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 3563 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 3571 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 3576 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 3580 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 3598 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 3608 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 3612 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4002 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 3632 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 3643 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 3661 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:3981 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 3698 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 3703 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4070 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 3711 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 3724 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 3748 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 3777 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 3801 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4062 (direkt/dynamisch unklar); tests/test_server.py:4063 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 3814 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 3826 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 3856 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 3885 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 3892 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 3951 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 3974 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:242 (direkt/dynamisch unklar); tests/test_server.py:279 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4015 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8365 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4016 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:364 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4023 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4034 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:4069 (direkt/dynamisch unklar); tests/test_server.py:4081 (direkt/dynamisch unklar); tests/test_server.py:7669 (direkt/dynamisch unklar); tests/test_server.py:8366 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4074 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:280 (direkt/dynamisch unklar); tests/test_server.py:3134 (direkt/dynamisch unklar); tests/test_server.py:3148 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4097 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1736 (direkt/dynamisch unklar); tests/test_server.py:1768 (direkt/dynamisch unklar); tests/test_server.py:4382 (direkt/dynamisch unklar); tests/test_server.py:4383 (direkt/dynamisch unklar); tests/test_server.py:4384 (direkt/dynamisch unklar); tests/test_server.py:5077 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4104 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4111 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4114 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4126 | `athlete/` | P3 | offen | tests/test_server.py:1182 (direkt/dynamisch unklar); tests/test_server.py:1645 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4135 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1655 (direkt/dynamisch unklar); tests/test_server.py:6594 (direkt/dynamisch unklar); tests/test_server.py:8433 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4144 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:77 (direkt/dynamisch unklar); tests/test_audit_remediation.py:80 (direkt/dynamisch unklar); tests/test_audit_remediation.py:88 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1214 (direkt/dynamisch unklar); tests/test_server.py:1230 (direkt/dynamisch unklar); tests/test_server.py:1232 (direkt/dynamisch unklar); tests/test_server.py:1236 (direkt/dynamisch unklar); tests/test_server.py:1250 (direkt/dynamisch unklar); tests/test_server.py:1252 (direkt/dynamisch unklar); tests/test_server.py:1256 (direkt/dynamisch unklar); tests/test_server.py:1264 (direkt/dynamisch unklar); tests/test_server.py:1271 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar); tests/test_server.py:1557 (direkt/dynamisch unklar); tests/test_server.py:1574 (direkt/dynamisch unklar); tests/test_server.py:1617 (direkt/dynamisch unklar); tests/test_server.py:1638 (direkt/dynamisch unklar); tests/test_server.py:1640 (direkt/dynamisch unklar); tests/test_server.py:1651 (direkt/dynamisch unklar); tests/test_server.py:6547 (direkt/dynamisch unklar); tests/test_server.py:6575 (direkt/dynamisch unklar); tests/test_server.py:7144 (direkt/dynamisch unklar); tests/test_server.py:7289 (direkt/dynamisch unklar); tests/test_server.py:8418 (direkt/dynamisch unklar); tests/test_server.py:8419 (direkt/dynamisch unklar); tests/test_server.py:8448 (direkt/dynamisch unklar); tests/test_server.py:8465 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4158 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4168 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4175 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4178 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 4190 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 4202 | `athlete/` | P3 | offen | tests/test_server.py:1662 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 4222 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2573 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 4227 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:184 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1625 (direkt/dynamisch unklar); tests/test_server.py:1634 (direkt/dynamisch unklar); tests/test_server.py:1664 (direkt/dynamisch unklar); tests/test_server.py:1668 (direkt/dynamisch unklar); tests/test_server.py:1682 (direkt/dynamisch unklar); tests/test_server.py:1713 (direkt/dynamisch unklar); tests/test_server.py:2562 (direkt/dynamisch unklar); tests/test_server.py:2583 (direkt/dynamisch unklar); tests/test_server.py:2609 (direkt/dynamisch unklar); tests/test_server.py:2628 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 4235 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 4258 | `athlete/` | P3 | offen | tests/test_server.py:1632 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 4268 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 4275 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 4289 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2408 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 4294 | `activities/` | P3 | offen | tests/test_server.py:2405 (direkt/dynamisch unklar); tests/test_server.py:2407 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 4306 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2375 (direkt/dynamisch unklar); tests/test_server.py:2388 (direkt/dynamisch unklar); tests/test_server.py:2398 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 4323 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 4330 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 4344 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 4356 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 4378 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 4390 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 4404 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 4410 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3070 (direkt/dynamisch unklar); tests/test_server.py:3074 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 4420 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3072 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 4427 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 4440 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3056 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 4461 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:46 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_audit_remediation.py:59 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:6297 (direkt/dynamisch unklar); tests/test_server.py:6379 (direkt/dynamisch unklar); tests/test_server.py:6614 (direkt/dynamisch unklar); tests/test_server.py:6668 (direkt/dynamisch unklar); tests/test_server.py:6702 (direkt/dynamisch unklar); tests/test_server.py:6739 (direkt/dynamisch unklar); tests/test_server.py:6786 (direkt/dynamisch unklar); tests/test_server.py:6823 (direkt/dynamisch unklar); tests/test_server.py:6831 (direkt/dynamisch unklar); tests/test_server.py:6858 (direkt/dynamisch unklar); tests/test_server.py:6886 (direkt/dynamisch unklar); tests/test_server.py:691 (direkt/dynamisch unklar); tests/test_server.py:701 (direkt/dynamisch unklar) |
| Funktion | `list_external_calendar_events` | 4466 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2451 (direkt/dynamisch unklar); tests/test_server.py:2460 (direkt/dynamisch unklar); tests/test_server.py:2501 (direkt/dynamisch unklar); tests/test_server.py:2521 (direkt/dynamisch unklar); tests/test_server.py:2534 (direkt/dynamisch unklar); tests/test_server.py:2976 (direkt/dynamisch unklar); tests/test_server.py:2978 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 4477 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2496 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 4492 | `sync/` | P6 | offen | tests/test_server.py:2450 (direkt/dynamisch unklar); tests/test_server.py:2491 (direkt/dynamisch unklar); tests/test_server.py:2517 (direkt/dynamisch unklar); tests/test_server.py:2533 (direkt/dynamisch unklar); tests/test_server.py:7664 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 4549 | `providers/calendar.py` | P2 | offen | tests/test_audit_remediation.py:170 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 4564 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 4568 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 4572 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 4578 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 4584 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 4592 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 4610 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 4627 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 4654 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 4661 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 4675 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 4707 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 4716 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 4727 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 4746 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 4758 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 4764 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 4777 | `performance/` | P3 | offen | tests/test_server.py:4072 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 4789 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 4793 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 4803 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 4812 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 4822 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 4833 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 4842 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 4862 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 4876 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1694 (direkt/dynamisch unklar); tests/test_server.py:2978 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 4900 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 4909 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 4921 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 4934 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 4949 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 4955 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 4966 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 4974 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 4985 | `athlete/` | P3 | offen | tests/test_server.py:1259 (direkt/dynamisch unklar); tests/test_server.py:3466 (direkt/dynamisch unklar); tests/test_server.py:6169 (direkt/dynamisch unklar); tests/test_server.py:6197 (direkt/dynamisch unklar); tests/test_server.py:6241 (direkt/dynamisch unklar); tests/test_server.py:6259 (direkt/dynamisch unklar); tests/test_server.py:6268 (direkt/dynamisch unklar); tests/test_server.py:6332 (direkt/dynamisch unklar); tests/test_server.py:6555 (direkt/dynamisch unklar); tests/test_server.py:6622 (direkt/dynamisch unklar); tests/test_server.py:6672 (direkt/dynamisch unklar); tests/test_server.py:6708 (direkt/dynamisch unklar); tests/test_server.py:6747 (direkt/dynamisch unklar); tests/test_server.py:6830 (direkt/dynamisch unklar); tests/test_server.py:6836 (direkt/dynamisch unklar); tests/test_server.py:6862 (direkt/dynamisch unklar); tests/test_server.py:6881 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 5002 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 5024 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 5036 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 5037 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 5042 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 5052 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 5070 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 5082 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 5095 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 5107 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 5126 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_audit_remediation.py:40 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1118 (direkt/dynamisch unklar); tests/test_server.py:463 (direkt/dynamisch unklar); tests/test_server.py:6253 (direkt/dynamisch unklar); tests/test_server.py:6279 (direkt/dynamisch unklar); tests/test_server.py:6591 (direkt/dynamisch unklar); tests/test_server.py:6596 (direkt/dynamisch unklar); tests/test_server.py:6630 (direkt/dynamisch unklar); tests/test_server.py:6771 (direkt/dynamisch unklar); tests/test_server.py:681 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 5134 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:52 (direkt/dynamisch unklar); tests/test_audit_remediation.py:64 (direkt/dynamisch unklar); tests/test_server.py:6611 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 5164 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 5185 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 5208 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 5223 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 5233 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 5239 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3049 (direkt/dynamisch unklar); tests/test_server.py:3050 (direkt/dynamisch unklar); tests/test_server.py:3051 (direkt/dynamisch unklar); tests/test_server.py:3052 (direkt/dynamisch unklar); tests/test_server.py:3053 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 5244 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 5259 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_server.py:6277 (direkt/dynamisch unklar); tests/test_server.py:6609 (direkt/dynamisch unklar); tests/test_server.py:6624 (direkt/dynamisch unklar); tests/test_server.py:6701 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 5263 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3078 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 5283 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3066 (direkt/dynamisch unklar); tests/test_server.py:3067 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 5299 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 5309 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3104 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 5316 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3105 (direkt/dynamisch unklar); tests/test_server.py:3106 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 5322 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3090 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 5350 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 5356 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 5365 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 5375 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6766 (direkt/dynamisch unklar); tests/test_server.py:6783 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 5415 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 5429 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 5442 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 5468 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 5494 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 5502 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 5510 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 5514 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 5552 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 5560 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 5567 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 5582 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 5594 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 5606 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 5613 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 5617 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 5650 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 5673 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 5692 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 5709 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 5717 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 5747 | `sync/` | P6 | offen | tests/test_audit_remediation.py:45 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:58 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_server.py:6252 (direkt/dynamisch unklar); tests/test_server.py:6260 (direkt/dynamisch unklar); tests/test_server.py:6296 (direkt/dynamisch unklar); tests/test_server.py:6466 (direkt/dynamisch unklar); tests/test_server.py:6663 (direkt/dynamisch unklar); tests/test_server.py:6695 (direkt/dynamisch unklar); tests/test_server.py:6696 (direkt/dynamisch unklar); tests/test_server.py:6733 (direkt/dynamisch unklar); tests/test_server.py:6765 (direkt/dynamisch unklar); tests/test_server.py:6781 (direkt/dynamisch unklar); tests/test_server.py:6784 (direkt/dynamisch unklar); tests/test_server.py:6820 (direkt/dynamisch unklar); tests/test_server.py:6853 (direkt/dynamisch unklar); tests/test_server.py:6880 (direkt/dynamisch unklar); tests/test_server.py:6882 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_STATUS_KEY` | 5803 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `GEMINI_STATUS_KEY` | 5804 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 5805 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `record_openai_status` | 5808 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_success` | 5823 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_persist_openai_rate_limits` | 5833 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_body` | 5839 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 5847 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 5855 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 5867 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 5872 | `coach/context.py` | P7 | offen | tests/test_server.py:7778 (direkt/dynamisch unklar) |
| Funktion | `_urlopen_interruptibly` | 5882 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_http_request_started` | 5909 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_http_response` | 5922 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 5937 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 5978 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 5997 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 6052 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 6087 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 6092 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 6120 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1782 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4230 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4299 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4423 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4438 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4522 (direkt/dynamisch unklar); tests/test_server.py:4565 (direkt/dynamisch unklar); tests/test_server.py:4602 (direkt/dynamisch unklar); tests/test_server.py:4635 (direkt/dynamisch unklar); tests/test_server.py:4677 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5307 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7290 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7684 (direkt/dynamisch unklar); tests/test_server.py:7702 (direkt/dynamisch unklar); tests/test_server.py:7720 (direkt/dynamisch unklar); tests/test_server.py:7754 (direkt/dynamisch unklar); tests/test_server.py:7771 (direkt/dynamisch unklar); tests/test_server.py:7895 (direkt/dynamisch unklar); tests/test_server.py:7931 (direkt/dynamisch unklar); tests/test_server.py:7959 (direkt/dynamisch unklar); tests/test_server.py:7980 (direkt/dynamisch unklar); tests/test_server.py:8293 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 6160 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 6172 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 6181 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 6189 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 6193 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 6199 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 6211 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 6216 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 6242 | `weather/` | P3 | offen | tests/test_server.py:1193 (direkt/dynamisch unklar); tests/test_server.py:1199 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 6252 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 6276 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 6291 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 6310 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 6325 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 6339 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 6360 | `weather/` | P3 | offen | tests/test_server.py:7333 (direkt/dynamisch unklar); tests/test_server.py:7340 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 6407 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 6423 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 6433 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 6454 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 6474 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 6478 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 6501 | `weather/` | P3 | offen | tests/test_audit_remediation.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:82 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1211 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1237 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1265 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1279 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1298 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1565 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1581 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 6513 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 6524 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 6551 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 6559 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 6572 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 6608 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 6627 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 6633 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 6655 | `weather/` | P3 | offen | tests/test_audit_remediation.py:147 (direkt/dynamisch unklar); tests/test_audit_remediation.py:148 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1299 (direkt/dynamisch unklar); tests/test_server.py:1300 (direkt/dynamisch unklar); tests/test_server.py:1301 (direkt/dynamisch unklar); tests/test_server.py:1591 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2842 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7295 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 6673 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 6691 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 6706 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 6713 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 6729 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 6757 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 6770 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 6790 | `sync/` | P6 | offen | tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_server.py:1280 (direkt/dynamisch unklar); tests/test_server.py:1281 (direkt/dynamisch unklar); tests/test_server.py:1282 (direkt/dynamisch unklar); tests/test_server.py:1568 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 6806 | `weather/` | P3 | offen | tests/test_server.py:7307 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 6818 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 6831 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 6836 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 6841 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 6845 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 6849 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 6857 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 6873 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 6892 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 6896 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 6905 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 6917 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 6938 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 6965 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 6980 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 6993 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2789 (direkt/dynamisch unklar); tests/test_server.py:2791 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 7031 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 7052 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 7072 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 7090 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2754 (direkt/dynamisch unklar); tests/test_server.py:2814 (direkt/dynamisch unklar); tests/test_server.py:2853 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 7100 | `providers/` | P2 | offen | tests/test_server.py:2815 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 7124 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 7144 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 7150 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 7173 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 7183 | `planning/` | P4 | offen | tests/test_server.py:2714 (direkt/dynamisch unklar); tests/test_server.py:3431 (direkt/dynamisch unklar); tests/test_server.py:6538 (direkt/dynamisch unklar); tests/test_server.py:6906 (direkt/dynamisch unklar); tests/test_server.py:6935 (direkt/dynamisch unklar); tests/test_server.py:7064 (direkt/dynamisch unklar); tests/test_server.py:7088 (direkt/dynamisch unklar); tests/test_server.py:7109 (direkt/dynamisch unklar); tests/test_server.py:7125 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 7221 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 7222 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 7227 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 7230 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 7239 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 7243 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 7252 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 7277 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 7284 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 7295 | `planning/competitions.py` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3661 (direkt/dynamisch unklar); tests/test_server.py:3678 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 7309 | `planning/competitions.py` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:2943 (direkt/dynamisch unklar); tests/test_server.py:3035 (direkt/dynamisch unklar); tests/test_server.py:3111 (direkt/dynamisch unklar); tests/test_server.py:3697 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 7332 | `planning/competitions.py` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 7345 | `planning/competitions.py` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3623 (direkt/dynamisch unklar); tests/test_server.py:3673 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 7372 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 7382 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 7392 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 7399 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 7417 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 7427 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 7440 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 7453 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 7468 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 7477 | `providers/` | P2 | offen | tests/test_server.py:3446 (direkt/dynamisch unklar); tests/test_server.py:3451 (direkt/dynamisch unklar); tests/test_server.py:3452 (direkt/dynamisch unklar); tests/test_server.py:3462 (direkt/dynamisch unklar); tests/test_server.py:3467 (direkt/dynamisch unklar); tests/test_server.py:4880 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 7492 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 7505 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 7529 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 7540 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 7555 | `planning/competitions.py` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1587 (direkt/dynamisch unklar); tests/test_server.py:1604 (direkt/dynamisch unklar); tests/test_server.py:2464 (direkt/dynamisch unklar); tests/test_server.py:2538 (direkt/dynamisch unklar); tests/test_server.py:2558 (direkt/dynamisch unklar); tests/test_server.py:2605 (direkt/dynamisch unklar); tests/test_server.py:2624 (direkt/dynamisch unklar); tests/test_server.py:2635 (direkt/dynamisch unklar); tests/test_server.py:2667 (direkt/dynamisch unklar); tests/test_server.py:3645 (direkt/dynamisch unklar); tests/test_server.py:3730 (direkt/dynamisch unklar); tests/test_server.py:3758 (direkt/dynamisch unklar); tests/test_server.py:3779 (direkt/dynamisch unklar); tests/test_server.py:3781 (direkt/dynamisch unklar); tests/test_server.py:3788 (direkt/dynamisch unklar); tests/test_server.py:405 (direkt/dynamisch unklar); tests/test_server.py:5391 (direkt/dynamisch unklar); tests/test_server.py:5401 (direkt/dynamisch unklar); tests/test_server.py:5429 (direkt/dynamisch unklar); tests/test_server.py:5674 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6140 (direkt/dynamisch unklar); tests/test_server.py:818 (direkt/dynamisch unklar); tests/test_server.py:851 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 7572 | `planning/competitions.py` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5395 (direkt/dynamisch unklar); tests/test_server.py:5406 (direkt/dynamisch unklar); tests/test_server.py:5422 (direkt/dynamisch unklar); tests/test_server.py:5434 (direkt/dynamisch unklar); tests/test_server.py:5450 (direkt/dynamisch unklar); tests/test_server.py:5473 (direkt/dynamisch unklar); tests/test_server.py:5495 (direkt/dynamisch unklar); tests/test_server.py:845 (direkt/dynamisch unklar); tests/test_server.py:873 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 7580 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 7588 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 7593 | `planning/competitions.py` | P4 | offen | tests/test_server.py:5397 (direkt/dynamisch unklar); tests/test_server.py:5407 (direkt/dynamisch unklar); tests/test_server.py:857 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 7610 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 7615 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 7627 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 7645 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 7674 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_server.py:1618 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 7686 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2579 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 7703 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7572 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 7720 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 7745 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 7759 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 7768 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 7786 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 7800 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 7808 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 7826 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 7835 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 7849 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 7864 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 7881 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 7898 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 7922 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 7954 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 7980 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 8001 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 8009 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 8028 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 8051 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1595 (direkt/dynamisch unklar); tests/test_server.py:1612 (direkt/dynamisch unklar); tests/test_server.py:2473 (direkt/dynamisch unklar); tests/test_server.py:2547 (direkt/dynamisch unklar); tests/test_server.py:2563 (direkt/dynamisch unklar); tests/test_server.py:2577 (direkt/dynamisch unklar); tests/test_server.py:2584 (direkt/dynamisch unklar); tests/test_server.py:2610 (direkt/dynamisch unklar); tests/test_server.py:2629 (direkt/dynamisch unklar); tests/test_server.py:2639 (direkt/dynamisch unklar); tests/test_server.py:2676 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 8082 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 8093 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 8109 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 8124 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 8134 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 8173 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 8188 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 8196 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 8218 | `planning/` | P4 | offen | tests/test_audit_remediation.py:244 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2568 (direkt/dynamisch unklar); tests/test_server.py:2595 (direkt/dynamisch unklar); tests/test_server.py:2614 (direkt/dynamisch unklar); tests/test_server.py:2619 (direkt/dynamisch unklar); tests/test_server.py:2631 (direkt/dynamisch unklar); tests/test_server.py:2640 (direkt/dynamisch unklar); tests/test_server.py:2643 (direkt/dynamisch unklar); tests/test_server.py:2677 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 8248 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 8272 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1619 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 8276 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 8284 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 8300 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 8313 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 8318 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 8323 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 8332 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 8341 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 8363 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 8369 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 8373 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 8386 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 8400 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 8406 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 8419 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 8432 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 8453 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 8469 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 8479 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 8495 | `planning/` | P4 | offen | tests/test_server.py:2655 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 8518 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 8534 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 8537 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 8561 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 8570 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:2862 (direkt/dynamisch unklar); tests/test_server.py:2984 (direkt/dynamisch unklar); tests/test_server.py:3005 (direkt/dynamisch unklar); tests/test_server.py:3458 (direkt/dynamisch unklar); tests/test_server.py:375 (direkt/dynamisch unklar); tests/test_server.py:4743 (direkt/dynamisch unklar); tests/test_server.py:4765 (direkt/dynamisch unklar); tests/test_server.py:4821 (direkt/dynamisch unklar); tests/test_server.py:4838 (direkt/dynamisch unklar); tests/test_server.py:4856 (direkt/dynamisch unklar); tests/test_server.py:4874 (direkt/dynamisch unklar); tests/test_server.py:4895 (direkt/dynamisch unklar); tests/test_server.py:4918 (direkt/dynamisch unklar); tests/test_server.py:4963 (direkt/dynamisch unklar); tests/test_server.py:4985 (direkt/dynamisch unklar); tests/test_server.py:5008 (direkt/dynamisch unklar); tests/test_server.py:5024 (direkt/dynamisch unklar); tests/test_server.py:5041 (direkt/dynamisch unklar); tests/test_server.py:5104 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5175 (direkt/dynamisch unklar); tests/test_server.py:5333 (direkt/dynamisch unklar); tests/test_server.py:5364 (direkt/dynamisch unklar); tests/test_server.py:5527 (direkt/dynamisch unklar); tests/test_server.py:5557 (direkt/dynamisch unklar); tests/test_server.py:5575 (direkt/dynamisch unklar); tests/test_server.py:5580 (direkt/dynamisch unklar); tests/test_server.py:5589 (direkt/dynamisch unklar); tests/test_server.py:5593 (direkt/dynamisch unklar); tests/test_server.py:5598 (direkt/dynamisch unklar); tests/test_server.py:5607 (direkt/dynamisch unklar); tests/test_server.py:5626 (direkt/dynamisch unklar); tests/test_server.py:5629 (direkt/dynamisch unklar); tests/test_server.py:5655 (direkt/dynamisch unklar); tests/test_server.py:705 (direkt/dynamisch unklar); tests/test_server.py:7168 (direkt/dynamisch unklar); tests/test_server.py:728 (direkt/dynamisch unklar); tests/test_server.py:745 (direkt/dynamisch unklar); tests/test_server.py:771 (direkt/dynamisch unklar); tests/test_server.py:775 (direkt/dynamisch unklar); tests/test_server.py:878 (direkt/dynamisch unklar); tests/test_server.py:898 (direkt/dynamisch unklar); tests/test_server.py:902 (direkt/dynamisch unklar); tests/test_server.py:925 (direkt/dynamisch unklar); tests/test_server.py:973 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 8588 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2571 (direkt/dynamisch unklar); tests/test_server.py:2572 (direkt/dynamisch unklar); tests/test_server.py:2580 (direkt/dynamisch unklar); tests/test_server.py:2645 (direkt/dynamisch unklar); tests/test_server.py:2916 (direkt/dynamisch unklar); tests/test_server.py:2926 (direkt/dynamisch unklar); tests/test_server.py:2929 (direkt/dynamisch unklar); tests/test_server.py:2940 (direkt/dynamisch unklar); tests/test_server.py:2956 (direkt/dynamisch unklar); tests/test_server.py:3027 (direkt/dynamisch unklar); tests/test_server.py:3768 (direkt/dynamisch unklar); tests/test_server.py:3772 (direkt/dynamisch unklar); tests/test_server.py:3780 (direkt/dynamisch unklar); tests/test_server.py:3784 (direkt/dynamisch unklar); tests/test_server.py:4756 (direkt/dynamisch unklar); tests/test_server.py:4782 (direkt/dynamisch unklar); tests/test_server.py:4799 (direkt/dynamisch unklar); tests/test_server.py:4833 (direkt/dynamisch unklar); tests/test_server.py:4851 (direkt/dynamisch unklar); tests/test_server.py:4869 (direkt/dynamisch unklar); tests/test_server.py:4908 (direkt/dynamisch unklar); tests/test_server.py:4932 (direkt/dynamisch unklar); tests/test_server.py:4954 (direkt/dynamisch unklar); tests/test_server.py:5021 (direkt/dynamisch unklar); tests/test_server.py:5037 (direkt/dynamisch unklar); tests/test_server.py:5058 (direkt/dynamisch unklar); tests/test_server.py:5358 (direkt/dynamisch unklar); tests/test_server.py:5359 (direkt/dynamisch unklar); tests/test_server.py:5448 (direkt/dynamisch unklar); tests/test_server.py:5522 (direkt/dynamisch unklar); tests/test_server.py:5650 (direkt/dynamisch unklar); tests/test_server.py:5680 (direkt/dynamisch unklar); tests/test_server.py:6050 (direkt/dynamisch unklar); tests/test_server.py:768 (direkt/dynamisch unklar); tests/test_server.py:796 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 8600 | `planning/` | P4 | offen | tests/test_server.py:3528 (direkt/dynamisch unklar); tests/test_server.py:3739 (direkt/dynamisch unklar); tests/test_server.py:3801 (direkt/dynamisch unklar); tests/test_server.py:6079 (direkt/dynamisch unklar); tests/test_server.py:6116 (direkt/dynamisch unklar); tests/test_server.py:6160 (direkt/dynamisch unklar); tests/test_server.py:6319 (direkt/dynamisch unklar); tests/test_server.py:8439 (direkt/dynamisch unklar); tests/test_server.py:8529 (direkt/dynamisch unklar); tests/test_server.py:8530 (direkt/dynamisch unklar); tests/test_server.py:996 (direkt/dynamisch unklar); tests/test_server.py:999 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 8628 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3727 (direkt/dynamisch unklar); tests/test_server.py:538 (direkt/dynamisch unklar); tests/test_server.py:732 (direkt/dynamisch unklar); tests/test_server.py:950 (direkt/dynamisch unklar); tests/test_server.py:970 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 8651 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 8666 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 8683 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 8698 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 8721 | `planning/` | P4 | offen | tests/test_server.py:1431 (direkt/dynamisch unklar); tests/test_server.py:1748 (direkt/dynamisch unklar); tests/test_server.py:3513 (direkt/dynamisch unklar); tests/test_server.py:3519 (direkt/dynamisch unklar); tests/test_server.py:3543 (direkt/dynamisch unklar); tests/test_server.py:4152 (direkt/dynamisch unklar); tests/test_server.py:4168 (direkt/dynamisch unklar); tests/test_server.py:4186 (direkt/dynamisch unklar); tests/test_server.py:4201 (direkt/dynamisch unklar); tests/test_server.py:6133 (direkt/dynamisch unklar); tests/test_server.py:6333 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 8746 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3524 (direkt/dynamisch unklar); tests/test_server.py:3533 (direkt/dynamisch unklar); tests/test_server.py:3535 (direkt/dynamisch unklar); tests/test_server.py:3536 (direkt/dynamisch unklar); tests/test_server.py:3538 (direkt/dynamisch unklar); tests/test_server.py:3540 (direkt/dynamisch unklar); tests/test_server.py:3748 (direkt/dynamisch unklar); tests/test_server.py:3811 (direkt/dynamisch unklar); tests/test_server.py:4156 (direkt/dynamisch unklar); tests/test_server.py:4164 (direkt/dynamisch unklar); tests/test_server.py:4172 (direkt/dynamisch unklar); tests/test_server.py:4182 (direkt/dynamisch unklar); tests/test_server.py:4190 (direkt/dynamisch unklar); tests/test_server.py:4198 (direkt/dynamisch unklar); tests/test_server.py:4205 (direkt/dynamisch unklar); tests/test_server.py:6008 (direkt/dynamisch unklar); tests/test_server.py:6097 (direkt/dynamisch unklar); tests/test_server.py:6150 (direkt/dynamisch unklar); tests/test_server.py:6385 (direkt/dynamisch unklar); tests/test_server.py:8445 (direkt/dynamisch unklar); tests/test_server.py:966 (direkt/dynamisch unklar); tests/test_server.py:967 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 8753 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 8770 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 8771 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 8772 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 8773 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 8776 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 8783 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 8788 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 8798 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 8805 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1727 (direkt/dynamisch unklar); tests/test_server.py:1728 (direkt/dynamisch unklar); tests/test_server.py:1729 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 8832 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:307 (direkt/dynamisch unklar); tests/test_audit_remediation.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1737 (direkt/dynamisch unklar); tests/test_server.py:1738 (direkt/dynamisch unklar); tests/test_server.py:1743 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 8864 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1752 (direkt/dynamisch unklar); tests/test_server.py:1753 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 8892 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1903 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 8913 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 8933 | `activities/` | P3 | offen | tests/test_server.py:534 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 8974 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 8979 | `planning/` | P4 | offen | tests/test_server.py:2554 (direkt/dynamisch unklar); tests/test_server.py:2567 (direkt/dynamisch unklar); tests/test_server.py:2570 (direkt/dynamisch unklar); tests/test_server.py:2618 (direkt/dynamisch unklar); tests/test_server.py:2644 (direkt/dynamisch unklar); tests/test_server.py:2678 (direkt/dynamisch unklar); tests/test_server.py:2681 (direkt/dynamisch unklar); tests/test_server.py:2841 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2891 (direkt/dynamisch unklar); tests/test_server.py:2908 (direkt/dynamisch unklar); tests/test_server.py:3002 (direkt/dynamisch unklar); tests/test_server.py:3647 (direkt/dynamisch unklar); tests/test_server.py:3736 (direkt/dynamisch unklar); tests/test_server.py:3794 (direkt/dynamisch unklar); tests/test_server.py:4165 (direkt/dynamisch unklar); tests/test_server.py:4183 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 8984 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 8991 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 9002 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 9014 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 9039 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 9055 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 9063 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 9077 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 9089 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:2876 (direkt/dynamisch unklar); tests/test_server.py:2891 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 9108 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 9113 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 9130 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 9144 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 9151 | `calendar/` | P3 | offen | tests/test_server.py:2976 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 9166 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 9179 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 9192 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 9249 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 9266 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 9306 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 9313 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 9321 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 9329 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 9342 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 9352 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 9364 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 9393 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 9403 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 9425 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:311 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 9442 | `sync/` | P6 | offen | tests/test_server.py:3767 (direkt/dynamisch unklar); tests/test_server.py:3771 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 9447 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 9465 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 9472 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 9481 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 9496 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 9501 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 9507 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 9515 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 9527 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 9536 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 9553 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 9573 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 9576 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 9589 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 9601 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 9624 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 9644 | `planning/` | P4 | offen | tests/test_server.py:5903 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5932 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5945 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5965 (direkt/dynamisch unklar); tests/test_server.py:6044 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6068 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6109 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6127 (direkt/dynamisch unklar); tests/test_server.py:661 (Monkeypatch/getattr/sys.modules); tests/test_server.py:674 (Monkeypatch/getattr/sys.modules) |
| Funktion | `plan_library_workout_remote` | 9685 | `planning/` | P4 | offen | tests/test_server.py:6308 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 9689 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 9710 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 9725 | `sync/snapshots.py` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 9731 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 9738 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 9753 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 9768 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 9778 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 9784 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 9799 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 9807 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1435 (direkt/dynamisch unklar); tests/test_server.py:3531 (direkt/dynamisch unklar); tests/test_server.py:3534 (direkt/dynamisch unklar); tests/test_server.py:3537 (direkt/dynamisch unklar); tests/test_server.py:3539 (direkt/dynamisch unklar); tests/test_server.py:3545 (direkt/dynamisch unklar); tests/test_server.py:3547 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 9831 | `planning/` | P4 | offen | tests/test_server.py:6323 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 9850 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 9866 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 9878 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 9892 | `calendar/` | P3 | offen | tests/test_server.py:7785 (direkt/dynamisch unklar); tests/test_server.py:7795 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 9927 | `sync/status.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 9957 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 9975 | `sync/` | P6 | offen | tests/test_server.py:1904 (direkt/dynamisch unklar); tests/test_server.py:2149 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 9979 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 9994 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 10013 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 10026 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 10040 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 10059 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 10072 | `sync/` | P6 | offen | tests/test_server.py:3746 (direkt/dynamisch unklar); tests/test_server.py:3752 (direkt/dynamisch unklar); tests/test_server.py:3808 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 10087 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 10095 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 10119 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 10124 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 10147 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 10154 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 10179 | `planning/` | P4 | offen | tests/test_server.py:4158 (direkt/dynamisch unklar); tests/test_server.py:4178 (direkt/dynamisch unklar); tests/test_server.py:4193 (direkt/dynamisch unklar); tests/test_server.py:4207 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 10193 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 10202 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 10213 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 10222 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 10234 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 10247 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 10251 | `sync/` | P6 | offen | tests/test_server.py:6372 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8537 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 10264 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 10277 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 10281 | `sync/` | P6 | offen | tests/test_server.py:312 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 10300 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 10315 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 10330 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 10346 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 10359 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 10376 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 10387 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 10403 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 10421 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 10440 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 10463 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 10478 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 10487 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 10508 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 10526 | `planning/calendar.py` | P3 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 10550 | `planning/` | P4 | offen | tests/test_server.py:2612 (direkt/dynamisch unklar); tests/test_server.py:2630 (direkt/dynamisch unklar); tests/test_server.py:2913 (direkt/dynamisch unklar); tests/test_server.py:2927 (direkt/dynamisch unklar); tests/test_server.py:2957 (direkt/dynamisch unklar); tests/test_server.py:2989 (direkt/dynamisch unklar); tests/test_server.py:2996 (direkt/dynamisch unklar); tests/test_server.py:2998 (direkt/dynamisch unklar); tests/test_server.py:3000 (direkt/dynamisch unklar); tests/test_server.py:3010 (direkt/dynamisch unklar); tests/test_server.py:3012 (direkt/dynamisch unklar); tests/test_server.py:3461 (direkt/dynamisch unklar); tests/test_server.py:3735 (direkt/dynamisch unklar); tests/test_server.py:3783 (direkt/dynamisch unklar); tests/test_server.py:4879 (direkt/dynamisch unklar); tests/test_server.py:5579 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 10576 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 10587 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 10598 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 10608 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 10614 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 10625 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 10637 | `planning/` | P4 | offen | tests/test_server.py:2959 (direkt/dynamisch unklar); tests/test_server.py:2962 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 10655 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:92 (direkt/dynamisch unklar); tests/test_server.py:1695 (direkt/dynamisch unklar); tests/test_server.py:1696 (direkt/dynamisch unklar); tests/test_server.py:2840 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5258 (direkt/dynamisch unklar); tests/test_server.py:5260 (direkt/dynamisch unklar); tests/test_server.py:6377 (direkt/dynamisch unklar); tests/test_server.py:6400 (direkt/dynamisch unklar); tests/test_server.py:7557 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 10660 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:110 (direkt/dynamisch unklar); tests/test_provider_review.py:230 (direkt/dynamisch unklar); tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_provider_review.py:63 (direkt/dynamisch unklar); tests/test_provider_review.py:87 (direkt/dynamisch unklar); tests/test_server.py:1463 (direkt/dynamisch unklar); tests/test_server.py:1675 (direkt/dynamisch unklar); tests/test_server.py:1712 (direkt/dynamisch unklar); tests/test_server.py:1720 (direkt/dynamisch unklar); tests/test_server.py:1760 (direkt/dynamisch unklar); tests/test_server.py:2368 (direkt/dynamisch unklar); tests/test_server.py:2393 (direkt/dynamisch unklar); tests/test_server.py:3487 (direkt/dynamisch unklar); tests/test_server.py:3552 (direkt/dynamisch unklar); tests/test_server.py:4174 (direkt/dynamisch unklar); tests/test_server.py:489 (direkt/dynamisch unklar); tests/test_server.py:5212 (direkt/dynamisch unklar); tests/test_server.py:5253 (direkt/dynamisch unklar); tests/test_server.py:6389 (direkt/dynamisch unklar); tests/test_server.py:7170 (direkt/dynamisch unklar); tests/test_server.py:7548 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 10670 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 10696 | `sync/` | P6 | offen | tests/test_server.py:1048 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 10721 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 10726 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 10736 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 10744 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 10775 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 10797 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 10808 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 10822 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 10844 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 10861 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 10895 | `planning/` | P4 | offen | tests/test_server.py:2904 (direkt/dynamisch unklar); tests/test_server.py:2906 (direkt/dynamisch unklar); tests/test_server.py:2914 (direkt/dynamisch unklar); tests/test_server.py:2925 (direkt/dynamisch unklar); tests/test_server.py:2928 (direkt/dynamisch unklar); tests/test_server.py:2936 (direkt/dynamisch unklar); tests/test_server.py:2955 (direkt/dynamisch unklar); tests/test_server.py:2958 (direkt/dynamisch unklar); tests/test_server.py:2961 (direkt/dynamisch unklar); tests/test_server.py:3445 (direkt/dynamisch unklar); tests/test_server.py:3450 (direkt/dynamisch unklar); tests/test_server.py:5507 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 10943 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 10959 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 10971 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 10983 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 10988 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 10998 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 11005 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 11012 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 11023 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 11038 | `sync/` | P6 | offen | tests/test_server.py:6235 (direkt/dynamisch unklar); tests/test_server.py:6373 (direkt/dynamisch unklar); tests/test_server.py:6399 (direkt/dynamisch unklar); tests/test_server.py:6409 (direkt/dynamisch unklar); tests/test_server.py:6485 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 11073 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 11088 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 11117 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 11146 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 11166 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 11183 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 11240 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 11255 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 11266 | `sync/` | P6 | offen | tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5904 (direkt/dynamisch unklar); tests/test_server.py:5919 (direkt/dynamisch unklar); tests/test_server.py:5934 (direkt/dynamisch unklar); tests/test_server.py:5947 (direkt/dynamisch unklar); tests/test_server.py:5976 (direkt/dynamisch unklar); tests/test_server.py:6005 (direkt/dynamisch unklar); tests/test_server.py:6045 (direkt/dynamisch unklar); tests/test_server.py:6046 (direkt/dynamisch unklar); tests/test_server.py:6070 (direkt/dynamisch unklar); tests/test_server.py:6072 (direkt/dynamisch unklar); tests/test_server.py:6092 (direkt/dynamisch unklar); tests/test_server.py:6110 (direkt/dynamisch unklar); tests/test_server.py:619 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6227 (direkt/dynamisch unklar); tests/test_server.py:6328 (direkt/dynamisch unklar); tests/test_server.py:664 (direkt/dynamisch unklar); tests/test_server.py:677 (direkt/dynamisch unklar); tests/test_server.py:7601 (direkt/dynamisch unklar); tests/test_server.py:7868 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 11300 | `performance/` | P3 | offen | tests/test_provider_review.py:77 (direkt/dynamisch unklar); tests/test_server.py:595 (Monkeypatch/getattr/sys.modules); tests/test_server.py:608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7162 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 11324 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 11331 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 11338 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 11356 | `activities/` | P3 | offen | tests/test_server.py:5126 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 11368 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 11385 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 11398 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 11415 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 11436 | `performance/` | P3 | offen | tests/test_server.py:7059 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 11445 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 11457 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 11473 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 11488 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 11524 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 11534 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 11548 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 11564 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 11581 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 11591 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 11602 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 11616 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 11628 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 11633 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 11665 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 11674 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 11680 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 11687 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 11701 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 11714 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 11718 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 11747 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 11754 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 11791 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 11811 | `performance/` | P3 | offen | tests/test_server.py:3206 (direkt/dynamisch unklar); tests/test_server.py:3215 (direkt/dynamisch unklar); tests/test_server.py:3323 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 11840 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 11854 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 11870 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 11878 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 11888 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 11915 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 11930 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 11953 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 11971 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 12003 | `activities/` | P3 | offen | tests/test_server.py:6958 (direkt/dynamisch unklar); tests/test_server.py:6980 (direkt/dynamisch unklar); tests/test_server.py:6986 (direkt/dynamisch unklar); tests/test_server.py:6995 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 12048 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 12081 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 12102 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 12114 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 12134 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 12147 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 12178 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 12208 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 12219 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 12262 | `performance/` | P3 | offen | tests/test_provider_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:3346 (direkt/dynamisch unklar); tests/test_server.py:3376 (direkt/dynamisch unklar); tests/test_server.py:3405 (direkt/dynamisch unklar); tests/test_server.py:3426 (direkt/dynamisch unklar); tests/test_server.py:3438 (direkt/dynamisch unklar); tests/test_server.py:6897 (direkt/dynamisch unklar); tests/test_server.py:6919 (direkt/dynamisch unklar); tests/test_server.py:6946 (direkt/dynamisch unklar); tests/test_server.py:7015 (direkt/dynamisch unklar); tests/test_server.py:7029 (direkt/dynamisch unklar); tests/test_server.py:7045 (direkt/dynamisch unklar); tests/test_server.py:7076 (direkt/dynamisch unklar); tests/test_server.py:7097 (direkt/dynamisch unklar); tests/test_server.py:7119 (direkt/dynamisch unklar); tests/test_server.py:7139 (direkt/dynamisch unklar); tests/test_server.py:7145 (direkt/dynamisch unklar); tests/test_server.py:7149 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 12333 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 12347 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 12351 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 12355 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 12360 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 12364 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 12368 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 12372 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 12376 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 12395 | `planning/` | P4 | offen | tests/test_server.py:5116 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 12414 | `coach/context.py` | P7 | offen | tests/test_server.py:5108 (direkt/dynamisch unklar); tests/test_server.py:5145 (direkt/dynamisch unklar); tests/test_server.py:5146 (direkt/dynamisch unklar); tests/test_server.py:5167 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 12460 | `coach/context.py` | P7 | offen | tests/test_server.py:1582 (direkt/dynamisch unklar); tests/test_server.py:1656 (direkt/dynamisch unklar); tests/test_server.py:2382 (direkt/dynamisch unklar); tests/test_server.py:3159 (direkt/dynamisch unklar); tests/test_server.py:5188 (direkt/dynamisch unklar); tests/test_server.py:5194 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6570 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 12525 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 12543 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 12553 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 12570 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:248 (direkt/dynamisch unklar); tests/test_provider_review.py:282 (direkt/dynamisch unklar); tests/test_server.py:3525 (direkt/dynamisch unklar); tests/test_server.py:5184 (direkt/dynamisch unklar); tests/test_server.py:5195 (direkt/dynamisch unklar); tests/test_server.py:5196 (direkt/dynamisch unklar); tests/test_server.py:5213 (direkt/dynamisch unklar); tests/test_server.py:5224 (direkt/dynamisch unklar); tests/test_server.py:5256 (direkt/dynamisch unklar); tests/test_server.py:6548 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 12610 | `coach/context.py` | P7 | offen | tests/test_server.py:5078 (direkt/dynamisch unklar); tests/test_server.py:5218 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 12666 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 12696 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_openai_usage_summary_unlocked` | 12706 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_usage_summary` | 12715 | `providers/` | P2 | offen | tests/test_server.py:7932 (direkt/dynamisch unklar); tests/test_server.py:7962 (direkt/dynamisch unklar); tests/test_server.py:8078 (direkt/dynamisch unklar); tests/test_server.py:8088 (direkt/dynamisch unklar); tests/test_server.py:8112 (direkt/dynamisch unklar); tests/test_server.py:8160 (direkt/dynamisch unklar); tests/test_server.py:8304 (direkt/dynamisch unklar); tests/test_server.py:8342 (direkt/dynamisch unklar) |
| Funktion | `_record_openai_usage_unlocked` | 12723 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_usage` | 12738 | `providers/` | P2 | offen | tests/test_server.py:5698 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8299 (direkt/dynamisch unklar); tests/test_server.py:8340 (direkt/dynamisch unklar) |
| Funktion | `_validate_openai_response` | 12745 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8281 (direkt/dynamisch unklar); tests/test_server.py:8284 (direkt/dynamisch unklar); tests/test_server.py:8287 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 12767 | `providers/` | P2 | offen | tests/test_server.py:4469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4678 (direkt/dynamisch unklar); tests/test_server.py:5301 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5310 (direkt/dynamisch unklar); tests/test_server.py:5903 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7160 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8009 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8294 (direkt/dynamisch unklar) |
| Funktion | `transcribe_audio` | 12793 | `providers/` | P2 | offen | tests/test_server.py:4439 (direkt/dynamisch unklar); tests/test_server.py:4655 (direkt/dynamisch unklar); tests/test_server.py:4710 (direkt/dynamisch unklar); tests/test_server.py:4712 (direkt/dynamisch unklar) |
| Funktion | `_provider_usage_summary` | 12845 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_usage_summary` | 12855 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_status` | 12860 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_usage` | 12866 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_content_has_function_response` | 12878 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 12883 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 12890 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 12901 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 12917 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 12929 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4362 (direkt/dynamisch unklar); tests/test_server.py:4494 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 12937 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 12949 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 12965 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 12981 | `coach/conversation.py` | P7 | offen | tests/test_server.py:4373 (direkt/dynamisch unklar); tests/test_server.py:4378 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 13003 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_request_history` | 13025 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_last_user_text` | 13038 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_call_names` | 13045 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_request_payload` | 13053 | `providers/` | P2 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4390 (direkt/dynamisch unklar); tests/test_server.py:4403 (direkt/dynamisch unklar); tests/test_server.py:4473 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 13086 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 13105 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 13144 | `providers/` | P2 | offen | tests/test_server.py:4231 (direkt/dynamisch unklar); tests/test_server.py:4233 (direkt/dynamisch unklar); tests/test_server.py:4300 (direkt/dynamisch unklar); tests/test_server.py:4303 (direkt/dynamisch unklar); tests/test_server.py:4425 (direkt/dynamisch unklar); tests/test_server.py:4469 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 13151 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `request_ai_provider` | 13245 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 13250 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4470 (direkt/dynamisch unklar); tests/test_server.py:5302 (direkt/dynamisch unklar); tests/test_server.py:5693 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8010 (direkt/dynamisch unklar) |
| Funktion | `retrieve_openai_response` | 13276 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 13291 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 13309 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5699 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 13349 | `coach/context.py` | P7 | offen | tests/test_server.py:5959 (direkt/dynamisch unklar) |
| Funktion | `_read_openai_stream_response` | 13354 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_openai_stream_failure` | 13392 | `observability.py` | P1 | offen | tests/test_server.py:8118 (direkt/dynamisch unklar); tests/test_server.py:8129 (direkt/dynamisch unklar) |
| Funktion | `_capture_openai_stream_failure` | 13411 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 13425 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 13437 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 13448 | `providers/` | P2 | offen | tests/test_server.py:7994 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 13480 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 13496 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 13511 | `providers/` | P2 | offen | tests/test_server.py:4702 (direkt/dynamisch unklar); tests/test_server.py:8030 (direkt/dynamisch unklar); tests/test_server.py:8071 (direkt/dynamisch unklar); tests/test_server.py:8085 (direkt/dynamisch unklar); tests/test_server.py:8109 (direkt/dynamisch unklar); tests/test_server.py:8159 (direkt/dynamisch unklar); tests/test_server.py:8165 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 13590 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4275 (direkt/dynamisch unklar); tests/test_server.py:5799 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8166 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 13619 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 13638 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 13651 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 13669 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 13682 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 13688 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 13696 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:308 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4503 (direkt/dynamisch unklar); tests/test_server.py:5324 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 13705 | `providers/` | P2 | offen | tests/test_server.py:4215 (direkt/dynamisch unklar); tests/test_server.py:4247 (direkt/dynamisch unklar); tests/test_server.py:4281 (direkt/dynamisch unklar); tests/test_server.py:4469 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 13709 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 13710 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 13713 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 13717 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 13730 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 13755 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 13779 | `activities/` | P3 | offen | tests/test_server.py:7551 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 13799 | `coach/context.py` | P7 | offen | tests/test_server.py:8403 (direkt/dynamisch unklar); tests/test_server.py:8414 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 13821 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 13830 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 13852 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8430 (direkt/dynamisch unklar); tests/test_server.py:8442 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 13876 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 13885 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8431 (direkt/dynamisch unklar); tests/test_server.py:8443 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 13914 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 13918 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:278 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5824 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 13935 | `coach/context.py` | P7 | offen | tests/test_server.py:5853 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 13939 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:5844 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 13951 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 13968 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 13995 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 14004 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 14021 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 14073 | `sync/` | P6 | offen | tests/test_audit_remediation.py:269 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4483 (direkt/dynamisch unklar); tests/test_server.py:5710 (direkt/dynamisch unklar); tests/test_server.py:5738 (direkt/dynamisch unklar); tests/test_server.py:5759 (direkt/dynamisch unklar); tests/test_server.py:5786 (direkt/dynamisch unklar); tests/test_server.py:5813 (direkt/dynamisch unklar); tests/test_server.py:5837 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 14106 | `coach/context.py` | P7 | offen | tests/test_server.py:5757 (direkt/dynamisch unklar); tests/test_server.py:8174 (direkt/dynamisch unklar); tests/test_server.py:8177 (direkt/dynamisch unklar); tests/test_server.py:8191 (direkt/dynamisch unklar); tests/test_server.py:8212 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8239 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8252 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 14120 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 14135 | `coach/context.py` | P7 | offen | tests/test_server.py:5773 (direkt/dynamisch unklar); tests/test_server.py:8214 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8241 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 14144 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 14153 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 14165 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 14182 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_server.py:8180 (direkt/dynamisch unklar); tests/test_server.py:8182 (direkt/dynamisch unklar); tests/test_server.py:8256 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 14190 | `coach/context.py` | P7 | offen | tests/test_server.py:5781 (direkt/dynamisch unklar); tests/test_server.py:8186 (direkt/dynamisch unklar); tests/test_server.py:8197 (direkt/dynamisch unklar); tests/test_server.py:8213 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8261 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 14197 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 14198 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 14199 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 14199 | `coach/` | P7 | offen | tests/test_server.py:399 (direkt/dynamisch unklar); tests/test_server.py:455 (direkt/dynamisch unklar); tests/test_server.py:4718 (direkt/dynamisch unklar); tests/test_server.py:4721 (direkt/dynamisch unklar); tests/test_server.py:5071 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 14199 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 14199 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 14208 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 14216 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 14220 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 14225 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 14236 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 14261 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 14280 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 14292 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:2905 (direkt/dynamisch unklar); tests/test_server.py:2907 (direkt/dynamisch unklar); tests/test_server.py:5337 (direkt/dynamisch unklar); tests/test_server.py:5373 (direkt/dynamisch unklar); tests/test_server.py:5396 (direkt/dynamisch unklar); tests/test_server.py:5398 (direkt/dynamisch unklar); tests/test_server.py:5414 (direkt/dynamisch unklar); tests/test_server.py:5421 (direkt/dynamisch unklar); tests/test_server.py:5435 (direkt/dynamisch unklar); tests/test_server.py:5458 (direkt/dynamisch unklar); tests/test_server.py:5483 (direkt/dynamisch unklar); tests/test_server.py:5512 (direkt/dynamisch unklar); tests/test_server.py:5532 (direkt/dynamisch unklar); tests/test_server.py:5584 (direkt/dynamisch unklar); tests/test_server.py:5597 (direkt/dynamisch unklar); tests/test_server.py:5603 (direkt/dynamisch unklar); tests/test_server.py:5632 (direkt/dynamisch unklar); tests/test_server.py:5659 (direkt/dynamisch unklar); tests/test_server.py:5662 (direkt/dynamisch unklar); tests/test_server.py:5683 (direkt/dynamisch unklar); tests/test_server.py:736 (direkt/dynamisch unklar); tests/test_server.py:749 (direkt/dynamisch unklar); tests/test_server.py:825 (direkt/dynamisch unklar); tests/test_server.py:860 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 14315 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 14322 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 14329 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 14347 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 14357 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:322 (direkt/dynamisch unklar); tests/test_server.py:347 (direkt/dynamisch unklar); tests/test_server.py:4409 (direkt/dynamisch unklar); tests/test_server.py:5318 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 14370 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 14379 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 14390 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 14422 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 14448 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 14468 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 14492 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 14504 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 14517 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 14531 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 14539 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 14550 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 14572 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 14582 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 14596 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 14608 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 14622 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 14630 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 14643 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 14652 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 14674 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 14692 | `planning/` | P4 | offen | tests/test_server.py:4748 (direkt/dynamisch unklar); tests/test_server.py:4770 (direkt/dynamisch unklar); tests/test_server.py:4789 (direkt/dynamisch unklar); tests/test_server.py:4811 (direkt/dynamisch unklar); tests/test_server.py:4826 (direkt/dynamisch unklar); tests/test_server.py:4842 (direkt/dynamisch unklar); tests/test_server.py:4860 (direkt/dynamisch unklar); tests/test_server.py:4882 (direkt/dynamisch unklar); tests/test_server.py:4900 (direkt/dynamisch unklar); tests/test_server.py:4923 (direkt/dynamisch unklar); tests/test_server.py:4967 (direkt/dynamisch unklar); tests/test_server.py:4992 (direkt/dynamisch unklar); tests/test_server.py:5013 (direkt/dynamisch unklar); tests/test_server.py:5028 (direkt/dynamisch unklar); tests/test_server.py:5047 (direkt/dynamisch unklar); tests/test_server.py:5064 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 14703 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 14713 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 14730 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 14741 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 14771 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 14789 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 14795 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 14808 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 14826 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 14842 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 14855 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 14869 | `planning/` | P4 | offen | tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:5485 (direkt/dynamisch unklar); tests/test_server.py:5513 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 14903 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:1007 (direkt/dynamisch unklar); tests/test_server.py:1016 (direkt/dynamisch unklar); tests/test_server.py:380 (direkt/dynamisch unklar); tests/test_server.py:411 (direkt/dynamisch unklar); tests/test_server.py:8536 (direkt/dynamisch unklar); tests/test_server.py:929 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 14916 | `sync/reconcile.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 14928 | `sync/reconcile.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 14943 | `sync/reconcile.py` | P6 | offen | tests/test_server.py:420 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 14955 | `sync/reconcile.py` | P6 | offen | tests/test_server.py:690 (direkt/dynamisch unklar); tests/test_server.py:700 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 14985 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 14993 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 15000 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 15022 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 15029 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 15035 | `coach/context.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 15053 | `coach/context.py` | P7 | offen | tests/test_server.py:444 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 15081 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 15090 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 15117 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 15143 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 15148 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 15154 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 15168 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 15175 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 15183 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 15190 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 15199 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 15206 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 15219 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 15242 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 15256 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 15270 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 15298 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 15314 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 15333 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 15353 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 15375 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 15391 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 15408 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 15443 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 15455 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 15470 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 15490 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 15516 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 15534 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 15542 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 15563 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 15590 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 15614 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 15641 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 15662 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:1009 (direkt/dynamisch unklar); tests/test_server.py:334 (direkt/dynamisch unklar); tests/test_server.py:366 (direkt/dynamisch unklar); tests/test_server.py:390 (direkt/dynamisch unklar); tests/test_server.py:423 (direkt/dynamisch unklar); tests/test_server.py:445 (direkt/dynamisch unklar); tests/test_server.py:470 (direkt/dynamisch unklar); tests/test_server.py:477 (direkt/dynamisch unklar); tests/test_server.py:4946 (direkt/dynamisch unklar); tests/test_server.py:517 (direkt/dynamisch unklar); tests/test_server.py:5343 (direkt/dynamisch unklar); tests/test_server.py:5379 (direkt/dynamisch unklar); tests/test_server.py:546 (direkt/dynamisch unklar); tests/test_server.py:5464 (direkt/dynamisch unklar); tests/test_server.py:552 (direkt/dynamisch unklar); tests/test_server.py:5538 (direkt/dynamisch unklar); tests/test_server.py:556 (direkt/dynamisch unklar); tests/test_server.py:5562 (direkt/dynamisch unklar); tests/test_server.py:5567 (direkt/dynamisch unklar); tests/test_server.py:5616 (direkt/dynamisch unklar); tests/test_server.py:5638 (direkt/dynamisch unklar); tests/test_server.py:573 (direkt/dynamisch unklar); tests/test_server.py:577 (direkt/dynamisch unklar); tests/test_server.py:714 (direkt/dynamisch unklar); tests/test_server.py:756 (direkt/dynamisch unklar); tests/test_server.py:785 (direkt/dynamisch unklar); tests/test_server.py:804 (direkt/dynamisch unklar); tests/test_server.py:833 (direkt/dynamisch unklar); tests/test_server.py:866 (direkt/dynamisch unklar); tests/test_server.py:886 (direkt/dynamisch unklar); tests/test_server.py:913 (direkt/dynamisch unklar); tests/test_server.py:939 (direkt/dynamisch unklar); tests/test_server.py:958 (direkt/dynamisch unklar); tests/test_server.py:984 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 15704 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 15708 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 15721 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8550 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 15733 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 15752 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 15768 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 15779 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 15801 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 15816 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 15834 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 15864 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 15870 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 15884 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 15894 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 15907 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 15920 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 15937 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 15950 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5676 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 15977 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 15994 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 15999 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 16008 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 16022 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 16035 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 16045 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 16058 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 16079 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 16102 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 16113 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 16122 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 16134 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 16148 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 16156 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 16171 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 16191 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 16215 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 16229 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 16240 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 16265 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 16281 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 16296 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 16353 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 16381 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 16411 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 16427 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 16447 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 16461 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 16473 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 16483 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 16534 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 16596 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 16600 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 16605 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 16623 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 16642 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 16652 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 16678 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 16716 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 16742 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 16767 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 16798 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 16838 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 16868 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 16888 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 16946 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 16950 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 16966 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 16982 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 17014 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 17058 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 17074 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 17093 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 17119 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 17196 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 17201 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 17210 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 17215 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 17242 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 17260 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 17289 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 17308 | `coach/service.py` | P7 | offen | tests/test_server.py:4311 (direkt/dynamisch unklar); tests/test_server.py:4326 (direkt/dynamisch unklar); tests/test_server.py:4340 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 17318 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 17333 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 17365 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 17380 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4413 (direkt/dynamisch unklar); tests/test_server.py:5329 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 17393 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5717 (direkt/dynamisch unklar); tests/test_server.py:5720 (direkt/dynamisch unklar); tests/test_server.py:8190 (direkt/dynamisch unklar); tests/test_server.py:8193 (direkt/dynamisch unklar); tests/test_server.py:8194 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 17412 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 17425 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 17449 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 17465 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 17476 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 17491 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:263 (direkt/dynamisch unklar); tests/test_audit_remediation.py:278 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5746 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5770 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5802 (direkt/dynamisch unklar); tests/test_server.py:5865 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 17515 | `sync/` | P6 | offen | tests/test_server.py:4489 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 17556 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:270 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4488 (direkt/dynamisch unklar); tests/test_server.py:5744 (direkt/dynamisch unklar); tests/test_server.py:5763 (direkt/dynamisch unklar); tests/test_server.py:5790 (direkt/dynamisch unklar); tests/test_server.py:5819 (direkt/dynamisch unklar); tests/test_server.py:5843 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 17581 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 17607 | `coach/authorization.py` | P7 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 17617 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 17621 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 17629 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 17635 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 17645 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 17662 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 17693 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 17715 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 17730 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:279 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:148 (direkt/dynamisch unklar); tests/test_server.py:5747 (direkt/dynamisch unklar); tests/test_server.py:5771 (direkt/dynamisch unklar); tests/test_server.py:5825 (direkt/dynamisch unklar); tests/test_server.py:5868 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 17751 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 17766 | `coach/authorization.py` | P7 | offen | tests/test_server.py:242 (direkt/dynamisch unklar) |
| Funktion | `local_now` | 17777 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1202 (direkt/dynamisch unklar); tests/test_server.py:1586 (direkt/dynamisch unklar); tests/test_server.py:1602 (direkt/dynamisch unklar); tests/test_server.py:1603 (direkt/dynamisch unklar); tests/test_server.py:1624 (direkt/dynamisch unklar); tests/test_server.py:1642 (direkt/dynamisch unklar); tests/test_server.py:1661 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1674 (direkt/dynamisch unklar); tests/test_server.py:1711 (direkt/dynamisch unklar); tests/test_server.py:1719 (direkt/dynamisch unklar); tests/test_server.py:1759 (direkt/dynamisch unklar); tests/test_server.py:2440 (direkt/dynamisch unklar); tests/test_server.py:2506 (direkt/dynamisch unklar); tests/test_server.py:2565 (direkt/dynamisch unklar); tests/test_server.py:2575 (direkt/dynamisch unklar); tests/test_server.py:2753 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2813 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2843 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2852 (direkt/dynamisch unklar); tests/test_server.py:3340 (direkt/dynamisch unklar); tests/test_server.py:3359 (direkt/dynamisch unklar); tests/test_server.py:3391 (direkt/dynamisch unklar); tests/test_server.py:3416 (direkt/dynamisch unklar); tests/test_server.py:3506 (direkt/dynamisch unklar); tests/test_server.py:3507 (direkt/dynamisch unklar); tests/test_server.py:3551 (direkt/dynamisch unklar); tests/test_server.py:5086 (direkt/dynamisch unklar); tests/test_server.py:5135 (direkt/dynamisch unklar); tests/test_server.py:5152 (direkt/dynamisch unklar); tests/test_server.py:5174 (direkt/dynamisch unklar); tests/test_server.py:5201 (direkt/dynamisch unklar); tests/test_server.py:5233 (direkt/dynamisch unklar); tests/test_server.py:541 (direkt/dynamisch unklar); tests/test_server.py:5908 (direkt/dynamisch unklar); tests/test_server.py:7242 (direkt/dynamisch unklar); tests/test_server.py:7560 (direkt/dynamisch unklar); tests/test_server.py:8291 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 17786 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1943 (direkt/dynamisch unklar); tests/test_server.py:1944 (direkt/dynamisch unklar); tests/test_server.py:1945 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 17794 | `sync/daily.py` | P6 | offen | tests/test_server.py:1942 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 17802 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 17807 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 17818 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 17830 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4020 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 17833 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 17840 | `coach/authorization.py` | P7 | offen | tests/test_server.py:4018 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 17857 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 17863 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 17871 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 17883 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:302 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 17915 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 17936 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 17950 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 17963 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 17982 | `http_api/bootstrap.py` | P10 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 18016 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1769 (direkt/dynamisch unklar); tests/test_server.py:1783 (direkt/dynamisch unklar); tests/test_server.py:1826 (direkt/dynamisch unklar); tests/test_server.py:1908 (direkt/dynamisch unklar); tests/test_server.py:8331 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 18090 | `http_api/` | P10 | offen | tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:2845 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 18126 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 18131 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 18135 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:98 (direkt/dynamisch unklar); tests/test_server.py:1266 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 18142 | `http_api/` | P10 | offen | tests/test_server.py:1238 (direkt/dynamisch unklar); tests/test_server.py:1246 (direkt/dynamisch unklar); tests/test_server.py:1669 (direkt/dynamisch unklar); tests/test_server.py:1714 (direkt/dynamisch unklar); tests/test_server.py:2379 (direkt/dynamisch unklar); tests/test_server.py:3556 (direkt/dynamisch unklar); tests/test_server.py:7171 (direkt/dynamisch unklar); tests/test_server.py:8331 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 18254 | `diagnostics/report.py` | P9 | offen | tests/test_server.py:7705 (direkt/dynamisch unklar); tests/test_server.py:7757 (direkt/dynamisch unklar); tests/test_server.py:7871 (direkt/dynamisch unklar); tests/test_server.py:7902 (direkt/dynamisch unklar); tests/test_server.py:8077 (direkt/dynamisch unklar); tests/test_server.py:8113 (direkt/dynamisch unklar); tests/test_server.py:8387 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 18271 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 18287 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 18308 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 18322 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 18338 | `diagnostics/report.py` | P9 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 18347 | `diagnostics/report.py` | P9 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7620 (direkt/dynamisch unklar); tests/test_server.py:7622 (direkt/dynamisch unklar); tests/test_server.py:7623 (direkt/dynamisch unklar); tests/test_server.py:7670 (direkt/dynamisch unklar); tests/test_server.py:7733 (direkt/dynamisch unklar); tests/test_server.py:7748 (direkt/dynamisch unklar); tests/test_server.py:8504 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 18410 | `privacy.py` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1449 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 18460 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 18461 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 18485 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 18489 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 18500 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 18504 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 18514 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 18522 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:187 (direkt/dynamisch unklar); tests/test_server.py:1464 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 18661 | `db/manager.py` | P1 | offen | tests/test_server.py:6437 (direkt/dynamisch unklar); tests/test_server.py:6450 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 18664 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 18677 | `backup/` | P9 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_server.py:6426 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 18686 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 18707 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1492 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 18718 | `backup/` | P9 | offen | tests/test_audit_remediation.py:293 (direkt/dynamisch unklar); tests/test_server.py:6427 (direkt/dynamisch unklar); tests/test_server.py:6443 (direkt/dynamisch unklar); tests/test_server.py:6456 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 18723 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 18732 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 18749 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 18761 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 18779 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 18786 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 18807 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1532 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1548 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4502 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8450 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 18820 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1541 (direkt/dynamisch unklar); tests/test_server.py:1545 (direkt/dynamisch unklar); tests/test_server.py:1551 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 18835 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 18842 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 18849 | `privacy.py` | P9 | offen | tests/test_server.py:1544 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 18864 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:103 (direkt/dynamisch unklar); tests/test_provider_review.py:116 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (direkt/dynamisch unklar); tests/test_provider_review.py:146 (direkt/dynamisch unklar); tests/test_provider_review.py:164 (direkt/dynamisch unklar); tests/test_server.py:1533 (direkt/dynamisch unklar); tests/test_server.py:1549 (direkt/dynamisch unklar); tests/test_server.py:8451 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 18893 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 18894 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 18895 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 18896 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 18897 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 18898 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1364 (direkt/dynamisch unklar); tests/test_server.py:1372 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 18899 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1369 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 18900 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 18901 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 18902 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 18903 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7835 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 18906 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 18910 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:185 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7837 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 18935 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 18944 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1328 (direkt/dynamisch unklar); tests/test_server.py:1357 (direkt/dynamisch unklar); tests/test_server.py:1360 (direkt/dynamisch unklar); tests/test_server.py:1409 (direkt/dynamisch unklar); tests/test_server.py:1416 (direkt/dynamisch unklar); tests/test_server.py:5732 (direkt/dynamisch unklar); tests/test_server.py:5736 (direkt/dynamisch unklar); tests/test_server.py:5751 (direkt/dynamisch unklar); tests/test_server.py:5755 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 18948 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 18958 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1370 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 18973 | `performance/` | P3 | offen | tests/test_server.py:7800 (direkt/dynamisch unklar); tests/test_server.py:7810 (direkt/dynamisch unklar); tests/test_server.py:7818 (direkt/dynamisch unklar); tests/test_server.py:7825 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 19015 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1334 (direkt/dynamisch unklar); tests/test_server.py:1337 (direkt/dynamisch unklar); tests/test_server.py:1358 (direkt/dynamisch unklar); tests/test_server.py:1391 (direkt/dynamisch unklar); tests/test_server.py:1428 (direkt/dynamisch unklar); tests/test_server.py:3252 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 19041 | `http_api/auth.py` | P10 | offen | tests/test_provider_review.py:188 (direkt/dynamisch unklar); tests/test_provider_review.py:191 (direkt/dynamisch unklar); tests/test_provider_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:3249 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 19060 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1427 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 19068 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 19080 | `http_api/` | P10 | offen | tests/test_server.py:1409 (direkt/dynamisch unklar); tests/test_server.py:1416 (direkt/dynamisch unklar); tests/test_server.py:3254 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 19086 | `http_api/` | P10 | offen | tests/test_server.py:1309 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 19099 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:209 (direkt/dynamisch unklar); tests/test_server.py:1512 (direkt/dynamisch unklar); tests/test_server.py:1807 (direkt/dynamisch unklar); tests/test_server.py:7348 (direkt/dynamisch unklar); tests/test_server.py:7358 (direkt/dynamisch unklar); tests/test_server.py:7364 (direkt/dynamisch unklar); tests/test_server.py:7374 (direkt/dynamisch unklar); tests/test_server.py:7386 (direkt/dynamisch unklar); tests/test_server.py:7391 (direkt/dynamisch unklar); tests/test_server.py:7395 (direkt/dynamisch unklar); tests/test_server.py:7398 (direkt/dynamisch unklar); tests/test_server.py:7404 (direkt/dynamisch unklar); tests/test_server.py:7414 (direkt/dynamisch unklar); tests/test_server.py:7421 (direkt/dynamisch unklar); tests/test_server.py:7428 (direkt/dynamisch unklar); tests/test_server.py:7435 (direkt/dynamisch unklar); tests/test_server.py:8203 (direkt/dynamisch unklar); tests/test_server.py:8226 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 19778 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:209 (direkt/dynamisch unklar); tests/test_server.py:222 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_loop` | 19783 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 19796 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 19800 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 19806 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 19812 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 19818 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 19826 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:155 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 19833 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 19847 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 19852 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 19864 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 19876 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 19881 | `sync/` | P6 | offen | tests/test_server.py:1023 (direkt/dynamisch unklar); tests/test_server.py:1032 (direkt/dynamisch unklar); tests/test_server.py:226 (Monkeypatch/getattr/sys.modules) |
| Funktion | `main` | 19889 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar); tests/test_server.py:229 (direkt/dynamisch unklar) |

## Zielverteilung

| Zielmodul | Einträge |
| --- | ---: |
| `activities/` | 46 |
| `athlete/` | 20 |
| `backend` | 2 |
| `backend/backup/export` | 5 |
| `backend/coach/attachments` | 7 |
| `backend/coach/authorization` | 4 |
| `backend/coach/context` | 10 |
| `backend/coach/dialogue` | 3 |
| `backend/coach/outcomes` | 4 |
| `backend/coach/service` | 4 |
| `backend/coach/tools` | 1 |
| `backend/config` | 3 |
| `backend/db` | 1 |
| `backend/db/bootstrap` | 1 |
| `backend/db/manager` | 1 |
| `backend/db/repositories` | 9 |
| `backend/db/schema` | 5 |
| `backend/errors` | 19 |
| `backend/http_api/requests` | 3 |
| `backend/http_api/responses` | 4 |
| `backend/planning/adaptive` | 2 |
| `backend/planning/changes` | 3 |
| `backend/planning/repository` | 2 |
| `backend/planning/service` | 3 |
| `backend/providers` | 6 |
| `backend/providers/garmin` | 2 |
| `backend/providers/http` | 2 |
| `backend/providers/intervals` | 3 |
| `backend/providers/workout_text` | 4 |
| `backend/runtime` | 2 |
| `backend/settings` | 1 |
| `backend/sync` | 1 |
| `backend/sync/cursors` | 2 |
| `backend/sync/daily` | 2 |
| `backend/sync/jobs` | 12 |
| `backend/sync/reconcile` | 2 |
| `backend/sync/refresh` | 3 |
| `backend/sync/snapshots` | 2 |
| `backend/sync/status` | 2 |
| `backend/sync/windows` | 1 |
| `backup/` | 16 |
| `calendar/` | 34 |
| `coach/` | 27 |
| `coach/authorization.py` | 33 |
| `coach/context.py` | 63 |
| `coach/conversation.py` | 19 |
| `coach/dialogue.py` | 18 |
| `coach/jobs.py` | 5 |
| `coach/morning.py` | 3 |
| `coach/proposals.py` | 66 |
| `coach/service.py` | 6 |
| `coach/streams.py` | 3 |
| `coach/tool_execution.py` | 8 |
| `config.py` | 6 |
| `db/` | 20 |
| `db/bootstrap.py` | 1 |
| `db/manager.py` | 6 |
| `diagnostics/report.py` | 7 |
| `history/` | 34 |
| `http_api/` | 38 |
| `http_api/auth.py` | 21 |
| `http_api/bootstrap.py` | 1 |
| `http_api/pagination.py` | 9 |
| `observability.py` | 18 |
| `performance/` | 56 |
| `performance/activity_validation.py` | 4 |
| `planning/` | 219 |
| `planning/calendar.py` | 1 |
| `planning/competitions.py` | 96 |
| `privacy.py` | 8 |
| `providers/` | 67 |
| `providers/calendar.py` | 6 |
| `providers/http.py` | 11 |
| `providers/intervals_client.py` | 1 |
| `providers/workout_text.py` | 12 |
| `runtime/` | 2 |
| `server.py / Composition Root` | 51 |
| `settings.py` | 7 |
| `sync/` | 172 |
| `sync/competitions.py` | 1 |
| `sync/daily.py` | 1 |
| `sync/freshness.py` | 1 |
| `sync/garmin.py` | 85 |
| `sync/jobs.py` | 1 |
| `sync/reconcile.py` | 4 |
| `sync/refresh.py` | 4 |
| `sync/scheduler.py` | 13 |
| `sync/snapshots.py` | 1 |
| `sync/status.py` | 1 |
| `weather/` | 55 |

## Grenzen und offene Unsicherheiten

- AST-Aufrufauflösung erfasst nur direkte lokale Aufrufe; `getattr`, `globals()`, `sys.modules`, dekoratorbasierte Registrierung und Callback-Injektion benötigen eine manuelle Nachprüfung.
- Ein Name kann in mehreren Kategorien mit derselben Schreibweise vorkommen; Referenzzählungen sind deshalb namensbasiert und zeigen Ortsangaben, nicht vermeintliche Laufzeitidentität.
- Die Tabelle enthält bewusst auch Importbindungen, damit Rückimporte, spätere Re-Exports und der endgültige Composition-Root-Inhalt überprüfbar bleiben.
- Offene Zielzuordnungen müssen vor dem jeweiligen Umzug fachlich entschieden werden; sie gelten nicht als erledigt.
