# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `43241169b250e7d6e65f600852b5be4f8517f1dc50cfd90a7bfeb55d4cbd8590`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 19.869 physische Zeilen
- Inventareinträge: 1.536
- Definitionen (Funktionen/Klassen): 1.090
- Globale Bindungen einschließlich Imports: 257 Zuweisungen. 189 Imports
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
| P1 | 21 | 41 | 142 |
| P2 | 69 | 8 | 0 |
| P3 | 189 | 27 | 0 |
| P4 | 285 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 228 | 43 | 0 |
| P7 | 205 | 39 | 0 |
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
- `tests/test_server.py:1034: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=True) as active, patch.object(`
- `tests/test_server.py:1043: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=False), patch.object(`
- `tests/test_server.py:1045: ), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:1225: with patch.object(server, "_fetch_weather_forecast", side_effect=[old, new]) as fetch:`
- `tests/test_server.py:1251: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1279: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1293: with patch.object(server, "_fetch_weather_forecast", return_value=forecast) as fetch:`
- `tests/test_server.py:1312: with patch.object(server, "_fetch_weather_forecast", side_effect=[server.AppError(503, "upstream"), forecast]) as fetch:`
- `tests/test_server.py:1328: with patch.object(server, "CONFIG", replace(server.CONFIG, secure_cookies=True)):`
- `tests/test_server.py:1546: with patch.object(server, "delete_remote_conversation", side_effect=server.AppError(503, "upstream")):`
- `tests/test_server.py:1562: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:1579: with patch.object(server, "_fetch_weather_forecast", return_value=forecast), patch.object(`
- `tests/test_server.py:1595: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("coach context must not refresh weather")):`
- `tests/test_server.py:1605: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1622: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1632: with patch.object(server, "latest_replan_preview", return_value={"status": "preview", "changes": [{"date": "2026-09-01"}]}):`
- `tests/test_server.py:1656: self.assertEqual(getattr(server.local_now().tzinfo, "key", None), "UTC")`
- `tests/test_server.py:1675: with patch.object(server, "local_now", return_value=fixed_now):`
- `tests/test_server.py:1690: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:1809: with patch.object(server, "http_json", side_effect=AssertionError("network")), patch.object(server, "external_call", side_effect=AssertionError("network")):`
- `tests/test_server.py:1852: with patch.object(server.sqlite3, "connect", wraps=sqlite3.connect) as connect:`
- `tests/test_server.py:191: with patch.object(server, "CONFIG", config), patch.object(server, "DATA_DIR", Path(temporary)), patch.object(`
- `tests/test_server.py:1930: with patch.object(server, "state_versions", return_value={"activities": "v1"}):`
- `tests/test_server.py:220: with patch.object(server, "resume_interrupted_sync_jobs") as sync_recovery, patch.object(`
- `tests/test_server.py:230: with patch.object(server.observability, "configure_logging"), patch.object(`
- `tests/test_server.py:232: ), patch.object(server, "initialise_database", side_effect=lambda: order.append("schema")), patch.object(`
- `tests/test_server.py:236: ), patch.object(server, "CoachHTTPServer", return_value=http_server), patch.object(`
- `tests/test_server.py:240: ), patch.object(server, "enqueue_startup_sync_jobs"), patch.object(`
- `tests/test_server.py:242: ), patch.object(server.threading, "Thread"):`
- `tests/test_server.py:2473: with patch.object(server, "CONFIG", replace(server.CONFIG, calendar_ical_url="https://calendar.example/feed.ics")), patch.object(`
- `tests/test_server.py:250: with patch.object(server, "resume_interrupted_sync_jobs") as sync_recovery, patch.object(`
- `tests/test_server.py:2513: with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", return_value=payload) as fetch, patch.object(`
- `tests/test_server.py:252: ) as coach_recovery, patch.object(server.threading, "Thread") as thread, patch.object(`
- `tests/test_server.py:2543: with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", return_value=payload):`
- `tests/test_server.py:254: ), patch.object(server, "COACH_JOB_WORKER", None):`
- `tests/test_server.py:2558: with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", side_effect=server.AppError(502, "upstream unavailable")):`
- `tests/test_server.py:2619: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:2714: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=-1)):`
- `tests/test_server.py:271: with patch.object(server, "_execute_sync_job", return_value={"status": "ok"}):`
- `tests/test_server.py:2723: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=30)):`
- `tests/test_server.py:2733: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:2780: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)):`
- `tests/test_server.py:282: with patch.object(server, "_execute_sync_job", side_effect=server.AppError(503, provider_detail, reason="network_error")):`
- `tests/test_server.py:2840: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 20, 0)):`
- `tests/test_server.py:2867: patch.object(server, "latest_snapshot", return_value=snapshot),`
- `tests/test_server.py:2868: patch.object(server, "list_dated_local_planned_workouts", return_value=planned),`
- `tests/test_server.py:2869: patch.object(server, "weather_state", return_value={"days": []}),`
- `tests/test_server.py:2870: patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)),`
- `tests/test_server.py:293: with patch.object(server, "sync_garmin") as sync:`
- `tests/test_server.py:315: with patch.object(server, "_execute_sync_job", return_value=result):`
- `tests/test_server.py:325: with patch.object(server, "_repair_local_planned_unit_calendar_entry", return_value=None) as repair:`
- `tests/test_server.py:3274: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:3769: with patch.object(server.IntervalsClient, "get_workout_library", return_value=[]), \`
- `tests/test_server.py:3770: patch.object(server.IntervalsClient, "create_library_workouts", return_value=[{"id": "synthetic-remote", "type": "Ride"}]) as create, \`
- `tests/test_server.py:3771: patch.object(server.IntervalsClient, "update_library_workout", return_value={"id": "synthetic-remote", **parsed_workout_fixture()}) as update:`
- `tests/test_server.py:3789: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=[`
- `tests/test_server.py:3814: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:3832: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:3834: ), patch.object(server.IntervalsClient, "create_library_workouts") as create:`
- `tests/test_server.py:403: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-plan-push"}) as enqueue:`
- `tests/test_server.py:4041: with patch.object(server, "garmin_fixture_path", return_value="fixture.json"), \`
- `tests/test_server.py:4042: patch.object(server, "sync_garmin") as sync_garmin, \`
- `tests/test_server.py:4043: patch.object(server, "garmin_sleep_ready_for_checkin", return_value=False), \`
- `tests/test_server.py:4088: with patch.object(server, "CONFIG", config), patch.object(server, "Garmin", FakeGarmin):`
- `tests/test_server.py:4257: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4301: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=fake_urlopen):`
- `tests/test_server.py:4326: patch.object(server, "CONFIG", config),`
- `tests/test_server.py:4327: patch.object(server, "MAX_EXTERNAL_RESPONSE_BYTES", 1),`
- `tests/test_server.py:4328: patch.object(server, "urlopen", return_value=StreamResponse()),`
- `tests/test_server.py:4349: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:434: with patch.object(server, "_mark_local_planning_authoritative"), patch.object(`
- `tests/test_server.py:4473: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value=response):`
- `tests/test_server.py:4488: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4499: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4513: with patch.object(server, "CONFIG", replace(server.CONFIG, gemini_api_key=key)):`
- `tests/test_server.py:4519: with patch.object(server, "CONFIG", config), patch.object(server, "gemini_responses_request", return_value={"output_text": "ok"}) as gemini, patch.object(server, "openai_request") as openai:`
- `tests/test_server.py:4532: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4552: with patch.object(server, "CONFIG", config), patch.object(server, "delete_remote_conversation", return_value=True) as delete:`
- `tests/test_server.py:4570: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:458: with patch.object(server, "_enqueue_coach_plan_push") as enqueue, self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:4619: with patch.object(server, "urlopen", side_effect=blocked_urlopen):`
- `tests/test_server.py:4650: with patch.object(server, "urlopen", return_value=response):`
- `tests/test_server.py:4683: with patch.object(server, "urlopen", side_effect=return_cancelled_response):`
- `tests/test_server.py:4705: with patch.object(server, "urlopen", return_value=EmptyResponse()):`
- `tests/test_server.py:4715: patch.object(server, "MAX_EXTERNAL_RESPONSE_BYTES", 3),`
- `tests/test_server.py:4716: patch.object(server, "urlopen", return_value=OversizedResponse()),`
- `tests/test_server.py:4734: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")), patch.object(`
- `tests/test_server.py:4759: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4783: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:4790: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:490: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-competition"}) as enqueue:`
- `tests/test_server.py:4962: with patch.object(server, "calendar_conflicts", return_value=[{"name": "Occupied"}]) as conflicts:`
- `tests/test_server.py:5276: with patch.object(server, "structured_athlete_context", return_value={"source_policy": {"untrusted": "x" * 200_000}}):`
- `tests/test_server.py:5383: with patch.object(server, "openai_request", side_effect=fake_openai):`
- `tests/test_server.py:5389: with patch.object(server, "http_json", return_value=response), patch.object(`
- `tests/test_server.py:5405: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:5519: with patch.object(server, "CHANGE_HISTORY_MAX_ROWS", 3), self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:5656: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 2):`
- `tests/test_server.py:5670: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 1):`
- `tests/test_server.py:5756: with patch.object(server, "save_workout_library_entries", side_effect=RuntimeError("creation failed")):`
- `tests/test_server.py:5758: server._apply_training_patch(arguments, {`
- `tests/test_server.py:5775: with patch.object(server, "responses_request", side_effect=create), patch.object(`
- `tests/test_server.py:5780: ) as retrieve, patch.object(server, "OPENAI_BACKGROUND_POLL_SECONDS", 0), patch.object(`
- `tests/test_server.py:5797: with patch.object(server, "responses_request", return_value=initial), patch.object(`
- `tests/test_server.py:5801: ) as poll, patch.object(server.provider_state_service(), "record_usage"):`
- `tests/test_server.py:5845: with patch.object(server, "chat_with_coach", side_effect=lambda *args, **kwargs: seen.update(kwargs) or {}):`
- `tests/test_server.py:5869: with patch.object(server, "chat_with_coach", side_effect=complete_chat):`
- `tests/test_server.py:586: with patch.object(server, "enqueue_sync_job", side_effect=[{"id": "job-performance"}, {"id": "job-competition"}]) as enqueue:`
- `tests/test_server.py:5898: with patch.object(server, "responses_stream_request", side_effect=streamed_response) as streamed, patch.object(`
- `tests/test_server.py:5923: ), patch.object(server, "_restore_coach_session_csrf_hash", return_value="csrf-background-requeue"):`
- `tests/test_server.py:5964: with patch.object(server, "chat_with_coach", side_effect=capture_phase), patch.object(`
- `tests/test_server.py:6000: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6002: ) as fetch_snapshot, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:6013: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6029: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6031: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6042: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6044: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6060: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6073: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:609: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:6101: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6103: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=remote) as get_library:`
- `tests/test_server.py:6141: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6143: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6163: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6167: ) as import_units, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6185: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6187: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[{`
- `tests/test_server.py:6204: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6208: ) as library_sync, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6223: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:622: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:6277: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6286: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6305: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6314: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6323: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6331: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:633: with patch.object(server, "sync_intervals", return_value={"status": "ok"}) as sync, patch.object(`
- `tests/test_server.py:6348: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6392: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6406: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_server.py:6424: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:645: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6469: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6471: ), patch.object(server, "_sync_selected_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6494: with patch.object(server, "IntervalsClient", FailingIntervalsClient), patch.object(`
- `tests/test_server.py:6504: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6517: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", db_path), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6562: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:6583: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6592: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir), patch.dict(`
- `tests/test_server.py:6612: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir):`
- `tests/test_server.py:664: with patch.object(server, "CONFIG", config), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:673: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6759: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:675: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:677: ) as enqueue, patch.object(server, "_wait_for_performance_refresh") as wait:`
- `tests/test_server.py:6791: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6829: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6861: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:686: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6877: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:688: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:6916: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6949: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6976: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7259: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:7260: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:7389: with patch.object(server, "http_json", side_effect=[`
- `tests/test_server.py:7472: with patch.object(server.LOGGER, "info") as logger:`
- `tests/test_server.py:7649: with patch.object(server.IntervalsClient, "delete_activity", return_value=None) as delete:`
- `tests/test_server.py:7699: with patch.object(server, "get_kv", side_effect=get_kv_after_read):`
- `tests/test_server.py:7731: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7753: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7781: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7800: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7817: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7851: with patch.object(server, "urlopen", side_effect=server.URLError("offline")):`
- `tests/test_server.py:7868: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7882: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7892: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7908: with patch.object(server, "database", side_effect=OSError("database unavailable")):`
- `tests/test_server.py:7916: with patch.object(server.tempfile, "NamedTemporaryFile", side_effect=OSError("read-only")):`
- `tests/test_server.py:7935: with patch.object(server.time, "monotonic", return_value=20 * 60):`
- `tests/test_server.py:7964: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:7966: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[]):`
- `tests/test_server.py:7993: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8029: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8056: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8077: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8108: with patch.object(server, "openai_request", side_effect=fake_request), patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8127: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8169: with patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:8198: patch.object(server, "MAX_EXTERNAL_RESPONSE_BYTES", 1),`
- `tests/test_server.py:8199: patch.object(server, "urlopen", return_value=OversizedResponse()),`
- `tests/test_server.py:8216: with patch.object(server, "urlopen") as urlopen:`
- `tests/test_server.py:8243: with patch.object(server, "urlopen", return_value=TimeoutResponse()):`
- `tests/test_server.py:8256: with patch.object(server.LOGGER, "log") as log:`
- `tests/test_server.py:8267: with patch.object(server.LOGGER, "log") as log:`
- `tests/test_server.py:8296: with patch.object(server, "urlopen", return_value=DisconnectResponse()):`
- `tests/test_server.py:8307: with patch.object(server, "openai_stream_request", side_effect=responses) as request, patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8354: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), \`
- `tests/test_server.py:8355: patch.object(server, "unregister_chat_stream") as unregister, \`
- `tests/test_server.py:8356: patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8381: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), patch.object(`
- `tests/test_server.py:8383: ) as unregister, patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8435: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value={"status": "completed"}) as request:`
- `tests/test_server.py:8486: with patch.object(server, "DB_LOCK", database_lock), patch.object(`
- `tests/test_server.py:8518: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8605: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:8619: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8630: with patch.object(server, "CONFIG", replace(config, intervals_api_key="")):`
- `tests/test_server.py:8687: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:926: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-changed"}) as enqueue:`
- `tests/test_server.py:952: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-large-changed"}) as enqueue:`
- `tests/test_server.py:997: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-all"}) as enqueue:`
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
| `operation_trigger` | 965 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 971 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 980 | – | `Any` | – | – |
| `log_operation_event` | 990 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1017 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1038 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count`, `runtime_maintenance`, `wraps` | – | – |
| `database_manager` | 1081 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `PROVIDER_STATE_SERVICE` | – |
| `provider_state_service` | 1109 | `database_manager`, `local_now` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `LOGGER`, `PROVIDER_STATE_SERVICE`, `database_manager`, `local_now`, `provider_state`, `utc_now` | `PROVIDER_STATE_SERVICE` | – |
| `database` | 1126 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1132 | `database`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `KEY_VALUE_REPOSITORY`, `PROVIDER_RESYNC_KEYS`, `database`, `datetime`, `initialize_application_database`, `json`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_cleanup` | 1144 | – | `Any`, `cleanup_refresh_history`, `datetime`, `sync_freshness`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1152 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `runtime_events`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1164 | `_provider_refresh_cleanup`, `database`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `runtime_events`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1198 | – | – | – | – |
| `_sync_job_error_class` | 1213 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1227 | – | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1236 | – | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1250 | `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1263 | `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1273 | `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1282 | – | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1292 | – | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1299 | `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1324 | `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1333 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1339 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1344 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1367 | – | `AppError` | – | – |
| `_pending_performance_job_id` | 1375 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1384 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1402 | `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1429 | – | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1438 | – | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1445 | – | `Any` | – | – |
| `_insert_sync_job` | 1455 | – | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 1480 | – | `Any`, `runtime_events` | – | – |
| `enqueue_sync_job` | 1494 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `runtime_maintenance`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 1521 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 1541 | `database`, `utc_now` | `Any`, `DB_LOCK`, `database`, `runtime_maintenance`, `utc_now` | – | – |
| `_sync_job_update` | 1562 | `database`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `runtime_events`, `utc_now` | – | – |
| `_sync_job_item_results` | 1600 | – | `Any` | – | – |
| `_sync_job_result_target` | 1606 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 1617 | `_sync_job_result_target` | `Any`, `REDACTOR`, `_sync_job_result_target` | – | – |
| `_sync_job_completion_snapshot` | 1637 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 1652 | – | `runtime_events` | – | – |
| `_sync_job_update_from_result` | 1669 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 1682 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 1691 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 1698 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 1715 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 1727 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 1739 | `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 1762 | – | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 1771 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 1791 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 1811 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | `Any`, `LOGGER`, `REDACTOR`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update` | – | – |
| `_run_claimed_sync_job` | 1829 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `runtime_maintenance` | – | – |
| `_sync_job_worker_loop` | 1839 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job`, `runtime_maintenance` | – | – |
| `start_sync_job_worker` | 1854 | – | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 1865 | `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_current_provider_freshness` | 1888 | `_garmin_core_error_entries`, `database`, `get_profile` | `Any`, `CONFIG`, `DB_LOCK`, `Path`, `_garmin_core_error_entries`, `database`, `datetime`, `get_kv`, `get_profile`, `sync_freshness`, `timezone` | – | – |
| `_audit_projection_fields` | 1902 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 1916 | – | `Any`, `json` | – | – |
| `_audit_projection` | 1927 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 1951 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 1956 | – | `Any` | – | – |
| `_cleanup_change_history` | 1968 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 1978 | – | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 1995 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2034 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2066 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2077 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2089 | – | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2103 | – | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2119 | `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2157 | `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2177 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2187 | `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2212 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2233 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2243 | `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2252 | `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2278 | `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2294 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2323 | `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2338 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |
| `sync_period` | 2376 | `get_kv` | `ALL_SYNC_DAYS`, `SYNC_PERIOD_DEFAULTS`, `get_kv` | – | – |
| `set_sync_period` | 2387 | `set_kv` | `ALL_SYNC_DAYS`, `Any`, `AppError`, `set_kv` | – | – |
| `sync_date_windows` | 2399 | `local_now` | `ALL_SYNC_DAYS`, `SYNC_CHUNK_DAYS`, `SYNC_EARLIEST_DATE`, `date`, `local_now`, `split_date_windows` | – | – |
| `provider_sync_cursor` | 2410 | `database` | `Any`, `DB_LOCK`, `database`, `read_cursor` | – | – |
| `update_provider_sync_cursor` | 2415 | `database`, `utc_now` | `DB_LOCK`, `database`, `utc_now`, `write_cursor` | – | – |
| `set_kv` | 2421 | `database`, `set_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `set_kv`, `sqlite3` | – | – |
| `_coach_error_metadata` | 2433 | – | `Any`, `Path`, `ROOT`, `observability` | – | – |
| `_safe_response_headers` | 2448 | – | `Any`, `REDACTOR` | – | – |
| `garmin_snapshot` | 2465 | `get_kv` | `Any`, `get_kv`, `json` | – | – |
| `garmin_configured` | 2473 | – | `CONFIG`, `Garmin` | – | – |
| `garmin_fixture_path` | 2477 | – | `CONFIG`, `Path`, `ROOT` | – | – |
| `activity_datetime` | 2485 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `activity_kind` | 2497 | – | `Any` | – | – |
| `_cycling_event_candidates` | 2512 | `activity_kind` | `Any`, `activity_kind` | – | – |
| `_cycling_event_interval` | 2522 | `activity_datetime`, `as_number` | `Any`, `activity_datetime`, `as_number`, `datetime`, `timedelta` | – | – |
| `_cycling_intervals_share_group` | 2533 | – | `datetime` | – | – |
| `_cycling_event_edges` | 2542 | `_cycling_intervals_share_group` | `_cycling_intervals_share_group`, `datetime` | – | – |
| `_cycling_event_group` | 2557 | – | `Any` | – | – |
| `parallel_cycling_event_groups` | 2571 | `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | `Any`, `_cycling_event_candidates`, `_cycling_event_edges`, `_cycling_event_group`, `_cycling_event_interval` | – | – |
| `_garmin_duplicate_measurements` | 2583 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_activity_matches` | 2599 | `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | `Any`, `_garmin_duplicate_measurements`, `activity_datetime`, `activity_kind` | – | – |
| `garmin_activity_duplicates_intervals` | 2614 | `_garmin_activity_matches` | `Any`, `_garmin_activity_matches` | – | – |
| `filter_garmin_activities` | 2621 | `garmin_activity_duplicates_intervals` | `Any`, `garmin_activity_duplicates_intervals` | – | – |
| `intervals_activity_device_source` | 2628 | – | `Any` | – | – |
| `intervals_cycling_activities_match` | 2643 | `activity_datetime`, `activity_kind`, `as_number`, `first_present` | `Any`, `activity_datetime`, `activity_kind`, `as_number`, `first_present` | – | – |
| `_latest_activity_id` | 2666 | `activity_datetime`, `first_present` | `Any`, `activity_datetime`, `first_present` | – | – |
| `_wahoo_garmin_pairs` | 2679 | `activity_datetime`, `activity_kind`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | `Any`, `activity_datetime`, `activity_kind`, `datetime`, `first_present`, `intervals_activity_device_source`, `intervals_cycling_activities_match` | – | – |
| `_wahoo_garmin_duplicate_view` | 2697 | `first_present` | `Any`, `datetime`, `first_present` | – | – |
| `latest_wahoo_garmin_duplicate` | 2715 | `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | `Any`, `_latest_activity_id`, `_wahoo_garmin_duplicate_view`, `_wahoo_garmin_pairs`, `latest_snapshot` | – | – |
| `garmin_activity_max_hr` | 2730 | `activity_kind`, `as_number`, `first_present` | `Any`, `activity_kind`, `as_number`, `first_present` | – | – |
| `merge_garmin_max_hr` | 2745 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_key` | 2773 | – | `Any` | – | – |
| `_garmin_numeric` | 2777 | `as_number`, `first_present` | `Any`, `as_number`, `first_present` | – | – |
| `_garmin_vo2_value` | 2783 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_colon_duration_seconds` | 2788 | – | – | – | – |
| `_garmin_duration_seconds` | 2797 | `_garmin_colon_duration_seconds`, `as_number`, `first_present` | `Any`, `_garmin_colon_duration_seconds`, `as_number`, `first_present` | – | – |
| `_garmin_race_slot` | 2816 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_race_time` | 2829 | `_garmin_duration_seconds` | `Any`, `_garmin_duration_seconds` | – | – |
| `_garmin_weight_kg` | 2833 | `_garmin_key`, `as_number`, `first_present` | `Any`, `_garmin_key`, `as_number`, `first_present` | – | – |
| `_garmin_record_date` | 2851 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_collect_garmin_weight_records` | 2865 | `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | `Any`, `_collect_garmin_weight_records`, `_garmin_key`, `_garmin_record_date`, `_garmin_weight_kg`, `first_present` | – | – |
| `garmin_weight_records` | 2881 | `_collect_garmin_weight_records` | `Any`, `_collect_garmin_weight_records` | – | – |
| `garmin_weight_metric` | 2887 | `garmin_weight_records`, `metric` | `Any`, `GARMIN_PERFORMANCE_SOURCE`, `garmin_weight_records`, `metric` | – | – |
| `garmin_weight_average` | 2895 | `garmin_weight_records` | `Any`, `date`, `garmin_weight_records`, `timedelta` | – | – |
| `_collect_garmin_numeric_values` | 2908 | `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | `Any`, `_collect_garmin_numeric_values`, `_garmin_key`, `_garmin_numeric` | – | – |
| `_garmin_last_numeric` | 2921 | `_collect_garmin_numeric_values` | `Any`, `_collect_garmin_numeric_values` | – | – |
| `_garmin_last_value` | 2928 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `_garmin_bounded_metric` | 2946 | `as_number` | `Any`, `as_number` | – | – |
| `_garmin_pace_seconds` | 2951 | `_garmin_numeric` | `Any`, `_garmin_numeric` | – | – |
| `_garmin_mapping_nodes` | 2977 | `_garmin_mapping_nodes` | `Any`, `Iterator`, `_garmin_mapping_nodes` | – | – |
| `_garmin_sport_category` | 2987 | `_garmin_key` | `Any`, `_garmin_key` | – | – |
| `garmin_profile_max_hr` | 2996 | `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | `Any`, `_garmin_mapping_nodes`, `_garmin_sport_category`, `as_number`, `first_present` | – | – |

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
| Importbindung | `queue` | 17 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:8350 (direkt/dynamisch unklar); tests/test_server.py:8376 (direkt/dynamisch unklar) |
| Importbindung | `re` | 18 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `secrets` | 19 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_coach_language_recovery.py:42 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:69 (direkt/dynamisch unklar) |
| Importbindung | `shutil` | 20 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `socket` | 21 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `sqlite3` | 22 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1082 (direkt/dynamisch unklar); tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:1852 (direkt/dynamisch unklar) |
| Importbindung | `threading` | 23 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_diagnostic_followups.py:170 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:37 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:56 (direkt/dynamisch unklar); tests/test_server.py:242 (direkt/dynamisch unklar); tests/test_server.py:252 (direkt/dynamisch unklar) |
| Importbindung | `tempfile` | 24 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7916 (direkt/dynamisch unklar) |
| Importbindung | `time` | 25 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/support.py:130 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:108 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:41 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:95 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:38 (direkt/dynamisch unklar); tests/test_coach_review.py:257 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:257 (direkt/dynamisch unklar); tests/test_server.py:1371 (direkt/dynamisch unklar); tests/test_server.py:1384 (direkt/dynamisch unklar); tests/test_server.py:4123 (direkt/dynamisch unklar); tests/test_server.py:5798 (direkt/dynamisch unklar); tests/test_server.py:7935 (direkt/dynamisch unklar); tests/test_server.py:8108 (direkt/dynamisch unklar); tests/test_server.py:8259 (direkt/dynamisch unklar); tests/test_server.py:8270 (direkt/dynamisch unklar); tests/test_server.py:8307 (direkt/dynamisch unklar) |
| Importbindung | `uuid` | 26 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `zipfile` | 27 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ContextVar` | 28 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `nullcontext` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `contextmanager` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `dataclass` | 30 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `date` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1632 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `datetime` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `timedelta` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:555 (direkt/dynamisch unklar) |
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
| Importbindung | `HTTPError` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4563 (direkt/dynamisch unklar); tests/test_server.py:7779 (direkt/dynamisch unklar); tests/test_server.py:7810 (direkt/dynamisch unklar); tests/test_server.py:7861 (direkt/dynamisch unklar); tests/test_server.py:8046 (direkt/dynamisch unklar); tests/test_server.py:8070 (direkt/dynamisch unklar); tests/test_server.py:8085 (direkt/dynamisch unklar); tests/test_server.py:8122 (direkt/dynamisch unklar) |
| Importbindung | `URLError` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7851 (direkt/dynamisch unklar) |
| Importbindung | `parse_qs` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `quote` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlencode` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlparse` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Request` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlopen` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4301 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4570 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4619 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4650 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4683 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4705 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4716 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4783 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7781 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7800 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7817 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7851 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7868 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7993 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8029 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8056 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8077 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8127 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8169 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8199 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8216 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8243 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8296 (Monkeypatch/getattr/sys.modules) |
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
| Importbindung | `AppError` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:161 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_server.py:1022 (direkt/dynamisch unklar); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:1422 (direkt/dynamisch unklar); tests/test_server.py:1429 (direkt/dynamisch unklar); tests/test_server.py:1546 (direkt/dynamisch unklar); tests/test_server.py:1647 (direkt/dynamisch unklar); tests/test_server.py:1651 (direkt/dynamisch unklar); tests/test_server.py:1677 (direkt/dynamisch unklar); tests/test_server.py:1827 (direkt/dynamisch unklar); tests/test_server.py:2078 (direkt/dynamisch unklar); tests/test_server.py:2084 (direkt/dynamisch unklar); tests/test_server.py:2095 (direkt/dynamisch unklar); tests/test_server.py:2099 (direkt/dynamisch unklar); tests/test_server.py:2100 (direkt/dynamisch unklar); tests/test_server.py:2102 (direkt/dynamisch unklar); tests/test_server.py:2107 (direkt/dynamisch unklar); tests/test_server.py:2110 (direkt/dynamisch unklar); tests/test_server.py:2115 (direkt/dynamisch unklar); tests/test_server.py:2118 (direkt/dynamisch unklar); tests/test_server.py:2123 (direkt/dynamisch unklar); tests/test_server.py:2126 (direkt/dynamisch unklar); tests/test_server.py:2133 (direkt/dynamisch unklar); tests/test_server.py:2158 (direkt/dynamisch unklar); tests/test_server.py:2414 (direkt/dynamisch unklar); tests/test_server.py:2476 (direkt/dynamisch unklar); tests/test_server.py:2558 (direkt/dynamisch unklar); tests/test_server.py:2559 (direkt/dynamisch unklar); tests/test_server.py:282 (direkt/dynamisch unklar); tests/test_server.py:294 (direkt/dynamisch unklar); tests/test_server.py:3100 (direkt/dynamisch unklar); tests/test_server.py:3137 (direkt/dynamisch unklar); tests/test_server.py:347 (direkt/dynamisch unklar); tests/test_server.py:3571 (direkt/dynamisch unklar); tests/test_server.py:3671 (direkt/dynamisch unklar); tests/test_server.py:3687 (direkt/dynamisch unklar); tests/test_server.py:3726 (direkt/dynamisch unklar); tests/test_server.py:3753 (direkt/dynamisch unklar); tests/test_server.py:3761 (direkt/dynamisch unklar); tests/test_server.py:3772 (direkt/dynamisch unklar); tests/test_server.py:379 (direkt/dynamisch unklar); tests/test_server.py:3793 (direkt/dynamisch unklar); tests/test_server.py:3805 (direkt/dynamisch unklar); tests/test_server.py:3809 (direkt/dynamisch unklar); tests/test_server.py:3997 (direkt/dynamisch unklar); tests/test_server.py:4158 (direkt/dynamisch unklar); tests/test_server.py:4219 (direkt/dynamisch unklar); tests/test_server.py:4329 (direkt/dynamisch unklar); tests/test_server.py:4339 (direkt/dynamisch unklar); tests/test_server.py:4352 (direkt/dynamisch unklar); tests/test_server.py:4362 (direkt/dynamisch unklar); tests/test_server.py:4377 (direkt/dynamisch unklar); tests/test_server.py:4391 (direkt/dynamisch unklar); tests/test_server.py:4474 (direkt/dynamisch unklar); tests/test_server.py:4558 (direkt/dynamisch unklar); tests/test_server.py:4560 (direkt/dynamisch unklar); tests/test_server.py:4571 (direkt/dynamisch unklar); tests/test_server.py:458 (direkt/dynamisch unklar); tests/test_server.py:4616 (direkt/dynamisch unklar); tests/test_server.py:4684 (direkt/dynamisch unklar); tests/test_server.py:4717 (direkt/dynamisch unklar); tests/test_server.py:4791 (direkt/dynamisch unklar); tests/test_server.py:4793 (direkt/dynamisch unklar); tests/test_server.py:4817 (direkt/dynamisch unklar); tests/test_server.py:4892 (direkt/dynamisch unklar); tests/test_server.py:4963 (direkt/dynamisch unklar); tests/test_server.py:5128 (direkt/dynamisch unklar); tests/test_server.py:5145 (direkt/dynamisch unklar); tests/test_server.py:5351 (direkt/dynamisch unklar); tests/test_server.py:5358 (direkt/dynamisch unklar); tests/test_server.py:5368 (direkt/dynamisch unklar); tests/test_server.py:5370 (direkt/dynamisch unklar); tests/test_server.py:547 (direkt/dynamisch unklar); tests/test_server.py:5519 (direkt/dynamisch unklar); tests/test_server.py:5632 (direkt/dynamisch unklar); tests/test_server.py:5684 (direkt/dynamisch unklar); tests/test_server.py:5697 (direkt/dynamisch unklar); tests/test_server.py:5922 (direkt/dynamisch unklar); tests/test_server.py:6028 (direkt/dynamisch unklar); tests/test_server.py:6032 (direkt/dynamisch unklar); tests/test_server.py:6041 (direkt/dynamisch unklar); tests/test_server.py:6045 (direkt/dynamisch unklar); tests/test_server.py:6063 (direkt/dynamisch unklar); tests/test_server.py:6074 (direkt/dynamisch unklar); tests/test_server.py:6541 (direkt/dynamisch unklar); tests/test_server.py:6554 (direkt/dynamisch unklar); tests/test_server.py:6566 (direkt/dynamisch unklar); tests/test_server.py:7489 (direkt/dynamisch unklar); tests/test_server.py:7496 (direkt/dynamisch unklar); tests/test_server.py:7754 (direkt/dynamisch unklar); tests/test_server.py:7762 (direkt/dynamisch unklar); tests/test_server.py:7782 (direkt/dynamisch unklar); tests/test_server.py:7818 (direkt/dynamisch unklar); tests/test_server.py:7852 (direkt/dynamisch unklar); tests/test_server.py:7869 (direkt/dynamisch unklar); tests/test_server.py:798 (direkt/dynamisch unklar); tests/test_server.py:8057 (direkt/dynamisch unklar); tests/test_server.py:8078 (direkt/dynamisch unklar); tests/test_server.py:8092 (direkt/dynamisch unklar); tests/test_server.py:8099 (direkt/dynamisch unklar); tests/test_server.py:8128 (direkt/dynamisch unklar); tests/test_server.py:817 (direkt/dynamisch unklar); tests/test_server.py:8200 (direkt/dynamisch unklar); tests/test_server.py:8217 (direkt/dynamisch unklar); tests/test_server.py:8244 (direkt/dynamisch unklar); tests/test_server.py:8305 (direkt/dynamisch unklar); tests/test_server.py:8318 (direkt/dynamisch unklar); tests/test_server.py:8321 (direkt/dynamisch unklar); tests/test_server.py:8413 (direkt/dynamisch unklar); tests/test_server.py:8422 (direkt/dynamisch unklar); tests/test_server.py:8425 (direkt/dynamisch unklar); tests/test_server.py:8428 (direkt/dynamisch unklar); tests/test_server.py:8519 (direkt/dynamisch unklar); tests/test_server.py:8568 (direkt/dynamisch unklar); tests/test_server.py:8589 (direkt/dynamisch unklar); tests/test_server.py:8689 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Importbindung | `ClientDisconnected` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8297 (direkt/dynamisch unklar); tests/test_server.py:8298 (direkt/dynamisch unklar); tests/test_server.py:8349 (direkt/dynamisch unklar) |
| Importbindung | `provider_error` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `public_app_error_status` | 42 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4559 (direkt/dynamisch unklar); tests/test_server.py:4560 (direkt/dynamisch unklar) |
| Importbindung | `app_config` | 63 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_audit_remediation.py:206 (direkt/dynamisch unklar); tests/test_provider_review.py:184 (direkt/dynamisch unklar); tests/test_provider_review.py:317 (direkt/dynamisch unklar); tests/test_server.py:231 (direkt/dynamisch unklar); tests/test_server.py:6597 (direkt/dynamisch unklar); tests/test_server.py:6604 (direkt/dynamisch unklar); tests/test_server.py:6613 (direkt/dynamisch unklar); tests/test_server.py:6629 (direkt/dynamisch unklar) |
| Importbindung | `observability` | 64 | `backend` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar); tests/test_provider_review.py:32 (direkt/dynamisch unklar); tests/test_server.py:230 (direkt/dynamisch unklar); tests/test_server.py:7715 (direkt/dynamisch unklar); tests/test_server.py:7780 (direkt/dynamisch unklar); tests/test_server.py:7850 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:7992 (direkt/dynamisch unklar); tests/test_server.py:8227 (direkt/dynamisch unklar); tests/test_server.py:8525 (direkt/dynamisch unklar); tests/test_server.py:8530 (direkt/dynamisch unklar); tests/test_server.py:8533 (direkt/dynamisch unklar) |
| Importbindung | `runtime_events` | 65 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `runtime_maintenance` | 66 | `backend/runtime` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `sync_freshness` | 67 | `backend/sync` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8653 (direkt/dynamisch unklar); tests/test_server.py:8658 (direkt/dynamisch unklar) |
| Importbindung | `SettingsService` | 68 | `backend/settings` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `initialize_application_database` | 69 | `backend/db/bootstrap` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ActivityFeedbackRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1173 (direkt/dynamisch unklar) |
| Importbindung | `ChatRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1099 (direkt/dynamisch unklar) |
| Importbindung | `CheckinRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1107 (direkt/dynamisch unklar) |
| Importbindung | `CompetitionRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1139 (direkt/dynamisch unklar) |
| Importbindung | `KeyValueRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1090 (direkt/dynamisch unklar); tests/test_server.py:1124 (direkt/dynamisch unklar) |
| Importbindung | `PlanAdjustmentRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1163 (direkt/dynamisch unklar) |
| Importbindung | `ProfileRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1124 (direkt/dynamisch unklar) |
| Importbindung | `SnapshotRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1186 (direkt/dynamisch unklar) |
| Importbindung | `TrainingPlanRepository` | 70 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1148 (direkt/dynamisch unklar) |
| Importbindung | `DatabaseManager` | 71 | `backend/db/manager` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CURRENT_DATABASE_INDEXES` | 72 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:163 (direkt/dynamisch unklar) |
| Importbindung | `CURRENT_DATABASE_SCHEMA` | 72 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1554 (direkt/dynamisch unklar); tests/test_server.py:162 (direkt/dynamisch unklar) |
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
| Importbindung | `openai_provider` | 85 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:5800 (direkt/dynamisch unklar) |
| Importbindung | `provider_state` | 86 | `backend/providers` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_error_detail` | 87 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
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
| Importbindung | `response_json_bytes` | 138 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:7480 (direkt/dynamisch unklar) |
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
| Globale Bindung | `Garmin` | 158 | `sync/` | P6 | offen | tests/test_provider_review.py:215 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4088 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `sqlite_backend` | 163 | `db/` | P1 | offen | tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:6534 (direkt/dynamisch unklar); tests/test_server.py:6547 (direkt/dynamisch unklar) |
| Globale Bindung | `SQLCIPHER_AVAILABLE` | 164 | `db/` | P1 | offen | tests/test_audit_remediation.py:282 (direkt/dynamisch unklar); tests/test_provider_review.py:315 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:323 (direkt/dynamisch unklar); tests/test_server.py:2728 (direkt/dynamisch unklar); tests/test_server.py:3263 (direkt/dynamisch unklar); tests/test_server.py:6511 (direkt/dynamisch unklar) |
| Globale Bindung | `ROOT` | 170 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:6592 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6612 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PUBLIC_DIR` | 171 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2438 (direkt/dynamisch unklar); tests/test_server.py:2439 (direkt/dynamisch unklar); tests/test_server.py:2455 (direkt/dynamisch unklar); tests/test_server.py:2456 (direkt/dynamisch unklar); tests/test_server.py:7278 (direkt/dynamisch unklar); tests/test_server.py:7279 (direkt/dynamisch unklar); tests/test_server.py:7290 (direkt/dynamisch unklar); tests/test_server.py:7291 (direkt/dynamisch unklar); tests/test_server.py:7299 (direkt/dynamisch unklar); tests/test_server.py:7300 (direkt/dynamisch unklar); tests/test_server.py:7308 (direkt/dynamisch unklar); tests/test_server.py:7309 (direkt/dynamisch unklar); tests/test_server.py:7315 (direkt/dynamisch unklar); tests/test_server.py:7316 (direkt/dynamisch unklar); tests/test_server.py:7325 (direkt/dynamisch unklar); tests/test_server.py:7326 (direkt/dynamisch unklar); tests/test_server.py:7327 (direkt/dynamisch unklar); tests/test_server.py:7328 (direkt/dynamisch unklar); tests/test_server.py:7539 (direkt/dynamisch unklar); tests/test_server.py:7558 (direkt/dynamisch unklar); tests/test_server.py:8664 (direkt/dynamisch unklar); tests/test_server.py:8665 (direkt/dynamisch unklar) |
| Globale Bindung | `DATA_DIR` | 172 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:112 (direkt/dynamisch unklar); tests/test_server.py:121 (direkt/dynamisch unklar); tests/test_server.py:191 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2733 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3274 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6517 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6592 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6612 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7715 (direkt/dynamisch unklar); tests/test_server.py:7780 (direkt/dynamisch unklar); tests/test_server.py:7850 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:7992 (direkt/dynamisch unklar); tests/test_server.py:8227 (direkt/dynamisch unklar); tests/test_server.py:8533 (direkt/dynamisch unklar); tests/test_server.py:97 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 173 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:107 (direkt/dynamisch unklar); tests/test_server.py:111 (direkt/dynamisch unklar); tests/test_server.py:113 (direkt/dynamisch unklar); tests/test_server.py:122 (direkt/dynamisch unklar); tests/test_server.py:2733 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3274 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6517 (Monkeypatch/getattr/sys.modules); tests/test_server.py:98 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 174 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:30 (Monkeypatch/getattr/sys.modules); tests/test_server.py:108 (direkt/dynamisch unklar); tests/test_server.py:114 (direkt/dynamisch unklar); tests/test_server.py:123 (direkt/dynamisch unklar); tests/test_server.py:7715 (direkt/dynamisch unklar); tests/test_server.py:7780 (direkt/dynamisch unklar); tests/test_server.py:7850 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:7992 (direkt/dynamisch unklar); tests/test_server.py:8227 (direkt/dynamisch unklar); tests/test_server.py:8533 (direkt/dynamisch unklar); tests/test_server.py:99 (direkt/dynamisch unklar) |
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
| Globale Bindung | `UUID_PATTERN` | 225 | `http_api/` | P10 | offen | tests/test_server.py:3099 (direkt/dynamisch unklar) |
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
| Globale Bindung | `APP_VERSION` | 240 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2530 (direkt/dynamisch unklar); tests/test_server.py:7272 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 241 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 242 | `http_api/` | P10 | offen | tests/test_server.py:4794 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 243 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 244 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 245 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 246 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 247 | `coach/streams.py` | P8 | offen | tests/test_server.py:1525 (direkt/dynamisch unklar); tests/test_server.py:1535 (direkt/dynamisch unklar); tests/test_server.py:1536 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_EXTERNAL_RESPONSE_BYTES` | 248 | `providers/http.py` | P2 | offen | tests/test_server.py:4327 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4715 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8198 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_DEFAULT_MAX_OUTPUT_TOKENS` | 252 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LONG_PLAN_MAX_OUTPUT_TOKENS` | 253 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_FOLLOWUP_MAX_OUTPUT_TOKENS` | 254 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_TIMEOUT_SECONDS` | 255 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MESSAGE_ATTACHMENTS_QUERY` | 256 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_BASE_URL` | 257 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 258 | `providers/` | P2 | offen | tests/test_server.py:5780 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 259 | `providers/` | P2 | offen | tests/test_server.py:5805 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 260 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 261 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 262 | `coach/` | P7 | offen | tests/test_server.py:4822 (direkt/dynamisch unklar); tests/test_server.py:5148 (direkt/dynamisch unklar); tests/test_server.py:5156 (direkt/dynamisch unklar); tests/test_server.py:5508 (direkt/dynamisch unklar); tests/test_server.py:5638 (direkt/dynamisch unklar); tests/test_server.py:5648 (direkt/dynamisch unklar); tests/test_server.py:5650 (direkt/dynamisch unklar); tests/test_server.py:5653 (direkt/dynamisch unklar); tests/test_server.py:5656 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5670 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 263 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 264 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:150 (direkt/dynamisch unklar); tests/test_audit_remediation.py:156 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:199 (direkt/dynamisch unklar); tests/test_audit_remediation.py:32 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:73 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1070 (direkt/dynamisch unklar); tests/test_server.py:128 (direkt/dynamisch unklar); tests/test_server.py:1344 (direkt/dynamisch unklar); tests/test_server.py:1349 (direkt/dynamisch unklar); tests/test_server.py:1352 (direkt/dynamisch unklar); tests/test_server.py:1370 (direkt/dynamisch unklar); tests/test_server.py:1373 (direkt/dynamisch unklar); tests/test_server.py:1377 (direkt/dynamisch unklar); tests/test_server.py:1454 (direkt/dynamisch unklar); tests/test_server.py:1566 (direkt/dynamisch unklar); tests/test_server.py:159 (direkt/dynamisch unklar); tests/test_server.py:1716 (direkt/dynamisch unklar); tests/test_server.py:2468 (direkt/dynamisch unklar); tests/test_server.py:2482 (direkt/dynamisch unklar); tests/test_server.py:2495 (direkt/dynamisch unklar); tests/test_server.py:2552 (direkt/dynamisch unklar); tests/test_server.py:2569 (direkt/dynamisch unklar); tests/test_server.py:2698 (direkt/dynamisch unklar); tests/test_server.py:2711 (direkt/dynamisch unklar); tests/test_server.py:2716 (direkt/dynamisch unklar); tests/test_server.py:2914 (direkt/dynamisch unklar); tests/test_server.py:2994 (direkt/dynamisch unklar); tests/test_server.py:4540 (direkt/dynamisch unklar); tests/test_server.py:4841 (direkt/dynamisch unklar); tests/test_server.py:4973 (direkt/dynamisch unklar); tests/test_server.py:4996 (direkt/dynamisch unklar); tests/test_server.py:5019 (direkt/dynamisch unklar); tests/test_server.py:5041 (direkt/dynamisch unklar); tests/test_server.py:5055 (direkt/dynamisch unklar); tests/test_server.py:5061 (direkt/dynamisch unklar); tests/test_server.py:5078 (direkt/dynamisch unklar); tests/test_server.py:5086 (direkt/dynamisch unklar); tests/test_server.py:5408 (direkt/dynamisch unklar); tests/test_server.py:5450 (direkt/dynamisch unklar); tests/test_server.py:5538 (direkt/dynamisch unklar); tests/test_server.py:5561 (direkt/dynamisch unklar); tests/test_server.py:5820 (direkt/dynamisch unklar); tests/test_server.py:5832 (direkt/dynamisch unklar); tests/test_server.py:5851 (direkt/dynamisch unklar); tests/test_server.py:5925 (direkt/dynamisch unklar); tests/test_server.py:5947 (direkt/dynamisch unklar); tests/test_server.py:5956 (direkt/dynamisch unklar); tests/test_server.py:6081 (direkt/dynamisch unklar); tests/test_server.py:6373 (direkt/dynamisch unklar); tests/test_server.py:6436 (direkt/dynamisch unklar); tests/test_server.py:6481 (direkt/dynamisch unklar); tests/test_server.py:6520 (direkt/dynamisch unklar); tests/test_server.py:6529 (direkt/dynamisch unklar); tests/test_server.py:654 (direkt/dynamisch unklar); tests/test_server.py:6705 (direkt/dynamisch unklar); tests/test_server.py:6714 (direkt/dynamisch unklar); tests/test_server.py:6724 (direkt/dynamisch unklar); tests/test_server.py:6875 (direkt/dynamisch unklar); tests/test_server.py:698 (direkt/dynamisch unklar); tests/test_server.py:709 (direkt/dynamisch unklar); tests/test_server.py:723 (direkt/dynamisch unklar); tests/test_server.py:7669 (direkt/dynamisch unklar); tests/test_server.py:8486 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8506 (direkt/dynamisch unklar); tests/test_server.py:8642 (direkt/dynamisch unklar); tests/test_server.py:8656 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 265 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7679 (direkt/dynamisch unklar); tests/test_server.py:7691 (direkt/dynamisch unklar); tests/test_server.py:7694 (direkt/dynamisch unklar); tests/test_server.py:7707 (direkt/dynamisch unklar); tests/test_server.py:7708 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 266 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 267 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 268 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 269 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 270 | `performance/` | P3 | offen | tests/test_server.py:662 (direkt/dynamisch unklar); tests/test_server.py:668 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 271 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 272 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 273 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:154 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 274 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8406 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 275 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8406 (direkt/dynamisch unklar); tests/test_server.py:8419 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 276 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 277 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 278 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 279 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 280 | `coach/jobs.py` | P8 | offen | tests/test_server.py:254 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 281 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:155 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 282 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:300 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 283 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 284 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 285 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 286 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 287 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 288 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 289 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 290 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5832 (direkt/dynamisch unklar); tests/test_server.py:5851 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 291 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LOCK` | 292 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7931 (direkt/dynamisch unklar); tests/test_server.py:7937 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 293 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7932 (direkt/dynamisch unklar); tests/test_server.py:7933 (direkt/dynamisch unklar); tests/test_server.py:7938 (direkt/dynamisch unklar); tests/test_server.py:7939 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 294 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 295 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 296 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 297 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Klasse | `ProviderResyncGate` | 300 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 347 | `sync/` | P6 | offen | tests/test_server.py:6559 (direkt/dynamisch unklar); tests/test_server.py:6574 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 348 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 351 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 356 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 364 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `CONFIG` | 372 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:154 (direkt/dynamisch unklar); tests/test_audit_remediation.py:286 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (direkt/dynamisch unklar); tests/test_provider_review.py:196 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:314 (direkt/dynamisch unklar); tests/test_provider_review.py:318 (direkt/dynamisch unklar); tests/test_provider_review.py:327 (direkt/dynamisch unklar); tests/test_provider_review.py:328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:103 (direkt/dynamisch unklar); tests/test_server.py:1033 (direkt/dynamisch unklar); tests/test_server.py:1034 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1042 (direkt/dynamisch unklar); tests/test_server.py:1043 (Monkeypatch/getattr/sys.modules); tests/test_server.py:120 (direkt/dynamisch unklar); tests/test_server.py:1257 (direkt/dynamisch unklar); tests/test_server.py:1328 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1328 (direkt/dynamisch unklar); tests/test_server.py:1688 (direkt/dynamisch unklar); tests/test_server.py:1690 (Monkeypatch/getattr/sys.modules); tests/test_server.py:189 (direkt/dynamisch unklar); tests/test_server.py:191 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2473 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2473 (direkt/dynamisch unklar); tests/test_server.py:2512 (direkt/dynamisch unklar); tests/test_server.py:2513 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2542 (direkt/dynamisch unklar); tests/test_server.py:2543 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2557 (direkt/dynamisch unklar); tests/test_server.py:2558 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2619 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2619 (direkt/dynamisch unklar); tests/test_server.py:2714 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2714 (direkt/dynamisch unklar); tests/test_server.py:2723 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2723 (direkt/dynamisch unklar); tests/test_server.py:2732 (direkt/dynamisch unklar); tests/test_server.py:2733 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3273 (direkt/dynamisch unklar); tests/test_server.py:3274 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3515 (direkt/dynamisch unklar); tests/test_server.py:3588 (direkt/dynamisch unklar); tests/test_server.py:3608 (direkt/dynamisch unklar); tests/test_server.py:3619 (direkt/dynamisch unklar); tests/test_server.py:3638 (direkt/dynamisch unklar); tests/test_server.py:3814 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3814 (direkt/dynamisch unklar); tests/test_server.py:3832 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3832 (direkt/dynamisch unklar); tests/test_server.py:3842 (direkt/dynamisch unklar); tests/test_server.py:4087 (direkt/dynamisch unklar); tests/test_server.py:4088 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4155 (direkt/dynamisch unklar); tests/test_server.py:4163 (direkt/dynamisch unklar); tests/test_server.py:4255 (direkt/dynamisch unklar); tests/test_server.py:4257 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4300 (direkt/dynamisch unklar); tests/test_server.py:4301 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4324 (direkt/dynamisch unklar); tests/test_server.py:4326 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4348 (direkt/dynamisch unklar); tests/test_server.py:4349 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4472 (direkt/dynamisch unklar); tests/test_server.py:4473 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4487 (direkt/dynamisch unklar); tests/test_server.py:4488 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4498 (direkt/dynamisch unklar); tests/test_server.py:4499 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4513 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4513 (direkt/dynamisch unklar); tests/test_server.py:4517 (direkt/dynamisch unklar); tests/test_server.py:4519 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4527 (direkt/dynamisch unklar); tests/test_server.py:4532 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4551 (direkt/dynamisch unklar); tests/test_server.py:4552 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4734 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4734 (direkt/dynamisch unklar); tests/test_server.py:4758 (direkt/dynamisch unklar); tests/test_server.py:4759 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4782 (direkt/dynamisch unklar); tests/test_server.py:4783 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4789 (direkt/dynamisch unklar); tests/test_server.py:4790 (Monkeypatch/getattr/sys.modules); tests/test_server.py:59 (direkt/dynamisch unklar); tests/test_server.py:5998 (direkt/dynamisch unklar); tests/test_server.py:60 (direkt/dynamisch unklar); tests/test_server.py:6000 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6012 (direkt/dynamisch unklar); tests/test_server.py:6013 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6027 (direkt/dynamisch unklar); tests/test_server.py:6029 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6039 (direkt/dynamisch unklar); tests/test_server.py:6042 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6052 (direkt/dynamisch unklar); tests/test_server.py:6060 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6072 (direkt/dynamisch unklar); tests/test_server.py:6073 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6100 (direkt/dynamisch unklar); tests/test_server.py:6101 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6140 (direkt/dynamisch unklar); tests/test_server.py:6141 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6162 (direkt/dynamisch unklar); tests/test_server.py:6163 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6184 (direkt/dynamisch unklar); tests/test_server.py:6185 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6203 (direkt/dynamisch unklar); tests/test_server.py:6204 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6223 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6223 (direkt/dynamisch unklar); tests/test_server.py:6277 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6277 (direkt/dynamisch unklar); tests/test_server.py:6286 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6286 (direkt/dynamisch unklar); tests/test_server.py:6305 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6305 (direkt/dynamisch unklar); tests/test_server.py:6314 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6314 (direkt/dynamisch unklar); tests/test_server.py:6323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6323 (direkt/dynamisch unklar); tests/test_server.py:6331 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6331 (direkt/dynamisch unklar); tests/test_server.py:6348 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6348 (direkt/dynamisch unklar); tests/test_server.py:6392 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6392 (direkt/dynamisch unklar); tests/test_server.py:6424 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6424 (direkt/dynamisch unklar); tests/test_server.py:644 (direkt/dynamisch unklar); tests/test_server.py:645 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6470 (direkt/dynamisch unklar); tests/test_server.py:6495 (direkt/dynamisch unklar); tests/test_server.py:6503 (direkt/dynamisch unklar); tests/test_server.py:6504 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6515 (direkt/dynamisch unklar); tests/test_server.py:6517 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6562 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6583 (Monkeypatch/getattr/sys.modules); tests/test_server.py:661 (direkt/dynamisch unklar); tests/test_server.py:664 (Monkeypatch/getattr/sys.modules); tests/test_server.py:672 (direkt/dynamisch unklar); tests/test_server.py:673 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6760 (direkt/dynamisch unklar); tests/test_server.py:6792 (direkt/dynamisch unklar); tests/test_server.py:6830 (direkt/dynamisch unklar); tests/test_server.py:685 (direkt/dynamisch unklar); tests/test_server.py:686 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6862 (direkt/dynamisch unklar); tests/test_server.py:6878 (direkt/dynamisch unklar); tests/test_server.py:6917 (direkt/dynamisch unklar); tests/test_server.py:6950 (direkt/dynamisch unklar); tests/test_server.py:6977 (direkt/dynamisch unklar); tests/test_server.py:7260 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7260 (direkt/dynamisch unklar); tests/test_server.py:7727 (direkt/dynamisch unklar); tests/test_server.py:7731 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7752 (direkt/dynamisch unklar); tests/test_server.py:7753 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7777 (direkt/dynamisch unklar); tests/test_server.py:7781 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7881 (direkt/dynamisch unklar); tests/test_server.py:7882 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7891 (direkt/dynamisch unklar); tests/test_server.py:7892 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7962 (direkt/dynamisch unklar); tests/test_server.py:7964 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8126 (direkt/dynamisch unklar); tests/test_server.py:8127 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8434 (direkt/dynamisch unklar); tests/test_server.py:8435 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8517 (direkt/dynamisch unklar); tests/test_server.py:8518 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8612 (direkt/dynamisch unklar); tests/test_server.py:8619 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8630 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8686 (direkt/dynamisch unklar); tests/test_server.py:8687 (Monkeypatch/getattr/sys.modules); tests/test_server.py:96 (direkt/dynamisch unklar) |
| Klasse | `IntervalsClient` | 375 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:44 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:55 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:71 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:81 (direkt/dynamisch unklar); tests/test_server.py:3515 (direkt/dynamisch unklar); tests/test_server.py:3588 (direkt/dynamisch unklar); tests/test_server.py:3608 (direkt/dynamisch unklar); tests/test_server.py:3619 (direkt/dynamisch unklar); tests/test_server.py:3638 (direkt/dynamisch unklar); tests/test_server.py:3710 (direkt/dynamisch unklar); tests/test_server.py:3738 (direkt/dynamisch unklar); tests/test_server.py:3769 (direkt/dynamisch unklar); tests/test_server.py:3770 (direkt/dynamisch unklar); tests/test_server.py:3771 (direkt/dynamisch unklar); tests/test_server.py:3789 (direkt/dynamisch unklar); tests/test_server.py:3833 (direkt/dynamisch unklar); tests/test_server.py:3834 (direkt/dynamisch unklar); tests/test_server.py:3842 (direkt/dynamisch unklar); tests/test_server.py:4155 (direkt/dynamisch unklar); tests/test_server.py:4163 (direkt/dynamisch unklar); tests/test_server.py:6001 (direkt/dynamisch unklar); tests/test_server.py:6014 (direkt/dynamisch unklar); tests/test_server.py:6030 (direkt/dynamisch unklar); tests/test_server.py:6043 (direkt/dynamisch unklar); tests/test_server.py:6061 (direkt/dynamisch unklar); tests/test_server.py:6102 (direkt/dynamisch unklar); tests/test_server.py:6103 (direkt/dynamisch unklar); tests/test_server.py:6142 (direkt/dynamisch unklar); tests/test_server.py:6164 (direkt/dynamisch unklar); tests/test_server.py:6186 (direkt/dynamisch unklar); tests/test_server.py:6187 (direkt/dynamisch unklar); tests/test_server.py:6205 (direkt/dynamisch unklar); tests/test_server.py:6406 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6469 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6494 (Monkeypatch/getattr/sys.modules); tests/test_server.py:674 (direkt/dynamisch unklar); tests/test_server.py:6759 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6791 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6829 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6861 (Monkeypatch/getattr/sys.modules); tests/test_server.py:687 (direkt/dynamisch unklar); tests/test_server.py:6877 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6916 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6949 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6976 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7259 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7649 (direkt/dynamisch unklar); tests/test_server.py:7965 (direkt/dynamisch unklar); tests/test_server.py:7966 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 678 | `observability.py` | P1 | offen | tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:23 (direkt/dynamisch unklar); tests/test_provider_review.py:31 (direkt/dynamisch unklar); tests/test_provider_review.py:40 (direkt/dynamisch unklar); tests/test_provider_review.py:42 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_server.py:7472 (direkt/dynamisch unklar); tests/test_server.py:7715 (direkt/dynamisch unklar); tests/test_server.py:7716 (direkt/dynamisch unklar); tests/test_server.py:7717 (direkt/dynamisch unklar); tests/test_server.py:7780 (direkt/dynamisch unklar); tests/test_server.py:7802 (direkt/dynamisch unklar); tests/test_server.py:7850 (direkt/dynamisch unklar); tests/test_server.py:7854 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:7968 (direkt/dynamisch unklar); tests/test_server.py:7992 (direkt/dynamisch unklar); tests/test_server.py:7999 (direkt/dynamisch unklar); tests/test_server.py:8227 (direkt/dynamisch unklar); tests/test_server.py:8256 (direkt/dynamisch unklar); tests/test_server.py:8267 (direkt/dynamisch unklar); tests/test_server.py:8533 (direkt/dynamisch unklar); tests/test_server.py:8540 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTOR` | 679 | `observability.py` | P1 | offen | tests/test_server.py:4514 (direkt/dynamisch unklar); tests/test_server.py:7715 (direkt/dynamisch unklar); tests/test_server.py:7742 (direkt/dynamisch unklar); tests/test_server.py:7780 (direkt/dynamisch unklar); tests/test_server.py:7850 (direkt/dynamisch unklar); tests/test_server.py:7963 (direkt/dynamisch unklar); tests/test_server.py:7992 (direkt/dynamisch unklar); tests/test_server.py:8227 (direkt/dynamisch unklar); tests/test_server.py:8533 (direkt/dynamisch unklar) |
| Funktion | `external_call` | 682 | `providers/http.py` | P2 | offen | tests/test_server.py:1809 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7755 (direkt/dynamisch unklar); tests/test_server.py:7831 (direkt/dynamisch unklar); tests/test_server.py:7846 (direkt/dynamisch unklar); tests/test_server.py:8534 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 745 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 764 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 765 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 766 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 767 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 768 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 769 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 770 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 771 | `weather/` | P3 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_server.py:1245 (direkt/dynamisch unklar); tests/test_server.py:1247 (direkt/dynamisch unklar); tests/test_server.py:1271 (direkt/dynamisch unklar); tests/test_server.py:1274 (direkt/dynamisch unklar); tests/test_server.py:1451 (direkt/dynamisch unklar); tests/test_server.py:1589 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 772 | `weather/` | P3 | offen | tests/test_audit_remediation.py:122 (direkt/dynamisch unklar); tests/test_audit_remediation.py:85 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 773 | `history/` | P5 | offen | tests/test_server.py:4097 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 774 | `weather/` | P3 | offen | tests/test_server.py:1265 (direkt/dynamisch unklar); tests/test_server.py:1267 (direkt/dynamisch unklar); tests/test_server.py:1272 (direkt/dynamisch unklar); tests/test_server.py:1275 (direkt/dynamisch unklar); tests/test_server.py:1320 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 775 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 776 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 777 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 778 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 779 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 809 | `weather/` | P3 | offen | tests/test_server.py:7405 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 841 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `serialise_conversation` | 874 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8409 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 891 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:186 (direkt/dynamisch unklar); tests/test_audit_remediation.py:201 (direkt/dynamisch unklar); tests/test_audit_remediation.py:69 (direkt/dynamisch unklar); tests/test_audit_remediation.py:81 (direkt/dynamisch unklar); tests/test_audit_remediation.py:95 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1069 (direkt/dynamisch unklar); tests/test_server.py:1220 (direkt/dynamisch unklar); tests/test_server.py:1223 (direkt/dynamisch unklar); tests/test_server.py:1291 (direkt/dynamisch unklar); tests/test_server.py:1310 (direkt/dynamisch unklar); tests/test_server.py:1457 (direkt/dynamisch unklar); tests/test_server.py:1461 (direkt/dynamisch unklar); tests/test_server.py:1577 (direkt/dynamisch unklar); tests/test_server.py:1719 (direkt/dynamisch unklar); tests/test_server.py:2471 (direkt/dynamisch unklar); tests/test_server.py:2485 (direkt/dynamisch unklar); tests/test_server.py:2498 (direkt/dynamisch unklar); tests/test_server.py:2555 (direkt/dynamisch unklar); tests/test_server.py:2572 (direkt/dynamisch unklar); tests/test_server.py:2701 (direkt/dynamisch unklar); tests/test_server.py:2997 (direkt/dynamisch unklar); tests/test_server.py:3001 (direkt/dynamisch unklar); tests/test_server.py:4975 (direkt/dynamisch unklar); tests/test_server.py:4998 (direkt/dynamisch unklar); tests/test_server.py:5021 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5064 (direkt/dynamisch unklar); tests/test_server.py:5088 (direkt/dynamisch unklar); tests/test_server.py:5539 (direkt/dynamisch unklar); tests/test_server.py:5563 (direkt/dynamisch unklar); tests/test_server.py:5835 (direkt/dynamisch unklar); tests/test_server.py:5854 (direkt/dynamisch unklar); tests/test_server.py:7670 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 895 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 896 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 897 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 898 | `planning/` | P4 | offen | tests/test_server.py:4974 (direkt/dynamisch unklar); tests/test_server.py:4997 (direkt/dynamisch unklar); tests/test_server.py:5020 (direkt/dynamisch unklar); tests/test_server.py:5042 (direkt/dynamisch unklar); tests/test_server.py:5056 (direkt/dynamisch unklar); tests/test_server.py:5063 (direkt/dynamisch unklar); tests/test_server.py:5079 (direkt/dynamisch unklar); tests/test_server.py:5087 (direkt/dynamisch unklar); tests/test_server.py:5539 (direkt/dynamisch unklar); tests/test_server.py:5562 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 899 | `planning/` | P4 | offen | tests/test_server.py:7670 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 900 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4462 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 901 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 902 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 903 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CONTEXT` | 906 | `observability.py` | P1 | offen | tests/test_server.py:7949 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 907 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:335 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:168 (direkt/dynamisch unklar); tests/test_server.py:198 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 908 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:336 (direkt/dynamisch unklar); tests/test_provider_review.py:49 (direkt/dynamisch unklar); tests/test_server.py:169 (direkt/dynamisch unklar); tests/test_server.py:199 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_STATE_SERVICE` | 909 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 911 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 912 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 913 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 914 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 915 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 916 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 917 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 918 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 919 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 920 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 921 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 924 | `history/` | P5 | offen | tests/test_server.py:5508 (direkt/dynamisch unklar); tests/test_server.py:5519 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 925 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 926 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 927 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 928 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 933 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 938 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 943 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 947 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 949 | `planning/` | P4 | offen | tests/test_server.py:422 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 950 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 951 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 954 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 965 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 971 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 980 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 990 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1017 | `observability.py` | P1 | offen | tests/test_server.py:7946 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1038 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1081 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:297 (direkt/dynamisch unklar); tests/test_provider_review.py:187 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:197 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_provider_review.py:334 (direkt/dynamisch unklar); tests/test_server.py:167 (direkt/dynamisch unklar); tests/test_server.py:196 (direkt/dynamisch unklar) |
| Funktion | `provider_state_service` | 1109 | `settings.py` | P1 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_server.py:166 (direkt/dynamisch unklar); tests/test_server.py:171 (direkt/dynamisch unklar); tests/test_server.py:5390 (direkt/dynamisch unklar); tests/test_server.py:5781 (direkt/dynamisch unklar); tests/test_server.py:5801 (direkt/dynamisch unklar); tests/test_server.py:8031 (direkt/dynamisch unklar); tests/test_server.py:8061 (direkt/dynamisch unklar); tests/test_server.py:8177 (direkt/dynamisch unklar); tests/test_server.py:8206 (direkt/dynamisch unklar); tests/test_server.py:8222 (direkt/dynamisch unklar); tests/test_server.py:8249 (direkt/dynamisch unklar); tests/test_server.py:8300 (direkt/dynamisch unklar); tests/test_server.py:8441 (direkt/dynamisch unklar); tests/test_server.py:8491 (direkt/dynamisch unklar) |
| Funktion | `database` | 1126 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:150 (direkt/dynamisch unklar); tests/test_audit_remediation.py:156 (direkt/dynamisch unklar); tests/test_audit_remediation.py:185 (direkt/dynamisch unklar); tests/test_audit_remediation.py:199 (direkt/dynamisch unklar); tests/test_audit_remediation.py:32 (direkt/dynamisch unklar); tests/test_audit_remediation.py:68 (direkt/dynamisch unklar); tests/test_audit_remediation.py:73 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1070 (direkt/dynamisch unklar); tests/test_server.py:1091 (direkt/dynamisch unklar); tests/test_server.py:1100 (direkt/dynamisch unklar); tests/test_server.py:1114 (direkt/dynamisch unklar); tests/test_server.py:1126 (direkt/dynamisch unklar); tests/test_server.py:1140 (direkt/dynamisch unklar); tests/test_server.py:1149 (direkt/dynamisch unklar); tests/test_server.py:1158 (direkt/dynamisch unklar); tests/test_server.py:1165 (direkt/dynamisch unklar); tests/test_server.py:1176 (direkt/dynamisch unklar); tests/test_server.py:1187 (direkt/dynamisch unklar); tests/test_server.py:128 (direkt/dynamisch unklar); tests/test_server.py:1344 (direkt/dynamisch unklar); tests/test_server.py:1349 (direkt/dynamisch unklar); tests/test_server.py:1352 (direkt/dynamisch unklar); tests/test_server.py:1370 (direkt/dynamisch unklar); tests/test_server.py:1373 (direkt/dynamisch unklar); tests/test_server.py:1377 (direkt/dynamisch unklar); tests/test_server.py:1454 (direkt/dynamisch unklar); tests/test_server.py:1566 (direkt/dynamisch unklar); tests/test_server.py:159 (direkt/dynamisch unklar); tests/test_server.py:1716 (direkt/dynamisch unklar); tests/test_server.py:2468 (direkt/dynamisch unklar); tests/test_server.py:2482 (direkt/dynamisch unklar); tests/test_server.py:2495 (direkt/dynamisch unklar); tests/test_server.py:2552 (direkt/dynamisch unklar); tests/test_server.py:2569 (direkt/dynamisch unklar); tests/test_server.py:2698 (direkt/dynamisch unklar); tests/test_server.py:2711 (direkt/dynamisch unklar); tests/test_server.py:2716 (direkt/dynamisch unklar); tests/test_server.py:2735 (direkt/dynamisch unklar); tests/test_server.py:2914 (direkt/dynamisch unklar); tests/test_server.py:2994 (direkt/dynamisch unklar); tests/test_server.py:3282 (direkt/dynamisch unklar); tests/test_server.py:4461 (direkt/dynamisch unklar); tests/test_server.py:4540 (direkt/dynamisch unklar); tests/test_server.py:4841 (direkt/dynamisch unklar); tests/test_server.py:4973 (direkt/dynamisch unklar); tests/test_server.py:4996 (direkt/dynamisch unklar); tests/test_server.py:5019 (direkt/dynamisch unklar); tests/test_server.py:5041 (direkt/dynamisch unklar); tests/test_server.py:5055 (direkt/dynamisch unklar); tests/test_server.py:5061 (direkt/dynamisch unklar); tests/test_server.py:5078 (direkt/dynamisch unklar); tests/test_server.py:5086 (direkt/dynamisch unklar); tests/test_server.py:5408 (direkt/dynamisch unklar); tests/test_server.py:5450 (direkt/dynamisch unklar); tests/test_server.py:5538 (direkt/dynamisch unklar); tests/test_server.py:5561 (direkt/dynamisch unklar); tests/test_server.py:5820 (direkt/dynamisch unklar); tests/test_server.py:5832 (direkt/dynamisch unklar); tests/test_server.py:5851 (direkt/dynamisch unklar); tests/test_server.py:5925 (direkt/dynamisch unklar); tests/test_server.py:5947 (direkt/dynamisch unklar); tests/test_server.py:5956 (direkt/dynamisch unklar); tests/test_server.py:6081 (direkt/dynamisch unklar); tests/test_server.py:6373 (direkt/dynamisch unklar); tests/test_server.py:6436 (direkt/dynamisch unklar); tests/test_server.py:6481 (direkt/dynamisch unklar); tests/test_server.py:6520 (direkt/dynamisch unklar); tests/test_server.py:6529 (direkt/dynamisch unklar); tests/test_server.py:654 (direkt/dynamisch unklar); tests/test_server.py:6705 (direkt/dynamisch unklar); tests/test_server.py:6714 (direkt/dynamisch unklar); tests/test_server.py:6724 (direkt/dynamisch unklar); tests/test_server.py:6875 (direkt/dynamisch unklar); tests/test_server.py:698 (direkt/dynamisch unklar); tests/test_server.py:709 (direkt/dynamisch unklar); tests/test_server.py:723 (direkt/dynamisch unklar); tests/test_server.py:7669 (direkt/dynamisch unklar); tests/test_server.py:7908 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8359 (direkt/dynamisch unklar); tests/test_server.py:8506 (direkt/dynamisch unklar); tests/test_server.py:8642 (direkt/dynamisch unklar); tests/test_server.py:8656 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1132 | `db/bootstrap.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:288 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:37 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:115 (direkt/dynamisch unklar); tests/test_server.py:1229 (direkt/dynamisch unklar); tests/test_server.py:158 (direkt/dynamisch unklar); tests/test_server.py:195 (direkt/dynamisch unklar); tests/test_server.py:215 (direkt/dynamisch unklar); tests/test_server.py:223 (direkt/dynamisch unklar); tests/test_server.py:232 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2715 (direkt/dynamisch unklar); tests/test_server.py:2724 (direkt/dynamisch unklar); tests/test_server.py:2734 (direkt/dynamisch unklar); tests/test_server.py:3275 (direkt/dynamisch unklar); tests/test_server.py:6518 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1144 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1152 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8624 (direkt/dynamisch unklar); tests/test_server.py:8640 (direkt/dynamisch unklar); tests/test_server.py:8654 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1164 | `sync/refresh.py` | P6 | offen | tests/test_server.py:8625 (direkt/dynamisch unklar); tests/test_server.py:8641 (direkt/dynamisch unklar); tests/test_server.py:8655 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1198 | `sync/refresh.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1213 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1227 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1236 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1250 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1263 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1273 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1282 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1292 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1299 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1324 | `sync/` | P6 | offen | tests/test_audit_remediation.py:294 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:267 (direkt/dynamisch unklar); tests/test_server.py:269 (direkt/dynamisch unklar); tests/test_server.py:273 (direkt/dynamisch unklar); tests/test_server.py:284 (direkt/dynamisch unklar); tests/test_server.py:317 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1333 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:142 (direkt/dynamisch unklar); tests/test_provider_review.py:179 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1339 | `sync/` | P6 | offen | tests/test_server.py:1034 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1043 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1344 | `sync/` | P6 | offen | tests/test_server.py:665 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1367 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1375 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1384 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1402 | `sync/` | P6 | offen | tests/test_server.py:677 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1429 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1438 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1445 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1455 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 1480 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 1494 | `sync/` | P6 | offen | tests/test_audit_remediation.py:256 (direkt/dynamisch unklar); tests/test_audit_remediation.py:289 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:1045 (Monkeypatch/getattr/sys.modules); tests/test_server.py:262 (direkt/dynamisch unklar); tests/test_server.py:279 (direkt/dynamisch unklar); tests/test_server.py:306 (direkt/dynamisch unklar); tests/test_server.py:403 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4814 (direkt/dynamisch unklar); tests/test_server.py:4818 (direkt/dynamisch unklar); tests/test_server.py:490 (Monkeypatch/getattr/sys.modules); tests/test_server.py:586 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6280 (direkt/dynamisch unklar); tests/test_server.py:6289 (direkt/dynamisch unklar); tests/test_server.py:6308 (direkt/dynamisch unklar); tests/test_server.py:6317 (direkt/dynamisch unklar); tests/test_server.py:646 (direkt/dynamisch unklar); tests/test_server.py:649 (direkt/dynamisch unklar); tests/test_server.py:664 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8634 (direkt/dynamisch unklar); tests/test_server.py:926 (Monkeypatch/getattr/sys.modules); tests/test_server.py:952 (Monkeypatch/getattr/sys.modules); tests/test_server.py:997 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 1521 | `sync/` | P6 | offen | tests/test_server.py:220 (Monkeypatch/getattr/sys.modules); tests/test_server.py:250 (Monkeypatch/getattr/sys.modules); tests/test_server.py:268 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 1541 | `sync/` | P6 | offen | tests/test_audit_remediation.py:290 (direkt/dynamisch unklar); tests/test_audit_remediation.py:295 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:154 (direkt/dynamisch unklar); tests/test_server.py:265 (direkt/dynamisch unklar); tests/test_server.py:270 (direkt/dynamisch unklar); tests/test_server.py:280 (direkt/dynamisch unklar); tests/test_server.py:313 (direkt/dynamisch unklar); tests/test_server.py:6281 (direkt/dynamisch unklar); tests/test_server.py:6290 (direkt/dynamisch unklar); tests/test_server.py:6309 (direkt/dynamisch unklar); tests/test_server.py:6318 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 1562 | `sync/` | P6 | offen | tests/test_audit_remediation.py:257 (direkt/dynamisch unklar); tests/test_audit_remediation.py:292 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 1600 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 1606 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 1617 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 1637 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 1652 | `sync/jobs.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 1669 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 1682 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 1691 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 1698 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 1715 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 1727 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 1739 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:138 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:167 (Monkeypatch/getattr/sys.modules); tests/test_server.py:271 (Monkeypatch/getattr/sys.modules); tests/test_server.py:282 (Monkeypatch/getattr/sys.modules); tests/test_server.py:295 (direkt/dynamisch unklar); tests/test_server.py:315 (Monkeypatch/getattr/sys.modules); tests/test_server.py:612 (direkt/dynamisch unklar); tests/test_server.py:613 (direkt/dynamisch unklar); tests/test_server.py:625 (direkt/dynamisch unklar); tests/test_server.py:638 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 1762 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 1771 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 1791 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 1811 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 1829 | `sync/` | P6 | offen | tests/test_provider_review.py:139 (direkt/dynamisch unklar); tests/test_provider_review.py:168 (direkt/dynamisch unklar); tests/test_server.py:272 (direkt/dynamisch unklar); tests/test_server.py:283 (direkt/dynamisch unklar); tests/test_server.py:316 (direkt/dynamisch unklar); tests/test_server.py:6281 (direkt/dynamisch unklar); tests/test_server.py:6290 (direkt/dynamisch unklar); tests/test_server.py:6309 (direkt/dynamisch unklar); tests/test_server.py:6318 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 1839 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 1854 | `sync/` | P6 | offen | tests/test_server.py:255 (direkt/dynamisch unklar) |
| Funktion | `resolve_sync_job` | 1865 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_current_provider_freshness` | 1888 | `sync/freshness.py` | P6 | offen | tests/test_server.py:6078 (direkt/dynamisch unklar); tests/test_server.py:8621 (direkt/dynamisch unklar); tests/test_server.py:8626 (direkt/dynamisch unklar); tests/test_server.py:8631 (direkt/dynamisch unklar); tests/test_server.py:8638 (direkt/dynamisch unklar); tests/test_server.py:8648 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 1902 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 1916 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 1927 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 1951 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 1956 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 1968 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 1978 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 1995 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2034 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2066 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3042 (direkt/dynamisch unklar); tests/test_server.py:5491 (direkt/dynamisch unklar); tests/test_server.py:5580 (direkt/dynamisch unklar); tests/test_server.py:5629 (direkt/dynamisch unklar); tests/test_server.py:8575 (direkt/dynamisch unklar); tests/test_server.py:8595 (direkt/dynamisch unklar); tests/test_server.py:8604 (direkt/dynamisch unklar); tests/test_server.py:8607 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2077 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2089 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2103 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2119 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8584 (direkt/dynamisch unklar); tests/test_server.py:8590 (direkt/dynamisch unklar); tests/test_server.py:8596 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2157 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2177 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2187 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2212 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2233 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2243 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2252 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2278 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2294 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2314 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2323 | `history/` | P5 | offen | tests/test_server.py:3049 (direkt/dynamisch unklar); tests/test_server.py:5498 (direkt/dynamisch unklar); tests/test_server.py:5633 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2338 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:121 (direkt/dynamisch unklar); tests/test_audit_remediation.py:122 (direkt/dynamisch unklar); tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_audit_remediation.py:303 (direkt/dynamisch unklar); tests/test_audit_remediation.py:304 (direkt/dynamisch unklar); tests/test_audit_remediation.py:84 (direkt/dynamisch unklar); tests/test_audit_remediation.py:85 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar); tests/test_provider_review.py:337 (direkt/dynamisch unklar); tests/test_server.py:1247 (direkt/dynamisch unklar); tests/test_server.py:1267 (direkt/dynamisch unklar); tests/test_server.py:1274 (direkt/dynamisch unklar); tests/test_server.py:1275 (direkt/dynamisch unklar); tests/test_server.py:1320 (direkt/dynamisch unklar); tests/test_server.py:216 (direkt/dynamisch unklar); tests/test_server.py:217 (direkt/dynamisch unklar); tests/test_server.py:2725 (direkt/dynamisch unklar); tests/test_server.py:2726 (direkt/dynamisch unklar); tests/test_server.py:4048 (direkt/dynamisch unklar); tests/test_server.py:4049 (direkt/dynamisch unklar); tests/test_server.py:4355 (direkt/dynamisch unklar); tests/test_server.py:4478 (direkt/dynamisch unklar); tests/test_server.py:6035 (direkt/dynamisch unklar); tests/test_server.py:6047 (direkt/dynamisch unklar); tests/test_server.py:6048 (direkt/dynamisch unklar); tests/test_server.py:6151 (direkt/dynamisch unklar); tests/test_server.py:6170 (direkt/dynamisch unklar); tests/test_server.py:6174 (direkt/dynamisch unklar); tests/test_server.py:6509 (direkt/dynamisch unklar); tests/test_server.py:6528 (direkt/dynamisch unklar); tests/test_server.py:6586 (direkt/dynamisch unklar); tests/test_server.py:7681 (direkt/dynamisch unklar); tests/test_server.py:7699 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 2345 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 2346 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 2347 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 2348 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 2349 | `planning/` | P4 | offen | tests/test_server.py:2591 (direkt/dynamisch unklar); tests/test_server.py:2601 (direkt/dynamisch unklar); tests/test_server.py:2626 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 2350 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 2351 | `planning/` | P4 | offen | tests/test_server.py:2388 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 2352 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 2355 | `planning/` | P4 | offen | tests/test_server.py:3533 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 2356 | `planning/` | P4 | offen | tests/test_server.py:3534 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 2357 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 2358 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 2359 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 2360 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 2361 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 2362 | `coach/` | P7 | offen | tests/test_server.py:5269 (direkt/dynamisch unklar); tests/test_server.py:5280 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 2363 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 2376 | `sync/` | P6 | offen | tests/test_server.py:5972 (direkt/dynamisch unklar); tests/test_server.py:5974 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 2387 | `sync/` | P6 | offen | tests/test_server.py:5971 (direkt/dynamisch unklar); tests/test_server.py:5973 (direkt/dynamisch unklar); tests/test_server.py:5999 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 2399 | `sync/` | P6 | offen | tests/test_server.py:5975 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 2410 | `settings.py` | P1 | offen | tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:223 (direkt/dynamisch unklar); tests/test_provider_review.py:247 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 2415 | `settings.py` | P1 | offen | tests/test_provider_review.py:210 (direkt/dynamisch unklar); tests/test_provider_review.py:211 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 2421 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_server.py:1245 (direkt/dynamisch unklar); tests/test_server.py:1265 (direkt/dynamisch unklar); tests/test_server.py:1271 (direkt/dynamisch unklar); tests/test_server.py:1272 (direkt/dynamisch unklar); tests/test_server.py:1450 (direkt/dynamisch unklar); tests/test_server.py:1451 (direkt/dynamisch unklar); tests/test_server.py:1452 (direkt/dynamisch unklar); tests/test_server.py:1453 (direkt/dynamisch unklar); tests/test_server.py:1545 (direkt/dynamisch unklar); tests/test_server.py:1557 (direkt/dynamisch unklar); tests/test_server.py:1589 (direkt/dynamisch unklar); tests/test_server.py:1710 (direkt/dynamisch unklar); tests/test_server.py:1925 (direkt/dynamisch unklar); tests/test_server.py:1926 (direkt/dynamisch unklar); tests/test_server.py:1927 (direkt/dynamisch unklar); tests/test_server.py:1928 (direkt/dynamisch unklar); tests/test_server.py:1929 (direkt/dynamisch unklar); tests/test_server.py:213 (direkt/dynamisch unklar); tests/test_server.py:214 (direkt/dynamisch unklar); tests/test_server.py:2721 (direkt/dynamisch unklar); tests/test_server.py:2722 (direkt/dynamisch unklar); tests/test_server.py:3146 (direkt/dynamisch unklar); tests/test_server.py:3170 (direkt/dynamisch unklar); tests/test_server.py:3181 (direkt/dynamisch unklar); tests/test_server.py:3229 (direkt/dynamisch unklar); tests/test_server.py:3336 (direkt/dynamisch unklar); tests/test_server.py:3368 (direkt/dynamisch unklar); tests/test_server.py:3387 (direkt/dynamisch unklar); tests/test_server.py:3428 (direkt/dynamisch unklar); tests/test_server.py:3448 (direkt/dynamisch unklar); tests/test_server.py:4098 (direkt/dynamisch unklar); tests/test_server.py:4104 (direkt/dynamisch unklar); tests/test_server.py:4411 (direkt/dynamisch unklar); tests/test_server.py:4435 (direkt/dynamisch unklar); tests/test_server.py:4448 (direkt/dynamisch unklar); tests/test_server.py:4528 (direkt/dynamisch unklar); tests/test_server.py:4550 (direkt/dynamisch unklar); tests/test_server.py:5336 (direkt/dynamisch unklar); tests/test_server.py:5372 (direkt/dynamisch unklar); tests/test_server.py:5884 (direkt/dynamisch unklar); tests/test_server.py:6040 (direkt/dynamisch unklar); tests/test_server.py:6502 (direkt/dynamisch unklar); tests/test_server.py:6519 (direkt/dynamisch unklar); tests/test_server.py:6577 (direkt/dynamisch unklar); tests/test_server.py:6578 (direkt/dynamisch unklar); tests/test_server.py:7660 (direkt/dynamisch unklar); tests/test_server.py:7661 (direkt/dynamisch unklar); tests/test_server.py:7678 (direkt/dynamisch unklar); tests/test_server.py:7693 (direkt/dynamisch unklar); tests/test_server.py:7767 (direkt/dynamisch unklar); tests/test_server.py:7883 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:8433 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS` | 2429 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:382 (direkt/dynamisch unklar); tests/test_server.py:4500 (direkt/dynamisch unklar); tests/test_server.py:4501 (direkt/dynamisch unklar); tests/test_server.py:4502 (direkt/dynamisch unklar); tests/test_server.py:4506 (direkt/dynamisch unklar); tests/test_server.py:4507 (direkt/dynamisch unklar); tests/test_server.py:4508 (direkt/dynamisch unklar); tests/test_server.py:4509 (direkt/dynamisch unklar); tests/test_server.py:5348 (direkt/dynamisch unklar); tests/test_server.py:5349 (direkt/dynamisch unklar); tests/test_server.py:5350 (direkt/dynamisch unklar); tests/test_server.py:5352 (direkt/dynamisch unklar); tests/test_server.py:5355 (direkt/dynamisch unklar); tests/test_server.py:5356 (direkt/dynamisch unklar); tests/test_server.py:5357 (direkt/dynamisch unklar); tests/test_server.py:5359 (direkt/dynamisch unklar); tests/test_server.py:5362 (direkt/dynamisch unklar); tests/test_server.py:5364 (direkt/dynamisch unklar); tests/test_server.py:5367 (direkt/dynamisch unklar); tests/test_server.py:5369 (direkt/dynamisch unklar); tests/test_server.py:5371 (direkt/dynamisch unklar); tests/test_server.py:5373 (direkt/dynamisch unklar); tests/test_server.py:5376 (direkt/dynamisch unklar) |
| Globale Bindung | `DIAGNOSTIC_CAPTURE` | 2430 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7823 (direkt/dynamisch unklar); tests/test_server.py:7824 (direkt/dynamisch unklar); tests/test_server.py:7838 (direkt/dynamisch unklar); tests/test_server.py:7844 (direkt/dynamisch unklar); tests/test_server.py:7845 (direkt/dynamisch unklar); tests/test_server.py:8125 (direkt/dynamisch unklar); tests/test_server.py:8131 (direkt/dynamisch unklar); tests/test_server.py:8196 (direkt/dynamisch unklar); tests/test_server.py:8209 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 2433 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 2448 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 2465 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:217 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar); tests/test_server.py:5341 (direkt/dynamisch unklar); tests/test_server.py:5343 (direkt/dynamisch unklar); tests/test_server.py:6587 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 2473 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 2477 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4041 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 2485 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 2497 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 2512 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 2522 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 2533 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 2542 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 2557 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 2571 | `activities/` | P3 | offen | tests/test_server.py:3499 (direkt/dynamisch unklar); tests/test_server.py:3507 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 2583 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 2599 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 2614 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7569 (direkt/dynamisch unklar); tests/test_server.py:7580 (direkt/dynamisch unklar); tests/test_server.py:7588 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 2621 | `sync/` | P6 | offen | tests/test_server.py:3312 (direkt/dynamisch unklar); tests/test_server.py:7570 (direkt/dynamisch unklar); tests/test_server.py:7596 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 2628 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 2643 | `activities/` | P3 | offen | tests/test_server.py:7635 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 2666 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 2679 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 2697 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 2715 | `sync/` | P6 | offen | tests/test_server.py:7611 (direkt/dynamisch unklar); tests/test_server.py:7624 (direkt/dynamisch unklar); tests/test_server.py:7636 (direkt/dynamisch unklar); tests/test_server.py:7648 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 2730 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3315 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 2745 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 2758 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 2770 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 2773 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 2777 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 2783 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 2788 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 2797 | `sync/` | P6 | offen | tests/test_server.py:3223 (direkt/dynamisch unklar); tests/test_server.py:3224 (direkt/dynamisch unklar); tests/test_server.py:3225 (direkt/dynamisch unklar); tests/test_server.py:3226 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 2816 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 2829 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 2833 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 2851 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 2865 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 2881 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 2887 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 2895 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 2908 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 2921 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 2928 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 2946 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 2951 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 2977 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 2987 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 2996 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3330 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 3006 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3021 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3030 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3035 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3043 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3057 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3068 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3087 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3098 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3115 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3139 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3148 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3159 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3178 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:292 (direkt/dynamisch unklar); tests/test_provider_review.py:307 (direkt/dynamisch unklar); tests/test_server.py:3198 (direkt/dynamisch unklar); tests/test_server.py:3255 (direkt/dynamisch unklar); tests/test_server.py:3288 (direkt/dynamisch unklar); tests/test_server.py:3315 (direkt/dynamisch unklar); tests/test_server.py:3322 (direkt/dynamisch unklar); tests/test_server.py:3362 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3200 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 3215 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 3220 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 3236 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:302 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 3254 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 3273 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 3302 | `planning/` | P4 | offen | tests/test_server.py:3141 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 3319 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 3327 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 3355 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 3362 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 3386 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 3395 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 3412 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 3428 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 3433 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3998 (direkt/dynamisch unklar); tests/test_server.py:4002 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 3434 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 3437 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4001 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 3445 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4000 (direkt/dynamisch unklar); tests/test_server.py:4005 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 3454 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3999 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 3467 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4004 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 3472 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 3494 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 3504 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 3508 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4053 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 3523 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 3524 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 3527 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 3546 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 3560 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 3571 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4043 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 3582 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 3590 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 3595 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 3599 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 3617 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 3627 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 3631 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4029 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 3651 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 3662 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 3680 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:4008 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 3717 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 3722 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4097 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 3730 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 3743 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 3767 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 3796 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 3820 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4089 (direkt/dynamisch unklar); tests/test_server.py:4090 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 3833 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 3845 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 3875 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 3904 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 3911 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 3970 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 3993 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:242 (direkt/dynamisch unklar); tests/test_server.py:293 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4042 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8520 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4035 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:364 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4042 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4053 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:4096 (direkt/dynamisch unklar); tests/test_server.py:4108 (direkt/dynamisch unklar); tests/test_server.py:7768 (direkt/dynamisch unklar); tests/test_server.py:8521 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4093 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:280 (direkt/dynamisch unklar); tests/test_server.py:3161 (direkt/dynamisch unklar); tests/test_server.py:3175 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4116 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1763 (direkt/dynamisch unklar); tests/test_server.py:1795 (direkt/dynamisch unklar); tests/test_server.py:4432 (direkt/dynamisch unklar); tests/test_server.py:4433 (direkt/dynamisch unklar); tests/test_server.py:4434 (direkt/dynamisch unklar); tests/test_server.py:5159 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4123 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4130 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4133 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4145 | `athlete/` | P3 | offen | tests/test_server.py:1196 (direkt/dynamisch unklar); tests/test_server.py:1659 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4154 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1669 (direkt/dynamisch unklar); tests/test_server.py:6693 (direkt/dynamisch unklar); tests/test_server.py:8588 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4163 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:77 (direkt/dynamisch unklar); tests/test_audit_remediation.py:80 (direkt/dynamisch unklar); tests/test_audit_remediation.py:88 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1219 (direkt/dynamisch unklar); tests/test_server.py:1228 (direkt/dynamisch unklar); tests/test_server.py:1244 (direkt/dynamisch unklar); tests/test_server.py:1246 (direkt/dynamisch unklar); tests/test_server.py:1250 (direkt/dynamisch unklar); tests/test_server.py:1264 (direkt/dynamisch unklar); tests/test_server.py:1266 (direkt/dynamisch unklar); tests/test_server.py:1270 (direkt/dynamisch unklar); tests/test_server.py:1278 (direkt/dynamisch unklar); tests/test_server.py:1285 (direkt/dynamisch unklar); tests/test_server.py:1304 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar); tests/test_server.py:1571 (direkt/dynamisch unklar); tests/test_server.py:1588 (direkt/dynamisch unklar); tests/test_server.py:1631 (direkt/dynamisch unklar); tests/test_server.py:1652 (direkt/dynamisch unklar); tests/test_server.py:1654 (direkt/dynamisch unklar); tests/test_server.py:1665 (direkt/dynamisch unklar); tests/test_server.py:6646 (direkt/dynamisch unklar); tests/test_server.py:6674 (direkt/dynamisch unklar); tests/test_server.py:7243 (direkt/dynamisch unklar); tests/test_server.py:7388 (direkt/dynamisch unklar); tests/test_server.py:8573 (direkt/dynamisch unklar); tests/test_server.py:8574 (direkt/dynamisch unklar); tests/test_server.py:8603 (direkt/dynamisch unklar); tests/test_server.py:8620 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4177 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4187 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4194 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4197 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 4209 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 4221 | `athlete/` | P3 | offen | tests/test_server.py:1676 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 4241 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2600 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 4246 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:184 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1639 (direkt/dynamisch unklar); tests/test_server.py:1648 (direkt/dynamisch unklar); tests/test_server.py:1678 (direkt/dynamisch unklar); tests/test_server.py:1682 (direkt/dynamisch unklar); tests/test_server.py:1709 (direkt/dynamisch unklar); tests/test_server.py:1740 (direkt/dynamisch unklar); tests/test_server.py:2589 (direkt/dynamisch unklar); tests/test_server.py:2610 (direkt/dynamisch unklar); tests/test_server.py:2636 (direkt/dynamisch unklar); tests/test_server.py:2655 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 4254 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 4277 | `athlete/` | P3 | offen | tests/test_server.py:1646 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 4287 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 4294 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 4308 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2435 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 4313 | `activities/` | P3 | offen | tests/test_server.py:2432 (direkt/dynamisch unklar); tests/test_server.py:2434 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 4325 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2402 (direkt/dynamisch unklar); tests/test_server.py:2415 (direkt/dynamisch unklar); tests/test_server.py:2425 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 4342 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 4349 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 4363 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 4375 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 4397 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 4409 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 4423 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 4429 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3097 (direkt/dynamisch unklar); tests/test_server.py:3101 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 4439 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3099 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 4446 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 4459 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3083 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 4480 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:46 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_audit_remediation.py:59 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:6396 (direkt/dynamisch unklar); tests/test_server.py:6478 (direkt/dynamisch unklar); tests/test_server.py:6713 (direkt/dynamisch unklar); tests/test_server.py:6767 (direkt/dynamisch unklar); tests/test_server.py:6801 (direkt/dynamisch unklar); tests/test_server.py:6838 (direkt/dynamisch unklar); tests/test_server.py:6885 (direkt/dynamisch unklar); tests/test_server.py:6922 (direkt/dynamisch unklar); tests/test_server.py:6930 (direkt/dynamisch unklar); tests/test_server.py:6957 (direkt/dynamisch unklar); tests/test_server.py:6985 (direkt/dynamisch unklar); tests/test_server.py:705 (direkt/dynamisch unklar); tests/test_server.py:715 (direkt/dynamisch unklar) |
| Funktion | `list_external_calendar_events` | 4485 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2478 (direkt/dynamisch unklar); tests/test_server.py:2487 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2548 (direkt/dynamisch unklar); tests/test_server.py:2561 (direkt/dynamisch unklar); tests/test_server.py:3003 (direkt/dynamisch unklar); tests/test_server.py:3005 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 4496 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2523 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 4511 | `sync/` | P6 | offen | tests/test_server.py:2477 (direkt/dynamisch unklar); tests/test_server.py:2518 (direkt/dynamisch unklar); tests/test_server.py:2544 (direkt/dynamisch unklar); tests/test_server.py:2560 (direkt/dynamisch unklar); tests/test_server.py:7763 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 4568 | `providers/calendar.py` | P2 | offen | tests/test_audit_remediation.py:170 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 4583 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 4587 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 4591 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 4597 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 4603 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 4611 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 4629 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 4646 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 4673 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 4680 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 4694 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 4726 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 4735 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 4746 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 4765 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 4777 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 4783 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 4796 | `performance/` | P3 | offen | tests/test_server.py:4099 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 4808 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 4812 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 4822 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 4831 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 4841 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 4852 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 4861 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 4881 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 4895 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1721 (direkt/dynamisch unklar); tests/test_server.py:3005 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 4919 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 4928 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 4940 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 4953 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 4968 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 4974 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 4985 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 4993 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 5004 | `athlete/` | P3 | offen | tests/test_server.py:1273 (direkt/dynamisch unklar); tests/test_server.py:3493 (direkt/dynamisch unklar); tests/test_server.py:6268 (direkt/dynamisch unklar); tests/test_server.py:6296 (direkt/dynamisch unklar); tests/test_server.py:6340 (direkt/dynamisch unklar); tests/test_server.py:6358 (direkt/dynamisch unklar); tests/test_server.py:6367 (direkt/dynamisch unklar); tests/test_server.py:6431 (direkt/dynamisch unklar); tests/test_server.py:6654 (direkt/dynamisch unklar); tests/test_server.py:6721 (direkt/dynamisch unklar); tests/test_server.py:6771 (direkt/dynamisch unklar); tests/test_server.py:6807 (direkt/dynamisch unklar); tests/test_server.py:6846 (direkt/dynamisch unklar); tests/test_server.py:6929 (direkt/dynamisch unklar); tests/test_server.py:6935 (direkt/dynamisch unklar); tests/test_server.py:6961 (direkt/dynamisch unklar); tests/test_server.py:6980 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 5021 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 5043 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 5055 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 5056 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 5061 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 5071 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 5089 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 5101 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 5114 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 5126 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 5145 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_audit_remediation.py:40 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1132 (direkt/dynamisch unklar); tests/test_server.py:477 (direkt/dynamisch unklar); tests/test_server.py:6352 (direkt/dynamisch unklar); tests/test_server.py:6378 (direkt/dynamisch unklar); tests/test_server.py:6690 (direkt/dynamisch unklar); tests/test_server.py:6695 (direkt/dynamisch unklar); tests/test_server.py:6729 (direkt/dynamisch unklar); tests/test_server.py:6870 (direkt/dynamisch unklar); tests/test_server.py:695 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 5153 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:52 (direkt/dynamisch unklar); tests/test_audit_remediation.py:64 (direkt/dynamisch unklar); tests/test_server.py:6710 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 5183 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 5204 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 5227 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 5242 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 5252 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 5258 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3076 (direkt/dynamisch unklar); tests/test_server.py:3077 (direkt/dynamisch unklar); tests/test_server.py:3078 (direkt/dynamisch unklar); tests/test_server.py:3079 (direkt/dynamisch unklar); tests/test_server.py:3080 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 5263 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 5278 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:31 (direkt/dynamisch unklar); tests/test_server.py:6376 (direkt/dynamisch unklar); tests/test_server.py:6708 (direkt/dynamisch unklar); tests/test_server.py:6723 (direkt/dynamisch unklar); tests/test_server.py:6800 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 5282 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3105 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 5302 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3093 (direkt/dynamisch unklar); tests/test_server.py:3094 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 5318 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 5328 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3131 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 5335 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3132 (direkt/dynamisch unklar); tests/test_server.py:3133 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 5341 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3117 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 5369 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 5375 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 5384 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 5394 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6865 (direkt/dynamisch unklar); tests/test_server.py:6882 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 5434 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 5448 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 5461 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 5487 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 5513 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 5521 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 5529 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 5533 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 5571 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 5579 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 5586 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 5601 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 5613 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 5625 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 5632 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 5636 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 5669 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 5692 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 5711 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 5728 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 5736 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 5766 | `sync/` | P6 | offen | tests/test_audit_remediation.py:45 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:58 (direkt/dynamisch unklar); tests/test_audit_remediation.py:72 (direkt/dynamisch unklar); tests/test_server.py:6351 (direkt/dynamisch unklar); tests/test_server.py:6359 (direkt/dynamisch unklar); tests/test_server.py:6395 (direkt/dynamisch unklar); tests/test_server.py:6565 (direkt/dynamisch unklar); tests/test_server.py:6762 (direkt/dynamisch unklar); tests/test_server.py:6794 (direkt/dynamisch unklar); tests/test_server.py:6795 (direkt/dynamisch unklar); tests/test_server.py:6832 (direkt/dynamisch unklar); tests/test_server.py:6864 (direkt/dynamisch unklar); tests/test_server.py:6880 (direkt/dynamisch unklar); tests/test_server.py:6883 (direkt/dynamisch unklar); tests/test_server.py:6919 (direkt/dynamisch unklar); tests/test_server.py:6952 (direkt/dynamisch unklar); tests/test_server.py:6979 (direkt/dynamisch unklar); tests/test_server.py:6981 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 5822 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `_provider_error_body` | 5825 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 5833 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 5841 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 5853 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 5858 | `coach/context.py` | P7 | offen | tests/test_server.py:7877 (direkt/dynamisch unklar) |
| Funktion | `_log_http_request_started` | 5868 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 5881 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 5920 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 5939 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 6008 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 6042 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 6047 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 6074 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1809 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4257 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4349 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4473 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4488 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4572 (direkt/dynamisch unklar); tests/test_server.py:4615 (direkt/dynamisch unklar); tests/test_server.py:4652 (direkt/dynamisch unklar); tests/test_server.py:4685 (direkt/dynamisch unklar); tests/test_server.py:4706 (direkt/dynamisch unklar); tests/test_server.py:4719 (direkt/dynamisch unklar); tests/test_server.py:4759 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5389 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7389 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7783 (direkt/dynamisch unklar); tests/test_server.py:7801 (direkt/dynamisch unklar); tests/test_server.py:7819 (direkt/dynamisch unklar); tests/test_server.py:7853 (direkt/dynamisch unklar); tests/test_server.py:7870 (direkt/dynamisch unklar); tests/test_server.py:7994 (direkt/dynamisch unklar); tests/test_server.py:8030 (direkt/dynamisch unklar); tests/test_server.py:8058 (direkt/dynamisch unklar); tests/test_server.py:8079 (direkt/dynamisch unklar); tests/test_server.py:8435 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 6134 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 6146 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 6155 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 6163 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 6167 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 6173 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 6185 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 6190 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 6216 | `weather/` | P3 | offen | tests/test_server.py:1207 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 6226 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 6250 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 6265 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 6284 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 6299 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 6313 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 6334 | `weather/` | P3 | offen | tests/test_server.py:7432 (direkt/dynamisch unklar); tests/test_server.py:7439 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 6381 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 6397 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 6407 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 6428 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 6448 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 6452 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 6475 | `weather/` | P3 | offen | tests/test_audit_remediation.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:82 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1225 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1251 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1279 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1293 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1312 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1595 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 6487 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 6498 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 6525 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 6533 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 6546 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 6582 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 6601 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 6607 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 6629 | `weather/` | P3 | offen | tests/test_audit_remediation.py:147 (direkt/dynamisch unklar); tests/test_audit_remediation.py:148 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_server.py:1226 (direkt/dynamisch unklar); tests/test_server.py:1227 (direkt/dynamisch unklar); tests/test_server.py:1313 (direkt/dynamisch unklar); tests/test_server.py:1314 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar); tests/test_server.py:1605 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1622 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2869 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7394 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 6647 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 6665 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 6680 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 6687 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 6703 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 6731 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 6744 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 6764 | `sync/` | P6 | offen | tests/test_audit_remediation.py:149 (direkt/dynamisch unklar); tests/test_server.py:1294 (direkt/dynamisch unklar); tests/test_server.py:1295 (direkt/dynamisch unklar); tests/test_server.py:1296 (direkt/dynamisch unklar); tests/test_server.py:1582 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 6780 | `weather/` | P3 | offen | tests/test_server.py:7406 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 6792 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 6805 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 6810 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 6815 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 6819 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 6823 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 6831 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 6847 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 6866 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 6870 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 6879 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 6891 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 6912 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 6939 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 6954 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 6967 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2816 (direkt/dynamisch unklar); tests/test_server.py:2818 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 7005 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 7026 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 7046 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 7064 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2781 (direkt/dynamisch unklar); tests/test_server.py:2841 (direkt/dynamisch unklar); tests/test_server.py:2880 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 7074 | `providers/` | P2 | offen | tests/test_server.py:2842 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 7098 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 7118 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 7124 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 7147 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 7157 | `planning/` | P4 | offen | tests/test_server.py:2741 (direkt/dynamisch unklar); tests/test_server.py:3458 (direkt/dynamisch unklar); tests/test_server.py:6637 (direkt/dynamisch unklar); tests/test_server.py:7005 (direkt/dynamisch unklar); tests/test_server.py:7034 (direkt/dynamisch unklar); tests/test_server.py:7163 (direkt/dynamisch unklar); tests/test_server.py:7187 (direkt/dynamisch unklar); tests/test_server.py:7208 (direkt/dynamisch unklar); tests/test_server.py:7224 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 7195 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 7196 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 7201 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 7204 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 7213 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 7217 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 7226 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 7251 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 7258 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 7269 | `planning/competitions.py` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3688 (direkt/dynamisch unklar); tests/test_server.py:3705 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 7283 | `planning/competitions.py` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:2970 (direkt/dynamisch unklar); tests/test_server.py:3062 (direkt/dynamisch unklar); tests/test_server.py:3138 (direkt/dynamisch unklar); tests/test_server.py:3724 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 7306 | `planning/competitions.py` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 7319 | `planning/competitions.py` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3650 (direkt/dynamisch unklar); tests/test_server.py:3700 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 7346 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 7356 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 7366 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 7373 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 7391 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 7401 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 7414 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 7427 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 7442 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 7451 | `providers/` | P2 | offen | tests/test_server.py:3473 (direkt/dynamisch unklar); tests/test_server.py:3478 (direkt/dynamisch unklar); tests/test_server.py:3479 (direkt/dynamisch unklar); tests/test_server.py:3489 (direkt/dynamisch unklar); tests/test_server.py:3494 (direkt/dynamisch unklar); tests/test_server.py:4962 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 7466 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 7479 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 7503 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 7514 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 7529 | `planning/competitions.py` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1601 (direkt/dynamisch unklar); tests/test_server.py:1618 (direkt/dynamisch unklar); tests/test_server.py:2491 (direkt/dynamisch unklar); tests/test_server.py:2565 (direkt/dynamisch unklar); tests/test_server.py:2585 (direkt/dynamisch unklar); tests/test_server.py:2632 (direkt/dynamisch unklar); tests/test_server.py:2651 (direkt/dynamisch unklar); tests/test_server.py:2662 (direkt/dynamisch unklar); tests/test_server.py:2694 (direkt/dynamisch unklar); tests/test_server.py:3672 (direkt/dynamisch unklar); tests/test_server.py:3757 (direkt/dynamisch unklar); tests/test_server.py:3785 (direkt/dynamisch unklar); tests/test_server.py:3806 (direkt/dynamisch unklar); tests/test_server.py:3808 (direkt/dynamisch unklar); tests/test_server.py:3815 (direkt/dynamisch unklar); tests/test_server.py:419 (direkt/dynamisch unklar); tests/test_server.py:5473 (direkt/dynamisch unklar); tests/test_server.py:5483 (direkt/dynamisch unklar); tests/test_server.py:5511 (direkt/dynamisch unklar); tests/test_server.py:5756 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6239 (direkt/dynamisch unklar); tests/test_server.py:832 (direkt/dynamisch unklar); tests/test_server.py:865 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 7546 | `planning/competitions.py` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5477 (direkt/dynamisch unklar); tests/test_server.py:5488 (direkt/dynamisch unklar); tests/test_server.py:5504 (direkt/dynamisch unklar); tests/test_server.py:5516 (direkt/dynamisch unklar); tests/test_server.py:5532 (direkt/dynamisch unklar); tests/test_server.py:5555 (direkt/dynamisch unklar); tests/test_server.py:5577 (direkt/dynamisch unklar); tests/test_server.py:859 (direkt/dynamisch unklar); tests/test_server.py:887 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 7554 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 7562 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 7567 | `planning/competitions.py` | P4 | offen | tests/test_server.py:5479 (direkt/dynamisch unklar); tests/test_server.py:5489 (direkt/dynamisch unklar); tests/test_server.py:871 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 7584 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 7589 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 7601 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 7619 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 7648 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_server.py:1632 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 7660 | `planning/competitions.py` | P4 | offen | tests/test_server.py:2606 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 7677 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7671 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 7694 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 7719 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 7733 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 7742 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 7760 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 7774 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 7782 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 7800 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 7809 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 7823 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 7838 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 7855 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 7872 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 7896 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 7928 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 7954 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 7975 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 7983 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 8002 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 8025 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1609 (direkt/dynamisch unklar); tests/test_server.py:1626 (direkt/dynamisch unklar); tests/test_server.py:2500 (direkt/dynamisch unklar); tests/test_server.py:2574 (direkt/dynamisch unklar); tests/test_server.py:2590 (direkt/dynamisch unklar); tests/test_server.py:2604 (direkt/dynamisch unklar); tests/test_server.py:2611 (direkt/dynamisch unklar); tests/test_server.py:2637 (direkt/dynamisch unklar); tests/test_server.py:2656 (direkt/dynamisch unklar); tests/test_server.py:2666 (direkt/dynamisch unklar); tests/test_server.py:2703 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 8056 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 8067 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 8083 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 8098 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 8108 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 8147 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 8162 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 8170 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 8192 | `planning/` | P4 | offen | tests/test_audit_remediation.py:244 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2595 (direkt/dynamisch unklar); tests/test_server.py:2622 (direkt/dynamisch unklar); tests/test_server.py:2641 (direkt/dynamisch unklar); tests/test_server.py:2646 (direkt/dynamisch unklar); tests/test_server.py:2658 (direkt/dynamisch unklar); tests/test_server.py:2667 (direkt/dynamisch unklar); tests/test_server.py:2670 (direkt/dynamisch unklar); tests/test_server.py:2704 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 8222 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 8246 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1633 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 8250 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 8258 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 8274 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 8287 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 8292 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 8297 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 8306 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 8315 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 8337 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 8343 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 8347 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 8360 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 8374 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 8380 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 8393 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 8406 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 8427 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 8443 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 8453 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 8469 | `planning/` | P4 | offen | tests/test_server.py:2682 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 8492 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 8508 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 8511 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 8535 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 8544 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:2889 (direkt/dynamisch unklar); tests/test_server.py:3011 (direkt/dynamisch unklar); tests/test_server.py:3032 (direkt/dynamisch unklar); tests/test_server.py:3485 (direkt/dynamisch unklar); tests/test_server.py:389 (direkt/dynamisch unklar); tests/test_server.py:4825 (direkt/dynamisch unklar); tests/test_server.py:4847 (direkt/dynamisch unklar); tests/test_server.py:4903 (direkt/dynamisch unklar); tests/test_server.py:4920 (direkt/dynamisch unklar); tests/test_server.py:4938 (direkt/dynamisch unklar); tests/test_server.py:4956 (direkt/dynamisch unklar); tests/test_server.py:4977 (direkt/dynamisch unklar); tests/test_server.py:5000 (direkt/dynamisch unklar); tests/test_server.py:5045 (direkt/dynamisch unklar); tests/test_server.py:5067 (direkt/dynamisch unklar); tests/test_server.py:5090 (direkt/dynamisch unklar); tests/test_server.py:5106 (direkt/dynamisch unklar); tests/test_server.py:5123 (direkt/dynamisch unklar); tests/test_server.py:5186 (direkt/dynamisch unklar); tests/test_server.py:5248 (direkt/dynamisch unklar); tests/test_server.py:5257 (direkt/dynamisch unklar); tests/test_server.py:5415 (direkt/dynamisch unklar); tests/test_server.py:5446 (direkt/dynamisch unklar); tests/test_server.py:5609 (direkt/dynamisch unklar); tests/test_server.py:5639 (direkt/dynamisch unklar); tests/test_server.py:5657 (direkt/dynamisch unklar); tests/test_server.py:5662 (direkt/dynamisch unklar); tests/test_server.py:5671 (direkt/dynamisch unklar); tests/test_server.py:5675 (direkt/dynamisch unklar); tests/test_server.py:5680 (direkt/dynamisch unklar); tests/test_server.py:5689 (direkt/dynamisch unklar); tests/test_server.py:5708 (direkt/dynamisch unklar); tests/test_server.py:5711 (direkt/dynamisch unklar); tests/test_server.py:5737 (direkt/dynamisch unklar); tests/test_server.py:719 (direkt/dynamisch unklar); tests/test_server.py:7267 (direkt/dynamisch unklar); tests/test_server.py:742 (direkt/dynamisch unklar); tests/test_server.py:759 (direkt/dynamisch unklar); tests/test_server.py:785 (direkt/dynamisch unklar); tests/test_server.py:789 (direkt/dynamisch unklar); tests/test_server.py:892 (direkt/dynamisch unklar); tests/test_server.py:912 (direkt/dynamisch unklar); tests/test_server.py:916 (direkt/dynamisch unklar); tests/test_server.py:939 (direkt/dynamisch unklar); tests/test_server.py:987 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 8562 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2598 (direkt/dynamisch unklar); tests/test_server.py:2599 (direkt/dynamisch unklar); tests/test_server.py:2607 (direkt/dynamisch unklar); tests/test_server.py:2672 (direkt/dynamisch unklar); tests/test_server.py:2943 (direkt/dynamisch unklar); tests/test_server.py:2953 (direkt/dynamisch unklar); tests/test_server.py:2956 (direkt/dynamisch unklar); tests/test_server.py:2967 (direkt/dynamisch unklar); tests/test_server.py:2983 (direkt/dynamisch unklar); tests/test_server.py:3054 (direkt/dynamisch unklar); tests/test_server.py:3795 (direkt/dynamisch unklar); tests/test_server.py:3799 (direkt/dynamisch unklar); tests/test_server.py:3807 (direkt/dynamisch unklar); tests/test_server.py:3811 (direkt/dynamisch unklar); tests/test_server.py:4838 (direkt/dynamisch unklar); tests/test_server.py:4864 (direkt/dynamisch unklar); tests/test_server.py:4881 (direkt/dynamisch unklar); tests/test_server.py:4915 (direkt/dynamisch unklar); tests/test_server.py:4933 (direkt/dynamisch unklar); tests/test_server.py:4951 (direkt/dynamisch unklar); tests/test_server.py:4990 (direkt/dynamisch unklar); tests/test_server.py:5014 (direkt/dynamisch unklar); tests/test_server.py:5036 (direkt/dynamisch unklar); tests/test_server.py:5103 (direkt/dynamisch unklar); tests/test_server.py:5119 (direkt/dynamisch unklar); tests/test_server.py:5140 (direkt/dynamisch unklar); tests/test_server.py:5440 (direkt/dynamisch unklar); tests/test_server.py:5441 (direkt/dynamisch unklar); tests/test_server.py:5530 (direkt/dynamisch unklar); tests/test_server.py:5604 (direkt/dynamisch unklar); tests/test_server.py:5732 (direkt/dynamisch unklar); tests/test_server.py:5762 (direkt/dynamisch unklar); tests/test_server.py:6149 (direkt/dynamisch unklar); tests/test_server.py:782 (direkt/dynamisch unklar); tests/test_server.py:810 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 8574 | `planning/` | P4 | offen | tests/test_server.py:1010 (direkt/dynamisch unklar); tests/test_server.py:1013 (direkt/dynamisch unklar); tests/test_server.py:3555 (direkt/dynamisch unklar); tests/test_server.py:3766 (direkt/dynamisch unklar); tests/test_server.py:3828 (direkt/dynamisch unklar); tests/test_server.py:6178 (direkt/dynamisch unklar); tests/test_server.py:6215 (direkt/dynamisch unklar); tests/test_server.py:6259 (direkt/dynamisch unklar); tests/test_server.py:6418 (direkt/dynamisch unklar); tests/test_server.py:8594 (direkt/dynamisch unklar); tests/test_server.py:8684 (direkt/dynamisch unklar); tests/test_server.py:8685 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 8602 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3754 (direkt/dynamisch unklar); tests/test_server.py:552 (direkt/dynamisch unklar); tests/test_server.py:746 (direkt/dynamisch unklar); tests/test_server.py:964 (direkt/dynamisch unklar); tests/test_server.py:984 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 8625 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 8640 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 8657 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 8672 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 8695 | `planning/` | P4 | offen | tests/test_server.py:1445 (direkt/dynamisch unklar); tests/test_server.py:1775 (direkt/dynamisch unklar); tests/test_server.py:3540 (direkt/dynamisch unklar); tests/test_server.py:3546 (direkt/dynamisch unklar); tests/test_server.py:3570 (direkt/dynamisch unklar); tests/test_server.py:4179 (direkt/dynamisch unklar); tests/test_server.py:4195 (direkt/dynamisch unklar); tests/test_server.py:4213 (direkt/dynamisch unklar); tests/test_server.py:4228 (direkt/dynamisch unklar); tests/test_server.py:6232 (direkt/dynamisch unklar); tests/test_server.py:6432 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 8720 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3551 (direkt/dynamisch unklar); tests/test_server.py:3560 (direkt/dynamisch unklar); tests/test_server.py:3562 (direkt/dynamisch unklar); tests/test_server.py:3563 (direkt/dynamisch unklar); tests/test_server.py:3565 (direkt/dynamisch unklar); tests/test_server.py:3567 (direkt/dynamisch unklar); tests/test_server.py:3775 (direkt/dynamisch unklar); tests/test_server.py:3838 (direkt/dynamisch unklar); tests/test_server.py:4183 (direkt/dynamisch unklar); tests/test_server.py:4191 (direkt/dynamisch unklar); tests/test_server.py:4199 (direkt/dynamisch unklar); tests/test_server.py:4209 (direkt/dynamisch unklar); tests/test_server.py:4217 (direkt/dynamisch unklar); tests/test_server.py:4225 (direkt/dynamisch unklar); tests/test_server.py:4232 (direkt/dynamisch unklar); tests/test_server.py:6107 (direkt/dynamisch unklar); tests/test_server.py:6196 (direkt/dynamisch unklar); tests/test_server.py:6249 (direkt/dynamisch unklar); tests/test_server.py:6484 (direkt/dynamisch unklar); tests/test_server.py:8600 (direkt/dynamisch unklar); tests/test_server.py:980 (direkt/dynamisch unklar); tests/test_server.py:981 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 8727 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 8744 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 8745 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 8746 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 8747 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 8750 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 8757 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 8762 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 8772 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 8779 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1754 (direkt/dynamisch unklar); tests/test_server.py:1755 (direkt/dynamisch unklar); tests/test_server.py:1756 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 8806 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:307 (direkt/dynamisch unklar); tests/test_audit_remediation.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1764 (direkt/dynamisch unklar); tests/test_server.py:1765 (direkt/dynamisch unklar); tests/test_server.py:1770 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 8838 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1779 (direkt/dynamisch unklar); tests/test_server.py:1780 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 8866 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1930 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 8887 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 8907 | `activities/` | P3 | offen | tests/test_server.py:548 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 8948 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 8953 | `planning/` | P4 | offen | tests/test_server.py:2581 (direkt/dynamisch unklar); tests/test_server.py:2594 (direkt/dynamisch unklar); tests/test_server.py:2597 (direkt/dynamisch unklar); tests/test_server.py:2645 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2705 (direkt/dynamisch unklar); tests/test_server.py:2708 (direkt/dynamisch unklar); tests/test_server.py:2868 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2918 (direkt/dynamisch unklar); tests/test_server.py:2935 (direkt/dynamisch unklar); tests/test_server.py:3029 (direkt/dynamisch unklar); tests/test_server.py:3674 (direkt/dynamisch unklar); tests/test_server.py:3763 (direkt/dynamisch unklar); tests/test_server.py:3821 (direkt/dynamisch unklar); tests/test_server.py:4192 (direkt/dynamisch unklar); tests/test_server.py:4210 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 8958 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 8965 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 8976 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 8988 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 9013 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 9029 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 9037 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 9051 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 9063 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:2903 (direkt/dynamisch unklar); tests/test_server.py:2918 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 9082 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 9087 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 9104 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 9118 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 9125 | `calendar/` | P3 | offen | tests/test_server.py:3003 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 9140 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 9153 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 9166 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 9223 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 9240 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 9280 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 9287 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 9295 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 9303 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 9316 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 9326 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 9338 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 9367 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 9377 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 9399 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:325 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 9416 | `sync/` | P6 | offen | tests/test_server.py:3794 (direkt/dynamisch unklar); tests/test_server.py:3798 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 9421 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 9439 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 9446 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 9455 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 9470 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 9475 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 9481 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 9489 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 9501 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 9510 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 9527 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 9547 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 9550 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 9563 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 9575 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 9598 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 9618 | `planning/` | P4 | offen | tests/test_server.py:6002 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6031 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6044 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6064 (direkt/dynamisch unklar); tests/test_server.py:6143 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6167 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6208 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6226 (direkt/dynamisch unklar); tests/test_server.py:675 (Monkeypatch/getattr/sys.modules); tests/test_server.py:688 (Monkeypatch/getattr/sys.modules) |
| Funktion | `plan_library_workout_remote` | 9659 | `planning/` | P4 | offen | tests/test_server.py:6407 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 9663 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 9684 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 9699 | `sync/snapshots.py` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 9705 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 9712 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 9727 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 9742 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 9752 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 9758 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 9773 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 9781 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1449 (direkt/dynamisch unklar); tests/test_server.py:3558 (direkt/dynamisch unklar); tests/test_server.py:3561 (direkt/dynamisch unklar); tests/test_server.py:3564 (direkt/dynamisch unklar); tests/test_server.py:3566 (direkt/dynamisch unklar); tests/test_server.py:3572 (direkt/dynamisch unklar); tests/test_server.py:3574 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 9805 | `planning/` | P4 | offen | tests/test_server.py:6422 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 9824 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 9840 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 9852 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 9866 | `calendar/` | P3 | offen | tests/test_server.py:7884 (direkt/dynamisch unklar); tests/test_server.py:7894 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 9901 | `sync/status.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 9931 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 9949 | `sync/` | P6 | offen | tests/test_server.py:1931 (direkt/dynamisch unklar); tests/test_server.py:2176 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 9953 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 9968 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 9987 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 10000 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 10014 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 10033 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 10046 | `sync/` | P6 | offen | tests/test_server.py:3773 (direkt/dynamisch unklar); tests/test_server.py:3779 (direkt/dynamisch unklar); tests/test_server.py:3835 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 10061 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 10069 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 10093 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 10098 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 10121 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 10128 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 10153 | `planning/` | P4 | offen | tests/test_server.py:4185 (direkt/dynamisch unklar); tests/test_server.py:4205 (direkt/dynamisch unklar); tests/test_server.py:4220 (direkt/dynamisch unklar); tests/test_server.py:4234 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 10167 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 10176 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 10187 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 10196 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 10208 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 10221 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 10225 | `sync/` | P6 | offen | tests/test_server.py:6471 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8692 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 10238 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 10251 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 10255 | `sync/` | P6 | offen | tests/test_server.py:326 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 10274 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 10289 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 10304 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 10320 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 10333 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 10350 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 10361 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 10377 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 10395 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 10414 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 10437 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 10452 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 10461 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 10482 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 10500 | `planning/calendar.py` | P3 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 10524 | `planning/` | P4 | offen | tests/test_server.py:2639 (direkt/dynamisch unklar); tests/test_server.py:2657 (direkt/dynamisch unklar); tests/test_server.py:2940 (direkt/dynamisch unklar); tests/test_server.py:2954 (direkt/dynamisch unklar); tests/test_server.py:2984 (direkt/dynamisch unklar); tests/test_server.py:3016 (direkt/dynamisch unklar); tests/test_server.py:3023 (direkt/dynamisch unklar); tests/test_server.py:3025 (direkt/dynamisch unklar); tests/test_server.py:3027 (direkt/dynamisch unklar); tests/test_server.py:3037 (direkt/dynamisch unklar); tests/test_server.py:3039 (direkt/dynamisch unklar); tests/test_server.py:3488 (direkt/dynamisch unklar); tests/test_server.py:3762 (direkt/dynamisch unklar); tests/test_server.py:3810 (direkt/dynamisch unklar); tests/test_server.py:4961 (direkt/dynamisch unklar); tests/test_server.py:5661 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 10550 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 10561 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 10572 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 10582 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 10588 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 10599 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 10611 | `planning/` | P4 | offen | tests/test_server.py:2986 (direkt/dynamisch unklar); tests/test_server.py:2989 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 10629 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:92 (direkt/dynamisch unklar); tests/test_server.py:1722 (direkt/dynamisch unklar); tests/test_server.py:1723 (direkt/dynamisch unklar); tests/test_server.py:2867 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5340 (direkt/dynamisch unklar); tests/test_server.py:5342 (direkt/dynamisch unklar); tests/test_server.py:6476 (direkt/dynamisch unklar); tests/test_server.py:6499 (direkt/dynamisch unklar); tests/test_server.py:7656 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 10634 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:110 (direkt/dynamisch unklar); tests/test_provider_review.py:230 (direkt/dynamisch unklar); tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_provider_review.py:63 (direkt/dynamisch unklar); tests/test_provider_review.py:87 (direkt/dynamisch unklar); tests/test_server.py:1477 (direkt/dynamisch unklar); tests/test_server.py:1702 (direkt/dynamisch unklar); tests/test_server.py:1739 (direkt/dynamisch unklar); tests/test_server.py:1747 (direkt/dynamisch unklar); tests/test_server.py:1787 (direkt/dynamisch unklar); tests/test_server.py:2395 (direkt/dynamisch unklar); tests/test_server.py:2420 (direkt/dynamisch unklar); tests/test_server.py:3514 (direkt/dynamisch unklar); tests/test_server.py:3579 (direkt/dynamisch unklar); tests/test_server.py:4201 (direkt/dynamisch unklar); tests/test_server.py:503 (direkt/dynamisch unklar); tests/test_server.py:5294 (direkt/dynamisch unklar); tests/test_server.py:5335 (direkt/dynamisch unklar); tests/test_server.py:6488 (direkt/dynamisch unklar); tests/test_server.py:7269 (direkt/dynamisch unklar); tests/test_server.py:7647 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 10644 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 10670 | `sync/` | P6 | offen | tests/test_server.py:1062 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 10695 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 10700 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 10710 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 10718 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 10749 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 10771 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 10782 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 10796 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 10818 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 10835 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 10869 | `planning/` | P4 | offen | tests/test_server.py:2931 (direkt/dynamisch unklar); tests/test_server.py:2933 (direkt/dynamisch unklar); tests/test_server.py:2941 (direkt/dynamisch unklar); tests/test_server.py:2952 (direkt/dynamisch unklar); tests/test_server.py:2955 (direkt/dynamisch unklar); tests/test_server.py:2963 (direkt/dynamisch unklar); tests/test_server.py:2982 (direkt/dynamisch unklar); tests/test_server.py:2985 (direkt/dynamisch unklar); tests/test_server.py:2988 (direkt/dynamisch unklar); tests/test_server.py:3472 (direkt/dynamisch unklar); tests/test_server.py:3477 (direkt/dynamisch unklar); tests/test_server.py:5589 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 10917 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 10933 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 10945 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 10957 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 10962 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 10972 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 10979 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 10986 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 10997 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 11012 | `sync/` | P6 | offen | tests/test_server.py:6334 (direkt/dynamisch unklar); tests/test_server.py:6472 (direkt/dynamisch unklar); tests/test_server.py:6498 (direkt/dynamisch unklar); tests/test_server.py:6508 (direkt/dynamisch unklar); tests/test_server.py:6584 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 11047 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 11062 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 11091 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 11120 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 11140 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 11157 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 11214 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 11229 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 11240 | `sync/` | P6 | offen | tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6003 (direkt/dynamisch unklar); tests/test_server.py:6018 (direkt/dynamisch unklar); tests/test_server.py:6033 (direkt/dynamisch unklar); tests/test_server.py:6046 (direkt/dynamisch unklar); tests/test_server.py:6075 (direkt/dynamisch unklar); tests/test_server.py:6104 (direkt/dynamisch unklar); tests/test_server.py:6144 (direkt/dynamisch unklar); tests/test_server.py:6145 (direkt/dynamisch unklar); tests/test_server.py:6169 (direkt/dynamisch unklar); tests/test_server.py:6171 (direkt/dynamisch unklar); tests/test_server.py:6191 (direkt/dynamisch unklar); tests/test_server.py:6209 (direkt/dynamisch unklar); tests/test_server.py:6326 (direkt/dynamisch unklar); tests/test_server.py:633 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6427 (direkt/dynamisch unklar); tests/test_server.py:678 (direkt/dynamisch unklar); tests/test_server.py:691 (direkt/dynamisch unklar); tests/test_server.py:7700 (direkt/dynamisch unklar); tests/test_server.py:7967 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 11274 | `performance/` | P3 | offen | tests/test_provider_review.py:77 (direkt/dynamisch unklar); tests/test_server.py:609 (Monkeypatch/getattr/sys.modules); tests/test_server.py:622 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7261 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 11298 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 11305 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 11312 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 11330 | `activities/` | P3 | offen | tests/test_server.py:5208 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 11342 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 11359 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 11372 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 11389 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 11410 | `performance/` | P3 | offen | tests/test_server.py:7158 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 11419 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 11431 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 11447 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 11462 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 11498 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 11508 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 11522 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 11538 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 11555 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 11565 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 11576 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 11590 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 11602 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 11607 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 11639 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 11648 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 11654 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 11661 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 11675 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 11688 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 11692 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 11721 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 11728 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 11765 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 11785 | `performance/` | P3 | offen | tests/test_server.py:3233 (direkt/dynamisch unklar); tests/test_server.py:3242 (direkt/dynamisch unklar); tests/test_server.py:3350 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 11814 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 11828 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 11844 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 11852 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 11862 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 11889 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 11904 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 11927 | `performance/activity_validation.py` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 11945 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 11977 | `activities/` | P3 | offen | tests/test_server.py:7057 (direkt/dynamisch unklar); tests/test_server.py:7079 (direkt/dynamisch unklar); tests/test_server.py:7085 (direkt/dynamisch unklar); tests/test_server.py:7094 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 12022 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 12055 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 12076 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 12088 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 12108 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 12121 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 12152 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 12182 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 12193 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 12236 | `performance/` | P3 | offen | tests/test_provider_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:3373 (direkt/dynamisch unklar); tests/test_server.py:3403 (direkt/dynamisch unklar); tests/test_server.py:3432 (direkt/dynamisch unklar); tests/test_server.py:3453 (direkt/dynamisch unklar); tests/test_server.py:3465 (direkt/dynamisch unklar); tests/test_server.py:6996 (direkt/dynamisch unklar); tests/test_server.py:7018 (direkt/dynamisch unklar); tests/test_server.py:7045 (direkt/dynamisch unklar); tests/test_server.py:7114 (direkt/dynamisch unklar); tests/test_server.py:7128 (direkt/dynamisch unklar); tests/test_server.py:7144 (direkt/dynamisch unklar); tests/test_server.py:7175 (direkt/dynamisch unklar); tests/test_server.py:7196 (direkt/dynamisch unklar); tests/test_server.py:7218 (direkt/dynamisch unklar); tests/test_server.py:7238 (direkt/dynamisch unklar); tests/test_server.py:7244 (direkt/dynamisch unklar); tests/test_server.py:7248 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 12307 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 12321 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 12325 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 12329 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 12334 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 12338 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 12342 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 12346 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 12350 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 12369 | `planning/` | P4 | offen | tests/test_server.py:5198 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 12388 | `coach/context.py` | P7 | offen | tests/test_server.py:5190 (direkt/dynamisch unklar); tests/test_server.py:5227 (direkt/dynamisch unklar); tests/test_server.py:5228 (direkt/dynamisch unklar); tests/test_server.py:5249 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 12434 | `coach/context.py` | P7 | offen | tests/test_server.py:1596 (direkt/dynamisch unklar); tests/test_server.py:1670 (direkt/dynamisch unklar); tests/test_server.py:2409 (direkt/dynamisch unklar); tests/test_server.py:3186 (direkt/dynamisch unklar); tests/test_server.py:5270 (direkt/dynamisch unklar); tests/test_server.py:5276 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6669 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 12499 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 12517 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 12527 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 12544 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:248 (direkt/dynamisch unklar); tests/test_provider_review.py:282 (direkt/dynamisch unklar); tests/test_server.py:3552 (direkt/dynamisch unklar); tests/test_server.py:5266 (direkt/dynamisch unklar); tests/test_server.py:5277 (direkt/dynamisch unklar); tests/test_server.py:5278 (direkt/dynamisch unklar); tests/test_server.py:5295 (direkt/dynamisch unklar); tests/test_server.py:5306 (direkt/dynamisch unklar); tests/test_server.py:5338 (direkt/dynamisch unklar); tests/test_server.py:6647 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 12584 | `coach/context.py` | P7 | offen | tests/test_server.py:5160 (direkt/dynamisch unklar); tests/test_server.py:5300 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 12640 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 12670 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_validate_openai_response` | 12680 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8423 (direkt/dynamisch unklar); tests/test_server.py:8426 (direkt/dynamisch unklar); tests/test_server.py:8429 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 12720 | `providers/` | P2 | offen | tests/test_server.py:4519 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4760 (direkt/dynamisch unklar); tests/test_server.py:5383 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5392 (direkt/dynamisch unklar); tests/test_server.py:6002 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7259 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8108 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8436 (direkt/dynamisch unklar) |
| Funktion | `transcribe_audio` | 12746 | `providers/` | P2 | offen | tests/test_server.py:4489 (direkt/dynamisch unklar); tests/test_server.py:4737 (direkt/dynamisch unklar); tests/test_server.py:4792 (direkt/dynamisch unklar); tests/test_server.py:4794 (direkt/dynamisch unklar) |
| Funktion | `_gemini_content_has_function_response` | 12798 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 12803 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 12810 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 12821 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 12837 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 12849 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4412 (direkt/dynamisch unklar); tests/test_server.py:4544 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 12857 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 12869 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 12885 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 12901 | `coach/conversation.py` | P7 | offen | tests/test_server.py:4423 (direkt/dynamisch unklar); tests/test_server.py:4428 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 12923 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_request_history` | 12945 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_last_user_text` | 12958 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_call_names` | 12965 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_gemini_request_payload` | 12973 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4440 (direkt/dynamisch unklar); tests/test_server.py:4453 (direkt/dynamisch unklar); tests/test_server.py:4523 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 13006 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 13037 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 13076 | `providers/` | P2 | offen | tests/test_server.py:4258 (direkt/dynamisch unklar); tests/test_server.py:4260 (direkt/dynamisch unklar); tests/test_server.py:4350 (direkt/dynamisch unklar); tests/test_server.py:4353 (direkt/dynamisch unklar); tests/test_server.py:4475 (direkt/dynamisch unklar); tests/test_server.py:4519 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 13083 | `providers/` | P2 | offen | tests/test_server.py:4331 (direkt/dynamisch unklar) |
| Funktion | `request_ai_provider` | 13195 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 13200 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4520 (direkt/dynamisch unklar); tests/test_server.py:5384 (direkt/dynamisch unklar); tests/test_server.py:5775 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5797 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8109 (direkt/dynamisch unklar) |
| Funktion | `retrieve_openai_response` | 13226 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 13241 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 13259 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5783 (direkt/dynamisch unklar); tests/test_server.py:5802 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 13300 | `coach/context.py` | P7 | offen | tests/test_server.py:6058 (direkt/dynamisch unklar) |
| Funktion | `_log_openai_stream_failure` | 13305 | `observability.py` | P1 | offen | tests/test_server.py:8257 (direkt/dynamisch unklar); tests/test_server.py:8268 (direkt/dynamisch unklar) |
| Funktion | `_capture_openai_stream_failure` | 13324 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 13338 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 13350 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 13361 | `providers/` | P2 | offen | tests/test_server.py:8093 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 13400 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 13422 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 13443 | `providers/` | P2 | offen | tests/test_server.py:4784 (direkt/dynamisch unklar); tests/test_server.py:8129 (direkt/dynamisch unklar); tests/test_server.py:8170 (direkt/dynamisch unklar); tests/test_server.py:8202 (direkt/dynamisch unklar); tests/test_server.py:8218 (direkt/dynamisch unklar); tests/test_server.py:8245 (direkt/dynamisch unklar); tests/test_server.py:8298 (direkt/dynamisch unklar); tests/test_server.py:8307 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 13542 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4302 (direkt/dynamisch unklar); tests/test_server.py:5898 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8308 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 13571 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:262 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 13590 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 13603 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 13621 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 13634 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 13640 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 13648 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:308 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4553 (direkt/dynamisch unklar); tests/test_server.py:5406 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 13657 | `providers/` | P2 | offen | tests/test_server.py:4242 (direkt/dynamisch unklar); tests/test_server.py:4274 (direkt/dynamisch unklar); tests/test_server.py:4308 (direkt/dynamisch unklar); tests/test_server.py:4519 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 13661 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 13662 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 13665 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 13669 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 13682 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 13707 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 13731 | `activities/` | P3 | offen | tests/test_server.py:7650 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 13751 | `coach/context.py` | P7 | offen | tests/test_server.py:8558 (direkt/dynamisch unklar); tests/test_server.py:8569 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 13773 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 13782 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 13804 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8585 (direkt/dynamisch unklar); tests/test_server.py:8597 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 13828 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 13837 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8586 (direkt/dynamisch unklar); tests/test_server.py:8598 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 13866 | `coach/context.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 13870 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:278 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5923 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 13887 | `coach/context.py` | P7 | offen | tests/test_server.py:5952 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 13891 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:5943 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 13903 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 13920 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 13947 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 13956 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 13973 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 14025 | `sync/` | P6 | offen | tests/test_audit_remediation.py:269 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4533 (direkt/dynamisch unklar); tests/test_server.py:5809 (direkt/dynamisch unklar); tests/test_server.py:5837 (direkt/dynamisch unklar); tests/test_server.py:5858 (direkt/dynamisch unklar); tests/test_server.py:5885 (direkt/dynamisch unklar); tests/test_server.py:5912 (direkt/dynamisch unklar); tests/test_server.py:5936 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 14058 | `coach/context.py` | P7 | offen | tests/test_server.py:5856 (direkt/dynamisch unklar); tests/test_server.py:8316 (direkt/dynamisch unklar); tests/test_server.py:8319 (direkt/dynamisch unklar); tests/test_server.py:8333 (direkt/dynamisch unklar); tests/test_server.py:8354 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8381 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8394 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 14072 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 14087 | `coach/context.py` | P7 | offen | tests/test_server.py:5872 (direkt/dynamisch unklar); tests/test_server.py:8356 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8383 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 14096 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 14105 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 14117 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 14134 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_server.py:8322 (direkt/dynamisch unklar); tests/test_server.py:8324 (direkt/dynamisch unklar); tests/test_server.py:8398 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 14142 | `coach/context.py` | P7 | offen | tests/test_server.py:5880 (direkt/dynamisch unklar); tests/test_server.py:8328 (direkt/dynamisch unklar); tests/test_server.py:8339 (direkt/dynamisch unklar); tests/test_server.py:8355 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8403 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 14149 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 14150 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 14151 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 14151 | `coach/` | P7 | offen | tests/test_server.py:413 (direkt/dynamisch unklar); tests/test_server.py:469 (direkt/dynamisch unklar); tests/test_server.py:4800 (direkt/dynamisch unklar); tests/test_server.py:4803 (direkt/dynamisch unklar); tests/test_server.py:5153 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 14151 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 14151 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 14160 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 14168 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 14172 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 14177 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 14188 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 14213 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 14232 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 14244 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:2932 (direkt/dynamisch unklar); tests/test_server.py:2934 (direkt/dynamisch unklar); tests/test_server.py:5419 (direkt/dynamisch unklar); tests/test_server.py:5455 (direkt/dynamisch unklar); tests/test_server.py:5478 (direkt/dynamisch unklar); tests/test_server.py:5480 (direkt/dynamisch unklar); tests/test_server.py:5496 (direkt/dynamisch unklar); tests/test_server.py:5503 (direkt/dynamisch unklar); tests/test_server.py:5517 (direkt/dynamisch unklar); tests/test_server.py:5540 (direkt/dynamisch unklar); tests/test_server.py:5565 (direkt/dynamisch unklar); tests/test_server.py:5594 (direkt/dynamisch unklar); tests/test_server.py:5614 (direkt/dynamisch unklar); tests/test_server.py:5666 (direkt/dynamisch unklar); tests/test_server.py:5679 (direkt/dynamisch unklar); tests/test_server.py:5685 (direkt/dynamisch unklar); tests/test_server.py:5714 (direkt/dynamisch unklar); tests/test_server.py:5741 (direkt/dynamisch unklar); tests/test_server.py:5744 (direkt/dynamisch unklar); tests/test_server.py:5765 (direkt/dynamisch unklar); tests/test_server.py:750 (direkt/dynamisch unklar); tests/test_server.py:763 (direkt/dynamisch unklar); tests/test_server.py:839 (direkt/dynamisch unklar); tests/test_server.py:874 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 14267 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 14274 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 14281 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 14299 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 14309 | `coach/context.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:336 (direkt/dynamisch unklar); tests/test_server.py:361 (direkt/dynamisch unklar); tests/test_server.py:4459 (direkt/dynamisch unklar); tests/test_server.py:5400 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 14322 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 14331 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 14342 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 14374 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 14400 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 14420 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 14444 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 14456 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 14469 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 14483 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 14491 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 14502 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 14524 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 14534 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 14548 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 14560 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 14574 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 14582 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 14595 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 14604 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 14626 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 14644 | `planning/` | P4 | offen | tests/test_server.py:4830 (direkt/dynamisch unklar); tests/test_server.py:4852 (direkt/dynamisch unklar); tests/test_server.py:4871 (direkt/dynamisch unklar); tests/test_server.py:4893 (direkt/dynamisch unklar); tests/test_server.py:4908 (direkt/dynamisch unklar); tests/test_server.py:4924 (direkt/dynamisch unklar); tests/test_server.py:4942 (direkt/dynamisch unklar); tests/test_server.py:4964 (direkt/dynamisch unklar); tests/test_server.py:4982 (direkt/dynamisch unklar); tests/test_server.py:5005 (direkt/dynamisch unklar); tests/test_server.py:5049 (direkt/dynamisch unklar); tests/test_server.py:5074 (direkt/dynamisch unklar); tests/test_server.py:5095 (direkt/dynamisch unklar); tests/test_server.py:5110 (direkt/dynamisch unklar); tests/test_server.py:5129 (direkt/dynamisch unklar); tests/test_server.py:5146 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 14655 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 14665 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 14682 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 14693 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 14723 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 14741 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 14747 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 14760 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 14778 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 14794 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 14807 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 14821 | `planning/` | P4 | offen | tests/test_server.py:5520 (direkt/dynamisch unklar); tests/test_server.py:5567 (direkt/dynamisch unklar); tests/test_server.py:5595 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 14855 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:1021 (direkt/dynamisch unklar); tests/test_server.py:1030 (direkt/dynamisch unklar); tests/test_server.py:394 (direkt/dynamisch unklar); tests/test_server.py:425 (direkt/dynamisch unklar); tests/test_server.py:8691 (direkt/dynamisch unklar); tests/test_server.py:943 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 14868 | `sync/reconcile.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 14880 | `sync/reconcile.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 14895 | `sync/reconcile.py` | P6 | offen | tests/test_server.py:434 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 14907 | `sync/reconcile.py` | P6 | offen | tests/test_server.py:704 (direkt/dynamisch unklar); tests/test_server.py:714 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 14937 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 14945 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 14952 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 14974 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 14981 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 14987 | `coach/context.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 15005 | `coach/context.py` | P7 | offen | tests/test_server.py:458 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 15033 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 15042 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 15069 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 15095 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 15100 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 15106 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 15120 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 15127 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 15135 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 15142 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 15151 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 15158 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 15171 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 15194 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 15208 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 15222 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 15250 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 15266 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 15285 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 15305 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 15327 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 15343 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 15360 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 15395 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 15407 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 15422 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 15442 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 15468 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 15486 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 15494 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 15515 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 15542 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 15566 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 15593 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 15614 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:1023 (direkt/dynamisch unklar); tests/test_server.py:348 (direkt/dynamisch unklar); tests/test_server.py:380 (direkt/dynamisch unklar); tests/test_server.py:404 (direkt/dynamisch unklar); tests/test_server.py:437 (direkt/dynamisch unklar); tests/test_server.py:459 (direkt/dynamisch unklar); tests/test_server.py:484 (direkt/dynamisch unklar); tests/test_server.py:491 (direkt/dynamisch unklar); tests/test_server.py:5028 (direkt/dynamisch unklar); tests/test_server.py:531 (direkt/dynamisch unklar); tests/test_server.py:5425 (direkt/dynamisch unklar); tests/test_server.py:5461 (direkt/dynamisch unklar); tests/test_server.py:5546 (direkt/dynamisch unklar); tests/test_server.py:560 (direkt/dynamisch unklar); tests/test_server.py:5620 (direkt/dynamisch unklar); tests/test_server.py:5644 (direkt/dynamisch unklar); tests/test_server.py:5649 (direkt/dynamisch unklar); tests/test_server.py:566 (direkt/dynamisch unklar); tests/test_server.py:5698 (direkt/dynamisch unklar); tests/test_server.py:570 (direkt/dynamisch unklar); tests/test_server.py:5720 (direkt/dynamisch unklar); tests/test_server.py:587 (direkt/dynamisch unklar); tests/test_server.py:591 (direkt/dynamisch unklar); tests/test_server.py:728 (direkt/dynamisch unklar); tests/test_server.py:770 (direkt/dynamisch unklar); tests/test_server.py:799 (direkt/dynamisch unklar); tests/test_server.py:818 (direkt/dynamisch unklar); tests/test_server.py:847 (direkt/dynamisch unklar); tests/test_server.py:880 (direkt/dynamisch unklar); tests/test_server.py:900 (direkt/dynamisch unklar); tests/test_server.py:927 (direkt/dynamisch unklar); tests/test_server.py:953 (direkt/dynamisch unklar); tests/test_server.py:972 (direkt/dynamisch unklar); tests/test_server.py:998 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 15656 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 15660 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 15673 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8705 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 15685 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 15704 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 15720 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 15731 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 15753 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 15768 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 15786 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 15816 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 15822 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 15836 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 15846 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 15859 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 15872 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 15889 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 15902 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5758 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 15929 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 15946 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 15951 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 15960 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 15974 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 15987 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 15997 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 16010 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 16031 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 16054 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 16065 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 16074 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 16086 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 16100 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 16108 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 16123 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 16143 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 16167 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 16181 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 16192 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 16217 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 16233 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 16248 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 16305 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 16333 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 16363 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 16379 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 16399 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 16413 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 16425 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 16435 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 16486 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 16548 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 16552 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 16557 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 16575 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 16594 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 16604 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 16630 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 16668 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 16694 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 16719 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 16750 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 16790 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 16820 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 16840 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 16898 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 16902 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 16918 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 16934 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 16966 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 17010 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 17026 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 17045 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 17071 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 17148 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 17153 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 17162 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 17167 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 17194 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 17212 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 17241 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 17260 | `coach/service.py` | P7 | offen | tests/test_server.py:4361 (direkt/dynamisch unklar); tests/test_server.py:4376 (direkt/dynamisch unklar); tests/test_server.py:4390 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 17270 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 17285 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 17317 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 17332 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4463 (direkt/dynamisch unklar); tests/test_server.py:5411 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 17345 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5816 (direkt/dynamisch unklar); tests/test_server.py:5819 (direkt/dynamisch unklar); tests/test_server.py:8332 (direkt/dynamisch unklar); tests/test_server.py:8335 (direkt/dynamisch unklar); tests/test_server.py:8336 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 17364 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 17377 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 17401 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 17417 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 17428 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 17443 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:263 (direkt/dynamisch unklar); tests/test_audit_remediation.py:278 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:301 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:147 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5845 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5869 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5901 (direkt/dynamisch unklar); tests/test_server.py:5964 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 17467 | `sync/` | P6 | offen | tests/test_server.py:4539 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 17508 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:270 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4538 (direkt/dynamisch unklar); tests/test_server.py:5843 (direkt/dynamisch unklar); tests/test_server.py:5862 (direkt/dynamisch unklar); tests/test_server.py:5889 (direkt/dynamisch unklar); tests/test_server.py:5918 (direkt/dynamisch unklar); tests/test_server.py:5942 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 17533 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 17559 | `coach/authorization.py` | P7 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 17569 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 17573 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 17581 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 17587 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 17597 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 17614 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 17645 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 17667 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 17682 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:279 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:148 (direkt/dynamisch unklar); tests/test_server.py:5846 (direkt/dynamisch unklar); tests/test_server.py:5870 (direkt/dynamisch unklar); tests/test_server.py:5924 (direkt/dynamisch unklar); tests/test_server.py:5967 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 17703 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 17718 | `coach/authorization.py` | P7 | offen | tests/test_server.py:256 (direkt/dynamisch unklar) |
| Funktion | `local_now` | 17729 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:1600 (direkt/dynamisch unklar); tests/test_server.py:1616 (direkt/dynamisch unklar); tests/test_server.py:1617 (direkt/dynamisch unklar); tests/test_server.py:1638 (direkt/dynamisch unklar); tests/test_server.py:1656 (direkt/dynamisch unklar); tests/test_server.py:1675 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1701 (direkt/dynamisch unklar); tests/test_server.py:1738 (direkt/dynamisch unklar); tests/test_server.py:1746 (direkt/dynamisch unklar); tests/test_server.py:1786 (direkt/dynamisch unklar); tests/test_server.py:2467 (direkt/dynamisch unklar); tests/test_server.py:2533 (direkt/dynamisch unklar); tests/test_server.py:2592 (direkt/dynamisch unklar); tests/test_server.py:2602 (direkt/dynamisch unklar); tests/test_server.py:2780 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2840 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2870 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2879 (direkt/dynamisch unklar); tests/test_server.py:3367 (direkt/dynamisch unklar); tests/test_server.py:3386 (direkt/dynamisch unklar); tests/test_server.py:3418 (direkt/dynamisch unklar); tests/test_server.py:3443 (direkt/dynamisch unklar); tests/test_server.py:3533 (direkt/dynamisch unklar); tests/test_server.py:3534 (direkt/dynamisch unklar); tests/test_server.py:3578 (direkt/dynamisch unklar); tests/test_server.py:5168 (direkt/dynamisch unklar); tests/test_server.py:5217 (direkt/dynamisch unklar); tests/test_server.py:5234 (direkt/dynamisch unklar); tests/test_server.py:5256 (direkt/dynamisch unklar); tests/test_server.py:5283 (direkt/dynamisch unklar); tests/test_server.py:5315 (direkt/dynamisch unklar); tests/test_server.py:555 (direkt/dynamisch unklar); tests/test_server.py:6007 (direkt/dynamisch unklar); tests/test_server.py:7341 (direkt/dynamisch unklar); tests/test_server.py:7659 (direkt/dynamisch unklar); tests/test_server.py:8433 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 17738 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:154 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1970 (direkt/dynamisch unklar); tests/test_server.py:1971 (direkt/dynamisch unklar); tests/test_server.py:1972 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 17746 | `sync/daily.py` | P6 | offen | tests/test_server.py:1969 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 17754 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 17759 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 17770 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 17782 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4047 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 17785 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 17792 | `coach/authorization.py` | P7 | offen | tests/test_server.py:4045 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 17809 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 17815 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 17823 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 17835 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:302 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 17867 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 17888 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 17902 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 17915 | `coach/authorization.py` | P7 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 17934 | `http_api/bootstrap.py` | P10 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 17968 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1691 (direkt/dynamisch unklar); tests/test_server.py:1796 (direkt/dynamisch unklar); tests/test_server.py:1810 (direkt/dynamisch unklar); tests/test_server.py:1853 (direkt/dynamisch unklar); tests/test_server.py:1935 (direkt/dynamisch unklar); tests/test_server.py:8480 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 18042 | `http_api/` | P10 | offen | tests/test_server.py:1230 (direkt/dynamisch unklar); tests/test_server.py:2872 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 18078 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 18083 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 18087 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:98 (direkt/dynamisch unklar); tests/test_server.py:1280 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 18094 | `http_api/` | P10 | offen | tests/test_server.py:1252 (direkt/dynamisch unklar); tests/test_server.py:1260 (direkt/dynamisch unklar); tests/test_server.py:1683 (direkt/dynamisch unklar); tests/test_server.py:1692 (direkt/dynamisch unklar); tests/test_server.py:1741 (direkt/dynamisch unklar); tests/test_server.py:2406 (direkt/dynamisch unklar); tests/test_server.py:3583 (direkt/dynamisch unklar); tests/test_server.py:7270 (direkt/dynamisch unklar); tests/test_server.py:8480 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 18206 | `diagnostics/report.py` | P9 | offen | tests/test_server.py:7804 (direkt/dynamisch unklar); tests/test_server.py:7856 (direkt/dynamisch unklar); tests/test_server.py:7970 (direkt/dynamisch unklar); tests/test_server.py:8001 (direkt/dynamisch unklar); tests/test_server.py:8176 (direkt/dynamisch unklar); tests/test_server.py:8252 (direkt/dynamisch unklar); tests/test_server.py:8542 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 18223 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 18239 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 18260 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 18274 | `diagnostics/report.py` | P9 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 18290 | `diagnostics/report.py` | P9 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 18299 | `diagnostics/report.py` | P9 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7719 (direkt/dynamisch unklar); tests/test_server.py:7721 (direkt/dynamisch unklar); tests/test_server.py:7722 (direkt/dynamisch unklar); tests/test_server.py:7769 (direkt/dynamisch unklar); tests/test_server.py:7832 (direkt/dynamisch unklar); tests/test_server.py:7847 (direkt/dynamisch unklar); tests/test_server.py:8659 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 18362 | `privacy.py` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1463 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 18412 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 18413 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 18437 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 18441 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 18452 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 18456 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 18466 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 18474 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:187 (direkt/dynamisch unklar); tests/test_server.py:1478 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 18613 | `db/manager.py` | P1 | offen | tests/test_server.py:6536 (direkt/dynamisch unklar); tests/test_server.py:6549 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 18616 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 18629 | `backup/` | P9 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_server.py:6525 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 18638 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 18659 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1506 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 18670 | `backup/` | P9 | offen | tests/test_audit_remediation.py:293 (direkt/dynamisch unklar); tests/test_server.py:6526 (direkt/dynamisch unklar); tests/test_server.py:6542 (direkt/dynamisch unklar); tests/test_server.py:6555 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 18675 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 18684 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 18701 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 18713 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 18731 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 18738 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 18759 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1546 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4552 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5405 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8605 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 18772 | `coach/authorization.py` | P7 | offen | tests/test_server.py:1555 (direkt/dynamisch unklar); tests/test_server.py:1559 (direkt/dynamisch unklar); tests/test_server.py:1565 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 18787 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 18794 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 18801 | `privacy.py` | P9 | offen | tests/test_server.py:1558 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 18816 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:103 (direkt/dynamisch unklar); tests/test_provider_review.py:116 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (direkt/dynamisch unklar); tests/test_provider_review.py:146 (direkt/dynamisch unklar); tests/test_provider_review.py:164 (direkt/dynamisch unklar); tests/test_server.py:1547 (direkt/dynamisch unklar); tests/test_server.py:1563 (direkt/dynamisch unklar); tests/test_server.py:8606 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 18845 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 18846 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 18847 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 18848 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 18849 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 18850 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1378 (direkt/dynamisch unklar); tests/test_server.py:1386 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 18851 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1383 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 18852 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 18853 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 18854 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 18855 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7934 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 18858 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 18862 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:185 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7936 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 18887 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 18896 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1342 (direkt/dynamisch unklar); tests/test_server.py:1371 (direkt/dynamisch unklar); tests/test_server.py:1374 (direkt/dynamisch unklar); tests/test_server.py:1423 (direkt/dynamisch unklar); tests/test_server.py:1430 (direkt/dynamisch unklar); tests/test_server.py:5831 (direkt/dynamisch unklar); tests/test_server.py:5835 (direkt/dynamisch unklar); tests/test_server.py:5850 (direkt/dynamisch unklar); tests/test_server.py:5854 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 18900 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 18910 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1384 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 18925 | `performance/` | P3 | offen | tests/test_server.py:7899 (direkt/dynamisch unklar); tests/test_server.py:7909 (direkt/dynamisch unklar); tests/test_server.py:7917 (direkt/dynamisch unklar); tests/test_server.py:7924 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 18967 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1348 (direkt/dynamisch unklar); tests/test_server.py:1351 (direkt/dynamisch unklar); tests/test_server.py:1372 (direkt/dynamisch unklar); tests/test_server.py:1405 (direkt/dynamisch unklar); tests/test_server.py:1442 (direkt/dynamisch unklar); tests/test_server.py:3279 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 18993 | `http_api/auth.py` | P10 | offen | tests/test_provider_review.py:188 (direkt/dynamisch unklar); tests/test_provider_review.py:191 (direkt/dynamisch unklar); tests/test_provider_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:3276 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 19012 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1441 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 19020 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 19032 | `http_api/` | P10 | offen | tests/test_server.py:1423 (direkt/dynamisch unklar); tests/test_server.py:1430 (direkt/dynamisch unklar); tests/test_server.py:3281 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 19038 | `http_api/` | P10 | offen | tests/test_server.py:1323 (direkt/dynamisch unklar); tests/test_server.py:1329 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 19051 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:209 (direkt/dynamisch unklar); tests/test_server.py:1526 (direkt/dynamisch unklar); tests/test_server.py:1834 (direkt/dynamisch unklar); tests/test_server.py:7447 (direkt/dynamisch unklar); tests/test_server.py:7457 (direkt/dynamisch unklar); tests/test_server.py:7463 (direkt/dynamisch unklar); tests/test_server.py:7473 (direkt/dynamisch unklar); tests/test_server.py:7485 (direkt/dynamisch unklar); tests/test_server.py:7490 (direkt/dynamisch unklar); tests/test_server.py:7494 (direkt/dynamisch unklar); tests/test_server.py:7497 (direkt/dynamisch unklar); tests/test_server.py:7503 (direkt/dynamisch unklar); tests/test_server.py:7513 (direkt/dynamisch unklar); tests/test_server.py:7520 (direkt/dynamisch unklar); tests/test_server.py:7527 (direkt/dynamisch unklar); tests/test_server.py:7534 (direkt/dynamisch unklar); tests/test_server.py:8345 (direkt/dynamisch unklar); tests/test_server.py:8368 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 19730 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:209 (direkt/dynamisch unklar); tests/test_server.py:236 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_loop` | 19735 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 19748 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 19752 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 19758 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 19764 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 19770 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 19778 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:155 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 19785 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 19799 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 19804 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 19816 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 19828 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 19833 | `sync/` | P6 | offen | tests/test_server.py:1037 (direkt/dynamisch unklar); tests/test_server.py:1046 (direkt/dynamisch unklar); tests/test_server.py:240 (Monkeypatch/getattr/sys.modules) |
| Funktion | `main` | 19841 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar); tests/test_server.py:243 (direkt/dynamisch unklar) |

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
| `backend/providers/http` | 1 |
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
| `coach/conversation.py` | 23 |
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
| `planning/` | 215 |
| `planning/calendar.py` | 1 |
| `planning/competitions.py` | 100 |
| `privacy.py` | 8 |
| `providers/` | 49 |
| `providers/calendar.py` | 6 |
| `providers/http.py` | 9 |
| `providers/intervals_client.py` | 1 |
| `providers/workout_text.py` | 12 |
| `runtime/` | 2 |
| `server.py / Composition Root` | 51 |
| `settings.py` | 9 |
| `sync/` | 171 |
| `sync/competitions.py` | 1 |
| `sync/daily.py` | 1 |
| `sync/freshness.py` | 1 |
| `sync/garmin.py` | 86 |
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
