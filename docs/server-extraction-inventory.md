# Statisches Inventar für die server.py-Auslagerung

> Automatisch erzeugt durch `python scripts/server_extraction_inventory.py`. Die Analyse liest ausschließlich Quelltext mit der Python-Standardbibliothek; `server` wird nie importiert und Laufzeitdaten werden nicht geöffnet.

## Ausgangsstand

- Geprüfter P0-Basiscommit: `362d6caa4c27951af86b82b11b3a43d48dadceee`
- Inventarisierter `server.py`-Quelltext (SHA-256): `d2cfcddf1300786a8fa1b2278a417dac33ae4996ebc3b843c82d140989ef2788`; dieser Fingerprint ist unabhängig von HEAD und Arbeitsbaum stabil.
- `server.py`: 21.998 physische Zeilen
- Inventareinträge: 1.723
- Definitionen (Funktionen/Klassen): 1.235
- Globale Bindungen einschließlich Imports: 309 Zuweisungen. 179 Imports
- Planbereich: bis Zeile 21.702; Einträge dahinter: 15 (zielbestimmt über Symbol-/Verantwortungsanalyse)
- Status dieses Stands: P0/Intervals-Reabsorption integriert; P1 hat noch nicht begonnen. `offen` bedeutet, dass die fachliche Eigentümerschaft noch migriert werden muss.

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
| P1 | 93 | 72 | 122 |
| P2 | 156 | 24 | 0 |
| P3 | 182 | 28 | 0 |
| P4 | 306 | 30 | 0 |
| P5 | 24 | 10 | 0 |
| P6 | 218 | 47 | 0 |
| P7 | 163 | 36 | 0 |
| P8 | 47 | 14 | 0 |
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
| `publish_state_event` | 310 | – | `Any`, `STATE_EVENTS`, `STATE_EVENT_CONDITION`, `STATE_EVENT_NEXT_ID` | `STATE_EVENT_NEXT_ID` | – |
| `state_events_since` | 333 | `AppError` | `Any`, `AppError`, `STATE_EVENTS`, `STATE_EVENT_CONDITION`, `STATE_EVENT_NEXT_ID` | – | – |
| `MaintenanceGate` | 350 | `AppError` | `Any`, `AppError`, `contextmanager`, `threading` | – | – |
| `maintenance_operation` | 413 | – | `Any`, `MAINTENANCE_GATE`, `wraps` | – | – |
| `claimed_maintenance_operation` | 421 | – | `Any`, `AppError`, `MAINTENANCE_GATE`, `wraps` | – | – |
| `ProviderResyncGate` | 434 | `AppError` | `AppError`, `contextmanager`, `threading` | – | – |
| `provider_operation` | 485 | – | `GARMIN_RESYNC_GATE`, `INTERVALS_RESYNC_GATE` | – | – |
| `intervals_operation` | 490 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `garmin_operation` | 498 | `provider_operation` | `Any`, `provider_operation`, `wraps` | – | – |
| `load_local_env` | 506 | – | `DATA_DIR`, `ROOT`, `load_config_env` | – | – |
| `IntervalsClient` | 514 | `AppError`, `_raise_chat_cancelled`, `compact_snapshot`, `deduplicate_api_records`, `intervals_workout_sport`, `latest_snapshot`, `local_now`, `selected`, `sync_date_windows`, `validate_intervals_workout_result`, `validate_workout_description`, `workout_event_payload` | `ALL_SYNC_DAYS`, `APP_NAME`, `Any`, `AppError`, `CONFIG`, `Callable`, `Config`, `IntervalsReadTransport`, `IntervalsWriteTransport`, `PLANNED_CALENDAR_FUTURE_DAYS`, `PLANNED_CALENDAR_HISTORY_DAYS`, `_raise_chat_cancelled`, … (+18) | – | – |
| `available_ai_providers` | 836 | – | `CONFIG` | – | – |
| `selected_ai_provider` | 845 | `available_ai_providers`, `get_kv` | `CONFIG`, `available_ai_providers`, `get_kv` | – | – |
| `save_ai_provider` | 859 | `AppError`, `available_ai_providers`, `available_model_options`, `selected_model`, `set_kv` | `Any`, `AppError`, `available_ai_providers`, `available_model_options`, `selected_model`, `set_kv` | – | – |
| `available_model_options` | 871 | `selected_ai_provider` | `CONFIG`, `GEMINI_MODEL_OPTIONS`, `MODEL_OPTIONS`, `selected_ai_provider` | – | – |
| `selected_model` | 880 | `available_model_options`, `get_kv`, `selected_ai_provider` | `CONFIG`, `available_model_options`, `get_kv`, `selected_ai_provider` | – | – |
| `save_model` | 888 | `AppError`, `available_model_options`, `selected_ai_provider`, `set_kv` | `Any`, `AppError`, `available_model_options`, `selected_ai_provider`, `set_kv` | – | – |
| `available_thinking_level_options` | 896 | – | `THINKING_LEVEL_OPTIONS` | – | – |
| `selected_thinking_level` | 900 | `get_kv` | `THINKING_LEVEL_OPTIONS`, `get_kv` | – | – |
| `save_thinking_level` | 906 | `AppError`, `set_kv` | `Any`, `AppError`, `THINKING_LEVEL_OPTIONS`, `set_kv` | – | – |
| `calendar_display_settings` | 914 | `get_kv` | `CALENDAR_DISPLAY_DEFAULTS`, `CALENDAR_DISPLAY_MAX_WEEKS`, `get_kv` | – | – |
| `save_calendar_display_settings` | 925 | `AppError`, `calendar_display_settings`, `set_kv` | `Any`, `AppError`, `CALENDAR_DISPLAY_MAX_WEEKS`, `calendar_display_settings`, `set_kv` | – | – |
| `_secret_variants` | 953 | – | `Any`, `quote`, `unquote` | – | – |
| `_safe_url_netloc` | 966 | – | `Any` | – | – |
| `_safe_provider_path` | 979 | – | `REDACTED_PATH`, `re`, `unquote` | – | – |
| `_unguessable_url_path_segment` | 1002 | – | `re`, `unquote` | – | – |
| `_redact_url` | 1012 | `_safe_url_netloc`, `_unguessable_url_path_segment` | `REDACTED_PATH`, `REDACTED_URL_QUERY_KEYS`, `_safe_url_netloc`, `_unguessable_url_path_segment`, `parse_qsl`, `re`, `urlencode`, `urlparse`, `urlunparse` | – | – |
| `_safe_calendar_url` | 1036 | `_safe_url_netloc` | `CONFIG`, `_safe_url_netloc`, `urlparse`, `urlunparse` | – | – |
| `redact_text` | 1046 | `_safe_calendar_url`, `_secret_variants` | `CONFIG`, `URL_VALUE_RE`, `_redact_url`, `_safe_calendar_url`, `_secret_variants`, `re` | – | – |
| `sanitize_log_value` | 1072 | `redact_text`, `sanitize_log_value` | `Any`, `redact_text`, `sanitize_log_value` | – | – |
| `JsonLogFormatter` | 1084 | `sanitize_log_value` | `Any`, `datetime`, `json`, `logging`, `sanitize_log_value`, `timezone` | – | – |
| `initialise_logging` | 1100 | `JsonLogFormatter` | `DATA_DIR`, `JsonLogFormatter`, `LOGGER`, `LOG_PATH`, `RotatingFileHandler`, `logging`, `sys` | – | – |
| `external_result_context` | 1122 | – | `Any` | – | – |
| `provider_error` | 1133 | `AppError` | `AppError`, `PROVIDER_INTERVALS_NAME` | – | – |
| `external_call` | 1154 | `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `external_result_context`, `initialise_logging`, `operation_error_code`, `provider_error` | `Any`, `AppError`, `LOGGER`, `OPERATION_CONTEXT`, `_safe_diagnostic_context`, `_safe_diagnostic_error`, `capture_diagnostic_event`, `diagnostic_capture_response`, `external_result_context`, `initialise_logging`, `operation_error_code`, `provider_error`, … (+1) | – | – |
| `AppError` | 1346 | – | – | – | – |
| `public_app_error_status` | 1354 | – | `AppError` | – | – |
| `ClientDisconnected` | 1361 | – | – | – | – |
| `serialise_conversation` | 1365 | `AppError` | `AppError`, `CHAT_LOCK_TIMEOUT_SECONDS`, `CHAT_QUEUE`, `OPENAI_CONVERSATION_LOCK`, `wraps` | – | – |
| `utc_now` | 1382 | – | `datetime`, `timezone` | – | – |
| `security_configuration_error` | 1397 | – | `CONFIG`, `SQLCIPHER_AVAILABLE` | – | – |
| `operation_trigger` | 1488 | – | `Any`, `OPERATION_CLEANUP_REASONS` | – | – |
| `operation_error_code` | 1494 | – | `AppError`, `re` | – | – |
| `operation_result_count` | 1503 | – | `Any` | – | – |
| `log_operation_event` | 1513 | – | `Any`, `LOGGER`, `logging`, `time` | – | – |
| `observed_operation` | 1540 | `log_operation_event`, `operation_error_code`, `operation_trigger` | `Any`, `OPERATION_CONTEXT`, `contextmanager`, `log_operation_event`, `operation_error_code`, `operation_trigger`, `time`, `uuid` | – | – |
| `observed_sync` | 1561 | `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `observed_operation`, `operation_result_count` | `Any`, `AppError`, `_provider_refresh_error_code`, `_provider_refresh_finish`, `_provider_refresh_start`, `log_operation_event`, `maintenance_operation`, `observed_operation`, `operation_result_count`, `wraps` | – | – |
| `database_manager` | 1604 | – | `CONFIG`, `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE`, `DATA_DIR`, `DB_PATH`, `DatabaseManager`, `SQLCIPHER_AVAILABLE`, `configure_cipher`, `database_row_factory`, `sqlite3`, `sqlite_backend` | `DATABASE_MANAGER`, `DATABASE_MANAGER_SIGNATURE` | – |
| `database` | 1631 | `database_manager` | `contextmanager`, `database_manager` | – | – |
| `initialise_database` | 1637 | `database`, `get_kv`, `resume_interrupted_sync_jobs`, `set_kv`, `utc_now` | `ALL_SYNC_DAYS`, `CONFIG`, `DB_LOCK`, `DEFAULT_PROFILE`, `PROVIDER_RESYNC_KEYS`, `database`, `database_schema_is_current`, `database_table_names`, `datetime`, `get_kv`, `initialize_schema`, `json`, … (+5) | – | – |
| `_provider_refresh_cleanup` | 1679 | – | `Any`, `PROVIDER_REFRESH_MAX_ROWS`, `PROVIDER_REFRESH_RETENTION_DAYS`, `cleanup_refresh_history`, `datetime`, `timedelta`, `timezone` | – | – |
| `_provider_refresh_start` | 1684 | `_provider_refresh_cleanup`, `database`, `publish_state_event`, `utc_now` | `DB_LOCK`, `_provider_refresh_cleanup`, `create_refresh_record`, `database`, `publish_state_event`, `utc_now`, `uuid` | – | – |
| `_provider_refresh_finish` | 1696 | `_provider_refresh_cleanup`, `database`, `publish_state_event`, `utc_now` | `DB_LOCK`, `PROVIDER_REFRESH_RETRY_BASE_SECONDS`, `PROVIDER_REFRESH_RETRY_MAX_SECONDS`, `_provider_refresh_cleanup`, `database`, `datetime`, `finish_refresh_record`, `publish_state_event`, `timezone`, `utc_now` | – | – |
| `_provider_refresh_error_code` | 1730 | – | – | – | – |
| `_sync_job_error_class` | 1745 | `_provider_refresh_error_code` | `_provider_refresh_error_code` | – | – |
| `_normalized_performance_job` | 1759 | `AppError` | `Any`, `AppError` | – | – |
| `_normalized_plan_push_entries` | 1768 | `AppError` | `Any`, `AppError`, `PAYLOAD_HASH_PATTERN`, `UUID_PATTERN`, `re` | – | – |
| `_normalized_plan_push_job` | 1782 | `AppError`, `_normalized_plan_push_entries` | `Any`, `AppError`, `_normalized_plan_push_entries` | – | – |
| `_normalized_sync_payload` | 1795 | `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | `Any`, `AppError`, `_normalized_generic_sync_job`, `_normalized_performance_job`, `_normalized_plan_push_job` | – | – |
| `_sync_job_payload` | 1805 | `AppError`, `_normalized_sync_payload` | `Any`, `AppError`, `_normalized_sync_payload`, `validate_job_request` | – | – |
| `_normalized_sync_days` | 1814 | `AppError` | `ALL_SYNC_DAYS`, `Any`, `AppError` | – | – |
| `_normalized_sync_end_date` | 1824 | `AppError` | `Any`, `AppError`, `date` | – | – |
| `_normalized_generic_sync_job` | 1831 | `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | `Any`, `AppError`, `_normalized_sync_days`, `_normalized_sync_end_date` | – | – |
| `sync_job_state` | 1856 | `AppError`, `database` | `Any`, `AppError`, `DB_LOCK`, `database`, `job_dto`, `read_job` | – | – |
| `sync_jobs_state` | 1865 | `database` | `Any`, `DB_LOCK`, `SYNC_JOB_LIST_LIMIT`, `database`, `list_jobs` | – | – |
| `_sync_job_active` | 1871 | `database` | `DB_LOCK`, `database`, `has_active_job` | – | – |
| `_enqueue_automatic_performance_refresh` | 1876 | `enqueue_sync_job` | `Any`, `CONFIG`, `LOGGER`, `PERFORMANCE_LOCK`, `enqueue_sync_job` | – | – |
| `_performance_refresh_failed` | 1899 | `AppError` | `AppError` | – | – |
| `_pending_performance_job_id` | 1907 | `database` | `DB_LOCK`, `database` | – | – |
| `_performance_refresh_poll_state` | 1916 | `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | `Any`, `_pending_performance_job_id`, `_performance_refresh_failed`, `get_kv`, `sync_job_state` | – | – |
| `_wait_for_performance_refresh` | 1934 | `AppError`, `_performance_refresh_poll_state`, `_raise_chat_cancelled` | `Any`, `AppError`, `INTERVALS_SYNC_WAIT_SECONDS`, `SYNC_JOB_POLL_SECONDS`, `_performance_refresh_poll_state`, `_raise_chat_cancelled`, `threading`, `time` | – | – |
| `_scheduled_sync_job_at` | 1961 | `AppError` | `AppError`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_sync_job_operations` | 1970 | `AppError` | `Any`, `AppError` | – | – |
| `_existing_performance_job_id` | 1977 | – | `Any` | – | – |
| `_insert_sync_job` | 1987 | `AppError` | `Any`, `AppError`, `hashlib`, `json` | – | – |
| `_publish_created_sync_job` | 2012 | `publish_state_event` | `Any`, `publish_state_event` | – | – |
| `enqueue_sync_job` | 2026 | `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `sync_job_state`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_WAKE`, `_existing_performance_job_id`, `_insert_sync_job`, `_publish_created_sync_job`, `_scheduled_sync_job_at`, `_sync_job_operations`, `_sync_job_payload`, `database`, `maintenance_operation`, `sync_job_state`, … (+2) | – | – |
| `resume_interrupted_sync_jobs` | 2053 | `database`, `utc_now` | `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `utc_now` | – | – |
| `_claim_sync_job` | 2073 | `database`, `utc_now` | `Any`, `DB_LOCK`, `MAINTENANCE_GATE`, `database`, `maintenance_operation`, `utc_now` | – | – |
| `_sync_job_update` | 2094 | `database`, `publish_state_event`, `utc_now` | `DB_LOCK`, `ITEM_STATUSES`, `aggregate_job_status`, `bounded_progress`, `database`, `publish_state_event`, `utc_now` | – | – |
| `_sync_job_item_results` | 2132 | – | `Any` | – | – |
| `_sync_job_result_target` | 2138 | – | `Any` | – | – |
| `_persist_sync_job_result_items` | 2149 | `_sync_job_result_target`, `redact_text` | `Any`, `_sync_job_result_target`, `redact_text` | – | – |
| `_sync_job_completion_snapshot` | 2169 | – | `Any`, `aggregate_job_status`, `bounded_progress` | – | – |
| `_publish_sync_job_result_event` | 2184 | `publish_state_event` | `publish_state_event` | – | – |
| `_sync_job_update_from_result` | 2201 | `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | `Any`, `DB_LOCK`, `_persist_sync_job_result_items`, `_publish_sync_job_result_event`, `_sync_job_completion_snapshot`, `_sync_job_item_results`, `_sync_job_update`, `database`, `utc_now` | – | – |
| `_historical_sync_window` | 2214 | `local_now`, `sync_period` | `Any`, `SYNC_CHUNK_DAYS`, `date`, `local_now`, `sync_period`, `timedelta` | – | – |
| `_historical_next_end` | 2223 | – | `Any`, `SYNC_EARLIEST_DATE`, `date`, `timedelta` | – | – |
| `_execute_intervals_sync_job` | 2230 | `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | `Any`, `_historical_next_end`, `_historical_sync_window`, `sync_competitions`, `sync_intervals` | – | – |
| `_execute_garmin_sync_job` | 2247 | `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | `ALL_SYNC_DAYS`, `Any`, `_historical_next_end`, `_historical_sync_window`, `garmin_fixture_path`, `refresh_morning_body_battery`, `sync_garmin` | – | – |
| `_execute_intervals_specific_job` | 2259 | `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | `Any`, `_sync_selected_workout_library`, `refresh_current_performance`, `sync_competitions` | – | – |
| `_execute_sync_job` | 2271 | `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `sync_external_calendar`, `sync_weather` | `Any`, `AppError`, `_execute_garmin_sync_job`, `_execute_intervals_specific_job`, `_execute_intervals_sync_job`, `_sync_job_payload`, `decode_job_payload`, `sync_external_calendar`, `sync_weather` | – | – |
| `_sync_job_fallback_status` | 2294 | `AppError` | `Any`, `AppError` | – | – |
| `_queue_next_historical_backfill` | 2303 | `enqueue_sync_job` | `Any`, `SYNC_CHUNK_DAYS`, `enqueue_sync_job` | – | – |
| `_requeue_claimed_sync_job` | 2323 | `database`, `utc_now` | `Any`, `DB_LOCK`, `SYNC_JOB_MAX_ATTEMPTS`, `SYNC_JOB_RETRY_BASE_SECONDS`, `SYNC_JOB_RETRY_MAX_SECONDS`, `SYNC_JOB_WAKE`, `database`, `datetime`, `is_retryable_error`, `retry_delay`, `timedelta`, `timezone`, … (+1) | – | – |
| `_record_claimed_sync_job_failure` | 2343 | `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update`, `redact_text` | `Any`, `LOGGER`, `_requeue_claimed_sync_job`, `_sync_job_error_class`, `_sync_job_update`, `redact_text` | – | – |
| `_run_claimed_sync_job` | 2361 | `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result` | `Any`, `_execute_sync_job`, `_queue_next_historical_backfill`, `_record_claimed_sync_job_failure`, `_sync_job_fallback_status`, `_sync_job_update_from_result`, `claimed_maintenance_operation` | – | – |
| `_sync_job_worker_loop` | 2371 | `_claim_sync_job`, `_run_claimed_sync_job` | `AppError`, `MAINTENANCE_GATE`, `SYNC_JOB_POLL_SECONDS`, `SYNC_JOB_STOP`, `SYNC_JOB_WAKE`, `_claim_sync_job`, `_run_claimed_sync_job` | – | – |
| `start_sync_job_worker` | 2386 | `resume_interrupted_sync_jobs` | `SYNC_JOB_STOP`, `SYNC_JOB_WORKER`, `SYNC_JOB_WORKER_LOCK`, `_sync_job_worker_loop`, `resume_interrupted_sync_jobs`, `threading` | `SYNC_JOB_WORKER` | – |
| `resolve_sync_job` | 2398 | `AppError`, `database`, `sync_job_state`, `utc_now` | `Any`, `AppError`, `DB_LOCK`, `SYNC_JOB_WAKE`, `database`, `sync_job_state`, `utc_now` | – | – |
| `_scheduled_provider_retry_at` | 2421 | – | `Any`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_freshness_inputs` | 2440 | `_garmin_core_error_entries`, `get_kv`, `get_profile` | `Any`, `CONFIG`, `Path`, `WEATHER_CACHE_KEY`, `WEATHER_FAILURE_KEY`, `_garmin_core_error_entries`, `get_kv`, `get_profile`, `json` | – | – |
| `_provider_freshness_last_good_state` | 2474 | – | `Any`, `PROVIDER_REFRESH_STALE_SECONDS`, `UTC_OFFSET_SUFFIX`, `datetime`, `timezone` | – | – |
| `_provider_fallback_error_code` | 2484 | – | – | – | – |
| `_provider_freshness_error_code` | 2488 | `_provider_fallback_error_code` | `Any`, `_provider_fallback_error_code` | – | – |
| `_provider_freshness_status` | 2496 | `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | `Any`, `_provider_fallback_error_code`, `_provider_freshness_error_code`, `_provider_freshness_last_good_state` | – | – |
| `provider_freshness_state` | 2517 | `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | `Any`, `DB_LOCK`, `PROVIDER_REFRESH_LABELS`, `_provider_freshness_inputs`, `_provider_freshness_status`, `_provider_refresh_cleanup`, `_scheduled_provider_retry_at`, `database` | – | – |
| `_audit_projection_fields` | 2558 | – | `CHANGE_HISTORY_COMPETITION_FIELDS`, `CHANGE_HISTORY_LIBRARY_FIELDS`, `CHANGE_HISTORY_PLANNED_UNIT_FIELDS`, `CHANGE_HISTORY_PLAN_FIELDS`, `CHANGE_HISTORY_PROFILE_FIELDS` | – | – |
| `_audit_payload_projection` | 2572 | – | `Any`, `json` | – | – |
| `_audit_projection` | 2583 | `_audit_payload_projection`, `_audit_projection_fields` | `Any`, `_audit_payload_projection`, `_audit_projection_fields`, `json` | – | – |
| `_audit_hash` | 2607 | – | `Any`, `hashlib`, `json` | – | – |
| `_audit_diff` | 2612 | – | `Any` | – | – |
| `_cleanup_change_history` | 2624 | – | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `CHANGE_HISTORY_RETENTION_DAYS`, `datetime`, `timedelta`, `timezone` | – | – |
| `_reserve_change_history_capacity` | 2634 | `AppError` | `Any`, `AppError`, `CHANGE_HISTORY_MAX_ROWS` | – | – |
| `_record_change` | 2651 | `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `utc_now` | `Any`, `CHANGE_HISTORY_ACTIONS`, `CHANGE_HISTORY_ENTITY_TYPES`, `_audit_diff`, `_audit_hash`, `_audit_projection`, `_cleanup_change_history`, `json`, `utc_now`, `uuid` | – | – |
| `_change_history_view` | 2690 | – | `Any`, `json`, `re` | – | – |
| `list_change_history` | 2722 | `_change_history_view`, `_cleanup_change_history`, `database` | `Any`, `CHANGE_HISTORY_MAX_ROWS`, `DB_LOCK`, `_change_history_view`, `_cleanup_change_history`, `database` | – | – |
| `_history_current` | 2733 | `_audit_projection`, `_history_current_record`, `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `_audit_projection`, `_history_current_record`, `json`, `normalize_profile` | – | – |
| `_history_current_record` | 2745 | `AppError` | `Any`, `AppError`, `SELECT_COMPETITION_SQL` | – | – |
| `_history_target` | 2759 | `AppError` | `Any`, `AppError`, `json` | – | – |
| `_history_preview` | 2775 | `AppError`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, `database`, `utc_now` | `Any`, `AppError`, `CHANGE_HISTORY_TTL_SECONDS`, `DB_LOCK`, `SELECT_ACTION_PROPOSAL_SQL`, `UUID_PATTERN`, `_audit_hash`, `_change_history_view`, `_coach_action_hash`, `_coach_action_view`, `_history_current`, `_history_target`, … (+6) | – | – |
| `_undo_history_state` | 2813 | `AppError`, `_audit_hash`, `_history_current`, `_history_target` | `Any`, `AppError`, `UUID_PATTERN`, `_audit_hash`, `_history_current`, `_history_target`, `re`, `sqlite3` | – | – |
| `_undo_profile_change` | 2833 | `normalize_profile` | `Any`, `DEFAULT_PROFILE`, `PROFILE_REPOSITORY`, `json`, `normalize_profile`, `sqlite3` | – | – |
| `_undo_workout_library_change` | 2843 | `AppError`, `normalize_library_workout`, `utc_now` | `Any`, `AppError`, `INSERT_LIBRARY_SQL`, `json`, `normalize_library_workout`, `sqlite3`, `utc_now` | – | – |
| `_undo_competition_change` | 2868 | `normalize_competition`, `utc_now` | `Any`, `normalize_competition`, `sqlite3`, `utc_now` | – | – |
| `_planned_unit_undo_state` | 2889 | – | `Any` | – | – |
| `_validate_planned_unit_undo_date` | 2899 | `AppError`, `calendar_conflicts` | `Any`, `AppError`, `calendar_conflicts` | – | – |
| `_undo_existing_planned_unit` | 2908 | `AppError`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `normalize_planned_unit`, `utc_now` | `Any`, `AppError`, `ISO_MIDNIGHT_SUFFIX`, `UPDATE_PLANNED_UNIT_SQL`, `_planned_unit_undo_state`, `_validate_planned_unit_undo_date`, `json`, `normalize_planned_unit`, `sqlite3`, `utc_now` | – | – |
| `_undo_planned_unit_change` | 2934 | `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit` | `Any`, `AppError`, `_insert_planned_unit`, `_undo_existing_planned_unit`, `calendar_conflicts`, `normalize_planned_unit`, `sqlite3` | – | – |
| `_undo_training_plan_change` | 2950 | `utc_now` | `Any`, `sqlite3`, `utc_now` | – | – |
| `_apply_change_undo` | 2979 | `AppError`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | `Any`, `AppError`, `DB_LOCK`, `UNDO_ENTITY_HANDLERS`, `_bump_planning_revision`, `_record_change`, `_undo_history_state`, `database` | – | – |
| `get_kv` | 2994 | `database`, `get_kv` | `DB_LOCK`, `KEY_VALUE_REPOSITORY`, `database`, `get_kv`, `sqlite3` | – | – |

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

`Zielmodul` und `Phase` folgen der Bereichstabelle des vollständigen Plans. Jede Zuordnung ist konkret; eine künftig neu hinzukommende nicht auflösbare Bindung wird als offen markiert und darf nicht stillschweigend erfunden werden. `Status` beschreibt ausschließlich den Stand vor P1.

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
| Importbindung | `ActivityFeedbackRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1111 (direkt/dynamisch unklar) |
| Importbindung | `ChatRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1037 (direkt/dynamisch unklar) |
| Importbindung | `CheckinRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1045 (direkt/dynamisch unklar) |
| Importbindung | `CompetitionRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1077 (direkt/dynamisch unklar) |
| Importbindung | `KeyValueRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1028 (direkt/dynamisch unklar); tests/test_server.py:1062 (direkt/dynamisch unklar) |
| Importbindung | `PlanAdjustmentRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1101 (direkt/dynamisch unklar) |
| Importbindung | `ProfileRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1062 (direkt/dynamisch unklar) |
| Importbindung | `SnapshotRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1124 (direkt/dynamisch unklar) |
| Importbindung | `TrainingPlanRepository` | 49 | `backend/db/repositories` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1086 (direkt/dynamisch unklar) |
| Importbindung | `DatabaseManager` | 50 | `backend/db/manager` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `CURRENT_DATABASE_INDEXES` | 51 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:157 (direkt/dynamisch unklar) |
| Importbindung | `CURRENT_DATABASE_SCHEMA` | 51 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:1492 (direkt/dynamisch unklar); tests/test_server.py:156 (direkt/dynamisch unklar) |
| Importbindung | `configure_cipher` | 51 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `database_index_names` | 51 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:157 (direkt/dynamisch unklar) |
| Importbindung | `database_schema_is_current` | 51 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:155 (direkt/dynamisch unklar) |
| Importbindung | `database_table_names` | 51 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:156 (direkt/dynamisch unklar) |
| Importbindung | `initialize_schema` | 51 | `backend/db/schema` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `Config` | 60 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `DEFAULT_OPENAI_BASE_URL` | 60 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:4818 (direkt/dynamisch unklar) |
| Importbindung | `load_config` | 60 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `load_config_env` | 60 | `backend/config` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsReadTransport` | 61 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `IntervalsWriteTransport` | 61 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `fetch_paged_collection` | 61 | `backend/providers/intervals` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_function_tools` | 62 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `gemini_response_text` | 62 | `backend/providers/gemini` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_failure_reason` | 63 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `openai_response_text` | 63 | `backend/providers/openai` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `provider_error_detail` | 64 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_bounded_response` | 64 | `backend/providers/http` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `WorkoutTextError` | 65 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `canonical_workout_zones` | 65 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `structured_duration` | 65 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `verify_workout_readback` | 65 | `backend/providers/workout_text` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `GarminCollectionOptions` | 66 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `collect_garmin_data` | 66 | `backend/providers/garmin` | P1 | bereits ausgelagert (Importbindung) | tests/test_provider_review.py:214 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:240 (Monkeypatch/getattr/sys.modules) |
| Importbindung | `ical_duration` | 67 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_date` | 67 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `parse_ics_value` | 67 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `unfold_ical` | 67 | `backend/providers/calendar` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `split_date_windows` | 68 | `backend/sync/windows` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_cursor` | 69 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `write_cursor` | 69 | `backend/sync/cursors` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_sync_operation_state` | 70 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `project_sync_status` | 70 | `backend/sync/status` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `daily_sync_is_due` | 71 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_daily_sync_value` | 71 | `backend/sync/daily` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `cleanup_refresh_history` | 72 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `create_refresh_record` | 72 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `finish_refresh_record` | 72 | `backend/sync/refresh` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `latest_snapshot_in_transaction` | 73 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `save_snapshot_in_transaction` | 73 | `backend/sync/snapshots` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ReconcileDependencies` | 74 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `persist_planned_unit_state` | 74 | `backend/sync/reconcile` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_payload` | 75 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `planned_unit_rows` | 75 | `backend/planning/repository` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_bounds` | 76 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `TRAINING_PLAN_STATUSES` | 77 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `update_plan_metadata` | 77 | `backend/planning/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `AdaptiveDependencies` | 78 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_adaptive_changes` | 78 | `backend/planning/adaptive` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `PlanningChangeDependencies` | 79 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes` | 79 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `apply_structured_changes_in_db` | 79 | `backend/planning/changes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `JOB_STATUSES` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `ITEM_STATUSES` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `aggregate_job_status` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_progress` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `decode_job_payload` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `has_active_job` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `job_dto` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `list_jobs` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_job` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `is_retryable_error` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `retry_delay` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_job_request` | 82 | `backend/sync/jobs` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTIVITY_FIELDS` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_sections_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `bounded_coach_context_value_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_json_size_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_context_projection_meta_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_activity_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workout_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_local_planned_workouts_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `compact_coach_planned_event_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `detailed_coach_activity_value` | 96 | `backend/coach/context` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_DIALOGUE_INSTRUCTIONS` | 108 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `dialogue_tools` | 108 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `validate_request` | 108 | `backend/coach/dialogue` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `build_tool_contracts` | 109 | `backend/coach/tools` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `command_receipt` | 110 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `effects_from_receipts` | 110 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `mark_resolved_receipts` | 110 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `outcome_status` | 110 | `backend/coach/service` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `authorized_operations` | 114 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_operation` | 114 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `require_scope` | 114 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `scope_values` | 114 | `backend/coach/authorization` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `COACH_ACTION_LABELS` | 115 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_effect_label` | 115 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `coach_failure_lines` | 115 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | tests/test_coach_language_recovery.py:163 (direkt/dynamisch unklar) |
| Importbindung | `coach_observed_sync_lines` | 115 | `backend/coach/outcomes` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_header_items` | 116 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `response_json_bytes` | 116 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | tests/test_server.py:7542 (direkt/dynamisch unklar) |
| Importbindung | `response_headers` | 116 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `session_cookies` | 116 | `backend/http_api/responses` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_audio_body` | 122 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_body` | 122 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `read_request_json` | 122 | `backend/http_api/requests` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_application_state` | 127 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_decode_payload` | 127 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_workout_library` | 127 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_manifest` | 127 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Importbindung | `export_jsonl_rows` | 127 | `backend/backup/export` | P1 | bereits ausgelagert (Importbindung) | keine statisch gefunden |
| Globale Bindung | `Garmin` | 136 | `sync/` | P6 | offen | tests/test_provider_review.py:214 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:237 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4200 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `sqlite_backend` | 141 | `db/` | P1 | offen | tests/test_server.py:1195 (direkt/dynamisch unklar); tests/test_server.py:6596 (direkt/dynamisch unklar); tests/test_server.py:6609 (direkt/dynamisch unklar) |
| Globale Bindung | `SQLCIPHER_AVAILABLE` | 142 | `db/` | P1 | offen | tests/test_audit_remediation.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:314 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:317 (direkt/dynamisch unklar); tests/test_server.py:2840 (direkt/dynamisch unklar); tests/test_server.py:3375 (direkt/dynamisch unklar); tests/test_server.py:6573 (direkt/dynamisch unklar) |
| Globale Bindung | `ROOT` | 148 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:6654 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6674 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PUBLIC_DIR` | 149 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:2365 (direkt/dynamisch unklar); tests/test_server.py:2366 (direkt/dynamisch unklar); tests/test_server.py:2382 (direkt/dynamisch unklar); tests/test_server.py:2383 (direkt/dynamisch unklar); tests/test_server.py:7340 (direkt/dynamisch unklar); tests/test_server.py:7341 (direkt/dynamisch unklar); tests/test_server.py:7352 (direkt/dynamisch unklar); tests/test_server.py:7353 (direkt/dynamisch unklar); tests/test_server.py:7361 (direkt/dynamisch unklar); tests/test_server.py:7362 (direkt/dynamisch unklar); tests/test_server.py:7370 (direkt/dynamisch unklar); tests/test_server.py:7371 (direkt/dynamisch unklar); tests/test_server.py:7377 (direkt/dynamisch unklar); tests/test_server.py:7378 (direkt/dynamisch unklar); tests/test_server.py:7387 (direkt/dynamisch unklar); tests/test_server.py:7388 (direkt/dynamisch unklar); tests/test_server.py:7389 (direkt/dynamisch unklar); tests/test_server.py:7390 (direkt/dynamisch unklar); tests/test_server.py:7601 (direkt/dynamisch unklar); tests/test_server.py:7620 (direkt/dynamisch unklar); tests/test_server.py:8721 (direkt/dynamisch unklar); tests/test_server.py:8722 (direkt/dynamisch unklar) |
| Globale Bindung | `DATA_DIR` | 150 | `db/` | P1 | offen | tests/support.py:107 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:27 (Monkeypatch/getattr/sys.modules); tests/test_server.py:100 (direkt/dynamisch unklar); tests/test_server.py:106 (direkt/dynamisch unklar); tests/test_server.py:115 (direkt/dynamisch unklar); tests/test_server.py:171 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2845 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6654 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6674 (Monkeypatch/getattr/sys.modules); tests/test_server.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `DB_PATH` | 151 | `db/` | P1 | offen | tests/support.py:108 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:28 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:101 (direkt/dynamisch unklar); tests/test_server.py:105 (direkt/dynamisch unklar); tests/test_server.py:107 (direkt/dynamisch unklar); tests/test_server.py:116 (direkt/dynamisch unklar); tests/test_server.py:2845 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:92 (direkt/dynamisch unklar) |
| Globale Bindung | `LOG_PATH` | 152 | `observability.py` | P1 | offen | tests/support.py:109 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:29 (Monkeypatch/getattr/sys.modules); tests/test_server.py:102 (direkt/dynamisch unklar); tests/test_server.py:108 (direkt/dynamisch unklar); tests/test_server.py:117 (direkt/dynamisch unklar); tests/test_server.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `ASSET_INDEX_HTML` | 153 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_API_JS` | 154 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_APP_JS` | 155 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_NAVIGATION_JS` | 156 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STATE_JS` | 157 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_VIEWS_JS` | 158 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_FORMS_JS` | 159 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_COMPONENTS_JS` | 160 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_STYLES_CSS` | 161 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_SERVICE_WORKER_JS` | 162 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_MANIFEST` | 163 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_LOGO` | 164 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `ASSET_ICON` | 165 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_TARGETS` | 166 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `VERSIONED_STATIC_ASSETS` | 181 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_REVALIDATE_ASSETS` | 182 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_NAME` | 183 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_GARMIN_NAME` | 184 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_INTERVALS_WELLNESS_NAME` | 185 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UTC_OFFSET_SUFFIX` | 186 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ISO_MIDNIGHT_SUFFIX` | 187 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `JSON_MEDIA_TYPE` | 188 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OCTET_STREAM_MIME` | 189 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSES_PATH` | 190 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_API_KEY_ERROR` | 191 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_API_KEY_ERROR` | 192 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_KEY_ERROR` | 193 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `VO2MAX_UNIT` | 194 | `performance/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_RUN_PREDICTION_SOURCE` | 195 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_STARTED_EVENT` | 196 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_HTTP_COMPLETED_EVENT` | 197 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLAN_CONSTRAINTS_PREFIX` | 198 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_SCOPE_PREFIX` | 199 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LOCAL_INTERVALS_SCOPE` | 200 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `WORKDAY_TIME_LABEL` | 201 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_WORKOUT_LABEL` | 202 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `FULL_RESYNC_LABEL` | 203 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `NOT_FOUND_ERROR` | 204 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INTERNAL_SERVER_ERROR` | 205 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DAILY_AUTO_UPDATE_LABEL` | 206 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_NOT_FOUND_ERROR` | 207 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_ABORTED_ERROR` | 208 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `APP_NAME` | 209 | `config.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `REDACTED_PATH` | 210 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UUID_PATTERN` | 211 | `http_api/` | P10 | offen | tests/test_server.py:3211 (direkt/dynamisch unklar) |
| Globale Bindung | `PAYLOAD_HASH_PATTERN` | 212 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `DATE_ONLY_PATTERN` | 213 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMPETITION_SQL` | 214 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_ACTION_PROPOSAL_SQL` | 215 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INSERT_LIBRARY_SQL` | 216 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_PLANNED_UNIT_SQL` | 217 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMPETITION_CONFLICT_SQL` | 218 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNED_PAYLOAD_SQL` | 219 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_LIBRARY_PAYLOAD_SQL` | 220 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UPDATE_COMMAND_RECEIPT_SQL` | 221 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_COMMAND_RECEIPT_SQL` | 222 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_PLANNING_REVISION_SQL` | 223 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SELECT_USER_MESSAGE_SQL` | 224 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `STRUCTURED_AUTHORIZATION_ERROR` | 225 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INVALID_PLANNING_ID_ERROR` | 226 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CORRUPT_PLANNING_ERROR` | 227 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INVALID_LIBRARY_ID_ERROR` | 228 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CORRUPT_LIBRARY_ERROR` | 229 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `INVALID_PLANNING_DATE_ERROR` | 230 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `STALE_PLANNING_REVISION_ERROR` | 231 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `UNSUPPORTED_BYDAY_ERROR` | 232 | `errors.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `STATIC_IMMUTABLE_MAX_AGE` | 233 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `APP_VERSION` | 234 | `server.py / Composition Root` | P11 | verbleibt bis P11 (prüfen) | tests/test_server.py:7334 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BODY_BYTES` | 235 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_AUDIO_BODY_BYTES` | 236 | `http_api/` | P10 | offen | tests/test_server.py:4873 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_BACKUP_BYTES` | 237 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_PRIVACY_EXPORT_BYTES` | 238 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `MIN_EXPORT_FREE_BYTES` | 239 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `EXPORT_TIME_LIMIT_SECONDS` | 240 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `STREAM_CHUNK_BYTES` | 241 | `coach/streams.py` | P8 | offen | tests/test_server.py:1463 (direkt/dynamisch unklar); tests/test_server.py:1473 (direkt/dynamisch unklar); tests/test_server.py:1474 (direkt/dynamisch unklar) |
| Globale Bindung | `MAX_EXTERNAL_CALENDAR_BYTES` | 242 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_FETCH_TIMEOUT_SECONDS` | 243 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_CONNECTION_TIMEOUT_SECONDS` | 244 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MAX_EXTERNAL_RESPONSE_BYTES` | 245 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_DEFAULT_MAX_OUTPUT_TOKENS` | 249 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LONG_PLAN_MAX_OUTPUT_TOKENS` | 250 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_FOLLOWUP_MAX_OUTPUT_TOKENS` | 251 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_TIMEOUT_SECONDS` | 252 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `MESSAGE_ATTACHMENTS_QUERY` | 253 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_RESPONSE_ERROR_CODES` | 255 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_API_BASE_URL` | 263 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_BACKGROUND_POLL_SECONDS` | 264 | `providers/` | P2 | offen | tests/test_server.py:5859 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `OPENAI_BACKGROUND_MAX_SECONDS` | 265 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_HORIZON_DAYS` | 266 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_BACKGROUND_UNIT_LIMIT` | 267 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_TRAINING_CHANGE_LIMIT` | 268 | `coach/` | P7 | offen | tests/test_server.py:4901 (direkt/dynamisch unklar); tests/test_server.py:5227 (direkt/dynamisch unklar); tests/test_server.py:5235 (direkt/dynamisch unklar); tests/test_server.py:5587 (direkt/dynamisch unklar); tests/test_server.py:5717 (direkt/dynamisch unklar); tests/test_server.py:5727 (direkt/dynamisch unklar); tests/test_server.py:5729 (direkt/dynamisch unklar); tests/test_server.py:5732 (direkt/dynamisch unklar); tests/test_server.py:5735 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5749 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `INTERVALS_SYNC_WAIT_SECONDS` | 269 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `DB_LOCK` | 270 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:148 (direkt/dynamisch unklar); tests/test_audit_remediation.py:154 (direkt/dynamisch unklar); tests/test_audit_remediation.py:168 (direkt/dynamisch unklar); tests/test_audit_remediation.py:182 (direkt/dynamisch unklar); tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_audit_remediation.py:66 (direkt/dynamisch unklar); tests/test_audit_remediation.py:71 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_server.py:1008 (direkt/dynamisch unklar); tests/test_server.py:122 (direkt/dynamisch unklar); tests/test_server.py:1282 (direkt/dynamisch unklar); tests/test_server.py:1287 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1308 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1504 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar); tests/test_server.py:1641 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2589 (direkt/dynamisch unklar); tests/test_server.py:2602 (direkt/dynamisch unklar); tests/test_server.py:2658 (direkt/dynamisch unklar); tests/test_server.py:2681 (direkt/dynamisch unklar); tests/test_server.py:2810 (direkt/dynamisch unklar); tests/test_server.py:2823 (direkt/dynamisch unklar); tests/test_server.py:2828 (direkt/dynamisch unklar); tests/test_server.py:3026 (direkt/dynamisch unklar); tests/test_server.py:3106 (direkt/dynamisch unklar); tests/test_server.py:4629 (direkt/dynamisch unklar); tests/test_server.py:4920 (direkt/dynamisch unklar); tests/test_server.py:5052 (direkt/dynamisch unklar); tests/test_server.py:5075 (direkt/dynamisch unklar); tests/test_server.py:5098 (direkt/dynamisch unklar); tests/test_server.py:5120 (direkt/dynamisch unklar); tests/test_server.py:5134 (direkt/dynamisch unklar); tests/test_server.py:5140 (direkt/dynamisch unklar); tests/test_server.py:5157 (direkt/dynamisch unklar); tests/test_server.py:5165 (direkt/dynamisch unklar); tests/test_server.py:5487 (direkt/dynamisch unklar); tests/test_server.py:5529 (direkt/dynamisch unklar); tests/test_server.py:5617 (direkt/dynamisch unklar); tests/test_server.py:5640 (direkt/dynamisch unklar); tests/test_server.py:5882 (direkt/dynamisch unklar); tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar); tests/test_server.py:592 (direkt/dynamisch unklar); tests/test_server.py:5987 (direkt/dynamisch unklar); tests/test_server.py:6009 (direkt/dynamisch unklar); tests/test_server.py:6018 (direkt/dynamisch unklar); tests/test_server.py:6143 (direkt/dynamisch unklar); tests/test_server.py:636 (direkt/dynamisch unklar); tests/test_server.py:6435 (direkt/dynamisch unklar); tests/test_server.py:647 (direkt/dynamisch unklar); tests/test_server.py:6498 (direkt/dynamisch unklar); tests/test_server.py:6543 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6591 (direkt/dynamisch unklar); tests/test_server.py:661 (direkt/dynamisch unklar); tests/test_server.py:6767 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:6786 (direkt/dynamisch unklar); tests/test_server.py:6937 (direkt/dynamisch unklar); tests/test_server.py:7731 (direkt/dynamisch unklar); tests/test_server.py:8558 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8563 (direkt/dynamisch unklar); tests/test_server.py:8699 (direkt/dynamisch unklar); tests/test_server.py:8713 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_LOCK` | 271 | `sync/` | P6 | offen | tests/test_coach_review.py:42 (direkt/dynamisch unklar); tests/test_coach_review.py:57 (direkt/dynamisch unklar); tests/test_coach_review.py:66 (direkt/dynamisch unklar); tests/test_coach_review.py:67 (direkt/dynamisch unklar); tests/test_server.py:7741 (direkt/dynamisch unklar); tests/test_server.py:7753 (direkt/dynamisch unklar); tests/test_server.py:7756 (direkt/dynamisch unklar); tests/test_server.py:7769 (direkt/dynamisch unklar); tests/test_server.py:7770 (direkt/dynamisch unklar); tests/test_workout_repair.py:141 (direkt/dynamisch unklar); tests/test_workout_repair.py:148 (direkt/dynamisch unklar); tests/test_workout_repair.py:159 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_LIBRARY_SYNC_LOCK` | 272 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNC_GUARD` | 273 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_UNIT_SYNCS` | 274 | `sync/` | P6 | offen | tests/test_workout_repair.py:323 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SYNC_LOCK` | 275 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PERFORMANCE_LOCK` | 276 | `performance/` | P3 | offen | tests/test_server.py:600 (direkt/dynamisch unklar); tests/test_server.py:606 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_CONVERSATION_LOCK` | 277 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_LOCK` | 278 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_STREAM_LOCK` | 279 | `coach/streams.py` | P8 | offen | tests/support.py:153 (direkt/dynamisch unklar); tests/test_server.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_STREAMS` | 280 | `coach/streams.py` | P8 | offen | tests/support.py:154 (direkt/dynamisch unklar); tests/test_server.py:148 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE_LIMIT` | 281 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8476 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_QUEUE` | 282 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8476 (direkt/dynamisch unklar); tests/test_server.py:8489 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_LOCK_TIMEOUT_SECONDS` | 283 | `coach/conversation.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER_LOCK` | 284 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WAKE` | 285 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_STOP` | 286 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_WORKER` | 287 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_JOB_CANCEL_EVENTS` | 288 | `coach/jobs.py` | P8 | offen | tests/support.py:155 (direkt/dynamisch unklar); tests/test_audit_remediation.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:750 (direkt/dynamisch unklar); tests/test_server.py:149 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_LOCK` | 289 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:283 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:103 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:126 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:144 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:161 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:175 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:51 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:63 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:78 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_LOCK` | 290 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:244 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `EXTERNAL_CALENDAR_LOCK` | 291 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_LOCK` | 292 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER_LOCK` | 293 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WAKE` | 294 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_STOP` | 295 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_WORKER` | 296 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_LOCK` | 297 | `http_api/auth.py` | P10 | offen | tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSIONS` | 298 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `STATE_EVENT_CONDITION` | 299 | `runtime/events.py` | P1 | offen | tests/test_server.py:1740 (direkt/dynamisch unklar) |
| Globale Bindung | `STATE_EVENTS` | 300 | `runtime/events.py` | P1 | offen | tests/test_server.py:1741 (direkt/dynamisch unklar) |
| Globale Bindung | `STATE_EVENT_NEXT_ID` | 301 | `runtime/events.py` | P1 | offen | tests/test_server.py:1742 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_LOCK` | 302 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7993 (direkt/dynamisch unklar); tests/test_server.py:7999 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMITS` | 303 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7994 (direkt/dynamisch unklar); tests/test_server.py:7995 (direkt/dynamisch unklar); tests/test_server.py:8000 (direkt/dynamisch unklar); tests/test_server.py:8001 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_JOB_RE` | 304 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RESOLVE_RE` | 305 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_EXTERNAL_PREFIX` | 306 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_EVENT_EXTERNAL_PREFIX` | 307 | `coach/` | P7 | offen | tests/test_workout_repair.py:222 (direkt/dynamisch unklar); tests/test_workout_repair.py:59 (direkt/dynamisch unklar) |
| Funktion | `publish_state_event` | 310 | `runtime/events.py` | P1 | offen | tests/test_server.py:1744 (direkt/dynamisch unklar); tests/test_server.py:1757 (direkt/dynamisch unklar); tests/test_server.py:4156 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4930 (Monkeypatch/getattr/sys.modules) |
| Funktion | `state_events_since` | 333 | `runtime/events.py` | P1 | offen | tests/test_server.py:1745 (direkt/dynamisch unklar); tests/test_server.py:1748 (direkt/dynamisch unklar); tests/test_server.py:1755 (direkt/dynamisch unklar); tests/test_server.py:1758 (direkt/dynamisch unklar) |
| Klasse | `MaintenanceGate` | 350 | `runtime/maintenance.py` | P1 | offen | tests/test_provider_review.py:32 (direkt/dynamisch unklar); tests/test_server.py:2065 (direkt/dynamisch unklar); tests/test_server.py:2096 (direkt/dynamisch unklar) |
| Globale Bindung | `MAINTENANCE_GATE` | 410 | `runtime/maintenance.py` | P1 | offen | tests/test_audit_remediation.py:77 (direkt/dynamisch unklar); tests/test_provider_review.py:108 (direkt/dynamisch unklar); tests/test_provider_review.py:114 (direkt/dynamisch unklar); tests/test_provider_review.py:130 (direkt/dynamisch unklar); tests/test_provider_review.py:144 (direkt/dynamisch unklar); tests/test_provider_review.py:32 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7985 (direkt/dynamisch unklar) |
| Funktion | `maintenance_operation` | 413 | `runtime/maintenance.py` | P1 | offen | tests/test_provider_review.py:103 (direkt/dynamisch unklar) |
| Funktion | `claimed_maintenance_operation` | 421 | `runtime/maintenance.py` | P1 | offen | keine statisch gefunden |
| Klasse | `ProviderResyncGate` | 434 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_RESYNC_GATE` | 481 | `sync/` | P6 | offen | tests/test_server.py:6621 (direkt/dynamisch unklar); tests/test_server.py:6636 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RESYNC_GATE` | 482 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_operation` | 485 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `intervals_operation` | 490 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_operation` | 498 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `load_local_env` | 506 | `config.py` | P1 | offen | tests/test_server.py:6666 (direkt/dynamisch unklar); tests/test_server.py:6691 (direkt/dynamisch unklar) |
| Globale Bindung | `CONFIG` | 511 | `config.py` | P1 | offen | tests/support.py:106 (Monkeypatch/getattr/sys.modules); tests/support.py:106 (direkt/dynamisch unklar); tests/test_audit_remediation.py:152 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:269 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:269 (direkt/dynamisch unklar); tests/test_coach_review.py:23 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:119 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:120 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:139 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:155 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:181 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:182 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:193 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:194 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:71 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:72 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:96 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:97 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:182 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:182 (direkt/dynamisch unklar); tests/test_provider_review.py:195 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:195 (direkt/dynamisch unklar); tests/test_provider_review.py:26 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:26 (direkt/dynamisch unklar); tests/test_provider_review.py:313 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:313 (direkt/dynamisch unklar); tests/test_provider_review.py:321 (direkt/dynamisch unklar); tests/test_provider_review.py:322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:114 (direkt/dynamisch unklar); tests/test_server.py:1195 (direkt/dynamisch unklar); tests/test_server.py:1266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1266 (direkt/dynamisch unklar); tests/test_server.py:169 (direkt/dynamisch unklar); tests/test_server.py:171 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2533 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2533 (direkt/dynamisch unklar); tests/test_server.py:2619 (direkt/dynamisch unklar); tests/test_server.py:2620 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2648 (direkt/dynamisch unklar); tests/test_server.py:2649 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2663 (direkt/dynamisch unklar); tests/test_server.py:2664 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2731 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2731 (direkt/dynamisch unklar); tests/test_server.py:2826 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2826 (direkt/dynamisch unklar); tests/test_server.py:2835 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2835 (direkt/dynamisch unklar); tests/test_server.py:2844 (direkt/dynamisch unklar); tests/test_server.py:2845 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3385 (direkt/dynamisch unklar); tests/test_server.py:3386 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3627 (direkt/dynamisch unklar); tests/test_server.py:3700 (direkt/dynamisch unklar); tests/test_server.py:3720 (direkt/dynamisch unklar); tests/test_server.py:3731 (direkt/dynamisch unklar); tests/test_server.py:3750 (direkt/dynamisch unklar); tests/test_server.py:3926 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3926 (direkt/dynamisch unklar); tests/test_server.py:3944 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3944 (direkt/dynamisch unklar); tests/test_server.py:3954 (direkt/dynamisch unklar); tests/test_server.py:4199 (direkt/dynamisch unklar); tests/test_server.py:4200 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4267 (direkt/dynamisch unklar); tests/test_server.py:4275 (direkt/dynamisch unklar); tests/test_server.py:4367 (direkt/dynamisch unklar); tests/test_server.py:4369 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4412 (direkt/dynamisch unklar); tests/test_server.py:4413 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4437 (direkt/dynamisch unklar); tests/test_server.py:4438 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4561 (direkt/dynamisch unklar); tests/test_server.py:4562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4576 (direkt/dynamisch unklar); tests/test_server.py:4577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4587 (direkt/dynamisch unklar); tests/test_server.py:4588 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4602 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4602 (direkt/dynamisch unklar); tests/test_server.py:4606 (direkt/dynamisch unklar); tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4616 (direkt/dynamisch unklar); tests/test_server.py:4621 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4640 (direkt/dynamisch unklar); tests/test_server.py:4641 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4795 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4795 (direkt/dynamisch unklar); tests/test_server.py:4813 (direkt/dynamisch unklar); tests/test_server.py:4814 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4817 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4817 (direkt/dynamisch unklar); tests/test_server.py:4825 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4825 (direkt/dynamisch unklar); tests/test_server.py:4837 (direkt/dynamisch unklar); tests/test_server.py:4838 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4861 (direkt/dynamisch unklar); tests/test_server.py:4862 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4868 (direkt/dynamisch unklar); tests/test_server.py:4869 (Monkeypatch/getattr/sys.modules); tests/test_server.py:53 (direkt/dynamisch unklar); tests/test_server.py:54 (direkt/dynamisch unklar); tests/test_server.py:582 (direkt/dynamisch unklar); tests/test_server.py:583 (Monkeypatch/getattr/sys.modules); tests/test_server.py:599 (direkt/dynamisch unklar); tests/test_server.py:602 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6060 (direkt/dynamisch unklar); tests/test_server.py:6062 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6074 (direkt/dynamisch unklar); tests/test_server.py:6075 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6089 (direkt/dynamisch unklar); tests/test_server.py:6091 (Monkeypatch/getattr/sys.modules); tests/test_server.py:610 (direkt/dynamisch unklar); tests/test_server.py:6101 (direkt/dynamisch unklar); tests/test_server.py:6104 (Monkeypatch/getattr/sys.modules); tests/test_server.py:611 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6114 (direkt/dynamisch unklar); tests/test_server.py:6122 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6134 (direkt/dynamisch unklar); tests/test_server.py:6135 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6162 (direkt/dynamisch unklar); tests/test_server.py:6163 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6202 (direkt/dynamisch unklar); tests/test_server.py:6203 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6224 (direkt/dynamisch unklar); tests/test_server.py:6225 (Monkeypatch/getattr/sys.modules); tests/test_server.py:623 (direkt/dynamisch unklar); tests/test_server.py:624 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6246 (direkt/dynamisch unklar); tests/test_server.py:6247 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6265 (direkt/dynamisch unklar); tests/test_server.py:6266 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6285 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6285 (direkt/dynamisch unklar); tests/test_server.py:6339 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6339 (direkt/dynamisch unklar); tests/test_server.py:6348 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6348 (direkt/dynamisch unklar); tests/test_server.py:6367 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6367 (direkt/dynamisch unklar); tests/test_server.py:6376 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6376 (direkt/dynamisch unklar); tests/test_server.py:6385 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6385 (direkt/dynamisch unklar); tests/test_server.py:6393 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6393 (direkt/dynamisch unklar); tests/test_server.py:6410 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6410 (direkt/dynamisch unklar); tests/test_server.py:6454 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6454 (direkt/dynamisch unklar); tests/test_server.py:6486 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6486 (direkt/dynamisch unklar); tests/test_server.py:6532 (direkt/dynamisch unklar); tests/test_server.py:6557 (direkt/dynamisch unklar); tests/test_server.py:6565 (direkt/dynamisch unklar); tests/test_server.py:6566 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6577 (direkt/dynamisch unklar); tests/test_server.py:6579 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6624 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6624 (direkt/dynamisch unklar); tests/test_server.py:6644 (direkt/dynamisch unklar); tests/test_server.py:6645 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6822 (direkt/dynamisch unklar); tests/test_server.py:6854 (direkt/dynamisch unklar); tests/test_server.py:6892 (direkt/dynamisch unklar); tests/test_server.py:6924 (direkt/dynamisch unklar); tests/test_server.py:6940 (direkt/dynamisch unklar); tests/test_server.py:6979 (direkt/dynamisch unklar); tests/test_server.py:7012 (direkt/dynamisch unklar); tests/test_server.py:7039 (direkt/dynamisch unklar); tests/test_server.py:7322 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7322 (direkt/dynamisch unklar); tests/test_server.py:7789 (direkt/dynamisch unklar); tests/test_server.py:7793 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7814 (direkt/dynamisch unklar); tests/test_server.py:7815 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7839 (direkt/dynamisch unklar); tests/test_server.py:7843 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7943 (direkt/dynamisch unklar); tests/test_server.py:7944 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7953 (direkt/dynamisch unklar); tests/test_server.py:7954 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8024 (direkt/dynamisch unklar); tests/test_server.py:8026 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8264 (direkt/dynamisch unklar); tests/test_server.py:8265 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8504 (direkt/dynamisch unklar); tests/test_server.py:8505 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8574 (direkt/dynamisch unklar); tests/test_server.py:8575 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8669 (direkt/dynamisch unklar); tests/test_server.py:8676 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8687 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8743 (direkt/dynamisch unklar); tests/test_server.py:8744 (Monkeypatch/getattr/sys.modules); tests/test_server.py:90 (direkt/dynamisch unklar); tests/test_server.py:97 (direkt/dynamisch unklar); tests/test_server.py:971 (direkt/dynamisch unklar); tests/test_server.py:972 (Monkeypatch/getattr/sys.modules); tests/test_server.py:980 (direkt/dynamisch unklar); tests/test_server.py:981 (Monkeypatch/getattr/sys.modules) |
| Klasse | `IntervalsClient` | 514 | `providers/intervals_client.py` | P2 | offen | tests/test_audit_remediation.py:42 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:53 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:69 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:312 (Monkeypatch/getattr/sys.modules); tests/test_intervals_client.py:12 (direkt/dynamisch unklar); tests/test_provider_review.py:80 (direkt/dynamisch unklar); tests/test_server.py:3627 (direkt/dynamisch unklar); tests/test_server.py:3700 (direkt/dynamisch unklar); tests/test_server.py:3720 (direkt/dynamisch unklar); tests/test_server.py:3731 (direkt/dynamisch unklar); tests/test_server.py:3750 (direkt/dynamisch unklar); tests/test_server.py:3822 (direkt/dynamisch unklar); tests/test_server.py:3850 (direkt/dynamisch unklar); tests/test_server.py:3881 (direkt/dynamisch unklar); tests/test_server.py:3882 (direkt/dynamisch unklar); tests/test_server.py:3883 (direkt/dynamisch unklar); tests/test_server.py:3901 (direkt/dynamisch unklar); tests/test_server.py:3945 (direkt/dynamisch unklar); tests/test_server.py:3946 (direkt/dynamisch unklar); tests/test_server.py:3954 (direkt/dynamisch unklar); tests/test_server.py:4267 (direkt/dynamisch unklar); tests/test_server.py:4275 (direkt/dynamisch unklar); tests/test_server.py:6063 (direkt/dynamisch unklar); tests/test_server.py:6076 (direkt/dynamisch unklar); tests/test_server.py:6092 (direkt/dynamisch unklar); tests/test_server.py:6105 (direkt/dynamisch unklar); tests/test_server.py:612 (direkt/dynamisch unklar); tests/test_server.py:6123 (direkt/dynamisch unklar); tests/test_server.py:6164 (direkt/dynamisch unklar); tests/test_server.py:6165 (direkt/dynamisch unklar); tests/test_server.py:6204 (direkt/dynamisch unklar); tests/test_server.py:6226 (direkt/dynamisch unklar); tests/test_server.py:6248 (direkt/dynamisch unklar); tests/test_server.py:6249 (direkt/dynamisch unklar); tests/test_server.py:625 (direkt/dynamisch unklar); tests/test_server.py:6267 (direkt/dynamisch unklar); tests/test_server.py:6468 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6531 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6556 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6821 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6853 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6891 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6923 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6939 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6978 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7011 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7038 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7321 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7711 (direkt/dynamisch unklar); tests/test_server.py:8027 (direkt/dynamisch unklar); tests/test_server.py:8028 (direkt/dynamisch unklar); tests/test_workout_repair.py:152 (direkt/dynamisch unklar); tests/test_workout_repair.py:178 (direkt/dynamisch unklar); tests/test_workout_repair.py:204 (direkt/dynamisch unklar); tests/test_workout_repair.py:22 (direkt/dynamisch unklar); tests/test_workout_repair.py:23 (direkt/dynamisch unklar); tests/test_workout_repair.py:238 (direkt/dynamisch unklar); tests/test_workout_repair.py:24 (direkt/dynamisch unklar); tests/test_workout_repair.py:25 (direkt/dynamisch unklar); tests/test_workout_repair.py:266 (direkt/dynamisch unklar); tests/test_workout_repair.py:294 (direkt/dynamisch unklar); tests/test_workout_repair.py:318 (direkt/dynamisch unklar); tests/test_workout_repair.py:334 (direkt/dynamisch unklar); tests/test_workout_repair.py:355 (direkt/dynamisch unklar); tests/test_workout_repair.py:422 (direkt/dynamisch unklar); tests/test_workout_repair.py:458 (direkt/dynamisch unklar); tests/test_workout_text.py:172 (direkt/dynamisch unklar); tests/test_workout_text.py:35 (direkt/dynamisch unklar) |
| Globale Bindung | `LOGGER` | 817 | `observability.py` | P1 | offen | tests/test_provider_review.py:20 (direkt/dynamisch unklar); tests/test_provider_review.py:21 (direkt/dynamisch unklar); tests/test_provider_review.py:22 (direkt/dynamisch unklar); tests/test_provider_review.py:30 (direkt/dynamisch unklar); tests/test_provider_review.py:39 (direkt/dynamisch unklar); tests/test_provider_review.py:41 (direkt/dynamisch unklar); tests/test_provider_review.py:43 (direkt/dynamisch unklar); tests/test_provider_review.py:44 (direkt/dynamisch unklar); tests/test_server.py:7534 (direkt/dynamisch unklar); tests/test_server.py:7778 (direkt/dynamisch unklar); tests/test_server.py:7779 (direkt/dynamisch unklar); tests/test_server.py:7864 (direkt/dynamisch unklar); tests/test_server.py:7916 (direkt/dynamisch unklar); tests/test_server.py:8030 (direkt/dynamisch unklar); tests/test_server.py:8061 (direkt/dynamisch unklar); tests/test_server.py:8597 (direkt/dynamisch unklar) |
| Globale Bindung | `MODEL_OPTIONS` | 818 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `GEMINI_MODEL_OPTIONS` | 823 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `THINKING_LEVEL_OPTIONS` | 827 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_DISPLAY_DEFAULTS` | 832 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_DISPLAY_MAX_WEEKS` | 833 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `available_ai_providers` | 836 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_ai_provider` | 845 | `settings.py` | P1 | offen | tests/test_coach_attachments.py:176 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:382 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4589 (direkt/dynamisch unklar) |
| Funktion | `save_ai_provider` | 859 | `settings.py` | P1 | offen | tests/test_server.py:4591 (direkt/dynamisch unklar); tests/test_server.py:4597 (direkt/dynamisch unklar) |
| Funktion | `available_model_options` | 871 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_model` | 880 | `settings.py` | P1 | offen | tests/test_server.py:4595 (direkt/dynamisch unklar); tests/test_server.py:4598 (direkt/dynamisch unklar); tests/test_server.py:5427 (direkt/dynamisch unklar); tests/test_server.py:5429 (direkt/dynamisch unklar) |
| Funktion | `save_model` | 888 | `settings.py` | P1 | offen | tests/test_server.py:4590 (direkt/dynamisch unklar); tests/test_server.py:4596 (direkt/dynamisch unklar); tests/test_server.py:5428 (direkt/dynamisch unklar); tests/test_server.py:5431 (direkt/dynamisch unklar) |
| Funktion | `available_thinking_level_options` | 896 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `selected_thinking_level` | 900 | `settings.py` | P1 | offen | tests/test_server.py:5434 (direkt/dynamisch unklar); tests/test_server.py:5436 (direkt/dynamisch unklar) |
| Funktion | `save_thinking_level` | 906 | `settings.py` | P1 | offen | tests/test_server.py:5435 (direkt/dynamisch unklar); tests/test_server.py:5438 (direkt/dynamisch unklar); tests/test_server.py:5455 (direkt/dynamisch unklar) |
| Funktion | `calendar_display_settings` | 914 | `settings.py` | P1 | offen | tests/test_server.py:5441 (direkt/dynamisch unklar); tests/test_server.py:5446 (direkt/dynamisch unklar); tests/test_server.py:5452 (direkt/dynamisch unklar) |
| Funktion | `save_calendar_display_settings` | 925 | `settings.py` | P1 | offen | tests/test_server.py:5443 (direkt/dynamisch unklar); tests/test_server.py:5448 (direkt/dynamisch unklar); tests/test_server.py:5450 (direkt/dynamisch unklar) |
| Globale Bindung | `REDACTED_URL_QUERY_KEYS` | 946 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `URL_VALUE_RE` | 950 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_secret_variants` | 953 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_url_netloc` | 966 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_provider_path` | 979 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_unguessable_url_path_segment` | 1002 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_redact_url` | 1012 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_calendar_url` | 1036 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `redact_text` | 1046 | `observability.py` | P1 | offen | tests/test_server.py:4603 (direkt/dynamisch unklar); tests/test_server.py:7804 (direkt/dynamisch unklar) |
| Funktion | `sanitize_log_value` | 1072 | `observability.py` | P1 | offen | keine statisch gefunden |
| Klasse | `JsonLogFormatter` | 1084 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `initialise_logging` | 1100 | `observability.py` | P1 | offen | tests/test_provider_review.py:31 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7777 (direkt/dynamisch unklar); tests/test_server.py:7842 (direkt/dynamisch unklar); tests/test_server.py:7912 (direkt/dynamisch unklar); tests/test_server.py:8025 (direkt/dynamisch unklar); tests/test_server.py:8054 (direkt/dynamisch unklar); tests/test_server.py:8328 (direkt/dynamisch unklar); tests/test_server.py:8590 (direkt/dynamisch unklar) |
| Funktion | `external_result_context` | 1122 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `provider_error` | 1133 | `errors.py` | P1 | offen | keine statisch gefunden |
| Funktion | `external_call` | 1154 | `providers/http.py` | P2 | offen | tests/test_server.py:1734 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7817 (direkt/dynamisch unklar); tests/test_server.py:7893 (direkt/dynamisch unklar); tests/test_server.py:7908 (direkt/dynamisch unklar); tests/test_server.py:8591 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_PROFILE` | 1217 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_FORECAST_DAYS` | 1236 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RECOMMENDATION_DAYS` | 1237 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICON_D2_DAYS` | 1238 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_DAYS` | 1239 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_LONG_RIDE_MINUTES` | 1240 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ADAPTIVE_MAX_MINUTES` | 1241 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_SECONDS` | 1242 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CACHE_KEY` | 1243 | `weather/` | P3 | offen | tests/test_audit_remediation.py:119 (direkt/dynamisch unklar); tests/test_audit_remediation.py:144 (direkt/dynamisch unklar); tests/test_audit_remediation.py:82 (direkt/dynamisch unklar); tests/test_server.py:1183 (direkt/dynamisch unklar); tests/test_server.py:1185 (direkt/dynamisch unklar); tests/test_server.py:1209 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1389 (direkt/dynamisch unklar); tests/test_server.py:1527 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_HISTORY_KEY` | 1244 | `weather/` | P3 | offen | tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_BATTERY_HISTORY_KEY` | 1245 | `history/` | P5 | offen | tests/test_server.py:4209 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_FAILURE_KEY` | 1246 | `weather/` | P3 | offen | tests/test_server.py:1203 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1210 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar) |
| Globale Bindung | `WEATHER_RETRY_BASE_SECONDS` | 1247 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_RETRY_MAX_SECONDS` | 1248 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LATITUDE_BOUNDS` | 1249 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `NRW_LONGITUDE_BOUNDS` | 1250 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_CONDITIONS` | 1251 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `WEATHER_ICONS` | 1281 | `weather/` | P3 | offen | tests/test_server.py:7467 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_PROMPT` | 1313 | `coach/` | P7 | offen | keine statisch gefunden |
| Klasse | `AppError` | 1346 | `errors.py` | P1 | offen | e2e/fixture_runtime.py:25 (direkt/dynamisch unklar); e2e/fixture_runtime.py:95 (direkt/dynamisch unklar); tests/test_coach_attachments.py:164 (direkt/dynamisch unklar); tests/test_coach_attachments.py:170 (direkt/dynamisch unklar); tests/test_coach_attachments.py:177 (direkt/dynamisch unklar); tests/test_coach_attachments.py:285 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:104 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:648 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:75 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:809 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:831 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:92 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:12 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:67 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:76 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:99 (direkt/dynamisch unklar); tests/test_coach_review.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:175 (direkt/dynamisch unklar); tests/test_coach_review.py:185 (direkt/dynamisch unklar); tests/test_coach_review.py:201 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:219 (direkt/dynamisch unklar); tests/test_coach_review.py:230 (direkt/dynamisch unklar); tests/test_coach_review.py:234 (direkt/dynamisch unklar); tests/test_coach_review.py:236 (direkt/dynamisch unklar); tests/test_coach_review.py:246 (direkt/dynamisch unklar); tests/test_coach_review.py:258 (direkt/dynamisch unklar); tests/test_coach_review.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:309 (direkt/dynamisch unklar); tests/test_coach_review.py:328 (direkt/dynamisch unklar); tests/test_coach_review.py:331 (direkt/dynamisch unklar); tests/test_coach_review.py:81 (direkt/dynamisch unklar); tests/test_provider_review.py:160 (direkt/dynamisch unklar); tests/test_provider_review.py:189 (direkt/dynamisch unklar); tests/test_server.py:1250 (direkt/dynamisch unklar); tests/test_server.py:1360 (direkt/dynamisch unklar); tests/test_server.py:1367 (direkt/dynamisch unklar); tests/test_server.py:1484 (direkt/dynamisch unklar); tests/test_server.py:1585 (direkt/dynamisch unklar); tests/test_server.py:1589 (direkt/dynamisch unklar); tests/test_server.py:1615 (direkt/dynamisch unklar); tests/test_server.py:1754 (direkt/dynamisch unklar); tests/test_server.py:2005 (direkt/dynamisch unklar); tests/test_server.py:2011 (direkt/dynamisch unklar); tests/test_server.py:2022 (direkt/dynamisch unklar); tests/test_server.py:2026 (direkt/dynamisch unklar); tests/test_server.py:2027 (direkt/dynamisch unklar); tests/test_server.py:2029 (direkt/dynamisch unklar); tests/test_server.py:2034 (direkt/dynamisch unklar); tests/test_server.py:2037 (direkt/dynamisch unklar); tests/test_server.py:2042 (direkt/dynamisch unklar); tests/test_server.py:2045 (direkt/dynamisch unklar); tests/test_server.py:2050 (direkt/dynamisch unklar); tests/test_server.py:2053 (direkt/dynamisch unklar); tests/test_server.py:2060 (direkt/dynamisch unklar); tests/test_server.py:2085 (direkt/dynamisch unklar); tests/test_server.py:220 (direkt/dynamisch unklar); tests/test_server.py:232 (direkt/dynamisch unklar); tests/test_server.py:2341 (direkt/dynamisch unklar); tests/test_server.py:2451 (direkt/dynamisch unklar); tests/test_server.py:2476 (direkt/dynamisch unklar); tests/test_server.py:2480 (direkt/dynamisch unklar); tests/test_server.py:2523 (direkt/dynamisch unklar); tests/test_server.py:2536 (direkt/dynamisch unklar); tests/test_server.py:2542 (direkt/dynamisch unklar); tests/test_server.py:2582 (direkt/dynamisch unklar); tests/test_server.py:2664 (direkt/dynamisch unklar); tests/test_server.py:2665 (direkt/dynamisch unklar); tests/test_server.py:2670 (direkt/dynamisch unklar); tests/test_server.py:2672 (direkt/dynamisch unklar); tests/test_server.py:285 (direkt/dynamisch unklar); tests/test_server.py:317 (direkt/dynamisch unklar); tests/test_server.py:3212 (direkt/dynamisch unklar); tests/test_server.py:3249 (direkt/dynamisch unklar); tests/test_server.py:3683 (direkt/dynamisch unklar); tests/test_server.py:3783 (direkt/dynamisch unklar); tests/test_server.py:3799 (direkt/dynamisch unklar); tests/test_server.py:3838 (direkt/dynamisch unklar); tests/test_server.py:3865 (direkt/dynamisch unklar); tests/test_server.py:3873 (direkt/dynamisch unklar); tests/test_server.py:3884 (direkt/dynamisch unklar); tests/test_server.py:3905 (direkt/dynamisch unklar); tests/test_server.py:3917 (direkt/dynamisch unklar); tests/test_server.py:3921 (direkt/dynamisch unklar); tests/test_server.py:396 (direkt/dynamisch unklar); tests/test_server.py:4109 (direkt/dynamisch unklar); tests/test_server.py:4270 (direkt/dynamisch unklar); tests/test_server.py:4331 (direkt/dynamisch unklar); tests/test_server.py:4428 (direkt/dynamisch unklar); tests/test_server.py:4441 (direkt/dynamisch unklar); tests/test_server.py:4451 (direkt/dynamisch unklar); tests/test_server.py:4466 (direkt/dynamisch unklar); tests/test_server.py:4480 (direkt/dynamisch unklar); tests/test_server.py:4563 (direkt/dynamisch unklar); tests/test_server.py:4653 (direkt/dynamisch unklar); tests/test_server.py:4655 (direkt/dynamisch unklar); tests/test_server.py:4666 (direkt/dynamisch unklar); tests/test_server.py:4709 (direkt/dynamisch unklar); tests/test_server.py:4777 (direkt/dynamisch unklar); tests/test_server.py:4826 (direkt/dynamisch unklar); tests/test_server.py:485 (direkt/dynamisch unklar); tests/test_server.py:4870 (direkt/dynamisch unklar); tests/test_server.py:4872 (direkt/dynamisch unklar); tests/test_server.py:4896 (direkt/dynamisch unklar); tests/test_server.py:4971 (direkt/dynamisch unklar); tests/test_server.py:5042 (direkt/dynamisch unklar); tests/test_server.py:5207 (direkt/dynamisch unklar); tests/test_server.py:5224 (direkt/dynamisch unklar); tests/test_server.py:5430 (direkt/dynamisch unklar); tests/test_server.py:5437 (direkt/dynamisch unklar); tests/test_server.py:5447 (direkt/dynamisch unklar); tests/test_server.py:5449 (direkt/dynamisch unklar); tests/test_server.py:5598 (direkt/dynamisch unklar); tests/test_server.py:5711 (direkt/dynamisch unklar); tests/test_server.py:5763 (direkt/dynamisch unklar); tests/test_server.py:5776 (direkt/dynamisch unklar); tests/test_server.py:5984 (direkt/dynamisch unklar); tests/test_server.py:6090 (direkt/dynamisch unklar); tests/test_server.py:6094 (direkt/dynamisch unklar); tests/test_server.py:6103 (direkt/dynamisch unklar); tests/test_server.py:6107 (direkt/dynamisch unklar); tests/test_server.py:6125 (direkt/dynamisch unklar); tests/test_server.py:6136 (direkt/dynamisch unklar); tests/test_server.py:6603 (direkt/dynamisch unklar); tests/test_server.py:6616 (direkt/dynamisch unklar); tests/test_server.py:6628 (direkt/dynamisch unklar); tests/test_server.py:736 (direkt/dynamisch unklar); tests/test_server.py:755 (direkt/dynamisch unklar); tests/test_server.py:7551 (direkt/dynamisch unklar); tests/test_server.py:7558 (direkt/dynamisch unklar); tests/test_server.py:7816 (direkt/dynamisch unklar); tests/test_server.py:7824 (direkt/dynamisch unklar); tests/test_server.py:7844 (direkt/dynamisch unklar); tests/test_server.py:7880 (direkt/dynamisch unklar); tests/test_server.py:7914 (direkt/dynamisch unklar); tests/test_server.py:7931 (direkt/dynamisch unklar); tests/test_server.py:8119 (direkt/dynamisch unklar); tests/test_server.py:8160 (direkt/dynamisch unklar); tests/test_server.py:8174 (direkt/dynamisch unklar); tests/test_server.py:8185 (direkt/dynamisch unklar); tests/test_server.py:8266 (direkt/dynamisch unklar); tests/test_server.py:8321 (direkt/dynamisch unklar); tests/test_server.py:8345 (direkt/dynamisch unklar); tests/test_server.py:8375 (direkt/dynamisch unklar); tests/test_server.py:8388 (direkt/dynamisch unklar); tests/test_server.py:8391 (direkt/dynamisch unklar); tests/test_server.py:8483 (direkt/dynamisch unklar); tests/test_server.py:8492 (direkt/dynamisch unklar); tests/test_server.py:8495 (direkt/dynamisch unklar); tests/test_server.py:8498 (direkt/dynamisch unklar); tests/test_server.py:8576 (direkt/dynamisch unklar); tests/test_server.py:8625 (direkt/dynamisch unklar); tests/test_server.py:8646 (direkt/dynamisch unklar); tests/test_server.py:8746 (direkt/dynamisch unklar); tests/test_server.py:960 (direkt/dynamisch unklar); tests/test_workout_repair.py:30 (direkt/dynamisch unklar); tests/test_workout_repair.py:312 (direkt/dynamisch unklar); tests/test_workout_repair.py:472 (direkt/dynamisch unklar); tests/test_workout_repair.py:49 (direkt/dynamisch unklar); tests/test_workout_repair.py:504 (direkt/dynamisch unklar); tests/test_workout_repair.py:507 (direkt/dynamisch unklar); tests/test_workout_repair.py:511 (direkt/dynamisch unklar); tests/test_workout_repair.py:560 (direkt/dynamisch unklar); tests/test_workout_text.py:156 (direkt/dynamisch unklar); tests/test_workout_text.py:166 (direkt/dynamisch unklar); tests/test_workout_text.py:200 (direkt/dynamisch unklar); tests/test_workout_text.py:214 (direkt/dynamisch unklar); tests/test_workout_text.py:25 (direkt/dynamisch unklar); tests/test_workout_text.py:44 (direkt/dynamisch unklar); tests/test_workout_text.py:88 (direkt/dynamisch unklar) |
| Funktion | `public_app_error_status` | 1354 | `errors.py` | P1 | offen | tests/test_server.py:4654 (direkt/dynamisch unklar); tests/test_server.py:4655 (direkt/dynamisch unklar) |
| Klasse | `ClientDisconnected` | 1361 | `errors.py` | P1 | offen | tests/test_server.py:8370 (direkt/dynamisch unklar); tests/test_server.py:8371 (direkt/dynamisch unklar); tests/test_server.py:8419 (direkt/dynamisch unklar) |
| Funktion | `serialise_conversation` | 1365 | `coach/conversation.py` | P7 | offen | tests/test_server.py:8479 (direkt/dynamisch unklar) |
| Funktion | `utc_now` | 1382 | `runtime/` | P1 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_audit_remediation.py:169 (direkt/dynamisch unklar); tests/test_audit_remediation.py:184 (direkt/dynamisch unklar); tests/test_audit_remediation.py:67 (direkt/dynamisch unklar); tests/test_audit_remediation.py:79 (direkt/dynamisch unklar); tests/test_audit_remediation.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:218 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:220 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:257 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_server.py:1007 (direkt/dynamisch unklar); tests/test_server.py:1158 (direkt/dynamisch unklar); tests/test_server.py:1161 (direkt/dynamisch unklar); tests/test_server.py:1229 (direkt/dynamisch unklar); tests/test_server.py:1248 (direkt/dynamisch unklar); tests/test_server.py:1395 (direkt/dynamisch unklar); tests/test_server.py:1399 (direkt/dynamisch unklar); tests/test_server.py:1515 (direkt/dynamisch unklar); tests/test_server.py:1644 (direkt/dynamisch unklar); tests/test_server.py:2531 (direkt/dynamisch unklar); tests/test_server.py:2592 (direkt/dynamisch unklar); tests/test_server.py:2605 (direkt/dynamisch unklar); tests/test_server.py:2661 (direkt/dynamisch unklar); tests/test_server.py:2684 (direkt/dynamisch unklar); tests/test_server.py:2813 (direkt/dynamisch unklar); tests/test_server.py:3109 (direkt/dynamisch unklar); tests/test_server.py:3113 (direkt/dynamisch unklar); tests/test_server.py:5054 (direkt/dynamisch unklar); tests/test_server.py:5077 (direkt/dynamisch unklar); tests/test_server.py:5100 (direkt/dynamisch unklar); tests/test_server.py:5122 (direkt/dynamisch unklar); tests/test_server.py:5143 (direkt/dynamisch unklar); tests/test_server.py:5167 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5642 (direkt/dynamisch unklar); tests/test_server.py:5897 (direkt/dynamisch unklar); tests/test_server.py:5916 (direkt/dynamisch unklar); tests/test_server.py:7732 (direkt/dynamisch unklar) |
| Globale Bindung | `KEY_VALUE_REPOSITORY` | 1386 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `PROFILE_REPOSITORY` | 1387 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_REPOSITORY` | 1388 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `TRAINING_PLAN_REPOSITORY` | 1389 | `planning/` | P4 | offen | tests/test_server.py:5053 (direkt/dynamisch unklar); tests/test_server.py:5076 (direkt/dynamisch unklar); tests/test_server.py:5099 (direkt/dynamisch unklar); tests/test_server.py:5121 (direkt/dynamisch unklar); tests/test_server.py:5135 (direkt/dynamisch unklar); tests/test_server.py:5142 (direkt/dynamisch unklar); tests/test_server.py:5158 (direkt/dynamisch unklar); tests/test_server.py:5166 (direkt/dynamisch unklar); tests/test_server.py:5618 (direkt/dynamisch unklar); tests/test_server.py:5641 (direkt/dynamisch unklar) |
| Globale Bindung | `PLAN_ADJUSTMENT_REPOSITORY` | 1390 | `planning/` | P4 | offen | tests/test_server.py:7732 (direkt/dynamisch unklar) |
| Globale Bindung | `CHAT_REPOSITORY` | 1391 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:266 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:838 (direkt/dynamisch unklar); tests/test_server.py:4551 (direkt/dynamisch unklar) |
| Globale Bindung | `CHECKIN_REPOSITORY` | 1392 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `ACTIVITY_FEEDBACK_REPOSITORY` | 1393 | `activities/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `SNAPSHOT_REPOSITORY` | 1394 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `security_configuration_error` | 1397 | `config.py` | P1 | offen | tests/test_audit_remediation.py:189 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:183 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:315 (direkt/dynamisch unklar) |
| Globale Bindung | `OPERATION_CONTEXT` | 1407 | `observability.py` | P1 | offen | tests/test_server.py:8011 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER` | 1408 | `db/manager.py` | P1 | offen | tests/support.py:117 (direkt/dynamisch unklar); tests/support.py:118 (direkt/dynamisch unklar); tests/support.py:119 (direkt/dynamisch unklar); tests/test_provider_review.py:329 (direkt/dynamisch unklar); tests/test_provider_review.py:45 (direkt/dynamisch unklar); tests/test_provider_review.py:46 (direkt/dynamisch unklar); tests/test_provider_review.py:47 (direkt/dynamisch unklar); tests/test_server.py:178 (direkt/dynamisch unklar) |
| Globale Bindung | `DATABASE_MANAGER_SIGNATURE` | 1409 | `db/manager.py` | P1 | offen | tests/support.py:120 (direkt/dynamisch unklar); tests/test_provider_review.py:330 (direkt/dynamisch unklar); tests/test_provider_review.py:48 (direkt/dynamisch unklar); tests/test_server.py:179 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETENTION_DAYS` | 1411 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_MAX_ROWS` | 1412 | `sync/` | P6 | offen | tests/test_server.py:8710 (direkt/dynamisch unklar); tests/test_server.py:8715 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_BASE_SECONDS` | 1413 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_RETRY_MAX_SECONDS` | 1414 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_STALE_SECONDS` | 1415 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `PROVIDER_REFRESH_LABELS` | 1423 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_MAX_ATTEMPTS` | 1431 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_BASE_SECONDS` | 1432 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_RETRY_MAX_SECONDS` | 1433 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_POLL_SECONDS` | 1434 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_JOB_LIST_LIMIT` | 1435 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_MORNING_BODY_BATTERY_LOCK_WAIT_SECONDS` | 1436 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_RETRY_SECONDS` | 1437 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_MAX_ATTEMPTS` | 1438 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_DURATION_SECONDS` | 1439 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_MAX_ENTRIES` | 1440 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_STATE_KEY` | 1441 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `DIAGNOSTIC_CAPTURE_ENTRIES_KEY` | 1442 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_RETENTION_DAYS` | 1444 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_MAX_ROWS` | 1447 | `history/` | P5 | offen | tests/test_server.py:5587 (direkt/dynamisch unklar); tests/test_server.py:5598 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `CHANGE_HISTORY_TTL_SECONDS` | 1448 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ENTITY_TYPES` | 1449 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_ACTIONS` | 1450 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PROFILE_FIELDS` | 1451 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_LIBRARY_FIELDS` | 1456 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLANNED_UNIT_FIELDS` | 1461 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_COMPETITION_FIELDS` | 1466 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `CHANGE_HISTORY_PLAN_FIELDS` | 1470 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_MAX_ENTRIES` | 1472 | `planning/` | P4 | offen | tests/test_server.py:360 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_BULK_PREVIEW_TTL_SECONDS` | 1473 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_BULK_LOCAL_ACTIONS` | 1474 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `OPERATION_CLEANUP_REASONS` | 1477 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_trigger` | 1488 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_error_code` | 1494 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `operation_result_count` | 1503 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `log_operation_event` | 1513 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `observed_operation` | 1540 | `observability.py` | P1 | offen | tests/test_server.py:8008 (direkt/dynamisch unklar) |
| Funktion | `observed_sync` | 1561 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `database_manager` | 1604 | `db/manager.py` | P1 | offen | tests/test_audit_remediation.py:280 (direkt/dynamisch unklar); tests/test_provider_review.py:186 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:196 (direkt/dynamisch unklar); tests/test_provider_review.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:328 (direkt/dynamisch unklar); tests/test_server.py:176 (direkt/dynamisch unklar) |
| Funktion | `database` | 1631 | `db/manager.py` | P1 | offen | e2e/fixture_runtime.py:90 (direkt/dynamisch unklar); tests/support.py:131 (direkt/dynamisch unklar); tests/support.py:149 (direkt/dynamisch unklar); tests/test_audit_remediation.py:148 (direkt/dynamisch unklar); tests/test_audit_remediation.py:154 (direkt/dynamisch unklar); tests/test_audit_remediation.py:168 (direkt/dynamisch unklar); tests/test_audit_remediation.py:182 (direkt/dynamisch unklar); tests/test_audit_remediation.py:30 (direkt/dynamisch unklar); tests/test_audit_remediation.py:66 (direkt/dynamisch unklar); tests/test_audit_remediation.py:71 (direkt/dynamisch unklar); tests/test_coach_attachments.py:148 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:191 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:208 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:219 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:242 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:265 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:626 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:702 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:712 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:724 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:744 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:837 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:850 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:856 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:878 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:919 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:106 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:136 (direkt/dynamisch unklar); tests/test_coach_review.py:128 (direkt/dynamisch unklar); tests/test_coach_review.py:179 (direkt/dynamisch unklar); tests/test_coach_review.py:192 (direkt/dynamisch unklar); tests/test_coach_review.py:217 (direkt/dynamisch unklar); tests/test_coach_review.py:222 (direkt/dynamisch unklar); tests/test_coach_review.py:295 (direkt/dynamisch unklar); tests/test_coach_review.py:301 (direkt/dynamisch unklar); tests/test_coach_review.py:317 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:185 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:292 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:304 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:311 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:461 (direkt/dynamisch unklar); tests/test_server.py:1008 (direkt/dynamisch unklar); tests/test_server.py:1029 (direkt/dynamisch unklar); tests/test_server.py:1038 (direkt/dynamisch unklar); tests/test_server.py:1052 (direkt/dynamisch unklar); tests/test_server.py:1064 (direkt/dynamisch unklar); tests/test_server.py:1078 (direkt/dynamisch unklar); tests/test_server.py:1087 (direkt/dynamisch unklar); tests/test_server.py:1096 (direkt/dynamisch unklar); tests/test_server.py:1103 (direkt/dynamisch unklar); tests/test_server.py:1114 (direkt/dynamisch unklar); tests/test_server.py:1125 (direkt/dynamisch unklar); tests/test_server.py:122 (direkt/dynamisch unklar); tests/test_server.py:1282 (direkt/dynamisch unklar); tests/test_server.py:1287 (direkt/dynamisch unklar); tests/test_server.py:1290 (direkt/dynamisch unklar); tests/test_server.py:1308 (direkt/dynamisch unklar); tests/test_server.py:1311 (direkt/dynamisch unklar); tests/test_server.py:1315 (direkt/dynamisch unklar); tests/test_server.py:1392 (direkt/dynamisch unklar); tests/test_server.py:1504 (direkt/dynamisch unklar); tests/test_server.py:153 (direkt/dynamisch unklar); tests/test_server.py:1641 (direkt/dynamisch unklar); tests/test_server.py:2528 (direkt/dynamisch unklar); tests/test_server.py:2589 (direkt/dynamisch unklar); tests/test_server.py:2602 (direkt/dynamisch unklar); tests/test_server.py:2658 (direkt/dynamisch unklar); tests/test_server.py:2681 (direkt/dynamisch unklar); tests/test_server.py:2810 (direkt/dynamisch unklar); tests/test_server.py:2823 (direkt/dynamisch unklar); tests/test_server.py:2828 (direkt/dynamisch unklar); tests/test_server.py:2847 (direkt/dynamisch unklar); tests/test_server.py:3026 (direkt/dynamisch unklar); tests/test_server.py:3106 (direkt/dynamisch unklar); tests/test_server.py:3394 (direkt/dynamisch unklar); tests/test_server.py:4550 (direkt/dynamisch unklar); tests/test_server.py:4629 (direkt/dynamisch unklar); tests/test_server.py:4920 (direkt/dynamisch unklar); tests/test_server.py:5052 (direkt/dynamisch unklar); tests/test_server.py:5075 (direkt/dynamisch unklar); tests/test_server.py:5098 (direkt/dynamisch unklar); tests/test_server.py:5120 (direkt/dynamisch unklar); tests/test_server.py:5134 (direkt/dynamisch unklar); tests/test_server.py:5140 (direkt/dynamisch unklar); tests/test_server.py:5157 (direkt/dynamisch unklar); tests/test_server.py:5165 (direkt/dynamisch unklar); tests/test_server.py:5487 (direkt/dynamisch unklar); tests/test_server.py:5529 (direkt/dynamisch unklar); tests/test_server.py:5617 (direkt/dynamisch unklar); tests/test_server.py:5640 (direkt/dynamisch unklar); tests/test_server.py:5882 (direkt/dynamisch unklar); tests/test_server.py:5894 (direkt/dynamisch unklar); tests/test_server.py:5913 (direkt/dynamisch unklar); tests/test_server.py:592 (direkt/dynamisch unklar); tests/test_server.py:5987 (direkt/dynamisch unklar); tests/test_server.py:6009 (direkt/dynamisch unklar); tests/test_server.py:6018 (direkt/dynamisch unklar); tests/test_server.py:6143 (direkt/dynamisch unklar); tests/test_server.py:636 (direkt/dynamisch unklar); tests/test_server.py:6435 (direkt/dynamisch unklar); tests/test_server.py:647 (direkt/dynamisch unklar); tests/test_server.py:6498 (direkt/dynamisch unklar); tests/test_server.py:6543 (direkt/dynamisch unklar); tests/test_server.py:6582 (direkt/dynamisch unklar); tests/test_server.py:6591 (direkt/dynamisch unklar); tests/test_server.py:661 (direkt/dynamisch unklar); tests/test_server.py:6767 (direkt/dynamisch unklar); tests/test_server.py:6776 (direkt/dynamisch unklar); tests/test_server.py:6786 (direkt/dynamisch unklar); tests/test_server.py:6937 (direkt/dynamisch unklar); tests/test_server.py:7731 (direkt/dynamisch unklar); tests/test_server.py:7970 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8429 (direkt/dynamisch unklar); tests/test_server.py:8563 (direkt/dynamisch unklar); tests/test_server.py:8699 (direkt/dynamisch unklar); tests/test_server.py:8713 (direkt/dynamisch unklar); tests/test_workout_repair.py:163 (direkt/dynamisch unklar); tests/test_workout_repair.py:477 (direkt/dynamisch unklar); tests/test_workout_repair.py:549 (direkt/dynamisch unklar) |
| Funktion | `initialise_database` | 1637 | `db/schema.py` | P1 | offen | e2e/fixture_runtime.py:101 (direkt/dynamisch unklar); e2e/fixture_runtime.py:65 (direkt/dynamisch unklar); tests/support.py:114 (direkt/dynamisch unklar); tests/test_audit_remediation.py:271 (direkt/dynamisch unklar); tests/test_coach_review.py:25 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:205 (direkt/dynamisch unklar); tests/test_provider_review.py:324 (direkt/dynamisch unklar); tests/test_provider_review.py:36 (direkt/dynamisch unklar); tests/test_server.py:103 (direkt/dynamisch unklar); tests/test_server.py:109 (direkt/dynamisch unklar); tests/test_server.py:1167 (direkt/dynamisch unklar); tests/test_server.py:152 (direkt/dynamisch unklar); tests/test_server.py:175 (direkt/dynamisch unklar); tests/test_server.py:195 (direkt/dynamisch unklar); tests/test_server.py:2827 (direkt/dynamisch unklar); tests/test_server.py:2836 (direkt/dynamisch unklar); tests/test_server.py:2846 (direkt/dynamisch unklar); tests/test_server.py:3387 (direkt/dynamisch unklar); tests/test_server.py:6580 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_cleanup` | 1679 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_refresh_start` | 1684 | `settings.py` | P1 | offen | tests/test_server.py:8681 (direkt/dynamisch unklar); tests/test_server.py:8697 (direkt/dynamisch unklar); tests/test_server.py:8711 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_finish` | 1696 | `settings.py` | P1 | offen | tests/test_server.py:8682 (direkt/dynamisch unklar); tests/test_server.py:8698 (direkt/dynamisch unklar); tests/test_server.py:8712 (direkt/dynamisch unklar) |
| Funktion | `_provider_refresh_error_code` | 1730 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_error_class` | 1745 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_performance_job` | 1759 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_entries` | 1768 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_plan_push_job` | 1782 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_payload` | 1795 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_payload` | 1805 | `sync/` | P6 | offen | tests/test_workout_repair.py:473 (direkt/dynamisch unklar) |
| Funktion | `_normalized_sync_days` | 1814 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_sync_end_date` | 1824 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_normalized_generic_sync_job` | 1831 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_job_state` | 1856 | `sync/` | P6 | offen | tests/test_audit_remediation.py:277 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:247 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:254 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:643 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:668 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:51 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:90 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:275 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:314 (direkt/dynamisch unklar); tests/test_server.py:205 (direkt/dynamisch unklar); tests/test_server.py:207 (direkt/dynamisch unklar); tests/test_server.py:211 (direkt/dynamisch unklar); tests/test_server.py:222 (direkt/dynamisch unklar); tests/test_server.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:123 (direkt/dynamisch unklar) |
| Funktion | `sync_jobs_state` | 1865 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:131 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:176 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:195 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:233 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:255 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:257 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:260 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:276 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:327 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:369 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:449 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:568 (direkt/dynamisch unklar); tests/test_provider_review.py:141 (direkt/dynamisch unklar); tests/test_provider_review.py:178 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_active` | 1871 | `sync/` | P6 | offen | tests/test_server.py:972 (Monkeypatch/getattr/sys.modules); tests/test_server.py:981 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_enqueue_automatic_performance_refresh` | 1876 | `sync/` | P6 | offen | tests/test_server.py:603 (direkt/dynamisch unklar); tests/test_workout_repair.py:180 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:206 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_performance_refresh_failed` | 1899 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_pending_performance_job_id` | 1907 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_performance_refresh_poll_state` | 1916 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_performance_refresh` | 1934 | `sync/` | P6 | offen | tests/test_server.py:615 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_scheduled_sync_job_at` | 1961 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_operations` | 1970 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_existing_performance_job_id` | 1977 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_sync_job` | 1987 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_created_sync_job` | 2012 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `enqueue_sync_job` | 2026 | `sync/` | P6 | offen | tests/test_audit_remediation.py:239 (direkt/dynamisch unklar); tests/test_audit_remediation.py:272 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:241 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:398 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:649 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:671 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:43 (Monkeypatch/getattr/sys.modules); tests/test_coach_language_recovery.py:43 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:39 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:39 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:74 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:74 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:310 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:133 (direkt/dynamisch unklar); tests/test_provider_review.py:135 (direkt/dynamisch unklar); tests/test_provider_review.py:152 (direkt/dynamisch unklar); tests/test_server.py:200 (direkt/dynamisch unklar); tests/test_server.py:217 (direkt/dynamisch unklar); tests/test_server.py:244 (direkt/dynamisch unklar); tests/test_server.py:341 (Monkeypatch/getattr/sys.modules); tests/test_server.py:428 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4893 (direkt/dynamisch unklar); tests/test_server.py:4897 (direkt/dynamisch unklar); tests/test_server.py:524 (Monkeypatch/getattr/sys.modules); tests/test_server.py:584 (direkt/dynamisch unklar); tests/test_server.py:587 (direkt/dynamisch unklar); tests/test_server.py:602 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6342 (direkt/dynamisch unklar); tests/test_server.py:6351 (direkt/dynamisch unklar); tests/test_server.py:6370 (direkt/dynamisch unklar); tests/test_server.py:6379 (direkt/dynamisch unklar); tests/test_server.py:864 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8691 (direkt/dynamisch unklar); tests/test_server.py:890 (Monkeypatch/getattr/sys.modules); tests/test_server.py:935 (Monkeypatch/getattr/sys.modules); tests/test_server.py:983 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_sync_jobs` | 2053 | `sync/` | P6 | offen | tests/test_server.py:206 (direkt/dynamisch unklar) |
| Funktion | `_claim_sync_job` | 2073 | `sync/` | P6 | offen | tests/test_audit_remediation.py:273 (direkt/dynamisch unklar); tests/test_audit_remediation.py:278 (direkt/dynamisch unklar); tests/test_provider_review.py:134 (direkt/dynamisch unklar); tests/test_provider_review.py:140 (direkt/dynamisch unklar); tests/test_provider_review.py:153 (direkt/dynamisch unklar); tests/test_server.py:203 (direkt/dynamisch unklar); tests/test_server.py:208 (direkt/dynamisch unklar); tests/test_server.py:218 (direkt/dynamisch unklar); tests/test_server.py:251 (direkt/dynamisch unklar); tests/test_server.py:6343 (direkt/dynamisch unklar); tests/test_server.py:6352 (direkt/dynamisch unklar); tests/test_server.py:6371 (direkt/dynamisch unklar); tests/test_server.py:6380 (direkt/dynamisch unklar); tests/test_workout_repair.py:119 (direkt/dynamisch unklar); tests/test_workout_repair.py:174 (direkt/dynamisch unklar); tests/test_workout_repair.py:185 (direkt/dynamisch unklar); tests/test_workout_repair.py:526 (direkt/dynamisch unklar); tests/test_workout_repair.py:544 (direkt/dynamisch unklar); tests/test_workout_repair.py:571 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_update` | 2094 | `sync/` | P6 | offen | tests/test_audit_remediation.py:240 (direkt/dynamisch unklar); tests/test_audit_remediation.py:275 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_item_results` | 2132 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_result_target` | 2138 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_sync_job_result_items` | 2149 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_job_completion_snapshot` | 2169 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_publish_sync_job_result_event` | 2184 | `runtime/` | P1 | offen | keine statisch gefunden |
| Funktion | `_sync_job_update_from_result` | 2201 | `sync/` | P6 | offen | tests/test_workout_repair.py:122 (direkt/dynamisch unklar); tests/test_workout_repair.py:175 (direkt/dynamisch unklar); tests/test_workout_repair.py:193 (direkt/dynamisch unklar); tests/test_workout_repair.py:576 (direkt/dynamisch unklar) |
| Funktion | `_historical_sync_window` | 2214 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_historical_next_end` | 2223 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync_job` | 2230 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_garmin_sync_job` | 2247 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_specific_job` | 2259 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_sync_job` | 2271 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:250 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:253 (direkt/dynamisch unklar); tests/test_provider_review.py:137 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:166 (Monkeypatch/getattr/sys.modules); tests/test_server.py:209 (Monkeypatch/getattr/sys.modules); tests/test_server.py:220 (Monkeypatch/getattr/sys.modules); tests/test_server.py:233 (direkt/dynamisch unklar); tests/test_server.py:253 (Monkeypatch/getattr/sys.modules); tests/test_server.py:550 (direkt/dynamisch unklar); tests/test_server.py:551 (direkt/dynamisch unklar); tests/test_server.py:563 (direkt/dynamisch unklar); tests/test_server.py:576 (direkt/dynamisch unklar); tests/test_workout_repair.py:120 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_fallback_status` | 2294 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_next_historical_backfill` | 2303 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_requeue_claimed_sync_job` | 2323 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_claimed_sync_job_failure` | 2343 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_claimed_sync_job` | 2361 | `sync/` | P6 | offen | tests/test_provider_review.py:138 (direkt/dynamisch unklar); tests/test_provider_review.py:167 (direkt/dynamisch unklar); tests/test_server.py:210 (direkt/dynamisch unklar); tests/test_server.py:221 (direkt/dynamisch unklar); tests/test_server.py:254 (direkt/dynamisch unklar); tests/test_server.py:6343 (direkt/dynamisch unklar); tests/test_server.py:6352 (direkt/dynamisch unklar); tests/test_server.py:6371 (direkt/dynamisch unklar); tests/test_server.py:6380 (direkt/dynamisch unklar) |
| Funktion | `_sync_job_worker_loop` | 2371 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `start_sync_job_worker` | 2386 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `resolve_sync_job` | 2398 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_scheduled_provider_retry_at` | 2421 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_inputs` | 2440 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_last_good_state` | 2474 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_fallback_error_code` | 2484 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_error_code` | 2488 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_provider_freshness_status` | 2496 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `provider_freshness_state` | 2517 | `settings.py` | P1 | offen | tests/test_server.py:6140 (direkt/dynamisch unklar); tests/test_server.py:8678 (direkt/dynamisch unklar); tests/test_server.py:8683 (direkt/dynamisch unklar); tests/test_server.py:8688 (direkt/dynamisch unklar); tests/test_server.py:8695 (direkt/dynamisch unklar); tests/test_server.py:8705 (direkt/dynamisch unklar) |
| Funktion | `_audit_projection_fields` | 2558 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_payload_projection` | 2572 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_projection` | 2583 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_hash` | 2607 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_audit_diff` | 2612 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_cleanup_change_history` | 2624 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_reserve_change_history_capacity` | 2634 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_record_change` | 2651 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_change_history_view` | 2690 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `list_change_history` | 2722 | `history/` | P5 | offen | tests/test_coach_review.py:228 (direkt/dynamisch unklar); tests/test_coach_review.py:254 (direkt/dynamisch unklar); tests/test_coach_review.py:264 (direkt/dynamisch unklar); tests/test_coach_review.py:291 (direkt/dynamisch unklar); tests/test_coach_review.py:323 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:352 (direkt/dynamisch unklar); tests/test_server.py:3154 (direkt/dynamisch unklar); tests/test_server.py:5570 (direkt/dynamisch unklar); tests/test_server.py:5659 (direkt/dynamisch unklar); tests/test_server.py:5708 (direkt/dynamisch unklar); tests/test_server.py:8632 (direkt/dynamisch unklar); tests/test_server.py:8652 (direkt/dynamisch unklar); tests/test_server.py:8661 (direkt/dynamisch unklar); tests/test_server.py:8664 (direkt/dynamisch unklar) |
| Funktion | `_history_current` | 2733 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_current_record` | 2745 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_target` | 2759 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_history_preview` | 2775 | `history/` | P5 | offen | tests/test_coach_review.py:229 (direkt/dynamisch unklar); tests/test_coach_review.py:255 (direkt/dynamisch unklar); tests/test_coach_review.py:265 (direkt/dynamisch unklar); tests/test_coach_review.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:293 (direkt/dynamisch unklar); tests/test_coach_review.py:324 (direkt/dynamisch unklar); tests/test_server.py:8641 (direkt/dynamisch unklar); tests/test_server.py:8647 (direkt/dynamisch unklar); tests/test_server.py:8653 (direkt/dynamisch unklar) |
| Funktion | `_undo_history_state` | 2813 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_profile_change` | 2833 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_workout_library_change` | 2843 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_competition_change` | 2868 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_undo_state` | 2889 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_unit_undo_date` | 2899 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_existing_planned_unit` | 2908 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_planned_unit_change` | 2934 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_undo_training_plan_change` | 2950 | `history/` | P5 | offen | keine statisch gefunden |
| Globale Bindung | `UNDO_ENTITY_HANDLERS` | 2970 | `history/` | P5 | offen | keine statisch gefunden |
| Funktion | `_apply_change_undo` | 2979 | `history/` | P5 | offen | tests/test_server.py:3161 (direkt/dynamisch unklar); tests/test_server.py:5577 (direkt/dynamisch unklar); tests/test_server.py:5712 (direkt/dynamisch unklar) |
| Funktion | `get_kv` | 2994 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:119 (direkt/dynamisch unklar); tests/test_audit_remediation.py:120 (direkt/dynamisch unklar); tests/test_audit_remediation.py:236 (direkt/dynamisch unklar); tests/test_audit_remediation.py:286 (direkt/dynamisch unklar); tests/test_audit_remediation.py:287 (direkt/dynamisch unklar); tests/test_audit_remediation.py:82 (direkt/dynamisch unklar); tests/test_audit_remediation.py:83 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:323 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:392 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:395 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:458 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:584 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:709 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:710 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:732 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar); tests/test_coach_review.py:44 (direkt/dynamisch unklar); tests/test_coach_review.py:62 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:380 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:383 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:473 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:475 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:490 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:109 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:110 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:147 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:173 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:174 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:206 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:269 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:42 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:47 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:85 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:86 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:87 (direkt/dynamisch unklar); tests/test_provider_review.py:177 (direkt/dynamisch unklar); tests/test_provider_review.py:331 (direkt/dynamisch unklar); tests/test_server.py:1185 (direkt/dynamisch unklar); tests/test_server.py:1205 (direkt/dynamisch unklar); tests/test_server.py:1212 (direkt/dynamisch unklar); tests/test_server.py:1213 (direkt/dynamisch unklar); tests/test_server.py:1258 (direkt/dynamisch unklar); tests/test_server.py:196 (direkt/dynamisch unklar); tests/test_server.py:197 (direkt/dynamisch unklar); tests/test_server.py:2837 (direkt/dynamisch unklar); tests/test_server.py:2838 (direkt/dynamisch unklar); tests/test_server.py:4160 (direkt/dynamisch unklar); tests/test_server.py:4161 (direkt/dynamisch unklar); tests/test_server.py:4444 (direkt/dynamisch unklar); tests/test_server.py:4567 (direkt/dynamisch unklar); tests/test_server.py:6097 (direkt/dynamisch unklar); tests/test_server.py:6109 (direkt/dynamisch unklar); tests/test_server.py:6110 (direkt/dynamisch unklar); tests/test_server.py:6213 (direkt/dynamisch unklar); tests/test_server.py:6232 (direkt/dynamisch unklar); tests/test_server.py:6236 (direkt/dynamisch unklar); tests/test_server.py:6571 (direkt/dynamisch unklar); tests/test_server.py:6590 (direkt/dynamisch unklar); tests/test_server.py:6648 (direkt/dynamisch unklar); tests/test_server.py:7743 (direkt/dynamisch unklar); tests/test_server.py:7761 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:189 (direkt/dynamisch unklar); tests/test_workout_repair.py:196 (direkt/dynamisch unklar); tests/test_workout_repair.py:211 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_PERIOD_DEFAULTS` | 3001 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `ALL_SYNC_DAYS` | 3002 | `sync/` | P6 | offen | tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:68 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar) |
| Globale Bindung | `SYNC_CHUNK_DAYS` | 3003 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `SYNC_EARLIEST_DATE` | 3004 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `EXTERNAL_CALENDAR_WINDOW_DAYS` | 3005 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2640 (direkt/dynamisch unklar) |
| Globale Bindung | `ICAL_MAX_RECURRENCE_COUNT` | 3006 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_MAX_RECURRENCE_PERIODS` | 3007 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_PAUSE_DEFAULT_DAYS` | 3008 | `planning/` | P4 | offen | tests/test_server.py:2703 (direkt/dynamisch unklar); tests/test_server.py:2713 (direkt/dynamisch unklar); tests/test_server.py:2738 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_PAUSE_MAX_DAYS` | 3009 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ILLNESS_CALENDAR_CATEGORY` | 3010 | `planning/` | P4 | offen | tests/test_server.py:2315 (direkt/dynamisch unklar) |
| Globale Bindung | `ILLNESS_EVENT_EXTERNAL_PREFIX` | 3011 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_HISTORY_DAYS` | 3014 | `planning/` | P4 | offen | tests/test_server.py:3645 (direkt/dynamisch unklar) |
| Globale Bindung | `PLANNED_CALENDAR_FUTURE_DAYS` | 3015 | `planning/` | P4 | offen | tests/test_server.py:3646 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_RECENT_ACTIVITIES_PER_SPORT` | 3016 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_PLANNED_EVENT_LIMIT` | 3017 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LOCAL_PLANNED_LIMIT` | 3018 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_LIMIT` | 3019 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_LIBRARY_DESCRIPTION_LIMIT` | 3020 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CONTEXT_TOTAL_CHAR_LIMIT` | 3021 | `coach/` | P7 | offen | tests/test_server.py:5348 (direkt/dynamisch unklar); tests/test_server.py:5359 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_CONTEXT_SECTION_LIMITS` | 3022 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `sync_period` | 3035 | `sync/` | P6 | offen | tests/test_server.py:6034 (direkt/dynamisch unklar); tests/test_server.py:6036 (direkt/dynamisch unklar) |
| Funktion | `set_sync_period` | 3046 | `sync/garmin.py` | P6 | offen | tests/test_server.py:6033 (direkt/dynamisch unklar); tests/test_server.py:6035 (direkt/dynamisch unklar); tests/test_server.py:6061 (direkt/dynamisch unklar) |
| Funktion | `sync_date_windows` | 3058 | `sync/` | P6 | offen | tests/test_server.py:6037 (direkt/dynamisch unklar) |
| Funktion | `provider_sync_cursor` | 3069 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:221 (direkt/dynamisch unklar); tests/test_provider_review.py:222 (direkt/dynamisch unklar); tests/test_provider_review.py:246 (direkt/dynamisch unklar) |
| Funktion | `update_provider_sync_cursor` | 3074 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:209 (direkt/dynamisch unklar); tests/test_provider_review.py:210 (direkt/dynamisch unklar) |
| Funktion | `set_kv` | 3080 | `settings.py` | P1 | offen | tests/test_audit_remediation.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:389 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:393 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:581 (direkt/dynamisch unklar); tests/test_coach_review.py:40 (direkt/dynamisch unklar); tests/test_coach_review.py:41 (direkt/dynamisch unklar); tests/test_coach_review.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:114 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:115 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:133 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:134 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:151 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:167 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:168 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:169 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:203 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:204 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:219 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:243 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:260 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:27 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:28 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:45 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:54 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:55 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:59 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:67 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:92 (direkt/dynamisch unklar); tests/test_provider_review.py:159 (direkt/dynamisch unklar); tests/test_provider_review.py:208 (direkt/dynamisch unklar); tests/test_provider_review.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:325 (direkt/dynamisch unklar); tests/test_server.py:1183 (direkt/dynamisch unklar); tests/test_server.py:1203 (direkt/dynamisch unklar); tests/test_server.py:1209 (direkt/dynamisch unklar); tests/test_server.py:1210 (direkt/dynamisch unklar); tests/test_server.py:1388 (direkt/dynamisch unklar); tests/test_server.py:1389 (direkt/dynamisch unklar); tests/test_server.py:1390 (direkt/dynamisch unklar); tests/test_server.py:1391 (direkt/dynamisch unklar); tests/test_server.py:1483 (direkt/dynamisch unklar); tests/test_server.py:1495 (direkt/dynamisch unklar); tests/test_server.py:1527 (direkt/dynamisch unklar); tests/test_server.py:1635 (direkt/dynamisch unklar); tests/test_server.py:1852 (direkt/dynamisch unklar); tests/test_server.py:1853 (direkt/dynamisch unklar); tests/test_server.py:1854 (direkt/dynamisch unklar); tests/test_server.py:1855 (direkt/dynamisch unklar); tests/test_server.py:1856 (direkt/dynamisch unklar); tests/test_server.py:193 (direkt/dynamisch unklar); tests/test_server.py:194 (direkt/dynamisch unklar); tests/test_server.py:2833 (direkt/dynamisch unklar); tests/test_server.py:2834 (direkt/dynamisch unklar); tests/test_server.py:3258 (direkt/dynamisch unklar); tests/test_server.py:3282 (direkt/dynamisch unklar); tests/test_server.py:3293 (direkt/dynamisch unklar); tests/test_server.py:3341 (direkt/dynamisch unklar); tests/test_server.py:3448 (direkt/dynamisch unklar); tests/test_server.py:3480 (direkt/dynamisch unklar); tests/test_server.py:3499 (direkt/dynamisch unklar); tests/test_server.py:3540 (direkt/dynamisch unklar); tests/test_server.py:3560 (direkt/dynamisch unklar); tests/test_server.py:4210 (direkt/dynamisch unklar); tests/test_server.py:4216 (direkt/dynamisch unklar); tests/test_server.py:4500 (direkt/dynamisch unklar); tests/test_server.py:4524 (direkt/dynamisch unklar); tests/test_server.py:4537 (direkt/dynamisch unklar); tests/test_server.py:4617 (direkt/dynamisch unklar); tests/test_server.py:4639 (direkt/dynamisch unklar); tests/test_server.py:5415 (direkt/dynamisch unklar); tests/test_server.py:5451 (direkt/dynamisch unklar); tests/test_server.py:5946 (direkt/dynamisch unklar); tests/test_server.py:6102 (direkt/dynamisch unklar); tests/test_server.py:6564 (direkt/dynamisch unklar); tests/test_server.py:6581 (direkt/dynamisch unklar); tests/test_server.py:6639 (direkt/dynamisch unklar); tests/test_server.py:6640 (direkt/dynamisch unklar); tests/test_server.py:7722 (direkt/dynamisch unklar); tests/test_server.py:7723 (direkt/dynamisch unklar); tests/test_server.py:7740 (direkt/dynamisch unklar); tests/test_server.py:7755 (direkt/dynamisch unklar); tests/test_server.py:7829 (direkt/dynamisch unklar); tests/test_server.py:7945 (direkt/dynamisch unklar); tests/test_server.py:7955 (direkt/dynamisch unklar); tests/test_server.py:8503 (direkt/dynamisch unklar) |
| Funktion | `_safe_diagnostic_context` | 3088 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_mapping_shape` | 3100 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_sequence_shape` | 3112 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_response_shape` | 3119 | `observability.py` | P1 | offen | tests/test_server.py:8582 (direkt/dynamisch unklar); tests/test_server.py:8587 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_response` | 3136 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_diagnostic_error` | 3141 | `observability.py` | P1 | offen | tests/test_coach_response_failure.py:104 (direkt/dynamisch unklar) |
| Funktion | `_coach_error_metadata` | 3159 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_safe_response_headers` | 3174 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_capture_state` | 3191 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `diagnostic_capture_status` | 3199 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:337 (direkt/dynamisch unklar); tests/test_server.py:7885 (direkt/dynamisch unklar); tests/test_server.py:7907 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_capture_entries` | 3221 | `observability.py` | P1 | offen | tests/test_server.py:7900 (direkt/dynamisch unklar); tests/test_server.py:8269 (direkt/dynamisch unklar) |
| Funktion | `set_diagnostic_capture` | 3231 | `observability.py` | P1 | offen | tests/test_server.py:7886 (direkt/dynamisch unklar); tests/test_server.py:7906 (direkt/dynamisch unklar); tests/test_server.py:8263 (direkt/dynamisch unklar) |
| Funktion | `capture_diagnostic_event` | 3246 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `garmin_snapshot` | 3260 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:217 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:223 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:246 (direkt/dynamisch unklar); tests/test_provider_review.py:216 (direkt/dynamisch unklar); tests/test_provider_review.py:243 (direkt/dynamisch unklar); tests/test_provider_review.py:245 (direkt/dynamisch unklar); tests/test_server.py:5420 (direkt/dynamisch unklar); tests/test_server.py:5422 (direkt/dynamisch unklar); tests/test_server.py:6649 (direkt/dynamisch unklar) |
| Funktion | `garmin_configured` | 3268 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_fixture_path` | 3272 | `sync/garmin.py` | P6 | offen | tests/test_audit_remediation.py:152 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:284 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:121 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:140 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:156 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:211 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:73 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:98 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:238 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4153 (Monkeypatch/getattr/sys.modules) |
| Funktion | `activity_datetime` | 3280 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_kind` | 3292 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_candidates` | 3307 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_interval` | 3317 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_intervals_share_group` | 3328 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_edges` | 3337 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_cycling_event_group` | 3352 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `parallel_cycling_event_groups` | 3366 | `activities/` | P3 | offen | tests/test_server.py:3611 (direkt/dynamisch unklar); tests/test_server.py:3619 (direkt/dynamisch unklar) |
| Funktion | `_garmin_duplicate_measurements` | 3378 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_matches` | 3394 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_activity_duplicates_intervals` | 3409 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7631 (direkt/dynamisch unklar); tests/test_server.py:7642 (direkt/dynamisch unklar); tests/test_server.py:7650 (direkt/dynamisch unklar) |
| Funktion | `filter_garmin_activities` | 3416 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3424 (direkt/dynamisch unklar); tests/test_server.py:7632 (direkt/dynamisch unklar); tests/test_server.py:7658 (direkt/dynamisch unklar) |
| Funktion | `intervals_activity_device_source` | 3423 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_cycling_activities_match` | 3438 | `activities/` | P3 | offen | tests/test_server.py:7697 (direkt/dynamisch unklar) |
| Funktion | `_latest_activity_id` | 3461 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_pairs` | 3474 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_wahoo_garmin_duplicate_view` | 3492 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_wahoo_garmin_duplicate` | 3510 | `sync/garmin.py` | P6 | offen | tests/test_server.py:7673 (direkt/dynamisch unklar); tests/test_server.py:7686 (direkt/dynamisch unklar); tests/test_server.py:7698 (direkt/dynamisch unklar); tests/test_server.py:7710 (direkt/dynamisch unklar) |
| Funktion | `garmin_activity_max_hr` | 3525 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3427 (direkt/dynamisch unklar) |
| Funktion | `merge_garmin_max_hr` | 3540 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CONTEXT_FIELDS` | 3553 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_PERFORMANCE_SOURCE` | 3565 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_key` | 3568 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_numeric` | 3572 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_value` | 3578 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_colon_duration_seconds` | 3583 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_duration_seconds` | 3592 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3335 (direkt/dynamisch unklar); tests/test_server.py:3336 (direkt/dynamisch unklar); tests/test_server.py:3337 (direkt/dynamisch unklar); tests/test_server.py:3338 (direkt/dynamisch unklar) |
| Funktion | `_garmin_race_slot` | 3611 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_time` | 3624 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_weight_kg` | 3628 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_record_date` | 3646 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_weight_records` | 3660 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_records` | 3676 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_metric` | 3682 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_weight_average` | 3690 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_collect_garmin_numeric_values` | 3703 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_numeric` | 3716 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_last_value` | 3723 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_bounded_metric` | 3741 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_pace_seconds` | 3746 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_mapping_nodes` | 3772 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sport_category` | 3782 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_profile_max_hr` | 3791 | `sync/garmin.py` | P6 | offen | tests/test_server.py:3442 (direkt/dynamisch unklar) |
| Funktion | `_garmin_collect_vo2_values` | 3801 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_vo2_metrics` | 3816 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_race_value` | 3825 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_store_direct_race_value` | 3830 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_collect_race_predictions` | 3838 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_race_predictions` | 3852 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_threshold_metrics` | 3863 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_max_hr_samples` | 3882 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_max_hr_samples` | 3893 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_units` | 3910 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_source_keys` | 3934 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_activity_observed_at` | 3943 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_performance_freshness` | 3954 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_metrics` | 3973 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:261 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:294 (direkt/dynamisch unklar); tests/test_provider_review.py:291 (direkt/dynamisch unklar); tests/test_provider_review.py:306 (direkt/dynamisch unklar); tests/test_server.py:3310 (direkt/dynamisch unklar); tests/test_server.py:3367 (direkt/dynamisch unklar); tests/test_server.py:3400 (direkt/dynamisch unklar); tests/test_server.py:3427 (direkt/dynamisch unklar); tests/test_server.py:3434 (direkt/dynamisch unklar); tests/test_server.py:3474 (direkt/dynamisch unklar) |
| Funktion | `measurement_age` | 3995 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `garmin_source_freshness` | 4010 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_metric_freshness` | 4015 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `append_garmin_performance_history` | 4031 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:257 (direkt/dynamisch unklar); tests/test_provider_review.py:265 (direkt/dynamisch unklar); tests/test_provider_review.py:290 (direkt/dynamisch unklar); tests/test_provider_review.py:301 (direkt/dynamisch unklar); tests/test_provider_review.py:305 (direkt/dynamisch unklar) |
| Funktion | `garmin_history_average` | 4049 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_performance_context` | 4068 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_context` | 4097 | `planning/` | P4 | offen | tests/test_server.py:3253 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_RECOVERY_FIELDS` | 4114 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `latest_garmin_record` | 4122 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `compact_garmin_recovery` | 4150 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `load_garmin_fixture` | 4157 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:183 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:195 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:212 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:239 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_normalize_fixture_sleep_dates` | 4181 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_fixture_sleep_dates` | 4190 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_shift_fixture_sleep_dates` | 4207 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `persist_garmin_error` | 4223 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_CAPABILITY_FAILURE_LIMIT` | 4228 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4110 (direkt/dynamisch unklar); tests/test_server.py:4114 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_CAPABILITY_PAUSE_SECONDS` | 4229 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_capability_state` | 4232 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4113 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_allowed` | 4240 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4112 (direkt/dynamisch unklar); tests/test_server.py:4117 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_failure` | 4249 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4111 (direkt/dynamisch unklar) |
| Funktion | `_garmin_capability_success` | 4262 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4116 (direkt/dynamisch unklar) |
| Funktion | `_merge_garmin_records` | 4267 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_record_observation_date` | 4289 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_nested_records` | 4299 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_source_observed_at` | 4303 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4165 (direkt/dynamisch unklar) |
| Globale Bindung | `GARMIN_COLLECTION_SOURCES` | 4318 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_METRIC_SOURCES` | 4319 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_garmin_source` | 4322 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `merge_garmin_sources` | 4341 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:258 (direkt/dynamisch unklar); tests/test_provider_review.py:256 (direkt/dynamisch unklar); tests/test_provider_review.py:264 (direkt/dynamisch unklar); tests/test_provider_review.py:289 (direkt/dynamisch unklar); tests/test_provider_review.py:300 (direkt/dynamisch unklar); tests/test_provider_review.py:304 (direkt/dynamisch unklar) |
| Funktion | `garmin_sleep_observation_date` | 4355 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_sleep_ready_for_checkin` | 4366 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4155 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_garmin_error_entries` | 4377 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_core_error_entries` | 4385 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_set_garmin_error_entries` | 4390 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_timestamp` | 4394 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_interval` | 4412 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_nested_sleep_records` | 4422 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_sleep_bounds` | 4426 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4141 (direkt/dynamisch unklar) |
| Funktion | `_garmin_body_battery_sample` | 4446 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_body_battery_samples` | 4457 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_record` | 4475 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:221 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:236 (direkt/dynamisch unklar); tests/test_server.py:4120 (direkt/dynamisch unklar) |
| Funktion | `_garmin_morning_body_battery` | 4512 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_saved_daily_history` | 4517 | `sync/garmin.py` | P6 | offen | tests/test_server.py:4209 (direkt/dynamisch unklar) |
| Funktion | `_morning_body_battery_cached_result` | 4525 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_persist_morning_body_battery` | 4538 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_morning_body_battery_remote_payload` | 4562 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_sync_morning_body_battery_locked` | 4591 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin_morning_body_battery` | 4615 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:213 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:215 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:222 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:224 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_server.py:4201 (direkt/dynamisch unklar); tests/test_server.py:4202 (direkt/dynamisch unklar) |
| Funktion | `refresh_morning_body_battery` | 4628 | `performance/` | P3 | offen | tests/test_diagnostic_followups.py:101 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:124 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:142 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:159 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:76 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_persist_garmin_sync_payload` | 4640 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_fixture_locked` | 4670 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_remote_collection_options` | 4699 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_garmin_remote_locked` | 4706 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_garmin_sync` | 4765 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_garmin` | 4788 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:122 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:141 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:157 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:249 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:39 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:74 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:99 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:215 (direkt/dynamisch unklar); tests/test_provider_review.py:241 (direkt/dynamisch unklar); tests/test_server.py:231 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4154 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8577 (direkt/dynamisch unklar) |
| Funktion | `garmin_collection_complete` | 4830 | `sync/garmin.py` | P6 | offen | tests/test_provider_review.py:358 (direkt/dynamisch unklar) |
| Funktion | `annotate_garmin_activity_matches` | 4837 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_public_state` | 4848 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:266 (direkt/dynamisch unklar); tests/test_provider_review.py:244 (direkt/dynamisch unklar); tests/test_provider_review.py:278 (direkt/dynamisch unklar); tests/test_server.py:4208 (direkt/dynamisch unklar); tests/test_server.py:4220 (direkt/dynamisch unklar); tests/test_server.py:7830 (direkt/dynamisch unklar); tests/test_server.py:8578 (direkt/dynamisch unklar) |
| Funktion | `garmin_coach_context` | 4888 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:3273 (direkt/dynamisch unklar); tests/test_server.py:3287 (direkt/dynamisch unklar) |
| Funktion | `add_message` | 4911 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:158 (direkt/dynamisch unklar); tests/test_coach_attachments.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:555 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:836 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:544 (direkt/dynamisch unklar); tests/test_server.py:1688 (direkt/dynamisch unklar); tests/test_server.py:1720 (direkt/dynamisch unklar); tests/test_server.py:4521 (direkt/dynamisch unklar); tests/test_server.py:4522 (direkt/dynamisch unklar); tests/test_server.py:4523 (direkt/dynamisch unklar); tests/test_server.py:5238 (direkt/dynamisch unklar) |
| Funktion | `list_messages` | 4918 | `coach/conversation.py` | P7 | offen | tests/test_coach_attachments.py:153 (direkt/dynamisch unklar); tests/test_coach_attachments.py:166 (direkt/dynamisch unklar); tests/test_coach_attachments.py:173 (direkt/dynamisch unklar); tests/test_coach_attachments.py:180 (direkt/dynamisch unklar); tests/test_coach_attachments.py:267 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:305 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:379 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:590 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:72 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:743 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:204 (direkt/dynamisch unklar) |
| Globale Bindung | `DEFAULT_TIMEZONE` | 4925 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `timezone_name` | 4928 | `config.py` | P1 | offen | keine statisch gefunden |
| Funktion | `normalize_profile` | 4940 | `athlete/` | P3 | offen | tests/test_server.py:1134 (direkt/dynamisch unklar); tests/test_server.py:1597 (direkt/dynamisch unklar) |
| Funktion | `get_profile` | 4949 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:122 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:123 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:124 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:132 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:136 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:144 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:159 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:160 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:168 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:169 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:173 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:106 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:129 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:130 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:238 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:247 (direkt/dynamisch unklar); tests/test_server.py:1607 (direkt/dynamisch unklar); tests/test_server.py:6755 (direkt/dynamisch unklar); tests/test_server.py:8645 (direkt/dynamisch unklar) |
| Funktion | `save_profile` | 4958 | `athlete/` | P3 | offen | tests/support.py:152 (direkt/dynamisch unklar); tests/test_audit_remediation.py:143 (direkt/dynamisch unklar); tests/test_audit_remediation.py:75 (direkt/dynamisch unklar); tests/test_audit_remediation.py:78 (direkt/dynamisch unklar); tests/test_audit_remediation.py:86 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:113 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:131 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:147 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:119 (direkt/dynamisch unklar); tests/test_server.py:1157 (direkt/dynamisch unklar); tests/test_server.py:1166 (direkt/dynamisch unklar); tests/test_server.py:1182 (direkt/dynamisch unklar); tests/test_server.py:1184 (direkt/dynamisch unklar); tests/test_server.py:1188 (direkt/dynamisch unklar); tests/test_server.py:1202 (direkt/dynamisch unklar); tests/test_server.py:1204 (direkt/dynamisch unklar); tests/test_server.py:1208 (direkt/dynamisch unklar); tests/test_server.py:1216 (direkt/dynamisch unklar); tests/test_server.py:1223 (direkt/dynamisch unklar); tests/test_server.py:1242 (direkt/dynamisch unklar); tests/test_server.py:146 (direkt/dynamisch unklar); tests/test_server.py:1509 (direkt/dynamisch unklar); tests/test_server.py:1526 (direkt/dynamisch unklar); tests/test_server.py:1569 (direkt/dynamisch unklar); tests/test_server.py:1590 (direkt/dynamisch unklar); tests/test_server.py:1592 (direkt/dynamisch unklar); tests/test_server.py:1603 (direkt/dynamisch unklar); tests/test_server.py:2500 (direkt/dynamisch unklar); tests/test_server.py:6708 (direkt/dynamisch unklar); tests/test_server.py:6736 (direkt/dynamisch unklar); tests/test_server.py:7305 (direkt/dynamisch unklar); tests/test_server.py:7450 (direkt/dynamisch unklar); tests/test_server.py:8630 (direkt/dynamisch unklar); tests/test_server.py:8631 (direkt/dynamisch unklar); tests/test_server.py:8660 (direkt/dynamisch unklar); tests/test_server.py:8677 (direkt/dynamisch unklar) |
| Funktion | `_invalidate_weather_cache_if_location_changed` | 4972 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_TEXT_LIMITS` | 4982 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `CHECKIN_SCORE_FIELDS` | 4989 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_score` | 4992 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_minutes` | 5004 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_checkin` | 5016 | `athlete/` | P3 | offen | tests/test_server.py:1614 (direkt/dynamisch unklar) |
| Funktion | `list_checkins` | 5036 | `athlete/` | P3 | offen | tests/test_coach_tool_coverage.py:240 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:246 (direkt/dynamisch unklar); tests/test_server.py:2712 (direkt/dynamisch unklar) |
| Funktion | `save_checkin` | 5041 | `athlete/` | P3 | offen | tests/test_audit_remediation.py:167 (direkt/dynamisch unklar); tests/test_coach_review.py:278 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:319 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:332 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:531 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:572 (direkt/dynamisch unklar); tests/test_server.py:1577 (direkt/dynamisch unklar); tests/test_server.py:1586 (direkt/dynamisch unklar); tests/test_server.py:1616 (direkt/dynamisch unklar); tests/test_server.py:1620 (direkt/dynamisch unklar); tests/test_server.py:1634 (direkt/dynamisch unklar); tests/test_server.py:1665 (direkt/dynamisch unklar); tests/test_server.py:2701 (direkt/dynamisch unklar); tests/test_server.py:2722 (direkt/dynamisch unklar); tests/test_server.py:2748 (direkt/dynamisch unklar); tests/test_server.py:2767 (direkt/dynamisch unklar) |
| Funktion | `save_coach_checkin` | 5049 | `athlete/` | P3 | offen | tests/test_coach_dialogue.py:755 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:755 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:824 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:892 (direkt/dynamisch unklar) |
| Funktion | `local_feedback_context` | 5072 | `athlete/` | P3 | offen | tests/test_server.py:1584 (direkt/dynamisch unklar); tests/test_workout_repair.py:282 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:378 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `ACTIVITY_FEEDBACK_TEXT_LIMITS` | 5082 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `normalize_activity_feedback` | 5089 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `list_activity_feedback` | 5103 | `activities/` | P3 | offen | tests/test_coach_tool_coverage.py:243 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:280 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:281 (direkt/dynamisch unklar); tests/test_server.py:2362 (direkt/dynamisch unklar) |
| Funktion | `save_activity_feedback` | 5108 | `activities/` | P3 | offen | tests/test_server.py:2359 (direkt/dynamisch unklar); tests/test_server.py:2361 (direkt/dynamisch unklar) |
| Funktion | `save_coach_activity_feedback` | 5120 | `activities/` | P3 | offen | tests/test_diagnostic_followups.py:329 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2329 (direkt/dynamisch unklar); tests/test_server.py:2342 (direkt/dynamisch unklar); tests/test_server.py:2352 (direkt/dynamisch unklar) |
| Funktion | `activity_feedback_context` | 5137 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activities_with_feedback` | 5144 | `athlete/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `COMPETITION_TEXT_LIMITS` | 5158 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_start` | 5170 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_moving_time` | 5192 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_distance` | 5204 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_target` | 5218 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_category_and_priority` | 5224 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3209 (direkt/dynamisch unklar); tests/test_server.py:3213 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_id` | 5234 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3211 (direkt/dynamisch unklar) |
| Funktion | `competition_normalized_text_fields` | 5241 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_competition` | 5254 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3195 (direkt/dynamisch unklar) |
| Funktion | `list_competitions` | 5275 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:44 (direkt/dynamisch unklar); tests/test_audit_remediation.py:55 (direkt/dynamisch unklar); tests/test_audit_remediation.py:57 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:600 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:604 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:609 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:613 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:252 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:254 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:259 (direkt/dynamisch unklar); tests/test_server.py:643 (direkt/dynamisch unklar); tests/test_server.py:6458 (direkt/dynamisch unklar); tests/test_server.py:653 (direkt/dynamisch unklar); tests/test_server.py:6540 (direkt/dynamisch unklar); tests/test_server.py:6775 (direkt/dynamisch unklar); tests/test_server.py:6829 (direkt/dynamisch unklar); tests/test_server.py:6863 (direkt/dynamisch unklar); tests/test_server.py:6900 (direkt/dynamisch unklar); tests/test_server.py:6947 (direkt/dynamisch unklar); tests/test_server.py:6984 (direkt/dynamisch unklar); tests/test_server.py:6992 (direkt/dynamisch unklar); tests/test_server.py:7019 (direkt/dynamisch unklar); tests/test_server.py:7047 (direkt/dynamisch unklar) |
| Funktion | `_resolve_calendar_addresses` | 5280 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2565 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_calendar_feed_request` | 5295 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_remaining` | 5318 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_fetch_calendar_address` | 5325 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_fetch_failure_log` | 5360 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `fetch_calendar_feed` | 5375 | `providers/calendar.py` | P2 | offen | tests/test_server.py:2535 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2570 (direkt/dynamisch unklar); tests/test_server.py:2583 (direkt/dynamisch unklar); tests/test_server.py:2620 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2649 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2664 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_ical_temporal_value` | 5430 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_TRAINING_MARKER` | 5460 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_NO_INTENSITY_MARKER` | 5461 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_SHORT_ONLY_MARKER` | 5462 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_TRAINING_MARKERS` | 5463 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_description_contains` | 5466 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_impact` | 5470 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_training_relevant` | 5475 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_no_intensity` | 5481 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `ical_short_only` | 5486 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `ICAL_DAY_NUMBERS` | 5491 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_values` | 5494 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_integer` | 5509 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_byday` | 5526 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_bydays` | 5540 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rule_until` | 5557 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_rrule` | 5566 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_shift_local` | 5606 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekday_ordinal` | 5610 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_byday` | 5614 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_matches_date_filters` | 5630 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_dates` | 5643 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_apply_bysetpos` | 5657 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_recurrence_start` | 5669 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_record` | 5674 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_daily_recurrence_starts` | 5693 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_candidate_starts` | 5715 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_weekly_recurrence_starts` | 5727 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_period` | 5753 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_candidates` | 5763 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_marker` | 5768 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_first_period_index` | 5772 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_period_recurrence_starts` | 5781 | `providers/calendar.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_recurrence_starts` | 5806 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_duration` | 5816 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_occurrence_overlaps_window` | 5827 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rule_starts` | 5832 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_rdates` | 5845 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_event_instances` | 5852 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_calendar_window` | 5869 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_property_parameters` | 5877 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_dates` | 5888 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_temporal_property` | 5903 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_recurrence_id` | 5913 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_store_event_property` | 5920 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_append_event` | 5941 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_skip_nested_event_line` | 5950 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_parsed_events` | 5958 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_exception_starts` | 5982 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_add_event_instances` | 5990 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_ical_expanded_events` | 6004 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `parse_ical_calendar` | 6017 | `providers/` | P2 | offen | tests/test_audit_remediation.py:159 (direkt/dynamisch unklar); tests/test_audit_remediation.py:163 (direkt/dynamisch unklar); tests/test_server.py:2393 (direkt/dynamisch unklar); tests/test_server.py:2424 (direkt/dynamisch unklar); tests/test_server.py:2452 (direkt/dynamisch unklar); tests/test_server.py:2458 (direkt/dynamisch unklar); tests/test_server.py:2465 (direkt/dynamisch unklar); tests/test_server.py:2472 (direkt/dynamisch unklar); tests/test_server.py:2477 (direkt/dynamisch unklar); tests/test_server.py:2481 (direkt/dynamisch unklar); tests/test_server.py:2492 (direkt/dynamisch unklar); tests/test_server.py:2507 (direkt/dynamisch unklar); tests/test_server.py:2520 (direkt/dynamisch unklar); tests/test_server.py:2524 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_url` | 6023 | `providers/` | P2 | offen | tests/test_server.py:2543 (direkt/dynamisch unklar); tests/test_server.py:2552 (direkt/dynamisch unklar); tests/test_server.py:2671 (direkt/dynamisch unklar); tests/test_server.py:2673 (direkt/dynamisch unklar); tests/test_server.py:7821 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_external_calendar_events` | 6039 | `providers/` | P2 | offen | tests/test_server.py:2538 (direkt/dynamisch unklar); tests/test_server.py:2594 (direkt/dynamisch unklar); tests/test_server.py:2635 (direkt/dynamisch unklar); tests/test_server.py:2654 (direkt/dynamisch unklar); tests/test_server.py:2667 (direkt/dynamisch unklar); tests/test_server.py:3115 (direkt/dynamisch unklar); tests/test_server.py:3117 (direkt/dynamisch unklar); tests/test_workout_repair.py:284 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:380 (Monkeypatch/getattr/sys.modules) |
| Funktion | `external_calendar_state` | 6050 | `providers/` | P2 | offen | tests/test_server.py:2630 (direkt/dynamisch unklar) |
| Funktion | `sync_external_calendar` | 6065 | `sync/` | P6 | offen | tests/test_server.py:2537 (direkt/dynamisch unklar); tests/test_server.py:2625 (direkt/dynamisch unklar); tests/test_server.py:2650 (direkt/dynamisch unklar); tests/test_server.py:2666 (direkt/dynamisch unklar); tests/test_server.py:7825 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_event_dates` | 6111 | `providers/` | P2 | offen | tests/test_audit_remediation.py:162 (direkt/dynamisch unklar) |
| Funktion | `external_calendar_events_for_date` | 6126 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_CHECKIN_FIELDS` | 6130 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_WEATHER_FIELDS` | 6134 | `weather/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNING_CONTEXT_APPOINTMENT_FIELDS` | 6140 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_context_date` | 6146 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_dated_garmin_recovery_records` | 6154 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_metric` | 6172 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_recovery_average` | 6189 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `GARMIN_DAILY_HEALTH_FIELDS` | 6216 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_garmin_daily_health_by_date` | 6223 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `garmin_daily_health_metrics` | 6237 | `sync/garmin.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_planning_recovery_value` | 6269 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_sleep_hours` | 6278 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_intervals_planning_recovery` | 6289 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery_record` | 6308 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_garmin_planning_recovery` | 6320 | `sync/competitions.py` | P6 | offen | keine statisch gefunden |
| Funktion | `_add_morning_battery_recovery` | 6326 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planning_recovery_by_date` | 6339 | `performance/` | P3 | offen | tests/test_server.py:4211 (direkt/dynamisch unklar) |
| Funktion | `_planning_context_day` | 6351 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_planned_context` | 6355 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_add_checkin_context` | 6365 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_calendar_context` | 6374 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_add_feedback_context` | 6384 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_weather_context` | 6395 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_add_planning_context_signals` | 6404 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_finalize_planning_context` | 6424 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `daily_planning_context` | 6438 | `planning/competitions.py` | P4 | offen | tests/test_server.py:1646 (direkt/dynamisch unklar); tests/test_server.py:3117 (direkt/dynamisch unklar) |
| Funktion | `list_public_calendar_sources` | 6462 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `list_public_event_candidates` | 6471 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `public_calendar_state` | 6483 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `_validated_athlete_context` | 6496 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_removed_competition_tombstones` | 6511 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_profile` | 6517 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_save_athlete_competition` | 6528 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_removed_athlete_competitions` | 6536 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_athlete_context` | 6547 | `coach/context.py` | P7 | offen | tests/test_server.py:1211 (direkt/dynamisch unklar); tests/test_server.py:3605 (direkt/dynamisch unklar); tests/test_server.py:6330 (direkt/dynamisch unklar); tests/test_server.py:6358 (direkt/dynamisch unklar); tests/test_server.py:6402 (direkt/dynamisch unklar); tests/test_server.py:6420 (direkt/dynamisch unklar); tests/test_server.py:6429 (direkt/dynamisch unklar); tests/test_server.py:6493 (direkt/dynamisch unklar); tests/test_server.py:6716 (direkt/dynamisch unklar); tests/test_server.py:6783 (direkt/dynamisch unklar); tests/test_server.py:6833 (direkt/dynamisch unklar); tests/test_server.py:6869 (direkt/dynamisch unklar); tests/test_server.py:6908 (direkt/dynamisch unklar); tests/test_server.py:6991 (direkt/dynamisch unklar); tests/test_server.py:6997 (direkt/dynamisch unklar); tests/test_server.py:7023 (direkt/dynamisch unklar); tests/test_server.py:7042 (direkt/dynamisch unklar) |
| Funktion | `coach_competition_payload` | 6564 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalise_coach_competition_id` | 6586 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_REQUIRED_FIELDS` | 6598 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_COMPETITION_OPTIONAL_FIELDS` | 6599 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_coach_competition` | 6604 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_merge_coach_competition_update` | 6614 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_coach_competition` | 6632 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_insert_coach_competition` | 6644 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_coach_competition` | 6657 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_normalized_coach_competition` | 6669 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `save_coach_competition` | 6688 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:28 (direkt/dynamisch unklar); tests/test_audit_remediation.py:38 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:597 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:608 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:139 (direkt/dynamisch unklar); tests/test_server.py:1070 (direkt/dynamisch unklar); tests/test_server.py:415 (direkt/dynamisch unklar); tests/test_server.py:633 (direkt/dynamisch unklar); tests/test_server.py:6414 (direkt/dynamisch unklar); tests/test_server.py:6440 (direkt/dynamisch unklar); tests/test_server.py:6752 (direkt/dynamisch unklar); tests/test_server.py:6757 (direkt/dynamisch unklar); tests/test_server.py:6791 (direkt/dynamisch unklar); tests/test_server.py:6932 (direkt/dynamisch unklar) |
| Funktion | `delete_coach_competition` | 6696 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:50 (direkt/dynamisch unklar); tests/test_audit_remediation.py:62 (direkt/dynamisch unklar); tests/test_server.py:6772 (direkt/dynamisch unklar) |
| Globale Bindung | `COMPETITION_SPORTS` | 6726 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_SPORTS` | 6747 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `INTERVALS_WORKOUT_TYPES` | 6770 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar) |
| Globale Bindung | `INTERVALS_ENDURANCE_WORKOUT_TYPES` | 6785 | `planning/` | P4 | offen | tests/test_workout_text.py:147 (direkt/dynamisch unklar); tests/test_workout_text.py:160 (direkt/dynamisch unklar) |
| Funktion | `supported_competition_sport` | 6795 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `intervals_competition_sport` | 6801 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3188 (direkt/dynamisch unklar); tests/test_server.py:3189 (direkt/dynamisch unklar); tests/test_server.py:3190 (direkt/dynamisch unklar); tests/test_server.py:3191 (direkt/dynamisch unklar); tests/test_server.py:3192 (direkt/dynamisch unklar) |
| Funktion | `intervals_workout_sport` | 6806 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_external_id` | 6821 | `planning/competitions.py` | P4 | offen | tests/test_audit_remediation.py:29 (direkt/dynamisch unklar); tests/test_server.py:6438 (direkt/dynamisch unklar); tests/test_server.py:6770 (direkt/dynamisch unklar); tests/test_server.py:6785 (direkt/dynamisch unklar); tests/test_server.py:6862 (direkt/dynamisch unklar) |
| Funktion | `competition_event_optional_payload` | 6825 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3217 (direkt/dynamisch unklar) |
| Funktion | `competition_event_payload` | 6845 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3205 (direkt/dynamisch unklar); tests/test_server.py:3206 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_date` | 6861 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `remote_competition_moving_time` | 6871 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3243 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_distance` | 6878 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3244 (direkt/dynamisch unklar); tests/test_server.py:3245 (direkt/dynamisch unklar) |
| Funktion | `remote_competition_data` | 6884 | `planning/competitions.py` | P4 | offen | tests/test_server.py:3229 (direkt/dynamisch unklar) |
| Funktion | `competition_conflict_payload` | 6912 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `is_remote_competition_event` | 6918 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `competition_sync_key` | 6927 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `resolve_competition_conflict` | 6937 | `planning/competitions.py` | P4 | offen | tests/test_server.py:6927 (direkt/dynamisch unklar); tests/test_server.py:6944 (direkt/dynamisch unklar) |
| Funktion | `_competition_remote_indexes` | 6977 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_match` | 6991 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_conflict_action` | 7004 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_dirty_row_action` | 7030 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_delete_identifiers` | 7056 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_signature` | 7064 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_plan_summary` | 7072 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_plan` | 7076 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_remote_events` | 7114 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_records` | 7122 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_competition_tombstones` | 7129 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_indexes` | 7144 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_competition_sync_remote_match` | 7156 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_competition_sync_conflict` | 7168 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_missing_competition_conflict` | 7175 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_dirty_competition` | 7179 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_synced_competition` | 7212 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_synchronize_existing_competitions` | 7235 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_remote_competition_local_id` | 7254 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_suppressed_competition_identifiers` | 7271 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `_import_remote_competitions` | 7279 | `planning/competitions.py` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_competitions` | 7309 | `sync/` | P6 | offen | tests/test_audit_remediation.py:43 (direkt/dynamisch unklar); tests/test_audit_remediation.py:54 (direkt/dynamisch unklar); tests/test_audit_remediation.py:56 (direkt/dynamisch unklar); tests/test_audit_remediation.py:70 (direkt/dynamisch unklar); tests/test_server.py:6413 (direkt/dynamisch unklar); tests/test_server.py:6421 (direkt/dynamisch unklar); tests/test_server.py:6457 (direkt/dynamisch unklar); tests/test_server.py:6627 (direkt/dynamisch unklar); tests/test_server.py:6824 (direkt/dynamisch unklar); tests/test_server.py:6856 (direkt/dynamisch unklar); tests/test_server.py:6857 (direkt/dynamisch unklar); tests/test_server.py:6894 (direkt/dynamisch unklar); tests/test_server.py:6926 (direkt/dynamisch unklar); tests/test_server.py:6942 (direkt/dynamisch unklar); tests/test_server.py:6945 (direkt/dynamisch unklar); tests/test_server.py:6981 (direkt/dynamisch unklar); tests/test_server.py:7014 (direkt/dynamisch unklar); tests/test_server.py:7041 (direkt/dynamisch unklar); tests/test_server.py:7043 (direkt/dynamisch unklar) |
| Globale Bindung | `OPENAI_RATE_LIMIT_HEADERS` | 7365 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_STATUS_KEY` | 7374 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:106 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:93 (direkt/dynamisch unklar) |
| Globale Bindung | `GEMINI_STATUS_KEY` | 7375 | `providers/` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `OPENAI_MAX_RETRY_DELAY_SECONDS` | 7376 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:77 (direkt/dynamisch unklar) |
| Funktion | `_retry_after_seconds` | 7379 | `providers/http.py` | P2 | offen | tests/test_server.py:8148 (direkt/dynamisch unklar) |
| Funktion | `_safe_openai_error_token` | 7393 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_diagnostic_details` | 7401 | `observability.py` | P1 | offen | tests/test_server.py:8211 (direkt/dynamisch unklar); tests/test_server.py:8234 (direkt/dynamisch unklar) |
| Funktion | `_openai_error_tokens` | 7424 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_invalid_input_state` | 7434 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_conversation_error` | 7442 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_billing_error` | 7453 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_error_reason` | 7464 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_error_details` | 7484 | `providers/` | P2 | offen | tests/test_server.py:8136 (direkt/dynamisch unklar); tests/test_server.py:8141 (direkt/dynamisch unklar); tests/test_server.py:8209 (direkt/dynamisch unklar); tests/test_server.py:8232 (direkt/dynamisch unklar); tests/test_server.py:8249 (direkt/dynamisch unklar) |
| Funktion | `safe_openai_log_reason` | 7500 | `observability.py` | P1 | offen | tests/test_server.py:8180 (direkt/dynamisch unklar); tests/test_server.py:8181 (direkt/dynamisch unklar) |
| Funktion | `_provider_error_payload` | 7523 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_tokens` | 7532 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_error_reason` | 7540 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_error_details` | 7554 | `providers/` | P2 | offen | tests/test_server.py:4647 (direkt/dynamisch unklar); tests/test_server.py:4649 (direkt/dynamisch unklar); tests/test_server.py:4650 (direkt/dynamisch unklar) |
| Funktion | `record_openai_status` | 7560 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_success` | 7575 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_rate_limits` | 7585 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_body` | 7597 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_provider_error_text` | 7605 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_intervals_error_detail` | 7613 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_safe_interval_error_detail` | 7625 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `upstream_http_error_message` | 7630 | `coach/context.py` | P7 | offen | tests/test_server.py:7939 (direkt/dynamisch unklar) |
| Funktion | `_read_http_error_body` | 7640 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_urlopen_interruptibly` | 7651 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_body` | 7678 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_request_parts` | 7686 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_http_request_started` | 7720 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_http_response` | 7733 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_http_success_result` | 7748 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_capture_http_failure` | 7789 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_error` | 7808 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_network_error` | 7858 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_app_error` | 7893 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_http_client_error` | 7898 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Funktion | `http_json` | 7926 | `providers/http.py` | P2 | offen | e2e/fixture_runtime.py:28 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:37 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:73 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1734 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4369 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4438 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4562 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4577 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4667 (direkt/dynamisch unklar); tests/test_server.py:4708 (direkt/dynamisch unklar); tests/test_server.py:4745 (direkt/dynamisch unklar); tests/test_server.py:4778 (direkt/dynamisch unklar); tests/test_server.py:4838 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5468 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7451 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7845 (direkt/dynamisch unklar); tests/test_server.py:7863 (direkt/dynamisch unklar); tests/test_server.py:7881 (direkt/dynamisch unklar); tests/test_server.py:7915 (direkt/dynamisch unklar); tests/test_server.py:7932 (direkt/dynamisch unklar); tests/test_server.py:8056 (direkt/dynamisch unklar); tests/test_server.py:8092 (direkt/dynamisch unklar); tests/test_server.py:8120 (direkt/dynamisch unklar); tests/test_server.py:8161 (direkt/dynamisch unklar); tests/test_server.py:8505 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:21 (Monkeypatch/getattr/sys.modules) |
| Funktion | `is_outdoor_activity` | 7961 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `is_cycling_activity` | 7973 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_number` | 7982 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_icon` | 7990 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_array_value` | 7994 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_peak_time` | 8000 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_sun_time` | 8012 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_row` | 8017 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_daily_summary` | 8043 | `weather/` | P3 | offen | tests/test_server.py:1145 (direkt/dynamisch unklar); tests/test_server.py:1151 (direkt/dynamisch unklar) |
| Funktion | `_weather_hourly_rows` | 8053 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_training_windows` | 8077 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_summary` | 8092 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_window_score` | 8111 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_interval_is_usable` | 8126 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_candidate_windows` | 8140 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendation` | 8161 | `weather/` | P3 | offen | tests/test_server.py:7494 (direkt/dynamisch unklar); tests/test_server.py:7501 (direkt/dynamisch unklar) |
| Funktion | `_overlay_weather_values` | 8208 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_merge_weather_forecasts` | 8224 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_geocoded_location` | 8234 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_params` | 8255 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_forecast_is_complete` | 8275 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_fetch_icon_d2` | 8279 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_fetch_weather_forecast` | 8302 | `weather/` | P3 | offen | tests/test_audit_remediation.py:105 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:80 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1163 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1189 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1217 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1231 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1250 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1517 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1533 (Monkeypatch/getattr/sys.modules) |
| Klasse | `_WeatherCacheState` | 8314 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_cache_state` | 8325 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_retry_wait` | 8352 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_record_weather_refresh_failure` | 8360 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_refresh_weather_state` | 8373 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_recommendations` | 8409 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_unavailable_state` | 8428 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_ready_state` | 8434 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `weather_state` | 8456 | `weather/` | P3 | offen | tests/test_audit_remediation.py:145 (direkt/dynamisch unklar); tests/test_audit_remediation.py:146 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:81 (direkt/dynamisch unklar); tests/test_server.py:1164 (direkt/dynamisch unklar); tests/test_server.py:1165 (direkt/dynamisch unklar); tests/test_server.py:1251 (direkt/dynamisch unklar); tests/test_server.py:1252 (direkt/dynamisch unklar); tests/test_server.py:1253 (direkt/dynamisch unklar); tests/test_server.py:1543 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1560 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2981 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7456 (direkt/dynamisch unklar) |
| Funktion | `_remember_calendar_weather` | 8474 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_weather_state` | 8492 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_duration_minutes` | 8507 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_forecast` | 8514 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_precipitation` | 8530 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_details` | 8558 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `_weather_adaptive_reason` | 8571 | `weather/` | P3 | offen | keine statisch gefunden |
| Funktion | `sync_weather` | 8591 | `sync/` | P6 | offen | tests/test_audit_remediation.py:147 (direkt/dynamisch unklar); tests/test_server.py:1232 (direkt/dynamisch unklar); tests/test_server.py:1233 (direkt/dynamisch unklar); tests/test_server.py:1234 (direkt/dynamisch unklar); tests/test_server.py:1520 (direkt/dynamisch unklar) |
| Funktion | `add_weather_to_planned` | 8607 | `planning/` | P4 | offen | tests/test_server.py:7468 (direkt/dynamisch unklar) |
| Funktion | `is_planned_workout_event` | 8619 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_date` | 8632 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activity_metric` | 8637 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_workout_duration` | 8642 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_load` | 8646 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `CALENDAR_ACTIVITY_FIELDS` | 8650 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_payload` | 8658 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `calendar_activity_identity` | 8674 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_rows` | 8693 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_activities_by_paired_event_id` | 8697 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_paired_activity_match` | 8706 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_unpaired_activity_match` | 8718 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `match_planned_workouts` | 8739 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_basis` | 8766 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_compliance_percentage` | 8781 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_compliance` | 8794 | `planning/` | P4 | offen | tests/test_server.py:2928 (direkt/dynamisch unklar); tests/test_server.py:2930 (direkt/dynamisch unklar) |
| Funktion | `_planning_compliance_rows` | 8832 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_values` | 8853 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_weekly_compliance_row` | 8873 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_compliance_state` | 8891 | `planning/` | P4 | offen | tests/test_server.py:2893 (direkt/dynamisch unklar); tests/test_server.py:2953 (direkt/dynamisch unklar); tests/test_server.py:2992 (direkt/dynamisch unklar) |
| Funktion | `training_calendar_items` | 8901 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:2954 (direkt/dynamisch unklar) |
| Funktion | `deduplicate_api_records` | 8925 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `selected` | 8945 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_sport_settings` | 8951 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_wellness_sport_info` | 8974 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_snapshot` | 8984 | `planning/` | P4 | offen | tests/test_server.py:2853 (direkt/dynamisch unklar); tests/test_server.py:3570 (direkt/dynamisch unklar); tests/test_server.py:6699 (direkt/dynamisch unklar); tests/test_server.py:7067 (direkt/dynamisch unklar); tests/test_server.py:7096 (direkt/dynamisch unklar); tests/test_server.py:7225 (direkt/dynamisch unklar); tests/test_server.py:7249 (direkt/dynamisch unklar); tests/test_server.py:7270 (direkt/dynamisch unklar); tests/test_server.py:7286 (direkt/dynamisch unklar) |
| Globale Bindung | `WORKOUT_STEP_QUANTITY` | 9022 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_QUANTITY_UNITS` | 9023 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `WORKOUT_STEP_TIME_UNITS` | 9028 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_step_amounts` | 9031 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_ambiguous_workout_step` | 9040 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_is_composite_duration` | 9044 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_endurance_workout_steps` | 9053 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_workout_duration` | 9078 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_workout_duration_match` | 9085 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `validate_workout_description` | 9096 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:145 (direkt/dynamisch unklar); tests/test_server.py:3800 (direkt/dynamisch unklar); tests/test_server.py:3817 (direkt/dynamisch unklar); tests/test_workout_repair.py:248 (direkt/dynamisch unklar); tests/test_workout_text.py:114 (direkt/dynamisch unklar); tests/test_workout_text.py:121 (direkt/dynamisch unklar); tests/test_workout_text.py:132 (direkt/dynamisch unklar); tests/test_workout_text.py:144 (direkt/dynamisch unklar); tests/test_workout_text.py:26 (direkt/dynamisch unklar); tests/test_workout_text.py:93 (direkt/dynamisch unklar) |
| Funktion | `workout_event_payload` | 9110 | `planning/` | P4 | offen | tests/test_coach_review.py:155 (direkt/dynamisch unklar); tests/test_server.py:3082 (direkt/dynamisch unklar); tests/test_server.py:3174 (direkt/dynamisch unklar); tests/test_server.py:3250 (direkt/dynamisch unklar); tests/test_server.py:3836 (direkt/dynamisch unklar); tests/test_workout_text.py:110 (direkt/dynamisch unklar); tests/test_workout_text.py:115 (direkt/dynamisch unklar); tests/test_workout_text.py:122 (direkt/dynamisch unklar); tests/test_workout_text.py:152 (direkt/dynamisch unklar); tests/test_workout_text.py:42 (direkt/dynamisch unklar); tests/test_workout_text.py:53 (direkt/dynamisch unklar); tests/test_workout_text.py:79 (direkt/dynamisch unklar) |
| Funktion | `validate_intervals_workout_result` | 9133 | `planning/` | P4 | offen | tests/test_workout_repair.py:249 (direkt/dynamisch unklar); tests/test_workout_text.py:155 (direkt/dynamisch unklar); tests/test_workout_text.py:157 (direkt/dynamisch unklar); tests/test_workout_text.py:167 (direkt/dynamisch unklar); tests/test_workout_text.py:187 (direkt/dynamisch unklar); tests/test_workout_text.py:201 (direkt/dynamisch unklar); tests/test_workout_text.py:212 (direkt/dynamisch unklar); tests/test_workout_text.py:215 (direkt/dynamisch unklar); tests/test_workout_text.py:85 (direkt/dynamisch unklar); tests/test_workout_text.py:89 (direkt/dynamisch unklar) |
| Funktion | `normalize_workout` | 9146 | `planning/` | P4 | offen | tests/test_coach_language_recovery.py:144 (direkt/dynamisch unklar); tests/test_server.py:3762 (direkt/dynamisch unklar); tests/test_server.py:3812 (direkt/dynamisch unklar); tests/test_workout_text.py:150 (direkt/dynamisch unklar) |
| Funktion | `_naive_calendar_datetime` | 9173 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_duration_minutes` | 9183 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval_end` | 9193 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_interval` | 9200 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_items_conflict` | 9218 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_record` | 9228 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflict_sources` | 9241 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_library_entries` | 9254 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_calendar_conflicts_for_items` | 9269 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `calendar_conflicts` | 9278 | `providers/workout_text.py` | P2 | offen | tests/test_server.py:3585 (direkt/dynamisch unklar); tests/test_server.py:3590 (direkt/dynamisch unklar); tests/test_server.py:3591 (direkt/dynamisch unklar); tests/test_server.py:3601 (direkt/dynamisch unklar); tests/test_server.py:3606 (direkt/dynamisch unklar); tests/test_server.py:5041 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_create_training_plan_record` | 9293 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_for_storage` | 9306 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_local_plan_entries` | 9330 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_save_workout_library_entries_in_db` | 9341 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `save_workout_library_entries` | 9356 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:176 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:196 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:207 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:239 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:303 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:326 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:339 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:349 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:368 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:587 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:631 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:646 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:678 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:685 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:907 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:917 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:104 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:117 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:36 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:18 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:51 (direkt/dynamisch unklar); tests/test_coach_review.py:151 (direkt/dynamisch unklar); tests/test_coach_review.py:277 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:137 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:226 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:302 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:318 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:331 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:373 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:413 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:421 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:467 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:493 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:530 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:559 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:571 (direkt/dynamisch unklar); tests/test_server.py:1539 (direkt/dynamisch unklar); tests/test_server.py:1556 (direkt/dynamisch unklar); tests/test_server.py:2598 (direkt/dynamisch unklar); tests/test_server.py:2677 (direkt/dynamisch unklar); tests/test_server.py:2697 (direkt/dynamisch unklar); tests/test_server.py:2744 (direkt/dynamisch unklar); tests/test_server.py:2763 (direkt/dynamisch unklar); tests/test_server.py:2774 (direkt/dynamisch unklar); tests/test_server.py:2806 (direkt/dynamisch unklar); tests/test_server.py:357 (direkt/dynamisch unklar); tests/test_server.py:3784 (direkt/dynamisch unklar); tests/test_server.py:3869 (direkt/dynamisch unklar); tests/test_server.py:3897 (direkt/dynamisch unklar); tests/test_server.py:3918 (direkt/dynamisch unklar); tests/test_server.py:3920 (direkt/dynamisch unklar); tests/test_server.py:3927 (direkt/dynamisch unklar); tests/test_server.py:5552 (direkt/dynamisch unklar); tests/test_server.py:5562 (direkt/dynamisch unklar); tests/test_server.py:5590 (direkt/dynamisch unklar); tests/test_server.py:5835 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6301 (direkt/dynamisch unklar); tests/test_server.py:770 (direkt/dynamisch unklar); tests/test_server.py:803 (direkt/dynamisch unklar); tests/test_workout_repair.py:216 (direkt/dynamisch unklar); tests/test_workout_repair.py:275 (direkt/dynamisch unklar); tests/test_workout_repair.py:437 (direkt/dynamisch unklar); tests/test_workout_repair.py:53 (direkt/dynamisch unklar); tests/test_workout_repair.py:531 (direkt/dynamisch unklar); tests/test_workout_repair.py:79 (direkt/dynamisch unklar); tests/test_workout_repair.py:86 (direkt/dynamisch unklar) |
| Funktion | `list_training_plans` | 9373 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:362 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:364 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:918 (direkt/dynamisch unklar); tests/test_coach_review.py:178 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:213 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:219 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:221 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:222 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:496 (direkt/dynamisch unklar); tests/test_server.py:5556 (direkt/dynamisch unklar); tests/test_server.py:5567 (direkt/dynamisch unklar); tests/test_server.py:5583 (direkt/dynamisch unklar); tests/test_server.py:5595 (direkt/dynamisch unklar); tests/test_server.py:5611 (direkt/dynamisch unklar); tests/test_server.py:5634 (direkt/dynamisch unklar); tests/test_server.py:5656 (direkt/dynamisch unklar); tests/test_server.py:797 (direkt/dynamisch unklar); tests/test_server.py:825 (direkt/dynamisch unklar) |
| Funktion | `_normalise_training_plan_id` | 9381 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_transaction` | 9389 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_training_plan` | 9394 | `planning/` | P4 | offen | tests/test_server.py:5558 (direkt/dynamisch unklar); tests/test_server.py:5568 (direkt/dynamisch unklar); tests/test_server.py:809 (direkt/dynamisch unklar) |
| Funktion | `workout_is_hard` | 9411 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_recovery_description` | 9416 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_recovery_replacement` | 9428 | `planning/` | P4 | offen | tests/test_workout_repair.py:245 (direkt/dynamisch unklar) |
| Funktion | `private_calendar_adjustment_context` | 9446 | `providers/workout_text.py` | P2 | offen | keine statisch gefunden |
| Funktion | `latest_replan_preview` | 9475 | `planning/` | P4 | offen | tests/test_audit_remediation.py:223 (direkt/dynamisch unklar); tests/test_server.py:1570 (Monkeypatch/getattr/sys.modules) |
| Funktion | `current_adaptive_replan_status` | 9487 | `planning/` | P4 | offen | tests/test_server.py:2718 (direkt/dynamisch unklar) |
| Funktion | `coach_quick_actions_state` | 9504 | `coach/context.py` | P7 | offen | tests/test_coach_dialogue.py:711 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:733 (direkt/dynamisch unklar); tests/test_server.py:7733 (direkt/dynamisch unklar) |
| Funktion | `_adaptive_quick_action_blockers` | 9521 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `latest_illness_pause_state` | 9546 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_workout_fingerprint` | 9560 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `check_adaptive_replan` | 9569 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_forecast` | 9587 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_pause_replacement` | 9601 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `illness_calendar_events` | 9609 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `sync_illness_pause_to_intervals` | 9627 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:336 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_adaptive_preview_calendar_context` | 9636 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_feedback_signals` | 9650 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_approve_existing_pause` | 9665 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_environment` | 9682 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_calendar_limits` | 9699 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_reasons` | 9723 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_state` | 9755 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_replacement` | 9781 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_needs_change` | 9802 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change_result` | 9810 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_preview_change` | 9829 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `adaptive_replan_preview` | 9852 | `planning/` | P4 | offen | tests/test_coach_review.py:279 (direkt/dynamisch unklar); tests/test_server.py:1547 (direkt/dynamisch unklar); tests/test_server.py:1564 (direkt/dynamisch unklar); tests/test_server.py:2607 (direkt/dynamisch unklar); tests/test_server.py:2686 (direkt/dynamisch unklar); tests/test_server.py:2702 (direkt/dynamisch unklar); tests/test_server.py:2716 (direkt/dynamisch unklar); tests/test_server.py:2723 (direkt/dynamisch unklar); tests/test_server.py:2749 (direkt/dynamisch unklar); tests/test_server.py:2768 (direkt/dynamisch unklar); tests/test_server.py:2778 (direkt/dynamisch unklar); tests/test_server.py:2815 (direkt/dynamisch unklar); tests/test_workout_repair.py:285 (direkt/dynamisch unklar); tests/test_workout_repair.py:381 (direkt/dynamisch unklar) |
| Funktion | `_illness_checkin_values` | 9883 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_illness_checkin` | 9894 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_fill_illness_checkins` | 9910 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_change_stale_reason` | 9925 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_change` | 9935 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_adaptive_changes` | 9974 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_status` | 9989 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adaptive_replan_result` | 9997 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_adaptive_replan` | 10019 | `planning/` | P4 | offen | tests/test_audit_remediation.py:227 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:283 (direkt/dynamisch unklar); tests/test_server.py:2707 (direkt/dynamisch unklar); tests/test_server.py:2734 (direkt/dynamisch unklar); tests/test_server.py:2753 (direkt/dynamisch unklar); tests/test_server.py:2758 (direkt/dynamisch unklar); tests/test_server.py:2770 (direkt/dynamisch unklar); tests/test_server.py:2779 (direkt/dynamisch unklar); tests/test_server.py:2782 (direkt/dynamisch unklar); tests/test_server.py:2816 (direkt/dynamisch unklar); tests/test_workout_repair.py:286 (direkt/dynamisch unklar); tests/test_workout_repair.py:383 (direkt/dynamisch unklar) |
| Funktion | `season_plan_summary` | 10049 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `planning_state` | 10073 | `planning/` | P4 | offen | tests/test_server.py:1571 (direkt/dynamisch unklar) |
| Globale Bindung | `LIBRARY_WORKOUT_FIELDS` | 10077 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_local_id` | 10085 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_external_id` | 10101 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_ids` | 10114 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_workout_projection` | 10119 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_text_fields` | 10124 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalize_library_workout_duration` | 10133 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_library_workout` | 10142 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `workout_library_type` | 10164 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalized_workout_text` | 10170 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_matches` | 10174 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `library_workout_duration_minutes` | 10187 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compatible_workout_duration` | 10201 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_workout_inputs` | 10207 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validated_library_candidate` | 10220 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_similar_library_candidate_score` | 10233 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `find_similar_library_workout` | 10254 | `planning/` | P4 | offen | tests/test_workout_repair.py:77 (direkt/dynamisch unklar); tests/test_workout_repair.py:84 (direkt/dynamisch unklar); tests/test_workout_repair.py:92 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_payload_hash` | 10270 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_unit_metadata` | 10280 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `normalize_planned_unit` | 10296 | `planning/` | P4 | offen | tests/test_server.py:2794 (direkt/dynamisch unklar); tests/test_workout_repair.py:166 (direkt/dynamisch unklar); tests/test_workout_repair.py:482 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Funktion | `_insert_planned_unit` | 10319 | `planning/` | P4 | offen | tests/test_workout_repair.py:170 (direkt/dynamisch unklar); tests/test_workout_repair.py:487 (direkt/dynamisch unklar); tests/test_workout_repair.py:553 (direkt/dynamisch unklar) |
| Globale Bindung | `_PLANNING_STATE_RESET_PENDING` | 10335 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_bump_planning_revision` | 10338 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:879 (direkt/dynamisch unklar); tests/test_workout_repair.py:488 (direkt/dynamisch unklar); tests/test_workout_repair.py:557 (direkt/dynamisch unklar) |
| Funktion | `_persist_local_planned_unit` | 10362 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `create_local_planned_unit` | 10371 | `planning/` | P4 | offen | tests/test_coach_review.py:183 (direkt/dynamisch unklar); tests/test_server.py:3001 (direkt/dynamisch unklar); tests/test_server.py:3123 (direkt/dynamisch unklar); tests/test_server.py:3144 (direkt/dynamisch unklar); tests/test_server.py:327 (direkt/dynamisch unklar); tests/test_server.py:3597 (direkt/dynamisch unklar); tests/test_server.py:4904 (direkt/dynamisch unklar); tests/test_server.py:4926 (direkt/dynamisch unklar); tests/test_server.py:4982 (direkt/dynamisch unklar); tests/test_server.py:4999 (direkt/dynamisch unklar); tests/test_server.py:5017 (direkt/dynamisch unklar); tests/test_server.py:5035 (direkt/dynamisch unklar); tests/test_server.py:5056 (direkt/dynamisch unklar); tests/test_server.py:5079 (direkt/dynamisch unklar); tests/test_server.py:5124 (direkt/dynamisch unklar); tests/test_server.py:5146 (direkt/dynamisch unklar); tests/test_server.py:5169 (direkt/dynamisch unklar); tests/test_server.py:5185 (direkt/dynamisch unklar); tests/test_server.py:5202 (direkt/dynamisch unklar); tests/test_server.py:5265 (direkt/dynamisch unklar); tests/test_server.py:5327 (direkt/dynamisch unklar); tests/test_server.py:5336 (direkt/dynamisch unklar); tests/test_server.py:5494 (direkt/dynamisch unklar); tests/test_server.py:5525 (direkt/dynamisch unklar); tests/test_server.py:5688 (direkt/dynamisch unklar); tests/test_server.py:5718 (direkt/dynamisch unklar); tests/test_server.py:5736 (direkt/dynamisch unklar); tests/test_server.py:5741 (direkt/dynamisch unklar); tests/test_server.py:5750 (direkt/dynamisch unklar); tests/test_server.py:5754 (direkt/dynamisch unklar); tests/test_server.py:5759 (direkt/dynamisch unklar); tests/test_server.py:5768 (direkt/dynamisch unklar); tests/test_server.py:5787 (direkt/dynamisch unklar); tests/test_server.py:5790 (direkt/dynamisch unklar); tests/test_server.py:5816 (direkt/dynamisch unklar); tests/test_server.py:657 (direkt/dynamisch unklar); tests/test_server.py:680 (direkt/dynamisch unklar); tests/test_server.py:697 (direkt/dynamisch unklar); tests/test_server.py:723 (direkt/dynamisch unklar); tests/test_server.py:727 (direkt/dynamisch unklar); tests/test_server.py:7329 (direkt/dynamisch unklar); tests/test_server.py:830 (direkt/dynamisch unklar); tests/test_server.py:850 (direkt/dynamisch unklar); tests/test_server.py:854 (direkt/dynamisch unklar); tests/test_server.py:877 (direkt/dynamisch unklar); tests/test_server.py:925 (direkt/dynamisch unklar) |
| Funktion | `list_planned_units` | 10389 | `planning/` | P4 | offen | tests/test_coach_review.py:154 (direkt/dynamisch unklar); tests/test_coach_review.py:168 (direkt/dynamisch unklar); tests/test_coach_review.py:177 (direkt/dynamisch unklar); tests/test_coach_review.py:287 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:326 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:565 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:581 (direkt/dynamisch unklar); tests/test_server.py:2710 (direkt/dynamisch unklar); tests/test_server.py:2711 (direkt/dynamisch unklar); tests/test_server.py:2719 (direkt/dynamisch unklar); tests/test_server.py:2784 (direkt/dynamisch unklar); tests/test_server.py:3055 (direkt/dynamisch unklar); tests/test_server.py:3065 (direkt/dynamisch unklar); tests/test_server.py:3068 (direkt/dynamisch unklar); tests/test_server.py:3079 (direkt/dynamisch unklar); tests/test_server.py:3095 (direkt/dynamisch unklar); tests/test_server.py:3166 (direkt/dynamisch unklar); tests/test_server.py:3907 (direkt/dynamisch unklar); tests/test_server.py:3911 (direkt/dynamisch unklar); tests/test_server.py:3919 (direkt/dynamisch unklar); tests/test_server.py:3923 (direkt/dynamisch unklar); tests/test_server.py:4917 (direkt/dynamisch unklar); tests/test_server.py:4943 (direkt/dynamisch unklar); tests/test_server.py:4960 (direkt/dynamisch unklar); tests/test_server.py:4994 (direkt/dynamisch unklar); tests/test_server.py:5012 (direkt/dynamisch unklar); tests/test_server.py:5030 (direkt/dynamisch unklar); tests/test_server.py:5069 (direkt/dynamisch unklar); tests/test_server.py:5093 (direkt/dynamisch unklar); tests/test_server.py:5115 (direkt/dynamisch unklar); tests/test_server.py:5182 (direkt/dynamisch unklar); tests/test_server.py:5198 (direkt/dynamisch unklar); tests/test_server.py:5219 (direkt/dynamisch unklar); tests/test_server.py:5519 (direkt/dynamisch unklar); tests/test_server.py:5520 (direkt/dynamisch unklar); tests/test_server.py:5609 (direkt/dynamisch unklar); tests/test_server.py:5683 (direkt/dynamisch unklar); tests/test_server.py:5811 (direkt/dynamisch unklar); tests/test_server.py:5841 (direkt/dynamisch unklar); tests/test_server.py:6211 (direkt/dynamisch unklar); tests/test_server.py:720 (direkt/dynamisch unklar); tests/test_server.py:748 (direkt/dynamisch unklar); tests/test_workout_repair.py:127 (direkt/dynamisch unklar); tests/test_workout_repair.py:140 (direkt/dynamisch unklar); tests/test_workout_repair.py:158 (direkt/dynamisch unklar); tests/test_workout_repair.py:233 (direkt/dynamisch unklar); tests/test_workout_repair.py:256 (direkt/dynamisch unklar); tests/test_workout_repair.py:268 (direkt/dynamisch unklar); tests/test_workout_repair.py:287 (direkt/dynamisch unklar); tests/test_workout_repair.py:296 (direkt/dynamisch unklar); tests/test_workout_repair.py:304 (direkt/dynamisch unklar); tests/test_workout_repair.py:336 (direkt/dynamisch unklar); tests/test_workout_repair.py:384 (direkt/dynamisch unklar); tests/test_workout_repair.py:395 (direkt/dynamisch unklar); tests/test_workout_repair.py:425 (direkt/dynamisch unklar); tests/test_workout_repair.py:460 (direkt/dynamisch unklar) |
| Funktion | `create_local_workout_library_entry` | 10401 | `planning/` | P4 | offen | tests/test_server.py:3667 (direkt/dynamisch unklar); tests/test_server.py:3878 (direkt/dynamisch unklar); tests/test_server.py:3940 (direkt/dynamisch unklar); tests/test_server.py:6240 (direkt/dynamisch unklar); tests/test_server.py:6277 (direkt/dynamisch unklar); tests/test_server.py:6321 (direkt/dynamisch unklar); tests/test_server.py:6480 (direkt/dynamisch unklar); tests/test_server.py:8651 (direkt/dynamisch unklar); tests/test_server.py:8741 (direkt/dynamisch unklar); tests/test_server.py:8742 (direkt/dynamisch unklar); tests/test_server.py:948 (direkt/dynamisch unklar); tests/test_server.py:951 (direkt/dynamisch unklar) |
| Funktion | `create_local_library_template` | 10429 | `planning/` | P4 | offen | tests/test_coach_review.py:227 (direkt/dynamisch unklar); tests/test_coach_review.py:253 (direkt/dynamisch unklar); tests/test_coach_review.py:263 (direkt/dynamisch unklar); tests/test_coach_review.py:290 (direkt/dynamisch unklar); tests/test_coach_review.py:322 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:138 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:351 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:494 (direkt/dynamisch unklar); tests/test_server.py:3866 (direkt/dynamisch unklar); tests/test_server.py:490 (direkt/dynamisch unklar); tests/test_server.py:684 (direkt/dynamisch unklar); tests/test_server.py:902 (direkt/dynamisch unklar); tests/test_server.py:922 (direkt/dynamisch unklar) |
| Funktion | `_preserved_dirty_library_workout` | 10452 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_remote_library_metadata` | 10467 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_remote_library_workout_entry` | 10484 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_library_workouts` | 10499 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_workout_library` | 10522 | `planning/` | P4 | offen | tests/test_server.py:1383 (direkt/dynamisch unklar); tests/test_server.py:1700 (direkt/dynamisch unklar); tests/test_server.py:3652 (direkt/dynamisch unklar); tests/test_server.py:3658 (direkt/dynamisch unklar); tests/test_server.py:3682 (direkt/dynamisch unklar); tests/test_server.py:4291 (direkt/dynamisch unklar); tests/test_server.py:4307 (direkt/dynamisch unklar); tests/test_server.py:4325 (direkt/dynamisch unklar); tests/test_server.py:4340 (direkt/dynamisch unklar); tests/test_server.py:6294 (direkt/dynamisch unklar); tests/test_server.py:6494 (direkt/dynamisch unklar) |
| Funktion | `list_workout_library` | 10547 | `planning/` | P4 | offen | tests/test_coach_review.py:203 (direkt/dynamisch unklar); tests/test_coach_review.py:238 (direkt/dynamisch unklar); tests/test_coach_review.py:252 (direkt/dynamisch unklar); tests/test_coach_review.py:260 (direkt/dynamisch unklar); tests/test_coach_review.py:273 (direkt/dynamisch unklar); tests/test_coach_review.py:333 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:158 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:162 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:170 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:353 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:356 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:495 (direkt/dynamisch unklar); tests/test_server.py:3663 (direkt/dynamisch unklar); tests/test_server.py:3672 (direkt/dynamisch unklar); tests/test_server.py:3674 (direkt/dynamisch unklar); tests/test_server.py:3675 (direkt/dynamisch unklar); tests/test_server.py:3677 (direkt/dynamisch unklar); tests/test_server.py:3679 (direkt/dynamisch unklar); tests/test_server.py:3887 (direkt/dynamisch unklar); tests/test_server.py:3950 (direkt/dynamisch unklar); tests/test_server.py:4295 (direkt/dynamisch unklar); tests/test_server.py:4303 (direkt/dynamisch unklar); tests/test_server.py:4311 (direkt/dynamisch unklar); tests/test_server.py:4321 (direkt/dynamisch unklar); tests/test_server.py:4329 (direkt/dynamisch unklar); tests/test_server.py:4337 (direkt/dynamisch unklar); tests/test_server.py:4344 (direkt/dynamisch unklar); tests/test_server.py:6169 (direkt/dynamisch unklar); tests/test_server.py:6258 (direkt/dynamisch unklar); tests/test_server.py:6311 (direkt/dynamisch unklar); tests/test_server.py:6546 (direkt/dynamisch unklar); tests/test_server.py:8657 (direkt/dynamisch unklar); tests/test_server.py:918 (direkt/dynamisch unklar); tests/test_server.py:919 (direkt/dynamisch unklar); tests/test_workout_repair.py:78 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:85 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_list_workout_library_in_db` | 10554 | `db/` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_DEFAULT` | 10571 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `API_PAGE_MAX` | 10572 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CHAT_PAGE_MAX` | 10573 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_PAGE_MAX` | 10574 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `api_page_limit` | 10577 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `encode_page_cursor` | 10584 | `http_api/pagination.py` | P10 | offen | tests/test_workout_repair.py:510 (direkt/dynamisch unklar) |
| Funktion | `decode_page_cursor` | 10589 | `http_api/pagination.py` | P10 | offen | keine statisch gefunden |
| Funktion | `activity_page_key` | 10599 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `paged_activities` | 10606 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1679 (direkt/dynamisch unklar); tests/test_server.py:1680 (direkt/dynamisch unklar); tests/test_server.py:1681 (direkt/dynamisch unklar) |
| Funktion | `paged_chat_history` | 10633 | `http_api/pagination.py` | P10 | offen | tests/test_audit_remediation.py:290 (direkt/dynamisch unklar); tests/test_audit_remediation.py:292 (direkt/dynamisch unklar); tests/test_coach_review.py:266 (direkt/dynamisch unklar); tests/test_coach_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:1689 (direkt/dynamisch unklar); tests/test_server.py:1690 (direkt/dynamisch unklar); tests/test_server.py:1695 (direkt/dynamisch unklar) |
| Funktion | `paged_library` | 10665 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1704 (direkt/dynamisch unklar); tests/test_server.py:1705 (direkt/dynamisch unklar) |
| Funktion | `state_versions` | 10693 | `http_api/pagination.py` | P10 | offen | tests/test_server.py:1857 (Monkeypatch/getattr/sys.modules) |
| Funktion | `list_recent_activities` | 10714 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `get_activity_details` | 10734 | `activities/` | P3 | offen | tests/test_server.py:486 (direkt/dynamisch unklar) |
| Funktion | `list_local_planned_workouts` | 10775 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `list_dated_local_planned_workouts` | 10780 | `planning/` | P4 | offen | tests/test_server.py:2693 (direkt/dynamisch unklar); tests/test_server.py:2706 (direkt/dynamisch unklar); tests/test_server.py:2709 (direkt/dynamisch unklar); tests/test_server.py:2757 (direkt/dynamisch unklar); tests/test_server.py:2783 (direkt/dynamisch unklar); tests/test_server.py:2817 (direkt/dynamisch unklar); tests/test_server.py:2820 (direkt/dynamisch unklar); tests/test_server.py:2980 (Monkeypatch/getattr/sys.modules); tests/test_server.py:3030 (direkt/dynamisch unklar); tests/test_server.py:3047 (direkt/dynamisch unklar); tests/test_server.py:3141 (direkt/dynamisch unklar); tests/test_server.py:3786 (direkt/dynamisch unklar); tests/test_server.py:3875 (direkt/dynamisch unklar); tests/test_server.py:3933 (direkt/dynamisch unklar); tests/test_server.py:4304 (direkt/dynamisch unklar); tests/test_server.py:4322 (direkt/dynamisch unklar) |
| Funktion | `_canonical_remote_indexes` | 10785 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_linked_remote` | 10792 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event_identity` | 10803 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_event` | 10815 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_remote_event` | 10840 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_planned_workout_sort_key` | 10856 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_local_events` | 10864 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_canonical_unjoined_remote_events` | 10878 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `canonical_planned_workouts` | 10890 | `planning/` | P4 | offen | tests/test_server.py:3015 (direkt/dynamisch unklar); tests/test_server.py:3030 (direkt/dynamisch unklar) |
| Funktion | `list_coach_planned_workouts` | 10909 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_competition` | 10914 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_external_event` | 10931 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_local_calendar_sort_key` | 10945 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `local_calendar_events` | 10952 | `calendar/` | P3 | offen | tests/test_server.py:3115 (direkt/dynamisch unklar) |
| Funktion | `update_planned_unit_sync_state` | 10967 | `planning/` | P4 | offen | tests/test_workout_repair.py:225 (direkt/dynamisch unklar); tests/test_workout_repair.py:254 (direkt/dynamisch unklar); tests/test_workout_repair.py:279 (direkt/dynamisch unklar); tests/test_workout_repair.py:65 (direkt/dynamisch unklar) |
| Funktion | `_planned_unit_sync_guard` | 10980 | `planning/` | P4 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarBatch` | 10993 | `calendar/` | P3 | offen | keine statisch gefunden |
| Klasse | `_RepairCalendarContext` | 11050 | `calendar/` | P3 | offen | keine statisch gefunden |
| Globale Bindung | `PLANNED_CALENDAR_RECHECK_ERROR` | 11067 | `errors.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_context` | 11070 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_recheck` | 11110 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_invalid` | 11117 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_event_is_ambiguous` | 11125 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_event` | 11133 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_related_events` | 11146 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_check_remote_identity` | 11156 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_upsert` | 11168 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_delete_duplicates` | 11197 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_calendar_completion` | 11207 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_repair_local_planned_unit_calendar_entry` | 11229 | `planning/` | P4 | offen | tests/test_server.py:263 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_sync_local_planned_unit_calendar_entry` | 11246 | `sync/` | P6 | offen | tests/test_server.py:3906 (direkt/dynamisch unklar); tests/test_server.py:3910 (direkt/dynamisch unklar); tests/test_workout_repair.py:313 (direkt/dynamisch unklar) |
| Funktion | `_load_planned_calendar_entry` | 11251 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_sync_recheck` | 11269 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_remote_event_is_invalid` | 11276 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_planned_calendar_remote_event` | 11285 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_require_intervals_calendar_access` | 11300 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_planned_calendar_removed` | 11305 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remove_planned_calendar_event` | 11311 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_calendar_event_payload` | 11319 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_planned_calendar_sync_error` | 11331 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_calendar_event` | 11340 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_planned_unit_calendar_entry_unlocked` | 11357 | `sync/` | P6 | offen | keine statisch gefunden |
| Globale Bindung | `LIBRARY_SYNC_PREVIEW_TTL_SECONDS` | 11377 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_rows` | 11380 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_category` | 11393 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_entry` | 11405 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_sync_snapshot` | 11428 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `refresh_workout_library` | 11448 | `planning/` | P4 | offen | tests/test_server.py:6064 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6093 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6106 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6126 (direkt/dynamisch unklar); tests/test_server.py:613 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6205 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6229 (Monkeypatch/getattr/sys.modules); tests/test_server.py:626 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6270 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6288 (direkt/dynamisch unklar) |
| Funktion | `plan_library_workout_remote` | 11489 | `planning/` | P4 | offen | tests/test_server.py:6469 (direkt/dynamisch unklar) |
| Funktion | `_persist_library_calendar_identity` | 11493 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_calendar_entry` | 11514 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `save_snapshot_view` | 11529 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:111 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:362 (direkt/dynamisch unklar) |
| Funktion | `_workout_library_entry_id` | 11535 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stored_workout_library_entry` | 11542 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_workout_library_update_candidate` | 11557 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_library_workout_content` | 11572 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_library_workout_metadata` | 11582 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_updated_workout_library_entry` | 11588 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_workout_library_entry` | 11603 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `update_workout_library_entry` | 11611 | `planning/` | P4 | offen | tests/test_coach_review.py:269 (direkt/dynamisch unklar); tests/test_server.py:1387 (direkt/dynamisch unklar); tests/test_server.py:3670 (direkt/dynamisch unklar); tests/test_server.py:3673 (direkt/dynamisch unklar); tests/test_server.py:3676 (direkt/dynamisch unklar); tests/test_server.py:3678 (direkt/dynamisch unklar); tests/test_server.py:3684 (direkt/dynamisch unklar); tests/test_server.py:3686 (direkt/dynamisch unklar) |
| Funktion | `update_workout_library_sync_state` | 11635 | `planning/` | P4 | offen | tests/test_server.py:6484 (direkt/dynamisch unklar) |
| Funktion | `workout_library_sync_summary` | 11654 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_intervals_calendar_window` | 11670 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_connection_state` | 11682 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_public_state` | 11696 | `calendar/` | P3 | offen | tests/test_server.py:7946 (direkt/dynamisch unklar); tests/test_server.py:7956 (direkt/dynamisch unklar) |
| Funktion | `set_sync_operation_state` | 11731 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_public_state` | 11761 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_status_state` | 11779 | `sync/` | P6 | offen | tests/test_server.py:1858 (direkt/dynamisch unklar); tests/test_server.py:2103 (direkt/dynamisch unklar) |
| Funktion | `sync_browser_state` | 11783 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_load_local_library_workout_for_sync` | 11798 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_library_workout` | 11817 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_store_library_workout_remote_identity` | 11830 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_finish_library_workout_sync` | 11844 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_local_workout_library_entry_unlocked` | 11863 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_local_workout_library_entry` | 11876 | `sync/` | P6 | offen | tests/test_server.py:3885 (direkt/dynamisch unklar); tests/test_server.py:3891 (direkt/dynamisch unklar); tests/test_server.py:3947 (direkt/dynamisch unklar) |
| Funktion | `_validate_library_plan_entries` | 11891 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_request` | 11899 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_requests` | 11923 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_plan_conflicts` | 11928 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_raise_library_plan_conflicts` | 11951 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_library_plan_request` | 11958 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `apply_workout_library_plan` | 11983 | `planning/` | P4 | offen | tests/test_server.py:4297 (direkt/dynamisch unklar); tests/test_server.py:4317 (direkt/dynamisch unklar); tests/test_server.py:4332 (direkt/dynamisch unklar); tests/test_server.py:4346 (direkt/dynamisch unklar) |
| Funktion | `_library_bulk_entry_id` | 11997 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_date` | 12006 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_entry_hash` | 12017 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entry` | 12026 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_bulk_request_entries` | 12038 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_payload_hash` | 12051 | `planning/` | P4 | offen | tests/test_coach_tool_coverage.py:188 (direkt/dynamisch unklar); tests/test_workout_repair.py:172 (direkt/dynamisch unklar) |
| Funktion | `_sync_selected_workout_library` | 12055 | `sync/` | P6 | offen | tests/test_server.py:6533 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8749 (direkt/dynamisch unklar); tests/test_workout_repair.py:239 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar); tests/test_workout_repair.py:95 (direkt/dynamisch unklar) |
| Funktion | `_selected_library_sync_row` | 12068 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_library_sync_error` | 12081 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_planned_library_entry` | 12085 | `sync/` | P6 | offen | tests/test_server.py:264 (direkt/dynamisch unklar) |
| Funktion | `_sync_existing_library_calendar_entry` | 12104 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_pending_library_entry` | 12119 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_library_entry` | 12134 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_verify_selected_library_repair` | 12150 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_sync_selected_workout_library_unlocked` | 12163 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_request` | 12180 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_load_local_planned_workout` | 12191 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_delete_local_planned_workout` | 12207 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_workout_update_candidate` | 12225 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_planned_workout_date` | 12244 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_reconcile_updated_planned_workout_content` | 12267 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_preserve_local_planned_workout_metadata` | 12282 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_normalized_planned_workout_update` | 12291 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_save_local_planned_workout_update` | 12312 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_local_planned_workout_in_db` | 12330 | `db/` | P1 | offen | keine statisch gefunden |
| Funktion | `update_local_planned_workout` | 12354 | `planning/` | P4 | offen | tests/test_server.py:2751 (direkt/dynamisch unklar); tests/test_server.py:2769 (direkt/dynamisch unklar); tests/test_server.py:3052 (direkt/dynamisch unklar); tests/test_server.py:3066 (direkt/dynamisch unklar); tests/test_server.py:3096 (direkt/dynamisch unklar); tests/test_server.py:3128 (direkt/dynamisch unklar); tests/test_server.py:3135 (direkt/dynamisch unklar); tests/test_server.py:3137 (direkt/dynamisch unklar); tests/test_server.py:3139 (direkt/dynamisch unklar); tests/test_server.py:3149 (direkt/dynamisch unklar); tests/test_server.py:3151 (direkt/dynamisch unklar); tests/test_server.py:3600 (direkt/dynamisch unklar); tests/test_server.py:3874 (direkt/dynamisch unklar); tests/test_server.py:3922 (direkt/dynamisch unklar); tests/test_server.py:5040 (direkt/dynamisch unklar); tests/test_server.py:5740 (direkt/dynamisch unklar); tests/test_workout_repair.py:255 (direkt/dynamisch unklar); tests/test_workout_repair.py:331 (direkt/dynamisch unklar); tests/test_workout_repair.py:352 (direkt/dynamisch unklar); tests/test_workout_repair.py:371 (direkt/dynamisch unklar); tests/test_workout_repair.py:419 (direkt/dynamisch unklar); tests/test_workout_repair.py:436 (direkt/dynamisch unklar); tests/test_workout_repair.py:506 (direkt/dynamisch unklar); tests/test_workout_repair.py:535 (direkt/dynamisch unklar) |
| Funktion | `_planned_conflict_resolution_request` | 12380 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_open_planned_unit_conflict` | 12391 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planned_conflict_payload` | 12402 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_keep_local_planned_unit_conflict` | 12412 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_deletion` | 12418 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_adopt_remote_planned_unit` | 12429 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `resolve_planned_unit_conflict` | 12441 | `planning/` | P4 | offen | tests/test_server.py:3098 (direkt/dynamisch unklar); tests/test_server.py:3101 (direkt/dynamisch unklar) |
| Funktion | `latest_snapshot` | 12459 | `sync/` | P6 | offen | tests/test_coach_tool_coverage.py:368 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:311 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:319 (direkt/dynamisch unklar); tests/test_provider_review.py:129 (direkt/dynamisch unklar); tests/test_provider_review.py:91 (direkt/dynamisch unklar); tests/test_server.py:1647 (direkt/dynamisch unklar); tests/test_server.py:1648 (direkt/dynamisch unklar); tests/test_server.py:2979 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5419 (direkt/dynamisch unklar); tests/test_server.py:5421 (direkt/dynamisch unklar); tests/test_server.py:6538 (direkt/dynamisch unklar); tests/test_server.py:6561 (direkt/dynamisch unklar); tests/test_server.py:7718 (direkt/dynamisch unklar) |
| Funktion | `save_snapshot` | 12464 | `sync/` | P6 | offen | tests/test_diagnostic_followups.py:272 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:310 (direkt/dynamisch unklar); tests/test_provider_review.py:109 (direkt/dynamisch unklar); tests/test_provider_review.py:229 (direkt/dynamisch unklar); tests/test_provider_review.py:267 (direkt/dynamisch unklar); tests/test_provider_review.py:62 (direkt/dynamisch unklar); tests/test_provider_review.py:86 (direkt/dynamisch unklar); tests/test_server.py:1415 (direkt/dynamisch unklar); tests/test_server.py:1627 (direkt/dynamisch unklar); tests/test_server.py:1664 (direkt/dynamisch unklar); tests/test_server.py:1672 (direkt/dynamisch unklar); tests/test_server.py:1712 (direkt/dynamisch unklar); tests/test_server.py:2322 (direkt/dynamisch unklar); tests/test_server.py:2347 (direkt/dynamisch unklar); tests/test_server.py:3626 (direkt/dynamisch unklar); tests/test_server.py:3691 (direkt/dynamisch unklar); tests/test_server.py:4313 (direkt/dynamisch unklar); tests/test_server.py:441 (direkt/dynamisch unklar); tests/test_server.py:5373 (direkt/dynamisch unklar); tests/test_server.py:5414 (direkt/dynamisch unklar); tests/test_server.py:6550 (direkt/dynamisch unklar); tests/test_server.py:7331 (direkt/dynamisch unklar); tests/test_server.py:7709 (direkt/dynamisch unklar) |
| Funktion | `merge_performance_snapshot` | 12474 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `merge_historical_snapshot` | 12500 | `sync/` | P6 | offen | tests/test_server.py:1000 (direkt/dynamisch unklar) |
| Funktion | `_remote_planned_unit_id` | 12525 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_date` | 12530 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_duration` | 12540 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_payload` | 12548 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_planned_unit_existing_state` | 12579 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_conflict` | 12601 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_update_remote_planned_clean` | 12612 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_upsert_remote_planned_event` | 12626 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_remote_calendar_window` | 12648 | `calendar/` | P3 | offen | keine statisch gefunden |
| Funktion | `_mark_missing_remote_planned_units` | 12665 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `upsert_remote_planned_units` | 12699 | `planning/` | P4 | offen | tests/test_server.py:3043 (direkt/dynamisch unklar); tests/test_server.py:3045 (direkt/dynamisch unklar); tests/test_server.py:3053 (direkt/dynamisch unklar); tests/test_server.py:3064 (direkt/dynamisch unklar); tests/test_server.py:3067 (direkt/dynamisch unklar); tests/test_server.py:3075 (direkt/dynamisch unklar); tests/test_server.py:3094 (direkt/dynamisch unklar); tests/test_server.py:3097 (direkt/dynamisch unklar); tests/test_server.py:3100 (direkt/dynamisch unklar); tests/test_server.py:3584 (direkt/dynamisch unklar); tests/test_server.py:3589 (direkt/dynamisch unklar); tests/test_server.py:5668 (direkt/dynamisch unklar) |
| Globale Bindung | `PROVIDER_RESYNC_KEYS` | 12747 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `provider_resync_state` | 12763 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_full_provider_resync` | 12775 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_full_provider_resync_details` | 12787 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_full_provider_resync` | 12792 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_start_full_provider_resync` | 12802 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_complete_full_provider_resync` | 12809 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_full_provider_resync_failure` | 12816 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_full_provider_resync` | 12827 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `full_provider_resync` | 12842 | `sync/` | P6 | offen | tests/test_server.py:6396 (direkt/dynamisch unklar); tests/test_server.py:6534 (direkt/dynamisch unklar); tests/test_server.py:6560 (direkt/dynamisch unklar); tests/test_server.py:6570 (direkt/dynamisch unklar); tests/test_server.py:6646 (direkt/dynamisch unklar) |
| Funktion | `_completed_intervals_sync_result` | 12877 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_wait_for_existing_intervals_sync` | 12892 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_store_intervals_snapshot` | 12921 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_seed_intervals_workout_library` | 12950 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_window` | 12970 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_execute_intervals_sync` | 12987 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_record_intervals_sync_failure` | 13044 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_finish_intervals_sync` | 13059 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `sync_intervals` | 13070 | `sync/` | P6 | offen | tests/test_audit_remediation.py:284 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:405 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:63 (direkt/dynamisch unklar); tests/test_coach_review.py:80 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:265 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:100 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:123 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:158 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:38 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:75 (Monkeypatch/getattr/sys.modules); tests/test_server.py:571 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6065 (direkt/dynamisch unklar); tests/test_server.py:6080 (direkt/dynamisch unklar); tests/test_server.py:6095 (direkt/dynamisch unklar); tests/test_server.py:6108 (direkt/dynamisch unklar); tests/test_server.py:6137 (direkt/dynamisch unklar); tests/test_server.py:616 (direkt/dynamisch unklar); tests/test_server.py:6166 (direkt/dynamisch unklar); tests/test_server.py:6206 (direkt/dynamisch unklar); tests/test_server.py:6207 (direkt/dynamisch unklar); tests/test_server.py:6231 (direkt/dynamisch unklar); tests/test_server.py:6233 (direkt/dynamisch unklar); tests/test_server.py:6253 (direkt/dynamisch unklar); tests/test_server.py:6271 (direkt/dynamisch unklar); tests/test_server.py:629 (direkt/dynamisch unklar); tests/test_server.py:6388 (direkt/dynamisch unklar); tests/test_server.py:6489 (direkt/dynamisch unklar); tests/test_server.py:7762 (direkt/dynamisch unklar); tests/test_server.py:8029 (direkt/dynamisch unklar); tests/test_workout_repair.py:149 (direkt/dynamisch unklar); tests/test_workout_repair.py:186 (direkt/dynamisch unklar); tests/test_workout_repair.py:194 (direkt/dynamisch unklar); tests/test_workout_repair.py:209 (direkt/dynamisch unklar) |
| Funktion | `refresh_current_performance` | 13104 | `performance/` | P3 | offen | tests/test_provider_review.py:76 (direkt/dynamisch unklar); tests/test_server.py:547 (Monkeypatch/getattr/sys.modules); tests/test_server.py:560 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7323 (direkt/dynamisch unklar) |
| Funktion | `_activity_rollup_date` | 13128 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_number` | 13135 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_rollup_totals` | 13142 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_rollup` | 13160 | `activities/` | P3 | offen | tests/test_server.py:5287 (direkt/dynamisch unklar) |
| Funktion | `wellness_average` | 13172 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_wellness_rows` | 13189 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_load_by_date` | 13202 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_atl_series_from_rows` | 13219 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `actual_atl_series` | 13240 | `performance/` | P3 | offen | tests/test_server.py:7220 (direkt/dynamisch unklar) |
| Funktion | `_wellness_eftp_value` | 13249 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_activity_eftp_value` | 13261 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `eftp_30_day_average` | 13277 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `comparison_value` | 13292 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `first_present` | 13328 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_value` | 13338 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `readiness_score_value` | 13352 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `wellness_form_average` | 13368 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `as_number` | 13385 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_setting` | 13395 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `sport_info_setting` | 13406 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `intervals_eftp_value` | 13420 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `metric` | 13432 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `intervals_max_hr_metric` | 13437 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `threshold_pace_seconds` | 13469 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `zone2_pace_seconds` | 13478 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `height_in_cm` | 13484 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_snapshot_inputs` | 13491 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_latest_ride_activity` | 13505 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_first_performance_source` | 13518 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_body_metrics` | 13522 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_preferred_performance_metric` | 13551 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_threshold_metrics` | 13558 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_vo2_and_prediction_metrics` | 13595 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `api_performance_metrics` | 13615 | `performance/` | P3 | offen | tests/test_server.py:3345 (direkt/dynamisch unklar); tests/test_server.py:3354 (direkt/dynamisch unklar); tests/test_server.py:3462 (direkt/dynamisch unklar) |
| Funktion | `activity_pace_seconds_per_km` | 13644 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `latest_activity_for_validation` | 13658 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_activity_metric` | 13674 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_intensity` | 13682 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_evidence` | 13692 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_direct_estimates` | 13719 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `bounded_performance_metric` | 13734 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `cycling_activity_validation_details` | 13757 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_validation_details` | 13775 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `activity_performance_validation` | 13807 | `activities/` | P3 | offen | tests/test_server.py:7119 (direkt/dynamisch unklar); tests/test_server.py:7141 (direkt/dynamisch unklar); tests/test_server.py:7147 (direkt/dynamisch unklar); tests/test_server.py:7156 (direkt/dynamisch unklar) |
| Funktion | `_garmin_sleep_recovery` | 13852 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_intervals_sleep_recovery` | 13885 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_sleep_recovery` | 13906 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_metric` | 13918 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_readiness` | 13938 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_recovery_context` | 13951 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_load_context` | 13982 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_trend` | 14012 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_performance_comparisons` | 14023 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `current_performance_context` | 14066 | `performance/` | P3 | offen | tests/test_provider_review.py:268 (direkt/dynamisch unklar); tests/test_server.py:3485 (direkt/dynamisch unklar); tests/test_server.py:3515 (direkt/dynamisch unklar); tests/test_server.py:3544 (direkt/dynamisch unklar); tests/test_server.py:3565 (direkt/dynamisch unklar); tests/test_server.py:3577 (direkt/dynamisch unklar); tests/test_server.py:7058 (direkt/dynamisch unklar); tests/test_server.py:7080 (direkt/dynamisch unklar); tests/test_server.py:7107 (direkt/dynamisch unklar); tests/test_server.py:7176 (direkt/dynamisch unklar); tests/test_server.py:7190 (direkt/dynamisch unklar); tests/test_server.py:7206 (direkt/dynamisch unklar); tests/test_server.py:7237 (direkt/dynamisch unklar); tests/test_server.py:7258 (direkt/dynamisch unklar); tests/test_server.py:7280 (direkt/dynamisch unklar); tests/test_server.py:7300 (direkt/dynamisch unklar); tests/test_server.py:7306 (direkt/dynamisch unklar); tests/test_server.py:7310 (direkt/dynamisch unklar) |
| Funktion | `activity_sport` | 14137 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `compact_coach_activity` | 14151 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_planned_event` | 14155 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workout` | 14159 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `compact_coach_local_planned_workouts` | 14164 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `coach_context_json_size` | 14168 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_value` | 14172 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `bounded_coach_context_sections` | 14176 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_context_projection_meta` | 14180 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `future_coach_planned_workouts` | 14199 | `coach/context.py` | P7 | offen | tests/test_server.py:5277 (direkt/dynamisch unklar) |
| Funktion | `coach_intervals_context` | 14218 | `coach/context.py` | P7 | offen | tests/test_server.py:5269 (direkt/dynamisch unklar); tests/test_server.py:5306 (direkt/dynamisch unklar); tests/test_server.py:5307 (direkt/dynamisch unklar); tests/test_server.py:5328 (direkt/dynamisch unklar) |
| Funktion | `structured_athlete_context` | 14264 | `coach/context.py` | P7 | offen | tests/test_server.py:1534 (direkt/dynamisch unklar); tests/test_server.py:1608 (direkt/dynamisch unklar); tests/test_server.py:2336 (direkt/dynamisch unklar); tests/test_server.py:3298 (direkt/dynamisch unklar); tests/test_server.py:5349 (direkt/dynamisch unklar); tests/test_server.py:5355 (Monkeypatch/getattr/sys.modules); tests/test_server.py:6731 (direkt/dynamisch unklar) |
| Funktion | `_compact_coach_library_item` | 14329 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_balanced_coach_library_items` | 14347 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `coach_workout_library` | 14357 | `coach/context.py` | P7 | offen | keine statisch gefunden |
| Funktion | `build_training_context` | 14374 | `coach/context.py` | P7 | offen | tests/test_audit_remediation.py:245 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:35 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:71 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:247 (direkt/dynamisch unklar); tests/test_provider_review.py:281 (direkt/dynamisch unklar); tests/test_server.py:3664 (direkt/dynamisch unklar); tests/test_server.py:5345 (direkt/dynamisch unklar); tests/test_server.py:5356 (direkt/dynamisch unklar); tests/test_server.py:5357 (direkt/dynamisch unklar); tests/test_server.py:5374 (direkt/dynamisch unklar); tests/test_server.py:5385 (direkt/dynamisch unklar); tests/test_server.py:5417 (direkt/dynamisch unklar); tests/test_server.py:6709 (direkt/dynamisch unklar) |
| Funktion | `context_preview` | 14414 | `coach/context.py` | P7 | offen | tests/test_server.py:5239 (direkt/dynamisch unklar); tests/test_server.py:5379 (direkt/dynamisch unklar) |
| Funktion | `intervals_performance_average` | 14470 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `performance_trend_average` | 14500 | `performance/` | P3 | offen | keine statisch gefunden |
| Funktion | `_openai_usage_summary_unlocked` | 14510 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `openai_usage_summary` | 14533 | `providers/` | P2 | offen | tests/test_server.py:8093 (direkt/dynamisch unklar); tests/test_server.py:8123 (direkt/dynamisch unklar); tests/test_server.py:8315 (direkt/dynamisch unklar); tests/test_server.py:8325 (direkt/dynamisch unklar); tests/test_server.py:8349 (direkt/dynamisch unklar); tests/test_server.py:8372 (direkt/dynamisch unklar); tests/test_server.py:8516 (direkt/dynamisch unklar); tests/test_server.py:8554 (direkt/dynamisch unklar) |
| Funktion | `_record_openai_usage_unlocked` | 14541 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `record_openai_usage` | 14570 | `providers/` | P2 | offen | tests/test_server.py:5859 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8511 (direkt/dynamisch unklar); tests/test_server.py:8552 (direkt/dynamisch unklar) |
| Funktion | `_validate_openai_response` | 14577 | `providers/` | P2 | offen | tests/test_coach_response_failure.py:100 (direkt/dynamisch unklar); tests/test_server.py:8493 (direkt/dynamisch unklar); tests/test_server.py:8496 (direkt/dynamisch unklar); tests/test_server.py:8499 (direkt/dynamisch unklar) |
| Funktion | `openai_endpoint` | 14599 | `providers/` | P2 | offen | tests/test_server.py:4815 (direkt/dynamisch unklar); tests/test_server.py:4816 (direkt/dynamisch unklar); tests/test_server.py:4818 (direkt/dynamisch unklar); tests/test_server.py:4827 (direkt/dynamisch unklar) |
| Funktion | `openai_request` | 14616 | `providers/` | P2 | offen | tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4839 (direkt/dynamisch unklar); tests/test_server.py:5462 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5471 (direkt/dynamisch unklar); tests/test_server.py:6064 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7321 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8194 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8506 (direkt/dynamisch unklar) |
| Funktion | `multipart_form_data` | 14640 | `providers/http.py` | P2 | offen | keine statisch gefunden |
| Globale Bindung | `VOICE_AUDIO_TYPES` | 14665 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `normalized_audio_type` | 14677 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `transcribe_audio` | 14681 | `providers/` | P2 | offen | tests/test_server.py:4578 (direkt/dynamisch unklar); tests/test_server.py:4798 (direkt/dynamisch unklar); tests/test_server.py:4871 (direkt/dynamisch unklar); tests/test_server.py:4873 (direkt/dynamisch unklar) |
| Funktion | `_provider_usage_summary` | 14733 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_usage_summary` | 14750 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_status` | 14755 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_record_gemini_usage` | 14761 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_content_has_function_response` | 14780 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_exchange_boundary` | 14785 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_trim_gemini_history` | 14792 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts_without_raw_media` | 14803 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_inline_media_from_history` | 14819 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history` | 14831 | `providers/` | P2 | offen | tests/test_coach_attachments.py:198 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4501 (direkt/dynamisch unklar); tests/test_server.py:4633 (direkt/dynamisch unklar) |
| Funktion | `_save_gemini_history` | 14839 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `repair_incomplete_gemini_tool_history` | 14851 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_selected_raw_attachments` | 14867 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_history_parts` | 14883 | `providers/` | P2 | offen | tests/test_server.py:4512 (direkt/dynamisch unklar); tests/test_server.py:4517 (direkt/dynamisch unklar) |
| Funktion | `_gemini_local_chat_history` | 14905 | `providers/` | P2 | offen | tests/test_coach_attachments.py:215 (direkt/dynamisch unklar); tests/test_coach_attachments.py:227 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_gemini_text` | 14927 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_tools` | 14931 | `providers/` | P2 | offen | tests/test_server.py:4673 (direkt/dynamisch unklar) |
| Funktion | `_gemini_request_payload` | 14935 | `providers/` | P2 | offen | tests/test_coach_attachments.py:160 (direkt/dynamisch unklar); tests/test_coach_attachments.py:186 (direkt/dynamisch unklar); tests/test_coach_attachments.py:190 (direkt/dynamisch unklar); tests/test_coach_attachments.py:199 (direkt/dynamisch unklar); tests/test_coach_attachments.py:232 (direkt/dynamisch unklar); tests/test_coach_attachments.py:233 (direkt/dynamisch unklar); tests/test_coach_attachments.py:70 (direkt/dynamisch unklar); tests/test_server.py:4529 (direkt/dynamisch unklar); tests/test_server.py:4542 (direkt/dynamisch unklar); tests/test_server.py:4612 (direkt/dynamisch unklar) |
| Funktion | `gemini_raw_request` | 15031 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_gemini_responses_result` | 15050 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `gemini_responses_request` | 15089 | `providers/` | P2 | offen | tests/test_server.py:4370 (direkt/dynamisch unklar); tests/test_server.py:4372 (direkt/dynamisch unklar); tests/test_server.py:4439 (direkt/dynamisch unklar); tests/test_server.py:4442 (direkt/dynamisch unklar); tests/test_server.py:4564 (direkt/dynamisch unklar); tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules) |
| Funktion | `gemini_stream_request` | 15096 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `request_ai_provider` | 15237 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_request` | 15242 | `providers/` | P2 | offen | e2e/fixture_runtime.py:60 (direkt/dynamisch unklar); tests/test_audit_remediation.py:245 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:36 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:72 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4609 (direkt/dynamisch unklar); tests/test_server.py:5463 (direkt/dynamisch unklar); tests/test_server.py:5854 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8195 (direkt/dynamisch unklar) |
| Funktion | `_openai_response_id` | 15267 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `retrieve_openai_response` | 15274 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `cancel_openai_response` | 15289 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `responses_background_request` | 15307 | `providers/` | P2 | offen | e2e/fixture_runtime.py:61 (direkt/dynamisch unklar); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:59 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5860 (direkt/dynamisch unklar) |
| Funktion | `_raise_chat_cancelled` | 15344 | `coach/context.py` | P7 | offen | tests/test_server.py:6120 (direkt/dynamisch unklar) |
| Funktion | `_notify_openai_stream_response_id` | 15349 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_forward_openai_stream_delta` | 15362 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_openai_stream_final_response` | 15370 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_consume_openai_sse_event` | 15377 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_read_openai_stream_response` | 15396 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_log_openai_stream_failure` | 15432 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_capture_openai_stream_failure` | 15450 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_app_error` | 15464 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_disconnect` | 15476 | `providers/` | P2 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_http_error` | 15487 | `providers/` | P2 | offen | tests/test_server.py:8175 (direkt/dynamisch unklar) |
| Funktion | `_handle_openai_stream_timeout` | 15504 | `coach/streams.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_handle_openai_stream_network_error` | 15520 | `coach/streams.py` | P8 | offen | keine statisch gefunden |
| Funktion | `openai_stream_request` | 15535 | `coach/streams.py` | P8 | offen | tests/test_server.py:4863 (direkt/dynamisch unklar); tests/test_server.py:8267 (direkt/dynamisch unklar); tests/test_server.py:8308 (direkt/dynamisch unklar); tests/test_server.py:8322 (direkt/dynamisch unklar); tests/test_server.py:8346 (direkt/dynamisch unklar); tests/test_server.py:8371 (direkt/dynamisch unklar); tests/test_server.py:8377 (Monkeypatch/getattr/sys.modules) |
| Funktion | `responses_stream_request` | 15612 | `coach/streams.py` | P8 | offen | e2e/fixture_runtime.py:64 (direkt/dynamisch unklar); tests/test_server.py:4414 (direkt/dynamisch unklar); tests/test_server.py:5960 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8378 (direkt/dynamisch unklar) |
| Funktion | `ensure_conversation` | 15638 | `coach/proposals.py` | P7 | offen | e2e/fixture_runtime.py:29 (direkt/dynamisch unklar); tests/test_audit_remediation.py:245 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:246 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:260 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:57 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:34 (Monkeypatch/getattr/sys.modules); tests/test_coach_response_failure.py:70 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:133 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_delete_reset_coach_conversation` | 15657 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_reset_coach_commands` | 15670 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_reset_local_coach_chat_state` | 15688 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_request_coach_operation_cancellation` | 15701 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_clear_coach_conversation_state` | 15707 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `reset_coach_chat` | 15715 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:291 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:394 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:741 (direkt/dynamisch unklar); tests/test_server.py:4642 (direkt/dynamisch unklar); tests/test_server.py:5485 (direkt/dynamisch unklar) |
| Funktion | `output_text` | 15724 | `providers/` | P2 | offen | tests/test_server.py:4354 (direkt/dynamisch unklar); tests/test_server.py:4386 (direkt/dynamisch unklar); tests/test_server.py:4420 (direkt/dynamisch unklar); tests/test_server.py:4608 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_ACTION_TTL_SECONDS` | 15728 | `coach/` | P7 | offen | tests/test_coach_review.py:257 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_ACTION_TYPES` | 15729 | `coach/` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_hash` | 15732 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_action_view` | 15736 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `duplicate_activity_delete_preview` | 15749 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `_remove_intervals_activity_from_local_snapshot` | 15774 | `activities/` | P3 | offen | keine statisch gefunden |
| Funktion | `delete_duplicate_intervals_activity` | 15798 | `activities/` | P3 | offen | tests/test_server.py:7712 (direkt/dynamisch unklar) |
| Funktion | `validated_coach_action_preview_input` | 15818 | `coach/proposals.py` | P7 | offen | tests/test_server.py:8615 (direkt/dynamisch unklar); tests/test_server.py:8626 (direkt/dynamisch unklar) |
| Funktion | `assert_duplicate_action_preview_is_current` | 15840 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `create_coach_action_preview` | 15849 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `confirm_coach_action_preview` | 15871 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:231 (direkt/dynamisch unklar); tests/test_coach_review.py:232 (direkt/dynamisch unklar); tests/test_coach_review.py:256 (direkt/dynamisch unklar); tests/test_coach_review.py:270 (direkt/dynamisch unklar); tests/test_coach_review.py:307 (direkt/dynamisch unklar); tests/test_coach_review.py:325 (direkt/dynamisch unklar); tests/test_coach_review.py:327 (direkt/dynamisch unklar); tests/test_coach_review.py:332 (direkt/dynamisch unklar); tests/test_server.py:8642 (direkt/dynamisch unklar); tests/test_server.py:8654 (direkt/dynamisch unklar) |
| Funktion | `_execute_coach_action` | 15895 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_coach_action` | 15904 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:235 (direkt/dynamisch unklar); tests/test_coach_review.py:237 (direkt/dynamisch unklar); tests/test_coach_review.py:244 (direkt/dynamisch unklar); tests/test_coach_review.py:259 (direkt/dynamisch unklar); tests/test_coach_review.py:272 (direkt/dynamisch unklar); tests/test_coach_review.py:329 (direkt/dynamisch unklar); tests/test_coach_review.py:330 (direkt/dynamisch unklar); tests/test_server.py:8643 (direkt/dynamisch unklar); tests/test_server.py:8655 (direkt/dynamisch unklar) |
| Funktion | `_coach_session_key` | 15933 | `coach/proposals.py` | P7 | offen | tests/test_coach_review.py:122 (direkt/dynamisch unklar); tests/test_coach_review.py:216 (direkt/dynamisch unklar) |
| Funktion | `_restore_coach_session_csrf_hash` | 15937 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:261 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:705 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:728 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5985 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_coach_command_receipt` | 15954 | `coach/proposals.py` | P7 | offen | tests/test_server.py:6014 (direkt/dynamisch unklar) |
| Funktion | `_merge_coach_command_receipt` | 15958 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:776 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:786 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:93 (direkt/dynamisch unklar); tests/test_server.py:6005 (direkt/dynamisch unklar) |
| Funktion | `_active_background_coach_job` | 15970 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_request` | 15987 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_background_coach_provider_settings` | 16014 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_existing_background_coach_job_response` | 16023 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_background_coach_job` | 16040 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `enqueue_background_coach_job` | 16092 | `sync/` | P6 | offen | tests/test_audit_remediation.py:252 (direkt/dynamisch unklar); tests/test_coach_attachments.py:145 (direkt/dynamisch unklar); tests/test_coach_attachments.py:165 (direkt/dynamisch unklar); tests/test_coach_attachments.py:171 (direkt/dynamisch unklar); tests/test_coach_attachments.py:178 (direkt/dynamisch unklar); tests/test_coach_attachments.py:211 (direkt/dynamisch unklar); tests/test_coach_attachments.py:212 (direkt/dynamisch unklar); tests/test_coach_attachments.py:241 (direkt/dynamisch unklar); tests/test_coach_attachments.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:262 (direkt/dynamisch unklar); tests/test_coach_attachments.py:271 (direkt/dynamisch unklar); tests/test_coach_attachments.py:282 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:696 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:717 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:736 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:771 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:784 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:91 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:21 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:54 (direkt/dynamisch unklar); tests/test_coach_review.py:120 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:60 (direkt/dynamisch unklar); tests/test_server.py:4622 (direkt/dynamisch unklar); tests/test_server.py:5871 (direkt/dynamisch unklar); tests/test_server.py:5899 (direkt/dynamisch unklar); tests/test_server.py:5920 (direkt/dynamisch unklar); tests/test_server.py:5947 (direkt/dynamisch unklar); tests/test_server.py:5974 (direkt/dynamisch unklar); tests/test_server.py:5998 (direkt/dynamisch unklar) |
| Funktion | `register_chat_stream` | 16125 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5918 (direkt/dynamisch unklar); tests/test_server.py:8386 (direkt/dynamisch unklar); tests/test_server.py:8389 (direkt/dynamisch unklar); tests/test_server.py:8403 (direkt/dynamisch unklar); tests/test_server.py:8424 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8451 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8464 (direkt/dynamisch unklar) |
| Funktion | `publish_chat_stream_event` | 16139 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_stream_events` | 16154 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5934 (direkt/dynamisch unklar); tests/test_server.py:8426 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8453 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_close_chat_provider_response` | 16163 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_attached_chat_stream` | 16172 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cancel_background_chat_job` | 16184 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `cancel_chat_stream` | 16201 | `coach/proposals.py` | P7 | offen | tests/test_audit_remediation.py:256 (direkt/dynamisch unklar); tests/test_server.py:8392 (direkt/dynamisch unklar); tests/test_server.py:8394 (direkt/dynamisch unklar); tests/test_server.py:8468 (direkt/dynamisch unklar) |
| Funktion | `unregister_chat_stream` | 16209 | `coach/proposals.py` | P7 | offen | tests/test_server.py:5942 (direkt/dynamisch unklar); tests/test_server.py:8398 (direkt/dynamisch unklar); tests/test_server.py:8409 (direkt/dynamisch unklar); tests/test_server.py:8425 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8473 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_TOOL_MAX_ROUNDS` | 16216 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:793 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `COACH_COMMAND_STALE_SECONDS` | 16217 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_CANONICAL_TOOL_NAMES` | 16218 | `coach/` | P7 | offen | keine statisch gefunden |
| Globale Bindung | `COACH_STRUCTURED_TOOLS` | 16218 | `coach/` | P7 | offen | tests/test_server.py:351 (direkt/dynamisch unklar); tests/test_server.py:407 (direkt/dynamisch unklar); tests/test_server.py:4879 (direkt/dynamisch unklar); tests/test_server.py:4882 (direkt/dynamisch unklar); tests/test_server.py:5232 (direkt/dynamisch unklar) |
| Globale Bindung | `STRUCTURED_READ_ONLY_TOOLS` | 16218 | `coach/proposals.py` | P7 | offen | tests/test_coach_dialogue.py:271 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:425 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:567 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:401 (direkt/dynamisch unklar) |
| Globale Bindung | `COACH_DIALOGUE_TOOLS` | 16218 | `coach/` | P7 | offen | tests/test_coach_dialogue.py:268 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:568 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:388 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:402 (direkt/dynamisch unklar) |
| Funktion | `coach_execution_scope` | 16227 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_scope_values` | 16235 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_coach_scope` | 16239 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_after_key` | 16244 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_snapshot` | 16255 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_target_ref` | 16280 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state_page` | 16299 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_state` | 16311 | `planning/` | P4 | offen | tests/test_coach_dialogue.py:64 (direkt/dynamisch unklar); tests/test_server.py:3044 (direkt/dynamisch unklar); tests/test_server.py:3046 (direkt/dynamisch unklar); tests/test_server.py:5498 (direkt/dynamisch unklar); tests/test_server.py:5534 (direkt/dynamisch unklar); tests/test_server.py:5557 (direkt/dynamisch unklar); tests/test_server.py:5559 (direkt/dynamisch unklar); tests/test_server.py:5575 (direkt/dynamisch unklar); tests/test_server.py:5582 (direkt/dynamisch unklar); tests/test_server.py:5596 (direkt/dynamisch unklar); tests/test_server.py:5619 (direkt/dynamisch unklar); tests/test_server.py:5644 (direkt/dynamisch unklar); tests/test_server.py:5673 (direkt/dynamisch unklar); tests/test_server.py:5693 (direkt/dynamisch unklar); tests/test_server.py:5745 (direkt/dynamisch unklar); tests/test_server.py:5758 (direkt/dynamisch unklar); tests/test_server.py:5764 (direkt/dynamisch unklar); tests/test_server.py:5793 (direkt/dynamisch unklar); tests/test_server.py:5820 (direkt/dynamisch unklar); tests/test_server.py:5823 (direkt/dynamisch unklar); tests/test_server.py:5844 (direkt/dynamisch unklar); tests/test_server.py:688 (direkt/dynamisch unklar); tests/test_server.py:701 (direkt/dynamisch unklar); tests/test_server.py:777 (direkt/dynamisch unklar); tests/test_server.py:812 (direkt/dynamisch unklar); tests/test_workout_repair.py:372 (direkt/dynamisch unklar); tests/test_workout_repair.py:489 (direkt/dynamisch unklar); tests/test_workout_repair.py:492 (direkt/dynamisch unklar); tests/test_workout_repair.py:500 (direkt/dynamisch unklar); tests/test_workout_repair.py:505 (direkt/dynamisch unklar); tests/test_workout_repair.py:508 (direkt/dynamisch unklar); tests/test_workout_repair.py:512 (direkt/dynamisch unklar); tests/test_workout_repair.py:70 (direkt/dynamisch unklar) |
| Funktion | `_structured_artifact_payload` | 16334 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_action_payload` | 16341 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_plan_limits` | 16348 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_plan_calendar` | 16366 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_stage_coach_artifact` | 16376 | `coach/proposals.py` | P7 | offen | e2e/fixture_runtime.py:71 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:563 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:839 (direkt/dynamisch unklar); tests/test_coach_review.py:162 (direkt/dynamisch unklar); tests/test_coach_review.py:173 (direkt/dynamisch unklar); tests/test_coach_review.py:294 (direkt/dynamisch unklar); tests/test_server.py:274 (direkt/dynamisch unklar); tests/test_server.py:299 (direkt/dynamisch unklar); tests/test_server.py:4548 (direkt/dynamisch unklar); tests/test_server.py:5479 (direkt/dynamisch unklar) |
| Funktion | `_validated_training_date` | 16389 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_created_training_change` | 16398 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_record_existing_training_change` | 16409 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_dates` | 16441 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_training_change_batch` | 16467 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_change` | 16487 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_training_changes` | 16511 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_revision` | 16523 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hash` | 16536 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_hashes` | 16550 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_revisions` | 16558 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_membership_update` | 16569 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_training_change_moves_bounds` | 16591 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_collect_structured_training_memberships` | 16601 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derived_structured_training_plan` | 16615 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_authorized_structured_training_plan` | 16627 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_training_plan_reference` | 16641 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_create_plan_ids` | 16649 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_derive_structured_training_plan` | 16662 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_change_rows` | 16671 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_planning_change_dependencies` | 16693 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_training_changes` | 16711 | `planning/` | P4 | offen | tests/test_server.py:4909 (direkt/dynamisch unklar); tests/test_server.py:4931 (direkt/dynamisch unklar); tests/test_server.py:4950 (direkt/dynamisch unklar); tests/test_server.py:4972 (direkt/dynamisch unklar); tests/test_server.py:4987 (direkt/dynamisch unklar); tests/test_server.py:5003 (direkt/dynamisch unklar); tests/test_server.py:5021 (direkt/dynamisch unklar); tests/test_server.py:5043 (direkt/dynamisch unklar); tests/test_server.py:5061 (direkt/dynamisch unklar); tests/test_server.py:5084 (direkt/dynamisch unklar); tests/test_server.py:5128 (direkt/dynamisch unklar); tests/test_server.py:5153 (direkt/dynamisch unklar); tests/test_server.py:5174 (direkt/dynamisch unklar); tests/test_server.py:5189 (direkt/dynamisch unklar); tests/test_server.py:5208 (direkt/dynamisch unklar); tests/test_server.py:5225 (direkt/dynamisch unklar) |
| Funktion | `_apply_structured_training_changes_in_db` | 16722 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_replacement` | 16732 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_workouts` | 16749 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_existing_state` | 16760 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replacement_entries` | 16790 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_replacement_calendar` | 16808 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_replacement_entries` | 16814 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_archive_superseded_training_plans` | 16827 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_plan` | 16845 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_copy_replacement_constraints` | 16861 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_create_replacement_units` | 16874 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_training_plan` | 16888 | `planning/` | P4 | offen | tests/test_server.py:5599 (direkt/dynamisch unklar); tests/test_server.py:5646 (direkt/dynamisch unklar); tests/test_server.py:5674 (direkt/dynamisch unklar) |
| Funktion | `_pending_plan_push_entries` | 16922 | `sync/` | P6 | offen | tests/test_coach_dialogue.py:177 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:240 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:686 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:105 (direkt/dynamisch unklar); tests/test_coach_tool_coverage.py:288 (direkt/dynamisch unklar); tests/test_server.py:332 (direkt/dynamisch unklar); tests/test_server.py:363 (direkt/dynamisch unklar); tests/test_server.py:8748 (direkt/dynamisch unklar); tests/test_server.py:881 (direkt/dynamisch unklar); tests/test_server.py:959 (direkt/dynamisch unklar); tests/test_server.py:968 (direkt/dynamisch unklar); tests/test_workout_repair.py:295 (direkt/dynamisch unklar); tests/test_workout_repair.py:391 (direkt/dynamisch unklar); tests/test_workout_repair.py:396 (direkt/dynamisch unklar); tests/test_workout_repair.py:413 (direkt/dynamisch unklar); tests/test_workout_repair.py:423 (direkt/dynamisch unklar) |
| Funktion | `_local_planning_authoritative_rows` | 16935 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_row_authoritative` | 16947 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_mark_local_planning_authoritative` | 16962 | `planning/` | P4 | offen | tests/test_server.py:372 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_mark_local_competitions_authoritative` | 16974 | `planning/` | P4 | offen | tests/test_server.py:642 (direkt/dynamisch unklar); tests/test_server.py:652 (direkt/dynamisch unklar) |
| Funktion | `_repair_manifest_rows` | 17004 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_repair_manifest_entries` | 17012 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_selection` | 17019 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_repair_manifest_workouts` | 17041 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_refresh_repair_manifest_hashes` | 17048 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_manifest` | 17054 | `coach/proposals.py` | P7 | offen | tests/test_workout_repair.py:561 (direkt/dynamisch unklar) |
| Funktion | `_enqueue_coach_plan_push` | 17072 | `planning/` | P4 | offen | tests/test_server.py:396 (Monkeypatch/getattr/sys.modules); tests/test_workout_repair.py:173 (direkt/dynamisch unklar); tests/test_workout_repair.py:201 (direkt/dynamisch unklar) |
| Funktion | `_structured_bounded_integer` | 17100 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_read_result` | 17109 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_profile_result` | 17136 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_authorized_coach_athlete_operation` | 17162 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_checkin_result` | 17167 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_activity_feedback_result` | 17173 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_activity_feedback_result` | 17187 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_save_competition_result` | 17194 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_delete_competition_result` | 17202 | `planning/` | P4 | offen | keine statisch gefunden |
| Globale Bindung | `ATHLETE_RECORD_HANDLERS` | 17209 | `athlete/` | P3 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_athlete_record_result` | 17218 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_stage_structured_training_plan` | 17225 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_training_template_result` | 17238 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_apply_library_plan_result` | 17261 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_commit_structured_training_plan` | 17275 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_persist_committed_training_plan` | 17289 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_committed_training_plan` | 17317 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_replace_structured_coach_training_plan` | 17333 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_validate_structured_training_change_scopes` | 17352 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_training_changes` | 17372 | `coach/proposals.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_plan_tool_result` | 17394 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_start_structured_provider_refresh` | 17410 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_run_structured_intervals_refresh` | 17427 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_retry_structured_intervals_refresh` | 17462 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_queue_structured_performance_refresh` | 17474 | `coach/jobs.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_without_entries` | 17489 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_validate_selected_plan_sync_entries` | 17509 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_persist_selected_plan_sync_entries` | 17535 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_plan_entries` | 17553 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_sync_structured_training_plan` | 17561 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_resolve_structured_sync_conflict` | 17582 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_sync_tool_result` | 17609 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_misc_tool_result` | 17633 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_adaptive_replan` | 17660 | `planning/` | P4 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_tool_result` | 17681 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:777 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (Monkeypatch/getattr/sys.modules); tests/test_coach_dialogue.py:97 (direkt/dynamisch unklar); tests/test_coach_review.py:104 (direkt/dynamisch unklar); tests/test_coach_review.py:165 (direkt/dynamisch unklar); tests/test_coach_review.py:166 (direkt/dynamisch unklar); tests/test_coach_review.py:176 (direkt/dynamisch unklar); tests/test_coach_review.py:186 (direkt/dynamisch unklar); tests/test_coach_review.py:202 (direkt/dynamisch unklar); tests/test_coach_review.py:209 (direkt/dynamisch unklar); tests/test_coach_review.py:210 (direkt/dynamisch unklar); tests/test_coach_review.py:212 (direkt/dynamisch unklar); tests/test_coach_review.py:82 (direkt/dynamisch unklar); tests/test_server.py:286 (direkt/dynamisch unklar); tests/test_server.py:318 (direkt/dynamisch unklar); tests/test_server.py:342 (direkt/dynamisch unklar); tests/test_server.py:375 (direkt/dynamisch unklar); tests/test_server.py:397 (direkt/dynamisch unklar); tests/test_server.py:422 (direkt/dynamisch unklar); tests/test_server.py:429 (direkt/dynamisch unklar); tests/test_server.py:469 (direkt/dynamisch unklar); tests/test_server.py:498 (direkt/dynamisch unklar); tests/test_server.py:504 (direkt/dynamisch unklar); tests/test_server.py:508 (direkt/dynamisch unklar); tests/test_server.py:5107 (direkt/dynamisch unklar); tests/test_server.py:525 (direkt/dynamisch unklar); tests/test_server.py:529 (direkt/dynamisch unklar); tests/test_server.py:5504 (direkt/dynamisch unklar); tests/test_server.py:5540 (direkt/dynamisch unklar); tests/test_server.py:5625 (direkt/dynamisch unklar); tests/test_server.py:5699 (direkt/dynamisch unklar); tests/test_server.py:5723 (direkt/dynamisch unklar); tests/test_server.py:5728 (direkt/dynamisch unklar); tests/test_server.py:5777 (direkt/dynamisch unklar); tests/test_server.py:5799 (direkt/dynamisch unklar); tests/test_server.py:666 (direkt/dynamisch unklar); tests/test_server.py:708 (direkt/dynamisch unklar); tests/test_server.py:737 (direkt/dynamisch unklar); tests/test_server.py:756 (direkt/dynamisch unklar); tests/test_server.py:785 (direkt/dynamisch unklar); tests/test_server.py:818 (direkt/dynamisch unklar); tests/test_server.py:838 (direkt/dynamisch unklar); tests/test_server.py:865 (direkt/dynamisch unklar); tests/test_server.py:891 (direkt/dynamisch unklar); tests/test_server.py:910 (direkt/dynamisch unklar); tests/test_server.py:936 (direkt/dynamisch unklar); tests/test_server.py:961 (direkt/dynamisch unklar) |
| Funktion | `_structured_authorized_operations` | 17723 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_pending_messages` | 17727 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_dialogue_command_result` | 17740 | `coach/authorization.py` | P7 | offen | tests/test_server.py:8762 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_context` | 17752 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:267 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_retry_metadata` | 17771 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_request_target` | 17787 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_scope_objects` | 17798 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_repair_scope` | 17820 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_dialogue_operation_scope` | 17835 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_action` | 17853 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:273 (direkt/dynamisch unklar) |
| Funktion | `_check_dialogue_plan_date` | 17883 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_changes` | 17889 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_artifact` | 17903 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_dialogue_plan_scope` | 17913 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_save_coach_question` | 17926 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_validate_training_patch_schedule` | 17939 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_store_training_patch_constraints` | 17956 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_training_patch` | 17969 | `coach/dialogue.py` | P7 | offen | tests/test_coach_tool_coverage.py:436 (Monkeypatch/getattr/sys.modules); tests/test_coach_tool_coverage.py:436 (direkt/dynamisch unklar); tests/test_server.py:5837 (direkt/dynamisch unklar) |
| Funktion | `_alternative_planning_steps_repaired` | 17996 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_repair_fields` | 18013 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_profile_steps_repaired` | 18018 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_matching_coach_steps_repaired` | 18027 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_steps_repaired` | 18041 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_unresolved_coach_steps` | 18054 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:230 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:232 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:510 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:522 (direkt/dynamisch unklar) |
| Funktion | `_dialogue_scope_repair_key` | 18064 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_request_binding_key` | 18077 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_plan_effect_key` | 18098 | `coach/dialogue.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_repair_key` | 18121 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_dialogue_effect_key` | 18132 | `coach/dialogue.py` | P7 | offen | tests/test_coach_dialogue.py:774 (direkt/dynamisch unklar) |
| Funktion | `_append_template_command_scope` | 18141 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_append_planning_command_scope` | 18153 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_planning_command_intent` | 18167 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_commit_planning_command` | 18175 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_planning_command` | 18190 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_claim_planning_command` | 18210 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_claimed_planning_command` | 18234 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `execute_planning_command` | 18248 | `coach/tool_execution.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_receipt` | 18259 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_attachments` | 18284 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_add_structured_coach_attachment_evidence` | 18300 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_request_payload` | 18315 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_send_structured_coach_response` | 18372 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_structured_coach_conversation` | 18400 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_coach_response` | 18430 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_invalid_structured_conversation` | 18446 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_response_retry_delay` | 18466 | `providers/` | P2 | offen | tests/test_coach_language_recovery.py:70 (direkt/dynamisch unklar); tests/test_coach_language_recovery.py:78 (direkt/dynamisch unklar) |
| Funktion | `_wait_for_coach_response_retry` | 18480 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachResponseAttemptContext` | 18492 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response_attempt` | 18502 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_response` | 18553 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_mark_resolved_coach_receipts` | 18615 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_coach_effects` | 18619 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_text` | 18624 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_pending_request` | 18642 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome_status` | 18661 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_outcome` | 18671 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_metadata` | 18697 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_cached_structured_tool_call` | 18735 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_plan_sync` | 18761 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_prepare_structured_tool_execution` | 18786 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool` | 18817 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_tool_call_failure` | 18857 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Klasse | `_StructuredCoachRoundState` | 18887 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_execute_structured_coach_tool_call` | 18907 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_function_calls` | 18965 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_record_structured_coach_tool_output` | 18969 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_followup_response` | 18985 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_run_structured_coach_tool_rounds` | 19001 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_turn_request` | 19033 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_apply_structured_coach_replay` | 19077 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_coach_final_receipt` | 19093 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_coach_final_receipt` | 19112 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_with_structured_coach_impl` | 19138 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_require_command_owner` | 19215 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `current_coach_proposals` | 19220 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:316 (direkt/dynamisch unklar); tests/test_coach_review.py:326 (direkt/dynamisch unklar) |
| Funktion | `prune_expired_coach_proposals` | 19229 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:302 (direkt/dynamisch unklar) |
| Funktion | `coach_command_receipt` | 19234 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_steps` | 19261 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_base_response` | 19279 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_effect_text` | 19308 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_structured_command_failure_response` | 19327 | `coach/service.py` | P7 | offen | tests/test_server.py:4450 (direkt/dynamisch unklar); tests/test_server.py:4465 (direkt/dynamisch unklar); tests/test_server.py:4479 (direkt/dynamisch unklar) |
| Funktion | `_persist_structured_command_failure_pending_request` | 19337 | `coach/service.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_persist_structured_command_failure` | 19352 | `coach/service.py` | P7 | offen | tests/test_provider_review.py:146 (Monkeypatch/getattr/sys.modules) |
| Funktion | `_chat_with_structured_coach` | 19384 | `coach/authorization.py` | P7 | offen | tests/test_coach_review.py:220 (direkt/dynamisch unklar) |
| Funktion | `coach_dialogue_artifact_refs` | 19399 | `coach/authorization.py` | P7 | offen | tests/test_coach_dialogue.py:564 (direkt/dynamisch unklar); tests/test_server.py:4552 (direkt/dynamisch unklar); tests/test_server.py:5490 (direkt/dynamisch unklar) |
| Funktion | `chat_stream_status` | 19412 | `coach/authorization.py` | P7 | offen | tests/test_server.py:5878 (direkt/dynamisch unklar); tests/test_server.py:5881 (direkt/dynamisch unklar); tests/test_server.py:8402 (direkt/dynamisch unklar); tests/test_server.py:8405 (direkt/dynamisch unklar); tests/test_server.py:8406 (direkt/dynamisch unklar) |
| Funktion | `_validated_chat_request` | 19431 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_recover_stale_chat_command` | 19444 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_command_state` | 19468 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_chat_provider_settings` | 19484 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `_resume_background_chat_command` | 19495 | `coach/authorization.py` | P7 | offen | keine statisch gefunden |
| Funktion | `chat_with_coach` | 19510 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:246 (direkt/dynamisch unklar); tests/test_audit_remediation.py:261 (Monkeypatch/getattr/sys.modules); tests/test_audit_remediation.py:284 (Monkeypatch/getattr/sys.modules); tests/test_coach_attachments.py:247 (direkt/dynamisch unklar); tests/test_coach_attachments.py:261 (direkt/dynamisch unklar); tests/test_coach_attachments.py:263 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:60 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:832 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:40 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:75 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:77 (direkt/dynamisch unklar); tests/test_coach_review.py:138 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:102 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:125 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:143 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:160 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:40 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:77 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:146 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5907 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5931 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5963 (direkt/dynamisch unklar); tests/test_server.py:6026 (Monkeypatch/getattr/sys.modules) |
| Funktion | `resume_interrupted_coach_jobs` | 19534 | `sync/` | P6 | offen | tests/test_server.py:4628 (direkt/dynamisch unklar) |
| Funktion | `_claim_background_coach_job` | 19575 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:253 (direkt/dynamisch unklar); tests/test_coach_attachments.py:146 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:700 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:721 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:742 (direkt/dynamisch unklar); tests/test_server.py:4627 (direkt/dynamisch unklar); tests/test_server.py:5905 (direkt/dynamisch unklar); tests/test_server.py:5924 (direkt/dynamisch unklar); tests/test_server.py:5951 (direkt/dynamisch unklar); tests/test_server.py:5980 (direkt/dynamisch unklar); tests/test_server.py:6004 (direkt/dynamisch unklar) |
| Funktion | `_requeue_background_coach_job` | 19600 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_message` | 19626 | `coach/morning.py` | P8 | offen | tests/test_coach_attachments.py:147 (direkt/dynamisch unklar) |
| Funktion | `_background_coach_stream_delta` | 19636 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_delta_callback` | 19640 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_stream_receipt` | 19648 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_background_coach_cancel_event` | 19654 | `runtime/` | P1 | offen | keine statisch gefunden |
| Funktion | `_persist_completed_morning_coach_job` | 19664 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_execute_background_coach_job` | 19681 | `sync/` | P6 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_error` | 19712 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_handle_background_coach_exception` | 19734 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_run_background_coach_job` | 19749 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:262 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:708 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:731 (direkt/dynamisch unklar); tests/test_provider_review.py:147 (direkt/dynamisch unklar); tests/test_server.py:5908 (direkt/dynamisch unklar); tests/test_server.py:5932 (direkt/dynamisch unklar); tests/test_server.py:5986 (direkt/dynamisch unklar); tests/test_server.py:6029 (direkt/dynamisch unklar) |
| Funktion | `_coach_job_worker_loop` | 19770 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `start_coach_job_worker` | 19785 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `local_now` | 19797 | `runtime/` | P1 | offen | e2e/fixture_runtime.py:70 (direkt/dynamisch unklar); tests/test_coach_dialogue.py:28 (Monkeypatch/getattr/sys.modules); tests/test_coach_review.py:281 (direkt/dynamisch unklar); tests/test_coach_review.py:282 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:113 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:132 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:184 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:196 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:210 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:228 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:23 (Monkeypatch/getattr/sys.modules); tests/test_diagnostic_followups.py:245 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:66 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:90 (direkt/dynamisch unklar); tests/test_server.py:1154 (direkt/dynamisch unklar); tests/test_server.py:1538 (direkt/dynamisch unklar); tests/test_server.py:1554 (direkt/dynamisch unklar); tests/test_server.py:1555 (direkt/dynamisch unklar); tests/test_server.py:1576 (direkt/dynamisch unklar); tests/test_server.py:1594 (direkt/dynamisch unklar); tests/test_server.py:1613 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1626 (direkt/dynamisch unklar); tests/test_server.py:1663 (direkt/dynamisch unklar); tests/test_server.py:1671 (direkt/dynamisch unklar); tests/test_server.py:1711 (direkt/dynamisch unklar); tests/test_server.py:2527 (direkt/dynamisch unklar); tests/test_server.py:2639 (direkt/dynamisch unklar); tests/test_server.py:2704 (direkt/dynamisch unklar); tests/test_server.py:2714 (direkt/dynamisch unklar); tests/test_server.py:2892 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2952 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2982 (Monkeypatch/getattr/sys.modules); tests/test_server.py:2991 (direkt/dynamisch unklar); tests/test_server.py:3479 (direkt/dynamisch unklar); tests/test_server.py:3498 (direkt/dynamisch unklar); tests/test_server.py:3530 (direkt/dynamisch unklar); tests/test_server.py:3555 (direkt/dynamisch unklar); tests/test_server.py:3645 (direkt/dynamisch unklar); tests/test_server.py:3646 (direkt/dynamisch unklar); tests/test_server.py:3690 (direkt/dynamisch unklar); tests/test_server.py:493 (direkt/dynamisch unklar); tests/test_server.py:5247 (direkt/dynamisch unklar); tests/test_server.py:5296 (direkt/dynamisch unklar); tests/test_server.py:5313 (direkt/dynamisch unklar); tests/test_server.py:5335 (direkt/dynamisch unklar); tests/test_server.py:5362 (direkt/dynamisch unklar); tests/test_server.py:5394 (direkt/dynamisch unklar); tests/test_server.py:6069 (direkt/dynamisch unklar); tests/test_server.py:7403 (direkt/dynamisch unklar); tests/test_server.py:7721 (direkt/dynamisch unklar); tests/test_server.py:8503 (direkt/dynamisch unklar); tests/test_workout_text.py:14 (Monkeypatch/getattr/sys.modules) |
| Funktion | `daily_sync_due` | 19806 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:152 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1897 (direkt/dynamisch unklar); tests/test_server.py:1898 (direkt/dynamisch unklar); tests/test_server.py:1899 (direkt/dynamisch unklar) |
| Funktion | `mark_daily_sync` | 19814 | `sync/scheduler.py` | P8 | offen | tests/test_server.py:1896 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_date` | 19822 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:24 (direkt/dynamisch unklar) |
| Funktion | `morning_checkin_state` | 19827 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:207 (direkt/dynamisch unklar) |
| Globale Bindung | `MORNING_CHECKIN_PROMPT` | 19838 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Globale Bindung | `MORNING_GARMIN_SYNC_DAYS` | 19850 | `sync/garmin.py` | P6 | offen | tests/test_diagnostic_followups.py:107 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:129 (direkt/dynamisch unklar); tests/test_server.py:4159 (direkt/dynamisch unklar) |
| Funktion | `_start_morning_checkin` | 19853 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_morning_checkin_garmin_ready` | 19860 | `sync/scheduler.py` | P8 | offen | tests/test_server.py:4157 (direkt/dynamisch unklar) |
| Funktion | `_morning_checkin_attempt` | 19877 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_wait_for_morning_intervals_sync` | 19883 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_complete_morning_checkin` | 19891 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `run_morning_checkin` | 19903 | `coach/morning.py` | P8 | offen | tests/test_audit_remediation.py:285 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:104 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:127 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:145 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:162 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:79 (direkt/dynamisch unklar) |
| Funktion | `_reserve_morning_checkin` | 19935 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_run_scheduled_morning_checkin` | 19956 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_start_scheduled_morning_checkin` | 19970 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_morning_checkin` | 19983 | `coach/morning.py` | P8 | offen | tests/test_diagnostic_followups.py:171 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:41 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:43 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:46 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:49 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:57 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:61 (direkt/dynamisch unklar) |
| Funktion | `bootstrap_provider_states` | 20002 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `public_bootstrap` | 20036 | `http_api/` | P10 | offen | tests/test_diagnostic_followups.py:29 (direkt/dynamisch unklar); tests/test_server.py:1721 (direkt/dynamisch unklar); tests/test_server.py:1735 (direkt/dynamisch unklar); tests/test_server.py:1780 (direkt/dynamisch unklar); tests/test_server.py:1862 (direkt/dynamisch unklar); tests/test_server.py:8543 (direkt/dynamisch unklar) |
| Funktion | `public_plan_state` | 20110 | `http_api/` | P10 | offen | tests/test_server.py:1168 (direkt/dynamisch unklar); tests/test_server.py:2984 (direkt/dynamisch unklar) |
| Funktion | `public_performance_state` | 20146 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_feedback_state` | 20151 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `public_weather_state` | 20155 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:96 (direkt/dynamisch unklar); tests/test_server.py:1218 (direkt/dynamisch unklar) |
| Funktion | `public_state` | 20162 | `http_api/` | P10 | offen | tests/test_server.py:1190 (direkt/dynamisch unklar); tests/test_server.py:1198 (direkt/dynamisch unklar); tests/test_server.py:1621 (direkt/dynamisch unklar); tests/test_server.py:1666 (direkt/dynamisch unklar); tests/test_server.py:2333 (direkt/dynamisch unklar); tests/test_server.py:3695 (direkt/dynamisch unklar); tests/test_server.py:7332 (direkt/dynamisch unklar); tests/test_server.py:8543 (direkt/dynamisch unklar) |
| Funktion | `recent_log_entries` | 20274 | `observability.py` | P1 | offen | tests/test_server.py:7866 (direkt/dynamisch unklar); tests/test_server.py:7918 (direkt/dynamisch unklar); tests/test_server.py:8032 (direkt/dynamisch unklar); tests/test_server.py:8063 (direkt/dynamisch unklar); tests/test_server.py:8314 (direkt/dynamisch unklar); tests/test_server.py:8350 (direkt/dynamisch unklar); tests/test_server.py:8599 (direkt/dynamisch unklar) |
| Globale Bindung | `SETTINGS_SECRET_KEYS` | 20291 | `observability.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_VALUE_KEYS` | 20292 | `settings.py` | P1 | offen | keine statisch gefunden |
| Globale Bindung | `SETTINGS_KEYS` | 20293 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_submitted_settings` | 20296 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_read_settings_file` | 20311 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_rewrite_settings_lines` | 20318 | `settings.py` | P1 | offen | keine statisch gefunden |
| Funktion | `save_settings` | 20338 | `settings.py` | P1 | offen | tests/test_server.py:6659 (direkt/dynamisch unklar); tests/test_server.py:6675 (direkt/dynamisch unklar) |
| Funktion | `_diagnostic_frame` | 20353 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_error_metadata` | 20369 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_command_steps` | 20390 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `_diagnostic_history_entry` | 20404 | `observability.py` | P1 | offen | keine statisch gefunden |
| Funktion | `coach_diagnostic_history` | 20420 | `observability.py` | P1 | offen | tests/test_coach_dialogue.py:497 (direkt/dynamisch unklar); tests/test_coach_response_failure.py:91 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:345 (direkt/dynamisch unklar) |
| Funktion | `diagnostic_report` | 20429 | `observability.py` | P1 | offen | tests/test_diagnostic_followups.py:32 (direkt/dynamisch unklar); tests/test_diagnostic_followups.py:332 (direkt/dynamisch unklar); tests/test_server.py:7781 (direkt/dynamisch unklar); tests/test_server.py:7783 (direkt/dynamisch unklar); tests/test_server.py:7784 (direkt/dynamisch unklar); tests/test_server.py:7831 (direkt/dynamisch unklar); tests/test_server.py:7894 (direkt/dynamisch unklar); tests/test_server.py:7909 (direkt/dynamisch unklar); tests/test_server.py:8716 (direkt/dynamisch unklar) |
| Funktion | `privacy_export` | 20492 | `backup/` | P9 | offen | tests/test_coach_attachments.py:156 (direkt/dynamisch unklar); tests/test_server.py:1401 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_EXPORT_FORMAT_VERSION` | 20542 | `backup/` | P9 | offen | keine statisch gefunden |
| Globale Bindung | `PRIVACY_EXPORT_JSONL_FILES` | 20543 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_payload` | 20567 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_jsonl_rows` | 20571 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_workout_library` | 20582 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_planned_units` | 20586 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_export_application_state` | 20596 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_privacy_export_file` | 20604 | `backup/` | P9 | offen | tests/test_audit_remediation.py:170 (direkt/dynamisch unklar); tests/test_server.py:1416 (direkt/dynamisch unklar) |
| Globale Bindung | `_configure_cipher` | 20743 | `db/manager.py` | P1 | offen | tests/test_server.py:6598 (direkt/dynamisch unklar); tests/test_server.py:6611 (direkt/dynamisch unklar) |
| Funktion | `_checkpoint_database_locked` | 20746 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `database_backup_bytes` | 20759 | `backup/` | P9 | offen | tests/test_audit_remediation.py:274 (direkt/dynamisch unklar); tests/test_server.py:6587 (direkt/dynamisch unklar) |
| Funktion | `stream_database_backup` | 20768 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `stream_privacy_export` | 20789 | `coach/morning.py` | P8 | offen | tests/test_server.py:1444 (direkt/dynamisch unklar) |
| Funktion | `restore_database_backup` | 20800 | `backup/` | P9 | offen | tests/test_audit_remediation.py:276 (direkt/dynamisch unklar); tests/test_server.py:6588 (direkt/dynamisch unklar); tests/test_server.py:6604 (direkt/dynamisch unklar); tests/test_server.py:6617 (direkt/dynamisch unklar) |
| Funktion | `_temporary_restore_database` | 20805 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_connection` | 20814 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_validate_restore_database` | 20831 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_replace_database_with_restore` | 20843 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_resume_after_database_restore` | 20861 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `_restore_database_backup` | 20868 | `backup/` | P9 | offen | keine statisch gefunden |
| Funktion | `delete_remote_conversation` | 20889 | `coach/morning.py` | P8 | offen | tests/test_server.py:1484 (Monkeypatch/getattr/sys.modules); tests/test_server.py:1500 (Monkeypatch/getattr/sys.modules); tests/test_server.py:4641 (Monkeypatch/getattr/sys.modules); tests/test_server.py:5484 (Monkeypatch/getattr/sys.modules); tests/test_server.py:8662 (Monkeypatch/getattr/sys.modules) |
| Globale Bindung | `PRIVACY_DELETE_SCOPE` | 20902 | `coach/morning.py` | P8 | offen | tests/test_server.py:1493 (direkt/dynamisch unklar); tests/test_server.py:1497 (direkt/dynamisch unklar); tests/test_server.py:1503 (direkt/dynamisch unklar) |
| Globale Bindung | `PRIVACY_REMOTE_SCOPE` | 20917 | `coach/morning.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_privacy_delete_counts` | 20924 | `privacy.py` | P9 | offen | keine statisch gefunden |
| Funktion | `privacy_delete_preview` | 20931 | `privacy.py` | P9 | offen | tests/test_server.py:1496 (direkt/dynamisch unklar) |
| Funktion | `delete_local_data` | 20946 | `privacy.py` | P9 | offen | tests/test_audit_remediation.py:101 (direkt/dynamisch unklar); tests/test_provider_review.py:115 (direkt/dynamisch unklar); tests/test_provider_review.py:136 (direkt/dynamisch unklar); tests/test_provider_review.py:145 (direkt/dynamisch unklar); tests/test_provider_review.py:163 (direkt/dynamisch unklar); tests/test_server.py:1485 (direkt/dynamisch unklar); tests/test_server.py:1501 (direkt/dynamisch unklar); tests/test_server.py:8663 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_COOKIE` | 20975 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `CSRF_COOKIE` | 20976 | `http_api/` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_TTL_SECONDS` | 20977 | `http_api/auth.py` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_TOUCH_INTERVAL_SECONDS` | 20978 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_INTERVAL_SECONDS` | 20979 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `SESSION_CLEANUP_BATCH_SIZE` | 20980 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1316 (direkt/dynamisch unklar); tests/test_server.py:1324 (direkt/dynamisch unklar) |
| Globale Bindung | `SESSION_LAST_CLEANUP_MONOTONIC` | 20981 | `http_api/auth.py` | P10 | offen | tests/test_server.py:1321 (direkt/dynamisch unklar) |
| Globale Bindung | `RATE_LIMIT_CLEANUP_INTERVAL_SECONDS` | 20982 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_CLEANUP_BATCH_SIZE` | 20983 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_BUCKET_MAX_AGE_SECONDS` | 20984 | `http_api/auth.py` | P10 | offen | keine statisch gefunden |
| Globale Bindung | `RATE_LIMIT_LAST_CLEANUP_MONOTONIC` | 20985 | `http_api/auth.py` | P10 | offen | tests/test_server.py:7996 (direkt/dynamisch unklar) |
| Funktion | `client_ip` | 20988 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `allow_rate` | 20992 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:33 (direkt/dynamisch unklar); tests/test_provider_review.py:184 (Monkeypatch/getattr/sys.modules); tests/test_provider_review.py:323 (Monkeypatch/getattr/sys.modules); tests/test_server.py:7998 (direkt/dynamisch unklar) |
| Funktion | `cookie_value` | 21017 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `session_token_hash` | 21026 | `http_api/` | P10 | offen | tests/support.py:134 (direkt/dynamisch unklar); tests/test_coach_review.py:116 (direkt/dynamisch unklar); tests/test_server.py:1280 (direkt/dynamisch unklar); tests/test_server.py:1309 (direkt/dynamisch unklar); tests/test_server.py:1312 (direkt/dynamisch unklar); tests/test_server.py:1361 (direkt/dynamisch unklar); tests/test_server.py:1368 (direkt/dynamisch unklar); tests/test_server.py:5893 (direkt/dynamisch unklar); tests/test_server.py:5897 (direkt/dynamisch unklar); tests/test_server.py:5912 (direkt/dynamisch unklar); tests/test_server.py:5916 (direkt/dynamisch unklar) |
| Funktion | `session_timestamp` | 21030 | `http_api/` | P10 | offen | keine statisch gefunden |
| Funktion | `cleanup_expired_sessions` | 21040 | `http_api/` | P10 | offen | tests/test_server.py:1322 (direkt/dynamisch unklar) |
| Funktion | `readiness_state` | 21055 | `performance/` | P3 | offen | tests/test_server.py:7961 (direkt/dynamisch unklar); tests/test_server.py:7971 (direkt/dynamisch unklar); tests/test_server.py:7979 (direkt/dynamisch unklar); tests/test_server.py:7986 (direkt/dynamisch unklar) |
| Funktion | `authenticated_session` | 21097 | `http_api/` | P10 | offen | tests/test_server.py:1286 (direkt/dynamisch unklar); tests/test_server.py:1289 (direkt/dynamisch unklar); tests/test_server.py:1310 (direkt/dynamisch unklar); tests/test_server.py:1343 (direkt/dynamisch unklar); tests/test_server.py:1380 (direkt/dynamisch unklar); tests/test_server.py:3391 (direkt/dynamisch unklar) |
| Funktion | `login_user` | 21123 | `observability.py` | P1 | offen | tests/test_provider_review.py:187 (direkt/dynamisch unklar); tests/test_provider_review.py:190 (direkt/dynamisch unklar); tests/test_provider_review.py:326 (direkt/dynamisch unklar); tests/test_server.py:3388 (direkt/dynamisch unklar) |
| Funktion | `logout_user` | 21142 | `observability.py` | P1 | offen | tests/test_server.py:1379 (direkt/dynamisch unklar) |
| Funktion | `require_auth` | 21150 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:89 (direkt/dynamisch unklar) |
| Funktion | `require_csrf` | 21162 | `http_api/` | P10 | offen | tests/test_server.py:1361 (direkt/dynamisch unklar); tests/test_server.py:1368 (direkt/dynamisch unklar); tests/test_server.py:3393 (direkt/dynamisch unklar) |
| Funktion | `session_cookie_headers` | 21168 | `http_api/` | P10 | offen | tests/test_server.py:1261 (direkt/dynamisch unklar); tests/test_server.py:1267 (direkt/dynamisch unklar) |
| Klasse | `RequestHandler` | 21181 | `http_api/` | P10 | offen | e2e/fixture_runtime.py:102 (direkt/dynamisch unklar); e2e/fixture_runtime.py:85 (direkt/dynamisch unklar); tests/test_audit_remediation.py:192 (direkt/dynamisch unklar); tests/test_server.py:1464 (direkt/dynamisch unklar); tests/test_server.py:1761 (direkt/dynamisch unklar); tests/test_server.py:7509 (direkt/dynamisch unklar); tests/test_server.py:7519 (direkt/dynamisch unklar); tests/test_server.py:7525 (direkt/dynamisch unklar); tests/test_server.py:7535 (direkt/dynamisch unklar); tests/test_server.py:7547 (direkt/dynamisch unklar); tests/test_server.py:7552 (direkt/dynamisch unklar); tests/test_server.py:7556 (direkt/dynamisch unklar); tests/test_server.py:7559 (direkt/dynamisch unklar); tests/test_server.py:7565 (direkt/dynamisch unklar); tests/test_server.py:7575 (direkt/dynamisch unklar); tests/test_server.py:7582 (direkt/dynamisch unklar); tests/test_server.py:7589 (direkt/dynamisch unklar); tests/test_server.py:7596 (direkt/dynamisch unklar); tests/test_server.py:8415 (direkt/dynamisch unklar); tests/test_server.py:8438 (direkt/dynamisch unklar) |
| Klasse | `CoachHTTPServer` | 21861 | `http_api/` | P10 | offen | tests/test_audit_remediation.py:192 (direkt/dynamisch unklar) |
| Funktion | `daily_sync_loop` | 21866 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_scheduler_garmin_configured` | 21879 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_weather_job` | 21883 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_calendar_job` | 21889 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_garmin_job` | 21895 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_schedule_daily_intervals_job` | 21901 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `schedule_daily_sync_jobs` | 21909 | `sync/scheduler.py` | P8 | offen | tests/test_audit_remediation.py:153 (direkt/dynamisch unklar) |
| Funktion | `_startup_historical_backfill_payload` | 21916 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_calendar_job` | 21930 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_intervals_jobs` | 21935 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_garmin_jobs` | 21947 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `_enqueue_startup_weather_job` | 21959 | `sync/scheduler.py` | P8 | offen | keine statisch gefunden |
| Funktion | `enqueue_startup_sync_jobs` | 21964 | `sync/` | P6 | offen | tests/test_server.py:975 (direkt/dynamisch unklar); tests/test_server.py:984 (direkt/dynamisch unklar) |
| Funktion | `main` | 21972 | `server.py / Composition Root` | P11 | offen | e2e/fixture_runtime.py:103 (direkt/dynamisch unklar) |

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
| `coach/authorization.py` | 60 |
| `coach/context.py` | 20 |
| `coach/conversation.py` | 8 |
| `coach/dialogue.py` | 18 |
| `coach/jobs.py` | 6 |
| `coach/morning.py` | 33 |
| `coach/proposals.py` | 52 |
| `coach/service.py` | 6 |
| `coach/streams.py` | 7 |
| `coach/tool_execution.py` | 8 |
| `config.py` | 8 |
| `db/` | 22 |
| `db/manager.py` | 6 |
| `db/schema.py` | 1 |
| `errors.py` | 20 |
| `history/` | 34 |
| `http_api/` | 43 |
| `http_api/auth.py` | 14 |
| `http_api/pagination.py` | 9 |
| `observability.py` | 57 |
| `performance/` | 56 |
| `planning/` | 272 |
| `planning/competitions.py` | 64 |
| `privacy.py` | 4 |
| `providers/` | 105 |
| `providers/calendar.py` | 45 |
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
| `weather/` | 55 |

## Grenzen und offene Unsicherheiten

- AST-Aufrufauflösung erfasst nur direkte lokale Aufrufe; `getattr`, `globals()`, `sys.modules`, dekoratorbasierte Registrierung und Callback-Injektion benötigen eine manuelle Nachprüfung.
- Ein Name kann in mehreren Kategorien mit derselben Schreibweise vorkommen; Referenzzählungen sind deshalb namensbasiert und zeigen Ortsangaben, nicht vermeintliche Laufzeitidentität.
- Die Tabelle enthält bewusst auch Importbindungen, damit Rückimporte, spätere Re-Exports und der endgültige Composition-Root-Inhalt überprüfbar bleiben.
- Offene Zielzuordnungen müssen vor dem jeweiligen Umzug fachlich entschieden werden; sie gelten nicht als erledigt.
