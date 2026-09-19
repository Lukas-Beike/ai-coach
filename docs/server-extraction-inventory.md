# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `c1ae03057cf4cf97c9348983223f72f4eb5c71b6f0f9db80157deb589038a723`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 21.127 physische Zeilen
- Inventareinträge: 1.650
- Definitionen (Funktionen/Klassen): 1.181
- Globale Bindungen einschließlich Imports: 271 Zuweisungen. 198 Imports
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
| P1 | 22 | 40 | 146 |
| P2 | 168 | 23 | 0 |
| P3 | 187 | 27 | 0 |
| P4 | 298 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 223 | 43 | 0 |
| P7 | 186 | 37 | 0 |
| P8 | 17 | 13 | 0 |
| P9 | 25 | 6 | 0 |
| P10 | 30 | 39 | 0 |
| P11 | 1 | 3 | 52 |

## Referenzanalyse außerhalb von server.py

Direkte `server.<name>`-Zugriffe und erkennbare Import-/Patchstellen sind pro Eintrag in der Tabelle vermerkt. Die Ortsangaben decken `backend/`, `tests/`, `e2e/`, `scripts/`, Docker und GitHub-Workflows ab.

### Dynamische Zugriffe und Monkeypatches

Diese Stellen benötigen bei jeder Migration eine manuelle Prüfung des Lookup-Ortes:

- `tests/support.py:106: patch.object(server, "CONFIG", replace(server.CONFIG, app_password=app_password)),`
- `tests/support.py:107: patch.object(server, "DATA_DIR", root),`
- `tests/support.py:108: patch.object(server, "DB_PATH", root / "test.db"),`
- `tests/support.py:109: patch.object(server, "LOG_PATH", root / "test.log"),`
- `tests/test_audit_remediation.py:106: with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):`
- `tests/test_audit_remediation.py:147: with patch.object(server, "weather_state", return_value={"stale": True, "days": [{}], "error": "Synthetic failure"}):`
- `tests/test_audit_remediation.py:153: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="", calendar_ical_url="")), patch.object(server, "garmin_fixture_path", return_value="synthetic"), patch.object(server, "daily_sync_due", return_value=True):`
- `tests/test_audit_remediation.py:190: startup = patch.object(server.app_config, "security_configuration_error", return_value=None)`
- `tests/test_audit_remediation.py:228: with patch.object(server, "apply_adaptive_replan", return_value={"status": "applied"}) as mutation:`
- `tests/test_audit_remediation.py:246: with patch.object(server, "ensure_conversation", return_value="synthetic"), patch.object(server, "build_training_context", side_effect=["Old Garmin data", "Fresh Garmin data"]) as context, patch.object(server, "responses_request", side_effect=response) as model:`
- `tests/test_audit_remediation.py:262: with patch.object(server, "_restore_coach_session_csrf_hash", side_effect=restore), patch.object(server, "chat_with_coach", side_effect=coach) as execute:`
- `tests/test_audit_remediation.py:270: with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="synthetic-encrypted-key")), patch.object(server, "DATA_DIR", root), patch.object(server, "DB_PATH", root / "test.db"), patch.object(server, "LOG_PATH", root / "test.log"):`
- `tests/test_audit_remediation.py:285: with patch.object(server, "sync_intervals", return_value={"status": "ok"}), patch.object(server, "chat_with_coach", return_value={"status": "failed"}), patch.object(server, "garmin_fixture_path", return_value=None):`
- `tests/test_audit_remediation.py:43: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:54: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:70: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:81: with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):`
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
- `tests/test_server.py:1018: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=True) as active, patch.object(`
- `tests/test_server.py:1027: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=False), patch.object(`
- `tests/test_server.py:1029: ), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:1209: with patch.object(server, "_fetch_weather_forecast", side_effect=[old, new]) as fetch:`
- `tests/test_server.py:1235: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1263: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1277: with patch.object(server, "_fetch_weather_forecast", return_value=forecast) as fetch:`
- `tests/test_server.py:1296: with patch.object(server, "_fetch_weather_forecast", side_effect=[server.AppError(503, "upstream"), forecast]) as fetch:`
- `tests/test_server.py:1312: with patch.object(server, "CONFIG", replace(server.CONFIG, secure_cookies=True)):`
- `tests/test_server.py:1530: with patch.object(server, "delete_remote_conversation", side_effect=server.AppError(503, "upstream")):`
- `tests/test_server.py:1546: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:1563: with patch.object(server, "_fetch_weather_forecast", return_value=forecast), patch.object(`
- `tests/test_server.py:1579: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("coach context must not refresh weather")):`
- `tests/test_server.py:1589: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1606: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1616: with patch.object(server, "latest_replan_preview", return_value={"status": "preview", "changes": [{"date": "2026-09-01"}]}):`
- `tests/test_server.py:1640: self.assertEqual(getattr(server.local_now().tzinfo, "key", None), "UTC")`
- `tests/test_server.py:1659: with patch.object(server, "local_now", return_value=fixed_now):`
- `tests/test_server.py:175: with patch.object(server, "CONFIG", config), patch.object(server, "DATA_DIR", Path(temporary)), patch.object(`
- `tests/test_server.py:1780: with patch.object(server, "http_json", side_effect=AssertionError("network")), patch.object(server, "external_call", side_effect=AssertionError("network")):`
- `tests/test_server.py:1823: with patch.object(server.sqlite3, "connect", wraps=sqlite3.connect) as connect:`
- `tests/test_server.py:1901: with patch.object(server, "state_versions", return_value={"activities": "v1"}):`
- `tests/test_server.py:204: with patch.object(server, "resume_interrupted_sync_jobs") as sync_recovery, patch.object(`
- `tests/test_server.py:214: with patch.object(server.observability, "configure_logging"), patch.object(`
- `tests/test_server.py:216: ), patch.object(server, "initialise_database", side_effect=lambda: order.append("schema")), patch.object(`
- `tests/test_server.py:220: ), patch.object(server, "CoachHTTPServer", return_value=http_server), patch.object(`
- `tests/test_server.py:224: ), patch.object(server, "enqueue_startup_sync_jobs"), patch.object(`
- `tests/test_server.py:226: ), patch.object(server.threading, "Thread"):`
- `tests/test_server.py:234: with patch.object(server, "resume_interrupted_sync_jobs") as sync_recovery, patch.object(`
- `tests/test_server.py:236: ) as coach_recovery, patch.object(server.threading, "Thread") as thread, patch.object(`
- `tests/test_server.py:238: ), patch.object(server, "COACH_JOB_WORKER", None):`
- `tests/test_server.py:255: with patch.object(server, "_execute_sync_job", return_value={"status": "ok"}):`
- `tests/test_server.py:2577: with patch.object(server, "CONFIG", replace(server.CONFIG, calendar_ical_url="https://calendar.example/feed.ics")), patch.object(`
- `tests/test_server.py:2579: ), patch.object(server, "fetch_calendar_feed", return_value=b"not an ical feed"):`
- `tests/test_server.py:2585: with patch.object(server.socket, "getaddrinfo", return_value=[(None, None, None, None, ("100.64.0.1", 443))]):`
- `tests/test_server.py:2609: with patch.object(server, "_resolve_calendar_addresses", return_value=addresses) as resolve, patch.object(`
- `tests/test_server.py:2611: ), patch.object(server.socket, "create_connection", side_effect=[OSError("first address unavailable"), raw_socket]) as connect, patch.object(`
- `tests/test_server.py:2625: ), patch.object(server.socket, "create_connection", side_effect=TimeoutError("calendar timeout")):`
- `tests/test_server.py:2664: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload), patch.object(`
- `tests/test_server.py:266: with patch.object(server, "_execute_sync_job", side_effect=server.AppError(503, provider_detail, reason="network_error")):`
- `tests/test_server.py:2693: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload):`
- `tests/test_server.py:2708: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", side_effect=server.AppError(502, "upstream unavailable")):`
- `tests/test_server.py:2775: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:277: with patch.object(server, "sync_garmin") as sync:`
- `tests/test_server.py:2870: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=-1)):`
- `tests/test_server.py:2879: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=30)):`
- `tests/test_server.py:2889: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:2936: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)):`
- `tests/test_server.py:2996: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 20, 0)):`
- `tests/test_server.py:299: with patch.object(server, "_execute_sync_job", return_value=result):`
- `tests/test_server.py:3023: patch.object(server, "latest_snapshot", return_value=snapshot),`
- `tests/test_server.py:3024: patch.object(server, "list_dated_local_planned_workouts", return_value=planned),`
- `tests/test_server.py:3025: patch.object(server, "weather_state", return_value={"days": []}),`
- `tests/test_server.py:3026: patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)),`
- `tests/test_server.py:309: with patch.object(server, "_repair_local_planned_unit_calendar_entry", return_value=None) as repair:`
- `tests/test_server.py:3430: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:387: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-plan-push"}) as enqueue:`
- `tests/test_server.py:3925: with patch.object(server.IntervalsClient, "get_workout_library", return_value=[]), \`
- `tests/test_server.py:3926: patch.object(server.IntervalsClient, "create_library_workouts", return_value=[{"id": "synthetic-remote", "type": "Ride"}]) as create, \`
- `tests/test_server.py:3927: patch.object(server.IntervalsClient, "update_library_workout", return_value={"id": "synthetic-remote", **parsed_workout_fixture()}) as update:`
- `tests/test_server.py:3945: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=[`
- `tests/test_server.py:3970: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:3988: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:3990: ), patch.object(server.IntervalsClient, "create_library_workouts") as create:`
- `tests/test_server.py:418: with patch.object(server, "_mark_local_planning_authoritative"), patch.object(`
- `tests/test_server.py:4197: with patch.object(server, "garmin_fixture_path", return_value="fixture.json"), \`
- `tests/test_server.py:4198: patch.object(server, "sync_garmin") as sync_garmin, \`
- `tests/test_server.py:4199: patch.object(server, "garmin_sleep_ready_for_checkin", return_value=False), \`
- `tests/test_server.py:4244: with patch.object(server, "CONFIG", config), patch.object(server, "Garmin", FakeGarmin):`
- `tests/test_server.py:4413: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:442: with patch.object(server, "_enqueue_coach_plan_push") as enqueue, self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:4457: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=fake_urlopen):`
- `tests/test_server.py:4482: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4606: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value=response):`
- `tests/test_server.py:4621: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4632: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4646: with patch.object(server, "CONFIG", replace(server.CONFIG, gemini_api_key=key)):`
- `tests/test_server.py:4652: with patch.object(server, "CONFIG", config), patch.object(server, "gemini_responses_request", return_value={"output_text": "ok"}) as gemini, patch.object(server, "openai_request") as openai:`
- `tests/test_server.py:4665: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4685: with patch.object(server, "CONFIG", config), patch.object(server, "delete_remote_conversation", return_value=True) as delete:`
- `tests/test_server.py:4709: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:474: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-competition"}) as enqueue:`
- `tests/test_server.py:4756: with patch.object(server, "urlopen", side_effect=blocked_urlopen):`
- `tests/test_server.py:4787: with patch.object(server, "urlopen", return_value=response):`
- `tests/test_server.py:4820: with patch.object(server, "urlopen", side_effect=return_cancelled_response):`
- `tests/test_server.py:4839: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")), patch.object(`
- `tests/test_server.py:4858: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4861: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url="")):`
- `tests/test_server.py:4869: with self.subTest(invalid=invalid), patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url=invalid)):`
- `tests/test_server.py:4882: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4906: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:4913: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:5085: with patch.object(server, "calendar_conflicts", return_value=[{"name": "Occupied"}]) as conflicts:`
- `tests/test_server.py:5399: with patch.object(server, "structured_athlete_context", return_value={"source_policy": {"untrusted": "x" * 200_000}}):`
- `tests/test_server.py:5506: with patch.object(server, "openai_request", side_effect=fake_openai):`
- `tests/test_server.py:5512: with patch.object(server, "http_json", return_value=response), patch.object(`
- `tests/test_server.py:5528: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:5642: with patch.object(server, "CHANGE_HISTORY_MAX_ROWS", 3), self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:570: with patch.object(server, "enqueue_sync_job", side_effect=[{"id": "job-performance"}, {"id": "job-competition"}]) as enqueue:`
- `tests/test_server.py:5779: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 2):`
- `tests/test_server.py:5793: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 1):`
- `tests/test_server.py:5879: with patch.object(server, "save_workout_library_entries", side_effect=RuntimeError("creation failed")):`
- `tests/test_server.py:5881: server._apply_training_patch(arguments, {`
- `tests/test_server.py:5898: with patch.object(server, "responses_request", side_effect=create), patch.object(`
- `tests/test_server.py:5903: ) as retrieve, patch.object(server, "OPENAI_BACKGROUND_POLL_SECONDS", 0), patch.object(server, "record_openai_usage"):`
- `tests/test_server.py:593: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:5951: with patch.object(server, "chat_with_coach", side_effect=lambda *args, **kwargs: seen.update(kwargs) or {}):`
- `tests/test_server.py:5975: with patch.object(server, "chat_with_coach", side_effect=complete_chat):`
- `tests/test_server.py:6004: with patch.object(server, "responses_stream_request", side_effect=streamed_response) as streamed, patch.object(`
- `tests/test_server.py:6029: ), patch.object(server, "_restore_coach_session_csrf_hash", return_value="csrf-background-requeue"):`
- `tests/test_server.py:606: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:6070: with patch.object(server, "chat_with_coach", side_effect=capture_phase), patch.object(`
- `tests/test_server.py:6106: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6108: ) as fetch_snapshot, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:6119: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6135: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6137: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6148: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6150: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6166: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6179: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:617: with patch.object(server, "sync_intervals", return_value={"status": "ok"}) as sync, patch.object(`
- `tests/test_server.py:6207: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6209: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=remote) as get_library:`
- `tests/test_server.py:6247: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6249: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6269: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6273: ) as import_units, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6291: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6293: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[{`
- `tests/test_server.py:629: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6310: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6314: ) as library_sync, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6329: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6383: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6392: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6411: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6420: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6429: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6437: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6454: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:648: with patch.object(server, "CONFIG", config), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:6498: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6512: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_server.py:6530: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6575: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6577: ), patch.object(server, "_sync_selected_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:657: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:659: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:6600: with patch.object(server, "IntervalsClient", FailingIntervalsClient), patch.object(`
- `tests/test_server.py:6610: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:661: ) as enqueue, patch.object(server, "_wait_for_performance_refresh") as wait:`
- `tests/test_server.py:6623: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", db_path), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6668: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:6689: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6698: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir), patch.dict(`
- `tests/test_server.py:670: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6718: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir):`
- `tests/test_server.py:672: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:6865: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6897: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6935: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6967: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6983: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:7022: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7055: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7082: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7365: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:7366: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:7495: with patch.object(server, "http_json", side_effect=[`
- `tests/test_server.py:7578: with patch.object(server.LOGGER, "info") as logger:`
- `tests/test_server.py:7755: with patch.object(server.IntervalsClient, "delete_activity", return_value=None) as delete:`
- `tests/test_server.py:7805: with patch.object(server, "get_kv", side_effect=get_kv_after_read):`
- `tests/test_server.py:7837: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7859: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7865: with patch.object(server, "external_calendar_url", return_value=calendar_url), patch.object(`
- `tests/test_server.py:7887: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7906: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7923: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7957: with patch.object(server, "urlopen", side_effect=server.URLError("offline")):`
- `tests/test_server.py:7974: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7988: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7998: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8014: with patch.object(server, "database", side_effect=OSError("database unavailable")):`
- `tests/test_server.py:8022: with patch.object(server.tempfile, "NamedTemporaryFile", side_effect=OSError("read-only")):`
- `tests/test_server.py:8041: with patch.object(server.time, "monotonic", return_value=20 * 60):`
- `tests/test_server.py:8070: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:8072: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[]):`
- `tests/test_server.py:8099: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8135: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8162: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8203: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8238: with patch.object(server, "openai_request", side_effect=fake_request), patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8309: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8351: with patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:8364: with patch.object(server, "urlopen") as urlopen:`
- `tests/test_server.py:8388: with patch.object(server, "urlopen", return_value=TimeoutResponse()):`
- `tests/test_server.py:8413: with patch.object(server, "urlopen", return_value=DisconnectResponse()):`
- `tests/test_server.py:8421: with patch.object(server, "openai_stream_request", side_effect=responses) as request, patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8468: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), \`
- `tests/test_server.py:8469: patch.object(server, "unregister_chat_stream") as unregister, \`
- `tests/test_server.py:8470: patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8495: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), patch.object(`
- `tests/test_server.py:8497: ) as unregister, patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8549: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value={"status": "completed"}) as request:`
- `tests/test_server.py:8602: with patch.object(server, "DB_LOCK", database_lock), patch.object(`
- `tests/test_server.py:8619: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8706: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:8720: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8731: with patch.object(server, "CONFIG", replace(config, intervals_api_key="")):`
- `tests/test_server.py:8788: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:910: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-changed"}) as enqueue:`
- `tests/test_server.py:936: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-large-changed"}) as enqueue:`
- `tests/test_server.py:981: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-all"}) as enqueue:`
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
| `ProviderResyncGate` | 305 | – | `AppError`, `contextmanager`, `threading` | – | – |
| `provider_operation` | 356 | – | `GARMIN_RESYNC_GATE`, `INTERVALS_RESYNC_GATE` | – | – |
| `intervals_operation` | 361 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `garmin_operation` | 369 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `IntervalsClient` | 380 | `_raise_chat_cancelled`, `compact_snapshot`, `deduplicate_api_records`, `intervals_workout_sport`, `latest_snapshot`, `local_now`, `selected`, `sync_date_windows`, `validate_intervals_workout_result`, `validate_workout_description`, `workout_event_payload` | `ALL_SYNC_DAYS`, `APP_NAME`, `Any`, `AppError`, `CONFIG`, `Callable`, `Config`, `IntervalsReadTransport`, `IntervalsWriteTransport`, `PLANNED_CALENDAR_FUTURE_DAYS`, `PLANNED_CALENDAR_HISTORY_DAYS`, `_raise_chat_cancelled`, … (+18) | – | – |
| `external_call` | 687 | `operation_error_code` | `Any`, `AppError`, `DATA_DIR`, `DIAGNOSTIC_CAPTURE`, `LOGGER`, `LOG_PATH`, `OPERATION_CONTEXT`, `REDACTOR`, `observability`, `operation_error_code`, `provider_error`, `time` | – | – |
| `serialise_conversation` | 879 | – | `AppError`, `CHAT_LOCK_TIMEOUT_SECONDS`, `CHAT_QUEUE`, `OPENAI_CONVERSATION_LOCK`, `wraps` | – | – |
| `utc_now` | 896 | – | `datetime`, `timezone` | – | – |
| `operation_trigger` | 969 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 975 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 984 | – | `Any` | – | – |
| `log_operation_event` | 994 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1021 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1042 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count`, `runtime_maintenance`, `wraps` | – | – |
| `database_manager` | 1085 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE` | – |
| `database` | 1112 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1118 | `database`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `KEY_VALUE_REPOSITORY`, `PROVIDER_RESYNC_KEYS`, `database`, `datetime`, `initialize_application_database`, `json`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_cleanup` | 1130 | – | `Any`, `cleanup_refresh_history`, `datetime`, `sync_freshness`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1138 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `runtime_events`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1150 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `runtime_events`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1184 | – | – | – | – |
| `_sync_job_error_class` | 1199 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1213 | – | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1222 | – | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1236 | `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1249 | `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1259 | `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1268 | – | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1278 | – | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1285 | `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1310 | `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1319 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1325 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1330 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1353 | – | `AppError` | – | – |
| `_pending_performance_job_id` | 1361 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1370 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1388 | `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1415 | – | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1424 | – | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1431 | – | `Any` | – | – |
| `_insert_sync_job` | 1441 | – | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 1466 | – | `Any`, `runtime_events` | – | – |
| `enqueue_sync_job` | 1480 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `runtime_maintenance`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 1507 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 1527 | `database`, `utc_now` | `Any`, `DB_LOCK`, `database`, `runtime_maintenance`, `utc_now` | – | – |
| `_sync_job_update` | 1548 | `database`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `runtime_events`, `utc_now` | – | – |
| `_sync_job_item_results` | 1586 | – | `Any` | – | – |
| `_sync_job_result_target` | 1592 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 1603 | `_sync_job_result_target` | `Any`, `REDACTOR`, `_sync_job_result_target` | – | – |
| `_sync_job_completion_snapshot` | 1623 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 1638 | – | `runtime_events` | – | – |
| `_sync_job_update_from_result` | 1655 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 1668 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 1677 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 1684 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 1701 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 1713 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 1725 | `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 1748 | – | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 1757 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 1777 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 1797 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | `Any`, `LOGGER`, `REDACTOR`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | – | – |
| `_run_claimed_sync_job` | 1815 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `runtime_maintenance` | – | – |
| `_sync_job_worker_loop` | 1825 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job`, `runtime_maintenance` | – | – |
| `start_sync_job_worker` | 1840 | – | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 1851 | `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_current_provider_freshness` | 1874 | `_garmin_core_error_entries`, `database`, `get_profile` | `Any`, `CONFIG`, `DB_LOCK`, `Path`, `_garmin_core_error_entries`, `database`, `datetime`, `get_kv`, `get_profile`, `sync_freshness`, `timezone` | – | – |
| `_audit_projection_fields` | 1888 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 1902 | – | `Any`, `json` | – | – |
| `_audit_projection` | 1913 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 1937 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 1942 | – | `Any` | – | – |
| `_cleanup_change_history` | 1954 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 1964 | – | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 1981 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2020 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2052 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2063 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2075 | – | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2089 | – | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2105 | `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2143 | `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2163 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2173 | `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2198 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2219 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2229 | `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2238 | `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2264 | `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2280 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2309 | `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2324 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |
| `sync_period` | 2365 | `get_kv` | `ALL_SYNC_DAYS`, `SYNC_PERIOD_DEFAULTS`, `get_kv` | – | – |
| `set_sync_period` | 2376 | `set_kv` | `ALL_SYNC_DAYS`, `Any`, `AppError`, `set_kv` | – | – |
| `sync_date_windows` | 2388 | `local_now` | `ALL_SYNC_DAYS`, `SYNC_CHUNK_DAYS`, `SYNC_EARLIEST_DATE`, `date`, `local_now`, `split_date_windows` | – | – |
| `provider_sync_cursor` | 2399 | `database` | `Any`, `DB_LOCK`, `database`, `read_cursor` | – | – |
| `update_provider_sync_cursor` | 2404 | `database`, `utc_now` | `DB_LOCK`, `database`, `utc_now`, `write_cursor` | – | – |
| `set_kv` | 2410 | `database`, `set_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `set_kv`, `sqlite3` | – | – |
| `_coach_error_metadata` | 2422 | – | `Any`, `Path`, `ROOT`, `observability` | – | – |
| `_safe_response_headers` | 2437 | – | `Any`, `REDACTOR` | – | – |
| `garmin_snapshot` | 2454 | `get_kv` | `Any`, `get_kv`, `json` | – | – |
| `garmin_configured` | 2462 | – | `CONFIG`, `Garmin` | – | – |
| `garmin_fixture_path` | 2466 | – | `CONFIG`, `Path`, `ROOT` | – | – |
| `activity_datetime` | 2474 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `activity_kind` | 2486 | – | `Any` | – | – |
| `_cycling_event_candidates` | 2501 | `activity_kind` | `Any`, `activity_kind` | – | – |
| `_cycling_event_interval` | 2511 | `activity_datetime`, `as_number` | `Any`, `activity_datetime`, `as_number`, `datetime`, `timedelta` | – | – |
| `_cycling_intervals_share_group` | 2522 | – | `datetime` | – | – |
| `_cycling_event_edges` | 2531 | `_cycling_intervals_share_group` | `_cycling_intervals_share_group`, `datetime` | – | – |
| `_cycling_event_group` | 2546 | – | `Any` | – | – |
| `parallel_cycling_event_groups` | 2560 | `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | `Any`, `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | – | – |
| `_garmin_duplicate_measurements` | 2572 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_activity_matches` | 2588 | `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | `Any`, `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | – | – |
| `garmin_activity_duplicates_intervals` | 2603 | `_garmin_activity_matches` | `Any`, `_garmin_activity_matches` | – | – |
| `filter_garmin_activities` | 2610 | `garmin_activity_duplicates_intervals` | `Any`, `garmin_activity_duplicates_intervals` | – | – |
| `intervals_activity_device_source` | 2617 | – | `Any` | – | – |
| `intervals_cycling_activities_match` | 2632 | `activity_datetime`, `activity_kind`, `as_number`, `first_present` | `Any`, `activity_datetime`, `activity_kind`, `as_number`, `first_present` | – | – |
| `_latest_activity_id` | 2655 | `activity_datetime`, `first_present` | `Any`, `activity_datetime`, `first_present` | – | – |
| `_wahoo_garmin_pairs` | 2668 | `activity_datetime`, `activity_kind`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | `Any`, `activity_datetime`, `activity_kind`, `datetime`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | – | – |
| `_wahoo_garmin_duplicate_view` | 2686 | `first_present` | `Any`, `datetime`, `first_present` | – | – |
| `latest_wahoo_garmin_duplicate` | 2704 | `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | `Any`, `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | – | – |
| `garmin_activity_max_hr` | 2719 | `activity_kind`, `as_number`, `first_present` | `Any`, `activity_kind`, `as_number`, `first_present` | – | – |
| `merge_garmin_max_hr` | 2734 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_key` | 2762 | – | `Any` | – | – |
| `_garmin_numeric` | 2766 | `as_number`, `first_present` | `Any`, `as_number`, `first_present` | – | – |
| `_garmin_vo2_value` | 2772 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_colon_duration_seconds` | 2777 | – | – | – | – |
| `_garmin_duration_seconds` | 2786 | `_garmin_colon_duration_seconds`, `as_number`, `first_present` | `Any`, `_garmin_colon_duration_seconds`, `as_number`, `first_present` | – | – |
| `_garmin_race_slot` | 2805 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_race_time` | 2818 | `_garmin_duration_seconds` | `Any`, `_garmin_duration_seconds` | – | – |
| `_garmin_weight_kg` | 2822 | `_garmin_key`, `as_number`, `first_present` | `Any`, `_garmin_key`, `as_number`, `first_present` | – | – |
| `_garmin_record_date` | 2840 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_collect_garmin_weight_records` | 2854 | `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | `Any`, `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | – | – |
| `garmin_weight_records` | 2870 | `_collect_garmin_weight_records` | `Any`, `_collect_garmin_weight_records` | – | – |
| `garmin_weight_metric` | 2876 | `garmin_weight_records`, `metric` | `Any`, `GARMIN_PERFORMANCE_SOURCE`, `garmin_weight_records`, `metric` | – | – |
| `garmin_weight_average` | 2884 | `garmin_weight_records` | `Any`, `date`, `garmin_weight_records`, `timedelta` | – | – |
| `_collect_garmin_numeric_values` | 2897 | `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | `Any`, `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | – | – |
| `_garmin_last_numeric` | 2910 | `_collect_garmin_numeric_values` | `Any`, `_collect_garmin_numeric_values` | – | – |
| `_garmin_last_value` | 2917 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_bounded_metric` | 2935 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_pace_seconds` | 2940 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_mapping_nodes` | 2966 | `_garmin_mapping_nodes` | `Any`, `Iterator`, `_garmin_mapping_nodes` | – | – |
| `_garmin_sport_category` | 2976 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `garmin_profile_max_hr` | 2985 | `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | `Any`, `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | – | – |
| `_garmin_collect_vo2_values` | 2995 | `_garmin_collect_vo2_values`, `_garmin_key`, `_garmin_sport_category`, `_garmin_vo2_value` | `Any`, `_garmin_collect_vo2_values`, `_garmin_key`, `_garmin_sport_category`, `_garmin_vo2_value` | – | – |

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
| Importbindung | `calendar_module` | 8 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `difflib` | 9 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `hashlib` | 10 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `hmac` | 11 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ipaddress` | 12 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2607 (direkt/dynamisch unklar); tests/test_server.py:2624 (direkt/dynamisch unklar) |
| Importbindung | `json` | 13 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_workout_repair.py:572 (direkt/dynamisch unklar) |
| Importbindung | `logging` | 14 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `math` | 15 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `mimetypes` | 16 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `os` | 17 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `platform` | 18 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `queue` | 19 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:8464 (direkt/dynamisch unklar); tests/test_server.py:8490 (direkt/dynamisch unklar) |
| Importbindung | `re` | 20 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `secrets` | 21 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_coach_language_recovery.py:42 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:69 (direkt/dynamisch unklar) |
| Importbindung | `shutil` | 22 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `socket` | 23 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2585 (direkt/dynamisch unklar); tests/test_server.py:2592 (direkt/dynamisch unklar); tests/test_server.py:2611 (direkt/dynamisch unklar); tests/test_server.py:2625 (direkt/dynamisch unklar) |
| Importbindung | `ssl` | 24 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2610 (direkt/dynamisch unklar) |
| Importbindung | `sqlite3` | 25 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1066 (direkt/dynamisch unklar); tests/test_server.py:1241 (direkt/dynamisch unklar); tests/test_server.py:1823 (direkt/dynamisch unklar) |
| Importbindung | `threading` | 26 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_diagnostic_followups.py:170 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:37 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:56 (direkt/dynamisch unklar); tests/test_server.py:226 (direkt/dynamisch unklar); tests/test_server.py:236 (direkt/dynamisch unklar) |
| Importbindung | `tempfile` | 27 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:8022 (direkt/dynamisch unklar) |
| Importbindung | `time` | 28 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/support.py:130 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:108 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:41 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:95 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:38 (direkt/dynamisch unklar); tests/test_coach_review.py:257 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:257 (direkt/dynamisch unklar); tests/test_server.py:1355 (direkt/dynamisch unklar); tests/test_server.py:1368 (direkt/dynamisch unklar); tests/test_server.py:4279 (direkt/dynamisch unklar); tests/test_server.py:8041 (direkt/dynamisch unklar); tests/test_server.py:8238 (direkt/dynamisch unklar); tests/test_server.py:8421 (direkt/dynamisch unklar) |
| Importbindung | `uuid` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `zipfile` | 30 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ContextVar` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `nullcontext` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `contextmanager` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `dataclass` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `date` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1616 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `datetime` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `timedelta` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:539 (direkt/dynamisch unklar) |
| Importbindung | `timezone` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `wraps` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPResponse` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `BaseHTTPRequestHandler` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ThreadingHTTPServer` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `SimpleCookie` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Path` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Any` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Callable` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Iterator` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `NoReturn` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPError` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4702 (direkt/dynamisch unklar); tests/test_server.py:7885 (direkt/dynamisch unklar); tests/test_server.py:7916 (direkt/dynamisch unklar); tests/test_server.py:7967 (direkt/dynamisch unklar); tests/test_server.py:8152 (direkt/dynamisch unklar); tests/test_server.py:8196 (direkt/dynamisch unklar); tests/test_server.py:8211 (direkt/dynamisch unklar); tests/test_server.py:8304 (direkt/dynamisch unklar) |
| Importbindung | `URLError` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7957 (direkt/dynamisch unklar) |
| Importbindung | `parse_qs` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `quote` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlencode` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlparse` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlunparse` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Request` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlopen` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4457 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4709 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4756 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4787 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4820 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4906 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7887 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7906 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7923 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7957 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7974 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8099 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8135 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8162 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8203 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8309 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8351 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8364 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8388 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8413 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `database_row_factory` | 45 | `backend/db` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ABORTED_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COMPETITION_NOT_FOUND_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_LIBRARY_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_PLANNING_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GEMINI_API_KEY_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERNAL_SERVER_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERVALS_API_KEY_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_LIBRARY_ID_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_DATE_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_ID_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `NOT_FOUND_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `OPENAI_API_KEY_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PLANNED_CALENDAR_RECHECK_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STALE_PLANNING_REVISION_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STRUCTURED_AUTHORIZATION_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `UNSUPPORTED_BYDAY_ERROR` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AppError` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:161 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_server.py:1006 (direkt/dynamisch unklar); tests/test_server.py:1296 (direkt/dynamisch unklar); tests/test_server.py:1406 (direkt/dynamisch unklar); tests/test_server.py:1413 (direkt/dynamisch unklar); tests/test_server.py:1530 (direkt/dynamisch unklar); tests/test_server.py:1631 (direkt/dynamisch unklar); tests/test_server.py:1635 (direkt/dynamisch unklar); tests/test_server.py:1661 (direkt/dynamisch unklar); tests/test_server.py:1798 (direkt/dynamisch unklar); tests/test_server.py:2049 (direkt/dynamisch unklar); tests/test_server.py:2055 (direkt/dynamisch unklar); tests/test_server.py:2066 (direkt/dynamisch unklar); tests/test_server.py:2070 (direkt/dynamisch unklar); tests/test_server.py:2071 (direkt/dynamisch unklar); tests/test_server.py:2073 (direkt/dynamisch unklar); tests/test_server.py:2078 (direkt/dynamisch unklar); tests/test_server.py:2081 (direkt/dynamisch unklar); tests/test_server.py:2086 (direkt/dynamisch unklar); tests/test_server.py:2089 (direkt/dynamisch unklar); tests/test_server.py:2094 (direkt/dynamisch unklar); tests/test_server.py:2097 (direkt/dynamisch unklar); tests/test_server.py:2104 (direkt/dynamisch unklar); tests/test_server.py:2129 (direkt/dynamisch unklar); tests/test_server.py:2385 (direkt/dynamisch unklar); tests/test_server.py:2495 (direkt/dynamisch unklar); tests/test_server.py:2520 (direkt/dynamisch unklar); tests/test_server.py:2524 (direkt/dynamisch unklar); tests/test_server.py:2567 (direkt/dynamisch unklar); tests/test_server.py:2580 (direkt/dynamisch unklar); tests/test_server.py:2586 (direkt/dynamisch unklar); tests/test_server.py:2626 (direkt/dynamisch unklar); tests/test_server.py:266 (direkt/dynamisch unklar); tests/test_server.py:2708 (direkt/dynamisch unklar); tests/test_server.py:2709 (direkt/dynamisch unklar); tests/test_server.py:2714 (direkt/dynamisch unklar); tests/test_server.py:2716 (direkt/dynamisch unklar); tests/test_server.py:278 (direkt/dynamisch unklar); tests/test_server.py:3256 (direkt/dynamisch unklar); tests/test_server.py:3293 (direkt/dynamisch unklar); tests/test_server.py:331 (direkt/dynamisch unklar); tests/test_server.py:363 (direkt/dynamisch unklar); tests/test_server.py:3727 (direkt/dynamisch unklar); tests/test_server.py:3827 (direkt/dynamisch unklar); tests/test_server.py:3843 (direkt/dynamisch unklar); tests/test_server.py:3882 (direkt/dynamisch unklar); tests/test_server.py:3909 (direkt/dynamisch unklar); tests/test_server.py:3917 (direkt/dynamisch unklar); tests/test_server.py:3928 (direkt/dynamisch unklar); tests/test_server.py:3949 (direkt/dynamisch unklar); tests/test_server.py:3961 (direkt/dynamisch unklar); tests/test_server.py:3965 (direkt/dynamisch unklar); tests/test_server.py:4153 (direkt/dynamisch unklar); tests/test_server.py:4314 (direkt/dynamisch unklar); tests/test_server.py:4375 (direkt/dynamisch unklar); tests/test_server.py:442 (direkt/dynamisch unklar); tests/test_server.py:4472 (direkt/dynamisch unklar); tests/test_server.py:4485 (direkt/dynamisch unklar); tests/test_server.py:4495 (direkt/dynamisch unklar); tests/test_server.py:4510 (direkt/dynamisch unklar); tests/test_server.py:4524 (direkt/dynamisch unklar); tests/test_server.py:4607 (direkt/dynamisch unklar); tests/test_server.py:4697 (direkt/dynamisch unklar); tests/test_server.py:4699 (direkt/dynamisch unklar); tests/test_server.py:4710 (direkt/dynamisch unklar); tests/test_server.py:4753 (direkt/dynamisch unklar); tests/test_server.py:4821 (direkt/dynamisch unklar); tests/test_server.py:4870 (direkt/dynamisch unklar); tests/test_server.py:4914 (direkt/dynamisch unklar); tests/test_server.py:4916 (direkt/dynamisch unklar); tests/test_server.py:4940 (direkt/dynamisch unklar); tests/test_server.py:5015 (direkt/dynamisch unklar); tests/test_server.py:5086 (direkt/dynamisch unklar); tests/test_server.py:5251 (direkt/dynamisch unklar); tests/test_server.py:5268 (direkt/dynamisch unklar); tests/test_server.py:531 (direkt/dynamisch unklar); tests/test_server.py:5474 (direkt/dynamisch unklar); tests/test_server.py:5481 (direkt/dynamisch unklar); tests/test_server.py:5491 (direkt/dynamisch unklar); tests/test_server.py:5493 (direkt/dynamisch unklar); tests/test_server.py:5642 (direkt/dynamisch unklar); tests/test_server.py:5755 (direkt/dynamisch unklar); tests/test_server.py:5807 (direkt/dynamisch unklar); tests/test_server.py:5820 (direkt/dynamisch unklar); tests/test_server.py:6028 (direkt/dynamisch unklar); tests/test_server.py:6134 (direkt/dynamisch unklar); tests/test_server.py:6138 (direkt/dynamisch unklar); tests/test_server.py:6147 (direkt/dynamisch unklar); tests/test_server.py:6151 (direkt/dynamisch unklar); tests/test_server.py:6169 (direkt/dynamisch unklar); tests/test_server.py:6180 (direkt/dynamisch unklar); tests/test_server.py:6647 (direkt/dynamisch unklar); tests/test_server.py:6660 (direkt/dynamisch unklar); tests/test_server.py:6672 (direkt/dynamisch unklar); tests/test_server.py:7595 (direkt/dynamisch unklar); tests/test_server.py:7602 (direkt/dynamisch unklar); tests/test_server.py:782 (direkt/dynamisch unklar); tests/test_server.py:7860 (direkt/dynamisch unklar); tests/test_server.py:7868 (direkt/dynamisch unklar); tests/test_server.py:7888 (direkt/dynamisch unklar); tests/test_server.py:7924 (direkt/dynamisch unklar); tests/test_server.py:7958 (direkt/dynamisch unklar); tests/test_server.py:7975 (direkt/dynamisch unklar); tests/test_server.py:801 (direkt/dynamisch unklar); tests/test_server.py:8163 (direkt/dynamisch unklar); tests/test_server.py:8204 (direkt/dynamisch unklar); tests/test_server.py:8218 (direkt/dynamisch unklar); tests/test_server.py:8229 (direkt/dynamisch unklar); tests/test_server.py:8310 (direkt/dynamisch unklar); tests/test_server.py:8365 (direkt/dynamisch unklar); tests/test_server.py:8389 (direkt/dynamisch unklar); tests/test_server.py:8419 (direkt/dynamisch unklar); tests/test_server.py:8432 (direkt/dynamisch unklar); tests/test_server.py:8435 (direkt/dynamisch unklar); tests/test_server.py:8527 (direkt/dynamisch unklar); tests/test_server.py:8536 (direkt/dynamisch unklar); tests/test_server.py:8539 (direkt/dynamisch unklar); tests/test_server.py:8542 (direkt/dynamisch unklar); tests/test_server.py:8620 (direkt/dynamisch unklar); tests/test_server.py:8669 (direkt/dynamisch unklar); tests/test_server.py:8690 (direkt/dynamisch unklar); tests/test_server.py:8790 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Importbindung | `ClientDisconnected` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8414 (direkt/dynamisch unklar); tests/test_server.py:8415 (direkt/dynamisch unklar); tests/test_server.py:8463 (direkt/dynamisch unklar) |
| Importbindung | `provider_error` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `public_app_error_status` | 46 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4698 (direkt/dynamisch unklar); tests/test_server.py:4699 (direkt/dynamisch unklar) |
| Importbindung | `app_config` | 68 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_audit_remediation.py:190 (direkt/dynamisch unklar); tests/test_provider_review.py:184 (direkt/dynamisch unklar); tests/test_provider_review.py:317 (direkt/dynamisch unklar); tests/test_server.py:215 (direkt/dynamisch unklar); tests/test_server.py:6703 (direkt/dynamisch unklar); tests/test_server.py:6710 (direkt/dynamisch unklar); tests/test_server.py:6719 (direkt/dynamisch unklar); tests/test_server.py:6735 (direkt/dynamisch unklar) |
| Importbindung | `observability` | 69 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar); tests/test_provider_review.py:32 (direkt/dynamisch unklar); tests/test_server.py:214 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar); tests/test_server.py:8069 (direkt/dynamisch unklar); tests/test_server.py:8098 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8626 (direkt/dynamisch unklar); tests/test_server.py:8631 (direkt/dynamisch unklar); tests/test_server.py:8634 (direkt/dynamisch unklar) |
| Importbindung | `runtime_events` | 70 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `runtime_maintenance` | 71 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `sync_freshness` | 72 | `backend/sync` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8754 (direkt/dynamisch unklar); tests/test_server.py:8759 (direkt/dynamisch unklar) |
| Importbindung | `SettingsService` | 73 | `backend/settings` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `initialize_application_database` | 74 | `backend/db/bootstrap` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ActivityFeedbackRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1157 (direkt/dynamisch unklar) |
| Importbindung | `ChatRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1083 (direkt/dynamisch unklar) |
| Importbindung | `CheckinRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1091 (direkt/dynamisch unklar) |
| Importbindung | `CompetitionRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1123 (direkt/dynamisch unklar) |
| Importbindung | `KeyValueRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1074 (direkt/dynamisch unklar); tests/test_server.py:1108 (direkt/dynamisch unklar) |
| Importbindung | `PlanAdjustmentRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1147 (direkt/dynamisch unklar) |
| Importbindung | `ProfileRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1108 (direkt/dynamisch unklar) |
| Importbindung | `SnapshotRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1170 (direkt/dynamisch unklar) |
| Importbindung | `TrainingPlanRepository` | 75 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1132 (direkt/dynamisch unklar) |
| Importbindung | `DatabaseManager` | 76 | `backend/db/manager` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CURRENT_DATABASE_INDEXES` | 77 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:161 (direkt/dynamisch unklar) |
| Importbindung | `CURRENT_DATABASE_SCHEMA` | 77 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1538 (direkt/dynamisch unklar); tests/test_server.py:160 (direkt/dynamisch unklar) |
| Importbindung | `configure_cipher` | 77 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `database_index_names` | 77 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:161 (direkt/dynamisch unklar) |
| Importbindung | `database_schema_is_current` | 77 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `Config` | 84 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `DEFAULT_OPENAI_BASE_URL` | 84 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4862 (direkt/dynamisch unklar) |
| Importbindung | `load_config` | 84 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsReadTransport` | 85 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsWriteTransport` | 85 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `fetch_paged_collection` | 85 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_function_tools` | 86 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_response_text` | 86 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_failure_reason` | 87 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_text` | 87 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_error_detail` | 88 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_bounded_response` | 88 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `WorkoutTextError` | 89 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `canonical_workout_zones` | 89 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `structured_duration` | 89 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `verify_workout_readback` | 89 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GarminCollectionOptions` | 90 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `collect_garmin_data` | 90 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:241 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `ical_duration` | 91 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_date` | 91 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_value` | 91 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `unfold_ical` | 91 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `split_date_windows` | 92 | `backend/sync/windows` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_cursor` | 93 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `write_cursor` | 93 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_sync_operation_state` | 94 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `project_sync_status` | 94 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `daily_sync_is_due` | 95 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_daily_sync_value` | 95 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `cleanup_refresh_history` | 96 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `create_refresh_record` | 96 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `finish_refresh_record` | 96 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `latest_snapshot_in_transaction` | 97 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `save_snapshot_in_transaction` | 97 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ReconcileDependencies` | 98 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_planned_unit_state` | 98 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_payload` | 99 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_rows` | 99 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_bounds` | 100 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `TRAINING_PLAN_STATUSES` | 101 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_metadata` | 101 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AdaptiveDependencies` | 102 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_adaptive_changes` | 102 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PlanningChangeDependencies` | 103 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes` | 103 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes_in_db` | 103 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `JOB_STATUSES` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ITEM_STATUSES` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `aggregate_job_status` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_progress` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `decode_job_payload` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `has_active_job` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `job_dto` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `list_jobs` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_job` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `is_retryable_error` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `retry_delay` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_job_request` | 106 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTIVITY_FIELDS` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_sections_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_value_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_json_size_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_projection_meta_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_activity_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workout_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workouts_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_planned_event_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `detailed_coach_activity_value` | 120 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_DIALOGUE_INSTRUCTIONS` | 132 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `dialogue_tools` | 132 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_request` | 132 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `build_tool_contracts` | 133 | `backend/coach/tools` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `command_receipt` | 134 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `effects_from_receipts` | 134 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_resolved_receipts` | 134 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `outcome_status` | 134 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `authorized_operations` | 138 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_operation` | 138 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_scope` | 138 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `scope_values` | 138 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTION_LABELS` | 139 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_effect_label` | 139 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_failure_lines` | 139 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_language_recovery.py:163 (direkt/dynamisch unklar) |
| Importbindung | `coach_observed_sync_lines` | 139 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_header_items` | 140 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_json_bytes` | 140 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:7586 (direkt/dynamisch unklar) |
| Importbindung | `response_headers` | 140 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `session_cookies` | 140 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_audio_body` | 146 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_body` | 146 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_json` | 146 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_application_state` | 151 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_decode_payload` | 151 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_workout_library` | 151 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_manifest` | 151 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_jsonl_rows` | 151 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Globale Bindung | `Garmin` | 160 | `sync/` | P6 | offen | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `sqlite_backend` | 165 | `db/` | P1 | offen | tests/test_server.py:1241 (direkt/dynamisch unklar); tests/test_server.py:6640 (direkt/dynamisch unklar); tests/test_server.py:6653 (direkt/dynamisch unklar) |
| Globale Bindung | `SQLCIPHER_AVAILABLE` | 166 | `db/` | P1 | offen | tests/test_audit_remediation.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:315 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:323 (direkt/dynamisch unklar); tests/test_server.py:2884 (direkt/dynamisch unklar); tests/test_server.py:3419 (direkt/dynamisch unklar); tests/test_server.py:6617 (direkt/dynamisch unklar) |
| Globale Bindung | `ROOT` | 172 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:6698 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6718 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PUBLIC_DIR` | 173 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2409 (direkt/dynamisch unklar); tests/test_server.py:2410 (direkt/dynamisch unklar); tests/test_server.py:2426 (direkt/dynamisch unklar); tests/test_server.py:2427 (direkt/dynamisch unklar); tests/test_server.py:7384 (direkt/dynamisch unklar); tests/test_server.py:7385 (direkt/dynamisch unklar); tests/test_server.py:7396 (direkt/dynamisch unklar); tests/test_server.py:7397 (direkt/dynamisch unklar); tests/test_server.py:7405 (direkt/dynamisch unklar); tests/test_server.py:7406 (direkt/dynamisch unklar); tests/test_server.py:7414 (direkt/dynamisch unklar); tests/test_server.py:7415 (direkt/dynamisch unklar); tests/test_server.py:7421 (direkt/dynamisch unklar); tests/test_server.py:7422 (direkt/dynamisch unklar); tests/test_server.py:7431 (direkt/dynamisch unklar); tests/test_server.py:7432 (direkt/dynamisch unklar); tests/test_server.py:7433 (direkt/dynamisch unklar); tests/test_server.py:7434 (direkt/dynamisch unklar); tests/test_server.py:7645 (direkt/dynamisch unklar); tests/test_server.py:7664 (direkt/dynamisch unklar); tests/test_server.py:8765 (direkt/dynamisch unklar); tests/test_server.py:8766 (direkt/dynamisch unklar) |
| Globale Bindung | `DATA_DIR` | 174 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_server.py:104 (direkt/dynamisch unklar); tests/test_server.py:110 (direkt/dynamisch unklar); tests/test_server.py:119 (direkt/dynamisch unklar); tests/test_server.py:175 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2889 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3430 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6623 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6698 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6718 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar); tests/test_server.py:8069 (direkt/dynamisch unklar); tests/test_server.py:8098 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8634 (direkt/dynamisch unklar); tests/test_server.py:95 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 175 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:105 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:111 (direkt/dynamisch unklar); tests/test_server.py:120 (direkt/dynamisch unklar); tests/test_server.py:2889 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3430 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6623 (Monkeypatch/getattr/sys.modules); tests/test_server.py:96 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 176 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:30 (Monkeypatch/getattr/sys.modules); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:112 (direkt/dynamisch unklar); tests/test_server.py:121 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar); tests/test_server.py:8069 (direkt/dynamisch unklar); tests/test_server.py:8098 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8634 (direkt/dynamisch unklar); tests/test_server.py:97 (direkt/dynamisch unklar) |
| Globale Bindung | `ASSET_INDEX_HTML` | 177 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_API_JS` | 178 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_APP_JS` | 179 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_NAVIGATION_JS` | 180 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STATE_JS` | 181 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_VIEWS_JS` | 182 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_FORMS_JS` | 183 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_COMPONENTS_JS` | 184 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STYLES_CSS` | 185 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_SERVICE_WORKER_JS` | 186 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_MANIFEST` | 187 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_LOGO` | 188 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_ICON` | 189 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_TARGETS` | 190 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `VERSIONED_STATIC_ASSETS` | 205 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_REVALIDATE_ASSETS` | 206 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_NAME` | 207 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_GARMIN_NAME` | 208 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_WELLNESS_NAME` | 209 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UTC_OFFSET_SUFFIX` | 210 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ISO_MIDNIGHT_SUFFIX` | 211 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `JSON_MEDIA_TYPE` | 212 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OCTET_STREAM_MIME` | 213 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSES_PATH` | 214 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VO2MAX_UNIT` | 215 | `performance/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_RUN_PREDICTION_SOURCE` | 216 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_STARTED_EVENT` | 217 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_COMPLETED_EVENT` | 218 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLAN_CONSTRAINTS_PREFIX` | 219 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_SCOPE_PREFIX` | 220 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LOCAL_INTERVALS_SCOPE` | 221 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `WORKDAY_TIME_LABEL` | 222 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_WORKOUT_LABEL` | 223 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `FULL_RESYNC_LABEL` | 224 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DAILY_AUTO_UPDATE_LABEL` | 225 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `APP_NAME` | 226 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UUID_PATTERN` | 227 | `http_api/` | P10 | offen | tests/test_server.py:3255 (direkt/dynamisch unklar) |
| Globale Bindung | `PAYLOAD_HASH_PATTERN` | 228 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `DATE_ONLY_PATTERN` | 229 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMPETITION_SQL` | 230 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_ACTION_PROPOSAL_SQL` | 231 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INSERT_LIBRARY_SQL` | 232 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_PLANNED_UNIT_SQL` | 233 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMPETITION_CONFLICT_SQL` | 234 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNED_PAYLOAD_SQL` | 235 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_LIBRARY_PAYLOAD_SQL` | 236 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMMAND_RECEIPT_SQL` | 237 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMMAND_RECEIPT_SQL` | 238 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNING_REVISION_SQL` | 239 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_USER_MESSAGE_SQL` | 240 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_IMMUTABLE_MAX_AGE` | 241 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `APP_VERSION` | 242 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:7378 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 243 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 244 | `http_api/` | P10 | offen | tests/test_server.py:4917 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 245 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 246 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 247 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 248 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 249 | `coach/streams.py` | P8 | offen | tests/test_server.py:1509 (direkt/dynamisch unklar); tests/test_server.py:1519 (direkt/dynamisch unklar); tests/test_server.py:1520 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_EXTERNAL_CALENDAR_BYTES` | 250 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_FETCH_TIMEOUT_SECONDS` | 251 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_CONNECTION_TIMEOUT_SECONDS` | 252 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_EXTERNAL_RESPONSE_BYTES` | 253 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_DEFAULT_MAX_OUTPUT_TOKENS` | 257 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LONG_PLAN_MAX_OUTPUT_TOKENS` | 258 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_FOLLOWUP_MAX_OUTPUT_TOKENS` | 259 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_TIMEOUT_SECONDS` | 260 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MESSAGE_ATTACHMENTS_QUERY` | 261 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_BASE_URL` | 262 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 263 | `providers/` | P2 | offen | tests/test_server.py:5903 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 264 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 265 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 266 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 267 | `coach/` | P7 | offen | tests/test_server.py:4945 (direkt/dynamisch unklar); tests/test_server.py:5271 (direkt/dynamisch unklar); tests/test_server.py:5279 (direkt/dynamisch unklar); tests/test_server.py:5631 (direkt/dynamisch unklar); tests/test_server.py:5761 (direkt/dynamisch unklar); tests/test_server.py:5771 (direkt/dynamisch unklar); tests/test_server.py:5773 (direkt/dynamisch unklar); tests/test_server.py:5776 (direkt/dynamisch unklar); tests/test_server.py:5779 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 268 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 269 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:183 (direkt/dynamisch unklar); tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1054 (direkt/dynamisch unklar); tests/test_server.py:126 (direkt/dynamisch unklar); tests/test_server.py:1328 (direkt/dynamisch unklar); tests/test_server.py:1333 (direkt/dynamisch unklar); tests/test_server.py:1336 (direkt/dynamisch unklar); tests/test_server.py:1354 (direkt/dynamisch unklar); tests/test_server.py:1357 (direkt/dynamisch unklar); tests/test_server.py:1361 (direkt/dynamisch unklar); tests/test_server.py:1438 (direkt/dynamisch unklar); tests/test_server.py:1550 (direkt/dynamisch unklar); tests/test_server.py:157 (direkt/dynamisch unklar); tests/test_server.py:1687 (direkt/dynamisch unklar); tests/test_server.py:2572 (direkt/dynamisch unklar); tests/test_server.py:2633 (direkt/dynamisch unklar); tests/test_server.py:2646 (direkt/dynamisch unklar); tests/test_server.py:2702 (direkt/dynamisch unklar); tests/test_server.py:2725 (direkt/dynamisch unklar); tests/test_server.py:2854 (direkt/dynamisch unklar); tests/test_server.py:2867 (direkt/dynamisch unklar); tests/test_server.py:2872 (direkt/dynamisch unklar); tests/test_server.py:3070 (direkt/dynamisch unklar); tests/test_server.py:3150 (direkt/dynamisch unklar); tests/test_server.py:4673 (direkt/dynamisch unklar); tests/test_server.py:4964 (direkt/dynamisch unklar); tests/test_server.py:5096 (direkt/dynamisch unklar); tests/test_server.py:5119 (direkt/dynamisch unklar); tests/test_server.py:5142 (direkt/dynamisch unklar); tests/test_server.py:5164 (direkt/dynamisch unklar); tests/test_server.py:5178 (direkt/dynamisch unklar); tests/test_server.py:5184 (direkt/dynamisch unklar); tests/test_server.py:5201 (direkt/dynamisch unklar); tests/test_server.py:5209 (direkt/dynamisch unklar); tests/test_server.py:5531 (direkt/dynamisch unklar); tests/test_server.py:5573 (direkt/dynamisch unklar); tests/test_server.py:5661 (direkt/dynamisch unklar); tests/test_server.py:5684 (direkt/dynamisch unklar); tests/test_server.py:5926 (direkt/dynamisch unklar); tests/test_server.py:5938 (direkt/dynamisch unklar); tests/test_server.py:5957 (direkt/dynamisch unklar); tests/test_server.py:6031 (direkt/dynamisch unklar); tests/test_server.py:6053 (direkt/dynamisch unklar); tests/test_server.py:6062 (direkt/dynamisch unklar); tests/test_server.py:6187 (direkt/dynamisch unklar); tests/test_server.py:638 (direkt/dynamisch unklar); tests/test_server.py:6479 (direkt/dynamisch unklar); tests/test_server.py:6542 (direkt/dynamisch unklar); tests/test_server.py:6587 (direkt/dynamisch unklar); tests/test_server.py:6626 (direkt/dynamisch unklar); tests/test_server.py:6635 (direkt/dynamisch unklar); tests/test_server.py:6811 (direkt/dynamisch unklar); tests/test_server.py:682 (direkt/dynamisch unklar); tests/test_server.py:6820 (direkt/dynamisch unklar); tests/test_server.py:6830 (direkt/dynamisch unklar); tests/test_server.py:693 (direkt/dynamisch unklar); tests/test_server.py:6981 (direkt/dynamisch unklar); tests/test_server.py:707 (direkt/dynamisch unklar); tests/test_server.py:7775 (direkt/dynamisch unklar); tests/test_server.py:8602 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8607 (direkt/dynamisch unklar); tests/test_server.py:8743 (direkt/dynamisch unklar); tests/test_server.py:8757 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 270 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7785 (direkt/dynamisch unklar); tests/test_server.py:7797 (direkt/dynamisch unklar); tests/test_server.py:7800 (direkt/dynamisch unklar); tests/test_server.py:7813 (direkt/dynamisch unklar); tests/test_server.py:7814 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 271 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 272 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 273 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 274 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 275 | `performance/` | P3 | offen | tests/test_server.py:646 (direkt/dynamisch unklar); tests/test_server.py:652 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 276 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 277 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:151 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 278 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 279 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8520 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 280 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8520 (direkt/dynamisch unklar); tests/test_server.py:8533 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 281 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 282 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 283 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 284 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 285 | `coach/jobs.py` | P8 | offen | tests/test_server.py:238 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 286 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:255 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 287 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:284 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 288 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 289 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 290 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 291 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 292 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 293 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 294 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 295 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5938 (direkt/dynamisch unklar); tests/test_server.py:5957 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 296 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LOCK` | 297 | `http_api/auth.py` | P10 | offen | tests/test_server.py:8037 (direkt/dynamisch unklar); tests/test_server.py:8043 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 298 | `http_api/auth.py` | P10 | offen | tests/test_server.py:8038 (direkt/dynamisch unklar); tests/test_server.py:8039 (direkt/dynamisch unklar); tests/test_server.py:8044 (direkt/dynamisch unklar); tests/test_server.py:8045 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 299 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 300 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 301 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 302 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Klasse | `ProviderResyncGate` | 305 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 352 | `sync/` | P6 | offen | tests/test_server.py:6665 (direkt/dynamisch unklar); tests/test_server.py:6680 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 353 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 356 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 361 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 369 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `CONFIG` | 377 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:153 (direkt/dynamisch unklar); tests/test_audit_remediation.py:270 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (direkt/dynamisch unklar); tests/test_provider_review.py:196 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:314 (direkt/dynamisch unklar); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:327 (direkt/dynamisch unklar); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:101 (direkt/dynamisch unklar); tests/test_server.py:1017 (direkt/dynamisch unklar); tests/test_server.py:1018 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1026 (direkt/dynamisch unklar); tests/test_server.py:1027 (Monkeypatch/getattr/sys.modules); tests/test_server.py:118 (direkt/dynamisch unklar); tests/test_server.py:1241 (direkt/dynamisch unklar); tests/test_server.py:1312 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:173 (direkt/dynamisch unklar); tests/test_server.py:175 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2577 (direkt/dynamisch unklar); tests/test_server.py:2663 (direkt/dynamisch unklar); tests/test_server.py:2664 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2692 (direkt/dynamisch unklar); tests/test_server.py:2693 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2707 (direkt/dynamisch unklar); tests/test_server.py:2708 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2775 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2775 (direkt/dynamisch unklar); tests/test_server.py:2870 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2870 (direkt/dynamisch unklar); tests/test_server.py:2879 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2879 (direkt/dynamisch unklar); tests/test_server.py:2888 (direkt/dynamisch unklar); tests/test_server.py:2889 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3429 (direkt/dynamisch unklar); tests/test_server.py:3430 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3671 (direkt/dynamisch unklar); tests/test_server.py:3744 (direkt/dynamisch unklar); tests/test_server.py:3764 (direkt/dynamisch unklar); tests/test_server.py:3775 (direkt/dynamisch unklar); tests/test_server.py:3794 (direkt/dynamisch unklar); tests/test_server.py:3970 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3970 (direkt/dynamisch unklar); tests/test_server.py:3988 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3988 (direkt/dynamisch unklar); tests/test_server.py:3998 (direkt/dynamisch unklar); tests/test_server.py:4243 (direkt/dynamisch unklar); tests/test_server.py:4244 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4311 (direkt/dynamisch unklar); tests/test_server.py:4319 (direkt/dynamisch unklar); tests/test_server.py:4411 (direkt/dynamisch unklar); tests/test_server.py:4413 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4456 (direkt/dynamisch unklar); tests/test_server.py:4457 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4481 (direkt/dynamisch unklar); tests/test_server.py:4482 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4605 (direkt/dynamisch unklar); tests/test_server.py:4606 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4620 (direkt/dynamisch unklar); tests/test_server.py:4621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4631 (direkt/dynamisch unklar); tests/test_server.py:4632 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4646 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4646 (direkt/dynamisch unklar); tests/test_server.py:4650 (direkt/dynamisch unklar); tests/test_server.py:4652 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4660 (direkt/dynamisch unklar); tests/test_server.py:4665 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4684 (direkt/dynamisch unklar); tests/test_server.py:4685 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4839 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4839 (direkt/dynamisch unklar); tests/test_server.py:4857 (direkt/dynamisch unklar); tests/test_server.py:4858 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4861 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4861 (direkt/dynamisch unklar); tests/test_server.py:4869 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4869 (direkt/dynamisch unklar); tests/test_server.py:4881 (direkt/dynamisch unklar); tests/test_server.py:4882 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4905 (direkt/dynamisch unklar); tests/test_server.py:4906 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4912 (direkt/dynamisch unklar); tests/test_server.py:4913 (Monkeypatch/getattr/sys.modules); tests/test_server.py:57 (direkt/dynamisch unklar); tests/test_server.py:58 (direkt/dynamisch unklar); tests/test_server.py:6104 (direkt/dynamisch unklar); tests/test_server.py:6106 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6118 (direkt/dynamisch unklar); tests/test_server.py:6119 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6133 (direkt/dynamisch unklar); tests/test_server.py:6135 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6145 (direkt/dynamisch unklar); tests/test_server.py:6148 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6158 (direkt/dynamisch unklar); tests/test_server.py:6166 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6178 (direkt/dynamisch unklar); tests/test_server.py:6179 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6206 (direkt/dynamisch unklar); tests/test_server.py:6207 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6246 (direkt/dynamisch unklar); tests/test_server.py:6247 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6268 (direkt/dynamisch unklar); tests/test_server.py:6269 (Monkeypatch/getattr/sys.modules); tests/test_server.py:628 (direkt/dynamisch unklar); tests/test_server.py:629 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6290 (direkt/dynamisch unklar); tests/test_server.py:6291 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6309 (direkt/dynamisch unklar); tests/test_server.py:6310 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6329 (direkt/dynamisch unklar); tests/test_server.py:6383 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6383 (direkt/dynamisch unklar); tests/test_server.py:6392 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6392 (direkt/dynamisch unklar); tests/test_server.py:6411 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6411 (direkt/dynamisch unklar); tests/test_server.py:6420 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6420 (direkt/dynamisch unklar); tests/test_server.py:6429 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6429 (direkt/dynamisch unklar); tests/test_server.py:6437 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6437 (direkt/dynamisch unklar); tests/test_server.py:645 (direkt/dynamisch unklar); tests/test_server.py:6454 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6454 (direkt/dynamisch unklar); tests/test_server.py:648 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6498 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6498 (direkt/dynamisch unklar); tests/test_server.py:6530 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6530 (direkt/dynamisch unklar); tests/test_server.py:656 (direkt/dynamisch unklar); tests/test_server.py:657 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6576 (direkt/dynamisch unklar); tests/test_server.py:6601 (direkt/dynamisch unklar); tests/test_server.py:6609 (direkt/dynamisch unklar); tests/test_server.py:6610 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6621 (direkt/dynamisch unklar); tests/test_server.py:6623 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6668 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6668 (direkt/dynamisch unklar); tests/test_server.py:6688 (direkt/dynamisch unklar); tests/test_server.py:6689 (Monkeypatch/getattr/sys.modules); tests/test_server.py:669 (direkt/dynamisch unklar); tests/test_server.py:670 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6866 (direkt/dynamisch unklar); tests/test_server.py:6898 (direkt/dynamisch unklar); tests/test_server.py:6936 (direkt/dynamisch unklar); tests/test_server.py:6968 (direkt/dynamisch unklar); tests/test_server.py:6984 (direkt/dynamisch unklar); tests/test_server.py:7023 (direkt/dynamisch unklar); tests/test_server.py:7056 (direkt/dynamisch unklar); tests/test_server.py:7083 (direkt/dynamisch unklar); tests/test_server.py:7366 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7366 (direkt/dynamisch unklar); tests/test_server.py:7833 (direkt/dynamisch unklar); tests/test_server.py:7837 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7858 (direkt/dynamisch unklar); tests/test_server.py:7859 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7883 (direkt/dynamisch unklar); tests/test_server.py:7887 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7987 (direkt/dynamisch unklar); tests/test_server.py:7988 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7997 (direkt/dynamisch unklar); tests/test_server.py:7998 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8068 (direkt/dynamisch unklar); tests/test_server.py:8070 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8308 (direkt/dynamisch unklar); tests/test_server.py:8309 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8548 (direkt/dynamisch unklar); tests/test_server.py:8549 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8618 (direkt/dynamisch unklar); tests/test_server.py:8619 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8713 (direkt/dynamisch unklar); tests/test_server.py:8720 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8731 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8787 (direkt/dynamisch unklar); tests/test_server.py:8788 (Monkeypatch/getattr/sys.modules); tests/test_server.py:94 (direkt/dynamisch unklar) |
| Klasse | `IntervalsClient` | 380 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:43 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:54 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:70 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:81 (direkt/dynamisch unklar); tests/test_server.py:3671 (direkt/dynamisch unklar); tests/test_server.py:3744 (direkt/dynamisch unklar); tests/test_server.py:3764 (direkt/dynamisch unklar); tests/test_server.py:3775 (direkt/dynamisch unklar); tests/test_server.py:3794 (direkt/dynamisch unklar); tests/test_server.py:3866 (direkt/dynamisch unklar); tests/test_server.py:3894 (direkt/dynamisch unklar); tests/test_server.py:3925 (direkt/dynamisch unklar); tests/test_server.py:3926 (direkt/dynamisch unklar); tests/test_server.py:3927 (direkt/dynamisch unklar); tests/test_server.py:3945 (direkt/dynamisch unklar); tests/test_server.py:3989 (direkt/dynamisch unklar); tests/test_server.py:3990 (direkt/dynamisch unklar); tests/test_server.py:3998 (direkt/dynamisch unklar); tests/test_server.py:4311 (direkt/dynamisch unklar); tests/test_server.py:4319 (direkt/dynamisch unklar); tests/test_server.py:6107 (direkt/dynamisch unklar); tests/test_server.py:6120 (direkt/dynamisch unklar); tests/test_server.py:6136 (direkt/dynamisch unklar); tests/test_server.py:6149 (direkt/dynamisch unklar); tests/test_server.py:6167 (direkt/dynamisch unklar); tests/test_server.py:6208 (direkt/dynamisch unklar); tests/test_server.py:6209 (direkt/dynamisch unklar); tests/test_server.py:6248 (direkt/dynamisch unklar); tests/test_server.py:6270 (direkt/dynamisch unklar); tests/test_server.py:6292 (direkt/dynamisch unklar); tests/test_server.py:6293 (direkt/dynamisch unklar); tests/test_server.py:6311 (direkt/dynamisch unklar); tests/test_server.py:6512 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6575 (Monkeypatch/getattr/sys.modules); tests/test_server.py:658 (direkt/dynamisch unklar); tests/test_server.py:6600 (Monkeypatch/getattr/sys.modules); tests/test_server.py:671 (direkt/dynamisch unklar); tests/test_server.py:6865 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6897 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6935 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6967 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6983 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7022 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7055 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7082 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7365 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7755 (direkt/dynamisch unklar); tests/test_server.py:8071 (direkt/dynamisch unklar); tests/test_server.py:8072 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 683 | `observability.py` | P1 | offen | tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:23 (direkt/dynamisch unklar); tests/test_provider_review.py:31 (direkt/dynamisch unklar); tests/test_provider_review.py:40 (direkt/dynamisch unklar); tests/test_provider_review.py:42 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_server.py:7578 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7822 (direkt/dynamisch unklar); tests/test_server.py:7823 (direkt/dynamisch unklar); tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7908 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar); tests/test_server.py:7960 (direkt/dynamisch unklar); tests/test_server.py:8069 (direkt/dynamisch unklar); tests/test_server.py:8074 (direkt/dynamisch unklar); tests/test_server.py:8098 (direkt/dynamisch unklar); tests/test_server.py:8105 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8634 (direkt/dynamisch unklar); tests/test_server.py:8641 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTOR` | 684 | `observability.py` | P1 | offen | tests/test_server.py:4647 (direkt/dynamisch unklar); tests/test_server.py:7821 (direkt/dynamisch unklar); tests/test_server.py:7848 (direkt/dynamisch unklar); tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar); tests/test_server.py:8069 (direkt/dynamisch unklar); tests/test_server.py:8098 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8634 (direkt/dynamisch unklar) |
| Funktion | `external_call` | 687 | `providers/http.py` | P2 | offen | tests/test_server.py:1780 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7861 (direkt/dynamisch unklar); tests/test_server.py:7937 (direkt/dynamisch unklar); tests/test_server.py:7952 (direkt/dynamisch unklar); tests/test_server.py:8635 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 750 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 769 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 770 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 771 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 772 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 773 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 774 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 775 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 776 | `weather/` | P3 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_server.py:1229 (direkt/dynamisch unklar); tests/test_server.py:1231 (direkt/dynamisch unklar); tests/test_server.py:1255 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:1435 (direkt/dynamisch unklar); tests/test_server.py:1573 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 777 | `weather/` | P3 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 778 | `history/` | P5 | offen | tests/test_server.py:4253 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 779 | `weather/` | P3 | offen | tests/test_server.py:1249 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1256 (direkt/dynamisch unklar); tests/test_server.py:1259 (direkt/dynamisch unklar); tests/test_server.py:1304 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 780 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 781 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 782 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 783 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 784 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 814 | `weather/` | P3 | offen | tests/test_server.py:7511 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 846 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `serialise_conversation` | 879 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8523 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 896 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:170 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:80 (direkt/dynamisch unklar); tests/test_audit_remediation.py:94 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1053 (direkt/dynamisch unklar); tests/test_server.py:1204 (direkt/dynamisch unklar); tests/test_server.py:1207 (direkt/dynamisch unklar); tests/test_server.py:1275 (direkt/dynamisch unklar); tests/test_server.py:1294 (direkt/dynamisch unklar); tests/test_server.py:1441 (direkt/dynamisch unklar); tests/test_server.py:1445 (direkt/dynamisch unklar); tests/test_server.py:1561 (direkt/dynamisch unklar); tests/test_server.py:1690 (direkt/dynamisch unklar); tests/test_server.py:2575 (direkt/dynamisch unklar); tests/test_server.py:2636 (direkt/dynamisch unklar); tests/test_server.py:2649 (direkt/dynamisch unklar); tests/test_server.py:2705 (direkt/dynamisch unklar); tests/test_server.py:2728 (direkt/dynamisch unklar); tests/test_server.py:2857 (direkt/dynamisch unklar); tests/test_server.py:3153 (direkt/dynamisch unklar); tests/test_server.py:3157 (direkt/dynamisch unklar); tests/test_server.py:5098 (direkt/dynamisch unklar); tests/test_server.py:5121 (direkt/dynamisch unklar); tests/test_server.py:5144 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5187 (direkt/dynamisch unklar); tests/test_server.py:5211 (direkt/dynamisch unklar); tests/test_server.py:5662 (direkt/dynamisch unklar); tests/test_server.py:5686 (direkt/dynamisch unklar); tests/test_server.py:5941 (direkt/dynamisch unklar); tests/test_server.py:5960 (direkt/dynamisch unklar); tests/test_server.py:7776 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 900 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 901 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 902 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 903 | `planning/` | P4 | offen | tests/test_server.py:5097 (direkt/dynamisch unklar); tests/test_server.py:5120 (direkt/dynamisch unklar); tests/test_server.py:5143 (direkt/dynamisch unklar); tests/test_server.py:5165 (direkt/dynamisch unklar); tests/test_server.py:5179 (direkt/dynamisch unklar); tests/test_server.py:5186 (direkt/dynamisch unklar); tests/test_server.py:5202 (direkt/dynamisch unklar); tests/test_server.py:5210 (direkt/dynamisch unklar); tests/test_server.py:5662 (direkt/dynamisch unklar); tests/test_server.py:5685 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 904 | `planning/` | P4 | offen | tests/test_server.py:7776 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 905 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4595 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 906 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 907 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 908 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CONTEXT` | 911 | `observability.py` | P1 | offen | tests/test_server.py:8055 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 912 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:335 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:182 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 913 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:336 (direkt/dynamisch unklar); tests/test_provider_review.py:49 (direkt/dynamisch unklar); tests/test_server.py:183 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 915 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 916 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 917 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 918 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 919 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 920 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 921 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 922 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 923 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 924 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 925 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 928 | `history/` | P5 | offen | tests/test_server.py:5631 (direkt/dynamisch unklar); tests/test_server.py:5642 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 929 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 930 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 931 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 932 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 937 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 942 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 947 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 951 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 953 | `planning/` | P4 | offen | tests/test_server.py:406 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 954 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 955 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 958 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 969 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 975 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 984 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 994 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1021 | `observability.py` | P1 | offen | tests/test_server.py:8052 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1042 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1085 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:281 (direkt/dynamisch unklar); tests/test_provider_review.py:187 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:197 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_provider_review.py:334 (direkt/dynamisch unklar); tests/test_server.py:180 (direkt/dynamisch unklar) |
| Funktion | `database` | 1112 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:183 (direkt/dynamisch unklar); tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1054 (direkt/dynamisch unklar); tests/test_server.py:1075 (direkt/dynamisch unklar); tests/test_server.py:1084 (direkt/dynamisch unklar); tests/test_server.py:1098 (direkt/dynamisch unklar); tests/test_server.py:1110 (direkt/dynamisch unklar); tests/test_server.py:1124 (direkt/dynamisch unklar); tests/test_server.py:1133 (direkt/dynamisch unklar); tests/test_server.py:1142 (direkt/dynamisch unklar); tests/test_server.py:1149 (direkt/dynamisch unklar); tests/test_server.py:1160 (direkt/dynamisch unklar); tests/test_server.py:1171 (direkt/dynamisch unklar); tests/test_server.py:126 (direkt/dynamisch unklar); tests/test_server.py:1328 (direkt/dynamisch unklar); tests/test_server.py:1333 (direkt/dynamisch unklar); tests/test_server.py:1336 (direkt/dynamisch unklar); tests/test_server.py:1354 (direkt/dynamisch unklar); tests/test_server.py:1357 (direkt/dynamisch unklar); tests/test_server.py:1361 (direkt/dynamisch unklar); tests/test_server.py:1438 (direkt/dynamisch unklar); tests/test_server.py:1550 (direkt/dynamisch unklar); tests/test_server.py:157 (direkt/dynamisch unklar); tests/test_server.py:1687 (direkt/dynamisch unklar); tests/test_server.py:2572 (direkt/dynamisch unklar); tests/test_server.py:2633 (direkt/dynamisch unklar); tests/test_server.py:2646 (direkt/dynamisch unklar); tests/test_server.py:2702 (direkt/dynamisch unklar); tests/test_server.py:2725 (direkt/dynamisch unklar); tests/test_server.py:2854 (direkt/dynamisch unklar); tests/test_server.py:2867 (direkt/dynamisch unklar); tests/test_server.py:2872 (direkt/dynamisch unklar); tests/test_server.py:2891 (direkt/dynamisch unklar); tests/test_server.py:3070 (direkt/dynamisch unklar); tests/test_server.py:3150 (direkt/dynamisch unklar); tests/test_server.py:3438 (direkt/dynamisch unklar); tests/test_server.py:4594 (direkt/dynamisch unklar); tests/test_server.py:4673 (direkt/dynamisch unklar); tests/test_server.py:4964 (direkt/dynamisch unklar); tests/test_server.py:5096 (direkt/dynamisch unklar); tests/test_server.py:5119 (direkt/dynamisch unklar); tests/test_server.py:5142 (direkt/dynamisch unklar); tests/test_server.py:5164 (direkt/dynamisch unklar); tests/test_server.py:5178 (direkt/dynamisch unklar); tests/test_server.py:5184 (direkt/dynamisch unklar); tests/test_server.py:5201 (direkt/dynamisch unklar); tests/test_server.py:5209 (direkt/dynamisch unklar); tests/test_server.py:5531 (direkt/dynamisch unklar); tests/test_server.py:5573 (direkt/dynamisch unklar); tests/test_server.py:5661 (direkt/dynamisch unklar); tests/test_server.py:5684 (direkt/dynamisch unklar); tests/test_server.py:5926 (direkt/dynamisch unklar); tests/test_server.py:5938 (direkt/dynamisch unklar); tests/test_server.py:5957 (direkt/dynamisch unklar); tests/test_server.py:6031 (direkt/dynamisch unklar); tests/test_server.py:6053 (direkt/dynamisch unklar); tests/test_server.py:6062 (direkt/dynamisch unklar); tests/test_server.py:6187 (direkt/dynamisch unklar); tests/test_server.py:638 (direkt/dynamisch unklar); tests/test_server.py:6479 (direkt/dynamisch unklar); tests/test_server.py:6542 (direkt/dynamisch unklar); tests/test_server.py:6587 (direkt/dynamisch unklar); tests/test_server.py:6626 (direkt/dynamisch unklar); tests/test_server.py:6635 (direkt/dynamisch unklar); tests/test_server.py:6811 (direkt/dynamisch unklar); tests/test_server.py:682 (direkt/dynamisch unklar); tests/test_server.py:6820 (direkt/dynamisch unklar); tests/test_server.py:6830 (direkt/dynamisch unklar); tests/test_server.py:693 (direkt/dynamisch unklar); tests/test_server.py:6981 (direkt/dynamisch unklar); tests/test_server.py:707 (direkt/dynamisch unklar); tests/test_server.py:7775 (direkt/dynamisch unklar); tests/test_server.py:8014 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8473 (direkt/dynamisch unklar); tests/test_server.py:8607 (direkt/dynamisch unklar); tests/test_server.py:8743 (direkt/dynamisch unklar); tests/test_server.py:8757 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1118 | `db/bootstrap.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:37 (direkt/dynamisch unklar); tests/test_server.py:107 (direkt/dynamisch unklar); tests/test_server.py:113 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:156 (direkt/dynamisch unklar); tests/test_server.py:179 (direkt/dynamisch unklar); tests/test_server.py:199 (direkt/dynamisch unklar); tests/test_server.py:207 (direkt/dynamisch unklar); tests/test_server.py:216 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2871 (direkt/dynamisch unklar); tests/test_server.py:2880 (direkt/dynamisch unklar); tests/test_server.py:2890 (direkt/dynamisch unklar); tests/test_server.py:3431 (direkt/dynamisch unklar); tests/test_server.py:6624 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1130 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1138 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8725 (direkt/dynamisch unklar); tests/test_server.py:8741 (direkt/dynamisch unklar); tests/test_server.py:8755 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1150 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8726 (direkt/dynamisch unklar); tests/test_server.py:8742 (direkt/dynamisch unklar); tests/test_server.py:8756 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1184 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1199 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1213 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1222 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1236 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1249 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1259 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1268 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1278 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1285 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1310 | `sync/` | P6 | offen | tests/test_audit_remediation.py:278 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:251 (direkt/dynamisch unklar); tests/test_server.py:253 (direkt/dynamisch unklar); tests/test_server.py:257 (direkt/dynamisch unklar); tests/test_server.py:268 (direkt/dynamisch unklar); tests/test_server.py:301 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1319 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:142 (direkt/dynamisch unklar); tests/test_provider_review.py:179 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1325 | `sync/` | P6 | offen | tests/test_server.py:1018 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1027 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1330 | `sync/` | P6 | offen | tests/test_server.py:649 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1353 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1361 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1370 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1388 | `sync/` | P6 | offen | tests/test_server.py:661 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1415 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1424 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1431 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1441 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 1466 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 1480 | `sync/` | P6 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:1029 (Monkeypatch/getattr/sys.modules); tests/test_server.py:246 (direkt/dynamisch unklar); tests/test_server.py:263 (direkt/dynamisch unklar); tests/test_server.py:290 (direkt/dynamisch unklar); tests/test_server.py:387 (Monkeypatch/getattr/sys.modules); tests/test_server.py:474 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4937 (direkt/dynamisch unklar); tests/test_server.py:4941 (direkt/dynamisch unklar); tests/test_server.py:570 (Monkeypatch/getattr/sys.modules); tests/test_server.py:630 (direkt/dynamisch unklar); tests/test_server.py:633 (direkt/dynamisch unklar); tests/test_server.py:6386 (direkt/dynamisch unklar); tests/test_server.py:6395 (direkt/dynamisch unklar); tests/test_server.py:6414 (direkt/dynamisch unklar); tests/test_server.py:6423 (direkt/dynamisch unklar); tests/test_server.py:648 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8735 (direkt/dynamisch unklar); tests/test_server.py:910 (Monkeypatch/getattr/sys.modules); tests/test_server.py:936 (Monkeypatch/getattr/sys.modules); tests/test_server.py:981 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 1507 | `sync/` | P6 | offen | tests/test_server.py:204 (Monkeypatch/getattr/sys.modules); tests/test_server.py:234 (Monkeypatch/getattr/sys.modules); tests/test_server.py:252 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 1527 | `sync/` | P6 | offen | tests/test_audit_remediation.py:274 (direkt/dynamisch unklar); tests/test_audit_remediation.py:279 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:154 (direkt/dynamisch unklar); tests/test_server.py:249 (direkt/dynamisch unklar); tests/test_server.py:254 (direkt/dynamisch unklar); tests/test_server.py:264 (direkt/dynamisch unklar); tests/test_server.py:297 (direkt/dynamisch unklar); tests/test_server.py:6387 (direkt/dynamisch unklar); tests/test_server.py:6396 (direkt/dynamisch unklar); tests/test_server.py:6415 (direkt/dynamisch unklar); tests/test_server.py:6424 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 1548 | `sync/` | P6 | offen | tests/test_audit_remediation.py:241 (direkt/dynamisch unklar); tests/test_audit_remediation.py:276 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 1586 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 1592 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 1603 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 1623 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 1638 | `sync/jobs.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 1655 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 1668 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 1677 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 1684 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 1701 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 1713 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 1725 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:138 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:167 (Monkeypatch/getattr/sys.modules); tests/test_server.py:255 (Monkeypatch/getattr/sys.modules); tests/test_server.py:266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:279 (direkt/dynamisch unklar); tests/test_server.py:299 (Monkeypatch/getattr/sys.modules); tests/test_server.py:596 (direkt/dynamisch unklar); tests/test_server.py:597 (direkt/dynamisch unklar); tests/test_server.py:609 (direkt/dynamisch unklar); tests/test_server.py:622 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 1748 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 1757 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 1777 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 1797 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 1815 | `sync/` | P6 | offen | tests/test_provider_review.py:139 (direkt/dynamisch unklar); tests/test_provider_review.py:168 (direkt/dynamisch unklar); tests/test_server.py:256 (direkt/dynamisch unklar); tests/test_server.py:267 (direkt/dynamisch unklar); tests/test_server.py:300 (direkt/dynamisch unklar); tests/test_server.py:6387 (direkt/dynamisch unklar); tests/test_server.py:6396 (direkt/dynamisch unklar); tests/test_server.py:6415 (direkt/dynamisch unklar); tests/test_server.py:6424 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 1825 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 1840 | `sync/` | P6 | offen | tests/test_server.py:239 (direkt/dynamisch unklar) |
| Funktion | `resolve_sync_job` | 1851 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_current_provider_freshness` | 1874 | `sync/freshness.py` | P6 | offen | tests/test_server.py:6184 (direkt/dynamisch unklar); tests/test_server.py:8722 (direkt/dynamisch unklar); tests/test_server.py:8727 (direkt/dynamisch unklar); tests/test_server.py:8732 (direkt/dynamisch unklar); tests/test_server.py:8739 (direkt/dynamisch unklar); tests/test_server.py:8749 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 1888 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 1902 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 1913 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 1937 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 1942 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 1954 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 1964 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 1981 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2020 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2052 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3198 (direkt/dynamisch unklar); tests/test_server.py:5614 (direkt/dynamisch unklar); tests/test_server.py:5703 (direkt/dynamisch unklar); tests/test_server.py:5752 (direkt/dynamisch unklar); tests/test_server.py:8676 (direkt/dynamisch unklar); tests/test_server.py:8696 (direkt/dynamisch unklar); tests/test_server.py:8705 (direkt/dynamisch unklar); tests/test_server.py:8708 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2063 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2075 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2089 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2105 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8685 (direkt/dynamisch unklar); tests/test_server.py:8691 (direkt/dynamisch unklar); tests/test_server.py:8697 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2143 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2163 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2173 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2198 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2219 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2229 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2238 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2264 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2280 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2300 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2309 | `history/` | P5 | offen | tests/test_server.py:3205 (direkt/dynamisch unklar); tests/test_server.py:5621 (direkt/dynamisch unklar); tests/test_server.py:5756 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2324 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:237 (direkt/dynamisch unklar); tests/test_audit_remediation.py:287 (direkt/dynamisch unklar); tests/test_audit_remediation.py:288 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar); tests/test_provider_review.py:337 (direkt/dynamisch unklar); tests/test_server.py:1231 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:1259 (direkt/dynamisch unklar); tests/test_server.py:1304 (direkt/dynamisch unklar); tests/test_server.py:200 (direkt/dynamisch unklar); tests/test_server.py:201 (direkt/dynamisch unklar); tests/test_server.py:2881 (direkt/dynamisch unklar); tests/test_server.py:2882 (direkt/dynamisch unklar); tests/test_server.py:4204 (direkt/dynamisch unklar); tests/test_server.py:4205 (direkt/dynamisch unklar); tests/test_server.py:4488 (direkt/dynamisch unklar); tests/test_server.py:4611 (direkt/dynamisch unklar); tests/test_server.py:6141 (direkt/dynamisch unklar); tests/test_server.py:6153 (direkt/dynamisch unklar); tests/test_server.py:6154 (direkt/dynamisch unklar); tests/test_server.py:6257 (direkt/dynamisch unklar); tests/test_server.py:6276 (direkt/dynamisch unklar); tests/test_server.py:6280 (direkt/dynamisch unklar); tests/test_server.py:6615 (direkt/dynamisch unklar); tests/test_server.py:6634 (direkt/dynamisch unklar); tests/test_server.py:6692 (direkt/dynamisch unklar); tests/test_server.py:7787 (direkt/dynamisch unklar); tests/test_server.py:7805 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 2331 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 2332 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 2333 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 2334 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_CALENDAR_WINDOW_DAYS` | 2335 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2684 (direkt/dynamisch unklar) |
| Globale Bindung | `ICAL_MAX_RECURRENCE_COUNT` | 2336 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_MAX_RECURRENCE_PERIODS` | 2337 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 2338 | `planning/` | P4 | offen | tests/test_server.py:2747 (direkt/dynamisch unklar); tests/test_server.py:2757 (direkt/dynamisch unklar); tests/test_server.py:2782 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 2339 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 2340 | `planning/` | P4 | offen | tests/test_server.py:2359 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 2341 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 2344 | `planning/` | P4 | offen | tests/test_server.py:3689 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 2345 | `planning/` | P4 | offen | tests/test_server.py:3690 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 2346 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 2347 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 2348 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 2349 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 2350 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 2351 | `coach/` | P7 | offen | tests/test_server.py:5392 (direkt/dynamisch unklar); tests/test_server.py:5403 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 2352 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 2365 | `sync/` | P6 | offen | tests/test_server.py:6078 (direkt/dynamisch unklar); tests/test_server.py:6080 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 2376 | `sync/` | P6 | offen | tests/test_server.py:6077 (direkt/dynamisch unklar); tests/test_server.py:6079 (direkt/dynamisch unklar); tests/test_server.py:6105 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 2388 | `sync/` | P6 | offen | tests/test_server.py:6081 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 2399 | `settings.py` | P1 | offen | tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:223 (direkt/dynamisch unklar); tests/test_provider_review.py:247 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 2404 | `settings.py` | P1 | offen | tests/test_provider_review.py:210 (direkt/dynamisch unklar); tests/test_provider_review.py:211 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 2410 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_server.py:1229 (direkt/dynamisch unklar); tests/test_server.py:1249 (direkt/dynamisch unklar); tests/test_server.py:1255 (direkt/dynamisch unklar); tests/test_server.py:1256 (direkt/dynamisch unklar); tests/test_server.py:1434 (direkt/dynamisch unklar); tests/test_server.py:1435 (direkt/dynamisch unklar); tests/test_server.py:1436 (direkt/dynamisch unklar); tests/test_server.py:1437 (direkt/dynamisch unklar); tests/test_server.py:1529 (direkt/dynamisch unklar); tests/test_server.py:1541 (direkt/dynamisch unklar); tests/test_server.py:1573 (direkt/dynamisch unklar); tests/test_server.py:1681 (direkt/dynamisch unklar); tests/test_server.py:1896 (direkt/dynamisch unklar); tests/test_server.py:1897 (direkt/dynamisch unklar); tests/test_server.py:1898 (direkt/dynamisch unklar); tests/test_server.py:1899 (direkt/dynamisch unklar); tests/test_server.py:1900 (direkt/dynamisch unklar); tests/test_server.py:197 (direkt/dynamisch unklar); tests/test_server.py:198 (direkt/dynamisch unklar); tests/test_server.py:2877 (direkt/dynamisch unklar); tests/test_server.py:2878 (direkt/dynamisch unklar); tests/test_server.py:3302 (direkt/dynamisch unklar); tests/test_server.py:3326 (direkt/dynamisch unklar); tests/test_server.py:3337 (direkt/dynamisch unklar); tests/test_server.py:3385 (direkt/dynamisch unklar); tests/test_server.py:3492 (direkt/dynamisch unklar); tests/test_server.py:3524 (direkt/dynamisch unklar); tests/test_server.py:3543 (direkt/dynamisch unklar); tests/test_server.py:3584 (direkt/dynamisch unklar); tests/test_server.py:3604 (direkt/dynamisch unklar); tests/test_server.py:4254 (direkt/dynamisch unklar); tests/test_server.py:4260 (direkt/dynamisch unklar); tests/test_server.py:4544 (direkt/dynamisch unklar); tests/test_server.py:4568 (direkt/dynamisch unklar); tests/test_server.py:4581 (direkt/dynamisch unklar); tests/test_server.py:4661 (direkt/dynamisch unklar); tests/test_server.py:4683 (direkt/dynamisch unklar); tests/test_server.py:5459 (direkt/dynamisch unklar); tests/test_server.py:5495 (direkt/dynamisch unklar); tests/test_server.py:5990 (direkt/dynamisch unklar); tests/test_server.py:6146 (direkt/dynamisch unklar); tests/test_server.py:6608 (direkt/dynamisch unklar); tests/test_server.py:6625 (direkt/dynamisch unklar); tests/test_server.py:6683 (direkt/dynamisch unklar); tests/test_server.py:6684 (direkt/dynamisch unklar); tests/test_server.py:7766 (direkt/dynamisch unklar); tests/test_server.py:7767 (direkt/dynamisch unklar); tests/test_server.py:7784 (direkt/dynamisch unklar); tests/test_server.py:7799 (direkt/dynamisch unklar); tests/test_server.py:7873 (direkt/dynamisch unklar); tests/test_server.py:7989 (direkt/dynamisch unklar); tests/test_server.py:7999 (direkt/dynamisch unklar); tests/test_server.py:8547 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS` | 2418 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:382 (direkt/dynamisch unklar); tests/test_server.py:4633 (direkt/dynamisch unklar); tests/test_server.py:4634 (direkt/dynamisch unklar); tests/test_server.py:4635 (direkt/dynamisch unklar); tests/test_server.py:4639 (direkt/dynamisch unklar); tests/test_server.py:4640 (direkt/dynamisch unklar); tests/test_server.py:4641 (direkt/dynamisch unklar); tests/test_server.py:4642 (direkt/dynamisch unklar); tests/test_server.py:5471 (direkt/dynamisch unklar); tests/test_server.py:5472 (direkt/dynamisch unklar); tests/test_server.py:5473 (direkt/dynamisch unklar); tests/test_server.py:5475 (direkt/dynamisch unklar); tests/test_server.py:5478 (direkt/dynamisch unklar); tests/test_server.py:5479 (direkt/dynamisch unklar); tests/test_server.py:5480 (direkt/dynamisch unklar); tests/test_server.py:5482 (direkt/dynamisch unklar); tests/test_server.py:5485 (direkt/dynamisch unklar); tests/test_server.py:5487 (direkt/dynamisch unklar); tests/test_server.py:5490 (direkt/dynamisch unklar); tests/test_server.py:5492 (direkt/dynamisch unklar); tests/test_server.py:5494 (direkt/dynamisch unklar); tests/test_server.py:5496 (direkt/dynamisch unklar); tests/test_server.py:5499 (direkt/dynamisch unklar) |
| Globale Bindung | `DIAGNOSTIC_CAPTURE` | 2419 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7929 (direkt/dynamisch unklar); tests/test_server.py:7930 (direkt/dynamisch unklar); tests/test_server.py:7944 (direkt/dynamisch unklar); tests/test_server.py:7950 (direkt/dynamisch unklar); tests/test_server.py:7951 (direkt/dynamisch unklar); tests/test_server.py:8307 (direkt/dynamisch unklar); tests/test_server.py:8313 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 2422 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 2437 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 2454 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:217 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar); tests/test_server.py:5464 (direkt/dynamisch unklar); tests/test_server.py:5466 (direkt/dynamisch unklar); tests/test_server.py:6693 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 2462 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 2466 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4197 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 2474 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 2486 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 2501 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 2511 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 2522 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 2531 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 2546 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 2560 | `activities/` | P3 | offen | tests/test_server.py:3655 (direkt/dynamisch unklar); tests/test_server.py:3663 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 2572 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 2588 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 2603 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7675 (direkt/dynamisch unklar); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7694 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 2610 | `sync/` | P6 | offen | tests/test_server.py:3468 (direkt/dynamisch unklar); tests/test_server.py:7676 (direkt/dynamisch unklar); tests/test_server.py:7702 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 2617 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 2632 | `activities/` | P3 | offen | tests/test_server.py:7741 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 2655 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 2668 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 2686 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 2704 | `sync/` | P6 | offen | tests/test_server.py:7717 (direkt/dynamisch unklar); tests/test_server.py:7730 (direkt/dynamisch unklar); tests/test_server.py:7742 (direkt/dynamisch unklar); tests/test_server.py:7754 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 2719 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3471 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 2734 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 2747 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 2759 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 2762 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 2766 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 2772 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 2777 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 2786 | `sync/` | P6 | offen | tests/test_server.py:3379 (direkt/dynamisch unklar); tests/test_server.py:3380 (direkt/dynamisch unklar); tests/test_server.py:3381 (direkt/dynamisch unklar); tests/test_server.py:3382 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 2805 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 2818 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 2822 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 2840 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 2854 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 2870 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 2876 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 2884 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 2897 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 2910 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 2917 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 2935 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 2940 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 2966 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 2976 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 2985 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3486 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 2995 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3010 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3019 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3024 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3032 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3046 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3057 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3076 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3087 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3104 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3128 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3137 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3148 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3167 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:292 (direkt/dynamisch unklar); tests/test_provider_review.py:307 (direkt/dynamisch unklar); tests/test_server.py:3354 (direkt/dynamisch unklar); tests/test_server.py:3411 (direkt/dynamisch unklar); tests/test_server.py:3444 (direkt/dynamisch unklar); tests/test_server.py:3471 (direkt/dynamisch unklar); tests/test_server.py:3478 (direkt/dynamisch unklar); tests/test_server.py:3518 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3189 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 3204 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 3209 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 3225 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:302 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 3243 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 3262 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 3291 | `planning/` | P4 | offen | tests/test_server.py:3297 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 3308 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 3316 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 3344 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 3351 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 3375 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 3384 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 3401 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 3417 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 3422 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4154 (direkt/dynamisch unklar); tests/test_server.py:4158 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 3423 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 3426 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4157 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 3434 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4156 (direkt/dynamisch unklar); tests/test_server.py:4161 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 3443 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4155 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 3456 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4160 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 3461 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 3483 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 3493 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 3497 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4209 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 3512 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 3513 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 3516 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 3535 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 3549 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 3560 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4199 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 3571 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 3579 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 3584 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 3588 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 3606 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 3616 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 3620 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4185 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 3640 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 3651 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 3669 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:4164 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 3706 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 3711 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4253 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 3719 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 3732 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 3756 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 3785 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 3809 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4245 (direkt/dynamisch unklar); tests/test_server.py:4246 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 3822 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 3834 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 3864 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 3893 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 3900 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 3959 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 3982 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:242 (direkt/dynamisch unklar); tests/test_server.py:277 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4198 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8621 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4024 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:364 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4031 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4042 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:4252 (direkt/dynamisch unklar); tests/test_server.py:4264 (direkt/dynamisch unklar); tests/test_server.py:7874 (direkt/dynamisch unklar); tests/test_server.py:8622 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4082 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:280 (direkt/dynamisch unklar); tests/test_server.py:3317 (direkt/dynamisch unklar); tests/test_server.py:3331 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4105 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1734 (direkt/dynamisch unklar); tests/test_server.py:1766 (direkt/dynamisch unklar); tests/test_server.py:4565 (direkt/dynamisch unklar); tests/test_server.py:4566 (direkt/dynamisch unklar); tests/test_server.py:4567 (direkt/dynamisch unklar); tests/test_server.py:5282 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4112 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4119 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4122 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4134 | `athlete/` | P3 | offen | tests/test_server.py:1180 (direkt/dynamisch unklar); tests/test_server.py:1643 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4143 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1653 (direkt/dynamisch unklar); tests/test_server.py:6799 (direkt/dynamisch unklar); tests/test_server.py:8689 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4152 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:144 (direkt/dynamisch unklar); tests/test_audit_remediation.py:76 (direkt/dynamisch unklar); tests/test_audit_remediation.py:79 (direkt/dynamisch unklar); tests/test_audit_remediation.py:87 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1203 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1228 (direkt/dynamisch unklar); tests/test_server.py:1230 (direkt/dynamisch unklar); tests/test_server.py:1234 (direkt/dynamisch unklar); tests/test_server.py:1248 (direkt/dynamisch unklar); tests/test_server.py:1250 (direkt/dynamisch unklar); tests/test_server.py:1254 (direkt/dynamisch unklar); tests/test_server.py:1262 (direkt/dynamisch unklar); tests/test_server.py:1269 (direkt/dynamisch unklar); tests/test_server.py:1288 (direkt/dynamisch unklar); tests/test_server.py:150 (direkt/dynamisch unklar); tests/test_server.py:1555 (direkt/dynamisch unklar); tests/test_server.py:1572 (direkt/dynamisch unklar); tests/test_server.py:1615 (direkt/dynamisch unklar); tests/test_server.py:1636 (direkt/dynamisch unklar); tests/test_server.py:1638 (direkt/dynamisch unklar); tests/test_server.py:1649 (direkt/dynamisch unklar); tests/test_server.py:2544 (direkt/dynamisch unklar); tests/test_server.py:6752 (direkt/dynamisch unklar); tests/test_server.py:6780 (direkt/dynamisch unklar); tests/test_server.py:7349 (direkt/dynamisch unklar); tests/test_server.py:7494 (direkt/dynamisch unklar); tests/test_server.py:8674 (direkt/dynamisch unklar); tests/test_server.py:8675 (direkt/dynamisch unklar); tests/test_server.py:8704 (direkt/dynamisch unklar); tests/test_server.py:8721 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4166 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4176 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4183 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4186 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 4198 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 4210 | `athlete/` | P3 | offen | tests/test_server.py:1660 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 4230 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2756 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 4235 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1623 (direkt/dynamisch unklar); tests/test_server.py:1632 (direkt/dynamisch unklar); tests/test_server.py:1662 (direkt/dynamisch unklar); tests/test_server.py:1666 (direkt/dynamisch unklar); tests/test_server.py:1680 (direkt/dynamisch unklar); tests/test_server.py:1711 (direkt/dynamisch unklar); tests/test_server.py:2745 (direkt/dynamisch unklar); tests/test_server.py:2766 (direkt/dynamisch unklar); tests/test_server.py:2792 (direkt/dynamisch unklar); tests/test_server.py:2811 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 4243 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 4266 | `athlete/` | P3 | offen | tests/test_server.py:1630 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 4276 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 4283 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 4297 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2406 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 4302 | `activities/` | P3 | offen | tests/test_server.py:2403 (direkt/dynamisch unklar); tests/test_server.py:2405 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 4314 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2373 (direkt/dynamisch unklar); tests/test_server.py:2386 (direkt/dynamisch unklar); tests/test_server.py:2396 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 4331 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 4338 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 4352 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 4364 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 4386 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 4398 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 4412 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 4418 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3253 (direkt/dynamisch unklar); tests/test_server.py:3257 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 4428 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3255 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 4435 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 4448 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3239 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 4469 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:45 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:58 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:6502 (direkt/dynamisch unklar); tests/test_server.py:6584 (direkt/dynamisch unklar); tests/test_server.py:6819 (direkt/dynamisch unklar); tests/test_server.py:6873 (direkt/dynamisch unklar); tests/test_server.py:689 (direkt/dynamisch unklar); tests/test_server.py:6907 (direkt/dynamisch unklar); tests/test_server.py:6944 (direkt/dynamisch unklar); tests/test_server.py:699 (direkt/dynamisch unklar); tests/test_server.py:6991 (direkt/dynamisch unklar); tests/test_server.py:7028 (direkt/dynamisch unklar); tests/test_server.py:7036 (direkt/dynamisch unklar); tests/test_server.py:7063 (direkt/dynamisch unklar); tests/test_server.py:7091 (direkt/dynamisch unklar) |
| Funktion | `_resolve_calendar_addresses` | 4474 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2609 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_calendar_feed_request` | 4489 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_remaining` | 4512 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_fetch_calendar_address` | 4519 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_failure_log` | 4554 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `fetch_calendar_feed` | 4569 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2614 (direkt/dynamisch unklar); tests/test_server.py:2627 (direkt/dynamisch unklar); tests/test_server.py:2664 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2693 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2708 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_ical_temporal_value` | 4624 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_TRAINING_MARKER` | 4654 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_INTENSITY_MARKER` | 4655 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_SHORT_ONLY_MARKER` | 4656 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_TRAINING_MARKERS` | 4657 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_description_contains` | 4660 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_impact` | 4664 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_relevant` | 4669 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_no_intensity` | 4675 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_short_only` | 4680 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_DAY_NUMBERS` | 4685 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_values` | 4688 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_integer` | 4703 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_byday` | 4720 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_bydays` | 4734 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_until` | 4751 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rrule` | 4760 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_shift_local` | 4800 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekday_ordinal` | 4804 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_byday` | 4808 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_date_filters` | 4824 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_dates` | 4837 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_apply_bysetpos` | 4851 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_recurrence_start` | 4863 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_record` | 4868 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_daily_recurrence_starts` | 4887 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_candidate_starts` | 4909 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_recurrence_starts` | 4921 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_period` | 4947 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_candidates` | 4957 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_marker` | 4962 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_first_period_index` | 4966 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_recurrence_starts` | 4975 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_starts` | 5000 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_duration` | 5010 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_occurrence_overlaps_window` | 5021 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rule_starts` | 5026 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rdates` | 5039 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_instances` | 5046 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_calendar_window` | 5063 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_property_parameters` | 5071 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_dates` | 5082 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_temporal_property` | 5097 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_id` | 5107 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_event_property` | 5114 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_append_event` | 5135 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_skip_nested_event_line` | 5144 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_parsed_events` | 5152 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_exception_starts` | 5176 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_event_instances` | 5184 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_expanded_events` | 5198 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `parse_ical_calendar` | 5211 | `providers/calendar.py` | P2 | offen | tests/test_audit_remediation.py:160 (direkt/dynamisch unklar); tests/test_audit_remediation.py:164 (direkt/dynamisch unklar); tests/test_server.py:2437 (direkt/dynamisch unklar); tests/test_server.py:2468 (direkt/dynamisch unklar); tests/test_server.py:2496 (direkt/dynamisch unklar); tests/test_server.py:2502 (direkt/dynamisch unklar); tests/test_server.py:2509 (direkt/dynamisch unklar); tests/test_server.py:2516 (direkt/dynamisch unklar); tests/test_server.py:2521 (direkt/dynamisch unklar); tests/test_server.py:2525 (direkt/dynamisch unklar); tests/test_server.py:2536 (direkt/dynamisch unklar); tests/test_server.py:2551 (direkt/dynamisch unklar); tests/test_server.py:2564 (direkt/dynamisch unklar); tests/test_server.py:2568 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_url` | 5217 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2587 (direkt/dynamisch unklar); tests/test_server.py:2596 (direkt/dynamisch unklar); tests/test_server.py:2715 (direkt/dynamisch unklar); tests/test_server.py:2717 (direkt/dynamisch unklar); tests/test_server.py:7865 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_external_calendar_events` | 5233 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2582 (direkt/dynamisch unklar); tests/test_server.py:2638 (direkt/dynamisch unklar); tests/test_server.py:2679 (direkt/dynamisch unklar); tests/test_server.py:2698 (direkt/dynamisch unklar); tests/test_server.py:2711 (direkt/dynamisch unklar); tests/test_server.py:3159 (direkt/dynamisch unklar); tests/test_server.py:3161 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 5244 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2674 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 5259 | `sync/` | P6 | offen | tests/test_server.py:2581 (direkt/dynamisch unklar); tests/test_server.py:2669 (direkt/dynamisch unklar); tests/test_server.py:2694 (direkt/dynamisch unklar); tests/test_server.py:2710 (direkt/dynamisch unklar); tests/test_server.py:7869 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 5305 | `providers/calendar.py` | P2 | offen | tests/test_audit_remediation.py:163 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 5320 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 5324 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 5328 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 5334 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 5340 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 5348 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 5366 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 5383 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 5410 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 5417 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 5431 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 5463 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 5472 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 5483 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 5502 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 5514 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 5520 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 5533 | `performance/` | P3 | offen | tests/test_server.py:4255 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 5545 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 5549 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 5559 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 5568 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 5578 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 5589 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 5598 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 5618 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 5632 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1692 (direkt/dynamisch unklar); tests/test_server.py:3161 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 5656 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 5665 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 5677 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 5690 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 5705 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 5711 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 5722 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 5730 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 5741 | `athlete/` | P3 | offen | tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:3649 (direkt/dynamisch unklar); tests/test_server.py:6374 (direkt/dynamisch unklar); tests/test_server.py:6402 (direkt/dynamisch unklar); tests/test_server.py:6446 (direkt/dynamisch unklar); tests/test_server.py:6464 (direkt/dynamisch unklar); tests/test_server.py:6473 (direkt/dynamisch unklar); tests/test_server.py:6537 (direkt/dynamisch unklar); tests/test_server.py:6760 (direkt/dynamisch unklar); tests/test_server.py:6827 (direkt/dynamisch unklar); tests/test_server.py:6877 (direkt/dynamisch unklar); tests/test_server.py:6913 (direkt/dynamisch unklar); tests/test_server.py:6952 (direkt/dynamisch unklar); tests/test_server.py:7035 (direkt/dynamisch unklar); tests/test_server.py:7041 (direkt/dynamisch unklar); tests/test_server.py:7067 (direkt/dynamisch unklar); tests/test_server.py:7086 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 5758 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 5780 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 5792 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 5793 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 5798 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 5808 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 5826 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 5838 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 5851 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 5863 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 5882 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:39 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1116 (direkt/dynamisch unklar); tests/test_server.py:461 (direkt/dynamisch unklar); tests/test_server.py:6458 (direkt/dynamisch unklar); tests/test_server.py:6484 (direkt/dynamisch unklar); tests/test_server.py:679 (direkt/dynamisch unklar); tests/test_server.py:6796 (direkt/dynamisch unklar); tests/test_server.py:6801 (direkt/dynamisch unklar); tests/test_server.py:6835 (direkt/dynamisch unklar); tests/test_server.py:6976 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 5890 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:51 (direkt/dynamisch unklar); tests/test_audit_remediation.py:63 (direkt/dynamisch unklar); tests/test_server.py:6816 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 5920 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 5941 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 5964 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 5979 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 5989 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 5995 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3232 (direkt/dynamisch unklar); tests/test_server.py:3233 (direkt/dynamisch unklar); tests/test_server.py:3234 (direkt/dynamisch unklar); tests/test_server.py:3235 (direkt/dynamisch unklar); tests/test_server.py:3236 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 6000 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 6015 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_server.py:6482 (direkt/dynamisch unklar); tests/test_server.py:6814 (direkt/dynamisch unklar); tests/test_server.py:6829 (direkt/dynamisch unklar); tests/test_server.py:6906 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 6019 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3261 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 6039 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3249 (direkt/dynamisch unklar); tests/test_server.py:3250 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 6055 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 6065 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3287 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 6072 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3288 (direkt/dynamisch unklar); tests/test_server.py:3289 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 6078 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3273 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 6106 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 6112 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 6121 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 6131 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6971 (direkt/dynamisch unklar); tests/test_server.py:6988 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 6171 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 6185 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 6198 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 6224 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 6250 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 6258 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 6266 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 6270 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 6308 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 6316 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 6323 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 6338 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 6350 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 6362 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 6369 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 6373 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 6406 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 6429 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 6448 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 6465 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 6473 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 6503 | `sync/` | P6 | offen | tests/test_audit_remediation.py:44 (direkt/dynamisch unklar); tests/test_audit_remediation.py:55 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_audit_remediation.py:71 (direkt/dynamisch unklar); tests/test_server.py:6457 (direkt/dynamisch unklar); tests/test_server.py:6465 (direkt/dynamisch unklar); tests/test_server.py:6501 (direkt/dynamisch unklar); tests/test_server.py:6671 (direkt/dynamisch unklar); tests/test_server.py:6868 (direkt/dynamisch unklar); tests/test_server.py:6900 (direkt/dynamisch unklar); tests/test_server.py:6901 (direkt/dynamisch unklar); tests/test_server.py:6938 (direkt/dynamisch unklar); tests/test_server.py:6970 (direkt/dynamisch unklar); tests/test_server.py:6986 (direkt/dynamisch unklar); tests/test_server.py:6989 (direkt/dynamisch unklar); tests/test_server.py:7025 (direkt/dynamisch unklar); tests/test_server.py:7058 (direkt/dynamisch unklar); tests/test_server.py:7085 (direkt/dynamisch unklar); tests/test_server.py:7087 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_RATE_LIMIT_HEADERS` | 6559 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_STATUS_KEY` | 6568 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `GEMINI_STATUS_KEY` | 6569 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 6570 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `_retry_after_seconds` | 6573 | `providers/http.py` | P2 | offen | tests/test_server.py:8192 (direkt/dynamisch unklar) |
| Funktion | `_safe_openai_error_token` | 6587 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_diagnostic_details` | 6595 | `observability.py` | P1 | offen | tests/test_server.py:8255 (direkt/dynamisch unklar); tests/test_server.py:8278 (direkt/dynamisch unklar) |
| Funktion | `_openai_error_tokens` | 6618 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_invalid_input_state` | 6628 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_conversation_error` | 6636 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_billing_error` | 6647 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_error_reason` | 6658 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_details` | 6678 | `providers/` | P2 | offen | tests/test_server.py:8180 (direkt/dynamisch unklar); tests/test_server.py:8185 (direkt/dynamisch unklar); tests/test_server.py:8253 (direkt/dynamisch unklar); tests/test_server.py:8276 (direkt/dynamisch unklar); tests/test_server.py:8293 (direkt/dynamisch unklar) |
| Funktion | `safe_openai_log_reason` | 6694 | `observability.py` | P1 | offen | tests/test_server.py:8224 (direkt/dynamisch unklar); tests/test_server.py:8225 (direkt/dynamisch unklar) |
| Funktion | `_provider_error_payload` | 6717 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_tokens` | 6726 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_reason` | 6734 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_error_details` | 6748 | `providers/` | P2 | offen | tests/test_server.py:4691 (direkt/dynamisch unklar); tests/test_server.py:4693 (direkt/dynamisch unklar); tests/test_server.py:4694 (direkt/dynamisch unklar) |
| Funktion | `record_openai_status` | 6754 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_success` | 6769 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_rate_limits` | 6779 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_body` | 6791 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 6799 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 6807 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 6819 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 6824 | `coach/context.py` | P7 | offen | tests/test_server.py:7983 (direkt/dynamisch unklar) |
| Funktion | `_read_http_error_body` | 6834 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_urlopen_interruptibly` | 6845 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_body` | 6872 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_parts` | 6880 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_http_request_started` | 6914 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_http_response` | 6927 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 6942 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 6983 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 7002 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 7052 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 7087 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 7092 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 7120 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1780 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4413 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4482 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4606 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4711 (direkt/dynamisch unklar); tests/test_server.py:4752 (direkt/dynamisch unklar); tests/test_server.py:4789 (direkt/dynamisch unklar); tests/test_server.py:4822 (direkt/dynamisch unklar); tests/test_server.py:4882 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5512 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7495 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7889 (direkt/dynamisch unklar); tests/test_server.py:7907 (direkt/dynamisch unklar); tests/test_server.py:7925 (direkt/dynamisch unklar); tests/test_server.py:7959 (direkt/dynamisch unklar); tests/test_server.py:7976 (direkt/dynamisch unklar); tests/test_server.py:8100 (direkt/dynamisch unklar); tests/test_server.py:8136 (direkt/dynamisch unklar); tests/test_server.py:8164 (direkt/dynamisch unklar); tests/test_server.py:8205 (direkt/dynamisch unklar); tests/test_server.py:8549 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 7155 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 7167 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 7176 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 7184 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 7188 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 7194 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 7206 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 7211 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 7237 | `weather/` | P3 | offen | tests/test_server.py:1191 (direkt/dynamisch unklar); tests/test_server.py:1197 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 7247 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 7271 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 7286 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 7305 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 7320 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 7334 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 7355 | `weather/` | P3 | offen | tests/test_server.py:7538 (direkt/dynamisch unklar); tests/test_server.py:7545 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 7402 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 7418 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 7428 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 7449 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 7469 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 7473 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 7496 | `weather/` | P3 | offen | tests/test_audit_remediation.py:106 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:81 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1209 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1235 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1263 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1277 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1296 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1563 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1579 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 7508 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 7519 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 7546 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 7554 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 7567 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 7603 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 7622 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 7628 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 7650 | `weather/` | P3 | offen | tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_audit_remediation.py:147 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:82 (direkt/dynamisch unklar); tests/test_server.py:1210 (direkt/dynamisch unklar); tests/test_server.py:1211 (direkt/dynamisch unklar); tests/test_server.py:1297 (direkt/dynamisch unklar); tests/test_server.py:1298 (direkt/dynamisch unklar); tests/test_server.py:1299 (direkt/dynamisch unklar); tests/test_server.py:1589 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1606 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3025 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7500 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 7668 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 7686 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 7701 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 7708 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 7724 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 7752 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 7765 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 7785 | `sync/` | P6 | offen | tests/test_audit_remediation.py:148 (direkt/dynamisch unklar); tests/test_server.py:1278 (direkt/dynamisch unklar); tests/test_server.py:1279 (direkt/dynamisch unklar); tests/test_server.py:1280 (direkt/dynamisch unklar); tests/test_server.py:1566 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 7801 | `weather/` | P3 | offen | tests/test_server.py:7512 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 7813 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 7826 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 7831 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 7836 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 7840 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 7844 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 7852 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 7868 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 7887 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 7891 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 7900 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 7912 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 7933 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 7960 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 7975 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 7988 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2972 (direkt/dynamisch unklar); tests/test_server.py:2974 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 8026 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 8047 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 8067 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 8085 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2937 (direkt/dynamisch unklar); tests/test_server.py:2997 (direkt/dynamisch unklar); tests/test_server.py:3036 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 8095 | `providers/` | P2 | offen | tests/test_server.py:2998 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 8119 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 8139 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 8145 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 8168 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 8178 | `planning/` | P4 | offen | tests/test_server.py:2897 (direkt/dynamisch unklar); tests/test_server.py:3614 (direkt/dynamisch unklar); tests/test_server.py:6743 (direkt/dynamisch unklar); tests/test_server.py:7111 (direkt/dynamisch unklar); tests/test_server.py:7140 (direkt/dynamisch unklar); tests/test_server.py:7269 (direkt/dynamisch unklar); tests/test_server.py:7293 (direkt/dynamisch unklar); tests/test_server.py:7314 (direkt/dynamisch unklar); tests/test_server.py:7330 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 8216 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 8217 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 8222 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 8225 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 8234 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 8238 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 8247 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 8272 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 8279 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 8290 | `planning/competitions.py` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3844 (direkt/dynamisch unklar); tests/test_server.py:3861 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 8304 | `planning/` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:3126 (direkt/dynamisch unklar); tests/test_server.py:3218 (direkt/dynamisch unklar); tests/test_server.py:3294 (direkt/dynamisch unklar); tests/test_server.py:3880 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 8327 | `planning/` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 8340 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3806 (direkt/dynamisch unklar); tests/test_server.py:3856 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 8367 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 8377 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 8387 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 8394 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 8412 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 8422 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 8435 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 8448 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 8463 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 8472 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:3629 (direkt/dynamisch unklar); tests/test_server.py:3634 (direkt/dynamisch unklar); tests/test_server.py:3635 (direkt/dynamisch unklar); tests/test_server.py:3645 (direkt/dynamisch unklar); tests/test_server.py:3650 (direkt/dynamisch unklar); tests/test_server.py:5085 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 8487 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 8500 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 8524 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 8535 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 8550 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1585 (direkt/dynamisch unklar); tests/test_server.py:1602 (direkt/dynamisch unklar); tests/test_server.py:2642 (direkt/dynamisch unklar); tests/test_server.py:2721 (direkt/dynamisch unklar); tests/test_server.py:2741 (direkt/dynamisch unklar); tests/test_server.py:2788 (direkt/dynamisch unklar); tests/test_server.py:2807 (direkt/dynamisch unklar); tests/test_server.py:2818 (direkt/dynamisch unklar); tests/test_server.py:2850 (direkt/dynamisch unklar); tests/test_server.py:3828 (direkt/dynamisch unklar); tests/test_server.py:3913 (direkt/dynamisch unklar); tests/test_server.py:3941 (direkt/dynamisch unklar); tests/test_server.py:3962 (direkt/dynamisch unklar); tests/test_server.py:3964 (direkt/dynamisch unklar); tests/test_server.py:3971 (direkt/dynamisch unklar); tests/test_server.py:403 (direkt/dynamisch unklar); tests/test_server.py:5596 (direkt/dynamisch unklar); tests/test_server.py:5606 (direkt/dynamisch unklar); tests/test_server.py:5634 (direkt/dynamisch unklar); tests/test_server.py:5879 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6345 (direkt/dynamisch unklar); tests/test_server.py:816 (direkt/dynamisch unklar); tests/test_server.py:849 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 8567 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5600 (direkt/dynamisch unklar); tests/test_server.py:5611 (direkt/dynamisch unklar); tests/test_server.py:5627 (direkt/dynamisch unklar); tests/test_server.py:5639 (direkt/dynamisch unklar); tests/test_server.py:5655 (direkt/dynamisch unklar); tests/test_server.py:5678 (direkt/dynamisch unklar); tests/test_server.py:5700 (direkt/dynamisch unklar); tests/test_server.py:843 (direkt/dynamisch unklar); tests/test_server.py:871 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 8575 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 8583 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 8588 | `planning/` | P4 | offen | tests/test_server.py:5602 (direkt/dynamisch unklar); tests/test_server.py:5612 (direkt/dynamisch unklar); tests/test_server.py:855 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 8605 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 8610 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 8622 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 8640 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 8669 | `planning/` | P4 | offen | tests/test_audit_remediation.py:224 (direkt/dynamisch unklar); tests/test_server.py:1616 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 8681 | `planning/` | P4 | offen | tests/test_server.py:2762 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 8698 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7777 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 8715 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 8740 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 8754 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 8763 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 8781 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 8795 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 8803 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 8821 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 8830 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 8844 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 8859 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 8876 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 8893 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 8917 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 8949 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 8975 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 8996 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 9004 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 9023 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 9046 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1593 (direkt/dynamisch unklar); tests/test_server.py:1610 (direkt/dynamisch unklar); tests/test_server.py:2651 (direkt/dynamisch unklar); tests/test_server.py:2730 (direkt/dynamisch unklar); tests/test_server.py:2746 (direkt/dynamisch unklar); tests/test_server.py:2760 (direkt/dynamisch unklar); tests/test_server.py:2767 (direkt/dynamisch unklar); tests/test_server.py:2793 (direkt/dynamisch unklar); tests/test_server.py:2812 (direkt/dynamisch unklar); tests/test_server.py:2822 (direkt/dynamisch unklar); tests/test_server.py:2859 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 9077 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 9088 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 9104 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 9119 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 9129 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 9168 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 9183 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 9191 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 9213 | `planning/` | P4 | offen | tests/test_audit_remediation.py:228 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2751 (direkt/dynamisch unklar); tests/test_server.py:2778 (direkt/dynamisch unklar); tests/test_server.py:2797 (direkt/dynamisch unklar); tests/test_server.py:2802 (direkt/dynamisch unklar); tests/test_server.py:2814 (direkt/dynamisch unklar); tests/test_server.py:2823 (direkt/dynamisch unklar); tests/test_server.py:2826 (direkt/dynamisch unklar); tests/test_server.py:2860 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 9243 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 9267 | `planning/` | P4 | offen | tests/test_server.py:1617 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 9271 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 9279 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 9295 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 9308 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 9313 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 9318 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 9327 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 9336 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 9358 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 9364 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 9368 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 9381 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 9395 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 9401 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 9414 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 9427 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 9448 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 9464 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 9474 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 9490 | `planning/` | P4 | offen | tests/test_server.py:2838 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 9513 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 9529 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 9532 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 9556 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 9565 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:3045 (direkt/dynamisch unklar); tests/test_server.py:3167 (direkt/dynamisch unklar); tests/test_server.py:3188 (direkt/dynamisch unklar); tests/test_server.py:3641 (direkt/dynamisch unklar); tests/test_server.py:373 (direkt/dynamisch unklar); tests/test_server.py:4948 (direkt/dynamisch unklar); tests/test_server.py:4970 (direkt/dynamisch unklar); tests/test_server.py:5026 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5061 (direkt/dynamisch unklar); tests/test_server.py:5079 (direkt/dynamisch unklar); tests/test_server.py:5100 (direkt/dynamisch unklar); tests/test_server.py:5123 (direkt/dynamisch unklar); tests/test_server.py:5168 (direkt/dynamisch unklar); tests/test_server.py:5190 (direkt/dynamisch unklar); tests/test_server.py:5213 (direkt/dynamisch unklar); tests/test_server.py:5229 (direkt/dynamisch unklar); tests/test_server.py:5246 (direkt/dynamisch unklar); tests/test_server.py:5309 (direkt/dynamisch unklar); tests/test_server.py:5371 (direkt/dynamisch unklar); tests/test_server.py:5380 (direkt/dynamisch unklar); tests/test_server.py:5538 (direkt/dynamisch unklar); tests/test_server.py:5569 (direkt/dynamisch unklar); tests/test_server.py:5732 (direkt/dynamisch unklar); tests/test_server.py:5762 (direkt/dynamisch unklar); tests/test_server.py:5780 (direkt/dynamisch unklar); tests/test_server.py:5785 (direkt/dynamisch unklar); tests/test_server.py:5794 (direkt/dynamisch unklar); tests/test_server.py:5798 (direkt/dynamisch unklar); tests/test_server.py:5803 (direkt/dynamisch unklar); tests/test_server.py:5812 (direkt/dynamisch unklar); tests/test_server.py:5831 (direkt/dynamisch unklar); tests/test_server.py:5834 (direkt/dynamisch unklar); tests/test_server.py:5860 (direkt/dynamisch unklar); tests/test_server.py:703 (direkt/dynamisch unklar); tests/test_server.py:726 (direkt/dynamisch unklar); tests/test_server.py:7373 (direkt/dynamisch unklar); tests/test_server.py:743 (direkt/dynamisch unklar); tests/test_server.py:769 (direkt/dynamisch unklar); tests/test_server.py:773 (direkt/dynamisch unklar); tests/test_server.py:876 (direkt/dynamisch unklar); tests/test_server.py:896 (direkt/dynamisch unklar); tests/test_server.py:900 (direkt/dynamisch unklar); tests/test_server.py:923 (direkt/dynamisch unklar); tests/test_server.py:971 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 9583 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2754 (direkt/dynamisch unklar); tests/test_server.py:2755 (direkt/dynamisch unklar); tests/test_server.py:2763 (direkt/dynamisch unklar); tests/test_server.py:2828 (direkt/dynamisch unklar); tests/test_server.py:3099 (direkt/dynamisch unklar); tests/test_server.py:3109 (direkt/dynamisch unklar); tests/test_server.py:3112 (direkt/dynamisch unklar); tests/test_server.py:3123 (direkt/dynamisch unklar); tests/test_server.py:3139 (direkt/dynamisch unklar); tests/test_server.py:3210 (direkt/dynamisch unklar); tests/test_server.py:3951 (direkt/dynamisch unklar); tests/test_server.py:3955 (direkt/dynamisch unklar); tests/test_server.py:3963 (direkt/dynamisch unklar); tests/test_server.py:3967 (direkt/dynamisch unklar); tests/test_server.py:4961 (direkt/dynamisch unklar); tests/test_server.py:4987 (direkt/dynamisch unklar); tests/test_server.py:5004 (direkt/dynamisch unklar); tests/test_server.py:5038 (direkt/dynamisch unklar); tests/test_server.py:5056 (direkt/dynamisch unklar); tests/test_server.py:5074 (direkt/dynamisch unklar); tests/test_server.py:5113 (direkt/dynamisch unklar); tests/test_server.py:5137 (direkt/dynamisch unklar); tests/test_server.py:5159 (direkt/dynamisch unklar); tests/test_server.py:5226 (direkt/dynamisch unklar); tests/test_server.py:5242 (direkt/dynamisch unklar); tests/test_server.py:5263 (direkt/dynamisch unklar); tests/test_server.py:5563 (direkt/dynamisch unklar); tests/test_server.py:5564 (direkt/dynamisch unklar); tests/test_server.py:5653 (direkt/dynamisch unklar); tests/test_server.py:5727 (direkt/dynamisch unklar); tests/test_server.py:5855 (direkt/dynamisch unklar); tests/test_server.py:5885 (direkt/dynamisch unklar); tests/test_server.py:6255 (direkt/dynamisch unklar); tests/test_server.py:766 (direkt/dynamisch unklar); tests/test_server.py:794 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 9595 | `planning/` | P4 | offen | tests/test_server.py:3711 (direkt/dynamisch unklar); tests/test_server.py:3922 (direkt/dynamisch unklar); tests/test_server.py:3984 (direkt/dynamisch unklar); tests/test_server.py:6284 (direkt/dynamisch unklar); tests/test_server.py:6321 (direkt/dynamisch unklar); tests/test_server.py:6365 (direkt/dynamisch unklar); tests/test_server.py:6524 (direkt/dynamisch unklar); tests/test_server.py:8695 (direkt/dynamisch unklar); tests/test_server.py:8785 (direkt/dynamisch unklar); tests/test_server.py:8786 (direkt/dynamisch unklar); tests/test_server.py:994 (direkt/dynamisch unklar); tests/test_server.py:997 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 9623 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3910 (direkt/dynamisch unklar); tests/test_server.py:536 (direkt/dynamisch unklar); tests/test_server.py:730 (direkt/dynamisch unklar); tests/test_server.py:948 (direkt/dynamisch unklar); tests/test_server.py:968 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 9646 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 9661 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 9678 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 9693 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 9716 | `planning/` | P4 | offen | tests/test_server.py:1429 (direkt/dynamisch unklar); tests/test_server.py:1746 (direkt/dynamisch unklar); tests/test_server.py:3696 (direkt/dynamisch unklar); tests/test_server.py:3702 (direkt/dynamisch unklar); tests/test_server.py:3726 (direkt/dynamisch unklar); tests/test_server.py:4335 (direkt/dynamisch unklar); tests/test_server.py:4351 (direkt/dynamisch unklar); tests/test_server.py:4369 (direkt/dynamisch unklar); tests/test_server.py:4384 (direkt/dynamisch unklar); tests/test_server.py:6338 (direkt/dynamisch unklar); tests/test_server.py:6538 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 9741 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3707 (direkt/dynamisch unklar); tests/test_server.py:3716 (direkt/dynamisch unklar); tests/test_server.py:3718 (direkt/dynamisch unklar); tests/test_server.py:3719 (direkt/dynamisch unklar); tests/test_server.py:3721 (direkt/dynamisch unklar); tests/test_server.py:3723 (direkt/dynamisch unklar); tests/test_server.py:3931 (direkt/dynamisch unklar); tests/test_server.py:3994 (direkt/dynamisch unklar); tests/test_server.py:4339 (direkt/dynamisch unklar); tests/test_server.py:4347 (direkt/dynamisch unklar); tests/test_server.py:4355 (direkt/dynamisch unklar); tests/test_server.py:4365 (direkt/dynamisch unklar); tests/test_server.py:4373 (direkt/dynamisch unklar); tests/test_server.py:4381 (direkt/dynamisch unklar); tests/test_server.py:4388 (direkt/dynamisch unklar); tests/test_server.py:6213 (direkt/dynamisch unklar); tests/test_server.py:6302 (direkt/dynamisch unklar); tests/test_server.py:6355 (direkt/dynamisch unklar); tests/test_server.py:6590 (direkt/dynamisch unklar); tests/test_server.py:8701 (direkt/dynamisch unklar); tests/test_server.py:964 (direkt/dynamisch unklar); tests/test_server.py:965 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 9748 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 9765 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 9766 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 9767 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 9768 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 9771 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 9778 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 9783 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 9793 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 9800 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1725 (direkt/dynamisch unklar); tests/test_server.py:1726 (direkt/dynamisch unklar); tests/test_server.py:1727 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 9827 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_audit_remediation.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1735 (direkt/dynamisch unklar); tests/test_server.py:1736 (direkt/dynamisch unklar); tests/test_server.py:1741 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 9859 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1750 (direkt/dynamisch unklar); tests/test_server.py:1751 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 9887 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1901 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 9908 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 9928 | `activities/` | P3 | offen | tests/test_server.py:532 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 9969 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 9974 | `planning/` | P4 | offen | tests/test_server.py:2737 (direkt/dynamisch unklar); tests/test_server.py:2750 (direkt/dynamisch unklar); tests/test_server.py:2753 (direkt/dynamisch unklar); tests/test_server.py:2801 (direkt/dynamisch unklar); tests/test_server.py:2827 (direkt/dynamisch unklar); tests/test_server.py:2861 (direkt/dynamisch unklar); tests/test_server.py:2864 (direkt/dynamisch unklar); tests/test_server.py:3024 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3074 (direkt/dynamisch unklar); tests/test_server.py:3091 (direkt/dynamisch unklar); tests/test_server.py:3185 (direkt/dynamisch unklar); tests/test_server.py:3830 (direkt/dynamisch unklar); tests/test_server.py:3919 (direkt/dynamisch unklar); tests/test_server.py:3977 (direkt/dynamisch unklar); tests/test_server.py:4348 (direkt/dynamisch unklar); tests/test_server.py:4366 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 9979 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 9986 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 9997 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 10009 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 10034 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 10050 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 10058 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 10072 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 10084 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:3059 (direkt/dynamisch unklar); tests/test_server.py:3074 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 10103 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 10108 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 10125 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 10139 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 10146 | `calendar/` | P3 | offen | tests/test_server.py:3159 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 10161 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 10174 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 10187 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 10244 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 10261 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 10301 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 10308 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 10316 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 10324 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 10337 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 10347 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 10359 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 10388 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 10398 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 10420 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:309 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 10437 | `sync/` | P6 | offen | tests/test_server.py:3950 (direkt/dynamisch unklar); tests/test_server.py:3954 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 10442 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 10460 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 10467 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 10476 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 10491 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 10496 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 10502 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 10510 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 10522 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 10531 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 10548 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 10568 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 10571 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 10584 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 10596 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 10619 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 10639 | `planning/` | P4 | offen | tests/test_server.py:6108 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6137 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6150 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6170 (direkt/dynamisch unklar); tests/test_server.py:6249 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6273 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6314 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6332 (direkt/dynamisch unklar); tests/test_server.py:659 (Monkeypatch/getattr/sys.modules); tests/test_server.py:672 (Monkeypatch/getattr/sys.modules) |
| Funktion | `plan_library_workout_remote` | 10680 | `planning/` | P4 | offen | tests/test_server.py:6513 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 10684 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 10705 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 10720 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 10726 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 10733 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 10748 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 10763 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 10773 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 10779 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 10794 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 10802 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1433 (direkt/dynamisch unklar); tests/test_server.py:3714 (direkt/dynamisch unklar); tests/test_server.py:3717 (direkt/dynamisch unklar); tests/test_server.py:3720 (direkt/dynamisch unklar); tests/test_server.py:3722 (direkt/dynamisch unklar); tests/test_server.py:3728 (direkt/dynamisch unklar); tests/test_server.py:3730 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 10826 | `planning/` | P4 | offen | tests/test_server.py:6528 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 10845 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 10861 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 10873 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 10887 | `calendar/` | P3 | offen | tests/test_server.py:7990 (direkt/dynamisch unklar); tests/test_server.py:8000 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 10922 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 10952 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 10970 | `sync/` | P6 | offen | tests/test_server.py:1902 (direkt/dynamisch unklar); tests/test_server.py:2147 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 10974 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 10989 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 11008 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 11021 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 11035 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 11054 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 11067 | `sync/` | P6 | offen | tests/test_server.py:3929 (direkt/dynamisch unklar); tests/test_server.py:3935 (direkt/dynamisch unklar); tests/test_server.py:3991 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 11082 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 11090 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 11114 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 11119 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 11142 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 11149 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 11174 | `planning/` | P4 | offen | tests/test_server.py:4341 (direkt/dynamisch unklar); tests/test_server.py:4361 (direkt/dynamisch unklar); tests/test_server.py:4376 (direkt/dynamisch unklar); tests/test_server.py:4390 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 11188 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 11197 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 11208 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 11217 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 11229 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 11242 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 11246 | `sync/` | P6 | offen | tests/test_server.py:6577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8793 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 11259 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 11272 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 11276 | `sync/` | P6 | offen | tests/test_server.py:310 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 11295 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 11310 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 11325 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 11341 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 11354 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 11371 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 11382 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 11398 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 11416 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 11435 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 11458 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 11473 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 11482 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 11503 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 11521 | `planning/calendar.py` | P3 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 11545 | `planning/` | P4 | offen | tests/test_server.py:2795 (direkt/dynamisch unklar); tests/test_server.py:2813 (direkt/dynamisch unklar); tests/test_server.py:3096 (direkt/dynamisch unklar); tests/test_server.py:3110 (direkt/dynamisch unklar); tests/test_server.py:3140 (direkt/dynamisch unklar); tests/test_server.py:3172 (direkt/dynamisch unklar); tests/test_server.py:3179 (direkt/dynamisch unklar); tests/test_server.py:3181 (direkt/dynamisch unklar); tests/test_server.py:3183 (direkt/dynamisch unklar); tests/test_server.py:3193 (direkt/dynamisch unklar); tests/test_server.py:3195 (direkt/dynamisch unklar); tests/test_server.py:3644 (direkt/dynamisch unklar); tests/test_server.py:3918 (direkt/dynamisch unklar); tests/test_server.py:3966 (direkt/dynamisch unklar); tests/test_server.py:5084 (direkt/dynamisch unklar); tests/test_server.py:5784 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 11571 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 11582 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 11593 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 11603 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 11609 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 11620 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 11632 | `planning/` | P4 | offen | tests/test_server.py:3142 (direkt/dynamisch unklar); tests/test_server.py:3145 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 11650 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:92 (direkt/dynamisch unklar); tests/test_server.py:1693 (direkt/dynamisch unklar); tests/test_server.py:1694 (direkt/dynamisch unklar); tests/test_server.py:3023 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5463 (direkt/dynamisch unklar); tests/test_server.py:5465 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6605 (direkt/dynamisch unklar); tests/test_server.py:7762 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 11655 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:110 (direkt/dynamisch unklar); tests/test_provider_review.py:230 (direkt/dynamisch unklar); tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_provider_review.py:63 (direkt/dynamisch unklar); tests/test_provider_review.py:87 (direkt/dynamisch unklar); tests/test_server.py:1461 (direkt/dynamisch unklar); tests/test_server.py:1673 (direkt/dynamisch unklar); tests/test_server.py:1710 (direkt/dynamisch unklar); tests/test_server.py:1718 (direkt/dynamisch unklar); tests/test_server.py:1758 (direkt/dynamisch unklar); tests/test_server.py:2366 (direkt/dynamisch unklar); tests/test_server.py:2391 (direkt/dynamisch unklar); tests/test_server.py:3670 (direkt/dynamisch unklar); tests/test_server.py:3735 (direkt/dynamisch unklar); tests/test_server.py:4357 (direkt/dynamisch unklar); tests/test_server.py:487 (direkt/dynamisch unklar); tests/test_server.py:5417 (direkt/dynamisch unklar); tests/test_server.py:5458 (direkt/dynamisch unklar); tests/test_server.py:6594 (direkt/dynamisch unklar); tests/test_server.py:7375 (direkt/dynamisch unklar); tests/test_server.py:7753 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 11665 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 11691 | `sync/` | P6 | offen | tests/test_server.py:1046 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 11716 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 11721 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 11731 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 11739 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 11770 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 11792 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 11803 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 11817 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 11839 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 11856 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 11890 | `planning/` | P4 | offen | tests/test_server.py:3087 (direkt/dynamisch unklar); tests/test_server.py:3089 (direkt/dynamisch unklar); tests/test_server.py:3097 (direkt/dynamisch unklar); tests/test_server.py:3108 (direkt/dynamisch unklar); tests/test_server.py:3111 (direkt/dynamisch unklar); tests/test_server.py:3119 (direkt/dynamisch unklar); tests/test_server.py:3138 (direkt/dynamisch unklar); tests/test_server.py:3141 (direkt/dynamisch unklar); tests/test_server.py:3144 (direkt/dynamisch unklar); tests/test_server.py:3628 (direkt/dynamisch unklar); tests/test_server.py:3633 (direkt/dynamisch unklar); tests/test_server.py:5712 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 11938 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 11954 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 11966 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 11978 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 11983 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 11993 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 12000 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 12007 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 12018 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 12033 | `sync/` | P6 | offen | tests/test_server.py:6440 (direkt/dynamisch unklar); tests/test_server.py:6578 (direkt/dynamisch unklar); tests/test_server.py:6604 (direkt/dynamisch unklar); tests/test_server.py:6614 (direkt/dynamisch unklar); tests/test_server.py:6690 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 12068 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 12083 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 12112 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 12141 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 12161 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 12178 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 12235 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 12250 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 12261 | `sync/` | P6 | offen | tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6109 (direkt/dynamisch unklar); tests/test_server.py:6124 (direkt/dynamisch unklar); tests/test_server.py:6139 (direkt/dynamisch unklar); tests/test_server.py:6152 (direkt/dynamisch unklar); tests/test_server.py:617 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6181 (direkt/dynamisch unklar); tests/test_server.py:6210 (direkt/dynamisch unklar); tests/test_server.py:6250 (direkt/dynamisch unklar); tests/test_server.py:6251 (direkt/dynamisch unklar); tests/test_server.py:6275 (direkt/dynamisch unklar); tests/test_server.py:6277 (direkt/dynamisch unklar); tests/test_server.py:6297 (direkt/dynamisch unklar); tests/test_server.py:6315 (direkt/dynamisch unklar); tests/test_server.py:6432 (direkt/dynamisch unklar); tests/test_server.py:6533 (direkt/dynamisch unklar); tests/test_server.py:662 (direkt/dynamisch unklar); tests/test_server.py:675 (direkt/dynamisch unklar); tests/test_server.py:7806 (direkt/dynamisch unklar); tests/test_server.py:8073 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 12295 | `performance/` | P3 | offen | tests/test_provider_review.py:77 (direkt/dynamisch unklar); tests/test_server.py:593 (Monkeypatch/getattr/sys.modules); tests/test_server.py:606 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7367 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 12319 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 12326 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 12333 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 12351 | `activities/` | P3 | offen | tests/test_server.py:5331 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 12363 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 12380 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 12393 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 12410 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 12431 | `performance/` | P3 | offen | tests/test_server.py:7264 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 12440 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 12452 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 12468 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 12483 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 12519 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 12529 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 12543 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 12559 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 12576 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 12586 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 12597 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 12611 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 12623 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 12628 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 12660 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 12669 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 12675 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 12682 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 12696 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 12709 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 12713 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 12742 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 12749 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 12786 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 12806 | `performance/` | P3 | offen | tests/test_server.py:3389 (direkt/dynamisch unklar); tests/test_server.py:3398 (direkt/dynamisch unklar); tests/test_server.py:3506 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 12835 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 12849 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 12865 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 12873 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 12883 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 12910 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 12925 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 12948 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 12966 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 12998 | `activities/` | P3 | offen | tests/test_server.py:7163 (direkt/dynamisch unklar); tests/test_server.py:7185 (direkt/dynamisch unklar); tests/test_server.py:7191 (direkt/dynamisch unklar); tests/test_server.py:7200 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 13043 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 13076 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 13097 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 13109 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 13129 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 13142 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 13173 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 13203 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 13214 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 13257 | `performance/` | P3 | offen | tests/test_provider_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:3529 (direkt/dynamisch unklar); tests/test_server.py:3559 (direkt/dynamisch unklar); tests/test_server.py:3588 (direkt/dynamisch unklar); tests/test_server.py:3609 (direkt/dynamisch unklar); tests/test_server.py:3621 (direkt/dynamisch unklar); tests/test_server.py:7102 (direkt/dynamisch unklar); tests/test_server.py:7124 (direkt/dynamisch unklar); tests/test_server.py:7151 (direkt/dynamisch unklar); tests/test_server.py:7220 (direkt/dynamisch unklar); tests/test_server.py:7234 (direkt/dynamisch unklar); tests/test_server.py:7250 (direkt/dynamisch unklar); tests/test_server.py:7281 (direkt/dynamisch unklar); tests/test_server.py:7302 (direkt/dynamisch unklar); tests/test_server.py:7324 (direkt/dynamisch unklar); tests/test_server.py:7344 (direkt/dynamisch unklar); tests/test_server.py:7350 (direkt/dynamisch unklar); tests/test_server.py:7354 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 13328 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 13342 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 13346 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 13350 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 13355 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 13359 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 13363 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 13367 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 13371 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 13390 | `coach/context.py` | P7 | offen | tests/test_server.py:5321 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 13409 | `coach/context.py` | P7 | offen | tests/test_server.py:5313 (direkt/dynamisch unklar); tests/test_server.py:5350 (direkt/dynamisch unklar); tests/test_server.py:5351 (direkt/dynamisch unklar); tests/test_server.py:5372 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 13455 | `coach/context.py` | P7 | offen | tests/test_server.py:1580 (direkt/dynamisch unklar); tests/test_server.py:1654 (direkt/dynamisch unklar); tests/test_server.py:2380 (direkt/dynamisch unklar); tests/test_server.py:3342 (direkt/dynamisch unklar); tests/test_server.py:5393 (direkt/dynamisch unklar); tests/test_server.py:5399 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6775 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 13520 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 13538 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 13548 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 13565 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:248 (direkt/dynamisch unklar); tests/test_provider_review.py:282 (direkt/dynamisch unklar); tests/test_server.py:3708 (direkt/dynamisch unklar); tests/test_server.py:5389 (direkt/dynamisch unklar); tests/test_server.py:5400 (direkt/dynamisch unklar); tests/test_server.py:5401 (direkt/dynamisch unklar); tests/test_server.py:5418 (direkt/dynamisch unklar); tests/test_server.py:5429 (direkt/dynamisch unklar); tests/test_server.py:5461 (direkt/dynamisch unklar); tests/test_server.py:6753 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 13605 | `coach/context.py` | P7 | offen | tests/test_server.py:5283 (direkt/dynamisch unklar); tests/test_server.py:5423 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 13661 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 13691 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_openai_usage_summary_unlocked` | 13701 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_usage_summary` | 13724 | `providers/` | P2 | offen | tests/test_server.py:8137 (direkt/dynamisch unklar); tests/test_server.py:8167 (direkt/dynamisch unklar); tests/test_server.py:8359 (direkt/dynamisch unklar); tests/test_server.py:8369 (direkt/dynamisch unklar); tests/test_server.py:8393 (direkt/dynamisch unklar); tests/test_server.py:8416 (direkt/dynamisch unklar); tests/test_server.py:8560 (direkt/dynamisch unklar); tests/test_server.py:8598 (direkt/dynamisch unklar) |
| Funktion | `_record_openai_usage_unlocked` | 13732 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_usage` | 13761 | `providers/` | P2 | offen | tests/test_server.py:5903 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8555 (direkt/dynamisch unklar); tests/test_server.py:8596 (direkt/dynamisch unklar) |
| Funktion | `_validate_openai_response` | 13768 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8537 (direkt/dynamisch unklar); tests/test_server.py:8540 (direkt/dynamisch unklar); tests/test_server.py:8543 (direkt/dynamisch unklar) |
| Funktion | `openai_endpoint` | 13790 | `providers/` | P2 | offen | tests/test_server.py:4859 (direkt/dynamisch unklar); tests/test_server.py:4860 (direkt/dynamisch unklar); tests/test_server.py:4862 (direkt/dynamisch unklar); tests/test_server.py:4871 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 13807 | `providers/` | P2 | offen | tests/test_server.py:4652 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4883 (direkt/dynamisch unklar); tests/test_server.py:5506 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5515 (direkt/dynamisch unklar); tests/test_server.py:6108 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7365 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8550 (direkt/dynamisch unklar) |
| Funktion | `multipart_form_data` | 13831 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VOICE_AUDIO_TYPES` | 13856 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `normalized_audio_type` | 13868 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `transcribe_audio` | 13872 | `providers/` | P2 | offen | tests/test_server.py:4622 (direkt/dynamisch unklar); tests/test_server.py:4842 (direkt/dynamisch unklar); tests/test_server.py:4915 (direkt/dynamisch unklar); tests/test_server.py:4917 (direkt/dynamisch unklar) |
| Funktion | `_provider_usage_summary` | 13924 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_usage_summary` | 13941 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_status` | 13946 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_usage` | 13952 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_content_has_function_response` | 13971 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 13976 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 13983 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 13994 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 14010 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 14022 | `providers/` | P2 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4545 (direkt/dynamisch unklar); tests/test_server.py:4677 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 14030 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 14042 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 14058 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 14074 | `providers/` | P2 | offen | tests/test_server.py:4556 (direkt/dynamisch unklar); tests/test_server.py:4561 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 14096 | `providers/` | P2 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_text` | 14118 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_tools` | 14122 | `providers/` | P2 | offen | tests/test_server.py:4717 (direkt/dynamisch unklar) |
| Funktion | `_gemini_request_payload` | 14126 | `providers/` | P2 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4573 (direkt/dynamisch unklar); tests/test_server.py:4586 (direkt/dynamisch unklar); tests/test_server.py:4656 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 14222 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 14241 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 14280 | `providers/` | P2 | offen | tests/test_server.py:4414 (direkt/dynamisch unklar); tests/test_server.py:4416 (direkt/dynamisch unklar); tests/test_server.py:4483 (direkt/dynamisch unklar); tests/test_server.py:4486 (direkt/dynamisch unklar); tests/test_server.py:4608 (direkt/dynamisch unklar); tests/test_server.py:4652 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 14287 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `request_ai_provider` | 14428 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 14433 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4653 (direkt/dynamisch unklar); tests/test_server.py:5507 (direkt/dynamisch unklar); tests/test_server.py:5898 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8239 (direkt/dynamisch unklar) |
| Funktion | `_openai_response_id` | 14458 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `retrieve_openai_response` | 14465 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 14480 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 14498 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5904 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 14535 | `coach/context.py` | P7 | offen | tests/test_server.py:6164 (direkt/dynamisch unklar) |
| Funktion | `_notify_openai_stream_response_id` | 14540 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_forward_openai_stream_delta` | 14553 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_stream_final_response` | 14561 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_consume_openai_sse_event` | 14568 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_read_openai_stream_response` | 14587 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_openai_stream_failure` | 14623 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_capture_openai_stream_failure` | 14641 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 14655 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 14667 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 14678 | `providers/` | P2 | offen | tests/test_server.py:8219 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 14695 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 14711 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 14726 | `providers/` | P2 | offen | tests/test_server.py:4907 (direkt/dynamisch unklar); tests/test_server.py:8311 (direkt/dynamisch unklar); tests/test_server.py:8352 (direkt/dynamisch unklar); tests/test_server.py:8366 (direkt/dynamisch unklar); tests/test_server.py:8390 (direkt/dynamisch unklar); tests/test_server.py:8415 (direkt/dynamisch unklar); tests/test_server.py:8421 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 14803 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4458 (direkt/dynamisch unklar); tests/test_server.py:6004 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8422 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 14829 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 14848 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 14861 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 14879 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 14892 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 14898 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 14906 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:292 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4686 (direkt/dynamisch unklar); tests/test_server.py:5529 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 14915 | `providers/` | P2 | offen | tests/test_server.py:4398 (direkt/dynamisch unklar); tests/test_server.py:4430 (direkt/dynamisch unklar); tests/test_server.py:4464 (direkt/dynamisch unklar); tests/test_server.py:4652 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 14919 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 14920 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 14923 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 14927 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 14940 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 14965 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 14989 | `activities/` | P3 | offen | tests/test_server.py:7756 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 15009 | `coach/context.py` | P7 | offen | tests/test_server.py:8659 (direkt/dynamisch unklar); tests/test_server.py:8670 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 15031 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 15040 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 15062 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8686 (direkt/dynamisch unklar); tests/test_server.py:8698 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 15086 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 15095 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8687 (direkt/dynamisch unklar); tests/test_server.py:8699 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 15124 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 15128 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6029 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 15145 | `coach/context.py` | P7 | offen | tests/test_server.py:6058 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 15149 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:6049 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 15161 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 15178 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 15205 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 15214 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 15231 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 15283 | `sync/` | P6 | offen | tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4666 (direkt/dynamisch unklar); tests/test_server.py:5915 (direkt/dynamisch unklar); tests/test_server.py:5943 (direkt/dynamisch unklar); tests/test_server.py:5964 (direkt/dynamisch unklar); tests/test_server.py:5991 (direkt/dynamisch unklar); tests/test_server.py:6018 (direkt/dynamisch unklar); tests/test_server.py:6042 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 15316 | `coach/context.py` | P7 | offen | tests/test_server.py:5962 (direkt/dynamisch unklar); tests/test_server.py:8430 (direkt/dynamisch unklar); tests/test_server.py:8433 (direkt/dynamisch unklar); tests/test_server.py:8447 (direkt/dynamisch unklar); tests/test_server.py:8468 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8495 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8508 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 15330 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 15345 | `coach/context.py` | P7 | offen | tests/test_server.py:5978 (direkt/dynamisch unklar); tests/test_server.py:8470 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8497 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 15354 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 15363 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 15375 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 15392 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:257 (direkt/dynamisch unklar); tests/test_server.py:8436 (direkt/dynamisch unklar); tests/test_server.py:8438 (direkt/dynamisch unklar); tests/test_server.py:8512 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 15400 | `coach/context.py` | P7 | offen | tests/test_server.py:5986 (direkt/dynamisch unklar); tests/test_server.py:8442 (direkt/dynamisch unklar); tests/test_server.py:8453 (direkt/dynamisch unklar); tests/test_server.py:8469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8517 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 15407 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 15408 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 15409 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 15409 | `coach/` | P7 | offen | tests/test_server.py:397 (direkt/dynamisch unklar); tests/test_server.py:453 (direkt/dynamisch unklar); tests/test_server.py:4923 (direkt/dynamisch unklar); tests/test_server.py:4926 (direkt/dynamisch unklar); tests/test_server.py:5276 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 15409 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 15409 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 15418 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 15426 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 15430 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 15435 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 15446 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 15471 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 15490 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 15502 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:3088 (direkt/dynamisch unklar); tests/test_server.py:3090 (direkt/dynamisch unklar); tests/test_server.py:5542 (direkt/dynamisch unklar); tests/test_server.py:5578 (direkt/dynamisch unklar); tests/test_server.py:5601 (direkt/dynamisch unklar); tests/test_server.py:5603 (direkt/dynamisch unklar); tests/test_server.py:5619 (direkt/dynamisch unklar); tests/test_server.py:5626 (direkt/dynamisch unklar); tests/test_server.py:5640 (direkt/dynamisch unklar); tests/test_server.py:5663 (direkt/dynamisch unklar); tests/test_server.py:5688 (direkt/dynamisch unklar); tests/test_server.py:5717 (direkt/dynamisch unklar); tests/test_server.py:5737 (direkt/dynamisch unklar); tests/test_server.py:5789 (direkt/dynamisch unklar); tests/test_server.py:5802 (direkt/dynamisch unklar); tests/test_server.py:5808 (direkt/dynamisch unklar); tests/test_server.py:5837 (direkt/dynamisch unklar); tests/test_server.py:5864 (direkt/dynamisch unklar); tests/test_server.py:5867 (direkt/dynamisch unklar); tests/test_server.py:5888 (direkt/dynamisch unklar); tests/test_server.py:734 (direkt/dynamisch unklar); tests/test_server.py:747 (direkt/dynamisch unklar); tests/test_server.py:823 (direkt/dynamisch unklar); tests/test_server.py:858 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 15525 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 15532 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 15539 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 15557 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 15567 | `coach/proposals.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:320 (direkt/dynamisch unklar); tests/test_server.py:345 (direkt/dynamisch unklar); tests/test_server.py:4592 (direkt/dynamisch unklar); tests/test_server.py:5523 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 15580 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 15589 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 15600 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 15632 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 15658 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 15678 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 15702 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 15714 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 15727 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 15741 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 15749 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 15760 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 15782 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 15792 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 15806 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 15818 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 15832 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 15840 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 15853 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 15862 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 15884 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 15902 | `planning/` | P4 | offen | tests/test_server.py:4953 (direkt/dynamisch unklar); tests/test_server.py:4975 (direkt/dynamisch unklar); tests/test_server.py:4994 (direkt/dynamisch unklar); tests/test_server.py:5016 (direkt/dynamisch unklar); tests/test_server.py:5031 (direkt/dynamisch unklar); tests/test_server.py:5047 (direkt/dynamisch unklar); tests/test_server.py:5065 (direkt/dynamisch unklar); tests/test_server.py:5087 (direkt/dynamisch unklar); tests/test_server.py:5105 (direkt/dynamisch unklar); tests/test_server.py:5128 (direkt/dynamisch unklar); tests/test_server.py:5172 (direkt/dynamisch unklar); tests/test_server.py:5197 (direkt/dynamisch unklar); tests/test_server.py:5218 (direkt/dynamisch unklar); tests/test_server.py:5233 (direkt/dynamisch unklar); tests/test_server.py:5252 (direkt/dynamisch unklar); tests/test_server.py:5269 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 15913 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 15923 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 15940 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 15951 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 15981 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 15999 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 16005 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 16018 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 16036 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 16052 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 16065 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 16079 | `planning/` | P4 | offen | tests/test_server.py:5643 (direkt/dynamisch unklar); tests/test_server.py:5690 (direkt/dynamisch unklar); tests/test_server.py:5718 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 16113 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:1005 (direkt/dynamisch unklar); tests/test_server.py:1014 (direkt/dynamisch unklar); tests/test_server.py:378 (direkt/dynamisch unklar); tests/test_server.py:409 (direkt/dynamisch unklar); tests/test_server.py:8792 (direkt/dynamisch unklar); tests/test_server.py:927 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 16126 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 16138 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 16153 | `planning/` | P4 | offen | tests/test_server.py:418 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 16165 | `planning/` | P4 | offen | tests/test_server.py:688 (direkt/dynamisch unklar); tests/test_server.py:698 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 16195 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 16203 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 16210 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 16232 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 16239 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 16245 | `coach/proposals.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 16263 | `planning/` | P4 | offen | tests/test_server.py:442 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 16291 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 16300 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 16327 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 16353 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 16358 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 16364 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 16378 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 16385 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 16393 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 16400 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 16409 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 16416 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 16429 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 16452 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 16466 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 16480 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 16508 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 16524 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 16543 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 16563 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 16585 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 16601 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 16618 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 16653 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 16665 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 16680 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 16700 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 16726 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 16744 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 16752 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 16773 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 16800 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 16824 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 16851 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 16872 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:1007 (direkt/dynamisch unklar); tests/test_server.py:332 (direkt/dynamisch unklar); tests/test_server.py:364 (direkt/dynamisch unklar); tests/test_server.py:388 (direkt/dynamisch unklar); tests/test_server.py:421 (direkt/dynamisch unklar); tests/test_server.py:443 (direkt/dynamisch unklar); tests/test_server.py:468 (direkt/dynamisch unklar); tests/test_server.py:475 (direkt/dynamisch unklar); tests/test_server.py:515 (direkt/dynamisch unklar); tests/test_server.py:5151 (direkt/dynamisch unklar); tests/test_server.py:544 (direkt/dynamisch unklar); tests/test_server.py:550 (direkt/dynamisch unklar); tests/test_server.py:554 (direkt/dynamisch unklar); tests/test_server.py:5548 (direkt/dynamisch unklar); tests/test_server.py:5584 (direkt/dynamisch unklar); tests/test_server.py:5669 (direkt/dynamisch unklar); tests/test_server.py:571 (direkt/dynamisch unklar); tests/test_server.py:5743 (direkt/dynamisch unklar); tests/test_server.py:575 (direkt/dynamisch unklar); tests/test_server.py:5767 (direkt/dynamisch unklar); tests/test_server.py:5772 (direkt/dynamisch unklar); tests/test_server.py:5821 (direkt/dynamisch unklar); tests/test_server.py:5843 (direkt/dynamisch unklar); tests/test_server.py:712 (direkt/dynamisch unklar); tests/test_server.py:754 (direkt/dynamisch unklar); tests/test_server.py:783 (direkt/dynamisch unklar); tests/test_server.py:802 (direkt/dynamisch unklar); tests/test_server.py:831 (direkt/dynamisch unklar); tests/test_server.py:864 (direkt/dynamisch unklar); tests/test_server.py:884 (direkt/dynamisch unklar); tests/test_server.py:911 (direkt/dynamisch unklar); tests/test_server.py:937 (direkt/dynamisch unklar); tests/test_server.py:956 (direkt/dynamisch unklar); tests/test_server.py:982 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 16914 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 16918 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 16931 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8806 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 16943 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 16962 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 16978 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 16989 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 17011 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 17026 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 17044 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 17074 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 17080 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 17094 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 17104 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 17117 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 17130 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 17147 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 17160 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5881 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 17187 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 17204 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 17209 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 17218 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 17232 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 17245 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 17255 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 17268 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 17289 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 17312 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 17323 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 17332 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 17344 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 17358 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 17366 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 17381 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 17401 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 17425 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 17439 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 17450 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 17475 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 17491 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 17506 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 17563 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 17591 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 17621 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 17637 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 17657 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 17671 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 17683 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 17693 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 17744 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 17806 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 17810 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 17815 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 17833 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 17852 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 17862 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 17888 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 17926 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 17952 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 17977 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 18008 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 18048 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 18078 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 18098 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 18156 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 18160 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 18176 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 18192 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 18224 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 18268 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 18284 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 18303 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 18329 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 18406 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 18411 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 18420 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 18425 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 18452 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 18470 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 18499 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 18518 | `coach/service.py` | P7 | offen | tests/test_server.py:4494 (direkt/dynamisch unklar); tests/test_server.py:4509 (direkt/dynamisch unklar); tests/test_server.py:4523 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 18528 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 18543 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 18575 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 18590 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4596 (direkt/dynamisch unklar); tests/test_server.py:5534 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 18603 | `coach/authorization.py` | P7 | offen | tests/test_server.py:5922 (direkt/dynamisch unklar); tests/test_server.py:5925 (direkt/dynamisch unklar); tests/test_server.py:8446 (direkt/dynamisch unklar); tests/test_server.py:8449 (direkt/dynamisch unklar); tests/test_server.py:8450 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 18622 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 18635 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 18659 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 18675 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 18686 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 18701 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:247 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:285 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5951 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5975 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6007 (direkt/dynamisch unklar); tests/test_server.py:6070 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 18725 | `sync/` | P6 | offen | tests/test_server.py:4672 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 18766 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:254 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4671 (direkt/dynamisch unklar); tests/test_server.py:5949 (direkt/dynamisch unklar); tests/test_server.py:5968 (direkt/dynamisch unklar); tests/test_server.py:5995 (direkt/dynamisch unklar); tests/test_server.py:6024 (direkt/dynamisch unklar); tests/test_server.py:6048 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 18791 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 18817 | `coach/authorization.py` | P7 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 18827 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 18831 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 18839 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 18845 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 18855 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 18872 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 18903 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 18925 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 18940 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:148 (direkt/dynamisch unklar); tests/test_server.py:5952 (direkt/dynamisch unklar); tests/test_server.py:5976 (direkt/dynamisch unklar); tests/test_server.py:6030 (direkt/dynamisch unklar); tests/test_server.py:6073 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 18961 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 18976 | `coach/authorization.py` | P7 | offen | tests/test_server.py:240 (direkt/dynamisch unklar) |
| Funktion | `local_now` | 18987 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1200 (direkt/dynamisch unklar); tests/test_server.py:1584 (direkt/dynamisch unklar); tests/test_server.py:1600 (direkt/dynamisch unklar); tests/test_server.py:1601 (direkt/dynamisch unklar); tests/test_server.py:1622 (direkt/dynamisch unklar); tests/test_server.py:1640 (direkt/dynamisch unklar); tests/test_server.py:1659 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1672 (direkt/dynamisch unklar); tests/test_server.py:1709 (direkt/dynamisch unklar); tests/test_server.py:1717 (direkt/dynamisch unklar); tests/test_server.py:1757 (direkt/dynamisch unklar); tests/test_server.py:2571 (direkt/dynamisch unklar); tests/test_server.py:2683 (direkt/dynamisch unklar); tests/test_server.py:2748 (direkt/dynamisch unklar); tests/test_server.py:2758 (direkt/dynamisch unklar); tests/test_server.py:2936 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2996 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3026 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3035 (direkt/dynamisch unklar); tests/test_server.py:3523 (direkt/dynamisch unklar); tests/test_server.py:3542 (direkt/dynamisch unklar); tests/test_server.py:3574 (direkt/dynamisch unklar); tests/test_server.py:3599 (direkt/dynamisch unklar); tests/test_server.py:3689 (direkt/dynamisch unklar); tests/test_server.py:3690 (direkt/dynamisch unklar); tests/test_server.py:3734 (direkt/dynamisch unklar); tests/test_server.py:5291 (direkt/dynamisch unklar); tests/test_server.py:5340 (direkt/dynamisch unklar); tests/test_server.py:5357 (direkt/dynamisch unklar); tests/test_server.py:5379 (direkt/dynamisch unklar); tests/test_server.py:539 (direkt/dynamisch unklar); tests/test_server.py:5406 (direkt/dynamisch unklar); tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:6113 (direkt/dynamisch unklar); tests/test_server.py:7447 (direkt/dynamisch unklar); tests/test_server.py:7765 (direkt/dynamisch unklar); tests/test_server.py:8547 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 18996 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:153 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1941 (direkt/dynamisch unklar); tests/test_server.py:1942 (direkt/dynamisch unklar); tests/test_server.py:1943 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 19004 | `sync/daily.py` | P6 | offen | tests/test_server.py:1940 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 19012 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 19017 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 19028 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 19040 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4203 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 19043 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 19050 | `coach/authorization.py` | P7 | offen | tests/test_server.py:4201 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 19067 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 19073 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 19081 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 19093 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 19125 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 19146 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 19160 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 19173 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 19192 | `http_api/bootstrap.py` | P10 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 19226 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1767 (direkt/dynamisch unklar); tests/test_server.py:1781 (direkt/dynamisch unklar); tests/test_server.py:1824 (direkt/dynamisch unklar); tests/test_server.py:1906 (direkt/dynamisch unklar); tests/test_server.py:8587 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 19300 | `http_api/` | P10 | offen | tests/test_server.py:1214 (direkt/dynamisch unklar); tests/test_server.py:3028 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 19336 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 19341 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 19345 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:97 (direkt/dynamisch unklar); tests/test_server.py:1264 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 19352 | `http_api/` | P10 | offen | tests/test_server.py:1236 (direkt/dynamisch unklar); tests/test_server.py:1244 (direkt/dynamisch unklar); tests/test_server.py:1667 (direkt/dynamisch unklar); tests/test_server.py:1712 (direkt/dynamisch unklar); tests/test_server.py:2377 (direkt/dynamisch unklar); tests/test_server.py:3739 (direkt/dynamisch unklar); tests/test_server.py:7376 (direkt/dynamisch unklar); tests/test_server.py:8587 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 19464 | `diagnostics/report.py` | P9 | offen | tests/test_server.py:7910 (direkt/dynamisch unklar); tests/test_server.py:7962 (direkt/dynamisch unklar); tests/test_server.py:8076 (direkt/dynamisch unklar); tests/test_server.py:8107 (direkt/dynamisch unklar); tests/test_server.py:8358 (direkt/dynamisch unklar); tests/test_server.py:8394 (direkt/dynamisch unklar); tests/test_server.py:8643 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 19481 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 19497 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 19518 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 19532 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 19548 | `diagnostics/report.py` | P9 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 19557 | `diagnostics/report.py` | P9 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7825 (direkt/dynamisch unklar); tests/test_server.py:7827 (direkt/dynamisch unklar); tests/test_server.py:7828 (direkt/dynamisch unklar); tests/test_server.py:7875 (direkt/dynamisch unklar); tests/test_server.py:7938 (direkt/dynamisch unklar); tests/test_server.py:7953 (direkt/dynamisch unklar); tests/test_server.py:8760 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 19620 | `backup/` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1447 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 19670 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 19671 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 19695 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 19699 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 19710 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 19714 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 19724 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 19732 | `backup/` | P9 | offen | tests/test_audit_remediation.py:171 (direkt/dynamisch unklar); tests/test_server.py:1462 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 19871 | `db/manager.py` | P1 | offen | tests/test_server.py:6642 (direkt/dynamisch unklar); tests/test_server.py:6655 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 19874 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 19887 | `backup/` | P9 | offen | tests/test_audit_remediation.py:275 (direkt/dynamisch unklar); tests/test_server.py:6631 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 19896 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 19917 | `coach/morning.py` | P8 | offen | tests/test_server.py:1490 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 19928 | `backup/` | P9 | offen | tests/test_audit_remediation.py:277 (direkt/dynamisch unklar); tests/test_server.py:6632 (direkt/dynamisch unklar); tests/test_server.py:6648 (direkt/dynamisch unklar); tests/test_server.py:6661 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 19933 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 19942 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 19959 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 19971 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 19989 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 19996 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 20017 | `coach/morning.py` | P8 | offen | tests/test_server.py:1530 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1546 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4685 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5528 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8706 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 20030 | `coach/morning.py` | P8 | offen | tests/test_server.py:1539 (direkt/dynamisch unklar); tests/test_server.py:1543 (direkt/dynamisch unklar); tests/test_server.py:1549 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 20045 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 20052 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 20059 | `privacy.py` | P9 | offen | tests/test_server.py:1542 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 20074 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:102 (direkt/dynamisch unklar); tests/test_provider_review.py:116 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (direkt/dynamisch unklar); tests/test_provider_review.py:146 (direkt/dynamisch unklar); tests/test_provider_review.py:164 (direkt/dynamisch unklar); tests/test_server.py:1531 (direkt/dynamisch unklar); tests/test_server.py:1547 (direkt/dynamisch unklar); tests/test_server.py:8707 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 20103 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 20104 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 20105 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 20106 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 20107 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 20108 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1362 (direkt/dynamisch unklar); tests/test_server.py:1370 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 20109 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1367 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 20110 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 20111 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 20112 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 20113 | `http_api/auth.py` | P10 | offen | tests/test_server.py:8040 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 20116 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 20120 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:185 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8042 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 20145 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 20154 | `http_api/` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1326 (direkt/dynamisch unklar); tests/test_server.py:1355 (direkt/dynamisch unklar); tests/test_server.py:1358 (direkt/dynamisch unklar); tests/test_server.py:1407 (direkt/dynamisch unklar); tests/test_server.py:1414 (direkt/dynamisch unklar); tests/test_server.py:5937 (direkt/dynamisch unklar); tests/test_server.py:5941 (direkt/dynamisch unklar); tests/test_server.py:5956 (direkt/dynamisch unklar); tests/test_server.py:5960 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 20158 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 20168 | `http_api/` | P10 | offen | tests/test_server.py:1368 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 20183 | `performance/` | P3 | offen | tests/test_server.py:8005 (direkt/dynamisch unklar); tests/test_server.py:8015 (direkt/dynamisch unklar); tests/test_server.py:8023 (direkt/dynamisch unklar); tests/test_server.py:8030 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 20225 | `http_api/` | P10 | offen | tests/test_server.py:1332 (direkt/dynamisch unklar); tests/test_server.py:1335 (direkt/dynamisch unklar); tests/test_server.py:1356 (direkt/dynamisch unklar); tests/test_server.py:1389 (direkt/dynamisch unklar); tests/test_server.py:1426 (direkt/dynamisch unklar); tests/test_server.py:3435 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 20251 | `http_api/auth.py` | P10 | offen | tests/test_provider_review.py:188 (direkt/dynamisch unklar); tests/test_provider_review.py:191 (direkt/dynamisch unklar); tests/test_provider_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:3432 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 20270 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1425 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 20278 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 20290 | `http_api/` | P10 | offen | tests/test_server.py:1407 (direkt/dynamisch unklar); tests/test_server.py:1414 (direkt/dynamisch unklar); tests/test_server.py:3437 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 20296 | `http_api/` | P10 | offen | tests/test_server.py:1307 (direkt/dynamisch unklar); tests/test_server.py:1313 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 20309 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:193 (direkt/dynamisch unklar); tests/test_server.py:1510 (direkt/dynamisch unklar); tests/test_server.py:1805 (direkt/dynamisch unklar); tests/test_server.py:7553 (direkt/dynamisch unklar); tests/test_server.py:7563 (direkt/dynamisch unklar); tests/test_server.py:7569 (direkt/dynamisch unklar); tests/test_server.py:7579 (direkt/dynamisch unklar); tests/test_server.py:7591 (direkt/dynamisch unklar); tests/test_server.py:7596 (direkt/dynamisch unklar); tests/test_server.py:7600 (direkt/dynamisch unklar); tests/test_server.py:7603 (direkt/dynamisch unklar); tests/test_server.py:7609 (direkt/dynamisch unklar); tests/test_server.py:7619 (direkt/dynamisch unklar); tests/test_server.py:7626 (direkt/dynamisch unklar); tests/test_server.py:7633 (direkt/dynamisch unklar); tests/test_server.py:7640 (direkt/dynamisch unklar); tests/test_server.py:8459 (direkt/dynamisch unklar); tests/test_server.py:8482 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 20988 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:193 (direkt/dynamisch unklar); tests/test_server.py:220 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_loop` | 20993 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 21006 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 21010 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 21016 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 21022 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 21028 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 21036 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:154 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 21043 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 21057 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 21062 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 21074 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 21086 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 21091 | `sync/` | P6 | offen | tests/test_server.py:1021 (direkt/dynamisch unklar); tests/test_server.py:1030 (direkt/dynamisch unklar); tests/test_server.py:224 (Monkeypatch/getattr/sys.modules) |
| Funktion | `main` | 21099 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar); tests/test_server.py:227 (direkt/dynamisch unklar) |

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
| `backend/errors` | 20 |
| `backend/http_api/requests` | 3 |
| `backend/http_api/responses` | 4 |
| `backend/planning/adaptive` | 2 |
| `backend/planning/changes` | 3 |
| `backend/planning/repository` | 2 |
| `backend/planning/service` | 3 |
| `backend/providers/calendar` | 4 |
| `backend/providers/garmin` | 2 |
| `backend/providers/gemini` | 2 |
| `backend/providers/http` | 2 |
| `backend/providers/intervals` | 3 |
| `backend/providers/openai` | 2 |
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
| `backup/` | 20 |
| `calendar/` | 34 |
| `coach/` | 27 |
| `coach/authorization.py` | 69 |
| `coach/context.py` | 51 |
| `coach/conversation.py` | 8 |
| `coach/dialogue.py` | 18 |
| `coach/jobs.py` | 6 |
| `coach/morning.py` | 8 |
| `coach/proposals.py` | 36 |
| `coach/service.py` | 6 |
| `coach/streams.py` | 3 |
| `coach/tool_execution.py` | 8 |
| `config.py` | 6 |
| `db/` | 20 |
| `db/bootstrap.py` | 1 |
| `db/manager.py` | 6 |
| `diagnostics/report.py` | 7 |
| `history/` | 34 |
| `http_api/` | 43 |
| `http_api/auth.py` | 16 |
| `http_api/bootstrap.py` | 1 |
| `http_api/pagination.py` | 9 |
| `observability.py` | 20 |
| `performance/` | 56 |
| `performance/activity_validation.py` | 4 |
| `planning/` | 250 |
| `planning/calendar.py` | 1 |
| `planning/competitions.py` | 78 |
| `privacy.py` | 4 |
| `providers/` | 86 |
| `providers/calendar.py` | 71 |
| `providers/http.py` | 16 |
| `providers/intervals_client.py` | 1 |
| `providers/workout_text.py` | 17 |
| `runtime/` | 2 |
| `server.py / Composition Root` | 56 |
| `settings.py` | 7 |
| `sync/` | 173 |
| `sync/competitions.py` | 1 |
| `sync/daily.py` | 1 |
| `sync/freshness.py` | 1 |
| `sync/garmin.py` | 85 |
| `sync/jobs.py` | 1 |
| `sync/refresh.py` | 4 |
| `sync/scheduler.py` | 13 |
| `weather/` | 55 |

## Grenzen und offene Unsicherheiten

- AST-Aufrufauflösung erfasst nur direkte lokale Aufrufe; `getattr`, `globals()`, `sys.modules`, dekoratorbasierte Registrierung und Callback-Injektion benötigen eine manuelle Nachprüfung.
- Ein Name kann in mehreren Kategorien mit derselben Schreibweise vorkommen; Referenzzählungen sind deshalb namensbasiert und zeigen Ortsangaben, nicht vermeintliche Laufzeitidentität.
- Die Tabelle enthält bewusst auch Importbindungen, damit Rückimporte, spätere Re-Exports und der endgültige Composition-Root-Inhalt überprüfbar bleiben.
- Offene Zielzuordnungen müssen vor dem jeweiligen Umzug fachlich entschieden werden; sie gelten nicht als erledigt.
