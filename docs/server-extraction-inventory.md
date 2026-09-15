# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `aefa4b18596feb0bf034588919cef39a0bda9bf84907878b045f6a8b9efd73c2`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 21.962 physische Zeilen
- Inventareinträge: 1.723
- Definitionen (Funktionen/Klassen): 1.231
- Globale Bindungen einschließlich Imports: 293 Zuweisungen. 199 Imports
- Planbereich: bis Zeile 21.702; Einträge dahinter: 15 (zielbestimmt über Symbol-/Verantwortungsanalyse)
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
| P0 (Zuordnung offen) | 0 | 3 | 0 |
| P1 | 89 | 56 | 142 |
| P2 | 159 | 21 | 0 |
| P3 | 182 | 28 | 0 |
| P4 | 306 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 218 | 47 | 0 |
| P7 | 164 | 36 | 0 |
| P8 | 43 | 14 | 0 |
| P9 | 18 | 6 | 0 |
| P10 | 27 | 39 | 0 |
| P11 | 1 | 3 | 57 |

## Referenzanalyse außerhalb von server.py

Direkte `server.<name>`-Zugriffe und erkennbare Import-/Patchstellen sind pro Eintrag in der Tabelle vermerkt. Die Ortsangaben decken `backend/`, `tests/`, `e2e/`, `scripts/`, Docker und GitHub-Workflows ab.

### Dynamische Zugriffe und Monkeypatches

Diese Stellen benötigen bei jeder Migration eine manuelle Prüfung des Lookup-Ortes:

- `tests/support.py:106: patch.object(server, "CONFIG", replace(server.CONFIG, app_password=app_password)),`
- `tests/support.py:107: patch.object(server, "DATA_DIR", root),`
- `tests/support.py:108: patch.object(server, "DB_PATH", root / "test.db"),`
- `tests/support.py:109: patch.object(server, "LOG_PATH", root / "test.log"),`
- `tests/test_audit_remediation.py:105: with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):`
- `tests/test_audit_remediation.py:146: with patch.object(server, "weather_state", return_value={"stale": True, "days": [{}], "error": "Synthetic failure"}):`
- `tests/test_audit_remediation.py:152: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="", calendar_ical_url="")), patch.object(server, "garmin_fixture_path", return_value="synthetic"), patch.object(server, "daily_sync_due", return_value=True):`
- `tests/test_audit_remediation.py:189: startup = patch.object(server, "security_configuration_error", return_value=None)`
- `tests/test_audit_remediation.py:227: with patch.object(server, "apply_adaptive_replan", return_value={"status": "applied"}) as mutation:`
- `tests/test_audit_remediation.py:245: with patch.object(server, "ensure_conversation", return_value="synthetic"), patch.object(server, "build_training_context", side_effect=["Old Garmin data", "Fresh Garmin data"]) as context, patch.object(server, "responses_request", side_effect=response) as model:`
- `tests/test_audit_remediation.py:261: with patch.object(server, "_restore_coach_session_csrf_hash", side_effect=restore), patch.object(server, "chat_with_coach", side_effect=coach) as execute:`
- `tests/test_audit_remediation.py:269: with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="synthetic-encrypted-key")), patch.object(server, "DATA_DIR", root), patch.object(server, "DB_PATH", root / "test.db"), patch.object(server, "LOG_PATH", root / "test.log"):`
- `tests/test_audit_remediation.py:284: with patch.object(server, "sync_intervals", return_value={"status": "ok"}), patch.object(server, "chat_with_coach", return_value={"status": "failed"}), patch.object(server, "garmin_fixture_path", return_value=None):`
- `tests/test_audit_remediation.py:42: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:53: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:69: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_audit_remediation.py:80: with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):`
- `tests/test_coach_attachments.py:169: with patch.object(server, "MAX_ATTACHMENT_STORAGE_BYTES", 10):`
- `tests/test_coach_attachments.py:176: with patch.object(server, "selected_ai_provider", return_value="gemini"), patch.object(server, "MAX_GEMINI_INLINE_IMAGE_BYTES", 1):`
- `tests/test_coach_attachments.py:198: with patch.object(server, "_gemini_history", return_value=saved_history):`
- `tests/test_coach_attachments.py:214: with patch.object(server, "MAX_GEMINI_INLINE_IMAGE_BYTES", encoded_size + 1):`
- `tests/test_coach_attachments.py:227: with patch.object(server, "_gemini_local_chat_history", return_value=history), patch.object(server, "_gemini_history", return_value=history):`
- `tests/test_coach_attachments.py:246: with patch.object(server, "responses_background_request", side_effect=respond), patch.object(server, "ensure_conversation", return_value="synthetic-conversation"):`
- `tests/test_coach_attachments.py:260: with patch.object(server, "responses_background_request", side_effect=respond), patch.object(server, "ensure_conversation", return_value="synthetic-conversation"):`
- `tests/test_coach_dialogue.py:28: fixed = patch.object(server, "local_now", return_value=datetime(2026, 9, 7, 12, tzinfo=timezone.utc))`
- `tests/test_coach_dialogue.py:382: with patch.object(server, "selected_ai_provider", return_value="gemini"):`
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
- `tests/test_provider_review.py:137: with patch.object(server, "_execute_sync_job") as execute:`
- `tests/test_provider_review.py:146: with patch.object(server, "chat_with_coach") as coach, patch.object(server, "_persist_structured_command_failure") as failure:`
- `tests/test_provider_review.py:166: with patch.object(server, "_execute_sync_job", side_effect=execute):`
- `tests/test_provider_review.py:182: with self.subTest(kind="utf8"), patch.object(server, "CONFIG", replace(server.CONFIG, app_password=password)), \`
- `tests/test_provider_review.py:183: patch.object(server, "security_configuration_error", return_value=None), \`
- `tests/test_provider_review.py:184: patch.object(server, "allow_rate", return_value=(True, 0)):`
- `tests/test_provider_review.py:186: with patch.object(server, "database_manager", return_value=self.manager_for_login()):`
- `tests/test_provider_review.py:195: with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="")):`
- `tests/test_provider_review.py:214: with patch.object(server, "Garmin", return_value=client), patch.object(server, "collect_garmin_data", return_value=payload):`
- `tests/test_provider_review.py:237: with patch.object(server, "Garmin", return_value=client), \`
- `tests/test_provider_review.py:238: patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json") if fixture else None), \`
- `tests/test_provider_review.py:239: patch.object(server, "load_garmin_fixture", return_value=payload), \`
- `tests/test_provider_review.py:240: patch.object(server, "collect_garmin_data", return_value=payload):`
- `tests/test_provider_review.py:26: patch.object(server, "CONFIG", replace(server.CONFIG, app_password="", garmin_fixture_path="", garmin_email="synthetic@example.invalid")),`
- `tests/test_provider_review.py:27: patch.object(server, "DATA_DIR", root),`
- `tests/test_provider_review.py:28: patch.object(server, "DB_PATH", root / "fresh.db"),`
- `tests/test_provider_review.py:29: patch.object(server, "LOG_PATH", root / "synthetic.log"),`
- `tests/test_provider_review.py:30: patch.object(server.LOGGER, "disabled", True),`
- `tests/test_provider_review.py:313: with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="\U0001f6b4" * length)), \`
- `tests/test_provider_review.py:314: patch.object(server, "SQLCIPHER_AVAILABLE", True):`
- `tests/test_provider_review.py:31: patch.object(server, "initialise_logging"),`
- `tests/test_provider_review.py:322: with patch.object(server, "DB_PATH", encrypted_path), patch.object(server, "CONFIG", configured), \`
- `tests/test_provider_review.py:323: patch.object(server, "allow_rate", return_value=(True, 0)):`
- `tests/test_provider_review.py:32: patch.object(server, "MAINTENANCE_GATE", server.MaintenanceGate()),`
- `tests/test_provider_review.py:80: with patch.object(server.IntervalsClient, "fetch_performance_snapshot", side_effect=fetch):`
- `tests/test_server.py:1163: with patch.object(server, "_fetch_weather_forecast", side_effect=[old, new]) as fetch:`
- `tests/test_server.py:1189: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1217: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("weather must stay local")):`
- `tests/test_server.py:1231: with patch.object(server, "_fetch_weather_forecast", return_value=forecast) as fetch:`
- `tests/test_server.py:1250: with patch.object(server, "_fetch_weather_forecast", side_effect=[server.AppError(503, "upstream"), forecast]) as fetch:`
- `tests/test_server.py:1266: with patch.object(server, "CONFIG", replace(server.CONFIG, secure_cookies=True)):`
- `tests/test_server.py:1484: with patch.object(server, "delete_remote_conversation", side_effect=server.AppError(503, "upstream")):`
- `tests/test_server.py:1500: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:1517: with patch.object(server, "_fetch_weather_forecast", return_value=forecast), patch.object(`
- `tests/test_server.py:1533: with patch.object(server, "_fetch_weather_forecast", side_effect=AssertionError("coach context must not refresh weather")):`
- `tests/test_server.py:1543: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1560: with patch.object(server, "weather_state", return_value={"days": [{`
- `tests/test_server.py:1570: with patch.object(server, "latest_replan_preview", return_value={"status": "preview", "changes": [{"date": "2026-09-01"}]}):`
- `tests/test_server.py:1594: self.assertEqual(getattr(server.local_now().tzinfo, "key", None), "UTC")`
- `tests/test_server.py:1613: with patch.object(server, "local_now", return_value=fixed_now):`
- `tests/test_server.py:171: with patch.object(server, "CONFIG", config), patch.object(server, "DATA_DIR", Path(temporary)), patch.object(`
- `tests/test_server.py:1734: with patch.object(server, "http_json", side_effect=AssertionError("network")), patch.object(server, "external_call", side_effect=AssertionError("network")):`
- `tests/test_server.py:1779: with patch.object(server.sqlite3, "connect", wraps=sqlite3.connect) as connect:`
- `tests/test_server.py:1857: with patch.object(server, "state_versions", return_value={"activities": "v1"}):`
- `tests/test_server.py:209: with patch.object(server, "_execute_sync_job", return_value={"status": "ok"}):`
- `tests/test_server.py:220: with patch.object(server, "_execute_sync_job", side_effect=server.AppError(503, provider_detail, reason="network_error")):`
- `tests/test_server.py:231: with patch.object(server, "sync_garmin") as sync:`
- `tests/test_server.py:2533: with patch.object(server, "CONFIG", replace(server.CONFIG, calendar_ical_url="https://calendar.example/feed.ics")), patch.object(`
- `tests/test_server.py:2535: ), patch.object(server, "fetch_calendar_feed", return_value=b"not an ical feed"):`
- `tests/test_server.py:253: with patch.object(server, "_execute_sync_job", return_value=result):`
- `tests/test_server.py:2541: with patch.object(server.socket, "getaddrinfo", return_value=[(None, None, None, None, ("100.64.0.1", 443))]):`
- `tests/test_server.py:2565: with patch.object(server, "_resolve_calendar_addresses", return_value=addresses) as resolve, patch.object(`
- `tests/test_server.py:2567: ), patch.object(server.socket, "create_connection", side_effect=[OSError("first address unavailable"), raw_socket]) as connect, patch.object(`
- `tests/test_server.py:2581: ), patch.object(server.socket, "create_connection", side_effect=TimeoutError("calendar timeout")):`
- `tests/test_server.py:2620: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload), patch.object(`
- `tests/test_server.py:263: with patch.object(server, "_repair_local_planned_unit_calendar_entry", return_value=None) as repair:`
- `tests/test_server.py:2649: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", return_value=payload):`
- `tests/test_server.py:2664: with patch.object(server, "CONFIG", config), patch.object(server, "fetch_calendar_feed", side_effect=server.AppError(502, "upstream unavailable")):`
- `tests/test_server.py:2731: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:2826: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=-1)):`
- `tests/test_server.py:2835: with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=30)):`
- `tests/test_server.py:2845: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:2892: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)):`
- `tests/test_server.py:2952: with patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 20, 0)):`
- `tests/test_server.py:2979: patch.object(server, "latest_snapshot", return_value=snapshot),`
- `tests/test_server.py:2980: patch.object(server, "list_dated_local_planned_workouts", return_value=planned),`
- `tests/test_server.py:2981: patch.object(server, "weather_state", return_value={"days": []}),`
- `tests/test_server.py:2982: patch.object(server, "local_now", return_value=datetime(2026, 8, 26, 12, 0)),`
- `tests/test_server.py:3386: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:341: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-plan-push"}) as enqueue:`
- `tests/test_server.py:372: with patch.object(server, "_mark_local_planning_authoritative"), patch.object(`
- `tests/test_server.py:3881: with patch.object(server.IntervalsClient, "get_workout_library", return_value=[]), \`
- `tests/test_server.py:3882: patch.object(server.IntervalsClient, "create_library_workouts", return_value=[{"id": "synthetic-remote", "type": "Ride"}]) as create, \`
- `tests/test_server.py:3883: patch.object(server.IntervalsClient, "update_library_workout", return_value={"id": "synthetic-remote", **parsed_workout_fixture()}) as update:`
- `tests/test_server.py:3901: with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=[`
- `tests/test_server.py:3926: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:3944: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:3946: ), patch.object(server.IntervalsClient, "create_library_workouts") as create:`
- `tests/test_server.py:396: with patch.object(server, "_enqueue_coach_plan_push") as enqueue, self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:4153: with patch.object(server, "garmin_fixture_path", return_value="fixture.json"), \`
- `tests/test_server.py:4154: patch.object(server, "sync_garmin") as sync_garmin, \`
- `tests/test_server.py:4155: patch.object(server, "garmin_sleep_ready_for_checkin", return_value=False), \`
- `tests/test_server.py:4156: patch.object(server, "publish_state_event", side_effect=lambda *args: events.append(args)):`
- `tests/test_server.py:4200: with patch.object(server, "CONFIG", config), patch.object(server, "Garmin", FakeGarmin):`
- `tests/test_server.py:428: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-competition"}) as enqueue:`
- `tests/test_server.py:4369: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4413: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=fake_urlopen):`
- `tests/test_server.py:4438: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4562: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value=response):`
- `tests/test_server.py:4577: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4588: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4602: with patch.object(server, "CONFIG", replace(server.CONFIG, gemini_api_key=key)):`
- `tests/test_server.py:4608: with patch.object(server, "CONFIG", config), patch.object(server, "gemini_responses_request", return_value={"output_text": "ok"}) as gemini, patch.object(server, "openai_request") as openai:`
- `tests/test_server.py:4621: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4641: with patch.object(server, "CONFIG", config), patch.object(server, "delete_remote_conversation", return_value=True) as delete:`
- `tests/test_server.py:4665: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:4712: with patch.object(server, "urlopen", side_effect=blocked_urlopen):`
- `tests/test_server.py:4743: with patch.object(server, "urlopen", return_value=response):`
- `tests/test_server.py:4776: with patch.object(server, "urlopen", side_effect=return_cancelled_response):`
- `tests/test_server.py:4795: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_api_key="test-key", openai_base_url="https://foundry.example.invalid/openai/v1/")), patch.object(`
- `tests/test_server.py:4814: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4817: with patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url="")):`
- `tests/test_server.py:4825: with self.subTest(invalid=invalid), patch.object(server, "CONFIG", replace(server.CONFIG, openai_base_url=invalid)):`
- `tests/test_server.py:4838: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", side_effect=fake_http_json):`
- `tests/test_server.py:4862: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:4869: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:4930: with patch.object(server, "publish_state_event") as publish:`
- `tests/test_server.py:5041: with patch.object(server, "calendar_conflicts", return_value=[{"name": "Occupied"}]) as conflicts:`
- `tests/test_server.py:524: with patch.object(server, "enqueue_sync_job", side_effect=[{"id": "job-performance"}, {"id": "job-competition"}]) as enqueue:`
- `tests/test_server.py:5355: with patch.object(server, "structured_athlete_context", return_value={"source_policy": {"untrusted": "x" * 200_000}}):`
- `tests/test_server.py:5462: with patch.object(server, "openai_request", side_effect=fake_openai):`
- `tests/test_server.py:5468: with patch.object(server, "http_json", return_value=response), patch.object(`
- `tests/test_server.py:547: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:5484: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:5598: with patch.object(server, "CHANGE_HISTORY_MAX_ROWS", 3), self.assertRaises(server.AppError) as error:`
- `tests/test_server.py:560: with patch.object(server, "refresh_current_performance", return_value={"status": "ok"}) as performance, patch.object(`
- `tests/test_server.py:571: with patch.object(server, "sync_intervals", return_value={"status": "ok"}) as sync, patch.object(`
- `tests/test_server.py:5735: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 2):`
- `tests/test_server.py:5749: with patch.object(server, "COACH_TRAINING_CHANGE_LIMIT", 1):`
- `tests/test_server.py:5835: with patch.object(server, "save_workout_library_entries", side_effect=RuntimeError("creation failed")):`
- `tests/test_server.py:5837: server._apply_training_patch(arguments, {`
- `tests/test_server.py:583: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:5854: with patch.object(server, "responses_request", side_effect=create), patch.object(`
- `tests/test_server.py:5859: ) as retrieve, patch.object(server, "OPENAI_BACKGROUND_POLL_SECONDS", 0), patch.object(server, "record_openai_usage"):`
- `tests/test_server.py:5907: with patch.object(server, "chat_with_coach", side_effect=lambda *args, **kwargs: seen.update(kwargs) or {}):`
- `tests/test_server.py:5931: with patch.object(server, "chat_with_coach", side_effect=complete_chat):`
- `tests/test_server.py:5960: with patch.object(server, "responses_stream_request", side_effect=streamed_response) as streamed, patch.object(`
- `tests/test_server.py:5985: ), patch.object(server, "_restore_coach_session_csrf_hash", return_value="csrf-background-requeue"):`
- `tests/test_server.py:6026: with patch.object(server, "chat_with_coach", side_effect=capture_phase), patch.object(`
- `tests/test_server.py:602: with patch.object(server, "CONFIG", config), patch.object(server, "enqueue_sync_job") as enqueue:`
- `tests/test_server.py:6062: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6064: ) as fetch_snapshot, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:6075: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6091: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6093: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:6104: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6106: ), patch.object(server, "refresh_workout_library", side_effect=cancellation):`
- `tests/test_server.py:611: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6122: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6135: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:613: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:615: ) as enqueue, patch.object(server, "_wait_for_performance_refresh") as wait:`
- `tests/test_server.py:6163: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6165: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=remote) as get_library:`
- `tests/test_server.py:6203: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6205: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6225: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6229: ) as import_units, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6247: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6249: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[{`
- `tests/test_server.py:624: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6266: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:626: ), patch.object(server, "refresh_workout_library", return_value={"workouts": 0}), patch.object(`
- `tests/test_server.py:6270: ) as library_sync, patch.object(server, "refresh_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6285: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6339: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6348: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6367: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6376: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6385: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6393: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6410: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6454: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6468: with patch.object(server, "IntervalsClient", return_value=client):`
- `tests/test_server.py:6486: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(`
- `tests/test_server.py:6531: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6533: ), patch.object(server, "_sync_selected_workout_library", return_value={"workouts": 0}):`
- `tests/test_server.py:6556: with patch.object(server, "IntervalsClient", FailingIntervalsClient), patch.object(`
- `tests/test_server.py:6566: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:6579: with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", db_path), patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6624: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:6645: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:6654: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir), patch.dict(`
- `tests/test_server.py:6674: with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir):`
- `tests/test_server.py:6821: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6853: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6891: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:6923: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6939: with patch.object(server, "IntervalsClient", return_value=client), patch.object(`
- `tests/test_server.py:6978: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7011: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7038: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(`
- `tests/test_server.py:7321: with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(server, "openai_request") as openai_request:`
- `tests/test_server.py:7322: with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):`
- `tests/test_server.py:7451: with patch.object(server, "http_json", side_effect=[`
- `tests/test_server.py:7534: with patch.object(server.LOGGER, "info") as logger:`
- `tests/test_server.py:7711: with patch.object(server.IntervalsClient, "delete_activity", return_value=None) as delete:`
- `tests/test_server.py:7761: with patch.object(server, "get_kv", side_effect=get_kv_after_read):`
- `tests/test_server.py:7793: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7815: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7821: with patch.object(server, "external_calendar_url", return_value=calendar_url), patch.object(`
- `tests/test_server.py:7843: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7862: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:7879: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7913: with patch.object(server, "urlopen", side_effect=server.URLError("offline")):`
- `tests/test_server.py:7930: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:7944: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7954: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:7970: with patch.object(server, "database", side_effect=OSError("database unavailable")):`
- `tests/test_server.py:7978: with patch.object(server.tempfile, "NamedTemporaryFile", side_effect=OSError("read-only")):`
- `tests/test_server.py:7997: with patch.object(server.time, "monotonic", return_value=20 * 60):`
- `tests/test_server.py:8026: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:8028: ), patch.object(server.IntervalsClient, "get_workout_library", return_value=[]):`
- `tests/test_server.py:8055: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8091: with patch.object(server, "urlopen", return_value=FakeResponse()):`
- `tests/test_server.py:8118: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8159: with patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8194: with patch.object(server, "openai_request", side_effect=fake_request), patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8265: with patch.object(server, "CONFIG", config), patch.object(server, "urlopen", side_effect=upstream_error):`
- `tests/test_server.py:8307: with patch.object(server, "urlopen", return_value=FakeResponse()) as urlopen:`
- `tests/test_server.py:8320: with patch.object(server, "urlopen") as urlopen:`
- `tests/test_server.py:8344: with patch.object(server, "urlopen", return_value=TimeoutResponse()):`
- `tests/test_server.py:8369: with patch.object(server, "urlopen", return_value=DisconnectResponse()):`
- `tests/test_server.py:8377: with patch.object(server, "openai_stream_request", side_effect=responses) as request, patch.object(server.time, "sleep") as sleep:`
- `tests/test_server.py:8424: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), \`
- `tests/test_server.py:8425: patch.object(server, "unregister_chat_stream") as unregister, \`
- `tests/test_server.py:8426: patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8451: with patch.object(server, "register_chat_stream", return_value=(operation_id, cancel_event)), patch.object(`
- `tests/test_server.py:8453: ) as unregister, patch.object(server, "chat_stream_events", return_value=events):`
- `tests/test_server.py:8505: with patch.object(server, "CONFIG", config), patch.object(server, "http_json", return_value={"status": "completed"}) as request:`
- `tests/test_server.py:8558: with patch.object(server, "DB_LOCK", database_lock), patch.object(`
- `tests/test_server.py:8575: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:864: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-changed"}) as enqueue:`
- `tests/test_server.py:8662: with patch.object(server, "delete_remote_conversation", return_value=True):`
- `tests/test_server.py:8676: with patch.object(server, "CONFIG", config):`
- `tests/test_server.py:8687: with patch.object(server, "CONFIG", replace(config, intervals_api_key="")):`
- `tests/test_server.py:8744: with patch.object(server, "CONFIG", config), patch.object(`
- `tests/test_server.py:890: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-large-changed"}) as enqueue:`
- `tests/test_server.py:935: with patch.object(server, "enqueue_sync_job", return_value={"id": "job-all"}) as enqueue:`
- `tests/test_server.py:972: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=True) as active, patch.object(`
- `tests/test_server.py:981: with patch.object(server, "CONFIG", config), patch.object(server, "_sync_job_active", return_value=False), patch.object(`
- `tests/test_server.py:983: ), patch.object(server, "enqueue_sync_job") as enqueue:`
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
| `publish_state_event` | 317 | – | `Any`, `STATE_EVENTS`, `STATE_EVENT_CONDITION`, `STATE_EVENT_NEXT_ID` | `STATE_EVENT_NEXT_ID` | – |
| `state_events_since` | 340 | – | `Any`, `AppError`, `STATE_EVENTS`, `STATE_EVENT_CONDITION`, `STATE_EVENT_NEXT_ID` | – | – |
| `MaintenanceGate` | 357 | – | `Any`, `AppError`, `contextmanager`, `threading` | – | – |
| `maintenance_operation` | 420 | – | `Any`, `MAINTENANCE_GATE`, `wraps` | – | – |
| `claimed_maintenance_operation` | 428 | – | `Any`, `AppError`, `MAINTENANCE_GATE`, `wraps` | – | – |
| `ProviderResyncGate` | 441 | – | `AppError`, `contextmanager`, `threading` | – | – |
| `provider_operation` | 492 | – | `GARMIN_RESYNC_GATE`, `INTERVALS_RESYNC_GATE` | – | – |
| `intervals_operation` | 497 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `garmin_operation` | 505 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `load_local_env` | 513 | – | `DATA_DIR`, `ROOT`, `load_config_env` | – | – |
| `IntervalsClient` | 521 | `_raise_chat_cancelled`, `compact_snapshot`, `deduplicate_api_records`, `intervals_workout_sport`, `latest_snapshot`, `local_now`, `selected`, `sync_date_windows`, `validate_intervals_workout_result`, `validate_workout_description`, `workout_event_payload` | `ALL_SYNC_DAYS`, `APP_NAME`, `Any`, `AppError`, `CONFIG`, `Callable`, `Config`, `IntervalsReadTransport`, `IntervalsWriteTransport`, `PLANNED_CALENDAR_FUTURE_DAYS`, `PLANNED_CALENDAR_HISTORY_DAYS`, `_raise_chat_cancelled`, … (+18) | – | – |
| `available_ai_providers` | 843 | – | `CONFIG` | – | – |
| `selected_ai_provider` | 852 | `available_ai_providers`, `get_kv` | `CONFIG`, `available_ai_providers`, `get_kv` | – | – |
| `save_ai_provider` | 866 | `available_ai_providers`, `available_model_options`, `selected_model`, `set_kv` | `Any`, `AppError`, `available_ai_providers`, `available_model_options`, `selected_model`, `set_kv` | – | – |
| `available_model_options` | 878 | `selected_ai_provider` | `CONFIG`, `GEMINI_MODEL_OPTIONS`, `MODEL_OPTIONS`, `selected_ai_provider` | – | – |
| `selected_model` | 887 | `available_model_options`, `get_kv`, `selected_ai_provider` | `CONFIG`, `available_model_options`, `get_kv`, `selected_ai_provider` | – | – |
| `save_model` | 895 | `available_model_options`, `selected_ai_provider`, `set_kv` | `Any`, `AppError`, `available_model_options`, `selected_ai_provider`, `set_kv` | – | – |
| `available_thinking_level_options` | 903 | – | `THINKING_LEVEL_OPTIONS` | – | – |
| `selected_thinking_level` | 907 | `get_kv` | `THINKING_LEVEL_OPTIONS`, `get_kv` | – | – |
| `save_thinking_level` | 913 | `set_kv` | `Any`, `AppError`, `THINKING_LEVEL_OPTIONS`, `set_kv` | – | – |
| `calendar_display_settings` | 921 | `get_kv` | `CALENDAR_DISPLAY_DEFAULTS`, `CALENDAR_DISPLAY_MAX_WEEKS`, `get_kv` | – | – |
| `save_calendar_display_settings` | 932 | `calendar_display_settings`, `set_kv` | `Any`, `AppError`, `CALENDAR_DISPLAY_MAX_WEEKS`, `calendar_display_settings`, `set_kv` | – | – |
| `_secret_variants` | 960 | – | `Any`, `quote`, `unquote` | – | – |
| `_safe_url_netloc` | 973 | – | `Any` | – | – |
| `_safe_provider_path` | 986 | – | `REDACTED_PATH`, `re`, `unquote` | – | – |
| `_unguessable_url_path_segment` | 1009 | – | `re`, `unquote` | – | – |
| `_redact_url` | 1019 | `_safe_url_netloc`, `_unguessable_url_path_segment` | `REDACTED_PATH`, `REDACTED_URL_QUERY_KEYS`, `_safe_url_netloc`, `_unguessable_url_path_segment`, `parse_qsl`, `re`, `urlencode`, `urlparse`, `urlunparse` | – | – |
| `_safe_calendar_url` | 1043 | `_safe_url_netloc` | `CONFIG`, `_safe_url_netloc`, `urlparse`, `urlunparse` | – | – |
| `redact_text` | 1053 | `_safe_calendar_url`, `_secret_variants` | `CONFIG`, `URL_VALUE_RE`, `_redact_url`, `_safe_calendar_url`, `_secret_variants`, `re` | – | – |
| `sanitize_log_value` | 1079 | `redact_text`, `sanitize_log_value` | `Any`, `redact_text`, `sanitize_log_value` | – | – |
| `JsonLogFormatter` | 1091 | `sanitize_log_value` | `Any`, `datetime`, `json`, `logging`, `sanitize_log_value`, `timezone` | – | – |
| `initialise_logging` | 1107 | `JsonLogFormatter` | `DATA_DIR`, `JsonLogFormatter`, `LOGGER`, `LOG_PATH`, `RotatingFileHandler`, `logging`, `sys` | – | – |
| `external_result_context` | 1129 | – | `Any` | – | – |
| `external_call` | 1140 | `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `external_result_context`, `initialise_logging`, `operation_error_code` | `Any`, `AppError`, `LOGGER`, `OPERATION_CONTEXT`, `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `external_result_context`, `initialise_logging`, `operation_error_code`, `provider_error`, … (+1) | – | – |
| `serialise_conversation` | 1332 | – | `AppError`, `CHAT_LOCK_TIMEOUT_SECONDS`, `CHAT_QUEUE`, `OPENAI_CONVERSATION_LOCK`, `wraps` | – | – |
| `utc_now` | 1349 | – | `datetime`, `timezone` | – | – |
| `security_configuration_error` | 1364 | – | `CONFIG`, `SQLCIPHER_AVAILABLE` | – | – |
| `operation_trigger` | 1455 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 1461 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 1470 | – | `Any` | – | – |
| `log_operation_event` | 1480 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1507 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1528 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `maintenance_operation`, `observed_operation`, `operation_result_count`, `wraps` | – | – |
| `database_manager` | 1571 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE` | – |
| `database` | 1598 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1604 | `database`, `get_kv`, `resume_interrupted_sync_jobs`, `set_kv`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `PROVIDER_RESYNC_KEYS`, `database`, `database_schema_is_current`, `database_table_names`, `datetime`, `get_kv`, `initialize_schema`, `json`, … (+5) | – | – |
| `_provider_refresh_cleanup` | 1646 | – | `Any`, `PROVIDER_REFRESH_MAX_ROWS`, `PROVIDER_REFRESH_RETENTION_DAYS`, `cleanup_refresh_history`, `datetime`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1651 | `_provider_refresh_cleanup`, `database`, `publish_state_event`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `publish_state_event`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1663 | `_provider_refresh_cleanup`, `database`, `publish_state_event`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `publish_state_event`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1697 | – | – | – | – |
| `_sync_job_error_class` | 1712 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1726 | – | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1735 | – | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1749 | `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1762 | `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1772 | `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1781 | – | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1791 | – | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1798 | `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1823 | `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1832 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1838 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1843 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1866 | – | `AppError` | – | – |
| `_pending_performance_job_id` | 1874 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1883 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1901 | `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1928 | – | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1937 | – | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1944 | – | `Any` | – | – |
| `_insert_sync_job` | 1954 | – | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 1979 | `publish_state_event` | `Any`, `publish_state_event` | – | – |
| `enqueue_sync_job` | 1993 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `maintenance_operation`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 2020 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 2040 | `database`, `utc_now` | `Any`, `DB_LOCK`, `MAINTENANCE_GATE`, `database`, `maintenance_operation`, `utc_now` | – | – |
| `_sync_job_update` | 2061 | `database`, `publish_state_event`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `publish_state_event`, `utc_now` | – | – |
| `_sync_job_item_results` | 2099 | – | `Any` | – | – |
| `_sync_job_result_target` | 2105 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 2116 | `_sync_job_result_target`, `redact_text` | `Any`, `_sync_job_result_target`, `redact_text` | – | – |
| `_sync_job_completion_snapshot` | 2136 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 2151 | `publish_state_event` | `publish_state_event` | – | – |
| `_sync_job_update_from_result` | 2168 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 2181 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 2190 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 2197 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 2214 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 2226 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 2238 | `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 2261 | – | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 2270 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 2290 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 2310 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update`, `redact_text` | `Any`, `LOGGER`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update`, `redact_text` | – | – |
| `_run_claimed_sync_job` | 2328 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `claimed_maintenance_operation` | – | – |
| `_sync_job_worker_loop` | 2338 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `MAINTENANCE_GATE`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job` | – | – |
| `start_sync_job_worker` | 2353 | `resume_interrupted_sync_jobs` | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `resume_interrupted_sync_jobs`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 2365 | `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_scheduled_provider_retry_at` | 2388 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_freshness_inputs` | 2407 | `_garmin_core_error_entries`, `get_kv`, `get_profile` | `Any`, `CONFIG`, `Path`, `WEATHER_CACHE_KEY`, `WEATHER_FAILURE_KEY`, `_garmin_core_error_entries`, `get_kv`, `get_profile`, `json` | – | – |
| `_provider_freshness_last_good_state` | 2441 | – | `Any`, `PROVIDER_REFRESH_STALE_SECONDS`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_fallback_error_code` | 2451 | – | – | – | – |
| `_provider_freshness_error_code` | 2455 | `_provider_fallback_error_code` | `Any`, `_provider_fallback_error_code` | – | – |
| `_provider_freshness_status` | 2463 | `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | `Any`, `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | – | – |
| `provider_freshness_state` | 2484 | `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | `Any`, `DB_LOCK`, `PROVIDER_REFRESH_LABELS`, `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | – | – |
| `_audit_projection_fields` | 2525 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 2539 | – | `Any`, `json` | – | – |
| `_audit_projection` | 2550 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 2574 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 2579 | – | `Any` | – | – |
| `_cleanup_change_history` | 2591 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 2601 | – | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 2618 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2657 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2689 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2700 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2712 | – | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2726 | – | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2742 | `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2780 | `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2800 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2810 | `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2835 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2856 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2866 | `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2875 | `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2901 | `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2917 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2946 | `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2961 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |

### Zyklische Gruppen

Statisch erkannte SCCs im direkten lokalen Aufrufgraphen: 14. Jede Gruppe ist als gemeinsame Umzugseinheit zu prüfen.

- `_collect_garmin_numeric_values`
- `_collect_garmin_weight_records`
- `_fixture_sleep_dates`
- `_garmin_collect_race_predictions`
- `_garmin_collect_vo2_values`
- `_garmin_mapping_nodes`
- `_shift_fixture_sleep_dates`
- `compact_garmin_context`
- `diagnostic_mapping_shape`, `diagnostic_response_shape`, `diagnostic_sequence_shape`
- `get_kv`
- `readiness_score_value`
- `sanitize_log_value`
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
| Importbindung | `deque` | 9 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `difflib` | 10 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `hashlib` | 11 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `hmac` | 12 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ipaddress` | 13 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2563 (direkt/dynamisch unklar); tests/test_server.py:2580 (direkt/dynamisch unklar) |
| Importbindung | `json` | 14 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_workout_repair.py:572 (direkt/dynamisch unklar) |
| Importbindung | `logging` | 15 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `math` | 16 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `mimetypes` | 17 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `os` | 18 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `platform` | 19 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `queue` | 20 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:8420 (direkt/dynamisch unklar); tests/test_server.py:8446 (direkt/dynamisch unklar) |
| Importbindung | `re` | 21 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `secrets` | 22 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_coach_language_recovery.py:42 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:69 (direkt/dynamisch unklar) |
| Importbindung | `shutil` | 23 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `socket` | 24 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2541 (direkt/dynamisch unklar); tests/test_server.py:2548 (direkt/dynamisch unklar); tests/test_server.py:2567 (direkt/dynamisch unklar); tests/test_server.py:2581 (direkt/dynamisch unklar) |
| Importbindung | `ssl` | 25 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:2566 (direkt/dynamisch unklar) |
| Importbindung | `sqlite3` | 26 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1020 (direkt/dynamisch unklar); tests/test_server.py:1195 (direkt/dynamisch unklar); tests/test_server.py:1779 (direkt/dynamisch unklar) |
| Importbindung | `sys` | 27 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `threading` | 28 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_diagnostic_followups.py:170 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:37 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:56 (direkt/dynamisch unklar) |
| Importbindung | `tempfile` | 29 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7978 (direkt/dynamisch unklar) |
| Importbindung | `time` | 30 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/support.py:130 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:108 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:41 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:58 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:95 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:38 (direkt/dynamisch unklar); tests/test_coach_review.py:257 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:257 (direkt/dynamisch unklar); tests/test_server.py:1309 (direkt/dynamisch unklar); tests/test_server.py:1322 (direkt/dynamisch unklar); tests/test_server.py:4235 (direkt/dynamisch unklar); tests/test_server.py:7997 (direkt/dynamisch unklar); tests/test_server.py:8194 (direkt/dynamisch unklar); tests/test_server.py:8377 (direkt/dynamisch unklar) |
| Importbindung | `uuid` | 31 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `zipfile` | 32 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ContextVar` | 33 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `nullcontext` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `contextmanager` | 34 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `dataclass` | 35 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `date` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:1570 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `datetime` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `timedelta` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:493 (direkt/dynamisch unklar) |
| Importbindung | `timezone` | 36 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `wraps` | 37 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPResponse` | 38 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `BaseHTTPRequestHandler` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `ThreadingHTTPServer` | 39 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `SimpleCookie` | 40 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `RotatingFileHandler` | 41 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Path` | 42 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Any` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Callable` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Iterator` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `NoReturn` | 43 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `HTTPError` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4658 (direkt/dynamisch unklar); tests/test_server.py:7841 (direkt/dynamisch unklar); tests/test_server.py:7872 (direkt/dynamisch unklar); tests/test_server.py:7923 (direkt/dynamisch unklar); tests/test_server.py:8108 (direkt/dynamisch unklar); tests/test_server.py:8152 (direkt/dynamisch unklar); tests/test_server.py:8167 (direkt/dynamisch unklar); tests/test_server.py:8260 (direkt/dynamisch unklar) |
| Importbindung | `URLError` | 44 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:7913 (direkt/dynamisch unklar) |
| Importbindung | `parse_qs` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `parse_qsl` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `quote` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `unquote` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlencode` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlparse` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlunparse` | 45 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `Request` | 46 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | keine statisch gefunden |
| Importbindung | `urlopen` | 46 | `server.py / Composition Root` | P11 | bestehende Infrastrukturbindung | tests/test_server.py:4413 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4665 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4712 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4743 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4776 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4862 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7843 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7862 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7879 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7913 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7930 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8055 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8091 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8118 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8159 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8265 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8307 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8320 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8344 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8369 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `database_row_factory` | 48 | `backend/db` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ABORTED_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COMPETITION_NOT_FOUND_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_LIBRARY_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CORRUPT_PLANNING_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GEMINI_API_KEY_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERNAL_SERVER_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INTERVALS_API_KEY_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_LIBRARY_ID_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_DATE_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `INVALID_PLANNING_ID_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `NOT_FOUND_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `OPENAI_API_KEY_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PLANNED_CALENDAR_RECHECK_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STALE_PLANNING_REVISION_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `STRUCTURED_AUTHORIZATION_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `UNSUPPORTED_BYDAY_ERROR` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AppError` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:189 (direkt/dynamisch unklar); tests/test_server.py:1250 (direkt/dynamisch unklar); tests/test_server.py:1360 (direkt/dynamisch unklar); tests/test_server.py:1367 (direkt/dynamisch unklar); tests/test_server.py:1484 (direkt/dynamisch unklar); tests/test_server.py:1585 (direkt/dynamisch unklar); tests/test_server.py:1589 (direkt/dynamisch unklar); tests/test_server.py:1615 (direkt/dynamisch unklar); tests/test_server.py:1754 (direkt/dynamisch unklar); tests/test_server.py:2005 (direkt/dynamisch unklar); tests/test_server.py:2011 (direkt/dynamisch unklar); tests/test_server.py:2022 (direkt/dynamisch unklar); tests/test_server.py:2026 (direkt/dynamisch unklar); tests/test_server.py:2027 (direkt/dynamisch unklar); tests/test_server.py:2029 (direkt/dynamisch unklar); tests/test_server.py:2034 (direkt/dynamisch unklar); tests/test_server.py:2037 (direkt/dynamisch unklar); tests/test_server.py:2042 (direkt/dynamisch unklar); tests/test_server.py:2045 (direkt/dynamisch unklar); tests/test_server.py:2050 (direkt/dynamisch unklar); tests/test_server.py:2053 (direkt/dynamisch unklar); tests/test_server.py:2060 (direkt/dynamisch unklar); tests/test_server.py:2085 (direkt/dynamisch unklar); tests/test_server.py:220 (direkt/dynamisch unklar); tests/test_server.py:232 (direkt/dynamisch unklar); tests/test_server.py:2341 (direkt/dynamisch unklar); tests/test_server.py:2451 (direkt/dynamisch unklar); tests/test_server.py:2476 (direkt/dynamisch unklar); tests/test_server.py:2480 (direkt/dynamisch unklar); tests/test_server.py:2523 (direkt/dynamisch unklar); tests/test_server.py:2536 (direkt/dynamisch unklar); tests/test_server.py:2542 (direkt/dynamisch unklar); tests/test_server.py:2582 (direkt/dynamisch unklar); tests/test_server.py:2664 (direkt/dynamisch unklar); tests/test_server.py:2665 (direkt/dynamisch unklar); tests/test_server.py:2670 (direkt/dynamisch unklar); tests/test_server.py:2672 (direkt/dynamisch unklar); tests/test_server.py:285 (direkt/dynamisch unklar); tests/test_server.py:317 (direkt/dynamisch unklar); tests/test_server.py:3212 (direkt/dynamisch unklar); tests/test_server.py:3249 (direkt/dynamisch unklar); tests/test_server.py:3683 (direkt/dynamisch unklar); tests/test_server.py:3783 (direkt/dynamisch unklar); tests/test_server.py:3799 (direkt/dynamisch unklar); tests/test_server.py:3838 (direkt/dynamisch unklar); tests/test_server.py:3865 (direkt/dynamisch unklar); tests/test_server.py:3873 (direkt/dynamisch unklar); tests/test_server.py:3884 (direkt/dynamisch unklar); tests/test_server.py:3905 (direkt/dynamisch unklar); tests/test_server.py:3917 (direkt/dynamisch unklar); tests/test_server.py:3921 (direkt/dynamisch unklar); tests/test_server.py:396 (direkt/dynamisch unklar); tests/test_server.py:4109 (direkt/dynamisch unklar); tests/test_server.py:4270 (direkt/dynamisch unklar); tests/test_server.py:4331 (direkt/dynamisch unklar); tests/test_server.py:4428 (direkt/dynamisch unklar); tests/test_server.py:4441 (direkt/dynamisch unklar); tests/test_server.py:4451 (direkt/dynamisch unklar); tests/test_server.py:4466 (direkt/dynamisch unklar); tests/test_server.py:4480 (direkt/dynamisch unklar); tests/test_server.py:4563 (direkt/dynamisch unklar); tests/test_server.py:4653 (direkt/dynamisch unklar); tests/test_server.py:4655 (direkt/dynamisch unklar); tests/test_server.py:4666 (direkt/dynamisch unklar); tests/test_server.py:4709 (direkt/dynamisch unklar); tests/test_server.py:4777 (direkt/dynamisch unklar); tests/test_server.py:4826 (direkt/dynamisch unklar); tests/test_server.py:485 (direkt/dynamisch unklar); tests/test_server.py:4870 (direkt/dynamisch unklar); tests/test_server.py:4872 (direkt/dynamisch unklar); tests/test_server.py:4896 (direkt/dynamisch unklar); tests/test_server.py:4971 (direkt/dynamisch unklar); tests/test_server.py:5042 (direkt/dynamisch unklar); tests/test_server.py:5207 (direkt/dynamisch unklar); tests/test_server.py:5224 (direkt/dynamisch unklar); tests/test_server.py:5430 (direkt/dynamisch unklar); tests/test_server.py:5437 (direkt/dynamisch unklar); tests/test_server.py:5447 (direkt/dynamisch unklar); tests/test_server.py:5449 (direkt/dynamisch unklar); tests/test_server.py:5598 (direkt/dynamisch unklar); tests/test_server.py:5711 (direkt/dynamisch unklar); tests/test_server.py:5763 (direkt/dynamisch unklar); tests/test_server.py:5776 (direkt/dynamisch unklar); tests/test_server.py:5984 (direkt/dynamisch unklar); tests/test_server.py:6090 (direkt/dynamisch unklar); tests/test_server.py:6094 (direkt/dynamisch unklar); tests/test_server.py:6103 (direkt/dynamisch unklar); tests/test_server.py:6107 (direkt/dynamisch unklar); tests/test_server.py:6125 (direkt/dynamisch unklar); tests/test_server.py:6136 (direkt/dynamisch unklar); tests/test_server.py:6603 (direkt/dynamisch unklar); tests/test_server.py:6616 (direkt/dynamisch unklar); tests/test_server.py:6628 (direkt/dynamisch unklar); tests/test_server.py:736 (direkt/dynamisch unklar); tests/test_server.py:755 (direkt/dynamisch unklar); tests/test_server.py:7551 (direkt/dynamisch unklar); tests/test_server.py:7558 (direkt/dynamisch unklar); tests/test_server.py:7816 (direkt/dynamisch unklar); tests/test_server.py:7824 (direkt/dynamisch unklar); tests/test_server.py:7844 (direkt/dynamisch unklar); tests/test_server.py:7880 (direkt/dynamisch unklar); tests/test_server.py:7914 (direkt/dynamisch unklar); tests/test_server.py:7931 (direkt/dynamisch unklar); tests/test_server.py:8119 (direkt/dynamisch unklar); tests/test_server.py:8160 (direkt/dynamisch unklar); tests/test_server.py:8174 (direkt/dynamisch unklar); tests/test_server.py:8185 (direkt/dynamisch unklar); tests/test_server.py:8266 (direkt/dynamisch unklar); tests/test_server.py:8321 (direkt/dynamisch unklar); tests/test_server.py:8345 (direkt/dynamisch unklar); tests/test_server.py:8375 (direkt/dynamisch unklar); tests/test_server.py:8388 (direkt/dynamisch unklar); tests/test_server.py:8391 (direkt/dynamisch unklar); tests/test_server.py:8483 (direkt/dynamisch unklar); tests/test_server.py:8492 (direkt/dynamisch unklar); tests/test_server.py:8495 (direkt/dynamisch unklar); tests/test_server.py:8498 (direkt/dynamisch unklar); tests/test_server.py:8576 (direkt/dynamisch unklar); tests/test_server.py:8625 (direkt/dynamisch unklar); tests/test_server.py:8646 (direkt/dynamisch unklar); tests/test_server.py:8746 (direkt/dynamisch unklar); tests/test_server.py:960 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Importbindung | `ClientDisconnected` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:8370 (direkt/dynamisch unklar); tests/test_server.py:8371 (direkt/dynamisch unklar); tests/test_server.py:8419 (direkt/dynamisch unklar) |
| Importbindung | `provider_error` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `public_app_error_status` | 49 | `backend/errors` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4654 (direkt/dynamisch unklar); tests/test_server.py:4655 (direkt/dynamisch unklar) |
| Importbindung | `ActivityFeedbackRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1111 (direkt/dynamisch unklar) |
| Importbindung | `ChatRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1037 (direkt/dynamisch unklar) |
| Importbindung | `CheckinRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1045 (direkt/dynamisch unklar) |
| Importbindung | `CompetitionRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1077 (direkt/dynamisch unklar) |
| Importbindung | `KeyValueRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1028 (direkt/dynamisch unklar); tests/test_server.py:1062 (direkt/dynamisch unklar) |
| Importbindung | `PlanAdjustmentRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1101 (direkt/dynamisch unklar) |
| Importbindung | `ProfileRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1062 (direkt/dynamisch unklar) |
| Importbindung | `SnapshotRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1124 (direkt/dynamisch unklar) |
| Importbindung | `TrainingPlanRepository` | 71 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1086 (direkt/dynamisch unklar) |
| Importbindung | `DatabaseManager` | 72 | `backend/db/manager` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CURRENT_DATABASE_INDEXES` | 73 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:157 (direkt/dynamisch unklar) |
| Importbindung | `CURRENT_DATABASE_SCHEMA` | 73 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1492 (direkt/dynamisch unklar); tests/test_server.py:156 (direkt/dynamisch unklar) |
| Importbindung | `configure_cipher` | 73 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `database_index_names` | 73 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:157 (direkt/dynamisch unklar) |
| Importbindung | `database_schema_is_current` | 73 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:155 (direkt/dynamisch unklar) |
| Importbindung | `database_table_names` | 73 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:156 (direkt/dynamisch unklar) |
| Importbindung | `initialize_schema` | 73 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `Config` | 82 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `DEFAULT_OPENAI_BASE_URL` | 82 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4818 (direkt/dynamisch unklar) |
| Importbindung | `load_config` | 82 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `load_config_env` | 82 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsReadTransport` | 83 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsWriteTransport` | 83 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `fetch_paged_collection` | 83 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_function_tools` | 84 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_response_text` | 84 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_failure_reason` | 85 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_text` | 85 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_error_detail` | 86 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_bounded_response` | 86 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `WorkoutTextError` | 87 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `canonical_workout_zones` | 87 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `structured_duration` | 87 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `verify_workout_readback` | 87 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GarminCollectionOptions` | 88 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `collect_garmin_data` | 88 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | tests/test_provider_review.py:214 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `ical_duration` | 89 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_date` | 89 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_value` | 89 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `unfold_ical` | 89 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
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
| Importbindung | `response_json_bytes` | 138 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:7542 (direkt/dynamisch unklar) |
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
| Globale Bindung | `Garmin` | 158 | `sync/` | P6 | offen | tests/test_provider_review.py:214 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:237 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4200 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `sqlite_backend` | 163 | `db/` | P1 | offen | tests/test_server.py:1195 (direkt/dynamisch unklar); tests/test_server.py:6596 (direkt/dynamisch unklar); tests/test_server.py:6609 (direkt/dynamisch unklar) |
| Globale Bindung | `SQLCIPHER_AVAILABLE` | 164 | `db/` | P1 | offen | tests/test_audit_remediation.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:317 (direkt/dynamisch unklar); tests/test_server.py:2840 (direkt/dynamisch unklar); tests/test_server.py:3375 (direkt/dynamisch unklar); tests/test_server.py:6573 (direkt/dynamisch unklar) |
| Globale Bindung | `ROOT` | 170 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:6654 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6674 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PUBLIC_DIR` | 171 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2365 (direkt/dynamisch unklar); tests/test_server.py:2366 (direkt/dynamisch unklar); tests/test_server.py:2382 (direkt/dynamisch unklar); tests/test_server.py:2383 (direkt/dynamisch unklar); tests/test_server.py:7340 (direkt/dynamisch unklar); tests/test_server.py:7341 (direkt/dynamisch unklar); tests/test_server.py:7352 (direkt/dynamisch unklar); tests/test_server.py:7353 (direkt/dynamisch unklar); tests/test_server.py:7361 (direkt/dynamisch unklar); tests/test_server.py:7362 (direkt/dynamisch unklar); tests/test_server.py:7370 (direkt/dynamisch unklar); tests/test_server.py:7371 (direkt/dynamisch unklar); tests/test_server.py:7377 (direkt/dynamisch unklar); tests/test_server.py:7378 (direkt/dynamisch unklar); tests/test_server.py:7387 (direkt/dynamisch unklar); tests/test_server.py:7388 (direkt/dynamisch unklar); tests/test_server.py:7389 (direkt/dynamisch unklar); tests/test_server.py:7390 (direkt/dynamisch unklar); tests/test_server.py:7601 (direkt/dynamisch unklar); tests/test_server.py:7620 (direkt/dynamisch unklar); tests/test_server.py:8721 (direkt/dynamisch unklar); tests/test_server.py:8722 (direkt/dynamisch unklar) |
| Globale Bindung | `DATA_DIR` | 172 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_server.py:100 (direkt/dynamisch unklar); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:115 (direkt/dynamisch unklar); tests/test_server.py:171 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2845 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6654 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6674 (Monkeypatch/getattr/sys.modules); tests/test_server.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 173 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:101 (direkt/dynamisch unklar); tests/test_server.py:105 (direkt/dynamisch unklar); tests/test_server.py:107 (direkt/dynamisch unklar); tests/test_server.py:116 (direkt/dynamisch unklar); tests/test_server.py:2845 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:92 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 174 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_server.py:102 (direkt/dynamisch unklar); tests/test_server.py:108 (direkt/dynamisch unklar); tests/test_server.py:117 (direkt/dynamisch unklar); tests/test_server.py:93 (direkt/dynamisch unklar) |
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
| Globale Bindung | `REDACTED_PATH` | 225 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UUID_PATTERN` | 226 | `http_api/` | P10 | offen | tests/test_server.py:3211 (direkt/dynamisch unklar) |
| Globale Bindung | `PAYLOAD_HASH_PATTERN` | 227 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `DATE_ONLY_PATTERN` | 228 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMPETITION_SQL` | 229 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_ACTION_PROPOSAL_SQL` | 230 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INSERT_LIBRARY_SQL` | 231 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_PLANNED_UNIT_SQL` | 232 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMPETITION_CONFLICT_SQL` | 233 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNED_PAYLOAD_SQL` | 234 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_LIBRARY_PAYLOAD_SQL` | 235 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMMAND_RECEIPT_SQL` | 236 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMMAND_RECEIPT_SQL` | 237 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNING_REVISION_SQL` | 238 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_USER_MESSAGE_SQL` | 239 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_IMMUTABLE_MAX_AGE` | 240 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `APP_VERSION` | 241 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:7334 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 242 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 243 | `http_api/` | P10 | offen | tests/test_server.py:4873 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 244 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 245 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 246 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 247 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 248 | `coach/streams.py` | P8 | offen | tests/test_server.py:1463 (direkt/dynamisch unklar); tests/test_server.py:1473 (direkt/dynamisch unklar); tests/test_server.py:1474 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_EXTERNAL_CALENDAR_BYTES` | 249 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_FETCH_TIMEOUT_SECONDS` | 250 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_CONNECTION_TIMEOUT_SECONDS` | 251 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_EXTERNAL_RESPONSE_BYTES` | 252 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_DEFAULT_MAX_OUTPUT_TOKENS` | 256 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LONG_PLAN_MAX_OUTPUT_TOKENS` | 257 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_FOLLOWUP_MAX_OUTPUT_TOKENS` | 258 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_TIMEOUT_SECONDS` | 259 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MESSAGE_ATTACHMENTS_QUERY` | 260 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_ERROR_CODES` | 262 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_BASE_URL` | 270 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 271 | `providers/` | P2 | offen | tests/test_server.py:5859 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 272 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 273 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 274 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 275 | `coach/` | P7 | offen | tests/test_server.py:4901 (direkt/dynamisch unklar); tests/test_server.py:5227 (direkt/dynamisch unklar); tests/test_server.py:5235 (direkt/dynamisch unklar); tests/test_server.py:5587 (direkt/dynamisch unklar); tests/test_server.py:5717 (direkt/dynamisch unklar); tests/test_server.py:5727 (direkt/dynamisch unklar); tests/test_server.py:5729 (direkt/dynamisch unklar); tests/test_server.py:5732 (direkt/dynamisch unklar); tests/test_server.py:5735 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5749 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 276 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 277 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:148 (direkt/dynamisch unklar); tests/test_audit_remediation.py:154 (direkt/dynamisch unklar); tests/test_audit_remediation.py:168 (direkt/dynamisch unklar); tests/test_audit_remediation.py:182 (direkt/dynamisch unklar); tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_audit_remediation.py:66 (direkt/dynamisch unklar); tests/test_audit_remediation.py:71 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1008 (direkt/dynamisch unklar); tests/test_server.py:122 (direkt/dynamisch unklar); tests/test_server.py:1282 (direkt/dynamisch unklar); tests/test_server.py:1287 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1308 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1504 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar); tests/test_server.py:1641 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2589 (direkt/dynamisch unklar); tests/test_server.py:2602 (direkt/dynamisch unklar); tests/test_server.py:2658 (direkt/dynamisch unklar); tests/test_server.py:2681 (direkt/dynamisch unklar); tests/test_server.py:2810 (direkt/dynamisch unklar); tests/test_server.py:2823 (direkt/dynamisch unklar); tests/test_server.py:2828 (direkt/dynamisch unklar); tests/test_server.py:3026 (direkt/dynamisch unklar); tests/test_server.py:3106 (direkt/dynamisch unklar); tests/test_server.py:4629 (direkt/dynamisch unklar); tests/test_server.py:4920 (direkt/dynamisch unklar); tests/test_server.py:5052 (direkt/dynamisch unklar); tests/test_server.py:5075 (direkt/dynamisch unklar); tests/test_server.py:5098 (direkt/dynamisch unklar); tests/test_server.py:5120 (direkt/dynamisch unklar); tests/test_server.py:5134 (direkt/dynamisch unklar); tests/test_server.py:5140 (direkt/dynamisch unklar); tests/test_server.py:5157 (direkt/dynamisch unklar); tests/test_server.py:5165 (direkt/dynamisch unklar); tests/test_server.py:5487 (direkt/dynamisch unklar); tests/test_server.py:5529 (direkt/dynamisch unklar); tests/test_server.py:5617 (direkt/dynamisch unklar); tests/test_server.py:5640 (direkt/dynamisch unklar); tests/test_server.py:5882 (direkt/dynamisch unklar); tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar); tests/test_server.py:592 (direkt/dynamisch unklar); tests/test_server.py:5987 (direkt/dynamisch unklar); tests/test_server.py:6009 (direkt/dynamisch unklar); tests/test_server.py:6018 (direkt/dynamisch unklar); tests/test_server.py:6143 (direkt/dynamisch unklar); tests/test_server.py:636 (direkt/dynamisch unklar); tests/test_server.py:6435 (direkt/dynamisch unklar); tests/test_server.py:647 (direkt/dynamisch unklar); tests/test_server.py:6498 (direkt/dynamisch unklar); tests/test_server.py:6543 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6591 (direkt/dynamisch unklar); tests/test_server.py:661 (direkt/dynamisch unklar); tests/test_server.py:6767 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:6786 (direkt/dynamisch unklar); tests/test_server.py:6937 (direkt/dynamisch unklar); tests/test_server.py:7731 (direkt/dynamisch unklar); tests/test_server.py:8558 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8563 (direkt/dynamisch unklar); tests/test_server.py:8699 (direkt/dynamisch unklar); tests/test_server.py:8713 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 278 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7741 (direkt/dynamisch unklar); tests/test_server.py:7753 (direkt/dynamisch unklar); tests/test_server.py:7756 (direkt/dynamisch unklar); tests/test_server.py:7769 (direkt/dynamisch unklar); tests/test_server.py:7770 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 279 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 280 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 281 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 282 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 283 | `performance/` | P3 | offen | tests/test_server.py:600 (direkt/dynamisch unklar); tests/test_server.py:606 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 284 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_LOCK` | 285 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 286 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 287 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:148 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 288 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8476 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 289 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8476 (direkt/dynamisch unklar); tests/test_server.py:8489 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 290 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 291 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 292 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 293 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 294 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 295 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:149 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 296 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:283 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 297 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 298 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 299 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 300 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 301 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 302 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 303 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 304 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 305 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATE_EVENT_CONDITION` | 306 | `runtime/events.py` | P1 | offen | tests/test_server.py:1740 (direkt/dynamisch unklar) |
| Globale Bindung | `STATE_EVENTS` | 307 | `runtime/events.py` | P1 | offen | tests/test_server.py:1741 (direkt/dynamisch unklar) |
| Globale Bindung | `STATE_EVENT_NEXT_ID` | 308 | `runtime/events.py` | P1 | offen | tests/test_server.py:1742 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_LOCK` | 309 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7993 (direkt/dynamisch unklar); tests/test_server.py:7999 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 310 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7994 (direkt/dynamisch unklar); tests/test_server.py:7995 (direkt/dynamisch unklar); tests/test_server.py:8000 (direkt/dynamisch unklar); tests/test_server.py:8001 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 311 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 312 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 313 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 314 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Funktion | `publish_state_event` | 317 | `runtime/events.py` | P1 | offen | tests/test_server.py:1744 (direkt/dynamisch unklar); tests/test_server.py:1757 (direkt/dynamisch unklar); tests/test_server.py:4156 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4930 (Monkeypatch/getattr/sys.modules) |
| Funktion | `state_events_since` | 340 | `runtime/events.py` | P1 | offen | tests/test_server.py:1745 (direkt/dynamisch unklar); tests/test_server.py:1748 (direkt/dynamisch unklar); tests/test_server.py:1755 (direkt/dynamisch unklar); tests/test_server.py:1758 (direkt/dynamisch unklar) |
| Klasse | `MaintenanceGate` | 357 | `runtime/maintenance.py` | P1 | offen | tests/test_provider_review.py:32 (direkt/dynamisch unklar); tests/test_server.py:2065 (direkt/dynamisch unklar); tests/test_server.py:2096 (direkt/dynamisch unklar) |
| Globale Bindung | `MAINTENANCE_GATE` | 417 | `runtime/maintenance.py` | P1 | offen | tests/test_audit_remediation.py:77 (direkt/dynamisch unklar); tests/test_provider_review.py:108 (direkt/dynamisch unklar); tests/test_provider_review.py:114 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:144 (direkt/dynamisch unklar); tests/test_provider_review.py:32 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7985 (direkt/dynamisch unklar) |
| Funktion | `maintenance_operation` | 420 | `runtime/maintenance.py` | P1 | offen | tests/test_provider_review.py:103 (direkt/dynamisch unklar) |
| Funktion | `claimed_maintenance_operation` | 428 | `runtime/maintenance.py` | P1 | offen | keine statisch gefunden |
| Klasse | `ProviderResyncGate` | 441 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 488 | `sync/` | P6 | offen | tests/test_server.py:6621 (direkt/dynamisch unklar); tests/test_server.py:6636 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 489 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 492 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 497 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 505 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `load_local_env` | 513 | `config.py` | P1 | offen | tests/test_server.py:6666 (direkt/dynamisch unklar); tests/test_server.py:6691 (direkt/dynamisch unklar) |
| Globale Bindung | `CONFIG` | 518 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:152 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:182 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:182 (direkt/dynamisch unklar); tests/test_provider_review.py:195 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:195 (direkt/dynamisch unklar); tests/test_provider_review.py:26 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:26 (direkt/dynamisch unklar); tests/test_provider_review.py:313 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:313 (direkt/dynamisch unklar); tests/test_provider_review.py:321 (direkt/dynamisch unklar); tests/test_provider_review.py:322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:114 (direkt/dynamisch unklar); tests/test_server.py:1195 (direkt/dynamisch unklar); tests/test_server.py:1266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1266 (direkt/dynamisch unklar); tests/test_server.py:169 (direkt/dynamisch unklar); tests/test_server.py:171 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2533 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2533 (direkt/dynamisch unklar); tests/test_server.py:2619 (direkt/dynamisch unklar); tests/test_server.py:2620 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2648 (direkt/dynamisch unklar); tests/test_server.py:2649 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2663 (direkt/dynamisch unklar); tests/test_server.py:2664 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2731 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2731 (direkt/dynamisch unklar); tests/test_server.py:2826 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2826 (direkt/dynamisch unklar); tests/test_server.py:2835 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2835 (direkt/dynamisch unklar); tests/test_server.py:2844 (direkt/dynamisch unklar); tests/test_server.py:2845 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3385 (direkt/dynamisch unklar); tests/test_server.py:3386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3627 (direkt/dynamisch unklar); tests/test_server.py:3700 (direkt/dynamisch unklar); tests/test_server.py:3720 (direkt/dynamisch unklar); tests/test_server.py:3731 (direkt/dynamisch unklar); tests/test_server.py:3750 (direkt/dynamisch unklar); tests/test_server.py:3926 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3926 (direkt/dynamisch unklar); tests/test_server.py:3944 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3944 (direkt/dynamisch unklar); tests/test_server.py:3954 (direkt/dynamisch unklar); tests/test_server.py:4199 (direkt/dynamisch unklar); tests/test_server.py:4200 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4267 (direkt/dynamisch unklar); tests/test_server.py:4275 (direkt/dynamisch unklar); tests/test_server.py:4367 (direkt/dynamisch unklar); tests/test_server.py:4369 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4412 (direkt/dynamisch unklar); tests/test_server.py:4413 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4437 (direkt/dynamisch unklar); tests/test_server.py:4438 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4561 (direkt/dynamisch unklar); tests/test_server.py:4562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4576 (direkt/dynamisch unklar); tests/test_server.py:4577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4587 (direkt/dynamisch unklar); tests/test_server.py:4588 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4602 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4602 (direkt/dynamisch unklar); tests/test_server.py:4606 (direkt/dynamisch unklar); tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4616 (direkt/dynamisch unklar); tests/test_server.py:4621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4640 (direkt/dynamisch unklar); tests/test_server.py:4641 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4795 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4795 (direkt/dynamisch unklar); tests/test_server.py:4813 (direkt/dynamisch unklar); tests/test_server.py:4814 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4817 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4817 (direkt/dynamisch unklar); tests/test_server.py:4825 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4825 (direkt/dynamisch unklar); tests/test_server.py:4837 (direkt/dynamisch unklar); tests/test_server.py:4838 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4861 (direkt/dynamisch unklar); tests/test_server.py:4862 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4868 (direkt/dynamisch unklar); tests/test_server.py:4869 (Monkeypatch/getattr/sys.modules); tests/test_server.py:53 (direkt/dynamisch unklar); tests/test_server.py:54 (direkt/dynamisch unklar); tests/test_server.py:582 (direkt/dynamisch unklar); tests/test_server.py:583 (Monkeypatch/getattr/sys.modules); tests/test_server.py:599 (direkt/dynamisch unklar); tests/test_server.py:602 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6060 (direkt/dynamisch unklar); tests/test_server.py:6062 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6074 (direkt/dynamisch unklar); tests/test_server.py:6075 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6089 (direkt/dynamisch unklar); tests/test_server.py:6091 (Monkeypatch/getattr/sys.modules); tests/test_server.py:610 (direkt/dynamisch unklar); tests/test_server.py:6101 (direkt/dynamisch unklar); tests/test_server.py:6104 (Monkeypatch/getattr/sys.modules); tests/test_server.py:611 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6114 (direkt/dynamisch unklar); tests/test_server.py:6122 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6134 (direkt/dynamisch unklar); tests/test_server.py:6135 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6162 (direkt/dynamisch unklar); tests/test_server.py:6163 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6202 (direkt/dynamisch unklar); tests/test_server.py:6203 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6224 (direkt/dynamisch unklar); tests/test_server.py:6225 (Monkeypatch/getattr/sys.modules); tests/test_server.py:623 (direkt/dynamisch unklar); tests/test_server.py:624 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6246 (direkt/dynamisch unklar); tests/test_server.py:6247 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6265 (direkt/dynamisch unklar); tests/test_server.py:6266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6285 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6285 (direkt/dynamisch unklar); tests/test_server.py:6339 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6339 (direkt/dynamisch unklar); tests/test_server.py:6348 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6348 (direkt/dynamisch unklar); tests/test_server.py:6367 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6367 (direkt/dynamisch unklar); tests/test_server.py:6376 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6376 (direkt/dynamisch unklar); tests/test_server.py:6385 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6385 (direkt/dynamisch unklar); tests/test_server.py:6393 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6393 (direkt/dynamisch unklar); tests/test_server.py:6410 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6410 (direkt/dynamisch unklar); tests/test_server.py:6454 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6454 (direkt/dynamisch unklar); tests/test_server.py:6486 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6486 (direkt/dynamisch unklar); tests/test_server.py:6532 (direkt/dynamisch unklar); tests/test_server.py:6557 (direkt/dynamisch unklar); tests/test_server.py:6565 (direkt/dynamisch unklar); tests/test_server.py:6566 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6577 (direkt/dynamisch unklar); tests/test_server.py:6579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6624 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6624 (direkt/dynamisch unklar); tests/test_server.py:6644 (direkt/dynamisch unklar); tests/test_server.py:6645 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6822 (direkt/dynamisch unklar); tests/test_server.py:6854 (direkt/dynamisch unklar); tests/test_server.py:6892 (direkt/dynamisch unklar); tests/test_server.py:6924 (direkt/dynamisch unklar); tests/test_server.py:6940 (direkt/dynamisch unklar); tests/test_server.py:6979 (direkt/dynamisch unklar); tests/test_server.py:7012 (direkt/dynamisch unklar); tests/test_server.py:7039 (direkt/dynamisch unklar); tests/test_server.py:7322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7322 (direkt/dynamisch unklar); tests/test_server.py:7789 (direkt/dynamisch unklar); tests/test_server.py:7793 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7814 (direkt/dynamisch unklar); tests/test_server.py:7815 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7839 (direkt/dynamisch unklar); tests/test_server.py:7843 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7943 (direkt/dynamisch unklar); tests/test_server.py:7944 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7953 (direkt/dynamisch unklar); tests/test_server.py:7954 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8024 (direkt/dynamisch unklar); tests/test_server.py:8026 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8264 (direkt/dynamisch unklar); tests/test_server.py:8265 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8504 (direkt/dynamisch unklar); tests/test_server.py:8505 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8574 (direkt/dynamisch unklar); tests/test_server.py:8575 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8669 (direkt/dynamisch unklar); tests/test_server.py:8676 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8687 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8743 (direkt/dynamisch unklar); tests/test_server.py:8744 (Monkeypatch/getattr/sys.modules); tests/test_server.py:90 (direkt/dynamisch unklar); tests/test_server.py:97 (direkt/dynamisch unklar); tests/test_server.py:971 (direkt/dynamisch unklar); tests/test_server.py:972 (Monkeypatch/getattr/sys.modules); tests/test_server.py:980 (direkt/dynamisch unklar); tests/test_server.py:981 (Monkeypatch/getattr/sys.modules) |
| Klasse | `IntervalsClient` | 521 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:42 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:53 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:69 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:80 (direkt/dynamisch unklar); tests/test_server.py:3627 (direkt/dynamisch unklar); tests/test_server.py:3700 (direkt/dynamisch unklar); tests/test_server.py:3720 (direkt/dynamisch unklar); tests/test_server.py:3731 (direkt/dynamisch unklar); tests/test_server.py:3750 (direkt/dynamisch unklar); tests/test_server.py:3822 (direkt/dynamisch unklar); tests/test_server.py:3850 (direkt/dynamisch unklar); tests/test_server.py:3881 (direkt/dynamisch unklar); tests/test_server.py:3882 (direkt/dynamisch unklar); tests/test_server.py:3883 (direkt/dynamisch unklar); tests/test_server.py:3901 (direkt/dynamisch unklar); tests/test_server.py:3945 (direkt/dynamisch unklar); tests/test_server.py:3946 (direkt/dynamisch unklar); tests/test_server.py:3954 (direkt/dynamisch unklar); tests/test_server.py:4267 (direkt/dynamisch unklar); tests/test_server.py:4275 (direkt/dynamisch unklar); tests/test_server.py:6063 (direkt/dynamisch unklar); tests/test_server.py:6076 (direkt/dynamisch unklar); tests/test_server.py:6092 (direkt/dynamisch unklar); tests/test_server.py:6105 (direkt/dynamisch unklar); tests/test_server.py:612 (direkt/dynamisch unklar); tests/test_server.py:6123 (direkt/dynamisch unklar); tests/test_server.py:6164 (direkt/dynamisch unklar); tests/test_server.py:6165 (direkt/dynamisch unklar); tests/test_server.py:6204 (direkt/dynamisch unklar); tests/test_server.py:6226 (direkt/dynamisch unklar); tests/test_server.py:6248 (direkt/dynamisch unklar); tests/test_server.py:6249 (direkt/dynamisch unklar); tests/test_server.py:625 (direkt/dynamisch unklar); tests/test_server.py:6267 (direkt/dynamisch unklar); tests/test_server.py:6468 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6531 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6556 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6821 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6853 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6891 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6923 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6939 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6978 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7011 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7038 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7321 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7711 (direkt/dynamisch unklar); tests/test_server.py:8027 (direkt/dynamisch unklar); tests/test_server.py:8028 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 824 | `observability.py` | P1 | offen | tests/test_provider_review.py:20 (direkt/dynamisch unklar); tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:30 (direkt/dynamisch unklar); tests/test_provider_review.py:39 (direkt/dynamisch unklar); tests/test_provider_review.py:41 (direkt/dynamisch unklar); tests/test_provider_review.py:43 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_server.py:7534 (direkt/dynamisch unklar); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7779 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7916 (direkt/dynamisch unklar); tests/test_server.py:8030 (direkt/dynamisch unklar); tests/test_server.py:8061 (direkt/dynamisch unklar); tests/test_server.py:8597 (direkt/dynamisch unklar) |
| Globale Bindung | `MODEL_OPTIONS` | 825 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_MODEL_OPTIONS` | 830 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `THINKING_LEVEL_OPTIONS` | 834 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_DISPLAY_DEFAULTS` | 839 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_DISPLAY_MAX_WEEKS` | 840 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `available_ai_providers` | 843 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_ai_provider` | 852 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:382 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4589 (direkt/dynamisch unklar) |
| Funktion | `save_ai_provider` | 866 | `settings.py` | P1 | offen | tests/test_server.py:4591 (direkt/dynamisch unklar); tests/test_server.py:4597 (direkt/dynamisch unklar) |
| Funktion | `available_model_options` | 878 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_model` | 887 | `settings.py` | P1 | offen | tests/test_server.py:4595 (direkt/dynamisch unklar); tests/test_server.py:4598 (direkt/dynamisch unklar); tests/test_server.py:5427 (direkt/dynamisch unklar); tests/test_server.py:5429 (direkt/dynamisch unklar) |
| Funktion | `save_model` | 895 | `settings.py` | P1 | offen | tests/test_server.py:4590 (direkt/dynamisch unklar); tests/test_server.py:4596 (direkt/dynamisch unklar); tests/test_server.py:5428 (direkt/dynamisch unklar); tests/test_server.py:5431 (direkt/dynamisch unklar) |
| Funktion | `available_thinking_level_options` | 903 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_thinking_level` | 907 | `settings.py` | P1 | offen | tests/test_server.py:5434 (direkt/dynamisch unklar); tests/test_server.py:5436 (direkt/dynamisch unklar) |
| Funktion | `save_thinking_level` | 913 | `settings.py` | P1 | offen | tests/test_server.py:5435 (direkt/dynamisch unklar); tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:5455 (direkt/dynamisch unklar) |
| Funktion | `calendar_display_settings` | 921 | `settings.py` | P1 | offen | tests/test_server.py:5441 (direkt/dynamisch unklar); tests/test_server.py:5446 (direkt/dynamisch unklar); tests/test_server.py:5452 (direkt/dynamisch unklar) |
| Funktion | `save_calendar_display_settings` | 932 | `settings.py` | P1 | offen | tests/test_server.py:5443 (direkt/dynamisch unklar); tests/test_server.py:5448 (direkt/dynamisch unklar); tests/test_server.py:5450 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTED_URL_QUERY_KEYS` | 953 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `URL_VALUE_RE` | 957 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_secret_variants` | 960 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_url_netloc` | 973 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_provider_path` | 986 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_unguessable_url_path_segment` | 1009 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_redact_url` | 1019 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_calendar_url` | 1043 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `redact_text` | 1053 | `observability.py` | P1 | offen | tests/test_server.py:4603 (direkt/dynamisch unklar); tests/test_server.py:7804 (direkt/dynamisch unklar) |
| Funktion | `sanitize_log_value` | 1079 | `observability.py` | P1 | offen | keine statisch gefunden |
| Klasse | `JsonLogFormatter` | 1091 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `initialise_logging` | 1107 | `observability.py` | P1 | offen | tests/test_provider_review.py:31 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7777 (direkt/dynamisch unklar); tests/test_server.py:7842 (direkt/dynamisch unklar); tests/test_server.py:7912 (direkt/dynamisch unklar); tests/test_server.py:8025 (direkt/dynamisch unklar); tests/test_server.py:8054 (direkt/dynamisch unklar); tests/test_server.py:8328 (direkt/dynamisch unklar); tests/test_server.py:8590 (direkt/dynamisch unklar) |
| Funktion | `external_result_context` | 1129 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `external_call` | 1140 | `providers/http.py` | P2 | offen | tests/test_server.py:1734 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7817 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:7908 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 1203 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 1222 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 1223 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 1224 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 1225 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 1226 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 1227 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 1228 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 1229 | `weather/` | P3 | offen | tests/test_audit_remediation.py:119 (direkt/dynamisch unklar); tests/test_audit_remediation.py:144 (direkt/dynamisch unklar); tests/test_audit_remediation.py:82 (direkt/dynamisch unklar); tests/test_server.py:1183 (direkt/dynamisch unklar); tests/test_server.py:1185 (direkt/dynamisch unklar); tests/test_server.py:1209 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1389 (direkt/dynamisch unklar); tests/test_server.py:1527 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 1230 | `weather/` | P3 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 1231 | `history/` | P5 | offen | tests/test_server.py:4209 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 1232 | `weather/` | P3 | offen | tests/test_server.py:1203 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1210 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 1233 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 1234 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 1235 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 1236 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 1237 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 1267 | `weather/` | P3 | offen | tests/test_server.py:7467 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 1299 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `serialise_conversation` | 1332 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8479 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 1349 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:184 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:79 (direkt/dynamisch unklar); tests/test_audit_remediation.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1007 (direkt/dynamisch unklar); tests/test_server.py:1158 (direkt/dynamisch unklar); tests/test_server.py:1161 (direkt/dynamisch unklar); tests/test_server.py:1229 (direkt/dynamisch unklar); tests/test_server.py:1248 (direkt/dynamisch unklar); tests/test_server.py:1395 (direkt/dynamisch unklar); tests/test_server.py:1399 (direkt/dynamisch unklar); tests/test_server.py:1515 (direkt/dynamisch unklar); tests/test_server.py:1644 (direkt/dynamisch unklar); tests/test_server.py:2531 (direkt/dynamisch unklar); tests/test_server.py:2592 (direkt/dynamisch unklar); tests/test_server.py:2605 (direkt/dynamisch unklar); tests/test_server.py:2661 (direkt/dynamisch unklar); tests/test_server.py:2684 (direkt/dynamisch unklar); tests/test_server.py:2813 (direkt/dynamisch unklar); tests/test_server.py:3109 (direkt/dynamisch unklar); tests/test_server.py:3113 (direkt/dynamisch unklar); tests/test_server.py:5054 (direkt/dynamisch unklar); tests/test_server.py:5077 (direkt/dynamisch unklar); tests/test_server.py:5100 (direkt/dynamisch unklar); tests/test_server.py:5122 (direkt/dynamisch unklar); tests/test_server.py:5143 (direkt/dynamisch unklar); tests/test_server.py:5167 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5642 (direkt/dynamisch unklar); tests/test_server.py:5897 (direkt/dynamisch unklar); tests/test_server.py:5916 (direkt/dynamisch unklar); tests/test_server.py:7732 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 1353 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 1354 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 1355 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 1356 | `planning/` | P4 | offen | tests/test_server.py:5053 (direkt/dynamisch unklar); tests/test_server.py:5076 (direkt/dynamisch unklar); tests/test_server.py:5099 (direkt/dynamisch unklar); tests/test_server.py:5121 (direkt/dynamisch unklar); tests/test_server.py:5135 (direkt/dynamisch unklar); tests/test_server.py:5142 (direkt/dynamisch unklar); tests/test_server.py:5158 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5641 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 1357 | `planning/` | P4 | offen | tests/test_server.py:7732 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 1358 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4551 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 1359 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 1360 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 1361 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `security_configuration_error` | 1364 | `config.py` | P1 | offen | tests/test_audit_remediation.py:189 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:315 (direkt/dynamisch unklar) |
| Globale Bindung | `OPERATION_CONTEXT` | 1374 | `observability.py` | P1 | offen | tests/test_server.py:8011 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 1375 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:329 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_server.py:178 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 1376 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:179 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETENTION_DAYS` | 1378 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_MAX_ROWS` | 1379 | `sync/` | P6 | offen | tests/test_server.py:8710 (direkt/dynamisch unklar); tests/test_server.py:8715 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 1380 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 1381 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_STALE_SECONDS` | 1382 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_LABELS` | 1390 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 1398 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 1399 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 1400 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 1401 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 1402 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 1403 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 1404 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 1405 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_DURATION_SECONDS` | 1406 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_MAX_ENTRIES` | 1407 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_STATE_KEY` | 1408 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_ENTRIES_KEY` | 1409 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 1411 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 1414 | `history/` | P5 | offen | tests/test_server.py:5587 (direkt/dynamisch unklar); tests/test_server.py:5598 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 1415 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 1416 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 1417 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 1418 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 1423 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 1428 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 1433 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 1437 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 1439 | `planning/` | P4 | offen | tests/test_server.py:360 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 1440 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 1441 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 1444 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 1455 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 1461 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 1470 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 1480 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1507 | `observability.py` | P1 | offen | tests/test_server.py:8008 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1528 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1571 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:280 (direkt/dynamisch unklar); tests/test_provider_review.py:186 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:328 (direkt/dynamisch unklar); tests/test_server.py:176 (direkt/dynamisch unklar) |
| Funktion | `database` | 1598 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:148 (direkt/dynamisch unklar); tests/test_audit_remediation.py:154 (direkt/dynamisch unklar); tests/test_audit_remediation.py:168 (direkt/dynamisch unklar); tests/test_audit_remediation.py:182 (direkt/dynamisch unklar); tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_audit_remediation.py:66 (direkt/dynamisch unklar); tests/test_audit_remediation.py:71 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1008 (direkt/dynamisch unklar); tests/test_server.py:1029 (direkt/dynamisch unklar); tests/test_server.py:1038 (direkt/dynamisch unklar); tests/test_server.py:1052 (direkt/dynamisch unklar); tests/test_server.py:1064 (direkt/dynamisch unklar); tests/test_server.py:1078 (direkt/dynamisch unklar); tests/test_server.py:1087 (direkt/dynamisch unklar); tests/test_server.py:1096 (direkt/dynamisch unklar); tests/test_server.py:1103 (direkt/dynamisch unklar); tests/test_server.py:1114 (direkt/dynamisch unklar); tests/test_server.py:1125 (direkt/dynamisch unklar); tests/test_server.py:122 (direkt/dynamisch unklar); tests/test_server.py:1282 (direkt/dynamisch unklar); tests/test_server.py:1287 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1308 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1504 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar); tests/test_server.py:1641 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2589 (direkt/dynamisch unklar); tests/test_server.py:2602 (direkt/dynamisch unklar); tests/test_server.py:2658 (direkt/dynamisch unklar); tests/test_server.py:2681 (direkt/dynamisch unklar); tests/test_server.py:2810 (direkt/dynamisch unklar); tests/test_server.py:2823 (direkt/dynamisch unklar); tests/test_server.py:2828 (direkt/dynamisch unklar); tests/test_server.py:2847 (direkt/dynamisch unklar); tests/test_server.py:3026 (direkt/dynamisch unklar); tests/test_server.py:3106 (direkt/dynamisch unklar); tests/test_server.py:3394 (direkt/dynamisch unklar); tests/test_server.py:4550 (direkt/dynamisch unklar); tests/test_server.py:4629 (direkt/dynamisch unklar); tests/test_server.py:4920 (direkt/dynamisch unklar); tests/test_server.py:5052 (direkt/dynamisch unklar); tests/test_server.py:5075 (direkt/dynamisch unklar); tests/test_server.py:5098 (direkt/dynamisch unklar); tests/test_server.py:5120 (direkt/dynamisch unklar); tests/test_server.py:5134 (direkt/dynamisch unklar); tests/test_server.py:5140 (direkt/dynamisch unklar); tests/test_server.py:5157 (direkt/dynamisch unklar); tests/test_server.py:5165 (direkt/dynamisch unklar); tests/test_server.py:5487 (direkt/dynamisch unklar); tests/test_server.py:5529 (direkt/dynamisch unklar); tests/test_server.py:5617 (direkt/dynamisch unklar); tests/test_server.py:5640 (direkt/dynamisch unklar); tests/test_server.py:5882 (direkt/dynamisch unklar); tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar); tests/test_server.py:592 (direkt/dynamisch unklar); tests/test_server.py:5987 (direkt/dynamisch unklar); tests/test_server.py:6009 (direkt/dynamisch unklar); tests/test_server.py:6018 (direkt/dynamisch unklar); tests/test_server.py:6143 (direkt/dynamisch unklar); tests/test_server.py:636 (direkt/dynamisch unklar); tests/test_server.py:6435 (direkt/dynamisch unklar); tests/test_server.py:647 (direkt/dynamisch unklar); tests/test_server.py:6498 (direkt/dynamisch unklar); tests/test_server.py:6543 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6591 (direkt/dynamisch unklar); tests/test_server.py:661 (direkt/dynamisch unklar); tests/test_server.py:6767 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:6786 (direkt/dynamisch unklar); tests/test_server.py:6937 (direkt/dynamisch unklar); tests/test_server.py:7731 (direkt/dynamisch unklar); tests/test_server.py:7970 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8429 (direkt/dynamisch unklar); tests/test_server.py:8563 (direkt/dynamisch unklar); tests/test_server.py:8699 (direkt/dynamisch unklar); tests/test_server.py:8713 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1604 | `db/schema.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:324 (direkt/dynamisch unklar); tests/test_provider_review.py:36 (direkt/dynamisch unklar); tests/test_server.py:103 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:1167 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar); tests/test_server.py:175 (direkt/dynamisch unklar); tests/test_server.py:195 (direkt/dynamisch unklar); tests/test_server.py:2827 (direkt/dynamisch unklar); tests/test_server.py:2836 (direkt/dynamisch unklar); tests/test_server.py:2846 (direkt/dynamisch unklar); tests/test_server.py:3387 (direkt/dynamisch unklar); tests/test_server.py:6580 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1646 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1651 | `settings.py` | P1 | offen | tests/test_server.py:8681 (direkt/dynamisch unklar); tests/test_server.py:8697 (direkt/dynamisch unklar); tests/test_server.py:8711 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1663 | `settings.py` | P1 | offen | tests/test_server.py:8682 (direkt/dynamisch unklar); tests/test_server.py:8698 (direkt/dynamisch unklar); tests/test_server.py:8712 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1697 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1712 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1726 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1735 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1749 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1762 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1772 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1781 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1791 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1798 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1823 | `sync/` | P6 | offen | tests/test_audit_remediation.py:277 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:205 (direkt/dynamisch unklar); tests/test_server.py:207 (direkt/dynamisch unklar); tests/test_server.py:211 (direkt/dynamisch unklar); tests/test_server.py:222 (direkt/dynamisch unklar); tests/test_server.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1832 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1838 | `sync/` | P6 | offen | tests/test_server.py:972 (Monkeypatch/getattr/sys.modules); tests/test_server.py:981 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1843 | `sync/` | P6 | offen | tests/test_server.py:603 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1866 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1874 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1883 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1901 | `sync/` | P6 | offen | tests/test_server.py:615 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1928 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1937 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1944 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1954 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 1979 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 1993 | `sync/` | P6 | offen | tests/test_audit_remediation.py:239 (direkt/dynamisch unklar); tests/test_audit_remediation.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:133 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:152 (direkt/dynamisch unklar); tests/test_server.py:200 (direkt/dynamisch unklar); tests/test_server.py:217 (direkt/dynamisch unklar); tests/test_server.py:244 (direkt/dynamisch unklar); tests/test_server.py:341 (Monkeypatch/getattr/sys.modules); tests/test_server.py:428 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4893 (direkt/dynamisch unklar); tests/test_server.py:4897 (direkt/dynamisch unklar); tests/test_server.py:524 (Monkeypatch/getattr/sys.modules); tests/test_server.py:584 (direkt/dynamisch unklar); tests/test_server.py:587 (direkt/dynamisch unklar); tests/test_server.py:602 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6342 (direkt/dynamisch unklar); tests/test_server.py:6351 (direkt/dynamisch unklar); tests/test_server.py:6370 (direkt/dynamisch unklar); tests/test_server.py:6379 (direkt/dynamisch unklar); tests/test_server.py:864 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8691 (direkt/dynamisch unklar); tests/test_server.py:890 (Monkeypatch/getattr/sys.modules); tests/test_server.py:935 (Monkeypatch/getattr/sys.modules); tests/test_server.py:983 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 2020 | `sync/` | P6 | offen | tests/test_server.py:206 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 2040 | `sync/` | P6 | offen | tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_audit_remediation.py:278 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:140 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:203 (direkt/dynamisch unklar); tests/test_server.py:208 (direkt/dynamisch unklar); tests/test_server.py:218 (direkt/dynamisch unklar); tests/test_server.py:251 (direkt/dynamisch unklar); tests/test_server.py:6343 (direkt/dynamisch unklar); tests/test_server.py:6352 (direkt/dynamisch unklar); tests/test_server.py:6371 (direkt/dynamisch unklar); tests/test_server.py:6380 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 2061 | `sync/` | P6 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_audit_remediation.py:275 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 2099 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 2105 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 2116 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 2136 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 2151 | `runtime/` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 2168 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 2181 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 2190 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 2197 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 2214 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 2226 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 2238 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:166 (Monkeypatch/getattr/sys.modules); tests/test_server.py:209 (Monkeypatch/getattr/sys.modules); tests/test_server.py:220 (Monkeypatch/getattr/sys.modules); tests/test_server.py:233 (direkt/dynamisch unklar); tests/test_server.py:253 (Monkeypatch/getattr/sys.modules); tests/test_server.py:550 (direkt/dynamisch unklar); tests/test_server.py:551 (direkt/dynamisch unklar); tests/test_server.py:563 (direkt/dynamisch unklar); tests/test_server.py:576 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 2261 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 2270 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 2290 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 2310 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 2328 | `sync/` | P6 | offen | tests/test_provider_review.py:138 (direkt/dynamisch unklar); tests/test_provider_review.py:167 (direkt/dynamisch unklar); tests/test_server.py:210 (direkt/dynamisch unklar); tests/test_server.py:221 (direkt/dynamisch unklar); tests/test_server.py:254 (direkt/dynamisch unklar); tests/test_server.py:6343 (direkt/dynamisch unklar); tests/test_server.py:6352 (direkt/dynamisch unklar); tests/test_server.py:6371 (direkt/dynamisch unklar); tests/test_server.py:6380 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 2338 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 2353 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `resolve_sync_job` | 2365 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_scheduled_provider_retry_at` | 2388 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_inputs` | 2407 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_last_good_state` | 2441 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_fallback_error_code` | 2451 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_error_code` | 2455 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_status` | 2463 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `provider_freshness_state` | 2484 | `settings.py` | P1 | offen | tests/test_server.py:6140 (direkt/dynamisch unklar); tests/test_server.py:8678 (direkt/dynamisch unklar); tests/test_server.py:8683 (direkt/dynamisch unklar); tests/test_server.py:8688 (direkt/dynamisch unklar); tests/test_server.py:8695 (direkt/dynamisch unklar); tests/test_server.py:8705 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 2525 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 2539 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 2550 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 2574 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 2579 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 2591 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 2601 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 2618 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2657 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2689 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3154 (direkt/dynamisch unklar); tests/test_server.py:5570 (direkt/dynamisch unklar); tests/test_server.py:5659 (direkt/dynamisch unklar); tests/test_server.py:5708 (direkt/dynamisch unklar); tests/test_server.py:8632 (direkt/dynamisch unklar); tests/test_server.py:8652 (direkt/dynamisch unklar); tests/test_server.py:8661 (direkt/dynamisch unklar); tests/test_server.py:8664 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2700 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2712 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2726 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2742 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8641 (direkt/dynamisch unklar); tests/test_server.py:8647 (direkt/dynamisch unklar); tests/test_server.py:8653 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2780 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2800 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2810 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2835 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2856 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2866 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2875 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2901 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2917 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2937 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2946 | `history/` | P5 | offen | tests/test_server.py:3161 (direkt/dynamisch unklar); tests/test_server.py:5577 (direkt/dynamisch unklar); tests/test_server.py:5712 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2961 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:119 (direkt/dynamisch unklar); tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:236 (direkt/dynamisch unklar); tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_audit_remediation.py:287 (direkt/dynamisch unklar); tests/test_audit_remediation.py:82 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:177 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_server.py:1185 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:196 (direkt/dynamisch unklar); tests/test_server.py:197 (direkt/dynamisch unklar); tests/test_server.py:2837 (direkt/dynamisch unklar); tests/test_server.py:2838 (direkt/dynamisch unklar); tests/test_server.py:4160 (direkt/dynamisch unklar); tests/test_server.py:4161 (direkt/dynamisch unklar); tests/test_server.py:4444 (direkt/dynamisch unklar); tests/test_server.py:4567 (direkt/dynamisch unklar); tests/test_server.py:6097 (direkt/dynamisch unklar); tests/test_server.py:6109 (direkt/dynamisch unklar); tests/test_server.py:6110 (direkt/dynamisch unklar); tests/test_server.py:6213 (direkt/dynamisch unklar); tests/test_server.py:6232 (direkt/dynamisch unklar); tests/test_server.py:6236 (direkt/dynamisch unklar); tests/test_server.py:6571 (direkt/dynamisch unklar); tests/test_server.py:6590 (direkt/dynamisch unklar); tests/test_server.py:6648 (direkt/dynamisch unklar); tests/test_server.py:7743 (direkt/dynamisch unklar); tests/test_server.py:7761 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 2968 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 2969 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 2970 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 2971 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_CALENDAR_WINDOW_DAYS` | 2972 | `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | P0 (Zuordnung offen) | offen | tests/test_server.py:2640 (direkt/dynamisch unklar) |
| Globale Bindung | `ICAL_MAX_RECURRENCE_COUNT` | 2973 | `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | P0 (Zuordnung offen) | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_MAX_RECURRENCE_PERIODS` | 2974 | `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | P0 (Zuordnung offen) | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 2975 | `planning/` | P4 | offen | tests/test_server.py:2703 (direkt/dynamisch unklar); tests/test_server.py:2713 (direkt/dynamisch unklar); tests/test_server.py:2738 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 2976 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 2977 | `planning/` | P4 | offen | tests/test_server.py:2315 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 2978 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 2981 | `planning/` | P4 | offen | tests/test_server.py:3645 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 2982 | `planning/` | P4 | offen | tests/test_server.py:3646 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 2983 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 2984 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 2985 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 2986 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 2987 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 2988 | `coach/` | P7 | offen | tests/test_server.py:5348 (direkt/dynamisch unklar); tests/test_server.py:5359 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 2989 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 3002 | `sync/` | P6 | offen | tests/test_server.py:6034 (direkt/dynamisch unklar); tests/test_server.py:6036 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 3013 | `sync/garmin.py` | P6 | offen | tests/test_server.py:6033 (direkt/dynamisch unklar); tests/test_server.py:6035 (direkt/dynamisch unklar); tests/test_server.py:6061 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 3025 | `sync/` | P6 | offen | tests/test_server.py:6037 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 3036 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:221 (direkt/dynamisch unklar); tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 3041 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:210 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 3047 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:159 (direkt/dynamisch unklar); tests/test_provider_review.py:208 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_server.py:1183 (direkt/dynamisch unklar); tests/test_server.py:1203 (direkt/dynamisch unklar); tests/test_server.py:1209 (direkt/dynamisch unklar); tests/test_server.py:1210 (direkt/dynamisch unklar); tests/test_server.py:1388 (direkt/dynamisch unklar); tests/test_server.py:1389 (direkt/dynamisch unklar); tests/test_server.py:1390 (direkt/dynamisch unklar); tests/test_server.py:1391 (direkt/dynamisch unklar); tests/test_server.py:1483 (direkt/dynamisch unklar); tests/test_server.py:1495 (direkt/dynamisch unklar); tests/test_server.py:1527 (direkt/dynamisch unklar); tests/test_server.py:1635 (direkt/dynamisch unklar); tests/test_server.py:1852 (direkt/dynamisch unklar); tests/test_server.py:1853 (direkt/dynamisch unklar); tests/test_server.py:1854 (direkt/dynamisch unklar); tests/test_server.py:1855 (direkt/dynamisch unklar); tests/test_server.py:1856 (direkt/dynamisch unklar); tests/test_server.py:193 (direkt/dynamisch unklar); tests/test_server.py:194 (direkt/dynamisch unklar); tests/test_server.py:2833 (direkt/dynamisch unklar); tests/test_server.py:2834 (direkt/dynamisch unklar); tests/test_server.py:3258 (direkt/dynamisch unklar); tests/test_server.py:3282 (direkt/dynamisch unklar); tests/test_server.py:3293 (direkt/dynamisch unklar); tests/test_server.py:3341 (direkt/dynamisch unklar); tests/test_server.py:3448 (direkt/dynamisch unklar); tests/test_server.py:3480 (direkt/dynamisch unklar); tests/test_server.py:3499 (direkt/dynamisch unklar); tests/test_server.py:3540 (direkt/dynamisch unklar); tests/test_server.py:3560 (direkt/dynamisch unklar); tests/test_server.py:4210 (direkt/dynamisch unklar); tests/test_server.py:4216 (direkt/dynamisch unklar); tests/test_server.py:4500 (direkt/dynamisch unklar); tests/test_server.py:4524 (direkt/dynamisch unklar); tests/test_server.py:4537 (direkt/dynamisch unklar); tests/test_server.py:4617 (direkt/dynamisch unklar); tests/test_server.py:4639 (direkt/dynamisch unklar); tests/test_server.py:5415 (direkt/dynamisch unklar); tests/test_server.py:5451 (direkt/dynamisch unklar); tests/test_server.py:5946 (direkt/dynamisch unklar); tests/test_server.py:6102 (direkt/dynamisch unklar); tests/test_server.py:6564 (direkt/dynamisch unklar); tests/test_server.py:6581 (direkt/dynamisch unklar); tests/test_server.py:6639 (direkt/dynamisch unklar); tests/test_server.py:6640 (direkt/dynamisch unklar); tests/test_server.py:7722 (direkt/dynamisch unklar); tests/test_server.py:7723 (direkt/dynamisch unklar); tests/test_server.py:7740 (direkt/dynamisch unklar); tests/test_server.py:7755 (direkt/dynamisch unklar); tests/test_server.py:7829 (direkt/dynamisch unklar); tests/test_server.py:7945 (direkt/dynamisch unklar); tests/test_server.py:7955 (direkt/dynamisch unklar); tests/test_server.py:8503 (direkt/dynamisch unklar) |
| Funktion | `_safe_diagnostic_context` | 3055 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_mapping_shape` | 3067 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_sequence_shape` | 3079 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_response_shape` | 3086 | `observability.py` | P1 | offen | tests/test_server.py:8582 (direkt/dynamisch unklar); tests/test_server.py:8587 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_response` | 3103 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_diagnostic_error` | 3108 | `observability.py` | P1 | offen | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 3126 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 3141 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_capture_state` | 3158 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_capture_status` | 3166 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7885 (direkt/dynamisch unklar); tests/test_server.py:7907 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_entries` | 3188 | `observability.py` | P1 | offen | tests/test_server.py:7900 (direkt/dynamisch unklar); tests/test_server.py:8269 (direkt/dynamisch unklar) |
| Funktion | `set_diagnostic_capture` | 3198 | `observability.py` | P1 | offen | tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7906 (direkt/dynamisch unklar); tests/test_server.py:8263 (direkt/dynamisch unklar) |
| Funktion | `capture_diagnostic_event` | 3213 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 3227 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:243 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_server.py:5420 (direkt/dynamisch unklar); tests/test_server.py:5422 (direkt/dynamisch unklar); tests/test_server.py:6649 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 3235 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 3239 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:152 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:284 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4153 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 3247 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 3259 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 3274 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 3284 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 3295 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 3304 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 3319 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 3333 | `activities/` | P3 | offen | tests/test_server.py:3611 (direkt/dynamisch unklar); tests/test_server.py:3619 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 3345 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 3361 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 3376 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7631 (direkt/dynamisch unklar); tests/test_server.py:7642 (direkt/dynamisch unklar); tests/test_server.py:7650 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 3383 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3424 (direkt/dynamisch unklar); tests/test_server.py:7632 (direkt/dynamisch unklar); tests/test_server.py:7658 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 3390 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 3405 | `activities/` | P3 | offen | tests/test_server.py:7697 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 3428 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 3441 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 3459 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 3477 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7673 (direkt/dynamisch unklar); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7698 (direkt/dynamisch unklar); tests/test_server.py:7710 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 3492 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3427 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 3507 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 3520 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 3532 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 3535 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 3539 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 3545 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 3550 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 3559 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3335 (direkt/dynamisch unklar); tests/test_server.py:3336 (direkt/dynamisch unklar); tests/test_server.py:3337 (direkt/dynamisch unklar); tests/test_server.py:3338 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 3578 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 3591 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 3595 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 3613 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 3627 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 3643 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 3649 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 3657 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 3670 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 3683 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 3690 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 3708 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 3713 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 3739 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 3749 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 3758 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3442 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 3768 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3783 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3792 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3797 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3805 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3819 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3830 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3849 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3860 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3877 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3901 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3910 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3921 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3940 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar); tests/test_server.py:3310 (direkt/dynamisch unklar); tests/test_server.py:3367 (direkt/dynamisch unklar); tests/test_server.py:3400 (direkt/dynamisch unklar); tests/test_server.py:3427 (direkt/dynamisch unklar); tests/test_server.py:3434 (direkt/dynamisch unklar); tests/test_server.py:3474 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3962 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 3977 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 3982 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 3998 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 4016 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 4035 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 4064 | `planning/` | P4 | offen | tests/test_server.py:3253 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 4081 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 4089 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 4117 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 4124 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 4148 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 4157 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 4174 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 4190 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 4195 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4110 (direkt/dynamisch unklar); tests/test_server.py:4114 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 4196 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 4199 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4113 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 4207 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4112 (direkt/dynamisch unklar); tests/test_server.py:4117 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 4216 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4111 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 4229 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4116 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 4234 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 4256 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 4266 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 4270 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4165 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 4285 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 4286 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 4289 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 4308 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:256 (direkt/dynamisch unklar); tests/test_provider_review.py:264 (direkt/dynamisch unklar); tests/test_provider_review.py:289 (direkt/dynamisch unklar); tests/test_provider_review.py:300 (direkt/dynamisch unklar); tests/test_provider_review.py:304 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 4322 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 4333 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4155 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 4344 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 4352 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 4357 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 4361 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 4379 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 4389 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 4393 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4141 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 4413 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 4424 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 4442 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:4120 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 4479 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 4484 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4209 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 4492 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 4505 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 4529 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 4558 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 4582 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4201 (direkt/dynamisch unklar); tests/test_server.py:4202 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 4595 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 4607 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 4637 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 4666 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 4673 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 4732 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 4755 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:215 (direkt/dynamisch unklar); tests/test_provider_review.py:241 (direkt/dynamisch unklar); tests/test_server.py:231 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4154 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8577 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4797 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:358 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4804 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4815 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:278 (direkt/dynamisch unklar); tests/test_server.py:4208 (direkt/dynamisch unklar); tests/test_server.py:4220 (direkt/dynamisch unklar); tests/test_server.py:7830 (direkt/dynamisch unklar); tests/test_server.py:8578 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4855 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:3273 (direkt/dynamisch unklar); tests/test_server.py:3287 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4878 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1688 (direkt/dynamisch unklar); tests/test_server.py:1720 (direkt/dynamisch unklar); tests/test_server.py:4521 (direkt/dynamisch unklar); tests/test_server.py:4522 (direkt/dynamisch unklar); tests/test_server.py:4523 (direkt/dynamisch unklar); tests/test_server.py:5238 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4885 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4892 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4895 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4907 | `athlete/` | P3 | offen | tests/test_server.py:1134 (direkt/dynamisch unklar); tests/test_server.py:1597 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4916 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1607 (direkt/dynamisch unklar); tests/test_server.py:6755 (direkt/dynamisch unklar); tests/test_server.py:8645 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4925 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:143 (direkt/dynamisch unklar); tests/test_audit_remediation.py:75 (direkt/dynamisch unklar); tests/test_audit_remediation.py:78 (direkt/dynamisch unklar); tests/test_audit_remediation.py:86 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1157 (direkt/dynamisch unklar); tests/test_server.py:1166 (direkt/dynamisch unklar); tests/test_server.py:1182 (direkt/dynamisch unklar); tests/test_server.py:1184 (direkt/dynamisch unklar); tests/test_server.py:1188 (direkt/dynamisch unklar); tests/test_server.py:1202 (direkt/dynamisch unklar); tests/test_server.py:1204 (direkt/dynamisch unklar); tests/test_server.py:1208 (direkt/dynamisch unklar); tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:1223 (direkt/dynamisch unklar); tests/test_server.py:1242 (direkt/dynamisch unklar); tests/test_server.py:146 (direkt/dynamisch unklar); tests/test_server.py:1509 (direkt/dynamisch unklar); tests/test_server.py:1526 (direkt/dynamisch unklar); tests/test_server.py:1569 (direkt/dynamisch unklar); tests/test_server.py:1590 (direkt/dynamisch unklar); tests/test_server.py:1592 (direkt/dynamisch unklar); tests/test_server.py:1603 (direkt/dynamisch unklar); tests/test_server.py:2500 (direkt/dynamisch unklar); tests/test_server.py:6708 (direkt/dynamisch unklar); tests/test_server.py:6736 (direkt/dynamisch unklar); tests/test_server.py:7305 (direkt/dynamisch unklar); tests/test_server.py:7450 (direkt/dynamisch unklar); tests/test_server.py:8630 (direkt/dynamisch unklar); tests/test_server.py:8631 (direkt/dynamisch unklar); tests/test_server.py:8660 (direkt/dynamisch unklar); tests/test_server.py:8677 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4939 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4949 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4956 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4959 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 4971 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 4983 | `athlete/` | P3 | offen | tests/test_server.py:1614 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 5003 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2712 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 5008 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:167 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1577 (direkt/dynamisch unklar); tests/test_server.py:1586 (direkt/dynamisch unklar); tests/test_server.py:1616 (direkt/dynamisch unklar); tests/test_server.py:1620 (direkt/dynamisch unklar); tests/test_server.py:1634 (direkt/dynamisch unklar); tests/test_server.py:1665 (direkt/dynamisch unklar); tests/test_server.py:2701 (direkt/dynamisch unklar); tests/test_server.py:2722 (direkt/dynamisch unklar); tests/test_server.py:2748 (direkt/dynamisch unklar); tests/test_server.py:2767 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 5016 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 5039 | `athlete/` | P3 | offen | tests/test_server.py:1584 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 5049 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 5056 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 5070 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2362 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 5075 | `activities/` | P3 | offen | tests/test_server.py:2359 (direkt/dynamisch unklar); tests/test_server.py:2361 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 5087 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2329 (direkt/dynamisch unklar); tests/test_server.py:2342 (direkt/dynamisch unklar); tests/test_server.py:2352 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 5104 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 5111 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 5125 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 5137 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 5159 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 5171 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 5185 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 5191 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3209 (direkt/dynamisch unklar); tests/test_server.py:3213 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 5201 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3211 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 5208 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 5221 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3195 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 5242 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:44 (direkt/dynamisch unklar); tests/test_audit_remediation.py:55 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:643 (direkt/dynamisch unklar); tests/test_server.py:6458 (direkt/dynamisch unklar); tests/test_server.py:653 (direkt/dynamisch unklar); tests/test_server.py:6540 (direkt/dynamisch unklar); tests/test_server.py:6775 (direkt/dynamisch unklar); tests/test_server.py:6829 (direkt/dynamisch unklar); tests/test_server.py:6863 (direkt/dynamisch unklar); tests/test_server.py:6900 (direkt/dynamisch unklar); tests/test_server.py:6947 (direkt/dynamisch unklar); tests/test_server.py:6984 (direkt/dynamisch unklar); tests/test_server.py:6992 (direkt/dynamisch unklar); tests/test_server.py:7019 (direkt/dynamisch unklar); tests/test_server.py:7047 (direkt/dynamisch unklar) |
| Funktion | `_resolve_calendar_addresses` | 5247 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2565 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_calendar_feed_request` | 5262 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_remaining` | 5285 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_fetch_calendar_address` | 5292 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_failure_log` | 5327 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `fetch_calendar_feed` | 5342 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2535 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2570 (direkt/dynamisch unklar); tests/test_server.py:2583 (direkt/dynamisch unklar); tests/test_server.py:2620 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2649 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2664 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_ical_temporal_value` | 5397 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_TRAINING_MARKER` | 5427 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_INTENSITY_MARKER` | 5428 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_SHORT_ONLY_MARKER` | 5429 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_TRAINING_MARKERS` | 5430 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_description_contains` | 5433 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_impact` | 5437 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_relevant` | 5442 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_no_intensity` | 5448 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_short_only` | 5453 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_DAY_NUMBERS` | 5458 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_values` | 5461 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_integer` | 5476 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_byday` | 5493 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_bydays` | 5507 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_until` | 5524 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rrule` | 5533 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_shift_local` | 5573 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekday_ordinal` | 5577 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_byday` | 5581 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_date_filters` | 5597 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_dates` | 5610 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_apply_bysetpos` | 5624 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_recurrence_start` | 5636 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_record` | 5641 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_daily_recurrence_starts` | 5660 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_candidate_starts` | 5682 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_recurrence_starts` | 5694 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_period` | 5720 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_candidates` | 5730 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_marker` | 5735 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_first_period_index` | 5739 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_recurrence_starts` | 5748 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_starts` | 5773 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_duration` | 5783 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_occurrence_overlaps_window` | 5794 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rule_starts` | 5799 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rdates` | 5812 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_instances` | 5819 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_calendar_window` | 5836 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_property_parameters` | 5844 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_dates` | 5855 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_temporal_property` | 5870 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_id` | 5880 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_event_property` | 5887 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_append_event` | 5908 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_skip_nested_event_line` | 5917 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_parsed_events` | 5925 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_exception_starts` | 5949 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_event_instances` | 5957 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_expanded_events` | 5971 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `parse_ical_calendar` | 5984 | `providers/` | P2 | offen | tests/test_audit_remediation.py:159 (direkt/dynamisch unklar); tests/test_audit_remediation.py:163 (direkt/dynamisch unklar); tests/test_server.py:2393 (direkt/dynamisch unklar); tests/test_server.py:2424 (direkt/dynamisch unklar); tests/test_server.py:2452 (direkt/dynamisch unklar); tests/test_server.py:2458 (direkt/dynamisch unklar); tests/test_server.py:2465 (direkt/dynamisch unklar); tests/test_server.py:2472 (direkt/dynamisch unklar); tests/test_server.py:2477 (direkt/dynamisch unklar); tests/test_server.py:2481 (direkt/dynamisch unklar); tests/test_server.py:2492 (direkt/dynamisch unklar); tests/test_server.py:2507 (direkt/dynamisch unklar); tests/test_server.py:2520 (direkt/dynamisch unklar); tests/test_server.py:2524 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_url` | 5990 | `providers/` | P2 | offen | tests/test_server.py:2543 (direkt/dynamisch unklar); tests/test_server.py:2552 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2673 (direkt/dynamisch unklar); tests/test_server.py:7821 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_external_calendar_events` | 6006 | `providers/` | P2 | offen | tests/test_server.py:2538 (direkt/dynamisch unklar); tests/test_server.py:2594 (direkt/dynamisch unklar); tests/test_server.py:2635 (direkt/dynamisch unklar); tests/test_server.py:2654 (direkt/dynamisch unklar); tests/test_server.py:2667 (direkt/dynamisch unklar); tests/test_server.py:3115 (direkt/dynamisch unklar); tests/test_server.py:3117 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 6017 | `providers/` | P2 | offen | tests/test_server.py:2630 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 6032 | `sync/` | P6 | offen | tests/test_server.py:2537 (direkt/dynamisch unklar); tests/test_server.py:2625 (direkt/dynamisch unklar); tests/test_server.py:2650 (direkt/dynamisch unklar); tests/test_server.py:2666 (direkt/dynamisch unklar); tests/test_server.py:7825 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 6078 | `providers/` | P2 | offen | tests/test_audit_remediation.py:162 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 6093 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 6097 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 6101 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 6107 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 6113 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 6121 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 6139 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 6156 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 6183 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 6190 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 6204 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 6236 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 6245 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 6256 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 6275 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 6287 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 6293 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 6306 | `performance/` | P3 | offen | tests/test_server.py:4211 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 6318 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 6322 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 6332 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 6341 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 6351 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 6362 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 6371 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 6391 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 6405 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1646 (direkt/dynamisch unklar); tests/test_server.py:3117 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 6429 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 6438 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 6450 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 6463 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 6478 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 6484 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 6495 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 6503 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 6514 | `coach/context.py` | P7 | offen | tests/test_server.py:1211 (direkt/dynamisch unklar); tests/test_server.py:3605 (direkt/dynamisch unklar); tests/test_server.py:6330 (direkt/dynamisch unklar); tests/test_server.py:6358 (direkt/dynamisch unklar); tests/test_server.py:6402 (direkt/dynamisch unklar); tests/test_server.py:6420 (direkt/dynamisch unklar); tests/test_server.py:6429 (direkt/dynamisch unklar); tests/test_server.py:6493 (direkt/dynamisch unklar); tests/test_server.py:6716 (direkt/dynamisch unklar); tests/test_server.py:6783 (direkt/dynamisch unklar); tests/test_server.py:6833 (direkt/dynamisch unklar); tests/test_server.py:6869 (direkt/dynamisch unklar); tests/test_server.py:6908 (direkt/dynamisch unklar); tests/test_server.py:6991 (direkt/dynamisch unklar); tests/test_server.py:6997 (direkt/dynamisch unklar); tests/test_server.py:7023 (direkt/dynamisch unklar); tests/test_server.py:7042 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 6531 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 6553 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 6565 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 6566 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 6571 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 6581 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 6599 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 6611 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 6624 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 6636 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 6655 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:28 (direkt/dynamisch unklar); tests/test_audit_remediation.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1070 (direkt/dynamisch unklar); tests/test_server.py:415 (direkt/dynamisch unklar); tests/test_server.py:633 (direkt/dynamisch unklar); tests/test_server.py:6414 (direkt/dynamisch unklar); tests/test_server.py:6440 (direkt/dynamisch unklar); tests/test_server.py:6752 (direkt/dynamisch unklar); tests/test_server.py:6757 (direkt/dynamisch unklar); tests/test_server.py:6791 (direkt/dynamisch unklar); tests/test_server.py:6932 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 6663 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:50 (direkt/dynamisch unklar); tests/test_audit_remediation.py:62 (direkt/dynamisch unklar); tests/test_server.py:6772 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 6693 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 6714 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 6737 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 6752 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 6762 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 6768 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3188 (direkt/dynamisch unklar); tests/test_server.py:3189 (direkt/dynamisch unklar); tests/test_server.py:3190 (direkt/dynamisch unklar); tests/test_server.py:3191 (direkt/dynamisch unklar); tests/test_server.py:3192 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 6773 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 6788 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:29 (direkt/dynamisch unklar); tests/test_server.py:6438 (direkt/dynamisch unklar); tests/test_server.py:6770 (direkt/dynamisch unklar); tests/test_server.py:6785 (direkt/dynamisch unklar); tests/test_server.py:6862 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 6792 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3217 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 6812 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3205 (direkt/dynamisch unklar); tests/test_server.py:3206 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 6828 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 6838 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3243 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 6845 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3244 (direkt/dynamisch unklar); tests/test_server.py:3245 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 6851 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3229 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 6879 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 6885 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 6894 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 6904 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6927 (direkt/dynamisch unklar); tests/test_server.py:6944 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 6944 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 6958 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 6971 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 6997 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 7023 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 7031 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 7039 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 7043 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 7081 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 7089 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 7096 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 7111 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 7123 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 7135 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 7142 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 7146 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 7179 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 7202 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 7221 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 7238 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 7246 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 7276 | `sync/` | P6 | offen | tests/test_audit_remediation.py:43 (direkt/dynamisch unklar); tests/test_audit_remediation.py:54 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:70 (direkt/dynamisch unklar); tests/test_server.py:6413 (direkt/dynamisch unklar); tests/test_server.py:6421 (direkt/dynamisch unklar); tests/test_server.py:6457 (direkt/dynamisch unklar); tests/test_server.py:6627 (direkt/dynamisch unklar); tests/test_server.py:6824 (direkt/dynamisch unklar); tests/test_server.py:6856 (direkt/dynamisch unklar); tests/test_server.py:6857 (direkt/dynamisch unklar); tests/test_server.py:6894 (direkt/dynamisch unklar); tests/test_server.py:6926 (direkt/dynamisch unklar); tests/test_server.py:6942 (direkt/dynamisch unklar); tests/test_server.py:6945 (direkt/dynamisch unklar); tests/test_server.py:6981 (direkt/dynamisch unklar); tests/test_server.py:7014 (direkt/dynamisch unklar); tests/test_server.py:7041 (direkt/dynamisch unklar); tests/test_server.py:7043 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_RATE_LIMIT_HEADERS` | 7332 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_STATUS_KEY` | 7341 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `GEMINI_STATUS_KEY` | 7342 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 7343 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `_retry_after_seconds` | 7346 | `providers/http.py` | P2 | offen | tests/test_server.py:8148 (direkt/dynamisch unklar) |
| Funktion | `_safe_openai_error_token` | 7360 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_diagnostic_details` | 7368 | `observability.py` | P1 | offen | tests/test_server.py:8211 (direkt/dynamisch unklar); tests/test_server.py:8234 (direkt/dynamisch unklar) |
| Funktion | `_openai_error_tokens` | 7391 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_invalid_input_state` | 7401 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_conversation_error` | 7409 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_billing_error` | 7420 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_error_reason` | 7431 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_details` | 7451 | `providers/` | P2 | offen | tests/test_server.py:8136 (direkt/dynamisch unklar); tests/test_server.py:8141 (direkt/dynamisch unklar); tests/test_server.py:8209 (direkt/dynamisch unklar); tests/test_server.py:8232 (direkt/dynamisch unklar); tests/test_server.py:8249 (direkt/dynamisch unklar) |
| Funktion | `safe_openai_log_reason` | 7467 | `observability.py` | P1 | offen | tests/test_server.py:8180 (direkt/dynamisch unklar); tests/test_server.py:8181 (direkt/dynamisch unklar) |
| Funktion | `_provider_error_payload` | 7490 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_tokens` | 7499 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_reason` | 7507 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_error_details` | 7521 | `providers/` | P2 | offen | tests/test_server.py:4647 (direkt/dynamisch unklar); tests/test_server.py:4649 (direkt/dynamisch unklar); tests/test_server.py:4650 (direkt/dynamisch unklar) |
| Funktion | `record_openai_status` | 7527 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_success` | 7542 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_rate_limits` | 7552 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_body` | 7564 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 7572 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 7580 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 7592 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 7597 | `coach/context.py` | P7 | offen | tests/test_server.py:7939 (direkt/dynamisch unklar) |
| Funktion | `_read_http_error_body` | 7607 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_urlopen_interruptibly` | 7618 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_body` | 7645 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_parts` | 7653 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_http_request_started` | 7687 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_http_response` | 7700 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 7715 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 7756 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 7775 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 7825 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 7860 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 7865 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 7893 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1734 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4369 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4438 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4667 (direkt/dynamisch unklar); tests/test_server.py:4708 (direkt/dynamisch unklar); tests/test_server.py:4745 (direkt/dynamisch unklar); tests/test_server.py:4778 (direkt/dynamisch unklar); tests/test_server.py:4838 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5468 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7451 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7845 (direkt/dynamisch unklar); tests/test_server.py:7863 (direkt/dynamisch unklar); tests/test_server.py:7881 (direkt/dynamisch unklar); tests/test_server.py:7915 (direkt/dynamisch unklar); tests/test_server.py:7932 (direkt/dynamisch unklar); tests/test_server.py:8056 (direkt/dynamisch unklar); tests/test_server.py:8092 (direkt/dynamisch unklar); tests/test_server.py:8120 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8505 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 7928 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 7940 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 7949 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 7957 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 7961 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 7967 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 7979 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 7984 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 8010 | `weather/` | P3 | offen | tests/test_server.py:1145 (direkt/dynamisch unklar); tests/test_server.py:1151 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 8020 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 8044 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 8059 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 8078 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 8093 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 8107 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 8128 | `weather/` | P3 | offen | tests/test_server.py:7494 (direkt/dynamisch unklar); tests/test_server.py:7501 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 8175 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 8191 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 8201 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 8222 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 8242 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 8246 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 8269 | `weather/` | P3 | offen | tests/test_audit_remediation.py:105 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:80 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1163 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1189 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1217 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1231 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1250 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1517 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1533 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 8281 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 8292 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 8319 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 8327 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 8340 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 8376 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 8395 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 8401 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 8423 | `weather/` | P3 | offen | tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:146 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:81 (direkt/dynamisch unklar); tests/test_server.py:1164 (direkt/dynamisch unklar); tests/test_server.py:1165 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1252 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1543 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1560 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2981 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7456 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 8441 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 8459 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 8474 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 8481 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 8497 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 8525 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 8538 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 8558 | `sync/` | P6 | offen | tests/test_audit_remediation.py:147 (direkt/dynamisch unklar); tests/test_server.py:1232 (direkt/dynamisch unklar); tests/test_server.py:1233 (direkt/dynamisch unklar); tests/test_server.py:1234 (direkt/dynamisch unklar); tests/test_server.py:1520 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 8574 | `planning/` | P4 | offen | tests/test_server.py:7468 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 8586 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 8599 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 8604 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 8609 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 8613 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 8617 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 8625 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 8641 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 8660 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 8664 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 8673 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 8685 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 8706 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 8733 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 8748 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 8761 | `planning/` | P4 | offen | tests/test_server.py:2928 (direkt/dynamisch unklar); tests/test_server.py:2930 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 8799 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 8820 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 8840 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 8858 | `planning/` | P4 | offen | tests/test_server.py:2893 (direkt/dynamisch unklar); tests/test_server.py:2953 (direkt/dynamisch unklar); tests/test_server.py:2992 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 8868 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:2954 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 8892 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 8912 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 8918 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 8941 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 8951 | `planning/` | P4 | offen | tests/test_server.py:2853 (direkt/dynamisch unklar); tests/test_server.py:3570 (direkt/dynamisch unklar); tests/test_server.py:6699 (direkt/dynamisch unklar); tests/test_server.py:7067 (direkt/dynamisch unklar); tests/test_server.py:7096 (direkt/dynamisch unklar); tests/test_server.py:7225 (direkt/dynamisch unklar); tests/test_server.py:7249 (direkt/dynamisch unklar); tests/test_server.py:7270 (direkt/dynamisch unklar); tests/test_server.py:7286 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 8989 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 8990 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 8995 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 8998 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 9007 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 9011 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 9020 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 9045 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 9052 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 9063 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3800 (direkt/dynamisch unklar); tests/test_server.py:3817 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 9077 | `planning/` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:3082 (direkt/dynamisch unklar); tests/test_server.py:3174 (direkt/dynamisch unklar); tests/test_server.py:3250 (direkt/dynamisch unklar); tests/test_server.py:3836 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 9100 | `planning/` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 9113 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3762 (direkt/dynamisch unklar); tests/test_server.py:3812 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 9140 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 9150 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 9160 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 9167 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 9185 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 9195 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 9208 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 9221 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 9236 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 9245 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:3585 (direkt/dynamisch unklar); tests/test_server.py:3590 (direkt/dynamisch unklar); tests/test_server.py:3591 (direkt/dynamisch unklar); tests/test_server.py:3601 (direkt/dynamisch unklar); tests/test_server.py:3606 (direkt/dynamisch unklar); tests/test_server.py:5041 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 9260 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 9273 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 9297 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 9308 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 9323 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1539 (direkt/dynamisch unklar); tests/test_server.py:1556 (direkt/dynamisch unklar); tests/test_server.py:2598 (direkt/dynamisch unklar); tests/test_server.py:2677 (direkt/dynamisch unklar); tests/test_server.py:2697 (direkt/dynamisch unklar); tests/test_server.py:2744 (direkt/dynamisch unklar); tests/test_server.py:2763 (direkt/dynamisch unklar); tests/test_server.py:2774 (direkt/dynamisch unklar); tests/test_server.py:2806 (direkt/dynamisch unklar); tests/test_server.py:357 (direkt/dynamisch unklar); tests/test_server.py:3784 (direkt/dynamisch unklar); tests/test_server.py:3869 (direkt/dynamisch unklar); tests/test_server.py:3897 (direkt/dynamisch unklar); tests/test_server.py:3918 (direkt/dynamisch unklar); tests/test_server.py:3920 (direkt/dynamisch unklar); tests/test_server.py:3927 (direkt/dynamisch unklar); tests/test_server.py:5552 (direkt/dynamisch unklar); tests/test_server.py:5562 (direkt/dynamisch unklar); tests/test_server.py:5590 (direkt/dynamisch unklar); tests/test_server.py:5835 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6301 (direkt/dynamisch unklar); tests/test_server.py:770 (direkt/dynamisch unklar); tests/test_server.py:803 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 9340 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5556 (direkt/dynamisch unklar); tests/test_server.py:5567 (direkt/dynamisch unklar); tests/test_server.py:5583 (direkt/dynamisch unklar); tests/test_server.py:5595 (direkt/dynamisch unklar); tests/test_server.py:5611 (direkt/dynamisch unklar); tests/test_server.py:5634 (direkt/dynamisch unklar); tests/test_server.py:5656 (direkt/dynamisch unklar); tests/test_server.py:797 (direkt/dynamisch unklar); tests/test_server.py:825 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 9348 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 9356 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 9361 | `planning/` | P4 | offen | tests/test_server.py:5558 (direkt/dynamisch unklar); tests/test_server.py:5568 (direkt/dynamisch unklar); tests/test_server.py:809 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 9378 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 9383 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 9395 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 9413 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 9442 | `planning/` | P4 | offen | tests/test_audit_remediation.py:223 (direkt/dynamisch unklar); tests/test_server.py:1570 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 9454 | `planning/` | P4 | offen | tests/test_server.py:2718 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 9471 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7733 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 9488 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 9513 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 9527 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 9536 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 9554 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 9568 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 9576 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 9594 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 9603 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 9617 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 9632 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 9649 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 9666 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 9690 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 9722 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 9748 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 9769 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 9777 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 9796 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 9819 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1547 (direkt/dynamisch unklar); tests/test_server.py:1564 (direkt/dynamisch unklar); tests/test_server.py:2607 (direkt/dynamisch unklar); tests/test_server.py:2686 (direkt/dynamisch unklar); tests/test_server.py:2702 (direkt/dynamisch unklar); tests/test_server.py:2716 (direkt/dynamisch unklar); tests/test_server.py:2723 (direkt/dynamisch unklar); tests/test_server.py:2749 (direkt/dynamisch unklar); tests/test_server.py:2768 (direkt/dynamisch unklar); tests/test_server.py:2778 (direkt/dynamisch unklar); tests/test_server.py:2815 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 9850 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 9861 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 9877 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 9892 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 9902 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 9941 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 9956 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 9964 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 9986 | `planning/` | P4 | offen | tests/test_audit_remediation.py:227 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2707 (direkt/dynamisch unklar); tests/test_server.py:2734 (direkt/dynamisch unklar); tests/test_server.py:2753 (direkt/dynamisch unklar); tests/test_server.py:2758 (direkt/dynamisch unklar); tests/test_server.py:2770 (direkt/dynamisch unklar); tests/test_server.py:2779 (direkt/dynamisch unklar); tests/test_server.py:2782 (direkt/dynamisch unklar); tests/test_server.py:2816 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 10016 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 10040 | `planning/` | P4 | offen | tests/test_server.py:1571 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 10044 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 10052 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 10068 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 10081 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 10086 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 10091 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 10100 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 10109 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 10131 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 10137 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 10141 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 10154 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 10168 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 10174 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 10187 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 10200 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 10221 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 10237 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 10247 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 10263 | `planning/` | P4 | offen | tests/test_server.py:2794 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 10286 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 10302 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 10305 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 10329 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 10338 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:3001 (direkt/dynamisch unklar); tests/test_server.py:3123 (direkt/dynamisch unklar); tests/test_server.py:3144 (direkt/dynamisch unklar); tests/test_server.py:327 (direkt/dynamisch unklar); tests/test_server.py:3597 (direkt/dynamisch unklar); tests/test_server.py:4904 (direkt/dynamisch unklar); tests/test_server.py:4926 (direkt/dynamisch unklar); tests/test_server.py:4982 (direkt/dynamisch unklar); tests/test_server.py:4999 (direkt/dynamisch unklar); tests/test_server.py:5017 (direkt/dynamisch unklar); tests/test_server.py:5035 (direkt/dynamisch unklar); tests/test_server.py:5056 (direkt/dynamisch unklar); tests/test_server.py:5079 (direkt/dynamisch unklar); tests/test_server.py:5124 (direkt/dynamisch unklar); tests/test_server.py:5146 (direkt/dynamisch unklar); tests/test_server.py:5169 (direkt/dynamisch unklar); tests/test_server.py:5185 (direkt/dynamisch unklar); tests/test_server.py:5202 (direkt/dynamisch unklar); tests/test_server.py:5265 (direkt/dynamisch unklar); tests/test_server.py:5327 (direkt/dynamisch unklar); tests/test_server.py:5336 (direkt/dynamisch unklar); tests/test_server.py:5494 (direkt/dynamisch unklar); tests/test_server.py:5525 (direkt/dynamisch unklar); tests/test_server.py:5688 (direkt/dynamisch unklar); tests/test_server.py:5718 (direkt/dynamisch unklar); tests/test_server.py:5736 (direkt/dynamisch unklar); tests/test_server.py:5741 (direkt/dynamisch unklar); tests/test_server.py:5750 (direkt/dynamisch unklar); tests/test_server.py:5754 (direkt/dynamisch unklar); tests/test_server.py:5759 (direkt/dynamisch unklar); tests/test_server.py:5768 (direkt/dynamisch unklar); tests/test_server.py:5787 (direkt/dynamisch unklar); tests/test_server.py:5790 (direkt/dynamisch unklar); tests/test_server.py:5816 (direkt/dynamisch unklar); tests/test_server.py:657 (direkt/dynamisch unklar); tests/test_server.py:680 (direkt/dynamisch unklar); tests/test_server.py:697 (direkt/dynamisch unklar); tests/test_server.py:723 (direkt/dynamisch unklar); tests/test_server.py:727 (direkt/dynamisch unklar); tests/test_server.py:7329 (direkt/dynamisch unklar); tests/test_server.py:830 (direkt/dynamisch unklar); tests/test_server.py:850 (direkt/dynamisch unklar); tests/test_server.py:854 (direkt/dynamisch unklar); tests/test_server.py:877 (direkt/dynamisch unklar); tests/test_server.py:925 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 10356 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2710 (direkt/dynamisch unklar); tests/test_server.py:2711 (direkt/dynamisch unklar); tests/test_server.py:2719 (direkt/dynamisch unklar); tests/test_server.py:2784 (direkt/dynamisch unklar); tests/test_server.py:3055 (direkt/dynamisch unklar); tests/test_server.py:3065 (direkt/dynamisch unklar); tests/test_server.py:3068 (direkt/dynamisch unklar); tests/test_server.py:3079 (direkt/dynamisch unklar); tests/test_server.py:3095 (direkt/dynamisch unklar); tests/test_server.py:3166 (direkt/dynamisch unklar); tests/test_server.py:3907 (direkt/dynamisch unklar); tests/test_server.py:3911 (direkt/dynamisch unklar); tests/test_server.py:3919 (direkt/dynamisch unklar); tests/test_server.py:3923 (direkt/dynamisch unklar); tests/test_server.py:4917 (direkt/dynamisch unklar); tests/test_server.py:4943 (direkt/dynamisch unklar); tests/test_server.py:4960 (direkt/dynamisch unklar); tests/test_server.py:4994 (direkt/dynamisch unklar); tests/test_server.py:5012 (direkt/dynamisch unklar); tests/test_server.py:5030 (direkt/dynamisch unklar); tests/test_server.py:5069 (direkt/dynamisch unklar); tests/test_server.py:5093 (direkt/dynamisch unklar); tests/test_server.py:5115 (direkt/dynamisch unklar); tests/test_server.py:5182 (direkt/dynamisch unklar); tests/test_server.py:5198 (direkt/dynamisch unklar); tests/test_server.py:5219 (direkt/dynamisch unklar); tests/test_server.py:5519 (direkt/dynamisch unklar); tests/test_server.py:5520 (direkt/dynamisch unklar); tests/test_server.py:5609 (direkt/dynamisch unklar); tests/test_server.py:5683 (direkt/dynamisch unklar); tests/test_server.py:5811 (direkt/dynamisch unklar); tests/test_server.py:5841 (direkt/dynamisch unklar); tests/test_server.py:6211 (direkt/dynamisch unklar); tests/test_server.py:720 (direkt/dynamisch unklar); tests/test_server.py:748 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 10368 | `planning/` | P4 | offen | tests/test_server.py:3667 (direkt/dynamisch unklar); tests/test_server.py:3878 (direkt/dynamisch unklar); tests/test_server.py:3940 (direkt/dynamisch unklar); tests/test_server.py:6240 (direkt/dynamisch unklar); tests/test_server.py:6277 (direkt/dynamisch unklar); tests/test_server.py:6321 (direkt/dynamisch unklar); tests/test_server.py:6480 (direkt/dynamisch unklar); tests/test_server.py:8651 (direkt/dynamisch unklar); tests/test_server.py:8741 (direkt/dynamisch unklar); tests/test_server.py:8742 (direkt/dynamisch unklar); tests/test_server.py:948 (direkt/dynamisch unklar); tests/test_server.py:951 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 10396 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3866 (direkt/dynamisch unklar); tests/test_server.py:490 (direkt/dynamisch unklar); tests/test_server.py:684 (direkt/dynamisch unklar); tests/test_server.py:902 (direkt/dynamisch unklar); tests/test_server.py:922 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 10419 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 10434 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 10451 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 10466 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 10489 | `planning/` | P4 | offen | tests/test_server.py:1383 (direkt/dynamisch unklar); tests/test_server.py:1700 (direkt/dynamisch unklar); tests/test_server.py:3652 (direkt/dynamisch unklar); tests/test_server.py:3658 (direkt/dynamisch unklar); tests/test_server.py:3682 (direkt/dynamisch unklar); tests/test_server.py:4291 (direkt/dynamisch unklar); tests/test_server.py:4307 (direkt/dynamisch unklar); tests/test_server.py:4325 (direkt/dynamisch unklar); tests/test_server.py:4340 (direkt/dynamisch unklar); tests/test_server.py:6294 (direkt/dynamisch unklar); tests/test_server.py:6494 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 10514 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3663 (direkt/dynamisch unklar); tests/test_server.py:3672 (direkt/dynamisch unklar); tests/test_server.py:3674 (direkt/dynamisch unklar); tests/test_server.py:3675 (direkt/dynamisch unklar); tests/test_server.py:3677 (direkt/dynamisch unklar); tests/test_server.py:3679 (direkt/dynamisch unklar); tests/test_server.py:3887 (direkt/dynamisch unklar); tests/test_server.py:3950 (direkt/dynamisch unklar); tests/test_server.py:4295 (direkt/dynamisch unklar); tests/test_server.py:4303 (direkt/dynamisch unklar); tests/test_server.py:4311 (direkt/dynamisch unklar); tests/test_server.py:4321 (direkt/dynamisch unklar); tests/test_server.py:4329 (direkt/dynamisch unklar); tests/test_server.py:4337 (direkt/dynamisch unklar); tests/test_server.py:4344 (direkt/dynamisch unklar); tests/test_server.py:6169 (direkt/dynamisch unklar); tests/test_server.py:6258 (direkt/dynamisch unklar); tests/test_server.py:6311 (direkt/dynamisch unklar); tests/test_server.py:6546 (direkt/dynamisch unklar); tests/test_server.py:8657 (direkt/dynamisch unklar); tests/test_server.py:918 (direkt/dynamisch unklar); tests/test_server.py:919 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 10521 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 10538 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 10539 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 10540 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 10541 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 10544 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 10551 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 10556 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 10566 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 10573 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1679 (direkt/dynamisch unklar); tests/test_server.py:1680 (direkt/dynamisch unklar); tests/test_server.py:1681 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 10600 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:290 (direkt/dynamisch unklar); tests/test_audit_remediation.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1689 (direkt/dynamisch unklar); tests/test_server.py:1690 (direkt/dynamisch unklar); tests/test_server.py:1695 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 10632 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1704 (direkt/dynamisch unklar); tests/test_server.py:1705 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 10660 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1857 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 10681 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 10701 | `activities/` | P3 | offen | tests/test_server.py:486 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 10742 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 10747 | `planning/` | P4 | offen | tests/test_server.py:2693 (direkt/dynamisch unklar); tests/test_server.py:2706 (direkt/dynamisch unklar); tests/test_server.py:2709 (direkt/dynamisch unklar); tests/test_server.py:2757 (direkt/dynamisch unklar); tests/test_server.py:2783 (direkt/dynamisch unklar); tests/test_server.py:2817 (direkt/dynamisch unklar); tests/test_server.py:2820 (direkt/dynamisch unklar); tests/test_server.py:2980 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3030 (direkt/dynamisch unklar); tests/test_server.py:3047 (direkt/dynamisch unklar); tests/test_server.py:3141 (direkt/dynamisch unklar); tests/test_server.py:3786 (direkt/dynamisch unklar); tests/test_server.py:3875 (direkt/dynamisch unklar); tests/test_server.py:3933 (direkt/dynamisch unklar); tests/test_server.py:4304 (direkt/dynamisch unklar); tests/test_server.py:4322 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 10752 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 10759 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 10770 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 10782 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 10807 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 10823 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 10831 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 10845 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 10857 | `planning/` | P4 | offen | tests/test_server.py:3015 (direkt/dynamisch unklar); tests/test_server.py:3030 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 10876 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 10881 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 10898 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 10912 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 10919 | `calendar/` | P3 | offen | tests/test_server.py:3115 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 10934 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 10947 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 10960 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 11017 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 11034 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 11074 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 11081 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 11089 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 11097 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 11110 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 11120 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 11132 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 11161 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 11171 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 11193 | `planning/` | P4 | offen | tests/test_server.py:263 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 11210 | `sync/` | P6 | offen | tests/test_server.py:3906 (direkt/dynamisch unklar); tests/test_server.py:3910 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 11215 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 11233 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 11240 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 11249 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 11264 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 11269 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 11275 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 11283 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 11295 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 11304 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 11321 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 11341 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 11344 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 11357 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 11369 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 11392 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 11412 | `planning/` | P4 | offen | tests/test_server.py:6064 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6093 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6106 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6126 (direkt/dynamisch unklar); tests/test_server.py:613 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6205 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6229 (Monkeypatch/getattr/sys.modules); tests/test_server.py:626 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6270 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6288 (direkt/dynamisch unklar) |
| Funktion | `plan_library_workout_remote` | 11453 | `planning/` | P4 | offen | tests/test_server.py:6469 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 11457 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 11478 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 11493 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 11499 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 11506 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 11521 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 11536 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 11546 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 11552 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 11567 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 11575 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1387 (direkt/dynamisch unklar); tests/test_server.py:3670 (direkt/dynamisch unklar); tests/test_server.py:3673 (direkt/dynamisch unklar); tests/test_server.py:3676 (direkt/dynamisch unklar); tests/test_server.py:3678 (direkt/dynamisch unklar); tests/test_server.py:3684 (direkt/dynamisch unklar); tests/test_server.py:3686 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 11599 | `planning/` | P4 | offen | tests/test_server.py:6484 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 11618 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 11634 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 11646 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 11660 | `calendar/` | P3 | offen | tests/test_server.py:7946 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 11695 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 11725 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 11743 | `sync/` | P6 | offen | tests/test_server.py:1858 (direkt/dynamisch unklar); tests/test_server.py:2103 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 11747 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 11762 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 11781 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 11794 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 11808 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 11827 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 11840 | `sync/` | P6 | offen | tests/test_server.py:3885 (direkt/dynamisch unklar); tests/test_server.py:3891 (direkt/dynamisch unklar); tests/test_server.py:3947 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 11855 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 11863 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 11887 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 11892 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 11915 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 11922 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 11947 | `planning/` | P4 | offen | tests/test_server.py:4297 (direkt/dynamisch unklar); tests/test_server.py:4317 (direkt/dynamisch unklar); tests/test_server.py:4332 (direkt/dynamisch unklar); tests/test_server.py:4346 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 11961 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 11970 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 11981 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 11990 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 12002 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 12015 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 12019 | `sync/` | P6 | offen | tests/test_server.py:6533 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8749 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 12032 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 12045 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 12049 | `sync/` | P6 | offen | tests/test_server.py:264 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 12068 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 12083 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 12098 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 12114 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 12127 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 12144 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 12155 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 12171 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 12189 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 12208 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 12231 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 12246 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 12255 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 12276 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 12294 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 12318 | `planning/` | P4 | offen | tests/test_server.py:2751 (direkt/dynamisch unklar); tests/test_server.py:2769 (direkt/dynamisch unklar); tests/test_server.py:3052 (direkt/dynamisch unklar); tests/test_server.py:3066 (direkt/dynamisch unklar); tests/test_server.py:3096 (direkt/dynamisch unklar); tests/test_server.py:3128 (direkt/dynamisch unklar); tests/test_server.py:3135 (direkt/dynamisch unklar); tests/test_server.py:3137 (direkt/dynamisch unklar); tests/test_server.py:3139 (direkt/dynamisch unklar); tests/test_server.py:3149 (direkt/dynamisch unklar); tests/test_server.py:3151 (direkt/dynamisch unklar); tests/test_server.py:3600 (direkt/dynamisch unklar); tests/test_server.py:3874 (direkt/dynamisch unklar); tests/test_server.py:3922 (direkt/dynamisch unklar); tests/test_server.py:5040 (direkt/dynamisch unklar); tests/test_server.py:5740 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 12344 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 12355 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 12366 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 12376 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 12382 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 12393 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 12405 | `planning/` | P4 | offen | tests/test_server.py:3098 (direkt/dynamisch unklar); tests/test_server.py:3101 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 12423 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:129 (direkt/dynamisch unklar); tests/test_provider_review.py:91 (direkt/dynamisch unklar); tests/test_server.py:1647 (direkt/dynamisch unklar); tests/test_server.py:1648 (direkt/dynamisch unklar); tests/test_server.py:2979 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5419 (direkt/dynamisch unklar); tests/test_server.py:5421 (direkt/dynamisch unklar); tests/test_server.py:6538 (direkt/dynamisch unklar); tests/test_server.py:6561 (direkt/dynamisch unklar); tests/test_server.py:7718 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 12428 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:109 (direkt/dynamisch unklar); tests/test_provider_review.py:229 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:62 (direkt/dynamisch unklar); tests/test_provider_review.py:86 (direkt/dynamisch unklar); tests/test_server.py:1415 (direkt/dynamisch unklar); tests/test_server.py:1627 (direkt/dynamisch unklar); tests/test_server.py:1664 (direkt/dynamisch unklar); tests/test_server.py:1672 (direkt/dynamisch unklar); tests/test_server.py:1712 (direkt/dynamisch unklar); tests/test_server.py:2322 (direkt/dynamisch unklar); tests/test_server.py:2347 (direkt/dynamisch unklar); tests/test_server.py:3626 (direkt/dynamisch unklar); tests/test_server.py:3691 (direkt/dynamisch unklar); tests/test_server.py:4313 (direkt/dynamisch unklar); tests/test_server.py:441 (direkt/dynamisch unklar); tests/test_server.py:5373 (direkt/dynamisch unklar); tests/test_server.py:5414 (direkt/dynamisch unklar); tests/test_server.py:6550 (direkt/dynamisch unklar); tests/test_server.py:7331 (direkt/dynamisch unklar); tests/test_server.py:7709 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 12438 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 12464 | `sync/` | P6 | offen | tests/test_server.py:1000 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 12489 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 12494 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 12504 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 12512 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 12543 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 12565 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 12576 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 12590 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 12612 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 12629 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 12663 | `planning/` | P4 | offen | tests/test_server.py:3043 (direkt/dynamisch unklar); tests/test_server.py:3045 (direkt/dynamisch unklar); tests/test_server.py:3053 (direkt/dynamisch unklar); tests/test_server.py:3064 (direkt/dynamisch unklar); tests/test_server.py:3067 (direkt/dynamisch unklar); tests/test_server.py:3075 (direkt/dynamisch unklar); tests/test_server.py:3094 (direkt/dynamisch unklar); tests/test_server.py:3097 (direkt/dynamisch unklar); tests/test_server.py:3100 (direkt/dynamisch unklar); tests/test_server.py:3584 (direkt/dynamisch unklar); tests/test_server.py:3589 (direkt/dynamisch unklar); tests/test_server.py:5668 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 12711 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 12727 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 12739 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 12751 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 12756 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 12766 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 12773 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 12780 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 12791 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 12806 | `sync/` | P6 | offen | tests/test_server.py:6396 (direkt/dynamisch unklar); tests/test_server.py:6534 (direkt/dynamisch unklar); tests/test_server.py:6560 (direkt/dynamisch unklar); tests/test_server.py:6570 (direkt/dynamisch unklar); tests/test_server.py:6646 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 12841 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 12856 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 12885 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 12914 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 12934 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 12951 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 13008 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 13023 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 13034 | `sync/` | P6 | offen | tests/test_audit_remediation.py:284 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:571 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6065 (direkt/dynamisch unklar); tests/test_server.py:6080 (direkt/dynamisch unklar); tests/test_server.py:6095 (direkt/dynamisch unklar); tests/test_server.py:6108 (direkt/dynamisch unklar); tests/test_server.py:6137 (direkt/dynamisch unklar); tests/test_server.py:616 (direkt/dynamisch unklar); tests/test_server.py:6166 (direkt/dynamisch unklar); tests/test_server.py:6206 (direkt/dynamisch unklar); tests/test_server.py:6207 (direkt/dynamisch unklar); tests/test_server.py:6231 (direkt/dynamisch unklar); tests/test_server.py:6233 (direkt/dynamisch unklar); tests/test_server.py:6253 (direkt/dynamisch unklar); tests/test_server.py:6271 (direkt/dynamisch unklar); tests/test_server.py:629 (direkt/dynamisch unklar); tests/test_server.py:6388 (direkt/dynamisch unklar); tests/test_server.py:6489 (direkt/dynamisch unklar); tests/test_server.py:7762 (direkt/dynamisch unklar); tests/test_server.py:8029 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 13068 | `performance/` | P3 | offen | tests/test_provider_review.py:76 (direkt/dynamisch unklar); tests/test_server.py:547 (Monkeypatch/getattr/sys.modules); tests/test_server.py:560 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7323 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 13092 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 13099 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 13106 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 13124 | `activities/` | P3 | offen | tests/test_server.py:5287 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 13136 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 13153 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 13166 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 13183 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 13204 | `performance/` | P3 | offen | tests/test_server.py:7220 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 13213 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 13225 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 13241 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 13256 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 13292 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 13302 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 13316 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 13332 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 13349 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 13359 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 13370 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 13384 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 13396 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 13401 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 13433 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 13442 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 13448 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 13455 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 13469 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 13482 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 13486 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 13515 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 13522 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 13559 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 13579 | `performance/` | P3 | offen | tests/test_server.py:3345 (direkt/dynamisch unklar); tests/test_server.py:3354 (direkt/dynamisch unklar); tests/test_server.py:3462 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 13608 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 13622 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 13638 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 13646 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 13656 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 13683 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 13698 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 13721 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 13739 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 13771 | `activities/` | P3 | offen | tests/test_server.py:7119 (direkt/dynamisch unklar); tests/test_server.py:7141 (direkt/dynamisch unklar); tests/test_server.py:7147 (direkt/dynamisch unklar); tests/test_server.py:7156 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 13816 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 13849 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 13870 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 13882 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 13902 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 13915 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 13946 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 13976 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 13987 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 14030 | `performance/` | P3 | offen | tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:3485 (direkt/dynamisch unklar); tests/test_server.py:3515 (direkt/dynamisch unklar); tests/test_server.py:3544 (direkt/dynamisch unklar); tests/test_server.py:3565 (direkt/dynamisch unklar); tests/test_server.py:3577 (direkt/dynamisch unklar); tests/test_server.py:7058 (direkt/dynamisch unklar); tests/test_server.py:7080 (direkt/dynamisch unklar); tests/test_server.py:7107 (direkt/dynamisch unklar); tests/test_server.py:7176 (direkt/dynamisch unklar); tests/test_server.py:7190 (direkt/dynamisch unklar); tests/test_server.py:7206 (direkt/dynamisch unklar); tests/test_server.py:7237 (direkt/dynamisch unklar); tests/test_server.py:7258 (direkt/dynamisch unklar); tests/test_server.py:7280 (direkt/dynamisch unklar); tests/test_server.py:7300 (direkt/dynamisch unklar); tests/test_server.py:7306 (direkt/dynamisch unklar); tests/test_server.py:7310 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 14101 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 14115 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 14119 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 14123 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 14128 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 14132 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 14136 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 14140 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 14144 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 14163 | `coach/context.py` | P7 | offen | tests/test_server.py:5277 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 14182 | `coach/context.py` | P7 | offen | tests/test_server.py:5269 (direkt/dynamisch unklar); tests/test_server.py:5306 (direkt/dynamisch unklar); tests/test_server.py:5307 (direkt/dynamisch unklar); tests/test_server.py:5328 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 14228 | `coach/context.py` | P7 | offen | tests/test_server.py:1534 (direkt/dynamisch unklar); tests/test_server.py:1608 (direkt/dynamisch unklar); tests/test_server.py:2336 (direkt/dynamisch unklar); tests/test_server.py:3298 (direkt/dynamisch unklar); tests/test_server.py:5349 (direkt/dynamisch unklar); tests/test_server.py:5355 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6731 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 14293 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 14311 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 14321 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 14338 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:245 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:247 (direkt/dynamisch unklar); tests/test_provider_review.py:281 (direkt/dynamisch unklar); tests/test_server.py:3664 (direkt/dynamisch unklar); tests/test_server.py:5345 (direkt/dynamisch unklar); tests/test_server.py:5356 (direkt/dynamisch unklar); tests/test_server.py:5357 (direkt/dynamisch unklar); tests/test_server.py:5374 (direkt/dynamisch unklar); tests/test_server.py:5385 (direkt/dynamisch unklar); tests/test_server.py:5417 (direkt/dynamisch unklar); tests/test_server.py:6709 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 14378 | `coach/context.py` | P7 | offen | tests/test_server.py:5239 (direkt/dynamisch unklar); tests/test_server.py:5379 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 14434 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 14464 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_openai_usage_summary_unlocked` | 14474 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_usage_summary` | 14497 | `providers/` | P2 | offen | tests/test_server.py:8093 (direkt/dynamisch unklar); tests/test_server.py:8123 (direkt/dynamisch unklar); tests/test_server.py:8315 (direkt/dynamisch unklar); tests/test_server.py:8325 (direkt/dynamisch unklar); tests/test_server.py:8349 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8516 (direkt/dynamisch unklar); tests/test_server.py:8554 (direkt/dynamisch unklar) |
| Funktion | `_record_openai_usage_unlocked` | 14505 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_usage` | 14534 | `providers/` | P2 | offen | tests/test_server.py:5859 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8511 (direkt/dynamisch unklar); tests/test_server.py:8552 (direkt/dynamisch unklar) |
| Funktion | `_validate_openai_response` | 14541 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8493 (direkt/dynamisch unklar); tests/test_server.py:8496 (direkt/dynamisch unklar); tests/test_server.py:8499 (direkt/dynamisch unklar) |
| Funktion | `openai_endpoint` | 14563 | `providers/` | P2 | offen | tests/test_server.py:4815 (direkt/dynamisch unklar); tests/test_server.py:4816 (direkt/dynamisch unklar); tests/test_server.py:4818 (direkt/dynamisch unklar); tests/test_server.py:4827 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 14580 | `providers/` | P2 | offen | tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4839 (direkt/dynamisch unklar); tests/test_server.py:5462 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5471 (direkt/dynamisch unklar); tests/test_server.py:6064 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7321 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8194 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8506 (direkt/dynamisch unklar) |
| Funktion | `multipart_form_data` | 14604 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VOICE_AUDIO_TYPES` | 14629 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `normalized_audio_type` | 14641 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `transcribe_audio` | 14645 | `providers/` | P2 | offen | tests/test_server.py:4578 (direkt/dynamisch unklar); tests/test_server.py:4798 (direkt/dynamisch unklar); tests/test_server.py:4871 (direkt/dynamisch unklar); tests/test_server.py:4873 (direkt/dynamisch unklar) |
| Funktion | `_provider_usage_summary` | 14697 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_usage_summary` | 14714 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_status` | 14719 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_usage` | 14725 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_content_has_function_response` | 14744 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 14749 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 14756 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 14767 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 14783 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 14795 | `providers/` | P2 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4501 (direkt/dynamisch unklar); tests/test_server.py:4633 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 14803 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 14815 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 14831 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 14847 | `providers/` | P2 | offen | tests/test_server.py:4512 (direkt/dynamisch unklar); tests/test_server.py:4517 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 14869 | `providers/` | P2 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_text` | 14891 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_tools` | 14895 | `providers/` | P2 | offen | tests/test_server.py:4673 (direkt/dynamisch unklar) |
| Funktion | `_gemini_request_payload` | 14899 | `providers/` | P2 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4529 (direkt/dynamisch unklar); tests/test_server.py:4542 (direkt/dynamisch unklar); tests/test_server.py:4612 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 14995 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 15014 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 15053 | `providers/` | P2 | offen | tests/test_server.py:4370 (direkt/dynamisch unklar); tests/test_server.py:4372 (direkt/dynamisch unklar); tests/test_server.py:4439 (direkt/dynamisch unklar); tests/test_server.py:4442 (direkt/dynamisch unklar); tests/test_server.py:4564 (direkt/dynamisch unklar); tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 15060 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `request_ai_provider` | 15201 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 15206 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:245 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4609 (direkt/dynamisch unklar); tests/test_server.py:5463 (direkt/dynamisch unklar); tests/test_server.py:5854 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8195 (direkt/dynamisch unklar) |
| Funktion | `_openai_response_id` | 15231 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `retrieve_openai_response` | 15238 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 15253 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 15271 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5860 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 15308 | `coach/context.py` | P7 | offen | tests/test_server.py:6120 (direkt/dynamisch unklar) |
| Funktion | `_notify_openai_stream_response_id` | 15313 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_forward_openai_stream_delta` | 15326 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_stream_final_response` | 15334 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_consume_openai_sse_event` | 15341 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_read_openai_stream_response` | 15360 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_openai_stream_failure` | 15396 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_capture_openai_stream_failure` | 15414 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 15428 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 15440 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 15451 | `providers/` | P2 | offen | tests/test_server.py:8175 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 15468 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 15484 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 15499 | `providers/` | P2 | offen | tests/test_server.py:4863 (direkt/dynamisch unklar); tests/test_server.py:8267 (direkt/dynamisch unklar); tests/test_server.py:8308 (direkt/dynamisch unklar); tests/test_server.py:8322 (direkt/dynamisch unklar); tests/test_server.py:8346 (direkt/dynamisch unklar); tests/test_server.py:8371 (direkt/dynamisch unklar); tests/test_server.py:8377 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 15576 | `coach/streams.py` | P8 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4414 (direkt/dynamisch unklar); tests/test_server.py:5960 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8378 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 15602 | `coach/proposals.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:245 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 15621 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 15634 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 15652 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 15665 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 15671 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 15679 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4642 (direkt/dynamisch unklar); tests/test_server.py:5485 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 15688 | `providers/` | P2 | offen | tests/test_server.py:4354 (direkt/dynamisch unklar); tests/test_server.py:4386 (direkt/dynamisch unklar); tests/test_server.py:4420 (direkt/dynamisch unklar); tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 15692 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 15693 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 15696 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 15700 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 15713 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 15738 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 15762 | `activities/` | P3 | offen | tests/test_server.py:7712 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 15782 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8615 (direkt/dynamisch unklar); tests/test_server.py:8626 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 15804 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 15813 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 15835 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8642 (direkt/dynamisch unklar); tests/test_server.py:8654 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 15859 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 15868 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8643 (direkt/dynamisch unklar); tests/test_server.py:8655 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 15897 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 15901 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:261 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5985 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 15918 | `coach/proposals.py` | P7 | offen | tests/test_server.py:6014 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 15922 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:6005 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 15934 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 15951 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 15978 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 15987 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 16004 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 16056 | `sync/` | P6 | offen | tests/test_audit_remediation.py:252 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4622 (direkt/dynamisch unklar); tests/test_server.py:5871 (direkt/dynamisch unklar); tests/test_server.py:5899 (direkt/dynamisch unklar); tests/test_server.py:5920 (direkt/dynamisch unklar); tests/test_server.py:5947 (direkt/dynamisch unklar); tests/test_server.py:5974 (direkt/dynamisch unklar); tests/test_server.py:5998 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 16089 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5918 (direkt/dynamisch unklar); tests/test_server.py:8386 (direkt/dynamisch unklar); tests/test_server.py:8389 (direkt/dynamisch unklar); tests/test_server.py:8403 (direkt/dynamisch unklar); tests/test_server.py:8424 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8451 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8464 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 16103 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 16118 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5934 (direkt/dynamisch unklar); tests/test_server.py:8426 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8453 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 16127 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 16136 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 16148 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 16165 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:256 (direkt/dynamisch unklar); tests/test_server.py:8392 (direkt/dynamisch unklar); tests/test_server.py:8394 (direkt/dynamisch unklar); tests/test_server.py:8468 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 16173 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5942 (direkt/dynamisch unklar); tests/test_server.py:8398 (direkt/dynamisch unklar); tests/test_server.py:8409 (direkt/dynamisch unklar); tests/test_server.py:8425 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8473 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 16180 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 16181 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 16182 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 16182 | `coach/` | P7 | offen | tests/test_server.py:351 (direkt/dynamisch unklar); tests/test_server.py:407 (direkt/dynamisch unklar); tests/test_server.py:4879 (direkt/dynamisch unklar); tests/test_server.py:4882 (direkt/dynamisch unklar); tests/test_server.py:5232 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 16182 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 16182 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 16191 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 16199 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 16203 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 16208 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 16219 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 16244 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 16263 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 16275 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:3044 (direkt/dynamisch unklar); tests/test_server.py:3046 (direkt/dynamisch unklar); tests/test_server.py:5498 (direkt/dynamisch unklar); tests/test_server.py:5534 (direkt/dynamisch unklar); tests/test_server.py:5557 (direkt/dynamisch unklar); tests/test_server.py:5559 (direkt/dynamisch unklar); tests/test_server.py:5575 (direkt/dynamisch unklar); tests/test_server.py:5582 (direkt/dynamisch unklar); tests/test_server.py:5596 (direkt/dynamisch unklar); tests/test_server.py:5619 (direkt/dynamisch unklar); tests/test_server.py:5644 (direkt/dynamisch unklar); tests/test_server.py:5673 (direkt/dynamisch unklar); tests/test_server.py:5693 (direkt/dynamisch unklar); tests/test_server.py:5745 (direkt/dynamisch unklar); tests/test_server.py:5758 (direkt/dynamisch unklar); tests/test_server.py:5764 (direkt/dynamisch unklar); tests/test_server.py:5793 (direkt/dynamisch unklar); tests/test_server.py:5820 (direkt/dynamisch unklar); tests/test_server.py:5823 (direkt/dynamisch unklar); tests/test_server.py:5844 (direkt/dynamisch unklar); tests/test_server.py:688 (direkt/dynamisch unklar); tests/test_server.py:701 (direkt/dynamisch unklar); tests/test_server.py:777 (direkt/dynamisch unklar); tests/test_server.py:812 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 16298 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 16305 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 16312 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 16330 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 16340 | `coach/proposals.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:274 (direkt/dynamisch unklar); tests/test_server.py:299 (direkt/dynamisch unklar); tests/test_server.py:4548 (direkt/dynamisch unklar); tests/test_server.py:5479 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 16353 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 16362 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 16373 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 16405 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 16431 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 16451 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 16475 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 16487 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 16500 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 16514 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 16522 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 16533 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 16555 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 16565 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 16579 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 16591 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 16605 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 16613 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 16626 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 16635 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 16657 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 16675 | `planning/` | P4 | offen | tests/test_server.py:4909 (direkt/dynamisch unklar); tests/test_server.py:4931 (direkt/dynamisch unklar); tests/test_server.py:4950 (direkt/dynamisch unklar); tests/test_server.py:4972 (direkt/dynamisch unklar); tests/test_server.py:4987 (direkt/dynamisch unklar); tests/test_server.py:5003 (direkt/dynamisch unklar); tests/test_server.py:5021 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5061 (direkt/dynamisch unklar); tests/test_server.py:5084 (direkt/dynamisch unklar); tests/test_server.py:5128 (direkt/dynamisch unklar); tests/test_server.py:5153 (direkt/dynamisch unklar); tests/test_server.py:5174 (direkt/dynamisch unklar); tests/test_server.py:5189 (direkt/dynamisch unklar); tests/test_server.py:5208 (direkt/dynamisch unklar); tests/test_server.py:5225 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 16686 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 16696 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 16713 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 16724 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 16754 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 16772 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 16778 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 16791 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 16809 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 16825 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 16838 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 16852 | `planning/` | P4 | offen | tests/test_server.py:5599 (direkt/dynamisch unklar); tests/test_server.py:5646 (direkt/dynamisch unklar); tests/test_server.py:5674 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 16886 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:332 (direkt/dynamisch unklar); tests/test_server.py:363 (direkt/dynamisch unklar); tests/test_server.py:8748 (direkt/dynamisch unklar); tests/test_server.py:881 (direkt/dynamisch unklar); tests/test_server.py:959 (direkt/dynamisch unklar); tests/test_server.py:968 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 16899 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 16911 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 16926 | `planning/` | P4 | offen | tests/test_server.py:372 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 16938 | `planning/` | P4 | offen | tests/test_server.py:642 (direkt/dynamisch unklar); tests/test_server.py:652 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 16968 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 16976 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 16983 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 17005 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 17012 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 17018 | `coach/proposals.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 17036 | `planning/` | P4 | offen | tests/test_server.py:396 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 17064 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 17073 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 17100 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 17126 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 17131 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 17137 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 17151 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 17158 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 17166 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 17173 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 17182 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 17189 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 17202 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 17225 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 17239 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 17253 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 17281 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 17297 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 17316 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 17336 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 17358 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 17374 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 17391 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 17426 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 17438 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 17453 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 17473 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 17499 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 17517 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 17525 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 17546 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 17573 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 17597 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 17624 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 17645 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:286 (direkt/dynamisch unklar); tests/test_server.py:318 (direkt/dynamisch unklar); tests/test_server.py:342 (direkt/dynamisch unklar); tests/test_server.py:375 (direkt/dynamisch unklar); tests/test_server.py:397 (direkt/dynamisch unklar); tests/test_server.py:422 (direkt/dynamisch unklar); tests/test_server.py:429 (direkt/dynamisch unklar); tests/test_server.py:469 (direkt/dynamisch unklar); tests/test_server.py:498 (direkt/dynamisch unklar); tests/test_server.py:504 (direkt/dynamisch unklar); tests/test_server.py:508 (direkt/dynamisch unklar); tests/test_server.py:5107 (direkt/dynamisch unklar); tests/test_server.py:525 (direkt/dynamisch unklar); tests/test_server.py:529 (direkt/dynamisch unklar); tests/test_server.py:5504 (direkt/dynamisch unklar); tests/test_server.py:5540 (direkt/dynamisch unklar); tests/test_server.py:5625 (direkt/dynamisch unklar); tests/test_server.py:5699 (direkt/dynamisch unklar); tests/test_server.py:5723 (direkt/dynamisch unklar); tests/test_server.py:5728 (direkt/dynamisch unklar); tests/test_server.py:5777 (direkt/dynamisch unklar); tests/test_server.py:5799 (direkt/dynamisch unklar); tests/test_server.py:666 (direkt/dynamisch unklar); tests/test_server.py:708 (direkt/dynamisch unklar); tests/test_server.py:737 (direkt/dynamisch unklar); tests/test_server.py:756 (direkt/dynamisch unklar); tests/test_server.py:785 (direkt/dynamisch unklar); tests/test_server.py:818 (direkt/dynamisch unklar); tests/test_server.py:838 (direkt/dynamisch unklar); tests/test_server.py:865 (direkt/dynamisch unklar); tests/test_server.py:891 (direkt/dynamisch unklar); tests/test_server.py:910 (direkt/dynamisch unklar); tests/test_server.py:936 (direkt/dynamisch unklar); tests/test_server.py:961 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 17687 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 17691 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 17704 | `coach/authorization.py` | P7 | offen | tests/test_server.py:8762 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 17716 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 17735 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 17751 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 17762 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 17784 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 17799 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 17817 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 17847 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 17853 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 17867 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 17877 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 17890 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 17903 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 17920 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 17933 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5837 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 17960 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 17977 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 17982 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 17991 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 18005 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 18018 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 18028 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 18041 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 18062 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 18085 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 18096 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 18105 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 18117 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 18131 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 18139 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 18154 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 18174 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 18198 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 18212 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 18223 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 18248 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 18264 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 18279 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 18336 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 18364 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 18394 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 18410 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 18430 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 18444 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 18456 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 18466 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 18517 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 18579 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 18583 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 18588 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 18606 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 18625 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 18635 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 18661 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 18699 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 18725 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 18750 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 18781 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 18821 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 18851 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 18871 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 18929 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 18933 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 18949 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 18965 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 18997 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 19041 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 19057 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 19076 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 19102 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 19179 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 19184 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 19193 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 19198 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 19225 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 19243 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 19272 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 19291 | `coach/service.py` | P7 | offen | tests/test_server.py:4450 (direkt/dynamisch unklar); tests/test_server.py:4465 (direkt/dynamisch unklar); tests/test_server.py:4479 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 19301 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 19316 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:146 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 19348 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 19363 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4552 (direkt/dynamisch unklar); tests/test_server.py:5490 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 19376 | `coach/authorization.py` | P7 | offen | tests/test_server.py:5878 (direkt/dynamisch unklar); tests/test_server.py:5881 (direkt/dynamisch unklar); tests/test_server.py:8402 (direkt/dynamisch unklar); tests/test_server.py:8405 (direkt/dynamisch unklar); tests/test_server.py:8406 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 19395 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 19408 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 19432 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 19448 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 19459 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 19474 | `coach/authorization.py` | P7 | offen | tests/test_audit_remediation.py:246 (direkt/dynamisch unklar); tests/test_audit_remediation.py:261 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:284 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:146 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5907 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5931 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5963 (direkt/dynamisch unklar); tests/test_server.py:6026 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 19498 | `sync/` | P6 | offen | tests/test_server.py:4628 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 19539 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4627 (direkt/dynamisch unklar); tests/test_server.py:5905 (direkt/dynamisch unklar); tests/test_server.py:5924 (direkt/dynamisch unklar); tests/test_server.py:5951 (direkt/dynamisch unklar); tests/test_server.py:5980 (direkt/dynamisch unklar); tests/test_server.py:6004 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 19564 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 19590 | `coach/morning.py` | P8 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 19600 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 19604 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 19612 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 19618 | `runtime/` | P1 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 19628 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 19645 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 19676 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 19698 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 19713 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:262 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:147 (direkt/dynamisch unklar); tests/test_server.py:5908 (direkt/dynamisch unklar); tests/test_server.py:5932 (direkt/dynamisch unklar); tests/test_server.py:5986 (direkt/dynamisch unklar); tests/test_server.py:6029 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 19734 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 19749 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `local_now` | 19761 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1154 (direkt/dynamisch unklar); tests/test_server.py:1538 (direkt/dynamisch unklar); tests/test_server.py:1554 (direkt/dynamisch unklar); tests/test_server.py:1555 (direkt/dynamisch unklar); tests/test_server.py:1576 (direkt/dynamisch unklar); tests/test_server.py:1594 (direkt/dynamisch unklar); tests/test_server.py:1613 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1626 (direkt/dynamisch unklar); tests/test_server.py:1663 (direkt/dynamisch unklar); tests/test_server.py:1671 (direkt/dynamisch unklar); tests/test_server.py:1711 (direkt/dynamisch unklar); tests/test_server.py:2527 (direkt/dynamisch unklar); tests/test_server.py:2639 (direkt/dynamisch unklar); tests/test_server.py:2704 (direkt/dynamisch unklar); tests/test_server.py:2714 (direkt/dynamisch unklar); tests/test_server.py:2892 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2952 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2982 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2991 (direkt/dynamisch unklar); tests/test_server.py:3479 (direkt/dynamisch unklar); tests/test_server.py:3498 (direkt/dynamisch unklar); tests/test_server.py:3530 (direkt/dynamisch unklar); tests/test_server.py:3555 (direkt/dynamisch unklar); tests/test_server.py:3645 (direkt/dynamisch unklar); tests/test_server.py:3646 (direkt/dynamisch unklar); tests/test_server.py:3690 (direkt/dynamisch unklar); tests/test_server.py:493 (direkt/dynamisch unklar); tests/test_server.py:5247 (direkt/dynamisch unklar); tests/test_server.py:5296 (direkt/dynamisch unklar); tests/test_server.py:5313 (direkt/dynamisch unklar); tests/test_server.py:5335 (direkt/dynamisch unklar); tests/test_server.py:5362 (direkt/dynamisch unklar); tests/test_server.py:5394 (direkt/dynamisch unklar); tests/test_server.py:6069 (direkt/dynamisch unklar); tests/test_server.py:7403 (direkt/dynamisch unklar); tests/test_server.py:7721 (direkt/dynamisch unklar); tests/test_server.py:8503 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 19770 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:152 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1897 (direkt/dynamisch unklar); tests/test_server.py:1898 (direkt/dynamisch unklar); tests/test_server.py:1899 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 19778 | `sync/scheduler.py` | P8 | offen | tests/test_server.py:1896 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 19786 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 19791 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 19802 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 19814 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4159 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 19817 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 19824 | `sync/scheduler.py` | P8 | offen | tests/test_server.py:4157 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 19841 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 19847 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 19855 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 19867 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:285 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 19899 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 19920 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 19934 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 19947 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 19966 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 20000 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1721 (direkt/dynamisch unklar); tests/test_server.py:1735 (direkt/dynamisch unklar); tests/test_server.py:1780 (direkt/dynamisch unklar); tests/test_server.py:1862 (direkt/dynamisch unklar); tests/test_server.py:8543 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 20074 | `http_api/` | P10 | offen | tests/test_server.py:1168 (direkt/dynamisch unklar); tests/test_server.py:2984 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 20110 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 20115 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 20119 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:96 (direkt/dynamisch unklar); tests/test_server.py:1218 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 20126 | `http_api/` | P10 | offen | tests/test_server.py:1190 (direkt/dynamisch unklar); tests/test_server.py:1198 (direkt/dynamisch unklar); tests/test_server.py:1621 (direkt/dynamisch unklar); tests/test_server.py:1666 (direkt/dynamisch unklar); tests/test_server.py:2333 (direkt/dynamisch unklar); tests/test_server.py:3695 (direkt/dynamisch unklar); tests/test_server.py:7332 (direkt/dynamisch unklar); tests/test_server.py:8543 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 20238 | `observability.py` | P1 | offen | tests/test_server.py:7866 (direkt/dynamisch unklar); tests/test_server.py:7918 (direkt/dynamisch unklar); tests/test_server.py:8032 (direkt/dynamisch unklar); tests/test_server.py:8063 (direkt/dynamisch unklar); tests/test_server.py:8314 (direkt/dynamisch unklar); tests/test_server.py:8350 (direkt/dynamisch unklar); tests/test_server.py:8599 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS_SECRET_KEYS` | 20255 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_VALUE_KEYS` | 20256 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_KEYS` | 20257 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_submitted_settings` | 20260 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_settings_file` | 20275 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_rewrite_settings_lines` | 20282 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `save_settings` | 20302 | `settings.py` | P1 | offen | tests/test_server.py:6659 (direkt/dynamisch unklar); tests/test_server.py:6675 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 20317 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 20333 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 20354 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 20368 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 20384 | `observability.py` | P1 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 20393 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7781 (direkt/dynamisch unklar); tests/test_server.py:7783 (direkt/dynamisch unklar); tests/test_server.py:7784 (direkt/dynamisch unklar); tests/test_server.py:7831 (direkt/dynamisch unklar); tests/test_server.py:7894 (direkt/dynamisch unklar); tests/test_server.py:7909 (direkt/dynamisch unklar); tests/test_server.py:8716 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 20456 | `backup/` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1401 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 20506 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 20507 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 20531 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 20535 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 20546 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 20550 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 20560 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 20568 | `backup/` | P9 | offen | tests/test_audit_remediation.py:170 (direkt/dynamisch unklar); tests/test_server.py:1416 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 20707 | `db/manager.py` | P1 | offen | tests/test_server.py:6598 (direkt/dynamisch unklar); tests/test_server.py:6611 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 20710 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 20723 | `backup/` | P9 | offen | tests/test_audit_remediation.py:274 (direkt/dynamisch unklar); tests/test_server.py:6587 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 20732 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 20753 | `coach/morning.py` | P8 | offen | tests/test_server.py:1444 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 20764 | `backup/` | P9 | offen | tests/test_audit_remediation.py:276 (direkt/dynamisch unklar); tests/test_server.py:6588 (direkt/dynamisch unklar); tests/test_server.py:6604 (direkt/dynamisch unklar); tests/test_server.py:6617 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 20769 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 20778 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 20795 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 20807 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 20825 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 20832 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 20853 | `coach/morning.py` | P8 | offen | tests/test_server.py:1484 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1500 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4641 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5484 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8662 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 20866 | `coach/morning.py` | P8 | offen | tests/test_server.py:1493 (direkt/dynamisch unklar); tests/test_server.py:1497 (direkt/dynamisch unklar); tests/test_server.py:1503 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 20881 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 20888 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 20895 | `privacy.py` | P9 | offen | tests/test_server.py:1496 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 20910 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:101 (direkt/dynamisch unklar); tests/test_provider_review.py:115 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:145 (direkt/dynamisch unklar); tests/test_provider_review.py:163 (direkt/dynamisch unklar); tests/test_server.py:1485 (direkt/dynamisch unklar); tests/test_server.py:1501 (direkt/dynamisch unklar); tests/test_server.py:8663 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 20939 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 20940 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 20941 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 20942 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 20943 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 20944 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1316 (direkt/dynamisch unklar); tests/test_server.py:1324 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 20945 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1321 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 20946 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 20947 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 20948 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 20949 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7996 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 20952 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 20956 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:184 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7998 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 20981 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 20990 | `http_api/` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1280 (direkt/dynamisch unklar); tests/test_server.py:1309 (direkt/dynamisch unklar); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:1361 (direkt/dynamisch unklar); tests/test_server.py:1368 (direkt/dynamisch unklar); tests/test_server.py:5893 (direkt/dynamisch unklar); tests/test_server.py:5897 (direkt/dynamisch unklar); tests/test_server.py:5912 (direkt/dynamisch unklar); tests/test_server.py:5916 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 20994 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 21004 | `http_api/` | P10 | offen | tests/test_server.py:1322 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 21019 | `performance/` | P3 | offen | tests/test_server.py:7961 (direkt/dynamisch unklar); tests/test_server.py:7971 (direkt/dynamisch unklar); tests/test_server.py:7979 (direkt/dynamisch unklar); tests/test_server.py:7986 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 21061 | `http_api/` | P10 | offen | tests/test_server.py:1286 (direkt/dynamisch unklar); tests/test_server.py:1289 (direkt/dynamisch unklar); tests/test_server.py:1310 (direkt/dynamisch unklar); tests/test_server.py:1343 (direkt/dynamisch unklar); tests/test_server.py:1380 (direkt/dynamisch unklar); tests/test_server.py:3391 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 21087 | `observability.py` | P1 | offen | tests/test_provider_review.py:187 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_provider_review.py:326 (direkt/dynamisch unklar); tests/test_server.py:3388 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 21106 | `observability.py` | P1 | offen | tests/test_server.py:1379 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 21114 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 21126 | `http_api/` | P10 | offen | tests/test_server.py:1361 (direkt/dynamisch unklar); tests/test_server.py:1368 (direkt/dynamisch unklar); tests/test_server.py:3393 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 21132 | `http_api/` | P10 | offen | tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:1267 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 21145 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:192 (direkt/dynamisch unklar); tests/test_server.py:1464 (direkt/dynamisch unklar); tests/test_server.py:1761 (direkt/dynamisch unklar); tests/test_server.py:7509 (direkt/dynamisch unklar); tests/test_server.py:7519 (direkt/dynamisch unklar); tests/test_server.py:7525 (direkt/dynamisch unklar); tests/test_server.py:7535 (direkt/dynamisch unklar); tests/test_server.py:7547 (direkt/dynamisch unklar); tests/test_server.py:7552 (direkt/dynamisch unklar); tests/test_server.py:7556 (direkt/dynamisch unklar); tests/test_server.py:7559 (direkt/dynamisch unklar); tests/test_server.py:7565 (direkt/dynamisch unklar); tests/test_server.py:7575 (direkt/dynamisch unklar); tests/test_server.py:7582 (direkt/dynamisch unklar); tests/test_server.py:7589 (direkt/dynamisch unklar); tests/test_server.py:7596 (direkt/dynamisch unklar); tests/test_server.py:8415 (direkt/dynamisch unklar); tests/test_server.py:8438 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 21825 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:192 (direkt/dynamisch unklar) |
| Funktion | `daily_sync_loop` | 21830 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 21843 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 21847 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 21853 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 21859 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 21865 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 21873 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:153 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 21880 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 21894 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 21899 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 21911 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 21923 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 21928 | `sync/` | P6 | offen | tests/test_server.py:975 (direkt/dynamisch unklar); tests/test_server.py:984 (direkt/dynamisch unklar) |
| Funktion | `main` | 21936 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar) |

## Zielverteilung

| Zielmodul | Einträge |
| --- | ---: |
| `activities/` | 51 |
| `athlete/` | 14 |
| `backend/backup/export` | 5 |
| `backend/coach/attachments` | 7 |
| `backend/coach/authorization` | 4 |
| `backend/coach/context` | 10 |
| `backend/coach/dialogue` | 3 |
| `backend/coach/outcomes` | 4 |
| `backend/coach/service` | 4 |
| `backend/coach/tools` | 1 |
| `backend/config` | 4 |
| `backend/db` | 1 |
| `backend/db/manager` | 1 |
| `backend/db/repositories` | 9 |
| `backend/db/schema` | 7 |
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
| `coach/authorization.py` | 61 |
| `coach/context.py` | 20 |
| `coach/conversation.py` | 8 |
| `coach/dialogue.py` | 18 |
| `coach/jobs.py` | 6 |
| `coach/morning.py` | 32 |
| `coach/proposals.py` | 52 |
| `coach/service.py` | 6 |
| `coach/streams.py` | 4 |
| `coach/tool_execution.py` | 8 |
| `config.py` | 8 |
| `db/` | 22 |
| `db/manager.py` | 6 |
| `db/schema.py` | 1 |
| `history/` | 34 |
| `http_api/` | 43 |
| `http_api/auth.py` | 14 |
| `http_api/pagination.py` | 9 |
| `observability.py` | 57 |
| `performance/` | 56 |
| `planning/` | 272 |
| `planning/competitions.py` | 64 |
| `privacy.py` | 4 |
| `providers/` | 104 |
| `providers/calendar.py` | 46 |
| `providers/http.py` | 16 |
| `providers/intervals_client.py` | 1 |
| `providers/workout_text.py` | 13 |
| `runtime/` | 4 |
| `runtime/events.py` | 5 |
| `runtime/maintenance.py` | 4 |
| `server.py / Composition Root` | 61 |
| `settings.py` | 38 |
| `sync/` | 151 |
| `sync/competitions.py` | 5 |
| `sync/garmin.py` | 109 |
| `sync/scheduler.py` | 15 |
| `unklar: config.py, errors.py, observability.py, runtime/, db/, sync/, history/, settings.py` | 3 |
| `weather/` | 55 |

## Grenzen und offene Unsicherheiten

- AST-Aufrufauflösung erfasst nur direkte lokale Aufrufe; `getattr`, `globals()`, `sys.modules`, dekoratorbasierte Registrierung und Callback-Injektion benötigen eine manuelle Nachprüfung.
- Ein Name kann in mehreren Kategorien mit derselben Schreibweise vorkommen; Referenzzählungen sind deshalb namensbasiert und zeigen Ortsangaben, nicht vermeintliche Laufzeitidentität.
- Die Tabelle enthält bewusst auch Importbindungen, damit Rückimporte, spätere Re-Exports und der endgültige Composition-Root-Inhalt überprüfbar bleiben.
- Offene Zielzuordnungen müssen vor dem jeweiligen Umzug fachlich entschieden werden; sie gelten nicht als erledigt.
