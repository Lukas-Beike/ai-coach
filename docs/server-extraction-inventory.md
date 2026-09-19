# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `6e8f99953bb79491d3214c3ca291dc81bdd67c5921e523405c527bf04174e2a2`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 20.357 physische Zeilen
- Inventareinträge: 1.570
- Definitionen (Funktionen/Klassen): 1.118
- Globale Bindungen einschließlich Imports: 261 Zuweisungen. 191 Imports
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
| P1 | 20 | 40 | 140 |
| P2 | 113 | 13 | 0 |
| P3 | 186 | 27 | 0 |
| P4 | 290 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 228 | 43 | 0 |
| P7 | 187 | 39 | 0 |
| P8 | 14 | 11 | 0 |
| P9 | 25 | 6 | 0 |
| P10 | 30 | 39 | 0 |
| P11 | 1 | 3 | 51 |

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
- `tests/test_server.py:2448: ), patch.object(server, "fetch_calendar_feed", return_value=b"not an ical feed"):`
- `tests/test_server.py:2454: with patch.object(server.socket, "getaddrinfo", return_value=[(None, None, None, None, ("100.64.0.1", 443))]):`
- `tests/test_server.py:2478: with patch.object(server, "_resolve_calendar_addresses", return_value=addresses) as resolve, patch.object(`
- `tests/test_server.py:2480: ), patch.object(server.socket, "create_connection", side_effect=[OSError("first address unavailable"), raw_socket]) as connect, patch.object(`
- `tests/test_server.py:2494: ), patch.object(server.socket, "create_connection", side_effect=TimeoutError("calendar timeout")):`
- `tests/test_server.py:2533: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload), patch.object(`
- `tests/test_server.py:2562: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload):`
- `tests/test_server.py:2577: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", side_effect=server.AppError(502, "upstream unavailable")):`
- `tests/test_server.py:257: with patch.object(server, "_execute_sync_job", return_value={"status": "ok"}):`
- `tests/test_server.py:2644: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:268: with patch.object(server, "_execute_sync_job", side_effect=server.AppError(503, provider_detail, reason="network_error")):`
- `tests/test_server.py:2739: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=-1)):`
- `tests/test_server.py:2748: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=30)):`
- `tests/test_server.py:2758: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:279: with patch.object(server, "sync_garmin") as sync:`
- `tests/test_server.py:2805: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)):`
- `tests/test_server.py:2865: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 20, 0)):`
- `tests/test_server.py:2892: patch.object(server, "latest_snapshot", return_value=snapshot),`
- `tests/test_server.py:2893: patch.object(server, "list_dated_local_planned_workouts", return_value=planned),`
- `tests/test_server.py:2894: patch.object(server, "weather_state", return_value={"days": []}),`
- `tests/test_server.py:2895: patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)),`
- `tests/test_server.py:301: with patch.object(server, "_execute_sync_job", return_value=result):`
- `tests/test_server.py:311: with patch.object(server, "_repair_local_planned_unit_calendar_entry", return_value=None) as repair:`
- `tests/test_server.py:3299: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:3794: with patch.object(server.IntervalsClient, "get_workout_library", return_value=[]), \`
- `tests/test_server.py:3795: patch.object(server.IntervalsClient, "create_library_workouts", return_value=[{"id": "synthetic-remote", "type": "Ride"}]) as create, \`
- `tests/test_server.py:3796: patch.object(server.IntervalsClient, "update_library_workout", return_value={"id": "synthetic-remote", **parsed_workout_fixture()}) as update:`
- `tests/test_server.py:3814: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=[`
- `tests/test_server.py:3839: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:3857: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:3859: ), patch.object(server.IntervalsClient, "create_library_workouts") as create:`
- `tests/test_server.py:389: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-plan-push"}) as enqueue:`
- `tests/test_server.py:4066: with patch.object(server, "garmin_fixture_path", return_value="fixture.json"), \`
- `tests/test_server.py:4067: patch.object(server, "sync_garmin") as sync_garmin, \`
- `tests/test_server.py:4068: patch.object(server, "garmin_sleep_ready_for_checkin", return_value=False), \`
- `tests/test_server.py:4113: with patch.object(server, "CONFIG", config), patch.object(server, "Garmin", FakeGarmin):`
- `tests/test_server.py:420: with patch.object(server, "_mark_local_planning_authoritative"), patch.object(`
- `tests/test_server.py:4282: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4326: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=fake_urlopen):`
- `tests/test_server.py:4351: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:444: with patch.object(server, "_enqueue_coach_plan_push") as enqueue, self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:4475: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value=response):`
- `tests/test_server.py:4490: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4501: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4515: with patch.object(server, "CONFIG", replace(server.CONFIG, gemini_api_key=key)):`
- `tests/test_server.py:4521: with patch.object(server, "CONFIG", config), patch.object(server, "gemini_responses_request", return_value={"output_text": "ok"}) as gemini, patch.object(server, "openai_request") as openai:`
- `tests/test_server.py:4534: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4554: with patch.object(server, "CONFIG", config), patch.object(server, "delete_remote_conversation", return_value=True) as delete:`
- `tests/test_server.py:4572: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:4621: with patch.object(server, "urlopen", side_effect=blocked_urlopen):`
- `tests/test_server.py:4652: with patch.object(server, "urlopen", return_value=response):`
- `tests/test_server.py:4685: with patch.object(server, "urlopen", side_effect=return_cancelled_response):`
- `tests/test_server.py:4704: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")), patch.object(`
- `tests/test_server.py:4723: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4726: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url="")):`
- `tests/test_server.py:4734: with self.subTest(invalid=invalid), patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url=invalid)):`
- `tests/test_server.py:4747: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:476: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-competition"}) as enqueue:`
- `tests/test_server.py:4771: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:4778: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4950: with patch.object(server, "calendar_conflicts", return_value=[{"name": "Occupied"}]) as conflicts:`
- `tests/test_server.py:5264: with patch.object(server, "structured_athlete_context", return_value={"source_policy": {"untrusted": "x" * 200_000}}):`
- `tests/test_server.py:5371: with patch.object(server, "openai_request", side_effect=fake_openai):`
- `tests/test_server.py:5377: with patch.object(server, "http_json", return_value=response), patch.object(`
- `tests/test_server.py:5393: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:5507: with patch.object(server, "CHANGE_HISTORY_MAX_ROWS", 3), self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:5644: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 2):`
- `tests/test_server.py:5658: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 1):`
- `tests/test_server.py:572: with patch.object(server, "enqueue_sync_job", side_effect=[{"id": "job-performance"}, {"id": "job-competition"}]) as enqueue:`
- `tests/test_server.py:5744: with patch.object(server, "save_workout_library_entries", side_effect=RuntimeError("creation failed")):`
- `tests/test_server.py:5746: server._apply_training_patch(arguments, {`
- `tests/test_server.py:5763: with patch.object(server, "responses_request", side_effect=create), patch.object(`
- `tests/test_server.py:5768: ) as retrieve, patch.object(server, "OPENAI_BACKGROUND_POLL_SECONDS", 0), patch.object(server, "record_openai_usage"):`
- `tests/test_server.py:5816: with patch.object(server, "chat_with_coach", side_effect=lambda *args, **kwargs: seen.update(kwargs) or {}):`
- `tests/test_server.py:5840: with patch.object(server, "chat_with_coach", side_effect=complete_chat):`
- `tests/test_server.py:5869: with patch.object(server, "responses_stream_request", side_effect=streamed_response) as streamed, patch.object(`
- `tests/test_server.py:5894: ), patch.object(server, "_restore_coach_session_csrf_hash", return_value="csrf-background-requeue"):`
- `tests/test_server.py:5935: with patch.object(server, "chat_with_coach", side_effect=capture_phase), patch.object(`
- `tests/test_server.py:595: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:5971: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:5973: ) as fetch_snapshot, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:5984: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6000: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6002: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6013: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6015: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6031: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6044: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6072: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6074: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=remote) as get_library:`
- `tests/test_server.py:608: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:6112: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6114: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6134: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6138: ) as import_units, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6156: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6158: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[{`
- `tests/test_server.py:6175: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6179: ) as library_sync, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6194: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:619: with patch.object(server, "sync_intervals", return_value={"status": "ok"}) as sync, patch.object(`
- `tests/test_server.py:6248: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6257: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6276: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6285: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6294: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6302: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6319: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:631: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6363: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6377: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_server.py:6395: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6440: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6442: ), patch.object(server, "_sync_selected_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6465: with patch.object(server, "IntervalsClient", FailingIntervalsClient), patch.object(`
- `tests/test_server.py:6475: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6488: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", db_path), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:650: with patch.object(server, "CONFIG", config), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:6533: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:6554: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6563: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir), patch.dict(`
- `tests/test_server.py:6583: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir):`
- `tests/test_server.py:659: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:661: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:663: ) as enqueue, patch.object(server, "_wait_for_performance_refresh") as wait:`
- `tests/test_server.py:672: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6730: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:674: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:6762: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6800: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6832: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6848: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6887: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6920: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6947: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7230: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:7231: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:7360: with patch.object(server, "http_json", side_effect=[`
- `tests/test_server.py:7443: with patch.object(server.LOGGER, "info") as logger:`
- `tests/test_server.py:7620: with patch.object(server.IntervalsClient, "delete_activity", return_value=None) as delete:`
- `tests/test_server.py:7670: with patch.object(server, "get_kv", side_effect=get_kv_after_read):`
- `tests/test_server.py:7702: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7724: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7730: with patch.object(server, "external_calendar_url", return_value=calendar_url), patch.object(`
- `tests/test_server.py:7752: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7771: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7788: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7822: with patch.object(server, "urlopen", side_effect=server.URLError("offline")):`
- `tests/test_server.py:7839: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7853: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7863: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7879: with patch.object(server, "database", side_effect=OSError("database unavailable")):`
- `tests/test_server.py:7887: with patch.object(server.tempfile, "NamedTemporaryFile", side_effect=OSError("read-only")):`
- `tests/test_server.py:7906: with patch.object(server.time, "monotonic", return_value=20 * 60):`
- `tests/test_server.py:7935: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:7937: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[]):`
- `tests/test_server.py:7964: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8000: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8027: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8048: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8079: with patch.object(server, "openai_request", side_effect=fake_request), patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8098: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8140: with patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:8153: with patch.object(server, "urlopen") as urlopen:`
- `tests/test_server.py:8177: with patch.object(server, "urlopen", return_value=TimeoutResponse()):`
- `tests/test_server.py:8202: with patch.object(server, "urlopen", return_value=DisconnectResponse()):`
- `tests/test_server.py:8210: with patch.object(server, "openai_stream_request", side_effect=responses) as request, patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8257: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), \`
- `tests/test_server.py:8258: patch.object(server, "unregister_chat_stream") as unregister, \`
- `tests/test_server.py:8259: patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8284: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), patch.object(`
- `tests/test_server.py:8286: ) as unregister, patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8338: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value={"status": "completed"}) as request:`
- `tests/test_server.py:8391: with patch.object(server, "DB_LOCK", database_lock), patch.object(`
- `tests/test_server.py:8408: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8495: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:8509: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8520: with patch.object(server, "CONFIG", replace(config, intervals_api_key="")):`
- `tests/test_server.py:8577: with patch.object(server, "CONFIG", config), patch.object(`
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
| `ProviderResyncGate` | 302 | – | `AppError`, `contextmanager`, `threading` | – | – |
| `provider_operation` | 353 | – | `GARMIN_RESYNC_GATE`, `INTERVALS_RESYNC_GATE` | – | – |
| `intervals_operation` | 358 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `garmin_operation` | 366 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `IntervalsClient` | 377 | `_raise_chat_cancelled`, `compact_snapshot`, `deduplicate_api_records`, `intervals_workout_sport`, `latest_snapshot`, `local_now`, `selected`, `sync_date_windows`, `validate_intervals_workout_result`, `validate_workout_description`, `workout_event_payload` | `ALL_SYNC_DAYS`, `APP_NAME`, `Any`, `AppError`, `CONFIG`, `Callable`, `Config`, `IntervalsReadTransport`, `IntervalsWriteTransport`, `PLANNED_CALENDAR_FUTURE_DAYS`, `PLANNED_CALENDAR_HISTORY_DAYS`, `_raise_chat_cancelled`, … (+18) | – | – |
| `external_call` | 684 | `operation_error_code` | `Any`, `AppError`, `DATA_DIR`, `DIAGNOSTIC_CAPTURE`, `LOGGER`, `LOG_PATH`, `OPERATION_CONTEXT`, `REDACTOR`, `observability`, `operation_error_code`, `provider_error`, `time` | – | – |
| `serialise_conversation` | 876 | – | `AppError`, `CHAT_LOCK_TIMEOUT_SECONDS`, `CHAT_QUEUE`, `OPENAI_CONVERSATION_LOCK`, `wraps` | – | – |
| `utc_now` | 893 | – | `datetime`, `timezone` | – | – |
| `operation_trigger` | 966 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 972 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 981 | – | `Any` | – | – |
| `log_operation_event` | 991 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1018 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1039 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count`, `runtime_maintenance`, `wraps` | – | – |
| `database_manager` | 1082 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE` | – |
| `database` | 1109 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1115 | `database`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `KEY_VALUE_REPOSITORY`, `PROVIDER_RESYNC_KEYS`, `database`, `datetime`, `initialize_application_database`, `json`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_cleanup` | 1127 | – | `Any`, `cleanup_refresh_history`, `datetime`, `sync_freshness`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1135 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `runtime_events`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1147 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `runtime_events`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1181 | – | – | – | – |
| `_sync_job_error_class` | 1196 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1210 | – | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1219 | – | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1233 | `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1246 | `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1256 | `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1265 | – | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1275 | – | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1282 | `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1307 | `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1316 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1322 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1327 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1350 | – | `AppError` | – | – |
| `_pending_performance_job_id` | 1358 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1367 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1385 | `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1412 | – | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1421 | – | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1428 | – | `Any` | – | – |
| `_insert_sync_job` | 1438 | – | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 1463 | – | `Any`, `runtime_events` | – | – |
| `enqueue_sync_job` | 1477 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `runtime_maintenance`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 1504 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 1524 | `database`, `utc_now` | `Any`, `DB_LOCK`, `database`, `runtime_maintenance`, `utc_now` | – | – |
| `_sync_job_update` | 1545 | `database`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `runtime_events`, `utc_now` | – | – |
| `_sync_job_item_results` | 1583 | – | `Any` | – | – |
| `_sync_job_result_target` | 1589 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 1600 | `_sync_job_result_target` | `Any`, `REDACTOR`, `_sync_job_result_target` | – | – |
| `_sync_job_completion_snapshot` | 1620 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 1635 | – | `runtime_events` | – | – |
| `_sync_job_update_from_result` | 1652 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 1665 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 1674 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 1681 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 1698 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 1710 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 1722 | `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 1745 | – | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 1754 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 1774 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 1794 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | `Any`, `LOGGER`, `REDACTOR`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | – | – |
| `_run_claimed_sync_job` | 1812 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `runtime_maintenance` | – | – |
| `_sync_job_worker_loop` | 1822 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job`, `runtime_maintenance` | – | – |
| `start_sync_job_worker` | 1837 | – | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 1848 | `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_current_provider_freshness` | 1871 | `_garmin_core_error_entries`, `database`, `get_profile` | `Any`, `CONFIG`, `DB_LOCK`, `Path`, `_garmin_core_error_entries`, `database`, `datetime`, `get_kv`, `get_profile`, `sync_freshness`, `timezone` | – | – |
| `_audit_projection_fields` | 1885 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 1899 | – | `Any`, `json` | – | – |
| `_audit_projection` | 1910 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 1934 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 1939 | – | `Any` | – | – |
| `_cleanup_change_history` | 1951 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 1961 | – | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 1978 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2017 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2049 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2060 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2072 | – | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2086 | – | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2102 | `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2140 | `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2160 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2170 | `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2195 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2216 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2226 | `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2235 | `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2261 | `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2277 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2306 | `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2321 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |
| `sync_period` | 2359 | `get_kv` | `ALL_SYNC_DAYS`, `SYNC_PERIOD_DEFAULTS`, `get_kv` | – | – |
| `set_sync_period` | 2370 | `set_kv` | `ALL_SYNC_DAYS`, `Any`, `AppError`, `set_kv` | – | – |
| `sync_date_windows` | 2382 | `local_now` | `ALL_SYNC_DAYS`, `SYNC_CHUNK_DAYS`, `SYNC_EARLIEST_DATE`, `date`, `local_now`, `split_date_windows` | – | – |
| `provider_sync_cursor` | 2393 | `database` | `Any`, `DB_LOCK`, `database`, `read_cursor` | – | – |
| `update_provider_sync_cursor` | 2398 | `database`, `utc_now` | `DB_LOCK`, `database`, `utc_now`, `write_cursor` | – | – |
| `set_kv` | 2404 | `database`, `set_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `set_kv`, `sqlite3` | – | – |
| `_coach_error_metadata` | 2416 | – | `Any`, `Path`, `ROOT`, `observability` | – | – |
| `_safe_response_headers` | 2431 | – | `Any`, `REDACTOR` | – | – |
| `garmin_snapshot` | 2448 | `get_kv` | `Any`, `get_kv`, `json` | – | – |
| `garmin_configured` | 2456 | – | `CONFIG`, `Garmin` | – | – |
| `garmin_fixture_path` | 2460 | – | `CONFIG`, `Path`, `ROOT` | – | – |
| `activity_datetime` | 2468 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `activity_kind` | 2480 | – | `Any` | – | – |
| `_cycling_event_candidates` | 2495 | `activity_kind` | `Any`, `activity_kind` | – | – |
| `_cycling_event_interval` | 2505 | `activity_datetime`, `as_number` | `Any`, `activity_datetime`, `as_number`, `datetime`, `timedelta` | – | – |
| `_cycling_intervals_share_group` | 2516 | – | `datetime` | – | – |
| `_cycling_event_edges` | 2525 | `_cycling_intervals_share_group` | `_cycling_intervals_share_group`, `datetime` | – | – |
| `_cycling_event_group` | 2540 | – | `Any` | – | – |
| `parallel_cycling_event_groups` | 2554 | `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | `Any`, `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | – | – |
| `_garmin_duplicate_measurements` | 2566 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_activity_matches` | 2582 | `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | `Any`, `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | – | – |
| `garmin_activity_duplicates_intervals` | 2597 | `_garmin_activity_matches` | `Any`, `_garmin_activity_matches` | – | – |
| `filter_garmin_activities` | 2604 | `garmin_activity_duplicates_intervals` | `Any`, `garmin_activity_duplicates_intervals` | – | – |
| `intervals_activity_device_source` | 2611 | – | `Any` | – | – |
| `intervals_cycling_activities_match` | 2626 | `activity_datetime`, `activity_kind`, `as_number`, `first_present` | `Any`, `activity_datetime`, `activity_kind`, `as_number`, `first_present` | – | – |
| `_latest_activity_id` | 2649 | `activity_datetime`, `first_present` | `Any`, `activity_datetime`, `first_present` | – | – |
| `_wahoo_garmin_pairs` | 2662 | `activity_datetime`, `activity_kind`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | `Any`, `activity_datetime`, `activity_kind`, `datetime`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | – | – |
| `_wahoo_garmin_duplicate_view` | 2680 | `first_present` | `Any`, `datetime`, `first_present` | – | – |
| `latest_wahoo_garmin_duplicate` | 2698 | `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | `Any`, `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | – | – |
| `garmin_activity_max_hr` | 2713 | `activity_kind`, `as_number`, `first_present` | `Any`, `activity_kind`, `as_number`, `first_present` | – | – |
| `merge_garmin_max_hr` | 2728 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_key` | 2756 | – | `Any` | – | – |
| `_garmin_numeric` | 2760 | `as_number`, `first_present` | `Any`, `as_number`, `first_present` | – | – |
| `_garmin_vo2_value` | 2766 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_colon_duration_seconds` | 2771 | – | – | – | – |
| `_garmin_duration_seconds` | 2780 | `_garmin_colon_duration_seconds`, `as_number`, `first_present` | `Any`, `_garmin_colon_duration_seconds`, `as_number`, `first_present` | – | – |
| `_garmin_race_slot` | 2799 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_race_time` | 2812 | `_garmin_duration_seconds` | `Any`, `_garmin_duration_seconds` | – | – |
| `_garmin_weight_kg` | 2816 | `_garmin_key`, `as_number`, `first_present` | `Any`, `_garmin_key`, `as_number`, `first_present` | – | – |
| `_garmin_record_date` | 2834 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_collect_garmin_weight_records` | 2848 | `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | `Any`, `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | – | – |
| `garmin_weight_records` | 2864 | `_collect_garmin_weight_records` | `Any`, `_collect_garmin_weight_records` | – | – |
| `garmin_weight_metric` | 2870 | `garmin_weight_records`, `metric` | `Any`, `GARMIN_PERFORMANCE_SOURCE`, `garmin_weight_records`, `metric` | – | – |
| `garmin_weight_average` | 2878 | `garmin_weight_records` | `Any`, `date`, `garmin_weight_records`, `timedelta` | – | – |
| `_collect_garmin_numeric_values` | 2891 | `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | `Any`, `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | – | – |
| `_garmin_last_numeric` | 2904 | `_collect_garmin_numeric_values` | `Any`, `_collect_garmin_numeric_values` | – | – |
| `_garmin_last_value` | 2911 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_bounded_metric` | 2929 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_pace_seconds` | 2934 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_mapping_nodes` | 2960 | `_garmin_mapping_nodes` | `Any`, `Iterator`, `_garmin_mapping_nodes` | – | – |
| `_garmin_sport_category` | 2970 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `garmin_profile_max_hr` | 2979 | `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | `Any`, `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | – | – |
| `_garmin_collect_vo2_values` | 2989 | `_garmin_collect_vo2_values`, `_garmin_key`, `_garmin_sport_category`, `_garmin_vo2_value` | `Any`, `_garmin_collect_vo2_values`, `_garmin_key`, `_garmin_sport_category`, `_garmin_vo2_value` | – | – |

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
| Importbindung | `ipaddress` | 11 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2476 (direkt/dynamisch unklar); tests/test_server.py:2493 (direkt/dynamisch unklar) |
| Importbindung | `json` | 12 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_workout_repair.py:572 (direkt/dynamisch unklar) |
| Importbindung | `logging` | 13 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `math` | 14 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `mimetypes` | 15 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `os` | 16 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `platform` | 17 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `queue` | 18 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:8253 (direkt/dynamisch unklar); tests/test_server.py:8279 (direkt/dynamisch unklar) |
| Importbindung | `re` | 19 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `secrets` | 20 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_coach_language_recovery.py:42 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:69 (direkt/dynamisch unklar) |
| Importbindung | `shutil` | 21 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `socket` | 22 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2454 (direkt/dynamisch unklar); tests/test_server.py:2461 (direkt/dynamisch unklar); tests/test_server.py:2480 (direkt/dynamisch unklar); tests/test_server.py:2494 (direkt/dynamisch unklar) |
| Importbindung | `ssl` | 23 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2479 (direkt/dynamisch unklar) |
| Importbindung | `sqlite3` | 24 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1068 (direkt/dynamisch unklar); tests/test_server.py:1243 (direkt/dynamisch unklar); tests/test_server.py:1825 (direkt/dynamisch unklar) |
| Importbindung | `threading` | 25 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_diagnostic_followups.py:170 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:37 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:56 (direkt/dynamisch unklar); tests/test_server.py:228 (direkt/dynamisch unklar); tests/test_server.py:238 (direkt/dynamisch unklar) |
| Importbindung | `tempfile` | 26 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7887 (direkt/dynamisch unklar) |
| Importbindung | `time` | 27 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/support.py:130 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:108 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:41 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:95 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:38 (direkt/dynamisch unklar); tests/test_coach_review.py:257 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:257 (direkt/dynamisch unklar); tests/test_server.py:1357 (direkt/dynamisch unklar); tests/test_server.py:1370 (direkt/dynamisch unklar); tests/test_server.py:4148 (direkt/dynamisch unklar); tests/test_server.py:7906 (direkt/dynamisch unklar); tests/test_server.py:8079 (direkt/dynamisch unklar); tests/test_server.py:8210 (direkt/dynamisch unklar) |
| Importbindung | `uuid` | 28 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `zipfile` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ContextVar` | 30 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `nullcontext` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `contextmanager` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `dataclass` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `date` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1618 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `datetime` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `timedelta` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:541 (direkt/dynamisch unklar) |
| Importbindung | `timezone` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `wraps` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPResponse` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `BaseHTTPRequestHandler` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ThreadingHTTPServer` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `SimpleCookie` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Path` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Any` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Callable` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Iterator` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `NoReturn` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPError` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4565 (direkt/dynamisch unklar); tests/test_server.py:7750 (direkt/dynamisch unklar); tests/test_server.py:7781 (direkt/dynamisch unklar); tests/test_server.py:7832 (direkt/dynamisch unklar); tests/test_server.py:8017 (direkt/dynamisch unklar); tests/test_server.py:8041 (direkt/dynamisch unklar); tests/test_server.py:8056 (direkt/dynamisch unklar); tests/test_server.py:8093 (direkt/dynamisch unklar) |
| Importbindung | `URLError` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7822 (direkt/dynamisch unklar) |
| Importbindung | `parse_qs` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `quote` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlencode` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlparse` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlunparse` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Request` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlopen` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4326 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4572 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4652 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4685 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4771 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7752 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7771 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7788 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7822 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7839 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7964 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8000 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8027 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8048 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8098 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8140 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8153 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8177 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8202 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `database_row_factory` | 44 | `backend/db` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ABORTED_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COMPETITION_NOT_FOUND_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_LIBRARY_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_PLANNING_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GEMINI_API_KEY_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERNAL_SERVER_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERVALS_API_KEY_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_LIBRARY_ID_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_DATE_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_ID_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `NOT_FOUND_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `OPENAI_API_KEY_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PLANNED_CALENDAR_RECHECK_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STALE_PLANNING_REVISION_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STRUCTURED_AUTHORIZATION_ERROR` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AppError` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:161 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_server.py:1008 (direkt/dynamisch unklar); tests/test_server.py:1298 (direkt/dynamisch unklar); tests/test_server.py:1408 (direkt/dynamisch unklar); tests/test_server.py:1415 (direkt/dynamisch unklar); tests/test_server.py:1532 (direkt/dynamisch unklar); tests/test_server.py:1633 (direkt/dynamisch unklar); tests/test_server.py:1637 (direkt/dynamisch unklar); tests/test_server.py:1663 (direkt/dynamisch unklar); tests/test_server.py:1800 (direkt/dynamisch unklar); tests/test_server.py:2051 (direkt/dynamisch unklar); tests/test_server.py:2057 (direkt/dynamisch unklar); tests/test_server.py:2068 (direkt/dynamisch unklar); tests/test_server.py:2072 (direkt/dynamisch unklar); tests/test_server.py:2073 (direkt/dynamisch unklar); tests/test_server.py:2075 (direkt/dynamisch unklar); tests/test_server.py:2080 (direkt/dynamisch unklar); tests/test_server.py:2083 (direkt/dynamisch unklar); tests/test_server.py:2088 (direkt/dynamisch unklar); tests/test_server.py:2091 (direkt/dynamisch unklar); tests/test_server.py:2096 (direkt/dynamisch unklar); tests/test_server.py:2099 (direkt/dynamisch unklar); tests/test_server.py:2106 (direkt/dynamisch unklar); tests/test_server.py:2131 (direkt/dynamisch unklar); tests/test_server.py:2387 (direkt/dynamisch unklar); tests/test_server.py:2449 (direkt/dynamisch unklar); tests/test_server.py:2455 (direkt/dynamisch unklar); tests/test_server.py:2495 (direkt/dynamisch unklar); tests/test_server.py:2577 (direkt/dynamisch unklar); tests/test_server.py:2578 (direkt/dynamisch unklar); tests/test_server.py:2583 (direkt/dynamisch unklar); tests/test_server.py:2585 (direkt/dynamisch unklar); tests/test_server.py:268 (direkt/dynamisch unklar); tests/test_server.py:280 (direkt/dynamisch unklar); tests/test_server.py:3125 (direkt/dynamisch unklar); tests/test_server.py:3162 (direkt/dynamisch unklar); tests/test_server.py:333 (direkt/dynamisch unklar); tests/test_server.py:3596 (direkt/dynamisch unklar); tests/test_server.py:365 (direkt/dynamisch unklar); tests/test_server.py:3696 (direkt/dynamisch unklar); tests/test_server.py:3712 (direkt/dynamisch unklar); tests/test_server.py:3751 (direkt/dynamisch unklar); tests/test_server.py:3778 (direkt/dynamisch unklar); tests/test_server.py:3786 (direkt/dynamisch unklar); tests/test_server.py:3797 (direkt/dynamisch unklar); tests/test_server.py:3818 (direkt/dynamisch unklar); tests/test_server.py:3830 (direkt/dynamisch unklar); tests/test_server.py:3834 (direkt/dynamisch unklar); tests/test_server.py:4022 (direkt/dynamisch unklar); tests/test_server.py:4183 (direkt/dynamisch unklar); tests/test_server.py:4244 (direkt/dynamisch unklar); tests/test_server.py:4341 (direkt/dynamisch unklar); tests/test_server.py:4354 (direkt/dynamisch unklar); tests/test_server.py:4364 (direkt/dynamisch unklar); tests/test_server.py:4379 (direkt/dynamisch unklar); tests/test_server.py:4393 (direkt/dynamisch unklar); tests/test_server.py:444 (direkt/dynamisch unklar); tests/test_server.py:4476 (direkt/dynamisch unklar); tests/test_server.py:4560 (direkt/dynamisch unklar); tests/test_server.py:4562 (direkt/dynamisch unklar); tests/test_server.py:4573 (direkt/dynamisch unklar); tests/test_server.py:4618 (direkt/dynamisch unklar); tests/test_server.py:4686 (direkt/dynamisch unklar); tests/test_server.py:4735 (direkt/dynamisch unklar); tests/test_server.py:4779 (direkt/dynamisch unklar); tests/test_server.py:4781 (direkt/dynamisch unklar); tests/test_server.py:4805 (direkt/dynamisch unklar); tests/test_server.py:4880 (direkt/dynamisch unklar); tests/test_server.py:4951 (direkt/dynamisch unklar); tests/test_server.py:5116 (direkt/dynamisch unklar); tests/test_server.py:5133 (direkt/dynamisch unklar); tests/test_server.py:533 (direkt/dynamisch unklar); tests/test_server.py:5339 (direkt/dynamisch unklar); tests/test_server.py:5346 (direkt/dynamisch unklar); tests/test_server.py:5356 (direkt/dynamisch unklar); tests/test_server.py:5358 (direkt/dynamisch unklar); tests/test_server.py:5507 (direkt/dynamisch unklar); tests/test_server.py:5620 (direkt/dynamisch unklar); tests/test_server.py:5672 (direkt/dynamisch unklar); tests/test_server.py:5685 (direkt/dynamisch unklar); tests/test_server.py:5893 (direkt/dynamisch unklar); tests/test_server.py:5999 (direkt/dynamisch unklar); tests/test_server.py:6003 (direkt/dynamisch unklar); tests/test_server.py:6012 (direkt/dynamisch unklar); tests/test_server.py:6016 (direkt/dynamisch unklar); tests/test_server.py:6034 (direkt/dynamisch unklar); tests/test_server.py:6045 (direkt/dynamisch unklar); tests/test_server.py:6512 (direkt/dynamisch unklar); tests/test_server.py:6525 (direkt/dynamisch unklar); tests/test_server.py:6537 (direkt/dynamisch unklar); tests/test_server.py:7460 (direkt/dynamisch unklar); tests/test_server.py:7467 (direkt/dynamisch unklar); tests/test_server.py:7725 (direkt/dynamisch unklar); tests/test_server.py:7733 (direkt/dynamisch unklar); tests/test_server.py:7753 (direkt/dynamisch unklar); tests/test_server.py:7789 (direkt/dynamisch unklar); tests/test_server.py:7823 (direkt/dynamisch unklar); tests/test_server.py:784 (direkt/dynamisch unklar); tests/test_server.py:7840 (direkt/dynamisch unklar); tests/test_server.py:8028 (direkt/dynamisch unklar); tests/test_server.py:803 (direkt/dynamisch unklar); tests/test_server.py:8049 (direkt/dynamisch unklar); tests/test_server.py:8063 (direkt/dynamisch unklar); tests/test_server.py:8070 (direkt/dynamisch unklar); tests/test_server.py:8099 (direkt/dynamisch unklar); tests/test_server.py:8154 (direkt/dynamisch unklar); tests/test_server.py:8178 (direkt/dynamisch unklar); tests/test_server.py:8208 (direkt/dynamisch unklar); tests/test_server.py:8221 (direkt/dynamisch unklar); tests/test_server.py:8224 (direkt/dynamisch unklar); tests/test_server.py:8316 (direkt/dynamisch unklar); tests/test_server.py:8325 (direkt/dynamisch unklar); tests/test_server.py:8328 (direkt/dynamisch unklar); tests/test_server.py:8331 (direkt/dynamisch unklar); tests/test_server.py:8409 (direkt/dynamisch unklar); tests/test_server.py:8458 (direkt/dynamisch unklar); tests/test_server.py:8479 (direkt/dynamisch unklar); tests/test_server.py:8579 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Importbindung | `ClientDisconnected` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8203 (direkt/dynamisch unklar); tests/test_server.py:8204 (direkt/dynamisch unklar); tests/test_server.py:8252 (direkt/dynamisch unklar) |
| Importbindung | `provider_error` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `public_app_error_status` | 45 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4561 (direkt/dynamisch unklar); tests/test_server.py:4562 (direkt/dynamisch unklar) |
| Importbindung | `app_config` | 66 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_audit_remediation.py:206 (direkt/dynamisch unklar); tests/test_provider_review.py:184 (direkt/dynamisch unklar); tests/test_provider_review.py:317 (direkt/dynamisch unklar); tests/test_server.py:217 (direkt/dynamisch unklar); tests/test_server.py:6568 (direkt/dynamisch unklar); tests/test_server.py:6575 (direkt/dynamisch unklar); tests/test_server.py:6584 (direkt/dynamisch unklar); tests/test_server.py:6600 (direkt/dynamisch unklar) |
| Importbindung | `observability` | 67 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar); tests/test_provider_review.py:32 (direkt/dynamisch unklar); tests/test_server.py:216 (direkt/dynamisch unklar); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7934 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8415 (direkt/dynamisch unklar); tests/test_server.py:8420 (direkt/dynamisch unklar); tests/test_server.py:8423 (direkt/dynamisch unklar) |
| Importbindung | `runtime_events` | 68 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `runtime_maintenance` | 69 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `sync_freshness` | 70 | `backend/sync` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8543 (direkt/dynamisch unklar); tests/test_server.py:8548 (direkt/dynamisch unklar) |
| Importbindung | `SettingsService` | 71 | `backend/settings` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `initialize_application_database` | 72 | `backend/db/bootstrap` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ActivityFeedbackRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1159 (direkt/dynamisch unklar) |
| Importbindung | `ChatRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1085 (direkt/dynamisch unklar) |
| Importbindung | `CheckinRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1093 (direkt/dynamisch unklar) |
| Importbindung | `CompetitionRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1125 (direkt/dynamisch unklar) |
| Importbindung | `KeyValueRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1076 (direkt/dynamisch unklar); tests/test_server.py:1110 (direkt/dynamisch unklar) |
| Importbindung | `PlanAdjustmentRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1149 (direkt/dynamisch unklar) |
| Importbindung | `ProfileRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1110 (direkt/dynamisch unklar) |
| Importbindung | `SnapshotRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1172 (direkt/dynamisch unklar) |
| Importbindung | `TrainingPlanRepository` | 73 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1134 (direkt/dynamisch unklar) |
| Importbindung | `DatabaseManager` | 74 | `backend/db/manager` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CURRENT_DATABASE_INDEXES` | 75 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:163 (direkt/dynamisch unklar) |
| Importbindung | `CURRENT_DATABASE_SCHEMA` | 75 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1540 (direkt/dynamisch unklar); tests/test_server.py:162 (direkt/dynamisch unklar) |
| Importbindung | `configure_cipher` | 75 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `database_index_names` | 75 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:163 (direkt/dynamisch unklar) |
| Importbindung | `database_schema_is_current` | 75 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `Config` | 82 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `DEFAULT_OPENAI_BASE_URL` | 82 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4727 (direkt/dynamisch unklar) |
| Importbindung | `load_config` | 82 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsReadTransport` | 83 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsWriteTransport` | 83 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `fetch_paged_collection` | 83 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `calendar_provider` | 84 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_provider` | 85 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_provider` | 86 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
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
| Importbindung | `response_json_bytes` | 138 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:7451 (direkt/dynamisch unklar) |
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
| Globale Bindung | `Garmin` | 158 | `sync/` | P6 | offen | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4113 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `sqlite_backend` | 163 | `db/` | P1 | offen | tests/test_server.py:1243 (direkt/dynamisch unklar); tests/test_server.py:6505 (direkt/dynamisch unklar); tests/test_server.py:6518 (direkt/dynamisch unklar) |
| Globale Bindung | `SQLCIPHER_AVAILABLE` | 164 | `db/` | P1 | offen | tests/test_audit_remediation.py:282 (direkt/dynamisch unklar); tests/test_provider_review.py:315 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:323 (direkt/dynamisch unklar); tests/test_server.py:2753 (direkt/dynamisch unklar); tests/test_server.py:3288 (direkt/dynamisch unklar); tests/test_server.py:6482 (direkt/dynamisch unklar) |
| Globale Bindung | `ROOT` | 170 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:6563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6583 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PUBLIC_DIR` | 171 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2411 (direkt/dynamisch unklar); tests/test_server.py:2412 (direkt/dynamisch unklar); tests/test_server.py:2428 (direkt/dynamisch unklar); tests/test_server.py:2429 (direkt/dynamisch unklar); tests/test_server.py:7249 (direkt/dynamisch unklar); tests/test_server.py:7250 (direkt/dynamisch unklar); tests/test_server.py:7261 (direkt/dynamisch unklar); tests/test_server.py:7262 (direkt/dynamisch unklar); tests/test_server.py:7270 (direkt/dynamisch unklar); tests/test_server.py:7271 (direkt/dynamisch unklar); tests/test_server.py:7279 (direkt/dynamisch unklar); tests/test_server.py:7280 (direkt/dynamisch unklar); tests/test_server.py:7286 (direkt/dynamisch unklar); tests/test_server.py:7287 (direkt/dynamisch unklar); tests/test_server.py:7296 (direkt/dynamisch unklar); tests/test_server.py:7297 (direkt/dynamisch unklar); tests/test_server.py:7298 (direkt/dynamisch unklar); tests/test_server.py:7299 (direkt/dynamisch unklar); tests/test_server.py:7510 (direkt/dynamisch unklar); tests/test_server.py:7529 (direkt/dynamisch unklar); tests/test_server.py:8554 (direkt/dynamisch unklar); tests/test_server.py:8555 (direkt/dynamisch unklar) |
| Globale Bindung | `DATA_DIR` | 172 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:112 (direkt/dynamisch unklar); tests/test_server.py:121 (direkt/dynamisch unklar); tests/test_server.py:177 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2758 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3299 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6488 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6583 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7934 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8423 (direkt/dynamisch unklar); tests/test_server.py:97 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 173 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:107 (direkt/dynamisch unklar); tests/test_server.py:111 (direkt/dynamisch unklar); tests/test_server.py:113 (direkt/dynamisch unklar); tests/test_server.py:122 (direkt/dynamisch unklar); tests/test_server.py:2758 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3299 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6488 (Monkeypatch/getattr/sys.modules); tests/test_server.py:98 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 174 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:30 (Monkeypatch/getattr/sys.modules); tests/test_server.py:108 (direkt/dynamisch unklar); tests/test_server.py:114 (direkt/dynamisch unklar); tests/test_server.py:123 (direkt/dynamisch unklar); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7934 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8423 (direkt/dynamisch unklar); tests/test_server.py:99 (direkt/dynamisch unklar) |
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
| Globale Bindung | `UUID_PATTERN` | 225 | `http_api/` | P10 | offen | tests/test_server.py:3124 (direkt/dynamisch unklar) |
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
| Globale Bindung | `APP_VERSION` | 240 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:7243 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 241 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 242 | `http_api/` | P10 | offen | tests/test_server.py:4782 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 243 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 244 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 245 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 246 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 247 | `coach/streams.py` | P8 | offen | tests/test_server.py:1511 (direkt/dynamisch unklar); tests/test_server.py:1521 (direkt/dynamisch unklar); tests/test_server.py:1522 (direkt/dynamisch unklar) |
| Globale Bindung | `CALENDAR_FETCH_TIMEOUT_SECONDS` | 248 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_CONNECTION_TIMEOUT_SECONDS` | 249 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_EXTERNAL_RESPONSE_BYTES` | 250 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_DEFAULT_MAX_OUTPUT_TOKENS` | 254 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LONG_PLAN_MAX_OUTPUT_TOKENS` | 255 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_FOLLOWUP_MAX_OUTPUT_TOKENS` | 256 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_TIMEOUT_SECONDS` | 257 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MESSAGE_ATTACHMENTS_QUERY` | 258 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_BASE_URL` | 259 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 260 | `providers/` | P2 | offen | tests/test_server.py:5768 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 261 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 262 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 263 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 264 | `coach/` | P7 | offen | tests/test_server.py:4810 (direkt/dynamisch unklar); tests/test_server.py:5136 (direkt/dynamisch unklar); tests/test_server.py:5144 (direkt/dynamisch unklar); tests/test_server.py:5496 (direkt/dynamisch unklar); tests/test_server.py:5626 (direkt/dynamisch unklar); tests/test_server.py:5636 (direkt/dynamisch unklar); tests/test_server.py:5638 (direkt/dynamisch unklar); tests/test_server.py:5641 (direkt/dynamisch unklar); tests/test_server.py:5644 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5658 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 265 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 266 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:150 (direkt/dynamisch unklar); tests/test_audit_remediation.py:156 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:199 (direkt/dynamisch unklar); tests/test_audit_remediation.py:32 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:73 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1056 (direkt/dynamisch unklar); tests/test_server.py:128 (direkt/dynamisch unklar); tests/test_server.py:1330 (direkt/dynamisch unklar); tests/test_server.py:1335 (direkt/dynamisch unklar); tests/test_server.py:1338 (direkt/dynamisch unklar); tests/test_server.py:1356 (direkt/dynamisch unklar); tests/test_server.py:1359 (direkt/dynamisch unklar); tests/test_server.py:1363 (direkt/dynamisch unklar); tests/test_server.py:1440 (direkt/dynamisch unklar); tests/test_server.py:1552 (direkt/dynamisch unklar); tests/test_server.py:159 (direkt/dynamisch unklar); tests/test_server.py:1689 (direkt/dynamisch unklar); tests/test_server.py:2441 (direkt/dynamisch unklar); tests/test_server.py:2502 (direkt/dynamisch unklar); tests/test_server.py:2515 (direkt/dynamisch unklar); tests/test_server.py:2571 (direkt/dynamisch unklar); tests/test_server.py:2594 (direkt/dynamisch unklar); tests/test_server.py:2723 (direkt/dynamisch unklar); tests/test_server.py:2736 (direkt/dynamisch unklar); tests/test_server.py:2741 (direkt/dynamisch unklar); tests/test_server.py:2939 (direkt/dynamisch unklar); tests/test_server.py:3019 (direkt/dynamisch unklar); tests/test_server.py:4542 (direkt/dynamisch unklar); tests/test_server.py:4829 (direkt/dynamisch unklar); tests/test_server.py:4961 (direkt/dynamisch unklar); tests/test_server.py:4984 (direkt/dynamisch unklar); tests/test_server.py:5007 (direkt/dynamisch unklar); tests/test_server.py:5029 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5049 (direkt/dynamisch unklar); tests/test_server.py:5066 (direkt/dynamisch unklar); tests/test_server.py:5074 (direkt/dynamisch unklar); tests/test_server.py:5396 (direkt/dynamisch unklar); tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:5526 (direkt/dynamisch unklar); tests/test_server.py:5549 (direkt/dynamisch unklar); tests/test_server.py:5791 (direkt/dynamisch unklar); tests/test_server.py:5803 (direkt/dynamisch unklar); tests/test_server.py:5822 (direkt/dynamisch unklar); tests/test_server.py:5896 (direkt/dynamisch unklar); tests/test_server.py:5918 (direkt/dynamisch unklar); tests/test_server.py:5927 (direkt/dynamisch unklar); tests/test_server.py:6052 (direkt/dynamisch unklar); tests/test_server.py:6344 (direkt/dynamisch unklar); tests/test_server.py:640 (direkt/dynamisch unklar); tests/test_server.py:6407 (direkt/dynamisch unklar); tests/test_server.py:6452 (direkt/dynamisch unklar); tests/test_server.py:6491 (direkt/dynamisch unklar); tests/test_server.py:6500 (direkt/dynamisch unklar); tests/test_server.py:6676 (direkt/dynamisch unklar); tests/test_server.py:6685 (direkt/dynamisch unklar); tests/test_server.py:6695 (direkt/dynamisch unklar); tests/test_server.py:684 (direkt/dynamisch unklar); tests/test_server.py:6846 (direkt/dynamisch unklar); tests/test_server.py:695 (direkt/dynamisch unklar); tests/test_server.py:709 (direkt/dynamisch unklar); tests/test_server.py:7640 (direkt/dynamisch unklar); tests/test_server.py:8391 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8396 (direkt/dynamisch unklar); tests/test_server.py:8532 (direkt/dynamisch unklar); tests/test_server.py:8546 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 267 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7650 (direkt/dynamisch unklar); tests/test_server.py:7662 (direkt/dynamisch unklar); tests/test_server.py:7665 (direkt/dynamisch unklar); tests/test_server.py:7678 (direkt/dynamisch unklar); tests/test_server.py:7679 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 268 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 269 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 270 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 271 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 272 | `performance/` | P3 | offen | tests/test_server.py:648 (direkt/dynamisch unklar); tests/test_server.py:654 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 273 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 274 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 275 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:154 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 276 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8309 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 277 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8309 (direkt/dynamisch unklar); tests/test_server.py:8322 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 278 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 279 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 280 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 281 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 282 | `coach/jobs.py` | P8 | offen | tests/test_server.py:240 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 283 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:155 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 284 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:300 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 285 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 286 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 287 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 288 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 289 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 290 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 291 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 292 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5803 (direkt/dynamisch unklar); tests/test_server.py:5822 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 293 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LOCK` | 294 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7902 (direkt/dynamisch unklar); tests/test_server.py:7908 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 295 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7903 (direkt/dynamisch unklar); tests/test_server.py:7904 (direkt/dynamisch unklar); tests/test_server.py:7909 (direkt/dynamisch unklar); tests/test_server.py:7910 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 296 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 297 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 298 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 299 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Klasse | `ProviderResyncGate` | 302 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 349 | `sync/` | P6 | offen | tests/test_server.py:6530 (direkt/dynamisch unklar); tests/test_server.py:6545 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 350 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 353 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 358 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 366 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `CONFIG` | 374 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:154 (direkt/dynamisch unklar); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (direkt/dynamisch unklar); tests/test_provider_review.py:196 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:314 (direkt/dynamisch unklar); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:327 (direkt/dynamisch unklar); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1019 (direkt/dynamisch unklar); tests/test_server.py:1020 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1028 (direkt/dynamisch unklar); tests/test_server.py:1029 (Monkeypatch/getattr/sys.modules); tests/test_server.py:103 (direkt/dynamisch unklar); tests/test_server.py:120 (direkt/dynamisch unklar); tests/test_server.py:1243 (direkt/dynamisch unklar); tests/test_server.py:1314 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1314 (direkt/dynamisch unklar); tests/test_server.py:175 (direkt/dynamisch unklar); tests/test_server.py:177 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2446 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2446 (direkt/dynamisch unklar); tests/test_server.py:2532 (direkt/dynamisch unklar); tests/test_server.py:2533 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2561 (direkt/dynamisch unklar); tests/test_server.py:2562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2576 (direkt/dynamisch unklar); tests/test_server.py:2577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2644 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2644 (direkt/dynamisch unklar); tests/test_server.py:2739 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2739 (direkt/dynamisch unklar); tests/test_server.py:2748 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2748 (direkt/dynamisch unklar); tests/test_server.py:2757 (direkt/dynamisch unklar); tests/test_server.py:2758 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3298 (direkt/dynamisch unklar); tests/test_server.py:3299 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3540 (direkt/dynamisch unklar); tests/test_server.py:3613 (direkt/dynamisch unklar); tests/test_server.py:3633 (direkt/dynamisch unklar); tests/test_server.py:3644 (direkt/dynamisch unklar); tests/test_server.py:3663 (direkt/dynamisch unklar); tests/test_server.py:3839 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3839 (direkt/dynamisch unklar); tests/test_server.py:3857 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3857 (direkt/dynamisch unklar); tests/test_server.py:3867 (direkt/dynamisch unklar); tests/test_server.py:4112 (direkt/dynamisch unklar); tests/test_server.py:4113 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4180 (direkt/dynamisch unklar); tests/test_server.py:4188 (direkt/dynamisch unklar); tests/test_server.py:4280 (direkt/dynamisch unklar); tests/test_server.py:4282 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4325 (direkt/dynamisch unklar); tests/test_server.py:4326 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4350 (direkt/dynamisch unklar); tests/test_server.py:4351 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4474 (direkt/dynamisch unklar); tests/test_server.py:4475 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4489 (direkt/dynamisch unklar); tests/test_server.py:4490 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4500 (direkt/dynamisch unklar); tests/test_server.py:4501 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4515 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4515 (direkt/dynamisch unklar); tests/test_server.py:4519 (direkt/dynamisch unklar); tests/test_server.py:4521 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4529 (direkt/dynamisch unklar); tests/test_server.py:4534 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4553 (direkt/dynamisch unklar); tests/test_server.py:4554 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4704 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4704 (direkt/dynamisch unklar); tests/test_server.py:4722 (direkt/dynamisch unklar); tests/test_server.py:4723 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4726 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4726 (direkt/dynamisch unklar); tests/test_server.py:4734 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4734 (direkt/dynamisch unklar); tests/test_server.py:4746 (direkt/dynamisch unklar); tests/test_server.py:4747 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4770 (direkt/dynamisch unklar); tests/test_server.py:4771 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4777 (direkt/dynamisch unklar); tests/test_server.py:4778 (Monkeypatch/getattr/sys.modules); tests/test_server.py:59 (direkt/dynamisch unklar); tests/test_server.py:5969 (direkt/dynamisch unklar); tests/test_server.py:5971 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5983 (direkt/dynamisch unklar); tests/test_server.py:5984 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5998 (direkt/dynamisch unklar); tests/test_server.py:60 (direkt/dynamisch unklar); tests/test_server.py:6000 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6010 (direkt/dynamisch unklar); tests/test_server.py:6013 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6023 (direkt/dynamisch unklar); tests/test_server.py:6031 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6043 (direkt/dynamisch unklar); tests/test_server.py:6044 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6071 (direkt/dynamisch unklar); tests/test_server.py:6072 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6111 (direkt/dynamisch unklar); tests/test_server.py:6112 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6133 (direkt/dynamisch unklar); tests/test_server.py:6134 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6155 (direkt/dynamisch unklar); tests/test_server.py:6156 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6174 (direkt/dynamisch unklar); tests/test_server.py:6175 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6194 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6194 (direkt/dynamisch unklar); tests/test_server.py:6248 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6248 (direkt/dynamisch unklar); tests/test_server.py:6257 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6257 (direkt/dynamisch unklar); tests/test_server.py:6276 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6276 (direkt/dynamisch unklar); tests/test_server.py:6285 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6285 (direkt/dynamisch unklar); tests/test_server.py:6294 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6294 (direkt/dynamisch unklar); tests/test_server.py:630 (direkt/dynamisch unklar); tests/test_server.py:6302 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6302 (direkt/dynamisch unklar); tests/test_server.py:631 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6319 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6319 (direkt/dynamisch unklar); tests/test_server.py:6363 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6363 (direkt/dynamisch unklar); tests/test_server.py:6395 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6395 (direkt/dynamisch unklar); tests/test_server.py:6441 (direkt/dynamisch unklar); tests/test_server.py:6466 (direkt/dynamisch unklar); tests/test_server.py:647 (direkt/dynamisch unklar); tests/test_server.py:6474 (direkt/dynamisch unklar); tests/test_server.py:6475 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6486 (direkt/dynamisch unklar); tests/test_server.py:6488 (Monkeypatch/getattr/sys.modules); tests/test_server.py:650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6533 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6533 (direkt/dynamisch unklar); tests/test_server.py:6553 (direkt/dynamisch unklar); tests/test_server.py:6554 (Monkeypatch/getattr/sys.modules); tests/test_server.py:658 (direkt/dynamisch unklar); tests/test_server.py:659 (Monkeypatch/getattr/sys.modules); tests/test_server.py:671 (direkt/dynamisch unklar); tests/test_server.py:672 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6731 (direkt/dynamisch unklar); tests/test_server.py:6763 (direkt/dynamisch unklar); tests/test_server.py:6801 (direkt/dynamisch unklar); tests/test_server.py:6833 (direkt/dynamisch unklar); tests/test_server.py:6849 (direkt/dynamisch unklar); tests/test_server.py:6888 (direkt/dynamisch unklar); tests/test_server.py:6921 (direkt/dynamisch unklar); tests/test_server.py:6948 (direkt/dynamisch unklar); tests/test_server.py:7231 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7231 (direkt/dynamisch unklar); tests/test_server.py:7698 (direkt/dynamisch unklar); tests/test_server.py:7702 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7723 (direkt/dynamisch unklar); tests/test_server.py:7724 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7748 (direkt/dynamisch unklar); tests/test_server.py:7752 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7852 (direkt/dynamisch unklar); tests/test_server.py:7853 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7862 (direkt/dynamisch unklar); tests/test_server.py:7863 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7933 (direkt/dynamisch unklar); tests/test_server.py:7935 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8097 (direkt/dynamisch unklar); tests/test_server.py:8098 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8337 (direkt/dynamisch unklar); tests/test_server.py:8338 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8407 (direkt/dynamisch unklar); tests/test_server.py:8408 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8502 (direkt/dynamisch unklar); tests/test_server.py:8509 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8520 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8576 (direkt/dynamisch unklar); tests/test_server.py:8577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:96 (direkt/dynamisch unklar) |
| Klasse | `IntervalsClient` | 377 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:44 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:55 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:71 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:81 (direkt/dynamisch unklar); tests/test_server.py:3540 (direkt/dynamisch unklar); tests/test_server.py:3613 (direkt/dynamisch unklar); tests/test_server.py:3633 (direkt/dynamisch unklar); tests/test_server.py:3644 (direkt/dynamisch unklar); tests/test_server.py:3663 (direkt/dynamisch unklar); tests/test_server.py:3735 (direkt/dynamisch unklar); tests/test_server.py:3763 (direkt/dynamisch unklar); tests/test_server.py:3794 (direkt/dynamisch unklar); tests/test_server.py:3795 (direkt/dynamisch unklar); tests/test_server.py:3796 (direkt/dynamisch unklar); tests/test_server.py:3814 (direkt/dynamisch unklar); tests/test_server.py:3858 (direkt/dynamisch unklar); tests/test_server.py:3859 (direkt/dynamisch unklar); tests/test_server.py:3867 (direkt/dynamisch unklar); tests/test_server.py:4180 (direkt/dynamisch unklar); tests/test_server.py:4188 (direkt/dynamisch unklar); tests/test_server.py:5972 (direkt/dynamisch unklar); tests/test_server.py:5985 (direkt/dynamisch unklar); tests/test_server.py:6001 (direkt/dynamisch unklar); tests/test_server.py:6014 (direkt/dynamisch unklar); tests/test_server.py:6032 (direkt/dynamisch unklar); tests/test_server.py:6073 (direkt/dynamisch unklar); tests/test_server.py:6074 (direkt/dynamisch unklar); tests/test_server.py:6113 (direkt/dynamisch unklar); tests/test_server.py:6135 (direkt/dynamisch unklar); tests/test_server.py:6157 (direkt/dynamisch unklar); tests/test_server.py:6158 (direkt/dynamisch unklar); tests/test_server.py:6176 (direkt/dynamisch unklar); tests/test_server.py:6377 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6440 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6465 (Monkeypatch/getattr/sys.modules); tests/test_server.py:660 (direkt/dynamisch unklar); tests/test_server.py:673 (direkt/dynamisch unklar); tests/test_server.py:6730 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6762 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6800 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6832 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6848 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6887 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6920 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6947 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7230 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7620 (direkt/dynamisch unklar); tests/test_server.py:7936 (direkt/dynamisch unklar); tests/test_server.py:7937 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 680 | `observability.py` | P1 | offen | tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:23 (direkt/dynamisch unklar); tests/test_provider_review.py:31 (direkt/dynamisch unklar); tests/test_provider_review.py:40 (direkt/dynamisch unklar); tests/test_provider_review.py:42 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_server.py:7443 (direkt/dynamisch unklar); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7687 (direkt/dynamisch unklar); tests/test_server.py:7688 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7773 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7825 (direkt/dynamisch unklar); tests/test_server.py:7934 (direkt/dynamisch unklar); tests/test_server.py:7939 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:7970 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8423 (direkt/dynamisch unklar); tests/test_server.py:8430 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTOR` | 681 | `observability.py` | P1 | offen | tests/test_server.py:4516 (direkt/dynamisch unklar); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7713 (direkt/dynamisch unklar); tests/test_server.py:7751 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7934 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8423 (direkt/dynamisch unklar) |
| Funktion | `external_call` | 684 | `providers/http.py` | P2 | offen | tests/test_server.py:1782 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7726 (direkt/dynamisch unklar); tests/test_server.py:7802 (direkt/dynamisch unklar); tests/test_server.py:7817 (direkt/dynamisch unklar); tests/test_server.py:8424 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 747 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 766 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 767 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 768 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 769 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 770 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 771 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 772 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 773 | `weather/` | P3 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_server.py:1231 (direkt/dynamisch unklar); tests/test_server.py:1233 (direkt/dynamisch unklar); tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:1260 (direkt/dynamisch unklar); tests/test_server.py:1437 (direkt/dynamisch unklar); tests/test_server.py:1575 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 774 | `weather/` | P3 | offen | tests/test_audit_remediation.py:122 (direkt/dynamisch unklar); tests/test_audit_remediation.py:85 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 775 | `history/` | P5 | offen | tests/test_server.py:4122 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 776 | `weather/` | P3 | offen | tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:1306 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 777 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 778 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 779 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 780 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 781 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 811 | `weather/` | P3 | offen | tests/test_server.py:7376 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 843 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `serialise_conversation` | 876 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8312 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 893 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:186 (direkt/dynamisch unklar); tests/test_audit_remediation.py:201 (direkt/dynamisch unklar); tests/test_audit_remediation.py:69 (direkt/dynamisch unklar); tests/test_audit_remediation.py:81 (direkt/dynamisch unklar); tests/test_audit_remediation.py:95 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1055 (direkt/dynamisch unklar); tests/test_server.py:1206 (direkt/dynamisch unklar); tests/test_server.py:1209 (direkt/dynamisch unklar); tests/test_server.py:1277 (direkt/dynamisch unklar); tests/test_server.py:1296 (direkt/dynamisch unklar); tests/test_server.py:1443 (direkt/dynamisch unklar); tests/test_server.py:1447 (direkt/dynamisch unklar); tests/test_server.py:1563 (direkt/dynamisch unklar); tests/test_server.py:1692 (direkt/dynamisch unklar); tests/test_server.py:2444 (direkt/dynamisch unklar); tests/test_server.py:2505 (direkt/dynamisch unklar); tests/test_server.py:2518 (direkt/dynamisch unklar); tests/test_server.py:2574 (direkt/dynamisch unklar); tests/test_server.py:2597 (direkt/dynamisch unklar); tests/test_server.py:2726 (direkt/dynamisch unklar); tests/test_server.py:3022 (direkt/dynamisch unklar); tests/test_server.py:3026 (direkt/dynamisch unklar); tests/test_server.py:4963 (direkt/dynamisch unklar); tests/test_server.py:4986 (direkt/dynamisch unklar); tests/test_server.py:5009 (direkt/dynamisch unklar); tests/test_server.py:5031 (direkt/dynamisch unklar); tests/test_server.py:5052 (direkt/dynamisch unklar); tests/test_server.py:5076 (direkt/dynamisch unklar); tests/test_server.py:5527 (direkt/dynamisch unklar); tests/test_server.py:5551 (direkt/dynamisch unklar); tests/test_server.py:5806 (direkt/dynamisch unklar); tests/test_server.py:5825 (direkt/dynamisch unklar); tests/test_server.py:7641 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 897 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 898 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 899 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 900 | `planning/` | P4 | offen | tests/test_server.py:4962 (direkt/dynamisch unklar); tests/test_server.py:4985 (direkt/dynamisch unklar); tests/test_server.py:5008 (direkt/dynamisch unklar); tests/test_server.py:5030 (direkt/dynamisch unklar); tests/test_server.py:5044 (direkt/dynamisch unklar); tests/test_server.py:5051 (direkt/dynamisch unklar); tests/test_server.py:5067 (direkt/dynamisch unklar); tests/test_server.py:5075 (direkt/dynamisch unklar); tests/test_server.py:5527 (direkt/dynamisch unklar); tests/test_server.py:5550 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 901 | `planning/` | P4 | offen | tests/test_server.py:7641 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 902 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4464 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 903 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 904 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 905 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CONTEXT` | 908 | `observability.py` | P1 | offen | tests/test_server.py:7920 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 909 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:335 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:184 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 910 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:336 (direkt/dynamisch unklar); tests/test_provider_review.py:49 (direkt/dynamisch unklar); tests/test_server.py:185 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 912 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 913 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 914 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 915 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 916 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 917 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 918 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 919 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 920 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 921 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 922 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 925 | `history/` | P5 | offen | tests/test_server.py:5496 (direkt/dynamisch unklar); tests/test_server.py:5507 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 926 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 927 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 928 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 929 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 934 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 939 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 944 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 948 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 950 | `planning/` | P4 | offen | tests/test_server.py:408 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 951 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 952 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 955 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 966 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 972 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 981 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 991 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1018 | `observability.py` | P1 | offen | tests/test_server.py:7917 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1039 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1082 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:297 (direkt/dynamisch unklar); tests/test_provider_review.py:187 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:197 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_provider_review.py:334 (direkt/dynamisch unklar); tests/test_server.py:182 (direkt/dynamisch unklar) |
| Funktion | `database` | 1109 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:150 (direkt/dynamisch unklar); tests/test_audit_remediation.py:156 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:199 (direkt/dynamisch unklar); tests/test_audit_remediation.py:32 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:73 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1056 (direkt/dynamisch unklar); tests/test_server.py:1077 (direkt/dynamisch unklar); tests/test_server.py:1086 (direkt/dynamisch unklar); tests/test_server.py:1100 (direkt/dynamisch unklar); tests/test_server.py:1112 (direkt/dynamisch unklar); tests/test_server.py:1126 (direkt/dynamisch unklar); tests/test_server.py:1135 (direkt/dynamisch unklar); tests/test_server.py:1144 (direkt/dynamisch unklar); tests/test_server.py:1151 (direkt/dynamisch unklar); tests/test_server.py:1162 (direkt/dynamisch unklar); tests/test_server.py:1173 (direkt/dynamisch unklar); tests/test_server.py:128 (direkt/dynamisch unklar); tests/test_server.py:1330 (direkt/dynamisch unklar); tests/test_server.py:1335 (direkt/dynamisch unklar); tests/test_server.py:1338 (direkt/dynamisch unklar); tests/test_server.py:1356 (direkt/dynamisch unklar); tests/test_server.py:1359 (direkt/dynamisch unklar); tests/test_server.py:1363 (direkt/dynamisch unklar); tests/test_server.py:1440 (direkt/dynamisch unklar); tests/test_server.py:1552 (direkt/dynamisch unklar); tests/test_server.py:159 (direkt/dynamisch unklar); tests/test_server.py:1689 (direkt/dynamisch unklar); tests/test_server.py:2441 (direkt/dynamisch unklar); tests/test_server.py:2502 (direkt/dynamisch unklar); tests/test_server.py:2515 (direkt/dynamisch unklar); tests/test_server.py:2571 (direkt/dynamisch unklar); tests/test_server.py:2594 (direkt/dynamisch unklar); tests/test_server.py:2723 (direkt/dynamisch unklar); tests/test_server.py:2736 (direkt/dynamisch unklar); tests/test_server.py:2741 (direkt/dynamisch unklar); tests/test_server.py:2760 (direkt/dynamisch unklar); tests/test_server.py:2939 (direkt/dynamisch unklar); tests/test_server.py:3019 (direkt/dynamisch unklar); tests/test_server.py:3307 (direkt/dynamisch unklar); tests/test_server.py:4463 (direkt/dynamisch unklar); tests/test_server.py:4542 (direkt/dynamisch unklar); tests/test_server.py:4829 (direkt/dynamisch unklar); tests/test_server.py:4961 (direkt/dynamisch unklar); tests/test_server.py:4984 (direkt/dynamisch unklar); tests/test_server.py:5007 (direkt/dynamisch unklar); tests/test_server.py:5029 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5049 (direkt/dynamisch unklar); tests/test_server.py:5066 (direkt/dynamisch unklar); tests/test_server.py:5074 (direkt/dynamisch unklar); tests/test_server.py:5396 (direkt/dynamisch unklar); tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:5526 (direkt/dynamisch unklar); tests/test_server.py:5549 (direkt/dynamisch unklar); tests/test_server.py:5791 (direkt/dynamisch unklar); tests/test_server.py:5803 (direkt/dynamisch unklar); tests/test_server.py:5822 (direkt/dynamisch unklar); tests/test_server.py:5896 (direkt/dynamisch unklar); tests/test_server.py:5918 (direkt/dynamisch unklar); tests/test_server.py:5927 (direkt/dynamisch unklar); tests/test_server.py:6052 (direkt/dynamisch unklar); tests/test_server.py:6344 (direkt/dynamisch unklar); tests/test_server.py:640 (direkt/dynamisch unklar); tests/test_server.py:6407 (direkt/dynamisch unklar); tests/test_server.py:6452 (direkt/dynamisch unklar); tests/test_server.py:6491 (direkt/dynamisch unklar); tests/test_server.py:6500 (direkt/dynamisch unklar); tests/test_server.py:6676 (direkt/dynamisch unklar); tests/test_server.py:6685 (direkt/dynamisch unklar); tests/test_server.py:6695 (direkt/dynamisch unklar); tests/test_server.py:684 (direkt/dynamisch unklar); tests/test_server.py:6846 (direkt/dynamisch unklar); tests/test_server.py:695 (direkt/dynamisch unklar); tests/test_server.py:709 (direkt/dynamisch unklar); tests/test_server.py:7640 (direkt/dynamisch unklar); tests/test_server.py:7879 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8262 (direkt/dynamisch unklar); tests/test_server.py:8396 (direkt/dynamisch unklar); tests/test_server.py:8532 (direkt/dynamisch unklar); tests/test_server.py:8546 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1115 | `db/bootstrap.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:288 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:37 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:115 (direkt/dynamisch unklar); tests/test_server.py:1215 (direkt/dynamisch unklar); tests/test_server.py:158 (direkt/dynamisch unklar); tests/test_server.py:181 (direkt/dynamisch unklar); tests/test_server.py:201 (direkt/dynamisch unklar); tests/test_server.py:209 (direkt/dynamisch unklar); tests/test_server.py:218 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2740 (direkt/dynamisch unklar); tests/test_server.py:2749 (direkt/dynamisch unklar); tests/test_server.py:2759 (direkt/dynamisch unklar); tests/test_server.py:3300 (direkt/dynamisch unklar); tests/test_server.py:6489 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1127 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1135 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8514 (direkt/dynamisch unklar); tests/test_server.py:8530 (direkt/dynamisch unklar); tests/test_server.py:8544 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1147 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8515 (direkt/dynamisch unklar); tests/test_server.py:8531 (direkt/dynamisch unklar); tests/test_server.py:8545 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1181 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1196 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1210 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1219 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1233 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1246 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1256 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1265 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1275 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1282 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1307 | `sync/` | P6 | offen | tests/test_audit_remediation.py:294 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:253 (direkt/dynamisch unklar); tests/test_server.py:255 (direkt/dynamisch unklar); tests/test_server.py:259 (direkt/dynamisch unklar); tests/test_server.py:270 (direkt/dynamisch unklar); tests/test_server.py:303 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1316 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:142 (direkt/dynamisch unklar); tests/test_provider_review.py:179 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1322 | `sync/` | P6 | offen | tests/test_server.py:1020 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1029 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1327 | `sync/` | P6 | offen | tests/test_server.py:651 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1350 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1358 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1367 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1385 | `sync/` | P6 | offen | tests/test_server.py:663 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1412 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1421 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1428 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1438 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 1463 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 1477 | `sync/` | P6 | offen | tests/test_audit_remediation.py:256 (direkt/dynamisch unklar); tests/test_audit_remediation.py:289 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:1031 (Monkeypatch/getattr/sys.modules); tests/test_server.py:248 (direkt/dynamisch unklar); tests/test_server.py:265 (direkt/dynamisch unklar); tests/test_server.py:292 (direkt/dynamisch unklar); tests/test_server.py:389 (Monkeypatch/getattr/sys.modules); tests/test_server.py:476 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4802 (direkt/dynamisch unklar); tests/test_server.py:4806 (direkt/dynamisch unklar); tests/test_server.py:572 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6251 (direkt/dynamisch unklar); tests/test_server.py:6260 (direkt/dynamisch unklar); tests/test_server.py:6279 (direkt/dynamisch unklar); tests/test_server.py:6288 (direkt/dynamisch unklar); tests/test_server.py:632 (direkt/dynamisch unklar); tests/test_server.py:635 (direkt/dynamisch unklar); tests/test_server.py:650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8524 (direkt/dynamisch unklar); tests/test_server.py:912 (Monkeypatch/getattr/sys.modules); tests/test_server.py:938 (Monkeypatch/getattr/sys.modules); tests/test_server.py:983 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 1504 | `sync/` | P6 | offen | tests/test_server.py:206 (Monkeypatch/getattr/sys.modules); tests/test_server.py:236 (Monkeypatch/getattr/sys.modules); tests/test_server.py:254 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 1524 | `sync/` | P6 | offen | tests/test_audit_remediation.py:290 (direkt/dynamisch unklar); tests/test_audit_remediation.py:295 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:154 (direkt/dynamisch unklar); tests/test_server.py:251 (direkt/dynamisch unklar); tests/test_server.py:256 (direkt/dynamisch unklar); tests/test_server.py:266 (direkt/dynamisch unklar); tests/test_server.py:299 (direkt/dynamisch unklar); tests/test_server.py:6252 (direkt/dynamisch unklar); tests/test_server.py:6261 (direkt/dynamisch unklar); tests/test_server.py:6280 (direkt/dynamisch unklar); tests/test_server.py:6289 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 1545 | `sync/` | P6 | offen | tests/test_audit_remediation.py:257 (direkt/dynamisch unklar); tests/test_audit_remediation.py:292 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 1583 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 1589 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 1600 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 1620 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 1635 | `sync/jobs.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 1652 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 1665 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 1674 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 1681 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 1698 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 1710 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 1722 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:138 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:167 (Monkeypatch/getattr/sys.modules); tests/test_server.py:257 (Monkeypatch/getattr/sys.modules); tests/test_server.py:268 (Monkeypatch/getattr/sys.modules); tests/test_server.py:281 (direkt/dynamisch unklar); tests/test_server.py:301 (Monkeypatch/getattr/sys.modules); tests/test_server.py:598 (direkt/dynamisch unklar); tests/test_server.py:599 (direkt/dynamisch unklar); tests/test_server.py:611 (direkt/dynamisch unklar); tests/test_server.py:624 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 1745 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 1754 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 1774 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 1794 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 1812 | `sync/` | P6 | offen | tests/test_provider_review.py:139 (direkt/dynamisch unklar); tests/test_provider_review.py:168 (direkt/dynamisch unklar); tests/test_server.py:258 (direkt/dynamisch unklar); tests/test_server.py:269 (direkt/dynamisch unklar); tests/test_server.py:302 (direkt/dynamisch unklar); tests/test_server.py:6252 (direkt/dynamisch unklar); tests/test_server.py:6261 (direkt/dynamisch unklar); tests/test_server.py:6280 (direkt/dynamisch unklar); tests/test_server.py:6289 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 1822 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 1837 | `sync/` | P6 | offen | tests/test_server.py:241 (direkt/dynamisch unklar) |
| Funktion | `resolve_sync_job` | 1848 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_current_provider_freshness` | 1871 | `sync/freshness.py` | P6 | offen | tests/test_server.py:6049 (direkt/dynamisch unklar); tests/test_server.py:8511 (direkt/dynamisch unklar); tests/test_server.py:8516 (direkt/dynamisch unklar); tests/test_server.py:8521 (direkt/dynamisch unklar); tests/test_server.py:8528 (direkt/dynamisch unklar); tests/test_server.py:8538 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 1885 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 1899 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 1910 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 1934 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 1939 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 1951 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 1961 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 1978 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2017 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2049 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3067 (direkt/dynamisch unklar); tests/test_server.py:5479 (direkt/dynamisch unklar); tests/test_server.py:5568 (direkt/dynamisch unklar); tests/test_server.py:5617 (direkt/dynamisch unklar); tests/test_server.py:8465 (direkt/dynamisch unklar); tests/test_server.py:8485 (direkt/dynamisch unklar); tests/test_server.py:8494 (direkt/dynamisch unklar); tests/test_server.py:8497 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2060 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2072 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2086 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2102 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8474 (direkt/dynamisch unklar); tests/test_server.py:8480 (direkt/dynamisch unklar); tests/test_server.py:8486 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2140 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2160 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2170 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2195 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2216 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2226 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2235 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2261 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2277 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2297 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2306 | `history/` | P5 | offen | tests/test_server.py:3074 (direkt/dynamisch unklar); tests/test_server.py:5486 (direkt/dynamisch unklar); tests/test_server.py:5621 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2321 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:122 (direkt/dynamisch unklar); tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_audit_remediation.py:303 (direkt/dynamisch unklar); tests/test_audit_remediation.py:304 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_audit_remediation.py:85 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar); tests/test_provider_review.py:337 (direkt/dynamisch unklar); tests/test_server.py:1233 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1260 (direkt/dynamisch unklar); tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:1306 (direkt/dynamisch unklar); tests/test_server.py:202 (direkt/dynamisch unklar); tests/test_server.py:203 (direkt/dynamisch unklar); tests/test_server.py:2750 (direkt/dynamisch unklar); tests/test_server.py:2751 (direkt/dynamisch unklar); tests/test_server.py:4073 (direkt/dynamisch unklar); tests/test_server.py:4074 (direkt/dynamisch unklar); tests/test_server.py:4357 (direkt/dynamisch unklar); tests/test_server.py:4480 (direkt/dynamisch unklar); tests/test_server.py:6006 (direkt/dynamisch unklar); tests/test_server.py:6018 (direkt/dynamisch unklar); tests/test_server.py:6019 (direkt/dynamisch unklar); tests/test_server.py:6122 (direkt/dynamisch unklar); tests/test_server.py:6141 (direkt/dynamisch unklar); tests/test_server.py:6145 (direkt/dynamisch unklar); tests/test_server.py:6480 (direkt/dynamisch unklar); tests/test_server.py:6499 (direkt/dynamisch unklar); tests/test_server.py:6557 (direkt/dynamisch unklar); tests/test_server.py:7652 (direkt/dynamisch unklar); tests/test_server.py:7670 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 2328 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 2329 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 2330 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 2331 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 2332 | `planning/` | P4 | offen | tests/test_server.py:2616 (direkt/dynamisch unklar); tests/test_server.py:2626 (direkt/dynamisch unklar); tests/test_server.py:2651 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 2333 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 2334 | `planning/` | P4 | offen | tests/test_server.py:2361 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 2335 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 2338 | `planning/` | P4 | offen | tests/test_server.py:3558 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 2339 | `planning/` | P4 | offen | tests/test_server.py:3559 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 2340 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 2341 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 2342 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 2343 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 2344 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 2345 | `coach/` | P7 | offen | tests/test_server.py:5257 (direkt/dynamisch unklar); tests/test_server.py:5268 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 2346 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 2359 | `sync/` | P6 | offen | tests/test_server.py:5943 (direkt/dynamisch unklar); tests/test_server.py:5945 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 2370 | `sync/` | P6 | offen | tests/test_server.py:5942 (direkt/dynamisch unklar); tests/test_server.py:5944 (direkt/dynamisch unklar); tests/test_server.py:5970 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 2382 | `sync/` | P6 | offen | tests/test_server.py:5946 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 2393 | `settings.py` | P1 | offen | tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:223 (direkt/dynamisch unklar); tests/test_provider_review.py:247 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 2398 | `settings.py` | P1 | offen | tests/test_provider_review.py:210 (direkt/dynamisch unklar); tests/test_provider_review.py:211 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 2404 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_server.py:1231 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:1436 (direkt/dynamisch unklar); tests/test_server.py:1437 (direkt/dynamisch unklar); tests/test_server.py:1438 (direkt/dynamisch unklar); tests/test_server.py:1439 (direkt/dynamisch unklar); tests/test_server.py:1531 (direkt/dynamisch unklar); tests/test_server.py:1543 (direkt/dynamisch unklar); tests/test_server.py:1575 (direkt/dynamisch unklar); tests/test_server.py:1683 (direkt/dynamisch unklar); tests/test_server.py:1898 (direkt/dynamisch unklar); tests/test_server.py:1899 (direkt/dynamisch unklar); tests/test_server.py:1900 (direkt/dynamisch unklar); tests/test_server.py:1901 (direkt/dynamisch unklar); tests/test_server.py:1902 (direkt/dynamisch unklar); tests/test_server.py:199 (direkt/dynamisch unklar); tests/test_server.py:200 (direkt/dynamisch unklar); tests/test_server.py:2746 (direkt/dynamisch unklar); tests/test_server.py:2747 (direkt/dynamisch unklar); tests/test_server.py:3171 (direkt/dynamisch unklar); tests/test_server.py:3195 (direkt/dynamisch unklar); tests/test_server.py:3206 (direkt/dynamisch unklar); tests/test_server.py:3254 (direkt/dynamisch unklar); tests/test_server.py:3361 (direkt/dynamisch unklar); tests/test_server.py:3393 (direkt/dynamisch unklar); tests/test_server.py:3412 (direkt/dynamisch unklar); tests/test_server.py:3453 (direkt/dynamisch unklar); tests/test_server.py:3473 (direkt/dynamisch unklar); tests/test_server.py:4123 (direkt/dynamisch unklar); tests/test_server.py:4129 (direkt/dynamisch unklar); tests/test_server.py:4413 (direkt/dynamisch unklar); tests/test_server.py:4437 (direkt/dynamisch unklar); tests/test_server.py:4450 (direkt/dynamisch unklar); tests/test_server.py:4530 (direkt/dynamisch unklar); tests/test_server.py:4552 (direkt/dynamisch unklar); tests/test_server.py:5324 (direkt/dynamisch unklar); tests/test_server.py:5360 (direkt/dynamisch unklar); tests/test_server.py:5855 (direkt/dynamisch unklar); tests/test_server.py:6011 (direkt/dynamisch unklar); tests/test_server.py:6473 (direkt/dynamisch unklar); tests/test_server.py:6490 (direkt/dynamisch unklar); tests/test_server.py:6548 (direkt/dynamisch unklar); tests/test_server.py:6549 (direkt/dynamisch unklar); tests/test_server.py:7631 (direkt/dynamisch unklar); tests/test_server.py:7632 (direkt/dynamisch unklar); tests/test_server.py:7649 (direkt/dynamisch unklar); tests/test_server.py:7664 (direkt/dynamisch unklar); tests/test_server.py:7738 (direkt/dynamisch unklar); tests/test_server.py:7854 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:8336 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS` | 2412 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:382 (direkt/dynamisch unklar); tests/test_server.py:4502 (direkt/dynamisch unklar); tests/test_server.py:4503 (direkt/dynamisch unklar); tests/test_server.py:4504 (direkt/dynamisch unklar); tests/test_server.py:4508 (direkt/dynamisch unklar); tests/test_server.py:4509 (direkt/dynamisch unklar); tests/test_server.py:4510 (direkt/dynamisch unklar); tests/test_server.py:4511 (direkt/dynamisch unklar); tests/test_server.py:5336 (direkt/dynamisch unklar); tests/test_server.py:5337 (direkt/dynamisch unklar); tests/test_server.py:5338 (direkt/dynamisch unklar); tests/test_server.py:5340 (direkt/dynamisch unklar); tests/test_server.py:5343 (direkt/dynamisch unklar); tests/test_server.py:5344 (direkt/dynamisch unklar); tests/test_server.py:5345 (direkt/dynamisch unklar); tests/test_server.py:5347 (direkt/dynamisch unklar); tests/test_server.py:5350 (direkt/dynamisch unklar); tests/test_server.py:5352 (direkt/dynamisch unklar); tests/test_server.py:5355 (direkt/dynamisch unklar); tests/test_server.py:5357 (direkt/dynamisch unklar); tests/test_server.py:5359 (direkt/dynamisch unklar); tests/test_server.py:5361 (direkt/dynamisch unklar); tests/test_server.py:5364 (direkt/dynamisch unklar) |
| Globale Bindung | `DIAGNOSTIC_CAPTURE` | 2413 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7794 (direkt/dynamisch unklar); tests/test_server.py:7795 (direkt/dynamisch unklar); tests/test_server.py:7809 (direkt/dynamisch unklar); tests/test_server.py:7815 (direkt/dynamisch unklar); tests/test_server.py:7816 (direkt/dynamisch unklar); tests/test_server.py:8096 (direkt/dynamisch unklar); tests/test_server.py:8102 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 2416 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 2431 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 2448 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:217 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar); tests/test_server.py:5329 (direkt/dynamisch unklar); tests/test_server.py:5331 (direkt/dynamisch unklar); tests/test_server.py:6558 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 2456 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 2460 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4066 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 2468 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 2480 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 2495 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 2505 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 2516 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 2525 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 2540 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 2554 | `activities/` | P3 | offen | tests/test_server.py:3524 (direkt/dynamisch unklar); tests/test_server.py:3532 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 2566 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 2582 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 2597 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7540 (direkt/dynamisch unklar); tests/test_server.py:7551 (direkt/dynamisch unklar); tests/test_server.py:7559 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 2604 | `sync/` | P6 | offen | tests/test_server.py:3337 (direkt/dynamisch unklar); tests/test_server.py:7541 (direkt/dynamisch unklar); tests/test_server.py:7567 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 2611 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 2626 | `activities/` | P3 | offen | tests/test_server.py:7606 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 2649 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 2662 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 2680 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 2698 | `sync/` | P6 | offen | tests/test_server.py:7582 (direkt/dynamisch unklar); tests/test_server.py:7595 (direkt/dynamisch unklar); tests/test_server.py:7607 (direkt/dynamisch unklar); tests/test_server.py:7619 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 2713 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3340 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 2728 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 2741 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 2753 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 2756 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 2760 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 2766 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 2771 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 2780 | `sync/` | P6 | offen | tests/test_server.py:3248 (direkt/dynamisch unklar); tests/test_server.py:3249 (direkt/dynamisch unklar); tests/test_server.py:3250 (direkt/dynamisch unklar); tests/test_server.py:3251 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 2799 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 2812 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 2816 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 2834 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 2848 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 2864 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 2870 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 2878 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 2891 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 2904 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 2911 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 2929 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 2934 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 2960 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 2970 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 2979 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3355 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 2989 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3004 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3013 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3018 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3026 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3040 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3051 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3070 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3081 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3098 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3122 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3131 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3142 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3161 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:292 (direkt/dynamisch unklar); tests/test_provider_review.py:307 (direkt/dynamisch unklar); tests/test_server.py:3223 (direkt/dynamisch unklar); tests/test_server.py:3280 (direkt/dynamisch unklar); tests/test_server.py:3313 (direkt/dynamisch unklar); tests/test_server.py:3340 (direkt/dynamisch unklar); tests/test_server.py:3347 (direkt/dynamisch unklar); tests/test_server.py:3387 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3183 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 3198 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 3203 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 3219 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:302 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 3237 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 3256 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 3285 | `planning/` | P4 | offen | tests/test_server.py:3166 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 3302 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 3310 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 3338 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 3345 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 3369 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 3378 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 3395 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 3411 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 3416 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4023 (direkt/dynamisch unklar); tests/test_server.py:4027 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 3417 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 3420 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4026 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 3428 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4025 (direkt/dynamisch unklar); tests/test_server.py:4030 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 3437 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4024 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 3450 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4029 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 3455 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 3477 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 3487 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 3491 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4078 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 3506 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 3507 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 3510 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 3529 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 3543 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 3554 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4068 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 3565 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 3573 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 3578 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 3582 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 3600 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 3610 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 3614 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4054 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 3634 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 3645 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 3663 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:4033 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 3700 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 3705 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4122 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 3713 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 3726 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 3750 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 3779 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 3803 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4114 (direkt/dynamisch unklar); tests/test_server.py:4115 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 3816 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 3828 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 3858 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 3887 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 3894 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 3953 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 3976 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:242 (direkt/dynamisch unklar); tests/test_server.py:279 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4067 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8410 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4018 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:364 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4025 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4036 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:4121 (direkt/dynamisch unklar); tests/test_server.py:4133 (direkt/dynamisch unklar); tests/test_server.py:7739 (direkt/dynamisch unklar); tests/test_server.py:8411 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4076 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:280 (direkt/dynamisch unklar); tests/test_server.py:3186 (direkt/dynamisch unklar); tests/test_server.py:3200 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4099 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1736 (direkt/dynamisch unklar); tests/test_server.py:1768 (direkt/dynamisch unklar); tests/test_server.py:4434 (direkt/dynamisch unklar); tests/test_server.py:4435 (direkt/dynamisch unklar); tests/test_server.py:4436 (direkt/dynamisch unklar); tests/test_server.py:5147 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4106 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4113 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4116 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4128 | `athlete/` | P3 | offen | tests/test_server.py:1182 (direkt/dynamisch unklar); tests/test_server.py:1645 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4137 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1655 (direkt/dynamisch unklar); tests/test_server.py:6664 (direkt/dynamisch unklar); tests/test_server.py:8478 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4146 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:77 (direkt/dynamisch unklar); tests/test_audit_remediation.py:80 (direkt/dynamisch unklar); tests/test_audit_remediation.py:88 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1214 (direkt/dynamisch unklar); tests/test_server.py:1230 (direkt/dynamisch unklar); tests/test_server.py:1232 (direkt/dynamisch unklar); tests/test_server.py:1236 (direkt/dynamisch unklar); tests/test_server.py:1250 (direkt/dynamisch unklar); tests/test_server.py:1252 (direkt/dynamisch unklar); tests/test_server.py:1256 (direkt/dynamisch unklar); tests/test_server.py:1264 (direkt/dynamisch unklar); tests/test_server.py:1271 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar); tests/test_server.py:1557 (direkt/dynamisch unklar); tests/test_server.py:1574 (direkt/dynamisch unklar); tests/test_server.py:1617 (direkt/dynamisch unklar); tests/test_server.py:1638 (direkt/dynamisch unklar); tests/test_server.py:1640 (direkt/dynamisch unklar); tests/test_server.py:1651 (direkt/dynamisch unklar); tests/test_server.py:6617 (direkt/dynamisch unklar); tests/test_server.py:6645 (direkt/dynamisch unklar); tests/test_server.py:7214 (direkt/dynamisch unklar); tests/test_server.py:7359 (direkt/dynamisch unklar); tests/test_server.py:8463 (direkt/dynamisch unklar); tests/test_server.py:8464 (direkt/dynamisch unklar); tests/test_server.py:8493 (direkt/dynamisch unklar); tests/test_server.py:8510 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4160 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4170 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4177 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4180 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 4192 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 4204 | `athlete/` | P3 | offen | tests/test_server.py:1662 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 4224 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2625 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 4229 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:184 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1625 (direkt/dynamisch unklar); tests/test_server.py:1634 (direkt/dynamisch unklar); tests/test_server.py:1664 (direkt/dynamisch unklar); tests/test_server.py:1668 (direkt/dynamisch unklar); tests/test_server.py:1682 (direkt/dynamisch unklar); tests/test_server.py:1713 (direkt/dynamisch unklar); tests/test_server.py:2614 (direkt/dynamisch unklar); tests/test_server.py:2635 (direkt/dynamisch unklar); tests/test_server.py:2661 (direkt/dynamisch unklar); tests/test_server.py:2680 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 4237 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 4260 | `athlete/` | P3 | offen | tests/test_server.py:1632 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 4270 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 4277 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 4291 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2408 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 4296 | `activities/` | P3 | offen | tests/test_server.py:2405 (direkt/dynamisch unklar); tests/test_server.py:2407 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 4308 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2375 (direkt/dynamisch unklar); tests/test_server.py:2388 (direkt/dynamisch unklar); tests/test_server.py:2398 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 4325 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 4332 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 4346 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 4358 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 4380 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 4392 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 4406 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 4412 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3122 (direkt/dynamisch unklar); tests/test_server.py:3126 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 4422 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3124 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 4429 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 4442 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3108 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 4463 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:46 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_audit_remediation.py:59 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:6367 (direkt/dynamisch unklar); tests/test_server.py:6449 (direkt/dynamisch unklar); tests/test_server.py:6684 (direkt/dynamisch unklar); tests/test_server.py:6738 (direkt/dynamisch unklar); tests/test_server.py:6772 (direkt/dynamisch unklar); tests/test_server.py:6809 (direkt/dynamisch unklar); tests/test_server.py:6856 (direkt/dynamisch unklar); tests/test_server.py:6893 (direkt/dynamisch unklar); tests/test_server.py:6901 (direkt/dynamisch unklar); tests/test_server.py:691 (direkt/dynamisch unklar); tests/test_server.py:6928 (direkt/dynamisch unklar); tests/test_server.py:6956 (direkt/dynamisch unklar); tests/test_server.py:701 (direkt/dynamisch unklar) |
| Funktion | `_resolve_calendar_addresses` | 4468 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2478 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_calendar_feed_request` | 4483 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_remaining` | 4506 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_fetch_calendar_address` | 4513 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_failure_log` | 4548 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `fetch_calendar_feed` | 4563 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2448 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2483 (direkt/dynamisch unklar); tests/test_server.py:2496 (direkt/dynamisch unklar); tests/test_server.py:2533 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2577 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_url` | 4618 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2456 (direkt/dynamisch unklar); tests/test_server.py:2465 (direkt/dynamisch unklar); tests/test_server.py:2584 (direkt/dynamisch unklar); tests/test_server.py:2586 (direkt/dynamisch unklar); tests/test_server.py:7730 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_external_calendar_events` | 4634 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2451 (direkt/dynamisch unklar); tests/test_server.py:2507 (direkt/dynamisch unklar); tests/test_server.py:2548 (direkt/dynamisch unklar); tests/test_server.py:2567 (direkt/dynamisch unklar); tests/test_server.py:2580 (direkt/dynamisch unklar); tests/test_server.py:3028 (direkt/dynamisch unklar); tests/test_server.py:3030 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 4645 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2543 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 4660 | `sync/` | P6 | offen | tests/test_server.py:2450 (direkt/dynamisch unklar); tests/test_server.py:2538 (direkt/dynamisch unklar); tests/test_server.py:2563 (direkt/dynamisch unklar); tests/test_server.py:2579 (direkt/dynamisch unklar); tests/test_server.py:7734 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 4719 | `providers/calendar.py` | P2 | offen | tests/test_audit_remediation.py:170 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 4734 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 4738 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 4742 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 4748 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 4754 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 4762 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 4780 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 4797 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 4824 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 4831 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 4845 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 4877 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 4886 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 4897 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 4916 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 4928 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 4934 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 4947 | `performance/` | P3 | offen | tests/test_server.py:4124 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 4959 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 4963 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 4973 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 4982 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 4992 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 5003 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 5012 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 5032 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 5046 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1694 (direkt/dynamisch unklar); tests/test_server.py:3030 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 5070 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 5079 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 5091 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 5104 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 5119 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 5125 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 5136 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 5144 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 5155 | `athlete/` | P3 | offen | tests/test_server.py:1259 (direkt/dynamisch unklar); tests/test_server.py:3518 (direkt/dynamisch unklar); tests/test_server.py:6239 (direkt/dynamisch unklar); tests/test_server.py:6267 (direkt/dynamisch unklar); tests/test_server.py:6311 (direkt/dynamisch unklar); tests/test_server.py:6329 (direkt/dynamisch unklar); tests/test_server.py:6338 (direkt/dynamisch unklar); tests/test_server.py:6402 (direkt/dynamisch unklar); tests/test_server.py:6625 (direkt/dynamisch unklar); tests/test_server.py:6692 (direkt/dynamisch unklar); tests/test_server.py:6742 (direkt/dynamisch unklar); tests/test_server.py:6778 (direkt/dynamisch unklar); tests/test_server.py:6817 (direkt/dynamisch unklar); tests/test_server.py:6900 (direkt/dynamisch unklar); tests/test_server.py:6906 (direkt/dynamisch unklar); tests/test_server.py:6932 (direkt/dynamisch unklar); tests/test_server.py:6951 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 5172 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 5194 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 5206 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 5207 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 5212 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 5222 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 5240 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 5252 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 5265 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 5277 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 5296 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_audit_remediation.py:40 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1118 (direkt/dynamisch unklar); tests/test_server.py:463 (direkt/dynamisch unklar); tests/test_server.py:6323 (direkt/dynamisch unklar); tests/test_server.py:6349 (direkt/dynamisch unklar); tests/test_server.py:6661 (direkt/dynamisch unklar); tests/test_server.py:6666 (direkt/dynamisch unklar); tests/test_server.py:6700 (direkt/dynamisch unklar); tests/test_server.py:681 (direkt/dynamisch unklar); tests/test_server.py:6841 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 5304 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:52 (direkt/dynamisch unklar); tests/test_audit_remediation.py:64 (direkt/dynamisch unklar); tests/test_server.py:6681 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 5334 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 5355 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 5378 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 5393 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 5403 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 5409 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3101 (direkt/dynamisch unklar); tests/test_server.py:3102 (direkt/dynamisch unklar); tests/test_server.py:3103 (direkt/dynamisch unklar); tests/test_server.py:3104 (direkt/dynamisch unklar); tests/test_server.py:3105 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 5414 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 5429 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_server.py:6347 (direkt/dynamisch unklar); tests/test_server.py:6679 (direkt/dynamisch unklar); tests/test_server.py:6694 (direkt/dynamisch unklar); tests/test_server.py:6771 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 5433 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3130 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 5453 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3118 (direkt/dynamisch unklar); tests/test_server.py:3119 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 5469 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 5479 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3156 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 5486 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3157 (direkt/dynamisch unklar); tests/test_server.py:3158 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 5492 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3142 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 5520 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 5526 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 5535 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 5545 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6836 (direkt/dynamisch unklar); tests/test_server.py:6853 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 5585 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 5599 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 5612 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 5638 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 5664 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 5672 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 5680 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 5684 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 5722 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 5730 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 5737 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 5752 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 5764 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 5776 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 5783 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 5787 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 5820 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 5843 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 5862 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 5879 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 5887 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 5917 | `sync/` | P6 | offen | tests/test_audit_remediation.py:45 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:58 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_server.py:6322 (direkt/dynamisch unklar); tests/test_server.py:6330 (direkt/dynamisch unklar); tests/test_server.py:6366 (direkt/dynamisch unklar); tests/test_server.py:6536 (direkt/dynamisch unklar); tests/test_server.py:6733 (direkt/dynamisch unklar); tests/test_server.py:6765 (direkt/dynamisch unklar); tests/test_server.py:6766 (direkt/dynamisch unklar); tests/test_server.py:6803 (direkt/dynamisch unklar); tests/test_server.py:6835 (direkt/dynamisch unklar); tests/test_server.py:6851 (direkt/dynamisch unklar); tests/test_server.py:6854 (direkt/dynamisch unklar); tests/test_server.py:6890 (direkt/dynamisch unklar); tests/test_server.py:6923 (direkt/dynamisch unklar); tests/test_server.py:6950 (direkt/dynamisch unklar); tests/test_server.py:6952 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_STATUS_KEY` | 5973 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `GEMINI_STATUS_KEY` | 5974 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 5975 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `record_openai_status` | 5978 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_success` | 5993 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_persist_openai_rate_limits` | 6003 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_body` | 6009 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 6017 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 6025 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 6037 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 6042 | `coach/context.py` | P7 | offen | tests/test_server.py:7848 (direkt/dynamisch unklar) |
| Funktion | `_read_http_error_body` | 6052 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_urlopen_interruptibly` | 6063 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_body` | 6090 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_parts` | 6098 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_http_request_started` | 6132 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_http_response` | 6145 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 6160 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 6201 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 6220 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 6275 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 6310 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 6315 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 6343 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1782 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4282 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4351 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4475 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4490 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4574 (direkt/dynamisch unklar); tests/test_server.py:4617 (direkt/dynamisch unklar); tests/test_server.py:4654 (direkt/dynamisch unklar); tests/test_server.py:4687 (direkt/dynamisch unklar); tests/test_server.py:4747 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5377 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7360 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7754 (direkt/dynamisch unklar); tests/test_server.py:7772 (direkt/dynamisch unklar); tests/test_server.py:7790 (direkt/dynamisch unklar); tests/test_server.py:7824 (direkt/dynamisch unklar); tests/test_server.py:7841 (direkt/dynamisch unklar); tests/test_server.py:7965 (direkt/dynamisch unklar); tests/test_server.py:8001 (direkt/dynamisch unklar); tests/test_server.py:8029 (direkt/dynamisch unklar); tests/test_server.py:8050 (direkt/dynamisch unklar); tests/test_server.py:8338 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 6378 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 6390 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 6399 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 6407 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 6411 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 6417 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 6429 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 6434 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 6460 | `weather/` | P3 | offen | tests/test_server.py:1193 (direkt/dynamisch unklar); tests/test_server.py:1199 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 6470 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 6494 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 6509 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 6528 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 6543 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 6557 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 6578 | `weather/` | P3 | offen | tests/test_server.py:7403 (direkt/dynamisch unklar); tests/test_server.py:7410 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 6625 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 6641 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 6651 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 6672 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 6692 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 6696 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 6719 | `weather/` | P3 | offen | tests/test_audit_remediation.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:82 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1211 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1237 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1265 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1279 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1298 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1565 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1581 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 6731 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 6742 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 6769 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 6777 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 6790 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 6826 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 6845 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 6851 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 6873 | `weather/` | P3 | offen | tests/test_audit_remediation.py:147 (direkt/dynamisch unklar); tests/test_audit_remediation.py:148 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1299 (direkt/dynamisch unklar); tests/test_server.py:1300 (direkt/dynamisch unklar); tests/test_server.py:1301 (direkt/dynamisch unklar); tests/test_server.py:1591 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2894 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7365 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 6891 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 6909 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 6924 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 6931 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 6947 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 6975 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 6988 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 7008 | `sync/` | P6 | offen | tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_server.py:1280 (direkt/dynamisch unklar); tests/test_server.py:1281 (direkt/dynamisch unklar); tests/test_server.py:1282 (direkt/dynamisch unklar); tests/test_server.py:1568 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 7024 | `weather/` | P3 | offen | tests/test_server.py:7377 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 7036 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 7049 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 7054 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 7059 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 7063 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 7067 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 7075 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 7091 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 7110 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 7114 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 7123 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 7135 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 7156 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 7183 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 7198 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 7211 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2841 (direkt/dynamisch unklar); tests/test_server.py:2843 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 7249 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 7270 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 7290 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 7308 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2806 (direkt/dynamisch unklar); tests/test_server.py:2866 (direkt/dynamisch unklar); tests/test_server.py:2905 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 7318 | `providers/` | P2 | offen | tests/test_server.py:2867 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 7342 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 7362 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 7368 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 7391 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 7401 | `planning/` | P4 | offen | tests/test_server.py:2766 (direkt/dynamisch unklar); tests/test_server.py:3483 (direkt/dynamisch unklar); tests/test_server.py:6608 (direkt/dynamisch unklar); tests/test_server.py:6976 (direkt/dynamisch unklar); tests/test_server.py:7005 (direkt/dynamisch unklar); tests/test_server.py:7134 (direkt/dynamisch unklar); tests/test_server.py:7158 (direkt/dynamisch unklar); tests/test_server.py:7179 (direkt/dynamisch unklar); tests/test_server.py:7195 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 7439 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 7440 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 7445 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 7448 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 7457 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 7461 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 7470 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 7495 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 7502 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 7513 | `planning/competitions.py` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3713 (direkt/dynamisch unklar); tests/test_server.py:3730 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 7527 | `planning/competitions.py` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:2995 (direkt/dynamisch unklar); tests/test_server.py:3087 (direkt/dynamisch unklar); tests/test_server.py:3163 (direkt/dynamisch unklar); tests/test_server.py:3749 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 7550 | `planning/competitions.py` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 7563 | `planning/competitions.py` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3675 (direkt/dynamisch unklar); tests/test_server.py:3725 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 7590 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 7600 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 7610 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 7617 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 7635 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 7645 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 7658 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 7671 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 7686 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 7695 | `providers/` | P2 | offen | tests/test_server.py:3498 (direkt/dynamisch unklar); tests/test_server.py:3503 (direkt/dynamisch unklar); tests/test_server.py:3504 (direkt/dynamisch unklar); tests/test_server.py:3514 (direkt/dynamisch unklar); tests/test_server.py:3519 (direkt/dynamisch unklar); tests/test_server.py:4950 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 7710 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 7723 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 7747 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 7758 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 7773 | `planning/competitions.py` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1587 (direkt/dynamisch unklar); tests/test_server.py:1604 (direkt/dynamisch unklar); tests/test_server.py:2511 (direkt/dynamisch unklar); tests/test_server.py:2590 (direkt/dynamisch unklar); tests/test_server.py:2610 (direkt/dynamisch unklar); tests/test_server.py:2657 (direkt/dynamisch unklar); tests/test_server.py:2676 (direkt/dynamisch unklar); tests/test_server.py:2687 (direkt/dynamisch unklar); tests/test_server.py:2719 (direkt/dynamisch unklar); tests/test_server.py:3697 (direkt/dynamisch unklar); tests/test_server.py:3782 (direkt/dynamisch unklar); tests/test_server.py:3810 (direkt/dynamisch unklar); tests/test_server.py:3831 (direkt/dynamisch unklar); tests/test_server.py:3833 (direkt/dynamisch unklar); tests/test_server.py:3840 (direkt/dynamisch unklar); tests/test_server.py:405 (direkt/dynamisch unklar); tests/test_server.py:5461 (direkt/dynamisch unklar); tests/test_server.py:5471 (direkt/dynamisch unklar); tests/test_server.py:5499 (direkt/dynamisch unklar); tests/test_server.py:5744 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6210 (direkt/dynamisch unklar); tests/test_server.py:818 (direkt/dynamisch unklar); tests/test_server.py:851 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 7790 | `planning/competitions.py` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5465 (direkt/dynamisch unklar); tests/test_server.py:5476 (direkt/dynamisch unklar); tests/test_server.py:5492 (direkt/dynamisch unklar); tests/test_server.py:5504 (direkt/dynamisch unklar); tests/test_server.py:5520 (direkt/dynamisch unklar); tests/test_server.py:5543 (direkt/dynamisch unklar); tests/test_server.py:5565 (direkt/dynamisch unklar); tests/test_server.py:845 (direkt/dynamisch unklar); tests/test_server.py:873 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 7798 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 7806 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 7811 | `planning/competitions.py` | P4 | offen | tests/test_server.py:5467 (direkt/dynamisch unklar); tests/test_server.py:5477 (direkt/dynamisch unklar); tests/test_server.py:857 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 7828 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 7833 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 7845 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 7863 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 7892 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_server.py:1618 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 7904 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2631 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 7921 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7642 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 7938 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 7963 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 7977 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 7986 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 8004 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 8018 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 8026 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 8044 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 8053 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 8067 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 8082 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 8099 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 8116 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 8140 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 8172 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 8198 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 8219 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 8227 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 8246 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 8269 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1595 (direkt/dynamisch unklar); tests/test_server.py:1612 (direkt/dynamisch unklar); tests/test_server.py:2520 (direkt/dynamisch unklar); tests/test_server.py:2599 (direkt/dynamisch unklar); tests/test_server.py:2615 (direkt/dynamisch unklar); tests/test_server.py:2629 (direkt/dynamisch unklar); tests/test_server.py:2636 (direkt/dynamisch unklar); tests/test_server.py:2662 (direkt/dynamisch unklar); tests/test_server.py:2681 (direkt/dynamisch unklar); tests/test_server.py:2691 (direkt/dynamisch unklar); tests/test_server.py:2728 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 8300 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 8311 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 8327 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 8342 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 8352 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 8391 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 8406 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 8414 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 8436 | `planning/` | P4 | offen | tests/test_audit_remediation.py:244 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2620 (direkt/dynamisch unklar); tests/test_server.py:2647 (direkt/dynamisch unklar); tests/test_server.py:2666 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2683 (direkt/dynamisch unklar); tests/test_server.py:2692 (direkt/dynamisch unklar); tests/test_server.py:2695 (direkt/dynamisch unklar); tests/test_server.py:2729 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 8466 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 8490 | `planning/` | P4 | offen | tests/test_server.py:1619 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 8494 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 8502 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 8518 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 8531 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 8536 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 8541 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 8550 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 8559 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 8581 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 8587 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 8591 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 8604 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 8618 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 8624 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 8637 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 8650 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 8671 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 8687 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 8697 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 8713 | `planning/` | P4 | offen | tests/test_server.py:2707 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 8736 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 8752 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 8755 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 8779 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 8788 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:2914 (direkt/dynamisch unklar); tests/test_server.py:3036 (direkt/dynamisch unklar); tests/test_server.py:3057 (direkt/dynamisch unklar); tests/test_server.py:3510 (direkt/dynamisch unklar); tests/test_server.py:375 (direkt/dynamisch unklar); tests/test_server.py:4813 (direkt/dynamisch unklar); tests/test_server.py:4835 (direkt/dynamisch unklar); tests/test_server.py:4891 (direkt/dynamisch unklar); tests/test_server.py:4908 (direkt/dynamisch unklar); tests/test_server.py:4926 (direkt/dynamisch unklar); tests/test_server.py:4944 (direkt/dynamisch unklar); tests/test_server.py:4965 (direkt/dynamisch unklar); tests/test_server.py:4988 (direkt/dynamisch unklar); tests/test_server.py:5033 (direkt/dynamisch unklar); tests/test_server.py:5055 (direkt/dynamisch unklar); tests/test_server.py:5078 (direkt/dynamisch unklar); tests/test_server.py:5094 (direkt/dynamisch unklar); tests/test_server.py:5111 (direkt/dynamisch unklar); tests/test_server.py:5174 (direkt/dynamisch unklar); tests/test_server.py:5236 (direkt/dynamisch unklar); tests/test_server.py:5245 (direkt/dynamisch unklar); tests/test_server.py:5403 (direkt/dynamisch unklar); tests/test_server.py:5434 (direkt/dynamisch unklar); tests/test_server.py:5597 (direkt/dynamisch unklar); tests/test_server.py:5627 (direkt/dynamisch unklar); tests/test_server.py:5645 (direkt/dynamisch unklar); tests/test_server.py:5650 (direkt/dynamisch unklar); tests/test_server.py:5659 (direkt/dynamisch unklar); tests/test_server.py:5663 (direkt/dynamisch unklar); tests/test_server.py:5668 (direkt/dynamisch unklar); tests/test_server.py:5677 (direkt/dynamisch unklar); tests/test_server.py:5696 (direkt/dynamisch unklar); tests/test_server.py:5699 (direkt/dynamisch unklar); tests/test_server.py:5725 (direkt/dynamisch unklar); tests/test_server.py:705 (direkt/dynamisch unklar); tests/test_server.py:7238 (direkt/dynamisch unklar); tests/test_server.py:728 (direkt/dynamisch unklar); tests/test_server.py:745 (direkt/dynamisch unklar); tests/test_server.py:771 (direkt/dynamisch unklar); tests/test_server.py:775 (direkt/dynamisch unklar); tests/test_server.py:878 (direkt/dynamisch unklar); tests/test_server.py:898 (direkt/dynamisch unklar); tests/test_server.py:902 (direkt/dynamisch unklar); tests/test_server.py:925 (direkt/dynamisch unklar); tests/test_server.py:973 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 8806 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2623 (direkt/dynamisch unklar); tests/test_server.py:2624 (direkt/dynamisch unklar); tests/test_server.py:2632 (direkt/dynamisch unklar); tests/test_server.py:2697 (direkt/dynamisch unklar); tests/test_server.py:2968 (direkt/dynamisch unklar); tests/test_server.py:2978 (direkt/dynamisch unklar); tests/test_server.py:2981 (direkt/dynamisch unklar); tests/test_server.py:2992 (direkt/dynamisch unklar); tests/test_server.py:3008 (direkt/dynamisch unklar); tests/test_server.py:3079 (direkt/dynamisch unklar); tests/test_server.py:3820 (direkt/dynamisch unklar); tests/test_server.py:3824 (direkt/dynamisch unklar); tests/test_server.py:3832 (direkt/dynamisch unklar); tests/test_server.py:3836 (direkt/dynamisch unklar); tests/test_server.py:4826 (direkt/dynamisch unklar); tests/test_server.py:4852 (direkt/dynamisch unklar); tests/test_server.py:4869 (direkt/dynamisch unklar); tests/test_server.py:4903 (direkt/dynamisch unklar); tests/test_server.py:4921 (direkt/dynamisch unklar); tests/test_server.py:4939 (direkt/dynamisch unklar); tests/test_server.py:4978 (direkt/dynamisch unklar); tests/test_server.py:5002 (direkt/dynamisch unklar); tests/test_server.py:5024 (direkt/dynamisch unklar); tests/test_server.py:5091 (direkt/dynamisch unklar); tests/test_server.py:5107 (direkt/dynamisch unklar); tests/test_server.py:5128 (direkt/dynamisch unklar); tests/test_server.py:5428 (direkt/dynamisch unklar); tests/test_server.py:5429 (direkt/dynamisch unklar); tests/test_server.py:5518 (direkt/dynamisch unklar); tests/test_server.py:5592 (direkt/dynamisch unklar); tests/test_server.py:5720 (direkt/dynamisch unklar); tests/test_server.py:5750 (direkt/dynamisch unklar); tests/test_server.py:6120 (direkt/dynamisch unklar); tests/test_server.py:768 (direkt/dynamisch unklar); tests/test_server.py:796 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 8818 | `planning/` | P4 | offen | tests/test_server.py:3580 (direkt/dynamisch unklar); tests/test_server.py:3791 (direkt/dynamisch unklar); tests/test_server.py:3853 (direkt/dynamisch unklar); tests/test_server.py:6149 (direkt/dynamisch unklar); tests/test_server.py:6186 (direkt/dynamisch unklar); tests/test_server.py:6230 (direkt/dynamisch unklar); tests/test_server.py:6389 (direkt/dynamisch unklar); tests/test_server.py:8484 (direkt/dynamisch unklar); tests/test_server.py:8574 (direkt/dynamisch unklar); tests/test_server.py:8575 (direkt/dynamisch unklar); tests/test_server.py:996 (direkt/dynamisch unklar); tests/test_server.py:999 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 8846 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3779 (direkt/dynamisch unklar); tests/test_server.py:538 (direkt/dynamisch unklar); tests/test_server.py:732 (direkt/dynamisch unklar); tests/test_server.py:950 (direkt/dynamisch unklar); tests/test_server.py:970 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 8869 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 8884 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 8901 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 8916 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 8939 | `planning/` | P4 | offen | tests/test_server.py:1431 (direkt/dynamisch unklar); tests/test_server.py:1748 (direkt/dynamisch unklar); tests/test_server.py:3565 (direkt/dynamisch unklar); tests/test_server.py:3571 (direkt/dynamisch unklar); tests/test_server.py:3595 (direkt/dynamisch unklar); tests/test_server.py:4204 (direkt/dynamisch unklar); tests/test_server.py:4220 (direkt/dynamisch unklar); tests/test_server.py:4238 (direkt/dynamisch unklar); tests/test_server.py:4253 (direkt/dynamisch unklar); tests/test_server.py:6203 (direkt/dynamisch unklar); tests/test_server.py:6403 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 8964 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3576 (direkt/dynamisch unklar); tests/test_server.py:3585 (direkt/dynamisch unklar); tests/test_server.py:3587 (direkt/dynamisch unklar); tests/test_server.py:3588 (direkt/dynamisch unklar); tests/test_server.py:3590 (direkt/dynamisch unklar); tests/test_server.py:3592 (direkt/dynamisch unklar); tests/test_server.py:3800 (direkt/dynamisch unklar); tests/test_server.py:3863 (direkt/dynamisch unklar); tests/test_server.py:4208 (direkt/dynamisch unklar); tests/test_server.py:4216 (direkt/dynamisch unklar); tests/test_server.py:4224 (direkt/dynamisch unklar); tests/test_server.py:4234 (direkt/dynamisch unklar); tests/test_server.py:4242 (direkt/dynamisch unklar); tests/test_server.py:4250 (direkt/dynamisch unklar); tests/test_server.py:4257 (direkt/dynamisch unklar); tests/test_server.py:6078 (direkt/dynamisch unklar); tests/test_server.py:6167 (direkt/dynamisch unklar); tests/test_server.py:6220 (direkt/dynamisch unklar); tests/test_server.py:6455 (direkt/dynamisch unklar); tests/test_server.py:8490 (direkt/dynamisch unklar); tests/test_server.py:966 (direkt/dynamisch unklar); tests/test_server.py:967 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 8971 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 8988 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 8989 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 8990 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 8991 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 8994 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 9001 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 9006 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 9016 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 9023 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1727 (direkt/dynamisch unklar); tests/test_server.py:1728 (direkt/dynamisch unklar); tests/test_server.py:1729 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 9050 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:307 (direkt/dynamisch unklar); tests/test_audit_remediation.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1737 (direkt/dynamisch unklar); tests/test_server.py:1738 (direkt/dynamisch unklar); tests/test_server.py:1743 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 9082 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1752 (direkt/dynamisch unklar); tests/test_server.py:1753 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 9110 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1903 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 9131 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 9151 | `activities/` | P3 | offen | tests/test_server.py:534 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 9192 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 9197 | `planning/` | P4 | offen | tests/test_server.py:2606 (direkt/dynamisch unklar); tests/test_server.py:2619 (direkt/dynamisch unklar); tests/test_server.py:2622 (direkt/dynamisch unklar); tests/test_server.py:2670 (direkt/dynamisch unklar); tests/test_server.py:2696 (direkt/dynamisch unklar); tests/test_server.py:2730 (direkt/dynamisch unklar); tests/test_server.py:2733 (direkt/dynamisch unklar); tests/test_server.py:2893 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2943 (direkt/dynamisch unklar); tests/test_server.py:2960 (direkt/dynamisch unklar); tests/test_server.py:3054 (direkt/dynamisch unklar); tests/test_server.py:3699 (direkt/dynamisch unklar); tests/test_server.py:3788 (direkt/dynamisch unklar); tests/test_server.py:3846 (direkt/dynamisch unklar); tests/test_server.py:4217 (direkt/dynamisch unklar); tests/test_server.py:4235 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 9202 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 9209 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 9220 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 9232 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 9257 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 9273 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 9281 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 9295 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 9307 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:2928 (direkt/dynamisch unklar); tests/test_server.py:2943 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 9326 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 9331 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 9348 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 9362 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 9369 | `calendar/` | P3 | offen | tests/test_server.py:3028 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 9384 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 9397 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 9410 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 9467 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 9484 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 9524 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 9531 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 9539 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 9547 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 9560 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 9570 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 9582 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 9611 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 9621 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 9643 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:311 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 9660 | `sync/` | P6 | offen | tests/test_server.py:3819 (direkt/dynamisch unklar); tests/test_server.py:3823 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 9665 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 9683 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 9690 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 9699 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 9714 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 9719 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 9725 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 9733 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 9745 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 9754 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 9771 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 9791 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 9794 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 9807 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 9819 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 9842 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 9862 | `planning/` | P4 | offen | tests/test_server.py:5973 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6002 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6015 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6035 (direkt/dynamisch unklar); tests/test_server.py:6114 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6138 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6179 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6197 (direkt/dynamisch unklar); tests/test_server.py:661 (Monkeypatch/getattr/sys.modules); tests/test_server.py:674 (Monkeypatch/getattr/sys.modules) |
| Funktion | `plan_library_workout_remote` | 9903 | `planning/` | P4 | offen | tests/test_server.py:6378 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 9907 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 9928 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 9943 | `sync/snapshots.py` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 9949 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 9956 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 9971 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 9986 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 9996 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 10002 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 10017 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 10025 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1435 (direkt/dynamisch unklar); tests/test_server.py:3583 (direkt/dynamisch unklar); tests/test_server.py:3586 (direkt/dynamisch unklar); tests/test_server.py:3589 (direkt/dynamisch unklar); tests/test_server.py:3591 (direkt/dynamisch unklar); tests/test_server.py:3597 (direkt/dynamisch unklar); tests/test_server.py:3599 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 10049 | `planning/` | P4 | offen | tests/test_server.py:6393 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 10068 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 10084 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 10096 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 10110 | `calendar/` | P3 | offen | tests/test_server.py:7855 (direkt/dynamisch unklar); tests/test_server.py:7865 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 10145 | `sync/status.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 10175 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 10193 | `sync/` | P6 | offen | tests/test_server.py:1904 (direkt/dynamisch unklar); tests/test_server.py:2149 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 10197 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 10212 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 10231 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 10244 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 10258 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 10277 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 10290 | `sync/` | P6 | offen | tests/test_server.py:3798 (direkt/dynamisch unklar); tests/test_server.py:3804 (direkt/dynamisch unklar); tests/test_server.py:3860 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 10305 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 10313 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 10337 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 10342 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 10365 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 10372 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 10397 | `planning/` | P4 | offen | tests/test_server.py:4210 (direkt/dynamisch unklar); tests/test_server.py:4230 (direkt/dynamisch unklar); tests/test_server.py:4245 (direkt/dynamisch unklar); tests/test_server.py:4259 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 10411 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 10420 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 10431 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 10440 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 10452 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 10465 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 10469 | `sync/` | P6 | offen | tests/test_server.py:6442 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8582 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 10482 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 10495 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 10499 | `sync/` | P6 | offen | tests/test_server.py:312 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 10518 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 10533 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 10548 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 10564 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 10577 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 10594 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 10605 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 10621 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 10639 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 10658 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 10681 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 10696 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 10705 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 10726 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 10744 | `planning/calendar.py` | P3 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 10768 | `planning/` | P4 | offen | tests/test_server.py:2664 (direkt/dynamisch unklar); tests/test_server.py:2682 (direkt/dynamisch unklar); tests/test_server.py:2965 (direkt/dynamisch unklar); tests/test_server.py:2979 (direkt/dynamisch unklar); tests/test_server.py:3009 (direkt/dynamisch unklar); tests/test_server.py:3041 (direkt/dynamisch unklar); tests/test_server.py:3048 (direkt/dynamisch unklar); tests/test_server.py:3050 (direkt/dynamisch unklar); tests/test_server.py:3052 (direkt/dynamisch unklar); tests/test_server.py:3062 (direkt/dynamisch unklar); tests/test_server.py:3064 (direkt/dynamisch unklar); tests/test_server.py:3513 (direkt/dynamisch unklar); tests/test_server.py:3787 (direkt/dynamisch unklar); tests/test_server.py:3835 (direkt/dynamisch unklar); tests/test_server.py:4949 (direkt/dynamisch unklar); tests/test_server.py:5649 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 10794 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 10805 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 10816 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 10826 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 10832 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 10843 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 10855 | `planning/` | P4 | offen | tests/test_server.py:3011 (direkt/dynamisch unklar); tests/test_server.py:3014 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 10873 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:92 (direkt/dynamisch unklar); tests/test_server.py:1695 (direkt/dynamisch unklar); tests/test_server.py:1696 (direkt/dynamisch unklar); tests/test_server.py:2892 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5328 (direkt/dynamisch unklar); tests/test_server.py:5330 (direkt/dynamisch unklar); tests/test_server.py:6447 (direkt/dynamisch unklar); tests/test_server.py:6470 (direkt/dynamisch unklar); tests/test_server.py:7627 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 10878 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:110 (direkt/dynamisch unklar); tests/test_provider_review.py:230 (direkt/dynamisch unklar); tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_provider_review.py:63 (direkt/dynamisch unklar); tests/test_provider_review.py:87 (direkt/dynamisch unklar); tests/test_server.py:1463 (direkt/dynamisch unklar); tests/test_server.py:1675 (direkt/dynamisch unklar); tests/test_server.py:1712 (direkt/dynamisch unklar); tests/test_server.py:1720 (direkt/dynamisch unklar); tests/test_server.py:1760 (direkt/dynamisch unklar); tests/test_server.py:2368 (direkt/dynamisch unklar); tests/test_server.py:2393 (direkt/dynamisch unklar); tests/test_server.py:3539 (direkt/dynamisch unklar); tests/test_server.py:3604 (direkt/dynamisch unklar); tests/test_server.py:4226 (direkt/dynamisch unklar); tests/test_server.py:489 (direkt/dynamisch unklar); tests/test_server.py:5282 (direkt/dynamisch unklar); tests/test_server.py:5323 (direkt/dynamisch unklar); tests/test_server.py:6459 (direkt/dynamisch unklar); tests/test_server.py:7240 (direkt/dynamisch unklar); tests/test_server.py:7618 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 10888 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 10914 | `sync/` | P6 | offen | tests/test_server.py:1048 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 10939 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 10944 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 10954 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 10962 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 10993 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 11015 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 11026 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 11040 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 11062 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 11079 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 11113 | `planning/` | P4 | offen | tests/test_server.py:2956 (direkt/dynamisch unklar); tests/test_server.py:2958 (direkt/dynamisch unklar); tests/test_server.py:2966 (direkt/dynamisch unklar); tests/test_server.py:2977 (direkt/dynamisch unklar); tests/test_server.py:2980 (direkt/dynamisch unklar); tests/test_server.py:2988 (direkt/dynamisch unklar); tests/test_server.py:3007 (direkt/dynamisch unklar); tests/test_server.py:3010 (direkt/dynamisch unklar); tests/test_server.py:3013 (direkt/dynamisch unklar); tests/test_server.py:3497 (direkt/dynamisch unklar); tests/test_server.py:3502 (direkt/dynamisch unklar); tests/test_server.py:5577 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 11161 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 11177 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 11189 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 11201 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 11206 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 11216 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 11223 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 11230 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 11241 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 11256 | `sync/` | P6 | offen | tests/test_server.py:6305 (direkt/dynamisch unklar); tests/test_server.py:6443 (direkt/dynamisch unklar); tests/test_server.py:6469 (direkt/dynamisch unklar); tests/test_server.py:6479 (direkt/dynamisch unklar); tests/test_server.py:6555 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 11291 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 11306 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 11335 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 11364 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 11384 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 11401 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 11458 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 11473 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 11484 | `sync/` | P6 | offen | tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5974 (direkt/dynamisch unklar); tests/test_server.py:5989 (direkt/dynamisch unklar); tests/test_server.py:6004 (direkt/dynamisch unklar); tests/test_server.py:6017 (direkt/dynamisch unklar); tests/test_server.py:6046 (direkt/dynamisch unklar); tests/test_server.py:6075 (direkt/dynamisch unklar); tests/test_server.py:6115 (direkt/dynamisch unklar); tests/test_server.py:6116 (direkt/dynamisch unklar); tests/test_server.py:6140 (direkt/dynamisch unklar); tests/test_server.py:6142 (direkt/dynamisch unklar); tests/test_server.py:6162 (direkt/dynamisch unklar); tests/test_server.py:6180 (direkt/dynamisch unklar); tests/test_server.py:619 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6297 (direkt/dynamisch unklar); tests/test_server.py:6398 (direkt/dynamisch unklar); tests/test_server.py:664 (direkt/dynamisch unklar); tests/test_server.py:677 (direkt/dynamisch unklar); tests/test_server.py:7671 (direkt/dynamisch unklar); tests/test_server.py:7938 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 11518 | `performance/` | P3 | offen | tests/test_provider_review.py:77 (direkt/dynamisch unklar); tests/test_server.py:595 (Monkeypatch/getattr/sys.modules); tests/test_server.py:608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7232 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 11542 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 11549 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 11556 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 11574 | `activities/` | P3 | offen | tests/test_server.py:5196 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 11586 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 11603 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 11616 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 11633 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 11654 | `performance/` | P3 | offen | tests/test_server.py:7129 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 11663 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 11675 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 11691 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 11706 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 11742 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 11752 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 11766 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 11782 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 11799 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 11809 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 11820 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 11834 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 11846 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 11851 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 11883 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 11892 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 11898 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 11905 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 11919 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 11932 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 11936 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 11965 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 11972 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 12009 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 12029 | `performance/` | P3 | offen | tests/test_server.py:3258 (direkt/dynamisch unklar); tests/test_server.py:3267 (direkt/dynamisch unklar); tests/test_server.py:3375 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 12058 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 12072 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 12088 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 12096 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 12106 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 12133 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 12148 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 12171 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 12189 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 12221 | `activities/` | P3 | offen | tests/test_server.py:7028 (direkt/dynamisch unklar); tests/test_server.py:7050 (direkt/dynamisch unklar); tests/test_server.py:7056 (direkt/dynamisch unklar); tests/test_server.py:7065 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 12266 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 12299 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 12320 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 12332 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 12352 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 12365 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 12396 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 12426 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 12437 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 12480 | `performance/` | P3 | offen | tests/test_provider_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:3398 (direkt/dynamisch unklar); tests/test_server.py:3428 (direkt/dynamisch unklar); tests/test_server.py:3457 (direkt/dynamisch unklar); tests/test_server.py:3478 (direkt/dynamisch unklar); tests/test_server.py:3490 (direkt/dynamisch unklar); tests/test_server.py:6967 (direkt/dynamisch unklar); tests/test_server.py:6989 (direkt/dynamisch unklar); tests/test_server.py:7016 (direkt/dynamisch unklar); tests/test_server.py:7085 (direkt/dynamisch unklar); tests/test_server.py:7099 (direkt/dynamisch unklar); tests/test_server.py:7115 (direkt/dynamisch unklar); tests/test_server.py:7146 (direkt/dynamisch unklar); tests/test_server.py:7167 (direkt/dynamisch unklar); tests/test_server.py:7189 (direkt/dynamisch unklar); tests/test_server.py:7209 (direkt/dynamisch unklar); tests/test_server.py:7215 (direkt/dynamisch unklar); tests/test_server.py:7219 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 12551 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 12565 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 12569 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 12573 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 12578 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 12582 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 12586 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 12590 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 12594 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 12613 | `planning/` | P4 | offen | tests/test_server.py:5186 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 12632 | `coach/context.py` | P7 | offen | tests/test_server.py:5178 (direkt/dynamisch unklar); tests/test_server.py:5215 (direkt/dynamisch unklar); tests/test_server.py:5216 (direkt/dynamisch unklar); tests/test_server.py:5237 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 12678 | `coach/context.py` | P7 | offen | tests/test_server.py:1582 (direkt/dynamisch unklar); tests/test_server.py:1656 (direkt/dynamisch unklar); tests/test_server.py:2382 (direkt/dynamisch unklar); tests/test_server.py:3211 (direkt/dynamisch unklar); tests/test_server.py:5258 (direkt/dynamisch unklar); tests/test_server.py:5264 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6640 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 12743 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 12761 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 12771 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 12788 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:248 (direkt/dynamisch unklar); tests/test_provider_review.py:282 (direkt/dynamisch unklar); tests/test_server.py:3577 (direkt/dynamisch unklar); tests/test_server.py:5254 (direkt/dynamisch unklar); tests/test_server.py:5265 (direkt/dynamisch unklar); tests/test_server.py:5266 (direkt/dynamisch unklar); tests/test_server.py:5283 (direkt/dynamisch unklar); tests/test_server.py:5294 (direkt/dynamisch unklar); tests/test_server.py:5326 (direkt/dynamisch unklar); tests/test_server.py:6618 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 12828 | `coach/context.py` | P7 | offen | tests/test_server.py:5148 (direkt/dynamisch unklar); tests/test_server.py:5288 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 12884 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 12914 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_openai_usage_summary_unlocked` | 12924 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_usage_summary` | 12947 | `providers/` | P2 | offen | tests/test_server.py:8002 (direkt/dynamisch unklar); tests/test_server.py:8032 (direkt/dynamisch unklar); tests/test_server.py:8148 (direkt/dynamisch unklar); tests/test_server.py:8158 (direkt/dynamisch unklar); tests/test_server.py:8182 (direkt/dynamisch unklar); tests/test_server.py:8205 (direkt/dynamisch unklar); tests/test_server.py:8349 (direkt/dynamisch unklar); tests/test_server.py:8387 (direkt/dynamisch unklar) |
| Funktion | `_record_openai_usage_unlocked` | 12955 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_usage` | 12984 | `providers/` | P2 | offen | tests/test_server.py:5768 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8344 (direkt/dynamisch unklar); tests/test_server.py:8385 (direkt/dynamisch unklar) |
| Funktion | `_validate_openai_response` | 12991 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8326 (direkt/dynamisch unklar); tests/test_server.py:8329 (direkt/dynamisch unklar); tests/test_server.py:8332 (direkt/dynamisch unklar) |
| Funktion | `openai_endpoint` | 13013 | `providers/` | P2 | offen | tests/test_server.py:4724 (direkt/dynamisch unklar); tests/test_server.py:4725 (direkt/dynamisch unklar); tests/test_server.py:4727 (direkt/dynamisch unklar); tests/test_server.py:4736 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 13030 | `providers/` | P2 | offen | tests/test_server.py:4521 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4748 (direkt/dynamisch unklar); tests/test_server.py:5371 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5380 (direkt/dynamisch unklar); tests/test_server.py:5973 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7230 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8079 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8339 (direkt/dynamisch unklar) |
| Funktion | `multipart_form_data` | 13054 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VOICE_AUDIO_TYPES` | 13079 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `normalized_audio_type` | 13091 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `transcribe_audio` | 13095 | `providers/` | P2 | offen | tests/test_server.py:4491 (direkt/dynamisch unklar); tests/test_server.py:4707 (direkt/dynamisch unklar); tests/test_server.py:4780 (direkt/dynamisch unklar); tests/test_server.py:4782 (direkt/dynamisch unklar) |
| Funktion | `_provider_usage_summary` | 13147 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_usage_summary` | 13164 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_status` | 13169 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_usage` | 13175 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_content_has_function_response` | 13194 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 13199 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 13206 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 13217 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 13233 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 13245 | `providers/` | P2 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4414 (direkt/dynamisch unklar); tests/test_server.py:4546 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 13253 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 13265 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 13281 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 13297 | `providers/` | P2 | offen | tests/test_server.py:4425 (direkt/dynamisch unklar); tests/test_server.py:4430 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 13319 | `providers/` | P2 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_request_payload` | 13341 | `providers/` | P2 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4442 (direkt/dynamisch unklar); tests/test_server.py:4455 (direkt/dynamisch unklar); tests/test_server.py:4525 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 13437 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 13456 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 13495 | `providers/` | P2 | offen | tests/test_server.py:4283 (direkt/dynamisch unklar); tests/test_server.py:4285 (direkt/dynamisch unklar); tests/test_server.py:4352 (direkt/dynamisch unklar); tests/test_server.py:4355 (direkt/dynamisch unklar); tests/test_server.py:4477 (direkt/dynamisch unklar); tests/test_server.py:4521 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 13502 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `request_ai_provider` | 13643 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 13648 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4522 (direkt/dynamisch unklar); tests/test_server.py:5372 (direkt/dynamisch unklar); tests/test_server.py:5763 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8080 (direkt/dynamisch unklar) |
| Funktion | `_openai_response_id` | 13673 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `retrieve_openai_response` | 13680 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 13695 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 13713 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5769 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 13750 | `coach/context.py` | P7 | offen | tests/test_server.py:6029 (direkt/dynamisch unklar) |
| Funktion | `_notify_openai_stream_response_id` | 13755 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_forward_openai_stream_delta` | 13768 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_stream_final_response` | 13776 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_consume_openai_sse_event` | 13783 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_read_openai_stream_response` | 13802 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_openai_stream_failure` | 13838 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_capture_openai_stream_failure` | 13856 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 13870 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 13882 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 13893 | `providers/` | P2 | offen | tests/test_server.py:8064 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 13925 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 13941 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 13956 | `providers/` | P2 | offen | tests/test_server.py:4772 (direkt/dynamisch unklar); tests/test_server.py:8100 (direkt/dynamisch unklar); tests/test_server.py:8141 (direkt/dynamisch unklar); tests/test_server.py:8155 (direkt/dynamisch unklar); tests/test_server.py:8179 (direkt/dynamisch unklar); tests/test_server.py:8204 (direkt/dynamisch unklar); tests/test_server.py:8210 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 14033 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4327 (direkt/dynamisch unklar); tests/test_server.py:5869 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8211 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 14059 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 14078 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 14091 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 14109 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 14122 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 14128 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 14136 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:308 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4555 (direkt/dynamisch unklar); tests/test_server.py:5394 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 14145 | `providers/` | P2 | offen | tests/test_server.py:4267 (direkt/dynamisch unklar); tests/test_server.py:4299 (direkt/dynamisch unklar); tests/test_server.py:4333 (direkt/dynamisch unklar); tests/test_server.py:4521 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 14149 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 14150 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 14153 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 14157 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 14170 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 14195 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 14219 | `activities/` | P3 | offen | tests/test_server.py:7621 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 14239 | `coach/context.py` | P7 | offen | tests/test_server.py:8448 (direkt/dynamisch unklar); tests/test_server.py:8459 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 14261 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 14270 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 14292 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8475 (direkt/dynamisch unklar); tests/test_server.py:8487 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 14316 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 14325 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8476 (direkt/dynamisch unklar); tests/test_server.py:8488 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 14354 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 14358 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:278 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5894 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 14375 | `coach/context.py` | P7 | offen | tests/test_server.py:5923 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 14379 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:5914 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 14391 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 14408 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 14435 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 14444 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 14461 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 14513 | `sync/` | P6 | offen | tests/test_audit_remediation.py:269 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4535 (direkt/dynamisch unklar); tests/test_server.py:5780 (direkt/dynamisch unklar); tests/test_server.py:5808 (direkt/dynamisch unklar); tests/test_server.py:5829 (direkt/dynamisch unklar); tests/test_server.py:5856 (direkt/dynamisch unklar); tests/test_server.py:5883 (direkt/dynamisch unklar); tests/test_server.py:5907 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 14546 | `coach/context.py` | P7 | offen | tests/test_server.py:5827 (direkt/dynamisch unklar); tests/test_server.py:8219 (direkt/dynamisch unklar); tests/test_server.py:8222 (direkt/dynamisch unklar); tests/test_server.py:8236 (direkt/dynamisch unklar); tests/test_server.py:8257 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8284 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8297 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 14560 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 14575 | `coach/context.py` | P7 | offen | tests/test_server.py:5843 (direkt/dynamisch unklar); tests/test_server.py:8259 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8286 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 14584 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 14593 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 14605 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 14622 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_server.py:8225 (direkt/dynamisch unklar); tests/test_server.py:8227 (direkt/dynamisch unklar); tests/test_server.py:8301 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 14630 | `coach/context.py` | P7 | offen | tests/test_server.py:5851 (direkt/dynamisch unklar); tests/test_server.py:8231 (direkt/dynamisch unklar); tests/test_server.py:8242 (direkt/dynamisch unklar); tests/test_server.py:8258 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8306 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 14637 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 14638 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 14639 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 14639 | `coach/` | P7 | offen | tests/test_server.py:399 (direkt/dynamisch unklar); tests/test_server.py:455 (direkt/dynamisch unklar); tests/test_server.py:4788 (direkt/dynamisch unklar); tests/test_server.py:4791 (direkt/dynamisch unklar); tests/test_server.py:5141 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 14639 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 14639 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 14648 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 14656 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 14660 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 14665 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 14676 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 14701 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 14720 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 14732 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:2957 (direkt/dynamisch unklar); tests/test_server.py:2959 (direkt/dynamisch unklar); tests/test_server.py:5407 (direkt/dynamisch unklar); tests/test_server.py:5443 (direkt/dynamisch unklar); tests/test_server.py:5466 (direkt/dynamisch unklar); tests/test_server.py:5468 (direkt/dynamisch unklar); tests/test_server.py:5484 (direkt/dynamisch unklar); tests/test_server.py:5491 (direkt/dynamisch unklar); tests/test_server.py:5505 (direkt/dynamisch unklar); tests/test_server.py:5528 (direkt/dynamisch unklar); tests/test_server.py:5553 (direkt/dynamisch unklar); tests/test_server.py:5582 (direkt/dynamisch unklar); tests/test_server.py:5602 (direkt/dynamisch unklar); tests/test_server.py:5654 (direkt/dynamisch unklar); tests/test_server.py:5667 (direkt/dynamisch unklar); tests/test_server.py:5673 (direkt/dynamisch unklar); tests/test_server.py:5702 (direkt/dynamisch unklar); tests/test_server.py:5729 (direkt/dynamisch unklar); tests/test_server.py:5732 (direkt/dynamisch unklar); tests/test_server.py:5753 (direkt/dynamisch unklar); tests/test_server.py:736 (direkt/dynamisch unklar); tests/test_server.py:749 (direkt/dynamisch unklar); tests/test_server.py:825 (direkt/dynamisch unklar); tests/test_server.py:860 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 14755 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 14762 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 14769 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 14787 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 14797 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:322 (direkt/dynamisch unklar); tests/test_server.py:347 (direkt/dynamisch unklar); tests/test_server.py:4461 (direkt/dynamisch unklar); tests/test_server.py:5388 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 14810 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 14819 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 14830 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 14862 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 14888 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 14908 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 14932 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 14944 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 14957 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 14971 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 14979 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 14990 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 15012 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 15022 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 15036 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 15048 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 15062 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 15070 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 15083 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 15092 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 15114 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 15132 | `planning/` | P4 | offen | tests/test_server.py:4818 (direkt/dynamisch unklar); tests/test_server.py:4840 (direkt/dynamisch unklar); tests/test_server.py:4859 (direkt/dynamisch unklar); tests/test_server.py:4881 (direkt/dynamisch unklar); tests/test_server.py:4896 (direkt/dynamisch unklar); tests/test_server.py:4912 (direkt/dynamisch unklar); tests/test_server.py:4930 (direkt/dynamisch unklar); tests/test_server.py:4952 (direkt/dynamisch unklar); tests/test_server.py:4970 (direkt/dynamisch unklar); tests/test_server.py:4993 (direkt/dynamisch unklar); tests/test_server.py:5037 (direkt/dynamisch unklar); tests/test_server.py:5062 (direkt/dynamisch unklar); tests/test_server.py:5083 (direkt/dynamisch unklar); tests/test_server.py:5098 (direkt/dynamisch unklar); tests/test_server.py:5117 (direkt/dynamisch unklar); tests/test_server.py:5134 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 15143 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 15153 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 15170 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 15181 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 15211 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 15229 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 15235 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 15248 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 15266 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 15282 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 15295 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 15309 | `planning/` | P4 | offen | tests/test_server.py:5508 (direkt/dynamisch unklar); tests/test_server.py:5555 (direkt/dynamisch unklar); tests/test_server.py:5583 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 15343 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:1007 (direkt/dynamisch unklar); tests/test_server.py:1016 (direkt/dynamisch unklar); tests/test_server.py:380 (direkt/dynamisch unklar); tests/test_server.py:411 (direkt/dynamisch unklar); tests/test_server.py:8581 (direkt/dynamisch unklar); tests/test_server.py:929 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 15356 | `sync/reconcile.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 15368 | `sync/reconcile.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 15383 | `sync/reconcile.py` | P6 | offen | tests/test_server.py:420 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 15395 | `sync/reconcile.py` | P6 | offen | tests/test_server.py:690 (direkt/dynamisch unklar); tests/test_server.py:700 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 15425 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 15433 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 15440 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 15462 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 15469 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 15475 | `coach/context.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 15493 | `coach/context.py` | P7 | offen | tests/test_server.py:444 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 15521 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 15530 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 15557 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 15583 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 15588 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 15594 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 15608 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 15615 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 15623 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 15630 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 15639 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 15646 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 15659 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 15682 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 15696 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 15710 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 15738 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 15754 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 15773 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 15793 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 15815 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 15831 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 15848 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 15883 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 15895 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 15910 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 15930 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 15956 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 15974 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 15982 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 16003 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 16030 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 16054 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 16081 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 16102 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:1009 (direkt/dynamisch unklar); tests/test_server.py:334 (direkt/dynamisch unklar); tests/test_server.py:366 (direkt/dynamisch unklar); tests/test_server.py:390 (direkt/dynamisch unklar); tests/test_server.py:423 (direkt/dynamisch unklar); tests/test_server.py:445 (direkt/dynamisch unklar); tests/test_server.py:470 (direkt/dynamisch unklar); tests/test_server.py:477 (direkt/dynamisch unklar); tests/test_server.py:5016 (direkt/dynamisch unklar); tests/test_server.py:517 (direkt/dynamisch unklar); tests/test_server.py:5413 (direkt/dynamisch unklar); tests/test_server.py:5449 (direkt/dynamisch unklar); tests/test_server.py:546 (direkt/dynamisch unklar); tests/test_server.py:552 (direkt/dynamisch unklar); tests/test_server.py:5534 (direkt/dynamisch unklar); tests/test_server.py:556 (direkt/dynamisch unklar); tests/test_server.py:5608 (direkt/dynamisch unklar); tests/test_server.py:5632 (direkt/dynamisch unklar); tests/test_server.py:5637 (direkt/dynamisch unklar); tests/test_server.py:5686 (direkt/dynamisch unklar); tests/test_server.py:5708 (direkt/dynamisch unklar); tests/test_server.py:573 (direkt/dynamisch unklar); tests/test_server.py:577 (direkt/dynamisch unklar); tests/test_server.py:714 (direkt/dynamisch unklar); tests/test_server.py:756 (direkt/dynamisch unklar); tests/test_server.py:785 (direkt/dynamisch unklar); tests/test_server.py:804 (direkt/dynamisch unklar); tests/test_server.py:833 (direkt/dynamisch unklar); tests/test_server.py:866 (direkt/dynamisch unklar); tests/test_server.py:886 (direkt/dynamisch unklar); tests/test_server.py:913 (direkt/dynamisch unklar); tests/test_server.py:939 (direkt/dynamisch unklar); tests/test_server.py:958 (direkt/dynamisch unklar); tests/test_server.py:984 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 16144 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 16148 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 16161 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8595 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 16173 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 16192 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 16208 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 16219 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 16241 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 16256 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 16274 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 16304 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 16310 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 16324 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 16334 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 16347 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 16360 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 16377 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 16390 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5746 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 16417 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 16434 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 16439 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 16448 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 16462 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 16475 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 16485 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 16498 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 16519 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 16542 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 16553 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 16562 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 16574 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 16588 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 16596 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 16611 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 16631 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 16655 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 16669 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 16680 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 16705 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 16721 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 16736 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 16793 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 16821 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 16851 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 16867 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 16887 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 16901 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 16913 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 16923 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 16974 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 17036 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 17040 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 17045 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 17063 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 17082 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 17092 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 17118 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 17156 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 17182 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 17207 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 17238 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 17278 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 17308 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 17328 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 17386 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 17390 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 17406 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 17422 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 17454 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 17498 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 17514 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 17533 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 17559 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 17636 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 17641 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 17650 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 17655 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 17682 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 17700 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 17729 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 17748 | `coach/service.py` | P7 | offen | tests/test_server.py:4363 (direkt/dynamisch unklar); tests/test_server.py:4378 (direkt/dynamisch unklar); tests/test_server.py:4392 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 17758 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 17773 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 17805 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 17820 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4465 (direkt/dynamisch unklar); tests/test_server.py:5399 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 17833 | `coach/authorization.py` | P7 | offen | tests/test_server.py:5787 (direkt/dynamisch unklar); tests/test_server.py:5790 (direkt/dynamisch unklar); tests/test_server.py:8235 (direkt/dynamisch unklar); tests/test_server.py:8238 (direkt/dynamisch unklar); tests/test_server.py:8239 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 17852 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 17865 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 17889 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 17905 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 17916 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 17931 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:263 (direkt/dynamisch unklar); tests/test_audit_remediation.py:278 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5816 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5840 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5872 (direkt/dynamisch unklar); tests/test_server.py:5935 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 17955 | `sync/` | P6 | offen | tests/test_server.py:4541 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 17996 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:270 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4540 (direkt/dynamisch unklar); tests/test_server.py:5814 (direkt/dynamisch unklar); tests/test_server.py:5833 (direkt/dynamisch unklar); tests/test_server.py:5860 (direkt/dynamisch unklar); tests/test_server.py:5889 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 18021 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 18047 | `coach/authorization.py` | P7 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 18057 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 18061 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 18069 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 18075 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 18085 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 18102 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 18133 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 18155 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 18170 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:279 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:148 (direkt/dynamisch unklar); tests/test_server.py:5817 (direkt/dynamisch unklar); tests/test_server.py:5841 (direkt/dynamisch unklar); tests/test_server.py:5895 (direkt/dynamisch unklar); tests/test_server.py:5938 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 18191 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 18206 | `coach/authorization.py` | P7 | offen | tests/test_server.py:242 (direkt/dynamisch unklar) |
| Funktion | `local_now` | 18217 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1202 (direkt/dynamisch unklar); tests/test_server.py:1586 (direkt/dynamisch unklar); tests/test_server.py:1602 (direkt/dynamisch unklar); tests/test_server.py:1603 (direkt/dynamisch unklar); tests/test_server.py:1624 (direkt/dynamisch unklar); tests/test_server.py:1642 (direkt/dynamisch unklar); tests/test_server.py:1661 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1674 (direkt/dynamisch unklar); tests/test_server.py:1711 (direkt/dynamisch unklar); tests/test_server.py:1719 (direkt/dynamisch unklar); tests/test_server.py:1759 (direkt/dynamisch unklar); tests/test_server.py:2440 (direkt/dynamisch unklar); tests/test_server.py:2552 (direkt/dynamisch unklar); tests/test_server.py:2617 (direkt/dynamisch unklar); tests/test_server.py:2627 (direkt/dynamisch unklar); tests/test_server.py:2805 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2865 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2895 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2904 (direkt/dynamisch unklar); tests/test_server.py:3392 (direkt/dynamisch unklar); tests/test_server.py:3411 (direkt/dynamisch unklar); tests/test_server.py:3443 (direkt/dynamisch unklar); tests/test_server.py:3468 (direkt/dynamisch unklar); tests/test_server.py:3558 (direkt/dynamisch unklar); tests/test_server.py:3559 (direkt/dynamisch unklar); tests/test_server.py:3603 (direkt/dynamisch unklar); tests/test_server.py:5156 (direkt/dynamisch unklar); tests/test_server.py:5205 (direkt/dynamisch unklar); tests/test_server.py:5222 (direkt/dynamisch unklar); tests/test_server.py:5244 (direkt/dynamisch unklar); tests/test_server.py:5271 (direkt/dynamisch unklar); tests/test_server.py:5303 (direkt/dynamisch unklar); tests/test_server.py:541 (direkt/dynamisch unklar); tests/test_server.py:5978 (direkt/dynamisch unklar); tests/test_server.py:7312 (direkt/dynamisch unklar); tests/test_server.py:7630 (direkt/dynamisch unklar); tests/test_server.py:8336 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 18226 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1943 (direkt/dynamisch unklar); tests/test_server.py:1944 (direkt/dynamisch unklar); tests/test_server.py:1945 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 18234 | `sync/daily.py` | P6 | offen | tests/test_server.py:1942 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 18242 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 18247 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 18258 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 18270 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4072 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 18273 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 18280 | `coach/authorization.py` | P7 | offen | tests/test_server.py:4070 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 18297 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 18303 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 18311 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 18323 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:302 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 18355 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 18376 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 18390 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 18403 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 18422 | `http_api/bootstrap.py` | P10 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 18456 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1769 (direkt/dynamisch unklar); tests/test_server.py:1783 (direkt/dynamisch unklar); tests/test_server.py:1826 (direkt/dynamisch unklar); tests/test_server.py:1908 (direkt/dynamisch unklar); tests/test_server.py:8376 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 18530 | `http_api/` | P10 | offen | tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:2897 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 18566 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 18571 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 18575 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:98 (direkt/dynamisch unklar); tests/test_server.py:1266 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 18582 | `http_api/` | P10 | offen | tests/test_server.py:1238 (direkt/dynamisch unklar); tests/test_server.py:1246 (direkt/dynamisch unklar); tests/test_server.py:1669 (direkt/dynamisch unklar); tests/test_server.py:1714 (direkt/dynamisch unklar); tests/test_server.py:2379 (direkt/dynamisch unklar); tests/test_server.py:3608 (direkt/dynamisch unklar); tests/test_server.py:7241 (direkt/dynamisch unklar); tests/test_server.py:8376 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 18694 | `diagnostics/report.py` | P9 | offen | tests/test_server.py:7775 (direkt/dynamisch unklar); tests/test_server.py:7827 (direkt/dynamisch unklar); tests/test_server.py:7941 (direkt/dynamisch unklar); tests/test_server.py:7972 (direkt/dynamisch unklar); tests/test_server.py:8147 (direkt/dynamisch unklar); tests/test_server.py:8183 (direkt/dynamisch unklar); tests/test_server.py:8432 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 18711 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 18727 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 18748 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 18762 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 18778 | `diagnostics/report.py` | P9 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 18787 | `diagnostics/report.py` | P9 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7690 (direkt/dynamisch unklar); tests/test_server.py:7692 (direkt/dynamisch unklar); tests/test_server.py:7693 (direkt/dynamisch unklar); tests/test_server.py:7740 (direkt/dynamisch unklar); tests/test_server.py:7803 (direkt/dynamisch unklar); tests/test_server.py:7818 (direkt/dynamisch unklar); tests/test_server.py:8549 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 18850 | `privacy.py` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1449 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 18900 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 18901 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 18925 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 18929 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 18940 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 18944 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 18954 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 18962 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:187 (direkt/dynamisch unklar); tests/test_server.py:1464 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 19101 | `db/manager.py` | P1 | offen | tests/test_server.py:6507 (direkt/dynamisch unklar); tests/test_server.py:6520 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 19104 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 19117 | `backup/` | P9 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_server.py:6496 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 19126 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 19147 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1492 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 19158 | `backup/` | P9 | offen | tests/test_audit_remediation.py:293 (direkt/dynamisch unklar); tests/test_server.py:6497 (direkt/dynamisch unklar); tests/test_server.py:6513 (direkt/dynamisch unklar); tests/test_server.py:6526 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 19163 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 19172 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 19189 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 19201 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 19219 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 19226 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 19247 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1532 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1548 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4554 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5393 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8495 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 19260 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1541 (direkt/dynamisch unklar); tests/test_server.py:1545 (direkt/dynamisch unklar); tests/test_server.py:1551 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 19275 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 19282 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 19289 | `privacy.py` | P9 | offen | tests/test_server.py:1544 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 19304 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:103 (direkt/dynamisch unklar); tests/test_provider_review.py:116 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (direkt/dynamisch unklar); tests/test_provider_review.py:146 (direkt/dynamisch unklar); tests/test_provider_review.py:164 (direkt/dynamisch unklar); tests/test_server.py:1533 (direkt/dynamisch unklar); tests/test_server.py:1549 (direkt/dynamisch unklar); tests/test_server.py:8496 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 19333 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 19334 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 19335 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 19336 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 19337 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 19338 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1364 (direkt/dynamisch unklar); tests/test_server.py:1372 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 19339 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1369 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 19340 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 19341 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 19342 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 19343 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7905 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 19346 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 19350 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:185 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7907 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 19375 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 19384 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1328 (direkt/dynamisch unklar); tests/test_server.py:1357 (direkt/dynamisch unklar); tests/test_server.py:1360 (direkt/dynamisch unklar); tests/test_server.py:1409 (direkt/dynamisch unklar); tests/test_server.py:1416 (direkt/dynamisch unklar); tests/test_server.py:5802 (direkt/dynamisch unklar); tests/test_server.py:5806 (direkt/dynamisch unklar); tests/test_server.py:5821 (direkt/dynamisch unklar); tests/test_server.py:5825 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 19388 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 19398 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1370 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 19413 | `performance/` | P3 | offen | tests/test_server.py:7870 (direkt/dynamisch unklar); tests/test_server.py:7880 (direkt/dynamisch unklar); tests/test_server.py:7888 (direkt/dynamisch unklar); tests/test_server.py:7895 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 19455 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1334 (direkt/dynamisch unklar); tests/test_server.py:1337 (direkt/dynamisch unklar); tests/test_server.py:1358 (direkt/dynamisch unklar); tests/test_server.py:1391 (direkt/dynamisch unklar); tests/test_server.py:1428 (direkt/dynamisch unklar); tests/test_server.py:3304 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 19481 | `http_api/auth.py` | P10 | offen | tests/test_provider_review.py:188 (direkt/dynamisch unklar); tests/test_provider_review.py:191 (direkt/dynamisch unklar); tests/test_provider_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:3301 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 19500 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1427 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 19508 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 19520 | `http_api/` | P10 | offen | tests/test_server.py:1409 (direkt/dynamisch unklar); tests/test_server.py:1416 (direkt/dynamisch unklar); tests/test_server.py:3306 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 19526 | `http_api/` | P10 | offen | tests/test_server.py:1309 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 19539 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:209 (direkt/dynamisch unklar); tests/test_server.py:1512 (direkt/dynamisch unklar); tests/test_server.py:1807 (direkt/dynamisch unklar); tests/test_server.py:7418 (direkt/dynamisch unklar); tests/test_server.py:7428 (direkt/dynamisch unklar); tests/test_server.py:7434 (direkt/dynamisch unklar); tests/test_server.py:7444 (direkt/dynamisch unklar); tests/test_server.py:7456 (direkt/dynamisch unklar); tests/test_server.py:7461 (direkt/dynamisch unklar); tests/test_server.py:7465 (direkt/dynamisch unklar); tests/test_server.py:7468 (direkt/dynamisch unklar); tests/test_server.py:7474 (direkt/dynamisch unklar); tests/test_server.py:7484 (direkt/dynamisch unklar); tests/test_server.py:7491 (direkt/dynamisch unklar); tests/test_server.py:7498 (direkt/dynamisch unklar); tests/test_server.py:7505 (direkt/dynamisch unklar); tests/test_server.py:8248 (direkt/dynamisch unklar); tests/test_server.py:8271 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 20218 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:209 (direkt/dynamisch unklar); tests/test_server.py:222 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_loop` | 20223 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 20236 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 20240 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 20246 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 20252 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 20258 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 20266 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:155 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 20273 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 20287 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 20292 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 20304 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 20316 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 20321 | `sync/` | P6 | offen | tests/test_server.py:1023 (direkt/dynamisch unklar); tests/test_server.py:1032 (direkt/dynamisch unklar); tests/test_server.py:226 (Monkeypatch/getattr/sys.modules) |
| Funktion | `main` | 20329 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar); tests/test_server.py:229 (direkt/dynamisch unklar) |

## Zielverteilung

| Zielmodul | Einträge |
| --- | ---: |
| `activities/` | 44 |
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
| `backend/providers` | 3 |
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
| `coach/authorization.py` | 48 |
| `coach/context.py` | 51 |
| `coach/conversation.py` | 8 |
| `coach/dialogue.py` | 18 |
| `coach/jobs.py` | 6 |
| `coach/morning.py` | 3 |
| `coach/proposals.py` | 60 |
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
| `performance/` | 55 |
| `performance/activity_validation.py` | 4 |
| `planning/` | 227 |
| `planning/calendar.py` | 1 |
| `planning/competitions.py` | 93 |
| `privacy.py` | 8 |
| `providers/` | 83 |
| `providers/calendar.py` | 15 |
| `providers/http.py` | 15 |
| `providers/intervals_client.py` | 1 |
| `providers/workout_text.py` | 12 |
| `runtime/` | 2 |
| `server.py / Composition Root` | 55 |
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
